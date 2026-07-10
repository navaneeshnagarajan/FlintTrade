"""Tests for the multi-round risk debate module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from flinttrade_ai.risk_debate import (
    DebateResult,
    DebateRound,
    RiskDebate,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_llm(responses: list[str] | None = None) -> MagicMock:
    """Create a mock LLMClient that returns canned responses."""
    llm = MagicMock()
    if responses is None:
        responses = [
            # Round 1: aggressive, conservative, neutral
            "The upside potential is enormous, VIX is low, buy aggressively.",
            "The risk is too high, margin requirements are steep, avoid.",
            "Both sides have merit, consider a smaller position with hedges.",
            # Round 2: aggressive, conservative, neutral
            "I counter the conservative view: low VIX means low risk environment.",
            "Counter to aggressive: low VIX often precedes spikes.",
            "The truth lies in position sizing, not direction.",
            # Judge
            "VERDICT: BUY\nCONFIDENCE: 0.72\nREASONING: Low VIX supports directional bet with hedges.",
        ]
    call_count = [0]

    def side_effect(messages, **kwargs):
        resp = MagicMock()
        idx = min(call_count[0], len(responses) - 1)
        resp.content = responses[idx]
        resp.success = True
        call_count[0] += 1
        return resp

    llm.chat.side_effect = side_effect
    return llm


# ---------------------------------------------------------------------------
# Tests: DebateRound and DebateResult models
# ---------------------------------------------------------------------------


class TestDebateModels:
    """Tests for the debate data models."""

    def test_debate_round_defaults(self) -> None:
        r = DebateRound(round_number=1)
        assert r.round_number == 1
        assert r.aggressive == ""
        assert r.conservative == ""
        assert r.neutral == ""

    def test_debate_result_defaults(self) -> None:
        r = DebateResult(trade_proposal="BUY NIFTY")
        assert r.trade_proposal == "BUY NIFTY"
        assert r.verdict == "HOLD"
        assert r.confidence == 0.0
        assert r.timestamp  # auto-populated
        assert r.rounds == []

    def test_debate_result_custom(self) -> None:
        r = DebateResult(
            trade_proposal="SELL BANKNIFTY",
            verdict="SELL",
            confidence=0.8,
            reasoning="Bearish consensus.",
        )
        assert r.verdict == "SELL"
        assert r.confidence == 0.8


# ---------------------------------------------------------------------------
# Tests: RiskDebate
# ---------------------------------------------------------------------------


class TestRiskDebate:
    """Tests for the RiskDebate orchestrator."""

    def test_basic_debate_runs(self) -> None:
        llm = _make_mock_llm()
        debate = RiskDebate(llm_client=llm, rounds=2)
        result = debate.run(
            trade_proposal="BUY NIFTY 22000 CE at 350",
            market_context={"rsi": 68, "vix": 14.2},
        )
        assert isinstance(result, DebateResult)
        assert result.verdict == "BUY"
        assert result.confidence == pytest.approx(0.72)
        assert len(result.rounds) == 2
        # 2 rounds x 3 debaters + 1 judge = 7 LLM calls
        assert llm.chat.call_count == 7

    def test_single_round_debate(self) -> None:
        llm = _make_mock_llm(
            [
                "Aggressive argument",
                "Conservative argument",
                "Neutral argument",
                "VERDICT: HOLD\nCONFIDENCE: 0.5\nREASONING: No clear edge.",
            ]
        )
        debate = RiskDebate(llm_client=llm, rounds=1)
        result = debate.run(trade_proposal="SELL RELIANCE")
        assert len(result.rounds) == 1
        assert result.verdict == "HOLD"
        assert result.confidence == pytest.approx(0.5)

    def test_no_market_context(self) -> None:
        llm = _make_mock_llm()
        debate = RiskDebate(llm_client=llm, rounds=1)
        result = debate.run(trade_proposal="BUY NIFTY")
        assert isinstance(result, DebateResult)

    def test_separate_judge_llm(self) -> None:
        llm = _make_mock_llm()
        judge_llm = _make_mock_llm(
            [
                "VERDICT: SELL\nCONFIDENCE: 0.9\nREASONING: Strong bearish case.",
            ]
        )
        debate = RiskDebate(llm_client=llm, judge_llm_client=judge_llm, rounds=1)
        result = debate.run(trade_proposal="BUY NIFTY")
        # Judge should use the separate LLM
        assert judge_llm.chat.call_count == 1
        assert result.verdict == "SELL"

    def test_judge_failure_fallback(self) -> None:
        call_count = [0]

        def side_effect(messages, **kwargs):
            resp = MagicMock()
            call_count[0] += 1
            if call_count[0] <= 3:
                resp.content = "Debater argument"
                resp.success = True
            else:
                raise RuntimeError("LLM down")
            return resp

        llm = MagicMock()
        llm.chat.side_effect = side_effect
        debate = RiskDebate(llm_client=llm, rounds=1)
        result = debate.run(trade_proposal="BUY NIFTY")
        assert result.verdict == "HOLD"
        assert result.reasoning == "Judge analysis failed"
        assert "LLM down" not in result.reasoning
        assert result.error_codes == {"judge": "provider_failure"}

    def test_debate_transcript_accumulates(self) -> None:
        llm = _make_mock_llm()
        debate = RiskDebate(llm_client=llm, rounds=2)
        result = debate.run(trade_proposal="BUY NIFTY")
        assert "Round 1" in result.full_transcript
        assert "Round 2" in result.full_transcript
        assert "Aggressive" in result.full_transcript
        assert "Conservative" in result.full_transcript
        assert "Neutral" in result.full_transcript

    def test_minimum_rounds_clamped_to_1(self) -> None:
        debate = RiskDebate(llm_client=_make_mock_llm(), rounds=0)
        assert debate._rounds == 1

    def test_debater_failure_returns_empty(self) -> None:
        llm = MagicMock()
        llm.chat.side_effect = RuntimeError("Connection error")
        debate = RiskDebate(llm_client=llm, rounds=1)
        result = debate.run(trade_proposal="BUY NIFTY")
        # All debaters fail, judge also fails
        assert result.verdict == "HOLD"


# ---------------------------------------------------------------------------
# Tests: Judge response parsing
# ---------------------------------------------------------------------------


class TestJudgeParsing:
    """Tests for the judge response parser."""

    def test_valid_response(self) -> None:
        text = "VERDICT: BUY\nCONFIDENCE: 0.85\nREASONING: Strong bullish case."
        v, c, r = RiskDebate._parse_judge_response(text)
        assert v == "BUY"
        assert c == pytest.approx(0.85)
        assert r == "Strong bullish case."

    def test_sell_verdict(self) -> None:
        text = "VERDICT: SELL\nCONFIDENCE: 0.6\nREASONING: Bears win."
        v, c, r = RiskDebate._parse_judge_response(text)
        assert v == "SELL"
        assert c == pytest.approx(0.6)

    def test_missing_verdict_defaults_hold(self) -> None:
        text = "CONFIDENCE: 0.5\nREASONING: Unclear."
        v, c, r = RiskDebate._parse_judge_response(text)
        assert v == "HOLD"

    def test_invalid_confidence_defaults_zero(self) -> None:
        text = "VERDICT: BUY\nCONFIDENCE: abc\nREASONING: test"
        v, c, r = RiskDebate._parse_judge_response(text)
        assert v == "BUY"
        assert c == 0.0

    def test_confidence_clamped(self) -> None:
        text = "VERDICT: BUY\nCONFIDENCE: 5.0\nREASONING: test"
        _, c, _ = RiskDebate._parse_judge_response(text)
        assert c == 1.0

    def test_completely_malformed(self) -> None:
        text = "I think we should buy because reasons."
        v, c, r = RiskDebate._parse_judge_response(text)
        assert v == "HOLD"
        assert c == 0.0
        # Reasoning falls back to full text
        assert r == text
