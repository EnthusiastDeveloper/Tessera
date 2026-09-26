"""A route's database work must be committed before its response is sent.

FastAPI runs a yield dependency's teardown after the response by default. For `get_db`
that teardown is the commit, so a client could get the response - and act on it -
before the data existed: the Playwright suite logged in, fired the next request with the
new cookie, and got `session_expired` because the session row wasn't committed yet.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterable, Iterator

import httpx
import pytest
import uvicorn
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.routing import BaseRoute

from app.auth.setup_token import setup_token_store
from app.db.session import get_db
from app.main import app

VALID_PASSWORD = "correcthorsebatterystaple"


def _api_routes(routes: Iterable[BaseRoute]) -> Iterator[APIRoute]:
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        included = getattr(route, "original_router", None)  # FastAPI wraps each include_router()
        if included is not None:
            yield from _api_routes(included.routes)


def test_every_route_commits_its_session_before_responding() -> None:
    found = 0
    for route in _api_routes(app.routes):
        pending = list(route.dependant.dependencies)
        while pending:
            dependant = pending.pop()
            pending.extend(dependant.dependencies)
            if dependant.call is get_db:
                found += 1
                assert dependant.scope == "function", f"{route.path} gets a request-scoped DB session"
    assert found > 0


@pytest.fixture
def live_server(app_client: TestClient) -> Iterator[str]:
    """The same app, served over a real socket: TestClient waits for the whole ASGI call
    including dependency teardown, so it can't observe a response that beats the commit.
    `app_client` has already run the lifespan (DB, setup token), so it's switched off here.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off", log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "live server did not start"
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_a_session_is_usable_by_the_very_next_request_after_login(
    app_client: TestClient, live_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = setup_token_store._token  # test-only introspection, see test_auth_routes.py
    assert token is not None
    app_client.post("/api/v1/auth/setup", json={"token": token, "password": VALID_PASSWORD})

    # Widen the window a slow machine opens by accident.
    real_commit = Session.commit

    def slow_commit(self: Session) -> None:
        time.sleep(0.5)
        real_commit(self)

    monkeypatch.setattr(Session, "commit", slow_commit)

    with httpx.Client(base_url=live_server) as client:
        assert client.post("/api/v1/auth/login", json={"username": "admin", "password": VALID_PASSWORD}).status_code == 200
        me = client.get("/api/v1/auth/me")

    assert me.status_code == 200, me.text
