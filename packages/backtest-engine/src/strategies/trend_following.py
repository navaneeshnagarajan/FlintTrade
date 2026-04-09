"""Trend-following strategies — absorbed from AlgoTrading repo (0001–0015, 0022).

Strategies:
    SupertrendStrategy        — Supertrend crossover (0010_Super_Trend)
    EMACrossoverStrategy      — EMA fast/slow crossover (0001_MA_CrossOver)
    MACDStrategy              — MACD signal-line crossover (0009_MACD_Trend)
    ADXStrategy               — ADX trend-strength filter with SMA (0003_ADX_Trend)
    ADXDIStrategy             — ADX with +DI/-DI crossover (0022_ADX_DI)
    ParabolicSARStrategy      — Parabolic SAR crossover (0004_Parabolic_SAR_Trend)
    DonchianBreakoutStrategy  — Donchian channel price breakout (0005_Donchian_Channel)
    KeltnerBreakoutStrategy   — Keltner channel breakout (0007_Keltner_Channel_Breakout)
    HeikinAshiStrategy        — N consecutive Heikin-Ashi candles (0012_Heikin_Ashi)

All strategies extend BaseBacktestStrategy and emit signals via
``enter_long`` / ``enter_short`` / ``exit_position``.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

try:
    from ..base_strategy import BaseBacktestStrategy
except ImportError:
    from base_strategy import BaseBacktestStrategy  # type: ignore[no-redef]

logger = logging.getLogger("flinttrade.backtest.strategies.trend_following")

__all__ = [
    "SupertrendStrategy",
    "EMACrossoverStrategy",
    "MACDStrategy",
    "ADXStrategy",
    "ADXDIStrategy",
    "ParabolicSARStrategy",
    "DonchianBreakoutStrategy",
    "KeltnerBreakoutStrategy",
    "HeikinAshiStrategy",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ema_np(arr: np.ndarray, period: int) -> np.ndarray:
    """EMA using numpy with Wilder-compatible weighting."""
    k = 2.0 / (period + 1)
    result = np.empty_like(arr)
    result[0] = arr[0]
    for i in range(1, len(arr)):
        result[i] = arr[i] * k + result[i - 1] * (1.0 - k)
    return result


def _atr_np(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> np.ndarray:
    """Wilder-smoothed ATR."""
    n = len(closes)
    tr = np.empty(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    atr = np.zeros(n)
    if n < period:
        return atr
    atr[period - 1] = float(np.mean(tr[:period]))
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


# ---------------------------------------------------------------------------
# SupertrendStrategy
# ---------------------------------------------------------------------------


class SupertrendStrategy(BaseBacktestStrategy):
    """Supertrend indicator crossover strategy.

    Description:
        Computes Supertrend = median ± multiplier × ATR.
        Enters long when price crosses above the Supertrend line,
        enters short when price crosses below.

    Default parameters:
        period (int): ATR period. Default 10.
        multiplier (float): ATR multiplier. Default 3.0.

    Signal logic:
        BUY  — price crosses above Supertrend (was below, now above).
        SELL — price crosses below Supertrend (was above, now below).
    """

    period: int = 10
    multiplier: float = 3.0

    def __init__(
        self,
        name: str = "SupertrendStrategy",
        symbol: str = "",
        period: int = 10,
        multiplier: float = 3.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.period = period
        self.multiplier = multiplier
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._closes: list[float] = []

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit Supertrend crossover signals.

        Args:
            bar: OHLCV bar with .high, .low, .close attributes.
        """
        self._highs.append(float(bar.high))
        self._lows.append(float(bar.low))
        self._closes.append(float(bar.close))
        self._bar_count += 1

        if len(self._closes) < self.period + 2:
            return

        highs = np.array(self._highs)
        lows = np.array(self._lows)
        closes = np.array(self._closes)
        atr = _atr_np(highs, lows, closes, self.period)
        n = len(closes)

        # Compute Supertrend
        st = np.zeros(n)
        uptrend = np.ones(n, dtype=bool)
        for i in range(self.period, n):
            median = (highs[i] + lows[i]) / 2.0
            basic_upper = median + self.multiplier * atr[i]
            basic_lower = median - self.multiplier * atr[i]
            if i == self.period:
                st[i] = basic_lower if closes[i] > basic_lower else basic_upper
                uptrend[i] = closes[i] > st[i]
                continue
            if uptrend[i - 1]:
                st[i] = max(basic_lower, st[i - 1]) if closes[i] > st[i - 1] else basic_upper
            else:
                st[i] = min(basic_upper, st[i - 1]) if closes[i] < st[i - 1] else basic_lower
            uptrend[i] = closes[i] > st[i]

        was_above = uptrend[-2]
        is_above = uptrend[-1]

        if is_above and not was_above:
            self.enter_long()
        elif not is_above and was_above:
            self.enter_short()


