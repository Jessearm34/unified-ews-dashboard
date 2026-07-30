"""Insperity API route — worker records and org structure.

Reads from the warehouse tables populated by the sync worker (pull_insperity.py).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query

try:
    from zoneinfo import ZoneInfo
    _HOUSTON = ZoneInfo("America/Chicago")
except Exception:
    _HOUSTON = timezone.utc

from data import insperity as INS

router = APIRouter()


@router.get("/_api/insperity/{section}")
def insperity_section(section: str = "workers"):
    now = datetime.now(_HOUSTON).isoformat()
    ds = INS.load_dataset()

    if ds is None or not ds.has_data:
        return {
            "kpis": [], "charts": {},
            "loaded_at": now, "section": section,
            "pipeline_status": "No data yet — waiting for sync worker",
            "source": INS.source_label(),
        }

    if section == "workers":
        kpis = [
            {"label": "Total Employees", "value": len(ds.employees), "unit": "", "hint": "", "platform": "IN", "help": "All employees in Insperity"},
            {"label": "Active", "value": int((ds.employees["status"].str.lower() == "active").sum()) if "status" in ds.employees.columns else 0, "unit": "", "hint": "", "platform": "IN"},
            {"label": "Departments", "value": len(ds.departments), "unit": "", "hint": "", "platform": "IN"},
            {"label": "Locations", "value": len(ds.locations), "unit": "", "hint": "", "platform": "IN"},
        ]
        charts = {}
    elif section == "certs":
        kpis = [
            {"label": "Certifications", "value": "—", "unit": "", "hint": "Not available via Insperity API", "platform": "IN"},
        ]
        charts = {}
    else:
        return {"kpis": [], "charts": {}, "loaded_at": now, "section": section, "error": f"Unknown section: {section}"}

    return {
        "kpis": [{**k, "rag": None, "delta": None, "delta_up_good": True, "deltaLabel": ""} for k in kpis],
        "charts": charts, "loaded_at": now, "section": section,
        "source": INS.source_label(),
    }
