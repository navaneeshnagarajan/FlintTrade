"""Generic webhook receiver for external signal sources.

Receives, authenticates, parses, and dispatches webhooks from:
- TradingView alert webhooks
- ChartInk scanner webhooks
- GoCharting alert webhooks
- Custom / generic JSON webhooks

Security: HMAC-SHA256 signature verification via ``X-Signature`` header
(``sha256=<hex>`` format, compatible with GitHub-style webhook signing).

Rate limiting: in-memory sliding-window per :class:`WebhookConfig`.

Dispatch: routes payloads to handler coroutines based on ``action`` field.

Example::

    from .webhook_receiver import (
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

import logging
import math
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from inspect import isawaitable
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .webhook_hmac import verify_hmac_sha256_signature

logger = logging.getLogger("flinttrade.integration.webhook_receiver")

_VALID_EXCHANGES = frozenset({
    "NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "NCDEX", "NCO", "DELTA",
})
_VALID_PRICETYPES = frozenset({"MARKET", "LIMIT", "SL", "SL-M"})
_VALID_PRODUCTS = frozenset({"MIS", "CNC", "NRML"})
_CHARTINK_SUFFIXES = ("-EQ", "-BE", "-SM", "-ST", "-BZ")
_ORDER_SIDE_KEYS = ("side", "tv_action", "gc_action", "order_action", "transaction_type")


def _normalise_order_choice(
    raw: Mapping[str, Any],
    field: str,
    *,
    default: str,
    allowed: frozenset[str],
    source: str,
) -> str:
    """Return a canonical order enum, rejecting unsafe supplied values."""
    if field not in raw:
        return default
    value = str(raw[field]).strip().upper()
    if value not in allowed:
        raise ValueError(f"{source} payload has invalid {field}")
    return value


def _normalise_order_prices(data: dict[str, Any], *, source: str) -> None:
    """Canonicalise price fields and reject values unsafe for live routing."""
    parsed: dict[str, float] = {}
    for field in ("price", "trigger_price"):
        value = str(data.get(field, "0")).strip() or "0"
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{source} payload has an invalid {field}") from None
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"{source} payload has an invalid {field}")
        data[field] = value
        parsed[field] = number

    pricetype = str(data.get("pricetype", "MARKET")).upper()
    if pricetype in {"LIMIT", "SL"} and parsed["price"] <= 0:
        raise ValueError(f"{source} {pricetype} order requires a positive price")
    if pricetype in {"SL", "SL-M"} and parsed["trigger_price"] <= 0:
        raise ValueError(f"{source} {pricetype} order requires a positive trigger_price")


def _normalise_chartink_symbol(raw_symbol: object) -> str:
    symbol = str(raw_symbol).strip().upper()
    for suffix in _CHARTINK_SUFFIXES:
        if symbol.endswith(suffix):
            symbol = symbol[: -len(suffix)]
            break
    if ":" in symbol:
        symbol = symbol.rsplit(":", 1)[-1]
    return symbol


def _parse_order_text(
    raw: str,
    *,
    source: str,
    action_key: str,
    strategy: str,
) -> WebhookPayload:
    """Parse the shared signed-relay text order shape for alert providers."""
    parts = raw.strip().upper().split()
    if len(parts) < 2 or parts[0] not in {"BUY", "SELL"}:
        raise ValueError(f"{source} text payload requires ACTION SYMBOL")
    action_raw = parts[0]
    symbol = parts[1]
    exchange = "NSE"
    quantity = "1"
    pricetype = "MARKET"
    price = "0"
    index = 2
    if index < len(parts) and parts[index] in _VALID_EXCHANGES:
        exchange = parts[index]
        index += 1
    if index < len(parts) and parts[index].isdigit():
        quantity = parts[index]
        index += 1
    if index < len(parts):
        if parts[index] not in _VALID_PRICETYPES:
            raise ValueError(f"{source} text payload has an invalid order token")
        pricetype = parts[index]
        index += 1
    if index < len(parts):
        try:
            parsed_price = float(parts[index])
        except ValueError:
            raise ValueError(f"{source} text payload has an invalid price") from None
        if not 0 <= parsed_price < float("inf"):
            raise ValueError(f"{source} text payload has an invalid price")
        price = parts[index]
        index += 1
    if index != len(parts):
        raise ValueError(f"{source} text payload has trailing order tokens")
    data = {
        action_key: action_raw,
        "side": action_raw,
        "quantity": quantity,
        "price": price,
        "trigger_price": "0",
        "pricetype": pricetype,
        "product": "MIS",
        "strategy": strategy,
    }
    _normalise_order_prices(data, source=source)
    return WebhookPayload(
        source=source,
        action="place_order",
        symbol=symbol,
        exchange=exchange,
        data=data,
    )


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
        default_factory=lambda: ["tradingview", "chartink", "gocharting", "custom"]
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
        webhook_nonce: Verified replay nonce supplied by the route layer.
        webhook_path: Mounted named endpoint path, when this came through the
            endpoint registry.
        timestamp: UTC timestamp when the payload was received/created.
    """

    source: str
    action: str
    symbol: str | None = None
    exchange: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    webhook_nonce: str | None = None
    webhook_path: str | None = None
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
        self._lock = threading.Lock()

    def allow(self) -> bool:
        """Check whether a new request fits within the rate limit.

        Returns:
            ``True`` if allowed, ``False`` if limit exceeded.
        """
        with self._lock:
            now = time.monotonic()
            cutoff = now - self._window
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
        with self._lock:
            now = time.monotonic()
            cutoff = now - self._window
            while self._timestamps and self._timestamps[0] <= cutoff:
                self._timestamps.popleft()
            return max(0, self._max - len(self._timestamps))


