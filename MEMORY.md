# EWS Unified Dashboard — Memory & Conventions

> This file is the durable record for this project. Hermes memory points here.
> Last updated: July 2026

---

## User Profile

- **Jesse** — Direct, irreverent, hates AI-sounding writing. Powerlifter, barefoot shoes (Vivo/Xero).
- **FocusShield iOS dev**, college student. iPhone 14 Pro.
- **EWS** (Energy Water Solutions) — Tomball, TX. VOX wastewater treatment.
- Work style: step-back whole-picture diagnosis before patching. Hates partial/surface fixes. Force-push complete solutions.
- Prefers programmatic fixes over GUI steps. Gets furious at GUI instructions.
- Prefers phased execution (Phase 1 → ask → Phase 2).
- Data viz: only show temporal (time-series) or comparative (multiple-entity) charts. Charts must be genuinely useful.
- Wants permanent chart structures with constant auto-updating data. SvelteKit over FastHTML for new dashboards.

---

## Environment

- **Repo:** `/Users/jesse/Desktop/EWS/unified-ews-dashboard`
- **GitHub:** `git@github.com:Jessearm34/unified-ews-dashboard.git` (origin/main)
- **Remote origin/main is often ahead** of local with extra debug routes — always `git pull --rebase` before push.
- **Active Hermes profile:** `default` (at `~/.hermes/config.yaml`)

### Railway Deployments

| Service | DB Env Var | Auth |
|---|---|---|
| unified-ews-dashboard | `GT_DATABASE_URL` | `require_login()` |
| geotab-data-export | `DATABASE_URL` | `AuthMiddleware` |

**All dashboard edits go to unified-ews-dashboard**, NOT the legacy geotab-fleet-dashboard.

### Database Notes

- Railway SQLAlchemy 1.x: use `text()` only, no bind params.
- Separate Postgres per project.

---

## SiteDocs Integration

| Detail | Value |
|---|---|
| API Base | `api-1.sitedocs.com` (REST fails DNS — use direct) |
| Auth | `x-api-key` header or `Authorization` |
| Content/Value | JSON dicts parsed with `_extract_label()` |
| Forms table | Metadata only (fields via `/api/v1/forms/content/{fid}`) |
| BBSO Form Type UUID | `5add4d1b-82c6-4067-a300-6f005612f3a7` |
| SD_DATABASE_URL | Warehouse Postgres for `sitedocs_*` tables |

---

## Dashboard Architecture

- **Frontend:** SvelteKit SPA (build output → `static/` or `build/`)
- **Backend:** FastAPI with Plotly chart rendering
- **API Pattern:** `GET /_api/{platform}/{section}` returns JSON with KPIs + chart HTML
- **Sections:**
  - SD: hse, forms, compliance, workers
  - GT: fleet (includes safety), maintenance
  - QB: overview, sales, finance, profitability, customers, accounts
- **Data cache:** Per-platform, 600s TTL, invalidated on writes
- **Auth:** Session-based login via FastAPI sessions

---

## Data Sources & Key Metrics

### SiteDocs (10 tables)
- **Workers:** total/active/inactive/employee/contractor counts
- **Equipment:** total/active/inactive by type
- **Incidents:** open/closed/investigation/ytd, monthly trend, by type/status
- **Certifications:** active/expiring/expired counts, coverage %, type breakdown
- **Forms:** total/this-month, monthly trend, by category (JSA/Inspection/Incident/Training/Other)
- **Form Responses:** BBSO safe/at-risk by category, task observations, RIR events
- **Schedules:** completion %, overdue/late/scheduled/cancelled, overdue items
- **Signatures, Locations, FormTypes:** metadata counts

### Geotab (13 query groups)
- Fleet summary, daily trends, vehicle utilization, idling, speed analysis, driver metrics, maintenance metrics, seatbelt analysis, after-hours analysis, speed trend, exception analysis, vehicle maintenance status, safety driver rankings

