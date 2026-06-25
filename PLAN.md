# Unified EWS Dashboard — Implementation Plan

> **For Hermes:** Use subagent-driven-development to implement this plan task-by-task.

**Goal:** Build one unified FastHTML dashboard that consolidates all KPIs, charts, and tabs from the three existing dashboards (QuickBooks, SiteDocs, GeoTab) into a single app with an overview + expandable sidebar by platform.

**Architecture:** New FastHTML + HTMX + Plotly app deployed as a 4th Railway service. The three existing dashboards stay up unchanged. The unified app reads from all three Postgres databases (or a single shared one) and renders all data in one place.

**Tech Stack:** python-fasthtml, pandas, plotly, sqlalchemy, psycopg2-binary, gunicorn, uvicorn

---

## Current State (3 Dashboards)

### 1. QuickBooks Dashboard
- **Local path:** `/Users/jesse/Desktop/quickbooks-data-export/` (also `/Users/jesse/Desktop/eww-dashboard-public/`)
- **GitHub:** `Jessearm34/eww-dashboard-public`
- **DB tables:** `quickbooks_customers`, `quickbooks_invoices`, `quickbooks_accounts`, `quickbooks_pnl`, `quickbooks_pnl_detail`
- **Data source:** QuickBooks Online API (OAuth 2.0) → Postgres
- **6 tabs:** Overview, Sales, Finance, Profitability, Customers, Accounts
- **~26 KPIs, ~20 charts**
- **App file:** `visualize_fasthtml/app.py` (667 lines, port 5001)
- **Data layer:** `visualize_fasthtml/data.py`
- **Charts:** `visualize_fasthtml/charts.py`
- **Railway deployment:** Running at `ewsdashboard.live` or Railway-assigned URL

### 2. SiteDocs Dashboard
- **Local path:** `/Users/jesse/Projects/ews-dashboard-public-sitedocs/`
- **GitHub:** `Jessearm34/ews-dashboard-public-sitedocs`
- **DB tables:** `sitedocs_workers`, `sitedocs_equipment`, `sitedocs_incidents`, `sitedocs_certifications`, `sitedocs_forms`, `sitedocs_signatures`, `sitedocs_locations`, `sitedocs_formtypes`, `sitedocs_schedules`
- **Data source:** SiteDocs REST API (API key) → Postgres
- **10 tabs:** HSE, Forms & JSAs, Compliance, Incidents, Workers, Certifications, Equipment, Locations, Signatures, Reports
- **~30 KPIs, ~34 charts**
- **App file:** `visualize_fasthtml/app.py` (801 lines, port 5001)
- **Data layer:** `visualize_fasthtml/data.py`
- **Charts:** `visualize_fasthtml/charts.py`

### 3. GeoTab Fleet Dashboard
- **Local path:** `/Users/jesse/Desktop/geotab-fleet-dashboard/`
- **GitHub:** `Jessearm34/geotab-data-export`
- **DB tables:** `vehicles`, `drivers`, `trips`, `gps_logs`, `fault_codes` (in a separate Postgres DB)
- **Data source:** MyGeotab API (separate sync service) → Postgres
- **1 tab:** Fleet Overview
- **6 KPIs, 7 charts/tables**
- **App file:** `app.py` (547 lines, port 8000/5003)
- **Data layer:** `analytics.py` (SQLAlchemy), `database.py`
- **Models:** `models.py` (SQLAlchemy ORM)

---

## Design: Unified Dashboard

### Layout
```
┌─────────────────────────────────────────────────────┐
│  EWS Unified          [last refreshed]  [logout]    │
├──────────┬──────────────────────────────────────────┤
│          │  ▼ Overview                              │
│  ▦ OVER  │  [KPI cards from ALL platforms]          │
│  VIEW    │  [Cross-platform charts]                 │
│          │                                          │
│  ▼ QB    │  ▼ QuickBooks > Overview                 │
│  ▦ Overv │  [QB KPIs + charts]                     │
│  📈 Sale │                                          │
│  💲 Fina │                                          │
│  💹 Prof │                                          │
│  👥 Cust │                                          │
│  🏦 Acco │                                          │
│          │                                          │
│  ▼ Site  │                                          │
│  Docs    │                                          │
│  🛡️ HSE  │                                          │
│  📋 Form │                                          │
│  ...     │                                          │
│          │                                          │
│  ▼ Geo   │                                          │
│  Tab     │                                          │
│  📊 Flee │                                          │
│          │                                          │
│          │                                          │
├──────────┴──────────────────────────────────────────┤
│  EWS Dashboard · Powered by data                    │
└─────────────────────────────────────────────────────┘
```

