"""Multi-Timeframe Supertrend Confluence strategy.

Enters only when Supertrend aligns across three timeframes (all bullish or all bearish).
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import supertrend
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.mtf_supertrend_confluence")


class MTFSupertrendConfluence(BaseStrategy, _BacktestStrategyMixin):
    """Supertrend alignment across 3 timeframes.

    Primary (LTF) bars drive on_bar(). Two sets of higher TF bars
    can be passed as bars_htf1 and bars_htf2. Entry fires when all
    three Supertrend signals agree.

    Args:
        period: ATR period for Supertrend (default 10).
        multiplier: ATR multiplier (default 3.0).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "MTFSupertrendConfluence",
        exchange: str = "NSE",
        product: str = "MIS",
        period: int = 10,
        multiplier: float = 3.0,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.period = period
        self.multiplier = multiplier
        self._symbol = symbol
        self._init_history()
        self._htf1_uptrend: bool | None = None
        self._htf2_uptrend: bool | None = None


    def on_tick(self, quote: Quote) -> None:
        pass

    def _htf_trend(self, bars: list[OHLCV]) -> bool | None:
        if len(bars) < self.period + 2:
            return None
        h = [b.high for b in bars]
        lo = [b.low for b in bars]
        c = [b.close for b in bars]
        _, uptrend = supertrend(h, lo, c, self.period, self.multiplier)
        return uptrend[-1]

    def on_bar(
        self,
        bar: OHLCV,
        bars_htf1: list[OHLCV] | None = None,
        bars_htf2: list[OHLCV] | None = None,
    ) -> None:
        self._record_bar(bar)

        if bars_htf1:
            self._htf1_uptrend = self._htf_trend(bars_htf1)
        if bars_htf2:
            self._htf2_uptrend = self._htf_trend(bars_htf2)

        if len(self._closes) < self.period + 2:
            return

        _, ltf_uptrend = supertrend(
            self._highs, self._lows, self._closes, self.period, self.multiplier
        )
        ltf_up = ltf_uptrend[-1]
        ltf_prev = ltf_uptrend[-2]

        # Determine confluence: all available TFs must agree
        htf1 = self._htf1_uptrend if self._htf1_uptrend is not None else ltf_up
        htf2 = self._htf2_uptrend if self._htf2_uptrend is not None else ltf_up

        all_bullish = ltf_up and htf1 and htf2
        all_bearish = not ltf_up and not htf1 and not htf2

        just_turned_bull = ltf_up and not ltf_prev
        just_turned_bear = not ltf_up and ltf_prev

        if just_turned_bull and all_bullish:
            self._buy()
        elif just_turned_bear and all_bearish:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["MTFSupertrendConfluence"]
