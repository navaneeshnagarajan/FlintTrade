"""EMA Crossover strategy — golden cross buy, death cross sell.

First concrete strategy for FlintTrade. Uses fast/slow EMA crossover
to generate BUY/SELL signals with position reversal.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

logger = logging.getLogger("flinttrade.engine.strategies.ema_crossover")


def _ema(prices: list[float], period: int) -> float:
    """Calculate Exponential Moving Average over a price list."""
    k = 2 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = price * k + ema * (1 - k)
    return ema


class EMACrossover(BaseStrategy):
    """EMA crossover strategy with position reversal.

    - Golden cross (fast > slow): BUY
    - Death cross (fast < slow): SELL
    - Reversal: if already short and golden cross, BUY 2x to flip long

    Usage::

        strategy = EMACrossover(
            symbol="RELIANCE", exchange="NSE",
            fast_period=9, slow_period=21,
            quantity=1, product="MIS",
        )
        strategy.start()
        # Feed ticks via on_tick(quote)
    """

    def __init__(
        self,
        symbol: str = "RELIANCE",
        exchange: str = "NSE",
        fast_period: int = 9,
        slow_period: int = 21,
        quantity: int = 1,
        product: str = "MIS",
        router: Any = None,
        **kwargs: Any,
    ) -> None:
        name = kwargs.pop("name", f"EMA_{fast_period}_{slow_period}_{symbol}")
        super().__init__(name=name, exchange=exchange, product=product, **kwargs)

        self.symbol = symbol
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.quantity = quantity
        if router is not None:
            logger.warning(
                "EMACrossover ignores the legacy router argument; generated orders "
                "must be consumed by FlintTrade's canonical gated runtime"
            )

        # State
        self.price_buffer: deque[float] = deque(maxlen=slow_period)
        self.position: int = 0       # +1 long, -1 short, 0 flat
        self.last_signal: str = "NONE"
        self._pending_orders: list[Order] = []

    # ------------------------------------------------------------------
    # ABC implementations
    # ------------------------------------------------------------------

    async def on_tick(self, quote: Quote) -> None:
        """Process a tick: update buffer, compute EMAs, detect crossover."""
        if quote.ltp <= 0:
            return

        self.price_buffer.append(quote.ltp)

        # Need at least slow_period prices for EMA calculation
        if len(self.price_buffer) < self.slow_period:
            return

        prices = list(self.price_buffer)
        fast_ema = _ema(prices, self.fast_period)
        slow_ema = _ema(prices, self.slow_period)

        # Golden cross — BUY
        if fast_ema > slow_ema and self.last_signal != "BUY" and self.position <= 0:
            qty = self.quantity * 2 if self.position == -1 else self.quantity
            await self._place_order("BUY", qty)
            self.position = 1
            self.last_signal = "BUY"
            logger.info(
                "EMA signal: BUY | fast=%.2f slow=%.2f ltp=%.2f | %s",
                fast_ema, slow_ema, quote.ltp, self.symbol,
            )

        # Death cross — SELL
        elif fast_ema < slow_ema and self.last_signal != "SELL" and self.position >= 0:
            qty = self.quantity * 2 if self.position == 1 else self.quantity
            await self._place_order("SELL", qty)
            self.position = -1
            self.last_signal = "SELL"
            logger.info(
                "EMA signal: SELL | fast=%.2f slow=%.2f ltp=%.2f | %s",
                fast_ema, slow_ema, quote.ltp, self.symbol,
            )

    def on_bar(self, bar: OHLCV) -> None:
        """Not used — this strategy runs on ticks."""

    def on_signal(self, signal: dict[str, Any]) -> None:
        """Not used — this strategy generates its own signals."""

    def generate_orders(self) -> list[Order]:
        """Return and clear any pending orders."""
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders

    # ------------------------------------------------------------------
    # Square-off and stop
    # ------------------------------------------------------------------

    async def on_square_off(self) -> None:
        """Close any open position at market."""
        if self.position == 1:
            await self._place_order("SELL", self.quantity)
            logger.info("Square-off: closed LONG position for %s", self.symbol)
        elif self.position == -1:
            await self._place_order("BUY", self.quantity)
            logger.info("Square-off: closed SHORT position for %s", self.symbol)
        self.position = 0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _place_order(self, action: str, qty: int) -> None:
        """Build an order intent for the canonical gated strategy runtime."""
        order = Order(
            symbol=self.symbol,
            action=action,
            exchange=self.exchange,
            pricetype="MARKET",
            product=self.product,
            quantity=str(qty),
            strategy=self.name,
        )

        self._pending_orders.append(order)
