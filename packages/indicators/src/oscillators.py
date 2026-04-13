"""Oscillator indicators — GatorOscillator, STC, Coppock Curve, TSI, CHO,
CHOP, KST, Vortex Indicator, AC (Acceleration/Deceleration).

All functions:
- Accept numpy float64 arrays
- Return numpy float64 arrays (or tuples thereof)
- Fill NaN for bars where insufficient history exists
- Do NOT forward-fill
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from packages.indicators.src.utils import validate_ohlcv, validate_series


def gator_oscillator(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    jaw_period: int = 13,
    jaw_offset: int = 8,
    teeth_period: int = 8,
    teeth_offset: int = 5,
    lips_period: int = 5,
    lips_offset: int = 3,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Gator Oscillator (Bill Williams).

    The Gator Oscillator visualises the convergence/divergence of the three
    Alligator lines.  It plots two histograms:

    - Upper histogram: ``abs(jaw - teeth)``
    - Lower histogram: ``-abs(teeth - lips)`` (negative, plotted below zero)

    When both histograms are positive/expanding, the Alligator is "eating"
    (strong trend); when both are contracting, the Alligator is "sleeping".

    Args:
        high: High prices, shape (n,).
        low: Low prices, shape (n,).
        jaw_period: Jaw SMMA period (default 13).
        jaw_offset: Jaw displacement bars (default 8).
        teeth_period: Teeth SMMA period (default 8).
        teeth_offset: Teeth displacement bars (default 5).
        lips_period: Lips SMMA period (default 5).
        lips_offset: Lips displacement bars (default 3).

    Returns:
        Tuple of (upper, lower) histogram arrays, each shape (n,).  NaN where
        any Alligator line is NaN.
    """
    from packages.indicators.src.trend import alligator as _alligator

    validate_ohlcv(high, low, high, min_length=1)
    jaw, teeth, lips = _alligator(
        high, low,
        jaw_period=jaw_period, jaw_offset=jaw_offset,
        teeth_period=teeth_period, teeth_offset=teeth_offset,
        lips_period=lips_period, lips_offset=lips_offset,
    )

    n = len(high)
    upper = np.full(n, np.nan, dtype=np.float64)
    lower = np.full(n, np.nan, dtype=np.float64)

    for i in range(n):
        if not (np.isnan(jaw[i]) or np.isnan(teeth[i]) or np.isnan(lips[i])):
            upper[i] = abs(jaw[i] - teeth[i])
            lower[i] = -abs(teeth[i] - lips[i])

    return upper, lower


def stc(
    close: NDArray[np.float64],
    fast: int = 23,
    slow: int = 50,
    cycle: int = 10,
    d1: int = 3,
    d2: int = 3,
) -> NDArray[np.float64]:
    """Schaff Trend Cycle (STC).

    Developed by Doug Schaff.  STC combines the speed of MACD with the
    cycle-detection accuracy of the Stochastic oscillator.  It oscillates
    between 0 and 100 and tends to signal trend changes ahead of MACD.

    Algorithm:
        1. Compute MACD line = EMA(close, fast) - EMA(close, slow)
        2. Apply Stochastic to MACD line with cycle-period window → FK
        3. Apply EMA(FK, d1) → PF
        4. Apply Stochastic to PF with cycle-period window → FKK
        5. STC = EMA(FKK, d2)

    Args:
        close: Close prices, shape (n,).
        fast: Fast EMA period for MACD (default 23).
        slow: Slow EMA period for MACD (default 50).
        cycle: Stochastic lookback window (default 10).
        d1: First smoothing period for FK → PF (default 3).
        d2: Second smoothing period for FKK → STC (default 3).

    Returns:
        STC values, shape (n,). Oscillates 0–100. NaN during warm-up.
    """
    from packages.indicators.src.trend import ema as _ema

    validate_series(close, min_length=slow + cycle)
    n = len(close)

    # Step 1: MACD line
    macd_line = _ema(close, fast) - _ema(close, slow)

    def _stoch_norm(series: NDArray[np.float64], per: int) -> NDArray[np.float64]:
        """Apply stochastic normalisation to a series."""
        out = np.full(n, np.nan, dtype=np.float64)
        for i in range(per - 1, n):
            window = series[i - per + 1 : i + 1]
            if np.any(np.isnan(window)):
                continue
            lo = float(np.min(window))
            hi = float(np.max(window))
            denom = hi - lo
            out[i] = (series[i] - lo) / denom * 100.0 if denom != 0.0 else 50.0
        return out

    def _ema_valid(arr: NDArray[np.float64], p: int) -> NDArray[np.float64]:
        mask = ~np.isnan(arr)
        valid = arr[mask]
        result = arr.copy()
        if len(valid) >= p:
            e = _ema(valid, p)
            result[mask] = e
        return result

    # Step 2-3: first stochastic + smooth
    fk = _stoch_norm(macd_line, cycle)
    pf = _ema_valid(fk, d1)

    # Step 4-5: second stochastic + smooth
    fkk = _stoch_norm(pf, cycle)
    stc_vals = _ema_valid(fkk, d2)

    # Clamp to [0, 100]
    out = np.where(np.isnan(stc_vals), np.nan, np.clip(stc_vals, 0.0, 100.0))
    return out.astype(np.float64)


