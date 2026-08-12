"""ingest.py — Load SiteDocs CSV exports into the Postgres warehouse.

Mirrors the QuickBooks ingest pattern.  Each dataset lands in a
``sitedocs_<dataset>`` table.  Re-running replaces the tables.
"""

from __future__ import annotations

import csv
import io
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", str(ROOT / "output"))).expanduser().resolve()

# Tables we create / refresh — each maps a dataset folder to a table name.
TABLES: list[dict] = [
    {"folder": "workers", "table": "sitedocs_workers"},
    {"folder": "equipment", "table": "sitedocs_equipment"},
    {"folder": "incidents", "table": "sitedocs_incidents"},
    {"folder": "certifications", "table": "sitedocs_certifications"},
    {"folder": "forms", "table": "sitedocs_forms"},
    {"folder": "locations", "table": "sitedocs_locations"},
    {"folder": "companytypes", "table": "sitedocs_companytypes"},
    {"folder": "certificationtypes", "table": "sitedocs_certificationtypes"},
    {"folder": "formtypes", "table": "sitedocs_formtypes"},
    {"folder": "signatures", "table": "sitedocs_signatures"},
    {"folder": "schedules", "table": "sitedocs_schedules"},
]


def _engine():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable not set")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if "psycopg2" not in url and "psycopg" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return create_engine(url, pool_size=3, max_overflow=5, pool_recycle=1800)


def _read_csv(path: Path) -> list[dict]:
    """Read a CSV and return rows as dicts."""
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader)


def _create_table_ddl(table_name: str, sample_row: dict) -> str:
    """Build a CREATE TABLE statement from a sample row (all TEXT columns)."""
    cols = [f'"{k}" TEXT' for k in sample_row if k]
    if not cols:
        return f"CREATE TABLE IF NOT EXISTS {table_name} (_blank BOOLEAN)"
    return f"CREATE TABLE IF NOT EXISTS {table_name} ({', '.join(cols)})"


def _ingest_folder(engine, folder: str, table: str) -> int:
    """Load all CSVs in ``output/<folder>/`` into ``<table>``.

    Drops and recreates the table each time (full refresh).
    Returns the row count.
    """
    src = OUTPUT_DIR / folder
    if not src.is_dir():
        logger.warning("  No output directory: %s", src)
        return 0

    csv_files = sorted(src.glob("*.csv"))
    all_rows: list[dict] = []
    for csv_path in csv_files:
        all_rows.extend(_read_csv(csv_path))

    if not all_rows:
        # Create an empty table so the dashboard has something to query
        logger.info("  %s: 0 rows (creating empty table)", table)
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS {}".format(table)))
            conn.execute(text("CREATE TABLE IF NOT EXISTS {} (_empty BOOLEAN)".format(table)))
        return 0

    # Derive columns from the union of all row keys
    columns: list[str] = []
    for row in all_rows:
        for k in row:
            if k and k not in columns:
                columns.append(k)

    quoted_cols = ['"{}"'.format(c) for c in columns]
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS {}".format(table)))
        col_defs = ', '.join('{} TEXT'.format(c) for c in quoted_cols)
        conn.execute(text("CREATE TABLE {} ({})".format(table, col_defs)))

        # Insert
        col_list = ', '.join(quoted_cols)
        placeholders = ', '.join(':{}'.format(c) for c in columns)
        insert_sql = text("INSERT INTO {} ({}) VALUES ({})".format(table, col_list, placeholders))

        batch = []
        for row in all_rows:
            cleaned = {c: row.get(c, "") for c in columns}
            batch.append(cleaned)
        conn.execute(insert_sql, batch)

    logger.info("  %s: %d rows", table, len(all_rows))
    return len(all_rows)


def main() -> None:
    logger.info("\n═══ Warehouse ingest (SiteDocs) ═══")
    engine = _engine()

    total = 0
    for t in TABLES:
        count = _ingest_folder(engine, t["folder"], t["table"])
        total += count

    logger.info("Ingested %d total rows across %d tables", total, len(TABLES))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main()
