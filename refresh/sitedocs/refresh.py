"""refresh.py — one-command SiteDocs export + warehouse ingest.

Mirrors the QuickBooks refresh pipeline but for SiteDocs HSE data.
Runs: src.main (pull SiteDocs API -> CSVs) then database/ingest.py (CSVs -> Postgres).
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("refresh-sd")

ROOT = Path(__file__).resolve().parent


def run(args: list[str]) -> None:
    logger.info("$ %s", " ".join(args))
    subprocess.check_call(args, cwd=ROOT)


def main() -> None:
    parser = argparse.ArgumentParser(description="SiteDocs data refresh pipeline")
    parser.add_argument("--no-export", action="store_true", help="Skip the SiteDocs API pull")
    args = parser.parse_args()

    # 1. Export SiteDocs data to CSVs
    if not args.no_export:
        logger.info("═══ SiteDocs export ═══")
        run([sys.executable, "-m", "src.main"])

    # 2. Ingest CSVs into Postgres
    logger.info("═══ warehouse ingest ═══")
    run([sys.executable, "database/ingest.py"])

    logger.info("SiteDocs refresh complete ✓")


if __name__ == "__main__":
    main()
