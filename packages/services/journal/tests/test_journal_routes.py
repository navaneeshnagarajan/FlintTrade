"""Tests for the Trade Journal HTTP blueprint (journal_routes)."""

from __future__ import annotations

import pytest
from flask import Flask

from flinttrade_journal import journal_routes
from flinttrade_journal.trade_journal import TradeJournal

pytestmark = pytest.mark.unit


@pytest.fixture
def journal(tmp_path):
    j = TradeJournal(":memory:", screenshots_dir=tmp_path / "journal_screenshots")
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


def test_import_malformed_rows_returns_201_not_500(client):
    # Untrusted rows (non-dict, null side) must be skipped and reported, never
    # crash the route (the store validates per-row).
    resp = client.post(
        "/api/v1/journal/import",
        json={"trades": [123, None, {"symbol": "A", "action": None, "quantity": 1, "price": 1.0}]},
    )
    assert resp.status_code == 201
    assert resp.get_json()["data"]["count"] == 1  # only the valid dict row imports


def test_import_non_list_body_returns_400(client):
    assert client.post("/api/v1/journal/import", json={"trades": "nope"}).status_code == 400


# ---------------------------------------------------------------------------
# Daily notes
# ---------------------------------------------------------------------------


def test_daily_note_roundtrip(client):
    put = client.put("/api/v1/journal/notes/2026-07-20", json={"content": "Sat out the gap open."})
    assert put.status_code == 200
    saved = put.get_json()["data"]
    assert saved["date"] == "2026-07-20"
    assert saved["content"] == "Sat out the gap open."
    assert saved["updated_at"] is not None

    got = client.get("/api/v1/journal/notes/2026-07-20")
    assert got.status_code == 200
    assert got.get_json()["data"]["content"] == "Sat out the gap open."


def test_daily_note_missing_returns_empty_200(client):
    resp = client.get("/api/v1/journal/notes/2026-01-01")
    assert resp.status_code == 200
    assert resp.get_json()["data"] == {"date": "2026-01-01", "content": "", "updated_at": None}


def test_daily_note_empty_content_deletes(client):
    client.put("/api/v1/journal/notes/2026-07-20", json={"content": "temp"})
    resp = client.put("/api/v1/journal/notes/2026-07-20", json={"content": ""})
    assert resp.status_code == 200
    assert resp.get_json()["data"] == {"date": "2026-07-20", "content": "", "updated_at": None}
    # The row is gone: the read serves the empty record and the list omits it.
    assert client.get("/api/v1/journal/notes/2026-07-20").get_json()["data"]["updated_at"] is None
    assert client.get("/api/v1/journal/notes").get_json()["data"] == []


def test_daily_note_bad_date_400(client):
    assert client.get("/api/v1/journal/notes/2026-7-1").status_code == 400
    assert client.put("/api/v1/journal/notes/not-a-date", json={"content": "x"}).status_code == 400


def test_daily_note_date_uses_fullmatch_ascii_and_real_calendar(client):
    """Pins the _DATE_RE hardening: fullmatch + re.ASCII + date.fromisoformat.

    ``re.match`` + ``$`` accepts a trailing newline, ``\\d`` without
    ``re.ASCII`` accepts Unicode digits, and the regex alone accepts
    impossible dates — each previously created a daily_notes row under a key
    the NotesTab can never address.
    """
    bad_dates = [
        # Trailing newline, percent-encoded as a real HTTP client sends it —
        # Werkzeug decodes %0A to "\n" AFTER routing (a raw "\n" in the path
        # is stripped before routing and never reaches the handler).
        "2026-07-20%0A",
        "२०२६-०७-२०",  # Devanagari digits — \d matches these without re.ASCII
        "2026-99-99",  # regex-shaped but not a real calendar date
        "2026-02-30",  # regex-shaped but not a real calendar date
    ]
    for bad in bad_dates:
        put = client.put(f"/api/v1/journal/notes/{bad}", json={"content": "x"})
        assert put.status_code == 400, f"PUT accepted bad date {bad!r}"
        got = client.get(f"/api/v1/journal/notes/{bad}")
        assert got.status_code == 400, f"GET accepted bad date {bad!r}"
    # No DB write happened for any rejected key.
    assert client.get("/api/v1/journal/notes").get_json()["data"] == []
    # A genuine date still round-trips.
    assert client.put("/api/v1/journal/notes/2026-07-20", json={"content": "x"}).status_code == 200


