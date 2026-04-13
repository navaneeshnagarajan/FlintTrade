"""Lightweight in-process memory manager with compound scoring for AI agents.

Complements the ChromaDB-backed TradedMemory (memory.py) by providing a fast,
embedding-free, in-memory store suitable for short-lived agent sessions,
strategy contexts, and intraday state where full vector search is not required.

Pattern absorbed from FinMem-LLM-StockTrading:
- Compound scoring: importance x recency-decay x relevance
- Exponential time decay parameterised per entry category
- Access-count boost: frequently accessed memories resist decay
- Pruning: sweep stale low-score entries periodically
- 3-tier hierarchical memory (working / medium / long-term) with
  tier-specific decay half-lives and promotion based on access frequency

Categories and their default importance:

    "trade"          -> 0.90  (actual trade outcomes -- highest signal value)
    "signal"         -> 0.70  (ML or LLM-generated trading signals)
    "analysis"       -> 0.60  (chart / option-chain analysis snapshots)
    "market_event"   -> 0.80  (circuit breakers, SGX gap-up, major news)
    "user_feedback"  -> 0.75  (user-supplied corrections or preferences)

Usage::

    from packages.ai.src.memory_manager import MemoryManager

    mgr = MemoryManager()
    mid = mgr.add("NIFTY broke 22500 CE OI resistance", category="signal", importance=0.75)
    context = mgr.summarise_context("What is NIFTY doing today?")

    # 3-tier hierarchical mode
    hmgr = HierarchicalMemoryManager()
    hmgr.add("Bought NIFTY 22500 CE", category="trade")
    results = hmgr.query("NIFTY trades", top_k=5)
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
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
        category: Semantic category -- one of the CATEGORY_IMPORTANCE keys.
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
# MemoryManager (original single-tier -- backward compatible)
# ---------------------------------------------------------------------------


class MemoryManager:
    """Lightweight in-process memory manager for FlintTrade AI agents.

    Stores entries in a plain Python list. Scoring is fully in-process --
    no ChromaDB or network I/O. Relevance is computed via keyword overlap
    unless the caller supplies embeddings and a similarity function.

    Args:
        decay_rate: Per-hour multiplicative decay applied to the recency
            component. Default 0.995 ~ 60% remaining after 24 hours.
        importance_weight: Weight of the static importance component (0-1).
        recency_weight: Weight of the time-decayed recency component (0-1).
        relevance_weight: Weight of the query-relevance component (0-1).
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

        This does NOT mutate ``importance`` -- importance is a static creation-
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

        Uses relevance=0 so that only importance x recency is compared against
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
        (treating 1 token ~ 4 characters).

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


# ---------------------------------------------------------------------------
# 3-Tier Hierarchical Memory (FinMem pattern)
# ---------------------------------------------------------------------------


class MemoryTier(str, Enum):
    """Memory hierarchy tiers with increasing retention.

    Each tier has a characteristic time window and decay half-life:
    - WORKING: 5-day window, half-life 2 days (fast decay)
    - MEDIUM: 30-day window, half-life 10 days (moderate decay)
    - LONG_TERM: 365-day window, half-life 90 days (slow decay)
    """

    WORKING = "working"
    MEDIUM = "medium"
    LONG_TERM = "long_term"


# Tier configuration: (window_days, half_life_days, tier_weight)
_TIER_CONFIG: dict[MemoryTier, tuple[int, float, float]] = {
    MemoryTier.WORKING: (5, 2.0, 1.0),
    MemoryTier.MEDIUM: (30, 10.0, 0.8),
    MemoryTier.LONG_TERM: (365, 90.0, 0.6),
}

# Promotion threshold: entries accessed >= this many times get promoted
_PROMOTION_THRESHOLD_WORKING_TO_MEDIUM = 3
_PROMOTION_THRESHOLD_MEDIUM_TO_LONG = 5


def _half_life_to_decay_rate(half_life_days: float) -> float:
    """Convert a half-life in days to an hourly decay rate.

    Args:
        half_life_days: Number of days for the score to reach 50%.

    Returns:
        Per-hour multiplicative decay rate.
    """
    half_life_hours = half_life_days * 24.0
    return math.pow(0.5, 1.0 / half_life_hours)


