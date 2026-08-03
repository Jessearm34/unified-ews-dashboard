"""Insperity → Postgres sync worker. Runs on cron every 10 minutes on the DO droplet.

Pulls employee roster, employment, positions, departments, and locations
from Insperity's API.  Builds a unified worker view with Direct/Indirect
classification and region mapping, then upserts into the Railway warehouse.

Mike Skrbich wants: headcount broken down by Direct (field) vs Indirect (SGA),
plus a regional breakdown.  Classification is driven by department name —
"Field Operators" and similar → Direct, everything else → Indirect.
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

# Department names that map to Direct (field / operational)
DIRECT_DEPARTMENTS = {
    "field operators", "field operations", "field", "operations",
    "manufacturing", "shop", "installation", "maintenance",
}

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
    """Replace the whole table in a transaction."""
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
    url = f"{INSPERITY_BASE}/public/company/{INSPERITY_CLIENT_ID}/{endpoint}/{version}?apikey={INSPERITY_API_KEY}"
    headers = {
        "Accept": "application/json",
    }
    all_items = []
    params = None

    while url:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code == 404:
            log.warning("  endpoint %s/%s returned 404 — skipping", endpoint, version)
            return []
        resp.raise_for_status()
        data = resp.json()
        log.info("  %s/%s: HTTP %s, body: %s", endpoint, version, resp.status_code,
                  json.dumps(data)[:300] if not isinstance(data, list) else f"[{len(data)} items]")

        if isinstance(data, list):
            all_items.extend(data)
        elif isinstance(data, dict):
            items = data.get("data") or data.get("results") or data.get("items") or []
            all_items.extend(items)
            url = data.get("next") or data.get("nextPage") or data.get("next_page") or None
            params = None  # baked into next URL
        else:
            url = None

    return all_items


# ═══════════════════════════════════════════════════════════════════════
#  Pullers
# ═══════════════════════════════════════════════════════════════════════


def _to_df(raw, mapping):
    if not raw:
        return pd.DataFrame()
    df = pd.DataFrame(raw)
    df = df.rename(columns={k: v for k, v in mapping.items() if k in df.columns})
    for col in set(mapping.values()):
        if col not in df.columns:
            df[col] = None
    return df[list(dict.fromkeys(mapping.values()))]


def pull_employees():
    return _to_df(
        _api_get("employees", "v2"),
        {"employeeId": "employee_id", "id": "employee_id",
         "firstName": "first_name", "lastName": "last_name",
         "email": "email", "status": "status"},
    )


def pull_employment():
    return _to_df(
        _api_get("employeesemployment"),
        {"employeeId": "employee_id", "hireDate": "hire_date",
         "employmentStatus": "employment_status",
         "workerType": "worker_type", "terminationDate": "termination_date"},
    )


def pull_positions():
    return _to_df(
        _api_get("employeesposition"),
        {"employeeId": "employee_id", "jobTitle": "job_title",
         "departmentId": "department_id", "departmentName": "department_name",
         "supervisorId": "supervisor_id", "supervisorName": "supervisor_name"},
    )


def pull_departments():
    return _to_df(
        _api_get("departments"),
        {"departmentId": "department_id", "id": "department_id",
         "name": "department_name", "departmentName": "department_name"},
    )


def pull_locations():
    return _to_df(
        _api_get("locations"),
        {"locationId": "location_id", "id": "location_id",
         "name": "location_name", "locationName": "location_name",
         "city": "city", "state": "state"},
    )


# ═══════════════════════════════════════════════════════════════════════
#  Unified worker view  (the dashboard reads from this single table)
# ═══════════════════════════════════════════════════════════════════════


def _classify(department_name: str | None) -> str:
    """Direct = field/operational.  Indirect = SGA / support."""
    if pd.isna(department_name) or not department_name:
        return "indirect"
    name = str(department_name).strip().lower()
    for kw in DIRECT_DEPARTMENTS:
        if kw in name:
            return "direct"
    return "indirect"


def _build_worker_view(emp, empmt, pos, depts, locs) -> pd.DataFrame:
    """Join all Insperity tables into one worker row with Direct/Indirect flag."""
    if emp.empty:
        return pd.DataFrame(columns=[
            "employee_id", "first_name", "last_name", "email", "status",
            "hire_date", "employment_status", "worker_type",
            "job_title", "department_id", "department_name", "supervisor_id",
            "classification", "region",
        ])

    df = emp.copy()

    # Merge employment
    if not empmt.empty:
        df = df.merge(empmt, on="employee_id", how="left")

    # Merge positions (job title, department, supervisor)
    if not pos.empty:
        df = df.merge(pos, on="employee_id", how="left")

    # Classification
    df["classification"] = df.get("department_name", pd.Series()).apply(_classify)

    # Region — derived from department.  If we get locations with city/state, use that.
    # For now: "Permian" if department includes "Permian" or "Field", else "Houston"
    def _region(row):
        dept = str(row.get("department_name", "")).lower() if pd.notna(row.get("department_name")) else ""
        job = str(row.get("job_title", "")).lower() if pd.notna(row.get("job_title")) else ""
        if "permian" in dept or "permian" in job:
            return "Permian"
        return "Houston"  # default — everyone's HQ'd in Tomball

    df["region"] = df.apply(_region, axis=1)

    cols = [
        "employee_id", "first_name", "last_name", "email", "status",
        "hire_date", "employment_status", "worker_type",
        "job_title", "department_id", "department_name", "supervisor_id",
        "classification", "region",
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

    # Pull raw tables
    log.info("Pulling endpoints...")
    emp = pull_employees()
    empmt = pull_employment()
    pos = pull_positions()
    depts = pull_departments()
    locs = pull_locations()

    # Persist raw tables (useful for debugging)
    _fresh_table(engine, "employees", emp)
    _fresh_table(engine, "employment", empmt)
    _fresh_table(engine, "positions", pos)
    _fresh_table(engine, "departments", depts)
    _fresh_table(engine, "locations", locs)

    # Build & persist unified worker view
    workers = _build_worker_view(emp, empmt, pos, depts, locs)
    _fresh_table(engine, "workers", workers)

    # Log the breakdown Mike wants to see
    if not workers.empty:
        direct = int((workers["classification"] == "direct").sum())
        indirect = int((workers["classification"] == "indirect").sum())
        total = len(workers)
        ratio = f"{direct}:{indirect}" if indirect else str(direct)
        log.info("Headcount: %d total  |  Direct %d  |  Indirect %d  |  Ratio %s",
                 total, direct, indirect, ratio)

        # Regional breakdown
        for region in sorted(workers["region"].dropna().unique()):
            r_df = workers[workers["region"] == region]
            log.info("  %s: %d total  (Direct %d / Indirect %d)",
                     region, len(r_df),
                     int((r_df["classification"] == "direct").sum()),
                     int((r_df["classification"] == "indirect").sum()))

    elapsed = time.monotonic() - start
    log.info("Insperity sync finished in %.1fs", elapsed)


if __name__ == "__main__":
    sync_all()
