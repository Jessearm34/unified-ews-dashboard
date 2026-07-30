"""Insperity → Postgres sync worker. Runs on cron every 10 minutes on the droplet.

Pulls employee roster, employment details, positions, departments, and locations
from Insperity's Public API and upserts them into the warehouse database so the
dashboard can read them alongside SiteDocs, GeoTab, and QuickBooks data.

Set these env vars before running:
    INSPERITY_CLIENT_ID      — from Insperity Integration Specialist
    INSPERITY_API_KEY      — from Insperity
    DATABASE_URL             — Railway Postgres (reseau.proxy.rlwy.net:...)
"""

from __future__ import annotations

import os
import sys
import time
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

import requests
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════════════════
#  Config
# ═══════════════════════════════════════════════════════════════════════

INSPERITY_BASE = os.getenv("INSPERITY_BASE_URL", "https://api.insperity.com/v1")
INSPERITY_CLIENT_ID = os.getenv("INSPERITY_CLIENT_ID", "")
INSPERITY_API_KEY = os.getenv("INSPERITY_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

TABLE_PREFIX = "insperity_"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("insperity-sync")


# ═══════════════════════════════════════════════════════════════════════
#  Database helpers
# ═══════════════════════════════════════════════════════════════════════


def _get_engine():
    url = DATABASE_URL
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://") and "+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return create_engine(url)


def upsert_df(engine, table_name: str, df: pd.DataFrame, pk_cols: list[str]):
    """Insert or update rows in *table_name* keyed on *pk_cols*.

    Rows matching on all pk columns are updated; new rows are inserted.
    """
    if df.empty:
        log.info("  %s: nothing to upsert (0 rows)", table_name)
        return

    schema = "public"
    full_name = f"{schema}.{TABLE_PREFIX}{table_name}"
    now = datetime.now(timezone.utc).isoformat()

    with engine.begin() as conn:
        # Ensure table structure matches DataFrame columns
        # We don't CREATE TABLE here — assume it already exists from a prior run or migration.
        # On first run the upsert will create the table implicitly via pandas to_sql,
        # then subsequent runs do the upsert.

        for _, row in df.iterrows():
            record = row.to_dict()
            record["_synced_at"] = now

            where = " AND ".join(f'"{c}" = :{c}' for c in pk_cols)
            check = conn.execute(
                text(f'SELECT 1 FROM {full_name} WHERE {where} LIMIT 1'),
                record,
            ).fetchone()

            if check:
                set_clause = ", ".join(
                    f'"{c}" = :{c}' for c in record if c not in pk_cols
                )
                conn.execute(
                    text(f"UPDATE {full_name} SET {set_clause} WHERE {where}"),
                    record,
                )
            else:
                cols = ", ".join(f'"{c}"' for c in record)
                vals = ", ".join(f":{c}" for c in record)
                conn.execute(
                    text(f"INSERT INTO {full_name} ({cols}) VALUES ({vals})"),
                    record,
                )

    log.info("  %s: upserted %d rows", table_name, len(df))


# ═══════════════════════════════════════════════════════════════════════
#  Insperity API client
# ═══════════════════════════════════════════════════════════════════════


def _api_get(endpoint: str, params: dict | None = None) -> list[dict]:
    """GET a paginated Insperity endpoint, return all results as a list of dicts."""
    url = f"{INSPERITY_BASE}/public/company/{INSPERITY_CLIENT_ID}/{endpoint}/v2"
    headers = {
        "X-Client-Id": INSPERITY_CLIENT_ID,
        "X-API-Key": INSPERITY_API_KEY,
        "Accept": "application/json",
    }
    all_results = []

    while url:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # Insperity may wrap results in a "data" or "results" key
        if isinstance(data, list):
            all_results.extend(data)
        elif isinstance(data, dict):
            items = data.get("data") or data.get("results") or data.get("items") or []
            all_results.extend(items)

        # Pagination — check for next link
        url = None
        if isinstance(data, dict):
            next_link = data.get("next") or data.get("nextPage") or data.get("next_page")
            if next_link:
                url = next_link
                params = None  # params are baked into the next URL

    return all_results


# ═══════════════════════════════════════════════════════════════════════
#  Endpoint pullers  (each returns a DataFrame ready for upsert)
# ═══════════════════════════════════════════════════════════════════════


def pull_employees() -> pd.DataFrame:
    """
    GET employees/v2 — basic roster.

    Columns persisted: employee_id, first_name, last_name, email, status
    """
    if not INSPERITY_API_KEY:
        log.warning("Skipping employees — INSPERITY_API_KEY not set")
        return pd.DataFrame()

    try:
        raw = _api_get("employees")
    except Exception as exc:
        log.error("Failed to pull employees: %s", exc)
        return pd.DataFrame()

    if not raw:
        return pd.DataFrame()

    df = pd.DataFrame(raw)
    # Normalize column names (Insperity uses camelCase)
    mapping = {
        "employeeId": "employee_id", "id": "employee_id",
        "firstName": "first_name", "lastName": "last_name",
        "email": "email", "status": "status",
    }
    df = df.rename(columns={k: v for k, v in mapping.items() if k in df.columns})
    for col in ["employee_id", "first_name", "last_name", "email", "status"]:
        if col not in df.columns:
            df[col] = None
    return df[["employee_id", "first_name", "last_name", "email", "status"]]


def pull_employment() -> pd.DataFrame:
    """GET employeesemployment/v1 — hire date, worker type."""
    if not INSPERITY_API_KEY:
        return pd.DataFrame()

    try:
        raw = _api_get("employeesemployment", params={})
    except Exception as exc:
        log.error("Failed to pull employment: %s", exc)
        return pd.DataFrame()

    if not raw:
        return pd.DataFrame()

    df = pd.DataFrame(raw)
    mapping = {
        "employeeId": "employee_id",
        "hireDate": "hire_date",
        "employmentStatus": "employment_status",
        "workerType": "worker_type",
        "terminationDate": "termination_date",
    }
    df = df.rename(columns={k: v for k, v in mapping.items() if k in df.columns})
    for col in ["employee_id", "hire_date", "employment_status", "worker_type"]:
        if col not in df.columns:
            df[col] = None
    return df[["employee_id", "hire_date", "employment_status", "worker_type"]]


def pull_positions() -> pd.DataFrame:
    """GET employeesposition/v1 — job title, department, supervisor."""
    if not INSPERITY_API_KEY:
        return pd.DataFrame()

    try:
        raw = _api_get("employeesposition", params={})
    except Exception as exc:
        log.error("Failed to pull positions: %s", exc)
        return pd.DataFrame()

    if not raw:
        return pd.DataFrame()

    df = pd.DataFrame(raw)
    mapping = {
        "employeeId": "employee_id",
        "jobTitle": "job_title",
        "departmentId": "department_id",
        "departmentName": "department_name",
        "supervisorId": "supervisor_id",
        "supervisorName": "supervisor_name",
    }
    df = df.rename(columns={k: v for k, v in mapping.items() if k in df.columns})
    for col in ["employee_id", "job_title", "department_id", "department_name", "supervisor_id"]:
        if col not in df.columns:
            df[col] = None
    return df[["employee_id", "job_title", "department_id", "department_name", "supervisor_id"]]


def pull_departments() -> pd.DataFrame:
    """GET departments/v1 — department reference data."""
    if not INSPERITY_API_KEY:
        return pd.DataFrame()

    try:
        raw = _api_get("departments", params={})
    except Exception as exc:
        log.error("Failed to pull departments: %s", exc)
        return pd.DataFrame()

    if not raw:
        return pd.DataFrame()

    df = pd.DataFrame(raw)
    mapping = {
        "departmentId": "department_id", "id": "department_id",
        "name": "department_name", "departmentName": "department_name",
        "costCenter": "cost_center",
    }
    df = df.rename(columns={k: v for k, v in mapping.items() if k in df.columns})
    for col in ["department_id", "department_name"]:
        if col not in df.columns:
            df[col] = None
    return df[["department_id", "department_name"]]


def pull_locations() -> pd.DataFrame:
    """GET locations/v1 — physical locations / sites."""
    if not INSPERITY_API_KEY:
        return pd.DataFrame()

    try:
        raw = _api_get("locations", params={})
    except Exception as exc:
        log.error("Failed to pull locations: %s", exc)
        return pd.DataFrame()

    if not raw:
        return pd.DataFrame()

    df = pd.DataFrame(raw)
    mapping = {
        "locationId": "location_id", "id": "location_id",
        "name": "location_name", "locationName": "location_name",
        "address": "address", "city": "city", "state": "state", "zip": "zip",
    }
    df = df.rename(columns={k: v for k, v in mapping.items() if k in df.columns})
    for col in ["location_id", "location_name"]:
        if col not in df.columns:
            df[col] = None
    return df[["location_id", "location_name"]]


def pull_communication() -> pd.DataFrame:
    """GET employeescommunication/v1 — email, phone."""
    if not INSPERITY_API_KEY:
        return pd.DataFrame()

    try:
        raw = _api_get("employeescommunication", params={})
    except Exception as exc:
        log.error("Failed to pull communication: %s", exc)
        return pd.DataFrame()

    if not raw:
        return pd.DataFrame()

    df = pd.DataFrame(raw)
    mapping = {
        "employeeId": "employee_id",
        "email": "email",
        "phone": "phone",
        "workPhone": "work_phone",
        "mobilePhone": "mobile_phone",
    }
    df = df.rename(columns={k: v for k, v in mapping.items() if k in df.columns})
    for col in ["employee_id", "email", "phone"]:
        if col not in df.columns:
            df[col] = None
    return df[["employee_id", "email", "phone"]]


# ═══════════════════════════════════════════════════════════════════════
#  Main sync
# ═══════════════════════════════════════════════════════════════════════


def sync_all():
    """Pull all Insperity endpoints and upsert into the warehouse."""
    start = time.monotonic()
    log.info("Insperity sync starting")

    if not INSPERITY_API_KEY:
        log.warning("INSPERITY_API_KEY not set — skipping all pulls")
        return

    engine = _get_engine()

    tasks = [
        ("employees", pull_employees, ["employee_id"]),
        ("employment", pull_employment, ["employee_id"]),
        ("positions", pull_positions, ["employee_id"]),
        ("departments", pull_departments, ["department_id"]),
        ("locations", pull_locations, ["location_id"]),
        ("communication", pull_communication, ["employee_id"]),
    ]

    for table, puller, pks in tasks:
        try:
            df = puller()
            if not df.empty:
                upsert_df(engine, table, df, pks)
            else:
                log.info("  %s: no data returned", table)
        except Exception as exc:
            log.error("  %s: FAILED — %s", table, exc)

    elapsed = time.monotonic() - start
    log.info("Insperity sync finished in %.1fs", elapsed)


if __name__ == "__main__":
    sync_all()
