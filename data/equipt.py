"""Data pipeline for Equipt — equipment tracking, maintenance, and asset management.

Pulls from the Equipt API (exact endpoint TBD — confirm with Equipt).
Requires: API key, organization slug.

ENABLED = False  —  set True when credentials are ready.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from typing import Any

import pandas as pd
from sqlalchemy import create_engine

# ═══════════════════════════════════════════════════════════════════════
#  PILLBOX SWITCH  —  flip to True when you're ready to pull live data
# ═══════════════════════════════════════════════════════════════════════

ENABLED = False

# ═══════════════════════════════════════════════════════════════════════
#  Configuration  (set these env vars before enabling)
# ═══════════════════════════════════════════════════════════════════════

EQUIPT_BASE_URL = os.environ.get("EQUIPT_BASE_URL", "https://api.equiptsoftware.com/api")
EQUIPT_API_KEY = os.environ.get("EQUIPT_API_KEY", "")
EQUIPT_ORG_SLUG = os.environ.get("EQUIPT_ORG_SLUG", "")
EQUIPT_DATABASE_URL = os.environ.get("EQUIPT_DATABASE_URL", "")

_CACHE_TTL = 600
_DATASET_CACHE: EqptDataset | None = None
_CACHE_TIMESTAMP: float = 0.0


# ── Engine ────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _equipt_engine():
    """
    SQLAlchemy engine for the Equipt warehouse mirror.

    UNCOMMENT and set ``EQUIPT_DATABASE_URL`` when the mirror exists.
    """
    # url = os.environ.get("EQUIPT_DATABASE_URL", "")
    # if not url:
    #     raise RuntimeError("EQUIPT_DATABASE_URL is not set")
    # if url.startswith("postgres://"):
    #     url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    # elif url.startswith("postgresql://") and "+psycopg2" not in url:
    #     url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    # return create_engine(url, connect_args={"sslmode": "require"})
    return None


# ── Dataset ────────────────────────────────────────────────────────────


@dataclass
class EqptDataset:
    """Snapshot of all Equipt data loaded for the dashboard."""

    equipment: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=[
        "equipmentId", "name", "category", "status", "location",
        "lastServiceDate", "nextServiceDue",
    ]))
    maintenance_logs: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=[
        "logId", "equipmentId", "serviceType", "completedDate",
        "technician", "notes", "cost",
    ]))
    inspections: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=[
        "inspectionId", "equipmentId", "inspector", "date",
        "result", "findings",
    ]))
    utilization: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=[
        "equipmentId", "date", "hoursUsed", "location",
    ]))


def _empty_eqpt_dataset() -> EqptDataset:
    return EqptDataset()


# ── API client (commented out) ────────────────────────────────────────


def _equipt_api_get(endpoint: str, params: dict | None = None) -> dict | list:
    """
    Call the Equipt REST API.

    UNCOMMENT and set credentials when ready.

    Expected headers:
        X-API-Key: <EQUIPT_API_KEY>
        X-Org-Slug: <EQUIPT_ORG_SLUG>
    """
    # import requests
    # resp = requests.get(
    #     f"{EQUIPT_BASE_URL}/{endpoint}",
    #     headers={
    #         "X-API-Key": EQUIPT_API_KEY,
    #         "X-Org-Slug": EQUIPT_ORG_SLUG,
    #         "Accept": "application/json",
    #     },
    #     params=params or {},
    #     timeout=30,
    # )
    # resp.raise_for_status()
    # return resp.json()
    return []


# ── Load functions ────────────────────────────────────────────────────


def load_equipment() -> pd.DataFrame:
    """
    Fetch equipment registry from Equipt.

    Endpoint: candidate — GET /equipment

    Returns: equipmentId, name, category, status, location,
             lastServiceDate, nextServiceDue
    """
    if not ENABLED:
        return pd.DataFrame(columns=[
            "equipmentId", "name", "category", "status", "location",
            "lastServiceDate", "nextServiceDue",
        ])
    return pd.DataFrame()


def load_maintenance() -> pd.DataFrame:
    """
    Fetch maintenance logs.

    Endpoint: candidate — GET /equipment/{id}/maintenance

    Returns: logId, equipmentId, serviceType, completedDate,
             technician, notes, cost
    """
    if not ENABLED:
        return pd.DataFrame(columns=[
            "logId", "equipmentId", "serviceType", "completedDate",
            "technician", "notes", "cost",
        ])
    return pd.DataFrame()


def load_inspections() -> pd.DataFrame:
    """
    Fetch inspection records.

    Endpoint: candidate — GET /equipment/{id}/inspections

    Returns: inspectionId, equipmentId, inspector, date, result, findings
    """
    if not ENABLED:
        return pd.DataFrame(columns=[
            "inspectionId", "equipmentId", "inspector", "date",
            "result", "findings",
        ])
    return pd.DataFrame()


def load_dataset() -> EqptDataset | None:
    """Full Equipt dataset — cached for CACHE_TTL seconds."""
    global _DATASET_CACHE, _CACHE_TIMESTAMP
    now = time.monotonic()
    if _DATASET_CACHE is not None and now - _CACHE_TIMESTAMP < _CACHE_TTL:
        return _DATASET_CACHE

    if not ENABLED:
        ds = _empty_eqpt_dataset()
        _DATASET_CACHE = ds
        _CACHE_TIMESTAMP = now
        return ds

    # ── LIVE path (commented out until credentials are set) ─────────
    # ds = EqptDataset(
    #     equipment=load_equipment(),
    #     maintenance_logs=load_maintenance(),
    #     inspections=load_inspections(),
    # )
    # _DATASET_CACHE = ds
    # _CACHE_TIMESTAMP = now
    # return ds

    return None


# ── Error inspection ──────────────────────────────────────────────────


def inspect_errors(dataset: EqptDataset | None = None) -> dict[str, Any]:
    """
    Inspect the loaded dataset for data-quality issues.

    Call from a REPL:

        from data import equipt as EQP
        ds = EQP.load_dataset()
        issues = EQP.inspect_errors(ds)
    """
    if dataset is None:
        return {"pipeline": "DISABLED — set ENABLED = True to inspect live data"}

    report: dict[str, Any] = {
        "equipment": {"rows": len(dataset.equipment), "missing_name": 0, "overdue_service": 0},
        "maintenance_logs": {"rows": len(dataset.maintenance_logs), "missing_date": 0},
        "inspections": {"rows": len(dataset.inspections), "failed_inspections": 0},
    }

    if not dataset.equipment.empty:
        report["equipment"]["missing_name"] = int(dataset.equipment["name"].isna().sum())
        if "nextServiceDue" in dataset.equipment.columns:
            overdue_mask = pd.to_datetime(
                dataset.equipment["nextServiceDue"], errors="coerce"
            ) < pd.Timestamp.now("US/Central")
            report["equipment"]["overdue_service"] = int(overdue_mask.sum())

    if not dataset.maintenance_logs.empty:
        report["maintenance_logs"]["missing_date"] = int(
            dataset.maintenance_logs["completedDate"].isna().sum()
        )

    if not dataset.inspections.empty and "result" in dataset.inspections.columns:
        report["inspections"]["failed_inspections"] = int(
            (dataset.inspections["result"].str.lower() == "fail").sum()
        )

    return report


# ── Metadata ──────────────────────────────────────────────────────────


def source_label() -> str:
    return "Equipt · equipment tracking & maintenance"


def last_updated() -> str:
    if _DATASET_CACHE is None:
        return "never — ENABLED is False"
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(_CACHE_TIMESTAMP))
