"""Tests for Monte Carlo simulator.

Covers: basic run, determinism, edge cases, VaR/CVaR, drawdown distribution,
probability of loss, empty trades guard.
"""

from __future__ import annotations

import os
import sys

import pytest

# Fix import paths for hyphenated package name (backtest-engine can't be a Python identifier)
_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_test_dir, '..', 'src'))
sys.path.insert(0, os.path.join(_test_dir, '..', '..', '..'))
sys.path.insert(0, os.path.join(_test_dir, '..', '..', 'core', 'src'))
sys.path.insert(0, os.path.join(_test_dir, '..', '..', 'engine', 'src'))

from monte_carlo import (
    MonteCarloConfig,
    MonteCarloResult,
    MonteCarloSimulator,
    _max_drawdown,
    _percentile,
)


# ---------------------------------------------------------------------------
# _percentile helper
# ---------------------------------------------------------------------------


def test_percentile_empty() -> None:
    assert _percentile([], 50.0) == 0.0


def test_percentile_single() -> None:
    assert _percentile([42.0], 0.0) == 42.0
    assert _percentile([42.0], 50.0) == 42.0
    assert _percentile([42.0], 100.0) == 42.0


def test_percentile_sorted_list() -> None:
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert _percentile(vals, 0.0) == pytest.approx(1.0)
    assert _percentile(vals, 100.0) == pytest.approx(5.0)
    assert _percentile(vals, 50.0) == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# _max_drawdown helper
# ---------------------------------------------------------------------------


def test_max_drawdown_flat() -> None:
    path = [100.0, 100.0, 100.0]
    assert _max_drawdown(path) == pytest.approx(0.0)


def test_max_drawdown_declining() -> None:
    path = [100.0, 90.0, 80.0]
    # peak=100, low=80 → 20%
    assert _max_drawdown(path) == pytest.approx(20.0)


def test_max_drawdown_recovery() -> None:
    path = [100.0, 80.0, 120.0, 100.0]
    # After peak 120, falls to 100 → 16.67% drawdown
    # But earlier 100→80 is 20%
    assert _max_drawdown(path) == pytest.approx(20.0)


def test_max_drawdown_empty() -> None:
    assert _max_drawdown([]) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# MonteCarloSimulator — basic
# ---------------------------------------------------------------------------


def test_run_returns_result_type() -> None:
    trades = [500.0, -200.0, 300.0, -100.0, 800.0]
    sim = MonteCarloSimulator(trades, MonteCarloConfig(n_simulations=100))
    result = sim.run()
    assert isinstance(result, MonteCarloResult)


def test_run_n_simulations_stored() -> None:
    trades = [100.0, -50.0, 200.0]
    sim = MonteCarloSimulator(trades, MonteCarloConfig(n_simulations=250))
    result = sim.run()
    assert result.n_simulations == 250


def test_percentile_ordering() -> None:
    """p5 <= p25 <= p50 <= p75 <= p95."""
    trades = [200.0, -150.0, 400.0, -80.0, 100.0, -300.0, 500.0]
    sim = MonteCarloSimulator(trades, MonteCarloConfig(n_simulations=500, seed=1))
    r = sim.run()
    assert r.p5 <= r.p25
    assert r.p25 <= r.p50
    assert r.p50 <= r.p75
    assert r.p75 <= r.p95


def test_all_winning_trades_low_loss_probability() -> None:
    """All winning trades: probability of loss should be 0."""
    trades = [100.0, 200.0, 150.0, 50.0, 300.0]
    sim = MonteCarloSimulator(trades, MonteCarloConfig(n_simulations=200, seed=7))
    r = sim.run()
    # Sum of P&L is always +800 regardless of order → final always > initial
    assert r.probability_of_loss == pytest.approx(0.0)


def test_all_losing_trades_high_loss_probability() -> None:
    """All losing trades: every permutation ends below initial capital."""
    trades = [-100.0, -200.0, -150.0]
    sim = MonteCarloSimulator(trades, MonteCarloConfig(n_simulations=200, seed=3))
    r = sim.run()
    assert r.probability_of_loss == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_determinism_same_seed() -> None:
    trades = [300.0, -150.0, 100.0, -50.0, 200.0]
    cfg = MonteCarloConfig(n_simulations=500, seed=42)
    r1 = MonteCarloSimulator(trades, cfg).run()
    r2 = MonteCarloSimulator(trades, cfg).run()
    assert r1.p50 == pytest.approx(r2.p50)
    assert r1.probability_of_loss == pytest.approx(r2.probability_of_loss)
    assert r1.var_95 == pytest.approx(r2.var_95)


