"""Evening Star candlestick strategy — Pattern category.

The Evening Star is a 3-candle bearish reversal pattern (mirror of Morning Star):
    Bar -2 (first):   Large bullish candle  (close > open, body > body_min_pct of range)
    Bar -1 (middle):  Small body star       (|close - open| <= star_body_max * range)
                      — the star gaps up from bar -2 (close > bar -2 close)
    Bar  0 (current): Large bearish candle  (close < open, body > body_min_pct of range)
                      — closes below the midpoint of bar -2's body (deep penetration)

An optional SMA trend filter ensures we only take the pattern in an uptrend
(price above SMA), increasing probability of a genuine reversal.

Exit is time-based after hold_bars candles.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import sma
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.pattern_evening_star")


class EveningStar(BaseStrategy, _BacktestStrategyMixin):
    """Evening Star 3-candle bearish reversal strategy.

    Entry: SELL when a complete Evening Star pattern is detected.
    Exit: Time-based after hold_bars bars.

    Args:
        sma_period: SMA period for uptrend context filter (default 20).
            Set to 0 to disable the trend filter.
        body_min_pct: Minimum body/range ratio for first and third candle
            to qualify as "large" candles (default 0.60).
        star_body_max: Maximum body/range ratio for the middle star candle
            (default 0.30).
        penetration: Minimum fraction the third candle must close into the
            first candle's body (default 0.50 — halfway).
        hold_bars: Bars to hold before forced exit (default 6).
        symbol: Instrument symbol (default "").
        exchange: Exchange code (default "NSE").
        product: Product type (default "MIS").
    """

    def __init__(
        self,
        name: str = "EveningStar",
        exchange: str = "NSE",
        product: str = "MIS",
        sma_period: int = 20,
        body_min_pct: float = 0.60,
        star_body_max: float = 0.30,
        penetration: float = 0.50,
        hold_bars: int = 6,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.sma_period = sma_period
        self.body_min_pct = body_min_pct
        self.star_body_max = star_body_max
        self.penetration = penetration
        self.hold_bars = hold_bars
        self._symbol = symbol
        self._init_history()
        self._bars_in_trade: int = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _body_ratio(o: float, c: float, h: float, lo: float) -> float:
        """Return |close - open| / (high - low), 0.0 if range is zero."""
        r = h - lo
        return abs(c - o) / r if r > 0 else 0.0

    def on_tick(self, quote: Quote) -> None:
        """Not used — bar-close strategy."""

    def on_bar(self, bar: OHLCV) -> None:
        """Process a completed bar and detect Evening Star patterns.

        Args:
            bar: The just-closed OHLCV bar.
        """
        if not self.is_active:
            return
        self._record_bar(bar)

        min_bars = max(self.sma_period, 3) + 1 if self.sma_period > 0 else 4
        if len(self._closes) < min_bars:
            return

        # Time-based exit
        if self._position != 0:
            self._bars_in_trade += 1
            if self._bars_in_trade >= self.hold_bars:
                logger.debug(
                    "Time-exit | bars=%d pos=%d | %s",
                    self._bars_in_trade,
                    self._position,
                    self._symbol,
                )
                if self._position == 1:
                    self._sell()
                elif self._position == -1:
                    self._buy()
                self._flat()
                self._bars_in_trade = 0
            return

        # Extract the 3 most recent candles
        o1, h1, lo1, c1 = (
            self._opens[-3], self._highs[-3], self._lows[-3], self._closes[-3],
        )
        o2, h2, lo2, c2 = (
            self._opens[-2], self._highs[-2], self._lows[-2], self._closes[-2],
        )
        o3, h3, lo3, c3 = (
            self._opens[-1], self._highs[-1], self._lows[-1], self._closes[-1],
        )

        # --- Candle 1: large bullish ---
        br1 = self._body_ratio(o1, c1, h1, lo1)
        c1_bullish = c1 > o1 and br1 >= self.body_min_pct

        # --- Candle 2: small star body ---
        br2 = self._body_ratio(o2, c2, h2, lo2)
        # Star must gap up: its low is at or above candle 1's close
        c2_star = br2 <= self.star_body_max and min(o2, c2) >= c1

        # --- Candle 3: large bearish, deep penetration into candle 1 ---
        br3 = self._body_ratio(o3, c3, h3, lo3)
        midpoint_c1 = o1 + (c1 - o1) * self.penetration  # midpoint of c1's body
        c3_bearish = c3 < o3 and br3 >= self.body_min_pct and c3 <= midpoint_c1

        # Optional trend filter: pattern should occur in an uptrend
        trend_ok = True
        if self.sma_period > 0:
            sma_vals = sma(self._closes, self.sma_period)
            trend_ok = c3 >= sma_vals[-1] or sma_vals[-1] == 0

        if c1_bullish and c2_star and c3_bearish and trend_ok:
            logger.debug(
                "Evening Star | c1_close=%.2f c2_body=%.4f c3_close=%.2f | %s",
                c1,
                br2,
                c3,
                self._symbol,
            )
            self._sell()
            self._bars_in_trade = 0

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
