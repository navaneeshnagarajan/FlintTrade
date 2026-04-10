"""Tests for IndianShortStraddle — Indian F&O short straddle backtest strategy.

Covers lot-size lookup, strike interval lookup, ATM rounding, entry/exit timing,
all five SL modes, state machine transitions, re-entry logic, target modes, and
error handling for unknown underlyings.

All tests use synthetic bar data; no network or broker access required.
"""

from __future__ import annotations

from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Shared imports (deferred inside tests to avoid import errors at collection)
# ---------------------------------------------------------------------------

def _import_strategy():
    from strategies.options_short_straddle_indian import (
        IndianShortStraddle,
        LOT_SIZES,
        STRIKE_INTERVALS,
        SLMode,
        StraddleState,
        TargetMode,
        atm_strike,
        lot_size_for,
        strike_interval_for,
    )
    return (
        IndianShortStraddle,
        LOT_SIZES,
        STRIKE_INTERVALS,
        SLMode,
        StraddleState,
        TargetMode,
        atm_strike,
        lot_size_for,
        strike_interval_for,
    )


def _make_ohlcv(timestamp: str, price: float, volume: int = 5000):
    """Create an OHLCV instance with a given timestamp and flat price."""
    from packages.core.src.models import OHLCV
    return OHLCV(
        timestamp=timestamp,
        open=price,
        high=price + 10,
        low=price - 10,
        close=price,
        volume=volume,
    )


def _make_bars_around_entry(
    n_before: int = 3,
    n_after: int = 10,
    spot: float = 19_000.0,
    entry_time: str = "09:20",
    date: str = "2025-01-02",
) -> list[Any]:
    """Generate OHLCV bars: n_before before entry_time, then n_after at/after.

    All bars on the same date. Timestamps use minute-level granularity.
    The entry bar timestamp is set exactly to entry_time.
    """
    from packages.core.src.models import OHLCV

    bars: list[OHLCV] = []

    # Pre-entry bars at 09:15, 09:16, … (n_before bars)
    start_hh, start_mm = 9, 15
    for i in range(n_before):
        mm = start_mm + i
        ts = f"{date} {start_hh:02d}:{mm:02d}:00"
        bars.append(_make_ohlcv(ts, spot))

    # Entry bar at exactly entry_time
    entry_hh, entry_mm = int(entry_time[:2]), int(entry_time[3:])
    bars.append(_make_ohlcv(f"{date} {entry_hh:02d}:{entry_mm:02d}:00", spot))

    # Post-entry bars
    for i in range(1, n_after):
        mm_total = entry_mm + i
        hh = entry_hh + mm_total // 60
        mm = mm_total % 60
        ts = f"{date} {hh:02d}:{mm:02d}:00"
        bars.append(_make_ohlcv(ts, spot))

    return bars


def _run(strategy, bars: list[Any]) -> list[Any]:
    """Feed bars and collect all orders generated."""
    strategy.start()
    orders: list[Any] = []
    for bar in bars:
        strategy.on_bar(bar)
        orders.extend(strategy.generate_orders())
    return orders


# ===========================================================================
# test_lot_size_lookup
# ===========================================================================

class TestLotSizeLookup:
    """Verify LOT_SIZES registry and lot_size_for() helper."""

    def test_nifty_lot_size(self):
        _, LOT_SIZES, _, _, _, _, _, lot_size_for, _ = _import_strategy()
        assert lot_size_for("NIFTY") == 75

    def test_banknifty_lot_size(self):
        _, LOT_SIZES, _, _, _, _, _, lot_size_for, _ = _import_strategy()
        assert lot_size_for("BANKNIFTY") == 15

    def test_finnifty_lot_size(self):
        _, LOT_SIZES, _, _, _, _, _, lot_size_for, _ = _import_strategy()
        assert lot_size_for("FINNIFTY") == 25

    def test_sensex_lot_size(self):
        _, LOT_SIZES, _, _, _, _, _, lot_size_for, _ = _import_strategy()
        assert lot_size_for("SENSEX") == 10

    def test_midcpnifty_lot_size(self):
        _, LOT_SIZES, _, _, _, _, _, lot_size_for, _ = _import_strategy()
        assert lot_size_for("MIDCPNIFTY") == 50

    def test_case_insensitive(self):
        _, _, _, _, _, _, _, lot_size_for, _ = _import_strategy()
        assert lot_size_for("nifty") == lot_size_for("NIFTY")
        assert lot_size_for("banknifty") == lot_size_for("BANKNIFTY")

    def test_unknown_symbol_returns_default(self):
        _, _, _, _, _, _, _, lot_size_for, _ = _import_strategy()
        assert lot_size_for("UNKNOWN_XYZ") == 1


