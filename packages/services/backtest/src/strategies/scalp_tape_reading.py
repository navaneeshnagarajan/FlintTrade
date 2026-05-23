"""Scalp Tape Reading strategy.

Detects order flow imbalance from bid/ask volume data (or approximated
from bar internals when quote data is unavailable).

Buy-side imbalance (more volume on up-ticks) → buy signal.
Sell-side imbalance (more volume on down-ticks) → sell signal.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.scalp_tape_reading")


class ScalpTapeReading(BaseStrategy, _BacktestStrategyMixin):
    """Order flow imbalance scalping.

    Estimates imbalance from bar internals: if close is in the upper half
    of the bar range (closer to high), the bar is "buy-dominant" and vice versa.
    Uses a rolling imbalance score to trigger scalp entries.

    Args:
        lookback: Bars for rolling imbalance score (default 5).
        imbalance_threshold: Score (0–1) above which to enter (default 0.7).
        session_close: Force-exit HH:MM (default "15:15").
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "ScalpTapeReading",
        exchange: str = "NSE",
        product: str = "MIS",
        lookback: int = 5,
        imbalance_threshold: float = 0.7,
        session_close: str = "15:15",
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.lookback = lookback
        self.imbalance_threshold = imbalance_threshold
        self.session_close = session_close
        self._symbol = symbol
        self._init_history()
        self._imbalance_scores: list[float] = []


    def _time_part(self, ts: str) -> str:
        return ts[11:16] if len(ts) > 16 else ""

    def _bar_imbalance(self, bar: OHLCV) -> float:
        """Score 0–1: how buy-dominant is this bar."""
        rng = bar.high - bar.low
        if rng == 0:
            return 0.5
        return (bar.close - bar.low) / rng

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

        score = self._bar_imbalance(bar)
        self._imbalance_scores.append(score)

        if len(self._imbalance_scores) < self.lookback:
            return

        window = self._imbalance_scores[-self.lookback:]
        avg_score = sum(window) / self.lookback

        if avg_score >= self.imbalance_threshold and self._position <= 0:
            self._buy()
        elif avg_score <= (1 - self.imbalance_threshold) and self._position >= 0:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["ScalpTapeReading"]
