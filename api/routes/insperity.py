"""Insperity API route — headcount, Direct/Indirect ratio, regional breakdown.

Reads from the warehouse table ``insperity_workers`` populated by the sync worker.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from fastapi import APIRouter, Query

try:
    from zoneinfo import ZoneInfo
    _HOUSTON = ZoneInfo("America/Chicago")
except Exception:
    _HOUSTON = timezone.utc

from data import insperity as INS

router = APIRouter(prefix="/_api", tags=["insperity"])


def _kpi(label: str, value, hint=None, help=None):
    return {"label": label, "value": value, "hint": hint, "help": help,
            "platform": "", "delta_up_good": True}


@router.get("/insperity/workers")
async def insperity_workers():
    ds = INS.load_dataset()
    if ds is None or ds.workers.empty:
        return {"kpis": [_kpi("No Data", "—")], "charts": {}}

    workers = ds.workers.copy()
    total = len(workers)
    direct = int((workers["classification"] == "direct").sum())
    indirect = int((workers["classification"] == "indirect").sum())
    ratio = f"{direct}:{indirect}" if indirect else str(direct)

    kpis = [
        _kpi("Total Headcount", total, help="All active workers in Insperity"),
        _kpi("Direct (Field)", direct, help="Field operators — classified by Insperity department"),
        _kpi("Indirect (Shop)", indirect, help="Shop/office/SGA — classified by Insperity department"),
        _kpi("D:I Ratio", ratio, help="Direct to Indirect headcount ratio"),
    ]

    regions = workers.groupby("region").size().sort_values(ascending=False)
    for region, count in regions.items():
        kpis.append(_kpi(region, count, hint=f"{(count/total*100):.0f}%"))

    rows = []
    for _, w in workers.sort_values(["classification", "last_name", "first_name"]).iterrows():
        cls = str(w.get("classification", ""))
        badge = '<span class="badge green">Field</span>' if cls == "direct" else '<span class="badge">Shop</span>'
        name = f"{w.get('first_name','')} {w.get('last_name','')}".strip()
        rows.append(
            f"<tr><td>{name}</td><td>{badge}</td><td>{w.get('department_name','')}</td>"
            f"<td>{w.get('job_title','')}</td><td>{w.get('region','')}</td></tr>"
        )

    table_html = f"""<div class='tbl-wrap'>
<table class='data'><thead><tr>
<th>Name</th><th>Class</th><th>Department</th><th>Title</th><th>Region</th>
</tr></thead><tbody>{"".join(rows)}</tbody></table></div>"""

    charts = {"worker-table": {"html": table_html, "title": f"Workers ({total})",
                                "help": "Employee roster from Insperity — Field (Direct) vs Shop (Indirect)"}}

    return {
        "kpis": kpis,
        "charts": charts,
        "loaded_at": datetime.now(_HOUSTON).isoformat(),
    }