# ===========================================================================
# test_strike_interval_lookup
# ===========================================================================

class TestStrikeIntervalLookup:
    """Verify STRIKE_INTERVALS registry and strike_interval_for() helper."""

    def test_nifty_interval(self):
        _, _, _, _, _, _, _, _, strike_interval_for = _import_strategy()
        assert strike_interval_for("NIFTY") == 50

    def test_banknifty_interval(self):
        _, _, _, _, _, _, _, _, strike_interval_for = _import_strategy()
        assert strike_interval_for("BANKNIFTY") == 100

    def test_finnifty_interval(self):
        _, _, _, _, _, _, _, _, strike_interval_for = _import_strategy()
        assert strike_interval_for("FINNIFTY") == 50

    def test_sensex_interval(self):
        _, _, _, _, _, _, _, _, strike_interval_for = _import_strategy()
        assert strike_interval_for("SENSEX") == 100

    def test_midcpnifty_interval(self):
        _, _, _, _, _, _, _, _, strike_interval_for = _import_strategy()
        assert strike_interval_for("MIDCPNIFTY") == 25

    def test_unknown_falls_back_to_50(self):
        _, _, _, _, _, _, _, _, strike_interval_for = _import_strategy()
        assert strike_interval_for("WHATEVER") == 50


# ===========================================================================
# test_atm_strike_rounding
# ===========================================================================

class TestATMStrikeRounding:
    """Verify atm_strike() rounds correctly for each underlying."""

    def test_nifty_round_down(self):
        _, _, _, _, _, _, atm_strike, _, _ = _import_strategy()
        # 19453 % 50 == 3 < 25 → round down to 19450
        assert atm_strike(19453.0, "NIFTY") == 19450

    def test_nifty_round_up(self):
        _, _, _, _, _, _, atm_strike, _, _ = _import_strategy()
        # 19476 % 50 == 26 >= 25 → round up to 19500
        assert atm_strike(19476.0, "NIFTY") == 19500

    def test_nifty_exact_multiple(self):
        _, _, _, _, _, _, atm_strike, _, _ = _import_strategy()
        assert atm_strike(19500.0, "NIFTY") == 19500

    def test_banknifty_round_down(self):
        _, _, _, _, _, _, atm_strike, _, _ = _import_strategy()
        # 44987 % 100 == 87 >= 50 → round up to 45000
        assert atm_strike(44987.0, "BANKNIFTY") == 45000

    def test_banknifty_round_up(self):
        _, _, _, _, _, _, atm_strike, _, _ = _import_strategy()
        # 44930 % 100 == 30 < 50 → round down to 44900
        assert atm_strike(44930.0, "BANKNIFTY") == 44900

    def test_midcpnifty_interval_25(self):
        _, _, _, _, _, _, atm_strike, _, _ = _import_strategy()
        # 9513 % 25 == 13 >= 12.5 → round up to 9525
        assert atm_strike(9513.0, "MIDCPNIFTY") == 9525

    def test_midcpnifty_round_down(self):
        _, _, _, _, _, _, atm_strike, _, _ = _import_strategy()
        # 9512 % 25 == 12 < 12.5 → round down to 9500
        assert atm_strike(9512.0, "MIDCPNIFTY") == 9500

    def test_sensex_interval_100(self):
        _, _, _, _, _, _, atm_strike, _, _ = _import_strategy()
        # 72560 % 100 == 60 >= 50 → round up to 72600
        assert atm_strike(72560.0, "SENSEX") == 72600


# ===========================================================================
# test_entry_time_check
# ===========================================================================

