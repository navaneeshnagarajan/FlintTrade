"""Multi-agent analysis pipeline for FlintTrade AI.

Absorbs TradingAgents pattern: a typed ``AnalysisState`` flows sequentially
through analyst nodes, each calling ``LLMClient`` with a structured prompt
and writing its report back to the shared state.  No LangGraph — pure Python
state machine.

Two-tier LLM strategy:
- ``quick_llm`` — used by all analyst nodes (fast, lower-cost model).
- ``deep_llm`` — used by the judge node for the final decision (optional;
  falls back to ``quick_llm`` when not provided).

Usage::

    from packages.ai.src.llm_client import LLMClient, LLMConfig
    from packages.ai.src.analyst_chain import AnalystChain

    client = LLMClient(config=LLMConfig.from_env())
    chain = AnalystChain(llm_client=client, analysts=["market", "sentiment"])
    state = chain.analyse("NIFTY", "NSE_INDEX")
    print(state.final_decision, state.confidence)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from .llm_client import LLMClient, LLMMessage
from .memory import MemoryLayer, TradedMemory

logger = logging.getLogger("flinttrade.ai.analyst_chain")

# Literal type alias used only at the annotation level; kept as a plain str
# alias so the module stays importable without TypeAlias (Python 3.10+).
DecisionLiteral = str  # "BUY" | "SELL" | "HOLD"

_VALID_DECISIONS = frozenset({"BUY", "SELL", "HOLD"})


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------


@dataclass
class AnalysisState:
    """Shared state flowing through the analyst chain.

    Each analyst node reads from this state (for context) and writes its
    report back.  The judge node reads all reports and produces the final
    decision fields.

    Attributes:
        symbol: Instrument symbol being analysed (e.g. "NIFTY").
        exchange: Exchange code (e.g. "NSE_INDEX", "NFO", "NSE").
        trade_date: Date for which the analysis is performed.
        market_report: Output of the market analyst node.
        sentiment_report: Output of the sentiment analyst node.
        bull_thesis: Output of the bull-thesis analyst node (future use).
        bear_thesis: Output of the bear-thesis analyst node (future use).
        risk_assessment: Output of the risk analyst node (future use).
        final_decision: "BUY", "SELL", or "HOLD" — set by the judge node.
        final_reasoning: Judge's plain-text reasoning (2-3 sentences).
        confidence: Parsed judge confidence score clamped to [0.0, 1.0].
        errors: List of ``"analyst_name: error message"`` strings for any
            node that raised an exception during analysis.
    """

    symbol: str
    exchange: str
    trade_date: date
    market_report: str = ""
    sentiment_report: str = ""
    bull_thesis: str = ""
    bear_thesis: str = ""
    risk_assessment: str = ""
    final_decision: DecisionLiteral = "HOLD"
    final_reasoning: str = ""
    confidence: float = 0.0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# AnalystChain
# ---------------------------------------------------------------------------


class AnalystChain:
    """Sequential multi-agent analysis pipeline.

    Absorbs TradingAgents pattern: typed state flows through analyst nodes.
    Each node calls LLMClient with a structured prompt and writes its report
    to the shared state.  No LangGraph — pure Python state machine.

    Two-tier LLM: ``quick_llm`` for analyst nodes, ``deep_llm`` for the
    judge node (optional; falls back to ``quick_llm``).

    Supported analyst names: ``"market"``, ``"sentiment"``,
    ``"fundamentals"``.  Unknown names raise ``ValueError`` at ``analyse``
    time (captured into ``state.errors``).

    Args:
        llm_client: Primary LLM client used for all analyst nodes.
        deep_llm_client: Optional secondary client for the judge node.
            When ``None`` the judge reuses ``llm_client``.
        memory: Optional ``TradedMemory`` for enriching the sentiment
            analyst with past observations.
        analysts: Ordered list of analyst names to run.  Defaults to
            ``["market", "sentiment"]``.

    Example::

        chain = AnalystChain(
            llm_client=fast_client,
            deep_llm_client=powerful_client,
            analysts=["market", "sentiment", "fundamentals"],
        )
        state = chain.analyse("RELIANCE", "NSE")
        print(state.final_decision)  # "BUY" | "SELL" | "HOLD"
    """

    def __init__(
        self,
        llm_client: LLMClient,
        deep_llm_client: LLMClient | None = None,
        memory: TradedMemory | None = None,
        analysts: list[str] | None = None,
    ) -> None:
        self._quick = llm_client
        self._deep = deep_llm_client or llm_client
        self._memory = memory
        self._analysts: list[str] = analysts if analysts is not None else ["market", "sentiment"]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyse(
        self,
        symbol: str,
        exchange: str,
        trade_date: date | None = None,
    ) -> AnalysisState:
        """Run the full analyst chain for a symbol and return the state.

        Executes each enabled analyst node in order, collects errors
        non-fatally, then always runs the judge node to produce a
        final decision.

        Args:
            symbol: Instrument symbol (e.g. "NIFTY", "RELIANCE").
            exchange: Exchange code (e.g. "NSE_INDEX", "NSE", "NFO").
            trade_date: Date for the analysis.  Defaults to ``date.today()``.

        Returns:
            A fully-populated ``AnalysisState`` instance.  Check
            ``state.errors`` for any per-node failures.
        """
        state = AnalysisState(
            symbol=symbol,
            exchange=exchange,
            trade_date=trade_date or date.today(),
        )

        for name in self._analysts:
            try:
                node = self._get_node(name)
                node(state)
            except Exception as exc:  # noqa: BLE001
                error_msg = f"{name}: {exc}"
                state.errors.append(error_msg)
                logger.warning("Analyst node '%s' failed: %s", name, exc)

        # Judge always runs — uses deep LLM
        try:
            self._judge_node(state)
        except Exception as exc:  # noqa: BLE001
            state.errors.append(f"judge: {exc}")
            logger.warning("Judge node failed: %s", exc)

        return state

    # ------------------------------------------------------------------
    # Node registry
    # ------------------------------------------------------------------

    def _get_node(self, name: str) -> Callable[[AnalysisState], None]:
        """Return the analyst callable for a given name.

        Args:
            name: Analyst identifier string.

        Returns:
            Callable that accepts an ``AnalysisState`` and mutates it.

        Raises:
            ValueError: If ``name`` is not a recognised analyst.
        """
        nodes: dict[str, Callable[[AnalysisState], None]] = {
            "market": self._market_analyst,
            "sentiment": self._sentiment_analyst,
            "fundamentals": self._fundamentals_analyst,
        }
        if name not in nodes:
            raise ValueError(
                f"Unknown analyst '{name}'. "
                f"Valid options: {sorted(nodes.keys())}"
            )
        return nodes[name]

    # ------------------------------------------------------------------
    # Analyst nodes
    # ------------------------------------------------------------------

    def _market_analyst(self, state: AnalysisState) -> None:
        """Analyse price action, volume, and technical indicators.

        Writes a concise market report (trend direction, key support /
        resistance levels, volume, notable patterns) to
        ``state.market_report``.

        Args:
            state: Shared analysis state; mutated in place.
        """
        messages = [
            LLMMessage(
                role="system",
                content=(
                    "You are a technical market analyst specialising in Indian equity "
                    "and derivatives markets.  Be concise and data-driven."
                ),
            ),
            LLMMessage(
                role="user",
                content=(
                    f"Analyse the current market conditions for {state.symbol} "
                    f"on {state.exchange}.\n"
                    f"Date: {state.trade_date}\n"
                    "Provide a concise market report covering: trend direction, "
                    "key support/resistance levels, volume analysis, and any notable "
                    "technical patterns.  Keep under 200 words."
                ),
            ),
        ]
        response = self._quick.chat(messages)
        state.market_report = response.content
        logger.debug("Market report for %s: %d chars", state.symbol, len(response.content))

    def _sentiment_analyst(self, state: AnalysisState) -> None:
        """Analyse news sentiment, optionally enriched with memory context.

        When ``self._memory`` is available, the two most relevant past
        sentiment observations for the symbol are prepended to the prompt.
        Writes to ``state.sentiment_report``.

        Args:
            state: Shared analysis state; mutated in place.
        """
        memory_context = ""
        if self._memory is not None:
            try:
                result = self._memory.get_memories(
                    state.symbol,
                    f"sentiment for {state.symbol}",
                    MemoryLayer.SHORT,
                    n=2,
                )
                if result.items:
                    lines = "\n".join(f"- {item.text}" for item in result.items)
                    memory_context = f"\nPast sentiment observations:\n{lines}"
            except Exception as exc:  # noqa: BLE001
                logger.warning("Memory retrieval failed for sentiment node: %s", exc)

        messages = [
            LLMMessage(
                role="system",
                content=(
                    "You are a financial news sentiment analyst covering Indian markets. "
                    "Be concise and evidence-based."
                ),
            ),
            LLMMessage(
                role="user",
                content=(
                    f"Analyse the current news sentiment for {state.symbol}."
                    f"{memory_context}\n"
                    "Provide a concise sentiment report: overall sentiment "
                    "(bullish/bearish/neutral), key news drivers, and any sentiment "
                    "shifts.  Keep under 200 words."
                ),
            ),
        ]
        response = self._quick.chat(messages)
        state.sentiment_report = response.content
        logger.debug(
            "Sentiment report for %s: %d chars", state.symbol, len(response.content)
        )

    def _fundamentals_analyst(self, state: AnalysisState) -> None:
        """Analyse fundamental valuation metrics and earnings quality.

        Writes to ``state.bull_thesis`` (positive fundamentals) and
        ``state.bear_thesis`` (fundamental risks).  Both are populated in a
        single LLM call and split at the BEAR marker.

        Args:
            state: Shared analysis state; mutated in place.
        """
        messages = [
            LLMMessage(
                role="system",
                content=(
                    "You are a fundamental equity analyst covering Indian markets. "
                    "Evaluate valuation, growth, and balance-sheet quality concisely."
                ),
            ),
            LLMMessage(
                role="user",
                content=(
                    f"Analyse the fundamental outlook for {state.symbol} ({state.exchange}).\n"
                    f"Date: {state.trade_date}\n"
                    "Respond in EXACTLY this format:\n"
                    "BULL: [key fundamental strengths, under 100 words]\n"
                    "BEAR: [key fundamental risks, under 100 words]"
                ),
            ),
        ]
        response = self._quick.chat(messages)
        content = response.content

        # Split bull / bear from the structured response
        bull = ""
        bear = ""
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("BULL:"):
                bull = stripped.split(":", 1)[1].strip()
            elif stripped.upper().startswith("BEAR:"):
                bear = stripped.split(":", 1)[1].strip()

        state.bull_thesis = bull or content
        state.bear_thesis = bear
        logger.debug("Fundamentals for %s: bull=%d chars", state.symbol, len(bull))

    # ------------------------------------------------------------------
    # Judge node
    # ------------------------------------------------------------------

    def _judge_node(self, state: AnalysisState) -> None:
        """Synthesise analyst reports into a final trading decision.

        Uses ``self._deep`` (the deep LLM client) for higher-quality
        reasoning.  Parses a structured response to populate
        ``state.final_decision``, ``state.confidence``, and
        ``state.final_reasoning``.

        Args:
            state: Shared analysis state; mutated in place.
        """
        report_sections: list[str] = []
        if state.market_report:
            report_sections.append(f"MARKET ANALYSIS:\n{state.market_report}")
        if state.sentiment_report:
            report_sections.append(f"SENTIMENT ANALYSIS:\n{state.sentiment_report}")
        if state.bull_thesis:
            report_sections.append(f"BULL THESIS:\n{state.bull_thesis}")
        if state.bear_thesis:
            report_sections.append(f"BEAR THESIS:\n{state.bear_thesis}")

        combined = "\n\n".join(report_sections) if report_sections else "(no analyst reports available)"

        messages = [
            LLMMessage(
                role="system",
                content=(
                    "You are the final decision maker for a trading system. "
                    "Synthesise the analyst reports and provide a clear, well-reasoned "
                    "trading decision.  Follow the output format exactly."
                ),
            ),
            LLMMessage(
                role="user",
                content=(
                    f"You are the final decision maker for {state.symbol} ({state.exchange}).\n"
                    f"Based on the following analyst reports, provide your trading decision.\n\n"
                    f"{combined}\n\n"
                    "Respond in EXACTLY this format:\n"
                    "DECISION: [BUY/SELL/HOLD]\n"
                    "CONFIDENCE: [0.0-1.0]\n"
                    "REASONING: [2-3 sentences explaining why]"
                ),
            ),
        ]
        response = self._deep.chat(messages)
        decision, confidence, reasoning = self._parse_judge_response(response.content)
        state.final_decision = decision
        state.confidence = confidence
        state.final_reasoning = reasoning
        logger.debug(
            "Judge decision for %s: %s (confidence=%.2f)",
            state.symbol,
            decision,
            confidence,
        )

    # ------------------------------------------------------------------
    # Parsing helper
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_judge_response(response: str) -> tuple[DecisionLiteral, float, str]:
        """Extract decision, confidence, and reasoning from judge output.

        Parses the structured three-line format produced by the judge
        prompt.  Falls back gracefully on malformed output:
        - Missing DECISION → "HOLD"
        - Missing / invalid CONFIDENCE → 0.0
        - Missing REASONING → full response text

        Confidence is always clamped to [0.0, 1.0].

        Args:
            response: Raw string returned by the judge LLM call.

        Returns:
            A three-tuple ``(decision, confidence, reasoning)``.
        """
        decision: DecisionLiteral = "HOLD"
        confidence: float = 0.0
        reasoning: str = response  # Default to full response if not parsed

        for line in response.splitlines():
            stripped = line.strip()
            upper = stripped.upper()

            if upper.startswith("DECISION:"):
                raw = stripped.split(":", 1)[1].strip().upper()
                if raw in _VALID_DECISIONS:
                    decision = raw  # type: ignore[assignment]

            elif upper.startswith("CONFIDENCE:"):
                raw_conf = stripped.split(":", 1)[1].strip()
                try:
                    parsed = float(raw_conf)
                    confidence = max(0.0, min(1.0, parsed))
                except ValueError:
                    pass  # Keep default 0.0

            elif upper.startswith("REASONING:"):
                reasoning = stripped.split(":", 1)[1].strip()

        return decision, confidence, reasoning
