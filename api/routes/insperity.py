"""Insperity API route — headcount, Direct/Indirect ratio, worker cross-reference with SiteDocs certifications.

Reads from the warehouse tables populated by the sync worker and SiteDocs.
"""

from __future__ import annotations

from datetime import datetime, timezone, date, timedelta

import pandas as pd
from fastapi import APIRouter, Query

try:
    from zoneinfo import ZoneInfo
    _HOUSTON = ZoneInfo("America/Chicago")
except Exception:
    _HOUSTON = timezone.utc

from data import insperity as INS
from data import sd_data as SD
from api.csv_export import to_csv_response

router = APIRouter(prefix="/_api", tags=["insperity"])


def _kpi(label: str, value, hint=None, help=None, delta_up_good=True):
    return {"label": label, "value": value, "hint": hint, "help": help, "delta_up_good": delta_up_good}


@router.get("/insperity/{section}")
async def insperity_section(section: str, format: str | None = None):
    ds = INS.load_dataset()
    if ds is None or ds.workers.empty:
        return {"kpis": [_kpi("No Data", "—")], "charts": {}}

    if section == "workers":
        kpis, charts = _workers_section(ds)
    elif section == "certs":
        kpis, charts = _certs_section(ds)
    else:
        return {"kpis": [_kpi("Unknown", section)], "charts": {}}

    if format == "csv":
        return _export_csv(section, ds)

    return {
        "kpis": kpis,
        "charts": charts,
        "loaded_at": datetime.now(_HOUSTON).isoformat(),
    }


def _export_csv(section: str, ds):
    if section == "workers":
        df = ds.workers.copy()
    elif section == "certs":
        sd_ds = SD.sd_load_dataset()
        if sd_ds and not sd_ds.certifications.empty:
            cert_records = SD.cert_records(sd_ds.certifications, sd_ds.workers)
            workers = ds.workers.copy()
            rows = []
            for _, w in workers.iterrows():
                full = f"{w.get('first_name','')} {w.get('last_name','')}".strip()
                w_certs = cert_records[cert_records["_WorkerName"].str.lower().str.strip() == full.lower()]
                rows.append({
                    "name": full,
                    "classification": w.get("classification"),
                    "cert_count": len(w_certs),
                    "department": w.get("department_name"),
                })
            df = pd.DataFrame(rows)
        else:
            df = pd.DataFrame()
    else:
        df = pd.DataFrame()

    return to_csv_response(df, filename=f"insperity_{section}_{date.today().isoformat()}.csv")


def _workers_section(ds):
    workers = ds.workers.copy()
    total = len(workers)
    direct = int((workers["classification"] == "direct").sum())
    indirect = int((workers["classification"] == "indirect").sum())
    ratio = f"{direct}:{indirect}" if indirect else str(direct)

    kpis = [
        _kpi("Total Headcount", total),
        _kpi("Direct", direct),
        _kpi("Indirect", indirect),
        _kpi("D:I Ratio", ratio),
    ]

    regions = workers.groupby("region").size().sort_values(ascending=False)
    for region, count in regions.items():
        kpis.append(_kpi(f"  {region}", count, hint=f"{(count/total*100):.0f}%"))

    rows = []
    for _, w in workers.sort_values(["classification", "last_name", "first_name"]).iterrows():
        cls = str(w.get("classification", ""))
        badge = '<span class="badge green">Direct</span>' if cls == "direct" else '<span class="badge">Indirect</span>'
        name = f"{w.get('first_name','')} {w.get('last_name','')}".strip()
        rows.append(
            f"<tr><td>{name}</td><td>{badge}</td><td>{w.get('department_name','')}</td>"
            f"<td>{w.get('job_title','')}</td><td>{w.get('region','')}</td></tr>"
        )

    table_html = f"""<div class='tbl-wrap'>
<table class='data'><thead><tr>
<th>Name</th><th>Class</th><th>Department</th><th>Title</th><th>Region</th>
</tr></thead><tbody>{"".join(rows)}</tbody></table></div>"""

    charts = {"worker-table": {"html": table_html, "title": f"All Workers ({total})"}}
    return kpis, charts


