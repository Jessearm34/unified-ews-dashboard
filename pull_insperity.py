"""Insperity → Postgres sync worker. Runs on cron every 10 minutes on the DO droplet.

Pulls employee roster, employment, positions, departments, and locations
from Insperity's API.  Builds a unified worker view with Direct/Indirect
classification and region mapping, then upserts into the Railway warehouse.
"""

from __future__ import annotations

import os
import time
import json
import logging
from datetime import datetime, timezone

import requests
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════════════════
#  Config
# ═══════════════════════════════════════════════════════════════════════

INSPERITY_BASE = os.getenv("INSPERITY_BASE_URL", "https://api.insperity.com")
INSPERITY_CLIENT_ID = os.getenv("INSPERITY_CLIENT_ID", "")
INSPERITY_API_KEY = os.getenv("INSPERITY_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

TABLE_PREFIX = "insperity_"

# Department IDs that map to Direct (field / operational)
DIRECT_DEPT_IDS = {"FIELD", "FIELD1", "SHOP", "MAINT", "INSTALL", "OPERATIONS"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("insperity-sync")


# ═══════════════════════════════════════════════════════════════════════
#  Database
# ═══════════════════════════════════════════════════════════════════════


def _engine():
    url = DATABASE_URL
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://") and "+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return create_engine(url)


def _fresh_table(engine, table: str, df: pd.DataFrame):
    if df.empty:
        log.info("  %s: no rows — skipping", table)
        return
    full = f"public.{TABLE_PREFIX}{table}"
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {full}"))
        df.to_sql(f"{TABLE_PREFIX}{table}", conn, schema="public",
                  index=False, if_exists="replace")
    log.info("  %s: written %d rows", table, len(df))


# ═══════════════════════════════════════════════════════════════════════
#  API client
# ═══════════════════════════════════════════════════════════════════════


def _api_get(endpoint: str, version: str = "v1") -> list[dict]:
    """GET an Insperity endpoint, return the unwrapped item list.

    Insperity nests results in wrapper keys like {"employees": [...]},
    {"items": [...]}, or returns a flat list.
    """
    url = f"{INSPERITY_BASE}/public/company/{INSPERITY_CLIENT_ID}/{endpoint}/{version}?apikey={INSPERITY_API_KEY}"
    headers = {"Accept": "application/json"}
    all_items = []
    params = None

    while url:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code == 404:
            log.warning("  %s/%s returned 404 — skipping", endpoint, version)
            return []
        resp.raise_for_status()
        data = resp.json()

        # Unwrap Insperity's nested response envelope
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            # Try all common wrapper keys
            items = (data.get("employees")
                     or data.get("items")
                     or data.get("data")
                     or data.get("results")
                     or [])
        else:
            items = []

        all_items.extend(items)
        log.info("  %s/%s: got %d items (total %d so far)", endpoint, version,
                 len(items), len(all_items))

        # Pagination
        if isinstance(data, dict):
            url = data.get("next") or data.get("nextPage") or data.get("next_page") or None
            params = None
        else:
            url = None

    return all_items


# ═══════════════════════════════════════════════════════════════════════
#  Pullers  (field names matched to actual Insperity API responses)
# ═══════════════════════════════════════════════════════════════════════


def _to_df(raw, col_map):
    """Build a DataFrame from raw dicts, renaming columns per col_map."""
    if not raw:
        return pd.DataFrame()
    df = pd.DataFrame(raw)
    df = df.rename(columns=col_map)
    for col in set(col_map.values()):
        if col not in df.columns:
            df[col] = None
    return df[list(dict.fromkeys(col_map.values()))]


def pull_employees():
    """GET employees/v2 — returns personId, givenName, familyName, email, status."""
    raw = _api_get("employees", "v2")
    return _to_df(raw, {
        "personId": "person_id",
        "givenName": "first_name",
        "familyName": "last_name",
        "email": "email",
        "status": "status",
        "communication": "_communication_raw",  # nested object with email/phone
    })


def pull_employment():
    """GET employeesemployment/v1 — hire date, worker type, status."""
    raw = _api_get("employeesemployment")
    return _to_df(raw, {
        "personId": "person_id",
        "hireDate": "hire_date",
        "employmentStatus": "employment_status",
        "employmentStatusReason": "status_reason",
        "clientEmployeeNumber": "employee_number",
    })


def pull_positions():
    """GET employeesposition/v1 — job title, departmentId, supervisor."""
    raw = _api_get("employeesposition")
    return _to_df(raw, {
        "personId": "person_id",
        "jobTitle": "job_title",
        "departmentId": "department_id",
        "supervisorId": "supervisor_id",
        "supervisorName": "supervisor_name",
    })


def pull_departments():
    """GET departments/v1 — id, description."""
    raw = _api_get("departments")
    return _to_df(raw, {
        "id": "department_id",
        "description": "department_name",
    })


def pull_locations():
    """GET locations/v1."""
    raw = _api_get("locations")
    return _to_df(raw, {
        "id": "location_id",
        "description": "location_name",
        "city": "city",
        "state": "state",
    })


# ═══════════════════════════════════════════════════════════════════════
#  Unified worker view
# ═══════════════════════════════════════════════════════════════════════


def _classify(department_id: str | None, department_name: str | None) -> str:
    """Direct = field/operational.  Indirect = SGA / support."""
    if department_id and str(department_id).strip().upper() in DIRECT_DEPT_IDS:
        return "direct"
    if department_name and str(department_name).strip().upper() in DIRECT_DEPT_IDS:
        return "direct"
    return "indirect"


def _build_worker_view(emp, empmt, pos, depts, locs) -> pd.DataFrame:
    """Join into one worker row with Direct/Indirect classification."""
    if emp.empty:
        return pd.DataFrame(columns=[
            "person_id", "first_name", "last_name", "status",
            "hire_date", "employment_status", "job_title",
            "department_id", "department_name", "classification", "region",
        ])

    df = emp.copy()

    # Merge employment
    if not empmt.empty:
        df = df.merge(empmt, on="person_id", how="left")

    # Merge positions
    if not pos.empty:
        df = df.merge(pos, on="person_id", how="left")

    # Map department ID → name
    if not depts.empty and "department_id" in df.columns:
        dept_map = dict(zip(depts["department_id"], depts["department_name"]))
        df["department_name"] = df["department_id"].map(dept_map).fillna(df.get("department_name", None))

    # Classification
    df["classification"] = df.apply(
        lambda r: _classify(r.get("department_id"), r.get("department_name")), axis=1
    )

    # Region — default Houston for now
    df["region"] = "Houston"

    cols = [
        "person_id", "first_name", "last_name", "status",
        "hire_date", "employment_status", "job_title",
        "department_id", "department_name", "classification", "region",
    ]
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols]


# ═══════════════════════════════════════════════════════════════════════
#  Sync
# ═══════════════════════════════════════════════════════════════════════


def sync_all():
    start = time.monotonic()
    log.info("Insperity sync starting")

    if not INSPERITY_API_KEY:
        log.warning("INSPERITY_API_KEY not set — skipping")
        return

    engine = _engine()

    log.info("Pulling endpoints...")
    emp = pull_employees()
    empmt = pull_employment()
    pos = pull_positions()
    depts = pull_departments()
    locs = pull_locations()

    # Persist raw tables
    _fresh_table(engine, "employees", emp)
    _fresh_table(engine, "employment", empmt)
    _fresh_table(engine, "positions", pos)
    _fresh_table(engine, "departments", depts)
    _fresh_table(engine, "locations", locs)

    # Build & persist unified worker view
    workers = _build_worker_view(emp, empmt, pos, depts, locs)
    _fresh_table(engine, "workers", workers)

    # Headcount breakdown
    if not workers.empty:
        direct = int((workers["classification"] == "direct").sum())
        indirect = int((workers["classification"] == "indirect").sum())
        total = len(workers)
        ratio = f"{direct}:{indirect}" if indirect else str(direct)
        log.info("Headcount: %d total  |  Direct %d  |  Indirect %d  |  Ratio %s",
                 total, direct, indirect, ratio)

    elapsed = time.monotonic() - start
    log.info("Insperity sync finished in %.1fs", elapsed)


if __name__ == "__main__":
    sync_all()
