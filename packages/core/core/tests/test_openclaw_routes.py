"""End-to-end route tests for the OpenClaw agent bridge.

The bridge itself is unit-tested in flinttrade_ai; these prove the
``/api/v1/ai/openclaw/*`` endpoints are actually WIRED through the Flask app and
return the bridge's result — so "support OpenClaw agents" is reachable from the
running backend, not just a class in isolation. The external OpenClaw service is
mocked (the bridge is patched), so no live gateway is required.

    uv run pytest packages/core/core/tests/test_openclaw_routes.py -v --import-mode=importlib
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture()
def client():
    from flask import Flask

    from flinttrade_core.operations_routes import operations_bp

    app = Flask(__name__)
    app.register_blueprint(operations_bp)  # carries its own /api/v1 url_prefix
    with app.test_client() as c:
        yield c


def test_openclaw_status_route_reports_bridge_health(client) -> None:
    with patch("flinttrade_ai.openclaw_bridge.OpenClawBridge") as bridge_cls:
        bridge_cls.return_value.check_health.return_value = True
        resp = client.get("/api/v1/ai/openclaw/status")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["data"] == {"connected": True}


def test_openclaw_status_route_reports_disconnected(client) -> None:
    with patch("flinttrade_ai.openclaw_bridge.OpenClawBridge") as bridge_cls:
        bridge_cls.return_value.check_health.return_value = False
        resp = client.get("/api/v1/ai/openclaw/status")

    assert resp.status_code == 200
    assert resp.get_json()["data"] == {"connected": False}


def test_openclaw_agents_route_returns_listed_agents(client) -> None:
    agents = [{"id": "agent-1", "name": "scalper", "status": "running"}]
    with patch("flinttrade_ai.openclaw_bridge.OpenClawBridge") as bridge_cls:
        bridge_cls.return_value.list_agents.return_value = agents
        resp = client.get("/api/v1/ai/openclaw/agents")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["data"]["agents"] == agents
