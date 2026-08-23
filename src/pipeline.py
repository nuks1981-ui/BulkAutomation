#!/usr/bin/env python3
"""End-to-end CLI: log into the India Post MIS portal, download the CRM
last-event report for a date range/customer, and process it into the
customized output formats defined in config/pipeline.yaml.

Examples:
    # Download + process (dates in YYYY-MM-DD, matching the portal's date picker)
    python -m src.pipeline --from-date 2026-08-01 --to-date 2026-08-23

    # Use a specific customer ID (there is no fixed default; pass it each run)
    python -m src.pipeline --from-date 2026-08-01 --to-date 2026-08-23 --customer-id 2000014074

    # Skip the download step and just re-process an already-downloaded file
    python -m src.pipeline --skip-download --raw-file data/raw/some_export.csv
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

from src.config import ROOT_DIR, Settings
from src.process import run as run_processing

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    today = date.today().isoformat()

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from-date", default=yesterday, help=f"Report start date (default: yesterday, {yesterday})")
    parser.add_argument("--to-date", default=today, help=f"Report end date (default: today, {today})")
    parser.add_argument("--customer-id", default=None, help="Overrides INDIAPOST_CUSTOMER_ID from .env")
    parser.add_argument("--skip-download", action="store_true", help="Skip the browser step; process an existing file")
    parser.add_argument("--raw-file", type=Path, default=None, help="Raw file to process when --skip-download is set")
    parser.add_argument(
        "--pipeline-config",
        type=Path,
        default=ROOT_DIR / "config" / "pipeline.yaml",
        help="Path to the processing config (default: config/pipeline.yaml)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = Settings.load()

    customer_id = args.customer_id or settings.customer_id
    if not customer_id:
        logger.error("No customer ID given. Pass --customer-id or set INDIAPOST_CUSTOMER_ID in .env.")
        return 1

    if args.skip_download:
        if not args.raw_file:
            logger.error("--skip-download requires --raw-file <path>")
            return 1
        raw_path = args.raw_file
    else:
        if not settings.username or not settings.password:
            logger.error("INDIAPOST_USERNAME / INDIAPOST_PASSWORD not set in .env")
            return 1
        # Imported lazily so `--skip-download` runs don't require Playwright's
        # browser binaries to be installed.
        from src.browser import run_pipeline_steps

        raw_path = run_pipeline_steps(
            url=settings.url,
            selectors_path=settings.selectors_path,
            download_dir=settings.download_dir,
            headless=settings.headless,
            username=settings.username,
            password=settings.password,
            totp_secret=settings.totp_secret,
            from_date=args.from_date,
            to_date=args.to_date,
            customer_id=customer_id,
        )

    run_tag = f"{args.from_date.replace('/', '-')}_to_{args.to_date.replace('/', '-')}"
    outputs = run_processing(
        raw_path=raw_path,
        pipeline_config_path=args.pipeline_config,
        processed_dir=settings.processed_dir,
        run_tag=run_tag,
    )

    logger.info("Done. Wrote %d file(s):", len(outputs))
    for out in outputs:
        logger.info("  %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