class TestEntryTimeCheck:
    """Verify strategy waits for entry_time before placing orders."""

    def test_no_orders_before_entry_time(self):
        IndianShortStraddle, *_ = _import_strategy()
        s = IndianShortStraddle(underlying="NIFTY", entry_time="09:20", lots=1)
        s.start()
        # Bar at 09:15 — before entry
        bar = _make_ohlcv("2025-01-02 09:15:00", 19000.0)
        s.on_bar(bar)
        assert s.generate_orders() == []

    def test_orders_placed_at_entry_time(self):
        IndianShortStraddle, *_ = _import_strategy()
        s = IndianShortStraddle(underlying="NIFTY", entry_time="09:20", lots=1)
        s.start()
        bar = _make_ohlcv("2025-01-02 09:20:00", 19000.0)
        s.on_bar(bar)
        orders = s.generate_orders()
        # Should produce 2 SELL orders (CE + PE)
        assert len(orders) == 2
        actions = {o.action for o in orders}
        assert actions == {"SELL"}

    def test_orders_placed_after_entry_time(self):
        IndianShortStraddle, *_ = _import_strategy()
        s = IndianShortStraddle(underlying="NIFTY", entry_time="09:20", lots=1)
        s.start()
        # Skip past entry time — first bar at 09:25
        bar = _make_ohlcv("2025-01-02 09:25:00", 19000.0)
        s.on_bar(bar)
        orders = s.generate_orders()
        assert len(orders) == 2

    def test_state_is_waiting_before_entry(self):
        IndianShortStraddle, _, _, _, StraddleState, *_ = _import_strategy()
        s = IndianShortStraddle(underlying="NIFTY", entry_time="09:20", lots=1)
        s.start()
        bar = _make_ohlcv("2025-01-02 09:15:00", 19000.0)
        s.on_bar(bar)
        assert s.straddle_state == StraddleState.WAITING

    def test_state_is_active_after_entry(self):
        IndianShortStraddle, _, _, _, StraddleState, *_ = _import_strategy()
        s = IndianShortStraddle(underlying="NIFTY", entry_time="09:20", lots=1)
        s.start()
        bar = _make_ohlcv("2025-01-02 09:20:00", 19000.0)
        s.on_bar(bar)
        s.generate_orders()  # flush
        assert s.straddle_state == StraddleState.ACTIVE


# ===========================================================================
# test_sl_percentage_mode
# ===========================================================================

class TestSLPercentageMode:
    """Verify per-leg percentage SL exits work correctly."""

    def _build_strategy(self, ce_sl_pct: float = 25.0, pe_sl_pct: float = 25.0):
        IndianShortStraddle, *_ = _import_strategy()
        return IndianShortStraddle(
            underlying="NIFTY",
            sl_mode="percentage",
            ce_sl_pct=ce_sl_pct,
            pe_sl_pct=pe_sl_pct,
            entry_time="09:20",
            exit_time="15:06",
            lots=1,
            price_series_mode="premium",
        )

    def test_no_exit_before_sl_hit(self):
        s = self._build_strategy()
        s.start()
        # Entry at 09:20 with combined premium = 200
        entry_bar = _make_ohlcv("2025-01-02 09:20:00", 200.0)
        s.on_bar(entry_bar)
        s.generate_orders()  # flush entry orders

        # Post-entry bar: premium stays at 200 (no decay → no SL)
        bar = _make_ohlcv("2025-01-02 09:21:00", 200.0)
        s.on_bar(bar)
        orders = s.generate_orders()
        # No exit orders expected
        assert not any(o.action == "BUY" for o in orders)

    def test_sl_triggers_buy_back(self):
        """When the combined premium rises well above SL threshold, exits are queued."""
        s = self._build_strategy(ce_sl_pct=25.0, pe_sl_pct=25.0)
        s.start()
        # Entry: combined = 200; each leg proxy = 100; SL at 125 per leg
        entry_bar = _make_ohlcv("2025-01-02 09:20:00", 200.0)
        s.on_bar(entry_bar)
        s.generate_orders()

        # Premium rises sharply — both legs breach their SL
        high_bar = _make_ohlcv("2025-01-02 09:21:00", 300.0)
        s.on_bar(high_bar)
        orders = s.generate_orders()
        buy_orders = [o for o in orders if o.action == "BUY"]
        # Both legs should be bought back
        assert len(buy_orders) == 2

    def test_sl_level_calculation(self):
        """Verify SL level matches expected formula: sell_price * (1 + sl_pct/100)."""
        IndianShortStraddle, *_ = _import_strategy()
        s = IndianShortStraddle(
            underlying="NIFTY",
            sl_mode="percentage",
            ce_sl_pct=20.0,
            pe_sl_pct=30.0,
            entry_time="09:20",
            price_series_mode="premium",
        )
        s.start()
        entry_bar = _make_ohlcv("2025-01-02 09:20:00", 400.0)
        s.on_bar(entry_bar)
        s.generate_orders()

        # Each leg sell price ≈ 200 (premium / 2 in premium mode)
        # CE SL = 200 * 1.20 = 240; PE SL = 200 * 1.30 = 260
        assert abs(s._ce_sl_level - 240.0) < 1.0
        assert abs(s._pe_sl_level - 260.0) < 1.0


