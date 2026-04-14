"""Strategy Comparison — side-by-side ranking of multiple backtest results.

Accepts a dict of named :class:`BacktestResult` objects and produces a
:class:`StrategyComparisonResult` containing per-strategy metrics, weighted
rankings, equity-curve data, inter-strategy return correlations, and an
optimal blend suggestion based on mean-variance optimisation.

Example::

    from .strategy_comparison import (
        StrategyComparator,
    )

    comparator = StrategyComparator()
    result = comparator.compare({"MomentumV1": res1, "MeanRev": res2})
    print(result.best_overall)
    print(result.rankings["sharpe"])
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
from flask import Blueprint, jsonify, request
from pydantic import BaseModel

logger = logging.getLogger("flinttrade.backtest.strategy_comparison")

# ---------------------------------------------------------------------------
# Default metric weights
# ---------------------------------------------------------------------------

_DEFAULT_WEIGHTS: dict[str, float] = {
    "sharpe": 0.30,
    "cagr": 0.30,
    "max_drawdown": 0.20,   # lower is better → inverted during scoring
    "win_rate": 0.20,
}

# Metrics where a *lower* value is better (will be negated for ranking/scoring)
_LOWER_IS_BETTER = {"max_drawdown", "volatility", "var_95"}

# Metrics extracted from BacktestResult for comparison
_EXTRACTABLE_METRICS = (
    "sharpe",
    "sortino",
    "cagr",
    "max_drawdown",
    "win_rate",
    "profit_factor",
    "total_return_pct",
    "volatility",
    "calmar",
    "total_trades",
)

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class StrategyComparisonResult(BaseModel):
    """Side-by-side comparison of multiple backtest results.

    Attributes:
        strategies: Ordered list of strategy names included in the comparison.
        metrics: Mapping of ``{strategy_name: {metric_name: value}}``.
        rankings: Mapping of ``{metric_name: [strategy_names_ranked_best_first]}``.
        best_overall: Name of the strategy with the highest weighted composite score.
        equity_curves: Mapping of ``{strategy_name: [equity_values]}`` for charting.
        correlation_matrix: N×N return-correlation matrix (row/col order matches
            ``strategies``).
    """

    strategies: list[str]
    metrics: dict[str, dict[str, float]]
    rankings: dict[str, list[str]]
    best_overall: str
    equity_curves: dict[str, list[float]]
    correlation_matrix: list[list[float]]


# ---------------------------------------------------------------------------
# Helper: extract metrics from BacktestResult
# ---------------------------------------------------------------------------


def _extract_metrics(result: Any) -> dict[str, float]:
    """Extract a flat metric dict from a BacktestResult (or plain dict).

    Supports both the dataclass-based :class:`BacktestResult` from
    ``packages.backtest_engine.src.simulator`` (which carries a
    ``PerformanceReport`` after ``PerformanceMetrics.compute()`` is called),
    and a plain dict representation (useful for API payloads).

    Args:
        result: A :class:`BacktestResult` dataclass instance *or* a plain
            dict with the same structure.

    Returns:
        Flat ``{metric_name: float}`` dict.
    """
    if isinstance(result, dict):
        return _extract_from_dict(result)
    return _extract_from_dataclass(result)


def _extract_from_dict(d: dict[str, Any]) -> dict[str, float]:
    """Extract metrics from a plain dict payload."""
    metrics: dict[str, float] = {}

    def _f(key: str, default: float = 0.0) -> float:
        val = d.get(key, default)
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    # Top-level keys
    metrics["total_return_pct"] = _f("total_return_pct")
    metrics["cagr"] = _f("cagr")
    metrics["sharpe"] = _f("sharpe", _f("sharpe_ratio"))
    metrics["sortino"] = _f("sortino", _f("sortino_ratio"))
    metrics["calmar"] = _f("calmar", _f("calmar_ratio"))
    metrics["total_trades"] = _f("total_trades")
    metrics["win_rate"] = _f("win_rate")
    metrics["profit_factor"] = _f("profit_factor")

    # Nested drawdown
    dd = d.get("drawdown", d.get("max_drawdown", {}))
    if isinstance(dd, dict):
        metrics["max_drawdown"] = _f("max_drawdown_pct", 0.0) or float(
            dd.get("max_drawdown_pct", 0.0)
        )
    else:
        metrics["max_drawdown"] = float(dd or 0.0)

    # Nested risk
    risk = d.get("risk", {})
    if isinstance(risk, dict):
        metrics["volatility"] = float(risk.get("volatility", 0.0))
        metrics["var_95"] = float(risk.get("var_95", 0.0))
    else:
        metrics["volatility"] = 0.0
        metrics["var_95"] = 0.0

    # Nested trade_stats
    ts = d.get("trade_stats", {})
    if isinstance(ts, dict) and not metrics["win_rate"]:
        metrics["win_rate"] = float(ts.get("win_rate", 0.0))
    if isinstance(ts, dict) and not metrics["profit_factor"]:
        metrics["profit_factor"] = float(ts.get("profit_factor", 0.0))
    if isinstance(ts, dict) and not metrics["total_trades"]:
        metrics["total_trades"] = float(ts.get("total_trades", 0.0))

    return metrics


def _extract_from_dataclass(result: Any) -> dict[str, float]:
    """Extract metrics from a :class:`BacktestResult` dataclass."""
    # Try to compute PerformanceReport if not already present
    report = getattr(result, "_perf_report", None)
    if report is None:
        try:
            from .metrics import PerformanceMetrics

            report = PerformanceMetrics.compute(result)
        except Exception:
            try:
                from metrics import PerformanceMetrics  # type: ignore[import]

                report = PerformanceMetrics.compute(result)
            except Exception:
                report = None

    metrics: dict[str, float] = {
        "total_return_pct": float(getattr(result, "total_return_pct", 0.0)),
    }

    if report is not None:
        dd = report.drawdown
        ts = report.trade_stats
        risk = report.risk
        metrics.update({
            "cagr": float(getattr(report, "cagr", 0.0)),
            "sharpe": float(getattr(report, "sharpe_ratio", 0.0)),
            "sortino": float(getattr(report, "sortino_ratio", 0.0)),
            "calmar": float(getattr(report, "calmar_ratio", 0.0)),
            "max_drawdown": float(getattr(dd, "max_drawdown_pct", 0.0)),
            "win_rate": float(getattr(ts, "win_rate", 0.0)),
            "profit_factor": float(getattr(ts, "profit_factor", 0.0)),
            "total_trades": float(getattr(ts, "total_trades", 0.0)),
            "volatility": float(getattr(risk, "volatility", 0.0)),
            "var_95": float(getattr(risk, "var_95", 0.0)),
        })
    else:
        # Fallback: populate from result attributes directly
        for key in _EXTRACTABLE_METRICS:
            val = getattr(result, key, None)
            if val is not None:
                metrics[key] = float(val)

    return metrics


def _equity_values(result: Any) -> list[float]:
    """Extract a flat list of equity floats from a BacktestResult or dict."""
    if isinstance(result, dict):
        curve = result.get("equity_curve", [])
        if not curve:
            return []
        if isinstance(curve[0], dict):
            return [float(pt.get("equity", 0.0)) for pt in curve]
        return [float(v) for v in curve]

    curve = getattr(result, "equity_curve", [])
    if not curve:
        return []
    if hasattr(curve[0], "equity"):
        return [float(pt.equity) for pt in curve]
    return [float(v) for v in curve]


# ---------------------------------------------------------------------------
# Main comparator
# ---------------------------------------------------------------------------


class StrategyComparator:
    """Compare multiple backtest results and produce a ranked comparison report.

    Args:
        metric_weights: Custom weights for the composite scoring function.
            Keys must be metric names; values are non-negative floats that
            will be normalised to sum to 1.  Default weights:
            Sharpe 0.30, CAGR 0.30, max_drawdown 0.20, win_rate 0.20.

    Example::

        comparator = StrategyComparator(
            metric_weights={"sharpe": 0.5, "max_drawdown": 0.3, "win_rate": 0.2}
        )
        result = comparator.compare({"Alpha": r1, "Beta": r2, "Gamma": r3})
        print(result.best_overall)
    """

    def __init__(self, metric_weights: dict[str, float] | None = None) -> None:
        raw = metric_weights or _DEFAULT_WEIGHTS
        total = sum(abs(v) for v in raw.values())
        if total == 0.0:
            raise ValueError("metric_weights values must not all be zero")
        self._weights: dict[str, float] = {k: abs(v) / total for k, v in raw.items()}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compare(self, results: dict[str, Any]) -> StrategyComparisonResult:
        """Compare multiple backtest results and return a ranked report.

        Args:
            results: Mapping of ``{strategy_name: BacktestResult}``.  Values
                may be :class:`BacktestResult` dataclass instances or plain
                dicts (for API use).

        Returns:
            :class:`StrategyComparisonResult` with metrics, rankings, equity
            curves, correlation matrix, and the overall best strategy.

        Raises:
            ValueError: When fewer than two strategies are provided or the
                results mapping is empty.
        """
        if not results:
            raise ValueError("At least one strategy result is required")

        strategy_names = list(results.keys())

        # Extract metrics for every strategy
        all_metrics: dict[str, dict[str, float]] = {
            name: _extract_metrics(result) for name, result in results.items()
        }

        # Build rankings for every metric that appears in the data
        metric_names: set[str] = set()
        for m in all_metrics.values():
            metric_names.update(m.keys())

        rankings: dict[str, list[str]] = {}
        for metric in sorted(metric_names):
            ranked = self._rank_strategies(all_metrics, metric)
            if ranked:
                rankings[metric] = ranked

        # Weighted composite score → best_overall
        scores = {
            name: self.weighted_score(all_metrics[name])
            for name in strategy_names
        }
        best_overall = max(scores, key=lambda n: scores[n])

        # Equity curves
        equity_curves: dict[str, list[float]] = {
            name: _equity_values(result) for name, result in results.items()
        }

        # Correlation matrix
        corr_matrix = self._correlation_matrix(equity_curves, strategy_names)

        return StrategyComparisonResult(
            strategies=strategy_names,
            metrics=all_metrics,
            rankings=rankings,
            best_overall=best_overall,
            equity_curves=equity_curves,
            correlation_matrix=corr_matrix,
        )

    def rank_by_metric(self, results: dict[str, Any], metric: str) -> list[str]:
        """Rank strategy names by a single metric, best first.

        Args:
            results: Mapping of ``{strategy_name: BacktestResult}``.
            metric: Metric name to rank by (e.g. ``"sharpe"``, ``"cagr"``).

        Returns:
            List of strategy names sorted best-first for the given metric.
        """
        all_metrics = {
            name: _extract_metrics(result) for name, result in results.items()
        }
        return self._rank_strategies(all_metrics, metric)

    def weighted_score(self, metrics: dict[str, float]) -> float:
        """Compute a weighted composite score for a single strategy.

        Metrics in :data:`_LOWER_IS_BETTER` are negated before weighting so
        that a lower raw value yields a *higher* score contribution.

        Args:
            metrics: Flat ``{metric_name: value}`` dict for one strategy.

        Returns:
            Weighted composite score (higher is better).
        """
        score = 0.0
        for metric, weight in self._weights.items():
            value = float(metrics.get(metric, 0.0))
            if not math.isfinite(value):
                value = 0.0
            if metric in _LOWER_IS_BETTER:
                value = -value
            score += weight * value
        return score

    def optimal_blend(self, results: dict[str, Any]) -> dict[str, float]:
        """Suggest an optimal portfolio blend of the given strategies.

        Uses inverse-variance weighting on strategy returns as a lightweight
        alternative to full mean-variance optimisation (no scipy required).
        Strategies with very high correlation (|r| > 0.95) to a previously
        selected strategy receive a 50% weight penalty to encourage
        diversification.

        Args:
            results: Mapping of ``{strategy_name: BacktestResult}``.

        Returns:
            Dict mapping strategy name to blend weight (values sum to 1.0).
            Returns equal-weight allocation when returns or equity curves are
            unavailable.
        """
        strategy_names = list(results.keys())
        n = len(strategy_names)

        if n == 0:
            return {}
        if n == 1:
            return {strategy_names[0]: 1.0}

        equity_curves = {
            name: _equity_values(result) for name, result in results.items()
        }

        # Compute per-bar returns for each strategy
        strategy_returns: dict[str, np.ndarray] = {}
        for name, curve in equity_curves.items():
            if len(curve) < 2:
                continue
            arr = np.array(curve, dtype=float)
            # Filter non-finite values
            arr = arr[np.isfinite(arr)]
            if len(arr) < 2:
                continue
            rets = np.diff(arr) / np.where(arr[:-1] != 0, arr[:-1], 1.0)
            strategy_returns[name] = rets

        if len(strategy_returns) < 2:
            # Fall back to equal weight
            eq = 1.0 / n
            return {name: round(eq, 6) for name in strategy_names}

        # Align to minimum length
        min_len = min(len(r) for r in strategy_returns.values())
        aligned = {
            name: ret[:min_len] for name, ret in strategy_returns.items()
        }

        # Inverse-variance weights
        variances: dict[str, float] = {}
        for name, rets in aligned.items():
            var = float(np.var(rets))
            variances[name] = max(var, 1e-12)  # prevent division by zero

        # Diversification penalty: penalise highly-correlated pairs
        raw_weights: dict[str, float] = {}
        names_with_returns = list(aligned.keys())
        selected: list[str] = []
        penalties: dict[str, float] = {n: 1.0 for n in names_with_returns}

        for name in names_with_returns:
            for sel in selected:
                corr = float(
                    np.corrcoef(aligned[name], aligned[sel])[0, 1]
                )
                if abs(corr) > 0.95:
                    penalties[name] *= 0.5
            selected.append(name)

        inv_var_sum = sum(
            (1.0 / variances[n]) * penalties[n] for n in names_with_returns
        )
        for name in names_with_returns:
            raw_weights[name] = (1.0 / variances[name]) * penalties[name] / inv_var_sum

        # Fill missing strategies (no equity curve data) with zero weight
        all_weights = {name: raw_weights.get(name, 0.0) for name in strategy_names}

        # Normalise so weights sum to exactly 1.0
        total = sum(all_weights.values())
        if total > 0:
            all_weights = {n: round(w / total, 6) for n, w in all_weights.items()}

        return all_weights

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _rank_strategies(
        self, all_metrics: dict[str, dict[str, float]], metric: str
    ) -> list[str]:
        """Rank strategy names by a metric, best first.

        Handles ``_LOWER_IS_BETTER`` metrics by reversing the sort direction.

        Args:
            all_metrics: Mapping of ``{strategy_name: {metric: value}}``.
            metric: Metric name.

        Returns:
            Strategy names sorted best-first.  Strategies missing the metric
            are placed last with an effective value of 0.
        """
        lower_better = metric in _LOWER_IS_BETTER

        def _sort_key(name: str) -> float:
            val = float(all_metrics[name].get(metric, 0.0))
            if not math.isfinite(val):
                val = 0.0
            return -val if lower_better else val

        return sorted(all_metrics.keys(), key=_sort_key, reverse=True)

    @staticmethod
    def _correlation_matrix(
        equity_curves: dict[str, list[float]], strategy_names: list[str]
    ) -> list[list[float]]:
        """Compute the pairwise return-correlation matrix.

        Returns an N×N matrix where entry [i][j] is the Pearson correlation
        between the per-bar returns of strategy i and strategy j.

        Args:
            equity_curves: Mapping of ``{strategy_name: [equity_values]}``.
            strategy_names: Ordered list of strategy names (defines row/col order).

        Returns:
            N×N correlation matrix as a list-of-lists (serialisable).
            Diagonal entries are always 1.0.  When a strategy has no usable
            equity curve, its row/column entries are 0.0.
        """
        n = len(strategy_names)
        matrix = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]

        # Build return series for each strategy
        return_series: list[np.ndarray | None] = []
        for name in strategy_names:
            curve = equity_curves.get(name, [])
            if len(curve) < 2:
                return_series.append(None)
                continue
            arr = np.array(curve, dtype=float)
            arr = arr[np.isfinite(arr)]
            if len(arr) < 2:
                return_series.append(None)
                continue
            rets = np.diff(arr) / np.where(arr[:-1] != 0, arr[:-1], 1.0)
            return_series.append(rets)

        for i in range(n):
            for j in range(i + 1, n):
                ri = return_series[i]
                rj = return_series[j]
                if ri is None or rj is None:
                    continue
                # Align lengths
                min_len = min(len(ri), len(rj))
                if min_len < 2:
                    continue
                corr_matrix = np.corrcoef(ri[:min_len], rj[:min_len])
                corr = float(corr_matrix[0, 1])
                if not math.isfinite(corr):
                    corr = 0.0
                matrix[i][j] = round(corr, 6)
                matrix[j][i] = round(corr, 6)

        return matrix


# ---------------------------------------------------------------------------
# Flask Blueprint
# ---------------------------------------------------------------------------

strategy_comparison_bp = Blueprint("strategy_comparison", __name__)


@strategy_comparison_bp.route("/backtest/compare", methods=["POST"])
def backtest_compare_endpoint() -> tuple[Any, int]:
    """Compare multiple backtest results side-by-side.

    Request body (JSON):
        results (dict): Mapping of ``{strategy_name: backtest_result_dict}``.
            Each result dict should include ``equity_curve`` and optionally
            pre-computed metric fields (``sharpe``, ``cagr``, ``max_drawdown``,
            ``win_rate``, ``total_return_pct``, ``drawdown``, ``trade_stats``,
            ``risk``).
        metric_weights (dict, optional): Custom metric weights for composite
            scoring.  Defaults to Sharpe 0.30, CAGR 0.30, max_drawdown 0.20,
            win_rate 0.20.

    Returns:
        JSON with ``status`` and ``data`` keys.  ``data`` is the serialised
        :class:`StrategyComparisonResult`.

    Status codes:
        200: Success.
        400: Missing or malformed ``results`` field.
        500: Internal processing error.
    """
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"status": "error", "message": "JSON body required"}), 400

    results = payload.get("results")
    if results is None:
        return jsonify({"status": "error", "message": "'results' field required"}), 400
    if not isinstance(results, dict):
        return jsonify({"status": "error", "message": "'results' must be an object"}), 400
    if not results:
        return jsonify({"status": "error", "message": "'results' must not be empty"}), 400

    metric_weights: dict[str, float] | None = payload.get("metric_weights")

    try:
        comparator = StrategyComparator(metric_weights=metric_weights)
        comparison = comparator.compare(results)
        blend = comparator.optimal_blend(results)
        response_data = comparison.model_dump()
        response_data["optimal_blend"] = blend
        return jsonify({"status": "success", "data": response_data}), 200
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception as exc:
        logger.exception("Strategy comparison failed: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500
