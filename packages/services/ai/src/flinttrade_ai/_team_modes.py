"""Canonical implementations for FlintTrade's sequential and debate team modes.

The public compatibility modules re-export these models and orchestrators. This
private module owns the complete behaviour so the two modes have one source of
truth while their established APIs remain stable.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from inspect import Parameter, signature
from typing import Any, Callable

from ._team_dag import EventCallback, TeamDagRunner, TeamEvent, _ThreadCallRunner
from .llm_client import LLMClient, LLMMessage
from .memory import MemoryBackend, MemoryEntry, MemoryLayer, TradedMemory

logger = logging.getLogger("flinttrade.ai.team_modes")

DecisionLiteral = str  # "BUY" | "SELL" | "HOLD"

_VALID_DECISIONS = frozenset({"BUY", "SELL", "HOLD"})
_VALID_VERDICTS = frozenset({"BUY", "SELL", "HOLD"})
_ANALYSIS_FAILED = "analysis failed"
_JUDGE_FAILED = "Judge analysis failed"

__all__ = [
    "AnalysisState",
    "AnalystChain",
    "DebateResult",
    "DebateRound",
    "RiskDebate",
]


@dataclass
class AnalysisState:
    """Shared state flowing through the analyst chain."""

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


def _accepts_keyword(callable_object: Callable[..., Any], keyword: str) -> bool:
    """Return whether a callable accepts a named keyword or arbitrary keywords."""
    try:
        parameters = signature(callable_object).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(parameter.name == keyword or parameter.kind is Parameter.VAR_KEYWORD for parameter in parameters)


def _response_content(response: Any, role: str) -> str:
    """Return usable response text or raise after logging provider detail."""
    content = response.content if isinstance(response.content, str) else ""
    if not response.success or not content.strip():
        logger.warning(
            "%s returned an unsuccessful LLM response: %s",
            role,
            response.error or "empty response",
        )
        raise RuntimeError("LLM analysis failed")
    return content


class AnalystChain:
    """Sequential multi-agent analysis pipeline with a final judge."""

    def __init__(
        self,
        llm_client: LLMClient,
        deep_llm_client: LLMClient | None = None,
        memory: TradedMemory | None = None,
        analysts: list[str] | None = None,
    ) -> None:
        self._quick = llm_client
        self._deep = deep_llm_client or llm_client
        self._memory: MemoryBackend | TradedMemory | None = memory
        self._analysts: list[str] = analysts if analysts is not None else ["market", "sentiment"]

    def analyse(
        self,
        symbol: str,
        exchange: str,
        trade_date: date | None = None,
    ) -> AnalysisState:
        """Run enabled analysts in order, then always attempt the judge."""
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
                state.errors.append(f"{name}: {_ANALYSIS_FAILED}")
                logger.warning("Analyst node '%s' failed: %s", name, exc)

        try:
            self._judge_node(state)
        except Exception as exc:  # noqa: BLE001
            state.errors.append(f"judge: {_ANALYSIS_FAILED}")
            logger.warning("Judge node failed: %s", exc)

        return state

    async def analyse_async(
        self,
        symbol: str,
        exchange: str,
        *,
        timeout_seconds: float,
        call_runner: _ThreadCallRunner,
        on_event: EventCallback | None = None,
        trade_date: date | None = None,
    ) -> AnalysisState:
        """Run each analyst and judge with isolated state and lifecycle events."""
        state = AnalysisState(symbol=symbol, exchange=exchange, trade_date=trade_date or date.today())
        for name in self._analysts:
            await TeamDagRunner._emit(
                on_event,
                TeamEvent(task_id=name, agent_role=name, event_type="started"),
            )
            draft = copy.deepcopy(state)
            try:
                node = self._get_node(name)
                await call_runner.run(lambda node=node, draft=draft: node(draft), timeout_seconds)
            except TimeoutError:
                state.errors.append(f"{name}: analysis timed out")
                await TeamDagRunner._emit(
                    on_event,
                    TeamEvent(
                        task_id=name,
                        agent_role=name,
                        event_type="timeout",
                        data={"timeout_seconds": timeout_seconds},
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                state.errors.append(f"{name}: {_ANALYSIS_FAILED}")
                logger.warning("Analyst node '%s' failed: %s", name, exc)
                await TeamDagRunner._emit(
                    on_event,
                    TeamEvent(
                        task_id=name,
                        agent_role=name,
                        event_type="error",
                        data={"error": "Analysis failed"},
                    ),
                )
            else:
                state = draft
                await TeamDagRunner._emit(
                    on_event,
                    TeamEvent(task_id=name, agent_role=name, event_type="completed"),
                )

        await TeamDagRunner._emit(
            on_event,
            TeamEvent(task_id="judge", agent_role="judge", event_type="started"),
        )
        draft = copy.deepcopy(state)
        try:
            await call_runner.run(lambda: self._judge_node(draft), timeout_seconds)
        except TimeoutError:
            state.errors.append("judge: analysis timed out")
            await TeamDagRunner._emit(
                on_event,
                TeamEvent(
                    task_id="judge",
                    agent_role="judge",
                    event_type="timeout",
                    data={"timeout_seconds": timeout_seconds},
                ),
            )
        except Exception as exc:  # noqa: BLE001
            state.errors.append(f"judge: {_ANALYSIS_FAILED}")
            logger.warning("Judge node failed: %s", exc)
            await TeamDagRunner._emit(
                on_event,
                TeamEvent(
                    task_id="judge",
                    agent_role="judge",
                    event_type="error",
                    data={"error": "Analysis failed"},
                ),
            )
        else:
            state = draft
            await TeamDagRunner._emit(
                on_event,
                TeamEvent(task_id="judge", agent_role="judge", event_type="completed"),
            )
        return state

    def _get_node(self, name: str) -> Callable[[AnalysisState], None]:
        """Return the requested analyst node or reject an unknown name."""
        nodes: dict[str, Callable[[AnalysisState], None]] = {
            "market": self._market_analyst,
            "sentiment": self._sentiment_analyst,
            "fundamentals": self._fundamentals_analyst,
        }
        if name not in nodes:
            raise ValueError(f"Unknown analyst '{name}'. Valid options: {sorted(nodes.keys())}")
        return nodes[name]

    def _market_analyst(self, state: AnalysisState) -> None:
        """Analyse price action, volume, and technical indicators."""
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
        state.market_report = _response_content(response, "Market analyst")
        logger.debug("Market report for %s: %d chars", state.symbol, len(state.market_report))

    def _sentiment_memories(self, symbol: str) -> list[MemoryEntry]:
        """Retrieve at most two short-horizon memories through either API shape."""
        if self._memory is None:
            return []

        query = f"sentiment for {symbol}"
        if "retrieve" in dir(self._memory):
            retrieve = self._memory.retrieve
            kwargs: dict[str, Any] = {"top_k": 2, "symbol": symbol}
            if _accepts_keyword(retrieve, "layer"):
                kwargs["layer"] = MemoryLayer.SHORT
            return list(retrieve(query, **kwargs))[:2]

        if "get_memories" in dir(self._memory):
            result = self._memory.get_memories(
                symbol,
                query,
                MemoryLayer.SHORT,
                n=2,
            )
            return list(result.items)[:2]

        return []

    @staticmethod
    def _memory_text(item: MemoryEntry) -> str:
        """Read canonical content while accepting the former text attribute."""
        content = getattr(item, "content", None)
        if isinstance(content, str):
            return content
        text = getattr(item, "text", "")
        return text if isinstance(text, str) else str(text)

    def _sentiment_analyst(self, state: AnalysisState) -> None:
        """Analyse news sentiment with fail-soft memory enrichment."""
        memory_context = ""
        try:
            items = self._sentiment_memories(state.symbol)
            if items:
                lines = "\n".join(f"- {self._memory_text(item)}" for item in items)
                memory_context = f"\nPast sentiment observations:\n{lines}"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Memory retrieval failed for sentiment node: %s", exc)

        messages = [
            LLMMessage(
                role="system",
                content=(
                    "You are a financial news sentiment analyst covering Indian markets. Be concise and evidence-based."
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
        state.sentiment_report = _response_content(response, "Sentiment analyst")
        logger.debug("Sentiment report for %s: %d chars", state.symbol, len(state.sentiment_report))

    def _fundamentals_analyst(self, state: AnalysisState) -> None:
        """Analyse fundamental strengths and risks in one structured call."""
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
        content = _response_content(response, "Fundamentals analyst")

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

    def _judge_node(self, state: AnalysisState) -> None:
        """Synthesise analyst reports into a final trading decision."""
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
                    "Based on the following analyst reports, provide your trading decision.\n\n"
                    f"{combined}\n\n"
                    "Respond in EXACTLY this format:\n"
                    "DECISION: [BUY/SELL/HOLD]\n"
                    "CONFIDENCE: [0.0-1.0]\n"
                    "REASONING: [2-3 sentences explaining why]"
                ),
            ),
        ]
        response = self._deep.chat(messages)
        decision, confidence, reasoning = self._parse_judge_response(_response_content(response, "Sequential judge"))
        state.final_decision = decision
        state.confidence = confidence
        state.final_reasoning = reasoning
        logger.debug(
            "Judge decision for %s: %s (confidence=%.2f)",
            state.symbol,
            decision,
            confidence,
        )

    @staticmethod
    def _parse_judge_response(response: str) -> tuple[DecisionLiteral, float, str]:
        """Extract decision, confidence, and reasoning from judge output."""
        decision: DecisionLiteral = "HOLD"
        confidence = 0.0
        reasoning = response

        for line in response.splitlines():
            stripped = line.strip()
            upper = stripped.upper()
            if upper.startswith("DECISION:"):
                raw = stripped.split(":", 1)[1].strip().upper()
                if raw in _VALID_DECISIONS:
                    decision = raw
            elif upper.startswith("CONFIDENCE:"):
                raw_confidence = stripped.split(":", 1)[1].strip()
                try:
                    parsed = float(raw_confidence)
                    confidence = max(0.0, min(1.0, parsed))
                except ValueError:
                    pass
            elif upper.startswith("REASONING:"):
                reasoning = stripped.split(":", 1)[1].strip()

        return decision, confidence, reasoning


@dataclass
class DebateRound:
    """One round of the three-way risk debate."""

    round_number: int
    aggressive: str = ""
    conservative: str = ""
    neutral: str = ""


@dataclass
class DebateResult:
    """Complete result of a risk debate."""

    trade_proposal: str
    rounds: list[DebateRound] = field(default_factory=list)
    verdict: str = "HOLD"
    confidence: float = 0.0
    reasoning: str = ""
    full_transcript: str = ""
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


_AGGRESSIVE_SYSTEM = (
    "You are the Aggressive Risk Analyst for an Indian F&O trading desk. "
    "Champion high-reward opportunities, emphasise bold strategies, growth "
    "potential, and competitive advantages.  Directly counter the conservative "
    "and neutral viewpoints with data-driven rebuttals.  Focus on why the "
    "potential upside justifies elevated risk.  Be conversational, concise, "
    "and persuasive.  Keep under 150 words."
)

_CONSERVATIVE_SYSTEM = (
    "You are the Conservative Risk Analyst for an Indian F&O trading desk. "
    "Protect capital, minimise volatility, and ensure steady growth.  Critically "
    "examine high-risk elements, point out where the proposal may expose the desk "
    "to excessive risk.  Directly counter the aggressive and neutral viewpoints.  "
    "Emphasise tail risk, margin requirements, VIX, and drawdown scenarios.  "
    "Be conversational, concise, and persuasive.  Keep under 150 words."
)

_NEUTRAL_SYSTEM = (
    "You are the Neutral Risk Analyst for an Indian F&O trading desk.  Provide "
    "a balanced view, weighing upside and downside.  Challenge both the aggressive "
    "and conservative perspectives -- point out where each is overly optimistic "
    "or overly cautious.  Suggest a moderate, sustainable approach.  Be "
    "conversational, concise, and persuasive.  Keep under 150 words."
)

_JUDGE_SYSTEM = (
    "You are the Risk Management Judge for an Indian F&O trading desk.  "
    "Evaluate the three-way debate between Aggressive, Conservative, and Neutral "
    "risk analysts.  Make a clear, decisive recommendation: BUY, SELL, or HOLD.  "
    "Do NOT default to HOLD unless strongly justified.  Summarise the strongest "
    "arguments from each side and explain your verdict.\n\n"
    "Respond in EXACTLY this format:\n"
    "VERDICT: [BUY/SELL/HOLD]\n"
    "CONFIDENCE: [0.0-1.0]\n"
    "REASONING: [2-4 sentences]"
)


class RiskDebate:
    """Multi-round adversarial risk debate with a final judge."""

    def __init__(
        self,
        llm_client: LLMClient,
        judge_llm_client: LLMClient | None = None,
        rounds: int = 2,
    ) -> None:
        self._llm = llm_client
        self._judge_llm = judge_llm_client or llm_client
        self._rounds = max(1, rounds)

    def run(
        self,
        trade_proposal: str,
        market_context: dict[str, Any] | None = None,
    ) -> DebateResult:
        """Execute all debate rounds and return the judge's synthesis."""
        result = DebateResult(trade_proposal=trade_proposal)
        context_block = self._format_context(market_context)

        current_aggressive = ""
        current_conservative = ""
        current_neutral = ""
        full_history = ""

        for round_num in range(1, self._rounds + 1):
            debate_round = DebateRound(round_number=round_num)
            debate_round.aggressive = self._safe_call_debater(
                system_prompt=_AGGRESSIVE_SYSTEM,
                trade_proposal=trade_proposal,
                context_block=context_block,
                history=full_history,
                other_a=current_conservative,
                other_b=current_neutral,
                other_a_label="Conservative",
                other_b_label="Neutral",
            )
            current_aggressive = debate_round.aggressive
            full_history += f"\n\n[Round {round_num} - Aggressive]: {current_aggressive}"

            debate_round.conservative = self._safe_call_debater(
                system_prompt=_CONSERVATIVE_SYSTEM,
                trade_proposal=trade_proposal,
                context_block=context_block,
                history=full_history,
                other_a=current_aggressive,
                other_b=current_neutral,
                other_a_label="Aggressive",
                other_b_label="Neutral",
            )
            current_conservative = debate_round.conservative
            full_history += f"\n\n[Round {round_num} - Conservative]: {current_conservative}"

            debate_round.neutral = self._safe_call_debater(
                system_prompt=_NEUTRAL_SYSTEM,
                trade_proposal=trade_proposal,
                context_block=context_block,
                history=full_history,
                other_a=current_aggressive,
                other_b=current_conservative,
                other_a_label="Aggressive",
                other_b_label="Conservative",
            )
            current_neutral = debate_round.neutral
            full_history += f"\n\n[Round {round_num} - Neutral]: {current_neutral}"

            result.rounds.append(debate_round)
            logger.debug("Debate round %d/%d complete", round_num, self._rounds)

        result.full_transcript = full_history.strip()
        try:
            verdict, confidence, reasoning = self._call_judge(
                trade_proposal=trade_proposal,
                context_block=context_block,
                full_history=full_history,
            )
            result.verdict = verdict
            result.confidence = confidence
            result.reasoning = reasoning
        except Exception as exc:  # noqa: BLE001
            logger.warning("Judge failed: %s", exc)
            result.verdict = "HOLD"
            result.reasoning = _JUDGE_FAILED

        return result

    async def run_async(
        self,
        trade_proposal: str,
        market_context: dict[str, Any] | None,
        *,
        timeout_seconds: float,
        call_runner: _ThreadCallRunner,
        on_event: EventCallback | None = None,
    ) -> tuple[DebateResult, dict[str, str]]:
        """Run every persona and judge with bounded per-call timeout handling."""
        result = DebateResult(trade_proposal=trade_proposal)
        context_block = self._format_context(market_context)
        current = {"aggressive": "", "conservative": "", "neutral": ""}
        failures: dict[str, str] = {}
        full_history = ""

        personas = (
            ("aggressive", _AGGRESSIVE_SYSTEM, "conservative", "neutral"),
            ("conservative", _CONSERVATIVE_SYSTEM, "aggressive", "neutral"),
            ("neutral", _NEUTRAL_SYSTEM, "aggressive", "conservative"),
        )
        for round_num in range(1, self._rounds + 1):
            debate_round = DebateRound(round_number=round_num)
            for role, system_prompt, other_a, other_b in personas:
                value, failure = await self._call_debater_async(
                    role=role,
                    system_prompt=system_prompt,
                    trade_proposal=trade_proposal,
                    context_block=context_block,
                    history=full_history,
                    other_a=current[other_a],
                    other_b=current[other_b],
                    other_a_label=other_a.title(),
                    other_b_label=other_b.title(),
                    timeout_seconds=timeout_seconds,
                    call_runner=call_runner,
                    on_event=on_event,
                )
                setattr(debate_round, role, value)
                current[role] = value
                if failure:
                    failures[role] = failure
                else:
                    failures.pop(role, None)
                full_history += f"\n\n[Round {round_num} - {role.title()}]: {value}"
            result.rounds.append(debate_round)

        result.full_transcript = full_history.strip()
        await TeamDagRunner._emit(
            on_event,
            TeamEvent(task_id="judge", agent_role="judge", event_type="started"),
        )
        try:
            verdict, confidence, reasoning = await call_runner.run(
                lambda: self._call_judge(trade_proposal, context_block, full_history),
                timeout_seconds,
            )
        except TimeoutError:
            failures["judge"] = "timeout"
            result.reasoning = "Judge analysis timed out"
            await TeamDagRunner._emit(
                on_event,
                TeamEvent(
                    task_id="judge",
                    agent_role="judge",
                    event_type="timeout",
                    data={"timeout_seconds": timeout_seconds},
                ),
            )
        except Exception as exc:  # noqa: BLE001
            failures["judge"] = "error"
            result.reasoning = _JUDGE_FAILED
            logger.warning("Judge failed: %s", exc)
            await TeamDagRunner._emit(
                on_event,
                TeamEvent(
                    task_id="judge",
                    agent_role="judge",
                    event_type="error",
                    data={"error": "Analysis failed"},
                ),
            )
        else:
            result.verdict = verdict
            result.confidence = confidence
            result.reasoning = reasoning
            await TeamDagRunner._emit(
                on_event,
                TeamEvent(task_id="judge", agent_role="judge", event_type="completed"),
            )
        return result, failures

    def _safe_call_debater(self, **kwargs: str) -> str:
        """Preserve sync debate progress while sanitising failed persona output."""
        try:
            return self._call_debater(**kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Debater call failed: %s", exc)
            return ""

    async def _call_debater_async(
        self,
        *,
        role: str,
        timeout_seconds: float,
        call_runner: _ThreadCallRunner,
        on_event: EventCallback | None,
        **kwargs: str,
    ) -> tuple[str, str]:
        """Call one persona and return its text plus a sanitised failure kind."""
        await TeamDagRunner._emit(
            on_event,
            TeamEvent(task_id=role, agent_role=role, event_type="started"),
        )
        try:
            value = await call_runner.run(lambda: self._call_debater(**kwargs), timeout_seconds)
        except TimeoutError:
            await TeamDagRunner._emit(
                on_event,
                TeamEvent(
                    task_id=role,
                    agent_role=role,
                    event_type="timeout",
                    data={"timeout_seconds": timeout_seconds},
                ),
            )
            return "", "timeout"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Debater call failed: %s", exc)
            await TeamDagRunner._emit(
                on_event,
                TeamEvent(
                    task_id=role,
                    agent_role=role,
                    event_type="error",
                    data={"error": "Analysis failed"},
                ),
            )
            return "", "error"

        await TeamDagRunner._emit(
            on_event,
            TeamEvent(task_id=role, agent_role=role, event_type="completed"),
        )
        return value, ""

    def _call_debater(
        self,
        system_prompt: str,
        trade_proposal: str,
        context_block: str,
        history: str,
        other_a: str,
        other_b: str,
        other_a_label: str,
        other_b_label: str,
    ) -> str:
        """Call one debater with the latest arguments and accumulated history."""
        user_content = f"Trade proposal: {trade_proposal}\n"
        if context_block:
            user_content += f"\nMarket context:\n{context_block}\n"
        if history:
            user_content += f"\nDebate history:\n{history}\n"
        if other_a:
            user_content += f"\nLatest {other_a_label} argument: {other_a}\n"
        if other_b:
            user_content += f"\nLatest {other_b_label} argument: {other_b}\n"
        user_content += (
            "\nRespond with your analysis and counter-arguments.  "
            "Be specific and address the other perspectives directly."
        )

        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_content),
        ]
        response = self._llm.chat(messages)
        return _response_content(response, "Debate persona").strip()

    def _call_judge(
        self,
        trade_proposal: str,
        context_block: str,
        full_history: str,
    ) -> tuple[str, float, str]:
        """Call the judge to synthesise the complete debate."""
        user_content = f"Trade proposal: {trade_proposal}\n"
        if context_block:
            user_content += f"\nMarket context:\n{context_block}\n"
        user_content += f"\nFull debate transcript:\n{full_history}\n\nProvide your VERDICT, CONFIDENCE, and REASONING."
        messages = [
            LLMMessage(role="system", content=_JUDGE_SYSTEM),
            LLMMessage(role="user", content=user_content),
        ]
        response = self._judge_llm.chat(messages)
        return self._parse_judge_response(_response_content(response, "Debate judge"))

    @staticmethod
    def _parse_judge_response(response: str) -> tuple[str, float, str]:
        """Parse the judge's structured verdict with safe defaults."""
        verdict = "HOLD"
        confidence = 0.0
        reasoning = response

        for line in response.splitlines():
            stripped = line.strip()
            upper = stripped.upper()
            if upper.startswith("VERDICT:"):
                raw = stripped.split(":", 1)[1].strip().upper()
                if raw in _VALID_VERDICTS:
                    verdict = raw
            elif upper.startswith("CONFIDENCE:"):
                raw_confidence = stripped.split(":", 1)[1].strip()
                try:
                    parsed = float(raw_confidence)
                    confidence = max(0.0, min(1.0, parsed))
                except ValueError:
                    pass
            elif upper.startswith("REASONING:"):
                reasoning = stripped.split(":", 1)[1].strip()

        return verdict, confidence, reasoning

    @staticmethod
    def _format_context(ctx: dict[str, Any] | None) -> str:
        """Format market context as the legacy prompt block."""
        if not ctx:
            return ""
        return "\n".join(f"  {key}: {value}" for key, value in ctx.items())
