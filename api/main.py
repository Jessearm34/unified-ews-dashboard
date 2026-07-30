"""EWS Unified Dashboard — FastAPI application entry point.

Replaces the original monolithic app.py with a modular FastAPI structure.
Serves the SvelteKit SPA and exposes JSON API routes for all platforms.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from hmac import compare_digest
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from starlette.middleware.sessions import SessionMiddleware

import api.config as cfg
import api.cache as cache
from api.auth import hash_password, verify_password, email_allowed

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("ewsd")

# ---------------------------------------------------------------------------
# Lifespan (must be defined before app)
# ---------------------------------------------------------------------------

from contextlib import asynccontextmanager


def _preload_data() -> None:
    """Background preload — runs in a daemon thread after startup."""
    time.sleep(1)
    log.info("Preloading data in background…")

    for name, loader, cache_key in [
        ("QuickBooks", lambda: __import__("data.qb_data", fromlist=["qb_load_dataset"]).qb_load_dataset(), "qb"),
        ("SiteDocs", lambda: __import__("data.sd_data", fromlist=["sd_load_dataset"]).sd_load_dataset(), "sd"),
    ]:
        try:
            ds = loader()
            if ds is not None:
                cache.cached(cache_key, lambda: ds, ttl=cfg.DATA_CACHE_TTL)
                log.info("Preloaded %s data", name)
        except Exception as exc:
            log.warning("Could not preload %s data: %s", name, exc)

    try:
        eng = __import__("data.gt_data", fromlist=["gt_engine"]).gt_engine()
        if eng is not None:
            cache.cached("gt", lambda: eng, ttl=cfg.DATA_CACHE_TTL)
            log.info("Preloaded GeoTab engine")
    except Exception as exc:
        log.info("GeoTab engine not available (non-fatal): %s", exc)

    log.info("Background data preloading complete")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    log.info("EWS Unified Dashboard starting up")
    t = threading.Thread(target=_preload_data, daemon=True)
    t.start()
    yield
    log.info("EWS Unified Dashboard shutting down")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="EWS Unified Dashboard", lifespan=lifespan)

# -- CORS -------------------------------------------------------------------
_dev_origin = "http://localhost:5173"
_railway_domain = os.getenv("RAILWAY_STATIC_URL", "")
if _railway_domain and not _railway_domain.startswith("https://"):
    _railway_domain = f"https://{_railway_domain}"

_origins = [_dev_origin]
if _railway_domain:
    _origins.append(_railway_domain)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -- Sessions ----------------------------------------------------------------
app.add_middleware(SessionMiddleware, secret_key=cfg.SESSION_SECRET)

# ---------------------------------------------------------------------------
# Router imports  (mounted at no prefix — each router defines its own path)
# ---------------------------------------------------------------------------

# Overview
try:
    from api.routes.overview import router as overview_router

    app.include_router(overview_router)
    log.info("Mounted router: overview")
except ImportError:
    log.warning("Router not found: api/routes/overview.py — skipping")

# QuickBooks
try:
    from api.routes.qb import router as qb_router

    app.include_router(qb_router)
    log.info("Mounted router: qb")
except ImportError:
    log.warning("Router not found: api/routes/qb.py — skipping")

# SiteDocs
try:
    from api.routes.sd import router as sd_router

    app.include_router(sd_router)
    log.info("Mounted router: sd")
except ImportError:
    log.warning("Router not found: api/routes/sd.py — skipping")

# GeoTab
try:
    from api.routes.gt import router as gt_router

    app.include_router(gt_router)
    log.info("Mounted router: gt")
except ImportError:
    log.warning("Router not found: api/routes/gt.py — skipping")

# Insperity  (commented out — ENABLED = False in data pipeline)
# try:
#     from api.routes.insperity import router as insperity_router
#     app.include_router(insperity_router)
#     log.info("Mounted router: insperity")
# except ImportError:
#     log.warning("Router not found: api/routes/insperity.py — skipping")

# Equipt  (commented out — ENABLED = False in data pipeline)
# try:
#     from api.routes.equipt import router as equipt_router
#     app.include_router(equipt_router)
#     log.info("Mounted router: equipt")
# except ImportError:
#     log.warning("Router not found: api/routes/equipt.py — skipping")

# Admin / debug
try:
    from api.routes.admin import router as admin_router

    app.include_router(admin_router)
    log.info("Mounted router: admin")
except ImportError:
    log.debug("Router not found: api/routes/admin.py — skipping")

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Login  (GET renders form, POST authenticates)
# ---------------------------------------------------------------------------


@app.get("/login")
async def login_get(request: Request):
    """Render the login page."""
    if request.session.get("user"):
        return RedirectResponse("/", status_code=303)

    next_url = request.query_params.get("next", "/")
    return _login_page(error=None, next_url=next_url)


@app.post("/login")
async def login_post(request: Request):
    """Authenticate user via email + password."""
    if request.session.get("user"):
        return RedirectResponse("/", status_code=303)

    form = await request.form()
    email = str((form.get("email") or "")).strip().lower()
    password = str(form.get("password") or "")
    next_url = str(form.get("next") or request.query_params.get("next", "/"))

    error: str | None = None

    # Validate email domain
    if cfg.AUTH_DOMAIN and not email.endswith(f"@{cfg.AUTH_DOMAIN}"):
        error = "Invalid email or password."
    # Validate password hash
    elif cfg.AUTH_PASSWORD_HASH:
        if not verify_password(password, cfg.AUTH_PASSWORD_HASH):
            error = "Invalid email or password."
    # Validate plain-text password
    elif cfg.AUTH_PASSWORD:
        if not compare_digest(password.encode(), cfg.AUTH_PASSWORD.encode()):
            error = "Invalid email or password."
    else:
        error = "No password configured."

    if not error:
        request.session["user"] = email
        return RedirectResponse(next_url, status_code=303)

    return _login_page(error=error, next_url=next_url)


def _login_page(error: str | None, next_url: str) -> HTMLResponse:
    """Return an HTML login page matching the original app.py style."""
    error_html = (
        f"""<div style="background:#fef2f2;padding:10px 14px;border-radius:8px;border:1px solid #fecaca;margin-bottom:12px;">
            <p style="color:#dc2626;font-size:13px;margin:0;">{error}</p>
        </div>"""
        if error
        else ""
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <title>Sign in — EWS Unified Dashboard</title>
    <style>
        :root {{ --navy:#0a1f33; --page:#eef2f7; --card:#fff; --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; --accent:#2563eb; --bad:#dc2626; }}
        * {{ box-sizing:border-box; }}
        body {{ margin:0; font-family:Inter,system-ui,-apple-system,sans-serif; background:var(--page); color:var(--ink); }}
        .wrap {{ max-width:400px; margin:0 auto; padding:40px 20px; }}
        .card {{ max-width:360px; margin:80px auto; background:var(--card); padding:32px; border-radius:16px; border:1px solid var(--line); }}
        .card h2 {{ margin:0 0 4px; }}
        .card .sub {{ color:var(--muted); margin:0 0 20px; }}
        .card input {{ width:100%; padding:10px; margin-bottom:10px; border:1px solid var(--line); border-radius:8px; font-size:14px; }}
        .card button {{ width:100%; padding:10px; background:var(--navy); color:#fff; border:none; border-radius:8px; font-weight:600; cursor:pointer; font-size:14px; }}
        .card button:hover {{ opacity:.9; }}
    </style>
</head>
<body>
    <div class="wrap">
        <div class="card">
            <h2>EWS Unified Dashboard</h2>
            <p class="sub">Sign in</p>
            {error_html}
            <form method="post" action="/login">
                <input type="email" name="email" placeholder="you@company.com" required/>
                <input type="password" name="password" placeholder="Password" required/>
                <input type="hidden" name="next" value="{next_url}"/>
                <button type="submit">Sign in</button>
            </form>
        </div>
    </div>
</body>
</html>"""
    return HTMLResponse(html, status_code=200 if not error else 401)


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


