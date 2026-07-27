"""Configuration — loaded once from environment."""

import os

# ── Database URLs ──
QB_DATABASE_URL = os.getenv("QB_DATABASE_URL", "")
SD_DATABASE_URL = os.getenv("SD_DATABASE_URL", "")
GT_DATABASE_URL = os.getenv("GT_DATABASE_URL", os.getenv("DATABASE_URL", ""))

# ── Auth ──
AUTH_PASSWORD = os.getenv("DASHBOARD_LOGIN_PASSWORD")
AUTH_PASSWORD_HASH = os.getenv("DASHBOARD_LOGIN_PASSWORD_HASH", "").strip()
AUTH_DOMAIN = os.getenv("DASHBOARD_LOGIN_DOMAIN", "").strip().lower()
SESSION_SECRET = os.getenv("FASTHTML_SECRET_KEY", os.getenv("SESSION_SECRET", "change-this-secret"))

# ── Server ──
PORT = int(os.getenv("PORT", "8000"))
DEBUG = os.getenv("DEBUG", "").lower() in ("1", "true", "yes")

# ── Cache ──
DATA_CACHE_TTL = int(os.getenv("DATA_CACHE_TTL", "600"))
CHART_CACHE_TTL = int(os.getenv("CHART_CACHE_TTL", "30"))