"""Correlation matrix computation engine.

Computes pairwise Pearson correlation matrices from return series and
provides rolling correlation between instrument pairs.

Uses numpy for efficient matrix operations and avoids external dependencies
beyond the standard scientific stack.

Integration:
- RegimeDetector (regime_detector.py) is used to enrich the matrix response
  with current market regime classification.
- The Flask route in payoff_routes.py exposes this via POST /ft-api/v1/analytics/correlation.

Adapted from:
- Standard numpy correlation patterns
- MarketCalls portfolio analysis patterns
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import numpy as np
from pydantic import BaseModel, Field

from .regime_detector import RegimeDetector, RegimeSignal, RegimeType

logger = logging.getLogger("flinttrade.screener.correlation")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_PERIOD_DAYS: int = 90
_MIN_OBSERVATIONS: int = 5   # Minimum return observations for a valid correlation
_ROLLING_WINDOW_DEFAULT: int = 30

# Default symbols for sample/fallback data
_DEFAULT_SYMBOLS: list[str] = [
    "NIFTY50", "BANKNIFTY", "IT", "GOLD", "USD/INR", "NIFTY500",
]

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CorrelationMatrix(BaseModel):
    """Correlation matrix result.

    Attributes:
        symbols: Ordered list of instrument names.
        matrix: N×N row-major Pearson correlation matrix.
        period_days: Number of days used in the calculation.
        regime: Current market regime signal.
        updated_at: ISO-format UTC timestamp of computation.
        is_sample_data: True when synthetic fallback data was used.
    """

    symbols: list[str]
    matrix: list[list[float]]
    period_days: int
    regime: RegimeSignal
    updated_at: str = Field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    is_sample_data: bool = False

    # Convenience properties not serialised (computed on access)

    def get_pair_correlation(self, sym_a: str, sym_b: str) -> float | None:
        """Return correlation between two symbols.

        Args:
            sym_a: First symbol name.
            sym_b: Second symbol name.

        Returns:
            Pearson correlation value or None if either symbol is missing.
        """
        if sym_a not in self.symbols or sym_b not in self.symbols:
            return None
        i = self.symbols.index(sym_a)
        j = self.symbols.index(sym_b)
        return self.matrix[i][j]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class CorrelationEngine:
    """Compute pairwise correlation matrices and rolling correlations.

    Usage::

        engine = CorrelationEngine()

        returns = {
            "NIFTY50":   [0.01, -0.005, 0.003, ...],   # daily returns
            "BANKNIFTY": [0.012, -0.006, 0.004, ...],
            "GOLD":      [-0.002, 0.001, -0.001, ...],
        }

        result = engine.compute(returns, period=90)
        print(result.symbols)
        print(result.matrix)      # 3×3 correlation matrix
        print(result.regime)
    """

    def __init__(self, regime_detector: RegimeDetector | None = None) -> None:
        """Initialise the engine.

        Args:
            regime_detector: Optional RegimeDetector instance.  A default
                instance is created if not provided.
        """
        self._regime_detector = regime_detector or RegimeDetector()

    def compute(
        self,
        returns: dict[str, list[float]],
        period: int = _DEFAULT_PERIOD_DAYS,
        vix: float = 15.0,
        fii_net: float | None = None,
        advance_decline: tuple[int, int] | None = None,
        breadth: float | None = None,
    ) -> CorrelationMatrix:
        """Compute pairwise Pearson correlation matrix from return series.

        Only the last `period` observations of each return series are used.
        Symbols with fewer than `_MIN_OBSERVATIONS` valid returns are excluded.

        Args:
            returns: Dict mapping symbol → list of daily returns (as decimals).
            period: Number of most-recent days to include (default 90).
            vix: Current VIX level for regime detection.
            fii_net: Net FII flow in crores (optional, for regime).
            advance_decline: (advances, declines) count tuple (optional).
            breadth: Percentage of stocks above 200 DMA (optional).

        Returns:
            CorrelationMatrix with symbols, N×N matrix, and regime signal.
        """
        # Filter and truncate return series
        valid: dict[str, np.ndarray] = {}
        for sym, rets in returns.items():
            arr = np.asarray(rets[-period:], dtype=float)
            arr = arr[np.isfinite(arr)]
            if len(arr) >= _MIN_OBSERVATIONS:
                valid[sym] = arr
            else:
                logger.warning("Symbol %s has only %d valid returns — skipping", sym, len(arr))

        symbols = list(valid.keys())
        n = len(symbols)

        if n == 0:
            logger.warning("No valid return series — returning identity matrix")
            regime = self._detect_regime(vix, [], fii_net, advance_decline, breadth)
            return CorrelationMatrix(
                symbols=[],
                matrix=[],
                period_days=period,
                regime=regime,
                is_sample_data=True,
            )

        # Align lengths: pad shorter series with NaN, then compute pairwise
        matrix_arr = np.full((n, n), np.nan)

        for i in range(n):
            for j in range(i, n):
                xi = valid[symbols[i]]
                xj = valid[symbols[j]]
                # Use the overlapping (minimum length) window
                min_len = min(len(xi), len(xj))
                if min_len < _MIN_OBSERVATIONS:
                    corr = float("nan")
                elif i == j:
                    corr = 1.0
                else:
                    corr = float(np.corrcoef(xi[-min_len:], xj[-min_len:])[0, 1])
                    # Guard against NaN from zero-variance series
                    if not np.isfinite(corr):
                        corr = 0.0

                matrix_arr[i, j] = corr
                matrix_arr[j, i] = corr

        # Replace any remaining NaN diagonal entries with 1.0
        np.fill_diagonal(matrix_arr, 1.0)
        # Replace remaining off-diagonal NaN with 0.0
        matrix_arr = np.nan_to_num(matrix_arr, nan=0.0)

        # Detect regime (use first symbol's returns for Nifty context if available)
        nifty_rets: list[float] = []
        if symbols:
            nifty_rets = list(valid[symbols[0]])

        regime = self._detect_regime(vix, nifty_rets, fii_net, advance_decline, breadth)

        # Round to 4 decimal places for clean JSON
        matrix_list = [
            [round(float(v), 4) for v in row]
            for row in matrix_arr.tolist()
        ]

        logger.debug(
            "Correlation matrix computed: %d symbols, period=%d days",
            n,
            period,
        )

        return CorrelationMatrix(
            symbols=symbols,
            matrix=matrix_list,
            period_days=period,
            regime=regime,
        )

    def rolling_correlation(
        self,
        returns: dict[str, list[float]],
        pair: tuple[str, str],
        window: int = _ROLLING_WINDOW_DEFAULT,
    ) -> list[float]:
        """Compute rolling Pearson correlation between two assets.

        Args:
            returns: Dict mapping symbol → list of daily returns.
            pair: (symbol_a, symbol_b) tuple.
            window: Rolling window size in days.

        Returns:
            List of rolling correlation values.  Values before enough
            observations are available are set to 0.0.  Sorted oldest-first.
        """
        sym_a, sym_b = pair

        if sym_a not in returns or sym_b not in returns:
            logger.warning(
                "Rolling correlation: symbol(s) %s/%s not in returns dict",
                sym_a, sym_b,
            )
            return []

        xa = np.asarray(returns[sym_a], dtype=float)
        xb = np.asarray(returns[sym_b], dtype=float)
        min_len = min(len(xa), len(xb))

        if min_len < window:
            logger.warning(
                "Rolling correlation: series too short (%d < window %d)",
                min_len, window,
            )
            return [0.0] * min_len

        xa = xa[:min_len]
        xb = xb[:min_len]
        result: list[float] = [0.0] * (window - 1)

        for i in range(window - 1, min_len):
            slice_a = xa[i - window + 1 : i + 1]
            slice_b = xb[i - window + 1 : i + 1]
            corr = float(np.corrcoef(slice_a, slice_b)[0, 1])
            result.append(round(corr if np.isfinite(corr) else 0.0, 4))

        return result

    # ---------------------------------------------------------------------- #
    # Private helpers                                                         #
    # ---------------------------------------------------------------------- #

    def _detect_regime(
        self,
        vix: float,
        nifty_returns: list[float],
        fii_net: float | None,
        advance_decline: tuple[int, int] | None,
        breadth: float | None,
    ) -> RegimeSignal:
        """Delegate regime detection to RegimeDetector.

        Args:
            vix: Current VIX level.
            nifty_returns: Recent Nifty daily returns.
            fii_net: Net FII flow.
            advance_decline: Advances/declines tuple.
            breadth: Breadth percentage.

        Returns:
            RegimeSignal from the detector.
        """
        try:
            return self._regime_detector.detect(
                vix=vix,
                nifty_returns=nifty_returns,
                advance_decline=advance_decline,
                fii_net=fii_net,
                breadth=breadth,
            )
        except Exception as exc:
            logger.warning("Regime detection failed, using fallback: %s", exc)
            return RegimeSignal(
                regime=RegimeType.ROTATION,
                confidence=0.3,
                vix_level=vix,
                vix_percentile=50.0,
                rationale="Regime detection unavailable — using rotation as fallback.",
            )


# ---------------------------------------------------------------------------
# Sample data factory (used by Flask route for dev/fallback mode)
# ---------------------------------------------------------------------------

def make_sample_returns(
    n_days: int = 90,
    symbols: list[str] | None = None,
    seed: int = 42,
) -> dict[str, list[float]]:
    """Generate deterministic synthetic daily return series.

    Correlations are loosely realistic:
    - Equities (NIFTY50, BANKNIFTY, NIFTY500) are positively correlated
    - GOLD has mild negative correlation with equities
    - USD/INR has negative correlation with equities (rupee strengthens in rallies)
    - IT has moderate positive correlation with equities

    Args:
        n_days: Number of trading days to generate.
        symbols: List of symbol names. Defaults to _DEFAULT_SYMBOLS.
        seed: Random seed for reproducibility.

    Returns:
        Dict of symbol → list of daily returns.
    """
    rng = np.random.default_rng(seed)
    if symbols is None:
        symbols = list(_DEFAULT_SYMBOLS)

    n = len(symbols)
    # Build a correlation structure: all equities are correlated with each other
    # GOLD and USD/INR are inversely related to equities
    equity_factor = rng.standard_normal(n_days) * 0.008
    idio = rng.standard_normal((n, n_days)) * 0.004

    result: dict[str, list[float]] = {}
    for i, sym in enumerate(symbols):
        if sym in ("GOLD", "USD/INR"):
            # Inverse equity factor with some idiosyncratic noise
            rets = -equity_factor * 0.4 + idio[i]
        elif sym == "IT":
            rets = equity_factor * 0.7 + idio[i]
        else:
            rets = equity_factor + idio[i]

        result[sym] = [round(float(r), 6) for r in rets]

    return result
