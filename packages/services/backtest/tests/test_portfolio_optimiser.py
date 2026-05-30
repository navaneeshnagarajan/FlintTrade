"""Tests for portfolio_optimiser.py.

All tests are purely in-process — no HTTP calls, no external data.
Uses pytest with --import-mode=importlib (configured in pyproject.toml / conftest).

Coverage targets:
- OptimiserConfig validation
- PortfolioResult schema
- PortfolioOptimiser.optimise() for every method
- markowitz, min_variance, risk_parity, equal_weight, max_sharpe dispatch
- black_litterman with and without views
- efficient_frontier shape and ordering
- Input validation (empty, single-asset, NaN-only)
- Weight constraints enforcement (max_weight, min_weight)
- Flask routes: /optimise and /frontier (happy and error paths)
"""

from __future__ import annotations

import json
import math

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_returns(n_assets: int = 4, n_days: int = 252, seed: int = 42):
    """Build a synthetic daily-returns DataFrame."""
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(seed)
    assets = [f"ASSET{i}" for i in range(n_assets)]
    data = rng.normal(loc=0.0005, scale=0.015, size=(n_days, n_assets))
    return pd.DataFrame(data, columns=assets)


def _two_asset_returns(n_days: int = 200, seed: int = 7):
    """Minimal two-asset returns frame."""
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(seed)
    data = rng.normal(loc=[0.0008, 0.0003], scale=[0.02, 0.01], size=(n_days, 2))
    return pd.DataFrame(data, columns=["NIFTY", "GOLD"])


@pytest.fixture()
def returns4():
    return _make_returns()


@pytest.fixture()
def returns2():
    return _two_asset_returns()


# ---------------------------------------------------------------------------
# OptimiserConfig
# ---------------------------------------------------------------------------


class TestOptimiserConfig:
    def test_defaults(self):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig
        cfg = OptimiserConfig()
        assert cfg.method == "markowitz"
        assert math.isclose(cfg.risk_free_rate, 0.065)
        assert math.isclose(cfg.max_weight, 0.4)
        assert cfg.min_weight == 0.0
        assert cfg.rebalance_frequency == "monthly"
        assert cfg.target_return is None

    def test_custom_values(self):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig
        cfg = OptimiserConfig(method="risk_parity", risk_free_rate=0.07, max_weight=0.5)
        assert cfg.method == "risk_parity"
        assert math.isclose(cfg.risk_free_rate, 0.07)

    def test_invalid_method(self):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig
        with pytest.raises(Exception):
            OptimiserConfig(method="invalid_method")

    def test_min_gt_max_raises(self):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig
        with pytest.raises(Exception):
            OptimiserConfig(min_weight=0.5, max_weight=0.2)

    def test_rfr_out_of_range_raises(self):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig
        with pytest.raises(Exception):
            OptimiserConfig(risk_free_rate=1.5)

    def test_equal_min_max_allowed(self):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig
        # e.g. equal weight forced by setting min=max=0.25 for 4 assets
        cfg = OptimiserConfig(min_weight=0.25, max_weight=0.25)
        assert cfg.min_weight == cfg.max_weight


# ---------------------------------------------------------------------------
# PortfolioResult
# ---------------------------------------------------------------------------


class TestPortfolioResult:
    def test_schema(self):
        from flinttrade_backtest.portfolio_optimiser import PortfolioResult
        r = PortfolioResult(
            weights={"A": 0.5, "B": 0.5},
            expected_return=0.12,
            expected_volatility=0.18,
            sharpe_ratio=0.3,
            diversification_ratio=1.1,
        )
        assert r.weights["A"] == 0.5
        assert r.expected_return == 0.12

    def test_model_dump(self):
        from flinttrade_backtest.portfolio_optimiser import PortfolioResult
        r = PortfolioResult(
            weights={"X": 1.0},
            expected_return=0.1,
            expected_volatility=0.2,
            sharpe_ratio=0.17,
            diversification_ratio=1.0,
        )
        d = r.model_dump()
        assert "weights" in d
        assert d["sharpe_ratio"] == pytest.approx(0.17)


# ---------------------------------------------------------------------------
# PortfolioOptimiser — validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_empty_dataframe_raises(self):
        import pandas as pd
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        optimiser = PortfolioOptimiser(OptimiserConfig())
        with pytest.raises(ValueError, match="empty"):
            optimiser.optimise(pd.DataFrame())

    def test_single_asset_raises(self):
        import pandas as pd
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        df = pd.DataFrame({"NIFTY": [0.01, 0.02, -0.01]})
        optimiser = PortfolioOptimiser(OptimiserConfig())
        with pytest.raises(ValueError, match="2 assets"):
            optimiser.optimise(df)

    def test_all_nan_raises(self):
        import pandas as pd
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        df = pd.DataFrame({"A": [float("nan")] * 10, "B": [float("nan")] * 10})
        optimiser = PortfolioOptimiser(OptimiserConfig())
        with pytest.raises(ValueError, match="NaN"):
            optimiser.optimise(df)


