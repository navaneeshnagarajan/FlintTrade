"""Volatility-based strategies — adapted from AlgoTrading repo (0036–0045).

Strategies:
    ATRBreakoutStrategy            — ATR expansion + price vs SMA direction (0036_ATR_Expansion)
    ATRRangeStrategy               — Price moves >= ATR over N bars (0044_ATR_Range)
    ChoppinessBreakoutStrategy     — Choppiness Index below threshold indicates trend (0045)
    VolatilityContractionStrategy  — Bollinger Band width expansion direction (0038_BB_Width)

All strategies extend BaseBacktestStrategy and emit signals via
``enter_long`` / ``enter_short`` / ``exit_position``.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

try:
    # Relative first: these strategy modules are also loaded standalone by file
    # path, where __package__ is unset and the relative form raises. The absolute
    # form is the except-branch fallback below, so rewriting this to absolute
    # would make both branches identical and kill the fallback.
    from ..base_strategy import BaseBacktestStrategy  # noqa: TID252
except ImportError:
    from flinttrade_backtest.base_strategy import BaseBacktestStrategy  # type: ignore[no-redef]

logger = logging.getLogger("flinttrade.backtest.strategies.volatility")

__all__ = [
    "ATRBreakoutStrategy",
    "ATRRangeStrategy",
    "ChoppinessBreakoutStrategy",
    "VolatilityContractionStrategy",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _atr_np(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> float:
    """Compute current ATR using Wilder smoothing.

    Args:
        highs: High price series.
        lows: Low price series.
        closes: Close price series.
        period: ATR period.

    Returns:
        Current ATR value.
    """
    n = len(closes)
    if n < 2:
        return 0.0
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    if n < period:
        return float(np.mean(tr))
    atr = float(np.mean(tr[:period]))
    for i in range(period, n):
        atr = (atr * (period - 1) + tr[i]) / period
    return atr


def _choppiness(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int,
) -> float:
    """Compute Choppiness Index for the most recent period bars.

    The Choppiness Index ranges from 100/log10(period) (trending)
    to 100 (choppy/ranging). Values below ~38.2 indicate strong trends;
    values above ~61.8 indicate choppy markets.

    Args:
        highs: High prices.
        lows: Low prices.
        closes: Close prices.
        period: Lookback period.

    Returns:
        Choppiness Index value.
    """
    n = len(closes)
    if n < period + 1:
        return 100.0
    h_slice = highs[-period:]
    l_slice = lows[-period:]
    c_slice = closes[-period - 1:]

    atr_sum = 0.0
    for i in range(1, period + 1):
        tr = max(
            h_slice[i - 1] - l_slice[i - 1],
            abs(h_slice[i - 1] - c_slice[i - 1]),
            abs(l_slice[i - 1] - c_slice[i - 1]),
        )
        atr_sum += tr

    high_n = max(h_slice)
    low_n = min(l_slice)
    price_range = high_n - low_n
    if price_range == 0 or atr_sum == 0:
        return 100.0

    return 100.0 * math.log10(atr_sum / price_range) / math.log10(period)


# ---------------------------------------------------------------------------
# ATRBreakoutStrategy
# ---------------------------------------------------------------------------


class ATRBreakoutStrategy(BaseBacktestStrategy):
    """ATR expansion breakout strategy.

    Description:
        Detects volatility expansion when the current ATR is significantly
        higher than the previous ATR (ratio >= expansion_ratio). When
        volatility is expanding, enters in the direction that price is
        moving relative to a SMA. Exits when ATR contracts below the
        expansion level.

    Default parameters:
        atr_period (int): ATR calculation period. Default 14.
        ma_period (int): SMA direction filter period. Default 20.
        expansion_ratio (float): Minimum ATR current/previous ratio. Default 1.05.

    Signal logic:
        BUY  — ATR expanding AND close > SMA.
        SELL — ATR expanding AND close < SMA.
        EXIT — ATR contracting (ratio < 1/expansion_ratio).
    """

    atr_period: int = 14
    ma_period: int = 20
    expansion_ratio: float = 1.05

    def __init__(
        self,
        name: str = "ATRBreakoutStrategy",
        symbol: str = "",
        atr_period: int = 14,
        ma_period: int = 20,
        expansion_ratio: float = 1.05,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.atr_period = atr_period
        self.ma_period = ma_period
        self.expansion_ratio = expansion_ratio
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._closes: list[float] = []
        self._prev_atr: float = 0.0
        self._in_position: bool = False

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit ATR expansion signals.

        Args:
            bar: OHLCV bar with .high, .low, .close attributes.
        """
        self._highs.append(float(bar.high))
        self._lows.append(float(bar.low))
        self._closes.append(float(bar.close))
        self._bar_count += 1

        min_bars = max(self.atr_period, self.ma_period) + 2
        if len(self._closes) < min_bars:
            return

        highs = np.array(self._highs)
        lows = np.array(self._lows)
        closes = np.array(self._closes)

        atr_now = _atr_np(highs, lows, closes, self.atr_period)
        sma_vals = self.indicators.sma(self._closes, self.ma_period)
        sma_now = sma_vals[-1]
        close = self._closes[-1]

        if self._prev_atr == 0.0:
            self._prev_atr = atr_now
            return

        is_expanding = self._prev_atr > 0 and atr_now / self._prev_atr >= self.expansion_ratio
        is_contracting = self._prev_atr > 0 and atr_now / self._prev_atr < 1.0 / self.expansion_ratio

        # Exit on contraction
        if self._in_position and is_contracting:
            self.exit_position()
            self._in_position = False

        # Entry on expansion
        if not self._in_position and is_expanding:
            if close > sma_now:
                self.enter_long()
                self._in_position = True
            elif close < sma_now:
                self.enter_short()
                self._in_position = True

        self._prev_atr = atr_now


