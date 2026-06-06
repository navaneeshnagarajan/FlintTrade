"""Multi-timeframe signal alignment analyser.

Computes per-timeframe signals (trend, RSI, MACD histogram, EMA position)
and aggregates them into a single confluence score and overall direction.

Confluence algorithm:
    - Each timeframe casts a directional vote: +1 (bullish), -1 (bearish), 0 (neutral).
    - ``confluence`` = (count of non-neutral votes that agree with majority) / total timeframes.
    - ``overall`` is the majority direction if confluence >= 0.5, else "neutral".

Per-timeframe signal details:

    trend:
        EMA20 > EMA50  → "bullish"
        EMA20 < EMA50  → "bearish"
        otherwise      → "neutral"

    rsi (14-period Wilder):
        Reported as a float in [0, 100].

    macd_histogram:
        Standard MACD (12, 26, 9) histogram value.

    ema_position:
        Last close relative to EMA20:
        close > EMA20  → "above"
        close < EMA20  → "below"
        otherwise      → "above"   (tie treated as above)

    strength:
        |macd_histogram| normalised to [0, 1] using a softmax-like
        tanh scaling: tanh(|histogram| / scale) where scale = 0.5 % of mean
        close price.  Capped at 1.0.

Integration:
- Flask route in ``pair_routes.py`` exposes this via POST /ft-api/v1/analytics/mtf.

Adapted from:
- Standard TA-Lib / pandas-ta patterns for multi-timeframe analysis
- FlintTrade indicators package (rsi, macd, ema functions)
"""

from __future__ import annotations

import logging
import math

import numpy as np
from pydantic import BaseModel, Field

from flinttrade_indicators.momentum import macd as _macd
from flinttrade_indicators.momentum import rsi as _rsi
from flinttrade_indicators.trend import ema as _ema

logger = logging.getLogger("flinttrade.screener.multi_timeframe")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIN_BARS: int = 30       # minimum bars required to produce any signal
_EMA_FAST: int = 20       # fast EMA for trend & position check
_EMA_SLOW: int = 50       # slow EMA for trend check
_RSI_PERIOD: int = 14
_MACD_FAST: int = 12
_MACD_SLOW: int = 26
_MACD_SIGNAL: int = 9
_CONFLUENCE_THRESHOLD: float = 0.5   # fraction to declare overall direction


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TimeframeSignal(BaseModel):
    """Signal summary for a single timeframe.

    Attributes:
        timeframe:       Label, e.g. ``"5m"``, ``"15m"``, ``"1h"``, ``"1D"``.
        trend:           ``"bullish"``, ``"bearish"``, or ``"neutral"``.
        rsi:             14-period RSI value (0–100). ``50.0`` (neutral) when insufficient data — kept finite so the JSON response stays valid.
        macd_histogram:  MACD (12,26,9) histogram value. ``0.0`` (flat) when insufficient data — kept finite so the JSON response stays valid.
        ema_position:    ``"above"`` or ``"below"`` (close vs EMA20).
        strength:        Direction strength in [0, 1] derived from MACD histogram.
    """

    timeframe: str
    trend: str        # "bullish" | "bearish" | "neutral"
    rsi: float
    macd_histogram: float
    ema_position: str  # "above" | "below"
    strength: float = Field(..., ge=0.0, le=1.0)


