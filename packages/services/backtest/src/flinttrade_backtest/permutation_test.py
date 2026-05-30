"""Statistical permutation testing for backtest significance.

Distinguishes skill from luck by comparing a strategy's observed metric
against a null distribution built from randomly shuffled returns or trades.

Two tests are provided:
- ``test_returns``: shuffles daily return signs to test if return series alpha
  is significant.
- ``test_trades``: randomly samples same-size trade sets from the return pool
  to test if trade selection skill is real.

Additionally, ``monte_carlo_confidence`` projects equity-curve confidence bands
using the same bootstrap approach used by the existing MonteCarloSimulator.

Reference methodology: standard financial permutation testing (see e.g.
  White (2000) "A Reality Check for Data Snooping", Econometrica 68(5)).
"""

from __future__ import annotations

import logging
import math
import random
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger("flinttrade.backtest.permutation")

# Annualisation constant (matches metrics.py)
_TRADING_DAYS_PER_YEAR: int = 252
_RISK_FREE_RATE: float = 0.07  # India 7%


# ---------------------------------------------------------------------------
# Config / Result models
# ---------------------------------------------------------------------------


class PermutationConfig(BaseModel):
    """Configuration for a permutation test run.

    Attributes:
        n_permutations: Number of random shuffles to build the null distribution.
        confidence_level: Significance threshold (e.g. 0.95 → p < 0.05 is
            significant).
        metric: Which performance metric to test.  Supported values:
            ``"sharpe_ratio"``, ``"total_return"``, ``"sortino_ratio"``,
            ``"profit_factor"``.
        random_seed: RNG seed for reproducibility.  ``None`` uses OS entropy.
    """

    n_permutations: int = Field(default=1000, ge=100, le=100_000)
    confidence_level: float = Field(default=0.95, ge=0.5, le=0.9999)
    metric: Literal[
        "sharpe_ratio", "total_return", "sortino_ratio", "profit_factor"
    ] = "sharpe_ratio"
    random_seed: int | None = 42


class PermutationResult(BaseModel):
    """Result of a single permutation test.

    Attributes:
        original_metric: Observed value of the tested metric on the real strategy.
        permutation_mean: Mean metric value across all random permutations.
        permutation_std: Standard deviation of the permutation distribution.
        p_value: Fraction of permutations that equalled or exceeded the original
            metric.  Lower is better — ``p_value < (1 - confidence_level)``
            means the result is statistically significant.
        is_significant: Whether ``p_value < (1 - confidence_level)``.
        confidence_level: The confidence level used for the significance test
            (copied from :class:`PermutationConfig`).
        n_permutations: Number of permutations actually run.
        percentile_rank: Where the original metric sits in the permutation
            distribution, expressed as a percentile (0–100).  100 means the
            original beat every permutation.
    """

    original_metric: float
    permutation_mean: float
    permutation_std: float
    p_value: float
    is_significant: bool
    confidence_level: float
    n_permutations: int
    percentile_rank: float

    def as_dict(self) -> dict[str, float | bool | int]:
        """Flat dict for JSON serialisation."""
        return self.model_dump()


# ---------------------------------------------------------------------------
# Metric computation helpers
# ---------------------------------------------------------------------------


def _sharpe(returns: list[float]) -> float:
    """Annualised Sharpe ratio from a daily return series."""
    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0
    if std == 0:
        return 0.0
    daily_rf = _RISK_FREE_RATE / _TRADING_DAYS_PER_YEAR
    return (mean - daily_rf) / std * math.sqrt(_TRADING_DAYS_PER_YEAR)


def _sortino(returns: list[float]) -> float:
    """Annualised Sortino ratio from a daily return series."""
    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    daily_rf = _RISK_FREE_RATE / _TRADING_DAYS_PER_YEAR
    downside_sq = [min(0.0, r - daily_rf) ** 2 for r in returns]
    downside_dev = math.sqrt(sum(downside_sq) / n)
    if downside_dev == 0:
        return 0.0
    return (mean - daily_rf) / downside_dev * math.sqrt(_TRADING_DAYS_PER_YEAR)


def _total_return(returns: list[float]) -> float:
    """Cumulative return as a percentage."""
    equity = 1.0
    for r in returns:
        equity *= 1.0 + r
    return (equity - 1.0) * 100.0