# ---------------------------------------------------------------------------
# ATRRangeStrategy
# ---------------------------------------------------------------------------


class ATRRangeStrategy(BaseBacktestStrategy):
    """ATR range measurement breakout strategy.

    Description:
        Measures price movement over N candles. When the absolute price move
        over N bars equals or exceeds one ATR, enters in the direction of the
        move. Exits when price crosses the SMA.

    Default parameters:
        ma_period (int): SMA exit filter period. Default 20.
        atr_period (int): ATR calculation period. Default 14.
        lookback_period (int): N candles over which to measure movement. Default 5.

    Signal logic:
        BUY  — price rose >= ATR over lookback_period bars.
        SELL — price fell >= ATR over lookback_period bars.
        EXIT — price crosses SMA.
    """

    ma_period: int = 20
    atr_period: int = 14
    lookback_period: int = 5

    def __init__(
        self,
        name: str = "ATRRangeStrategy",
        symbol: str = "",
        ma_period: int = 20,
        atr_period: int = 14,
        lookback_period: int = 5,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.ma_period = ma_period
        self.atr_period = atr_period
        self.lookback_period = lookback_period
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._closes: list[float] = []
        self._in_long: bool = False
        self._in_short: bool = False

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit ATR range breakout signals.

        Args:
            bar: OHLCV bar with .high, .low, .close attributes.
        """
        self._highs.append(float(bar.high))
        self._lows.append(float(bar.low))
        self._closes.append(float(bar.close))
        self._bar_count += 1

        min_bars = max(self.ma_period, self.atr_period) + self.lookback_period + 1
        if len(self._closes) < min_bars:
            return

        highs = np.array(self._highs)
        lows = np.array(self._lows)
        closes = np.array(self._closes)

        atr_val = _atr_np(highs, lows, closes, self.atr_period)
        sma_vals = self.indicators.sma(self._closes, self.ma_period)
        sma_now = sma_vals[-1]
        close = self._closes[-1]
        lb = self.lookback_period

        # Exit: price crosses SMA
        if self._in_long and close < sma_now:
            self.exit_position()
            self._in_long = False
            return
        if self._in_short and close > sma_now:
            self.exit_position()
            self._in_short = False
            return

        # Entry: check every N bars
        if self._bar_count % lb == 0 and not self._in_long and not self._in_short:
            price_movement = close - self._closes[-1 - lb]
            if abs(price_movement) >= atr_val:
                if price_movement > 0:
                    self.enter_long()
                    self._in_long = True
                elif price_movement < 0:
                    self.enter_short()
                    self._in_short = True


# ---------------------------------------------------------------------------
# ChoppinessBreakoutStrategy
# ---------------------------------------------------------------------------


class ChoppinessBreakoutStrategy(BaseBacktestStrategy):
    """Choppiness Index trend-filter breakout strategy.

    Description:
        The Choppiness Index quantifies whether a market is trending or
        choppy. Values below the trend threshold indicate a trending market
        where breakout trades are taken; values above the chop threshold
        signal that positions should be closed.

    Default parameters:
        ma_period (int): SMA direction filter period. Default 20.
        choppiness_period (int): Choppiness Index period. Default 14.
        trend_threshold (float): Choppiness below this = trending. Default 61.8.
        chop_threshold (float): Choppiness above this = exit positions. Default 61.8.

    Signal logic:
        BUY  — Choppiness < trend_threshold AND close > SMA.
        SELL — Choppiness < trend_threshold AND close < SMA.
        EXIT — Choppiness > chop_threshold.
    """

    ma_period: int = 20
    choppiness_period: int = 14
    trend_threshold: float = 61.8
    chop_threshold: float = 61.8

    def __init__(
        self,
        name: str = "ChoppinessBreakoutStrategy",
        symbol: str = "",
        ma_period: int = 20,
        choppiness_period: int = 14,
        trend_threshold: float = 61.8,
        chop_threshold: float = 61.8,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.ma_period = ma_period
        self.choppiness_period = choppiness_period
        self.trend_threshold = trend_threshold
        self.chop_threshold = chop_threshold
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._closes: list[float] = []
        self._in_long: bool = False
        self._in_short: bool = False

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit Choppiness Index signals.

        Args:
            bar: OHLCV bar with .high, .low, .close attributes.
        """
        self._highs.append(float(bar.high))
        self._lows.append(float(bar.low))
        self._closes.append(float(bar.close))
        self._bar_count += 1

        min_bars = max(self.ma_period, self.choppiness_period) + 2
        if len(self._closes) < min_bars:
            return

        chop = _choppiness(self._highs, self._lows, self._closes, self.choppiness_period)
        sma_vals = self.indicators.sma(self._closes, self.ma_period)
        sma_now = sma_vals[-1]
        close = self._closes[-1]

        is_trending = chop < self.trend_threshold
        is_choppy = chop > self.chop_threshold

        # Exit on choppy market
        if (self._in_long or self._in_short) and is_choppy:
            self.exit_position()
            self._in_long = False
            self._in_short = False
            return

        # Entry in trending market
        if not self._in_long and not self._in_short and is_trending:
            if close > sma_now:
                self.enter_long()
                self._in_long = True
            elif close < sma_now:
                self.enter_short()
                self._in_short = True


# ---------------------------------------------------------------------------
# VolatilityContractionStrategy
# ---------------------------------------------------------------------------


class VolatilityContractionStrategy(BaseBacktestStrategy):
    """Bollinger Band width expansion strategy (VCP-style volatility trigger).

    Description:
        Measures Bollinger Band width (upper - lower) normalised by the middle
        band. Enters when bandwidth is expanding (current > previous) in the
        direction price is relative to the middle band. Exits when bandwidth
        starts contracting.

    Default parameters:
        period (int): Bollinger Band period. Default 20.
        num_std (float): Standard deviation multiplier. Default 2.0.

    Signal logic:
        BUY  — BB width expanding AND close > middle band.
        SELL — BB width expanding AND close < middle band.
        EXIT — BB width contracting (current < previous).
    """

    period: int = 20
    num_std: float = 2.0

    def __init__(
        self,
        name: str = "VolatilityContractionStrategy",
        symbol: str = "",
        period: int = 20,
        num_std: float = 2.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.period = period
        self.num_std = num_std
        self._closes: list[float] = []
        self._prev_width: float = 0.0
        self._in_long: bool = False
        self._in_short: bool = False

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit BB-width expansion signals.

        Args:
            bar: OHLCV bar with .close attribute.
        """
        self._closes.append(float(bar.close))
        self._bar_count += 1

        if len(self._closes) < self.period + 1:
            return

        upper, middle, lower = self.indicators.bollinger_bands(
            self._closes, self.period, self.num_std
        )
        mid = middle[-1]
        up = upper[-1]
        lo = lower[-1]
        close = self._closes[-1]

        if mid == 0.0 or up == 0.0 or lo == 0.0:
            return

        width = (up - lo) / mid

        if self._prev_width == 0.0:
            self._prev_width = width
            return

        is_expanding = width > self._prev_width
        is_contracting = width < self._prev_width

        # Exit on contraction
        if (self._in_long or self._in_short) and is_contracting:
            self.exit_position()
            self._in_long = False
            self._in_short = False

        # Entry on expansion
        if not self._in_long and not self._in_short and is_expanding:
            if close > mid:
                self.enter_long()
                self._in_long = True
            elif close < mid:
                self.enter_short()
                self._in_short = True

        self._prev_width = width
