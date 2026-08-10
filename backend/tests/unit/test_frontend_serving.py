"""Unit tests for `SPAStaticFiles` (architecture-plan §7 - same-origin static serving).

Exercises the class directly against a throwaway static directory rather than the real
`app.main` singleton, since that mount is resolved once at import time from a fixed,
Dockerfile-populated path (`../static`) that doesn't exist in this test environment.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import SPAStaticFiles, _docs_urls


@pytest.fixture
def built_frontend(tmp_path: Path) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>spa shell</html>")
    (tmp_path / "assets" / "app.js").write_text("console.log('app');")
    return tmp_path


@pytest.fixture
def spa_client(built_frontend: Path) -> Iterator[TestClient]:
    app = FastAPI()
    app.mount("/", SPAStaticFiles(directory=built_frontend, html=True), name="frontend")
    with TestClient(app) as client:
        yield client


class TestSPAStaticFiles:
    def test_serves_a_real_static_asset(self, spa_client: TestClient) -> None:
        response = spa_client.get("/assets/app.js")
        assert response.status_code == 200
        assert "console.log" in response.text

    def test_serves_index_html_at_root(self, spa_client: TestClient) -> None:
        response = spa_client.get("/")
        assert response.status_code == 200
        assert "spa shell" in response.text

    def test_falls_back_to_index_html_for_an_unknown_client_route(self, spa_client: TestClient) -> None:
        # React Router route like /timeline has no matching file on disk - a hard
        # reload here must still return the SPA shell, not a 404.
        response = spa_client.get("/timeline")
        assert response.status_code == 200
        assert "spa shell" in response.text

    def test_does_not_mask_an_unmatched_api_path_with_the_spa_shell(self, spa_client: TestClient) -> None:
        # Belt-and-suspenders: in the real app this is unreachable (a real /api/... route
        # always claims the request first), but the fallback itself must not paper over
        # a stale/removed API path with a misleading 200.
        response = spa_client.get("/api/does-not-exist")
        assert response.status_code == 404


class TestDocsUrls:
    """architecture-plan §6 "API docs in production" (Rev 3, closed in Stage 11):
    `/docs`/`/redoc`/`/openapi.json` would otherwise expose the whole API surface
    uncredentialed - disabled by default, opt-in via `ENABLE_API_DOCS`.
    """

    def test_disabled_by_default_means_every_url_is_none(self) -> None:
        urls = _docs_urls(enable_api_docs=False)
        assert urls == (None, None, None, None)

    def test_enabled_scopes_every_url_under_api_v1(self) -> None:
        urls = _docs_urls(enable_api_docs=True)
        assert urls.openapi_url == "/api/v1/openapi.json"
        assert urls.docs_url == "/api/v1/docs"
        assert urls.redoc_url == "/api/v1/redoc"
        # Must stay under /api/ - AuthGuardMiddleware._is_frontend_request treats
        # anything outside that prefix as a public static path (Stage 10).
        assert urls.swagger_ui_oauth2_redirect_url is not None
        assert urls.swagger_ui_oauth2_redirect_url.startswith("/api/")
