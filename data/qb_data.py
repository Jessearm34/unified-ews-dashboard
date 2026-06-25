"""Data loading and aggregation for the QuickBooks executive dashboard.

All numbers come from the real export files under ``output/``. Nothing is
synthesised. Panels that the QuickBooks accounting export cannot back
(production, HSE, etc. from the design mock) are simply not rendered.
"""

from __future__ import annotations

import ast
import os
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from typing import Any

import pandas as pd
from sqlalchemy import create_engine


def qb_get_db_url():
    url = os.getenv("QB_DATABASE_URL")
    if url:
        # Standardize Railway/Cloud URLs for SQLAlchemy
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg2://", 1)
        return url
    # Fallback: local dev (also used as the default when deploying to Railway)
    return "postgresql+psycopg2://ews:ews_local_dev@localhost:5432/warehouse"


DATABASE_URL = qb_get_db_url()


@lru_cache(maxsize=1)
def qb_engine():
    # added pool_recycle to ensure connections are refreshed before DB timeouts
    return create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)


def qb_read_table(table: str) -> pd.DataFrame:
    """Read a raw landing table from the warehouse (all columns as text)."""
    try:
        return pd.read_sql(f'SELECT * FROM {table}', qb_engine())
    except Exception as exc:  # surface a clear, actionable message
        raise RuntimeError(
            f"Could not read '{table}' from the warehouse at {DATABASE_URL}. "
            f"Is the database running? Try: docker start ews-warehouse, then "
            f"python database/ingest.py. Original error: {exc}"
        ) from exc

# Global cache to prevent re-processing all data on every HTMX request.
_DATASET_CACHE: QbDataset | None = None
_CACHE_TIMESTAMP: float = 0
_CACHE_TTL = 300  # 5 minutes


