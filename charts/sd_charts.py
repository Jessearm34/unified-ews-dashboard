"""Plotly figure builders for the SiteDocs safety dashboard."""
from __future__ import annotations

import re
import json
import random

import pandas as pd
import plotly.graph_objects as go

try:
    import data.sd_data as D
except ImportError:
    from charts import sd_data as D


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
        template="plotly_white", height=height,
        margin=dict(l=20, r=10, t=30, b=10),
        font=dict(family="Inter, system-ui, sans-serif", size=12, color="#0f172a"),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=fig.layout.showlegend, title=None,
        uniformtext=dict(minsize=9, mode="hide"),
    )
    return fig


def render(fig: go.Figure) -> str:
    return fig.to_html(include_plotlyjs=False, full_html=False,
                       config=_PLOT_CONFIG, div_id=f"plot-{next(_ids)}",
                       default_width="100%")


def empty(message: str = "No data for this period") -> str:
    return f"<div class='chart-empty'>{message}</div>"


def worker_status(workers: pd.DataFrame) -> str:
    c = D.worker_counts(workers)
    labels = [f"Active ({c['active']})", f"Inactive ({c['inactive']})"]
    values = [c["active"], c["inactive"]]
    if sum(values) == 0:
        return empty()
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.55,
        marker=dict(colors=[SEQ[0], SEQ[-1]], line=dict(color="white", width=1)),
        textinfo="label+percent"))
    fig.update_layout(showlegend=False)
    return render(_layout(fig, 260))


def worker_type_split(workers: pd.DataFrame) -> str:
    c = D.worker_counts(workers)
    labels = [f"Employees ({c['employees']})", f"Contractors ({c['contractors']})"]
    values = [c["employees"], c["contractors"]]
    if sum(values) == 0:
        return empty()
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.55,
        marker=dict(colors=[SEQ[2], SEQ[4]], line=dict(color="white", width=1)),
        textinfo="label+percent"))
    fig.update_layout(showlegend=False)
    return render(_layout(fig, 260))


def cert_expiry_profile(certs: pd.DataFrame) -> str:
    df = D.cert_type_breakdown(certs)
    if df.empty:
        return empty("No certification data")
    fig = go.Figure()
    for col, color, label in [("Active", SEQ[0], "Active"),
                               ("Expiring", SEQ[4], "Expiring (<=90d)"),
                               ("Expired", "#dc2626", "Expired")]:
        if col in df.columns and df[col].sum() > 0:
            fig.add_bar(x=df["CertificationType"], y=df[col], name=label,
                        marker=dict(color=color))
    fig.update_layout(barmode="stack", showlegend=True,
                      legend=dict(orientation="h", y=1.12, x=0))
    fig.update_yaxes(title=None, gridcolor="#e2e8f0")
    fig.update_xaxes(title=None, tickangle=-30)
    return render(_layout(fig, 320))


def cert_coverage(certs: pd.DataFrame, workers: pd.DataFrame) -> str:
    summary = D.cert_summary(certs, workers)
    trained = summary["unique_workers_with_certs"]
    total = len(workers)
    untrained = max(total - trained, 0)
    labels = [f"Trained ({trained})", f"Untrained ({untrained})"]
    values = [trained, untrained]
    if sum(values) == 0:
        return empty()
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.55,
        marker=dict(colors=[SEQ[0], "#e2e8f0"], line=dict(color="white", width=1)),
        textinfo="label+percent"))
    fig.update_layout(showlegend=False)
    return render(_layout(fig, 260))


def incident_trend(incidents: pd.DataFrame) -> str:
    df = D.incident_monthly_trend(incidents)
    if df.empty:
        return empty()
    tick_count = min(len(df), 6)
    fig = go.Figure(go.Scatter(x=df["Month"], y=df["Count"],
        mode="lines+markers", line=dict(color="#dc2626", width=3, shape="spline"),
        marker=dict(size=7, color="#dc2626"), fill="tozeroy",
        fillcolor=_rgba("#dc2626", 0.10),
        hovertemplate="%{x|%b %Y}<br>%{y} incidents<extra></extra>"))
    fig.update_layout(showlegend=False)
    fig.update_yaxes(gridcolor="#e2e8f0", dtick=1)
    fig.update_xaxes(title=None, gridcolor="#f1f5f9", tickformat="%b %Y",
                     tickangle=-30, nticks=tick_count, tickfont=dict(size=10),
                     tickmode="auto")
    return render(_layout(fig, 300))


