"""Tests for packages/historical/src/expiry_tracker_routes.py — historical expiry chain."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from flask import Flask

import packages.historical.src.expiry_tracker_routes as mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mock_tracker() -> MagicMock:
    tracker = MagicMock()
    tracker.list_expiries.return_value = ["260327", "260424", "260529"]
    tracker.get_historical_chain.return_value = [
        {
            "strike": 22000,
            "option_type": "CE",
            "oi": 1200000,
            "volume": 85000,
            "ltp": 250.5,
            "iv": 0.18,
        }
    ]
    return tracker


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    mod.init_expiry_tracker_routes(_mock_tracker())
    flask_app.register_blueprint(mod.expiry_tracker_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# GET /api/v1/historical/expiries/<symbol>
# ---------------------------------------------------------------------------


def test_list_expiries_ok(client):
    """200 with expiry list."""
    resp = client.get("/api/v1/historical/expiries/NIFTY")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["data"]["symbol"] == "NIFTY"
    assert "260327" in body["data"]["expiries"]


def test_list_expiries_custom_exchange(client):
    """200 with custom exchange param."""
    resp = client.get("/api/v1/historical/expiries/RELIANCE?exchange=NSE")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["exchange"] == "NSE"


def test_list_expiries_symbol_uppercased(client):
    """Symbol is uppercased in response."""
    resp = client.get("/api/v1/historical/expiries/nifty")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["symbol"] == "NIFTY"


# ---------------------------------------------------------------------------
# GET /api/v1/historical/chain/<symbol>/<expiry>
# ---------------------------------------------------------------------------


def test_historical_chain_ok(client):
    """200 with chain data for NIFTY 260327."""
    resp = client.get("/api/v1/historical/chain/NIFTY/260327")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["data"]["symbol"] == "NIFTY"
    assert body["data"]["expiry"] == "260327"
    assert isinstance(body["data"]["chain"], list)
    assert body["data"]["chain"][0]["strike"] == 22000


def test_historical_chain_exchange_param(client):
    """200 with custom exchange query param."""
    resp = client.get("/api/v1/historical/chain/BANKNIFTY/260327?exchange=NSE")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["exchange"] == "NSE"
