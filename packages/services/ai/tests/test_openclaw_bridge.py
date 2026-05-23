"""Tests for OpenClaw bridge.

All tests use mocks — no live OpenClaw instance required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from flinttrade_ai.openclaw_bridge import OpenClawBridge


# ======================================================================
# Helpers
# ======================================================================


def _mock_response(status_code: int = 200, json_data=None):
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    return resp


# ======================================================================
# Health check
# ======================================================================


class TestOpenClawHealth:
    """Test health check when OpenClaw is running or unreachable."""

    @patch("flinttrade_ai.openclaw_bridge.httpx.Client")
    def test_health_check_success(self, mock_client_cls):
        client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        client.get.return_value = _mock_response(200)

        bridge = OpenClawBridge()
        assert bridge.check_health() is True
        assert bridge.is_connected is True

    @patch("flinttrade_ai.openclaw_bridge.httpx.Client")
    def test_health_check_service_down(self, mock_client_cls):
        import httpx as _httpx

        client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        client.get.side_effect = _httpx.ConnectError("Connection refused")

        bridge = OpenClawBridge()
        assert bridge.check_health() is False
        assert bridge.is_connected is False

    @patch("flinttrade_ai.openclaw_bridge.httpx.Client")
    def test_health_check_non_200(self, mock_client_cls):
        client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        client.get.return_value = _mock_response(503)

        bridge = OpenClawBridge()
        assert bridge.check_health() is False


# ======================================================================
# Agent deployment
# ======================================================================


class TestOpenClawDeploy:
    """Test agent deploy operations."""

    @patch("flinttrade_ai.openclaw_bridge.httpx.Client")
    def test_deploy_agent_success(self, mock_client_cls):
        client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        client.post.return_value = _mock_response(200, {
            "status": "success", "agent_id": "agent-123",
        })

        bridge = OpenClawBridge()
        result = bridge.deploy_agent({
            "name": "scalper-nifty",
            "strategy": "momentum",
            "symbols": ["NIFTY"],
        })
        assert result["status"] == "success"
        assert result["agent_id"] == "agent-123"

    @patch("flinttrade_ai.openclaw_bridge.httpx.Client")
    def test_deploy_agent_connection_error(self, mock_client_cls):
        import httpx as _httpx

        client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        client.post.side_effect = _httpx.ConnectError("Connection refused")

        bridge = OpenClawBridge()
        result = bridge.deploy_agent({"name": "test"})
        assert result["status"] == "error"


# ======================================================================
# Agent listing
# ======================================================================


class TestOpenClawListAgents:
    """Test list agents with different response formats."""

    @patch("flinttrade_ai.openclaw_bridge.httpx.Client")
    def test_list_agents_wrapped_format(self, mock_client_cls):
        client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        agents = [
            {"id": "a1", "name": "scalper", "status": "running"},
            {"id": "a2", "name": "hedger", "status": "stopped"},
        ]
        client.get.return_value = _mock_response(200, {"agents": agents})

        bridge = OpenClawBridge()
        result = bridge.list_agents()
        assert len(result) == 2
        assert result[0]["name"] == "scalper"

    @patch("flinttrade_ai.openclaw_bridge.httpx.Client")
    def test_list_agents_bare_list_format(self, mock_client_cls):
        client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        agents = [{"id": "a1", "name": "test", "status": "running"}]
        client.get.return_value = _mock_response(200, agents)

        bridge = OpenClawBridge()
        result = bridge.list_agents()
        assert len(result) == 1

    @patch("flinttrade_ai.openclaw_bridge.httpx.Client")
    def test_list_agents_connection_error(self, mock_client_cls):
        import httpx as _httpx

        client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        client.get.side_effect = _httpx.ConnectError("Connection refused")

        bridge = OpenClawBridge()
        result = bridge.list_agents()
        assert result == []


# ======================================================================
# Agent stop and logs
# ======================================================================


class TestOpenClawAgentControl:
    """Test stop and log retrieval."""

    @patch("flinttrade_ai.openclaw_bridge.httpx.Client")
    def test_stop_agent_success(self, mock_client_cls):
        client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        client.post.return_value = _mock_response(200, {
            "status": "success", "stopped": True,
        })

        bridge = OpenClawBridge()
        result = bridge.stop_agent("agent-123")
        assert result["status"] == "success"

    @patch("flinttrade_ai.openclaw_bridge.httpx.Client")
    def test_get_agent_logs_success(self, mock_client_cls):
        client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        logs = ["2026-04-08 10:00 INFO Agent started", "2026-04-08 10:01 INFO Order placed"]
        client.get.return_value = _mock_response(200, {"logs": logs})

        bridge = OpenClawBridge()
        result = bridge.get_agent_logs("agent-123")
        assert len(result) == 2
        assert "Agent started" in result[0]

    @patch("flinttrade_ai.openclaw_bridge.httpx.Client")
    def test_get_agent_logs_connection_error(self, mock_client_cls):
        import httpx as _httpx

        client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        client.get.side_effect = _httpx.ConnectError("Connection refused")

        bridge = OpenClawBridge()
        result = bridge.get_agent_logs("agent-123")
        assert result == []


# ======================================================================
# Constructor
# ======================================================================


class TestOpenClawInit:
    """Test bridge initialisation."""

    def test_default_host(self):
        bridge = OpenClawBridge()
        assert bridge.host == "http://127.0.0.1:18789"
        assert bridge.is_connected is False

    def test_custom_host(self):
        bridge = OpenClawBridge(host="http://192.0.2.10:18789/")
        assert bridge.host == "http://192.0.2.10:18789"