def coppock_curve(
    close: NDArray[np.float64],
    wma_period: int = 10,
    long_roc_period: int = 14,
    short_roc_period: int = 11,
) -> NDArray[np.float64]:
    """Coppock Curve.

    Developed by Edwin Coppock as a long-term buy indicator for monthly data.
    The curve crosses above zero to signal long entries; it was originally
    never meant to signal sells.

    Formula:
        ROC_long  = ROC(close, long_roc_period)
        ROC_short = ROC(close, short_roc_period)
        Coppock   = WMA(ROC_long + ROC_short, wma_period)

    Args:
        close: Close prices, shape (n,).
        wma_period: Weighted moving average period (default 10).
        long_roc_period: Long ROC period (default 14).
        short_roc_period: Short ROC period (default 11).

    Returns:
        Coppock Curve values, shape (n,). NaN during warm-up.
    """
    from packages.indicators.src.trend import wma as _wma
    from packages.indicators.src.momentum import roc as _roc

    validate_series(close, min_length=long_roc_period + wma_period + 1)
    n = len(close)

    roc_long = _roc(close, long_roc_period)
    roc_short = _roc(close, short_roc_period)

    combined = np.full(n, np.nan, dtype=np.float64)
    for i in range(n):
        if not (np.isnan(roc_long[i]) or np.isnan(roc_short[i])):
            combined[i] = roc_long[i] + roc_short[i]

    valid_mask = ~np.isnan(combined)
    valid_combined = combined[valid_mask]
    result = np.full(n, np.nan, dtype=np.float64)

    if len(valid_combined) >= wma_period:
        wma_vals = _wma(valid_combined, wma_period)
        result[valid_mask] = wma_vals

    return result


def tsi(
    close: NDArray[np.float64],
    long_period: int = 25,
    short_period: int = 13,
) -> NDArray[np.float64]:
    """True Strength Index (TSI).

    Developed by William Blau.  TSI uses double-smoothed price momentum to
    reveal trend direction and overbought/oversold conditions.

    Formula:
        momentum       = close - close[i-1]
        ds_momentum    = EMA(EMA(momentum, long_period), short_period)
        ds_abs_momentum= EMA(EMA(|momentum|, long_period), short_period)
        TSI            = 100 * ds_momentum / ds_abs_momentum

    Args:
        close: Close prices, shape (n,).
        long_period: Long EMA period (default 25).
        short_period: Short EMA period (default 13).

    Returns:
        TSI values, shape (n,). Oscillates between -100 and 100.
        NaN during warm-up.
    """
    from packages.indicators.src.trend import ema as _ema

    validate_series(close, min_length=long_period + short_period + 1)
    n = len(close)

    momentum = np.full(n, np.nan, dtype=np.float64)
    momentum[1:] = close[1:] - close[:-1]
    abs_momentum = np.abs(momentum)

    def _double_ema(series: NDArray[np.float64], p1: int, p2: int) -> NDArray[np.float64]:
        mask1 = ~np.isnan(series)
        e1 = np.full(n, np.nan, dtype=np.float64)
        v1 = series[mask1]
        if len(v1) >= p1:
            e1[mask1] = _ema(v1, p1)
        mask2 = ~np.isnan(e1)
        e2 = np.full(n, np.nan, dtype=np.float64)
        v2 = e1[mask2]
        if len(v2) >= p2:
            e2[mask2] = _ema(v2, p2)
        return e2

    ds_mom = _double_ema(momentum, long_period, short_period)
    ds_abs = _double_ema(abs_momentum, long_period, short_period)

    result = np.full(n, np.nan, dtype=np.float64)
    for i in range(n):
        if not np.isnan(ds_mom[i]) and not np.isnan(ds_abs[i]) and ds_abs[i] != 0.0:
            result[i] = 100.0 * ds_mom[i] / ds_abs[i]

    return result


