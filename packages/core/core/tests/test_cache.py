"""Tests for packages/core/core/src/cache.py.

Covers: set/get, TTL expiry, LRU eviction, tag invalidation, clear,
        stats, CacheRestoration snapshot/restore, EventBus wiring,
        thread safety.
"""

from __future__ import annotations

import json
import time
import threading
from pathlib import Path

import pytest

from flinttrade_core.cache import Cache, CacheRestoration, wire_to_event_bus
from flinttrade_core.event_bus import EventBus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cache() -> Cache:
    return Cache(max_size=100)


# ---------------------------------------------------------------------------
# Basic set / get
# ---------------------------------------------------------------------------


def test_set_and_get(cache: Cache) -> None:
    """get() returns the value previously set."""
    cache.set("k", 42)
    assert cache.get("k") == 42


def test_get_missing_returns_none(cache: Cache) -> None:
    """get() returns None for an unknown key."""
    assert cache.get("missing") is None


def test_set_overwrites_existing(cache: Cache) -> None:
    """set() on an existing key replaces the value."""
    cache.set("k", 1)
    cache.set("k", 2)
    assert cache.get("k") == 2


def test_set_stores_any_type(cache: Cache) -> None:
    """set() accepts any Python object as value."""
    cache.set("list", [1, 2, 3])
    cache.set("dict", {"a": 1})
    assert cache.get("list") == [1, 2, 3]
    assert cache.get("dict") == {"a": 1}


# ---------------------------------------------------------------------------
# TTL expiry
# ---------------------------------------------------------------------------


def test_get_expired_returns_none(cache: Cache) -> None:
    """get() returns None after the TTL has elapsed."""
    cache.set("exp", "value", ttl_seconds=0)
    # TTL=0 means expire immediately (0 seconds)
    time.sleep(0.01)
    assert cache.get("exp") is None


def test_get_within_ttl_returns_value(cache: Cache) -> None:
    """get() returns the value when TTL has not yet elapsed."""
    cache.set("fresh", "ok", ttl_seconds=60)
    assert cache.get("fresh") == "ok"


def test_none_ttl_never_expires(cache: Cache) -> None:
    """An entry with ttl_seconds=None never expires via TTL."""
    cache.set("immortal", "forever", ttl_seconds=None)
    assert cache.get("immortal") == "forever"


# ---------------------------------------------------------------------------
# LRU eviction
# ---------------------------------------------------------------------------


def test_lru_evicts_oldest_entry() -> None:
    """When max_size is exceeded, the LRU entry is evicted."""
    small = Cache(max_size=3)
    small.set("a", 1)
    small.set("b", 2)
    small.set("c", 3)
    # Access "a" to make it MRU; "b" becomes LRU
    small.get("a")
    # Insert 4th entry — "b" should be evicted
    small.set("d", 4)
    assert small.get("b") is None
    assert small.get("a") == 1
    assert small.get("c") == 3
    assert small.get("d") == 4


def test_lru_evicts_correctly_after_overwrite() -> None:
    """Overwriting a key promotes it to MRU."""
    small = Cache(max_size=2)
    small.set("x", 1)
    small.set("y", 2)
    # Overwrite "x" → "x" becomes MRU
    small.set("x", 99)
    # Insert third entry — "y" should be evicted
    small.set("z", 3)
    assert small.get("y") is None
    assert small.get("x") == 99


# ---------------------------------------------------------------------------
# Explicit invalidation
# ---------------------------------------------------------------------------


def test_invalidate_existing_key(cache: Cache) -> None:
    """invalidate() removes an existing key and returns True."""
    cache.set("del_me", "bye")
    assert cache.invalidate("del_me") is True
    assert cache.get("del_me") is None


def test_invalidate_missing_key(cache: Cache) -> None:
    """invalidate() returns False for an unknown key."""
    assert cache.invalidate("never_set") is False


def test_invalidate_tag_removes_all_matching(cache: Cache) -> None:
    """invalidate_tag() removes all entries sharing the tag."""
    cache.set("a", 1, tags={"grp"})
    cache.set("b", 2, tags={"grp"})
    cache.set("c", 3, tags={"other"})
    count = cache.invalidate_tag("grp")
    assert count == 2
    assert cache.get("a") is None
    assert cache.get("b") is None
    assert cache.get("c") == 3


def test_invalidate_tag_returns_zero_for_unknown(cache: Cache) -> None:
    """invalidate_tag() returns 0 when no entries carry the tag."""
    assert cache.invalidate_tag("no_such_tag") == 0


def test_clear_removes_all_entries(cache: Cache) -> None:
    """clear() removes all entries."""
    cache.set("p", 1)
    cache.set("q", 2)
    cache.clear()
    assert cache.get("p") is None
    assert cache.get("q") is None
    assert cache.stats()["entries"] == 0


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def test_stats_tracks_hits_and_misses(cache: Cache) -> None:
    """stats() returns accurate hit/miss counts."""
    cache.set("s", 1)
    cache.get("s")    # hit
    cache.get("s")    # hit
    cache.get("nope") # miss
    s = cache.stats()
    assert s["hits"] == 2
    assert s["misses"] == 1


