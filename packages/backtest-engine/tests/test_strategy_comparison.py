"""Tests for strategy_comparison.py — multi-strategy ranking and blending.

All tests use plain-dict BacktestResult representations (no simulator
dependency) to keep the tests fast and isolated.
"""

from __future__ import annotations

import math

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _equity_curve(start: float = 100_000.0, step: float = 500.0, n: int = 50) -> list[dict]:
    """Generate a simple upward-trending equity curve."""
    return [{"equity": start + i * step, "timestamp": f"2026-01-{(i % 28) + 1:02d}"} for i in range(n)]


def _flat_curve(equity: float = 100_000.0, n: int = 50) -> list[dict]:
    return [{"equity": equity, "timestamp": f"2026-01-{(i % 28) + 1:02d}"} for i in range(n)]


def _drawdown_curve(n: int = 50) -> list[dict]:
    """Curve that dips mid-way."""
    curve = []
    for i in range(n):
        if i < 20:
            eq = 100_000.0 + i * 1_000
        elif i < 35:
            eq = 120_000.0 - (i - 20) * 2_000
        else:
            eq = 90_000.0 + (i - 35) * 500
        curve.append({"equity": eq, "timestamp": f"2026-01-{(i % 28) + 1:02d}"})
    return curve


def _make_result(
    sharpe: float = 1.0,
    cagr: float = 15.0,
    max_drawdown: float = 10.0,
    win_rate: float = 55.0,
    equity_curve: list | None = None,
    total_trades: int = 100,
    profit_factor: float = 1.5,
) -> dict:
    """Build a minimal backtest result dict."""
    return {
        "sharpe": sharpe,
        "cagr": cagr,
        "max_drawdown": max_drawdown,
        "win_rate": win_rate,
        "total_trades": total_trades,
        "profit_factor": profit_factor,
        "total_return_pct": cagr * 1.2,
        "equity_curve": equity_curve or _equity_curve(),
        "risk": {"volatility": 12.0, "var_95": 2.0},
    }


def _make_comparator(weights=None):
    from strategy_comparison import StrategyComparator
    return StrategyComparator(metric_weights=weights)


# ---------------------------------------------------------------------------
# StrategyComparator — basic construction
# ---------------------------------------------------------------------------


class TestStrategyComparatorInit:
    def test_default_weights_normalised(self):
        c = _make_comparator()
        total = sum(c._weights.values())
        assert total == pytest.approx(1.0)

    def test_custom_weights_normalised(self):
        c = _make_comparator({"sharpe": 2.0, "cagr": 2.0})
        assert sum(c._weights.values()) == pytest.approx(1.0)

    def test_all_zero_weights_raises(self):
        with pytest.raises(ValueError, match="zero"):
            _make_comparator({"sharpe": 0.0})


# ---------------------------------------------------------------------------
# weighted_score
# ---------------------------------------------------------------------------


class TestWeightedScore:
    def test_higher_sharpe_higher_score(self):
        c = _make_comparator({"sharpe": 1.0})
        s1 = c.weighted_score({"sharpe": 2.0})
        s2 = c.weighted_score({"sharpe": 1.0})
        assert s1 > s2

    def test_lower_drawdown_higher_score(self):
        c = _make_comparator({"max_drawdown": 1.0})
        s1 = c.weighted_score({"max_drawdown": 5.0})   # lower drawdown
        s2 = c.weighted_score({"max_drawdown": 20.0})  # higher drawdown
        assert s1 > s2

    def test_missing_metric_treated_as_zero(self):
        c = _make_comparator({"sharpe": 0.5, "cagr": 0.5})
        score = c.weighted_score({"sharpe": 1.0})  # cagr missing
        expected = 0.5 * 1.0 + 0.5 * 0.0
        assert score == pytest.approx(expected)

    def test_infinite_value_treated_as_zero(self):
        c = _make_comparator({"sharpe": 1.0})
        score = c.weighted_score({"sharpe": float("inf")})
        assert score == pytest.approx(0.0)

    def test_nan_value_treated_as_zero(self):
        c = _make_comparator({"sharpe": 1.0})
        score = c.weighted_score({"sharpe": float("nan")})
        assert score == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# rank_by_metric
# ---------------------------------------------------------------------------


