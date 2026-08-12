from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import yaml

ROOT = Path(__file__).resolve().parents[1]

logger = logging.getLogger(__name__)

PLACEHOLDER_PREFIX = "PLACEHOLDER"


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    return raw in ("1", "true", "yes", "on")


def is_placeholder(value: str | None) -> bool:
    if not value:
        return True
    return value.strip().upper().startswith(PLACEHOLDER_PREFIX)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _get_db_engine():
    """Return a SQLAlchemy engine for DATABASE_URL, or None if not configured."""
    try:
        from sqlalchemy import create_engine, text

        url = os.environ.get("QB_DATABASE_URL", "") or os.environ.get("DATABASE_URL", "")
        url = url.strip()
        if not url:
            return None
        # Normalise legacy postgres:// scheme and ensure SSL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif url.startswith("postgresql://") and not url.startswith("postgresql+psycopg2://"):
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
        if "sslmode=" not in url:
            # Private internal Railway connections don't support SSL negotiation;
            # explicitly disable SSL for those and require it for public proxy URLs.
            from urllib.parse import urlparse
            _host = urlparse(url.split("?")[0]).hostname or ""
            sep = "&" if "?" in url else "?"
            if _host.endswith(".railway.internal"):
                url = f"{url}{sep}sslmode=disable"
            else:
                url = f"{url}{sep}sslmode=require"
        engine = create_engine(url, pool_pre_ping=True)
        # Smoke-test the connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return engine
    except Exception as exc:
        logger.warning("Could not connect to database: %s", exc)
        return None


def _ensure_table(engine) -> None:
    """Bootstrap the oauth_tokens table (idempotent)."""
    try:
        from database.migrations import ensure_oauth_tokens_table
        ensure_oauth_tokens_table(engine)
    except Exception as exc:
        logger.warning("Could not ensure oauth_tokens table: %s", exc)


def _load_tokens_from_db() -> Optional[tuple[str, str]]:
    """Return (access_token, refresh_token) for the 'quickbooks' service from
    the database, or None if unavailable / not yet stored."""
    engine = _get_db_engine()
    if engine is None:
        return None
    try:
        _ensure_table(engine)
        from sqlalchemy import text
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT access_token, refresh_token "
                    "FROM oauth_tokens WHERE service = :svc"
                ),
                {"svc": "quickbooks"},
            ).fetchone()
        if row:
            return row[0], row[1]
    except Exception as exc:
        logger.warning("Could not load tokens from database: %s", exc)
    return None


def _save_tokens_to_db(access_token: str, refresh_token: str) -> None:
    """Upsert QuickBooks OAuth tokens into the database."""
    engine = _get_db_engine()
    if engine is None:
        logger.warning(
            "DATABASE_URL not set — rotated tokens will not be persisted."
        )
        return
    try:
        _ensure_table(engine)
        from sqlalchemy import text
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO oauth_tokens (service, access_token, refresh_token, updated_at)
                    VALUES (:svc, :at, :rt, NOW())
                    ON CONFLICT (service) DO UPDATE
                        SET access_token  = EXCLUDED.access_token,
                            refresh_token = EXCLUDED.refresh_token,
                            updated_at    = EXCLUDED.updated_at
                    """
                ),
                {"svc": "quickbooks", "at": access_token, "rt": refresh_token},
            )
        logger.info("✓ Persisted rotated OAuth tokens to database")
    except Exception as exc:
        logger.warning("Could not save tokens to database: %s", exc)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class Settings:
    output_dir: Path = Path(os.getenv("OUTPUT_DIR", str(ROOT / "output"))).expanduser().resolve()
    use_stub_data: bool = _bool("USE_STUB_DATA", False)

    client_id: str = os.getenv("QUICKBOOKS_CLIENT_ID", "")
    client_secret: str = os.getenv("QUICKBOOKS_CLIENT_SECRET", "")
    redirect_uri: str = os.getenv("QUICKBOOKS_REDIRECT_URI", "https://localhost:8080/callback")
    realm_id: str = os.getenv("QUICKBOOKS_REALM_ID", "")
    environment: str = os.getenv("QUICKBOOKS_ENVIRONMENT", "production")

    def __init__(self) -> None:
        # Start with whatever Railway (or .env) injected into the environment.
        self.access_token: str = os.getenv("QUICKBOOKS_ACCESS_TOKEN", "")
        self.refresh_token: str = os.getenv("QUICKBOOKS_REFRESH_TOKEN", "")

        # Prefer database tokens — they are always more recent than the static
        # environment variables because save_oauth_tokens() writes there after
        # every successful token rotation.
        db_tokens = _load_tokens_from_db()
        if db_tokens:
            db_access, db_refresh = db_tokens
            self.access_token = db_access
            self.refresh_token = db_refresh
            logger.info("Loaded QuickBooks OAuth tokens from database")
        else:
            logger.info(
                "No database tokens found; using environment variable tokens as fallback"
            )

    @property
    def api_base_url(self) -> str:
        return "https://quickbooks.api.intuit.com"

    def save_oauth_tokens(self, access_token: str, refresh_token: str) -> None:
        """Persist updated QuickBooks OAuth tokens to the database and update
        the in-process settings so the current run uses the new tokens."""
        _save_tokens_to_db(access_token, refresh_token)
        os.environ["QUICKBOOKS_ACCESS_TOKEN"] = access_token
        os.environ["QUICKBOOKS_REFRESH_TOKEN"] = refresh_token
        self.access_token = access_token
        self.refresh_token = refresh_token

    def datasets(self) -> list[dict]:
        path = ROOT / "config" / "datasets.yaml"
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("datasets", [])


settings = Settings()
