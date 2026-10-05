"""Two-scale trend agreement using FlintTrade's native indicator library."""
from __future__ import annotations

import math
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import supertrend
from ._mixin import _BacktestStrategyMixin


class DoubleSupertrend(BaseStrategy, _BacktestStrategyMixin):
    """Produce one intent when two ATR-band trends enter agreement.

    Disagreement rearms the confirmation. Repeated agreement emits no further
    intents. Indicators consume only completed bars through the native mixin.
    """

    def __init__(self, name: str = "DoubleSupertrend", exchange: str = "NSE", product: str = "MIS",
                 fast_period: int = 7, fast_mult: float = 3.0, slow_period: int = 14,
                 slow_mult: float = 5.0, symbol: str = "", **kwargs: Any) -> None:
        if min(fast_period, slow_period) < 1 or any(not math.isfinite(value) or value <= 0
                                                 for value in (fast_mult, slow_mult)):
            raise ValueError("ATR periods and multipliers must be positive")
        super().__init__(name=name, exchange=exchange, product=product)
        self.fast_period, self.slow_period = fast_period, slow_period
        self.fast_mult, self.slow_mult = fast_mult, slow_mult
        self._symbol = symbol
        self._confirmation: bool | None = None
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        """Quotes do not change a completed-bar indicator."""

    def on_signal(self, signal: dict[str, Any]) -> None:
        """External signals do not bypass trend confirmation."""

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        if len(self._closes) < max(self.fast_period, self.slow_period) + 2:
            return
        directions = [supertrend(self._highs, self._lows, self._closes, period, multiple)[1][-1]
                      for period, multiple in ((self.fast_period, self.fast_mult), (self.slow_period, self.slow_mult))]
        agreement = bool(directions[0]) if directions[0] == directions[1] else None
        previous, self._confirmation = self._confirmation, agreement
        if agreement is not None and agreement != previous:
            (self._buy if agreement else self._sell)()

    def generate_orders(self) -> list[Order]:
        pending, self._pending_orders = self._pending_orders, []
        return pending


__all__ = ["DoubleSupertrend"]
