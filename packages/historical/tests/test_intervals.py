"""Tests for the intervals module.

Run with:
    python -m pytest packages/historical/tests/test_intervals.py -v --import-mode=importlib
"""
from __future__ import annotations



class TestGetIntervals:
    """Tests for get_intervals()."""

    def test_known_broker_returns_list(self):
        from packages.historical.src.intervals import get_intervals
        result = get_intervals("zerodha")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_contains_1d(self):
        from packages.historical.src.intervals import get_intervals
        assert "1d" in get_intervals("zerodha")

    def test_case_insensitive(self):
        from packages.historical.src.intervals import get_intervals
        assert get_intervals("Zerodha") == get_intervals("zerodha")
        assert get_intervals("ANGEL") == get_intervals("angel")

    def test_unknown_broker_returns_defaults(self):
        from packages.historical.src.intervals import get_intervals
        result = get_intervals("nonexistent_broker_xyz")
        assert isinstance(result, list)
        assert len(result) > 0
        assert "1d" in result

    def test_returns_new_list_each_call(self):
        from packages.historical.src.intervals import get_intervals
        a = get_intervals("zerodha")
        b = get_intervals("zerodha")
        assert a is not b  # defensive copy

    def test_all_registered_brokers_have_1d(self):
        from packages.historical.src.intervals import (
            SUPPORTED_INTERVALS_PER_BROKER,
            get_intervals,
        )
        for broker in SUPPORTED_INTERVALS_PER_BROKER:
            assert "1d" in get_intervals(broker), f"{broker} missing 1d"


class TestIsSupported:
    """Tests for is_supported()."""

    def test_supported_interval_returns_true(self):
        from packages.historical.src.intervals import is_supported
        assert is_supported("zerodha", "1m") is True
        assert is_supported("zerodha", "1d") is True

    def test_unsupported_interval_returns_false(self):
        from packages.historical.src.intervals import is_supported
        assert is_supported("zerodha", "2h") is False  # not in zerodha's list

    def test_unknown_broker_uses_defaults(self):
        from packages.historical.src.intervals import is_supported
        assert is_supported("phantom_broker", "1d") is True

    def test_unknown_interval_returns_false(self):
        from packages.historical.src.intervals import is_supported
        assert is_supported("zerodha", "999d") is False


class TestGetCommonIntervals:
    """Tests for get_common_intervals()."""

    def test_single_broker_returns_its_intervals(self):
        from packages.historical.src.intervals import get_common_intervals, get_intervals
        result = get_common_intervals(["zerodha"])
        assert result == get_intervals("zerodha")

    def test_two_brokers_returns_intersection(self):
        from packages.historical.src.intervals import (
            get_common_intervals,
            get_intervals,
        )
        result = get_common_intervals(["zerodha", "hdfc"])
        hdfc = set(get_intervals("hdfc"))
        for iv in result:
            assert iv in hdfc, f"{iv} not in hdfc intervals"

    def test_empty_list_returns_defaults(self):
        from packages.historical.src.intervals import get_common_intervals
        result = get_common_intervals([])
        assert isinstance(result, list)
        assert "1d" in result

    def test_all_brokers_share_1d(self):
        from packages.historical.src.intervals import (
            SUPPORTED_INTERVALS_PER_BROKER,
            get_common_intervals,
        )
        all_brokers = list(SUPPORTED_INTERVALS_PER_BROKER.keys())
        common = get_common_intervals(all_brokers)
        assert "1d" in common

    def test_order_preserves_first_broker_order(self):
        from packages.historical.src.intervals import get_common_intervals, get_intervals
        result = get_common_intervals(["zerodha", "angel"])
        zerodha = get_intervals("zerodha")
        # All elements in result appear in zerodha's order
        positions = [zerodha.index(iv) for iv in result if iv in zerodha]
        assert positions == sorted(positions)


class TestListBrokers:
    """Tests for list_brokers()."""

    def test_returns_sorted_list(self):
        from packages.historical.src.intervals import list_brokers
        brokers = list_brokers()
        assert brokers == sorted(brokers)

    def test_includes_known_brokers(self):
        from packages.historical.src.intervals import list_brokers
        brokers = list_brokers()
        for expected in ("zerodha", "angel", "fyers", "upstox"):
            assert expected in brokers
