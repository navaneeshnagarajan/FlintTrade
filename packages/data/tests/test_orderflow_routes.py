"""Tests for packages/data/src/orderflow_routes.py — footprint / order flow endpoint."""

from __future__ import annotations

import pytest
from flask import Flask

import packages.data.src.orderflow_routes as mod


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
