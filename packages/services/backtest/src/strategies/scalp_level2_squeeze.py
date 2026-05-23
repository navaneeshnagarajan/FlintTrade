"""Scalp Level 2 Bid-Ask Squeeze strategy.

Detects compression of the bid/ask spread (squeeze) which often precedes
a sharp directional move. When the spread compresses and then expands rapidly
in one direction, enter in that direction.

In backtest mode (no live L2 data), squeeze is approximated by bar range
compression followed by range expansion.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import atr
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.scalp_level2_squeeze")


class ScalpLevel2Squeeze(BaseStrategy, _BacktestStrategyMixin):
    """Level 2 bid/ask compression detection for scalping.

    Approximates L2 squeeze via bar range compression:
    - Squeeze: current bar range < squeeze_factor * ATR (compressed).
    - Release: next bar range > release_factor * ATR.
    - Direction determined by which side the release breaks toward.

    Args:
        atr_period: ATR period for range normalization (default 14).
        squeeze_factor: Bar range as % of ATR to call a squeeze (default 0.5).
        release_factor: Bar range as % of ATR to call a release (default 1.5).
        session_close: Force-exit HH:MM (default "15:15").
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "ScalpLevel2Squeeze",
        exchange: str = "NSE",
        product: str = "MIS",
        atr_period: int = 14,
        squeeze_factor: float = 0.5,
        release_factor: float = 1.5,
        session_close: str = "15:15",
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.atr_period = atr_period
        self.squeeze_factor = squeeze_factor
        self.release_factor = release_factor
        self.session_close = session_close
        self._symbol = symbol
        self._init_history()
        self._squeezed: bool = False
        self._squeeze_close: float = 0.0


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

        if len(self._closes) < self.atr_period + 2:
            return

        atr_vals = atr(self._highs, self._lows, self._closes, self.atr_period)
        cur_atr = atr_vals[-1]
        if cur_atr == 0:
            return

        bar_range = bar.high - bar.low
        range_ratio = bar_range / cur_atr

        if range_ratio < self.squeeze_factor:
            # Squeeze detected
            self._squeezed = True
            self._squeeze_close = bar.close
            return

        if self._squeezed and range_ratio >= self.release_factor:
            # Release: direction from squeeze_close vs bar close
            if bar.close > self._squeeze_close and self._position <= 0:
                self._buy()
            elif bar.close < self._squeeze_close and self._position >= 0:
                self._sell()
            self._squeezed = False
            self._squeeze_close = 0.0

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["ScalpLevel2Squeeze"]
