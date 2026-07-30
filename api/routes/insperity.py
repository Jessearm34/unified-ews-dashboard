"""Insperity API route — worker records and certifications.

Stub — returns empty KPIs until ``data.insperity.ENABLED = True``.

Training data removed — confirmed unavailable by Insperity (2026-07-30).
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
from data import insperity as INS

router = APIRouter()


def _kpi(label: str, value, unit: str = "", hint: str = "", help: str = "") -> dict:
    return {
        "label": label, "value": value, "unit": unit, "hint": hint or "",
        "rag": None, "platform": "IN", "delta": None,
        "delta_up_good": True, "help": help, "deltaLabel": "",
    }


def _section_workers(ds) -> tuple[list[dict], dict[str, dict]]:
    kpis = [
        _kpi("Total Employees", 0, help="Active employees in Insperity"),
        _kpi("Active Workers", 0, help="Currently active / not terminated"),
        _kpi("Contractors", 0, help="1099 / non-employee workers"),
    ]
    return kpis, {}


def _section_certs(ds) -> tuple[list[dict], dict[str, dict]]:
    kpis = [
        _kpi("Active Certifications", 0, help="Total certs on file"),
        _kpi("Expiring Soon (30d)", 0, help="Certs expiring within 30 days"),
        _kpi("Expired", 0, help="Certs past their expiry date"),
    ]
    return kpis, {}


_SECTIONS = {"workers": _section_workers, "certs": _section_certs}


@router.get("/_api/insperity/{section}")
def insperity_section(section: str = "workers"):
    now = datetime.now(_HOUSTON).isoformat()
    ds = cached("insperity", INS.load_dataset)
    handler = _SECTIONS.get(section)
    if handler is None:
        return {"kpis": [], "charts": {}, "loaded_at": now, "section": section, "error": f"Unknown section: {section}"}
    kpis, charts = handler(ds)
    return {
        "kpis": kpis, "charts": charts, "loaded_at": now,
        "section": section,
        "pipeline_status": "ENABLED" if INS.ENABLED else "DISABLED",
        "source": INS.source_label(),
    }
