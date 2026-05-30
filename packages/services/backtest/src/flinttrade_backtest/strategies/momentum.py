"""Momentum strategies — absorbed from AlgoTrading repo (0018–0020, 0046–0055).

Strategies:
    MomentumStrategy       — Rate of change crosses zero (0018_ROC_Impulce)
    DualMomentumStrategy   — Momentum + SMA trend filter (0020_Momentum_Percentage)
    VolumeBreakoutStrategy — Volume spike above SMA with price direction (0046_Volume_Spike)
    VWAPStrategy           — VWAP crossover (0048_VWAP_Breakout)
    OBVStrategy            — OBV rising/falling with price vs SMA (0047_OBV_Breakout)
    VWMAStrategy           — Volume Weighted MA crossover (0049_VWMA)

All strategies extend BaseBacktestStrategy and emit signals via
``enter_long`` / ``enter_short`` / ``exit_position``.
"""

from __future__ import annotations

import logging
from typing import Any


try:
    from ..base_strategy import BaseBacktestStrategy
except ImportError:
    from flinttrade_backtest.base_strategy import BaseBacktestStrategy  # type: ignore[no-redef]

logger = logging.getLogger("flinttrade.backtest.strategies.momentum")

__all__ = [
    "MomentumStrategy",
    "DualMomentumStrategy",
    "VolumeBreakoutStrategy",
    "VWAPStrategy",
    "OBVStrategy",
    "VWMAStrategy",
]


# ---------------------------------------------------------------------------
# MomentumStrategy
# ---------------------------------------------------------------------------


