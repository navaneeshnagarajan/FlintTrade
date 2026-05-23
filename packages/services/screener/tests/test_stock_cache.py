"""Tests for StockCache — DuckDB-backed fundamental data store.

All tests use an in-memory DuckDB database (db_path=":memory:").
No files are written to disk.
"""

from __future__ import annotations

import time

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cache():
    from flinttrade_screener.stock_cache import StockCache

    return StockCache(db_path=":memory:")


def _stock(
    symbol: str = "RELIANCE",
    name: str = "Reliance Industries",
    exchange: str = "NSE",
    market_cap: float = 1_800_000.0,
    pe_ratio: float = 24.5,
    pb_ratio: float = 2.1,
    roe: float = 15.2,
    roce: float = 13.8,
    dividend_yield: float = 0.4,
    sector: str = "Energy",
    updated_at: float | None = None,
):
    from flinttrade_screener.stock_cache import StockFundamentals

    return StockFundamentals(
        symbol=symbol,
        name=name,
        exchange=exchange,
        market_cap=market_cap,
        pe_ratio=pe_ratio,
        pb_ratio=pb_ratio,
        roe=roe,
        roce=roce,
        dividend_yield=dividend_yield,
        sector=sector,
        updated_at=updated_at if updated_at is not None else time.time(),
    )


# ===========================================================================
# Upsert and get
# ===========================================================================


class TestUpsertAndGet:
    def test_upsert_and_get(self):
        with _make_cache() as cache:
            cache.upsert(_stock())
            result = cache.get("RELIANCE")
            assert result is not None
            assert result.symbol == "RELIANCE"
            assert result.name == "Reliance Industries"

    def test_get_all_fields_preserved(self):
        with _make_cache() as cache:
            s = _stock(
                symbol="TCS",
                market_cap=1_200_000.0,
                pe_ratio=30.1,
                pb_ratio=12.5,
                roe=44.0,
                roce=56.0,
                dividend_yield=1.2,
                sector="IT",
            )
            cache.upsert(s)
            result = cache.get("TCS")
            assert result is not None
            assert result.market_cap == pytest.approx(1_200_000.0)
            assert result.pe_ratio == pytest.approx(30.1)
            assert result.pb_ratio == pytest.approx(12.5)
            assert result.roe == pytest.approx(44.0)
            assert result.roce == pytest.approx(56.0)
            assert result.dividend_yield == pytest.approx(1.2)
            assert result.sector == "IT"

    def test_upsert_overwrites_existing(self):
        """Second upsert for the same symbol replaces the first row."""
        with _make_cache() as cache:
            cache.upsert(_stock(symbol="INFY", pe_ratio=20.0))
            cache.upsert(_stock(symbol="INFY", pe_ratio=25.0))
            result = cache.get("INFY")
            assert result is not None
            assert result.pe_ratio == pytest.approx(25.0)
            assert cache.count() == 1  # only one row

    def test_get_missing_returns_none(self):
        with _make_cache() as cache:
            assert cache.get("GHOST") is None

    def test_expired_returns_none(self):
        """Rows older than 24 hours must not be returned."""
        with _make_cache() as cache:
            stale_ts = time.time() - 90_000  # 25 hours ago
            cache.upsert(_stock(symbol="WIPRO", updated_at=stale_ts))
            assert cache.get("WIPRO") is None

    def test_fresh_row_is_returned(self):
        with _make_cache() as cache:
            cache.upsert(_stock(symbol="HDFCBANK", updated_at=time.time()))
            assert cache.get("HDFCBANK") is not None


# ===========================================================================
# Scan — filters
# ===========================================================================


