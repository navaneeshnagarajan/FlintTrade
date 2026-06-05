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
