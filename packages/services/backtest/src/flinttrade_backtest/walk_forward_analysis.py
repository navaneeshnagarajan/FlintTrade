"""Walk-Forward Analysis with Walk-Forward Efficiency (WFE) ratio.

Extends the existing :mod:`walk_forward` module with a richer per-fold
metrics model and the Walk-Forward Efficiency ratio:

    WFE = OOS performance / IS performance

A WFE near 1.0 is excellent.  Values above 0.5 are generally considered
acceptable for a production strategy.  Values below 0.3 suggest heavy
in-sample overfitting.

Two windowing modes:
- **Rolling** (``anchor=False``): fixed-size training window that advances
  by one test step per fold.  Each fold has the same train size.
- **Expanding / Anchored** (``anchor=True``): training window always starts
  from bar 0 and expands to include more history.  Useful when data is
  limited or when recency alone does not capture the strategy regime.

The module is self-contained and works with any callable strategy that
exposes either:

- ``daily_returns: list[float]`` attribute after calling ``on_bar`` for
  each bar, **or**
- ``get_equity_curve() -> list[float]`` method.

Falls back to bar-to-bar close returns when neither interface is available.

Supported performance metrics (``metric`` parameter):
    ``"sharpe_ratio"``, ``"sortino_ratio"``, ``"total_return"``,
    ``"calmar_ratio"``, ``"win_rate"``, ``"profit_factor"``

Usage::

    from flinttrade_backtest.walk_forward_analysis import WFAnalysis, WFAConfig

    config = WFAConfig(n_splits=5, train_pct=0.7, anchor=False)
    wfa = WFAnalysis(config)
    result = wfa.run(
        bars=historical_bars,
        strategy_class=EMACrossover,
        strategy_kwargs={"fast": 9, "slow": 21},
        metric="sharpe_ratio",
    )
    print(f"WFE ratio : {result.wfe_ratio:.3f}")
    print(f"Avg IS    : {result.avg_is_metric:.3f}")
    print(f"Avg OOS   : {result.avg_oos_metric:.3f}")
    for fold in result.folds:
        print(f"  Fold {fold.fold_index}: IS={fold.is_metric:.3f} OOS={fold.oos_metric:.3f}")
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("flinttrade.backtest.walk_forward_analysis")

_ANNUALISE = 252
_RISK_FREE = 0.07


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------


def _safe_mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _safe_std(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = _safe_mean(vals)
    v = sum((x - m) ** 2 for x in vals) / (len(vals) - 1)
    return math.sqrt(max(0.0, v))


def _sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    m = _safe_mean(returns)
    s = _safe_std(returns)
    if s == 0:
        return 0.0
    return (m - _RISK_FREE / _ANNUALISE) / s * math.sqrt(_ANNUALISE)


def _sortino(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    m = _safe_mean(returns)
    daily_rf = _RISK_FREE / _ANNUALISE
    downside = math.sqrt(
        sum(min(0.0, r - daily_rf) ** 2 for r in returns) / len(returns)
    )
    if downside == 0:
        return 0.0
    return (m - daily_rf) / downside * math.sqrt(_ANNUALISE)


def _total_return(returns: list[float]) -> float:
    eq = 1.0
    for r in returns:
        eq *= 1.0 + r
    return (eq - 1.0) * 100.0


def _max_drawdown(returns: list[float]) -> float:
    eq, peak, max_dd = 1.0, 1.0, 0.0
    for r in returns:
        eq *= 1.0 + r
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100.0 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _calmar(returns: list[float]) -> float:
    total = _total_return(returns)
    mdd = _max_drawdown(returns)
    if mdd == 0:
        return 0.0
    years = len(returns) / _ANNUALISE if returns else 1.0
    years = max(years, 1e-6)
    try:
        cagr = ((1.0 + total / 100.0) ** (1.0 / years) - 1.0) * 100.0
    except (ValueError, ZeroDivisionError):
        cagr = 0.0
    return cagr / mdd


def _win_rate(returns: list[float]) -> float:
    if not returns:
        return 0.0
    return sum(1 for r in returns if r > 0) / len(returns) * 100.0


def _profit_factor(returns: list[float]) -> float:
    gross_win = sum(r for r in returns if r > 0)
    gross_loss = abs(sum(r for r in returns if r < 0))
    if gross_loss == 0:
        return float("inf") if gross_win > 0 else 0.0
    return gross_win / gross_loss


_METRIC_FNS: dict[str, Any] = {
    "sharpe_ratio": _sharpe,
    "sortino_ratio": _sortino,
    "total_return": _total_return,
    "calmar_ratio": _calmar,
    "win_rate": _win_rate,
    "profit_factor": _profit_factor,
}


def _compute_metric(returns: list[float], metric: str) -> float:
    """Evaluate a single metric from a return series.

    Args:
        returns: Daily return fractions.
        metric:  One of the supported metric keys.

    Returns:
        Scalar metric value.

    Raises:
        ValueError: If metric is not recognised.
    """
    fn = _METRIC_FNS.get(metric)
    if fn is None:
        supported = ", ".join(sorted(_METRIC_FNS))
        raise ValueError(f"Unsupported metric {metric!r}. Supported: {supported}")
    return fn(returns)


# ---------------------------------------------------------------------------
# Strategy runner
# ---------------------------------------------------------------------------


def _run_strategy(
    strategy_class: type,
    strategy_kwargs: dict[str, Any],
    bars: list[dict[str, Any]],
) -> list[float]:
    """Instantiate and run a strategy; return daily returns.

    Tries, in order:
    1. ``strategy.daily_returns`` attribute.
    2. ``strategy.get_equity_curve()`` converted to returns.
    3. Bar-to-bar close returns as fallback.

    Args:
        strategy_class:   Strategy class.
        strategy_kwargs:  Constructor kwargs.
        bars:             Bar dicts with at least a ``"close"`` key.

    Returns:
        List of daily return fractions.
    """
    if not bars:
        return []
    try:
        strategy = strategy_class(**strategy_kwargs)
        if hasattr(strategy, "on_bar"):
            for bar in bars:
                strategy.on_bar(bar)

        if hasattr(strategy, "daily_returns") and isinstance(strategy.daily_returns, list):
            returns = list(strategy.daily_returns)
            if returns:
                return returns

        if hasattr(strategy, "get_equity_curve"):
            eq = strategy.get_equity_curve()
            if eq and len(eq) >= 2:
                return [
                    (eq[i] - eq[i - 1]) / eq[i - 1] if eq[i - 1] > 0 else 0.0
                    for i in range(1, len(eq))
                ]

    except Exception as exc:
        logger.warning("Strategy run failed: %s", exc)

    # Fallback: close-to-close returns
    closes: list[float] = []
    for bar in bars:
        c = bar.get("close") or bar.get("Close") or bar.get("c")
        if c is not None:
            try:
                closes.append(float(c))
            except (TypeError, ValueError):
                pass

    if len(closes) < 2:
        return []
    return [
        (closes[i] - closes[i - 1]) / closes[i - 1] if closes[i - 1] > 0 else 0.0
        for i in range(1, len(closes))
    ]


# ---------------------------------------------------------------------------
# Config and result models
# ---------------------------------------------------------------------------


class WFAConfig(BaseModel):
    """Configuration for walk-forward analysis.

    Attributes:
        n_splits:   Number of train/test folds.  Must be >= 2.
        train_pct:  Fraction of each fold allocated to training (0.5–0.9).
        anchor:     When ``True``, use an expanding window starting from bar 0.
                    When ``False`` (default), use a fixed rolling window.
    """

    n_splits: int = Field(default=5, ge=2, le=200)
    train_pct: float = Field(default=0.7, ge=0.5, le=0.9)
    anchor: bool = False


@dataclass
class WFAFold:
    """Per-fold walk-forward results.

    Attributes:
        fold_index:     0-based fold index.
        train_start:    First bar index in the training window.
        train_end:      Last bar index in the training window (inclusive).
        oos_start:      First bar index in the out-of-sample window.
        oos_end:        Last bar index in the out-of-sample window (inclusive).
        n_train:        Number of training bars.
        n_oos:          Number of OOS bars.
        is_metric:      In-sample performance metric.
        oos_metric:     Out-of-sample performance metric.
        wfe:            Fold-level WFE = oos_metric / is_metric.
                        Zero when is_metric == 0.
        is_returns:     In-sample daily returns (stored for downstream use).
        oos_returns:    Out-of-sample daily returns.
    """

    fold_index: int = 0
    train_start: int = 0
    train_end: int = 0
    oos_start: int = 0
    oos_end: int = 0
    n_train: int = 0
    n_oos: int = 0
    is_metric: float = 0.0
    oos_metric: float = 0.0
    wfe: float = 0.0
    is_returns: list[float] = field(default_factory=list)
    oos_returns: list[float] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Serialise fold to a plain dict (excludes return series)."""
        return {
            "fold_index": self.fold_index,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "oos_start": self.oos_start,
            "oos_end": self.oos_end,
            "n_train": self.n_train,
            "n_oos": self.n_oos,
            "is_metric": self.is_metric,
            "oos_metric": self.oos_metric,
            "wfe": self.wfe,
        }


