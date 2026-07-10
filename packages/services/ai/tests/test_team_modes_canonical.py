"""Canonical contract tests for the analyst-chain and risk-debate modes."""

from __future__ import annotations

from datetime import date
from inspect import signature
from types import SimpleNamespace
from typing import Any

import pytest

from flinttrade_ai._team_modes import (
    AnalysisState,
    AnalystChain,
    DebateResult,
    DebateRound,
    RiskDebate,
)
from flinttrade_ai.llm_client import LLMMessage, LLMResponse
from flinttrade_ai.memory import MemoryEntry, MemoryLayer


class ScriptedLLM:
    """Small deterministic LLM fake that records each message list."""

    def __init__(self, responses: list[str | LLMResponse | Exception]) -> None:
        self._responses = iter(responses)
        self.calls: list[list[LLMMessage]] = []

    def chat(self, messages: list[LLMMessage]) -> LLMResponse:
        self.calls.append(messages)
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, LLMResponse):
            return response
        return LLMResponse(content=response)


def _user_content(call: list[LLMMessage]) -> str:
    return next(message.content for message in call if message.role == "user")


class CanonicalMemory:
    """Memory fake exposing the current retrieve API and a forbidden legacy path."""

    def __init__(self, entries: list[MemoryEntry], *, error: Exception | None = None) -> None:
        self.entries = entries
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        *,
        symbol: str | None = None,
        layer: MemoryLayer | None = None,
    ) -> list[MemoryEntry]:
        self.calls.append({"query": query, "top_k": top_k, "symbol": symbol, "layer": layer})
        if self.error is not None:
            raise self.error
        return self.entries

    def get_memories(self, *_args: object, **_kwargs: object) -> object:
        raise AssertionError("legacy retrieval must not run when retrieve is available")


class LegacyMemory:
    """Memory fake retaining only the former TradedMemory retrieval shape."""

    def __init__(self, entries: list[MemoryEntry]) -> None:
        self.entries = entries
        self.calls: list[tuple[object, ...]] = []

    def get_memories(
        self,
        symbol: str,
        query: str,
        layer: MemoryLayer,
        n: int = 3,
    ) -> object:
        self.calls.append((symbol, query, layer, n))
        return SimpleNamespace(items=self.entries)


def test_public_models_and_constructor_shapes_are_preserved() -> None:
    state = AnalysisState(symbol="NIFTY", exchange="NSE_INDEX", trade_date=date(2026, 7, 10))
    debate_round = DebateRound(round_number=1)
    debate_result = DebateResult(trade_proposal="BUY NIFTY")

    assert state.market_report == ""
    assert state.sentiment_report == ""
    assert state.bull_thesis == ""
    assert state.bear_thesis == ""
    assert state.risk_assessment == ""
    assert state.final_decision == "HOLD"
    assert state.final_reasoning == ""
    assert state.confidence == 0.0
    assert state.errors == []
    assert debate_round == DebateRound(round_number=1, aggressive="", conservative="", neutral="")
    assert debate_result.rounds == []
    assert debate_result.verdict == "HOLD"
    assert debate_result.timestamp

    analyst_params = signature(AnalystChain.__init__).parameters
    assert list(analyst_params) == ["self", "llm_client", "deep_llm_client", "memory", "analysts"]
    assert analyst_params["deep_llm_client"].default is None
    assert analyst_params["memory"].default is None
    assert analyst_params["analysts"].default is None

    debate_params = signature(RiskDebate.__init__).parameters
    assert list(debate_params) == ["self", "llm_client", "judge_llm_client", "rounds"]
    assert debate_params["judge_llm_client"].default is None
    assert debate_params["rounds"].default == 2


