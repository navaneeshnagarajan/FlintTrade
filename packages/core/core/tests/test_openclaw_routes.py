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
    assert body["data"] == {
        "connected": True,
        "agent_control_supported": False,
        "message": "",
    }


def test_openclaw_status_route_reports_disconnected(client) -> None:
    with patch("flinttrade_ai.openclaw_bridge.OpenClawBridge") as bridge_cls:
        bridge_cls.return_value.check_health.return_value = False
        resp = client.get("/api/v1/ai/openclaw/status")

    assert resp.status_code == 200
    assert resp.get_json()["data"] == {
        "connected": False,
        "agent_control_supported": False,
        "message": "",
    }


def test_openclaw_status_route_reports_lifecycle_capability(client) -> None:
    with patch("flinttrade_ai.openclaw_bridge.OpenClawBridge") as bridge_cls:
        bridge = bridge_cls.return_value
        bridge.check_health.return_value = True
        bridge.agent_control_supported = False
        bridge.agent_control_message = "HTTP agent lifecycle controls are unavailable."
        resp = client.get("/api/v1/ai/openclaw/status")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"] == {
        "connected": True,
        "agent_control_supported": False,
        "message": "HTTP agent lifecycle controls are unavailable.",
    }


def test_openclaw_agents_route_returns_listed_agents(client) -> None:
    agents = [{"id": "agent-1", "name": "scalper", "status": "running"}]
    with patch("flinttrade_ai.openclaw_bridge.OpenClawBridge") as bridge_cls:
        bridge_cls.return_value.list_agents.return_value = agents
        resp = client.get("/api/v1/ai/openclaw/agents")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["data"]["agents"] == agents


def test_deploy_route_delegates_to_the_bridge(client) -> None:
    with patch("flinttrade_ai.openclaw_bridge.OpenClawBridge") as bridge_cls:
        bridge_cls.return_value.deploy_agent.return_value = {"status": "success", "agent_id": "a-9"}
        resp = client.post(
            "/api/v1/ai/openclaw/agents",
            json={"name": "scalper-nifty", "strategy": "momentum", "symbols": ["NIFTY"]},
        )

    assert resp.status_code == 200
    assert resp.get_json()["data"]["agent_id"] == "a-9"
    bridge_cls.return_value.deploy_agent.assert_called_once()


def test_deploy_route_requires_a_name(client) -> None:
    resp = client.post("/api/v1/ai/openclaw/agents", json={"strategy": "momentum"})
    assert resp.status_code == 400


def test_deploy_route_502_when_openclaw_unreachable(client) -> None:
    with patch("flinttrade_ai.openclaw_bridge.OpenClawBridge") as bridge_cls:
        # The bridge returns an error dict (it never raises) when OpenClaw is down.
        bridge_cls.return_value.deploy_agent.return_value = {"status": "error", "message": "ConnectError"}
        resp = client.post("/api/v1/ai/openclaw/agents", json={"name": "x"})

    assert resp.status_code == 502


def test_deploy_route_501_when_lifecycle_api_unsupported(client) -> None:
    with patch("flinttrade_ai.openclaw_bridge.OpenClawBridge") as bridge_cls:
        bridge_cls.return_value.deploy_agent.return_value = {
            "status": "error",
            "code": "openclaw_agent_control_unsupported",
            "message": "HTTP agent lifecycle controls are unavailable.",
        }
        resp = client.post("/api/v1/ai/openclaw/agents", json={"name": "x"})

    assert resp.status_code == 501
    assert resp.get_json()["message"] == "HTTP agent lifecycle controls are unavailable."


def test_stop_route_delegates_to_the_bridge(client) -> None:
    with patch("flinttrade_ai.openclaw_bridge.OpenClawBridge") as bridge_cls:
        bridge_cls.return_value.stop_agent.return_value = {"status": "success"}
        resp = client.post("/api/v1/ai/openclaw/agents/a-9/stop")

    assert resp.status_code == 200
    bridge_cls.return_value.stop_agent.assert_called_once_with("a-9")


def test_stop_route_502_when_openclaw_unreachable(client) -> None:
    with patch("flinttrade_ai.openclaw_bridge.OpenClawBridge") as bridge_cls:
        bridge_cls.return_value.stop_agent.return_value = {"status": "error", "message": "ConnectError"}
        resp = client.post("/api/v1/ai/openclaw/agents/a-9/stop")

    assert resp.status_code == 502


def test_stop_route_501_when_lifecycle_api_unsupported(client) -> None:
    with patch("flinttrade_ai.openclaw_bridge.OpenClawBridge") as bridge_cls:
        bridge_cls.return_value.stop_agent.return_value = {
            "status": "error",
            "code": "openclaw_agent_control_unsupported",
            "message": "HTTP agent lifecycle controls are unavailable.",
        }
        resp = client.post("/api/v1/ai/openclaw/agents/a-9/stop")

    assert resp.status_code == 501
    assert resp.get_json()["message"] == "HTTP agent lifecycle controls are unavailable."


def test_logs_route_returns_lines_and_degrades_to_empty(client) -> None:
    with patch("flinttrade_ai.openclaw_bridge.OpenClawBridge") as bridge_cls:
        bridge_cls.return_value.get_agent_logs.return_value = ["line 1", "line 2"]
        resp = client.get("/api/v1/ai/openclaw/agents/a-9/logs")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["logs"] == ["line 1", "line 2"]

    with patch("flinttrade_ai.openclaw_bridge.OpenClawBridge") as bridge_cls:
        # Unreachable → the bridge returns [] → still a clean 200, empty logs.
        bridge_cls.return_value.get_agent_logs.return_value = []
        resp = client.get("/api/v1/ai/openclaw/agents/a-9/logs")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["logs"] == []
