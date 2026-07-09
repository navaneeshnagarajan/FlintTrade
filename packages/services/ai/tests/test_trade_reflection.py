"""Tests for TradeReflector — automated batch trade reflection system.

All tests use the rule-based path (no LLM) to remain self-contained.
The LLM path is exercised via a lightweight mock in the async tests.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import threading
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from flinttrade_ai.llm_client import LLMResponse
from flinttrade_ai.memory import MemoryLayer
from flinttrade_ai.trade_reflection import (
    ReflectionConfig,
    ReflectionResult,
    TradeOutcome,
    TradeReflector,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trade(
    symbol: str = "NIFTY",
    action: str = "BUY",
    pnl_pct: float = 1.0,
    entry_price: float = 22000.0,
    exit_price: float = 22220.0,
    confidence: float | None = None,
    timestamp: str = "2026-04-09",
) -> dict[str, Any]:
    trade: dict[str, Any] = {
        "symbol": symbol,
        "action": action,
        "pnl_pct": pnl_pct,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "timestamp": timestamp,
    }
    if confidence is not None:
        trade["confidence"] = confidence
    return trade


def _make_trades(n: int, win: bool = True) -> list[dict[str, Any]]:
    return [_make_trade(pnl_pct=1.0 if win else -1.0) for _ in range(n)]


def _make_outcome(**overrides: Any) -> TradeOutcome:
    values: dict[str, Any] = {
        "symbol": "NIFTY",
        "exchange": "NSE_INDEX",
        "direction": "BUY",
        "entry_price": 22_000.0,
        "exit_price": 22_450.0,
        "quantity": 1,
        "pnl": 450.0,
        "pnl_pct": 2.05,
        "holding_period_days": 3,
        "analysis_summary": "Bullish PCR divergence.",
    }
    values.update(overrides)
    return TradeOutcome(**values)


@pytest.fixture
def reflector() -> TradeReflector:
    return TradeReflector(
        config=ReflectionConfig(
            trigger_every_n_trades=10,
            lookback_trades=20,
            min_trades_for_reflection=5,
        )
    )


# ---------------------------------------------------------------------------
# ReflectionConfig
# ---------------------------------------------------------------------------


class TestReflectionConfig:
    def test_defaults(self) -> None:
        cfg = ReflectionConfig()
        assert cfg.trigger_every_n_trades == 10
        assert cfg.lookback_trades == 20
        assert cfg.min_trades_for_reflection == 5

    def test_custom_values(self) -> None:
        cfg = ReflectionConfig(trigger_every_n_trades=5, lookback_trades=10)
        assert cfg.trigger_every_n_trades == 5
        assert cfg.lookback_trades == 10

    def test_trigger_must_be_positive(self) -> None:
        with pytest.raises(Exception):
            ReflectionConfig(trigger_every_n_trades=0)


# ---------------------------------------------------------------------------
# TradeReflector.should_reflect
# ---------------------------------------------------------------------------


class TestShouldReflect:
    def test_not_triggered_before_threshold(self, reflector: TradeReflector) -> None:
        assert reflector.should_reflect(5) is False

    def test_triggered_at_threshold(self, reflector: TradeReflector) -> None:
        assert reflector.should_reflect(10) is True

    def test_triggered_above_threshold(self, reflector: TradeReflector) -> None:
        assert reflector.should_reflect(15) is True

    def test_not_triggered_after_last_reflection(self) -> None:
        reflector = TradeReflector(config=ReflectionConfig(trigger_every_n_trades=5))
        # Simulate reflection having consumed 5 trades
        reflector._last_reflected_count = 5
        assert reflector.should_reflect(8) is False

    def test_triggered_when_gap_reaches_threshold(self) -> None:
        reflector = TradeReflector(config=ReflectionConfig(trigger_every_n_trades=5))
        reflector._last_reflected_count = 5
        assert reflector.should_reflect(10) is True


# ---------------------------------------------------------------------------
# TradeReflector.reflect (rule-based, async)
# ---------------------------------------------------------------------------


class TestReflectRuleBased:
    def test_reflect_remains_an_async_batch_entrypoint(self) -> None:
        assert inspect.iscoroutinefunction(TradeReflector.reflect)

    @pytest.mark.asyncio
    async def test_reflect_returns_result(self, reflector: TradeReflector) -> None:
        trades = _make_trades(10)
        result = await reflector.reflect(trades)
        assert result is not None
        assert isinstance(result, ReflectionResult)

    @pytest.mark.asyncio
    async def test_reflect_win_rate_all_wins(self, reflector: TradeReflector) -> None:
        trades = [_make_trade(pnl_pct=2.0) for _ in range(10)]
        result = await reflector.reflect(trades)
        assert result.win_rate == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_reflect_win_rate_all_losses(self, reflector: TradeReflector) -> None:
        trades = [_make_trade(pnl_pct=-2.0) for _ in range(10)]
        result = await reflector.reflect(trades)
        assert result.win_rate == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_reflect_avg_pnl_positive(self, reflector: TradeReflector) -> None:
        trades = [_make_trade(pnl_pct=3.0) for _ in range(10)]
        result = await reflector.reflect(trades)
        assert result.avg_pnl == pytest.approx(3.0)

    @pytest.mark.asyncio
    async def test_reflect_avg_pnl_negative(self, reflector: TradeReflector) -> None:
        trades = [_make_trade(pnl_pct=-1.5) for _ in range(10)]
        result = await reflector.reflect(trades)
        assert result.avg_pnl == pytest.approx(-1.5)

    @pytest.mark.asyncio
    async def test_reflect_winning_patterns_populated(self, reflector: TradeReflector) -> None:
        trades = [_make_trade(pnl_pct=2.0) for _ in range(10)]
        result = await reflector.reflect(trades)
        assert isinstance(result.winning_patterns, list)

    @pytest.mark.asyncio
    async def test_reflect_recommendations_non_empty(self, reflector: TradeReflector) -> None:
        trades = _make_trades(10, win=False)
        result = await reflector.reflect(trades)
        assert len(result.recommendations) >= 1

    @pytest.mark.asyncio
    async def test_reflect_too_few_trades_returns_none(self, reflector: TradeReflector) -> None:
        trades = _make_trades(2)
        result = await reflector.reflect(trades)
        assert result is None

    @pytest.mark.asyncio
    async def test_reflect_appends_to_history(self, reflector: TradeReflector) -> None:
        await reflector.reflect(_make_trades(10))
        assert len(reflector.get_history()) == 1
        await reflector.reflect(_make_trades(10))
        assert len(reflector.get_history()) == 2

    @pytest.mark.asyncio
    async def test_reflect_advances_last_count(self, reflector: TradeReflector) -> None:
        trades = _make_trades(10)
        await reflector.reflect(trades)
        assert reflector._last_reflected_count == 10

    @pytest.mark.asyncio
    async def test_confidence_calibration_in_result(self, reflector: TradeReflector) -> None:
        trades = [
            _make_trade(pnl_pct=2.0, confidence=0.9),
            _make_trade(pnl_pct=-1.0, confidence=0.3),
        ] * 5
        result = await reflector.reflect(trades)
        assert isinstance(result.confidence_calibration, str)
        assert len(result.confidence_calibration) > 0

    @pytest.mark.asyncio
    async def test_explicit_reflect_batch_matches_compatibility_alias(
        self,
        reflector: TradeReflector,
    ) -> None:
        explicit = await reflector.reflect_batch(_make_trades(10))
        compatibility = await reflector.reflect(_make_trades(10))

        assert explicit is not None
        assert compatibility is not None
        assert explicit.trades_analysed == compatibility.trades_analysed == 10


class TestReflectOne:
    @staticmethod
    def _make_reflector(lesson: str = "LESSON: Respect the opening range."):
        response = LLMResponse(content=lesson)
        llm = MagicMock()
        llm.chat.return_value = response
        memory = MagicMock()
        memory.add_memory.return_value = "reflection-memory-id"
        return TradeReflector(llm_client=llm, memory=memory), llm, memory

    def test_trade_outcome_is_exported_from_package_root(self) -> None:
        from flinttrade_ai import TradeOutcome as ExportedTradeOutcome

        assert ExportedTradeOutcome is TradeOutcome

    def test_legacy_positional_constructor_remains_available(self) -> None:
        _, llm, memory = self._make_reflector()

        reflector = TradeReflector(llm, memory)
        lesson = reflector.reflect_one(_make_outcome())

        assert lesson == "Respect the opening range."

    def test_reflect_one_strips_prefix_and_persists_lesson(self) -> None:
        reflector, _, memory = self._make_reflector()
        outcome = _make_outcome(symbol="BANKNIFTY")

        lesson = reflector.reflect_one(outcome, contributing_memory_ids=["source-memory"])

        assert lesson == "Respect the opening range."
        memory.add_memory.assert_called_once()
        call = memory.add_memory.call_args.kwargs
        assert call["symbol"] == "BANKNIFTY"
        assert call["text"] == lesson
        assert call["layer"] is MemoryLayer.REFLECTION
        memory.update_on_outcome.assert_called_once_with(
            memory_ids=["source-memory"],
            direction_correct=True,
        )

    def test_reflect_one_keeps_inr_prompt_and_trade_context(self) -> None:
        reflector, llm, _ = self._make_reflector()

        reflector.reflect_one(_make_outcome(pnl=-125.5, pnl_pct=-0.57))

        messages = llm.chat.call_args.args[0]
        prompt = next(message.content for message in messages if message.role == "user")
        assert "₹22000.00" in prompt
        assert "₹22450.00" in prompt
        assert "₹-125.50 (-0.6%)" in prompt
        assert "Bullish PCR divergence." in prompt

    def test_reflect_dispatches_trade_outcome_synchronously(self) -> None:
        reflector, _, _ = self._make_reflector("LESSON: Keep the stop mechanical.")

        result = reflector.reflect_one(_make_outcome())

        assert result == "Keep the stop mechanical."

    def test_reflect_one_requires_llm_and_memory(self) -> None:
        with pytest.raises(RuntimeError, match="LLM client"):
            TradeReflector(memory=MagicMock()).reflect_one(_make_outcome())
        with pytest.raises(RuntimeError, match="memory backend"):
            TradeReflector(llm_client=MagicMock()).reflect_one(_make_outcome())

    def test_reflect_one_rejects_failed_llm_response_without_writing(self) -> None:
        llm = MagicMock()
        llm.chat.return_value = LLMResponse(error="provider unavailable")
        memory = MagicMock()
        reflector = TradeReflector(llm_client=llm, memory=memory)

        with pytest.raises(RuntimeError, match="provider unavailable"):
            reflector.reflect_one(_make_outcome(), contributing_memory_ids=["source-memory"])

        memory.add_memory.assert_not_called()
        memory.update_on_outcome.assert_not_called()

    def test_reflect_one_rejects_prefix_only_response_without_writing(self) -> None:
        llm = MagicMock()
        llm.chat.return_value = LLMResponse(content="LESSON:   ")
        memory = MagicMock()
        reflector = TradeReflector(llm_client=llm, memory=memory)

        with pytest.raises(RuntimeError, match="empty response"):
            reflector.reflect_one(_make_outcome(), contributing_memory_ids=["source-memory"])

        memory.add_memory.assert_not_called()
        memory.update_on_outcome.assert_not_called()


# ---------------------------------------------------------------------------
# TradeReflector.get_reflection_prompt
# ---------------------------------------------------------------------------


class TestGetReflectionPrompt:
    def test_prompt_contains_table_header(self, reflector: TradeReflector) -> None:
        trades = _make_trades(5)
        prompt = reflector.get_reflection_prompt(trades)
        assert "Symbol" in prompt
        assert "PnL%" in prompt

    def test_prompt_contains_summary_stats(self, reflector: TradeReflector) -> None:
        trades = _make_trades(5)
        prompt = reflector.get_reflection_prompt(trades)
        assert "Win rate" in prompt or "win" in prompt.lower()

    def test_prompt_lists_all_trades(self, reflector: TradeReflector) -> None:
        trades = _make_trades(7)
        prompt = reflector.get_reflection_prompt(trades)
        assert "7 Trades" in prompt or "7" in prompt


# ---------------------------------------------------------------------------
# TradeReflector.format_for_prompt
# ---------------------------------------------------------------------------


class TestFormatForPrompt:
    @pytest.mark.asyncio
    async def test_empty_before_reflect(self, reflector: TradeReflector) -> None:
        assert reflector.format_for_prompt() == ""

    @pytest.mark.asyncio
    async def test_non_empty_after_reflect(self, reflector: TradeReflector) -> None:
        await reflector.reflect(_make_trades(10))
        output = reflector.format_for_prompt()
        assert len(output) > 0
        assert "[Trade Reflection" in output


# ---------------------------------------------------------------------------
# TradeReflector.latest
# ---------------------------------------------------------------------------


class TestLatest:
    def test_latest_none_before_reflect(self, reflector: TradeReflector) -> None:
        assert reflector.latest() is None

    @pytest.mark.asyncio
    async def test_latest_returns_most_recent(self, reflector: TradeReflector) -> None:
        await reflector.reflect(_make_trades(10))
        result = reflector.latest()
        assert result is not None
        assert result.trades_analysed == 10


# ---------------------------------------------------------------------------
# TradeReflector helpers: _extract_pnl and _extract_confidence
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_extract_pnl_pnl_pct_key(self) -> None:
        assert TradeReflector._extract_pnl({"pnl_pct": 2.5}) == pytest.approx(2.5)

    def test_extract_pnl_pnl_key(self) -> None:
        assert TradeReflector._extract_pnl({"pnl": -1.5}) == pytest.approx(-1.5)

    def test_extract_pnl_profit_key(self) -> None:
        assert TradeReflector._extract_pnl({"profit": 0.8}) == pytest.approx(0.8)

    def test_extract_pnl_missing_returns_zero(self) -> None:
        assert TradeReflector._extract_pnl({}) == 0.0

    def test_extract_pnl_non_numeric_returns_zero(self) -> None:
        assert TradeReflector._extract_pnl({"pnl_pct": "n/a"}) == 0.0

    def test_extract_confidence_confidence_key(self) -> None:
        assert TradeReflector._extract_confidence({"confidence": 0.85}) == pytest.approx(0.85)

    def test_extract_confidence_missing_returns_none(self) -> None:
        assert TradeReflector._extract_confidence({}) is None


# ---------------------------------------------------------------------------
# LLM path — mocked
# ---------------------------------------------------------------------------


class TestLLMPath:
    @pytest.mark.asyncio
    async def test_llm_result_parsed_correctly(self) -> None:
        llm_response = MagicMock()
        llm_response.content = json.dumps(
            {
                "summary": "10 trades, ok performance",
                "win_rate": 0.6,
                "avg_pnl": 1.2,
                "winning_patterns": ["Trend-aligned entries"],
                "losing_patterns": ["Counter-trend trades lost"],
                "recommendations": ["Tighten stops on counter-trend"],
                "confidence": 0.85,
                "market_insights": "Trending market",
                "confidence_calibration": "Well calibrated",
            }
        )

        mock_llm = MagicMock()
        mock_llm.chat = MagicMock(return_value=llm_response)

        reflector = TradeReflector(llm_client=mock_llm)
        trades = _make_trades(10)
        result = await reflector.reflect(trades)

        assert result is not None
        assert result.win_rate == pytest.approx(0.6)
        assert result.avg_pnl == pytest.approx(1.2)
        assert "Trend-aligned entries" in result.winning_patterns

    @pytest.mark.asyncio
    async def test_llm_invalid_json_falls_back_to_rules(self) -> None:
        llm_response = MagicMock()
        llm_response.content = "not valid json at all"

        mock_llm = MagicMock()
        mock_llm.chat = MagicMock(return_value=llm_response)

        reflector = TradeReflector(llm_client=mock_llm)
        trades = _make_trades(10)
        result = await reflector.reflect(trades)

        # Should still return a result via rule fallback
        assert result is not None
        assert isinstance(result, ReflectionResult)

    @pytest.mark.asyncio
    async def test_llm_exception_falls_back_to_rules(self) -> None:
        mock_llm = MagicMock()
        mock_llm.chat = MagicMock(side_effect=RuntimeError("LLM unavailable"))

        reflector = TradeReflector(llm_client=mock_llm)
        trades = _make_trades(10)
        result = await reflector.reflect(trades)

        assert result is not None
        assert isinstance(result, ReflectionResult)

    @pytest.mark.asyncio
    async def test_llm_call_does_not_block_the_event_loop(self) -> None:
        llm_response = MagicMock()
        llm_response.content = json.dumps({"win_rate": 0.5, "avg_pnl": 0.1})
        chat_started = threading.Event()
        release_chat = threading.Event()
        chat_finished_at = 0.0

        def blocking_chat(_messages: list[Any]) -> MagicMock:
            nonlocal chat_finished_at
            chat_started.set()
            release_chat.wait(timeout=0.5)
            chat_finished_at = time.monotonic()
            return llm_response

        mock_llm = MagicMock()
        mock_llm.chat.side_effect = blocking_chat
        reflector = TradeReflector(llm_client=mock_llm)
        heartbeat_at = 0.0

        async def heartbeat() -> None:
            nonlocal heartbeat_at
            while not chat_started.is_set():
                await asyncio.sleep(0)
            heartbeat_at = time.monotonic()
            release_chat.set()

        result, _ = await asyncio.wait_for(
            asyncio.gather(reflector.reflect(_make_trades(10)), heartbeat()),
            timeout=2,
        )

        assert result is not None
        assert heartbeat_at < chat_finished_at

    @pytest.mark.asyncio
    async def test_numeric_string_prices_still_reach_rule_fallback(self) -> None:
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = RuntimeError("LLM unavailable")
        reflector = TradeReflector(llm_client=mock_llm)
        trades = _make_trades(10)
        for trade in trades:
            trade["entry_price"] = "22000.50"
            trade["exit_price"] = "22100.75"

        result = await reflector.reflect(trades)

        assert result is not None
        assert isinstance(result, ReflectionResult)
