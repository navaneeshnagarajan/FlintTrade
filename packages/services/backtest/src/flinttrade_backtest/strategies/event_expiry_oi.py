"""Event-Driven Max Pain Convergence (Expiry OI) strategy (India-specific).

As weekly/monthly expiry approaches, the underlying tends to drift toward the
max pain level — the strike with the highest open interest. This strategy
positions in that direction from Wednesday onwards (for Thursday expiry).
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.event_expiry_oi")


class EventExpiryOI(BaseStrategy, _BacktestStrategyMixin):
    """Max pain convergence strategy using OI data near expiry.

    max_pain_level is set externally via set_max_pain(). The strategy
    trades toward max pain from a configurable bar before expiry.

    Args:
        bars_before_expiry: Bars before expiry to start trading (default 5).
        pain_threshold_pct: Minimum distance from max pain to enter (default 0.3).
        symbol: Underlying index symbol.
    """

    def __init__(
        self,
        name: str = "EventExpiryOI",
        exchange: str = "NFO",
        product: str = "MIS",
        bars_before_expiry: int = 5,
        pain_threshold_pct: float = 0.3,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.bars_before_expiry = bars_before_expiry
        self.pain_threshold_pct = pain_threshold_pct
        self._symbol = symbol
        self._init_history()
        self._expiry_bar_idx: int = -1
        self._max_pain: float = 0.0


    def set_max_pain(self, max_pain_level: float, expiry_bar_idx: int) -> None:
        """Set max pain level and expiry bar index.

        Args:
            max_pain_level: Max pain strike price.
            expiry_bar_idx: Bar index of expiry.
        """
        self._max_pain = max_pain_level
        self._expiry_bar_idx = expiry_bar_idx

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        idx = len(self._closes) - 1

        if self._expiry_bar_idx < 0 or self._max_pain <= 0:
            return

        bars_to_expiry = self._expiry_bar_idx - idx

        # Exit on expiry bar
        if bars_to_expiry <= 0 and self._position != 0:
            if self._position > 0:
                self._sell()
            else:
                self._buy()
                self._flat()
            return

        # Start trading within the window
        if bars_to_expiry > self.bars_before_expiry:
            return

        close = bar.close
        if self._max_pain == 0:
            return
        distance_pct = (close - self._max_pain) / self._max_pain * 100

        if distance_pct > self.pain_threshold_pct and self._position >= 0:
            # Price above max pain → sell toward pain
            self._sell()
        elif distance_pct < -self.pain_threshold_pct and self._position <= 0:
            # Price below max pain → buy toward pain
            self._buy()
        elif abs(distance_pct) < 0.1 and self._position != 0:
            # Near max pain: exit
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


__all__ = ["EventExpiryOI"]
