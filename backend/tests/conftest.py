"""Pytest configuration and shared fixtures."""

import os

# Settings.secret_key is required (architecture-plan §7.1) - set a test-only default
# before anything imports app.core.config, so no test needs to remember to set it.
# monkeypatch.setenv in individual tests overrides this within its own scope as usual.
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-use")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    """Provide a FastAPI test client."""
    return TestClient(app)