# ---------------------------------------------------------------------------
# EMACrossoverStrategy
# ---------------------------------------------------------------------------


class EMACrossoverStrategy(BaseBacktestStrategy):
    """EMA fast/slow crossover strategy.

    Description:
        Uses two Exponential Moving Averages. Enters long when the fast EMA
        crosses above the slow EMA; enters short when it crosses below.

    Default parameters:
        fast_period (int): Fast EMA period. Default 9.
        slow_period (int): Slow EMA period. Default 21.

    Signal logic:
        BUY  — fast EMA crosses above slow EMA.
        SELL — fast EMA crosses below slow EMA.
    """

    fast_period: int = 9
    slow_period: int = 21

    def __init__(
        self,
        name: str = "EMACrossoverStrategy",
        symbol: str = "",
        fast_period: int = 9,
        slow_period: int = 21,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.fast_period = fast_period
        self.slow_period = slow_period
        self._closes: list[float] = []

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit EMA crossover signals.

        Args:
            bar: OHLCV bar with .close attribute.
        """
        self._closes.append(float(bar.close))
        self._bar_count += 1

        if len(self._closes) < self.slow_period + 1:
            return

        closes = np.array(self._closes)
        fast = _ema_np(closes, self.fast_period)
        slow = _ema_np(closes, self.slow_period)

        cross_up = fast[-1] > slow[-1] and fast[-2] <= slow[-2]
        cross_dn = fast[-1] < slow[-1] and fast[-2] >= slow[-2]

        if cross_up:
            self.enter_long()
        elif cross_dn:
            self.enter_short()


# ---------------------------------------------------------------------------
# MACDStrategy
# ---------------------------------------------------------------------------


class MACDStrategy(BaseBacktestStrategy):
    """MACD signal-line crossover strategy.

    Description:
        Computes the MACD line (fast EMA − slow EMA) and a signal line
        (EMA of MACD). Enters long when MACD crosses above signal;
        enters short when MACD crosses below signal.

    Default parameters:
        fast_period (int): Fast EMA period. Default 12.
        slow_period (int): Slow EMA period. Default 26.
        signal_period (int): Signal EMA period. Default 9.

    Signal logic:
        BUY  — MACD line crosses above signal line.
        SELL — MACD line crosses below signal line.
    """

    fast_period: int = 12
    slow_period: int = 26
    signal_period: int = 9

    def __init__(
        self,
        name: str = "MACDStrategy",
        symbol: str = "",
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        self._closes: list[float] = []

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit MACD crossover signals.

        Args:
            bar: OHLCV bar with .close attribute.
        """
        self._closes.append(float(bar.close))
        self._bar_count += 1

        warmup = self.slow_period + self.signal_period + 1
        if len(self._closes) < warmup:
            return

        closes = np.array(self._closes)
        fast_ema = _ema_np(closes, self.fast_period)
        slow_ema = _ema_np(closes, self.slow_period)
        macd_line = fast_ema - slow_ema
        signal_line = _ema_np(macd_line, self.signal_period)

        crossed_above = macd_line[-1] > signal_line[-1] and macd_line[-2] <= signal_line[-2]
        crossed_below = macd_line[-1] < signal_line[-1] and macd_line[-2] >= signal_line[-2]

        if crossed_above:
            self.enter_long()
        elif crossed_below:
            self.enter_short()


# ---------------------------------------------------------------------------
# ADXStrategy
# ---------------------------------------------------------------------------


class ADXStrategy(BaseBacktestStrategy):
    """ADX trend-strength filter with SMA crossover.

    Description:
        Combines ADX (Average Directional Index) with a Simple Moving Average.
        Only enters when ADX exceeds a threshold (strong trend), using price
        crossing the SMA as the entry trigger.

    Default parameters:
        adx_period (int): ADX calculation period. Default 14.
        ma_period (int): SMA trend period. Default 20.
        adx_threshold (float): Minimum ADX for trade entry. Default 25.0.

    Signal logic:
        BUY  — price crosses above SMA AND ADX > threshold.
        SELL — price crosses below SMA AND ADX > threshold.
        EXIT — ADX falls below threshold (trend weakening).
    """

    adx_period: int = 14
    ma_period: int = 20
    adx_threshold: float = 25.0

    def __init__(
        self,
        name: str = "ADXStrategy",
        symbol: str = "",
        adx_period: int = 14,
        ma_period: int = 20,
        adx_threshold: float = 25.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.adx_period = adx_period
        self.ma_period = ma_period
        self.adx_threshold = adx_threshold
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._closes: list[float] = []

    def _compute_adx(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> float:
        """Compute current ADX value using Wilder smoothing.

        Args:
            highs: High price series.
            lows: Low price series.
            closes: Close price series.

        Returns:
            Current ADX value.
        """
        period = self.adx_period
        n = len(closes)
        if n < period * 2:
            return 0.0

        tr = np.zeros(n)
        plus_dm = np.zeros(n)
        minus_dm = np.zeros(n)
        for i in range(1, n):
            h_diff = highs[i] - highs[i - 1]
            l_diff = lows[i - 1] - lows[i]
            tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            plus_dm[i] = h_diff if h_diff > l_diff and h_diff > 0 else 0.0
            minus_dm[i] = l_diff if l_diff > h_diff and l_diff > 0 else 0.0

        # Wilder smooth
        smooth_tr = float(np.sum(tr[1:period + 1]))
        smooth_plus = float(np.sum(plus_dm[1:period + 1]))
        smooth_minus = float(np.sum(minus_dm[1:period + 1]))
        dx_vals: list[float] = []

        for i in range(period + 1, n):
            smooth_tr = smooth_tr - smooth_tr / period + tr[i]
            smooth_plus = smooth_plus - smooth_plus / period + plus_dm[i]
            smooth_minus = smooth_minus - smooth_minus / period + minus_dm[i]
            if smooth_tr == 0:
                continue
            plus_di = 100.0 * smooth_plus / smooth_tr
            minus_di = 100.0 * smooth_minus / smooth_tr
            denom = plus_di + minus_di
            if denom == 0:
                continue
            dx_vals.append(100.0 * abs(plus_di - minus_di) / denom)

        if len(dx_vals) < period:
            return 0.0
        adx = float(np.mean(dx_vals[-period:]))
        return adx

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit ADX-filtered SMA crossover signals.

        Args:
            bar: OHLCV bar with .high, .low, .close attributes.
        """
        self._highs.append(float(bar.high))
        self._lows.append(float(bar.low))
        self._closes.append(float(bar.close))
        self._bar_count += 1

        min_bars = max(self.ma_period, self.adx_period * 2) + 2
        if len(self._closes) < min_bars:
            return

        closes = np.array(self._closes)
        sma_vals = np.array(self.indicators.sma(list(closes), self.ma_period))
        highs = np.array(self._highs)
        lows = np.array(self._lows)

        adx_val = self._compute_adx(highs, lows, closes)
        close = self._closes[-1]
        prev_close = self._closes[-2]
        sma_now = sma_vals[-1]
        sma_prev = sma_vals[-2]

        if adx_val < self.adx_threshold:
            return

        price_crossed_above = prev_close <= sma_prev and close > sma_now
        price_crossed_below = prev_close >= sma_prev and close < sma_now

        if price_crossed_above:
            self.enter_long()
        elif price_crossed_below:
            self.enter_short()


# ---------------------------------------------------------------------------
# ADXDIStrategy
# ---------------------------------------------------------------------------


class ADXDIStrategy(BaseBacktestStrategy):
    """+DI / -DI crossover with ADX confirmation.

    Description:
        Uses the directional indicators +DI and -DI. Enters long when +DI
        crosses above -DI with ADX confirming trend strength; enters short
        on the reverse cross.

    Default parameters:
        adx_period (int): ADX calculation period. Default 14.
        adx_threshold (float): Minimum ADX for entry. Default 15.0.

    Signal logic:
        BUY  — +DI crosses above -DI AND ADX >= threshold.
        SELL — -DI crosses above +DI AND ADX >= threshold.
    """

    adx_period: int = 14
    adx_threshold: float = 15.0

    def __init__(
        self,
        name: str = "ADXDIStrategy",
        symbol: str = "",
        adx_period: int = 14,
        adx_threshold: float = 15.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._closes: list[float] = []

    def _compute_di(
        self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray
    ) -> tuple[float, float, float]:
        """Compute +DI, -DI, and ADX for the last bar.

        Args:
            highs: High price series.
            lows: Low price series.
            closes: Close price series.

        Returns:
            Tuple of (plus_di, minus_di, adx).
        """
        period = self.adx_period
        n = len(closes)
        if n < period * 2 + 1:
            return 0.0, 0.0, 0.0

        tr = np.zeros(n)
        plus_dm = np.zeros(n)
        minus_dm = np.zeros(n)
        for i in range(1, n):
            h_diff = highs[i] - highs[i - 1]
            l_diff = lows[i - 1] - lows[i]
            tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            plus_dm[i] = h_diff if h_diff > l_diff and h_diff > 0 else 0.0
            minus_dm[i] = l_diff if l_diff > h_diff and l_diff > 0 else 0.0

        smooth_tr = float(np.sum(tr[1:period + 1]))
        smooth_plus = float(np.sum(plus_dm[1:period + 1]))
        smooth_minus = float(np.sum(minus_dm[1:period + 1]))
        dx_vals: list[float] = []
        final_plus = smooth_plus / smooth_tr * 100.0 if smooth_tr else 0.0
        final_minus = smooth_minus / smooth_tr * 100.0 if smooth_tr else 0.0

        for i in range(period + 1, n):
            smooth_tr = smooth_tr - smooth_tr / period + tr[i]
            smooth_plus = smooth_plus - smooth_plus / period + plus_dm[i]
            smooth_minus = smooth_minus - smooth_minus / period + minus_dm[i]
            if smooth_tr == 0:
                continue
            final_plus = 100.0 * smooth_plus / smooth_tr
            final_minus = 100.0 * smooth_minus / smooth_tr
            denom = final_plus + final_minus
            if denom == 0:
                continue
            dx_vals.append(100.0 * abs(final_plus - final_minus) / denom)

        adx = float(np.mean(dx_vals[-period:])) if len(dx_vals) >= period else 0.0
        return final_plus, final_minus, adx

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit +DI/-DI crossover signals.

        Args:
            bar: OHLCV bar with .high, .low, .close attributes.
        """
        self._highs.append(float(bar.high))
        self._lows.append(float(bar.low))
        self._closes.append(float(bar.close))
        self._bar_count += 1

        if len(self._closes) < self.adx_period * 2 + 2:
            return

        highs = np.array(self._highs)
        lows = np.array(self._lows)
        closes = np.array(self._closes)

        plus_di_now, minus_di_now, adx_now = self._compute_di(highs, lows, closes)
        plus_di_prev, minus_di_prev, _ = self._compute_di(highs[:-1], lows[:-1], closes[:-1])

        if adx_now < self.adx_threshold:
            return

        crossed_long = plus_di_prev <= minus_di_prev and plus_di_now > minus_di_now
        crossed_short = plus_di_prev >= minus_di_prev and plus_di_now < minus_di_now

        if crossed_long:
            self.enter_long()
        elif crossed_short:
            self.enter_short()


# ---------------------------------------------------------------------------
# ParabolicSARStrategy
# ---------------------------------------------------------------------------


class ParabolicSARStrategy(BaseBacktestStrategy):
    """Parabolic SAR trend-following strategy.

    Description:
        Tracks the Parabolic SAR indicator. Enters long when price crosses
        above the SAR; enters short when price crosses below.

    Default parameters:
        acceleration (float): Initial acceleration factor. Default 0.02.
        max_acceleration (float): Maximum acceleration factor. Default 0.2.

    Signal logic:
        BUY  — price crosses above SAR (SAR flips from above to below price).
        SELL — price crosses below SAR (SAR flips from below to above price).
    """

    acceleration: float = 0.02
    max_acceleration: float = 0.2

    def __init__(
        self,
        name: str = "ParabolicSARStrategy",
        symbol: str = "",
        acceleration: float = 0.02,
        max_acceleration: float = 0.2,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.acceleration = acceleration
        self.max_acceleration = max_acceleration
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._closes: list[float] = []

    def _compute_sar(self) -> tuple[float, float]:
        """Compute current and previous SAR values.

        Returns:
            Tuple of (prev_sar, curr_sar).
        """
        closes = self._closes
        highs = self._highs
        lows = self._lows
        n = len(closes)

        af = self.acceleration
        max_af = self.max_acceleration
        rising = closes[1] > closes[0]
        ep = highs[1] if rising else lows[1]
        sar = lows[0] if rising else highs[0]
        prev_sar = sar

        for i in range(2, n):
            prev_sar = sar
            if rising:
                sar = sar + af * (ep - sar)
                sar = min(sar, lows[i - 1], lows[i - 2] if i >= 2 else lows[i - 1])
                if lows[i] < sar:
                    rising = False
                    sar = ep
                    ep = lows[i]
                    af = self.acceleration
                else:
                    if highs[i] > ep:
                        ep = highs[i]
                        af = min(af + self.acceleration, max_af)
            else:
                sar = sar + af * (ep - sar)
                sar = max(sar, highs[i - 1], highs[i - 2] if i >= 2 else highs[i - 1])
                if highs[i] > sar:
                    rising = True
                    sar = ep
                    ep = highs[i]
                    af = self.acceleration
                else:
                    if lows[i] < ep:
                        ep = lows[i]
                        af = min(af + self.acceleration, max_af)

        return prev_sar, sar

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit Parabolic SAR crossover signals.

        Args:
            bar: OHLCV bar with .high, .low, .close attributes.
        """
        self._highs.append(float(bar.high))
        self._lows.append(float(bar.low))
        self._closes.append(float(bar.close))
        self._bar_count += 1

        if len(self._closes) < 5:
            return

        prev_sar, curr_sar = self._compute_sar()
        close = self._closes[-1]
        prev_close = self._closes[-2]

        prev_above = prev_close > prev_sar
        curr_above = close > curr_sar

        if curr_above and not prev_above:
            self.enter_long()
        elif not curr_above and prev_above:
            self.enter_short()


# ---------------------------------------------------------------------------
# DonchianBreakoutStrategy
# ---------------------------------------------------------------------------


class DonchianBreakoutStrategy(BaseBacktestStrategy):
    """Donchian channel price breakout strategy.

    Description:
        Tracks the N-period highest high (upper band) and lowest low
        (lower band). Enters long when price breaks above the previous upper
        band; enters short when price breaks below the previous lower band.

    Default parameters:
        period (int): Donchian channel lookback period. Default 20.

    Signal logic:
        BUY  — close > previous upper band AND previous close <= previous upper band.
        SELL — close < previous lower band AND previous close >= previous lower band.
    """

    period: int = 20

    def __init__(
        self,
        name: str = "DonchianBreakoutStrategy",
        symbol: str = "",
        period: int = 20,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.period = period
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._closes: list[float] = []

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit Donchian breakout signals.

        Args:
            bar: OHLCV bar with .high, .low, .close attributes.
        """
        self._highs.append(float(bar.high))
        self._lows.append(float(bar.low))
        self._closes.append(float(bar.close))
        self._bar_count += 1

        if len(self._closes) < self.period + 2:
            return

        # Previous bar's channel (excludes current bar)
        prev_highs = self._highs[-self.period - 1:-1]
        prev_lows = self._lows[-self.period - 1:-1]
        prev_upper = max(prev_highs)
        prev_lower = min(prev_lows)

        close = self._closes[-1]
        prev_close = self._closes[-2]

        breakout_up = close > prev_upper and prev_close <= prev_upper
        breakout_dn = close < prev_lower and prev_close >= prev_lower

        if breakout_up:
            self.enter_long()
        elif breakout_dn:
            self.enter_short()


# ---------------------------------------------------------------------------
# KeltnerBreakoutStrategy
# ---------------------------------------------------------------------------


class KeltnerBreakoutStrategy(BaseBacktestStrategy):
    """Keltner channel breakout strategy.

    Description:
        Constructs a Keltner Channel using EMA (middle) ± ATR multiplier.
        Enters long when price breaks above the upper band; enters short when
        price breaks below the lower band.

    Default parameters:
        ema_period (int): EMA period for the middle band. Default 20.
        atr_period (int): ATR period. Default 14.
        atr_multiplier (float): ATR multiplier for channel width. Default 2.0.

    Signal logic:
        BUY  — close > previous upper band AND previous close <= previous upper band.
        SELL — close < previous lower band AND previous close >= previous lower band.
    """

    ema_period: int = 20
    atr_period: int = 14
    atr_multiplier: float = 2.0

    def __init__(
        self,
        name: str = "KeltnerBreakoutStrategy",
        symbol: str = "",
        ema_period: int = 20,
        atr_period: int = 14,
        atr_multiplier: float = 2.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.ema_period = ema_period
        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._closes: list[float] = []

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit Keltner breakout signals.

        Args:
            bar: OHLCV bar with .high, .low, .close attributes.
        """
        self._highs.append(float(bar.high))
        self._lows.append(float(bar.low))
        self._closes.append(float(bar.close))
        self._bar_count += 1

        min_bars = max(self.ema_period, self.atr_period) + 2
        if len(self._closes) < min_bars:
            return

        closes = np.array(self._closes)
        highs = np.array(self._highs)
        lows = np.array(self._lows)

        ema_vals = _ema_np(closes, self.ema_period)
        atr_vals = _atr_np(highs, lows, closes, self.atr_period)

        prev_upper = ema_vals[-2] + self.atr_multiplier * atr_vals[-2]
        prev_lower = ema_vals[-2] - self.atr_multiplier * atr_vals[-2]

        close = self._closes[-1]
        prev_close = self._closes[-2]

        breakout_up = close > prev_upper and prev_close <= prev_upper
        breakout_dn = close < prev_lower and prev_close >= prev_lower

        if breakout_up:
            self.enter_long()
        elif breakout_dn:
            self.enter_short()


# ---------------------------------------------------------------------------
# HeikinAshiStrategy
# ---------------------------------------------------------------------------


class HeikinAshiStrategy(BaseBacktestStrategy):
    """N consecutive Heikin-Ashi candles strategy.

    Description:
        Converts OHLCV to Heikin-Ashi candles, then counts consecutive
        bullish (HA_close > HA_open) or bearish candles. Signals when a
        streak of N candles is reached.

    Default parameters:
        consecutive_candles (int): Required streak to trigger entry. Default 3.

    Signal logic:
        BUY  — N consecutive bullish Heikin-Ashi candles.
        SELL — N consecutive bearish Heikin-Ashi candles.
    """

    consecutive_candles: int = 3

    def __init__(
        self,
        name: str = "HeikinAshiStrategy",
        symbol: str = "",
        consecutive_candles: int = 3,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.consecutive_candles = consecutive_candles
        self._opens: list[float] = []
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._closes: list[float] = []
        self._ha_open: float = 0.0
        self._ha_close: float = 0.0
        self._bullish_streak: int = 0
        self._bearish_streak: int = 0

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit Heikin-Ashi consecutive-candle signals.

        Args:
            bar: OHLCV bar with .open, .high, .low, .close attributes.
        """
        o = float(bar.open)
        h = float(bar.high)
        lo = float(bar.low)
        c = float(bar.close)
        self._bar_count += 1

        if self._ha_open == 0.0:
            ha_open = (o + c) / 2.0
            ha_close = (o + h + lo + c) / 4.0
        else:
            ha_open = (self._ha_open + self._ha_close) / 2.0
            ha_close = (o + h + lo + c) / 4.0

        is_bullish = ha_close > ha_open
        is_bearish = ha_close < ha_open

        if is_bullish:
            self._bullish_streak += 1
            self._bearish_streak = 0
        elif is_bearish:
            self._bearish_streak += 1
            self._bullish_streak = 0
        else:
            self._bullish_streak = 0
            self._bearish_streak = 0

        self._ha_open = ha_open
        self._ha_close = ha_close

        if self._bullish_streak >= self.consecutive_candles:
            self.enter_long()
        elif self._bearish_streak >= self.consecutive_candles:
            self.enter_short()
