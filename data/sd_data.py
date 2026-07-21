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

_CACHE_TTL = 600
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
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
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
    form_responses: pd.DataFrame = field(default_factory=pd.DataFrame)

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
    form_responses = safe_read("sitedocs_form_responses")

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
        form_responses=form_responses,
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


# --------------------------------------------------------------------------- #
# BBSO & RIR (Safety Engagement KPIs)
# --------------------------------------------------------------------------- #

# UUIDs for BBSO / RIR form types in the SiteDocs warehouse.
# Check these against your actual data — they vary per SiteDocs account.
BBSO_FORM_TYPE_ID = "5add4d1b-82c6-4067-a300-6f005612f3a7"
RIR_FORM_TYPE_ID = "f5bdff50-1e1f-4a78-bc52-8a46ec78f0ed"

# Name-based keywords (used as fallback when UUID column is missing or unmatched)
BBSO_KEYWORDS = ["BBSO", "Behavioral Based Safety", "Behavior Based Safety",
                 "Safety Observation", "Safe Behavior"]
RIR_KEYWORDS = ["RIR", "Near Miss", "Recordable Incident", "Recordable Injury",
                "First Aid", "Medical Treatment"]


def _matches_name(name: str, keywords: list[str]) -> bool:
    """Check if a form type name matches any of the given keywords (case-insensitive)."""
    n = str(name).lower()
    return any(k.lower() in n for k in keywords)


def _filter_bbso(forms: pd.DataFrame) -> pd.DataFrame:
    if forms.empty:
        return pd.DataFrame()

    # Strategy 1: DocumentTemplateVersionId (UUID)
    if "DocumentTemplateVersionId" in forms.columns:
        matched = forms[forms["DocumentTemplateVersionId"] == BBSO_FORM_TYPE_ID]
        if not matched.empty:
            return matched

    # Strategy 2: FormTypeName / FormType
    for col in ("FormTypeName", "FormType", "TypeName"):
        if col in forms.columns:
            matched = forms[forms[col].apply(lambda x: _matches_name(x, BBSO_KEYWORDS))]
            if not matched.empty:
                return matched

    # Strategy 3: DocumentTemplateName (name-based)
    if "DocumentTemplateName" in forms.columns:
        matched = forms[forms["DocumentTemplateName"].apply(lambda x: _matches_name(x, BBSO_KEYWORDS))]
        if not matched.empty:
            return matched

    return pd.DataFrame()


def _filter_rir(forms: pd.DataFrame) -> pd.DataFrame:
    if forms.empty:
        return pd.DataFrame()

    # Strategy 1: DocumentTemplateVersionId (UUID)
    if "DocumentTemplateVersionId" in forms.columns:
        matched = forms[forms["DocumentTemplateVersionId"] == RIR_FORM_TYPE_ID]
        if not matched.empty:
            return matched

    # Strategy 2: FormTypeName / FormType
    for col in ("FormTypeName", "FormType", "TypeName"):
        if col in forms.columns:
            matched = forms[forms[col].apply(lambda x: _matches_name(x, RIR_KEYWORDS))]
            if not matched.empty:
                return matched

    # Strategy 3: DocumentTemplateName (name-based)
    if "DocumentTemplateName" in forms.columns:
        matched = forms[forms["DocumentTemplateName"].apply(lambda x: _matches_name(x, RIR_KEYWORDS))]
        if not matched.empty:
            return matched

    return pd.DataFrame()


def bbso_rir_counts(forms: pd.DataFrame) -> dict[str, Any]:
    bbso = _filter_bbso(forms)
    rir = _filter_rir(forms)
    total_bbso = len(bbso)
    total_rir = len(rir)

    def _monthly(df, date_col="CreatedOn"):
        if df.empty or date_col not in df.columns:
            return {}
        df = df.copy()
        df["_m"] = pd.to_datetime(df[date_col]).dt.to_period("M")
        return df.groupby("_m").size().to_dict()

    bbso_by_month = _monthly(bbso)
    rir_by_month = _monthly(rir)
    this_month = pd.Timestamp.now().to_period("M")
    bbso_this_month = bbso_by_month.get(this_month, 0)
    rir_this_month = rir_by_month.get(this_month, 0)

    def _by_worker(df):
        if df.empty:
            return {}
        col = "CreatedBy" if "CreatedBy" in df.columns else "createdBy"
        if col not in df.columns:
            return {}
        return df[col].value_counts().to_dict()

    bbso_by_worker = _by_worker(bbso)
    rir_by_worker = _by_worker(rir)

    return {
        "total_bbso": total_bbso, "total_rir": total_rir,
        "bbso_this_month": bbso_this_month, "rir_this_month": rir_this_month,
        "bbso_by_month": bbso_by_month, "rir_by_month": rir_by_month,
        "bbso_by_worker": bbso_by_worker, "rir_by_worker": rir_by_worker,
        "bbso_contributors": len(bbso_by_worker),
        "rir_contributors": len(rir_by_worker),
    }


