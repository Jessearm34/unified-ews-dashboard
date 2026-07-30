"""Equipt API route — equipment tracking, maintenance, and inspections.

Stub — returns empty KPIs until ``data.equipt.ENABLED = True``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query

try:
    from zoneinfo import ZoneInfo
    _HOUSTON = ZoneInfo("America/Chicago")
except Exception:
    _HOUSTON = timezone.utc

from api.cache import cached
from data import equipt as EQP

router = APIRouter()


def _kpi(label: str, value, unit: str = "", hint: str = "", help: str = "") -> dict:
    return {
        "label": label, "value": value, "unit": unit, "hint": hint or "",
        "rag": None, "platform": "EQ", "delta": None,
        "delta_up_good": True, "help": help, "deltaLabel": "",
    }


# ── Section: Equipment ───────────────────────────────────────────────


def _section_equipment(ds) -> tuple[list[dict], dict[str, dict]]:
    kpis = [
        _kpi("Total Equipment", 0, help="All registered equipment"),
        _kpi("Active Units", 0, help="Equipment currently in service"),
        _kpi("Service Overdue", 0, help="Units past next service date"),
    ]
    return kpis, {}


# ── Section: Maintenance ─────────────────────────────────────────────


def _section_maintenance(ds) -> tuple[list[dict], dict[str, dict]]:
    kpis = [
        _kpi("Service Events", 0, help="Maintenance events in range"),
        _kpi("Total Cost", 0, "$", help="Sum of maintenance costs"),
        _kpi("Avg Cost Per Event", 0, "$"),
    ]
    return kpis, {}


# ── Section: Inspections ─────────────────────────────────────────────


def _section_inspections(ds) -> tuple[list[dict], dict[str, dict]]:
    kpis = [
        _kpi("Inspections", 0, help="Total inspections in range"),
        _kpi("Passed", 0, help="Inspections with passing result"),
        _kpi("Failed", 0, help="Inspections with failing result"),
    ]
    return kpis, {}


_SECTIONS = {
    "equipment": _section_equipment,
    "maintenance": _section_maintenance,
    "inspections": _section_inspections,
}


@router.get("/_api/equipt/{section}")
def equipt_section(section: str = "equipment"):
    now = datetime.now(_HOUSTON).isoformat()

    ds = cached("equipt", EQP.load_dataset)
    handler = _SECTIONS.get(section)
    if handler is None:
        return {
            "kpis": [], "charts": {}, "loaded_at": now,
            "section": section, "error": f"Unknown section: {section}",
        }

    kpis, charts = handler(ds)
    return {
        "kpis": kpis, "charts": charts, "loaded_at": now,
        "section": section,
        "pipeline_status": "ENABLED" if EQP.ENABLED else "DISABLED",
        "source": EQP.source_label(),
    }
