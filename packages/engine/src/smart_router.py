# packages/engine/src/smart_router.py
"""Smart Order Router — liquidity-aware, slippage-budgeted order splitting.

Routes orders intelligently based on:
1. Available depth at target price
2. Recent volume profile
3. Slippage budget (basis points)
4. Time urgency (high/medium/low)

Urgency mapping:
- ``high``   → single MARKET order at best bid/ask, no splitting, no delay
- ``medium`` → split across multiple child orders if qty exceeds depth at top-5
               levels; randomised 1–5 s inter-order delay
- ``low``    → TWAP: N equal child orders spread over a configurable window

Usage::

    router = SmartOrderRouter(
        base_router=order_router,
        depth_provider=my_depth_fn,
        volume_provider=my_volume_fn,
    )
    result = await router.route(
        symbol="NIFTY25APRFUT",
        exchange="NFO",
        quantity=3600,
        action="BUY",
        max_slippage_bps=20,
        urgency="medium",
    )
    for child in result.child_orders:
        print(child.order_id, child.quantity, child.status)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Literal

from packages.core.src.models import Action, Exchange, Order, PriceType

logger = logging.getLogger("flinttrade.engine.smart_router")


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ChildOrderResult:
    """Result of a single child order within a smart route.

    Attributes:
        quantity: Quantity placed in this child.
        price_type: MARKET or LIMIT used for this leg.
        status: "placed", "skipped", or "failed".
        order_id: Broker order ID if placed successfully.
        error: Error message if placement failed.
        slippage_bps: Estimated slippage in basis points.
        placed_at: ISO-8601 timestamp.
    """

    quantity: int
    price_type: str
    status: str  # "placed" | "skipped" | "failed"
    order_id: str = ""
    error: str = ""
    slippage_bps: float = 0.0
    placed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class SmartRouteResult:
    """Aggregated result of a smart routing decision.

    Attributes:
        symbol: Instrument symbol.
        exchange: Exchange.
        action: "BUY" or "SELL".
        total_quantity: Original requested quantity.
        filled_quantity: Sum of successfully placed child quantities.
        child_orders: Individual child order results.
        urgency: Urgency level used.
        strategy: Strategy tag propagated to each child.
        slippage_budget_bps: Max allowed slippage.
        average_slippage_bps: Weighted average actual slippage.
        completed: True when all children have been attempted.
        error: Top-level routing error if something failed early.
    """

    symbol: str
    exchange: str
    action: str
    total_quantity: int
    filled_quantity: int = 0
    child_orders: list[ChildOrderResult] = field(default_factory=list)
    urgency: str = "medium"
    strategy: str = "Flint"
    slippage_budget_bps: int = 20
    average_slippage_bps: float = 0.0
    completed: bool = False
    error: str = ""

    def add_child(self, child: ChildOrderResult) -> None:
        """Append a child result and update running totals.

        Args:
            child: The child order result to add.
        """
        self.child_orders.append(child)
        if child.status == "placed":
            self.filled_quantity += child.quantity

    def compute_average_slippage(self) -> None:
        """Recompute :attr:`average_slippage_bps` from placed child orders."""
        placed = [c for c in self.child_orders if c.status == "placed" and c.quantity > 0]
        if not placed:
            self.average_slippage_bps = 0.0
            return
        total_qty = sum(c.quantity for c in placed)
        weighted = sum(c.slippage_bps * c.quantity for c in placed)
        self.average_slippage_bps = weighted / total_qty


# ---------------------------------------------------------------------------
# Depth utilities
# ---------------------------------------------------------------------------


def _available_qty_top_n(depth: dict, action: Literal["BUY", "SELL"], n: int = 5) -> int:
    """Sum the available quantity across the top *n* price levels in *depth*.

    Depth dict format (matches OpenAlgo depth response)::

        {
            "asks": [{"price": 100.0, "quantity": 200}, ...],
            "bids": [{"price":  99.5, "quantity": 150}, ...],
        }

    For a BUY order we consume from the ask side; for SELL from the bid side.

    Args:
        depth: Market depth data with "asks" and "bids" lists.
        action: "BUY" uses asks; "SELL" uses bids.
        n: Number of price levels to consider.

    Returns:
        Total available quantity across the top *n* levels.
    """
    side = "asks" if action == "BUY" else "bids"
    levels: list[dict] = depth.get(side, [])
    return sum(int(lvl.get("quantity", 0)) for lvl in levels[:n])


def _best_price(depth: dict, action: Literal["BUY", "SELL"]) -> float | None:
    """Return the best (most favourable) price from depth for the given action.

    Args:
        depth: Market depth dict.
        action: "BUY" → best ask (lowest); "SELL" → best bid (highest).

    Returns:
        Best price as float, or ``None`` if depth is empty.
    """
    side = "asks" if action == "BUY" else "bids"
    levels: list[dict] = depth.get(side, [])
    if not levels:
        return None
    # Asks should be ascending (lowest first); bids descending (highest first)
    return float(levels[0].get("price", 0))


# ---------------------------------------------------------------------------
# SmartOrderRouter
# ---------------------------------------------------------------------------


class SmartOrderRouter:
    """Routes orders intelligently based on depth, volume, slippage, and urgency.

    Does not modify :class:`~packages.engine.src.router.OrderRouter` — wraps it.

    Attributes:
        base_router: The underlying :class:`~packages.engine.src.router.OrderRouter`.
        depth_provider: Async callable ``(symbol, exchange) → dict`` returning
            market depth in OpenAlgo format.
        volume_provider: Async callable ``(symbol, exchange) → int`` returning
            recent traded volume.
        twap_window_seconds: Total TWAP window for ``low`` urgency orders (default 300 s).
        twap_slices: Number of equal-sized slices for TWAP (default 5).
    """

    def __init__(
        self,
        base_router: object,
        depth_provider: Callable,
        volume_provider: Callable,
        twap_window_seconds: int = 300,
        twap_slices: int = 5,
    ) -> None:
        """Initialise the SmartOrderRouter.

        Args:
            base_router: An :class:`~packages.engine.src.router.OrderRouter`
                instance used to place individual child orders.
            depth_provider: Async callable that returns market depth dict for a
                symbol and exchange.
            volume_provider: Async callable that returns recent volume (int) for
                a symbol and exchange.
            twap_window_seconds: Duration of the TWAP window in seconds.
            twap_slices: How many equal slices to split TWAP into.
        """
        self._base_router = base_router
        self._depth_provider = depth_provider
        self._volume_provider = volume_provider
        self._twap_window_seconds = twap_window_seconds
        self._twap_slices = twap_slices

    async def route(
        self,
        symbol: str,
        exchange: str,
        quantity: int,
        action: Literal["BUY", "SELL"],
        max_slippage_bps: int = 20,
        urgency: Literal["low", "medium", "high"] = "medium",
        strategy: str = "Flint",
        product: str = "MIS",
    ) -> SmartRouteResult:
        """Route an order intelligently based on urgency and liquidity.

        High urgency:
            Single MARKET order, immediate.  No depth analysis.

        Medium urgency:
            Fetch depth.  If ``quantity <= depth at top-5``, place as one
            order.  Otherwise split into chunks that fit within the top-5
            depth, with 1–5 s random delay between chunks.

        Low urgency:
            TWAP: divide ``quantity`` into :attr:`twap_slices` equal parts,
            placed at evenly-spaced intervals over :attr:`twap_window_seconds`.

        Args:
            symbol: Instrument symbol (e.g. "NIFTY25APRFUT").
            exchange: Exchange code (e.g. "NFO").
            quantity: Total quantity to place.
            action: "BUY" or "SELL".
            max_slippage_bps: Maximum allowed slippage in basis points.
            urgency: Routing urgency — "high", "medium", or "low".
            strategy: Strategy tag forwarded to each child order.
            product: Product type (MIS/NRML/CNC).

        Returns:
            :class:`SmartRouteResult` with all child order results.
        """
        result = SmartRouteResult(
            symbol=symbol,
            exchange=exchange,
            action=action,
            total_quantity=quantity,
            urgency=urgency,
            strategy=strategy,
            slippage_budget_bps=max_slippage_bps,
        )

        try:
            if urgency == "high":
                await self._route_high(result, product)
            elif urgency == "medium":
                await self._route_medium(result, product)
            else:
                await self._route_low(result, product)
        except Exception as exc:
            logger.error(
                "SmartOrderRouter.route failed for %s %s: %s",
                action, symbol, exc,
            )
            result.error = str(exc)

        result.compute_average_slippage()
        result.completed = True
        return result

    # ------------------------------------------------------------------
    # Urgency strategies
    # ------------------------------------------------------------------

    async def _route_high(self, result: SmartRouteResult, product: str) -> None:
        """High urgency: single MARKET order, no splitting.

        Args:
            result: The in-progress :class:`SmartRouteResult` to populate.
            product: Product type string.
        """
        logger.info(
            "SmartOrderRouter [HIGH] %s %s qty=%d — single MARKET",
            result.action, result.symbol, result.total_quantity,
        )
        child = await self._place_child(
            result=result,
            quantity=result.total_quantity,
            price_type=PriceType.MARKET,
            product=product,
            slippage_bps=0.0,
        )
        result.add_child(child)

    async def _route_medium(self, result: SmartRouteResult, product: str) -> None:
        """Medium urgency: depth-aware splitting with inter-order delay.

        Args:
            result: The in-progress :class:`SmartRouteResult` to populate.
            product: Product type string.
        """
        depth = await self._depth_provider(result.symbol, result.exchange)
        available = _available_qty_top_n(depth, result.action, n=5)  # type: ignore[arg-type]
        best = _best_price(depth, result.action)  # type: ignore[arg-type]

        slippage_bps = self._estimate_slippage(depth, result.action, result.total_quantity)

        if slippage_bps > result.slippage_budget_bps:
            logger.warning(
                "SmartOrderRouter [MEDIUM] %s %s: estimated slippage %.1f bps > budget %d bps",
                result.action, result.symbol, slippage_bps, result.slippage_budget_bps,
            )

        logger.info(
            "SmartOrderRouter [MEDIUM] %s %s qty=%d depth_avail=%d best_px=%s",
            result.action, result.symbol, result.total_quantity, available, best,
        )

        if available == 0 or result.total_quantity <= available:
            # Fits within top-5 depth — single order
            child = await self._place_child(
                result=result,
                quantity=result.total_quantity,
                price_type=PriceType.MARKET,
                product=product,
                slippage_bps=slippage_bps,
            )
            result.add_child(child)
        else:
            # Split into chunks that fit within available depth
            remaining = result.total_quantity
            chunk = available if available > 0 else result.total_quantity
            first = True
            while remaining > 0:
                qty = min(chunk, remaining)
                if not first:
                    delay = 1.0 + (asyncio.get_event_loop().time() % 4)  # 1–5 s pseudo-random
                    await asyncio.sleep(delay)
                child = await self._place_child(
                    result=result,
                    quantity=qty,
                    price_type=PriceType.MARKET,
                    product=product,
                    slippage_bps=slippage_bps,
                )
                result.add_child(child)
                remaining -= qty
                first = False

    async def _route_low(self, result: SmartRouteResult, product: str) -> None:
        """Low urgency: TWAP — equal slices over a time window.

        Args:
            result: The in-progress :class:`SmartRouteResult` to populate.
            product: Product type string.
        """
        slices = self._twap_slices
        base_qty, remainder = divmod(result.total_quantity, slices)
        interval = self._twap_window_seconds / slices

        logger.info(
            "SmartOrderRouter [LOW/TWAP] %s %s qty=%d slices=%d interval=%.0fs",
            result.action, result.symbol, result.total_quantity, slices, interval,
        )

        for i in range(slices):
            qty = base_qty + (remainder if i == slices - 1 else 0)
            if qty <= 0:
                continue
            if i > 0:
                await asyncio.sleep(interval)
            child = await self._place_child(
                result=result,
                quantity=qty,
                price_type=PriceType.MARKET,
                product=product,
                slippage_bps=0.0,
            )
            result.add_child(child)

    # ------------------------------------------------------------------
    # Child order placement
    # ------------------------------------------------------------------

    async def _place_child(
        self,
        result: SmartRouteResult,
        quantity: int,
        price_type: PriceType,
        product: str,
        slippage_bps: float,
    ) -> ChildOrderResult:
        """Build and dispatch a single child order via the base router.

        Args:
            result: Parent :class:`SmartRouteResult` for context.
            quantity: Quantity for this child.
            price_type: MARKET or LIMIT.
            product: Product type.
            slippage_bps: Estimated slippage for this child.

        Returns:
            :class:`ChildOrderResult` populated with outcome.
        """
        try:
            order = Order(
                symbol=result.symbol,
                exchange=Exchange(result.exchange),
                action=Action(result.action),
                pricetype=price_type,
                quantity=str(quantity),
                strategy=result.strategy,
                product=product,  # type: ignore[arg-type]
            )

            # Support both sync .route() and async .route_order()
            if hasattr(self._base_router, "route_order"):
                decision = await self._base_router.route_order(order)
            else:
                decision = self._base_router.route(order)

            if decision.passed and decision.order_response:
                return ChildOrderResult(
                    quantity=quantity,
                    price_type=price_type.value if hasattr(price_type, "value") else str(price_type),
                    status="placed",
                    order_id=decision.order_response.orderid,
                    slippage_bps=slippage_bps,
                )
            else:
                err = decision.error or "safety block"
                return ChildOrderResult(
                    quantity=quantity,
                    price_type=price_type.value if hasattr(price_type, "value") else str(price_type),
                    status="failed",
                    error=err,
                    slippage_bps=slippage_bps,
                )
        except Exception as exc:
            logger.error("Child order placement error for %s: %s", result.symbol, exc)
            return ChildOrderResult(
                quantity=quantity,
                price_type=price_type.value if hasattr(price_type, "value") else str(price_type),
                status="failed",
                error=str(exc),
                slippage_bps=slippage_bps,
            )

    # ------------------------------------------------------------------
    # Slippage estimation
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_slippage(
        depth: dict,
        action: Literal["BUY", "SELL"],
        quantity: int,
    ) -> float:
        """Estimate slippage in basis points for filling *quantity* from *depth*.

        Walks the price levels consuming quantity until the order is filled.
        Returns the volume-weighted average execution price vs. best price,
        expressed in basis points.

        Args:
            depth: Market depth dict with "asks" and "bids".
            action: "BUY" uses asks; "SELL" uses bids.
            quantity: Quantity to fill.

        Returns:
            Estimated slippage in basis points (0.0 if depth is insufficient
            or best price is zero).
        """
        side = "asks" if action == "BUY" else "bids"
        levels: list[dict] = depth.get(side, [])
        if not levels:
            return 0.0

        best_px = float(levels[0].get("price", 0))
        if best_px == 0:
            return 0.0

        remaining = quantity
        weighted_sum = 0.0
        total_filled = 0

        for lvl in levels:
            px = float(lvl.get("price", 0))
            avail = int(lvl.get("quantity", 0))
            fill = min(remaining, avail)
            weighted_sum += px * fill
            total_filled += fill
            remaining -= fill
            if remaining <= 0:
                break

        if total_filled == 0:
            return 0.0

        vwap = weighted_sum / total_filled
        slippage = abs(vwap - best_px) / best_px * 10_000  # bps
        return round(slippage, 2)
