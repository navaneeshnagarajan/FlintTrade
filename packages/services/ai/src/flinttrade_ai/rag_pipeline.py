"""Full RAG pipeline for FlintTrade AI package.

Provides a self-contained, configurable RAG chain:

    DocumentLoader  → load .md / .txt / .pdf files from a directory.
    TextChunker     → split documents into overlapping chunks.
    EmbeddingProvider → sentence-transformers or OpenAI-compatible embeddings.
    VectorStore     → ChromaDB-backed similarity search.
    RAGPipeline     → orchestrates the full query → retrieve → generate chain.

Design:
- All settings are Pydantic models so the pipeline is configurable without
  subclassing.
- Embedding provider is pluggable: sentence-transformers (default, offline)
  or any callable that maps List[str] → List[List[float]].
- ChromaDB is lazily initialised so tests can run without installing it.
- The LLM generation step is optional; callers can use the pipeline in
  retrieval-only mode by calling ``retrieve()`` instead of ``query()``.

Absorbed from: openalgo-chatbot/openalgo_documentation_chatbot.py
Extended with:
  - Configurable chunk_size / overlap (512 / 64 per spec).
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

_DEFAULT_CHUNK_SIZE = 512       # tokens (approximate, ~4 chars / token)
_DEFAULT_CHUNK_OVERLAP = 64     # token overlap between adjacent chunks
_DEFAULT_TOP_K = 5
_DEFAULT_SIMILARITY_THRESHOLD = 0.0  # no filtering by default
_DEFAULT_COLLECTION = "flinttrade_rag"
_DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"

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
        collection_name:      ChromaDB collection name.
        persist_directory:    Persist ChromaDB to disk at this path. Empty = in-memory.
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


# ---------------------------------------------------------------------------
# DomainFilter — topic guard for the RAG pipeline
# ---------------------------------------------------------------------------


class DomainFilter:
    """Pre-query topic guard that rejects off-topic questions.

    Absorbed from openalgo-chatbot's intent-filtering pattern: before
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

    TRADING_KEYWORDS: frozenset[str] = frozenset({
        # Indian markets & instruments
        "nifty", "banknifty", "sensex", "nse", "bse", "mcx",
        "nfo", "fut", "ce", "pe", "otm", "itm", "atm",
        # Order types & execution
        "order", "buy", "sell", "trade", "position", "holding",
        "orderbook", "tradebook", "bracket", "cover", "limit", "market",
        "sl", "stoploss", "stop-loss", "target", "entry", "exit",
        # Options concepts
        "option", "options", "call", "put", "strike", "expiry", "expiration",
        "premium", "theta", "delta", "gamma", "vega", "rho", "iv",
        "implied volatility", "greeks", "hedging", "hedge",
        "straddle", "strangle", "spread", "iron condor", "butterfly",
        # Technical analysis
        "chart", "candle", "indicator", "rsi", "macd", "ema", "sma",
        "bollinger", "atr", "adx", "momentum", "volume", "support", "resistance",
        "breakout", "breakdown", "trend", "signal",
        # Portfolio & risk
        "portfolio", "pnl", "profit", "loss", "drawdown", "sharpe",
        "margin", "risk", "exposure", "allocation", "rebalance",
        # Market data & finance
        "market", "price", "ltp", "ohlc", "ohlcv", "quote", "depth",
        "oi", "open interest", "pcr", "max pain", "vix", "fii", "dii",
        "sector", "equity", "fund", "etf", "mutual fund", "sip",
        "broker", "api", "backtest", "strategy", "algo", "automation",
        "ticker", "symbol", "exchange", "intraday", "swing", "positional",
    })

    REFUSAL_MESSAGE: str = (
        "I can only help with trading and market-related questions."
    )

    def __init__(
        self,
        extra_keywords: set[str] | None = None,
        semantic_threshold: float = 0.35,
        embedding_provider: "EmbeddingProvider | None" = None,
    ) -> None:
        base = (
            self.TRADING_KEYWORDS | {k.lower() for k in extra_keywords}
            if extra_keywords
            else self.TRADING_KEYWORDS
        )
        # Pre-compile one regex per keyword using word boundaries so that
        # short abbreviations like "iv", "pe", "ce" do not match within
        # unrelated English words (e.g. "recipe", "sentence", "live").
        self._keyword_patterns: list[re.Pattern[str]] = [
            re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
            for kw in base
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
                    self._seed_embeddings = self._embedding_provider.embed(
                        self._seed_phrases
                    )
                query_vec = self._embedding_provider.embed([query])[0]
                max_sim = max(
                    self._cosine(query_vec, seed)
                    for seed in self._seed_embeddings
                )
                if max_sim >= self._semantic_threshold:
                    return True
            except Exception:  # noqa: BLE001
                pass  # Embedding failure does not block the query

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
    """Load documents from .md, .txt, and .pdf files.

    PDF support requires the ``pypdf`` package (``pip install pypdf``).
    Falls back gracefully to empty content if pypdf is not installed.

    Example::

        loader = DocumentLoader()
        docs = loader.load_directory("docs/")
    """

    SUPPORTED = {".md", ".txt", ".pdf"}

    def load_file(self, file_path: str | Path, doc_type: str = "") -> LoadedDocument | None:
        """Load a single file and return a LoadedDocument.

        Args:
            file_path: Path to the file to load.
            doc_type:  Override document type tag. Auto-detected if empty.

        Returns:
            LoadedDocument, or None if the file is unsupported / unreadable.
        """
        path = Path(file_path)
        if not path.exists():
            logger.warning("File not found: %s", file_path)
            return None
        if path.suffix.lower() not in self.SUPPORTED:
            logger.debug("Unsupported file type: %s", path.suffix)
            return None

        content = self._read(path)
        if not content.strip():
            return None

        inferred = doc_type or self._infer_type(path.name)
        return LoadedDocument(content=content, source=str(path), doc_type=inferred)

    def load_directory(
        self,
        dir_path: str | Path,
        recursive: bool = True,
    ) -> list[LoadedDocument]:
        """Load all supported files in a directory.

        Args:
            dir_path:  Root directory to scan.
            recursive: Whether to recurse into subdirectories.

        Returns:
            List of successfully loaded documents.
        """
        root = Path(dir_path)
        if not root.is_dir():
            logger.warning("Not a directory: %s", dir_path)
            return []

        pattern = "**/*" if recursive else "*"
        docs: list[LoadedDocument] = []
        for path in root.glob(pattern):
            if path.is_file() and path.suffix.lower() in self.SUPPORTED:
                doc = self.load_file(path)
                if doc is not None:
                    docs.append(doc)

        logger.info("Loaded %d documents from %s", len(docs), dir_path)
        return docs

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _read(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in {".md", ".txt"}:
            return path.read_text(encoding="utf-8", errors="replace")
        if suffix == ".pdf":
            return self._read_pdf(path)
        return ""

    @staticmethod
    def _read_pdf(path: Path) -> str:
        try:
            import pypdf  # type: ignore[import]

            reader = pypdf.PdfReader(str(path))
            return "\n".join(
                page.extract_text() or "" for page in reader.pages
            )
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
        except ImportError:
            raise RuntimeError("sentence-transformers not installed — pip install sentence-transformers")

        if self._st_model is None:
            self._st_model = SentenceTransformer(self._model)
        embeddings = self._st_model.encode(texts, show_progress_bar=False)
        return [vec.tolist() for vec in embeddings]

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
    """ChromaDB-backed vector store for semantic search.

    Lazily initialises the ChromaDB client on first use.

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

        # Use pre-computed embeddings only if provider isn't the ChromaDB default.
        try:
            embeddings = self._embedding_provider.embed(documents)
            coll.upsert(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)
        except RuntimeError:
            # Fall back to ChromaDB's default embedding function.
            coll.upsert(ids=ids, documents=documents, metadatas=metadatas)

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

        try:
            query_emb = self._embedding_provider.embed([query])
            results = coll.query(
                query_embeddings=query_emb,
                n_results=min(top_k, max(coll.count(), 1)),
                where=where,
            )
        except RuntimeError:
            results = coll.query(
                query_texts=[query],
                n_results=min(top_k, max(coll.count(), 1)),
                where=where,
            )

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        chunks: list[RetrievedChunk] = []
        for i, text in enumerate(documents):
            meta = metadatas[i] if i < len(metadatas) else {}
            dist = distances[i] if i < len(distances) else 1.0
            score = max(0.0, 1.0 - dist)
            if score < similarity_threshold:
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

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import chromadb  # type: ignore[import]
            except ImportError:
                raise ImportError("chromadb required — pip install chromadb")

            if self._persist_dir:
                self._client = chromadb.PersistentClient(path=self._persist_dir)
            else:
                self._client = chromadb.Client()
        return self._client

    def _get_collection(self) -> Any:
        if self._collection is None:
            client = self._get_client()
            self._collection = client.get_or_create_collection(
                name=self._collection_name,
            )
            logger.info(
                "ChromaDB collection '%s' ready (%d chunks)",
                self._collection_name,
                self._collection.count(),
            )
        return self._collection


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
            config=PipelineConfig(chunk_size=512, chunk_overlap=64),
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
        enable_domain_filter: bool = True,
    ) -> None:
        self.config = config or PipelineConfig()

        _embedding = embedding_provider or EmbeddingProvider(
            model=self.config.embedding_model,
            provider=self.config.embedding_provider,
            api_base=self.config.openai_api_base,
            api_key=self.config.openai_api_key,
        )

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
        self._domain_filter: DomainFilter | None = None
        if enable_domain_filter:
            self._domain_filter = domain_filter or DomainFilter(
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

    def index_document(self, content: str, source: str = "", doc_type: str = "general") -> int:
        """Index raw text content directly (no file I/O).

        Args:
            content:  Text content to index.
            source:   Arbitrary source identifier.
            doc_type: Document type tag.

        Returns:
            Number of chunks indexed.
        """
        doc = LoadedDocument(content=content, source=source, doc_type=doc_type)
        return self._index_document(doc)

    def index_directory(self, dir_path: str | Path, recursive: bool = True) -> int:
        """Load and index all supported files in a directory.

        Args:
            dir_path:  Root directory to scan.
            recursive: Whether to recurse into subdirectories.

        Returns:
            Total number of chunks indexed.
        """
        docs = self._loader.load_directory(dir_path, recursive=recursive)
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
        threshold = (
            similarity_threshold
            if similarity_threshold is not None
            else self.config.similarity_threshold
        )
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
    ) -> RAGResult:
        """Full RAG chain: retrieve relevant chunks then generate an answer.

        Args:
            question:            The question to answer.
            top_k:               Max chunks to retrieve.
            doc_type:            Optional document type filter.
            system_prompt:       Override the default LLM system prompt.
            similarity_threshold: Override the similarity threshold.

        Returns:
            RAGResult with the generated answer and source chunks.
        """
        if self._llm is None:
            return RAGResult(query=question, error="No LLM client configured")

        # Domain filter pre-check — refuse off-topic questions before retrieval.
        if self._domain_filter is not None and not self._domain_filter.is_on_topic(question):
            logger.info("Domain filter rejected query: %r", question[:80])
            return RAGResult(
                query=question,
                answer=DomainFilter.REFUSAL_MESSAGE,
            )

        chunks = self.retrieve(question, top_k, doc_type, similarity_threshold)
        if not chunks:
            return RAGResult(query=question, error="No relevant documents found")

        context = "\n\n---\n\n".join(c.content for c in chunks)
        system = system_prompt or (
            "You are a FlintTrade trading assistant. "
            "Answer using ONLY the provided context. "
            "If the answer is not in the context, say so. "
            "Be concise and cite sources where possible."
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
            return RAGResult(query=question, error=str(exc), chunks_used=chunks)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def document_count(self) -> int:
        """Total number of indexed chunks."""
        return self._store.count()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _index_document(self, doc: LoadedDocument) -> int:
        chunks = self._chunker.chunk_document(doc)
        if not chunks:
            return 0
        return self._store.upsert(chunks)
