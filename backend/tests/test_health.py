"""Tests for health check endpoint."""

from fastapi.testclient import TestClient

from app.main import app


def test_health_check() -> None:
    """Test that the health check endpoint returns 200 OK."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