def _certs_section(ds):
    workers = ds.workers.copy()
    if workers.empty:
        return [_kpi("No Worker Data", "—")], {}

    sd_ds = SD.sd_load_dataset()
    if sd_ds is None or sd_ds.certifications.empty:
        return [
            _kpi("No SiteDocs Certs", "—",
                 help="SiteDocs certification tracking may not be set up yet"),
            _kpi("Workers Tracked", len(workers),
                 help="Insperity workers waiting for SiteDocs cert data"),
        ], {}

    certs = sd_ds.certifications
    sd_workers = sd_ds.workers
    cert_records = SD.cert_records(certs, sd_workers)
    if cert_records.empty:
        return [_kpi("No Cert Records", "—")], {}

    today = date.today()
    rows = []
    total_with_certs = 0
    total_certs_count = 0
    total_expired = 0
    total_expiring = 0

    for _, w in workers.iterrows():
        full = f"{w.get('first_name','')} {w.get('last_name','')}".strip()
        if not full:
            continue
        full_lower = full.lower()

        w_certs = cert_records[cert_records["_WorkerName"].str.lower().str.strip() == full_lower]
        if len(w_certs) == 0:
            last = str(w.get("last_name", "")).strip().lower()
            if last:
                w_certs = cert_records[cert_records["_WorkerName"].str.lower().str.contains(last, na=False)]
            if len(w_certs) == 0:
                first = str(w.get("first_name", "")).strip().lower()
                if first:
                    w_certs = cert_records[cert_records["_WorkerName"].str.lower().str.contains(first, na=False)]

        has = len(w_certs) > 0

        if has:
            total_with_certs += 1
            active = 0
            expired = 0
            expiring = 0
            cert_names = []
            for _, c in w_certs.iterrows():
                total_certs_count += 1
                name = c.get("Name") or c.get("CertificationName") or c.get("Type") or "Cert"
                cert_names.append(str(name))
                expires = c.get("Expires")
                if pd.notna(expires):
                    try:
                        if expires.date() < today:
                            expired += 1
                            total_expired += 1
                        elif expires.date() <= today + timedelta(days=30):
                            expiring += 1
                            total_expiring += 1
                        else:
                            active += 1
                    except Exception:
                        active += 1
                else:
                    active += 1

            status = "⚠️" if expired > 0 else ("⏰" if expiring > 0 else "✅")
            detail = "; ".join(cert_names[:3])
            if len(cert_names) > 3:
                detail += f" +{len(cert_names)-3} more"
        else:
            active = expired = expiring = 0
            detail = "—"
            status = "—"

        cls = str(w.get("classification", ""))
        badge = '<span class="badge green">Direct</span>' if cls == "direct" else '<span class="badge">Indirect</span>'
        rows.append(f"<tr><td>{full}</td><td>{badge}</td><td class='num'>{status}</td><td class='num'>{active}</td><td class='num'>{expiring}</td><td class='num'>{expired}</td><td>{detail}</td></tr>")

    kpis = [
        _kpi("Workers with Certs", total_with_certs, hint=f"of {len(workers)} total"),
        _kpi("Total Certifications", total_certs_count),
        _kpi("Expired", total_expired),
        _kpi("Expiring (30d)", total_expiring),
    ]

    table_html = f"""<div class='tbl-wrap'>
<table class='data'><thead><tr>
<th>Name</th><th>Class</th><th>Status</th><th>Active</th><th>Expiring</th><th>Expired</th><th>Certs</th>
</tr></thead><tbody>{"".join(rows)}</tbody></table></div>"""

    charts = {"cert-table": {"html": table_html, "title": f"SiteDocs Certifications × Insperity ({len(workers)} workers, {total_with_certs} with certs)"}}
    return kpis, charts
