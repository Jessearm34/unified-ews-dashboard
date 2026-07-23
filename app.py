"""Unified EWS Dashboard — QuickBooks + SiteDocs in one place.

All data comes from real PostgreSQL databases, one per platform.
Two existing dashboards stay up unchanged; this is a 3rd deployment.
GeoTab was removed — unreliable + comes with its own dashboard.
"""
from __future__ import annotations

import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from hashlib import pbkdf2_hmac
from hmac import compare_digest
from urllib.parse import parse_qs, urlencode

import pandas as pd
import plotly.graph_objects as go
from dotenv import load_dotenv
from fasthtml.common import *

load_dotenv()

from data import qb_data as QB
from data import sd_data as SD
from data import gt_data as GT

# ── App setup ──────────────────────────────────────────────────────────────

PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"

# Date range presets
def resolve_date_range(range_key, end_date=None):
    """Return (start, end) where end is the last completed month."""
    if end_date is None:
        end_date = date.today()
    # End of last completed month = 1st of current month - 1 day
    end = date(end_date.year, end_date.month, 1) - timedelta(days=1)
    if end < date(2020, 1, 1):
        end = end_date  # fallback if something weird
    if range_key == "ytd":
        return date(end.year, 1, 1), end
    if range_key == "30d":
        return end - timedelta(days=30), end
    if range_key == "90d":
        return end - timedelta(days=90), end
    if range_key == "lm":
        # Last completed month
        lm_end = date(end.year, end.month, 1) - timedelta(days=1)
        lm_start = date(lm_end.year, lm_end.month, 1)
        return lm_start, lm_end
    if range_key == "12m":
        return date(end.year - 1, 1, 1), date(end.year - 1, 12, 31)
    if range_key == "ly":
        return date(end.year - 1, 1, 1), date(end.year - 1, 12, 31)
    return date(2020, 1, 1), end

RANGE_PRESETS = [("ytd","YTD"), ("lm","Last month"), ("30d","30d"), ("90d","90d"), ("ly","Last year"), ("all","All")]

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

/* ── Sidebar ── */
.sidebar { width: 232px; flex: 0 0 232px; background: var(--navy); color: #e8eef5;
           display: flex; flex-direction: column; padding: 22px 14px; overflow-y: auto;
           position: sticky; top: 0; height: 100vh; }
