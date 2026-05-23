"""Tests for packages/core/data/src/audit_routes.py — SEBI audit trail endpoints."""

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


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.config["ACTIVITY_LOG"] = _mock_log()
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
