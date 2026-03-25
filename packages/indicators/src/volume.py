"""Volume indicators — OBV, AD, CMF, MFI, VWMA, Elder Force Index, Price Volume Trend.

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


def obv(
    close: NDArray[np.float64],
    volume: NDArray[np.float64],
) -> NDArray[np.float64]:
    """On Balance Volume.

    OBV is a cumulative momentum indicator that adds volume on up-bars and
    subtracts it on down-bars.  When close equals the previous close the bar
    is treated as an up-bar (volume is added).

    Formula:
        OBV[0] = 0
        OBV[i] = OBV[i-1] + volume[i]  if close[i] >= close[i-1]
               = OBV[i-1] - volume[i]  if close[i] <  close[i-1]

    Args:
        close:  Close prices, shape (n,).
        volume: Volume,       shape (n,). Values must be >= 0.

    Returns:
        OBV values, shape (n,). No NaN warmup — starts at bar 0.
    """
    validate_series(close, min_length=1)
    validate_series(volume, min_length=1)
    if len(close) != len(volume):
        raise ValueError(
            f"Array length mismatch: close={len(close)}, volume={len(volume)}"
        )

    n = len(close)
    result = np.zeros(n, dtype=np.float64)

    for i in range(1, n):
        if close[i] >= close[i - 1]:
            result[i] = result[i - 1] + volume[i]
        else:
            result[i] = result[i - 1] - volume[i]

    return result


def ad(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    volume: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Accumulation / Distribution Line.

    The A/D line is a cumulative indicator that uses volume flow to indicate
    whether a security is being accumulated (bought) or distributed (sold).

    Formula:
        CLV  = ((close - low) - (high - close)) / (high - low)
        MFV  = CLV * volume
        AD[i] = AD[i-1] + MFV[i]

    CLV is 0 when high == low.

    Args:
        high:   High prices,  shape (n,).
        low:    Low prices,   shape (n,).
        close:  Close prices, shape (n,).
        volume: Volume,       shape (n,). Values must be >= 0.

    Returns:
        A/D line values, shape (n,). Bar 0 is seeded at 0.
    """
    validate_ohlcv(high, low, close, min_length=1)
    validate_series(volume, min_length=1)
    if len(volume) != len(close):
        raise ValueError(
            f"Array length mismatch: volume={len(volume)}, close={len(close)}"
        )

    n = len(close)
    result = np.zeros(n, dtype=np.float64)

    for i in range(1, n):
        hl = high[i] - low[i]
        clv = ((close[i] - low[i]) - (high[i] - close[i])) / hl if hl != 0.0 else 0.0
        result[i] = result[i - 1] + clv * volume[i]

    return result


def cmf(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    volume: NDArray[np.float64],
    period: int = 20,
) -> NDArray[np.float64]:
    """Chaikin Money Flow.

    CMF = sum(MFV, period) / sum(volume, period)

    where MFV = CLV * volume and CLV = ((close - low) - (high - close)) / (high - low).

    CMF oscillates between -1 and +1.  Readings > 0 indicate accumulation,
    readings < 0 indicate distribution.

    Args:
        high:   High prices,  shape (n,).
        low:    Low prices,   shape (n,).
        close:  Close prices, shape (n,).
        volume: Volume,       shape (n,). Values must be >= 0.
        period: Rolling window (default 20).

    Returns:
        CMF values, shape (n,). First ``period - 1`` values are NaN.
    """
    validate_ohlcv(high, low, close, min_length=period)
    validate_series(volume, min_length=period)
    if len(volume) != len(close):
        raise ValueError(
            f"Array length mismatch: volume={len(volume)}, close={len(close)}"
        )

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)

    # Pre-compute Money Flow Volume per bar
    mfv = np.zeros(n, dtype=np.float64)
    for i in range(n):
        hl = high[i] - low[i]
        clv = ((close[i] - low[i]) - (high[i] - close[i])) / hl if hl != 0.0 else 0.0
        mfv[i] = clv * volume[i]

    for i in range(period - 1, n):
        sum_mfv = float(np.sum(mfv[i - period + 1 : i + 1]))
        sum_vol = float(np.sum(volume[i - period + 1 : i + 1]))
        result[i] = sum_mfv / sum_vol if sum_vol > 0.0 else 0.0

    return result


def mfi(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    volume: NDArray[np.float64],
    period: int = 14,
) -> NDArray[np.float64]:
    """Money Flow Index — volume-weighted RSI.

    MFI oscillates between 0 and 100.  Readings > 80 are traditionally
    overbought; readings < 20 are oversold.

    Formula:
        Typical Price (TP)  = (high + low + close) / 3
        Raw Money Flow      = TP * volume
        Positive MF: cumulated when TP > TP[prev]
        Negative MF: cumulated when TP < TP[prev]
        Money Ratio         = Positive MF / Negative MF
        MFI                 = 100 - 100 / (1 + Money Ratio)

    Args:
        high:   High prices,  shape (n,).
        low:    Low prices,   shape (n,).
        close:  Close prices, shape (n,).
        volume: Volume,       shape (n,). Values must be >= 0.
        period: Rolling window (default 14).

    Returns:
        MFI values, shape (n,). First ``period`` values are NaN.
    """
    validate_ohlcv(high, low, close, min_length=period + 1)
    validate_series(volume, min_length=period + 1)
    if len(volume) != len(close):
        raise ValueError(
            f"Array length mismatch: volume={len(volume)}, close={len(close)}"
        )

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)
    tp = (high + low + close) / 3.0
    rmf = tp * volume  # raw money flow

    pos_mf = np.zeros(n, dtype=np.float64)
    neg_mf = np.zeros(n, dtype=np.float64)
    for i in range(1, n):
        if tp[i] > tp[i - 1]:
            pos_mf[i] = rmf[i]
        elif tp[i] < tp[i - 1]:
            neg_mf[i] = rmf[i]

    for i in range(period, n):
        pos_sum = float(np.sum(pos_mf[i - period + 1 : i + 1]))
        neg_sum = float(np.sum(neg_mf[i - period + 1 : i + 1]))
        if neg_sum == 0.0:
            result[i] = 100.0
        else:
            result[i] = 100.0 - 100.0 / (1.0 + pos_sum / neg_sum)

    return result


