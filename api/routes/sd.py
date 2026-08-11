"""SiteDocs API routes — serve KPIs and chart HTML as JSON."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from fastapi import APIRouter, Query

from api.cache import cached
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


def _kpi(label, value, unit="", hint="", rag=None, delta=None, delta_up_good=True, help=""):
    if isinstance(value, (int, float)):
        return {"label": label, "value": value, "unit": unit, "hint": hint or "", "rag": rag,
                "platform": "", "delta": delta, "delta_up_good": delta_up_good, "help": help, "deltaLabel": ""}
    return {"label": label, "value": 0, "unit": unit, "hint": str(value) if value else "", "rag": rag,
            "platform": "", "delta": delta, "delta_up_good": delta_up_good, "help": help, "deltaLabel": ""}


def _rag(v, g, a, gh=True):
    if gh:
        if v >= g: return "green"
        if v >= a: return "amber"
        return "red"
    if v <= g: return "green"
    if v <= a: return "amber"
    return "red"


@router.get("/_api/sd/{section}")
async def sd_section(section: str = "hse",
                     compare: bool = Query(False)):
    ds = cached("sd", _load_sd)
    if not ds:
        return {"kpis": [], "charts": {}, "loaded_at": datetime.now(_HOUSTON).isoformat()}

    now_iso = datetime.now(_HOUSTON).isoformat()
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
        brc = SD.bbso_rir_counts(ds.forms)

        kpis = [
            _kpi("Schedule Compliance", sched_c["completion_pct"], "%",
                 rag=_rag(sched_c["completion_pct"], 80, 60),
                 help="Percentage of scheduled safety activities completed on time"),
            _kpi("Overdue Items", float(sched_c["overdue"]), "",
                 rag=_rag(sched_c["overdue"], 5, 15, False),
                 help="Safety tasks past their due date — items over 30 days hidden"),
            _kpi("BBSO Observations", float(brc["total_bbso"]), "",
                 hint=f"{brc['bbso_this_month']} this month · {brc['bbso_contributors']} observers",
                 help="Behavior-Based Safety Observations — proactive safety engagement by category"),
            _kpi("RIR / Near Miss", float(brc["total_rir"]), "",
                 hint=f"{brc['rir_this_month']} this month · {brc['rir_contributors']} reporters",
                 help="Recordable Incident Reports and near-miss reports — captures events before injuries"),
        ]

        charts = {
            "safety_profile": {"html": SDC.safety_profile_table(ds.workers, ds.forms),
                              "title": "Safety Profile",
                              "help": "Per-worker breakdown of BBSO and RIR submissions"},
            "observer_leaderboard": {"html": SDC.observer_leaderboard_table(ds.workers, ds.forms),
                                    "title": "Top BBSO Observers",
                                    "help": "Workers ranked by behavior-based safety observation count"},
            "reporter_leaderboard": {"html": SDC.reporter_leaderboard_table(ds.workers, ds.forms),
                                    "title": "Top RIR Reporters",
                                    "help": "Workers ranked by incident/near-miss report count"},
            "bbso_trend": {"html": SDC.bbso_trend(ds.forms, compare_forms=compare_forms),
                          "title": "Monthly BBSO Trend",
                          "help": "Behavior-based safety observations per month — leading indicator"},
            "rir_trend": {"html": SDC.rir_trend(ds.forms, compare_forms=compare_forms),
                         "title": "Monthly RIR Trend",
                         "help": "Recordable incident reports per month"},
            "schedule_compliance": {"html": SDC.schedule_compliance(ds.schedules),
                                   "title": "Schedule Compliance",
                                   "help": "Scheduled safety activities — completed, overdue, and cancelled"},
            "form_category": {"html": SDC.form_category_chart(ds.forms),
                             "title": "Forms by Category",
                             "help": "Distribution of safety form types submitted"},
        }
        return {"kpis": kpis, "charts": charts, "loaded_at": now_iso}

    elif section == "forms":
        f_count = SD.form_counts(ds.forms)
        w_count = SD.worker_counts(ds.workers)
        brc = SD.bbso_rir_counts(ds.forms)
        kpis = [
            _kpi("Total Forms", float(f_count["total"]), "",
                 help="All safety forms submitted across the platform"),
            _kpi("This Month", float(f_count["month"]), "",
                 help="Forms submitted in the current calendar month"),
            _kpi("BBSO", float(brc["total_bbso"]), "",
                 hint=f"{brc['bbso_this_month']} this month"),
            _kpi("RIR / Near Miss", float(brc["total_rir"]), "",
                 hint=f"{brc['rir_this_month']} this month"),
            _kpi("Active Workers", float(w_count["active"]), ""),
        ]
        charts = {
            "form_category": {"html": SDC.form_category_chart(ds.forms),
                             "title": "Forms by Category",
                             "help": "Distribution of safety form types submitted"},
            "forms_trend": {"html": SDC.forms_trend(ds.forms, compare_forms=compare_forms),
                           "title": "Monthly Trend",
                           "help": "Total forms submitted per month"},
            "bbso_trend": {"html": SDC.bbso_trend(ds.forms, compare_forms=compare_forms),
                          "title": "Monthly BBSO Trend",
                          "help": "Behavior-based safety observations per month"},
            "rir_trend": {"html": SDC.rir_trend(ds.forms, compare_forms=compare_forms),
                         "title": "Monthly RIR Trend",
                         "help": "Recordable incident reports per month"},
        }
        return {"kpis": kpis, "charts": charts, "loaded_at": now_iso}

    elif section == "compliance":
        sched_c = SD.schedule_counts(ds.schedules)
        brc = SD.bbso_rir_counts(ds.forms)
        kpis = [
            _kpi("Completion Rate", sched_c["completion_pct"], "%",
                 rag=_rag(sched_c["completion_pct"], 80, 60)),
            _kpi("Overdue", float(sched_c["overdue"]), "",
                 rag=_rag(sched_c["overdue"], 5, 15, False)),
            _kpi("Late", float(sched_c["late"]), ""),
            _kpi("Cancelled", float(sched_c["cancelled"]), ""),
            _kpi("BBSO This Month", float(brc["bbso_this_month"]), "",
                 hint=f"{brc['total_bbso']} total"),
            _kpi("RIR This Month", float(brc["rir_this_month"]), "",
                 hint=f"{brc['total_rir']} total"),
        ]
        charts = {
            "schedule_compliance": {"html": SDC.schedule_compliance(ds.schedules),
                                   "title": "Schedule Compliance",
                                   "help": "Scheduled safety activities — completed, overdue, and cancelled"},
            "bbso_trend": {"html": SDC.bbso_trend(ds.forms, compare_forms=compare_forms),
                          "title": "Monthly BBSO Trend"},
            "rir_trend": {"html": SDC.rir_trend(ds.forms, compare_forms=compare_forms),
                         "title": "Monthly RIR Trend"},
            "overdue": {"html": SDC.overdue_items_list(ds.schedules),
                       "title": "Overdue & Late Items",
                       "help": "Items past due (over 30 days hidden as resolved)"},
        }
        return {"kpis": kpis, "charts": charts, "loaded_at": now_iso}

    elif section == "workers":
        w_count = SD.worker_counts(ds.workers)
        brc = SD.bbso_rir_counts(ds.forms)
        kpis = [
            _kpi("Active Workers", float(w_count["active"]), "",
                 hint=f"of {w_count['total']} total"),
            _kpi("Contractors", float(w_count["contractors"]), "",
                 hint=f"{w_count['employees']} employees"),
            _kpi("BBSO Contributors", float(brc["bbso_contributors"]), "",
                 hint=f"{brc['total_bbso']} total BBSOs"),
            _kpi("RIR Contributors", float(brc["rir_contributors"]), "",
                 hint=f"{brc['total_rir']} total RIRs"),
        ]
        charts = {
            "status": {"html": SDC.worker_status(ds.workers),
                      "title": "Active vs Inactive",
                      "help": "Workers currently active in the SiteDocs platform"},
            "type_split": {"html": SDC.worker_type_split(ds.workers),
                          "title": "Employee vs Contractor",
                          "help": "Workforce composition — employee vs contractor ratio"},
            "leaderboard": {"html": SDC.bbso_rir_leaderboard_table(ds.workers, ds.forms),
                           "title": "BBSO & RIR by Worker",
                           "help": "Per-worker safety observation and incident report counts"},
        }
        return {"kpis": kpis, "charts": charts, "loaded_at": now_iso}

    return {"kpis": [], "charts": {}, "loaded_at": now_iso}