class MomentumStrategy(BaseBacktestStrategy):
    """Rate-of-change (momentum) zero-line crossover strategy.

    Description:
        Uses the price momentum indicator (close[i] - close[i - period]).
        Enters long when momentum crosses from negative to positive;
        enters short when it crosses from positive to negative.

    Default parameters:
        roc_period (int): Lookback period for momentum calculation. Default 12.

    Signal logic:
        BUY  — previous momentum <= 0 AND current momentum > 0.
        SELL — previous momentum >= 0 AND current momentum < 0.
    """

    roc_period: int = 12

    def __init__(
        self,
        name: str = "MomentumStrategy",
        symbol: str = "",
        roc_period: int = 12,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.roc_period = roc_period
        self._closes: list[float] = []

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit momentum zero-cross signals.

        Args:
            bar: OHLCV bar with .close attribute.
        """
        self._closes.append(float(bar.close))
        self._bar_count += 1

        if len(self._closes) < self.roc_period + 2:
            return

        mom_now = self._closes[-1] - self._closes[-1 - self.roc_period]
        mom_prev = self._closes[-2] - self._closes[-2 - self.roc_period]

        if mom_prev <= 0.0 and mom_now > 0.0:
            self.enter_long()
        elif mom_prev >= 0.0 and mom_now < 0.0:
            self.enter_short()


# ---------------------------------------------------------------------------
# DualMomentumStrategy
# ---------------------------------------------------------------------------


class DualMomentumStrategy(BaseBacktestStrategy):
    """Dual momentum strategy: absolute momentum + SMA trend filter.

    Description:
        Requires both momentum crossing zero AND price being above or below
        a Simple Moving Average for confirmation. Reduces false crossovers
        in choppy, trend-less markets.

    Default parameters:
        momentum_period (int): Momentum lookback period. Default 10.
        sma_period (int): SMA trend filter period. Default 20.

    Signal logic:
        BUY  — momentum crosses above zero AND close > SMA.
        SELL — momentum crosses below zero AND close < SMA.
    """

    momentum_period: int = 10
    sma_period: int = 20

    def __init__(
        self,
        name: str = "DualMomentumStrategy",
        symbol: str = "",
        momentum_period: int = 10,
        sma_period: int = 20,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.momentum_period = momentum_period
        self.sma_period = sma_period
        self._closes: list[float] = []

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit dual momentum signals.

        Args:
            bar: OHLCV bar with .close attribute.
        """
        self._closes.append(float(bar.close))
        self._bar_count += 1

        min_bars = max(self.momentum_period, self.sma_period) + 2
        if len(self._closes) < min_bars:
            return

        sma_vals = self.indicators.sma(self._closes, self.sma_period)
        sma_now = sma_vals[-1]
        if sma_now == 0.0:
            return

        mom_now = self._closes[-1] - self._closes[-1 - self.momentum_period]
        mom_prev = self._closes[-2] - self._closes[-2 - self.momentum_period]
        close = self._closes[-1]

        if mom_prev <= 0.0 and mom_now > 0.0 and close > sma_now:
            self.enter_long()
        elif mom_prev >= 0.0 and mom_now < 0.0 and close < sma_now:
            self.enter_short()


# ---------------------------------------------------------------------------
# VolumeBreakoutStrategy
# ---------------------------------------------------------------------------


class VolumeBreakoutStrategy(BaseBacktestStrategy):
    """Volume spike breakout strategy.

    Description:
        Compares current volume to the previous bar's volume. When volume
        spikes above the previous volume by a multiplier threshold, enters
        in the direction price is relative to a SMA. Exits when volume
        returns below average (volume contraction).

    Default parameters:
        ma_period (int): SMA trend period for price direction. Default 20.
        volume_spike_multiplier (float): Min ratio current/previous volume. Default 2.0.

    Signal logic:
        BUY  — volume ratio >= multiplier AND close > SMA.
        SELL — volume ratio >= multiplier AND close < SMA.
        EXIT — volume decreases vs previous bar.
    """

    ma_period: int = 20
    volume_spike_multiplier: float = 2.0

    def __init__(
        self,
        name: str = "VolumeBreakoutStrategy",
        symbol: str = "",
        ma_period: int = 20,
        volume_spike_multiplier: float = 2.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.ma_period = ma_period
        self.volume_spike_multiplier = volume_spike_multiplier
        self._closes: list[float] = []
        self._volumes: list[float] = []
        self._in_position: bool = False

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit volume spike signals.

        Args:
            bar: OHLCV bar with .close and .volume attributes.
        """
        self._closes.append(float(bar.close))
        self._volumes.append(float(bar.volume))
        self._bar_count += 1

        if len(self._closes) < self.ma_period + 2:
            return

        sma_vals = self.indicators.sma(self._closes, self.ma_period)
        sma_now = sma_vals[-1]
        close = self._closes[-1]
        vol_now = self._volumes[-1]
        vol_prev = self._volumes[-2]

        if vol_prev == 0.0:
            return

        vol_ratio = vol_now / vol_prev
        spike = vol_ratio >= self.volume_spike_multiplier

        # Exit on volume contraction
        if self._in_position and vol_now < vol_prev:
            self.exit_position()
            self._in_position = False
            return

        # Entry on volume spike
        if not self._in_position and spike:
            if close > sma_now:
                self.enter_long()
                self._in_position = True
            elif close < sma_now:
                self.enter_short()
                self._in_position = True


# ---------------------------------------------------------------------------
# VWAPStrategy
# ---------------------------------------------------------------------------


class VWAPStrategy(BaseBacktestStrategy):
    """VWAP crossover strategy.

    Description:
        Computes a running Volume Weighted Average Price (VWAP).
        Enters long when price breaks above VWAP; enters short when price
        breaks below VWAP. Exits when price reverts across VWAP.

    Default parameters:
        No configurable parameters. VWAP is recalculated from all available bars.

    Signal logic:
        BUY  — previous close <= previous VWAP AND current close > VWAP.
        SELL — previous close >= previous VWAP AND current close < VWAP.
        EXIT long — close < VWAP.
        EXIT short — close > VWAP.
    """

    def __init__(
        self,
        name: str = "VWAPStrategy",
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self._closes: list[float] = []
        self._volumes: list[float] = []
        self._in_long: bool = False
        self._in_short: bool = False

    def _vwap(self, closes: list[float], volumes: list[float]) -> float:
        """Compute running VWAP.

        Args:
            closes: Close prices.
            volumes: Bar volumes.

        Returns:
            VWAP value.
        """
        total_vol = sum(volumes)
        if total_vol == 0:
            return closes[-1] if closes else 0.0
        return sum(c * v for c, v in zip(closes, volumes)) / total_vol

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit VWAP crossover signals.

        Args:
            bar: OHLCV bar with .close and .volume attributes.
        """
        self._closes.append(float(bar.close))
        self._volumes.append(float(bar.volume))
        self._bar_count += 1

        if len(self._closes) < 3:
            return

        vwap_now = self._vwap(self._closes, self._volumes)
        vwap_prev = self._vwap(self._closes[:-1], self._volumes[:-1])
        close = self._closes[-1]
        prev_close = self._closes[-2]

        # Exit logic
        if self._in_long and close < vwap_now:
            self.exit_position()
            self._in_long = False
            return
        if self._in_short and close > vwap_now:
            self.exit_position()
            self._in_short = False
            return

        # Entry logic
        if not self._in_long and not self._in_short:
            breakout_up = prev_close <= vwap_prev and close > vwap_now
            breakout_dn = prev_close >= vwap_prev and close < vwap_now
            if breakout_up:
                self.enter_long()
                self._in_long = True
            elif breakout_dn:
                self.enter_short()
                self._in_short = True


# ---------------------------------------------------------------------------
# OBVStrategy
# ---------------------------------------------------------------------------


class OBVStrategy(BaseBacktestStrategy):
    """On-Balance Volume (OBV) breakout strategy.

    Description:
        Tracks OBV direction (rising vs. falling) and combines it with price
        position relative to an SMA. Enters only when OBV direction and price
        direction agree. Exits when OBV reverses.

    Default parameters:
        ma_period (int): SMA period for price trend. Default 20.

    Signal logic:
        BUY  — OBV rising AND close > SMA.
        SELL — OBV falling AND close < SMA.
        EXIT long — OBV falls.
        EXIT short — OBV rises.
    """

    ma_period: int = 20

    def __init__(
        self,
        name: str = "OBVStrategy",
        symbol: str = "",
        ma_period: int = 20,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.ma_period = ma_period
        self._closes: list[float] = []
        self._volumes: list[float] = []
        self._obv: float = 0.0
        self._prev_obv: float = 0.0
        self._in_long: bool = False
        self._in_short: bool = False

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit OBV directional signals.

        Args:
            bar: OHLCV bar with .close and .volume attributes.
        """
        close = float(bar.close)
        vol = float(bar.volume)
        self._bar_count += 1

        prev_obv = self._obv
        if self._closes:
            if close > self._closes[-1]:
                self._obv += vol
            elif close < self._closes[-1]:
                self._obv -= vol

        self._closes.append(close)
        self._volumes.append(vol)

        if len(self._closes) < self.ma_period + 2:
            self._prev_obv = prev_obv
            return

        sma_vals = self.indicators.sma(self._closes, self.ma_period)
        sma_now = sma_vals[-1]
        obv_rising = self._obv > self._prev_obv

        # Exit logic
        if self._in_long and not obv_rising:
            self.exit_position()
            self._in_long = False
        elif self._in_short and obv_rising:
            self.exit_position()
            self._in_short = False

        # Entry logic
        if not self._in_long and not self._in_short:
            if obv_rising and close > sma_now:
                self.enter_long()
                self._in_long = True
            elif not obv_rising and close < sma_now:
                self.enter_short()
                self._in_short = True

        self._prev_obv = prev_obv


# ---------------------------------------------------------------------------
# VWMAStrategy
# ---------------------------------------------------------------------------


class VWMAStrategy(BaseBacktestStrategy):
    """Volume Weighted Moving Average (VWMA) crossover strategy.

    Description:
        Computes a VWMA (price × volume / sum_of_volumes over a period).
        Enters long when price crosses above VWMA; enters short when price
        crosses below VWMA.

    Default parameters:
        vwma_period (int): VWMA lookback period. Default 14.

    Signal logic:
        BUY  — previous close <= previous VWMA AND current close > current VWMA.
        SELL — previous close >= previous VWMA AND current close < current VWMA.
    """

    vwma_period: int = 14

    def __init__(
        self,
        name: str = "VWMAStrategy",
        symbol: str = "",
        vwma_period: int = 14,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, symbol=symbol, **kwargs)
        self.vwma_period = vwma_period
        self._closes: list[float] = []
        self._volumes: list[float] = []

    def _vwma(self, closes: list[float], volumes: list[float]) -> float:
        """Compute VWMA from a window of closes and volumes.

        Args:
            closes: Close prices (window).
            volumes: Volumes (window).

        Returns:
            VWMA value.
        """
        total_vol = sum(volumes)
        if total_vol == 0:
            return closes[-1] if closes else 0.0
        return sum(c * v for c, v in zip(closes, volumes)) / total_vol

    def on_bar(self, bar: Any) -> None:
        """Process OHLCV bar and emit VWMA crossover signals.

        Args:
            bar: OHLCV bar with .close and .volume attributes.
        """
        self._closes.append(float(bar.close))
        self._volumes.append(float(bar.volume))
        self._bar_count += 1

        if len(self._closes) < self.vwma_period + 1:
            return

        window_c = self._closes[-self.vwma_period:]
        window_v = self._volumes[-self.vwma_period:]
        prev_window_c = self._closes[-self.vwma_period - 1:-1]
        prev_window_v = self._volumes[-self.vwma_period - 1:-1]

        vwma_now = self._vwma(window_c, window_v)
        vwma_prev = self._vwma(prev_window_c, prev_window_v)
        close = self._closes[-1]
        prev_close = self._closes[-2]

        cross_up = prev_close <= vwma_prev and close > vwma_now
        cross_dn = prev_close >= vwma_prev and close < vwma_now

        if cross_up:
            self.enter_long()
        elif cross_dn:
            self.enter_short()
