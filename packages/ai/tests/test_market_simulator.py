"""Tests for MarketSimulator — mock LLM, no network calls."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_llm(response_text: str = "DIRECTION: BUY | CONFIDENCE: 0.75 | RATIONALE: Strong momentum") -> MagicMock:
    """Return a mock LLMClient whose chat() returns *response_text*."""
    mock_response = MagicMock()
    mock_response.success = True
    mock_response.content = response_text

    mock_llm = MagicMock()
    mock_llm.chat.return_value = mock_response
    return mock_llm


# ---------------------------------------------------------------------------
# Data-model tests
# ---------------------------------------------------------------------------


class TestMarketParticipant:
    """MarketParticipant dataclass behaviour."""

    def test_creation(self):
        from packages.ai.src.market_simulator import MarketParticipant

        p = MarketParticipant(
            name="Test Trader",
            persona="Aggressive retail buyer",
            risk_tolerance=0.8,
            capital=500_000,
        )
        assert p.name == "Test Trader"
        assert p.risk_tolerance == 0.8
        assert p.capital == 500_000

    def test_risk_bounds_not_enforced_by_dataclass(self):
        """Dataclass does not enforce bounds — caller's responsibility."""
        from packages.ai.src.market_simulator import MarketParticipant

        p = MarketParticipant(name="X", persona="Y", risk_tolerance=1.5, capital=0)
        assert p.risk_tolerance == 1.5  # no clipping — intentional

    def test_default_participants_count(self):
        from packages.ai.src.market_simulator import DEFAULT_PARTICIPANTS

        assert len(DEFAULT_PARTICIPANTS) == 5

    def test_default_participants_names_unique(self):
        from packages.ai.src.market_simulator import DEFAULT_PARTICIPANTS

        names = [p.name for p in DEFAULT_PARTICIPANTS]
        assert len(names) == len(set(names))

    def test_default_participants_risk_range(self):
        from packages.ai.src.market_simulator import DEFAULT_PARTICIPANTS

        for p in DEFAULT_PARTICIPANTS:
            assert 0.0 <= p.risk_tolerance <= 1.0, f"{p.name} risk out of range"


class TestParticipantAction:
    def test_creation(self):
        from packages.ai.src.market_simulator import ParticipantAction

        a = ParticipantAction(
            participant="Retail Bull",
            instrument="NIFTY",
            direction="BUY",
            rationale="Momentum is strong",
            confidence=0.8,
        )
        assert a.direction == "BUY"
        assert a.confidence == 0.8

    def test_direction_values(self):
        from packages.ai.src.market_simulator import ParticipantAction

        for d in ("BUY", "SELL", "HOLD"):
            a = ParticipantAction("P", "I", d, "reason", 0.5)
            assert a.direction == d


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


class TestParseResponse:
    def test_parse_buy(self):
        from packages.ai.src.market_simulator import _parse_response

        action = _parse_response(
            "DIRECTION: BUY | CONFIDENCE: 0.9 | RATIONALE: Bullish breakout",
            participant="Retail Bull",
            instrument="NIFTY",
        )
        assert action.direction == "BUY"
        assert action.confidence == 0.9
        assert "Bullish" in action.rationale

    def test_parse_sell(self):
        from packages.ai.src.market_simulator import _parse_response

        action = _parse_response(
            "DIRECTION: SELL | CONFIDENCE: 0.6 | RATIONALE: Resistance hit",
            participant="Inst Bear",
            instrument="BANKNIFTY",
        )
        assert action.direction == "SELL"
        assert action.confidence == 0.6

    def test_parse_hold(self):
        from packages.ai.src.market_simulator import _parse_response

        action = _parse_response(
            "DIRECTION: HOLD | CONFIDENCE: 0.4 | RATIONALE: Unclear signal",
            participant="Momentum",
            instrument="NIFTY",
        )
        assert action.direction == "HOLD"

    def test_parse_fallback_on_garbage(self):
        from packages.ai.src.market_simulator import _parse_response

        action = _parse_response("nonsense text", participant="X", instrument="Y")
        assert action.direction == "HOLD"
        assert action.confidence == 0.0

    def test_parse_confidence_clamped(self):
        from packages.ai.src.market_simulator import _parse_response

        action = _parse_response(
            "DIRECTION: BUY | CONFIDENCE: 5.0 | RATIONALE: overconfident",
            participant="X",
            instrument="Y",
        )
        assert action.confidence <= 1.0


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


