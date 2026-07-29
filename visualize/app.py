"""EWS Unified Dashboard — FastHTML multi-platform executive dashboard.

Serves QuickBooks, SiteDocs, and GeoTab data in a single HTMX-driven interface.
Based on the eww-dashboard-public architecture, extended for all three platforms.
"""

from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo
    _HOUSTON = ZoneInfo("America/Chicago")
except Exception:
    _HOUSTON = timezone.utc
from hashlib import pbkdf2_hmac
from hmac import compare_digest
from os import getenv
from urllib.parse import parse_qs, urlencode

import pandas as pd
from fasthtml.common import *

# Check if running in production (fasthtml package available)
try:
    import charts as C
    import data as D
except ImportError:
    from visualize import charts as C
    from visualize import data as D

from data import qb_data as QB
from data import sd_data as SD
from data import gt_data as GT
from data import issues as ISS

# ── App + Styles ─────────────────────────────────────────────────────

PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"

STYLE = Style("""
:root {
  --navy: #0a1f33; --navy-2: #0d2840; --page: #eef2f7; --card: #ffffff;
  --ink: #0f172a; --muted: #64748b; --line: #e2e8f0; --accent: #2563eb;
  --good: #16a34a; --bad: #dc2626; --warn: #ea580c;
}
* { box-sizing: border-box; }
body { margin: 0; font-family: Inter, system-ui, -apple-system, sans-serif;
       background: var(--page); color: var(--ink); }
.layout { display: flex; min-height: 100vh; }

/* Sidebar */
.sidebar { width: 232px; flex: 0 0 232px; background: var(--navy); color: #e8eef5;
           display: flex; flex-direction: column; padding: 22px 14px; }
.brand { display: flex; align-items: center; gap: 10px; padding: 6px 8px 20px; }
.brand .mark { font-size: 22px; }
.brand .name { font-weight: 800; font-size: 14px; line-height: 1.15; letter-spacing: .04em; }
.brand .name small { display:block; font-weight:600; font-size:10px; color:#7e93a8; letter-spacing:.14em; }
.nav { display: flex; flex-direction: column; gap: 4px; margin-top: 8px; }
.nav a { display: flex; align-items: center; gap: 11px; padding: 10px 12px; border-radius: 10px;
         color: #b8c6d6; text-decoration: none; font-size: 14px; font-weight: 500; cursor: pointer; }
.nav a:hover { background: var(--navy-2); color: #fff; }
.nav a.active { background: var(--accent); color: #fff; }
.sidebar .foot { margin-top: auto; font-size: 11px; color: #64788f; padding: 8px; }

/* Main */
.main { flex: 1; min-width: 0; padding: 22px 26px 40px; }
.header { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px; }
.header h1 { margin: 0; font-size: 26px; font-weight: 800; }
.header .crumbs { color: var(--muted); font-size: 13px; margin-top: 4px; }
.header .refreshed { text-align: right; color: var(--muted); font-size: 12px; }
.header .refreshed .pill { display:inline-block; background:#fff; border:1px solid var(--line);
        border-radius: 20px; padding: 6px 12px; font-weight:600; color:var(--ink); }

/* Controls */
.controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
            background:#fff; border:1px solid var(--line); border-radius: 14px; padding: 12px 14px; margin: 16px 0 14px; }
.controls .lbl { font-size: 12px; font-weight:600; color: var(--muted); margin-right: 4px; }
.preset { border: 1px solid var(--line); background:#f8fafc; color: var(--ink); border-radius: 999px;
          padding: 7px 14px; font-size: 13px; cursor: pointer; font-weight: 500; }
.preset:hover { border-color: var(--accent); color: var(--accent); }
.preset.active { background: var(--accent); border-color: var(--accent); color: #fff; }
.controls .spacer { flex: 1; }
.controls input[type=date] { border:1px solid var(--line); border-radius: 8px; padding: 6px 8px; font-size: 13px; color: var(--ink); }
.controls .apply { background: var(--navy); color:#fff; border:none; border-radius: 8px; padding: 7px 14px; font-size:13px; cursor:pointer; font-weight:600; }
.controls .apply:hover { background: var(--navy-2); }

/* KPI cards */
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(176px, 1fr)); gap: 14px; margin-bottom: 20px; }
.kpi { background: var(--card); border:1px solid var(--line); border-radius: 16px; padding: 16px 18px;
       text-decoration: none; color: inherit; transition: box-shadow .15s, transform .15s, border-color .15s; }
a.kpi { cursor: pointer; }
a.kpi:hover { box-shadow: 0 12px 26px rgba(15,23,42,.10); transform: translateY(-2px); }
.kpi.active { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(37,99,235,.25); }
.kpi .k-label { color: var(--muted); font-size: 13px; font-weight: 600; }
.kpi .k-value { font-size: 28px; font-weight: 800; margin: 6px 0 4px; }
.kpi .k-delta { font-size: 12.5px; font-weight: 600; }
.kpi .k-delta.up { color: var(--good); } .kpi .k-delta.down { color: var(--bad); } .kpi .k-delta.flat { color: var(--muted); }
.kpi .k-hint { color:#94a3b8; font-size: 11px; margin-top:6px; }

/* KPI tooltips */
.k-tip-icon { display:inline-block; margin-left:5px; font-size:14px; color:#94a3b8; cursor:help; position:relative; }
.k-tip-icon:hover::after { content:attr(title); position:absolute; left:50%; transform:translateX(-50%);
   bottom:calc(100% + 8px); background:#0f172a; color:#f1f5f9; font-size:12px; font-weight:400;
   padding:8px 10px; border-radius:8px; white-space:normal; width:220px; max-width:min(220px,90vw);
   z-index:100; line-height:1.4; box-shadow:0 4px 12px rgba(0,0,0,.18); pointer-events:none; }
.k-tip-icon:hover::before { content:""; position:absolute; left:50%; transform:translateX(-50%);
   bottom:calc(100% + 4px); border:4px solid transparent; border-top-color:#0f172a; z-index:101; pointer-events:none; }

/* Panels */
.grid { display: grid; gap: 16px; }
.grid.two { grid-template-columns: 1fr 1fr; }
.grid.even { grid-template-columns: 1fr 1fr; }
.panel { background: var(--card); border:1px solid var(--line); border-radius: 16px; padding: 16px 18px; min-width: 0; }
.panel h3 { margin: 0 0 12px; font-size: 14px; font-weight: 700; display:flex; align-items:center; gap:8px; }
.panel h3 .dot { width:9px; height:9px; border-radius: 3px; display:inline-block; }
.chart-empty { display:flex; align-items:center; justify-content:center; height: 280px; color: var(--muted);
               border: 1px dashed var(--line); border-radius: 12px; font-size: 13px; }
.mt { margin-top: 16px; }

/* Tables */
.tbl-wrap { overflow-x: auto; }
table.data { width: 100%; border-collapse: collapse; font-size: 13px; }
table.data th { text-align: left; color: var(--muted); font-weight: 600; padding: 8px 10px; border-bottom: 2px solid var(--line); white-space: nowrap; }
table.data td { padding: 8px 10px; border-bottom: 1px solid #f1f5f9; white-space: nowrap; }
table.data td.num, table.data th.num { text-align: right; }
.badge { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px; background:#e2e8f0; color:#475569; }
.badge.red { background:#fee2e2; color:#b91c1c; } .badge.green { background:#dcfce7; color:#15803d; }
.note { color: var(--muted); font-size: 12px; }

/* RAG dots */
.kpi-rag { display:inline-block; width:7px; height:7px; border-radius:50%; margin-right:3px; flex-shrink:0; }

/* Print */
@media print {
  body { background: #fff; }
  .sidebar, .controls, .header .refreshed, .header .crumbs { display: none !important; }
  .main { padding: 0 !important; }
  .kpi { border: 1px solid #ccc; break-inside: avoid; }
  .panel { border: 1px solid #ccc; break-inside: avoid; }
}
""")