@app.get("/logout")
async def logout(request: Request):
    """Clear the session and redirect to login."""
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ---------------------------------------------------------------------------
# Catch-all: serve the SvelteKit SPA
# ---------------------------------------------------------------------------

_BUILD_DIR = Path(__file__).resolve().parent.parent / "static"
# Also check "build" as fallback
_BUILD_DIR_FALLBACK = Path(__file__).resolve().parent.parent / "build"

_INDEX_HTML: str | None = None

# Try to load the built index.html once
for _try_dir in (_BUILD_DIR, _BUILD_DIR_FALLBACK):
    if _try_dir.is_dir():
        _index_path = _try_dir / "index.html"
        if _index_path.is_file():
            _INDEX_HTML = _index_path.read_text(encoding="utf-8")
            _BUILD_DIR = _try_dir
            log.info("SvelteKit build found at %s — serving SPA", _try_dir)
            break
        else:
            log.warning("Build directory exists but no index.html at %s", _index_path)
    else:
        log.debug("No build directory at %s", _try_dir)
if _INDEX_HTML is None:
    log.info("No SvelteKit build yet — serving fallback placeholder")


@app.get("/{path:path}", include_in_schema=False)
async def catch_all(request: Request, path: str):
    """Serve the SvelteKit SPA or a placeholder message."""
    # API routes that don't exist — return 404 JSON
    if path.startswith("_api/"):
        return JSONResponse(
            {"error": f"Route '{path}' not found"}, status_code=404
        )

    # Serve static assets (JS, CSS, favicon) from the build directory
    if path.startswith("_app/") or path in ("favicon.png", "favicon.ico"):
        file_path = _BUILD_DIR / path
        if file_path.is_file():
            return FileResponse(file_path)
        return JSONResponse(
            {"error": f"Asset '{path}' not found"}, status_code=404
        )

    if _INDEX_HTML is not None:
        return HTMLResponse(_INDEX_HTML)

    # Fallback when the SvelteKit app hasn't been built yet
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <title>EWS Unified Dashboard</title>
    <style>
        * {{ box-sizing:border-box; }}
        body {{ margin:0; font-family:Inter,system-ui,-apple-system,sans-serif;
                background:#eef2f7; color:#0f172a; display:flex; align-items:center;
                justify-content:center; min-height:100vh; }}
        .msg {{ text-align:center; }}
        .msg h1 {{ font-size:1.5rem; margin:0 0 8px; }}
        .msg p {{ color:#64748b; margin:0; }}
    </style>
</head>
<body>
    <div class="msg">
        <h1>EWS Unified Dashboard</h1>
        <p>Frontend build not yet deployed. API is running at <code>/health</code>.</p>
        <p style="margin-top:12px;font-size:13px;">
            <a href="/login" style="color:#2563eb;">Sign in</a>
            &middot;
            <a href="/health" style="color:#2563eb;">Health check</a>
        </p>
    </div>
</body>
</html>"""
    return HTMLResponse(html)


# ---------------------------------------------------------------------------
# Direct run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=cfg.PORT,
        reload=cfg.DEBUG,
    )