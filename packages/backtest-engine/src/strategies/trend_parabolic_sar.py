"""Parabolic SAR strategy — Trend category.

Uses the Parabolic SAR indicator for trend direction.
Buys when price crosses above SAR; sells when price crosses below SAR.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.trend_parabolic_sar")


def parabolic_sar(
    highs: list[float],
    lows: list[float],
    af_start: float = 0.02,
    af_step: float = 0.02,
    af_max: float = 0.20,
) -> tuple[list[float], list[bool]]:
    """Parabolic SAR calculation.

    Args:
        highs: List of high prices.
        lows: List of low prices.
        af_start: Initial acceleration factor (default 0.02).
        af_step: AF increment on each new extreme (default 0.02).
        af_max: Maximum acceleration factor (default 0.20).

    Returns:
        Tuple of (sar_values, is_uptrend) lists.
    """
    n = len(highs)
    if n < 2:
        return [0.0] * n, [True] * n

    sar = [0.0] * n
    uptrend = [True] * n

    # Initialise: assume uptrend, SAR starts at first low
    uptrend[0] = True
    sar[0] = lows[0]
    ep = highs[0]  # extreme point
    af = af_start

    for i in range(1, n):
        prev_sar = sar[i - 1]

        if uptrend[i - 1]:
            # Calculate new SAR
            new_sar = prev_sar + af * (ep - prev_sar)
            # SAR must be below two prior lows
            new_sar = min(new_sar, lows[i - 1], lows[max(0, i - 2)])

            if lows[i] < new_sar:
                # Trend reversal to downtrend
                uptrend[i] = False
                sar[i] = ep
                ep = lows[i]
                af = af_start
            else:
                uptrend[i] = True
                sar[i] = new_sar
                if highs[i] > ep:
                    ep = highs[i]
                    af = min(af + af_step, af_max)
        else:
            # Downtrend
            new_sar = prev_sar - af * (prev_sar - ep)
            # SAR must be above two prior highs
            new_sar = max(new_sar, highs[i - 1], highs[max(0, i - 2)])

            if highs[i] > new_sar:
                # Trend reversal to uptrend
                uptrend[i] = True
                sar[i] = ep
                ep = highs[i]
                af = af_start
            else:
                uptrend[i] = False
                sar[i] = new_sar
                if lows[i] < ep:
                    ep = lows[i]
                    af = min(af + af_step, af_max)

    return sar, uptrend


class ParabolicSAR(BaseStrategy, _BacktestStrategyMixin):
    """Parabolic SAR trend-following strategy.

    Buys when price moves above SAR (uptrend starts); sells when below SAR.

    Args:
        af_start: Initial acceleration factor (default 0.02).
        af_step: AF increment per new extreme (default 0.02).
        af_max: Maximum AF cap (default 0.20).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "ParabolicSAR",
        exchange: str = "NSE",
        product: str = "MIS",
        af_start: float = 0.02,
        af_step: float = 0.02,
        af_max: float = 0.20,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.af_start = af_start
        self.af_step = af_step
        self.af_max = af_max
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        if len(self._closes) < 3:
            return
        _, trend = parabolic_sar(self._highs, self._lows, self.af_start, self.af_step, self.af_max)
        if trend[-1] and not trend[-2]:
            self._buy()
        elif not trend[-1] and trend[-2]:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
