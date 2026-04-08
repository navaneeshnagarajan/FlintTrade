"""Multi-channel alert system — Telegram, console, and extensible channels.

Alert types:
- ORDER_PLACED, ORDER_FILLED, ORDER_CANCELLED
- SAFETY_TRIGGERED (with layer info)
- KILL_SWITCH_ACTIVATED, KILL_SWITCH_RESET
- STRATEGY_STARTED, STRATEGY_STOPPED, STRATEGY_ERROR
- CUSTOM

Alert throttling: max 1 alert per (symbol, alert_type) per configurable window
(default 60s) to prevent spam.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from packages.core.src.openalgo_client import OpenAlgoClient

logger = logging.getLogger("flinttrade.integration.alerter")


class AlertType(StrEnum):
    ORDER_PLACED = "ORDER_PLACED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    SAFETY_TRIGGERED = "SAFETY_TRIGGERED"
    KILL_SWITCH_ACTIVATED = "KILL_SWITCH_ACTIVATED"
    KILL_SWITCH_RESET = "KILL_SWITCH_RESET"
    STRATEGY_STARTED = "STRATEGY_STARTED"
    STRATEGY_STOPPED = "STRATEGY_STOPPED"
    STRATEGY_ERROR = "STRATEGY_ERROR"
    CUSTOM = "CUSTOM"


class AlertChannel(StrEnum):
    TELEGRAM = "TELEGRAM"
    WHATSAPP = "WHATSAPP"
    CONSOLE = "CONSOLE"


@dataclass
class Alert:
    """A single alert to be dispatched."""

    alert_type: str
    message: str
    symbol: str = ""
    exchange: str = ""
    action: str = ""
    quantity: str = ""
    price: str = ""
    pnl: str = ""
    strategy: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


def format_alert(alert: Alert) -> str:
    """Format an alert into a clean readable message."""
    parts = [f"[{alert.alert_type}]"]

    if alert.strategy:
        parts.append(f"Strategy: {alert.strategy}")

    if alert.symbol:
        line = alert.symbol
        if alert.exchange:
            line = f"{alert.symbol} ({alert.exchange})"
        if alert.action:
            line = f"{alert.action} {line}"
        if alert.quantity:
            line += f" qty={alert.quantity}"
        if alert.price and alert.price != "0":
            line += f" @ {alert.price}"
        parts.append(line)

    if alert.pnl:
        parts.append(f"P&L: {alert.pnl}")

    if alert.message:
        parts.append(alert.message)

    return " | ".join(parts)


class AlertThrottler:
    """Prevents alert spam — max 1 alert per (symbol, type) per window.

    Default window: 60 seconds.
    """

    def __init__(self, window_seconds: float = 60.0) -> None:
        self.window = window_seconds
        self._last_sent: dict[str, float] = {}

    def should_send(self, alert: Alert) -> bool:
        """Check if this alert should be sent or throttled."""
        key = f"{alert.alert_type}:{alert.symbol}"
        now = time.time()
        last = self._last_sent.get(key, 0.0)

        if now - last < self.window:
            return False

        self._last_sent[key] = now
        return True

    def reset(self) -> None:
        """Clear all throttle state."""
        self._last_sent.clear()


class Alerter:
    """Multi-channel alert dispatcher.

    Usage::

        alerter = Alerter(client=client, channels=[AlertChannel.TELEGRAM, AlertChannel.CONSOLE])
        alerter.order_placed(symbol="RELIANCE", exchange="NSE", action="BUY", quantity="10", price="2500")
        alerter.safety_triggered(layer="L1_ORDER", reason="Price deviation 12%", symbol="RELIANCE")
        alerter.send(Alert(alert_type="CUSTOM", message="My custom alert"))
    """

    def __init__(
        self,
        client: OpenAlgoClient | None = None,
        channels: list[AlertChannel] | None = None,
        throttle_seconds: float = 60.0,
    ) -> None:
        self._client = client
        self._channels = channels or [AlertChannel.CONSOLE]
        self._throttler = AlertThrottler(throttle_seconds)
        self._history: list[Alert] = []

    @property
    def history(self) -> list[Alert]:
        return list(self._history)

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    def order_placed(
        self, *, symbol: str, exchange: str = "", action: str = "",
        quantity: str = "", price: str = "", strategy: str = "",
        orderid: str = "",
    ) -> None:
        self.send(Alert(
            alert_type=AlertType.ORDER_PLACED.value,
            message=f"Order {orderid}" if orderid else "",
            symbol=symbol, exchange=exchange, action=action,
            quantity=quantity, price=price, strategy=strategy,
        ))

    def order_filled(
        self, *, symbol: str, exchange: str = "", action: str = "",
        quantity: str = "", price: str = "", pnl: str = "",
        strategy: str = "",
    ) -> None:
        self.send(Alert(
            alert_type=AlertType.ORDER_FILLED.value,
            message="",
            symbol=symbol, exchange=exchange, action=action,
            quantity=quantity, price=price, pnl=pnl, strategy=strategy,
        ))

    def order_cancelled(
        self, *, symbol: str, orderid: str = "", strategy: str = "",
    ) -> None:
        self.send(Alert(
            alert_type=AlertType.ORDER_CANCELLED.value,
            message=f"Cancelled {orderid}" if orderid else "",
            symbol=symbol, strategy=strategy,
        ))

    def safety_triggered(
        self, *, layer: str, reason: str, symbol: str = "",
        strategy: str = "",
    ) -> None:
        self.send(Alert(
            alert_type=AlertType.SAFETY_TRIGGERED.value,
            message=f"[{layer}] {reason}",
            symbol=symbol, strategy=strategy,
        ))

    def kill_switch(self, *, activated: bool, reason: str = "") -> None:
        atype = AlertType.KILL_SWITCH_ACTIVATED if activated else AlertType.KILL_SWITCH_RESET
        self.send(Alert(
            alert_type=atype.value,
            message=reason,
        ))

    def strategy_event(
        self, *, event: str, strategy: str, message: str = "",
    ) -> None:
        """Send a strategy lifecycle event (started/stopped/error)."""
        type_map = {
            "started": AlertType.STRATEGY_STARTED,
            "stopped": AlertType.STRATEGY_STOPPED,
            "error": AlertType.STRATEGY_ERROR,
        }
        atype = type_map.get(event.lower(), AlertType.CUSTOM)
        self.send(Alert(
            alert_type=atype.value,
            message=message,
            strategy=strategy,
        ))

    # ------------------------------------------------------------------
    # Core send
    # ------------------------------------------------------------------

    def send(self, alert: Alert) -> bool:
        """Send an alert through all configured channels.

        Returns True if the alert was sent (not throttled).
        """
        if not self._throttler.should_send(alert):
            logger.debug("Alert throttled: %s %s", alert.alert_type, alert.symbol)
            return False

        formatted = format_alert(alert)
        self._history.append(alert)

        for channel in self._channels:
            try:
                if channel == AlertChannel.TELEGRAM:
                    self._send_telegram(formatted)
                elif channel == AlertChannel.WHATSAPP:
                    self._send_whatsapp(formatted)
                elif channel == AlertChannel.CONSOLE:
                    self._send_console(formatted)
            except Exception as exc:
                logger.error("Alert channel %s failed: %s", channel, exc)

        return True

    def _send_telegram(self, message: str) -> None:
        """Send via OpenAlgo /api/v1/telegram endpoint."""
        if self._client is None:
            logger.warning("Telegram alert skipped — no OpenAlgo client")
            return
        try:
            self._client.telegram(message)
            logger.debug("Telegram alert sent")
        except Exception as exc:
            logger.error("Telegram send failed: %s", exc)

    def _send_whatsapp(self, message: str) -> None:
        """Send via WhatsApp webhook."""
        try:
            from packages.automation.src.whatsapp_alerts import WhatsAppAlerter
            alerter = WhatsAppAlerter()
            alerter.send_alert(message)
            logger.debug("WhatsApp alert sent")
        except Exception as exc:
            logger.error("WhatsApp send failed: %s", exc)

    def _send_console(self, message: str) -> None:
        """Log alert to console via Python logging."""
        logger.info("ALERT: %s", message)
