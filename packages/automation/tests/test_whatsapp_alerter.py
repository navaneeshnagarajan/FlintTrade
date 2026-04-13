# packages/automation/tests/test_whatsapp_alerter.py
"""Tests for WhatsAppAlerter (wabridge sidecar) and AlertRouter.

All HTTP calls are mocked. No real wabridge instance is required.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# WhatsAppAlerter — configuration
# ---------------------------------------------------------------------------


class TestWhatsAppAlerterConfig:
    def test_bridge_url_from_constructor(self):
        from packages.automation.src.whatsapp_alerter import WhatsAppAlerter

        a = WhatsAppAlerter(bridge_url="http://localhost:3000")
        assert a.bridge_url == "http://localhost:3000"
        assert a.is_configured is True

    def test_empty_bridge_url_not_configured(self):
        from packages.automation.src.whatsapp_alerter import WhatsAppAlerter

        a = WhatsAppAlerter(bridge_url="")
        # _resolve_bridge_url will also return "" in test env
        assert a.is_configured is False

    def test_bridge_url_from_env(self, monkeypatch):
        monkeypatch.setenv("WABRIDGE_URL", "http://10.0.0.1:3000")
        from packages.automation.src.whatsapp_alerter import WhatsAppAlerter

        a = WhatsAppAlerter()
        assert a.bridge_url == "http://10.0.0.1:3000"

    def test_trailing_slash_stripped_on_post(self):
        """Ensure trailing slash on bridge_url does not cause double-slash paths."""
        from packages.automation.src.whatsapp_alerter import WhatsAppAlerter

        a = WhatsAppAlerter(bridge_url="http://localhost:3000/")
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.post", return_value=mock_resp) as mock_post:
            a.send_to_self("hello")
            call_url = mock_post.call_args[0][0]
        assert not call_url.startswith("http://localhost:3000//")


# ---------------------------------------------------------------------------
# WhatsAppAlerter — send_text
# ---------------------------------------------------------------------------


class TestSendText:
    def _alerter(self) -> "WhatsAppAlerter":
        from packages.automation.src.whatsapp_alerter import WhatsAppAlerter

        return WhatsAppAlerter(bridge_url="http://localhost:3000")

    def test_send_text_posts_to_send_endpoint(self):
        a = self._alerter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.post", return_value=mock_resp) as mock_post:
            result = a.send_text("919876543210", "Test alert")

        assert result is True
        call_url, call_kwargs = mock_post.call_args[0][0], mock_post.call_args[1]
        assert call_url.endswith("/send")
        payload = mock_post.call_args[1]["json"]
        assert payload["phone"] == "919876543210"
        assert payload["message"] == "Test alert"

    def test_send_text_returns_false_on_http_error(self):
        a = self._alerter()
        mock_resp = MagicMock()
        mock_resp.status_code = 500

        with patch("httpx.post", return_value=mock_resp):
            result = a.send_text("919876543210", "fail")

        assert result is False

    def test_send_text_returns_false_on_exception(self):
        a = self._alerter()
        with patch("httpx.post", side_effect=OSError("connection refused")):
            result = a.send_text("919876543210", "fail")

        assert result is False

    def test_send_text_returns_false_when_not_configured(self):
        from packages.automation.src.whatsapp_alerter import WhatsAppAlerter

        a = WhatsAppAlerter(bridge_url="")
        result = a.send_text("919876543210", "fail")
        assert result is False


# ---------------------------------------------------------------------------
# WhatsAppAlerter — send_to_self
# ---------------------------------------------------------------------------


class TestSendToSelf:
    def _alerter(self):
        from packages.automation.src.whatsapp_alerter import WhatsAppAlerter

        return WhatsAppAlerter(bridge_url="http://localhost:3000")

    def test_posts_to_send_self(self):
        a = self._alerter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.post", return_value=mock_resp) as mock_post:
            result = a.send_to_self("Strategy triggered!")

        assert result is True
        call_url = mock_post.call_args[0][0]
        assert call_url.endswith("/send/self")
        assert mock_post.call_args[1]["json"]["message"] == "Strategy triggered!"

    def test_returns_false_on_error(self):
        a = self._alerter()
        mock_resp = MagicMock()
        mock_resp.status_code = 400

        with patch("httpx.post", return_value=mock_resp):
            assert a.send_to_self("fail") is False


# ---------------------------------------------------------------------------
# WhatsAppAlerter — send_to_group
# ---------------------------------------------------------------------------


class TestSendToGroup:
    def _alerter(self):
        from packages.automation.src.whatsapp_alerter import WhatsAppAlerter

        return WhatsAppAlerter(bridge_url="http://localhost:3000")

    def test_posts_to_send_group(self):
        a = self._alerter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.post", return_value=mock_resp) as mock_post:
            result = a.send_to_group("120363012345@g.us", "Group alert!")

        assert result is True
        call_url = mock_post.call_args[0][0]
        assert call_url.endswith("/send/group")
        payload = mock_post.call_args[1]["json"]
        assert payload["groupId"] == "120363012345@g.us"
        assert payload["message"] == "Group alert!"


# ---------------------------------------------------------------------------
# WhatsAppAlerter — rate limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    def test_rate_limit_blocks_after_30_messages(self):
        from packages.automation.src.whatsapp_alerter import WhatsAppAlerter

        a = WhatsAppAlerter(bridge_url="http://localhost:3000")
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.post", return_value=mock_resp):
            # Send 30 allowed messages
            for _ in range(30):
                a.send_to_self("msg")

            # 31st must be blocked
            result = a.send_to_self("blocked")

        assert result is False

    def test_rate_limit_resets_after_window(self):
        from packages.automation.src.whatsapp_alerter import WhatsAppAlerter

        a = WhatsAppAlerter(bridge_url="http://localhost:3000")
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.post", return_value=mock_resp):
            # Fill up 30 slots with old timestamps
            old_time = time.time() - 65  # 65 seconds ago (outside the 60s window)
            a._send_timestamps = [old_time] * 30

            # Should be allowed now — window has slid past those timestamps
            result = a.send_to_self("after window")

        assert result is True


# ---------------------------------------------------------------------------
# AlertRouter — channel resolution
# ---------------------------------------------------------------------------


class TestAlertRouterChannels:
    def test_default_signal_goes_to_both_channels(self):
        from packages.automation.src.whatsapp_alerter import AlertRouter, AlertRouterConfig

        cfg = AlertRouterConfig(telegram_enabled=True, whatsapp_enabled=True)
        router = AlertRouter(config=cfg)
        channels = router._channels_for("signal")
        assert "telegram" in channels
        assert "whatsapp" in channels

    def test_telegram_only_when_whatsapp_disabled(self):
        from packages.automation.src.whatsapp_alerter import AlertRouter, AlertRouterConfig

        cfg = AlertRouterConfig(telegram_enabled=True, whatsapp_enabled=False)
        router = AlertRouter(config=cfg)
        channels = router._channels_for("signal")
        assert channels == ["telegram"]

    def test_no_channels_when_both_disabled(self):
        from packages.automation.src.whatsapp_alerter import AlertRouter, AlertRouterConfig

        cfg = AlertRouterConfig(telegram_enabled=False, whatsapp_enabled=False)
        router = AlertRouter(config=cfg)
        channels = router._channels_for("signal")
        assert channels == []

    def test_pnl_alert_goes_to_telegram_only_by_default(self):
        from packages.automation.src.whatsapp_alerter import AlertRouter, AlertRouterConfig

        cfg = AlertRouterConfig(telegram_enabled=True, whatsapp_enabled=True)
        router = AlertRouter(config=cfg)
        channels = router._channels_for("pnl")
        assert "telegram" in channels
        assert "whatsapp" not in channels

    def test_workspace_override_respected(self):
        from packages.automation.src.whatsapp_alerter import AlertRouter, AlertRouterConfig

        cfg = AlertRouterConfig(
            telegram_enabled=True,
            whatsapp_enabled=True,
            alert_channels={"pnl": ["telegram", "whatsapp"]},
        )
        router = AlertRouter(config=cfg)
        channels = router._channels_for("pnl")
        assert "whatsapp" in channels


# ---------------------------------------------------------------------------
# AlertRouter — route_alert delivery
# ---------------------------------------------------------------------------


class TestAlertRouterDelivery:
    def _router_with_mocks(self, tg_enabled=True, wa_enabled=True):
        from packages.automation.src.whatsapp_alerter import (
            AlertRouter,
            AlertRouterConfig,
            WhatsAppAlerter,
        )

        mock_tg = MagicMock()
        mock_tg.send_message.return_value = True

        mock_wa = WhatsAppAlerter(bridge_url="http://localhost:3000")
        mock_wa.send_to_self = MagicMock(return_value=True)
        mock_wa.send_text = MagicMock(return_value=True)

        cfg = AlertRouterConfig(
            telegram_enabled=tg_enabled,
            whatsapp_enabled=wa_enabled,
        )
        return AlertRouter(telegram_bot=mock_tg, whatsapp_alerter=mock_wa, config=cfg), mock_tg, mock_wa

    def test_signal_sent_to_both_channels(self):
        router, mock_tg, mock_wa = self._router_with_mocks()
        router.route_alert("signal", "NIFTY BUY", {"confidence": 0.9})

        mock_tg.send_message.assert_called_once()
        assert "[SIGNAL]" in mock_tg.send_message.call_args[0][0]
        mock_wa.send_to_self.assert_called_once()

    def test_telegram_only_when_wa_disabled(self):
        router, mock_tg, mock_wa = self._router_with_mocks(wa_enabled=False)
        router.route_alert("signal", "NIFTY BUY", {})

        mock_tg.send_message.assert_called_once()
        mock_wa.send_to_self.assert_not_called()

    def test_no_delivery_when_both_disabled(self):
        router, mock_tg, mock_wa = self._router_with_mocks(tg_enabled=False, wa_enabled=False)
        router.route_alert("signal", "dropped", {})

        mock_tg.send_message.assert_not_called()
        mock_wa.send_to_self.assert_not_called()

    def test_sends_to_phone_when_configured(self):
        from packages.automation.src.whatsapp_alerter import (
            AlertRouter,
            AlertRouterConfig,
            WhatsAppAlerter,
        )

        mock_tg = MagicMock()
        mock_wa = WhatsAppAlerter(bridge_url="http://localhost:3000")
        mock_wa.send_text = MagicMock(return_value=True)
        mock_wa.send_to_self = MagicMock(return_value=True)

        cfg = AlertRouterConfig(
            telegram_enabled=False,
            whatsapp_enabled=True,
            whatsapp_self_phone="919876543210",
        )
        router = AlertRouter(telegram_bot=mock_tg, whatsapp_alerter=mock_wa, config=cfg)
        router.route_alert("signal", "test", {})

        mock_wa.send_text.assert_called_once_with("919876543210", "[SIGNAL] test")
        mock_wa.send_to_self.assert_not_called()

    def test_telegram_error_does_not_block_whatsapp(self):
        from packages.automation.src.whatsapp_alerter import (
            AlertRouter,
            AlertRouterConfig,
            WhatsAppAlerter,
        )

        mock_tg = MagicMock()
        mock_tg.send_message.side_effect = RuntimeError("telegram down")

        mock_wa = WhatsAppAlerter(bridge_url="http://localhost:3000")
        mock_wa.send_to_self = MagicMock(return_value=True)

        cfg = AlertRouterConfig(telegram_enabled=True, whatsapp_enabled=True)
        router = AlertRouter(telegram_bot=mock_tg, whatsapp_alerter=mock_wa, config=cfg)

        # Should not raise even when telegram fails
        router.route_alert("signal", "still delivered", {})

        mock_wa.send_to_self.assert_called_once()


# ---------------------------------------------------------------------------
# AlertRouterConfig.from_workspace
# ---------------------------------------------------------------------------


class TestAlertRouterConfigFromWorkspace:
    def test_returns_defaults_when_workspace_unavailable(self):
        from packages.automation.src.whatsapp_alerter import AlertRouterConfig

        with patch(
            "packages.automation.src.whatsapp_alerter.AlertRouterConfig.from_workspace",
            side_effect=Exception("no workspace"),
        ):
            # Calling directly with defaults still works
            cfg = AlertRouterConfig()
        assert cfg.telegram_enabled is True
        assert cfg.whatsapp_enabled is False
