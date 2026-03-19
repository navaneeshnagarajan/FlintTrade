"""Supertrend strategies — Trend category.

Includes:
- TrendSupertrend: standalone configurable Supertrend (wraps parent class).
- DoubleSupertrend: two Supertrend instances, both must agree before entry.
  Inspired by the doublesupertrend reference in openalgostratagies repo.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._indicators import supertrend
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.trend_supertrend")


class DoubleSupertrend(BaseStrategy, _BacktestStrategyMixin):
    """Double Supertrend confirmation strategy.

    Two Supertrend indicators with different ATR periods/multipliers must
    both agree on trend direction before an entry is triggered.
    Reduces false signals compared to a single Supertrend.

    Args:
        fast_period: ATR period for the faster Supertrend (default 7).
        fast_mult: ATR multiplier for the faster Supertrend (default 3.0).
        slow_period: ATR period for the slower Supertrend (default 14).
        slow_mult: ATR multiplier for the slower Supertrend (default 5.0).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "DoubleSupertrend",
        exchange: str = "NSE",
        product: str = "MIS",
        fast_period: int = 7,
        fast_mult: float = 3.0,
        slow_period: int = 14,
        slow_mult: float = 5.0,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.fast_period = fast_period
        self.fast_mult = fast_mult
        self.slow_period = slow_period
        self.slow_mult = slow_mult
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        min_bars = max(self.fast_period, self.slow_period) + 2
        if len(self._closes) < min_bars:
            return

        _, fast_trend = supertrend(
            self._highs, self._lows, self._closes,
            self.fast_period, self.fast_mult,
        )
        _, slow_trend = supertrend(
            self._highs, self._lows, self._closes,
            self.slow_period, self.slow_mult,
        )

        # Both uptrend → buy signal; both downtrend → sell signal
        both_up_now = fast_trend[-1] and slow_trend[-1]
        both_up_prev = fast_trend[-2] and slow_trend[-2]
        both_dn_now = not fast_trend[-1] and not slow_trend[-1]
        both_dn_prev = not fast_trend[-2] and not slow_trend[-2]

        if both_up_now and not both_up_prev:
            self._buy()
        elif both_dn_now and not both_dn_prev:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["DoubleSupertrend"]
