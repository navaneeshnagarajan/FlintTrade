"""FlintTrade AI package — LLM, RAG, ML signals, sentiment, MCP, advisor, memory."""

__version__ = "0.1.0-alpha"

from .advisor import PortfolioSuggestion, StockAdvisor, StockFeatures, StockRanking
from .analyst_chain import AnalysisState, AnalystChain
from .llm_client import LLMClient, LLMConfig, LLMMessage, LLMProvider, LLMResponse
from .mcp_bridge import MCPBridge, MCPResult, MCPToolCall
from .memory import MemoryItem, MemoryLayer, MemoryQueryResult, TradedMemory
from .rag import Document, RAGEngine, RAGResponse, RetrievedChunk
from .sentiment import (
    AggregatedSentiment,
    SentimentAnalyzer,
    SentimentScore,
)
from .pipeline import SignalPipeline
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
]
