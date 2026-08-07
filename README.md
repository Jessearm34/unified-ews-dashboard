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

## How the Direct/Indirect classification works

The sync worker reads each employee's department from Insperity:

- **FIELD** or **SHOP** → Direct
- Everything else → Indirect

Vrutika updates someone's department in Insperity → the next sync picks it up.
No separate database, no manual steps, no code.

## CSV export

Append `?format=csv` to any API URL to download raw data:

| Endpoint | Data |
|---|---|
| `/_api/qb/overview?format=csv` | Filtered invoices |
| `/_api/qb/sales?format=csv` | Filtered invoices |
| `/_api/qb/finance?format=csv` | Chart of accounts |
| `/_api/qb/profitability?format=csv` | P&L detail |
| `/_api/qb/customers?format=csv` | Customer revenue summary |
| `/_api/qb/accounts?format=csv` | Chart of accounts |
| `/_api/sd/hse?format=csv` | All safety forms |
| `/_api/sd/forms?format=csv` | All safety forms |
| `/_api/sd/compliance?format=csv` | Schedule items |
| `/_api/sd/workers?format=csv` | Worker roster |
| `/_api/gt/fleet?format=csv` | Daily trends (mileage, trips) |
| `/_api/gt/maintenance?format=csv` | Vehicle maintenance status |
| `/_api/insperity/workers?format=csv` | Worker roster with classification |
| `/_api/insperity/certs?format=csv` | Cert cross-reference |

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
