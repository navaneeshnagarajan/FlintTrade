"""Pairs Ratio Mean Reversion strategy.

Computes the price ratio between two correlated instruments and trades
mean reversion when the ratio deviates beyond a z-score threshold.

Bars for the second instrument (leg_b) are fed via the bars_b parameter.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.pairs_ratio_reversion")


def _zscore(series: list[float], lookback: int) -> float:
    """Compute z-score of the last value vs rolling window."""
    if len(series) < lookback:
        return 0.0
    window = series[-lookback:]
    mean = sum(window) / lookback
    variance = sum((x - mean) ** 2 for x in window) / lookback
    std = variance ** 0.5
    if std == 0:
        return 0.0
    return (series[-1] - mean) / std


class PairsRatioReversion(BaseStrategy, _BacktestStrategyMixin):
    """Price ratio mean reversion between two correlated instruments.

    Instrument A is the primary (on_bar receives bar A).
    Instrument B prices are passed via bars_b parameter.
    When ratio A/B deviates beyond z_entry std devs, trade mean reversion.

    Args:
        lookback: Rolling window for ratio statistics (default 60).
        z_entry: Z-score threshold to enter trade (default 2.0).
        z_exit: Z-score threshold to exit trade (default 0.5).
        symbol: Symbol for leg A.
        symbol_b: Symbol for leg B (informational).
    """

    def __init__(
        self,
        name: str = "PairsRatioReversion",
        exchange: str = "NSE",
        product: str = "MIS",
        lookback: int = 60,
        z_entry: float = 2.0,
        z_exit: float = 0.5,
        symbol: str = "",
        symbol_b: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.lookback = lookback
        self.z_entry = z_entry
        self.z_exit = z_exit
        self._symbol = symbol
        self.symbol_b = symbol_b
        self._init_history()
        self._b_closes: list[float] = []
        self._ratios: list[float] = []


    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV, bars_b: list[OHLCV] | None = None) -> None:
        self._record_bar(bar)

        if bars_b:
            self._b_closes = [b.close for b in bars_b]

        if not self._b_closes or len(self._closes) != len(self._b_closes):
            return
        if self._b_closes[-1] == 0:
            return

        ratio = self._closes[-1] / self._b_closes[-1]
        self._ratios.append(ratio)

        if len(self._ratios) < self.lookback + 2:
            return

        z = _zscore(self._ratios, self.lookback)

        if z > self.z_entry and self._position >= 0:
            # Ratio too high: sell A, effectively short the spread
            self._sell()
        elif z < -self.z_entry and self._position <= 0:
            # Ratio too low: buy A
            self._buy()
        elif abs(z) < self.z_exit and self._position != 0:
            # Mean reversion: exit
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


__all__ = ["PairsRatioReversion"]
