"""WhatsApp alert system via configurable webhook URL.

Sends trading alerts to WhatsApp using any HTTP-based bridge:
- WhatsApp Business Cloud API
- whatsapp-web.js HTTP bridge
- Any custom webhook that accepts JSON POST

Configuration:
  WHATSAPP_WEBHOOK_URL env var or workspace.json ``whatsapp.webhook_url``
  WHATSAPP_ENABLED env var or workspace.json ``whatsapp.enabled``

Rate limiting: max 30 messages per minute to avoid spam / API throttling.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("flinttrade.automation.whatsapp")

# Maximum messages per minute
_MAX_MESSAGES_PER_MINUTE = 30
_RATE_WINDOW_SECONDS = 60.0


@dataclass
class WhatsAppConfig:
    """WhatsApp alerter configuration."""

    webhook_url: str = ""
    enabled: bool = False

    @classmethod
    def from_env(cls) -> WhatsAppConfig:
        """Load from env vars, falling back to the UI-persisted settings.

        The workspace stores only a ``secret://`` reference; the URL itself is
        resolved through ``flinttrade_core.whatsapp_config`` (secret file, with
        the legacy plaintext key as fallback). A bare reference string is never
        used as a URL.
        """
        webhook_url = os.getenv("WHATSAPP_WEBHOOK_URL", "")
        enabled = os.getenv("WHATSAPP_ENABLED", "")

        if not webhook_url:
            try:
                from flinttrade_core.whatsapp_config import resolve_whatsapp_webhook_url
                from flinttrade_core.workspace import Workspace

                ws = Workspace()
                webhook_url = resolve_whatsapp_webhook_url(ws)
                if not enabled:
                    enabled = "true" if ws.get("whatsapp.enabled", False) else "false"
            except Exception:
                logger.warning("Failed to load WhatsApp config from workspace", exc_info=True)

        if webhook_url.startswith("secret://"):
            webhook_url = ""

        return cls(
            webhook_url=webhook_url,
            enabled=(enabled or "false").lower() == "true",
        )


class WhatsAppAlerter:
    """Send trading alerts to WhatsApp via a webhook URL.

    The webhook receives a JSON POST with ``{"message": "..."}`` body.
    Compatible with any bridge that accepts this shape.

    Usage::

        alerter = WhatsAppAlerter()
        alerter.send_alert("NIFTY crossed 24000!")
        alerter.send_signal({"symbol": "RELIANCE", "signal": "BUY", "confidence": 0.85})
        alerter.send_order_update({"symbol": "INFY", "action": "BUY", "quantity": 50, "status": "FILLED"})
    """

    def __init__(self, config: WhatsAppConfig | None = None) -> None:
        self.config = config or WhatsAppConfig.from_env()
        self._send_timestamps: list[float] = []
        self._history: list[dict[str, Any]] = []

    @property
    def history(self) -> list[dict[str, Any]]:
        """Return a copy of sent message history."""
        return list(self._history)

    @property
    def is_configured(self) -> bool:
        """Check if the alerter has a valid webhook URL and is enabled."""
        return bool(self.config.webhook_url) and self.config.enabled

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _check_rate_limit(self) -> bool:
        """Return True if sending is allowed under the rate limit.

        Enforces max 30 messages per 60-second sliding window.
        """
        now = time.time()
        cutoff = now - _RATE_WINDOW_SECONDS
        # Prune old timestamps
        self._send_timestamps = [
            ts for ts in self._send_timestamps if ts > cutoff
        ]
        return len(self._send_timestamps) < _MAX_MESSAGES_PER_MINUTE

    def _record_send(self) -> None:
        """Record a successful send for rate limiting."""
        self._send_timestamps.append(time.time())

    # ------------------------------------------------------------------
    # Core send
    # ------------------------------------------------------------------

    def _send_webhook(self, payload: dict[str, Any]) -> bool:
        """POST JSON payload to the configured webhook URL.

        Returns True on success (2xx response).
        """
        if not self.is_configured:
            logger.warning("WhatsApp not configured — message not sent")
            return False

        if not self._check_rate_limit():
            logger.warning("WhatsApp rate limit exceeded (max %d/min)", _MAX_MESSAGES_PER_MINUTE)
            return False

        try:
            import httpx
            resp = httpx.post(
                self.config.webhook_url,
                json=payload,
                timeout=10,
            )
            if 200 <= resp.status_code < 300:
                self._record_send()
                self._history.append(payload)
                logger.debug("WhatsApp alert sent: %s", payload.get("message", "")[:80])
                return True
            logger.error("WhatsApp webhook returned HTTP %d", resp.status_code)
            return False
        except Exception as exc:
            logger.error("WhatsApp send failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def send_alert(self, message: str) -> bool:
        """Send a plain text alert message.

        Args:
            message: The alert text to send.

        Returns:
            True if the message was sent successfully.
        """
        return self._send_webhook({"message": message})

    def send_signal(self, signal: dict[str, Any]) -> bool:
        """Send a trading signal alert.

        Args:
            signal: Dict with keys like ``symbol``, ``signal``/``signal_type``,
                    ``confidence``, ``exchange``, etc.

        Returns:
            True if the message was sent successfully.
        """
        symbol = signal.get("symbol", "?")
        sig_type = signal.get("signal_type", signal.get("signal", "?"))
        confidence = signal.get("confidence", "")
        exchange = signal.get("exchange", "")

        parts = [f"[SIGNAL] {sig_type} {symbol}"]
        if exchange:
            parts[0] += f" ({exchange})"
        if confidence:
            parts.append(f"Confidence: {confidence}")

        text = " | ".join(parts)
        return self._send_webhook({"message": text, "type": "signal", "data": signal})

    def send_order_update(self, order: dict[str, Any]) -> bool:
        """Send an order status update.

        Args:
            order: Dict with keys like ``symbol``, ``action``, ``quantity``,
                   ``price``, ``status``, ``orderid``.

        Returns:
            True if the message was sent successfully.
        """
        symbol = order.get("symbol", "?")
        action = order.get("action", "?")
        qty = order.get("quantity", "?")
        price = order.get("price", "")
        status = order.get("status", "")
        orderid = order.get("orderid", "")

        parts = [f"[ORDER] {action} {symbol} qty={qty}"]
        if price:
            parts[0] += f" @ {price}"
        if status:
            parts.append(f"Status: {status}")
        if orderid:
            parts.append(f"ID: {orderid}")

        text = " | ".join(parts)
        return self._send_webhook({"message": text, "type": "order", "data": order})
