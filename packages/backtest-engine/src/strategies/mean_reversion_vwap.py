"""VWAP Reversion strategy — Mean Reversion category.

Distinct from VWAPDeviation (which is in strategies.py).
This version uses a rolling VWAP reset each session and adds a
standard-deviation band to filter noise.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.mean_reversion_vwap")


class VWAPReversion(BaseStrategy, _BacktestStrategyMixin):
    """Intraday VWAP mean-reversion strategy.

    Resets VWAP accumulation at session open (09:15 bar).
    Enters long when price is more than `std_mult` standard deviations below VWAP.
    Enters short when price is more than `std_mult` standard deviations above VWAP.
    Exits when price returns to VWAP.

    Args:
        std_mult: Band multiplier in standard deviations (default 2.0).
        band_period: Rolling window for std-dev calculation (default 20).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "VWAPReversion",
        exchange: str = "NSE",
        product: str = "MIS",
        std_mult: float = 2.0,
        band_period: int = 20,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.std_mult = std_mult
        self.band_period = band_period
        self._symbol = symbol
        self._init_history()
        self._cum_tp_vol: float = 0.0
        self._cum_vol: int = 0
        self._cum_tp2_vol: float = 0.0  # For variance: sum(tp^2 * vol)

    def _reset_session(self) -> None:
        self._cum_tp_vol = 0.0
        self._cum_vol = 0
        self._cum_tp2_vol = 0.0

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
        self._cum_tp2_vol += (typical ** 2) * bar.volume

        if self._cum_vol == 0:
            return

        vwap = self._cum_tp_vol / self._cum_vol
        # VWAP standard deviation using online formula
        variance = max(0.0, self._cum_tp2_vol / self._cum_vol - vwap ** 2)
        std = variance ** 0.5

        upper_band = vwap + self.std_mult * std
        lower_band = vwap - self.std_mult * std

        close = bar.close

        if close < lower_band and self._position <= 0:
            self._buy()
        elif close > upper_band and self._position >= 0:
            self._sell()
        # Exit: price returns to VWAP
        elif self._position == 1 and close >= vwap:
            self._sell()
        elif self._position == -1 and close <= vwap:
            self._buy()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
