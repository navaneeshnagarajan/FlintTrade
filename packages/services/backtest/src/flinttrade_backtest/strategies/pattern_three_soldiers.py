"""Three White Soldiers / Three Black Crows strategy — Pattern category.

Three White Soldiers — 3 consecutive large bullish candles:
    - Each candle opens within the prior candle's real body.
    - Each candle closes near its high (small upper wick).
    - Each close is higher than the previous close.
    - Combined with price near a low (below SMA) for reversal context.

Three Black Crows — mirror image (3 consecutive large bearish candles):
    - Each candle opens within the prior candle's real body.
    - Each candle closes near its low (small lower wick).
    - Each close is lower than the previous close.
    - Combined with price near a high (above SMA) for reversal context.

Exit is time-based after hold_bars candles.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import sma
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.pattern_three_soldiers")


class ThreeWhiteSoldiers(BaseStrategy, _BacktestStrategyMixin):
    """Three White Soldiers and Three Black Crows strategy.

    Both patterns trade from the same strategy class:
    - Three White Soldiers → BUY (bullish reversal)
    - Three Black Crows    → SELL (bearish reversal)

    Args:
        sma_period: SMA period for trend context (default 20).
        min_body_pct: Minimum body/range for each candle (default 0.55).
            Ensures candles are genuinely large/strong.
        max_wick_pct: Maximum opposite-wick/range ratio (default 0.20).
            Three White Soldiers: upper wick; Three Black Crows: lower wick.
        hold_bars: Bars to hold before forced exit (default 8).
        symbol: Instrument symbol (default "").
        exchange: Exchange code (default "NSE").
        product: Product type (default "MIS").
    """

    def __init__(
        self,
        name: str = "ThreeWhiteSoldiers",
        exchange: str = "NSE",
        product: str = "MIS",
        sma_period: int = 20,
        min_body_pct: float = 0.55,
        max_wick_pct: float = 0.20,
        hold_bars: int = 8,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.sma_period = sma_period
        self.min_body_pct = min_body_pct
        self.max_wick_pct = max_wick_pct
        self.hold_bars = hold_bars
        self._symbol = symbol
        self._init_history()
        self._bars_in_trade: int = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _metrics(o: float, c: float, h: float, lo: float) -> tuple[float, float, float]:
        """Return (body_ratio, upper_wick_ratio, lower_wick_ratio)."""
        r = h - lo
        if r == 0:
            return 0.0, 0.0, 0.0
        body = abs(c - o) / r
        upper_wick = (h - max(o, c)) / r
        lower_wick = (min(o, c) - lo) / r
        return body, upper_wick, lower_wick

    def on_tick(self, quote: Quote) -> None:
        """Not used — bar-close strategy."""

    def on_bar(self, bar: OHLCV) -> None:
        """Process a completed bar and detect 3-soldier / 3-crow patterns.

        Args:
            bar: The just-closed OHLCV bar.
        """
        if not self.is_active:
            return
        self._record_bar(bar)

        min_bars = max(self.sma_period, 3) + 1
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

        # Three most recent bars
        o1, h1, lo1, c1 = (
            self._opens[-3], self._highs[-3], self._lows[-3], self._closes[-3],
        )
        o2, h2, lo2, c2 = (
            self._opens[-2], self._highs[-2], self._lows[-2], self._closes[-2],
        )
        o3, h3, lo3, c3 = (
            self._opens[-1], self._highs[-1], self._lows[-1], self._closes[-1],
        )

        b1, uw1, lw1 = self._metrics(o1, c1, h1, lo1)
        b2, uw2, lw2 = self._metrics(o2, c2, h2, lo2)
        b3, uw3, lw3 = self._metrics(o3, c3, h3, lo3)

        sma_vals = sma(self._closes, self.sma_period)
        cur_ma = sma_vals[-1]

        # --- Three White Soldiers ---
        # Each candle: bullish, large body, small upper wick
        # Each opens within prior body, each close higher
        soldiers = (
            c1 > o1 and b1 >= self.min_body_pct and uw1 <= self.max_wick_pct
            and c2 > o2 and b2 >= self.min_body_pct and uw2 <= self.max_wick_pct
            and c3 > o3 and b3 >= self.min_body_pct and uw3 <= self.max_wick_pct
            and o1 <= o2 <= c1  # c2 opens within c1's body
            and o2 <= o3 <= c2  # c3 opens within c2's body
            and c2 > c1 and c3 > c2  # progressive higher closes
            and (cur_ma == 0 or c3 <= cur_ma)  # in downtrend — reversal signal
        )

        # --- Three Black Crows ---
        # Each candle: bearish, large body, small lower wick
        # Each opens within prior body, each close lower
        crows = (
            c1 < o1 and b1 >= self.min_body_pct and lw1 <= self.max_wick_pct
            and c2 < o2 and b2 >= self.min_body_pct and lw2 <= self.max_wick_pct
            and c3 < o3 and b3 >= self.min_body_pct and lw3 <= self.max_wick_pct
            and c1 <= o2 <= o1  # c2 opens within c1's body (bearish)
            and c2 <= o3 <= o2  # c3 opens within c2's body
            and c2 < c1 and c3 < c2  # progressive lower closes
            and (cur_ma == 0 or c3 >= cur_ma)  # in uptrend — reversal signal
        )

        if soldiers:
            logger.debug(
                "Three White Soldiers | c1=%.2f c2=%.2f c3=%.2f | %s",
                c1, c2, c3, self._symbol,
            )
            self._buy()
            self._bars_in_trade = 0
        elif crows:
            logger.debug(
                "Three Black Crows | c1=%.2f c2=%.2f c3=%.2f | %s",
                c1, c2, c3, self._symbol,
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