# ===========================================================================
# test_sl_fixed_points_mode
# ===========================================================================

class TestSLFixedPointsMode:
    """Verify fixed-points SL mode."""

    def test_fixed_points_sl_level(self):
        IndianShortStraddle, *_ = _import_strategy()
        s = IndianShortStraddle(
            underlying="BANKNIFTY",
            sl_mode="fixed_points",
            ce_sl_points=50.0,
            pe_sl_points=60.0,
            entry_time="09:20",
            price_series_mode="premium",
        )
        s.start()
        entry_bar = _make_ohlcv("2025-01-02 09:20:00", 600.0)
        s.on_bar(entry_bar)
        s.generate_orders()

        # Each leg sell price ≈ 300 (600 / 2)
        # CE SL = 300 + 50 = 350; PE SL = 300 + 60 = 360
        assert abs(s._ce_sl_level - 350.0) < 1.0
        assert abs(s._pe_sl_level - 360.0) < 1.0

    def test_fixed_points_sl_triggers_exit(self):
        IndianShortStraddle, *_ = _import_strategy()
        s = IndianShortStraddle(
            underlying="BANKNIFTY",
            sl_mode="fixed_points",
            ce_sl_points=50.0,
            pe_sl_points=50.0,
            entry_time="09:20",
            exit_time="15:06",
            price_series_mode="premium",
        )
        s.start()
        entry_bar = _make_ohlcv("2025-01-02 09:20:00", 400.0)
        s.on_bar(entry_bar)
        s.generate_orders()

        # Rise sharply — both legs breach SL
        high_bar = _make_ohlcv("2025-01-02 09:21:00", 600.0)
        s.on_bar(high_bar)
        orders = s.generate_orders()
        buy_orders = [o for o in orders if o.action == "BUY"]
        assert len(buy_orders) == 2


# ===========================================================================
# test_state_transitions
# ===========================================================================