def test_different_seeds_produce_different_drawdowns() -> None:
    """Different seeds produce different path-dependent metrics (max drawdown).

    Note: final equity is always the same for all permutations (sum of P&L is
    invariant to ordering). However, max drawdown IS path-dependent and WILL
    differ between seeds.
    """
    trades = [300.0, -150.0, 100.0, -50.0, 200.0, -400.0, 600.0]
    r1 = MonteCarloSimulator(trades, MonteCarloConfig(n_simulations=500, seed=1)).run()
    r2 = MonteCarloSimulator(trades, MonteCarloConfig(n_simulations=500, seed=99)).run()
    # max_drawdown_p50 is path-dependent and differs between seeds
    assert r1.max_drawdown_p50 != r2.max_drawdown_p50


# ---------------------------------------------------------------------------
# VaR and CVaR
# ---------------------------------------------------------------------------


def test_var_non_negative() -> None:
    trades = [100.0, -500.0, 200.0, -300.0, 400.0]
    sim = MonteCarloSimulator(trades, MonteCarloConfig(n_simulations=300, seed=5))
    r = sim.run()
    assert r.var_95 >= 0.0
    assert r.cvar_95 >= 0.0


def test_cvar_gte_var() -> None:
    """CVaR (Expected Shortfall) should be >= VaR at same confidence."""
    trades = [100.0, -500.0, 200.0, -300.0, 150.0, -100.0]
    sim = MonteCarloSimulator(trades, MonteCarloConfig(n_simulations=500, seed=13))
    r = sim.run()
    assert r.cvar_95 >= r.var_95 - 0.01  # allow floating-point tolerance


def test_var_zero_when_all_wins() -> None:
    trades = [100.0, 200.0, 300.0]
    sim = MonteCarloSimulator(trades, MonteCarloConfig(n_simulations=200, seed=9))
    r = sim.run()
    assert r.var_95 == pytest.approx(0.0)
    assert r.cvar_95 == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Drawdown distribution
# ---------------------------------------------------------------------------


def test_drawdown_fields_non_negative() -> None:
    trades = [200.0, -300.0, 150.0, -100.0, 500.0]
    sim = MonteCarloSimulator(trades, MonteCarloConfig(n_simulations=200, seed=2))
    r = sim.run()
    assert r.max_drawdown_p50 >= 0.0
    assert r.max_drawdown_p95 >= 0.0


def test_drawdown_p95_gte_p50() -> None:
    trades = [100.0, -400.0, 200.0, -150.0, 300.0]
    sim = MonteCarloSimulator(trades, MonteCarloConfig(n_simulations=400, seed=17))
    r = sim.run()
    assert r.max_drawdown_p95 >= r.max_drawdown_p50 - 0.01


# ---------------------------------------------------------------------------
# as_dict
# ---------------------------------------------------------------------------


def test_as_dict_keys() -> None:
    trades = [100.0, -50.0, 200.0]
    sim = MonteCarloSimulator(trades, MonteCarloConfig(n_simulations=50, seed=0))
    d = sim.run().as_dict()
    expected_keys = {
        "p5", "p25", "p50", "p75", "p95",
        "mean_final", "std_final",
        "probability_of_loss", "var_95", "cvar_95",
        "max_drawdown_p50", "max_drawdown_p95", "n_simulations",
    }
    assert expected_keys == set(d.keys())


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_single_trade() -> None:
    """Single trade: every permutation is identical."""
    sim = MonteCarloSimulator([500.0], MonteCarloConfig(n_simulations=100, seed=1))
    r = sim.run()
    assert r.p5 == pytest.approx(100_500.0)
    assert r.p95 == pytest.approx(100_500.0)
    assert r.std_final == pytest.approx(0.0, abs=1e-6)


def test_empty_trades_raises() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        MonteCarloSimulator([])


def test_large_simulation_completes() -> None:
    """1000 simulations with 100 trades should complete quickly."""
    import time
    trades = [float(i % 10 - 5) * 100 for i in range(100)]
    start = time.monotonic()
    sim = MonteCarloSimulator(trades, MonteCarloConfig(n_simulations=1000, seed=42))
    sim.run()
    elapsed = time.monotonic() - start
    assert elapsed < 10.0, f"Simulation took {elapsed:.1f}s — too slow"


def test_config_defaults() -> None:
    cfg = MonteCarloConfig()
    assert cfg.n_simulations == 1000
    assert cfg.seed == 42
    assert cfg.initial_capital == 100_000.0


def test_none_seed_runs() -> None:
    """None seed (random) should still produce valid results."""
    trades = [100.0, -50.0, 200.0, -75.0]
    sim = MonteCarloSimulator(trades, MonteCarloConfig(n_simulations=50, seed=None))
    r = sim.run()
    assert r.n_simulations == 50
    assert r.p50 > 0