class TestScanFilters:
    def _seed(self, cache) -> None:
        """Insert a diverse dataset for filter tests."""
        cache.upsert(_stock("RELIANCE", sector="Energy",  market_cap=1_800_000, pe_ratio=24.5, roce=13.8, roe=15.0))
        cache.upsert(_stock("TCS",      sector="IT",      market_cap=1_200_000, pe_ratio=30.1, roce=56.0, roe=44.0))
        cache.upsert(_stock("INFY",     sector="IT",      market_cap=600_000,   pe_ratio=25.0, roce=35.0, roe=30.0))
        cache.upsert(_stock("SBIN",     sector="Banking", market_cap=550_000,   pe_ratio=10.5, roce=8.0,  roe=12.0))
        cache.upsert(_stock("HDFCBANK", sector="Banking", market_cap=900_000,   pe_ratio=19.0, roce=14.0, roe=16.0))

    def test_scan_with_no_filters_returns_all(self):
        with _make_cache() as cache:
            self._seed(cache)
            results = cache.scan(limit=100)
            assert len(results) == 5

    def test_scan_pe_lt_filter(self):
        with _make_cache() as cache:
            self._seed(cache)
            results = cache.scan(filters={"pe_lt": 20.0})
            symbols = {r.symbol for r in results}
            assert "SBIN" in symbols
            assert "HDFCBANK" in symbols
            assert "TCS" not in symbols

    def test_scan_pe_gt_filter(self):
        with _make_cache() as cache:
            self._seed(cache)
            results = cache.scan(filters={"pe_gt": 25.0})
            symbols = {r.symbol for r in results}
            assert "TCS" in symbols

    def test_scan_roce_gt_filter(self):
        with _make_cache() as cache:
            self._seed(cache)
            results = cache.scan(filters={"roce_gt": 30.0})
            symbols = {r.symbol for r in results}
            assert "TCS" in symbols
            assert "INFY" in symbols
            assert "RELIANCE" not in symbols

    def test_scan_sector_eq_filter(self):
        with _make_cache() as cache:
            self._seed(cache)
            results = cache.scan(filters={"sector_eq": "IT"})
            symbols = {r.symbol for r in results}
            assert symbols == {"TCS", "INFY"}

    def test_scan_market_cap_gt_filter(self):
        with _make_cache() as cache:
            self._seed(cache)
            results = cache.scan(filters={"market_cap_gt": 1_000_000})
            symbols = {r.symbol for r in results}
            assert "RELIANCE" in symbols
            assert "TCS" in symbols
            assert "SBIN" not in symbols

    def test_scan_market_cap_lt_filter(self):
        with _make_cache() as cache:
            self._seed(cache)
            results = cache.scan(filters={"market_cap_lt": 700_000})
            symbols = {r.symbol for r in results}
            assert "INFY" in symbols
            assert "SBIN" in symbols
            assert "RELIANCE" not in symbols

    def test_scan_combined_filters(self):
        with _make_cache() as cache:
            self._seed(cache)
            results = cache.scan(filters={"sector_eq": "IT", "roce_gt": 40.0})
            symbols = {r.symbol for r in results}
            assert symbols == {"TCS"}

    def test_scan_filters_exclude_expired(self):
        with _make_cache() as cache:
            cache.upsert(_stock("STALE", updated_at=time.time() - 90_000))
            cache.upsert(_stock("FRESH"))
            results = cache.scan(limit=100)
            symbols = {r.symbol for r in results}
            assert "STALE" not in symbols
            assert "FRESH" in symbols


# ===========================================================================
# Scan — sort order
# ===========================================================================


