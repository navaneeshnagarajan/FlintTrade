"""Tests for packages/data/src/sandbox_routes.py (Flask Blueprint).

Uses Flask test client with a mock SandboxEngine.

Run with:
    python -m pytest packages/data/tests/test_sandbox_routes.py -v --import-mode=importlib
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from flask import Flask

from packages.data.src.sandbox_routes import data_sandbox_bp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_engine(starting_capital: float = 500_000.0) -> MagicMock:
    """Return a mock SandboxEngine with sensible defaults."""
    engine = MagicMock()
    engine.get_capital.return_value = {
        "initial": starting_capital,
        "current": starting_capital,
        "available": starting_capital,
        "used_margin": 0.0,
    }
    engine.adjust_capital.return_value = {
        "initial": starting_capital,
        "current": starting_capital + 10_000.0,
        "available": starting_capital + 10_000.0,
        "used_margin": 0.0,
    }
    engine.get_positions.return_value = []
    engine.get_orders.return_value = []
    engine.get_pnl.return_value = {"realised": 0.0, "unrealised": 0.0, "total": 0.0}
    engine.place_order.return_value = {
        "status": "COMPLETE",
        "order_id": "SB-001",
        "message": "Order filled",
    }
    engine.reset.return_value = {
        "capital": starting_capital,
        "positions": [],
        "orders": [],
    }
    engine.export_data.return_value = '{"capital":500000}'
    engine.import_data.return_value = {
        "capital_imported": True,
        "positions_imported": 0,
        "orders_imported": 0,
    }
    return engine


@pytest.fixture()
def app():
    """Minimal Flask app with the data sandbox blueprint."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.config["DATA_SANDBOX_ENGINE"] = _make_mock_engine()
    flask_app.register_blueprint(data_sandbox_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def engine(app):
    return app.config["DATA_SANDBOX_ENGINE"]


@pytest.fixture()
def client_no_engine():
    """Flask app without a sandbox engine — tests 503 responses."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(data_sandbox_bp)
    return flask_app.test_client()


# ---------------------------------------------------------------------------
# Tests — Capital
# ---------------------------------------------------------------------------


class TestGetCapital:
    def test_returns_capital(self, client, engine):
        resp = client.get("/v1/sandbox/capital")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["capital"]["initial"] == 500_000.0
        engine.get_capital.assert_called_once()

    def test_no_engine_returns_503(self, client_no_engine):
        resp = client_no_engine.get("/v1/sandbox/capital")
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Tests — Place Order
# ---------------------------------------------------------------------------


class TestPlaceOrder:
    def test_place_order_success(self, client, engine):
        resp = client.post("/v1/sandbox/order", json={
            "symbol": "NIFTY",
            "exchange": "NSE_INDEX",
            "action": "BUY",
            "quantity": 50,
            "price": 24000.0,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["order"]["order_id"] == "SB-001"
        engine.place_order.assert_called_once_with(
            symbol="NIFTY",
            exchange="NSE_INDEX",
            action="BUY",
            quantity=50,
            price=24000.0,
            product="MIS",
        )

    def test_place_order_missing_fields(self, client):
        resp = client.post("/v1/sandbox/order", json={"symbol": "NIFTY"})
        assert resp.status_code == 400
        assert "Missing required fields" in resp.get_json()["message"]

    def test_place_order_invalid_quantity(self, client):
        resp = client.post("/v1/sandbox/order", json={
            "symbol": "NIFTY",
            "exchange": "NSE_INDEX",
            "action": "BUY",
            "quantity": "abc",
            "price": 24000.0,
        })
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Tests — Positions
# ---------------------------------------------------------------------------


class TestGetPositions:
    def test_returns_list(self, client, engine):
        resp = client.get("/v1/sandbox/positions")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["positions"] == []
        engine.get_positions.assert_called_once()


# ---------------------------------------------------------------------------
# Tests — Orders
# ---------------------------------------------------------------------------


class TestGetOrders:
    def test_returns_list(self, client, engine):
        resp = client.get("/v1/sandbox/orders")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["orders"] == []
        engine.get_orders.assert_called_once()


# ---------------------------------------------------------------------------
# Tests — Reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_everything(self, client, engine):
        resp = client.post("/v1/sandbox/reset")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "backup" in data["data"]
        engine.reset.assert_called_once()

    def test_reset_no_engine(self, client_no_engine):
        resp = client_no_engine.post("/v1/sandbox/reset")
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Tests — P&L
# ---------------------------------------------------------------------------


class TestGetPnl:
    def test_returns_pnl(self, client, engine):
        resp = client.get("/v1/sandbox/pnl")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["data"]["pnl"]["realised"] == 0.0
        engine.get_pnl.assert_called_once()
