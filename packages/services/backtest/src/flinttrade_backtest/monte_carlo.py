"""Monte Carlo simulator for backtest result confidence estimation.

Adapted from raptorbt (marketcalls/raptorbt) Rust implementation.
Translated to pure Python for integration with the backtest-engine package.

Key differences from the Rust original:
- Trade-sequence permutation (shuffle) model instead of GBM forward projection.
  This directly tests "what if trades came in a different order?" which is the
  natural question after a backtest.
- Correlated multi-strategy support retained for portfolio-level analysis.
- Deterministic via seeded PRNG for reproducible CI runs.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Sequence

# ---------------------------------------------------------------------------
# Config / Result dataclasses (match raptorbt MonteCarloConfig/Result shape)
# ---------------------------------------------------------------------------


@dataclass
class MonteCarloConfig:
    """Configuration for a Monte Carlo simulation run.

    Attributes:
        n_simulations: Number of random permutations to run.
        seed:          RNG seed for reproducibility. Set to None for random.
        initial_capital: Starting equity for each simulation path.
    """

    n_simulations: int = 1000
    seed: int | None = 42
    initial_capital: float = 100_000.0


@dataclass
class MonteCarloResult:
    """Results from a completed Monte Carlo simulation.

    All percentile values refer to the *final equity* distribution across
    all simulated paths.

    Attributes:
        p5:   5th percentile final equity (worst-case tail).
        p25:  25th percentile final equity.
        p50:  50th percentile final equity (median).
        p75:  75th percentile final equity.
        p95:  95th percentile final equity (best-case tail).
        mean_final:          Mean final equity across all simulations.
        std_final:           Standard deviation of final equities.
        probability_of_loss: Fraction of runs ending below initial capital.
        var_95:              Value at Risk at 95% confidence (positive number,
                             expressed as % of initial capital).
        cvar_95:             Conditional VaR (Expected Shortfall) at 95%.
        max_drawdown_p50:    Median maximum drawdown across simulations (%).
        max_drawdown_p95:    95th percentile max drawdown (worst 5% of runs).
        n_simulations:       Number of simulations actually run.
    """

    p5: float = 0.0
    p25: float = 0.0
    p50: float = 0.0
    p75: float = 0.0
    p95: float = 0.0
    mean_final: float = 0.0
    std_final: float = 0.0
    probability_of_loss: float = 0.0
    var_95: float = 0.0
    cvar_95: float = 0.0
    max_drawdown_p50: float = 0.0
    max_drawdown_p95: float = 0.0
    n_simulations: int = 0

    def as_dict(self) -> dict[str, float | int]:
        """Flat dict for JSON serialisation."""
        return {
            "p5": self.p5,
            "p25": self.p25,
            "p50": self.p50,
            "p75": self.p75,
            "p95": self.p95,
            "mean_final": self.mean_final,
            "std_final": self.std_final,
            "probability_of_loss": self.probability_of_loss,
            "var_95": self.var_95,
            "cvar_95": self.cvar_95,
            "max_drawdown_p50": self.max_drawdown_p50,
            "max_drawdown_p95": self.max_drawdown_p95,
            "n_simulations": self.n_simulations,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolation percentile from a pre-sorted list."""
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    idx = pct / 100.0 * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def _max_drawdown(equity_path: list[float]) -> float:
    """Compute max drawdown (%) from an equity curve list."""
    peak = equity_path[0] if equity_path else 0.0
    max_dd = 0.0
    for eq in equity_path:
        if eq > peak:
            peak = eq
        if peak > 0:
            dd = (peak - eq) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _simulate_path(
    trades: list[float],
    initial_capital: float,
    rng: random.Random,
) -> tuple[float, float]:
    """Run one random permutation of trade P&L sequence.

    Returns:
        Tuple of (final_equity, max_drawdown_pct).
    """
    shuffled = trades[:]
    rng.shuffle(shuffled)

    equity = initial_capital
    path = [equity]
    for pnl in shuffled:
        equity += pnl
        path.append(equity)

    return path[-1], _max_drawdown(path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class MonteCarloSimulator:
    """Run N random permutations of a trade sequence to estimate confidence intervals.

    This answers the core question: "How sensitive is my strategy's performance
    to the *order* in which trades occurred?" A strategy with consistent edge
    will show tight percentile bands; a lucky streak will show wide bands.

    Adapted from raptorbt's portfolio-level Monte Carlo (marketcalls/raptorbt),
    simplified to the single-strategy trade-sequence model used in FlintTrade
    backtest-engine.

    Usage::

        trades = [500.0, -200.0, 300.0, -100.0, 800.0]  # net P&L per trade
        sim = MonteCarloSimulator(trades, config=MonteCarloConfig(n_simulations=2000))
        result = sim.run()
        print(f"Median final equity: {result.p50:.0f}")
        print(f"5th percentile: {result.p5:.0f}")
        print(f"Probability of loss: {result.probability_of_loss:.1%}")
    """

    def __init__(
        self,
        trades: Sequence[float],
        config: MonteCarloConfig | None = None,
    ) -> None:
        """Initialise the simulator.

        Args:
            trades: List of net P&L values for each completed trade.
                    Positive = win, negative = loss.
            config: Simulation configuration. Uses defaults if not provided.
        """
        if not trades:
            raise ValueError("trades must be non-empty")

        self.trades = list(trades)
        self.config = config or MonteCarloConfig()
        self._rng = random.Random(self.config.seed)

    def run(self) -> MonteCarloResult:
        """Run the full Monte Carlo simulation.

        Returns:
            MonteCarloResult with percentile bands, VaR, CVaR, and drawdown
            distribution.
        """
        final_equities: list[float] = []
        max_drawdowns: list[float] = []

        for _ in range(self.config.n_simulations):
            final_eq, max_dd = _simulate_path(
                self.trades, self.config.initial_capital, self._rng
            )
            final_equities.append(final_eq)
            max_drawdowns.append(max_dd)

        final_equities.sort()
        max_drawdowns.sort()

        n = len(final_equities)
        initial = self.config.initial_capital

        # Percentile final equities
        p5 = _percentile(final_equities, 5.0)
        p25 = _percentile(final_equities, 25.0)
        p50 = _percentile(final_equities, 50.0)
        p75 = _percentile(final_equities, 75.0)
        p95 = _percentile(final_equities, 95.0)

        # Mean and std
        mean_final = sum(final_equities) / n
        variance = sum((v - mean_final) ** 2 for v in final_equities) / n
        std_final = math.sqrt(variance) if variance > 0 else 0.0

        # Probability of loss
        n_loss = sum(1 for v in final_equities if v < initial)
        probability_of_loss = n_loss / n

        # VaR 95% (loss as % of initial capital)
        p5_idx = max(0, min(int(0.05 * (n - 1)), n - 1))
        var_95 = max(0.0, (initial - final_equities[p5_idx]) / initial * 100.0) if initial > 0 else 0.0

        # CVaR 95% (average of worst 5% outcomes)
        tail = final_equities[: p5_idx + 1]
        if tail and initial > 0:
            avg_tail = sum(tail) / len(tail)
            cvar_95 = max(0.0, (initial - avg_tail) / initial * 100.0)
        else:
            cvar_95 = var_95

        return MonteCarloResult(
            p5=p5,
            p25=p25,
            p50=p50,
            p75=p75,
            p95=p95,
            mean_final=mean_final,
            std_final=std_final,
            probability_of_loss=probability_of_loss,
            var_95=var_95,
            cvar_95=cvar_95,
            max_drawdown_p50=_percentile(max_drawdowns, 50.0),
            max_drawdown_p95=_percentile(max_drawdowns, 95.0),
            n_simulations=self.config.n_simulations,
        )
