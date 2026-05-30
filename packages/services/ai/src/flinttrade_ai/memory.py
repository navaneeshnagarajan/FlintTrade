"""4-layer tiered memory system for AI trading agents.

Absorbs FinMem patterns: compound scoring, layer-differentiated importance,
access-count reinforcement on correct predictions, and exponential recency decay.

Layers:
- SHORT:      News-scale (hours/days), initial importance 50–70
- MID:        Earnings-scale (weeks), initial importance 55–75
- LONG:       Thesis-scale (months), initial importance 60–80
- REFLECTION: Learned lessons, initial importance 70–90
"""

from __future__ import annotations

import logging
import math
import random
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger("flinttrade.ai.memory")

_DEFAULT_PERSIST_DIR = "~/.flinttrade/memory/"
_DEFAULT_COLLECTION_PREFIX = "trading"
_EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Importance delta applied on outcome feedback
_REINFORCE_DELTA = 5.0
_WEAKEN_DELTA = -2.0

# Minimum importance floor — prevents memories from going negative
_IMPORTANCE_FLOOR = 0.0

# Maximum importance ceiling — prevents unbounded reinforcement
_IMPORTANCE_CEILING = 100.0

# How many extra results to over-fetch from ChromaDB before Python-side reranking
_OVERFETCH_MULTIPLIER = 5


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class MemoryLayer(str, Enum):
    """Temporal layer that determines importance ranges and decay speed."""

    SHORT = "short"
    MID = "mid"
    LONG = "long"
    REFLECTION = "reflection"


@dataclass
class MemoryItem:
    """A single memory entry across any layer.

    Attributes:
        id: Stable UUID used as ChromaDB document ID.
        symbol: Trading instrument this memory pertains to (e.g. "NIFTY").
        text: The actual memory content.
        layer: Which tiered layer this belongs to.
        importance: Mutable relevance score (0–100).
        recency_delta: Days since this memory was created.
        access_count: How many times this memory has been retrieved.
        timestamp: UTC creation time.
        metadata: Arbitrary extra key/value pairs stored in ChromaDB.
    """

    id: str
    symbol: str
    text: str
    layer: MemoryLayer
    importance: float
    recency_delta: int
    access_count: int
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryQueryResult:
    """Result of a memory retrieval operation.

    Attributes:
        items: Retrieved and reranked memory items.
        query: The original query string.
        layer: The layer that was searched.
    """

    items: list[MemoryItem]
    query: str
    layer: MemoryLayer


# ---------------------------------------------------------------------------
# Scoring functions (FinMem pattern)
# ---------------------------------------------------------------------------


def exponential_decay(recency_delta: int, k: float = 10.0) -> float:
    """Compute recency weight using exponential decay.

    After ``k`` days the memory retains approximately 37% (1/e) of its
    original recency weight.

    Args:
        recency_delta: Number of days since the memory was created.
        k: Decay half-life in days. Smaller values decay faster.

    Returns:
        A float in (0, 1]. Returns 1.0 when ``recency_delta`` is 0.
    """
    return math.exp(-(recency_delta / k))


def compound_score(
    similarity: float,
    recency_delta: int,
    importance: float,
    k: float = 10.0,
) -> float:
    """Rank memories by a composite of similarity, recency, and importance.

    Final score = similarity + decayed_recency/100 + importance/100.

    All three components contribute on similar scales:
    - ``similarity``:  typically 0–1 from ChromaDB cosine distance
    - ``recency/100``: 0–0.01 per unit, bounded by decay
    - ``importance/100``: 0–1 for the 0–100 importance range

    Args:
        similarity: Vector similarity score from ChromaDB (0–1).
        recency_delta: Days since creation.
        importance: Current importance value (0–100).
        k: Decay constant in days passed to ``exponential_decay``.

    Returns:
        Compound ranking score. Higher is better.
    """
    recency = exponential_decay(recency_delta, k)
    return similarity + recency / 100.0 + importance / 100.0


def initial_importance(layer: MemoryLayer) -> float:
    """Sample layer-differentiated initial importance (FinMem pattern).

    Args:
        layer: The memory layer being created.

    Returns:
        A float sampled uniformly from the layer's importance range.
    """
    ranges: dict[MemoryLayer, tuple[float, float]] = {
        MemoryLayer.SHORT: (50.0, 70.0),
        MemoryLayer.MID: (55.0, 75.0),
        MemoryLayer.LONG: (60.0, 80.0),
        MemoryLayer.REFLECTION: (70.0, 90.0),
    }
    lo, hi = ranges[layer]
    return random.uniform(lo, hi)


