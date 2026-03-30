"""Tests for OrderFlowAggregator — footprint chart data from raw ticks.

All tests are pure in-memory and require no external connections.
"""

from __future__ import annotations


import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agg(tick_size: float = 50.0, interval_minutes: int = 5):
    from packages.data.src.orderflow import OrderFlowAggregator

    return OrderFlowAggregator(tick_size=tick_size, interval_minutes=interval_minutes)


# Fixed timestamp that sits cleanly inside a 5-minute bucket.
# 2026-03-25 09:15:00 IST → epoch 1742870700  (bucket label "09:15" in IST)
_BASE_TS = 1742870700.0


# ===========================================================================
# Bucket creation and keying
# ===========================================================================


class TestBucketCreation:
    def test_process_tick_creates_bucket(self):
        agg = _make_agg()
        key = agg.process_tick(ltp=24050.0, volume=100, timestamp=_BASE_TS)
        buckets = agg.get_buckets()
        assert key in buckets

    def test_bucket_has_correct_time_label(self):
        agg = _make_agg()
        key = agg.process_tick(ltp=24050.0, volume=100, timestamp=_BASE_TS)
        bucket = agg.get_bucket(key)
        assert bucket is not None
        assert bucket.time_label == key

    def test_multiple_ticks_same_bucket(self):
        agg = _make_agg()
        k1 = agg.process_tick(ltp=24050.0, volume=100, timestamp=_BASE_TS)
        k2 = agg.process_tick(ltp=24100.0, volume=200, timestamp=_BASE_TS + 30)
        assert k1 == k2
        assert len(agg.get_buckets()) == 1

    def test_multiple_buckets(self):
        agg = _make_agg(interval_minutes=5)
        ts1 = _BASE_TS
        ts2 = _BASE_TS + 300  # exactly one 5-min interval later
        agg.process_tick(ltp=24050.0, volume=100, timestamp=ts1)
        agg.process_tick(ltp=24100.0, volume=200, timestamp=ts2)
        assert len(agg.get_buckets()) == 2

    def test_get_bucket_missing_returns_none(self):
        agg = _make_agg()
        assert agg.get_bucket("99:99") is None


# ===========================================================================
# Price level rounding
# ===========================================================================


class TestPriceLevelRounding:
    def test_price_level_rounding_50(self):
        agg = _make_agg(tick_size=50.0)
        agg.process_tick(ltp=24025.0, volume=100, timestamp=_BASE_TS)
        bucket = agg.get_bucket(agg.process_tick(ltp=24025.0, volume=200, timestamp=_BASE_TS + 1))
        # 24025 rounds to nearest 50 → 24000
        assert 24000.0 in bucket.cells

    def test_price_level_rounding_up(self):
        agg = _make_agg(tick_size=50.0)
        agg.process_tick(ltp=24076.0, volume=100, timestamp=_BASE_TS)
        bucket = agg.get_bucket(agg.process_tick(ltp=24076.0, volume=200, timestamp=_BASE_TS + 1))
        # 24076 rounds up to 24100
        assert 24100.0 in bucket.cells

    def test_price_level_rounding_custom_tick_size(self):
        agg = _make_agg(tick_size=0.05)  # e.g. USDINR
        agg.process_tick(ltp=83.123, volume=100, timestamp=_BASE_TS)
        key = agg.process_tick(ltp=83.123, volume=200, timestamp=_BASE_TS + 1)
        bucket = agg.get_bucket(key)
        expected_level = round(83.123 / 0.05) * 0.05
        assert pytest.approx(expected_level, abs=1e-9) in [
            pytest.approx(p, abs=1e-9) for p in bucket.cells
        ]


# ===========================================================================
# Direction classification
# ===========================================================================


