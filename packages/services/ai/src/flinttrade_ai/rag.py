"""Compatibility imports for the canonical RAG pipeline.

The implementation was consolidated into :mod:`flinttrade_ai.rag_pipeline`.
This module preserves existing ``flinttrade_ai.rag`` imports without keeping a
second loader, chunker, vector store, or query path.
"""

from .rag_pipeline import (
    Document,
    LegacyRetrievedChunk as RetrievedChunk,
    RAGEngine,
    RAGResponse,
    chunk_text,
    content_hash,
)

__all__ = [
    "Document",
    "RAGEngine",
    "RAGResponse",
    "RetrievedChunk",
    "chunk_text",
    "content_hash",
]
