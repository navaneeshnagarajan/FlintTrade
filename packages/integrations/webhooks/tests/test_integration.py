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
# Flow Builder — validation
# ======================================================================


class TestFlowBuilder:
    """Test flow builder construction and validation."""

    def _build_simple_flow(self):
        from flinttrade_webhooks.flow_builder import (
            ActionType, ConditionType, ExitType, FlowBuilder, SignalSource,
        )
        fb = FlowBuilder("Test Strategy")
        sig = fb.add_signal(SignalSource.WEBHOOK, label="Webhook Alert")
        cond = fb.add_condition(ConditionType.PRICE_ABOVE, config={"value": 24000})
        act = fb.add_action(ActionType.PLACE_ORDER, config={"symbol": "NIFTY"})
        exit_ = fb.add_exit(ExitType.STOP_LOSS, config={"points": 100})
        fb.connect(sig, cond)
        fb.connect(cond, act)
        fb.connect(act, exit_)
        return fb

    def test_build_valid_flow(self):
        fb = self._build_simple_flow()
        result = fb.validate()
        assert result.is_valid

    def test_flow_has_correct_node_count(self):
        fb = self._build_simple_flow()
        flow = fb.build()
        assert len(flow.nodes) == 4

    def test_flow_entry_is_signal(self):
        fb = self._build_simple_flow()
        flow = fb.build()
        entry = flow.nodes[flow.entry_node_id]
        assert entry.node_type == "SIGNAL"

    def test_validate_empty_flow(self):
        from flinttrade_webhooks.flow_builder import FlowBuilder
        fb = FlowBuilder("Empty")
        result = fb.validate()
        assert not result.is_valid

    def test_validate_no_entry_node(self):
        from flinttrade_webhooks.flow_builder import FlowDefinition, FlowNode, validate_flow
        flow = FlowDefinition(name="Bad")
        flow.add_node(FlowNode(id="n1", node_type="ACTION", subtype="PLACE_ORDER"))
        result = validate_flow(flow)
        assert not result.is_valid

    def test_validate_broken_connection(self):
        from flinttrade_webhooks.flow_builder import FlowDefinition, FlowNode, validate_flow
        flow = FlowDefinition(name="Bad", entry_node_id="n1")
        flow.add_node(FlowNode(
            id="n1", node_type="SIGNAL", subtype="WEBHOOK",
            next_nodes=["n999"],  # doesn't exist
        ))
        result = validate_flow(flow)
        assert not result.is_valid

    def test_validate_self_loop(self):
        from flinttrade_webhooks.flow_builder import FlowDefinition, FlowNode, validate_flow
        flow = FlowDefinition(name="Loop", entry_node_id="n1")
        flow.add_node(FlowNode(
            id="n1", node_type="SIGNAL", subtype="WEBHOOK",
            next_nodes=["n1"],
        ))
        result = validate_flow(flow)
        assert not result.is_valid

    def test_validate_orphan_warning(self):
        from flinttrade_webhooks.flow_builder import FlowDefinition, FlowNode, validate_flow
        flow = FlowDefinition(name="Orphan", entry_node_id="n1")
        flow.add_node(FlowNode(id="n1", node_type="SIGNAL", next_nodes=["n2"]))
        flow.add_node(FlowNode(id="n2", node_type="ACTION", subtype="PLACE_ORDER"))
        flow.add_node(FlowNode(id="n3", node_type="ACTION", subtype="SEND_ALERT"))  # orphan
        result = validate_flow(flow)
        assert any(w.node_id == "n3" for w in result.warnings)

    def test_validate_no_action_or_exit(self):
        from flinttrade_webhooks.flow_builder import FlowDefinition, FlowNode, validate_flow
        flow = FlowDefinition(name="NoAction", entry_node_id="n1")
        flow.add_node(FlowNode(id="n1", node_type="SIGNAL", next_nodes=["n2"]))
        flow.add_node(FlowNode(id="n2", node_type="CONDITION"))
        result = validate_flow(flow)
        assert not result.is_valid

    def test_flow_json_roundtrip(self):
        from flinttrade_webhooks.flow_builder import FlowDefinition
        fb = self._build_simple_flow()
        flow = fb.build()
        json_str = flow.to_json()
        restored = FlowDefinition.from_json(json_str)
        assert restored.name == flow.name
        assert len(restored.nodes) == len(flow.nodes)
        assert restored.entry_node_id == flow.entry_node_id

    def test_connect_nonexistent_raises(self):
        from flinttrade_webhooks.flow_builder import FlowBuilder, SignalSource
        fb = FlowBuilder("Bad Connect")
        sig = fb.add_signal(SignalSource.MANUAL)
        with pytest.raises(ValueError, match="not found"):
            fb.connect(sig, "nonexistent")


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
            client=mock_client,
            channels=[AlertChannel.TELEGRAM],
            throttle_seconds=0,
        )
        alerter.send(Alert(alert_type="CUSTOM", message="Test"))
        mock_client.telegram.assert_called_once()

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
            "FlowBuilder", "Alerter", "FlowDefinition",
            "AlertType", "AlertChannel",
        ]
        for name in expected:
            assert name in __all__, f"Missing export: {name}"
        assert "WebhookServer" not in __all__
        # Retired provider integrations must not be re-exported.
        for retired in ("TradingViewWebhook", "TradingViewAlert", "ChartInkWebhook", "ChartInkConfig"):
            assert retired not in __all__, f"Retired export resurfaced: {retired}"

    def test_version(self):
        from flinttrade_webhooks import __version__
        from flinttrade_core.version import APP_VERSION

        assert __version__ == APP_VERSION

    def test_package_exists(self):
        pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        assert os.path.exists(os.path.join(pkg_dir, "src", "flinttrade_webhooks", "__init__.py"))
        assert os.path.exists(os.path.join(pkg_dir, "README.md"))
