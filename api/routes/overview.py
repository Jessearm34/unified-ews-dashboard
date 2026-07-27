"""Overview API route — returns KPIs and chart HTML for both platforms.

Mirrors the original render_overview() from app.py (lines 488–610) as a
JSON API endpoint, using FastAPI APIRouter and api.cache.cached() for data.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Query

from api.cache import cached
from api.utils import resolve_date_range
from charts import qb_charts as QBC
from charts import sd_charts as SDC
from data import qb_data as QB
from data import sd_data as SD

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


def _qb_kpis(qb_ds, start, end):
    """QB KPI dicts — mirrors app.py lines 517–527."""
    invoices = QB.filter_invoices(qb_ds.invoices, date(2020, 1, 1), date.today())
    bs = QB.balance_sheet_summary(qb_ds.accounts)
    pnl = QB.pnl_summary(qb_ds.pnl, "accrual", start, end)
    revenue = (
        pnl["income"]
        if not qb_ds.pnl.empty
        else (float(invoices["Revenue"].sum()) if not invoices.empty else 0.0)
    )
    return [
        {"label": "Revenue", "value": _fmt_val(revenue, "$"), "unit": "$", "platform": "QB", "hint": "", "rag": None},
        {"label": "Cash on Hand", "value": _fmt_val(bs["cash"], "$"), "unit": "$", "platform": "QB", "hint": "", "rag": None},
        {"label": "Outstanding AR", "value": _fmt_val(bs["ar"], "$"), "unit": "$", "platform": "QB", "hint": "", "rag": None},
        {"label": "Net Income", "value": _fmt_val(pnl["net_income"], "$"), "unit": "$", "platform": "QB", "hint": "", "rag": None},
    ]


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
        },
        {
            "label": "Overdue Items",
            "value": _fmt_val(float(sched_c["overdue"])),
            "unit": "",
            "platform": "SD",
            "hint": "",
            "rag": _rag(sched_c["overdue"], 5, 15, False),
        },
        {
            "label": "BBSO",
            "value": _fmt_val(float(brc["total_bbso"])),
            "unit": "",
            "platform": "SD",
            "hint": f"{brc['bbso_this_month']} this month",
            "rag": None,
        },
        {
            "label": "RIR / Near Miss",
            "value": _fmt_val(float(brc["total_rir"])),
            "unit": "",
            "platform": "SD",
            "hint": f"{brc['rir_this_month']} this month",
            "rag": None,
        },
    ]


# ── Chart builders ──────────────────────────────────────────────────────────


def _qb_charts(qb_ds, start, end):
    """Build QB chart dicts — mirrors app.py lines 566–573."""
    charts = {}
    if qb_ds:
        try:
            inv = QB.filter_invoices(qb_ds.invoices, start, end)
            if not inv.empty:
                charts["revenue-trend"] = {
                    "html": QBC.trend(inv, "revenue"),
                    "title": "Monthly Revenue Trend",
                }
        except Exception:
            pass
    return charts


def _sd_charts(sd_ds):
    """Build SD chart dicts — mirrors app.py lines 575–603."""
    charts = {}
    if sd_ds:
        # Schedule Compliance
        try:
            if not sd_ds.schedules.empty:
                sched_c = SD.schedule_counts(sd_ds.schedules)
                if sched_c.get("total", 0) > 0:
                    charts["schedule-compliance"] = {
                        "html": SDC.schedule_compliance(sd_ds.schedules),
                        "title": "Schedule Compliance",
                    }
        except Exception:
            pass

        # Monthly BBSO
        try:
            if not sd_ds.forms.empty:
                charts["monthly-bbso"] = {
                    "html": SDC.bbso_trend(sd_ds.forms),
                    "title": "Monthly BBSO",
                }
        except Exception:
            pass

        # Forms Monthly Trend
        try:
            if not sd_ds.forms.empty:
                charts["forms-trend"] = {
                    "html": SDC.forms_trend(sd_ds.forms),
                    "title": "Forms Monthly Trend",
                }
        except Exception:
            pass

    return charts


# ── Endpoint ────────────────────────────────────────────────────────────────


@router.get("/_api/overview")
def overview(range: str = Query("ytd", description="Date range key")):
    """Return KPI data + chart HTML for the Overview dashboard.

    Mirrors the original render_overview() from app.py as a JSON API.
    Chart HTML strings (Plotly .to_html()) are returned directly — not
    serialised to JSON.
    """
    start, end = resolve_date_range(range)

    qb_ds = cached("qb", QB.qb_load_dataset)
    sd_ds = cached("sd", SD.sd_load_dataset)

    kpis = []
    if qb_ds:
        kpis.extend(_qb_kpis(qb_ds, start, end))
    if sd_ds:
        kpis.extend(_sd_kpis(sd_ds))

    charts = {}
    charts.update(_qb_charts(qb_ds, start, end))
    charts.update(_sd_charts(sd_ds))

    return {
        "kpis": kpis,
        "charts": charts,
        "loaded_at": datetime.now(timezone.utc).isoformat(),
        "has_more": {
            "qb": qb_ds is not None,
            "sd": sd_ds is not None,
        },
    }