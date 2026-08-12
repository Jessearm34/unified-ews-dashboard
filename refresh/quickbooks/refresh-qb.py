#!/usr/bin/env python3
"""Export QuickBooks data only (no SiteDocs)."""
from __future__ import annotations

import argparse
import logging
import sys

from src.config import settings
from src.exporter import CsvExporter
from src.quickbooks_client import QuickBooksClient


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def run_export(verbose: bool = False) -> int:
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    client = QuickBooksClient()
    logger.info("Fetching from QuickBooks (%s)...", settings.environment)
    sheets = client.fetch_all()

    exporter = CsvExporter(settings.output_dir)
    paths = exporter.export_all(sheets)
    logger.info("Wrote %d files to %s", len(paths), settings.output_dir)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export QuickBooks to CSV (quickbooks only).")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    try:
        return run_export(args.verbose)
    except Exception as exc:
        logger.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
