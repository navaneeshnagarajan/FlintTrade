"""Tests for packages/core/data/src/orderflow_routes.py — footprint / order flow endpoint."""

from __future__ import annotations

import os
import time as host_time

import pytest
from flask import Flask

import flinttrade_data.orderflow_routes as mod


def _mark_fresh(aggregator) -> None:
    aggregator.get_market_freshness.return_value = {
        "state": "live",
        "is_fresh": True,
        "last_tick_timestamp": 1_700_000_001.0,
        "last_tick_session": "2026-07-11",
        "current_session": "2026-07-11",
        "age_seconds": 1.0,
    }


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


@pytest.fixture()
def non_ist_host_timezone():
    if not hasattr(host_time, "tzset"):
        pytest.skip("host timezone mutation requires time.tzset")
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"
    host_time.tzset()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        host_time.tzset()


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
    _mark_fresh(aggregator)
    app.config["ORDERFLOW_AGGREGATOR"] = aggregator

    with app.test_client() as c:
        resp = c.get("/api/v1/data/orderflow?symbol=NIFTY&interval=60")  # request 1m
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["is_live"] is True
    assert data["interval"] == 300          # the aggregator's true width, not 60
    assert data["requested_interval"] == 60  # the request is echoed separately


def test_orderflow_prior_session_buckets_are_reported_as_stale_not_live(app):
    from flinttrade_data.orderflow_aggregator import OrderFlowAggregator

    prior_session = 1_700_000_000.0
    aggregator = OrderFlowAggregator()
    aggregator.feed_market_tick("NIFTY", 100.0, 1000, exchange="NFO", timestamp=prior_session)
    aggregator.feed_market_tick("NIFTY", 101.0, 1100, exchange="NFO", timestamp=prior_session + 1)
    app.config["ORDERFLOW_AGGREGATOR"] = aggregator

    with app.test_client() as client:
        response = client.get("/api/v1/data/orderflow?symbol=NIFTY&exchange=NFO")

    data = response.get_json()["data"]
    assert data["buckets"]
    assert data["is_live"] is False
    assert data["live_state"] == "stale"
    assert data["freshness"]["is_fresh"] is False
    assert data["freshness"]["last_tick_timestamp"] == prior_session + 1


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
    _mark_fresh(aggregator)
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
    _mark_fresh(aggregator)
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
    _mark_fresh(aggregator)
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


@pytest.mark.parametrize(
    ("symbol", "exchange", "prices", "requested_tick_size", "expected_cell_count"),
    [
        ("EURUSD", "CDS", (1.0840, 1.0841), 0.0001, 2),
        ("USDINR", "CDS", (83.0000, 83.0001), 0.0025, 1),
        ("CRUDEOIL", "MCX", (6500.0, 6500.0001), 1.0, 1),
        ("RELIANCE", "NSE", (2500.00, 2500.0001), 0.01, 1),
    ],
)
def test_precise_shared_live_grid_coarsens_each_instrument_without_losing_volume(
    app,
    symbol,
    exchange,
    prices,
    requested_tick_size,
    expected_cell_count,
):
    from flinttrade_data.orderflow_aggregator import create_live_market_orderflow_aggregator

    aggregator = create_live_market_orderflow_aggregator()
    aggregator.add_tick(symbol, prices[0], 12, "BUY", timestamp=1_774_410_300, exchange=exchange)
    aggregator.add_tick(symbol, prices[1], 23, "SELL", timestamp=1_774_410_301, exchange=exchange)
    app.config["ORDERFLOW_AGGREGATOR"] = aggregator

    with app.test_client() as client:
        response = client.get(
            "/api/v1/data/orderflow",
            query_string={
                "symbol": symbol,
                "exchange": exchange,
                "interval": 60,
                "tick_size": requested_tick_size,
            },
        )

    data = response.get_json()["data"]
    assert data["source_tick_size"] == 0.0001
    assert data["tick_size"] == requested_tick_size
    assert len(data["buckets"][0]["cells"]) == expected_cell_count
    assert data["buckets"][0]["total_volume"] == 35
    assert data["buckets"][0]["delta"] == -11


def test_live_and_synthetic_time_labels_are_explicitly_ist_under_non_ist_host_timezone(
    non_ist_host_timezone,
    monkeypatch,
):
    from types import SimpleNamespace

    market_open_ist = 1_774_410_300  # 2026-03-25 09:15:00 Asia/Kolkata
    monkeypatch.setattr(mod.time, "time", lambda: market_open_ist)

    synthetic = mod._generate_synthetic_buckets("NIFTY", 300, 0.05, count=1)
    live = mod._live_buckets_to_response(
        [
            SimpleNamespace(
                timestamp_bin=market_open_ist,
                price_level=100.0,
                buy_volume=5,
                sell_volume=3,
                delta=2,
            )
        ],
        "NIFTY",
    )

    assert synthetic[0]["time_label"] == "09:15:00"
    assert live[0]["time_label"] == "09:15:00"


def test_orderflow_synthetic_reports_requested_interval(app):
    """The synthetic fallback genuinely honours the requested interval."""
    with app.test_client() as c:
        resp = c.get("/api/v1/data/orderflow?symbol=NIFTY&interval=900")
    data = resp.get_json()["data"]
    assert data["is_live"] is False
    assert data["interval"] == 900
    assert data["requested_interval"] == 900
