"""RAG (Retrieval Augmented Generation) for trading knowledge.

Uses ChromaDB for vector storage and sentence-transformers for embeddings.
Indexes strategy docs, market reports, OpenAlgo API docs, and trade journals.
Chunks documents into 1000-token pieces with 200-token overlap.
Retrieval uses a similarity threshold of 0.7 to filter low-quality matches.

Config values adapted from openalgo-chatbot audit:
  - chunk_size=1000  (was 512 — larger chunks preserve more context per retrieval)
  - overlap=200      (was 50  — wider overlap reduces boundary-cut information loss)
  - similarity_threshold=0.7 (new — drops chunks below 70% similarity to reduce noise)
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .llm_client import LLMClient, LLMMessage

logger = logging.getLogger("flinttrade.ai.rag")

_DEFAULT_COLLECTION = "flinttrade_docs"
_CHUNK_SIZE = 1000
_CHUNK_OVERLAP = 200
_SIMILARITY_THRESHOLD = 0.7


# ---------------------------------------------------------------------------
# Document types
# ---------------------------------------------------------------------------


@dataclass
class Document:
    """A single document to index."""

    content: str
    source: str = ""  # file path or URL
    doc_type: str = ""  # "strategy", "market_report", "api_docs", "trade_journal"
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class RetrievedChunk:
    """A retrieved chunk with relevance score."""

    content: str
    source: str = ""
    doc_type: str = ""
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RAGResponse:
    """Response from RAG query."""

    answer: str = ""
    chunks_used: list[RetrievedChunk] = field(default_factory=list)
    query: str = ""
    error: str = ""

    @property
    def success(self) -> bool:
        return bool(self.answer) and not self.error


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def chunk_text(
    text: str,
    chunk_size: int = _CHUNK_SIZE,
    overlap: int = _CHUNK_OVERLAP,
) -> list[str]:
    """Split text into overlapping chunks by approximate token count.

    Uses ~4 chars per token as a rough estimate.
    """
    char_chunk = chunk_size * 4
    char_overlap = overlap * 4

    if len(text) <= char_chunk:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + char_chunk
        # Try to break at sentence boundary
        if end < len(text):
            for sep in (". ", "\n\n", "\n", " "):
                last_sep = text.rfind(sep, start + char_chunk // 2, end)
                if last_sep > start:
                    end = last_sep + len(sep)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - char_overlap
        if start <= 0:
            break

    return chunks


def content_hash(text: str) -> str:
    """Generate a stable hash for deduplication."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# RAG Engine
# ---------------------------------------------------------------------------


