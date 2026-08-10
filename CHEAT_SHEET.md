# EWS Dashboard — Technical Cheat Sheet

Quick reference for interviews. Each section explains the *why*, not just the *what*.

---

## 1. REST API Architecture (FastAPI)

**What I built:** A backend that serves JSON to the frontend. Five API modules
(QuickBooks, SiteDocs, GeoTab, Insperity, overview) each with their own routes.

**How REST works here:**
- `GET /_api/qb/overview?range=ytd` → returns KPIs + chart HTML as JSON
- `GET /_api/sd/forms?compare=true` → returns forms with year-over-year overlay
- `GET /_api/insperity/workers?format=csv` → streaming CSV download

**Design choices I made:**
- **Stateless.** Every request is independent. The server doesn't remember who you
  are between requests for API calls. The login session is the only stateful piece.
- **Resource-oriented URLs.** `/_api/{platform}/{section}` — the URL tells you
  what you're getting before you even make the request.
- **Query parameters for filters.** `range`, `compare`, `basis`, `format` — the
  same endpoint returns different views without creating new URLs. Cleaner than
  `/revenue/ytd` vs `/revenue/all`.
- **Parallel data loading.** The overview pulls QuickBooks and SiteDocs
  simultaneously using Python's `ThreadPoolExecutor`. If either fails, the other
  still returns. No single-point blockage.
- **Health check endpoint.** `/health` returns JSON with diagnostics — which env
  vars are set, which databases are reachable, what Python packages are installed.
  Railway uses this to know if the app is alive.

**Problems this avoids:**
- **No GraphQL complexity.** REST is simpler for a dashboard where the data shape
  is known. No over-fetching or under-fetching problems.
- **No server-side rendering for charts.** Charts are rendered server-side as
  Plotly HTML, but the page itself is a SvelteKit SPA. This means the browser
  does the layout work, the server just pumps data. Cheaper on CPU.
- **Timeouts and partial responses.** If QuickBooks is slow, the overview still
  loads SiteDocs data. The `as_completed` pattern means we don't wait for the
  slowest database.

---

## 2. OAuth & Third-Party API Integration

**What I integrated:**
- **QuickBooks Online** — OAuth 2.0 with refresh tokens
- **SiteDocs** — API key authentication
- **GeoTab** — username/password + database name
- **Insperity** — API key in query string (unusual pattern)

**How QuickBooks OAuth works:**
1. User authenticates once through Intuit's OAuth flow → we get an access token
   (short-lived, ~1 hour) and a refresh token (long-lived, ~100 days)
2. On every API call, the backend checks if the access token is expired
3. If expired, it uses the refresh token to get a new access token silently
4. The user never sees this — it's transparent

**Why refresh tokens matter:**
Without them, the dashboard would break every hour and someone would need to
re-authenticate. The refresh token flow keeps the connection alive without
human intervention.

**Insperity's unusual auth pattern:**
Most APIs put the API key in an `Authorization: Bearer xxx` header. Insperity
puts it in the URL as `?apikey=xxx`. This is less secure (URLs get logged) but
it's what they support. I discovered this by reading their developer docs
carefully when all my requests returned 404 — the key was correct, the delivery
method was wrong.

**Static IP requirement:**
Insperity whitelists API access by IP address. Railway uses dynamic outbound IPs
on standard plans. I solved this by putting the Insperity sync worker on a
DigitalOcean droplet ($4/month) with a static IP. The droplet pulls from
Insperity → writes to the shared Postgres → the dashboard (on Railway) reads
from Postgres. Clean separation of concerns.

---

## 3. Frontend — SvelteKit SPA

**What I built:** A single-page application with a top navigation bar and
platform tabs. No page reloads — all navigation is client-side.

**Key concepts:**
- **Reactive state.** `$state()` variables automatically update the UI when
  data changes. No manual DOM manipulation.
- **Stores.** Shared state across components (current platform, current section,
  loading state) using Svelte stores.
- **Static adapter.** The app builds to static HTML/CSS/JS files. The FastAPI
  backend serves these files. No Node.js server needed in production.