class TestStateTransitions:
    """Verify correct state machine transitions."""

    def test_waiting_to_active_on_entry(self):
        IndianShortStraddle, _, _, _, StraddleState, *_ = _import_strategy()
        s = IndianShortStraddle(underlying="NIFTY", entry_time="09:20")
        s.start()
        assert s.straddle_state == StraddleState.WAITING
        s.on_bar(_make_ohlcv("2025-01-02 09:20:00", 19_000.0))
        s.generate_orders()
        assert s.straddle_state == StraddleState.ACTIVE

    def test_active_to_sl_hit_on_both_legs_exited(self):
        """When both CE and PE SLs are hit, state moves to SL_HIT."""
        IndianShortStraddle, _, _, _, StraddleState, *_ = _import_strategy()
        s = IndianShortStraddle(
            underlying="NIFTY",
            sl_mode="percentage",
            ce_sl_pct=25.0,
            pe_sl_pct=25.0,
            entry_time="09:20",
            exit_time="15:06",
            re_entry_enabled=False,
            price_series_mode="premium",
        )
        s.start()
        s.on_bar(_make_ohlcv("2025-01-02 09:20:00", 200.0))
        s.generate_orders()
        assert s.straddle_state == StraddleState.ACTIVE

        # Spike the premium hard enough to blow through 25% SL
        s.on_bar(_make_ohlcv("2025-01-02 09:21:00", 400.0))
        s.generate_orders()
        assert s.straddle_state == StraddleState.SL_HIT

    def test_sl_hit_to_active_on_re_entry(self):
        """After SL_HIT, re-entry before re_entry_time moves state back to ACTIVE."""
        IndianShortStraddle, _, _, _, StraddleState, *_ = _import_strategy()
        s = IndianShortStraddle(
            underlying="NIFTY",
            sl_mode="percentage",
            ce_sl_pct=25.0,
            pe_sl_pct=25.0,
            entry_time="09:20",
            exit_time="15:06",
            re_entry_enabled=True,
            re_entry_time="12:30",
            price_series_mode="premium",
        )
        s.start()
        s.on_bar(_make_ohlcv("2025-01-02 09:20:00", 200.0))
        s.generate_orders()

        # Trigger SL_HIT
        s.on_bar(_make_ohlcv("2025-01-02 09:21:00", 400.0))
        s.generate_orders()
        assert s.straddle_state == StraddleState.SL_HIT

        # Re-entry bar within re_entry_time window
        s.on_bar(_make_ohlcv("2025-01-02 10:00:00", 200.0))
        s.generate_orders()
        assert s.straddle_state == StraddleState.ACTIVE

    def test_no_re_entry_after_re_entry_time(self):
        """No re-entry if bar time is past re_entry_time."""
        IndianShortStraddle, _, _, _, StraddleState, *_ = _import_strategy()
        s = IndianShortStraddle(
            underlying="NIFTY",
            sl_mode="percentage",
            ce_sl_pct=25.0,
            pe_sl_pct=25.0,
            entry_time="09:20",
            exit_time="15:06",
            re_entry_enabled=True,
            re_entry_time="10:00",
            price_series_mode="premium",
        )
        s.start()
        s.on_bar(_make_ohlcv("2025-01-02 09:20:00", 200.0))
        s.generate_orders()

        s.on_bar(_make_ohlcv("2025-01-02 09:21:00", 400.0))
        s.generate_orders()
        assert s.straddle_state == StraddleState.SL_HIT

        # Bar past re_entry_time — should stay SL_HIT
        s.on_bar(_make_ohlcv("2025-01-02 11:00:00", 200.0))
        s.generate_orders()
        assert s.straddle_state == StraddleState.SL_HIT


# ===========================================================================
# test_exit_at_close
# ===========================================================================

class TestExitAtClose:
    """Verify forced square-off at exit_time."""

    def test_square_off_queues_buy_orders(self):
        IndianShortStraddle, _, _, _, StraddleState, *_ = _import_strategy()
        s = IndianShortStraddle(
            underlying="NIFTY",
            entry_time="09:20",
            exit_time="15:06",
            price_series_mode="premium",
        )
        s.start()
        # Enter the straddle
        s.on_bar(_make_ohlcv("2025-01-02 09:20:00", 200.0))
        s.generate_orders()
        assert s.straddle_state == StraddleState.ACTIVE

        # Fast-forward to exit time with unchanged premium (no SL hit)
        s.on_bar(_make_ohlcv("2025-01-02 15:06:00", 180.0))
        orders = s.generate_orders()
        buy_orders = [o for o in orders if o.action == "BUY"]
        assert len(buy_orders) == 2

    def test_state_is_exited_after_squareoff(self):
        IndianShortStraddle, _, _, _, StraddleState, *_ = _import_strategy()
        s = IndianShortStraddle(
            underlying="NIFTY",
            entry_time="09:20",
            exit_time="15:06",
            price_series_mode="premium",
        )
        s.start()
        s.on_bar(_make_ohlcv("2025-01-02 09:20:00", 200.0))
        s.generate_orders()

        s.on_bar(_make_ohlcv("2025-01-02 15:06:00", 180.0))
        s.generate_orders()
        assert s.straddle_state == StraddleState.EXITED

    def test_no_orders_after_exited(self):
        """After EXITED, no additional orders should be generated."""
        IndianShortStraddle, *_ = _import_strategy()
        s = IndianShortStraddle(
            underlying="NIFTY",
            entry_time="09:20",
            exit_time="15:06",
            price_series_mode="premium",
        )
        s.start()
        s.on_bar(_make_ohlcv("2025-01-02 09:20:00", 200.0))
        s.generate_orders()
        s.on_bar(_make_ohlcv("2025-01-02 15:06:00", 180.0))
        s.generate_orders()

        # Additional bars after exit — must produce no orders
        s.on_bar(_make_ohlcv("2025-01-02 15:07:00", 175.0))
        late_orders = s.generate_orders()
        assert late_orders == []


# ===========================================================================
# test_re_entry_logic
# ===========================================================================