class RAGEngine:
    """RAG engine using ChromaDB and sentence-transformers.

    Usage::

        rag = RAGEngine(llm_client=llm)
        rag.index_document(Document(content="NIFTY options...", doc_type="strategy"))
        rag.index_directory("docs/")
        response = rag.query("What is max pain?")
        print(response.answer)
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        collection_name: str = _DEFAULT_COLLECTION,
        persist_directory: str | None = None,
        embedding_model: str = "all-MiniLM-L6-v2",
    ) -> None:
        self._llm = llm_client
        self._collection_name = collection_name
        self._persist_dir = persist_directory
        self._embedding_model_name = embedding_model
        self._chroma_client = None
        self._collection = None
        self._embedding_fn = None

    def _get_collection(self) -> Any:
        """Lazy-initialise ChromaDB collection."""
        if self._collection is not None:
            return self._collection

        try:
            import chromadb
            from chromadb.utils import embedding_functions
        except ImportError:
            raise ImportError("chromadb required — pip install chromadb")

        if self._persist_dir:
            self._chroma_client = chromadb.PersistentClient(path=self._persist_dir)
        else:
            self._chroma_client = chromadb.Client()

        try:
            self._embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=self._embedding_model_name,
            )
        except Exception:
            self._embedding_fn = embedding_functions.DefaultEmbeddingFunction()
            logger.warning("sentence-transformers not available, using default embeddings")

        self._collection = self._chroma_client.get_or_create_collection(
            name=self._collection_name,
            embedding_function=self._embedding_fn,
        )
        logger.info("ChromaDB collection '%s' initialised, %d docs", self._collection_name, self._collection.count())
        return self._collection

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def index_document(self, doc: Document) -> int:
        """Index a single document. Returns number of chunks indexed."""
        collection = self._get_collection()
        chunks = chunk_text(doc.content)
        if not chunks:
            return 0

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, str]] = []

        for i, chunk in enumerate(chunks):
            chunk_id = f"{content_hash(doc.source or doc.content)}_{i}"
            ids.append(chunk_id)
            documents.append(chunk)
            metadatas.append({
                "source": doc.source,
                "doc_type": doc.doc_type,
                "chunk_index": str(i),
                **doc.metadata,
            })

        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        logger.info("Indexed %d chunks from %s", len(chunks), doc.source or "inline")
        return len(chunks)

    def index_file(self, file_path: str, doc_type: str = "") -> int:
        """Index a text/markdown file."""
        path = Path(file_path)
        if not path.exists():
            logger.warning("File not found: %s", file_path)
            return 0

        content = path.read_text(encoding="utf-8", errors="replace")
        if not content.strip():
            return 0

        inferred_type = doc_type or self._infer_doc_type(path.name)
        return self.index_document(Document(
            content=content,
            source=str(path),
            doc_type=inferred_type,
        ))

    def index_directory(self, dir_path: str, extensions: tuple[str, ...] = (".md", ".txt", ".py")) -> int:
        """Recursively index all matching files in a directory."""
        total = 0
        for path in Path(dir_path).rglob("*"):
            if path.is_file() and path.suffix in extensions:
                total += self.index_file(str(path))
        logger.info("Indexed %d total chunks from %s", total, dir_path)
        return total

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        n_results: int = 5,
        doc_type: str | None = None,
        similarity_threshold: float = _SIMILARITY_THRESHOLD,
    ) -> list[RetrievedChunk]:
        """Retrieve relevant chunks for a query.

        Args:
            query: The search query text.
            n_results: Maximum number of results to fetch from the vector store
                before threshold filtering. The returned list may be smaller.
            doc_type: Optional filter to restrict results to a specific doc type.
            similarity_threshold: Minimum cosine similarity (0–1) required for a
                chunk to be included. Defaults to 0.7. Set to 0.0 to disable.

        Returns:
            List of chunks whose similarity score meets the threshold, sorted
            by descending score.
        """
        collection = self._get_collection()

        where_filter = None
        if doc_type:
            where_filter = {"doc_type": doc_type}

        results = collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where_filter,
        )

        chunks: list[RetrievedChunk] = []
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for i, doc_text in enumerate(documents):
            meta = metadatas[i] if i < len(metadatas) else {}
            dist = distances[i] if i < len(distances) else 1.0
            score = 1.0 - dist  # Convert L2/cosine distance to similarity
            if score < similarity_threshold:
                logger.debug(
                    "Dropped chunk from '%s' (score=%.3f < threshold=%.3f)",
                    meta.get("source", ""),
                    score,
                    similarity_threshold,
                )
                continue
            chunks.append(RetrievedChunk(
                content=doc_text,
                source=meta.get("source", ""),
                doc_type=meta.get("doc_type", ""),
                score=score,
                metadata=meta,
            ))

        return chunks

    # ------------------------------------------------------------------
    # Query (retrieve + generate)
    # ------------------------------------------------------------------

    def query(
        self,
        question: str,
        n_results: int = 5,
        doc_type: str | None = None,
        system_prompt: str = "",
        similarity_threshold: float = _SIMILARITY_THRESHOLD,
    ) -> RAGResponse:
        """Answer a question using RAG: retrieve relevant chunks, then generate."""
        if not self._llm:
            return RAGResponse(query=question, error="No LLM client configured")

        chunks = self.retrieve(question, n_results, doc_type, similarity_threshold)
        if not chunks:
            return RAGResponse(query=question, error="No relevant documents found")

        context = "\n\n---\n\n".join(c.content for c in chunks)
        system = system_prompt or (
            "You are a FlintTrade trading assistant. Answer the question using ONLY the "
            "provided context. If the context doesn't contain the answer, say so. "
            "Be concise and specific. Reference source documents when possible."
        )

        messages = [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=f"Context:\n{context}\n\nQuestion: {question}"),
        ]

        response = self._llm.chat(messages)
        return RAGResponse(
            answer=response.content,
            chunks_used=chunks,
            query=question,
            error=response.error,
        )

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def document_count(self) -> int:
        """Number of indexed chunks."""
        try:
            return self._get_collection().count()
        except Exception:
            return 0

    @staticmethod
    def _infer_doc_type(filename: str) -> str:
        name = filename.lower()
        if "strategy" in name or "strat" in name:
            return "strategy"
        if "api" in name or "openalgo" in name:
            return "api_docs"
        if "journal" in name or "trade" in name:
            return "trade_journal"
        if "report" in name or "market" in name:
            return "market_report"
        return "general"
