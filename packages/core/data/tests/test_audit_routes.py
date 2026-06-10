"""Tests for packages/core/data/src/audit_routes.py — local audit-trail endpoints."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from flask import Flask

import flinttrade_data.audit_routes as mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _entry(action: str = "order.place") -> MagicMock:
    e = MagicMock()
    e.log_id = "log-001"
    e.timestamp = datetime(2026, 4, 19, 10, 0, 0)
    e.action = action
    e.user = "admin"
    e.ip = "127.0.0.1"
    e.details = {}
    return e


def _mock_log(entries: list | None = None) -> MagicMock:
    log = MagicMock()
    log.query.return_value = entries or [_entry()]
    return log


def _audit_events() -> list[dict]:
    """Two events in append (oldest-first) order, as ``read_day`` returns them."""
    return [
        {
            "ts": "2026-04-19T10:00:00+05:30",
            "event_type": "SAFETY_CHECK",
            "layer": "L1",
            "verdict": "PASS",
            "reason": "",
            "symbol": "NIFTY",
            "exchange": "NSE_INDEX",
            "strategy": "sma-cross",
        },
        {
            "ts": "2026-04-19T10:00:01+05:30",
            "event_type": "ORDER_PLACED",
            "strategy": "sma-cross",
            "symbol": "NIFTY24APR22000CE",
            "exchange": "NFO",
            "action": "BUY",
            "quantity": "50",
            "price": "100.5",
        },
    ]


def _mock_audit(events: list[dict] | None = None) -> MagicMock:
    audit = MagicMock()
    audit.read_day.return_value = _audit_events() if events is None else events
    return audit


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.config["ACTIVITY_LOG"] = _mock_log()
    flask_app.config["AUDIT"] = _mock_audit()
    flask_app.register_blueprint(mod.audit_bp)
    return flask_app


@pytest.fixture()
def app_no_log():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.audit_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# GET /ft-api/v1/audit/log
# ---------------------------------------------------------------------------


def test_audit_log_ok(client):
    """200 with entries and pagination metadata."""
    resp = client.get("/v1/audit/log")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert "entries" in body["data"]
    assert "total" in body["data"]
    assert "pages" in body["data"]


def test_audit_log_no_log(app_no_log):
    """503 when ACTIVITY_LOG not configured."""
    with app_no_log.test_client() as c:
        resp = c.get("/v1/audit/log")
    assert resp.status_code == 503


def test_audit_log_bad_page(client):
    """400 for non-integer page."""
    resp = client.get("/v1/audit/log?page=abc")
    assert resp.status_code == 400


def test_audit_log_action_filter(client):
    """200 with action filter applied."""
    resp = client.get("/v1/audit/log?action=order.place")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /ft-api/v1/audit/export
# ---------------------------------------------------------------------------


def test_audit_export_ok(client):
    """200 CSV attachment."""
    resp = client.get("/v1/audit/export")
    assert resp.status_code == 200
    assert "text/csv" in resp.content_type


def test_audit_export_no_log(app_no_log):
    """503 when ACTIVITY_LOG not configured."""
    with app_no_log.test_client() as c:
        resp = c.get("/v1/audit/export")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# GET /ft-api/v1/audit/stats
# ---------------------------------------------------------------------------


def test_audit_stats_ok(client):
    """200 with by_action counts."""
    resp = client.get("/v1/audit/stats")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "by_action" in body["data"]
    assert "total" in body["data"]


def test_audit_stats_no_log(app_no_log):
    """503 when ACTIVITY_LOG not configured."""
    with app_no_log.test_client() as c:
        resp = c.get("/v1/audit/stats")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# GET /ft-api/v1/audit/events  (gated-execution audit — the Execution Logs viewer)
# ---------------------------------------------------------------------------


def test_audit_events_ok(client):
    """200 with the gated-execution shape, newest event first, numbers coerced."""
    resp = client.get("/v1/audit/events?date=2026-04-19")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    logs = body["data"]["logs"]
    assert body["data"]["total"] == 2
    # Newest-first: the later-appended ORDER_PLACED leads.
    assert logs[0]["event_type"] == "ORDER_PLACED"
    assert logs[0]["strategy"] == "sma-cross"
    assert logs[0]["symbol"] == "NIFTY24APR22000CE"
    # quantity/price coerced from stored strings to numbers (the TS contract).
    assert logs[0]["quantity"] == 50.0
    assert logs[0]["price"] == 100.5
    # Safety-check row carries layer/verdict and absent order fields default cleanly.
    assert logs[1]["event_type"] == "SAFETY_CHECK"
    assert logs[1]["layer"] == "L1"
    assert logs[1]["verdict"] == "PASS"
    assert logs[1]["quantity"] == 0.0


def test_audit_events_reads_requested_day(client, app):
    """The ``date`` query param is passed through to ``read_day``."""
    client.get("/v1/audit/events?date=2026-04-19")
    app.config["AUDIT"].read_day.assert_called_with("2026-04-19")


def test_audit_events_pagination(client, app):
    """``limit``/``offset`` page the newest-first list; ``total`` is the full count."""
    app.config["AUDIT"].read_day.return_value = [
        {"ts": f"2026-04-19T10:00:0{i}+05:30", "event_type": "ORDER_PLACED", "strategy": str(i)}
        for i in range(5)
    ]
    resp = client.get("/v1/audit/events?date=2026-04-19&limit=2&offset=0")
    body = resp.get_json()["data"]
    assert body["total"] == 5
    assert len(body["logs"]) == 2
    # Newest-first → offset 0 starts at the last-appended event (strategy "4").
    assert body["logs"][0]["strategy"] == "4"

    resp2 = client.get("/v1/audit/events?date=2026-04-19&limit=2&offset=4")
    body2 = resp2.get_json()["data"]
    assert len(body2["logs"]) == 1
    assert body2["logs"][0]["strategy"] == "0"


def test_audit_events_no_audit(app_no_log):
    """503 when AUDIT not configured."""
    with app_no_log.test_client() as c:
        resp = c.get("/v1/audit/events")
    assert resp.status_code == 503


def test_audit_events_bad_limit(client):
    """400 for a non-integer limit."""
    resp = client.get("/v1/audit/events?limit=abc")
    assert resp.status_code == 400


def test_audit_events_bad_offset(client):
    """400 for a non-integer offset."""
    resp = client.get("/v1/audit/events?offset=xyz")
    assert resp.status_code == 400


def test_audit_events_corrupt_day_is_empty(client, app):
    """A day file that fails to read yields an empty page, not a 500."""
    app.config["AUDIT"].read_day.side_effect = ValueError("corrupt hash chain")
    resp = client.get("/v1/audit/events?date=2026-04-19")
    assert resp.status_code == 200
    assert resp.get_json()["data"] == {"logs": [], "total": 0}