def incident_by_type(incidents: pd.DataFrame) -> str:
    df = D.incident_by_type(incidents)
    if df.empty:
        return empty()
    fig = go.Figure(go.Bar(x=df["Count"], y=df["TypeName"], orientation="h",
        marker=dict(color=ACCENT)))
    fig.update_layout(showlegend=False)
    fig.update_xaxes(title=None, gridcolor="#e2e8f0", tickfont=dict(size=10))
    fig.update_yaxes(title=None)
    return render(_layout(fig, max(260, 34 * len(df))))


def incident_status_pie(incidents: pd.DataFrame) -> str:
    df = D.incident_by_status(incidents)
    if df.empty:
        return empty()
    colors = {"Open": "#dc2626", "Closed": "#16a34a", "Investigation": "#ea580c"}
    markers = [colors.get(r["LatestStatus"], ACCENT) for _, r in df.iterrows()]
    fig = go.Figure(go.Pie(labels=df["LatestStatus"], values=df["Count"],
        hole=0.55, marker=dict(colors=markers, line=dict(color="white", width=1)),
        textinfo="label+percent"))
    fig.update_layout(showlegend=False)
    return render(_layout(fig, 260))


def equipment_by_type(equipment: pd.DataFrame) -> str:
    df = D.equipment_by_type(equipment)
    if df.empty:
        return empty()
    fig = go.Figure(go.Bar(x=df["Count"], y=df["EquipmentTypeName"], orientation="h",
        marker=dict(color=ACCENT)))
    fig.update_layout(showlegend=False)
    fig.update_xaxes(title=None, gridcolor="#e2e8f0", dtick=1)
    fig.update_yaxes(title=None)
    return render(_layout(fig, max(260, 34 * len(df))))


def equipment_status(equipment: pd.DataFrame) -> str:
    c = D.equipment_counts(equipment)
    if c["total"] == 0:
        return empty()
    labels = [f"Active ({c['active']})", f"Inactive ({c['inactive']})"]
    values = [c["active"], c["inactive"]]
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.55,
        marker=dict(colors=[SEQ[0], SEQ[-1]], line=dict(color="white", width=1)),
        textinfo="label+percent"))
    fig.update_layout(showlegend=False)
    return render(_layout(fig, 260))


def form_types_chart(formtypes: pd.DataFrame, forms: pd.DataFrame) -> str:
    """Horizontal bar chart of form types by submission count."""
    df = D.form_types_with_counts(formtypes, forms)
    if df.empty:
        return empty("No form types")
    top = df.head(12)
    if top["Count"].sum() == 0:
        return empty("No form submissions yet")
    fig = go.Figure(go.Bar(
        x=top["Count"], y=top["FormType"], orientation="h",
        marker=dict(color=ACCENT),
        hovertemplate="%{y}<br>%{x} submissions<extra></extra>"))
    fig.update_layout(showlegend=False)
    fig.update_xaxes(title=None, gridcolor="#e2e8f0", tickfont=dict(size=10))
    fig.update_yaxes(title=None, autorange="reversed")
    return render(_layout(fig, max(260, 28 * len(top))))


