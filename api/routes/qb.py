"""QuickBooks API routes — serve KPIs, chart HTML, and CSV exports as JSON."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query

try:
    from zoneinfo import ZoneInfo
    _HOUSTON = ZoneInfo("America/Chicago")
except Exception:
    _HOUSTON = timezone.utc

from api.cache import cached
from api.utils import resolve_date_range
from api.csv_export import to_csv_response
from data import qb_data as QB
from charts import qb_charts as QBC

router = APIRouter()

# ── KPI helpers ─────────────────────────────────────────────────────


def _fmt_val(value, unit=""):
    if isinstance(value, float):
        if unit == "$":
            if abs(value) >= 1e6: return f"${value / 1e6:,.2f}M"
            if abs(value) >= 1000: return f"${value / 1000:,.0f}K"
            return f"${value:,.0f}"
        if unit == "%": return f"${value:.1f}%"
        if unit == "days": return f"${value:.0f}d"
        if value == int(value): return f"${int(value):,}"
        return f"${value:,.1f}"
    if isinstance(value, int): return f"${value:,}"
    return str(value)


def _kpi(label, value, unit="", hint="", delta=None, delta_up_good=True, help=""):
    return {
        "label": label, "value": value, "unit": unit, "hint": hint or "",
        "rag": None, "platform": "QB", "delta": delta,
        "delta_up_good": delta_up_good, "help": help, "deltaLabel": "",
    }


# ── Section handlers ────────────────────────────────────────────────


def _section_overview(ds, invoices, start, end, basis, metric):
    kpis_all = QB.compute_kpis(ds, invoices, start, end)
    kpis = []
    for k in ["revenue", "cash", "outstanding", "overdue", "dso", "active_customers"]:
        if k in kpis_all:
            kp = kpis_all[k]
            kpis.append(_kpi(kp.label, _fmt_val(kp.value, kp.unit), kp.unit, kp.hint,
                            kp.delta, kp.delta_good_when_up))
    return kpis, invoices


def _section_sales(ds, invoices, start, end, basis, metric):
    kpis_all = QB.compute_kpis(ds, invoices, start, end)
    kpis = []
    for k in ["revenue", "collected", "invoice_count", "avg_invoice"]:
        if k in kpis_all:
            kp = kpis_all[k]
            kpis.append(_kpi(kp.label, _fmt_val(kp.value, kp.unit), kp.unit, kp.hint,
                            kp.delta, kp.delta_good_when_up))
    return kpis, invoices


def _section_finance(ds, invoices, start, end, basis, metric):
    kpis_all = QB.compute_kpis(ds, invoices, start, end)
    kpis = []
    for k in ["cash", "outstanding", "dso", "working_capital", "current_ratio", "total_liabilities"]:
        if k in kpis_all:
            kp = kpis_all[k]
            kpis.append(_kpi(kp.label, _fmt_val(kp.value, kp.unit), kp.unit, kp.hint,
                            kp.delta, kp.delta_good_when_up))
    return kpis, ds.accounts


def _section_profitability(ds, invoices, start, end, basis, metric):
    kpis_all = QB.pnl_kpis(ds, basis, start, end)
    kpis = []
    for k in ["pnl_income", "pnl_cogs", "pnl_gross_profit", "pnl_gross_margin", "pnl_net_income", "pnl_net_margin"]:
        if k in kpis_all:
            kp = kpis_all[k]
            kpis.append(_kpi(kp.label, _fmt_val(kp.value, kp.unit), kp.unit, kp.hint,
                            kp.delta, kp.delta_good_when_up))
    return kpis, ds.pnl


def _section_customers(ds, invoices, start, end, basis, metric):
    kpis_all = QB.compute_kpis(ds, invoices, start, end)
    kpis = []
    for k in ["active_customers", "total_customers", "outstanding", "overdue"]:
        if k in kpis_all:
            kp = kpis_all[k]
            kpis.append(_kpi(kp.label, _fmt_val(kp.value, kp.unit), kp.unit, kp.hint,
                            kp.delta, kp.delta_good_when_up))
    # build customer summary for export
    cust_df = (
        invoices.groupby("CustomerName", as_index=False)
        .agg(Revenue=("Revenue", "sum"), InvoiceCount=("InvoiceId", "nunique"))
        .sort_values("Revenue", ascending=False)
    )
    return kpis, cust_df


def _section_accounts(ds, invoices, start, end, basis, metric):
    kpis_all = QB.compute_kpis(ds, invoices, start, end)
    kpis = []
    for k in ["total_assets", "total_liabilities", "equity", "cash"]:
        if k in kpis_all:
            kp = kpis_all[k]
            kpis.append(_kpi(kp.label, _fmt_val(kp.value, kp.unit), kp.unit, kp.hint,
                            kp.delta, kp.delta_good_when_up))
    return kpis, ds.accounts


_SECTION_HANDLERS = {
    "overview": _section_overview, "sales": _section_sales,
    "finance": _section_finance, "profitability": _section_profitability,
    "customers": _section_customers, "accounts": _section_accounts,
}

# Chart builders — called separately to avoid generating charts during CSV export
_CHARTS = {
    "overview": lambda ds, inv, s, e, b, m: _charts_overview(ds, inv, s, e, b, m),
    "sales": lambda ds, inv, s, e, b, m: _charts_sales(ds, inv, s, e, b, m),
    "finance": lambda ds, inv, s, e, b, m: _charts_finance(ds, inv, s, e, b, m),
    "profitability": lambda ds, inv, s, e, b, m: _charts_profitability(ds, inv, s, e, b, m),
    "customers": lambda ds, inv, s, e, b, m: _charts_customers(ds, inv, s, e, b, m),
    "accounts": lambda ds, inv, s, e, b, m: _charts_accounts(ds, inv, s, e, b, m),
}


def _charts_overview(ds, invoices, start, end, basis, metric):
    charts = {}
    try:
        if not invoices.empty:
            charts["revenue-trend"] = {"html": QBC.trend(invoices, metric), "title": "Monthly Revenue Trend"}
            charts["ar-aging"] = {"html": QBC.ar_aging(invoices), "title": "A/R Aging"}
            charts["revenue-by-class"] = {"html": QBC.revenue_by_class(invoices), "title": "Revenue by Segment"}
            charts["top-customers"] = {"html": QBC.top_customers(invoices), "title": "Top Customers"}
    except Exception:
        pass
    return charts


def _charts_sales(ds, invoices, start, end, basis, metric):
    charts = {}
    try:
        if not invoices.empty:
            charts["revenue-trend"] = {"html": QBC.trend(invoices, metric), "title": "Monthly Revenue"}
            charts["revenue-by-item"] = {"html": QBC.revenue_by_item(invoices), "title": "Revenue by Service/Product"}
            charts["revenue-by-class"] = {"html": QBC.revenue_by_class(invoices), "title": "Revenue by Segment"}
            charts["top-customers"] = {"html": QBC.top_customers(invoices), "title": "Top Customers"}
            charts["customer-ranking"] = {"html": QBC.class_period_ranking(invoices, start, end), "title": "Customers (Period)"}
    except Exception:
        pass
    return charts


def _charts_finance(ds, invoices, start, end, basis, metric):
    charts = {}
    try:
        if not ds.accounts.empty:
            charts["balance-sheet"] = {"html": QBC.balance_sheet(ds.accounts), "title": "Balance Sheet"}
            charts["accounts-by-type"] = {"html": QBC.accounts_by_type(ds.accounts), "title": "Assets by Type"}
        if not invoices.empty:
            charts["ar-aging"] = {"html": QBC.ar_aging(invoices), "title": "A/R Aging"}
            charts["balance-status"] = {"html": QBC.balance_status(invoices), "title": "Invoice Balance Status"}
            charts["dso-trend"] = {"html": QBC.dso_trend(invoices, start, end), "title": "Monthly DSO Trend"}
    except Exception:
        pass
    return charts


def _charts_profitability(ds, invoices, start, end, basis, metric):
    pnl_sum = QB.pnl_summary(ds.pnl, basis, start, end)
    charts = {}
    try:
        if pnl_sum.get("income", 0):
            charts["pnl-waterfall"] = {"html": QBC.pnl_waterfall(pnl_sum), "title": "P&L Waterfall"}
        if not ds.pnl.empty:
            charts["pnl-trend"] = {"html": QBC.pnl_trend(ds.pnl, basis), "title": f"Monthly P&L Trend ({basis})"}
        if not ds.pnl_detail.empty:
            charts["pnl-expenses"] = {"html": QBC.pnl_expenses(ds.pnl_detail, basis, start, end), "title": "Top Expenses"}
    except Exception:
        pass
    return charts


def _charts_customers(ds, invoices, start, end, basis, metric):
    charts = {}
    try:
        if not invoices.empty:
            charts["top-customers"] = {"html": QBC.top_customers(invoices), "title": "Top Customers"}
            charts["revenue-by-city"] = {"html": QBC.revenue_by_city(invoices), "title": "Revenue by Region"}
            charts["customer-ranking"] = {"html": QBC.class_period_ranking(invoices, start, end), "title": "Customers (Period)"}
    except Exception:
        pass
    return charts


def _charts_accounts(ds, invoices, start, end, basis, metric):
    charts = {}
    try:
        if not ds.accounts.empty:
            charts["accounts-by-type"] = {"html": QBC.accounts_by_type(ds.accounts), "title": "Balances by Type"}
            charts["accounts-by-classification"] = {"html": QBC.accounts_by_classification(ds.accounts), "title": "Balances by Classification"}
            charts["balance-sheet"] = {"html": QBC.balance_sheet(ds.accounts), "title": "Balance Sheet"}
    except Exception:
        pass
    return charts


@router.get("/_api/qb/{section}")
def qb_section(
    section: str,
    basis: str = Query("accrual"),
    range: str = Query("all"),
    metric: str = Query("revenue"),
    format: str | None = Query(None),
):
    now_iso = datetime.now(_HOUSTON).isoformat()
    ds = cached("qb", QB.qb_load_dataset)
    if not ds:
        return {"kpis": [], "charts": {}, "loaded_at": now_iso}

    start, end = resolve_date_range(range)
    invoices = QB.filter_invoices(ds.invoices, start, end)
    handler = _SECTION_HANDLERS.get(section)
    if handler is None:
        return {"kpis": [], "charts": {}, "loaded_at": now_iso, "error": f"Unknown section: {section}"}

    kpis, export_df = handler(ds, invoices, start, end, basis, metric)

    # CSV export
    if format == "csv":
        return to_csv_response(export_df, filename=f"qb_{section}_{range}.csv")

    # Charts — only generate when not exporting
    chart_builder = _CHARTS.get(section)
    charts = chart_builder(ds, invoices, start, end, basis, metric) if chart_builder else {}

    return {
        "kpis": kpis, "charts": charts,
        "loaded_at": now_iso, "has_more": {"qb": True},
        "section": section, "basis": basis, "range": range,
        "range_info": f"{range.upper()} · {start.strftime('%b %d')} – {end.strftime('%b %d, %Y')}",
    }
