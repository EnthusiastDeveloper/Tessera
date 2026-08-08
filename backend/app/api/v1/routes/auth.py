"""Auth endpoints: setup, login, logout, me. See design doc §3.6, architecture-plan §3, §6."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.errors import AppError
from app.auth import service
from app.auth.cookie_signing import sign
from app.core.config import get_settings
from app.db.schemas import User
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

SESSION_COOKIE_NAME = "tessera_session"

_SETUP_ERROR_STATUS = {
    "already_configured": 410,
    "invalid_setup_token": 401,
    "password_too_short": 422,
}
_AUTH_ERROR_STATUS = {
    "invalid_credentials": 401,
    "too_many_attempts": 429,
}


class SetupRequest(BaseModel):
    token: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: str
    username: str


def _user_response(user: User) -> UserResponse:
    return UserResponse(id=user.id, username=user.username)


def _set_session_cookie(response: Response, session_id: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=sign(session_id, settings.secret_key),
        httponly=True,
        samesite="lax",
        secure=settings.resolve_session_cookie_secure(),
        path="/",
        max_age=int(service.SESSION_TTL.total_seconds()),
    )


@router.post("/setup", status_code=201)
def setup_endpoint(payload: SetupRequest, db: Session = Depends(get_db)) -> UserResponse:
    """Public only while zero `User` rows exist (§3.6) - `410 Gone` afterwards, enforced
    inside `service.setup`, not by the auth guard (this route is always allowlisted).
    """
    try:
        user = service.setup(db, token=payload.token, password=payload.password)
    except service.SetupError as exc:
        raise AppError(_SETUP_ERROR_STATUS[exc.code], exc.code, str(exc)) from exc
    return _user_response(user)


@router.post("/login")
def login_endpoint(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> UserResponse:
    client_host = request.client.host if request.client else "unknown"
    throttle_key = f"{client_host}:{payload.username}"
    try:
        user, user_session = service.login(db, username=payload.username, password=payload.password, throttle_key=throttle_key)
    except service.AuthError as exc:
        raise AppError(_AUTH_ERROR_STATUS[exc.code], exc.code, str(exc)) from exc
    _set_session_cookie(response, user_session.id)
    return _user_response(user)


@router.post("/logout", status_code=204)
def logout_endpoint(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    """Not in the public allowlist - reaching this handler already implies a valid session.
    Returns 204 regardless of the delete's outcome (§14.2) - logout is idempotent.
    """
    service.logout(db, session_id=request.state.session_id)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


@router.get("/me")
def me_endpoint(request: Request) -> UserResponse:
    """Who the current session belongs to - lets the frontend confirm a stored session is
    still valid on load, without needing a separate throwaway "ping" endpoint.
    """
    return _user_response(request.state.user)
