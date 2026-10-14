"""Statistic definitions, not financial qualification; synthetic samples."""
import pytest
from flinttrade_backtest.permutation_test import PermutationConfig, PermutationTester
from flinttrade_backtest.monte_carlo import MonteCarloConfig, MonteCarloSimulator

pytestmark = pytest.mark.unit


def test_sign_randomisation_changes_order_invariant_metric_with_nonzero_p_value():
    result = PermutationTester(PermutationConfig(n_permutations=200, metric="total_return")).test_returns(
        [0.01, 0.02, 0.03, 0.01, 0.04, 0.02, 0.03, 0.04])
    assert result.permutation_std > 1
    assert 0 < result.p_value < 0.05
    assert result.as_dict()["null_model"] == "independent_sign_symmetry"


@pytest.mark.parametrize("trades", [[{"net_pnl": 100}], [{"return_pct": float("nan")}]] )
def test_trade_test_refuses_currency_as_return_or_nonfinite(trades):
    with pytest.raises(ValueError):
        PermutationTester().test_trades(trades, [0.01, -0.01, 0.02])


def test_shuffle_exposes_constant_terminal_total_and_path_stress_only():
    result = MonteCarloSimulator([100, -200, 300], MonteCarloConfig(n_simulations=20)).run()
    assert result.p5 == result.p95
    assert result.std_final == 0
    assert result.as_dict()["sampling_method"] == "permutation"
    assert result.as_dict()["terminal_distribution_estimated"] is False


def test_bootstrap_resamples_terminal_outcomes_when_explicitly_selected():
    result = MonteCarloSimulator([100, -200, 300], MonteCarloConfig(
        n_simulations=100, sampling_method="bootstrap")).run()
    assert result.p5 < result.p95
    assert result.as_dict()["terminal_distribution_estimated"] is True
