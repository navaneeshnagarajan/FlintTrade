"""Multi-agent trading team for collaborative market analysis.

Adapts patterns from:
- **MiroFish** (CAMEL-AI/OASIS): Agents with specialised system prompts that
  independently observe their environment, then a consensus mechanism
  combines their views into a unified decision.
- **TradingAgents**: Multiple LLM personas (market analyst, fundamentals
  analyst, sentiment analyst) each produce an independent report.  A risk
  debate (aggressive / conservative / neutral perspectives) refines the
  signal, and a final judge/aggregator synthesises everything into a
  BUY/SELL/HOLD recommendation with confidence.
- **autoresearch** (MarketCalls/autoresearch): Autonomous experiment loop
  pattern — run analysis, evaluate results, decide next action, repeat.
  Applied here as ``AutonomousResearchLoop`` for continuous market
  monitoring without human intervention.

Key design choices:
- **No LangGraph / LangChain dependency** — pure Python state machine using
  FlintTrade's existing ``LLMClient``.  Each agent is simply a different
  system prompt sent to the same LLM.
- **Parallel-ready** — agents are independent; today they run sequentially
  but the design allows trivial ``asyncio.gather`` parallelism later.
- **Configurable roster** — agents can be added, removed, or disabled at
  runtime via the ``AgentRole`` dataclass.
- **Two-tier LLM** — analyst agents use the quick LLM; the aggregator
  uses an optional deep LLM for higher-quality synthesis.

Usage::

    from flinttrade_ai.llm_client import LLMClient
    from flinttrade_ai.multi_agent import AgentTeam

    client = LLMClient()
    team = AgentTeam(llm_client=client)
    result = team.analyse("NIFTY", "NSE_INDEX")
    rec = team.get_recommendation(result)
    print(rec.action, rec.confidence)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from .agent_models import (
    AgentAnalysis,
    AgentRole,
    AgentRoleType,
    TeamAnalysis,
    TradeRecommendation,
)
from .llm_client import LLMClient, LLMMessage

logger = logging.getLogger("flinttrade.ai.multi_agent")

_VALID_SIGNALS = frozenset({"BUY", "SELL", "HOLD"})


# ---------------------------------------------------------------------------
# Default agent roster
# ---------------------------------------------------------------------------

def default_agents() -> list[AgentRole]:
    """Return the default agent roster for a trading team.

    Inspired by TradingAgents' analyst personas and MiroFish's role-based
    swarm: each agent has a distinct analytical perspective and writes
    a structured report with an explicit signal and confidence.
    """
    return [
        AgentRole(
            name="Technical Analyst",
            role_type=AgentRoleType.TECHNICAL,
            system_prompt=(
                "You are a technical market analyst specialising in Indian equity "
                "and derivatives markets (NSE, NFO, MCX).  Analyse price action, "
                "volume, moving averages, RSI, MACD, Bollinger Bands, and chart "
                "patterns.  Be concise and data-driven.  Focus on actionable "
                "levels: support, resistance, breakout/breakdown zones.\n\n"
                "Always conclude your report with EXACTLY these three lines:\n"
                "SIGNAL: [BUY/SELL/HOLD]\n"
                "CONFIDENCE: [0.0-1.0]\n"
                "SUMMARY: [one sentence]"
            ),
        ),
        AgentRole(
            name="Fundamental Analyst",
            role_type=AgentRoleType.FUNDAMENTAL,
            system_prompt=(
                "You are a fundamental equity analyst covering Indian markets.  "
                "Evaluate valuation metrics (P/E, P/B, EV/EBITDA), earnings "
                "quality, revenue growth, debt levels, promoter holding, and "
                "sector positioning.  Consider macro factors: RBI policy, INR "
                "trends, FII/DII flows.  Be concise.\n\n"
                "Always conclude your report with EXACTLY these three lines:\n"
                "SIGNAL: [BUY/SELL/HOLD]\n"
                "CONFIDENCE: [0.0-1.0]\n"
                "SUMMARY: [one sentence]"
            ),
        ),
        AgentRole(
            name="Sentiment Analyst",
            role_type=AgentRoleType.SENTIMENT,
            system_prompt=(
                "You are a financial sentiment analyst covering Indian markets.  "
                "Analyse news sentiment, social media chatter, FII/DII activity, "
                "options market sentiment (PCR, max pain, OI build-up), and "
                "global cues.  Identify sentiment shifts and crowd positioning.\n\n"
                "Always conclude your report with EXACTLY these three lines:\n"
                "SIGNAL: [BUY/SELL/HOLD]\n"
                "CONFIDENCE: [0.0-1.0]\n"
                "SUMMARY: [one sentence]"
            ),
        ),
        AgentRole(
            name="Risk Manager",
            role_type=AgentRoleType.RISK_MANAGER,
            system_prompt=(
                "You are a risk manager for an Indian F&O trading desk.  "
                "Evaluate position sizing risk, portfolio concentration, "
                "margin requirements, volatility (VIX, ATR), maximum drawdown "
                "scenarios, and tail risk.  Consider correlation with NIFTY, "
                "sector exposure, and event risk (earnings, expiry, RBI policy).\n\n"
                "Always conclude your report with EXACTLY these three lines:\n"
                "SIGNAL: [BUY/SELL/HOLD]\n"
                "CONFIDENCE: [0.0-1.0]\n"
                "SUMMARY: [one sentence]"
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# Aggregator prompt (inspired by TradingAgents' research_manager + risk_manager)
# ---------------------------------------------------------------------------

_AGGREGATOR_SYSTEM = (
    "You are the portfolio manager and final decision maker for a trading team.  "
    "You receive independent analysis reports from multiple specialist agents "
    "(technical, fundamental, sentiment, risk).  Your task is to:\n"
    "1. Weigh each agent's report by its relevance and confidence.\n"
    "2. Identify consensus and disagreements across agents.\n"
    "3. Produce a single, clear, actionable trading recommendation.\n"
    "4. Do NOT default to HOLD when agents disagree — commit to the "
    "strongest evidence-backed position.\n\n"
    "Respond in EXACTLY this format:\n"
    "DECISION: [BUY/SELL/HOLD]\n"
    "CONFIDENCE: [0.0-1.0]\n"
    "REASONING: [2-4 sentences synthesising the agents' views]"
)


# ---------------------------------------------------------------------------
# AgentTeam
# ---------------------------------------------------------------------------


class AgentTeam:
    """Multi-agent trading team inspired by MiroFish + TradingAgents.

    Each agent in the roster independently analyses a symbol by sending
    its specialised system prompt to the LLM.  The Aggregator then
    synthesises all reports into a single BUY/SELL/HOLD recommendation.

    Args:
        llm_client: LLM client used by all analyst agents.
        deep_llm_client: Optional higher-quality LLM for the aggregator.
            Falls back to ``llm_client`` when ``None``.
        agents: List of ``AgentRole`` definitions.  Defaults to
            ``default_agents()`` (Technical, Fundamental, Sentiment,
            Risk Manager).

    Example::

        team = AgentTeam(llm_client=LLMClient())
        result = team.analyse("RELIANCE", "NSE")
        rec = team.get_recommendation(result)
        print(rec.action, rec.confidence, rec.reasoning)
    """

    def __init__(
        self,
        llm_client: LLMClient,
        deep_llm_client: LLMClient | None = None,
        agents: list[AgentRole] | None = None,
    ) -> None:
        self._quick = llm_client
        self._deep = deep_llm_client or llm_client
        self._agents: list[AgentRole] = agents if agents is not None else default_agents()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def agents(self) -> list[AgentRole]:
        """Return the current agent roster."""
        return list(self._agents)

    @property
    def enabled_agents(self) -> list[AgentRole]:
        """Return only enabled agents (excludes aggregator role type)."""
        return [a for a in self._agents if a.enabled and a.role_type != AgentRoleType.AGGREGATOR]

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def add_agent(self, agent: AgentRole) -> None:
        """Add an agent to the roster."""
        self._agents.append(agent)

    def remove_agent(self, name: str) -> bool:
        """Remove an agent by name.  Returns True if found and removed."""
        before = len(self._agents)
        self._agents = [a for a in self._agents if a.name != name]
        return len(self._agents) < before

    def set_agent_enabled(self, name: str, enabled: bool) -> bool:
        """Enable or disable an agent by name.  Returns True if found."""
        for agent in self._agents:
            if agent.name == name:
                agent.enabled = enabled
                return True
        return False

    def get_config(self) -> dict[str, Any]:
        """Return the team configuration as a serialisable dictionary."""
        return {
            "agents": [a.to_dict() for a in self._agents],
        }

    def update_config(self, config: dict[str, Any]) -> None:
        """Update the team configuration from a dictionary.

        Replaces the agent roster with the provided list.
        """
        if "agents" in config:
            self._agents = [AgentRole.from_dict(d) for d in config["agents"]]

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def analyse(
        self,
        symbol: str,
        exchange: str,
        market_data: dict[str, Any] | None = None,
        parallel: bool = False,
    ) -> TeamAnalysis:
        """Run team analysis on a symbol.

        Each enabled agent independently analyses the symbol, then the
        aggregator synthesises all reports into a consensus.

        Inspired by TradingAgents' flow: analysts produce reports in
        parallel (here sequential by default), then the research manager
        + risk manager debate and judge.  We collapse that into a single
        aggregator step for simplicity while preserving the multi-
        perspective pattern.

        Args:
            symbol: Instrument symbol (e.g. "NIFTY", "RELIANCE").
            exchange: Exchange code (e.g. "NSE_INDEX", "NSE", "NFO").
            market_data: Optional dict of market context to include in
                the user prompt (indicators, prices, news snippets).
            parallel: When True, run all analyst agents concurrently via
                ``asyncio.gather`` with a semaphore of 4 concurrent LLM
                calls.  When False (default), agents run sequentially as
                a safe fallback.

        Returns:
            A ``TeamAnalysis`` with all agent analyses and the consensus.
        """
        result = TeamAnalysis(symbol=symbol, exchange=exchange)
        enabled = self.enabled_agents

        if not enabled:
            result.errors.append("No enabled agents in the team")
            result.consensus_signal = "HOLD"
            result.consensus_reasoning = "No agents available for analysis."
            return result

        # Phase 1: Each agent produces an independent analysis
        if parallel:
            analyses = asyncio.run(
                self._run_agents_parallel(enabled, symbol, exchange, market_data)
            )
        else:
            analyses = [
                self._run_agent(agent, symbol, exchange, market_data)
                for agent in enabled
            ]

        for analysis in analyses:
            result.agent_analyses.append(analysis)
            if analysis.error:
                result.errors.append(f"{analysis.agent_name}: {analysis.error}")

        # Phase 2: Aggregator synthesises all reports
        try:
            self._run_aggregator(result)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"Aggregator: {exc}")
            logger.warning("Aggregator failed: %s", exc)
            # Fall back to majority vote
            self._majority_vote_fallback(result)

        return result

    async def run_parallel(
        self,
        agents: list[AgentRole],
        context: dict[str, Any],
        max_concurrent: int = 4,
    ) -> list[AgentAnalysis]:
        """Run a list of agents concurrently against a market context dict.

        This is the primary public async entry point for parallel
        execution.  It wraps ``_run_agents_parallel`` with a configurable
        concurrency limit, making it safe to call from external async code
        such as a FastAPI route handler or an async research loop.

        Adapts the MiroFish parallel-agent pattern: agents are
        independent observers that run simultaneously and write their
        reports into a shared result.

        Args:
            agents: List of ``AgentRole`` objects to execute.
            context: Market context dict forwarded to each agent as
                ``market_data``.  Expected keys (all optional):
                ``symbol``, ``exchange``, plus any indicator values.
            max_concurrent: Maximum number of simultaneous LLM calls
                (semaphore limit).  Defaults to 4.

        Returns:
            List of ``AgentAnalysis`` in the same order as ``agents``.

        Example::

            team = AgentTeam(llm_client=LLMClient())
            analyses = await team.run_parallel(
                team.enabled_agents,
                {"symbol": "NIFTY", "exchange": "NSE_INDEX", "rsi": 55},
            )
        """
        symbol = str(context.get("symbol", ""))
        exchange = str(context.get("exchange", ""))
        market_data = {k: v for k, v in context.items() if k not in ("symbol", "exchange")}

        return await self._run_agents_parallel(
            agents, symbol, exchange, market_data or None, max_concurrent=max_concurrent
        )

    def get_recommendation(self, team_analysis: TeamAnalysis) -> TradeRecommendation:
        """Convert a TeamAnalysis into a simplified TradeRecommendation."""
        return TradeRecommendation.from_team_analysis(team_analysis)

    # ------------------------------------------------------------------
    # Internal: parallel agent execution
    # ------------------------------------------------------------------

    async def _run_agents_parallel(
        self,
        agents: list[AgentRole],
        symbol: str,
        exchange: str,
        market_data: dict[str, Any] | None,
        max_concurrent: int = 4,
    ) -> list[AgentAnalysis]:
        """Run all agents concurrently with a semaphore-limited gather.

        Uses ``asyncio.Semaphore`` to cap simultaneous LLM calls at
        ``max_concurrent`` (default 4), preventing rate-limit errors
        on local LLM Studio and cloud providers alike.

        Each agent wraps the synchronous ``_run_agent`` call in
        ``asyncio.get_event_loop().run_in_executor`` so the actual
        blocking HTTP call does not stall the event loop.

        Args:
            agents: Enabled agents to run.
            symbol: Instrument symbol.
            exchange: Exchange code.
            market_data: Optional market context dict.
            max_concurrent: Semaphore concurrency limit.

        Returns:
            Ordered list of ``AgentAnalysis`` results.
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        loop = asyncio.get_event_loop()

        async def _guarded(agent: AgentRole) -> AgentAnalysis:
            async with semaphore:
                return await loop.run_in_executor(
                    None,
                    self._run_agent,
                    agent,
                    symbol,
                    exchange,
                    market_data,
                )

        logger.debug(
            "Running %d agents in parallel (max_concurrent=%d)",
            len(agents),
            max_concurrent,
        )
        results = await asyncio.gather(*[_guarded(a) for a in agents])
        return list(results)

    # ------------------------------------------------------------------
    # Internal: run a single agent
    # ------------------------------------------------------------------

    def _run_agent(
        self,
        agent: AgentRole,
        symbol: str,
        exchange: str,
        market_data: dict[str, Any] | None,
    ) -> AgentAnalysis:
        """Execute a single agent's analysis.

        Builds a user prompt with the symbol, exchange, and any market
        context, sends it with the agent's system prompt to the LLM,
        and parses the structured response.
        """
        user_content = (
            f"Analyse {symbol} on {exchange} for a trading decision.\n"
        )
        if market_data:
            context_lines = [f"  {k}: {v}" for k, v in market_data.items()]
            user_content += "Market context:\n" + "\n".join(context_lines) + "\n"

        user_content += (
            "\nProvide your analysis report (under 200 words), then conclude "
            "with your SIGNAL, CONFIDENCE, and SUMMARY lines."
        )

        messages = [
            LLMMessage(role="system", content=agent.system_prompt),
            LLMMessage(role="user", content=user_content),
        ]

        try:
            response = self._quick.chat(
                messages,
                temperature=agent.temperature,
            )
            if not response.success:
                return AgentAnalysis(
                    agent_name=agent.name,
                    role_type=agent.role_type.value,
                    error=response.error or "LLM returned empty response",
                )

            signal, confidence, report = self._parse_agent_response(response.content)
            return AgentAnalysis(
                agent_name=agent.name,
                role_type=agent.role_type.value,
                report=report,
                signal=signal,
                confidence=confidence,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Agent '%s' failed: %s", agent.name, exc)
            return AgentAnalysis(
                agent_name=agent.name,
                role_type=agent.role_type.value,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Internal: aggregator
    # ------------------------------------------------------------------

    def _run_aggregator(self, result: TeamAnalysis) -> None:
        """Synthesise all agent reports into a consensus decision.

        Inspired by TradingAgents' research_manager: reads all analyst
        reports, weighs evidence, and produces a decisive recommendation.
        Uses the deep LLM for higher-quality reasoning.
        """
        successful = [a for a in result.agent_analyses if a.success]
        if not successful:
            result.consensus_signal = "HOLD"
            result.consensus_confidence = 0.0
            result.consensus_reasoning = "All agents failed; defaulting to HOLD."
            return

        # Build the combined report for the aggregator
        report_sections = []
        for analysis in successful:
            section = (
                f"--- {analysis.agent_name} ({analysis.role_type}) ---\n"
                f"Signal: {analysis.signal} (confidence: {analysis.confidence})\n"
                f"Report: {analysis.report}"
            )
            report_sections.append(section)

        combined = "\n\n".join(report_sections)

        messages = [
            LLMMessage(role="system", content=_AGGREGATOR_SYSTEM),
            LLMMessage(
                role="user",
                content=(
                    f"Synthesise the following agent analyses for {result.symbol} "
                    f"({result.exchange}) into a final trading recommendation.\n\n"
                    f"{combined}\n\n"
                    "Provide your DECISION, CONFIDENCE, and REASONING."
                ),
            ),
        ]

        response = self._deep.chat(messages)
        decision, confidence, reasoning = self._parse_aggregator_response(response.content)
        result.consensus_signal = decision
        result.consensus_confidence = confidence
        result.consensus_reasoning = reasoning

    def _majority_vote_fallback(self, result: TeamAnalysis) -> None:
        """Simple majority-vote fallback when the aggregator LLM fails.

        Counts BUY/SELL/HOLD votes from successful agents and picks
        the majority.  Confidence is the fraction of agents that agree.
        Inspired by MiroFish's consensus/voting mechanism.
        """
        successful = [a for a in result.agent_analyses if a.success]
        if not successful:
            result.consensus_signal = "HOLD"
            result.consensus_confidence = 0.0
            result.consensus_reasoning = "No successful analyses to aggregate."
            return

        votes: dict[str, int] = {"BUY": 0, "SELL": 0, "HOLD": 0}
        for analysis in successful:
            signal = analysis.signal.upper()
            if signal in votes:
                votes[signal] += 1

        winner = max(votes, key=lambda k: votes[k])
        total = len(successful)
        result.consensus_signal = winner
        result.consensus_confidence = round(votes[winner] / total, 4) if total > 0 else 0.0
        result.consensus_reasoning = (
            f"Majority vote: {votes['BUY']} BUY, {votes['SELL']} SELL, "
            f"{votes['HOLD']} HOLD out of {total} agents."
        )

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_agent_response(response: str) -> tuple[str, float, str]:
        """Parse an agent's structured response into (signal, confidence, report).

        Extracts the SIGNAL, CONFIDENCE, and SUMMARY lines.  The report
        is everything before the SIGNAL line.  Falls back gracefully on
        malformed output.
        """
        signal = "HOLD"
        confidence = 0.0
        report_lines: list[str] = []
        found_signal = False

        for line in response.splitlines():
            stripped = line.strip()
            upper = stripped.upper()

            if upper.startswith("SIGNAL:"):
                raw = stripped.split(":", 1)[1].strip().upper()
                if raw in _VALID_SIGNALS:
                    signal = raw
                found_signal = True
            elif upper.startswith("CONFIDENCE:"):
                raw_conf = stripped.split(":", 1)[1].strip()
                try:
                    parsed = float(raw_conf)
                    confidence = max(0.0, min(1.0, parsed))
                except ValueError:
                    pass
            elif upper.startswith("SUMMARY:"):
                pass  # Summary is for display; report captures the detail
            elif not found_signal:
                report_lines.append(line)

        report = "\n".join(report_lines).strip() or response
        return signal, confidence, report

    @staticmethod
    def _parse_aggregator_response(response: str) -> tuple[str, float, str]:
        """Parse the aggregator's structured response.

        Same format as AnalystChain's judge: DECISION, CONFIDENCE, REASONING.
        """
        decision = "HOLD"
        confidence = 0.0
        reasoning = response

        for line in response.splitlines():
            stripped = line.strip()
            upper = stripped.upper()

            if upper.startswith("DECISION:"):
                raw = stripped.split(":", 1)[1].strip().upper()
                if raw in _VALID_SIGNALS:
                    decision = raw
            elif upper.startswith("CONFIDENCE:"):
                raw_conf = stripped.split(":", 1)[1].strip()
                try:
                    parsed = float(raw_conf)
                    confidence = max(0.0, min(1.0, parsed))
                except ValueError:
                    pass
            elif upper.startswith("REASONING:"):
                reasoning = stripped.split(":", 1)[1].strip()

        return decision, confidence, reasoning


# ---------------------------------------------------------------------------
# Autonomous Research Loop (adapted from MarketCalls/autoresearch)
# ---------------------------------------------------------------------------


@dataclass
class ResearchIteration:
    """Record of a single autonomous research iteration.

    Mirrors autoresearch's results.tsv row: each iteration records what
    was tried, the outcome, and whether to keep the result.
    """

    iteration: int
    symbol: str
    exchange: str
    signal: str = "HOLD"
    confidence: float = 0.0
    reasoning: str = ""
    status: str = "pending"  # pending | completed | failed
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a serialisable dictionary."""
        return {
            "iteration": self.iteration,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "signal": self.signal,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "status": self.status,
            "error": self.error,
        }


class AutonomousResearchLoop:
    """Autonomous market research loop inspired by autoresearch.

    Runs an ``AgentTeam`` analysis repeatedly on a watchlist, accumulating
    results for trend detection and signal persistence.  Follows
    autoresearch's core pattern: run -> evaluate -> decide -> record -> repeat.

    Unlike autoresearch (which modifies code between iterations), this loop
    re-analyses the same instruments with fresh market data each iteration,
    looking for signal convergence or divergence across time.

    Args:
        team: The AgentTeam to use for each analysis.
        max_iterations: Maximum number of analysis passes (0 = unlimited).
        on_iteration: Optional callback invoked after each iteration with
            the ``ResearchIteration`` result.

    Example::

        team = AgentTeam(llm_client=LLMClient())
        loop = AutonomousResearchLoop(team, max_iterations=5)
        results = loop.run_sync([("NIFTY", "NSE_INDEX"), ("RELIANCE", "NSE")])
        for r in results:
            print(r.symbol, r.signal, r.confidence)
    """

    def __init__(
        self,
        team: AgentTeam,
        max_iterations: int = 10,
        on_iteration: Any = None,
    ) -> None:
        self._team = team
        self._max_iterations = max_iterations
        self._on_iteration = on_iteration
        self._results: list[ResearchIteration] = []
        self._stop_requested = False

    @property
    def results(self) -> list[ResearchIteration]:
        """All completed research iterations."""
        return list(self._results)

    def stop(self) -> None:
        """Request the loop to stop after the current iteration."""
        self._stop_requested = True

    def run_sync(
        self,
        watchlist: list[tuple[str, str]],
        market_data: dict[str, Any] | None = None,
    ) -> list[ResearchIteration]:
        """Run the autonomous research loop synchronously.

        Iterates over the watchlist ``max_iterations`` times (or until
        ``stop()`` is called), running a full AgentTeam analysis on each
        symbol per iteration.

        Adapts autoresearch's "never stop" philosophy: the loop continues
        until max_iterations or explicit stop, logging each result.

        Args:
            watchlist: List of (symbol, exchange) tuples.
            market_data: Optional shared market context for all analyses.

        Returns:
            List of all ResearchIteration results.
        """
        self._stop_requested = False
        self._results = []
        iteration = 0

        while True:
            if self._stop_requested:
                logger.info("Autonomous loop: stop requested at iteration %d", iteration)
                break
            if self._max_iterations > 0 and iteration >= self._max_iterations:
                break

            for symbol, exchange in watchlist:
                if self._stop_requested:
                    break

                record = ResearchIteration(
                    iteration=iteration,
                    symbol=symbol,
                    exchange=exchange,
                )

                try:
                    result = self._team.analyse(symbol, exchange, market_data)
                    rec = self._team.get_recommendation(result)
                    record.signal = rec.action
                    record.confidence = rec.confidence
                    record.reasoning = rec.reasoning
                    record.status = "completed"
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Autonomous loop: %s/%s failed at iteration %d: %s",
                        symbol, exchange, iteration, exc,
                    )
                    record.status = "failed"
                    record.error = str(exc)

                self._results.append(record)

                if self._on_iteration is not None:
                    try:
                        self._on_iteration(record)
                    except Exception:  # noqa: BLE001
                        pass

            iteration += 1

        logger.info(
            "Autonomous loop completed: %d iterations, %d results",
            iteration, len(self._results),
        )
        return self._results

    def get_signal_summary(self) -> dict[str, dict[str, Any]]:
        """Summarise signals across all iterations per symbol.

        Returns a dict keyed by symbol with:
        - ``dominant_signal``: Most frequent signal across iterations.
        - ``avg_confidence``: Mean confidence.
        - ``iterations``: Number of completed iterations.
        - ``signal_counts``: Dict of signal -> count.

        Returns:
            Per-symbol signal summary.
        """
        from collections import defaultdict

        by_symbol: dict[str, list[ResearchIteration]] = defaultdict(list)
        for r in self._results:
            if r.status == "completed":
                by_symbol[r.symbol].append(r)

        summary: dict[str, dict[str, Any]] = {}
        for symbol, iterations in by_symbol.items():
            counts: dict[str, int] = {"BUY": 0, "SELL": 0, "HOLD": 0}
            total_conf = 0.0
            for it in iterations:
                signal = it.signal.upper()
                if signal in counts:
                    counts[signal] += 1
                total_conf += it.confidence

            dominant = max(counts, key=lambda k: counts[k])
            avg_conf = total_conf / len(iterations) if iterations else 0.0

            summary[symbol] = {
                "dominant_signal": dominant,
                "avg_confidence": round(avg_conf, 4),
                "iterations": len(iterations),
                "signal_counts": counts,
            }

        return summary