class HierarchicalMemoryManager:
    """3-tier hierarchical memory manager inspired by FinMem.

    Memories are stored in three tiers with different decay profiles:

    - **working_memory**: Recent memories (5-day window), fast decay
      (half-life 2 days). New entries always start here.
    - **medium_memory**: Intermediate memories (30-day window), moderate
      decay (half-life 10 days). Promoted from working when accessed
      >= 3 times.
    - **long_term_memory**: Persistent memories (1-year window), slow
      decay (half-life 90 days). Promoted from medium when accessed
      >= 5 times.

    Queries search all three tiers and merge results with tier-weighted
    scoring so that recently relevant working memories rank alongside
    well-established long-term memories.

    Backward compatibility: this class exposes the same ``add()``,
    ``retrieve()``, ``summarise_context()``, ``size``, ``get_by_id()``,
    ``get_by_category()``, and ``clear()`` interface as ``MemoryManager``.

    Args:
        importance_weight: Weight for the importance component.
        recency_weight: Weight for the recency component.
        relevance_weight: Weight for the relevance component.
    """

    def __init__(
        self,
        importance_weight: float = 0.4,
        recency_weight: float = 0.3,
        relevance_weight: float = 0.3,
    ) -> None:
        self._importance_weight = importance_weight
        self._recency_weight = recency_weight
        self._relevance_weight = relevance_weight

        # Each tier stores its own list of entries
        self._tiers: dict[MemoryTier, list[MemoryEntry]] = {
            MemoryTier.WORKING: [],
            MemoryTier.MEDIUM: [],
            MemoryTier.LONG_TERM: [],
        }

        # Track which tier each entry lives in (by entry ID)
        self._entry_tier: dict[str, MemoryTier] = {}

        # Pre-compute per-hour decay rates from half-lives
        self._decay_rates: dict[MemoryTier, float] = {
            tier: _half_life_to_decay_rate(config[1])
            for tier, config in _TIER_CONFIG.items()
        }

    # ------------------------------------------------------------------
    # Public API (backward-compatible with MemoryManager)
    # ------------------------------------------------------------------

    def add(
        self,
        content: str,
        category: str,
        importance: float | None = None,
        metadata: dict[str, Any] | None = None,
        tier: MemoryTier | None = None,
    ) -> str:
        """Add a new memory entry to the working tier (or a specified tier).

        Args:
            content: Free-text memory content.
            category: Semantic category (e.g. "trade", "signal").
            importance: Override importance score in [0, 1].
            metadata: Optional extra key/value payload.
            tier: Target tier. Defaults to WORKING for new entries.

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

        target_tier = tier if tier is not None else MemoryTier.WORKING
        self._tiers[target_tier].append(entry)
        self._entry_tier[entry.id] = target_tier

        logger.debug(
            "HierarchicalMemoryManager.add: id=%s tier=%s category=%s importance=%.2f",
            entry.id, target_tier.value, category, importance,
        )
        return entry.id

    def retrieve(self, query: str, top_k: int = 5) -> list[MemoryEntry]:
        """Retrieve entries from all tiers, ranked by tier-weighted compound score.

        Args:
            query: Natural-language retrieval query.
            top_k: Maximum number of entries to return.

        Returns:
            List of MemoryEntry objects from any tier, sorted by descending
            weighted score.
        """
        now = datetime.now(timezone.utc)
        query_tokens = set(query.lower().split())
        scored: list[tuple[float, MemoryEntry]] = []

        for tier, entries in self._tiers.items():
            decay_rate = self._decay_rates[tier]
            tier_weight = _TIER_CONFIG[tier][2]

            for entry in entries:
                relevance = self._relevance(entry, query_tokens)
                score = self._compound_score(entry, relevance, decay_rate, now)
                weighted_score = score * tier_weight
                scored.append((weighted_score, entry))

        scored.sort(key=lambda t: t[0], reverse=True)
        top = [entry for _, entry in scored[:top_k]]

        # Update access metadata and check for promotion
        for entry in top:
            entry.access_count += 1
            entry.last_accessed = now
            self._maybe_promote(entry)

        return top

    def query(self, query: str, top_k: int = 5) -> list[MemoryEntry]:
        """Alias for retrieve() -- searches all 3 tiers and merges results.

        Args:
            query: Natural-language retrieval query.
            top_k: Maximum number of entries to return.

        Returns:
            Merged and scored list of MemoryEntry objects.
        """
        return self.retrieve(query, top_k=top_k)

    def summarise_context(self, query: str, max_tokens: int = 2000) -> str:
        """Build a context string from top memories for LLM injection.

        Args:
            query: The retrieval query.
            max_tokens: Approximate character budget.

        Returns:
            Formatted multi-line string, or empty string if no entries.
        """
        entries = self.retrieve(query, top_k=10)
        if not entries:
            return ""

        char_budget = max_tokens * 4
        lines: list[str] = ["[Memory Context]"]
        used = len(lines[0]) + 1

        for i, entry in enumerate(entries, start=1):
            ts = entry.timestamp.strftime("%Y-%m-%d %H:%M UTC")
            tier = self._entry_tier.get(entry.id, "unknown")
            tier_label = tier.value if isinstance(tier, MemoryTier) else tier
            line = f"{i}. [{entry.category}|{tier_label}] {entry.content} (ts={ts})"
            if used + len(line) + 1 > char_budget:
                break
            lines.append(line)
            used += len(line) + 1

        return "\n".join(lines)

    def prune(self, min_score: float = 0.1) -> int:
        """Remove stale entries from all tiers.

        Also removes entries outside their tier's time window.

        Args:
            min_score: Score floor (relevance=0 scoring).

        Returns:
            Total number of entries removed across all tiers.
        """
        now = datetime.now(timezone.utc)
        total_removed = 0

        for tier, entries in self._tiers.items():
            decay_rate = self._decay_rates[tier]
            window_days = _TIER_CONFIG[tier][0]
            cutoff = now - timedelta(days=window_days)
            before = len(entries)

            kept: list[MemoryEntry] = []
            for e in entries:
                # Remove if outside window
                if e.timestamp < cutoff:
                    self._entry_tier.pop(e.id, None)
                    continue
                # Remove if score too low
                score = self._compound_score(e, relevance=0.0, decay_rate=decay_rate, now=now)
                if score < min_score:
                    self._entry_tier.pop(e.id, None)
                    continue
                kept.append(e)

            self._tiers[tier] = kept
            removed = before - len(kept)
            total_removed += removed

        if total_removed:
            logger.info(
                "HierarchicalMemoryManager.prune: removed %d entries (min_score=%.2f)",
                total_removed, min_score,
            )
        return total_removed

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        """Total number of entries across all tiers."""
        return sum(len(entries) for entries in self._tiers.values())

    def tier_sizes(self) -> dict[str, int]:
        """Return the count of entries per tier.

        Returns:
            Dict mapping tier name to entry count.
        """
        return {tier.value: len(entries) for tier, entries in self._tiers.items()}

    def get_by_id(self, entry_id: str) -> MemoryEntry | None:
        """Find an entry by UUID across all tiers.

        Args:
            entry_id: The UUID to look up.

        Returns:
            The MemoryEntry or None.
        """
        for entries in self._tiers.values():
            for entry in entries:
                if entry.id == entry_id:
                    return entry
        return None

    def get_by_category(self, category: str) -> list[MemoryEntry]:
        """Return all entries matching a category across all tiers.

        Args:
            category: Category string to filter on.

        Returns:
            List of matching entries (unscored).
        """
        result: list[MemoryEntry] = []
        for entries in self._tiers.values():
            result.extend(e for e in entries if e.category == category)
        return result

    def get_tier(self, entry_id: str) -> MemoryTier | None:
        """Return the tier an entry currently resides in.

        Args:
            entry_id: The UUID to look up.

        Returns:
            The MemoryTier or None if not found.
        """
        return self._entry_tier.get(entry_id)

    def clear(self) -> None:
        """Remove all entries from all tiers."""
        for entries in self._tiers.values():
            entries.clear()
        self._entry_tier.clear()
        logger.debug("HierarchicalMemoryManager.clear: all entries removed")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compound_score(
        self,
        entry: MemoryEntry,
        relevance: float,
        decay_rate: float,
        now: datetime,
    ) -> float:
        """Compute compound score using a tier-specific decay rate.

        Args:
            entry: The memory entry.
            relevance: Pre-computed relevance in [0, 1].
            decay_rate: Per-hour decay rate for the entry's tier.
            now: Reference time.

        Returns:
            Composite float score.
        """
        hours_old = max(0.0, (now - entry.timestamp).total_seconds() / 3600.0)
        recency_raw = math.pow(decay_rate, hours_old)
        access_boost = entry.access_count * _ACCESS_DECAY_BOOST
        recency = min(1.0, recency_raw + access_boost)

        return (
            self._importance_weight * entry.importance
            + self._recency_weight * recency
            + self._relevance_weight * relevance
        )

    def _relevance(self, entry: MemoryEntry, query_tokens: set[str]) -> float:
        """Keyword-overlap relevance."""
        if not query_tokens:
            return 0.0
        content_tokens = set(entry.content.lower().split())
        if not content_tokens:
            return 0.0
        overlap = len(query_tokens & content_tokens)
        return overlap / len(query_tokens)

    def _maybe_promote(self, entry: MemoryEntry) -> None:
        """Promote an entry to a higher tier if access threshold is met.

        Working -> Medium: access_count >= 3
        Medium -> Long-term: access_count >= 5
        """
        current_tier = self._entry_tier.get(entry.id)
        if current_tier is None:
            return

        target_tier: MemoryTier | None = None

        if (
            current_tier == MemoryTier.WORKING
            and entry.access_count >= _PROMOTION_THRESHOLD_WORKING_TO_MEDIUM
        ):
            target_tier = MemoryTier.MEDIUM
        elif (
            current_tier == MemoryTier.MEDIUM
            and entry.access_count >= _PROMOTION_THRESHOLD_MEDIUM_TO_LONG
        ):
            target_tier = MemoryTier.LONG_TERM

        if target_tier is not None and target_tier != current_tier:
            # Move entry from current tier to target tier
            self._tiers[current_tier] = [
                e for e in self._tiers[current_tier] if e.id != entry.id
            ]
            self._tiers[target_tier].append(entry)
            self._entry_tier[entry.id] = target_tier
            logger.info(
                "Promoted entry %s from %s to %s (access_count=%d)",
                entry.id, current_tier.value, target_tier.value, entry.access_count,
            )
