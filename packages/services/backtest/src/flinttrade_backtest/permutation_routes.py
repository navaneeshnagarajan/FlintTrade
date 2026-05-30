"""Flask Blueprint for permutation testing and walk-forward analysis.

External URLs (frontend calls these via /ft-api/v1/backtest/*; the WSGI prefix
stripper in app.py rewrites to /v1/backtest/* before Flask dispatch):

- ``POST /ft-api/v1/backtest/permutation`` — test strategy significance
- ``POST /ft-api/v1/backtest/walkforward`` — run walk-forward analysis

Blueprint registered at ``/v1/backtest`` (post-strip form).

---

**Permutation test request** (``/permutation``)::

    {
        "returns": [0.01, -0.005, 0.008, ...],          // daily return fractions
        "benchmark_returns": [0.002, 0.001, ...],        // optional, same length
        "trades": [                                      // optional, for test_trades mode
            {"return_pct": 0.015},
            {"net_pnl": 1200.0},
            ...
        ],
        "mode": "returns" | "trades",                    // default: "returns"
        "config": {                                      // optional
            "n_permutations": 1000,
            "confidence_level": 0.95,
            "metric": "sharpe_ratio",
            "random_seed": 42
        }
    }

Response::

    {
        "status": "success",
        "data": {
            "original_metric": 1.42,
            "permutation_mean": 0.31,
            "permutation_std": 0.58,
            "p_value": 0.021,
            "is_significant": true,
            "confidence_level": 0.95,
            "n_permutations": 1000,
            "percentile_rank": 97.9
        }
    }

---

**Walk-forward request** (``/walkforward``)::

    {
        "bars": [                                        // list of OHLCV dicts
            {"close": 18500.0, ...},
            ...
        ],
        "metric": "sharpe_ratio",                       // optional, default
        "config": {                                     // optional
            "n_splits": 5,
            "train_ratio": 0.7,
            "anchored": false
        }
    }

Note: ``strategy_class`` cannot be passed via HTTP.  The endpoint uses
a built-in ``BuyAndHoldStrategy`` (close-to-close returns) as a baseline.
For full strategy walk-forward with a real strategy class, use
:class:`~flinttrade_backtest.walk_forward.WalkForwardAnalyser`
programmatically.

Response::

    {
        "status": "success",
        "data": {
            "splits": [ ... ],
            "avg_train_metric": 1.12,
            "avg_test_metric": 0.89,
            "degradation_pct": 20.5,
            "is_robust": true,
            "n_splits_run": 5
        }
    }
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, Response, jsonify, request
from pydantic import ValidationError

try:
    from .permutation_test import PermutationConfig, PermutationTester
    from .walk_forward import WalkForwardAnalyser, WalkForwardConfig
except ImportError:
    from flinttrade_backtest.permutation_test import PermutationConfig, PermutationTester  # type: ignore[no-redef]
    from flinttrade_backtest.walk_forward import WalkForwardAnalyser, WalkForwardConfig  # type: ignore[no-redef]

logger = logging.getLogger("flinttrade.backtest.permutation_routes")

permutation_bp = Blueprint(
    "backtest_permutation",
    __name__,
    url_prefix="/v1/backtest",
)


# ---------------------------------------------------------------------------
# Built-in strategy for walk-forward HTTP endpoint
# ---------------------------------------------------------------------------


class _BuyAndHoldStrategy:
    """Minimal buy-and-hold strategy for the walk-forward HTTP endpoint.

    Records close-to-close daily returns as ``daily_returns`` so that
    :func:`~flinttrade_backtest.walk_forward._run_strategy_on_bars`
    can extract them.

    Args:
        **kwargs: Ignored — accepts arbitrary kwargs so walk-forward can
                  pass ``strategy_kwargs`` safely.
    """

    def __init__(self, **kwargs: Any) -> None:
        self.daily_returns: list[float] = []
        self._prev_close: float | None = None

    def on_bar(self, bar: dict[str, Any]) -> None:
        """Record bar-to-bar return.

        Args:
            bar: OHLCV dict with a ``"close"`` (or ``"Close"`` / ``"c"``) key.
        """
        close_raw = bar.get("close") or bar.get("Close") or bar.get("c")
        if close_raw is None:
            return
        try:
            close = float(close_raw)
        except (TypeError, ValueError):
            return

        if self._prev_close is not None and self._prev_close > 0:
            self.daily_returns.append((close - self._prev_close) / self._prev_close)
        self._prev_close = close


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _parse_floats(raw: Any, field_name: str) -> list[float] | None:
    """Validate and convert a JSON value to a list of floats.

    Args:
        raw:        Decoded JSON value.
        field_name: Field name for error messages.

    Returns:
        ``list[float]`` or ``None`` on validation failure.
    """
    if not isinstance(raw, list) or not raw:
        return None
    try:
        return [float(v) for v in raw]
    except (TypeError, ValueError):
        logger.debug("Failed to parse %s as list[float]", field_name)
        return None


def _parse_permutation_config(raw: Any) -> PermutationConfig | None:
    """Parse optional config dict into :class:`PermutationConfig`.

    Args:
        raw: Decoded JSON value or ``None``.

    Returns:
        :class:`PermutationConfig` (defaults used when ``raw`` is ``None``).
    """
    if raw is None:
        return PermutationConfig()
    if not isinstance(raw, dict):
        return None
    try:
        return PermutationConfig(**raw)
    except (ValidationError, TypeError) as exc:
        logger.debug("PermutationConfig parse error: %s", exc)
        return None


def _parse_walk_forward_config(raw: Any) -> WalkForwardConfig | None:
    """Parse optional config dict into :class:`WalkForwardConfig`.

    Args:
        raw: Decoded JSON value or ``None``.

    Returns:
        :class:`WalkForwardConfig` (defaults used when ``raw`` is ``None``).
    """
    if raw is None:
        return WalkForwardConfig()
    if not isinstance(raw, dict):
        return None
    try:
        return WalkForwardConfig(**raw)
    except (ValidationError, TypeError) as exc:
        logger.debug("WalkForwardConfig parse error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@permutation_bp.route("/permutation", methods=["POST"])
def run_permutation_test() -> tuple[Response, int]:
    """Test whether a strategy's performance is statistically significant.

    Request JSON:
        returns (list[float], required for mode="returns"): Daily return series.
        benchmark_returns (list[float], optional): Benchmark return series.
        trades (list[dict], required for mode="trades"): Trade list with
            ``return_pct`` or ``net_pnl`` keys.
        mode (str, optional): ``"returns"`` (default) or ``"trades"``.
        config (dict, optional): :class:`PermutationConfig` fields.

    Returns:
        JSON with ``status`` and ``data`` fields.
    """
    body: dict[str, Any] = request.get_json(silent=True) or {}
    mode: str = body.get("mode", "returns")

    config = _parse_permutation_config(body.get("config"))
    if config is None:
        return jsonify({
            "status": "error",
            "message": (
                "config is invalid — see PermutationConfig for valid fields "
                "(n_permutations, confidence_level, metric, random_seed)"
            ),
        }), 400

    tester = PermutationTester(config)

    if mode == "trades":
        trades_raw = body.get("trades")
        if not isinstance(trades_raw, list) or not trades_raw:
            return jsonify({
                "status": "error",
                "message": "trades must be a non-empty list of dicts when mode='trades'",
            }), 400

        all_returns_raw = body.get("returns")
        if all_returns_raw is None:
            return jsonify({
                "status": "error",
                "message": "returns (full return series) is required when mode='trades'",
            }), 400

        all_returns = _parse_floats(all_returns_raw, "returns")
        if all_returns is None:
            return jsonify({
                "status": "error",
                "message": "returns must be a non-empty list of numbers",
            }), 400

        try:
            result = tester.test_trades(trades_raw, all_returns)
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 422
        except Exception as exc:
            logger.exception("Unexpected error in test_trades")
            return jsonify({"status": "error", "message": f"Internal error: {exc}"}), 500

    else:
        # Default: mode == "returns"
        returns_raw = body.get("returns")
        if returns_raw is None:
            return jsonify({
                "status": "error",
                "message": "returns field is required",
            }), 400

        strategy_returns = _parse_floats(returns_raw, "returns")
        if strategy_returns is None:
            return jsonify({
                "status": "error",
                "message": "returns must be a non-empty list of numbers",
            }), 400

        benchmark_returns: list[float] | None = None
        bench_raw = body.get("benchmark_returns")
        if bench_raw is not None:
            benchmark_returns = _parse_floats(bench_raw, "benchmark_returns")
            if benchmark_returns is None:
                return jsonify({
                    "status": "error",
                    "message": "benchmark_returns must be a non-empty list of numbers",
                }), 400

        try:
            result = tester.test_returns(strategy_returns, benchmark_returns)
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 422
        except Exception as exc:
            logger.exception("Unexpected error in test_returns")
            return jsonify({"status": "error", "message": f"Internal error: {exc}"}), 500

    logger.info(
        "Permutation test complete: metric=%s p_value=%.4f significant=%s",
        config.metric, result.p_value, result.is_significant,
    )
    return jsonify({"status": "success", "data": result.as_dict()}), 200


@permutation_bp.route("/walkforward", methods=["POST"])
def run_walk_forward() -> tuple[Response, int]:
    """Run walk-forward analysis on a bar series.

    Uses a built-in buy-and-hold baseline strategy.  For custom strategy
    classes use :class:`~flinttrade_backtest.walk_forward.WalkForwardAnalyser`
    programmatically.

    Request JSON:
        bars (list[dict], required): OHLCV bar dicts with a ``"close"`` key.
        metric (str, optional): Metric to compare (default: ``"sharpe_ratio"``).
        config (dict, optional): :class:`WalkForwardConfig` fields.

    Returns:
        JSON with ``status`` and ``data`` fields.
    """
    body: dict[str, Any] = request.get_json(silent=True) or {}

    bars_raw = body.get("bars")
    if not isinstance(bars_raw, list) or not bars_raw:
        return jsonify({
            "status": "error",
            "message": "bars must be a non-empty list of OHLCV dicts",
        }), 400

    metric: str = body.get("metric", "sharpe_ratio")

    wf_config = _parse_walk_forward_config(body.get("config"))
    if wf_config is None:
        return jsonify({
            "status": "error",
            "message": (
                "config is invalid — see WalkForwardConfig for valid fields "
                "(n_splits, train_ratio, anchored)"
            ),
        }), 400

    analyser = WalkForwardAnalyser(wf_config)

    try:
        result = analyser.analyse(
            bars=bars_raw,
            strategy_class=_BuyAndHoldStrategy,
            strategy_kwargs={},
            metric=metric,
        )
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 422
    except Exception as exc:
        logger.exception("Unexpected error in walk-forward analysis")
        return jsonify({"status": "error", "message": f"Internal error: {exc}"}), 500

    logger.info(
        "Walk-forward complete: %d splits, degradation=%.1f%%, robust=%s",
        result.n_splits_run, result.degradation_pct, result.is_robust,
    )
    return jsonify({"status": "success", "data": result.as_dict()}), 200
