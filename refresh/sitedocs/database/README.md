# Central Warehouse (PostgreSQL)

Single SQL database shared by all EWS dashboards, including the SiteDocs
safety dashboard.  Mirrors the QuickBooks warehouse pattern.

## Useful commands

```bash
docker start ews-warehouse              # start the DB server
docker stop  ews-warehouse              # stop it (data persists)
docker exec -it ews-warehouse psql -U ews -d warehouse
```

## SiteDocs tables

| Table | Source | Description |
| --- | --- | --- |
| `sitedocs_workers` | `workers/workers.csv` | All workers (employees + contractors), active/inactive |
| `sitedocs_equipment` | `equipment/equipment.csv` | Equipment roster with specs, location, status |
| `sitedocs_certifications` | `certifications/certifications.csv` | Worker certifications with expiry dates |
| `sitedocs_incidents` | `incidents/incidents.csv` | Safety incidents (near miss → recordable) |
| `sitedocs_forms` | `forms/forms.csv` | Safety forms, JSA safe-work permits |

## Connection

| Setting | Value |
| --- | --- |
| Host / port | `localhost:5432` |
| Database | `warehouse` |
| User / password | `ews` / `ews_local_dev` |
| URL | `postgresql+psycopg2://ews:ews_local_dev@localhost:5432/warehouse` |
