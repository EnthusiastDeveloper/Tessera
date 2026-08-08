"""Integration tests for app.auth.service against a real (in-memory) SQLite DB.

See design doc §3.6, architecture-plan §6, §6.2. Uses the `db_session` fixture from
`tests/integration/conftest.py`. `setup_token_store`/`login_throttle` are process-global
singletons (by design - see their modules), so each test resets them explicitly rather
than relying on import-time state.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.auth import service
from app.auth.passwords import verify_password
from app.auth.setup_token import setup_token_store
from app.auth.throttle import MAX_ATTEMPTS, login_throttle
from app.db.base import generate_id, utcnow
from app.db.repositories import SessionRepository, UserRepository
from app.db.schemas import User, UserSession


@pytest.fixture(autouse=True)
def _reset_singletons() -> None:
    setup_token_store.invalidate()
    login_throttle.clear_all()


def _issue_and_get_token() -> str:
    return setup_token_store.issue()


def _create_user(db_session: Session, *, username: str = "admin", password_hash: str = "x") -> User:
    return UserRepository(db_session).create(
        User(id=generate_id(), username=username, password_hash=password_hash, created_at=utcnow())
    )


def _create_session(db_session: Session, *, user_id: str, expires_at: datetime | None = None) -> UserSession:
    now = utcnow()
    return SessionRepository(db_session).create(
        UserSession(
            id=generate_id(),
            user_id=user_id,
            created_at=now,
            expires_at=expires_at if expires_at is not None else now + timedelta(days=1),
        )
    )


class TestSetup:
    def test_creates_the_admin_user(self, db_session: Session) -> None:
        token = _issue_and_get_token()
        user = service.setup(db_session, token=token, password="correcthorsebatterystaple")
        assert user.username == "admin"
        assert UserRepository(db_session).count() == 1

    def test_invalidates_the_token_on_success(self, db_session: Session) -> None:
        token = _issue_and_get_token()
        service.setup(db_session, token=token, password="correcthorsebatterystaple")
        assert setup_token_store.is_active is False

    def test_rejects_when_already_configured(self, db_session: Session) -> None:
        token = _issue_and_get_token()
        service.setup(db_session, token=token, password="correcthorsebatterystaple")
        with pytest.raises(service.SetupError) as exc_info:
            service.setup(db_session, token=_issue_and_get_token(), password="correcthorsebatterystaple")
        assert exc_info.value.code == "already_configured"

    def test_rejects_wrong_token(self, db_session: Session) -> None:
        _issue_and_get_token()
        with pytest.raises(service.SetupError) as exc_info:
            service.setup(db_session, token="wrong-token", password="correcthorsebatterystaple")
        assert exc_info.value.code == "invalid_setup_token"

    def test_rejects_short_password(self, db_session: Session) -> None:
        token = _issue_and_get_token()
        with pytest.raises(service.SetupError) as exc_info:
            service.setup(db_session, token=token, password="short")
        assert exc_info.value.code == "password_too_short"


class TestLogin:
    def _create_admin(self, db_session: Session, password: str = "correcthorsebatterystaple") -> None:
        token = _issue_and_get_token()
        service.setup(db_session, token=token, password=password)

    def test_correct_credentials_issue_a_session(self, db_session: Session) -> None:
        self._create_admin(db_session)
        user, user_session = service.login(db_session, username="admin", password="correcthorsebatterystaple", throttle_key="k")
        assert user.username == "admin"
        assert user_session.user_id == user.id
        assert SessionRepository(db_session).get(user_session.id) is not None

    def test_wrong_password_is_rejected(self, db_session: Session) -> None:
        self._create_admin(db_session)
        with pytest.raises(service.AuthError) as exc_info:
            service.login(db_session, username="admin", password="wrong", throttle_key="k")
        assert exc_info.value.code == "invalid_credentials"

    def test_unknown_username_is_rejected(self, db_session: Session) -> None:
        with pytest.raises(service.AuthError) as exc_info:
            service.login(db_session, username="nobody", password="whatever12345", throttle_key="k")
        assert exc_info.value.code == "invalid_credentials"

    def test_throttle_locks_out_after_max_attempts(self, db_session: Session) -> None:
        self._create_admin(db_session)
        for _ in range(MAX_ATTEMPTS):
            with pytest.raises(service.AuthError):
                service.login(db_session, username="admin", password="wrong", throttle_key="k")
        with pytest.raises(service.AuthError) as exc_info:
            service.login(db_session, username="admin", password="correcthorsebatterystaple", throttle_key="k")
        assert exc_info.value.code == "too_many_attempts"

    def test_successful_login_resets_the_throttle(self, db_session: Session) -> None:
        self._create_admin(db_session)
        with pytest.raises(service.AuthError):
            service.login(db_session, username="admin", password="wrong", throttle_key="k")
        service.login(db_session, username="admin", password="correcthorsebatterystaple", throttle_key="k")
        # a fresh failure right after a successful login should report a plain wrong-password
        # error, not a lockout - the earlier failure must have been cleared.
        with pytest.raises(service.AuthError) as exc_info:
            service.login(db_session, username="admin", password="wrong", throttle_key="k")
        assert exc_info.value.code == "invalid_credentials"

    def test_rotates_session_id_on_each_login(self, db_session: Session) -> None:
        self._create_admin(db_session)
        _, first_session = service.login(db_session, username="admin", password="correcthorsebatterystaple", throttle_key="k1")
        _, second_session = service.login(db_session, username="admin", password="correcthorsebatterystaple", throttle_key="k2")
        assert first_session.id != second_session.id


class TestLogoutAndValidateSession:
    def test_logout_deletes_the_session(self, db_session: Session) -> None:
        user = _create_user(db_session)
        created = _create_session(db_session, user_id=user.id)
        service.logout(db_session, session_id=created.id)
        assert SessionRepository(db_session).get(created.id) is None

    def test_logout_is_idempotent_for_an_unknown_session(self, db_session: Session) -> None:
        service.logout(db_session, session_id="does-not-exist")  # must not raise

    def test_validate_session_returns_the_user_for_a_live_session(self, db_session: Session) -> None:
        token = _issue_and_get_token()
        user = service.setup(db_session, token=token, password="correcthorsebatterystaple")
        _, user_session = service.login(db_session, username="admin", password="correcthorsebatterystaple", throttle_key="k")
        validated = service.validate_session(db_session, session_id=user_session.id)
        assert validated is not None
        assert validated.id == user.id

    def test_validate_session_returns_none_for_an_expired_session(self, db_session: Session) -> None:
        user = _create_user(db_session)
        expired = _create_session(db_session, user_id=user.id, expires_at=utcnow() - timedelta(days=1))
        assert service.validate_session(db_session, session_id=expired.id) is None
        # not deleted by validate_session - cleanup only happens at login (§6.2)
        assert SessionRepository(db_session).get(expired.id) is not None

    def test_validate_session_returns_none_for_unknown_session(self, db_session: Session) -> None:
        assert service.validate_session(db_session, session_id="does-not-exist") is None


class TestResetAdminPassword:
    def test_no_op_when_value_is_empty(self, db_session: Session) -> None:
        service.apply_reset_admin_password_if_needed(db_session, reset_value=None)
        service.apply_reset_admin_password_if_needed(db_session, reset_value="")

    def test_no_op_when_no_admin_account_exists_yet(self, db_session: Session) -> None:
        service.apply_reset_admin_password_if_needed(db_session, reset_value="new-password-123")
        assert UserRepository(db_session).count() == 0

    def test_first_restart_resets_the_password_and_revokes_sessions(self, db_session: Session) -> None:
        token = _issue_and_get_token()
        user = service.setup(db_session, token=token, password="original-password-123")
        _, session_a = service.login(db_session, username="admin", password="original-password-123", throttle_key="k")

        service.apply_reset_admin_password_if_needed(db_session, reset_value="new-password-456")

        refreshed = UserRepository(db_session).get(user.id)
        assert refreshed is not None
        assert verify_password("new-password-456", refreshed.password_hash)
        assert SessionRepository(db_session).get(session_a.id) is None  # revoked

    def test_second_consecutive_restart_with_same_value_does_not_reset_again(self, db_session: Session) -> None:
        token = _issue_and_get_token()
        service.setup(db_session, token=token, password="original-password-123")
        service.apply_reset_admin_password_if_needed(db_session, reset_value="new-password-456")

        user_after_first = UserRepository(db_session).get_by_username("admin")
        assert user_after_first is not None

        # "restart 2": same env var value still present
        service.apply_reset_admin_password_if_needed(db_session, reset_value="new-password-456")

        user_after_second = UserRepository(db_session).get_by_username("admin")
        assert user_after_second is not None
        assert user_after_second.password_hash == user_after_first.password_hash

    def test_third_restart_with_a_changed_value_resets_again(self, db_session: Session) -> None:
        token = _issue_and_get_token()
        service.setup(db_session, token=token, password="original-password-123")
        service.apply_reset_admin_password_if_needed(db_session, reset_value="new-password-456")
        user_after_first = UserRepository(db_session).get_by_username("admin")
        assert user_after_first is not None

        # "restart 3": a genuinely new value
        service.apply_reset_admin_password_if_needed(db_session, reset_value="yet-another-password-789")

        user_after_third = UserRepository(db_session).get_by_username("admin")
        assert user_after_third is not None
        assert user_after_third.password_hash != user_after_first.password_hash
        assert verify_password("yet-another-password-789", user_after_third.password_hash)