.brand { display: flex; align-items: center; gap: 10px; padding: 6px 8px 20px; }
.layout { display: flex; min-height: 100vh; align-items: stretch; }
.brand .mark { font-size: 22px; }
.brand .name { font-weight: 800; font-size: 14px; line-height: 1.15; letter-spacing: .04em; }
.brand .name small { display:block; font-weight:600; font-size:10px; color:#7e93a8; letter-spacing:.14em; }
.nav { display: flex; flex-direction: column; gap: 2px; margin-top: 8px; }

/* Platform group headers */
.nav-group summary { display: flex; align-items: center; gap: 11px; padding: 10px 12px;
  border-radius: 10px; color: #b8c6d6; text-decoration: none; font-size: 14px;
  font-weight: 600; cursor: pointer; list-style: none; }
.nav-group summary::-webkit-details-marker { display: none; }
.nav-group summary:hover { background: var(--navy-2); color: #fff; }
.nav-group summary .arrow { color: #5a7a9a; font-size: 11px; margin-left: auto; transition: transform .2s; }
.nav-group[open] summary .arrow { transform: rotate(90deg); }

/* Sub-tab links */
.nav-group .sub { padding-left: 8px; }
.nav-group .sub a { display: flex; align-items: center; gap: 11px; padding: 8px 12px 8px 20px;
  border-radius: 8px; color: #889bb3; text-decoration: none; font-size: 13px; font-weight: 500; }
.nav-group .sub a:hover { background: var(--navy-2); color: #fff; }
.nav-group .sub a.active { background: var(--accent); color: #fff; }

/* Overview link at top */
.nav-link { display: flex; align-items: center; gap: 11px; padding: 10px 12px;
  border-radius: 10px; color: #b8c6d6; text-decoration: none; font-size: 14px; font-weight: 600; }
.nav-link:hover { background: var(--navy-2); color: #fff; }
.nav-link.active { background: var(--accent); color: #fff; }

.sidebar .foot { margin-top: auto; font-size: 11px; color: #64788f; padding: 8px; }

/* Main content */
.main { flex: 1; min-width: 0; padding: 22px 26px 40px; padding-bottom: 60px; }
.header { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 12px; }
.header h1 { margin: 0; font-size: 26px; font-weight: 800; }
.header .crumbs { color: var(--muted); font-size: 13px; margin-top: 4px; }
.header .refreshed { text-align: right; color: var(--muted); font-size: 12px; }
.header .refreshed .pill { display:inline-block; background:#fff; border:1px solid var(--line);
        border-radius: 20px; padding: 6px 12px; font-weight:600; color:var(--ink); }

/* Controls / filters */
.controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
            background:#fff; border:1px solid var(--line); border-radius: 14px; padding: 12px 14px; margin: 16px 0 14px; }
.controls .lbl { font-size: 12px; font-weight:600; color: var(--muted); margin-right: 4px; }
.preset { border: 1px solid var(--line); background:#f8fafc; color: var(--ink); border-radius: 999px;
          padding: 7px 14px; font-size: 13px; cursor: pointer; font-weight: 500; }
.preset:hover { border-color: var(--accent); color: var(--accent); }
.preset.active { background: var(--accent); border-color: var(--accent); color: #fff; }

/* KPI cards */
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 12px; }
.kpi-group { margin-bottom: 4px; }
.kpi-group-title { font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em;
                   color: var(--muted); margin: 0 0 4px 2px; display: flex; align-items: center; gap: 6px; }
.kpi-group-title .line { flex:1; height:1px; background: var(--line); }
.kpi { background: var(--card); border:1px solid var(--line); border-radius: 8px; padding: 8px 10px;
       text-decoration: none; color: inherit; transition: box-shadow .15s; }
.kpi:hover { box-shadow: 0 2px 8px rgba(15,23,42,.06); }
.kpi .k-label { color: var(--muted); font-size: 9px; font-weight: 600; display:flex; align-items:center; gap:3px; white-space: nowrap; }
.kpi .k-label .k-platform { font-size:8px; background:#e2e8f0; color:#475569; padding:0 4px; border-radius:2px; font-weight:700; }
.kpi .k-value { font-size: 16px; font-weight: 800; margin: 1px 0 0; line-height: 1.2; }
.kpi .k-hint { color:#94a3b8; font-size: 9px; margin-top:0; }
.kpi .k-delta { font-size: 9px; font-weight: 600; margin-left: 2px; }
.kpi .k-delta.up { color: var(--good); }
.kpi .k-delta.down { color: var(--bad); }
.kpi .k-badge { display: inline-block; font-size: 9px; font-weight: 700; padding: 0 5px;
                border-radius: 999px; margin-left: 3px; }
.kpi .k-badge.green { background:#dcfce7; color:#15803d; }
.kpi .k-badge.warn { background:#fef3c7; color:#92400e; }
.kpi .k-badge.red { background:#fee2e2; color:#b91c1c; }

.kpi-rag { display:inline-block; width:6px; height:6px; border-radius:50%; margin-right:2px; flex-shrink:0; }

/* Panels */
.grid { display: grid; gap: 16px; }
.grid.two { grid-template-columns: 1fr 1fr; }
.grid.three { grid-template-columns: 1fr 1fr 1fr; }
.panel { background: var(--card); border:1px solid var(--line); border-radius: 16px; padding: 16px 18px; min-width: 0; }
.panel h3 { margin: 0 0 12px; font-size: 14px; font-weight: 700; display:flex; align-items:center; gap:8px; }
.panel h3 .dot { width:9px; height:9px; border-radius: 3px; display:inline-block; }
.panel-scroll { max-height: 340px; overflow-y: auto; }
.chart-empty { display:flex; align-items:center; justify-content:center; height: 260px; color: var(--muted);
               border: 1px dashed var(--line); border-radius: 12px; font-size: 13px; }

/* Tables */
.tbl-wrap { overflow-x: auto; max-height: 340px; overflow-y: auto; }
table.data { width: 100%; border-collapse: collapse; font-size: 13px; }
table.data th { text-align: left; color: var(--muted); font-weight: 600; padding: 8px 10px;
                border-bottom: 2px solid var(--line); white-space: nowrap; position: sticky; top: 0; background: #fff; }
table.data td { padding: 8px 10px; border-bottom: 1px solid #f1f5f9; white-space: nowrap; }
table.data td.num { text-align: right; }
table.data td.clickable { cursor: pointer; color: var(--accent); font-weight: 700; }
table.data td.clickable:hover { text-decoration: underline; }
.badge { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px; background:#e2e8f0; color:#475569; }
.badge.green { background:#dcfce7; color:#15803d; }
.badge.red { background:#fee2e2; color:#b91c1c; }
.badge.warn { background:#fef3c7; color:#92400e; }
.mt { margin-top: 16px; }
.note { color: var(--muted); font-size: 12px; }
.htmx-indicator { opacity: 0; transition: opacity .2s; font-size: 12px; color: var(--accent); }
.htmx-request .htmx-indicator { opacity: 1; }

/* Loading spinner & HTMX indicator — shown inside content while swapping */
#content.htmx-request .loading-zone { display: flex; }
#content .loading-zone { display: none; }
.spinner { display:inline-block; width:16px; height:16px; border:2px solid var(--line);
           border-top-color: var(--accent); border-radius:50%; animation: spin .6s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.loading-zone { display:flex; align-items:center; justify-content:center; min-height:200px; color:var(--muted); gap:8px; }

/* Fix alignment in safety profile number cells */
.num a { display: inline-block; min-width: 24px; text-align: center; }
.num-link { display: inline-block; min-width: 28px; text-align: center; font-weight: 700;
            color: var(--accent); text-decoration: none; cursor: pointer; padding: 2px 6px;
            border-radius: 6px; transition: background .15s; }
.num-link:hover { background: #dbeafe; }
.num-link.warn { color: var(--warn); }
.num-link.warn:hover { background: #ffedd5; }
.modebar, .modebar-container, .plotly-notifier,
.js-plotly-plot .modebar, .js-plotly-plot .modebar-btn,
.modebar-btn, .modebar-group { display: none !important; }

/* Fix chart panel sizing */
.panel .js-plotly-plot { width: 100%; }
.panel .plot-container { width: 100%; }

/* Prevent mobile auto-zoom on orientation/scroll */
html { -webkit-text-size-adjust: 100%; -moz-text-size-adjust: 100%; text-size-adjust: 100%; }
body { touch-action: pan-y; }

/* Fade in content on HTMX swap — subtle, no layout shift */
#content { animation: fadein .2s ease; }
@keyframes fadein { from { opacity:0; } to { opacity:1; } }
""")

app, rt = fast_app(
    pico=False,
    hdrs=(
        Meta(name="viewport", content="width=device-width, initial-scale=1"),
        Link(rel="preconnect", href="https://fonts.googleapis.com"),
        Link(rel="stylesheet", href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap"),
        Script(src=PLOTLY_CDN),
        STYLE,
    ),
    secret_key=os.getenv("FASTHTML_SECRET_KEY", "change-this-secret"),
)

# ── Auth ──────────────────────────────────────────────────────────────────

AUTH_PASSWORD = os.getenv("DASHBOARD_LOGIN_PASSWORD")
AUTH_PASSWORD_HASH = os.getenv("DASHBOARD_LOGIN_PASSWORD_HASH", "").strip()
AUTH_DOMAIN = os.getenv("DASHBOARD_LOGIN_DOMAIN", "").strip().lower()


def _hash_password(password: str, salt: str | None = None) -> str:
    if salt is None:
        salt = os.urandom(16).hex()
    dk = pbkdf2_hmac("sha256", password.encode(), salt.encode(), 250000)
    return f"pbkdf2_sha256${salt}${dk.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algo, salt, digest = stored_hash.split("$", 2)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    return compare_digest(_hash_password(password, salt), stored_hash)


def require_login(req):
    """Call inside route handlers. Returns a RedirectResponse if not logged in, else None."""
    user = req.session.get("user")
    if not user:
        return RedirectResponse(f"/login?next={req.url.path}{'?' + urlencode(req.query_params) if req.query_params else ''}", status_code=303)
    return None


# ── Sidebar & navigation data ─────────────────────────────────────────────

# Platform definitions (checked lazily for empty sections)
PLATFORMS = [
    {
        "key": "qb",
        "label": "QuickBooks",
        "icon": "📊",
        "sections": [
            ("overview", "Overview", "▦"),
            ("sales", "Sales", "📈"),
            ("finance", "Finance", "💲"),
            ("profitability", "Profitability", "💹"),
            ("customers", "Customers", "👥"),
            ("accounts", "Accounts", "🏦"),
        ],
    },
    {
        "key": "sd",
        "label": "SiteDocs",
        "icon": "🛡️",
        "sections": [
            ("hse", "HSE Overview", "🛡️"),
            ("forms", "Forms & JSAs", "📋"),
            ("compliance", "Compliance", "✅"),
            ("workers", "Workers", "👷"),
        ],
    },
    {
        "key": "gt",
        "label": "GeoTab",
        "icon": "🚛",
        "sections": [
            ("fleet", "Fleet Overview", "📊"),
            ("safety", "Safety", "🛡️"),
            ("exceptions", "Exceptions", "⚠️"),
            ("maintenance", "Maintenance", "🔧"),
        ],
    },
]


def sidebar(active_platform=None, active_section="overview"):
    nav_items = []

    # Overview link
    ov_class = "nav-link active" if active_platform is None else "nav-link"
    nav_items.append(
        A("▦ Overview", cls=ov_class, href="/",
          hx_get="/view?platform=overview", hx_target="#content",
          hx_push_url="true")
    )

    for pf in PLATFORMS:
        is_open = (pf["key"] == active_platform)
        subs = []
        for skey, slabel, sicon in pf["sections"]:
            sub_class = "active" if (active_platform == pf["key"] and active_section == skey) else ""
            subs.append(
                Div(
                    A(f"{sicon} {slabel}", cls=sub_class,
                      href=f"/?platform={pf['key']}&section={skey}",
                      hx_get=f"/view?platform={pf['key']}&section={skey}",
                      hx_target="#content",
                      hx_push_url="true"),
                )
            )
        nav_items.append(
            Details(
                Summary(
                    Span(f"{pf['icon']} {pf['label']}"),
                    Span("▶", cls="arrow"),
                ),
                Div(*subs, cls="sub"),
                cls="nav-group",
                open=is_open,
            )
        )

    return Aside(
        Div(
            Div(
                Span("▦", cls="mark"),
                Div("EWS", Small("Unified Dashboard"), cls="name"),
                cls="brand",
            ),
            Div(*nav_items, cls="nav"),
            Div("Powered by data", cls="foot"),
            cls="sidebar",
        )
    )


# ── KPI helpers ───────────────────────────────────────────────────────────

def kpi_card(label, value, unit="", hint="", rag=None, platform="", delta=None, delta_up_good=True):
    """Render a single KPI card with optional delta arrow."""
    fmt_val = value
    if isinstance(value, float):
        if unit == "$":
            if abs(value) >= 1e6:
                fmt_val = f"${value/1e6:,.2f}M"
            elif abs(value) >= 1000:
                fmt_val = f"${value/1000:,.0f}K"
            else:
                fmt_val = f"${value:,.0f}"
        elif unit == "%" or unit == "%":
            fmt_val = f"{value:.1f}%"
        elif unit == "days":
            fmt_val = f"{value:.0f}d"
        elif unit == "mph":
            fmt_val = f"{value:.0f} mph"
        else:
            if value == int(value):
                fmt_val = f"{int(value):,}"
            else:
                fmt_val = f"{value:,.1f}"
    elif isinstance(value, int):
        fmt_val = f"{value:,}"

    rag_dot = ""
    if rag:
        rag_dot = Span(cls="kpi-rag", style=f"background:{rag_color_css(rag)}")
    platform_tag = Span(platform, cls="k-platform") if platform else ""

    # Delta arrow
    delta_el = ""
    if delta is not None:
        up = delta > 0
        good = up if delta_up_good else not up
        arrow = "▲" if up else "▼"
        cls = "k-delta up" if good else "k-delta down"
        delta_el = Span(f" {arrow} {abs(delta):.1f}%", cls=cls)

    return Div(
        Div(rag_dot, label, platform_tag, cls="k-label"),
        Div(fmt_val, delta_el, cls="k-value"),
        Div(hint, cls="k-hint") if hint else "",
        cls="kpi",
    )


def rag_color_css(status):
    return {"green": "#16a34a", "amber": "#ea580c", "red": "#dc2626"}.get(status, "#64748b")


def rag_for_value(value, green, amber, good_when_high=True):
    if good_when_high:
        if value >= green:
            return "green"
        if value >= amber:
            return "amber"
        return "red"
    else:
        if value <= green:
            return "green"
        if value <= amber:
            return "amber"
        return "red"


def panel(title, body, dot="#2563eb", scroll=False):
    cls = "panel panel-scroll" if scroll else "panel"
    return Div(H3(Span(cls="dot", style=f"background:{dot}"), title),
               NotStr(body) if isinstance(body, str) else body, cls=cls)


def empty(msg="No data for this period"):
    return Div(msg, cls="chart-empty")


def _rgba(h: str, a: float) -> str:
    h = h.lstrip("#")
    return f"rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{a})"


def kpi_grid(cards):
    return Div(*cards, cls="kpis")


# ── Page shell ────────────────────────────────────────────────────────────

def shell(content, active_platform=None, active_section="overview", title=""):
    user = ""  # placeholder; we don't have req here
    header = Div(
        Div(
            H1(title or "Overview"),
            Div(cls="crumbs"),
            cls="header-left",
        ),
        Div(
            Div(
                Span(f"Updated {datetime.now().strftime('%H:%M')}", cls="pill"),
                cls="refreshed",
            ),
            A("Logout", href="/logout", style="color:var(--muted);font-size:12px;margin-left:12px;"),
        ),
        cls="header",
    )
    return Div(
        sidebar(active_platform, active_section),
        Div(header,
            Div(content,
                Div(Div(cls="spinner"), "Loading...", cls="loading-zone"),
                id="content"),
            cls="main"),
        cls="layout",
    )


# ── Overview (cross-platform) ─────────────────────────────────────────────

def render_overview(range_key="all"):
    """Top KPIs and charts from both platforms (QB + SD). GeoTab removed."""
    parts = []
    start, end = resolve_date_range(range_key)

    # ── Range buttons for Overview ──
    def ov_range_buttons():
        btns = []
        for rk, rl in RANGE_PRESETS:
            active = "active" if range_key == rk else ""
            if rk == "custom":
                btns.append(Button(rl, cls=f"preset {active}",
                    onclick="document.getElementById('ov-custom-range').style.display='flex'"))
            else:
                btns.append(Button(rl, cls=f"preset {active}",
                    hx_get=f"/view?platform=overview&range={rk}", hx_target="#content"))
        custom = Div(Input(type="date", id="ov-start"), Input(type="date", id="ov-end"),
            Button("Apply", cls="preset active",
                hx_get="/view?platform=overview&range=custom",
                hx_include="#ov-start,#ov-end", hx_target="#content"),
            id="ov-custom-range", style="display:none;gap:6px;align-items:center;")
        return Div(Span("Range:", cls="lbl"), *btns, custom, cls="controls")

    # ── Load data from both platforms ──
    qb_ds = _cached("qb", load_qb)
    sd_ds = _cached("sd", load_sd)

    # ── Top KPI row: 4 per platform ──
    qb_kpis = []
    if qb_ds:
        invoices = QB.filter_invoices(qb_ds.invoices, date(2020, 1, 1), date.today())
        bs = QB.balance_sheet_summary(qb_ds.accounts)
        pnl = QB.pnl_summary(qb_ds.pnl, "accrual", start, end)
        revenue = pnl["income"] if not qb_ds.pnl.empty else (float(invoices["Revenue"].sum()) if not invoices.empty else 0.0)
        qb_kpis = [
            kpi_card("Revenue", revenue, "$", "", platform="QB"),
            kpi_card("Cash on Hand", bs["cash"], "$", "", platform="QB"),
            kpi_card("Outstanding AR", bs["ar"], "$", "", platform="QB"),
            kpi_card("Net Income", pnl["net_income"], "$", "", platform="QB"),
        ]

    sd_kpis = []
    if sd_ds:
        sched_c = SD.schedule_counts(sd_ds.schedules)
        w_count = SD.worker_counts(sd_ds.workers)
        f_count = SD.form_counts(sd_ds.forms)
        part = SD.worker_participation(sd_ds.workers, sd_ds.forms)
        brc = SD.bbso_rir_counts(sd_ds.forms)
        rag = rag_for_value(sched_c["completion_pct"], 80, 60)
        sd_kpis = [
            kpi_card("Schedule Compliance", sched_c["completion_pct"], "%",
                     rag=rag, platform="SD"),
            kpi_card("Overdue Items", float(sched_c["overdue"]), "",
                     rag=rag_for_value(sched_c["overdue"], 5, 15, False),
                     platform="SD"),
            kpi_card("BBSO", float(brc["total_bbso"]), "",
                     hint=f"{brc['bbso_this_month']} this month",
                     platform="SD"),
            kpi_card("RIR / Near Miss", float(brc["total_rir"]), "",
                     hint=f"{brc['rir_this_month']} this month",
                     platform="SD"),
        ]

    all_kpis = (*qb_kpis, *sd_kpis)
    if all_kpis:
        groups = []
        if qb_kpis:
            groups.append(Div(Div(NotStr("QuickBooks"), Div(cls="line"), cls="kpi-group-title"),
                              Div(*qb_kpis, cls="kpis"), cls="kpi-group"))
        if sd_kpis:
            groups.append(Div(Div(NotStr("SiteDocs"), Div(cls="line"), cls="kpi-group-title"),
                              Div(*sd_kpis, cls="kpis"), cls="kpi-group"))
        parts.append(Div(*groups))

    # ── Charts: 2×2 grid (only render if data exists) ──
    charts = []

    # 1. Monthly Revenue Trend (QB)
    if qb_ds:
        try:
            from charts import qb_charts as QBC
            inv = QB.filter_invoices(qb_ds.invoices, start, end)
            if not inv.empty:
                charts.append(Div(H3("Monthly Revenue Trend"), NotStr(QBC.trend(inv, "revenue")), cls="panel"))
        except Exception:
            pass

    # 2. Schedule Compliance (SD)
    if sd_ds:
        if not sd_ds.schedules.empty:
            try:
                sched_c = SD.schedule_counts(sd_ds.schedules)
                schedule_total = sched_c.get("total", 0)
                if schedule_total > 0:
                    from charts import sd_charts as SDC
                    charts.append(Div(H3("Schedule Compliance"), NotStr(SDC.schedule_compliance(sd_ds.schedules)), cls="panel"))
            except Exception:
                pass

    # 3. Monthly BBSO (SD)
    if sd_ds:
        if not sd_ds.forms.empty:
            try:
                from charts import sd_charts as SDC
                charts.append(Div(H3("Monthly BBSO"), NotStr(SDC.bbso_trend(sd_ds.forms)), cls="panel"))
            except Exception:
                pass

    # 4. Forms Monthly Trend (SD)
    if sd_ds:
        if not sd_ds.forms.empty:
            try:
                from charts import sd_charts as SDC
                charts.append(Div(H3("Forms Monthly Trend"), NotStr(SDC.forms_trend(sd_ds.forms)), cls="panel"))
            except Exception:
                pass

    parts.insert(0, ov_range_buttons())
    if charts:
        parts.append(Div(*charts, cls="grid two"))
    if sd_ds and not sd_ds.forms.empty:
        parts.append(Div(id="sd-forms-list"))
    return tuple(parts)


# ── Safe data loaders with app-level cache ────────────────────────────────

_data_cache = {}
_cache_ts = {}
_CACHE_DURATION = 600  # 10 minutes


def _cached(key, loader):
    """Load data once and cache for _CACHE_DURATION seconds."""
    now = time.time()
    if key in _data_cache and (now - _cache_ts.get(key, 0) < _CACHE_DURATION):
        return _data_cache[key]
    try:
        val = loader()
        if val is not None:
            _data_cache[key] = val
            _cache_ts[key] = now
        return val
    except Exception:
        return None


def load_qb():
    try:
        ds = QB.qb_load_dataset()
        if ds and not ds.invoices.empty:
            return ds
    except Exception:
        pass
    return None


def load_sd():
    try:
        ds = SD.sd_load_dataset()
        if ds and ds.has_data:
            return ds
    except Exception:
        pass
    return None


def load_gt():
    """Check GeoTab DB is reachable and has data."""
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


# ── Platform section renderers ─────────────────────────────────────────────

# Chart HTML cache — avoids re-rendering Plotly on every HTMX request
_chart_html_cache: dict[str, tuple[str, float]] = {}
_CHART_CACHE_DURATION = 30  # seconds


def _chart(label, fn, *args, **kw):
    """Render a chart with HTML caching. Returns empty string if chart has nothing."""
    # Build a cache key from function name + args
    cache_key = f"{fn.__name__}:{':'.join(str(a) for a in args)}"
    now = time.time()
    if cache_key in _chart_html_cache:
        cached_html, cached_ts = _chart_html_cache[cache_key]
        if now - cached_ts < _CHART_CACHE_DURATION:
            if not cached_html:
                return ""
            if label:
                return Div(H3(label), NotStr(cached_html), cls="panel")
            return Div(NotStr(cached_html), cls="panel")
    try:
        html = fn(*args, **kw)
        if not html or 'chart-empty' in str(html) or 'No data' in str(html) or 'No schedule' in str(html):
            _chart_html_cache[cache_key] = ("", now)
            return ""
        _chart_html_cache[cache_key] = (html, now)
        if label:
            return Div(H3(label), NotStr(html), cls="panel")
        return Div(NotStr(html), cls="panel")
    except Exception:
        return ""



def render_qb_section(section_key, basis="accrual", range_key="all", metric="revenue"):
    """Render a QuickBooks sub-tab."""
    ds = _cached("qb", load_qb)
    if not ds:
        return Div(H2("QuickBooks"), Div("No data available.", cls="chart-empty"), cls="mt")

    from charts import qb_charts as QBC

    start, end = resolve_date_range(range_key)
    invoices = QB.filter_invoices(ds.invoices, start, end)

    # ── Helper: basis toggle ──
    def basis_buttons():
        btns = []
        for key, label in [("accrual", "Accrual"), ("cash", "Cash")]:
            active = "active" if basis.lower() == key else ""
            btns.append(
                Button(label, cls=f"preset {active}",
                       hx_get=f"/view?platform=qb&section={section_key}&basis={key}&metric={metric}&range={range_key}",
                       hx_target="#content", hx_indicator="#loading")
            )
        return Div(Span("Basis:", cls="lbl"), *btns,
                   Span("QuickBooks ProfitAndLoss", cls="note", style="margin-left:10px;"),
                   cls="controls", style="margin-top:0;")

    # ── Helper: range buttons
    def range_buttons():
        btns = []
        for rk, rl in RANGE_PRESETS:
            active = "active" if range_key == rk else ""
            btns.append(Button(rl, cls=f"preset {active}",
                hx_get=f"/view?platform=qb&section={section_key}&basis={basis}&range={rk}",
                hx_target="#content"))
        return Div(Span("Range:", cls="lbl"), *btns, cls="controls")

    # ── Helper: P&L statement table ──
    def pnl_statement(summary):
        def _signed(v):
            return f"-${abs(v):,.2f}" if v < 0 else f"${v:,.2f}"
        def row(label, value, total=False, pct=False, indent=False):
            txt = f"{value:,.1f}%" if pct else _signed(value)
            neg = (not pct and value < 0) or (pct and value < 0)
            style = "font-weight:700;" if total else ""
            if neg: style += "color: var(--bad);"
            lc = Td(label, style=("padding-left:24px;color:var(--muted);" if indent else ("font-weight:700;" if total else "")))
            rs = "border-top:2px solid var(--line);" if total else ""
            return Tr(lc, Td(txt, cls="num", style=style), style=rs)
        s = summary
        body = [
            row("Income", s["income"]),
            row("Cost of Goods Sold", -s["cogs"]),
            row("Gross Profit", s["gross_profit"], total=True),
            row("Gross Margin", s["gross_margin"], pct=True, indent=True),
            row("Operating Expenses", -s["expenses"]),
            row("Net Operating Income", s["net_operating_income"], total=True),
            row("Other Income", s["other_income"]),
            row("Other Expenses", -s["other_expenses"]),
            row("Net Income", s["net_income"], total=True),
            row("Net Margin", s["net_margin"], pct=True, indent=True),
        ]
        return Div(Table(Thead(Tr(Th("Line item"), Th("Amount", cls="num"))), Tbody(*body), cls="data"), cls="tbl-wrap")

    if section_key == "overview":
        kpis = QB.compute_kpis(ds, invoices, start, end)
        cards = [
            kpi_card(k.label, k.value, k.unit, k.hint or "", delta=k.delta, delta_up_good=k.delta_good_when_up)
            for k in [kpis["revenue"], kpis["cash"], kpis["outstanding"], kpis["overdue"],
                      kpis["dso"], kpis["active_customers"]]
        ]
        return (
            H2("QuickBooks Overview"),
            range_buttons(),
            kpi_grid(cards),
            Div(
                Div(H3("Monthly Revenue Trend"), NotStr(QBC.trend(invoices, "revenue")), cls="panel"),
                Div(H3("A/R Aging"), NotStr(QBC.ar_aging(invoices)), cls="panel"),
                cls="grid two"),
            Div(
                Div(H3("Revenue by Segment"), NotStr(QBC.revenue_by_class(invoices)), cls="panel"),
                Div(H3("Top Customers"), NotStr(QBC.top_customers(invoices)), cls="panel"),
                cls="grid two mt"),
        )

    elif section_key == "sales":
        kpis = QB.compute_kpis(ds, invoices, start, end)
        cards = [kpi_card(k.label, k.value, k.unit, k.hint or "", delta=k.delta, delta_up_good=k.delta_good_when_up)
                 for k in [kpis["revenue"], kpis["collected"], kpis["invoice_count"], kpis["avg_invoice"]]]
        items = QB.invoice_line_items(invoices)
        return (
            H2("Sales"),
            range_buttons(),
            kpi_grid(cards),
            Div(
                Div(H3("Monthly Revenue"), NotStr(QBC.trend(invoices, "revenue")), cls="panel"),
                Div(H3("Revenue by Service/Product"), NotStr(QBC.revenue_by_item(invoices)), cls="panel"),
                cls="grid two"),
            Div(
                Div(H3("Revenue by Segment"), NotStr(QBC.revenue_by_class(invoices)), cls="panel"),
                Div(H3("Top Customers"), NotStr(QBC.top_customers(invoices)), cls="panel"),
                cls="grid two mt"),
        )

    elif section_key == "finance":
        kpis = QB.compute_kpis(ds, invoices, start, end)
        cards = [kpi_card(k.label, k.value, k.unit, k.hint or "", delta=k.delta, delta_up_good=k.delta_good_when_up)
                 for k in [kpis["cash"], kpis["outstanding"], kpis["dso"],
                           kpis["working_capital"], kpis["current_ratio"], kpis["total_liabilities"]]]
        return (
            H2("Finance"),
            range_buttons(),
            kpi_grid(cards),
            Div(
                Div(H3("Balance Sheet"), NotStr(QBC.balance_sheet(ds.accounts)), cls="panel"),
                Div(H3("A/R Aging"), NotStr(QBC.ar_aging(invoices)), cls="panel"),
                cls="grid two"),
            Div(
                Div(H3("Invoice Balance Status"), NotStr(QBC.balance_status(invoices)), cls="panel"),
                Div(H3("Assets by Type"), NotStr(QBC.accounts_by_type(ds.accounts)), cls="panel"),
                cls="grid two mt"),
        )

    elif section_key == "profitability":
        pnl_sum = QB.pnl_summary(ds.pnl, basis, start, end)
        kpis = QB.pnl_kpis(ds, basis, start, end)
        cards = [kpi_card(k.label, k.value, k.unit, k.hint or "", delta=k.delta, delta_up_good=k.delta_good_when_up)
                 for k in [kpis["pnl_income"], kpis["pnl_cogs"], kpis["pnl_gross_profit"],
                           kpis["pnl_gross_margin"], kpis["pnl_net_income"], kpis["pnl_net_margin"]]]
        return (
            H2("Profitability"),
            range_buttons(),
            basis_buttons(),
            kpi_grid(cards),
            Div(
                Div(H3("P&L Waterfall"), NotStr(QBC.pnl_waterfall(pnl_sum)), cls="panel"),
                Div(H3(f"Income Statement ({basis})"), pnl_statement(pnl_sum), cls="panel"),
                cls="grid two"),
            Div(
                Div(H3("Monthly P&L Trend"), NotStr(QBC.pnl_trend(ds.pnl, basis)), cls="panel"),
                Div(H3("Top Expenses"), NotStr(QBC.pnl_expenses(ds.pnl_detail, basis, start, end)), cls="panel"),
                cls="grid two mt"),
        )

    elif section_key == "customers":
        kpis = QB.compute_kpis(ds, invoices, start, end)
        cards = [kpi_card(k.label, k.value, k.unit, k.hint or "", delta=k.delta, delta_up_good=k.delta_good_when_up)
                 for k in [kpis["active_customers"], kpis["total_customers"], kpis["outstanding"], kpis["overdue"]]]
        return (
            H2("Customers"),
            kpi_grid(cards),
            Div(
                Div(H3("Top Customers"), NotStr(QBC.top_customers(invoices)), cls="panel"),
                Div(H3("Revenue by Region"), NotStr(QBC.revenue_by_city(invoices)), cls="panel"),
                cls="grid two"),
        )

    elif section_key == "accounts":
        kpis = QB.compute_kpis(ds, invoices, start, end)
        cards = [kpi_card(k.label, k.value, k.unit, k.hint or "", delta=k.delta, delta_up_good=k.delta_good_when_up)
                 for k in [kpis["total_assets"], kpis["total_liabilities"], kpis["equity"], kpis["cash"]]]
        return (
            H2("Accounts"),
            kpi_grid(cards),
            Div(
                Div(H3("Balances by Type"), NotStr(QBC.accounts_by_type(ds.accounts)), cls="panel"),
                Div(H3("Balances by Classification"), NotStr(QBC.accounts_by_classification(ds.accounts)), cls="panel"),
                cls="grid two"),
            Div(
                Div(H3("Balance Sheet"), NotStr(QBC.balance_sheet(ds.accounts)), cls="panel"),
                cls="grid two mt"),
        )

    return Div(H2("QuickBooks"), Div("Section not found.", cls="chart-empty"))



def invoice_table(invoices):
    """HTML table of invoices sorted by date descending."""
    if invoices.empty:
        return ""
    top = invoices.sort_values("TxnDate", ascending=False).head(30)
    rows = []
    for _, r in top.iterrows():
        bal = r.get("RevenueBalance", 0)
        if bal <= 0:
            badge = "<span class='badge green'>Paid</span>"
        elif r.get("Overdue", False):
            badge = "<span class='badge red'>Overdue</span>"
        else:
            badge = "<span class='badge'>Open</span>"
        txn = str(r.get("TxnDate", ""))[:10] if hasattr(r.get("TxnDate"), "strftime") else ""
        rows.append(f"<tr><td>{r.get('DocNumber','')}</td><td>{txn}</td>"
                    f"<td>{r.get('CustomerName','')[:20]}</td>"
                    f"<td class='num'>${r.get('Revenue',0):,.0f}</td>"
                    f"<td>{badge}</td></tr>")
    h = "<tr><th>Doc#</th><th>Date</th><th>Customer</th><th class='num'>Revenue</th><th>Status</th></tr>"
    return f"<div class='tbl-wrap'><table class='data'><thead>{h}</thead><tbody>{''.join(rows)}</tbody></table></div>"


def customer_table(ds, invoices):
    """HTML table of customers sorted by billed amount."""
    if ds.customers.empty:
        return ""
    cust_billed = invoices.groupby("CustomerName")["Revenue"].sum().reset_index() if not invoices.empty else pd.DataFrame()
    if cust_billed.empty:
        return ""
    merged = ds.customers.merge(cust_billed, on="CustomerName", how="left")
    merged = merged.dropna(subset=["Revenue"]).sort_values("Revenue", ascending=False).head(20)
    rows = []
    for _, r in merged.iterrows():
        active = "<span class='badge green'>Active</span>" if r.get("Active") else "<span class='badge'>Inactive</span>"
        rows.append(f"<tr><td>{r.get('CustomerName','')[:25]}</td>"
                    f"<td>{r.get('City','')[:15]}</td>"
                    f"<td class='num'>${r.get('Revenue',0):,.0f}</td>"
                    f"<td class='num'>${r.get('Balance',0):,.0f}</td>"
                    f"<td>{active}</td></tr>")
    h = "<tr><th>Customer</th><th>City</th><th class='num'>Billed</th><th class='num'>Balance</th><th>Status</th></tr>"
    return f"<div class='tbl-wrap'><table class='data'><thead>{h}</thead><tbody>{''.join(rows)}</tbody></table></div>"



def render_sd_section(section_key):
    """Render a SiteDocs sub-tab with BBSO & RIR KPIs prominent throughout."""
    ds = _cached("sd", load_sd)
    if not ds:
        return Div(H2("SiteDocs"), Div("No data available.", cls="chart-empty"), cls="mt")

    from charts import sd_charts as SDC

    if section_key == "hse":
        sched_c = SD.schedule_counts(ds.schedules)
        f_count = SD.form_counts(ds.forms)
        part = SD.worker_participation(ds.workers, ds.forms)
        brc = SD.bbso_rir_counts(ds.forms)
        cards = [
            kpi_card("Schedule Compliance", sched_c["completion_pct"], "%",
                     rag=rag_for_value(sched_c["completion_pct"], 80, 60)),
            kpi_card("Overdue Items", float(sched_c["overdue"]), "",
                     rag=rag_for_value(sched_c["overdue"], 5, 15, False)),
            kpi_card("BBSO Observations", float(brc["total_bbso"]), "",
                     hint=f"{brc['bbso_this_month']} this month · {brc['bbso_contributors']} observers"),
            kpi_card("RIR / Near Miss Reports", float(brc["total_rir"]), "",
                     hint=f"{brc['rir_this_month']} this month · {brc['rir_contributors']} reporters"),
            kpi_card("Worker Participation", part["pct"], "%",
                     rag=rag_for_value(part["pct"], 80, 60)),
        ]
        return (
            H2("HSE Overview"),
            kpi_grid(cards),
            Div(
                Div(
                    H3("Safety Profile"),
                    NotStr(SDC.safety_profile_table(ds.workers, ds.forms)),
                    cls="panel",
                ),
                cls="mt",
            ),
            Div(
                Div(
                    H3("Top BBSO Observers"),
                    NotStr(SDC.observer_leaderboard_table(ds.workers, ds.forms)),
                    cls="panel",
                ),
                Div(
                    H3("Top RIR / Near Miss Reporters"),
                    NotStr(SDC.reporter_leaderboard_table(ds.workers, ds.forms)),
                    cls="panel",
                ),
                cls="grid two mt",
            ),
            Div(
                Div(
                    H3("Recent RIR / Near Miss Events"),
                    NotStr(SDC.rir_events_from_forms(ds.forms, ds.workers, ds.incidents, ds.locations)),
                    cls="panel",
                ),
                cls="mt",
            ) if hasattr(ds, 'form_responses') and not ds.form_responses.empty else "",
            H3("Trends", style="margin:20px 0 8px;font-size:15px;font-weight:700;"),
            Div(
                _chart("Monthly BBSO", SDC.bbso_trend, ds.forms),
                _chart("Monthly RIR / Near Miss", SDC.rir_trend, ds.forms),
                cls="grid two",
            ),
            Div(
                _chart("BBSO & RIR by Worker", SDC.bbso_rir_leaderboard_table, ds.workers, ds.forms),
                _chart("Overdue Items", SDC.overdue_items_list, ds.schedules),
                cls="grid two mt",
            ),
            Div(
                _chart("Schedule Compliance", SDC.schedule_compliance, ds.schedules),
                _chart("Forms by Category", SDC.form_category_chart, ds.forms),
                cls="grid two mt",
            ),
            Div(id="sd-forms-list"),
        )

    elif section_key == "forms":
        f_count = SD.form_counts(ds.forms)
        w_count = SD.worker_counts(ds.workers)
        brc = SD.bbso_rir_counts(ds.forms)
        cards = [
            kpi_card("Total Forms", float(f_count["total"]), ""),
            kpi_card("This Month", float(f_count["month"]), ""),
            kpi_card("BBSO", float(brc["total_bbso"]), "",
                     hint=f"{brc['bbso_this_month']} this month"),
            kpi_card("RIR / Near Miss", float(brc["total_rir"]), "",
                     hint=f"{brc['rir_this_month']} this month"),
            kpi_card("Active Workers", float(w_count["active"]), ""),
        ]
        return (
            H2("Forms & JSAs"),
            kpi_grid(cards),
            Div(
                _chart("Forms by Category", SDC.form_category_chart, ds.forms),
                _chart("Monthly Trend", SDC.forms_trend, ds.forms),
                cls="grid two"),
            Div(
                _chart("Monthly BBSO Trend", SDC.bbso_trend, ds.forms),
                _chart("Monthly RIR / Near Miss Trend", SDC.rir_trend, ds.forms),
                cls="grid two mt"),
            Div(
                _chart("Forms by Type", SDC.form_types_chart, ds.formtypes, ds.forms),
                cls="mt"),
            Div(id="sd-forms-list"),
        )

    elif section_key == "compliance":
        sched_c = SD.schedule_counts(ds.schedules)
        brc = SD.bbso_rir_counts(ds.forms)
        cards = [
            kpi_card("Completion Rate", sched_c["completion_pct"], "%",
                     rag=rag_for_value(sched_c["completion_pct"], 80, 60)),
            kpi_card("Overdue", float(sched_c["overdue"]), "",
                     rag=rag_for_value(sched_c["overdue"], 5, 15, False)),
            kpi_card("Late", float(sched_c["late"]), ""),
            kpi_card("Cancelled", float(sched_c["cancelled"]), ""),
            kpi_card("BBSO This Month", float(brc["bbso_this_month"]), "",
                     hint=f"{brc['total_bbso']} total"),
            kpi_card("RIR This Month", float(brc["rir_this_month"]), "",
                     hint=f"{brc['total_rir']} total"),
        ]
        return (
            H2("Compliance"),
            kpi_grid(cards),
            Div(
                _chart("Schedule Compliance", SDC.schedule_compliance, ds.schedules),
                _chart("Monthly BBSO Trend", SDC.bbso_trend, ds.forms),
                cls="grid two"),
            Div(
                _chart("Monthly RIR / Near Miss Trend", SDC.rir_trend, ds.forms),
                _chart("Forms Trend", SDC.forms_trend, ds.forms),
                cls="grid two mt"),
            Div(
                _chart("BBSO & RIR by Worker", SDC.bbso_rir_leaderboard_table, ds.workers, ds.forms),
                _chart("Overdue & Late Items", SDC.overdue_items_list, ds.schedules),
                cls="mt"),
        )



    elif section_key == "workers":
        w_count = SD.worker_counts(ds.workers)
        part = SD.worker_participation(ds.workers, ds.forms)
        brc = SD.bbso_rir_counts(ds.forms)
        cards = [
            kpi_card("Active Workers", float(w_count["active"]), "",
                     hint=f"of {w_count['total']} total"),
            kpi_card("Contractors", float(w_count["contractors"]), "",
                     hint=f"{w_count['employees']} employees"),
            kpi_card("Participation", part["pct"], "%",
                     rag=rag_for_value(part["pct"], 80, 60)),
            kpi_card("BBSO Contributors", float(brc["bbso_contributors"]), "",
                     hint=f"{brc['total_bbso']} total BBSOs"),
            kpi_card("RIR Contributors", float(brc["rir_contributors"]), "",
                     hint=f"{brc['total_rir']} total RIRs"),
        ]
        return (
            H2("Workers"),
            kpi_grid(cards),
            Div(
                _chart("Active vs Inactive", SDC.worker_status, ds.workers),
                _chart("Employee vs Contractor", SDC.worker_type_split, ds.workers),
                cls="grid two"),
            Div(
                _chart("BBSO & RIR by Worker", SDC.bbso_rir_leaderboard_table, ds.workers, ds.forms),
                _chart("Worker Activity", SDC.worker_leaderboard_table, ds.workers, ds.forms, ds.signatures, ds.schedules),
                cls="grid two mt"),
        )



    return Div(H2("SiteDocs"), Div("Section not found.", cls="chart-empty"))


# ── GeoTab Section Renderer ──────────────────────────────────────────

def _fig_html(fig, height=300):
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=5, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, system-ui, sans-serif", size=11),
        yaxis=dict(gridcolor="#e2e8f0"), xaxis=dict(gridcolor="#f1f5f9"),
    )
    return fig.to_html(include_plotlyjs=False, full_html=False, config={"displayModeBar": False})

def _gt_controls(section_key, range_key):
    btns = []
    for rk, rl in RANGE_PRESETS:
        active = "active" if range_key == rk else ""
        btns.append(Button(rl, cls=f"preset {active}",
            hx_get=f"/view?platform=gt&section={section_key}&range={rk}", hx_target="#content"))
    return Div(Span("Range:", cls="lbl"), *btns, cls="controls")


def render_gt_section(section_key="fleet", range_key="all"):
    start, end = resolve_date_range(range_key)
    since = datetime.combine(start, datetime.min.time()).replace(tzinfo=timezone.utc)
    until = datetime.combine(end, datetime.max.time()).replace(tzinfo=timezone.utc)
    I = "#2563eb"
    ctrl = _gt_controls(section_key, range_key)

    # ── Fleet Overview ──
    if section_key == "fleet":
        s = GT.fleet_summary(since, until)
        tr = GT.daily_trends(since, until)
        ut = GT.vehicle_utilization(since, until)
        il = GT.idling_summary(since, until)
        sp = GT.speed_analysis(since, until)

        kpi_row = Div(
            _kpi("Active Vehicles", s["active_vehicles"], f"of {s['total_vehicles']}"),
            _kpi("Fleet Miles", s["total_fleet_miles"]),
            _kpi("Avg Speed", round(sp.get("avg_speed",0),1), f"Max {round(sp.get('max_speed',0),1)} mph"),
            _kpi("Speeding", sp.get("speeding_count",0)),
            cls="kpis",
        )

        # Mileage trend line chart
        mt_html = _empty
        if tr:
            df = pd.DataFrame(tr)
            if df["mileage"].sum() > 0:
                df["d"] = pd.to_datetime(df["day"])
                fig = go.Figure(go.Scatter(x=df["d"], y=df["mileage"],
                    mode="lines+markers", line=dict(color=I, width=2.5, shape="spline"),
                    marker=dict(size=5), fill="tozeroy", fillcolor=_rgba(I, 0.10),
                    hovertemplate="%{x|%b %d}<br>%{y:,.0f} mi<extra></extra>"))
                mt_html = _fig_html(fig)

        # Utilization bar chart
        ul_html = _empty
        if ut:
            top = [u for u in ut if u["total_miles"] > 0]
            if top:
                labels = [u.get("assigned_driver","") or u["label"] for u in top]
                fig = go.Figure(go.Bar(x=[u["total_miles"] for u in top], y=labels,
                    orientation="h", marker=dict(color=I),
                    hovertemplate="%{y}<br>%{x:,.0f} mi<extra></extra>"))
                fig.update_layout(yaxis=dict(autorange="reversed"))
                ul_html = _fig_html(fig)

        # Speed histogram
        sh_html = _empty
        sd = sp.get("speed_distribution", [])
        if sd:
            fig = go.Figure(go.Histogram(x=sd, marker=dict(color="#ea580c"),
                hovertemplate="%{x:.0f} mph<br>%{y} records<extra></extra>"))
            sh_html = _fig_html(fig)

        # Idle bar chart
        ih_html = _empty
        iv = il.get("vehicles", [])
        if iv:
            active = [v for v in iv if v["idle_pct"] > 0][:10]
            if active:
                labels = [v.get("assigned_driver","") or v["label"] for v in active]
                fig = go.Figure(go.Bar(x=[v["idle_pct"] for v in active], y=labels,
                    orientation="h", marker=dict(color="#ea580c"),
                    hovertemplate="%{y}<br>%{x:.1f}%<extra></extra>"))
                fig.update_layout(yaxis=dict(autorange="reversed"))
                ih_html = _fig_html(fig)

        # Vehicle detail table
        vt_html = _empty
        if ut:
            def _vt():
                h = ["Vehicle/Driver", "Miles", "Hours", "Util %"]
                trs = ""
                for u in ut:
                    lbl = u.get("assigned_driver","") or u["label"]
                    trs += f"<tr><td>{lbl}</td><td class='num'>{u['total_miles']:,.0f}</td>"
                    trs += f"<td class='num'>{u['hours_driven']:.1f}</td>"
                    trs += f"<td class='num'>{u['utilization_percentage']:.1f}%</td></tr>"
                return f"<div class='tbl-wrap'><table class='data'><thead><tr>{''.join(f'<th>{c}</th>' for c in h)}</tr></thead><tbody>{trs}</tbody></table></div>"
            vt_html = _vt()

        return ctrl, kpi_row, Div(
            Div(panel("Daily Mileage", mt_html, dot=I), panel("Vehicle Utilization", ul_html, dot=I), cls="grid two"),
            Div(panel("Speed Distribution", sh_html, dot="#ea580c"), panel("Idle Time", ih_html, dot="#ea580c"), cls="grid two mt"),
            Div(panel("Vehicle Details", NotStr(vt_html), scroll=True), cls="grid mt"),
        )

    # ── Safety ──
    if section_key == "safety":
        sb = GT.seatbelt_analysis(since, until)
        ah = GT.after_hours_analysis(since, until)
        sd = GT.safety_driver_rankings(since, until)

        # Seatbelt stacked bar
        sb_html = _empty
        if sb:
            df = pd.DataFrame(sb)
            if df["seatbelt_off"].sum() > 0 or df["seatbelt_on"].sum() > 0:
                df["d"] = pd.to_datetime(df["day"])
                fig = go.Figure()
                fig.add_trace(go.Bar(x=df["d"], y=df["seatbelt_off"], name="No Belt",
                    marker=dict(color="#dc2626"), hovertemplate="%{x|%b %d}<br>%{y}<extra></extra>"))
                fig.add_trace(go.Bar(x=df["d"], y=df["seatbelt_on"], name="Belt On",
                    marker=dict(color="#16a34a")))
                fig.update_layout(barmode="stack", showlegend=True, legend=dict(orientation="h", y=1.1, font=dict(size=9)))
                sb_html = _fig_html(fig)

        # After-hours stacked bar
        ah_html = _empty
        if ah:
            df = pd.DataFrame(ah)
            if df["after_hours_miles"].sum() > 0 or df["work_miles"].sum() > 0:
                df["d"] = pd.to_datetime(df["day"])
                fig = go.Figure()
                fig.add_trace(go.Bar(x=df["d"], y=df["work_miles"], name="Work",
                    marker=dict(color=I), hovertemplate="%{x|%b %d}<br>%{y:.0f} mi<extra></extra>"))
                fig.add_trace(go.Bar(x=df["d"], y=df["after_hours_miles"], name="After-Hours",
                    marker=dict(color="#ea580c")))
                fig.update_layout(barmode="stack", showlegend=True, legend=dict(orientation="h", y=1.1, font=dict(size=9)))
                ah_html = _fig_html(fig)

        # Safety score chart
        sc_html = _empty
        sd_table_html = _empty
        if sd:
            active = [d for d in sd if d["trip_count"] > 0][:15]
            if active:
                colors = ["#16a34a" if s["score"]>=80 else "#ea580c" if s["score"]>=60 else "#dc2626" for s in active]
                fig = go.Figure(go.Bar(x=[d["score"] for d in active], y=[d["name"] for d in active],
                    orientation="h", marker=dict(color=colors),
                    hovertemplate="%{y}<br>Score: %{x}<extra></extra>"))
                fig.update_layout(xaxis=dict(range=[0,100]), yaxis=dict(autorange="reversed"))
                sc_html = _fig_html(fig)

            trs = ""
            for d in sd[:20]:
                bg = "green" if d["score"]>=80 else "warn" if d["score"]>=60 else "red"
                trs += f"<tr><td>{d['name']}</td><td class='num'>{d['trip_count']}</td>"
                trs += f"<td class='num'>{d['seatbelt_violation_pct']:.0f}%</td>"
                trs += f"<td class='num'>{d['after_hours_pct']:.0f}%</td>"
                trs += f"<td class='num'>{d['idle_pct']:.0f}%</td>"
                trs += f"<td class='num'>{d['speeding_pct']:.0f}%</td>"
                trs += f"<td><span class='badge {bg}'>{d['score']}</span></td></tr>"
            sd_table_html = f"<div class='tbl-wrap' style='max-height:400px'><table class='data'><thead><tr><th>Driver</th><th class='num'>Trips</th><th class='num'>Seatbelt</th><th class='num'>After-Hrs</th><th class='num'>Idle</th><th class='num'>Speeding</th><th class='num'>Score</th></tr></thead><tbody>{trs}</tbody></table></div>"

        return ctrl, Div(
            Div(panel("Seatbelt Violations", sb_html, dot="#dc2626"), panel("Work vs After-Hours", ah_html, dot="#ea580c"), cls="grid two"),
            Div(panel("Driver Safety Score", sc_html, dot="#16a34a"), panel("Safety Details", NotStr(sd_table_html), scroll=True), cls="grid two mt"),
        )

    # ── Exceptions ──
    if section_key == "exceptions":
        exc = GT.exception_analysis(since, until)
        total = exc.get("total", 0)
        if total == 0:
            return ctrl, Div(H2("No Exceptions"), Div("No exception events in this period.", cls="chart-empty"))

        by_type = exc.get("by_type", [])
        by_vehicle = exc.get("by_vehicle", [])

        bt_html = _empty
        if by_type:
            fig = go.Figure(go.Bar(x=[t["count"] for t in by_type], y=[t["event_type"] for t in by_type],
                orientation="h", marker=dict(color="#dc2626"),
                hovertemplate="%{y}<br>%{x}<extra></extra>"))
            fig.update_layout(yaxis=dict(autorange="reversed"))
            bt_html = _fig_html(fig)

        bv_html = _empty
        if by_vehicle:
            labels = [v.get("driver","") or v["vehicle"] for v in by_vehicle]
            fig = go.Figure(go.Bar(x=[v["count"] for v in by_vehicle], y=labels,
                orientation="h", marker=dict(color="#ea580c"),
                hovertemplate="%{y}<br>%{x}<extra></extra>"))
            fig.update_layout(yaxis=dict(autorange="reversed"))
            bv_html = _fig_html(fig)

        return ctrl, Div(
            Div(H2(f"Exceptions ({total})"), cls="header"),
            Div(panel("By Type", bt_html, dot="#dc2626"), panel("By Vehicle", bv_html, dot="#ea580c"), cls="grid two"),
        )

    # ── Maintenance ──
    if section_key == "maintenance":
        mt = GT.vehicle_maintenance_status(since, until)
        fl = GT.maintenance_metrics(since, until)

        active_mt = [v for v in mt if v.get("odo_mi",0) > 0]
        odom_html = _empty
        if active_mt:
            fig = go.Figure(go.Bar(x=[v["odo_mi"] for v in active_mt],
                y=[v["label"] for v in active_mt],
                orientation="h", marker=dict(color=I),
                hovertemplate="%{y}<br>%{x:,.0f} mi<extra></extra>"))
            fig.update_layout(yaxis=dict(autorange="reversed"))
            odom_html = _fig_html(fig)

        freq = fl.get("fault_frequency", [])
        flt_html = _empty
        if freq:
            fig = go.Figure(go.Bar(x=[f["count"] for f in freq], y=[f["fault_code"] for f in freq],
                orientation="h", marker=dict(color="#dc2626"),
                hovertemplate="%{y}<br>%{x}<extra></extra>"))
            fig.update_layout(yaxis=dict(autorange="reversed"))
            flt_html = _fig_html(fig)

        mt_rows = [[v["label"], f"{v['odo_mi']:,.0f}", f"{v['engine_hours']:,.0f}", f"{v['total_miles']:,.0f}", str(v["trip_count"])]
                   for v in mt if v.get("odo_mi",0) > 0 or v.get("engine_hours",0) > 0]
        mtt_html = _empty
        if mt_rows:
            h = ["Vehicle/Driver", "Odometer (mi)", "Engine Hrs", "Trip Miles", "Trips"]
            trs_parts = []
            for r in mt_rows:
                cells = "".join(f'<td class="num">{c}</td>' if i else f"<td>{c}</td>" for i, c in enumerate(r))
                trs_parts.append(f"<tr>{cells}</tr>")
            trs = "".join(trs_parts)
            mtt_html = f"<div class='tbl-wrap' style='max-height:400px'><table class='data'><thead><tr>{''.join(f'<th>{c}</th>' for c in h)}</tr></thead><tbody>{trs}</tbody></table></div>"

        return ctrl, Div(
            Div(panel("Vehicle Odometer", odom_html, dot=I), panel("Fault Frequency", flt_html, dot="#dc2626"), cls="grid two"),
            Div(panel("Maintenance Status", NotStr(mtt_html), scroll=True), cls="grid mt"),
        )

    return ctrl, Div(H2("GeoTab"), Div("Section not found.", cls="chart-empty"))


_empty = Div("No data for this period.", cls="chart-empty")


def _kpi(label, value, hint=""):
    if value is None: val = "—"
    elif isinstance(value, float):
        val = f"{int(value):,}" if value == int(value) else f"{value:,.1f}"
    else: val = f"{value:,}"
    return Div(Div(label, cls="k-label"), Div(val, cls="k-value"),
               Div(hint, cls="k-hint") if hint else "", cls="kpi")


# ── Routes ────────────────────────────────────────────────────────────────

@rt("/health")
async def health(req):
    return "OK"


@rt("/_dbcheck")
async def db_check(req):
    """Diagnostic - checks both DB connections and lists tables."""
    import traceback
    from sqlalchemy import create_engine, text

    def try_connect(label, env_var):
        try:
            url = os.getenv(env_var, "")
            if not url:
                return f"{label}: NOT SET"
            if "sslmode" not in url:
                url += "&sslmode=require" if "?" in url else "?sslmode=require"
            eng = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
            with eng.connect() as c:
                result = c.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name"))
                tables = [r[0] for r in result]
            return f"{label}: OK ({len(tables)} tables: {', '.join(tables[:30])})"
        except Exception as e:
            tb = traceback.format_exc()
            return f"{label}: ERROR — {e}"

    lines = [
        try_connect("QB", "QB_DATABASE_URL"),
        "",
        try_connect("SD", "SD_DATABASE_URL"),
    ]
    return Pre("\n".join(lines))


@rt("/login")
async def login(req):
    if req.session.get("user"):
        return RedirectResponse("/", status_code=303)
    error = None
    next_url = req.query_params.get("next", "/")
    if req.method == "POST":
        form = await req.form()
        email = (form.get("email") or "").strip().lower()
        password = form.get("password") or ""
        next_url = form.get("next") or "/"
        # Validate email domain
        if AUTH_DOMAIN and not email.endswith(f"@{AUTH_DOMAIN}"):
            error = "Invalid email or password."
        # Validate password
        elif AUTH_PASSWORD_HASH:
            if not _verify_password(password, AUTH_PASSWORD_HASH):
                error = "Invalid email or password."
        elif AUTH_PASSWORD:
            if not compare_digest(password.encode(), AUTH_PASSWORD.encode()):
                error = "Invalid email or password."
        else:
            error = "No password configured."
        if not error:
            req.session["user"] = email
            return RedirectResponse(next_url, status_code=303)
    return Title("Login"), Div(
        Div(
            H2("EWS Unified Dashboard", style="margin-bottom:4px;"),
            P("Sign in", style="color:var(--muted);margin:0 0 20px;"),
            Div(P(error, style="color:var(--bad);font-size:13px;margin-bottom:12px;"),
                style="background:#fef2f2;padding:10px 14px;border-radius:8px;border:1px solid #fecaca;") if error else "",
            Form(
                Input(type="email", name="email", placeholder="you@company.com",
                      required=True, style="width:100%;padding:10px;margin-bottom:10px;border:1px solid var(--line);border-radius:8px;"),
                Input(type="password", name="password", placeholder="Password",
                      required=True, style="width:100%;padding:10px;margin-bottom:14px;border:1px solid var(--line);border-radius:8px;"),
                Input(type="hidden", name="next", value=next_url),
                Button("Sign in", type="submit",
                       style="width:100%;padding:10px;background:var(--navy);color:#fff;border:none;border-radius:8px;font-weight:600;cursor:pointer;"),
                method="post", action="/login",
            ),
            style="max-width:360px;margin:80px auto;background:#fff;padding:32px;border-radius:16px;border:1px solid var(--line);"
        ),
        style="max-width:400px;margin:0 auto;padding:40px 20px;"
    )


@rt("/_gt_check")
async def gt_check(req):
    """Diagnostic: show GT vehicle-driver relationships from the actual data."""
    from sqlalchemy import text
    try:
        db = load_gt()
        out = []
        
        # Check trips with/without driver_id
        r = db.execute(text("SELECT COUNT(*) as total, COUNT(driver_id) as with_driver, COUNT(*) - COUNT(driver_id) as no_driver FROM trips"))
        row = r.one()
        out.append(f"Trips: {row.total} total, {row.with_driver} with driver, {row.no_driver} without driver")
        
        # Sample trips with driver info
        r = db.execute(text("""
            SELECT t.id, t.vehicle_id, t.driver_id, d.name as driver_name,
                   v.license_plate, v.vin
            FROM trips t
            LEFT JOIN drivers d ON d.id = t.driver_id
            LEFT JOIN vehicles v ON v.id = t.vehicle_id
            WHERE t.driver_id IS NOT NULL
            LIMIT 10
        """))
        out.append("\n\nTrips WITH driver (sample 10):")
        for row in r:
            out.append(f"  Trip {row.id}: vehicle={row.vehicle_id} ({row.license_plate or row.vin}), driver={row.driver_id} ({row.driver_name or '?'})")
        
        # Top vehicles by driver count (vehicles with most distinct drivers)
        r = db.execute(text("""
            SELECT v.id, v.license_plate, v.vin,
                   COUNT(DISTINCT t.driver_id) as num_drivers,
                   COUNT(*) as trip_count
            FROM trips t
            JOIN vehicles v ON v.id = t.vehicle_id
            WHERE t.driver_id IS NOT NULL
            GROUP BY v.id
            ORDER BY num_drivers DESC
            LIMIT 10
        """))
        out.append("\n\nVehicles with most distinct drivers:")
        for row in r:
            out.append(f"  Vehicle {row.id}: {row.license_plate or row.vin} — {row.num_drivers} drivers, {row.trip_count} trips")
        
        # Check if any trips have driver_id = NULL
        r = db.execute(text("""
            SELECT COUNT(*) as null_count
            FROM trips
            WHERE driver_id IS NULL
        """))
        null_count = r.scalar()
        out.append(f"\n\nTrips with NULL driver_id: {null_count}")
        
        # Check if drivers table has any records
        r = db.execute(text("SELECT COUNT(*) FROM drivers"))
        out.append(f"\nTotal drivers in DB: {r.scalar()}")
        
        # Check if vehicles table has any records
        r = db.execute(text("SELECT COUNT(*) FROM vehicles"))
        out.append(f"\nTotal vehicles in DB: {r.scalar()}")
        
        # Show all drivers
        r = db.execute(text("SELECT id, name, geotab_id, employee_id FROM drivers LIMIT 20"))
        out.append("\n\nAll drivers:")
        for row in r:
            out.append(f"  Driver {row.id}: {row.name} (geotab={row.geotab_id}, emp={row.employee_id})")
        
        db.close()
        return Pre("\n".join(out))
    except Exception as e:
        import traceback
        return Pre(f"Error: {e}\\n{traceback.format_exc()}")


@rt("/_gt_sync_now")
async def gt_sync_now(req):
    """One-shot: sync all Geotab users into drivers table."""
    from sqlalchemy import text
    import requests
    try:
        # Get Geotab credentials
        gt_db = os.getenv("GEOTAB_DATABASE")
        gt_user = os.getenv("GEOTAB_USERNAME")
        gt_pass = os.getenv("GEOTAB_PASSWORD")
        gt_server = os.getenv("GEOTAB_SERVER", "my.geotab.com")
        
        if not all([gt_db, gt_user, gt_pass]):
            return Pre("ERROR: GEOTAB_DATABASE, GEOTAB_USERNAME, GEOTAB_PASSWORD must be set as env vars")
        
        # Authenticate with Geotab API
        base = f"https://{gt_server}/apiv1"
        auth_resp = requests.post(base, json={
            "method": "Authenticate",
            "params": {
                "database": gt_db,
                "userName": gt_user,
                "password": gt_pass,
            }
        }, timeout=30)
        auth_data = auth_resp.json()
        if "error" in auth_data:
            return Pre(f"Geotab API auth error: {auth_data['error']}")
        creds = auth_data.get("result", {}).get("credentials", auth_data.get("result", {}))
        
        # Fetch all Users
        get_resp = requests.post(base, json={
            "method": "Get",
            "params": {
                "typeName": "User",
                "credentials": creds,
                "resultsLimit": 50000,
            }
        }, timeout=60)
        get_data = get_resp.json()
        users = get_data.get("result", []) if isinstance(get_data.get("result"), list) else []
        
        # Insert into drivers table
        db = load_gt()
        inserted = 0
        for u in users:
            uid = str(u.get("id", ""))
            first = u.get("firstName", "")
            last = u.get("lastName", "")
            name = u.get("name") or f"{first} {last}".strip() or uid
            emp = u.get("employeeNo") or u.get("employeeId") or ""
            db.execute(text(
                "INSERT INTO drivers (geotab_id, name, employee_id, created_at, updated_at) "
                "VALUES (:gid, :name, :emp, NOW(), NOW()) "
                "ON CONFLICT (geotab_id) DO UPDATE SET name=:name2, employee_id=:emp2, updated_at=NOW()"
            ), {"gid": uid, "name": name, "emp": emp, "name2": name, "emp2": emp})
            inserted += 1
        db.commit()
        db.close()
        return Pre(f"Synced {inserted} users into drivers table.")
    except Exception as e:
        import traceback
        return Pre(f"Error: {e}\n{traceback.format_exc()}")


@rt("/_gt_inspect_trip")
async def gt_inspect_trip(req):
    """Show sample raw trip data from Geotab API to check driver field."""
    import requests, json
    try:
        gt_db = os.getenv("GEOTAB_DATABASE")
        gt_user = os.getenv("GEOTAB_USERNAME")
        gt_pass = os.getenv("GEOTAB_PASSWORD")
        gt_server = os.getenv("GEOTAB_SERVER", "my.geotab.com")
        if not all([gt_db, gt_user, gt_pass]):
            return Pre("ERROR: missing Geotab credentials")

        base = f"https://{gt_server}/apiv1"
        auth_resp = requests.post(base, json={
            "method": "Authenticate",
            "params": {"database": gt_db, "userName": gt_user, "password": gt_pass}
        }, timeout=30)
        auth_data = auth_resp.json()
        if "error" in auth_data:
            return Pre(f"Auth error: {auth_data['error']}")
        creds = auth_data.get("result", {}).get("credentials", auth_data.get("result", {}))

        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        since = now - datetime.timedelta(days=7)
        
        # Fetch just 3 trips to inspect
        get_resp = requests.post(base, json={
            "method": "Get",
            "params": {
                "typeName": "Trip",
                "credentials": creds,
                "search": {"fromDate": since.isoformat().replace("+00:00", "Z")},
                "resultsLimit": 3,
            }
        }, timeout=60)
        raw = get_resp.json()
        trips = raw.get("result", [])
        if not trips:
            # Try without date filter
            get_resp = requests.post(base, json={
                "method": "Get",
                "params": {"typeName": "Trip", "credentials": creds, "resultsLimit": 3}
            }, timeout=60)
            raw = get_resp.json()
            trips = raw.get("result", [])
        
        out = []
        out.append(f"Total trips returned: {len(trips)}")
        for i, t in enumerate(trips):
            out.append(f"\n--- Trip {i+1} ---")
            out.append(f"ID: {t.get('id')}")
            out.append(f"device: {t.get('device')}")
            out.append(f"driver: {t.get('driver')}")
            # Show all keys
            out.append(f"All keys: {', '.join(sorted(t.keys()))}")
            # Show relevant values
            for key in ['start', 'stop', 'distance', 'idlingDuration']:
                out.append(f"  {key}: {t.get(key)}")
        
        return Pre("\n".join(out))
    except Exception as e:
        import traceback
        return Pre(f"Error: {e}\\n{traceback.format_exc()}")


@rt("/_gt_inspect_device")
async def gt_inspect_device(req):
    """Show 3 sample Device records from Geotab to check driver-related fields."""
    import requests, json
    try:
        gt_db = os.getenv("GEOTAB_DATABASE")
        gt_user = os.getenv("GEOTAB_USERNAME")
        gt_pass = os.getenv("GEOTAB_PASSWORD")
        gt_server = os.getenv("GEOTAB_SERVER", "my.geotab.com")
        if not all([gt_db, gt_user, gt_pass]):
            return Pre("ERROR: missing Geotab credentials")

        base = f"https://{gt_server}/apiv1"
        auth_resp = requests.post(base, json={
            "method": "Authenticate",
            "params": {"database": gt_db, "userName": gt_user, "password": gt_pass}
        }, timeout=30)
        auth_data = auth_resp.json()
        if "error" in auth_data:
            return Pre(f"Auth error: {auth_data['error']}")
        creds = auth_data.get("result", {}).get("credentials", auth_data.get("result", {}))

        # Fetch 3 Device records
        get_resp = requests.post(base, json={
            "method": "Get",
            "params": {"typeName": "Device", "credentials": creds, "resultsLimit": 3}
        }, timeout=60)
        raw = get_resp.json()
        devices = raw.get("result", [])

        out = []
        out.append(f"Total devices returned: {len(devices)}")
        for i, d in enumerate(devices):
            out.append(f"\n--- Device {i+1} ---")
            out.append(f"ID: {d.get('id')}")
            out.append(f"VIN: {d.get('vehicleIdentificationNumber') or d.get('vin') or 'N/A'}")
            out.append(f"Plate: {d.get('licensePlate') or 'N/A'}")
            out.append(f"Make/Model: {d.get('make') or ''} {d.get('model') or ''} ({d.get('year') or ''})")
            out.append(f"All keys: {', '.join(sorted(d.keys()))}")
            for key in sorted(d.keys()):
                val = d[key]
                if isinstance(val, dict) and any(k in str(val).lower() for k in ['driver', 'user', 'person']):
                    out.append(f"  -> {key}: {val}")
            for key in ['driver', 'licenseType', 'deviceType', 'property', 'properties', 'customProperties']:
                if key in d:
                    out.append(f"  {key}: {d[key]}")
        return Pre("\n".join(out))
    except Exception as e:
        import traceback
        return Pre(f"Error: {e}\\n{traceback.format_exc()}")


@rt("/_gt_assign_drivers")
async def gt_assign_drivers(req):
    """Fetch ALL Devices from Geotab and write their 'name' as assigned_driver in vehicles."""
    from sqlalchemy import create_engine, text
    import requests, json, os
    try:
        gt_db = os.getenv("GEOTAB_DATABASE")
        gt_user = os.getenv("GEOTAB_USERNAME")
        gt_pass = os.getenv("GEOTAB_PASSWORD")
        gt_server = os.getenv("GEOTAB_SERVER", "my.geotab.com")
        if not all([gt_db, gt_user, gt_pass]):
            return Pre("ERROR: missing Geotab credentials")

        gt_url = os.getenv("GT_DATABASE_URL", os.getenv("DATABASE_URL", ""))
        if not gt_url:
            return Pre("ERROR: GT_DATABASE_URL (or DATABASE_URL) not set")
        if gt_url.startswith("postgres://"):
            gt_url = gt_url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif gt_url.startswith("postgresql://") and "+psycopg2" not in gt_url:
            gt_url = gt_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        eng = create_engine(gt_url, pool_pre_ping=True, connect_args={"connect_timeout": 5})

        with eng.begin() as conn:
            conn.execute(text("""
                DO $$ BEGIN
                    ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS assigned_driver VARCHAR(255);
                EXCEPTION WHEN duplicate_column THEN null;
                END $$;
            """))

        base = f"https://{gt_server}/apiv1"
        auth_resp = requests.post(base, json={
            "method": "Authenticate",
            "params": {"database": gt_db, "userName": gt_user, "password": gt_pass}
        }, timeout=30)
        auth_data = auth_resp.json()
        if "error" in auth_data:
            return Pre(f"Auth error: {auth_data['error']}")
        creds = auth_data.get("result", {}).get("credentials", auth_data.get("result", {}))

        get_resp = requests.post(base, json={
            "method": "Get",
            "params": {"typeName": "Device", "credentials": creds, "resultsLimit": 50000}
        }, timeout=120)
        raw = get_resp.json()
        devices = raw.get("result", [])
        if not isinstance(devices, list):
            return Pre(f"Unexpected: {json.dumps(raw)[:500]}")

        out = [f"Fetched {len(devices)} devices from Geotab."]
        updated = 0
        skipped = 0
        with eng.begin() as conn:
            for d in devices:
                gid = str(d.get("id", ""))
                if not gid:
                    skipped += 1; continue
                device_name = d.get("name", "") or ""
                vin = d.get("vehicleIdentificationNumber") or d.get("vin") or ""
                plate = d.get("licensePlate") or ""
                r = conn.execute(text(
                    "UPDATE vehicles SET assigned_driver=:name, license_plate=COALESCE(NULLIF(:plate,''),license_plate) WHERE geotab_id=:gid"
                ), {"name": device_name, "plate": plate, "gid": gid})
                if r.rowcount > 0:
                    updated += 1
                    out.append(f"  ✓ {vin[:8]}... → {device_name}")
                else:
                    skipped += 1
        out.append(f"\nUpdated {updated} vehicles. Skipped {skipped}.")
        return Pre("\n".join(out))
    except Exception as e:
        import traceback
        return Pre(f"Error: {e}\\n{traceback.format_exc()}")


@rt("/_gt_migrate_trips")
async def gt_migrate_trips(req):
    """ALTER TABLE trips to add all new columns for enhanced Geotab fields."""
    from sqlalchemy import create_engine, text
    import os
    try:
        gt_url = os.getenv("GT_DATABASE_URL", os.getenv("DATABASE_URL", ""))
        if not gt_url:
            return Pre("ERROR: GT_DATABASE_URL (or DATABASE_URL) not set")
        if gt_url.startswith("postgres://"):
            gt_url = gt_url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif gt_url.startswith("postgresql://") and "+psycopg2" not in gt_url:
            gt_url = gt_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        eng = create_engine(gt_url, pool_pre_ping=True, connect_args={"connect_timeout": 5})

        columns = [
            ("average_speed", "FLOAT"),
            ("maximum_speed", "FLOAT"),
            ("driving_duration", "FLOAT DEFAULT 0"),
            ("engine_hours", "FLOAT DEFAULT 0"),
            ("is_seatbelt_off", "INTEGER"),
            ("after_hours_distance", "FLOAT DEFAULT 0"),
            ("work_distance", "FLOAT DEFAULT 0"),
            ("stop_duration", "FLOAT DEFAULT 0"),
            ("odometer_end", "FLOAT"),
            ("speed_range_1_duration", "FLOAT DEFAULT 0"),
            ("speed_range_2_duration", "FLOAT DEFAULT 0"),
            ("speed_range_3_duration", "FLOAT DEFAULT 0"),
        ]

        out = []
        with eng.begin() as conn:
            for col_name, col_type in columns:
                try:
                    conn.execute(text(
                        f"ALTER TABLE trips ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
                    ))
                    out.append(f"  ✓ {col_name} ({col_type})")
                except Exception as e:
                    try:
                        # Fallback for older PG
                        conn.execute(text(f"ALTER TABLE trips ADD COLUMN {col_name} {col_type}"))
                        out.append(f"  ✓ {col_name} ({col_type}) [fallback]")
                    except Exception as e2:
                        if "already exists" in str(e2).lower():
                            out.append(f"  — {col_name} (already exists)")
                        else:
                            out.append(f"  ✗ {col_name}: {str(e2)[:100]}")

        conn = eng.connect()
        r = conn.execute(text("SELECT COUNT(*) FROM trips"))
        trip_count = r.scalar()
        r = conn.execute(text("SELECT COUNT(odometer_end) FROM trips WHERE odometer_end IS NOT NULL"))
        odom_count = r.scalar()
        conn.close()
        eng.dispose()

        return Pre(
            "=== Trip Table Migration ==="
            + "\n" + "\n".join(out)
            + f"\n\nTotal trips in DB: {trip_count}"
            + f"\nTrips with odometer: {odom_count}"
            + "\n\nPhase 1 complete. New columns added to trips table."
        )
    except Exception as e:
        import traceback
        return Pre(f"Error: {e}\\n{traceback.format_exc()}")


@rt("/_gt_enhanced_sync")
async def gt_enhanced_sync(req):
    """Re-fetch ALL trips from Geotab with full fields + create exception_events table."""
    from sqlalchemy import create_engine, text, types
    import requests, json, os, datetime, time
    try:
        gt_db = os.getenv("GEOTAB_DATABASE")
        gt_user = os.getenv("GEOTAB_USERNAME")
        gt_pass = os.getenv("GEOTAB_PASSWORD")
        gt_server = os.getenv("GEOTAB_SERVER", "my.geotab.com")
        gt_url = os.getenv("GT_DATABASE_URL", os.getenv("DATABASE_URL", ""))
        if not all([gt_db, gt_user, gt_pass]):
            return Pre("ERROR: missing Geotab credentials")
        if not gt_url:
            return Pre("ERROR: GT_DATABASE_URL not set")

        if gt_url.startswith("postgres://"):
            gt_url = gt_url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif gt_url.startswith("postgresql://") and "+psycopg2" not in gt_url:
            gt_url = gt_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        eng = create_engine(gt_url, pool_pre_ping=True, connect_args={"connect_timeout": 5})

        out_lines = []
        step_start = time.time()

        # ── Step 1: Ensure all columns exist ──
        new_cols = [
            ("average_speed", "FLOAT"),
            ("maximum_speed", "FLOAT"),
            ("driving_duration", "FLOAT DEFAULT 0"),
            ("engine_hours", "FLOAT DEFAULT 0"),
            ("is_seatbelt_off", "INTEGER"),
            ("after_hours_distance", "FLOAT DEFAULT 0"),
            ("work_distance", "FLOAT DEFAULT 0"),
            ("stop_duration", "FLOAT DEFAULT 0"),
            ("odometer_end", "FLOAT"),
            ("speed_range_1_duration", "FLOAT DEFAULT 0"),
            ("speed_range_2_duration", "FLOAT DEFAULT 0"),
            ("speed_range_3_duration", "FLOAT DEFAULT 0"),
        ]
        with eng.begin() as conn:
            for name, typ in new_cols:
                conn.execute(text(f"ALTER TABLE trips ADD COLUMN IF NOT EXISTS {name} {typ}"))
        out_lines.append(f"Step 1: Columns ensured ({len(new_cols)} cols)")

        # ── Step 2: Create exception_events table ──
        with eng.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS exception_events (
                    id SERIAL PRIMARY KEY,
                    geotab_event_id VARCHAR(128) UNIQUE,
                    vehicle_id INTEGER REFERENCES vehicles(id) ON DELETE CASCADE,
                    driver_id INTEGER REFERENCES drivers(id) ON DELETE SET NULL,
                    event_type VARCHAR(64),
                    event_description TEXT,
                    timestamp TIMESTAMP WITH TIME ZONE,
                    rule_name VARCHAR(255),
                    latitude FLOAT,
                    longitude FLOAT,
                    speed FLOAT,
                    zone_name VARCHAR(255),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_exception_events_ts ON exception_events(timestamp)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_exception_events_type ON exception_events(event_type)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_exception_events_vehicle ON exception_events(vehicle_id)"))
        out_lines.append("Step 2: exception_events table ready")

        # ── Step 3: Authenticate with Geotab API ──
        base = f"https://{gt_server}/apiv1"
        auth_resp = requests.post(base, json={
            "method": "Authenticate",
            "params": {"database": gt_db, "userName": gt_user, "password": gt_pass}
        }, timeout=30)
        auth_data = auth_resp.json()
        if "error" in auth_data:
            return Pre(f"Auth error: {auth_data['error']}")
        creds = auth_data.get("result", {}).get("credentials", auth_data.get("result", {}))
        out_lines.append(f"Step 3: Authenticated")

        # ── Step 4: Fetch all trips (90-day lookback, bisect) ──
        KM_TO_MILES = 0.621371
        LITERS_TO_GALLONS = 0.264172
        now = datetime.datetime.now(datetime.timezone.utc)
        since = now - datetime.timedelta(days=365)

        def parse_dur(val):
            if val is None or val == "" or val == 0:
                return 0.0
            if isinstance(val, (int, float)):
                return float(val)
            text = str(val).strip()
            parts = text.split(":")
            if len(parts) == 3:
                try: return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
                except: return 0.0
            try: return float(text)
            except: return 0.0

        def parse_idling(val):
            if val is None or val == "" or val == 0: return 0.0
            if isinstance(val, (int, float)): return float(val)
            text = str(val).strip()
            parts = text.split(":")
            if len(parts) == 3:
                try: return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
                except: return 0.0
            try: return float(text)
            except: return 0.0

        def fetch_bisect(from_dt, to_dt, depth=0):
            if depth > 10: return []
            search = {"fromDate": from_dt.isoformat().replace("+00:00", "Z"),
                       "toDate": to_dt.isoformat().replace("+00:00", "Z")}
            r = requests.post(base, json={
                "method": "Get", "params": {
                    "typeName": "Trip", "credentials": creds,
                    "search": search, "resultsLimit": 50000
                }
            }, timeout=120)
            data = r.json()
            items = data.get("result", [])
            if isinstance(items, list) and len(items) < 50000:
                return items
            # Hit limit, bisect
            mid = from_dt + (to_dt - from_dt) / 2
            gap = int((to_dt - from_dt).total_seconds())
            if gap < 3600:  # < 1 hour, accept partial
                return items if isinstance(items, list) else []
            first = fetch_bisect(from_dt, mid, depth+1)
            second = fetch_bisect(mid, to_dt, depth+1)
            return first + second

        trips_raw = fetch_bisect(since, now)
        out_lines.append(f"Step 4: Fetched {len(trips_raw)} trips from Geotab API")

        # ── Step 5: Build vehicle map ──
        with eng.connect() as conn:
            rows = conn.execute(text("SELECT geotab_id, id FROM vehicles")).all()
            vehicle_map = {r[0]: r[1] for r in rows}
            driver_rows = conn.execute(text("SELECT geotab_id, id FROM drivers")).all()
            driver_map = {r[0]: r[1] for r in rows}
        out_lines.append(f"Step 5: Vehicle map ({len(vehicle_map)}) / Driver map ({len(driver_map)})")

        # ── Step 6: Upsert trips ──
        updated = 0
        skipped = 0
        batch = []
        for trip in trips_raw:
            trip_id = str(trip.get("id", ""))
            if not trip_id: continue
            device_raw = trip.get("device")
            veh_gid = str(device_raw.get("id", "")) if isinstance(device_raw, dict) else ""
            veh_id = vehicle_map.get(veh_gid)
            if not veh_id:
                skipped += 1
                continue

            driver_raw = trip.get("driver")
            drv_gid = None
            if isinstance(driver_raw, dict): drv_gid = str(driver_raw.get("id", ""))
            elif driver_raw: drv_gid = str(driver_raw)
            drv_id = driver_map.get(drv_gid) if drv_gid else None

            distance = float(trip.get("distance", 0) or 0) * KM_TO_MILES
            fuel = float(trip.get("fuelUsed", 0) or 0) * LITERS_TO_GALLONS
            idle = parse_idling(trip.get("idlingDuration"))
            avg_speed = float(trip["averageSpeed"]) if trip.get("averageSpeed") else None
            max_speed = float(trip["maximumSpeed"]) if trip.get("maximumSpeed") else None
            drive_dur = parse_dur(trip.get("drivingDuration"))
            eng_hrs = float(trip.get("engineHours", 0) or 0)
            seatbelt = 1 if trip.get("isSeatBeltOff") else (0 if trip.get("isSeatBeltOff") is not None else None)
            after_hrs = float(trip.get("afterHoursDistance", 0) or 0) * KM_TO_MILES
            work_dist = float(trip.get("workDistance", 0) or 0) * KM_TO_MILES
            stop_dur = parse_dur(trip.get("stopDuration"))
            odo = float(trip["odometer"]) if trip.get("odometer") else None
            sr1 = parse_dur(trip.get("speedRange1Duration"))
            sr2 = parse_dur(trip.get("speedRange2Duration"))
            sr3 = parse_dur(trip.get("speedRange3Duration"))

            start_str = trip.get("start", "")
            end_str = trip.get("stop") or trip.get("end", "")
            start_dt = start_str.replace("Z", "+00:00") if start_str else None
            end_dt = end_str.replace("Z", "+00:00") if end_str else None

            batch.append({
                "gid": trip_id, "vid": veh_id, "did": drv_id,
                "start": start_dt, "end": end_dt,
                "dist": distance, "fuel": fuel, "idle": idle,
                "avg_spd": avg_speed, "max_spd": max_speed,
                "drive_dur": drive_dur, "eng_hrs": eng_hrs,
                "belt": seatbelt, "after_hrs": after_hrs, "work": work_dist,
                "stop": stop_dur, "odo": odo,
                "sr1": sr1, "sr2": sr2, "sr3": sr3,
            })

        with eng.begin() as conn:
            for b in batch:
                r = conn.execute(text("""
                    INSERT INTO trips (
                        geotab_trip_id, vehicle_id, driver_id,
                        start_time, end_time, distance_miles, fuel_used, idle_time,
                        average_speed, maximum_speed, driving_duration, engine_hours,
                        is_seatbelt_off, after_hours_distance, work_distance, stop_duration,
                        odometer_end, speed_range_1_duration, speed_range_2_duration, speed_range_3_duration
                    ) VALUES (
                        :gid, :vid, :did,
                        :start, :end, :dist, :fuel, :idle,
                        :avg_spd, :max_spd, :drive_dur, :eng_hrs,
                        :belt, :after_hrs, :work, :stop,
                        :odo, :sr1, :sr2, :sr3
                    )
                    ON CONFLICT (geotab_trip_id) DO UPDATE SET
                        vehicle_id=:vid, driver_id=:did,
                        start_time=:start, end_time=:end,
                        distance_miles=:dist, fuel_used=:fuel, idle_time=:idle,
                        average_speed=:avg_spd, maximum_speed=:max_spd,
                        driving_duration=:drive_dur, engine_hours=:eng_hrs,
                        is_seatbelt_off=:belt, after_hours_distance=:after_hrs,
                        work_distance=:work, stop_duration=:stop, odometer_end=:odo,
                        speed_range_1_duration=:sr1, speed_range_2_duration=:sr2,
                        speed_range_3_duration=:sr3
                """), b)
                updated += 1
        out_lines.append(f"Step 6: Upserted {updated} trips (skipped {skipped})")

        # ── Step 7: Fetch ExceptionEvents (last 30 days) ──
        since_ee = now - datetime.timedelta(days=30)
        r = requests.post(base, json={
            "method": "Get", "params": {
                "typeName": "ExceptionEvent", "credentials": creds,
                "search": {"fromDate": since_ee.isoformat().replace("+00:00", "Z")},
                "resultsLimit": 50000
            }
        }, timeout=120)
        ee_data = r.json()
        ee_items = ee_data.get("result", [])
        if not isinstance(ee_items, list):
            ee_items = []
        out_lines.append(f"Step 7: Fetched {len(ee_items)} exception events")

        ee_inserted = 0
        with eng.begin() as conn:
            for ee in ee_items:
                ee_id = str(ee.get("id", ""))
                if not ee_id: continue
                # Extract vehicle
                dev_raw = ee.get("device")
                veh_gid = str(dev_raw.get("id", "")) if isinstance(dev_raw, dict) else ""
                veh_id = vehicle_map.get(veh_gid)
                # Extract driver
                drv_raw = ee.get("driver")
                drv_gid = None
                if isinstance(drv_raw, dict): drv_gid = str(drv_raw.get("id", ""))
                elif drv_raw: drv_gid = str(drv_raw)
                drv_id = driver_map.get(drv_gid) if drv_gid else None
                # Parse rule info
                rule_raw = ee.get("rule", {})
                rule_name = rule_raw.get("name", "") if isinstance(rule_raw, dict) else ""
                # Event type
                event_type = ee.get("eventType", "") or ee.get("exceptionType", "") or rule_name
                event_desc = ee.get("description") or ee.get("notes", "") or ""
                ts_raw = ee.get("dateTime") or ee.get("timestamp", "")
                ts = ts_raw.replace("Z", "+00:00") if ts_raw else None
                lat = float(ee["latitude"]) if ee.get("latitude") else None
                lon = float(ee["longitude"]) if ee.get("longitude") else None
                speed_val = float(ee["speed"]) if ee.get("speed") else None

                try:
                    conn.execute(text("""
                        INSERT INTO exception_events
                            (geotab_event_id, vehicle_id, driver_id, event_type, event_description,
                             timestamp, rule_name, latitude, longitude, speed)
                        VALUES (:eid, :vid, :did, :type, :desc, :ts, :rule, :lat, :lon, :spd)
                        ON CONFLICT (geotab_event_id) DO UPDATE SET
                            vehicle_id=:vid, driver_id=:did, event_type=:type,
                            event_description=:desc, timestamp=:ts, rule_name=:rule,
                            latitude=:lat, longitude=:lon, speed=:spd
                    """), {"eid": ee_id, "vid": veh_id, "did": drv_id,
                           "type": event_type, "desc": event_desc, "ts": ts,
                           "rule": rule_name, "lat": lat, "lon": lon, "spd": speed_val})
                    ee_inserted += 1
                except Exception:
                    pass

        out_lines.append(f"     Inserted {ee_inserted} exception events")

        elapsed = time.time() - step_start
        out_lines.append(f"\n=== Enhanced Sync Complete in {elapsed:.0f}s ===")
        out_lines.append(f"Trips processed: {updated} | Exception events: {ee_inserted}")
        return Pre("\n".join(out_lines))

    except Exception as e:
        import traceback
        return Pre(f"Error: {e}\\n{traceback.format_exc()}")


@rt("/_gt_inspect_entity")
async def gt_inspect_entity(req):
    """Query any Geotab entity type to inspect its structure."""
    import requests, json, datetime
    try:
        gt_db = os.getenv("GEOTAB_DATABASE")
        gt_user = os.getenv("GEOTAB_USERNAME")
        gt_pass = os.getenv("GEOTAB_PASSWORD")
        gt_server = os.getenv("GEOTAB_SERVER", "my.geotab.com")
        if not all([gt_db, gt_user, gt_pass]):
            return Pre("ERROR: missing Geotab credentials")

        entity = req.query_params.get("entity", "").strip()
        if not entity:
            return Pre("Usage: /_gt_inspect_entity?entity=DriverChange&limit=3")

        limit = int(req.query_params.get("limit", "3"))

        base = f"https://{gt_server}/apiv1"
        auth_resp = requests.post(base, json={
            "method": "Authenticate",
            "params": {"database": gt_db, "userName": gt_user, "password": gt_pass}
        }, timeout=30)
        auth_data = auth_resp.json()
        if "error" in auth_data:
            return Pre(f"Auth error: {auth_data['error']}")
        creds = auth_data.get("result", {}).get("credentials", auth_data.get("result", {}))

        get_resp = requests.post(base, json={
            "method": "Get",
            "params": {"typeName": entity, "credentials": creds, "resultsLimit": limit}
        }, timeout=60)
        raw = get_resp.json()
        items = raw.get("result", [])
        if not isinstance(items, list):
            return Pre(f"Response: {json.dumps(raw, indent=2)[:5000]}")

        out = []
        out.append(f"Total {entity} returned: {len(items)}")
        for i, item in enumerate(items):
            out.append(f"\n--- {entity} {i+1} ---")
            out.append(f"ID: {item.get('id')}")
            # Show all keys and their values (truncated)
            for key in sorted(item.keys()):
                val = item[key]
                val_str = json.dumps(val) if not isinstance(val, str) else val
                if len(val_str) > 200:
                    val_str = val_str[:200] + "..."
                out.append(f"  {key}: {val_str}")
        return Pre("\n".join(out))
    except Exception as e:
        import traceback
        return Pre(f"Error: {e}\\n{traceback.format_exc()}")


@rt("/_gt_sync_device_names")
async def gt_sync_device_names(req):
    """Fetch all Devices from Geotab and update assigned_driver on vehicles table."""
    from sqlalchemy import create_engine, text
    import requests, json, os
    try:
        gt_db = os.getenv("GEOTAB_DATABASE")
        gt_user = os.getenv("GEOTAB_USERNAME")
        gt_pass = os.getenv("GEOTAB_PASSWORD")
        gt_server = os.getenv("GEOTAB_SERVER", "my.geotab.com")
        if not all([gt_db, gt_user, gt_pass]):
            return Pre("ERROR: missing Geotab credentials")

        # Connect to GT database
        gt_db_url = os.getenv("GT_DATABASE_URL")
        if not gt_db_url:
            return Pre("ERROR: GT_DATABASE_URL not set")
        if gt_db_url.startswith("postgres://"):
            gt_db_url = gt_db_url.replace("postgres://", "postgresql+psycopg2://", 1)
        if "sslmode" not in gt_db_url:
            gt_db_url += "&sslmode=require" if "?" in gt_db_url else "?sslmode=require"
        eng = create_engine(gt_db_url, pool_pre_ping=True, connect_args={"connect_timeout": 5})

        # Ensure assigned_driver column exists
        with eng.begin() as conn:
            conn.execute(text("""
                DO $$ BEGIN
                    ALTER TABLE vehicles ADD COLUMN assigned_driver VARCHAR(255);
                EXCEPTION WHEN duplicate_column THEN null;
                END $$;
            """))

        # Authenticate with Geotab API
        base = f"https://{gt_server}/apiv1"
        auth_resp = requests.post(base, json={
            "method": "Authenticate",
            "params": {"database": gt_db, "userName": gt_user, "password": gt_pass}
        }, timeout=30)
        auth_data = auth_resp.json()
        if "error" in auth_data:
            return Pre(f"Auth error: {auth_data['error']}")
        creds = auth_data.get("result", {}).get("credentials", auth_data.get("result", {}))

        # Fetch ALL Devices
        get_resp = requests.post(base, json={
            "method": "Get",
            "params": {"typeName": "Device", "credentials": creds, "resultsLimit": 50000}
        }, timeout=120)
        raw = get_resp.json()
        devices = raw.get("result", [])
        if not isinstance(devices, list):
            return Pre(f"Unexpected response: {json.dumps(raw)[:500]}")

        updated = 0
        skipped = 0
        with eng.begin() as conn:
            for d in devices:
                gid = str(d.get("id", ""))
                if not gid:
                    skipped += 1
                    continue
                device_name = d.get("name", "") or ""
                plate = d.get("licensePlate") or ""
                result = conn.execute(text(
                    "UPDATE vehicles SET assigned_driver = :name, license_plate = COALESCE(NULLIF(:plate, ''), license_plate) WHERE geotab_id = :gid"
                ), {"name": device_name, "plate": plate, "gid": gid})
                if result.rowcount > 0:
                    updated += 1
                else:
                    skipped += 1

        return Pre(f"Processed {len(devices)} devices from Geotab.\nUpdated {updated} vehicles in DB.\nSkipped {skipped} (no matching vehicle).\n\nVIN-to-Driver mapping saved to vehicles.assigned_driver.")
    except Exception as e:
        import traceback
        return Pre(f"Error: {e}\\n{traceback.format_exc()}")


@rt("/_gt_resync_trips")
async def gt_resync_trips(req):
    """Re-fetch all trips from Geotab to populate driver_id on existing records."""
    from sqlalchemy import text
    import requests
    try:
        gt_db = os.getenv("GEOTAB_DATABASE")
        gt_user = os.getenv("GEOTAB_USERNAME")
        gt_pass = os.getenv("GEOTAB_PASSWORD")
        gt_server = os.getenv("GEOTAB_SERVER", "my.geotab.com")
        if not all([gt_db, gt_user, gt_pass]):
            return Pre("ERROR: missing Geotab credentials")

        base = f"https://{gt_server}/apiv1"
        auth_resp = requests.post(base, json={
            "method": "Authenticate",
            "params": {"database": gt_db, "userName": gt_user, "password": gt_pass}
        }, timeout=30)
        auth_data = auth_resp.json()
        if "error" in auth_data:
            return Pre(f"Auth error: {auth_data['error']}")
        creds = auth_data.get("result", {}).get("credentials", auth_data.get("result", {}))

        # Fetch trips from Geotab (30 days lookback, since DB shows trips up to June 23)
        import json
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        since = now - datetime.timedelta(days=60)
        get_resp = requests.post(base, json={
            "method": "Get",
            "params": {
                "typeName": "Trip",
                "credentials": creds,
                "search": {"fromDate": since.isoformat().replace("+00:00", "Z")},
                "resultsLimit": 50000,
            }
        }, timeout=120)
        raw = get_resp.json()
        trips_raw = raw.get("result", [])
        if not isinstance(trips_raw, list):
            return Pre(f"Unexpected response: {json.dumps(raw)[:500]}")

        # Build driver geotab_id -> DB id map
        db = load_gt()
        driver_rows = db.execute(text("SELECT id, geotab_id FROM drivers")).all()
        driver_map = {r.geotab_id: r.id for r in driver_rows}
        
        # Build vehicle geotab_id -> DB id map
        vehicle_rows = db.execute(text("SELECT id, geotab_id FROM vehicles")).all()
        vehicle_map = {v.geotab_id: v.id for v in vehicle_rows}

        updated = 0
        skipped = 0
        for trip in trips_raw:
            trip_id = str(trip.get("id", ""))
            if not trip_id:
                continue
            # Extract driver from trip - Geotab returns "driver": {"id": "b3AE"}
            driver_raw = trip.get("driver")
            driver_geotab = None
            if isinstance(driver_raw, dict):
                driver_geotab = str(driver_raw.get("id", ""))
            elif driver_raw:
                driver_geotab = str(driver_raw)
            driver_db_id = driver_map.get(driver_geotab) if driver_geotab else None

            # Extract vehicle
            device_raw = trip.get("device")
            vehicle_geotab = None
            if isinstance(device_raw, dict):
                vehicle_geotab = str(device_raw.get("id", ""))
            vehicle_db_id = vehicle_map.get(vehicle_geotab) if vehicle_geotab else None

            if not vehicle_db_id:
                skipped += 1
                continue

            db.execute(text(
                "UPDATE trips SET driver_id=:did, vehicle_id=:vid "
                "WHERE geotab_trip_id=:tid"
            ), {"did": driver_db_id, "vid": vehicle_db_id, "tid": trip_id})
            updated += 1

        db.commit()
        db.close()
        return Pre(f"Processed {len(trips_raw)} trips from Geotab. Updated {updated} (skipped {skipped} no-vehicle).")
    except Exception as e:
        import traceback
        return Pre(f"Error: {e}\n{traceback.format_exc()}")

@rt("/_gt_sync_logs")
async def gt_sync_logs(req):
    """Show sync log entries from the GT database."""
    from sqlalchemy import text
    try:
        db = load_gt()
        out = []
        r = db.execute(text("SELECT entity_name, status, records_processed, started_at, finished_at, message FROM sync_logs ORDER BY started_at DESC LIMIT 20"))
        out.append("Last 20 sync attempts:")
        for row in r:
            msg = (row.message or "")[:80]
            out.append(f"  {row.entity_name:12s} {row.status:8s} {str(row.records_processed or 0):5s} records  {str(row.started_at)[:19]}  {msg}")
        r = db.execute(text("SELECT entity_name, last_sync_timestamp FROM sync_metadata ORDER BY entity_name"))
        out.append("\nSync watermarks:")
        for row in r:
            out.append(f"  {row.entity_name:12s} last: {str(row.last_sync_timestamp)[:19]}")
        db.close()
        return Pre("\n".join(out))
    except Exception as e:
        import traceback
        return Pre(f"Error: {e}")



@rt("/_sd_worker_bbso")
async def sd_worker_bbso(req):
    """Return BBSO or RIR forms for a specific worker."""
    worker_id = req.query_params.get("worker_id", "")
    ftype = req.query_params.get("type", "bbso")
    ds = _cached("sd", load_sd)
    if not ds or ds.forms.empty or not worker_id:
        return Div("")
    try:
        # Build worker name lookup
        worker_map = {}
        if not ds.workers.empty and "Id" in ds.workers.columns:
            for _, w in ds.workers.iterrows():
                wid = str(w.get("Id", ""))
                fname = str(w.get("FirstName", ""))
                lname = str(w.get("LastName", ""))
                worker_map[wid] = f"{fname} {lname}".strip() or wid[:12]
        worker_name = worker_map.get(worker_id, worker_id[:12])

        # Build location name lookup
        loc_map = {}
        if not ds.locations.empty and "Id" in ds.locations.columns:
            for _, loc in ds.locations.iterrows():
                loc_map[str(loc.get("Id", ""))] = str(loc.get("Name", ""))[:30]

        # Filter forms
        forms = ds.forms.copy()
        if ftype == "bbso":
            from data.sd_data import _filter_bbso
            filtered = _filter_bbso(forms)
        else:
            from data.sd_data import _filter_rir
            filtered = _filter_rir(forms)

        col = "CreatedBy" if "CreatedBy" in filtered.columns else "createdBy"
        if col not in filtered.columns or filtered.empty:
            return Div(P("No forms found for this worker.", cls="note"))

        worker_forms = filtered[filtered[col] == worker_id].copy()
        if worker_forms.empty:
            return Div(P("No forms found for this worker.", cls="note"))

        date_col = "CreatedOn" if "CreatedOn" in worker_forms.columns else "createdOn"
        if date_col in worker_forms.columns:
            worker_forms = worker_forms.sort_values(date_col, ascending=False)

        rows = []
        for _, r in worker_forms.iterrows():
            raw_dt = r.get(date_col) if date_col in r else ""
            if hasattr(raw_dt, "strftime"):
                dt = raw_dt.strftime("%Y-%m-%d %H:%M")
            else:
                dt = str(raw_dt)[:16]
            label = str(r.get("Label", ""))[:60] or "(no note)"
            loc_id = str(r.get("LocationId", ""))
            loc_name = loc_map.get(loc_id, loc_id[:12])
            rows.append(f"<tr><td>{dt}</td><td>{label}</td><td>{loc_name}</td></tr>")

        header = "<tr><th>Date</th><th>Note</th><th>Location</th></tr>"
        heading = "BBSO" if ftype == "bbso" else "RIR / Near Miss"
        back = A(f"← Back to {worker_name}",
                 hx_get="/view?platform=sd&section=hse", hx_target="#content", cls="preset")
        return Div(
            H3(f"{heading} Forms — {worker_name}", style="margin:0 0 8px;font-size:14px;"),
            Div(P(f"{len(rows)} form(s)", style="color:var(--muted);font-size:12px;margin:0 0 8px;")),
            Div(NotStr("<table class='data'><thead>" + header + "</thead><tbody>" + "".join(rows) + "</tbody></table>"), cls="tbl-wrap"),
            back,
            cls="panel", id="sd-forms-list",
        )
    except Exception:
        return Div("")


@rt("/_sd_forms")
async def sd_forms(req):
    """Return forms table for a month. Replaces the chart panel."""
    month = req.query_params.get("month", "")
    ds = _cached("sd", load_sd)
    if not ds or ds.forms.empty or not month:
        return Div("")
    try:
        forms = ds.forms.copy()
        forms_dates = forms["CreatedOn"] if "CreatedOn" in forms.columns else forms.get("createdOn", pd.Series())
        mask = forms_dates.dt.strftime("%Y-%m") == month
        matching = forms[mask].sort_values("CreatedOn" if "CreatedOn" in forms.columns else "createdOn", ascending=False).head(30)
        if matching.empty:
            return Div(H3("Forms in " + month, style="margin:0 0 8px;font-size:14px;"),
                       P("No forms for " + month, cls="note"),
                       A("← Back", href="#", cls="preset",
                         hx_get="/view?platform=sd&section=hse", hx_target="#content"),
                       cls="panel", id="sd-forms-chart")
        rows = []
        # Build worker lookup dict: worker UUID -> name
        worker_map = {}
        if not ds.workers.empty and "Id" in ds.workers.columns:
            for _, w in ds.workers.iterrows():
                wid = str(w.get("Id", ""))
                fname = str(w.get("FirstName", ""))
                lname = str(w.get("LastName", ""))
                worker_map[wid] = f"{fname} {lname}".strip() or wid[:12]
        for _, r in matching.iterrows():
            name = r.get("DocumentTemplateName", r.get("Label", ""))[:45]
            created = str(r.get("CreatedOn", ""))[:10] if hasattr(r.get("CreatedOn"), "strftime") else str(r.get("createdOn", ""))[:10]
            by_uuid = str(r.get("CreatedBy", r.get("createdBy", "")))
            by_name = worker_map.get(by_uuid, by_uuid[:12])
            rows.append(f"<tr><td>{name}</td><td>{created}</td><td>{by_name}</td></tr>")
        h = "<tr><th>Form</th><th>Date</th><th>Created By</th></tr>"
        back = A("← Back to chart", cls="preset",
                 hx_get="/view?platform=sd&section=hse", hx_target="#content")
        return Div(
            H3("Forms in " + month, style="margin:0 0 8px;font-size:14px;"),
            Div(NotStr("<table class='data'><thead>" + h + "</thead><tbody>" + "".join(rows) + "</tbody></table>"),
                cls="tbl-wrap"),
            back,
            cls="panel", id="sd-forms-chart",
        )
    except Exception:
        return Div("")


@rt("/_sd_person_forms")
async def sd_person_forms(req):
    """Show BBSO or RIR forms filed by a specific worker, with full field-level content."""
    try:
        import json as _json
        worker_id = req.query_params.get("worker_id", "")
        form_type = req.query_params.get("type", "bbso")
        ds = _cached("sd", load_sd)
        if not ds or ds.forms.empty or not worker_id:
            return Div("")

        # Resolve worker name
        worker_name = worker_id[:12]
        if not ds.workers.empty and "Id" in ds.workers.columns:
            wm = ds.workers[ds.workers["Id"] == worker_id]
            if not wm.empty:
                w = wm.iloc[0]
                worker_name = f"{w.get('FirstName','')} {w.get('LastName','')}".strip() or worker_id[:12]

        # Resolve location names
        loc_map = {}
        if not ds.locations.empty and "Id" in ds.locations.columns:
            for _, loc in ds.locations.iterrows():
                loc_map[str(loc["Id"])] = str(loc.get("Name", ""))

        # Filter forms by type and creator
        forms = ds.forms.copy()
        if form_type == "bbso":
            from data.sd_data import _filter_bbso
            filtered = _filter_bbso(forms)
            type_label = "BBSO"
        else:
            from data.sd_data import _filter_rir
            filtered = _filter_rir(forms)
            type_label = "RIR / Near Miss"

        col = "CreatedBy" if "CreatedBy" in filtered.columns else "createdBy"
        if col not in filtered.columns:
            return Div(P(f"No {type_label} forms found for {worker_name}", cls="note"))

        person_forms = filtered[filtered[col] == worker_id].copy()
        if person_forms.empty:
            return Div(P(f"No {type_label} forms from {worker_name}", cls="note"))

        date_col = "CreatedOn" if "CreatedOn" in person_forms.columns else "createdOn"
        if date_col in person_forms.columns:
            person_forms[date_col] = pd.to_datetime(person_forms[date_col], errors="coerce")
            person_forms = person_forms.sort_values(date_col, ascending=False)

        # Close/back button
        close_btn = A("← Close", cls="preset", style="margin-bottom:10px;display:inline-block;",
                      hx_get="/_sd_close_panel", hx_target="#person-forms-panel", hx_swap="innerHTML")

        # ── Fetch fresh form content from SiteDocs API (no warehouse middleman) ──
        api_key = os.getenv("SITEDOCS_API_KEY", "")
        api_base = os.getenv("SITEDOCS_API_BASE", "https://api-1.sitedocs.com")
        form_panels = []
        import requests

        for _, frow in person_forms.iterrows():
            fid = frow.get("Id") or frow.get("DocumentId", "")
            dt = str(frow.get(date_col, ""))[:10] if date_col in frow else ""
            loc_id = str(frow.get("LocationId", ""))
            loc_name = loc_map.get(loc_id, loc_id[:12]) if loc_id else "—"

            # Fetch from API directly
            content = None
            if api_key and fid:
                try:
                    url = f"{api_base}/api/v1/forms/content/{fid}"
                    resp = requests.get(url, headers={"Authorization": api_key, "Accept": "application/json"}, timeout=15)
                    if resp.status_code == 200:
                        content = resp.json()
                except Exception:
                    pass

            if not content or not isinstance(content, dict):
                # Fallback: just show metadata
                label = frow.get("Label", frow.get("DocumentTemplateName", ""))
                form_panels.append(
                    f"<div class='panel' style='margin-bottom:8px;padding:10px;'>"
                    f"<div style='display:flex;justify-content:space-between;font-size:13px;'>"
                    f"<strong>{type_label}</strong> — {dt}</div>"
                    f"<div class='note'>{label[:60]} · {loc_name}</div></div>"
                )
                continue

            # Process API response groups → items
            # Type field is numeric (0-indexed position in SiteDocs enum):
            # 1=Checkbox, 2=Inspection, 6=ShortAnswer, 9=SelectSingle, 13=SelectDate,
            # 18=YesNo, 19=PassFailCounter
            SAFE_TYPES = {1, 2, 18, 19}  # Checkbox, Inspection, YesNo, PassFailCounter

            def _extract_label(raw):
                """Extract readable label from a value that might be JSON."""
                if isinstance(raw, dict):
                    for k in ("Text", "Name", "Label", "Value"):
                        if k in raw and str(raw[k]).strip():
                            return str(raw[k])
                    if "Id" in raw:
                        uid = str(raw["Id"])
                        if uid in loc_map:
                            return loc_map[uid]
                        if uid in _MISSING_LOCS:
                            return _MISSING_LOCS[uid]
                        return "Location"
                    return str(raw)
                s = str(raw)
                if s.startswith("{"):
                    try:
                        p = _json.loads(s)
                        if isinstance(p, dict):
                            for k in ("Text", "Name", "Label", "Value"):
                                if k in p and str(p[k]).strip():
                                    return str(p[k])
                            if "Id" in p:
                                uid = str(p["Id"])
                                if uid in loc_map:
                                    return loc_map[uid]
                                if uid in _MISSING_LOCS:
                                    return _MISSING_LOCS[uid]
                                return "Location"
                            return str(p)
                    except Exception:
                        pass
                return s

            # Known missing location UUIDs that SiteDocs returns but aren't in the warehouse
            _MISSING_LOCS = {
                "c6e5469e-0647-4ba1-a1d7-730632d895ab": "Delta",
            }

            group_htmls = []
            for group in content.get("Groups", []):
                gtitle = group.get("Title", "")
                items = group.get("Items", [])
                item_rows = []
                for item in items:
                    raw_content = item.get("Content", "")
                    q = _extract_label(raw_content)
                    raw_val = item.get("Value")
                    raw_comments = item.get("Comments", "")
                    item_type = item.get("Type", 0)

                    # Extract value
                    val = _extract_label(raw_val)

                    # Comments
                    comments = ""
                    if raw_comments:
                        if isinstance(raw_comments, dict):
                            comments = str(raw_comments.get("Text", ""))
                        elif isinstance(raw_comments, list):
                            comments = "; ".join(str(c.get("Text", c)) if isinstance(c, dict) else str(c) for c in raw_comments[:2])
                        else:
                            comments = str(raw_comments)

                    # Classify safe/at-risk for Checkbox/Inspection/YesNo/PassFail
                    v_lower = val.strip().lower()
                    if item_type in SAFE_TYPES and gtitle != "Task Information" and "Task" not in gtitle:
                        if v_lower in ("yes", "pass", "true", "safe", "1"):
                            cls = "badge green"
                            display = "Safe ✓"
                        elif v_lower in ("no", "fail", "false", "0"):
                            cls = "badge red"
                            display = "At-Risk ✗"
                        else:
                            cls = "badge"
                            display = val[:40]
                    else:
                        cls = "badge"
                        display = val[:60]

                    cmt = f"<br><span class='note'>{comments[:120]}</span>" if comments else ""
                    item_rows.append(
                        f"<tr><td style='padding:3px 8px;font-size:12px;'>{q[:60]}</td>"
                        f"<td style='padding:3px 8px;'><span class='{cls}'>{display}</span>{cmt}</td></tr>"
                    )

                if item_rows:
                    group_htmls.append(
                        f"<tr style='background:#f8fafc;'><td colspan='2' style='padding:4px 8px;font-weight:600;font-size:11px;color:#475569;'>{gtitle}</td></tr>"
                        + "".join(item_rows)
                    )

            body = "".join(group_htmls) if group_htmls else "<tr><td colspan='2' class='note' style='padding:8px;'>No field data</td></tr>"
            form_panels.append(
                f"<div class='panel' style='margin-bottom:8px;padding:10px;'>"
                f"<div style='display:flex;justify-content:space-between;margin-bottom:6px;font-size:13px;'>"
                f"<strong>{type_label}</strong> — {dt} <span class='note'>{loc_name}</span></div>"
                f"<table class='data' style='font-size:12px;'><tbody>{body}</tbody></table></div>"
            )

        count = len(person_forms)
        return Div(
            close_btn,
            H3(f"{type_label} forms from {worker_name} ({count})",
               style="margin:0 0 10px;font-size:15px;"),
            NotStr("\n".join(form_panels)),
            cls="panel",
            id="person-forms-panel",
        )
    except Exception as e:
        import traceback
        return Div(P(f"Error loading forms: {e}", cls="note"),
                   Pre(traceback.format_exc(), style="font-size:10px;color:var(--muted);"))


@rt("/_sd_clear_cache")
async def sd_clear_cache(req):
    """Clear the in-memory data cache so fresh data is loaded on next request."""
    global _data_cache, _cache_ts, _chart_html_cache
    _data_cache.clear()
    _cache_ts.clear()
    _chart_html_cache.clear()
    return Pre("Cache cleared. Refresh the page to see fresh data.")


@rt("/_check_env")
async def check_env(req):
    """Check which env vars are available (safe check — doesn't print values)."""
    vars_to_check = ["SITEDOCS_API_KEY", "SD_DATABASE_URL", "QB_DATABASE_URL", "DASHBOARD_LOGIN_PASSWORD"]
    lines = []
    for v in vars_to_check:
        val = os.getenv(v, "")
        if val:
            lines.append(f"{v}: SET ({val[:20]}...{val[-4:]})")
        else:
            lines.append(f"{v}: NOT SET")
    return Pre("\n".join(lines))


@rt("/_sd_raw_form")
async def sd_raw_form(req):
    """Debug: fetch one BBSO form from SiteDocs API and dump its Groups/Items structure."""
    try:
        import requests, json
        api_key = os.getenv("SITEDOCS_API_KEY", "")
        api_base = os.getenv("SITEDOCS_API_BASE", "https://api-1.sitedocs.com")
        from data.sd_data import _filter_bbso
        ds = _cached("sd", load_sd)
        if not ds or ds.forms.empty:
            return Pre("No forms data")
        bbso = _filter_bbso(ds.forms)
        if bbso.empty:
            return Pre("No BBSO forms found")
        fid = bbso.iloc[0].get("Id") or bbso.iloc[0].get("DocumentId", "")
        url = f"{api_base}/api/v1/forms/content/{fid}"
        resp = requests.get(url, headers={"Authorization": api_key, "Accept": "application/json"}, timeout=15)
        data = resp.json()
        lines = [f"HTTP {resp.status_code}", f"Top keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}"]
        if isinstance(data, dict):
            groups = data.get("Groups", [])
            lines.append(f"Groups count: {len(groups)}")
            for i, g in enumerate(groups):
                gtitle = g.get("Title", "?")
                items = g.get("Items", [])
                lines.append(f"  Group {i}: '{gtitle}' — {len(items)} items")
                for j, item in enumerate(items[:3]):
                    q = item.get("Content", "")
                    v = item.get("Value")
                    t = item.get("Type", "")
                    lines.append(f"    Item {j}: type={t} q='{q}' value_type={type(v).__name__} value={str(v)[:80]}")
        return Pre("\n".join(lines))
    except Exception as e:
        import traceback
        return Pre(f"Error: {e}\n{traceback.format_exc()}")


@rt("/_sd_lookup")
async def sd_lookup(req):
    """Search all SD database tables for a UUID to identify what it is."""
    uid = req.query_params.get("uid", "")
    if not uid:
        return Pre("Usage: /_sd_lookup?uid=c6e5469e-...")
    try:
        from sqlalchemy import text as _text
        from data.sd_data import sd_engine
        import pandas as _pd
        eng = sd_engine()
        lines = [f"Searching for: {uid}"]
        with eng.connect() as conn:
            tables = conn.execute(_text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name"
            )).all()
            for (tname,) in tables:
                try:
                    df = _pd.read_sql(f"SELECT * FROM \"{tname}\"", conn)
                    for col in df.columns:
                        if df[col].dtype == 'object':
                            matches = df[df[col] == uid]
                            if len(matches) > 0:
                                # Show first matching row's relevant field
                                row = matches.iloc[0]
                                label = ""
                                for k in ("Name", "label", "DocumentTemplateName", "Description",
                                          "FirstName", "Title", "LocationName"):
                                    if k in row and str(row[k]).strip():
                                        label = f" → {str(row[k])[:80]}"
                                        break
                                lines.append(f"  {tname}.{col}: {len(matches)} row(s){label}")
                except Exception:
                    pass
            eng.dispose()
        return Pre("\n".join(lines))
    except Exception as e:
        import traceback
        return Pre(f"Error: {e}\n{traceback.format_exc()}")


@rt("/_sd_close_panel")
async def sd_close_panel(req):
    """Return empty content for HTMX to swap into the person-forms-panel."""
    return Div("")


@rt("/_sd_scrub")
async def sd_scrub(req):
    """One-shot: clean corrupted JSON values in sitedocs_form_responses table."""
    try:
        from sqlalchemy import text as _text
        from data.sd_data import sd_engine
        import json as _json
        import re as _re

        eng = sd_engine()
        lines = []

        # Check if table exists
        with eng.connect() as conn:
            result = conn.execute(_text(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'sitedocs_form_responses')"
            ))
            exists = result.scalar()
            lines.append(f"Table exists: {exists}")
            if not exists:
                eng.dispose()
                return Pre("\n".join(lines))

            # Get sample data first
            sample = conn.execute(_text("SELECT \"ItemValue\" FROM sitedocs_form_responses LIMIT 5")).all()
            lines.append(f"Sample values before scrub:")
            for r in sample:
                val = r[0]
                lines.append(f"  raw={repr(str(val)[:120])}")

            # Count and fix
            count_total = 0
            count_fixed = 0

            rows = conn.execute(_text(
                "SELECT ctid, \"ItemValue\" FROM sitedocs_form_responses"
            )).all()
            lines.append(f"Total rows: {len(rows)}")

            for ctid, raw in rows:
                if not raw or raw == "nan":
                    count_total += 1
                    continue
                s = str(raw).strip()
                cleaned = s.replace("\t", " ").replace("\r", " ").replace("\n", " ")

                extracted = None

                # Try JSON
                fixed = cleaned
                ob = fixed.count("{")
                cb = fixed.count("}")
                while cb < ob:
                    fixed += "}"
                    cb += 1
                try:
                    parsed = _json.loads(fixed)
                    if isinstance(parsed, dict):
                        for k in ("Text", "Name", "Label", "Value", "Description", "Title"):
                            if k in parsed and str(parsed[k]).strip():
                                extracted = str(parsed[k])
                                break
                        if extracted is None:
                            for v in parsed.values():
                                if isinstance(v, str) and v.strip():
                                    extracted = v
                                    break
                            if extracted is None:
                                extracted = str(parsed)
                    elif isinstance(parsed, list):
                        extracted = "; ".join(str(p.get("Text", p.get("Name", p.get("Label", p)))) if isinstance(p, dict) else str(p) for p in parsed[:3])
                    else:
                        extracted = str(parsed)
                except Exception:
                    pass

                # Regex fallback
                if extracted is None:
                    for pat in (r'"Label"\s*:\s*"([^"]+)"', r'"Text"\s*:\s*"([^"]+)"', r'"Name"\s*:\s*"([^"]+)"'):
                        m = _re.search(pat, s)
                        if m:
                            extracted = m.group(1).strip()
                            break

                # UUID fallback
                if extracted is None:
                    uuids = _re.findall(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', s)
                    if uuids:
                        extracted = uuids[0]

                if extracted is not None and extracted != s:
                    conn.execute(
                        _text("UPDATE sitedocs_form_responses SET \"ItemValue\" = :v WHERE ctid = :c"),
                        {"v": extracted, "c": ctid}
                    )
                    count_fixed += 1
                count_total += 1

            conn.commit()

            # Verify after scrub
            sample2 = conn.execute(_text("SELECT \"ItemValue\" FROM sitedocs_form_responses LIMIT 5")).all()
            lines.append(f"Sample values after scrub:")
            for r in sample2:
                val = r[0]
                lines.append(f"  clean={repr(str(val)[:120])}")

        eng.dispose()
        lines.append(f"\nScanned {count_total} rows. Fixed {count_fixed}.")
        return Pre("\n".join(lines))
    except Exception as e:
        import traceback
        return Pre(f"Error: {e}\n{traceback.format_exc()}")


@rt("/_sd_diag_value")
async def sd_diag_value(req):
    """Diagnostic: show raw ItemValues from sitedocs_form_responses for debugging."""
    try:
        from charts import sd_charts as _sd_charts
        ds = _cached("sd", load_sd)
        if not ds or not hasattr(ds, 'form_responses') or ds.form_responses.empty:
            return Pre("No form_responses data loaded")
        fr = ds.form_responses.head(20)
        lines = ["First 20 form_responses rows, raw ItemValues:"]
        for _, r in fr.iterrows():
            raw = repr(str(r.get("ItemValue", "")))
            cleaned = repr(_sd_charts._clean_value(str(r.get("ItemValue", ""))))
            lines.append(f"  type={r.get('FormType',''):12s} group={r.get('GroupTitle',''):20s} raw={raw}")
            if cleaned != raw.strip("'"):
                lines.append(f"  {'':>6s}clean={cleaned}")
        return Pre("\n".join(lines))
    except Exception as e:
        import traceback
        return Pre(f"Error: {e}\n{traceback.format_exc()}")


@rt("/_sd_inspect")
async def sd_inspect(req):
    """Diagnostic: show the actual columns and sample rows from sitedocs_forms."""
    try:
        from data.sd_data import sd_read_table, _filter_bbso, _filter_rir, sd_engine
        from sqlalchemy import text

        # First, list all tables in the SD database
        engine = sd_engine()
        with engine.connect() as c:
            tables_result = c.execute(text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE' "
                "ORDER BY table_name"
            ))
            all_tables = [r[0] for r in tables_result]

        lines = []
        lines.append(f"All tables in SD database ({len(all_tables)}):")
        for t in all_tables:
            lines.append(f"  {t}")

        # Now inspect sitedocs_forms
        forms = sd_read_table("sitedocs_forms")
        lines.append(f"\n── sitedocs_forms ──")
        lines.append(f"Total rows: {len(forms)}")
        lines.append(f"Columns ({len(forms.columns)}):")
        for c in sorted(forms.columns):
            dtype = str(forms[c].dtype)
            non_null = forms[c].notna().sum()
            sample = ""
            if non_null > 0:
                val = forms[c].dropna().iloc[0]
                sample = f"  eg: {str(val)[:80]}"
            lines.append(f"  {c:40s} {dtype:12s} {non_null:6d} non-null{sample}")

        # Show BBSO and RIR breakdown
        # Check what unique template names exist
        name_counts = forms["DocumentTemplateName"].value_counts()
        lines.append(f"\n── Form types (by DocumentTemplateName):")
        for name, count in name_counts.head(20).items():
            lines.append(f"  {name:40s} {count}")

        lines.append(f"\n── BBSO forms: {len(_filter_bbso(forms))}")
        lines.append(f"── RIR forms: {len(_filter_rir(forms))}")

        # Check locations table if it exists
        if "sitedocs_locations" in all_tables:
            loc_df = pd.read_sql("SELECT * FROM sitedocs_locations LIMIT 5", engine)
            lines.append(f"\n── sitedocs_locations sample (columns: {list(loc_df.columns)}):")
            for _, r in loc_df.iterrows():
                lines.append(f"  {dict(r)}")

        # Check for any form-related tables not currently loaded
        for t in all_tables:
            if "form" in t.lower() and t != "sitedocs_forms":
                try:
                    df = pd.read_sql(f"SELECT * FROM {t} LIMIT 3", engine)
                    lines.append(f"\n── {t} -- {len(df)} rows, columns: {list(df.columns)}")
                    for _, r in df.iterrows():
                        lines.append(f"  {dict(r)}")
                except Exception as e:
                    lines.append(f"\n── {t} -- ERROR: {e}")

        # Also peek at incidents table for any useful detail
        if "sitedocs_incidents" in all_tables:
            inc_df = pd.read_sql("SELECT * FROM sitedocs_incidents LIMIT 3", engine)
            lines.append(f"\n── sitedocs_incidents sample (columns: {list(inc_df.columns)}):")
            for _, r in inc_df.iterrows():
                lines.append(f"  {dict(r)}")

        engine.dispose()
        return Pre("\n".join(lines))
    except Exception as e:
        import traceback
        return Pre(f"Error: {e}\n{traceback.format_exc()}")

@rt("/logout")
async def logout(req):
    req.session.clear()
    return RedirectResponse("/login", status_code=303)


@rt("/")
async def index(req):
    guard = require_login(req)
    if guard:
        return guard
    platform = req.query_params.get("platform")
    section = req.query_params.get("section", "overview")
    basis = req.query_params.get("basis", "accrual")
    range_key = req.query_params.get("range", "all")

    # Load overview content on initial page load
    if not platform or platform == "overview":
        content = render_overview(req.query_params.get("range", "ytd"))
        title = "Overview"
    elif platform == "qb":
        content = render_qb_section(section or "overview", basis, range_key, req.query_params.get("metric", "revenue"))
        title = f"QuickBooks - {section.title()}"
    elif platform == "sd":
        content = render_sd_section(section or "hse")
        title = f"SiteDocs - {section.title()}"
    elif platform == "gt":
        content = render_gt_section(section or "fleet", range_key)
        title = f"GeoTab - {section.title()}"
    else:
        content = render_overview(req.query_params.get("range", "ytd"))
        title = "Overview"

    return shell(content, active_platform=platform, active_section=section or "overview", title=title)


@rt("/view")
async def view_section(req):
    guard = require_login(req)
    if guard:
        return guard
    platform = req.query_params.get("platform", "overview")
    section = req.query_params.get("section", "overview")
    basis = req.query_params.get("basis", "accrual")
    range_key = req.query_params.get("range", "all")

    if platform == "overview":
        return tuple(render_overview(req.query_params.get("range", "ytd")))

    if platform == "qb":
        return tuple(render_qb_section(section, basis, range_key, req.query_params.get("metric", "revenue")))

    if platform == "sd":
        return tuple(render_sd_section(section))

    if platform == "gt":
        return tuple(render_gt_section(section or "fleet", range_key))

    return Div("Unknown platform", cls="chart-empty")


# ── Entry point ───────────────────────────────────────────────────────────

# Preload data on startup so first user doesn't wait
import threading as _threading
def _preload():
    time.sleep(1)  # Let server start first
    _cached("qb", load_qb)
    _cached("sd", load_sd)
    _cached("gt", load_gt)
_threading.Thread(target=_preload, daemon=True).start()

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
