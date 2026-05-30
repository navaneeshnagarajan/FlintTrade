"""Volume indicators — OBV, AD, CMF, MFI, VWMA, Elder Force Index, Price Volume
Trend, Cumulative Delta, Volume Profile, EMV, NVI, KlingerVolumeOscillator,
OBVSmoothed, RVOL, VROC, FI (Force Index).

All functions:
- Accept numpy float64 arrays
- Return numpy float64 arrays (or tuples thereof)
- Fill NaN for bars where insufficient history exists
- Do NOT forward-fill
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from .utils import validate_ohlcv, validate_series


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
    from .trend import ema as _ema

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


def cumulative_delta(
    close: NDArray[np.float64],
    volume: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Cumulative Delta — running net buy-minus-sell volume.

    Approximates order flow imbalance by assigning volume as positive (buy) on
    up-bars and negative (sell) on down-bars.  Flat bars (close == prior close)
    contribute zero delta.

    This is the batch equivalent of ``StreamingCumulativeDelta``.

    Formula:
        delta[0] = 0
        delta[i] = delta[i-1] + volume[i]   if close[i] > close[i-1]
                 = delta[i-1] - volume[i]   if close[i] < close[i-1]
                 = delta[i-1]               if close[i] == close[i-1]

    Args:
        close:  Close prices, shape (n,).
        volume: Volume,       shape (n,). Values must be >= 0.

    Returns:
        Cumulative delta values, shape (n,). No NaN warmup — starts at 0.

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
        if close[i] > close[i - 1]:
            result[i] = result[i - 1] + volume[i]
        elif close[i] < close[i - 1]:
            result[i] = result[i - 1] - volume[i]
        else:
            result[i] = result[i - 1]

    return result


def volume_profile(
    close: NDArray[np.float64],
    volume: NDArray[np.float64],
    num_bins: int = 20,
) -> tuple[NDArray[np.float64], NDArray[np.float64], float]:
    """Volume Profile — distribution of volume across price bins.

    Splits the price range [min_close, max_close] into ``num_bins`` equally
    spaced bins and sums the volume in each bin.  Returns the bin centre prices,
    the volume per bin, and the Point of Control (POC) — the price level with
    the highest accumulated volume.

    Args:
        close:    Close prices, shape (n,).
        volume:   Volume,       shape (n,). Values must be >= 0.
        num_bins: Number of price buckets (default 20, must be >= 2).

    Returns:
        Tuple of:
        - price_levels: Centre price of each bin, shape (num_bins,).
        - bin_volumes:  Total volume in each bin, shape (num_bins,).
        - poc_price:    Point of Control price (highest-volume bin centre).

    Raises:
        ValueError: If close and volume lengths differ, num_bins < 2, or
                    close has fewer than 2 bars.
    """
    validate_series(close, min_length=2)
    validate_series(volume, min_length=2)
    if len(close) != len(volume):
        raise ValueError(
            f"Array length mismatch: close={len(close)}, volume={len(volume)}"
        )
    if num_bins < 2:
        raise ValueError(f"volume_profile num_bins must be >= 2, got {num_bins}")

    price_min = float(np.min(close))
    price_max = float(np.max(close))

    if price_min == price_max:
        # All prices identical — single bin
        price_levels = np.full(num_bins, price_min, dtype=np.float64)
        bin_volumes = np.zeros(num_bins, dtype=np.float64)
        bin_volumes[0] = float(np.sum(volume))
        return price_levels, bin_volumes, price_min

    bin_edges = np.linspace(price_min, price_max, num_bins + 1, dtype=np.float64)
    price_levels = (bin_edges[:-1] + bin_edges[1:]) / 2.0
    bin_volumes = np.zeros(num_bins, dtype=np.float64)

    for i in range(len(close)):
        # Find bin index using linear interpolation
        frac = (close[i] - price_min) / (price_max - price_min)
        idx = int(frac * num_bins)
        idx = min(idx, num_bins - 1)  # clamp the last edge into the final bin
        bin_volumes[idx] += volume[i]

    poc_idx = int(np.argmax(bin_volumes))
    poc_price = float(price_levels[poc_idx])

    return price_levels, bin_volumes, poc_price


def emv(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    volume: NDArray[np.float64],
    period: int = 14,
    divisor: float = 1e4,
) -> NDArray[np.float64]:
    """Ease of Movement (EMV).

    Developed by Richard W. Arms Jr.  EMV relates an asset's price change to
    its volume and is used to assess the ease with which a security's price
    moves.  A smoothed (SMA) version is returned.

    Formula:
        midpoint_move = (high + low) / 2 - (high[i-1] + low[i-1]) / 2
        box_ratio     = (volume / divisor) / (high - low)
        raw_emv       = midpoint_move / box_ratio
        EMV           = SMA(raw_emv, period)

    Args:
        high: High prices, shape (n,).
        low: Low prices, shape (n,).
        volume: Volume values, shape (n,).
        period: SMA smoothing period (default 14).
        divisor: Volume scale divisor (default 1e4; adjust for large volume series).

    Returns:
        EMV values, shape (n,). NaN until warmed up.
    """
    from .trend import sma as _sma

    validate_ohlcv(high, low, high, min_length=2)
    validate_series(volume, min_length=2)
    if len(high) != len(volume):
        raise ValueError(f"Array length mismatch: high={len(high)}, volume={len(volume)}")

    n = len(high)
    raw = np.full(n, np.nan, dtype=np.float64)

    for i in range(1, n):
        hl = high[i] - low[i]
        if hl == 0.0 or volume[i] == 0.0:
            raw[i] = 0.0
            continue
        mid_move = (high[i] + low[i]) / 2.0 - (high[i - 1] + low[i - 1]) / 2.0
        box_ratio = (volume[i] / divisor) / hl
        raw[i] = mid_move / box_ratio if box_ratio != 0.0 else 0.0

    # Smooth over valid portion
    valid_mask = ~np.isnan(raw)
    valid_raw = raw[valid_mask]
    result = np.full(n, np.nan, dtype=np.float64)
    if len(valid_raw) >= period:
        sma_vals = _sma(valid_raw, period)
        result[valid_mask] = sma_vals
    return result


def nvi(
    close: NDArray[np.float64],
    volume: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Negative Volume Index (NVI).

    The NVI focuses on days when volume decreases from the previous day.  The
    idea is that informed ("smart money") trades occur on low-volume days.

    Formula:
        NVI[0] = 1000
        NVI[i] = NVI[i-1] * (1 + pct_change(close)) if volume[i] < volume[i-1]
               = NVI[i-1]                             otherwise

    Args:
        close: Close prices, shape (n,).
        volume: Volume values, shape (n,).

    Returns:
        NVI values, shape (n,). Starts at 1000 for bar 0.
    """
    validate_series(close, min_length=1)
    validate_series(volume, min_length=1)
    if len(close) != len(volume):
        raise ValueError(f"Array length mismatch: close={len(close)}, volume={len(volume)}")

    n = len(close)
    result = np.full(n, 1000.0, dtype=np.float64)

    for i in range(1, n):
        if volume[i] < volume[i - 1]:
            prev = close[i - 1]
            pct = (close[i] - prev) / prev if prev != 0.0 else 0.0
            result[i] = result[i - 1] * (1.0 + pct)
        else:
            result[i] = result[i - 1]

    return result