# ---------------------------------------------------------------------------
# TradedMemory — main class
# ---------------------------------------------------------------------------


class TradedMemory:
    """4-layer tiered memory with exponential recency decay and feedback reinforcement.

    Absorbs FinMem patterns: compound scoring, layer-differentiated importance,
    access-count reinforcement on correct predictions.

    One ChromaDB collection is created per layer, named
    ``{collection_prefix}_{layer}``.

    Usage::

        memory = TradedMemory(persist_dir="~/.flinttrade/memory/")

        # Store a news event
        mid = memory.add_memory("NIFTY", "NIFTY Q1 earnings beat by 12%", MemoryLayer.MID)

        # Retrieve before a trade
        result = memory.get_memories("NIFTY", "recent earnings performance", MemoryLayer.MID)
        for item in result.items:
            print(item.text, item.importance)

        # Reinforce memories that contributed to a winning trade
        memory.update_on_outcome([mid], direction_correct=True)

        # Age memories at session start
        memory.step(days=1)
    """

    def __init__(
        self,
        persist_dir: str = _DEFAULT_PERSIST_DIR,
        collection_prefix: str = _DEFAULT_COLLECTION_PREFIX,
        embedding_model: str = _EMBEDDING_MODEL,
        _chroma_client: Any | None = None,
        _embedding_fn: Any | None = None,
    ) -> None:
        """Initialise TradedMemory.

        Args:
            persist_dir: Directory for ChromaDB persistence. Tilde is expanded.
                Pass ``None`` to use an ephemeral in-memory client (testing only).
            collection_prefix: Prefix for ChromaDB collection names.
            embedding_model: sentence-transformers model name for embeddings.
            _chroma_client: Override ChromaDB client (used in tests to inject
                an ``EphemeralClient``).
            _embedding_fn: Override ChromaDB embedding function (used in tests
                to keep unit tests independent from transformer runtimes).
        """
        self._persist_dir = persist_dir
        self._collection_prefix = collection_prefix
        self._embedding_model_name = embedding_model
        self._override_client = _chroma_client

        # Lazy-initialised per layer
        self._chroma_client: Any | None = None
        self._collections: dict[MemoryLayer, Any] = {}
        self._embedding_fn: Any | None = _embedding_fn

        # Thread safety for lazy-init helpers (RLock because _get_collection
        # calls _get_client and _get_embedding_fn while already holding the lock)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self) -> Any:
        """Return (and lazily create) the ChromaDB client."""
        with self._lock:
            if self._chroma_client is not None:
                return self._chroma_client

            if self._override_client is not None:
                self._chroma_client = self._override_client
                return self._chroma_client

            try:
                import chromadb
            except ImportError:
                raise ImportError("chromadb required — pip install chromadb")

            if self._persist_dir:
                import os

                path = os.path.expanduser(self._persist_dir)
                os.makedirs(path, exist_ok=True)
                self._chroma_client = chromadb.PersistentClient(path=path)
            else:
                self._chroma_client = chromadb.EphemeralClient()

            logger.debug("ChromaDB client initialised (persist_dir=%s)", self._persist_dir)
            return self._chroma_client

    def _get_embedding_fn(self) -> Any:
        """Return (and lazily create) the sentence-transformer embedding function."""
        with self._lock:
            if self._embedding_fn is not None:
                return self._embedding_fn

            try:
                from chromadb.utils import embedding_functions

                self._embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                    model_name=self._embedding_model_name,
                )
            except Exception:
                from chromadb.utils import embedding_functions

                self._embedding_fn = embedding_functions.DefaultEmbeddingFunction()
                logger.warning("sentence-transformers not available, using default embeddings")

            return self._embedding_fn

    def _collection_name(self, layer: MemoryLayer) -> str:
        return f"{self._collection_prefix}_{layer.value}"

    def _get_collection(self, layer: MemoryLayer) -> Any:
        """Return (and lazily create) the ChromaDB collection for a layer."""
        with self._lock:
            if layer in self._collections:
                return self._collections[layer]

            client = self._get_client()
            name = self._collection_name(layer)
            collection = client.get_or_create_collection(
                name=name,
                embedding_function=self._get_embedding_fn(),
            )
            self._collections[layer] = collection
            logger.debug("Collection '%s' ready (%d items)", name, collection.count())
            return collection

    def _item_from_meta(self, doc_id: str, text: str, meta: dict[str, Any]) -> MemoryItem:
        """Reconstruct a MemoryItem from ChromaDB metadata."""
        ts_str = meta.get("timestamp")
        if ts_str is None:
            logger.warning("Memory %s missing timestamp, defaulting to epoch", doc_id)
            ts_str = "1970-01-01T00:00:00+00:00"
        return MemoryItem(
            id=doc_id,
            symbol=meta.get("symbol", ""),
            text=text,
            layer=MemoryLayer(meta.get("layer", MemoryLayer.SHORT.value)),
            importance=float(meta.get("importance", 50.0)),
            recency_delta=int(meta.get("recency_delta", 0)),
            access_count=int(meta.get("access_count", 0)),
            timestamp=datetime.fromisoformat(ts_str),
            metadata={
                k: v
                for k, v in meta.items()
                if k not in {"symbol", "layer", "importance", "recency_delta", "access_count", "timestamp"}
            },
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_memory(
        self,
        symbol: str,
        text: str,
        layer: MemoryLayer,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store a new memory with layer-appropriate initial importance.

        Args:
            symbol: Instrument symbol (e.g. "NIFTY", "RELIANCE").
            text: Memory content to embed and store.
            layer: Which temporal layer to store in.
            metadata: Optional extra key/value pairs stored alongside.

        Returns:
            The stable UUID string assigned to this memory.
        """
        memory_id = str(uuid.uuid4())
        importance = initial_importance(layer)
        now = datetime.now(timezone.utc)

        chroma_meta: dict[str, Any] = {
            "symbol": symbol,
            "layer": layer.value,
            "importance": importance,
            "recency_delta": 0,
            "access_count": 0,
            "timestamp": now.isoformat(),
        }
        if metadata:
            chroma_meta.update(metadata)

        collection = self._get_collection(layer)
        collection.add(
            ids=[memory_id],
            documents=[text],
            metadatas=[chroma_meta],
        )
        logger.debug(
            "Memory added: id=%s symbol=%s layer=%s importance=%.1f",
            memory_id,
            symbol,
            layer.value,
            importance,
        )
        return memory_id

    def get_memories(
        self,
        symbol: str,
        query: str,
        layer: MemoryLayer,
        n: int = 3,
    ) -> MemoryQueryResult:
        """Retrieve memories ranked by compound score.

        Fetches up to ``n * _OVERFETCH_MULTIPLIER`` candidates from ChromaDB
        by vector similarity, then Python-side reranks using
        ``compound_score(similarity, recency_delta, importance)``.

        Args:
            symbol: Filter results to this instrument symbol.
            query: Natural-language query used for vector search.
            layer: Which layer to search.
            n: Maximum number of results to return.

        Returns:
            A ``MemoryQueryResult`` with ``items`` sorted best-first.
        """
        if n <= 0:
            return MemoryQueryResult(items=[], query=query, layer=layer)

        collection = self._get_collection(layer)
        count = collection.count()
        if count == 0:
            return MemoryQueryResult(items=[], query=query, layer=layer)

        # Over-fetch so the Python reranker has more candidates to choose from
        fetch_n = min(count, max(n, n * _OVERFETCH_MULTIPLIER))

        try:
            results = collection.query(
                query_texts=[query],
                n_results=fetch_n,
                where={"symbol": symbol},
            )
        except Exception:
            return MemoryQueryResult(items=[], query=query, layer=layer)

        documents: list[str] = results.get("documents", [[]])[0]
        metadatas: list[dict[str, Any]] = results.get("metadatas", [[]])[0]
        distances: list[float] = results.get("distances", [[]])[0]
        ids: list[str] = results.get("ids", [[]])[0]

        if not documents:
            return MemoryQueryResult(items=[], query=query, layer=layer)

        # Build scored candidates
        scored: list[tuple[float, MemoryItem]] = []

        for doc_id, text, meta, dist in zip(ids, documents, metadatas, distances):
            similarity = 1.0 - dist  # ChromaDB returns L2/cosine distance
            item = self._item_from_meta(doc_id, text, meta)
            score = compound_score(similarity, item.recency_delta, item.importance)
            scored.append((score, item))

        # Sort descending by compound score
        scored.sort(key=lambda t: t[0], reverse=True)
        top_items = [item for _, item in scored[:n]]

        # Increment access_count in storage and on the returned item objects
        for item in top_items:
            item.access_count += 1
            updated_meta = {
                "symbol": item.symbol,
                "layer": item.layer.value,
                "importance": item.importance,
                "recency_delta": item.recency_delta,
                "access_count": item.access_count,
                "timestamp": item.timestamp.isoformat(),
                **item.metadata,
            }
            collection.update(ids=[item.id], metadatas=[updated_meta])

        return MemoryQueryResult(items=top_items, query=query, layer=layer)

    def update_on_outcome(
        self,
        memory_ids: list[str],
        direction_correct: bool,
    ) -> None:
        """Reinforce or weaken importance based on trade outcome.

        Correct predictions add ``+5`` to importance; incorrect predictions
        subtract ``2``. Importance is clamped at ``_IMPORTANCE_FLOOR``.

        Args:
            memory_ids: UUIDs of memories to update.
            direction_correct: True if the trade direction was correct.
        """
        delta = _REINFORCE_DELTA if direction_correct else _WEAKEN_DELTA

        for layer in MemoryLayer:
            collection = self._get_collection(layer)
            if collection.count() == 0:
                continue

            try:
                results = collection.get(ids=memory_ids)
            except Exception as exc:
                logger.exception("suppressed: %s", exc)
                continue

            retrieved_ids: list[str] = results.get("ids", [])
            metadatas: list[dict[str, Any]] = results.get("metadatas", [])

            if not retrieved_ids:
                continue

            updated_metas: list[dict[str, Any]] = []
            for meta in metadatas:
                current = float(meta.get("importance", 50.0))
                new_importance = max(_IMPORTANCE_FLOOR, min(_IMPORTANCE_CEILING, current + delta))
                updated_metas.append({**meta, "importance": new_importance})

            collection.update(ids=retrieved_ids, metadatas=updated_metas)

        logger.debug(
            "update_on_outcome: %d memories, correct=%s, delta=%.1f",
            len(memory_ids),
            direction_correct,
            delta,
        )

    def step(self, days: int = 1) -> None:
        """Age all memories by ``days`` days.

        Call once per trading session on startup to advance ``recency_delta``
        for every stored memory across all layers.

        Args:
            days: Number of days to age each memory (default 1).
        """
        for layer in MemoryLayer:
            collection = self._get_collection(layer)
            count = collection.count()
            if count == 0:
                continue

            _STEP_BATCH_WARN = 1000
            if count > _STEP_BATCH_WARN:
                logger.warning(
                    "step(): layer '%s' has %d memories (> %d). "
                    "Consider pruning stale memories to keep step() performant.",
                    layer.value,
                    count,
                    _STEP_BATCH_WARN,
                )
            # TODO: page through in batches when ChromaDB exposes stable offset/limit
            # on collection.get(). For now we fetch all at once; prune before this
            # becomes a bottleneck (see warning threshold above).
            results = collection.get(include=["metadatas", "documents"])
            all_ids: list[str] = results.get("ids", [])
            all_metas: list[dict[str, Any]] = results.get("metadatas", [])

            if not all_ids:
                continue

            updated_metas: list[dict[str, Any]] = []
            for meta in all_metas:
                new_delta = int(meta.get("recency_delta", 0)) + days
                updated_metas.append({**meta, "recency_delta": new_delta})

            collection.update(ids=all_ids, metadatas=updated_metas)

        logger.debug("step(): aged all memories by %d day(s)", days)

    def clear_symbol(self, symbol: str) -> None:
        """Remove all memories for a symbol across all layers.

        Args:
            symbol: The instrument symbol whose memories should be deleted.
        """
        for layer in MemoryLayer:
            collection = self._get_collection(layer)
            if collection.count() == 0:
                continue
            collection.delete(where={"symbol": symbol})

        logger.debug("clear_symbol: removed all memories for '%s'", symbol)
