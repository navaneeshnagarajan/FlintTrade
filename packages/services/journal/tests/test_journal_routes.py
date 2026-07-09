"""Tests for the Trade Journal HTTP blueprint (journal_routes)."""

from __future__ import annotations

import pytest
from flask import Flask

from flinttrade_journal import journal_routes
from flinttrade_journal.trade_journal import TradeJournal

pytestmark = pytest.mark.unit


@pytest.fixture
def journal():
    j = TradeJournal(":memory:")
    j.initialise()
    yield j
    j.close()


@pytest.fixture
def app(journal):
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    journal_routes.init_journal_routes(journal)
    flask_app.register_blueprint(journal_routes.journal_bp)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def app_no_journal():
    journal_routes.init_journal_routes(None)  # type: ignore[arg-type]
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(journal_routes.journal_bp)
    return flask_app


_ENTRY = {
    "symbol": "BANKNIFTY",
    "exchange": "NFO",
    "side": "buy",
    "quantity": 25,
    "entry_price": 48000.0,
    "exit_price": 48500.0,
    "strategy": "momentum",
    "tags": ["breakout", "trending"],
    "notes": "Clean breakout above resistance.",
    "setup_quality": 4,
}


def _create(client, **overrides):
    body = {**_ENTRY, **overrides}
    return client.post("/api/v1/journal/entries", json=body)


def test_create_and_get_entry(client):
    resp = _create(client)
    assert resp.status_code == 201
    entry = resp.get_json()["data"]
    assert entry["symbol"] == "BANKNIFTY"
    assert entry["side"] == "BUY"  # normalised
    assert entry["pnl"] == pytest.approx(12500.0)

    got = client.get(f"/api/v1/journal/entries/{entry['id']}")
    assert got.status_code == 200
    assert got.get_json()["data"]["notes"] == "Clean breakout above resistance."


def test_create_rejects_invalid_body(client):
    assert client.post("/api/v1/journal/entries", json=[]).status_code == 400
    bad = _create(client, side="SHORT")  # fails model validation
    assert bad.status_code == 400
    assert bad.get_json()["status"] == "error"


def test_create_ignores_client_supplied_id(client):
    resp = _create(client, id="attacker-chosen", created_at="1999-01-01T00:00:00+05:30")
    assert resp.status_code == 201
    assert resp.get_json()["data"]["id"] != "attacker-chosen"


def test_list_and_filter(client):
    _create(client, symbol="BANKNIFTY", tags=["breakout"])
    _create(client, symbol="RELIANCE", tags=["reversal"], exit_price=None)
    all_resp = client.get("/api/v1/journal/entries")
    assert all_resp.status_code == 200
    assert all_resp.get_json()["data"]["total"] == 2

    filtered = client.get("/api/v1/journal/entries?symbol=RELIANCE")
    assert filtered.get_json()["data"]["total"] == 1

    tagged = client.get("/api/v1/journal/entries?tags=breakout")
    assert tagged.get_json()["data"]["total"] == 1


def test_update_entry(client):
    entry = _create(client).get_json()["data"]
    resp = client.patch(f"/api/v1/journal/entries/{entry['id']}", json={"notes": "revised"})
    assert resp.status_code == 200
    assert resp.get_json()["data"]["notes"] == "revised"


def test_update_missing_entry_404(client):
    resp = client.patch("/api/v1/journal/entries/ghost", json={"notes": "x"})
    assert resp.status_code == 404


def test_delete_entry(client):
    entry = _create(client).get_json()["data"]
    assert client.delete(f"/api/v1/journal/entries/{entry['id']}").status_code == 200
    assert client.get(f"/api/v1/journal/entries/{entry['id']}").status_code == 404


def test_search(client):
    _create(client, symbol="BANKNIFTY", notes="clean breakout above resistance")
    _create(client, symbol="RELIANCE", notes="faded the gap up", tags=["reversal"])
    resp = client.get("/api/v1/journal/search?q=breakout")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["total"] == 1
    assert data["entries"][0]["symbol"] == "BANKNIFTY"


def test_search_malformed_query_is_not_500(client):
    _create(client)
    resp = client.get('/api/v1/journal/search?q="unterminated')
    assert resp.status_code == 200
    assert isinstance(resp.get_json()["data"]["entries"], list)


def test_stats(client):
    _create(client, exit_price=48500.0)  # +12500 win
    resp = client.get("/api/v1/journal/stats")
    assert resp.status_code == 200
    stats = resp.get_json()["data"]
    assert stats["closed_entries"] == 1
    assert stats["win_rate"] == pytest.approx(100.0)


def test_export_csv(client):
    _create(client)
    resp = client.get("/api/v1/journal/export")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert "attachment" in resp.headers["Content-Disposition"]
    assert "symbol" in resp.get_data(as_text=True)


def test_import_tradebook(client):
    trades = [
        {"symbol": "HDFC", "exchange": "NSE", "action": "BUY", "quantity": "20",
         "price": "1600.0", "timestamp": "2026-04-07T11:00:00"},
    ]
    resp = client.post("/api/v1/journal/import", json={"trades": trades})
    assert resp.status_code == 201
    assert resp.get_json()["data"]["count"] == 1
    # Duplicate re-import is skipped.
    again = client.post("/api/v1/journal/import", json={"trades": trades})
    assert again.get_json()["data"]["count"] == 0


def test_endpoints_503_when_uninitialised(app_no_journal):
    with app_no_journal.test_client() as c:
        assert c.get("/api/v1/journal/entries").status_code == 503
        assert c.get("/api/v1/journal/search?q=x").status_code == 503
        assert c.get("/api/v1/journal/stats").status_code == 503
