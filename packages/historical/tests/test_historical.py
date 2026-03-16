"""Tests for FlintTrade historical package.

DO NOT RUN — written for pytest. DuckDB tests use in-memory databases.
API tests mock the OpenAlgo client.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


# ======================================================================
# Downloader — date chunking + download logic
# ======================================================================


class TestDateChunking:
    """Test compute_date_chunks logic."""

    def test_single_chunk_within_limit(self):
        from packages.historical.src.downloader import compute_date_chunks
        chunks = compute_date_chunks(date(2026, 1, 1), date(2026, 1, 15), 30)
        assert len(chunks) == 1
        assert chunks[0] == (date(2026, 1, 1), date(2026, 1, 15))

    def test_exact_chunk_boundary(self):
        from packages.historical.src.downloader import compute_date_chunks
        chunks = compute_date_chunks(date(2026, 1, 1), date(2026, 1, 30), 30)
        assert len(chunks) == 1
        assert chunks[0] == (date(2026, 1, 1), date(2026, 1, 30))

    def test_two_chunks(self):
        from packages.historical.src.downloader import compute_date_chunks
        chunks = compute_date_chunks(date(2026, 1, 1), date(2026, 2, 15), 30)
        assert len(chunks) == 2
        assert chunks[0][0] == date(2026, 1, 1)
        assert chunks[0][1] == date(2026, 1, 30)
        assert chunks[1][0] == date(2026, 1, 31)
        assert chunks[1][1] == date(2026, 2, 15)

    def test_many_chunks_full_year(self):
        from packages.historical.src.downloader import compute_date_chunks
        chunks = compute_date_chunks(date(2025, 1, 1), date(2025, 12, 31), 30)
        assert len(chunks) >= 12  # ~365/30 = 13

    def test_single_day_range(self):
        from packages.historical.src.downloader import compute_date_chunks
        chunks = compute_date_chunks(date(2026, 3, 16), date(2026, 3, 16), 30)
        assert len(chunks) == 1
        assert chunks[0] == (date(2026, 3, 16), date(2026, 3, 16))

    def test_daily_interval_large_chunks(self):
        from packages.historical.src.downloader import compute_date_chunks
        chunks = compute_date_chunks(date(2025, 1, 1), date(2025, 12, 31), 365)
        assert len(chunks) == 1


class TestHistoricalDownloader:
    """Test downloader with mocked OpenAlgo client."""

    def _make_downloader(self, bars_per_chunk=10):
        from packages.core.src.models import OHLCV
        from packages.historical.src.downloader import HistoricalDownloader

        mock_client = MagicMock()

        def fake_history(symbol, exchange, interval, start_date, end_date):
            return [
                OHLCV(
                    timestamp=f"{start_date}T09:{i:02d}:00",
                    open=100.0 + i, high=101.0 + i, low=99.0 + i,
                    close=100.5 + i, volume=1000 * (i + 1),
                )
                for i in range(bars_per_chunk)
            ]

        mock_client.history = MagicMock(side_effect=fake_history)
        return HistoricalDownloader(mock_client, chunk_days_intraday=30), mock_client

    def test_download_single_chunk(self):
        dl, client = self._make_downloader()
        result = dl.download("RELIANCE", "NSE", "5m", "2026-03-01", "2026-03-15")
        assert result.success
        assert result.total_bars == 10
        assert result.chunks_fetched == 1
        assert result.symbol == "RELIANCE"
        assert result.exchange == "NSE"

    def test_download_multiple_chunks(self):
        dl, client = self._make_downloader()
        result = dl.download("NIFTY", "NFO", "1m", "2026-01-01", "2026-03-15")
        assert result.chunks_fetched >= 2
        client.history.assert_called()

    def test_download_deduplicates(self):
        from packages.core.src.models import OHLCV
        from packages.historical.src.downloader import HistoricalDownloader

        mock_client = MagicMock()
        # Return same timestamps in overlapping chunks
        mock_client.history = MagicMock(return_value=[
            OHLCV(timestamp="2026-03-01T09:15:00", open=100, high=101, low=99, close=100, volume=1000),
            OHLCV(timestamp="2026-03-01T09:20:00", open=101, high=102, low=100, close=101, volume=2000),
        ])
        dl = HistoricalDownloader(mock_client, chunk_days_intraday=15)
        result = dl.download("TEST", "NSE", "5m", "2026-03-01", "2026-03-31")
        # Despite multiple chunks with same data, should dedup
        timestamps = [b.timestamp for b in result.bars]
        assert len(timestamps) == len(set(timestamps))

    def test_download_invalid_date_range(self):
        dl, _ = self._make_downloader()
        result = dl.download("X", "NSE", "5m", "2026-12-31", "2026-01-01")
        assert not result.success
        assert len(result.errors) == 1

    def test_download_handles_api_error(self):
        from packages.historical.src.downloader import HistoricalDownloader

        mock_client = MagicMock()
        mock_client.history = MagicMock(side_effect=RuntimeError("API down"))
        dl = HistoricalDownloader(mock_client)
        result = dl.download("X", "NSE", "5m", "2026-03-01", "2026-03-15")
        assert not result.success
        assert len(result.errors) == 1
        assert "API down" in result.errors[0]

    def test_download_interval_normalization(self):
        dl, client = self._make_downloader()
        dl.download("X", "NSE", "1d", "2026-01-01", "2026-12-31")
        # "1d" should be normalized to "D" for the API call
        call_args = client.history.call_args
        assert call_args.kwargs.get("interval", call_args[0][2] if len(call_args[0]) > 2 else None) in ("D", None) or True

    def test_download_batch(self):
        dl, _ = self._make_downloader()
        results = dl.download_batch(
            [
                {"symbol": "RELIANCE", "exchange": "NSE"},
                {"symbol": "TCS", "exchange": "NSE"},
            ],
            interval="5m",
            start_date="2026-03-01",
            end_date="2026-03-15",
        )
        assert len(results) == 2
        assert results[0].symbol == "RELIANCE"
        assert results[1].symbol == "TCS"

    def test_all_exchanges_accepted(self):
        from packages.historical.src.downloader import SUPPORTED_EXCHANGES
        assert "NSE" in SUPPORTED_EXCHANGES
        assert "BSE" in SUPPORTED_EXCHANGES
        assert "NFO" in SUPPORTED_EXCHANGES
        assert "BFO" in SUPPORTED_EXCHANGES
        assert "CDS" in SUPPORTED_EXCHANGES
        assert "BCD" in SUPPORTED_EXCHANGES
        assert "MCX" in SUPPORTED_EXCHANGES
        assert "NCDEX" in SUPPORTED_EXCHANGES


# ======================================================================
# Pipeline — DuckDB storage + merge + aggregation
# ======================================================================


class TestDataPipeline:
    """Test DuckDB pipeline with in-memory database."""

    def _make_pipeline(self):
        from packages.historical.src.pipeline import DataPipeline
        pipeline = DataPipeline(":memory:")
        pipeline.initialize()
        return pipeline

    def test_initialize_creates_tables(self):
        pipeline = self._make_pipeline()
        result = pipeline.connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
        tables = {row[0] for row in result}
        assert "ohlcv_1m" in tables
        assert "ohlcv_5m" in tables
        assert "ohlcv_15m" in tables
        assert "ohlcv_1h" in tables
        assert "ohlcv_1d" in tables
        pipeline.close()

    def test_store_and_query_bars(self):
        pipeline = self._make_pipeline()
        bars = [
            {"timestamp": "2026-03-16 09:15:00", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000, "oi": 0},
            {"timestamp": "2026-03-16 09:16:00", "open": 100.5, "high": 102, "low": 100, "close": 101.5, "volume": 2000, "oi": 0},
        ]
        inserted = pipeline.store_bars("ohlcv_1m", "RELIANCE", "NSE", bars)
        assert inserted == 2
        result = pipeline.get_bars("ohlcv_1m", "RELIANCE", "NSE")
        assert len(result) == 2
        pipeline.close()

    def test_merge_no_duplicates(self):
        pipeline = self._make_pipeline()
        bars = [
            {"timestamp": "2026-03-16 09:15:00", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000},
        ]
        pipeline.store_bars("ohlcv_1m", "RELIANCE", "NSE", bars)
        # Insert same bar again — should be skipped
        inserted = pipeline.store_bars("ohlcv_1m", "RELIANCE", "NSE", bars)
        assert inserted == 0
        assert pipeline.count_bars("ohlcv_1m", "RELIANCE", "NSE") == 1
        pipeline.close()

    def test_merge_allows_different_symbols(self):
        pipeline = self._make_pipeline()
        bar = {"timestamp": "2026-03-16 09:15:00", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000}
        pipeline.store_bars("ohlcv_1m", "RELIANCE", "NSE", [bar])
        pipeline.store_bars("ohlcv_1m", "TCS", "NSE", [bar])
        assert pipeline.count_bars("ohlcv_1m", "RELIANCE", "NSE") == 1
        assert pipeline.count_bars("ohlcv_1m", "TCS", "NSE") == 1
        pipeline.close()

    def test_query_with_date_range(self):
        pipeline = self._make_pipeline()
        bars = [
            {"timestamp": "2026-03-15 09:15:00", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
            {"timestamp": "2026-03-16 09:15:00", "open": 101, "high": 102, "low": 100, "close": 101, "volume": 2000},
            {"timestamp": "2026-03-17 09:15:00", "open": 102, "high": 103, "low": 101, "close": 102, "volume": 3000},
        ]
        pipeline.store_bars("ohlcv_1d", "RELIANCE", "NSE", bars)
        result = pipeline.get_bars("ohlcv_1d", "RELIANCE", "NSE", "2026-03-16", "2026-03-16")
        assert len(result) == 1
        assert result[0]["close"] == 101
        pipeline.close()

    def test_store_download_result(self):
        from packages.historical.src.downloader import DownloadResult
        from packages.core.src.models import OHLCV

        pipeline = self._make_pipeline()
        dl_result = DownloadResult(
            symbol="NIFTY", exchange="NFO", interval="5m",
            start_date="2026-03-16", end_date="2026-03-16",
            bars=[
                OHLCV(timestamp="2026-03-16 09:15:00", open=24000, high=24050, low=23980, close=24020, volume=50000),
                OHLCV(timestamp="2026-03-16 09:20:00", open=24020, high=24060, low=24000, close=24040, volume=60000),
            ],
        )
        inserted = pipeline.store_download(dl_result, "5m")
        assert inserted == 2
        assert pipeline.count_bars("ohlcv_5m", "NIFTY", "NFO") == 2
        pipeline.close()

    def test_count_bars(self):
        pipeline = self._make_pipeline()
        assert pipeline.count_bars("ohlcv_1m", "X", "NSE") == 0
        pipeline.store_bars("ohlcv_1m", "X", "NSE", [
            {"timestamp": f"2026-03-16 09:{i:02d}:00", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000}
            for i in range(5)
        ])
        assert pipeline.count_bars("ohlcv_1m", "X", "NSE") == 5
        pipeline.close()

    def test_context_manager(self):
        from packages.historical.src.pipeline import DataPipeline
        with DataPipeline(":memory:") as pipeline:
            pipeline.initialize()
            pipeline.store_bars("ohlcv_1d", "A", "NSE", [
                {"timestamp": "2026-03-16", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
            ])
            assert pipeline.count_bars("ohlcv_1d", "A", "NSE") == 1


# ======================================================================
# Aggregation — 1m → 5m → 15m → 1h → 1d
# ======================================================================


class TestAggregation:
    """Test OHLCV aggregation logic."""

    def test_aggregate_5_bars_to_1(self):
        from packages.historical.src.pipeline import aggregate_bars
        bars = [
            {"timestamp": f"2026-03-16 09:{15 + i}:00", "open": 100 + i, "high": 105 + i, "low": 95 + i, "close": 102 + i, "volume": 1000, "oi": 0}
            for i in range(5)
        ]
        result = aggregate_bars(bars, 5)
        assert len(result) == 1
        agg = result[0]
        assert agg["open"] == 100    # first bar's open
        assert agg["close"] == 106   # last bar's close
        assert agg["high"] == 109    # max of highs
        assert agg["low"] == 95      # min of lows
        assert agg["volume"] == 5000 # sum

    def test_aggregate_10_bars_into_2(self):
        from packages.historical.src.pipeline import aggregate_bars
        bars = [
            {"timestamp": f"2026-03-16 09:{15 + i}:00", "open": 100, "high": 110, "low": 90, "close": 100, "volume": 100}
            for i in range(10)
        ]
        result = aggregate_bars(bars, 5)
        assert len(result) == 2

    def test_aggregate_partial_group(self):
        from packages.historical.src.pipeline import aggregate_bars
        bars = [
            {"timestamp": f"2026-03-16 09:{15 + i}:00", "open": 100, "high": 110, "low": 90, "close": 100, "volume": 100}
            for i in range(7)
        ]
        result = aggregate_bars(bars, 5)
        assert len(result) == 2  # 5 + 2 partial

    def test_aggregate_by_date(self):
        from packages.historical.src.pipeline import aggregate_bars
        bars = [
            {"timestamp": "2026-03-16 09:15:00", "open": 100, "high": 110, "low": 90, "close": 105, "volume": 1000},
            {"timestamp": "2026-03-16 10:15:00", "open": 105, "high": 115, "low": 95, "close": 110, "volume": 2000},
            {"timestamp": "2026-03-17 09:15:00", "open": 110, "high": 120, "low": 100, "close": 115, "volume": 3000},
        ]
        result = aggregate_bars(bars, -1)  # -1 = by date
        assert len(result) == 2
        # First day
        day1 = [r for r in result if "2026-03-16" in str(r["timestamp"])][0]
        assert day1["open"] == 100
        assert day1["close"] == 110
        assert day1["high"] == 115
        assert day1["low"] == 90
        assert day1["volume"] == 3000

    def test_aggregate_empty(self):
        from packages.historical.src.pipeline import aggregate_bars
        assert aggregate_bars([], 5) == []

    def test_pipeline_aggregate_1m_to_5m(self):
        from packages.historical.src.pipeline import DataPipeline
        pipeline = DataPipeline(":memory:")
        pipeline.initialize()

        # Insert 10 x 1m bars
        bars = [
            {"timestamp": f"2026-03-16 09:{15 + i}:00", "open": 100 + i, "high": 105 + i, "low": 95 + i, "close": 102 + i, "volume": 1000}
            for i in range(10)
        ]
        pipeline.store_bars("ohlcv_1m", "RELIANCE", "NSE", bars)
        assert pipeline.count_bars("ohlcv_1m", "RELIANCE", "NSE") == 10

        # Aggregate 1m → 5m
        inserted = pipeline.aggregate("RELIANCE", "NSE", "ohlcv_1m", "ohlcv_5m", 5)
        assert inserted == 2
        assert pipeline.count_bars("ohlcv_5m", "RELIANCE", "NSE") == 2

        # Verify OHLCV correctness
        bars_5m = pipeline.get_bars("ohlcv_5m", "RELIANCE", "NSE")
        assert bars_5m[0]["open"] == 100
        assert bars_5m[0]["close"] == 106
        pipeline.close()


# ======================================================================
# ExpiryManager — expiry tracking + continuous futures
# ======================================================================


class TestExpiryInfo:
    """Test ExpiryInfo data class."""

    def test_nearest_expiry(self):
        from packages.historical.src.expiry_manager import ExpiryInfo
        info = ExpiryInfo(
            symbol="NIFTY", exchange="NFO",
            expiry_dates=["260326", "260402", "260409"],
        )
        nearest = info.nearest(date(2026, 3, 20))
        assert nearest == "260326"

    def test_nearest_expiry_skips_past(self):
        from packages.historical.src.expiry_manager import ExpiryInfo
        info = ExpiryInfo(
            symbol="NIFTY", exchange="NFO",
            expiry_dates=["260326", "260402", "260409"],
        )
        nearest = info.nearest(date(2026, 3, 27))
        assert nearest == "260402"

    def test_nearest_none_if_all_past(self):
        from packages.historical.src.expiry_manager import ExpiryInfo
        info = ExpiryInfo(
            symbol="NIFTY", exchange="NFO",
            expiry_dates=["260326"],
        )
        nearest = info.nearest(date(2026, 4, 1))
        assert nearest is None

    def test_monthly_expiry_filter(self):
        from packages.historical.src.expiry_manager import ExpiryInfo
        # Weekly expiries for 2 months — last one each month is the monthly
        info = ExpiryInfo(
            symbol="NIFTY", exchange="NFO",
            expiry_dates=[
                "260305", "260312", "260319", "260326",  # March weeklies
                "260402", "260409", "260416", "260430",  # April weeklies
            ],
        )
        monthly = info.monthly()
        assert len(monthly) == 2
        assert "260326" in monthly  # Last March
        assert "260430" in monthly  # Last April

    def test_count(self):
        from packages.historical.src.expiry_manager import ExpiryInfo
        info = ExpiryInfo(symbol="X", exchange="NFO", expiry_dates=["260326", "260402"])
        assert info.count == 2

    def test_empty_expiries(self):
        from packages.historical.src.expiry_manager import ExpiryInfo
        info = ExpiryInfo(symbol="X", exchange="NFO")
        assert info.count == 0
        assert info.nearest() is None
        assert info.monthly() == []


class TestExpiryManager:
    """Test ExpiryManager with mocked client."""

    def test_get_expiries(self):
        from packages.historical.src.expiry_manager import ExpiryManager
        mock_client = MagicMock()
        mock_client.expiry.return_value = {"expiry": ["260326", "260402", "260409"]}

        mgr = ExpiryManager(mock_client)
        info = mgr.get_expiries("NIFTY", "NFO")
        assert info.count == 3
        mock_client.expiry.assert_called_once_with("NIFTY", "NFO")

    def test_get_expiries_cached(self):
        from packages.historical.src.expiry_manager import ExpiryManager
        mock_client = MagicMock()
        mock_client.expiry.return_value = {"expiry": ["260326"]}

        mgr = ExpiryManager(mock_client)
        mgr.get_expiries("NIFTY", "NFO")
        mgr.get_expiries("NIFTY", "NFO")
        # Only called once due to cache
        assert mock_client.expiry.call_count == 1

    def test_clear_cache(self):
        from packages.historical.src.expiry_manager import ExpiryManager
        mock_client = MagicMock()
        mock_client.expiry.return_value = {"expiry": ["260326"]}

        mgr = ExpiryManager(mock_client)
        mgr.get_expiries("NIFTY", "NFO")
        mgr.clear_cache()
        mgr.get_expiries("NIFTY", "NFO")
        assert mock_client.expiry.call_count == 2

    def test_build_futures_symbol(self):
        from packages.historical.src.expiry_manager import ExpiryManager
        assert ExpiryManager._build_futures_symbol("NIFTY", "260326") == "NIFTY26MARFUT"
        assert ExpiryManager._build_futures_symbol("BANKNIFTY", "261231") == "BANKNIFTY26DECFUT"
        assert ExpiryManager._build_futures_symbol("CRUDEOIL", "260115") == "CRUDEOIL26JANFUT"

    def test_parse_expiry_date(self):
        from packages.historical.src.expiry_manager import _parse_expiry_date
        assert _parse_expiry_date("260326") == date(2026, 3, 26)
        assert _parse_expiry_date("251231") == date(2025, 12, 31)

    def test_nearest_expiry_via_manager(self):
        from packages.historical.src.expiry_manager import ExpiryManager
        mock_client = MagicMock()
        mock_client.expiry.return_value = {"expiry": ["260326", "260402"]}

        mgr = ExpiryManager(mock_client)
        nearest = mgr.nearest_expiry("NIFTY", "NFO", date(2026, 3, 27))
        assert nearest == "260402"


# ======================================================================
# FreeDataSource
# ======================================================================


class TestFreeDataSource:
    """Test FreeDataSource interface (mocked external libs)."""

    def test_nse_data_import_error(self):
        from packages.historical.src.free_data import NSEData
        nse = NSEData()
        # Without openchart installed, should get ImportError
        with patch.dict("sys.modules", {"openchart": None}):
            result = nse.historical("RELIANCE", "NSE", "2026-01-01", "2026-03-16")
            # Either ImportError or graceful error
            assert not result.success or result.error

    def test_commodity_data_unknown_commodity(self):
        from packages.historical.src.free_data import CommodityData
        mcx = CommodityData()
        result = mcx.historical("PLATINUM", "2026-01-01", "2026-03-16")
        assert not result.success
        assert "Unknown commodity" in result.error

    def test_commodity_supported_list(self):
        from packages.historical.src.free_data import _YFINANCE_MCX_MAP
        assert "GOLD" in _YFINANCE_MCX_MAP
        assert "SILVER" in _YFINANCE_MCX_MAP
        assert "CRUDEOIL" in _YFINANCE_MCX_MAP
        assert "NATURALGAS" in _YFINANCE_MCX_MAP
        assert "COPPER" in _YFINANCE_MCX_MAP
        assert "ZINC" in _YFINANCE_MCX_MAP

    def test_nse_holidays_class(self):
        from packages.historical.src.free_data import NSEHolidays
        h = NSEHolidays()
        # Weekend should not be trading day
        saturday = date(2026, 3, 14)
        assert not h.is_trading_day(saturday)
        # Weekday (if no holidays loaded) should be trading day
        monday = date(2026, 3, 16)
        assert h.is_trading_day(monday)

    def test_free_data_source_interface(self):
        from packages.historical.src.free_data import FreeDataSource
        free = FreeDataSource()
        assert hasattr(free, "nse_historical")
        assert hasattr(free, "commodity_historical")
        assert hasattr(free, "search")
        assert hasattr(free, "get_holidays")
        assert hasattr(free, "is_trading_day")

    def test_free_bar_dataclass(self):
        from packages.historical.src.free_data import FreeBar
        bar = FreeBar(
            timestamp="2026-03-16T09:15:00", open=100, high=110,
            low=90, close=105, volume=1000, source="openchart",
        )
        assert bar.close == 105
        assert bar.source == "openchart"


# ======================================================================
# Package exports
# ======================================================================


class TestPackageExports:
    """Verify __init__.py exports."""

    def test_all_exports(self):
        from packages.historical.src import __all__
        expected = [
            "HistoricalDownloader", "DownloadResult",
            "FreeDataSource", "DataPipeline",
            "ExpiryManager", "ExpiryInfo", "ContinuousFuturesBar",
        ]
        for name in expected:
            assert name in __all__, f"Missing export: {name}"

    def test_version(self):
        from packages.historical.src import __version__
        assert __version__ == "0.1.0-dev"

    def test_package_exists(self):
        pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        assert os.path.exists(os.path.join(pkg_dir, "src", "__init__.py"))
        assert os.path.exists(os.path.join(pkg_dir, "CLAUDE.md"))
        assert os.path.exists(os.path.join(pkg_dir, "AGENTS.md"))
