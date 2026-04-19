"""Split order executor — chunk a large order to reduce market impact.

Breaks a single large order into ``chunk_size``-sized slices with an
optional delay between each chunk.  Any remainder after full chunks is
placed as a final smaller order.

A :class:`SplitResult` is always returned describing per-chunk outcomes.

Usage::

    router = OrderRouter(client=client, safety=safety)
    executor = SplitOrderExecutor(router=router)

    result = await executor.execute_split(
        symbol="NIFTY25MAYFUT",
        exchange="NFO",
        total_quantity=300,
        chunk_size=75,
        action="BUY",
        delay_seconds=0.5,
        order_type="MARKET",
        strategy="impact_reducer",
    )
    if result.success:
        print(f"Placed {result.placed_count} chunks, total qty {result.placed_quantity}")
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from packages.core.src.models import (
    Action,
    Exchange,
    Order,
    PriceType,
    Product,
)
from packages.engine.src.router import OrderRouter

logger = logging.getLogger("flinttrade.engine.split_orders")

# Hard cap to prevent accidental runaway loops (mirrors OpenAlgo MAX_ORDERS=100)
MAX_CHUNKS = 100


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SplitOrderError(Exception):
    """Raised when split order parameters are invalid."""


class SplitValidationError(SplitOrderError):
    """Raised during pre-execution validation."""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ChunkResult:
    """Execution result for a single chunk of a split order.

    Attributes:
        chunk_index: 1-based chunk number.
        quantity: Quantity of this chunk.
        success: Whether the chunk was placed successfully.
        order_id: Broker order-ID when successful, empty otherwise.
        error: Error message when unsuccessful, empty otherwise.
    """

    chunk_index: int
    quantity: int
    success: bool
    order_id: str = ""
    error: str = ""


@dataclass
class SplitResult:
    """Aggregate result for a :class:`SplitOrderExecutor.execute_split` call.

    Attributes:
        success: ``True`` only when *all* chunks were placed without error.
        symbol: Instrument symbol.
        exchange: Exchange code.
        action: ``"BUY"`` or ``"SELL"``.
        total_quantity: Requested total quantity.
        chunk_size: Requested chunk size.
        chunks: Per-chunk :class:`ChunkResult` objects in execution order.
        timestamp: ISO-8601 UTC timestamp of split completion.
        strategy: Strategy tag used.
        error: Human-readable failure message when ``success`` is ``False``.
    """

    success: bool
    symbol: str
    exchange: str
    action: str
    total_quantity: int
    chunk_size: int
    chunks: list[ChunkResult] = field(default_factory=list)
    timestamp: str = ""
    strategy: str = ""
    error: str = ""

    @property
    def placed_count(self) -> int:
        """Number of successfully placed chunks."""
        return sum(1 for c in self.chunks if c.success)

    @property
    def failed_count(self) -> int:
        """Number of failed chunks."""
        return sum(1 for c in self.chunks if not c.success)

    @property
    def placed_quantity(self) -> int:
        """Total quantity successfully placed across all chunks."""
        return sum(c.quantity for c in self.chunks if c.success)

    @property
    def order_ids(self) -> list[str]:
        """Order-IDs for all successfully placed chunks."""
        return [c.order_id for c in self.chunks if c.success and c.order_id]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_split_params(
    symbol: str,
    exchange: str,
    total_quantity: int,
    chunk_size: int,
    action: str,
    order_type: str,
    price: float,
    trigger_price: float,
) -> None:
    """Raise :class:`SplitValidationError` when parameters are invalid.

    Args:
        symbol: Instrument symbol.
        exchange: Exchange code.
        total_quantity: Total quantity to split.
        chunk_size: Maximum size per chunk.
        action: ``"BUY"`` or ``"SELL"``.
        order_type: Price type string.
        price: Limit/SL price.
        trigger_price: Trigger price for SL types.

    Raises:
        SplitValidationError: When any parameter is invalid.
    """
    if not symbol or not symbol.strip():
        raise SplitValidationError("symbol is required")
    if not exchange or not exchange.strip():
        raise SplitValidationError("exchange is required")
    if action not in ("BUY", "SELL"):
        raise SplitValidationError(f"action must be 'BUY' or 'SELL', got '{action}'")
    if total_quantity <= 0:
        raise SplitValidationError(f"total_quantity must be > 0, got {total_quantity}")
    if chunk_size <= 0:
        raise SplitValidationError(f"chunk_size must be > 0, got {chunk_size}")
    if chunk_size > total_quantity:
        raise SplitValidationError(
            f"chunk_size ({chunk_size}) must be <= total_quantity ({total_quantity})"
        )
    if order_type not in ("MARKET", "LIMIT", "SL", "SL-M"):
        raise SplitValidationError(
            f"order_type must be MARKET/LIMIT/SL/SL-M, got '{order_type}'"
        )
    if order_type in ("LIMIT", "SL") and price <= 0:
        raise SplitValidationError(
            f"price must be > 0 for {order_type} orders"
        )
    if order_type in ("SL", "SL-M") and trigger_price <= 0:
        raise SplitValidationError(
            f"trigger_price must be > 0 for {order_type} orders"
        )

    import math
    num_full = total_quantity // chunk_size
    has_remainder = (total_quantity % chunk_size) > 0
    total_chunks = num_full + (1 if has_remainder else 0)
    if total_chunks > MAX_CHUNKS:
        raise SplitValidationError(
            f"Split would produce {total_chunks} chunks, exceeding MAX_CHUNKS={MAX_CHUNKS}. "
            f"Increase chunk_size or reduce total_quantity."
        )


def _build_chunk_order(
    symbol: str,
    exchange: str,
    action: str,
    quantity: int,
    order_type: str,
    price: float,
    trigger_price: float,
    product: str,
    strategy: str,
) -> Order:
    """Build an :class:`Order` for a single chunk.

    Args:
        symbol: Instrument symbol.
        exchange: Exchange code string.
        action: ``"BUY"`` or ``"SELL"``.
        quantity: Chunk quantity.
        order_type: Price type string.
        price: Limit/SL price (0 for MARKET).
        trigger_price: Trigger price (0 if not needed).
        product: Product type string.
        strategy: Strategy tag.

    Returns:
        :class:`Order` ready for the router.
    """
    price_type_map: dict[str, PriceType] = {
        "MARKET": PriceType.MARKET,
        "LIMIT": PriceType.LIMIT,
        "SL": PriceType.SL,
        "SL-M": PriceType.SL_M,
    }
    product_map: dict[str, Product] = {
        "MIS": Product.MIS,
        "CNC": Product.CNC,
        "NRML": Product.NRML,
    }

    try:
        exch = Exchange(exchange.upper())
    except ValueError:
        exch = exchange  # type: ignore[assignment]

    return Order(
        symbol=symbol,
        action=Action(action.upper()),
        exchange=exch,
        pricetype=price_type_map.get(order_type, PriceType.MARKET),
        product=product_map.get(product, Product.MIS),
        quantity=str(quantity),
        price=str(price),
        trigger_price=str(trigger_price),
        strategy=strategy,
    )


# ---------------------------------------------------------------------------
# SplitOrderExecutor
# ---------------------------------------------------------------------------


class SplitOrderExecutor:
    """Breaks a large order into smaller chunks and places them sequentially.

    Useful for illiquid instruments where a single large order may cause
    significant market impact.

    Args:
        router: The :class:`~packages.engine.src.router.OrderRouter` to use.
    """

    def __init__(self, router: OrderRouter) -> None:
        self._router = router

    async def execute_split(
        self,
        symbol: str,
        exchange: str,
        total_quantity: int,
        chunk_size: int,
        action: Literal["BUY", "SELL"],
        delay_seconds: float = 1.0,
        order_type: str = "MARKET",
        price: float = 0.0,
        trigger_price: float = 0.0,
        product: str = "MIS",
        strategy: str = "split",
    ) -> SplitResult:
        """Break ``total_quantity`` into chunks and place with optional delay.

        Full chunks of ``chunk_size`` are placed first; any remainder is placed
        last.  Execution halts on the first failed chunk and all subsequent
        chunks are skipped (partial fill is reported in the result).

        Args:
            symbol: Instrument symbol.
            exchange: Exchange code (e.g. ``"NFO"``).
            total_quantity: Total quantity to buy or sell.
            chunk_size: Maximum units per individual order.
            action: ``"BUY"`` or ``"SELL"``.
            delay_seconds: Seconds to sleep between consecutive chunks.
            order_type: ``"MARKET"``, ``"LIMIT"``, ``"SL"``, or ``"SL-M"``.
            price: Limit/SL price (required for LIMIT/SL types).
            trigger_price: Trigger price (required for SL/SL-M types).
            product: ``"MIS"``, ``"CNC"``, or ``"NRML"``.
            strategy: Strategy name tag forwarded to every chunk order.

        Returns:
            :class:`SplitResult` describing the outcome of the split.
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        try:
            _validate_split_params(
                symbol, exchange, total_quantity, chunk_size,
                action, order_type, price, trigger_price,
            )
        except SplitValidationError as exc:
            logger.warning("Split validation failed: %s", exc)
            return SplitResult(
                success=False,
                symbol=symbol,
                exchange=exchange,
                action=action,
                total_quantity=total_quantity,
                chunk_size=chunk_size,
                timestamp=timestamp,
                strategy=strategy,
                error=str(exc),
            )

        # Build chunk sizes list
        num_full = total_quantity // chunk_size
        remainder = total_quantity % chunk_size
        chunk_quantities: list[int] = [chunk_size] * num_full
        if remainder:
            chunk_quantities.append(remainder)

        chunk_results: list[ChunkResult] = []
        first_error = ""
        all_success = True

        for idx, qty in enumerate(chunk_quantities, start=1):
            if idx > 1 and delay_seconds > 0:
                await asyncio.sleep(delay_seconds)

            order = _build_chunk_order(
                symbol=symbol,
                exchange=exchange,
                action=action,
                quantity=qty,
                order_type=order_type,
                price=price,
                trigger_price=trigger_price,
                product=product,
                strategy=strategy,
            )

            try:
                decision = await self._router.route_order(order)
            except Exception as exc:
                logger.exception("Unexpected error placing chunk %d of %s", idx, symbol)
                first_error = str(exc)
                all_success = False
                chunk_results.append(
                    ChunkResult(
                        chunk_index=idx,
                        quantity=qty,
                        success=False,
                        error=str(exc),
                    )
                )
                break

            if not decision.passed:
                first_error = decision.error or "Safety check blocked chunk order"
                all_success = False
                chunk_results.append(
                    ChunkResult(
                        chunk_index=idx,
                        quantity=qty,
                        success=False,
                        error=first_error,
                    )
                )
                logger.warning(
                    "Split chunk %d/%d failed for %s: %s",
                    idx,
                    len(chunk_quantities),
                    symbol,
                    first_error,
                )
                break

            order_id = decision.order_response.orderid if decision.order_response else ""
            chunk_results.append(
                ChunkResult(chunk_index=idx, quantity=qty, success=True, order_id=order_id)
            )
            logger.info(
                "Split chunk %d/%d placed: %s %s qty=%d orderid=%s",
                idx,
                len(chunk_quantities),
                action,
                symbol,
                qty,
                order_id,
            )

        return SplitResult(
            success=all_success,
            symbol=symbol,
            exchange=exchange,
            action=action,
            total_quantity=total_quantity,
            chunk_size=chunk_size,
            chunks=chunk_results,
            timestamp=timestamp,
            strategy=strategy,
            error=first_error,
        )
