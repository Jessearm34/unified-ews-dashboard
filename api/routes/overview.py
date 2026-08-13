"""Overview API route — returns KPIs and chart HTML for both platforms.

Mirrors the original render_overview() from app.py (lines 488–610) as a
JSON API endpoint, using FastAPI APIRouter and api.cache.cached() for data.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone

import pandas as pd
from fastapi import APIRouter, Query

from api.cache import cached
from api.chart_errors import safe_chart
from api.csv_export import to_csv_response
from api.utils import resolve_date_range, previous_range, compute_delta

import logging
log = logging.getLogger("ewsd.overview")

# Houston timezone
try:
    from zoneinfo import ZoneInfo
    _HOUSTON = ZoneInfo("America/Chicago")
except Exception:
    _HOUSTON = timezone.utc
from charts import qb_charts as QBC
from charts import sd_charts as SDC
from charts import issues_charts as IC
from charts import cross_charts as XC
from data import qb_data as QB
from data import sd_data as SD
from data import issues as ISS

router = APIRouter()


# ── KPI formatting helpers (mirror app.py kpi_card / rag_for_value) ────────


def _fmt_val(value, unit=""):
    """Format a KPI value as a display string, matching app.py kpi_card()."""
    if isinstance(value, float):
        if unit == "$":
            if abs(value) >= 1e6:
                return f"${value / 1e6:,.2f}M"
            if abs(value) >= 1000:
                return f"${value / 1000:,.0f}K"
            return f"${value:,.0f}"
        if unit == "%":
            return f"{value:.1f}%"
        if unit == "days":
            return f"{value:.0f}d"
        if value == int(value):
            return f"{int(value):,}"
        return f"{value:,.1f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _rag(value, green, amber, good_when_high=True):
    """Replica of app.py rag_for_value()."""
    if good_when_high:
        if value >= green:
            return "green"
        if value >= amber:
            return "amber"
        return "red"
    if value <= green:
        return "green"
    if value <= amber:
        return "amber"
    return "red"


# ── KPI builders ────────────────────────────────────────────────────────────


def _sd_kpis(sd_ds):
    """SD KPI dicts — mirrors app.py lines 530–549."""
    sched_c = SD.schedule_counts(sd_ds.schedules)
    brc = SD.bbso_rir_counts(sd_ds.forms)
    return [
        {
            "label": "Schedule Compliance",
            "value": _fmt_val(sched_c["completion_pct"], "%"),
            "unit": "%",
            "platform": "SD",
            "hint": "",
            "rag": _rag(sched_c["completion_pct"], 80, 60),
            "delta": None,
            "delta_up_good": True,
        },
        {
            "label": "Overdue Items",
            "value": _fmt_val(float(sched_c["overdue"])),
            "unit": "",
            "platform": "SD",
            "hint": "",
            "rag": _rag(sched_c["overdue"], 5, 15, False),
            "delta": None,
            "delta_up_good": False,
        },
        {
            "label": "BBSO",
            "value": _fmt_val(float(brc["total_bbso"])),
            "unit": "",
            "platform": "SD",
            "hint": f"{brc['bbso_this_month']} this month",
            "rag": None,
            "delta": None,
            "delta_up_good": True,
        },
        {
            "label": "RIR / Near Miss",
            "value": _fmt_val(float(brc["total_rir"])),
            "unit": "",
            "platform": "SD",
            "hint": f"{brc['rir_this_month']} this month",
            "rag": None,
            "delta": None,
            "delta_up_good": True,
        },
    ]


def _qb_kpis(qb_ds, start, end, prev_start, prev_end):
    """QB KPI dicts with period-over-period deltas."""
    invoices = QB.filter_invoices(qb_ds.invoices, date(2020, 1, 1), date.today())
    bs = QB.balance_sheet_summary(qb_ds.accounts)
    pnl = QB.pnl_summary(qb_ds.pnl, "accrual", start, end)
    revenue = (
        pnl["income"]
        if not qb_ds.pnl.empty
        else (float(invoices["Revenue"].sum()) if not invoices.empty else 0.0)
    )
    gross = revenue - abs(pnl.get("cogs", 0))
    margin = (gross / revenue * 100) if revenue > 0 else 0
    dso = QB.compute_dso(invoices, start, end) if not invoices.empty else 0

    prev_invoices = QB.filter_invoices(qb_ds.invoices, prev_start, prev_end) if prev_start != start else invoices
    prev_pnl = QB.pnl_summary(qb_ds.pnl, "accrual", prev_start, prev_end)
    prev_revenue = (
        prev_pnl["income"]
        if not qb_ds.pnl.empty
        else (float(prev_invoices["Revenue"].sum()) if not prev_invoices.empty else 0.0)
    )
    prev_margin = ((prev_revenue - abs(prev_pnl.get("cogs", 0))) / prev_revenue * 100) if prev_revenue > 0 else 0

    return [
        {"label": "Revenue", "value": _fmt_val(revenue, "$"), "unit": "$", "platform": "QB", "hint": "", "rag": None,
         "delta": compute_delta(revenue, prev_revenue), "delta_up_good": True, "deltaLabel": "vs. prior period"},
        {"label": "Gross Margin", "value": _fmt_val(margin, "%"), "unit": "%", "platform": "QB", "hint": "", "rag": _rag(margin, 40, 20),
         "delta": compute_delta(margin, prev_margin), "delta_up_good": True, "deltaLabel": "vs. prior period"},
        {"label": "Cash on Hand", "value": _fmt_val(bs["cash"], "$"), "unit": "$", "platform": "QB", "hint": "", "rag": None,
         "delta": None, "delta_up_good": True},
        {"label": "Outstanding AR", "value": _fmt_val(bs["ar"], "$"), "unit": "$", "platform": "QB", "hint": "", "rag": None,
         "delta": None, "delta_up_good": False, "help": "Accounts receivable — invoiced but not yet collected"},
        {"label": "DSO", "value": _fmt_val(dso, "days"), "unit": "days", "platform": "QB", "hint": "Days sales outstanding", "rag": _rag(dso, 45, 60, False),
         "delta": None, "delta_up_good": False},
        {"label": "Net Income", "value": _fmt_val(pnl["net_income"], "$"), "unit": "$", "platform": "QB", "hint": "", "rag": None,
         "delta": compute_delta(pnl["net_income"], prev_pnl["net_income"]), "delta_up_good": True, "deltaLabel": "vs. prior period"},
    ]


# ── Chart builders ──────────────────────────────────────────────────────────


def _qb_charts(qb_ds, start, end, compare: bool = False, prev_start=None, prev_end=None):
    """Build QB chart dicts — mirrors app.py lines 566–573."""
    charts = {}
    if qb_ds:
        inv = QB.filter_invoices(qb_ds.invoices, start, end)
        if not inv.empty:
            comp_inv = None
            if compare and prev_start and prev_end and prev_start != start:
                comp_inv = QB.filter_invoices(qb_ds.invoices, prev_start, prev_end)
            html = safe_chart(
                lambda: QBC.trend(inv, "revenue", compare_invoices=comp_inv),
                "revenue-trend",
            )
            if "Error rendering" not in html:
                charts["revenue-trend"] = {"html": html, "title": "Monthly Revenue Trend"}
    return charts


def _sd_charts(sd_ds, compare: bool = False, prev_start=None, prev_end=None):
    """Build SD chart dicts — mirrors app.py lines 575–603."""
    charts = {}
    if sd_ds:
        # Compute compare forms if requested
        compare_forms = None
        if compare and prev_start and prev_end and not sd_ds.forms.empty:
            try:
                prev_s = pd.Timestamp(prev_start)
                prev_e = pd.Timestamp(prev_end)
                date_col = "CreatedOn" if "CreatedOn" in sd_ds.forms.columns else "createdOn"
                if date_col in sd_ds.forms.columns:
                    forms_dates = pd.to_datetime(sd_ds.forms[date_col], errors="coerce")
                    mask = (forms_dates >= prev_s) & (forms_dates <= prev_e)
                    compare_forms = sd_ds.forms[mask].copy()
            except Exception:
                pass

        # Schedule Compliance
        if not sd_ds.schedules.empty:
            sched_c = SD.schedule_counts(sd_ds.schedules)
            if sched_c.get("total", 0) > 0:
                html = safe_chart(lambda: SDC.schedule_compliance(sd_ds.schedules), "schedule-compliance")
                if "Error rendering" not in html:
                    charts["schedule-compliance"] = {"html": html, "title": "Schedule Compliance"}

        # Monthly BBSO
        if not sd_ds.forms.empty:
            html = safe_chart(lambda: SDC.bbso_trend(sd_ds.forms, compare_forms=compare_forms), "monthly-bbso")
            if "Error rendering" not in html:
                charts["monthly-bbso"] = {"html": html, "title": "Monthly BBSO"}

        # Forms Monthly Trend
        if not sd_ds.forms.empty:
            html = safe_chart(lambda: SDC.forms_trend(sd_ds.forms, compare_forms=compare_forms), "forms-trend")
            if "Error rendering" not in html:
                charts["forms-trend"] = {"html": html, "title": "Forms Monthly Trend"}

    return charts


# ── Endpoint ────────────────────────────────────────────────────────────────


@router.get("/_api/overview")
def overview(range: str = Query("ytd", description="Date range key"),
             compare: bool = Query(False, description="Show year-over-year overlay on trend charts"),
             format: str | None = Query(None)):
    """Return KPI data + chart HTML for the Overview dashboard.

    Mirrors the original render_overview() from app.py as a JSON API.
    Chart HTML strings (Plotly .to_html()) are returned directly — not
    serialised to JSON.
    """
    start, end = resolve_date_range(range)
    prev_start, prev_end = previous_range(range, start, end)

    # CSV export — return raw invoices
    if format == "csv":
        qb_ds = cached("qb", QB.qb_load_dataset)
        if qb_ds and not qb_ds.invoices.empty:
            inv = QB.filter_invoices(qb_ds.invoices, start, end)
            return to_csv_response(inv, filename=f"overview_{range}.csv")
        return to_csv_response(pd.DataFrame(), filename="overview_empty.csv")

    # Load QB and SD in parallel
    qb_ds = None
    sd_ds = None
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {
            pool.submit(lambda: cached("qb", QB.qb_load_dataset)): "qb",
            pool.submit(lambda: cached("sd", SD.sd_load_dataset)): "sd",
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                result = future.result(timeout=30)
                if key == "qb":
                    qb_ds = result
                else:
                    sd_ds = result
            except Exception as exc:
                log.warning("Failed to load %s data in overview: %s", key, exc)

    kpis = []
    if qb_ds:
        kpis.extend(_qb_kpis(qb_ds, start, end, prev_start, prev_end))
    if sd_ds:
        kpis.extend(_sd_kpis(sd_ds))

    charts = {}
    charts.update(_qb_charts(qb_ds, start, end, compare=compare, prev_start=prev_start, prev_end=prev_end))
    charts.update(_sd_charts(sd_ds, compare=compare, prev_start=prev_start, prev_end=prev_end))

    # Issues Needing Attention — cross-platform
    try:
        issues = ISS.collect_issues(ds=sd_ds)
        if issues:
            charts["issues"] = {
                "html": IC.issues_table(issues),
                "title": "Issues Needing Attention",
            }
    except Exception:
        pass

    return {
        "kpis": kpis,
        "charts": charts,
        "loaded_at": datetime.now(_HOUSTON).isoformat(),
        "range_info": f"{range.upper()} · {start.strftime('%b %d')} – {end.strftime('%b %d, %Y')}",
        "has_more": {
            "qb": qb_ds is not None,
            "sd": sd_ds is not None,
        },
    }