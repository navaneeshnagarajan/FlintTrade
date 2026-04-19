"""Tests for GET /api/v1/broker/capabilities endpoint.

Run with:
    python -m pytest packages/gateway/tests/test_capabilities_routes.py -v --import-mode=importlib
"""

from __future__ import annotations

import pytest
from flask import Flask

from packages.gateway.src.capabilities_routes import capabilities_bp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app() -> Flask:
    """Minimal Flask app with only the capabilities blueprint."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(capabilities_bp)
    return flask_app


@pytest.fixture()
def client(app: Flask):  # type: ignore[no-untyped-def]
    return app.test_client()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCapabilitiesRoute:
    """Tests for GET /api/v1/broker/capabilities."""

    def test_no_broker_returns_all(self, client) -> None:  # type: ignore[no-untyped-def]
        """Omitting ?broker returns all registered brokers."""
        response = client.get("/api/v1/broker/capabilities")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        assert isinstance(data["brokers"], list)
        assert data["count"] == len(data["brokers"])
        assert data["count"] > 0

    def test_known_broker_returns_caps(self, client) -> None:  # type: ignore[no-untyped-def]
        """Known broker returns its capabilities record."""
        response = client.get("/api/v1/broker/capabilities?broker=zerodha")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        assert data["broker"] == "zerodha"
        caps = data["capabilities"]
        assert caps["broker_name"] == "zerodha"
        assert isinstance(caps["supports_equity"], bool)

    def test_unknown_broker_returns_404(self, client) -> None:  # type: ignore[no-untyped-def]
        """Unregistered broker returns HTTP 404."""
        response = client.get("/api/v1/broker/capabilities?broker=nonexistent")
        assert response.status_code == 404
        data = response.get_json()
        assert data["status"] == "error"
        assert "known_brokers" in data

    def test_capabilities_fields_present(self, client) -> None:  # type: ignore[no-untyped-def]
        """All expected capability boolean fields are present in the response."""
        response = client.get("/api/v1/broker/capabilities?broker=zerodha")
        caps = response.get_json()["capabilities"]
        required_fields = [
            "supports_market_orders",
            "supports_limit_orders",
            "supports_options",
            "supports_websocket",
            "order_rate_limit_per_sec",
        ]
        for field in required_fields:
            assert field in caps, f"Missing field: {field}"

    def test_all_brokers_have_broker_name(self, client) -> None:  # type: ignore[no-untyped-def]
        """Every broker entry in the full list contains broker_name."""
        response = client.get("/api/v1/broker/capabilities")
        data = response.get_json()
        for entry in data["brokers"]:
            assert "broker_name" in entry
            assert isinstance(entry["broker_name"], str)
            assert len(entry["broker_name"]) > 0
