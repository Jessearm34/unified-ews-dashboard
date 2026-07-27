"""Authentication — password hashing, session login, middleware."""

from __future__ import annotations

import os
from hashlib import pbkdf2_hmac
from hmac import compare_digest
from typing import Optional

from fastapi import Request, Response
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

import api.config as cfg


def hash_password(password: str, salt: str | None = None) -> str:
    if salt is None:
        salt = os.urandom(16).hex()
    dk = pbkdf2_hmac("sha256", password.encode(), salt.encode(), 250_000)
    return f"pbkdf2_sha256${salt}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algo, salt, digest = stored_hash.split("$", 2)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    return compare_digest(hash_password(password, salt), stored_hash)


def email_allowed(email: str) -> bool:
    if not cfg.AUTH_DOMAIN or not email:
        return True
    return email.strip().lower().endswith(f"@{cfg.AUTH_DOMAIN}")


def require_login(request: Request):
    """Returns a RedirectResponse if not authenticated, else None."""
    user = request.session.get("user")
    if not user:
        next_url = str(request.url.path)
        if request.url.query:
            next_url += f"?{request.url.query}"
        return RedirectResponse(f"/login?next={next_url}", status_code=303)
    return None


class AuthMiddleware(BaseHTTPMiddleware):
    """Protect all routes except login, logout, health, and static files."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        # Public paths
        if path.startswith(("/login", "/logout", "/health", "/_api/")):
            return await call_next(request)
        # Static assets
        if path.startswith(("/_app/", "/favicon", "/static/")):
            return await call_next(request)
        # Check auth
        guard = require_login(request)
        if guard:
            return guard
        return await call_next(request)