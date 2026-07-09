"""Tests for packages/core/data/src/audit_routes.py — local audit-trail endpoints."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

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


# ---------------------------------------------------------------------------
# GET /ft-api/v1/audit/verify  (hash-chain tamper-evidence)
# ---------------------------------------------------------------------------


def test_audit_verify_ok(client, app):
    """The route surfaces the logger's verify_chain result verbatim."""
    app.config["AUDIT"].verify_chain.return_value = {"ok": True, "checked": 3, "break": None}
    resp = client.get("/v1/audit/verify")
    assert resp.status_code == 200
    assert resp.get_json()["data"] == {"ok": True, "checked": 3, "break": None}


def test_audit_verify_reports_break(client, app):
    """A detected tamper is reported as ok=false with the break location."""
    brk = {"file": "audit_2026-04-19.jsonl", "line": 1, "seq": 1, "reason": "tampered"}
    app.config["AUDIT"].verify_chain.return_value = {"ok": False, "checked": 1, "break": brk}
    resp = client.get("/v1/audit/verify")
    assert resp.status_code == 200
    body = resp.get_json()["data"]
    assert body["ok"] is False
    assert body["break"]["seq"] == 1


def test_audit_verify_no_log(app_no_log):
    """503 when the audit logger is not initialised."""
    with app_no_log.test_client() as c:
        resp = c.get("/v1/audit/verify")
    assert resp.status_code == 503


def test_audit_verify_run_failure_is_500(client, app):
    """If verification itself raises, the route returns 500, not a stack trace."""
    app.config["AUDIT"].verify_chain.side_effect = RuntimeError("disk gone")
    resp = client.get("/v1/audit/verify")
    assert resp.status_code == 500
    assert resp.get_json()["status"] == "error"


# ---------------------------------------------------------------------------
# GET /ft-api/v1/audit/events/export  (gated-execution audit CSV/PDF range export)
# ---------------------------------------------------------------------------


def test_audit_events_export_csv_ok(client, app):
    """200 CSV attachment built from the gated audit over a day range."""
    resp = client.get("/v1/audit/events/export?format=csv&from=2026-04-19&to=2026-04-19")
    assert resp.status_code == 200
    assert "text/csv" in resp.content_type
    assert "attachment" in resp.headers["Content-Disposition"]
    # The exporter read the requested day from the gated AuditLogger.
    app.config["AUDIT"].read_day.assert_called_with("2026-04-19")
    body = resp.get_data(as_text=True)
    assert "event_type" in body  # CSV header
    assert "ORDER_PLACED" in body


def test_audit_events_export_defaults_to_csv(client):
    """No format param defaults to CSV."""
    resp = client.get("/v1/audit/events/export?from=2026-04-19&to=2026-04-19")
    assert resp.status_code == 200
    assert "text/csv" in resp.content_type


def test_audit_events_export_pdf_error_is_500(client):
    """A PDF export failure (e.g. reportlab absent) surfaces as 500, not a stack trace."""
    from flinttrade_data.audit_export import AuditExportError

    with patch(
        "flinttrade_data.audit_export.AuditExporter.to_pdf",
        side_effect=AuditExportError("reportlab unavailable"),
    ):
        resp = client.get("/v1/audit/events/export?format=pdf&from=2026-04-19&to=2026-04-19")
    assert resp.status_code == 500
    assert resp.get_json()["status"] == "error"


def test_audit_events_export_pdf_ok_when_reportlab_present(client):
    """When reportlab is installed the PDF branch streams an application/pdf attachment."""
    pytest.importorskip("reportlab")
    resp = client.get("/v1/audit/events/export?format=pdf&from=2026-04-19&to=2026-04-19")
    assert resp.status_code == 200
    assert "application/pdf" in resp.content_type
    assert resp.get_data()[:4] == b"%PDF"


def test_audit_events_export_missing_dates_400(client):
    """Missing 'from'/'to' returns 400."""
    assert client.get("/v1/audit/events/export?format=csv").status_code == 400
    assert client.get("/v1/audit/events/export?from=2026-04-19").status_code == 400


