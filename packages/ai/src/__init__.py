"""FlintTrade AI package — LLM, RAG, ML signals, sentiment, MCP, advisor, memory."""

__version__ = "0.1.0-alpha"

from .advisor import PortfolioSuggestion, StockAdvisor, StockFeatures, StockRanking
from .analyst_chain import AnalysisState, AnalystChain
from .agent_models import AgentAnalysis, AgentRole, AgentRoleType, TeamAnalysis, TradeRecommendation
from .multi_agent import AgentTeam, default_agents
from .news_summarizer import MarketNewsSummarizer, NewsSummary
from .llm_client import LLMClient, LLMConfig, LLMMessage, LLMProvider, LLMResponse
from .mcp_bridge import MCPBridge, MCPResult, MCPToolCall
from .openclaw_bridge import OpenClawAgent, OpenClawBridge
from .memory import MemoryItem, MemoryLayer, MemoryQueryResult, TradedMemory
from .rag import Document, RAGEngine, RAGResponse, RetrievedChunk
from .sentiment import (
    AggregatedSentiment,
    SentimentAnalyzer,
    SentimentScore,
)
from .market_simulator import (
    DEFAULT_PARTICIPANTS,
    MarketParticipant,
    MarketSimulator,
    ParticipantAction,
    SimulationResult,
)
from .pipeline import SignalPipeline
from .signal_models import Signal as LiveSignal
from .signal_models import SignalConfig
from .signal_pipeline import LiveSignalPipeline
from .signals import Signal, SignalGenerator, compute_turbulence, generate_sharpe_labels
from .risk_debate import DebateResult, DebateRound, RiskDebate
from .ensemble_selector import (
    EnsembleResult,
    EnsembleSelector,
    ModelCandidate,
    compute_dissimilarity_index,
)
from .hyperopt_strategy import OptimisationResult, StrategyOptimiser

__all__ = [
    # LLM
    "LLMClient",
    "LLMConfig",
    "LLMMessage",
    "LLMResponse",
    "LLMProvider",
    # RAG
    "RAGEngine",
    "Document",
    "RetrievedChunk",
    "RAGResponse",
    # Signals
    "SignalGenerator",
    "SignalPipeline",
    "Signal",
    # Live signal pipeline (v0.5.0)
    "LiveSignal",
    "LiveSignalPipeline",
    "SignalConfig",
    # Sentiment
    "SentimentAnalyzer",
    "SentimentScore",
    "AggregatedSentiment",
    # MCP
    "MCPBridge",
    "MCPToolCall",
    "MCPResult",
    # Advisor
    "StockAdvisor",
    "StockFeatures",
    "StockRanking",
    "PortfolioSuggestion",
    # Memory
    "TradedMemory",
    "MemoryLayer",
    "MemoryItem",
    "MemoryQueryResult",
    # Analyst chain
    "AnalystChain",
    "AnalysisState",
    # Multi-agent team
    "AgentTeam",
    "AgentRole",
    "AgentRoleType",
    "AgentAnalysis",
    "TeamAnalysis",
    "TradeRecommendation",
    "default_agents",
    # News summarizer
    "MarketNewsSummarizer",
    "NewsSummary",
    # Market simulator
    "MarketSimulator",
    "MarketParticipant",
    "ParticipantAction",
    "SimulationResult",
    "DEFAULT_PARTICIPANTS",
    # OpenClaw bridge
    "OpenClawBridge",
    "OpenClawAgent",
    # Extended signal functions
    "generate_sharpe_labels",
    "compute_turbulence",
    # Risk debate (from TradingAgents)
    "RiskDebate",
    "DebateResult",
    "DebateRound",
    # Ensemble selector (from FinRL)
    "EnsembleSelector",
    "EnsembleResult",
    "ModelCandidate",
    "compute_dissimilarity_index",
    # Hyperopt (from freqtrade)
    "StrategyOptimiser",
    "OptimisationResult",
]
