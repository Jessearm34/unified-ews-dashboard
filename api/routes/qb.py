"""QuickBooks API routes — serve KPIs, chart HTML, invoice/customer/account tables.

Matches the eww-dashboard-public reference exactly — KPI sets, chart sections,
and drill-down features word-for-word.
"""

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

import pandas as pd

router = APIRouter()


# ── Helpers ──────────────────────────────────────────────────────────

def _money(v) -> str:
    return f"${v:,.2f}"


def _abbrev_money(v) -> str:
    n = abs(v)
    sign = "-" if v < 0 else ""
    if n >= 1e6:
        return f"{sign}${n / 1e6:,.2f}M"
    if n >= 1e3:
        return f"{sign}${n / 1e3:,.1f}K"
    return f"{sign}${n:,.0f}"


def _fmt_val(value, unit=""):
    if isinstance(value, float):
        if unit == "$":
            if abs(value) >= 1e6: return f"${value / 1e6:,.2f}M"
            if abs(value) >= 1000: return f"${value / 1000:,.0f}K"
            return f"${value:,.0f}"
        if unit == "%": return f"${value:.1f}%"
        if unit == "days": return f"${value:.0f}d"
        if unit == "x": return f"${value:,.2f}×"
        if value == int(value): return f"${int(value):,}"
        return f"${value:,.1f}"
    if isinstance(value, int): return f"${value:,}"
    return str(value)


def _kpi(label, value, unit="", hint="", delta=None, delta_up_good=True, help=""):
    return {"label": label, "value": value, "unit": unit, "hint": hint or "",
            "platform": "", "rag": None, "delta": delta,
            "delta_up_good": delta_up_good, "help": help, "deltaLabel": ""}


# ── KPI sets — matches eww-dashboard-public KPI_SETS ────────────────

_KPI_SETS = {
    "overview": ["revenue", "cash", "outstanding", "overdue", "dso", "active_customers"],
    "sales": ["revenue", "collected", "invoice_count", "avg_invoice"],
    "finance": ["cash", "outstanding", "dso", "working_capital", "current_ratio", "total_liabilities"],
    "profitability": ["pnl_income", "pnl_cogs", "pnl_gross_profit", "pnl_gross_margin",
                      "pnl_opex", "pnl_net_operating", "pnl_net_income", "pnl_net_margin"],
    "customers": ["active_customers", "total_customers", "outstanding", "overdue"],
    "accounts": ["total_assets", "total_liabilities", "equity", "cash"],
}


# ── Invoice table — matches eww-dashboard-public invoice_table ────────

def _invoice_table(invoices, limit=60):
    df = invoices.sort_values(["TxnDate", "DocNumber"], ascending=[False, True]).head(limit)
    if df.empty:
        return "<div class='chart-empty'>No invoices in this range</div>"
    rows = []
    for _, r in df.iterrows():
        status = ('<span class="badge red">Overdue</span>' if r["Overdue"]
                  else '<span class="badge green">Paid</span>' if r["Balance"] <= 0
                  else '<span class="badge">Open</span>')
        rows.append(
            f"<tr><td>{r['DocNumber']}</td><td>{r['TxnDate'].date().isoformat()}</td>"
            f"<td>{r['DueDate'].date().isoformat() if pd.notna(r['DueDate']) else '—'}</td>"
            f"<td>{r['CustomerName'] or '—'}</td><td>{r['City']}</td>"
            f"<td class='num'>{_money(r['Revenue'])}</td>"
            f"<td class='num'>{_money(r['RevenueBalance'])}</td><td>{status}</td></tr>"
        )
    header = "<tr><th>Doc #</th><th>Txn date</th><th>Due date</th><th>Customer</th><th>City</th><th class='num'>Revenue</th><th class='num'>Balance</th><th>Status</th></tr>"
    return f"<div class='tbl-wrap'><table class='data'><thead>{header}</thead><tbody>{''.join(rows)}</tbody></table></div>"


# ── Customer table — matches eww-dashboard-public customer_table ─────

