"""Unified in-memory LRU cache with tag-based invalidation for FlintTrade.

The :class:`Cache` stores arbitrary Python values under string keys.  Each
entry may carry:

* an optional TTL (entries expire after *ttl_seconds* seconds),
* a set of *tags* used for group invalidation (e.g. all entries tagged
  ``"market_open"`` are dropped when the market opens).

The cache is backed by an :class:`collections.OrderedDict`-based LRU so that
the least-recently-used entry is evicted first when ``max_size`` is reached.

:class:`CacheRestoration` can persist a snapshot of non-expired entries to
disk (JSON via DuckDB-compatible path) and restore them across restarts.

EventBus wiring
---------------
Call :func:`wire_to_event_bus` to automatically invalidate tags when market
lifecycle events fire::

    from packages.core.src.cache import Cache, wire_to_event_bus
    from packages.core.src.event_bus import bus

    cache = Cache()
    wire_to_event_bus(cache, bus)

This wires ``market.open`` → invalidate tag ``"market_open"``,
``market.close`` → ``"market_close"``, ``expiry.change`` → ``"expiry_change"``.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.core.cache")


# ---------------------------------------------------------------------------
# CacheEntry
# ---------------------------------------------------------------------------


@dataclass
class CacheEntry:
    """A single cached value with optional TTL and grouping tags.

    Args:
        key: Cache key string.
        value: Arbitrary Python value to store.
        created_at: Unix timestamp (seconds) when the entry was created.
        ttl_seconds: Time-to-live in seconds.  ``None`` means the entry never
            expires via TTL (it can still be evicted by the LRU limit or
            invalidated explicitly).
        tags: Set of string tags.  Any entry sharing a tag with a
            :meth:`Cache.invalidate_tag` call is removed.
    """

    key: str
    value: Any
    created_at: float
    ttl_seconds: int | None
    tags: set[str] = field(default_factory=set)

    def is_expired(self) -> bool:
        """Return True when the TTL has elapsed."""
        if self.ttl_seconds is None:
            return False
        return (time.time() - self.created_at) > self.ttl_seconds


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class Cache:
    """In-memory LRU cache with tag-based invalidation.

    The cache is fully thread-safe.  All public methods acquire an internal
    :class:`threading.Lock` before touching shared state.

    The LRU eviction policy removes the entry that was accessed (via
    :meth:`get`) or inserted (via :meth:`set`) least recently when the
    number of entries would exceed *max_size*.

    Args:
        max_size: Maximum number of live entries (default 1000).

    Example::

        cache = Cache(max_size=500)
        cache.set("oi:NIFTY", data, ttl_seconds=60, tags={"expiry_change"})
        value = cache.get("oi:NIFTY")  # None after 60s or tag invalidation
        cache.invalidate_tag("expiry_change")  # drops all tagged entries
    """

    def __init__(self, max_size: int = 1000) -> None:
        self._max_size = max(1, max_size)
        # OrderedDict preserves insertion/access order for LRU
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        # Inverted index: tag -> set of keys
        self._tag_index: dict[str, set[str]] = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
        tags: set[str] | None = None,
    ) -> None:
        """Store *value* under *key*.

        If an entry already exists for *key* it is overwritten.  The new
        entry is moved to the *most-recently-used* position.  If the cache
        is full the *least-recently-used* entry is evicted first.

        Args:
            key: String cache key.
            value: Value to store.
            ttl_seconds: Expiry duration in seconds.  ``None`` → no expiry.
            tags: Optional set of string tags for group invalidation.
        """
        effective_tags: set[str] = tags or set()
        entry = CacheEntry(
            key=key,
            value=value,
            created_at=time.time(),
            ttl_seconds=ttl_seconds,
            tags=effective_tags,
        )
        with self._lock:
            # Remove existing entry (and its tag registrations) if present
            if key in self._store:
                self._deregister_tags(key, self._store[key].tags)
                del self._store[key]

            # Evict LRU if at capacity
            while len(self._store) >= self._max_size:
                evicted_key, _ = self._store.popitem(last=False)
                self._deregister_tags(evicted_key, self._store.get(evicted_key, CacheEntry(evicted_key, None, 0, None)).tags)
                logger.debug("Cache: LRU eviction of key '%s'", evicted_key)

            self._store[key] = entry
            self._register_tags(key, effective_tags)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, key: str) -> Any | None:
        """Retrieve the value stored under *key*.

        Returns ``None`` on a cache miss OR when the entry has expired.
        Expired entries are lazily removed on access.

        Args:
            key: String cache key.

        Returns:
            Stored value or ``None``.
        """
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None

            if entry.is_expired():
                self._remove_entry(key)
                self._misses += 1
                logger.debug("Cache: TTL expired for key '%s'", key)
                return None

            # Move to MRU position
            self._store.move_to_end(key)
            self._hits += 1
            return entry.value

    # ------------------------------------------------------------------
    # Invalidation
    # ------------------------------------------------------------------

    def invalidate(self, key: str) -> bool:
        """Remove a single entry by key.

        Args:
            key: Cache key to remove.

        Returns:
            ``True`` if the key existed and was removed, ``False`` otherwise.
        """
        with self._lock:
            if key not in self._store:
                return False
            self._remove_entry(key)
            logger.debug("Cache: invalidated key '%s'", key)
            return True

    def invalidate_tag(self, tag: str) -> int:
        """Remove all entries that carry *tag*.

        Args:
            tag: Tag string to invalidate.

        Returns:
            Number of entries removed.
        """
        with self._lock:
            keys = list(self._tag_index.get(tag, set()))
            for key in keys:
                if key in self._store:
                    self._remove_entry(key)
            count = len(keys)
            if count:
                logger.info("Cache: invalidated %d entries for tag '%s'", count, tag)
            return count

    def clear(self) -> None:
        """Remove all entries and reset statistics."""
        with self._lock:
            self._store.clear()
            self._tag_index.clear()
            self._hits = 0
            self._misses = 0
            logger.debug("Cache: cleared all entries")

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Return cache performance and memory statistics.

        Returns:
            Dict with keys: ``hits``, ``misses``, ``hit_rate`` (0.0–1.0),
            ``entries`` (live count), ``memory_estimate_kb`` (rough estimate
            based on entry count × average overhead).
        """
        with self._lock:
            entries = len(self._store)
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0.0
            # Rough estimate: ~512 bytes per entry (key str + entry overhead)
            memory_kb = round(entries * 512 / 1024, 2)
            return {
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(hit_rate, 4),
                "entries": entries,
                "memory_estimate_kb": memory_kb,
            }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _remove_entry(self, key: str) -> None:
        """Remove entry by key; must be called with lock held."""
        entry = self._store.pop(key, None)
        if entry is not None:
            self._deregister_tags(key, entry.tags)

    def _register_tags(self, key: str, tags: set[str]) -> None:
        """Add *key* to each tag's index set; must be called with lock held."""
        for tag in tags:
            if tag not in self._tag_index:
                self._tag_index[tag] = set()
            self._tag_index[tag].add(key)

    def _deregister_tags(self, key: str, tags: set[str]) -> None:
        """Remove *key* from each tag's index set; must be called with lock held."""
        for tag in tags:
            bucket = self._tag_index.get(tag)
            if bucket is not None:
                bucket.discard(key)
                if not bucket:
                    del self._tag_index[tag]


