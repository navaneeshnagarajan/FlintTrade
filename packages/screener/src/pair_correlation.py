"""Pair correlation and spread divergence engine.

Analyses correlated instrument pairs for statistical divergence (z-score of
the price spread).  Useful for identifying mean-reversion and momentum
continuation opportunities in Indian markets.

Preset pairs cover the most liquid Nifty/BankNifty baskets plus selected
commodity/FX cross:

    ("NIFTY", "BANKNIFTY")   — index pair
    ("RELIANCE", "NIFTY")    — large-cap vs index
    ("HDFCBANK", "BANKNIFTY") — banking pair
    ("TCS", "INFY")           — IT sector pair
    ("GOLD", "USDINR")        — commodity/FX pair

Algorithm::

    returns_a[i] = (prices_a[i] - prices_a[i-1]) / prices_a[i-1]
    correlation  = Pearson(returns_a, returns_b)
    spread[i]    = prices_a[i] - prices_b[i]
    mean_spread  = mean(spread)
    std_spread   = std(spread, ddof=1)
    z_score      = (spread[-1] - mean_spread) / std_spread

Signal classification:
    z > +1.5   → "diverging"   (spread expanding above mean)
    z < -1.5   → "diverging"   (spread contracting below mean)
    |z| < 0.5  → "converging"  (spread near mean, possible reversion)
    otherwise  → "neutral"

Integration:
- Flask route in pair_routes.py exposes this via POST /ft-api/v1/analytics/pairs.
"""

from __future__ import annotations

import logging

import numpy as np
from pydantic import BaseModel, Field

logger = logging.getLogger("flinttrade.screener.pair_correlation")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIN_OBSERVATIONS: int = 10
_DIVERGE_THRESHOLD: float = 1.5   # |z| > this → diverging
_CONVERGE_THRESHOLD: float = 0.5  # |z| < this → converging


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class PairSignal(BaseModel):
    """Signal for a single instrument pair.

    Attributes:
        pair:           Two-element tuple of symbol names, e.g. ``("TCS", "INFY")``.
        correlation:    Pearson correlation of log/simple returns, rounded to 4 dp.
        current_spread: Most recent spread value (prices_a[-1] - prices_b[-1]).
        mean_spread:    Mean spread over the lookback window.
        std_spread:     Standard deviation of the spread (ddof=1).
        z_score:        (current_spread - mean_spread) / std_spread.
                        0.0 when std_spread is 0 or data is insufficient.
        signal:         One of ``"converging"``, ``"diverging"``, or ``"neutral"``.
    """

    pair: tuple[str, str]
    correlation: float = Field(..., ge=-1.0, le=1.0)
    current_spread: float
    mean_spread: float
    std_spread: float = Field(..., ge=0.0)
    z_score: float
    signal: str  # "converging" | "diverging" | "neutral"


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class PairCorrelationEngine:
    """Analyse instrument pairs for correlation and spread divergence.

    Usage::

        engine = PairCorrelationEngine()

        signal = engine.analyse_pair(
            returns_a=list_of_returns_for_A,
            returns_b=list_of_returns_for_B,
            prices_a=list_of_prices_for_A,
            prices_b=list_of_prices_for_B,
            pair=("TCS", "INFY"),
        )

        all_signals = engine.analyse_all_presets(data)
    """

    PRESET_PAIRS: list[tuple[str, str]] = [
        ("NIFTY", "BANKNIFTY"),
        ("RELIANCE", "NIFTY"),
        ("HDFCBANK", "BANKNIFTY"),
        ("TCS", "INFY"),
        ("GOLD", "USDINR"),
    ]

    # ---------------------------------------------------------------------- #
    # Public methods                                                           #
    # ---------------------------------------------------------------------- #

    def analyse_pair(
        self,
        returns_a: list[float],
        returns_b: list[float],
        prices_a: list[float],
        prices_b: list[float],
        pair: tuple[str, str] = ("A", "B"),
    ) -> PairSignal:
        """Analyse a single pair for correlation and spread divergence.

        Returns a PairSignal with a z-score-based directional signal.  If
        either series is too short or has zero variance the signal defaults to
        ``"neutral"`` with a z-score of 0.0.

        Args:
            returns_a: Daily/bar returns for instrument A (as decimals).
            returns_b: Daily/bar returns for instrument B (as decimals).
            prices_a:  Absolute prices for instrument A, same length as returns_a.
            prices_b:  Absolute prices for instrument B, same length as returns_b.
            pair:      Symbol names tuple, used only for labelling.

        Returns:
            PairSignal with correlation, spread statistics, z-score, and signal.
        """
        sym_a, sym_b = pair
        xa = np.asarray(returns_a, dtype=np.float64)
        xb = np.asarray(returns_b, dtype=np.float64)
        pa = np.asarray(prices_a, dtype=np.float64)
        pb = np.asarray(prices_b, dtype=np.float64)

        # Align to shortest available series
        min_ret = min(len(xa), len(xb))
        min_px = min(len(pa), len(pb))

        if min_ret < _MIN_OBSERVATIONS or min_px < 2:
            logger.warning(
                "Pair %s/%s: insufficient data (returns=%d, prices=%d), returning neutral",
                sym_a, sym_b, min_ret, min_px,
            )
            return PairSignal(
                pair=pair,
                correlation=0.0,
                current_spread=0.0,
                mean_spread=0.0,
                std_spread=0.0,
                z_score=0.0,
                signal="neutral",
            )

        xa_aligned = xa[:min_ret]
        xb_aligned = xb[:min_ret]

        # Remove non-finite values pairwise before computing correlation
        finite_mask = np.isfinite(xa_aligned) & np.isfinite(xb_aligned)
        xa_clean = xa_aligned[finite_mask]
        xb_clean = xb_aligned[finite_mask]

        if len(xa_clean) < _MIN_OBSERVATIONS:
            corr = 0.0
        else:
            raw_corr = float(np.corrcoef(xa_clean, xb_clean)[0, 1])
            corr = round(raw_corr if np.isfinite(raw_corr) else 0.0, 4)

        # Spread statistics over the price window
        pa_aligned = pa[:min_px]
        pb_aligned = pb[:min_px]
        spread = pa_aligned - pb_aligned

        current_spread = float(spread[-1])
        mean_spread = float(np.mean(spread))
        std_spread = float(np.std(spread, ddof=1)) if len(spread) > 1 else 0.0

        if std_spread == 0.0 or not np.isfinite(std_spread):
            z_score = 0.0
        else:
            z_score = round(float((current_spread - mean_spread) / std_spread), 4)

        signal = self._classify_signal(z_score)

        return PairSignal(
            pair=pair,
            correlation=corr,
            current_spread=round(current_spread, 4),
            mean_spread=round(mean_spread, 4),
            std_spread=round(std_spread, 4),
            z_score=z_score,
            signal=signal,
        )

    def analyse_all_presets(
        self,
        data: dict[str, dict[str, list[float]]],
    ) -> list[PairSignal]:
        """Analyse all preset pairs.

        Only pairs where both symbols have entries in ``data`` are analysed.
        Missing pairs are silently skipped and do not raise exceptions.

        Args:
            data: Dict mapping symbol name → dict with keys ``"returns"`` and
                  ``"prices"``, each a list of floats::

                      {
                          "TCS":  {"returns": [...], "prices": [...]},
                          "INFY": {"returns": [...], "prices": [...]},
                      }

        Returns:
            List of PairSignal objects, one per available preset pair.
            Order matches PRESET_PAIRS.
        """
        results: list[PairSignal] = []

        for sym_a, sym_b in self.PRESET_PAIRS:
            if sym_a not in data or sym_b not in data:
                logger.debug("Preset pair %s/%s skipped — data missing", sym_a, sym_b)
                continue

            entry_a = data[sym_a]
            entry_b = data[sym_b]

            returns_a = entry_a.get("returns", [])
            returns_b = entry_b.get("returns", [])
            prices_a = entry_a.get("prices", [])
            prices_b = entry_b.get("prices", [])

            signal = self.analyse_pair(
                returns_a=returns_a,
                returns_b=returns_b,
                prices_a=prices_a,
                prices_b=prices_b,
                pair=(sym_a, sym_b),
            )
            results.append(signal)

        return results

    # ---------------------------------------------------------------------- #
    # Private helpers                                                          #
    # ---------------------------------------------------------------------- #

    @staticmethod
    def _classify_signal(z_score: float) -> str:
        """Classify z-score into a directional signal label.

        Args:
            z_score: Standardised spread deviation.

        Returns:
            ``"diverging"`` when |z| > 1.5 (spread expanding away from mean).
            ``"converging"`` when |z| < 0.5 (spread near mean, likely to revert).
            ``"neutral"`` otherwise.
        """
        abs_z = abs(z_score)
        if abs_z > _DIVERGE_THRESHOLD:
            return "diverging"
        if abs_z < _CONVERGE_THRESHOLD:
            return "converging"
        return "neutral"


