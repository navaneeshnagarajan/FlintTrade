"""Intraday Opening Range Breakout with ATR targets (India-specific).

Computes the opening range high/low in the first N minutes of the session.
Enters on breakout with ATR-scaled targets and stops.

Session timings: 09:15–15:30 IST (NSE/BSE).
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import atr
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.intraday_orb_atr")


class IntradayORBATR(BaseStrategy, _BacktestStrategyMixin):
    """Opening Range Breakout with ATR-based targets and stops.

    The opening range is defined as the high/low over the first ``orb_minutes``
    of the session. Entry is triggered on a bar close outside the range.
    Target = entry + atr_target * ATR; stop = entry - atr_stop * ATR.

    Args:
        orb_minutes: Minutes of opening range (default 15).
        atr_period: ATR lookback period (default 14).
        atr_target: Target as multiple of ATR (default 2.0).
        atr_stop: Stop as multiple of ATR (default 1.0).
        session_open: Market open time HH:MM IST (default "09:15").
        session_close: Force-exit time HH:MM IST (default "15:15").
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "IntradayORBATR",
        exchange: str = "NSE",
        product: str = "MIS",
        orb_minutes: int = 15,
        atr_period: int = 14,
        atr_target: float = 2.0,
        atr_stop: float = 1.0,
        session_open: str = "09:15",
        session_close: str = "15:15",
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.orb_minutes = orb_minutes
        self.atr_period = atr_period
        self.atr_target = atr_target
        self.atr_stop = atr_stop
        self.session_open = session_open
        self.session_close = session_close
        self._symbol = symbol
        self._init_history()
        self._orb_high: float = 0.0
        self._orb_low: float = float("inf")
        self._orb_set: bool = False
        self._orb_bars: int = 0
        self._entry_price: float = 0.0
        self._entry_atr: float = 0.0


    def on_tick(self, quote: Quote) -> None:
        pass

    def _time_part(self, ts: str) -> str:
        return ts[11:16] if len(ts) > 16 else ""

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        tp = self._time_part(bar.timestamp)

        # Reset at session open
        if tp == self.session_open:
            self._orb_high = 0.0
            self._orb_low = float("inf")
            self._orb_set = False
            self._orb_bars = 0
            self._entry_price = 0.0

        # Build opening range
        if not self._orb_set:
            self._orb_bars += 1
            self._orb_high = max(self._orb_high, bar.high)
            self._orb_low = min(self._orb_low, bar.low)
            if self._orb_bars >= self.orb_minutes:
                self._orb_set = True
                logger.debug("ORB set: H=%.2f L=%.2f", self._orb_high, self._orb_low)
            return

        # Force exit at session close
        if tp >= self.session_close and self._position != 0:
            if self._position > 0:
                self._sell()
            else:
                self._buy()
                self._flat()
            return

        if len(self._closes) < self.atr_period + 2:
            return

        atr_vals = atr(self._highs, self._lows, self._closes, self.atr_period)
        cur_atr = atr_vals[-1]
        close = bar.close

        # Entry
        if self._position == 0:
            if close > self._orb_high:
                self._buy()
                self._entry_price = close
                self._entry_atr = cur_atr
            elif close < self._orb_low:
                self._sell()
                self._entry_price = close
                self._entry_atr = cur_atr
            return

        # Manage long
        if self._position == 1 and self._entry_price > 0:
            target = self._entry_price + self.atr_target * self._entry_atr
            stop = self._entry_price - self.atr_stop * self._entry_atr
            if close >= target or close <= stop:
                self._sell()
                self._entry_price = 0.0

        # Manage short
        elif self._position == -1 and self._entry_price > 0:
            target = self._entry_price - self.atr_target * self._entry_atr
            stop = self._entry_price + self.atr_stop * self._entry_atr
            if close <= target or close >= stop:
                self._buy()
                self._flat()
                self._entry_price = 0.0

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["IntradayORBATR"]
