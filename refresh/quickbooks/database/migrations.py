"""Database migrations / schema initialization.

Run automatically when tokens are first read or written; safe to call
multiple times (all DDL uses IF NOT EXISTS).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine


def ensure_oauth_tokens_table(engine: Engine) -> None:
    """Create the oauth_tokens table if it does not already exist."""
    ddl = text(
        """
        CREATE TABLE IF NOT EXISTS oauth_tokens (
            id           SERIAL PRIMARY KEY,
            service      TEXT        NOT NULL UNIQUE,
            access_token TEXT        NOT NULL,
            refresh_token TEXT       NOT NULL,
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    with engine.begin() as conn:
        conn.execute(ddl)
