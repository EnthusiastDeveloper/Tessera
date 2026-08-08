"""Auth orchestration: setup, login, logout, RESET_ADMIN_PASSWORD, session validation.

See design doc §3.6, §14.2; architecture-plan §6. Framework-agnostic on purpose, like
every other service-layer module (architecture-plan §2) - the API layer translates
`SetupError`/`AuthError` into HTTP responses, this module never imports FastAPI.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from sqlalchemy.orm import Session as DBSession

from app.auth.passwords import hash_password, verify_password
from app.auth.setup_token import setup_token_store
from app.auth.throttle import login_throttle
from app.db.base import generate_id, utcnow
from app.db.repositories import AdminPasswordResetMarkerRepository, SessionRepository, UserRepository
from app.db.schemas import AdminPasswordResetMarker, User, UserSession

logger = logging.getLogger(__name__)

ADMIN_USERNAME = "admin"
MIN_PASSWORD_LENGTH = 12
SESSION_TTL = timedelta(days=30)


class SetupError(Exception):
    """Raised by `setup()`. `code` maps to the API error envelope (architecture-plan §3)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AuthError(Exception):
    """Raised by `login()`. `code` maps to the API error envelope (architecture-plan §3)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def setup(db: DBSession, *, token: str, password: str) -> User:
    """First-run account creation (§3.6). Public only while zero `User` rows exist -
    `already_configured` maps to `410 Gone` at the API layer, not a 401/403, since the
    resource is permanently gone rather than access-controlled.
    """
    user_repo = UserRepository(db)
    if user_repo.count() > 0:
        raise SetupError("already_configured", "Setup has already been completed.")
    if not setup_token_store.verify(token):
        raise SetupError("invalid_setup_token", "The setup token is missing, incorrect, or already used.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SetupError("password_too_short", f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    user = User(
        id=generate_id(),
        username=ADMIN_USERNAME,
        password_hash=hash_password(password),
        created_at=utcnow(),
    )
    created = user_repo.create(user)
    setup_token_store.invalidate()
    return created


def login(db: DBSession, *, username: str, password: str, throttle_key: str) -> tuple[User, UserSession]:
    """Verify credentials and issue a new session, rotating on every successful login (§6.2)."""
    now = utcnow()
    if login_throttle.is_locked_out(throttle_key, now=now):
        raise AuthError("too_many_attempts", "Too many failed login attempts. Try again later.")

    user = UserRepository(db).get_by_username(username)
    if user is None or not verify_password(password, user.password_hash):
        login_throttle.record_failure(throttle_key, now=now)
        raise AuthError("invalid_credentials", "Incorrect username or password.")

    login_throttle.reset(throttle_key)

    session_repo = SessionRepository(db)
    session_repo.delete_expired(now)  # lazy cleanup, swept only at login (§6.2)

    new_session = UserSession(
        id=secrets.token_urlsafe(32),
        user_id=user.id,
        created_at=now,
        expires_at=now + SESSION_TTL,
    )
    return user, session_repo.create(new_session)


def logout(db: DBSession, *, session_id: str) -> None:
    """Idempotent - always succeeds whether or not `session_id` referred to a real session."""
    SessionRepository(db).delete(session_id)


def validate_session(db: DBSession, *, session_id: str) -> User | None:
    """Look up the session and its user; `None` if missing, expired, or the user vanished.

    Does not delete expired rows - cleanup is swept lazily at login only (§6.2), not here.
    """
    user_session = SessionRepository(db).get(session_id)
    if user_session is None or user_session.expires_at <= utcnow():
        return None
    return UserRepository(db).get(user_session.user_id)


def apply_reset_admin_password_if_needed(db: DBSession, *, reset_value: str | None) -> None:
    """Startup `RESET_ADMIN_PASSWORD` check (§3.6). One-time consumption via a DB marker row -
    a marker on the container's writable layer would be erased by a recreate, turning the
    env var back into the standing backdoor this mechanism exists to prevent.
    """
    if not reset_value:
        return

    marker_repo = AdminPasswordResetMarkerRepository(db)
    value_hash = hashlib.sha256(reset_value.encode()).hexdigest()
    existing_marker = marker_repo.get()
    if existing_marker is not None and existing_marker.consumed_value_hash == value_hash:
        logger.warning(
            "RESET_ADMIN_PASSWORD is set but this value was already consumed on a prior "
            "restart - not resetting again. Remove the env var, or change its value to "
            "trigger a new reset."
        )
        return

    user_repo = UserRepository(db)
    admin = user_repo.get_by_username(ADMIN_USERNAME)
    if admin is None:
        return  # no account yet - nothing to reset; the setup wizard handles first-run

    user_repo.update(admin.model_copy(update={"password_hash": hash_password(reset_value)}))
    SessionRepository(db).delete_all_for_user(admin.id)  # mandatory on any password reset (§6.2)

    marker_repo.upsert(
        AdminPasswordResetMarker(
            id=existing_marker.id if existing_marker is not None else generate_id(),
            consumed_value_hash=value_hash,
            consumed_at=utcnow(),
        )
    )
    logger.warning("Admin password reset via RESET_ADMIN_PASSWORD. All existing sessions were revoked.")