def cho(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    volume: NDArray[np.float64],
    fast: int = 3,
    slow: int = 10,
) -> NDArray[np.float64]:
    """Chaikin Oscillator (CHO).

    Developed by Marc Chaikin.  The CHO is computed as the difference between
    a fast and a slow EMA of the Accumulation/Distribution (A/D) line.

    Formula:
        AD_line = cumulative A/D line
        CHO     = EMA(AD_line, fast) - EMA(AD_line, slow)

    Args:
        high: High prices, shape (n,).
        low: Low prices, shape (n,).
        close: Close prices, shape (n,).
        volume: Volume values, shape (n,).
        fast: Fast EMA period (default 3).
        slow: Slow EMA period (default 10).

    Returns:
        CHO values, shape (n,). NaN during warm-up.
    """
    from packages.indicators.src.trend import ema as _ema
    from packages.indicators.src.volume import ad as _ad

    validate_ohlcv(high, low, close, min_length=slow)
    validate_series(volume, min_length=slow)
    if len(volume) != len(close):
        raise ValueError(f"Array length mismatch: volume={len(volume)}, close={len(close)}")

    ad_line = _ad(high, low, close, volume)
    return _ema(ad_line, fast) - _ema(ad_line, slow)


def chop(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    period: int = 14,
) -> NDArray[np.float64]:
    """Choppiness Index (CHOP).

    Developed by E.W. Dreiss.  The Choppiness Index quantifies whether the
    market is trending (low values, near 38.2) or choppy / sideways (high
    values, near 61.8).

    Formula:
        CHOP = 100 * log10(sum(ATR(1), period) / (highest(high, period) - lowest(low, period)))
               / log10(period)

    Args:
        high: High prices, shape (n,).
        low: Low prices, shape (n,).
        close: Close prices, shape (n,).
        period: Lookback period (default 14).

    Returns:
        CHOP values, shape (n,). Values range roughly 38.2–61.8.
        NaN during warm-up.
    """
    from packages.indicators.src.volatility import atr as _atr

    validate_ohlcv(high, low, close, min_length=period + 1)
    n = len(close)

    atr1 = _atr(high, low, close, 1)
    result = np.full(n, np.nan, dtype=np.float64)
    log_period = float(np.log10(period))

    if log_period == 0.0:
        return result

    for i in range(period, n):
        window_atr = atr1[i - period + 1 : i + 1]
        if np.any(np.isnan(window_atr)):
            continue
        sum_atr = float(np.sum(window_atr))
        hi = float(np.max(high[i - period + 1 : i + 1]))
        lo = float(np.min(low[i - period + 1 : i + 1]))
        denom = hi - lo
        if denom == 0.0 or sum_atr == 0.0:
            continue
        result[i] = 100.0 * float(np.log10(sum_atr / denom)) / log_period

    return result


