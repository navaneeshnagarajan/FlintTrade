"""VWAP Cross strategy — Volume category.

Simple price/VWAP crossover for intraday momentum.
Distinct from VWAPDeviation (which uses bands) and VWAPReversion (which reverts).
This strategy trades the crossover directly as a trend signal.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.volume_vwap_cross")


class VWAPCross(BaseStrategy, _BacktestStrategyMixin):
    """VWAP crossover momentum strategy.

    Buy: close crosses above VWAP (bullish momentum).
    Sell: close crosses below VWAP (bearish momentum).
    VWAP resets each session at 09:15.

    Requires volume data; without volume, degenerate to simple TP average.

    Args:
        min_distance_pct: Minimum distance from VWAP to trigger entry (default 0.0).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "VWAPCross",
        exchange: str = "NSE",
        product: str = "MIS",
        min_distance_pct: float = 0.0,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.min_distance_pct = min_distance_pct
        self._symbol = symbol
        self._init_history()
        self._cum_tp_vol: float = 0.0
        self._cum_vol: int = 0

    def _reset_session(self) -> None:
        self._cum_tp_vol = 0.0
        self._cum_vol = 0

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        ts = bar.timestamp
        time_part = ts[11:16] if len(ts) > 16 else ""
        if time_part == "09:15":
            self._reset_session()

        typical = (bar.high + bar.low + bar.close) / 3
        self._cum_tp_vol += typical * bar.volume
        self._cum_vol += bar.volume

        if self._cum_vol == 0 or len(self._closes) < 2:
            return

        vwap = self._cum_tp_vol / self._cum_vol
        close = self._closes[-1]
        prev_close = self._closes[-2]

        # Apply minimum distance filter
        dist = abs(close - vwap) / vwap * 100 if vwap > 0 else 0.0
        if dist < self.min_distance_pct:
            return

        # Cross above VWAP
        if close > vwap and prev_close <= vwap:
            self._buy()
        # Cross below VWAP
        elif close < vwap and prev_close >= vwap:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
