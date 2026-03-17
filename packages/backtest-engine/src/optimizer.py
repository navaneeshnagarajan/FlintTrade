"""Walk-forward optimization and Monte Carlo simulation.

Walk-forward splits historical data into in-sample (train) and out-of-sample
(test) windows, runs a parameter grid on in-sample, validates the best
parameters on out-of-sample, then walks forward and repeats.

Monte Carlo randomizes trade order 1000x to report confidence intervals.
"""

from __future__ import annotations

import itertools
import logging
import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable

try:
    from .metrics import PerformanceMetrics, PerformanceReport  # noqa: F401
    from .simulator import BacktestConfig, BacktestSimulator, SimTrade  # noqa: F401
except ImportError:
    from metrics import PerformanceMetrics, PerformanceReport  # noqa: F401
    from simulator import BacktestConfig, BacktestSimulator, SimTrade  # noqa: F401

logger = logging.getLogger("flinttrade.backtest.optimizer")


# ---------------------------------------------------------------------------
# Parameter grid
# ---------------------------------------------------------------------------


@dataclass
class ParamRange:
    """A single parameter with its possible values."""

    name: str
    values: list[Any]


@dataclass
class ParamGrid:
    """Parameter grid for optimization."""

    params: list[ParamRange] = field(default_factory=list)

    def add(self, name: str, values: list[Any]) -> None:
        self.params.append(ParamRange(name=name, values=values))

    def combinations(self) -> list[dict[str, Any]]:
        """Generate all combinations of parameter values."""
        if not self.params:
            return [{}]
        names = [p.name for p in self.params]
        value_lists = [p.values for p in self.params]
        return [dict(zip(names, combo)) for combo in itertools.product(*value_lists)]

    @property
    def total_combinations(self) -> int:
        if not self.params:
            return 1
        count = 1
        for p in self.params:
            count *= len(p.values)
        return count


# ---------------------------------------------------------------------------
# Walk-forward split
# ---------------------------------------------------------------------------


@dataclass
class WalkForwardWindow:
    """A single in-sample / out-of-sample window."""

    in_sample_start: int   # bar index
    in_sample_end: int
    out_sample_start: int
    out_sample_end: int


def walk_forward_splits(
    total_bars: int,
    in_sample_pct: float = 0.7,
    num_windows: int = 3,
) -> list[WalkForwardWindow]:
    """Split bar indices into walk-forward windows.

    Each window: [in_sample_start..in_sample_end] [out_sample_start..out_sample_end]
    Windows advance forward with overlap.
    """
    if total_bars < 10 or num_windows < 1:
        return []

    window_size = total_bars // num_windows
    in_size = int(window_size * in_sample_pct)
    out_size = window_size - in_size

    if in_size < 5 or out_size < 2:
        return []

    windows: list[WalkForwardWindow] = []
    for i in range(num_windows):
        start = i * out_size
        in_end = start + in_size - 1
        out_start = in_end + 1
        out_end = min(out_start + out_size - 1, total_bars - 1)

        if out_end <= out_start:
            continue

        windows.append(WalkForwardWindow(
            in_sample_start=start,
            in_sample_end=in_end,
            out_sample_start=out_start,
            out_sample_end=out_end,
        ))

    return windows


# ---------------------------------------------------------------------------
# Optimization result
# ---------------------------------------------------------------------------


@dataclass
class OptimizationEntry:
    """Result of a single parameter combination."""

    params: dict[str, Any]
    sharpe: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    total_trades: int = 0


@dataclass
class WalkForwardResult:
    """Result from walk-forward optimization."""

    best_params: dict[str, Any] = field(default_factory=dict)
    in_sample_results: list[OptimizationEntry] = field(default_factory=list)
    out_sample_report: PerformanceReport | None = None
    robustness_score: float = 0.0  # 0-100, higher = more robust


@dataclass
class MonteCarloResult:
    """Result from Monte Carlo simulation."""

    num_simulations: int = 0
    mean_return: float = 0.0
    median_return: float = 0.0
    std_return: float = 0.0
    percentile_5: float = 0.0
    percentile_25: float = 0.0
    percentile_75: float = 0.0
    percentile_95: float = 0.0
    probability_of_profit: float = 0.0
    max_drawdown_mean: float = 0.0


# ---------------------------------------------------------------------------
# Walk-Forward Optimizer
# ---------------------------------------------------------------------------


