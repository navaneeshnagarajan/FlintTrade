"""4-layer tiered memory system for AI trading agents.

Adapts FinMem patterns: compound scoring, layer-differentiated importance,
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
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal, Protocol

from pydantic import AliasChoices, BaseModel, Field, PrivateAttr, model_validator

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

# Category defaults use the shared, normalised 0..1 importance scale.
CATEGORY_IMPORTANCE: dict[str, float] = {
    "trade": 0.90,
    "market_event": 0.80,
    "user_feedback": 0.75,
    "signal": 0.70,
    "analysis": 0.60,
}

_DEFAULT_CATEGORY_IMPORTANCE = 0.65
_ACCESS_DECAY_BOOST = 0.005
_CATEGORY_META_KEY = "_flinttrade_category"
_LAST_ACCESSED_META_KEY = "_flinttrade_last_accessed_at"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class MemoryLayer(str, Enum):
    """Temporal layer that determines importance ranges and decay speed."""

    SHORT = "short"
    MID = "mid"
    LONG = "long"
    REFLECTION = "reflection"


class MemoryBackendKind(str, Enum):
    """Available memory storage backends."""

    PERSISTENT = "persistent"
    HIERARCHICAL = "hierarchical"


@dataclass(frozen=True)
class MemoryBackendConfig:
    """Configuration used to select a memory backend without changing imports."""

    backend: MemoryBackendKind | str = MemoryBackendKind.PERSISTENT
    persist_dir: str | None = _DEFAULT_PERSIST_DIR
    collection_prefix: str = _DEFAULT_COLLECTION_PREFIX
    embedding_model: str = _EMBEDDING_MODEL


class MemoryEntry(BaseModel):
    """Canonical memory entry shared by persistent and in-process backends.

    Attributes:
        id: Stable UUID used by either backend.
        content: The actual memory content. ``text`` remains a compatibility
            input/property for the former ``MemoryItem`` model.
        symbol: Optional trading instrument scope.
        layer: Optional persistent temporal layer.
        category: Semantic category used for default importance.
        importance: Normalised mutable relevance score (0.0–1.0).
        recency_delta: Days since this memory was created.
        access_count: How many times this memory has been retrieved.
        timestamp: UTC creation time.
        last_accessed: UTC time of the most recent retrieval.
        embedding: Optional caller-supplied dense embedding.
        metadata: Arbitrary extra key/value pairs stored in ChromaDB.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: str = Field(validation_alias=AliasChoices("content", "text"))
    symbol: str = ""
    layer: MemoryLayer | None = None
    category: str = "analysis"
    importance: float = Field(default=_DEFAULT_CATEGORY_IMPORTANCE, ge=0.0, le=1.0)
    recency_delta: int = Field(default=0, ge=0)
    access_count: int = Field(default=0, ge=0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_accessed: datetime | None = None
    embedding: list[float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    _retrieval_score: float | None = PrivateAttr(default=None)

    model_config = {"arbitrary_types_allowed": True, "populate_by_name": True}

    def __init__(self, *args: Any, **data: Any) -> None:
        """Accept the former ``MemoryItem`` dataclass's positional shape."""
        if args:
            legacy_fields = (
                "id",
                "symbol",
                "text",
                "layer",
                "importance",
                "recency_delta",
                "access_count",
                "timestamp",
                "metadata",
            )
            if len(args) > len(legacy_fields):
                raise TypeError(
                    f"MemoryItem expected at most {len(legacy_fields)} positional arguments, got {len(args)}"
                )
            for field_name, field_value in zip(legacy_fields, args):
                if field_name in data or (field_name == "text" and "content" in data):
                    raise TypeError(f"MemoryItem got multiple values for {field_name!r}")
                data[field_name] = field_value
        super().__init__(**data)

    @model_validator(mode="before")
    @classmethod
    def _normalise_legacy_percent_importance(cls, value: Any) -> Any:
        """Accept the former persistent model's 0..100 constructor shape."""
        if not isinstance(value, dict):
            return value
        data = dict(value)
        importance = data.get("importance")
        legacy_persistent_shape = "text" in data
        if legacy_persistent_shape and isinstance(importance, (int, float)) and 0.0 <= float(importance) <= 100.0:
            data["importance"] = float(importance) / 100.0
        return data

    @property
    def text(self) -> str:
        """Compatibility alias for the former persistent ``MemoryItem.text``."""
        return self.content

    @property
    def importance_percent(self) -> float:
        """Return importance on the persisted 0..100 scale."""
        return self.importance * 100.0


# Public compatibility name; both backends now return the exact same class.
MemoryItem = MemoryEntry


class MemoryBackend(Protocol):
    """Common interface implemented by persistent and in-process memory."""

    def add(
        self,
        content: str,
        category: str,
        importance: float | None = None,
        metadata: dict[str, Any] | None = None,
        *,
        symbol: str = "",
    ) -> str: ...

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        *,
        symbol: str | None = None,
    ) -> list[MemoryEntry]: ...

    def summarise_context(
        self,
        symbol: str,
        query: str,
        max_tokens: int = 2000,
    ) -> str: ...

    def clear(self, symbol: str | None = None) -> None: ...


@dataclass
class MemoryQueryResult:
    """Result of a memory retrieval operation.

    Attributes:
        items: Retrieved and reranked memory items.
        query: The original query string.
        layer: The layer that was searched.
    """

    items: list[MemoryEntry]
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
    recency_delta: float,
    importance: float,
    k: float = 10.0,
    *,
    decay_rate: float | None = None,
    access_count: int = 0,
    importance_weight: float = 1.0,
    recency_weight: float = 0.01,
    similarity_weight: float = 1.0,
    importance_scale: Literal["normalised", "percent"] = "percent",
) -> float:
    """Rank memories for either backend with one shared scoring formula.

    The persistent defaults preserve the historical formula exactly::

        similarity + (decayed_recency / 100) + normalised_importance

    The in-process backends pass their own weights and a per-hour
    ``decay_rate`` and declare the canonical normalised importance scale.

    All three components contribute on similar scales:
    - ``similarity``:  typically 0–1 from ChromaDB cosine distance
    - ``recency/100``: 0–0.01 per unit, bounded by decay
    - ``importance/100``: 0–1 for the 0–100 importance range

    Args:
        similarity: Vector similarity score from ChromaDB (0–1).
        recency_delta: Age in days for exponential decay, or hours when
            ``decay_rate`` is supplied.
        importance: Current importance value in ``importance_scale`` units.
        k: Decay constant in days passed to ``exponential_decay``.
        decay_rate: Optional multiplicative decay rate per recency unit.
        access_count: Retrieval count used to slow recency decay.
        importance_weight: Weight of the normalised importance component.
        recency_weight: Weight of the recency component.
        similarity_weight: Weight of vector/keyword relevance.
        importance_scale: Explicit unit for importance. Defaults to the former
            public utility's 0..100 contract.

    Returns:
        Compound ranking score. Higher is better.
    """
    if importance_scale not in {"normalised", "percent"}:
        raise ValueError("importance_scale must be 'normalised' or 'percent'")
    normalised_importance = importance / 100.0 if importance_scale == "percent" else importance
    normalised_importance = max(0.0, min(1.0, normalised_importance))
    if decay_rate is None:
        recency_raw = exponential_decay(recency_delta, k)
    else:
        recency_raw = math.pow(decay_rate, recency_delta)
    recency = min(1.0, recency_raw + access_count * _ACCESS_DECAY_BOOST)
    return similarity_weight * similarity + recency_weight * recency + importance_weight * normalised_importance


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

    Adapts FinMem patterns: compound scoring, layer-differentiated importance,
    access-count reinforcement on correct predictions.

    One collection is created per layer, named ``{collection_prefix}_{layer}``.

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
        persist_dir: str | None = _DEFAULT_PERSIST_DIR,
        collection_prefix: str = _DEFAULT_COLLECTION_PREFIX,
        embedding_model: str = _EMBEDDING_MODEL,
        _chroma_client: Any | None = None,
        _embedding_fn: Any | None = None,
    ) -> None:
        """Initialise TradedMemory.

        Args:
            persist_dir: Directory for sqlite vector persistence. Tilde is expanded.
                Pass ``None`` to use an ephemeral in-memory client (testing only).
            collection_prefix: Prefix for per-layer collection names.
            embedding_model: Unused model name retained for API compatibility.
            _chroma_client: Override vector client (used in tests to inject
                an in-memory client).
            _embedding_fn: Override embedding function (used in tests
                to keep unit tests independent from transformer runtimes).
        """
        self._persist_dir = persist_dir
        self._collection_prefix = collection_prefix
        self._embedding_model_name = embedding_model
        self._override_client = _chroma_client
        if persist_dir and _chroma_client is None:
            from .local_vector_store import assert_no_legacy_chroma_store

            assert_no_legacy_chroma_store(persist_dir)

        # Lazy-initialised per layer
        self._chroma_client: Any | None = None
        self._collections: dict[MemoryLayer, Any] = {}
        self._distance_spaces: dict[MemoryLayer, str] = {}
        self._embedding_fn: Any | None = _embedding_fn
        self._closed = False

        # Thread safety for lazy-init helpers (RLock because _get_collection
        # calls _get_client and _get_embedding_fn while already holding the lock)
        self._lock = threading.RLock()

    def close(self) -> None:
        """Close the owned vector client once and clear cached collection handles."""
        with self._lock:
            if self._closed:
                return
            client = self._chroma_client
            if client is None:
                client = self._override_client
            if client is not None:
                close = getattr(client, "close", None)
                if callable(close):
                    close()
            self._chroma_client = None
            self._override_client = None
            self._collections.clear()
            self._distance_spaces.clear()
            self._closed = True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self) -> Any:
        """Return (and lazily create) the local vector client."""
        with self._lock:
            if self._closed:
                raise RuntimeError("learning memory is closed")
            if self._chroma_client is not None:
                return self._chroma_client

            if self._override_client is not None:
                self._chroma_client = self._override_client
                return self._chroma_client

            from .local_vector_store import EphemeralClient, PersistentClient

            if self._persist_dir:
                import os

                path = os.path.expanduser(self._persist_dir)
                os.makedirs(path, exist_ok=True)
                self._chroma_client = PersistentClient(path=path)
            else:
                self._chroma_client = EphemeralClient()

            logger.debug("Local vector client initialised (persist_dir=%s)", self._persist_dir)
            return self._chroma_client

    def _get_embedding_fn(self) -> Any:
        """Return (and lazily create) the sentence-transformer embedding function."""
        with self._lock:
            if self._embedding_fn is not None:
                return self._embedding_fn

            from .local_vector_store import HashingEmbeddingFunction

            self._embedding_fn = HashingEmbeddingFunction()
            logger.debug(
                "Using deterministic local hashing embeddings (model=%s unused)",
                self._embedding_model_name,
            )
            return self._embedding_fn

    def _collection_name(self, layer: MemoryLayer) -> str:
        return f"{self._collection_prefix}_{layer.value}"

    def _embedding_distance_space(self) -> str:
        """Return the embedding function's default metric as a fallback."""
        embedding_fn = self._get_embedding_fn()
        default_space = getattr(embedding_fn, "default_space", None)
        space = default_space() if callable(default_space) else "l2"
        space_value = getattr(space, "value", space)
        return str(space_value).lower()

    def _configured_distance_space(self, collection: Any) -> str:
        """Read the metric from the collection index configuration."""
        configuration = getattr(collection, "configuration", None)
        if isinstance(configuration, dict):
            for index_name in ("hnsw", "spann"):
                index_config = configuration.get(index_name)
                if isinstance(index_config, dict) and index_config.get("space"):
                    return str(index_config["space"]).lower()
        return self._embedding_distance_space()

    def _distance_to_similarity(self, distance: float, *, space: str | None = None) -> float:
        """Convert Chroma distance using the collection index's metric."""
        resolved_space = (space or self._embedding_distance_space()).lower()
        if resolved_space in {"cosine", "ip", "inner_product"}:
            return 1.0 - distance
        return 1.0 / (1.0 + max(0.0, distance))

    def _get_collection(self, layer: MemoryLayer) -> Any:
        """Return (and lazily create) the collection for a layer."""
        with self._lock:
            if layer in self._collections:
                collection = self._collections[layer]
                self._distance_spaces.setdefault(
                    layer,
                    self._configured_distance_space(collection),
                )
                return collection

            client = self._get_client()
            name = self._collection_name(layer)
            collection = client.get_or_create_collection(
                name=name,
                embedding_function=self._get_embedding_fn(),
            )
            self._collections[layer] = collection
            self._distance_spaces[layer] = self._configured_distance_space(collection)
            logger.debug("Collection '%s' ready (%d items)", name, collection.count())
            return collection

    def _item_from_meta(self, doc_id: str, text: str, meta: dict[str, Any]) -> MemoryEntry:
        """Reconstruct a canonical MemoryEntry from ChromaDB metadata."""
        ts_str = meta.get("timestamp")
        if ts_str is None:
            logger.warning("Memory %s missing timestamp, defaulting to epoch", doc_id)
            ts_str = "1970-01-01T00:00:00+00:00"
        raw_last_accessed = meta.get(_LAST_ACCESSED_META_KEY)
        parsed_last_accessed: datetime | None = None
        invalid_internal_last_accessed = False
        if raw_last_accessed:
            try:
                parsed_last_accessed = datetime.fromisoformat(str(raw_last_accessed))
            except ValueError:
                invalid_internal_last_accessed = True
                logger.warning(
                    "Memory %s has invalid internal last-access timestamp; preserving it as metadata",
                    doc_id,
                )
        extra_metadata = {
            key: value
            for key, value in meta.items()
            if key
            not in {
                "symbol",
                "layer",
                _CATEGORY_META_KEY,
                "importance",
                "recency_delta",
                "access_count",
                "timestamp",
                _LAST_ACCESSED_META_KEY,
            }
        }
        if invalid_internal_last_accessed:
            extra_metadata[_LAST_ACCESSED_META_KEY] = raw_last_accessed
        return MemoryEntry(
            id=doc_id,
            symbol=meta.get("symbol", ""),
            content=text,
            layer=MemoryLayer(meta.get("layer", MemoryLayer.SHORT.value)),
            category=str(meta.get(_CATEGORY_META_KEY, "analysis")),
            importance=float(meta.get("importance", 50.0)) / 100.0,
            recency_delta=int(meta.get("recency_delta", 0)),
            access_count=int(meta.get("access_count", 0)),
            timestamp=datetime.fromisoformat(ts_str),
            last_accessed=parsed_last_accessed,
            metadata=extra_metadata,
        )

    @staticmethod
    def _metadata_from_entry(entry: MemoryEntry) -> dict[str, Any]:
        """Serialise a canonical entry to the existing Chroma metadata shape."""
        if entry.layer is None:
            raise ValueError("Persistent memory entries require a MemoryLayer")
        metadata = dict(entry.metadata)
        metadata.update(
            {
                "symbol": entry.symbol,
                "layer": entry.layer.value,
                _CATEGORY_META_KEY: entry.category,
                "importance": entry.importance_percent,
                "recency_delta": entry.recency_delta,
                "access_count": entry.access_count,
                "timestamp": entry.timestamp.isoformat(),
            }
        )
        if entry.last_accessed is not None:
            metadata[_LAST_ACCESSED_META_KEY] = entry.last_accessed.isoformat()
        return metadata

    def _record_retrieval(self, entry: MemoryEntry) -> None:
        """Persist one access update for an entry returned to the caller."""
        if entry.layer is None:
            raise ValueError("Persistent memory entries require a MemoryLayer")
        entry.access_count += 1
        entry.last_accessed = datetime.now(UTC)
        collection = self._get_collection(entry.layer)
        collection.update(
            ids=[entry.id],
            metadatas=[self._metadata_from_entry(entry)],
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
        *,
        category: str | None = None,
        importance: float | None = None,
        importance_scale: Literal["normalised", "percent"] = "normalised",
    ) -> str:
        """Store a new memory with category- or layer-seeded importance.

        Args:
            symbol: Instrument symbol (e.g. "NIFTY", "RELIANCE").
            text: Memory content to embed and store.
            layer: Which temporal layer to store in.
            metadata: Optional extra key/value pairs stored alongside.
            category: Optional semantic category. Its category default seeds
                importance instead of the layer range.
            importance: Optional explicit importance on either the canonical
                0..1 scale or the legacy 0..100 scale.
            importance_scale: Unit used by explicit ``importance``.

        Returns:
            The stable UUID string assigned to this memory.
        """
        memory_id = str(uuid.uuid4())
        if importance_scale not in {"normalised", "percent"}:
            raise ValueError("importance_scale must be 'normalised' or 'percent'")
        if importance is not None:
            normalised_importance = importance / 100.0 if importance_scale == "percent" else importance
            normalised_importance = max(0.0, min(1.0, normalised_importance))
        elif category is not None:
            normalised_importance = CATEGORY_IMPORTANCE.get(category, _DEFAULT_CATEGORY_IMPORTANCE)
        else:
            normalised_importance = initial_importance(layer) / 100.0
        persisted_importance = normalised_importance * 100.0
        now = datetime.now(UTC)

        entry = MemoryEntry(
            id=memory_id,
            content=text,
            symbol=symbol,
            layer=layer,
            category=category or "analysis",
            importance=normalised_importance,
            timestamp=now,
            metadata=metadata or {},
        )
        chroma_meta = self._metadata_from_entry(entry)

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
            persisted_importance,
        )
        return memory_id

    def add(
        self,
        content: str,
        category: str,
        importance: float | None = None,
        metadata: dict[str, Any] | None = None,
        *,
        symbol: str = "",
        layer: MemoryLayer = MemoryLayer.SHORT,
    ) -> str:
        """Add an entry through the backend-neutral interface."""
        normalised_importance = None if importance is None else max(0.0, min(1.0, importance))
        return self.add_memory(
            symbol=symbol,
            text=content,
            layer=layer,
            metadata=metadata,
            category=category,
            importance=normalised_importance,
        )

    def get_memories(
        self,
        symbol: str | None,
        query: str,
        layer: MemoryLayer,
        n: int = 3,
        *,
        _update_access: bool = True,
    ) -> MemoryQueryResult:
        """Retrieve memories ranked by compound score.

        Fetches up to ``n * _OVERFETCH_MULTIPLIER`` candidates from ChromaDB
        by vector similarity, then Python-side reranks using
        ``compound_score(similarity, recency_delta, importance)``.

        Degraded mode: if the vector query raises (ChromaDB 1.5.x can wedge a
        collection's vector index permanently while its metadata stays
        readable), candidates are fetched by the symbol filter alone and
        reranked with neutral similarity — recency and importance only. The
        degradation is logged loudly; only if the metadata path also fails
        does this return no memories.

        Args:
            symbol: Optional instrument filter. ``None`` searches all symbols.
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

        query_kwargs: dict[str, Any] = {
            "query_texts": [query],
            "n_results": fetch_n,
        }
        if symbol is not None:
            query_kwargs["where"] = {"symbol": symbol}

        try:
            results = collection.query(**query_kwargs)
            ids: list[str] = results.get("ids", [[]])[0]
            documents: list[str] = results.get("documents", [[]])[0]
            metadatas: list[dict[str, Any]] = results.get("metadatas", [[]])[0]
            distances: list[float] = results.get("distances", [[]])[0]
            distance_space = self._distance_spaces.get(layer) or self._configured_distance_space(collection)
            similarities: list[float] = [self._distance_to_similarity(dist, space=distance_space) for dist in distances]
        except Exception:
            # ChromaDB 1.5.9's Rust core can PERMANENTLY wedge a collection's
            # vector index (upstream chroma-core/chroma#7032, open): under
            # rapid collection churn ~4% of add()s lose the embedding write
            # (metadata lands; every later vector-touching plan — query, or
            # get with embeddings — raises InternalError "Error finding id",
            # unrecoverable by retry or a fresh handle), while plain metadata
            # get() still serves the row. Reproduced 326 wedges in 8000 adds
            # on 1.5.9 (the latest release; no upstream fix to upgrade to).
            # Rather than blind the agent, degrade to metadata retrieval:
            # filter by symbol and rerank on recency + importance with
            # NEUTRAL similarity (no vector ranking in this mode).
            logger.warning(
                "Memory vector query failed for %s/%s in %s — falling back to "
                "metadata retrieval (similarity-neutral ranking)",
                symbol,
                query,
                layer.value,
                exc_info=True,
            )
            try:
                # Default include (documents+metadatas) only — requesting
                # embeddings on a wedged collection raises the same error.
                get_kwargs: dict[str, Any] = {"limit": fetch_n}
                if symbol is not None:
                    get_kwargs["where"] = {"symbol": symbol}
                results = collection.get(**get_kwargs)
            except Exception:
                logger.warning(
                    "Memory metadata fallback also failed for %s in %s — returning no memories",
                    symbol,
                    layer.value,
                    exc_info=True,
                )
                return MemoryQueryResult(items=[], query=query, layer=layer)
            # collection.get returns FLAT lists (query returns nested ones)
            ids = results.get("ids") or []
            documents = results.get("documents") or []
            metadatas = results.get("metadatas") or []
            similarities = [0.0] * len(ids)

        if not documents:
            return MemoryQueryResult(items=[], query=query, layer=layer)

        # Build scored candidates
        scored: list[tuple[float, MemoryEntry]] = []

        for doc_id, text, meta, similarity in zip(ids, documents, metadatas, similarities):
            item = self._item_from_meta(doc_id, text, meta)
            score = compound_score(
                similarity,
                item.recency_delta,
                item.importance,
                importance_scale="normalised",
            )
            item._retrieval_score = score
            scored.append((score, item))

        # Sort descending by compound score
        scored.sort(key=lambda t: t[0], reverse=True)
        top_items = [item for _, item in scored[:n]]

        if _update_access:
            for item in top_items:
                self._record_retrieval(item)

        return MemoryQueryResult(items=top_items, query=query, layer=layer)

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        *,
        symbol: str | None = None,
        layer: MemoryLayer | None = None,
    ) -> list[MemoryEntry]:
        """Retrieve entries through the backend-neutral interface."""
        if top_k <= 0:
            return []
        layers = (layer,) if layer is not None else tuple(MemoryLayer)
        entries: list[MemoryEntry] = []
        for candidate_layer in layers:
            entries.extend(
                self.get_memories(
                    symbol=symbol,
                    query=query,
                    layer=candidate_layer,
                    n=top_k,
                    _update_access=False,
                ).items
            )
        entries.sort(
            key=lambda entry: (
                entry._retrieval_score
                if entry._retrieval_score is not None
                else compound_score(
                    similarity=0.0,
                    recency_delta=entry.recency_delta,
                    importance=entry.importance,
                    importance_scale="normalised",
                )
            ),
            reverse=True,
        )
        top_entries = entries[:top_k]
        for entry in top_entries:
            self._record_retrieval(entry)
        return top_entries

    def summarise_context(
        self,
        symbol: str,
        query: str,
        max_tokens: int = 2000,
    ) -> str:
        """Build an LLM-ready context block from all persistent layers."""
        entries = self.retrieve(query, top_k=10, symbol=symbol)
        if not entries:
            return ""

        char_budget = max(0, max_tokens) * 4
        lines: list[str] = ["[Memory Context]"]
        used = len(lines[0]) + 1
        for index, entry in enumerate(entries, start=1):
            layer = entry.layer.value if entry.layer is not None else "unknown"
            timestamp = entry.timestamp.strftime("%Y-%m-%d %H:%M UTC")
            line = f"{index}. [{entry.category}|{layer}] {entry.content} (ts={timestamp})"
            if used + len(line) + 1 > char_budget:
                break
            lines.append(line)
            used += len(line) + 1
        return "\n".join(lines)

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

    def prune(
        self,
        min_score: float = 0.1,
        *,
        min_importance: float = 0.0,
        max_recency_days: int | None = None,
        symbol: str | None = None,
    ) -> int:
        """Remove persistent entries below score/importance or outside a window.

        Args:
            min_score: Similarity-neutral compound-score floor.
            min_importance: Canonical 0..1 importance floor.
            max_recency_days: Optional maximum age in ``recency_delta`` days.
            symbol: Optional symbol scope. ``None`` prunes every symbol.

        Returns:
            Number of deleted entries across all layers.
        """
        removed = 0
        for layer in MemoryLayer:
            collection = self._get_collection(layer)
            if collection.count() == 0:
                continue
            try:
                results = collection.get(include=["metadatas"])
            except Exception:
                logger.warning(
                    "Memory metadata read failed while pruning layer %s",
                    layer.value,
                    exc_info=True,
                )
                continue

            delete_ids: list[str] = []
            ids: list[str] = results.get("ids") or []
            metadatas: list[dict[str, Any]] = results.get("metadatas") or []
            for entry_id, metadata in zip(ids, metadatas):
                if symbol is not None and metadata.get("symbol") != symbol:
                    continue
                recency_delta = int(metadata.get("recency_delta", 0))
                importance = float(metadata.get("importance", 50.0)) / 100.0
                score = compound_score(
                    similarity=0.0,
                    recency_delta=recency_delta,
                    importance=importance,
                    importance_scale="normalised",
                )
                outside_window = max_recency_days is not None and recency_delta > max_recency_days
                if importance < min_importance or score < min_score or outside_window:
                    delete_ids.append(entry_id)

            if delete_ids:
                collection.delete(ids=delete_ids)
                removed += len(delete_ids)

        if removed:
            logger.info(
                "TradedMemory.prune: removed %d entries (min_score=%.2f, min_importance=%.2f)",
                removed,
                min_score,
                min_importance,
            )
        return removed

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

    def clear(self, symbol: str | None = None) -> None:
        """Clear all entries, or only entries for one symbol."""
        if symbol is not None:
            self.clear_symbol(symbol)
            return
        for layer in MemoryLayer:
            collection = self._get_collection(layer)
            if collection.count() == 0:
                continue
            ids: list[str] = collection.get(include=[]).get("ids") or []
            if ids:
                collection.delete(ids=ids)
        logger.debug("clear: removed all persistent memories")


def create_memory_backend(
    config: MemoryBackendConfig | None = None,
) -> MemoryBackend:
    """Create a persistent or hierarchical backend from configuration."""
    resolved = config or MemoryBackendConfig()
    backend = MemoryBackendKind(resolved.backend)
    if backend is MemoryBackendKind.PERSISTENT:
        return TradedMemory(
            persist_dir=resolved.persist_dir,
            collection_prefix=resolved.collection_prefix,
            embedding_model=resolved.embedding_model,
        )

    from .in_process_memory import HierarchicalMemoryManager

    return HierarchicalMemoryManager()


def __getattr__(name: str) -> Any:
    """Lazily expose in-process implementations from the canonical module."""
    if name in {"HierarchicalMemoryManager", "MemoryManager", "MemoryTier"}:
        from . import in_process_memory

        return getattr(in_process_memory, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