class TestDirectionClassification:
    def test_first_tick_is_buy(self):
        """First tick has no previous LTP — defaults to BUY."""
        agg = _make_agg()
        # volume=0 on the first tick so no trade_volume accumulates
        agg.process_tick(ltp=24000.0, volume=0, timestamp=_BASE_TS)
        assert agg._prev_direction == "BUY"

    def test_rising_ltp_is_buy(self):
        agg = _make_agg()
        agg.process_tick(ltp=24000.0, volume=100, timestamp=_BASE_TS)
        key = agg.process_tick(ltp=24050.0, volume=200, timestamp=_BASE_TS + 1)
        bucket = agg.get_bucket(key)
        assert bucket is not None
        level = 24050.0
        assert bucket.cells[level].buy_volume > 0

    def test_falling_ltp_is_sell(self):
        agg = _make_agg()
        agg.process_tick(ltp=24050.0, volume=100, timestamp=_BASE_TS)
        key = agg.process_tick(ltp=24000.0, volume=250, timestamp=_BASE_TS + 1)
        bucket = agg.get_bucket(key)
        assert bucket is not None
        level = 24000.0
        assert bucket.cells[level].sell_volume > 0

    def test_flat_ltp_inherits_direction_buy(self):
        """Flat price after a BUY tick should remain BUY."""
        agg = _make_agg()
        agg.process_tick(ltp=24000.0, volume=100, timestamp=_BASE_TS)
        agg.process_tick(ltp=24050.0, volume=200, timestamp=_BASE_TS + 1)  # BUY
        agg.process_tick(ltp=24050.0, volume=300, timestamp=_BASE_TS + 2)  # flat
        assert agg._prev_direction == "BUY"

    def test_flat_ltp_inherits_direction_sell(self):
        """Flat price after a SELL tick should remain SELL."""
        agg = _make_agg()
        agg.process_tick(ltp=24050.0, volume=100, timestamp=_BASE_TS)
        agg.process_tick(ltp=24000.0, volume=200, timestamp=_BASE_TS + 1)  # SELL
        agg.process_tick(ltp=24000.0, volume=300, timestamp=_BASE_TS + 2)  # flat
        assert agg._prev_direction == "SELL"


# ===========================================================================
# Volume delta
# ===========================================================================


class TestVolumeDelta:
    def test_first_tick_zero_volume(self):
        """First tick produces 0 trade volume (no previous baseline)."""
        agg = _make_agg()
        agg.process_tick(ltp=24000.0, volume=5000, timestamp=_BASE_TS)
        bucket_key = list(agg.get_buckets().keys())[0]
        bucket = agg.get_bucket(bucket_key)
        assert bucket is not None
        total = sum(c.total_volume for c in bucket.cells.values())
        assert total == 0

    def test_volume_delta_accumulated(self):
        """Second tick's volume delta (200-100=100) should be stored."""
        agg = _make_agg()
        agg.process_tick(ltp=24000.0, volume=100, timestamp=_BASE_TS)
        key = agg.process_tick(ltp=24050.0, volume=200, timestamp=_BASE_TS + 1)
        bucket = agg.get_bucket(key)
        assert bucket is not None
        total = sum(c.total_volume for c in bucket.cells.values())
        assert total == 100  # delta = 200 - 100

    def test_negative_volume_clamped_to_zero(self):
        """If cumulative volume somehow drops, delta is clamped to 0."""
        agg = _make_agg()
        agg.process_tick(ltp=24000.0, volume=500, timestamp=_BASE_TS)
        key = agg.process_tick(ltp=24050.0, volume=300, timestamp=_BASE_TS + 1)
        bucket = agg.get_bucket(key)
        total = sum(c.total_volume for c in bucket.cells.values())
        assert total == 0

    def test_volume_delta_across_multiple_ticks(self):
        agg = _make_agg()
        # Tick 1: baseline — no delta
        agg.process_tick(ltp=24000.0, volume=0, timestamp=_BASE_TS)
        # Tick 2: +50 vol
        agg.process_tick(ltp=24050.0, volume=50, timestamp=_BASE_TS + 10)
        # Tick 3: +75 vol
        key = agg.process_tick(ltp=24100.0, volume=125, timestamp=_BASE_TS + 20)
        bucket = agg.get_bucket(key)
        total = sum(c.total_volume for c in bucket.cells.values())
        assert total == 125  # 50 + 75


# ===========================================================================
# Point of Control
# ===========================================================================


class TestPOCCalculation:
    def test_poc_set_after_first_volume_tick(self):
        agg = _make_agg()
        agg.process_tick(ltp=24000.0, volume=100, timestamp=_BASE_TS)
        key = agg.process_tick(ltp=24000.0, volume=300, timestamp=_BASE_TS + 1)
        bucket = agg.get_bucket(key)
        assert bucket is not None
        assert bucket.poc_price == 24000.0

    def test_poc_tracks_highest_volume_level(self):
        """After adding more volume at a different level, POC should shift."""
        agg = _make_agg(tick_size=100.0)
        # Level 24000: 50 vol
        agg.process_tick(ltp=24000.0, volume=50, timestamp=_BASE_TS)
        agg.process_tick(ltp=24000.0, volume=100, timestamp=_BASE_TS + 1)
        # Level 24100: 200 vol (bigger)
        agg.process_tick(ltp=24100.0, volume=300, timestamp=_BASE_TS + 2)
        key = agg.process_tick(ltp=24100.0, volume=500, timestamp=_BASE_TS + 3)
        bucket = agg.get_bucket(key)
        # level 24100 has total=200, level 24000 has total=50 → POC=24100
        assert bucket.poc_price == 24100.0


