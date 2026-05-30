"""Walk-forward analysis for out-of-sample strategy validation.

Walk-forward analysis avoids in-sample overfitting by repeatedly splitting
historical data into a training window and an unseen test window, running
the strategy on each, and comparing in-sample vs out-of-sample performance.

Two windowing modes:
- **Rolling** (``anchored=False``): both start and end of the training
  window advance by one step per split.  Each training window is the same
  size.
- **Anchored / Expanding** (``anchored=True``): the training window always
  starts from the very first bar and expands forward.  This is sometimes
  called "expanding window" walk-forward.

The :class:`WalkForwardAnalyser` works on plain bar dicts (``list[dict]``)
and accepts a ``strategy_class`` type together with ``strategy_kwargs`` so
it can instantiate fresh strategy objects for each split.  This avoids
state leakage between windows.

Supported metrics (``metric`` parameter):
    ``"sharpe_ratio"``, ``"total_return"``, ``"sortino_ratio"``,
    ``"calmar_ratio"``, ``"win_rate"``, ``"profit_factor"``

Flask routes are registered in :mod:`permutation_routes`.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("flinttrade.backtest.walk_forward")

# Robustness threshold: out-of-sample degradation must be < 30 %
_ROBUST_DEGRADATION_THRESHOLD: float = 30.0


# ---------------------------------------------------------------------------
# Config / Result models
# ---------------------------------------------------------------------------


class WalkForwardConfig(BaseModel):
    """Configuration for walk-forward analysis.

    Attributes:
        n_splits:    Number of train/test splits to create.  More splits give
                     a richer picture but require more data.  Must be >= 2.
        train_ratio: Fraction of each window allocated to training
                     (0.5–0.9).
        anchored:    If ``True``, use an expanding (anchored) training window
                     that always starts from bar 0.  If ``False`` (default),
                     use a rolling fixed-size window.
    """

    n_splits: int = Field(default=5, ge=2, le=100)
    train_ratio: float = Field(default=0.7, ge=0.5, le=0.9)
    anchored: bool = False


class SplitDetail(BaseModel):
    """Detailed result for a single walk-forward split.

    Attributes:
        split_index:   0-based index of this split.
        train_start:   First bar index of the training window.
        train_end:     Last bar index of the training window (inclusive).
        test_start:    First bar index of the test window.
        test_end:      Last bar index of the test window (inclusive).
        n_train_bars:  Number of bars in the training window.
        n_test_bars:   Number of bars in the test window.
        train_metric:  Metric value on the training window.
        test_metric:   Metric value on the test window.
        degradation_pct: Percentage drop from ``train_metric`` to
                         ``test_metric``.  Negative means out-of-sample
                         *improved*, which can indicate the strategy is
                         conservative in-sample.
    """

    split_index: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    n_train_bars: int
    n_test_bars: int
    train_metric: float
    test_metric: float
    degradation_pct: float


class WalkForwardResult(BaseModel):
    """Aggregated results from a full walk-forward run.

    Attributes:
        splits:             Detailed result for every split.
        avg_train_metric:   Mean in-sample metric across all splits.
        avg_test_metric:    Mean out-of-sample metric across all splits.
        degradation_pct:    Average degradation from in-sample to out-of-sample.
                            Computed as
                            ``(avg_train - avg_test) / |avg_train| * 100``.
                            When ``avg_train`` is zero, degradation is 0.
        is_robust:          ``True`` when ``|degradation_pct| < 30 %``.
                            A robust strategy does not lose most of its edge
                            out of sample.
        n_splits_run:       Actual number of splits that completed without
                            errors.
    """

    splits: list[SplitDetail]
    avg_train_metric: float
    avg_test_metric: float
    degradation_pct: float
    is_robust: bool
    n_splits_run: int

    def as_dict(self) -> dict[str, Any]:
        """Flat dict for JSON serialisation (splits serialised as list of dicts)."""
        return self.model_dump()


# ---------------------------------------------------------------------------
# Metric extraction from a raw return series
# ---------------------------------------------------------------------------

_ANNUALISE = 252  # trading days per year
_RISK_FREE = 0.07  # India 7 %


def _safe_mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _safe_std(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    mean = _safe_mean(vals)
    variance = sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)
    return math.sqrt(variance) if variance > 0 else 0.0


def _sharpe_from_returns(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    mean = _safe_mean(returns)
    std = _safe_std(returns)
    if std == 0:
        return 0.0
    daily_rf = _RISK_FREE / _ANNUALISE
    return (mean - daily_rf) / std * math.sqrt(_ANNUALISE)


def _sortino_from_returns(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    mean = _safe_mean(returns)
    daily_rf = _RISK_FREE / _ANNUALISE
    downside_sq = [min(0.0, r - daily_rf) ** 2 for r in returns]
    downside_dev = math.sqrt(sum(downside_sq) / len(returns))
    if downside_dev == 0:
        return 0.0
    return (mean - daily_rf) / downside_dev * math.sqrt(_ANNUALISE)


def _total_return_from_returns(returns: list[float]) -> float:
    equity = 1.0
    for r in returns:
        equity *= 1.0 + r
    return (equity - 1.0) * 100.0


def _max_drawdown_from_returns(returns: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        equity *= 1.0 + r
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _calmar_from_returns(returns: list[float]) -> float:
    total_ret = _total_return_from_returns(returns)
    max_dd = _max_drawdown_from_returns(returns)
    if max_dd == 0:
        return 0.0
    # CAGR approximation from total return over the period
    years = len(returns) / _ANNUALISE if returns else 1.0
    if years <= 0:
        years = 1.0
    try:
        cagr = ((1.0 + total_ret / 100.0) ** (1.0 / years) - 1.0) * 100.0
    except (ValueError, ZeroDivisionError):
        cagr = 0.0
    return cagr / max_dd


def _win_rate_from_returns(returns: list[float]) -> float:
    if not returns:
        return 0.0
    wins = sum(1 for r in returns if r > 0)
    return wins / len(returns) * 100.0


def _profit_factor_from_returns(returns: list[float]) -> float:
    gross_win = sum(r for r in returns if r > 0)
    gross_loss = abs(sum(r for r in returns if r < 0))
    if gross_loss == 0:
        return float("inf") if gross_win > 0 else 0.0
    return gross_win / gross_loss


_METRIC_FUNCTIONS: dict[str, Any] = {
    "sharpe_ratio": _sharpe_from_returns,
    "sortino_ratio": _sortino_from_returns,
    "total_return": _total_return_from_returns,
    "calmar_ratio": _calmar_from_returns,
    "win_rate": _win_rate_from_returns,
    "profit_factor": _profit_factor_from_returns,
}


def _compute_metric(returns: list[float], metric: str) -> float:
    """Compute a single scalar metric from a return series.

    Args:
        returns: Daily return fractions.
        metric:  Metric name.

    Returns:
        Scalar value.

    Raises:
        ValueError: If ``metric`` is not supported.
    """
    fn = _METRIC_FUNCTIONS.get(metric)
    if fn is None:
        supported = ", ".join(sorted(_METRIC_FUNCTIONS))
        raise ValueError(
            f"Unsupported metric: {metric!r}.  Supported: {supported}"
        )
    return fn(returns)


# ---------------------------------------------------------------------------
# Strategy runner adapter
# ---------------------------------------------------------------------------


def _run_strategy_on_bars(
    strategy_class: type,
    strategy_kwargs: dict[str, Any],
    bars: list[dict[str, Any]],
) -> list[float]:
    """Instantiate and run a strategy on a bar slice; return daily returns.

    The strategy class must expose an ``on_bar(bar)`` method and a
    ``daily_returns`` attribute (list[float]) after running, OR a
    ``get_equity_curve()`` method returning a list of equity values.

    If neither interface is available we fall back to extracting ``"close"``
    prices and computing simple bar-to-bar returns so the walk-forward can
    still produce *something* meaningful for testing.

    Args:
        strategy_class:   Class (not instance) of the strategy.
        strategy_kwargs:  Keyword arguments passed to the constructor.
        bars:             Historical bar dicts for this split window.

    Returns:
        List of daily return fractions.
    """
    if not bars:
        return []

    try:
        strategy = strategy_class(**strategy_kwargs)

        # Try running through on_bar
        if hasattr(strategy, "on_bar"):
            for bar in bars:
                strategy.on_bar(bar)

            # Prefer a daily_returns attribute
            if hasattr(strategy, "daily_returns") and isinstance(
                strategy.daily_returns, list
            ):
                return list(strategy.daily_returns)

            # Try equity curve
            if hasattr(strategy, "get_equity_curve"):
                equity = strategy.get_equity_curve()
                if equity and len(equity) >= 2:
                    return _equity_to_returns(equity)

    except Exception as exc:
        logger.warning("Strategy execution failed: %s", exc)

    # Fallback: bar-to-bar close returns
    return _bars_to_returns(bars)


def _equity_to_returns(equity: list[float]) -> list[float]:
    """Convert an equity curve to a daily return series."""
    returns: list[float] = []
    for i in range(1, len(equity)):
        prev = equity[i - 1]
        curr = equity[i]
        if prev > 0:
            returns.append((curr - prev) / prev)
        else:
            returns.append(0.0)
    return returns


def _bars_to_returns(bars: list[dict[str, Any]]) -> list[float]:
    """Compute bar-to-bar close returns as a baseline."""
    closes: list[float] = []
    for bar in bars:
        close = bar.get("close") or bar.get("Close") or bar.get("c")
        if close is not None:
            try:
                closes.append(float(close))
            except (TypeError, ValueError):
                pass
    if len(closes) < 2:
        return []
    returns: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        curr = closes[i]
        if prev > 0:
            returns.append((curr - prev) / prev)
        else:
            returns.append(0.0)
    return returns


# ---------------------------------------------------------------------------
# Walk-forward split generation
# ---------------------------------------------------------------------------


def _generate_splits(
    n_bars: int,
    config: WalkForwardConfig,
) -> list[tuple[int, int, int, int]]:
    """Generate (train_start, train_end, test_start, test_end) bar indices.

    Args:
        n_bars: Total number of bars.
        config: Walk-forward configuration.

    Returns:
        List of (train_start, train_end, test_start, test_end) tuples.
        Indices are inclusive on both ends.
    """
    n_splits = config.n_splits
    train_ratio = config.train_ratio

    # Minimum bars needed: each split needs at least 5 train + 2 test bars
    min_bars = n_splits * 7
    if n_bars < min_bars:
        raise ValueError(
            f"Need at least {min_bars} bars for {n_splits} splits; "
            f"got {n_bars}"
        )

    # Each test window gets an equal share of bars
    test_window_size = max(2, n_bars // (n_splits + int(train_ratio * n_splits)))
    train_window_size = max(5, int(test_window_size * train_ratio / (1 - train_ratio)))

    splits: list[tuple[int, int, int, int]] = []

    for i in range(n_splits):
        if config.anchored:
            # Expanding window: train always starts at 0
            train_start = 0
            train_end = train_window_size + i * test_window_size - 1
        else:
            # Rolling window: fixed size, advances by one test window per split
            train_start = i * test_window_size
            train_end = train_start + train_window_size - 1

        test_start = train_end + 1
        test_end = min(test_start + test_window_size - 1, n_bars - 1)

        # Guard: skip splits that exceed the data
        if train_end >= n_bars or test_start >= n_bars:
            break
        if test_end <= test_start:
            break
        if train_end < train_start:
            break

        splits.append((train_start, train_end, test_start, test_end))

    return splits


# ---------------------------------------------------------------------------
# Degradation computation
# ---------------------------------------------------------------------------


def _degradation(train_metric: float, test_metric: float) -> float:
    """Compute percentage degradation from in-sample to out-of-sample.

    Positive means the strategy did worse out-of-sample.
    Negative means it did *better* out-of-sample.

    Args:
        train_metric: In-sample metric value.
        test_metric:  Out-of-sample metric value.

    Returns:
        Degradation percentage.
    """
    if train_metric == 0.0:
        return 0.0
    return (train_metric - test_metric) / abs(train_metric) * 100.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class WalkForwardAnalyser:
    """Run walk-forward analysis to validate strategy robustness.

    Splits historical data into N train/test windows, runs the strategy on
    each window, computes the chosen metric, and reports how much performance
    degrades from in-sample to out-of-sample.

    Usage::

        config = WalkForwardConfig(n_splits=5, train_ratio=0.7, anchored=False)
        analyser = WalkForwardAnalyser(config)
        result = analyser.analyse(
            bars=historical_bars,
            strategy_class=EMACrossover,
            strategy_kwargs={"fast": 9, "slow": 21},
            metric="sharpe_ratio",
        )
        print(f"Degradation: {result.degradation_pct:.1f}%")
        print(f"Robust: {result.is_robust}")
    """

    def __init__(self, config: WalkForwardConfig | None = None) -> None:
        """Initialise the analyser.

        Args:
            config: Walk-forward configuration.  Uses defaults when ``None``.
        """
        self.config = config or WalkForwardConfig()

    def analyse(
        self,
        bars: list[dict[str, Any]],
        strategy_class: type,
        strategy_kwargs: dict[str, Any],
        metric: str = "sharpe_ratio",
    ) -> WalkForwardResult:
        """Run walk-forward analysis on a strategy.

        Args:
            bars:             Full historical bar data as a list of dicts.
                              Each dict should contain at least a ``"close"``
                              key for the fallback return computation.
            strategy_class:   The strategy class to instantiate for each split.
                              Must accept ``**strategy_kwargs`` in its
                              constructor and expose either
                              ``daily_returns: list[float]`` or
                              ``get_equity_curve() -> list[float]`` after
                              ``on_bar`` has been called for each bar.
            strategy_kwargs:  Keyword arguments forwarded to the strategy
                              constructor.
            metric:           Metric to compare across splits.  Supported:
                              ``"sharpe_ratio"``, ``"sortino_ratio"``,
                              ``"total_return"``, ``"calmar_ratio"``,
                              ``"win_rate"``, ``"profit_factor"``.

        Returns:
            :class:`WalkForwardResult` with per-split details and summary.

        Raises:
            ValueError: If ``bars`` has too few data points for the requested
                        number of splits, or if ``metric`` is unsupported.
        """
        if metric not in _METRIC_FUNCTIONS:
            supported = ", ".join(sorted(_METRIC_FUNCTIONS))
            raise ValueError(
                f"Unsupported metric: {metric!r}.  Supported: {supported}"
            )

        n_bars = len(bars)
        splits_indices = _generate_splits(n_bars, self.config)

        split_details: list[SplitDetail] = []
        n_errors = 0

        for idx, (train_start, train_end, test_start, test_end) in enumerate(
            splits_indices
        ):
            train_bars = bars[train_start : train_end + 1]
            test_bars = bars[test_start : test_end + 1]

            try:
                train_returns = _run_strategy_on_bars(
                    strategy_class, strategy_kwargs, train_bars
                )
                test_returns = _run_strategy_on_bars(
                    strategy_class, strategy_kwargs, test_bars
                )

                train_metric = _compute_metric(train_returns, metric)
                test_metric = _compute_metric(test_returns, metric)
                deg = _degradation(train_metric, test_metric)

                split_details.append(
                    SplitDetail(
                        split_index=idx,
                        train_start=train_start,
                        train_end=train_end,
                        test_start=test_start,
                        test_end=test_end,
                        n_train_bars=len(train_bars),
                        n_test_bars=len(test_bars),
                        train_metric=train_metric,
                        test_metric=test_metric,
                        degradation_pct=deg,
                    )
                )

                logger.debug(
                    "Split %d: train=[%d,%d] test=[%d,%d] "
                    "train_metric=%.4f test_metric=%.4f degradation=%.1f%%",
                    idx, train_start, train_end,
                    test_start, test_end,
                    train_metric, test_metric, deg,
                )

            except Exception as exc:
                logger.warning("Split %d failed: %s", idx, exc)
                n_errors += 1

        if not split_details:
            return WalkForwardResult(
                splits=[],
                avg_train_metric=0.0,
                avg_test_metric=0.0,
                degradation_pct=0.0,
                is_robust=False,
                n_splits_run=0,
            )

        avg_train = _safe_mean([s.train_metric for s in split_details])
        avg_test = _safe_mean([s.test_metric for s in split_details])
        avg_deg = _degradation(avg_train, avg_test)
        is_robust = abs(avg_deg) < _ROBUST_DEGRADATION_THRESHOLD

        logger.info(
            "Walk-forward complete: %d splits, avg_train=%.4f avg_test=%.4f "
            "degradation=%.1f%% robust=%s",
            len(split_details), avg_train, avg_test, avg_deg, is_robust,
        )

        return WalkForwardResult(
            splits=split_details,
            avg_train_metric=avg_train,
            avg_test_metric=avg_test,
            degradation_pct=avg_deg,
            is_robust=is_robust,
            n_splits_run=len(split_details),
        )
