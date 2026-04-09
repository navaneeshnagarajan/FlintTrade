"""Tests for straddle_strategies module.

Covers:
- ATM strike calculation for all supported indices.
- MTMStraddleStrategy: entry, target exit, stop-loss exit, squareoff-time exit.
- TrailingStopStraddle: entry, ratchet mechanics, stop trigger, squareoff exit.
- CombinedPremiumStraddle: entry on premium threshold, target exit, stop exit.
- MTMMonitor: position management, MTM calculation, loss breach, profit target,
  squareoff time, graceful no-position handling.
"""

from __future__ import annotations

from datetime import date, time as dtime
from typing import Callable
from unittest.mock import MagicMock, call, patch

import pytest

from packages.engine.src.straddle_strategies import (
    CombinedPremiumConfig,
    CombinedPremiumStraddle,
    ExitReason,
    MTMMonitor,
    MTMMonitorConfig,
    MTMStraddleConfig,
    MTMStraddleStrategy,
    OptionPosition,
    StrategyState,
    TrailingStopConfig,
    TrailingStopStraddle,
    _atm_strike,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _noop_ltp(_index: str, _exch: str) -> float:
    return 45_000.0


def _noop_expiry(_index: str) -> date:
    return date(2026, 5, 29)


def _noop_symbols(_index: str, _expiry: date, _strike: int) -> tuple[str, str]:
    return ("BANKNIFTY29MAY2645000CE", "BANKNIFTY29MAY2645000PE")


def _noop_option_ltp(_ce: str, _pe: str, _exch: str) -> tuple[float, float]:
    return (200.0, 200.0)


def _noop_sell(_sym: str, _qty: int, _exch: str) -> str:
    return "ORD001"


def _noop_buy(_sym: str, _qty: int, _exch: str) -> str:
    return "ORD002"


# ---------------------------------------------------------------------------
# _atm_strike
# ---------------------------------------------------------------------------


class TestATMStrike:
    def test_banknifty_rounds_to_nearest_100(self) -> None:
        assert _atm_strike(45_049.0, "BANKNIFTY") == 45_000
        assert _atm_strike(45_050.0, "BANKNIFTY") == 45_100
        assert _atm_strike(45_075.0, "BANKNIFTY") == 45_100

    def test_nifty_rounds_to_nearest_50(self) -> None:
        assert _atm_strike(22_024.0, "NIFTY") == 22_000
        assert _atm_strike(22_025.0, "NIFTY") == 22_050
        assert _atm_strike(22_060.0, "NIFTY") == 22_050

    def test_finnifty_rounds_to_nearest_50(self) -> None:
        assert _atm_strike(21_024.0, "FINNIFTY") == 21_000

    def test_sensex_rounds_to_nearest_100(self) -> None:
        assert _atm_strike(75_049.0, "SENSEX") == 75_000
        assert _atm_strike(75_099.0, "SENSEX") == 75_100

    def test_exact_strike(self) -> None:
        assert _atm_strike(45_000.0, "BANKNIFTY") == 45_000

    def test_unknown_index_defaults_to_50_step(self) -> None:
        # Unknown index uses default step of 50
        assert _atm_strike(22_024.0, "UNKNOWN") == 22_000


# ---------------------------------------------------------------------------
# StraddleConfig / MTMStraddleConfig
# ---------------------------------------------------------------------------


class TestStraddleConfig:
    def test_defaults(self) -> None:
        cfg = MTMStraddleConfig()
        assert cfg.index == "BANKNIFTY"
        assert cfg.lots == 1
        assert cfg.entry_time == dtime(9, 20)
        assert cfg.squareoff_time == dtime(15, 15)
        assert cfg.quantity == cfg.lots * cfg.lot_size

    def test_exchange_derived_from_index(self) -> None:
        cfg = MTMStraddleConfig(index="SENSEX")
        assert cfg.exchange == "BFO"

    def test_explicit_exchange_not_overridden(self) -> None:
        cfg = MTMStraddleConfig(index="BANKNIFTY", exchange="CUSTOM")
        assert cfg.exchange == "CUSTOM"

    def test_quantity(self) -> None:
        cfg = MTMStraddleConfig(lots=3, lot_size=25)
        assert cfg.quantity == 75


# ---------------------------------------------------------------------------
# MTMStraddleStrategy
# ---------------------------------------------------------------------------


class TestMTMStraddleStrategy:
    def _make_strategy(
        self,
        option_ltp_fn=None,
        **config_kwargs,
    ) -> MTMStraddleStrategy:
        if option_ltp_fn is None:
            option_ltp_fn = _noop_option_ltp
        cfg = MTMStraddleConfig(
            lots=1,
            lot_size=25,
            entry_hour=9,
            entry_minute=20,
            squareoff_hour=15,
            squareoff_minute=15,
            **config_kwargs,
        )
        return MTMStraddleStrategy(
            config=cfg,
            get_index_ltp=_noop_ltp,
            get_expiry=_noop_expiry,
            get_option_symbols=_noop_symbols,
            get_option_ltp=option_ltp_fn,
            place_sell=_noop_sell,
            place_buy=_noop_buy,
        )

    def test_initial_state(self) -> None:
        s = self._make_strategy()
        assert s.state == StrategyState.WAITING

    def test_enter_sets_state_and_premium(self) -> None:
        s = self._make_strategy()
        s._enter()
        assert s.state == StrategyState.ENTERED
        # premium_collected = (200+200) * 25 = 10_000
        assert s.premium_collected == pytest.approx(10_000.0)

    def test_target_exit(self) -> None:
        """MTM >= 50 % of premium_collected triggers TARGET exit."""
        call_count = 0

        def option_ltp_after_drop(_ce, _pe, _exch):
            nonlocal call_count
            call_count += 1
            # First call (entry): 200+200
            # Subsequent calls (monitoring): drop to 100+100 → MTM = 5000
            if call_count == 1:
                return (200.0, 200.0)
            return (100.0, 100.0)

        s = self._make_strategy(option_ltp_fn=option_ltp_after_drop, target_pct=0.5)
        s._enter()
        # premium_collected = 10_000; target = 5_000
        result = s._check_exit_conditions()
        assert not result
        assert s.exit_reason == ExitReason.TARGET
        assert s.state == StrategyState.EXITED
        assert s.final_pnl == pytest.approx(5_000.0)

    def test_stoploss_exit(self) -> None:
        """MTM loss >= stoploss_pct triggers STOPLOSS exit."""
        call_count = 0

        def rising_option_ltp(_ce, _pe, _exch):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (200.0, 200.0)
            return (400.0, 400.0)  # premium doubled → MTM loss

        s = self._make_strategy(option_ltp_fn=rising_option_ltp, stoploss_pct=1.0)
        s._enter()
        # premium_collected = 10_000; stoploss threshold = -10_000
        # current_value = 20_000; MTM = 10_000 - 20_000 = -10_000 (exactly at boundary)
        result = s._check_exit_conditions()
        assert not result
        assert s.exit_reason == ExitReason.STOPLOSS

    def test_squareoff_time_exit(self) -> None:
        """Position closes at squareoff time even without target/SL hit."""
        s = self._make_strategy()
        s._enter()

        with patch(
            "packages.engine.src.straddle_strategies._current_time",
            return_value=dtime(15, 16),
        ):
            result = s._check_exit_conditions()

        assert not result
        assert s.exit_reason == ExitReason.SQUAREOFF_TIME
        assert s.state == StrategyState.EXITED

    def test_buy_orders_called_on_exit(self) -> None:
        """Both CE and PE buy orders must be placed on exit."""
        buy_calls: list[tuple] = []

        def tracking_buy(sym, qty, exch):
            buy_calls.append((sym, qty, exch))
            return "EXIT_ORD"

        cfg = MTMStraddleConfig(lots=1, lot_size=25, target_pct=0.5)
        s = MTMStraddleStrategy(
            config=cfg,
            get_index_ltp=_noop_ltp,
            get_expiry=_noop_expiry,
            get_option_symbols=_noop_symbols,
            get_option_ltp=_noop_option_ltp,
            place_sell=_noop_sell,
            place_buy=tracking_buy,
        )
        s._exit(ExitReason.MANUAL, 0.0)
        assert len(buy_calls) == 2

    def test_tick_returns_false_after_exit(self) -> None:
        s = self._make_strategy()
        s._enter()
        s.state = StrategyState.EXITED
        assert s.tick() is False


# ---------------------------------------------------------------------------
# TrailingStopStraddle
# ---------------------------------------------------------------------------


class TestTrailingStopStraddle:
    def _make_strategy(self, option_ltp_fn=None, **config_kwargs) -> TrailingStopStraddle:
        if option_ltp_fn is None:
            option_ltp_fn = _noop_option_ltp
        cfg = TrailingStopConfig(
            lots=1,
            lot_size=25,
            initial_sl_pct=0.5,
            trail_pct=0.0,
            trail_step=5.0,
            **config_kwargs,
        )
        return TrailingStopStraddle(
            config=cfg,
            get_index_ltp=_noop_ltp,
            get_expiry=_noop_expiry,
            get_option_symbols=_noop_symbols,
            get_option_ltp=option_ltp_fn,
            place_sell=_noop_sell,
            place_buy=_noop_buy,
        )

    def test_initial_stop_set_on_entry(self) -> None:
        s = self._make_strategy()
        s._enter()
        # sell_premium = 400; initial_sl = 0.5 × 400 = 200; stop = 600
        assert s.sell_premium == pytest.approx(400.0)
        assert s.stop_premium == pytest.approx(600.0)

    def test_no_ratchet_before_trail_step(self) -> None:
        """Premium must drop by trail_step before ratchet fires."""
        call_count = 0
        initial_stop = None

        def slight_drop(_ce, _pe, _exch):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (200.0, 200.0)
            return (197.0, 197.0)  # drop = 6 → >= trail_step 5

        s = self._make_strategy(option_ltp_fn=slight_drop)
        s._enter()
        initial_stop = s.stop_premium
        # First monitoring call: premium drops 6 pts — ratchet should fire.
        with patch(
            "packages.engine.src.straddle_strategies._current_time",
            return_value=dtime(10, 0),
        ):
            s._check_exit_conditions()
        # Ratchet: new stop = (394) + 0.5*400 = 394+200 = 594 < 600 → stop tightened.
        assert s.stop_premium < initial_stop

    def test_ratchet_only_moves_stop_lower(self) -> None:
        """Ratchet never moves stop higher (one-directional)."""
        call_count = 0

        def premium_sequence(_ce, _pe, _exch):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (200.0, 200.0)
            # Drop further — triggers ratchet
            if call_count == 2:
                return (190.0, 190.0)
            # Rise back but still below stop
            return (195.0, 195.0)

        s = self._make_strategy(option_ltp_fn=premium_sequence)
        s._enter()
        stop_after_entry = s.stop_premium

        with patch(
            "packages.engine.src.straddle_strategies._current_time",
            return_value=dtime(10, 0),
        ):
            s._check_exit_conditions()  # premium drops — ratchet fires
        stop_after_ratchet = s.stop_premium

        with patch(
            "packages.engine.src.straddle_strategies._current_time",
            return_value=dtime(10, 0),
        ):
            s._check_exit_conditions()  # premium rises slightly — no ratchet back up
        assert s.stop_premium == stop_after_ratchet
        assert stop_after_ratchet <= stop_after_entry

    def test_trailing_sl_exit_on_premium_rise(self) -> None:
        """When premium rises above stop, TRAILING_SL exit fires."""
        call_count = 0

        def premium_fn(_ce, _pe, _exch):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (200.0, 200.0)
            return (350.0, 350.0)  # 700 > stop 600

        s = self._make_strategy(option_ltp_fn=premium_fn)
        s._enter()
        with patch(
            "packages.engine.src.straddle_strategies._current_time",
            return_value=dtime(10, 0),
        ):
            result = s._check_exit_conditions()
        assert not result
        assert s.exit_reason == ExitReason.TRAILING_SL

    def test_squareoff_time_exit(self) -> None:
        s = self._make_strategy()
        s._enter()
        with patch(
            "packages.engine.src.straddle_strategies._current_time",
            return_value=dtime(15, 16),
        ):
            result = s._check_exit_conditions()
        assert not result
        assert s.exit_reason == ExitReason.SQUAREOFF_TIME

    def test_tick_false_when_not_entered(self) -> None:
        s = self._make_strategy()
        assert s.tick() is False


# ---------------------------------------------------------------------------
# CombinedPremiumStraddle
# ---------------------------------------------------------------------------


class TestCombinedPremiumStraddle:
    def _make_strategy(self, option_ltp_fn=None, **config_kwargs) -> CombinedPremiumStraddle:
        if option_ltp_fn is None:
            option_ltp_fn = _noop_option_ltp
        defaults = dict(lots=1, lot_size=25, min_premium=0.0, target_drop=50.0, stop_rise=30.0)
        defaults.update(config_kwargs)
        cfg = CombinedPremiumConfig(**defaults)
        return CombinedPremiumStraddle(
            config=cfg,
            get_index_ltp=_noop_ltp,
            get_expiry=_noop_expiry,
            get_option_symbols=_noop_symbols,
            get_option_ltp=option_ltp_fn,
            place_sell=_noop_sell,
            place_buy=_noop_buy,
        )

    def test_enter_sets_entry_premium(self) -> None:
        s = self._make_strategy()
        s._resolve_symbols()
        s._enter()
        assert s.entry_premium == pytest.approx(400.0)
        assert s.state == StrategyState.ENTERED

    def test_target_exit_on_premium_drop(self) -> None:
        """Premium drops by target_drop → TARGET exit."""
        call_count = 0

        def drop_fn(_ce, _pe, _exch):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (200.0, 200.0)
            return (175.0, 175.0)  # drop = 50 >= target_drop 50

        s = self._make_strategy(option_ltp_fn=drop_fn, target_drop=50.0)
        s._resolve_symbols()
        s._enter()
        with patch(
            "packages.engine.src.straddle_strategies._current_time",
            return_value=dtime(10, 0),
        ):
            result = s._check_exit_conditions()
        assert not result
        assert s.exit_reason == ExitReason.TARGET
        assert s.final_pnl == pytest.approx(50.0 * 25)

    def test_stop_exit_on_premium_rise(self) -> None:
        """Premium rises by stop_rise → STOPLOSS exit."""
        call_count = 0

        def rise_fn(_ce, _pe, _exch):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (200.0, 200.0)
            return (215.0, 215.0)  # rise = 30 >= stop_rise 30

        s = self._make_strategy(option_ltp_fn=rise_fn, stop_rise=30.0)
        s._resolve_symbols()
        s._enter()
        with patch(
            "packages.engine.src.straddle_strategies._current_time",
            return_value=dtime(10, 0),
        ):
            result = s._check_exit_conditions()
        assert not result
        assert s.exit_reason == ExitReason.STOPLOSS

    def test_wait_for_premium_exits_at_squareoff(self) -> None:
        """_wait_for_premium returns False when squareoff time is reached."""
        s = self._make_strategy(min_premium=1_000.0)  # unreachable threshold
        s._resolve_symbols()
        with patch(
            "packages.engine.src.straddle_strategies._current_time",
            return_value=dtime(15, 16),  # already past squareoff
        ):
            result = s._wait_for_premium()
        assert result is False

    def test_wait_for_premium_returns_true_on_threshold_met(self) -> None:
        s = self._make_strategy(min_premium=300.0)  # 400 combined > 300
        s._resolve_symbols()
        with patch(
            "packages.engine.src.straddle_strategies._current_time",
            return_value=dtime(10, 0),
        ):
            result = s._wait_for_premium()
        assert result is True

    def test_zero_min_premium_skips_threshold_wait(self) -> None:
        """min_premium=0 should return True immediately."""
        s = self._make_strategy(min_premium=0.0)
        s._resolve_symbols()
        result = s._wait_for_premium()
        assert result is True

    def test_tick_returns_false_when_not_entered(self) -> None:
        s = self._make_strategy()
        assert s.tick() is False


# ---------------------------------------------------------------------------
# MTMMonitor
# ---------------------------------------------------------------------------


class TestMTMMonitor:
    def _make_monitor(
        self,
        ltp_fn: Callable | None = None,
        max_loss: float = 10_000.0,
        max_profit: float = 0.0,
    ) -> MTMMonitor:
        if ltp_fn is None:
            ltp_fn = lambda _sym, _exch: 200.0  # noqa: E731
        cfg = MTMMonitorConfig(
            max_loss=max_loss,
            max_profit=max_profit,
            squareoff_hour=15,
            squareoff_minute=15,
            poll_interval=0.01,
        )
        return MTMMonitor(
            config=cfg,
            get_option_ltp=ltp_fn,
            place_buy=_noop_buy,
            place_sell=_noop_sell,
        )

    def _short_pos(
        self,
        symbol: str = "NIFTY30DEC2523500CE",
        quantity: int = 50,
        entry_price: float = 250.0,
    ) -> OptionPosition:
        return OptionPosition(
            symbol=symbol,
            exchange="NFO",
            direction="SELL",
            quantity=quantity,
            entry_price=entry_price,
        )

    def test_add_and_remove_position(self) -> None:
        m = self._make_monitor()
        pos = self._short_pos()
        m.add_position(pos)
        assert len(m._positions) == 1
        m.remove_position(pos.symbol)
        assert len(m._positions) == 0

    def test_clear_positions(self) -> None:
        m = self._make_monitor()
        m.add_position(self._short_pos("CE1"))
        m.add_position(self._short_pos("CE2"))
        m.clear_positions()
        assert m._positions == []

    def test_mtm_sell_position_profit(self) -> None:
        """Sell position: LTP dropped → profit."""
        m = self._make_monitor(ltp_fn=lambda _s, _e: 200.0)
        m.add_position(
            OptionPosition(symbol="CE", exchange="NFO", direction="SELL", quantity=50, entry_price=250.0)
        )
        mtm = m.calculate_mtm()
        # (250 - 200) * 50 = 2500
        assert mtm == pytest.approx(2_500.0)

    def test_mtm_sell_position_loss(self) -> None:
        """Sell position: LTP rose → loss (negative MTM)."""
        m = self._make_monitor(ltp_fn=lambda _s, _e: 300.0)
        m.add_position(
            OptionPosition(symbol="CE", exchange="NFO", direction="SELL", quantity=50, entry_price=250.0)
        )
        mtm = m.calculate_mtm()
        # (250 - 300) * 50 = -2500
        assert mtm == pytest.approx(-2_500.0)

    def test_mtm_buy_position(self) -> None:
        """Buy position: LTP rose → profit."""
        m = self._make_monitor(ltp_fn=lambda _s, _e: 300.0)
        m.add_position(
            OptionPosition(symbol="PE", exchange="NFO", direction="BUY", quantity=25, entry_price=250.0)
        )
        mtm = m.calculate_mtm()
        # (300 - 250) * 25 = 1250
        assert mtm == pytest.approx(1_250.0)

    def test_loss_breach_triggers_squareoff(self) -> None:
        """MTM loss >= max_loss triggers square-off."""
        buy_calls: list[str] = []

        def track_buy(sym, qty, exch):
            buy_calls.append(sym)
            return "ORD"

        # LTP at 500 vs entry 250 → loss = (250-500)*50 = -12500 >= max_loss 10000
        m = self._make_monitor(ltp_fn=lambda _s, _e: 500.0, max_loss=10_000.0)
        m.add_position(
            OptionPosition(symbol="CE", exchange="NFO", direction="SELL", quantity=50, entry_price=250.0)
        )
        cfg = MTMMonitorConfig(max_loss=10_000.0, poll_interval=0.01)
        m2 = MTMMonitor(
            config=cfg,
            get_option_ltp=lambda _s, _e: 500.0,
            place_buy=track_buy,
            place_sell=_noop_sell,
        )
        m2.add_position(
            OptionPosition(symbol="CE", exchange="NFO", direction="SELL", quantity=50, entry_price=250.0)
        )
        result = m2.tick()
        assert result is False
        assert m2.squaredoff is True
        assert m2.squaredoff_reason == "MAX_LOSS_BREACH"
        assert "CE" in buy_calls

    def test_profit_target_triggers_squareoff(self) -> None:
        """MTM profit >= max_profit triggers square-off."""
        buy_calls: list[str] = []

        def track_buy(sym, qty, exch):
            buy_calls.append(sym)
            return "ORD"

        cfg = MTMMonitorConfig(max_loss=100_000.0, max_profit=2_500.0, poll_interval=0.01)
        m = MTMMonitor(
            config=cfg,
            # LTP 200 vs entry 250 → profit = (250-200)*50 = 2500 = max_profit
            get_option_ltp=lambda _s, _e: 200.0,
            place_buy=track_buy,
            place_sell=_noop_sell,
        )
        m.add_position(
            OptionPosition(symbol="CE", exchange="NFO", direction="SELL", quantity=50, entry_price=250.0)
        )
        result = m.tick()
        assert result is False
        assert m.squaredoff_reason == "MAX_PROFIT_REACHED"

    def test_squareoff_time_triggers_squareoff(self) -> None:
        """At squareoff time, positions are closed regardless of P&L."""
        cfg = MTMMonitorConfig(
            max_loss=999_999.0,
            squareoff_hour=15,
            squareoff_minute=15,
            poll_interval=0.01,
        )
        m = MTMMonitor(
            config=cfg,
            get_option_ltp=lambda _s, _e: 250.0,  # breakeven
            place_buy=_noop_buy,
            place_sell=_noop_sell,
        )
        m.add_position(
            OptionPosition(symbol="CE", exchange="NFO", direction="SELL", quantity=50, entry_price=250.0)
        )
        with patch(
            "packages.engine.src.straddle_strategies._current_time",
            return_value=dtime(15, 16),
        ):
            result = m.tick()
        assert result is False
        assert m.squaredoff_reason == "SQUAREOFF_TIME"

    def test_no_positions_does_not_crash(self) -> None:
        """Monitor with no positions returns valid (0.0) MTM."""
        m = self._make_monitor()
        assert m.calculate_mtm() == pytest.approx(0.0)

    def test_multiple_positions_aggregated(self) -> None:
        """MTM is summed across all positions."""
        # CE: sell 50 @ 250, ltp 200 → +2500
        # PE: sell 50 @ 200, ltp 250 → -2500
        def ltp_fn(sym, _exch):
            if "CE" in sym:
                return 200.0
            return 250.0

        m = self._make_monitor(ltp_fn=ltp_fn)
        m.add_position(OptionPosition(symbol="CE", exchange="NFO", direction="SELL", quantity=50, entry_price=250.0))
        m.add_position(OptionPosition(symbol="PE", exchange="NFO", direction="SELL", quantity=50, entry_price=200.0))
        assert m.calculate_mtm() == pytest.approx(0.0)

    def test_stop_method_stops_run(self) -> None:
        """stop() sets _running=False so run() exits."""
        m = self._make_monitor()

        import threading

        t = threading.Thread(target=m.run, daemon=True)
        t.start()
        m.stop()
        t.join(timeout=1.0)
        assert not t.is_alive()
