"""Tests for GET /api/v1/ping liveness endpoint.

Run with:
    python -m pytest packages/core/core/tests/test_ping_route.py -v --import-mode=importlib
"""

from __future__ import annotations

import pytest
from flask import Flask

from flinttrade_core.health_routes import health_bp
from flinttrade_engine.laya import DecisionStatus, process_laya, reset_process_laya_for_tests


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

    def test_ping_publishes_laya_down_until_status_is_explicit(self, client) -> None:  # type: ignore[no-untyped-def]
        """A fresh process is Down. Ping does not invent Ready."""
        reset_process_laya_for_tests()
        assert process_laya().status is DecisionStatus.DOWN
        first = client.get("/api/v1/ping").get_json()
        assert first is not None
        assert first["laya"] == "down"
        assert first["laya_practice"] == "down"
        assert first["laya_live_qualified"] is False
        assert first["laya_reason"] == "not_started"
        assert first["laya_port"] == 8000
        process_laya().set_status(DecisionStatus.READY)
        second = client.get("/api/v1/ping").get_json()
        assert second is not None
        assert second["laya"] == "ready"
        assert second["laya_practice"] == "ready"
        assert second["laya_live_qualified"] is True
        assert second["laya_reason"] is None
        process_laya().apply_runtime_status(DecisionStatus.DEGRADED, live_qualified=False)
        third = client.get("/api/v1/ping").get_json()
        assert third is not None
        assert third["laya"] == "down"
        assert third["laya_practice"] == "degraded"
        assert third["laya_live_qualified"] is False
        assert third["laya_reason"] is None
        reset_process_laya_for_tests()
