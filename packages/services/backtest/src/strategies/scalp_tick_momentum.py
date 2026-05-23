"""Scalp Tick Momentum Burst strategy.

Detects rapid consecutive tick-direction bursts (all up-ticks or all down-ticks)
that signal short-term momentum. In bar-by-bar backtest mode, approximated
by N consecutive same-direction bars.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.scalp_tick_momentum")


class ScalpTickMomentum(BaseStrategy, _BacktestStrategyMixin):
    """Tick-by-tick momentum burst detection.

    In bar mode: counts consecutive up/down closes. Enters on a burst
    of consec_bars consecutive same-direction bars, expecting continuation.
    Exits on any reversal bar.

    Args:
        consec_bars: Number of consecutive same-direction bars to trigger (default 3).
        session_close: Force-exit HH:MM (default "15:15").
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "ScalpTickMomentum",
        exchange: str = "NSE",
        product: str = "MIS",
        consec_bars: int = 3,
        session_close: str = "15:15",
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.consec_bars = consec_bars
        self.session_close = session_close
        self._symbol = symbol
        self._init_history()
        self._consec_up: int = 0
        self._consec_dn: int = 0


    def _time_part(self, ts: str) -> str:
        return ts[11:16] if len(ts) > 16 else ""

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        tp = self._time_part(bar.timestamp)

        if tp >= self.session_close and self._position != 0:
            if self._position > 0:
                self._sell()
            else:
                self._buy()
                self._flat()
            return

        if len(self._closes) < 2:
            return

        up_bar = self._closes[-1] > self._closes[-2]
        dn_bar = self._closes[-1] < self._closes[-2]

        if up_bar:
            self._consec_up += 1
            self._consec_dn = 0
        elif dn_bar:
            self._consec_dn += 1
            self._consec_up = 0
        else:
            self._consec_up = 0
            self._consec_dn = 0

        # Exit on reversal
        if self._position == 1 and dn_bar:
            self._sell()
            return
        if self._position == -1 and up_bar:
            self._buy()
            self._flat()
            return

        # Enter on burst
        if self._consec_up >= self.consec_bars and self._position <= 0:
            self._buy()
        elif self._consec_dn >= self.consec_bars and self._position >= 0:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["ScalpTickMomentum"]