app, rt = fast_app(
    pico=False,
    hdrs=(
        Meta(name="viewport", content="width=device-width, initial-scale=1"),
        Link(rel="preconnect", href="https://fonts.googleapis.com"),
        Link(rel="stylesheet",
             href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap"),
        Script(src=PLOTLY_CDN),
        STYLE,
    ),
    secret_key=getenv("FASTHTML_SECRET_KEY", "please-change-this-secret"),
)

# ── State helpers ────────────────────────────────────────────────────

PLATFORMS = [
    ("qb", "QuickBooks", "📊", [
        ("overview", "Overview", "▦"), ("sales", "Sales", "📈"),
        ("finance", "Finance", "💲"), ("profitability", "Profitability", "💹"),
        ("customers", "Customers", "👥"), ("accounts", "Accounts", "🏦"),
    ]),
    ("sd", "SiteDocs", "🛡️", [
        ("hse", "HSE Overview", "🛡️"), ("forms", "Forms & JSAs", "📋"),
        ("compliance", "Compliance", "✅"), ("workers", "Workers", "👷"),
    ]),
    ("gt", "GeoTab", "🚛", [
        ("fleet", "Fleet Overview", "📊"), ("maintenance", "Maintenance", "🔧"),
    ]),
]

SWAP = dict(hx_target="#app", hx_swap="outerHTML", hx_indicator="#loading")

RANGE_PRESETS = [
    ("ytd", "Year to date"), ("last_month", "Last month"),
    ("last_quarter", "Last quarter"), ("last_year", "Last year"),
    ("custom", "Custom"),
]


def get_state(req) -> dict:
    q = req.query_params
    return {
        "platform": q.get("platform", ""),
        "section": q.get("section", ""),
        "range": q.get("range", "ytd"),
        "start": q.get("start", ""),
        "end": q.get("end", ""),
        "compare": q.get("compare", "0"),
        "basis": q.get("basis", "accrual"),
        "waterfall": q.get("waterfall", ""),
    }


def url(state: dict, **over) -> str:
    return "/view?" + urlencode({**state, **over})


# ── Auth ─────────────────────────────────────────────────────────────

AUTH_LOGIN_DOMAIN = getenv("DASHBOARD_LOGIN_DOMAIN", "energywatersolutions.com").strip().lower()
AUTH_PASSWORD = getenv("DASHBOARD_LOGIN_PASSWORD")
AUTH_PASSWORD_HASH = getenv("DASHBOARD_LOGIN_PASSWORD_HASH", "").strip()


def _password_hash(password: str) -> str:
    digest = pbkdf2_hmac("sha256", password.encode("utf-8"), b"fasthtml-dashboard", 120_000)
    return digest.hex()


def verify_password(password: str) -> bool:
    if AUTH_PASSWORD_HASH:
        return compare_digest(_password_hash(password), AUTH_PASSWORD_HASH)
    return compare_digest(password, AUTH_PASSWORD)


def email_allowed(email: str) -> bool:
    return email.strip().lower().endswith(f"@{AUTH_LOGIN_DOMAIN}") if email else False


def user_is_authenticated(req) -> bool:
    try:
        return bool(req.session.get("user"))
    except AssertionError:
        return False


def require_login(req):
    if user_is_authenticated(req):
        return None
    next_url = str(req.url.path)
    if req.url.query:
        next_url += f"?{req.url.query}"
    return Redirect(f"/login?{urlencode({'next': next_url})}")


def parse_form(body: bytes) -> dict[str, str]:
    raw = parse_qs(body.decode("utf-8", errors="ignore"))
    return {k: v[0] for k, v in raw.items() if v}


# ── Range resolution ─────────────────────────────────────────────────

def resolve_range(state: dict, qb_ds=None) -> tuple:
    today = datetime.now(_HOUSTON).date()
    range_key = state.get("range", "ytd")

    if range_key == "ytd":
        end = date(today.year, today.month, 1) - timedelta(days=1)
        lbl = f"Year to date (Jan–{end.strftime('%b %Y')})"
        return date(today.year, 1, 1), end, lbl
    if range_key == "last_month":
        first = date(today.year, today.month, 1)
        end = first - timedelta(days=1)
        start = date(end.year, end.month, 1)
        return start, end, end.strftime("%B %Y")
    if range_key == "last_quarter":
        q_start_m = ((today.month - 1) // 3) * 3 + 1
        q_start = date(today.year, q_start_m, 1)
        end = q_start - timedelta(days=1)
        prev_q = (end.month - 1) // 3
        start = date(end.year, prev_q * 3 + 1, 1)
        return start, end, f"Q{prev_q + 1} {end.year}"
    if range_key == "last_year":
        y = today.year - 1
        return date(y, 1, 1), date(y, 12, 31), str(y)
    if range_key == "custom":
        try:
            s = date.fromisoformat(state.get("start", "")) if state.get("start") else date(2020, 1, 1)
        except ValueError:
            s = date(2020, 1, 1)
        try:
            e = date.fromisoformat(state.get("end", "")) if state.get("end") else today
        except ValueError:
            e = today
        if e < s:
            s, e = e, s
        return s, e, f"{s.isoformat()} → {e.isoformat()}"
    return date(2020, 1, 1), today, "All time"


# ── Formatting helpers ───────────────────────────────────────────────

def _abbrev_money(v) -> str:
    n = abs(v)
    sign = "-" if v < 0 else ""
    if n >= 1e6: return f"{sign}${n / 1e6:,.2f}M"
    if n >= 1e3: return f"{sign}${n / 1e3:,.1f}K"
    return f"{sign}${n:,.0f}"


def _fmt_val(value, unit=""):
    if isinstance(value, (int, float)):
        if unit == "$": return _abbrev_money(value)
        if unit == "%": return f"{value:,.1f}%"
        if unit == "days": return f"{value:,.0f} days"
        if unit == ":1": return f"{value:,.1f}:1"
        if float(value).is_integer(): return f"{int(value):,}"
        return f"{value:,.2f}"
    return str(value)


_rag = {"green": "#16a34a", "amber": "#ea580c", "red": "#dc2626"}


# ── KPI cards ────────────────────────────────────────────────────────

def rag_for_value(v, green, amber, good_when_high=True):
    if good_when_high:
        if v >= green: return "green"
        if v >= amber: return "amber"
        return "red"
    if v <= green: return "green"
    if v <= amber: return "amber"
    return "red"


def delta_chip(delta, delta_up_good, comp_label="vs. prior period"):
    if delta is None:
        return Div("— no comparison", cls="k-delta flat")
    up = delta >= 0
    good = up if delta_up_good else not up
    arrow = "▲" if up else "▼"
    return Div(f"{arrow} {abs(delta):.1f}% {comp_label}", cls=f"k-delta {'up' if good else 'down'}")


def kpi_card(label, value, unit="", hint="", rag=None, delta=None, delta_up_good=True,
             help_text="", delta_label=""):
    r = [Div(
        label,
        Span("ⓘ", cls="k-tip-icon", title=help_text) if help_text else "",
        cls="k-label",
    )]
    if rag:
        r[0] = Div(Span(cls="kpi-rag", style=f"background:{_rag.get(rag,_rag['amber'])}"), label,
                   Span("ⓘ", cls="k-tip-icon", title=help_text) if help_text else "", cls="k-label")
    r.append(Div(_fmt_val(value, unit), cls="k-value"))
    if delta is not None:
        r.append(delta_chip(delta, delta_up_good, delta_label))
    if hint:
        r.append(Div(hint, cls="k-hint"))
    return Div(*r, cls="kpi")


# ── Controls ─────────────────────────────────────────────────────────

def controls(state: dict, qb_ds=None):
    preset_btns = []
    for key, label in RANGE_PRESETS:
        if key == "custom":
            continue
        active = "active" if state["range"] == key else ""
        preset_btns.append(Button(label, cls=f"preset {active}", hx_get=url(state, range=key), **SWAP))

    custom_active = "active" if state["range"] == "custom" else ""
    custom = [
        Span("Custom:", cls="lbl"),
        Input(type="date", name="start", value=state.get("start", ""), id="f-start"),
        Span("→", cls="lbl"),
        Input(type="date", name="end", value=state.get("end", ""), id="f-end"),
        Button("Apply", cls=f"apply {custom_active}", hx_get=url(state, range="custom"),
               hx_include="#f-start,#f-end", **SWAP),
    ]
    return Div(Span("Range:", cls="lbl"), *preset_btns, Span(cls="spacer"), *custom, cls="controls")


def compare_toggle(state: dict):
    comp = state.get("compare", "0")
    active = "active" if comp == "1" else ""
    return Button(f"{'◉' if comp == '1' else '○'} Compare",
                  cls=f"preset {active}",
                  hx_get=url(state, compare="0" if comp == "1" else "1"), **SWAP)


# ── Panels ────────────────────────────────────────────────────────────

def panel(title: str, body, dot_color: str = "#2563eb"):
    return Div(H3(Span(cls="dot", style=f"background:{dot_color}"), title),
               NotStr(body) if isinstance(body, str) else body, cls="panel")


# ── SD Section Bodies ─────────────────────────────────────────────────

def sd_hse_body(ds):
    sched_c = SD.schedule_counts(ds.schedules)
    brc = SD.bbso_rir_counts(ds.forms)
    bir = SD.bbso_incident_ratio(ds.forms, ds.incidents)
    rir_ratio = SD.rir_incident_ratio(ds.forms, ds.incidents)
    close_time = SD.incident_close_time(ds.incidents)
    part = SD.worker_participation(ds.workers, ds.forms)

    kpis = [
        kpi_card("Schedule Compliance", sched_c["completion_pct"], "%",
                 rag=rag_for_value(sched_c["completion_pct"], 80, 60),
                 help_text="Percentage of scheduled safety forms completed on time"),
        kpi_card("Overdue Items", sched_c["overdue"],
                 rag=rag_for_value(sched_c["overdue"], 5, 15, False),
                 help_text="Schedule items past their due date"),
        kpi_card("BBSO Observations", brc["total_bbso"],
                 hint=f"{brc['bbso_this_month']} this month · {brc['bbso_contributors']} observers",
                 help_text="Behavior-based safety observations track proactive safety engagement"),
        kpi_card("RIR / Near Miss Reports", brc["total_rir"],
                 hint=f"{brc['rir_this_month']} this month · {brc['rir_contributors']} reporters",
                 help_text="Recordable incident and near-miss reports"),
        kpi_card("Worker Participation", part["pct"], "%",
                 rag=rag_for_value(part["pct"], 80, 60),
                 help_text="Percent of active workers who submitted safety forms this month"),
        kpi_card("BBSO:Incident Ratio", bir["ratio"], ":1",
                 hint=f"{bir['total_bbso']} BBSO · {bir['total_incidents']} incidents",
                 rag=rag_for_value(bir["ratio"], 5, 2),
                 help_text="Proactive observations per incident. >5:1 = strong culture"),
        kpi_card("Reporting Culture Index", rir_ratio["ratio"], ":1",
                 hint=f"{rir_ratio['total_rir']} RIRs · {rir_ratio['total_incidents']} incidents",
                 rag=rag_for_value(rir_ratio["ratio"], 5, 2),
                 help_text="Near-miss reports per incident. High = people report hazards"),
        kpi_card("Avg Close Time", close_time["mean_days"], "days",
                 hint=f"median {close_time['median_days']}d",
                 rag=rag_for_value(close_time["mean_days"], 14, 30, False),
                 help_text="Mean days to close an incident. <14 days is excellent"),
    ]

    charts = Div(
        Div(panel("Monthly BBSO Trend", C.bbso_trend(ds.forms)),
            panel("Monthly RIR Trend", C.rir_trend(ds.forms)), cls="grid two"),
        Div(panel("Safety Profile", C.safety_profile_table(ds.workers, ds.forms)),
            panel("BBSO Risk by Category", C.bbso_risk_heatmap(ds.forms, ds.form_responses)),
            cls="grid two mt"),
        Div(panel("Top BBSO Observers", C.observer_leaderboard_table(ds.workers, ds.forms)),
            panel("Top RIR Reporters", C.reporter_leaderboard_table(ds.workers, ds.forms)),
            cls="grid two mt"),
        Div(panel("Schedule Compliance", C.schedule_compliance(ds.schedules)),
            panel("Forms by Category", C.form_category_chart(ds.forms)), cls="grid two mt"),
    )

    if hasattr(ds, 'form_responses') and not ds.form_responses.empty:
        charts = Div(charts, Div(panel("Recent RIR Events",
                    C.rir_events_from_forms(ds.forms, ds.workers, ds.incidents, ds.locations)),
                    cls="grid mt"))

    return Div(Div(*kpis, cls="kpis"), charts)


def sd_forms_body(ds):
    f_count = SD.form_counts(ds.forms)
    w_count = SD.worker_counts(ds.workers)
    brc = SD.bbso_rir_counts(ds.forms)

    kpis = [
        kpi_card("Total Forms", f_count["total"]),
        kpi_card("This Month", f_count["month"]),
        kpi_card("BBSO", brc["total_bbso"], hint=f"{brc['bbso_this_month']} this month"),
        kpi_card("RIR / Near Miss", brc["total_rir"], hint=f"{brc['rir_this_month']} this month"),
        kpi_card("Active Workers", w_count["active"]),
    ]

    return Div(
        Div(*kpis, cls="kpis"),
        Div(panel("Forms by Category", C.form_category_chart(ds.forms)),
            panel("Forms Monthly Trend", C.forms_trend(ds.forms)), cls="grid two"),
        Div(panel("BBSO Monthly Trend", C.bbso_trend(ds.forms)),
            panel("RIR Monthly Trend", C.rir_trend(ds.forms)), cls="grid two mt"),
        Div(panel("Forms by Type", C.form_types_chart(ds.formtypes, ds.forms)), cls="grid mt"),
    )


def sd_compliance_body(ds):
    sched_c = SD.schedule_counts(ds.schedules)
    brc = SD.bbso_rir_counts(ds.forms)

    kpis = [
        kpi_card("Completion Rate", sched_c["completion_pct"], "%",
                 rag=rag_for_value(sched_c["completion_pct"], 80, 60)),
        kpi_card("Overdue", sched_c["overdue"],
                 rag=rag_for_value(sched_c["overdue"], 5, 15, False)),
        kpi_card("Late", sched_c["late"]),
        kpi_card("Cancelled", sched_c["cancelled"]),
        kpi_card("BBSO This Month", brc["bbso_this_month"], hint=f"{brc['total_bbso']} total"),
        kpi_card("RIR This Month", brc["rir_this_month"], hint=f"{brc['total_rir']} total"),
    ]

    return Div(
        Div(*kpis, cls="kpis"),
        Div(panel("Schedule Compliance", C.schedule_compliance(ds.schedules)),
            panel("BBSO Monthly Trend", C.bbso_trend(ds.forms)), cls="grid two"),
        Div(panel("Overdue & Late Items", C.overdue_items_list(ds.schedules)),
            panel("BBSO & RIR by Worker", C.bbso_rir_leaderboard_table(ds.workers, ds.forms)),
            cls="grid two mt"),
    )


def sd_workers_body(ds):
    w_count = SD.worker_counts(ds.workers)
    part = SD.worker_participation(ds.workers, ds.forms)
    brc = SD.bbso_rir_counts(ds.forms)

    kpis = [
        kpi_card("Active Workers", w_count["active"], hint=f"of {w_count['total']} total"),
        kpi_card("Contractors", w_count["contractors"], hint=f"{w_count['employees']} employees"),
        kpi_card("Participation", part["pct"], "%",
                 rag=rag_for_value(part["pct"], 80, 60)),
        kpi_card("BBSO Contributors", brc["bbso_contributors"]),
        kpi_card("RIR Contributors", brc["rir_contributors"]),
    ]

    return Div(
        Div(*kpis, cls="kpis"),
        Div(panel("Active vs Inactive", C.worker_status(ds.workers)),
            panel("Employee vs Contractor", C.worker_type_split(ds.workers)), cls="grid two"),
        Div(panel("BBSO & RIR by Worker", C.bbso_rir_leaderboard_table(ds.workers, ds.forms)),
            cls="grid mt"),
    )


# ── GT Section Bodies ─────────────────────────────────────────────────

def gt_fleet_body(since, until, state):
    s = GT.fleet_summary(since, until)
    tr = GT.daily_trends(since, until)
    ut = GT.vehicle_utilization(since, until)
    il = GT.idling_summary(since, until)
    ic = GT.idling_cost(since, until)
    sb = GT.seatbelt_analysis(since, until)
    ah = GT.after_hours_analysis(since, until)
    sd_rank = GT.safety_driver_rankings(since, until)

    total_trips = sum(r.get("trips", 0) for r in tr) if tr else 0
    total_hrs = sum(u["hours_driven"] for u in ut) if ut else 0

    kpis = [
        kpi_card("Active Vehicles", s["active_vehicles"],
                 hint=f"of {s['total_vehicles']}",
                 help_text="Vehicles with trips in the selected period"),
        kpi_card("Fleet Miles", round(s["total_fleet_miles"], 0),
                 help_text="Total miles driven by all vehicles"),
        kpi_card("Total Trips", total_trips),
        kpi_card("Drive Hours", round(total_hrs)),
        kpi_card("Idle Cost", round(ic["estimated_cost"]), "$",
                 hint=f"{ic['total_idle_hours']} hrs · ${ic['cost_per_hour']:.0f}/hr",
                 help_text="Estimated fuel + maintenance cost of idle time at $5/hr"),
    ]

    panels = []

    # Mileage trend
    if tr and sum(r.get("mileage", 0) for r in tr) > 0:
        def _rgba(h, a):
            h = h.lstrip("#")
            return f"rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{a})"
        df = pd.DataFrame(tr).sort_values("day")
        df["d"] = pd.to_datetime(df["day"])
        f = go.Figure()
        f.add_trace(go.Scatter(x=df["d"], y=df["mileage"].rolling(7, min_periods=1).mean(),
                    mode="lines", line=dict(color="#2563eb", width=2.5, shape="spline"),
                    name="7-day avg"))
        f.add_trace(go.Bar(x=df["d"], y=df["mileage"],
                    marker=dict(color="rgba(37,99,235,0.25)"), name="Daily"))
        f.update_layout(showlegend=True, legend=dict(orientation="h", y=1.1, font=dict(size=9)),
                       height=350, margin=dict(l=10, r=10, t=5, b=10),
                       paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                       font=dict(family="Inter, system-ui, sans-serif", size=11),
                       yaxis=dict(gridcolor="#e2e8f0"), xaxis=dict(gridcolor="#f1f5f9"))
        panels.append(panel("Daily Mileage Trend",
                     NotStr(f.to_html(include_plotlyjs=False, full_html=False,
                            config={"displayModeBar": False, "responsive": True}))))

    # Seatbelt
    if sb:
        sbd = pd.DataFrame(sb)
        sb_off = sbd["seatbelt_off"].sum()
        sb_on = sbd["seatbelt_on"].sum()
        if sb_off + sb_on > 0:
            sbd["d"] = pd.to_datetime(sbd["day"])
            f2 = go.Figure()
            f2.add_trace(go.Bar(x=sbd["d"], y=sbd["seatbelt_off"], name="No Belt",
                         marker=dict(color="#dc2626")))
            f2.add_trace(go.Bar(x=sbd["d"], y=sbd["seatbelt_on"], name="Belt On",
                         marker=dict(color="#16a34a")))
            f2.update_layout(barmode="stack", showlegend=True,
                            legend=dict(orientation="h", y=1.1, font=dict(size=9)),
                            height=300, margin=dict(l=10, r=10, t=5, b=10),
                            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                            font=dict(family="Inter, system-ui, sans-serif", size=11))
            panels.append(panel("Seatbelt Violations",
                         NotStr(f2.to_html(include_plotlyjs=False, full_html=False,
                                config={"displayModeBar": False, "responsive": True}))))

    # Driver scores
    if sd_rank:
        active = [d for d in sd_rank if d["trip_count"] > 0][:15]
        if active:
            colors = ["#16a34a" if s["score"] >= 80 else "#ea580c" if s["score"] >= 60 else "#dc2626"
                     for s in active]
            f3 = go.Figure(go.Bar(x=[d["score"] for d in active], y=[d["name"] for d in active],
                           orientation="h", marker=dict(color=colors)))
            f3.update_layout(height=350, xaxis=dict(range=[0, 100]), yaxis=dict(autorange="reversed"),
                            margin=dict(l=10, r=10, t=5, b=10),
                            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                            font=dict(family="Inter, system-ui, sans-serif", size=11))
            panels.append(panel("Driver Safety Scores",
                         NotStr(f3.to_html(include_plotlyjs=False, full_html=False,
                                config={"displayModeBar": False, "responsive": True}))))

    return Div(
        Div(*kpis, cls="kpis"),
        Div(*panels[:2], cls="grid two") if len(panels) >= 2 else Div(panels[0] if panels else "", cls="grid"),
        Div(*panels[2:3], cls="grid mt") if len(panels) > 2 else "",
    )


def gt_maintenance_body(since, until, state):
    mt = GT.vehicle_maintenance_status(since, until)
    fl = GT.maintenance_metrics(since, until)
    total_odo = sum(v.get("odo_mi", 0) for v in mt)

    kpis = [
        kpi_card("Vehicles Tracked", len(mt)),
        kpi_card("Total Odometer", round(total_odo)),
    ]

    panels = []
    active_mt = [v for v in mt if v.get("odo_mi", 0) > 0]
    if len(active_mt) >= 2:
        f = go.Figure(go.Bar(x=[v["odo_mi"] for v in active_mt],
                      y=[v["label"] for v in active_mt], orientation="h",
                      marker=dict(color="#2563eb")))
        f.update_layout(height=300, yaxis=dict(autorange="reversed"),
                       margin=dict(l=10, r=10, t=5, b=10),
                       paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                       font=dict(family="Inter, system-ui, sans-serif", size=11))
        panels.append(panel("Vehicle Odometer",
                     NotStr(f.to_html(include_plotlyjs=False, full_html=False,
                            config={"displayModeBar": False, "responsive": True}))))

    freq = fl.get("fault_frequency", []) if fl else []
    if len(freq) >= 2:
        f2 = go.Figure(go.Bar(x=[f["count"] for f in freq],
                        y=[f["fault_code"] for f in freq], orientation="h",
                        marker=dict(color="#dc2626")))
        f2.update_layout(height=300, yaxis=dict(autorange="reversed"),
                        margin=dict(l=10, r=10, t=5, b=10),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        font=dict(family="Inter, system-ui, sans-serif", size=11))
        panels.append(panel("Fault Frequency",
                     NotStr(f2.to_html(include_plotlyjs=False, full_html=False,
                            config={"displayModeBar": False, "responsive": True}))))

    return Div(Div(*kpis, cls="kpis"),
               Div(*panels, cls="grid two") if len(panels) >= 2 else "")


# ── QB Section Bodies ─────────────────────────────────────────────────

def qb_overview_body(ds, inv, start, end, state):
    return Div(
        Div(panel("Monthly Revenue Trend", C.trend(inv, "revenue")),
            panel("Revenue by Business Segment", C.revenue_by_class(inv), "#16a34a"),
            cls="grid two"),
        Div(panel("A/R Aging", C.ar_aging(inv), "#dc2626"),
            panel("Top Customers (Period Ranking)", C.class_period_ranking(inv, start, end)),
            cls="grid even mt"),
    )


def qb_sales_body(ds, inv, start, end, state):
    return Div(
        Div(panel("Monthly Revenue", C.trend(inv, "revenue")),
            panel("Revenue by Service / Product", C.revenue_by_item(inv), "#0e7490"),
            cls="grid two"),
        Div(panel("Customers: Current Period Ranking", C.class_period_ranking(inv, start, end), "#7c3aed"),
            panel("Customer Monthly Trend (Top 3)", C.revenue_by_customer_monthly(inv, start, end), "#7c3aed"),
            cls="grid two mt"),
        Div(panel("Revenue by Business Segment (Class)", C.revenue_by_class(inv), "#16a34a"),
            panel("Revenue by Location (City)", C.location_period_ranking(inv, start, end), "#0891b2"),
            cls="grid even mt"),
        Div(panel("Invoices in Range", invoice_table(inv)), cls="grid mt"),
    )


def qb_finance_body(ds, inv, start, end, state):
    return Div(
        Div(panel("Balance Sheet", C.balance_sheet(ds.accounts), "#0e7490"),
            panel("A/R Aging", C.ar_aging(inv), "#dc2626"),
            cls="grid even"),
        Div(panel("Monthly DSO Trend", C.dso_trend(inv, start, end), "#2563eb"), cls="grid mt"),
        Div(panel("Invoice Balance Status", C.balance_status(inv), "#16a34a"),
            panel("Assets by Type", C.accounts_by_type(ds.accounts), "#0e7490"),
            cls="grid even mt"),
    )


def qb_profitability_body(ds, inv, start, end, state):
    basis = state.get("basis", "accrual")
    summary = QB.pnl_summary(ds.pnl, basis, start, end)
    if ds.pnl.empty or summary.get("income", 0) == 0:
        return Div(basis_toggle(state),
                   Div(panel("Profit & Loss", "No P&L data yet — data lands on next scheduled refresh", "#2563eb"), cls="grid mt"))

    base_state = {k: v for k, v in state.items() if k != "waterfall"}
    drill_url = "/view?" + urlencode(base_state)
    return Div(
        basis_toggle(state),
        Div(panel("Profit & Loss Waterfall", NotStr(C.pnl_waterfall(summary)), "#2563eb"),
            panel(f"Income Statement ({basis})", pnl_statement(summary), "#0e7490"),
            cls="grid two mt"),
        Div(id="waterfall-drilldown", cls="drilldown-content", style="margin:12px 0; min-height:48px;"),
        Div(panel("Monthly P&L Trend", C.pnl_trend(ds.pnl, basis), "#16a34a"), cls="grid mt"),
        Div(panel("Top Expenses", C.pnl_expenses(ds.pnl_detail, basis, start, end), "#dc2626"),
            panel("Revenue by Class — Period Ranking", C.class_period_ranking(inv, start, end), "#16a34a"),
            cls="grid even mt"),
    )


def qb_customers_body(ds, inv, start, end, state):
    return Div(
        Div(panel("Current Period Ranking", C.class_period_ranking(inv, start, end)),
            panel("Monthly Trend (Top 3)", C.revenue_by_customer_monthly(inv, start, end), "#7c3aed"),
            cls="grid two"),
    )


def qb_accounts_body(ds, inv, start, end, state):
    return Div(
        Div(panel("Balances by Type", C.accounts_by_type(ds.accounts), "#0e7490"),
            panel("Balances by Classification", C.accounts_by_classification(ds.accounts), "#7c3aed"),
            cls="grid even"),
        Div(panel("Balance Sheet", C.balance_sheet(ds.accounts), "#0e7490"), cls="grid mt"),
    )


# ── Invoice table ───────────────────────────────────────────────────

def invoice_table(invoices, limit=30):
    df = invoices.sort_values(["TxnDate", "DocNumber"], ascending=[False, True]).head(limit)
    rows = []
    for _, r in df.iterrows():
        status = (Span("Overdue", cls="badge red") if r["Overdue"]
                  else Span("Paid", cls="badge green") if r["RevenueBalance"] <= 0
                  else Span("Open", cls="badge"))
        rows.append(Tr(
            Td(str(r["DocNumber"])),
            Td(r["TxnDate"].date().isoformat() if pd.notna(r["TxnDate"]) else "—"),
            Td(r["CustomerName"] or "—"),
            Td(_abbrev_money(r["Revenue"]), cls="num"),
            Td(_abbrev_money(r["RevenueBalance"]), cls="num"),
            Td(status),
        ))
    head = Tr(Th("Doc #"), Th("Date"), Th("Customer"), Th("Revenue", cls="num"),
              Th("Balance", cls="num"), Th("Status"))
    return Div(Table(Thead(head), Tbody(*rows), cls="data"), cls="tbl-wrap")


# ── P&L Helpers ────────────────────────────────────────────────────

def _signed_money(v):
    v = float(v) if pd.notna(v) else 0.0
    return f"-${abs(v):,.2f}" if v < 0 else f"${v:,.2f}"


def pnl_statement(summary):
    def row(label, value, *, total=False, pct=False, indent=False):
        txt = f"{value:,.1f}%" if pct else _signed_money(value)
        neg = (not pct and value < 0) or (pct and value < 0)
        td_style = "font-weight:700;" if total else ""
        if neg: td_style += "color: var(--bad);"
        label_cell = Td(label, style=("padding-left:24px; color:var(--muted);" if indent else
                                       ("font-weight:700;" if total else "")))
        tr_style = "border-top:2px solid var(--line);" if total else ""
        return Tr(label_cell, Td(txt, cls="num", style=td_style), style=tr_style)

    s = summary
    body = [
        row("Income", s["income"]),
        row("Cost of Goods Sold", -s["cogs"]),
        row("Gross Profit", s["gross_profit"], total=True),
        row("Gross Margin", s["gross_margin"], pct=True, indent=True),
        row("Operating Expenses", -s["expenses"]),
        row("Net Operating Income", s.get("net_operating_income", 0), total=True),
        row("Other Income", s.get("other_income", 0)),
        row("Other Expenses", -s.get("other_expenses", 0)),
        row("Net Income", s["net_income"], total=True),
        row("Net Margin", s["net_margin"], pct=True, indent=True),
    ]
    head = Tr(Th("Line item"), Th("Amount", cls="num"))
    return Div(Table(Thead(head), Tbody(*body), cls="data"), cls="tbl-wrap")


def basis_toggle(state):
    btns = []
    for key, label in [("accrual", "Accrual"), ("cash", "Cash")]:
        active = "active" if state.get("basis", "accrual").lower() == key else ""
        btns.append(Button(label, cls=f"preset {active}", hx_get=url(state, basis=key), **SWAP))
    return Div(
        Span("Accounting basis:", cls="lbl"), *btns,
        Span("QuickBooks Profit & Loss — your books", cls="note", style="margin-left:10px;"),
        cls="controls", style="margin-top:0;",
    )

PLATFORM_KPI_BUILDERS = {
    "qb": lambda ds, inv, start, end, state: [
        kpi_card("Revenue", ds.pnl["income"] if not ds.pnl.empty else inv["Revenue"].sum(), "$",
                 help_text="Revenue for the selected period"),
        kpi_card("Cash on Hand", ds.accounts["CurrentBalance"].sum(), "$" if ds.accounts["CurrentBalance"].sum() < 1e6 else "$"),
        kpi_card("Outstanding AR", inv.loc[inv["RevenueBalance"] > 0, "RevenueBalance"].sum(), "$",
                 help_text="Accounts receivable — invoiced but not yet collected"),
        kpi_card("Overdue", inv.loc[inv["Overdue"], "RevenueBalance"].sum(), "$",
                 help_text="Past-due receivables"),
        kpi_card("DSO", 0, "days"),  # placeholder
    ],
    "sd": lambda ds, inv, start, end, state: [
        kpi_card("Schedule Compliance", SD.schedule_counts(ds.schedules)["completion_pct"], "%",
                 rag=rag_for_value(SD.schedule_counts(ds.schedules)["completion_pct"], 80, 60)),
        kpi_card("Overdue Items", SD.schedule_counts(ds.schedules)["overdue"],
                 rag=rag_for_value(SD.schedule_counts(ds.schedules)["overdue"], 5, 15, False)),
        kpi_card("BBSO", SD.bbso_rir_counts(ds.forms)["total_bbso"],
                 hint=f"{SD.bbso_rir_counts(ds.forms)['bbso_this_month']} this month"),
        kpi_card("RIR", SD.bbso_rir_counts(ds.forms)["total_rir"],
                 hint=f"{SD.bbso_rir_counts(ds.forms)['rir_this_month']} this month"),
    ],
}

# ── Sidebar ──────────────────────────────────────────────────────────

def sidebar(state: dict):
    links = []
    links.append(A(Span("▦"), Span("Overview"), cls="active" if not state["platform"] else "",
                   hx_get=url(state, platform="", section=""), **SWAP))

    for pkey, plabel, picon, sections in PLATFORMS:
        for skey, slabel, sicon in sections:
            active = "active" if state["platform"] == pkey and state["section"] == skey else ""
            links.append(
                A(Span(sicon), Span(f"{plabel}: {slabel}"),
                  cls=active,
                  hx_get=url(state, platform=pkey, section=skey), **SWAP)
            )

    return Div(
        Div(Span("▦", cls="mark"),
            Span(NotStr("EWS<small>UNIFIED DASHBOARD</small>"), cls="name"),
            cls="brand"),
        Div(*links, cls="nav"),
        Div("Powered by data · EWS", cls="foot"),
        cls="sidebar",
    )


# ── Shell ────────────────────────────────────────────────────────────

def header(label: str):
    now_dt = datetime.now(_HOUSTON)
    now = now_dt.strftime("%b %d, %Y %I:%M %p")
    crumb = " · ".join(f"{plabel}: {slabel}" for _, plabel, _, sections in PLATFORMS
                       for _, slabel, _ in sections)
    return Div(
        Div(H1("EWS Unified Dashboard"), Div(crumb, cls="crumbs")),
        Div(Div(Span("Updating…", id="loading", cls="htmx-indicator"),
                " Last refreshed",
                style="margin-bottom:6px"),
            Span(f"{now} (Houston Time)", cls="pill"), cls="refreshed"),
        cls="header",
    )


def app_shell(state: dict):
    platform = state.get("platform", "")
    section = state.get("section", "")

    # Load data
    qb_ds = QB.qb_load_dataset()
    sd_ds = SD.sd_load_dataset()

    # Date range
    start, end, label = resolve_range(state, qb_ds)
    since = datetime.combine(start, datetime.min.time()).replace(tzinfo=timezone.utc) if start else None
    until = datetime.combine(end, datetime.max.time()).replace(tzinfo=timezone.utc) if end else None

    # QB data (always loaded for overview)
    qb_inv = QB.filter_invoices(qb_ds.invoices, start, end)

    # ── Overview (no platform selected) ──────────────────────────────
    if not platform:
        sd_kpis = PLATFORM_KPI_BUILDERS["sd"](sd_ds, qb_inv, start, end, state) if sd_ds else []
        qb_kpis = PLATFORM_KPI_BUILDERS["qb"](qb_ds, qb_inv, start, end, state) if qb_ds else []

        issues_html = ""
        try:
            issues = ISS.collect_issues(ds=sd_ds)
            if issues:
                issues_html = Div(panel("Issues Needing Attention", C.issues_table(issues), "#dc2626"),
                                  cls="grid mt")
        except Exception:
            pass

        main = Div(
            header(label),
            controls(state, qb_ds),
            Div(compare_toggle(state), style="margin-bottom:10px"),
            Div(NotStr(f"<span class='note'>Showing {label}</span>"),
                style="margin-bottom:14px"),
            Div(*qb_kpis, cls="kpis"),
            Div(*sd_kpis, cls="kpis"),
            qb_overview_body(qb_ds, qb_inv, start, end, state) if qb_ds else "",
            issues_html,
            cls="main",
        )
        return Div(sidebar(state), main, id="app", cls="layout")

    # ── Platform-specific body ──────────────────────────────────────
    body_content = ""

    if platform == "sd" and sd_ds:
        if section == "hse":
            body_content = sd_hse_body(sd_ds)
        elif section == "forms":
            body_content = sd_forms_body(sd_ds)
        elif section == "compliance":
            body_content = sd_compliance_body(sd_ds)
        elif section == "workers":
            body_content = sd_workers_body(sd_ds)

    elif platform == "gt":
        if section == "fleet":
            body_content = gt_fleet_body(since, until, state)
        elif section == "maintenance":
            body_content = gt_maintenance_body(since, until, state)

    elif platform == "qb" and qb_ds:
        if section == "overview":
            body_content = qb_overview_body(qb_ds, qb_inv, start, end, state)
        elif section == "sales":
            body_content = qb_sales_body(qb_ds, qb_inv, start, end, state)
        elif section == "finance":
            body_content = qb_finance_body(qb_ds, qb_inv, start, end, state)
        elif section == "profitability":
            body_content = qb_profitability_body(qb_ds, qb_inv, start, end, state)
        elif section == "customers":
            body_content = qb_customers_body(qb_ds, qb_inv, start, end, state)
        elif section == "accounts":
            body_content = qb_accounts_body(qb_ds, qb_inv, start, end, state)

    main = Div(
        header(label),
        controls(state, qb_ds),
        Div(NotStr(f"<span class='note'>Showing {label}</span>"),
            style="margin-bottom:14px"),
        body_content,
        cls="main",
    )
    return Div(sidebar(state), main, id="app", cls="layout")


# ── Routes ──────────────────────────────────────────────────────────

@rt("/")
def index(req):
    guard = require_login(req)
    if guard is not None:
        return guard
    return Title("EWS Unified Dashboard"), app_shell(get_state(req))


@rt("/view")
def view(req):
    guard = require_login(req)
    if guard is not None:
        return guard
    state = get_state(req)
    if state.get("waterfall"):
        # HTMX drilldown fragment — only return the breakdown
        qb_ds = QB.qb_load_dataset()
        start, end, _ = resolve_range(state, qb_ds)
        summary = QB.pnl_summary(qb_ds.pnl, state.get("basis", "accrual"), start, end)
        cat = state["waterfall"]
        rows = []
        if cat == "Income" and summary["income"] > 0:
            rows.append(Tr(Td("Total Income"), Td(_signed_money(summary["income"]), cls="num")))
        elif cat == "COGS" and summary["cogs"] > 0:
            rows.append(Tr(Td("Total COGS"), Td(_signed_money(summary["cogs"]), cls="num")))
        elif cat == "Operating Exp." and summary["expenses"] > 0:
            rows.append(Tr(Td("Total Operating Expenses"), Td(_signed_money(summary["expenses"]), cls="num")))
        elif cat == "Other Income" and summary.get("other_income", 0) != 0:
            rows.append(Tr(Td("Total Other Income"), Td(_signed_money(summary.get("other_income", 0)), cls="num")))
        elif cat == "Other Exp." and summary.get("other_expenses", 0) != 0:
            rows.append(Tr(Td("Total Other Expenses"), Td(_signed_money(summary.get("other_expenses", 0)), cls="num")))
        else:
            rows.append(Tr(Td("No detail available"), Td("—")))
        return Div(
            H4(f"{cat} — Breakdown", style="margin:0 0 8px; font-size:13px;"),
            Table(Thead(Tr(Th("Category"), Th("Amount", cls="num"))),
                  Tbody(*rows), cls="data"),
            cls="tbl-wrap",
        )
    return app_shell(state)


def login_page(error: str | None = None, next_url: str = "/"):
    alert = Div(error, cls="note", style="color: #b91c1c; margin-bottom: 14px;") if error else ""
    form = Form(
        Label("Email", html_for="email"),
        Input(type="email", name="email", id="email", required=True,
              style="width:100%; padding:10px; border:1px solid #d1d5db; border-radius:10px; margin-bottom:12px;"),
        Label("Password", html_for="password"),
        Input(type="password", name="password", id="password", required=True,
              style="width:100%; padding:10px; border:1px solid #d1d5db; border-radius:10px; margin-bottom:16px;"),
        Input(type="hidden", name="next", value=next_url),
        Button("Sign in", type="submit", cls="apply", style="width:100%;"),
        action="/login", method="post",
    )
    return Div(
        Div(H1("Dashboard sign in", style="margin-top:0;"),
            Div(f"Access restricted to @{AUTH_LOGIN_DOMAIN} accounts.", cls="note"),
            alert, form,
            cls="panel", style="max-width:420px; width:100%; margin:auto;"),
        cls="main",
        style="display:flex; align-items:center; justify-content:center; min-height:100vh; padding:0 18px; background: var(--page);"
    )


@rt("/login")
async def login(req):
    if user_is_authenticated(req):
        return Redirect(req.query_params.get("next", "/"))
    error = None
    next_url = req.query_params.get("next", "/")
    if req.method == "POST":
        try:
            payload = parse_form(await req.body())
        except RuntimeError:
            form = await req.form()
            payload = {k: v for k, v in form.items()}
        email = payload.get("email", "").strip()
        password = payload.get("password", "")
        next_url = payload.get("next", next_url) or "/"
        if email_allowed(email) and verify_password(password):
            req.session["user"] = email.lower()
            return Redirect(next_url)
        error = "Invalid email or password."
    return Title("Login"), login_page(error, next_url)


@rt("/logout")
def logout(req):
    try:
        req.session.clear()
    except AssertionError:
        pass
    return Redirect("/login")


@rt("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("visualize.app:app", host="0.0.0.0", port=int(getenv("PORT", "5001")), reload=True)
