"""Loads runtime settings from .env (and CLI overrides applied by callers)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    url: str
    username: str
    password: str
    customer_id: str
    download_dir: Path
    processed_dir: Path
    headless: bool
    selectors_path: Path

    @classmethod
    def load(cls, env_file: Path | None = None) -> "Settings":
        load_dotenv(dotenv_path=env_file or ROOT_DIR / ".env")

        def _path(env_var: str, default: str) -> Path:
            p = Path(os.getenv(env_var, default))
            return p if p.is_absolute() else ROOT_DIR / p

        return cls(
            url=os.getenv("INDIAPOST_URL", "https://app.indiapost.gov.in/misreports/crm-last-event"),
            username=os.getenv("INDIAPOST_USERNAME", ""),
            password=os.getenv("INDIAPOST_PASSWORD", ""),
            customer_id=os.getenv("INDIAPOST_CUSTOMER_ID", ""),
            download_dir=_path("DOWNLOAD_DIR", "./data/raw"),
            processed_dir=_path("PROCESSED_DIR", "./data/processed"),
            headless=os.getenv("HEADLESS", "true").strip().lower() not in ("false", "0", "no"),
            selectors_path=ROOT_DIR / "config" / "selectors.yaml",
        )
