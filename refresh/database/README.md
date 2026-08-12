# Central Warehouse (PostgreSQL)

The single SQL database all dashboards will eventually read from, replacing
scattered CSV files. This is the first step toward the multi-dashboard,
multi-source architecture.

## Useful commands

```bash
# Database server (Docker)
docker start ews-warehouse      # start the DB server
docker stop  ews-warehouse      # stop it (data persists in the ews_pgdata volume)
docker ps --filter name=ews-warehouse   # check it's running

# Load / refresh data
source .venv/bin/activate
python database/ingest.py       # (re)load all source exports into the warehouse

# Inspect with SQL
docker exec -it ews-warehouse psql -U ews -d warehouse
#   \dt                                  list tables
#   select count(*) from quickbooks_invoices;

# Run the dashboard
source .venv/bin/activate
python visualize_fasthtml/app.py   # -> http://localhost:5001
```

## Engine

PostgreSQL 16, running in Docker (native ARM, no emulation). Persistent —
survives restarts via a named Docker volume.

| Setting | Value |
| --- | --- |
| Host / port | `localhost:5432` |
| Database | `warehouse` |
| User / password | `ews` / `ews_local_dev` *(local dev only — rotate for any shared/hosted deployment)* |
| Connection URL | `postgresql+psycopg2://ews:ews_local_dev@localhost:5432/warehouse` |

## Start / stop the server

```bash
# First-time create (already done):
docker run -d --name ews-warehouse \
  -e POSTGRES_PASSWORD=ews_local_dev -e POSTGRES_USER=ews -e POSTGRES_DB=warehouse \
  -p 5432:5432 -v ews_pgdata:/var/lib/postgresql/data postgres:16

docker start ews-warehouse     # start an existing container
docker stop  ews-warehouse     # stop it (data persists in the ews_pgdata volume)
```

## Load data

```bash
source .venv/bin/activate
python database/ingest.py
```

Loads each source export into raw "landing" tables named `<source>_<entity>`
(e.g. `quickbooks_invoices`). Re-running replaces the tables with the latest
export. Override the target with `DATABASE_URL` to point at a hosted DB later.

## Data sources

| Source | Domain | Status |
| --- | --- | --- |
| QuickBooks | Billing / accounting | **Connected** (`quickbooks_*` tables) |
| SiteDocs | Safety / HSE | Planned — add folder to `SOURCES` in `ingest.py` |
| Insperity | HR / payroll | Planned |
| EquipT | Equipment / assets | Planned |

## Inspect

```bash
docker exec -it ews-warehouse psql -U ews -d warehouse
# \dt           list tables
# select count(*) from quickbooks_invoices;
```

## Next steps (not done yet)

- Point the FastHTML dashboard's data layer at the DB instead of CSVs.
- Add the other three source folders to `SOURCES` as their exports come online.
- For multi-user / hosted use: move off the Docker container to a hosted
  Postgres, rotate credentials, and add the auth + row-level data-scoping layer.
