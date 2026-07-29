"""Plotly figure builders. Each returns an HTML fragment (div + init script).

Plotly.js is loaded once in the page head (see app.py), so every fragment is
emitted with ``include_plotlyjs=False``. HTMX evaluates the inline init script
when the fragment is swapped in, so charts re-render on every interaction.
"""

from __future__ import annotations

import itertools
import random

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

try:
    import data.qb_data as D
except ImportError:
    from visualize_fasthtml.data import qb_data as D

# Palette echoing the executive-dashboard mock.
ACCENT = "#2563eb"
SEQ = ["#2563eb", "#0e7490", "#7c3aed", "#16a34a", "#ea580c", "#db2777", "#0891b2", "#64748b"]

_PLOT_CONFIG = {"displayModeBar": False, "displaylogo": False, "responsive": True}
_ids = iter(lambda: f'chart-{random.randrange(10_000_000, 99_999_999)}', None)


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _layout(fig: go.Figure, height: int = 300) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        height=height,
        margin=dict(l=10, r=10, t=30, b=10),
        font=dict(family="Inter, system-ui, sans-serif", size=12, color="#0f172a"),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=fig.layout.showlegend,
        title=None,
        uniformtext=dict(minsize=9, mode="hide"),
    )
    return fig


def render(fig: go.Figure) -> str:
    return fig.to_html(
        include_plotlyjs=False,
        full_html=False,
        config=_PLOT_CONFIG,
        div_id=f"plot-{next(_ids)}",
        default_width="100%",
    )


def empty(message: str = "No data for this range") -> str:
    return f"<div class='chart-empty'>{message}</div>"


# --------------------------------------------------------------------------- #


def trend(invoices: pd.DataFrame, metric: str, compare_invoices: pd.DataFrame | None = None) -> str:
    from datetime import date as dt_date
    _, _, ylabel, color = D.TREND_SPECS[metric]
    df = D.trend_series(invoices, metric)
    if df.empty:
        return empty()
    hover_fmt = "%{y:,.2f}" if metric in ("revenue", "avg_invoice") else "%{y:,.0f}"

    today = dt_date.today()
    current_month_start = pd.Timestamp(today.replace(day=1))
    completed = df[df["Month"] < current_month_start]
    in_progress = df[df["Month"] >= current_month_start]

    fig = go.Figure()

    # Completed months: normal trace
    if not completed.empty:
        fig.add_trace(go.Scatter(
            x=completed["Month"], y=completed["value"],
            mode="lines+markers",
            line=dict(color=color, width=3, shape="spline"),
            marker=dict(size=7, color=color),
            fill="tozeroy",
            fillcolor=_rgba(color, 0.10),
            name="Completed",
            hovertemplate=f"%{{x|%b %Y}}<br>{hover_fmt}<extra></extra>",
        ))

    # Current month: open circle before 25th, connected after
    if not in_progress.empty:
        row = in_progress.iloc[0]
        if today.day < 25:
            fig.add_trace(go.Scatter(
                x=[row["Month"]], y=[row["value"]],
                mode="markers",
                marker=dict(size=9, color=color, symbol="circle-open",
                           line=dict(color=color, width=2)),
                name="Current month",
                hovertemplate=f"%{{x|%b %Y}}<br>{hover_fmt}<extra></extra>",
            ))
        else:
            all_pts = pd.concat([completed, in_progress]).sort_values("Month")
            fig.add_trace(go.Scatter(
                x=all_pts["Month"], y=all_pts["value"],
                mode="lines+markers",
                line=dict(color=color, width=3, shape="spline"),
                marker=dict(size=7, color=color),
                fill="tozeroy",
                fillcolor=_rgba(color, 0.10),
                name="Completed",
                hovertemplate=f"%{{x|%b %Y}}<br>{hover_fmt}<extra></extra>",
            ))
    # Overlay comparison (last year / previous period)
    if compare_invoices is not None and not compare_invoices.empty:
        cdf = D.trend_series(compare_invoices, metric)
        if not cdf.empty and len(cdf) > 0:
            fig.add_trace(go.Scatter(
                x=cdf["Month"], y=cdf["value"],
                mode="lines+markers",
                line=dict(color="#94a3b8", width=2, dash="dash"),
                marker=dict(size=5, color="#94a3b8"),
                name="Prev period",
                hovertemplate=f"%{{x|%b %Y}}<br>{hover_fmt}<extra></extra>",
            ))
    fig.update_layout(showlegend=compare_invoices is not None and not compare_invoices.empty,
                      legend=dict(orientation="h", y=1.1, font=dict(size=9)))
    fig.update_yaxes(title=ylabel, gridcolor="#e2e8f0")
    fig.update_xaxes(title=None, gridcolor="#f1f5f9", dtick="M1", tickformat="%b %Y")
    return render(_layout(fig, 320))


