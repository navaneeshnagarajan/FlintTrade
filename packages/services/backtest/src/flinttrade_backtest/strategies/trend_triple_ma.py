"""Triple Moving Average trend strategy — Trend category.

Uses three moving averages of different periods. When they are perfectly ordered
(fast > mid > slow) the trend is strongly up; when (fast < mid < slow) strongly
down. The triple stack filters out the noise-prone two-MA crossovers.

Trading rules:
    BUY  when fast_ma > mid_ma > slow_ma (all three stacked bullishly).
    SELL when fast_ma < mid_ma < slow_ma (all three stacked bearishly).
    FLAT when the MAs are not perfectly ordered (no new signal, hold existing).
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import ema
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.trend_triple_ma")


class TripleMA(BaseStrategy, _BacktestStrategyMixin):
    """Triple EMA trend-following strategy.

    Enters long when fast > mid > slow (bullish stack).
    Enters short when fast < mid < slow (bearish stack).
    Exits when the stack is no longer perfectly ordered.

    Args:
        fast_period: Fast EMA period (default 10).
        mid_period: Mid EMA period (default 20).
        slow_period: Slow EMA period (default 50).
        symbol: Instrument symbol (default "").
        exchange: Exchange code (default "NSE").
        product: Product type (default "MIS").
    """

    def __init__(
        self,
        name: str = "TripleMA",
        exchange: str = "NSE",
        product: str = "MIS",
        fast_period: int = 10,
        mid_period: int = 20,
        slow_period: int = 50,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.fast_period = fast_period
        self.mid_period = mid_period
        self.slow_period = slow_period
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        """Not used — bar-close strategy."""

    def on_bar(self, bar: OHLCV) -> None:
        """Process a completed bar and emit orders when triple stack fires.

        Args:
            bar: The just-closed OHLCV bar.
        """
        if not self.is_active:
            return
        self._record_bar(bar)
        if len(self._closes) < self.slow_period + 1:
            return

        fast_vals = ema(self._closes, self.fast_period)
        mid_vals = ema(self._closes, self.mid_period)
        slow_vals = ema(self._closes, self.slow_period)

        f = fast_vals[-1]
        m = mid_vals[-1]
        s = slow_vals[-1]

        bull_stack = f > m > s
        bear_stack = f < m < s

        if bull_stack:
            if self._position != 1:
                logger.debug(
                    "Bull stack | f=%.2f m=%.2f s=%.2f | %s", f, m, s, self._symbol
                )
                self._buy()
        elif bear_stack:
            if self._position != -1:
                logger.debug(
                    "Bear stack | f=%.2f m=%.2f s=%.2f | %s", f, m, s, self._symbol
                )
                self._sell()
        else:
            # Stack broken — exit existing position
            if self._position == 1:
                self._sell()
                self._flat()
            elif self._position == -1:
                self._buy()
                self._flat()

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