class TestReEntryLogic:
    """Verify re-entry behaviour when both legs SL out."""

    def test_re_entry_enabled_default(self):
        IndianShortStraddle, *_ = _import_strategy()
        s = IndianShortStraddle(underlying="NIFTY")
        assert s.re_entry_enabled is True

    def test_re_entry_produces_two_new_sell_orders(self):
        IndianShortStraddle, _, _, _, StraddleState, *_ = _import_strategy()
        s = IndianShortStraddle(
            underlying="NIFTY",
            sl_mode="percentage",
            ce_sl_pct=25.0,
            pe_sl_pct=25.0,
            entry_time="09:20",
            exit_time="15:06",
            re_entry_enabled=True,
            re_entry_time="12:30",
            price_series_mode="premium",
        )
        s.start()

        # Initial entry
        s.on_bar(_make_ohlcv("2025-01-02 09:20:00", 200.0))
        entry_orders = s.generate_orders()
        assert len(entry_orders) == 2  # 2 SELLs

        # Blow through SL
        s.on_bar(_make_ohlcv("2025-01-02 09:21:00", 400.0))
        sl_orders = s.generate_orders()
        buy_backs = [o for o in sl_orders if o.action == "BUY"]
        assert len(buy_backs) == 2  # 2 buy-backs
        assert s.straddle_state == StraddleState.SL_HIT

        # Re-entry bar within window
        s.on_bar(_make_ohlcv("2025-01-02 10:00:00", 200.0))
        re_entry_orders = s.generate_orders()
        re_sells = [o for o in re_entry_orders if o.action == "SELL"]
        assert len(re_sells) == 2  # 2 new SELLs
        assert s.straddle_state == StraddleState.ACTIVE

    def test_re_entry_disabled(self):
        IndianShortStraddle, _, _, _, StraddleState, *_ = _import_strategy()
        s = IndianShortStraddle(
            underlying="NIFTY",
            sl_mode="percentage",
            ce_sl_pct=25.0,
            pe_sl_pct=25.0,
            entry_time="09:20",
            exit_time="15:06",
            re_entry_enabled=False,
            price_series_mode="premium",
        )
        s.start()
        s.on_bar(_make_ohlcv("2025-01-02 09:20:00", 200.0))
        s.generate_orders()

        s.on_bar(_make_ohlcv("2025-01-02 09:21:00", 400.0))
        s.generate_orders()
        assert s.straddle_state == StraddleState.SL_HIT

        # Next bar — should not re-enter
        s.on_bar(_make_ohlcv("2025-01-02 10:00:00", 200.0))
        orders = s.generate_orders()
        sells = [o for o in orders if o.action == "SELL"]
        assert sells == []
        assert s.straddle_state == StraddleState.SL_HIT


# ===========================================================================
# test_unknown_underlying_raises
# ===========================================================================

class TestUnknownUnderlyingRaises:
    """Verify that an unknown underlying raises a ValueError at construction."""

    def test_unknown_raises_value_error(self):
        IndianShortStraddle, *_ = _import_strategy()
        with pytest.raises(ValueError, match="Unknown underlying"):
            IndianShortStraddle(underlying="SENSEXNXT50")

    def test_known_underlyings_do_not_raise(self):
        IndianShortStraddle, *_ = _import_strategy()
        for sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY"):
            s = IndianShortStraddle(underlying=sym)
            assert s is not None

    def test_empty_string_raises(self):
        IndianShortStraddle, *_ = _import_strategy()
        with pytest.raises(ValueError):
            IndianShortStraddle(underlying="")


# ===========================================================================
# test_atr_indicator
# ===========================================================================

