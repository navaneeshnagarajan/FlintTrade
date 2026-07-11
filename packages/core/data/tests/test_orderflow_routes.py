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


def test_orderflow_live_reports_unrepresentable_interval_and_tick_size_honestly(app):
    """Finer requested dimensions cannot be reconstructed from coarser live bins."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    bucket = SimpleNamespace(
        timestamp_bin=1_700_000_000,
        price_level=100.0,
        buy_volume=5,
        sell_volume=3,
        delta=2,
    )
    aggregator = MagicMock()
    aggregator.time_bin_seconds = 300
    aggregator.tick_size = 0.05
    aggregator.get_footprint.return_value = [bucket]
    app.config["ORDERFLOW_AGGREGATOR"] = aggregator

    with app.test_client() as client:
        response = client.get("/api/v1/data/orderflow?symbol=NIFTY&interval=60&tick_size=0.01")

    data = response.get_json()["data"]
    assert data["is_live"] is True
    assert data["interval"] == 300
    assert data.get("tick_size") == 0.05
    assert data["requested_interval"] == 60
    assert data.get("requested_tick_size") == 0.01
    assert data.get("source_interval") == 300
    assert data.get("source_tick_size") == 0.05


def test_orderflow_live_coarsens_exact_interval_multiple_without_losing_volume(app):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    source_start = 1_742_870_700
    aggregator = MagicMock()
    aggregator.time_bin_seconds = 300
    aggregator.tick_size = 0.05
    aggregator.get_footprint.return_value = [
        SimpleNamespace(
            timestamp_bin=source_start + offset,
            price_level=100.0,
            buy_volume=buy,
            sell_volume=sell,
            delta=buy - sell,
        )
        for offset, buy, sell in ((0, 10, 1), (300, 20, 2), (600, 30, 3))
    ]
    app.config["ORDERFLOW_AGGREGATOR"] = aggregator

    with app.test_client() as client:
        response = client.get("/api/v1/data/orderflow?symbol=NIFTY&interval=900&bins=2")

    data = response.get_json()["data"]
    assert data["is_live"] is True
    assert data["interval"] == 900
    assert data.get("source_interval") == 300
    assert len(data["buckets"]) == 1
    assert data["buckets"][0]["total_volume"] == 66
    assert data["buckets"][0]["delta"] == 54
    aggregator.get_footprint.assert_called_once_with("NIFTY", n_bins=6, exchange="NFO")


def test_orderflow_live_coarsens_exact_tick_size_multiple_without_losing_volume(app):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    aggregator = MagicMock()
    aggregator.time_bin_seconds = 300
    aggregator.tick_size = 0.5
    aggregator.get_footprint.return_value = [
        SimpleNamespace(
            timestamp_bin=1_700_000_000,
            price_level=price,
            buy_volume=buy,
            sell_volume=sell,
            delta=buy - sell,
        )
        for price, buy, sell in ((100.0, 10, 2), (100.5, 20, 3))
    ]
    app.config["ORDERFLOW_AGGREGATOR"] = aggregator

    with app.test_client() as client:
        response = client.get("/api/v1/data/orderflow?symbol=NIFTY&tick_size=1.0")

    data = response.get_json()["data"]
    assert data["is_live"] is True
    assert data.get("tick_size") == 1.0
    assert data.get("source_tick_size") == 0.5
    assert data.get("requested_tick_size") == 1.0
    assert len(data["buckets"][0]["cells"]) == 1
    assert data["buckets"][0]["total_volume"] == 35
    assert data["buckets"][0]["delta"] == 25


def test_orderflow_synthetic_reports_requested_interval(app):
    """The synthetic fallback genuinely honours the requested interval."""
    with app.test_client() as c:
        resp = c.get("/api/v1/data/orderflow?symbol=NIFTY&interval=900")
    data = resp.get_json()["data"]
    assert data["is_live"] is False
    assert data["interval"] == 900
    assert data["requested_interval"] == 900
