"""Mean-reversion strategies — adapted from AlgoTrading repo (0016–0031, 0058).

Strategies:
    RSIStrategy              — RSI crossover from oversold/overbought zones (0058_RSI_Overbought_Oversold)
    BollingerBandStrategy    — BB mean reversion: enter at bands, exit at middle (0027_Bollinger_Reversion)
    StochasticStrategy       — Stochastic %K/%D crossover in oversold/overbought zones (0025)
    CCIStrategy              — CCI breakout above +100 / below -100 (0019_CCI_Breakout)
    WilliamsRStrategy        — Williams %R crossover from oversold/overbought (0017_Williams_R)
    KeltnerChannelStrategy   — Keltner channel mean reversion: buy below lower, sell above upper (0031)

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
    from flinttrade_backtest.base_strategy import BaseBacktestStrategy  # type: ignore[no-redef]

logger = logging.getLogger("flinttrade.backtest.strategies.mean_reversion")

__all__ = [
    "RSIStrategy",
    "BollingerBandStrategy",
    "StochasticStrategy",
    "CCIStrategy",
    "WilliamsRStrategy",
    "KeltnerChannelStrategy",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ema_np(arr: np.ndarray, period: int) -> np.ndarray:
    """Exponential Moving Average using 2/(period+1) weighting."""
    k = 2.0 / (period + 1)
    result = np.empty_like(arr)
    result[0] = arr[0]
    for i in range(1, len(arr)):
        result[i] = arr[i] * k + result[i - 1] * (1.0 - k)
    return result


def _rsi(closes: list[float], period: int) -> float:
    """Compute current RSI value from a close price series.

    Args:
        closes: Close price series (newest last).
        period: RSI period.

    Returns:
        Current RSI value in [0, 100].
    """
    if len(closes) < period + 1:
        return 50.0
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        gains.append(max(0.0, diff))
        losses.append(max(0.0, -diff))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    for i in range(period, len(closes) - 1):
        diff = closes[i + 1] - closes[i]
        avg_gain = (avg_gain * (period - 1) + max(0.0, diff)) / period
        avg_loss = (avg_loss * (period - 1) + max(0.0, -diff)) / period
    if avg_loss == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def _rsi_prev(closes: list[float], period: int) -> float:
    """Compute RSI for the second-to-last bar."""
    return _rsi(closes[:-1], period)


# ---------------------------------------------------------------------------
# RSIStrategy
# ---------------------------------------------------------------------------


class RSIStrategy(BaseBacktestStrategy):
    """RSI oversold / overbought mean reversion strategy.

    Description:
        Buys when RSI crosses from oversold (< oversold_level) into neutral
        territory. Sells/shorts when RSI crosses from overbought (> overbought_level)
        into neutral territory.

    Default parameters:
        rsi_period (int): RSI calculation period. Default 14.
        oversold_level (float): RSI level below which market is oversold. Default 30.0.
        overbought_level (float): RSI level above which market is overbought. Default 70.0.

    Signal logic:
        BUY  — previous RSI < oversold_level AND current RSI >= oversold_level.
        SELL — previous RSI > overbought_level AND current RSI <= overbought_level.
    """

    rsi_period: int = 14
    oversold_level: float = 30.0
    overbought_level: float = 70.0

    def __init__(
        self,
        name: str = "RSIStrategy",
        symbol: str = "",
        rsi_period: int = 14,
        oversold_level: float = 30.0,
        overbought_level: float = 70.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.rsi_period = rsi_period
        self.oversold_level = oversold_level
        self.overbought_level = overbought_level
        self._closes: list[float] = []

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit RSI crossover signals.

        Args:
            bar: OHLCV bar with .close attribute.
        """
        self._closes.append(float(bar.close))
        self._bar_count += 1

        if len(self._closes) < self.rsi_period + 2:
            return

        rsi_now = _rsi(self._closes, self.rsi_period)
        rsi_prev = _rsi_prev(self._closes, self.rsi_period)

        if rsi_prev < self.oversold_level and rsi_now >= self.oversold_level:
            self.enter_long()
        elif rsi_prev > self.overbought_level and rsi_now <= self.overbought_level:
            self.enter_short()


