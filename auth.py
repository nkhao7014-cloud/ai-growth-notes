"""Single-user session authentication, CSRF, and login throttling."""
from __future__ import annotations

import os
import secrets
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlencode, urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pwdlib import PasswordHash
from starlette.middleware.base import BaseHTTPMiddleware

password_hash = PasswordHash.recommended()
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
PUBLIC_PATHS = {"/login", "/health", "/favicon.ico"}
_attempts: dict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def is_production() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() == "production"


def validate_settings() -> None:
    required = ("APP_USERNAME", "APP_PASSWORD_HASH", "SESSION_SECRET", "DATABASE_URL")
    missing = [name for name in required if not os.getenv(name, "").strip()]
    if missing:
        raise RuntimeError("Missing required environment variables: " + ", ".join(missing))
    if len(os.environ["SESSION_SECRET"]) < 32:
        raise RuntimeError("SESSION_SECRET must contain at least 32 characters")


def safe_next(value: str | None) -> str:
    if not value:
        return "/"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    return value


def ensure_csrf(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def verify_csrf(request: Request, supplied: str | None) -> None:
    expected = request.session.get("csrf_token", "")
    if not expected or not supplied or not secrets.compare_digest(expected, supplied):
        raise HTTPException(status_code=403, detail="CSRF validation failed")


def login_allowed(key: str) -> bool:
    now = time.monotonic()
    with _lock:
        values = _attempts[key]
        while values and values[0] < now - 300:
            values.popleft()
        return len(values) < 5


def record_failure(key: str) -> None:
    with _lock:
        _attempts[key].append(time.monotonic())


def clear_failures(key: str) -> None:
    with _lock:
        _attempts.pop(key, None)


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        public = path in PUBLIC_PATHS or path.startswith("/static/")
        authenticated = request.session.get("authenticated") is True
        if not public and not authenticated:
            if path.startswith("/api/"):
                return JSONResponse({"detail": "Authentication required"}, status_code=401)
            target = safe_next(path + (("?" + request.url.query) if request.url.query else ""))
            return RedirectResponse("/login?" + urlencode({"next": target}), status_code=303)
        if authenticated and request.method not in SAFE_METHODS:
            supplied = request.headers.get("X-CSRF-Token")
            if request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
                form = await request.form()
                supplied = str(form.get("csrf_token", ""))
            try:
                verify_csrf(request, supplied)
            except HTTPException as exc:
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        response = await call_next(request)
        token = ensure_csrf(request)
        response.set_cookie("agn_csrf", token, max_age=int(os.getenv("SESSION_MAX_AGE", "604800")),
                            secure=is_production(),
                            httponly=False, samesite="lax", path="/")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if authenticated:
            response.headers["Cache-Control"] = "no-store"
        if is_production():
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
