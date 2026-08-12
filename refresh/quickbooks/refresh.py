"""One-command dashboard refresh: QuickBooks -> PostgreSQL.

Usage:
    python refresh.py             # pull from QuickBooks and ingest into Postgres
    python refresh.py --no-export # skip the QuickBooks pull; re-ingest existing CSVs
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

PY = sys.executable  # always uses the current python, no hardcoded venv path


def step(n: int, msg: str) -> None:
    print(f"\n\033[1m[{n}/3] {msg}\033[0m", flush=True)


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd, cwd=ROOT, **kw)


def export_quickbooks() -> None:
    step(1, "Exporting latest data from QuickBooks")
    run([PY, "-m", "src.main"], check=True)


def ingest() -> None:
    step(2, "Ingesting exports into Railway Postgres")
    run([PY, "database/ingest.py"], check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Refresh the dashboard end to end.")
    ap.add_argument("--no-export", action="store_true",
                    help="skip the QuickBooks pull; re-ingest existing CSVs")
    args = ap.parse_args()

    if not args.no_export:
        export_quickbooks()
    else:
        print("\n[1/3] Skipping QuickBooks export (--no-export)")

    ingest()

    print("\n\033[1mDone.\033[0m")


if __name__ == "__main__":
    main()
