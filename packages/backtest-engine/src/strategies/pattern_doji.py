"""Doji Reversal candlestick strategy — Pattern category.

A Doji forms when open ≈ close (small real body relative to the candle's
total range). Combined with a trend filter it signals potential reversals.

Doji definition:
    body_ratio = |close - open| / (high - low)  <=  body_threshold   (default 0.10)

Trend filter (SMA):
    - Price below SMA → prior downtrend → bullish Doji → BUY
    - Price above SMA → prior uptrend  → bearish Doji → SELL

Exit is time-based: after hold_bars candles the position is closed.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._indicators import sma
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.pattern_doji")


class DojiReversal(BaseStrategy, _BacktestStrategyMixin):
    """Doji candlestick reversal with SMA trend filter.

    Bullish Doji below SMA → BUY.
    Bearish Doji above SMA → SELL.
    Time-based exit after ``hold_bars`` candles.

    Args:
        sma_period: Trend-context SMA period (default 20).
        body_threshold: Maximum body/range ratio to qualify as a Doji
            (default 0.10 — body must be < 10% of the candle's range).
        min_range_pct: Minimum candle range as a fraction of close price
            to avoid signals on flat/doji-like bars with zero range
            (default 0.001, i.e. 0.1% of close).
        hold_bars: Exit after this many bars if no prior exit (default 5).
        symbol: Instrument symbol (default "").
        exchange: Exchange code (default "NSE").
        product: Product type (default "MIS").
    """

    def __init__(
        self,
        name: str = "DojiReversal",
        exchange: str = "NSE",
        product: str = "MIS",
        sma_period: int = 20,
        body_threshold: float = 0.10,
        min_range_pct: float = 0.001,
        hold_bars: int = 5,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.sma_period = sma_period
        self.body_threshold = body_threshold
        self.min_range_pct = min_range_pct
        self.hold_bars = hold_bars
        self._symbol = symbol
        self._init_history()
        self._bars_in_trade: int = 0

    def on_tick(self, quote: Quote) -> None:
        """Not used — bar-close strategy."""

    def on_bar(self, bar: OHLCV) -> None:
        """Process a completed bar and detect Doji reversal signals.

        Args:
            bar: The just-closed OHLCV bar.
        """
        if not self.is_active:
            return
        self._record_bar(bar)
        if len(self._closes) < self.sma_period + 1:
            return

        sma_vals = sma(self._closes, self.sma_period)
        cur_ma = sma_vals[-1]
        if cur_ma == 0:
            return

        o = self._opens[-1]
        h = self._highs[-1]
        lo = self._lows[-1]
        c = self._closes[-1]

        candle_range = h - lo
        # Skip doji-on-flat-bar (range too small to be meaningful)
        if candle_range < self.min_range_pct * max(c, 0.01):
            return

        body_ratio = abs(c - o) / candle_range

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

        is_doji = body_ratio <= self.body_threshold

        if is_doji and self._position == 0:
            if c < cur_ma:
                # Doji in downtrend → bullish reversal
                logger.debug(
                    "Bullish Doji | body_ratio=%.4f close=%.2f sma=%.2f | %s",
                    body_ratio,
                    c,
                    cur_ma,
                    self._symbol,
                )
                self._buy()
                self._bars_in_trade = 0
            elif c > cur_ma:
                # Doji in uptrend → bearish reversal
                logger.debug(
                    "Bearish Doji | body_ratio=%.4f close=%.2f sma=%.2f | %s",
                    body_ratio,
                    c,
                    cur_ma,
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