def kst(
    close: NDArray[np.float64],
    r1: int = 10, r2: int = 13, r3: int = 15, r4: int = 20,
    n1: int = 10, n2: int = 13, n3: int = 15, n4: int = 20,
    signal: int = 9,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Know Sure Thing (KST).

    Developed by Martin Pring.  KST is a momentum oscillator based on the
    smoothed rate of change of four different periods.  Its signal line is
    a simple moving average of the KST line.

    Formula:
        RCMA1 = SMA(ROC(close, r1), n1)
        RCMA2 = SMA(ROC(close, r2), n2)
        RCMA3 = SMA(ROC(close, r3), n3)
        RCMA4 = SMA(ROC(close, r4), n4)
        KST   = RCMA1*1 + RCMA2*2 + RCMA3*3 + RCMA4*4
        Signal= SMA(KST, signal)

    Args:
        close: Close prices, shape (n,).
        r1: ROC period 1 (default 10).
        r2: ROC period 2 (default 13).
        r3: ROC period 3 (default 15).
        r4: ROC period 4 (default 20).
        n1: SMA smoothing period 1 (default 10).
        n2: SMA smoothing period 2 (default 13).
        n3: SMA smoothing period 3 (default 15).
        n4: SMA smoothing period 4 (default 20).
        signal: Signal SMA period (default 9).

    Returns:
        Tuple of (kst_line, signal_line), each shape (n,).
    """
    from packages.indicators.src.trend import sma as _sma
    from packages.indicators.src.momentum import roc as _roc

    validate_series(close, min_length=r4 + n4)
    n = len(close)

    rcma1 = _sma(_roc(close, r1), n1)
    rcma2 = _sma(_roc(close, r2), n2)
    rcma3 = _sma(_roc(close, r3), n3)
    rcma4 = _sma(_roc(close, r4), n4)

    kst_line = np.full(n, np.nan, dtype=np.float64)
    for i in range(n):
        if not any(np.isnan(v) for v in [rcma1[i], rcma2[i], rcma3[i], rcma4[i]]):
            kst_line[i] = rcma1[i] + 2.0 * rcma2[i] + 3.0 * rcma3[i] + 4.0 * rcma4[i]

    valid_mask = ~np.isnan(kst_line)
    valid_kst = kst_line[valid_mask]
    sig = np.full(n, np.nan, dtype=np.float64)
    if len(valid_kst) >= signal:
        sig_vals = _sma(valid_kst, signal)
        sig[valid_mask] = sig_vals

    return kst_line, sig


def vortex(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    period: int = 14,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Vortex Indicator (VI+ and VI-).

    Developed by Etienne Botes and Douglas Siepman.  The Vortex Indicator
    captures positive and negative trend movement with two oscillating lines.
    A crossover of VI+ above VI- signals a bullish trend; the reverse signals
    bearish.

    Formula:
        VM+[i] = |high[i] - low[i-1]|
        VM-[i] = |low[i]  - high[i-1]|
        TR[i]  = max(high[i]-low[i], |high[i]-close[i-1]|, |low[i]-close[i-1]|)
        VI+    = sum(VM+, period) / sum(TR, period)
        VI-    = sum(VM-, period) / sum(TR, period)

    Args:
        high: High prices, shape (n,).
        low: Low prices, shape (n,).
        close: Close prices, shape (n,).
        period: Lookback period (default 14).

    Returns:
        Tuple of (vi_plus, vi_minus) arrays, each shape (n,).
        First ``period`` values are NaN.
    """
    validate_ohlcv(high, low, close, min_length=period + 1)
    n = len(close)

    vm_plus = np.zeros(n, dtype=np.float64)
    vm_minus = np.zeros(n, dtype=np.float64)
    tr = np.zeros(n, dtype=np.float64)
    tr[0] = high[0] - low[0]

    for i in range(1, n):
        vm_plus[i] = abs(high[i] - low[i - 1])
        vm_minus[i] = abs(low[i] - high[i - 1])
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )

    vi_plus = np.full(n, np.nan, dtype=np.float64)
    vi_minus = np.full(n, np.nan, dtype=np.float64)

    for i in range(period, n):
        sum_vm_p = float(np.sum(vm_plus[i - period + 1 : i + 1]))
        sum_vm_m = float(np.sum(vm_minus[i - period + 1 : i + 1]))
        sum_tr = float(np.sum(tr[i - period + 1 : i + 1]))
        if sum_tr != 0.0:
            vi_plus[i] = sum_vm_p / sum_tr
            vi_minus[i] = sum_vm_m / sum_tr

    return vi_plus, vi_minus


def ac(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    fast: int = 5,
    slow: int = 34,
    signal: int = 5,
) -> NDArray[np.float64]:
    """Acceleration / Deceleration Oscillator (AC).

    Developed by Bill Williams.  The AC oscillator is the difference between
    the Awesome Oscillator and its ``signal``-period SMA.  It measures the
    acceleration or deceleration of market driving force.

    Formula:
        AO  = SMA(midpoint, fast) - SMA(midpoint, slow)
        AC  = AO - SMA(AO, signal)

    where midpoint = (high + low) / 2.

    Args:
        high: High prices, shape (n,).
        low: Low prices, shape (n,).
        fast: Fast SMA period for AO (default 5).
        slow: Slow SMA period for AO (default 34).
        signal: SMA period applied to AO for AC (default 5).

    Returns:
        AC values, shape (n,). NaN during warm-up.

    Raises:
        ValueError: If fast >= slow.
    """
    from packages.indicators.src.momentum import awesome_oscillator as _ao
    from packages.indicators.src.trend import sma as _sma

    validate_ohlcv(high, low, high, min_length=slow + signal)

    if fast >= slow:
        raise ValueError(f"ac fast ({fast}) must be < slow ({slow})")

    ao_vals = _ao(high, low, fast, slow)

    valid_mask = ~np.isnan(ao_vals)
    valid_ao = ao_vals[valid_mask]
    n = len(high)
    result = np.full(n, np.nan, dtype=np.float64)

    if len(valid_ao) >= signal:
        sma_ao_valid = _sma(valid_ao, signal)
        ao_sma = np.full(n, np.nan, dtype=np.float64)
        ao_sma[valid_mask] = sma_ao_valid
        valid_both = ~np.isnan(ao_vals) & ~np.isnan(ao_sma)
        result[valid_both] = ao_vals[valid_both] - ao_sma[valid_both]

    return result
