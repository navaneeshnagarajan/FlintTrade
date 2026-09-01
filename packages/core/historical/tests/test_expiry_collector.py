"""Tests for ExpiryDataCollector — expired F&O contract data collection.

All tests mock the OpenAlgo client. No network calls.
"""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch


# ======================================================================
# ExpiryDataCollector — initialization and data dir
# ======================================================================


class TestExpiryDataCollectorInit:
    """Test collector initialization and data directory handling."""

    def test_default_data_dir(self):
        from flinttrade_historical.expiry_collector import ExpiryDataCollector
        mock_client = MagicMock()
        collector = ExpiryDataCollector(mock_client)
        assert "expiry_data" in str(collector.data_dir)

    def test_custom_data_dir(self, tmp_path):
        from flinttrade_historical.expiry_collector import ExpiryDataCollector
        mock_client = MagicMock()
        collector = ExpiryDataCollector(mock_client, data_dir=str(tmp_path / "custom"))
        assert "custom" in str(collector.data_dir)

    def test_ensure_data_dir_creates_directory(self, tmp_path):
        from flinttrade_historical.expiry_collector import ExpiryDataCollector
        mock_client = MagicMock()
        target = tmp_path / "new_dir"
        collector = ExpiryDataCollector(mock_client, data_dir=str(target))
        collector._ensure_data_dir()
        assert target.exists()


# ======================================================================
# ExpiryDataResult — dataclass properties
# ======================================================================


class TestExpiryDataResult:
    """Test ExpiryDataResult properties."""

    def test_empty_result(self):
        from flinttrade_historical.expiry_collector import ExpiryDataResult
        result = ExpiryDataResult(symbol="NIFTY", expiry="260327", exchange="NFO")
        assert result.total_bars == 0
        assert not result.success

    def test_result_with_records(self):
        from flinttrade_historical.expiry_collector import (
            ExpiryDataRecord,
            ExpiryDataResult,
        )
        result = ExpiryDataResult(
            symbol="NIFTY",
            expiry="260327",
            exchange="NFO",
            records=[
                ExpiryDataRecord(
                    timestamp="2026-01-15T09:15:00",
                    open=22000.0, high=22100.0, low=21900.0,
                    close=22050.0, volume=10000,
                    symbol="NIFTY", expiry="260327",
                ),
            ],
        )
        assert result.total_bars == 1
        assert result.success


# ======================================================================
# ExpiryDataRecord — dataclass defaults
# ======================================================================


class TestExpiryDataRecord:
    """Test ExpiryDataRecord defaults."""

    def test_default_values(self):
        from flinttrade_historical.expiry_collector import ExpiryDataRecord
        record = ExpiryDataRecord()
        assert record.timestamp == ""
        assert record.open == 0.0
        assert record.volume == 0
        assert record.symbol == ""
        assert record.expiry == ""


# ======================================================================
# get_past_expiries — filtering logic
# ======================================================================


