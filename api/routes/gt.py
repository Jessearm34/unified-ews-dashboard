"""GeoTab API routes — serve KPIs and chart HTML as JSON.
Chart logic recreated from the inline code in the original app.py."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta, date
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from fastapi import APIRouter, Query

from api.cache import cached
from api.utils import resolve_date_range, _rgba, empty as _empty_html
from data import gt_data as GT

router = APIRouter()

ACCENT = "#2563eb"
_EMPTY_HTML = '<div class="chart-empty">No data for this period.</div>'

_PLOT_CONFIG = {"displayModeBar": False, "responsive": True}


def _fig_html(fig, height=350):
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=5, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="'Inter', system-ui, -apple-system, sans-serif", size=11),
        yaxis=dict(gridcolor="#e2e8f0", zeroline=False, tickfont=dict(size=10)),
        xaxis=dict(gridcolor="#f1f5f9", zeroline=False, tickfont=dict(size=10)),
        showlegend=fig.layout.showlegend,
    )
    return fig.to_html(include_plotlyjs=False, full_html=False, config=_PLOT_CONFIG)


def _kpi_dict(label, value, hint="", unit=""):
    if value is None:
        val_str = "—"
    elif isinstance(value, float):
        val_str = f"{int(value):,}" if value == int(value) else f"{value:,.1f}"
    elif isinstance(value, int):
        val_str = f"{value:,}"
    else:
        val_str = str(value)
    if unit == "$" and isinstance(value, (int, float)):
        val_str = f"${val_str}"
    return {"label": label, "value": val_str, "unit": unit, "hint": hint or "", "rag": None, "platform": "GT", "delta": None, "delta_up_good": True}


def _load_gt():
    from sqlalchemy import text
    eng = GT.gt_engine()
    if eng is None:
        return None
    try:
        with eng.connect() as conn:
            vc = conn.execute(text("SELECT COUNT(*) FROM vehicles")).scalar()
            tc = conn.execute(text("SELECT COUNT(*) FROM trips")).scalar()
        if vc and vc > 0:
            return {"vehicles": vc, "trips": tc}
    except Exception:
        pass
    return None


@router.get("/_api/gt/{section}")
async def gt_section(section: str = "fleet", range: str = Query(default="all")):
    try:
        return _gt_section_impl(section, range_key=range)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        # Log the full traceback for Railway logs
        try:
            import logging
            logging.getLogger("ewsd").error("GT section '%s' failed:\n%s", section, tb)
        except Exception:
            pass
        return {
            "kpis": [],
            "charts": {},
            "loaded_at": datetime.now(timezone.utc).isoformat(),
            "has_more": {},
            "error": f"Internal error in GT/{section}: {e}",
            "traceback": tb[-500:],  # last 500 chars
        }


def _gt_section_impl(section: str, range_key: str):
    start, end = resolve_date_range(range_key)
    since = datetime.combine(start, datetime.min.time()).replace(tzinfo=timezone.utc)
    until = datetime.combine(end, datetime.max.time()).replace(tzinfo=timezone.utc)
    now_iso = datetime.now(timezone.utc).isoformat()
    I = ACCENT

    if section == "fleet":
        s = GT.fleet_summary(since, until)
        tr = GT.daily_trends(since, until)
        ut = GT.vehicle_utilization(since, until)
        il = GT.idling_summary(since, until)
        ic = GT.idling_cost(since, until)

        total_trips = sum(r.get("trips", 0) for r in tr) if tr else 0
        total_hrs = sum(u["hours_driven"] for u in ut) if ut else 0

        kpis = [
            _kpi_dict("Active Vehicles", s["active_vehicles"], f"of {s['total_vehicles']}"),
            _kpi_dict("Fleet Miles", s["total_fleet_miles"]),
            _kpi_dict("Total Trips", total_trips),
            _kpi_dict("Drive Hours", round(total_hrs)),
            _kpi_dict("Idle Cost", round(ic['estimated_cost']), unit="$",
                      hint=f"{ic['total_idle_hours']} hrs · ${ic['cost_per_hour']:.0f}/hr"),
        ]

        charts = {}

        # Daily Mileage Trend
        if tr and sum(r.get("mileage", 0) for r in tr) > 0:
            df = pd.DataFrame(tr).sort_values("day")
            df["d"] = pd.to_datetime(df["day"])
            f = go.Figure()
            f.add_trace(go.Scatter(
                x=df["d"], y=df["mileage"].rolling(7, min_periods=1).mean(),
                mode="lines", line=dict(color=I, width=2.5, shape="spline"),
                name="7-day avg", hovertemplate="%{x|%b %d}<br>%{y:,.0f} mi<extra></extra>"))
            f.add_trace(go.Bar(
                x=df["d"], y=df["mileage"], marker=dict(color=_rgba(I, 0.25)),
                name="Daily", hovertemplate="%{x|%b %d}<br>%{y:,.0f} mi<extra></extra>"))
            f.update_layout(showlegend=True, legend=dict(orientation="h", y=1.1, font=dict(size=9)))
            charts["mileage_trend"] = {"html": _fig_html(f), "title": "Daily Mileage Trend"}
        else:
            charts["mileage_trend"] = {"html": _EMPTY_HTML, "title": "Daily Mileage Trend"}

        # Vehicle Utilization
        top = [u for u in ut if u["total_miles"] > 0] if ut else []
        if len(top) >= 2:
            colors = [_rgba(I, max(0.3, 1 - (i/len(top))*0.7)) for i in range(len(top))]
            labs = [u.get("assigned_driver", "") or u["label"] for u in top]
            f = go.Figure(go.Bar(
                x=[u["total_miles"] for u in top], y=labs,
                orientation="h", marker=dict(color=colors),
                hovertemplate="%{y}<br>%{x:,.0f} mi<extra></extra>"))
            f.update_layout(yaxis=dict(autorange="reversed"), xaxis=dict(title="Miles Driven"))
            charts["utilization"] = {"html": _fig_html(f, 350), "title": "Vehicle Utilization"}
        else:
            charts["utilization"] = {"html": _EMPTY_HTML, "title": "Vehicle Utilization"}

        # Trip Count
        if tr and sum(r.get("trips", 0) for r in tr) > 0:
            df = pd.DataFrame(tr).sort_values("day")
            df["d"] = pd.to_datetime(df["day"])
            f = go.Figure(go.Bar(
                x=df["d"], y=df["trips"],
                marker=dict(color="#ea580c", opacity=0.7),
                hovertemplate="%{x|%b %d}<br>%{y} trips<extra></extra>"))
            charts["trip_count"] = {"html": _fig_html(f, 200), "title": "Trip Count per Day"}
        else:
            charts["trip_count"] = {"html": _EMPTY_HTML, "title": "Trip Count per Day"}

        # Idle Time
        iv = il.get("vehicles", []) if il else []
        av = [v for v in iv if v["idle_pct"] > 1] if iv else []
        if len(av) >= 2:
            colors = [_rgba("#ea580c", max(0.3, 1 - (i/len(av))*0.6)) for i in range(len(av))]
            labs = [v.get("assigned_driver", "") or v["label"] for v in av]
            f = go.Figure(go.Bar(
                x=[v["idle_pct"] for v in av], y=labs,
                orientation="h", marker=dict(color=colors),
                hovertemplate="%{y}<br>%{x:.1f}%<extra></extra>"))
            f.update_layout(yaxis=dict(autorange="reversed"), xaxis=dict(title="Idle %"))
            charts["idle_time"] = {"html": _fig_html(f, 250), "title": "Idle Time by Vehicle"}

        # ── Safety (merged into Fleet) ──────────────────────────────

        sb = GT.seatbelt_analysis(since, until)
        ah = GT.after_hours_analysis(since, until)
        sd = GT.safety_driver_rankings(since, until)

        # Seatbelt chart
        if sb:
            df = pd.DataFrame(sb)
            sb_off = df["seatbelt_off"].sum()
            sb_on = df["seatbelt_on"].sum()
            if sb_off > 0 and sb_on > 0:
                df["d"] = pd.to_datetime(df["day"])
                fig = go.Figure()
                fig.add_trace(go.Bar(x=df["d"], y=df["seatbelt_off"], name="No Belt",
                    marker=dict(color="#dc2626"), hovertemplate="%{x|%b %d}<br>%{y}<extra></extra>"))
                fig.add_trace(go.Bar(x=df["d"], y=df["seatbelt_on"], name="Belt On",
                    marker=dict(color="#16a34a")))
                fig.update_layout(barmode="stack", showlegend=True, legend=dict(orientation="h", y=1.1, font=dict(size=9)))
                charts["seatbelt"] = {"html": _fig_html(fig), "title": "Seatbelt Violations (Daily)"}

        # After-hours chart
        if ah:
            df = pd.DataFrame(ah)
            ah_mi = df["after_hours_miles"].sum()
            wk_mi = df["work_miles"].sum()
            if ah_mi > 0 and wk_mi > 0:
                df["d"] = pd.to_datetime(df["day"])
                fig = go.Figure()
                fig.add_trace(go.Bar(x=df["d"], y=df["work_miles"], name="Work",
                    marker=dict(color=ACCENT), hovertemplate="%{x|%b %d}<br>%{y:.0f} mi<extra></extra>"))
                fig.add_trace(go.Bar(x=df["d"], y=df["after_hours_miles"], name="After-Hours",
                    marker=dict(color="#ea580c")))
                fig.update_layout(barmode="stack", showlegend=True, legend=dict(orientation="h", y=1.1, font=dict(size=9)))
                charts["after_hours"] = {"html": _fig_html(fig), "title": "Work vs After-Hours Miles"}

        # Driver safety score
        if sd:
            active = [d for d in sd if d["trip_count"] > 0][:15]
            if active:
                colors = ["#16a34a" if s["score"] >= 80 else "#ea580c" if s["score"] >= 60 else "#dc2626" for s in active]
                fig = go.Figure(go.Bar(
                    x=[d["score"] for d in active], y=[d["name"] for d in active],
                    orientation="h", marker=dict(color=colors),
                    hovertemplate="%{y}<br>Score: %{x}<extra></extra>"))
                fig.update_layout(xaxis=dict(range=[0, 100]), yaxis=dict(autorange="reversed"))
                charts["safety_score"] = {"html": _fig_html(fig), "title": "Driver Safety Score"}

            # Safety table
            trs = ""
            for d in sd[:20]:
                bg = "green" if d["score"] >= 80 else "warn" if d["score"] >= 60 else "red"
                trs += f"<tr><td>{d['name']}</td><td class='num'>{d['trip_count']}</td>"
                trs += f"<td class='num'>{d['seatbelt_violation_pct']:.0f}%</td>"
                trs += f"<td class='num'>{d['after_hours_pct']:.0f}%</td>"
                trs += f"<td class='num'>{d['idle_pct']:.0f}%</td>"
                trs += f"<td class='num'>{d['speeding_pct']:.0f}%</td>"
                trs += f"<td><span class='badge {bg}'>{d['score']}</span></td></tr>"
            sd_table = f"<div class='tbl-wrap' style='max-height:400px'><table class='data'><thead><tr><th>Driver</th><th class='num'>Trips</th><th class='num'>Seatbelt</th><th class='num'>After-Hrs</th><th class='num'>Idle</th><th class='num'>Speeding</th><th class='num'>Score</th></tr></thead><tbody>{trs}</tbody></table></div>"
            charts["safety_table"] = {"html": sd_table, "title": "Safety Details"}

        return {"kpis": kpis, "charts": charts, "loaded_at": now_iso, "has_more": {}}

    elif section == "maintenance":
        mt = GT.vehicle_maintenance_status(since, until)
        fl = GT.maintenance_metrics(since, until)
        charts = {}
        total_odo = sum(v.get("odo_mi", 0) for v in mt)
        kpis = [
            _kpi_dict("Vehicles Tracked", len(mt)),
            _kpi_dict("Total Odometer", round(total_odo)),
        ]

        active_mt = [v for v in mt if v.get("odo_mi", 0) > 0]
        if len(active_mt) >= 2:
            colors = [_rgba(I, max(0.3, 1 - (i/len(active_mt))*0.7)) for i in range(len(active_mt))]
            f = go.Figure(go.Bar(
                x=[v["odo_mi"] for v in active_mt], y=[v["label"] for v in active_mt],
                orientation="h", marker=dict(color=colors),
                hovertemplate="%{y}<br>%{x:,.0f} mi<extra></extra>"))
            f.update_layout(yaxis=dict(autorange="reversed"), xaxis=dict(title="Odometer (mi)"))
            charts["odometer"] = {"html": _fig_html(f, 300), "title": "Vehicle Odometer"}

        freq = fl.get("fault_frequency", []) if fl else []
        if len(freq) >= 2:
            colors = [_rgba("#dc2626", max(0.3, 1 - (i/len(freq))*0.6)) for i in range(len(freq))]
            f = go.Figure(go.Bar(
                x=[f["count"] for f in freq], y=[f["fault_code"] for f in freq],
                orientation="h", marker=dict(color=colors),
                hovertemplate="%{y}<br>%{x} occurrences<extra></extra>"))
            f.update_layout(yaxis=dict(autorange="reversed"), xaxis=dict(title="Occurrences"))
            charts["faults"] = {"html": _fig_html(f, 300), "title": "Fault Frequency"}

        return {"kpis": kpis, "charts": charts, "loaded_at": now_iso, "has_more": {}}

    return {"kpis": [], "charts": {}, "loaded_at": now_iso, "has_more": {}}