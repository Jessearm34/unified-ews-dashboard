"""SiteDocs API routes — serve KPIs and chart HTML as JSON."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from fastapi import APIRouter, Query

from api.cache import cached
from data import sd_data as SD
from charts import sd_charts as SDC

router = APIRouter()

def _load_sd():
    ds = SD.sd_load_dataset()
    if ds and ds.has_data:
        return ds
    return None

def _kpi_dict(label, value, unit="", hint="", rag=None, platform="SD", delta=None, delta_up_good=True):
    if isinstance(value, (int, float)):
        return {"label": label, "value": value, "unit": unit, "hint": hint or "", "rag": rag, "platform": platform, "delta": delta, "delta_up_good": delta_up_good}
    return {"label": label, "value": 0, "unit": unit, "hint": str(value) if value else "", "rag": rag, "platform": platform, "delta": delta, "delta_up_good": delta_up_good}


@router.get("/_api/sd/{section}")
async def sd_section(section: str = "hse",
                     compare: bool = Query(False, description="Show year-over-year overlay on trend charts")):
    ds = cached("sd", _load_sd)
    if not ds:
        return {"kpis": [], "charts": {}, "loaded_at": datetime.now(timezone.utc).isoformat(), "has_more": {}}

    has_qb = bool(cached("qb", lambda: None))
    now_iso = datetime.now(timezone.utc).isoformat()

    # Compute compare_forms if requested (last year same months)
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

        def _rag_for_value(v, green, amber, good_when_high=True):
            if good_when_high:
                if v >= green: return "green"
                if v >= amber: return "amber"
                return "red"
            else:
                if v <= green: return "green"
                if v <= amber: return "amber"
                return "red"

        kpis = [
            _kpi_dict("Schedule Compliance", sched_c["completion_pct"], "%",
                      rag=_rag_for_value(sched_c["completion_pct"], 80, 60)),
            _kpi_dict("Overdue Items", float(sched_c["overdue"]), "",
                      rag=_rag_for_value(sched_c["overdue"], 5, 15, False)),
            _kpi_dict("BBSO Observations", float(brc["total_bbso"]), "",
                      hint=f"{brc['bbso_this_month']} this month · {brc['bbso_contributors']} observers"),
            _kpi_dict("RIR / Near Miss Reports", float(brc["total_rir"]), "",
                      hint=f"{brc['rir_this_month']} this month · {brc['rir_contributors']} reporters"),
            _kpi_dict("Worker Participation", part["pct"], "%",
                      rag=_rag_for_value(part["pct"], 80, 60)),
            _kpi_dict("BBSO:Incident Ratio", float(bir["ratio"]), ":1",
                      hint=f"{bir['total_bbso']} BBSO · {bir['total_incidents']} incidents",
                      rag=_rag_for_value(bir["ratio"], 5, 2)),
            _kpi_dict("Reporting Culture Index", float(rir_ratio["ratio"]), ":1",
                      hint=f"{rir_ratio['total_rir']} RIRs · {rir_ratio['total_incidents']} incidents",
                      rag=_rag_for_value(rir_ratio["ratio"], 5, 2)),
            _kpi_dict("Avg Incident Close Time", float(close_time["mean_days"]), "days",
                      hint=f"median {close_time['median_days']}d · {close_time['closed_count']} closed",
                      rag=_rag_for_value(close_time["mean_days"], 14, 30, False)),
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

        return {"kpis": kpis, "charts": charts, "loaded_at": now_iso, "has_more": {}}

    elif section == "forms":
        f_count = SD.form_counts(ds.forms)
        w_count = SD.worker_counts(ds.workers)
        brc = SD.bbso_rir_counts(ds.forms)
        kpis = [
            _kpi_dict("Total Forms", float(f_count["total"]), ""),
            _kpi_dict("This Month", float(f_count["month"]), ""),
            _kpi_dict("BBSO", float(brc["total_bbso"]), "", hint=f"{brc['bbso_this_month']} this month"),
            _kpi_dict("RIR / Near Miss", float(brc["total_rir"]), "", hint=f"{brc['rir_this_month']} this month"),
            _kpi_dict("Active Workers", float(w_count["active"]), ""),
        ]
        charts = {
            "form_category": {"html": SDC.form_category_chart(ds.forms), "title": "Forms by Category"},
            "forms_trend": {"html": SDC.forms_trend(ds.forms, compare_forms=compare_forms), "title": "Monthly Trend"},
            "bbso_trend": {"html": SDC.bbso_trend(ds.forms, compare_forms=compare_forms), "title": "Monthly BBSO Trend"},
            "rir_trend": {"html": SDC.rir_trend(ds.forms, compare_forms=compare_forms), "title": "Monthly RIR Trend"},
            "form_types": {"html": SDC.form_types_chart(ds.formtypes, ds.forms), "title": "Forms by Type"},
        }
        return {"kpis": kpis, "charts": charts, "loaded_at": now_iso, "has_more": {}}

    elif section == "compliance":
        sched_c = SD.schedule_counts(ds.schedules)
        brc = SD.bbso_rir_counts(ds.forms)

        def _rag(v, g, a, gh=True):
            if gh:
                if v >= g: return "green"
                if v >= a: return "amber"
                return "red"
            else:
                if v <= g: return "green"
                if v <= a: return "amber"
                return "red"

        kpis = [
            _kpi_dict("Completion Rate", sched_c["completion_pct"], "%", rag=_rag(sched_c["completion_pct"], 80, 60)),
            _kpi_dict("Overdue", float(sched_c["overdue"]), "", rag=_rag(sched_c["overdue"], 5, 15, False)),
            _kpi_dict("Late", float(sched_c["late"]), ""),
            _kpi_dict("Cancelled", float(sched_c["cancelled"]), ""),
            _kpi_dict("BBSO This Month", float(brc["bbso_this_month"]), "", hint=f"{brc['total_bbso']} total"),
            _kpi_dict("RIR This Month", float(brc["rir_this_month"]), "", hint=f"{brc['total_rir']} total"),
        ]
        charts = {
            "schedule_compliance": {"html": SDC.schedule_compliance(ds.schedules), "title": "Schedule Compliance"},
            "bbso_trend": {"html": SDC.bbso_trend(ds.forms, compare_forms=compare_forms), "title": "Monthly BBSO Trend"},
            "rir_trend": {"html": SDC.rir_trend(ds.forms, compare_forms=compare_forms), "title": "Monthly RIR Trend"},
            "forms_trend": {"html": SDC.forms_trend(ds.forms, compare_forms=compare_forms), "title": "Forms Trend"},
            "leaderboard": {"html": SDC.bbso_rir_leaderboard_table(ds.workers, ds.forms), "title": "BBSO & RIR by Worker"},
            "overdue": {"html": SDC.overdue_items_list(ds.schedules), "title": "Overdue & Late Items"},
        }
        return {"kpis": kpis, "charts": charts, "loaded_at": now_iso, "has_more": {}}

    elif section == "workers":
        w_count = SD.worker_counts(ds.workers)
        part = SD.worker_participation(ds.workers, ds.forms)
        brc = SD.bbso_rir_counts(ds.forms)
        kpis = [
            _kpi_dict("Active Workers", float(w_count["active"]), "", hint=f"of {w_count['total']} total"),
            _kpi_dict("Contractors", float(w_count["contractors"]), "", hint=f"{w_count['employees']} employees"),
            _kpi_dict("Participation", part["pct"], "%", rag="green" if part["pct"] >= 80 else "amber" if part["pct"] >= 60 else "red"),
            _kpi_dict("BBSO Contributors", float(brc["bbso_contributors"]), "", hint=f"{brc['total_bbso']} total BBSOs"),
            _kpi_dict("RIR Contributors", float(brc["rir_contributors"]), "", hint=f"{brc['total_rir']} total RIRs"),
        ]
        charts = {
            "status": {"html": SDC.worker_status(ds.workers), "title": "Active vs Inactive"},
            "type_split": {"html": SDC.worker_type_split(ds.workers), "title": "Employee vs Contractor"},
            "leaderboard": {"html": SDC.bbso_rir_leaderboard_table(ds.workers, ds.forms), "title": "BBSO & RIR by Worker"},
            "activity": {"html": SDC.worker_leaderboard_table(ds.workers, ds.forms, ds.signatures, ds.schedules), "title": "Worker Activity"},
        }
        return {"kpis": kpis, "charts": charts, "loaded_at": now_iso, "has_more": {}}

    return {"kpis": [], "charts": {}, "loaded_at": now_iso, "has_more": {}}