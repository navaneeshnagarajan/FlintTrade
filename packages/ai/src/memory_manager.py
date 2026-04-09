"""Lightweight in-process memory manager with compound scoring for AI agents.

Complements the ChromaDB-backed TradedMemory (memory.py) by providing a fast,
embedding-free, in-memory store suitable for short-lived agent sessions,
strategy contexts, and intraday state where full vector search is not required.

Pattern absorbed from FinMem-LLM-StockTrading:
- Compound scoring: importance × recency-decay × relevance
- Exponential time decay parameterised per entry category
- Access-count boost: frequently accessed memories resist decay
- Pruning: sweep stale low-score entries periodically

Categories and their default importance:

    "trade"          → 0.90  (actual trade outcomes — highest signal value)
    "signal"         → 0.70  (ML or LLM-generated trading signals)
    "analysis"       → 0.60  (chart / option-chain analysis snapshots)
    "market_event"   → 0.80  (circuit breakers, SGX gap-up, major news)
    "user_feedback"  → 0.75  (user-supplied corrections or preferences)

Usage::

    from packages.ai.src.memory_manager import MemoryManager

    mgr = MemoryManager()
    mid = mgr.add("NIFTY broke 22500 CE OI resistance", category="signal", importance=0.75)
    context = mgr.summarise_context("What is NIFTY doing today?")
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("flinttrade.ai.memory_manager")

# ---------------------------------------------------------------------------
# Category defaults
# ---------------------------------------------------------------------------

CATEGORY_IMPORTANCE: dict[str, float] = {
    "trade": 0.90,
    "market_event": 0.80,
    "user_feedback": 0.75,
    "signal": 0.70,
    "analysis": 0.60,
}

_DEFAULT_IMPORTANCE = 0.65
_ACCESS_DECAY_BOOST = 0.005  # per additional access beyond first


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class MemoryEntry(BaseModel):
    """A single in-memory entry stored by MemoryManager.

    Attributes:
        id: Stable UUID string assigned at creation.
        content: Free-text memory content.
        category: Semantic category — one of the CATEGORY_IMPORTANCE keys.
        importance: Creation-time importance in [0, 1].
        timestamp: UTC creation time.
        access_count: Number of times this entry was returned by retrieve().
        last_accessed: UTC time of the most recent retrieval (None if never).
        embedding: Optional dense embedding vector (populated by caller).
        metadata: Arbitrary key/value pairs for filtering or display.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: str
    category: str
    importance: float = Field(ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    access_count: int = 0
    last_accessed: datetime | None = None
    embedding: list[float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# MemoryManager
# ---------------------------------------------------------------------------


class MemoryManager:
    """Lightweight in-process memory manager for FlintTrade AI agents.

    Stores entries in a plain Python list. Scoring is fully in-process —
    no ChromaDB or network I/O. Relevance is computed via keyword overlap
    unless the caller supplies embeddings and a similarity function.

    Args:
        decay_rate: Per-hour multiplicative decay applied to the recency
            component. Default 0.995 ≈ ~60% remaining after 24 hours.
        importance_weight: Weight of the static importance component (0–1).
        recency_weight: Weight of the time-decayed recency component (0–1).
        relevance_weight: Weight of the query-relevance component (0–1).
            The three weights need not sum to 1; raw scores are compared.

    Note:
        If you need persistent, vector-similarity-based retrieval across
        trading sessions, use TradedMemory (memory.py) instead.
    """

    def __init__(
        self,
        decay_rate: float = 0.995,
        importance_weight: float = 0.4,
        recency_weight: float = 0.3,
        relevance_weight: float = 0.3,
    ) -> None:
        self._decay_rate = decay_rate
        self._importance_weight = importance_weight
        self._recency_weight = recency_weight
        self._relevance_weight = relevance_weight
        self._entries: list[MemoryEntry] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(
        self,
        content: str,
        category: str,
        importance: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Add a new memory entry and return its UUID.

        If *importance* is omitted, the category default from
        CATEGORY_IMPORTANCE is used, falling back to 0.65.

        Args:
            content: Free-text memory content.
            category: Semantic category (e.g. ``"trade"``, ``"signal"``).
            importance: Override importance score in [0, 1]. If None, the
                category default applies.
            metadata: Optional extra key/value payload stored on the entry.

        Returns:
            UUID string of the newly created entry.
        """
        if importance is None:
            importance = CATEGORY_IMPORTANCE.get(category, _DEFAULT_IMPORTANCE)

        importance = max(0.0, min(1.0, importance))
        entry = MemoryEntry(
            content=content,
            category=category,
            importance=importance,
            metadata=metadata or {},
        )
        self._entries.append(entry)
        logger.debug("MemoryManager.add: id=%s category=%s importance=%.2f", entry.id, category, importance)
        return entry.id

    def retrieve(self, query: str, top_k: int = 5) -> list[MemoryEntry]:
        """Retrieve the top-k entries ranked by compound score.

        Relevance is computed as a normalised keyword-overlap ratio between
        the query tokens and the entry content tokens. Pass embeddings to the
        entries and override ``_relevance`` if you want vector similarity.

        Args:
            query: Natural-language retrieval query.
            top_k: Maximum number of entries to return.

        Returns:
            List of MemoryEntry objects sorted by descending compound score.
        """
        if not self._entries:
            return []

        now = datetime.now(timezone.utc)
        scored: list[tuple[float, MemoryEntry]] = []

        query_tokens = set(query.lower().split())

        for entry in self._entries:
            relevance = self._relevance(entry, query_tokens)
            score = self.compound_score(entry, relevance, now)
            scored.append((score, entry))

        scored.sort(key=lambda t: t[0], reverse=True)
        top = [entry for _, entry in scored[:top_k]]

        # Update access metadata in place
        for entry in top:
            entry.access_count += 1
            entry.last_accessed = now

        return top

    def compound_score(
        self,
        entry: MemoryEntry,
        relevance: float,
        now: datetime | None = None,
    ) -> float:
        """Compute a composite ranking score for a single entry.

        Formula::

            score = (importance_weight * importance)
                  + (recency_weight   * recency_decay)
                  + (relevance_weight * relevance)

        Access boost: each additional retrieval beyond the first slows decay
        by adding ``access_count * _ACCESS_DECAY_BOOST`` to the recency term.

        Args:
            entry: The memory entry to score.
            relevance: Pre-computed relevance score in [0, 1].
            now: Reference time for recency calculation (UTC). Defaults to
                ``datetime.now(timezone.utc)`` if None.

        Returns:
            Composite float score. Higher is more relevant.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        hours_old = max(0.0, (now - entry.timestamp).total_seconds() / 3600.0)
        recency_raw = math.pow(self._decay_rate, hours_old)

        # Access boost: frequently-retrieved entries resist decay
        access_boost = entry.access_count * _ACCESS_DECAY_BOOST
        recency = min(1.0, recency_raw + access_boost)

        return (
            self._importance_weight * entry.importance
            + self._recency_weight * recency
            + self._relevance_weight * relevance
        )

    def decay_all(self) -> None:
        """Apply one epoch of time-based recency decay to all entries.

        This does NOT mutate ``importance`` — importance is a static creation-
        time value. Recency is always computed on-the-fly from the timestamp.
        This method is provided as a hook for callers who want to trigger a
        background sweep (e.g. on market open) and inspect score distributions.

        In practice, ``retrieve()`` already computes fresh recency per call,
        so ``decay_all`` is mainly useful for monitoring and logging.
        """
        now = datetime.now(timezone.utc)
        for entry in self._entries:
            hours_old = max(0.0, (now - entry.timestamp).total_seconds() / 3600.0)
            score = math.pow(self._decay_rate, hours_old)
            logger.debug(
                "decay_all: id=%s hours_old=%.1f recency_score=%.4f",
                entry.id,
                hours_old,
                score,
            )

    def prune(self, min_score: float = 0.1) -> int:
        """Remove entries whose compound score (with zero relevance) is below threshold.

        Uses relevance=0 so that only importance × recency is compared against
        the threshold. Entries with no recent access and low importance are
        swept out.

        Args:
            min_score: Score floor. Entries below this are deleted.

        Returns:
            Number of entries removed.
        """
        now = datetime.now(timezone.utc)
        before = len(self._entries)
        self._entries = [
            e for e in self._entries
            if self.compound_score(e, relevance=0.0, now=now) >= min_score
        ]
        removed = before - len(self._entries)
        if removed:
            logger.info("MemoryManager.prune: removed %d entries (min_score=%.2f)", removed, min_score)
        return removed

    def summarise_context(self, query: str, max_tokens: int = 2000) -> str:
        """Build a context string from top memories for LLM injection.

        Retrieves the most relevant entries, formats each as a numbered line,
        and truncates the output to approximately *max_tokens* characters
        (treating 1 token ≈ 4 characters).

        Args:
            query: The retrieval query.
            max_tokens: Approximate character budget for the output.

        Returns:
            Formatted multi-line string ready for LLM system or user prompt.
            Returns an empty string if no entries are stored.
        """
        entries = self.retrieve(query, top_k=10)
        if not entries:
            return ""

        char_budget = max_tokens * 4
        lines: list[str] = ["[Memory Context]"]
        used = len(lines[0]) + 1

        for i, entry in enumerate(entries, start=1):
            ts = entry.timestamp.strftime("%Y-%m-%d %H:%M UTC")
            line = f"{i}. [{entry.category}] {entry.content} (ts={ts})"
            if used + len(line) + 1 > char_budget:
                break
            lines.append(line)
            used += len(line) + 1

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        """Number of entries currently stored."""
        return len(self._entries)

    def get_by_id(self, entry_id: str) -> MemoryEntry | None:
        """Retrieve a specific entry by its UUID.

        Args:
            entry_id: The UUID returned by add().

        Returns:
            The MemoryEntry or None if not found.
        """
        for entry in self._entries:
            if entry.id == entry_id:
                return entry
        return None

    def get_by_category(self, category: str) -> list[MemoryEntry]:
        """Return all entries belonging to a category.

        Args:
            category: Category string to filter on.

        Returns:
            List of matching MemoryEntry objects (unscored, insertion order).
        """
        return [e for e in self._entries if e.category == category]

    def clear(self) -> None:
        """Remove all stored entries."""
        self._entries.clear()
        logger.debug("MemoryManager.clear: all entries removed")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _relevance(self, entry: MemoryEntry, query_tokens: set[str]) -> float:
        """Compute keyword-overlap relevance between an entry and query tokens.

        Args:
            entry: The candidate memory entry.
            query_tokens: Lowercased, split query tokens.

        Returns:
            Normalised overlap in [0, 1]. Returns 0.0 when query is empty.
        """
        if not query_tokens:
            return 0.0
        content_tokens = set(entry.content.lower().split())
        if not content_tokens:
            return 0.0
        overlap = len(query_tokens & content_tokens)
        return overlap / len(query_tokens)
