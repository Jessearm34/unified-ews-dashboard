"""FastHTML chart builders — combines QB, SD, and GT charts.

QB trend chart uses current-month visual distinction (open circle marker).
All other chart types delegate to the existing modular chart packages.
"""

from __future__ import annotations

import itertools
from datetime import date as dt_date

import pandas as pd
import plotly.graph_objects as go

# QB charts (with current-month visual)
from charts import qb_charts as QBC
# SD charts
from charts import sd_charts as SDC
# Cross-platform charts
from charts import issues_charts as IC
from charts import cross_charts as XC

# ── Plotly helpers ─────────────────────────────────────────────────

ACCENT = "#2563eb"
SEQ = ["#2563eb", "#0e7490", "#7c3aed", "#16a34a", "#ea580c", "#db2777", "#0891b2", "#64748b"]
_PLOT_CONFIG = {"displayModeBar": False, "responsive": True}
_ids = itertools.count()


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _layout(fig: go.Figure, height: int = 300) -> go.Figure:
    fig.update_layout(
        template="plotly_white", height=height,
        margin=dict(l=10, r=10, t=30, b=10),
        font=dict(family="Inter, system-ui, sans-serif", size=12, color="#0f172a"),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=fig.layout.showlegend,
        title=None, uniformtext=dict(minsize=9, mode="hide"),
    )
    return fig


def render(fig: go.Figure) -> str:
    return fig.to_html(
        include_plotlyjs=False, full_html=False,
        config=_PLOT_CONFIG, div_id=f"plot-{next(_ids)}",
        default_width="100%",
    )


def empty(message: str = "No data for this range") -> str:
    return f"<div class='chart-empty'>{message}</div>"


# ── QB Charts (with current-month visual) ──────────────────────────

def trend(invoices: pd.DataFrame, metric: str) -> str:
    """Monthly trend with in-progress month as open circle marker."""
    import data.qb_data as D
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
    if not completed.empty:
        fig.add_trace(go.Scatter(
            x=completed["Month"], y=completed["value"],
            mode="lines+markers",
            line=dict(color=color, width=3, shape="spline"),
            marker=dict(size=7, color=color),
            fill="tozeroy", fillcolor=_rgba(color, 0.10),
            name="Completed",
            hovertemplate=f"%{{x|%b %Y}}<br>{hover_fmt}<extra></extra>",
        ))
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
                mode="lines+markers", line=dict(color=color, width=3, shape="spline"),
                marker=dict(size=7, color=color),
                fill="tozeroy", fillcolor=_rgba(color, 0.10),
                name="Completed",
                hovertemplate=f"%{{x|%b %Y}}<br>{hover_fmt}<extra></extra>",
            ))

    fig.update_layout(showlegend=False)
    fig.update_yaxes(title=ylabel, gridcolor="#e2e8f0")
    fig.update_xaxes(title=None, gridcolor="#f1f5f9", dtick="M1", tickformat="%b %Y")
    return render(_layout(fig, 320))


# ── QB Charts (delegated) ──────────────────────────────────────────

def revenue_by_city(invoices): return QBC.revenue_by_city(invoices)
def revenue_by_item(invoices): return QBC.revenue_by_item(invoices)
def revenue_by_class(invoices): return QBC.revenue_by_class(invoices)
def top_customers(invoices): return QBC.top_customers(invoices)
def ar_aging(invoices): return QBC.ar_aging(invoices)
def balance_sheet(accounts): return QBC.balance_sheet(accounts)
def balance_status(invoices): return QBC.balance_status(invoices)
def accounts_by_type(accounts): return QBC.accounts_by_type(accounts)
def accounts_by_classification(accounts): return QBC.accounts_by_classification(accounts)


# ── SD Charts (delegated) ──────────────────────────────────────────

def bbso_trend(forms, *a, **kw): return SDC.bbso_trend(forms, *a, **kw)
def rir_trend(forms, *a, **kw): return SDC.rir_trend(forms, *a, **kw)
def forms_trend(forms, *a, **kw): return SDC.forms_trend(forms, *a, **kw)
def bbso_risk_heatmap(forms, responses): return SDC.bbso_risk_heatmap(forms, responses)
def schedule_compliance(sched): return SDC.schedule_compliance(sched)
def form_category_chart(forms): return SDC.form_category_chart(forms)
def safety_profile_table(workers, forms): return SDC.safety_profile_table(workers, forms)
def observer_leaderboard_table(workers, forms): return SDC.observer_leaderboard_table(workers, forms)
def reporter_leaderboard_table(workers, forms): return SDC.reporter_leaderboard_table(workers, forms)
def worker_status(workers): return SDC.worker_status(workers)
def worker_type_split(workers): return SDC.worker_type_split(workers)
def rir_events_from_forms(forms, workers, incidents, locations):
    return SDC.rir_events_from_forms(forms, workers, incidents, locations)
def bbso_rir_leaderboard_table(workers, forms): return SDC.bbso_rir_leaderboard_table(workers, forms)
def worker_leaderboard_table(workers, forms, sigs, sched):
    return SDC.worker_leaderboard_table(workers, forms, sigs, sched)
def overdue_items_list(schedules): return SDC.overdue_items_list(schedules)
def form_types_chart(formtypes, forms): return SDC.form_types_chart(formtypes, forms)


# ── Cross-platform Charts ──────────────────────────────────────────

def issues_table(issues): return IC.issues_table(issues)
