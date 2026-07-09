"""FlintTrade AI package — LLM, RAG, ML signals, sentiment, MCP, advisor, memory."""

from flinttrade_core.version import APP_VERSION

__version__ = APP_VERSION

from .advisor import PortfolioSuggestion, StockAdvisor, StockFeatures, StockRanking
from .analyst_chain import AnalysisState, AnalystChain
from .agent_models import AgentAnalysis, AgentRole, AgentRoleType, TeamAnalysis, TradeRecommendation
from .multi_agent import AgentTeam, AutonomousResearchLoop, ResearchIteration, default_agents
from .rag_pipeline import (
    Document,
    DomainFilter,
    LegacyRetrievedChunk as RetrievedChunk,
    PipelineConfig,
    RAGEngine,
    RAGPipeline,
    RAGResponse,
)
from .news_summarizer import MarketNewsSummarizer, NewsSummary
from .llm_client import LLMClient, LLMConfig, LLMMessage, LLMProvider, LLMResponse
from .mcp_bridge import MCPBridge, MCPResult, MCPToolCall
from .agent_backends import (
    AGENT_BACKEND_CATALOGUE,
    AgentAuthMode,
    AgentBackendKind,
    AgentBackendProfile,
    AgentBackendUnavailable,
    AgentEvent,
    AgentEventKind,
    AgentSession,
    BackendStatus,
    CodexAppServerSession,
    backend_ids,
    detect_backend,
    get_backend,
    get_session,
    list_backends,
    register_backend,
)
from .memory import (
    CATEGORY_IMPORTANCE,
    HierarchicalMemoryManager,
    MemoryBackend,
    MemoryBackendConfig,
    MemoryBackendKind,
    MemoryEntry,
    MemoryItem,
    MemoryLayer,
    MemoryManager,
    MemoryQueryResult,
    MemoryTier,
    TradedMemory,
    create_memory_backend,
)
from .sentiment import (
    AggregatedSentiment,
    NewsArticle,
    NewsScraper,
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
    calculate_di,
    compute_dissimilarity_index,
)
from .regime_detector import (
    RegimeResult,
    RegimeState,
    detect_regime,
    detect_regime_detailed,
)
from .hyperopt_strategy import OptimisationResult, StrategyOptimiser
from .strategy_refiner import RefinementSuggestion, StrategyRefiner
from .trade_reflection import ReflectionConfig, ReflectionResult, TradeOutcome, TradeReflector
from .news_scheduler import NewsEvent, NewsScheduler, PollType, ScheduledJob

__all__ = [
    # LLM
    "LLMClient",
    "LLMConfig",
    "LLMMessage",
    "LLMResponse",
    "LLMProvider",
    # RAG
    "RAGEngine",
    "RAGPipeline",
    "PipelineConfig",
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
    "MemoryEntry",
    "MemoryManager",
    "HierarchicalMemoryManager",
    "MemoryTier",
    "MemoryBackendConfig",
    "MemoryBackendKind",
    "MemoryBackend",
    "CATEGORY_IMPORTANCE",
    "create_memory_backend",
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
    "AutonomousResearchLoop",
    "ResearchIteration",
    # News scraper (RSS/httpx)
    "NewsScraper",
    "NewsArticle",
    # News summarizer
    "MarketNewsSummarizer",
    "NewsSummary",
    # Market simulator
    "MarketSimulator",
    "MarketParticipant",
    "ParticipantAction",
    "SimulationResult",
    "DEFAULT_PARTICIPANTS",
    # Agent backends (replaces the removed OpenClaw external-gateway bridge)
    "AGENT_BACKEND_CATALOGUE",
    "AgentAuthMode",
    "AgentBackendKind",
    "AgentBackendProfile",
    "AgentBackendUnavailable",
    "AgentEvent",
    "AgentEventKind",
    "AgentSession",
    "BackendStatus",
    "CodexAppServerSession",
    "backend_ids",
    "detect_backend",
    "get_backend",
    "get_session",
    "list_backends",
    "register_backend",
    # Extended signal functions
    "generate_sharpe_labels",
    "compute_turbulence",
    # Risk debate (from TradingAgents)
    "RiskDebate",
    "DebateResult",
    "DebateRound",
    # Ensemble selector (from FinRL + FreqAI DI)
    "EnsembleSelector",
    "EnsembleResult",
    "ModelCandidate",
    "calculate_di",
    "compute_dissimilarity_index",
    # Regime detector (ADX + BB + ATR)
    "RegimeState",
    "RegimeResult",
    "detect_regime",
    "detect_regime_detailed",
    # RAG domain filter
    "DomainFilter",
    # Hyperopt (from freqtrade)
    "StrategyOptimiser",
    "OptimisationResult",
    # Strategy refiner
    "StrategyRefiner",
    "RefinementSuggestion",
    # Trade reflection (LLM-TradeBot pattern — batch analysis)
    "TradeReflector",
    "ReflectionConfig",
    "ReflectionResult",
    "TradeOutcome",
    # News scheduler (FinSights pattern — IST-scheduled RSS polling)
    "NewsScheduler",
    "NewsEvent",
    "PollType",
    "ScheduledJob",
]
