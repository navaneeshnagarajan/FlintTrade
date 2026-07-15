"""Tests for packages/core/data/src/sandbox_routes.py (Flask Blueprint).

Uses Flask test client with a mock SandboxEngine.

Run with:
    python -m pytest packages/core/data/tests/test_sandbox_routes.py -v --import-mode=importlib
"""

from __future__ import annotations

from dataclasses import asdict
from unittest.mock import MagicMock

import pytest
from flask import Flask

from flinttrade_data.sandbox_engine import SandboxConfig
from flinttrade_data.sandbox_routes import data_sandbox_bp


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
    engine.get_trades.return_value = []
    engine.get_pnl.return_value = {"realised": 0.0, "unrealised": 0.0, "total": 0.0}
    engine.get_pnl_history.return_value = []
    engine.config = SandboxConfig(starting_capital=starting_capital)
    engine.update_config.return_value = engine.config
    engine.square_off_all.return_value = 2
    engine.cancel_order.return_value = {
        "status": "CANCELLED",
        "order_id": "SB-001",
        "message": "Practice order cancelled",
    }
    engine.cancel_pending_orders.return_value = {
        "status": "CANCELLED",
        "cancelled_count": 2,
        "message": "Cancelled 2 pending Practice order(s)",
    }
    engine.modify_order.return_value = {
        "status": "PENDING",
        "order_id": "SB-001",
        "message": "Practice order modified",
    }
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
            order_type="MARKET",
            trigger_price=0.0,
            strategy="",
        )

    def test_pending_order_is_success_and_forwards_union_fields(self, client, engine):
        engine.place_order.return_value = {
            "status": "PENDING",
            "order_id": "SB-LIMIT",
            "message": "Pending",
        }
        resp = client.post("/v1/sandbox/order", json={
            "symbol": "INFY",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": 10,
            "price": 1_500.0,
            "pricetype": "LIMIT",
            "trigger_price": 1_490.0,
            "strategy": "mean-revert",
        })

        assert resp.status_code == 200
        engine.place_order.assert_called_once_with(
            symbol="INFY",
            exchange="NSE",
            action="BUY",
            quantity=10,
            price=1_500.0,
            product="MIS",
            order_type="LIMIT",
            trigger_price=1_490.0,
            strategy="mean-revert",
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


class TestGetStatus:
    """GET /v1/sandbox/status — combined status for the SandboxControls panel."""

    def test_returns_flat_status_shape(self, client, engine):
        resp = client.get("/v1/sandbox/status")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        # The UI schema requires capital as a single current-balance number.
        assert data["capital"] == 500_000.0
        assert data["initial_capital"] == 500_000.0
        assert data["pnl"] == 0.0
        assert data["trades_count"] == 0
        # capital must be a number, not the nested capital object
        assert isinstance(data["capital"], (int, float))

    def test_trades_count_reflects_executed_trades(self, client, engine):
        engine.get_trades.return_value = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
        resp = client.get("/v1/sandbox/status")
        assert resp.get_json()["data"]["trades_count"] == 3

    def test_no_engine_returns_503(self, client_no_engine):
        resp = client_no_engine.get("/v1/sandbox/status")
        assert resp.status_code == 503


class TestMergedSandboxSurface:
    def test_get_config(self, client, engine):
        resp = client.get("/v1/sandbox/config")

        assert resp.status_code == 200
        assert resp.get_json()["data"]["config"] == asdict(engine.config)

    def test_update_config_uses_validating_engine_method(self, client, engine):
        updated = SandboxConfig(starting_capital=500_000.0, equity_leverage=4)
        engine.update_config.return_value = updated

        resp = client.post("/v1/sandbox/config", json={"equity_leverage": 4})

        assert resp.status_code == 200
        assert resp.get_json()["data"]["config"]["equity_leverage"] == 4
        engine.update_config.assert_called_once_with(equity_leverage=4)

    def test_update_config_rejects_invalid_input(self, client, engine):
        engine.update_config.side_effect = ValueError("invalid")

        resp = client.post("/v1/sandbox/config", json={"equity_leverage": 0})

        assert resp.status_code == 400
        assert resp.get_json()["status"] == "error"

    def test_get_trades_and_pnl_history(self, client, engine):
        engine.get_trades.return_value = [{"trade_id": "T-1"}]
        engine.get_pnl_history.return_value = [{"date": "2026-07-14"}]

        trades = client.get("/v1/sandbox/trades")
        pnl = client.get("/v1/sandbox/pnl/history")

        assert trades.get_json()["data"]["trades"] == [{"trade_id": "T-1"}]
        assert pnl.get_json()["data"]["pnl_history"] == [{"date": "2026-07-14"}]

    def test_get_legacy_funds_shape_from_canonical_engine(self, client, engine):
        engine.get_funds.return_value = {
            "starting_capital": 500_000.0,
            "used_margin": 10_000.0,
            "realized_pnl": 500.0,
            "available_balance": 490_000.0,
            "total_equity": 500_500.0,
        }

        resp = client.get("/v1/sandbox/funds")

        assert resp.status_code == 200
        assert resp.get_json()["data"]["funds"]["total_equity"] == 500_500.0

    def test_square_off_forwards_exchange_qualified_ticks(self, client, engine):
        ticks = {"NSE:INFY": 1_510.0, "NSE:TCS": 3_900.0}

        resp = client.post("/v1/sandbox/square-off", json={"latest_ticks": ticks})

        assert resp.status_code == 200
        assert resp.get_json()["data"]["closed_positions"] == 2
        engine.square_off_all.assert_called_once_with(ticks)

    def test_cancel_modify_and_cancel_all_reach_engine(self, client, engine):
        cancelled = client.delete("/v1/sandbox/order/SB-001")
        modified = client.patch(
            "/v1/sandbox/order/SB-001",
            json={"quantity": 5, "price": 100.0, "pricetype": "LIMIT"},
        )
        all_cancelled = client.post("/v1/sandbox/orders/cancel-all")

        assert cancelled.status_code == 200
        assert modified.status_code == 200
        assert all_cancelled.status_code == 200
        engine.cancel_order.assert_called_once_with("SB-001")
        engine.modify_order.assert_called_once_with(
            "SB-001",
            quantity=5,
            price=100.0,
            order_type="LIMIT",
        )
        engine.cancel_pending_orders.assert_called_once_with()
