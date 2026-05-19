"""Tests for MemoryManager and HierarchicalMemoryManager.

All tests are purely in-process (no ChromaDB, no I/O).
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from packages.ai.src.memory_manager import (
    CATEGORY_IMPORTANCE,
    HierarchicalMemoryManager,
    MemoryEntry,
    MemoryManager,
    MemoryTier,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mgr() -> MemoryManager:
    """Fresh MemoryManager for each test."""
    return MemoryManager()


def _make_entry(
    content: str = "test content",
    category: str = "signal",
    importance: float = 0.7,
    hours_ago: float = 0.0,
    access_count: int = 0,
) -> MemoryEntry:
    """Create a MemoryEntry with a fixed timestamp for deterministic tests."""
    ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return MemoryEntry(
        content=content,
        category=category,
        importance=importance,
        timestamp=ts,
        access_count=access_count,
    )


# ---------------------------------------------------------------------------
# MemoryEntry model
# ---------------------------------------------------------------------------


class TestMemoryEntry:
    def test_id_auto_assigned(self) -> None:
        entry = MemoryEntry(content="hello", category="signal", importance=0.5)
        assert isinstance(entry.id, str)
        assert len(entry.id) > 0

    def test_unique_ids(self) -> None:
        ids = {MemoryEntry(content="x", category="trade", importance=0.8).id for _ in range(10)}
        assert len(ids) == 10

    def test_importance_clamped(self) -> None:
        with pytest.raises(Exception):
            MemoryEntry(content="x", category="trade", importance=1.5)

    def test_timestamp_defaults_to_utc_now(self) -> None:
        before = datetime.now(timezone.utc)
        entry = MemoryEntry(content="x", category="trade", importance=0.5)
        after = datetime.now(timezone.utc)
        assert before <= entry.timestamp <= after

    def test_metadata_defaults_empty(self) -> None:
        entry = MemoryEntry(content="x", category="signal", importance=0.5)
        assert entry.metadata == {}

    def test_last_accessed_defaults_none(self) -> None:
        entry = MemoryEntry(content="x", category="signal", importance=0.5)
        assert entry.last_accessed is None


# ---------------------------------------------------------------------------
# MemoryManager.add
# ---------------------------------------------------------------------------


class TestAdd:
    def test_returns_string_id(self, mgr: MemoryManager) -> None:
        entry_id = mgr.add("NIFTY broke resistance", category="signal")
        assert isinstance(entry_id, str)
        assert len(entry_id) > 0

    def test_size_increments(self, mgr: MemoryManager) -> None:
        assert mgr.size == 0
        mgr.add("content 1", category="signal")
        mgr.add("content 2", category="trade")
        assert mgr.size == 2

    def test_category_default_importance(self, mgr: MemoryManager) -> None:
        entry_id = mgr.add("trade result", category="trade")
        entry = mgr.get_by_id(entry_id)
        assert entry is not None
        assert entry.importance == CATEGORY_IMPORTANCE["trade"]

    def test_explicit_importance_respected(self, mgr: MemoryManager) -> None:
        entry_id = mgr.add("custom imp", category="signal", importance=0.42)
        entry = mgr.get_by_id(entry_id)
        assert entry is not None
        assert entry.importance == pytest.approx(0.42)

    def test_importance_clamped_above_one(self, mgr: MemoryManager) -> None:
        entry_id = mgr.add("high", category="signal", importance=5.0)
        entry = mgr.get_by_id(entry_id)
        assert entry.importance == pytest.approx(1.0)

    def test_importance_clamped_below_zero(self, mgr: MemoryManager) -> None:
        entry_id = mgr.add("low", category="signal", importance=-0.5)
        entry = mgr.get_by_id(entry_id)
        assert entry.importance == pytest.approx(0.0)

    def test_metadata_stored(self, mgr: MemoryManager) -> None:
        entry_id = mgr.add("meta test", category="analysis", metadata={"symbol": "NIFTY"})
        entry = mgr.get_by_id(entry_id)
        assert entry.metadata == {"symbol": "NIFTY"}

    def test_unknown_category_uses_default_importance(self, mgr: MemoryManager) -> None:
        entry_id = mgr.add("unknown cat", category="custom_category")
        entry = mgr.get_by_id(entry_id)
        assert 0.0 <= entry.importance <= 1.0


# ---------------------------------------------------------------------------
# MemoryManager.compound_score
# ---------------------------------------------------------------------------


class TestCompoundScore:
    def test_higher_importance_yields_higher_score(self, mgr: MemoryManager) -> None:
        e_high = _make_entry(importance=0.9, hours_ago=1)
        e_low = _make_entry(importance=0.2, hours_ago=1)
        now = datetime.now(timezone.utc)
        assert mgr.compound_score(e_high, 0.5, now) > mgr.compound_score(e_low, 0.5, now)

    def test_fresher_entry_yields_higher_score(self, mgr: MemoryManager) -> None:
        fresh = _make_entry(importance=0.6, hours_ago=0.5)
        old = _make_entry(importance=0.6, hours_ago=48.0)
        now = datetime.now(timezone.utc)
        assert mgr.compound_score(fresh, 0.5, now) > mgr.compound_score(old, 0.5, now)

    def test_higher_relevance_yields_higher_score(self, mgr: MemoryManager) -> None:
        entry = _make_entry(importance=0.6, hours_ago=1)
        now = datetime.now(timezone.utc)
        score_hi = mgr.compound_score(entry, relevance=0.9, now=now)
        score_lo = mgr.compound_score(entry, relevance=0.1, now=now)
        assert score_hi > score_lo

    def test_score_non_negative(self, mgr: MemoryManager) -> None:
        entry = _make_entry(importance=0.0, hours_ago=1000.0, access_count=0)
        now = datetime.now(timezone.utc)
        assert mgr.compound_score(entry, relevance=0.0, now=now) >= 0.0

    def test_access_boost_slows_decay(self, mgr: MemoryManager) -> None:
        # Same entry but one has been accessed many times
        e_new = _make_entry(importance=0.5, hours_ago=24.0, access_count=0)
        e_boosted = _make_entry(importance=0.5, hours_ago=24.0, access_count=50)
        now = datetime.now(timezone.utc)
        assert mgr.compound_score(e_boosted, 0.5, now) > mgr.compound_score(e_new, 0.5, now)


# ---------------------------------------------------------------------------
# MemoryManager.retrieve
# ---------------------------------------------------------------------------


class TestRetrieve:
    def test_empty_returns_empty(self, mgr: MemoryManager) -> None:
        assert mgr.retrieve("NIFTY trend") == []

    def test_returns_at_most_top_k(self, mgr: MemoryManager) -> None:
        for i in range(8):
            mgr.add(f"NIFTY signal {i}", category="signal")
        results = mgr.retrieve("NIFTY signal", top_k=3)
        assert len(results) <= 3

    def test_increments_access_count(self, mgr: MemoryManager) -> None:
        entry_id = mgr.add("NIFTY breakout confirmed", category="signal")
        mgr.retrieve("NIFTY breakout")
        entry = mgr.get_by_id(entry_id)
        assert entry.access_count == 1

    def test_sets_last_accessed(self, mgr: MemoryManager) -> None:
        entry_id = mgr.add("NIFTY market event", category="market_event")
        before = datetime.now(timezone.utc)
        mgr.retrieve("NIFTY market")
        entry = mgr.get_by_id(entry_id)
        assert entry.last_accessed is not None
        assert entry.last_accessed >= before

    def test_high_importance_ranks_first(self, mgr: MemoryManager) -> None:
        # Add two entries with same category and content; one with very high importance
        mgr.add("NIFTY movement signal low", category="signal", importance=0.1)
        high_id = mgr.add("NIFTY movement signal high", category="signal", importance=0.99)
        results = mgr.retrieve("NIFTY movement signal", top_k=2)
        assert results[0].id == high_id

    def test_relevant_entry_ranks_higher_than_irrelevant(self, mgr: MemoryManager) -> None:
        mgr.add("NIFTY strong bullish momentum breakout", category="signal", importance=0.7)
        mgr.add("weather is sunny today", category="signal", importance=0.7)
        results = mgr.retrieve("NIFTY bullish momentum", top_k=2)
        # The relevant entry should rank first
        assert "NIFTY" in results[0].content


# ---------------------------------------------------------------------------
# MemoryManager.prune
# ---------------------------------------------------------------------------


class TestPrune:
    def test_removes_stale_entries(self) -> None:
        # Use a MemoryManager with zero importance_weight so the only scoring factor
        # is recency decay.  With decay_rate=0.01, a 300-hour-old entry has
        # recency_score ≈ 0.01^300 ≈ 0, well below the min_score of 0.05.
        mgr = MemoryManager(
            decay_rate=0.01,
            importance_weight=0.0,
            recency_weight=1.0,
            relevance_weight=0.0,
        )
        old_id = mgr.add("old stale signal", category="signal", importance=0.3)
        fresh_id = mgr.add("fresh signal today", category="signal", importance=0.9)

        # Manually backdate the old entry so its recency score collapses to ~0
        entry = mgr.get_by_id(old_id)
        entry.timestamp = datetime.now(timezone.utc) - timedelta(hours=300)

        removed = mgr.prune(min_score=0.05)
        assert removed >= 1
        assert mgr.get_by_id(fresh_id) is not None

    def test_prune_returns_count(self, mgr: MemoryManager) -> None:
        for i in range(3):
            mgr.add(f"entry {i}", category="analysis", importance=0.9)
        removed = mgr.prune(min_score=0.0)
        assert removed == 0  # nothing should be pruned at threshold 0

    def test_prune_empty_returns_zero(self, mgr: MemoryManager) -> None:
        assert mgr.prune() == 0


# ---------------------------------------------------------------------------
# MemoryManager.decay_all
# ---------------------------------------------------------------------------


class TestDecayAll:
    def test_decay_all_does_not_raise(self, mgr: MemoryManager) -> None:
        mgr.add("signal 1", category="signal")
        mgr.add("trade 1", category="trade")
        mgr.decay_all()  # should not raise

    def test_decay_all_empty_does_not_raise(self, mgr: MemoryManager) -> None:
        mgr.decay_all()


# ---------------------------------------------------------------------------
# MemoryManager.summarise_context
# ---------------------------------------------------------------------------


class TestSummariseContext:
    def test_empty_returns_empty_string(self, mgr: MemoryManager) -> None:
        assert mgr.summarise_context("NIFTY") == ""

    def test_starts_with_header(self, mgr: MemoryManager) -> None:
        mgr.add("NIFTY broke 22500 CE", category="signal")
        context = mgr.summarise_context("NIFTY")
        assert context.startswith("[Memory Context]")

    def test_respects_max_tokens(self, mgr: MemoryManager) -> None:
        for i in range(20):
            mgr.add("x" * 200, category="signal", importance=0.9)
        context = mgr.summarise_context("x", max_tokens=50)
        assert len(context) <= 50 * 4 + 100  # some slack for header

    def test_includes_entry_content(self, mgr: MemoryManager) -> None:
        mgr.add("BANKNIFTY huge OI buildup", category="signal")
        context = mgr.summarise_context("BANKNIFTY OI")
        assert "BANKNIFTY huge OI buildup" in context


# ---------------------------------------------------------------------------
# MemoryManager helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_get_by_id_returns_entry(self, mgr: MemoryManager) -> None:
        entry_id = mgr.add("content", category="signal")
        assert mgr.get_by_id(entry_id) is not None

    def test_get_by_id_unknown_returns_none(self, mgr: MemoryManager) -> None:
        assert mgr.get_by_id("nonexistent-uuid") is None

    def test_get_by_category(self, mgr: MemoryManager) -> None:
        mgr.add("trade one", category="trade")
        mgr.add("trade two", category="trade")
        mgr.add("signal one", category="signal")
        trades = mgr.get_by_category("trade")
        assert len(trades) == 2
        assert all(e.category == "trade" for e in trades)

    def test_clear_removes_all(self, mgr: MemoryManager) -> None:
        for i in range(5):
            mgr.add(f"entry {i}", category="signal")
        assert mgr.size == 5
        mgr.clear()
        assert mgr.size == 0


# ===========================================================================
# HierarchicalMemoryManager (3-tier FinMem pattern)
# ===========================================================================


@pytest.fixture
def hmgr() -> HierarchicalMemoryManager:
    """Fresh HierarchicalMemoryManager for each test."""
    return HierarchicalMemoryManager()


class TestHierarchicalAdd:
    def test_returns_string_id(self, hmgr: HierarchicalMemoryManager) -> None:
        entry_id = hmgr.add("NIFTY broke resistance", category="signal")
        assert isinstance(entry_id, str)
        assert len(entry_id) > 0

    def test_starts_in_working_tier(self, hmgr: HierarchicalMemoryManager) -> None:
        entry_id = hmgr.add("test content", category="signal")
        assert hmgr.get_tier(entry_id) == MemoryTier.WORKING

    def test_size_increments(self, hmgr: HierarchicalMemoryManager) -> None:
        assert hmgr.size == 0
        hmgr.add("content 1", category="signal")
        hmgr.add("content 2", category="trade")
        assert hmgr.size == 2

    def test_explicit_tier(self, hmgr: HierarchicalMemoryManager) -> None:
        entry_id = hmgr.add("long-term memory", category="trade", tier=MemoryTier.LONG_TERM)
        assert hmgr.get_tier(entry_id) == MemoryTier.LONG_TERM

    def test_category_default_importance(self, hmgr: HierarchicalMemoryManager) -> None:
        entry_id = hmgr.add("trade result", category="trade")
        entry = hmgr.get_by_id(entry_id)
        assert entry is not None
        assert entry.importance == CATEGORY_IMPORTANCE["trade"]


class TestHierarchicalTierSizes:
    def test_initial_sizes_zero(self, hmgr: HierarchicalMemoryManager) -> None:
        sizes = hmgr.tier_sizes()
        assert sizes == {"working": 0, "medium": 0, "long_term": 0}

    def test_add_reflects_in_working(self, hmgr: HierarchicalMemoryManager) -> None:
        hmgr.add("entry", category="signal")
        sizes = hmgr.tier_sizes()
        assert sizes["working"] == 1
        assert sizes["medium"] == 0
        assert sizes["long_term"] == 0


class TestHierarchicalRetrieve:
    def test_empty_returns_empty(self, hmgr: HierarchicalMemoryManager) -> None:
        assert hmgr.retrieve("NIFTY") == []

    def test_returns_at_most_top_k(self, hmgr: HierarchicalMemoryManager) -> None:
        for i in range(8):
            hmgr.add(f"NIFTY signal {i}", category="signal")
        results = hmgr.retrieve("NIFTY signal", top_k=3)
        assert len(results) <= 3

    def test_increments_access_count(self, hmgr: HierarchicalMemoryManager) -> None:
        entry_id = hmgr.add("NIFTY breakout confirmed", category="signal")
        hmgr.retrieve("NIFTY breakout")
        entry = hmgr.get_by_id(entry_id)
        assert entry is not None
        assert entry.access_count == 1

    def test_query_alias_works(self, hmgr: HierarchicalMemoryManager) -> None:
        hmgr.add("NIFTY data", category="signal")
        results = hmgr.query("NIFTY", top_k=5)
        assert len(results) >= 1

    def test_searches_all_tiers(self, hmgr: HierarchicalMemoryManager) -> None:
        hmgr.add("working entry NIFTY", category="signal", tier=MemoryTier.WORKING)
        hmgr.add("medium entry NIFTY", category="signal", tier=MemoryTier.MEDIUM)
        hmgr.add("long-term entry NIFTY", category="signal", tier=MemoryTier.LONG_TERM)
        results = hmgr.query("NIFTY entry", top_k=10)
        assert len(results) == 3


class TestHierarchicalPromotion:
    def test_promotes_working_to_medium(self, hmgr: HierarchicalMemoryManager) -> None:
        entry_id = hmgr.add("NIFTY signal promote", category="signal")
        assert hmgr.get_tier(entry_id) == MemoryTier.WORKING

        # Access 3 times to trigger promotion
        for _ in range(3):
            hmgr.retrieve("NIFTY signal promote")

        assert hmgr.get_tier(entry_id) == MemoryTier.MEDIUM

    def test_promotes_medium_to_long_term(self, hmgr: HierarchicalMemoryManager) -> None:
        entry_id = hmgr.add("NIFTY long memory", category="trade", tier=MemoryTier.MEDIUM)
        assert hmgr.get_tier(entry_id) == MemoryTier.MEDIUM

        # Access 5 times to trigger promotion
        for _ in range(5):
            hmgr.retrieve("NIFTY long memory")

        assert hmgr.get_tier(entry_id) == MemoryTier.LONG_TERM

    def test_working_to_medium_updates_tier_sizes(self, hmgr: HierarchicalMemoryManager) -> None:
        hmgr.add("promote me NIFTY", category="signal")
        assert hmgr.tier_sizes()["working"] == 1
        assert hmgr.tier_sizes()["medium"] == 0

        for _ in range(3):
            hmgr.retrieve("promote me NIFTY")

        assert hmgr.tier_sizes()["working"] == 0
        assert hmgr.tier_sizes()["medium"] == 1

    def test_no_promotion_below_threshold(self, hmgr: HierarchicalMemoryManager) -> None:
        entry_id = hmgr.add("stay in working NIFTY", category="signal")

        # Access only 2 times (below threshold of 3)
        hmgr.retrieve("stay in working NIFTY")
        hmgr.retrieve("stay in working NIFTY")

        assert hmgr.get_tier(entry_id) == MemoryTier.WORKING


class TestHierarchicalPrune:
    def test_prune_empty_returns_zero(self, hmgr: HierarchicalMemoryManager) -> None:
        assert hmgr.prune() == 0

    def test_prune_respects_zero_threshold(self, hmgr: HierarchicalMemoryManager) -> None:
        hmgr.add("entry", category="signal")
        removed = hmgr.prune(min_score=0.0)
        assert removed == 0

    def test_prune_removes_stale(self) -> None:
        hmgr = HierarchicalMemoryManager(
            importance_weight=0.0,
            recency_weight=1.0,
            relevance_weight=0.0,
        )
        entry_id = hmgr.add("old stale signal", category="signal", importance=0.1)
        # Backdate the entry so its recency decays below threshold
        entry = hmgr.get_by_id(entry_id)
        assert entry is not None
        entry.timestamp = datetime.now(timezone.utc) - timedelta(hours=500)
        removed = hmgr.prune(min_score=0.05)
        assert removed >= 1


class TestHierarchicalSummariseContext:
    def test_empty_returns_empty_string(self, hmgr: HierarchicalMemoryManager) -> None:
        assert hmgr.summarise_context("NIFTY") == ""

    def test_includes_tier_label(self, hmgr: HierarchicalMemoryManager) -> None:
        hmgr.add("NIFTY broke 22500 CE", category="signal")
        context = hmgr.summarise_context("NIFTY")
        assert "[signal|working]" in context

    def test_starts_with_header(self, hmgr: HierarchicalMemoryManager) -> None:
        hmgr.add("NIFTY data", category="signal")
        context = hmgr.summarise_context("NIFTY")
        assert context.startswith("[Memory Context]")


class TestHierarchicalHelpers:
    def test_get_by_id_across_tiers(self, hmgr: HierarchicalMemoryManager) -> None:
        id1 = hmgr.add("working", category="signal", tier=MemoryTier.WORKING)
        id2 = hmgr.add("medium", category="signal", tier=MemoryTier.MEDIUM)
        id3 = hmgr.add("long", category="signal", tier=MemoryTier.LONG_TERM)
        assert hmgr.get_by_id(id1) is not None
        assert hmgr.get_by_id(id2) is not None
        assert hmgr.get_by_id(id3) is not None

    def test_get_by_id_unknown_returns_none(self, hmgr: HierarchicalMemoryManager) -> None:
        assert hmgr.get_by_id("nonexistent-uuid") is None

    def test_get_by_category_across_tiers(self, hmgr: HierarchicalMemoryManager) -> None:
        hmgr.add("trade 1", category="trade", tier=MemoryTier.WORKING)
        hmgr.add("trade 2", category="trade", tier=MemoryTier.LONG_TERM)
        hmgr.add("signal 1", category="signal")
        trades = hmgr.get_by_category("trade")
        assert len(trades) == 2
        assert all(e.category == "trade" for e in trades)

    def test_clear_removes_all(self, hmgr: HierarchicalMemoryManager) -> None:
        for i in range(5):
            hmgr.add(f"entry {i}", category="signal")
        assert hmgr.size == 5
        hmgr.clear()
        assert hmgr.size == 0
        assert hmgr.tier_sizes() == {"working": 0, "medium": 0, "long_term": 0}

    def test_get_tier_returns_none_for_unknown(self, hmgr: HierarchicalMemoryManager) -> None:
        assert hmgr.get_tier("nonexistent") is None


class TestHierarchicalBackwardCompatibility:
    """Ensure HierarchicalMemoryManager can be used as a drop-in for MemoryManager."""

    def test_add_retrieve_cycle(self, hmgr: HierarchicalMemoryManager) -> None:
        hmgr.add("NIFTY bullish signal", category="signal", importance=0.8)
        results = hmgr.retrieve("NIFTY bullish", top_k=1)
        assert len(results) == 1
        assert "NIFTY" in results[0].content

    def test_summarise_context_works(self, hmgr: HierarchicalMemoryManager) -> None:
        hmgr.add("test entry for context", category="analysis")
        context = hmgr.summarise_context("test entry")
        assert len(context) > 0
