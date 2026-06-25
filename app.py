"""Unified EWS Dashboard — QuickBooks + SiteDocs + GeoTab in one place.

All data comes from real PostgreSQL databases, one per platform.
Three existing dashboards stay up unchanged; this is a 4th deployment.
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta, timezone
from hashlib import pbkdf2_hmac
from hmac import compare_digest
from urllib.parse import parse_qs, urlencode

import pandas as pd
from dotenv import load_dotenv
from fasthtml.common import *

load_dotenv()

from data import qb_data as QB
from data import sd_data as SD
from data import gt_data as GT

# ── App setup ──────────────────────────────────────────────────────────────

PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"

# Date range presets
def resolve_date_range(range_key):
    end = date.today()
    if range_key == "ytd":
        return date(end.year, 1, 1), end
    if range_key == "30d":
        return end - timedelta(days=30), end
    if range_key == "90d":
        return end - timedelta(days=90), end
    if range_key == "12m":
        return end - timedelta(days=365), end
    return date(2020, 1, 1), end

RANGE_PRESETS = [("all","All"), ("ytd","YTD"), ("30d","30d"), ("90d","90d"), ("12m","12m")]

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
           min-height: 100vh; align-self: stretch; }
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
.main { flex: 1; min-width: 0; padding: 22px 26px 40px; }
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
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin-bottom: 20px; }
.kpi { background: var(--card); border:1px solid var(--line); border-radius: 12px; padding: 12px 14px;
       text-decoration: none; color: inherit; transition: box-shadow .15s; }
.kpi:hover { box-shadow: 0 4px 12px rgba(15,23,42,.06); }
.kpi .k-label { color: var(--muted); font-size: 11px; font-weight: 600; display:flex; align-items:center; gap:4px; white-space: nowrap; }
.kpi .k-label .k-platform { font-size:9px; background:#e2e8f0; color:#475569; padding:1px 5px; border-radius:3px; font-weight:700; }
.kpi .k-value { font-size: 22px; font-weight: 800; margin: 2px 0 0; line-height: 1.2; }
.kpi .k-hint { color:#94a3b8; font-size: 10px; margin-top:1px; }
.kpi .k-badge { display: inline-block; font-size: 10px; font-weight: 700; padding: 1px 6px;
                border-radius: 999px; margin-left: 4px; }
.kpi .k-badge.green { background:#dcfce7; color:#15803d; }
.kpi .k-badge.warn { background:#fef3c7; color:#92400e; }
.kpi .k-badge.red { background:#fee2e2; color:#b91c1c; }

.kpi-rag { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:3px; flex-shrink:0; }

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

/* Hide Plotly modebar & logo */
.modebar, .modebar-container, .plotly-notifier,
.js-plotly-plot .modebar, .js-plotly-plot .modebar-btn,
.modebar-btn, .modebar-group { display: none !important; }

/* Fix chart panel sizing */
.panel .js-plotly-plot { width: 100%; }
.panel .plot-container { width: 100%; }

/* Fade in content on HTMX swap */
#content { animation: fadein .25s ease; }
@keyframes fadein { from { opacity:0; transform:translateY(4px); } to { opacity:1; transform:translateY(0); } }
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
            ("incidents", "Incidents", "⚠️"),
            ("workers", "Workers", "👷"),
            ("certifications", "Certifications", "🎓"),
            ("equipment", "Equipment", "🔧"),
            ("locations", "Locations", "📍"),
            ("signatures", "Signatures", "✍️"),
            ("reports", "Reports & Trends", "📊"),
        ],
    },
    {
        "key": "gt",
        "label": "GeoTab",
        "icon": "🚛",
        "sections": [
            ("fleet", "Fleet Overview", "📊"),
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

def kpi_card(label, value, unit="", hint="", rag=None, platform=""):
    """Render a single KPI card.
    rag: 'green', 'amber', 'red', or None.
    """
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
        rag_dot = Span(cls=f"kpi-rag", style=f"background:{rag_color_css(rag)}")

    platform_tag = Span(platform, cls="k-platform") if platform else ""

    return Div(
        Div(rag_dot, label, platform_tag, cls="k-label"),
        Div(fmt_val, cls="k-value"),
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

def render_overview():
    """Top KPIs and charts from all three platforms."""
    parts = []

    # ── Load data from all three platforms ──
    qb_ds = qb_safe_load()
    sd_ds = sd_safe_load()
    gt_conn = gt_safe_connect()

    # ── Top KPI row: 4 per platform ──
    qb_kpis = []
    if qb_ds:
        invoices = QB.filter_invoices(qb_ds.invoices, date(2020, 1, 1), date.today())
        bs = QB.balance_sheet_summary(qb_ds.accounts)
        pnl = QB.pnl_summary(qb_ds.pnl, "accrual", date(2020, 1, 1), date.today())
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
        rag = rag_for_value(sched_c["completion_pct"], 80, 60)
        sd_kpis = [
            kpi_card("Schedule Compliance", sched_c["completion_pct"], "%",
                     rag=rag, platform="SD"),
            kpi_card("Overdue Items", float(sched_c["overdue"]), "",
                     rag=rag_for_value(sched_c["overdue"], 5, 15, False),
                     platform="SD"),
            kpi_card("Worker Participation", part["pct"], "%",
                     rag=rag_for_value(part["pct"], 80, 60),
                     platform="SD"),
            kpi_card("Forms This Month", float(f_count["month"]), "",
                     platform="SD"),
        ]

    gt_kpis = []
    if gt_conn:
        try:
            db = gt_conn
            since_365 = datetime.now(timezone.utc) - timedelta(days=365)
            summary = GT.gt_fleet_summary(db, since_365, datetime.now(timezone.utc))
            trends = GT.gt_daily_trends(db, since_365, datetime.now(timezone.utc))
            speed = GT.gt_speed_analysis(db, since_365, datetime.now(timezone.utc))
            total_trips = sum(t["trips"] for t in trends)
            gt_kpis = [
                kpi_card("Active Vehicles", summary.active_vehicles, "",
                         hint=f"of {summary.total_vehicles} total", platform="GT"),
                kpi_card("Fleet Miles", summary.total_fleet_miles, "",
                         hint="12-month total", platform="GT"),
                kpi_card("Total Trips", total_trips, "",
                         platform="GT"),
                kpi_card("Speeding Events", speed["speeding_count"], "",
                         hint=f"{speed['speeding_pct']:.1f}% of GPS", platform="GT"),
            ]
            db.close()
        except Exception:
            pass

    all_kpis = (*qb_kpis, *sd_kpis, *gt_kpis)
    if all_kpis:
        parts.append(kpi_grid(all_kpis))

    # ── Charts: 2×2 grid ──
    charts = []

    # 1. Monthly Revenue Trend (QB)
    if qb_ds:
        try:
            invoices = QB.filter_invoices(qb_ds.invoices, date(2020, 1, 1), date.today())
            if not invoices.empty:
                from charts import qb_charts as QBC
                charts.append(Div(H3(Span("Monthly Revenue Trend", cls="dot", style="background:#2563eb")),
                                  NotStr(QBC.trend(invoices, "revenue")), cls="panel"))
        except Exception:
            charts.append(Div(H3("Monthly Revenue Trend"), Div("No data", cls="chart-empty"), cls="panel"))
    else:
        charts.append(Div(H3("Monthly Revenue Trend"), Div("No data", cls="chart-empty"), cls="panel"))

    # 2. Schedule Compliance (SD)
    if sd_ds:
        from charts import sd_charts as SDC
        try:
            charts.append(Div(H3(Span("Schedule Compliance", cls="dot", style="background:#16a34a")),
                              NotStr(SDC.schedule_compliance(sd_ds.schedules)), cls="panel"))
        except Exception:
            charts.append(Div(H3("Schedule Compliance"), Div("No data", cls="chart-empty"), cls="panel"))
    else:
        charts.append(Div(H3("Schedule Compliance"), Div("No data", cls="chart-empty"), cls="panel"))

    # 3. Fleet Daily Mileage (GT)
    if gt_conn:
        from charts import gt_charts as GTC
        try:
            db = gt_conn
            since_365 = datetime.now(timezone.utc) - timedelta(days=365)
            trends = GT.gt_daily_trends(db, since_365, datetime.now(timezone.utc))
            speed = GT.gt_speed_analysis(db, since_365, datetime.now(timezone.utc))
            vehicle_util = GT.gt_vehicle_utilization(db, since_365, datetime.now(timezone.utc))
            idling = GT.gt_idling_summary(db, since_365, datetime.now(timezone.utc))
            locations = GT.gt_latest_locations(db)
            gt_data = {
                "trends": trends,
                "speed": speed,
                "vehicle_util": vehicle_util,
                "idling": idling,
                "locations": locations,
            }
            charts.append(Div(H3(Span("Daily Mileage Trend", cls="dot", style="background:#ea580c")),
                              NotStr(GTC.daily_mileage_chart(gt_data)), cls="panel"))
            db.close()
        except Exception:
            charts.append(Div(H3("Daily Mileage Trend"), Div("No data", cls="chart-empty"), cls="panel"))
    else:
        charts.append(Div(H3("Daily Mileage Trend"), Div("No data", cls="chart-empty"), cls="panel"))

    # 4. Forms Monthly Trend (SD)
    if sd_ds:
        from charts import sd_charts as SDC
        try:
            charts.append(Div(H3(Span("Forms Monthly Trend", cls="dot", style="background:#7c3aed")),
                              NotStr(SDC.forms_trend(sd_ds.forms)), cls="panel"))
        except Exception:
            charts.append(Div(H3("Forms Monthly Trend"), Div("No data", cls="chart-empty"), cls="panel"))
    else:
        charts.append(Div(H3("Forms Monthly Trend"), Div("No data", cls="chart-empty"), cls="panel"))

    parts.append(Div(*charts, cls="grid two"))
    return tuple(parts)


# ── Safe data loaders ─────────────────────────────────────────────────────

def qb_safe_load():
    try:
        ds = QB.qb_load_dataset()
        if ds and not ds.invoices.empty:
            return ds
    except Exception:
        pass
    return None


def sd_safe_load():
    try:
        ds = SD.sd_load_dataset()
        if ds and ds.has_data:
            return ds
    except Exception:
        pass
    return None


def gt_safe_connect():
    try:
        return next(GT.get_db())
    except Exception:
        return None


# ── Platform section renderers ─────────────────────────────────────────────

def render_qb_section(section_key, basis="accrual", range_key="all"):
    """Render a QuickBooks sub-tab."""
    ds = qb_safe_load()
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
                       hx_get=f"/view?platform=qb&section={section_key}&basis={key}&range={range_key}",
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
            kpi_card(k.label, k.value, k.unit, k.hint or "")
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
        cards = [kpi_card(k.label, k.value, k.unit, k.hint or "")
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
        cards = [kpi_card(k.label, k.value, k.unit, k.hint or "")
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
        cards = [kpi_card(k.label, k.value, k.unit, k.hint or "")
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
        cards = [kpi_card(k.label, k.value, k.unit, k.hint or "")
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
        cards = [kpi_card(k.label, k.value, k.unit, k.hint or "")
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


def render_sd_section(section_key):
    """Render a SiteDocs sub-tab."""
    ds = sd_safe_load()
    if not ds:
        return Div(H2("SiteDocs"), Div("No data available.", cls="chart-empty"), cls="mt")

    from charts import sd_charts as SDC

    if section_key == "hse":
        sched_c = SD.schedule_counts(ds.schedules)
        f_count = SD.form_counts(ds.forms)
        part = SD.worker_participation(ds.workers, ds.forms)
        cards = [
            kpi_card("Schedule Compliance", sched_c["completion_pct"], "%",
                     rag=rag_for_value(sched_c["completion_pct"], 80, 60)),
            kpi_card("Overdue Items", float(sched_c["overdue"]), "",
                     rag=rag_for_value(sched_c["overdue"], 5, 15, False)),
            kpi_card("Forms This Month", float(f_count["month"]), ""),
            kpi_card("Worker Participation", part["pct"], "%",
                     rag=rag_for_value(part["pct"], 80, 60)),
        ]
        return (
            H2("HSE Overview"),
            kpi_grid(cards),
            Div(
                Div(H3("Schedule Compliance"), NotStr(SDC.schedule_compliance(ds.schedules)), cls="panel"),
                Div(H3("Forms by Category"), NotStr(SDC.form_category_chart(ds.forms)), cls="panel"),
                cls="grid two"),
            Div(
                Div(H3("Monthly Trend"), NotStr(SDC.forms_trend(ds.forms)), cls="panel"),
                Div(H3("Worker Activity"), NotStr(SDC.worker_leaderboard_table(ds.workers, ds.forms, ds.signatures, ds.schedules)), cls="panel"),
                cls="grid two mt"),
            Div(
                Div(H3("Overdue Items"), NotStr(SDC.overdue_items_list(ds.schedules)), cls="panel"),
                cls="mt"),
        )

    elif section_key == "forms":
        f_count = SD.form_counts(ds.forms)
        w_count = SD.worker_counts(ds.workers)
        cards = [
            kpi_card("Total Forms", float(f_count["total"]), ""),
            kpi_card("This Month", float(f_count["month"]), ""),
            kpi_card("Active Workers", float(w_count["active"]), ""),
        ]
        return (
            H2("Forms & JSAs"),
            kpi_grid(cards),
            Div(
                Div(H3("Forms by Category"), NotStr(SDC.form_category_chart(ds.forms)), cls="panel"),
                Div(H3("Monthly Trend"), NotStr(SDC.forms_trend(ds.forms)), cls="panel"),
                cls="grid two"),
            Div(
                Div(H3("Forms by Type"), NotStr(SDC.form_types_chart(ds.formtypes, ds.forms)), cls="panel"),
                cls="mt"),
        )

    elif section_key == "compliance":
        sched_c = SD.schedule_counts(ds.schedules)
        cards = [
            kpi_card("Completion Rate", sched_c["completion_pct"], "%",
                     rag=rag_for_value(sched_c["completion_pct"], 80, 60)),
            kpi_card("Overdue", float(sched_c["overdue"]), "",
                     rag=rag_for_value(sched_c["overdue"], 5, 15, False)),
            kpi_card("Late", float(sched_c["late"]), ""),
            kpi_card("Cancelled", float(sched_c["cancelled"]), ""),
        ]
        return (
            H2("Compliance"),
            kpi_grid(cards),
            Div(
                Div(H3("Schedule Compliance"), NotStr(SDC.schedule_compliance(ds.schedules)), cls="panel"),
                Div(H3("Forms Trend"), NotStr(SDC.forms_trend(ds.forms)), cls="panel"),
                cls="grid two"),
            Div(
                Div(H3("Overdue & Late Items"), NotStr(SDC.overdue_items_list(ds.schedules)), cls="panel"),
                cls="mt"),
        )

    elif section_key == "incidents":
        inc_c = SD.incident_counts(ds.incidents)
        cards = [
            kpi_card("Total Incidents", float(inc_c["total"]), ""),
            kpi_card("Open", float(inc_c["open"]), ""),
            kpi_card("Investigation", float(inc_c["investigation"]), ""),
            kpi_card("YTD", float(inc_c["ytd"]), ""),
        ]
        return (
            H2("Incidents"),
            kpi_grid(cards),
            Div(
                Div(H3("Incident Trend"), NotStr(SDC.incident_trend(ds.incidents)), cls="panel"),
                Div(H3("By Type"), NotStr(SDC.incident_by_type(ds.incidents)), cls="panel"),
                cls="grid two"),
            Div(
                Div(H3("Status Breakdown"), NotStr(SDC.incident_status_pie(ds.incidents)), cls="panel"),
                cls="grid two mt"),
        )

    elif section_key == "workers":
        w_count = SD.worker_counts(ds.workers)
        part = SD.worker_participation(ds.workers, ds.forms)
        cards = [
            kpi_card("Active Workers", float(w_count["active"]), "",
                     hint=f"of {w_count['total']} total"),
            kpi_card("Contractors", float(w_count["contractors"]), "",
                     hint=f"{w_count['employees']} employees"),
            kpi_card("Participation", part["pct"], "%",
                     rag=rag_for_value(part["pct"], 80, 60)),
        ]
        return (
            H2("Workers"),
            kpi_grid(cards),
            Div(
                Div(H3("Active vs Inactive"), NotStr(SDC.worker_status(ds.workers)), cls="panel"),
                Div(H3("Employee vs Contractor"), NotStr(SDC.worker_type_split(ds.workers)), cls="panel"),
                cls="grid two"),
            Div(
                Div(H3("Worker Activity"), NotStr(SDC.worker_leaderboard_table(ds.workers, ds.forms, ds.signatures, ds.schedules)), cls="panel"),
                cls="mt"),
        )

    elif section_key == "certifications":
        cert_c = SD.cert_summary(ds.certifications, ds.workers)
        cards = [
            kpi_card("Total Certs", float(cert_c["total"]), ""),
            kpi_card("Active", float(cert_c["active"]), ""),
            kpi_card("Expired", float(cert_c["expired"]), ""),
        ]
        return (
            H2("Certifications"),
            kpi_grid(cards),
            Div(
                Div(H3("Expiry Profile"), NotStr(SDC.cert_expiry_profile(ds.certifications)), cls="panel"),
                Div(H3("Coverage"), NotStr(SDC.cert_coverage(ds.certifications, ds.workers)), cls="panel"),
                cls="grid two"),
        )

    elif section_key == "equipment":
        eq_c = SD.equipment_counts(ds.equipment)
        cards = [
            kpi_card("Total Equipment", float(eq_c["total"]), ""),
            kpi_card("Active", float(eq_c["active"]), ""),
        ]
        return (
            H2("Equipment"),
            kpi_grid(cards),
            Div(
                Div(H3("By Type"), NotStr(SDC.equipment_by_type(ds.equipment)), cls="panel"),
                Div(H3("Status"), NotStr(SDC.equipment_status(ds.equipment)), cls="panel"),
                cls="grid two"),
        )

    elif section_key == "locations":
        loc_c = SD.location_counts(ds.locations)
        f_count = SD.form_counts(ds.forms)
        cards = [
            kpi_card("Locations", float(loc_c["total"]), ""),
            kpi_card("Forms Submitted", float(f_count["total"]), ""),
        ]
        return (
            H2("Locations"),
            kpi_grid(cards),
            Div(
                Div(H3("Forms Trend"), NotStr(SDC.forms_trend(ds.forms)), cls="panel"),
                cls="grid two"),
        )

    elif section_key == "signatures":
        sig_c = SD.signature_counts(ds.signatures)
        sched_c = SD.schedule_counts(ds.schedules)
        cards = [
            kpi_card("Signatures", float(sig_c["total"]), ""),
            kpi_card("Schedule Items", float(sched_c["total"]), ""),
        ]
        return (
            H2("Signatures"),
            kpi_grid(cards),
            Div(
                Div(H3("Schedule Compliance"), NotStr(SDC.schedule_compliance(ds.schedules)), cls="panel"),
                cls="grid two"),
        )

    elif section_key == "reports":
        f_count = SD.form_counts(ds.forms)
        sched_c = SD.schedule_counts(ds.schedules)
        sig_c = SD.signature_counts(ds.signatures)
        loc_c = SD.location_counts(ds.locations)
        cards = [
            kpi_card("Forms", float(f_count["total"]), ""),
            kpi_card("Schedules", float(sched_c["total"]), "", hint=f"{sched_c['completed']} completed"),
            kpi_card("Signatures", float(sig_c["total"]), ""),
            kpi_card("Locations", float(loc_c["total"]), ""),
        ]
        return (
            H2("Reports & Trends"),
            kpi_grid(cards),
            Div(
                Div(H3("Forms Trend"), NotStr(SDC.forms_trend(ds.forms)), cls="panel"),
                Div(H3("Schedule Compliance"), NotStr(SDC.schedule_compliance(ds.schedules)), cls="panel"),
                cls="grid two"),
        )

    return Div(H2("SiteDocs"), Div("Section not found.", cls="chart-empty"))


def render_gt_section(section_key):
    """Render a GeoTab sub-tab."""
    conn = gt_safe_connect()
    if not conn:
        return Div(H2("GeoTab Fleet"), Div("No data available.", cls="chart-empty"), cls="mt")

    from charts import gt_charts as GTC

    try:
        now = datetime.now(timezone.utc)
        since_365 = now - timedelta(days=365)
        db = conn

        summary = GT.gt_fleet_summary(db, since_365, now)
        trends = GT.gt_daily_trends(db, since_365, now)
        speed = GT.gt_speed_analysis(db, since_365, now)
        vehicle_util = GT.gt_vehicle_utilization(db, since_365, now)
        idling = GT.gt_idling_summary(db, since_365, now)
        locations = GT.gt_latest_locations(db)

        gt_data = {
            "summary": summary,
            "trends": trends,
            "speed": speed,
            "vehicle_util": vehicle_util,
            "idling": idling,
            "locations": locations,
        }

        db.close()

        kpis_html = GTC.fleet_kpi_row(gt_data)

        return (
            H2("GeoTab Fleet Overview"),
            NotStr(kpis_html),
            Div(
                Div(H3("Daily Mileage Trend"), NotStr(GTC.daily_mileage_chart(gt_data)), cls="panel"),
                Div(H3("Daily Trip Count"), NotStr(GTC.trip_count_chart(gt_data)), cls="panel"),
                cls="grid two"),
            Div(
                Div(H3("Vehicle Utilization"), NotStr(GTC.vehicle_utilization_chart(gt_data)), cls="panel"),
                Div(
                    H3("Vehicle Details"),
                    Div(NotStr(GTC.vehicle_table(gt_data)), cls="panel-scroll"),
                    cls="panel"),
                cls="grid two mt"),
            Div(
                Div(H3("Speed Distribution"), NotStr(GTC.speed_distribution_chart(gt_data)), cls="panel"),
                Div(H3("Idle Time by Vehicle"), NotStr(GTC.idle_time_chart(gt_data)), cls="panel"),
                cls="grid two mt"),
            Div(
                Div(H3("Fleet Locations"), NotStr(GTC.fleet_map(gt_data)), cls="panel"),
                cls="mt"),
        )
    except Exception as e:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        return Div(H2("GeoTab Fleet"), Div(f"Error loading data: {e}", cls="chart-empty"), cls="mt")


# ── Routes ────────────────────────────────────────────────────────────────

@rt("/health")
async def health(req):
    return "OK"


@rt("/_dbcheck")
async def db_check(req):
    """Diagnostic - checks all three DB connections and lists tables."""
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
        "",
        try_connect("GT", "GT_DATABASE_URL"),
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
        content = render_overview()
        title = "Overview"
    elif platform == "qb":
        content = render_qb_section(section or "overview", basis, range_key)
        title = f"QuickBooks - {section.title()}"
    elif platform == "sd":
        content = render_sd_section(section or "hse")
        title = f"SiteDocs - {section.title()}"
    elif platform == "gt":
        content = render_gt_section(section or "fleet")
        title = "GeoTab Fleet"
    else:
        content = render_overview()
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
        return tuple(render_overview())

    if platform == "qb":
        return tuple(render_qb_section(section, basis, range_key))

    if platform == "sd":
        return tuple(render_sd_section(section))

    if platform == "gt":
        return tuple(render_gt_section(section))

    return Div("Unknown platform", cls="chart-empty")


# ── Entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