def bbso_monthly_trend(forms: pd.DataFrame) -> pd.DataFrame:
    bbso = _filter_bbso(forms)
    if bbso.empty:
        return pd.DataFrame(columns=["Month", "Count"])
    col = "CreatedOn" if "CreatedOn" in bbso.columns else "createdOn"
    if col not in bbso.columns:
        return pd.DataFrame(columns=["Month", "Count"])
    df = bbso.dropna(subset=[col]).copy()
    if df.empty:
        return pd.DataFrame(columns=["Month", "Count"])
    df["Month"] = pd.to_datetime(df[col]).dt.to_period("M").dt.to_timestamp()
    result = df.groupby("Month").size().reset_index(name="Count")
    return result.sort_values("Month").reset_index(drop=True)


def rir_monthly_trend(forms: pd.DataFrame) -> pd.DataFrame:
    rir = _filter_rir(forms)
    if rir.empty:
        return pd.DataFrame(columns=["Month", "Count"])
    col = "CreatedOn" if "CreatedOn" in rir.columns else "createdOn"
    if col not in rir.columns:
        return pd.DataFrame(columns=["Month", "Count"])
    df = rir.dropna(subset=[col]).copy()
    if df.empty:
        return pd.DataFrame(columns=["Month", "Count"])
    df["Month"] = pd.to_datetime(df[col]).dt.to_period("M").dt.to_timestamp()
    result = df.groupby("Month").size().reset_index(name="Count")
    return result.sort_values("Month").reset_index(drop=True)


def bbso_rir_leaderboard(workers: pd.DataFrame, forms: pd.DataFrame) -> pd.DataFrame:
    if workers.empty:
        return pd.DataFrame(columns=["Worker", "WorkerId", "BBSO", "RIR", "HSE_Engagement"])
    bbso = _filter_bbso(forms)
    rir = _filter_rir(forms)
    col = "CreatedBy" if "CreatedBy" in forms.columns else "createdBy"
    active = workers[workers["Active"].astype(bool)] if "Active" in workers.columns else workers
    rows = []
    for _, w in active.iterrows():
        wid = w["Id"]
        name = f"{w.get('FirstName','')} {w.get('LastName','')}".strip()
        b = int((bbso[col] == wid).sum()) if col in bbso.columns else 0
        r = int((rir[col] == wid).sum()) if col in rir.columns else 0
        engagement = (b + r) / 3.0
        if b > 0 or r > 0:
            rows.append({"Worker": name, "WorkerId": wid, "BBSO": b, "RIR": r, "HSE_Engagement": round(engagement, 1)})
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["Worker", "WorkerId", "BBSO", "RIR", "HSE_Engagement"])
    return df.sort_values("HSE_Engagement", ascending=False).reset_index(drop=True)




# --------------------------------------------------------------------------- #
# Per-person safety profiles: who observes, who reports, who's at risk
# --------------------------------------------------------------------------- #

def _worker_name(w_row) -> str:
    """Extract a human name from a worker DataFrame row."""
    return f"{w_row.get('FirstName','')} {w_row.get('LastName','')}".strip() or f"Worker {w_row.get('Id','')[:8]}"


def _created_by_col(forms: pd.DataFrame) -> str | None:
    """Return the name of the CreatedBy column (case-insensitive), or None."""
    for col in ("CreatedBy", "createdBy"):
        if col in forms.columns:
            return col
    return None