**Design choices:**
- **60-second auto-refresh.** `setInterval(load, 60000)` — the dashboard polls
  for new data once per minute. Cache TTL matches at 60 seconds, so every poll
  hits fresh data.
- **Chart HTML injection.** Plotly generates complete HTML fragments (div +
  script tag). Svelte injects these into the DOM by parsing the script tags and
  executing them. This is unusual — most apps use Plotly's JavaScript library
  directly. Server-side rendering means charts work even without JavaScript
  enabled after the initial load.
- **Top nav instead of sidebar.** More horizontal space for charts. Subnav
  uses underline indicators (like browser tabs) instead of background fills.
  Cleaner, less "heavy" feel.

---

## 4. Docker & Railway Deployment

**The Dockerfile:**
```dockerfile
FROM python:3.12-slim
COPY requirements.txt .  →  RUN pip install
COPY api/ charts/ data/ static/  →  CMD uvicorn api.main:app --port $PORT
```

**Key decisions:**
- `python:3.12-slim` — smallest viable image (~150MB). Alpine would be smaller
  but breaks `psycopg2` (needs build-essential). The slim Debian base just works.
- `COPY api/ charts/ data/ static/` — only copy what the app needs. `.git`,
  `node_modules`, `__pycache__` stay out (`.dockerignore`).
- `CMD uvicorn ... --port $PORT` — Railway assigns a random port via the `PORT`
  env var. Hardcoding `8000` caused a 502 (learned this the hard way).

**Railway's health check:**
Railway pings `/health` every few seconds. If it fails for 300 seconds, Railway
kills the container and restarts it. My `/health` endpoint returns diagnostic
data — I added it after the app silently crashed once and there were zero logs.

**Build caching problem (and fix):**
Railway caches Docker layers. After many deploys, the cache served a stale image
with broken Python imports. The fix: `RUN date > /app/.build_ts` at the end of
the Dockerfile forces at least one layer to rebuild every time, which cascades
and refreshes the cache.

---

## 5. Postgres Data Pipeline

**Architecture:**
```
Insperity API → DO droplet → Postgres (Railway) ← FastAPI dashboard
QuickBooks    ─────────────────────────────────────→ FastAPI dashboard
SiteDocs      ─────────────────────────────────────→ FastAPI dashboard
GeoTab        ─────────────────────────────────────→ FastAPI dashboard
```

**Three separate Postgres databases:**
- `QB_DATABASE_URL` — QuickBooks financial data
- `SD_DATABASE_URL` — SiteDocs safety data
- `GT_DATABASE_URL` — GeoTab fleet data

Each platform has its own ingest pipeline (separate from this repo). The
dashboard only reads — never writes to the source databases.

**Insperity sync worker (the one I built):**
- Runs on a cron job every 10 minutes on the droplet
- Pulls employee roster, employment, positions, departments from Insperity API
- Flattens nested JSON (Insperity returns employees with nested `communication`
  and `position` objects — I extract the flat fields the dashboard needs)
- Classifies each worker as Direct or Indirect (FIELD/SHOP → Direct, else
  Indirect)
- Writes to the shared Postgres warehouse
- The dashboard reads from the warehouse, not from Insperity directly

**Why a separate sync worker instead of real-time API calls:**
1. Insperity rate-limits. Real-time on every page load would hit limits.
2. The sync worker has a static IP (droplet), which Insperity whitelists.
3. Headcount data doesn't change second-to-second. 10-minute refresh is fine.
4. If Insperity is down, the dashboard still shows the last known data.

---

## 6. Caching Strategy

**In-memory cache with TTL (time-to-live):**
```python
# api/cache.py
_data_cache: dict[str, Any] = {}  # key → dataset
_cache_ts: dict[str, float] = {}  # key → when loaded

def cached(key, loader, ttl=60):
    if key in cache and (now - timestamp < ttl):
        return cache[key]  # hit — free
    val = loader()         # miss — load from DB
    cache[key] = val
    return val
```