@dataclass
class WalkForwardAnalysisResult:
    """Aggregated walk-forward analysis result.

    Attributes:
        folds:            Per-fold detail.
        avg_is_metric:    Mean in-sample metric across all folds.
        avg_oos_metric:   Mean out-of-sample metric across all folds.
        wfe_ratio:        Walk-Forward Efficiency = avg_oos / avg_is.
                          WFE > 0.9: excellent.
                          WFE 0.5–0.9: acceptable.
                          WFE < 0.5: possibly over-fitted.
        degradation_pct:  Percentage degradation IS → OOS.  Positive = degraded.
        is_robust:        True when degradation_pct < 30%.
        metric:           Metric name used.
        n_folds_run:      Number of folds that completed without error.
    """

    folds: list[WFAFold] = field(default_factory=list)
    avg_is_metric: float = 0.0
    avg_oos_metric: float = 0.0
    wfe_ratio: float = 0.0
    degradation_pct: float = 0.0
    is_robust: bool = False
    metric: str = ""
    n_folds_run: int = 0

    def as_dict(self) -> dict[str, Any]:
        """Flat dict for JSON serialisation."""
        return {
            "avg_is_metric": self.avg_is_metric,
            "avg_oos_metric": self.avg_oos_metric,
            "wfe_ratio": self.wfe_ratio,
            "degradation_pct": self.degradation_pct,
            "is_robust": self.is_robust,
            "metric": self.metric,
            "n_folds_run": self.n_folds_run,
            "folds": [f.as_dict() for f in self.folds],
        }


