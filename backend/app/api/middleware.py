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
from app.core.config import get_settings
from app.db.session import session_scope

SESSION_COOKIE_NAME = "tessera_session"

# See design doc §14.2 for the exhaustive rationale behind each entry. Static assets and
# SPA client routes join this list in Stage 10, when the backend starts serving them.
PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/health"),
        ("POST", "/api/v1/auth/setup"),
        ("POST", "/api/v1/auth/login"),
    }
)


class AuthGuardMiddleware(BaseHTTPMiddleware):
    """Rejects any request outside `PUBLIC_ROUTES` that lacks a valid session cookie."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if (request.method, request.url.path) in PUBLIC_ROUTES:
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
