"""Market regime detector using ADX, Bollinger Bands, and ATR.

Adapted from LLM-TradeBot's regime_detector_agent pattern:
combines directional-strength (ADX), volatility-spread (BB width),
and volatility-trend (ATR slope) into 6 mutually-exclusive regime
states that downstream strategies and the AI advisor use to adapt
their behaviour.

Six Regime States
-----------------
TRENDING_UP
    ADX > adx_threshold AND price above middle BB AND ATR not expanding.
TRENDING_DOWN
    ADX > adx_threshold AND price below middle BB AND ATR not expanding.
RANGING
    ADX < adx_threshold AND BB width below bb_width_threshold.
VOLATILE_DIRECTIONAL
    ADX > adx_threshold AND ATR rising (expanding volatility WITH direction).
VOLATILE_DIRECTIONLESS
    ADX < adx_threshold AND BB width > bb_width_threshold.
    Key regime: pre-expiry manipulation zone — avoid directional bets.
LOW_VOLATILITY
    ADX < adx_threshold AND BB width below a tight threshold
    AND ATR declining.  Anticipate compression before breakout.

Usage::

    from flinttrade_ai.regime_detector import detect_regime, RegimeState

    bars = [{"high": ..., "low": ..., "close": ...}, ...]
    state = detect_regime(
        high=[b["high"] for b in bars],
        low=[b["low"] for b in bars],
        close=[b["close"] for b in bars],
    )
    print(state)           # e.g. RegimeState.VOLATILE_DIRECTIONLESS
    print(state.label)     # "VOLATILE_DIRECTIONLESS"
    print(state.is_tradeable)  # False — avoid directional trades
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from enum import StrEnum
from typing import Sequence


# ---------------------------------------------------------------------------
# Regime state enum
# ---------------------------------------------------------------------------


class RegimeState(StrEnum):
    """Six mutually-exclusive market regime states.

    Attributes:
        TRENDING_UP: Strong directional uptrend, ADX-confirmed.
        TRENDING_DOWN: Strong directional downtrend, ADX-confirmed.
        RANGING: Low ADX, tight BB — no clear direction or volatility.
        VOLATILE_DIRECTIONAL: High ADX + expanding ATR — trend in motion
            with increasing volatility (breakout or impulse move).
        VOLATILE_DIRECTIONLESS: Low ADX + wide BB — choppy, expanding
            volatility with no directional conviction.  Pre-expiry
            manipulation zone; directional strategies should stand aside.
        LOW_VOLATILITY: Very tight BB + declining ATR — compression phase
            before a potential breakout.
    """

    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    VOLATILE_DIRECTIONAL = "VOLATILE_DIRECTIONAL"
    VOLATILE_DIRECTIONLESS = "VOLATILE_DIRECTIONLESS"
    LOW_VOLATILITY = "LOW_VOLATILITY"

    @property
    def label(self) -> str:
        """Human-readable label identical to the enum value."""
        return self.value

    @property
    def is_tradeable(self) -> bool:
        """Return True when directional strategies are appropriate.

        VOLATILE_DIRECTIONLESS and LOW_VOLATILITY are flagged as
        non-tradeable to prevent entering during chop or compression.
        """
        return self not in {
            RegimeState.VOLATILE_DIRECTIONLESS,
            RegimeState.LOW_VOLATILITY,
        }

    @property
    def is_trending(self) -> bool:
        """Return True when a clear directional trend is confirmed."""
        return self in {RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN}

    @property
    def is_volatile(self) -> bool:
        """Return True when volatility is elevated."""
        return self in {
            RegimeState.VOLATILE_DIRECTIONAL,
            RegimeState.VOLATILE_DIRECTIONLESS,
        }


# ---------------------------------------------------------------------------
# Indicator helpers (pure Python, no TA-Lib dependency)
# ---------------------------------------------------------------------------


def _ema(values: list[float], period: int) -> list[float]:
    """Compute exponential moving average.

    Args:
        values: Input price series.
        period: EMA look-back period.

    Returns:
        EMA series aligned to ``values`` (first ``period-1`` values are
        the simple average of the first ``period`` samples).
    """
    if len(values) < period:
        return [float("nan")] * len(values)
    k = 2.0 / (period + 1)
    result = [float("nan")] * len(values)
    # Seed with simple average of the first ``period`` values
    seed = sum(values[:period]) / period
    result[period - 1] = seed
    for i in range(period, len(values)):
        result[i] = values[i] * k + result[i - 1] * (1 - k)
    return result


def _sma(values: list[float], period: int) -> list[float]:
    """Compute simple moving average.

    Args:
        values: Input price series.
        period: Look-back period.

    Returns:
        SMA series (NaN for the first ``period-1`` positions).
    """
    result = [float("nan")] * len(values)
    for i in range(period - 1, len(values)):
        result[i] = sum(values[i - period + 1: i + 1]) / period
    return result


def _true_range(
    high: list[float],
    low: list[float],
    close: list[float],
) -> list[float]:
    """Compute true range for each bar.

    True range = max(H-L, |H-prev_C|, |L-prev_C|)

    Args:
        high: High prices.
        low: Low prices.
        close: Close prices.

    Returns:
        True range series (same length; first element = H[0] - L[0]).
    """
    tr = [high[0] - low[0]]
    for i in range(1, len(high)):
        hl = high[i] - low[i]
        hpc = abs(high[i] - close[i - 1])
        lpc = abs(low[i] - close[i - 1])
        tr.append(max(hl, hpc, lpc))
    return tr


def _atr(
    high: list[float],
    low: list[float],
    close: list[float],
    period: int = 14,
) -> list[float]:
    """Compute Average True Range (Wilder smoothed).

    Args:
        high: High prices.
        low: Low prices.
        close: Close prices.
        period: ATR period.

    Returns:
        ATR series aligned to inputs.
    """
    tr = _true_range(high, low, close)
    n = len(tr)
    atr: list[float] = [float("nan")] * n

    if n < period:
        return atr

    # First ATR = simple mean of first ``period`` TRs
    atr[period - 1] = sum(tr[:period]) / period
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    return atr


def _directional_movement(
    high: list[float],
    low: list[float],
    close: list[float],
    period: int = 14,
) -> tuple[list[float], list[float], list[float]]:
    """Compute Wilder's +DI, -DI, and ADX.

    Args:
        high: High prices.
        low: Low prices.
        close: Close prices.
        period: ADX/DI smoothing period.

    Returns:
        Tuple ``(plus_di, minus_di, adx)`` — each aligned to inputs.
    """
    n = len(close)
    nan = float("nan")
    plus_di = [nan] * n
    minus_di = [nan] * n
    adx = [nan] * n

    if n < period * 2:
        return plus_di, minus_di, adx

    tr = _true_range(high, low, close)

    plus_dm: list[float] = [0.0] * n
    minus_dm: list[float] = [0.0] * n

    for i in range(1, n):
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move

    # Wilder-smooth TR, +DM, -DM
    def _wilder_smooth(series: list[float], p: int) -> list[float]:
        result = [0.0] * n
        result[p] = sum(series[1: p + 1])
        for i in range(p + 1, n):
            result[i] = result[i - 1] - result[i - 1] / p + series[i]
        return result

    smooth_tr = _wilder_smooth(tr, period)
    smooth_plus = _wilder_smooth(plus_dm, period)
    smooth_minus = _wilder_smooth(minus_dm, period)

    dx_series: list[float] = [nan] * n
    for i in range(period, n):
        if smooth_tr[i] == 0:
            continue
        pdi = 100.0 * smooth_plus[i] / smooth_tr[i]
        mdi = 100.0 * smooth_minus[i] / smooth_tr[i]
        plus_di[i] = pdi
        minus_di[i] = mdi
        di_sum = pdi + mdi
        if di_sum > 0:
            dx_series[i] = 100.0 * abs(pdi - mdi) / di_sum

    # ADX = Wilder-smoothed DX
    # Seed at period * 2 (first valid DX at period, need period more for ADX)
    start_adx = period * 2
    if start_adx >= n:
        return plus_di, minus_di, adx

    valid_dx = [x for x in dx_series[period: start_adx] if not math.isnan(x)]
    if not valid_dx:
        return plus_di, minus_di, adx

    adx[start_adx - 1] = sum(valid_dx) / len(valid_dx)
    for i in range(start_adx, n):
        if math.isnan(dx_series[i]):
            adx[i] = adx[i - 1]
        else:
            adx[i] = (adx[i - 1] * (period - 1) + dx_series[i]) / period

    return plus_di, minus_di, adx


def _bollinger_bands(
    close: list[float],
    period: int = 20,
    num_std: float = 2.0,
) -> tuple[list[float], list[float], list[float]]:
    """Compute Bollinger Bands (upper, middle, lower).

    Args:
        close: Close prices.
        period: SMA period.
        num_std: Standard deviation multiplier.

    Returns:
        Tuple ``(upper, middle, lower)`` aligned to ``close``.
    """
    n = len(close)
    nan = float("nan")
    upper = [nan] * n
    middle = [nan] * n
    lower = [nan] * n

    for i in range(period - 1, n):
        window = close[i - period + 1: i + 1]
        mid = sum(window) / period
        std = statistics.stdev(window) if len(window) > 1 else 0.0
        middle[i] = mid
        upper[i] = mid + num_std * std
        lower[i] = mid - num_std * std

    return upper, middle, lower


# ---------------------------------------------------------------------------
# Regime detection result
# ---------------------------------------------------------------------------


@dataclass
class RegimeResult:
    """Detailed output from a single regime detection call.

    Attributes:
        state: Detected ``RegimeState``.
        adx: ADX value at the latest bar.
        bb_width: Bollinger Band width (normalised as (upper-lower)/middle).
        atr_current: ATR value at the latest bar.
        atr_slope: ATR trend over the last 5 bars (positive = expanding).
        plus_di: +DI value at the latest bar.
        minus_di: -DI value at the latest bar.
        close: Latest close price.
        n_bars: Number of input bars used.
    """

    state: RegimeState
    adx: float = float("nan")
    bb_width: float = float("nan")
    atr_current: float = float("nan")
    atr_slope: float = float("nan")
    plus_di: float = float("nan")
    minus_di: float = float("nan")
    close: float = float("nan")
    n_bars: int = 0

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable dict of all fields."""
        return {
            "state": self.state.value,
            "adx": self.adx,
            "bb_width": self.bb_width,
            "atr_current": self.atr_current,
            "atr_slope": self.atr_slope,
            "plus_di": self.plus_di,
            "minus_di": self.minus_di,
            "close": self.close,
            "n_bars": self.n_bars,
        }


