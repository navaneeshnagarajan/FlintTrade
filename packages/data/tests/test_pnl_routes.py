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


@pytest.fixture  # function-scoped (default)
def app_client(monkeypatch_module):
    """Flask test client with a freshly-populated PnLTracker per test.

    **Why function-scope, not module-scope:**

    The module-level ``test_init_pnl_routes`` test deliberately swaps the
    ``pnl_routes._tracker`` global. Under pytest-randomly, function order
    inside a module is shuffled. With a module-scoped fixture the
    populated tracker was set up *once*, then ``test_init_pnl_routes``
    could run later in the same session and restore the global to its
    pre-fixture state (an empty tracker captured at module-import time),
    leaving the next ``TestPnLRoutes::test_*`` to query an empty series
    — which is how CI run 26128153265 surfaced ``assert 0 >= 1``.
    Function-scope re-binds ``init_pnl_routes(populated_tracker)`` before
    every test, so the swap-test can't poison the others.
    """
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


def test_init_pnl_routes():
    from packages.data.src.pnl_tracker import PnLTracker
    from packages.data.src.pnl_routes import init_pnl_routes
    import packages.data.src.pnl_routes as pnl_routes

    old_tracker = pnl_routes._tracker
    new_tracker = PnLTracker()
    try:
        init_pnl_routes(new_tracker)
        assert pnl_routes._tracker is new_tracker
    finally:
        init_pnl_routes(old_tracker)


class TestPnLRoutes:

    def test_series_returns_ok(self, app_client):
        resp = _get(app_client, "/api/v1/pnl-tracker")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "success"
        assert isinstance(data["data"], list)
        # The function-scoped app_client fixture seeds one trade per test,
        # so the series must always have at least the one synthetic point.
        # A regression that drops the seed (e.g. tracker.update() no longer
        # generating a series tick) would surface here, not silently.
        assert len(data["data"]) >= 1

    def test_series_point_fields(self, app_client):
        resp = _get(app_client, "/api/v1/pnl-tracker")
        data = json.loads(resp.data)
        point = data["data"][0]
        assert "timestamp" in point
        assert "realized_pnl" in point
        assert "unrealized_pnl" in point
        assert "total_pnl" in point
        assert "trade_count" in point

    def test_summary_returns_ok(self, app_client):
        resp = _get(app_client, "/api/v1/pnl-tracker/summary")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "success"
        assert "realized" in data["data"]
        assert "unrealized" in data["data"]
        assert "total" in data["data"]
        assert "max_total" in data["data"]
        assert "min_total" in data["data"]
        assert "trade_count" in data["data"]
        assert data["data"]["data_points"] >= 1

    def test_summary_empty_tracker(self, app_client):
        import packages.data.src.pnl_routes as pnl_routes
        pnl_routes._tracker.reset()

        resp = _get(app_client, "/api/v1/pnl-tracker/summary")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "success"
        assert data["data"]["realized"] == 0.0
        assert data["data"]["unrealized"] == 0.0
        assert data["data"]["total"] == 0.0
        assert data["data"]["max_total"] == 0.0
        assert data["data"]["min_total"] == 0.0
        assert data["data"]["trade_count"] == 0
        assert data["data"]["data_points"] == 0

    def test_series_since_filter(self, app_client):
        import time
        future_ts = time.time() + 9999
        resp = _get(app_client, f"/api/v1/pnl-tracker?since={future_ts}")
        data = json.loads(resp.data)
        assert data["status"] == "success"
        assert data["data"] == []

    def test_series_since_filter_invalid(self, app_client):
        resp = _get(app_client, "/api/v1/pnl-tracker?since=invalid")
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert data["status"] == "error"
        assert data["message"] == "since must be a float"