def bbso_observer_leaderboard(workers: pd.DataFrame, forms: pd.DataFrame) -> pd.DataFrame:
    """Per-person BBSO submission counts — who is actively doing observations.

    ``CreatedBy`` on BBSO forms = the observer/supervisor who performed the
    observation. High counts = strong observation culture.
    Returns columns [Worker, BBSOs, LastObservation, Role].
    """
    if workers.empty:
        return pd.DataFrame(columns=["Worker", "BBSOs", "LastObservation", "Role"])
    bbso = _filter_bbso(forms)
    col = _created_by_col(bbso)
    if col is None:
        return pd.DataFrame(columns=["Worker", "BBSOs", "LastObservation", "Role"])
    if bbso.empty:
        return pd.DataFrame(columns=["Worker", "BBSOs", "LastObservation", "Role"])

    active = workers[workers["Active"].astype(bool)] if "Active" in workers.columns else workers
    now_ts = pd.Timestamp.now()
    rows = []
    for _, w in active.iterrows():
        wid = w["Id"]
        mask = bbso[col] == wid
        count = int(mask.sum())
        if count == 0:
            continue
        # Last observation date if available
        date_col = "CreatedOn" if "CreatedOn" in bbso.columns else "createdOn"
        if date_col in bbso.columns and mask.any():
            last = pd.to_datetime(bbso.loc[mask, date_col]).max()
            last_str = last.strftime("%b %d") if pd.notna(last) else "—"
        else:
            last_str = "—"
        # Employee/contractor label
        is_ext = bool(w.get("IsExternal", False)) if "IsExternal" in workers.columns else False
        role = "Contractor" if is_ext else "Employee"
        rows.append({"Worker": _worker_name(w), "BBSOs": count,
                      "LastObservation": last_str, "Role": role})
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["Worker", "BBSOs", "LastObservation", "Role"])
    return df.sort_values("BBSOs", ascending=False).reset_index(drop=True)


def rir_reporter_leaderboard(workers: pd.DataFrame, forms: pd.DataFrame) -> pd.DataFrame:
    """Per-person RIR / Near Miss reporting counts — who reports incidents.

    ``CreatedBy`` on RIR forms = the person who reported the near miss/incident.
    High counts = good reporting culture, but may indicate the person works in
    higher-risk areas.
    Returns columns [Worker, RIRs, LastReport, Role].
    """
    if workers.empty:
        return pd.DataFrame(columns=["Worker", "RIRs", "LastReport", "Role"])
    rir = _filter_rir(forms)
    col = _created_by_col(rir)
    if col is None or rir.empty:
        return pd.DataFrame(columns=["Worker", "RIRs", "LastReport", "Role"])

    active = workers[workers["Active"].astype(bool)] if "Active" in workers.columns else workers
    rows = []
    for _, w in active.iterrows():
        wid = w["Id"]
        mask = rir[col] == wid
        count = int(mask.sum())
        if count == 0:
            continue
        date_col = "CreatedOn" if "CreatedOn" in rir.columns else "createdOn"
        if date_col in rir.columns and mask.any():
            last = pd.to_datetime(rir.loc[mask, date_col]).max()
            last_str = last.strftime("%b %d") if pd.notna(last) else "—"
        else:
            last_str = "—"
        is_ext = bool(w.get("IsExternal", False)) if "IsExternal" in workers.columns else False
        role = "Contractor" if is_ext else "Employee"
        rows.append({"Worker": _worker_name(w), "RIRs": count,
                      "LastReport": last_str, "Role": role})
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["Worker", "RIRs", "LastReport", "Role"])
    return df.sort_values("RIRs", ascending=False).reset_index(drop=True)


