"""Rate of Change (ROC) strategy — Momentum category.

ROC measures percentage change over N periods.
Positive ROC indicates upward momentum; negative indicates downward.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.momentum_roc")


def rate_of_change(values: list[float], period: int = 12) -> list[float]:
    """Rate of Change indicator.

    Args:
        values: Price series.
        period: Lookback period (default 12).

    Returns:
        ROC series as percentage; leading values are 0.0.
    """
    n = len(values)
    result: list[float] = [0.0] * n
    for i in range(period, n):
        prev = values[i - period]
        result[i] = ((values[i] - prev) / prev * 100) if prev != 0 else 0.0
    return result


class ROCMomentum(BaseStrategy, _BacktestStrategyMixin):
    """Rate of Change momentum strategy.

    Buy: ROC crosses above positive threshold (strong upward momentum).
    Sell: ROC crosses below negative threshold (strong downward momentum).
    Exit: ROC crosses zero.

    Args:
        period: ROC lookback (default 12).
        threshold: Minimum |ROC| to trigger entry (default 2.0 percent).
        exit_on_zero: Exit when ROC crosses zero line (default True).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "ROCMomentum",
        exchange: str = "NSE",
        product: str = "MIS",
        period: int = 12,
        threshold: float = 2.0,
        exit_on_zero: bool = True,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.period = period
        self.threshold = threshold
        self.exit_on_zero = exit_on_zero
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        if len(self._closes) < self.period + 2:
            return

        roc = rate_of_change(self._closes, self.period)
        cur, prev = roc[-1], roc[-2]

        if cur > self.threshold and prev <= self.threshold:
            self._buy()
        elif cur < -self.threshold and prev >= -self.threshold:
            self._sell()

        if self.exit_on_zero:
            if self._position == 1 and cur < 0 and prev >= 0:
                self._sell()
            elif self._position == -1 and cur > 0 and prev <= 0:
                self._buy()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
