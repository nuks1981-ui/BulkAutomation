#!/usr/bin/env python3
"""Run this LOCALLY (on a machine that can reach app.indiapost.gov.in) to
capture the real field names/ids/labels on the login and report-filter pages.

It opens a real, visible Chromium window. You log in and click through to
the report screen YOURSELF (this handles any CAPTCHA and confirms your
credentials work). At each checkpoint you press Enter in this terminal, and
the script dumps every input/select/textarea/button on the current page to
a JSON file under data/discovery/, plus a screenshot.

Send me (or paste back) the contents of data/discovery/*.json and I'll fill
in config/selectors.yaml with the real selectors for you.

Usage:
    python scripts/discover_form.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT_DIR / "data" / "discovery"

DUMP_JS = """
() => {
  const describe = (el) => {
    const label =
      (el.labels && el.labels[0] && el.labels[0].innerText.trim()) ||
      el.getAttribute('aria-label') ||
      el.placeholder ||
      (el.closest('label') && el.closest('label').innerText.trim()) ||
      null;
    const info = {
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type'),
      id: el.id || null,
      name: el.getAttribute('name'),
      label,
      placeholder: el.getAttribute('placeholder'),
      value: 'value' in el ? el.value : null,
      text: el.tagName.toLowerCase() === 'button' || el.getAttribute('type') === 'submit'
        ? el.innerText.trim()
        : null,
    };
    if (el.tagName.toLowerCase() === 'select') {
      info.options = Array.from(el.options).map(o => ({ value: o.value, label: o.text }));
    }
    return info;
  };
  const nodes = Array.from(document.querySelectorAll('input, select, textarea, button, [role="button"]'));
  return nodes.map(describe);
}
"""


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "page"


def safe_evaluate(page, script: str, retries: int = 5, delay_seconds: float = 1.5):
    """Retries page.evaluate() to ride out redirects/reloads that destroy the
    JS execution context mid-call (common right after login or navigation)."""
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            page.wait_for_load_state("load", timeout=10_000)
        except Exception:
            pass  # page may already be settled; evaluate() below is the real check
        try:
            return page.evaluate(script)
        except Exception as e:
            last_error = e
            print(f"  (page still settling, retry {attempt}/{retries}...)")
            time.sleep(delay_seconds)
    raise RuntimeError(f"Page never settled after {retries} retries") from last_error


def dump_page(page, label: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = f"{ts}_{slugify(label)}"

    elements = safe_evaluate(page, DUMP_JS)
    json_path = OUT_DIR / f"{slug}.json"
    json_path.write_text(json.dumps({"url": page.url, "title": page.title(), "elements": elements}, indent=2))

    screenshot_path = OUT_DIR / f"{slug}.png"
    page.screenshot(path=str(screenshot_path), full_page=True)

    print(f"  -> saved {json_path.relative_to(ROOT_DIR)}")
    print(f"  -> saved {screenshot_path.relative_to(ROOT_DIR)}")


def main() -> None:
    url = "https://app.indiapost.gov.in/misreports/crm-last-event"
    print(f"Opening {url} in a visible browser window...")
    print("This script does NOT type your credentials for you — log in yourself,")
    print("handle any CAPTCHA, and navigate to each screen manually.\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(accept_downloads=True)
        # This portal polls continuously in the background (e.g. a "Check
        # Network Speed" widget), so it never reaches Playwright's
        # "networkidle" state — wait for the DOM instead and let the Enter
        # key / safe_evaluate retries handle any remaining settling.
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)

        input("Page loaded. Press Enter here to dump the LOGIN page's form fields...")
        dump_page(page, "login")

        input(
            "\nNow log in, and navigate to the report screen with the date "
            "range / customer ID fields. Press Enter here once that screen "
            "is visible..."
        )
        dump_page(page, "report-filter")

        while True:
            again = input(
                "\nDump another page state? (e.g. after opening the customer-id "
                "dropdown, or after clicking submit) [y/N]: "
            ).strip().lower()
            if again != "y":
                break
            label = input("  Short label for this page state (e.g. 'after-submit'): ").strip() or "extra"
            dump_page(page, label)

        input("\nDone. Press Enter to close the browser...")
        browser.close()

    print(f"\nAll captures saved under {OUT_DIR.relative_to(ROOT_DIR)}/")
    print("Share those .json files back so config/selectors.yaml can be filled in.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
