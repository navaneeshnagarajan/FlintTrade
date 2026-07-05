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
        client.get.assert_called_once_with("http://127.0.0.1:18789/healthz")

    @patch("flinttrade_ai.openclaw_bridge.httpx.Client")
    def test_health_check_falls_back_to_legacy_health_alias(self, mock_client_cls):
        client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        client.get.side_effect = [_mock_response(404), _mock_response(200)]

        bridge = OpenClawBridge()
        assert bridge.check_health() is True
        assert bridge.is_connected is True
        assert [c.args[0] for c in client.get.call_args_list] == [
            "http://127.0.0.1:18789/healthz",
            "http://127.0.0.1:18789/health",
        ]

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

    def test_deploy_agent_returns_explicit_unsupported(self):
        bridge = OpenClawBridge()
        result = bridge.deploy_agent({
            "name": "scalper-nifty",
            "strategy": "momentum",
            "symbols": ["NIFTY"],
        })
        assert result["status"] == "error"
        assert result["code"] == "openclaw_agent_control_unsupported"


# ======================================================================
# Agent listing
# ======================================================================


class TestOpenClawListAgents:
    """Test list agents with different response formats."""

    def test_list_agents_returns_empty_without_nonexistent_http_api(self):
        bridge = OpenClawBridge()
        result = bridge.list_agents()
        assert result == []


# ======================================================================
# Agent stop and logs
# ======================================================================


class TestOpenClawAgentControl:
    """Test stop and log retrieval."""

    def test_stop_agent_returns_explicit_unsupported(self):
        bridge = OpenClawBridge()
        result = bridge.stop_agent("agent-123")
        assert result["status"] == "error"
        assert result["code"] == "openclaw_agent_control_unsupported"

    def test_get_agent_logs_returns_empty_without_nonexistent_http_api(self):
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
