"""Pivot Point Mean Reversion strategy — Mean Reversion category.

Classic floor-trader pivot points computed from the previous bar's H/L/C:

    P  = (H + L + C) / 3
    R1 = 2 * P - L
    S1 = 2 * P - H
    R2 = P + (H - L)
    S2 = P - (H - L)

Trading rules (using the most recently completed pivot bar, e.g. daily pivots
derived from intraday data or bar-by-bar rolling pivots):
    BUY  when close touches S1 and then moves back above S1
         (confirmation: current close > S1 AND previous close <= S1).
    SELL when close touches R1 and then moves back below R1
         (confirmation: current close < R1 AND previous close >= R1).
    Exit long at R1 or P (whichever is crossed first).
    Exit short at S1 or P.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import pivot_points
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.mean_reversion_pivot_point")


class PivotPointReversion(BaseStrategy, _BacktestStrategyMixin):
    """Floor-trader pivot point mean-reversion strategy.

    Buys bounces from S1 and sells rejection from R1. Exits at the pivot (P)
    or when the opposite level is hit.

    Args:
        pivot_lookback: Number of bars to use when computing the pivot's H/L/C.
            Use 1 for a simple prior-bar pivot (default 1).
        symbol: Instrument symbol (default "").
        exchange: Exchange code (default "NSE").
        product: Product type (default "MIS").
    """

    def __init__(
        self,
        name: str = "PivotPointReversion",
        exchange: str = "NSE",
        product: str = "MIS",
        pivot_lookback: int = 1,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.pivot_lookback = pivot_lookback
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        """Not used — bar-close strategy."""

    def on_bar(self, bar: OHLCV) -> None:
        """Process a completed bar and trade pivot-level bounces.

        Args:
            bar: The just-closed OHLCV bar.
        """
        if not self.is_active:
            return
        self._record_bar(bar)
        # Need at least pivot_lookback + 2 bars (pivot window + current + previous)
        if len(self._closes) < self.pivot_lookback + 2:
            return

        # Derive pivot from the bars immediately preceding the current bar
        lb = self.pivot_lookback
        pivot_highs = self._highs[-(lb + 1):-1]
        pivot_lows = self._lows[-(lb + 1):-1]
        pivot_closes = self._closes[-(lb + 1):-1]

        p, r1, s1, _r2, _s2 = pivot_points(pivot_highs, pivot_lows, pivot_closes)

        close = self._closes[-1]
        prev_close = self._closes[-2]

        # Exit conditions (checked before entry to allow re-entry on same bar)
        if self._position == 1:
            # Long exit: close at R1 or falls back through pivot
            if close >= r1 or close < p:
                logger.debug(
                    "Pivot long-exit | close=%.2f P=%.2f R1=%.2f | %s",
                    close,
                    p,
                    r1,
                    self._symbol,
                )
                self._sell()
                self._flat()
                return
        elif self._position == -1:
            # Short exit: close at S1 or rises back through pivot
            if close <= s1 or close > p:
                logger.debug(
                    "Pivot short-exit | close=%.2f P=%.2f S1=%.2f | %s",
                    close,
                    p,
                    s1,
                    self._symbol,
                )
                self._buy()
                self._flat()
                return

        # Entry conditions (flat position only)
        if self._position == 0:
            # BUY: price bounces off S1 (crosses back above S1)
            if prev_close <= s1 < close:
                logger.debug(
                    "Pivot S1-bounce BUY | close=%.2f S1=%.2f P=%.2f | %s",
                    close,
                    s1,
                    p,
                    self._symbol,
                )
                self._buy()
            # SELL: price rejects from R1 (crosses back below R1)
            elif prev_close >= r1 > close:
                logger.debug(
                    "Pivot R1-reject SELL | close=%.2f R1=%.2f P=%.2f | %s",
                    close,
                    r1,
                    p,
                    self._symbol,
                )
                self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        """Not used — strategy generates its own signals."""

    def generate_orders(self) -> list[Order]:
        """Return and clear all pending orders.

        Returns:
            List of Order objects to submit to the engine.
        """
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
