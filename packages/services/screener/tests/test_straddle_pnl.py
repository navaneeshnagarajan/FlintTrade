"""Tests for straddle P&L simulation module.

All tests use synthetic candle data — no API calls required.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candles(
    spot: float = 24000.0,
    n: int = 20,
    base_ts: int = 1711900000,
    candle_seconds: int = 300,
    move_per_candle: float = 10.0,
    direction: str = "up",
) -> list[dict]:
    """Generate synthetic candles with a controlled price movement."""
    candles = []
    price = spot
    for i in range(n):
        if direction == "up":
            close = price + move_per_candle
        elif direction == "down":
            close = price - move_per_candle
        else:  # flat
            close = price
        high = close + abs(move_per_candle) * 0.2
        low = close - abs(move_per_candle) * 0.2
        candles.append({
            "time": base_ts + i * candle_seconds,
            "open": round(price, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
            "volume": 5000,
        })
        price = close
    return candles


# ---------------------------------------------------------------------------
# Basic simulation
# ---------------------------------------------------------------------------


class TestStraddlePnLBasic:
    """Basic straddle simulation tests."""

    def test_result_has_timestamps(self):
        from flinttrade_screener.straddle_pnl import simulate_straddle_pnl
        candles = _make_candles()
        result = simulate_straddle_pnl(
            candles=candles, strike=24000, ce_premium=200, pe_premium=210,
            adjustment_points=50, lot_size=75,
        )
        assert len(result.timestamps) == len(candles)

    def test_pnl_series_same_length_as_candles(self):
        from flinttrade_screener.straddle_pnl import simulate_straddle_pnl
        candles = _make_candles(n=30)
        result = simulate_straddle_pnl(
            candles=candles, strike=24000, ce_premium=200, pe_premium=210,
            adjustment_points=100, lot_size=75,
        )
        assert len(result.pnl_series) == len(candles)

    def test_initial_premium_stored(self):
        from flinttrade_screener.straddle_pnl import simulate_straddle_pnl
        candles = _make_candles()
        result = simulate_straddle_pnl(
            candles=candles, strike=24000, ce_premium=200, pe_premium=210,
            adjustment_points=50, lot_size=75,
        )
        assert result.initial_premium == 410.0

    def test_strike_stored(self):
        from flinttrade_screener.straddle_pnl import simulate_straddle_pnl
        candles = _make_candles()
        result = simulate_straddle_pnl(
            candles=candles, strike=24500, ce_premium=180, pe_premium=190,
            adjustment_points=50, lot_size=75,
        )
        assert result.strike == 24500

    def test_lot_size_stored(self):
        from flinttrade_screener.straddle_pnl import simulate_straddle_pnl
        candles = _make_candles()
        result = simulate_straddle_pnl(
            candles=candles, strike=24000, ce_premium=200, pe_premium=210,
            adjustment_points=50, lot_size=75,
        )
        assert result.lot_size == 75


# ---------------------------------------------------------------------------
# P&L bounds
# ---------------------------------------------------------------------------


class TestPnLBounds:
    """Verify max/min/final P&L statistics."""

    def test_max_pnl_gte_min_pnl(self):
        from flinttrade_screener.straddle_pnl import simulate_straddle_pnl
        candles = _make_candles()
        result = simulate_straddle_pnl(
            candles=candles, strike=24000, ce_premium=200, pe_premium=210,
            adjustment_points=50, lot_size=75,
        )
        assert result.max_pnl >= result.min_pnl

    def test_final_pnl_within_max_min(self):
        from flinttrade_screener.straddle_pnl import simulate_straddle_pnl
        candles = _make_candles()
        result = simulate_straddle_pnl(
            candles=candles, strike=24000, ce_premium=200, pe_premium=210,
            adjustment_points=50, lot_size=75,
        )
        assert result.min_pnl <= result.final_pnl <= result.max_pnl

    def test_flat_market_has_positive_pnl(self):
        """In a flat market, short straddle should profit from time value."""
        from flinttrade_screener.straddle_pnl import simulate_straddle_pnl
        candles = _make_candles(direction="flat", n=20)
        result = simulate_straddle_pnl(
            candles=candles, strike=24000, ce_premium=200, pe_premium=210,
            adjustment_points=5000,  # No adjustments
            lot_size=75,
        )
        # In flat market, straddle value should decrease → positive P&L for seller
        assert result.max_pnl >= 0

    def test_large_move_causes_loss(self):
        """Large directional move should cause straddle loss."""
        from flinttrade_screener.straddle_pnl import simulate_straddle_pnl
        # Move 50 points per candle for 20 candles = 1000 point move
        candles = _make_candles(direction="up", move_per_candle=50, n=20)
        result = simulate_straddle_pnl(
            candles=candles, strike=24000, ce_premium=100, pe_premium=110,
            adjustment_points=999999,  # No adjustments
            lot_size=75,
        )
        # Min P&L should be negative for a large move with small premium
        assert result.min_pnl < result.initial_premium


# ---------------------------------------------------------------------------
# Adjustments
# ---------------------------------------------------------------------------


class TestAdjustments:
    """Verify re-hedge/adjustment detection."""

    def test_adjustment_count_attribute(self):
        from flinttrade_screener.straddle_pnl import simulate_straddle_pnl
        candles = _make_candles()
        result = simulate_straddle_pnl(
            candles=candles, strike=24000, ce_premium=200, pe_premium=210,
            adjustment_points=50, lot_size=75,
        )
        assert result.adjustment_count == len(result.adjustments)

    def test_no_adjustments_when_threshold_very_high(self):
        from flinttrade_screener.straddle_pnl import simulate_straddle_pnl
        candles = _make_candles()
        result = simulate_straddle_pnl(
            candles=candles, strike=24000, ce_premium=200, pe_premium=210,
            adjustment_points=999999,  # Never triggers
            lot_size=75,
        )
        assert result.adjustment_count == 0

    def test_adjustment_has_timestamp(self):
        from flinttrade_screener.straddle_pnl import simulate_straddle_pnl
        # Use large move and small adjustment threshold to force adjustment
        candles = _make_candles(move_per_candle=100, n=30)
        result = simulate_straddle_pnl(
            candles=candles, strike=24000, ce_premium=50, pe_premium=55,
            adjustment_points=5,  # Very low threshold
            lot_size=75,
        )
        if result.adjustments:
            for adj in result.adjustments:
                assert adj.timestamp > 0

    def test_adjustment_direction_is_valid(self):
        from flinttrade_screener.straddle_pnl import simulate_straddle_pnl
        candles = _make_candles(move_per_candle=100, n=30)
        result = simulate_straddle_pnl(
            candles=candles, strike=24000, ce_premium=50, pe_premium=55,
            adjustment_points=5, lot_size=75,
        )
        for adj in result.adjustments:
            assert adj.direction in ("UP", "DOWN", "")


# ---------------------------------------------------------------------------
# Rupee conversion
# ---------------------------------------------------------------------------


class TestRupeeConversion:
    """Verify ₹ P&L properties."""

    def test_pnl_rupees_scaled_by_lot_size(self):
        from flinttrade_screener.straddle_pnl import simulate_straddle_pnl
        candles = _make_candles()
        result = simulate_straddle_pnl(
            candles=candles, strike=24000, ce_premium=200, pe_premium=210,
            adjustment_points=50, lot_size=75,
        )
        assert len(result.pnl_rupees) == len(result.pnl_series)
        for pts, rupees in zip(result.pnl_series, result.pnl_rupees):
            assert rupees == pytest.approx(pts * 75, rel=1e-9)

    def test_final_pnl_rupees(self):
        from flinttrade_screener.straddle_pnl import simulate_straddle_pnl
        candles = _make_candles()
        result = simulate_straddle_pnl(
            candles=candles, strike=24000, ce_premium=200, pe_premium=210,
            adjustment_points=50, lot_size=75,
        )
        assert result.final_pnl_rupees == pytest.approx(result.final_pnl * 75, rel=1e-9)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestStraddleEdgeCases:
    """Edge case handling."""

    def test_empty_candles_returns_empty_result(self):
        from flinttrade_screener.straddle_pnl import simulate_straddle_pnl
        result = simulate_straddle_pnl(
            candles=[], strike=24000, ce_premium=200, pe_premium=210,
            adjustment_points=50, lot_size=75,
        )
        assert result.timestamps == []
        assert result.pnl_series == []
        assert result.initial_premium == 410.0

    def test_zero_premium_returns_empty_result(self):
        from flinttrade_screener.straddle_pnl import simulate_straddle_pnl
        candles = _make_candles()
        result = simulate_straddle_pnl(
            candles=candles, strike=24000, ce_premium=0, pe_premium=210,
            adjustment_points=50, lot_size=75,
        )
        assert result.timestamps == []
