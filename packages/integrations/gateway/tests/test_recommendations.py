"""Tests for the broker capability metadata ranking engine."""

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


def test_streaming_requires_runtime_wiring() -> None:
    # Several brokers document feeds and the adapters can decode injected frames,
    # but the live SDK/callback streams are not wired into FlintTrade runtime yet.
    # Do not recommend a broker for "Live streaming" until stream() works without
    # test/feed-factory injection.
    assert best_broker_for(BrokerUseCase.STREAMING) is None
    by_broker = {r.broker_id: r for r in recommend(BrokerUseCase.STREAMING)}
    assert by_broker["dhan"].raw_score == 0.0
    assert "not enabled yet" in by_broker["dhan"].rationale


def test_streaming_scorer_rewards_runtime_ready_feeds() -> None:
    blocked, blocked_msg = _SCORERS[BrokerUseCase.STREAMING](
        _bare(streaming_supported=True, streaming_runtime_ready=False)
    )
    ready, ready_msg = _SCORERS[BrokerUseCase.STREAMING](
        _bare(
            streaming_supported=True,
            streaming_runtime_ready=True,
            streaming_max_total_symbols=1000,
            streaming_max_connections_per_user=2,
        )
    )
    none, none_msg = _SCORERS[BrokerUseCase.STREAMING](_bare())
    assert ready > blocked == none == 0.0
    assert "not enabled yet" in blocked_msg
    assert "No real-time streaming" in none_msg
    assert "live streaming" in ready_msg


def test_dhan_tops_advanced_orders() -> None:
    # Dhan advertises the widest native order set.
    assert best_broker_for(BrokerUseCase.ADVANCED_ORDERS).broker_id == "dhan"


def test_dhan_tops_historical_data() -> None:
    # 2026-06-12 correctness pass: an earlier comment credited Upstox with the
    # deepest intraday lookback ("Dhan caps at 90"), but the broker docs say the
    # opposite — Dhan's v2 history API serves 1/5/15/25/60-minute intraday for
    # the last ~5 years (90 days is its per-REQUEST range, not the lookback;
    # historical-data.md), whereas Upstox's 1-minute candles reach only ~1 month
    # (HistoryApi.md; the 1-year figure was 30-minute-only). With every adapter's
    # capability metadata honest, the engine correctly ranks Dhan first for
    # intraday HISTORICAL_DATA.
    assert best_broker_for(BrokerUseCase.HISTORICAL_DATA).broker_id == "dhan"


def test_indmoney_is_registered_and_ranked() -> None:
    # IndMoney is a full-parity native adapter (INDMONEY_CAPABILITIES) and must be
    # registered in NATIVE_BROKER_CAPABILITIES so the engine — and the
    # ``?brokers=indmoney`` route filter that validates against it — recognise it.
    assert "indmoney" in NATIVE_BROKER_CAPABILITIES
    ranked_ids = {r.broker_id for r in recommend(BrokerUseCase.HISTORICAL_DATA)}
    assert "indmoney" in ranked_ids


def test_dhan_beats_indmoney_on_documented_intraday_depth() -> None:
    # The honest invariant the scorer must defend: deep DOCUMENTED intraday
    # lookback (Dhan, ~5 years) outranks a broad-but-shallow interval menu
    # (IndMoney — 12 intervals but only ~7-day 1-minute depth, lookback unset),
    # which in turn outranks Upstox's ~1-month 1-minute depth. A future reweight
    # toward raw interval count would over-credit IndMoney and break this — that
    # is the regression this test guards against.
    by_broker = {r.broker_id: r for r in recommend(BrokerUseCase.HISTORICAL_DATA)}
    assert by_broker["dhan"].raw_score > by_broker["indmoney"].raw_score
    assert by_broker["indmoney"].raw_score > by_broker["upstox"].raw_score


def test_historical_data_full_ranking_with_indmoney() -> None:
    # Pin the exact HISTORICAL_DATA order with all four natives registered:
    #   dhan (5 intervals + 1825-day lookback = 70.83)
    #   > indmoney (12 intervals * 2 = 24.0; lookback honestly unset)
    #   > upstox (5 intervals + 31-day lookback = 11.03)
    #   > kotakneo (no candle API = 0.0).
    # IndMoney displaces Upstox at #2 on documented interval breadth, but Dhan's
    # real ~5-year intraday depth keeps it #1 — the doc-honest outcome.
    ranked_ids = [r.broker_id for r in recommend(BrokerUseCase.HISTORICAL_DATA)]
    assert ranked_ids == ["dhan", "indmoney", "upstox", "kotakneo"]


def test_indmoney_scores_zero_for_options() -> None:
    # IndMoney's options/utility family is "Coming Soon" broker-side, so it has no
    # option chain and no historical-options API — it must score 0 for both.
    for use_case in (BrokerUseCase.OPTIONS_ANALYTICS, BrokerUseCase.OPTIONS_HISTORY):
        by_broker = {r.broker_id: r for r in recommend(use_case)}
        assert by_broker["indmoney"].raw_score == 0.0


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