# ---------------------------------------------------------------------------
# BollingerBandStrategy
# ---------------------------------------------------------------------------


class BollingerBandStrategy(BaseBacktestStrategy):
    """Bollinger Band mean reversion strategy.

    Description:
        Enters when price touches or pierces the outer bands, then exits
        when price returns to the middle band (SMA). Also exits on time-
        based forced close after max_hold_bars.

    Default parameters:
        period (int): BB calculation period. Default 20.
        num_std (float): Standard deviations for bands. Default 2.0.
        max_hold_bars (int): Maximum bars to hold position. Default 50.

    Signal logic:
        BUY  — close < lower band (no open position).
        SELL — close > upper band (no open position).
        EXIT — close crosses back to middle band, or max_hold_bars reached.
    """

    period: int = 20
    num_std: float = 2.0
    max_hold_bars: int = 50

    def __init__(
        self,
        name: str = "BollingerBandStrategy",
        symbol: str = "",
        period: int = 20,
        num_std: float = 2.0,
        max_hold_bars: int = 50,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.period = period
        self.num_std = num_std
        self.max_hold_bars = max_hold_bars
        self._closes: list[float] = []
        self._hold_bars: int = 0
        self._in_long: bool = False
        self._in_short: bool = False

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit Bollinger Band mean reversion signals.

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
        close = self._closes[-1]
        mid = middle[-1]
        up = upper[-1]
        lo = lower[-1]

        if up == 0.0 or lo == 0.0:
            return

        # Track hold duration
        if self._in_long or self._in_short:
            self._hold_bars += 1

        # Exit logic
        if self._in_long and (close >= mid or self._hold_bars >= self.max_hold_bars):
            self.exit_position()
            self._in_long = False
            self._hold_bars = 0
            return
        if self._in_short and (close <= mid or self._hold_bars >= self.max_hold_bars):
            self.exit_position()
            self._in_short = False
            self._hold_bars = 0
            return

        # Entry logic
        if not self._in_long and not self._in_short:
            if close < lo:
                self.enter_long()
                self._in_long = True
                self._hold_bars = 0
            elif close > up:
                self.enter_short()
                self._in_short = True
                self._hold_bars = 0


# ---------------------------------------------------------------------------
# StochasticStrategy
# ---------------------------------------------------------------------------


class StochasticStrategy(BaseBacktestStrategy):
    """Stochastic %K/%D crossover strategy.

    Description:
        Computes Stochastic Oscillator %K (fast) and %D (smoothed %K).
        Buys when %K crosses above %D in oversold territory (< 20);
        sells when %K crosses below %D in overbought territory (> 80).

    Default parameters:
        k_period (int): %K lookback period. Default 14.
        d_period (int): %D smoothing period. Default 3.

    Signal logic:
        BUY  — %K crosses above %D AND %K < 20.
        SELL — %K crosses below %D AND %K > 80.
    """

    k_period: int = 14
    d_period: int = 3

    def __init__(
        self,
        name: str = "StochasticStrategy",
        symbol: str = "",
        k_period: int = 14,
        d_period: int = 3,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.k_period = k_period
        self.d_period = d_period
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._closes: list[float] = []

    def _stoch_k(self, closes: list[float], highs: list[float], lows: list[float]) -> list[float]:
        """Compute %K series.

        Args:
            closes: Close prices.
            highs: High prices.
            lows: Low prices.

        Returns:
            %K series.
        """
        n = len(closes)
        k_vals: list[float] = [50.0] * n
        for i in range(self.k_period - 1, n):
            h = max(highs[i - self.k_period + 1:i + 1])
            lo = min(lows[i - self.k_period + 1:i + 1])
            rng = h - lo
            k_vals[i] = (closes[i] - lo) / rng * 100.0 if rng != 0 else 50.0
        return k_vals

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit Stochastic crossover signals.

        Args:
            bar: OHLCV bar with .high, .low, .close attributes.
        """
        self._highs.append(float(bar.high))
        self._lows.append(float(bar.low))
        self._closes.append(float(bar.close))
        self._bar_count += 1

        min_bars = self.k_period + self.d_period + 1
        if len(self._closes) < min_bars:
            return

        k_series = self._stoch_k(self._closes, self._highs, self._lows)
        # %D = SMA of %K
        d_series = self.indicators.sma(k_series, self.d_period)

        k_now = k_series[-1]
        k_prev = k_series[-2]
        d_now = d_series[-1]
        d_prev = d_series[-2]

        cross_up = k_prev <= d_prev and k_now > d_now and k_now < 20.0
        cross_dn = k_prev >= d_prev and k_now < d_now and k_now > 80.0

        if cross_up:
            self.enter_long()
        elif cross_dn:
            self.enter_short()


# ---------------------------------------------------------------------------
# CCIStrategy
# ---------------------------------------------------------------------------


class CCIStrategy(BaseBacktestStrategy):
    """CCI (Commodity Channel Index) breakout strategy.

    Description:
        Buys when CCI crosses above +100 (bullish breakout from mean);
        sells when CCI crosses below -100 (bearish breakout from mean).

    Default parameters:
        cci_period (int): CCI calculation period. Default 20.

    Signal logic:
        BUY  — previous CCI <= +100 AND current CCI > +100.
        SELL — previous CCI >= -100 AND current CCI < -100.
    """

    cci_period: int = 20

    def __init__(
        self,
        name: str = "CCIStrategy",
        symbol: str = "",
        cci_period: int = 20,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.cci_period = cci_period
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._closes: list[float] = []

    def _cci(self, highs: list[float], lows: list[float], closes: list[float]) -> float:
        """Compute CCI for the most recent bar.

        Args:
            highs: High prices.
            lows: Low prices.
            closes: Close prices.

        Returns:
            CCI value.
        """
        n = len(closes)
        if n < self.cci_period:
            return 0.0
        window_h = highs[-self.cci_period:]
        window_l = lows[-self.cci_period:]
        window_c = closes[-self.cci_period:]
        typical = [(window_h[i] + window_l[i] + window_c[i]) / 3.0 for i in range(self.cci_period)]
        mean_tp = sum(typical) / self.cci_period
        mean_dev = sum(abs(tp - mean_tp) for tp in typical) / self.cci_period
        if mean_dev == 0:
            return 0.0
        return (typical[-1] - mean_tp) / (0.015 * mean_dev)

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit CCI breakout signals.

        Args:
            bar: OHLCV bar with .high, .low, .close attributes.
        """
        self._highs.append(float(bar.high))
        self._lows.append(float(bar.low))
        self._closes.append(float(bar.close))
        self._bar_count += 1

        if len(self._closes) < self.cci_period + 1:
            return

        cci_now = self._cci(self._highs, self._lows, self._closes)
        cci_prev = self._cci(self._highs[:-1], self._lows[:-1], self._closes[:-1])

        if cci_prev <= 100.0 and cci_now > 100.0:
            self.enter_long()
        elif cci_prev >= -100.0 and cci_now < -100.0:
            self.enter_short()


# ---------------------------------------------------------------------------
# WilliamsRStrategy
# ---------------------------------------------------------------------------


class WilliamsRStrategy(BaseBacktestStrategy):
    """Williams %R mean reversion strategy.

    Description:
        Williams %R oscillates between -100 (oversold) and 0 (overbought).
        Buys when %R crosses from below -80 to above -80 (oversold exit);
        sells when %R crosses from above -20 to below -20 (overbought exit).

    Default parameters:
        period (int): Lookback period for highest high / lowest low. Default 14.

    Signal logic:
        BUY  — previous %R < -80 AND current %R >= -80.
        SELL — previous %R > -20 AND current %R <= -20.
    """

    period: int = 14

    def __init__(
        self,
        name: str = "WilliamsRStrategy",
        symbol: str = "",
        period: int = 14,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.period = period
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._closes: list[float] = []

    def _wr(self, highs: list[float], lows: list[float], closes: list[float]) -> float:
        """Compute Williams %R for the most recent bar.

        Args:
            highs: High prices.
            lows: Low prices.
            closes: Close prices.

        Returns:
            Williams %R value in [-100, 0].
        """
        if len(closes) < self.period:
            return -50.0
        h = max(highs[-self.period:])
        lo = min(lows[-self.period:])
        rng = h - lo
        if rng == 0:
            return -50.0
        return (h - closes[-1]) / rng * -100.0

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit Williams %R crossover signals.

        Args:
            bar: OHLCV bar with .high, .low, .close attributes.
        """
        self._highs.append(float(bar.high))
        self._lows.append(float(bar.low))
        self._closes.append(float(bar.close))
        self._bar_count += 1

        if len(self._closes) < self.period + 1:
            return

        wr_now = self._wr(self._highs, self._lows, self._closes)
        wr_prev = self._wr(self._highs[:-1], self._lows[:-1], self._closes[:-1])

        if wr_prev < -80.0 and wr_now >= -80.0:
            self.enter_long()
        elif wr_prev > -20.0 and wr_now <= -20.0:
            self.enter_short()


# ---------------------------------------------------------------------------
# KeltnerChannelStrategy
# ---------------------------------------------------------------------------


class KeltnerChannelStrategy(BaseBacktestStrategy):
    """Keltner channel mean reversion strategy.

    Description:
        Constructs a Keltner Channel (EMA middle ± ATR multiplier).
        Enters long when price falls below the lower band; enters short when
        price rises above the upper band. Exits when price returns to the EMA.

    Default parameters:
        ema_period (int): EMA period for the middle band. Default 20.
        atr_period (int): ATR period. Default 14.
        atr_multiplier (float): ATR multiplier for channel width. Default 2.0.

    Signal logic:
        BUY  — close < lower band (no position).
        SELL — close > upper band (no position).
        EXIT long — close > middle (EMA).
        EXIT short — close < middle (EMA).
    """

    ema_period: int = 20
    atr_period: int = 14
    atr_multiplier: float = 2.0

    def __init__(
        self,
        name: str = "KeltnerChannelStrategy",
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
        self._in_long: bool = False
        self._in_short: bool = False

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit Keltner Channel reversion signals.

        Args:
            bar: OHLCV bar with .high, .low, .close attributes.
        """
        self._highs.append(float(bar.high))
        self._lows.append(float(bar.low))
        self._closes.append(float(bar.close))
        self._bar_count += 1

        min_bars = max(self.ema_period, self.atr_period) + 1
        if len(self._closes) < min_bars:
            return

        closes = np.array(self._closes)
        highs = np.array(self._highs)
        lows = np.array(self._lows)

        # EMA middle
        k = 2.0 / (self.ema_period + 1)
        ema_val = closes[0]
        for v in closes:
            ema_val = v * k + ema_val * (1.0 - k)

        # ATR
        n = len(closes)
        tr = np.zeros(n)
        tr[0] = highs[0] - lows[0]
        for i in range(1, n):
            tr[i] = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        if n < self.atr_period:
            return
        atr_val = float(np.mean(tr[-self.atr_period:]))

        upper = ema_val + self.atr_multiplier * atr_val
        lower = ema_val - self.atr_multiplier * atr_val
        close = self._closes[-1]

        # Exit logic
        if self._in_long and close > ema_val:
            self.exit_position()
            self._in_long = False
            return
        if self._in_short and close < ema_val:
            self.exit_position()
            self._in_short = False
            return

        # Entry logic
        if not self._in_long and not self._in_short:
            if close < lower:
                self.enter_long()
                self._in_long = True
            elif close > upper:
                self.enter_short()
                self._in_short = True