class TestAggregate:
    def test_majority_buy(self):
        from packages.ai.src.market_simulator import ParticipantAction, _aggregate

        actions = [
            ParticipantAction("A", "N", "BUY", "r", 0.8),
            ParticipantAction("B", "N", "BUY", "r", 0.7),
            ParticipantAction("C", "N", "SELL", "r", 0.5),
        ]
        consensus, bull_pct, bear_pct = _aggregate(actions)
        assert consensus == "BUY"
        assert bull_pct > bear_pct

    def test_majority_sell(self):
        from packages.ai.src.market_simulator import ParticipantAction, _aggregate

        actions = [
            ParticipantAction("A", "N", "SELL", "r", 0.8),
            ParticipantAction("B", "N", "SELL", "r", 0.7),
            ParticipantAction("C", "N", "BUY", "r", 0.5),
        ]
        consensus, bull_pct, bear_pct = _aggregate(actions)
        assert consensus == "SELL"

    def test_hold_on_tie(self):
        from packages.ai.src.market_simulator import ParticipantAction, _aggregate

        actions = [
            ParticipantAction("A", "N", "BUY", "r", 0.8),
            ParticipantAction("B", "N", "SELL", "r", 0.8),
        ]
        consensus, _, _ = _aggregate(actions)
        assert consensus == "HOLD"

    def test_empty_actions(self):
        from packages.ai.src.market_simulator import _aggregate

        consensus, bull_pct, bear_pct = _aggregate([])
        assert consensus == "HOLD"
        assert bull_pct == 0.0
        assert bear_pct == 0.0

    def test_percentages_sum_le_100(self):
        from packages.ai.src.market_simulator import ParticipantAction, _aggregate

        actions = [
            ParticipantAction("A", "N", "BUY", "r", 0.9),
            ParticipantAction("B", "N", "HOLD", "r", 0.5),
        ]
        _, bull_pct, bear_pct = _aggregate(actions)
        assert bull_pct + bear_pct <= 100.0


# ---------------------------------------------------------------------------
# MarketSimulator — sync path
# ---------------------------------------------------------------------------


