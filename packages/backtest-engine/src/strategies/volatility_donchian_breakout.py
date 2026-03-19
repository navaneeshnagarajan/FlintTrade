"""Donchian Channel Breakout strategy — Volatility category.

Donchian Channels use N-period high/low to define breakout levels.
Trades breakouts above the upper channel or below the lower channel.
Classic trend-following / volatility-expansion strategy.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.volatility_donchian_breakout")


def donchian_channels(
    highs: list[float],
    lows: list[float],
    period: int = 20,
) -> tuple[list[float], list[float], list[float]]:
    """Donchian Channels.

    Args:
        highs: High prices.
        lows: Low prices.
        period: Lookback period (default 20).

    Returns:
        Tuple of (upper, middle, lower) channels.
    """
    n = len(highs)
    upper: list[float] = [0.0] * n
    lower: list[float] = [0.0] * n
    middle: list[float] = [0.0] * n

    for i in range(period - 1, n):
        u = max(highs[i - period + 1: i + 1])
        lo = min(lows[i - period + 1: i + 1])
        upper[i] = u
        lower[i] = lo
        middle[i] = (u + lo) / 2

    return upper, middle, lower


class DonchianBreakout(BaseStrategy, _BacktestStrategyMixin):
    """Donchian Channel breakout strategy.

    Buy: close breaks above the upper channel of the prior N bars.
    Sell: close breaks below the lower channel.
    Optional shorter exit channel to take profits earlier.

    Args:
        entry_period: Breakout lookback period (default 20).
        exit_period: Exit channel period; 0 = use entry_period (default 10).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "DonchianBreakout",
        exchange: str = "NSE",
        product: str = "MIS",
        entry_period: int = 20,
        exit_period: int = 10,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.entry_period = entry_period
        self.exit_period = exit_period if exit_period > 0 else entry_period
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        if len(self._closes) < self.entry_period + 1:
            return

        entry_upper, _, entry_lower = donchian_channels(self._highs, self._lows, self.entry_period)
        exit_upper, _, exit_lower = donchian_channels(self._highs, self._lows, self.exit_period)

        close = self._closes[-1]
        # Entry: compare to prior period's channel (exclude current bar)
        eu_prev = entry_upper[-2]
        el_prev = entry_lower[-2]

        if self._position == 0:
            if close > eu_prev:
                self._buy()
            elif close < el_prev:
                self._sell()
        elif self._position == 1:
            # Exit: price drops below exit lower channel
            if close < exit_lower[-2]:
                self._sell()
        elif self._position == -1:
            # Exit: price rises above exit upper channel
            if close > exit_upper[-2]:
                self._buy()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
