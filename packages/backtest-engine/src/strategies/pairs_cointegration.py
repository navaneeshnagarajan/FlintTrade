"""Pairs Cointegration strategy.

Engle-Granger style cointegration-based pairs trading. Estimates a dynamic
hedge ratio via OLS regression of the spread, then trades deviations.

No external stats library required — OLS is computed in pure Python.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.pairs_cointegration")


def _ols_hedge_ratio(y: list[float], x: list[float]) -> float:
    """Simple OLS beta: regress y on x, return slope (hedge ratio)."""
    n = len(y)
    if n < 2:
        return 1.0
    sx = sum(x)
    sy = sum(y)
    sxy = sum(xi * yi for xi, yi in zip(x, y))
    sxx = sum(xi ** 2 for xi in x)
    denom = n * sxx - sx * sx
    if denom == 0:
        return 1.0
    return (n * sxy - sx * sy) / denom


class PairsCointegration(BaseStrategy, _BacktestStrategyMixin):
    """Engle-Granger cointegration pairs trading.

    Estimates hedge ratio via rolling OLS window and trades the spread
    z-score. Leg A is the primary instrument; Leg B is passed externally.

    Args:
        lookback: OLS and z-score window (default 60).
        z_entry: Spread z-score to enter (default 2.0).
        z_exit: Spread z-score to exit (default 0.5).
        symbol: Symbol for leg A.
    """

    def __init__(
        self,
        name: str = "PairsCointegration",
        exchange: str = "NSE",
        product: str = "MIS",
        lookback: int = 60,
        z_entry: float = 2.0,
        z_exit: float = 0.5,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.lookback = lookback
        self.z_entry = z_entry
        self.z_exit = z_exit
        self._symbol = symbol
        self._init_history()
        self._b_closes: list[float] = []
        self._spreads: list[float] = []


    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV, bars_b: list[OHLCV] | None = None) -> None:
        self._record_bar(bar)

        if bars_b:
            self._b_closes = [b.close for b in bars_b]

        n = min(len(self._closes), len(self._b_closes))
        if n < self.lookback:
            return

        y = self._closes[-self.lookback:]
        x = self._b_closes[-self.lookback:]
        beta = _ols_hedge_ratio(y, x)
        spread = self._closes[-1] - beta * self._b_closes[-1]
        self._spreads.append(spread)

        if len(self._spreads) < self.lookback:
            return

        window = self._spreads[-self.lookback:]
        mean = sum(window) / self.lookback
        std = (sum((s - mean) ** 2 for s in window) / self.lookback) ** 0.5
        z = (spread - mean) / std if std > 0 else 0.0

        if z > self.z_entry and self._position >= 0:
            self._sell()
        elif z < -self.z_entry and self._position <= 0:
            self._buy()
        elif abs(z) < self.z_exit and self._position != 0:
            if self._position > 0:
                self._sell()
            else:
                self._buy()
                self._flat()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["PairsCointegration"]
