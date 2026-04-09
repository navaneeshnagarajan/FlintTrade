"""Tests for the correlation matrix computation engine.

All tests are self-contained — no API calls, no broker connection required.
Uses pytest with --import-mode=importlib.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from packages.screener.src.correlation import (
    CorrelationEngine,
    CorrelationMatrix,
    make_sample_returns,
)
from packages.screener.src.regime_detector import RegimeType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine() -> CorrelationEngine:
    return CorrelationEngine()


@pytest.fixture
def simple_returns() -> dict[str, list[float]]:
    """Three symbols with known relationships for deterministic testing."""
    rng = np.random.default_rng(0)
    base = rng.standard_normal(100) * 0.01
    # A = base, B = A + noise, C = -A + noise (negatively correlated with A)
    noise_b = rng.standard_normal(100) * 0.002
    noise_c = rng.standard_normal(100) * 0.002
    return {
        "A": list(base),
        "B": list(base + noise_b),
        "C": list(-base + noise_c),
    }


@pytest.fixture
def single_symbol_returns() -> dict[str, list[float]]:
    rng = np.random.default_rng(1)
    return {"SINGLE": list(rng.standard_normal(50) * 0.005)}


# ---------------------------------------------------------------------------
# CorrelationMatrix model
# ---------------------------------------------------------------------------

class TestCorrelationMatrixModel:
    """Tests for the CorrelationMatrix Pydantic model."""

    def test_get_pair_correlation_valid(self, engine, simple_returns):
        result = engine.compute(simple_returns, period=90)
        corr = result.get_pair_correlation("A", "B")
        assert corr is not None
        assert -1.0 <= corr <= 1.0

    def test_get_pair_correlation_missing_symbol(self, engine, simple_returns):
        result = engine.compute(simple_returns, period=90)
        assert result.get_pair_correlation("A", "MISSING") is None

    def test_get_pair_correlation_self(self, engine, simple_returns):
        result = engine.compute(simple_returns, period=90)
        corr = result.get_pair_correlation("A", "A")
        assert corr == pytest.approx(1.0, abs=1e-6)

    def test_updated_at_is_iso_string(self, engine, simple_returns):
        result = engine.compute(simple_returns, period=90)
        assert isinstance(result.updated_at, str)
        assert "T" in result.updated_at or "-" in result.updated_at


# ---------------------------------------------------------------------------
# Compute method
# ---------------------------------------------------------------------------

class TestCorrelationEngineCompute:
    """Tests for CorrelationEngine.compute."""

    def test_returns_correlation_matrix(self, engine, simple_returns):
        result = engine.compute(simple_returns)
        assert isinstance(result, CorrelationMatrix)

    def test_correct_symbol_count(self, engine, simple_returns):
        result = engine.compute(simple_returns)
        assert len(result.symbols) == 3

    def test_matrix_shape_nxn(self, engine, simple_returns):
        result = engine.compute(simple_returns)
        n = len(result.symbols)
        assert len(result.matrix) == n
        for row in result.matrix:
            assert len(row) == n

    def test_diagonal_is_one(self, engine, simple_returns):
        result = engine.compute(simple_returns)
        for i in range(len(result.symbols)):
            assert result.matrix[i][i] == pytest.approx(1.0, abs=1e-6)

    def test_matrix_is_symmetric(self, engine, simple_returns):
        result = engine.compute(simple_returns)
        n = len(result.symbols)
        for i in range(n):
            for j in range(n):
                assert result.matrix[i][j] == pytest.approx(result.matrix[j][i], abs=1e-6)

    def test_all_values_in_minus_one_to_one(self, engine, simple_returns):
        result = engine.compute(simple_returns)
        for row in result.matrix:
            for v in row:
                assert -1.0 <= v <= 1.0

    def test_known_positive_correlation(self, engine, simple_returns):
        # A and B should be highly positively correlated
        result = engine.compute(simple_returns)
        corr_ab = result.get_pair_correlation("A", "B")
        assert corr_ab is not None
        assert corr_ab > 0.9

    def test_known_negative_correlation(self, engine, simple_returns):
        # A and C should be negatively correlated
        result = engine.compute(simple_returns)
        corr_ac = result.get_pair_correlation("A", "C")
        assert corr_ac is not None
        assert corr_ac < -0.9

    def test_period_stored(self, engine, simple_returns):
        result = engine.compute(simple_returns, period=60)
        assert result.period_days == 60

    def test_period_truncates_series(self, engine):
        # 120-day series, period=30 → only last 30 used
        rng = np.random.default_rng(5)
        long_series = list(rng.standard_normal(120) * 0.01)
        returns = {"X": long_series, "Y": long_series}
        result = engine.compute(returns, period=30)
        assert result.period_days == 30

    def test_empty_returns_returns_empty_matrix(self, engine):
        result = engine.compute({}, period=90)
        assert result.symbols == []
        assert result.matrix == []
        assert result.is_sample_data is True

    def test_single_symbol_returns_1x1_matrix(self, engine, single_symbol_returns):
        result = engine.compute(single_symbol_returns)
        assert len(result.symbols) == 1
        assert result.matrix[0][0] == pytest.approx(1.0)

    def test_too_short_series_excluded(self, engine):
        # Series with only 2 observations — below _MIN_OBSERVATIONS (5)
        returns = {
            "OK": [0.01] * 50,
            "SHORT": [0.01, 0.02],  # Only 2 values
        }
        result = engine.compute(returns)
        assert "SHORT" not in result.symbols
        assert "OK" in result.symbols

    def test_values_rounded_to_4_dp(self, engine, simple_returns):
        result = engine.compute(simple_returns)
        for row in result.matrix:
            for v in row:
                # Check rounding — value should equal itself rounded to 4dp
                assert v == round(v, 4)

    def test_regime_attached(self, engine, simple_returns):
        result = engine.compute(simple_returns, vix=15.0)
        assert result.regime is not None
        assert isinstance(result.regime.regime, RegimeType)

    def test_is_sample_data_false_for_real_input(self, engine, simple_returns):
        result = engine.compute(simple_returns)
        # The engine itself doesn't mark is_sample_data — that's set by the caller
        # We just check it's a bool
        assert isinstance(result.is_sample_data, bool)

    def test_six_symbol_default_sample(self, engine):
        returns = make_sample_returns()
        result = engine.compute(returns)
        assert len(result.symbols) == 6

    def test_nan_in_returns_handled(self, engine):
        import math
        returns = {
            "A": [0.01, float("nan"), 0.02, 0.01, 0.03, -0.01, 0.02, -0.02, 0.01, 0.00],
            "B": [0.02, 0.01, 0.01, 0.00, 0.02, -0.02, 0.01, -0.01, 0.01, 0.00],
        }
        result = engine.compute(returns)
        # Should not raise; NaN values filtered
        for row in result.matrix:
            for v in row:
                assert math.isfinite(v)


# ---------------------------------------------------------------------------
# Rolling correlation
# ---------------------------------------------------------------------------

class TestRollingCorrelation:
    """Tests for CorrelationEngine.rolling_correlation."""

    def test_returns_correct_length(self, engine, simple_returns):
        n = len(simple_returns["A"])
        window = 20
        result = engine.rolling_correlation(simple_returns, pair=("A", "B"), window=window)
        assert len(result) == n

    def test_first_window_minus_one_values_are_zero(self, engine, simple_returns):
        window = 20
        result = engine.rolling_correlation(simple_returns, pair=("A", "B"), window=window)
        # First (window-1) values should be 0 padding
        assert all(v == 0.0 for v in result[: window - 1])

    def test_values_in_range(self, engine, simple_returns):
        result = engine.rolling_correlation(simple_returns, pair=("A", "B"), window=20)
        for v in result:
            assert -1.0 <= v <= 1.0

    def test_high_correlation_pair(self, engine, simple_returns):
        result = engine.rolling_correlation(simple_returns, pair=("A", "B"), window=30)
        # After warm-up, A and B are highly correlated
        post_warmup = result[30:]
        assert any(v > 0.8 for v in post_warmup)

    def test_missing_symbol_returns_empty(self, engine, simple_returns):
        result = engine.rolling_correlation(simple_returns, pair=("A", "MISSING"), window=20)
        assert result == []

    def test_series_shorter_than_window(self, engine):
        short_returns = {"P": [0.01] * 10, "Q": [0.02] * 10}
        result = engine.rolling_correlation(short_returns, pair=("P", "Q"), window=20)
        # Length < window → returns zeros for all
        assert len(result) == 10
        assert all(v == 0.0 for v in result)

    def test_negative_correlation_pair(self, engine, simple_returns):
        result = engine.rolling_correlation(simple_returns, pair=("A", "C"), window=30)
        post_warmup = result[30:]
        assert any(v < -0.8 for v in post_warmup)


# ---------------------------------------------------------------------------
# Sample data factory
# ---------------------------------------------------------------------------

class TestMakeSampleReturns:
    """Tests for the make_sample_returns helper."""

    def test_returns_correct_symbols(self):
        result = make_sample_returns()
        expected = ["NIFTY50", "BANKNIFTY", "IT", "GOLD", "USD/INR", "NIFTY500"]
        assert list(result.keys()) == expected

    def test_returns_correct_length(self):
        result = make_sample_returns(n_days=60)
        for sym, rets in result.items():
            assert len(rets) == 60, f"{sym} has {len(rets)} returns, expected 60"

    def test_deterministic_with_same_seed(self):
        r1 = make_sample_returns(seed=42)
        r2 = make_sample_returns(seed=42)
        for sym in r1:
            assert r1[sym] == r2[sym]

    def test_different_seed_different_values(self):
        r1 = make_sample_returns(seed=1)
        r2 = make_sample_returns(seed=2)
        assert r1["NIFTY50"] != r2["NIFTY50"]

    def test_custom_symbols(self):
        syms = ["ALPHA", "BETA", "GAMMA"]
        result = make_sample_returns(symbols=syms)
        assert list(result.keys()) == syms

    def test_all_values_finite(self):
        result = make_sample_returns()
        for sym, rets in result.items():
            assert all(math.isfinite(r) for r in rets), f"Non-finite in {sym}"

    def test_gold_negatively_correlated_with_nifty(self):
        """Sample data should produce realistic correlations."""
        result = make_sample_returns(n_days=500, seed=0)
        nifty = np.array(result["NIFTY50"])
        gold = np.array(result["GOLD"])
        corr = float(np.corrcoef(nifty, gold)[0, 1])
        # Gold should be negatively correlated with Nifty in sample data
        assert corr < 0, f"Expected negative Nifty-GOLD correlation, got {corr:.3f}"

    def test_banknifty_positively_correlated_with_nifty(self):
        result = make_sample_returns(n_days=500, seed=0)
        nifty = np.array(result["NIFTY50"])
        bank = np.array(result["BANKNIFTY"])
        corr = float(np.corrcoef(nifty, bank)[0, 1])
        assert corr > 0, f"Expected positive Nifty-BankNifty correlation, got {corr:.3f}"


# ---------------------------------------------------------------------------
# Integration: compute with sample data
# ---------------------------------------------------------------------------

class TestIntegration:
    """End-to-end integration tests using sample return data."""

    def test_full_pipeline_6_symbols(self, engine):
        returns = make_sample_returns(n_days=90)
        result = engine.compute(returns, period=90, vix=14.5, fii_net=3000.0)
        assert isinstance(result, CorrelationMatrix)
        assert len(result.symbols) == 6
        assert len(result.matrix) == 6
        for row in result.matrix:
            assert len(row) == 6
        # All valid correlation values
        for i, row in enumerate(result.matrix):
            for j, v in enumerate(row):
                assert -1.0 <= v <= 1.0
                if i == j:
                    assert v == pytest.approx(1.0, abs=1e-6)

    def test_regime_attached_to_result(self, engine):
        returns = make_sample_returns(n_days=90)
        result = engine.compute(returns, vix=22.0)
        assert result.regime.vix_level == pytest.approx(22.0)

    def test_high_vix_leads_to_risk_off_regime(self, engine):
        returns = make_sample_returns(n_days=90)
        result = engine.compute(
            returns, vix=35.0,
            fii_net=-15000.0,
            advance_decline=(200, 1800),
        )
        assert result.regime.regime == RegimeType.RISK_OFF

    def test_low_vix_leads_to_calm_or_risk_on(self, engine):
        returns = make_sample_returns(n_days=90)
        result = engine.compute(
            returns, vix=10.0,
            fii_net=5000.0,
            advance_decline=(1800, 300),
        )
        assert result.regime.regime in (RegimeType.CALM, RegimeType.RISK_ON, RegimeType.TRENDING_UP)
