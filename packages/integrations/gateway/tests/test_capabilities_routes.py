"""Tests for GET /api/v1/broker/capabilities endpoint.

Run with:
    python -m pytest packages/integrations/gateway/tests/test_capabilities_routes.py -v --import-mode=importlib
"""

from __future__ import annotations

import pytest
from flask import Flask

from flinttrade_gateway.capabilities_routes import capabilities_bp


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

    def test_native_history_interval_metadata_present(self, client) -> None:  # type: ignore[no-untyped-def]
        """Native brokers expose adapter-grounded historical interval metadata."""
        response = client.get("/api/v1/broker/capabilities?broker=upstox")
        assert response.status_code == 200
        caps = response.get_json()["capabilities"]
        assert caps["historical_intraday_intervals_minutes"] == [1, 3, 5, 15, 30]
        assert caps["historical_intervals"] == ["1m", "3m", "5m", "15m", "30m", "1D", "1W", "1M"]
        assert caps["connectable"] is True
        assert caps["mcp"]["remote_url"] == "https://mcp.upstox.com/mcp"
        assert caps["mcp"]["read_only"] is True
        assert caps["mcp"]["trading_supported"] is False

    def test_mcp_catalogue_lists_hosted_broker_mcp_servers(self, client) -> None:  # type: ignore[no-untyped-def]
        response = client.get("/api/v1/broker/mcp")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] == 3
        brokers = {b["adapter_id"]: b for b in data["brokers"]}
        assert set(brokers) == {"dhan", "upstox", "groww"}
        assert brokers["dhan"]["native"] is True
        assert brokers["dhan"]["connectable"] is True
        assert brokers["dhan"]["mcp"]["trading_supported"] is True
        assert brokers["upstox"]["mcp"]["read_only"] is True
        assert brokers["upstox"]["mcp"]["daily_reauthorization"] is True
        assert brokers["groww"]["native"] is True
        assert brokers["groww"]["connectable"] is False
        assert brokers["groww"]["mcp"]["remote_url"] == "https://mcp.groww.in/mcp"
        assert "DDPI" in " ".join(brokers["groww"]["mcp"]["cautions"])
        assert "disabled until live login/read verification" in " ".join(brokers["groww"]["mcp"]["cautions"])

    def test_mcp_catalogue_supports_single_broker_lookup(self, client) -> None:  # type: ignore[no-untyped-def]
        response = client.get("/api/v1/broker/mcp?broker=groww")
        assert response.status_code == 200
        broker = response.get_json()["broker"]
        assert broker["adapter_id"] == "groww"
        assert broker["mcp"]["client_configs"][1]["args"] == [
            "mcp-remote@0.1.18",
            "https://mcp.groww.in/mcp",
            "52155",
        ]

    def test_all_brokers_have_broker_name(self, client) -> None:  # type: ignore[no-untyped-def]
        """Every broker entry in the full list contains broker_name."""
        response = client.get("/api/v1/broker/capabilities")
        data = response.get_json()
        for entry in data["brokers"]:
            assert "broker_name" in entry
            assert isinstance(entry["broker_name"], str)
            assert len(entry["broker_name"]) > 0


class TestRecommendationsRoute:
    """Tests for GET /api/v1/broker/recommendations."""

    def test_all_use_cases_returned_by_default(self, client) -> None:  # type: ignore[no-untyped-def]
        response = client.get("/api/v1/broker/recommendations")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        assert "low_cost_execution" in data["use_cases"]
        recs = data["use_cases"]["low_cost_execution"]
        assert {"broker_id", "score", "raw_score", "rationale", "connectable"} <= set(recs[0])
        assert all(r["connectable"] is True for r in recs)

    def test_single_use_case(self, client) -> None:  # type: ignore[no-untyped-def]
        response = client.get("/api/v1/broker/recommendations?use_case=low_cost_execution")
        assert response.status_code == 200
        data = response.get_json()
        assert data["use_case"] == "low_cost_execution"
        ids = {r["broker_id"] for r in data["recommendations"]}
        assert "kotakneo" not in ids
        assert ids == {"dhan", "upstox", "indmoney"}
        assert all(r["connectable"] is True for r in data["recommendations"])
        display_names = {r["broker_id"]: r["display_name"] for r in data["recommendations"]}
        assert display_names["indmoney"] == "INDmoney"

    def test_include_coming_soon_keeps_disabled_native_capability_metadata(self, client) -> None:  # type: ignore[no-untyped-def]
        response = client.get(
            "/api/v1/broker/recommendations?use_case=low_cost_execution&include_coming_soon=true"
        )
        assert response.status_code == 200
        data = response.get_json()
        by_id = {r["broker_id"]: r for r in data["recommendations"]}
        assert {"kotakneo", "groww"} <= set(by_id)
        assert by_id["kotakneo"]["connectable"] is False
        assert by_id["groww"]["connectable"] is False

    def test_unknown_use_case_returns_400(self, client) -> None:  # type: ignore[no-untyped-def]
        response = client.get("/api/v1/broker/recommendations?use_case=teleport")
        assert response.status_code == 400
        data = response.get_json()
        assert data["status"] == "error"
        assert "known_use_cases" in data

    def test_broker_subset_filter(self, client) -> None:  # type: ignore[no-untyped-def]
        response = client.get(
            "/api/v1/broker/recommendations?use_case=market_depth&brokers=upstox,dhan"
        )
        assert response.status_code == 200
        ids = {r["broker_id"] for r in response.get_json()["recommendations"]}
        assert ids == {"upstox", "dhan"}

    def test_unknown_broker_returns_400(self, client) -> None:  # type: ignore[no-untyped-def]
        response = client.get("/api/v1/broker/recommendations?brokers=dhan,wakanda")
        assert response.status_code == 400
        data = response.get_json()
        assert data["status"] == "error"
        assert "known_brokers" in data

    def test_indmoney_broker_subset_accepted(self, client) -> None:  # type: ignore[no-untyped-def]
        # IndMoney is a full-parity native broker; the ``?brokers=`` filter
        # validates against NATIVE_BROKER_CAPABILITIES, so it must NOT be rejected
        # as unknown (regression guard for the registration gap that 400'd it).
        response = client.get("/api/v1/broker/recommendations?use_case=historical_data&brokers=indmoney")
        assert response.status_code == 200
        recommendations = response.get_json()["recommendations"]
        ids = {r["broker_id"] for r in recommendations}
        assert ids == {"indmoney"}
        assert recommendations[0]["connectable"] is True

    def test_groww_broker_subset_accepted_but_marked_unavailable(self, client) -> None:  # type: ignore[no-untyped-def]
        response = client.get("/api/v1/broker/recommendations?use_case=historical_data&brokers=groww")
        assert response.status_code == 200
        recommendations = response.get_json()["recommendations"]
        assert [r["broker_id"] for r in recommendations] == ["groww"]
        assert recommendations[0]["connectable"] is False
