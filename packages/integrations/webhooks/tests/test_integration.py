"""Tests for FlintTrade integration package.

DO NOT RUN — written for pytest. All tests use synthetic data, no API calls.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest


# ======================================================================
# Webhook receiver surface
# ======================================================================


class TestWebhookReceiverSurface:
    """The mounted receiver is the single webhook intake core."""

    def test_standalone_webhook_server_is_retired(self):
        import importlib

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("flinttrade_webhooks.webhook_server")

    def test_receiver_rate_limit_replaces_server_limiter(self):
        from flinttrade_webhooks.webhook_receiver import WebhookConfig, WebhookReceiver

        receiver = WebhookReceiver(WebhookConfig(skip_verification=True, rate_limit=2))
        assert receiver.check_rate_limit() is True
        assert receiver.check_rate_limit() is True
        assert receiver.check_rate_limit() is False
        assert receiver.rate_limit_remaining == 0


# ======================================================================
# Alerter — throttling
# ======================================================================


class TestAlerter:
    """Test alert formatting, throttling, and dispatch."""

    def test_format_order_placed(self):
        from flinttrade_webhooks.alerter import Alert, format_alert
        alert = Alert(
            alert_type="ORDER_PLACED",
            message="Order 12345",
            symbol="RELIANCE", exchange="NSE",
            action="BUY", quantity="10", price="2500",
            strategy="Flint",
        )
        formatted = format_alert(alert)
        assert "ORDER_PLACED" in formatted
        assert "RELIANCE" in formatted
        assert "BUY" in formatted
        assert "2500" in formatted

    def test_format_safety_triggered(self):
        from flinttrade_webhooks.alerter import Alert, format_alert
        alert = Alert(
            alert_type="SAFETY_TRIGGERED",
            message="[L1_ORDER] Price deviation 12%",
            symbol="RELIANCE",
        )
        formatted = format_alert(alert)
        assert "SAFETY_TRIGGERED" in formatted
        assert "L1_ORDER" in formatted

    def test_throttle_blocks_duplicate(self):
        from flinttrade_webhooks.alerter import Alert, AlertThrottler
        throttler = AlertThrottler(window_seconds=60)
        alert = Alert(alert_type="ORDER_PLACED", message="test", symbol="RELIANCE")
        assert throttler.should_send(alert)
        assert not throttler.should_send(alert)  # same symbol+type within 60s

    def test_throttle_allows_different_symbol(self):
        from flinttrade_webhooks.alerter import Alert, AlertThrottler
        throttler = AlertThrottler(window_seconds=60)
        a1 = Alert(alert_type="ORDER_PLACED", message="test", symbol="RELIANCE")
        a2 = Alert(alert_type="ORDER_PLACED", message="test", symbol="TCS")
        assert throttler.should_send(a1)
        assert throttler.should_send(a2)  # different symbol

    def test_throttle_allows_different_type(self):
        from flinttrade_webhooks.alerter import Alert, AlertThrottler
        throttler = AlertThrottler(window_seconds=60)
        a1 = Alert(alert_type="ORDER_PLACED", message="test", symbol="RELIANCE")
        a2 = Alert(alert_type="ORDER_FILLED", message="test", symbol="RELIANCE")
        assert throttler.should_send(a1)
        assert throttler.should_send(a2)  # different type

    def test_throttle_reset(self):
        from flinttrade_webhooks.alerter import Alert, AlertThrottler
        throttler = AlertThrottler(window_seconds=60)
        alert = Alert(alert_type="ORDER_PLACED", message="test", symbol="RELIANCE")
        throttler.should_send(alert)
        throttler.reset()
        assert throttler.should_send(alert)  # reset clears throttle

    def test_alerter_console_channel(self):
        from flinttrade_webhooks.alerter import AlertChannel, Alerter
        alerter = Alerter(channels=[AlertChannel.CONSOLE], throttle_seconds=0)
        sent = alerter.send(
            __import__("flinttrade_webhooks.alerter", fromlist=["Alert"]).Alert(
                alert_type="CUSTOM", message="Hello"
            )
        )
        assert sent

    def test_alerter_convenience_order_placed(self):
        from flinttrade_webhooks.alerter import AlertChannel, Alerter
        alerter = Alerter(channels=[AlertChannel.CONSOLE], throttle_seconds=0)
        alerter.order_placed(symbol="RELIANCE", exchange="NSE", action="BUY", quantity="10", price="2500")
        assert len(alerter.history) == 1
        assert alerter.history[0].alert_type == "ORDER_PLACED"

    def test_alerter_convenience_safety(self):
        from flinttrade_webhooks.alerter import AlertChannel, Alerter
        alerter = Alerter(channels=[AlertChannel.CONSOLE], throttle_seconds=0)
        alerter.safety_triggered(layer="L1_ORDER", reason="Price deviation", symbol="X")
        assert alerter.history[0].alert_type == "SAFETY_TRIGGERED"

    def test_alerter_convenience_kill_switch(self):
        from flinttrade_webhooks.alerter import AlertChannel, Alerter
        alerter = Alerter(channels=[AlertChannel.CONSOLE], throttle_seconds=0)
        alerter.kill_switch(activated=True, reason="Daily P&L kill")
        assert alerter.history[0].alert_type == "KILL_SWITCH_ACTIVATED"
        alerter.kill_switch(activated=False, reason="Manual reset")
        assert alerter.history[1].alert_type == "KILL_SWITCH_RESET"

    def test_alerter_telegram_calls_client(self):
        from flinttrade_webhooks.alerter import Alert, AlertChannel, Alerter
        mock_client = MagicMock()
        alerter = Alerter(
            telegram_bot=mock_client,
            channels=[AlertChannel.TELEGRAM],
            throttle_seconds=0,
        )
        alerter.send(Alert(alert_type="CUSTOM", message="Test"))
        mock_client.send_message.assert_called_once()

    def test_alerter_throttle_in_action(self):
        from flinttrade_webhooks.alerter import AlertChannel, Alerter
        alerter = Alerter(channels=[AlertChannel.CONSOLE], throttle_seconds=60)
        alerter.order_placed(symbol="X", action="BUY")
        alerter.order_placed(symbol="X", action="BUY")  # should be throttled
        assert len(alerter.history) == 1  # only first one recorded


# ======================================================================
# Package exports
# ======================================================================


class TestPackageExports:
    """Verify __init__.py exports."""

    def test_all_exports(self):
        from flinttrade_webhooks import __all__
        expected = [
            "WebhookReceiver",
            "Alerter",
            "AlertType", "AlertChannel",
        ]
        for name in expected:
            assert name in __all__, f"Missing export: {name}"
        assert "WebhookServer" not in __all__
        # Retired provider integrations must not be re-exported.
        for retired in ("TradingViewWebhook", "TradingViewAlert", "ChartInkWebhook", "ChartInkConfig",
                        "FlowBuilder", "FlowDefinition", "ExcelBridge", "VoiceOrderParser", "voice_bp"):
            assert retired not in __all__, f"Retired export resurfaced: {retired}"

    def test_version(self):
        from flinttrade_webhooks import __version__
        from flinttrade_core.version import APP_VERSION

        assert __version__ == APP_VERSION

    def test_package_exists(self):
        pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        assert os.path.exists(os.path.join(pkg_dir, "src", "flinttrade_webhooks", "__init__.py"))
        assert os.path.exists(os.path.join(pkg_dir, "README.md"))
