"""Hammer and Shooting Star candlestick strategy — Pattern category.

Identifies hammer (bullish reversal at lows) and shooting star (bearish reversal
at highs) candles, confirmed by a volume spike relative to the recent average.

Hammer definition (bullish):
    - Small real body (body_ratio: body_size / total_range <= max_body_ratio)
    - Long lower wick  (lower_wick >= wick_mult * body_size)
    - Short upper wick (upper_wick <= body_size)
    - Price at or below SMA (downtrend context)
    - Volume >= volume_mult * avg_volume(vol_period) (confirmation)

Shooting star definition (bearish):
    - Small real body
    - Long upper wick  (upper_wick >= wick_mult * body_size)
    - Short lower wick (lower_wick <= body_size)
    - Price at or above SMA (uptrend context)
    - Volume confirmation
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._indicators import sma
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.pattern_hammer")


class HammerShootingStar(BaseStrategy, _BacktestStrategyMixin):
    """Hammer and Shooting Star pattern with volume confirmation.

    Hammer below SMA with volume spike → BUY.
    Shooting Star above SMA with volume spike → SELL.
    Time-based exit after hold_bars candles.

    Args:
        sma_period: SMA period for trend context (default 20).
        wick_mult: Minimum wick-to-body ratio for the dominant wick
            (default 2.0, i.e. wick is at least 2× the body).
        max_body_ratio: Maximum body-to-range ratio (default 0.35).
            Ensures the body is a small fraction of the candle range.
        vol_period: Volume lookback for average calculation (default 10).
        volume_mult: Volume must be at least this multiple of the
            rolling average (default 1.5).
        hold_bars: Bars to hold before forced exit (default 5).
        symbol: Instrument symbol (default "").
        exchange: Exchange code (default "NSE").
        product: Product type (default "MIS").
    """

    def __init__(
        self,
        name: str = "HammerShootingStar",
        exchange: str = "NSE",
        product: str = "MIS",
        sma_period: int = 20,
        wick_mult: float = 2.0,
        max_body_ratio: float = 0.35,
        vol_period: int = 10,
        volume_mult: float = 1.5,
        hold_bars: int = 5,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.sma_period = sma_period
        self.wick_mult = wick_mult
        self.max_body_ratio = max_body_ratio
        self.vol_period = vol_period
        self.volume_mult = volume_mult
        self.hold_bars = hold_bars
        self._symbol = symbol
        self._init_history()
        self._bars_in_trade: int = 0

    def on_tick(self, quote: Quote) -> None:
        """Not used — bar-close strategy."""

    def on_bar(self, bar: OHLCV) -> None:
        """Process a completed bar and detect hammer/shooting-star patterns.

        Args:
            bar: The just-closed OHLCV bar.
        """
        if not self.is_active:
            return
        self._record_bar(bar)
        min_bars = max(self.sma_period, self.vol_period) + 1
        if len(self._closes) < min_bars:
            return

        sma_vals = sma(self._closes, self.sma_period)
        cur_ma = sma_vals[-1]
        if cur_ma == 0:
            return

        o = self._opens[-1]
        h = self._highs[-1]
        lo = self._lows[-1]
        c = self._closes[-1]

        total_range = h - lo
        if total_range == 0:
            return

        body_size = abs(c - o)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - lo

        body_ratio = body_size / total_range
        vol = self._volumes[-1]
        avg_vol = sum(self._volumes[-self.vol_period - 1: -1]) / self.vol_period
        vol_ok = avg_vol > 0 and vol >= self.volume_mult * avg_vol

        # Time-based exit
        if self._position != 0:
            self._bars_in_trade += 1
            if self._bars_in_trade >= self.hold_bars:
                if self._position == 1:
                    self._sell()
                elif self._position == -1:
                    self._buy()
                self._flat()
                self._bars_in_trade = 0
                return

        if self._position == 0:
            # Hammer: long lower wick, small body, price below SMA
            is_hammer = (
                body_ratio <= self.max_body_ratio
                and lower_wick >= self.wick_mult * max(body_size, 0.001)
                and upper_wick <= max(body_size, 0.001)
                and c <= cur_ma
                and vol_ok
            )
            # Shooting star: long upper wick, small body, price above SMA
            is_shooting_star = (
                body_ratio <= self.max_body_ratio
                and upper_wick >= self.wick_mult * max(body_size, 0.001)
                and lower_wick <= max(body_size, 0.001)
                and c >= cur_ma
                and vol_ok
            )

            if is_hammer:
                logger.debug(
                    "Hammer | body=%.4f lower_wick=%.4f vol=%d | %s",
                    body_size,
                    lower_wick,
                    vol,
                    self._symbol,
                )
                self._buy()
                self._bars_in_trade = 0
            elif is_shooting_star:
                logger.debug(
                    "ShootingStar | body=%.4f upper_wick=%.4f vol=%d | %s",
                    body_size,
                    upper_wick,
                    vol,
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