class TestScanSortOrder:
    def _seed(self, cache) -> None:
        cache.upsert(_stock("A", market_cap=100.0, pe_ratio=5.0,  roce=50.0))
        cache.upsert(_stock("B", market_cap=300.0, pe_ratio=15.0, roce=30.0))
        cache.upsert(_stock("C", market_cap=200.0, pe_ratio=10.0, roce=40.0))

    def test_scan_sort_market_cap_desc(self):
        with _make_cache() as cache:
            self._seed(cache)
            results = cache.scan(sort_by="market_cap", ascending=False)
            caps = [r.market_cap for r in results]
            assert caps == sorted(caps, reverse=True)

    def test_scan_sort_market_cap_asc(self):
        with _make_cache() as cache:
            self._seed(cache)
            results = cache.scan(sort_by="market_cap", ascending=True)
            caps = [r.market_cap for r in results]
            assert caps == sorted(caps)

    def test_scan_sort_by_pe_ratio(self):
        with _make_cache() as cache:
            self._seed(cache)
            results = cache.scan(sort_by="pe_ratio", ascending=False)
            pes = [r.pe_ratio for r in results]
            assert pes == sorted(pes, reverse=True)

    def test_scan_sort_by_roce(self):
        with _make_cache() as cache:
            self._seed(cache)
            results = cache.scan(sort_by="roce", ascending=False)
            roces = [r.roce for r in results]
            assert roces == sorted(roces, reverse=True)

    def test_scan_sort_by_symbol_asc(self):
        with _make_cache() as cache:
            self._seed(cache)
            results = cache.scan(sort_by="symbol", ascending=True)
            syms = [r.symbol for r in results]
            assert syms == sorted(syms)

    def test_invalid_sort_column_falls_back_to_market_cap(self):
        """An unrecognised sort_by value must not raise — it falls back to market_cap."""
        with _make_cache() as cache:
            self._seed(cache)
            # Should not raise
            results = cache.scan(sort_by="DROP TABLE stock_fundamentals;--", ascending=False)
            assert len(results) == 3

    def test_scan_sort_with_invalid_column_uses_fallback_order(self):
        with _make_cache() as cache:
            self._seed(cache)
            results = cache.scan(sort_by="INVALID_COLUMN", ascending=False)
            caps = [r.market_cap for r in results]
            assert caps == sorted(caps, reverse=True)


# ===========================================================================
# Scan — limit
# ===========================================================================


class TestScanLimit:
    def _seed_n(self, cache, n: int) -> None:
        for i in range(n):
            cache.upsert(_stock(symbol=f"SYM{i:04d}", market_cap=float(i)))

    def test_scan_limit(self):
        with _make_cache() as cache:
            self._seed_n(cache, 20)
            results = cache.scan(limit=5)
            assert len(results) == 5

    def test_scan_limit_larger_than_rows_returns_all(self):
        with _make_cache() as cache:
            self._seed_n(cache, 3)
            results = cache.scan(limit=100)
            assert len(results) == 3

    def test_scan_limit_one(self):
        with _make_cache() as cache:
            self._seed_n(cache, 10)
            results = cache.scan(limit=1)
            assert len(results) == 1


# ===========================================================================
# Maintenance helpers
# ===========================================================================


class TestMaintenance:
    def test_count_reflects_inserted_rows(self):
        with _make_cache() as cache:
            assert cache.count() == 0
            cache.upsert(_stock("A"))
            cache.upsert(_stock("B"))
            assert cache.count() == 2

    def test_purge_expired_removes_stale_rows(self):
        with _make_cache() as cache:
            cache.upsert(_stock("OLD", updated_at=time.time() - 90_000))
            cache.upsert(_stock("NEW"))
            deleted = cache.purge_expired()
            assert deleted == 1
            assert cache.count() == 1
            assert cache.get("NEW") is not None

    def test_purge_expired_returns_zero_when_nothing_to_purge(self):
        with _make_cache() as cache:
            cache.upsert(_stock("FRESH"))
            assert cache.purge_expired() == 0


# ===========================================================================
# Context manager
# ===========================================================================


class TestContextManager:
    def test_context_manager_closes_connection(self):
        from flinttrade_screener.stock_cache import StockCache

        with StockCache(db_path=":memory:") as cache:
            cache.upsert(_stock())
            result = cache.get("RELIANCE")
            assert result is not None
        # After __exit__ the connection is closed; accessing it should raise
        with pytest.raises(Exception):
            cache.get("RELIANCE")
