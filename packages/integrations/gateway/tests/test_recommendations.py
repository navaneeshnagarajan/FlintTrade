"""Tests for the broker recommendation engine ("which broker for what")."""

from __future__ import annotations

import pytest

from flinttrade_gateway.capabilities import (
    AuthModel,
    Capabilities,
    DepthLevels,
    OrderTypes,
    Segments,
    TickProtocol,
)
from flinttrade_gateway.recommendations import (
    NATIVE_BROKER_CAPABILITIES,
    BrokerRecommendation,
    BrokerUseCase,
    best_broker_for,
    recommend,
    recommend_all,
    _SCORERS,
)

pytestmark = pytest.mark.unit


def _bare(**overrides) -> Capabilities:
    """A minimal Capabilities with no advantages, plus overrides."""
    base = dict(
        segments=Segments.NSE_EQ,
        order_types=OrderTypes.MARKET,
        depth_levels=DepthLevels.L1,
        tick_protocol=TickProtocol.GENERIC_JSON,
        auth_model=AuthModel.API_KEY_PERSISTENT,
        session_lifetime_hours=24.0,
    )
    base.update(overrides)
    return Capabilities(**base)


def test_recommend_returns_one_entry_per_broker_sorted_desc() -> None:
    recs = recommend(BrokerUseCase.MARKET_DEPTH)
    assert {r.broker_id for r in recs} == set(NATIVE_BROKER_CAPABILITIES)
    scores = [r.raw_score for r in recs]
    assert scores == sorted(scores, reverse=True)


def test_top_recommendation_is_normalised_to_one() -> None:
    recs = recommend(BrokerUseCase.LOW_COST_EXECUTION)
    assert recs[0].score == pytest.approx(1.0)
    assert all(0.0 <= r.score <= 1.0 for r in recs)


def test_kotak_neo_wins_low_cost_execution() -> None:
    # User's stated differentiator: Kotak Neo = zero brokerage execution.
    top = best_broker_for(BrokerUseCase.LOW_COST_EXECUTION)
    assert top is not None
    assert top.broker_id == "kotakneo"
    assert "zero execution brokerage" in top.rationale


def test_kotak_neo_scores_zero_for_options_and_historical() -> None:
    # Kotak Neo has no option-chain API and no historical candle API.
    for use_case in (BrokerUseCase.OPTIONS_ANALYTICS, BrokerUseCase.HISTORICAL_DATA):
        by_broker = {r.broker_id: r for r in recommend(use_case)}
        assert by_broker["kotakneo"].raw_score == 0.0


def test_dhan_wins_options_history() -> None:
    # User's stated differentiator: Dhan = rolling-options history.
    top = best_broker_for(BrokerUseCase.OPTIONS_HISTORY)
    assert top is not None
    assert top.broker_id == "dhan"
    assert "rolling" in top.rationale.lower()


def test_options_history_scorer_rewards_rolling_series() -> None:
    rolling, _ = _SCORERS[BrokerUseCase.OPTIONS_HISTORY](
        _bare(options_history_supported=True, options_history_rolling=True)
    )
    flat, _ = _SCORERS[BrokerUseCase.OPTIONS_HISTORY](
        _bare(options_history_supported=True, options_history_rolling=False)
    )
    none, msg = _SCORERS[BrokerUseCase.OPTIONS_HISTORY](_bare())
    assert rolling > flat > none == 0.0
    assert "No historical options-data API" in msg


def test_dhan_tops_streaming_and_advanced_orders() -> None:
    # Dhan advertises concrete streaming limits and the widest native order set.
    assert best_broker_for(BrokerUseCase.STREAMING).broker_id == "dhan"
    assert best_broker_for(BrokerUseCase.ADVANCED_ORDERS).broker_id == "dhan"


def test_upstox_tops_historical_data() -> None:
    # The mission names Upstox as the historical-data edge: its v2/v3 history API
    # serves 30-minute intraday for the last 1 year (~365 days), the deepest
    # intraday lookback of the three natives (Dhan caps at 90). The engine must
    # rank Upstox first for HISTORICAL_DATA, not Dhan.
    assert best_broker_for(BrokerUseCase.HISTORICAL_DATA).broker_id == "upstox"


def test_options_analytics_excludes_brokers_without_a_chain() -> None:
    recs = {r.broker_id: r for r in recommend(BrokerUseCase.OPTIONS_ANALYTICS)}
    assert recs["dhan"].raw_score > 0
    assert recs["upstox"].raw_score > 0
    assert recs["kotakneo"].raw_score == 0.0


def test_recommend_all_covers_every_use_case() -> None:
    everything = recommend_all()
    assert set(everything) == {uc.value for uc in BrokerUseCase}
    for ranked in everything.values():
        assert len(ranked) == len(NATIVE_BROKER_CAPABILITIES)
        assert all(isinstance(r, BrokerRecommendation) for r in ranked)


def test_ties_break_deterministically_by_broker_id() -> None:
    caps = {"zebra": _bare(), "alpha": _bare()}  # identical -> tie
    recs = recommend(BrokerUseCase.MARKET_DEPTH, caps)
    assert [r.broker_id for r in recs] == ["alpha", "zebra"]


def test_best_broker_for_returns_none_when_all_zero() -> None:
    # No broker has an option chain -> no qualifying recommendation.
    caps = {"a": _bare(), "b": _bare()}
    assert best_broker_for(BrokerUseCase.OPTIONS_ANALYTICS, caps) is None


def test_custom_capability_subset_is_respected() -> None:
    # Restricting to one broker returns exactly that broker.
    subset = {"upstox": NATIVE_BROKER_CAPABILITIES["upstox"]}
    recs = recommend(BrokerUseCase.HISTORICAL_DATA, subset)
    assert [r.broker_id for r in recs] == ["upstox"]


def test_zero_brokerage_note_surfaced_in_rationale() -> None:
    top = best_broker_for(BrokerUseCase.LOW_COST_EXECUTION)
    assert "square-off leg" in top.rationale  # the documented brokerage caveat