def test_daily_note_rejects_non_string_and_oversize_content(client):
    assert client.put("/api/v1/journal/notes/2026-07-20", json={"content": 42}).status_code == 400
    big = client.put("/api/v1/journal/notes/2026-07-20", json={"content": "x" * 100_001})
    assert big.status_code == 400
    assert big.get_json()["status"] == "error"
    # Exactly at the cap is accepted.
    assert client.put("/api/v1/journal/notes/2026-07-20", json={"content": "x" * 100_000}).status_code == 200


def test_daily_notes_list_ordering_and_preview(client):
    client.put("/api/v1/journal/notes/2026-07-18", json={"content": "older note " * 20})
    client.put("/api/v1/journal/notes/2026-07-20", json={"content": "two words"})
    resp = client.get("/api/v1/journal/notes")
    assert resp.status_code == 200
    notes = resp.get_json()["data"]
    assert [n["date"] for n in notes] == ["2026-07-20", "2026-07-18"]
    assert notes[0]["word_count"] == 2
    assert notes[1]["preview"] == ("older note " * 20)[:120]
    assert len(notes[1]["preview"]) == 120
    assert all("content" not in n for n in notes)


# ---------------------------------------------------------------------------
# Trade-log screenshots
# ---------------------------------------------------------------------------


def _data_url(data: bytes = b"fake-png-bytes", content_type: str = "image/png") -> str:
    import base64

    return f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}"


def test_screenshot_roundtrip_and_file_on_disk(client, tmp_path):
    resp = client.post(
        "/api/v1/journal/screenshots",
        json={"trade_key": "2026-07-20T10:00:00|BANKNIFTY|123", "data_url": _data_url()},
    )
    assert resp.status_code == 201
    row = resp.get_json()["data"]
    assert row["trade_key"] == "2026-07-20T10:00:00|BANKNIFTY|123"
    assert row["content_type"] == "image/png"
    assert row["size"] == len(b"fake-png-bytes")
    assert row["data_url"] == _data_url()

    stored = tmp_path / "journal_screenshots" / f"{row['id']}.png"
    assert stored.read_bytes() == b"fake-png-bytes"

    listed = client.get("/api/v1/journal/screenshots")
    assert listed.status_code == 200
    rows = listed.get_json()["data"]
    assert len(rows) == 1
    assert rows[0]["id"] == row["id"]
    assert rows[0]["data_url"] == _data_url()


def test_screenshot_dedupe_returns_existing_with_200(client):
    body = {"trade_key": "k1", "data_url": _data_url()}
    first = client.post("/api/v1/journal/screenshots", json=body)
    assert first.status_code == 201
    again = client.post("/api/v1/journal/screenshots", json=body)
    assert again.status_code == 200
    assert again.get_json()["data"]["id"] == first.get_json()["data"]["id"]
    assert len(client.get("/api/v1/journal/screenshots").get_json()["data"]) == 1
    # Same bytes under a DIFFERENT trade key is a new row, not a dedupe.
    other = client.post("/api/v1/journal/screenshots", json={"trade_key": "k2", "data_url": _data_url()})
    assert other.status_code == 201


