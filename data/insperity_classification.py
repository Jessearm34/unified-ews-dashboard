"""Source of truth: ``insperity_classification`` table in Postgres.

If someone is NOT in this table, classify by Insperity department:
  FIELD / SHOP → Direct    everything else → Indirect

To add or change someone, update the table directly (Railway DB UI
or the admin endpoint).  No code changes, no git, no IT needed.
"""

DIRECT_DEPT_NAMES = {"FIELD", "SHOP", "MAINTENANCE", "INSTALLATION", "OPERATIONS"}


def build_classification_lookup(engine) -> dict:
    """Return ``{last first → direct|indirect}`` from the DB.

    Populate once from Vrutika's list, then she updates the table
    through Railway's database UI whenever someone changes.
    """
    import pandas as pd
    try:
        df = pd.read_sql_table("insperity_classification", engine, schema="public")
        out = {}
        for _, r in df.iterrows():
            key = f"{str(r['last_name']).strip()} {str(r['first_name']).strip()}".upper()
            out[key] = str(r["classification"]).strip().lower()
        return out
    except Exception:
        return {}


def classify(last_name: str, first_name: str, department_name: str | None,
             lookup: dict) -> str:
    """Resolve classification: Vrutika's list → department default → Indirect."""
    key = f"{last_name} {first_name}".strip().upper()
    if key in lookup:
        return lookup[key]
    if department_name and department_name.upper() in DIRECT_DEPT_NAMES:
        return "direct"
    return "indirect"