# ---------------------------------------------------------------------------
# Sample data factory (used by routes in dev/fallback mode)
# ---------------------------------------------------------------------------


def make_sample_pair_data(
    n: int = 60,
    seed: int = 42,
) -> dict[str, dict[str, list[float]]]:
    """Generate deterministic synthetic pair data for all preset pairs.

    Prices and returns are loosely realistic for Indian market instruments.

    Args:
        n:    Number of bars to generate per symbol.
        seed: Random seed for reproducibility.

    Returns:
        Dict of symbol → ``{"returns": [...], "prices": [...]}``.
    """
    rng = np.random.default_rng(seed)

    base_prices: dict[str, float] = {
        "NIFTY": 24000.0,
        "BANKNIFTY": 52000.0,
        "RELIANCE": 1450.0,
        "HDFCBANK": 1650.0,
        "TCS": 3800.0,
        "INFY": 1700.0,
        "GOLD": 72000.0,
        "USDINR": 83.5,
    }

    result: dict[str, dict[str, list[float]]] = {}

    # Common market factor
    market_ret = rng.standard_normal(n) * 0.008

    correlation_factors: dict[str, float] = {
        "NIFTY": 1.0,
        "BANKNIFTY": 1.1,
        "RELIANCE": 0.8,
        "HDFCBANK": 1.05,
        "TCS": 0.7,
        "INFY": 0.7,
        "GOLD": -0.3,
        "USDINR": -0.5,
    }

    for sym, base_px in base_prices.items():
        factor = correlation_factors.get(sym, 0.5)
        idio = rng.standard_normal(n) * 0.003
        rets = market_ret * factor + idio
        prices = [base_px]
        for r in rets[1:]:
            prices.append(round(prices[-1] * (1.0 + r), 2))
        result[sym] = {
            "returns": [round(float(r), 6) for r in rets],
            "prices": prices,
        }

    return result
