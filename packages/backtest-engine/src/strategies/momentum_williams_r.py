"""Williams %R strategy — Momentum category.

Williams %R is a momentum oscillator ranging from -100 to 0.
-80 to -100 is oversold (potential buy zone).
0 to -20 is overbought (potential sell zone).
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.momentum_williams_r")


def williams_r(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> list[float]:
    """Williams %R oscillator.

    Args:
        highs: High prices.
        lows: Low prices.
        closes: Close prices.
        period: Lookback period (default 14).

    Returns:
        %R values ranging -100 to 0; leading values are -50.
    """
    n = len(closes)
    result: list[float] = [-50.0] * n
    for i in range(period - 1, n):
        h_max = max(highs[i - period + 1: i + 1])
        l_min = min(lows[i - period + 1: i + 1])
        rng = h_max - l_min
        result[i] = -100.0 * (h_max - closes[i]) / rng if rng != 0 else -50.0
    return result


class WilliamsR(BaseStrategy, _BacktestStrategyMixin):
    """Williams %R momentum strategy.

    Buy: %R crosses above oversold level (e.g. -80).
    Sell: %R crosses below overbought level (e.g. -20).

    Args:
        period: Lookback period (default 14).
        oversold: Buy threshold (default -80, i.e. crosses above -80).
        overbought: Sell threshold (default -20, i.e. crosses below -20).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "WilliamsR",
        exchange: str = "NSE",
        product: str = "MIS",
        period: int = 14,
        oversold: float = -80.0,
        overbought: float = -20.0,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        if len(self._closes) < self.period + 1:
            return

        wr = williams_r(self._highs, self._lows, self._closes, self.period)
        cur, prev = wr[-1], wr[-2]

        # Cross above oversold → buy momentum
        if cur > self.oversold and prev <= self.oversold:
            self._buy()
        # Cross below overbought → sell momentum
        elif cur < self.overbought and prev >= self.overbought:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
