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

router = APIRouter()


def _kpi(label, value, unit="", hint="", help=""):
    return {"label": label, "value": value, "unit": unit, "hint": hint or "",
            "rag": None, "platform": "IN", "delta": None,
            "delta_up_good": True, "help": help, "deltaLabel": ""}


def _worker_classification_table(df) -> str:
    """HTML table of workers with their classifications."""
    if df.empty:
        return "<div class='chart-empty'>No worker data yet</div>"
    rows = []
    for _, r in df.iterrows():
        name = f"{r.get('first_name','')} {r.get('last_name','')}".strip()
        cls = str(r.get("classification", ""))
        badge = '<span class="badge green">Direct</span>' if cls == "direct" else '<span class="badge">Indirect</span>'
        dept = r.get("department_name") or "—"
        job = r.get("job_title") or "—"
        region = r.get("region") or "—"
        rows.append(f"<tr><td>{name}</td><td>{badge}</td><td>{dept}</td><td>{job}</td><td>{region}</td></tr>")
    return f"""<div class='tbl-wrap'>
<table class='data'><thead><tr><th>Name</th><th>Classification</th><th>Department</th><th>Job Title</th><th>Region</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>"""


# ── Workers Section ──────────────────────────────────────────────────


def _workers_section(ds):
    df = ds.workers.sort_values("last_name") if not ds.workers.empty else ds.workers
    total = len(df)
    direct = int((df["classification"] == "direct").sum())
    indirect = int((df["classification"] == "indirect").sum())
    ratio = f"{direct}:{indirect}" if indirect > 0 else str(direct)

    kpis = [
        _kpi("Total Headcount", total),
        _kpi("Direct (Field)", direct, hint="Field operators & techs"),
        _kpi("Indirect (SGA)", indirect, hint="Support, admin, management"),
        _kpi("Direct:Indirect Ratio", ratio, ":1"),
    ]

    regions = []
    if "region" in df.columns:
        for region in sorted(df["region"].dropna().unique()):
            r_df = df[df["region"] == region]
            r_direct = int((r_df["classification"] == "direct").sum())
            r_indirect = int((r_df["classification"] == "indirect").sum())
            regions.append(f"{region}: {r_direct}D / {r_indirect}I")
    if regions:
        kpis.append(_kpi("Regions", " · ".join(regions)))

    charts = {"worker-table": {"html": _worker_classification_table(df), "title": f"Worker Classification ({total} total)"}}
    return kpis, charts


# ── Certifications Section (SiteDocs ↔ Insperity) ────────────────────


def _certs_section(ds):
    """Cross-reference Insperity workers with SiteDocs certification data."""
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

    # Build a lookup: SiteDocs worker name (lower) → list of cert names
    if not sd_workers.empty:
        w_lookup = dict(zip(
            (sd_workers["FirstName"].fillna("").str.lower() + " " + sd_workers["LastName"].fillna("").str.lower()).str.strip(),
            sd_workers["Id"]
        ))
    else:
        w_lookup = {}

    # Map certs to worker names
    cert_records = SD.cert_records(certs, sd_workers)
    if cert_records.empty:
        return [_kpi("No Cert Records", "—")], {}

    today = date.today()
    rows = []
    total_with_certs = 0
    total_certs_count = 0
    total_expired = 0
    total_expiring = 0
    no_match_names = []

    for _, w in workers.iterrows():
        full = f"{w.get('first_name','')} {w.get('last_name','')}".strip()
        if not full:
            continue
        full_lower = full.lower()

        # Try exact match first, then first-name-only match
        w_certs = cert_records[cert_records["_WorkerName"].str.lower().str.strip() == full_lower]
        if len(w_certs) == 0:
            # Try matching by last name only (SiteDocs sometimes only has last name)
            last = str(w.get("last_name", "")).strip().lower()
            if last:
                w_certs = cert_records[cert_records["_WorkerName"].str.lower().str.contains(last, na=False)]
        if len(w_certs) == 0:
            # Try matching by first name only  
            first = str(w.get("first_name", "")).strip().lower()
            if first:
                w_certs = cert_records[cert_records["_WorkerName"].str.lower().str.contains(first, na=False)]

        has = len(w_certs) > 0
        if not has:
            no_match_names.append(full)

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

    if no_match_names and len(no_match_names) <= 5:
        kpis.append(_kpi("No Match", ", ".join(no_match_names), help="Insperity names not found in SiteDocs"))

    table_html = f"""<div class='tbl-wrap'>
<table class='data'><thead><tr>
<th>Name</th><th>Class</th><th>Status</th><th>Active</th><th>Expiring</th><th>Expired</th><th>Certs</th>
</tr></thead><tbody>{"".join(rows)}</tbody></table></div>"""

    charts = {"cert-table": {"html": table_html, "title": f"SiteDocs Certifications × Insperity ({len(workers)} workers, {total_with_certs} with certs)"}}
    return kpis, charts


# ── Route ─────────────────────────────────────────────────────────────


@router.get("/_api/insperity/{section}")
def insperity_section(section: str = "workers"):
    now = datetime.now(_HOUSTON).isoformat()
    ds = INS.load_dataset()

    if ds is None or ds.workers.empty:
        return {"kpis": [_kpi("No Data", "—")], "charts": {}, "loaded_at": now, "section": section}

    if section == "workers":
        kpis, charts = _workers_section(ds)
    elif section == "certs":
        kpis, charts = _certs_section(ds)
    else:
        return {"kpis": [], "charts": {}, "loaded_at": now, "section": section, "error": f"Unknown section: {section}"}

    return {"kpis": kpis, "charts": charts, "loaded_at": now, "section": section, "source": INS.source_label()}
