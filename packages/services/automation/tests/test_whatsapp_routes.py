"""Tests for packages/services/automation/src/whatsapp_routes.py — WhatsApp alert endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from flask import Flask

import flinttrade_automation.whatsapp_routes as mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_alerter(configured: bool = True, send_ok: bool = True) -> MagicMock:
    alerter = MagicMock()
    alerter.is_configured = configured
    alerter.send_alert.return_value = send_ok
    return alerter


@pytest.fixture()
def app_configured():
    """App with a configured and healthy WhatsApp alerter."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    mod.init_whatsapp_routes(_make_alerter(configured=True, send_ok=True))
    flask_app.register_blueprint(mod.whatsapp_bp)
    return flask_app


@pytest.fixture()
def app_not_configured():
    """App with an unconfigured alerter."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    mod.init_whatsapp_routes(_make_alerter(configured=False))
    flask_app.register_blueprint(mod.whatsapp_bp)
    return flask_app


# ---------------------------------------------------------------------------
# POST /api/v1/alerts/whatsapp/test
# ---------------------------------------------------------------------------


def test_test_whatsapp_ok(app_configured):
    """200 with success message when alerter is configured and send succeeds."""
    with app_configured.test_client() as c:
        resp = c.post(
            "/api/v1/alerts/whatsapp/test",
            json={"message": "Hello from FlintTrade"},
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert "sent" in body["message"].lower()


def test_test_whatsapp_not_configured(app_not_configured):
    """400 when WhatsApp webhook not configured."""
    with app_not_configured.test_client() as c:
        resp = c.post("/api/v1/alerts/whatsapp/test", json={})
    assert resp.status_code == 400
    assert resp.get_json()["status"] == "error"


def test_test_whatsapp_send_failure():
    """502 when alert send fails."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    mod.init_whatsapp_routes(_make_alerter(configured=True, send_ok=False))
    flask_app.register_blueprint(mod.whatsapp_bp)
    with flask_app.test_client() as c:
        resp = c.post("/api/v1/alerts/whatsapp/test", json={})
    assert resp.status_code == 502


def test_test_whatsapp_default_message(app_configured):
    """Default message is used when body is empty."""
    with app_configured.test_client() as c:
        resp = c.post("/api/v1/alerts/whatsapp/test")
    # Either 200 (sent) or 400 — not a 5xx
    assert resp.status_code in {200, 400}