# ---------------------------------------------------------------------------
# WebhookReceiver
# ---------------------------------------------------------------------------


WebhookDispatchResult = dict[str, Any]
WebhookActionDispatcher = Callable[
    [WebhookPayload],
    WebhookDispatchResult | Awaitable[WebhookDispatchResult],
]


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

    def __init__(
        self,
        config: WebhookConfig,
        *,
        order_dispatcher: WebhookActionDispatcher | None = None,
        cancel_dispatcher: WebhookActionDispatcher | None = None,
    ) -> None:
        self._config = config
        self._limiter = _SlidingWindowLimiter(config.rate_limit)
        self._order_dispatcher = order_dispatcher
        self._cancel_dispatcher = cancel_dispatcher
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

    def verify_signature(self, payload: bytes, signature: str, *, secret: str | None = None) -> bool:
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
        signing_secret = self._config.secret if secret is None else secret
        skip_verification = self._config.skip_verification if secret is None else False

        if not signing_secret:
            # Explicit opt-out: caller has acknowledged there is no secret.
            if skip_verification:
                return True
            # Secret is absent and skip_verification is False — reject.
            logger.warning(
                "verify_signature called with no secret configured — rejecting request"
            )
            return False
        if not signature:
            return False

        return verify_hmac_sha256_signature(
            payload,
            signature,
            signing_secret,
            skip_verification=skip_verification,
        )

    # ------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------

    def parse_tradingview(self, raw: Mapping[str, Any] | str) -> WebhookPayload:
        """Parse a TradingView alert webhook payload.

        TradingView sends JSON with ``action``, ``symbol``, ``exchange``,
        ``quantity``, ``price``, ``pricetype``, and ``product`` fields.
        Unknown fields are preserved in ``data``.

        Args:
            raw: Decoded JSON dict from the TradingView webhook request.

        Returns:
            Populated :class:`WebhookPayload`.
        """
        if isinstance(raw, str):
            return _parse_order_text(
                raw,
                source="tradingview",
                action_key="tv_action",
                strategy="Flint",
            )

        action_raw = str(raw.get("action", "")).upper()
        # Map TradingView BUY/SELL to FlintTrade action vocabulary
        action = "place_order" if action_raw in ("BUY", "SELL") else action_raw.lower() or "signal"

        extra = {k: v for k, v in raw.items() if k not in {"action", "symbol", "exchange"}}
        for key in _ORDER_SIDE_KEYS:
            extra.pop(key, None)
        extra["tv_action"] = action_raw
        if action_raw in {"BUY", "SELL"}:
            extra["side"] = action_raw
        extra["pricetype"] = _normalise_order_choice(
            extra,
            "pricetype",
            default="MARKET",
            allowed=_VALID_PRICETYPES,
            source="TradingView",
        )
        extra["product"] = _normalise_order_choice(
            extra,
            "product",
            default="MIS",
            allowed=_VALID_PRODUCTS,
            source="TradingView",
        )
        _normalise_order_prices(extra, source="TradingView")

        return WebhookPayload(
            source="tradingview",
            action=action,
            symbol=str(raw.get("symbol", "")).upper() or None,
            exchange=str(raw.get("exchange", "NSE")).upper() or None,
            data={k: v for k, v in extra.items()},
        )

    def parse_gocharting(self, raw: Mapping[str, Any] | str) -> WebhookPayload:
        """Parse a GoCharting alert webhook payload.

        Signed relays may send JSON with explicit ``symbol``, ``exchange``,
        ``product``, ``action`` (BUY/SELL) and ``quantity`` fields, or the
        shared plain-text order shape. Both map to the same
        gated ``place_order`` action and flows through the identical
        ``_handle_place_order`` → gated-dispatcher path. No separate order path
        is introduced (one-core rule; ``test_no_legacy_order_path`` guard).

        A GoCharting alert missing an actionable BUY/SELL is downgraded to a
        ``signal`` so it is logged rather than routed to placement.

        Args:
            raw: Decoded JSON mapping or signed-relay text payload.

        Returns:
            Populated :class:`WebhookPayload`.
        """
        if isinstance(raw, str):
            return _parse_order_text(
                raw,
                source="gocharting",
                action_key="gc_action",
                strategy="GoCharting",
            )

        action_raw = str(raw.get("action", "")).upper()
        action = "place_order" if action_raw in ("BUY", "SELL") else action_raw.lower() or "signal"

        extra = {k: v for k, v in raw.items() if k not in {"action", "symbol", "exchange"}}
        # Preserve the original side and stamp the strategy, mirroring the
        # ``tv_action`` convention so the gated dispatcher reads the side and a
        # MARKET default when GoCharting omits ``pricetype``.
        for key in _ORDER_SIDE_KEYS:
            extra.pop(key, None)
        extra["gc_action"] = action_raw
        if action_raw in {"BUY", "SELL"}:
            extra["side"] = action_raw
        extra["pricetype"] = _normalise_order_choice(
            extra,
            "pricetype",
            default="MARKET",
            allowed=_VALID_PRICETYPES,
            source="GoCharting",
        )
        extra["product"] = _normalise_order_choice(
            extra,
            "product",
            default="MIS",
            allowed=_VALID_PRODUCTS,
            source="GoCharting",
        )
        _normalise_order_prices(extra, source="GoCharting")
        extra.setdefault("strategy", "GoCharting")

        return WebhookPayload(
            source="gocharting",
            action=action,
            symbol=str(raw.get("symbol", "")).upper() or None,
            exchange=str(raw.get("exchange", "NSE")).upper() or None,
            data={k: v for k, v in extra.items()},
        )

    def parse_chartink(self, raw: Mapping[str, Any] | str) -> WebhookPayload:
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
        if isinstance(raw, str):
            symbols_raw: str | list[str] = raw
            scan_name = ""
            triggered_at = ""
            exchange = "NSE"
        else:
            symbols_raw = (
                raw.get("stocks")
                or raw.get("alert_list")
                or raw.get("symbols")
                or ""
            )
            scan_name = str(raw.get("scan_name", ""))
            triggered_at = str(raw.get("triggered_at", ""))
            exchange = str(raw.get("exchange", "NSE")).upper() or None
        if isinstance(symbols_raw, str):
            symbols = [_normalise_chartink_symbol(s) for s in symbols_raw.split(",") if s.strip()]
        elif isinstance(symbols_raw, list):
            symbols = [_normalise_chartink_symbol(s) for s in symbols_raw if s]
        else:
            symbols = []

        first_symbol = symbols[0] if symbols else None

        return WebhookPayload(
            source="chartink",
            action="signal",
            symbol=first_symbol,
            exchange=exchange,
            data={
                "scan_name": scan_name,
                "symbols": symbols,
                "triggered_at": triggered_at,
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

        Webhook-triggered order placement is supported only when the app injects
        a gated dispatcher. Without that hook this receiver still fails loudly
        rather than pretending to queue: a fake "queued" response would let an
        operator believe a TradingView signal placed an order when nothing
        happened.

        Args:
            payload: Parsed webhook payload.

        Returns:
            Dispatcher result, or an honest fail-closed error when no gated
            dispatcher is available.
        """
        if self._order_dispatcher is not None:
            try:
                return await self._call_dispatcher(self._order_dispatcher, payload)
            except Exception:
                logger.exception(
                    "place_order signal dispatcher failed before/inside gated routing"
                )
                return {
                    "status": "error",
                    "action": "place_order",
                    "symbol": payload.symbol,
                    "exchange": payload.exchange,
                    "message": "Webhook order dispatch failed before broker execution.",
                }

        logger.warning(
            "place_order signal received but webhook order dispatch is not "
            "wired to the gated router — REJECTED: %s %s via %s",
            payload.symbol, payload.exchange, payload.source,
        )
        return {
            "status": "error",
            "action": "place_order",
            "symbol": payload.symbol,
            "exchange": payload.exchange,
            "message": (
                "Webhook order placement is not connected to the gated order "
                "router yet — no order was placed."
            ),
        }

    async def _handle_cancel_order(
        self, payload: WebhookPayload
    ) -> dict[str, Any]:
        """Handle a ``cancel_order`` action.

        Same fail-closed contract as :meth:`_handle_place_order`: cancellation is
        supported only when the app injects a gated cancel dispatcher.

        Args:
            payload: Parsed webhook payload.

        Returns:
            Dispatcher result, or an honest fail-closed error when no gated
            dispatcher is available.
        """
        if self._cancel_dispatcher is not None:
            try:
                return await self._call_dispatcher(self._cancel_dispatcher, payload)
            except Exception:
                logger.exception(
                    "cancel_order signal dispatcher failed before/inside gated routing"
                )
                return {
                    "status": "error",
                    "action": "cancel_order",
                    "symbol": payload.symbol,
                    "message": "Webhook order cancel failed before broker execution.",
                }

        logger.warning(
            "cancel_order signal received but webhook order dispatch is not "
            "wired to the gated router — REJECTED: %s via %s",
            payload.symbol, payload.source,
        )
        return {
            "status": "error",
            "action": "cancel_order",
            "symbol": payload.symbol,
            "message": (
                "Webhook order cancellation is not connected to the gated "
                "order router yet — nothing was cancelled."
            ),
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

    async def _call_dispatcher(
        self,
        dispatcher: WebhookActionDispatcher,
        payload: WebhookPayload,
    ) -> dict[str, Any]:
        result = dispatcher(payload)
        if isawaitable(result):
            result = await result
        if not isinstance(result, dict):
            raise TypeError(
                f"webhook dispatcher returned {type(result).__name__}; expected dict"
            )
        return result
