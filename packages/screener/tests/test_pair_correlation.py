"""Tests for the pair correlation and spread divergence engine.

All tests are self-contained — no API calls, no broker connection required.
Uses pytest with --import-mode=importlib.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from packages.screener.src.pair_correlation import (
    PairCorrelationEngine,
    PairSignal,
    _CONVERGE_THRESHOLD,
    _DIVERGE_THRESHOLD,
    _MIN_OBSERVATIONS,
    make_sample_pair_data,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> PairCorrelationEngine:
    return PairCorrelationEngine()


@pytest.fixture
def correlated_pair() -> dict:
    """Two highly correlated instruments sharing a common market factor."""
    rng = np.random.default_rng(42)
    base = rng.standard_normal(100) * 0.01
    noise = rng.standard_normal(100) * 0.002
    returns_a = list(base)
    returns_b = list(base + noise)

    # Build prices from cumulative returns
    prices_a = [1000.0]
    prices_b = [900.0]
    for ra, rb in zip(returns_a[1:], returns_b[1:]):
        prices_a.append(prices_a[-1] * (1.0 + ra))
        prices_b.append(prices_b[-1] * (1.0 + rb))

    return {
        "returns_a": returns_a,
        "returns_b": returns_b,
        "prices_a": prices_a,
        "prices_b": prices_b,
    }


@pytest.fixture
def anti_correlated_pair() -> dict:
    """Two negatively correlated instruments."""
    rng = np.random.default_rng(7)
    base = rng.standard_normal(100) * 0.01
    noise = rng.standard_normal(100) * 0.002
    returns_a = list(base)
    returns_b = list(-base + noise)

    prices_a = [1000.0]
    prices_b = [500.0]
    for ra, rb in zip(returns_a[1:], returns_b[1:]):
        prices_a.append(prices_a[-1] * (1.0 + ra))
        prices_b.append(prices_b[-1] * (1.0 + rb))

    return {
        "returns_a": returns_a,
        "returns_b": returns_b,
        "prices_a": prices_a,
        "prices_b": prices_b,
    }


@pytest.fixture
def short_pair() -> dict:
    """Pair with fewer than _MIN_OBSERVATIONS bars."""
    n = _MIN_OBSERVATIONS - 1
    return {
        "returns_a": [0.01] * n,
        "returns_b": [0.01] * n,
        "prices_a": [1000.0] * n,
        "prices_b": [900.0] * n,
    }


# ---------------------------------------------------------------------------
# PairSignal model
# ---------------------------------------------------------------------------


class TestPairSignalModel:
    def test_valid_signal_instantiation(self):
        sig = PairSignal(
            pair=("TCS", "INFY"),
            correlation=0.85,
            current_spread=2100.0,
            mean_spread=2050.0,
            std_spread=100.0,
            z_score=0.5,
            signal="neutral",
        )
        assert sig.pair == ("TCS", "INFY")
        assert sig.correlation == 0.85

    def test_correlation_bounds_enforced(self):
        with pytest.raises(Exception):
            PairSignal(
                pair=("A", "B"),
                correlation=1.5,   # out of bounds
                current_spread=0.0,
                mean_spread=0.0,
                std_spread=0.0,
                z_score=0.0,
                signal="neutral",
            )

    def test_std_spread_non_negative_enforced(self):
        with pytest.raises(Exception):
            PairSignal(
                pair=("A", "B"),
                correlation=0.5,
                current_spread=0.0,
                mean_spread=0.0,
                std_spread=-1.0,  # invalid
                z_score=0.0,
                signal="neutral",
            )


# ---------------------------------------------------------------------------
# analyse_pair — return type and field types
# ---------------------------------------------------------------------------


class TestAnalysePairReturnType:
    def test_returns_pair_signal(self, engine, correlated_pair):
        sig = engine.analyse_pair(**correlated_pair)
        assert isinstance(sig, PairSignal)

    def test_pair_label_set_correctly(self, engine, correlated_pair):
        sig = engine.analyse_pair(**correlated_pair, pair=("TCS", "INFY"))
        assert sig.pair == ("TCS", "INFY")

    def test_correlation_is_float(self, engine, correlated_pair):
        sig = engine.analyse_pair(**correlated_pair)
        assert isinstance(sig.correlation, float)

    def test_signal_is_valid_string(self, engine, correlated_pair):
        sig = engine.analyse_pair(**correlated_pair)
        assert sig.signal in ("converging", "diverging", "neutral")

    def test_z_score_is_finite_or_zero(self, engine, correlated_pair):
        sig = engine.analyse_pair(**correlated_pair)
        assert math.isfinite(sig.z_score)


# ---------------------------------------------------------------------------
# Correlation values
# ---------------------------------------------------------------------------


class TestCorrelationValues:
    def test_high_positive_correlation(self, engine, correlated_pair):
        sig = engine.analyse_pair(**correlated_pair)
        assert sig.correlation > 0.9

    def test_negative_correlation(self, engine, anti_correlated_pair):
        sig = engine.analyse_pair(**anti_correlated_pair)
        assert sig.correlation < -0.8

    def test_correlation_rounded_to_4dp(self, engine, correlated_pair):
        sig = engine.analyse_pair(**correlated_pair)
        assert sig.correlation == round(sig.correlation, 4)

    def test_correlation_within_bounds(self, engine, correlated_pair):
        sig = engine.analyse_pair(**correlated_pair)
        assert -1.0 <= sig.correlation <= 1.0


# ---------------------------------------------------------------------------
# Spread statistics
# ---------------------------------------------------------------------------


class TestSpreadStatistics:
    def test_current_spread_correct(self, engine, correlated_pair):
        pa = correlated_pair["prices_a"]
        pb = correlated_pair["prices_b"]
        sig = engine.analyse_pair(**correlated_pair)
        expected = round(pa[-1] - pb[-1], 4)
        assert sig.current_spread == pytest.approx(expected, rel=1e-4)

    def test_std_spread_non_negative(self, engine, correlated_pair):
        sig = engine.analyse_pair(**correlated_pair)
        assert sig.std_spread >= 0.0

    def test_mean_spread_finite(self, engine, correlated_pair):
        sig = engine.analyse_pair(**correlated_pair)
        assert math.isfinite(sig.mean_spread)

    def test_identical_prices_give_z_zero(self, engine):
        n = 50
        prices = [1000.0] * n
        returns = [0.0] * n
        sig = engine.analyse_pair(
            returns_a=returns,
            returns_b=returns,
            prices_a=prices,
            prices_b=prices,
        )
        assert sig.z_score == 0.0
        assert sig.std_spread == pytest.approx(0.0, abs=1e-8)


# ---------------------------------------------------------------------------
# Signal classification
# ---------------------------------------------------------------------------


class TestSignalClassification:
    def test_high_positive_z_is_diverging(self, engine):
        """Force high positive z-score — should be diverging."""
        rng = np.random.default_rng(10)
        n = 60
        base_p = 1000.0 + rng.standard_normal(n) * 5   # narrow spread historically
        b = [base_p[i] - 10.0 for i in range(n)]

        # Set last price much higher to push z above 1.5
        prices_a = list(base_p)
        prices_b = list(b)
        prices_a[-1] = base_p[-1] + 200.0   # large positive spread

        returns_a = [0.0] + [float((prices_a[i] - prices_a[i - 1]) / prices_a[i - 1])
                             for i in range(1, n)]
        returns_b = [0.0] + [float((prices_b[i] - prices_b[i - 1]) / prices_b[i - 1])
                             for i in range(1, n)]

        sig = engine.analyse_pair(
            returns_a=returns_a,
            returns_b=returns_b,
            prices_a=prices_a,
            prices_b=prices_b,
        )
        assert sig.signal == "diverging"
        assert abs(sig.z_score) > _DIVERGE_THRESHOLD

    def test_low_z_is_converging(self, engine):
        """Force z near zero — should be converging."""
        n = 60
        prices = [1000.0 + i * 0.1 for i in range(n)]  # smooth, constant spread
        prices_b = [p - 100.0 for p in prices]
        returns = [0.0] + [(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, n)]

        sig = engine.analyse_pair(
            returns_a=returns,
            returns_b=returns,
            prices_a=prices,
            prices_b=prices_b,
        )
        assert sig.signal == "converging"
        assert abs(sig.z_score) < _CONVERGE_THRESHOLD

    def test_classify_signal_boundaries(self, engine):
        assert engine._classify_signal(0.0) == "converging"
        assert engine._classify_signal(0.49) == "converging"
        assert engine._classify_signal(0.51) == "neutral"
        assert engine._classify_signal(1.49) == "neutral"
        assert engine._classify_signal(1.51) == "diverging"
        assert engine._classify_signal(-1.51) == "diverging"
        assert engine._classify_signal(-0.49) == "converging"


# ---------------------------------------------------------------------------
# Insufficient data
# ---------------------------------------------------------------------------


class TestInsufficientData:
    def test_short_series_returns_neutral(self, engine, short_pair):
        sig = engine.analyse_pair(**short_pair)
        assert sig.signal == "neutral"
        assert sig.z_score == 0.0
        assert sig.correlation == 0.0

    def test_empty_series_returns_neutral(self, engine):
        sig = engine.analyse_pair(
            returns_a=[],
            returns_b=[],
            prices_a=[],
            prices_b=[],
        )
        assert sig.signal == "neutral"


# ---------------------------------------------------------------------------
# analyse_all_presets
# ---------------------------------------------------------------------------


class TestAnalyseAllPresets:
    def test_returns_list_of_pair_signals(self, engine):
        data = make_sample_pair_data()
        results = engine.analyse_all_presets(data)
        assert isinstance(results, list)
        assert all(isinstance(s, PairSignal) for s in results)

    def test_all_preset_pairs_present(self, engine):
        data = make_sample_pair_data()
        results = engine.analyse_all_presets(data)
        result_pairs = [s.pair for s in results]
        for preset in PairCorrelationEngine.PRESET_PAIRS:
            assert preset in result_pairs

    def test_missing_symbol_skipped_gracefully(self, engine):
        # Provide only two of the five preset symbols
        data = make_sample_pair_data()
        partial_data = {k: v for k, v in data.items() if k in ("TCS", "INFY")}
        results = engine.analyse_all_presets(partial_data)
        # Only TCS/INFY pair should be returned
        assert len(results) == 1
        assert results[0].pair == ("TCS", "INFY")

    def test_empty_data_returns_empty_list(self, engine):
        results = engine.analyse_all_presets({})
        assert results == []

    def test_all_correlations_in_valid_range(self, engine):
        data = make_sample_pair_data()
        results = engine.analyse_all_presets(data)
        for sig in results:
            assert -1.0 <= sig.correlation <= 1.0

    def test_all_signals_valid_values(self, engine):
        data = make_sample_pair_data()
        results = engine.analyse_all_presets(data)
        valid_signals = {"converging", "diverging", "neutral"}
        for sig in results:
            assert sig.signal in valid_signals

    def test_std_spread_non_negative(self, engine):
        data = make_sample_pair_data()
        results = engine.analyse_all_presets(data)
        for sig in results:
            assert sig.std_spread >= 0.0


# ---------------------------------------------------------------------------
# make_sample_pair_data
# ---------------------------------------------------------------------------


class TestMakeSamplePairData:
    def test_returns_all_required_symbols(self):
        data = make_sample_pair_data()
        for pair in PairCorrelationEngine.PRESET_PAIRS:
            for sym in pair:
                assert sym in data, f"Symbol {sym} missing from sample data"

    def test_each_symbol_has_returns_and_prices(self):
        data = make_sample_pair_data()
        for sym, entry in data.items():
            assert "returns" in entry
            assert "prices" in entry

    def test_returns_and_prices_correct_length(self):
        n = 80
        data = make_sample_pair_data(n=n)
        for sym, entry in data.items():
            assert len(entry["returns"]) == n, f"{sym} returns length mismatch"
            assert len(entry["prices"]) == n, f"{sym} prices length mismatch"

    def test_deterministic_with_same_seed(self):
        d1 = make_sample_pair_data(seed=0)
        d2 = make_sample_pair_data(seed=0)
        assert d1["TCS"]["returns"] == d2["TCS"]["returns"]

    def test_different_seeds_differ(self):
        d1 = make_sample_pair_data(seed=1)
        d2 = make_sample_pair_data(seed=2)
        assert d1["TCS"]["returns"] != d2["TCS"]["returns"]

    def test_prices_all_positive(self):
        data = make_sample_pair_data()
        for sym, entry in data.items():
            for p in entry["prices"]:
                assert p > 0.0, f"{sym} has non-positive price: {p}"

    def test_all_returns_finite(self):
        data = make_sample_pair_data()
        for sym, entry in data.items():
            for r in entry["returns"]:
                assert math.isfinite(r), f"{sym} has non-finite return: {r}"
