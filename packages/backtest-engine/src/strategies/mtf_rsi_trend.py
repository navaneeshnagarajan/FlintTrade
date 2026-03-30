"""Multi-Timeframe RSI Trend strategy.

Uses RSI on a higher timeframe to establish trend direction, then enters
on the lower timeframe when RSI confirms momentum alignment.

Higher TF bars are fed externally via bars_htf parameter in on_bar().
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._indicators import rsi
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.mtf_rsi_trend")


class MTFRSITrend(BaseStrategy, _BacktestStrategyMixin):
    """Multi-timeframe RSI trend-following strategy.

    Trend filter: RSI on higher TF must be above htf_bull_level (bullish) or
    below htf_bear_level (bearish) to allow entries.
    Entry: Lower TF RSI crosses out of oversold (buy) or overbought (sell).

    Args:
        ltf_period: RSI period for lower timeframe (default 14).
        htf_period: RSI period for higher timeframe (default 14).
        ltf_oversold: Lower TF buy trigger (default 35).
        ltf_overbought: Lower TF sell trigger (default 65).
        htf_bull_level: Minimum HTF RSI for bullish bias (default 50).
        htf_bear_level: Maximum HTF RSI for bearish bias (default 50).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "MTFRSITrend",
        exchange: str = "NSE",
        product: str = "MIS",
        ltf_period: int = 14,
        htf_period: int = 14,
        ltf_oversold: float = 35.0,
        ltf_overbought: float = 65.0,
        htf_bull_level: float = 50.0,
        htf_bear_level: float = 50.0,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.ltf_period = ltf_period
        self.htf_period = htf_period
        self.ltf_oversold = ltf_oversold
        self.ltf_overbought = ltf_overbought
        self.htf_bull_level = htf_bull_level
        self.htf_bear_level = htf_bear_level
        self._symbol = symbol
        self._init_history()
        self._htf_closes: list[float] = []


    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV, bars_htf: list[OHLCV] | None = None) -> None:
        self._record_bar(bar)

        if bars_htf:
            self._htf_closes = [b.close for b in bars_htf]

        if len(self._closes) < self.ltf_period + 2:
            return

        ltf_rsi = rsi(self._closes, self.ltf_period)

        # Determine HTF bias
        htf_bullish = True
        htf_bearish = True
        if len(self._htf_closes) >= self.htf_period + 2:
            htf_rsi = rsi(self._htf_closes, self.htf_period)
            htf_bullish = htf_rsi[-1] >= self.htf_bull_level
            htf_bearish = htf_rsi[-1] <= self.htf_bear_level

        cross_up = ltf_rsi[-1] > self.ltf_oversold and ltf_rsi[-2] <= self.ltf_oversold
        cross_dn = ltf_rsi[-1] < self.ltf_overbought and ltf_rsi[-2] >= self.ltf_overbought

        if cross_up and htf_bullish:
            self._buy()
        elif cross_dn and htf_bearish:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["MTFRSITrend"]