def forms_trend(forms: pd.DataFrame) -> str:
    """Monthly forms — vertical bar chart with clean labels. Click a bar to see forms."""
    df = D.forms_monthly_trend(forms)
    if df.empty:
        return empty("No form submission data")
    df["Label"] = df["Month"].dt.strftime("%b")
    max_val = df["Count"].max() if not df.empty else 1
    months_iso = df["Month"].dt.strftime("%Y-%m").tolist()
    fig = go.Figure(go.Bar(
        x=df["Label"], y=df["Count"],
        marker=dict(color=ACCENT, line=dict(width=0)),
        hovertemplate="%{x} %{y} forms<extra></extra>",
        text=df["Count"], textposition="outside", textfont=dict(size=11, color="#0f172a"),
        customdata=months_iso))
    fig.update_layout(showlegend=False)
    fig.update_yaxes(gridcolor="#e2e8f0", showticklabels=False, showgrid=False,
                     range=[0, max_val * 1.25])
    fig.update_xaxes(gridcolor="#f1f5f9", tickfont=dict(size=11))
    html = render(_layout(fig, 300))
    div_id = html.split('id="')[1].split('"')[0] if 'id="' in html else "plot-0"
    click_js = '<script>'
    click_js += 'var el=document.getElementById("' + div_id + '");'
    click_js += 'if(el){el.on("plotly_click",function(d){'
    click_js += 'var m=d.points[0].customdata; if(m&&typeof htmx!="undefined"){'
    click_js += 'htmx.ajax("GET","/_sd_forms?month="+m,{target:"#sd-forms-chart",swap:"outerHTML"});'
    click_js += '}});}</script>'
    return '<div id="sd-forms-chart">' + html + click_js + '</div>'

def schedule_compliance(sched: pd.DataFrame) -> str:
    """Stacked bar: status breakdown for schedules."""
    if sched.empty:
        return empty("No schedule data")
    c = D.schedule_counts(sched)
    categories = [("Completed", c["completed"], "#16a34a"),
                  ("Scheduled", c["scheduled"], "#2563eb"),
                  ("Late", c["late"], "#ea580c"),
                  ("Overdue", c["overdue"], "#dc2626"),
                  ("Cancelled", c["cancelled"], "#94a3b8")]
    total = c["total"]
    if total == 0:
        return empty("No schedule data")
    labels, values, colors = [], [], []
    for name, val, color in categories:
        if val > 0:
            labels.append(f"{name} ({val})")
            values.append(val)
            colors.append(color)
    if not values:
        return empty("No schedule data")
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.5,
        marker=dict(colors=colors, line=dict(color="white", width=1)),
        textinfo="label+percent"))
    fig.update_layout(showlegend=False)
    pct = c["completion_pct"]
    fig.add_annotation(text=f"{pct:.0f}%<br><span style='font-size:10px'>complete</span>",
        x=0.5, y=0.5, showarrow=False, font=dict(size=18, color="#16a34a", family="Inter"),
        align="center")
    return render(_layout(fig, 280))


def schedules_overview(sched: pd.DataFrame) -> str:
    return schedule_compliance(sched)


def overdue_items_list(schedules: pd.DataFrame) -> str:
    """HTML table of overdue/late schedule items."""
    df = D.overdue_items(schedules)
    if df.empty:
        return empty("No overdue items — all schedules on track")
    rows = []
    for _, r in df.iterrows():
        status = r.get("status", "")
        badge_cls = "badge red" if status == "Overdue" else "badge warn"
        due = str(r.get("formDueOn", ""))[:10] if pd.notna(r.get("formDueOn")) else "—"
        days = int(r.get("daysOverdue", 0))
        rows.append(f"""<tr>
            <td>{r.get('formTypeName','—')[:40]}</td>
            <td>{r.get('locationName','—')[:20]}</td>
            <td>{r.get('responsibleEmployeeName','—')[:20]}</td>
            <td><span class='{badge_cls}'>{status}</span></td>
            <td>{due}</td>
            <td class='num'>{days}d</td>
        </tr>""")
    header = """<tr><th>Form</th><th>Location</th><th>Worker</th><th>Status</th><th>Due</th><th>Overdue</th></tr>"""
    return f"""<div class='tbl-wrap'><table class='data'><thead>{header}</thead><tbody>{"".join(rows)}</tbody></table></div>"""


