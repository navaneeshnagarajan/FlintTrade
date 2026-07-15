"""Tests for OrderFlowAggregator — per-symbol footprint aggregation.

All tests are pure in-memory and require no external connections.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone

import pytest


# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------


def _make_agg(time_bin_seconds: int = 300, tick_size: float = 50.0):
    from flinttrade_data.orderflow_aggregator import OrderFlowAggregator

    return OrderFlowAggregator(time_bin_seconds=time_bin_seconds, tick_size=tick_size)


# 2026-03-25 09:15:00 IST → Unix 1742870700
# This falls exactly on a 5-min bin boundary anchored to 09:15 IST.
_BASE_TS = 1742870700.0


# ===========================================================================
# Constructor validation
# ===========================================================================


class TestConstructorValidation:
    def test_zero_bin_seconds_raises(self):
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator

        with pytest.raises(ValueError, match="time_bin_seconds"):
            OrderFlowAggregator(time_bin_seconds=0)

    def test_negative_bin_seconds_raises(self):
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator

        with pytest.raises(ValueError, match="time_bin_seconds"):
            OrderFlowAggregator(time_bin_seconds=-60)

    def test_zero_tick_size_raises(self):
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator

        with pytest.raises(ValueError, match="tick_size"):
            OrderFlowAggregator(tick_size=0.0)

    def test_negative_tick_size_raises(self):
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator

        with pytest.raises(ValueError, match="tick_size"):
            OrderFlowAggregator(tick_size=-0.05)

    @pytest.mark.parametrize(
        "tick_size",
        [float("nan"), float("inf"), float("-inf"), 1e308, 1e-320],
        ids=["nan", "positive-infinity", "negative-infinity", "overflow-prone", "underflow-prone"],
    )
    def test_non_finite_or_arithmetic_unsafe_tick_size_raises(self, tick_size):
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator

        with pytest.raises(ValueError, match="tick_size"):
            OrderFlowAggregator(tick_size=tick_size)

    def test_default_parameters(self):
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator

        agg = OrderFlowAggregator()
        assert agg.time_bin_seconds == 60
        assert agg.tick_size == 0.05

    def test_live_market_factory_uses_precise_shared_ingestion_grid_without_changing_analytics_default(self):
        from flinttrade_data.orderflow_aggregator import (
            LIVE_MARKET_INGESTION_INTERVAL_SECONDS,
            LIVE_MARKET_INGESTION_TICK_SIZE,
            OrderFlowAggregator,
            create_live_market_orderflow_aggregator,
        )

        live = create_live_market_orderflow_aggregator()

        assert LIVE_MARKET_INGESTION_INTERVAL_SECONDS == 60
        assert LIVE_MARKET_INGESTION_TICK_SIZE == 0.0001
        assert live.time_bin_seconds == LIVE_MARKET_INGESTION_INTERVAL_SECONDS
        assert live.tick_size == LIVE_MARKET_INGESTION_TICK_SIZE
        assert OrderFlowAggregator().tick_size == 0.05

    def test_one_live_market_aggregator_preserves_distinct_levels_across_instrument_granularities(self):
        from flinttrade_data.orderflow_aggregator import create_live_market_orderflow_aggregator

        agg = create_live_market_orderflow_aggregator()
        instruments = (
            ("EURUSD", "CDS", 1.0840, 1.0841),
            ("USDINR", "CDS", 83.0000, 83.0025),
            ("CRUDEOIL", "MCX", 6500.0, 6501.0),
            ("RELIANCE", "NSE", 2500.00, 2500.01),
        )

        for symbol, exchange, first_price, second_price in instruments:
            agg.add_tick(symbol, first_price, 10, "BUY", timestamp=_BASE_TS, exchange=exchange)
            agg.add_tick(symbol, second_price, 20, "SELL", timestamp=_BASE_TS + 1, exchange=exchange)

        for symbol, exchange, first_price, second_price in instruments:
            levels = {round(bucket.price_level, 4) for bucket in agg.get_footprint(symbol, exchange=exchange)}
            assert levels == {round(first_price, 4), round(second_price, 4)}

    def test_global_identity_retention_bounds_all_state_maps(self):
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator

        agg = OrderFlowAggregator(max_instruments=3)
        for index in range(10):
            symbol = f"SYM{index}"
            agg.add_tick(symbol, 100.0, 1, "BUY", timestamp=_BASE_TS + index, exchange="NSE")
            agg.feed_market_tick(
                symbol,
                100.0,
                100,
                timestamp=_BASE_TS + index,
                exchange="NSE",
            )

        assert len(agg._state) == 3
        assert len(agg._last_tick) == 3
        assert len(agg._identity_recency) == 3
        assert set(agg._state) == {("NSE", "SYM7"), ("NSE", "SYM8"), ("NSE", "SYM9")}


# ===========================================================================
# add_tick — basic accumulation
# ===========================================================================


class TestAddTick:
    def test_add_tick_returns_bin_start(self):
        agg = _make_agg()
        bin_start = agg.add_tick("NIFTY", 24500.0, 100, "BUY", timestamp=_BASE_TS)
        assert isinstance(bin_start, int)

    def test_add_tick_invalid_side_raises(self):
        agg = _make_agg()
        with pytest.raises(ValueError, match="side"):
            agg.add_tick("NIFTY", 24500.0, 100, "HOLD", timestamp=_BASE_TS)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "volume",
        [True, False, 1.5, float("nan"), float("inf"), -1, 2**53],
        ids=["true", "false", "fractional", "nan", "infinity", "negative", "unsafe-integer"],
    )
    def test_add_tick_rejects_non_exact_or_unsafe_volume(self, volume):
        agg = _make_agg(tick_size=50.0)

        with pytest.raises(ValueError, match="volume"):
            agg.add_tick("NIFTY", 24500.0, volume, "BUY", timestamp=_BASE_TS)

        assert agg.get_footprint("NIFTY") == []

    def test_add_tick_accepts_an_exact_integral_float_without_truncation(self):
        agg = _make_agg(tick_size=50.0)

        agg.add_tick("NIFTY", 24500.0, 10.0, "BUY", timestamp=_BASE_TS)

        assert sum(bucket.total_volume for bucket in agg.get_footprint("NIFTY")) == 10

    def test_zero_volume_exact_tick_does_not_create_data_or_freshness(self):
        agg = _make_agg(tick_size=50.0)

        agg.add_tick("NIFTY", 24500.0, 0, "BUY", timestamp=_BASE_TS)

        assert agg.get_footprint("NIFTY") == []
        assert agg.get_market_freshness("NIFTY", now=_BASE_TS + 1)["state"] == "unavailable"

    def test_add_tick_defaults_timestamp_to_now(self):
        import time as _time

        agg = _make_agg()
        before = int(_time.time())
        agg.add_tick("NIFTY", 24500.0, 100, "BUY")
        int(_time.time())
        bins = agg.get_footprint("NIFTY")
        assert len(bins) > 0
        assert bins[0].timestamp_bin >= before - 300  # within same bin window

    def test_add_tick_accumulates_buy_volume(self):
        agg = _make_agg(tick_size=50.0)
        agg.add_tick("NIFTY", 24500.0, 100, "BUY", timestamp=_BASE_TS)
        agg.add_tick("NIFTY", 24500.0, 200, "BUY", timestamp=_BASE_TS + 30)
        bins = agg.get_footprint("NIFTY")
        # Both ticks land at price_level 24500 → buy_volume = 300
        lvl = next(b for b in bins if b.price_level == 24500.0)
        assert lvl.buy_volume == 300
        assert lvl.sell_volume == 0

    def test_add_tick_accumulates_sell_volume(self):
        agg = _make_agg(tick_size=50.0)
        agg.add_tick("NIFTY", 24500.0, 150, "SELL", timestamp=_BASE_TS)
        bins = agg.get_footprint("NIFTY")
        lvl = next(b for b in bins if b.price_level == 24500.0)
        assert lvl.sell_volume == 150
        assert lvl.buy_volume == 0

    def test_add_tick_mixed_sides_at_same_level(self):
        agg = _make_agg(tick_size=50.0)
        agg.add_tick("NIFTY", 24500.0, 200, "BUY", timestamp=_BASE_TS)
        agg.add_tick("NIFTY", 24500.0, 80, "SELL", timestamp=_BASE_TS + 10)
        bins = agg.get_footprint("NIFTY")
        lvl = next(b for b in bins if b.price_level == 24500.0)
        assert lvl.buy_volume == 200
        assert lvl.sell_volume == 80
        assert lvl.delta == 120

    def test_explicit_trade_ticks_are_marked_as_exact(self):
        agg = _make_agg(tick_size=50.0)
        agg.add_tick("NIFTY", 24500.0, 100, "BUY", timestamp=_BASE_TS)

        [bucket] = agg.get_footprint("NIFTY")
        assert bucket.quality == "exact"
        assert bucket.provenance == "trade_tick"


# ===========================================================================
# Per-symbol isolation
# ===========================================================================


class TestPerSymbolIsolation:
    def test_different_symbols_do_not_interfere(self):
        agg = _make_agg(tick_size=50.0)
        agg.add_tick("NIFTY", 24500.0, 100, "BUY", timestamp=_BASE_TS)
        agg.add_tick("BANKNIFTY", 52000.0, 200, "SELL", timestamp=_BASE_TS)

        nifty_bins = agg.get_footprint("NIFTY")
        bn_bins = agg.get_footprint("BANKNIFTY")

        nifty_buy_total = sum(b.buy_volume for b in nifty_bins)
        bn_sell_total = sum(b.sell_volume for b in bn_bins)

        assert nifty_buy_total == 100
        assert bn_sell_total == 200

    def test_unknown_symbol_returns_empty_list(self):
        agg = _make_agg()
        assert agg.get_footprint("UNKNOWNSYMBOL") == []

    def test_reset_single_symbol_preserves_others(self):
        agg = _make_agg(tick_size=50.0)
        agg.add_tick("NIFTY", 24500.0, 100, "BUY", timestamp=_BASE_TS)
        agg.add_tick("BANKNIFTY", 52000.0, 200, "BUY", timestamp=_BASE_TS)

        agg.reset("NIFTY")

        assert agg.get_footprint("NIFTY") == []
        assert len(agg.get_footprint("BANKNIFTY")) > 0

    def test_reset_all_clears_all_symbols(self):
        agg = _make_agg(tick_size=50.0)
        agg.add_tick("NIFTY", 24500.0, 100, "BUY", timestamp=_BASE_TS)
        agg.add_tick("BANKNIFTY", 52000.0, 200, "BUY", timestamp=_BASE_TS)
        agg.reset()
        assert agg.get_footprint("NIFTY") == []
        assert agg.get_footprint("BANKNIFTY") == []


# ===========================================================================
# get_footprint — n_bins limiting
# ===========================================================================


class TestGetFootprint:
    def test_n_bins_limits_to_most_recent_bins(self):
        agg = _make_agg(time_bin_seconds=300, tick_size=50.0)
        # Create 5 distinct bins (one tick each, 5 min apart)
        for i in range(5):
            agg.add_tick("NIFTY", 24500.0, 100, "BUY", timestamp=_BASE_TS + i * 300)

        bins = agg.get_footprint("NIFTY", n_bins=3)
        unique_bins = {b.timestamp_bin for b in bins}
        assert len(unique_bins) == 3

    def test_get_footprint_sorted_oldest_first(self):
        agg = _make_agg(time_bin_seconds=300, tick_size=50.0)
        agg.add_tick("NIFTY", 24500.0, 100, "BUY", timestamp=_BASE_TS)
        agg.add_tick("NIFTY", 24500.0, 100, "BUY", timestamp=_BASE_TS + 300)
        bins = agg.get_footprint("NIFTY")
        timestamps = [b.timestamp_bin for b in bins]
        assert timestamps == sorted(timestamps)

    def test_price_levels_sorted_ascending_within_bin(self):
        agg = _make_agg(time_bin_seconds=300, tick_size=50.0)
        agg.add_tick("NIFTY", 24600.0, 100, "BUY", timestamp=_BASE_TS)
        agg.add_tick("NIFTY", 24400.0, 100, "BUY", timestamp=_BASE_TS + 10)
        agg.add_tick("NIFTY", 24500.0, 100, "BUY", timestamp=_BASE_TS + 20)
        bins = agg.get_footprint("NIFTY")
        prices = [b.price_level for b in bins]
        assert prices == sorted(prices)

    def test_get_footprint_returns_only_the_latest_ist_trading_session(self):
        agg = _make_agg(time_bin_seconds=300, tick_size=50.0)
        previous_session = _BASE_TS
        latest_session = _BASE_TS + 24 * 3600
        agg.add_tick("NIFTY", 24500.0, 900, "SELL", timestamp=previous_session)
        agg.add_tick("NIFTY", 24500.0, 100, "BUY", timestamp=latest_session)

        bins = agg.get_footprint("NIFTY")

        assert {bucket.timestamp_bin for bucket in bins} == {int(latest_session)}
        assert sum(bucket.delta for bucket in bins) == 100

    def test_retained_state_evicts_old_sessions_and_oldest_bins_within_each_session(self):
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator

        agg = OrderFlowAggregator(
            time_bin_seconds=60,
            tick_size=0.05,
            max_retained_sessions=2,
            max_bins_per_session=2,
        )

        for session_offset in range(3):
            for bin_offset in range(3):
                agg.add_tick(
                    "NIFTY",
                    24500.0,
                    100,
                    "BUY",
                    timestamp=_BASE_TS + session_offset * 24 * 3600 + bin_offset * 60,
                    exchange="NFO",
                )

        retained = agg._state[("NFO", "NIFTY")]
        retained_sessions = {
            datetime.fromtimestamp(bin_start, tz=timezone(timedelta(hours=5, minutes=30))).date()
            for bin_start in retained
        }

        assert len(retained) == 4
        assert len(retained_sessions) == 2
        latest = agg.get_footprint("NIFTY", n_bins=10, exchange="NFO")
        assert len({bucket.timestamp_bin for bucket in latest}) == 2


# ===========================================================================
# Price rounding
# ===========================================================================


class TestPriceRounding:
    def test_rounds_to_nearest_50(self):
        agg = _make_agg(tick_size=50.0)
        # 24526 / 50 = 490.52 → round to 491 × 50 = 24550
        agg.add_tick("NIFTY", 24526.0, 100, "BUY", timestamp=_BASE_TS)
        bins = agg.get_footprint("NIFTY")
        levels = {b.price_level for b in bins}
        assert 24550.0 in levels

    def test_rounds_to_nearest_0_05(self):
        agg = _make_agg(tick_size=0.05)
        agg.add_tick("USDINR", 83.123, 100, "BUY", timestamp=_BASE_TS)
        bins = agg.get_footprint("USDINR")
        expected = round(83.123 / 0.05) * 0.05
        levels = {b.price_level for b in bins}
        assert pytest.approx(expected, abs=1e-9) in [pytest.approx(p, abs=1e-9) for p in levels]


# ===========================================================================
# calculate_aligned_time_bin
# ===========================================================================


class TestCalculateAlignedTimeBin:
    def test_ts_at_market_open_is_own_bin_start(self):
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator

        # _BASE_TS is exactly 09:15:00 IST → bin start should equal _BASE_TS
        result = OrderFlowAggregator.calculate_aligned_time_bin(_BASE_TS, bin_seconds=300, market_open="09:15")
        assert result == int(_BASE_TS)

    def test_ts_in_second_bin(self):
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator

        ts = _BASE_TS + 301  # 5min01s after open → second bin
        result = OrderFlowAggregator.calculate_aligned_time_bin(ts, bin_seconds=300, market_open="09:15")
        assert result == int(_BASE_TS) + 300

    def test_pre_market_ts_uses_floor_alignment(self):
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator

        # Use a timestamp well before 09:15 (e.g. 08:00 IST)
        # _BASE_TS - 75*60 = 08:00 IST
        ts = _BASE_TS - 75 * 60  # 08:00 IST
        result = OrderFlowAggregator.calculate_aligned_time_bin(ts, bin_seconds=300, market_open="09:15")
        assert result == (int(ts) // 300) * 300

    def test_different_bin_sizes(self):
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator

        ts = _BASE_TS + 610  # 10min10s after open → third 5-min bin (600s boundary)
        result_5m = OrderFlowAggregator.calculate_aligned_time_bin(ts, 300, "09:15")
        assert result_5m == int(_BASE_TS) + 600

        result_1m = OrderFlowAggregator.calculate_aligned_time_bin(ts, 60, "09:15")
        assert result_1m == int(_BASE_TS) + 600

    def test_custom_market_open(self):
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator

        # Crypto: market never closes, bins start from 00:00
        # Just verify it doesn't raise for unusual market open
        ts = _BASE_TS
        result = OrderFlowAggregator.calculate_aligned_time_bin(ts, bin_seconds=300, market_open="00:00")
        assert isinstance(result, int)


# ===========================================================================
# cumulative_delta
# ===========================================================================


class TestCumulativeDelta:
    def test_empty_bins_returns_empty_list(self):
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator

        assert OrderFlowAggregator.cumulative_delta([]) == []

    def test_single_bucket_equals_its_delta(self):
        from flinttrade_data.orderflow_aggregator import FootprintBucket, OrderFlowAggregator

        bucket = FootprintBucket(
            price_level=24500.0,
            buy_volume=200,
            sell_volume=100,
            delta=100,
            timestamp_bin=int(_BASE_TS),
        )
        result = OrderFlowAggregator.cumulative_delta([bucket])
        assert result == [100.0]

    def test_running_sum_accumulates(self):
        from flinttrade_data.orderflow_aggregator import FootprintBucket, OrderFlowAggregator

        bins = [
            FootprintBucket(24500.0, 200, 100, 100, int(_BASE_TS)),
            FootprintBucket(24550.0, 100, 150, -50, int(_BASE_TS) + 300),
            FootprintBucket(24500.0, 300, 100, 200, int(_BASE_TS) + 600),
        ]
        result = OrderFlowAggregator.cumulative_delta(bins)
        assert result == [100.0, 50.0, 250.0]

    def test_cumulative_delta_resets_on_new_calendar_day(self):
        from flinttrade_data.orderflow_aggregator import FootprintBucket, OrderFlowAggregator

        # Day 1: _BASE_TS
        # Day 2: add 24 * 3600 seconds
        day2_ts = int(_BASE_TS) + 24 * 3600

        bins = [
            FootprintBucket(24500.0, 200, 100, 100, int(_BASE_TS)),
            FootprintBucket(24500.0, 300, 100, 200, day2_ts),
        ]
        result = OrderFlowAggregator.cumulative_delta(bins)
        # After the day boundary, the running total resets to 0 then adds day2 delta
        assert result[0] == 100.0
        assert result[1] == 200.0  # reset: 0 + 200 = 200

    def test_length_matches_input(self):
        from flinttrade_data.orderflow_aggregator import FootprintBucket, OrderFlowAggregator

        bins = [
            FootprintBucket(p, 100, 50, 50, int(_BASE_TS) + i * 300) for i, p in enumerate([24500.0, 24550.0, 24600.0])
        ]
        assert len(OrderFlowAggregator.cumulative_delta(bins)) == 3


# ===========================================================================
# detect_poc
# ===========================================================================


class TestDetectPoc:
    def test_empty_returns_zero(self):
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator

        assert OrderFlowAggregator.detect_poc([]) == 0.0

    def test_single_bucket_is_poc(self):
        from flinttrade_data.orderflow_aggregator import FootprintBucket, OrderFlowAggregator

        bucket = FootprintBucket(24500.0, 100, 50, 50, int(_BASE_TS))
        assert OrderFlowAggregator.detect_poc([bucket]) == 24500.0

    def test_poc_is_highest_volume_level(self):
        from flinttrade_data.orderflow_aggregator import FootprintBucket, OrderFlowAggregator

        bins = [
            FootprintBucket(24400.0, 100, 50, 50, int(_BASE_TS)),  # total = 150
            FootprintBucket(24500.0, 300, 200, 100, int(_BASE_TS)),  # total = 500
            FootprintBucket(24600.0, 80, 20, 60, int(_BASE_TS)),  # total = 100
        ]
        assert OrderFlowAggregator.detect_poc(bins) == 24500.0

    def test_poc_aggregates_across_bins(self):
        """Same price level appearing in multiple bins should have volumes summed."""
        from flinttrade_data.orderflow_aggregator import FootprintBucket, OrderFlowAggregator

        bins = [
            FootprintBucket(24500.0, 200, 100, 100, int(_BASE_TS)),  # total = 300
            FootprintBucket(24500.0, 100, 50, 50, int(_BASE_TS) + 300),  # total = 150
            FootprintBucket(24600.0, 400, 0, 400, int(_BASE_TS)),  # total = 400
        ]
        # 24500 cumulative total = 300+150 = 450 > 24600 = 400
        assert OrderFlowAggregator.detect_poc(bins) == 24500.0

    def test_poc_tie_break_is_lowest_price(self):
        """When two levels have equal volume, the lower price wins."""
        from flinttrade_data.orderflow_aggregator import FootprintBucket, OrderFlowAggregator

        bins = [
            FootprintBucket(24500.0, 200, 100, 100, int(_BASE_TS)),  # total = 300
            FootprintBucket(24600.0, 200, 100, 100, int(_BASE_TS)),  # total = 300
        ]
        assert OrderFlowAggregator.detect_poc(bins) == 24500.0


# ===========================================================================
# FootprintBucket dataclass
# ===========================================================================


class TestFootprintBucketDataclass:
    def test_total_volume_is_buy_plus_sell(self):
        from flinttrade_data.orderflow_aggregator import FootprintBucket

        b = FootprintBucket(24500.0, 200, 150, 50, int(_BASE_TS))
        assert b.total_volume == 350

    def test_delta_is_buy_minus_sell(self):
        from flinttrade_data.orderflow_aggregator import FootprintBucket

        b = FootprintBucket(24500.0, 200, 150, 50, int(_BASE_TS))
        # delta stored directly, not computed from buy/sell
        assert b.delta == 50

    def test_negative_delta_preserved(self):
        from flinttrade_data.orderflow_aggregator import FootprintBucket

        b = FootprintBucket(24500.0, 50, 200, -150, int(_BASE_TS))
        assert b.delta == -150


# ===========================================================================
# Integration: add_tick → get_footprint → detect_poc
# ===========================================================================


class TestIntegration:
    def test_full_session_poc_detection(self):
        """Simulate a short session and verify POC is the dominant price."""
        agg = _make_agg(time_bin_seconds=300, tick_size=50.0)

        # Heavy buying at 24500 across two bins
        for _ in range(10):
            agg.add_tick("NIFTY", 24500.0, 500, "BUY", timestamp=_BASE_TS)
        for _ in range(5):
            agg.add_tick("NIFTY", 24500.0, 500, "BUY", timestamp=_BASE_TS + 300)

        # Some activity at other levels
        agg.add_tick("NIFTY", 24550.0, 100, "SELL", timestamp=_BASE_TS)
        agg.add_tick("NIFTY", 24450.0, 200, "BUY", timestamp=_BASE_TS)

        bins = agg.get_footprint("NIFTY")
        poc = agg.detect_poc(bins)
        assert poc == 24500.0

    def test_cumulative_delta_after_session(self):
        agg = _make_agg(time_bin_seconds=300, tick_size=50.0)
        agg.add_tick("NIFTY", 24500.0, 300, "BUY", timestamp=_BASE_TS)
        agg.add_tick("NIFTY", 24500.0, 100, "SELL", timestamp=_BASE_TS + 10)
        agg.add_tick("NIFTY", 24500.0, 200, "BUY", timestamp=_BASE_TS + 300)

        bins = agg.get_footprint("NIFTY")
        cd = agg.cumulative_delta(bins)
        # Bin 1: net +200, Bin 2: net +200 → cumulative [200, 400]
        assert cd[-1] == 400.0


class TestFeedMarketTick:
    """feed_market_tick derives incremental volume + aggressor side from raw
    market ticks (cumulative volume, no side), producing explicitly estimated
    order-flow from real quote snapshots instead of synthetic samples."""

    _TS = 1_700_000_000.0

    @staticmethod
    def _agg():
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator

        return OrderFlowAggregator()

    def test_failed_accumulation_does_not_advance_the_cumulative_baseline(self):
        agg = self._agg()
        agg.feed_market_tick("NIFTY", 100.0, 100, timestamp=self._TS)

        with pytest.raises(OverflowError):
            agg.feed_market_tick("NIFTY", 1e308, 200, timestamp=self._TS + 1)

        [identity_state] = agg.export_state()["identities"]
        assert identity_state["last_tick"]["volume"] == 100

        agg.feed_market_tick("NIFTY", 102.0, 225, timestamp=self._TS + 2)

        assert sum(bucket.total_volume for bucket in agg.get_footprint("NIFTY")) == 125

    def test_first_tick_is_a_baseline_noop(self):
        agg = self._agg()
        agg.feed_market_tick("NIFTY", 24500.0, 1000, timestamp=self._TS)
        assert agg.get_footprint("NIFTY") == []  # need a baseline first

        freshness = agg.get_market_freshness("NIFTY", now=self._TS + 1)
        assert freshness["state"] == "unavailable"
        assert freshness["is_fresh"] is False
        assert freshness["last_tick_timestamp"] is None

    def test_new_session_baseline_hides_prior_session_buckets(self):
        agg = self._agg()
        agg.feed_market_tick("NIFTY", 100.0, 1000, timestamp=self._TS)
        agg.feed_market_tick("NIFTY", 101.0, 1100, timestamp=self._TS + 1)
        assert agg.get_footprint("NIFTY")

        next_session = self._TS + 24 * 3600
        agg.feed_market_tick("NIFTY", 102.0, 2000, timestamp=next_session)

        assert agg.get_footprint("NIFTY") == []

    def test_prior_session_returned_data_is_exposed_as_stale(self):
        agg = self._agg()
        agg.feed_market_tick("NIFTY", 24500.0, 1000, timestamp=self._TS)
        agg.feed_market_tick("NIFTY", 24501.0, 1100, timestamp=self._TS + 1)

        freshness = agg.get_market_freshness("NIFTY", now=self._TS + 24 * 60 * 60)

        assert freshness["state"] == "stale"
        assert freshness["is_fresh"] is False
        assert freshness["last_tick_timestamp"] == self._TS + 1
        assert freshness["last_tick_session"] != freshness["current_session"]

    def test_freshness_accepts_recorder_future_skew_boundary(self):
        agg = self._agg()
        agg.feed_market_tick("NIFTY", 24500.0, 1000, timestamp=self._TS + 4.0)
        agg.feed_market_tick("NIFTY", 24501.0, 1100, timestamp=self._TS + 5.0)

        freshness = agg.get_market_freshness("NIFTY", now=self._TS)

        assert freshness["state"] == "live"
        assert freshness["is_fresh"] is True
        assert freshness["age_seconds"] == -5.0

    def test_fresh_zero_volume_snapshot_does_not_refresh_retained_buckets(self):
        from flinttrade_data.orderflow_aggregator import LIVE_TICK_FRESHNESS_SECONDS

        agg = self._agg()
        agg.feed_market_tick("NIFTY", 100.0, 1000, timestamp=self._TS)
        agg.feed_market_tick("NIFTY", 101.0, 1100, timestamp=self._TS + 1)
        fresh_snapshot = self._TS + LIVE_TICK_FRESHNESS_SECONDS + 2

        agg.feed_market_tick("NIFTY", 102.0, 1100, timestamp=fresh_snapshot)

        assert agg.get_footprint("NIFTY")
        freshness = agg.get_market_freshness("NIFTY", now=fresh_snapshot)
        assert freshness["state"] == "delayed"
        assert freshness["is_fresh"] is False
        assert freshness["last_tick_timestamp"] == self._TS + 1

    def test_exact_trade_tick_establishes_returned_data_freshness(self):
        agg = self._agg()

        agg.add_tick("NIFTY", 100.0, 25, "BUY", timestamp=self._TS, exchange="NFO")

        freshness = agg.get_market_freshness("NIFTY", exchange="NFO", now=self._TS + 1)
        assert freshness["state"] == "live"
        assert freshness["is_fresh"] is True
        assert freshness["last_tick_timestamp"] == self._TS
        assert freshness["provenance"] == "trade_tick"

    def test_uptick_records_incremental_buy_volume(self):
        agg = self._agg()
        agg.feed_market_tick("NIFTY", 24500.0, 1000, timestamp=self._TS)
        agg.feed_market_tick("NIFTY", 24505.0, 1250, timestamp=self._TS + 1)  # +250, price up -> BUY
        buckets = agg.get_footprint("NIFTY")
        assert buckets
        assert sum(b.buy_volume for b in buckets) == 250
        assert sum(b.sell_volume for b in buckets) == 0

    def test_quote_rule_overrides_tick_direction(self):
        agg = self._agg()
        agg.feed_market_tick("NIFTY", 24500.0, 1000, timestamp=self._TS)
        # Price ticked UP but the trade printed AT the bid -> seller-initiated.
        agg.feed_market_tick("NIFTY", 24505.0, 1100, bid=24505.0, ask=24506.0, timestamp=self._TS + 1)
        buckets = agg.get_footprint("NIFTY")
        assert sum(b.sell_volume for b in buckets) == 100
        assert sum(b.buy_volume for b in buckets) == 0

    def test_no_volume_change_is_a_noop(self):
        agg = self._agg()
        agg.feed_market_tick("NIFTY", 24500.0, 1000, timestamp=self._TS)
        agg.feed_market_tick("NIFTY", 24505.0, 1000, timestamp=self._TS + 1)  # no trade
        assert agg.get_footprint("NIFTY") == []

    def test_cumulative_volume_decrease_does_not_poison_valid_baseline(self):
        agg = self._agg()
        agg.feed_market_tick("NIFTY", 100.0, 1000, timestamp=self._TS)
        agg.feed_market_tick("NIFTY", 99.0, 1100, timestamp=self._TS + 1)  # establish SELL
        agg.feed_market_tick("NIFTY", 99.0, 100, timestamp=self._TS + 300)  # invalid regression
        agg.feed_market_tick("NIFTY", 99.0, 1125, timestamp=self._TS + 301)

        latest_bin = max(bucket.timestamp_bin for bucket in agg.get_footprint("NIFTY"))
        latest = [bucket for bucket in agg.get_footprint("NIFTY") if bucket.timestamp_bin == latest_bin]

        assert sum(bucket.buy_volume for bucket in latest) == 0
        assert sum(bucket.sell_volume for bucket in latest) == 25

    def test_intraday_cumulative_volume_reset_recovers_after_two_monotonic_samples(self):
        agg = self._agg()
        agg.feed_market_tick("NIFTY", 100.0, 1000, timestamp=self._TS)
        agg.feed_market_tick("NIFTY", 101.0, 1100, timestamp=self._TS + 1)

        # A single lower frame is held as an untrusted reset candidate. A later
        # monotonic sample confirms the new counter without inventing the first
        # sample's unknown volume.
        agg.feed_market_tick("NIFTY", 99.0, 100, timestamp=self._TS + 2)
        agg.feed_market_tick("NIFTY", 98.0, 125, timestamp=self._TS + 3)

        latest = agg.get_footprint("NIFTY")
        assert sum(bucket.buy_volume for bucket in latest) == 100
        assert sum(bucket.sell_volume for bucket in latest) == 25

    def test_equal_reset_candidates_resume_original_counter_without_manufacturing_volume(self):
        agg = self._agg()

        for offset, volume in enumerate((1000, 1100, 100, 100, 1200, 1300)):
            agg.feed_market_tick(
                "NIFTY",
                100.0 + offset,
                volume,
                timestamp=self._TS + offset,
            )

        latest = agg.get_footprint("NIFTY")
        assert sum(bucket.total_volume for bucket in latest) == 300

    def test_confirmed_reset_then_counter_recovery_does_not_double_count_volume(self):
        agg = self._agg()

        for offset, volume in enumerate((1000, 1100, 100, 125, 1125)):
            agg.feed_market_tick(
                "NIFTY",
                100.0 + offset,
                volume,
                timestamp=self._TS + offset,
            )

        latest = agg.get_footprint("NIFTY")
        assert sum(bucket.total_volume for bucket in latest) == 125

    def test_partial_old_counter_recovery_does_not_manufacture_volume(self):
        agg = self._agg()

        for offset, volume in enumerate((1000, 1100, 100, 125, 1101)):
            agg.feed_market_tick(
                "NIFTY",
                100.0 + offset,
                volume,
                timestamp=self._TS + offset,
            )

        latest = agg.get_footprint("NIFTY")
        assert sum(bucket.total_volume for bucket in latest) == 125

    def test_old_counter_catch_up_retires_reset_namespace_and_resumes_volume(self):
        agg = self._agg()

        for offset, volume in enumerate((1000, 1100, 100, 125, 1101, 1125, 1150)):
            agg.feed_market_tick(
                "NIFTY",
                100.0 + offset,
                volume,
                timestamp=self._TS + offset,
            )

        latest = agg.get_footprint("NIFTY")
        assert sum(bucket.total_volume for bucket in latest) == 150

    def test_old_counter_overshoot_retires_to_conservative_namespace(self):
        agg = self._agg()

        for offset, volume in enumerate((1000, 1100, 100, 125, 1101, 1130, 1150)):
            agg.feed_market_tick(
                "NIFTY",
                100.0 + offset,
                volume,
                timestamp=self._TS + offset,
            )

        latest = agg.get_footprint("NIFTY")
        assert sum(bucket.total_volume for bucket in latest) == 150

    def test_equal_reset_snapshot_refreshes_pending_price_without_delayed_rewind(self):
        agg = self._agg()
        agg.feed_market_tick("NIFTY", 100.0, 1000, timestamp=self._TS)
        agg.feed_market_tick("NIFTY", 101.0, 1100, timestamp=self._TS + 1)
        agg.feed_market_tick("NIFTY", 99.0, 100, timestamp=self._TS + 2)
        agg.feed_market_tick("NIFTY", 103.0, 100, timestamp=self._TS + 4)
        agg.feed_market_tick("NIFTY", 90.0, 100, timestamp=self._TS + 3)
        agg.feed_market_tick("NIFTY", 102.0, 125, timestamp=self._TS + 5)

        latest = agg.get_footprint("NIFTY")
        assert sum(bucket.buy_volume for bucket in latest) == 100
        assert sum(bucket.sell_volume for bucket in latest) == 25

    def test_ambiguous_counter_uses_conservative_lower_bound_after_reset(self):
        agg = self._agg()

        for offset, volume in enumerate((1000, 1100, 100, 125, 2000)):
            agg.feed_market_tick(
                "NIFTY",
                100.0 + offset,
                volume,
                timestamp=self._TS + offset,
            )

        latest = agg.get_footprint("NIFTY")
        assert sum(bucket.total_volume for bucket in latest) == 1000

    def test_cumulative_quote_snapshots_are_marked_as_estimated(self):
        agg = self._agg()
        agg.feed_market_tick("NIFTY", 100.0, 1000, timestamp=self._TS)
        agg.feed_market_tick("NIFTY", 101.0, 1100, timestamp=self._TS + 1)

        [bucket] = agg.get_footprint("NIFTY")
        assert bucket.quality == "estimated"
        assert bucket.provenance == "cumulative_quote_delta"

    def test_negative_cumulative_volume_does_not_clear_valid_baseline(self):
        agg = self._agg()
        agg.feed_market_tick("NIFTY", 100.0, 1000, timestamp=self._TS)
        agg.feed_market_tick("NIFTY", 99.0, 1100, timestamp=self._TS + 1)  # establish SELL
        agg.feed_market_tick("NIFTY", 99.0, -1, timestamp=self._TS + 300)
        agg.feed_market_tick("NIFTY", 99.0, 1125, timestamp=self._TS + 301)

        latest_bin = max(bucket.timestamp_bin for bucket in agg.get_footprint("NIFTY"))
        latest = [bucket for bucket in agg.get_footprint("NIFTY") if bucket.timestamp_bin == latest_bin]

        assert sum(bucket.buy_volume for bucket in latest) == 0
        assert sum(bucket.sell_volume for bucket in latest) == 25

    @pytest.mark.parametrize("volume", [True, False], ids=["true", "false"])
    def test_boolean_cumulative_volume_does_not_establish_a_baseline(self, volume):
        agg = self._agg()
        agg.feed_market_tick("NIFTY", 99.0, volume, timestamp=self._TS)
        agg.feed_market_tick("NIFTY", 100.0, 1000, timestamp=self._TS + 1)
        agg.feed_market_tick("NIFTY", 101.0, 1100, timestamp=self._TS + 2)

        latest = agg.get_footprint("NIFTY")
        assert sum(bucket.total_volume for bucket in latest) == 100

    @pytest.mark.parametrize("next_session_opening_volume", [100, 5000])
    def test_new_ist_session_rebaselines_higher_and_lower_opening_cumulative_volume(
        self,
        next_session_opening_volume,
    ):
        agg = self._agg()
        agg.feed_market_tick("NIFTY", 100.0, 1000, timestamp=self._TS)
        agg.feed_market_tick("NIFTY", 99.0, 1100, timestamp=self._TS + 1)  # establish stale SELL

        next_session = self._TS + 24 * 3600
        agg.feed_market_tick("NIFTY", 99.0, next_session_opening_volume, timestamp=next_session)
        agg.feed_market_tick("NIFTY", 99.0, next_session_opening_volume + 25, timestamp=next_session + 1)

        latest = agg.get_footprint("NIFTY")
        assert sum(bucket.buy_volume for bucket in latest) == 25
        assert sum(bucket.sell_volume for bucket in latest) == 0

    def test_late_intraday_tick_does_not_rebase_cumulative_volume(self):
        agg = self._agg()
        agg.feed_market_tick("NIFTY", 100.0, 1000, timestamp=self._TS)
        agg.feed_market_tick("NIFTY", 101.0, 1100, timestamp=self._TS + 2)
        agg.feed_market_tick("NIFTY", 100.5, 1050, timestamp=self._TS + 1)
        agg.feed_market_tick("NIFTY", 102.0, 1125, timestamp=self._TS + 3)

        latest = agg.get_footprint("NIFTY")
        assert sum(bucket.buy_volume + bucket.sell_volume for bucket in latest) == 125

    def test_equal_timestamp_volume_regression_does_not_rebase_cumulative_volume(self):
        agg = self._agg()
        agg.feed_market_tick("NIFTY", 100.0, 1000, timestamp=self._TS)
        agg.feed_market_tick("NIFTY", 101.0, 1100, timestamp=self._TS + 1)
        agg.feed_market_tick("NIFTY", 100.5, 1050, timestamp=self._TS + 1)
        agg.feed_market_tick("NIFTY", 102.0, 1125, timestamp=self._TS + 2)

        latest = agg.get_footprint("NIFTY")
        assert sum(bucket.buy_volume + bucket.sell_volume for bucket in latest) == 125

    def test_equal_timestamp_and_volume_does_not_replace_valid_price_baseline(self):
        agg = self._agg()
        agg.feed_market_tick("NIFTY", 100.0, 1000, timestamp=self._TS)
        agg.feed_market_tick("NIFTY", 101.0, 1100, timestamp=self._TS + 1)
        agg.feed_market_tick("NIFTY", 99.0, 1100, timestamp=self._TS + 1)
        agg.feed_market_tick("NIFTY", 100.0, 1125, timestamp=self._TS + 2)

        latest = agg.get_footprint("NIFTY")
        assert sum(bucket.buy_volume for bucket in latest) == 100
        assert sum(bucket.sell_volume for bucket in latest) == 25

    @pytest.mark.parametrize("stale_offset", [0, 1], ids=["older", "equal"])
    def test_stale_negative_volume_does_not_clear_valid_baseline(self, stale_offset):
        agg = self._agg()
        agg.feed_market_tick("NIFTY", 100.0, 1000, timestamp=self._TS)
        agg.feed_market_tick("NIFTY", 101.0, 1100, timestamp=self._TS + 1)
        agg.feed_market_tick("NIFTY", 100.5, -1, timestamp=self._TS + stale_offset)
        agg.feed_market_tick("NIFTY", 102.0, 1125, timestamp=self._TS + 2)

        latest = agg.get_footprint("NIFTY")
        assert sum(bucket.buy_volume + bucket.sell_volume for bucket in latest) == 125

    def test_late_previous_session_tick_does_not_drop_current_increment(self):
        agg = self._agg()
        current_session = self._TS + 24 * 3600
        agg.feed_market_tick("NIFTY", 100.0, 1000, timestamp=current_session)
        agg.feed_market_tick("NIFTY", 101.0, 1025, timestamp=current_session + 1)
        agg.feed_market_tick("NIFTY", 99.0, 500, timestamp=self._TS + 2)
        agg.feed_market_tick("NIFTY", 102.0, 1050, timestamp=current_session + 2)

        latest = agg.get_footprint("NIFTY")
        assert sum(bucket.buy_volume + bucket.sell_volume for bucket in latest) == 50

    def test_retain_identities_prunes_removed_instrument_state(self):
        agg = self._agg()
        agg.add_tick("NIFTY", 100.0, 10, "BUY", timestamp=self._TS, exchange="NFO")
        agg.feed_market_tick("NIFTY", 100.0, 100, timestamp=self._TS, exchange="NFO")

        agg.retain_identities({("NSE", "RELIANCE")})

        assert ("NFO", "NIFTY") not in agg._state
        assert ("NFO", "NIFTY") not in agg._last_tick
        assert ("NFO", "NIFTY") not in agg._last_side

    def test_exchange_qualified_streams_keep_baselines_sides_and_buckets_isolated(self):
        agg = self._agg()

        agg.feed_market_tick("RELIANCE", 2500.0, 1000, exchange="NSE", timestamp=self._TS)
        agg.feed_market_tick("RELIANCE", 2500.0, 5000, exchange="BSE", timestamp=self._TS)
        agg.feed_market_tick("reliance", 2501.0, 1100, exchange="nse", timestamp=self._TS + 1)
        agg.feed_market_tick("RELIANCE", 2499.0, 5200, exchange="BSE", timestamp=self._TS + 1)
        agg.feed_market_tick("RELIANCE", 2501.0, 1200, exchange="NSE", timestamp=self._TS + 2)
        agg.feed_market_tick("reliance", 2499.0, 5300, exchange="bse", timestamp=self._TS + 2)

        nse_buckets = agg.get_footprint("reliance", exchange="nse")
        bse_buckets = agg.get_footprint("RELIANCE", exchange="BSE")

        assert sum(bucket.buy_volume for bucket in nse_buckets) == 200
        assert sum(bucket.sell_volume for bucket in nse_buckets) == 0
        assert sum(bucket.buy_volume for bucket in bse_buckets) == 0
        assert sum(bucket.sell_volume for bucket in bse_buckets) == 300
        assert agg.get_footprint("RELIANCE") == []


class TestResetMarketTickState:
    _TS = 1_700_000_000.0

    @staticmethod
    def _agg():
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator

        return OrderFlowAggregator()

    def test_reset_qualified_identity_clears_footprint_baseline_and_side(self):
        agg = self._agg()
        agg.feed_market_tick("RELIANCE", 2500.0, 1000, exchange="NSE", timestamp=self._TS)
        agg.feed_market_tick("RELIANCE", 2499.0, 1200, exchange="NSE", timestamp=self._TS + 1)
        agg.feed_market_tick("RELIANCE", 2500.0, 5000, exchange="BSE", timestamp=self._TS)

        agg.reset("reliance", exchange="nse")

        # The first tick after reset is a fresh baseline, never a stale +3,800 trade.
        agg.feed_market_tick("RELIANCE", 2510.0, 5000, exchange="NSE", timestamp=self._TS + 2)
        assert agg.get_footprint("RELIANCE", exchange="NSE") == []
        assert agg.get_footprint("RELIANCE", exchange="BSE") == []

        # A flat follow-up tick verifies that the prior SELL side was cleared too.
        agg.feed_market_tick("RELIANCE", 2510.0, 5100, exchange="NSE", timestamp=self._TS + 3)
        buckets = agg.get_footprint("RELIANCE", exchange="NSE")
        assert sum(bucket.buy_volume for bucket in buckets) == 100
        assert sum(bucket.sell_volume for bucket in buckets) == 0

    def test_reset_empty_exchange_identity_clears_baseline_and_side(self):
        agg = self._agg()
        agg.feed_market_tick("RELIANCE", 2500.0, 1000, timestamp=self._TS)
        agg.feed_market_tick("RELIANCE", 2499.0, 1200, timestamp=self._TS + 1)

        agg.reset("reliance")

        agg.feed_market_tick("RELIANCE", 2510.0, 5000, timestamp=self._TS + 2)
        assert agg.get_footprint("RELIANCE") == []

        agg.feed_market_tick("RELIANCE", 2510.0, 5100, timestamp=self._TS + 3)
        buckets = agg.get_footprint("RELIANCE")
        assert sum(bucket.buy_volume for bucket in buckets) == 100
        assert sum(bucket.sell_volume for bucket in buckets) == 0

    def test_reset_all_clears_market_tick_state_for_every_identity(self):
        agg = self._agg()
        agg.feed_market_tick("RELIANCE", 2500.0, 1000, exchange="NSE", timestamp=self._TS)
        agg.feed_market_tick("INFY", 1500.0, 2000, timestamp=self._TS)
        agg.feed_market_tick("RELIANCE", 2501.0, 1100, exchange="NSE", timestamp=self._TS + 1)
        agg.feed_market_tick("INFY", 1499.0, 2200, timestamp=self._TS + 1)

        agg.reset()

        agg.feed_market_tick("RELIANCE", 2505.0, 9000, exchange="NSE", timestamp=self._TS + 2)
        agg.feed_market_tick("INFY", 1510.0, 9000, timestamp=self._TS + 2)
        assert agg.get_footprint("RELIANCE", exchange="NSE") == []
        assert agg.get_footprint("INFY") == []

    def test_targeted_reset_removes_identity_from_global_lru(self):
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator

        agg = OrderFlowAggregator(max_instruments=3)
        for symbol in ("A", "B", "C"):
            agg.add_tick(symbol, 100.0, 1, "BUY", timestamp=self._TS, exchange="NSE")

        agg.reset("C", exchange="NSE")
        agg.add_tick("D", 100.0, 1, "BUY", timestamp=self._TS + 1, exchange="NSE")

        assert set(agg._state) == {
            ("NSE", "A"),
            ("NSE", "B"),
            ("NSE", "D"),
        }
        assert ("NSE", "C") not in agg._identity_recency

    def test_full_reset_clears_global_lru(self):
        agg = self._agg()
        agg.add_tick("NIFTY", 100.0, 1, "BUY", timestamp=self._TS, exchange="NFO")

        agg.reset()

        assert agg._identity_recency == {}


class TestRestoreCurrentSession:
    _TS = 1_700_000_000.0

    @staticmethod
    def _agg():
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator

        return OrderFlowAggregator()

    @staticmethod
    def _row(timestamp, volume, *, ltp=100.0, symbol="NIFTY", exchange="NFO"):
        return {
            "ts": datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None),
            "symbol": symbol,
            "exchange": exchange,
            "ltp": ltp,
            "volume": volume,
            "bid": ltp - 0.05,
            "ask": ltp + 0.05,
            "timestamp_provenance": "source",
        }

    def test_restore_replays_current_session_and_restores_the_live_baseline(self):
        agg = self._agg()
        rows = [
            self._row(self._TS, 1000, ltp=100.0),
            self._row(self._TS + 1, 1100, ltp=101.0),
        ]

        result = agg.restore_current_session(rows, now=self._TS + 2, max_ticks=10)
        agg.feed_market_tick("NIFTY", 102.0, 1125, exchange="NFO", timestamp=self._TS + 2)

        assert result == {
            "input_ticks": 2,
            "restored_ticks": 2,
            "skipped_ticks": 0,
            "identities": 1,
        }
        buckets = agg.get_footprint("NIFTY", exchange="NFO")
        assert sum(bucket.total_volume for bucket in buckets) == 125
        assert {bucket.quality for bucket in buckets} == {"estimated"}
        assert {bucket.provenance for bucket in buckets} == {"cumulative_quote_delta"}

    @pytest.mark.parametrize(
        "replay_method",
        ["restore_current_session", "replay_current_session_tail"],
    )
    def test_replay_preserves_committed_ingest_order_when_source_time_regresses(
        self,
        replay_method,
    ):
        agg = self._agg()
        rows = [
            {**self._row(self._TS + 2, 200, ltp=102.0), "ingest_seq": 1},
            {**self._row(self._TS + 1, 100, ltp=101.0), "ingest_seq": 2},
        ]

        getattr(agg, replay_method)(rows, now=self._TS + 3, max_ticks=10)

        assert agg.get_footprint("NIFTY", exchange="NFO") == []

    def test_restore_is_idempotent_for_the_represented_identities(self):
        agg = self._agg()
        rows = [
            self._row(self._TS, 1000),
            self._row(self._TS + 1, 1100, ltp=101.0),
        ]

        agg.restore_current_session(rows, now=self._TS + 2, max_ticks=10)
        agg.restore_current_session(rows, now=self._TS + 2, max_ticks=10)

        buckets = agg.get_footprint("NIFTY", exchange="NFO")
        assert sum(bucket.total_volume for bucket in buckets) == 100

    def test_restore_preserves_bigint_cumulative_volume_precision(self):
        agg = self._agg()
        baseline = 2**53 + 1
        rows = [
            self._row(self._TS, baseline),
            self._row(self._TS + 1, baseline + 1, ltp=101.0),
        ]

        agg.restore_current_session(rows, now=self._TS + 2, max_ticks=10)

        buckets = agg.get_footprint("NIFTY", exchange="NFO")
        assert sum(bucket.total_volume for bucket in buckets) == 1

    def test_restore_skips_non_current_and_malformed_rows(self):
        agg = self._agg()
        rows = [
            self._row(self._TS, 900),
            self._row(self._TS + 24 * 3600, 1000),
            {**self._row(self._TS + 24 * 3600 + 1, 1100), "ltp": None},
            self._row(self._TS + 24 * 3600 + 1.5, 10**10_000),
            self._row(self._TS + 24 * 3600 + 2, 1125, ltp=101.0),
        ]

        result = agg.restore_current_session(
            rows,
            now=self._TS + 24 * 3600 + 3,
            max_ticks=10,
        )

        assert result == {
            "input_ticks": 5,
            "restored_ticks": 2,
            "skipped_ticks": 3,
            "identities": 1,
        }
        buckets = agg.get_footprint("NIFTY", exchange="NFO")
        assert sum(bucket.total_volume for bucket in buckets) == 125

    @pytest.mark.parametrize("provenance", [None, "unknown", "receipt"])
    def test_restore_skips_rows_without_trusted_source_timestamp_provenance(self, provenance):
        agg = self._agg()
        rows = [
            {**self._row(self._TS, 1000), "timestamp_provenance": provenance},
            {**self._row(self._TS + 1, 1100), "timestamp_provenance": provenance},
        ]

        result = agg.restore_current_session(rows, now=self._TS + 2, max_ticks=10)

        assert result["restored_ticks"] == 0
        assert result["skipped_ticks"] == 2
        assert agg.get_footprint("NIFTY", exchange="NFO") == []
        assert agg.get_market_freshness("NIFTY", exchange="NFO", now=self._TS + 2)["state"] == "unavailable"

    def test_restore_rejects_overflow_before_mutating_existing_state(self):
        agg = self._agg()
        agg.add_tick("EXISTING", 100.0, 7, "BUY", timestamp=self._TS, exchange="NSE")
        rows = [self._row(self._TS + offset, 1000 + offset) for offset in range(3)]

        with pytest.raises(ValueError, match="max_ticks"):
            agg.restore_current_session(rows, now=self._TS + 3, max_ticks=2)

        existing = agg.get_footprint("EXISTING", exchange="NSE")
        assert sum(bucket.total_volume for bucket in existing) == 7
        assert agg.get_footprint("NIFTY", exchange="NFO") == []

    def test_restore_rejects_an_exactly_full_unverified_tail(self):
        agg = self._agg()
        rows = [self._row(self._TS + offset, 1000 + offset) for offset in range(2)]

        with pytest.raises(ValueError, match="potentially truncated"):
            agg.restore_current_session(rows, now=self._TS + 2, max_ticks=2)

    def test_restore_accepts_an_exactly_full_tail_when_the_caller_proves_completeness(self):
        agg = self._agg()
        rows = [self._row(self._TS + offset, 1000 + offset) for offset in range(2)]

        result = agg.restore_current_session(
            rows,
            now=self._TS + 2,
            max_ticks=2,
            history_complete=True,
        )

        assert result["restored_ticks"] == 2
        assert sum(bucket.total_volume for bucket in agg.get_footprint("NIFTY", exchange="NFO")) == 1

    def test_restore_blocks_a_concurrent_live_writer_until_the_state_swap(self, monkeypatch):
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator

        agg = self._agg()
        rows = [
            self._row(self._TS, 1000),
            self._row(self._TS + 1, 1100, ltp=101.0),
        ]
        replay_started = threading.Event()
        release_replay = threading.Event()
        writer_done = threading.Event()
        original_feed = OrderFlowAggregator.feed_market_tick

        def paused_scratch_replay(instance, *args, **kwargs):
            if instance is not agg and not replay_started.is_set():
                replay_started.set()
                assert release_replay.wait(timeout=2)
            return original_feed(instance, *args, **kwargs)

        monkeypatch.setattr(OrderFlowAggregator, "feed_market_tick", paused_scratch_replay)
        restore = threading.Thread(target=lambda: agg.restore_current_session(rows, now=self._TS + 2, max_ticks=10))
        writer = threading.Thread(
            target=lambda: (
                agg.feed_market_tick(
                    "NIFTY",
                    102.0,
                    1125,
                    exchange="NFO",
                    timestamp=self._TS + 2,
                ),
                writer_done.set(),
            )
        )

        restore.start()
        assert replay_started.wait(timeout=2)
        writer.start()
        try:
            assert not writer_done.wait(timeout=0.2)
        finally:
            release_replay.set()
            restore.join(timeout=2)
            writer.join(timeout=2)

        assert not restore.is_alive()
        assert not writer.is_alive()
        assert writer_done.is_set()
        buckets = agg.get_footprint("NIFTY", exchange="NFO")
        assert sum(bucket.total_volume for bucket in buckets) == 125


class TestRestartStateContract:
    _TS = 1_700_000_000.0

    @staticmethod
    def _agg():
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator

        return OrderFlowAggregator()

    @staticmethod
    def _row(timestamp, volume, *, ltp=100.0):
        return {
            "ts": datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None),
            "symbol": "NIFTY",
            "exchange": "NFO",
            "ltp": ltp,
            "volume": volume,
            "bid": ltp - 0.05,
            "ask": ltp + 0.05,
            "timestamp_provenance": "source",
        }

    def test_checkpoint_restore_preserves_reset_namespaces_across_a_bounded_tail(self):
        source = self._agg()
        for offset, volume in enumerate((1000, 1100, 100, 125)):
            source.feed_market_tick(
                "NIFTY",
                100.0 + offset,
                volume,
                exchange="NFO",
                timestamp=self._TS + offset,
            )

        checkpoint = source.export_state()
        json.dumps(checkpoint)
        restarted = self._agg()
        restore_summary = restarted.restore_state(checkpoint, now=self._TS + 4)
        tail_summary = restarted.replay_current_session_tail(
            [
                self._row(self._TS + 4, 1101, ltp=104.0),
                self._row(self._TS + 5, 1125, ltp=105.0),
                self._row(self._TS + 6, 1150, ltp=106.0),
            ],
            now=self._TS + 7,
            max_ticks=10,
        )

        buckets = restarted.get_footprint("NIFTY", exchange="NFO")
        assert restore_summary == {"identities": 1, "bins": 1, "price_levels": 2}
        assert tail_summary["restored_ticks"] == 3
        assert sum(bucket.total_volume for bucket in buckets) == 150
        assert {bucket.provenance for bucket in buckets} == {"cumulative_quote_delta"}
        assert (
            restarted.get_market_freshness(
                "NIFTY",
                exchange="NFO",
                now=self._TS + 7,
            )["last_tick_timestamp"]
            == self._TS + 6
        )

    def test_checkpoint_tail_replays_rows_from_each_retained_session(self):
        source = self._agg()
        source.feed_market_tick(
            "NIFTY",
            100.0,
            100,
            exchange="NFO",
            timestamp=self._TS,
        )
        next_session = self._TS + 24 * 60 * 60
        restarted = self._agg()
        restarted.restore_state(source.export_state(), now=next_session + 2)

        restarted.replay_current_session_tail(
            [
                self._row(self._TS + 1, 200, ltp=101.0),
                self._row(next_session, 50, ltp=102.0),
                self._row(next_session + 1, 75, ltp=103.0),
            ],
            now=next_session + 2,
            max_ticks=10,
        )

        [identity_state] = restarted.export_state()["identities"]
        represented_volume = sum(
            level["buy_volume"] + level["sell_volume"]
            for bin_state in identity_state["bins"]
            for level in bin_state["levels"]
        )
        assert represented_volume == 125

    def test_checkpoint_round_trip_preserves_exact_source_time_and_provenance(self):
        source = self._agg()
        source.add_tick(
            "NIFTY",
            100.0,
            25,
            "BUY",
            exchange="NFO",
            timestamp=self._TS,
        )

        restarted = self._agg()
        restarted.restore_state(source.export_state(), now=self._TS + 1)

        [bucket] = restarted.get_footprint("NIFTY", exchange="NFO")
        freshness = restarted.get_market_freshness(
            "NIFTY",
            exchange="NFO",
            now=self._TS + 1,
        )
        assert bucket.quality == "exact"
        assert bucket.provenance == "trade_tick"
        assert freshness["last_tick_timestamp"] == self._TS
        assert freshness["provenance"] == "trade_tick"

    def test_invalid_checkpoint_does_not_mutate_existing_state(self):
        agg = self._agg()
        agg.add_tick("EXISTING", 100.0, 7, "BUY", timestamp=self._TS, exchange="NSE")
        checkpoint = agg.export_state()
        checkpoint["config"]["tick_size"] = 1.0

        with pytest.raises(ValueError, match="configuration"):
            agg.restore_state(checkpoint, now=self._TS + 1)

        buckets = agg.get_footprint("EXISTING", exchange="NSE")
        assert sum(bucket.total_volume for bucket in buckets) == 7

    def test_live_state_rejects_price_level_beyond_restore_limit_before_mutation(
        self,
        monkeypatch,
    ):
        import flinttrade_data.orderflow_aggregator as aggregator_module

        monkeypatch.setattr(aggregator_module, "_MAX_STATE_PRICE_LEVELS", 2)
        agg = self._agg()
        agg.add_tick("NIFTY", 100.0, 1, "BUY", exchange="NFO", timestamp=self._TS)
        agg.add_tick("NIFTY", 100.05, 1, "BUY", exchange="NFO", timestamp=self._TS)
        agg.add_tick("NIFTY", 100.0, 1, "SELL", exchange="NFO", timestamp=self._TS)
        before = agg.export_state()

        with pytest.raises(ValueError, match="too many price levels"):
            agg.add_tick("NIFTY", 100.10, 1, "BUY", exchange="NFO", timestamp=self._TS)

        assert agg.export_state() == before

    def test_price_level_cap_accounts_for_lru_identity_eviction(self, monkeypatch):
        import flinttrade_data.orderflow_aggregator as aggregator_module

        monkeypatch.setattr(aggregator_module, "_MAX_STATE_PRICE_LEVELS", 1)
        agg = aggregator_module.OrderFlowAggregator(max_instruments=1)
        agg.add_tick("OLD", 100.0, 1, "BUY", exchange="NSE", timestamp=self._TS)

        agg.add_tick("NEW", 200.0, 1, "BUY", exchange="NSE", timestamp=self._TS + 1)

        assert agg.get_footprint("OLD", exchange="NSE") == []
        assert {bucket.price_level for bucket in agg.get_footprint("NEW", exchange="NSE")} == {200.0}

    @pytest.mark.parametrize("next_timestamp", [_TS + 60, _TS + 24 * 60 * 60])
    def test_price_level_cap_accounts_for_bin_and_session_eviction(
        self,
        monkeypatch,
        next_timestamp,
    ):
        import flinttrade_data.orderflow_aggregator as aggregator_module

        monkeypatch.setattr(aggregator_module, "_MAX_STATE_PRICE_LEVELS", 1)
        agg = aggregator_module.OrderFlowAggregator(
            time_bin_seconds=60,
            max_retained_sessions=1,
            max_bins_per_session=1,
        )
        agg.add_tick("NIFTY", 100.0, 1, "BUY", exchange="NFO", timestamp=self._TS)

        agg.add_tick(
            "NIFTY",
            101.0,
            1,
            "BUY",
            exchange="NFO",
            timestamp=next_timestamp,
        )

        assert {bucket.price_level for bucket in agg.get_footprint("NIFTY", exchange="NFO")} == {101.0}

    def test_rejected_price_level_does_not_mutate_lru_or_state(self, monkeypatch):
        import flinttrade_data.orderflow_aggregator as aggregator_module

        monkeypatch.setattr(aggregator_module, "_MAX_STATE_PRICE_LEVELS", 2)
        agg = aggregator_module.OrderFlowAggregator(max_instruments=3)
        agg.add_tick("A", 100.0, 1, "BUY", exchange="NSE", timestamp=self._TS)
        agg.add_tick("B", 200.0, 1, "BUY", exchange="NSE", timestamp=self._TS)
        before_state = agg.export_state()
        before_lru = tuple(agg._identity_recency)

        with pytest.raises(ValueError, match="too many price levels"):
            agg.add_tick("C", 300.0, 1, "BUY", exchange="NSE", timestamp=self._TS)

        assert agg.export_state() == before_state
        assert tuple(agg._identity_recency) == before_lru

    def test_rejected_feed_tick_does_not_mutate_lru_or_state(self, monkeypatch):
        import flinttrade_data.orderflow_aggregator as aggregator_module

        monkeypatch.setattr(aggregator_module, "_MAX_STATE_PRICE_LEVELS", 2)
        agg = aggregator_module.OrderFlowAggregator(max_instruments=3)
        agg.feed_market_tick("A", 100.0, 10, exchange="NSE", timestamp=self._TS)
        agg.add_tick("A", 100.0, 1, "BUY", exchange="NSE", timestamp=self._TS)
        agg.add_tick("B", 200.0, 1, "BUY", exchange="NSE", timestamp=self._TS)
        before_state = agg.export_state()
        before_lru = tuple(agg._identity_recency)

        with pytest.raises(ValueError, match="too many price levels"):
            agg.feed_market_tick("A", 101.0, 11, exchange="NSE", timestamp=self._TS + 1)

        assert agg.export_state() == before_state
        assert tuple(agg._identity_recency) == before_lru

    def test_rejected_volume_overflow_does_not_mutate_lru_or_state(self):
        import flinttrade_data.orderflow_aggregator as aggregator_module

        agg = aggregator_module.OrderFlowAggregator(max_instruments=3)
        agg.add_tick(
            "A",
            100.0,
            aggregator_module._MAX_SAFE_VOLUME,
            "BUY",
            exchange="NSE",
            timestamp=self._TS,
        )
        agg.add_tick("B", 200.0, 1, "BUY", exchange="NSE", timestamp=self._TS)
        before_state = agg.export_state()
        before_lru = tuple(agg._identity_recency)

        with pytest.raises(ValueError, match="safe integer range"):
            agg.add_tick("A", 100.0, 1, "BUY", exchange="NSE", timestamp=self._TS)

        assert agg.export_state() == before_state
        assert tuple(agg._identity_recency) == before_lru

    def test_non_retained_late_ticks_do_not_mutate_state_lru_or_feed_baseline(self):
        import flinttrade_data.orderflow_aggregator as aggregator_module

        agg = aggregator_module.OrderFlowAggregator(
            time_bin_seconds=60,
            max_retained_sessions=1,
            max_bins_per_session=1,
            max_instruments=3,
        )
        agg.add_tick("A", 100.0, 1, "BUY", exchange="NSE", timestamp=self._TS)
        agg.add_tick("B", 200.0, 1, "BUY", exchange="NSE", timestamp=self._TS)
        before_state = agg.export_state()
        before_lru = tuple(agg._identity_recency)
        late_timestamp = self._TS - 24 * 60 * 60

        agg.add_tick("A", 99.0, 1, "SELL", exchange="NSE", timestamp=late_timestamp)
        agg.feed_market_tick("A", 99.0, 100, exchange="NSE", timestamp=late_timestamp)

        assert agg.export_state() == before_state
        assert tuple(agg._identity_recency) == before_lru

    def test_restore_cap_accounts_for_lru_eviction_without_partial_mutation(
        self,
        monkeypatch,
    ):
        import flinttrade_data.orderflow_aggregator as aggregator_module

        monkeypatch.setattr(aggregator_module, "_MAX_STATE_PRICE_LEVELS", 1)
        agg = aggregator_module.OrderFlowAggregator(max_instruments=1)
        agg.add_tick("OLD", 100.0, 1, "BUY", exchange="NSE", timestamp=self._TS)
        rows = [
            self._row(self._TS + 1, 1000, ltp=200.0),
            self._row(self._TS + 2, 1100, ltp=201.0),
        ]

        agg.restore_current_session(
            rows,
            now=self._TS + 3,
            max_ticks=10,
            history_complete=True,
        )

        assert agg.get_footprint("OLD", exchange="NSE") == []
        assert len(agg.get_footprint("NIFTY", exchange="NFO")) == 1

    def test_rejected_restore_does_not_mutate_live_state_or_lru(self, monkeypatch):
        import flinttrade_data.orderflow_aggregator as aggregator_module

        monkeypatch.setattr(aggregator_module, "_MAX_STATE_PRICE_LEVELS", 2)
        agg = aggregator_module.OrderFlowAggregator(max_instruments=3)
        agg.add_tick("A", 100.0, 1, "BUY", exchange="NSE", timestamp=self._TS)
        agg.add_tick("B", 200.0, 1, "BUY", exchange="NSE", timestamp=self._TS)
        rows = [
            self._row(self._TS + 1, 1000, ltp=300.0),
            self._row(self._TS + 2, 1100, ltp=301.0),
        ]
        before_state = agg.export_state()
        before_lru = tuple(agg._identity_recency)

        with pytest.raises(ValueError, match="too many price levels"):
            agg.restore_current_session(
                rows,
                now=self._TS + 3,
                max_ticks=10,
                history_complete=True,
            )

        assert agg.export_state() == before_state
        assert tuple(agg._identity_recency) == before_lru


class TestConcurrentAccess:
    def test_reader_snapshot_blocks_a_concurrent_writer_until_complete(self, monkeypatch):
        from flinttrade_data.orderflow_aggregator import _BinState

        agg = _make_agg(tick_size=50.0)
        agg.add_tick("NIFTY", 24500.0, 100, "BUY", timestamp=_BASE_TS)

        reader_inside = threading.Event()
        release_reader = threading.Event()
        writer_done = threading.Event()
        original_to_buckets = _BinState.to_buckets

        def paused_to_buckets(state):
            reader_inside.set()
            assert release_reader.wait(timeout=2)
            return original_to_buckets(state)

        monkeypatch.setattr(_BinState, "to_buckets", paused_to_buckets)

        reader = threading.Thread(target=agg.get_footprint, args=("NIFTY",))
        writer = threading.Thread(
            target=lambda: (
                agg.add_tick("NIFTY", 24600.0, 100, "SELL", timestamp=_BASE_TS),
                writer_done.set(),
            )
        )

        reader.start()
        assert reader_inside.wait(timeout=2)
        writer.start()
        try:
            assert not writer_done.wait(timeout=0.2)
        finally:
            release_reader.set()
            reader.join(timeout=2)
            writer.join(timeout=2)

        assert not reader.is_alive()
        assert not writer.is_alive()
        assert writer_done.is_set()
        assert {bucket.price_level for bucket in agg.get_footprint("NIFTY")} == {24500.0, 24600.0}
