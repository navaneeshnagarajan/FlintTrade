"""DuckDB-backed OHLCV cache with TTL, incremental updates, and batch fetch.

Adapted patterns from:
- historify DataPipeline: staging-table merge, batch processing, no per-row SELECT
- pipeline.py: _validate_table allowlist, _default_db_path, staging anti-join pattern

The cache is a logical layer on top of the existing DataPipeline. It adds:
    - Cache-key awareness: (symbol, exchange, interval, date range)
    - TTL-based invalidation: re-fetch if the cached head is older than ttl_seconds
    - Incremental updates: only fetch bars newer than the last cached bar
    - Async batch fetch: request multiple (symbol, exchange) pairs concurrently,
      delegating to any DataProvider via the ProviderRegistry

Schema:
    Reuses the OHLCV tables from pipeline.py (ohlcv_1m … ohlcv_1d).
    Adds a ``_cache_meta`` table to track per-(symbol, exchange, interval) metadata:
        - last_fetch_ts: when we last went to a provider for this series
        - head_bar_ts: timestamp of the most recent bar currently stored
        - provider: which provider populated this entry
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

from .pipeline import (
    DataPipeline,
    INTERVAL_TABLES,
    _default_db_path,
    _validate_table,
)

logger = logging.getLogger("flinttrade.historical.cache")

# Default TTL: 1 hour for intraday, 24 hours for daily/weekly
_DEFAULT_TTL_INTRADAY = 3600
_DEFAULT_TTL_DAILY = 86400

_INTRADAY_INTERVALS: frozenset[str] = frozenset(
    {"1m", "2m", "3m", "5m", "10m", "15m", "30m", "1h"}
)

_CACHE_META_DDL = """
CREATE TABLE IF NOT EXISTS _cache_meta (
    symbol      VARCHAR NOT NULL,
    exchange    VARCHAR NOT NULL,
    interval    VARCHAR NOT NULL,
    last_fetch  TIMESTAMP,
    head_bar_ts TIMESTAMP,
    provider    VARCHAR DEFAULT '',
    PRIMARY KEY (symbol, exchange, interval)
);
"""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CacheEntry:
    """Metadata for a single cached series.

    Attributes:
        symbol: Trading symbol.
        exchange: Exchange code.
        interval: Canonical interval string.
        last_fetch: UTC datetime when the provider was last queried.
        head_bar_ts: Timestamp of the newest bar in the cache.
        provider: Name of the provider that populated this entry.
    """

    symbol: str
    exchange: str
    interval: str
    last_fetch: datetime | None = None
    head_bar_ts: datetime | None = None
    provider: str = ""


@dataclass
class CacheResult:
    """Result from a cache fetch operation.

    Attributes:
        symbol: Trading symbol.
        exchange: Exchange code.
        interval: Canonical interval string.
        bars: Normalised bar dicts sorted oldest-first.
        from_cache: True when all bars came from the local cache.
        new_bars: Number of bars fetched from a provider and written to cache.
        error: Non-empty if the operation failed.
    """

    symbol: str
    exchange: str
    interval: str
    bars: list[dict[str, Any]] = field(default_factory=list)
    from_cache: bool = False
    new_bars: int = 0
    error: str = ""

    @property
    def total_bars(self) -> int:
        """Total bars returned."""
        return len(self.bars)

    @property
    def success(self) -> bool:
        """True when bars were returned without a fatal error."""
        return self.total_bars > 0 and not self.error


# ---------------------------------------------------------------------------
# OHLCVCache
# ---------------------------------------------------------------------------


class OHLCVCache:
    """DuckDB-backed OHLCV cache for historical data.

    The cache wraps a DataPipeline and a ProviderRegistry. When data is
    requested:
    1. Look up the ``_cache_meta`` table to check the last fetch time.
    2. If the cache is fresh (within TTL), return cached bars directly.
    3. If stale or missing, query the provider for the missing range only
       (incremental update from ``head_bar_ts``).
    4. Merge new bars into the pipeline, update meta, return all bars.

    Usage::

        from .data_provider import ProviderRegistry
        from .cache import OHLCVCache

        registry = ProviderRegistry(openalgo_client)
        cache = OHLCVCache(registry=registry)
        cache.initialise()

        result = cache.get("RELIANCE", "NSE", "5m", "2026-01-01", "2026-03-31")
        print(f"{result.total_bars} bars ({result.new_bars} new)")

        # Batch fetch
        results = cache.get_batch(
            [{"symbol": "RELIANCE", "exchange": "NSE"},
             {"symbol": "TCS", "exchange": "NSE"}],
            interval="5m",
            start_date="2026-01-01",
            end_date="2026-03-31",
        )

    Args:
        registry: ProviderRegistry instance. May be None for read-only cache use.
        db_path: DuckDB file path. Defaults to the workspace DuckDB path.
        ttl_intraday: Seconds before intraday cached data is considered stale.
        ttl_daily: Seconds before daily/weekly cached data is considered stale.
    """

    def __init__(
        self,
        registry: Any | None = None,
        db_path: str | None = None,
        ttl_intraday: int = _DEFAULT_TTL_INTRADAY,
        ttl_daily: int = _DEFAULT_TTL_DAILY,
    ) -> None:
        self._registry = registry
        self._db_path = db_path or _default_db_path()
        self._ttl_intraday = ttl_intraday
        self._ttl_daily = ttl_daily
        self._pipeline: DataPipeline | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def pipeline(self) -> DataPipeline:
        """Lazy-initialised DataPipeline."""
        if self._pipeline is None:
            self._pipeline = DataPipeline(self._db_path)
        return self._pipeline

    def initialise(self) -> None:
        """Create OHLCV tables, indexes, and the _cache_meta table."""
        self.pipeline.initialise()
        self.pipeline.connection.execute(_CACHE_META_DDL)
        logger.info("OHLCV cache schema initialised at %s", self._db_path)

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        if self._pipeline is not None:
            self._pipeline.close()
            self._pipeline = None

    def __enter__(self) -> OHLCVCache:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # TTL helpers
    # ------------------------------------------------------------------

    def _ttl_for(self, interval: str) -> int:
        """Return the TTL in seconds for the given interval.

        Args:
            interval: Canonical interval string.

        Returns:
            TTL in seconds.
        """
        return self._ttl_intraday if interval in _INTRADAY_INTERVALS else self._ttl_daily

    def _is_fresh(self, entry: CacheEntry, interval: str) -> bool:
        """Check if a cache entry is within its TTL.

        Args:
            entry: The cache metadata entry.
            interval: Canonical interval string.

        Returns:
            True if last_fetch is within the TTL window.
        """
        if entry.last_fetch is None:
            return False
        ttl = self._ttl_for(interval)
        age = (datetime.now(tz=timezone.utc) - entry.last_fetch).total_seconds()
        return age < ttl

    # ------------------------------------------------------------------
    # Meta table operations
    # ------------------------------------------------------------------

    def get_entry(self, symbol: str, exchange: str, interval: str) -> CacheEntry | None:
        """Read cache metadata for a series.

        Args:
            symbol: Trading symbol.
            exchange: Exchange code.
            interval: Canonical interval string.

        Returns:
            CacheEntry if found, else None.
        """
        row = self.pipeline.connection.execute(
            "SELECT symbol, exchange, interval, last_fetch, head_bar_ts, provider "
            "FROM _cache_meta WHERE symbol = ? AND exchange = ? AND interval = ?",
            [symbol, exchange, interval],
        ).fetchone()
        if row is None:
            return None
        last_fetch = row[3]
        head_bar_ts = row[4]
        # DuckDB returns timestamps as datetime objects
        if isinstance(last_fetch, str):
            last_fetch = datetime.fromisoformat(last_fetch).replace(tzinfo=timezone.utc)
        elif isinstance(last_fetch, datetime) and last_fetch.tzinfo is None:
            last_fetch = last_fetch.replace(tzinfo=timezone.utc)

        if isinstance(head_bar_ts, str):
            head_bar_ts = datetime.fromisoformat(head_bar_ts)
        return CacheEntry(
            symbol=row[0], exchange=row[1], interval=row[2],
            last_fetch=last_fetch, head_bar_ts=head_bar_ts,
            provider=row[5] or "",
        )

    def _upsert_entry(
        self,
        symbol: str,
        exchange: str,
        interval: str,
        head_bar_ts: datetime | None = None,
        provider: str = "",
    ) -> None:
        """Create or update a _cache_meta entry.

        Args:
            symbol: Trading symbol.
            exchange: Exchange code.
            interval: Canonical interval string.
            head_bar_ts: Timestamp of the newest cached bar.
            provider: Provider name that supplied the data.
        """
        now_utc = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        head_ts = head_bar_ts.replace(tzinfo=None) if head_bar_ts else None

        existing = self.get_entry(symbol, exchange, interval)
        if existing is None:
            self.pipeline.connection.execute(
                "INSERT INTO _cache_meta (symbol, exchange, interval, last_fetch, head_bar_ts, provider) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [symbol, exchange, interval, now_utc, head_ts, provider],
            )
        else:
            self.pipeline.connection.execute(
                "UPDATE _cache_meta SET last_fetch = ?, head_bar_ts = ?, provider = ? "
                "WHERE symbol = ? AND exchange = ? AND interval = ?",
                [now_utc, head_ts, provider, symbol, exchange, interval],
            )

    def _get_head_bar_ts(self, table: str, symbol: str, exchange: str) -> datetime | None:
        """Find the timestamp of the newest bar in the OHLCV table.

        Args:
            table: Validated OHLCV table name.
            symbol: Trading symbol.
            exchange: Exchange code.

        Returns:
            Datetime of the newest bar, or None if the table is empty.
        """
        table = _validate_table(table)
        row = self.pipeline.connection.execute(
            f"SELECT MAX(timestamp) FROM {table} WHERE symbol = ? AND exchange = ?",
            [symbol, exchange],
        ).fetchone()
        if row and row[0] is not None:
            ts = row[0]
            if isinstance(ts, str):
                return datetime.fromisoformat(ts)
            return ts
        return None

    # ------------------------------------------------------------------
    # Cache invalidation
    # ------------------------------------------------------------------

    def invalidate(self, symbol: str, exchange: str, interval: str) -> None:
        """Force a re-fetch on the next get() call by clearing last_fetch.

        Args:
            symbol: Trading symbol.
            exchange: Exchange code.
            interval: Canonical interval string.
        """
        self.pipeline.connection.execute(
            "UPDATE _cache_meta SET last_fetch = NULL "
            "WHERE symbol = ? AND exchange = ? AND interval = ?",
            [symbol, exchange, interval],
        )
        logger.info("Invalidated cache for %s %s %s", symbol, exchange, interval)

    def invalidate_all(self) -> None:
        """Invalidate all entries — next get() calls will re-fetch everything."""
        self.pipeline.connection.execute("UPDATE _cache_meta SET last_fetch = NULL")
        logger.info("All cache entries invalidated")

    # ------------------------------------------------------------------
    # Fetch (with incremental update)
    # ------------------------------------------------------------------

    def get(
        self,
        symbol: str,
        exchange: str,
        interval: str,
        start_date: str,
        end_date: str,
        *,
        force_refresh: bool = False,
    ) -> CacheResult:
        """Return OHLCV bars for a symbol, fetching from a provider if needed.

        Steps:
            1. Check _cache_meta for last_fetch and head_bar_ts.
            2. If fresh and not force_refresh, return cached bars.
            3. Otherwise fetch the missing range from the provider.
            4. Merge new bars into the OHLCV table.
            5. Update _cache_meta.
            6. Return all bars within [start_date, end_date].

        Args:
            symbol: Trading symbol.
            exchange: Exchange code.
            interval: Data interval (canonical or user-friendly).
            start_date: Requested start date "YYYY-MM-DD".
            end_date: Requested end date "YYYY-MM-DD".
            force_refresh: Bypass TTL and always re-fetch.

        Returns:
            CacheResult with bars from the cache (and any new bars merged in).
        """
        from .data_provider import normalise_interval

        try:
            canonical = normalise_interval(interval)
        except ValueError as exc:
            return CacheResult(symbol=symbol, exchange=exchange, interval=interval, error=str(exc))

        table = INTERVAL_TABLES.get(canonical) or INTERVAL_TABLES.get(interval)
        if not table:
            # Unsupported interval — pass straight to provider without caching
            return self._provider_only(symbol, exchange, canonical, start_date, end_date)

        result = CacheResult(symbol=symbol, exchange=exchange, interval=canonical)

        entry = self.get_entry(symbol, exchange, canonical)
        cache_is_fresh = not force_refresh and entry is not None and self._is_fresh(entry, canonical)

        if not cache_is_fresh and self._registry is not None:
            # Incremental: only request bars newer than what we have
            fetch_start = start_date
            if entry is not None and entry.head_bar_ts is not None:
                # Start one second after the last cached bar to avoid duplicates
                incremental_start = entry.head_bar_ts + timedelta(seconds=1)
                # But only if the incremental start is within the requested range
                if incremental_start.date().isoformat() <= end_date:
                    fetch_start = incremental_start.date().isoformat()

            logger.info(
                "Cache miss/stale for %s %s %s — fetching %s → %s",
                symbol, exchange, canonical, fetch_start, end_date,
            )

            provider_result = self._registry.fetch(
                symbol, exchange, interval, fetch_start, end_date,
            )

            if provider_result.success:
                # Normalise and store
                from .normaliser import OHLCVNormaliser

                norm = OHLCVNormaliser()
                norm_result = norm.normalise(
                    [
                        {
                            "timestamp": b.timestamp,
                            "open": b.open, "high": b.high,
                            "low": b.low, "close": b.close,
                            "volume": b.volume, "oi": b.oi,
                        }
                        for b in provider_result.bars
                    ],
                    symbol=symbol,
                    exchange=exchange,
                    interval=canonical,
                )

                if norm_result.bars:
                    raw_bars = [
                        {
                            "timestamp": b.timestamp,
                            "open": b.open, "high": b.high,
                            "low": b.low, "close": b.close,
                            "volume": b.volume, "oi": b.oi,
                        }
                        for b in norm_result.bars
                    ]
                    result.new_bars = self.pipeline.store_bars(
                        table, symbol, exchange, raw_bars,
                    )

                if norm_result.warnings:
                    for w in norm_result.warnings:
                        logger.debug("Normaliser warning: %s", w)

            elif not cache_is_fresh and provider_result.error:
                logger.warning(
                    "Provider error for %s %s %s: %s",
                    symbol, exchange, canonical, provider_result.error,
                )

            # Update meta regardless — record the attempt
            new_head = self._get_head_bar_ts(table, symbol, exchange)
            self._upsert_entry(
                symbol, exchange, canonical,
                head_bar_ts=new_head,
                provider=provider_result.provider,
            )

        # Read from cache
        cached_bars = self.pipeline.get_bars(table, symbol, exchange, start_date, end_date)
        result.bars = cached_bars
        result.from_cache = result.new_bars == 0

        logger.info(
            "Cache get: %s %s %s → %d bars (%d new)",
            symbol, exchange, canonical, result.total_bars, result.new_bars,
        )
        return result

    def _provider_only(
        self,
        symbol: str,
        exchange: str,
        interval: str,
        start_date: str,
        end_date: str,
    ) -> CacheResult:
        """Fetch directly from the provider without caching (unsupported interval).

        Args:
            symbol: Trading symbol.
            exchange: Exchange code.
            interval: Canonical interval string.
            start_date: Start date "YYYY-MM-DD".
            end_date: End date "YYYY-MM-DD".

        Returns:
            CacheResult with provider bars, not stored to DB.
        """
        result = CacheResult(symbol=symbol, exchange=exchange, interval=interval)
        if self._registry is None:
            result.error = "No registry available and interval is not cacheable"
            return result

        provider_result = self._registry.fetch(symbol, exchange, interval, start_date, end_date)
        if provider_result.success:
            result.bars = [
                {
                    "timestamp": b.timestamp,
                    "open": b.open, "high": b.high,
                    "low": b.low, "close": b.close,
                    "volume": b.volume, "oi": b.oi,
                    "symbol": symbol, "exchange": exchange,
                }
                for b in provider_result.bars
            ]
        else:
            result.error = provider_result.error
        return result

    # ------------------------------------------------------------------
    # Batch fetch (sequential — rate-limit-safe)
    # ------------------------------------------------------------------

    def get_batch(
        self,
        requests: list[dict[str, str]],
        interval: str,
        start_date: str,
        end_date: str,
        *,
        force_refresh: bool = False,
    ) -> list[CacheResult]:
        """Fetch multiple symbols, reusing the same cache and provider registry.

        Requests are processed sequentially to respect broker rate limits
        (adapted from historify batch_process / BATCH_SIZE = 10 pattern).
        Each request is a dict with "symbol" and "exchange".

        Args:
            requests: List of dicts with "symbol" and "exchange" keys.
            interval: Data interval applied to all symbols.
            start_date: Start date "YYYY-MM-DD".
            end_date: End date "YYYY-MM-DD".
            force_refresh: Bypass TTL for all symbols.

        Returns:
            List of CacheResult in the same order as ``requests``.
        """
        results: list[CacheResult] = []
        for req in requests:
            sym = req["symbol"]
            exch = req.get("exchange", "NSE")
            res = self.get(sym, exch, interval, start_date, end_date, force_refresh=force_refresh)
            results.append(res)
            logger.debug(
                "Batch fetch: %s %s → %d bars (%d new)",
                sym, exch, res.total_bars, res.new_bars,
            )
        return results

    # ------------------------------------------------------------------
    # Statistics / inspection
    # ------------------------------------------------------------------

    def list_entries(self) -> list[CacheEntry]:
        """Return all entries in _cache_meta.

        Returns:
            List of CacheEntry objects, one per cached series.
        """
        rows = self.pipeline.connection.execute(
            "SELECT symbol, exchange, interval, last_fetch, head_bar_ts, provider "
            "FROM _cache_meta ORDER BY symbol, exchange, interval"
        ).fetchall()
        entries: list[CacheEntry] = []
        for row in rows:
            last_fetch = row[3]
            if isinstance(last_fetch, datetime) and last_fetch.tzinfo is None:
                last_fetch = last_fetch.replace(tzinfo=timezone.utc)
            elif isinstance(last_fetch, str):
                last_fetch = datetime.fromisoformat(last_fetch).replace(tzinfo=timezone.utc)
            entries.append(
                CacheEntry(
                    symbol=row[0], exchange=row[1], interval=row[2],
                    last_fetch=last_fetch, head_bar_ts=row[4],
                    provider=row[5] or "",
                )
            )
        return entries

    def bar_counts(self) -> dict[str, int]:
        """Return bar count per OHLCV table.

        Returns:
            Dict mapping table name to total row count.
        """
        counts: dict[str, int] = {}
        for table in set(INTERVAL_TABLES.values()):
            row = self.pipeline.connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()
            counts[table] = row[0] if row else 0
        return counts
