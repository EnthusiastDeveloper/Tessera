"""Default-deny auth guard. See design doc §14.2, architecture-plan §6.3.

Middleware with an explicit public-route allowlist, not per-endpoint auth dependencies:
a route added later is protected unless someone deliberately exempts it, rather than
silently published because someone forgot a `Depends(...)`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.auth.cookie_signing import unsign
from app.auth.service import validate_session
from app.auth.setup_token import setup_token_store
from app.core.config import get_settings
from app.db.session import session_scope

SESSION_COOKIE_NAME = "tessera_session"

# See design doc §14.2 for the exhaustive rationale behind each entry. Static assets and
# SPA client routes (any GET outside /api/) are handled separately below - there are
# infinitely many of them (hashed asset filenames, arbitrary client routes), so they
# can't live in a fixed allowlist. They're served publicly; the SPA enforces auth itself
# by calling the (still fully guarded) API on load, per AuthContext's setup_required /
# unauthenticated / authenticated states.
PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/health"),
        ("POST", "/api/v1/auth/setup"),
        ("POST", "/api/v1/auth/login"),
    }
)

# Reachable while zero `User` rows exist (design doc §8.1 screen 0). Deliberately a strict
# subset of PUBLIC_ROUTES: login must NOT work pre-setup, since there is no account to log
# into yet. This is what makes "every other screen redirects to setup until one exists" a
# backend guarantee the frontend can rely on for *every* route (including its own session
# check on load), rather than something the SPA has to infer from a generic 401.
SETUP_ALLOWED_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/health"),
        ("POST", "/api/v1/auth/setup"),
    }
)


def _is_frontend_request(method: str, path: str) -> bool:
    """True for a same-origin static asset or SPA client route - never for `/api/...`
    or `/health`, and never for anything but a read.
    """
    return method in ("GET", "HEAD") and path != "/health" and not path.startswith("/api/")


class AuthGuardMiddleware(BaseHTTPMiddleware):
    """Rejects any request outside `PUBLIC_ROUTES` that lacks a valid session cookie.

    Also rejects, with a distinct `setup_required` code, any request outside
    `SETUP_ALLOWED_ROUTES` while first-run setup hasn't happened yet. Frontend static/SPA
    requests bypass both checks - see `_is_frontend_request`.
    """

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        path_key = (request.method, request.url.path)

        if _is_frontend_request(*path_key):
            return await call_next(request)

        if setup_token_store.is_active and path_key not in SETUP_ALLOWED_ROUTES:
            return _setup_required()

        if path_key in PUBLIC_ROUTES:
            return await call_next(request)

        cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
        session_id: str | None = None
        if cookie_value:
            session_id = unsign(cookie_value, get_settings().secret_key)
        if session_id is None:
            # A present-but-invalid cookie (bad signature, or valid signature pointing at
            # an expired/absent DB row) reports session_expired so the client redirects to
            # login; a wholly absent cookie is just "never logged in".
            return _unauthorized("session_expired" if cookie_value else "unauthenticated")

        with session_scope() as db:
            user = validate_session(db, session_id=session_id)
        if user is None:
            return _unauthorized("session_expired")

        request.state.user = user
        request.state.session_id = session_id
        return await call_next(request)


def _unauthorized(code: str) -> JSONResponse:
    return JSONResponse(status_code=401, content={"code": code, "message": "Authentication required."})


def _setup_required() -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"code": "setup_required", "message": "No account exists yet - complete first-run setup."},
    )