def _profit_factor(pnls: list[float]) -> float:
    """Gross profit / gross loss.  Returns 0 when there are no losses."""
    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    if gross_loss == 0:
        return float("inf") if gross_win > 0 else 0.0
    return gross_win / gross_loss


def _compute_metric(
    returns: list[float],
    metric: str,
) -> float:
    """Dispatch to the correct metric function.

    Args:
        returns: Daily return series (as fractions, not percentages).
        metric:  One of the supported metric names.

    Returns:
        Scalar metric value.
    """
    if metric == "sharpe_ratio":
        return _sharpe(returns)
    if metric == "sortino_ratio":
        return _sortino(returns)
    if metric == "total_return":
        return _total_return(returns)
    if metric == "profit_factor":
        return _profit_factor(returns)
    raise ValueError(f"Unsupported metric: {metric!r}")


# ---------------------------------------------------------------------------
# Internal: permutation null distribution builders
# ---------------------------------------------------------------------------


def _build_return_null_distribution(
    returns: list[float],
    metric: str,
    n_permutations: int,
    rng: random.Random,
) -> list[float]:
    """Shuffle returns N times; compute metric each time.

    This tests whether the *ordering* of returns matters, i.e. whether the
    strategy's entry/exit timing adds value.  The total P&L is preserved across
    shuffles; only sequence-dependent metrics (Sharpe, Sortino) vary.

    Args:
        returns:       Daily strategy return series.
        metric:        Metric name.
        n_permutations: Number of shuffles.
        rng:           Seeded random.Random instance.

    Returns:
        List of metric values, one per permutation.
    """
    null: list[float] = []
    buf = list(returns)
    for _ in range(n_permutations):
        rng.shuffle(buf)
        null.append(_compute_metric(buf, metric))
    return null


def _build_trade_null_distribution(
    n_trades: int,
    all_returns: list[float],
    metric: str,
    n_permutations: int,
    rng: random.Random,
) -> list[float]:
    """Sample ``n_trades`` returns from ``all_returns`` without replacement.

    Models the question: "Could a random trader, picking the same number of
    trades from this return pool, have achieved the same metric?"

    When the pool is smaller than ``n_trades``, sampling is done with
    replacement.

    Args:
        n_trades:       Number of trades the strategy actually made.
        all_returns:    Full return series the strategy traded over.
        metric:         Metric name.
        n_permutations: Number of random draws.
        rng:            Seeded RNG.

    Returns:
        List of metric values, one per permutation.
    """
    null: list[float] = []
    replace = n_trades > len(all_returns)
    for _ in range(n_permutations):
        if replace:
            sample = [rng.choice(all_returns) for _ in range(n_trades)]
        else:
            sample = rng.sample(all_returns, n_trades)
        null.append(_compute_metric(sample, metric))
    return null


# ---------------------------------------------------------------------------
# Internal: result builder from observed metric + null distribution
# ---------------------------------------------------------------------------


