"""Tests for packages/engine/src/order_routes.py — basket, split, options-strategy."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from flask import Flask

import packages.engine.src.order_routes as mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _basket_result(success: bool = True) -> MagicMock:
    r = MagicMock()
    r.success = success
    r.strategy = "test_basket"
    r.timestamp = "2026-04-19T10:00:00"
    r.placed_count = 2 if success else 0
    r.failed_count = 0 if success else 2
    r.rolled_back = not success
    r.order_ids = ["OID1", "OID2"] if success else []
    r.legs = []
    r.error = None if success else "Rejected"
    r.failed_leg_index = None if success else 0
    return r


def _split_result(success: bool = True) -> MagicMock:
    r = MagicMock()
    r.success = success
    r.symbol = "NIFTY25MAYFUT"
    r.exchange = "NFO"
    r.action = "BUY"
    r.total_quantity = 300
    r.chunk_size = 75
    r.placed_quantity = 300 if success else 0
    r.placed_count = 4 if success else 0
    r.failed_count = 0 if success else 4
    r.strategy = "split"
    r.timestamp = "2026-04-19T10:00:00"
    r.order_ids = ["OID1"] if success else []
    r.chunks = []
    r.error = None if success else "Rejected"
    return r


def _make_app(basket_executor=None, split_executor=None) -> Flask:
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.config["MODE"] = "live"
    if basket_executor:
        flask_app.config["BASKET_EXECUTOR"] = basket_executor
    if split_executor:
        flask_app.config["SPLIT_EXECUTOR"] = split_executor
    flask_app.register_blueprint(mod.order_bp)
    return flask_app


# ---------------------------------------------------------------------------
# POST /api/v1/orders/basket
# ---------------------------------------------------------------------------


def test_basket_no_executor():
    """503 when BASKET_EXECUTOR not configured."""
    with _make_app().test_client() as c:
        resp = c.post(
            "/api/v1/orders/basket",
            json={"legs": [{"symbol": "NIFTY25MAYFUT", "exchange": "NFO", "action": "BUY", "quantity": 50}]},
        )
    assert resp.status_code == 503


def test_basket_missing_legs():
    """400 when legs field absent."""
    ex = MagicMock()
    with _make_app(basket_executor=ex).test_client() as c:
        resp = c.post("/api/v1/orders/basket", json={})
    assert resp.status_code == 400


def test_basket_ok():
    """201 on successful basket execution."""
    result = _basket_result(success=True)
    ex = MagicMock()
    ex.execute = AsyncMock(return_value=result)

    legs = [
        {"symbol": "NIFTY25MAYFUT", "exchange": "NFO", "action": "BUY", "quantity": 50},
    ]

    with _make_app(basket_executor=ex).test_client() as c:
        with patch(
            "packages.engine.src.order_routes._run_async",
            return_value=result,
        ):
            resp = c.post("/api/v1/orders/basket", json={"legs": legs})

    assert resp.status_code == 201
    assert resp.get_json()["status"] == "success"


# ---------------------------------------------------------------------------
# POST /api/v1/orders/split
# ---------------------------------------------------------------------------


def test_split_no_executor():
    """503 when SPLIT_EXECUTOR not configured."""
    with _make_app().test_client() as c:
        resp = c.post(
            "/api/v1/orders/split",
            json={"symbol": "NIFTY25MAYFUT", "exchange": "NFO",
                  "action": "BUY", "total_qty": 300, "chunk_size": 75},
        )
    assert resp.status_code == 503


def test_split_missing_required():
    """400 when required fields absent."""
    ex = MagicMock()
    with _make_app(split_executor=ex).test_client() as c:
        resp = c.post("/api/v1/orders/split", json={"symbol": "NIFTY25MAYFUT"})
    assert resp.status_code == 400


def test_split_ok():
    """201 on successful split execution."""
    result = _split_result(success=True)
    ex = MagicMock()

    with _make_app(split_executor=ex).test_client() as c:
        with patch(
            "packages.engine.src.order_routes._run_async",
            return_value=result,
        ):
            resp = c.post(
                "/api/v1/orders/split",
                json={
                    "symbol": "NIFTY25MAYFUT",
                    "exchange": "NFO",
                    "action": "BUY",
                    "total_qty": 300,
                    "chunk_size": 75,
                },
            )

    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# POST /api/v1/orders/options-strategy
# ---------------------------------------------------------------------------


def test_options_strategy_invalid_name():
    """400 for unknown strategy_name."""
    ex = MagicMock()
    with _make_app(basket_executor=ex).test_client() as c:
        resp = c.post(
            "/api/v1/orders/options-strategy",
            json={
                "strategy_name": "unknown_strategy",
                "underlying": "NIFTY",
                "expiry": "25MAY25",
            },
        )
    assert resp.status_code == 400


def test_options_strategy_missing_underlying():
    """400 when underlying is absent."""
    ex = MagicMock()
    with _make_app(basket_executor=ex).test_client() as c:
        resp = c.post(
            "/api/v1/orders/options-strategy",
            json={"strategy_name": "short_straddle", "expiry": "25MAY25"},
        )
    assert resp.status_code == 400