def _customer_table(ds, invoices):
    billed = invoices.groupby("CustomerId")["Revenue"].sum().rename("Billed")
    c = ds.customers.merge(billed, left_on="Id", right_index=True, how="left")
    c["Billed"] = c["Billed"].fillna(0.0)
    c = c.sort_values("Billed", ascending=False)
    if c.empty:
        return "<div class='chart-empty'>No customer data</div>"
    rows = []
    for _, r in c.iterrows():
        rows.append(
            f"<tr><td>{r['CustomerName'] or '—'}</td><td>{r['City']}</td><td>{r['State']}</td>"
            f"<td><span class='badge green'>Active</span></td>"
            f"<td class='num'>{_money(r['Billed'])}</td><td class='num'>{_money(r['Balance'])}</td></tr>"
        )
    header = "<tr><th>Customer</th><th>City</th><th>State</th><th>Status</th><th class='num'>Billed (window)</th><th class='num'>Acct. balance</th></tr>"
    return f"<div class='tbl-wrap'><table class='data'><thead>{header}</thead><tbody>{''.join(rows)}</tbody></table></div>"


# ── Account table — matches eww-dashboard-public account_table ───────

def _account_table(ds, limit=90):
    a = QB.balance_sheet_accounts(ds.accounts).head(limit)
    if a.empty:
        return "<div class='chart-empty'>No balance-sheet accounts</div>"
    rows = []
    for _, r in a.iterrows():
        rows.append(
            f"<tr><td>{r['FullyQualifiedName']}</td><td>{r['Classification']}</td>"
            f"<td>{r['AccountType']}</td><td class='num'>{_money(r['CurrentBalance'])}</td></tr>"
        )
    header = "<tr><th>Account</th><th>Classification</th><th>Type</th><th class='num'>Current balance</th></tr>"
    return f"<div class='tbl-wrap'><table class='data'><thead>{header}</thead><tbody>{''.join(rows)}</tbody></table></div>"


# ── P&L statement — matches eww-dashboard-public pnl_statement ──────

def _pnl_statement(summary):
    if not summary or summary.get("income", 0) == 0:
        return "<div class='chart-empty'>No P&L data for this range</div>"
    s = summary
    lines = [
        ("Income", s["income"], False),
        ("COGS", -s["cogs"], False),
        ("Gross Profit", s["income"] - s["cogs"], True),
        ("Operating Expenses", -s["expenses"], False),
        ("Net Operating Income", s["income"] - s["cogs"] - s["expenses"], True),
        ("Other Income", s.get("other_income", 0), False),
        ("Other Expenses", -s.get("other_expenses", 0), False),
        ("Net Income", s["net_income"], True),
    ]
    rows = []
    for label, amount, is_total in lines:
        bold = " style='font-weight:700'" if is_total else ""
        cls = "num" if is_total else "num"
        border = " style='border-top:1px solid var(--border)'" if is_total and label != "Gross Profit" else ""
        rows.append(
            f"<tr{border}><td{bold}>{label}</td><td class='{cls}'{bold}>{_abbrev_money(amount)}</td></tr>"
        )
    return f"<div class='tbl-wrap'><table class='data'><thead><tr><th>Line Item</th><th class='num'>Amount</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


# ── Section handlers — matches eww-dashboard-public section structure ─

def _section_overview(ds, invoices, start, end, basis, metric):
    kpis_all = QB.compute_kpis(ds, invoices, start, end)
    kpis = []
    for k in _KPI_SETS["overview"]:
        if k in kpis_all:
            kp = kpis_all[k]
            kpis.append(_kpi(kp.label, _fmt_val(kp.value, kp.unit), kp.unit, kp.hint))

    charts = {}
    if not invoices.empty:
        charts["revenue-trend"] = {"html": QBC.trend(invoices, metric),
                                   "title": "Monthly Revenue Trend",
                                   "help": "Monthly revenue with completed months (filled) and current month (open circle)"}
        charts["top-customers"] = {"html": QBC.top_customers(invoices),
                                   "title": "Top Customers",
                                   "help": "Top 8 customers by billed revenue in the selected period"}
        charts["revenue-by-class"] = {"html": QBC.revenue_by_class(invoices),
                                      "title": "Revenue by Segment",
                                      "help": "Revenue distribution across business segments (Field, Corporate, etc.)"}
        charts["ar-aging"] = {"html": QBC.ar_aging(invoices),
                              "title": "A/R Aging",
                              "help": "Accounts receivable broken down by days past due"}

    # Invoice detail table (reference: overview section)
    charts["invoices"] = {"html": _invoice_table(invoices),
                          "title": "Recent Invoices",
                          "help": "Most recent invoices in the selected period — sort by date"}

    return kpis, charts