# ---------------------------------------------------------------------------
# Split generation
# ---------------------------------------------------------------------------


def _generate_splits(
    n_bars: int,
    config: WFAConfig,
) -> list[tuple[int, int, int, int]]:
    """Generate (train_start, train_end, oos_start, oos_end) bar indices.

    Uses either a rolling or an anchored (expanding) window strategy.

    Args:
        n_bars: Total number of bars.
        config: WFAConfig.

    Returns:
        List of (train_start, train_end, oos_start, oos_end) tuples.
        Indices are inclusive.

    Raises:
        ValueError: If there is insufficient data for the requested splits.
    """
    min_required = config.n_splits * 7
    if n_bars < min_required:
        raise ValueError(
            f"Need at least {min_required} bars for {config.n_splits} folds; "
            f"got {n_bars}."
        )

    # Test window size per fold (equal shares of total)
    oos_size = max(2, n_bars // (config.n_splits + int(config.train_pct * config.n_splits)))
    train_size = max(5, int(oos_size * config.train_pct / (1.0 - config.train_pct)))

    splits: list[tuple[int, int, int, int]] = []
    for i in range(config.n_splits):
        if config.anchor:
            # Expanding: always start training at bar 0
            train_start = 0
            train_end = train_size + i * oos_size - 1
        else:
            # Rolling: fixed-size window advancing by oos_size per fold
            train_start = i * oos_size
            train_end = train_start + train_size - 1

        oos_start = train_end + 1
        oos_end = min(oos_start + oos_size - 1, n_bars - 1)

        if train_end >= n_bars or oos_start >= n_bars:
            break
        if oos_end <= oos_start:
            break
        if train_end < train_start:
            break

        splits.append((train_start, train_end, oos_start, oos_end))

    return splits


# ---------------------------------------------------------------------------
# WFE ratio computation
# ---------------------------------------------------------------------------


def _wfe_ratio(is_metric: float, oos_metric: float) -> float:
    """Compute Walk-Forward Efficiency ratio.

    WFE = OOS performance / IS performance.

    Handles sign-aware normalisation: if both metrics are negative the ratio
    is still the fraction of OOS performance retained (so negative / negative
    = positive, which would be misleadingly high).  We clamp to [-1, 2].

    Args:
        is_metric:  In-sample metric value.
        oos_metric: Out-of-sample metric value.

    Returns:
        WFE ratio, clamped to [-1.0, 2.0].
    """
    if is_metric == 0.0:
        return 0.0
    ratio = oos_metric / is_metric
    return max(-1.0, min(2.0, ratio))


# ---------------------------------------------------------------------------
# Main analyser
# ---------------------------------------------------------------------------


class WFAnalysis:
    """Walk-forward analysis engine with WFE ratio reporting.

    Builds on the same split-and-run pattern as :class:`WalkForwardAnalyser`
    (in :mod:`walk_forward`) but adds:
    - Per-fold WFE ratio.
    - Aggregate WFE ratio across all folds.
    - Richer fold detail including stored return series.
    - ``anchor`` parameter for expanding vs rolling windows.

    Usage::

        from flinttrade_backtest.walk_forward_analysis import WFAnalysis, WFAConfig

        config = WFAConfig(n_splits=5, train_pct=0.7, anchor=False)
        wfa = WFAnalysis(config)
        result = wfa.run(
            bars=historical_bars,
            strategy_class=MyStrategy,
            strategy_kwargs={"fast": 9, "slow": 21},
            metric="sharpe_ratio",
        )
        print(result.wfe_ratio)
    """

    def __init__(self, config: WFAConfig | None = None) -> None:
        """Initialise the analyser.

        Args:
            config: Walk-forward configuration.  Defaults are used when None.
        """
        self.config = config or WFAConfig()

    def run(
        self,
        bars: list[dict[str, Any]],
        strategy_class: type,
        strategy_kwargs: dict[str, Any],
        metric: str = "sharpe_ratio",
    ) -> WalkForwardAnalysisResult:
        """Run walk-forward analysis.

        Args:
            bars:             Full historical bar data.  Each dict should
                              contain at minimum a ``"close"`` key.
            strategy_class:   Strategy class to instantiate for each fold.
                              Must accept ``**strategy_kwargs`` in the
                              constructor.
            strategy_kwargs:  Keyword arguments for the strategy constructor.
            metric:           Performance metric to compare.  One of:
                              ``"sharpe_ratio"``, ``"sortino_ratio"``,
                              ``"total_return"``, ``"calmar_ratio"``,
                              ``"win_rate"``, ``"profit_factor"``.

        Returns:
            :class:`WalkForwardAnalysisResult` with per-fold detail and
            aggregate WFE ratio.

        Raises:
            ValueError: If ``metric`` is unsupported or there is insufficient
                        data.
        """
        if metric not in _METRIC_FNS:
            supported = ", ".join(sorted(_METRIC_FNS))
            raise ValueError(
                f"Unsupported metric {metric!r}. Supported: {supported}"
            )

        n_bars = len(bars)
        try:
            splits = _generate_splits(n_bars, self.config)
        except ValueError as exc:
            logger.error("Split generation failed: %s", exc)
            raise

        folds: list[WFAFold] = []
        n_errors = 0

        for idx, (train_start, train_end, oos_start, oos_end) in enumerate(splits):
            train_bars = bars[train_start : train_end + 1]
            oos_bars = bars[oos_start : oos_end + 1]

            try:
                is_returns = _run_strategy(strategy_class, strategy_kwargs, train_bars)
                oos_returns = _run_strategy(strategy_class, strategy_kwargs, oos_bars)

                is_m = _compute_metric(is_returns, metric)
                oos_m = _compute_metric(oos_returns, metric)
                fold_wfe = _wfe_ratio(is_m, oos_m)

                folds.append(WFAFold(
                    fold_index=idx,
                    train_start=train_start,
                    train_end=train_end,
                    oos_start=oos_start,
                    oos_end=oos_end,
                    n_train=len(train_bars),
                    n_oos=len(oos_bars),
                    is_metric=is_m,
                    oos_metric=oos_m,
                    wfe=fold_wfe,
                    is_returns=is_returns,
                    oos_returns=oos_returns,
                ))

                logger.debug(
                    "Fold %d: train=[%d,%d] oos=[%d,%d] IS=%.4f OOS=%.4f WFE=%.4f",
                    idx, train_start, train_end, oos_start, oos_end,
                    is_m, oos_m, fold_wfe,
                )

            except Exception as exc:
                logger.warning("Fold %d failed: %s", idx, exc)
                n_errors += 1

        if not folds:
            logger.error("All folds failed (%d errors)", n_errors)
            return WalkForwardAnalysisResult(metric=metric)

        avg_is = _safe_mean([f.is_metric for f in folds])
        avg_oos = _safe_mean([f.oos_metric for f in folds])
        aggregate_wfe = _wfe_ratio(avg_is, avg_oos)

        degradation = (
            (avg_is - avg_oos) / abs(avg_is) * 100.0 if avg_is != 0.0 else 0.0
        )
        is_robust = abs(degradation) < 30.0

        logger.info(
            "WFA complete: %d folds, avg_IS=%.4f avg_OOS=%.4f WFE=%.4f "
            "degradation=%.1f%% robust=%s",
            len(folds), avg_is, avg_oos, aggregate_wfe, degradation, is_robust,
        )

        return WalkForwardAnalysisResult(
            folds=folds,
            avg_is_metric=avg_is,
            avg_oos_metric=avg_oos,
            wfe_ratio=aggregate_wfe,
            degradation_pct=degradation,
            is_robust=is_robust,
            metric=metric,
            n_folds_run=len(folds),
        )


__all__ = [
    "WFAnalysis",
    "WFAConfig",
    "WFAFold",
    "WalkForwardAnalysisResult",
]
