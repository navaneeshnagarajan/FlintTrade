"""Volatility cone calculation for options analysis.

A volatility cone is a visualisation tool that shows the range of historical
volatility observed over various look-back windows.  By plotting the current
realised HV and implied volatility (IV) against the cone, traders can assess
whether options are cheap or expensive relative to history.

Methodology:
1. From a series of daily log-returns, compute rolling historical volatility
   (HV) using each ``lookback_period`` window.
2. Collect all rolling HV samples for each window into a distribution.
3. Compute the 10th, 25th, 50th, 75th, and 90th percentiles, min and max.
4. The most recent rolling HV sample is the ``current_hv`` for that window.
5. The caller may optionally supply the current implied volatility (IV) for
   comparison.

Annualisation uses 252 trading days per year.

Usage::

    from .volatility_cone import VolatilityCone

    cone = VolatilityCone()
    returns = [0.005, -0.003, 0.002, ...]  # daily log-returns
    points = cone.calculate(returns)
    for p in points:
        pct = cone.iv_percentile(current_iv=0.18, cone_point=p)
        print(f"{p.lookback}d: current_hv={p.current_hv:.1%}, IV pct={pct:.1f}")
"""

from __future__ import annotations

import logging
import math

import numpy as np
from pydantic import BaseModel, Field

logger = logging.getLogger("flinttrade.screener.volatility_cone")

# Annualisation factor for daily returns
_TRADING_DAYS_PER_YEAR = 252

# Default look-back windows (in trading days)
_DEFAULT_LOOKBACKS: list[int] = [5, 10, 20, 30, 60, 90]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class VolatilityConePoint(BaseModel):
    """Volatility cone statistics for a single look-back window.

    All volatility values are expressed as annualised fractions
    (e.g. 0.18 = 18% annualised volatility).

    Attributes:
        lookback: Look-back window in trading days.
        current_hv: Most recent rolling historical volatility for this window.
        current_iv: Current implied volatility, if supplied by the caller.
        p10: 10th percentile of the rolling HV distribution.
        p25: 25th percentile.
        p50: Median (50th percentile).
        p75: 75th percentile.
        p90: 90th percentile.
        min: Minimum observed rolling HV.
        max: Maximum observed rolling HV.
    """

    lookback: int = Field(gt=0, description="Look-back window in trading days")
    current_hv: float = Field(ge=0.0, description="Current historical volatility (annualised)")
    current_iv: float | None = Field(default=None, description="Current implied volatility (annualised)")
    p10: float = Field(ge=0.0)
    p25: float = Field(ge=0.0)
    p50: float = Field(ge=0.0)
    p75: float = Field(ge=0.0)
    p90: float = Field(ge=0.0)
    min: float = Field(ge=0.0)
    max: float = Field(ge=0.0)


# ---------------------------------------------------------------------------
# Volatility cone calculator
# ---------------------------------------------------------------------------


