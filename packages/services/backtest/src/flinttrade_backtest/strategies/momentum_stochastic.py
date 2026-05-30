"""Stochastic Crossover strategy — Momentum category.

%K and %D crossover signals in oversold/overbought zones.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import sma
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.momentum_stochastic")


def stochastic(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    k_period: int = 14,
    d_period: int = 3,
    smooth_k: int = 3,
) -> tuple[list[float], list[float]]:
    """Stochastic oscillator (%K and %D).

    Args:
        highs: High prices.
        lows: Low prices.
        closes: Close prices.
        k_period: Fast %K lookback (default 14).
        d_period: %D smoothing period (default 3).
        smooth_k: %K smoothing period; 1 = raw fast stochastic (default 3).

    Returns:
        Tuple of (%K, %D) smoothed series.
    """
    n = len(closes)
    raw_k: list[float] = [50.0] * n
    for i in range(k_period - 1, n):
        h_max = max(highs[i - k_period + 1: i + 1])
        l_min = min(lows[i - k_period + 1: i + 1])
        rng = h_max - l_min
        raw_k[i] = (closes[i] - l_min) / rng * 100 if rng != 0 else 50.0

    smooth_k_vals = sma(raw_k, smooth_k)
    # Fill leading zeros with 50 so SMA has something to work with
    smooth_k_vals = [v if v != 0 else 50.0 for v in smooth_k_vals]
    d_vals = sma(smooth_k_vals, d_period)
    d_vals = [v if v != 0 else 50.0 for v in d_vals]

    return smooth_k_vals, d_vals


class StochasticCrossover(BaseStrategy, _BacktestStrategyMixin):
    """Stochastic %K/%D crossover momentum strategy.

    Buy: %K crosses above %D in oversold zone (below oversold threshold).
    Sell: %K crosses below %D in overbought zone (above overbought threshold).

    Args:
        k_period: %K lookback (default 14).
        d_period: %D smoothing (default 3).
        smooth_k: %K smoothing period (default 3).
        oversold: Threshold for oversold (default 20).
        overbought: Threshold for overbought (default 80).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "StochasticCrossover",
        exchange: str = "NSE",
        product: str = "MIS",
        k_period: int = 14,
        d_period: int = 3,
        smooth_k: int = 3,
        oversold: float = 20.0,
        overbought: float = 80.0,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.k_period = k_period
        self.d_period = d_period
        self.smooth_k = smooth_k
        self.oversold = oversold
        self.overbought = overbought
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        min_bars = self.k_period + self.d_period + self.smooth_k + 1
        if len(self._closes) < min_bars:
            return

        k_vals, d_vals = stochastic(
            self._highs, self._lows, self._closes,
            self.k_period, self.d_period, self.smooth_k,
        )

        k_cur, k_prev = k_vals[-1], k_vals[-2]
        d_cur, d_prev = d_vals[-1], d_vals[-2]

        cross_up = k_cur > d_cur and k_prev <= d_prev
        cross_dn = k_cur < d_cur and k_prev >= d_prev

        if cross_up and k_cur < self.oversold:
            self._buy()
        elif cross_dn and k_cur > self.overbought:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
