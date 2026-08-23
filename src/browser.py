"""Generic, config-driven Playwright step executor.

Reads an ordered list of steps from config/selectors.yaml and plays them back
against the India Post MIS reports portal: login -> set date range -> pick
customer ID -> submit -> capture the downloaded file.

Keeping the selectors in YAML (rather than hardcoded in Python) means the
script doesn't need to change once the real field IDs are known — only
config/selectors.yaml does.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pyotp
import yaml
from playwright.sync_api import Page, sync_playwright

logger = logging.getLogger(__name__)

RUNTIME_VALUE_KEYS = ("username", "password", "totp_secret", "from_date", "to_date", "customer_id")


class SelectorNotConfiguredError(RuntimeError):
    """Raised when a step in selectors.yaml still has a "TODO" selector."""


def load_steps(selectors_path: Path) -> list[dict[str, Any]]:
    if not selectors_path.exists():
        raise FileNotFoundError(
            f"{selectors_path} not found. Copy config/selectors.example.yaml to "
            "config/selectors.yaml and fill in real selectors (see that file's "
            "comments, and scripts/discover_form.py)."
        )
    data = yaml.safe_load(selectors_path.read_text())
    steps = data.get("steps", [])
    if not steps:
        raise ValueError(f"{selectors_path} has no steps defined.")
    return steps


def _run_step(page: Page, step: dict[str, Any], runtime_values: dict[str, str], download_dir: Path) -> Path | None:
    action = step["action"]
    name = step.get("name", "<unnamed>")
    selector = step.get("selector")

    if action != "wait_for_load" and selector == "TODO":
        raise SelectorNotConfiguredError(
            f"Step '{name}' still has selector: TODO in config/selectors.yaml. "
            "Run scripts/discover_form.py and fill in the real selector."
        )

    value = None
    if step.get("value_from"):
        key = step["value_from"]
        if key not in runtime_values:
            raise KeyError(f"Step '{name}' references unknown value_from '{key}'")
        value = runtime_values[key]

    logger.info("Step %s: %s(%s)", name, action, selector or "")

    if action == "fill":
        page.fill(selector, value or "")
    elif action == "select":
        try:
            page.select_option(selector, label=value)
        except Exception:
            page.select_option(selector, value=value)
    elif action == "click":
        page.click(selector)
    elif action == "fill_totp":
        # Single-input TOTP form: generate the 6-digit code at the moment we
        # fill it (codes rotate every 30s) rather than earlier in the run.
        code = pyotp.TOTP(value).now()
        page.fill(selector, code)
    elif action == "fill_totp_digits":
        # Segmented TOTP form: one text box per digit, no id/name on the
        # boxes, with a hidden field mirroring the combined value via the
        # boxes' own input-event JS. Typing into each box (rather than
        # setting the hidden field directly) keeps that sync logic intact.
        code = pyotp.TOTP(value).now()
        boxes = page.query_selector_all(selector)
        if len(boxes) != len(code):
            raise RuntimeError(
                f"Step '{name}': expected {len(code)} OTP digit boxes but found "
                f"{len(boxes)} matching selector '{selector}'"
            )
        for box, digit in zip(boxes, code):
            box.fill(digit)
    elif action == "click_and_download":
        with page.expect_download() as download_info:
            page.click(selector)
        download = download_info.value
        download_dir.mkdir(parents=True, exist_ok=True)
        dest = download_dir / download.suggested_filename
        download.save_as(dest)
        logger.info("Downloaded report to %s", dest)
        return dest
    elif action == "wait_for_load":
        # Not "networkidle": this portal polls continuously in the
        # background (e.g. a "Check Network Speed" widget) and would never
        # be considered idle, so wait_for_load would hang/timeout forever.
        page.wait_for_load_state("load")
    elif action == "wait_for_selector":
        page.wait_for_selector(selector)
    else:
        raise ValueError(f"Unknown action '{action}' in step '{name}'")
    return None


def run_pipeline_steps(
    url: str,
    selectors_path: Path,
    download_dir: Path,
    headless: bool,
    username: str,
    password: str,
    totp_secret: str,
    from_date: str,
    to_date: str,
    customer_id: str,
) -> Path:
    """Executes the configured steps and returns the path to the downloaded report."""
    steps = load_steps(selectors_path)
    runtime_values = {
        "username": username,
        "password": password,
        "totp_secret": totp_secret,
        "from_date": from_date,
        "to_date": to_date,
        "customer_id": customer_id,
    }

    downloaded_path: Path | None = None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            page = browser.new_page(accept_downloads=True)
            # This portal's SPA can take a while to render after the OAuth
            # login redirect (background network-speed checks, heavy menu
            # system) — the default 30s auto-wait on fill/click is too
            # tight for that step.
            page.set_default_timeout(60_000)
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            for step in steps:
                result = _run_step(page, step, runtime_values, download_dir)
                if result is not None:
                    downloaded_path = result
        finally:
            browser.close()

    if downloaded_path is None:
        raise RuntimeError(
            "No download was captured. Make sure one step in selectors.yaml "
            "uses action: click_and_download on the actual submit/export button."
        )
    return downloaded_path
