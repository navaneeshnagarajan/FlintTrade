"""Market simulator — LLM ensemble of synthetic market participants.

Each participant (retail trader, institutional fund, momentum chaser, etc.)
reacts to a market event via an LLM call.  All calls run concurrently behind
an ``asyncio.Semaphore`` so we never overwhelm the LLM provider.  When an
async event-loop is unavailable the simulator falls back to
``ThreadPoolExecutor`` so it also works in plain synchronous contexts.

Pattern inspired by MiroFish's semaphore-bounded concurrent agent execution.
"""

from __future__ import annotations

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("flinttrade.ai.market_simulator")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class MarketParticipant:
    """A synthetic market participant with a distinct trading persona.

    Args:
        name: Display name used in prompts and results.
        persona: Free-text description of the participant's behaviour and bias.
        risk_tolerance: 0.0 (very conservative) to 1.0 (highly aggressive).
        capital: Notional capital in INR, used to weight consensus.
    """

    name: str
    persona: str
    risk_tolerance: float  # 0.0 – 1.0
    capital: float


@dataclass
class ParticipantAction:
    """A single participant's decision for one simulation step.

    Args:
        participant: Name of the participant who made this decision.
        instrument: Instrument symbol the action applies to.
        direction: ``BUY``, ``SELL``, or ``HOLD``.
        rationale: One-sentence explanation from the LLM.
        confidence: Self-assessed confidence 0.0 – 1.0.
    """

    participant: str
    instrument: str
    direction: str  # BUY / SELL / HOLD
    rationale: str
    confidence: float


@dataclass
class SimulationResult:
    """Aggregated output of a complete market simulation run.

    Args:
        event: The market event that was simulated.
        instruments: Instruments included in the simulation.
        steps: Number of simulation steps executed.
        actions: All individual participant actions (all steps).
        consensus_direction: Majority direction (``BUY`` / ``SELL`` / ``HOLD``).
        bull_pct: Percentage of directional votes that were ``BUY``.
        bear_pct: Percentage of directional votes that were ``SELL``.
    """

    event: str
    instruments: list[str]
    steps: int
    actions: list[ParticipantAction]
    consensus_direction: str
    bull_pct: float
    bear_pct: float


# ---------------------------------------------------------------------------
# Default participant roster
# ---------------------------------------------------------------------------

DEFAULT_PARTICIPANTS: list[MarketParticipant] = [
    MarketParticipant(
        name="Retail Bull",
        persona="Aggressive retail trader, buys dips, uses leverage, NIFTY options",
        risk_tolerance=0.8,
        capital=500_000,
    ),
    MarketParticipant(
        name="Institutional Bear",
        persona="Conservative fund manager, hedges with puts, reduces exposure on uncertainty",
        risk_tolerance=0.3,
        capital=50_000_000,
    ),
    MarketParticipant(
        name="Momentum Chaser",
        persona="Follows trend, buys breakouts, quick exits on reversal signals",
        risk_tolerance=0.6,
        capital=1_000_000,
    ),
    MarketParticipant(
        name="Mean Reversion",
        persona="Fades extremes, sells rallies near resistance, buys panic lows",
        risk_tolerance=0.4,
        capital=2_000_000,
    ),
    MarketParticipant(
        name="Options Writer",
        persona="Sells premium, collects theta decay, hedges delta with futures",
        risk_tolerance=0.5,
        capital=5_000_000,
    ),
]


# ---------------------------------------------------------------------------
# LLM prompt helpers
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are simulating a market participant in an Indian stock market scenario. "
    "Respond ONLY in this exact format on a single line: "
    "DIRECTION: <BUY|SELL|HOLD> | CONFIDENCE: <0.0-1.0> | RATIONALE: <one sentence>"
)

_USER_PROMPT_TEMPLATE = (
    "Persona: {persona}\n"
    "Risk tolerance: {risk_tolerance:.0%}\n"
    "Capital: ₹{capital:,.0f}\n\n"
    "Market event: {event}\n"
    "Instruments in focus: {instruments}\n"
    "Simulation step: {step}/{steps}\n\n"
    "What is your trading decision?"
)


def _build_messages(
    participant: MarketParticipant,
    event: str,
    instruments: list[str],
    step: int,
    steps: int,
) -> list[Any]:
    """Build LLM message list for a single participant decision call."""
    from packages.ai.src.llm_client import LLMMessage  # local import avoids circular

    return [
        LLMMessage(role="system", content=_SYSTEM_PROMPT),
        LLMMessage(
            role="user",
            content=_USER_PROMPT_TEMPLATE.format(
                persona=participant.persona,
                risk_tolerance=participant.risk_tolerance,
                capital=participant.capital,
                event=event,
                instruments=", ".join(instruments),
                step=step,
                steps=steps,
            ),
        ),
    ]


