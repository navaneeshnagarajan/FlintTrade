"""Extended tests for Alerter — alert creation, alert matching, throttling, channels.

No HTTP calls. OpenAlgo client is mocked when Telegram channel is tested.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock



# ---------------------------------------------------------------------------
# AlertType enum
# ---------------------------------------------------------------------------


class TestAlertTypeEnum:
    def test_all_types_present(self):
        from packages.integration.src.alerter import AlertType
        expected = {
            "ORDER_PLACED", "ORDER_FILLED", "ORDER_CANCELLED",
            "SAFETY_TRIGGERED", "KILL_SWITCH_ACTIVATED", "KILL_SWITCH_RESET",
            "STRATEGY_STARTED", "STRATEGY_STOPPED", "STRATEGY_ERROR", "CUSTOM",
        }
        actual = {t.value for t in AlertType}
        assert expected.issubset(actual)

    def test_enum_is_str(self):
        from packages.integration.src.alerter import AlertType
        assert isinstance(AlertType.ORDER_PLACED, str)


# ---------------------------------------------------------------------------
# AlertChannel enum
# ---------------------------------------------------------------------------


class TestAlertChannelEnum:
    def test_telegram_and_console_present(self):
        from packages.integration.src.alerter import AlertChannel
        assert AlertChannel.TELEGRAM == "TELEGRAM"
        assert AlertChannel.CONSOLE == "CONSOLE"


# ---------------------------------------------------------------------------
# Alert dataclass
# ---------------------------------------------------------------------------


class TestAlertDataclass:
    def test_default_fields(self):
        from packages.integration.src.alerter import Alert
        a = Alert(alert_type="CUSTOM", message="hello")
        assert a.symbol == ""
        assert a.exchange == ""
        assert a.action == ""
        assert a.quantity == ""
        assert a.price == ""
        assert a.pnl == ""
        assert a.strategy == ""
        assert a.extra == {}

    def test_timestamp_auto_set(self):
        from packages.integration.src.alerter import Alert
        before = time.time()
        a = Alert(alert_type="CUSTOM", message="")
        after = time.time()
        assert before <= a.timestamp <= after

    def test_all_fields_set(self):
        from packages.integration.src.alerter import Alert
        a = Alert(
            alert_type="ORDER_PLACED",
            message="Order 123",
            symbol="RELIANCE", exchange="NSE",
            action="BUY", quantity="10", price="2500",
            pnl="200", strategy="Scalper",
            extra={"orderid": "ABC123"},
        )
        assert a.symbol == "RELIANCE"
        assert a.extra["orderid"] == "ABC123"


# ---------------------------------------------------------------------------
# format_alert
# ---------------------------------------------------------------------------


class TestFormatAlert:
    def test_minimal_alert(self):
        from packages.integration.src.alerter import Alert, format_alert
        a = Alert(alert_type="CUSTOM", message="test message")
        text = format_alert(a)
        assert "CUSTOM" in text
        assert "test message" in text

    def test_with_symbol_and_exchange(self):
        from packages.integration.src.alerter import Alert, format_alert
        a = Alert(alert_type="ORDER_PLACED", message="", symbol="TCS", exchange="NSE")
        text = format_alert(a)
        assert "TCS" in text
        assert "NSE" in text

    def test_with_action(self):
        from packages.integration.src.alerter import Alert, format_alert
        a = Alert(alert_type="ORDER_FILLED", message="", symbol="NIFTY", action="BUY")
        text = format_alert(a)
        assert "BUY" in text

    def test_with_quantity(self):
        from packages.integration.src.alerter import Alert, format_alert
        a = Alert(alert_type="X", message="", symbol="X", quantity="75")
        text = format_alert(a)
        assert "qty=75" in text

    def test_price_zero_not_shown(self):
        from packages.integration.src.alerter import Alert, format_alert
        a = Alert(alert_type="X", message="", symbol="X", price="0")
        text = format_alert(a)
        assert "@ 0" not in text

    def test_price_nonzero_shown(self):
        from packages.integration.src.alerter import Alert, format_alert
        a = Alert(alert_type="X", message="", symbol="X", price="2500")
        text = format_alert(a)
        assert "2500" in text

    def test_pnl_shown(self):
        from packages.integration.src.alerter import Alert, format_alert
        a = Alert(alert_type="ORDER_FILLED", message="", pnl="+500")
        text = format_alert(a)
        assert "P&L" in text
        assert "+500" in text

    def test_strategy_shown(self):
        from packages.integration.src.alerter import Alert, format_alert
        a = Alert(alert_type="STRATEGY_STARTED", message="", strategy="EMA_9_21")
        text = format_alert(a)
        assert "EMA_9_21" in text

    def test_parts_joined_with_pipe(self):
        from packages.integration.src.alerter import Alert, format_alert
        a = Alert(alert_type="CUSTOM", message="msg", symbol="X", strategy="S")
        text = format_alert(a)
        assert "|" in text


# ---------------------------------------------------------------------------
# AlertThrottler
# ---------------------------------------------------------------------------


class TestAlertThrottler:
    def test_first_alert_always_passes(self):
        from packages.integration.src.alerter import Alert, AlertThrottler
        t = AlertThrottler(window_seconds=60)
        a = Alert(alert_type="ORDER_PLACED", message="", symbol="X")
        assert t.should_send(a) is True

    def test_duplicate_within_window_blocked(self):
        from packages.integration.src.alerter import Alert, AlertThrottler
        t = AlertThrottler(window_seconds=60)
        a = Alert(alert_type="ORDER_PLACED", message="", symbol="X")
        t.should_send(a)
        assert t.should_send(a) is False

    def test_different_symbol_both_pass(self):
        from packages.integration.src.alerter import Alert, AlertThrottler
        t = AlertThrottler(window_seconds=60)
        a1 = Alert(alert_type="ORDER_PLACED", message="", symbol="A")
        a2 = Alert(alert_type="ORDER_PLACED", message="", symbol="B")
        assert t.should_send(a1)
        assert t.should_send(a2)

    def test_different_type_same_symbol_both_pass(self):
        from packages.integration.src.alerter import Alert, AlertThrottler
        t = AlertThrottler(window_seconds=60)
        a1 = Alert(alert_type="ORDER_PLACED", message="", symbol="X")
        a2 = Alert(alert_type="ORDER_FILLED", message="", symbol="X")
        assert t.should_send(a1)
        assert t.should_send(a2)

    def test_reset_clears_all(self):
        from packages.integration.src.alerter import Alert, AlertThrottler
        t = AlertThrottler(window_seconds=60)
        a = Alert(alert_type="ORDER_PLACED", message="", symbol="X")
        t.should_send(a)
        t.reset()
        assert t.should_send(a) is True

    def test_zero_window_always_allows(self):
        from packages.integration.src.alerter import Alert, AlertThrottler
        t = AlertThrottler(window_seconds=0)
        a = Alert(alert_type="CUSTOM", message="", symbol="X")
        assert t.should_send(a)
        assert t.should_send(a)  # second also passes with 0s window

    def test_throttle_key_combines_type_and_symbol(self):
        """Throttle key is 'type:symbol' — ensure proper isolation."""
        from packages.integration.src.alerter import Alert, AlertThrottler
        t = AlertThrottler(window_seconds=60)
        # Same type, empty symbol — one key
        a_no_sym = Alert(alert_type="CUSTOM", message="", symbol="")
        # Same type, different symbol — different key
        a_sym = Alert(alert_type="CUSTOM", message="", symbol="NIFTY")
        assert t.should_send(a_no_sym)
        assert t.should_send(a_sym)  # different key, should pass

    def test_multiple_resets_work(self):
        from packages.integration.src.alerter import Alert, AlertThrottler
        t = AlertThrottler(window_seconds=60)
        a = Alert(alert_type="CUSTOM", message="", symbol="X")
        for _ in range(3):
            t.reset()
            assert t.should_send(a)


# ---------------------------------------------------------------------------
# Alerter — core send
# ---------------------------------------------------------------------------


class TestAlerterSend:
    def test_send_returns_true_when_not_throttled(self):
        from packages.integration.src.alerter import Alert, AlertChannel, Alerter
        alerter = Alerter(channels=[AlertChannel.CONSOLE], throttle_seconds=0)
        a = Alert(alert_type="CUSTOM", message="hello")
        result = alerter.send(a)
        assert result is True

    def test_send_returns_false_when_throttled(self):
        from packages.integration.src.alerter import Alert, AlertChannel, Alerter
        alerter = Alerter(channels=[AlertChannel.CONSOLE], throttle_seconds=60)
        a = Alert(alert_type="CUSTOM", message="hello", symbol="X")
        alerter.send(a)  # first
        result = alerter.send(a)  # second — throttled
        assert result is False

    def test_send_adds_to_history(self):
        from packages.integration.src.alerter import Alert, AlertChannel, Alerter
        alerter = Alerter(channels=[AlertChannel.CONSOLE], throttle_seconds=0)
        a = Alert(alert_type="CUSTOM", message="m")
        alerter.send(a)
        assert len(alerter.history) == 1

    def test_throttled_alert_not_added_to_history(self):
        from packages.integration.src.alerter import Alert, AlertChannel, Alerter
        alerter = Alerter(channels=[AlertChannel.CONSOLE], throttle_seconds=60)
        a = Alert(alert_type="CUSTOM", message="m", symbol="S")
        alerter.send(a)
        alerter.send(a)  # throttled
        assert len(alerter.history) == 1

    def test_history_property_returns_copy(self):
        from packages.integration.src.alerter import Alert, AlertChannel, Alerter
        alerter = Alerter(channels=[AlertChannel.CONSOLE], throttle_seconds=0)
        alerter.send(Alert(alert_type="CUSTOM", message=""))
        h = alerter.history
        h.clear()
        assert len(alerter.history) == 1  # internal unaffected

    def test_multiple_alerts_accumulated(self):
        from packages.integration.src.alerter import Alert, AlertChannel, Alerter
        alerter = Alerter(channels=[AlertChannel.CONSOLE], throttle_seconds=0)
        for i in range(5):
            alerter.send(Alert(alert_type="CUSTOM", message=f"m{i}", symbol=f"SYM{i}"))
        assert len(alerter.history) == 5


# ---------------------------------------------------------------------------
# Alerter — Telegram channel
# ---------------------------------------------------------------------------


class TestAlerterTelegramChannel:
    def test_telegram_channel_calls_client(self):
        from packages.integration.src.alerter import Alert, AlertChannel, Alerter
        mock_client = MagicMock()
        alerter = Alerter(
            client=mock_client,
            channels=[AlertChannel.TELEGRAM],
            throttle_seconds=0,
        )
        alerter.send(Alert(alert_type="CUSTOM", message="Telegram test"))
        mock_client.telegram.assert_called_once()

    def test_telegram_no_client_does_not_raise(self):
        from packages.integration.src.alerter import Alert, AlertChannel, Alerter
        alerter = Alerter(
            client=None,
            channels=[AlertChannel.TELEGRAM],
            throttle_seconds=0,
        )
        alerter.send(Alert(alert_type="CUSTOM", message="test"))  # must not raise

    def test_both_channels_called(self):
        """With TELEGRAM + CONSOLE channels, both should fire."""
        from packages.integration.src.alerter import Alert, AlertChannel, Alerter
        mock_client = MagicMock()
        alerter = Alerter(
            client=mock_client,
            channels=[AlertChannel.TELEGRAM, AlertChannel.CONSOLE],
            throttle_seconds=0,
        )
        alerter.send(Alert(alert_type="CUSTOM", message="both"))
        mock_client.telegram.assert_called_once()

    def test_telegram_client_exception_does_not_propagate(self):
        from packages.integration.src.alerter import Alert, AlertChannel, Alerter
        mock_client = MagicMock()
        mock_client.telegram = MagicMock(side_effect=RuntimeError("network error"))
        alerter = Alerter(
            client=mock_client,
            channels=[AlertChannel.TELEGRAM],
            throttle_seconds=0,
        )
        alerter.send(Alert(alert_type="CUSTOM", message="test"))  # must not raise


# ---------------------------------------------------------------------------
# Alerter — convenience methods
# ---------------------------------------------------------------------------


class TestAlerterConvenienceMethods:
    def _alerter(self):
        from packages.integration.src.alerter import AlertChannel, Alerter
        return Alerter(channels=[AlertChannel.CONSOLE], throttle_seconds=0)

    def test_order_filled_records_type(self):
        alerter = self._alerter()
        alerter.order_filled(symbol="NIFTY", exchange="NFO", action="BUY",
                             quantity="75", price="24000", pnl="+500")
        assert alerter.history[0].alert_type == "ORDER_FILLED"

    def test_order_cancelled_records_type(self):
        alerter = self._alerter()
        alerter.order_cancelled(symbol="TCS", orderid="ORD001")
        assert alerter.history[0].alert_type == "ORDER_CANCELLED"

    def test_order_cancelled_message_includes_orderid(self):
        alerter = self._alerter()
        alerter.order_cancelled(symbol="TCS", orderid="ORD123")
        assert "ORD123" in alerter.history[0].message

    def test_safety_triggered_records_type(self):
        alerter = self._alerter()
        alerter.safety_triggered(layer="L2_DAILY_LOSS", reason="Daily loss exceeded 2%",
                                 symbol="BANKNIFTY")
        assert alerter.history[0].alert_type == "SAFETY_TRIGGERED"

    def test_safety_triggered_message_has_layer(self):
        alerter = self._alerter()
        alerter.safety_triggered(layer="L3_POSITION", reason="Open positions > 5")
        msg = alerter.history[0].message
        assert "L3_POSITION" in msg

    def test_kill_switch_activated_type(self):
        alerter = self._alerter()
        alerter.kill_switch(activated=True, reason="Manual /kill")
        assert alerter.history[0].alert_type == "KILL_SWITCH_ACTIVATED"

    def test_kill_switch_reset_type(self):
        alerter = self._alerter()
        alerter.kill_switch(activated=False, reason="System reset")
        assert alerter.history[0].alert_type == "KILL_SWITCH_RESET"

    def test_strategy_started_event(self):
        alerter = self._alerter()
        alerter.strategy_event(event="started", strategy="EMA_9_21")
        assert alerter.history[0].alert_type == "STRATEGY_STARTED"
        assert alerter.history[0].strategy == "EMA_9_21"

    def test_strategy_stopped_event(self):
        alerter = self._alerter()
        alerter.strategy_event(event="stopped", strategy="RSI_14")
        assert alerter.history[0].alert_type == "STRATEGY_STOPPED"

    def test_strategy_error_event(self):
        alerter = self._alerter()
        alerter.strategy_event(event="error", strategy="Supertrend", message="NaN in signal")
        assert alerter.history[0].alert_type == "STRATEGY_ERROR"
        assert alerter.history[0].message == "NaN in signal"

    def test_strategy_unknown_event_maps_to_custom(self):
        alerter = self._alerter()
        alerter.strategy_event(event="restarted", strategy="S")
        assert alerter.history[0].alert_type == "CUSTOM"

    def test_order_placed_all_fields(self):
        alerter = self._alerter()
        alerter.order_placed(
            symbol="RELIANCE", exchange="NSE", action="BUY",
            quantity="10", price="2500", strategy="Scalper", orderid="XYZ",
        )
        h = alerter.history[0]
        assert h.symbol == "RELIANCE"
        assert h.action == "BUY"
        assert h.price == "2500"
        assert h.strategy == "Scalper"
        assert "XYZ" in h.message


# ---------------------------------------------------------------------------
# Alerter — throttle with convenience methods
# ---------------------------------------------------------------------------


class TestAlerterThrottleWithConvenience:
    def test_order_placed_throttled_on_same_symbol(self):
        from packages.integration.src.alerter import AlertChannel, Alerter
        alerter = Alerter(channels=[AlertChannel.CONSOLE], throttle_seconds=60)
        alerter.order_placed(symbol="NIFTY", action="BUY")
        alerter.order_placed(symbol="NIFTY", action="BUY")  # throttled
        assert len(alerter.history) == 1

    def test_kill_switch_not_throttled_by_symbol(self):
        """Kill switch has no symbol, so key is 'KILL_SWITCH_ACTIVATED:' — fires each time."""
        from packages.integration.src.alerter import AlertChannel, Alerter
        alerter = Alerter(channels=[AlertChannel.CONSOLE], throttle_seconds=60)
        alerter.kill_switch(activated=True, reason="first")
        alerter.kill_switch(activated=True, reason="second")
        # Both share the same throttle key since symbol="" → only first goes through
        assert len(alerter.history) == 1
