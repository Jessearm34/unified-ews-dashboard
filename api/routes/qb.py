"""QuickBooks API routes — serve KPIs and chart HTML as JSON.

Mirrors render_qb_section() from the original app.py (lines 706–877) as
a FastAPI JSON API, using api.cache.cached() for data loading and the
existing data/qb_data and charts/qb_charts modules.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query

from api.cache import cached
from api.utils import resolve_date_range
from data import qb_data as QB
from charts import qb_charts as QBC

router = APIRouter()

# ── KPI formatting helpers ──────────────────────────────────────────────


def _fmt_val(value, unit=""):
    """Format a KPI value as a display string (matches app.py kpi_card)."""
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


def _kpi_dict(kpi: QB.Kpi) -> dict:
    """Convert a QB.Kpi namedtuple to a JSON-serialisable dict."""
    return {
        "key": kpi.key,
        "label": kpi.label or kpi.key,
        "value": kpi.value,
        "display": _fmt_val(kpi.value, kpi.unit),
        "unit": kpi.unit,
        "delta": kpi.delta,
        "delta_up_good": kpi.delta_good_when_up,
        "chartable": kpi.chartable,
        "hint": kpi.hint or "",
    }


# ── Section handlers ────────────────────────────────────────────────────


def _section_overview(ds, invoices, start, end, basis, metric):
    """Overview: 6 KPIs + 4 charts."""
    kpis_all = QB.compute_kpis(ds, invoices, start, end)
    keys = ["revenue", "cash", "outstanding", "overdue", "dso", "active_customers"]
    kpis = [_kpi_dict(kpis_all[k]) for k in keys if k in kpis_all]

    charts = {}
    try:
        if not invoices.empty:
            charts["revenue-trend"] = {
                "html": QBC.trend(invoices, metric),
                "title": "Monthly Revenue Trend",
            }
            charts["ar-aging"] = {
                "html": QBC.ar_aging(invoices),
                "title": "A/R Aging",
            }
            charts["revenue-by-class"] = {
                "html": QBC.revenue_by_class(invoices),
                "title": "Revenue by Segment",
            }
            charts["top-customers"] = {
                "html": QBC.top_customers(invoices),
                "title": "Top Customers",
            }
    except Exception:
        pass

    return kpis, charts


def _section_sales(ds, invoices, start, end, basis, metric):
    """Sales: 4 KPIs + 4 charts."""
    kpis_all = QB.compute_kpis(ds, invoices, start, end)
    keys = ["revenue", "collected", "invoice_count", "avg_invoice"]
    kpis = [_kpi_dict(kpis_all[k]) for k in keys if k in kpis_all]

    charts = {}
    try:
        if not invoices.empty:
            charts["revenue-trend"] = {
                "html": QBC.trend(invoices, metric),
                "title": "Monthly Revenue",
            }
            charts["revenue-by-item"] = {
                "html": QBC.revenue_by_item(invoices),
                "title": "Revenue by Service/Product",
            }
            charts["revenue-by-class"] = {
                "html": QBC.revenue_by_class(invoices),
                "title": "Revenue by Segment",
            }
            charts["top-customers"] = {
                "html": QBC.top_customers(invoices),
                "title": "Top Customers",
            }
    except Exception:
        pass

    return kpis, charts


def _section_finance(ds, invoices, start, end, basis, metric):
    """Finance: 6 KPIs + 4 charts."""
    kpis_all = QB.compute_kpis(ds, invoices, start, end)
    keys = ["cash", "outstanding", "dso", "working_capital", "current_ratio", "total_liabilities"]
    kpis = [_kpi_dict(kpis_all[k]) for k in keys if k in kpis_all]

    charts = {}
    try:
        if not ds.accounts.empty:
            charts["balance-sheet"] = {
                "html": QBC.balance_sheet(ds.accounts),
                "title": "Balance Sheet",
            }
            charts["accounts-by-type"] = {
                "html": QBC.accounts_by_type(ds.accounts),
                "title": "Assets by Type",
            }
        if not invoices.empty:
            charts["ar-aging"] = {
                "html": QBC.ar_aging(invoices),
                "title": "A/R Aging",
            }
            charts["balance-status"] = {
                "html": QBC.balance_status(invoices),
                "title": "Invoice Balance Status",
            }
    except Exception:
        pass

    return kpis, charts


def _section_profitability(ds, invoices, start, end, basis, metric):
    """Profitability: 6 P&L KPIs + 3 charts (uses basis for P&L)."""
    pnl_sum = QB.pnl_summary(ds.pnl, basis, start, end)
    kpis_all = QB.pnl_kpis(ds, basis, start, end)
    keys = ["pnl_income", "pnl_cogs", "pnl_gross_profit", "pnl_gross_margin", "pnl_net_income", "pnl_net_margin"]
    kpis = [_kpi_dict(kpis_all[k]) for k in keys if k in kpis_all]

    charts = {}
    try:
        if pnl_sum.get("income", 0):
            charts["pnl-waterfall"] = {
                "html": QBC.pnl_waterfall(pnl_sum),
                "title": "P&L Waterfall",
            }
        if not ds.pnl.empty:
            charts["pnl-trend"] = {
                "html": QBC.pnl_trend(ds.pnl, basis),
                "title": f"Monthly P&L Trend ({basis})",
            }
        if not ds.pnl_detail.empty:
            charts["pnl-expenses"] = {
                "html": QBC.pnl_expenses(ds.pnl_detail, basis, start, end),
                "title": "Top Expenses",
            }
    except Exception:
        pass

    return kpis, charts


def _section_customers(ds, invoices, start, end, basis, metric):
    """Customers: 4 KPIs + 2 charts."""
    kpis_all = QB.compute_kpis(ds, invoices, start, end)
    keys = ["active_customers", "total_customers", "outstanding", "overdue"]
    kpis = [_kpi_dict(kpis_all[k]) for k in keys if k in kpis_all]

    charts = {}
    try:
        if not invoices.empty:
            charts["top-customers"] = {
                "html": QBC.top_customers(invoices),
                "title": "Top Customers",
            }
            charts["revenue-by-city"] = {
                "html": QBC.revenue_by_city(invoices),
                "title": "Revenue by Region",
            }
    except Exception:
        pass

    return kpis, charts


def _section_accounts(ds, invoices, start, end, basis, metric):
    """Accounts: 4 KPIs + 3 charts."""
    kpis_all = QB.compute_kpis(ds, invoices, start, end)
    keys = ["total_assets", "total_liabilities", "equity", "cash"]
    kpis = [_kpi_dict(kpis_all[k]) for k in keys if k in kpis_all]

    charts = {}
    try:
        if not ds.accounts.empty:
            charts["accounts-by-type"] = {
                "html": QBC.accounts_by_type(ds.accounts),
                "title": "Balances by Type",
            }
            charts["accounts-by-classification"] = {
                "html": QBC.accounts_by_classification(ds.accounts),
                "title": "Balances by Classification",
            }
            charts["balance-sheet"] = {
                "html": QBC.balance_sheet(ds.accounts),
                "title": "Balance Sheet",
            }
    except Exception:
        pass

    return kpis, charts


# ── Section dispatch ────────────────────────────────────────────────────

_SECTION_HANDLERS = {
    "overview": _section_overview,
    "sales": _section_sales,
    "finance": _section_finance,
    "profitability": _section_profitability,
    "customers": _section_customers,
    "accounts": _section_accounts,
}


# ── Endpoint ────────────────────────────────────────────────────────────


@router.get("/_api/qb/{section}")
def qb_section(
    section: str,
    basis: str = Query("accrual", description="Accounting basis: accrual or cash"),
    range: str = Query("all", description="Date range key"),
    metric: str = Query("revenue", description="Chart metric (revenue, invoice_count, avg_invoice)"),
):
    """Return KPI data + chart HTML for a QuickBooks dashboard section.

    Mirrors render_qb_section() from the original app.py as a JSON API.
    Supports sections: overview, sales, finance, profitability, customers, accounts.
    Each returns:
      - ``kpis`` — list of dicts with key, label, value, display, unit, delta, hint
      - ``charts`` — dict of chart_id → {html, title}
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    ds = cached("qb", QB.qb_load_dataset)
    if not ds:
        return {
            "kpis": [],
            "charts": {},
            "loaded_at": now_iso,
            "has_more": {},
            "section": section,
            "basis": basis,
            "range": range,
        }

    start, end = resolve_date_range(range)
    invoices = QB.filter_invoices(ds.invoices, start, end)

    handler = _SECTION_HANDLERS.get(section)
    if handler is None:
        return {
            "kpis": [],
            "charts": {},
            "loaded_at": now_iso,
            "has_more": {"qb": True},
            "section": section,
            "basis": basis,
            "range": range,
            "error": f"Unknown section: {section}",
        }

    kpis, charts = handler(ds, invoices, start, end, basis, metric)

    return {
        "kpis": kpis,
        "charts": charts,
        "loaded_at": now_iso,
        "has_more": {"qb": True},
        "section": section,
        "basis": basis,
        "range": range,
    }