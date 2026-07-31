"""Multi-indicator composite strategies — adapted from AlgoTrading repo.

Strategies:
    RSI_MACD_Strategy      — RSI oversold/overbought + MACD trend confirmation
    SupertrendEMAStrategy  — Supertrend direction confirmed by EMA slope
    TripleScreenStrategy   — Elder's Triple Screen: weekly trend + daily oscillator + intraday entry
    IchimokuStrategy       — Ichimoku Cloud: price above/below kumo + Tenkan/Kijun cross

All strategies extend BaseBacktestStrategy and emit signals via
``enter_long`` / ``enter_short`` / ``exit_position``.
"""

from __future__ import annotations

import logging
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

logger = logging.getLogger("flinttrade.backtest.strategies.composite")

__all__ = [
    "RSI_MACD_Strategy",
    "SupertrendEMAStrategy",
    "TripleScreenStrategy",
    "IchimokuStrategy",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ema_np(arr: np.ndarray, period: int) -> np.ndarray:
    """EMA using 2/(period+1) multiplier."""
    k = 2.0 / (period + 1)
    result = np.empty_like(arr, dtype=float)
    result[0] = float(arr[0])
    for i in range(1, len(arr)):
        result[i] = float(arr[i]) * k + result[i - 1] * (1.0 - k)
    return result


def _rsi_current(closes: list[float], period: int) -> float:
    """Compute current RSI value.

    Args:
        closes: Close price series.
        period: RSI period.

    Returns:
        RSI in [0, 100].
    """
    if len(closes) < period + 1:
        return 50.0
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains.append(max(0.0, d))
        losses.append(max(0.0, -d))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    for i in range(period, len(closes) - 1):
        d = closes[i + 1] - closes[i]
        avg_gain = (avg_gain * (period - 1) + max(0.0, d)) / period
        avg_loss = (avg_loss * (period - 1) + max(0.0, -d)) / period
    if avg_loss == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def _atr_np(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> float:
    """Wilder ATR for the most recent bar."""
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


def _supertrend(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int,
    multiplier: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute Supertrend values and uptrend flags.

    Args:
        highs: High prices.
        lows: Low prices.
        closes: Close prices.
        period: ATR period.
        multiplier: ATR multiplier.

    Returns:
        Tuple of (supertrend_values, is_uptrend) arrays.
    """
    n = len(closes)
    st = np.zeros(n)
    uptrend = np.ones(n, dtype=bool)

    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    atr = np.zeros(n)
    if n >= period:
        atr[period - 1] = float(np.mean(tr[:period]))
        for i in range(period, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    for i in range(period, n):
        median = (highs[i] + lows[i]) / 2.0
        basic_upper = median + multiplier * atr[i]
        basic_lower = median - multiplier * atr[i]
        if i == period:
            st[i] = basic_lower if closes[i] > basic_lower else basic_upper
            uptrend[i] = closes[i] > st[i]
            continue
        if uptrend[i - 1]:
            st[i] = max(basic_lower, st[i - 1]) if closes[i] > st[i - 1] else basic_upper
        else:
            st[i] = min(basic_upper, st[i - 1]) if closes[i] < st[i - 1] else basic_lower
        uptrend[i] = closes[i] > st[i]

    return st, uptrend


# ---------------------------------------------------------------------------
# RSI_MACD_Strategy
# ---------------------------------------------------------------------------


class RSI_MACD_Strategy(BaseBacktestStrategy):
    """RSI + MACD dual confirmation strategy.

    Description:
        Combines two indicators requiring both to agree before entry:
        - RSI must be in oversold territory (< rsi_oversold) for buy or
          overbought territory (> rsi_overbought) for sell.
        - MACD line must have crossed the signal line in the confirming direction.

    Default parameters:
        rsi_period (int): RSI period. Default 14.
        rsi_oversold (float): RSI buy threshold. Default 40.0.
        rsi_overbought (float): RSI sell threshold. Default 60.0.
        macd_fast (int): MACD fast EMA period. Default 12.
        macd_slow (int): MACD slow EMA period. Default 26.
        macd_signal (int): MACD signal EMA period. Default 9.

    Signal logic:
        BUY  — RSI < rsi_oversold AND MACD crosses above signal.
        SELL — RSI > rsi_overbought AND MACD crosses below signal.
    """

    rsi_period: int = 14
    rsi_oversold: float = 40.0
    rsi_overbought: float = 60.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    def __init__(
        self,
        name: str = "RSI_MACD_Strategy",
        symbol: str = "",
        rsi_period: int = 14,
        rsi_oversold: float = 40.0,
        rsi_overbought: float = 60.0,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self._closes: list[float] = []

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit RSI + MACD confirmation signals.

        Args:
            bar: OHLCV bar with .close attribute.
        """
        self._closes.append(float(bar.close))
        self._bar_count += 1

        warmup = max(self.rsi_period, self.macd_slow + self.macd_signal) + 2
        if len(self._closes) < warmup:
            return

        rsi_val = _rsi_current(self._closes, self.rsi_period)
        closes_arr = np.array(self._closes)
        fast_ema = _ema_np(closes_arr, self.macd_fast)
        slow_ema = _ema_np(closes_arr, self.macd_slow)
        macd_line = fast_ema - slow_ema
        signal_line = _ema_np(macd_line, self.macd_signal)

        macd_cross_up = macd_line[-1] > signal_line[-1] and macd_line[-2] <= signal_line[-2]
        macd_cross_dn = macd_line[-1] < signal_line[-1] and macd_line[-2] >= signal_line[-2]

        if rsi_val < self.rsi_oversold and macd_cross_up:
            self.enter_long()
        elif rsi_val > self.rsi_overbought and macd_cross_dn:
            self.enter_short()


# ---------------------------------------------------------------------------
# SupertrendEMAStrategy
# ---------------------------------------------------------------------------


class SupertrendEMAStrategy(BaseBacktestStrategy):
    """Supertrend + EMA filter composite strategy.

    Description:
        Supertrend direction change is used as the primary signal. The EMA
        acts as a secondary filter: only enters long when the EMA is rising
        (current > previous); only enters short when the EMA is falling.

    Default parameters:
        st_period (int): Supertrend ATR period. Default 10.
        st_multiplier (float): Supertrend ATR multiplier. Default 3.0.
        ema_period (int): EMA filter period. Default 50.

    Signal logic:
        BUY  — Supertrend flips to uptrend AND EMA is rising.
        SELL — Supertrend flips to downtrend AND EMA is falling.
    """

    st_period: int = 10
    st_multiplier: float = 3.0
    ema_period: int = 50

    def __init__(
        self,
        name: str = "SupertrendEMAStrategy",
        symbol: str = "",
        st_period: int = 10,
        st_multiplier: float = 3.0,
        ema_period: int = 50,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.st_period = st_period
        self.st_multiplier = st_multiplier
        self.ema_period = ema_period
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._closes: list[float] = []

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit Supertrend + EMA signals.

        Args:
            bar: OHLCV bar with .high, .low, .close attributes.
        """
        self._highs.append(float(bar.high))
        self._lows.append(float(bar.low))
        self._closes.append(float(bar.close))
        self._bar_count += 1

        warmup = max(self.st_period, self.ema_period) + 2
        if len(self._closes) < warmup:
            return

        highs = np.array(self._highs)
        lows = np.array(self._lows)
        closes = np.array(self._closes)

        _, uptrend = _supertrend(highs, lows, closes, self.st_period, self.st_multiplier)
        ema_vals = _ema_np(closes, self.ema_period)

        st_flipped_up = uptrend[-1] and not uptrend[-2]
        st_flipped_dn = not uptrend[-1] and uptrend[-2]
        ema_rising = ema_vals[-1] > ema_vals[-2]
        ema_falling = ema_vals[-1] < ema_vals[-2]

        if st_flipped_up and ema_rising:
            self.enter_long()
        elif st_flipped_dn and ema_falling:
            self.enter_short()


# ---------------------------------------------------------------------------
# TripleScreenStrategy
# ---------------------------------------------------------------------------


class TripleScreenStrategy(BaseBacktestStrategy):
    """Elder's Triple Screen strategy.

    Description:
        Implements Alexander Elder's Triple Screen approach using three
        timeframe filters applied to a single bar stream:

        Screen 1 (Weekly trend): EMA slope on a long-period EMA.
        Screen 2 (Daily oscillator): MACD histogram direction.
        Screen 3 (Intraday entry): Bar-level momentum impulse.

        An entry is generated only when all three screens agree.

    Default parameters:
        trend_ema_period (int): Long EMA for Screen 1 trend detection. Default 52.
        macd_fast (int): MACD fast EMA. Default 12.
        macd_slow (int): MACD slow EMA. Default 26.
        macd_signal (int): MACD signal EMA. Default 9.
        rsi_period (int): RSI period for Screen 3 impulse. Default 5.

    Signal logic:
        BUY  — long EMA rising (Screen 1) AND MACD histogram crossing above zero
               (Screen 2) AND RSI < 70 (Screen 3 not overbought).
        SELL — long EMA falling (Screen 1) AND MACD histogram crossing below zero
               (Screen 2) AND RSI > 30 (Screen 3 not oversold).
    """

    trend_ema_period: int = 52
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    rsi_period: int = 5

    def __init__(
        self,
        name: str = "TripleScreenStrategy",
        symbol: str = "",
        trend_ema_period: int = 52,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        rsi_period: int = 5,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.trend_ema_period = trend_ema_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.rsi_period = rsi_period
        self._closes: list[float] = []

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit Triple Screen signals.

        Args:
            bar: OHLCV bar with .close attribute.
        """
        self._closes.append(float(bar.close))
        self._bar_count += 1

        warmup = max(self.trend_ema_period, self.macd_slow + self.macd_signal, self.rsi_period) + 3
        if len(self._closes) < warmup:
            return

        closes_arr = np.array(self._closes)

        # Screen 1: long-period EMA trend direction
        trend_ema = _ema_np(closes_arr, self.trend_ema_period)
        trend_rising = trend_ema[-1] > trend_ema[-2]
        trend_falling = trend_ema[-1] < trend_ema[-2]

        # Screen 2: MACD histogram crosses zero
        fast_ema = _ema_np(closes_arr, self.macd_fast)
        slow_ema = _ema_np(closes_arr, self.macd_slow)
        macd_line = fast_ema - slow_ema
        signal_line = _ema_np(macd_line, self.macd_signal)
        hist = macd_line - signal_line
        hist_cross_up = hist[-1] > 0.0 and hist[-2] <= 0.0
        hist_cross_dn = hist[-1] < 0.0 and hist[-2] >= 0.0

        # Screen 3: RSI not overbought/oversold
        rsi_val = _rsi_current(self._closes, self.rsi_period)

        if trend_rising and hist_cross_up and rsi_val < 70.0:
            self.enter_long()
        elif trend_falling and hist_cross_dn and rsi_val > 30.0:
            self.enter_short()


# ---------------------------------------------------------------------------
# IchimokuStrategy
# ---------------------------------------------------------------------------


class IchimokuStrategy(BaseBacktestStrategy):
    """Ichimoku Cloud strategy.

    Description:
        Implements the standard Ichimoku Kinko Hyo trading system.
        The primary signal is the Tenkan-sen / Kijun-sen crossover (TK cross),
        confirmed by price being above or below the Kumo (cloud).

    Default parameters:
        tenkan_period (int): Conversion line period. Default 9.
        kijun_period (int): Base line period. Default 26.
        senkou_b_period (int): Leading Span B period. Default 52.

    Signal logic:
        BUY  — Tenkan crosses above Kijun AND close > both Senkou A and B (above cloud).
        SELL — Tenkan crosses below Kijun AND close < both Senkou A and B (below cloud).
    """

    tenkan_period: int = 9
    kijun_period: int = 26
    senkou_b_period: int = 52

    def __init__(
        self,
        name: str = "IchimokuStrategy",
        symbol: str = "",
        tenkan_period: int = 9,
        kijun_period: int = 26,
        senkou_b_period: int = 52,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.tenkan_period = tenkan_period
        self.kijun_period = kijun_period
        self.senkou_b_period = senkou_b_period
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._closes: list[float] = []

    def _mid_range(self, period: int, offset: int = 0) -> float:
        """Compute midpoint of high/low over a lookback period.

        Args:
            period: Lookback period.
            offset: Offset from the end of the series (0 = most recent).

        Returns:
            Midpoint of the highest high and lowest low.
        """
        end = len(self._highs) - offset
        start = end - period
        if start < 0:
            return 0.0
        h = max(self._highs[start:end])
        lo = min(self._lows[start:end])
        return (h + lo) / 2.0

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit Ichimoku TK-cross signals.

        Args:
            bar: OHLCV bar with .high, .low, .close attributes.
        """
        self._highs.append(float(bar.high))
        self._lows.append(float(bar.low))
        self._closes.append(float(bar.close))
        self._bar_count += 1

        warmup = self.senkou_b_period + 2
        if len(self._closes) < warmup:
            return

        tenkan_now = self._mid_range(self.tenkan_period, 0)
        tenkan_prev = self._mid_range(self.tenkan_period, 1)
        kijun_now = self._mid_range(self.kijun_period, 0)
        kijun_prev = self._mid_range(self.kijun_period, 1)

        if tenkan_now == 0.0 or kijun_now == 0.0:
            return

        # Senkou A and B (current cloud — displaced back by kijun_period for reference)
        disp = self.kijun_period
        senkou_a = self._mid_range(self.tenkan_period, disp) if len(self._highs) > disp else 0.0
        senkou_b = self._mid_range(self.senkou_b_period, disp) if len(self._highs) > disp + self.senkou_b_period else 0.0

        close = self._closes[-1]

        tk_cross_up = tenkan_prev <= kijun_prev and tenkan_now > kijun_now
        tk_cross_dn = tenkan_prev >= kijun_prev and tenkan_now < kijun_now

        # Cloud check
        if senkou_a > 0.0 and senkou_b > 0.0:
            kumo_top = max(senkou_a, senkou_b)
            kumo_bot = min(senkou_a, senkou_b)
            above_cloud = close > kumo_top
            below_cloud = close < kumo_bot
        else:
            above_cloud = True
            below_cloud = True

        if tk_cross_up and above_cloud:
            self.enter_long()
        elif tk_cross_dn and below_cloud:
            self.enter_short()
