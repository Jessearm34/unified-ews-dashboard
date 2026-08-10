"""Diagnostic logging — runs at startup, logs everything needed to debug deployment issues."""

from __future__ import annotations

import logging
import os
import socket
import sys
import time
from datetime import datetime, timezone

log = logging.getLogger("ewsd.diag")


def redact(s: str) -> str:
    """Redact passwords/tokens in a connection string for safe logging."""
    if not s or len(s) < 10:
        return "***"
    # Replace password in postgresql://user:pass@host
    import re
    return re.sub(r'://[^:]+:([^@]+)@', r'://***:***@', s)


def run_startup_diagnostics() -> dict:
    """Run all startup checks and log results. Returns dict for /health response."""
    results = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "checks": {},
    }

    # 1. Required env vars
    env_checks = {}
    critical_vars = ["SESSION_SECRET", "DATABASE_URL", "QB_DATABASE_URL", "SD_DATABASE_URL"]
    for var in critical_vars:
        val = os.getenv(var)
        if val:
            env_checks[var] = "ok"
        else:
            env_checks[var] = "MISSING"
            log.warning("ENV CHECK: %s is not set", var)

    optional_vars = ["GT_DATABASE_URL", "SD_API_KEY", "GT_USERNAME", "INSPERITY_API_KEY"]
    for var in optional_vars:
        val = os.getenv(var)
        env_checks[var] = "ok" if val else "not set"
        if not val:
            log.info("ENV CHECK: %s not set (optional)", var)

    results["checks"]["env"] = env_checks

    # 2. Database URL format check
    db_url = os.getenv("DATABASE_URL", "")
    if db_url:
        log.info("DATABASE_URL: %s", redact(db_url))
        if "host" in db_url.split("@")[-1].split("/")[0] and "reseau" not in db_url:
            log.warning("DATABASE_URL contains placeholder 'host' — this will fail to connect")

    qb_url = os.getenv("QB_DATABASE_URL", "")
    if qb_url:
        log.info("QB_DATABASE_URL: %s", redact(qb_url))
    else:
        log.warning("QB_DATABASE_URL not set — QuickBooks section will be empty")

    sd_url = os.getenv("SD_DATABASE_URL", "")
    if sd_url:
        log.info("SD_DATABASE_URL: %s", redact(sd_url))

    # 3. Port binding
    port = os.getenv("PORT", "8000")
    log.info("PORT=%s — app will bind to 0.0.0.0:%s", port, port)
    results["checks"]["port"] = port

    # 4. Network interface check
    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        log.info("Hostname: %s, IP: %s", hostname, ip)
        results["checks"]["network"] = {"hostname": hostname, "ip": ip}
    except Exception as e:
        log.warning("Could not resolve hostname: %s", e)
        results["checks"]["network"] = {"error": str(e)}

    # 5. Try resolving DB hostnames
    for label, url in [("DATABASE_URL", db_url), ("QB", qb_url), ("SD", sd_url)]:
        if not url:
            continue
        try:
            # Extract hostname from postgresql://user:pass@host:port/db
            host_part = url.split("@")[-1].split("/")[0].split(":")[0] if "@" in url else ""
            if host_part and host_part not in ("localhost", "127.0.0.1", "host"):
                try:
                    socket.gethostbyname(host_part)
                    log.info("DB reachability check: %s (%s) — resolvable", label, host_part)
                except socket.gaierror:
                    log.warning("DB reachability check: %s (%s) — UNRESOLVABLE", label, host_part)
        except Exception:
            pass

    # 6. Python packages check
    packages = {}
    for pkg in ["fastapi", "uvicorn", "pandas", "plotly", "sqlalchemy", "psycopg2", "gunicorn"]:
        try:
            mod = __import__(pkg)
            version = getattr(mod, "__version__", "unknown")
            packages[pkg] = version
        except ImportError:
            packages[pkg] = "NOT INSTALLED"
            log.error("PACKAGE CHECK: %s is not installed", pkg)
    results["checks"]["packages"] = packages

    log.info("Startup diagnostics complete. %d checks run.", len(results["checks"]))
    return results