# ===========================================================================
# FootprintCell / FootprintBucket computed properties
# ===========================================================================


class TestDataclassProperties:
    def test_footprint_cell_total_volume(self):
        from packages.data.src.orderflow import FootprintCell

        cell = FootprintCell(buy_volume=300, sell_volume=200)
        assert cell.total_volume == 500

    def test_footprint_cell_delta_positive(self):
        from packages.data.src.orderflow import FootprintCell

        cell = FootprintCell(buy_volume=400, sell_volume=100)
        assert cell.delta == 300

    def test_footprint_cell_delta_negative(self):
        from packages.data.src.orderflow import FootprintCell

        cell = FootprintCell(buy_volume=100, sell_volume=400)
        assert cell.delta == -300

    def test_footprint_bucket_total_volume(self):
        from packages.data.src.orderflow import FootprintBucket, FootprintCell

        bucket = FootprintBucket(
            time_label="09:15",
            cells={
                24000.0: FootprintCell(buy_volume=100, sell_volume=50),
                24050.0: FootprintCell(buy_volume=200, sell_volume=100),
            },
        )
        assert bucket.total_volume == 450

    def test_footprint_bucket_total_delta(self):
        from packages.data.src.orderflow import FootprintBucket, FootprintCell

        bucket = FootprintBucket(
            time_label="09:15",
            cells={
                24000.0: FootprintCell(buy_volume=300, sell_volume=100),
                24050.0: FootprintCell(buy_volume=50, sell_volume=200),
            },
        )
        # delta per level: 200, -150 → total 50
        assert bucket.total_delta == 50

    def test_footprint_bucket_price_levels_sorted(self):
        from packages.data.src.orderflow import FootprintBucket, FootprintCell

        bucket = FootprintBucket(
            time_label="09:15",
            cells={
                24100.0: FootprintCell(),
                23900.0: FootprintCell(),
                24000.0: FootprintCell(),
            },
        )
        assert bucket.price_levels == [23900.0, 24000.0, 24100.0]


# ===========================================================================
# Empty / reset state
# ===========================================================================


class TestEmptyAndResetState:
    def test_empty_state_no_buckets(self):
        agg = _make_agg()
        assert agg.get_buckets() == {}

    def test_reset_clears_buckets(self):
        agg = _make_agg()
        agg.process_tick(ltp=24000.0, volume=100, timestamp=_BASE_TS)
        assert len(agg.get_buckets()) == 1
        agg.reset()
        assert agg.get_buckets() == {}

    def test_reset_clears_internal_state(self):
        agg = _make_agg()
        agg.process_tick(ltp=24050.0, volume=500, timestamp=_BASE_TS)
        agg.reset()
        assert agg._prev_ltp is None
        assert agg._prev_volume is None  # sentinel: no tick seen yet
        assert agg._prev_direction == "BUY"


# ===========================================================================
# Constructor validation
# ===========================================================================


class TestConstructorValidation:
    def test_invalid_tick_size_raises(self):
        from packages.data.src.orderflow import OrderFlowAggregator

        with pytest.raises(ValueError, match="tick_size"):
            OrderFlowAggregator(tick_size=0.0)

    def test_negative_tick_size_raises(self):
        from packages.data.src.orderflow import OrderFlowAggregator

        with pytest.raises(ValueError, match="tick_size"):
            OrderFlowAggregator(tick_size=-10.0)

    def test_invalid_interval_raises(self):
        from packages.data.src.orderflow import OrderFlowAggregator

        with pytest.raises(ValueError, match="interval_minutes"):
            OrderFlowAggregator(interval_minutes=0)

    def test_default_timestamp_uses_time_now(self, monkeypatch):
        """When timestamp is omitted, process_tick falls back to time.time()."""
        import packages.data.src.orderflow as orderflow_mod

        # Patch only time.time so the bucket key is deterministic.
        monkeypatch.setattr(orderflow_mod.time, "time", lambda: _BASE_TS)
        agg = orderflow_mod.OrderFlowAggregator()
        key = agg.process_tick(ltp=24000.0, volume=100)
        # The key must be a valid HH:MM string and present in the buckets dict.
        assert key in agg.get_buckets()
        assert len(key) == 5 and key[2] == ":"
