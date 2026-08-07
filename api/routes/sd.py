"""SiteDocs API routes — serve KPIs, chart HTML, and CSV exports as JSON."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from fastapi import APIRouter, Query

from api.cache import cached
from api.csv_export import to_csv_response
from data import sd_data as SD
from charts import sd_charts as SDC

try:
    from zoneinfo import ZoneInfo
    _HOUSTON = ZoneInfo("America/Chicago")
except Exception:
    _HOUSTON = timezone.utc

router = APIRouter()


def _load_sd():
    ds = SD.sd_load_dataset()
    if ds and ds.has_data:
        return ds
    return None


def _kpi(label, value, unit="", hint="", rag=None, platform="SD", delta=None, delta_up_good=True, help="", delta_label=""):
    if isinstance(value, (int, float)):
        return {"label": label, "value": value, "unit": unit, "hint": hint or "", "rag": rag, "platform": platform,
                "delta": delta, "delta_up_good": delta_up_good, "help": help, "deltaLabel": delta_label}
    return {"label": label, "value": 0, "unit": unit, "hint": str(value) if value else "", "rag": rag, "platform": platform,
            "delta": delta, "delta_up_good": delta_up_good, "help": help, "deltaLabel": delta_label}


def _rag(v, g, a, gh=True):
    if gh:
        if v >= g: return "green"
        if v >= a: return "amber"
        return "red"
    else:
        if v <= g: return "green"
        if v <= a: return "amber"
        return "red"


def _export_csv(section, ds):
    if section in ("hse", "forms"):
        return to_csv_response(ds.forms, filename=f"sd_{section}.csv")
    elif section == "compliance":
        return to_csv_response(ds.schedules, filename=f"sd_compliance.csv")
    elif section == "workers":
        return to_csv_response(ds.workers, filename=f"sd_workers.csv")
    return to_csv_response(ds.forms, filename="sd.csv")


@router.get("/_api/sd/{section}")
async def sd_section(section: str = "hse",
                     compare: bool = Query(False),
                     format: str | None = Query(None)):
    ds = cached("sd", _load_sd)
    if not ds:
        return {"kpis": [], "charts": {}, "loaded_at": datetime.now(_HOUSTON).isoformat()}

    now_iso = datetime.now(_HOUSTON).isoformat()

    # CSV export — raw data, no KPIs/charts
    if format == "csv":
        return _export_csv(section, ds)

    # Compute compare_forms if requested
    compare_forms = None
    if compare and not ds.forms.empty:
        try:
            from datetime import timedelta
            date_col = "CreatedOn" if "CreatedOn" in ds.forms.columns else "createdOn"
            if date_col in ds.forms.columns:
                forms_dates = pd.to_datetime(ds.forms[date_col], errors="coerce")
                latest = forms_dates.max()
                if pd.notna(latest):
                    prev_start = latest - timedelta(days=365)
                    prev_end = latest - timedelta(days=1)
                    mask = (forms_dates >= prev_start) & (forms_dates <= prev_end)
                    compare_forms = ds.forms[mask].copy()
        except Exception:
            pass

    if section == "hse":
        sched_c = SD.schedule_counts(ds.schedules)
        f_count = SD.form_counts(ds.forms)
        part = SD.worker_participation(ds.workers, ds.forms)
        brc = SD.bbso_rir_counts(ds.forms)
        bir = SD.bbso_incident_ratio(ds.forms, ds.incidents)
        rir_ratio = SD.rir_incident_ratio(ds.forms, ds.incidents)
        close_time = SD.incident_close_time(ds.incidents)

        kpis = [
            _kpi("Schedule Compliance", sched_c["completion_pct"], "%", rag=_rag(sched_c["completion_pct"], 80, 60)),
            _kpi("Overdue Items", float(sched_c["overdue"]), "", rag=_rag(sched_c["overdue"], 5, 15, False)),
            _kpi("BBSO Observations", float(brc["total_bbso"]), "",
                 hint=f"{brc['bbso_this_month']} this month · {brc['bbso_contributors']} observers",
                 help="Behavior-based safety observations — proactive safety engagement"),
            _kpi("RIR / Near Miss Reports", float(brc["total_rir"]), "",
                 hint=f"{brc['rir_this_month']} this month · {brc['rir_contributors']} reporters",
                 help="Recordable incident reports and near-miss reports"),
            _kpi("Worker Participation", part["pct"], "%", rag=_rag(part["pct"], 80, 60),
                 help="Active workers who submitted at least one safety form this month"),
            _kpi("BBSO:Incident Ratio", float(bir["ratio"]), ":1",
                 hint=f"{bir['total_bbso']} BBSO · {bir['total_incidents']} incidents", rag=_rag(bir["ratio"], 5, 2),
                 help="Leading indicator — proactive observations per actual incident"),
            _kpi("RIR:Incident Ratio", float(rir_ratio["ratio"]), ":1",
                 hint=f"{rir_ratio['total_rir']} RIRs · {rir_ratio['total_incidents']} incidents", rag=_rag(rir_ratio["ratio"], 5, 2),
                 help="Near-miss reporting rate — high values = strong safety culture"),
            _kpi("Avg Incident Close Time", float(close_time["mean_days"]), "days",
                 hint=f"median {close_time['median_days']}d · {close_time['closed_count']} closed",
                 rag=_rag(close_time["mean_days"], 14, 30, False)),
        ]
        charts = {
            "safety_profile": {"html": SDC.safety_profile_table(ds.workers, ds.forms), "title": "Safety Profile"},
            "observer_leaderboard": {"html": SDC.observer_leaderboard_table(ds.workers, ds.forms), "title": "Top BBSO Observers"},
            "reporter_leaderboard": {"html": SDC.reporter_leaderboard_table(ds.workers, ds.forms), "title": "Top RIR Reporters"},
            "bbso_trend": {"html": SDC.bbso_trend(ds.forms, compare_forms=compare_forms), "title": "Monthly BBSO Trend"},
            "rir_trend": {"html": SDC.rir_trend(ds.forms, compare_forms=compare_forms), "title": "Monthly RIR Trend"},
            "bbso_risk_heatmap": {"html": SDC.bbso_risk_heatmap(ds.forms, ds.form_responses), "title": "BBSO Risk by Category"},
            "schedule_compliance": {"html": SDC.schedule_compliance(ds.schedules), "title": "Schedule Compliance"},
            "form_category": {"html": SDC.form_category_chart(ds.forms), "title": "Forms by Category"},
        }
        if hasattr(ds, 'form_responses') and not ds.form_responses.empty:
            charts["rir_events"] = {"html": SDC.rir_events_from_forms(ds.forms, ds.workers, ds.incidents, ds.locations), "title": "Recent RIR Events"}
        return {"kpis": kpis, "charts": charts, "loaded_at": now_iso}

    elif section == "forms":
        f_count = SD.form_counts(ds.forms)
        w_count = SD.worker_counts(ds.workers)
        brc = SD.bbso_rir_counts(ds.forms)
        kpis = [
            _kpi("Total Forms", float(f_count["total"])),
            _kpi("This Month", float(f_count["month"])),
            _kpi("BBSO", float(brc["total_bbso"]), hint=f"{brc['bbso_this_month']} this month"),
            _kpi("RIR / Near Miss", float(brc["total_rir"]), hint=f"{brc['rir_this_month']} this month"),
            _kpi("Active Workers", float(w_count["active"])),
        ]
        charts = {
            "form_category": {"html": SDC.form_category_chart(ds.forms), "title": "Forms by Category"},
            "forms_trend": {"html": SDC.forms_trend(ds.forms, compare_forms=compare_forms), "title": "Monthly Trend"},
            "bbso_trend": {"html": SDC.bbso_trend(ds.forms, compare_forms=compare_forms), "title": "Monthly BBSO Trend"},
            "rir_trend": {"html": SDC.rir_trend(ds.forms, compare_forms=compare_forms), "title": "Monthly RIR Trend"},
            "form_types": {"html": SDC.form_types_chart(ds.formtypes, ds.forms), "title": "Forms by Type"},
        }
        return {"kpis": kpis, "charts": charts, "loaded_at": now_iso}

    elif section == "compliance":
        sched_c = SD.schedule_counts(ds.schedules)
        brc = SD.bbso_rir_counts(ds.forms)
        kpis = [
            _kpi("Completion Rate", sched_c["completion_pct"], "%", rag=_rag(sched_c["completion_pct"], 80, 60)),
            _kpi("Overdue", float(sched_c["overdue"]), "", rag=_rag(sched_c["overdue"], 5, 15, False)),
            _kpi("Late", float(sched_c["late"])),
            _kpi("Cancelled", float(sched_c["cancelled"])),
            _kpi("BBSO This Month", float(brc["bbso_this_month"]), "", hint=f"{brc['total_bbso']} total"),
            _kpi("RIR This Month", float(brc["rir_this_month"]), "", hint=f"{brc['total_rir']} total"),
        ]
        charts = {
            "schedule_compliance": {"html": SDC.schedule_compliance(ds.schedules), "title": "Schedule Compliance"},
            "bbso_trend": {"html": SDC.bbso_trend(ds.forms, compare_forms=compare_forms), "title": "Monthly BBSO Trend"},
            "rir_trend": {"html": SDC.rir_trend(ds.forms, compare_forms=compare_forms), "title": "Monthly RIR Trend"},
            "forms_trend": {"html": SDC.forms_trend(ds.forms, compare_forms=compare_forms), "title": "Forms Trend"},
            "leaderboard": {"html": SDC.bbso_rir_leaderboard_table(ds.workers, ds.forms), "title": "BBSO & RIR by Worker"},
            "overdue": {"html": SDC.overdue_items_list(ds.schedules), "title": "Overdue & Late Items"},
        }
        return {"kpis": kpis, "charts": charts, "loaded_at": now_iso}

    elif section == "workers":
        w_count = SD.worker_counts(ds.workers)
        part = SD.worker_participation(ds.workers, ds.forms)
        brc = SD.bbso_rir_counts(ds.forms)
        kpis = [
            _kpi("Active Workers", float(w_count["active"]), "", hint=f"of {w_count['total']} total"),
            _kpi("Contractors", float(w_count["contractors"]), "", hint=f"{w_count['employees']} employees"),
            _kpi("Participation", part["pct"], "%", rag=_rag(part["pct"], 80, 60)),
            _kpi("BBSO Contributors", float(brc["bbso_contributors"]), "", hint=f"{brc['total_bbso']} total BBSOs"),
            _kpi("RIR Contributors", float(brc["rir_contributors"]), "", hint=f"{brc['total_rir']} total RIRs"),
        ]
        charts = {
            "status": {"html": SDC.worker_status(ds.workers), "title": "Active vs Inactive"},
            "type_split": {"html": SDC.worker_type_split(ds.workers), "title": "Employee vs Contractor"},
            "leaderboard": {"html": SDC.bbso_rir_leaderboard_table(ds.workers, ds.forms), "title": "BBSO & RIR by Worker"},
            "activity": {"html": SDC.worker_leaderboard_table(ds.workers, ds.forms, ds.signatures, ds.schedules), "title": "Worker Activity"},
        }
        return {"kpis": kpis, "charts": charts, "loaded_at": now_iso}

    return {"kpis": [], "charts": {}, "loaded_at": now_iso}