### Sidebar Navigation (Collapsible by Platform)

The sidebar has a hierarchical structure:

```
▦ Overview                        ← always visible, shows top KPIs from all
                                  │
▼ QuickBooks                      ← expandable collapsible group
  ▦ Overview                      → QB Overview tab
  📈 Sales                        → QB Sales tab
  💲 Finance                      → QB Finance tab
  💹 Profitability                → QB Profitability tab
  👥 Customers                    → QB Customers tab
  🏦 Accounts                     → QB Accounts tab
                                  │
▼ SiteDocs                         ← expandable collapsible group
  🛡️ HSE                          → SD HSE tab
  📋 Forms & JSAs                  → SD Forms tab
  ✅ Compliance                    → SD Compliance tab
  ⚠️ Incidents                     → SD Incidents tab
  👷 Workers                       → SD Workers tab
  🎓 Certifications               → SD Certifications tab
  🔧 Equipment                    → SD Equipment tab
  📍 Locations                    → SD Locations tab
  ✍️ Signatures                   → SD Signatures tab
  📊 Reports & Trends              → SD Reports tab
                                  │
▼ GeoTab                           ← expandable collapsible group
  📊 Fleet Overview                → GT Fleet tab
```

- Groups start **collapsed** by default
- Clicking a group header expands/collapses its child tabs
- Clicking a child tab loads that section's content via HTMX
- Only ONE group can be expanded at a time (or allow multiple — TBD)
- Active tab is highlighted with accent color

### Overview Tab (Cross-Platform)

The Overview tab cherry-picks the **most important KPIs and charts** from each platform:

**Top KPI Row (12 cards, 4 per platform):**
| Platform | KPI 1 | KPI 2 | KPI 3 | KPI 4 |
|----------|-------|-------|-------|-------|
| **QuickBooks** | Revenue (window) | Cash on Hand | Outstanding AR | Net Income |
| **SiteDocs** | Schedule Compliance % | Overdue Items | Worker Participation % | Forms This Month |
| **GeoTab** | Active Vehicles | Fleet Miles | Total Trips | Speeding Events |

**Charts (2×2 grid):**
1. **Monthly Revenue Trend** (QuickBooks — line chart)
2. **Schedule Compliance Donut** (SiteDocs — donut chart)
3. **Fleet Daily Mileage Trend** (GeoTab — line+area chart)
4. **Forms Monthly Trend** (SiteDocs — bar chart)

**Secondary row (2×2):**
5. **A/R Aging** (QuickBooks — bar chart)
6. **Worker Activity Leaderboard** (SiteDocs — HTML table, top 10)
7. **Vehicle Utilization** (GeoTab — horizontal bar, top 10)
8. **P&L Waterfall** (QuickBooks — waterfall chart)

---

## Implementation Plan

### Task 1: Create repo and project structure

**Create `/Users/jesse/Desktop/unified-ews-dashboard/` with:**

```
unified-ews-dashboard/
├── app.py                 # Main FastHTML app
├── data/                  # Data loading modules
│   ├── qb_data.py         # Copy/adapt from quickbooks.../visualize_fasthtml/data.py
│   ├── sd_data.py         # Copy/adapt from sitedocs.../visualize_fasthtml/data.py
│   └── gt_data.py         # Copy/adapt from geotab/analytics.py
├── charts/                # Chart builders
│   ├── qb_charts.py       # Copy from quickbooks.../visualize_fasthtml/charts.py
│   ├── sd_charts.py       # Copy from sitedocs.../visualize_fasthtml/charts.py
│   └── gt_charts.py       # Copy/inline from geotab/app.py charts
├── requirements.txt       # All dependencies
├── Dockerfile             # Production container
├── railway.json           # Railway deployment config
└── .env                   # Local env vars (gitignored)
```

**Tasks:**
1. Create directory structure
2. Initialize git
3. Write `requirements.txt`
4. Copy data modules from each repo (stripping app-prefix imports)
5. Copy chart modules from each repo

### Task 2: Port data loading modules

**Subtask 2a: `data/qb_data.py`**
- Copy `quickbooks-data-export/visualize_fasthtml/data.py` → `data/qb_data.py`
- Rename load_dataset() → qb_load_dataset()
- Database URL: read from env var `QB_DATABASE_URL`
- Keep all KPI computation and aggregation functions

