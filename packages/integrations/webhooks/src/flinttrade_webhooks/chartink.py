"""ChartInk scanner webhook receiver.

ChartInk sends scan results as a list of triggered symbols. This module parses
them, maps to OpenAlgo symbol format, and generates batch orders.

Webhook URL format: /webhook/chartink/{strategy_id}

ChartInk payload format (typical)::

    {
        "scan_name": "OI Spurt Bullish",
        "scan_url": "https://chartink.com/screener/...",
        "alert_list": "RELIANCE,TCS,INFY,HDFCBANK",
        "triggered_at": "2026-03-16 10:30:00",
        "stocks": "RELIANCE,TCS,INFY,HDFCBANK"
    }

Also supports the simpler comma-separated format: "RELIANCE,TCS,INFY"
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from flinttrade_core.models import Order

logger = logging.getLogger("flinttrade.integration.chartink")


@dataclass
class ChartInkScanResult:
    """Parsed ChartInk scan result."""

    scan_name: str = ""
    symbols: list[str] = field(default_factory=list)
    triggered_at: str = ""
    raw_payload: str = ""
    is_valid: bool = False
    error: str = ""

    @property
    def symbol_count(self) -> int:
        return len(self.symbols)


@dataclass
class ChartInkConfig:
    """Configuration for ChartInk webhook handling."""

    action: str = "BUY"            # Default action for triggered symbols
    exit_action: str = "SELL"      # Action when symbols exit the scan
    exchange: str = "NSE"
    product: str = "MIS"
    pricetype: str = "MARKET"
    quantity_per_symbol: str = "1"
    strategy: str = "Flint"
    max_symbols: int = 10          # Max symbols to act on per scan
    account_id: str = "default"    # OpenAlgo account the gated router places into


# Common ChartInk symbol suffixes to strip
_CHARTINK_SUFFIXES = ["-EQ", "-BE", "-SM", "-ST", "-BZ"]


def normalize_chartink_symbol(raw_symbol: str) -> str:
    """Normalise a ChartInk symbol to OpenAlgo format.

    ChartInk may add suffixes like -EQ, -BE. OpenAlgo uses plain symbols.
    """
    symbol = raw_symbol.strip().upper()
    for suffix in _CHARTINK_SUFFIXES:
        if symbol.endswith(suffix):
            symbol = symbol[: -len(suffix)]
            break
    # Remove any NSE: or BSE: prefix
    if ":" in symbol:
        symbol = symbol.split(":")[-1]
    return symbol


def parse_chartink_payload(body: str | bytes) -> ChartInkScanResult:
    """Parse a ChartInk webhook payload."""
    raw = body.decode("utf-8") if isinstance(body, bytes) else body
    raw = raw.strip()

    if not raw:
        return ChartInkScanResult(raw_payload=raw, error="Empty payload")

    # Try JSON
    if raw.startswith("{"):
        return _parse_json_payload(raw)

    # Try comma-separated symbols
    return _parse_csv_payload(raw)


def _parse_json_payload(raw: str) -> ChartInkScanResult:
    """Parse JSON payload from ChartInk."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return ChartInkScanResult(raw_payload=raw, error=f"Invalid JSON: {exc}")

    if not isinstance(data, dict):
        return ChartInkScanResult(raw_payload=raw, error="Payload must be a JSON object")

    # Extract symbols from various fields ChartInk may use
    symbols_raw = (
        data.get("stocks", "")
        or data.get("alert_list", "")
        or data.get("symbols", "")
    )

    if isinstance(symbols_raw, list):
        symbols = [normalize_chartink_symbol(s) for s in symbols_raw if s]
    elif isinstance(symbols_raw, str):
        symbols = [
            normalize_chartink_symbol(s)
            for s in symbols_raw.split(",")
            if s.strip()
        ]
    else:
        symbols = []

    if not symbols:
        return ChartInkScanResult(raw_payload=raw, error="No symbols found in payload")

    return ChartInkScanResult(
        scan_name=str(data.get("scan_name", "")),
        symbols=symbols,
        triggered_at=str(data.get("triggered_at", "")),
        raw_payload=raw,
        is_valid=True,
    )


def _parse_csv_payload(raw: str) -> ChartInkScanResult:
    """Parse comma-separated symbol list."""
    symbols = [
        normalize_chartink_symbol(s) for s in raw.split(",") if s.strip()
    ]
    if not symbols:
        return ChartInkScanResult(raw_payload=raw, error="No symbols found")

    return ChartInkScanResult(
        symbols=symbols,
        raw_payload=raw,
        is_valid=True,
    )