def _section_sales(ds, invoices, start, end, basis, metric):
    kpis_all = QB.compute_kpis(ds, invoices, start, end)
    kpis = []
    for k in _KPI_SETS["sales"]:
        if k in kpis_all:
            kp = kpis_all[k]
            kpis.append(_kpi(kp.label, _fmt_val(kp.value, kp.unit), kp.unit, kp.hint))

    charts = {}
    if not invoices.empty:
        charts["revenue-trend"] = {"html": QBC.trend(invoices, metric),
                                   "title": "Monthly Revenue",
                                   "help": "Monthly billed revenue trend"}
        charts["revenue-by-item"] = {"html": QBC.revenue_by_item(invoices),
                                     "title": "Revenue by Service/Product",
                                     "help": "Revenue breakdown by line item — which services/products drive billing"}
        charts["top-customers"] = {"html": QBC.top_customers(invoices),
                                   "title": "Top Customers",
                                   "help": "Highest-billed customers in the selected period"}
        charts["invoices"] = {"html": _invoice_table(invoices),
                              "title": "Invoice Detail",
                              "help": "Individual invoices with status — Paid, Open, or Overdue"}

    return kpis, charts


def _section_finance(ds, invoices, start, end, basis, metric):
    kpis_all = QB.compute_kpis(ds, invoices, start, end)
    kpis = []
    for k in _KPI_SETS["finance"]:
        if k in kpis_all:
            kp = kpis_all[k]
            kpis.append(_kpi(kp.label, _fmt_val(kp.value, kp.unit), kp.unit, kp.hint))

    charts = {}
    if not ds.accounts.empty:
        charts["balance-sheet"] = {"html": QBC.balance_sheet(ds.accounts),
                                   "title": "Balance Sheet",
                                   "help": "Assets, liabilities, and equity — current GL snapshot"}
        charts["accounts-by-type"] = {"html": QBC.accounts_by_type(ds.accounts),
                                      "title": "Assets by Type",
                                      "help": "Account balances grouped by account type (bank, AR, fixed assets, etc.)"}
    if not invoices.empty:
        charts["ar-aging"] = {"html": QBC.ar_aging(invoices),
                              "title": "A/R Aging",
                              "help": "Open receivables broken down by days past due"}
        charts["balance-status"] = {"html": QBC.balance_status(invoices),
                                    "title": "Invoice Balance Status",
                                    "help": "Paid, open, and overdue invoice balances"}
        charts["dso-trend"] = {"html": QBC.dso_trend(invoices, start, end),
                               "title": "Monthly DSO Trend",
                               "help": "Days Sales Outstanding per month — lower is better"}

    return kpis, charts


def _section_profitability(ds, invoices, start, end, basis, metric):
    pnl_sum = QB.pnl_summary(ds.pnl, basis, start, end)
    kpis_all = QB.pnl_kpis(ds, basis, start, end)
    kpis = []
    for k in _KPI_SETS["profitability"]:
        if k in kpis_all:
            kp = kpis_all[k]
            kpis.append(_kpi(kp.label, _fmt_val(kp.value, kp.unit), kp.unit, kp.hint))

    charts = {}
    if pnl_sum.get("income", 0):
        charts["pnl-waterfall"] = {"html": QBC.pnl_waterfall(pnl_sum),
                                   "title": "P&L Waterfall",
                                   "help": "Income → COGS → Gross Profit → OpEx → Net Income flow"}
        charts["pnl-statement"] = {"html": _pnl_statement(pnl_sum),
                                   "title": "Income Statement",
                                   "help": "Profit & Loss line items for the selected period"}
    if not ds.pnl.empty:
        charts["pnl-trend"] = {"html": QBC.pnl_trend(ds.pnl, basis),
                               "title": f"Monthly P&L Trend ({basis})",
                               "help": "Monthly income vs cost with net income overlay"}
    if not ds.pnl_detail.empty:
        charts["pnl-expenses"] = {"html": QBC.pnl_expenses(ds.pnl_detail, basis, start, end),
                                  "title": "Top Expenses",
                                  "help": "Highest expense accounts in the selected period"}

    return kpis, charts


