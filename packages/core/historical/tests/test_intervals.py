"""Tests for the intervals module.

Run with:
    python -m pytest packages/core/historical/tests/test_intervals.py -v --import-mode=importlib
"""

from __future__ import annotations


class TestGetIntervals:
    """Tests for get_intervals()."""

    def test_known_broker_returns_list(self):
        from flinttrade_historical.intervals import get_intervals

        result = get_intervals("dhan")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_contains_1d(self):
        from flinttrade_historical.intervals import get_intervals

        assert "1d" in get_intervals("dhan")

    def test_case_insensitive(self):
        from flinttrade_historical.intervals import get_intervals

        assert get_intervals("Dhan") == get_intervals("dhan")
        assert get_intervals("UPSTOX") == get_intervals("upstox")

    def test_unknown_broker_returns_defaults(self):
        from flinttrade_historical.intervals import get_intervals

        result = get_intervals("nonexistent_broker_xyz")
        assert isinstance(result, list)
        assert result == []

    def test_returns_new_list_each_call(self):
        from flinttrade_historical.intervals import get_intervals

        a = get_intervals("dhan")
        b = get_intervals("dhan")
        assert a is not b  # defensive copy

    def test_all_registered_brokers_have_1d(self):
        from flinttrade_historical.intervals import (
            SUPPORTED_INTERVALS_PER_BROKER,
            get_intervals,
        )

        for broker in SUPPORTED_INTERVALS_PER_BROKER:
            assert "1d" in get_intervals(broker), f"{broker} missing 1d"


class TestIsSupported:
    """Tests for is_supported()."""

    def test_supported_interval_returns_true(self):
        from flinttrade_historical.intervals import is_supported

        assert is_supported("dhan", "1m") is True
        assert is_supported("dhan", "1d") is True

    def test_unsupported_interval_returns_false(self):
        from flinttrade_historical.intervals import is_supported

        assert is_supported("dhan", "2h") is False  # not in dhan's list

    def test_unknown_broker_uses_defaults(self):
        from flinttrade_historical.intervals import is_supported

        assert is_supported("phantom_broker", "1d") is False

    def test_unknown_interval_returns_false(self):
        from flinttrade_historical.intervals import is_supported

        assert is_supported("dhan", "999d") is False


class TestGetCommonIntervals:
    """Tests for get_common_intervals()."""

    def test_single_broker_returns_its_intervals(self):
        from flinttrade_historical.intervals import get_common_intervals, get_intervals

        result = get_common_intervals(["dhan"])
        assert result == get_intervals("dhan")

    def test_two_brokers_returns_intersection(self):
        from flinttrade_historical.intervals import (
            get_common_intervals,
            get_intervals,
        )

        result = get_common_intervals(["dhan", "kotakneo"])
        kotakneo = set(get_intervals("kotakneo"))
        for iv in result:
            assert iv in kotakneo, f"{iv} not in kotakneo intervals"

    def test_empty_list_returns_defaults(self):
        from flinttrade_historical.intervals import get_common_intervals

        result = get_common_intervals([])
        assert isinstance(result, list)
        assert result == []

    def test_all_brokers_share_1d(self):
        from flinttrade_historical.intervals import (
            SUPPORTED_INTERVALS_PER_BROKER,
            get_common_intervals,
        )

        all_brokers = list(SUPPORTED_INTERVALS_PER_BROKER.keys())
        common = get_common_intervals(all_brokers)
        assert "1d" in common

    def test_order_preserves_first_broker_order(self):
        from flinttrade_historical.intervals import get_common_intervals, get_intervals

        result = get_common_intervals(["dhan", "upstox"])
        dhan = get_intervals("dhan")
        # All elements in result appear in dhan's order
        positions = [dhan.index(iv) for iv in result if iv in dhan]
        assert positions == sorted(positions)


class TestListBrokers:
    """Tests for list_brokers()."""

    def test_returns_sorted_list(self):
        from flinttrade_historical.intervals import list_brokers

        brokers = list_brokers()
        assert brokers == sorted(brokers)

    def test_includes_known_brokers(self):
        from flinttrade_historical.intervals import list_brokers

        brokers = list_brokers()
        for expected in ("dhan", "upstox", "groww", "upstox"):
            assert expected in brokers
