"""Tests for packages/core/data/src/orderflow_routes.py — footprint / order flow endpoint."""

from __future__ import annotations

import pytest
from flask import Flask

import flinttrade_data.orderflow_routes as mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.orderflow_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# GET /api/v1/data/orderflow
# ---------------------------------------------------------------------------


def test_orderflow_ok(client):
    """200 with synthetic buckets when no live aggregator configured."""
    resp = client.get("/api/v1/data/orderflow?symbol=NIFTY")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["data"]["symbol"] == "NIFTY"
    assert isinstance(body["data"]["buckets"], list)
    assert body["data"]["is_live"] is False


def test_orderflow_with_exchange(client):
    """200 with custom exchange param."""
    resp = client.get("/api/v1/data/orderflow?symbol=BANKNIFTY&exchange=NSE_INDEX")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["exchange"] == "NSE_INDEX"


def test_orderflow_missing_symbol(client):
    """400 when symbol param absent."""
    resp = client.get("/api/v1/data/orderflow")
    assert resp.status_code == 400


def test_orderflow_blank_symbol_returns_400(client):
    """Whitespace cannot select the legacy empty-symbol namespace."""
    resp = client.get("/api/v1/data/orderflow", query_string={"symbol": "   "})
    assert resp.status_code == 400


def test_orderflow_blank_exchange_returns_400(client):
    """Whitespace cannot collapse into the empty-exchange compatibility key."""
    resp = client.get(
        "/api/v1/data/orderflow",
        query_string={"symbol": "RELIANCE", "exchange": "   "},
    )
    assert resp.status_code == 400


def test_orderflow_invalid_interval(client):
    """400 when interval is not an integer."""
    resp = client.get("/api/v1/data/orderflow?symbol=NIFTY&interval=bad")
    assert resp.status_code == 400


def test_orderflow_invalid_bins(client):
    """400 when bins is not an integer."""
    resp = client.get("/api/v1/data/orderflow?symbol=NIFTY&bins=oops")
    assert resp.status_code == 400


def test_orderflow_invalid_tick_size(client):
    """400 when tick_size is not a parseable float."""
    resp = client.get("/api/v1/data/orderflow?symbol=NIFTY&tick_size=notafloat")
    assert resp.status_code == 400


def test_orderflow_negative_interval(client):
    """400 when interval <= 0."""
    resp = client.get("/api/v1/data/orderflow?symbol=NIFTY&interval=-1")
    assert resp.status_code == 400


def test_orderflow_live_aggregator(app):
    """Uses live aggregator when ORDERFLOW_AGGREGATOR configured."""
    from unittest.mock import MagicMock

    aggregator = MagicMock()
    # Return empty list so code falls back gracefully
    aggregator.get_footprint.return_value = []
    app.config["ORDERFLOW_AGGREGATOR"] = aggregator

    with app.test_client() as c:
        resp = c.get("/api/v1/data/orderflow?symbol=NIFTY")
    assert resp.status_code == 200


def test_orderflow_live_aggregator_receives_exchange(app):
    """The route queries the live footprint for the requested exchange."""
    from unittest.mock import MagicMock

    aggregator = MagicMock()
    aggregator.get_footprint.return_value = []
    app.config["ORDERFLOW_AGGREGATOR"] = aggregator

    with app.test_client() as c:
        resp = c.get(
            "/api/v1/data/orderflow",
            query_string={"symbol": " reliance ", "exchange": " bse ", "bins": 7},
        )

    assert resp.status_code == 200
    assert resp.get_json()["data"]["exchange"] == "BSE"
    aggregator.get_footprint.assert_called_once_with("RELIANCE", n_bins=7, exchange="BSE")


def test_orderflow_live_reports_real_bin_width_not_requested(app):
    """G28a: the live path must report the aggregator's real bin width, not echo
    the requested interval (which would relabel fixed 5-min bins as 1m/15m)."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    bucket = SimpleNamespace(
        timestamp_bin=1_700_000_000, price_level=100.0,
        buy_volume=5, sell_volume=3, delta=2,
    )
    aggregator = MagicMock()
    aggregator.time_bin_seconds = 300
    aggregator.get_footprint.return_value = [bucket]
    app.config["ORDERFLOW_AGGREGATOR"] = aggregator

    with app.test_client() as c:
        resp = c.get("/api/v1/data/orderflow?symbol=NIFTY&interval=60")  # request 1m
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["is_live"] is True
    assert data["interval"] == 300          # the aggregator's true width, not 60
    assert data["requested_interval"] == 60  # the request is echoed separately


def test_orderflow_synthetic_reports_requested_interval(app):
    """The synthetic fallback genuinely honours the requested interval."""
    with app.test_client() as c:
        resp = c.get("/api/v1/data/orderflow?symbol=NIFTY&interval=900")
    data = resp.get_json()["data"]
    assert data["is_live"] is False
    assert data["interval"] == 900
    assert data["requested_interval"] == 900