def test_audit_events_export_inverted_dates_400(client):
    """'from' after 'to' returns 400."""
    resp = client.get("/v1/audit/events/export?from=2026-04-30&to=2026-04-01")
    assert resp.status_code == 400
    assert "on or before" in resp.get_json()["message"]


def test_audit_events_export_bad_date_format_400(client):
    """A non-ISO date returns 400."""
    resp = client.get("/v1/audit/events/export?from=19-04-2026&to=2026-04-30")
    assert resp.status_code == 400


def test_audit_events_export_bad_format_400(client):
    """An unsupported format returns 400."""
    resp = client.get("/v1/audit/events/export?format=xlsx&from=2026-04-19&to=2026-04-19")
    assert resp.status_code == 400


def test_audit_events_export_no_audit_503(app_no_log):
    """503 when the gated AuditLogger is not configured."""
    with app_no_log.test_client() as c:
        resp = c.get("/v1/audit/events/export?format=csv&from=2026-04-19&to=2026-04-19")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# GET /ft-api/v1/audit/events/summary  (gated-execution audit stats)
# ---------------------------------------------------------------------------


def test_audit_events_summary_ok(client):
    """200 with the gated-audit summary stats over a day range."""
    resp = client.get("/v1/audit/events/summary?from=2026-04-19&to=2026-04-19")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    data = body["data"]
    # _audit_events(): one SAFETY_CHECK (PASS) + one ORDER_PLACED.
    assert data["total_events"] == 2
    assert data["orders_placed"] == 1
    assert data["orders_rejected"] == 0
    assert data["events_by_type"]["ORDER_PLACED"] == 1


def test_audit_events_summary_missing_dates_400(client):
    """Missing dates on the summary endpoint returns 400."""
    assert client.get("/v1/audit/events/summary").status_code == 400


def test_audit_events_summary_inverted_dates_400(client):
    """'from' after 'to' on the summary endpoint returns 400."""
    resp = client.get("/v1/audit/events/summary?from=2026-05-01&to=2026-04-01")
    assert resp.status_code == 400


def test_audit_events_summary_no_audit_503(app_no_log):
    """503 when the gated AuditLogger is not configured."""
    with app_no_log.test_client() as c:
        resp = c.get("/v1/audit/events/summary?from=2026-04-19&to=2026-04-19")
    assert resp.status_code == 503


def test_audit_events_export_corrupt_day_is_controlled_500(client, app):
    """A corrupt/tampered day file (read_day raises) is a controlled 500, not an uncaught escape."""
    app.config["AUDIT"].read_day.side_effect = ValueError("corrupt hash chain")
    resp = client.get("/v1/audit/events/export?format=csv&from=2026-04-19&to=2026-04-19")
    assert resp.status_code == 500
    assert resp.get_json()["status"] == "error"


def test_audit_events_summary_corrupt_day_is_controlled_500(client, app):
    """A corrupt/tampered day file surfaces as a controlled 500 on the summary route too."""
    app.config["AUDIT"].read_day.side_effect = ValueError("corrupt hash chain")
    resp = client.get("/v1/audit/events/summary?from=2026-04-19&to=2026-04-19")
    assert resp.status_code == 500
    assert resp.get_json()["status"] == "error"


def test_audit_events_export_range_too_wide_400(client):
    """A range beyond the max span (guards against a fat-fingered to=9999-...) returns 400."""
    resp = client.get("/v1/audit/events/export?format=csv&from=2020-01-01&to=2026-01-01")
    assert resp.status_code == 400
    assert "exceed" in resp.get_json()["message"]


def test_audit_events_summary_range_too_wide_400(client):
    """The span cap applies to the summary endpoint via the shared helper."""
    resp = client.get("/v1/audit/events/summary?from=0001-01-01&to=9999-12-31")
    assert resp.status_code == 400