class VolatilityCone:
    """Compute historical volatility cones from daily return series.

    The calculator is stateless; call ``calculate`` with each new series.

    Example::

        cone = VolatilityCone()
        points = cone.calculate(daily_returns, lookback_periods=[10, 20, 30])
    """

    def calculate(
        self,
        daily_returns: list[float],
        lookback_periods: list[int] | None = None,
        current_iv: float | None = None,
    ) -> list[VolatilityConePoint]:
        """Calculate the volatility cone from a daily return series.

        For each look-back period ``w``:
        - Compute all rolling HV samples: HV[i] = std(returns[i-w:i]) * sqrt(252)
        - Build a distribution of these samples.
        - Compute percentile statistics.
        - Record the most recent sample as ``current_hv``.

        If fewer data points are available than a given window, that window is
        skipped and omitted from the result.

        Args:
            daily_returns: Daily log-returns (or simple returns), oldest first.
                At least ``max(lookback_periods) + 1`` values are needed to
                produce at least one rolling sample for the longest window.
            lookback_periods: List of look-back windows in trading days.
                Defaults to ``[5, 10, 20, 30, 60, 90]``.
            current_iv: Annualised implied volatility to annotate each point.

        Returns:
            List of VolatilityConePoint objects, one per valid look-back window,
            sorted by look-back period ascending.  Empty list if ``daily_returns``
            is too short for any window.
        """
        if lookback_periods is None:
            lookback_periods = _DEFAULT_LOOKBACKS

        if not daily_returns or not lookback_periods:
            return []

        arr = np.asarray(daily_returns, dtype=float)
        n = len(arr)

        results: list[VolatilityConePoint] = []
        annualise = math.sqrt(_TRADING_DAYS_PER_YEAR)

        for window in sorted(dict.fromkeys(lookback_periods)):
            if window < 2 or n <= window:
                # Not enough data to compute even one rolling sample
                logger.debug(
                    "Skipping window=%d: need %d returns, have %d", window, window + 1, n
                )
                continue

            # Rolling HV: std of each window, annualised
            hv_samples = _rolling_hv(arr, window, annualise)

            if len(hv_samples) == 0:
                continue

            pct = np.percentile(hv_samples, [10, 25, 50, 75, 90])

            results.append(
                VolatilityConePoint(
                    lookback=window,
                    current_hv=round(float(hv_samples[-1]), 6),
                    current_iv=round(current_iv, 6) if current_iv is not None else None,
                    p10=round(float(pct[0]), 6),
                    p25=round(float(pct[1]), 6),
                    p50=round(float(pct[2]), 6),
                    p75=round(float(pct[3]), 6),
                    p90=round(float(pct[4]), 6),
                    min=round(float(hv_samples.min()), 6),
                    max=round(float(hv_samples.max()), 6),
                )
            )

        return results

    def iv_percentile(
        self,
        current_iv: float,
        cone_point: VolatilityConePoint,
    ) -> float:
        """Estimate where the current IV sits within the cone's HV distribution.

        Uses linear interpolation across the five stored percentile points
        (p10, p25, p50, p75, p90) to produce a smooth 0–100 score.

        - Returns 0.0 when IV ≤ p10 (IV cheaper than 90% of history).
        - Returns 100.0 when IV ≥ p90 (IV more expensive than 90% of history).
        - Returns 50.0 when IV == p50 (IV at the historical median).

        Args:
            current_iv: Current annualised implied volatility (fraction, e.g. 0.18).
            cone_point: A VolatilityConePoint returned by ``calculate``.

        Returns:
            IV percentile rank in the range [0.0, 100.0].
        """
        # Build the percentile ladder
        ladder_x = [cone_point.p10, cone_point.p25, cone_point.p50, cone_point.p75, cone_point.p90]
        ladder_y = [10.0, 25.0, 50.0, 75.0, 90.0]

        if current_iv < ladder_x[0]:
            return 0.0
        if current_iv > ladder_x[-1]:
            return 100.0

        for i in range(len(ladder_x) - 1):
            lo_x, hi_x = ladder_x[i], ladder_x[i + 1]
            lo_y, hi_y = ladder_y[i], ladder_y[i + 1]
            if lo_x <= current_iv <= hi_x:
                if hi_x == lo_x:
                    return round(lo_y, 2)
                t = (current_iv - lo_x) / (hi_x - lo_x)
                return round(lo_y + t * (hi_y - lo_y), 2)

        return 100.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _rolling_hv(arr: np.ndarray, window: int, annualise: float) -> np.ndarray:
    """Compute the rolling historical volatility for a return series.

    Uses population standard deviation (ddof=1 for sample std) over each
    rolling window of length ``window``, then annualises by multiplying by
    ``annualise`` (typically sqrt(252)).

    Args:
        arr: 1-D numpy array of daily returns, oldest first.
        window: Rolling window length in trading days.
        annualise: Annualisation multiplier (sqrt of trading days per year).

    Returns:
        1-D numpy array of annualised HV values; length is len(arr) - window.
    """
    n = len(arr)
    n_samples = n - window
    if n_samples <= 0:
        return np.empty(0, dtype=float)

    hv = np.empty(n_samples, dtype=float)
    for i in range(n_samples):
        window_returns = arr[i : i + window]
        hv[i] = float(np.std(window_returns, ddof=1)) * annualise

    return hv
