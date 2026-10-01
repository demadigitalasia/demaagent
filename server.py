"""Mission Control — APLIKASI MANDIRI (server FastAPI + frontend React standalone).

Server sendiri di port 9120, auth sendiri (session cookie HttpOnly),
menyajikan frontend React buatan Vite (dist/) — TANPA ketergantungan pada
dashboard Hermes :9119.

Backend REUSE data layer plugin yang sudah ada:
``/opt/data/plugins/mission-control/dashboard/plugin_api.py`` — router-nya
di-import (importlib, path absolut) dan di-mount di prefix ``/api``.
TIDAK ada logika data yang disalin; semua endpoint data (overview, agents,
tasks, calendar, activity, memory, office) adalah router plugin asli.

FASE 4 runtime identity:
  - `/api/*` remains the owner control plane behind `mc_session`.
  - `/runtime-api/*` is a separate bearer-only router using verified,
    short-lived HMAC service tokens scoped to one knowledge-capable agent.
    No runtime route trusts an agent id from a URL.

Auth:
  - POST /auth/login     : {username, password} -> validasi terhadap env
                           HERMES_DASHBOARD_BASIC_AUTH_USERNAME/PASSWORD
                           (kredensial sama dengan dashboard Hermes, dibaca
                           dari os.environ saat runtime, tidak pernah dicetak)
  - session token acak; hanya hash session/CSRF yang disimpan pada SQLite lokal, expiry 12 jam
  - cookie mc_session HttpOnly SameSite=Lax Secure path=/ ; logout via POST /auth/logout
  - cookie mc_csrf SameSite=Lax Secure path=/ (non-HttpOnly, session-bound)
  - mutating cookie-authenticated /api/* and /auth/logout requests require X-CSRF-Token
  - SEMUA /api/* dilindungi require_session kecuali /auth/login & /healthz
  - unauthorized -> 401 JSON {"error": "unauthorized"}; CSRF failure -> 403 {"error":"csrf_failed"}
  - throttle login gagal: 10 gagal / 60 dtk per IP -> 429

Frontend:
  - GET /            -> dist/index.html
  - GET /assets/*    -> file static dist/assets (StaticFiles)
  - path lain        -> SPA fallback ke index.html
  - GET /healthz     -> publik {"status": "ok"}

Jalankan (lihat README.md):
  cd /opt/data/mission-control && nohup /opt/hermes/.venv/bin/python -m uvicorn \
      server:app --host 0.0.0.0 --port 9120 >> /opt/data/logs/mission-control.log 2>&1 &
"""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR / "dist"
AUTH_STATE_DB_PATH = Path(
    os.environ.get("MISSION_CONTROL_AUTH_STATE_DB", str(BASE_DIR / "auth_state.db"))
)
PLUGIN_API_PATH = Path("/opt/data/plugins/mission-control/dashboard/plugin_api.py")

SESSION_TTL_S = 12 * 3600          # sesi 12 jam
LOGIN_FAIL_MAX = 10                # throttle: maksimal gagal per jendela
LOGIN_FAIL_WINDOW_S = 60
COOKIE_NAME = "mc_session"
CSRF_COOKIE_NAME = "mc_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

log = logging.getLogger("mission-control-standalone")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Mission Control Standalone", version="1.0.0")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Header keamanan minimum untuk aplikasi web pribadi."""
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Strict-Transport-Security"] = "max-age=31536000"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    )
    # Strategi cache: index.html & SPA fallback = selalu revalidasi;
    # aset ber-hash (assets/*) = immutable 1 tahun (anti-cache-stale seperti yang dialami user).
    path = request.url.path
    if path.startswith("/assets/"):
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        resp.headers["Cache-Control"] = "no-cache"
    return resp

# ---------------------------------------------------------------------------
# REUSE data layer: import router plugin asli (tanpa duplikasi logika).
# plugin_api.py hanya butuh fastapi + stdlib -> aman di-import berdiri sendiri.
# ---------------------------------------------------------------------------
_spec = importlib.util.spec_from_file_location("mission_control_plugin_api", PLUGIN_API_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"plugin_api.py tidak bisa dimuat: {PLUGIN_API_PATH}")
_plugin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_plugin)
router = _plugin.router
log.info("data layer plugin di-import: %s (%d route)",
         PLUGIN_API_PATH, len(router.routes))

# ---------------------------------------------------------------------------
# Sesi durable: hash token -> metadata sesi; CSRF hash -> session hash
# ---------------------------------------------------------------------------
_sessions: dict[str, float] = {}
_session_csrf_tokens: dict[str, str] = {}
_lock = threading.Lock()
_auth_state_init_lock = threading.Lock()
_auth_state_ready = False
_login_fails: dict[str, list[float]] = {}


