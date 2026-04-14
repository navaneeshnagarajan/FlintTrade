"""Tests for PnLTracker.

Run with:
    python -m pytest packages/data/tests/test_pnl_tracker.py -v --import-mode=importlib
"""
from __future__ import annotations

import time

import pytest


class TestPnLPoint:
    """Test the PnLPoint dataclass."""

    def test_fields_exist(self):
        from packages.data.src.pnl_tracker import PnLPoint

        p = PnLPoint(timestamp=1.0, realized_pnl=100.0, unrealized_pnl=50.0, total_pnl=150.0, trade_count=3)
        assert p.timestamp == 1.0
        assert p.realized_pnl == 100.0
        assert p.unrealized_pnl == 50.0
        assert p.total_pnl == 150.0
        assert p.trade_count == 3


class TestPnLTracker:
    """Test PnLTracker logic."""

    def _make_tracker(self):
        from packages.data.src.pnl_tracker import PnLTracker
        return PnLTracker()  # in-memory only

    def test_initial_state_empty(self):
        tracker = self._make_tracker()
        assert tracker.get_series() == []

    def test_update_realized_pnl_buy(self):
        """BUY trade: realized = (exit - entry) * qty."""
        tracker = self._make_tracker()
        trades = [
            {"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY",
             "quantity": 10, "entry_price": 2500.0, "exit_price": 2520.0},
        ]
        point = tracker.update(trades, [], {})
        assert point.realized_pnl == pytest.approx(200.0)
        assert point.unrealized_pnl == 0.0
        assert point.total_pnl == pytest.approx(200.0)
        assert point.trade_count == 1

    def test_update_realized_pnl_sell(self):
        """SELL (short) trade: realized = (entry - exit) * qty."""
        tracker = self._make_tracker()
        trades = [
            {"symbol": "NIFTY24APR23000CE", "exchange": "NFO", "action": "SELL",
             "quantity": 50, "entry_price": 200.0, "exit_price": 150.0},
        ]
        point = tracker.update(trades, [], {})
        assert point.realized_pnl == pytest.approx(2500.0)
        assert point.trade_count == 1

    def test_update_unrealized_pnl(self):
        """Open position MTM from LTP map."""
        tracker = self._make_tracker()
        positions = [
            {"symbol": "INFY", "exchange": "NSE", "quantity": 5, "average_price": 1800.0},
        ]
        ltp_map = {"NSE:INFY": 1820.0}
        point = tracker.update([], positions, ltp_map)
        assert point.unrealized_pnl == pytest.approx(100.0)  # (1820-1800)*5
        assert point.realized_pnl == 0.0

    def test_update_ltp_map_bare_symbol_fallback(self):
        """Falls back to bare symbol key when exchange:symbol key not present."""
        tracker = self._make_tracker()
        positions = [
            {"symbol": "SBIN", "exchange": "NSE", "quantity": 10, "average_price": 600.0},
        ]
        ltp_map = {"SBIN": 610.0}
        point = tracker.update([], positions, ltp_map)
        assert point.unrealized_pnl == pytest.approx(100.0)

    def test_update_skips_trade_without_prices(self):
        """Trade with missing entry_price/exit_price is not counted."""
        tracker = self._make_tracker()
        trades = [{"symbol": "TCS", "exchange": "NSE", "action": "BUY", "quantity": 5}]
        point = tracker.update(trades, [], {})
        assert point.realized_pnl == 0.0
        assert point.trade_count == 0

    def test_get_series_returns_all_points(self):
        tracker = self._make_tracker()
        tracker.update([], [], {})
        tracker.update([], [], {})
        assert len(tracker.get_series()) == 2

    def test_get_series_since_filter(self):
        tracker = self._make_tracker()
        tracker.update([], [], {})
        # Use the first point's timestamp + small epsilon so only the
        # second point passes the filter (avoids Windows timer resolution issues).
        first_ts = tracker.get_series()[-1].timestamp
        tracker.update([], [], {})
        series = tracker.get_series(since=first_ts + 1e-6)
        assert len(series) == 1

    def test_get_summary_empty(self):
        tracker = self._make_tracker()
        summary = tracker.get_summary()
        assert summary["total"] == 0.0
        assert summary["data_points"] == 0

    def test_get_summary_populated(self):
        tracker = self._make_tracker()
        trades = [
            {"action": "BUY", "quantity": 10, "entry_price": 100.0, "exit_price": 110.0},
        ]
        tracker.update(trades, [], {})
        summary = tracker.get_summary()
        assert summary["realized"] == pytest.approx(100.0)
        assert summary["total"] == pytest.approx(100.0)
        assert summary["max_total"] == pytest.approx(100.0)
        assert summary["trade_count"] == 1
        assert summary["data_points"] == 1

    def test_reset_clears_series(self):
        tracker = self._make_tracker()
        tracker.update([], [], {})
        tracker.reset()
        assert tracker.get_series() == []