def test_risk_debate_runs_rounds_in_order_and_gives_full_transcript_to_judge() -> None:
    quick = ScriptedLLM(
        [
            "aggressive-1",
            "conservative-1",
            "neutral-1",
            "aggressive-2",
            "conservative-2",
            "neutral-2",
        ]
    )
    judge = ScriptedLLM(["VERDICT: BUY\nCONFIDENCE: 0.72\nREASONING: The upside wins with controlled sizing."])

    result = RiskDebate(quick, judge_llm_client=judge, rounds=2).run(
        "BUY NIFTY 25000 CE",
        {"vix": 13.5, "rsi": 68},
    )

    assert result.rounds == [
        DebateRound(1, "aggressive-1", "conservative-1", "neutral-1"),
        DebateRound(2, "aggressive-2", "conservative-2", "neutral-2"),
    ]
    assert result.full_transcript == (
        "[Round 1 - Aggressive]: aggressive-1\n\n"
        "[Round 1 - Conservative]: conservative-1\n\n"
        "[Round 1 - Neutral]: neutral-1\n\n"
        "[Round 2 - Aggressive]: aggressive-2\n\n"
        "[Round 2 - Conservative]: conservative-2\n\n"
        "[Round 2 - Neutral]: neutral-2"
    )
    assert result.verdict == "BUY"
    assert result.confidence == pytest.approx(0.72)
    assert result.reasoning == "The upside wins with controlled sizing."
    assert len(quick.calls) == 6
    assert len(judge.calls) == 1

    conservative_prompt = _user_content(quick.calls[1])
    assert "Latest Aggressive argument: aggressive-1" in conservative_prompt
    assert "[Round 1 - Aggressive]: aggressive-1" in conservative_prompt

    second_aggressive_prompt = _user_content(quick.calls[3])
    assert "Latest Conservative argument: conservative-1" in second_aggressive_prompt
    assert "Latest Neutral argument: neutral-1" in second_aggressive_prompt
    assert "[Round 1 - Neutral]: neutral-1" in second_aggressive_prompt

    judge_prompt = _user_content(judge.calls[0])
    assert "vix: 13.5" in judge_prompt
    assert result.full_transcript in judge_prompt


def test_risk_debate_clamps_rounds_and_falls_back_when_judge_fails() -> None:
    quick = ScriptedLLM(["aggressive", "conservative", "neutral"])
    judge = ScriptedLLM([RuntimeError("judge unavailable")])
    debate = RiskDebate(quick, judge_llm_client=judge, rounds=0)

    result = debate.run("SELL BANKNIFTY")

    assert debate._rounds == 1
    assert len(result.rounds) == 1
    assert result.verdict == "HOLD"
    assert result.confidence == 0.0
    assert result.reasoning == "Judge analysis failed"
    assert "judge unavailable" not in result.reasoning


def test_unsuccessful_debaters_and_judge_are_explicit_sanitised_failures() -> None:
    secret = "provider token=debate-secret"
    quick = ScriptedLLM(
        [
            LLMResponse(error=secret),
            LLMResponse(content=""),
            "neutral survived",
        ]
    )
    judge = ScriptedLLM([LLMResponse(error=secret)])

    result = RiskDebate(quick, judge_llm_client=judge, rounds=1).run("BUY NIFTY")

    assert result.rounds[0] == DebateRound(1, "", "", "neutral survived")
    assert result.verdict == "HOLD"
    assert result.confidence == 0.0
    assert result.reasoning == "Judge analysis failed"
    assert secret not in repr(result)


def test_judge_parsers_preserve_structured_and_malformed_fallbacks() -> None:
    decision = AnalystChain._parse_judge_response("DECISION: SELL\nCONFIDENCE: 4\nREASONING: Breakdown confirmed.")
    verdict = RiskDebate._parse_judge_response("The debate did not reach a structured verdict.")

    assert decision == ("SELL", 1.0, "Breakdown confirmed.")
    assert verdict == ("HOLD", 0.0, "The debate did not reach a structured verdict.")


