"""Tests for TradeReflector — post-trade lesson extraction and memory storage.

All LLMClient and TradedMemory calls are mocked. No network or disk I/O.

Pattern: Arrange-Act-Assert throughout.
"""

from __future__ import annotations

from dataclasses import fields
from unittest.mock import MagicMock

import pytest

from flinttrade_ai.llm_client import LLMResponse
from flinttrade_ai.memory import MemoryLayer
from flinttrade_ai.reflection import TradeOutcome, TradeReflector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_outcome(**overrides) -> TradeOutcome:
    """Return a baseline TradeOutcome with optional field overrides."""
    defaults = dict(
        symbol="NIFTY",
        exchange="NSE_INDEX",
        direction="BUY",
        entry_price=22_000.0,
        exit_price=22_450.0,
        quantity=1,
        pnl=450.0,
        pnl_pct=2.05,
        holding_period_days=3,
        analysis_summary="Bullish PCR divergence with OI buildup at 22000 CE.",
    )
    defaults.update(overrides)
    return TradeOutcome(**defaults)


def make_reflector(llm_response_text: str = "LESSON: Hold winners longer."):
    """Return a (reflector, mock_llm, mock_memory) triple.

    The mock LLM's chat() returns an LLMResponse whose content is
    ``llm_response_text``.  The mock memory's add_memory() returns a fixed UUID.
    """
    mock_llm = MagicMock()
    mock_llm.chat.return_value = LLMResponse(content=llm_response_text)

    mock_memory = MagicMock()
    mock_memory.add_memory.return_value = "test-uuid-1234"

    reflector = TradeReflector(llm_client=mock_llm, memory=mock_memory)
    return reflector, mock_llm, mock_memory


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTradeOutcomeDataclass:
    """Verify TradeOutcome is a proper dataclass with expected fields."""

    def test_outcome_dataclass_fields(self):
        """TradeOutcome must expose all required fields via dataclass introspection."""
        # Arrange
        field_names = {f.name for f in fields(TradeOutcome)}
        required = {
            "symbol", "exchange", "direction",
            "entry_price", "exit_price", "quantity",
            "pnl", "pnl_pct", "holding_period_days", "analysis_summary",
        }

        # Act / Assert
        assert required.issubset(field_names), (
            f"Missing fields: {required - field_names}"
        )

    def test_outcome_analysis_summary_defaults_to_empty_string(self):
        """analysis_summary should default to empty string so it is optional."""
        # Arrange / Act
        outcome = TradeOutcome(
            symbol="RELIANCE", exchange="NSE", direction="SELL",
            entry_price=2900.0, exit_price=2850.0,
            quantity=10, pnl=-500.0, pnl_pct=-1.72,
            holding_period_days=1,
        )
        # Assert
        assert outcome.analysis_summary == ""


class TestReflectReturnsLesson:
    """reflect() must return the lesson string from the LLM."""

    def test_reflect_returns_lesson_string(self):
        """reflect() returns a non-empty string derived from LLM content."""
        # Arrange
        reflector, _, _ = make_reflector("LESSON: Always use stop-losses.")
        outcome = make_outcome()

        # Act
        result = reflector.reflect(outcome)

        # Assert
        assert isinstance(result, str)
        assert len(result) > 0

    def test_reflect_strips_lesson_prefix(self):
        """reflect() removes the 'LESSON:' prefix from the LLM response."""
        # Arrange
        reflector, _, _ = make_reflector("LESSON: Hold winners longer.")
        outcome = make_outcome()

        # Act
        result = reflector.reflect(outcome)

        # Assert
        assert result == "Hold winners longer."
        assert not result.startswith("LESSON:")

    def test_reflect_strips_lesson_prefix_with_extra_whitespace(self):
        """reflect() strips both the prefix and any surrounding whitespace."""
        # Arrange
        reflector, _, _ = make_reflector("LESSON:   Trim positions before expiry.  ")
        outcome = make_outcome()

        # Act
        result = reflector.reflect(outcome)

        # Assert
        assert result == "Trim positions before expiry."

    def test_reflect_handles_response_without_lesson_prefix(self):
        """reflect() returns the response as-is when 'LESSON:' prefix is absent."""
        # Arrange
        reflector, _, _ = make_reflector("Watch the open interest more carefully.")
        outcome = make_outcome()

        # Act
        result = reflector.reflect(outcome)

        # Assert
        assert result == "Watch the open interest more carefully."