class WalkForwardOptimizer:
    """Walk-forward optimization engine.

    Usage::

        optimizer = WalkForwardOptimizer()
        grid = ParamGrid()
        grid.add("fast_period", [5, 10, 15, 20])
        grid.add("slow_period", [30, 50, 100])

        result = optimizer.optimize(
            strategy_factory=lambda params: EMACrossover(name="ema", **params),
            bars=historical_bars,
            config=BacktestConfig(...),
            grid=grid,
        )
        print(f"Best params: {result.best_params}")
    """

    def optimize(
        self,
        strategy_factory: Callable[[dict[str, Any]], Any],
        bars: list[dict[str, Any]],
        config: BacktestConfig,
        grid: ParamGrid,
        in_sample_pct: float = 0.7,
        num_windows: int = 1,
        rank_by: str = "sharpe",
    ) -> WalkForwardResult:
        """Run walk-forward optimization.

        Args:
            strategy_factory: callable that takes a param dict and returns a BaseStrategy.
            bars: full historical bar data.
            config: backtest configuration.
            grid: parameter grid to search.
            in_sample_pct: fraction of data for in-sample.
            num_windows: number of walk-forward windows.
            rank_by: "sharpe" or "return" to rank parameter sets.
        """
        if num_windows <= 1:
            # Simple split
            split_idx = int(len(bars) * in_sample_pct)
            in_bars = bars[:split_idx]
            out_bars = bars[split_idx:]
        else:
            windows = walk_forward_splits(len(bars), in_sample_pct, num_windows)
            if not windows:
                return WalkForwardResult()
            # Use last window
            w = windows[-1]
            in_bars = bars[w.in_sample_start: w.in_sample_end + 1]
            out_bars = bars[w.out_sample_start: w.out_sample_end + 1]

        combos = grid.combinations()
        logger.info("Optimizing %d parameter combinations on %d in-sample bars", len(combos), len(in_bars))

        # Run all combinations on in-sample
        in_sample_results: list[OptimizationEntry] = []
        for params in combos:
            try:
                strategy = strategy_factory(params)
                sim = BacktestSimulator(config)
                result = sim.run(strategy, in_bars)
                report = PerformanceMetrics.compute(result)

                in_sample_results.append(OptimizationEntry(
                    params=params,
                    sharpe=report.sharpe_ratio,
                    total_return_pct=report.total_return_pct,
                    max_drawdown_pct=report.drawdown.max_drawdown_pct,
                    total_trades=report.trade_stats.total_trades,
                ))
            except Exception as exc:
                logger.warning("Params %s failed: %s", params, exc)
                in_sample_results.append(OptimizationEntry(params=params))

        # Rank by chosen metric
        if rank_by == "return":
            in_sample_results.sort(key=lambda e: e.total_return_pct, reverse=True)
        else:
            in_sample_results.sort(key=lambda e: e.sharpe, reverse=True)

        best_params = in_sample_results[0].params if in_sample_results else {}

        # Validate best params on out-of-sample
        out_report: PerformanceReport | None = None
        robustness = 0.0
        if out_bars and best_params:
            try:
                strategy = strategy_factory(best_params)
                sim = BacktestSimulator(config)
                out_result = sim.run(strategy, out_bars)
                out_report = PerformanceMetrics.compute(out_result)

                # Robustness: how well does out-of-sample compare to in-sample
                in_sharpe = in_sample_results[0].sharpe if in_sample_results else 0
                out_sharpe = out_report.sharpe_ratio
                if in_sharpe > 0:
                    robustness = min(100, max(0, (out_sharpe / in_sharpe) * 100))
            except Exception as exc:
                logger.error("Out-of-sample validation failed: %s", exc)

        return WalkForwardResult(
            best_params=best_params,
            in_sample_results=in_sample_results,
            out_sample_report=out_report,
            robustness_score=robustness,
        )

    # ------------------------------------------------------------------
    # Monte Carlo simulation
    # ------------------------------------------------------------------

    @staticmethod
    def monte_carlo(
        trades: list[SimTrade],
        initial_capital: float,
        num_simulations: int = 1000,
    ) -> MonteCarloResult:
        """Randomize trade order N times, report confidence intervals.

        This tests whether the strategy's performance depends on the specific
        sequence of trades (fragile) or is robust to ordering.
        """
        if not trades:
            return MonteCarloResult(num_simulations=num_simulations)

        pnls = [t.net_pnl for t in trades]
        final_equities: list[float] = []
        max_drawdowns: list[float] = []

        for _ in range(num_simulations):
            shuffled = list(pnls)
            random.shuffle(shuffled)

            equity = initial_capital
            peak = initial_capital
            max_dd = 0.0

            for pnl in shuffled:
                equity += pnl
                if equity > peak:
                    peak = equity
                dd = (peak - equity) / peak * 100 if peak > 0 else 0.0
                max_dd = max(max_dd, dd)

            final_equities.append(equity)
            max_drawdowns.append(max_dd)

        final_equities.sort()
        n = len(final_equities)
        returns = [(eq - initial_capital) / initial_capital * 100 for eq in final_equities]

        mean_ret = sum(returns) / n
        median_ret = returns[n // 2]
        std_ret = math.sqrt(sum((r - mean_ret) ** 2 for r in returns) / max(1, n - 1))
        prob_profit = sum(1 for r in returns if r > 0) / n * 100

        return MonteCarloResult(
            num_simulations=num_simulations,
            mean_return=mean_ret,
            median_return=median_ret,
            std_return=std_ret,
            percentile_5=returns[int(0.05 * n)],
            percentile_25=returns[int(0.25 * n)],
            percentile_75=returns[int(0.75 * n)],
            percentile_95=returns[int(0.95 * n)],
            probability_of_profit=prob_profit,
            max_drawdown_mean=sum(max_drawdowns) / n if max_drawdowns else 0.0,
        )
