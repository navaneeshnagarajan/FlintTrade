"""Tests for packages/core/historical/src/expiry_tracker_routes.py — historical expiry chain."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from flask import Flask

import flinttrade_historical.expiry_tracker_routes as mod


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
    tracker.capture_snapshot.return_value = 2
    tracker.last_capture_error = None
    return tracker


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    tracker = _mock_tracker()
    flask_app.config["TRACKER"] = tracker
    mod.init_expiry_tracker_routes(tracker)
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
    assert body["data"]["expiry"] == "2026-03-27"
    assert isinstance(body["data"]["chain"], list)
    assert body["data"]["chain"][0]["strike"] == 22000


def test_historical_chain_exchange_param(client):
    """200 with custom exchange query param."""
    resp = client.get("/api/v1/historical/chain/BANKNIFTY/260327?exchange=NSE")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["exchange"] == "NSE"


# ---------------------------------------------------------------------------
# POST /api/v1/historical/chain/<symbol>/<expiry>/capture
# ---------------------------------------------------------------------------


def test_capture_historical_chain_ok(client):
    """200 with capture result and rows inserted."""
    resp = client.post("/api/v1/historical/chain/nifty/260327/capture")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["data"] == {
        "symbol": "NIFTY",
        "expiry": "2026-03-27",
        "exchange": "NFO",
        "rows_inserted": 2,
        "captured": True,
    }
    client.application.config["TRACKER"].capture_snapshot.assert_called_with("NIFTY", "260327", "NFO")


def test_capture_historical_chain_body_exchange(client):
    """Capture accepts the exchange in the JSON body."""
    resp = client.post(
        "/api/v1/historical/chain/sensex/260327/capture",
        json={"exchange": "bfo"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"]["symbol"] == "SENSEX"
    assert body["data"]["exchange"] == "BFO"
    client.application.config["TRACKER"].capture_snapshot.assert_called_with("SENSEX", "260327", "BFO")


def test_capture_historical_chain_reports_capture_failure(client):
    """Upstream broker/OpenAlgo failures are surfaced to the caller."""
    tracker = client.application.config["TRACKER"]
    tracker.capture_snapshot.return_value = 0
    tracker.last_capture_error = "[403] optionchain: Authentication failed"

    resp = client.post("/api/v1/historical/chain/NIFTY/260327/capture")

    assert resp.status_code == 502
    body = resp.get_json()
    assert body["status"] == "error"
    assert body["data"]["captured"] is False
    assert body["data"]["rows_inserted"] == 0


# ---------------------------------------------------------------------------
# Lazy tracker wiring — hot-reload safety
# ---------------------------------------------------------------------------


def test_get_tracker_wires_the_client_provider_not_an_instance(monkeypatch):
    """The lazy tracker must receive the ``get_openalgo_client`` PROVIDER.

    Provider wiring keeps the tracker on the authoritative shared client even
    if startup fallback replaces it. Normal settings hot-reload reconfigures
    the shared object in place.
    """
    captured: dict[str, object] = {}

    class _StubTracker:
        def __init__(self, client=None, **_kwargs):
            captured["client"] = client

    monkeypatch.setattr(mod, "ExpiryTracker", _StubTracker)
    monkeypatch.setattr(mod, "_tracker", None)

    mod._get_tracker()

    assert captured["client"] is mod.get_openalgo_client