class TestReflectStoresInMemory:
    """reflect() must persist the lesson in the REFLECTION memory layer."""

    def test_reflect_stores_in_reflection_layer(self):
        """add_memory() is called with MemoryLayer.REFLECTION."""
        # Arrange
        reflector, _, mock_memory = make_reflector("LESSON: Size down in low VIX.")
        outcome = make_outcome()

        # Act
        reflector.reflect(outcome)

        # Assert
        mock_memory.add_memory.assert_called_once()
        _, kwargs = mock_memory.add_memory.call_args
        # accept both positional and keyword call styles
        call_args, call_kwargs = mock_memory.add_memory.call_args
        layer_arg = call_kwargs.get("layer") or call_args[2]
        assert layer_arg == MemoryLayer.REFLECTION

    def test_reflect_stores_with_correct_symbol(self):
        """add_memory() is called with the same symbol as the outcome."""
        # Arrange
        reflector, _, mock_memory = make_reflector("LESSON: Check OI before entry.")
        outcome = make_outcome(symbol="BANKNIFTY")

        # Act
        reflector.reflect(outcome)

        # Assert
        call_args, call_kwargs = mock_memory.add_memory.call_args
        symbol_arg = call_kwargs.get("symbol") or call_args[0]
        assert symbol_arg == "BANKNIFTY"


class TestReflectMetadata:
    """Verify the metadata dict stored alongside the reflection memory."""

    def _get_metadata(self, mock_memory: MagicMock) -> dict:
        """Extract the metadata kwarg from the last add_memory() call."""
        call_args, call_kwargs = mock_memory.add_memory.call_args
        return call_kwargs.get("metadata") or (call_args[3] if len(call_args) > 3 else {})

    def test_reflect_metadata_includes_direction(self):
        """Stored metadata must contain the trade direction."""
        # Arrange
        reflector, _, mock_memory = make_reflector("LESSON: Follow momentum.")
        outcome = make_outcome(direction="SELL")

        # Act
        reflector.reflect(outcome)
        metadata = self._get_metadata(mock_memory)

        # Assert
        assert metadata.get("direction") == "SELL"

    def test_reflect_metadata_includes_pnl_pct(self):
        """Stored metadata must contain the pnl_pct value."""
        # Arrange
        reflector, _, mock_memory = make_reflector("LESSON: Watch IV rank.")
        outcome = make_outcome(pnl_pct=-3.5)

        # Act
        reflector.reflect(outcome)
        metadata = self._get_metadata(mock_memory)

        # Assert
        assert metadata.get("pnl_pct") == pytest.approx(-3.5)

    def test_reflect_metadata_includes_holding_days(self):
        """Stored metadata must contain holding_days."""
        # Arrange
        reflector, _, mock_memory = make_reflector("LESSON: Exit before expiry week.")
        outcome = make_outcome(holding_period_days=7)

        # Act
        reflector.reflect(outcome)
        metadata = self._get_metadata(mock_memory)

        # Assert
        assert metadata.get("holding_days") == 7

    def test_reflect_metadata_includes_exchange(self):
        """Stored metadata must contain the exchange."""
        # Arrange
        reflector, _, mock_memory = make_reflector("LESSON: Use limit orders on BSE.")
        outcome = make_outcome(exchange="BSE")

        # Act
        reflector.reflect(outcome)
        metadata = self._get_metadata(mock_memory)

        # Assert
        assert metadata.get("exchange") == "BSE"