def klinger_volume_oscillator(
    high: NDArray[np.float64],
    low: NDArray[np.float64],
    close: NDArray[np.float64],
    volume: NDArray[np.float64],
    fast: int = 34,
    slow: int = 55,
    signal: int = 13,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Klinger Volume Oscillator (KVO).

    Developed by Stephen J. Klinger.  KVO attempts to predict price reversals
    by comparing the volume of a stock with its price movement.

    Formula:
        trend = +1 if (high + low + close) > prev(high + low + close) else -1
        dm    = high - low
        cm[i] = cm[i-1] + dm[i] if trend == prev_trend else dm[i]
        VF    = volume * |2 * dm/cm - 1| * trend * 100
        KVO   = EMA(VF, fast) - EMA(VF, slow)
        Signal = EMA(KVO, signal)

    Args:
        high: High prices, shape (n,).
        low: Low prices, shape (n,).
        close: Close prices, shape (n,).
        volume: Volume values, shape (n,).
        fast: Fast EMA period (default 34).
        slow: Slow EMA period (default 55).
        signal: Signal EMA period (default 13).

    Returns:
        Tuple of (kvo, signal_line) arrays, each shape (n,).
    """
    from .trend import ema as _ema

    validate_ohlcv(high, low, close, min_length=2)
    validate_series(volume, min_length=2)
    if len(volume) != len(close):
        raise ValueError(f"Array length mismatch: volume={len(volume)}, close={len(close)}")

    n = len(close)
    hlc = high + low + close

    # Volume force
    vf = np.zeros(n, dtype=np.float64)
    cm = 0.0
    prev_trend = 0

    for i in range(1, n):
        trend = 1 if hlc[i] >= hlc[i - 1] else -1
        dm = high[i] - low[i]
        if trend == prev_trend:
            cm += dm
        else:
            cm = high[i - 1] - low[i - 1] + dm  # reset cm
        prev_trend = trend
        vf[i] = volume[i] * (abs(2.0 * dm / cm - 1.0) if cm != 0.0 else 0.0) * trend * 100.0

    kvo_line = _ema(vf, fast) - _ema(vf, slow)

    valid_mask = ~np.isnan(kvo_line)
    valid_kvo = kvo_line[valid_mask]
    sig = np.full(n, np.nan, dtype=np.float64)
    if len(valid_kvo) >= signal:
        sig_vals = _ema(valid_kvo, signal)
        sig[valid_mask] = sig_vals

    return kvo_line, sig


def obv_smoothed(
    close: NDArray[np.float64],
    volume: NDArray[np.float64],
    period: int = 10,
) -> NDArray[np.float64]:
    """On Balance Volume — EMA smoothed.

    Computes standard OBV and then applies an EMA of the given period to
    reduce noise.  Useful for identifying the underlying trend of OBV.

    Args:
        close: Close prices, shape (n,).
        volume: Volume values, shape (n,).
        period: EMA smoothing period (default 10).

    Returns:
        Smoothed OBV values, shape (n,). First ``period - 1`` values are NaN.
    """
    from .trend import ema as _ema

    obv_raw = obv(close, volume)
    return _ema(obv_raw, period)


def rvol(
    volume: NDArray[np.float64],
    period: int = 20,
) -> NDArray[np.float64]:
    """Relative Volume (RVOL).

    RVOL compares the current bar's volume to the average volume over the
    preceding ``period`` bars.  A value of 2.0 means volume is twice the average.

    Formula:
        RVOL[i] = volume[i] / SMA(volume, period)[i-1]

    The comparison uses the SMA of the *prior* ``period`` bars (not including
    the current bar) to avoid lookahead.

    Args:
        volume: Volume values, shape (n,).
        period: Lookback for average volume (default 20).

    Returns:
        RVOL values, shape (n,). First ``period`` values are NaN.
        NaN is returned when average volume is zero.
    """
    from .trend import sma as _sma

    validate_series(volume, min_length=period + 1)

    n = len(volume)
    result = np.full(n, np.nan, dtype=np.float64)

    # Compute SMA of volume; we compare bar i to SMA ending at i-1
    sma_vol = _sma(volume, period)

    for i in range(period, n):
        avg = sma_vol[i - 1]
        if not np.isnan(avg) and avg != 0.0:
            result[i] = volume[i] / avg

    return result


def vroc(
    volume: NDArray[np.float64],
    period: int = 14,
) -> NDArray[np.float64]:
    """Volume Rate of Change (VROC).

    Measures the percentage change in volume over a given period, analogous to
    the Price ROC for price data.

    Formula:
        VROC[i] = (volume[i] - volume[i - period]) / volume[i - period] * 100

    Args:
        volume: Volume values, shape (n,).
        period: Lookback period (default 14).

    Returns:
        VROC values, shape (n,). First ``period`` values are NaN.
    """
    validate_series(volume, min_length=period + 1)
    n = len(volume)
    result = np.full(n, np.nan, dtype=np.float64)

    for i in range(period, n):
        prev = volume[i - period]
        result[i] = ((volume[i] - prev) / prev * 100.0) if prev != 0.0 else 0.0

    return result


def fi(
    close: NDArray[np.float64],
    volume: NDArray[np.float64],
    period: int = 13,
) -> NDArray[np.float64]:
    """Force Index (FI).

    Developed by Alexander Elder.  The Force Index combines price direction,
    magnitude, and volume.  This is the same calculation as ``efi`` but uses
    the common short name ``fi`` as an alias for ergonomics.

    Formula:
        raw[i] = (close[i] - close[i-1]) * volume[i]
        FI     = EMA(raw, period)

    Args:
        close: Close prices, shape (n,).
        volume: Volume values, shape (n,).
        period: EMA smoothing period (default 13).

    Returns:
        Force Index values, shape (n,). First ``period`` values are NaN.
    """
    return efi(close, volume, period)
