"""Tests for packages/core/historical/src/cache.py.

All tests use in-memory DuckDB and mock providers — no network or disk I/O.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cache(registry=None, ttl_intraday=3600, ttl_daily=86400):
    """Create an OHLCVCache backed by an in-memory DuckDB."""
    from flinttrade_historical.cache import OHLCVCache
    cache = OHLCVCache(
        registry=registry,
        db_path=":memory:",
        ttl_intraday=ttl_intraday,
        ttl_daily=ttl_daily,
    )
    cache.initialise()
    return cache


def _make_registry_with_bars(bars: list[dict] | None = None, error: str = ""):
    """Return a mock ProviderRegistry that returns the given bars."""
    from flinttrade_historical.data_provider import ProviderBar, ProviderResult

    mock_registry = MagicMock()
    provider_bars = [
        ProviderBar(
            timestamp=b["timestamp"],
            open=b.get("open", 100),
            high=b.get("high", 101),
            low=b.get("low", 99),
            close=b.get("close", 100.5),
            volume=b.get("volume", 1000),
            oi=b.get("oi", 0),
        )
        for b in (bars or [])
    ]
    result = ProviderResult(
        symbol="RELIANCE", exchange="NSE", interval="5m",
        provider="mock",
        bars=provider_bars,
        error=error,
    )
    mock_registry.fetch.return_value = result
    return mock_registry


# ---------------------------------------------------------------------------
# OHLCVCache lifecycle
# ---------------------------------------------------------------------------


class TestOHLCVCacheLifecycle:
    """Test initialise, close, context manager."""

    def test_initialise_creates_ohlcv_tables(self):
        cache = _make_cache()
        tables = {
            row[0]
            for row in cache.pipeline.connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        assert "ohlcv_1m" in tables
        assert "ohlcv_5m" in tables
        assert "ohlcv_1d" in tables
        cache.close()

    def test_initialise_creates_cache_meta_table(self):
        cache = _make_cache()
        tables = {
            row[0]
            for row in cache.pipeline.connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        assert "_cache_meta" in tables
        cache.close()

    def test_context_manager(self):
        from flinttrade_historical.cache import OHLCVCache
        with OHLCVCache(db_path=":memory:") as cache:
            cache.initialise()
            assert cache.pipeline is not None


# ---------------------------------------------------------------------------
# CacheEntry / meta operations
# ---------------------------------------------------------------------------


class TestCacheEntry:
    """Test _cache_meta read/write operations."""

    def test_get_entry_returns_none_when_missing(self):
        cache = _make_cache()
        entry = cache.get_entry("RELIANCE", "NSE", "5m")
        assert entry is None
        cache.close()

    def test_upsert_then_get_entry(self):
        cache = _make_cache()
        datetime(2026, 3, 16, 9, 15, 0, tzinfo=timezone.utc)
        head = datetime(2026, 3, 16, 15, 29, 0)
        cache._upsert_entry("RELIANCE", "NSE", "5m", head_bar_ts=head, provider="mock")

        entry = cache.get_entry("RELIANCE", "NSE", "5m")
        assert entry is not None
        assert entry.symbol == "RELIANCE"
        assert entry.exchange == "NSE"
        assert entry.interval == "5m"
        assert entry.provider == "mock"
        cache.close()

    def test_upsert_updates_existing(self):
        cache = _make_cache()
        cache._upsert_entry("X", "NSE", "5m", provider="old")
        cache._upsert_entry("X", "NSE", "5m", provider="new")
        entry = cache.get_entry("X", "NSE", "5m")
        assert entry is not None
        assert entry.provider == "new"
        cache.close()

    def test_list_entries_empty(self):
        cache = _make_cache()
        assert cache.list_entries() == []
        cache.close()

    def test_list_entries_after_upsert(self):
        cache = _make_cache()
        cache._upsert_entry("RELIANCE", "NSE", "5m")
        cache._upsert_entry("TCS", "NSE", "D")
        entries = cache.list_entries()
        assert len(entries) == 2
        symbols = {e.symbol for e in entries}
        assert "RELIANCE" in symbols
        assert "TCS" in symbols
        cache.close()


# ---------------------------------------------------------------------------
# TTL helpers
# ---------------------------------------------------------------------------


class TestTTL:
    """Test TTL freshness checks."""

    def test_ttl_intraday_interval(self):
        from flinttrade_historical.cache import OHLCVCache
        cache = OHLCVCache(db_path=":memory:", ttl_intraday=60, ttl_daily=86400)
        cache.initialise()
        assert cache._ttl_for("5m") == 60
        assert cache._ttl_for("1h") == 60
        assert cache._ttl_for("D") == 86400
        cache.close()

    def test_is_fresh_within_ttl(self):
        from flinttrade_historical.cache import CacheEntry, OHLCVCache
        cache = OHLCVCache(db_path=":memory:", ttl_intraday=3600)
        cache.initialise()
        entry = CacheEntry(
            symbol="X", exchange="NSE", interval="5m",
            last_fetch=datetime.now(tz=timezone.utc) - timedelta(seconds=10),
        )
        assert cache._is_fresh(entry, "5m")
        cache.close()

    def test_is_stale_past_ttl(self):
        from flinttrade_historical.cache import CacheEntry, OHLCVCache
        cache = OHLCVCache(db_path=":memory:", ttl_intraday=60)
        cache.initialise()
        entry = CacheEntry(
            symbol="X", exchange="NSE", interval="5m",
            last_fetch=datetime.now(tz=timezone.utc) - timedelta(seconds=120),
        )
        assert not cache._is_fresh(entry, "5m")
        cache.close()

    def test_is_stale_when_last_fetch_none(self):
        from flinttrade_historical.cache import CacheEntry, OHLCVCache
        cache = OHLCVCache(db_path=":memory:")
        cache.initialise()
        entry = CacheEntry(symbol="X", exchange="NSE", interval="5m", last_fetch=None)
        assert not cache._is_fresh(entry, "5m")
        cache.close()


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------


class TestInvalidation:
    """Test cache invalidation methods."""

    def test_invalidate_clears_last_fetch(self):
        cache = _make_cache()
        cache._upsert_entry("RELIANCE", "NSE", "5m")
        cache.invalidate("RELIANCE", "NSE", "5m")
        row = cache.pipeline.connection.execute(
            "SELECT last_fetch FROM _cache_meta WHERE symbol = ? AND exchange = ? AND interval = ?",
            ["RELIANCE", "NSE", "5m"],
        ).fetchone()
        assert row is not None
        assert row[0] is None
        cache.close()

    def test_invalidate_all(self):
        cache = _make_cache()
        cache._upsert_entry("A", "NSE", "5m")
        cache._upsert_entry("B", "NSE", "D")
        cache.invalidate_all()
        rows = cache.pipeline.connection.execute(
            "SELECT last_fetch FROM _cache_meta"
        ).fetchall()
        for row in rows:
            assert row[0] is None
        cache.close()


# ---------------------------------------------------------------------------
# get() — main fetch/cache cycle
# ---------------------------------------------------------------------------


class TestCacheGet:
    """Test the get() method with mocked provider registry."""

    def test_get_fetches_from_provider_on_first_call(self):
        registry = _make_registry_with_bars([
            {"timestamp": "2026-03-16 09:15:00", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000},
        ])
        cache = _make_cache(registry=registry)

        result = cache.get("RELIANCE", "NSE", "5m", "2026-03-16", "2026-03-16")
        assert result.success
        assert result.total_bars >= 1
        assert result.new_bars >= 1
        registry.fetch.assert_called_once()
        cache.close()

    def test_get_returns_cached_on_second_call_within_ttl(self):
        registry = _make_registry_with_bars([
            {"timestamp": "2026-03-16 09:15:00", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000},
        ])
        cache = _make_cache(registry=registry, ttl_intraday=3600)

        cache.get("RELIANCE", "NSE", "5m", "2026-03-16", "2026-03-16")
        result = cache.get("RELIANCE", "NSE", "5m", "2026-03-16", "2026-03-16")

        assert result.success
        # Provider should only be called once (second call served from cache)
        assert registry.fetch.call_count == 1
        cache.close()

    def test_get_refetches_after_ttl_expires(self):
        registry = _make_registry_with_bars([
            {"timestamp": "2026-03-16 09:15:00", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000},
        ])
        # Very short TTL
        cache = _make_cache(registry=registry, ttl_intraday=0)

        cache.get("RELIANCE", "NSE", "5m", "2026-03-16", "2026-03-16")
        cache.get("RELIANCE", "NSE", "5m", "2026-03-16", "2026-03-16")

        # With TTL=0 everything is stale — should call provider twice
        assert registry.fetch.call_count == 2
        cache.close()

    def test_get_force_refresh(self):
        registry = _make_registry_with_bars([
            {"timestamp": "2026-03-16 09:15:00", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000},
        ])
        cache = _make_cache(registry=registry, ttl_intraday=3600)

        cache.get("RELIANCE", "NSE", "5m", "2026-03-16", "2026-03-16")
        cache.get("RELIANCE", "NSE", "5m", "2026-03-16", "2026-03-16", force_refresh=True)

        assert registry.fetch.call_count == 2
        cache.close()

    def test_get_no_registry_returns_cached_bars_only(self):
        cache = _make_cache(registry=None)
        # Manually insert a bar
        cache.pipeline.store_bars("ohlcv_5m", "RELIANCE", "NSE", [
            {"timestamp": "2026-03-16 09:15:00", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
        ])
        result = cache.get("RELIANCE", "NSE", "5m", "2026-03-16", "2026-03-16")
        assert result.total_bars == 1
        assert result.new_bars == 0
        cache.close()

    def test_get_error_from_provider_still_returns_cached(self):
        """When provider errors, return whatever is already cached."""
        registry = _make_registry_with_bars([], error="API down")
        cache = _make_cache(registry=registry)
        # Pre-populate cache
        cache.pipeline.store_bars("ohlcv_5m", "RELIANCE", "NSE", [
            {"timestamp": "2026-03-15 09:15:00", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
        ])
        result = cache.get("RELIANCE", "NSE", "5m", "2026-03-15", "2026-03-16")
        assert result.total_bars == 1
        assert result.new_bars == 0
        cache.close()

    def test_get_invalid_interval_returns_error(self):
        cache = _make_cache()
        result = cache.get("RELIANCE", "NSE", "2d", "2026-03-01", "2026-03-16")
        assert not result.success
        assert result.error
        cache.close()

    def test_get_merges_no_duplicates(self):
        """Calling get() twice should not double-count bars."""
        registry = _make_registry_with_bars([
            {"timestamp": "2026-03-16 09:15:00", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000},
        ])
        cache = _make_cache(registry=registry, ttl_intraday=0)

        cache.get("RELIANCE", "NSE", "5m", "2026-03-16", "2026-03-16")
        cache.get("RELIANCE", "NSE", "5m", "2026-03-16", "2026-03-16")

        count = cache.pipeline.count_bars("ohlcv_5m", "RELIANCE", "NSE")
        assert count == 1  # No duplicates despite two fetches
        cache.close()

    def test_get_updates_meta_after_fetch(self):
        registry = _make_registry_with_bars([
            {"timestamp": "2026-03-16 09:15:00", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000},
        ])
        cache = _make_cache(registry=registry)
        cache.get("RELIANCE", "NSE", "5m", "2026-03-16", "2026-03-16")
        entry = cache.get_entry("RELIANCE", "NSE", "5m")
        assert entry is not None
        assert entry.last_fetch is not None
        assert entry.provider == "mock"
        cache.close()


# ---------------------------------------------------------------------------
# get_batch()
# ---------------------------------------------------------------------------


class TestCacheGetBatch:
    """Test batch fetch."""

    def test_batch_returns_one_result_per_request(self):
        from flinttrade_historical.data_provider import ProviderBar, ProviderResult

        mock_registry = MagicMock()

        def side_effect(symbol, exchange, interval, start, end, **kwargs):
            return ProviderResult(
                symbol=symbol, exchange=exchange, interval="5m",
                provider="mock",
                bars=[ProviderBar(timestamp="2026-03-16 09:15:00", open=100, high=101,
                                   low=99, close=100.5, volume=1000)],
            )

        mock_registry.fetch.side_effect = side_effect
        cache = _make_cache(registry=mock_registry)

        results = cache.get_batch(
            [
                {"symbol": "RELIANCE", "exchange": "NSE"},
                {"symbol": "TCS", "exchange": "NSE"},
            ],
            interval="5m",
            start_date="2026-03-16",
            end_date="2026-03-16",
        )
        assert len(results) == 2
        cache.close()

    def test_batch_respects_force_refresh(self):
        registry = _make_registry_with_bars([
            {"timestamp": "2026-03-16 09:15:00", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
        ])
        cache = _make_cache(registry=registry, ttl_intraday=3600)

        cache.get_batch(
            [{"symbol": "RELIANCE", "exchange": "NSE"}],
            interval="5m", start_date="2026-03-16", end_date="2026-03-16",
        )
        cache.get_batch(
            [{"symbol": "RELIANCE", "exchange": "NSE"}],
            interval="5m", start_date="2026-03-16", end_date="2026-03-16",
            force_refresh=True,
        )
        # force_refresh=True on second call should trigger provider again
        assert registry.fetch.call_count == 2
        cache.close()


# ---------------------------------------------------------------------------
# bar_counts()
# ---------------------------------------------------------------------------


class TestBarCounts:
    """Test bar_counts() statistics method."""

    def test_bar_counts_empty(self):
        cache = _make_cache()
        counts = cache.bar_counts()
        assert all(v == 0 for v in counts.values())
        cache.close()

    def test_bar_counts_after_insert(self):
        cache = _make_cache()
        cache.pipeline.store_bars("ohlcv_1d", "X", "NSE", [
            {"timestamp": "2026-03-16", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
        ])
        counts = cache.bar_counts()
        assert counts["ohlcv_1d"] == 1
        cache.close()


# ---------------------------------------------------------------------------
# CacheResult
# ---------------------------------------------------------------------------


class TestCacheResult:
    """Test CacheResult properties."""

    def test_success_with_bars(self):
        from flinttrade_historical.cache import CacheResult
        result = CacheResult(
            symbol="X", exchange="NSE", interval="5m",
            bars=[{"timestamp": "2026-03-16 09:15:00"}],
        )
        assert result.success
        assert result.total_bars == 1

    def test_failure_with_error(self):
        from flinttrade_historical.cache import CacheResult
        result = CacheResult(symbol="X", exchange="NSE", interval="5m", error="boom")
        assert not result.success

    def test_failure_no_bars(self):
        from flinttrade_historical.cache import CacheResult
        result = CacheResult(symbol="X", exchange="NSE", interval="5m")
        assert not result.success
