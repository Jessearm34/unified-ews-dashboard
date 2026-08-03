"""Insperity API route — headcount, Direct/Indirect ratio, regional breakdown, worker table.

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


def _worker_table(df) -> str:
    """Build an HTML table of workers with their classifications."""
    if df.empty:
        return "<div class='chart-empty'>No worker data yet</div>"

    rows = []
    for _, r in df.iterrows():
        name = f"{r.get('first_name','')} {r.get('last_name','')}".strip()
        cls = str(r.get("classification", "")).strip()
        badge = '<span class="badge green">Direct</span>' if cls == "direct" else '<span class="badge">Indirect</span>'
        dept = r.get("department_name") or "—"
        job = r.get("job_title") or "—"
        region = r.get("region") or "—"
        rows.append(f"<tr><td>{name}</td><td>{badge}</td><td>{dept}</td><td>{job}</td><td>{region}</td></tr>")

    return f"""<div class='tbl-wrap'>
<table class='data'>
<thead><tr><th>Name</th><th>Classification</th><th>Department</th><th>Job Title</th><th>Region</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table></div>"""


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

    df = ds.workers.sort_values("last_name") if not ds.workers.empty else ds.workers
    total = len(df)
    direct = int((df["classification"] == "direct").sum())
    indirect = int((df["classification"] == "indirect").sum())
    ratio = f"{direct}:{indirect}" if indirect > 0 else str(direct)

    kpis = [
        _kpi("Total Headcount", total, help="All employees in Insperity"),
        _kpi("Direct (Field)", direct, hint="Field operators & techs"),
        _kpi("Indirect (SGA)", indirect, hint="Support, admin, management"),
        _kpi("Direct:Indirect Ratio", ratio, ":1",
             hint="Lower is leaner — startups run support-heavy early"),
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
        kpis.append(_kpi("Regions", " · ".join(regions)))

    charts = {
        "worker-table": {
            "html": _worker_table(df),
            "title": f"Worker Classification ({total} total)",
        }
    }

    return {
        "kpis": kpis, "charts": charts, "loaded_at": now, "section": section,
        "source": INS.source_label(),
    }
