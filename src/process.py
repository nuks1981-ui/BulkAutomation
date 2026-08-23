"""Config-driven pandas pipeline: filter/reshape -> aggregate -> split -> merge -> export.

Behaviour is entirely driven by config/pipeline.yaml so the raw CSV's real
column names/business rules can be plugged in later without touching this
code.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

_OPS = {
    "eq": lambda s, v: s == v,
    "ne": lambda s, v: s != v,
    "gt": lambda s, v: s > v,
    "gte": lambda s, v: s >= v,
    "lt": lambda s, v: s < v,
    "lte": lambda s, v: s <= v,
    "in": lambda s, v: s.isin(v),
    "contains": lambda s, v: s.astype(str).str.contains(str(v), case=False, na=False),
    "not_null": lambda s, v: s.notna(),
}


def load_pipeline_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Copy config/pipeline.example.yaml to "
            "config/pipeline.yaml and adjust it to the real report columns."
        )
    return yaml.safe_load(path.read_text())


def load_raw(raw_path: Path) -> pd.DataFrame:
    if raw_path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(raw_path)
    return pd.read_csv(raw_path)


def apply_columns(df: pd.DataFrame, columns_cfg: dict[str, str] | None) -> pd.DataFrame:
    if not columns_cfg:
        return df
    missing = [c for c in columns_cfg if c not in df.columns]
    if missing:
        raise KeyError(
            f"pipeline.yaml 'columns' references columns not present in the "
            f"downloaded report: {missing}. Actual columns: {list(df.columns)}"
        )
    return df[list(columns_cfg.keys())].rename(columns=columns_cfg)


def apply_filters(df: pd.DataFrame, filters_cfg: list[dict[str, Any]] | None) -> pd.DataFrame:
    for f in filters_cfg or []:
        col, op, value = f["column"], f["op"], f.get("value")
        if col not in df.columns:
            raise KeyError(f"Filter references unknown column '{col}'. Actual columns: {list(df.columns)}")
        if op not in _OPS:
            raise ValueError(f"Unknown filter op '{op}'. Valid ops: {list(_OPS)}")
        df = df[_OPS[op](df[col], value)]
    return df


def merge_external(df: pd.DataFrame, merge_cfg: dict[str, Any] | None, base_dir: Path) -> pd.DataFrame:
    if not merge_cfg or not merge_cfg.get("enabled"):
        return df
    ext_path = Path(merge_cfg["path"])
    if not ext_path.is_absolute():
        ext_path = base_dir / ext_path
    if not ext_path.exists():
        raise FileNotFoundError(f"Merge source not found: {ext_path}")
    ext_df = pd.read_excel(ext_path) if ext_path.suffix.lower() in (".xlsx", ".xls") else pd.read_csv(ext_path)
    return df.merge(
        ext_df,
        left_on=merge_cfg["left_on"],
        right_on=merge_cfg["right_on"],
        how=merge_cfg.get("how", "left"),
    )


def build_summary(df: pd.DataFrame, aggregate_cfg: dict[str, Any] | None) -> pd.DataFrame | None:
    if not aggregate_cfg or not aggregate_cfg.get("group_by"):
        return None
    group_by = aggregate_cfg["group_by"]
    metrics = aggregate_cfg.get("metrics") or {}
    missing = [c for c in group_by if c not in df.columns]
    if missing:
        raise KeyError(f"aggregate.group_by references unknown columns: {missing}")
    if metrics:
        return df.groupby(group_by).agg(metrics).reset_index()
    return df.groupby(group_by).size().reset_index(name="count")


def _safe_filename(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(value)).strip("_") or "unknown"


def export(
    df: pd.DataFrame,
    summary_df: pd.DataFrame | None,
    split_by: str | None,
    output_cfg: dict[str, Any],
    processed_dir: Path,
    run_tag: str,
) -> list[Path]:
    processed_dir.mkdir(parents=True, exist_ok=True)
    fmt = output_cfg.get("format", "xlsx")
    prefix = output_cfg.get("filename_prefix", "report")

    groups: list[tuple[str | None, pd.DataFrame]]
    if split_by:
        if split_by not in df.columns:
            raise KeyError(f"split_by references unknown column '{split_by}'")
        groups = [(str(k), g) for k, g in df.groupby(split_by)]
    else:
        groups = [(None, df)]

    written: list[Path] = []
    for key, chunk in groups:
        suffix = f"_{_safe_filename(key)}" if key is not None else ""
        filename = f"{prefix}_{run_tag}{suffix}.{fmt}"
        out_path = processed_dir / filename

        if fmt == "csv":
            chunk.to_csv(out_path, index=False)
        else:
            with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
                chunk.to_excel(writer, sheet_name="Data", index=False)
                if summary_df is not None:
                    summary_df.to_excel(writer, sheet_name="Summary", index=False)
        written.append(out_path)

    return written


def run(
    raw_path: Path,
    pipeline_config_path: Path,
    processed_dir: Path,
    run_tag: str,
) -> list[Path]:
    cfg = load_pipeline_config(pipeline_config_path)

    df = load_raw(raw_path)
    df = apply_columns(df, cfg.get("columns"))
    df = apply_filters(df, cfg.get("filters"))
    df = merge_external(df, cfg.get("merge"), base_dir=pipeline_config_path.parent.parent)
    summary_df = build_summary(df, cfg.get("aggregate"))

    return export(
        df=df,
        summary_df=summary_df,
        split_by=cfg.get("split_by"),
        output_cfg=cfg.get("output", {}),
        processed_dir=processed_dir,
        run_tag=run_tag,
    )