class TestATRIndicator:
    """Verify the atr() function in _indicators.py."""

    def test_atr_basic_length(self):
        from strategies._indicators import atr
        n = 30
        highs = [float(i + 2) for i in range(n)]
        lows = [float(i) for i in range(n)]
        closes = [float(i + 1) for i in range(n)]
        result = atr(highs, lows, closes, period=14)
        assert len(result) == n

    def test_atr_leading_zeros(self):
        from strategies._indicators import atr
        n = 20
        highs = [float(i + 2) for i in range(n)]
        lows = [float(i) for i in range(n)]
        closes = [float(i + 1) for i in range(n)]
        result = atr(highs, lows, closes, period=14)
        # First 13 values (indices 0..12) should be 0.0
        for v in result[:13]:
            assert v == 0.0

    def test_atr_positive_after_warmup(self):
        from strategies._indicators import atr
        import random
        random.seed(123)
        n = 50
        closes = [100.0 + random.uniform(-1, 1) for _ in range(n)]
        highs = [c + random.uniform(0.5, 2.0) for c in closes]
        lows = [c - random.uniform(0.5, 2.0) for c in closes]
        result = atr(highs, lows, closes, period=14)
        for v in result[14:]:
            assert v > 0.0

    def test_atr_empty_input(self):
        from strategies._indicators import atr
        assert atr([], [], [], period=14) == []

    def test_atr_in_all_exports(self):
        from strategies._indicators import __all__ as indicator_all
        assert "atr" in indicator_all


# ===========================================================================
# test_combined_sl_mode
# ===========================================================================

class TestCombinedSLMode:
    """Verify combined-premium SL mode."""

    def test_combined_sl_threshold_set_correctly(self):
        IndianShortStraddle, *_ = _import_strategy()
        s = IndianShortStraddle(
            underlying="NIFTY",
            sl_mode="combined",
            combined_sl_points=10.0,
            entry_time="09:20",
            price_series_mode="premium",
        )
        s.start()
        entry_bar = _make_ohlcv("2025-01-02 09:20:00", 200.0)
        s.on_bar(entry_bar)
        s.generate_orders()
        # Combined entry premium = 200; SL at 200 + 10 = 210
        assert abs(s._combined_sl_threshold - 210.0) < 0.1

    def test_combined_sl_exits_both_legs(self):
        IndianShortStraddle, *_ = _import_strategy()
        s = IndianShortStraddle(
            underlying="NIFTY",
            sl_mode="combined",
            combined_sl_points=5.0,
            entry_time="09:20",
            exit_time="15:06",
            price_series_mode="premium",
        )
        s.start()
        s.on_bar(_make_ohlcv("2025-01-02 09:20:00", 200.0))
        s.generate_orders()

        # Premium rises above threshold (200 + 5 = 205)
        s.on_bar(_make_ohlcv("2025-01-02 09:21:00", 220.0))
        orders = s.generate_orders()
        buy_orders = [o for o in orders if o.action == "BUY"]
        assert len(buy_orders) == 2


# ===========================================================================
# test_mtm_sl_mode
# ===========================================================================

class TestMTMSLMode:
    """Verify MTM-rupees SL and target modes."""

    def test_mtm_sl_triggers(self):
        IndianShortStraddle, *_ = _import_strategy()
        # 1 lot NIFTY = 75 shares; sell at 100 each; MTM SL at 1000 rupees
        # Pnl per unit change = 75; so 14 units move = ~1050 loss
        s = IndianShortStraddle(
            underlying="NIFTY",
            sl_mode="mtm_rupees",
            mtm_sl_rupees=1000.0,
            entry_time="09:20",
            exit_time="15:06",
            lots=1,
            price_series_mode="premium",
        )
        s.start()
        # Entry combined premium = 200 (each leg = 100)
        s.on_bar(_make_ohlcv("2025-01-02 09:20:00", 200.0))
        s.generate_orders()

        # After a significant premium rise, MTM loss should exceed threshold
        # (ce_sell - ce_ltp + pe_sell - pe_ltp) * qty < -1000
        # In premium mode, each leg = 100; if combined rises to 230, each leg = 115
        # pnl = (100 - 115 + 100 - 115) * 75 = -30 * 75 = -2250 < -1000 → exit
        s.on_bar(_make_ohlcv("2025-01-02 09:21:00", 230.0))
        orders = s.generate_orders()
        buy_orders = [o for o in orders if o.action == "BUY"]
        assert len(buy_orders) == 2

    def test_mtm_target_triggers(self):
        IndianShortStraddle, _, _, _, _, TargetMode, *_ = _import_strategy()
        s = IndianShortStraddle(
            underlying="NIFTY",
            sl_mode="mtm_rupees",
            target_mode="mtm_rupees",
            mtm_target_rupees=500.0,
            entry_time="09:20",
            exit_time="15:06",
            lots=1,
            price_series_mode="premium",
        )
        s.start()
        # Entry combined = 200; each leg = 100
        s.on_bar(_make_ohlcv("2025-01-02 09:20:00", 200.0))
        s.generate_orders()

        # Combined falls to 186; each leg = 93; pnl = (100-93+100-93)*75 = 14*75=1050 > 500
        s.on_bar(_make_ohlcv("2025-01-02 09:21:00", 186.0))
        orders = s.generate_orders()
        buy_orders = [o for o in orders if o.action == "BUY"]
        assert len(buy_orders) == 2


