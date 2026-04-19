"""Tests for packages/historical/src/historify_routes.py — bulk OHLCV downloader."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from flask import Flask

import packages.historical.src.historify_routes as mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mock_result() -> MagicMock:
    r = MagicMock()
    r.total = 3
    r.succeeded = 3
    r.failed = 0
    r.skipped = 0
    r.errors = []
    return r


def _mock_downloader() -> MagicMock:
    dl = MagicMock()
    dl.download_symbols = AsyncMock(return_value=_mock_result())
    dl.delta_sync = AsyncMock(return_value={"inserted": 120})
    dl.list_pending_jobs.return_value = ["NIFTY/NSE/1d"]
    return dl


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    mod.init_historify_routes(_mock_downloader())
    flask_app.register_blueprint(mod.historify_bulk_bp)
    # Reset module-level state
    mod._last_result = None
    mod._progress = {"completed": 0, "total": 0}
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# POST /admin/historify/download
# ---------------------------------------------------------------------------


def test_download_ok(client):
    """200 on valid download request."""
    with patch(
        "packages.historical.src.historify_routes._run_async",
        return_value=_mock_result(),
    ):
        resp = client.post(
            "/admin/historify/download",
            json={
                "symbols": [{"symbol": "NIFTY", "exchange": "NSE"}],
                "intervals": ["1d"],
            },
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["data"]["total"] == 3


def test_download_missing_symbols(client):
    """400 when symbols is empty."""
    resp = client.post(
        "/admin/historify/download",
        json={"symbols": [], "intervals": ["1d"]},
    )
    assert resp.status_code == 400


def test_download_no_downloader():
    """503 when downloader not initialised."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    # Reset singleton
    mod._downloader = None
    flask_app.register_blueprint(mod.historify_bulk_bp)
    with flask_app.test_client() as c:
        resp = c.post(
            "/admin/historify/download",
            json={"symbols": [{"symbol": "NIFTY"}], "intervals": ["1d"]},
        )
    assert resp.status_code == 503


def test_download_invalid_date(client):
    """400 for bad date format."""
    resp = client.post(
        "/admin/historify/download",
        json={
            "symbols": [{"symbol": "NIFTY"}],
            "intervals": ["1d"],
            "from_date": "not-a-date",
        },
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /admin/historify/status
# ---------------------------------------------------------------------------


def test_status_ok(client):
    """200 with progress and last_result."""
    resp = client.get("/admin/historify/status")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert "completed" in body["data"]
    assert "total" in body["data"]