class TestRankByMetric:
    def test_rank_by_sharpe(self):
        results = {
            "Alpha": _make_result(sharpe=2.0),
            "Beta": _make_result(sharpe=0.5),
            "Gamma": _make_result(sharpe=1.5),
        }
        c = _make_comparator()
        ranked = c.rank_by_metric(results, "sharpe")
        assert ranked[0] == "Alpha"
        assert ranked[-1] == "Beta"

    def test_rank_by_drawdown_lower_is_better(self):
        results = {
            "Low DD": _make_result(max_drawdown=5.0),
            "High DD": _make_result(max_drawdown=30.0),
        }
        c = _make_comparator()
        ranked = c.rank_by_metric(results, "max_drawdown")
        assert ranked[0] == "Low DD"

    def test_rank_by_win_rate(self):
        results = {
            "S1": _make_result(win_rate=70.0),
            "S2": _make_result(win_rate=45.0),
            "S3": _make_result(win_rate=55.0),
        }
        c = _make_comparator()
        ranked = c.rank_by_metric(results, "win_rate")
        assert ranked[0] == "S1"

    def test_rank_returns_all_strategies(self):
        results = {f"S{i}": _make_result(sharpe=float(i)) for i in range(5)}
        c = _make_comparator()
        ranked = c.rank_by_metric(results, "sharpe")
        assert len(ranked) == 5
        assert set(ranked) == set(results.keys())


# ---------------------------------------------------------------------------
# compare — StrategyComparisonResult structure
# ---------------------------------------------------------------------------


class TestCompare:
    def test_empty_results_raises(self):
        c = _make_comparator()
        with pytest.raises(ValueError):
            c.compare({})

    def test_single_strategy(self):
        results = {"OnlyOne": _make_result()}
        c = _make_comparator()
        result = c.compare(results)
        assert result.best_overall == "OnlyOne"
        assert result.strategies == ["OnlyOne"]

    def test_strategies_list_populated(self):
        results = {
            "Alpha": _make_result(sharpe=2.0),
            "Beta": _make_result(sharpe=1.0),
        }
        c = _make_comparator()
        result = c.compare(results)
        assert set(result.strategies) == {"Alpha", "Beta"}

    def test_metrics_populated(self):
        results = {
            "Alpha": _make_result(sharpe=2.0, cagr=20.0),
        }
        c = _make_comparator()
        result = c.compare(results)
        assert "Alpha" in result.metrics
        assert "sharpe" in result.metrics["Alpha"]
        assert result.metrics["Alpha"]["sharpe"] == pytest.approx(2.0)

    def test_best_overall_is_best_composite(self):
        results = {
            "Strong": _make_result(sharpe=2.5, cagr=25.0, max_drawdown=5.0, win_rate=65.0),
            "Weak": _make_result(sharpe=0.3, cagr=3.0, max_drawdown=40.0, win_rate=35.0),
        }
        c = _make_comparator()
        result = c.compare(results)
        assert result.best_overall == "Strong"

    def test_rankings_contain_all_metrics(self):
        results = {
            "Alpha": _make_result(),
            "Beta": _make_result(),
        }
        c = _make_comparator()
        result = c.compare(results)
        assert isinstance(result.rankings, dict)
        for metric, ranked in result.rankings.items():
            assert set(ranked) == {"Alpha", "Beta"}

    def test_equity_curves_populated(self):
        curve = _equity_curve()
        results = {"Alpha": _make_result(equity_curve=curve)}
        c = _make_comparator()
        result = c.compare(results)
        assert "Alpha" in result.equity_curves
        assert len(result.equity_curves["Alpha"]) == len(curve)

    def test_equity_curves_are_floats(self):
        results = {"Alpha": _make_result()}
        c = _make_comparator()
        result = c.compare(results)
        for v in result.equity_curves["Alpha"]:
            assert isinstance(v, float)

    def test_correlation_matrix_shape(self):
        results = {
            "Alpha": _make_result(equity_curve=_equity_curve(step=500)),
            "Beta": _make_result(equity_curve=_equity_curve(step=200)),
            "Gamma": _make_result(equity_curve=_drawdown_curve()),
        }
        c = _make_comparator()
        result = c.compare(results)
        n = 3
        assert len(result.correlation_matrix) == n
        for row in result.correlation_matrix:
            assert len(row) == n

    def test_correlation_diagonal_is_one(self):
        results = {
            "Alpha": _make_result(equity_curve=_equity_curve(step=500)),
            "Beta": _make_result(equity_curve=_equity_curve(step=200)),
        }
        c = _make_comparator()
        result = c.compare(results)
        for i, row in enumerate(result.correlation_matrix):
            assert row[i] == pytest.approx(1.0)

    def test_correlation_symmetry(self):
        results = {
            "Alpha": _make_result(equity_curve=_equity_curve(step=300)),
            "Beta": _make_result(equity_curve=_drawdown_curve()),
        }
        c = _make_comparator()
        result = c.compare(results)
        m = result.correlation_matrix
        assert m[0][1] == pytest.approx(m[1][0])

    def test_result_serialisable(self):
        import json

        results = {
            "Alpha": _make_result(),
            "Beta": _make_result(sharpe=0.5),
        }
        c = _make_comparator()
        result = c.compare(results)
        json.dumps(result.model_dump())  # should not raise

    def test_three_strategies_rankings_order(self):
        results = {
            "High": _make_result(sharpe=3.0),
            "Mid": _make_result(sharpe=1.5),
            "Low": _make_result(sharpe=0.2),
        }
        c = _make_comparator()
        result = c.compare(results)
        ranked = result.rankings["sharpe"]
        assert ranked[0] == "High"
        assert ranked[-1] == "Low"

    def test_no_equity_curve_handled(self):
        """Strategies with no equity curve data should not crash compare."""
        results = {
            "Alpha": _make_result(equity_curve=[]),
            "Beta": _make_result(equity_curve=_equity_curve()),
        }
        c = _make_comparator()
        result = c.compare(results)
        assert "Alpha" in result.strategies