_AUTH_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS owner_sessions (
    session_hash TEXT PRIMARY KEY,
    csrf_hash TEXT NOT NULL,
    expires_at REAL NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS owner_sessions_expires_idx
    ON owner_sessions (expires_at);
CREATE TABLE IF NOT EXISTS runtime_token_revocations (
    token_id TEXT PRIMARY KEY, -- tagged SHA-256(token_id), never the raw JTI
    expires_at REAL NOT NULL,
    revoked_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS runtime_token_revocations_expires_idx
    ON runtime_token_revocations (expires_at);
"""


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ensure_auth_state_db() -> None:
    global _auth_state_ready
    if _auth_state_ready:
        return
    with _auth_state_init_lock:
        if _auth_state_ready:
            return
        path = AUTH_STATE_DB_PATH
        if path.exists() and (path.is_symlink() or not path.is_file()):
            raise RuntimeError(f"auth state path is not a regular file: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(path), timeout=5)
        try:
            connection.execute("PRAGMA busy_timeout=5000")
            connection.executescript(_AUTH_STATE_SCHEMA)
            connection.commit()
        finally:
            connection.close()
        os.chmod(path, 0o600)
        _auth_state_ready = True


def _auth_state_connect() -> sqlite3.Connection:
    _ensure_auth_state_db()
    connection = sqlite3.connect(str(AUTH_STATE_DB_PATH), timeout=5)
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


class UnauthorizedError(Exception):
    pass


class CsrfError(Exception):
    pass


@app.exception_handler(UnauthorizedError)
async def _unauthorized_handler(request: Request, exc: UnauthorizedError):
    return JSONResponse(status_code=401, content={"error": "unauthorized"})


@app.exception_handler(CsrfError)
async def _csrf_handler(request: Request, exc: CsrfError):
    return JSONResponse(status_code=403, content={"error": "csrf_failed"})


def _prune_sessions() -> None:
    now = time.time()
    connection = _auth_state_connect()
    try:
        connection.execute("DELETE FROM owner_sessions WHERE expires_at <= ?", (now,))
        connection.commit()
    finally:
        connection.close()
    expired = [t for t, exp in _sessions.items() if exp <= now]
    for t in expired:
        _sessions.pop(t, None)
        _session_csrf_tokens.pop(t, None)


def _require_csrf(request: Request) -> None:
    if request.method.upper() not in UNSAFE_METHODS:
        return
    session_token = request.cookies.get(COOKIE_NAME)
    supplied = request.headers.get(CSRF_HEADER_NAME)
    if not session_token or not supplied:
        raise CsrfError()
    connection = _auth_state_connect()
    try:
        row = connection.execute(
            "SELECT csrf_hash FROM owner_sessions WHERE session_hash = ? AND expires_at > ?",
            (_token_hash(session_token), time.time()),
        ).fetchone()
    finally:
        connection.close()
    if row is None or not secrets.compare_digest(_token_hash(supplied), row[0]):
        raise CsrfError()


def _valid_credentials(username: str, password: str) -> bool:
    env_user = os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_USERNAME", "")
    env_pass = os.environ.get("HERMES_DASHBOARD_BASIC_AUTH_PASSWORD", "")
    if not env_user or not env_pass:
        log.error("HERMES_DASHBOARD_BASIC_AUTH_USERNAME/PASSWORD tidak ada di env — login tidak mungkin")
        return False
    return (secrets.compare_digest(username, env_user)
            and secrets.compare_digest(password, env_pass))


def require_session(request: Request) -> None:
    """Dependency: semua /api/* kecuali login/healthz wajib punya sesi valid."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise UnauthorizedError()
    with _lock:
        _prune_sessions()
        connection = _auth_state_connect()
        try:
            row = connection.execute(
                "SELECT expires_at FROM owner_sessions WHERE session_hash = ? AND expires_at > ?",
                (_token_hash(token), time.time()),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise UnauthorizedError()
        _sessions[token] = float(row[0])


def _require_owner_request(request: Request) -> None:
    require_session(request)
    _require_csrf(request)


_ensure_auth_state_db()


# ---------------------------------------------------------------------------
# Auth endpoints (publik)
# ---------------------------------------------------------------------------
@app.post("/auth/login")
def login(request: Request, payload: dict) -> JSONResponse:
    username = str(payload.get("username") or "")
    password = str(payload.get("password") or "")
    if not _valid_credentials(username, password):
        # throttle: catat kegagalan per IP
        ip = request.client.host if request.client else "?"
        now = time.time()
        with _lock:
            fails = [t for t in _login_fails.get(ip, []) if now - t < LOGIN_FAIL_WINDOW_S]
            if len(fails) >= LOGIN_FAIL_MAX:
                return JSONResponse(status_code=429, content={"error": "too_many_attempts"})
            fails.append(now)
            _login_fails[ip] = fails
        raise UnauthorizedError()

    with _lock:
        _prune_sessions()
        token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        expires_at = time.time() + SESSION_TTL_S
        connection = _auth_state_connect()
        try:
            connection.execute(
                "INSERT INTO owner_sessions(session_hash, csrf_hash, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (_token_hash(token), _token_hash(csrf_token), expires_at, time.time()),
            )
            connection.commit()
        finally:
            connection.close()
        _sessions[token] = expires_at
        _session_csrf_tokens[token] = csrf_token
    resp = JSONResponse({"status": "ok", "expires_in_s": SESSION_TTL_S})
    resp.set_cookie(COOKIE_NAME, token, max_age=SESSION_TTL_S,
                    httponly=True, samesite="lax", secure=True, path="/")
    resp.set_cookie(CSRF_COOKIE_NAME, csrf_token, max_age=SESSION_TTL_S,
                    httponly=False, samesite="lax", secure=True, path="/")
    return resp


@app.post("/auth/logout")
def logout(request: Request) -> JSONResponse:
    require_session(request)
    _require_csrf(request)
    token = request.cookies.get(COOKIE_NAME)
    with _lock:
        connection = _auth_state_connect()
        try:
            connection.execute(
                "DELETE FROM owner_sessions WHERE session_hash = ?",
                (_token_hash(token or ""),),
            )
            connection.commit()
        finally:
            connection.close()
        _sessions.pop(token or "", None)
        _session_csrf_tokens.pop(token or "", None)
    resp = JSONResponse({"status": "ok"})
    resp.delete_cookie(COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax")
    resp.delete_cookie(CSRF_COOKIE_NAME, path="/", secure=True, httponly=False, samesite="lax")
    return resp


@app.get("/auth/session")
def session_info(request: Request) -> JSONResponse:
    """Sisa waktu sesi aktif (untuk indikator di UI). Wajib sesi valid."""
    try:
        require_session(request)
    except UnauthorizedError:
        return JSONResponse(status_code=401, content={"status": "error", "message": "unauthorized"})
    token = request.cookies.get(COOKIE_NAME)
    with _lock:
        _prune_sessions()
        connection = _auth_state_connect()
        try:
            row = connection.execute(
                "SELECT expires_at FROM owner_sessions WHERE session_hash = ? AND expires_at > ?",
                (_token_hash(token or ""), time.time()),
            ).fetchone()
        finally:
            connection.close()
    expires = float(row[0]) if row is not None else 0.0
    return JSONResponse({"status": "ok", "expires_in_s": max(0, int(expires - time.time()))})


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# API data — mount router plugin asli di /api (semua dilindungi session)
# ---------------------------------------------------------------------------
app.include_router(router, prefix="/api", dependencies=[Depends(_require_owner_request)])

# Runtime agent API — deliberately separate from mc_session owner control plane.
app.include_router(_plugin.runtime_router, prefix="/runtime-api")


# ---------------------------------------------------------------------------
# Frontend (dist/ dari build Vite)
# ---------------------------------------------------------------------------
if DIST_DIR.is_dir() and (DIST_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")


@app.get("/", include_in_schema=False, response_model=None)
def index() -> FileResponse | JSONResponse:
    target = DIST_DIR / "index.html"
    if target.is_file():
        return FileResponse(target)
    return JSONResponse(status_code=503, content={"status": "degraded",
                                                  "error": "frontend belum di-build (dist/index.html tidak ada)"})


@app.get("/{full_path:path}", include_in_schema=False, response_model=None)
def spa_fallback(full_path: str) -> FileResponse | JSONResponse:
    # path API yang tidak dikenal -> 404 JSON, jangan diserap SPA
    if full_path.startswith("api/") or full_path.startswith("runtime-api/"):
        return JSONResponse(status_code=404, content={"error": "not found"})
    candidate = DIST_DIR / full_path
    if full_path and candidate.is_file():
        return FileResponse(candidate)
    target = DIST_DIR / "index.html"
    if target.is_file():
        return FileResponse(target)
    return JSONResponse(status_code=503, content={"status": "degraded",
                                                  "error": "frontend belum di-build"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9120)