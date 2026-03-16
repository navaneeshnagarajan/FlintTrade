"""FlintTrade AI package — LLM, RAG, ML signals, sentiment, MCP, advisor."""

__version__ = "0.1.0-dev"

from .advisor import PortfolioSuggestion, StockAdvisor, StockFeatures, StockRanking
from .llm_client import LLMClient, LLMConfig, LLMMessage, LLMProvider, LLMResponse
from .mcp_bridge import MCPBridge, MCPResult, MCPToolCall
from .rag import Document, RAGEngine, RAGResponse, RetrievedChunk
from .sentiment import (
    AggregatedSentiment,
    SentimentAnalyzer,
    SentimentScore,
)
from .signals import Signal, SignalGenerator

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
]
