"""Plotly figure builders for the Geotab fleet dashboard.

Each function takes a data dict (from gt_load_data) and returns an HTML
fragment (plot div + init script).  Plotly.js is loaded once in the page head,
so every fragment uses ``include_plotlyjs=False``.  HTMX evaluates the inline
init script when the fragment is swapped in, so charts re-render on every
interaction.
"""
from __future__ import annotations

import itertools

import pandas as pd
import plotly.graph_objects as go

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
        template="plotly_white",
        height=height,
        margin=dict(l=20, r=10, t=30, b=10),
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


def empty(message: str = "No data for this period") -> str:
    return f"<div class='chart-empty'>{message}</div>"


# ---------------------------------------------------------------------------
# KPI helpers
# ---------------------------------------------------------------------------


def _kpi_card(label: str, value, hint: str = "", unit: str = "") -> str:
    if value is None:
        val = "\u2014"
    elif isinstance(value, float):
        if unit == "%":
            val = f"{value:.1f}%"
        elif value == int(value):
            val = f"{int(value):,}"
        else:
            val = f"{value:,.1f}"
    else:
        val = f"{value:,}"
    hint_html = f"<div class='k-hint'>{hint}</div>" if hint else ""
    return (
        f"<div class='kpi'>"
        f"<div class='k-label'>{label}</div>"
        f"<div class='k-value'>{val}</div>"
        f"{hint_html}"
        f"</div>"
    )


def fleet_kpi_row(data: dict) -> str:
    """HTML for the top KPI cards row.

    Consumes ``data["summary"]``, ``data["trends"]``, ``data["speed"]``,
    and ``data["idling"]``.
    """
    s = data["summary"]
    spd = data.get("speed", {})
    idl = data.get("idling", {})
    trends = data.get("trends", [])

    total_trips = sum(t.get("trips", 0) for t in trends)
    daily_avg = round(s.total_fleet_miles / total_trips, 1) if total_trips else 0

    cards = "".join([
        _kpi_card("Active Vehicles", s.active_vehicles, f"of {s.total_vehicles} total"),
        _kpi_card("Fleet Miles", s.total_fleet_miles, "Total distance"),
        _kpi_card("Total Trips", total_trips, f"{daily_avg} mi avg trip"),
        _kpi_card("Idle Time", idl.get("idle_pct", 0),
                  f"{idl.get('total_idle_hours', 0):.0f} hours", "%"),
        _kpi_card("Avg Speed", round(spd.get("avg_speed", 0), 1),
                  f"Max {round(spd.get('max_speed', 0), 1)} mph", "mph"),
        _kpi_card("Speeding Events", spd.get("speeding_count", 0),
                  f"{spd.get('speeding_pct', 0):.1f}% of GPS"),
    ])
    return f"<div class='kpis'>{cards}</div>"


# ---------------------------------------------------------------------------
# Chart builders
# ---------------------------------------------------------------------------


def daily_mileage_chart(data: dict) -> str:
    """Spline line chart with area fill — daily mileage from ``data["trends"]``."""
    trends = data.get("trends", [])
    if not trends:
        return empty("No trip data")

    df = pd.DataFrame(trends)
    if df.empty or df["mileage"].sum() == 0:
        return empty("No mileage data")

    df["d"] = pd.to_datetime(df["day"])
    labels = df[df["d"].dt.day == 1]

    fig = go.Figure(go.Scatter(
        x=df["d"], y=df["mileage"],
        mode="lines+markers",
        line=dict(color=ACCENT, width=3, shape="spline"),
        marker=dict(size=6, color=ACCENT),
        fill="tozeroy",
        fillcolor=_rgba(ACCENT, 0.10),
        hovertemplate="%{x|%b %d}<br>%{y:,.0f} miles<extra></extra>",
    ))
    fig.update_layout(showlegend=False)
    fig.update_yaxes(gridcolor="#e2e8f0")
    fig.update_xaxes(
        gridcolor="#f1f5f9",
        tickvals=labels["d"].tolist() if not labels.empty else None,
        ticktext=labels["d"].dt.strftime("%b").tolist() if not labels.empty else None,
        tickfont=dict(size=10),
    )
    return render(_layout(fig, 300))


def trip_count_chart(data: dict) -> str:
    """Bar chart of daily trip counts from ``data["trends"]``."""
    trends = data.get("trends", [])
    if not trends:
        return empty("No trip data")

    df = pd.DataFrame(trends)
    if df.empty or df["trips"].sum() == 0:
        return empty("No trip data")

    x = pd.to_datetime(df["day"])
    fig = go.Figure(go.Bar(
        x=x, y=df["trips"],
        marker=dict(color="#0e7490"),
        hovertemplate="%{x|%b %d}<br>%{y} trips<extra></extra>",
    ))
    fig.update_layout(showlegend=False)
    fig.update_xaxes(gridcolor="#f1f5f9")
    fig.update_yaxes(gridcolor="#e2e8f0")
    return render(_layout(fig, 250))


