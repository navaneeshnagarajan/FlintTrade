"""Event-Driven RBI Monetary Policy Date Positioning strategy (India-specific).

Positions the portfolio ahead of RBI MPC (Monetary Policy Committee) meetings.
Policy dates are injected externally. Strategy takes a neutral straddle position
before the event and exits after the announcement volatility spike.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import atr
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.event_rbi_policy")


class EventRBIPolicy(BaseStrategy, _BacktestStrategyMixin):
    """RBI monetary policy date positioning.

    Pre-policy: Enter a directional position based on rate-expectation bias.
    Post-policy: Exit after the announcement (volatility capture).

    Rate bias is injected via set_rate_bias() before the event.
    +1 = rate cut expected (bullish bonds/equities)
    -1 = rate hike expected (bearish)
    0  = no change / neutral (sell straddle / gamma)

    Args:
        bars_before: Bars before event to enter (default 2).
        bars_after: Bars after event to hold (default 3).
        atr_period: ATR for stop sizing (default 14).
        atr_stop_mult: Stop distance as ATR multiple (default 2.0).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "EventRBIPolicy",
        exchange: str = "NSE",
        product: str = "MIS",
        bars_before: int = 2,
        bars_after: int = 3,
        atr_period: int = 14,
        atr_stop_mult: float = 2.0,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.bars_before = bars_before
        self.bars_after = bars_after
        self.atr_period = atr_period
        self.atr_stop_mult = atr_stop_mult
        self._symbol = symbol
        self._init_history()
        self._event_bar_idx: int = -1
        self._rate_bias: int = 0
        self._bars_held: int = 0
        self._entry_price: float = 0.0
        self._stop: float = 0.0


    def set_event(self, bar_index: int, rate_bias: int = 0) -> None:
        """Set RBI policy event bar index and rate expectation bias.

        Args:
            bar_index: Bar index of the policy announcement.
            rate_bias: +1 cut, -1 hike, 0 neutral.
        """
        self._event_bar_idx = bar_index
        self._rate_bias = rate_bias

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        idx = len(self._closes) - 1

        if self._position != 0:
            self._bars_held += 1
            # Stop check
            if self._stop > 0:
                if self._position == 1 and bar.close <= self._stop:
                    self._sell()
                    self._bars_held = 0
                    self._entry_price = 0.0
                    return
                if self._position == -1 and bar.close >= self._stop:
                    self._buy()
                    self._flat()
                    self._bars_held = 0
                    self._entry_price = 0.0
                    return
            if self._bars_held >= self.bars_after:
                if self._position > 0:
                    self._sell()
                else:
                    self._buy()
                    self._flat()
                self._bars_held = 0
                self._entry_price = 0.0
            return

        if self._event_bar_idx < 0:
            return

        bars_to_event = self._event_bar_idx - idx
        if bars_to_event == self.bars_before:
            if len(self._closes) >= self.atr_period + 1:
                atr_vals = atr(self._highs, self._lows, self._closes, self.atr_period)
                stop_dist = self.atr_stop_mult * atr_vals[-1]
            else:
                stop_dist = bar.close * 0.01

            if self._rate_bias == 1:
                self._buy()
                self._stop = bar.close - stop_dist
            elif self._rate_bias == -1:
                self._sell()
                self._stop = bar.close + stop_dist
            # neutral: skip (sell-straddle modelled separately)
            self._entry_price = bar.close
            self._bars_held = 0

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["EventRBIPolicy"]
