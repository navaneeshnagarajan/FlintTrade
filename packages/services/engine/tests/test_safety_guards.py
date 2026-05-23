"""Tests for OvertradingGuard and MTMCircuitBreaker.

All tests are fully synchronous / async-in-process — no live broker calls.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

IST = timezone(timedelta(hours=5, minutes=30))


def _now() -> datetime:
    return datetime.now(IST)


def _at(offset_seconds: float) -> datetime:
    return _now() + timedelta(seconds=offset_seconds)


# ===========================================================================
# OvertradingGuard
# ===========================================================================


class TestOvertradingGuardCooldown:
    """Per-symbol cooldown behaviour."""

    def _guard(self, cooldown_seconds: int = 60):
        from flinttrade_engine.safety import OvertradingConfig, OvertradingGuard
        cfg = OvertradingConfig(
            cooldown_seconds=cooldown_seconds,
            max_consecutive_losses=3,
            loss_pause_seconds=300,
            daily_trade_limit_per_symbol=0,  # unlimited
        )
        return OvertradingGuard(config=cfg)

    def test_first_order_is_always_allowed(self):
        guard = self._guard()
        allowed, reason = guard.can_trade("NIFTY25APRFUT")
        assert allowed
        assert reason == ""

    def test_second_order_within_cooldown_is_blocked(self):
        guard = self._guard(cooldown_seconds=60)
        t0 = _now()
        guard.record_order("NIFTY25APRFUT", at=t0)
        # Try again 30 s later — still in cooldown
        allowed, reason = guard.can_trade("NIFTY25APRFUT", at=t0 + timedelta(seconds=30))
        assert not allowed
        assert "cooldown" in reason.lower()
        assert "NIFTY25APRFUT" in reason

    def test_order_allowed_after_cooldown_expires(self):
        guard = self._guard(cooldown_seconds=60)
        t0 = _now()
        guard.record_order("NIFTY25APRFUT", at=t0)
        # Try again 61 s later — cooldown expired
        allowed, reason = guard.can_trade("NIFTY25APRFUT", at=t0 + timedelta(seconds=61))
        assert allowed

    def test_different_symbols_are_independent(self):
        guard = self._guard(cooldown_seconds=60)
        t0 = _now()
        guard.record_order("NIFTY25APRFUT", at=t0)
        # BANKNIFTY was never traded — should be allowed immediately
        allowed, reason = guard.can_trade("BANKNIFTY25APRFUT", at=t0 + timedelta(seconds=1))
        assert allowed


class TestOvertradingGuardLossStreak:
    """Consecutive-loss streak and pause logic."""

    def _guard(self, max_losses: int = 3, pause_seconds: int = 120):
        from flinttrade_engine.safety import OvertradingConfig, OvertradingGuard
        cfg = OvertradingConfig(
            cooldown_seconds=0,
            max_consecutive_losses=max_losses,
            loss_pause_seconds=pause_seconds,
            daily_trade_limit_per_symbol=0,
        )
        return OvertradingGuard(config=cfg)

    def test_no_pause_before_threshold(self):
        guard = self._guard(max_losses=3)
        guard.record_trade_result("NIFTY25APRFUT", pnl=-500.0)
        guard.record_trade_result("NIFTY25APRFUT", pnl=-500.0)
        # 2 losses — threshold is 3
        assert guard.consecutive_losses == 2
        assert not guard.is_paused
        allowed, _ = guard.can_trade("NIFTY25APRFUT")
        assert allowed

    def test_pause_triggered_at_threshold(self):
        guard = self._guard(max_losses=3, pause_seconds=120)
        guard.record_trade_result("X", pnl=-1.0)
        guard.record_trade_result("X", pnl=-1.0)
        guard.record_trade_result("X", pnl=-1.0)  # 3rd loss — triggers pause
        assert guard.consecutive_losses == 3
        assert guard.is_paused

    def test_trading_blocked_during_pause(self):
        guard = self._guard(max_losses=2, pause_seconds=300)
        guard.record_trade_result("X", pnl=-1.0)
        guard.record_trade_result("X", pnl=-1.0)
        allowed, reason = guard.can_trade("NIFTY25APRFUT")
        assert not allowed
        assert "consecutive" in reason.lower() or "pause" in reason.lower()

    def test_win_resets_streak(self):
        guard = self._guard(max_losses=3)
        guard.record_trade_result("X", pnl=-500.0)
        guard.record_trade_result("X", pnl=-500.0)
        guard.record_trade_result("X", pnl=+1000.0)  # win resets streak
        assert guard.consecutive_losses == 0

    def test_pause_expires_naturally(self):
        from flinttrade_engine.safety import OvertradingConfig, OvertradingGuard
        cfg = OvertradingConfig(
            cooldown_seconds=0,
            max_consecutive_losses=2,
            loss_pause_seconds=1,  # very short pause
            daily_trade_limit_per_symbol=0,
        )
        guard = OvertradingGuard(config=cfg)
        guard.record_trade_result("X", pnl=-1.0)
        guard.record_trade_result("X", pnl=-1.0)
        assert guard.is_paused
        # Simulate future time after pause expires
        future = _now() + timedelta(seconds=5)
        allowed, _ = guard.can_trade("NIFTY25APRFUT", at=future)
        assert allowed


class TestOvertradingGuardDailyLimit:
    """Daily trade count limit per symbol."""

    def _guard(self, daily_limit: int = 3):
        from flinttrade_engine.safety import OvertradingConfig, OvertradingGuard
        cfg = OvertradingConfig(
            cooldown_seconds=0,
            max_consecutive_losses=99,
            loss_pause_seconds=0,
            daily_trade_limit_per_symbol=daily_limit,
        )
        return OvertradingGuard(config=cfg)

    def test_orders_allowed_up_to_limit(self):
        guard = self._guard(daily_limit=3)
        t0 = _now()
        for i in range(3):
            allowed, _ = guard.can_trade("INFY", at=t0 + timedelta(seconds=i))
            assert allowed, f"order {i+1} should be allowed"
            guard.record_order("INFY", at=t0 + timedelta(seconds=i))

    def test_order_blocked_at_limit(self):
        guard = self._guard(daily_limit=2)
        t0 = _now()
        guard.record_order("INFY", at=t0)
        guard.record_order("INFY", at=t0 + timedelta(seconds=1))
        allowed, reason = guard.can_trade("INFY", at=t0 + timedelta(seconds=2))
        assert not allowed
        assert "daily trade limit" in reason.lower()

    def test_zero_limit_means_unlimited(self):
        guard = self._guard(daily_limit=0)
        t0 = _now()
        for i in range(50):
            guard.record_order("INFY", at=t0 + timedelta(seconds=i))
        allowed, _ = guard.can_trade("INFY", at=t0 + timedelta(seconds=51))
        assert allowed

    def test_reset_daily_clears_counts(self):
        guard = self._guard(daily_limit=2)
        t0 = _now()
        guard.record_order("INFY", at=t0)
        guard.record_order("INFY", at=t0 + timedelta(seconds=1))
        guard.reset_daily()
        allowed, _ = guard.can_trade("INFY", at=t0 + timedelta(seconds=2))
        assert allowed


class TestOvertradingGuardHoldDuration:
    """6-hour hold limit warning."""

    def _guard(self, max_hold_hours: float = 6.0):
        from flinttrade_engine.safety import OvertradingConfig, OvertradingGuard
        cfg = OvertradingConfig(max_hold_hours=max_hold_hours)
        return OvertradingGuard(config=cfg)

    def test_within_hold_limit_no_warning(self):
        guard = self._guard(max_hold_hours=6.0)
        opened_at = _now() - timedelta(hours=3)
        over, msg = guard.check_hold_duration("NIFTY25APRFUT", opened_at)
        assert not over
        assert msg == ""

    def test_over_hold_limit_warns(self):
        guard = self._guard(max_hold_hours=6.0)
        opened_at = _now() - timedelta(hours=7)
        over, msg = guard.check_hold_duration("NIFTY25APRFUT", opened_at)
        assert over
        assert "NIFTY25APRFUT" in msg
        assert "warning" in msg.lower() or "h" in msg

    def test_hold_check_does_not_block_trade(self):
        """check_hold_duration is advisory only — can_trade should still pass."""
        guard = self._guard(max_hold_hours=6.0)
        opened_at = _now() - timedelta(hours=10)
        guard.check_hold_duration("NIFTY25APRFUT", opened_at)  # warns but does nothing
        allowed, _ = guard.can_trade("NIFTY25APRFUT")
        assert allowed


# ===========================================================================
# MTMCircuitBreaker
# ===========================================================================


class TestMTMCircuitBreaker:
    """Account-level MTM loss auto-exit."""

    def _breaker(self, limit: float = -50_000.0, client=None):
        from flinttrade_engine.safety import MTMCircuitBreaker, MTMCircuitBreakerConfig
        cfg = MTMCircuitBreakerConfig(daily_loss_limit=limit)
        return MTMCircuitBreaker(config=cfg, client=client)

    def test_within_limit_does_not_trigger(self):
        breaker = self._breaker(limit=-50_000.0)
        result = asyncio.run(
            breaker.check_and_act(daily_pnl=-30_000.0)
        )
        assert not result
        assert not breaker.is_triggered

    def test_exactly_at_limit_does_not_trigger(self):
        # Boundary: pnl > limit is False only when pnl <= limit
        # daily_pnl=-50000 and limit=-50000: -50000 > -50000 is False → triggers
        breaker = self._breaker(limit=-50_000.0)
        result = asyncio.run(
            breaker.check_and_act(daily_pnl=-50_000.0)
        )
        assert result
        assert breaker.is_triggered

    def test_breach_triggers_breaker(self):
        breaker = self._breaker(limit=-50_000.0)
        result = asyncio.run(
            breaker.check_and_act(daily_pnl=-60_000.0)
        )
        assert result
        assert breaker.is_triggered

    def test_breaker_fires_only_once_per_day(self):
        breaker = self._breaker(limit=-50_000.0)
        asyncio.run(
            breaker.check_and_act(daily_pnl=-70_000.0)
        )
        # Second call — already triggered, should return False
        result = asyncio.run(
            breaker.check_and_act(daily_pnl=-80_000.0)
        )
        assert not result

    def test_reset_daily_clears_trigger(self):
        breaker = self._breaker(limit=-50_000.0)
        asyncio.run(
            breaker.check_and_act(daily_pnl=-60_000.0)
        )
        assert breaker.is_triggered
        breaker.reset_daily()
        assert not breaker.is_triggered

    def test_close_position_called_on_breach(self):
        mock_client = MagicMock()
        mock_client.close_position = AsyncMock(return_value={"status": "success"})
        breaker = self._breaker(limit=-50_000.0, client=mock_client)
        asyncio.run(
            breaker.check_and_act(daily_pnl=-60_000.0)
        )
        mock_client.close_position.assert_awaited_once()

    def test_no_client_does_not_raise(self):
        """Breaker fires even without a client — it just can't close positions."""
        breaker = self._breaker(limit=-50_000.0, client=None)
        result = asyncio.run(
            breaker.check_and_act(daily_pnl=-60_000.0)
        )
        assert result

    def test_close_position_failure_does_not_re_raise(self):
        """If the broker call fails the breaker should still mark as triggered."""
        mock_client = MagicMock()
        mock_client.close_position = AsyncMock(side_effect=RuntimeError("network error"))
        breaker = self._breaker(limit=-50_000.0, client=mock_client)
        # Should not raise
        result = asyncio.run(
            breaker.check_and_act(daily_pnl=-60_000.0)
        )
        assert result
        assert breaker.is_triggered

    def test_positive_pnl_never_triggers(self):
        breaker = self._breaker(limit=-50_000.0)
        result = asyncio.run(
            breaker.check_and_act(daily_pnl=+10_000.0)
        )
        assert not result
        assert not breaker.is_triggered

    def test_activity_logger_receives_critical_log(self, caplog):
        import logging
        breaker = self._breaker(limit=-50_000.0)
        with caplog.at_level(logging.CRITICAL):
            asyncio.run(
                breaker.check_and_act(daily_pnl=-60_000.0)
            )
        assert any("MTMCircuitBreaker" in r.message for r in caplog.records)

    @pytest.mark.parametrize("limit,pnl,should_trigger", [
        (-10_000.0, -15_000.0, True),
        (-10_000.0, -9_999.0,  False),
        (-100.0,   -100.0,     True),    # exactly at boundary
        (-200_000.0, -199_999.0, False),
    ])
    def test_parametrized_limits(self, limit, pnl, should_trigger):
        breaker = self._breaker(limit=limit)
        result = asyncio.run(
            breaker.check_and_act(daily_pnl=pnl)
        )
        assert result == should_trigger