def vehicle_utilization_chart(data: dict) -> str:
    """Horizontal bar chart of top 10 vehicles by miles from ``data["vehicle_util"]``."""
    util = data.get("vehicle_util", [])
    top = [u for u in util[:10] if u["total_miles"] > 0]
    if not top:
        return empty("No vehicles with miles")

    fig = go.Figure(go.Bar(
        x=[u["total_miles"] for u in top],
        y=[u["label"] for u in top],
        orientation="h",
        marker=dict(color=ACCENT),
        hovertemplate="%{y}<br>%{x:,.0f} miles<extra></extra>",
    ))
    fig.update_layout(showlegend=False)
    fig.update_xaxes(gridcolor="#e2e8f0", tickfont=dict(size=10))
    fig.update_yaxes(autorange="reversed", tickfont=dict(size=10))
    return render(_layout(fig, max(260, 28 * len(top))))


def vehicle_table(data: dict) -> str:
    """HTML table of top 20 vehicles (Vehicle, Miles, Hours, Util %) from ``data["vehicle_util"]``."""
    util = data.get("vehicle_util", [])
    if not util:
        return empty("No vehicle data")

    rows = "".join(
        f"<tr><td>{u['label']}</td><td class='num'>{u['total_miles']:,.0f}</td>"
        f"<td class='num'>{u['hours_driven']:.1f}</td>"
        f"<td class='num'>{u['utilization_percentage']:.1f}%</td></tr>"
        for u in util[:20]
    )
    return (
        "<div class='tbl-wrap'>"
        "<table class='data'>"
        "<thead><tr><th>Vehicle</th><th class='num'>Miles</th>"
        "<th class='num'>Hours</th><th class='num'>Util %</th></tr></thead>"
        f"<tbody>{rows}</tbody>"
        "</table></div>"
    )


def speed_distribution_chart(data: dict) -> str:
    """Histogram of speed distribution from ``data["speed"]["speed_distribution"]``."""
    spd = data.get("speed", {})
    samples = spd.get("speed_distribution", [])
    if not samples:
        return empty("No GPS speed data")

    fig = go.Figure(go.Histogram(
        x=samples,
        marker=dict(color="#ea580c"),
        hovertemplate="%{x:.0f} mph<br>%{y} records<extra></extra>",
    ))
    fig.update_layout(showlegend=False)
    fig.update_yaxes(gridcolor="#e2e8f0")
    fig.update_xaxes(title="Speed (mph)", gridcolor="#f1f5f9", tickfont=dict(size=10))
    return render(_layout(fig, 280))


def idle_time_chart(data: dict) -> str:
    """Horizontal bar of top 10 vehicles by idle % from ``data["idling"]["vehicles"]``."""
    idl = data.get("idling", {})
    vehicles = idl.get("vehicles", [])
    active = [v for v in vehicles if v["idle_pct"] > 0][:10]
    if not active:
        return empty("No idle data")

    fig = go.Figure(go.Bar(
        x=[v["idle_pct"] for v in active],
        y=[v["label"] for v in active],
        orientation="h",
        marker=dict(color="#ea580c"),
        hovertemplate="%{y}<br>%{x:.1f}% idle<extra></extra>",
    ))
    fig.update_layout(showlegend=False)
    fig.update_xaxes(gridcolor="#e2e8f0", tickformat=".0f", ticksuffix="%", tickfont=dict(size=10))
    fig.update_yaxes(autorange="reversed", tickfont=dict(size=10))
    return render(_layout(fig, max(260, 28 * len(active))))


def fleet_map(data: dict) -> str:
    """Scattergeo map of latest locations from ``data["locations"]``."""
    locs = data.get("locations", [])
    if not locs:
        return empty("No GPS location data")

    moving = [l for l in locs if l["speed"] > 1]
    stopped = [l for l in locs if l["speed"] <= 1]

    fig = go.Figure()
    if moving:
        fig.add_trace(go.Scattergeo(
            lat=[l["latitude"] for l in moving],
            lon=[l["longitude"] for l in moving],
            mode="markers",
            marker=dict(size=8, color="#16a34a"),
            text=[l["vehicle"] for l in moving],
            name="Moving",
            hovertemplate="%{text}<extra></extra>",
        ))
    if stopped:
        fig.add_trace(go.Scattergeo(
            lat=[l["latitude"] for l in stopped],
            lon=[l["longitude"] for l in stopped],
            mode="markers",
            marker=dict(size=6, color="#94a3b8"),
            text=[l["vehicle"] for l in stopped],
            name="Stopped",
            hovertemplate="%{text}<extra></extra>",
        ))
    fig.update_layout(
        showlegend=True,
        legend=dict(orientation="h", y=1.1),
        geo=dict(projection_type="natural earth"),
        height=420,
        margin=dict(l=10, r=10, t=10, b=10),
    )
    return render(fig)