**Why 60 seconds:**
- Frontend polls every 60 seconds
- If cache TTL were 600 seconds (10 min), 9 out of 10 API calls waste CPU
  returning identical data
- At 60 seconds, every poll gets fresh data, no wasted work

**Chart HTML caching:**
Charts are rendered server-side as Plotly HTML. This is CPU-expensive (Plotly
computes every pixel). The chart cache also uses 60-second TTL — no
re-rendering between data refreshes.

---

## 7. Plotly Charting

**How charts get to the browser:**
1. Python reads data from Postgres → pandas DataFrame
2. `plotly.graph_objects.Figure` builds the chart (bars, lines, pie)
3. `fig.to_html()` generates a complete HTML string (div + script tag)
4. The API returns this HTML as part of the JSON response
5. SvelteKit injects the HTML into the page, executes the script, chart renders

**Key Plotly config:**
```python
_PLOT_CONFIG = {"displayModeBar": False, "displaylogo": False, "responsive": True}
```
- `displayModeBar: False` — no toolbar (zoom, pan, download). Cleaner look.
- `responsive: True` — chart resizes to container. No fixed pixel dimensions.
- `dragmode: False` — no accidental drag interactions.

**Dark theme integration:**
- `paper_bgcolor: rgba(0,0,0,0)` — transparent background, chart blends into card
- `plot_bgcolor: rgba(0,0,0,0)` — same for the plot area
- Grid lines at `rgba(48,54,61,0.3)` — barely visible, don't distract
- Font color `#8b949e` — muted gray, readable on dark backgrounds
- `tickangle: -30` on date axes — prevents "January 2025" overlapping

**The "neon problem" and how I fixed it:**
Plotly's default color palette uses bright, saturated colors. On a dark
background, these blast your eyes. I replaced every hardcoded color across
26+ chart functions with a muted professional palette:
- `#4a90d9` (deep blue) instead of electric blue
- `#2d8659` (forest green) instead of neon green  
- `#c78535` (rust) instead of bright orange
- `#c23b3b` (burgundy) instead of hot red

---

## 8. Direct/Indirect Classification

**The business problem:**
Mike Skrbich (CEO) needed a Direct (field workers) vs Indirect (office/SGA)
headcount breakdown by region for investor reporting.

**How it works:**
- Insperity's API returns each employee's department (FIELD, SHOP, ADMIN,
  BUSDEV)
- Rule: FIELD or SHOP → Direct. Everything else → Indirect.
- No manual list, no human intervention. If someone changes departments in
  Insperity, the next sync reflects it.

**Failed approaches (what I learned):**
1. First tried matching Vrutika's manual list against Insperity names. Problem:
   names didn't match perfectly (SCOTT-ALI vs SCOTT, middle names, etc.)
2. Then tried a database table for manual overrides. Problem: no IT team,
   Vrutika can't run SQL.
3. Final solution: pure department-based. Zero maintenance. The source of truth
   is Insperity itself.

---

## 9. Error Handling & Observability

**What I added after the dashboard went down silently:**
- **Startup diagnostics** — logs every env var, database reachability, and
  Python package version on boot. `/health` endpoint returns all of it.
- **Chart error logging** — every chart render wraps in `safe_chart()` which
  logs the full stacktrace instead of `except: pass` (which swallowed errors).
- **5xx middleware** — logs every server error with the full request path.
- **Crash-early database URLs** — if `QB_DATABASE_URL` isn't set, the app logs
  a clear warning instead of silently falling back to a broken localhost default.

---

## Quick Interview Talking Points

- "I built a production dashboard serving four data sources through a REST API."
- "The Insperity integration required static IP whitelisting, so I designed a
  two-tier architecture with a cron worker on a separate droplet."
- "I spent time on error handling and observability — the dashboard has startup
  diagnostics, health checks, and logged error boundaries so we know what broke
  before users do."
- "I worked through Docker caching issues, OAuth token refresh, and Plotly
  color calibration for dark theme accessibility."
- "The Direct/Indirect classification was an iterative design process — went
  through three approaches before landing on the simple, maintainable one."