def revenue_by_city(invoices: pd.DataFrame) -> str:
    g = (
        invoices.groupby("City", as_index=False)["Revenue"]
        .sum()
        .sort_values("Revenue", ascending=True)
    )
    if g.empty or g["Revenue"].sum() == 0:
        return empty()
    total = g["Revenue"].sum()
    g["LegendLabel"] = (
        g["City"].astype(str)
        + " "
        + (g["Revenue"] / total * 100).map(lambda v: f"{v:.1f}%")
    )
    small_count = min(4, len(g))
    textpositions = ["outside" if i < small_count else "inside" for i in range(len(g))]
    fig = go.Figure(
        go.Pie(
            labels=g["LegendLabel"],
            values=g["Revenue"],
            hole=0.55,
            sort=False,
            textinfo="none",
            textposition=textpositions,
            insidetextorientation="radial",
            rotation=135,
            textfont=dict(size=10),
            automargin=True,
            marker=dict(colors=SEQ, line=dict(color="white", width=1)),
            hovertemplate="%{label}<br>$%{value:,.2f} (%{percent})<extra></extra>",
        )
    )
    fig.update_layout(
        showlegend=True,
        legend=dict(orientation="v", font=dict(size=11), x=1.25, y=0.5),
        margin=dict(l=10, r=150, t=10, b=10),
    )
    return render(_layout(fig, 300))


def top_customers(invoices: pd.DataFrame, n: int = 8) -> str:
    g = (
        invoices.groupby("CustomerName", as_index=False)["Revenue"]
        .sum()
        .sort_values("Revenue", ascending=True)
        .tail(n)
    )
    if g.empty:
        return empty()
    fig = go.Figure(
        go.Bar(
            x=g["Revenue"],
            y=g["CustomerName"],
            orientation="h",
            marker=dict(color=ACCENT),
            hovertemplate="%{y}<br>$%{x:,.2f}<extra></extra>",
        )
    )
    fig.update_layout(showlegend=False)
    fig.update_xaxes(title="Billed (USD)", gridcolor="#e2e8f0")
    fig.update_yaxes(title=None)
    return render(_layout(fig, max(260, 34 * len(g))))


def balance_status(invoices: pd.DataFrame) -> str:
    # Calculate status based on recognized revenue balance, not raw balance
    paid = (invoices["Revenue"] - invoices["RevenueBalance"]).sum()
    current = invoices.loc[(invoices["RevenueBalance"] > 0) & (~invoices["Overdue"]), "RevenueBalance"].sum()
    overdue = invoices.loc[invoices["Overdue"], "RevenueBalance"].sum()
    rows = [("Paid", paid, "#16a34a"), ("Open / current", current, ACCENT), ("Overdue", overdue, "#dc2626")]
    rows = [(lbl, val, c) for lbl, val, c in rows if val > 0]
    if not rows:
        return empty()
    fig = go.Figure(
        go.Bar(
            x=[r[0] for r in rows],
            y=[r[1] for r in rows],
            marker=dict(color=[r[2] for r in rows]),
            hovertemplate="%{x}<br>$%{y:,.2f}<extra></extra>",
        )
    )
    fig.update_layout(showlegend=False)
    fig.update_yaxes(title="USD", gridcolor="#e2e8f0")
    return render(_layout(fig, 300))


def ar_aging(invoices: pd.DataFrame) -> str:
    """Open receivables bucketed by days past due (current → 90+)."""
    g = D.ar_aging(invoices)
    if g.empty or g["Amount"].sum() == 0:
        return empty("No open receivables in this range")
    text = [f"${v/1000:,.0f}K" if v >= 1000 else f"${v:,.0f}" for v in g["Amount"]]
    fig = go.Figure(
        go.Bar(
            x=g["Bucket"],
            y=g["Amount"],
            marker=dict(
                color=g["Color"].tolist(),
                line=dict(color="white", width=1)
            ),
            text=text,
            textposition="outside",
            cliponaxis=False,
            customdata=g[["Count"]].values,
            hovertemplate="%{x} past due<br>$%{y:,.2f} · %{customdata[0]} invoices<extra></extra>",
        )
    )
    fig.update_layout(showlegend=False)
    fig.update_yaxes(title="Open balance (USD)", gridcolor="#e2e8f0")
    fig.update_xaxes(title="Days past due")
    return render(_layout(fig, 300))


