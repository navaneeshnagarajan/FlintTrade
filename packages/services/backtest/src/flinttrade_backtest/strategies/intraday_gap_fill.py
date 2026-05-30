"""Intraday Gap Fill strategy (India-specific).

Detects gap-up or gap-down at market open vs previous day's close.
Trades the gap fill with volume confirmation. Common in Indian markets
where overnight gaps often fill before 11:00 IST.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.intraday_gap_fill")


class IntradayGapFill(BaseStrategy, _BacktestStrategyMixin):
    """Gap up/down fill strategy with volume confirmation.

    Detects gap at session open. If gap is significant (> gap_pct of prev close),
    trade against the gap (fade it) expecting mean reversion. Requires volume
    at first bar to exceed vol_multiplier * recent average volume.

    Args:
        gap_pct: Minimum gap size as % of prev close (default 0.5).
        vol_multiplier: Volume at open must be N x avg volume (default 1.5).
        exit_time: Force-exit time HH:MM (default "12:00").
        session_open: Market open time HH:MM (default "09:15").
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "IntradayGapFill",
        exchange: str = "NSE",
        product: str = "MIS",
        gap_pct: float = 0.5,
        vol_multiplier: float = 1.5,
        exit_time: str = "12:00",
        session_open: str = "09:15",
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.gap_pct = gap_pct
        self.vol_multiplier = vol_multiplier
        self.exit_time = exit_time
        self.session_open = session_open
        self._symbol = symbol
        self._init_history()
        self._prev_close: float = 0.0
        self._gap_direction: int = 0  # +1 gap-up, -1 gap-down
        self._entered_today: bool = False


    def on_tick(self, quote: Quote) -> None:
        pass

    def _time_part(self, ts: str) -> str:
        return ts[11:16] if len(ts) > 16 else ""

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        tp = self._time_part(bar.timestamp)

        # Detect gap at open
        if tp == self.session_open:
            self._entered_today = False
            self._gap_direction = 0
            if self._prev_close > 0:
                gap = (bar.open - self._prev_close) / self._prev_close * 100
                if gap > self.gap_pct:
                    self._gap_direction = 1  # gap up: fade (sell)
                elif gap < -self.gap_pct:
                    self._gap_direction = -1  # gap down: fade (buy)

                # Volume confirmation
                if len(self._volumes) > 10:
                    avg_vol = sum(self._volumes[-11:-1]) / 10
                    vol_ok = bar.volume >= avg_vol * self.vol_multiplier
                else:
                    vol_ok = True

                if self._gap_direction != 0 and vol_ok and not self._entered_today:
                    if self._gap_direction == -1:  # gap down → buy (fill up)
                        self._buy()
                    else:  # gap up → sell (fill down)
                        self._sell()
                    self._entered_today = True

            self._prev_close = bar.close
            return

        # Force exit at exit_time or on gap fill
        if tp >= self.exit_time and self._position != 0:
            if self._position > 0:
                self._sell()
            else:
                self._buy()
                self._flat()
            return

        # Gap fill detection: price crosses back to prev_close level
        if self._position != 0 and self._prev_close > 0:
            if self._position == 1 and bar.close >= self._prev_close:
                self._sell()
            elif self._position == -1 and bar.close <= self._prev_close:
                self._buy()
                self._flat()

        # Update daily close tracker
        if tp >= "15:29":
            self._prev_close = bar.close

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["IntradayGapFill"]