def test_screenshot_bad_content_type_400(client):
    svg = client.post(
        "/api/v1/journal/screenshots",
        json={"trade_key": "k1", "data_url": _data_url(content_type="image/svg+xml")},
    )
    assert svg.status_code == 400
    not_a_data_url = client.post(
        "/api/v1/journal/screenshots",
        json={"trade_key": "k1", "data_url": "https://example.invalid/x.png"},
    )
    assert not_a_data_url.status_code == 400


def test_screenshot_oversize_400(client):
    resp = client.post(
        "/api/v1/journal/screenshots",
        json={"trade_key": "k1", "data_url": _data_url(data=b"x" * (2 * 1024 * 1024 + 1))},
    )
    assert resp.status_code == 400
    assert "2 MiB" in resp.get_json()["message"]


def test_screenshot_invalid_inputs_400(client):
    assert client.post("/api/v1/journal/screenshots", json={"trade_key": "", "data_url": _data_url()}).status_code == 400
    long_key = "k" * 301
    assert (
        client.post("/api/v1/journal/screenshots", json={"trade_key": long_key, "data_url": _data_url()}).status_code
        == 400
    )
    assert client.post("/api/v1/journal/screenshots", json={"trade_key": "k1", "data_url": 7}).status_code == 400
    bad_b64 = client.post(
        "/api/v1/journal/screenshots",
        json={"trade_key": "k1", "data_url": "data:image/png;base64,%%not-base64%%"},
    )
    assert bad_b64.status_code == 400


def test_screenshot_get_single_roundtrip(client, tmp_path):
    """Pins GET /screenshots/<id> — the lazy per-image path (finding 8)."""
    row = client.post(
        "/api/v1/journal/screenshots",
        json={"trade_key": "k1", "data_url": _data_url()},
    ).get_json()["data"]
    got = client.get(f"/api/v1/journal/screenshots/{row['id']}")
    assert got.status_code == 200
    single = got.get_json()["data"]
    assert single["id"] == row["id"]
    assert single["trade_key"] == "k1"
    assert single["content_type"] == "image/png"
    assert single["size"] == len(b"fake-png-bytes")
    assert single["data_url"] == _data_url()


def test_screenshot_get_single_404_when_absent_or_file_missing(client, tmp_path):
    assert client.get("/api/v1/journal/screenshots/no-such-id").status_code == 404
    # A row whose file has gone missing on disk is also a 404, not a 500.
    row = client.post(
        "/api/v1/journal/screenshots",
        json={"trade_key": "k1", "data_url": _data_url()},
    ).get_json()["data"]
    (tmp_path / "journal_screenshots" / f"{row['id']}.png").unlink()
    assert client.get(f"/api/v1/journal/screenshots/{row['id']}").status_code == 404


def test_screenshot_delete_removes_file(client, tmp_path):
    row = client.post(
        "/api/v1/journal/screenshots",
        json={"trade_key": "k1", "data_url": _data_url()},
    ).get_json()["data"]
    stored = tmp_path / "journal_screenshots" / f"{row['id']}.png"
    assert stored.exists()
    assert client.delete(f"/api/v1/journal/screenshots/{row['id']}").status_code == 200
    assert not stored.exists()
    assert client.get("/api/v1/journal/screenshots").get_json()["data"] == []
    assert client.delete(f"/api/v1/journal/screenshots/{row['id']}").status_code == 404


def test_notes_and_screenshots_503_when_uninitialised(app_no_journal):
    with app_no_journal.test_client() as c:
        assert c.get("/api/v1/journal/notes").status_code == 503
        assert c.get("/api/v1/journal/notes/2026-07-20").status_code == 503
        assert c.put("/api/v1/journal/notes/2026-07-20", json={"content": "x"}).status_code == 503
        assert c.get("/api/v1/journal/screenshots").status_code == 503
        assert c.get("/api/v1/journal/screenshots/x").status_code == 503
        assert c.post("/api/v1/journal/screenshots", json={}).status_code == 503
        assert c.delete("/api/v1/journal/screenshots/x").status_code == 503
