"""Tests for OrderFlowInference — tick-level buy/sell direction inference.

All tests are self-contained and time-deterministic: timestamps are injected
rather than relying on wall-clock time.

Bucket interval is set to 60 seconds throughout unless a test requires otherwise.
"""

from __future__ import annotations

import pytest

T0 = 1_700_000_000.0  # arbitrary epoch base


def _inf(tick_size: float = 0.05, bucket_sec: int = 60):
    from flinttrade_screener.orderflow_inference import OrderFlowInference
    return OrderFlowInference(tick_size=tick_size, bucket_interval_sec=bucket_sec)


# ---------------------------------------------------------------------------
# PriceLevel
# ---------------------------------------------------------------------------


class TestPriceLevel:
    def test_delta_buy_heavy(self):
        from flinttrade_screener.orderflow_inference import PriceLevel
        lv = PriceLevel(price=100.0, buy_volume=500, sell_volume=200)
        assert lv.delta == 300

    def test_delta_sell_heavy(self):
        from flinttrade_screener.orderflow_inference import PriceLevel
        lv = PriceLevel(price=100.0, buy_volume=100, sell_volume=400)
        assert lv.delta == -300

    def test_total_volume(self):
        from flinttrade_screener.orderflow_inference import PriceLevel
        lv = PriceLevel(price=50.0, buy_volume=300, sell_volume=200)
        assert lv.total_volume == 500

    def test_zero_defaults(self):
        from flinttrade_screener.orderflow_inference import PriceLevel
        lv = PriceLevel(price=99.9)
        assert lv.buy_volume == 0
        assert lv.sell_volume == 0
        assert lv.delta == 0


# ---------------------------------------------------------------------------
# FlowBucket
# ---------------------------------------------------------------------------


class TestFlowBucket:
    def test_dominant_side_buy(self):
        from flinttrade_screener.orderflow_inference import FlowBucket
        b = FlowBucket(start_time=T0, end_time=T0 + 60, total_buy=500, total_sell=200, delta=300)
        assert b.dominant_side == "BUY"

    def test_dominant_side_sell(self):
        from flinttrade_screener.orderflow_inference import FlowBucket
        b = FlowBucket(start_time=T0, end_time=T0 + 60, total_buy=100, total_sell=400, delta=-300)
        assert b.dominant_side == "SELL"

    def test_dominant_side_neutral(self):
        from flinttrade_screener.orderflow_inference import FlowBucket
        b = FlowBucket(start_time=T0, end_time=T0 + 60, total_buy=250, total_sell=250, delta=0)
        assert b.dominant_side == "NEUTRAL"


# ---------------------------------------------------------------------------
# _round_to_tick
# ---------------------------------------------------------------------------


class TestRoundToTick:
    def test_exact_multiple(self):
        from flinttrade_screener.orderflow_inference import _round_to_tick
        assert _round_to_tick(24500.0, 0.05) == pytest.approx(24500.0)

    def test_rounds_down(self):
        from flinttrade_screener.orderflow_inference import _round_to_tick
        # 24500.07 → floor to 24500.05
        assert _round_to_tick(24500.07, 0.05) == pytest.approx(24500.05)

    def test_zero_tick_size_returns_price(self):
        from flinttrade_screener.orderflow_inference import _round_to_tick
        assert _round_to_tick(123.456, 0.0) == pytest.approx(123.456)

    def test_integer_tick(self):
        from flinttrade_screener.orderflow_inference import _round_to_tick
        assert _round_to_tick(2503.0, 1.0) == pytest.approx(2503.0)
        assert _round_to_tick(2503.7, 1.0) == pytest.approx(2503.0)


# ---------------------------------------------------------------------------
# OrderFlowInference — construction validation
# ---------------------------------------------------------------------------


class TestOrderFlowInferenceInit:
    def test_negative_tick_size_raises(self):
        from flinttrade_screener.orderflow_inference import OrderFlowInference
        with pytest.raises(ValueError, match="tick_size"):
            OrderFlowInference(tick_size=-0.05)

    def test_zero_bucket_sec_raises(self):
        from flinttrade_screener.orderflow_inference import OrderFlowInference
        with pytest.raises(ValueError, match="bucket_interval_sec"):
            OrderFlowInference(bucket_interval_sec=0)

    def test_negative_bucket_sec_raises(self):
        from flinttrade_screener.orderflow_inference import OrderFlowInference
        with pytest.raises(ValueError, match="bucket_interval_sec"):
            OrderFlowInference(bucket_interval_sec=-1)

    def test_zero_tick_size_allowed(self):
        from flinttrade_screener.orderflow_inference import OrderFlowInference
        # tick_size=0 is allowed (means no rounding)
        inf = OrderFlowInference(tick_size=0.0)
        assert inf.tick_size == 0.0


# ---------------------------------------------------------------------------
# process_tick — direction classification
# ---------------------------------------------------------------------------


