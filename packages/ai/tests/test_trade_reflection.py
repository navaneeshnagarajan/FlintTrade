"""Tests for TradeReflector — automated batch trade reflection system.

All tests use the rule-based path (no LLM) to remain self-contained.
The LLM path is exercised via a lightweight mock in the async tests.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from packages.ai.src.trade_reflection import (
    ReflectionConfig,
    ReflectionResult,
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


@pytest.fixture
def reflector() -> TradeReflector:
    return TradeReflector(config=ReflectionConfig(
        trigger_every_n_trades=10,
        lookback_trades=20,
        min_trades_for_reflection=5,
    ))


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
        llm_response.content = json.dumps({
            "summary": "10 trades, ok performance",
            "win_rate": 0.6,
            "avg_pnl": 1.2,
            "winning_patterns": ["Trend-aligned entries"],
            "losing_patterns": ["Counter-trend trades lost"],
            "recommendations": ["Tighten stops on counter-trend"],
            "confidence": 0.85,
            "market_insights": "Trending market",
            "confidence_calibration": "Well calibrated",
        })

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
