"""Tests for packages/automation/src/n8n_routes.py — n8n workflow integration."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from flask import Flask

import packages.automation.src.n8n_routes as mod
from packages.automation.src.n8n_bridge import N8nBridgeError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_bridge(healthy: bool = True, workflows: list | None = None) -> MagicMock:
    bridge = MagicMock()
    bridge.check_health.return_value = healthy
    bridge.list_workflows.return_value = workflows or [{"id": "1", "name": "Test"}]
    bridge.activate_workflow.return_value = True
    bridge.deactivate_workflow.return_value = True
    bridge.trigger_webhook.return_value = {"execution_id": "abc123"}
    return bridge


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    bridge = _make_bridge()
    mod.init_n8n_routes(bridge)
    flask_app.register_blueprint(mod.n8n_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# GET /api/v1/automation/n8n/health
# ---------------------------------------------------------------------------


def test_health_ok(client):
    """200 when n8n is reachable."""
    resp = client.get("/api/v1/automation/n8n/health")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["running"] is True


def test_health_down():
    """503 when n8n is unreachable."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    bridge = _make_bridge(healthy=False)
    mod.init_n8n_routes(bridge)
    flask_app.register_blueprint(mod.n8n_bp)
    with flask_app.test_client() as c:
        resp = c.get("/api/v1/automation/n8n/health")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# GET /api/v1/automation/n8n/workflows
# ---------------------------------------------------------------------------


def test_list_workflows_ok(client):
    """Returns workflow list and count."""
    resp = client.get("/api/v1/automation/n8n/workflows")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["data"]["count"] == 1


def test_list_workflows_error():
    """400 on N8nBridgeError."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    bridge = MagicMock()
    bridge.list_workflows.side_effect = N8nBridgeError("n8n unavailable")
    mod.init_n8n_routes(bridge)
    flask_app.register_blueprint(mod.n8n_bp)
    with flask_app.test_client() as c:
        resp = c.get("/api/v1/automation/n8n/workflows")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/v1/automation/n8n/webhook/trigger
# ---------------------------------------------------------------------------


def test_trigger_webhook_ok(client):
    """Returns execution_id on success."""
    resp = client.post(
        "/api/v1/automation/n8n/webhook/trigger",
        json={"webhook_id": "test-uuid", "data": {"symbol": "NIFTY"}},
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["execution_id"] == "abc123"


def test_trigger_webhook_missing_id(client):
    """400 when webhook_id is absent."""
    resp = client.post("/api/v1/automation/n8n/webhook/trigger", json={})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/v1/automation/n8n/workflows/<id>/activate
# ---------------------------------------------------------------------------


def test_activate_ok(client):
    """Returns active=true."""
    resp = client.post("/api/v1/automation/n8n/workflows/1/activate")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["active"] is True


def test_deactivate_ok(client):
    """Returns active=false."""
    resp = client.post("/api/v1/automation/n8n/workflows/1/deactivate")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["active"] is False