def balance_sheet(accounts: pd.DataFrame) -> str:
    """Assets vs Liabilities vs Equity magnitudes (current GL snapshot)."""
    bs = D.balance_sheet_summary(accounts)
    rows = [
        ("Assets", bs["assets"], "#0e7490"),
        ("Liabilities", bs["liabilities"], "#dc2626"),
        ("Equity", bs["equity"], "#7c3aed"),
    ]
    rows = [(lbl, val, c) for lbl, val, c in rows if val > 0]
    if not rows:
        return empty("No balance-sheet data")
    text = [f"${v/1e6:,.2f}M" if v >= 1e6 else f"${v/1000:,.0f}K" for _, v, _ in rows]
    fig = go.Figure(
        go.Bar(
            x=[r[0] for r in rows],
            y=[r[1] for r in rows],
            marker=dict(
                color=[r[2] for r in rows],
                line=dict(color="white", width=1)
            ),
            text=text,
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{x}<br>$%{y:,.2f}<extra></extra>",
        )
    )
    fig.update_layout(showlegend=False)
    fig.update_yaxes(title="USD (magnitude)", gridcolor="#e2e8f0")
    return render(_layout(fig, 300))


def revenue_by_item(invoices: pd.DataFrame) -> str:
    items = D.invoice_line_items(invoices)
    if items.empty:
        return empty("No product/service revenue data")
    g = (
        items.groupby("ItemName", as_index=False)["Amount"]
        .sum()
        .sort_values("Amount", ascending=True)
        .tail(8)
    )
    if g.empty or g["Amount"].sum() == 0:
        return empty("No item revenue")
    fig = go.Figure(
        go.Bar(
            x=g["Amount"],
            y=g["ItemName"],
            orientation="h",
            marker=dict(color=SEQ[1]),
            hovertemplate="%{y}<br>$%{x:,.2f}<extra></extra>",
        )
    )
    fig.update_layout(showlegend=False)
    fig.update_xaxes(title="Revenue (USD)", gridcolor="#e2e8f0")
    fig.update_yaxes(title=None)
    return render(_layout(fig, max(260, 32 * len(g))))


def revenue_by_class(invoices: pd.DataFrame) -> str:
    items = D.invoice_line_items(invoices)
    if items.empty:
        return empty("No class/category revenue data")
    g = (
        items.groupby("ClassName", as_index=False)["Amount"]
        .sum()
        .sort_values("Amount", ascending=True)
    )
    g = g[g["Amount"] > 0]  # a pie can't represent credits/negative slices
    if g.empty or g["Amount"].sum() == 0:
        return empty("No class revenue")
    fig = go.Figure(
        go.Pie(
            labels=g["ClassName"],
            values=g["Amount"],
            hole=0.55,
            marker=dict(colors=SEQ, line=dict(color="white", width=1)),
            textinfo="label+percent",
            hovertemplate="%{label}<br>$%{value:,.2f} (%{percent})<extra></extra>",
        )
    )
    fig.update_layout(showlegend=True, legend=dict(orientation="v", x=1.15, y=0.5, font=dict(size=10)), margin=dict(l=10, r=140, t=10, b=10))
    return render(_layout(fig, 300))

def pnl_waterfall(summary: dict) -> str:
    """Income-statement waterfall: Income → COGS → Gross → OpEx → Other → Net."""
    if not summary or summary.get("income", 0) == 0:
        return empty("No P&L data for this range")
    s = summary
    x = ["Income", "COGS", "Gross Profit", "Operating Exp.", "Net Op. Income",
         "Other Income", "Other Exp.", "Net Income"]
    measure = ["relative", "relative", "total", "relative", "total",
               "relative", "relative", "total"]
    y = [s["income"], -s["cogs"], 0, -s["expenses"], 0,
         s["other_income"], -s["other_expenses"], 0]
    fig = go.Figure(
        go.Waterfall(
            x=x, measure=measure, y=y,
            connector=dict(line=dict(color="#cbd5e1")),
            increasing=dict(marker=dict(color="#16a34a")),
            decreasing=dict(marker=dict(color="#dc2626")),
            totals=dict(marker=dict(color="#2563eb")),
            hovertemplate="%{x}<br>$%{y:,.0f}<extra></extra>",
        )
    )
    fig.update_layout(showlegend=False)
    fig.update_yaxes(title="USD", gridcolor="#e2e8f0", zeroline=True, zerolinecolor="#94a3b8")
    fig.update_xaxes(tickangle=-25)
    return render(_layout(fig, 340))


