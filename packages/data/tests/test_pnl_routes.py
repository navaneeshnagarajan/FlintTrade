"""Tests for P&L tracker Flask endpoints.

Run with:
    python -m pytest packages/data/tests/test_pnl_routes.py -v --import-mode=importlib
"""
from __future__ import annotations

import json

import pytest


_TEST_API_KEY = "test-pnl-routes-key"


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch fixture."""
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def app_client(monkeypatch_module):
    """Return a Flask test client with a pre-populated PnLTracker."""
    from packages.core.src.app import create_flask_app
    from packages.data.src.pnl_tracker import PnLTracker
    from packages.data.src.pnl_routes import init_pnl_routes

    monkeypatch_module.setenv("OPENALGO_API_KEY", _TEST_API_KEY)

    tracker = PnLTracker()
    trades = [{"action": "BUY", "quantity": 10, "entry_price": 100.0, "exit_price": 110.0}]
    tracker.update(trades, [], {})

    init_pnl_routes(tracker)

    flask_app = create_flask_app()
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


def _get(client, url):
    return client.get(url, headers={"X-API-Key": _TEST_API_KEY})


class TestPnLRoutes:

    def test_series_returns_ok(self, app_client):
        resp = _get(app_client, "/ft-api/v1/pnl-tracker")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "ok"
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 1

    def test_series_point_fields(self, app_client):
        resp = _get(app_client, "/ft-api/v1/pnl-tracker")
        data = json.loads(resp.data)
        point = data["data"][0]
        assert "timestamp" in point
        assert "realized_pnl" in point
        assert "unrealized_pnl" in point
        assert "total_pnl" in point
        assert "trade_count" in point

    def test_summary_returns_ok(self, app_client):
        resp = _get(app_client, "/ft-api/v1/pnl-tracker/summary")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "ok"
        assert "realized" in data["data"]
        assert "total" in data["data"]
        assert data["data"]["data_points"] >= 1

    def test_series_since_filter(self, app_client):
        import time
        future_ts = time.time() + 9999
        resp = _get(app_client, f"/ft-api/v1/pnl-tracker?since={future_ts}")
        data = json.loads(resp.data)
        assert data["status"] == "ok"
        assert data["data"] == []

    def test_init_pnl_routes(self, monkeypatch):
        from packages.data.src.pnl_routes import init_pnl_routes
        from packages.data.src.pnl_tracker import PnLTracker
        import packages.data.src.pnl_routes as pnl_routes_module

        tracker = PnLTracker()
        monkeypatch.setattr(pnl_routes_module, "_tracker", None)
        init_pnl_routes(tracker)
        assert pnl_routes_module._tracker is tracker

    def test_series_since_invalid(self, app_client):
        resp = _get(app_client, "/ft-api/v1/pnl-tracker?since=abc")
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert data["status"] == "error"
        assert "since must be a float" in data["message"]
