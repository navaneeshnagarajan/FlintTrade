"""Options Calendar Spread strategy.

Near-month vs far-month calendar: sell near-month option, buy same-strike
far-month option. Profits from near-month time decay faster than far-month.
Modelled via synthetic near-far premium differential instrument.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.options_calendar_spread")


class OptionsCalendarSpread(BaseStrategy, _BacktestStrategyMixin):
    """Near-month vs far-month calendar spread.

    Enters when IV rank is elevated (proxy: price at recent extremes).
    Exits at a target premium decay or at stop loss.

    Args:
        entry_time: Entry HH:MM (default "09:45").
        exit_time: Force-exit HH:MM (default "15:10").
        iv_lookback: Bars to estimate implied-vol proxy (default 20).
        iv_rank_threshold: IV rank percentile threshold to enter (default 50.0).
        target_pct: Target premium decay % (default 40.0).
        stop_pct: Max loss % vs entry premium (default 50.0).
        symbol: Synthetic instrument symbol.
    """

    def __init__(
        self,
        name: str = "OptionsCalendarSpread",
        exchange: str = "NFO",
        product: str = "NRML",
        entry_time: str = "09:45",
        exit_time: str = "15:10",
        iv_lookback: int = 20,
        iv_rank_threshold: float = 50.0,
        target_pct: float = 40.0,
        stop_pct: float = 50.0,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.entry_time = entry_time
        self.exit_time = exit_time
        self.iv_lookback = iv_lookback
        self.iv_rank_threshold = iv_rank_threshold
        self.target_pct = target_pct
        self.stop_pct = stop_pct
        self._symbol = symbol
        self._init_history()
        self._entry_premium: float = 0.0


    def _iv_rank_proxy(self, closes: list[float], lookback: int) -> float:
        """IV rank proxy via price range percentile (0–100)."""
        if len(closes) < lookback:
            return 50.0
        window = closes[-lookback:]
        lo, hi = min(window), max(window)
        if hi == lo:
            return 50.0
        return (closes[-1] - lo) / (hi - lo) * 100

    def on_tick(self, quote: Quote) -> None:
        pass

    def _time_part(self, ts: str) -> str:
        return ts[11:16] if len(ts) > 16 else ""

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        tp = self._time_part(bar.timestamp)

        if tp >= self.exit_time and self._position != 0:
            if self._position > 0:
                self._sell()
            else:
                self._buy()
                self._flat()
            self._entry_premium = 0.0
            return

        if tp == self.entry_time and self._position == 0:
            iv_rank = self._iv_rank_proxy(self._closes, self.iv_lookback)
            if iv_rank >= self.iv_rank_threshold:
                self._sell()  # sell near-month, buy far-month (net credit on decay)
                self._entry_premium = bar.close
            return

        if self._position == -1 and self._entry_premium > 0:
            pnl_pct = (self._entry_premium - bar.close) / self._entry_premium * 100
            if pnl_pct >= self.target_pct:
                self._buy()
                self._flat()
                self._entry_premium = 0.0
            elif -pnl_pct >= self.stop_pct:
                self._buy()
                self._flat()
                self._entry_premium = 0.0

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["OptionsCalendarSpread"]
