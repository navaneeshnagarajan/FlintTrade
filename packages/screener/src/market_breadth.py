"""Market breadth indicators for Indian equity markets.

Computes daily breadth statistics and derived indicators:

- Advance/Decline ratio and cumulative A-D line
- McClellan Oscillator (19-day EMA minus 39-day EMA of net advances ratio)
- Breadth Thrust (Zweig, 10-day EMA of advances / total issues)

Terminology:
- Advances: Stocks that closed higher than the previous day.
- Declines: Stocks that closed lower.
- Unchanged: Stocks that closed at the same price.
- A-D ratio: advances / declines (undefined if declines == 0, returns 1.0).
- Net advances ratio: (advances - declines) / (advances + declines + unchanged).
  McClellan uses this normalised ratio to remove the effect of changing index
  membership size over time.
- Breadth Thrust uses advances / (advances + declines), ignoring unchanged.

Usage::

    from .market_breadth import MarketBreadthCalculator

    calc = MarketBreadthCalculator()
    for row in raw_data:
        calc.update(row["advances"], row["declines"], row["unchanged"])

    latest = calc.get_history(days=1)[0]
    print(latest.mcclellan_oscillator)
"""

from __future__ import annotations

import logging
import random
from datetime import date, timedelta

import numpy as np
from pydantic import BaseModel, Field

logger = logging.getLogger("flinttrade.screener.market_breadth")

# ---------------------------------------------------------------------------
# EMA helper
# ---------------------------------------------------------------------------

_EMA_LONG = 39   # McClellan long period
_EMA_SHORT = 19  # McClellan short period
_THRUST_PERIOD = 10  # Breadth Thrust smoothing window


def _ema(values: list[float], period: int) -> list[float]:
    """Compute exponential moving average series.

    Uses the classic Wilder-style multiplier: k = 2 / (period + 1).
    The first EMA value is the simple mean of the first ``period`` elements
    (standard initialisation used by most platforms).

    Args:
        values: Input time series, oldest first.
        period: EMA smoothing period.

    Returns:
        EMA series of the same length as ``values``. Values before the first
        full ``period`` window are filled with the seed mean.
    """
    if not values or period <= 0:
        return []

    k = 2.0 / (period + 1)
    result: list[float] = []

    # Seed from the first full window
    seed_end = min(period, len(values))
    seed = float(np.mean(values[:seed_end]))

    for i, v in enumerate(values):
        if i < seed_end:
            result.append(seed)
        else:
            result.append(v * k + result[-1] * (1.0 - k))

    return result


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class BreadthData(BaseModel):
    """Single day's market breadth snapshot with derived indicators.

    Attributes:
        date: Trading date for this snapshot.
        advances: Number of advancing issues.
        declines: Number of declining issues.
        unchanged: Number of unchanged issues.
        new_highs: Issues making a 52-week high.
        new_lows: Issues making a 52-week low.
        ad_ratio: Advances divided by declines (1.0 when declines == 0).
        ad_line: Cumulative advance-decline line value for this day.
        mcclellan_oscillator: 19-day EMA minus 39-day EMA of net advances ratio.
        breadth_thrust: 10-day EMA of advances / (advances + declines).
    """

    date: date
    advances: int = Field(ge=0)
    declines: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    new_highs: int = Field(default=0, ge=0)
    new_lows: int = Field(default=0, ge=0)
    ad_ratio: float = Field(default=1.0)
    ad_line: float = Field(default=0.0)
    mcclellan_oscillator: float = Field(default=0.0)
    breadth_thrust: float = Field(default=0.0)


# ---------------------------------------------------------------------------
# Calculator
# ---------------------------------------------------------------------------