def _build_result(
    original: float,
    null: list[float],
    config: PermutationConfig,
) -> PermutationResult:
    """Compute p-value and percentile rank from null distribution.

    Args:
        original: Observed metric on the real strategy.
        null:     Null distribution values.
        config:   Permutation configuration (for threshold and N).

    Returns:
        :class:`PermutationResult`.
    """
    n = len(null)
    if n == 0:
        return PermutationResult(
            original_metric=original,
            permutation_mean=0.0,
            permutation_std=0.0,
            p_value=1.0,
            is_significant=False,
            confidence_level=config.confidence_level,
            n_permutations=0,
            percentile_rank=0.0,
        )

    mean = sum(null) / n
    variance = sum((v - mean) ** 2 for v in null) / max(1, n - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0

    # p-value: proportion of permutations >= original (one-sided, upper tail)
    n_exceeds = sum(1 for v in null if v >= original)
    p_value = n_exceeds / n

    # Percentile rank: fraction of permutations BELOW the original
    n_below = sum(1 for v in null if v < original)
    percentile_rank = (n_below / n) * 100.0

    alpha = 1.0 - config.confidence_level
    is_significant = p_value < alpha

    return PermutationResult(
        original_metric=original,
        permutation_mean=mean,
        permutation_std=std,
        p_value=p_value,
        is_significant=is_significant,
        confidence_level=config.confidence_level,
        n_permutations=n,
        percentile_rank=percentile_rank,
    )


# ---------------------------------------------------------------------------
# Equity-curve helpers
# ---------------------------------------------------------------------------


def _build_equity_curve(returns: list[float], initial: float = 100.0) -> list[float]:
    """Convert a return series into a cumulative equity curve.

    Args:
        returns: Daily returns (fractions).
        initial: Starting equity value.

    Returns:
        List of equity values (length = len(returns) + 1, starting with *initial*).
    """
    equity = initial
    curve = [equity]
    for r in returns:
        equity *= 1.0 + r
        curve.append(equity)
    return curve


def _percentile_at(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolation percentile from a sorted list.

    Args:
        sorted_values: Pre-sorted list of floats.
        pct:           Percentile in [0, 100].

    Returns:
        Interpolated value.
    """
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    idx = pct / 100.0 * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class PermutationTester:
    """Statistical significance testing for backtest results.

    Tests whether a strategy's performance metric exceeds what could be
    achieved by randomly shuffling entries/exits (``test_returns``) or by
    randomly picking the same number of trades from the return pool
    (``test_trades``).

    Usage::

        config = PermutationConfig(n_permutations=2000, metric="sharpe_ratio")
        tester = PermutationTester(config)
        result = tester.test_returns(strategy_daily_returns)
        print(f"p-value: {result.p_value:.4f}")
        print(f"Significant: {result.is_significant}")
        print(f"Percentile rank: {result.percentile_rank:.1f}")
    """

    def __init__(self, config: PermutationConfig | None = None) -> None:
        """Initialise the tester.

        Args:
            config: Configuration.  Uses defaults when ``None``.
        """
        self.config = config or PermutationConfig()
        self._rng = random.Random(self.config.random_seed)

    # ------------------------------------------------------------------
    # Public test methods
    # ------------------------------------------------------------------

    def test_returns(
        self,
        strategy_returns: list[float],
        benchmark_returns: list[float] | None = None,
    ) -> PermutationResult:
        """Test if strategy returns are statistically significant.

        Shuffles the daily return series N times and recomputes the chosen
        metric each time.  The original metric is then compared to this null
        distribution to derive a p-value.

        If ``benchmark_returns`` is provided, the metric is computed on the
        *excess* return series (strategy − benchmark) so that a neutral
        passive index does not appear significant.

        Args:
            strategy_returns:  Daily strategy returns (as fractions, not %).
                               Must contain at least 3 values.
            benchmark_returns: Optional daily benchmark returns of the same
                               length as ``strategy_returns``.

        Returns:
            :class:`PermutationResult` with significance verdict.

        Raises:
            ValueError: If ``strategy_returns`` is empty or too short.
        """
        if len(strategy_returns) < 3:
            raise ValueError(
                "strategy_returns must contain at least 3 values; "
                f"got {len(strategy_returns)}"
            )

        if benchmark_returns is not None:
            if len(benchmark_returns) != len(strategy_returns):
                raise ValueError(
                    "benchmark_returns must have the same length as strategy_returns"
                )
            test_series = [
                s - b for s, b in zip(strategy_returns, benchmark_returns)
            ]
        else:
            test_series = list(strategy_returns)

        original = _compute_metric(test_series, self.config.metric)
        null = _build_return_null_distribution(
            test_series,
            self.config.metric,
            self.config.n_permutations,
            self._rng,
        )

        logger.debug(
            "test_returns: metric=%s original=%.4f null_mean=%.4f n=%d",
            self.config.metric, original, sum(null) / len(null) if null else 0, len(null),
        )
        return _build_result(original, null, self.config)

    def test_trades(
        self,
        trades: list[dict],
        all_returns: list[float],
    ) -> PermutationResult:
        """Test if trade selection skill is statistically significant.

        Randomly samples the same number of trades as the strategy actually
        made from the full return pool, recomputing the chosen metric each
        time.  The strategy's original metric is compared to this random
        baseline.

        Each dict in ``trades`` must contain either a ``"return_pct"`` key
        (fraction) or a ``"net_pnl"`` key (used as a proxy return).

        Args:
            trades:      List of trade dicts.  Required keys: one of
                         ``"return_pct"`` (float) or ``"net_pnl"`` (float).
            all_returns: Full return series the strategy operated over.
                         Must have at least ``len(trades)`` elements for
                         without-replacement sampling.

        Returns:
            :class:`PermutationResult` with significance verdict.

        Raises:
            ValueError: If ``trades`` is empty or ``all_returns`` is empty.
        """
        if not trades:
            raise ValueError("trades must be non-empty")
        if not all_returns:
            raise ValueError("all_returns must be non-empty")

        # Extract per-trade return series
        trade_returns = _extract_trade_returns(trades)
        original = _compute_metric(trade_returns, self.config.metric)

        null = _build_trade_null_distribution(
            len(trades),
            all_returns,
            self.config.metric,
            self.config.n_permutations,
            self._rng,
        )

        logger.debug(
            "test_trades: metric=%s n_trades=%d original=%.4f",
            self.config.metric, len(trades), original,
        )
        return _build_result(original, null, self.config)

    def monte_carlo_confidence(
        self,
        equity_curve: list[float],
        n_simulations: int = 1000,
    ) -> dict[str, list[float]]:
        """Build Monte Carlo confidence bands on an equity curve.

        Converts the equity curve to a daily return series, then generates
        ``n_simulations`` random permutations to produce percentile bands.
        Each simulated path shares the same set of daily returns as the
        original — only the ordering differs.

        Args:
            equity_curve:  Equity values over time (must have at least 2
                           points).
            n_simulations: Number of random paths to generate.

        Returns:
            Dict with keys ``"p5"``, ``"p25"``, ``"p50"``, ``"p75"``,
            ``"p95"``, each mapping to an equity-curve list of the same
            length as ``equity_curve``.

        Raises:
            ValueError: If ``equity_curve`` has fewer than 2 points.
        """
        if len(equity_curve) < 2:
            raise ValueError(
                "equity_curve must have at least 2 points; "
                f"got {len(equity_curve)}"
            )

        # Convert equity curve to daily returns
        returns: list[float] = []
        for i in range(1, len(equity_curve)):
            prev = equity_curve[i - 1]
            curr = equity_curve[i]
            if prev > 0:
                returns.append((curr - prev) / prev)
            else:
                returns.append(0.0)

        initial = equity_curve[0]
        n_bars = len(returns)
        paths: list[list[float]] = []

        buf = list(returns)
        for _ in range(n_simulations):
            self._rng.shuffle(buf)
            paths.append(_build_equity_curve(buf, initial=initial))

        # At each time step collect the cross-sectional distribution
        n_steps = n_bars + 1  # equity_curve length
        p5_curve: list[float] = []
        p25_curve: list[float] = []
        p50_curve: list[float] = []
        p75_curve: list[float] = []
        p95_curve: list[float] = []

        for t in range(n_steps):
            cross_section = sorted(path[t] for path in paths)
            p5_curve.append(_percentile_at(cross_section, 5.0))
            p25_curve.append(_percentile_at(cross_section, 25.0))
            p50_curve.append(_percentile_at(cross_section, 50.0))
            p75_curve.append(_percentile_at(cross_section, 75.0))
            p95_curve.append(_percentile_at(cross_section, 95.0))

        return {
            "p5": p5_curve,
            "p25": p25_curve,
            "p50": p50_curve,
            "p75": p75_curve,
            "p95": p95_curve,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_trade_returns(trades: list[dict]) -> list[float]:
    """Extract a return series from a list of trade dicts.

    Tries ``"return_pct"`` first, then ``"net_pnl"`` as a fallback proxy.
    ``net_pnl`` is not normalised — it is treated directly as the return
    value in the metric computation.

    Args:
        trades: List of trade dicts.

    Returns:
        List of float return values, one per trade.

    Raises:
        ValueError: If neither key is present in any trade.
    """
    result: list[float] = []
    for i, trade in enumerate(trades):
        if "return_pct" in trade:
            result.append(float(trade["return_pct"]))
        elif "net_pnl" in trade:
            result.append(float(trade["net_pnl"]))
        else:
            raise ValueError(
                f"Trade at index {i} must contain 'return_pct' or 'net_pnl' key"
            )
    return result
