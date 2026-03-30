"""Tests for Historify watchlist Flask endpoints.

Run with:
    python -m pytest packages/historical/tests/test_watchlist_routes.py -v --import-mode=importlib
"""
from __future__ import annotations

import json

import pytest


_TEST_API_KEY = "test-watchlist-routes-key"


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch fixture."""
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def app_client(monkeypatch_module, tmp_path_factory):
    """Return a Flask test client with an in-memory watchlist."""
    from packages.core.src.app import create_flask_app
    from packages.historical.src.watchlist import DownloadWatchlist
    from packages.historical.src.watchlist_routes import init_watchlist_routes

    monkeypatch_module.setenv("OPENALGO_API_KEY", _TEST_API_KEY)

    db_path = tmp_path_factory.mktemp("wl") / "watchlist.db"
    watchlist = DownloadWatchlist(db_path)
    init_watchlist_routes(watchlist)

    flask_app = create_flask_app()
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


def _get(client, url):
    return client.get(url, headers={"X-API-Key": _TEST_API_KEY})


def _post(client, url, body=None):
    return client.post(
        url,
        data=json.dumps(body or {}),
        content_type="application/json",
        headers={"X-API-Key": _TEST_API_KEY},
    )


def _delete(client, url, body=None):
    return client.delete(
        url,
        data=json.dumps(body or {}),
        content_type="application/json",
        headers={"X-API-Key": _TEST_API_KEY},
    )


class TestWatchlistRoutes:

    def test_list_empty(self, app_client):
        resp = _get(app_client, "/v1/historify/watchlist")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "ok"
        assert isinstance(data["data"], list)

    def test_add_item(self, app_client):
        resp = _post(app_client, "/v1/historify/watchlist",
                     {"symbol": "RELIANCE", "exchange": "NSE", "interval": "1d"})
        assert resp.status_code == 201
        data = json.loads(resp.data)
        assert data["status"] == "ok"
        assert data["data"]["symbol"] == "RELIANCE"

    def test_list_after_add(self, app_client):
        resp = _get(app_client, "/v1/historify/watchlist")
        data = json.loads(resp.data)
        symbols = [item["symbol"] for item in data["data"]]
        assert "RELIANCE" in symbols

    def test_remove_item(self, app_client):
        _post(app_client, "/v1/historify/watchlist",
              {"symbol": "TEMPSTOCK", "exchange": "NSE"})
        resp = _delete(app_client, "/v1/historify/watchlist",
                       {"symbol": "TEMPSTOCK", "exchange": "NSE"})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "ok"

    def test_download_trigger_returns_ok(self, app_client):
        resp = _post(app_client, "/v1/historify/download",
                     {"start_date": "2026-01-01", "end_date": "2026-01-31"})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "ok"
        assert "triggered" in data["data"]
        assert "items" in data["data"]