# ===========================================================================
# test_trailing_sl_mode
# ===========================================================================

class TestTrailingSLMode:
    """Verify trailing combined-premium SL."""

    def test_tsl_ratchets_as_premium_decays(self):
        """After decay, the TSL base should update."""
        IndianShortStraddle, *_ = _import_strategy()
        s = IndianShortStraddle(
            underlying="NIFTY",
            sl_mode="trailing",
            tsl_points=5.0,
            entry_time="09:20",
            exit_time="15:06",
            price_series_mode="premium",
        )
        s.start()
        s.on_bar(_make_ohlcv("2025-01-02 09:20:00", 200.0))
        s.generate_orders()
        initial_base = s._tsl_base

        # Premium decays by more than tsl_points
        s.on_bar(_make_ohlcv("2025-01-02 09:21:00", 190.0))
        s.generate_orders()
        # Base should have ratcheted down
        assert s._tsl_base < initial_base

    def test_tsl_exits_on_bounce(self):
        """After ratcheting, a bounce above the new SL threshold triggers exit."""
        IndianShortStraddle, *_ = _import_strategy()
        s = IndianShortStraddle(
            underlying="NIFTY",
            sl_mode="trailing",
            tsl_points=5.0,
            entry_time="09:20",
            exit_time="15:06",
            price_series_mode="premium",
        )
        s.start()
        s.on_bar(_make_ohlcv("2025-01-02 09:20:00", 200.0))
        s.generate_orders()

        # Decay to 185 — base ratchets to 185, new SL = 190
        s.on_bar(_make_ohlcv("2025-01-02 09:21:00", 185.0))
        s.generate_orders()

        # Bounce to 192 — above new SL of 190
        s.on_bar(_make_ohlcv("2025-01-02 09:22:00", 192.0))
        orders = s.generate_orders()
        buy_orders = [o for o in orders if o.action == "BUY"]
        assert len(buy_orders) == 2


# ===========================================================================
# test_quantity_calculation
# ===========================================================================

class TestQuantityCalculation:
    """Verify that order quantities match lots × lot_size."""

    def test_quantity_nifty_1_lot(self):
        IndianShortStraddle, *_ = _import_strategy()
        s = IndianShortStraddle(underlying="NIFTY", lots=1)
        # NIFTY lot size = 75
        assert s._quantity == 75

    def test_quantity_banknifty_2_lots(self):
        IndianShortStraddle, *_ = _import_strategy()
        s = IndianShortStraddle(underlying="BANKNIFTY", lots=2)
        # BANKNIFTY lot size = 15
        assert s._quantity == 30

    def test_quantity_sensex_3_lots(self):
        IndianShortStraddle, *_ = _import_strategy()
        s = IndianShortStraddle(underlying="SENSEX", lots=3)
        # SENSEX lot size = 10
        assert s._quantity == 30

    def test_order_quantity_matches_strategy_quantity(self):
        IndianShortStraddle, *_ = _import_strategy()
        s = IndianShortStraddle(underlying="NIFTY", lots=2, entry_time="09:20")
        s.start()
        s.on_bar(_make_ohlcv("2025-01-02 09:20:00", 19_000.0))
        orders = s.generate_orders()
        for o in orders:
            assert o.quantity == str(2 * 75)  # 150


# ===========================================================================
# test_registry
# ===========================================================================

class TestRegistry:
    """Verify IndianShortStraddle is accessible from the strategies package."""

    def test_in_all_strategies(self):
        from strategies import ALL_STRATEGIES
        assert "IndianShortStraddle" in ALL_STRATEGIES

    def test_class_matches(self):
        from strategies import ALL_STRATEGIES
        from strategies.options_short_straddle_indian import IndianShortStraddle
        assert ALL_STRATEGIES["IndianShortStraddle"] is IndianShortStraddle
