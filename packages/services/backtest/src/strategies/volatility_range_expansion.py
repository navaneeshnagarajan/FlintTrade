"""Range Expansion strategy — Volatility category.

Detects days/bars where the current range expands significantly beyond
the average true range, signalling a strong directional breakout.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin
from .mean_reversion_keltner import atr

logger = logging.getLogger("flinttrade.backtest.strategies.volatility_range_expansion")


class RangeExpansion(BaseStrategy, _BacktestStrategyMixin):
    """Range expansion breakout strategy.

    Identifies bars where the true range is a multiple of the average ATR,
    indicating a volatility expansion / breakout. Enters in the direction of
    the expansion bar's close relative to its midpoint.

    Args:
        atr_period: ATR period for average range (default 14).
        expansion_mult: Minimum ratio of bar range to ATR to qualify (default 2.0).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "RangeExpansion",
        exchange: str = "NSE",
        product: str = "MIS",
        atr_period: int = 14,
        expansion_mult: float = 2.0,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.atr_period = atr_period
        self.expansion_mult = expansion_mult
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        if len(self._closes) < self.atr_period + 2:
            return

        atr_vals = atr(self._highs, self._lows, self._closes, self.atr_period)
        avg_atr = atr_vals[-2]  # prior bar's ATR (not current to avoid look-ahead)
        if avg_atr == 0:
            return

        cur_range = self._highs[-1] - self._lows[-1]
        bar_mid = (self._highs[-1] + self._lows[-1]) / 2
        close = self._closes[-1]

        is_expansion = cur_range > self.expansion_mult * avg_atr

        if is_expansion and self._position == 0:
            if close > bar_mid:
                self._buy()
            elif close < bar_mid:
                self._sell()

        # Exit on next bar close (single-bar trade; re-entry on next expansion)
        elif not is_expansion and self._position != 0:
            if self._position == 1:
                self._sell()
            else:
                self._buy()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
