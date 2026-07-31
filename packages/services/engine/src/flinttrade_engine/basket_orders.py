"""Basket order executor — atomic multi-leg order execution with rollback on failure.

Executes a list of :class:`BasketLeg` objects in sequence. If any leg fails
after one or more legs have already been placed, the executor attempts to
cancel or close all previously placed legs so the overall position remains
flat.  A full :class:`BasketResult` with per-leg status is always returned,
whether execution succeeded or was rolled back.

BUY legs are placed before SELL legs (mirrors OpenAlgo basket service
behaviour) to avoid margin shortfall on entry.

Usage::

    place_leg, _ = build_gated_leg_dispatchers(app)
    executor = BasketOrderExecutor(place_leg=place_leg)

    legs = [
        BasketLeg("NIFTY25MAYFUT", "NFO", "BUY", 50, "MARKET"),
        BasketLeg("BANKNIFTY25MAYFUT", "NFO", "SELL", 25, "LIMIT", price=52000.0),
    ]
    result = await executor.execute(legs, principal, strategy="my_strategy")
    if result.success:
        print("All legs placed:", result.order_ids)
    else:
        print("Basket failed at leg", result.failed_leg_index, result.error)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from flinttrade_core.models import (
    Action,
    Exchange,
    Order,
    PriceType,
    Product,
)
from flinttrade_engine.bracket_order import (
    BracketOrderError as GatedDispatchError,
    BracketPrincipal as OrderPrincipal,
    PlaceLegFn,
)

logger = logging.getLogger("flinttrade.engine.basket_orders")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BasketOrderError(Exception):
    """Raised when basket order construction or validation fails."""


class BasketValidationError(BasketOrderError):
    """Raised when pre-trade validation rejects one or more legs."""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class BasketLeg:
    """One leg of a basket order.

    Attributes:
        symbol: Instrument symbol (e.g. ``"NIFTY25MAYFUT"``).
        exchange: Exchange code string (e.g. ``"NFO"``).
        action: ``"BUY"`` or ``"SELL"``.
        quantity: Number of units/lots.
        order_type: Price type — ``"MARKET"``, ``"LIMIT"``, ``"SL"``, or ``"SL-M"``.
        price: Limit/SL price (required for LIMIT/SL order types).
        trigger_price: Trigger price (required for SL/SL-M order types).
        product: ``"MIS"``, ``"CNC"``, or ``"NRML"``.
    """

    symbol: str
    exchange: str
    action: Literal["BUY", "SELL"]
    quantity: int
    order_type: Literal["MARKET", "LIMIT", "SL", "SL-M"] = "MARKET"
    price: float | None = None
    trigger_price: float | None = None
    product: Literal["MIS", "CNC", "NRML"] = "MIS"


@dataclass
class LegResult:
    """Execution result for a single :class:`BasketLeg`.

    Attributes:
        leg_index: Position in the original legs list (0-based).
        symbol: Symbol of the leg.
        action: ``"BUY"`` or ``"SELL"``.
        quantity: Requested quantity.
        success: Whether the leg was placed successfully.
        order_id: Broker order-ID when successful, empty string otherwise.
        error: Error message when unsuccessful, empty string otherwise.
        rolled_back: Whether a rollback cancel/close was attempted for this leg.
        rollback_order_id: Order-ID of the rollback order (if any).
    """

    leg_index: int
    symbol: str
    action: str
    quantity: int
    success: bool
    order_id: str = ""
    error: str = ""
    rolled_back: bool = False
    rollback_order_id: str = ""


@dataclass
class BasketResult:
    """Aggregate result for a :class:`BasketOrderExecutor.execute` call.

    Attributes:
        success: ``True`` only when *all* legs were placed without error.
        legs: Per-leg :class:`LegResult` objects in execution order.
        failed_leg_index: Index of the first leg that failed; ``-1`` if none.
        error: Human-readable failure message, empty if successful.
        timestamp: ISO-8601 UTC timestamp of basket completion.
        strategy: Strategy tag passed to the executor.
        rolled_back: ``True`` if a rollback was attempted after partial fill.
    """

    success: bool
    legs: list[LegResult] = field(default_factory=list)
    failed_leg_index: int = -1
    error: str = ""
    timestamp: str = ""
    strategy: str = ""
    rolled_back: bool = False

    @property
    def order_ids(self) -> list[str]:
        """Return order-IDs for all successfully placed legs."""
        return [r.order_id for r in self.legs if r.success and r.order_id]

    @property
    def placed_count(self) -> int:
        """Number of legs that were successfully placed."""
        return sum(1 for r in self.legs if r.success)

    @property
    def failed_count(self) -> int:
        """Number of legs that failed to place."""
        return sum(1 for r in self.legs if not r.success)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_legs(legs: list[BasketLeg]) -> None:
    """Raise :class:`BasketValidationError` if any leg is malformed.

    Args:
        legs: Legs to validate.

    Raises:
        BasketValidationError: When validation fails.
    """
    if not legs:
        raise BasketValidationError("Basket must contain at least one leg")

    for i, leg in enumerate(legs):
        if not leg.symbol or not leg.symbol.strip():
            raise BasketValidationError(f"Leg {i}: symbol is required")
        if not leg.exchange or not leg.exchange.strip():
            raise BasketValidationError(f"Leg {i}: exchange is required")
        if leg.action not in ("BUY", "SELL"):
            raise BasketValidationError(
                f"Leg {i}: action must be 'BUY' or 'SELL', got '{leg.action}'"
            )
        if leg.quantity <= 0:
            raise BasketValidationError(
                f"Leg {i}: quantity must be > 0, got {leg.quantity}"
            )
        if leg.order_type not in ("MARKET", "LIMIT", "SL", "SL-M"):
            raise BasketValidationError(
                f"Leg {i}: order_type must be MARKET/LIMIT/SL/SL-M, got '{leg.order_type}'"
            )
        if leg.order_type in ("LIMIT", "SL") and (leg.price is None or leg.price <= 0):
            raise BasketValidationError(
                f"Leg {i}: price is required and must be > 0 for {leg.order_type} orders"
            )
        if leg.order_type in ("SL", "SL-M") and (
            leg.trigger_price is None or leg.trigger_price <= 0
        ):
            raise BasketValidationError(
                f"Leg {i}: trigger_price is required for {leg.order_type} orders"
            )


def _leg_to_order(leg: BasketLeg, strategy: str) -> Order:
    """Convert a :class:`BasketLeg` to a core :class:`Order`.

    Args:
        leg: The basket leg to convert.
        strategy: Strategy name tag.

    Returns:
        An :class:`Order` ready for the router.
    """
    # Map string exchange to Exchange enum (fall back to raw string — router handles it)
    try:
        exchange = Exchange(leg.exchange.upper())
    except ValueError:
        exchange = leg.exchange  # type: ignore[assignment]

    try:
        action = Action(leg.action.upper())
    except ValueError:
        action = leg.action  # type: ignore[assignment]

    price_type_map: dict[str, PriceType] = {
        "MARKET": PriceType.MARKET,
        "LIMIT": PriceType.LIMIT,
        "SL": PriceType.SL,
        "SL-M": PriceType.SL_M,
    }
    pricetype = price_type_map.get(leg.order_type, PriceType.MARKET)

    product_map: dict[str, Product] = {
        "MIS": Product.MIS,
        "CNC": Product.CNC,
        "NRML": Product.NRML,
    }
    product = product_map.get(leg.product, Product.MIS)

    return Order(
        symbol=leg.symbol,
        action=action,
        exchange=exchange,
        pricetype=pricetype,
        product=product,
        quantity=str(leg.quantity),
        price=str(leg.price or 0),
        trigger_price=str(leg.trigger_price or 0),
        strategy=strategy,
    )


# ---------------------------------------------------------------------------
# BasketOrderExecutor
# ---------------------------------------------------------------------------


class BasketOrderExecutor:
    """Executes a basket of orders atomically with rollback on failure.

    Every leg — entry and rollback alike — is placed through the injected
    ``place_leg`` dispatcher, which routes it through the SAME gated chain as a
    human ``/place`` order: SafetySystem L1–L5 → ``gate_order`` (one-shot HMAC
    ``SafetyContext``) → ``BrokerRouter`` → adapter. The executor holds NO broker
    client and no router, so a raw/ungated write from the basket path is
    structurally impossible (contract §8.1).

    Args:
        place_leg: The gated per-leg dispatcher
            (``flinttrade_engine.bracket_order.build_gated_leg_dispatchers``);
            ``place_leg(order, principal)`` returns the broker order id and
            raises :class:`~flinttrade_engine.bracket_order.BracketOrderError`
            on any safety block, gate refusal, or dispatch fault.
        rollback_delay_seconds: Seconds to wait between rollback orders
            (default 0.05 s to avoid rate limiting).
    """

    def __init__(
        self,
        place_leg: PlaceLegFn,
        rollback_delay_seconds: float = 0.05,
    ) -> None:
        self._place_leg = place_leg
        self._rollback_delay = rollback_delay_seconds

    def execute(
        self,
        legs: list[BasketLeg],
        principal: OrderPrincipal,
        strategy: str = "basket",
    ) -> BasketResult:
        """Place all legs atomically; roll back placed legs on any failure.

        Execution order: BUY legs first, then SELL legs (margin efficiency).
        On first failure the executor immediately rolls back all already-placed
        legs by sending the inverse action.

        Args:
            legs: Ordered list of :class:`BasketLeg` objects to execute.
            principal: The selector-bound identity every gated leg write is
                bound to (from the verified session JWT).
            strategy: Strategy tag forwarded to every order.

        Returns:
            :class:`BasketResult` describing the outcome of the basket.
        """
        timestamp = datetime.now(UTC).isoformat()

        try:
            _validate_legs(legs)
        except BasketValidationError as exc:
            logger.warning("Basket validation failed: %s", exc)
            return BasketResult(
                success=False,
                legs=[],
                failed_leg_index=-1,
                error=str(exc),
                timestamp=timestamp,
                strategy=strategy,
            )

        # Sort: BUY before SELL (preserves relative ordering within each group)
        indexed: list[tuple[int, BasketLeg]] = list(enumerate(legs))
        buy_first = [t for t in indexed if t[1].action == "BUY"]
        sell_after = [t for t in indexed if t[1].action == "SELL"]
        execution_order = buy_first + sell_after

        placed: list[tuple[int, BasketLeg, str]] = []  # (original_index, leg, order_id)
        leg_results: list[LegResult] = []
        failed_index = -1
        first_error = ""

        for orig_idx, leg in execution_order:
            order = _leg_to_order(leg, strategy)

            try:
                order_id = self._place_leg(order, principal)
            except GatedDispatchError as exc:
                # Safety block, gate refusal, or dispatch fault — leg NOT placed.
                failed_index = orig_idx
                first_error = str(exc)
                leg_results.append(
                    LegResult(
                        leg_index=orig_idx,
                        symbol=leg.symbol,
                        action=leg.action,
                        quantity=leg.quantity,
                        success=False,
                        error=first_error,
                    )
                )
                logger.warning(
                    "Basket leg %d (%s %s) failed: %s",
                    orig_idx,
                    leg.action,
                    leg.symbol,
                    first_error,
                )
                break
            except Exception as exc:
                logger.exception("Unexpected error placing leg %d (%s)", orig_idx, leg.symbol)
                failed_index = orig_idx
                first_error = str(exc)
                leg_results.append(
                    LegResult(
                        leg_index=orig_idx,
                        symbol=leg.symbol,
                        action=leg.action,
                        quantity=leg.quantity,
                        success=False,
                        error=str(exc),
                    )
                )
                break

            placed.append((orig_idx, leg, order_id))
            leg_results.append(
                LegResult(
                    leg_index=orig_idx,
                    symbol=leg.symbol,
                    action=leg.action,
                    quantity=leg.quantity,
                    success=True,
                    order_id=order_id,
                )
            )
            logger.info(
                "Basket leg %d placed: %s %s qty=%d orderid=%s",
                orig_idx,
                leg.action,
                leg.symbol,
                leg.quantity,
                order_id,
            )

        all_success = failed_index == -1

        rolled_back = False
        if not all_success and placed:
            logger.warning(
                "Rolling back %d placed leg(s) after failure at leg %d",
                len(placed),
                failed_index,
            )
            rolled_back = True
            self._rollback(placed, principal, strategy, leg_results)

        # Re-sort leg_results by original index for deterministic output
        leg_results.sort(key=lambda r: r.leg_index)

        return BasketResult(
            success=all_success,
            legs=leg_results,
            failed_leg_index=failed_index,
            error=first_error if not all_success else "",
            timestamp=timestamp,
            strategy=strategy,
            rolled_back=rolled_back,
        )

    # ------------------------------------------------------------------
    # Internal rollback
    # ------------------------------------------------------------------

    def _rollback(
        self,
        placed: list[tuple[int, BasketLeg, str]],
        principal: OrderPrincipal,
        strategy: str,
        leg_results: list[LegResult],
    ) -> None:
        """Attempt to close all placed legs by sending the inverse action.

        The rollback iterates in reverse placement order (LIFO).  Each rollback
        order is a MARKET order for the opposite action, placed through the same
        gated dispatcher as the entry legs.

        Args:
            placed: List of (original_index, leg, order_id) for placed legs.
            principal: The identity every gated rollback write is bound to.
            strategy: Strategy tag to use on rollback orders.
            leg_results: Mutable list to update with rollback outcomes.
        """
        # Build a lookup from original_index → LegResult for fast update
        result_by_idx: dict[int, LegResult] = {r.leg_index: r for r in leg_results}

        for orig_idx, leg, _ in reversed(placed):
            if self._rollback_delay > 0:
                time.sleep(self._rollback_delay)

            inverse_action = "SELL" if leg.action == "BUY" else "BUY"
            rollback_order = Order(
                symbol=leg.symbol,
                action=Action(inverse_action),
                exchange=Exchange(leg.exchange.upper()) if leg.exchange.upper() in Exchange.__members__.values() else leg.exchange,  # type: ignore[arg-type]
                pricetype=PriceType.MARKET,
                product=Product(leg.product) if leg.product in Product.__members__.values() else Product.MIS,
                quantity=str(leg.quantity),
                price="0",
                trigger_price="0",
                strategy=strategy,
            )

            try:
                rb_order_id = self._place_leg(rollback_order, principal)
                if orig_idx in result_by_idx:
                    result_by_idx[orig_idx].rolled_back = True
                    result_by_idx[orig_idx].rollback_order_id = rb_order_id
                logger.info(
                    "Rolled back leg %d (%s %s) rollback_orderid=%s",
                    orig_idx,
                    inverse_action,
                    leg.symbol,
                    rb_order_id,
                )
            except Exception as exc:
                logger.error(
                    "Rollback failed for leg %d (%s): %s",
                    orig_idx,
                    leg.symbol,
                    exc,
                )
                if orig_idx in result_by_idx:
                    result_by_idx[orig_idx].rolled_back = True  # attempted