def _parse_response(text: str, participant: str, instrument: str) -> ParticipantAction:
    """Parse the structured LLM response into a ``ParticipantAction``.

    Falls back to ``HOLD`` with 0.0 confidence if parsing fails.
    """
    direction = "HOLD"
    confidence = 0.0
    rationale = text.strip()

    try:
        dir_match = re.search(r"DIRECTION:\s*(BUY|SELL|HOLD)", text, re.IGNORECASE)
        conf_match = re.search(r"CONFIDENCE:\s*([0-9.]+)", text, re.IGNORECASE)
        rat_match = re.search(r"RATIONALE:\s*(.+)", text, re.IGNORECASE)

        if dir_match:
            direction = dir_match.group(1).upper()
        if conf_match:
            confidence = min(1.0, max(0.0, float(conf_match.group(1))))
        if rat_match:
            rationale = rat_match.group(1).strip()
    except Exception:
        logger.debug("Could not parse LLM response for %s: %r", participant, text)

    return ParticipantAction(
        participant=participant,
        instrument=instrument,
        direction=direction,
        rationale=rationale,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _aggregate(actions: list[ParticipantAction]) -> tuple[str, float, float]:
    """Compute consensus direction and bull/bear percentages.

    Returns:
        Tuple of ``(consensus_direction, bull_pct, bear_pct)``.
    """
    directional = [a for a in actions if a.direction in ("BUY", "SELL")]
    buy_count = sum(1 for a in directional if a.direction == "BUY")
    sell_count = sum(1 for a in directional if a.direction == "SELL")
    hold_count = sum(1 for a in actions if a.direction == "HOLD")
    total = len(actions)

    if total == 0:
        return "HOLD", 0.0, 0.0

    bull_pct = buy_count / total * 100
    bear_pct = sell_count / total * 100

    if buy_count > sell_count and buy_count > hold_count:
        consensus = "BUY"
    elif sell_count > buy_count and sell_count > hold_count:
        consensus = "SELL"
    else:
        consensus = "HOLD"

    return consensus, bull_pct, bear_pct


# ---------------------------------------------------------------------------
# MarketSimulator
# ---------------------------------------------------------------------------


class MarketSimulator:
    """Simulate how a roster of market participants reacts to a market event.

    Uses the project's ``LLMClient`` to query each participant's response.
    All requests within a step are dispatched concurrently, bounded by
    *semaphore_limit* to avoid overwhelming the LLM provider.

    When called from a synchronous context (no running event loop),
    ``simulate_sync`` is available, or you can call ``asyncio.run(sim.simulate(...))``.

    Example::

        from packages.ai.src.llm_client import LLMClient
        from packages.ai.src.market_simulator import MarketSimulator

        llm = LLMClient()
        sim = MarketSimulator(llm_client=llm)
        result = asyncio.run(sim.simulate("RBI hikes rates by 50 bps", ["NIFTY", "BANKNIFTY"]))
        print(result.consensus_direction, result.bull_pct, result.bear_pct)
    """

    def __init__(
        self,
        llm_client: Any,
        participants: list[MarketParticipant] | None = None,
        semaphore_limit: int = 5,
    ) -> None:
        self._llm = llm_client
        self._participants = participants or DEFAULT_PARTICIPANTS
        self._semaphore_limit = semaphore_limit
        # Semaphore is created lazily inside the async method so it binds to
        # the correct event loop (important when running under pytest-asyncio).
        self._semaphore: asyncio.Semaphore | None = None

    # ------------------------------------------------------------------
    # Internal: single participant call
    # ------------------------------------------------------------------

    def _call_llm_sync(
        self,
        participant: MarketParticipant,
        event: str,
        instruments: list[str],
        step: int,
        steps: int,
    ) -> ParticipantAction:
        """Synchronous LLM call for one participant (used by thread pool)."""
        messages = _build_messages(participant, event, instruments, step, steps)
        instrument = instruments[0] if instruments else "MARKET"
        try:
            response = self._llm.chat(messages)
            text = response.content if response.success else ""
        except Exception as exc:
            logger.warning("LLM call failed for %s: %s", participant.name, exc)
            text = ""
        return _parse_response(text, participant.name, instrument)

    async def _call_participant_async(
        self,
        participant: MarketParticipant,
        event: str,
        instruments: list[str],
        step: int,
        steps: int,
        semaphore: asyncio.Semaphore,
    ) -> ParticipantAction:
        """Semaphore-bounded async participant call.

        If the LLM client exposes an ``async_chat`` coroutine it is awaited
        directly.  Otherwise the synchronous ``chat`` method is dispatched to
        the default thread-pool executor so the event loop is never blocked.
        """
        async with semaphore:
            messages = _build_messages(participant, event, instruments, step, steps)
            instrument = instruments[0] if instruments else "MARKET"
            try:
                if hasattr(self._llm, "async_chat"):
                    # Async-capable LLM client (future extension point)
                    response = await self._llm.async_chat(messages)
                    text = response.content if response.success else ""
                else:
                    # Run synchronous LLM call in thread pool to avoid blocking
                    loop = asyncio.get_running_loop()
                    action_future = loop.run_in_executor(
                        None,
                        lambda p=participant: self._call_llm_sync(
                            p, event, instruments, step, steps
                        ),
                    )
                    return await action_future
            except Exception as exc:
                logger.warning(
                    "Async participant call failed for %s: %s", participant.name, exc
                )
                text = ""
            return _parse_response(text, participant.name, instrument)

    # ------------------------------------------------------------------
    # Public API — async
    # ------------------------------------------------------------------

    async def simulate(
        self,
        event: str,
        instruments: list[str],
        steps: int = 3,
    ) -> SimulationResult:
        """Run a multi-step ensemble simulation of participant reactions.

        Each step gathers all participant actions concurrently (semaphore
        bounded).  Subsequent steps could model updated beliefs, but in this
        implementation each step is an independent reaction to the same event
        so that results remain deterministic and comparable across runs.

        Args:
            event: Market event description (e.g. "RBI hikes rates by 50 bps").
            instruments: List of instrument symbols to consider.
            steps: Number of simulation rounds.

        Returns:
            ``SimulationResult`` with all actions and aggregated consensus.
        """
        semaphore = asyncio.Semaphore(self._semaphore_limit)
        all_actions: list[ParticipantAction] = []

        for step in range(1, steps + 1):
            tasks = [
                self._call_participant_async(p, event, instruments, step, steps, semaphore)
                for p in self._participants
            ]
            step_actions: list[ParticipantAction] = await asyncio.gather(*tasks)
            all_actions.extend(step_actions)
            logger.debug(
                "Step %d/%d complete — %d actions gathered", step, steps, len(step_actions)
            )

        consensus, bull_pct, bear_pct = _aggregate(all_actions)
        return SimulationResult(
            event=event,
            instruments=instruments,
            steps=steps,
            actions=all_actions,
            consensus_direction=consensus,
            bull_pct=bull_pct,
            bear_pct=bear_pct,
        )

    # ------------------------------------------------------------------
    # Public API — synchronous convenience wrapper
    # ------------------------------------------------------------------

    def simulate_sync(
        self,
        event: str,
        instruments: list[str],
        steps: int = 3,
        max_workers: int | None = None,
    ) -> SimulationResult:
        """Synchronous simulation using ``ThreadPoolExecutor``.

        Use this when you are in a plain synchronous context and cannot call
        ``asyncio.run()``, for example inside an existing synchronous
        pipeline.  All participant calls are dispatched to a thread pool so
        they run concurrently up to *max_workers* at a time.

        Args:
            event: Market event description.
            instruments: List of instrument symbols.
            steps: Number of simulation rounds.
            max_workers: Thread pool size (defaults to ``semaphore_limit``).

        Returns:
            ``SimulationResult`` with consensus and all participant actions.
        """
        workers = max_workers or self._semaphore_limit
        all_actions: list[ParticipantAction] = []

        with ThreadPoolExecutor(max_workers=workers) as executor:
            for step in range(1, steps + 1):
                futures = [
                    executor.submit(
                        self._call_llm_sync, p, event, instruments, step, steps
                    )
                    for p in self._participants
                ]
                step_actions = [f.result() for f in futures]
                all_actions.extend(step_actions)
                logger.debug(
                    "Step %d/%d complete (sync) — %d actions", step, steps, len(step_actions)
                )

        consensus, bull_pct, bear_pct = _aggregate(all_actions)
        return SimulationResult(
            event=event,
            instruments=instruments,
            steps=steps,
            actions=all_actions,
            consensus_direction=consensus,
            bull_pct=bull_pct,
            bear_pct=bear_pct,
        )
