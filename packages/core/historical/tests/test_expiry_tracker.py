"""Tests for ExpiryTracker — option chain snapshot capture and retrieval.

Uses in-memory DuckDB. OpenAlgo client is mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Capture and retrieve snapshot
# ---------------------------------------------------------------------------


class TestCaptureSnapshot:
    def _tracker(self, client=None):
        from flinttrade_historical.expiry_tracker import ExpiryTracker
        return ExpiryTracker(client=client, db_path=":memory:")

    def test_capture_stores_rows_in_duckdb(self):
        client = MagicMock()
        client.optionchain.return_value = [
            {
                "strike_price": 24000,
                "call_oi": 100000, "call_volume": 5000, "call_ltp": 150.5, "call_iv": 12.5,
                "put_oi": 80000, "put_volume": 4000, "put_ltp": 120.0, "put_iv": 13.0,
            },
            {
                "strike_price": 24100,
                "call_oi": 90000, "call_volume": 4500, "call_ltp": 100.0, "call_iv": 11.0,
                "put_oi": 70000, "put_volume": 3500, "put_ltp": 160.0, "put_iv": 14.0,
            },
        ]
        tracker = self._tracker(client)
        count = tracker.capture_snapshot("NIFTY", "260326")
        # 2 strikes x 2 option types = 4 rows
        assert count == 4

    def test_retrieve_after_capture(self):
        client = MagicMock()
        client.optionchain.return_value = [
            {
                "strike_price": 24000,
                "call_oi": 100000, "call_volume": 5000, "call_ltp": 150.5, "call_iv": 12.5,
                "put_oi": 80000, "put_volume": 4000, "put_ltp": 120.0, "put_iv": 13.0,
            },
        ]
        tracker = self._tracker(client)
        tracker.capture_snapshot("NIFTY", "260326")

        chain = tracker.get_historical_chain("NIFTY", "260326")
        assert len(chain) == 2  # CE + PE
        ce_row = [r for r in chain if r["option_type"] == "CE"][0]
        assert ce_row["strike"] == 24000
        assert ce_row["oi"] == 100000
        assert ce_row["ltp"] == 150.5

        pe_row = [r for r in chain if r["option_type"] == "PE"][0]
        assert pe_row["strike"] == 24000
        assert pe_row["oi"] == 80000

    def test_capture_with_no_client_returns_zero(self):
        tracker = self._tracker(client=None)
        count = tracker.capture_snapshot("NIFTY", "260326")
        assert count == 0

    def test_capture_with_empty_response_returns_zero(self):
        client = MagicMock()
        client.optionchain.return_value = []
        tracker = self._tracker(client)
        count = tracker.capture_snapshot("NIFTY", "260326")
        assert count == 0

    def test_capture_handles_api_error(self):
        client = MagicMock()
        client.optionchain.side_effect = Exception("API timeout")
        tracker = self._tracker(client)
        count = tracker.capture_snapshot("NIFTY", "260326")
        assert count == 0


# ---------------------------------------------------------------------------
# List expiries
# ---------------------------------------------------------------------------


class TestListExpiries:
    def _tracker_with_data(self):
        from flinttrade_historical.expiry_tracker import ExpiryTracker
        client = MagicMock()
        tracker = ExpiryTracker(client=client, db_path=":memory:")

        # Insert data for two expiries
        client.optionchain.return_value = [
            {"strike_price": 24000, "call_oi": 100, "call_volume": 50,
             "call_ltp": 150, "call_iv": 12, "put_oi": 80, "put_volume": 40,
             "put_ltp": 120, "put_iv": 13},
        ]
        tracker.capture_snapshot("NIFTY", "260326")
        tracker.capture_snapshot("NIFTY", "260402")
        return tracker

    def test_list_returns_all_expiries(self):
        tracker = self._tracker_with_data()
        expiries = tracker.list_expiries("NIFTY")
        assert "260326" in expiries
        assert "260402" in expiries
        assert len(expiries) == 2

    def test_list_returns_sorted(self):
        tracker = self._tracker_with_data()
        expiries = tracker.list_expiries("NIFTY")
        assert expiries == sorted(expiries)

    def test_list_empty_for_unknown_symbol(self):
        tracker = self._tracker_with_data()
        expiries = tracker.list_expiries("UNKNOWN")
        assert expiries == []


# ---------------------------------------------------------------------------
# get_historical_chain — empty result
# ---------------------------------------------------------------------------


class TestGetHistoricalChainEmpty:
    def test_empty_when_no_data(self):
        from flinttrade_historical.expiry_tracker import ExpiryTracker
        tracker = ExpiryTracker(client=None, db_path=":memory:")
        chain = tracker.get_historical_chain("NIFTY", "260326")
        assert chain == []


# ---------------------------------------------------------------------------
# Parse option chain — alternate key formats
# ---------------------------------------------------------------------------


class TestParseOptionChain:
    def test_parse_nested_dict_response(self):
        from flinttrade_historical.expiry_tracker import ExpiryTracker
        data = {
            "data": [
                {"strike": 24000, "ce_oi": 100, "ce_volume": 50,
                 "ce_ltp": 150, "ce_iv": 12, "pe_oi": 80, "pe_volume": 40,
                 "pe_ltp": 120, "pe_iv": 13},
            ],
        }
        rows = ExpiryTracker._parse_option_chain(data, "NIFTY", "NFO", "260326")
        assert len(rows) == 2
        assert rows[0]["option_type"] == "CE"
        assert rows[1]["option_type"] == "PE"

    def test_parse_skips_zero_strike(self):
        from flinttrade_historical.expiry_tracker import ExpiryTracker
        data = [
            {"strike_price": 0, "call_oi": 100, "call_volume": 50,
             "call_ltp": 150, "call_iv": 12, "put_oi": 80, "put_volume": 40,
             "put_ltp": 120, "put_iv": 13},
        ]
        rows = ExpiryTracker._parse_option_chain(data, "NIFTY", "NFO", "260326")
        assert len(rows) == 0


# ---------------------------------------------------------------------------
# ExpiryFlow-adapted features: rate limiter, metadata, bulk capture
# ---------------------------------------------------------------------------


class TestSnapshotRateLimiter:
    """Verify the rate limiter adapted from ExpiryFlow."""

    def test_rate_limiter_allows_burst(self):
        from flinttrade_historical.expiry_tracker import SnapshotRateLimiter
        limiter = SnapshotRateLimiter(max_per_second=10)
        # Should not raise for a small burst
        for _ in range(5):
            limiter.wait_if_needed()
        assert limiter.requests_today == 5

    def test_rate_limiter_daily_limit_raises(self):
        import pytest
        from flinttrade_historical.expiry_tracker import SnapshotRateLimiter
        limiter = SnapshotRateLimiter(max_per_second=100, max_per_day=3)
        limiter.wait_if_needed()
        limiter.wait_if_needed()
        limiter.wait_if_needed()
        with pytest.raises(RuntimeError, match="Daily API limit"):
            limiter.wait_if_needed()


class TestDownloadMetadata:
    """Verify download metadata tracking adapted from ExpiryFlow."""

    def _tracker(self, client=None):
        from flinttrade_historical.expiry_tracker import ExpiryTracker
        return ExpiryTracker(client=client, db_path=":memory:")

    def test_has_snapshot_false_when_empty(self):
        tracker = self._tracker()
        assert tracker.has_snapshot("NIFTY", "260326") is False

    def test_has_snapshot_true_after_capture(self):
        client = MagicMock()
        client.optionchain.return_value = [
            {"strike_price": 24000, "call_oi": 100, "call_volume": 50,
             "call_ltp": 150, "call_iv": 12, "put_oi": 80, "put_volume": 40,
             "put_ltp": 120, "put_iv": 13},
        ]
        tracker = self._tracker(client)
        tracker.capture_snapshot("NIFTY", "260326")
        assert tracker.has_snapshot("NIFTY", "260326") is True

    def test_get_download_history(self):
        client = MagicMock()
        client.optionchain.return_value = [
            {"strike_price": 24000, "call_oi": 100, "call_volume": 50,
             "call_ltp": 150, "call_iv": 12, "put_oi": 80, "put_volume": 40,
             "put_ltp": 120, "put_iv": 13},
        ]
        tracker = self._tracker(client)
        tracker.capture_snapshot("NIFTY", "260326")
        history = tracker.get_download_history()
        assert len(history) == 1
        assert history[0]["symbol"] == "NIFTY"
        assert history[0]["row_count"] == 2


class TestBulkCapture:
    """Verify bulk capture with skip-existing adapted from ExpiryFlow."""

    def test_capture_multiple_skips_existing(self):
        client = MagicMock()
        client.optionchain.return_value = [
            {"strike_price": 24000, "call_oi": 100, "call_volume": 50,
             "call_ltp": 150, "call_iv": 12, "put_oi": 80, "put_volume": 40,
             "put_ltp": 120, "put_iv": 13},
        ]
        from flinttrade_historical.expiry_tracker import ExpiryTracker
        tracker = ExpiryTracker(client=client, db_path=":memory:")

        # Capture first expiry
        tracker.capture_snapshot("NIFTY", "260326")

        # Bulk capture should skip the first and only fetch the second
        results = tracker.capture_multiple("NIFTY", ["260326", "260402"])
        assert results["260326"] == 0  # skipped
        assert results["260402"] == 2  # 1 strike x 2 types

    def test_capture_multiple_no_skip(self):
        client = MagicMock()
        client.optionchain.return_value = [
            {"strike_price": 24000, "call_oi": 100, "call_volume": 50,
             "call_ltp": 150, "call_iv": 12, "put_oi": 80, "put_volume": 40,
             "put_ltp": 120, "put_iv": 13},
        ]
        from flinttrade_historical.expiry_tracker import ExpiryTracker
        tracker = ExpiryTracker(client=client, db_path=":memory:")
        results = tracker.capture_multiple("NIFTY", ["260326", "260402"], skip_existing=False)
        assert results["260326"] == 2
        assert results["260402"] == 2