class MarketBreadthCalculator:
    """Computes and caches daily market breadth indicators.

    All indicators are recomputed in full over the entire history each time a
    new data point is added.  For typical usage (< 500 trading days) this is
    fast enough (< 1 ms per update on modern hardware).

    Example::

        calc = MarketBreadthCalculator()
        calc.update(1450, 380, 170)
        latest = calc.get_history(days=1)[0]
    """

    def __init__(self) -> None:
        self._history: list[BreadthData] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        advances: int,
        declines: int,
        unchanged: int,
        new_highs: int = 0,
        new_lows: int = 0,
        trading_date: date | None = None,
    ) -> BreadthData:
        """Add one day's breadth data and return the computed snapshot.

        The A-D line, McClellan Oscillator, and Breadth Thrust are all
        recomputed over the full history after appending the new point.

        Args:
            advances: Number of advancing issues.
            declines: Number of declining issues.
            unchanged: Number of unchanged issues.
            new_highs: Issues at 52-week highs (default 0).
            new_lows: Issues at 52-week lows (default 0).
            trading_date: Date for this snapshot.  Defaults to today if not
                provided; auto-increments by 1 day when consecutive updates
                do not supply dates.

        Returns:
            BreadthData with all indicators computed.
        """
        if trading_date is None:
            if self._history:
                trading_date = self._history[-1].date + timedelta(days=1)
            else:
                trading_date = date.today()

        ad_ratio = float(advances) / float(declines) if declines > 0 else 1.0

        # Append raw stub — indicators are computed below across the full series
        stub = BreadthData(
            date=trading_date,
            advances=advances,
            declines=declines,
            unchanged=unchanged,
            new_highs=new_highs,
            new_lows=new_lows,
            ad_ratio=round(ad_ratio, 4),
        )
        self._history.append(stub)

        # Recompute indicators for the whole series
        self._recompute_indicators()

        return self._history[-1]

    def ad_line(self) -> list[float]:
        """Return the cumulative advance-decline line.

        Returns:
            List of cumulative A-D values, one per trading day, oldest first.
            Empty if no data has been loaded.
        """
        return [d.ad_line for d in self._history]

    def mcclellan_oscillator(self) -> float:
        """Return the latest McClellan Oscillator value.

        The oscillator is the 19-day EMA of the net-advances ratio minus the
        39-day EMA.  Positive values indicate broadening breadth; negative
        values indicate narrowing breadth.

        Returns:
            Latest oscillator value, or 0.0 if fewer than two days of data.
        """
        if not self._history:
            return 0.0
        return self._history[-1].mcclellan_oscillator

    def breadth_thrust(self) -> float:
        """Return the latest Breadth Thrust value.

        Breadth Thrust is the 10-day EMA of advances / (advances + declines).
        Values above 0.615 (within a 10-session window from below 0.40) signal
        a classic Zweig Breadth Thrust buy signal.

        Returns:
            Latest breadth thrust value (0–1), or 0.0 if no data.
        """
        if not self._history:
            return 0.0
        return self._history[-1].breadth_thrust

    def generate_sample_data(self, days: int = 90) -> list[BreadthData]:
        """Populate the calculator with synthetic breadth data.

        Generates realistic Indian equity-market breadth using a mean-reverting
        random walk.  Typical NSE/BSE index breadth ranges: advances 400–1 800,
        declines 200–1 400, unchanged 50–300.

        Args:
            days: Number of trading days to generate (default 90).

        Returns:
            List of BreadthData objects for all generated days.
        """
        self._history = []
        rng = random.Random(42)  # Deterministic for reproducible dev mode

        start = date.today() - timedelta(days=days + 1)
        # Skip weekends in a simple way
        current = start
        generated = 0

        while generated < days:
            if current.weekday() < 5:  # Monday–Friday
                # Mean-reverting advances around 55% participation
                advances = max(200, min(1800, int(rng.gauss(1000, 250))))
                declines = max(100, min(1400, int(rng.gauss(700, 200))))
                unchanged = max(30, min(300, int(rng.gauss(150, 50))))
                new_highs = max(0, int(rng.gauss(60, 25)))
                new_lows = max(0, int(rng.gauss(25, 15)))
                self.update(
                    advances=advances,
                    declines=declines,
                    unchanged=unchanged,
                    new_highs=new_highs,
                    new_lows=new_lows,
                    trading_date=current,
                )
                generated += 1
            current += timedelta(days=1)

        return list(self._history)

    def get_history(self, days: int = 30) -> list[BreadthData]:
        """Return the most recent ``days`` breadth snapshots.

        Args:
            days: Maximum number of recent days to return.

        Returns:
            List of BreadthData, most recent last, capped at ``days``.
        """
        return self._history[-days:] if self._history else []

    # ------------------------------------------------------------------
    # Internal computation
    # ------------------------------------------------------------------

    def _recompute_indicators(self) -> None:
        """Recompute A-D line, McClellan Oscillator, and Breadth Thrust.

        Called internally after each ``update`` so all stored BreadthData
        objects carry consistent, up-to-date indicator values.
        """
        n = len(self._history)
        if n == 0:
            return

        # --- A-D line (cumulative) ----------------------------------------
        cumulative_ad = 0.0
        for i, d in enumerate(self._history):
            cumulative_ad += d.advances - d.declines
            self._history[i] = d.model_copy(update={"ad_line": round(cumulative_ad, 2)})

        # --- McClellan Oscillator -------------------------------------------
        # Net advances ratio = (A - D) / (A + D + U) for each day
        net_ratio = [
            float(d.advances - d.declines) / max(1, d.advances + d.declines + d.unchanged)
            for d in self._history
        ]

        ema_short = _ema(net_ratio, _EMA_SHORT)
        ema_long = _ema(net_ratio, _EMA_LONG)

        for i, d in enumerate(self._history):
            oscillator = round(ema_short[i] - ema_long[i], 6)
            self._history[i] = self._history[i].model_copy(
                update={"mcclellan_oscillator": oscillator}
            )

        # --- Breadth Thrust -------------------------------------------------
        # Thrust ratio = A / (A + D); undefined when A + D == 0 → 0.5
        thrust_raw = [
            float(d.advances) / max(1, d.advances + d.declines)
            for d in self._history
        ]

        thrust_ema = _ema(thrust_raw, _THRUST_PERIOD)

        for i, d in enumerate(self._history):
            self._history[i] = self._history[i].model_copy(
                update={"breadth_thrust": round(thrust_ema[i], 6)}
            )
