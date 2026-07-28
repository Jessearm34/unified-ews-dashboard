"""Cross-platform correlation charts — connecting SiteDocs safety with GeoTab fleet data.

Each function returns an HTML string (Plotly .to_html()).
"""

from __future__ import annotations

import random
from typing import Any

import pandas as pd
import plotly.graph_objects as go

from data import sd_data as SD
from data import gt_data as GT

_PLOT_CONFIG = {"displayModeBar": False, "displaylogo": False, "responsive": True}
_ids = iter(lambda: f'cross-chart-{random.randrange(10_000_000, 99_999_999)}', None)

SD_BLUE = "#2563eb"
GT_ORANGE = "#ea580c"


def _layout(fig: go.Figure, height: int = 300) -> go.Figure:
    fig.update_layout(
        template="plotly_white", height=height,
        margin=dict(l=10, r=50, t=30, b=10),
        font=dict(family="Inter, system-ui, sans-serif", size=12, color="#0f172a"),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        title=None,
    )
    return fig


def render(fig: go.Figure) -> str:
    return fig.to_html(include_plotlyjs=False, full_html=False,
                       config=_PLOT_CONFIG, div_id=f"plot-{next(_ids)}",
                       default_width="100%")


def empty(message: str = "No data for correlation") -> str:
    return f"<div class='chart-empty'>{message}</div>"


def safety_fleet_dual(forms: pd.DataFrame,
                       gt_since, gt_until) -> str:
    """Dual-axis chart: BBSO observations (bars, left axis) vs fleet speeding (line, right axis).

    Shows if proactive safety engagement correlates with fleet risk behavior.
    """
    # SD: BBSO monthly trend
    bbso = SD.bbso_monthly_trend(forms)
    if bbso.empty:
        return empty("No BBSO data for correlation")

    # GT: speeding trips daily → aggregate to monthly
    try:
        spd = GT.speed_trend(gt_since, gt_until)
    except Exception:
        spd = []

    if not spd:
        # Just show BBSO alone
        fig = go.Figure(go.Bar(
            x=bbso["Month"], y=bbso["Count"],
            marker=dict(color=SD_BLUE),
            name="BBSO Observations",
            hovertemplate="%{x|%b %Y}<br>%{y} BBSOs<extra></extra>",
        ))
        fig.update_layout(showlegend=False)
        fig.update_yaxes(title="BBSO Observations", gridcolor="#e2e8f0")
        return render(_layout(fig, 280))

    # Aggregate speeding by month
    spd_df = pd.DataFrame(spd)
    spd_df["day"] = pd.to_datetime(spd_df["day"])
    spd_df["month"] = spd_df["day"].dt.to_period("M").dt.to_timestamp()
    spd_monthly = spd_df.groupby("month")["speeding_trips"].sum().reset_index()

    # Merge BBSO and speeding by month
    bbso["month"] = bbso["Month"]
    merged = bbso.merge(spd_monthly, on="month", how="outer").sort_values("month").fillna(0)
    if merged.empty or merged["Count"].sum() == 0:
        return empty("Not enough overlapping data for correlation")

    fig = go.Figure()

    # BBSO bars (left axis)
    fig.add_trace(go.Bar(
        x=merged["month"], y=merged["Count"],
        name="BBSO Observations",
        marker=dict(color=SD_BLUE, opacity=0.7),
        yaxis="y",
        hovertemplate="%{x|%b %Y}<br>%{y} BBSOs<extra></extra>",
    ))

    # Speeding line (right axis)
    fig.add_trace(go.Scatter(
        x=merged["month"], y=merged["speeding_trips"],
        name="Speeding Events",
        mode="lines+markers",
        line=dict(color=GT_ORANGE, width=2.5, dash="dot"),
        marker=dict(size=6, color=GT_ORANGE),
        yaxis="y2",
        hovertemplate="%{x|%b %Y}<br>%{y} speeding events<extra></extra>",
    ))

    fig.update_layout(
        showlegend=True,
        legend=dict(orientation="h", y=1.12, x=0, font=dict(size=9)),
        yaxis=dict(title="BBSO Observations", gridcolor="#e2e8f0"),
        yaxis2=dict(
            title="Speeding Events", overlaying="y", side="right",
            gridcolor="#f1f5f9", showgrid=False,
        ),
        xaxis=dict(gridcolor="#f1f5f9"),
    )

    return render(_layout(fig, 300))


def person_profiles_table(profiles: list[dict]) -> str:
    """HTML table of person-level cross-platform safety profiles.

    Shows who's active on safety (SD) AND driving (GT) — identifies
    high/low performers across both domains.
    """
    if not profiles:
        return empty("No person profiles available")

    matched = [p for p in profiles if p.get("matched")]
    rows = []
    for p in matched[:20]:
        name = p.get("name", "—")
        sd_role = p.get("sd_role", "")
        sd_bbso = int(p.get("sd_bbso", 0))
        sd_rir = int(p.get("sd_rir", 0))
        gt_trips = int(p.get("gt_trip_count", 0))
        gt_miles = round(float(p.get("gt_miles", 0)), 0)
        gt_score = p.get("gt_safety_score")
        score_str = f"{gt_score:.0f}" if gt_score is not None else "—"
        score_cls = "badge green" if gt_score and gt_score >= 80 else ("badge warn" if gt_score and gt_score >= 60 else "badge red") if gt_score else ""

        sd_tag = ""
        if sd_bbso > 0 or sd_rir > 0:
            sd_tag = '<span class="badge green" style="font-size:10px">Active</span>'
        else:
            sd_tag = '<span class="badge" style="background:#e2e8f0;color:#64748b;font-size:10px">Inactive</span>'

        rows.append(f"""<tr>
            <td>{name}<br><span class="note">{sd_role}</span></td>
            <td class="num">{sd_tag}</td>
            <td class="num">{sd_bbso}</td>
            <td class="num">{sd_rir}</td>
            <td class="num">{gt_trips}</td>
            <td class="num">{gt_miles:,.0f}</td>
            <td class="num">{'<span class="' + score_cls + '">' + score_str + '</span>' if score_str != '—' else '—'}</td>
        </tr>""")

    header = """<tr><th>Person</th><th>Safety</th><th>BBSO</th><th>RIR</th><th>Trips</th><th>Miles</th><th>Score</th></tr>"""
    return f"""<div class='tbl-wrap' style='max-height:400px'><table class='data'><thead>{header}</thead><tbody>{"".join(rows)}</tbody></table></div>"""
