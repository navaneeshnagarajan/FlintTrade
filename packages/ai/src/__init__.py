"""FlintTrade AI package — LLM, RAG, ML signals, sentiment, MCP, advisor, memory."""

__version__ = "0.1.0-alpha"

from .advisor import PortfolioSuggestion, StockAdvisor, StockFeatures, StockRanking
from .analyst_chain import AnalysisState, AnalystChain
from .news_summarizer import MarketNewsSummarizer, NewsSummary
from .llm_client import LLMClient, LLMConfig, LLMMessage, LLMProvider, LLMResponse
from .mcp_bridge import MCPBridge, MCPResult, MCPToolCall
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
from .signals import Signal, SignalGenerator, compute_turbulence, generate_sharpe_labels

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
    # News summarizer
    "MarketNewsSummarizer",
    "NewsSummary",
    # Market simulator
    "MarketSimulator",
    "MarketParticipant",
    "ParticipantAction",
    "SimulationResult",
    "DEFAULT_PARTICIPANTS",
    # Extended signal functions
    "generate_sharpe_labels",
    "compute_turbulence",
]
