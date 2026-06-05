"""Evidence tests: the regime → strategy loop ("pick the right strategy per
market regime") is functional end-to-end."""

from __future__ import annotations

import pytest

from flinttrade_ai.regime_detector import (
    RegimeState,
    StrategySuggestion,
    detect_regime,
    select_strategy_for_regime,
)

pytestmark = pytest.mark.unit


def test_every_regime_maps_to_a_concrete_strategy():
    for state in RegimeState:
        suggestion = select_strategy_for_regime(state)
        assert isinstance(suggestion, StrategySuggestion)
        assert suggestion.strategy and suggestion.label and suggestion.rationale


def test_trending_regime_recommends_a_real_strategy():
    suggestion = select_strategy_for_regime(RegimeState.TRENDING_UP)
    assert suggestion.strategy != "stand_aside"


def test_detect_then_select_closes_the_loop():
    # A clean rising series → a regime is detected → a strategy is recommended.
    n = 60
    close = [100.0 + i for i in range(n)]
    high = [c + 1.0 for c in close]
    low = [c - 1.0 for c in close]

    state = detect_regime(high, low, close)
    assert isinstance(state, RegimeState)

    suggestion = select_strategy_for_regime(state)
    assert suggestion.strategy  # the detect → select loop yields a recommendation
    assert suggestion.to_dict()["label"]


def test_full_loop_regime_to_overnight_report():
    """The whole AI workflow runs together with REAL components: a price series
    is classified into a regime, that regime selects a strategy style, and the
    overnight optimiser refines it into a report with an improvement suggestion
    for exactly that strategy. No mocks in the middle.
    """
    from flinttrade_ai.overnight_optimiser import OvernightOptimiser
    from flinttrade_ai.strategy_refiner import StrategyRefiner

    n = 60
    close = [100.0 + i for i in range(n)]
    high = [c + 1.0 for c in close]
    low = [c - 1.0 for c in close]

    state = detect_regime(high, low, close)
    suggestion = select_strategy_for_regime(state)
    assert suggestion.strategy

    def _provider() -> list[dict]:
        return [{
            "name": suggestion.strategy,
            "params": {"fast_period": 9, "slow_period": 21},
            "backtest_results": {
                "sharpe_ratio": 0.6, "max_drawdown": -0.2, "win_rate": 0.4,
                "total_trades": 50, "total_return": 0.08, "profit_factor": 1.3,
            },
        }]

    report = OvernightOptimiser(_provider, StrategyRefiner()).run()

    assert report["strategies_optimised"] == 1
    only = report["suggestions"][0]
    assert only["strategy_name"] == suggestion.strategy
    assert only["analysis"].strip()
    assert 0.0 <= only["confidence"] <= 1.0
