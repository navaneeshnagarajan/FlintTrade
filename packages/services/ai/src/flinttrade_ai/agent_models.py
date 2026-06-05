"""Data models for the multi-agent trading team.

Adapts patterns from:
- MiroFish (CAMEL-AI/OASIS): agent roles with specialised system prompts,
  environment observation, consensus via aggregation.
- TradingAgents: independent analyst personas (market, fundamentals,
  sentiment, news), risk debate (aggressive/conservative/neutral),
  and a judge/aggregator that produces a final recommendation.

All models are plain dataclasses with ``to_dict()`` for JSON serialisation.
No external dependencies beyond the standard library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


class AgentRoleType(StrEnum):
    """Supported agent role types in a trading team."""

    TECHNICAL = "technical"
    FUNDAMENTAL = "fundamental"
    SENTIMENT = "sentiment"
    RISK_MANAGER = "risk_manager"
    AGGREGATOR = "aggregator"


@dataclass
class AgentRole:
    """Definition of an agent's role within the team.

    Each agent has a unique ``name``, a ``role_type`` that determines its
    specialisation, and a ``system_prompt`` used when calling the LLM.
    ``enabled`` controls whether the agent participates in analysis.

    Attributes:
        name: Human-readable agent name (e.g. "Technical Analyst").
        role_type: One of ``AgentRoleType`` values.
        system_prompt: System message sent to the LLM for this agent.
        enabled: Whether this agent participates in team analysis.
        temperature: Optional per-agent temperature override.
    """

    name: str
    role_type: AgentRoleType
    system_prompt: str
    enabled: bool = True
    temperature: float | None = None

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dictionary."""
        return {
            "name": self.name,
            "role_type": self.role_type.value,
            "system_prompt": self.system_prompt,
            "enabled": self.enabled,
            "temperature": self.temperature,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> AgentRole:
        """Create an AgentRole from a dictionary."""
        return cls(
            name=str(data.get("name", "")),
            role_type=AgentRoleType(str(data.get("role_type", "technical"))),
            system_prompt=str(data.get("system_prompt", "")),
            enabled=bool(data.get("enabled", True)),
            temperature=float(data["temperature"]) if data.get("temperature") is not None else None,
        )


@dataclass
class AgentAnalysis:
    """Analysis produced by a single agent.

    Attributes:
        agent_name: Name of the agent that produced this analysis.
        role_type: The agent's role type.
        report: Free-text analysis report from the LLM.
        signal: Agent's individual signal ("BUY", "SELL", or "HOLD").
        confidence: Agent's confidence in its signal (0.0 to 1.0).
        timestamp: ISO-8601 timestamp when the analysis was produced.
        error: Error message if the agent failed (empty on success).
    """

    agent_name: str
    role_type: str
    report: str = ""
    signal: str = "HOLD"  # "BUY" | "SELL" | "HOLD"
    confidence: float = 0.0
    timestamp: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    @property
    def success(self) -> bool:
        """Whether this analysis completed without error."""
        return bool(self.report) and not self.error

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dictionary."""
        return {
            "agent_name": self.agent_name,
            "role_type": self.role_type,
            "report": self.report,
            "signal": self.signal,
            "confidence": round(self.confidence, 4),
            "timestamp": self.timestamp,
            "error": self.error,
        }


@dataclass
class TeamAnalysis:
    """Combined analysis from the full agent team.

    Contains individual agent analyses plus the aggregated result.

    Attributes:
        symbol: Instrument symbol analysed.
        exchange: Exchange code.
        agent_analyses: List of individual agent analyses.
        consensus_signal: Aggregated signal from the Aggregator.
        consensus_confidence: Aggregated confidence score.
        consensus_reasoning: Aggregator's reasoning text.
        timestamp: ISO-8601 timestamp of the team analysis.
        errors: List of error strings from failed agents.
    """

    symbol: str
    exchange: str
    agent_analyses: list[AgentAnalysis] = field(default_factory=list)
    consensus_signal: str = "HOLD"
    consensus_confidence: float = 0.0
    consensus_reasoning: str = ""
    timestamp: str = ""
    errors: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dictionary."""
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "agent_analyses": [a.to_dict() for a in self.agent_analyses],
            "consensus_signal": self.consensus_signal,
            "consensus_confidence": round(self.consensus_confidence, 4),
            "consensus_reasoning": self.consensus_reasoning,
            "timestamp": self.timestamp,
            "errors": self.errors,
        }


@dataclass
class TradeRecommendation:
    """Final trade recommendation produced by the agent team.

    A simplified view of TeamAnalysis for consumption by the UI
    and downstream order logic.

    Attributes:
        symbol: Instrument symbol.
        exchange: Exchange code.
        action: "BUY", "SELL", or "HOLD".
        confidence: Aggregated confidence (0.0 to 1.0).
        reasoning: Aggregator's reasoning summary.
        agent_count: Number of agents that contributed.
        bullish_count: Agents that signalled BUY.
        bearish_count: Agents that signalled SELL.
        neutral_count: Agents that signalled HOLD.
        timestamp: ISO-8601 timestamp.
    """

    symbol: str
    exchange: str
    action: str = "HOLD"
    confidence: float = 0.0
    reasoning: str = ""
    agent_count: int = 0
    bullish_count: int = 0
    bearish_count: int = 0
    neutral_count: int = 0
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dictionary."""
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "action": self.action,
            "confidence": round(self.confidence, 4),
            "reasoning": self.reasoning,
            "agent_count": self.agent_count,
            "bullish_count": self.bullish_count,
            "bearish_count": self.bearish_count,
            "neutral_count": self.neutral_count,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_team_analysis(cls, ta: TeamAnalysis) -> TradeRecommendation:
        """Create a TradeRecommendation from a TeamAnalysis."""
        successful = [a for a in ta.agent_analyses if a.success]
        return cls(
            symbol=ta.symbol,
            exchange=ta.exchange,
            action=ta.consensus_signal,
            confidence=ta.consensus_confidence,
            reasoning=ta.consensus_reasoning,
            agent_count=len(successful),
            bullish_count=sum(1 for a in successful if a.signal == "BUY"),
            bearish_count=sum(1 for a in successful if a.signal == "SELL"),
            neutral_count=sum(1 for a in successful if a.signal == "HOLD"),
            timestamp=ta.timestamp,
        )