class TestReflectPromptContent:
    """Verify the prompt passed to the LLM contains required trade information."""

    def _get_user_message_content(self, mock_llm: MagicMock) -> str:
        """Extract the user-role message content from the chat() call."""
        messages = mock_llm.chat.call_args[0][0]
        user_messages = [m for m in messages if m.role == "user"]
        assert user_messages, "No user message found in LLM call"
        return user_messages[0].content

    def test_reflect_includes_pnl_in_prompt(self):
        """The user prompt must include the P&L value."""
        # Arrange
        reflector, mock_llm, _ = make_reflector()
        outcome = make_outcome(pnl=450.0, pnl_pct=2.05)

        # Act
        reflector.reflect(outcome)
        content = self._get_user_message_content(mock_llm)

        # Assert
        assert "450.00" in content
        assert "+2.1" in content or "2.05" in content or "+2.0" in content

    def test_reflect_includes_symbol_in_prompt(self):
        """The user prompt must include the instrument symbol."""
        # Arrange
        reflector, mock_llm, _ = make_reflector()
        outcome = make_outcome(symbol="RELIANCE")

        # Act
        reflector.reflect(outcome)
        content = self._get_user_message_content(mock_llm)

        # Assert
        assert "RELIANCE" in content

    def test_reflect_includes_direction_in_prompt(self):
        """The user prompt must include the trade direction."""
        # Arrange
        reflector, mock_llm, _ = make_reflector()
        outcome = make_outcome(direction="SELL")

        # Act
        reflector.reflect(outcome)
        content = self._get_user_message_content(mock_llm)

        # Assert
        assert "SELL" in content

    def test_reflect_includes_holding_period_in_prompt(self):
        """The user prompt must reference the holding period."""
        # Arrange
        reflector, mock_llm, _ = make_reflector()
        outcome = make_outcome(holding_period_days=14)

        # Act
        reflector.reflect(outcome)
        content = self._get_user_message_content(mock_llm)

        # Assert
        assert "14" in content

    def test_reflect_handles_no_analysis_summary(self):
        """When analysis_summary is empty, the prompt includes a fallback message."""
        # Arrange
        reflector, mock_llm, _ = make_reflector()
        outcome = make_outcome(analysis_summary="")

        # Act
        reflector.reflect(outcome)
        content = self._get_user_message_content(mock_llm)

        # Assert
        assert "No analysis recorded" in content

    def test_reflect_includes_analysis_summary_when_provided(self):
        """When analysis_summary is set, it appears verbatim in the prompt."""
        # Arrange
        reflector, mock_llm, _ = make_reflector()
        summary = "Bearish engulfing on daily timeframe with volume surge."
        outcome = make_outcome(analysis_summary=summary)

        # Act
        reflector.reflect(outcome)
        content = self._get_user_message_content(mock_llm)

        # Assert
        assert summary in content

    def test_reflect_sends_system_message(self):
        """The LLM call must include a system-role message."""
        # Arrange
        reflector, mock_llm, _ = make_reflector()
        outcome = make_outcome()

        # Act
        reflector.reflect(outcome)
        messages = mock_llm.chat.call_args[0][0]

        # Assert
        system_messages = [m for m in messages if m.role == "system"]
        assert len(system_messages) == 1
        assert len(system_messages[0].content) > 0


class TestReflectContributingMemories:
    """reflect() should optionally reinforce contributing memories."""

    def test_reflect_calls_update_on_outcome_when_ids_provided(self):
        """update_on_outcome() is called when contributing_memory_ids are given."""
        # Arrange
        reflector, _, mock_memory = make_reflector()
        outcome = make_outcome(pnl=200.0)
        ids = ["uuid-a", "uuid-b"]

        # Act
        reflector.reflect(outcome, contributing_memory_ids=ids)

        # Assert
        mock_memory.update_on_outcome.assert_called_once_with(
            memory_ids=ids, direction_correct=True
        )

    def test_reflect_marks_direction_correct_for_profitable_trade(self):
        """A profitable trade (pnl > 0) should pass direction_correct=True."""
        # Arrange
        reflector, _, mock_memory = make_reflector()
        outcome = make_outcome(pnl=100.0)
        ids = ["uuid-x"]

        # Act
        reflector.reflect(outcome, contributing_memory_ids=ids)

        # Assert
        _, kwargs = mock_memory.update_on_outcome.call_args
        assert kwargs["direction_correct"] is True

    def test_reflect_marks_direction_incorrect_for_losing_trade(self):
        """A losing trade (pnl < 0) should pass direction_correct=False."""
        # Arrange
        reflector, _, mock_memory = make_reflector()
        outcome = make_outcome(pnl=-250.0)
        ids = ["uuid-y"]

        # Act
        reflector.reflect(outcome, contributing_memory_ids=ids)

        # Assert
        _, kwargs = mock_memory.update_on_outcome.call_args
        assert kwargs["direction_correct"] is False

    def test_reflect_skips_update_on_outcome_when_no_ids(self):
        """update_on_outcome() must NOT be called when contributing_memory_ids is None."""
        # Arrange
        reflector, _, mock_memory = make_reflector()
        outcome = make_outcome()

        # Act
        reflector.reflect(outcome)

        # Assert
        mock_memory.update_on_outcome.assert_not_called()
