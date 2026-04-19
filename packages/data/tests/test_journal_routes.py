"""Tests for packages/data/src/journal_routes.py — Trade Journal CRUD endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from flask import Flask

import packages.data.src.journal_routes as mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_ENTRY_DICT = {
    "id": "ent-001",
    "symbol": "NIFTY",
    "exchange": "NSE",
    "side": "BUY",
    "quantity": 50,
    "entry_price": 22000.0,
    "strategy": "scalper",
    "tags": [],
}


def _mock_journal() -> MagicMock:
    journal = MagicMock()
    journal.add_entry.return_value = "ent-001"

    entry_mock = MagicMock()
    entry_mock.model_dump.return_value = _ENTRY_DICT

    journal.get_entry.return_value = entry_mock
    journal.list_entries.return_value = [entry_mock]
    journal.update_entry.return_value = entry_mock
    journal.delete_entry.return_value = True

    stats_mock = MagicMock()
    stats_mock.model_dump.return_value = {"total_trades": 5, "win_rate": 0.6}
    journal.get_stats.return_value = stats_mock

    journal.export_csv.return_value = "symbol,side\nNIFTY,BUY\n"
    journal.import_from_tradebook.return_value = ["ent-001", "ent-002"]
    return journal


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    mod.init_journal_routes(_mock_journal())
    flask_app.register_blueprint(mod.journal_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# POST /ft-api/v1/journal/
# ---------------------------------------------------------------------------


def test_create_entry_ok(client):
    """201 with entry id on valid payload."""
    payload = {
        "symbol": "NIFTY",
        "exchange": "NSE",
        "side": "BUY",
        "quantity": 50,
        "entry_price": 22000.0,
    }
    resp = client.post("/ft-api/v1/journal/", json=payload)
    assert resp.status_code == 201
    assert resp.get_json()["data"]["id"] == "ent-001"


def test_create_entry_no_body(client):
    """400 when no JSON body."""
    resp = client.post("/ft-api/v1/journal/", content_type="application/json")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /ft-api/v1/journal/
# ---------------------------------------------------------------------------


def test_list_entries_ok(client):
    """200 with entries list."""
    resp = client.get("/ft-api/v1/journal/")
    assert resp.status_code == 200
    assert isinstance(resp.get_json()["data"], list)


def test_list_entries_invalid_limit(client):
    """400 when limit is not an integer."""
    resp = client.get("/ft-api/v1/journal/?limit=bad")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /ft-api/v1/journal/stats
# ---------------------------------------------------------------------------


def test_get_stats_ok(client):
    """200 with stats dict."""
    resp = client.get("/ft-api/v1/journal/stats")
    assert resp.status_code == 200
    assert "total_trades" in resp.get_json()["data"]


# ---------------------------------------------------------------------------
# GET /ft-api/v1/journal/export
# ---------------------------------------------------------------------------


def test_export_csv_ok(client):
    """200 CSV attachment."""
    resp = client.get("/ft-api/v1/journal/export")
    assert resp.status_code == 200
    assert "text/csv" in resp.content_type


# ---------------------------------------------------------------------------
# GET /ft-api/v1/journal/<id>
# ---------------------------------------------------------------------------


def test_get_entry_ok(client):
    """200 with entry dict."""
    resp = client.get("/ft-api/v1/journal/ent-001")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["symbol"] == "NIFTY"


def test_get_entry_not_found(app):
    """404 when entry absent."""
    journal = _mock_journal()
    journal.get_entry.return_value = None
    mod.init_journal_routes(journal)

    with app.test_client() as c:
        resp = c.get("/ft-api/v1/journal/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /ft-api/v1/journal/<id>
# ---------------------------------------------------------------------------


def test_update_entry_ok(client):
    """200 with updated entry."""
    resp = client.patch(
        "/ft-api/v1/journal/ent-001",
        json={"exit_price": 22100.0},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# DELETE /ft-api/v1/journal/<id>
# ---------------------------------------------------------------------------


def test_delete_entry_ok(client):
    """200 with deleted=true."""
    resp = client.delete("/ft-api/v1/journal/ent-001")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["deleted"] is True


def test_delete_entry_not_found(app):
    """404 when entry not found."""
    journal = _mock_journal()
    journal.delete_entry.return_value = False
    mod.init_journal_routes(journal)

    with app.test_client() as c:
        resp = c.delete("/ft-api/v1/journal/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /ft-api/v1/journal/import
# ---------------------------------------------------------------------------


def test_import_tradebook_ok(client):
    """201 with created count."""
    resp = client.post(
        "/ft-api/v1/journal/import",
        json={"trades": [{"symbol": "NIFTY", "tradetype": "BUY"}]},
    )
    assert resp.status_code == 201
    assert resp.get_json()["data"]["created"] == 2


def test_import_tradebook_missing_trades(client):
    """400 when trades key absent."""
    resp = client.post("/ft-api/v1/journal/import", json={})
    assert resp.status_code == 400
