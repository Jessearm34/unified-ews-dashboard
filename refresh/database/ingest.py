"""Ingest QuickBooks CSV exports into Railway PostgreSQL.

Connection is read from the DATABASE_URL env var.
Tables are named `quickbooks_<entity>` (e.g. `quickbooks_invoices`).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
from pandas.errors import EmptyDataError
from sqlalchemy import create_engine, text, Table, MetaData

ROOT = Path(__file__).resolve().parents[1]

SOURCES: dict[str, Path] = {
    "quickbooks": ROOT / "output",
}


def get_engine():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("ERROR: DATABASE_URL is not set.")
        sys.exit(1)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://") and not url.startswith("postgresql+psycopg2://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if "sslmode=" not in url:
        # Private internal Railway connections don't support SSL negotiation;
        # explicitly disable SSL for those and require it for public proxy URLs.
        from urllib.parse import urlparse
        _host = urlparse(url.split("?")[0]).hostname or ""
        sep = "&" if "?" in url else "?"
        if _host.endswith(".railway.internal"):
            url = f"{url}{sep}sslmode=disable"
        else:
            url = f"{url}{sep}sslmode=require"
    print(f"Connecting with URL: {url!r}")
    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print(f"Successfully connected to: {engine.url.host}")
        return engine
    except Exception as e:
        print(f"ERROR: Database connection failed: {e}")
        sys.exit(1)
        
def ingest() -> None:
    engine = get_engine()
    loaded: list[tuple[str, int]] = []

    for source, folder in SOURCES.items():
        if not folder.exists():
            print(f"  ! skipping {source}: {folder} not found")
            continue
        
        # Scan for CSVs in subdirectories (e.g. output/invoices/invoices.csv)
        for csv_path in sorted(folder.glob("*/*.csv")):
            table_name = f"{source}_{csv_path.parent.name}"
            try:
                df = pd.read_csv(csv_path, dtype=str)
                if df.empty:
                    continue
                
                # Load into Postgres (replace table if exists)
                df.to_sql(table_name, engine, if_exists="replace", index=False)
                loaded.append((table_name, len(df)))
                print(f"  loaded {table_name:28s} {len(df):>5d} rows")
            except (EmptyDataError, Exception) as e:
                print(f"  failed to load {csv_path.name}: {e}")

    print(f"\nSuccessfully ingested {len(loaded)} tables.")

if __name__ == "__main__":
    print("Ingesting QuickBooks exports into Railway PostgreSQL...\n")
    ingest()
