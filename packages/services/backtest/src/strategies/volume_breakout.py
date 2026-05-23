"""Volume Breakout strategy — Volume category.

Detects price breakouts confirmed by unusually high volume.
High volume at a breakout level validates the move; low volume suggests a fake-out.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import sma  # noqa: F401 — available for subclass use
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.volume_breakout")


class VolumeBreakout(BaseStrategy, _BacktestStrategyMixin):
    """Volume-confirmed price breakout strategy.

    Entry conditions:
    - Price breaks above N-period high (or below N-period low).
    - Current volume exceeds vol_mult * rolling average volume.

    Exit: Trailing stop at N-period low (for longs) / high (for shorts).

    Args:
        price_period: Lookback for price high/low channel (default 20).
        vol_period: Lookback for average volume (default 20).
        vol_mult: Minimum volume multiple to confirm breakout (default 1.5).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "VolumeBreakout",
        exchange: str = "NSE",
        product: str = "MIS",
        price_period: int = 20,
        vol_period: int = 20,
        vol_mult: float = 1.5,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.price_period = price_period
        self.vol_period = vol_period
        self.vol_mult = vol_mult
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        min_bars = max(self.price_period, self.vol_period) + 2
        if len(self._closes) < min_bars:
            return

        # Exclude current bar for channel definition
        price_window_h = self._highs[-self.price_period - 1:-1]
        price_window_l = self._lows[-self.price_period - 1:-1]
        prev_high = max(price_window_h)
        prev_low = min(price_window_l)

        vol_window = [float(v) for v in self._volumes[-self.vol_period - 1:-1]]
        avg_vol = sum(vol_window) / len(vol_window) if vol_window else 0.0
        cur_vol = self._volumes[-1]
        high_volume = avg_vol > 0 and cur_vol > self.vol_mult * avg_vol

        close = self._closes[-1]

        if self._position == 0:
            if close > prev_high and high_volume:
                self._buy()
            elif close < prev_low and high_volume:
                self._sell()
        elif self._position == 1:
            # Trailing stop: exit if close drops below short-term low
            sl_low = min(self._lows[-self.price_period:]) if len(self._lows) >= self.price_period else 0.0
            if close < sl_low:
                self._sell()
        elif self._position == -1:
            # Trailing stop: exit if close rises above short-term high
            sl_high = max(self._highs[-self.price_period:]) if len(self._highs) >= self.price_period else float("inf")
            if close > sl_high:
                self._buy()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
