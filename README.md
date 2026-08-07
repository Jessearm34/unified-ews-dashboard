# EWS Unified Dashboard

Energy Water Solutions — unified operations dashboard combining QuickBooks,
SiteDocs, GeoTab, and Insperity into a single view.

## What each tab shows

| Tab | Data source | What you see |
|---|---|---|
| **Overview** | All platforms | Cross-platform KPIs and trends |
| **QB · Revenue** | QuickBooks | Revenue trends, top customers, by city/class |
| **QB · Financials** | QuickBooks | P&L waterfall, balance sheet, AR aging, DSO |
| **SD · Incidents** | SiteDocs | Incident counts, severity breakdown, location trends |
| **SD · Safety** | SiteDocs | Safety profile, hazard types, equipment |
| **GT · Fleet** | GeoTab | Vehicle counts, utilization, exceptions |
| **IN · Workers** | Insperity | Headcount, Direct/Indirect breakdown, worker table |
| **IN · Certs** | Insperity + SiteDocs | Certification cross-reference per worker |

## How data flows

```
Insperity → DO droplet cron (10 min) → Postgres (Railway)
QuickBooks                                ↓
SiteDocs   ────────────────────→  FastAPI dashboard (Railway)
GeoTab                                → SvelteKit frontend
```

## Environment variables

All env vars live in **Railway** (dashboard → Variables) except the
Insperity API key which also lives on the DO droplet.

| Variable | Where | Purpose |
|---|---|---|
| `AUTH_PASSWORD` | Railway | Dashboard login password (plain text) |
| `AUTH_DOMAIN` | Railway | Allowed email domain (e.g. energywatersolutions.com) |
| `SESSION_SECRET` | Railway | Random string for session encryption |
| `DATABASE_URL` | Railway | Postgres connection (Railway auto-sets this) |
| `QB_CLIENT_ID` | Railway | QuickBooks OAuth client ID |
| `QB_CLIENT_SECRET` | Railway | QuickBooks OAuth secret |
| `QB_REFRESH_TOKEN` | Railway | QuickBooks OAuth refresh token |
| `QB_REALM_ID` | Railway | QuickBooks company ID |
| `SD_API_KEY` | Railway | SiteDocs API key |
| `SD_COMPANY_ID` | Railway | SiteDocs company UUID |
| `GT_USERNAME` | Railway | GeoTab username |
| `GT_PASSWORD` | Railway | GeoTab password |
| `GT_DATABASE` | Railway | GeoTab database name |
| `GT_SERVER` | Railway | GeoTab server URL |
| `INSPERITY_CLIENT_ID` | Railway + Droplet | Insperity company ID |
| `INSPERITY_API_KEY` | Railway + Droplet | Insperity API key |
| `INSPERITY_BASE_URL` | Droplet | Insperity API base URL |
| `DATABASE_URL` | Droplet | Same Postgres as Railway |

## How to change the dashboard password

1. Go to [Railway](https://railway.app) → unified-ews-dashboard → Variables
2. Find `AUTH_PASSWORD`
3. Change it to the new password
4. Click **Deploy** — the app restarts with the new password

## How to update the Insperity Direct/Indirect classification

The classification lives in the **database**, not in code. Vrutika can update it:

1. Go to [Railway](https://railway.app) → Postgres → Data tab
2. Open the `insperity_classification` table
3. Add or edit a row:
   - `last_name`: uppercase (e.g. "SMITH")
   - `first_name`: uppercase (e.g. "JOHN")
   - `classification`: "direct" or "indirect"
4. The cron job picks it up on the next sync (within 10 minutes)

No code. No git. No IT.

## CSV export

Append `?format=csv` to any Insperity API URL to download data:

```
/_api/insperity/workers?format=csv   → worker roster CSV
/_api/insperity/certs?format=csv     → certification cross-reference CSV
```

## Redeploying

Push to `main` on GitHub. Railway auto-deploys within ~2 minutes.

```bash
git add -A && git commit -m "Update" && git push origin main
```

## DO droplet

The droplet (159.223.171.191) runs a cron job that syncs Insperity data
every 10 minutes. It needs a static IP because Insperity whitelists it.

Cron entry (on the droplet):
```
*/10 * * * * cd /root/unified-ews-dashboard && git pull && /root/unified-ews-dashboard/venv/bin/python pull_insperity.py >> /var/log/insperity.log 2>&1
```
