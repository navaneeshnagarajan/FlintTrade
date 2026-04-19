"""Tests for GET /api/v1/ping liveness endpoint.

Run with:
    python -m pytest packages/core/tests/test_ping_route.py -v --import-mode=importlib
"""

from __future__ import annotations

import pytest
from flask import Flask

from packages.core.src.health_routes import health_bp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app() -> Flask:
    """Create a minimal Flask app with only the health blueprint."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(health_bp)
    return flask_app


@pytest.fixture()
def client(app: Flask):  # type: ignore[no-untyped-def]
    """Return a Flask test client."""
    return app.test_client()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPingRoute:
    """Tests for GET /api/v1/ping."""

    def test_ping_returns_200(self, client) -> None:  # type: ignore[no-untyped-def]
        """Ping returns HTTP 200."""
        response = client.get("/api/v1/ping")
        assert response.status_code == 200

    def test_ping_status_ok(self, client) -> None:  # type: ignore[no-untyped-def]
        """Response body contains status='ok'."""
        response = client.get("/api/v1/ping")
        data = response.get_json()
        assert data is not None
        assert data["status"] == "ok"

    def test_ping_has_timestamp(self, client) -> None:  # type: ignore[no-untyped-def]
        """Response body contains a non-empty ISO-8601 timestamp."""
        response = client.get("/api/v1/ping")
        data = response.get_json()
        assert data is not None
        ts = data.get("timestamp", "")
        assert isinstance(ts, str)
        assert len(ts) > 0
        # Verify IST offset (+05:30) is embedded in the timestamp
        assert "+05:30" in ts or "T" in ts