class TestProcessTickClassification:
    def test_first_tick_returns_none(self):
        """No bucket can seal on the very first tick."""
        inf = _inf()
        result = inf.process_tick(ltp=24500.0, volume=1000, timestamp=T0)
        assert result is None

    def test_ltp_up_volume_up_classified_buy(self):
        inf = _inf()
        inf.process_tick(ltp=24500.0, volume=1000, timestamp=T0)
        inf.process_tick(ltp=24505.0, volume=1500, timestamp=T0 + 1)
        bucket = inf.get_current_bucket()
        assert bucket is not None
        assert bucket.total_buy > 0
        assert bucket.total_sell == 0

    def test_ltp_down_volume_up_classified_sell(self):
        inf = _inf()
        inf.process_tick(ltp=24500.0, volume=1000, timestamp=T0)
        inf.process_tick(ltp=24490.0, volume=1500, timestamp=T0 + 1)
        bucket = inf.get_current_bucket()
        assert bucket is not None
        assert bucket.total_sell > 0
        assert bucket.total_buy == 0

    def test_flat_ltp_volume_up_uses_continuation(self):
        """Flat LTP with new volume inherits the last known direction."""
        inf = _inf()
        inf.process_tick(ltp=24500.0, volume=1000, timestamp=T0)
        # First directional tick: BUY
        inf.process_tick(ltp=24505.0, volume=1500, timestamp=T0 + 1)
        # Flat LTP, new volume — should continue as BUY
        inf.process_tick(ltp=24505.0, volume=2000, timestamp=T0 + 2)
        bucket = inf.get_current_bucket()
        assert bucket.total_buy > 0

    def test_no_volume_delta_not_attributed(self):
        """Re-sent tick with same cumulative volume adds nothing."""
        inf = _inf()
        inf.process_tick(ltp=24500.0, volume=1000, timestamp=T0)
        inf.process_tick(ltp=24505.0, volume=1000, timestamp=T0 + 1)  # same volume
        bucket = inf.get_current_bucket()
        assert bucket.total_buy == 0
        assert bucket.total_sell == 0


# ---------------------------------------------------------------------------
# process_tick — bucket sealing
# ---------------------------------------------------------------------------


class TestBucketSealing:
    def test_bucket_sealed_at_interval_boundary(self):
        """A tick at T0+60 crosses the 60-second bucket boundary."""
        from flinttrade_screener.orderflow_inference import FlowBucket
        inf = _inf(bucket_sec=60)
        inf.process_tick(ltp=24500.0, volume=1000, timestamp=T0)
        inf.process_tick(ltp=24505.0, volume=1500, timestamp=T0 + 10)
        completed = inf.process_tick(ltp=24510.0, volume=2000, timestamp=T0 + 60)
        assert completed is not None
        assert isinstance(completed, FlowBucket)

    def test_sealed_bucket_appears_in_get_recent_buckets(self):
        inf = _inf(bucket_sec=60)
        inf.process_tick(ltp=24500.0, volume=1000, timestamp=T0)
        inf.process_tick(ltp=24510.0, volume=1500, timestamp=T0 + 61)
        buckets = inf.get_recent_buckets()
        assert len(buckets) == 1

    def test_sealed_bucket_ltp_open_and_close(self):
        inf = _inf(bucket_sec=60)
        inf.process_tick(ltp=24500.0, volume=1000, timestamp=T0)
        inf.process_tick(ltp=24510.0, volume=1500, timestamp=T0 + 30)
        inf.process_tick(ltp=24520.0, volume=2000, timestamp=T0 + 61)  # seals first bucket
        buckets = inf.get_recent_buckets()
        first = buckets[0]
        assert first.ltp_open == pytest.approx(24500.0)
        assert first.ltp_close == pytest.approx(24510.0)

    def test_get_recent_buckets_limit(self):
        """get_recent_buckets(n) returns at most n buckets."""
        inf = _inf(bucket_sec=60)
        inf.process_tick(ltp=24500.0, volume=1000, timestamp=T0)
        # Drive 5 bucket seals
        for i in range(1, 6):
            inf.process_tick(ltp=24500.0 + i, volume=1000 + i * 100, timestamp=T0 + i * 60)
        all_buckets = inf.get_recent_buckets(10)
        assert len(all_buckets) == 5
        limited = inf.get_recent_buckets(3)
        assert len(limited) == 3

    def test_get_current_bucket_none_before_first_tick(self):
        inf = _inf()
        assert inf.get_current_bucket() is None

    def test_price_levels_sorted_ascending(self):
        """Price levels within a bucket must be sorted by price ascending."""
        inf = _inf(tick_size=1.0, bucket_sec=60)
        inf.process_tick(ltp=100.0, volume=1000, timestamp=T0)
        inf.process_tick(ltp=103.0, volume=1500, timestamp=T0 + 5)   # BUY at 103
        inf.process_tick(ltp=101.0, volume=2000, timestamp=T0 + 10)  # SELL at 101
        inf.process_tick(ltp=102.0, volume=2600, timestamp=T0 + 15)  # BUY at 102
        bucket = inf.get_current_bucket()
        prices = [lv.price for lv in bucket.levels]
        assert prices == sorted(prices)


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_buckets(self):
        inf = _inf(bucket_sec=60)
        inf.process_tick(ltp=24500.0, volume=1000, timestamp=T0)
        inf.process_tick(ltp=24510.0, volume=1500, timestamp=T0 + 61)
        assert len(inf.get_recent_buckets()) == 1
        inf.reset()
        assert len(inf.get_recent_buckets()) == 0

    def test_reset_clears_current_bucket(self):
        inf = _inf()
        inf.process_tick(ltp=24500.0, volume=1000, timestamp=T0)
        inf.reset()
        assert inf.get_current_bucket() is None
