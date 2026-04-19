"""Tests for packages/historical/src/contract_status_routes.py — master contract status."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from flask import Flask

import packages.historical.src.contract_status_routes as mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mock_status() -> MagicMock:
    svc = MagicMock()
    svc.all_statuses.return_value = [
        {
            "broker": "broker1",
            "exchange": "NSE",
            "last_sync_utc": "2026-04-19T05:30:00",
            "symbol_count": 2000,
            "checksum": "abc123",
        }
    ]
    svc.record_sync.return_value = None
    svc.last_sync.return_value = datetime(2026, 4, 19, 5, 30, 0, tzinfo=timezone.utc)
    svc.stale_contracts.return_value = [
        {"broker": "broker2", "exchange": "BSE", "last_sync_utc": None}
    ]
    return svc


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    mod.init_contract_status_routes(_mock_status())
    flask_app.register_blueprint(mod.contract_status_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# GET /admin/contracts/status
# ---------------------------------------------------------------------------


def test_all_statuses_ok(client):
    """200 with list of sync records."""
    resp = client.get("/admin/contracts/status")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert isinstance(body["data"], list)
    assert body["data"][0]["broker"] == "broker1"


# ---------------------------------------------------------------------------
# POST /admin/contracts/sync/<broker>/<exchange>
# ---------------------------------------------------------------------------


def test_record_sync_ok(client):
    """200 with updated sync record."""
    resp = client.post(
        "/admin/contracts/sync/broker1/NSE",
        json={"symbol_count": 2100, "checksum": "xyz789"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["data"]["broker"] == "broker1"
    assert body["data"]["exchange"] == "NSE"
    assert body["data"]["symbol_count"] == 2100


def test_record_sync_defaults(client):
    """200 with defaults when body is empty."""
    resp = client.post("/admin/contracts/sync/broker1/BSE", json={})
    assert resp.status_code == 200
    assert resp.get_json()["data"]["symbol_count"] == 0


# ---------------------------------------------------------------------------
# GET /admin/contracts/stale
# ---------------------------------------------------------------------------


def test_stale_contracts_ok(client):
    """200 with stale contracts list."""
    resp = client.get("/admin/contracts/stale")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert isinstance(body["data"], list)


def test_stale_contracts_invalid_max_age(client):
    """400 when max_age_hours is not integer."""
    resp = client.get("/admin/contracts/stale?max_age_hours=bad")
    assert resp.status_code == 400


def test_stale_contracts_below_min(client):
    """400 when max_age_hours < 1."""
    resp = client.get("/admin/contracts/stale?max_age_hours=0")
    assert resp.status_code == 400