**Subtask 2b: `data/sd_data.py`**
- Copy `ews-dashboard-public-sitedocs/visualize_fasthtml/data.py` → `data/sd_data.py`
- Rename load_dataset() → sd_load_dataset()
- Database URL: read from env var `SD_DATABASE_URL`
- Keep all aggregation functions

**Subtask 2c: `data/gt_data.py`**
- Copy `geotab-fleet-dashboard/database.py` + subset of `analytics.py` → `data/gt_data.py`
- Database URL: read from env var `GT_DATABASE_URL`
- Keep AnalyticsService and all query methods

### Task 3: Port chart modules

**Subtask 3a: `charts/qb_charts.py`**
- Copy `quickbooks-data-export/visualize_fasthtml/charts.py` → `charts/qb_charts.py`
- Rename functions to avoid collisions (e.g., revenue_trend → qb_revenue_trend)

**Subtask 3b: `charts/sd_charts.py`**
- Copy `ews-dashboard-public-sitedocs/visualize_fasthtml/charts.py` → `charts/sd_charts.py`
- Rename functions with sd_ prefix

**Subtask 3c: `charts/gt_charts.py`**
- Extract chart-building functions from `geotab-fleet-dashboard/app.py` → `charts/gt_charts.py`
- Prefix with gt_

### Task 4: Build main app (`app.py`)

The main app is the largest task. It needs:

1. **App setup** — FastHTML app with common styles, Plotly CDN, session auth
2. **Auth** — Email + password (same mechanism as existing apps)
3. **Sidebar navigation** — Hierarchical with collapsible platform groups
4. **Overview section** — Cross-platform KPIs and charts
5. **Platform sections** — Each sub-tab renders the original dashboard content

**Sidebar implementation:**
- HTML structure with collapsible `<details>` / `<summary>` elements
- Or JS-enhanced `<div>` toggles
- Each child tab is an `<a>` with `hx-get="/view?platform=qb&section=overview"` and `hx-target="#content"`
- Active tab gets `.active` class

**Routing:**
- `GET /` → render index with Overview selected by default
- `GET /view?platform={qb|sd|gt}&section={section_key}` → HTMX fragment for that section
- `GET /login` → login form
- `POST /login` → authenticate
- `GET /logout` → clear session

**Section renderers:**
- `render_qb_section(key, data)` — delegates to QB charts + KPI builders
- `render_sd_section(key, data)` — delegates to SD charts + KPI builders
- `render_gt_section(key, data)` — delegates to GT charts + KPI builders
- `render_overview(qb_data, sd_data, gt_data)` — cherry-picks top KPIs from all three

### Task 5: Build Dockerfile

- Base: `python:3.12-slim`
- Dependencies from `requirements.txt`
- Copy all source files
- Expose port (Railway provides `$PORT`)
- CMD: `gunicorn -k uvicorn.workers.UvicornWorker app:app --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 120`

### Task 6: Railway deployment

**`railway.json`:**
```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "Dockerfile"
  },
  "deploy": {
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10,
    "healthcheckPath": "/health"
  }
}
```

**Env vars to set on Railway:**
| Variable | Source | Purpose |
|----------|--------|---------|
| `QB_DATABASE_URL` | QB dashboard's Postgres | QuickBooks data |
| `SD_DATABASE_URL` | SiteDocs dashboard's Postgres | SiteDocs data |
| `GT_DATABASE_URL` | Geotab dashboard's Postgres | Geotab data |
| `DASHBOARD_LOGIN_PASSWORD` | Same as existing dashboards | Auth |
| `DASHBOARD_LOGIN_PASSWORD_HASH` | Same as existing | Auth (optional) |
| `DASHBOARD_LOGIN_DOMAIN` | `energywatersolutions.com` | Auth |
| `FASTHTML_SECRET_KEY` | New secret key | Session signing |
| `PORT` | `8000` (Railway auto-sets) | Server port |

---

### Database architecture decision

There are two approaches for the database:

**Option A — 3 separate DB connections (recommended for now)**
- Each platform keeps its own Postgres database (as currently deployed)
- Unified app connects to all three via `QB_DATABASE_URL`, `SD_DATABASE_URL`, `GT_DATABASE_URL`
- Simplest migration — no changes to existing pipelines
- Downside: 3 connections per page load

