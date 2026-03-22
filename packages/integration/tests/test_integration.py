"""Tests for FlintTrade integration package.

DO NOT RUN — written for pytest. All tests use synthetic data, no API calls.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from unittest.mock import MagicMock

import pytest


# ======================================================================
# TradingView — payload parsing
# ======================================================================


class TestTradingViewPayloadParsing:
    """Test TradingView webhook payload parsing."""

    def test_parse_json_buy(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        payload = json.dumps({
            "action": "BUY", "symbol": "RELIANCE", "exchange": "NSE",
            "quantity": "10", "price": "0", "pricetype": "MARKET",
            "product": "MIS", "strategy": "Flint",
        })
        alert = parse_tradingview_payload(payload)
        assert alert.is_valid
        assert alert.action == "BUY"
        assert alert.symbol == "RELIANCE"
        assert alert.exchange == "NSE"
        assert alert.quantity == "10"
        assert alert.pricetype == "MARKET"
        assert alert.strategy == "Flint"

    def test_parse_json_sell(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        payload = json.dumps({"action": "sell", "symbol": "tcs", "quantity": "5"})
        alert = parse_tradingview_payload(payload)
        assert alert.is_valid
        assert alert.action == "SELL"
        assert alert.symbol == "TCS"

    def test_parse_json_defaults(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        payload = json.dumps({"action": "BUY", "symbol": "INFY"})
        alert = parse_tradingview_payload(payload)
        assert alert.is_valid
        assert alert.exchange == "NSE"
        assert alert.product == "MIS"
        assert alert.quantity == "1"

    def test_parse_text_simple(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        alert = parse_tradingview_payload("BUY NIFTY")
        assert alert.is_valid
        assert alert.action == "BUY"
        assert alert.symbol == "NIFTY"
        assert alert.exchange == "NSE"

    def test_parse_text_with_exchange_qty(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        alert = parse_tradingview_payload("BUY NIFTY NFO 75")
        assert alert.is_valid
        assert alert.symbol == "NIFTY"
        assert alert.exchange == "NFO"
        assert alert.quantity == "75"

    def test_parse_text_with_limit_price(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        alert = parse_tradingview_payload("BUY BANKNIFTY NFO 30 LIMIT 51000")
        assert alert.is_valid
        assert alert.pricetype == "LIMIT"
        assert alert.price == "51000"

    def test_parse_text_sell(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        alert = parse_tradingview_payload("SELL RELIANCE")
        assert alert.is_valid
        assert alert.action == "SELL"

    def test_parse_empty_payload(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        alert = parse_tradingview_payload("")
        assert not alert.is_valid
        assert "Empty" in alert.error

    def test_parse_invalid_json(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        alert = parse_tradingview_payload("{bad json")
        assert not alert.is_valid
        assert "Invalid JSON" in alert.error

    def test_parse_missing_action(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        alert = parse_tradingview_payload(json.dumps({"symbol": "RELIANCE"}))
        assert not alert.is_valid
        assert "action" in alert.error.lower()

    def test_parse_missing_symbol(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        alert = parse_tradingview_payload(json.dumps({"action": "BUY"}))
        assert not alert.is_valid
        assert "symbol" in alert.error.lower()

    def test_parse_text_too_short(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        alert = parse_tradingview_payload("BUY")
        assert not alert.is_valid

    def test_parse_invalid_action(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        alert = parse_tradingview_payload("HOLD NIFTY")
        assert not alert.is_valid

    def test_alert_to_order(self):
        from packages.integration.src.tradingview import alert_to_order, parse_tradingview_payload
        alert = parse_tradingview_payload(json.dumps({
            "action": "BUY", "symbol": "RELIANCE", "exchange": "NSE",
            "quantity": "10", "product": "CNC",
        }))
        order = alert_to_order(alert)
        assert order is not None
        assert order.symbol == "RELIANCE"
        assert order.action == "BUY"
        assert order.quantity == "10"
        assert order.product == "CNC"

    def test_alert_to_order_invalid(self):
        from packages.integration.src.tradingview import TradingViewAlert, alert_to_order
        alert = TradingViewAlert(is_valid=False)
        assert alert_to_order(alert) is None

    def test_bytes_payload(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        alert = parse_tradingview_payload(b"BUY NIFTY NFO 75")
        assert alert.is_valid
        assert alert.symbol == "NIFTY"

    def test_default_strategy_override(self):
        from packages.integration.src.tradingview import parse_tradingview_payload
        alert = parse_tradingview_payload("BUY NIFTY", default_strategy="MyStrat")
        assert alert.strategy == "MyStrat"


# ======================================================================
# TradingView — webhook authentication
# ======================================================================


class TestTradingViewAuth:
    """Test webhook signature verification."""

    def test_verify_valid_signature(self):
        from packages.integration.src.tradingview import verify_webhook_signature
        body = b'{"action":"BUY","symbol":"NIFTY"}'
        secret = "my_secret_key"
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert verify_webhook_signature(body, sig, secret)

    def test_verify_invalid_signature(self):
        from packages.integration.src.tradingview import verify_webhook_signature
        body = b'{"action":"BUY","symbol":"NIFTY"}'
        assert not verify_webhook_signature(body, "bad_signature", "my_secret_key")

    def test_verify_no_secret_skips(self):
        from packages.integration.src.tradingview import verify_webhook_signature
        assert verify_webhook_signature(b"data", "any", "")

    def test_handler_rejects_bad_sig(self):
        from packages.integration.src.tradingview import TradingViewWebhook
        tv = TradingViewWebhook(secret="secret123")
        alert = tv.handle('{"action":"BUY","symbol":"NIFTY"}', signature="badsig")
        assert not alert.is_valid
        assert "signature" in alert.error.lower()

    def test_handler_accepts_good_sig(self):
        from packages.integration.src.tradingview import TradingViewWebhook
        body = '{"action":"BUY","symbol":"NIFTY"}'
        secret = "secret123"
        sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        tv = TradingViewWebhook(secret=secret)
        alert = tv.handle(body, signature=sig)
        assert alert.is_valid

    def test_handler_no_secret_configured(self):
        from packages.integration.src.tradingview import TradingViewWebhook
        tv = TradingViewWebhook()
        alert = tv.handle('{"action":"BUY","symbol":"NIFTY"}')
        assert alert.is_valid


# ======================================================================
# ChartInk — symbol mapping
# ======================================================================


class TestChartInkSymbolMapping:
    """Test ChartInk payload parsing and symbol normalization."""

    def test_normalize_eq_suffix(self):
        from packages.integration.src.chartink import normalize_chartink_symbol
        assert normalize_chartink_symbol("RELIANCE-EQ") == "RELIANCE"

    def test_normalize_be_suffix(self):
        from packages.integration.src.chartink import normalize_chartink_symbol
        assert normalize_chartink_symbol("INFY-BE") == "INFY"

    def test_normalize_nse_prefix(self):
        from packages.integration.src.chartink import normalize_chartink_symbol
        assert normalize_chartink_symbol("NSE:RELIANCE") == "RELIANCE"

    def test_normalize_plain(self):
        from packages.integration.src.chartink import normalize_chartink_symbol
        assert normalize_chartink_symbol("TCS") == "TCS"

    def test_normalize_lowercase(self):
        from packages.integration.src.chartink import normalize_chartink_symbol
        assert normalize_chartink_symbol("reliance") == "RELIANCE"

    def test_parse_json_payload(self):
        from packages.integration.src.chartink import parse_chartink_payload
        payload = json.dumps({
            "scan_name": "OI Spurt",
            "stocks": "RELIANCE-EQ,TCS-EQ,INFY",
            "triggered_at": "2026-03-16 10:30:00",
        })
        result = parse_chartink_payload(payload)
        assert result.is_valid
        assert result.symbol_count == 3
        assert "RELIANCE" in result.symbols
        assert "TCS" in result.symbols
        assert "INFY" in result.symbols
        assert result.scan_name == "OI Spurt"

    def test_parse_csv_payload(self):
        from packages.integration.src.chartink import parse_chartink_payload
        result = parse_chartink_payload("RELIANCE,TCS,INFY")
        assert result.is_valid
        assert result.symbol_count == 3

    def test_parse_alert_list_field(self):
        from packages.integration.src.chartink import parse_chartink_payload
        payload = json.dumps({"alert_list": "HDFCBANK,ICICIBANK"})
        result = parse_chartink_payload(payload)
        assert result.is_valid
        assert "HDFCBANK" in result.symbols

    def test_parse_empty_payload(self):
        from packages.integration.src.chartink import parse_chartink_payload
        result = parse_chartink_payload("")
        assert not result.is_valid

    def test_parse_no_symbols(self):
        from packages.integration.src.chartink import parse_chartink_payload
        result = parse_chartink_payload(json.dumps({"scan_name": "Empty"}))
        assert not result.is_valid

    def test_scan_to_orders(self):
        from packages.integration.src.chartink import (
            ChartInkConfig, parse_chartink_payload, scan_result_to_orders,
        )
        result = parse_chartink_payload("RELIANCE,TCS,INFY")
        config = ChartInkConfig(action="BUY", quantity_per_symbol="10", exchange="NSE")
        orders = scan_result_to_orders(result, config)
        assert len(orders) == 3
        assert orders[0].symbol == "RELIANCE"
        assert orders[0].action == "BUY"
        assert orders[0].quantity == "10"

    def test_max_symbols_limit(self):
        from packages.integration.src.chartink import (
            ChartInkConfig, parse_chartink_payload, scan_result_to_orders,
        )
        symbols = ",".join(f"SYM{i}" for i in range(20))
        result = parse_chartink_payload(symbols)
        config = ChartInkConfig(max_symbols=5)
        orders = scan_result_to_orders(result, config)
        assert len(orders) == 5

    def test_webhook_handler(self):
        from packages.integration.src.chartink import ChartInkConfig, ChartInkWebhook
        ci = ChartInkWebhook(config=ChartInkConfig(action="BUY"))
        result = ci.handle("RELIANCE,TCS")
        assert result.is_valid
        orders = ci.to_orders(result)
        assert len(orders) == 2


# ======================================================================
# Webhook Server
# ======================================================================


class TestWebhookServer:
    """Test webhook server rate limiting and endpoint management."""

    def test_rate_limiter_allows_within_limit(self):
        from packages.integration.src.webhook_server import WebhookRateLimiter
        rl = WebhookRateLimiter(max_requests=5, window_seconds=60)
        for _ in range(5):
            assert rl.allow()
        assert not rl.allow()  # 6th should be blocked

    def test_rate_limiter_remaining(self):
        from packages.integration.src.webhook_server import WebhookRateLimiter
        rl = WebhookRateLimiter(max_requests=10, window_seconds=60)
        assert rl.remaining == 10
        rl.allow()
        assert rl.remaining == 9

    def test_server_creates_flask_app(self):
        from packages.integration.src.webhook_server import WebhookServer
        server = WebhookServer(port=9090)
        assert server.app is not None
        assert server.port == 9090

    def test_register_endpoint(self):
        from packages.integration.src.webhook_server import WebhookServer
        server = WebhookServer()
        handler = lambda body, headers: {"status": "ok"}
        server.register("/webhook/test", "test", handler)
        # Endpoint should exist in Flask app rules
        rules = [r.rule for r in server.app.url_map.iter_rules()]
        assert "/webhook/test" in rules

    def test_register_tradingview(self):
        from packages.integration.src.webhook_server import WebhookServer
        server = WebhookServer()
        handler = lambda body, headers: {"status": "ok"}
        server.register_tradingview(handler, strategy_id="my_strat")
        rules = [r.rule for r in server.app.url_map.iter_rules()]
        assert "/webhook/tradingview/my_strat" in rules

    def test_register_chartink(self):
        from packages.integration.src.webhook_server import WebhookServer
        server = WebhookServer()
        handler = lambda body, headers: {"status": "ok"}
        server.register_chartink(handler, strategy_id="scanner1")
        rules = [r.rule for r in server.app.url_map.iter_rules()]
        assert "/webhook/chartink/scanner1" in rules

    def test_health_endpoint(self):
        from packages.integration.src.webhook_server import WebhookServer
        server = WebhookServer()
        with server.app.test_client() as client:
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "ok"

    def test_webhook_auth_rejects_bad_secret(self):
        from packages.integration.src.webhook_server import WebhookServer
        server = WebhookServer()
        handler = lambda body, headers: {"result": "processed"}
        server.register("/webhook/secure", "secure", handler, secret="my_secret")
        with server.app.test_client() as client:
            resp = client.post(
                "/webhook/secure",
                data=b"test",
                headers={"X-Webhook-Secret": "wrong"},
            )
            assert resp.status_code == 401

    def test_webhook_auth_accepts_good_secret(self):
        from packages.integration.src.webhook_server import WebhookServer
        server = WebhookServer()
        handler = lambda body, headers: {"result": "processed"}
        server.register("/webhook/secure", "secure", handler, secret="my_secret")
        with server.app.test_client() as client:
            resp = client.post(
                "/webhook/secure",
                data=b"test",
                headers={"X-Webhook-Secret": "my_secret"},
            )
            assert resp.status_code == 200

    def test_webhook_no_secret_allows_all(self):
        from packages.integration.src.webhook_server import WebhookServer
        server = WebhookServer()
        handler = lambda body, headers: {"result": "ok"}
        server.register("/webhook/open", "open", handler)
        with server.app.test_client() as client:
            resp = client.post("/webhook/open", data=b"test")
            assert resp.status_code == 200

    def test_disable_endpoint(self):
        from packages.integration.src.webhook_server import WebhookServer
        server = WebhookServer()
        handler = lambda body, headers: {"result": "ok"}
        server.register("/webhook/toggle", "toggle", handler)
        server.disable_endpoint("/webhook/toggle")
        with server.app.test_client() as client:
            resp = client.post("/webhook/toggle", data=b"test")
            assert resp.status_code == 503

    def test_rate_limit_on_webhook(self):
        from packages.integration.src.webhook_server import WebhookServer
        server = WebhookServer(rate_limit=3, rate_window=60)
        handler = lambda body, headers: {"result": "ok"}
        server.register("/webhook/limited", "limited", handler)
        with server.app.test_client() as client:
            for _ in range(3):
                resp = client.post("/webhook/limited", data=b"test")
                assert resp.status_code == 200
            resp = client.post("/webhook/limited", data=b"test")
            assert resp.status_code == 429


# ======================================================================
# Flow Builder — validation
# ======================================================================


class TestFlowBuilder:
    """Test flow builder construction and validation."""

    def _build_simple_flow(self):
        from packages.integration.src.flow_builder import (
            ActionType, ConditionType, ExitType, FlowBuilder, SignalSource,
        )
        fb = FlowBuilder("Test Strategy")
        sig = fb.add_signal(SignalSource.TRADINGVIEW, label="TV Alert")
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
        from packages.integration.src.flow_builder import FlowBuilder
        fb = FlowBuilder("Empty")
        result = fb.validate()
        assert not result.is_valid

    def test_validate_no_entry_node(self):
        from packages.integration.src.flow_builder import FlowDefinition, FlowNode, validate_flow
        flow = FlowDefinition(name="Bad")
        flow.add_node(FlowNode(id="n1", node_type="ACTION", subtype="PLACE_ORDER"))
        result = validate_flow(flow)
        assert not result.is_valid

    def test_validate_broken_connection(self):
        from packages.integration.src.flow_builder import FlowDefinition, FlowNode, validate_flow
        flow = FlowDefinition(name="Bad", entry_node_id="n1")
        flow.add_node(FlowNode(
            id="n1", node_type="SIGNAL", subtype="TRADINGVIEW",
            next_nodes=["n999"],  # doesn't exist
        ))
        result = validate_flow(flow)
        assert not result.is_valid

    def test_validate_self_loop(self):
        from packages.integration.src.flow_builder import FlowDefinition, FlowNode, validate_flow
        flow = FlowDefinition(name="Loop", entry_node_id="n1")
        flow.add_node(FlowNode(
            id="n1", node_type="SIGNAL", subtype="TRADINGVIEW",
            next_nodes=["n1"],
        ))
        result = validate_flow(flow)
        assert not result.is_valid

    def test_validate_orphan_warning(self):
        from packages.integration.src.flow_builder import FlowDefinition, FlowNode, validate_flow
        flow = FlowDefinition(name="Orphan", entry_node_id="n1")
        flow.add_node(FlowNode(id="n1", node_type="SIGNAL", next_nodes=["n2"]))
        flow.add_node(FlowNode(id="n2", node_type="ACTION", subtype="PLACE_ORDER"))
        flow.add_node(FlowNode(id="n3", node_type="ACTION", subtype="SEND_ALERT"))  # orphan
        result = validate_flow(flow)
        assert any(w.node_id == "n3" for w in result.warnings)

    def test_validate_no_action_or_exit(self):
        from packages.integration.src.flow_builder import FlowDefinition, FlowNode, validate_flow
        flow = FlowDefinition(name="NoAction", entry_node_id="n1")
        flow.add_node(FlowNode(id="n1", node_type="SIGNAL", next_nodes=["n2"]))
        flow.add_node(FlowNode(id="n2", node_type="CONDITION"))
        result = validate_flow(flow)
        assert not result.is_valid

    def test_flow_json_roundtrip(self):
        from packages.integration.src.flow_builder import FlowDefinition
        fb = self._build_simple_flow()
        flow = fb.build()
        json_str = flow.to_json()
        restored = FlowDefinition.from_json(json_str)
        assert restored.name == flow.name
        assert len(restored.nodes) == len(flow.nodes)
        assert restored.entry_node_id == flow.entry_node_id

    def test_connect_nonexistent_raises(self):
        from packages.integration.src.flow_builder import FlowBuilder, SignalSource
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
        from packages.integration.src.alerter import Alert, format_alert
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
        from packages.integration.src.alerter import Alert, format_alert
        alert = Alert(
            alert_type="SAFETY_TRIGGERED",
            message="[L1_ORDER] Price deviation 12%",
            symbol="RELIANCE",
        )
        formatted = format_alert(alert)
        assert "SAFETY_TRIGGERED" in formatted
        assert "L1_ORDER" in formatted

    def test_throttle_blocks_duplicate(self):
        from packages.integration.src.alerter import Alert, AlertThrottler
        throttler = AlertThrottler(window_seconds=60)
        alert = Alert(alert_type="ORDER_PLACED", message="test", symbol="RELIANCE")
        assert throttler.should_send(alert)
        assert not throttler.should_send(alert)  # same symbol+type within 60s

    def test_throttle_allows_different_symbol(self):
        from packages.integration.src.alerter import Alert, AlertThrottler
        throttler = AlertThrottler(window_seconds=60)
        a1 = Alert(alert_type="ORDER_PLACED", message="test", symbol="RELIANCE")
        a2 = Alert(alert_type="ORDER_PLACED", message="test", symbol="TCS")
        assert throttler.should_send(a1)
        assert throttler.should_send(a2)  # different symbol

    def test_throttle_allows_different_type(self):
        from packages.integration.src.alerter import Alert, AlertThrottler
        throttler = AlertThrottler(window_seconds=60)
        a1 = Alert(alert_type="ORDER_PLACED", message="test", symbol="RELIANCE")
        a2 = Alert(alert_type="ORDER_FILLED", message="test", symbol="RELIANCE")
        assert throttler.should_send(a1)
        assert throttler.should_send(a2)  # different type

    def test_throttle_reset(self):
        from packages.integration.src.alerter import Alert, AlertThrottler
        throttler = AlertThrottler(window_seconds=60)
        alert = Alert(alert_type="ORDER_PLACED", message="test", symbol="RELIANCE")
        throttler.should_send(alert)
        throttler.reset()
        assert throttler.should_send(alert)  # reset clears throttle

    def test_alerter_console_channel(self):
        from packages.integration.src.alerter import AlertChannel, Alerter
        alerter = Alerter(channels=[AlertChannel.CONSOLE], throttle_seconds=0)
        sent = alerter.send(
            __import__("packages.integration.src.alerter", fromlist=["Alert"]).Alert(
                alert_type="CUSTOM", message="Hello"
            )
        )
        assert sent

    def test_alerter_convenience_order_placed(self):
        from packages.integration.src.alerter import AlertChannel, Alerter
        alerter = Alerter(channels=[AlertChannel.CONSOLE], throttle_seconds=0)
        alerter.order_placed(symbol="RELIANCE", exchange="NSE", action="BUY", quantity="10", price="2500")
        assert len(alerter.history) == 1
        assert alerter.history[0].alert_type == "ORDER_PLACED"

    def test_alerter_convenience_safety(self):
        from packages.integration.src.alerter import AlertChannel, Alerter
        alerter = Alerter(channels=[AlertChannel.CONSOLE], throttle_seconds=0)
        alerter.safety_triggered(layer="L1_ORDER", reason="Price deviation", symbol="X")
        assert alerter.history[0].alert_type == "SAFETY_TRIGGERED"

    def test_alerter_convenience_kill_switch(self):
        from packages.integration.src.alerter import AlertChannel, Alerter
        alerter = Alerter(channels=[AlertChannel.CONSOLE], throttle_seconds=0)
        alerter.kill_switch(activated=True, reason="Daily P&L kill")
        assert alerter.history[0].alert_type == "KILL_SWITCH_ACTIVATED"
        alerter.kill_switch(activated=False, reason="Manual reset")
        assert alerter.history[1].alert_type == "KILL_SWITCH_RESET"

    def test_alerter_telegram_calls_client(self):
        from packages.integration.src.alerter import Alert, AlertChannel, Alerter
        mock_client = MagicMock()
        alerter = Alerter(
            client=mock_client,
            channels=[AlertChannel.TELEGRAM],
            throttle_seconds=0,
        )
        alerter.send(Alert(alert_type="CUSTOM", message="Test"))
        mock_client.telegram.assert_called_once()

    def test_alerter_throttle_in_action(self):
        from packages.integration.src.alerter import AlertChannel, Alerter
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
        from packages.integration.src import __all__
        expected = [
            "TradingViewWebhook", "ChartInkWebhook", "WebhookServer",
            "FlowBuilder", "Alerter", "FlowDefinition",
            "AlertType", "AlertChannel",
        ]
        for name in expected:
            assert name in __all__, f"Missing export: {name}"

    def test_version(self):
        from packages.integration.src import __version__
        assert __version__ == "0.1.0-alpha"

    def test_package_exists(self):
        pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        assert os.path.exists(os.path.join(pkg_dir, "src", "__init__.py"))
        assert os.path.exists(os.path.join(pkg_dir, "README.md"))