def worker_leaderboard_table(workers: pd.DataFrame, forms: pd.DataFrame,
                              sigs: pd.DataFrame, sched: pd.DataFrame) -> str:
    """HTML table: per-worker activity leaderboard."""
    df = D.worker_leaderboard(workers, forms, sigs, sched)
    if df.empty:
        return empty("No worker activity data yet")
    rows = []
    for _, r in df.iterrows():
        pct = r.get("CompletionPct", 0.0)
        pct_cls = "badge green" if pct >= 80 else ("badge warn" if pct >= 50 else "badge red")
        rows.append(f"""<tr>
            <td>{r['Worker']}</td>
            <td class='num'>{int(r['Forms'])}</td>
            <td class='num'>{int(r['Signatures'])}</td>
            <td class='num'>{int(r['Schedules'])}</td>
            <td><span class='{pct_cls}'>{pct:.0f}%</span></td>
        </tr>""")
    header = """<tr><th>Worker</th><th>Forms</th><th>Signatures</th><th>Schedules</th><th>Compliance</th></tr>"""
    return f"""<div class='tbl-wrap'><table class='data'><thead>{header}</thead><tbody>{"".join(rows)}</tbody></table></div>"""


def form_category_chart(forms: pd.DataFrame) -> str:
    """Donut chart: form submissions grouped by category."""
    df = D.form_categories(forms)
    if df.empty:
        return empty("No form data to categorize")
    colors = {"JSA / Hazard Assessment": "#2563eb",
              "Inspection / Audit": "#0e7490",
              "Incident / Near Miss": "#dc2626",
              "Training / Orientation": "#16a34a",
              "Other": "#94a3b8"}
    markers = [colors.get(c, "#94a3b8") for c in df["Category"]]
    fig = go.Figure(go.Pie(labels=df["Category"], values=df["Count"],
        hole=0.55, marker=dict(colors=markers, line=dict(color="white", width=1)),
        textinfo="label+percent"))
    fig.update_layout(showlegend=False)
    return render(_layout(fig, 280))


# ── BBSO & RIR Charts ───────────────────────────────────────────────────────


def bbso_trend(forms: pd.DataFrame) -> str:
    df = D.bbso_monthly_trend(forms)
    if df.empty:
        return empty("No BBSO data yet")
    df["Label"] = df["Month"].dt.strftime("%b")
    max_val = df["Count"].max() if not df.empty else 1
    fig = go.Figure(go.Bar(
        x=df["Label"], y=df["Count"],
        marker=dict(color="#7c3aed", line=dict(width=0)),
        hovertemplate="%{x} %{y} BBSOs<extra></extra>",
        text=df["Count"], textposition="outside", textfont=dict(size=11, color="#0f172a")))
    fig.update_layout(showlegend=False)
    fig.update_yaxes(gridcolor="#e2e8f0", showticklabels=False, showgrid=False,
                     range=[0, max_val * 1.25])
    fig.update_xaxes(gridcolor="#f1f5f9", tickfont=dict(size=11))
    return render(_layout(fig, 260))


def rir_trend(forms: pd.DataFrame) -> str:
    df = D.rir_monthly_trend(forms)
    if df.empty:
        return empty("No RIR data yet")
    df["Label"] = df["Month"].dt.strftime("%b")
    max_val = df["Count"].max() if not df.empty else 1
    fig = go.Figure(go.Bar(
        x=df["Label"], y=df["Count"],
        marker=dict(color="#ea580c", line=dict(width=0)),
        hovertemplate="%{x} %{y} RIRs<extra></extra>",
        text=df["Count"], textposition="outside", textfont=dict(size=11, color="#0f172a")))
    fig.update_layout(showlegend=False)
    fig.update_yaxes(gridcolor="#e2e8f0", showticklabels=False, showgrid=False,
                     range=[0, max_val * 1.25])
    fig.update_xaxes(gridcolor="#f1f5f9", tickfont=dict(size=11))
    return render(_layout(fig, 260))


def bbso_rir_leaderboard_table(workers: pd.DataFrame, forms: pd.DataFrame) -> str:
    df = D.bbso_rir_leaderboard(workers, forms)
    if df.empty:
        return empty("No BBSO or RIR data yet")
    rows = []
    for _, r in df.iterrows():
        eng = r["HSE_Engagement"]
        eng_cls = "badge green" if eng >= 2.0 else ("badge" if eng >= 1.0 else "badge red")
        rows.append(f"""<tr>
            <td>{r['Worker']}</td>
            <td class='num'>{int(r['BBSO'])}</td>
            <td class='num'>{int(r['RIR'])}</td>
            <td><span class='{eng_cls}'>{eng}</span></td>
        </tr>""")
    header = """<tr><th>Worker</th><th>BBSO</th><th>RIR</th><th>HSE Engagement</th></tr>"""
    return f"""<div class='tbl-wrap'><table class='data'><thead>{header}</thead><tbody>{"".join(rows)}</tbody></table></div>"""


