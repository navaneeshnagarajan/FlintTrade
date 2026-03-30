"""Intraday First 5-Minute Candle Breakout strategy (India-specific).

Waits for the first 5-minute candle to complete, then enters on a breakout
above its high (long) or below its low (short) on subsequent bars.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.intraday_first_candle")


class IntradayFirstCandle(BaseStrategy, _BacktestStrategyMixin):
    """First 5-minute candle breakout strategy.

    Captures the high and low of the first candle after session open.
    Enters on breakout (close beyond the range) during the rest of the session.

    Args:
        candle_time: Timestamp of the first candle HH:MM (default "09:15").
        session_close: Force-exit time HH:MM (default "15:15").
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "IntradayFirstCandle",
        exchange: str = "NSE",
        product: str = "MIS",
        candle_time: str = "09:15",
        session_close: str = "15:15",
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.candle_time = candle_time
        self.session_close = session_close
        self._symbol = symbol
        self._init_history()
        self._fc_high: float = 0.0
        self._fc_low: float = 0.0
        self._fc_set: bool = False


    def on_tick(self, quote: Quote) -> None:
        pass

    def _time_part(self, ts: str) -> str:
        return ts[11:16] if len(ts) > 16 else ""

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        tp = self._time_part(bar.timestamp)

        if tp == self.candle_time:
            self._fc_high = bar.high
            self._fc_low = bar.low
            self._fc_set = True
            logger.debug("First candle set: H=%.2f L=%.2f", self._fc_high, self._fc_low)
            return

        if not self._fc_set:
            return

        if tp >= self.session_close and self._position != 0:
            if self._position > 0:
                self._sell()
            else:
                self._buy()
                self._flat()
            return

        close = bar.close
        if self._position == 0:
            if close > self._fc_high:
                self._buy()
            elif close < self._fc_low:
                self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["IntradayFirstCandle"]
