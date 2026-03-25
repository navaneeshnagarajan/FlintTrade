"""Relative Rotation Graph (RRG) computation for NSE sector indices.

Computes RS-Ratio and RS-Momentum for each sector versus NIFTY 50 benchmark,
producing the (x, y) tail coordinates used to plot a Relative Rotation Graph.

Algorithm (absorbed from sector-rotation-map reference):
  1. Raw RS = (sector_price / benchmark_price) * 100
  2. EWM-smooth raw RS with span=10 → smoothed_rs
  3. RS-Ratio = rolling z-score of smoothed_rs over 52-week window, rescaled
     to [97, 103] range (conventional RRG axis range)
  4. RS-Momentum = delta of RS-Ratio, EWM-smoothed (span=5), similarly rescaled

Quadrant classification:
  Leading   → RS-Ratio > 100 AND RS-Momentum > 100
  Weakening → RS-Ratio > 100 AND RS-Momentum < 100
  Lagging   → RS-Ratio < 100 AND RS-Momentum < 100
  Improving → RS-Ratio < 100 AND RS-Momentum > 100

No direct API calls — callers fetch price series and pass them in.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import TypedDict

logger = logging.getLogger("flinttrade.screener.rrg")

# ---------------------------------------------------------------------------
# NIFTY sector universe
# ---------------------------------------------------------------------------

NIFTY_SECTORS: list[tuple[str, str]] = [
    ("NIFTY IT", "IT"),
    ("NIFTY BANK", "Banking"),
    ("NIFTY PHARMA", "Pharma"),
    ("NIFTY FMCG", "FMCG"),
    ("NIFTY AUTO", "Auto"),
    ("NIFTY METAL", "Metals"),
    ("NIFTY REALTY", "Realty"),
    ("NIFTY ENERGY", "Energy"),
    ("NIFTY INFRA", "Infra"),
    ("NIFTY MEDIA", "Media"),
    ("NIFTY FINSERV", "FinServ"),
    ("NIFTY HEALTHCARE", "Healthcare"),
]

# Exchange for all sector indices on NSE
SECTOR_EXCHANGE = "NSE_INDEX"
BENCHMARK_SYMBOL = "NIFTY 50"
BENCHMARK_EXCHANGE = "NSE_INDEX"

# ---------------------------------------------------------------------------
# TypedDicts (JSON-serialisable output)
# ---------------------------------------------------------------------------


class RRGPoint(TypedDict):
    """Single tail point: date + RS-Ratio + RS-Momentum."""

    date: str
    rs_ratio: float
    rs_momentum: float


class SectorRRG(TypedDict):
    """RRG result for one sector."""

    symbol: str
    name: str
    tail: list[RRGPoint]
    current_quadrant: str  # "leading" | "weakening" | "lagging" | "improving"


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


@dataclass
class _Series:
    """Minimal indexed time-series (dates + float values, same length)."""

    dates: list[str] = field(default_factory=list)
    values: list[float] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.values)

    def __getitem__(self, idx: int) -> float:
        return self.values[idx]


def _ewm_smooth(values: list[float], span: int) -> list[float]:
    """Exponential weighted moving average (same semantics as pandas EWM span).

    alpha = 2 / (span + 1)
    EWM_t = alpha * x_t + (1 - alpha) * EWM_{t-1}

    Args:
        values: Input float series.
        span: Span parameter (higher = slower decay).

    Returns:
        Smoothed series of the same length.
    """
    if not values:
        return []
    alpha = 2.0 / (span + 1)
    result: list[float] = [values[0]]
    for v in values[1:]:
        result.append(alpha * v + (1 - alpha) * result[-1])
    return result


def _rolling_zscore(
    values: list[float],
    window: int,
    rescale_center: float = 100.0,
    rescale_range: float = 3.0,
) -> list[float]:
    """Rolling z-score with rescaling to [center-range, center+range].

    Z-score is computed over a trailing window. If the window has insufficient
    data (< 2 non-NaN), the value is set to rescale_center (neutral).

    After z-scoring, values are mapped to the conventional RRG axis range:
        rescaled = z * rescale_range / 3 + rescale_center
    (RRG convention: 100 = neutral, typical range 94–106)

    Args:
        values: Input float series (smoothed RS).
        window: Rolling window size in bars.
        rescale_center: Center of the output scale (default 100).
        rescale_range: Half-width of the output scale (default 3, giving 97–103).

    Returns:
        Rescaled z-score series of the same length.
    """
    n = len(values)
    result: list[float] = []
    for i in range(n):
        start = max(0, i - window + 1)
        window_vals = [v for v in values[start : i + 1] if not math.isnan(v)]
        if len(window_vals) < 2:
            result.append(rescale_center)
            continue
        mean = sum(window_vals) / len(window_vals)
        variance = sum((v - mean) ** 2 for v in window_vals) / (len(window_vals) - 1)
        std = math.sqrt(variance) if variance > 0 else 1.0
        z = (values[i] - mean) / std
        rescaled = z * (rescale_range / 3.0) + rescale_center
        result.append(round(rescaled, 4))
    return result


def compute_rrg(
    sector_prices: _Series,
    benchmark_prices: _Series,
    tail_length: int = 12,
) -> list[RRGPoint]:
    """Compute RS-Ratio and RS-Momentum for a single sector vs benchmark.

    Steps:
      1. Align dates (inner join on date strings).
      2. Raw RS = (sector / benchmark) * 100
      3. EWM smooth (span=10) → smoothed RS
      4. Rolling 52-bar z-score, rescaled → RS-Ratio
      5. RS-Ratio delta series, EWM smooth (span=5), z-score rescaled → RS-Momentum
      6. Return last `tail_length` points as list[RRGPoint].

    Args:
        sector_prices: Dated close-price series for the sector index.
        benchmark_prices: Dated close-price series for the benchmark (NIFTY 50).
        tail_length: Number of tail points to return (default 12 weeks).

    Returns:
        List of RRGPoint dicts, ordered oldest → newest.
    """
    # --- Step 1: Align on common dates ---
    bench_map = dict(zip(benchmark_prices.dates, benchmark_prices.values))
    aligned_dates: list[str] = []
    aligned_sector: list[float] = []
    aligned_bench: list[float] = []

    for date, sec_val in zip(sector_prices.dates, sector_prices.values):
        b = bench_map.get(date)
        if b is not None and b > 0 and sec_val > 0:
            aligned_dates.append(date)
            aligned_sector.append(sec_val)
            aligned_bench.append(b)

    if len(aligned_dates) < 4:
        logger.warning("RRG: insufficient aligned data points (%d)", len(aligned_dates))
        return []

    # --- Step 2: Raw RS ---
    raw_rs = [
        (sec / bench) * 100.0
        for sec, bench in zip(aligned_sector, aligned_bench)
    ]

    # --- Step 3: EWM smooth (span=10) ---
    smoothed_rs = _ewm_smooth(raw_rs, span=10)

    # --- Step 4: RS-Ratio (rolling 52-bar z-score, rescaled to ~97-103) ---
    rs_ratio = _rolling_zscore(smoothed_rs, window=52, rescale_center=100.0, rescale_range=3.0)

    # --- Step 5: RS-Momentum (delta of rs_ratio, EWM smooth span=5, rescale) ---
    rs_ratio_delta: list[float] = [0.0]
    for i in range(1, len(rs_ratio)):
        rs_ratio_delta.append(rs_ratio[i] - rs_ratio[i - 1])

    smoothed_delta = _ewm_smooth(rs_ratio_delta, span=5)
    rs_momentum = _rolling_zscore(
        smoothed_delta, window=52, rescale_center=100.0, rescale_range=3.0
    )

    # --- Step 6: Return last tail_length points ---
    n = len(aligned_dates)
    start = max(0, n - tail_length)
    tail: list[RRGPoint] = []
    for i in range(start, n):
        tail.append(RRGPoint(
            date=aligned_dates[i],
            rs_ratio=rs_ratio[i],
            rs_momentum=rs_momentum[i],
        ))
    return tail


def classify_quadrant(tail: list[RRGPoint]) -> str:
    """Return the current quadrant based on the last tail point.

    Quadrant rules (conventional RRG):
      - RS-Ratio > 100 AND RS-Momentum > 100 → leading
      - RS-Ratio > 100 AND RS-Momentum < 100 → weakening
      - RS-Ratio < 100 AND RS-Momentum < 100 → lagging
      - RS-Ratio < 100 AND RS-Momentum > 100 → improving

    Args:
        tail: Ordered tail points (last entry = current position).

    Returns:
        Quadrant string: "leading" | "weakening" | "lagging" | "improving" | "neutral"
    """
    if not tail:
        return "neutral"
    last = tail[-1]
    rs_r = last["rs_ratio"]
    rs_m = last["rs_momentum"]
    if rs_r >= 100 and rs_m >= 100:
        return "leading"
    if rs_r >= 100 and rs_m < 100:
        return "weakening"
    if rs_r < 100 and rs_m < 100:
        return "lagging"
    return "improving"


def build_sector_rrg(
    sector_prices: dict[str, _Series],
    benchmark_prices: _Series,
    tail_length: int = 12,
) -> list[SectorRRG]:
    """Compute RRG for all sectors against the benchmark.

    Args:
        sector_prices: Map of sector symbol → _Series with date/close data.
        benchmark_prices: Benchmark (NIFTY 50) date/close series.
        tail_length: Tail length for each sector (default 12 bars).

    Returns:
        List of SectorRRG dicts ready for JSON serialisation.
    """
    results: list[SectorRRG] = []
    for symbol, display_name in NIFTY_SECTORS:
        prices = sector_prices.get(symbol)
        if prices is None or len(prices) < 4:
            logger.warning("RRG: skipping %s — no price data", symbol)
            continue
        tail = compute_rrg(prices, benchmark_prices, tail_length=tail_length)
        quadrant = classify_quadrant(tail)
        results.append(SectorRRG(
            symbol=symbol,
            name=display_name,
            tail=tail,
            current_quadrant=quadrant,
        ))
    return results