# --------------------------------------------------------------------------- #
# Per-person safety profile tables
# --------------------------------------------------------------------------- #

def safety_profile_table(workers: pd.DataFrame, forms: pd.DataFrame) -> str:
    """Raw BBSO vs RIR per-person numbers. Click a count to see the forms."""
    df = D.bbso_rir_safety_profile(workers, forms)
    if df.empty:
        return empty("No person-level safety data yet")

    rows = []
    for _, r in df.iterrows():
        wid = r["WorkerId"]
        name = r["Worker"]
        role = r["Role"]
        bbso_count = int(r["BBSOs"])
        rir_count = int(r["RIRs"])
        bbso_link = f"<span class='num-link' style='cursor:pointer' hx-trigger='click' hx-get='/_sd_person_forms?worker_id={wid}&type=bbso' hx-target='#person-forms-panel' hx-swap='innerHTML'>{bbso_count}</span>" if bbso_count > 0 else "<span class='badge'>0</span>"
        rir_link = f"<span class='num-link warn' style='cursor:pointer' hx-trigger='click' hx-get='/_sd_person_forms?worker_id={wid}&type=rir' hx-target='#person-forms-panel' hx-swap='innerHTML'>{rir_count}</span>" if rir_count > 0 else "<span class='badge'>0</span>"
        rows.append(f"""<tr>
            <td>{name}<br><span class='note'>{role}</span></td>
            <td class='num'>{bbso_link}</td>
            <td class='num'>{rir_link}</td>
        </tr>""")
    header = """<tr><th>Worker</th><th class='num'>BBSOs</th><th class='num'>RIRs</th></tr>"""
    panel = f"""<div id='person-forms-panel' class='mt'></div>"""
    return f"""<div class='tbl-wrap'><table class='data'><thead>{header}</thead><tbody>{"".join(rows)}
    </tbody></table></div>{panel}"""


def observer_leaderboard_table(workers: pd.DataFrame, forms: pd.DataFrame) -> str:
    """Who's doing BBSO observations — sorted by most observations submitted."""
    df = D.bbso_observer_leaderboard(workers, forms)
    if df.empty:
        return empty("No BBSO observations recorded yet")
    rows = []
    for _, r in df.iterrows():
        name = r["Worker"]
        bbso_count = int(r["BBSOs"])
        last = r["LastObservation"]
        cls = "badge green" if bbso_count >= 5 else ("badge" if bbso_count >= 2 else "badge warn")
        rows.append(f"""<tr>
            <td>{name}<br><span class='note'>{r['Role']}</span></td>
            <td class='num'><span class='{cls}'>{bbso_count}</span></td>
            <td>{last}</td>
        </tr>""")
    header = """<tr><th>Observer</th><th class='num'>BBSOs Done</th><th>Last</th></tr>"""
    return f"""<div class='tbl-wrap'><table class='data'><thead>{header}</thead><tbody>{"".join(rows)}</tbody></table></div>"""


def reporter_leaderboard_table(workers: pd.DataFrame, forms: pd.DataFrame) -> str:
    """Who's reporting RIRs / Near Misses — sorted by most reports."""
    df = D.rir_reporter_leaderboard(workers, forms)
    if df.empty:
        return empty("No RIR/Near Miss reports recorded yet")
    rows = []
    for _, r in df.iterrows():
        name = r["Worker"]
        rir_count = int(r["RIRs"])
        last = r["LastReport"]
        cls = "badge warn" if rir_count >= 3 else "badge"
        rows.append(f"""<tr>
            <td>{name}<br><span class='note'>{r['Role']}</span></td>
            <td class='num'><span class='{cls}'>{rir_count}</span></td>
            <td>{last}</td>
        </tr>""")
    header = """<tr><th>Reporter</th><th class='num'>RIRs / Near Misses</th><th>Last</th></tr>"""
    return f"""<div class='tbl-wrap'><table class='data'><thead>{header}</thead><tbody>{"".join(rows)}</tbody></table></div>"""


