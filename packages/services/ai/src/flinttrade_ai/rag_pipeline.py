"""Full RAG pipeline for FlintTrade AI package.

Provides a self-contained, configurable RAG chain:

    DocumentLoader  → load .md / .txt / .py / .pdf files from a directory.
    TextChunker     → split documents into overlapping chunks.
    EmbeddingProvider → sentence-transformers or OpenAI-compatible embeddings.
    VectorStore     → local sqlite similarity search.
    RAGPipeline     → orchestrates the full query → retrieve → generate chain.

Design:
- All settings are Pydantic models so the pipeline is configurable without
  subclassing.
- Embedding provider is pluggable: sentence-transformers (default, offline)
  or any callable that maps List[str] → List[List[float]].
- The vector store is lazily initialised from sqlite3 + numpy.
- The LLM generation step is optional; callers can use the pipeline in
  retrieval-only mode by calling ``retrieve()`` instead of ``query()``.

Adapted from: openalgo-chatbot/openalgo_documentation_chatbot.py
Extended with:
  - Context-preserving chunk_size / overlap defaults (1000 / 200).
  - PDF support via pypdf (not PyPDF2 — maintained fork).
  - EmbeddingProvider abstraction so OpenAI embeddings can be swapped in.
  - Pydantic config models.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

logger = logging.getLogger("flinttrade.ai.rag_pipeline")

# ---------------------------------------------------------------------------
# Default constants
# ---------------------------------------------------------------------------

_DEFAULT_CHUNK_SIZE = 1000  # tokens (approximate, ~4 chars / token)
_DEFAULT_CHUNK_OVERLAP = 200  # token overlap between adjacent chunks
_DEFAULT_TOP_K = 5
_DEFAULT_SIMILARITY_THRESHOLD = 0.7
_DEFAULT_COLLECTION = "flinttrade_docs"
_DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
_EMBEDDING_MODE_METADATA_KEY = "flinttrade_embedding_mode"
_DISTANCE_SPACE_METADATA_KEY = "flinttrade_distance_space"
_EMBEDDING_MODE_EXTERNAL = "external"
_EMBEDDING_MODE_CHROMA = "chroma"

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class PipelineConfig(BaseModel):
    """Configuration for RAGPipeline.

    Attributes:
        chunk_size:           Approximate chunk size in tokens.
        chunk_overlap:        Overlap between adjacent chunks in tokens.
        embedding_model:      sentence-transformers model name.
        embedding_provider:   ``"sentence_transformers"`` or ``"openai"``.
        openai_api_base:      Base URL for OpenAI-compatible embedding endpoint.
        openai_api_key:       API key for the embedding endpoint.
        collection_name:      Vector collection name.
        persist_directory:    Persist the vector store to disk at this path. Empty = in-memory.
        top_k:                Default number of chunks to retrieve.
        similarity_threshold: Minimum cosine similarity score (0–1) for results.
    """

    chunk_size: int = Field(default=_DEFAULT_CHUNK_SIZE, ge=1)
    chunk_overlap: int = Field(default=_DEFAULT_CHUNK_OVERLAP, ge=0)
    embedding_model: str = _DEFAULT_EMBEDDING_MODEL
    embedding_provider: str = "sentence_transformers"
    openai_api_base: str = ""
    openai_api_key: str = ""
    collection_name: str = _DEFAULT_COLLECTION
    persist_directory: str = ""
    top_k: int = Field(default=_DEFAULT_TOP_K, ge=1)
    similarity_threshold: float = Field(default=_DEFAULT_SIMILARITY_THRESHOLD, ge=0.0, le=1.0)


@dataclass
class LoadedDocument:
    """A single document loaded from disk.

    Attributes:
        content:    Full text content.
        source:     Absolute file path.
        doc_type:   Inferred or provided document type tag.
        metadata:   Arbitrary key→value pairs for filtering.
    """

    content: str
    source: str = ""
    doc_type: str = "general"
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class TextChunk:
    """A single text chunk ready for embedding.

    Attributes:
        content:    Chunk text.
        chunk_id:   Deterministic ID for deduplication.
        source:     Origin file path.
        doc_type:   Document type tag.
        chunk_index: Position index within the source document.
        metadata:   Passthrough metadata from the source document.
    """

    content: str
    chunk_id: str
    source: str = ""
    doc_type: str = "general"
    chunk_index: int = 0
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class RetrievedChunk:
    """A retrieved chunk with a similarity score.

    Attributes:
        content:  Chunk text.
        source:   Origin file path.
        doc_type: Document type tag.
        score:    Cosine similarity (0–1). Higher is more relevant.
        metadata: Passthrough metadata.
    """

    content: str
    source: str = ""
    doc_type: str = "general"
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RAGResult:
    """Result from a full RAG query (retrieve + generate).

    Attributes:
        answer:      Generated answer text.
        query:       Original query string.
        chunks_used: Retrieved chunks that were passed to the LLM.
        error:       Non-empty string if an error occurred.
    """

    answer: str = ""
    query: str = ""
    chunks_used: list[RetrievedChunk] = field(default_factory=list)
    error: str = ""

    @property
    def success(self) -> bool:
        """True when an answer was generated without error."""
        return bool(self.answer) and not self.error


# Backwards-compatible input model. The old API used an empty doc-type default;
# the canonical loader keeps ``general`` as its explicit normalised default.
@dataclass
class Document(LoadedDocument):
    """Legacy document input accepted by the canonical pipeline."""

    doc_type: str = ""


@dataclass
class LegacyRetrievedChunk(RetrievedChunk):
    """Legacy retrieved chunk with the former empty doc-type default."""

    doc_type: str = ""


@dataclass(init=False)
class RAGResponse(RAGResult):
    """Legacy response constructor preserving ``answer, chunks, query, error``."""

    def __init__(
        self,
        answer: str = "",
        chunks_used: list[RetrievedChunk] | None = None,
        query: str = "",
        error: str = "",
    ) -> None:
        super().__init__(
            answer=answer,
            query=query,
            chunks_used=list(chunks_used or []),
            error=error,
        )


# ---------------------------------------------------------------------------
# DomainFilter — topic guard for the RAG pipeline
# ---------------------------------------------------------------------------


class DomainFilter:
    """Pre-query topic guard that rejects off-topic questions.

    Adapted from openalgo-chatbot's intent-filtering pattern: before
    hitting the vector store we confirm the query is finance/trading
    related via keyword matching.  An optional semantic similarity check
    can be wired in when an embedding provider is available.

    Two-stage check:
    1. **Keyword match** — fast O(n) scan against ``TRADING_KEYWORDS``.
       Any hit → on-topic.
    2. **Semantic similarity** (optional) — cosine similarity of the query
       embedding against a set of seed trading phrases.  If the similarity
       exceeds ``semantic_threshold`` the query is on-topic.

    If both stages fail the query is considered off-topic and
    ``is_on_topic`` returns False.

    Attributes:
        TRADING_KEYWORDS: Frozenset of 50+ trading and finance terms.
        REFUSAL_MESSAGE: Polite message returned to off-topic queries.

    Example::

        f = DomainFilter()
        if not f.is_on_topic("What is the weather today?"):
            print(f.REFUSAL_MESSAGE)
        # → "I can only help with trading and market-related questions."
    """

    TRADING_KEYWORDS: frozenset[str] = frozenset(
        {
            # Indian markets & instruments
            "nifty",
            "banknifty",
            "sensex",
            "nse",
            "bse",
            "mcx",
            "nfo",
            "fut",
            "ce",
            "pe",
            "otm",
            "itm",
            "atm",
            # Order types & execution
            "order",
            "buy",
            "sell",
            "trade",
            "position",
            "holding",
            "orderbook",
            "tradebook",
            "bracket",
            "cover",
            "limit",
            "market",
            "sl",
            "stoploss",
            "stop-loss",
            "target",
            "entry",
            "exit",
            # Options concepts
            "option",
            "options",
            "call",
            "put",
            "strike",
            "expiry",
            "expiration",
            "premium",
            "theta",
            "delta",
            "gamma",
            "vega",
            "rho",
            "iv",
            "implied volatility",
            "greeks",
            "hedging",
            "hedge",
            "straddle",
            "strangle",
            "spread",
            "iron condor",
            "butterfly",
            # Technical analysis
            "chart",
            "candle",
            "indicator",
            "rsi",
            "macd",
            "ema",
            "sma",
            "bollinger",
            "atr",
            "adx",
            "momentum",
            "volume",
            "support",
            "resistance",
            "breakout",
            "breakdown",
            "trend",
            "signal",
            # Portfolio & risk
            "portfolio",
            "pnl",
            "profit",
            "loss",
            "drawdown",
            "sharpe",
            "margin",
            "risk",
            "exposure",
            "allocation",
            "rebalance",
            # Market data & finance
            "price",
            "ltp",
            "ohlc",
            "ohlcv",
            "quote",
            "depth",
            "oi",
            "open interest",
            "pcr",
            "max pain",
            "vix",
            "fii",
            "dii",
            "sector",
            "equity",
            "fund",
            "etf",
            "mutual fund",
            "sip",
            "broker",
            "api",
            "backtest",
            "strategy",
            "algo",
            "automation",
            "ticker",
            "symbol",
            "exchange",
            "intraday",
            "swing",
            "positional",
            "adjust",
            "adjustment",
            "roll",
            "rolling",
            "trail",
            "trailing",
        }
    )

    REFUSAL_MESSAGE: str = "I can only help with trading and market-related questions."

    def __init__(
        self,
        extra_keywords: set[str] | None = None,
        semantic_threshold: float = 0.35,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        base = self.TRADING_KEYWORDS | {k.lower() for k in extra_keywords} if extra_keywords else self.TRADING_KEYWORDS
        # Pre-compile one regex per keyword using word boundaries so that
        # short abbreviations like "iv", "pe", "ce" do not match within
        # unrelated English words (e.g. "recipe", "sentence", "live").
        self._keyword_patterns: list[re.Pattern[str]] = [
            re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE) for kw in base
        ]
        self._semantic_threshold = semantic_threshold
        self._embedding_provider = embedding_provider

        # Seed phrases used for the optional semantic similarity check.
        self._seed_phrases: list[str] = [
            "stock market trading strategy",
            "options greeks delta gamma theta",
            "NIFTY futures open interest",
            "portfolio risk management drawdown",
            "technical analysis RSI MACD chart",
        ]
        self._seed_embeddings: list[list[float]] | None = None

    def is_on_topic(self, query: str) -> bool:
        """Return True when the query is finance / trading related.

        Stage 1: keyword match (fast, no external calls).
        Stage 2: semantic similarity (only when an EmbeddingProvider is
        configured and stage 1 fails).

        Args:
            query: Raw user query string.

        Returns:
            True if the query is on-topic; False if it should be refused.
        """
        # Stage 1 — keyword match (word-boundary regex to avoid false positives
        # from short abbreviations like "iv", "pe", "ce" inside common words)
        for pattern in self._keyword_patterns:
            if pattern.search(query):
                return True

        # Stage 2 — optional semantic similarity
        if self._embedding_provider is not None:
            try:
                if self._seed_embeddings is None:
                    self._seed_embeddings = self._embedding_provider.embed(self._seed_phrases)
                query_vec = self._embedding_provider.embed([query])[0]
                max_sim = max(self._cosine(query_vec, seed) for seed in self._seed_embeddings)
                if max_sim >= self._semantic_threshold:
                    return True
            except Exception as exc:  # noqa: BLE001
                logger.warning("Domain-filter embeddings unavailable; allowing retrieval: %s", exc)
                return True

        return False

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        """Cosine similarity between two equal-length float vectors."""
        dot = sum(ai * bi for ai, bi in zip(a, b))
        norm_a = math.sqrt(sum(ai * ai for ai in a))
        norm_b = math.sqrt(sum(bi * bi for bi in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# DocumentLoader
# ---------------------------------------------------------------------------


class DocumentLoader:
    """Load documents from .md, .txt, .py, and .pdf files.

    PDF support requires the ``pypdf`` package (``pip install pypdf``).
    Falls back gracefully to empty content if pypdf is not installed.

    Example::

        loader = DocumentLoader()
        docs = loader.load_directory("docs/")
    """

    SUPPORTED = {".md", ".txt", ".py", ".pdf"}

    def load_file(
        self,
        file_path: str | Path,
        doc_type: str = "",
        *,
        allow_unsupported_text: bool = False,
    ) -> LoadedDocument | None:
        """Load a single file and return a LoadedDocument.

        Args:
            file_path: Path to the file to load.
            doc_type:  Override document type tag. Auto-detected if empty.
            allow_unsupported_text: Read an explicitly selected suffix as UTF-8 text.

        Returns:
            LoadedDocument, or None if the file is unsupported / unreadable.
        """
        path = Path(file_path)
        if not path.exists():
            logger.warning("File not found: %s", file_path)
            return None
        if path.suffix.lower() not in self.SUPPORTED and not allow_unsupported_text:
            logger.debug("Unsupported file type: %s", path.suffix)
            return None

        content = self._read(path, allow_unsupported_text=allow_unsupported_text)
        if not content.strip():
            return None

        inferred = doc_type or self._infer_type(path.name)
        return LoadedDocument(content=content, source=str(path), doc_type=inferred)

    def load_directory(
        self,
        dir_path: str | Path,
        recursive: bool = True,
        extensions: tuple[str, ...] | None = None,
    ) -> list[LoadedDocument]:
        """Load all supported files in a directory.

        Args:
            dir_path:  Root directory to scan.
            recursive: Whether to recurse into subdirectories.
            extensions: Optional caller-selected subset of supported suffixes.

        Returns:
            List of successfully loaded documents.
        """
        root = Path(dir_path)
        if not root.is_dir():
            logger.warning("Not a directory: %s", dir_path)
            return []

        pattern = "**/*" if recursive else "*"
        caller_selected = extensions is not None
        selected = {suffix.lower() for suffix in extensions} if caller_selected else self.SUPPORTED
        docs: list[LoadedDocument] = []
        for path in root.glob(pattern):
            if path.is_file() and path.suffix.lower() in selected:
                doc = self.load_file(path, allow_unsupported_text=caller_selected)
                if doc is not None:
                    docs.append(doc)

        logger.info("Loaded %d documents from %s", len(docs), dir_path)
        return docs

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _read(self, path: Path, *, allow_unsupported_text: bool = False) -> str:
        suffix = path.suffix.lower()
        if suffix in {".md", ".txt", ".py"} or allow_unsupported_text:
            return path.read_text(encoding="utf-8", errors="replace")
        if suffix == ".pdf":
            return self._read_pdf(path)
        return ""

    @staticmethod
    def _read_pdf(path: Path) -> str:
        try:
            import pypdf  # type: ignore[import]

            reader = pypdf.PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            logger.warning("pypdf not installed — skipping PDF: %s", path.name)
            return ""
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to read PDF %s: %s", path.name, exc)
            return ""

    @staticmethod
    def _infer_type(filename: str) -> str:
        name = filename.lower()
        if any(k in name for k in ("strategy", "strat")):
            return "strategy"
        if any(k in name for k in ("api", "openalgo", "reference")):
            return "api_docs"
        if any(k in name for k in ("journal", "trade")):
            return "trade_journal"
        if any(k in name for k in ("report", "market", "news")):
            return "market_report"
        return "general"


# ---------------------------------------------------------------------------
# TextChunker
# ---------------------------------------------------------------------------


class TextChunker:
    """Split documents into overlapping text chunks.

    Uses a character-based approximation (4 chars ≈ 1 token) to stay fast
    without requiring a tokenizer dependency.

    Example::

        chunker = TextChunker(chunk_size=512, overlap=64)
        chunks = chunker.chunk_document(doc)
    """

    def __init__(self, chunk_size: int = _DEFAULT_CHUNK_SIZE, overlap: int = _DEFAULT_CHUNK_OVERLAP) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_text(self, text: str) -> list[str]:
        """Split text into overlapping character-window chunks.

        Args:
            text: Raw text to split.

        Returns:
            List of non-empty text chunks.
        """
        char_size = self.chunk_size * 4
        char_overlap = self.overlap * 4

        if len(text) <= char_size:
            return [text] if text.strip() else []

        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + char_size
            # Prefer breaking at a sentence / paragraph boundary.
            if end < len(text):
                for sep in (". ", "\n\n", "\n", " "):
                    last = text.rfind(sep, start + char_size // 2, end)
                    if last > start:
                        end = last + len(sep)
                        break
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            next_start = end - char_overlap
            if next_start <= start:
                break
            start = next_start

        return chunks

    def chunk_document(self, doc: LoadedDocument) -> list[TextChunk]:
        """Split a LoadedDocument into TextChunk objects.

        Args:
            doc: The document to chunk.

        Returns:
            List of TextChunk objects with deterministic IDs.
        """
        raw_chunks = self.chunk_text(doc.content)
        doc_hash = _content_hash(doc.source or doc.content)
        return [
            TextChunk(
                content=chunk,
                chunk_id=f"{doc_hash}_{i}",
                source=doc.source,
                doc_type=doc.doc_type,
                chunk_index=i,
                metadata=dict(doc.metadata),
            )
            for i, chunk in enumerate(raw_chunks)
        ]


def _content_hash(text: str, length: int = 16) -> str:
    """Return a short stable hash for deduplication."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def content_hash(text: str) -> str:
    """Return the canonical 16-character content hash."""
    return _content_hash(text)