class MTFAnalysis(BaseModel):
    """Multi-timeframe confluence analysis for one symbol.

    Attributes:
        symbol:     Instrument symbol.
        signals:    Per-timeframe signal list, ordered by input key order.
        confluence: Fraction of timeframes agreeing with the overall direction
                    (0 = no agreement, 1 = unanimous).
        overall:    Aggregated direction: ``"bullish"``, ``"bearish"``, or ``"neutral"``.
    """

    symbol: str
    signals: list[TimeframeSignal]
    confluence: float = Field(..., ge=0.0, le=1.0)
    overall: str  # "bullish" | "bearish" | "neutral"


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class MultiTimeframeAnalyser:
    """Compute signal alignment across multiple timeframes for a symbol.

    Usage::

        analyser = MultiTimeframeAnalyser()

        bars_5m  = [{"timestamp": ..., "open": ..., "high": ...,
                     "low": ..., "close": ..., "volume": ...}, ...]
        bars_15m = [...]

        result = analyser.analyse(
            symbol="NIFTY",
            data_by_tf={"5m": bars_5m, "15m": bars_15m},
        )
    """

    def analyse(
        self,
        symbol: str,
        data_by_tf: dict[str, list[dict]],
    ) -> MTFAnalysis:
        """Analyse signal alignment across timeframes.

        For each timeframe with at least ``_MIN_BARS`` bars, a
        ``TimeframeSignal`` is computed.  Timeframes with insufficient data
        are skipped with a warning.

        Args:
            symbol:      Instrument symbol (used for labelling only).
            data_by_tf:  Dict mapping timeframe label → list of OHLCV bar dicts.
                         Each bar must have keys: ``open``, ``high``, ``low``,
                         ``close``, ``volume`` (numeric), and optionally
                         ``timestamp``.

        Returns:
            MTFAnalysis with per-timeframe signals, confluence score, and
            overall direction.
        """
        signals: list[TimeframeSignal] = []

        for tf, bars in data_by_tf.items():
            if len(bars) < _MIN_BARS:
                logger.warning(
                    "Symbol %s, timeframe %s: only %d bars (min %d) — skipping",
                    symbol, tf, len(bars), _MIN_BARS,
                )
                continue

            sig = self._analyse_timeframe(tf, bars)
            signals.append(sig)

        confluence, overall = self._compute_confluence(signals)

        return MTFAnalysis(
            symbol=symbol,
            signals=signals,
            confluence=round(confluence, 4),
            overall=overall,
        )

    # ---------------------------------------------------------------------- #
    # Private helpers                                                          #
    # ---------------------------------------------------------------------- #

    def _analyse_timeframe(
        self,
        timeframe: str,
        bars: list[dict],
    ) -> TimeframeSignal:
        """Compute signal for a single timeframe.

        Args:
            timeframe: Timeframe label.
            bars:      List of OHLCV bar dicts, at least ``_MIN_BARS`` long.

        Returns:
            TimeframeSignal for this timeframe.
        """
        close = np.array([float(b["close"]) for b in bars], dtype=np.float64)
        n = len(close)

        # --- EMA20 & EMA50 (trend + position) ---
        ema20_series = _ema(close, _EMA_FAST) if n >= _EMA_FAST else np.full(n, math.nan)
        ema50_series = _ema(close, _EMA_SLOW) if n >= _EMA_SLOW else np.full(n, math.nan)

        last_ema20 = self._last_valid(ema20_series)
        last_ema50 = self._last_valid(ema50_series)

        trend = self._classify_trend(last_ema20, last_ema50)
        ema_position = self._classify_ema_position(close[-1], last_ema20)

        # --- RSI ---
        rsi_val = math.nan
        if n >= _RSI_PERIOD + 2:
            try:
                rsi_series = _rsi(close, _RSI_PERIOD)
                rsi_val = self._last_valid(rsi_series)
            except Exception as exc:
                logger.debug("RSI failed for %s: %s", timeframe, exc)

        # --- MACD ---
        macd_hist_val = math.nan
        if n >= _MACD_SLOW + _MACD_SIGNAL:
            try:
                _, _, hist = _macd(close, _MACD_FAST, _MACD_SLOW, _MACD_SIGNAL)
                macd_hist_val = self._last_valid(hist)
            except Exception as exc:
                logger.debug("MACD failed for %s: %s", timeframe, exc)

        strength = self._compute_strength(macd_hist_val, close)

        # JSON-safe sentinels for insufficient-data timeframes. A timeframe with
        # 30–34 bars clears the _MIN_BARS=30 floor (so it is not skipped) but is
        # below the MACD (35) / RSI (16) windows, leaving these values NaN. Flask
        # ``jsonify`` serialises a bare ``NaN`` token, which is invalid JSON and
        # makes the frontend ``JSON.parse`` throw — silently breaking the live
        # multi-timeframe path. Substitute neutral, finite values instead:
        # RSI 50.0 (midline) and MACD histogram 0.0 (flat → ``macdSign='flat'``).
        rsi_out = round(rsi_val, 4) if math.isfinite(rsi_val) else 50.0
        macd_out = round(macd_hist_val, 6) if math.isfinite(macd_hist_val) else 0.0

        return TimeframeSignal(
            timeframe=timeframe,
            trend=trend,
            rsi=rsi_out,
            macd_histogram=macd_out,
            ema_position=ema_position,
            strength=round(strength, 4),
        )

    @staticmethod
    def _last_valid(arr: np.ndarray) -> float:
        """Return the last non-NaN value in an array, or NaN if none.

        Args:
            arr: Numpy array, possibly containing NaN values.

        Returns:
            Last finite float, or ``math.nan``.
        """
        finite_mask = np.isfinite(arr)
        if not np.any(finite_mask):
            return math.nan
        return float(arr[np.where(finite_mask)[0][-1]])

    @staticmethod
    def _classify_trend(ema_fast: float, ema_slow: float) -> str:
        """Determine trend direction from EMA crossover.

        Args:
            ema_fast: Latest EMA20 value.
            ema_slow: Latest EMA50 value.

        Returns:
            ``"bullish"`` when EMA20 > EMA50, ``"bearish"`` when EMA20 < EMA50,
            ``"neutral"`` when either is NaN or equal.
        """
        if not math.isfinite(ema_fast) or not math.isfinite(ema_slow):
            return "neutral"
        if ema_fast > ema_slow:
            return "bullish"
        if ema_fast < ema_slow:
            return "bearish"
        return "neutral"

    @staticmethod
    def _classify_ema_position(close: float, ema20: float) -> str:
        """Determine whether close is above or below EMA20.

        Args:
            close: Latest close price.
            ema20: Latest EMA20 value.

        Returns:
            ``"above"`` or ``"below"``.  Returns ``"above"`` when EMA20 is NaN
            (insufficient data to determine position).
        """
        if not math.isfinite(ema20):
            return "above"
        return "below" if float(close) < ema20 else "above"

    @staticmethod
    def _compute_strength(macd_histogram: float, close: np.ndarray) -> float:
        """Convert MACD histogram to a normalised [0, 1] strength score.

        Uses tanh scaling relative to 0.5% of mean close price so that the
        metric is comparable across instruments at very different price levels.

        Args:
            macd_histogram: Latest MACD histogram value.  NaN → 0.0.
            close:          Close price array (for scale reference).

        Returns:
            Strength value in [0.0, 1.0].
        """
        if not math.isfinite(macd_histogram):
            return 0.0
        mean_px = float(np.mean(close))
        if mean_px <= 0.0:
            return 0.0
        scale = mean_px * 0.005   # 0.5% of mean price
        return float(min(math.tanh(abs(macd_histogram) / scale), 1.0))

    @staticmethod
    def _compute_confluence(
        signals: list[TimeframeSignal],
    ) -> tuple[float, str]:
        """Compute confluence fraction and overall direction from signal list.

        Each signal's ``trend`` casts a directional vote.  Signals with trend
        ``"neutral"`` cast no vote.  Confluence is the fraction of non-neutral
        timeframes that agree with the majority direction.

        Args:
            signals: List of TimeframeSignal objects.

        Returns:
            Tuple of (confluence, overall_direction).
        """
        if not signals:
            return 0.0, "neutral"

        votes: list[int] = []
        for sig in signals:
            if sig.trend == "bullish":
                votes.append(1)
            elif sig.trend == "bearish":
                votes.append(-1)
            # "neutral" → no vote

        if not votes:
            return 0.0, "neutral"

        bull_count = votes.count(1)
        bear_count = votes.count(-1)
        total = len(votes)

        if bull_count > bear_count:
            majority_direction = "bullish"
            majority_count = bull_count
        elif bear_count > bull_count:
            majority_direction = "bearish"
            majority_count = bear_count
        else:
            # Tie — neutral
            return round(0.5, 4), "neutral"

        confluence = majority_count / total
        overall = majority_direction if confluence >= _CONFLUENCE_THRESHOLD else "neutral"
        return round(confluence, 4), overall