class TestGetPastExpiries:
    """Test past expiry filtering."""

    def _make_collector(self, expiry_dates):
        from flinttrade_historical.expiry_collector import ExpiryDataCollector
        from flinttrade_historical.expiry_manager import ExpiryInfo

        mock_client = MagicMock()
        collector = ExpiryDataCollector(mock_client)

        # Mock the expiry manager to return our dates
        mock_info = ExpiryInfo(
            symbol="NIFTY", exchange="NFO",
            expiry_dates=expiry_dates,
        )
        collector._expiry_mgr.get_expiries = MagicMock(return_value=mock_info)
        return collector

    def test_no_expiries_returns_empty(self):
        collector = self._make_collector([])
        result = collector.get_past_expiries("NIFTY", months=12)
        assert result == []

    def test_filters_to_past_dates(self):
        # Use dates that are definitely in the past (2025)
        collector = self._make_collector(["250101", "250201", "250301", "290101"])
        with patch("flinttrade_historical.expiry_collector.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 31)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = collector.get_past_expiries("NIFTY", months=24)
        # 250101, 250201, 250301 are in the past; 290101 is in the future
        assert "290101" not in result

    def test_months_lookback(self):
        collector = self._make_collector(["240101", "260101", "260201"])
        with patch("flinttrade_historical.expiry_collector.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 31)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            # Only look back 3 months — should exclude 240101 and 260101
            result = collector.get_past_expiries("NIFTY", months=3)
        assert "240101" not in result

    def test_official_dashed_expiries_are_chronological(self):
        collector = self._make_collector(["02-APR-25", "26-MAR-25"])
        with patch("flinttrade_historical.expiry_collector.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 31)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = collector.get_past_expiries("NIFTY", months=24)
        assert result == ["26-MAR-25", "02-APR-25"]


# ======================================================================
# download_expiry_data — mock download
# ======================================================================


class TestDownloadExpiryData:
    """Test downloading data for a specific expiry."""

    def _make_collector(self, tmp_path, bars=None):
        from flinttrade_core.models import OHLCV
        from flinttrade_historical.downloader import DownloadResult
        from flinttrade_historical.expiry_collector import ExpiryDataCollector

        mock_client = MagicMock()
        collector = ExpiryDataCollector(mock_client, data_dir=str(tmp_path))

        default_bars = bars or [
            OHLCV(
                timestamp=f"2026-01-{d:02d}T09:15:00",
                open=22000.0 + d, high=22100.0 + d,
                low=21900.0 + d, close=22050.0 + d,
                volume=10000 * d,
            )
            for d in range(1, 6)
        ]

        mock_result = DownloadResult(
            symbol="NIFTY", exchange="NFO", interval="D",
            start_date="2025-12-27", end_date="2026-03-27",
            bars=default_bars, chunks_fetched=1,
        )
        collector._downloader.download = MagicMock(return_value=mock_result)
        return collector

    def test_download_returns_records(self, tmp_path):
        collector = self._make_collector(tmp_path)
        result = collector.download_expiry_data("NIFTY", "260327", days_before=90)
        assert result.total_bars == 5
        assert result.success
        assert result.symbol == "NIFTY"
        assert result.expiry == "260327"

    def test_download_caches_result(self, tmp_path):
        collector = self._make_collector(tmp_path)
        result1 = collector.download_expiry_data("NIFTY", "260327")
        result2 = collector.download_expiry_data("NIFTY", "260327")
        assert result1 is result2
        # Downloader should only be called once
        assert collector._downloader.download.call_count == 1

    def test_invalid_expiry_format(self, tmp_path):
        collector = self._make_collector(tmp_path)
        result = collector.download_expiry_data("NIFTY", "invalid")
        assert not result.success
        assert len(result.errors) > 0
        assert "Invalid expiry" in result.errors[0]


# ======================================================================
# export_csv — file output
# ======================================================================


class TestExportCsv:
    """Test CSV export."""

    def test_exports_csv_file(self, tmp_path):
        from flinttrade_core.models import OHLCV
        from flinttrade_historical.downloader import DownloadResult
        from flinttrade_historical.expiry_collector import ExpiryDataCollector

        mock_client = MagicMock()
        collector = ExpiryDataCollector(mock_client, data_dir=str(tmp_path))

        bars = [
            OHLCV(
                timestamp="2026-01-15T09:15:00",
                open=22000.0, high=22100.0, low=21900.0,
                close=22050.0, volume=10000,
            ),
        ]
        mock_result = DownloadResult(
            symbol="NIFTY", exchange="NFO", interval="D",
            start_date="2025-12-27", end_date="2026-03-27",
            bars=bars, chunks_fetched=1,
        )
        collector._downloader.download = MagicMock(return_value=mock_result)

        csv_path = collector.export_csv("NIFTY", "260327")
        assert csv_path.exists()
        content = csv_path.read_text()
        assert "timestamp,open,high,low,close,volume" in content
        assert "22000.0" in content

    def test_csv_creates_symbol_directory(self, tmp_path):
        from flinttrade_historical.downloader import DownloadResult
        from flinttrade_historical.expiry_collector import ExpiryDataCollector

        mock_client = MagicMock()
        collector = ExpiryDataCollector(mock_client, data_dir=str(tmp_path))
        collector._downloader.download = MagicMock(
            return_value=DownloadResult(
                symbol="BANKNIFTY", exchange="NFO", interval="D",
                start_date="2025-12-27", end_date="2026-03-27",
                bars=[], chunks_fetched=0,
            ),
        )

        collector.export_csv("BANKNIFTY", "260327")
        assert (tmp_path / "BANKNIFTY").is_dir()


# ======================================================================
# export_json — file output
# ======================================================================


class TestExportJson:
    """Test JSON export."""

    def test_exports_json_file(self, tmp_path):
        from flinttrade_core.models import OHLCV
        from flinttrade_historical.downloader import DownloadResult
        from flinttrade_historical.expiry_collector import ExpiryDataCollector

        mock_client = MagicMock()
        collector = ExpiryDataCollector(mock_client, data_dir=str(tmp_path))

        bars = [
            OHLCV(
                timestamp="2026-01-15T09:15:00",
                open=22000.0, high=22100.0, low=21900.0,
                close=22050.0, volume=10000,
            ),
        ]
        collector._downloader.download = MagicMock(
            return_value=DownloadResult(
                symbol="NIFTY", exchange="NFO", interval="D",
                start_date="2025-12-27", end_date="2026-03-27",
                bars=bars, chunks_fetched=1,
            ),
        )

        json_path = collector.export_json("NIFTY", "260327")
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert data["symbol"] == "NIFTY"
        assert data["expiry"] == "260327"
        assert data["total_bars"] == 1
        assert len(data["records"]) == 1
        assert data["records"][0]["open"] == 22000.0


# ======================================================================
# collect_all — batch collection
# ======================================================================


class TestCollectAll:
    """Test batch collection across multiple symbols."""

    def test_collect_all_default_symbols(self, tmp_path):
        from flinttrade_historical.expiry_collector import ExpiryDataCollector
        from flinttrade_historical.expiry_manager import ExpiryInfo

        mock_client = MagicMock()
        collector = ExpiryDataCollector(mock_client, data_dir=str(tmp_path))

        # Mock no expiries — should still return empty lists per symbol
        mock_info = ExpiryInfo(symbol="", exchange="NFO", expiry_dates=[])
        collector._expiry_mgr.get_expiries = MagicMock(return_value=mock_info)

        results = collector.collect_all()
        assert "NIFTY" in results
        assert "BANKNIFTY" in results
        assert results["NIFTY"] == []

    def test_collect_all_custom_symbols(self, tmp_path):
        from flinttrade_historical.expiry_collector import ExpiryDataCollector
        from flinttrade_historical.expiry_manager import ExpiryInfo

        mock_client = MagicMock()
        collector = ExpiryDataCollector(mock_client, data_dir=str(tmp_path))

        mock_info = ExpiryInfo(symbol="", exchange="NFO", expiry_dates=[])
        collector._expiry_mgr.get_expiries = MagicMock(return_value=mock_info)

        results = collector.collect_all(symbols=["RELIANCE"])
        assert "RELIANCE" in results
        assert "NIFTY" not in results
