"""Tests for portfolio_optimizer.py (pure-NumPy version).

Coverage:
- All four optimisation methods: mean_variance, risk_parity,
  max_diversification, equal_volatility
- unified optimize() entry point
- PortfolioResult schema
- Input validation (empty, single-asset, NaN-only, dict input)
- Numerical correctness (weights sum to 1, bounds, ERC property)
- Edge cases (singular covariance, zero-vol asset, target_return)
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_returns(
    n_assets: int = 4,
    n_days: int = 252,
    seed: int = 42,
) -> pd.DataFrame:
    """Synthetic daily-returns DataFrame with controllable volatility."""
    rng = np.random.default_rng(seed)
    assets = [f"ASSET{i}" for i in range(n_assets)]
    # Different vols per asset so optimisers have something to differentiate
    vols = np.array([0.020, 0.015, 0.025, 0.012])[:n_assets]
    mus  = np.array([0.0008, 0.0005, 0.0010, 0.0003])[:n_assets]
    data = rng.normal(loc=mus, scale=vols, size=(n_days, n_assets))
    return pd.DataFrame(data, columns=assets)


def _two_asset() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    data = rng.normal([0.0008, 0.0003], [0.02, 0.01], size=(200, 2))
    return pd.DataFrame(data, columns=["NIFTY", "GOLD"])


@pytest.fixture()
def returns4() -> pd.DataFrame:
    return _make_returns()


@pytest.fixture()
def returns2() -> pd.DataFrame:
    return _two_asset()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _weights_sum(result) -> float:
    return sum(result.weights.values())


def _import_mod():
    try:
        import flinttrade_backtest.portfolio_optimizer as m
    except ImportError:
        from flinttrade_backtest import portfolio_optimizer as m
    return m


# ---------------------------------------------------------------------------
# PortfolioResult schema
# ---------------------------------------------------------------------------


class TestPortfolioResult:
    def test_fields_present(self):
        m = _import_mod()
        r = m.PortfolioResult(
            weights={"A": 0.6, "B": 0.4},
            expected_return=0.12,
            expected_volatility=0.18,
            sharpe_ratio=0.30,
            diversification_ratio=1.05,
        )
        assert r.weights["A"] == pytest.approx(0.6)
        assert r.expected_return == pytest.approx(0.12)
        assert r.expected_volatility == pytest.approx(0.18)
        assert r.diversification_ratio == pytest.approx(1.05)

    def test_model_dump_has_all_keys(self):
        m = _import_mod()
        r = m.PortfolioResult(
            weights={"X": 1.0},
            expected_return=0.1,
            expected_volatility=0.2,
            sharpe_ratio=0.17,
            diversification_ratio=1.0,
        )
        d = r.model_dump()
        expected_keys = {"weights", "expected_return", "expected_volatility",
                         "sharpe_ratio", "diversification_ratio"}
        assert expected_keys.issubset(d.keys())


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_empty_dataframe_raises(self):
        m = _import_mod()
        with pytest.raises(ValueError, match="empty"):
            m.optimize(pd.DataFrame())

    def test_single_asset_raises(self):
        m = _import_mod()
        with pytest.raises(ValueError):
            m.optimize(pd.DataFrame({"NIFTY": [0.01, 0.02, -0.01]}))

    def test_all_nan_raises(self):
        m = _import_mod()
        df = pd.DataFrame({
            "A": [float("nan")] * 10,
            "B": [float("nan")] * 10,
        })
        with pytest.raises(ValueError, match="NaN"):
            m.optimize(df)

    def test_unknown_method_raises(self, returns2):
        m = _import_mod()
        with pytest.raises(ValueError, match="Unknown method"):
            m.optimize(returns2, method="magic")

    def test_dict_input_accepted(self):
        m = _import_mod()
        rng = np.random.default_rng(1)
        data = {
            "A": rng.normal(0.001, 0.02, 100).tolist(),
            "B": rng.normal(0.0005, 0.01, 100).tolist(),
        }
        result = m.optimize(data, method="equal_volatility")
        assert abs(_weights_sum(result) - 1.0) < 1e-6

    def test_wrong_type_raises(self):
        m = _import_mod()
        with pytest.raises(TypeError):
            m._to_dataframe([1, 2, 3])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# mean_variance
# ---------------------------------------------------------------------------


class TestMeanVariance:
    def test_weights_sum_to_one(self, returns4):
        m = _import_mod()
        result = m.optimize(returns4, method="mean_variance")
        assert abs(_weights_sum(result) - 1.0) < 1e-6

    def test_all_assets_in_weights(self, returns4):
        m = _import_mod()
        result = m.optimize(returns4, method="mean_variance")
        assert set(result.weights.keys()) == set(returns4.columns)

    def test_non_negative_weights(self, returns4):
        m = _import_mod()
        result = m.optimize(returns4, method="mean_variance")
        for w in result.weights.values():
            assert w >= -1e-8

    def test_expected_return_finite(self, returns4):
        m = _import_mod()
        result = m.optimize(returns4, method="mean_variance")
        assert math.isfinite(result.expected_return)

    def test_volatility_positive(self, returns4):
        m = _import_mod()
        result = m.optimize(returns4, method="mean_variance")
        assert result.expected_volatility > 0

    def test_sharpe_finite(self, returns4):
        m = _import_mod()
        result = m.optimize(returns4, method="mean_variance")
        assert math.isfinite(result.sharpe_ratio)

    def test_diversification_ratio_gte_1(self, returns4):
        m = _import_mod()
        result = m.optimize(returns4, method="mean_variance")
        assert result.diversification_ratio >= 0.99

    def test_target_return_accepted(self, returns4):
        m = _import_mod()
        target = 0.08
        result = m.optimize(returns4, method="mean_variance", target_return=target)
        assert abs(_weights_sum(result) - 1.0) < 1e-6

    def test_target_return_respected_approx(self, returns4):
        """Analytical MV at target_return should hit ~target_return."""
        m = _import_mod()
        mu_daily = returns4.mean().to_numpy()
        mu_ann = mu_daily * 252
        # Choose a reachable target within the asset return range
        target = float(np.percentile(mu_ann, 50))
        raw = m.mean_variance(returns4, target_return=target)
        w = np.array([raw[a] for a in returns4.columns])
        achieved = float(w @ (returns4.mean().to_numpy() * 252))
        assert abs(achieved - target) < 0.05  # within 5% due to simplex projection

    def test_two_asset_weights_sum(self, returns2):
        m = _import_mod()
        result = m.optimize(returns2, method="mean_variance")
        assert abs(_weights_sum(result) - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# risk_parity
# ---------------------------------------------------------------------------


class TestRiskParity:
    def test_weights_sum_to_one(self, returns4):
        m = _import_mod()
        result = m.optimize(returns4, method="risk_parity")
        assert abs(_weights_sum(result) - 1.0) < 1e-6

    def test_non_negative_weights(self, returns4):
        m = _import_mod()
        result = m.optimize(returns4, method="risk_parity")
        for w in result.weights.values():
            assert w >= -1e-8

    def test_all_assets_present(self, returns4):
        m = _import_mod()
        result = m.optimize(returns4, method="risk_parity")
        assert set(result.weights.keys()) == set(returns4.columns)

    def test_approximately_equal_risk_contributions(self, returns4):
        m = _import_mod()
        result = m.optimize(returns4, method="risk_parity")
        cov = returns4.cov().to_numpy() * 252
        weights = np.array([result.weights[a] for a in returns4.columns])
        port_var = float(weights @ cov @ weights)
        mrc = cov @ weights
        rc = weights * mrc / max(port_var, 1e-12)
        target = 1.0 / len(weights)
        for ri in rc:
            assert abs(ri - target) < 0.15, (
                f"Risk contribution {ri:.4f} too far from target {target:.4f}"
            )

    def test_higher_vol_gets_lower_weight(self, returns4):
        """Asset with higher volatility should receive lower weight in ERC."""
        m = _import_mod()
        result = m.optimize(returns4, method="risk_parity")
        vols = returns4.std(ddof=1).to_numpy() * np.sqrt(252)
        weights = np.array([result.weights[a] for a in returns4.columns])
        # Higher-vol asset should not consistently outweigh lower-vol
        max_vol_idx = int(np.argmax(vols))
        min_vol_idx = int(np.argmin(vols))
        assert weights[max_vol_idx] <= weights[min_vol_idx] + 0.10

    def test_two_asset(self, returns2):
        m = _import_mod()
        result = m.optimize(returns2, method="risk_parity")
        assert abs(_weights_sum(result) - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# max_diversification
# ---------------------------------------------------------------------------


class TestMaxDiversification:
    def test_weights_sum_to_one(self, returns4):
        m = _import_mod()
        result = m.optimize(returns4, method="max_diversification")
        assert abs(_weights_sum(result) - 1.0) < 1e-6

    def test_non_negative_weights(self, returns4):
        m = _import_mod()
        result = m.optimize(returns4, method="max_diversification")
        for w in result.weights.values():
            assert w >= -1e-8

    def test_all_assets_present(self, returns4):
        m = _import_mod()
        result = m.optimize(returns4, method="max_diversification")
        assert set(result.weights.keys()) == set(returns4.columns)

    def test_dr_gte_equal_weight(self, returns4):
        """Max-DR portfolio should achieve higher DR than equal weight."""
        m = _import_mod()
        result_md = m.optimize(returns4, method="max_diversification")
        result_ew = m.optimize(returns4, method="equal_volatility")
        # This is a soft assertion — MD should be at least as diversified
        assert result_md.diversification_ratio >= result_ew.diversification_ratio - 0.05

    def test_diversification_ratio_gte_1(self, returns4):
        m = _import_mod()
        result = m.optimize(returns4, method="max_diversification")
        assert result.diversification_ratio >= 0.99

    def test_two_asset(self, returns2):
        m = _import_mod()
        result = m.optimize(returns2, method="max_diversification")
        assert abs(_weights_sum(result) - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# equal_volatility
# ---------------------------------------------------------------------------


class TestEqualVolatility:
    def test_weights_sum_to_one(self, returns4):
        m = _import_mod()
        result = m.optimize(returns4, method="equal_volatility")
        assert abs(_weights_sum(result) - 1.0) < 1e-6

    def test_non_negative_weights(self, returns4):
        m = _import_mod()
        result = m.optimize(returns4, method="equal_volatility")
        for w in result.weights.values():
            assert w >= -1e-8

    def test_all_assets_present(self, returns4):
        m = _import_mod()
        result = m.optimize(returns4, method="equal_volatility")
        assert set(result.weights.keys()) == set(returns4.columns)

    def test_lower_vol_gets_higher_weight(self, returns4):
        """Inverse-vol: lower-volatility asset should get more weight."""
        m = _import_mod()
        result = m.optimize(returns4, method="equal_volatility")
        vols = returns4.std(ddof=1).to_numpy() * np.sqrt(252)
        weights = np.array([result.weights[a] for a in returns4.columns])
        for i in range(len(vols)):
            for j in range(len(vols)):
                if vols[i] < vols[j] - 1e-6:
                    assert weights[i] > weights[j] - 1e-8

    def test_equal_vol_assets_equal_weight(self):
        """Assets with the same volatility should receive equal allocation."""
        m = _import_mod()
        rng = np.random.default_rng(99)
        # Identical vol for all 3 assets by construction
        data = rng.normal(0, 0.02, (300, 3))
        df = pd.DataFrame(data, columns=["A", "B", "C"])
        result = m.optimize(df, method="equal_volatility")
        for w in result.weights.values():
            assert abs(w - 1 / 3) < 0.05  # allow for sampling noise

    def test_two_asset(self, returns2):
        m = _import_mod()
        result = m.optimize(returns2, method="equal_volatility")
        assert abs(_weights_sum(result) - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# optimize() — unified entry point
# ---------------------------------------------------------------------------


class TestOptimize:
    @pytest.mark.parametrize("method", [
        "mean_variance", "risk_parity", "max_diversification", "equal_volatility",
    ])
    def test_all_methods_produce_valid_result(self, method, returns4):
        m = _import_mod()
        result = m.optimize(returns4, method=method)
        assert isinstance(result, m.PortfolioResult)
        assert abs(_weights_sum(result) - 1.0) < 1e-6
        assert math.isfinite(result.expected_return)
        assert math.isfinite(result.expected_volatility)
        assert math.isfinite(result.sharpe_ratio)
        assert result.diversification_ratio >= 0.0

    def test_default_method_is_risk_parity(self, returns4):
        m = _import_mod()
        result_default = m.optimize(returns4)
        result_rp = m.optimize(returns4, method="risk_parity")
        # Same method → identical weights
        for a in returns4.columns:
            assert result_default.weights[a] == pytest.approx(result_rp.weights[a], abs=1e-6)

    def test_custom_rfr_changes_sharpe(self, returns4):
        m = _import_mod()
        r1 = m.optimize(returns4, method="equal_volatility", rfr=0.065)
        r2 = m.optimize(returns4, method="equal_volatility", rfr=0.02)
        # Lower RFR should yield higher (or equal) Sharpe when returns are positive
        # (weights identical for equal_volatility so only numerator differs)
        assert r2.sharpe_ratio >= r1.sharpe_ratio - 1e-6


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_annual_stats_shape(self, returns4):
        m = _import_mod()
        mu, cov = m._annual_stats(returns4)
        n = returns4.shape[1]
        assert mu.shape == (n,)
        assert cov.shape == (n, n)

    def test_annual_stats_scale(self, returns4):
        """Annualised mean and cov should be ~252× the daily equivalents."""
        m = _import_mod()
        mu, cov = m._annual_stats(returns4)
        daily_mu = returns4.mean().to_numpy()
        assert np.allclose(mu, daily_mu * 252, rtol=1e-6)

    def test_portfolio_stats_known(self):
        m = _import_mod()
        mu = np.array([0.10, 0.20])
        cov = np.diag([0.04, 0.09])
        w = np.array([0.5, 0.5])
        ret, vol, sharpe = m._portfolio_stats(w, mu, cov, rfr=0.065)
        assert ret == pytest.approx(0.15, abs=1e-6)
        expected_var = 0.25 * 0.04 + 0.25 * 0.09
        assert vol == pytest.approx(math.sqrt(expected_var), abs=1e-6)
        assert sharpe == pytest.approx((0.15 - 0.065) / math.sqrt(expected_var), abs=1e-5)

    def test_diversification_ratio_uncorrelated(self):
        m = _import_mod()
        cov = np.diag([0.04, 0.09, 0.01])
        w = np.array([1 / 3, 1 / 3, 1 / 3])
        dr = m._diversification_ratio(w, cov)
        assert dr >= 1.0

    def test_normalise_sums_to_one(self):
        m = _import_mod()
        v = np.array([2.0, 3.0, 5.0])
        w = m._normalise(v)
        assert abs(w.sum() - 1.0) < 1e-12

    def test_normalise_zero_vector_returns_equal(self):
        m = _import_mod()
        v = np.array([0.0, 0.0, 0.0])
        w = m._normalise(v)
        assert np.allclose(w, [1 / 3, 1 / 3, 1 / 3])

    def test_build_result_keys(self, returns2):
        m = _import_mod()
        mu, cov = m._annual_stats(returns2)
        w = np.array([0.6, 0.4])
        result = m._build_result(list(returns2.columns), w, mu, cov)
        assert set(result.weights.keys()) == {"NIFTY", "GOLD"}
        assert abs(sum(result.weights.values()) - 1.0) < 1e-6
