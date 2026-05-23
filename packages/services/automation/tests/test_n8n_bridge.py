"""Tests for N8nBridge — all tests use mocks, no live HTTP calls.

DO NOT RUN against a real n8n instance. All network I/O is patched.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestN8nBridgeHealth:
    """check_health — returns True on 200, False on error."""

    def test_health_returns_true_when_n8n_responds_200(self):
        from flinttrade_automation.n8n_bridge import N8nBridge

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        bridge = N8nBridge()
        with patch.object(bridge._http, "get", return_value=mock_resp):
            assert bridge.check_health() is True

    def test_health_returns_false_on_non_200(self):
        from flinttrade_automation.n8n_bridge import N8nBridge

        mock_resp = MagicMock()
        mock_resp.status_code = 503

        bridge = N8nBridge()
        with patch.object(bridge._http, "get", return_value=mock_resp):
            assert bridge.check_health() is False

    def test_health_returns_false_on_connection_error(self):
        from flinttrade_automation.n8n_bridge import N8nBridge

        bridge = N8nBridge()
        with patch.object(bridge._http, "get", side_effect=Exception("refused")):
            assert bridge.check_health() is False


class TestN8nBridgeTriggerWebhook:
    """trigger_webhook — sends POST to /webhook/<id> with payload."""

    def test_trigger_webhook_success(self):
        from flinttrade_automation.n8n_bridge import N8nBridge

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": "Workflow was started"}

        bridge = N8nBridge()
        with patch.object(bridge._http, "post", return_value=mock_resp) as mock_post:
            result = bridge.trigger_webhook("abc123", {"symbol": "NIFTY", "action": "BUY"})

        assert result == {"message": "Workflow was started"}
        called_url = mock_post.call_args[0][0]
        assert called_url == "http://127.0.0.1:5678/webhook/abc123"
        sent_json = mock_post.call_args[1]["json"]
        assert sent_json["symbol"] == "NIFTY"

    def test_trigger_webhook_raises_on_non_2xx(self):
        from flinttrade_automation.n8n_bridge import N8nBridge, N8nBridgeError

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"

        bridge = N8nBridge()
        with patch.object(bridge._http, "post", return_value=mock_resp):
            try:
                bridge.trigger_webhook("bad-id", {})
                assert False, "Expected N8nBridgeError"
            except N8nBridgeError as exc:
                assert "404" in str(exc)

    def test_trigger_webhook_raises_on_connection_error(self):
        from flinttrade_automation.n8n_bridge import N8nBridge, N8nBridgeError

        bridge = N8nBridge()
        with patch.object(bridge._http, "post", side_effect=Exception("connection refused")):
            try:
                bridge.trigger_webhook("abc", {"x": 1})
                assert False, "Expected N8nBridgeError"
            except N8nBridgeError as exc:
                assert "connection refused" in str(exc)


class TestN8nBridgeListWorkflows:
    """list_workflows — GET /api/v1/workflows, returns list of dicts."""

    def test_list_workflows_returns_workflow_list(self):
        from flinttrade_automation.n8n_bridge import N8nBridge

        workflows = [
            {"id": "1", "name": "Order Fill Alert", "active": True},
            {"id": "2", "name": "Daily P&L Report", "active": False},
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": workflows}

        bridge = N8nBridge(api_key="test-key")
        with patch.object(bridge._http, "get", return_value=mock_resp):
            result = bridge.list_workflows()

        assert len(result) == 2
        assert result[0]["name"] == "Order Fill Alert"

    def test_list_workflows_raises_without_api_key(self):
        from flinttrade_automation.n8n_bridge import N8nBridge, N8nBridgeError

        bridge = N8nBridge(api_key="")
        try:
            bridge.list_workflows()
            assert False, "Expected N8nBridgeError"
        except N8nBridgeError as exc:
            assert "API key" in str(exc)

    def test_list_workflows_raises_on_non_200(self):
        from flinttrade_automation.n8n_bridge import N8nBridge, N8nBridgeError

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"

        bridge = N8nBridge(api_key="bad-key")
        with patch.object(bridge._http, "get", return_value=mock_resp):
            try:
                bridge.list_workflows()
                assert False, "Expected N8nBridgeError"
            except N8nBridgeError as exc:
                assert "401" in str(exc)


class TestN8nBridgeActivateWorkflow:
    """activate_workflow — POST /api/v1/workflows/<id>/activate."""

    def test_activate_returns_true_on_200(self):
        from flinttrade_automation.n8n_bridge import N8nBridge

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "1", "active": True}

        bridge = N8nBridge(api_key="test-key")
        with patch.object(bridge._http, "post", return_value=mock_resp) as mock_post:
            result = bridge.activate_workflow("1")

        assert result is True
        called_url = mock_post.call_args[0][0]
        assert "activate" in called_url

    def test_activate_returns_false_on_non_200(self):
        from flinttrade_automation.n8n_bridge import N8nBridge

        mock_resp = MagicMock()
        mock_resp.status_code = 404

        bridge = N8nBridge(api_key="test-key")
        with patch.object(bridge._http, "post", return_value=mock_resp):
            result = bridge.activate_workflow("999")

        assert result is False


class TestN8nBridgeDeactivateWorkflow:
    """deactivate_workflow — POST /api/v1/workflows/<id>/deactivate."""

    def test_deactivate_returns_true_on_200(self):
        from flinttrade_automation.n8n_bridge import N8nBridge

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "2", "active": False}

        bridge = N8nBridge(api_key="test-key")
        with patch.object(bridge._http, "post", return_value=mock_resp) as mock_post:
            result = bridge.deactivate_workflow("2")

        assert result is True
        called_url = mock_post.call_args[0][0]
        assert "deactivate" in called_url

    def test_deactivate_returns_false_on_non_200(self):
        from flinttrade_automation.n8n_bridge import N8nBridge

        mock_resp = MagicMock()
        mock_resp.status_code = 500

        bridge = N8nBridge(api_key="test-key")
        with patch.object(bridge._http, "post", return_value=mock_resp):
            result = bridge.deactivate_workflow("2")

        assert result is False


class TestN8nBridgeConnectionError:
    """Connection error handling — all methods should propagate N8nBridgeError."""

    def test_trigger_webhook_network_failure(self):
        from flinttrade_automation.n8n_bridge import N8nBridge, N8nBridgeError

        bridge = N8nBridge()
        with patch.object(bridge._http, "post", side_effect=OSError("network unreachable")):
            try:
                bridge.trigger_webhook("wh1", {"foo": "bar"})
                assert False, "Expected N8nBridgeError"
            except N8nBridgeError:
                pass  # expected

    def test_list_workflows_network_failure(self):
        from flinttrade_automation.n8n_bridge import N8nBridge, N8nBridgeError

        bridge = N8nBridge(api_key="key")
        with patch.object(bridge._http, "get", side_effect=OSError("timeout")):
            try:
                bridge.list_workflows()
                assert False, "Expected N8nBridgeError"
            except N8nBridgeError:
                pass  # expected