# ---------------------------------------------------------------------------
# optimal_blend
# ---------------------------------------------------------------------------


class TestOptimalBlend:
    def test_empty_returns_empty(self):
        c = _make_comparator()
        assert c.optimal_blend({}) == {}

    def test_single_strategy_full_weight(self):
        results = {"Alpha": _make_result()}
        c = _make_comparator()
        blend = c.optimal_blend(results)
        assert blend == {"Alpha": pytest.approx(1.0)}

    def test_weights_sum_to_one(self):
        results = {
            "Alpha": _make_result(equity_curve=_equity_curve(step=500)),
            "Beta": _make_result(equity_curve=_equity_curve(step=200)),
            "Gamma": _make_result(equity_curve=_drawdown_curve()),
        }
        c = _make_comparator()
        blend = c.optimal_blend(results)
        assert sum(blend.values()) == pytest.approx(1.0, abs=1e-5)

    def test_all_strategies_represented(self):
        results = {
            "Alpha": _make_result(),
            "Beta": _make_result(),
        }
        c = _make_comparator()
        blend = c.optimal_blend(results)
        assert set(blend.keys()) == {"Alpha", "Beta"}

    def test_non_negative_weights(self):
        results = {
            "Alpha": _make_result(equity_curve=_equity_curve(step=100)),
            "Beta": _make_result(equity_curve=_drawdown_curve()),
        }
        c = _make_comparator()
        blend = c.optimal_blend(results)
        for weight in blend.values():
            assert weight >= 0.0

    def test_highly_correlated_strategies_penalised(self):
        """Two perfectly-correlated strategies should not both get 50% each (one penalised)."""
        same_curve = _equity_curve(step=500)
        results = {
            "CloneA": _make_result(equity_curve=same_curve),
            "CloneB": _make_result(equity_curve=same_curve),
            "Unique": _make_result(equity_curve=_drawdown_curve()),
        }
        c = _make_comparator()
        blend = c.optimal_blend(results)
        # Unique should receive a meaningful share (not zero)
        assert blend.get("Unique", 0.0) > 0.0

    def test_fallback_equal_weight_when_no_curves(self):
        results = {
            "Alpha": _make_result(equity_curve=[]),
            "Beta": _make_result(equity_curve=[]),
        }
        c = _make_comparator()
        blend = c.optimal_blend(results)
        total = sum(blend.values())
        assert total == pytest.approx(1.0, abs=1e-5)


