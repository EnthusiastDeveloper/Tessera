"""HTTP-level calendar-connection tests: auth guard, the OAuth connect/callback/disconnect
wiring, and response shape. Business logic (poll/collision) is covered at the service
layer (tests/integration/calendar_sync/test_service.py) - this file only proves the routes
wire up correctly, using a mocked provider per implementation-plan §7 ("OAuth flow against
a mocked provider, never a real one in CI").
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

import app.calendar_sync.service as calendar_sync_service
from app.auth.setup_token import setup_token_store
from app.core.config import get_settings
from tests.fixtures.calendar_providers import MockCalendarProvider

VALID_PASSWORD = "correcthorsebatterystaple"


def _complete_setup(client: TestClient) -> None:
    token = setup_token_store._token  # test-only introspection, matches other API test files
    assert token is not None
    client.post("/api/v1/auth/setup", json={"token": token, "password": VALID_PASSWORD})


def _login(client: TestClient) -> None:
    _complete_setup(client)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": VALID_PASSWORD})


def _configure_app_base_url(monkeypatch: pytest.MonkeyPatch, url: str = "http://localhost:8000") -> None:
    monkeypatch.setenv("APP_BASE_URL", url)
    get_settings.cache_clear()


def _install_mock_provider(monkeypatch: pytest.MonkeyPatch) -> MockCalendarProvider:
    provider = MockCalendarProvider()
    monkeypatch.setattr(calendar_sync_service, "get_provider_client", lambda _provider, *, settings: provider)
    return provider


class TestListConnections:
    def test_requires_authentication(self, app_client: TestClient) -> None:
        _complete_setup(app_client)
        assert app_client.get("/api/v1/calendar-connections").status_code == 401

    def test_returns_empty_list_when_none_connected(self, app_client: TestClient) -> None:
        _login(app_client)
        response = app_client.get("/api/v1/calendar-connections")
        assert response.status_code == 200
        assert response.json() == []


class TestConnect:
    def test_requires_authentication(self, app_client: TestClient) -> None:
        _complete_setup(app_client)
        assert app_client.get("/api/v1/calendar-connections/google/connect").status_code == 401

    def test_requires_app_base_url(self, app_client: TestClient) -> None:
        _login(app_client)
        response = app_client.get("/api/v1/calendar-connections/google/connect")
        assert response.status_code == 400
        assert response.json()["code"] == "app_base_url_not_configured"

    def test_requires_provider_credentials(self, app_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _login(app_client)
        _configure_app_base_url(monkeypatch)
        response = app_client.get("/api/v1/calendar-connections/google/connect")
        assert response.status_code == 400
        assert response.json()["code"] == "provider_not_configured"

    def test_rejects_an_unsupported_provider(self, app_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _login(app_client)
        _configure_app_base_url(monkeypatch)
        response = app_client.get("/api/v1/calendar-connections/other/connect")
        assert response.status_code == 400
        assert response.json()["code"] == "provider_not_configured"

    def test_returns_an_authorize_url_carrying_a_state_param(
        self, app_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _login(app_client)
        _configure_app_base_url(monkeypatch)
        _install_mock_provider(monkeypatch)

        response = app_client.get("/api/v1/calendar-connections/google/connect?refresh_interval_minutes=30")
        assert response.status_code == 200
        authorize_url = response.json()["authorize_url"]
        query = parse_qs(urlparse(authorize_url).query)
        assert "state" in query
        # state is "google:<session_id>:30:<issued_at>.<signature>" - refresh_interval_minutes embedded.
        assert ":30:" in query["state"][0]


class TestCallback:
    def _authorize_url_query(self, app_client: TestClient) -> dict[str, list[str]]:
        response = app_client.get("/api/v1/calendar-connections/google/connect")
        return parse_qs(urlparse(response.json()["authorize_url"]).query)

    def test_requires_authentication(self, app_client: TestClient) -> None:
        _complete_setup(app_client)
        response = app_client.get("/api/v1/calendar-connections/google/callback?code=abc&state=x", follow_redirects=False)
        assert response.status_code == 401

    def test_rejects_an_invalid_state(self, app_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _login(app_client)
        _configure_app_base_url(monkeypatch)
        _install_mock_provider(monkeypatch)

        response = app_client.get("/api/v1/calendar-connections/google/callback?code=abc&state=forged", follow_redirects=False)
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_oauth_state"

    def test_valid_callback_creates_a_connection_and_redirects(
        self, app_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _login(app_client)
        _configure_app_base_url(monkeypatch)
        _install_mock_provider(monkeypatch)

        state = self._authorize_url_query(app_client)["state"][0]
        response = app_client.get(
            f"/api/v1/calendar-connections/google/callback?code=test-code&state={state}", follow_redirects=False
        )

        assert response.status_code in (302, 307)
        assert "calendar_connected=google" in response.headers["location"]

        connections = app_client.get("/api/v1/calendar-connections").json()
        assert len(connections) == 1
        assert connections[0]["provider"] == "google"
        assert connections[0]["enabled"] is True

    def test_state_is_single_flow_bound_to_its_own_session(self, app_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """A state minted before logout/login-again (a different session id) must not
        validate - proves the session-binding half of the CSRF protection, not just the
        signature."""
        _login(app_client)
        _configure_app_base_url(monkeypatch)
        _install_mock_provider(monkeypatch)
        state = self._authorize_url_query(app_client)["state"][0]

        app_client.post("/api/v1/auth/logout")
        # Re-login only (not `_login`'s setup step - the setup token is single-use and
        # already consumed) - rotates to a fresh session id (architecture-plan §6.2).
        app_client.post("/api/v1/auth/login", json={"username": "admin", "password": VALID_PASSWORD})

        response = app_client.get(
            f"/api/v1/calendar-connections/google/callback?code=test-code&state={state}", follow_redirects=False
        )
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_oauth_state"


class TestDisconnect:
    def test_requires_authentication(self, app_client: TestClient) -> None:
        _complete_setup(app_client)
        assert app_client.delete("/api/v1/calendar-connections/anything").status_code == 401

    def test_unknown_connection_returns_404(self, app_client: TestClient) -> None:
        _login(app_client)
        response = app_client.delete("/api/v1/calendar-connections/does-not-exist")
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"

    def test_disconnect_removes_the_connection(self, app_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _login(app_client)
        _configure_app_base_url(monkeypatch)
        _install_mock_provider(monkeypatch)
        state = parse_qs(urlparse(app_client.get("/api/v1/calendar-connections/google/connect").json()["authorize_url"]).query)[
            "state"
        ][0]
        app_client.get(f"/api/v1/calendar-connections/google/callback?code=c&state={state}", follow_redirects=False)
        connection_id = app_client.get("/api/v1/calendar-connections").json()[0]["id"]

        response = app_client.delete(f"/api/v1/calendar-connections/{connection_id}")
        assert response.status_code == 204
        assert app_client.get("/api/v1/calendar-connections").json() == []