def test_analyst_chain_runs_sequentially_with_short_memory_then_deep_judge() -> None:
    memories = [
        MemoryEntry(content="first short sentiment", symbol="RELIANCE", layer=MemoryLayer.SHORT),
        MemoryEntry(content="second short sentiment", symbol="RELIANCE", layer=MemoryLayer.SHORT),
        MemoryEntry(content="third result must be ignored", symbol="RELIANCE", layer=MemoryLayer.SHORT),
    ]
    memory = CanonicalMemory(memories)
    quick = ScriptedLLM(
        [
            "market report",
            "sentiment report",
            "BULL: earnings growth\nBEAR: expensive valuation",
        ]
    )
    deep = ScriptedLLM(["DECISION: BUY\nCONFIDENCE: 0.81\nREASONING: Reports align on controlled upside."])
    chain = AnalystChain(
        quick,
        deep_llm_client=deep,
        memory=memory,
        analysts=["market", "sentiment", "fundamentals"],
    )

    state = chain.analyse("RELIANCE", "NSE", trade_date=date(2026, 7, 9))

    assert state == AnalysisState(
        symbol="RELIANCE",
        exchange="NSE",
        trade_date=date(2026, 7, 9),
        market_report="market report",
        sentiment_report="sentiment report",
        bull_thesis="earnings growth",
        bear_thesis="expensive valuation",
        final_decision="BUY",
        final_reasoning="Reports align on controlled upside.",
        confidence=0.81,
    )
    assert memory.calls == [
        {
            "query": "sentiment for RELIANCE",
            "top_k": 2,
            "symbol": "RELIANCE",
            "layer": MemoryLayer.SHORT,
        }
    ]
    assert len(quick.calls) == 3
    assert "current market conditions" in _user_content(quick.calls[0])
    sentiment_prompt = _user_content(quick.calls[1])
    assert "first short sentiment" in sentiment_prompt
    assert "second short sentiment" in sentiment_prompt
    assert "third result must be ignored" not in sentiment_prompt
    assert "fundamental outlook" in _user_content(quick.calls[2])
    assert len(deep.calls) == 1
    judge_prompt = _user_content(deep.calls[0])
    assert "MARKET ANALYSIS:\nmarket report" in judge_prompt
    assert "SENTIMENT ANALYSIS:\nsentiment report" in judge_prompt
    assert "BULL THESIS:\nearnings growth" in judge_prompt
    assert "BEAR THESIS:\nexpensive valuation" in judge_prompt


def test_unsuccessful_sequential_responses_become_sanitised_failures() -> None:
    secret = "provider token=sequential-secret"
    quick = ScriptedLLM(
        [
            LLMResponse(error=secret),
            LLMResponse(content=""),
            "BULL: durable growth\nBEAR: valuation",
        ]
    )
    deep = ScriptedLLM([LLMResponse(error=secret)])

    state = AnalystChain(
        quick,
        deep_llm_client=deep,
        analysts=["market", "sentiment", "fundamentals"],
    ).analyse("TCS", "NSE")

    assert state.market_report == ""
    assert state.sentiment_report == ""
    assert state.final_decision == "HOLD"
    assert state.final_reasoning == ""
    assert state.errors == [
        "market: analysis failed",
        "sentiment: analysis failed",
        "judge: analysis failed",
    ]
    assert secret not in repr(state)


def test_analyst_chain_supports_legacy_memory_retrieval_and_quick_judge_fallback() -> None:
    memory = LegacyMemory([MemoryEntry(content="legacy short sentiment", symbol="NIFTY", layer=MemoryLayer.SHORT)])
    quick = ScriptedLLM(
        [
            "sentiment report",
            "DECISION: HOLD\nCONFIDENCE: 0.4\nREASONING: Signals conflict.",
        ]
    )

    state = AnalystChain(quick, memory=memory, analysts=["sentiment"]).analyse("NIFTY", "NSE_INDEX")

    assert memory.calls == [("NIFTY", "sentiment for NIFTY", MemoryLayer.SHORT, 2)]
    assert "legacy short sentiment" in _user_content(quick.calls[0])
    assert len(quick.calls) == 2
    assert state.final_decision == "HOLD"
    assert state.confidence == pytest.approx(0.4)


def test_analyst_and_memory_failures_are_captured_or_softened_without_stopping_order() -> None:
    memory = CanonicalMemory([], error=RuntimeError("memory offline"))
    quick = ScriptedLLM(
        [
            RuntimeError("market timeout"),
            "sentiment survived",
            "BULL: durable growth\nBEAR: weak margins",
        ]
    )
    deep = ScriptedLLM([RuntimeError("judge timeout")])
    chain = AnalystChain(
        quick,
        deep_llm_client=deep,
        memory=memory,
        analysts=["market", "sentiment", "unknown", "fundamentals"],
    )

    state = chain.analyse("TCS", "NSE", trade_date=date(2026, 7, 8))

    assert state.market_report == ""
    assert state.sentiment_report == "sentiment survived"
    assert state.bull_thesis == "durable growth"
    assert state.bear_thesis == "weak margins"
    assert state.final_decision == "HOLD"
    assert state.confidence == 0.0
    assert state.final_reasoning == ""
    assert state.errors == [
        "market: analysis failed",
        "unknown: analysis failed",
        "judge: analysis failed",
    ]
    assert len(quick.calls) == 3
    assert "current market conditions" in _user_content(quick.calls[0])
    assert "current news sentiment" in _user_content(quick.calls[1])
    assert "Past sentiment observations" not in _user_content(quick.calls[1])
    assert "fundamental outlook" in _user_content(quick.calls[2])
    assert len(deep.calls) == 1