def vwma(
    close: NDArray[np.float64],
    volume: NDArray[np.float64],
    period: int = 20,
) -> NDArray[np.float64]:
    """Volume Weighted Moving Average.

    VWMA = sum(close * volume, period) / sum(volume, period)

    Gives more weight to bars with higher volume than a plain SMA.

    Args:
        close:  Close prices, shape (n,).
        volume: Volume,       shape (n,). Values must be >= 0.
        period: Rolling window (default 20).

    Returns:
        VWMA values, shape (n,). First ``period - 1`` values are NaN.
        NaN is returned for windows where cumulative volume is 0.
    """
    validate_series(close, min_length=period)
    validate_series(volume, min_length=period)
    if len(close) != len(volume):
        raise ValueError(
            f"Array length mismatch: close={len(close)}, volume={len(volume)}"
        )

    n = len(close)
    result = np.full(n, np.nan, dtype=np.float64)

    for i in range(period - 1, n):
        cv = close[i - period + 1 : i + 1]
        vl = volume[i - period + 1 : i + 1]
        sum_vol = float(np.sum(vl))
        result[i] = float(np.sum(cv * vl)) / sum_vol if sum_vol > 0.0 else np.nan

    return result


def efi(
    close: NDArray[np.float64],
    volume: NDArray[np.float64],
    period: int = 13,
) -> NDArray[np.float64]:
    """Elder Force Index — price change times volume, EMA smoothed.

    Developed by Alexander Elder. Combines price direction, magnitude, and
    volume into a single oscillator. Positive values indicate buying pressure;
    negative values indicate selling pressure.

    Formula:
        raw[i] = (close[i] - close[i - 1]) * volume[i]
        EFI[i] = EMA(raw, period)

    Args:
        close: Close prices, shape (n,).
        volume: Volume, shape (n,). Must be same length as close.
        period: EMA smoothing period (default 13).

    Returns:
        EFI values, shape (n,). Index 0 is NaN (no prior close).
        First ``period`` values total are NaN (1 for diff + period-1 for EMA warmup).

    Raises:
        ValueError: If close and volume lengths differ.
    """
    from packages.indicators.src.trend import ema as _ema

    validate_series(close, min_length=2)
    validate_series(volume, min_length=2)
    if len(close) != len(volume):
        raise ValueError(
            f"Array length mismatch: close={len(close)}, volume={len(volume)}"
        )
    if period < 1:
        raise ValueError(f"efi period must be >= 1, got {period}")

    n = len(close)
    raw = np.full(n, np.nan, dtype=np.float64)
    raw[1:] = (close[1:] - close[:-1]) * volume[1:]

    # Compute EMA over the valid (non-NaN) portion of raw
    valid_mask = ~np.isnan(raw)
    valid_raw = raw[valid_mask]

    result = np.full(n, np.nan, dtype=np.float64)
    if len(valid_raw) >= period:
        ema_vals = _ema(valid_raw, period)
        valid_indices = np.where(valid_mask)[0]
        result[valid_indices] = ema_vals

    return result


def pvt(
    close: NDArray[np.float64],
    volume: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Price Volume Trend — cumulative (percentage change * volume).

    PVT is similar to OBV but uses the percentage price change rather than
    a binary up/down signal, giving proportional weight to the magnitude of
    price moves.

    Formula:
        PVT[0] = 0
        PVT[i] = PVT[i-1] + ((close[i] - close[i-1]) / close[i-1]) * volume[i]

    When close[i-1] is 0, the contribution for that bar is treated as 0.

    Args:
        close: Close prices, shape (n,). All values should be > 0 for meaningful results.
        volume: Volume, shape (n,). Must be same length as close.

    Returns:
        PVT values, shape (n,). No NaN warmup — starts at 0 for bar 0.

    Raises:
        ValueError: If close and volume lengths differ.
    """
    validate_series(close, min_length=1)
    validate_series(volume, min_length=1)
    if len(close) != len(volume):
        raise ValueError(
            f"Array length mismatch: close={len(close)}, volume={len(volume)}"
        )

    n = len(close)
    result = np.zeros(n, dtype=np.float64)

    for i in range(1, n):
        prev_close = close[i - 1]
        if prev_close != 0.0:
            pct_change = (close[i] - prev_close) / prev_close
        else:
            pct_change = 0.0
        result[i] = result[i - 1] + pct_change * volume[i]

    return result