# ---------------------------------------------------------------------------
# Sample data factory (used by routes in dev/fallback mode)
# ---------------------------------------------------------------------------


def make_sample_mtf_data(
    timeframes: list[str] | None = None,
    n_bars: int = 200,
    seed: int = 42,
) -> dict[str, list[dict]]:
    """Generate deterministic synthetic multi-timeframe OHLCV data.

    Args:
        timeframes: List of timeframe labels (default: ``["5m", "15m", "1h", "1D"]``).
        n_bars:     Number of bars to generate per timeframe.
        seed:       Random seed for reproducibility.

    Returns:
        Dict of timeframe → list of OHLCV bar dicts with keys
        ``timestamp``, ``open``, ``high``, ``low``, ``close``, ``volume``.
    """
    if timeframes is None:
        timeframes = ["5m", "15m", "1h", "1D"]

    rng = np.random.default_rng(seed)
    result: dict[str, list[dict]] = {}

    for tf in timeframes:
        close = 24000.0
        bars: list[dict] = []
        for i in range(n_bars):
            ret = rng.standard_normal() * 0.004
            close = max(close * (1.0 + ret), 1.0)
            spread = close * 0.002
            open_ = close + rng.uniform(-spread, spread)
            high = max(open_, close) + abs(rng.standard_normal()) * spread * 0.5
            low = min(open_, close) - abs(rng.standard_normal()) * spread * 0.5
            volume = rng.uniform(1_000, 50_000)
            bars.append({
                "timestamp": f"2025-01-{(i % 28) + 1:02d}T{(i % 24):02d}:00:00",
                "open": round(open_, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "volume": round(volume, 0),
            })
        result[tf] = bars

    return result
