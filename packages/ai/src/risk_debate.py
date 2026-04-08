"""Multi-round risk debate with three adversarial perspectives.

Absorbs TradingAgents' risk debate pattern: three LLM-driven debaters
(Aggressive, Conservative, Neutral) argue iteratively over a proposed
trade.  Each debater reads and directly counters the others' arguments.
A judge synthesises the final recommendation after N rounds.

Key differences from FlintTrade's existing ``AgentTeam``:
- **Iterative** -- agents read and rebut each other's arguments across
  multiple rounds, refining positions.  AgentTeam runs one-shot parallel.
- **Adversarial framing** -- each perspective is explicitly instructed to
  challenge the other two, not just present its own view.
- **History accumulation** -- the full debate transcript is passed to the
  judge for a holistic verdict.

Usage::

    from packages.ai.src.llm_client import LLMClient
    from packages.ai.src.risk_debate import RiskDebate

    llm = LLMClient()
    debate = RiskDebate(llm_client=llm)
    result = debate.run(
        trade_proposal="BUY NIFTY 22000 CE at 350, target 500, SL 250",
        market_context={"rsi": 68, "pcr": 0.85, "vix": 14.2},
    )
    print(result.verdict, result.confidence)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from packages.ai.src.llm_client import LLMClient, LLMMessage

logger = logging.getLogger("flinttrade.ai.risk_debate")

_VALID_VERDICTS = frozenset({"BUY", "SELL", "HOLD"})


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class DebateRound:
    """One round of the three-way debate.

    Attributes:
        round_number: 1-indexed round number.
        aggressive: Aggressive debater's argument for this round.
        conservative: Conservative debater's argument for this round.
        neutral: Neutral debater's argument for this round.
    """

    round_number: int
    aggressive: str = ""
    conservative: str = ""
    neutral: str = ""


@dataclass
class DebateResult:
    """Complete result of a risk debate.

    Attributes:
        trade_proposal: The original trade proposal that was debated.
        rounds: List of ``DebateRound`` objects (one per round).
        verdict: Final judge verdict -- ``BUY``, ``SELL``, or ``HOLD``.
        confidence: Judge's confidence in the verdict (0.0 to 1.0).
        reasoning: Judge's reasoning synthesising the debate.
        full_transcript: Concatenated debate history.
        timestamp: ISO-8601 timestamp.
    """

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


# ---------------------------------------------------------------------------
# System prompts for each debater (from TradingAgents pattern)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# RiskDebate
# ---------------------------------------------------------------------------


class RiskDebate:
    """Multi-round adversarial risk debate.

    Three LLM personas (Aggressive, Conservative, Neutral) debate a trade
    proposal over ``rounds`` iterations, each reading and countering the
    others.  A Judge then synthesises the full transcript into a verdict.

    Absorbs TradingAgents' debate pattern: the key innovation is that each
    debater sees the *current* arguments of the other two, creating genuine
    adversarial refinement rather than one-shot opinions.

    Args:
        llm_client: LLM client used for all debaters.
        judge_llm_client: Optional stronger LLM for the judge step.
            Falls back to ``llm_client`` when ``None``.
        rounds: Number of debate rounds (default 2).
    """

    def __init__(
        self,
        llm_client: LLMClient,
        judge_llm_client: LLMClient | None = None,
        rounds: int = 2,
    ) -> None:
        self._llm = llm_client
        self._judge_llm = judge_llm_client or llm_client
        self._rounds = max(1, rounds)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        trade_proposal: str,
        market_context: dict[str, Any] | None = None,
    ) -> DebateResult:
        """Execute the full debate and return the result.

        Args:
            trade_proposal: Description of the proposed trade.
            market_context: Optional dict of market data (indicators,
                prices, news snippets) to include in prompts.

        Returns:
            A ``DebateResult`` with all rounds, the full transcript,
            and the judge's verdict.
        """
        result = DebateResult(trade_proposal=trade_proposal)
        context_block = self._format_context(market_context)

        # Running state (mirrors TradingAgents' risk_debate_state)
        current_aggressive = ""
        current_conservative = ""
        current_neutral = ""
        full_history = ""

        for round_num in range(1, self._rounds + 1):
            debate_round = DebateRound(round_number=round_num)

            # Aggressive speaks first
            debate_round.aggressive = self._call_debater(
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

            # Conservative responds
            debate_round.conservative = self._call_debater(
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

            # Neutral responds
            debate_round.neutral = self._call_debater(
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

        # Judge synthesises
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
            result.reasoning = f"Judge error: {exc}"

        return result

    # ------------------------------------------------------------------
    # Internal: debater call
    # ------------------------------------------------------------------

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
        """Call a single debater with the current state.

        Mirrors TradingAgents' debate node pattern: each debater sees
        the trade proposal, market context, debate history, and the
        latest arguments from the other two perspectives.
        """
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

        try:
            response = self._llm.chat(messages)
            return response.content.strip() if response.success else ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("Debater call failed: %s", exc)
            return ""

    # ------------------------------------------------------------------
    # Internal: judge call
    # ------------------------------------------------------------------

    def _call_judge(
        self,
        trade_proposal: str,
        context_block: str,
        full_history: str,
    ) -> tuple[str, float, str]:
        """Call the judge to synthesise the debate into a verdict."""
        user_content = (
            f"Trade proposal: {trade_proposal}\n"
        )
        if context_block:
            user_content += f"\nMarket context:\n{context_block}\n"
        user_content += (
            f"\nFull debate transcript:\n{full_history}\n\n"
            "Provide your VERDICT, CONFIDENCE, and REASONING."
        )

        messages = [
            LLMMessage(role="system", content=_JUDGE_SYSTEM),
            LLMMessage(role="user", content=user_content),
        ]

        response = self._judge_llm.chat(messages)
        return self._parse_judge_response(response.content)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_judge_response(response: str) -> tuple[str, float, str]:
        """Parse the judge's structured response."""
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
                raw_conf = stripped.split(":", 1)[1].strip()
                try:
                    parsed = float(raw_conf)
                    confidence = max(0.0, min(1.0, parsed))
                except ValueError:
                    pass
            elif upper.startswith("REASONING:"):
                reasoning = stripped.split(":", 1)[1].strip()

        return verdict, confidence, reasoning

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_context(ctx: dict[str, Any] | None) -> str:
        """Format market context dict into a readable string."""
        if not ctx:
            return ""
        return "\n".join(f"  {k}: {v}" for k, v in ctx.items())
