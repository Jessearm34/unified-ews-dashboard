"""One-time: create and seed the ``insperity_classification`` table.

Run this ONCE on the DB server (Railway or droplet):

    python3 seed_classification.py

After this, Vrutika updates classifications through Railway's DB UI —
no code, no git, no IT needed.  The cron worker reads this table on
every sync.
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set")

engine = create_engine(DATABASE_URL)

with engine.begin() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS public.insperity_classification (
            last_name   TEXT NOT NULL,
            first_name  TEXT NOT NULL,
            classification TEXT NOT NULL CHECK (classification IN ('direct', 'indirect')),
            PRIMARY KEY (last_name, first_name)
        );
    """))

    # Vrutika Patel's classification — source of truth as of Aug 2026
    data = [
        ("SKRBICH",     "MIKE",         "indirect"),
        ("PATEL",       "VRUTIKA",      "indirect"),
        ("NOUREDDINE",  "SCOTT-ALI",    "indirect"),
        ("BLAKEMAN",    "BRADLEY",      "indirect"),
        ("KEYSER",      "JUSTIN",       "indirect"),
        ("ELLIS",       "JUSTIN",       "indirect"),
        ("COHEE",       "LONNY",        "indirect"),
        ("MCBRYANT",    "JAMES",        "indirect"),
        ("PERRYMAN",    "ADAM",         "direct"),
        ("KEEL",        "COLBY",        "direct"),
        ("BARRETT",     "JARED",        "direct"),
        ("CANTU",       "JOSE",         "direct"),
        ("LONG",        "DAVID",        "direct"),
        ("NEWBOLD",     "CARTER",       "direct"),
        ("HOWER",       "HAILEN",       "direct"),
        ("MUNOZ",       "RAUL",         "direct"),
    ]

    for last, first, cls in data:
        conn.execute(
            text("""
                INSERT INTO public.insperity_classification (last_name, first_name, classification)
                VALUES (:last, :first, :cls)
                ON CONFLICT (last_name, first_name) DO UPDATE SET classification = EXCLUDED.classification
            """),
            {"last": last, "first": first, "cls": cls},
        )

    result = conn.execute(text("SELECT count(*) FROM public.insperity_classification"))
    count = result.scalar()
    print(f"Classification table seeded: {count} rows")
