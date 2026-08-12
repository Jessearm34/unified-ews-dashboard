#!/usr/bin/env python3
"""Report data freshness — how long ago each source last synced.

Usage:
    python check_freshness.py            # human-readable table
    python check_freshness.py --json      # machine-readable
    python check_freshness.py --max-age 3600   # exit non-zero if any source stale > 1h

Exit code 0 = all fresh, 1 = one or more sources stale, 2 = couldn't read metadata.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def _db_url() -> str | None:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return None
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://") and "+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def fetch_metadata() -> list[dict]:
    url = _db_url()
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        sys.exit(2)
    from sqlalchemy import create_engine, text
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS refresh_metadata ("
                "source TEXT PRIMARY KEY, last_sync_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                "row_count INT, status TEXT, error TEXT)"
            ))
            rows = conn.execute(text(
                "SELECT source, last_sync_at, row_count, status, error FROM refresh_metadata"
            )).mappings().all()
    finally:
        engine.dispose()
    return [dict(r) for r in rows]


def age_seconds(ts) -> float:
    if ts is None:
        return float("inf")
    if getattr(ts, "tzinfo", None) is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds()


def _human(secs: float) -> str:
    if secs == float("inf"):
        return "never"
    if secs < 60:
        return f"{int(secs)}s ago"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{secs / 3600:.1f}h ago"
    return f"{secs / 86400:.1f}d ago"


def main() -> None:
    parser = argparse.ArgumentParser(description="Check data freshness")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--max-age", type=int, default=None,
                        help="exit non-zero if any source is older than this many seconds")
    args = parser.parse_args()

    rows = fetch_metadata()
    if not rows:
        if args.json:
            print(json.dumps({"sources": []}))
        else:
            print("No sync metadata yet — refresh has never run.")
        sys.exit(2)

    enriched = [
        {"source": r["source"], "last_sync_at": str(r["last_sync_at"]),
         "age_seconds": age_seconds(r["last_sync_at"]),
         "status": r.get("status"), "row_count": r.get("row_count"), "error": r.get("error")}
        for r in rows
    ]

    if args.json:
        print(json.dumps({"sources": enriched}, default=str))
    else:
        print(f"{'SOURCE':<12} {'STATUS':<8} {'AGE':<12} {'ROWS':<8}")
        print("-" * 42)
        for r in enriched:
            print(f"{r['source']:<12} {(r['status'] or '?'):<8} {_human(r['age_seconds']):<12} {str(r['row_count'] or ''):<8}")

    if args.max_age is not None:
        stale = [r for r in enriched if r["age_seconds"] > args.max_age]
        if stale:
            for r in stale:
                print(f"STALE: {r['source']} is {_human(r['age_seconds'])} (max {args.max_age}s)", file=sys.stderr)
            sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
