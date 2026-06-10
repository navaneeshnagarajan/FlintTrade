"""Tests for packages/services/screener/src/breadth_routes.py — market breadth & vol cone endpoints."""

from __future__ import annotations


import pytest
from flask import Flask

import flinttrade_screener.breadth_routes as mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.breadth_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# GET /ft-api/v1/breadth/current
# ---------------------------------------------------------------------------


def test_breadth_current_ok(client):
    """200 with breadth snapshot."""
    resp = client.get("/v1/breadth/current")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    data = body["data"]
    assert "advances" in data or "ad_ratio" in data


class _Quote:
    def __init__(self, ltp: float, prev_close: float) -> None:
        self.ltp = ltp
        self.prev_close = prev_close


class _FakeBridgeClient:
    """Returns a deterministic NIFTY-50 quote sweep (30 up / 18 down / 2 flat)."""

    async def multi_quotes(self, payload):
        quotes = []
        for i in range(50):
            if i < 30:
                quotes.append(_Quote(ltp=101.0, prev_close=100.0))
            elif i < 48:
                quotes.append(_Quote(ltp=99.0, prev_close=100.0))
            else:
                quotes.append(_Quote(ltp=100.0, prev_close=100.0))
        return quotes


class _ConnectedRegistry:
    @staticmethod
    def is_connected() -> bool:
        return True


def test_breadth_current_live_from_quote_sweep(app):
    """With a connected broker, breadth is COMPUTED from a real quote sweep —
    the old live branch called a registry method that does not exist, so the
    connected path was dead code and is_sample_data could never go false."""
    app.config["REGISTRY"] = _ConnectedRegistry()
    app.config["OPENALGO_CLIENT"] = _FakeBridgeClient()
    with app.test_client() as c:
        resp = c.get("/v1/breadth/current")
    body = resp.get_json()
    assert body["is_sample_data"] is False
    assert body["data"]["advances"] == 30
    assert body["data"]["declines"] == 18
    assert body["data"]["unchanged"] == 2
    # Derived multi-day / 52-week indicators are NOT computable from a single
    # live snapshot — reported null, never as live 0s (the audit's honesty fix).
    for field in ("ad_line", "mcclellan_oscillator", "breadth_thrust", "new_highs", "new_lows"):
        assert body["data"][field] is None


def test_breadth_current_falls_back_to_sample_when_sweep_fails(app):
    class _FailingClient:
        async def multi_quotes(self, payload):
            raise RuntimeError("bridge down")

    app.config["REGISTRY"] = _ConnectedRegistry()
    app.config["OPENALGO_CLIENT"] = _FailingClient()
    with app.test_client() as c:
        resp = c.get("/v1/breadth/current")
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["is_sample_data"] is True


def test_breadth_current_refuses_thin_sweep_as_live(app):
    """A handful of quotes is not market breadth — stays honestly sample."""

    class _ThinClient:
        async def multi_quotes(self, payload):
            return [_Quote(101.0, 100.0) for _ in range(3)]

    app.config["REGISTRY"] = _ConnectedRegistry()
    app.config["OPENALGO_CLIENT"] = _ThinClient()
    with app.test_client() as c:
        resp = c.get("/v1/breadth/current")
    assert resp.get_json()["is_sample_data"] is True


# ---------------------------------------------------------------------------
# GET /ft-api/v1/breadth/history
# ---------------------------------------------------------------------------


def test_breadth_history_ok(client):
    """200 with list of historical breadth data."""
    resp = client.get("/v1/breadth/history?days=10")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert isinstance(body["data"], list)


def test_breadth_history_default_days(client):
    """200 with default days parameter."""
    resp = client.get("/v1/breadth/history")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /ft-api/v1/analytics/volcone
# ---------------------------------------------------------------------------


def test_volcone_ok(client):
    """200 with vol cone data for a valid return series."""
    returns = [0.01, -0.005, 0.008, 0.003, -0.002] * 20
    resp = client.post(
        "/v1/analytics/volcone",
        json={"returns": returns},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"


def test_volcone_missing_returns(client):
    """400 or sample data when returns absent (depends on implementation)."""
    resp = client.post("/v1/analytics/volcone", json={})
    # Either 400 validation or 200 with sample data
    assert resp.status_code in {200, 400}