### QuickBooks
- Revenue, cash, AR aging, DSO, working capital, P&L, customer analysis

---

## CSS/UI Conventions

- **Auth page** uses `--navy: #0a1f33` background
- **Dashboard cards** — clean slate, no AI tips/notes/classifications
- **HTMX sidebar:** detect `HX-Request` header, return bare `HTMLResponse(body)` not full page
- **RAG colors:** green `#16a34a`, amber `#ea580c`, red `#dc2626`

---

## Dashboard Improvement Roadmap

### Phase 1 — Surface Existing Data (highest priority)
1. BBSO Risk Heatmap from `sd_data.bbso_at_risk_by_category()` — already have the data, not shown
2. Period-over-period deltas on all KPIs (data structure exists, just needs compute)
3. Unified safety score — composite of SiteDocs BBSO/RIR + Geotab driver safety
4. "Issues Needing Attention" panel — overdue items, expired certs, open incidents >30d, fault codes, low-scoring drivers
5. BBSO-to-incident ratio as leading indicator KPI

### Phase 2 — New Computations
1. Person-level cross-platform joins (workers ↔ drivers)
2. Time-to-close for incidents
3. Idle cost in dollars
4. Reporting culture index (RIR / Incidents ratio)
5. Alert thresholds with visual indicators

### Phase 3 — Story & Narrative
1. Compare mode (this period vs last period)
2. Trend overlay of last year's data
3. Cross-platform correlation charts

### Phase 4 — Architecture
1. Data quality dashboard (last ingest timestamp, record counts, error rate)
2. Automated anomaly detection on key metrics
3. Export / PDF report generation
4. Mobile-friendly view for field supervisors

---

## Details on BBSO Form Response Analysis

The `form_responses` table contains rich per-item data:
- `GroupTitle` — category (PPE, Line of Fire, Housekeeping, Task Information, etc.)
- `ItemType` — YesNo, PassFailCounter, Inspection, Text, etc.
- `ItemValue` — Yes/No, Pass/Fail, or free text
- `ItemContent` — the question text
- `Comments` — observer notes

The `bbso_at_risk_by_category()` function in `sd_data.py` classifies:
- "Safe" = Yes/Pass/True/Safe/1
- "AtRisk" = No/Fail/False/0

This gives a per-category Safe% that can be trended over time.

---

## Phase 1 Implementation (July 2026) — Complete

### New Modules
| Module | Purpose | Phase 2/3 Ready |
|---|---|---|
| `data/issues.py` | Cross-platform issue aggregation + unified safety score | Extensible for alerts, person-level joins |
| `charts/issues_charts.py` | HTML table renderer for issues panel | Reusable for alert panels |

### New Functions
- **`sd_data.bbso_incident_ratio()`** — BBSO-to-incident ratio leading indicator with monthly trend
- **`sd_charts.bbso_risk_heatmap()`** — Horizontal bar chart of Safe% per BBSO category (PPE, LOF, etc.) with green/yellow/orange/red coloring
- **`issues.collect_issues()`** — Aggregates from SD (overdue schedules, expired certs, open incidents) + GT (fault codes, low driver scores)
- **`issues.unified_safety_score()`** — Weighted composite: 40% worker participation, 20% schedule compliance, 20% BBSO ratio, 20% driver safety
- **`issues_charts.issues_table()`** — HTML table with severity dots, platform badges, detail text
- **`utils.previous_range()`** — Computes previous equivalent time range for any preset
- **`utils.compute_delta()`** — Percentage change between two values

### Route Changes
- **`GET /_api/overview`**: Unified Safety Score KPI (top), period-over-period deltas on QB revenue/net income, Issues Needing Attention panel
- **`GET /_api/sd/hse`**: BBSO Risk Heatmap chart, BBSO:Incident Ratio KPI with RAG

### Frontend Changes
- Both overview and platform pages pass `delta_up_good` → `deltaUpGood` to KPICard (snake→camel mapping)
- All new charts render automatically via the generic chart grid