def _section_customers(ds, invoices, start, end, basis, metric):
    kpis_all = QB.compute_kpis(ds, invoices, start, end)
    kpis = []
    for k in _KPI_SETS["customers"]:
        if k in kpis_all:
            kp = kpis_all[k]
            kpis.append(_kpi(kp.label, _fmt_val(kp.value, kp.unit), kp.unit, kp.hint))

    charts = {}
    if not invoices.empty:
        charts["top-customers"] = {"html": QBC.top_customers(invoices),
                                   "title": "Top Customers",
                                   "help": "Highest-billed customers in the selected period"}
        charts["revenue-by-city"] = {"html": QBC.revenue_by_city(invoices),
                                     "title": "Revenue by Region",
                                     "help": "Geographic distribution of billed revenue"}
        charts["customers"] = {"html": _customer_table(ds, invoices),
                               "title": "Customer Detail",
                               "help": "Full customer list with billed amounts and account balances"}

    return kpis, charts


def _section_accounts(ds, invoices, start, end, basis, metric):
    kpis_all = QB.compute_kpis(ds, invoices, start, end)
    kpis = []
    for k in _KPI_SETS["accounts"]:
        if k in kpis_all:
            kp = kpis_all[k]
            kpis.append(_kpi(kp.label, _fmt_val(kp.value, kp.unit), kp.unit, kp.hint))

    charts = {}
    if not ds.accounts.empty:
        charts["accounts-by-type"] = {"html": QBC.accounts_by_type(ds.accounts),
                                      "title": "Balances by Type",
                                      "help": "Account balances grouped by account type"}
        charts["balance-sheet"] = {"html": QBC.balance_sheet(ds.accounts),
                                   "title": "Balance Sheet",
                                   "help": "Assets, liabilities, and equity — current GL snapshot"}
        charts["accounts"] = {"html": _account_table(ds),
                              "title": "Chart of Accounts",
                              "help": "Full account listing with current balances"}
    return kpis, charts


_SECTION_HANDLERS = {
    "overview": _section_overview, "sales": _section_sales,
    "finance": _section_finance, "profitability": _section_profitability,
    "customers": _section_customers, "accounts": _section_accounts,
}


# ── CSV export — raw normalized table for the current section ──────

def _export_dataframe(section: str, ds, invoices) -> pd.DataFrame:
    """Return the raw DataFrame (normalized Postgres table) to export for a section."""
    if section == "customers":
        df = ds.customers.copy()
        if not invoices.empty:
            billed = invoices.groupby("CustomerId")["Revenue"].sum().rename("Billed")
            df = df.merge(billed, left_on="Id", right_index=True, how="left")
            df["Billed"] = df["Billed"].fillna(0.0)
        return df
    if section == "accounts":
        return ds.accounts
    # overview / sales / finance / profitability -> invoices
    return invoices


@router.get("/_api/qb/{section}")
def qb_section(
    section: str,
    basis: str = Query("accrual"),
    range: str = Query("all"),
    metric: str = Query("revenue"),
    format: str = Query(""),
):
    now_iso = datetime.now(_HOUSTON).isoformat()
    ds = cached("qb", QB.qb_load_dataset)
    if not ds:
        if format == "csv":
            return to_csv_response(pd.DataFrame(), filename="quickbooks_empty.csv")
        return {"kpis": [], "charts": {}, "loaded_at": now_iso, "section": section, "error": "No QuickBooks data"}

    start, end = resolve_date_range(range)
    invoices = QB.filter_invoices(ds.invoices, start, end)

    if format == "csv":
        return to_csv_response(
            _export_dataframe(section, ds, invoices),
            filename=f"quickbooks_{section}_{range}.csv",
        )

    handler = _SECTION_HANDLERS.get(section)
    if handler is None:
        return {"kpis": [], "charts": {}, "loaded_at": now_iso, "error": f"Unknown section: {section}"}

    kpis, charts = handler(ds, invoices, start, end, basis, metric)

    # Filter out zero/null-data KPIs and charts
    kpis = [k for k in kpis if str(k.get("value", "")).strip() not in ("$0", "0", "0d", "—", "0.0%", "$0.00", "") and k.get("value") != 0 and k.get("value") != 0.0]
    charts = {k: v for k, v in charts.items() if "chart-empty" not in str(v.get("html", ""))}

    return {
        "kpis": kpis, "charts": charts,
        "loaded_at": now_iso,
        "section": section, "basis": basis, "range": range,
        "range_info": f"{range.upper()} · {start.strftime('%b %d')} – {end.strftime('%b %d, %Y')}",
    }
