"""Laguerre RSI momentum strategy — Momentum category.

Laguerre RSI applies a Laguerre filter to smooth the RSI oscillator, reducing
noise while maintaining responsiveness. The gamma parameter controls the
smoothing degree (higher gamma = more smoothing, slower response).

Entry logic:
    BUY  when Laguerre RSI crosses above the oversold level (default 0.2).
    SELL when Laguerre RSI crosses below the overbought level (default 0.8).
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._indicators import laguerre_rsi
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.momentum_laguerre_rsi")


class LaguerreRSI(BaseStrategy, _BacktestStrategyMixin):
    """Laguerre RSI crossover momentum strategy.

    Uses a Laguerre filter to produce a smoother oscillator bounded in [0, 1].
    Signals fire on level crossovers rather than price crossovers, making them
    less susceptible to whipsaws than a standard RSI strategy.

    Args:
        gamma: Laguerre damping factor in (0, 1). Higher values produce
            smoother but more lagging signals (default 0.5).
        oversold: LaRSI level at or below which we consider the market
            oversold; a cross ABOVE triggers BUY (default 0.2).
        overbought: LaRSI level at or above which we consider the market
            overbought; a cross BELOW triggers SELL (default 0.8).
        symbol: Instrument symbol (default "").
        exchange: Exchange code (default "NSE").
        product: Product type (default "MIS").
    """

    def __init__(
        self,
        name: str = "LaguerreRSI",
        exchange: str = "NSE",
        product: str = "MIS",
        gamma: float = 0.5,
        oversold: float = 0.2,
        overbought: float = 0.8,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.gamma = gamma
        self.oversold = oversold
        self.overbought = overbought
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        """Not used — bar-close strategy."""

    def on_bar(self, bar: OHLCV) -> None:
        """Process a completed bar and emit orders on LaRSI level crossovers.

        Args:
            bar: The just-closed OHLCV bar.
        """
        if not self.is_active:
            return
        self._record_bar(bar)
        # Need at least 3 bars to seed the Laguerre filter meaningfully
        if len(self._closes) < 3:
            return

        larsi = laguerre_rsi(self._closes, self.gamma)
        if len(larsi) < 2:
            return

        prev = larsi[-2]
        curr = larsi[-1]

        # Cross above oversold → momentum turning up → BUY
        if prev <= self.oversold < curr:
            logger.debug("LaRSI cross-up oversold=%.2f curr=%.4f | %s", self.oversold, curr, self._symbol)
            self._buy()

        # Cross below overbought → momentum turning down → SELL
        elif prev >= self.overbought > curr:
            logger.debug("LaRSI cross-dn overbought=%.2f curr=%.4f | %s", self.overbought, curr, self._symbol)
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        """Not used — strategy generates its own signals."""

    def generate_orders(self) -> list[Order]:
        """Return and clear all pending orders.

        Returns:
            List of Order objects to submit to the engine.
        """
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