---

## Phase 3 Implementation (July 2026) — Complete

### Trend Overlay (year-over-year on trend charts)
All monthly trend chart builders now accept an optional `compare_forms` / `compare_invoices` parameter:
- **`sd_charts.bbso_trend(forms, compare_forms=None)`** — dashed overlay line in purple
- **`sd_charts.rir_trend(forms, compare_forms=None)`** — dashed overlay line in orange
- **`sd_charts.forms_trend(forms, compare_forms=None)`** — dashed overlay line in blue
- **`qb_charts.trend(invoices, metric, compare_invoices=None)`** — dashed overlay line in gray

Added shared helper: **`sd_charts.overlay_compare(fig, compare_df, ...)`** — adds a dashed line trace with year-aligned months.

### Compare Mode Toggle
- **Backend**: `GET /_api/overview?compare=true` and `GET /_api/sd/{section}?compare=true` — pass previous year's data to trend chart builders for overlay
- **Frontend**: "Compare" toggle button on both overview and SD platform pages. When active, BBSO, RIR, forms, and revenue trend charts show last year's data as a dashed overlay line

### New Modules
| Module | Purpose |
|---|---|
| `charts/cross_charts.py` | Cross-platform correlation charts (SD → GT) |
| `charts/cross_charts.safety_fleet_dual()` | Dual-axis: BBSO bars vs speeding events line |

### Correlation Chart
- **`GET /_api/overview`**: Now includes a "Safety ↔ Fleet Correlation" chart showing monthly BBSO observations (bars, left axis) vs speeding events (line, right axis) — reveals if safety culture and fleet risk move together
- Uses existing `sd_data.bbso_monthly_trend()` and `gt_data.speed_trend()` — no new queries needed

### Route Changes
- **`GET /_api/overview`**: New `?compare` query param, new correlation chart
- **`GET /_api/sd/{section}`**: New `?compare` query param for HSE/forms/compliance sections

---

## Phase 2 Implementation (July 2026) — Complete

### New Data Functions
| Function | Module | Purpose |
|---|---|---|
| `sd_data.rir_incident_ratio()` | sd_data.py | RIR-to-incident ratio — the "reporting culture index". High = people report near misses before they become incidents |
| `sd_data.incident_close_time()` | sd_data.py | Mean/median days to close incidents. Checks for CloseOn/LastModifiedOn columns, falls back to CreatedOn estimate |
| `gt_data.idling_cost()` | gt_data.py | Converts idle hours to dollar cost ($5/hr default). Returns estimated_cost, savings_target (20% reduction), top 5 vehicles |
| `issues.cross_person_profiles()` | issues.py | Matches SiteDocs workers to GeoTab drivers by name. Returns combined profiles with SD BBSO/RIR counts + GT trip/miles/safety score |

### Threshold Alerts (added to `issues.collect_issues()`)
- **Compliance Alert**: High severity when schedule compliance drops below 70%
- **BBSO Stale**: Medium severity when no BBSO submissions in 30+ days
- **Slow Incident Resolution**: Medium severity when avg close time exceeds 30 days

### Route Changes
- **`GET /_api/sd/hse`**: New KPIs — "Reporting Culture Index" (RIR:Incident ratio, RAG: 5/2), "Avg Incident Close Time" (RAG: 14/30d)
- **`GET /_api/gt/fleet`**: New KPI — "Idle Cost" showing estimated $ cost + savings target hint
- **`GET /_api/overview`**: New "Combined Profiles" chart showing SD↔GT person matches with safety scores

### New Chart
- **`cross_charts.person_profiles_table()`** — HTML table of matched worker-driver profiles. Shows SD safety activity badge, BBSO/RIR counts, GT trips/miles, driver safety score

---

## Writing Style (for generated text)

- No AI-sounding writing. No "this proposal represents", "not a speculative leap", "materially mitigates"
- No rhetorical flourishes
- Plain English, short sentences, direct
- Accuracy matters — correct errors immediately
