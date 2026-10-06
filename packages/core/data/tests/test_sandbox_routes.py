"""Tests for packages/core/data/src/sandbox_routes.py (Flask Blueprint).

Uses Flask test clients with mock and isolated in-memory SandboxEngine instances.

Run with:
    python -m pytest packages/core/data/tests/test_sandbox_routes.py -v --import-mode=importlib
"""

from __future__ import annotations

from dataclasses import asdict
from unittest.mock import MagicMock

import pytest
from flask import Flask

from flinttrade_data.sandbox_engine import SandboxConfig, SandboxEngine
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


@pytest.fixture()
def pending_practice_order(app):
    """Exercise mutation routes against a real, isolated Practice book."""
    engine = SandboxEngine(db_path=":memory:")
    app.config["DATA_SANDBOX_ENGINE"] = engine
    try:
        placed = engine.place_order("INFY", "NSE", "BUY", 5, 100.0, order_type="LIMIT")
        assert placed["status"] == "PENDING"
        yield engine, placed["order_id"]
    finally:
        engine.close()


@pytest.mark.integration
class TestOrderInputValidation:
    @pytest.mark.parametrize(
        "quantity",
        [
            1.9,
            True,
            False,
            "1.9",
            None,
            "bad",
            "",
            "NaN",
            "Infinity",
            0,
            -1,
            [],
            {},
            float("nan"),
            float("inf"),
            -float("inf"),
        ],
    )
    def test_invalid_quantity_leaves_the_book_unchanged(self, client, pending_practice_order, quantity):
        engine, order_id = pending_practice_order
        before = (engine.get_orders(), engine.get_positions(), engine.get_capital())
        writes = engine._conn.total_changes

        response = client.patch(f"/v1/sandbox/order/{order_id}", json={"quantity": quantity, "price": 110.0})

        assert response.status_code == 400
        assert response.get_json()["status"] == "error"
        assert (engine.get_orders(), engine.get_positions(), engine.get_capital()) == before
        assert engine._conn.total_changes == writes

    @pytest.mark.parametrize(
        "method,route",
        [("PATCH", "/order/{order_id}"), ("DELETE", "/order/{order_id}"), ("POST", "/orders/cancel-all")],
    )
    @pytest.mark.parametrize(
        "raw_body", ["[]", "[1]", "null", '"text"', '""', "false", "true", "0", "1", "{not json", " "]
    )
    def test_invalid_json_leaves_the_book_unchanged(self, client, pending_practice_order, method, route, raw_body):
        engine, order_id = pending_practice_order
        before = (engine.get_orders(), engine.get_positions(), engine.get_capital())
        writes = engine._conn.total_changes

        response = client.open(
            "/v1/sandbox" + route.format(order_id=order_id),
            method=method,
            data=raw_body,
            content_type="application/json",
        )

        assert response.status_code == 400
        assert response.get_json()["status"] == "error"
        assert "JSON object" in response.get_json()["message"]
        assert (engine.get_orders(), engine.get_positions(), engine.get_capital()) == before
        assert engine._conn.total_changes == writes

    @pytest.mark.parametrize(
        "method,route",
        [("PATCH", "/order/{order_id}"), ("DELETE", "/order/{order_id}"), ("POST", "/orders/cancel-all")],
    )
    def test_non_json_content_type_leaves_the_book_unchanged(self, client, pending_practice_order, method, route):
        engine, order_id = pending_practice_order
        before = engine.get_orders()
        writes = engine._conn.total_changes

        response = client.open(
            "/v1/sandbox" + route.format(order_id=order_id),
            method=method,
            data='{"quantity": 2}',
            content_type="text/plain",
        )

        assert response.status_code == 400
        assert "JSON object" in response.get_json()["message"]
        assert engine.get_orders() == before
        assert engine._conn.total_changes == writes

    @pytest.mark.parametrize("quantity,expected", [(2, 2), (2.0, 2), ("2", 2), (" 2 ", 2), ("+2", 2), ("1_0", 10)])
    def test_whole_quantities_update_quantity_and_margin(self, client, pending_practice_order, quantity, expected):
        engine, order_id = pending_practice_order

        response = client.patch(f"/v1/sandbox/order/{order_id}", json={"quantity": quantity, "price": 110.0})

        assert response.status_code == 200, response.get_json()
        order = engine.get_orders()[0]
        assert order["quantity"] == expected
        assert order["price"] == 110.0
        assert order["order_type"] == "LIMIT"
        assert engine.get_capital()["used_margin"] == pytest.approx(expected * 110.0)

    def test_omitted_quantity_keeps_existing_quantity(self, client, pending_practice_order):
        engine, order_id = pending_practice_order

        response = client.patch(f"/v1/sandbox/order/{order_id}", json={"price": 110.0})

        assert response.status_code == 200, response.get_json()
        order = engine.get_orders()[0]
        assert order["quantity"] == 5
        assert order["price"] == 110.0
        assert order["order_type"] == "LIMIT"

    @pytest.mark.parametrize(
        "method,route,expected_status",
        [
            ("PATCH", "/order/{order_id}", "PENDING"),
            ("DELETE", "/order/{order_id}", "CANCELLED"),
            ("POST", "/orders/cancel-all", "CANCELLED"),
        ],
    )
    @pytest.mark.parametrize("raw_body", ["", "{}"])
    def test_absent_and_empty_object_bodies_still_work(
        self, client, pending_practice_order, method, route, expected_status, raw_body
    ):
        engine, order_id = pending_practice_order

        response = client.open(
            "/v1/sandbox" + route.format(order_id=order_id),
            method=method,
            data=raw_body,
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.get_json()["status"] == "success"
        order = engine.get_orders()[0]
        assert order["status"] == expected_status
        assert order["quantity"] == 5
        assert order["order_type"] == "LIMIT"

    @pytest.mark.parametrize("order_type,pricetype", [("LIMIT", "SL"), (" sl ", "limit")])
    def test_conflicting_order_types_leave_the_book_unchanged(
        self, client, pending_practice_order, order_type, pricetype
    ):
        engine, order_id = pending_practice_order
        before = engine.get_orders()
        writes = engine._conn.total_changes

        response = client.patch(
            f"/v1/sandbox/order/{order_id}",
            json={"quantity": 2, "order_type": order_type, "pricetype": pricetype, "trigger_price": 99.0},
        )

        assert response.status_code == 400
        assert response.get_json()["status"] == "error"
        assert engine.get_orders() == before
        assert engine._conn.total_changes == writes

    @pytest.mark.parametrize("order_type,pricetype", [(" slm ", "SL-M"), ("SL-M", " slm ")])
    def test_stop_market_alias_spellings_modify_the_same_order(
        self, client, pending_practice_order, order_type, pricetype
    ):
        engine, order_id = pending_practice_order

        response = client.patch(
            f"/v1/sandbox/order/{order_id}",
            json={"order_type": order_type, "pricetype": pricetype, "trigger_price": 99.0},
        )

        assert response.status_code == 200, response.get_json()
        assert response.get_json()["status"] == "success"
        order = engine.get_orders()[0]
        assert order["order_type"] == order["pricetype"] == "SL-M"
        assert order["status"] == "PENDING"
        assert order["quantity"] == 5
        assert order["trigger_price"] == 99.0

    @pytest.mark.parametrize(
        "aliases",
        [
            {"order_type": " sl "},
            {"pricetype": " sl "},
            {"order_type": " sl ", "pricetype": "SL"},
            {"order_type": None, "pricetype": "SL"},
            {"order_type": "", "pricetype": "SL"},
        ],
    )
    def test_order_type_aliases_are_normalised(self, client, pending_practice_order, aliases):
        engine, order_id = pending_practice_order

        response = client.patch(f"/v1/sandbox/order/{order_id}", json={**aliases, "trigger_price": 99.0})

        assert response.status_code == 200, response.get_json()
        order = engine.get_orders()[0]
        assert order["order_type"] == order["pricetype"] == "SL"
        assert order["quantity"] == 5
        assert order["trigger_price"] == 99.0


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

    def test_place_and_square_off_are_not_mounted(self, client):
        """Paper placement is not a sandbox route."""
        placed = client.post(
            "/v1/sandbox/order",
            json={
                "symbol": "NIFTY",
                "exchange": "NSE",
                "action": "BUY",
                "quantity": 1,
                "price": 100.0,
            },
        )
        squared = client.post("/v1/sandbox/square-off", json={"latest_ticks": {"NSE:NIFTY": 100.0}})

        assert placed.status_code == 404
        assert squared.status_code == 404

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