def scan_result_to_orders(
    result: ChartInkScanResult,
    config: ChartInkConfig | None = None,
) -> list[Order]:
    """Convert a ChartInk scan result into a list of Orders."""
    if not result.is_valid:
        return []

    cfg = config or ChartInkConfig()
    symbols = result.symbols[: cfg.max_symbols]

    orders: list[Order] = []
    for sym in symbols:
        orders.append(Order(
            symbol=sym,
            action=cfg.action,
            exchange=cfg.exchange,
            pricetype=cfg.pricetype,
            product=cfg.product,
            quantity=cfg.quantity_per_symbol,
            strategy=cfg.strategy,
        ))

    return orders


@dataclass
class ChartInkPlacementResult:
    """Outcome of routing one ChartInk-derived order through the safety gate.

    Attributes:
        symbol: The order's instrument symbol.
        success: ``True`` if the gated router accepted the order.
        broker_order_id: The broker order id returned by the router, if any.
        error: Failure detail when ``success`` is ``False``.
    """

    symbol: str
    success: bool = False
    broker_order_id: str = ""
    error: str = ""


class ChartInkWebhook:
    """ChartInk webhook handler.

    Parsing/Order-building is always available. When a safety-gated
    :class:`~flinttrade_gateway.router.BrokerRouter` is injected (S8/T8), the
    handler can additionally *place* each scan-derived order through
    ``gate_order`` -> ``BrokerRouter.place_order`` — i.e. account-bound HMAC +
    actor ACL + one-shot SafetyContext — instead of leaving placement to a
    caller. ChartInk is an EXTERNAL signal source, so the minted
    :class:`RequestContext` carries ``actor_type='external_intent'`` and
    ``intent_source='chartink'``; ``gate_order`` is invoked with the same
    metadata so a mismatch is rejected (Identity-Trust H11).

    Usage (parse only — unchanged)::

        ci = ChartInkWebhook(config=ChartInkConfig(action="BUY", quantity_per_symbol="10"))
        result = ci.handle(request_body)
        if result.is_valid:
            orders = ci.to_orders(result)

    Usage (gated placement — additive)::

        ci = ChartInkWebhook(config=cfg, broker_router=router, actor_id="external_intent:chartink")
        result = ci.handle(request_body)
        placements = ci.place_orders(result, nonce=webhook_nonce)
    """

    def __init__(
        self,
        config: ChartInkConfig | None = None,
        *,
        broker_router: Any | None = None,
        actor_id: str | None = None,
    ) -> None:
        self.config = config or ChartInkConfig()
        # When a safety-gated BrokerRouter is injected (S8/T8) ChartInk orders
        # are dispatched through the gate; otherwise placement is left to the
        # caller (existing behaviour — parse + to_orders only).
        self._broker_router = broker_router
        # ``actor_id`` must be authorised in workspace.json brokers.account_acls
        # for ``openalgo:<account_id>``. Defaults to the canonical external-intent
        # principal for ChartInk.
        self._actor_id = actor_id or "external_intent:chartink"

    @property
    def has_router(self) -> bool:
        """True when a safety-gated BrokerRouter is available for placement."""
        return self._broker_router is not None

    def handle(self, body: str | bytes) -> ChartInkScanResult:
        """Parse a ChartInk webhook payload."""
        result = parse_chartink_payload(body)
        if result.is_valid:
            logger.info(
                "ChartInk scan '%s': %d symbols — %s",
                result.scan_name, result.symbol_count,
                ", ".join(result.symbols[:5]),
            )
        else:
            logger.warning("Invalid ChartInk payload: %s", result.error)
        return result

    def to_orders(self, result: ChartInkScanResult) -> list[Order]:
        """Convert scan result to orders using this handler's config."""
        return scan_result_to_orders(result, self.config)

    # ------------------------------------------------------------------
    # Safety-gated placement (S8/T8) — only when a BrokerRouter is injected
    # ------------------------------------------------------------------

    def place_orders(
        self,
        result: ChartInkScanResult,
        *,
        nonce: str | None = None,
        signal_id: str | None = None,
    ) -> list[ChartInkPlacementResult]:
        """Place every scan-derived order through the safety-gated router.

        Requires a ``broker_router`` to have been injected at construction; with
        none, this raises :class:`RuntimeError` (call :meth:`to_orders` instead,
        the unchanged caller-places path). Each order is bound to the
        ``openalgo:<account_id>`` selector and gated as an EXTERNAL intent.

        Args:
            result: A valid :class:`ChartInkScanResult` (no-op if invalid).
            nonce: The webhook's replay nonce (see :mod:`webhook_replay`). When
                ``None`` a fresh ``uuid4`` is generated and documented — the
                ChartInk source itself carries no nonce, so the receiver's nonce
                (when present) should be threaded through here; otherwise a
                synthetic one binds the SafetyContext to this single dispatch.
            signal_id: Optional scan/webhook identifier folded into ``actor_id``.

        Returns:
            One :class:`ChartInkPlacementResult` per order (empty if the scan
            result is invalid).
        """
        if self._broker_router is None:
            raise RuntimeError(
                "ChartInkWebhook.place_orders requires a broker_router; none was "
                "injected. Use to_orders() for the caller-places path."
            )
        if not result.is_valid:
            return []

        orders = self.to_orders(result)
        account_id = self.config.account_id or "default"
        scan_id = signal_id or result.scan_name or "chartink"
        # ChartInk does not mint its own nonce. Reuse the receiver's replay nonce
        # when threaded through; otherwise generate one so the SafetyContext is
        # still bound to a single external-intent dispatch (documented synthetic).
        resolved_nonce = nonce if nonce is not None else uuid.uuid4().hex

        placements: list[ChartInkPlacementResult] = []
        for order in orders:
            placements.append(
                self._place_via_router(order, account_id, scan_id, resolved_nonce)
            )
        return placements

    def _place_via_router(
        self,
        order: Order,
        account_id: str,
        scan_id: str,
        nonce: str,
    ) -> ChartInkPlacementResult:
        """Gate one ChartInk order and dispatch it through the BrokerRouter.

        Mirrors the mint -> ``gate_order`` -> ``asyncio.run(router.place_order)``
        pattern from ``order_routes.place_order_routed`` (T7) and
        ``ditto.mirror._place_via_router`` (T9), but stamps the EXTERNAL-intent
        identity ChartInk requires: ``actor_type='external_intent'``,
        ``intent_source='chartink'`` and an ``external_nonce_hash`` so the gated
        context cannot be replayed with a different webhook payload.
        """
        import asyncio  # noqa: PLC0415

        from flinttrade_core.exceptions import SafetyBypassError  # noqa: PLC0415
        from flinttrade_engine.request_context import RequestContext  # noqa: PLC0415
        from flinttrade_engine.safety import gate_order  # noqa: PLC0415
        from flinttrade_gateway.routing_config import RoutingHint  # noqa: PLC0415

        try:
            from flinttrade_core.exceptions import BrokerError  # noqa: PLC0415
        except ImportError:  # pragma: no cover - BrokerError always present
            BrokerError = Exception  # type: ignore[assignment,misc]

        result = ChartInkPlacementResult(symbol=order.symbol)

        nonce_hash = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        request_ctx = RequestContext(
            jti=f"chartink-{uuid.uuid4().hex}",
            actor_type="external_intent",
            actor_id=self._actor_id,
            mode="live",
            intent_source="chartink",
            external_nonce_hash=nonce_hash,
            selector=f"openalgo:{account_id}",
        )

        try:
            safety_ctx = gate_order(
                order,
                request_ctx,
                adapter_id="openalgo",
                account_id=account_id,
                actor_type="external_intent",
                intent_source="chartink",
                external_nonce=nonce,
            )
            broker_order_id = asyncio.run(
                self._broker_router.place_order(
                    request_ctx,
                    order=order,
                    safety_ctx=safety_ctx,
                    hint=RoutingHint(adapter_id="openalgo", account_id=account_id),
                )
            )
            result.success = True
            result.broker_order_id = str(broker_order_id or "")
        except (SafetyBypassError, BrokerError) as exc:
            result.error = str(exc)
            logger.warning(
                "ChartInk (gated) order for %s refused: %s", order.symbol, exc
            )
        except Exception as exc:  # pragma: no cover - defensive
            result.error = str(exc)
            logger.error(
                "ChartInk (gated) order for %s failed: %s", order.symbol, exc
            )
        return result
