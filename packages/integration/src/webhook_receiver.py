"""Generic webhook receiver for external signal sources.

Receives, authenticates, parses, and dispatches webhooks from:
- TradingView alert webhooks
- ChartInk scanner webhooks
- Custom / generic JSON webhooks

Security: HMAC-SHA256 signature verification via ``X-Signature`` header
(``sha256=<hex>`` format, compatible with GitHub-style webhook signing).

Rate limiting: in-memory sliding-window per :class:`WebhookConfig`.

Dispatch: routes payloads to handler coroutines based on ``action`` field.

Example::

    from packages.integration.src.webhook_receiver import (
        WebhookConfig, WebhookReceiver,
    )

    receiver = WebhookReceiver(WebhookConfig(secret="my-secret"))

    # Simulate receiving a TradingView alert
    raw = {
        "action": "BUY",
        "symbol": "NIFTY",
        "exchange": "NFO",
        "quantity": "75",
    }
    payload = receiver.parse_tradingview(raw)
    import asyncio
    result = asyncio.run(receiver.dispatch(payload))
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("flinttrade.integration.webhook_receiver")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class WebhookConfig(BaseModel):
    """Configuration for :class:`WebhookReceiver`.

    Attributes:
        secret: HMAC-SHA256 signing secret.  Empty string disables verification
            only when ``skip_verification`` is explicitly set to ``True``.
        allowed_sources: Sources whose payloads are accepted.
        rate_limit: Maximum webhooks allowed per 60-second window.
        log_payloads: When ``True``, raw payload dicts are stored in
            :attr:`WebhookReceiver.log`.
        skip_verification: When ``True``, HMAC verification is skipped even
            if ``secret`` is empty.  Must be set explicitly — opt-in only.
    """

    secret: str = ""
    allowed_sources: list[str] = Field(
        default_factory=lambda: ["tradingview", "chartink", "custom"]
    )
    rate_limit: int = Field(default=60, ge=1, le=10_000)
    log_payloads: bool = True
    skip_verification: bool = False


# ---------------------------------------------------------------------------
# Payload model
# ---------------------------------------------------------------------------


class WebhookPayload(BaseModel):
    """Normalised webhook payload.

    Attributes:
        source: Originating source identifier (e.g. ``"tradingview"``).
        action: Requested action (``"place_order"``, ``"cancel_order"``,
            ``"alert"``, ``"signal"``).
        symbol: Optional instrument ticker.
        exchange: Optional exchange code.
        data: Additional key/value data from the raw webhook.
        timestamp: UTC timestamp when the payload was received/created.
    """

    source: str
    action: str
    symbol: str | None = None
    exchange: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("action")
    @classmethod
    def _normalise_action(cls, v: str) -> str:
        return v.lower().strip()

    @field_validator("source")
    @classmethod
    def _normalise_source(cls, v: str) -> str:
        return v.lower().strip()


# ---------------------------------------------------------------------------
# Log entry
# ---------------------------------------------------------------------------


class WebhookLogEntry(BaseModel):
    """Single entry in the webhook history log.

    Attributes:
        received_at: UTC epoch float when the webhook arrived.
        source: Parsed source identifier.
        action: Normalised action string.
        symbol: Optional symbol.
        status: ``"dispatched"``, ``"rate_limited"``, ``"auth_failed"``,
            ``"parse_error"``, or ``"unknown_action"``.
        detail: Additional detail or error message.
        raw: Original raw payload dict (only stored when
            :attr:`WebhookConfig.log_payloads` is ``True``).
    """

    received_at: float
    source: str
    action: str
    symbol: str | None = None
    status: str = "dispatched"
    detail: str = ""
    raw: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Rate limiter (in-memory, per receiver instance)
# ---------------------------------------------------------------------------


class _SlidingWindowLimiter:
    """Thread-safe sliding-window rate limiter.

    Args:
        max_requests: Maximum requests allowed in the window.
        window_seconds: Duration of the sliding window in seconds.
    """

    def __init__(self, max_requests: int, window_seconds: float = 60.0) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._timestamps: deque[float] = deque()

    def allow(self) -> bool:
        """Check whether a new request fits within the rate limit.

        Returns:
            ``True`` if allowed, ``False`` if limit exceeded.
        """
        now = time.monotonic()
        cutoff = now - self._window
        # Prune expired entries
        while self._timestamps and self._timestamps[0] <= cutoff:
            self._timestamps.popleft()
        if len(self._timestamps) >= self._max:
            return False
        self._timestamps.append(now)
        return True

    @property
    def remaining(self) -> int:
        """Requests remaining in the current window.

        Returns:
            Non-negative integer count.
        """
        now = time.monotonic()
        cutoff = now - self._window
        active = sum(1 for t in self._timestamps if t > cutoff)
        return max(0, self._max - active)


# ---------------------------------------------------------------------------
# WebhookReceiver
# ---------------------------------------------------------------------------


class WebhookReceiver:
    """Parse, verify, and dispatch webhooks from external sources.

    Args:
        config: :class:`WebhookConfig` instance controlling security and
            rate limiting.

    Attributes:
        log: In-memory list of :class:`WebhookLogEntry` records (most
            recent last).  Capped at 1 000 entries.
    """

    _LOG_CAPACITY = 1_000

    def __init__(self, config: WebhookConfig) -> None:
        self._config = config
        self._limiter = _SlidingWindowLimiter(config.rate_limit)
        self.log: list[WebhookLogEntry] = []

        if not config.secret and not config.skip_verification:
            logger.warning(
                "WebhookReceiver initialised without a signing secret and "
                "skip_verification=False — all incoming webhooks will be REJECTED. "
                "Set config.secret or set skip_verification=True to explicitly "
                "disable signature verification."
            )

    # ------------------------------------------------------------------
    # Signature verification
    # ------------------------------------------------------------------

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """Verify HMAC-SHA256 webhook signature.

        Accepts signatures in the format ``sha256=<hex>`` (GitHub style)
        or plain ``<hex>``.

        When ``config.secret`` is empty and ``config.skip_verification`` is
        ``False`` (the default), returns ``False`` so that unsigned webhooks are
        rejected.  To explicitly disable verification set
        ``skip_verification=True`` on :class:`WebhookConfig`.

        Args:
            payload: Raw request body bytes.
            signature: Value of the ``X-Signature`` header.

        Returns:
            ``True`` if the signature is valid or verification is explicitly
            skipped via ``skip_verification=True``.  ``False`` otherwise.
        """
        if not self._config.secret:
            # Explicit opt-out: caller has acknowledged there is no secret.
            if self._config.skip_verification:
                return True
            # Secret is absent and skip_verification is False — reject.
            logger.warning(
                "verify_signature called with no secret configured — rejecting request"
            )
            return False
        if not signature:
            return False

        # Strip "sha256=" prefix if present
        sig_hex = signature.removeprefix("sha256=")

        expected = hmac.new(
            self._config.secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, sig_hex)

    # ------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------

    def parse_tradingview(self, raw: dict[str, Any]) -> WebhookPayload:
        """Parse a TradingView alert webhook payload.

        TradingView sends JSON with ``action``, ``symbol``, ``exchange``,
        ``quantity``, ``price``, ``pricetype``, and ``product`` fields.
        Unknown fields are preserved in ``data``.

        Args:
            raw: Decoded JSON dict from the TradingView webhook request.

        Returns:
            Populated :class:`WebhookPayload`.
        """
        action_raw = str(raw.get("action", "")).upper()
        # Map TradingView BUY/SELL to FlintTrade action vocabulary
        action = "place_order" if action_raw in ("BUY", "SELL") else action_raw.lower() or "signal"

        extra = {k: v for k, v in raw.items() if k not in {"action", "symbol", "exchange"}}
        # Include the original TV action so downstream handlers can use it
        extra.setdefault("tv_action", action_raw)

        return WebhookPayload(
            source="tradingview",
            action=action,
            symbol=str(raw.get("symbol", "")).upper() or None,
            exchange=str(raw.get("exchange", "NSE")).upper() or None,
            data={k: v for k, v in extra.items()},
        )

    def parse_chartink(self, raw: dict[str, Any]) -> WebhookPayload:
        """Parse a ChartInk scanner webhook payload.

        ChartInk sends ``scan_name``, ``stocks``/``alert_list``, and
        ``triggered_at`` fields.  Symbols are normalised and stored in
        ``data["symbols"]``.

        Args:
            raw: Decoded JSON dict from the ChartInk webhook request.

        Returns:
            Populated :class:`WebhookPayload`.
        """
        # Extract symbol list
        symbols_raw: str | list[str] = (
            raw.get("stocks")
            or raw.get("alert_list")
            or raw.get("symbols")
            or ""
        )
        if isinstance(symbols_raw, str):
            symbols = [s.strip().upper() for s in symbols_raw.split(",") if s.strip()]
        elif isinstance(symbols_raw, list):
            symbols = [str(s).strip().upper() for s in symbols_raw if s]
        else:
            symbols = []

        first_symbol = symbols[0] if symbols else None

        return WebhookPayload(
            source="chartink",
            action="signal",
            symbol=first_symbol,
            exchange=str(raw.get("exchange", "NSE")).upper() or None,
            data={
                "scan_name": str(raw.get("scan_name", "")),
                "symbols": symbols,
                "triggered_at": str(raw.get("triggered_at", "")),
            },
        )

    def parse_custom(self, raw: dict[str, Any]) -> WebhookPayload:
        """Parse a generic custom JSON webhook payload.

        Expects an ``action`` field; all other fields are passed through
        in ``data``.  Defaults ``action`` to ``"signal"`` when absent.

        Args:
            raw: Decoded JSON dict from the custom webhook request.

        Returns:
            Populated :class:`WebhookPayload`.
        """
        action = str(raw.get("action", "signal"))
        symbol_raw = raw.get("symbol") or raw.get("ticker")
        symbol = str(symbol_raw).upper() if symbol_raw else None
        exchange_raw = raw.get("exchange")
        exchange = str(exchange_raw).upper() if exchange_raw else None

        extra = {
            k: v for k, v in raw.items()
            if k not in {"action", "symbol", "ticker", "exchange"}
        }

        return WebhookPayload(
            source="custom",
            action=action,
            symbol=symbol,
            exchange=exchange,
            data=extra,
        )

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def dispatch(self, payload: WebhookPayload) -> dict[str, Any]:
        """Route a validated payload to the appropriate handler.

        Current routing table:

        - ``place_order`` → :meth:`_handle_place_order`
        - ``cancel_order`` → :meth:`_handle_cancel_order`
        - ``alert`` / ``signal`` → :meth:`_handle_alert`
        - anything else → logged as ``"unknown_action"``

        Args:
            payload: Parsed :class:`WebhookPayload`.

        Returns:
            Dict with at least ``"status"`` and ``"action"`` keys.
        """
        action = payload.action
        if action == "place_order":
            result = await self._handle_place_order(payload)
        elif action == "cancel_order":
            result = await self._handle_cancel_order(payload)
        elif action in ("alert", "signal"):
            result = await self._handle_alert(payload)
        else:
            logger.warning("Unknown webhook action: %s", action)
            result = {
                "status": "unhandled",
                "action": action,
                "message": f"No handler registered for action '{action}'",
            }

        self._append_log(
            WebhookLogEntry(
                received_at=time.time(),
                source=payload.source,
                action=payload.action,
                symbol=payload.symbol,
                status=result.get("status", "dispatched"),
                detail=result.get("message", ""),
                raw=payload.data if self._config.log_payloads else None,
            )
        )
        return result

    # ------------------------------------------------------------------
    # Rate limiting (public — used by the Flask route layer)
    # ------------------------------------------------------------------

    def check_rate_limit(self) -> bool:
        """Check and consume one rate-limit slot.

        Returns:
            ``True`` if the request is within the rate limit.
        """
        return self._limiter.allow()

    @property
    def rate_limit_remaining(self) -> int:
        """Requests remaining in the current sliding window.

        Returns:
            Non-negative integer.
        """
        return self._limiter.remaining

    # ------------------------------------------------------------------
    # Log helpers
    # ------------------------------------------------------------------

    def _append_log(self, entry: WebhookLogEntry) -> None:
        """Append a log entry, trimming to capacity.

        Args:
            entry: :class:`WebhookLogEntry` to store.
        """
        self.log.append(entry)
        if len(self.log) > self._LOG_CAPACITY:
            self.log = self.log[-self._LOG_CAPACITY :]

    def recent_log(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recent webhook log entries.

        Args:
            limit: Maximum number of entries to return (default 50).

        Returns:
            List of serialised :class:`WebhookLogEntry` dicts, most recent
            last.
        """
        entries = self.log[-limit:] if limit > 0 else list(self.log)
        return [e.model_dump() for e in entries]

    # ------------------------------------------------------------------
    # Handlers (extendable in subclasses)
    # ------------------------------------------------------------------

    async def _handle_place_order(
        self, payload: WebhookPayload
    ) -> dict[str, Any]:
        """Handle a ``place_order`` action.

        Override in a subclass to integrate with the engine's order router.

        Args:
            payload: Parsed webhook payload.

        Returns:
            Response dict.
        """
        # Placeholder — full integration with engine order router is done
        # when the engine package is mounted in the main app.
        logger.info(
            "place_order signal received: %s %s via %s",
            payload.symbol, payload.exchange, payload.source,
        )
        return {
            "status": "queued",
            "action": "place_order",
            "symbol": payload.symbol,
            "exchange": payload.exchange,
            "message": "Order queued for routing",
        }

    async def _handle_cancel_order(
        self, payload: WebhookPayload
    ) -> dict[str, Any]:
        """Handle a ``cancel_order`` action.

        Override in a subclass to integrate with the engine's order manager.

        Args:
            payload: Parsed webhook payload.

        Returns:
            Response dict.
        """
        logger.info(
            "cancel_order signal received: %s via %s",
            payload.symbol, payload.source,
        )
        return {
            "status": "queued",
            "action": "cancel_order",
            "symbol": payload.symbol,
            "message": "Cancellation queued",
        }

    async def _handle_alert(
        self, payload: WebhookPayload
    ) -> dict[str, Any]:
        """Handle an ``alert`` or ``signal`` action.

        Logs the signal.  Override to forward to the AI signal pipeline or
        trigger an automation flow.

        Args:
            payload: Parsed webhook payload.

        Returns:
            Response dict.
        """
        logger.info(
            "alert/signal received: %s %s via %s | data=%s",
            payload.symbol, payload.action, payload.source, payload.data,
        )
        return {
            "status": "received",
            "action": payload.action,
            "symbol": payload.symbol,
            "message": "Signal logged",
        }
