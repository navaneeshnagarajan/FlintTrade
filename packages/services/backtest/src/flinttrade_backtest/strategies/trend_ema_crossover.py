"""EMA Crossover strategy — Trend category.

Re-exports the EMACrossover class from the core strategies module and provides
a configurable variant with a confirmation filter (close above fast EMA on buy).

The base EMACrossover (fast/slow crossover) is already in strategies.py.
This module adds TrendEMACrossover with optional confirmation logic.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import ema
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.trend_ema_crossover")


class TrendEMACrossover(BaseStrategy, _BacktestStrategyMixin):
    """EMA crossover with optional trend confirmation.

    Extends the basic EMA crossover by requiring that:
    - Close is above fast EMA at time of buy signal (avoids false entries).
    - Close is below fast EMA at time of sell signal.

    Uses three EMAs (fast, mid, slow) for stronger trend filtering when
    mid_period > 0.

    Args:
        fast_period: Fast EMA period (default 9).
        mid_period: Middle EMA period for trend filter, 0 = disabled (default 0).
        slow_period: Slow EMA period (default 21).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "TrendEMACrossover",
        exchange: str = "NSE",
        product: str = "MIS",
        fast_period: int = 9,
        mid_period: int = 0,
        slow_period: int = 21,
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
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        warmup = self.slow_period + 1
        if self.mid_period > 0:
            warmup = max(warmup, self.mid_period + 1)
        if len(self._closes) < warmup:
            return

        fast = ema(self._closes, self.fast_period)
        slow = ema(self._closes, self.slow_period)
        close = self._closes[-1]

        cross_up = fast[-1] > slow[-1] and fast[-2] <= slow[-2]
        cross_dn = fast[-1] < slow[-1] and fast[-2] >= slow[-2]

        if self.mid_period > 0:
            mid = ema(self._closes, self.mid_period)
            # All EMAs aligned: fast > mid > slow for buy
            if cross_up and close > fast[-1] and fast[-1] > mid[-1] > slow[-1]:
                self._buy()
            elif cross_dn and close < fast[-1] and fast[-1] < mid[-1] < slow[-1]:
                self._sell()
        else:
            if cross_up and close > fast[-1]:
                self._buy()
            elif cross_dn and close < fast[-1]:
                self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["TrendEMACrossover"]
