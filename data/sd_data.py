"""Data loading and aggregation for the SiteDocs safety dashboard.

All numbers come from the PostgreSQL warehouse (``sitedocs_*`` tables) OR from
the live SiteDocs API directly via ``sitedocs_client.py``.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text

_CACHE_TTL = 60
_DATASET_CACHE: SdDataset | None = None
_CACHE_TIMESTAMP: float = 0.0


@lru_cache(maxsize=1)
def sd_engine():
    url = os.environ.get("SD_DATABASE_URL", "")
    if not url:
        raise RuntimeError("SD_DATABASE_URL environment variable is not set.")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://") and "+psycopg2" not in url:
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    connect_args = {"sslmode": "require"}
    return create_engine(url, connect_args=connect_args)


@dataclass
class SdDataset:
    workers: pd.DataFrame
    equipment: pd.DataFrame
    incidents: pd.DataFrame
    certifications: pd.DataFrame
    forms: pd.DataFrame = field(default_factory=pd.DataFrame)
    signatures: pd.DataFrame = field(default_factory=pd.DataFrame)
    locations: pd.DataFrame = field(default_factory=pd.DataFrame)
    formtypes: pd.DataFrame = field(default_factory=pd.DataFrame)
    schedules: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def has_data(self) -> bool:
        return not self.workers.empty


# --------------------------------------------------------------------------- #
# Loaders
# --------------------------------------------------------------------------- #


def _parse_date(val: Any) -> pd.Timestamp | pd.NaT:
    try:
        return pd.to_datetime(val)
    except (ValueError, TypeError):
        return pd.NaT


def _clean_bool(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return bool(val)


def sd_load_dataset() -> SdDataset:
    global _DATASET_CACHE, _CACHE_TIMESTAMP
    now = time.time()
    if _DATASET_CACHE and (now - _CACHE_TIMESTAMP < _CACHE_TTL):
        return _DATASET_CACHE

    # Try warehouse first, then fall back to stub data from CSV export
    def safe_read(table):
        try:
            return sd_read_table(table)
        except RuntimeError:
            return pd.DataFrame()

    workers = safe_read("sitedocs_workers")
    equipment = safe_read("sitedocs_equipment")
    incidents = safe_read("sitedocs_incidents")
    certifications = safe_read("sitedocs_certifications")
    forms = safe_read("sitedocs_forms")
    signatures = safe_read("sitedocs_signatures")
    locations = safe_read("sitedocs_locations")
    formtypes = safe_read("sitedocs_formtypes")
    schedules = safe_read("sitedocs_schedules")

    if not workers.empty:
        # Parse date columns
        for col in ("DateHired",):
            if col in workers.columns:
                workers[col] = workers[col].apply(_parse_date)
        # Normalise boolean
        if "Active" in workers.columns:
            workers["Active"] = workers["Active"].apply(_clean_bool)

        for col in ("CreatedOn",):
            if col in incidents.columns:
                incidents[col] = incidents[col].apply(_parse_date)
            if col in forms.columns:
                forms[col] = forms[col].apply(_parse_date)
        if "CreatedOn" in equipment.columns:
            equipment["CreatedOn"] = equipment["CreatedOn"].apply(_parse_date)

        for col in ("Acquired", "Expires"):
            if col in certifications.columns:
                certifications[col] = certifications[col].apply(_parse_date)

    ds = SdDataset(
        workers=workers,
        equipment=equipment,
        incidents=incidents,
        certifications=certifications,
        forms=forms,
        signatures=signatures,
        locations=locations,
        formtypes=formtypes,
        schedules=schedules,
    )
    _DATASET_CACHE = ds
    _CACHE_TIMESTAMP = now
    return ds


def sd_read_table(table: str) -> pd.DataFrame:
    """Read a raw landing table from the warehouse (all columns as text)."""
    try:
        return pd.read_sql(f'SELECT * FROM {table}', sd_engine())
    except Exception as exc:
        raise RuntimeError(
            f"Could not read '{table}' from the warehouse. "
            f"Check SD_DATABASE_URL and ensure the ingest has run. "
            f"Original error: {exc}"
        ) from exc


# --------------------------------------------------------------------------- #
# Workers
# --------------------------------------------------------------------------- #


def worker_counts(workers: pd.DataFrame) -> dict[str, int]:
    if workers.empty:
        return {"total": 0, "active": 0, "inactive": 0, "employees": 0, "contractors": 0}
    total = len(workers)
    if "Active" in workers.columns:
        active = int(workers["Active"].sum())
    else:
        active = total
    inactive = total - active

    if "IsExternal" in workers.columns:
        employees = int((~workers["IsExternal"].astype(bool)).sum())
        contractors = int(workers["IsExternal"].astype(bool).sum())
    elif "ContractorName" in workers.columns:
        contractors = int(workers["ContractorName"].notna().sum())
        employees = total - contractors
    else:
        employees = total
        contractors = 0

    return {"total": total, "active": active, "inactive": inactive,
            "employees": employees, "contractors": contractors}


def worker_roster(workers: pd.DataFrame) -> pd.DataFrame:
    """Return sorted worker list with derived display fields."""
    if workers.empty:
        return workers
    df = workers.copy()
    df["_Name"] = df["FirstName"].fillna("") + " " + df["LastName"].fillna("")
    df["_Company"] = df["ContractorName"].fillna("Energy Water Solutions")
    df["_Type"] = df["IsExternal"].apply(lambda v: "Contractor" if v else "Employee") if "IsExternal" in df.columns else "Employee"
    df["_ActiveLabel"] = df["Active"].apply(lambda v: "Active" if v else "Inactive") if "Active" in df.columns else "Active"
    return df.sort_values("LastName").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Certifications
# --------------------------------------------------------------------------- #


def cert_summary(certs: pd.DataFrame, workers: pd.DataFrame) -> dict[str, Any]:
    if certs.empty:
        return {"total": 0, "active": 0, "expiring": 0, "expired": 0, "no_date": 0,
                "unique_workers_with_certs": 0, "coverage_pct": 0.0}
    total = len(certs)
    today = pd.Timestamp(date.today())
    has_expires = certs["Expires"].notna()
    expired = int((has_expires & (certs["Expires"] < today)).sum()) if has_expires.any() else 0
    expiring = int((has_expires & (certs["Expires"] >= today) & (certs["Expires"] <= today + timedelta(days=90))).sum()) if has_expires.any() else 0
    active = int((has_expires & (certs["Expires"] >= today)).sum()) if has_expires.any() else 0
    no_date = int((~has_expires).sum()) if has_expires.any() else 0
    trained = certs["WorkerId"].nunique() if "WorkerId" in certs.columns else 0
    total_w = len(workers)
    coverage = (trained / total_w * 100) if total_w else 0.0
    return {"total": total, "active": active + no_date, "expiring": expiring,
            "expired": expired, "no_date": no_date,
            "unique_workers_with_certs": trained, "coverage_pct": coverage}


def cert_type_breakdown(certs: pd.DataFrame) -> pd.DataFrame:
    if certs.empty:
        return pd.DataFrame(columns=["CertificationType", "Active", "Expired", "Expiring", "Total"])
    today = pd.Timestamp(date.today())
    df = certs.copy()
    df["_status"] = "Active"
    has_expires = df["Expires"].notna()
    df.loc[has_expires & (df["Expires"] < today), "_status"] = "Expired"
    df.loc[has_expires & (df["Expires"] >= today) & (df["Expires"] <= today + timedelta(days=90)), "_status"] = "Expiring"

    type_col = "CertificationTypeName"
    if type_col not in df.columns:
        return pd.DataFrame(columns=["CertificationType", "Active", "Expired", "Expiring", "Total"])

    piv = df.pivot_table(index=type_col, columns="_status", aggfunc="size", fill_value=0)
    for c in ("Active", "Expired", "Expiring"):
        if c not in piv.columns:
            piv[c] = 0
    piv["Total"] = piv.sum(axis=1)
    piv = piv.reset_index().sort_values("Total", ascending=False).rename(columns={type_col: "CertificationType"})
    return piv[["CertificationType", "Active", "Expiring", "Expired", "Total"]]


def cert_records(certs: pd.DataFrame, workers: pd.DataFrame) -> pd.DataFrame:
    """Join certs with workers to get worker names."""
    if certs.empty:
        return certs
    w = workers[["Id", "FirstName", "LastName"]].copy()
    w["_WorkerName"] = w["FirstName"].fillna("") + " " + w["LastName"].fillna("")
    merged = certs.merge(w, left_on="WorkerId", right_on="Id", how="left", suffixes=("", "_w"))
    merged["_WorkerName"] = merged["_WorkerName"].fillna(merged["WorkerId"])
    return merged.sort_values("Expires", ascending=True).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Incidents
# --------------------------------------------------------------------------- #


def incident_counts(incidents: pd.DataFrame) -> dict[str, Any]:
    if incidents.empty:
        return {"total": 0, "open": 0, "closed": 0, "investigation": 0, "ytd": 0}
    count = len(incidents)
    status_col = "LatestStatus"
    open_ = int((incidents[status_col].astype(str).str.lower() == "open").sum())
    closed = int((incidents[status_col].astype(str).str.lower() == "closed").sum())
    inv = int((incidents[status_col].astype(str).str.lower() == "investigation").sum())

    today = date.today()
    ytd_start = date(today.year, 1, 1)
    if "CreatedOn" in incidents.columns:
        inc_dates = incidents["CreatedOn"].dt.date
        ytd = int((inc_dates >= ytd_start).sum())
    else:
        ytd = 0

    return {"total": count, "open": open_, "closed": closed,
            "investigation": inv, "ytd": ytd}


def incident_monthly_trend(incidents: pd.DataFrame) -> pd.DataFrame:
    if incidents.empty or "CreatedOn" not in incidents.columns:
        return pd.DataFrame(columns=["Month", "Count"])
    df = incidents.dropna(subset=["CreatedOn"]).copy()
    if df.empty:
        return pd.DataFrame(columns=["Month", "Count"])
    df["Month"] = df["CreatedOn"].dt.to_period("M").dt.to_timestamp()
    result = df.groupby("Month").size().reset_index(name="Count")
    return result.sort_values("Month").reset_index(drop=True)


def incident_by_type(incidents: pd.DataFrame) -> pd.DataFrame:
    if incidents.empty:
        return pd.DataFrame()
    col = "TypeName"
    if col not in incidents.columns:
        return pd.DataFrame()
    return incidents.groupby(col).size().reset_index(name="Count").sort_values("Count", ascending=False)


def incident_by_status(incidents: pd.DataFrame) -> pd.DataFrame:
    if incidents.empty:
        return pd.DataFrame()
    col = "LatestStatus"
    if col not in incidents.columns:
        return pd.DataFrame()
    return incidents.groupby(col).size().reset_index(name="Count").sort_values("Count", ascending=False)


# --------------------------------------------------------------------------- #
# Equipment
# --------------------------------------------------------------------------- #


def equipment_counts(equipment: pd.DataFrame) -> dict[str, int]:
    if equipment.empty:
        return {"total": 0, "active": 0, "inactive": 0}
    total = len(equipment)
    if "IsDeleted" in equipment.columns:
        active = int((~equipment["IsDeleted"].astype(bool)).sum())
        inactive = int(equipment["IsDeleted"].astype(bool).sum())
    else:
        active = total
        inactive = 0
    return {"total": total, "active": active, "inactive": inactive}


def equipment_by_type(equipment: pd.DataFrame) -> pd.DataFrame:
    if equipment.empty:
        return pd.DataFrame()
    col = "EquipmentTypeName"
    if col not in equipment.columns:
        return pd.DataFrame()
    return equipment.groupby(col).size().reset_index(name="Count").sort_values("Count", ascending=False)


# --------------------------------------------------------------------------- #
# Forms
# --------------------------------------------------------------------------- #


def form_counts(forms: pd.DataFrame) -> dict[str, int]:
    if forms.empty:
        return {"total": 0, "month": 0}
    now = pd.Timestamp.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = len(forms)
    if "createdOn" in forms.columns:
        month = int((pd.to_datetime(forms["createdOn"]) >= month_start).sum())
    elif "CreatedOn" in forms.columns:
        month = int((pd.to_datetime(forms["CreatedOn"]) >= month_start).sum())
    else:
        month = 0
    return {"total": total, "month": month}


def signature_counts(sigs: pd.DataFrame) -> dict[str, int]:
    if sigs.empty:
        return {"total": 0, "has_image": 0}
    total = len(sigs)
    has_img = int(sigs["ImageId"].notna().sum()) if "ImageId" in sigs.columns else 0
    return {"total": total, "has_image": has_img}


def location_counts(locs: pd.DataFrame) -> dict[str, int]:
    if locs.empty:
        return {"total": 0}
    return {"total": len(locs)}


def form_type_counts(ft: pd.DataFrame) -> int:
    return len(ft) if not ft.empty else 0


def schedule_counts(sched: pd.DataFrame) -> dict[str, int]:
    if sched.empty:
        return {"total": 0, "completed": 0, "scheduled": 0, "late": 0, "cancelled": 0, "overdue": 0,
                "completion_pct": 0.0}
    total = len(sched)
    status_col = "status"
    completed = int((sched[status_col].astype(str).str.lower() == "completed").sum()) if status_col in sched.columns else 0
    scheduled = int((sched[status_col].astype(str).str.lower() == "scheduled").sum()) if status_col in sched.columns else 0
    late = int((sched[status_col].astype(str).str.lower() == "late").sum()) if status_col in sched.columns else 0
    cancelled = int((sched[status_col].astype(str).str.lower() == "cancelled").sum()) if status_col in sched.columns else 0
    overdue = int((sched[status_col].astype(str).str.lower() == "overdue").sum()) if status_col in sched.columns else 0
    completion_pct = (completed / total * 100) if total else 0.0
    return {"total": total, "completed": completed, "scheduled": scheduled,
            "late": late, "cancelled": cancelled, "overdue": overdue,
            "completion_pct": completion_pct}


def forms_monthly_trend(forms: pd.DataFrame) -> pd.DataFrame:
    if forms.empty or "CreatedOn" not in forms.columns:
        return pd.DataFrame(columns=["Month", "Count"])
    df = forms.dropna(subset=["CreatedOn"]).copy()
    if df.empty:
        return pd.DataFrame(columns=["Month", "Count"])
    df["Month"] = df["CreatedOn"].dt.to_period("M").dt.to_timestamp()
    result = df.groupby("Month").size().reset_index(name="Count")
    return result.sort_values("Month").reset_index(drop=True)


def form_types_with_counts(formtypes: pd.DataFrame, forms: pd.DataFrame) -> pd.DataFrame:
    """Return form types with submission counts from the forms table."""
    if formtypes.empty:
        return pd.DataFrame(columns=["FormType", "Count"])
    if "DocumentTemplateName" in forms.columns:
        type_counts = forms["DocumentTemplateName"].value_counts().reset_index()
        type_counts.columns = ["FormType", "Count"]
        return type_counts.sort_values("Count", ascending=False)
    # Fallback: just list the form types
    ft = formtypes.copy()
    ft["Count"] = 0
    return ft[["Name", "Count"]].rename(columns={"Name": "FormType"})


# --------------------------------------------------------------------------- #
# RAG (Red / Amber / Green) thresholds & helpers
# --------------------------------------------------------------------------- #

def rag_status(value: float, green: float, amber: float, good_when_high: bool = True) -> str:
    """Return 'green', 'amber', or 'red' based on threshold comparison.
    
    good_when_high=True: green means value >= green threshold (e.g. completion %)
    good_when_high=False: green means value <= green threshold (e.g. overdue count)
    """
    if good_when_high:
        if value >= green: return "green"
        if value >= amber: return "amber"
        return "red"
    else:
        if value <= green: return "green"
        if value <= amber: return "amber"
        return "red"


def rag_color(status: str) -> str:
    return {"green": "#16a34a", "amber": "#ea580c", "red": "#dc2626"}.get(status, "#64748b")


def rag_badge(status: str) -> str:
    return {"green": "✓ On Track", "amber": "⚠ Caution", "red": "● Critical"}.get(status, "—")


# --------------------------------------------------------------------------- #
# Worker participation
# --------------------------------------------------------------------------- #

def worker_participation(workers: pd.DataFrame, forms: pd.DataFrame) -> dict:
    """What % of active workers submitted >= 1 form this month."""
    if workers.empty or forms.empty:
        return {"active_workers": 0, "participating": 0, "pct": 0.0, "non_participating": 0}
    now = pd.Timestamp.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    active = workers[workers["Active"].astype(bool)] if "Active" in workers.columns else workers
    active_ids = set(active["Id"].dropna())
    if "createdOn" in forms.columns:
        month_forms = forms[pd.to_datetime(forms["createdOn"]) >= month_start]
    elif "CreatedOn" in forms.columns:
        month_forms = forms[pd.to_datetime(forms["CreatedOn"]) >= month_start]
    else:
        return {"active_workers": len(active_ids), "participating": 0, "pct": 0.0, "non_participating": len(active_ids)}
    # Match by worker ID
    if "createdBy" in month_forms.columns:
        submitters = set(month_forms["createdBy"].dropna())
    elif "CreatedBy" in month_forms.columns:
        submitters = set(month_forms["CreatedBy"].dropna())
    else:
        submitters = set()
    participating = len(active_ids & submitters)
    return {
        "active_workers": len(active_ids),
        "participating": participating,
        "pct": (participating / len(active_ids) * 100) if active_ids else 0.0,
        "non_participating": len(active_ids) - participating,
    }


# --------------------------------------------------------------------------- #
# Overdue schedule items
# --------------------------------------------------------------------------- #

def overdue_items(schedules: pd.DataFrame) -> pd.DataFrame:
    """Return overdue and late schedule items with location and worker info."""
    if schedules.empty:
        return pd.DataFrame(columns=["formTypeName", "locationName", "responsibleEmployeeName",
                                      "status", "formDueOn", "daysOverdue"])
    df = schedules[schedules["status"].isin(["Late", "Overdue"])].copy()
    if df.empty:
        return pd.DataFrame(columns=["formTypeName", "locationName", "responsibleEmployeeName",
                                      "status", "formDueOn", "daysOverdue"])
    if "formDueOn" in df.columns:
        df["formDueOn"] = pd.to_datetime(df["formDueOn"])
        now = pd.Timestamp.now()
        df["daysOverdue"] = (now - df["formDueOn"]).dt.days
    else:
        df["daysOverdue"] = 0
    cols = ["formTypeName", "locationName", "responsibleEmployeeName", "status", "formDueOn", "daysOverdue"]
    available = [c for c in cols if c in df.columns]
    result = df[available].sort_values("daysOverdue", ascending=False).head(20)
    return result


# --------------------------------------------------------------------------- #
# Worker leaderboard
# --------------------------------------------------------------------------- #

def worker_leaderboard(workers: pd.DataFrame, forms: pd.DataFrame,
                       signatures: pd.DataFrame, schedules: pd.DataFrame) -> pd.DataFrame:
    """Per-worker activity: forms submitted, signatures, schedule items, completion %."""
    if workers.empty:
        return pd.DataFrame(columns=["Worker", "Forms", "Signatures", "Schedules", "CompletionPct"])
    active = workers[workers["Active"].astype(bool)] if "Active" in workers.columns else workers
    rows = []
    for _, w in active.iterrows():
        wid = w["Id"]
        name = f"{w.get('FirstName','')} {w.get('LastName','')}".strip()
        # Forms count
        if "createdBy" in forms.columns:
            fc = int((forms["createdBy"] == wid).sum())
        elif "CreatedBy" in forms.columns:
            fc = int((forms["CreatedBy"] == wid).sum())
        else:
            fc = 0
        # Signatures count
        if "SignatoryId" in signatures.columns:
            sc = int((signatures["SignatoryId"] == wid).sum())
        elif "signatoryId" in signatures.columns:
            sc = int((signatures["signatoryId"] == wid).sum())
        else:
            sc = 0
        # Schedule items
        if "workerId" in schedules.columns:
            sw = schedules[schedules["workerId"] == wid]
            st = len(sw)
            sc_comp = int((sw["status"] == "Completed").sum()) if "status" in sw.columns else 0
            scomp_pct = (sc_comp / st * 100) if st > 0 else 0.0
        else:
            st = 0
            scomp_pct = 0.0
        if fc > 0 or sc > 0 or st > 0:
            rows.append({"Worker": name, "Forms": fc, "Signatures": sc,
                        "Schedules": st, "CompletionPct": scomp_pct})
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["Worker", "Forms", "Signatures", "Schedules", "CompletionPct"])
    return df.sort_values("Forms", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Form categorization
# --------------------------------------------------------------------------- #

def form_category(form_type_name: str) -> str:
    """Map form type names to high-level categories."""
    name = str(form_type_name).lower()
    if any(k in name for k in ["jsa", "jha", "flra", "hazard assessment", "safe work"]):
        return "JSA / Hazard Assessment"
    if any(k in name for k in ["inspection", "audit", "supervisor audit", "site inspection"]):
        return "Inspection / Audit"
    if any(k in name for k in ["incident", "near miss", "injury", "rir", "bbso"]):
        return "Incident / Near Miss"
    if any(k in name for k in ["training", "orientation", "toolbox", "safety meeting"]):
        return "Training / Orientation"
    return "Other"


def form_categories(forms: pd.DataFrame) -> pd.DataFrame:
    """Group forms into high-level categories."""
    if forms.empty:
        return pd.DataFrame(columns=["Category", "Count"])
    col = "DocumentTemplateName" if "DocumentTemplateName" in forms.columns else None
    if col is None:
        return pd.DataFrame(columns=["Category", "Count"])
    df = forms.copy()
    df["Category"] = df[col].apply(form_category)
    result = df.groupby("Category").size().reset_index(name="Count")
    return result.sort_values("Count", ascending=False)
