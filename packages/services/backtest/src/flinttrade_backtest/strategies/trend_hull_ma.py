"""Hull Moving Average strategy — Trend category.

HMA = WMA(2*WMA(n/2) - WMA(n), sqrt(n))
Faster and smoother than EMA; reduces lag significantly.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.trend_hull_ma")


def wma(values: list[float], period: int) -> list[float]:
    """Weighted Moving Average.

    Args:
        values: Price series.
        period: Lookback period.

    Returns:
        WMA series; leading values are 0.0.
    """
    n = len(values)
    result: list[float] = [0.0] * n
    weights = list(range(1, period + 1))
    w_sum = sum(weights)
    for i in range(period - 1, n):
        window = values[i - period + 1: i + 1]
        result[i] = sum(w * v for w, v in zip(weights, window)) / w_sum
    return result


def hull_ma(values: list[float], period: int) -> list[float]:
    """Hull Moving Average.

    Args:
        values: Price series.
        period: HMA period.

    Returns:
        HMA series; leading values are 0.0 until warm-up complete.
    """
    half = max(1, period // 2)
    sqrt_p = max(1, int(math.isqrt(period)))

    wma_half = wma(values, half)
    wma_full = wma(values, period)

    # Intermediate: 2*WMA(n/2) - WMA(n)
    n = len(values)
    diff: list[float] = [0.0] * n
    for i in range(n):
        if wma_half[i] and wma_full[i]:
            diff[i] = 2 * wma_half[i] - wma_full[i]

    # Final HMA = WMA(diff, sqrt(period))
    return wma(diff, sqrt_p)


class HullMA(BaseStrategy, _BacktestStrategyMixin):
    """Hull Moving Average trend strategy.

    Buy when HMA turns upward (current > previous); sell when it turns downward.
    Optionally confirm with two consecutive up/down bars for reduced whipsaws.

    Args:
        period: HMA period (default 20).
        confirm_bars: Number of consecutive direction bars required (default 1).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "HullMA",
        exchange: str = "NSE",
        product: str = "MIS",
        period: int = 20,
        confirm_bars: int = 1,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.period = period
        self.confirm_bars = confirm_bars
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        min_bars = self.period + int(math.isqrt(self.period)) + self.confirm_bars + 1
        if len(self._closes) < min_bars:
            return

        hma = hull_ma(self._closes, self.period)

        # Determine direction using last confirm_bars+1 values
        up = all(hma[-(i + 1)] > hma[-(i + 2)] for i in range(self.confirm_bars))
        dn = all(hma[-(i + 1)] < hma[-(i + 2)] for i in range(self.confirm_bars))

        # Crossover detection
        prev_up = hma[-2] > hma[-3] if len(hma) > 2 else False
        prev_dn = hma[-2] < hma[-3] if len(hma) > 2 else False

        if up and not prev_up:
            self._buy()
        elif dn and not prev_dn:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
