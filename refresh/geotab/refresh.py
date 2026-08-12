#!/usr/bin/env python3
"""GeoTab sync worker — standalone entry point.

Creates the geotab tables (vehicles, drivers, trips, gps_logs, fault_codes,
fuel_events, sync_metadata, sync_logs) in DATABASE_URL, then pulls fresh data
from MyGeotab and upserts it.

Usage:
    python refresh.py          # full sync
    python refresh.py --once   # same (single run, no scheduler)

Env vars:
    DATABASE_URL         Postgres to write into (the dashboard's DB)
    GEOTAB_DATABASE      MyGeotab database name
    GEOTAB_USERNAME      MyGeotab login
    GEOTAB_PASSWORD      MyGeotab password
    GEOTAB_SERVER        default my.geotab.com
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("geotab_sync")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def _db_url() -> str:
    import os

    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("DATABASE_URL is not set — cannot write geotab tables.")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://") and "+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def main() -> int:
    parser = argparse.ArgumentParser(description="GeoTab sync worker")
    parser.add_argument("--once", action="store_true", help="run a single sync and exit (default)")
    args = parser.parse_args()
    del args  # single-run mode; flag kept for clarity

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from config import get_settings, missing_geotab_credentials
    from models import Base
    from sync_service import SyncService

    settings = get_settings()
    missing = missing_geotab_credentials(settings)
    if missing:
        log.error("Missing GeoTab credentials: %s", ", ".join(missing))
        return 2

    url = _db_url()
    engine = create_engine(url, pool_pre_ping=True, future=True, connect_args={"connect_timeout": 10})
    Base.metadata.create_all(engine)
    log.info("Tables ensured in %s", url.split("@")[-1].split("/")[0])

    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)
    with SessionLocal() as db:
        service = SyncService(db)
        log.info("Starting GeoTab sync…")
        results = service.sync_all()
        log.info("Sync complete: %s", results)

    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