def chunk_text(
    text: str,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    overlap: int = _DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """Split text with the canonical chunker using the public legacy API."""
    return TextChunker(chunk_size=chunk_size, overlap=overlap).chunk_text(text)


# ---------------------------------------------------------------------------
# EmbeddingProvider
# ---------------------------------------------------------------------------


class EmbeddingProvider:
    """Pluggable embedding backend.

    Supports:
    - ``"sentence_transformers"`` — local, offline, default.
    - ``"openai"`` — any OpenAI-compatible REST endpoint.
    - Any callable accepting ``List[str]`` and returning ``List[List[float]]``.

    Example::

        provider = EmbeddingProvider(model="all-MiniLM-L6-v2")
        vectors = provider.embed(["hello world", "market open"])
    """

    def __init__(
        self,
        model: str = _DEFAULT_EMBEDDING_MODEL,
        provider: str = "sentence_transformers",
        api_base: str = "",
        api_key: str = "",
        custom_fn: Callable[[list[str]], list[list[float]]] | None = None,
    ) -> None:
        self._model = model
        self._provider = provider
        self._api_base = api_base
        self._api_key = api_key
        self._custom_fn = custom_fn
        self._st_model: Any = None  # lazy-loaded SentenceTransformer

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts.

        Args:
            texts: List of strings to embed.

        Returns:
            List of embedding vectors.

        Raises:
            RuntimeError: If no embedding backend is available.
        """
        if not texts:
            return []
        if self._custom_fn is not None:
            return self._custom_fn(texts)
        if self._provider == "openai":
            return self._embed_openai(texts)
        return self._embed_sentence_transformers(texts)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _embed_sentence_transformers(self, texts: list[str]) -> list[list[float]]:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import]

            if self._st_model is None:
                self._st_model = SentenceTransformer(self._model)
            embeddings = self._st_model.encode(texts, show_progress_bar=False)
            return [vec.tolist() for vec in embeddings]
        except Exception as exc:  # noqa: BLE001 - signal Chroma's built-in fallback
            raise RuntimeError("sentence-transformers unavailable; use Chroma default embeddings") from exc

    def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        try:
            import openai  # type: ignore[import]
        except ImportError:
            raise RuntimeError("openai package not installed — pip install openai")

        client = openai.OpenAI(
            api_key=self._api_key or "sk-local",
            base_url=self._api_base or None,
        )
        response = client.embeddings.create(model=self._model, input=texts)
        return [item.embedding for item in response.data]


# ---------------------------------------------------------------------------
# VectorStore
# ---------------------------------------------------------------------------


class VectorStore:
    """Local sqlite vector store for semantic search.

    Lazily initialises the client on first use.

    Example::

        store = VectorStore(collection_name="docs")
        store.upsert(chunks)
        results = store.search("NIFTY options chain", top_k=5)
    """

    def __init__(
        self,
        collection_name: str = _DEFAULT_COLLECTION,
        persist_directory: str = "",
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._collection_name = collection_name
        self._persist_dir = persist_directory
        self._embedding_provider = embedding_provider or EmbeddingProvider()
        self._client: Any = None
        self._collection: Any = None
        self._embedding_mode: str | None = None

    def upsert(self, chunks: list[TextChunk]) -> int:
        """Insert or update chunks in the vector store.

        Args:
            chunks: List of TextChunk objects to index.

        Returns:
            Number of chunks upserted.
        """
        if not chunks:
            return 0
        coll = self._get_collection()
        embedding_mode = self._resolve_embedding_mode(coll)

        ids = [c.chunk_id for c in chunks]
        documents = [c.content for c in chunks]
        metadatas: list[dict[str, str]] = [
            {
                "source": c.source,
                "doc_type": c.doc_type,
                "chunk_index": str(c.chunk_index),
                **c.metadata,
            }
            for c in chunks
        ]

        if embedding_mode == _EMBEDDING_MODE_CHROMA:
            coll.upsert(ids=ids, documents=documents, metadatas=metadatas)
        else:
            try:
                embeddings = self._embedding_provider.embed(documents)
                if len(embeddings) != len(documents):
                    raise ValueError("embedding provider returned an unexpected vector count")
            except Exception as exc:  # noqa: BLE001 - choose one stable mode for an empty collection
                if embedding_mode == _EMBEDDING_MODE_EXTERNAL:
                    raise RuntimeError(
                        "Embedding provider unavailable for a collection encoded with external embeddings"
                    ) from exc
                logger.warning("Embedding provider unavailable; fixing collection mode to Chroma embeddings: %s", exc)
                self._persist_embedding_mode(coll, _EMBEDDING_MODE_CHROMA)
                coll.upsert(ids=ids, documents=documents, metadatas=metadatas)
            else:
                if embedding_mode is None:
                    self._persist_embedding_mode(coll, _EMBEDDING_MODE_EXTERNAL)
                coll.upsert(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)

        logger.info("Upserted %d chunks into collection '%s'", len(chunks), self._collection_name)
        return len(chunks)

    def search(
        self,
        query: str,
        top_k: int = _DEFAULT_TOP_K,
        doc_type: str | None = None,
        similarity_threshold: float = _DEFAULT_SIMILARITY_THRESHOLD,
    ) -> list[RetrievedChunk]:
        """Perform semantic similarity search.

        Args:
            query:               Query text.
            top_k:               Maximum number of results to return.
            doc_type:            Optional filter by document type.
            similarity_threshold: Minimum similarity score (0–1) to include.

        Returns:
            Ranked list of RetrievedChunk objects.
        """
        coll = self._get_collection()
        where = {"doc_type": doc_type} if doc_type else None
        embedding_mode = self._resolve_embedding_mode(coll)

        if embedding_mode == _EMBEDDING_MODE_CHROMA:
            results = coll.query(
                query_texts=[query],
                n_results=min(top_k, max(coll.count(), 1)),
                where=where,
            )
        else:
            try:
                query_embeddings = self._embedding_provider.embed([query])
                if len(query_embeddings) != 1:
                    raise ValueError("embedding provider returned an unexpected query vector count")
            except Exception as exc:  # noqa: BLE001 - never mix embedding spaces in a populated collection
                if embedding_mode == _EMBEDDING_MODE_EXTERNAL:
                    raise RuntimeError(
                        "Embedding provider unavailable for a collection encoded with external embeddings"
                    ) from exc
                logger.warning("Query embedding unavailable; fixing collection mode to Chroma embeddings: %s", exc)
                self._persist_embedding_mode(coll, _EMBEDDING_MODE_CHROMA)
                results = coll.query(
                    query_texts=[query],
                    n_results=min(top_k, max(coll.count(), 1)),
                    where=where,
                )
            else:
                if embedding_mode is None:
                    self._persist_embedding_mode(coll, _EMBEDDING_MODE_EXTERNAL)
                results = coll.query(
                    query_embeddings=query_embeddings,
                    n_results=min(top_k, max(coll.count(), 1)),
                    where=where,
                )

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        chunks: list[RetrievedChunk] = []
        distance_space = self._distance_space(coll)
        for i, text in enumerate(documents):
            meta = metadatas[i] if i < len(metadatas) else {}
            dist = distances[i] if i < len(distances) else 1.0
            raw_score = 1.0 - (dist / 2.0) if distance_space == "l2" else 1.0 - dist
            score = min(1.0, max(0.0, raw_score))
            if score < similarity_threshold:
                logger.debug(
                    "Dropped chunk from '%s' (score=%.3f < threshold=%.3f)",
                    meta.get("source", ""),
                    score,
                    similarity_threshold,
                )
                continue
            chunks.append(
                RetrievedChunk(
                    content=text,
                    source=meta.get("source", ""),
                    doc_type=meta.get("doc_type", ""),
                    score=score,
                    metadata=dict(meta),
                )
            )
        return chunks

    def count(self) -> int:
        """Number of indexed chunks."""
        try:
            return self._get_collection().count()
        except Exception:
            return 0

    def delete_collection(self) -> None:
        """Drop and recreate the collection (clears all data)."""
        client = self._get_client()
        client.delete_collection(self._collection_name)
        self._collection = None
        self._embedding_mode = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_client(self) -> Any:
        if self._client is None:
            from .local_vector_store import Client, PersistentClient

            if self._persist_dir:
                self._client = PersistentClient(path=self._persist_dir)
            else:
                self._client = Client()
        return self._client

    def _get_collection(self) -> Any:
        if self._collection is None:
            client = self._get_client()
            self._collection = client.get_or_create_collection(
                name=self._collection_name,
                metadata={
                    "hnsw:space": "cosine",
                    _DISTANCE_SPACE_METADATA_KEY: "cosine",
                },
            )
            logger.info(
                "Vector collection '%s' ready (%d chunks)",
                self._collection_name,
                self._collection.count(),
            )
        return self._collection

    def _resolve_embedding_mode(self, collection: Any) -> str | None:
        """Return the persisted embedding mode, inferring old collections safely."""
        if self._embedding_mode is not None:
            return self._embedding_mode

        metadata = getattr(collection, "metadata", None)
        if isinstance(metadata, dict):
            mode = metadata.get(_EMBEDDING_MODE_METADATA_KEY)
            if mode in {_EMBEDDING_MODE_EXTERNAL, _EMBEDDING_MODE_CHROMA}:
                self._embedding_mode = str(mode)
                return self._embedding_mode

        if collection.count() > 0:
            raise RuntimeError(
                "RAG collection embedding mode is unknown; clear and reindex it before querying or writing"
            )
        return None

    def _persist_embedding_mode(self, collection: Any, mode: str) -> None:
        """Persist the one embedding space used by this collection."""
        raw_metadata = getattr(collection, "metadata", None)
        metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
        metadata[_DISTANCE_SPACE_METADATA_KEY] = self._distance_space(collection)
        metadata[_EMBEDDING_MODE_METADATA_KEY] = mode
        metadata.pop("hnsw:space", None)
        try:
            collection.modify(metadata=metadata)
        except Exception as exc:  # noqa: BLE001 - mode persistence is required to prevent mixed vectors
            raise RuntimeError("Could not persist the RAG collection embedding mode") from exc
        self._embedding_mode = mode

    @staticmethod
    def _distance_space(collection: Any) -> str:
        """Read the collection distance metric across Chroma API generations."""
        configuration = getattr(collection, "configuration", None)
        if isinstance(configuration, dict):
            hnsw = configuration.get("hnsw")
            if isinstance(hnsw, dict) and hnsw.get("space") in {"cosine", "l2", "ip"}:
                return str(hnsw["space"])
        metadata = getattr(collection, "metadata", None)
        if isinstance(metadata, dict):
            for key in (_DISTANCE_SPACE_METADATA_KEY, "hnsw:space"):
                if metadata.get(key) in {"cosine", "l2", "ip"}:
                    return str(metadata[key])
        return "l2"


# ---------------------------------------------------------------------------
# RAGPipeline — full chain
# ---------------------------------------------------------------------------


class RAGPipeline:
    """Full RAG pipeline: load → chunk → embed → store → retrieve → generate.

    All components are replaceable; the pipeline uses sensible defaults when
    components are not provided.

    Example::

        from flinttrade_ai.llm_client import LLMClient

        pipeline = RAGPipeline(
            config=PipelineConfig(chunk_size=1000, chunk_overlap=200),
            llm_client=LLMClient(...),
        )
        pipeline.index_directory("docs/")
        result = pipeline.query("What is the max pain for NIFTY?")
        print(result.answer)
    """

    def __init__(
        self,
        config: PipelineConfig | None = None,
        llm_client: Any | None = None,
        loader: DocumentLoader | None = None,
        chunker: TextChunker | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        vector_store: VectorStore | None = None,
        domain_filter: DomainFilter | None = None,
        enable_domain_filter: bool = False,
    ) -> None:
        self.config = config or PipelineConfig()

        _embedding = embedding_provider or EmbeddingProvider(
            model=self.config.embedding_model,
            provider=self.config.embedding_provider,
            api_base=self.config.openai_api_base,
            api_key=self.config.openai_api_key,
        )
        self._embedding_provider = _embedding

        self._llm = llm_client
        self._loader = loader or DocumentLoader()
        self._chunker = chunker or TextChunker(
            chunk_size=self.config.chunk_size,
            overlap=self.config.chunk_overlap,
        )
        self._store = vector_store or VectorStore(
            collection_name=self.config.collection_name,
            persist_directory=self.config.persist_directory,
            embedding_provider=_embedding,
        )
        # Domain filter — guards query() against off-topic questions.
        # Receives the same embedding provider for optional semantic check.
        self._domain_filter_enabled = enable_domain_filter
        self._domain_filter = domain_filter
        if self._domain_filter is None and enable_domain_filter:
            self._domain_filter = DomainFilter(
                embedding_provider=_embedding,
            )

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def index_file(self, file_path: str | Path, doc_type: str = "") -> int:
        """Load and index a single file.

        Args:
            file_path: Path to the file.
            doc_type:  Override document type. Auto-detected if empty.

        Returns:
            Number of chunks indexed.
        """
        doc = self._loader.load_file(file_path, doc_type)
        if doc is None:
            return 0
        return self._index_document(doc)

    def index_document(
        self,
        content: str | LoadedDocument,
        source: str = "",
        doc_type: str = "general",
        metadata: dict[str, str] | None = None,
    ) -> int:
        """Index raw text content directly (no file I/O).

        Args:
            content:  Text content or a loaded/legacy document object.
            source:   Arbitrary source identifier.
            doc_type: Document type tag.
            metadata: Optional metadata when indexing raw text.

        Returns:
            Number of chunks indexed.
        """
        if isinstance(content, LoadedDocument):
            doc = content
        else:
            doc = LoadedDocument(
                content=content,
                source=source,
                doc_type=doc_type,
                metadata=metadata or {},
            )
        return self._index_document(doc)

    def index_directory(
        self,
        dir_path: str | Path,
        recursive: bool = True,
        extensions: tuple[str, ...] | None = None,
    ) -> int:
        """Load and index all supported files in a directory.

        Args:
            dir_path:  Root directory to scan.
            recursive: Whether to recurse into subdirectories.
            extensions: Optional caller-selected subset of supported suffixes.

        Returns:
            Total number of chunks indexed.
        """
        docs = self._loader.load_directory(
            dir_path,
            recursive=recursive,
            extensions=extensions,
        )
        total = sum(self._index_document(doc) for doc in docs)
        logger.info("Indexed %d total chunks from %s", total, dir_path)
        return total

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        doc_type: str | None = None,
        similarity_threshold: float | None = None,
    ) -> list[RetrievedChunk]:
        """Retrieve the most relevant chunks for a query.

        Args:
            query:               The search query.
            top_k:               Max results. Defaults to ``config.top_k``.
            doc_type:            Optional document type filter.
            similarity_threshold: Minimum similarity. Defaults to ``config.similarity_threshold``.

        Returns:
            List of RetrievedChunk objects sorted by descending similarity.
        """
        k = top_k if top_k is not None else self.config.top_k
        threshold = similarity_threshold if similarity_threshold is not None else self.config.similarity_threshold
        return self._store.search(query, top_k=k, doc_type=doc_type, similarity_threshold=threshold)

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def query(
        self,
        question: str,
        top_k: int | None = None,
        doc_type: str | None = None,
        system_prompt: str = "",
        similarity_threshold: float | None = None,
        *,
        domain_filter: DomainFilter | None = None,
        enable_domain_filter: bool | None = None,
    ) -> RAGResult:
        """Full RAG chain: retrieve relevant chunks then generate an answer.

        Args:
            question:            The question to answer.
            top_k:               Max chunks to retrieve.
            doc_type:            Optional document type filter.
            system_prompt:       Override the default LLM system prompt.
            similarity_threshold: Override the similarity threshold.
            domain_filter:       Optional filter override for this query.
            enable_domain_filter: Enable or bypass filtering for this query.

        Returns:
            RAGResult with the generated answer and source chunks.
        """
        if self._llm is None:
            return RAGResult(query=question, error="No LLM client configured")

        # Domain filter pre-check — refuse off-topic questions before retrieval.
        active_filter = domain_filter or self._domain_filter
        filter_enabled = (
            self._domain_filter_enabled or domain_filter is not None
            if enable_domain_filter is None
            else enable_domain_filter
        )
        if filter_enabled and active_filter is None:
            active_filter = DomainFilter(embedding_provider=self._embedding_provider)
        if filter_enabled and active_filter is not None and not active_filter.is_on_topic(question):
            logger.info("Domain filter rejected query: %r", question[:80])
            return RAGResult(
                query=question,
                answer=DomainFilter.REFUSAL_MESSAGE,
            )

        try:
            chunks = self.retrieve(question, top_k, doc_type, similarity_threshold)
        except RuntimeError as exc:
            logger.error("RAG retrieval failed: %s", exc)
            return RAGResult(query=question, error="RAG retrieval failed")
        if not chunks:
            return RAGResult(query=question, error="No relevant documents found")

        context = "\n\n---\n\n".join(c.content for c in chunks)
        system = system_prompt or (
            "You are a FlintTrade trading assistant. Answer the question using ONLY the "
            "provided context. If the context doesn't contain the answer, say so. "
            "Be concise and specific. Reference source documents when possible."
        )

        try:
            from .llm_client import LLMMessage  # local import — avoids circular dep

            messages = [
                LLMMessage(role="system", content=system),
                LLMMessage(role="user", content=f"Context:\n{context}\n\nQuestion: {question}"),
            ]
            response = self._llm.chat(messages)
            return RAGResult(
                answer=response.content,
                query=question,
                chunks_used=chunks,
                error=response.error,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("LLM generation failed: %s", exc)
            return RAGResult(query=question, error="RAG query failed", chunks_used=chunks)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def document_count(self) -> int:
        """Total number of indexed chunks."""
        return self._store.count()

    def delete_collection(self) -> None:
        """Delete the canonical collection; it is recreated lazily on next use."""
        self._store.delete_collection()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _index_document(self, doc: LoadedDocument) -> int:
        chunks = self._chunker.chunk_document(doc)
        if not chunks:
            return 0
        return self._store.upsert(chunks)


class RAGEngine(RAGPipeline):
    """Compatibility façade for callers of the former ``rag.RAGEngine``.

    All work delegates to :class:`RAGPipeline`; this class only translates the
    old constructor and ``n_results`` method keyword onto the canonical API.
    """

    def __init__(
        self,
        llm_client: Any | None = None,
        collection_name: str = _DEFAULT_COLLECTION,
        persist_directory: str | None = None,
        embedding_model: str = _DEFAULT_EMBEDDING_MODEL,
        *,
        domain_filter: DomainFilter | None = None,
        enable_domain_filter: bool = False,
    ) -> None:
        super().__init__(
            config=PipelineConfig(
                collection_name=collection_name,
                persist_directory=persist_directory or "",
                embedding_model=embedding_model,
            ),
            llm_client=llm_client,
            domain_filter=domain_filter,
            enable_domain_filter=enable_domain_filter,
        )

    def index_document(self, doc: LoadedDocument) -> int:
        """Index a document supplied through the former dataclass API."""
        return super().index_document(doc)

    def index_file(self, file_path: str | Path, doc_type: str = "") -> int:
        """Index any explicitly supplied text path as the former engine did."""
        doc = self._loader.load_file(
            file_path,
            doc_type,
            allow_unsupported_text=True,
        )
        if doc is None:
            return 0
        return self._index_document(doc)

    def _get_collection(self) -> Any:
        """Return the canonical store collection through the legacy accessor."""
        return self._store._get_collection()

    def index_directory(
        self,
        dir_path: str | Path,
        extensions: tuple[str, ...] = (".md", ".txt", ".py", ".pdf"),
    ) -> int:
        """Index the caller-selected legacy extension set recursively."""
        return super().index_directory(
            dir_path,
            recursive=True,
            extensions=extensions,
        )

    def retrieve(
        self,
        query: str,
        n_results: int = _DEFAULT_TOP_K,
        doc_type: str | None = None,
        similarity_threshold: float = _DEFAULT_SIMILARITY_THRESHOLD,
        *,
        top_k: int | None = None,
    ) -> list[LegacyRetrievedChunk]:
        """Translate the legacy ``n_results`` argument to canonical ``top_k``."""
        chunks = super().retrieve(
            query,
            top_k=n_results if top_k is None else top_k,
            doc_type=doc_type,
            similarity_threshold=similarity_threshold,
        )
        return [
            LegacyRetrievedChunk(
                content=chunk.content,
                source=chunk.source,
                doc_type=chunk.doc_type,
                score=chunk.score,
                metadata=dict(chunk.metadata),
            )
            for chunk in chunks
        ]

    def query(
        self,
        question: str,
        n_results: int = _DEFAULT_TOP_K,
        doc_type: str | None = None,
        system_prompt: str = "",
        similarity_threshold: float = _DEFAULT_SIMILARITY_THRESHOLD,
        *,
        top_k: int | None = None,
        domain_filter: DomainFilter | None = None,
        enable_domain_filter: bool | None = None,
    ) -> RAGResponse:
        """Translate the legacy query signature onto :class:`RAGPipeline`."""
        result = super().query(
            question,
            top_k=n_results if top_k is None else top_k,
            doc_type=doc_type,
            system_prompt=system_prompt,
            similarity_threshold=similarity_threshold,
            domain_filter=domain_filter,
            enable_domain_filter=enable_domain_filter,
        )
        return RAGResponse(
            answer=result.answer,
            chunks_used=result.chunks_used,
            query=result.query,
            error=result.error,
        )

    _infer_doc_type = staticmethod(DocumentLoader._infer_type)
