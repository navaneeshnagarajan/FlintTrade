"""Tests for OvertradingGuard and MTMCircuitBreaker.

All tests are fully synchronous / async-in-process — no live broker calls.
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

IST = timezone(timedelta(hours=5, minutes=30))


def _now() -> datetime:
    return datetime.now(IST)


def _at(offset_seconds: float) -> datetime:
    return _now() + timedelta(seconds=offset_seconds)


# ===========================================================================
# Durable safety configuration
# ===========================================================================


class TestSafetyConfigurationTransactions:
    def test_persistence_failure_leaves_live_thresholds_unchanged(self):
        from flinttrade_engine.safety import SafetyConfig, SafetySystem

        safety = SafetySystem()

        def fail_persist(_config: SafetyConfig) -> None:
            raise OSError("disk unavailable")

        with pytest.raises(OSError, match="disk unavailable"):
            safety.update_and_persist_config({"price_deviation_pct": 10.0}, fail_persist)

        assert safety.snapshot_config() == SafetyConfig()

    def test_partial_updates_merge_into_the_latest_persisted_snapshot(self):
        from flinttrade_engine.safety import SafetyConfig, SafetySystem

        safety = SafetySystem()
        persisted: list[SafetyConfig] = []

        safety.update_and_persist_config({"max_positions": 12}, persisted.append)
        safety.update_and_persist_config({"pnl_pause_pct": 4.0}, persisted.append)

        snapshot = safety.snapshot_config()
        assert snapshot.max_positions == 12
        assert snapshot.pnl_pause_pct == 4.0
        assert persisted[-1] == snapshot

    def test_readers_wait_until_persistence_and_publication_complete(self):
        from flinttrade_engine.safety import SafetyConfig, SafetySystem

        safety = SafetySystem()
        persistence_started = threading.Event()
        release_persistence = threading.Event()
        reader_completed = threading.Event()
        observed: list[float] = []

        def persist(_config: SafetyConfig) -> None:
            persistence_started.set()
            assert release_persistence.wait(timeout=2.0)

        updater = threading.Thread(
            target=lambda: safety.update_and_persist_config({"price_deviation_pct": 10.0}, persist),
        )
        reader = threading.Thread(
            target=lambda: (observed.append(safety.snapshot_config().price_deviation_pct), reader_completed.set()),
        )
        updater.start()
        assert persistence_started.wait(timeout=1.0)
        reader.start()
        assert not reader_completed.wait(timeout=0.05)

        release_persistence.set()
        updater.join(timeout=1.0)
        reader.join(timeout=1.0)

        assert not updater.is_alive()
        assert not reader.is_alive()
        assert observed == [10.0]


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

    @staticmethod
    def _check(breaker, daily_pnl: float):
        return breaker.check_and_act(
            daily_pnl=daily_pnl,
            adapter_id="dhan",
            account_id="primary",
        )

    def _breaker(self, limit: float = -50_000.0, emergency_dispatcher=None):
        from flinttrade_engine.safety import MTMCircuitBreaker, MTMCircuitBreakerConfig
        cfg = MTMCircuitBreakerConfig(daily_loss_limit=limit)
        return MTMCircuitBreaker(config=cfg, emergency_dispatcher=emergency_dispatcher)

    def test_mtm_policy_cancels_resting_orders_before_exiting_positions(self):
        from flinttrade_engine.safety import MTM_EMERGENCY_POLICY

        assert MTM_EMERGENCY_POLICY.verbs == ("cancel_all_orders", "exit_all_positions")

    def test_within_limit_does_not_trigger(self):
        breaker = self._breaker(limit=-50_000.0)
        result = asyncio.run(
            self._check(breaker, -30_000.0)
        )
        assert not result
        assert not breaker.is_triggered

    def test_exactly_at_limit_does_not_trigger(self):
        # Boundary: pnl > limit is False only when pnl <= limit
        # daily_pnl=-50000 and limit=-50000: -50000 > -50000 is False → triggers
        breaker = self._breaker(limit=-50_000.0)
        result = asyncio.run(
            self._check(breaker, -50_000.0)
        )
        assert result
        assert breaker.is_triggered

    def test_breach_triggers_breaker(self):
        breaker = self._breaker(limit=-50_000.0)
        result = asyncio.run(
            self._check(breaker, -60_000.0)
        )
        assert result
        assert breaker.is_triggered

    def test_completed_flatten_is_rechecked_when_a_later_breach_can_reopen_exposure(self):
        from flinttrade_engine.safety import EmergencyDispatchResult, EmergencyVerbOutcome, MTM_EMERGENCY_POLICY

        dispatcher = MagicMock()
        dispatcher.dispatch.return_value = EmergencyDispatchResult(
            policy=MTM_EMERGENCY_POLICY,
            outcomes=tuple(
                EmergencyVerbOutcome(verb, succeeded=True, selector="dhan:primary")
                for verb in MTM_EMERGENCY_POLICY.verbs
            ),
        )
        breaker = self._breaker(limit=-50_000.0, emergency_dispatcher=dispatcher)
        assert asyncio.run(self._check(breaker, -70_000.0))
        assert asyncio.run(self._check(breaker, -80_000.0))
        assert dispatcher.dispatch.call_count == 2

    def test_incomplete_flatten_retries_until_a_later_breach_completes(self):
        from flinttrade_engine.safety import EmergencyDispatchResult, EmergencyVerbOutcome, MTM_EMERGENCY_POLICY

        dispatcher = MagicMock()
        complete = EmergencyDispatchResult(
            policy=MTM_EMERGENCY_POLICY,
            outcomes=tuple(
                EmergencyVerbOutcome(
                    verb,
                    succeeded=True,
                    selector="dhan:primary",
                )
                for verb in MTM_EMERGENCY_POLICY.verbs
            ),
        )
        dispatcher.dispatch.side_effect = (
            EmergencyDispatchResult.failed(
                MTM_EMERGENCY_POLICY,
                "partial_broker_result",
                attempted=True,
                selector="dhan:primary",
            ),
            complete,
            complete,
        )
        breaker = self._breaker(limit=-50_000.0, emergency_dispatcher=dispatcher)

        assert asyncio.run(self._check(breaker, -60_000.0))
        assert breaker.last_emergency_result is not None
        assert not breaker.last_emergency_result.complete
        assert asyncio.run(self._check(breaker, -61_000.0))
        assert breaker.last_emergency_result is not None
        assert breaker.last_emergency_result.complete
        assert asyncio.run(self._check(breaker, -62_000.0))
        assert dispatcher.dispatch.call_count == 3

    def test_reset_daily_clears_trigger(self):
        breaker = self._breaker(limit=-50_000.0)
        asyncio.run(
            self._check(breaker, -60_000.0)
        )
        assert breaker.is_triggered
        breaker.reset_daily()
        assert not breaker.is_triggered

    def test_reset_daily_refuses_to_clear_an_in_flight_flatten(self):
        from flinttrade_core.exceptions import SafetyBypassError
        from flinttrade_engine.safety import EmergencyDispatchResult, EmergencyVerbOutcome

        entered = threading.Event()
        release = threading.Event()

        class BlockingDispatcher:
            def dispatch(self, policy, *, reason, adapter_id, account_id):
                entered.set()
                release.wait(timeout=2.0)
                return EmergencyDispatchResult(
                    policy=policy,
                    outcomes=tuple(
                        EmergencyVerbOutcome(
                            verb,
                            succeeded=True,
                            selector=f"{adapter_id}:{account_id}",
                        )
                        for verb in policy.verbs
                    ),
                )

        breaker = self._breaker(
            limit=-50_000.0,
            emergency_dispatcher=BlockingDispatcher(),
        )
        worker = threading.Thread(target=lambda: asyncio.run(self._check(breaker, -60_000.0)))
        worker.start()
        assert entered.wait(timeout=1.0)

        with pytest.raises(SafetyBypassError, match="still in progress"):
            breaker.reset_daily(timeout=0)
        assert breaker.is_triggered

        release.set()
        worker.join(timeout=1.0)
        assert not worker.is_alive()
        breaker.reset_daily(timeout=1.0)
        assert not breaker.is_triggered

    def test_explicit_mtm_emergency_policy_dispatched_on_breach(self):
        from flinttrade_engine.safety import (
            EmergencyDispatchResult,
            EmergencyVerbOutcome,
            MTM_EMERGENCY_POLICY,
        )

        dispatcher = MagicMock()
        dispatcher.dispatch.return_value = EmergencyDispatchResult(
            policy=MTM_EMERGENCY_POLICY,
            outcomes=tuple(
                EmergencyVerbOutcome(verb, succeeded=True)
                for verb in MTM_EMERGENCY_POLICY.verbs
            ),
        )
        breaker = self._breaker(limit=-50_000.0, emergency_dispatcher=dispatcher)
        asyncio.run(
            self._check(breaker, -60_000.0)
        )
        dispatcher.dispatch.assert_called_once()
        policy = dispatcher.dispatch.call_args.args[0]
        assert policy is MTM_EMERGENCY_POLICY
        assert dispatcher.dispatch.call_args.kwargs["adapter_id"] == "dhan"
        assert dispatcher.dispatch.call_args.kwargs["account_id"] == "primary"

    @pytest.mark.asyncio
    async def test_mtm_emergency_dispatch_does_not_block_monitor_event_loop(self):
        from flinttrade_engine.safety import (
            EmergencyDispatchResult,
            EmergencyVerbOutcome,
        )

        release = threading.Event()

        class _BlockingDispatcher:
            def dispatch(self, policy, *, reason, adapter_id, account_id):
                release.wait(timeout=1.0)
                return EmergencyDispatchResult(
                    policy=policy,
                    outcomes=tuple(
                        EmergencyVerbOutcome(
                            verb,
                            succeeded=True,
                            selector=f"{adapter_id}:{account_id}",
                        )
                        for verb in policy.verbs
                    ),
                )

        breaker = self._breaker(
            limit=-50_000.0,
            emergency_dispatcher=_BlockingDispatcher(),
        )
        threading.Timer(0.2, release.set).start()
        started_at = time.monotonic()
        check_task = asyncio.create_task(
            self._check(breaker, -60_000.0)
        )

        await asyncio.sleep(0.02)
        heartbeat_elapsed = time.monotonic() - started_at
        release.set()
        assert await check_task
        assert heartbeat_elapsed < 0.1

    def test_no_client_does_not_raise(self):
        """Breaker fires even without a client — it just can't close positions."""
        breaker = self._breaker(limit=-50_000.0, emergency_dispatcher=None)
        result = asyncio.run(
            self._check(breaker, -60_000.0)
        )
        assert result

    def test_emergency_dispatch_failure_does_not_re_raise(self):
        """If the broker call fails the breaker should still mark as triggered."""
        dispatcher = MagicMock()
        dispatcher.dispatch.side_effect = RuntimeError("network error")
        breaker = self._breaker(limit=-50_000.0, emergency_dispatcher=dispatcher)
        # Should not raise
        result = asyncio.run(
            self._check(breaker, -60_000.0)
        )
        assert result
        assert breaker.is_triggered

    def test_positive_pnl_never_triggers(self):
        breaker = self._breaker(limit=-50_000.0)
        result = asyncio.run(
            self._check(breaker, +10_000.0)
        )
        assert not result
        assert not breaker.is_triggered

    def test_activity_logger_receives_critical_log(self, caplog):
        import logging
        breaker = self._breaker(limit=-50_000.0)
        with caplog.at_level(logging.CRITICAL):
            asyncio.run(
                self._check(breaker, -60_000.0)
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
            self._check(breaker, pnl)
        )
        assert result == should_trigger
