"""VWAP with standard deviation bands.

Computes intraday VWAP and ±1σ / ±2σ / ±3σ bands from a list of OHLCV bars.

Session-reset behaviour (``session_reset=True``):
  A new session begins whenever the date portion of the bar timestamp changes.
  Cumulative sums for VWAP and variance are restarted at the first bar of each
  new session.  Use ``session_reset=False`` to compute a rolling continuous VWAP
  (e.g. for weekly or monthly VWAP bands).

Formulae::

    typical_price[i] = (high[i] + low[i] + close[i]) / 3
    cum_tv[i]        = Σ(typical_price * volume) over session
    cum_v[i]         = Σ(volume)                 over session
    vwap[i]          = cum_tv[i] / cum_v[i]

    cum_variance[i]  = Σ((typical_price - vwap)² * volume) over session
    σ[i]             = sqrt(cum_variance[i] / cum_v[i])

    upper_k[i]       = vwap[i] + k * σ[i]
    lower_k[i]       = vwap[i] - k * σ[i]    for k = 1, 2, 3

All functions:
- Accept list[dict] OHLCV input (keys: timestamp, open, high, low, close, volume)
- Return Pydantic VWAPResult model with list[float] outputs
- Fill NaN (as float('nan')) for bars where cumulative volume is 0
- Are fully type-annotated
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
from pydantic import BaseModel

logger = logging.getLogger("flinttrade.indicators.vwap_bands")

# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------


class VWAPResult(BaseModel):
    """VWAP with ±1σ / ±2σ / ±3σ deviation bands.

    All lists share the same length as the input OHLCV bars.

    Attributes:
        timestamps: ISO-format bar timestamps, oldest first.
        vwap:       VWAP value for each bar.
        upper_1:    VWAP + 1σ for each bar.
        upper_2:    VWAP + 2σ for each bar.
        upper_3:    VWAP + 3σ for each bar.
        lower_1:    VWAP − 1σ for each bar.
        lower_2:    VWAP − 2σ for each bar.
        lower_3:    VWAP − 3σ for each bar.
    """

    timestamps: list[str]
    vwap: list[float]
    upper_1: list[float]
    upper_2: list[float]
    upper_3: list[float]
    lower_1: list[float]
    lower_2: list[float]
    lower_3: list[float]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_date(timestamp: str) -> str:
    """Extract the date portion (YYYY-MM-DD) from an ISO timestamp string.

    Handles both date-only strings (``"2025-01-15"``) and full ISO datetimes
    (``"2025-01-15T09:15:00"`` or ``"2025-01-15 09:15:00"``).

    Args:
        timestamp: ISO-format timestamp string.

    Returns:
        Date string, e.g. ``"2025-01-15"``.
    """
    return timestamp[:10]


def _compute_session_vwap(
    tp: np.ndarray,
    volume: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute cumulative VWAP and σ for a single contiguous session.

    Args:
        tp:     Typical prices, shape (n,).
        volume: Bar volumes, shape (n,).

    Returns:
        Tuple of (vwap_values, sigma_values) each shape (n,).
        Bars with zero cumulative volume get NaN.
    """
    n = len(tp)
    vwap_out = np.full(n, math.nan)
    sigma_out = np.full(n, math.nan)

    cum_tv = 0.0   # cumulative typical_price × volume
    cum_v = 0.0    # cumulative volume
    cum_var = 0.0  # cumulative (tp - vwap)² × volume

    for i in range(n):
        cum_tv += float(tp[i]) * float(volume[i])
        cum_v += float(volume[i])

        if cum_v <= 0.0:
            continue

        v = cum_tv / cum_v
        vwap_out[i] = v

        # Update running variance: add (tp - current_vwap)² * vol
        # Note: this accumulates using the *current* VWAP estimate at each bar,
        # which is the standard anchored-VWAP band approach.
        cum_var += ((float(tp[i]) - v) ** 2) * float(volume[i])
        sigma_out[i] = math.sqrt(cum_var / cum_v)

    return vwap_out, sigma_out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def calculate_vwap_bands(
    ohlcv: list[dict[str, Any]],
    session_reset: bool = True,
) -> VWAPResult:
    """Calculate intraday VWAP with standard deviation bands.

    Args:
        ohlcv: List of OHLCV bar dicts, each containing at minimum:
               ``timestamp`` (str, ISO format), ``high`` (float),
               ``low`` (float), ``close`` (float), ``volume`` (float).
               Bars must be sorted oldest-first.
        session_reset: If ``True`` (default), reset the VWAP accumulator at
                       each new calendar date (session boundary).  Set to
                       ``False`` for a rolling continuous VWAP.

    Returns:
        VWAPResult with timestamps, VWAP, and six band series.

    Raises:
        ValueError: If ``ohlcv`` is empty or a required key is missing.
    """
    if not ohlcv:
        raise ValueError("ohlcv must contain at least one bar")

    required_keys = {"timestamp", "high", "low", "close", "volume"}
    first = ohlcv[0]
    missing = required_keys - first.keys()
    if missing:
        raise ValueError(f"OHLCV bars missing required keys: {sorted(missing)}")

    n = len(ohlcv)
    timestamps: list[str] = []
    tp_arr = np.empty(n, dtype=np.float64)
    vol_arr = np.empty(n, dtype=np.float64)

    for i, bar in enumerate(ohlcv):
        timestamps.append(str(bar["timestamp"]))
        h = float(bar["high"])
        lo = float(bar["low"])
        c = float(bar["close"])
        tp_arr[i] = (h + lo + c) / 3.0
        vol_arr[i] = float(bar["volume"])

    vwap_out = np.full(n, math.nan)
    sigma_out = np.full(n, math.nan)

    if session_reset:
        # Split bars into sessions by calendar date and process each separately
        session_start = 0
        current_date = _extract_date(timestamps[0])

        for i in range(1, n + 1):
            # End of array or date change → flush session
            if i == n or _extract_date(timestamps[i]) != current_date:
                seg_tp = tp_arr[session_start:i]
                seg_vol = vol_arr[session_start:i]
                seg_vwap, seg_sigma = _compute_session_vwap(seg_tp, seg_vol)
                vwap_out[session_start:i] = seg_vwap
                sigma_out[session_start:i] = seg_sigma

                if i < n:
                    session_start = i
                    current_date = _extract_date(timestamps[i])
    else:
        vwap_out, sigma_out = _compute_session_vwap(tp_arr, vol_arr)

    def _band(k: float, sign: float) -> list[float]:
        """Build a band list: vwap + sign * k * sigma."""
        return [
            float(vwap_out[i] + sign * k * sigma_out[i])
            if (not math.isnan(vwap_out[i]) and not math.isnan(sigma_out[i]))
            else math.nan
            for i in range(n)
        ]

    return VWAPResult(
        timestamps=timestamps,
        vwap=[float(v) for v in vwap_out],
        upper_1=_band(1.0, +1.0),
        upper_2=_band(2.0, +1.0),
        upper_3=_band(3.0, +1.0),
        lower_1=_band(1.0, -1.0),
        lower_2=_band(2.0, -1.0),
        lower_3=_band(3.0, -1.0),
    )
