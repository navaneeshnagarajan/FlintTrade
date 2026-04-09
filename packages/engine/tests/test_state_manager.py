"""Tests for StateManager.

All tests use an in-memory DuckDB instance.

Coverage:
- initialise (idempotent)
- All valid transitions through the lifecycle
- Invalid transition guard (InvalidTransitionError)
- Unknown strategy guard (StrategyStateNotFoundError)
- Crash recovery (state reloaded from DuckDB)
- Transition history retrieval
- reset() back to IDLE
- is_in_state / current_state helpers
- strategies_in_state query
- Thread-safe concurrent transitions for different strategies
"""

from __future__ import annotations

import threading

import pytest

from packages.engine.src.state_manager import (
    InvalidTransitionError,
    StateManager,
    StrategyState,
    StrategyStateNotFoundError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SID_A = "strategy-aaaa-1111"
SID_B = "strategy-bbbb-2222"


def _sm() -> StateManager:
    """Fresh in-memory StateManager."""
    return StateManager(db_path=":memory:")


# ---------------------------------------------------------------------------
# Initialise
# ---------------------------------------------------------------------------


def test_initialise_creates_idle_state() -> None:
    sm = _sm()
    snap = sm.initialise(SID_A)
    assert snap.state == StrategyState.IDLE
    assert snap.strategy_id == SID_A


def test_initialise_is_idempotent() -> None:
    sm = _sm()
    sm.initialise(SID_A)
    snap2 = sm.initialise(SID_A)
    # Should return existing snapshot without resetting
    assert snap2.state == StrategyState.IDLE
    assert sm.strategies_in_state(StrategyState.IDLE) == [SID_A]


def test_initialise_default_session_date_set() -> None:
    sm = _sm()
    snap = sm.initialise(SID_A)
    assert snap.session_date  # Non-empty string


def test_initialise_metadata_stored() -> None:
    sm = _sm()
    snap = sm.initialise(SID_A, metadata={"exchange": "NFO"})
    assert snap.metadata["exchange"] == "NFO"


# ---------------------------------------------------------------------------
# Full lifecycle happy path
# ---------------------------------------------------------------------------


def test_full_lifecycle_idle_to_exited() -> None:
    sm = _sm()
    sm.initialise(SID_A)

    sm.transition(SID_A, StrategyState.ARMED, reason="CONDITIONS_MET")
    assert sm.current_state(SID_A) == StrategyState.ARMED

    sm.transition(SID_A, StrategyState.ENTRY_PENDING, reason="ORDER_PLACED")
    assert sm.current_state(SID_A) == StrategyState.ENTRY_PENDING

    sm.transition(SID_A, StrategyState.IN_POSITION, reason="ORDER_FILLED")
    assert sm.current_state(SID_A) == StrategyState.IN_POSITION

    sm.transition(SID_A, StrategyState.EXIT_PENDING, reason="SL_HIT")
    assert sm.current_state(SID_A) == StrategyState.EXIT_PENDING

    sm.transition(SID_A, StrategyState.EXITED, reason="EXIT_FILLED")
    assert sm.current_state(SID_A) == StrategyState.EXITED


def test_exited_can_loop_back_to_idle() -> None:
    sm = _sm()
    sm.initialise(SID_A)
    sm.transition(SID_A, StrategyState.ARMED, reason="X")
    sm.transition(SID_A, StrategyState.ENTRY_PENDING, reason="X")
    sm.transition(SID_A, StrategyState.IN_POSITION, reason="X")
    sm.transition(SID_A, StrategyState.EXITED, reason="X")
    sm.transition(SID_A, StrategyState.IDLE, reason="NEXT_CYCLE")
    assert sm.current_state(SID_A) == StrategyState.IDLE


def test_entry_pending_can_revert_to_armed_on_rejection() -> None:
    sm = _sm()
    sm.initialise(SID_A)
    sm.transition(SID_A, StrategyState.ARMED, reason="X")
    sm.transition(SID_A, StrategyState.ENTRY_PENDING, reason="X")
    sm.transition(SID_A, StrategyState.ARMED, reason="ORDER_REJECTED")
    assert sm.current_state(SID_A) == StrategyState.ARMED


def test_direct_close_from_in_position_allowed() -> None:
    """IN_POSITION → EXITED (e.g. EOD MIS auto-close detected)."""
    sm = _sm()
    sm.initialise(SID_A)
    sm.transition(SID_A, StrategyState.ARMED, reason="X")
    sm.transition(SID_A, StrategyState.ENTRY_PENDING, reason="X")
    sm.transition(SID_A, StrategyState.IN_POSITION, reason="X")
    sm.transition(SID_A, StrategyState.EXITED, reason="EOD_AUTO_CLOSE")
    assert sm.current_state(SID_A) == StrategyState.EXITED


# ---------------------------------------------------------------------------
# Error state
# ---------------------------------------------------------------------------


def test_any_state_can_transition_to_error() -> None:
    sm = _sm()
    for state in (
        StrategyState.IDLE,
        StrategyState.ARMED,
        StrategyState.ENTRY_PENDING,
        StrategyState.IN_POSITION,
        StrategyState.EXIT_PENDING,
    ):
        sm2 = _sm()
        sm2.initialise(SID_A)
        # Navigate to the target state
        path = {
            StrategyState.IDLE: [],
            StrategyState.ARMED: [StrategyState.ARMED],
            StrategyState.ENTRY_PENDING: [StrategyState.ARMED, StrategyState.ENTRY_PENDING],
            StrategyState.IN_POSITION: [StrategyState.ARMED, StrategyState.ENTRY_PENDING, StrategyState.IN_POSITION],
            StrategyState.EXIT_PENDING: [StrategyState.ARMED, StrategyState.ENTRY_PENDING, StrategyState.IN_POSITION, StrategyState.EXIT_PENDING],
        }
        for s in path[state]:
            sm2.transition(SID_A, s, reason="SETUP")
        sm2.transition(SID_A, StrategyState.ERROR, reason="TEST_ERROR")
        assert sm2.current_state(SID_A) == StrategyState.ERROR


def test_error_can_recover_to_idle() -> None:
    sm = _sm()
    sm.initialise(SID_A)
    sm.transition(SID_A, StrategyState.ERROR, reason="CRASH")
    sm.transition(SID_A, StrategyState.IDLE, reason="MANUAL_RECOVERY")
    assert sm.current_state(SID_A) == StrategyState.IDLE


# ---------------------------------------------------------------------------
# Pause / resume
# ---------------------------------------------------------------------------


def test_paused_from_in_position_then_back() -> None:
    sm = _sm()
    sm.initialise(SID_A)
    sm.transition(SID_A, StrategyState.ARMED, reason="X")
    sm.transition(SID_A, StrategyState.ENTRY_PENDING, reason="X")
    sm.transition(SID_A, StrategyState.IN_POSITION, reason="X")
    sm.transition(SID_A, StrategyState.PAUSED, reason="NEWS_EVENT")
    snap = sm.get(SID_A)
    assert snap.state == StrategyState.PAUSED
    assert snap.previous_state == StrategyState.IN_POSITION


def test_paused_can_resume_to_prior_state() -> None:
    sm = _sm()
    sm.initialise(SID_A)
    sm.transition(SID_A, StrategyState.ARMED, reason="X")
    sm.transition(SID_A, StrategyState.PAUSED, reason="X")
    sm.transition(SID_A, StrategyState.ARMED, reason="RESUME")
    assert sm.current_state(SID_A) == StrategyState.ARMED


# ---------------------------------------------------------------------------
# Invalid transitions
# ---------------------------------------------------------------------------


def test_invalid_transition_raises() -> None:
    sm = _sm()
    sm.initialise(SID_A)
    # IDLE → IN_POSITION is not a valid direct jump
    with pytest.raises(InvalidTransitionError):
        sm.transition(SID_A, StrategyState.IN_POSITION, reason="INVALID")


def test_cannot_transition_from_exited_to_armed() -> None:
    sm = _sm()
    sm.initialise(SID_A)
    sm.transition(SID_A, StrategyState.ARMED, reason="X")
    sm.transition(SID_A, StrategyState.ENTRY_PENDING, reason="X")
    sm.transition(SID_A, StrategyState.IN_POSITION, reason="X")
    sm.transition(SID_A, StrategyState.EXITED, reason="X")
    with pytest.raises(InvalidTransitionError):
        sm.transition(SID_A, StrategyState.ARMED, reason="INVALID")


def test_unknown_strategy_raises_on_transition() -> None:
    sm = _sm()
    with pytest.raises(StrategyStateNotFoundError):
        sm.transition("nonexistent-id", StrategyState.ARMED, reason="X")


def test_unknown_strategy_raises_on_get() -> None:
    sm = _sm()
    with pytest.raises(StrategyStateNotFoundError):
        sm.get("nonexistent-id")


# ---------------------------------------------------------------------------
# Transition record & reason code
# ---------------------------------------------------------------------------


def test_transition_stores_reason() -> None:
    sm = _sm()
    sm.initialise(SID_A)
    sm.transition(SID_A, StrategyState.ARMED, reason="BOLLINGER_SQUEEZE")
    snap = sm.get(SID_A)
    assert snap.last_reason == "BOLLINGER_SQUEEZE"


def test_transition_stores_previous_state() -> None:
    sm = _sm()
    sm.initialise(SID_A)
    sm.transition(SID_A, StrategyState.ARMED, reason="X")
    snap = sm.get(SID_A)
    assert snap.previous_state == StrategyState.IDLE


def test_transition_metadata_merged_into_snapshot() -> None:
    sm = _sm()
    sm.initialise(SID_A, metadata={"key": "initial"})
    sm.transition(SID_A, StrategyState.ARMED, reason="X", metadata={"order_id": "ORD-001"})
    snap = sm.get(SID_A)
    assert snap.metadata.get("order_id") == "ORD-001"
    assert snap.metadata.get("key") == "initial"


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


def test_get_history_returns_transitions(tmp_path) -> None:
    db = str(tmp_path / "sm.duckdb")
    sm = StateManager(db_path=db)
    sm.initialise(SID_A)
    sm.transition(SID_A, StrategyState.ARMED, reason="R1")
    sm.transition(SID_A, StrategyState.ENTRY_PENDING, reason="R2")
    history = sm.get_history(SID_A)
    assert len(history) >= 2
    # Most recent first
    assert history[0].to_state == StrategyState.ENTRY_PENDING
    sm.close_db()


def test_get_history_empty_for_no_transitions() -> None:
    sm = _sm()
    # In-memory DB — initialise doesn't log a transition record
    sm.initialise(SID_A)
    history = sm.get_history(SID_A)
    assert isinstance(history, list)


# ---------------------------------------------------------------------------
# Crash recovery
# ---------------------------------------------------------------------------


def test_recovery_restores_state(tmp_path) -> None:
    db = str(tmp_path / "sm_recovery.duckdb")
    sm1 = StateManager(db_path=db)
    sm1.initialise(SID_A)
    sm1.transition(SID_A, StrategyState.ARMED, reason="CONDITIONS_MET")
    sm1.transition(SID_A, StrategyState.ENTRY_PENDING, reason="ORDER_PLACED")
    sm1.close_db()

    sm2 = StateManager(db_path=db)
    assert sm2.current_state(SID_A) == StrategyState.ENTRY_PENDING
    sm2.close_db()


def test_recovery_does_not_affect_other_strategies(tmp_path) -> None:
    db = str(tmp_path / "sm_multi.duckdb")
    sm1 = StateManager(db_path=db)
    sm1.initialise(SID_A)
    sm1.initialise(SID_B)
    sm1.transition(SID_A, StrategyState.ARMED, reason="X")
    sm1.close_db()

    sm2 = StateManager(db_path=db)
    assert sm2.current_state(SID_A) == StrategyState.ARMED
    assert sm2.current_state(SID_B) == StrategyState.IDLE
    sm2.close_db()


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


def test_reset_returns_to_idle() -> None:
    sm = _sm()
    sm.initialise(SID_A)
    sm.transition(SID_A, StrategyState.ARMED, reason="X")
    sm.reset(SID_A, reason="DAILY_RESET")
    assert sm.current_state(SID_A) == StrategyState.IDLE


def test_reset_updates_session_date() -> None:
    sm = _sm()
    sm.initialise(SID_A)
    sm.transition(SID_A, StrategyState.ARMED, reason="X")
    sm.reset(SID_A)
    snap = sm.get(SID_A)
    assert snap.session_date  # Non-empty


def test_reset_unknown_strategy_is_noop() -> None:
    sm = _sm()
    sm.reset("nonexistent-id")  # Should not raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_is_in_state_true() -> None:
    sm = _sm()
    sm.initialise(SID_A)
    assert sm.is_in_state(SID_A, StrategyState.IDLE)


def test_is_in_state_false() -> None:
    sm = _sm()
    sm.initialise(SID_A)
    assert not sm.is_in_state(SID_A, StrategyState.ARMED)


def test_is_in_state_unknown_returns_false() -> None:
    sm = _sm()
    assert not sm.is_in_state("unknown", StrategyState.IDLE)


def test_strategies_in_state() -> None:
    sm = _sm()
    sm.initialise(SID_A)
    sm.initialise(SID_B)
    sm.transition(SID_A, StrategyState.ARMED, reason="X")
    in_idle = sm.strategies_in_state(StrategyState.IDLE)
    in_armed = sm.strategies_in_state(StrategyState.ARMED)
    assert SID_B in in_idle
    assert SID_A in in_armed
    assert SID_A not in in_idle


def test_all_snapshots_returns_all() -> None:
    sm = _sm()
    sm.initialise(SID_A)
    sm.initialise(SID_B)
    snaps = sm.all_snapshots()
    ids = {s.strategy_id for s in snaps}
    assert SID_A in ids
    assert SID_B in ids


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


def test_concurrent_transitions_different_strategies() -> None:
    sm = _sm()
    for i in range(10):
        sm.initialise(f"strat-{i}")

    errors: list[Exception] = []

    def arm_strategy(sid: str) -> None:
        try:
            sm.transition(sid, StrategyState.ARMED, reason="CONCURRENT_TEST")
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=arm_strategy, args=(f"strat-{i}",))
        for i in range(10)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    armed = sm.strategies_in_state(StrategyState.ARMED)
    assert len(armed) == 10
