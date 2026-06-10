"""Tests for Historify watchlist Flask endpoints.

Run with:
    python -m pytest packages/core/historical/tests/test_watchlist_routes.py -v --import-mode=importlib
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
    from flinttrade_core.app import create_flask_app
    from flinttrade_historical.watchlist import DownloadWatchlist
    from flinttrade_historical.watchlist_routes import init_watchlist_routes

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
        assert data["status"] == "success"
        assert isinstance(data["data"], list)

    def test_add_item(self, app_client):
        resp = _post(app_client, "/v1/historify/watchlist",
                     {"symbol": "RELIANCE", "exchange": "NSE", "interval": "1d"})
        assert resp.status_code == 201
        data = json.loads(resp.data)
        assert data["status"] == "success"
        assert data["data"]["symbol"] == "RELIANCE"

    def test_list_after_add(self, app_client):
        # Self-contained: add RELIANCE here too, don't rely on test_add_item
        # having executed first. Under pytest-randomly, test ordering inside
        # the class is shuffled and this test was running BEFORE test_add_item
        # in CI, leaving an empty watchlist and `assert 'RELIANCE' in []`.
        _post(app_client, "/v1/historify/watchlist",
              {"symbol": "RELIANCE", "exchange": "NSE", "interval": "1d"})
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
        assert data["status"] == "success"

    def test_download_trigger_starts_job(self, app_client, monkeypatch):
        """POST /download starts a background job and returns its snapshot (202).

        Self-contained: seeds an enabled watchlist item first (test ordering is
        shuffled under pytest-randomly), and stubs the job manager so no real
        download thread spawns.
        """
        import flinttrade_historical.watchlist_routes as wr

        _post(app_client, "/v1/historify/watchlist",
              {"symbol": "RELIANCE", "exchange": "NSE", "interval": "1d"})

        captured: dict = {}

        class _StubJob:
            status = "running"

            @staticmethod
            def to_dict():
                return {"job_id": "stub-1", "status": "running", "total": captured.get("total")}

        class _StubManager:
            @staticmethod
            def start(*, total, runner, storage_path):
                captured["total"] = total
                captured["storage_path"] = storage_path
                return _StubJob()

        monkeypatch.setattr(wr, "_job_manager", _StubManager())

        resp = _post(app_client, "/v1/historify/download",
                     {"start_date": "2026-01-01", "end_date": "2026-01-31"})
        assert resp.status_code == 202
        data = json.loads(resp.data)
        assert data["status"] == "success"
        assert data["data"]["job_id"] == "stub-1"
        assert data["data"]["status"] == "running"
        assert captured["total"] >= 1