class TestMarketSimulatorSync:
    def test_simulate_sync_basic(self):
        from packages.ai.src.market_simulator import MarketSimulator

        llm = _make_mock_llm("DIRECTION: BUY | CONFIDENCE: 0.8 | RATIONALE: Test")
        sim = MarketSimulator(llm_client=llm, semaphore_limit=3)
        result = sim.simulate_sync("RBI rate hike", ["NIFTY"], steps=1)
        assert result.event == "RBI rate hike"
        assert result.steps == 1
        assert result.consensus_direction in ("BUY", "SELL", "HOLD")
        assert len(result.actions) == 5  # 5 default participants

    def test_simulate_sync_multiple_steps(self):
        from packages.ai.src.market_simulator import MarketSimulator

        llm = _make_mock_llm("DIRECTION: SELL | CONFIDENCE: 0.6 | RATIONALE: Bear")
        sim = MarketSimulator(llm_client=llm)
        result = sim.simulate_sync("Market crash", ["BANKNIFTY"], steps=3)
        assert result.steps == 3
        # 5 participants * 3 steps
        assert len(result.actions) == 15

    def test_simulate_sync_custom_participants(self):
        from packages.ai.src.market_simulator import MarketParticipant, MarketSimulator

        participants = [
            MarketParticipant("Scalper", "Day trader", 0.9, 200_000),
            MarketParticipant("Hedger", "Risk-off buyer", 0.2, 10_000_000),
        ]
        llm = _make_mock_llm("DIRECTION: HOLD | CONFIDENCE: 0.5 | RATIONALE: Wait")
        sim = MarketSimulator(llm_client=llm, participants=participants)
        result = sim.simulate_sync("Uncertainty event", ["NIFTY"], steps=2)
        assert len(result.actions) == 4  # 2 participants * 2 steps

    def test_simulate_sync_instruments_recorded(self):
        from packages.ai.src.market_simulator import MarketSimulator

        llm = _make_mock_llm("DIRECTION: BUY | CONFIDENCE: 0.7 | RATIONALE: ok")
        sim = MarketSimulator(llm_client=llm)
        result = sim.simulate_sync("Event", ["NIFTY", "BANKNIFTY"], steps=1)
        assert "NIFTY" in result.instruments
        assert "BANKNIFTY" in result.instruments

    def test_simulate_sync_llm_failure_graceful(self):
        """LLM failure should produce HOLD actions, not raise."""
        from packages.ai.src.market_simulator import MarketSimulator

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = Exception("Connection refused")
        sim = MarketSimulator(llm_client=mock_llm)
        result = sim.simulate_sync("Bad event", ["NIFTY"], steps=1)
        # All actions should be HOLD (fallback on error)
        assert all(a.direction == "HOLD" for a in result.actions)

    def test_simulate_sync_bull_bear_pct_range(self):
        from packages.ai.src.market_simulator import MarketSimulator

        llm = _make_mock_llm("DIRECTION: BUY | CONFIDENCE: 0.9 | RATIONALE: Bullish")
        sim = MarketSimulator(llm_client=llm)
        result = sim.simulate_sync("Positive surprise", ["NIFTY"], steps=1)
        assert 0.0 <= result.bull_pct <= 100.0
        assert 0.0 <= result.bear_pct <= 100.0


# ---------------------------------------------------------------------------
# MarketSimulator — async path
# ---------------------------------------------------------------------------


class TestMarketSimulatorAsync:
    def test_simulate_async_basic(self):
        from packages.ai.src.market_simulator import MarketSimulator

        llm = _make_mock_llm("DIRECTION: BUY | CONFIDENCE: 0.8 | RATIONALE: OK")
        sim = MarketSimulator(llm_client=llm, semaphore_limit=5)
        result = asyncio.run(sim.simulate("Inflation data", ["NIFTY"], steps=1))
        assert result.event == "Inflation data"
        assert len(result.actions) == 5

    def test_simulate_async_consensus_valid(self):
        from packages.ai.src.market_simulator import MarketSimulator

        llm = _make_mock_llm("DIRECTION: SELL | CONFIDENCE: 0.7 | RATIONALE: Bear trend")
        sim = MarketSimulator(llm_client=llm)
        result = asyncio.run(sim.simulate("GDP miss", ["BANKNIFTY"], steps=2))
        assert result.consensus_direction in ("BUY", "SELL", "HOLD")


# ---------------------------------------------------------------------------
# Package export
# ---------------------------------------------------------------------------


class TestMarketSimulatorExports:
    def test_exported_from_package(self):
        from packages.ai.src import (
            DEFAULT_PARTICIPANTS,
            MarketSimulator,
        )

        assert MarketSimulator is not None
        assert len(DEFAULT_PARTICIPANTS) == 5

    def test_simulation_result_dataclass(self):
        from packages.ai.src.market_simulator import SimulationResult

        r = SimulationResult(
            event="Test",
            instruments=["NIFTY"],
            steps=2,
            actions=[],
            consensus_direction="BUY",
            bull_pct=60.0,
            bear_pct=20.0,
        )
        assert r.consensus_direction == "BUY"
        assert r.bull_pct == 60.0