# ---------------------------------------------------------------------------
# Flat equity curve edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_flat_equity_curve_correlation_zero(self):
        """Flat curves produce near-zero variance returns; should not crash."""
        results = {
            "Flat": _make_result(equity_curve=_flat_curve()),
            "Trending": _make_result(equity_curve=_equity_curve()),
        }
        c = _make_comparator()
        result = c.compare(results)
        # Should produce a valid result without NaN/inf
        for row in result.correlation_matrix:
            for v in row:
                assert math.isfinite(v)

    def test_single_point_equity_curve(self):
        results = {
            "Short": _make_result(equity_curve=[{"equity": 100_000.0, "timestamp": "2026-01-01"}]),
        }
        c = _make_comparator()
        result = c.compare(results)
        assert result.best_overall == "Short"

    def test_dict_extraction_nested_drawdown(self):
        """Ensure nested drawdown dict is extracted correctly."""
        result_dict = {
            "sharpe": 1.5,
            "cagr": 18.0,
            "win_rate": 60.0,
            "drawdown": {"max_drawdown_pct": 12.0},
            "equity_curve": _equity_curve(),
        }
        c = _make_comparator()
        comparison = c.compare({"S1": result_dict})
        assert comparison.metrics["S1"]["max_drawdown"] == pytest.approx(12.0)

    def test_dict_extraction_nested_trade_stats(self):
        result_dict = {
            "sharpe": 1.0,
            "equity_curve": _equity_curve(),
            "trade_stats": {"win_rate": 52.0, "profit_factor": 1.3, "total_trades": 80},
        }
        c = _make_comparator()
        comparison = c.compare({"S1": result_dict})
        assert comparison.metrics["S1"]["win_rate"] == pytest.approx(52.0)


# ---------------------------------------------------------------------------
# Flask endpoint
# ---------------------------------------------------------------------------


class TestBacktestCompareEndpoint:
    @pytest.fixture()
    def client(self):
        from flask import Flask
        from strategy_comparison import strategy_comparison_bp

        app = Flask(__name__)
        app.register_blueprint(strategy_comparison_bp, url_prefix="/ft-api/v1")
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

    def test_missing_body(self, client):
        resp = client.post("/ft-api/v1/backtest/compare")
        assert resp.status_code == 400

    def test_missing_results_key(self, client):
        resp = client.post("/ft-api/v1/backtest/compare", json={"foo": "bar"})
        assert resp.status_code == 400

    def test_results_not_dict(self, client):
        resp = client.post("/ft-api/v1/backtest/compare", json={"results": [1, 2]})
        assert resp.status_code == 400

    def test_empty_results_dict(self, client):
        resp = client.post("/ft-api/v1/backtest/compare", json={"results": {}})
        assert resp.status_code == 400

    def test_valid_request(self, client):
        payload = {
            "results": {
                "Momentum": _make_result(sharpe=1.8, cagr=20.0),
                "MeanRev": _make_result(sharpe=1.2, cagr=14.0),
            }
        }
        resp = client.post("/ft-api/v1/backtest/compare", json=payload)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "success"
        assert "data" in body
        data = body["data"]
        assert "best_overall" in data
        assert "rankings" in data
        assert "metrics" in data
        assert "optimal_blend" in data

    def test_custom_weights_accepted(self, client):
        payload = {
            "results": {
                "S1": _make_result(sharpe=2.0),
                "S2": _make_result(sharpe=0.5),
            },
            "metric_weights": {"sharpe": 1.0},
        }
        resp = client.post("/ft-api/v1/backtest/compare", json=payload)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["best_overall"] == "S1"

    def test_single_strategy(self, client):
        payload = {"results": {"OnlyOne": _make_result()}}
        resp = client.post("/ft-api/v1/backtest/compare", json=payload)
        assert resp.status_code == 200

    def test_response_includes_optimal_blend(self, client):
        payload = {
            "results": {
                "Alpha": _make_result(equity_curve=_equity_curve(step=500)),
                "Beta": _make_result(equity_curve=_drawdown_curve()),
            }
        }
        resp = client.post("/ft-api/v1/backtest/compare", json=payload)
        body = resp.get_json()
        blend = body["data"]["optimal_blend"]
        assert set(blend.keys()) == {"Alpha", "Beta"}
        assert sum(blend.values()) == pytest.approx(1.0, abs=1e-4)