def bbso_rir_safety_profile(workers: pd.DataFrame, forms: pd.DataFrame) -> pd.DataFrame:
    """Combined safety profile per person: BBSOs submitted vs RIRs reported.

    Returns columns [Worker, WorkerId, BBSOs, RIRs, Role].
    No classifications or engagement scores — just raw numbers.
    """
    if workers.empty:
        return pd.DataFrame(columns=["Worker", "WorkerId", "BBSOs", "RIRs", "Role"])
    bbso = _filter_bbso(forms)
    rir = _filter_rir(forms)
    col = _created_by_col(forms)
    if col is None:
        return pd.DataFrame(columns=["Worker", "WorkerId", "BBSOs", "RIRs", "Role"])

    active = workers[workers["Active"].astype(bool)] if "Active" in workers.columns else workers
    rows = []
    for _, w in active.iterrows():
        wid = w["Id"]
        b = int((bbso[col] == wid).sum()) if col in bbso.columns else 0
        r = int((rir[col] == wid).sum()) if col in rir.columns else 0
        if b == 0 and r == 0:
            continue
        is_ext = bool(w.get("IsExternal", False)) if "IsExternal" in workers.columns else False
        role = "Contractor" if is_ext else "Employee"
        rows.append({"Worker": _worker_name(w), "WorkerId": wid,
                      "BBSOs": b, "RIRs": r, "Role": role})
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["Worker", "WorkerId", "BBSOs", "RIRs", "Role"])
    return df.sort_values("BBSOs", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Form response analysis (from sitedocs_form_responses table)
# --------------------------------------------------------------------------- #

def bbso_responses(responses: pd.DataFrame) -> pd.DataFrame:
    """Filter to BBSO form responses only."""
    if responses.empty:
        return pd.DataFrame()
    return responses[responses["FormType"].str.upper().str.strip() == "BBSO"].copy()


def rir_responses(responses: pd.DataFrame) -> pd.DataFrame:
    """Filter to RIR/Near Miss form responses only."""
    if responses.empty:
        return pd.DataFrame()
    return responses[
        responses["FormType"].str.contains("RIR|Near Miss", na=False)
    ].copy()


def bbso_at_risk_by_category(responses: pd.DataFrame) -> pd.DataFrame:
    """Per-category (GroupTitle) count of safe vs at-risk observations from BBSO forms.

    Returns columns: [Category, Safe, AtRisk, Total, SafePct]
    Categories are the form groups (PPE, Line of Fire, Housekeeping, etc.)
    """
    bbso = bbso_responses(responses)
    if bbso.empty:
        return pd.DataFrame(columns=["Category", "Safe", "AtRisk", "Total", "SafePct"])

    # Filter to items that are YesNo type (safe/at-risk indicators)
    # Also include PassFailCounter and Inspection types
    qa = bbso[bbso["ItemType"].isin(["YesNo", "PassFailCounter", "Inspection"])].copy()
    if qa.empty:
        return pd.DataFrame(columns=["Category", "Safe", "AtRisk", "Total", "SafePct"])

    # Skip the "Task Information" group — it's metadata, not a safety category
    qa = qa[qa["GroupTitle"] != "Task Information"]

    def classify(val: str) -> str:
        v = str(val).strip().lower()
        if v in ("yes", "pass", "true", "safe", "1"):
            return "Safe"
        return "AtRisk"

    qa["_verdict"] = qa["ItemValue"].apply(classify)
    groups = qa.groupby(["GroupTitle", "_verdict"]).size().unstack(fill_value=0)
    for col in ("Safe", "AtRisk"):
        if col not in groups.columns:
            groups[col] = 0
    groups = groups.rename(columns={"Safe": "Safe", "AtRisk": "AtRisk"})
    groups = groups.reset_index()
    groups["Total"] = groups["Safe"] + groups["AtRisk"]
    groups["SafePct"] = (groups["Safe"] / groups["Total"] * 100).round(1)
    return groups.rename(columns={"GroupTitle": "Category"})\
        .sort_values("Total", ascending=False).reset_index(drop=True)


def bbso_tasks_observed(responses: pd.DataFrame) -> pd.DataFrame:
    """Extract unique task descriptions from BBSO forms.

    Returns columns: [FormId, ObserverId, Task, CreatedOn]
    Task descriptions come from the "Task Information" group (What task? question).
    """
    bbso = bbso_responses(responses)
    if bbso.empty:
        return pd.DataFrame(columns=["FormId", "ObserverId", "Task", "CreatedOn"])

    task_rows = bbso[
        (bbso["GroupTitle"] == "Task Information")
        & (bbso["ItemContent"].str.contains("task", case=False, na=False))
    ].copy()
    if task_rows.empty:
        return pd.DataFrame(columns=["FormId", "ObserverId", "Task", "CreatedOn"])

    result = task_rows[["FormId", "CreatedBy", "ItemValue", "CreatedOn"]]\
        .rename(columns={"CreatedBy": "ObserverId", "ItemValue": "Task"})
    return result.drop_duplicates(subset=["FormId"]).reset_index(drop=True)


def bbso_recent_at_risk(responses: pd.DataFrame, workers: pd.DataFrame,
                         limit: int = 15) -> pd.DataFrame:
    """Most recent BBSO at-risk observations with worker names and comments.

    Returns columns: [Worker, Date, Task, Category, Observation, Comments]
    """
    bbso = bbso_responses(responses)
    if bbso.empty or workers.empty:
        return pd.DataFrame(columns=["Worker", "Date", "Task", "Category", "Observation", "Comments"])

    # Filter to at-risk items
    qa = bbso[bbso["ItemType"].isin(["YesNo", "PassFailCounter", "Inspection"])].copy()
    if qa.empty:
        return pd.DataFrame(columns=["Worker", "Date", "Task", "Category", "Observation", "Comments"])

    at_risk = qa[qa["ItemValue"].str.lower().isin(["no", "fail", "false", "0"])].copy()
    if at_risk.empty:
        return pd.DataFrame(columns=["Worker", "Date", "Task", "Category", "Observation", "Comments"])

    # Parse dates
    at_risk["_date"] = pd.to_datetime(at_risk["CreatedOn"], errors="coerce")
    at_risk = at_risk.dropna(subset=["_date"])

    # Get task descriptions per form
    tasks = bbso_tasks_observed(responses)
    task_map = dict(zip(tasks["FormId"], tasks["Task"]))

    # Resolve worker names
    workers_map = {str(w["Id"]): f"{w.get('FirstName','')} {w.get('LastName','')}".strip()
                   for _, w in workers.iterrows()}

    result = at_risk.sort_values("_date", ascending=False).head(limit).copy()
    result["Task"] = result["FormId"].map(task_map).fillna("—")
    result["Worker"] = result["CreatedBy"].map(workers_map).fillna(result["CreatedBy"].str[:8])
    result["Date"] = result["_date"].dt.strftime("%b %d")

    return result[["Worker", "Date", "Task", "GroupTitle", "ItemContent", "Comments"]]\
        .rename(columns={"GroupTitle": "Category", "ItemContent": "Observation"})\
        .reset_index(drop=True)


def rir_recent_events(responses: pd.DataFrame, workers: pd.DataFrame,
                       locations: pd.DataFrame | None = None,
                       limit: int = 10) -> pd.DataFrame:
    """Most recent RIR/Near Miss events with details.

    Resolves UUIDs in ItemValues against workers and locations tables.
    Returns columns: [Worker, Date, WhatHappened, Severity, RootCause, Action]
    """
    rir = rir_responses(responses)
    if rir.empty or workers.empty:
        return pd.DataFrame(columns=["Worker", "Date", "WhatHappened", "Severity", "RootCause", "Action"])

    # Build lookup maps for UUID resolution
    workers_map = {str(w["Id"]): f"{w.get('FirstName','')} {w.get('LastName','')}".strip()
                   for _, w in workers.iterrows()}
    locations_map = {}
    if locations is not None and not locations.empty:
        for _, loc in locations.iterrows():
            locations_map[str(loc.get("Id", ""))] = str(loc.get("Name", ""))

    def resolve(val: str) -> str:
        """If val is a known UUID, return human-readable name. Otherwise val as-is."""
        v = str(val).strip()
        if v in workers_map:
            return workers_map[v]
        if v in locations_map:
            return locations_map[v]
        return v

    rows = []
    for form_id, group in rir.groupby("FormId"):
        what = ""
        severity = ""
        root_cause = ""
        action = ""
        created_by = group["CreatedBy"].iloc[0] if "CreatedBy" in group.columns else ""
        created_on = group["CreatedOn"].iloc[0] if "CreatedOn" in group.columns else ""

        for _, r in group.iterrows():
            item = str(r.get("ItemContent", "")).lower()
            val = resolve(r.get("ItemValue", ""))
            if "happened" in item or "describe" in item:
                what = val
            elif "severity" in item or "potential" in item:
                severity = val
            elif "root cause" in item:
                root_cause = val
            elif "action" in item or "corrective" in item:
                action = val

        rows.append({
            "FormId": form_id,
            "Worker": workers_map.get(created_by, created_by[:8]),
            "Date": str(created_on)[:10],
            "WhatHappened": what,
            "Severity": severity,
            "RootCause": root_cause,
            "Action": action,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["Worker", "Date", "WhatHappened", "Severity", "RootCause", "Action"])
    df["_dt"] = pd.to_datetime(df["Date"], errors="coerce")
    return df.sort_values("_dt", ascending=False).head(limit)\
        .drop(columns=["_dt", "FormId"]).reset_index(drop=True)


def worker_bbso_forms(workers: pd.DataFrame, forms: pd.DataFrame, worker_id: str) -> pd.DataFrame:
    """Return all BBSO forms for a given worker, with resolved location names."""
    bbso = _filter_bbso(forms)
    if bbso.empty:
        return pd.DataFrame(columns=["CreatedOn", "Label", "LocationName"])
    df = bbso[bbso.get("CreatedBy", bbso.get("createdBy")) == worker_id].copy()
    if df.empty:
        return pd.DataFrame(columns=["CreatedOn", "Label", "LocationName"])
    # Resolve location ID to name (all columns are text, LocationId is the raw UUID)
    loc_col = "LocationId"
    if loc_col in df.columns:
        # Location names from the locations table aren't loaded here,
        # so we return LocationId raw and let the caller resolve.
        pass
    col = "CreatedOn" if "CreatedOn" in df.columns else "createdOn"
    df = df.sort_values(col, ascending=False)
    df["_date"] = pd.to_datetime(df[col]).dt.strftime("%Y-%m-%d %H:%M") if col in df.columns else ""
    return df[[c for c in ["_date", "Label", "LocationId"] if c in df.columns]].rename(
        columns={"_date": "CreatedOn"}
    )

