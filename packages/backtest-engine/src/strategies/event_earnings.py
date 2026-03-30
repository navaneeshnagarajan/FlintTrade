"""Event-Driven Earnings Straddle strategy.

Pre/post earnings straddle based on IV rank. Enters a long straddle before
an earnings announcement when IV is low (cheap optionality), exits after
the earnings-driven move.

Event dates must be injected via set_event_date() before the session.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.event_earnings")


class EventEarnings(BaseStrategy, _BacktestStrategyMixin):
    """Pre/post earnings straddle based on IV rank.

    Enters a long straddle N bars before the earnings event.
    Exits N bars after the event or when move exceeds the target.

    Args:
        bars_before: Bars before event to enter (default 1).
        bars_after: Maximum bars to hold after event (default 2).
        iv_rank_threshold: IV rank below which to enter (default 40.0).
        iv_lookback: Lookback bars for IV rank proxy (default 30).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "EventEarnings",
        exchange: str = "NFO",
        product: str = "NRML",
        bars_before: int = 1,
        bars_after: int = 2,
        iv_rank_threshold: float = 40.0,
        iv_lookback: int = 30,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.bars_before = bars_before
        self.bars_after = bars_after
        self.iv_rank_threshold = iv_rank_threshold
        self.iv_lookback = iv_lookback
        self._symbol = symbol
        self._init_history()
        self._event_bar_idx: int = -1
        self._bars_held: int = 0


    def set_event_date(self, bar_index: int) -> None:
        """Set the index of the bar on which the event occurs.

        Args:
            bar_index: Absolute bar index of the event bar.
        """
        self._event_bar_idx = bar_index

    def _iv_rank_proxy(self, closes: list[float]) -> float:
        if len(closes) < self.iv_lookback:
            return 50.0
        window = closes[-self.iv_lookback:]
        lo, hi = min(window), max(window)
        if hi == lo:
            return 50.0
        return (closes[-1] - lo) / (hi - lo) * 100

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        idx = len(self._closes) - 1

        # Hold counter management
        if self._position != 0:
            self._bars_held += 1
            if self._bars_held >= self.bars_after:
                if self._position > 0:
                    self._sell()
                else:
                    self._buy()
                    self._flat()
                self._bars_held = 0
            return

        # Entry: N bars before event
        if self._event_bar_idx >= 0 and idx == self._event_bar_idx - self.bars_before:
            iv_rank = self._iv_rank_proxy(self._closes)
            if iv_rank <= self.iv_rank_threshold:
                self._buy()  # long straddle represented as long underlying
                self._bars_held = 0
                logger.info("Earnings straddle entered at idx=%d iv_rank=%.1f", idx, iv_rank)

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["EventEarnings"]
