"""Post-trade reflection loop for extracting and storing trading lessons.

Adapts TradingAgents reflection.py pattern: after a trade closes, the LLM
reviews the original analysis alongside the actual outcome, extracts a
concise actionable lesson, and stores it in the REFLECTION layer of
TradedMemory so future analysis can benefit from accumulated experience.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .llm_client import LLMClient, LLMMessage
from .memory import MemoryLayer, TradedMemory

logger = logging.getLogger("flinttrade.ai.reflection")

_LESSON_PREFIX = "LESSON:"
_SYSTEM_PROMPT = (
    "You are a disciplined trading coach who specialises in post-trade analysis "
    "for Indian F&O and equity markets. Extract clear, actionable lessons from "
    "completed trades. Be concise and specific. Avoid generalities."
)


@dataclass
class TradeOutcome:
    """A closed trade's summary used as input to the reflection loop.

    Attributes:
        symbol: Instrument symbol (e.g. "NIFTY", "RELIANCE").
        exchange: Exchange identifier (e.g. "NSE", "BSE", "NSE_INDEX").
        direction: Trade direction — "BUY" or "SELL".
        entry_price: Price at which the position was opened.
        exit_price: Price at which the position was closed.
        quantity: Number of units/lots traded.
        pnl: Absolute profit or loss in INR (negative for a loss).
        pnl_pct: P&L as a percentage of the entry value (e.g. +2.5 or -1.3).
        holding_period_days: Number of calendar days the position was held.
        analysis_summary: Optional free-text of the original analysis or
            reasoning that led to the trade. Used by the LLM to compare
            intent vs outcome.
    """

    symbol: str
    exchange: str
    direction: str  # "BUY" or "SELL"
    entry_price: float
    exit_price: float
    quantity: int
    pnl: float
    pnl_pct: float
    holding_period_days: int
    analysis_summary: str = ""


class TradeReflector:
    """Post-trade reflection loop.

    Adapts TradingAgents pattern: after a trade closes, an LLM reviews the
    original analysis together with the actual outcome, extracts a lesson, and
    stores it in TradedMemory's REFLECTION layer.  The lesson is also used to
    reinforce or weaken the importance of memories that contributed to the
    original analysis.

    Usage::

        llm = LLMClient()
        memory = TradedMemory()
        reflector = TradeReflector(llm, memory)

        outcome = TradeOutcome(
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
        lesson = reflector.reflect(outcome)
        print(lesson)
    """

    def __init__(self, llm_client: LLMClient, memory: TradedMemory) -> None:
        """Initialise the reflector.

        Args:
            llm_client: Configured LLMClient instance used to generate lessons.
            memory: TradedMemory instance where lessons will be persisted.
        """
        self._llm = llm_client
        self._memory = memory

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reflect(
        self,
        outcome: TradeOutcome,
        contributing_memory_ids: list[str] | None = None,
    ) -> str:
        """Generate and store a trading lesson from a completed trade.

        Sends the trade details and original analysis to the LLM, strips the
        "LESSON:" prefix from the response, persists the lesson in the
        REFLECTION memory layer, and optionally reinforces or weakens any
        contributing memories based on whether the trade was profitable.

        Args:
            outcome: The closed trade's summary.
            contributing_memory_ids: Optional list of memory UUIDs that
                influenced the original analysis. If provided, their importance
                scores are updated via ``update_on_outcome``.

        Returns:
            The extracted lesson string (prefix stripped, whitespace trimmed).
        """
        messages = self._build_messages(outcome)
        response = self._llm.chat(messages)

        lesson = response.content.strip()
        if lesson.startswith(_LESSON_PREFIX):
            lesson = lesson[len(_LESSON_PREFIX):].strip()

        memory_id = self._memory.add_memory(
            symbol=outcome.symbol,
            text=lesson,
            layer=MemoryLayer.REFLECTION,
            metadata=self._build_metadata(outcome),
        )

        direction_correct = outcome.pnl > 0

        if contributing_memory_ids:
            self._memory.update_on_outcome(
                memory_ids=contributing_memory_ids,
                direction_correct=direction_correct,
            )

        logger.info(
            "Reflection stored: symbol=%s direction=%s pnl_pct=%.1f%% memory_id=%s",
            outcome.symbol,
            outcome.direction,
            outcome.pnl_pct,
            memory_id,
        )
        return lesson

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_messages(self, outcome: TradeOutcome) -> list[LLMMessage]:
        """Construct the LLM message list for a reflection request.

        Args:
            outcome: The closed trade's summary.

        Returns:
            A two-element list: system prompt + user prompt.
        """
        analysis_block = outcome.analysis_summary or "No analysis recorded"

        user_content = (
            f"Review this completed trade and extract a lesson.\n\n"
            f"TRADE DETAILS:\n"
            f"- Symbol: {outcome.symbol} ({outcome.exchange})\n"
            f"- Direction: {outcome.direction}\n"
            f"- Entry: \u20b9{outcome.entry_price:.2f} \u2192 "
            f"Exit: \u20b9{outcome.exit_price:.2f}\n"
            f"- Quantity: {outcome.quantity}\n"
            f"- P&L: \u20b9{outcome.pnl:.2f} ({outcome.pnl_pct:+.1f}%)\n"
            f"- Holding Period: {outcome.holding_period_days} day(s)\n\n"
            f"ORIGINAL ANALYSIS:\n{analysis_block}\n\n"
            f"TASK: In 100 words or less, extract ONE specific actionable lesson. "
            f"Focus on what was correct and what should be done differently next time.\n"
            f"Start with \"{_LESSON_PREFIX}\""
        )

        return [
            LLMMessage(role="system", content=_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_content),
        ]

    def _build_metadata(self, outcome: TradeOutcome) -> dict[str, Any]:
        """Construct the metadata dict stored alongside the reflection memory.

        Args:
            outcome: The closed trade's summary.

        Returns:
            A flat dict of scalar values compatible with ChromaDB metadata.
        """
        return {
            "direction": outcome.direction,
            "pnl": outcome.pnl,
            "pnl_pct": outcome.pnl_pct,
            "holding_days": outcome.holding_period_days,
            "exchange": outcome.exchange,
            "entry_price": outcome.entry_price,
            "exit_price": outcome.exit_price,
            "quantity": outcome.quantity,
        }