# --------------------------------------------------------------------------- #
# RIR / Near Miss events directly from clean forms metadata
# --------------------------------------------------------------------------- #


def rir_events_from_forms(forms: pd.DataFrame, workers: pd.DataFrame,
                           incidents: pd.DataFrame | None = None,
                           locations: pd.DataFrame | None = None) -> str:
    """RIR/Near Miss events built from clean metadata tables — no form_responses needed.

    Uses sitedocs_forms (metadata) and sitedocs_incidents tables which have clean data.
    Falls back to incidents table for additional detail.
    """
    # Resolve worker names
    wm = {str(w["Id"]): f"{w.get('FirstName','')} {w.get('LastName','')}".strip()
          for _, w in workers.iterrows()}
    lm = {}
    if locations is not None and not locations.empty:
        lm = {str(loc["Id"]): str(loc.get("Name", "")) for _, loc in locations.iterrows()}

    # Filter forms to RIR/Near Miss types
    from data.sd_data import _filter_rir
    rir_forms = _filter_rir(forms).copy()
    if rir_forms.empty:
        # Fallback: filter by DocumentTemplateName
        rir_forms = forms[forms["DocumentTemplateName"].str.contains("RIR|Near Miss", na=False)].copy()

    if rir_forms.empty and (incidents is None or incidents.empty):
        return empty("No RIR/Near Miss events recorded")

    rows = []

    # From forms metadata
    if not rir_forms.empty:
        date_col = "CreatedOn" if "CreatedOn" in rir_forms.columns else "createdOn"
        if date_col in rir_forms.columns:
            rir_forms[date_col] = pd.to_datetime(rir_forms[date_col], errors="coerce")
            rir_forms = rir_forms.sort_values(date_col, ascending=False)

        for _, r in rir_forms.head(10).iterrows():
            created_by = str(r.get("CreatedBy", ""))
            dt = str(r.get(date_col, ""))[:10] if date_col in r else ""
            name = r.get("Label", r.get("DocumentTemplateName", ""))
            loc_id = str(r.get("LocationId", ""))
            loc_name = lm.get(loc_id, "") if loc_id else ""
            worker = wm.get(created_by, created_by[:12]) if created_by else ""
            rows.append(f"""<tr>
                <td>{worker}</td>
                <td>{dt}</td>
                <td>{name[:60]}</td>
                <td><span class='badge'>—</span></td>
                <td>—</td>
                <td>—</td>
            </tr>""")

    # From incidents table (additional detail)
    if incidents is not None and not incidents.empty:
        inc = incidents.copy()
        if "CreatedOn" in inc.columns:
            inc["CreatedOn"] = pd.to_datetime(inc["CreatedOn"], errors="coerce")
            inc = inc.sort_values("CreatedOn", ascending=False)
        for _, r in inc.head(5).iterrows():
            desc = r.get("Name", r.get("Description", ""))
            status = str(r.get("LatestStatus", ""))
            created_by = str(r.get("CreatedBy", "")) if "CreatedBy" in r else ""
            worker = wm.get(created_by, created_by[:12]) if created_by else ""
            dt = str(r.get("CreatedOn", ""))[:10] if "CreatedOn" in r else ""
            status_cls = "badge red" if status.lower() in ("open", "investigation") else "badge green"
            rows.append(f"""<tr>
                <td>{worker}</td>
                <td>{dt}</td>
                <td>{desc[:60]}</td>
                <td><span class='{status_cls}'>{status[:15]}</span></td>
                <td>—</td>
                <td>—</td>
            </tr>""")

    if not rows:
        return empty("No events to display")

    header = """<tr><th>Reporter</th><th>Date</th><th>Event</th><th>Status</th><th>Root Cause</th><th>Action</th></tr>"""
    return f"""<div class='tbl-wrap'><table class='data'><thead>{header}</thead><tbody>{"".join(rows)}</tbody></table></div>"""
