"""SMA Crossover strategy — Trend category.

Buy when fast SMA crosses above slow SMA; sell on reverse crossover.
Simple and robust baseline for trend-following.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._indicators import sma
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.trend_sma_crossover")


class SMACrossover(BaseStrategy, _BacktestStrategyMixin):
    """SMA crossover strategy.

    Entry: fast SMA crosses above slow SMA (buy) or below slow SMA (sell).
    Exit: reverse crossover.

    Args:
        fast_period: Period for the fast SMA (default 20).
        slow_period: Period for the slow SMA (default 50).
        symbol: Instrument symbol for order generation.
    """

    def __init__(
        self,
        name: str = "SMACrossover",
        exchange: str = "NSE",
        product: str = "MIS",
        fast_period: int = 20,
        slow_period: int = 50,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.fast_period = fast_period
        self.slow_period = slow_period
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        if len(self._closes) < self.slow_period + 1:
            return
        fast = sma(self._closes, self.fast_period)
        slow = sma(self._closes, self.slow_period)
        if fast[-1] > slow[-1] and fast[-2] <= slow[-2]:
            self._buy()
        elif fast[-1] < slow[-1] and fast[-2] >= slow[-2]:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
