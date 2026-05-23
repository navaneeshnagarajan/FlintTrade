"""Multi-Timeframe EMA Breakout strategy.

Daily EMA determines trend direction; intraday bar triggers entry on breakout
above or below the daily EMA level.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import ema
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.mtf_ema_breakout")


class MTFEMABreakout(BaseStrategy, _BacktestStrategyMixin):
    """Daily EMA trend + intraday breakout entry.

    Uses a higher-timeframe EMA (typically daily) to determine the macro trend
    direction. Enters intraday when price breaks out in the trend direction.

    Args:
        htf_period: EMA period for higher timeframe (default 20).
        ltf_period: EMA period for lower timeframe confirmation (default 9).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "MTFEMABreakout",
        exchange: str = "NSE",
        product: str = "MIS",
        htf_period: int = 20,
        ltf_period: int = 9,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.htf_period = htf_period
        self.ltf_period = ltf_period
        self._symbol = symbol
        self._init_history()
        self._htf_closes: list[float] = []
        self._htf_trend: int = 0  # +1 bullish, -1 bearish, 0 neutral


    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV, bars_htf: list[OHLCV] | None = None) -> None:
        self._record_bar(bar)

        if bars_htf and len(bars_htf) >= self.htf_period + 1:
            htf_closes = [b.close for b in bars_htf]
            htf_ema = ema(htf_closes, self.htf_period)
            last_close = htf_closes[-1]
            self._htf_trend = 1 if last_close > htf_ema[-1] else -1

        if len(self._closes) < self.ltf_period + 2:
            return

        ltf_ema = ema(self._closes, self.ltf_period)
        close = self._closes[-1]
        prev_close = self._closes[-2]

        # Breakout above LTF EMA with bullish HTF trend
        if self._htf_trend >= 0 and close > ltf_ema[-1] and prev_close <= ltf_ema[-2]:
            self._buy()
        # Breakdown below LTF EMA with bearish HTF trend
        elif self._htf_trend <= 0 and close < ltf_ema[-1] and prev_close >= ltf_ema[-2]:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["MTFEMABreakout"]