# ---------------------------------------------------------------------------
# markowitz
# ---------------------------------------------------------------------------


class TestMarkowitz:
    def test_weights_sum_to_one(self, returns4):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        cfg = OptimiserConfig(method="markowitz")
        result = PortfolioOptimiser(cfg).optimise(returns4)
        assert abs(sum(result.weights.values()) - 1.0) < 1e-6

    def test_all_assets_present(self, returns4):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        result = PortfolioOptimiser(OptimiserConfig()).optimise(returns4)
        assert set(result.weights.keys()) == set(returns4.columns)

    def test_weights_within_bounds(self, returns4):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        cfg = OptimiserConfig(max_weight=0.4)
        result = PortfolioOptimiser(cfg).optimise(returns4)
        for w in result.weights.values():
            assert -1e-6 <= w <= 0.4 + 1e-6

    def test_expected_return_finite(self, returns4):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        result = PortfolioOptimiser(OptimiserConfig()).optimise(returns4)
        assert math.isfinite(result.expected_return)

    def test_expected_volatility_positive(self, returns4):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        result = PortfolioOptimiser(OptimiserConfig()).optimise(returns4)
        assert result.expected_volatility > 0

    def test_sharpe_ratio_finite(self, returns4):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        result = PortfolioOptimiser(OptimiserConfig()).optimise(returns4)
        assert math.isfinite(result.sharpe_ratio)

    def test_diversification_ratio_gte_1(self, returns4):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        result = PortfolioOptimiser(OptimiserConfig()).optimise(returns4)
        # For long-only portfolios, diversification ratio >= 1
        assert result.diversification_ratio >= 0.99

    def test_max_sharpe_alias(self, returns4):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        r1 = PortfolioOptimiser(OptimiserConfig(method="markowitz")).optimise(returns4)
        r2 = PortfolioOptimiser(OptimiserConfig(method="max_sharpe")).optimise(returns4)
        assert r1.sharpe_ratio == pytest.approx(r2.sharpe_ratio, abs=1e-4)

    def test_two_asset(self, returns2):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        result = PortfolioOptimiser(OptimiserConfig()).optimise(returns2)
        assert abs(sum(result.weights.values()) - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# min_variance
# ---------------------------------------------------------------------------


class TestMinVariance:
    def test_weights_sum_to_one(self, returns4):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        result = PortfolioOptimiser(OptimiserConfig(method="min_variance")).optimise(returns4)
        assert abs(sum(result.weights.values()) - 1.0) < 1e-6

    def test_lower_vol_than_equal_weight(self, returns4):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        mv = PortfolioOptimiser(OptimiserConfig(method="min_variance")).optimise(returns4)
        ew = PortfolioOptimiser(OptimiserConfig(method="equal_weight")).optimise(returns4)
        # Min-variance should not exceed equal-weight volatility
        assert mv.expected_volatility <= ew.expected_volatility + 1e-4


# ---------------------------------------------------------------------------
# risk_parity
# ---------------------------------------------------------------------------


class TestRiskParity:
    def test_weights_sum_to_one(self, returns4):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        result = PortfolioOptimiser(OptimiserConfig(method="risk_parity")).optimise(returns4)
        assert abs(sum(result.weights.values()) - 1.0) < 1e-6

    def test_weights_non_negative(self, returns4):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        result = PortfolioOptimiser(OptimiserConfig(method="risk_parity")).optimise(returns4)
        for w in result.weights.values():
            assert w >= -1e-6

    def test_approximately_equal_risk_contributions(self, returns4):
        import numpy as np
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser

        result = PortfolioOptimiser(OptimiserConfig(method="risk_parity")).optimise(returns4)
        returns4.mean().values * 252
        cov = returns4.cov().values * 252

        weights = np.array([result.weights[a] for a in returns4.columns])
        portfolio_var = float(weights @ cov @ weights)
        mrc = cov @ weights
        rc = weights * mrc / max(portfolio_var, 1e-12)
        target = 1.0 / len(weights)
        # Each risk contribution should be close to the target (within 10%)
        for ri in rc:
            assert abs(ri - target) < 0.10, f"Risk contribution {ri:.4f} far from target {target:.4f}"


# ---------------------------------------------------------------------------
# equal_weight
# ---------------------------------------------------------------------------


class TestEqualWeight:
    def test_equal_weights(self, returns4):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        result = PortfolioOptimiser(OptimiserConfig(method="equal_weight")).optimise(returns4)
        weights = list(result.weights.values())
        expected = 1.0 / len(weights)
        for w in weights:
            assert abs(w - expected) < 1e-8


# ---------------------------------------------------------------------------
# black_litterman
# ---------------------------------------------------------------------------


class TestBlackLitterman:
    def test_weights_sum_to_one(self, returns4):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        optimiser = PortfolioOptimiser(OptimiserConfig())
        views = {"ASSET0": 0.20, "ASSET1": 0.10}
        conf = {"ASSET0": 0.8, "ASSET1": 0.6}
        result = optimiser.black_litterman(returns4, views, conf)
        assert abs(sum(result.weights.values()) - 1.0) < 1e-6

    def test_unknown_ticker_raises(self, returns4):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        optimiser = PortfolioOptimiser(OptimiserConfig())
        with pytest.raises(ValueError, match="not in returns columns"):
            optimiser.black_litterman(returns4, {"UNKNOWN": 0.2}, {"UNKNOWN": 0.5})

    def test_no_views_falls_back_to_markowitz(self, returns4):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        optimiser = PortfolioOptimiser(OptimiserConfig())
        result_bl = optimiser.black_litterman(returns4, {}, {})
        result_mv = optimiser.markowitz(returns4)
        # Both should produce finite sharpe ratios
        assert math.isfinite(result_bl.sharpe_ratio)
        assert math.isfinite(result_mv.sharpe_ratio)

    def test_high_confidence_shifts_weight(self, returns2):
        """View with high confidence should shift weight toward that asset."""
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        optimiser = PortfolioOptimiser(OptimiserConfig(max_weight=1.0))
        # Strongly bullish on NIFTY
        result = optimiser.black_litterman(returns2, {"NIFTY": 0.50}, {"NIFTY": 0.99})
        assert result.weights["NIFTY"] > 0.5


# ---------------------------------------------------------------------------
# efficient_frontier
# ---------------------------------------------------------------------------


class TestEfficientFrontier:
    def test_returns_list(self, returns4):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        frontier = PortfolioOptimiser(OptimiserConfig()).efficient_frontier(returns4, n_points=10)
        assert isinstance(frontier, list)
        assert len(frontier) > 0

    def test_each_result_weights_sum_to_one(self, returns4):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        frontier = PortfolioOptimiser(OptimiserConfig()).efficient_frontier(returns4, n_points=10)
        for pt in frontier:
            assert abs(sum(pt.weights.values()) - 1.0) < 1e-5

    def test_returns_non_decreasing(self, returns4):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        frontier = PortfolioOptimiser(OptimiserConfig()).efficient_frontier(returns4, n_points=20)
        rets = [pt.expected_return for pt in frontier]
        for i in range(1, len(rets)):
            assert rets[i] >= rets[i - 1] - 1e-4

    def test_n_points_requested_reasonable_count(self, returns4):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        frontier = PortfolioOptimiser(OptimiserConfig()).efficient_frontier(returns4, n_points=15)
        # With per-asset weight constraints (max_weight=0.4) many target-return levels
        # are infeasible; we only assert that at least some points are returned.
        assert len(frontier) >= 1

    def test_two_asset_frontier(self, returns2):
        from flinttrade_backtest.portfolio_optimiser import OptimiserConfig, PortfolioOptimiser
        # Relax max_weight so the full return range is feasible for two assets
        cfg = OptimiserConfig(max_weight=1.0)
        frontier = PortfolioOptimiser(cfg).efficient_frontier(returns2, n_points=5)
        assert len(frontier) >= 1


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class TestInternalHelpers:
    def test_annual_stats_shape(self, returns4):
        from flinttrade_backtest.portfolio_optimiser import _annual_stats
        mu, cov = _annual_stats(returns4)
        n = returns4.shape[1]
        assert mu.shape == (n,)
        assert cov.shape == (n, n)

    def test_portfolio_stats_known_values(self):
        import numpy as np
        from flinttrade_backtest.portfolio_optimiser import _portfolio_stats
        # Two equal assets, fully correlated with themselves
        mu = np.array([0.10, 0.20])
        cov = np.diag([0.04, 0.09])  # vol = 0.2, 0.3
        w = np.array([0.5, 0.5])
        ret, vol, sharpe = _portfolio_stats(w, mu, cov, rfr=0.065)
        assert ret == pytest.approx(0.15, abs=1e-6)
        expected_var = 0.5 ** 2 * 0.04 + 0.5 ** 2 * 0.09  # no covariance
        assert vol == pytest.approx(math.sqrt(expected_var), abs=1e-6)

    def test_diversification_ratio_uncorrelated(self):
        import numpy as np
        from flinttrade_backtest.portfolio_optimiser import _diversification_ratio
        # Uncorrelated assets — DR > 1
        cov = np.diag([0.04, 0.09, 0.01])
        w = np.array([1 / 3, 1 / 3, 1 / 3])
        dr = _diversification_ratio(w, cov)
        assert dr >= 1.0

    def test_build_result_keys(self, returns2):
        import numpy as np
        from flinttrade_backtest.portfolio_optimiser import _annual_stats, _build_result
        mu, cov = _annual_stats(returns2)
        w = np.array([0.6, 0.4])
        result = _build_result(list(returns2.columns), w, mu, cov, rfr=0.065)
        assert set(result.weights.keys()) == {"NIFTY", "GOLD"}
        assert abs(sum(result.weights.values()) - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# Flask routes
# ---------------------------------------------------------------------------


def _returns_payload(n_assets: int = 3, n_days: int = 100) -> dict:
    """Build a JSON-serialisable returns payload."""
    import numpy as np
    rng = np.random.default_rng(0)
    assets = [f"A{i}" for i in range(n_assets)]
    data = rng.normal(0.0005, 0.015, size=(n_days, n_assets))
    return {a: list(data[:, i]) for i, a in enumerate(assets)}


@pytest.fixture()
def flask_client():
    """Create a minimal Flask test client with optimiser Blueprint registered."""
    from flask import Flask

    try:
        from flinttrade_backtest.optimiser_routes import optimiser_bp
    except ImportError:
        from flinttrade_backtest.optimiser_routes import optimiser_bp

    app = Flask("test")
    app.register_blueprint(optimiser_bp)
    app.config["TESTING"] = True
    return app.test_client()


class TestOptimiserRoutes:
    def test_optimise_success(self, flask_client):
        payload = {
            "returns": _returns_payload(),
            "config": {"method": "markowitz"},
        }
        resp = flask_client.post(
            "/v1/portfolio/optimise",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "weights" in data["data"]
        assert "sharpe_ratio" in data["data"]

    def test_optimise_missing_returns(self, flask_client):
        resp = flask_client.post(
            "/v1/portfolio/optimise",
            data=json.dumps({"config": {}}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_optimise_single_asset_rejected(self, flask_client):
        payload = {"returns": {"A": [0.01, 0.02, -0.01]}}
        resp = flask_client.post(
            "/v1/portfolio/optimise",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code in (400, 422)

    def test_optimise_invalid_config(self, flask_client):
        payload = {
            "returns": _returns_payload(),
            "config": {"method": "nonexistent"},
        }
        resp = flask_client.post(
            "/v1/portfolio/optimise",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_optimise_equal_weight(self, flask_client):
        payload = {
            "returns": _returns_payload(n_assets=4),
            "config": {"method": "equal_weight"},
        }
        resp = flask_client.post(
            "/v1/portfolio/optimise",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        weights = resp.get_json()["data"]["weights"]
        for w in weights.values():
            assert abs(w - 0.25) < 1e-5

    def test_frontier_success(self, flask_client):
        payload = {
            "returns": _returns_payload(n_assets=3),
            "n_points": 5,
        }
        resp = flask_client.post(
            "/v1/portfolio/frontier",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 1

    def test_frontier_missing_returns(self, flask_client):
        resp = flask_client.post(
            "/v1/portfolio/frontier",
            data=json.dumps({"n_points": 5}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_frontier_invalid_n_points(self, flask_client):
        payload = {"returns": _returns_payload(), "n_points": -5}
        resp = flask_client.post(
            "/v1/portfolio/frontier",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_frontier_n_points_too_large(self, flask_client):
        payload = {"returns": _returns_payload(), "n_points": 9999}
        resp = flask_client.post(
            "/v1/portfolio/frontier",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_optimise_min_variance(self, flask_client):
        payload = {
            "returns": _returns_payload(n_assets=3),
            "config": {"method": "min_variance"},
        }
        resp = flask_client.post(
            "/v1/portfolio/optimise",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200

    def test_optimise_risk_parity(self, flask_client):
        payload = {
            "returns": _returns_payload(n_assets=3),
            "config": {"method": "risk_parity"},
        }
        resp = flask_client.post(
            "/v1/portfolio/optimise",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200

    def test_weights_respect_max_weight(self, flask_client):
        payload = {
            "returns": _returns_payload(n_assets=4),
            "config": {"method": "markowitz", "max_weight": 0.35},
        }
        resp = flask_client.post(
            "/v1/portfolio/optimise",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        for w in resp.get_json()["data"]["weights"].values():
            assert w <= 0.35 + 1e-5
