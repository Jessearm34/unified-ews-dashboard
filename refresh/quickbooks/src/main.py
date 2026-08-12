#!/usr/bin/env python3
"""Export QuickBooks Online data to CSV files."""

from __future__ import annotations

import argparse
import logging
import sys

from src.config import settings
from src.exporter import CsvExporter
from src.quickbooks_client import QuickBooksClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def run_export() -> list:
    paths: list = []

    # QuickBooks export
    qb_client = QuickBooksClient()
    logger.info("Fetching from QuickBooks (%s)...", settings.environment)
    qb_sheets = qb_client.fetch_all()
    exporter = CsvExporter(settings.output_dir)
    qb_paths = exporter.export_all(qb_sheets)
    logger.info("Wrote %d files to %s", len(qb_paths), settings.output_dir)
    paths.extend(qb_paths)

    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export QuickBooks Online data to CSV.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    try:
        run_export()
    except Exception as exc:
        logger.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