def pnl_trend(pnl: pd.DataFrame, basis: str) -> str:
    """Monthly Income vs total Cost (bars) with Net Income overlaid (line)."""
    df = D.pnl_trend(pnl, basis)
    if df.empty or df["Income"].abs().sum() == 0:
        return empty("No P&L data")
    fig = go.Figure()
    fig.add_bar(x=df["Month"], y=df["Income"], name="Income", marker=dict(color="#16a34a"),
                hovertemplate="%{x|%b %Y}<br>Income $%{y:,.0f}<extra></extra>")
    fig.add_bar(x=df["Month"], y=df["Cost"], name="Cost", marker=dict(color="#f1a8a8"),
                hovertemplate="%{x|%b %Y}<br>Cost $%{y:,.0f}<extra></extra>")
    fig.add_scatter(x=df["Month"], y=df["NetIncome"], name="Net Income", mode="lines+markers",
                    line=dict(color="#2563eb", width=3), marker=dict(size=6),
                    hovertemplate="%{x|%b %Y}<br>Net $%{y:,.0f}<extra></extra>")
    fig.update_layout(barmode="group", showlegend=True,
                      legend=dict(orientation="h", y=1.12, x=0))
    fig.update_yaxes(title="USD", gridcolor="#e2e8f0", zeroline=True, zerolinecolor="#94a3b8")
    fig.update_xaxes(title=None, gridcolor="#f1f5f9", tickformat="%b %Y")
    return render(_layout(fig, 340))


def pnl_expenses(pnl_detail: pd.DataFrame, basis: str, start, end, n: int = 10) -> str:
    """Top expense accounts (COGS + operating + other) over the window."""
    g = D.pnl_expense_categories(pnl_detail, basis, start, end, n)
    if g.empty or g["amount"].sum() == 0:
        return empty("No expense detail for this range")
    g = g.sort_values("amount", ascending=True)
    fig = go.Figure(
        go.Bar(
            x=g["amount"], y=g["account"], orientation="h",
            marker=dict(color="#dc2626"),
            hovertemplate="%{y}<br>$%{x:,.0f}<extra></extra>",
        )
    )
    fig.update_layout(showlegend=False)
    fig.update_xaxes(title="Expense (USD)", gridcolor="#e2e8f0")
    fig.update_yaxes(title=None)
    return render(_layout(fig, max(280, 30 * len(g))))


def accounts_by_type(accounts: pd.DataFrame) -> str:
    g = (
        accounts.assign(absBal=accounts["CurrentBalance"].abs())
        .groupby("AccountType", as_index=False)["absBal"]
        .sum()
        .sort_values("absBal", ascending=True)
    )
    g = g[g["absBal"] > 0]
    if g.empty:
        return empty()
    fig = go.Figure(
        go.Bar(
            x=g["absBal"],
            y=g["AccountType"],
            orientation="h",
            marker=dict(color="#0e7490"),
            hovertemplate="%{y}<br>$%{x:,.2f}<extra></extra>",
        )
    )
    fig.update_layout(showlegend=False)
    fig.update_xaxes(title="Balance magnitude (USD)", gridcolor="#e2e8f0")
    fig.update_yaxes(title=None)
    return render(_layout(fig, max(260, 30 * len(g))))


# ── DSO Trend ─────────────────────────────────────────────────────


def dso_trend(invoices: pd.DataFrame, start, end) -> str:
    """Monthly DSO line chart with prior-year comparison overlay."""
    df = D.dso_trend_series(invoices, start, end)
    if df.empty:
        return empty("No DSO data for this range")
    fig = go.Figure()
    fig.add_scatter(
        x=df["Month"], y=df["DSO"], mode="lines+markers",
        line=dict(color=ACCENT, width=3), marker=dict(size=7, color=ACCENT),
        name="DSO",
        hovertemplate="%{x|%b %Y}<br>DSO: %{y:.1f} days<extra></extra>",
    )
    py = df[df["DSO_PY"].notna()]
    if not py.empty:
        fig.add_scatter(
            x=py["Month"], y=py["DSO_PY"], mode="lines+markers",
            line=dict(color=_rgba(ACCENT, 0.4), width=2, dash="dot"),
            marker=dict(size=6, color=_rgba(ACCENT, 0.4)),
            name="DSO (prior year)",
            hovertemplate="%{x|%b %Y}<br>DSO: %{y:.1f} days<extra></extra>",
        )
    fig.update_layout(showlegend=True, legend=dict(orientation="h", y=1.12, x=0))
    fig.update_yaxes(title="Days", gridcolor="#e2e8f0")
    fig.update_xaxes(title=None, gridcolor="#f1f5f9", tickformat="%b %Y")
    return render(_layout(fig, 320))


