"""HTTP-level auth flow tests. See implementation-plan Stage 3 "Tests required",
architecture-plan §8's "Setup-token tests" and "Auth-boundary test" categories.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth.setup_token import setup_token_store
from app.auth.throttle import MAX_ATTEMPTS, login_throttle
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import build_engine, get_session_factory, sqlite_url
from app.main import app

VALID_PASSWORD = "correcthorsebatterystaple"


@contextmanager
def _booted_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **extra_env: str) -> Iterator[TestClient]:
    """Same wiring as the `app_client` fixture, but lets a test set extra env vars
    (e.g. `APP_BASE_URL`) before the app boots.
    """
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "tessera.db"))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-for-production-use")
    for key, value in extra_env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    login_throttle.clear_all()

    engine = build_engine(sqlite_url(str(tmp_path / "tessera.db")))
    Base.metadata.create_all(engine)
    engine.dispose()

    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()
    get_session_factory.cache_clear()


def _current_setup_token() -> str:
    # No public accessor by design (see SetupTokenStore) - test-only introspection.
    token = setup_token_store._token
    assert token is not None, "expected an active setup token"
    return token


def _complete_setup(client: TestClient, *, password: str = VALID_PASSWORD) -> None:
    response = client.post("/api/v1/auth/setup", json={"token": _current_setup_token(), "password": password})
    assert response.status_code == 201, response.text


class TestSetup:
    def test_missing_account_issues_an_active_token_at_startup(self, app_client: TestClient) -> None:
        assert setup_token_store.is_active is True

    def test_wrong_token_is_rejected(self, app_client: TestClient) -> None:
        response = app_client.post("/api/v1/auth/setup", json={"token": "wrong-token", "password": VALID_PASSWORD})
        assert response.status_code == 401
        assert response.json()["code"] == "invalid_setup_token"

    def test_missing_token_field_is_a_validation_error(self, app_client: TestClient) -> None:
        response = app_client.post("/api/v1/auth/setup", json={"password": VALID_PASSWORD})
        assert response.status_code == 422

    def test_successful_setup_returns_the_user_without_the_token(self, app_client: TestClient) -> None:
        response = app_client.post("/api/v1/auth/setup", json={"token": _current_setup_token(), "password": VALID_PASSWORD})
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["username"] == "admin"
        assert "token" not in body
        assert "password" not in body

    def test_already_consumed_token_is_rejected(self, app_client: TestClient) -> None:
        token = _current_setup_token()
        _complete_setup(app_client)
        response = app_client.post("/api/v1/auth/setup", json={"token": token, "password": VALID_PASSWORD})
        assert response.status_code == 410
        assert response.json()["code"] == "already_configured"

    def test_setup_after_completion_is_gone_even_with_a_fresh_valid_looking_token(self, app_client: TestClient) -> None:
        _complete_setup(app_client)
        response = app_client.post("/api/v1/auth/setup", json={"token": "anything-at-all", "password": VALID_PASSWORD})
        assert response.status_code == 410

    def test_restart_before_setup_issues_a_different_token(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        with _booted_client(tmp_path, monkeypatch):
            first_token = _current_setup_token()
        with _booted_client(tmp_path, monkeypatch):
            second_token = _current_setup_token()
        assert first_token != second_token


class TestLogin:
    def test_wrong_password_is_rejected(self, app_client: TestClient) -> None:
        _complete_setup(app_client)
        response = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
        assert response.status_code == 401
        assert response.json()["code"] == "invalid_credentials"

    def test_correct_credentials_set_the_session_cookie(self, app_client: TestClient) -> None:
        _complete_setup(app_client)
        response = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": VALID_PASSWORD})
        assert response.status_code == 200, response.text

        set_cookie = response.headers.get("set-cookie")
        assert set_cookie is not None
        assert "tessera_session=" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "samesite=lax" in set_cookie.lower()
        assert "path=/" in set_cookie.lower()
        assert "max-age=2592000" in set_cookie.lower()  # 30 days, in seconds

    def test_secure_flag_absent_without_a_https_app_base_url(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        with _booted_client(tmp_path, monkeypatch) as client:
            _complete_setup(client)
            response = client.post("/api/v1/auth/login", json={"username": "admin", "password": VALID_PASSWORD})
            set_cookie = response.headers.get("set-cookie", "")
            assert "secure" not in set_cookie.lower()

    def test_secure_flag_present_with_a_https_app_base_url(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        with _booted_client(tmp_path, monkeypatch, APP_BASE_URL="https://tessera.example.com") as client:
            _complete_setup(client)
            response = client.post("/api/v1/auth/login", json={"username": "admin", "password": VALID_PASSWORD})
            set_cookie = response.headers.get("set-cookie", "")
            assert "secure" in set_cookie.lower()

    def test_throttling_triggers_after_max_attempts(self, app_client: TestClient) -> None:
        _complete_setup(app_client)
        for _ in range(MAX_ATTEMPTS):
            response = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
            assert response.status_code == 401
        locked = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": VALID_PASSWORD})
        assert locked.status_code == 429
        assert locked.json()["code"] == "too_many_attempts"

    def test_throttle_does_not_trigger_below_the_max_and_resets_on_success(self, app_client: TestClient) -> None:
        """Below the threshold, a login still evaluates credentials rather than lumping
        everything into a lockout; a subsequent success clears the count entirely
        (`test_keys_are_independent`/`test_successful_login_resets_the_throttle` cover the
        rest of this logic directly against the throttle/service, not through HTTP).
        """
        _complete_setup(app_client)
        for _ in range(MAX_ATTEMPTS - 1):
            response = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
            assert response.status_code == 401
            assert response.json()["code"] == "invalid_credentials"
        response = app_client.post("/api/v1/auth/login", json={"username": "admin", "password": VALID_PASSWORD})
        assert response.status_code == 200


class TestLogoutAndMe:
    def test_me_requires_authentication(self, app_client: TestClient) -> None:
        response = app_client.get("/api/v1/auth/me")
        assert response.status_code == 401
        assert response.json()["code"] == "unauthenticated"

    def test_me_returns_the_logged_in_user(self, app_client: TestClient) -> None:
        _complete_setup(app_client)
        app_client.post("/api/v1/auth/login", json={"username": "admin", "password": VALID_PASSWORD})
        response = app_client.get("/api/v1/auth/me")
        assert response.status_code == 200
        assert response.json()["username"] == "admin"

    def test_logout_invalidates_the_session(self, app_client: TestClient) -> None:
        _complete_setup(app_client)
        app_client.post("/api/v1/auth/login", json={"username": "admin", "password": VALID_PASSWORD})
        assert app_client.get("/api/v1/auth/me").status_code == 200

        logout_response = app_client.post("/api/v1/auth/logout")
        assert logout_response.status_code == 204

        assert app_client.get("/api/v1/auth/me").status_code == 401

    def test_logout_without_a_session_is_rejected_by_the_guard(self, app_client: TestClient) -> None:
        response = app_client.post("/api/v1/auth/logout")
        assert response.status_code == 401

    def test_tampered_cookie_is_rejected(self, app_client: TestClient) -> None:
        _complete_setup(app_client)
        app_client.post("/api/v1/auth/login", json={"username": "admin", "password": VALID_PASSWORD})
        app_client.cookies.set("tessera_session", "tampered.value")
        response = app_client.get("/api/v1/auth/me")
        assert response.status_code == 401
        assert response.json()["code"] == "session_expired"

    def test_validly_signed_cookie_for_a_revoked_session_is_rejected(self, app_client: TestClient) -> None:
        """Distinct from a tampered signature: the cookie is genuinely well-formed, it
        just no longer names a live session - e.g. logout happened from another tab.
        """
        _complete_setup(app_client)
        app_client.post("/api/v1/auth/login", json={"username": "admin", "password": VALID_PASSWORD})
        still_valid_cookie = app_client.cookies.get("tessera_session")

        app_client.post("/api/v1/auth/logout")  # deletes the DB row and clears the client cookie
        app_client.cookies.set("tessera_session", still_valid_cookie)  # simulate a second tab that still has it

        response = app_client.get("/api/v1/auth/me")
        assert response.status_code == 401
        assert response.json()["code"] == "session_expired"


def _iter_api_routes(routes: object) -> list[object]:
    """Flatten `app.routes` into plain routes with `.path`/`.methods`.

    FastAPI (as of 0.141) wraps `include_router()`'d routes in a lazy `_IncludedRouter`
    that exposes neither attribute directly - its real `APIRoute` objects live on
    `.original_router.routes`. A naive `for route in app.routes` therefore silently skips
    every route added via `include_router()`, which is every auth endpoint. Recursing
    here is what makes the coverage test below actually cover them.
    """
    flattened: list[object] = []
    for route in routes:  # type: ignore[attr-defined]
        if hasattr(route, "path") and hasattr(route, "methods"):
            flattened.append(route)
        elif hasattr(route, "original_router"):
            flattened.extend(_iter_api_routes(route.original_router.routes))
    return flattened


class TestAuthGuardCoverage:
    """See architecture-plan §6.3: every registered route is either allowlisted or guarded."""

    def test_health_is_public(self, app_client: TestClient) -> None:
        assert app_client.get("/health").status_code == 200

    def test_route_enumeration_finds_the_known_auth_endpoints(self) -> None:
        """Guards the guard test below: if FastAPI's internals change again and this
        stops finding the auth routes, that must fail loudly rather than the coverage
        test below silently checking nothing, as it once did.
        """
        found = {(m, getattr(r, "path", None)) for r in _iter_api_routes(app.routes) for m in getattr(r, "methods", ())}
        for expected in [
            ("POST", "/api/v1/auth/setup"),
            ("POST", "/api/v1/auth/login"),
            ("POST", "/api/v1/auth/logout"),
            ("GET", "/api/v1/auth/me"),
        ]:
            assert expected in found

    def test_every_non_public_route_rejects_an_unauthenticated_request(self, app_client: TestClient) -> None:
        from app.api.middleware import PUBLIC_ROUTES

        checked = 0
        for route in _iter_api_routes(app.routes):
            methods = getattr(route, "methods", None)
            path = getattr(route, "path", None)
            if not methods or path is None or "{" in path:
                continue
            for method in methods:
                if method == "HEAD" or (method, path) in PUBLIC_ROUTES:
                    continue
                response = app_client.request(method, path)
                assert response.status_code == 401, f"{method} {path} should require auth, got {response.status_code}"
                checked += 1
        assert checked >= 4, "expected all four auth endpoints (plus docs/openapi) to be checked"
