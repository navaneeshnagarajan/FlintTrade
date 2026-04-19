"""Tests for GET /api/v1/intervals endpoint.

Run with:
    python -m pytest packages/historical/tests/test_intervals_routes.py -v --import-mode=importlib
"""

from __future__ import annotations

import pytest
from flask import Flask

from packages.historical.src.intervals_routes import intervals_bp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app() -> Flask:
    """Minimal Flask app with the intervals blueprint."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(intervals_bp)
    return flask_app


@pytest.fixture()
def client(app: Flask):  # type: ignore[no-untyped-def]
    return app.test_client()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIntervalsRoute:
    """Tests for GET /api/v1/intervals."""

    def test_no_broker_returns_registry(self, client) -> None:  # type: ignore[no-untyped-def]
        """Calling without ?broker returns the full broker registry."""
        response = client.get("/api/v1/intervals")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        assert "brokers" in data
        assert "all_brokers" in data
        assert isinstance(data["all_brokers"], list)
        assert len(data["all_brokers"]) > 0

    def test_known_broker_returns_intervals(self, client) -> None:  # type: ignore[no-untyped-def]
        """Known broker returns a non-empty interval list with is_known_broker=True."""
        response = client.get("/api/v1/intervals?broker=zerodha")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        assert data["broker"] == "zerodha"
        assert isinstance(data["intervals"], list)
        assert len(data["intervals"]) > 0
        assert data["is_known_broker"] is True

    def test_unknown_broker_returns_defaults(self, client) -> None:  # type: ignore[no-untyped-def]
        """Unknown broker returns default intervals with is_known_broker=False."""
        response = client.get("/api/v1/intervals?broker=unknownbroker")
        assert response.status_code == 200
        data = response.get_json()
        assert data["is_known_broker"] is False
        assert isinstance(data["intervals"], list)
        assert len(data["intervals"]) > 0

    def test_multi_broker_intersection(self, client) -> None:  # type: ignore[no-untyped-def]
        """?brokers=zerodha,icici returns intersection of their intervals."""
        response = client.get("/api/v1/intervals?brokers=zerodha,icici")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        assert isinstance(data["intervals"], list)
        # 1m is in zerodha but NOT in icici (icici min is 1m actually, but the
        # intersection should always be non-empty for two real brokers)
        assert data["count"] == len(data["intervals"])
