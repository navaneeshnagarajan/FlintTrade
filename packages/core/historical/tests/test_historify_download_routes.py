"""Lightweight tests for the Historify download/status routes.

Registers only the ``historify_bp`` blueprint on a bare Flask app (not the full
``create_flask_app``, which requires auth/master-password setup), so the new
job-based download endpoints can be exercised in isolation.
"""

from __future__ import annotations

import pytest
from flask import Flask

import flinttrade_historical.watchlist_routes as wr
from flinttrade_historical.watchlist import DownloadWatchlist
from flinttrade_historical.watchlist_routes import historify_bp, init_watchlist_routes

pytestmark = pytest.mark.unit


@pytest.fixture
def client(tmp_path):
    app = Flask(__name__)
    app.register_blueprint(historify_bp)
    init_watchlist_routes(DownloadWatchlist(tmp_path / "wl.db"))
    wr._job_manager = None  # reset the singleton between tests  # noqa: SLF001
    return app.test_client()


def test_status_with_no_jobs_returns_empty_list(client):
    resp = client.get("/v1/historify/download/status")
    assert resp.status_code == 200
    assert resp.get_json()["data"] == []


def test_status_unknown_job_id_404(client):
    resp = client.get("/v1/historify/download/status?job_id=does-not-exist")
    assert resp.status_code == 404


def test_download_with_no_enabled_items_400(client):
    resp = client.post("/v1/historify/download", json={})
    assert resp.status_code == 400
    assert "enabled" in resp.get_json()["message"].lower()


def test_download_invalid_dates_400(client):
    wr._get_watchlist().add("NIFTY", "NSE_INDEX", "1d")  # noqa: SLF001 - enabled by default
    resp = client.post("/v1/historify/download", json={"start_date": "not-a-date"})
    assert resp.status_code == 400
    assert "iso" in resp.get_json()["message"].lower()