**Option B — 1 unified Postgres database**
- All tables (quickbooks_*, sitedocs_*, vehicles, trips, etc.) on one Postgres instance
- Cleaner architecture but requires migrating data pipelines
- Worth considering if all three already share the same Postgres (e.g., the `ews-warehouse` Docker container)

**Recommendation:** Start with Option A (separate DB URLs). If the existing dashboards already all write to the same `ews-warehouse` Postgres (check Railway configs), use a single `DATABASE_URL` instead.

### Auth: Single sign-in for unified dashboard

The new dashboard uses the same auth mechanism (email + password) as the existing ones:
- One shared password for the whole team
- Email domain check: `@energywatersolutions.com`
- Pbkdf2-hmac-sha256 hash for password storage

The existing dashboards remain behind their own login — they stay up as-is with their own auth.

---

## Risks & Open Questions

1. **DB connectivity in production** — Need to verify each existing dashboard's Railway Postgres URL is accessible from the new deployment. If they're on different Railway projects, cross-project DB access needs to be configured.

2. **Data freshness** — Each platform refreshes on its own schedule. The unified dashboard reads whatever's in the DB at query time.

3. **Deployment** — Create a NEW Railway project for the unified dashboard (don't touch the existing 3 deployments). Set all env vars manually.

4. **Port conflicts** — Current apps use ports 5001 (QB, SD) and 5003/8000 (GT). Unified app should use whatever `$PORT` Railway provides (default 8000).

5. **DB table collisions** — Ensure table names don't collide across platforms. QuickBooks uses `quickbooks_*`, SiteDocs uses `sitedocs_*`, Geotab uses bare `vehicles` / `trips` etc. — safe as long as they're separate databases.

6. **Geotab model imports** — The Geotab dashboard uses SQLAlchemy ORM models (`models.py`). The unified app could either import these models or use raw SQL/pandas read_sql instead.

7. **CSS conflicts** — All three dashboards use almost identical CSS (navy sidebar, same variables). The unified app should use the same design system — just copy the CSS once.

---

## File Manifest

### New files to create:
```
unified-ews-dashboard/
├── .env                    # Local config (gitignored)
├── .gitignore
├── .env.example
├── requirements.txt
├── Dockerfile
├── railway.json
├── app.py                  # ~1200 lines — main app with sidebar + all sections
├── data/
│   ├── __init__.py
│   ├── qb_data.py          # ~500 lines — from quickbooks.../data.py
│   ├── sd_data.py          # ~575 lines — from sitedocs.../data.py
│   └── gt_data.py          # ~400 lines — from geotab/analytics.py + database.py
└── charts/
    ├── __init__.py
    ├── qb_charts.py         # ~400 lines — from quickbooks.../charts.py
    ├── sd_charts.py         # ~309 lines — from sitedocs.../charts.py
    └── gt_charts.py         # ~150 lines — extracted from geotab/app.py
```

### Files to NOT touch (leave existing dashboards running):
- `quickbooks-data-export/` — stays up unchanged
- `ews-dashboard-public-sitedocs/` — stays up unchanged
- `geotab-fleet-dashboard/` — stays up unchanged

---

## Execution Order

### Phase 1: Scaffold (1 task)
1. Create directory structure, `.env.example`, `requirements.txt`, `Dockerfile`, `railway.json`

### Phase 2: Port data layers (3 tasks — one per platform)
2. Copy/adapt QuickBooks data module
3. Copy/adapt SiteDocs data module
4. Copy/adapt Geotab data module

### Phase 3: Port chart layers (3 tasks — one per platform)
5. Copy/adapt QuickBooks chart module
6. Copy/adapt SiteDocs chart module
7. Extract Geotab chart module

### Phase 4: Main app (1 large task)
8. Build `app.py` — auth, sidebar, routing, overview, all section renderers

### Phase 5: Deploy (1 task)
9. Push to GitHub, create Railway project, set env vars, deploy

---

## Verification Plan

1. **Local:** Run `python app.py` and verify:
   - Login works
   - Overview shows KPIs from all three platforms
   - Each platform group expands in sidebar
   - Each sub-tab loads correct KPIs and charts
   - No broken charts or empty data errors

2. **Railway:** Deploy and verify:
   - Health check passes (`/health`)
   - All three DB connections work
   - Charts render with real production data
   - No errors in Railway logs

3. **Edge cases:**
   - If a platform's DB is down, show graceful error (not 500)
   - Empty datasets show "No data" placeholder, not broken chart
   - HTMX loading indicator shows during data fetch
