"""Tests for AlgoMirror bridge.

All tests use mocks — no live AlgoMirror instance required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from packages.ditto.src.algomirror_bridge import AlgoMirrorBridge


# ======================================================================
# Helpers
# ======================================================================


def _mock_response(status_code: int = 200, json_data: dict | None = None):
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


# ======================================================================
# Health check
# ======================================================================


class TestAlgoMirrorHealth:
    """Test health check when AlgoMirror is running or unreachable."""

    @patch("packages.ditto.src.algomirror_bridge.httpx.Client")
    def test_health_check_success(self, mock_client_cls):
        client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        client.get.return_value = _mock_response(200)

        bridge = AlgoMirrorBridge()
        assert bridge.check_health() is True
        assert bridge.is_connected is True

    @patch("packages.ditto.src.algomirror_bridge.httpx.Client")
    def test_health_check_service_down(self, mock_client_cls):
        import httpx as _httpx

        client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        client.get.side_effect = _httpx.ConnectError("Connection refused")

        bridge = AlgoMirrorBridge()
        assert bridge.check_health() is False
        assert bridge.is_connected is False

    @patch("packages.ditto.src.algomirror_bridge.httpx.Client")
    def test_health_check_non_200(self, mock_client_cls):
        client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        client.get.return_value = _mock_response(503)

        bridge = AlgoMirrorBridge()
        assert bridge.check_health() is False


# ======================================================================
# Account sync
# ======================================================================


class TestAlgoMirrorSync:
    """Test account sync operations."""

    @patch("packages.ditto.src.algomirror_bridge.httpx.Client")
    def test_sync_accounts_success(self, mock_client_cls):
        client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        client.post.return_value = _mock_response(200, {
            "status": "success", "synced_count": 2,
        })

        bridge = AlgoMirrorBridge()
        result = bridge.sync_accounts([
            {"id": "acc1", "api_key": "key1"},
            {"id": "acc2", "api_key": "key2"},
        ])
        assert result["status"] == "success"
        assert result["synced_count"] == 2

    @patch("packages.ditto.src.algomirror_bridge.httpx.Client")
    def test_sync_accounts_connection_error(self, mock_client_cls):
        import httpx as _httpx

        client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        client.post.side_effect = _httpx.ConnectError("Connection refused")

        bridge = AlgoMirrorBridge()
        result = bridge.sync_accounts([{"id": "acc1"}])
        assert result["status"] == "error"


# ======================================================================
# Mirror control
# ======================================================================


class TestAlgoMirrorControl:
    """Test start/stop/status mirror operations."""

    @patch("packages.ditto.src.algomirror_bridge.httpx.Client")
    def test_start_mirror_success(self, mock_client_cls):
        client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        client.post.return_value = _mock_response(200, {
            "status": "success", "active": True, "source": "acc1",
        })

        bridge = AlgoMirrorBridge()
        result = bridge.start_mirror("acc1", ["acc2", "acc3"], multiplier=1.5)
        assert result["status"] == "success"
        assert result["active"] is True

    @patch("packages.ditto.src.algomirror_bridge.httpx.Client")
    def test_stop_mirror_success(self, mock_client_cls):
        client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        client.post.return_value = _mock_response(200, {
            "status": "success", "active": False,
        })

        bridge = AlgoMirrorBridge()
        result = bridge.stop_mirror()
        assert result["status"] == "success"

    @patch("packages.ditto.src.algomirror_bridge.httpx.Client")
    def test_get_status_success(self, mock_client_cls):
        client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        client.get.return_value = _mock_response(200, {
            "active": True,
            "source": "acc1",
            "targets": ["acc2"],
            "multiplier": 2.0,
            "mirrored_positions": 5,
            "errors": [],
        })

        bridge = AlgoMirrorBridge()
        result = bridge.get_status()
        assert result["active"] is True
        assert result["mirrored_positions"] == 5

    @patch("packages.ditto.src.algomirror_bridge.httpx.Client")
    def test_get_status_connection_error(self, mock_client_cls):
        import httpx as _httpx

        client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        client.get.side_effect = _httpx.ConnectError("Connection refused")

        bridge = AlgoMirrorBridge()
        result = bridge.get_status()
        assert result["status"] == "error"
        assert result["active"] is False


# ======================================================================
# Constructor
# ======================================================================


class TestAlgoMirrorInit:
    """Test bridge initialisation."""

    def test_default_host(self):
        bridge = AlgoMirrorBridge()
        assert bridge.host == "http://127.0.0.1:5200"
        assert bridge.is_connected is False

    def test_custom_host(self):
        bridge = AlgoMirrorBridge(host="http://10.10.10.1:5200/")
        assert bridge.host == "http://10.10.10.1:5200"
