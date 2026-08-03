"""Insperity API route — headcount, Direct/Indirect ratio, regional breakdown.

Reads from the warehouse table ``insperity_workers`` populated by the sync worker.
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


def _kpi(label, value, unit="", hint="", help=""):
    return {"label": label, "value": value, "unit": unit, "hint": hint or "",
            "rag": None, "platform": "IN", "delta": None,
            "delta_up_good": True, "help": help, "deltaLabel": ""}


@router.get("/_api/insperity/{section}")
def insperity_section(section: str = "workers"):
    now = datetime.now(_HOUSTON).isoformat()
    ds = INS.load_dataset()

    if ds is None or ds.workers.empty:
        return {
            "kpis": [_kpi("No Data", "—", help="Waiting for sync worker to populate data")],
            "charts": {}, "loaded_at": now, "section": section,
            "source": INS.source_label(),
        }

    df = ds.workers
    total = len(df)
    direct = int((df["classification"] == "direct").sum())
    indirect = int((df["classification"] == "indirect").sum())
    ratio = f"{direct}:{indirect}" if indirect > 0 else str(direct)

    kpis = [
        _kpi("Total Headcount", total, help="All employees in Insperity"),
        _kpi("Direct (Field)", direct, hint="Field operators & techs",
             help="Hourly field workers — operations"),
        _kpi("Indirect (SGA)", indirect, hint="Support, admin, management",
             help="Selling, General & Administrative"),
        _kpi("Direct:Indirect Ratio", ratio, ":1",
             hint="Lower is leaner — startups run support-heavy early",
             help="Mike Skrbich: 'This should improve as we grow in the Permian'"),
    ]

    # Regional breakdown
    regions = []
    if "region" in df.columns:
        for region in sorted(df["region"].dropna().unique()):
            r_df = df[df["region"] == region]
            r_direct = int((r_df["classification"] == "direct").sum())
            r_indirect = int((r_df["classification"] == "indirect").sum())
            regions.append(f"{region}: {r_direct}D / {r_indirect}I")

    if regions:
        kpis.append(_kpi("Regions", " · ".join(regions), help="Headcount by region"))

    return {
        "kpis": kpis, "charts": {}, "loaded_at": now, "section": section,
        "source": INS.source_label(),
    }
