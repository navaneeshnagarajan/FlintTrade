"""Tests for DownloadWatchlist.

Run with:
    python -m pytest packages/core/historical/tests/test_watchlist.py -v --import-mode=importlib
"""
from __future__ import annotations

import pytest


class TestWatchlistItem:
    """Test the WatchlistItem dataclass defaults."""

    def test_defaults(self):
        from flinttrade_historical.watchlist import WatchlistItem
        item = WatchlistItem(symbol="NIFTY", exchange="NSE_INDEX")
        assert item.interval == "1d"
        assert item.enabled is True


class TestDownloadWatchlist:
    """Test DownloadWatchlist CRUD operations."""

    @pytest.fixture()
    def wl(self, tmp_path):
        from flinttrade_historical.watchlist import DownloadWatchlist
        watchlist = DownloadWatchlist(tmp_path / "watchlist.db")
        yield watchlist
        watchlist.close()

    def test_add_returns_item(self, wl):
        item = wl.add("RELIANCE", "NSE", "1d")
        assert item.symbol == "RELIANCE"
        assert item.exchange == "NSE"
        assert item.interval == "1d"
        assert item.enabled is True

    def test_add_normalizes_to_uppercase(self, wl):
        item = wl.add("nifty", "nse_index", "15m")
        assert item.symbol == "NIFTY"
        assert item.exchange == "NSE_INDEX"

    def test_list_items_empty(self, wl):
        assert wl.list_items() == []

    def test_list_items_after_add(self, wl):
        wl.add("SBIN", "NSE")
        wl.add("INFY", "NSE", "5m")
        items = wl.list_items()
        assert len(items) == 2

    def test_remove_item(self, wl):
        wl.add("TCS", "NSE")
        wl.remove("TCS", "NSE")
        assert wl.list_items() == []

    def test_remove_case_insensitive(self, wl):
        wl.add("HDFC", "NSE")
        wl.remove("hdfc", "nse")
        assert wl.list_items() == []

    def test_toggle_disable(self, wl):
        wl.add("WIPRO", "NSE")
        wl.toggle("WIPRO", "NSE", enabled=False)
        items = wl.list_items()
        assert items[0].enabled is False

    def test_toggle_reenable(self, wl):
        wl.add("HCL", "NSE")
        wl.toggle("HCL", "NSE", enabled=False)
        wl.toggle("HCL", "NSE", enabled=True)
        items = wl.list_items()
        assert items[0].enabled is True

    def test_get_enabled_filters(self, wl):
        wl.add("ONGC", "NSE")
        wl.add("COALINDIA", "NSE")
        wl.toggle("COALINDIA", "NSE", enabled=False)
        enabled = wl.get_enabled()
        assert len(enabled) == 1
        assert enabled[0].symbol == "ONGC"

    def test_add_updates_interval_on_conflict(self, wl):
        wl.add("ITC", "NSE", "1d")
        wl.add("ITC", "NSE", "5m")
        items = wl.list_items()
        assert len(items) == 1
        assert items[0].interval == "5m"

    def test_persistence_survives_reopen(self, tmp_path):
        from flinttrade_historical.watchlist import DownloadWatchlist
        db = tmp_path / "persist.db"
        wl1 = DownloadWatchlist(db)
        wl1.add("BAJFINANCE", "NSE")
        wl1.close()

        wl2 = DownloadWatchlist(db)
        items = wl2.list_items()
        wl2.close()
        assert len(items) == 1
        assert items[0].symbol == "BAJFINANCE"