# ---------------------------------------------------------------------------
# CacheRestoration
# ---------------------------------------------------------------------------


class CacheRestoration:
    """Snapshot and restore non-expired cache entries across restarts.

    Entries are serialised to newline-delimited JSON so they can be written
    to any file path (suitable for ``~/.flinttrade/`` data directories).
    Values must be JSON-serialisable; non-serialisable entries are skipped
    with a warning.

    Example::

        restoration = CacheRestoration()
        restoration.snapshot(cache, Path("/tmp/cache.jsonl"))
        count = restoration.restore(cache, Path("/tmp/cache.jsonl"))
    """

    def snapshot(self, cache: Cache, path: Path) -> None:
        """Write all non-expired entries to *path* as NDJSON.

        Args:
            cache: The :class:`Cache` instance to snapshot.
            path: Output file path.  Parent directories are created if
                needed.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        skipped = 0

        with cache._lock:  # noqa: SLF001
            entries = list(cache._store.values())  # noqa: SLF001

        with path.open("w", encoding="utf-8") as fh:
            for entry in entries:
                if entry.is_expired():
                    continue
                try:
                    row = {
                        "key": entry.key,
                        "value": entry.value,
                        "created_at": entry.created_at,
                        "ttl_seconds": entry.ttl_seconds,
                        "tags": list(entry.tags),
                    }
                    fh.write(json.dumps(row) + "\n")
                    written += 1
                except (TypeError, ValueError):
                    skipped += 1
                    logger.debug("CacheRestoration: skipping non-serialisable key '%s'", entry.key)

        logger.info(
            "CacheRestoration: snapshot written to %s (%d entries, %d skipped)",
            path,
            written,
            skipped,
        )

    def restore(self, cache: Cache, path: Path) -> int:
        """Load entries from *path* into *cache*, skipping expired ones.

        Args:
            cache: Destination :class:`Cache` instance.
            path: NDJSON file produced by :meth:`snapshot`.

        Returns:
            Number of entries successfully restored.
        """
        if not path.exists():
            logger.debug("CacheRestoration: no snapshot at %s", path)
            return 0

        restored = 0
        with path.open("r", encoding="utf-8") as fh:
            for line_no, raw in enumerate(fh, 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                    entry = CacheEntry(
                        key=row["key"],
                        value=row["value"],
                        created_at=float(row["created_at"]),
                        ttl_seconds=row.get("ttl_seconds"),
                        tags=set(row.get("tags", [])),
                    )
                    if entry.is_expired():
                        continue
                    cache.set(
                        entry.key,
                        entry.value,
                        ttl_seconds=entry.ttl_seconds,
                        tags=entry.tags,
                    )
                    restored += 1
                except (KeyError, ValueError, json.JSONDecodeError):
                    logger.warning(
                        "CacheRestoration: malformed line %d in %s, skipping",
                        line_no,
                        path,
                    )

        logger.info("CacheRestoration: restored %d entries from %s", restored, path)
        return restored


# ---------------------------------------------------------------------------
# EventBus wiring
# ---------------------------------------------------------------------------


def wire_to_event_bus(cache: Cache, event_bus: Any) -> None:
    """Subscribe *cache* to market lifecycle events on *event_bus*.

    Wiring table:

    ====================== ===================
    EventBus event         Tag invalidated
    ====================== ===================
    ``market.open``        ``"market_open"``
    ``market.close``       ``"market_close"``
    ``expiry.change``      ``"expiry_change"``
    ====================== ===================

    Args:
        cache: :class:`Cache` instance to wire.
        event_bus: :class:`~packages.core.src.event_bus.EventBus` instance.
    """

    def _on_market_open(_payload: dict) -> None:
        n = cache.invalidate_tag("market_open")
        logger.info("Cache: market.open → invalidated %d 'market_open' entries", n)

    def _on_market_close(_payload: dict) -> None:
        n = cache.invalidate_tag("market_close")
        logger.info("Cache: market.close → invalidated %d 'market_close' entries", n)

    def _on_expiry_change(_payload: dict) -> None:
        n = cache.invalidate_tag("expiry_change")
        logger.info("Cache: expiry.change → invalidated %d 'expiry_change' entries", n)

    event_bus.subscribe("market.open", _on_market_open)
    event_bus.subscribe("market.close", _on_market_close)
    event_bus.subscribe("expiry.change", _on_expiry_change)
    logger.debug("Cache: wired to EventBus for market lifecycle events")
