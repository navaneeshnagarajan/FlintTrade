"""Tests for WhatsApp alert system.

All HTTP calls are mocked. No real webhook URLs needed.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# WhatsAppConfig
# ---------------------------------------------------------------------------


class TestWhatsAppConfig:
    def test_default_config_disabled(self):
        from flinttrade_automation.whatsapp_alerts import WhatsAppConfig
        cfg = WhatsAppConfig()
        assert cfg.webhook_url == ""
        assert cfg.enabled is False

    def test_config_with_values(self):
        from flinttrade_automation.whatsapp_alerts import WhatsAppConfig
        cfg = WhatsAppConfig(webhook_url="https://example.com/webhook", enabled=True)
        assert cfg.webhook_url == "https://example.com/webhook"
        assert cfg.enabled is True

    def test_from_env_reads_env_vars(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_WEBHOOK_URL", "https://hook.example.com")
        monkeypatch.setenv("WHATSAPP_ENABLED", "true")
        from flinttrade_automation.whatsapp_alerts import WhatsAppConfig
        cfg = WhatsAppConfig.from_env()
        assert cfg.webhook_url == "https://hook.example.com"
        assert cfg.enabled is True

    def test_from_env_disabled_when_flag_false(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_WEBHOOK_URL", "https://hook.example.com")
        monkeypatch.setenv("WHATSAPP_ENABLED", "false")
        from flinttrade_automation.whatsapp_alerts import WhatsAppConfig
        cfg = WhatsAppConfig.from_env()
        assert cfg.enabled is False

    def test_from_env_missing_vars_returns_defaults(self, monkeypatch):
        monkeypatch.delenv("WHATSAPP_WEBHOOK_URL", raising=False)
        monkeypatch.delenv("WHATSAPP_ENABLED", raising=False)
        from flinttrade_automation.whatsapp_alerts import WhatsAppConfig
        cfg = WhatsAppConfig.from_env()
        assert cfg.webhook_url == ""
        assert cfg.enabled is False


# ---------------------------------------------------------------------------
# WhatsAppAlerter.send_alert
# ---------------------------------------------------------------------------


class TestSendAlert:
    def _alerter(self, url: str = "https://hook.example.com", enabled: bool = True):
        from flinttrade_automation.whatsapp_alerts import WhatsAppAlerter, WhatsAppConfig
        return WhatsAppAlerter(config=WhatsAppConfig(webhook_url=url, enabled=enabled))

    def test_send_alert_constructs_correct_payload(self):
        alerter = self._alerter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            result = alerter.send_alert("NIFTY crossed 24000!")
        assert result is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json"]["message"] == "NIFTY crossed 24000!"

    def test_send_alert_returns_false_when_not_configured(self):
        alerter = self._alerter(url="", enabled=False)
        result = alerter.send_alert("test")
        assert result is False

    def test_send_alert_returns_false_when_disabled(self):
        alerter = self._alerter(url="https://hook.example.com", enabled=False)
        result = alerter.send_alert("test")
        assert result is False

    def test_send_alert_returns_false_on_http_error(self):
        alerter = self._alerter()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch("httpx.post", return_value=mock_resp):
            result = alerter.send_alert("test")
        assert result is False

    def test_send_alert_returns_false_on_exception(self):
        alerter = self._alerter()
        with patch("httpx.post", side_effect=Exception("network down")):
            result = alerter.send_alert("test")
        assert result is False

    def test_send_alert_records_history(self):
        alerter = self._alerter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("httpx.post", return_value=mock_resp):
            alerter.send_alert("Alert 1")
            alerter.send_alert("Alert 2")
        assert len(alerter.history) == 2
        assert alerter.history[0]["message"] == "Alert 1"


# ---------------------------------------------------------------------------
# WhatsAppAlerter.send_signal
# ---------------------------------------------------------------------------


class TestSendSignal:
    def _alerter(self):
        from flinttrade_automation.whatsapp_alerts import WhatsAppAlerter, WhatsAppConfig
        return WhatsAppAlerter(config=WhatsAppConfig(
            webhook_url="https://hook.example.com", enabled=True,
        ))

    def test_send_signal_formats_message(self):
        alerter = self._alerter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            alerter.send_signal({
                "symbol": "RELIANCE",
                "signal_type": "BUY",
                "confidence": 0.85,
                "exchange": "NSE",
            })
        payload = mock_post.call_args[1]["json"]
        assert "RELIANCE" in payload["message"]
        assert "BUY" in payload["message"]
        assert payload["type"] == "signal"

    def test_send_signal_uses_signal_key_fallback(self):
        alerter = self._alerter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            alerter.send_signal({"symbol": "NIFTY", "signal": "SELL"})
        payload = mock_post.call_args[1]["json"]
        assert "SELL" in payload["message"]


# ---------------------------------------------------------------------------
# WhatsAppAlerter.send_order_update
# ---------------------------------------------------------------------------


class TestSendOrderUpdate:
    def _alerter(self):
        from flinttrade_automation.whatsapp_alerts import WhatsAppAlerter, WhatsAppConfig
        return WhatsAppAlerter(config=WhatsAppConfig(
            webhook_url="https://hook.example.com", enabled=True,
        ))

    def test_send_order_update_formats_message(self):
        alerter = self._alerter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            alerter.send_order_update({
                "symbol": "INFY",
                "action": "BUY",
                "quantity": 50,
                "price": "1500",
                "status": "FILLED",
            })
        payload = mock_post.call_args[1]["json"]
        assert "INFY" in payload["message"]
        assert "BUY" in payload["message"]
        assert "FILLED" in payload["message"]
        assert payload["type"] == "order"


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    def _alerter(self):
        from flinttrade_automation.whatsapp_alerts import WhatsAppAlerter, WhatsAppConfig
        return WhatsAppAlerter(config=WhatsAppConfig(
            webhook_url="https://hook.example.com", enabled=True,
        ))

    def test_rate_limit_blocks_after_max_messages(self):
        alerter = self._alerter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.post", return_value=mock_resp):
            # Send 30 messages (the limit)
            for i in range(30):
                result = alerter.send_alert(f"Message {i}")
                assert result is True

            # 31st should be rate-limited
            result = alerter.send_alert("Over limit")
            assert result is False

    def test_rate_limit_resets_after_window(self):
        alerter = self._alerter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.post", return_value=mock_resp):
            # Fill up the rate limit
            for i in range(30):
                alerter.send_alert(f"Message {i}")

            # Simulate time passing beyond the window
            alerter._rate_limit._timestamps = [
                time.time() - 61.0 for _ in range(30)
            ]

            # Should be allowed again
            result = alerter.send_alert("After window")
            assert result is True


# ---------------------------------------------------------------------------
# is_configured property
# ---------------------------------------------------------------------------


class TestIsConfigured:
    def test_configured_when_url_and_enabled(self):
        from flinttrade_automation.whatsapp_alerts import WhatsAppAlerter, WhatsAppConfig
        alerter = WhatsAppAlerter(config=WhatsAppConfig(
            webhook_url="https://hook.example.com", enabled=True,
        ))
        assert alerter.is_configured is True

    def test_not_configured_without_url(self):
        from flinttrade_automation.whatsapp_alerts import WhatsAppAlerter, WhatsAppConfig
        alerter = WhatsAppAlerter(config=WhatsAppConfig(webhook_url="", enabled=True))
        assert alerter.is_configured is False

    def test_not_configured_when_disabled(self):
        from flinttrade_automation.whatsapp_alerts import WhatsAppAlerter, WhatsAppConfig
        alerter = WhatsAppAlerter(config=WhatsAppConfig(
            webhook_url="https://hook.example.com", enabled=False,
        ))
        assert alerter.is_configured is False