def revenue_by_customer_monthly(invoices: pd.DataFrame, start, end) -> str:
    """Monthly revenue by top 3 customers + Other (thin focused trend)."""
    df = D.customer_monthly_revenue(invoices, start, end, top_n=3)
    if df.empty:
        return empty("No customer revenue data for this range")
    cols = [c for c in df.columns if c != "Month"]
    fig = go.Figure()
    colors = SEQ[:3] + ["#94a3b8"]
    for i, col in enumerate(cols):
        c = colors[i % len(colors)]
        is_other = col == "Other"
        fig.add_scatter(
            x=df["Month"], y=df[col],
            mode="lines+markers",
            line=dict(color=c, width=(1.5 if is_other else 3)),
            marker=dict(size=(5 if is_other else 8), color=c),
            name=col,
            hovertemplate="%{x|%b %Y}<br>%{customdata[0]}: $%{y:,.0f}<extra></extra>",
        )
    fig.update_layout(
        showlegend=True,
        legend=dict(orientation="v", font=dict(size=10), x=1.05, y=0.5),
        margin=dict(l=10, r=130, t=10, b=10),
    )
    fig.update_yaxes(title="Revenue", gridcolor="#e2e8f0")
    fig.update_xaxes(title=None, gridcolor="#f1f5f9", tickformat="%b %Y")
    return render(_layout(fig, 320))


def class_period_ranking(invoices: pd.DataFrame, start, end) -> str:
    """Ranked horizontal bar of class revenue for the period."""
    df = D.class_summary(invoices, start, end)
    if df.empty:
        return empty("No class data for this range")
    df = df.sort_values("Amount", ascending=True)
    labels = df["ClassName"] + "  " + df["Pct"].map(lambda v: f"{v:.1f}%")
    fig = go.Figure(
        go.Bar(
            x=df["Amount"], y=labels, orientation="h",
            marker=dict(color=ACCENT),
            hovertemplate="%{y}<br>$%{x:,.2f}<extra></extra>",
        )
    )
    fig.update_layout(showlegend=False)
    fig.update_xaxes(title="Revenue", gridcolor="#e2e8f0")
    fig.update_yaxes(title=None)
    return render(_layout(fig, max(260, 34 * len(df))))


def location_period_ranking(invoices: pd.DataFrame, start, end) -> str:
    """Ranked horizontal bar of city revenue for the period."""
    df = D.location_summary(invoices, start, end)
    if df.empty:
        return empty("No location data for this range")
    df = df.sort_values("Revenue", ascending=True)
    labels = df["City"] + "  " + df["Pct"].map(lambda v: f"{v:.1f}%")
    fig = go.Figure(
        go.Bar(
            x=df["Revenue"], y=labels, orientation="h",
            marker=dict(color="#0e7490"),
            hovertemplate="%{y}<br>$%{x:,.2f}<extra></extra>",
        )
    )
    fig.update_layout(showlegend=False)
    fig.update_xaxes(title="Revenue", gridcolor="#e2e8f0")
    fig.update_yaxes(title=None)
    return render(_layout(fig, max(260, 34 * len(df))))


def accounts_by_classification(accounts: pd.DataFrame) -> str:
    g = (
        accounts.assign(absBal=accounts["CurrentBalance"].abs())
        .groupby("Classification", as_index=False)["absBal"]
        .sum()
        .sort_values("absBal", ascending=True)
    )
    g = g[g["absBal"] > 0]
    if g.empty:
        return empty()
    small_count = min(4, len(g))
    textpositions = ["outside" if i < small_count else "inside" for i in range(len(g))]
    fig = go.Figure(
        go.Pie(
            labels=g["Classification"],
            values=g["absBal"],
            hole=0.55,
            marker=dict(colors=SEQ, line=dict(color="white", width=1)),
            textinfo="label+percent",
            textposition=textpositions,
            insidetextorientation="radial",
            rotation=135,
            textfont=dict(size=10),
            automargin=True,
            hovertemplate="%{label}<br>$%{value:,.2f} (%{percent})<extra></extra>",
        )
    )
    fig.update_layout(showlegend=True, legend=dict(orientation="v", x=1.25, y=0.5, font=dict(size=11)), margin=dict(l=10, r=180, t=10, b=10))
    return render(_layout(fig, 300))
