#!/usr/bin/env python3
"""Orchestrator — run every data-source refresh and record freshness metadata.

Usage:
    python refresh_all.py               # run quickbooks + sitedocs
    python refresh_all.py --source quickbooks

Each source's refresh.py runs in its own subprocess. On success/failure this
script upserts a row into the ``refresh_metadata`` table so staleness can be
monitored via ``check_freshness.py`` or the dashboard's ``/health`` endpoint.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("refresh_all")

ROOT = Path(__file__).resolve().parent

# source name -> its refresh script (each runs with cwd = its own directory)
SOURCES: dict[str, Path] = {
    "quickbooks": ROOT / "refresh" / "quickbooks" / "refresh.py",
    "sitedocs": ROOT / "refresh" / "sitedocs" / "refresh.py",
    "geotab": ROOT / "refresh" / "geotab" / "refresh.py",
}


def _db_url() -> str | None:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return None
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://") and "+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def mark_sync(source: str, status: str, row_count: int | None = None, error: str = "") -> None:
    """Upsert a freshness row into refresh_metadata."""
    url = _db_url()
    if not url:
        log.warning("DATABASE_URL not set — cannot record sync metadata for %s", source)
        return
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS refresh_metadata ("
                "source TEXT PRIMARY KEY, "
                "last_sync_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                "row_count INT, status TEXT, error TEXT)"
            ))
            conn.execute(text(
                "INSERT INTO refresh_metadata (source, last_sync_at, row_count, status, error) "
                "VALUES (:source, now(), :row_count, :status, :error) "
                "ON CONFLICT (source) DO UPDATE SET "
                "last_sync_at = now(), row_count = EXCLUDED.row_count, "
                "status = EXCLUDED.status, error = EXCLUDED.error"
            ), {"source": source, "row_count": row_count, "status": status, "error": error})
        engine.dispose()
        log.info("refresh_metadata: %s -> %s", source, status)
    except Exception as exc:  # metadata write must never fail the refresh
        log.warning("could not write refresh_metadata for %s: %s", source, exc)


def run_source(source: str, script: Path) -> bool:
    started = time.monotonic()
    log.info("══════ %s refresh starting ══════", source)
    try:
        subprocess.check_call([sys.executable, str(script)], cwd=script.parent)
        log.info("✓ %s refresh OK (%.1fs)", source, time.monotonic() - started)
        mark_sync(source, "success")
        return True
    except subprocess.CalledProcessError as exc:
        log.error("✗ %s refresh FAILED (exit %d)", source, exc.returncode)
        mark_sync(source, "failed", error=f"exit {exc.returncode}")
        return False
    except Exception as exc:  # noqa: BLE001
        log.exception("✗ %s refresh FAILED", source)
        mark_sync(source, "failed", error=str(exc)[:500])
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh all data sources")
    parser.add_argument("--source", choices=list(SOURCES) + ["all"], default="all",
                        help="which source to refresh (default: all)")
    args = parser.parse_args()

    items = list(SOURCES.items()) if args.source == "all" else [(args.source, SOURCES[args.source])]

    results: dict[str, bool] = {}
    for name, script in items:
        results[name] = run_source(name, script)

    ok = sum(1 for v in results.values() if v)
    log.info("Refresh complete: %d/%d sources OK", ok, len(results))
    sys.exit(0 if ok == len(results) else 1)


if __name__ == "__main__":
    main()