def test_stats_hit_rate_calculation(cache: Cache) -> None:
    """stats() hit_rate is hits / (hits + misses)."""
    cache.set("v", 99)
    for _ in range(3):
        cache.get("v")   # 3 hits
    cache.get("x")       # 1 miss
    s = cache.stats()
    assert abs(s["hit_rate"] - 0.75) < 0.01


def test_stats_entries_count(cache: Cache) -> None:
    """stats() entries reflects live count."""
    for i in range(5):
        cache.set(f"k{i}", i)
    assert cache.stats()["entries"] == 5


def test_stats_zero_total_no_divide_by_zero(cache: Cache) -> None:
    """stats() does not raise when no requests have been made."""
    s = cache.stats()
    assert s["hit_rate"] == 0.0


# ---------------------------------------------------------------------------
# CacheRestoration
# ---------------------------------------------------------------------------


def test_snapshot_and_restore(tmp_path: Path) -> None:
    """snapshot() + restore() round-trips non-expired entries."""
    c1 = Cache()
    c1.set("alpha", {"x": 1}, ttl_seconds=3600, tags={"grp"})
    c1.set("beta", [1, 2, 3])

    snap = tmp_path / "snap.jsonl"
    restoration = CacheRestoration()
    restoration.snapshot(c1, snap)

    c2 = Cache()
    count = restoration.restore(c2, snap)
    assert count == 2
    assert c2.get("alpha") == {"x": 1}
    assert c2.get("beta") == [1, 2, 3]


def test_restore_skips_expired_entries(tmp_path: Path) -> None:
    """restore() does not load entries that have already expired."""
    snap = tmp_path / "snap.jsonl"
    # Write a manually-constructed expired entry
    row = {
        "key": "old",
        "value": "stale",
        "created_at": 0.0,  # Unix epoch → definitely expired
        "ttl_seconds": 1,
        "tags": [],
    }
    snap.write_text(json.dumps(row) + "\n", encoding="utf-8")

    c = Cache()
    count = CacheRestoration().restore(c, snap)
    assert count == 0
    assert c.get("old") is None


def test_restore_missing_file(tmp_path: Path) -> None:
    """restore() returns 0 when the snapshot file does not exist."""
    c = Cache()
    count = CacheRestoration().restore(c, tmp_path / "none.jsonl")
    assert count == 0


def test_snapshot_skips_non_serialisable(tmp_path: Path) -> None:
    """snapshot() skips entries whose values cannot be JSON-serialised."""
    c = Cache()
    c.set("ok", "good")
    c.set("bad", object())  # not JSON-serialisable

    snap = tmp_path / "snap.jsonl"
    CacheRestoration().snapshot(c, snap)

    c2 = Cache()
    count = CacheRestoration().restore(c2, snap)
    assert count == 1
    assert c2.get("ok") == "good"


# ---------------------------------------------------------------------------
# EventBus wiring
# ---------------------------------------------------------------------------


def test_wire_market_open_invalidates_tag(cache: Cache) -> None:
    """market.open event invalidates entries tagged 'market_open'."""
    bus = EventBus()
    wire_to_event_bus(cache, bus)
    cache.set("intraday", "data", tags={"market_open"})
    bus.publish("market.open", {})
    assert cache.get("intraday") is None


def test_wire_market_close_invalidates_tag(cache: Cache) -> None:
    """market.close event invalidates entries tagged 'market_close'."""
    bus = EventBus()
    wire_to_event_bus(cache, bus)
    cache.set("eod", "data", tags={"market_close"})
    bus.publish("market.close", {})
    assert cache.get("eod") is None


def test_wire_expiry_change_invalidates_tag(cache: Cache) -> None:
    """expiry.change event invalidates entries tagged 'expiry_change'."""
    bus = EventBus()
    wire_to_event_bus(cache, bus)
    cache.set("oi_chain", "data", tags={"expiry_change"})
    bus.publish("expiry.change", {})
    assert cache.get("oi_chain") is None


def test_wire_does_not_affect_untagged(cache: Cache) -> None:
    """EventBus events do not remove entries without the matching tag."""
    bus = EventBus()
    wire_to_event_bus(cache, bus)
    cache.set("permanent", "stays", tags={"other_tag"})
    bus.publish("market.open", {})
    assert cache.get("permanent") == "stays"


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


def test_concurrent_set_get_is_safe() -> None:
    """Concurrent set/get from multiple threads does not raise."""
    c = Cache(max_size=200)
    errors: list[Exception] = []

    def _worker(idx: int) -> None:
        try:
            for i in range(20):
                c.set(f"k{idx}_{i}", i, ttl_seconds=10)
                c.get(f"k{idx}_{i}")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(t,)) for t in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Thread errors: {errors}"