# ---------------------------------------------------------------------------
# Regime -> strategy selection (closes the loop on detection)
# ---------------------------------------------------------------------------


@dataclass
class StrategySuggestion:
    """A regime-appropriate strategy recommendation.

    Attributes:
        strategy: Short machine id (e.g. ``"momentum_long"``) a strategy runner
            can switch on.
        label: Human-readable display name for the UI.
        rationale: One-line explanation of why the style suits the regime.
    """

    strategy: str
    label: str
    rationale: str

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-serialisable dict."""
        return {"strategy": self.strategy, "label": self.label, "rationale": self.rationale}


_REGIME_STRATEGY: dict[RegimeState, StrategySuggestion] = {
    RegimeState.TRENDING_UP: StrategySuggestion(
        "momentum_long",
        "Momentum (long)",
        "Strong ADX-confirmed uptrend — ride direction with trend-following or breakout longs; avoid fading.",
    ),
    RegimeState.TRENDING_DOWN: StrategySuggestion(
        "momentum_short",
        "Momentum (short)",
        "Strong ADX-confirmed downtrend — trend-following shorts or protective puts; avoid bottom-picking.",
    ),
    RegimeState.RANGING: StrategySuggestion(
        "mean_reversion",
        "Mean reversion",
        "Low ADX in a tight range — fade the edges (short strangles, range scalps); trend entries will whipsaw.",
    ),
    RegimeState.VOLATILE_DIRECTIONAL: StrategySuggestion(
        "trend_pullback",
        "Trend pullback",
        "Trend in motion with expanding ATR — enter on pullbacks with wide stops; size down for the volatility.",
    ),
    RegimeState.VOLATILE_DIRECTIONLESS: StrategySuggestion(
        "long_volatility",
        "Stand aside / long volatility",
        "Choppy with expanding bands and no direction — stand aside or buy volatility (long straddle); directional bets bleed.",
    ),
    RegimeState.LOW_VOLATILITY: StrategySuggestion(
        "theta",
        "Theta / premium selling",
        "Compressed volatility — collect theta (short straddles, iron condors); expect an eventual volatility expansion.",
    ),
}


def select_strategy_for_regime(state: RegimeState) -> StrategySuggestion:
    """Map a detected market regime to a regime-appropriate strategy style.

    Closes the loop on regime detection: the detector classifies the market and
    this selector recommends the strategy style that historically suits that
    regime — for the AI Regime panel and any regime-aware strategy runner. Falls
    back to a stand-aside default for an unrecognised state.

    Args:
        state: The detected :class:`RegimeState`.

    Returns:
        A :class:`StrategySuggestion` for the regime.
    """
    return _REGIME_STRATEGY.get(
        state,
        StrategySuggestion(
            "stand_aside",
            "Stand aside",
            "Unclassified regime — prefer to stand aside until it resolves.",
        ),
    )


# ---------------------------------------------------------------------------
# Primary public API
# ---------------------------------------------------------------------------


def detect_regime(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    adx_period: int = 14,
    bb_period: int = 20,
    atr_period: int = 14,
    adx_threshold: float = 25.0,
    bb_width_threshold: float = 0.04,
    low_vol_bb_threshold: float = 0.02,
    atr_slope_window: int = 5,
) -> RegimeState:
    """Detect the current market regime from price series.

    Combines ADX (directional strength), Bollinger Band width (volatility
    spread), and ATR slope (volatility trend) into one of six regime
    states.  Inspired by LLM-TradeBot's regime_detector_agent.

    Decision logic
    ~~~~~~~~~~~~~~
    1.  If ``adx > adx_threshold`` AND ``atr_slope > 0``
        → ``VOLATILE_DIRECTIONAL`` (trending + expanding vol)
    2.  If ``adx > adx_threshold`` AND ``close > bb_middle``
        → ``TRENDING_UP``
    3.  If ``adx > adx_threshold`` AND ``close ≤ bb_middle``
        → ``TRENDING_DOWN``
    4.  If ``adx < adx_threshold`` AND ``bb_width > bb_width_threshold``
        → ``VOLATILE_DIRECTIONLESS`` (pre-expiry manipulation zone)
    5.  If ``adx < adx_threshold`` AND ``bb_width < low_vol_bb_threshold``
           AND ``atr_slope < 0``
        → ``LOW_VOLATILITY`` (compression)
    6.  Otherwise → ``RANGING``

    Args:
        high: Sequence of bar high prices.
        low: Sequence of bar low prices.
        close: Sequence of bar close prices.
        adx_period: Wilder smoothing period for ADX / DI.  Defaults to 14.
        bb_period: Bollinger Band SMA period.  Defaults to 20.
        atr_period: ATR smoothing period.  Defaults to 14.
        adx_threshold: ADX level separating trending from non-trending.
            Defaults to 25.0.
        bb_width_threshold: Normalised BB width ((upper-lower)/middle)
            above which the market is considered volatile.  Defaults to
            0.04 (4%).
        low_vol_bb_threshold: BB width below which the market is
            considered compressed.  Defaults to 0.02 (2%).
        atr_slope_window: Number of recent ATR bars used to compute the
            ATR slope (positive = expanding).  Defaults to 5.

    Returns:
        ``RegimeState`` enum value.

    Raises:
        ValueError: If the input sequences have fewer bars than the
            maximum indicator warm-up period (``adx_period * 2 + 1``).

    Example::

        import pandas as pd
        df = pd.read_csv("nifty_1min.csv")
        regime = detect_regime(df["high"], df["low"], df["close"])
        print(regime)  # RegimeState.TRENDING_UP
    """
    result = detect_regime_detailed(
        high=high,
        low=low,
        close=close,
        adx_period=adx_period,
        bb_period=bb_period,
        atr_period=atr_period,
        adx_threshold=adx_threshold,
        bb_width_threshold=bb_width_threshold,
        low_vol_bb_threshold=low_vol_bb_threshold,
        atr_slope_window=atr_slope_window,
    )
    return result.state


def detect_regime_detailed(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    adx_period: int = 14,
    bb_period: int = 20,
    atr_period: int = 14,
    adx_threshold: float = 25.0,
    bb_width_threshold: float = 0.04,
    low_vol_bb_threshold: float = 0.02,
    atr_slope_window: int = 5,
) -> RegimeResult:
    """Detect regime and return full diagnostic detail.

    Same as ``detect_regime`` but returns a ``RegimeResult`` dataclass
    exposing all intermediate indicator values for logging, debugging,
    and the AI advisor's explainability layer.

    Args:
        high: Bar high prices.
        low: Bar low prices.
        close: Bar close prices.
        adx_period: ADX smoothing period.
        bb_period: Bollinger Band SMA period.
        atr_period: ATR period.
        adx_threshold: ADX trending threshold (default 25).
        bb_width_threshold: BB width volatile threshold (default 0.04).
        low_vol_bb_threshold: BB width low-vol threshold (default 0.02).
        atr_slope_window: Window for ATR slope calculation.

    Returns:
        ``RegimeResult`` with the detected state and all indicator values.

    Raises:
        ValueError: If fewer bars than the warm-up requirement are given.
    """
    high_list = list(high)
    low_list = list(low)
    close_list = list(close)
    n = len(close_list)

    min_bars = adx_period * 2 + 1
    if n < min_bars:
        raise ValueError(
            f"detect_regime requires at least {min_bars} bars "
            f"(adx_period={adx_period}); got {n}."
        )

    # Compute indicators
    plus_di_series, minus_di_series, adx_series = _directional_movement(
        high_list, low_list, close_list, adx_period
    )
    bb_upper, bb_middle, bb_lower = _bollinger_bands(close_list, bb_period)
    atr_series = _atr(high_list, low_list, close_list, atr_period)

    # Extract latest valid values
    def _last_valid(series: list[float]) -> float:
        for v in reversed(series):
            if not math.isnan(v):
                return v
        return float("nan")

    adx_val = _last_valid(adx_series)
    plus_di_val = _last_valid(plus_di_series)
    minus_di_val = _last_valid(minus_di_series)
    bb_upper_val = _last_valid(bb_upper)
    bb_middle_val = _last_valid(bb_middle)
    bb_lower_val = _last_valid(bb_lower)
    atr_val = _last_valid(atr_series)
    close_val = close_list[-1]

    # BB width: (upper - lower) / middle
    bb_width = float("nan")
    if (
        not math.isnan(bb_upper_val)
        and not math.isnan(bb_lower_val)
        and not math.isnan(bb_middle_val)
        and bb_middle_val != 0.0
    ):
        bb_width = (bb_upper_val - bb_lower_val) / bb_middle_val

    # ATR slope: linear regression slope over last ``atr_slope_window`` bars
    atr_recent = [v for v in atr_series[-atr_slope_window:] if not math.isnan(v)]
    atr_slope = 0.0
    if len(atr_recent) >= 2:
        xs = list(range(len(atr_recent)))
        mean_x = sum(xs) / len(xs)
        mean_y = sum(atr_recent) / len(atr_recent)
        numer = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(xs, atr_recent))
        denom = sum((xi - mean_x) ** 2 for xi in xs)
        atr_slope = numer / denom if denom != 0.0 else 0.0

    # --- Regime logic ---
    adx_ok = not math.isnan(adx_val)
    bb_ok = not math.isnan(bb_width)

    state: RegimeState

    if adx_ok and adx_val > adx_threshold and atr_slope > 0:
        # Trending direction with expanding volatility — strong move in progress
        state = RegimeState.VOLATILE_DIRECTIONAL

    elif adx_ok and adx_val > adx_threshold:
        # Trending — determine direction from close vs BB middle
        if bb_ok and not math.isnan(bb_middle_val) and close_val > bb_middle_val:
            state = RegimeState.TRENDING_UP
        else:
            state = RegimeState.TRENDING_DOWN

    elif adx_ok and adx_val <= adx_threshold and bb_ok and bb_width > bb_width_threshold:
        # Low ADX + wide bands → choppy/directionless volatility
        # Pre-expiry manipulation zone: avoid directional bets
        state = RegimeState.VOLATILE_DIRECTIONLESS

    elif (
        adx_ok
        and adx_val <= adx_threshold
        and bb_ok
        and bb_width < low_vol_bb_threshold
        and atr_slope < 0
    ):
        # Tight bands + declining ATR → compression before breakout
        state = RegimeState.LOW_VOLATILITY

    else:
        # Default: ranging
        state = RegimeState.RANGING

    return RegimeResult(
        state=state,
        adx=adx_val,
        bb_width=bb_width if not math.isnan(bb_width) else 0.0,
        atr_current=atr_val,
        atr_slope=atr_slope,
        plus_di=plus_di_val,
        minus_di=minus_di_val,
        close=close_val,
        n_bars=n,
    )