def safe_literal_eval(value: object) -> Any:
    """Parse the stringified Python dicts/lists QuickBooks exports embed in cells."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text


def get_nested(value: object, *keys: str, default=None) -> Any:
    data = safe_literal_eval(value)
    for key in keys:
        if isinstance(data, dict) and key in data:
            data = data[key]
        else:
            return default
    return data


def _count_sales_lines(raw_value: object) -> int:
    data = safe_literal_eval(raw_value)
    if isinstance(data, list):
        return sum(
            1
            for item in data
            if isinstance(item, dict) and item.get("DetailType") == "SalesItemLineDetail"
        )
    return 0


@dataclass
class QbDataset:
    invoices: pd.DataFrame
    customers: pd.DataFrame
    accounts: pd.DataFrame
    pnl: pd.DataFrame = field(default_factory=pd.DataFrame)
    pnl_detail: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def min_date(self) -> date:
        return self.invoices["TxnDate"].min().date()

    @property
    def max_date(self) -> date:
        return self.invoices["TxnDate"].max().date()


def qb_load_customers() -> pd.DataFrame:
    df = qb_read_table("quickbooks_customers")
    # Handle Balance
    if "Balance" in df.columns:
        df["Balance"] = pd.to_numeric(df["Balance"], errors="coerce").fillna(0.0)
    else:
        df["Balance"] = 0.0
    # Handle Active
    if "Active" in df.columns:
        df["Active"] = df["Active"].map({"True": True, "False": False}).fillna(False)
    else:
        df["Active"] = False
    # Handle CustomerName
    if "DisplayName" in df.columns:
        df["CustomerName"] = df["DisplayName"]
        if "CompanyName" in df.columns:
            df["CustomerName"] = df["CustomerName"].fillna(df["CompanyName"])
        if "FullyQualifiedName" in df.columns:
            df["CustomerName"] = df["CustomerName"].fillna(df["FullyQualifiedName"])
        df["CustomerName"] = df["CustomerName"].fillna("Unknown")
    elif "CompanyName" in df.columns:
        df["CustomerName"] = df["CompanyName"]
        if "FullyQualifiedName" in df.columns:
            df["CustomerName"] = df["CustomerName"].fillna(df["FullyQualifiedName"])
        df["CustomerName"] = df["CustomerName"].fillna("Unknown")
    else:
        df["CustomerName"] = "Unknown"
    # Handle City and State
    if "BillAddr" in df.columns:
        df["City"] = df["BillAddr"].apply(lambda x: get_nested(x, "City"))
        df["State"] = df["BillAddr"].apply(lambda x: get_nested(x, "CountrySubDivisionCode"))
    else:
        df["City"] = "Unknown"
        df["State"] = "Unknown"
    df["City"] = df["City"].fillna("Unknown").replace("", "Unknown")
    df["State"] = df["State"].fillna("Unknown").replace("", "Unknown")
    return df


def qb_load_accounts() -> pd.DataFrame:
    df = qb_read_table("quickbooks_accounts")
    # Handle CurrentBalance
    if "CurrentBalance" in df.columns:
        df["CurrentBalance"] = pd.to_numeric(df["CurrentBalance"], errors="coerce").fillna(0.0)
    else:
        df["CurrentBalance"] = 0.0
    # Handle CurrentBalanceWithSubAccounts
    if "CurrentBalanceWithSubAccounts" in df.columns:
        df["CurrentBalanceWithSubAccounts"] = pd.to_numeric(
            df["CurrentBalanceWithSubAccounts"], errors="coerce"
        ).fillna(0.0)
    else:
        df["CurrentBalanceWithSubAccounts"] = 0.0
    # Handle Active
    if "Active" in df.columns:
        df["Active"] = df["Active"].map({"True": True, "False": False}).fillna(False)
    else:
        df["Active"] = False
    return df


def qb_load_invoices(customers: pd.DataFrame) -> pd.DataFrame:
    df = qb_read_table("quickbooks_invoices")
    # Handle TxnDate
    if "TxnDate" in df.columns:
        df["TxnDate"] = pd.to_datetime(df["TxnDate"], errors="coerce")
    else:
        df["TxnDate"] = pd.NaT
    # Handle DueDate
    if "DueDate" in df.columns:
        df["DueDate"] = pd.to_datetime(df["DueDate"], errors="coerce")
    else:
        df["DueDate"] = pd.NaT
    # Handle TotalAmt
    if "TotalAmt" in df.columns:
        df["TotalAmt"] = pd.to_numeric(df["TotalAmt"], errors="coerce").fillna(0.0)
    else:
        df["TotalAmt"] = 0.0
    # Handle Balance
    if "Balance" in df.columns:
        df["Balance"] = pd.to_numeric(df["Balance"], errors="coerce").fillna(0.0)
    else:
        df["Balance"] = 0.0
    # Handle CustomerRef
    if "CustomerRef" in df.columns:
        df["CustomerId"] = df["CustomerRef"].apply(lambda x: get_nested(x, "value"))
        df["CustomerName"] = df["CustomerRef"].apply(
            lambda x: get_nested(x, "name") or get_nested(x, "value")
        )
    else:
        df["CustomerId"] = None
        df["CustomerName"] = "Unknown"
    # Compute Overdue
    df["Overdue"] = (df["Balance"] > 0) & (df["DueDate"] < pd.Timestamp(date.today()))
    # Handle Month
    if "TxnDate" in df.columns and not df["TxnDate"].isna().all():
        df["Month"] = df["TxnDate"].dt.to_period("M").dt.to_timestamp()
    else:
        df["Month"] = pd.NaT
    # Handle Line
    if "Line" in df.columns:
        df["LineItemCount"] = df["Line"].apply(_count_sales_lines)
    else:
        df["LineItemCount"] = 0

    # Join customer location so invoices can be aggregated by region/city.
    if not customers.empty and "Id" in customers.columns and "CustomerId" in df.columns:
        loc = customers[["Id", "City", "State"]].rename(columns={"Id": "CustomerId"})
        df = df.merge(loc, on="CustomerId", how="left")
    if "City" in df.columns:
        df["City"] = df["City"].fillna("Unknown").replace("", "Unknown")
    else:
        df["City"] = "Unknown"
    if "State" in df.columns:
        df["State"] = df["State"].fillna("Unknown").replace("", "Unknown")
    else:
        df["State"] = "Unknown"
    df["SalesClass"] = df["Line"].apply(lambda value: _extract_class_name(value))
    df["SalesItem"] = df["Line"].apply(lambda value: _extract_item_name(value))

    # Calculate recognized revenue and associated balance (excluding deposits/liabilities)
    df["Revenue"] = df["Line"].apply(_calculate_invoice_revenue)
    # Adjust the open balance to only reflect the recognized revenue portion.
    # RevenueBalance = Balance - (TotalAmt - Revenue), capped at 0 and at the Revenue amount.
    def _calc_rev_bal(row):
        deposit_amt = max(row["TotalAmt"] - row["Revenue"], 0.0)
        rev_bal = max(row["Balance"] - deposit_amt, 0.0)
        return min(rev_bal, row["Revenue"])

    df["RevenueBalance"] = df.apply(_calc_rev_bal, axis=1)

    # Return after dropna
    if "TxnDate" in df.columns and not df["TxnDate"].isna().all():
        return df.dropna(subset=["TxnDate"])
    return df


@lru_cache(maxsize=1024)
def _is_deferred_text(text: str) -> bool:
    """Cache the keyword check results to avoid repeated string ops."""
    deferred_keywords = ["deposit", "prepaid", "unearned", "deferred", "retainer", "advance", "down payment"]
    return any(k in text for k in deferred_keywords)


def _is_deferred_line(item: dict) -> bool:
    """Check if a line item represents deferred revenue/deposits."""
    detail = item.get("SalesItemLineDetail") or {}
    item_name = str(get_nested(detail, "ItemRef", "name") or "")
    acc_name = str(get_nested(detail, "ItemAccountRef", "name") or "")
    desc = str(item.get("Description") or "")
    search_text = f"{item_name} {acc_name} {desc}".lower()
    return _is_deferred_text(search_text)


def _calculate_invoice_revenue(line_json: object) -> float:
    """Sum only revenue-generating lines, excluding liability items like deposits or retainers."""
    line_items = safe_literal_eval(line_json)
    if not isinstance(line_items, list):
        return 0.0
    total = 0.0
    for item in line_items:
        if not isinstance(item, dict):
            continue
        # Include standard sales lines and discounts, but filter out the liability items
        if item.get("DetailType") in ("SalesItemLineDetail", "DiscountLineDetail"):
            if not _is_deferred_line(item):
                total += float(item.get("Amount", 0) or 0)
        elif item.get("DetailType") == "GroupLineDetail":
            # Recurse into groups/bundles
            group_detail = item.get("GroupLineDetail") or {}
            group_lines = group_detail.get("Line") or []
            total += _calculate_invoice_revenue(group_lines)
            
    return total


def _extract_item_name(raw_value: object) -> str:
    """Return the first sales item name found in the invoice Line detail."""
    line_items = safe_literal_eval(raw_value)
    if isinstance(line_items, list):
        for item in line_items:
            if isinstance(item, dict) and item.get("DetailType") == "SalesItemLineDetail":
                return get_nested(item, "SalesItemLineDetail", "ItemRef", "name") or "Unknown"
    return "Unknown"


def _extract_class_name(raw_value: object) -> str:
    line_items = safe_literal_eval(raw_value)
    if isinstance(line_items, list):
        for item in line_items:
            if isinstance(item, dict) and item.get("DetailType") == "SalesItemLineDetail":
                return get_nested(item, "SalesItemLineDetail", "ClassRef", "name") or "Unknown"
    return "Unknown"


def invoice_line_items(invoices: pd.DataFrame) -> pd.DataFrame:
    """Expand invoice line details into a flat line-item table."""
    rows: list[dict[str, Any]] = []
    for _, invoice in invoices.iterrows():
        line_items = safe_literal_eval(invoice.get("Line"))
        if not isinstance(line_items, list):
            continue

        def _process_lines(items: list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("DetailType") == "SalesItemLineDetail":
                    if _is_deferred_line(item):
                        continue
                    detail = item.get("SalesItemLineDetail") or {}

                    rows.append({
                        "InvoiceId": invoice.get("Id"),
                        "DocNumber": invoice.get("DocNumber"),
                        "TxnDate": invoice.get("TxnDate"),
                        "CustomerName": invoice.get("CustomerName"),
                        "ItemName": get_nested(detail, "ItemRef", "name") or "Unknown",
                        "ClassName": get_nested(detail, "ClassRef", "name") or "Unknown",
                        "Amount": float(item.get("Amount", 0) or 0),
                        "Qty": float(detail.get("Qty", 0) or 0),
                        "UnitPrice": float(detail.get("UnitPrice", 0) or 0),
                    })
                elif item.get("DetailType") == "GroupLineDetail":
                    group_detail = item.get("GroupLineDetail") or {}
                    group_lines = group_detail.get("Line") or []
                    _process_lines(group_lines)

        _process_lines(line_items)

    return pd.DataFrame(rows)


def qb_load_pnl() -> pd.DataFrame:
    """Section totals per month/basis from the ProfitAndLoss report.

    Returns empty (not an error) if the P&L tables haven't been ingested yet —
    they appear after the first refresh that includes the report pull.
    """
    cols = ["basis", "month", "section", "amount"]
    try:
        df = qb_read_table("quickbooks_pnl")
    except RuntimeError:
        return pd.DataFrame(columns=cols)
    df["amount"] = pd.to_numeric(df.get("amount"), errors="coerce").fillna(0.0)
    df["month"] = pd.to_datetime(df.get("month"), errors="coerce")
    df["basis"] = df.get("basis", "").astype(str)
    df["section"] = df.get("section", "").astype(str)
    return df.dropna(subset=["month"])


def qb_load_pnl_detail() -> pd.DataFrame:
    cols = ["basis", "month", "section", "account", "amount"]
    try:
        df = qb_read_table("quickbooks_pnl_detail")
    except RuntimeError:
        return pd.DataFrame(columns=cols)
    df["amount"] = pd.to_numeric(df.get("amount"), errors="coerce").fillna(0.0)
    df["month"] = pd.to_datetime(df.get("month"), errors="coerce")
    for c in ("basis", "section", "account"):
        df[c] = df.get(c, "").astype(str)
    return df.dropna(subset=["month"])


def qb_load_dataset() -> QbDataset:
    global _DATASET_CACHE, _CACHE_TIMESTAMP
    now = time.time()
    
    # Return cached dataset if valid
    if _DATASET_CACHE and (now - _CACHE_TIMESTAMP < _CACHE_TTL):
        return _DATASET_CACHE

    customers = qb_load_customers()
    accounts = qb_load_accounts()
    invoices = qb_load_invoices(customers)
    ds = QbDataset(invoices=invoices, customers=customers, accounts=accounts,
                   pnl=qb_load_pnl(), pnl_detail=qb_load_pnl_detail())
                   
    _DATASET_CACHE = ds
    _CACHE_TIMESTAMP = now
    return ds


# --------------------------------------------------------------------------- #
# Time-range resolution
# --------------------------------------------------------------------------- #

RANGE_PRESETS = [
    ("all", "All time"),
    ("ytd", "Year to date"),
    ("30d", "Last 30 days"),
    ("90d", "Last 90 days"),
    ("12m", "Last 12 months"),
    ("custom", "Custom"),
]


def resolve_range(
    ds: QbDataset,
    range_key: str,
    start: str | None,
    end: str | None,
) -> tuple[date, date, str]:
    """Return (start_date, end_date, label) for the requested preset."""
    today = date.today()
    data_min, data_max = ds.min_date, ds.max_date

    if range_key == "ytd":
        return date(today.year, 1, 1), today, f"Year to date ({today.year})"
    if range_key == "30d":
        return today - timedelta(days=30), today, "Last 30 days"
    if range_key == "90d":
        return today - timedelta(days=90), today, "Last 90 days"
    if range_key == "12m":
        return today - timedelta(days=365), today, "Last 12 months"
    if range_key == "custom":
        try:
            s = date.fromisoformat(start) if start else data_min
        except ValueError:
            s = data_min
        try:
            e = date.fromisoformat(end) if end else data_max
        except ValueError:
            e = data_max
        if e < s:
            s, e = e, s
        return s, e, f"{s.isoformat()} → {e.isoformat()}"
    # default: all time
    return data_min, data_max, "All time"


def filter_invoices(invoices: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """Return invoices with TxnDate in [start, end]."""
    mask = (invoices["TxnDate"].dt.date >= start) & (invoices["TxnDate"].dt.date <= end)
    return invoices[mask]


# --------------------------------------------------------------------------- #
# KPI & metrics
# --------------------------------------------------------------------------- #

@dataclass
class Kpi:
    key: str
    label: str
    value: float
    delta: float | None = None
    unit: str = ""
    delta_good_when_up: bool = True
    chartable: bool = False  # True if clicking the card charts a monthly trend
    hint: str = ""           # sub-label shown under the value


TREND_SPECS = {
    "revenue": ("Monthly Revenue", "currency", "Revenue ($)", "#2563eb"),
    "invoice_count": ("Monthly Invoice Count", "count", "Invoices", "#16a34a"),
    "avg_invoice": ("Avg Invoice Amount", "currency", "Avg ($)", "#0e7490"),
}


def trend_series(invoices: pd.DataFrame, metric: str) -> pd.DataFrame:
    """Aggregate invoices by month for trend charting.
    
    Returns DataFrame with columns [Month, value] where value is:
      - "revenue": Total TotalAmt per month
      - "invoice_count": Count of invoices per month
      - "avg_invoice": Average TotalAmt per month
    """
    if invoices.empty or "Month" not in invoices.columns:
        return pd.DataFrame(columns=["Month", "value"])
    
    invoices_with_month = invoices.dropna(subset=["Month"])
    if invoices_with_month.empty:
        return pd.DataFrame(columns=["Month", "value"])
    
    if metric == "revenue":
        result = invoices_with_month.groupby("Month")["Revenue"].sum().reset_index()
        result.columns = ["Month", "value"]
    elif metric == "invoice_count":
        result = invoices_with_month.groupby("Month").size().reset_index(name="value")
        result["Month"] = invoices_with_month.groupby("Month")["Month"].first().reset_index()["Month"]
    elif metric == "avg_invoice":
        result = invoices_with_month.groupby("Month")["Revenue"].mean().reset_index()
        result.columns = ["Month", "value"]
    else:
        return pd.DataFrame(columns=["Month", "value"])
    
    return result.sort_values("Month").reset_index(drop=True)


# --- AR aging --------------------------------------------------------------- #

AGING_BUCKETS = [
    ("Current", 0, "#16a34a"),       # not yet due
    ("1–30", 30, "#65a30d"),
    ("31–60", 60, "#ca8a04"),
    ("61–90", 90, "#ea580c"),
    ("90+", 10**9, "#dc2626"),       # severely overdue
]


def ar_aging(invoices: pd.DataFrame) -> pd.DataFrame:
    """Bucket open receivables by days past due, anchored to today.

    Returns columns [Bucket, Amount, Count, Color]. Invoices not yet due land
    in "Current"; the rest are aged by how far past DueDate they are.
    """
    cols = ["Bucket", "Amount", "Count", "Color"]
    if invoices.empty:
        return pd.DataFrame(columns=cols)
    open_inv = invoices[invoices["RevenueBalance"] > 0].copy()
    if open_inv.empty:
        return pd.DataFrame(columns=cols)
    today = pd.Timestamp(date.today())
    days_past = (today - open_inv["DueDate"]).dt.days
    rows = []
    prev = -(10**9)
    for label, upper, color in AGING_BUCKETS:
        if label == "Current":
            mask = open_inv["DueDate"].isna() | (days_past <= 0)
        else:
            mask = (days_past > prev) & (days_past <= upper)
            prev = upper
        bucket = open_inv[mask]
        rows.append({
            "Bucket": label,
            "Amount": float(bucket["RevenueBalance"].sum()),
            "Count": int(len(bucket)),
            "Color": color,
        })
    return pd.DataFrame(rows, columns=cols)


def compute_dso(invoices: pd.DataFrame, start: date, end: date) -> float | None:
    """Days Sales Outstanding for the window: AR / (revenue / window days)."""
    if invoices.empty:
        return None
    revenue = invoices["Revenue"].sum()
    if revenue <= 0:
        return None
    ar = invoices.loc[invoices["RevenueBalance"] > 0, "RevenueBalance"].sum()
    window_days = max((end - start).days + 1, 1)
    daily_revenue = revenue / window_days
    if daily_revenue <= 0:
        return None
    return ar / daily_revenue


# --- Balance sheet (point-in-time GL snapshot) ------------------------------ #

# AccountType groupings used to read the current GL snapshot. Liabilities and
# equity are stored as negative CurrentBalance in the QuickBooks export, so we
# take magnitudes for display.
_CURRENT_ASSET_TYPES = {"Bank", "Accounts Receivable", "Other Current Asset"}
_CURRENT_LIAB_TYPES = {"Accounts Payable", "Credit Card", "Other Current Liability"}


def balance_sheet_summary(accounts: pd.DataFrame) -> dict[str, float]:
    """Summarise the current balance sheet from GL account balances.

    Income/expense accounts carry no running balance in QuickBooks, so this
    only reflects Asset/Liability/Equity accounts. Returns positive magnitudes
    suitable for display.
    """
    if accounts.empty:
        return {k: 0.0 for k in (
            "cash", "ar", "ap", "assets", "liabilities", "equity",
            "current_assets", "current_liabilities", "working_capital", "current_ratio",
        )}
    bal = accounts["CurrentBalance"]
    by_type = lambda types: float(bal[accounts["AccountType"].isin(types)].sum())
    by_class = lambda cls: float(bal[accounts["Classification"] == cls].sum())

    cash = by_type({"Bank"})
    ar = by_type({"Accounts Receivable"})
    ap = abs(by_type({"Accounts Payable"}))
    assets = by_class("Asset")
    liabilities = abs(by_class("Liability"))
    equity = abs(by_class("Equity"))
    current_assets = by_type(_CURRENT_ASSET_TYPES)
    current_liabilities = abs(by_type(_CURRENT_LIAB_TYPES))
    working_capital = current_assets - current_liabilities
    current_ratio = (current_assets / current_liabilities) if current_liabilities else 0.0
    return {
        "cash": cash, "ar": ar, "ap": ap,
        "assets": assets, "liabilities": liabilities, "equity": equity,
        "current_assets": current_assets, "current_liabilities": current_liabilities,
        "working_capital": working_capital, "current_ratio": current_ratio,
    }


def balance_sheet_accounts(accounts: pd.DataFrame) -> pd.DataFrame:
    """Asset/Liability/Equity accounts with a non-zero balance, by magnitude."""
    if accounts.empty:
        return accounts
    bs = accounts[accounts["Classification"].isin(["Asset", "Liability", "Equity"])].copy()
    bs = bs[bs["CurrentBalance"].abs() > 0]
    return bs.reindex(bs["CurrentBalance"].abs().sort_values(ascending=False).index)


# --- KPIs ------------------------------------------------------------------- #

def _mom_delta(invoices: pd.DataFrame, agg) -> float | None:
    """Month-over-month % change of `agg(month_df)` for the last two months."""
    if invoices.empty or "Month" not in invoices.columns:
        return None
    wm = invoices.dropna(subset=["Month"])
    if wm.empty:
        return None
    months = sorted(m for m in wm["Month"].unique() if pd.notna(m))
    if len(months) < 2:
        return None
    last = agg(wm[wm["Month"] == months[-2]])
    this = agg(wm[wm["Month"] == months[-1]])
    if not last:
        return None
    return (this - last) / last * 100


def compute_kpis(ds: "QbDataset", invoices: pd.DataFrame, start: date, end: date) -> dict[str, Kpi]:
    """Compute the full KPI catalogue. Pages pick which keys to display.

    Invoice-derived KPIs follow the selected window; balance-sheet KPIs are a
    current GL snapshot (the export carries no historical balances).
    """
    bs = balance_sheet_summary(ds.accounts)
    customers = ds.customers

    # Use P&L 'Income' for revenue if available; it's the financial source of truth 
    # and correctly excludes non-income items like deposits. Fallback to cleaned 
    # invoice revenue if P&L table isn't populated yet.
    pnl_s = pnl_summary(ds.pnl, "accrual", start, end)
    revenue = pnl_s["income"] if not ds.pnl.empty else (
        float(invoices["Revenue"].sum()) if not invoices.empty else 0.0
    )

    count = int(len(invoices))
    avg_invoice = revenue / count if count else 0.0
    open_bal = float(invoices["RevenueBalance"].sum()) if not invoices.empty else 0.0
    overdue = float(invoices.loc[invoices["Overdue"], "RevenueBalance"].sum()) if not invoices.empty else 0.0
    collected = max(revenue - open_bal, 0.0)
    collection_rate = (collected / revenue * 100) if revenue else 0.0
    dso = compute_dso(invoices, start, end)
    active_customers = int(customers["Active"].sum()) if not customers.empty else 0
    total_customers = int(len(customers))

    k = {}
    k["revenue"] = Kpi("revenue", "Revenue (window)", revenue, _mom_delta(invoices, lambda d: d["Revenue"].sum()),
                       "$", True, chartable=True, hint="Click to chart monthly")
    k["collected"] = Kpi("collected", "Collected", collected, None, "$", True,
                         hint=f"{collection_rate:.0f}% of billed")
    k["collection_rate"] = Kpi("collection_rate", "Collection Rate", collection_rate, None, "%", True,
                               hint="Billed that's been paid")
    k["invoice_count"] = Kpi("invoice_count", "Invoices", float(count),
                             _mom_delta(invoices, lambda d: float(len(d))), "", True,
                             chartable=True, hint="Click to chart monthly")
    k["avg_invoice"] = Kpi("avg_invoice", "Avg Invoice", avg_invoice,
                           _mom_delta(invoices, lambda d: d["Revenue"].mean()), "$", True,
                           chartable=True, hint="Click to chart monthly")
    k["outstanding"] = Kpi("outstanding", "Outstanding AR", open_bal, None, "$", False,
                           hint="Unpaid invoice balance")
    k["overdue"] = Kpi("overdue", "Overdue AR", overdue, None, "$", False, hint="Past due date")
    k["dso"] = Kpi("dso", "DSO", dso if dso is not None else 0.0, None, "days", False,
                   hint="Days sales outstanding")
    k["cash"] = Kpi("cash", "Cash on Hand", bs["cash"], None, "$", True, hint="Current bank balance")
    k["ar"] = Kpi("ar", "Receivables (GL)", bs["ar"], None, "$", False, hint="Current A/R balance")
    k["ap"] = Kpi("ap", "Payables (GL)", bs["ap"], None, "$", False, hint="Current A/P balance")
    k["total_assets"] = Kpi("total_assets", "Total Assets", bs["assets"], None, "$", True, hint="Current snapshot")
    k["total_liabilities"] = Kpi("total_liabilities", "Total Liabilities", bs["liabilities"], None, "$", False, hint="Current snapshot")
    k["equity"] = Kpi("equity", "Total Equity", bs["equity"], None, "$", True, hint="Current snapshot")
    k["working_capital"] = Kpi("working_capital", "Working Capital", bs["working_capital"], None, "$", True,
                               hint="Current assets − current liab.")
    k["current_ratio"] = Kpi("current_ratio", "Current Ratio", bs["current_ratio"], None, "x", True,
                             hint="Current assets ÷ liabilities")
    k["active_customers"] = Kpi("active_customers", "Active Customers", float(active_customers), None, "", True,
                                hint=f"of {total_customers} total")
    k["total_customers"] = Kpi("total_customers", "Total Customers", float(total_customers), None, "", True,
                               hint="All accounts")
    return k


# --------------------------------------------------------------------------- #
# Profit & Loss (from the ProfitAndLoss report, by basis & month)
# --------------------------------------------------------------------------- #

PNL_BASES = [("accrual", "Accrual"), ("cash", "Cash")]
# Base sections we sum directly; gross/operating/net are derived from these so
# we never depend on QuickBooks' summary-only rows.
_PNL_BASE_SECTIONS = ["Income", "COGS", "Expenses", "OtherIncome", "OtherExpenses"]
_PNL_COST_SECTIONS = ["COGS", "Expenses", "OtherExpenses"]


def pnl_window(pnl: pd.DataFrame, basis: str, start: date, end: date) -> pd.DataFrame:
    """Rows for one basis whose month falls in the selected window."""
    if pnl.empty:
        return pnl
    lo = pd.Timestamp(start).to_period("M").to_timestamp()
    hi = pd.Timestamp(end)
    mask = (
        (pnl["basis"].str.lower() == basis.lower())
        & (pnl["month"] >= lo)
        & (pnl["month"] <= hi)
    )
    return pnl[mask]


def pnl_summary(pnl: pd.DataFrame, basis: str, start: date, end: date) -> dict[str, float]:
    """Aggregate P&L sections over the window into the income-statement lines."""
    keys = ("income", "cogs", "gross_profit", "gross_margin", "expenses",
            "net_operating_income", "other_income", "other_expenses",
            "net_income", "net_margin")
    f = pnl_window(pnl, basis, start, end)
    if f.empty:
        return {key: 0.0 for key in keys}
    totals = f.groupby("section")["amount"].sum()
    income = float(totals.get("Income", 0.0))
    cogs = float(totals.get("COGS", 0.0))
    expenses = float(totals.get("Expenses", 0.0))
    other_income = float(totals.get("OtherIncome", 0.0))
    other_expenses = float(totals.get("OtherExpenses", 0.0))
    gross_profit = income - cogs
    net_operating_income = gross_profit - expenses
    net_income = net_operating_income + other_income - other_expenses
    return {
        "income": income, "cogs": cogs, "gross_profit": gross_profit,
        "gross_margin": (gross_profit / income * 100) if income else 0.0,
        "expenses": expenses, "net_operating_income": net_operating_income,
        "other_income": other_income, "other_expenses": other_expenses,
        "net_income": net_income,
        "net_margin": (net_income / income * 100) if income else 0.0,
    }


def pnl_trend(pnl: pd.DataFrame, basis: str) -> pd.DataFrame:
    """Monthly Income, total Cost, and Net Income for one basis (full history)."""
    cols = ["Month", "Income", "Cost", "NetIncome"]
    if pnl.empty:
        return pd.DataFrame(columns=cols)
    f = pnl[pnl["basis"].str.lower() == basis.lower()]
    if f.empty:
        return pd.DataFrame(columns=cols)
    piv = f.pivot_table(index="month", columns="section", values="amount",
                        aggfunc="sum", fill_value=0.0)
    for s in _PNL_BASE_SECTIONS:
        if s not in piv.columns:
            piv[s] = 0.0
    out = pd.DataFrame({"Month": piv.index})
    out["Income"] = (piv["Income"] + piv["OtherIncome"]).values
    out["Cost"] = piv[_PNL_COST_SECTIONS].sum(axis=1).values
    out["NetIncome"] = (out["Income"].values - out["Cost"].values)
    return out.sort_values("Month").reset_index(drop=True)


def pnl_expense_categories(pnl_detail: pd.DataFrame, basis: str, start: date, end: date,
                           n: int = 10) -> pd.DataFrame:
    """Top expense accounts (COGS + Expenses + Other Expenses) over the window."""
    cols = ["account", "amount"]
    if pnl_detail.empty:
        return pd.DataFrame(columns=cols)
    lo = pd.Timestamp(start).to_period("M").to_timestamp()
    hi = pd.Timestamp(end)
    mask = (
        (pnl_detail["basis"].str.lower() == basis.lower())
        & (pnl_detail["section"].isin(_PNL_COST_SECTIONS))
        & (pnl_detail["month"] >= lo)
        & (pnl_detail["month"] <= hi)
    )
    f = pnl_detail[mask]
    if f.empty:
        return pd.DataFrame(columns=cols)
    g = (f.groupby("account", as_index=False)["amount"].sum()
         .sort_values("amount", ascending=False).head(n))
    return g.reset_index(drop=True)


def pnl_kpis(ds: "QbDataset", basis: str, start: date, end: date) -> dict[str, Kpi]:
    """P&L headline KPIs for the Profitability page (window + basis)."""
    s = pnl_summary(ds.pnl, basis, start, end)
    return {
        "pnl_income": Kpi("pnl_income", "Income", s["income"], None, "$", True, hint="Revenue per books"),
        "pnl_cogs": Kpi("pnl_cogs", "Cost of Goods Sold", s["cogs"], None, "$", False, hint="Direct costs"),
        "pnl_gross_profit": Kpi("pnl_gross_profit", "Gross Profit", s["gross_profit"], None, "$", True,
                                hint="Income − COGS"),
        "pnl_gross_margin": Kpi("pnl_gross_margin", "Gross Margin", s["gross_margin"], None, "%", True,
                                hint="Gross profit ÷ income"),
        "pnl_opex": Kpi("pnl_opex", "Operating Expenses", s["expenses"], None, "$", False,
                        hint="Below gross profit"),
        "pnl_net_operating": Kpi("pnl_net_operating", "Net Operating Income", s["net_operating_income"], None, "$", True,
                                 hint="Gross profit − opex"),
        "pnl_net_income": Kpi("pnl_net_income", "Net Income", s["net_income"], None, "$", True,
                              hint="Bottom line, incl. other"),
        "pnl_net_margin": Kpi("pnl_net_margin", "Net Margin", s["net_margin"], None, "%", True,
                              hint="Net income ÷ income"),
    }
