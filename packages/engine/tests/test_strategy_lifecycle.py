"""Tests for StrategyLifecycleManager.

All tests are offline — no broker, no registry (unless specifically testing
registry integration via a mock).

Covers: create, deploy, pause, resume, stop, error, remove, record_signal,
record_trade, increment_cycle, list_instances, stop_all, thread safety,
and all invalid transition guards.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from packages.engine.src.strategy_lifecycle import (
    InstanceNotFoundError,
    InstanceStatus,
    InvalidTransitionError,
    StrategyInstance,
    StrategyLifecycleError,
    StrategyLifecycleManager,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def manager() -> StrategyLifecycleManager:
    return StrategyLifecycleManager()


def make_instance(
    mgr: StrategyLifecycleManager,
    name: str = "Test EMA",
    cls: str = "EMACrossover",
    symbols: list[str] | None = None,
) -> StrategyInstance:
    return mgr.create_instance(
        strategy_class_name=cls,
        name=name,
        symbols=symbols or ["NIFTY25JULFUT"],
        exchange="NFO",
        product="MIS",
        parameters={"fast": 10, "slow": 20},
    )


# ---------------------------------------------------------------------------
# StrategyInstance dataclass
# ---------------------------------------------------------------------------


def test_instance_initial_status_created(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    assert inst.status == InstanceStatus.CREATED


def test_instance_has_uuid(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    assert len(inst.strategy_id) == 36  # standard UUID length


def test_instance_is_running_false_when_created(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    assert not inst.is_running


def test_instance_is_stopped_false_when_created(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    assert not inst.is_stopped


def test_instance_as_dict_has_all_keys(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    d = inst.as_dict()
    for key in [
        "strategy_id", "name", "strategy_class_name", "symbols", "exchange",
        "product", "parameters", "status", "created_at", "started_at",
        "stopped_at", "last_signal", "error_message", "cycle_count",
        "trade_count", "daily_pnl",
    ]:
        assert key in d


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_stores_instance(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    assert manager.instance_count == 1
    retrieved = manager.get_status(inst.strategy_id)
    assert retrieved.name == "Test EMA"


def test_create_empty_name_raises(manager: StrategyLifecycleManager) -> None:
    with pytest.raises(ValueError, match="name"):
        manager.create_instance("EMACrossover", "", ["NIFTY"])


def test_create_empty_class_name_raises(manager: StrategyLifecycleManager) -> None:
    with pytest.raises(ValueError, match="strategy_class_name"):
        manager.create_instance("", "MyStrat", ["NIFTY"])


def test_create_empty_symbols_raises(manager: StrategyLifecycleManager) -> None:
    with pytest.raises(ValueError, match="symbols"):
        manager.create_instance("EMACrossover", "MyStrat", [])


def test_create_custom_id(manager: StrategyLifecycleManager) -> None:
    inst = manager.create_instance("EMA", "Test", ["NIFTY"], strategy_id="fixed-id-123")
    assert inst.strategy_id == "fixed-id-123"


# ---------------------------------------------------------------------------
# Deploy
# ---------------------------------------------------------------------------


def test_deploy_created_to_running(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    manager.deploy(inst.strategy_id)
    assert manager.get_status(inst.strategy_id).status == InstanceStatus.RUNNING


def test_deploy_sets_started_at(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    manager.deploy(inst.strategy_id)
    assert manager.get_status(inst.strategy_id).started_at is not None


def test_deploy_running_instance_raises(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    manager.deploy(inst.strategy_id)
    with pytest.raises(InvalidTransitionError):
        manager.deploy(inst.strategy_id)


def test_deploy_stopped_instance_raises(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    manager.deploy(inst.strategy_id)
    manager.stop(inst.strategy_id)
    with pytest.raises(InvalidTransitionError):
        manager.deploy(inst.strategy_id)


def test_deploy_not_found_raises(manager: StrategyLifecycleManager) -> None:
    with pytest.raises(InstanceNotFoundError):
        manager.deploy("nonexistent-id")


# ---------------------------------------------------------------------------
# Pause
# ---------------------------------------------------------------------------


def test_pause_running_to_paused(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    manager.deploy(inst.strategy_id)
    manager.pause(inst.strategy_id)
    assert manager.get_status(inst.strategy_id).status == InstanceStatus.PAUSED


def test_pause_created_raises(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    with pytest.raises(InvalidTransitionError):
        manager.pause(inst.strategy_id)


def test_pause_stopped_raises(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    manager.deploy(inst.strategy_id)
    manager.stop(inst.strategy_id)
    with pytest.raises(InvalidTransitionError):
        manager.pause(inst.strategy_id)


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------


def test_resume_paused_to_running(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    manager.deploy(inst.strategy_id)
    manager.pause(inst.strategy_id)
    manager.resume(inst.strategy_id)
    assert manager.get_status(inst.strategy_id).status == InstanceStatus.RUNNING


def test_resume_running_raises(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    manager.deploy(inst.strategy_id)
    with pytest.raises(InvalidTransitionError):
        manager.resume(inst.strategy_id)


def test_resume_created_raises(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    with pytest.raises(InvalidTransitionError):
        manager.resume(inst.strategy_id)


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------


def test_stop_running_to_stopped(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    manager.deploy(inst.strategy_id)
    manager.stop(inst.strategy_id)
    assert manager.get_status(inst.strategy_id).status == InstanceStatus.STOPPED


def test_stop_paused_to_stopped(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    manager.deploy(inst.strategy_id)
    manager.pause(inst.strategy_id)
    manager.stop(inst.strategy_id)
    assert manager.get_status(inst.strategy_id).status == InstanceStatus.STOPPED


def test_stop_sets_stopped_at(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    manager.deploy(inst.strategy_id)
    manager.stop(inst.strategy_id)
    assert manager.get_status(inst.strategy_id).stopped_at is not None


def test_stop_created_raises(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    with pytest.raises(InvalidTransitionError):
        manager.stop(inst.strategy_id)


def test_stop_already_stopped_raises(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    manager.deploy(inst.strategy_id)
    manager.stop(inst.strategy_id)
    with pytest.raises(InvalidTransitionError):
        manager.stop(inst.strategy_id)


def test_stop_is_stopped_true_after_stop(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    manager.deploy(inst.strategy_id)
    manager.stop(inst.strategy_id)
    assert manager.get_status(inst.strategy_id).is_stopped


# ---------------------------------------------------------------------------
# Mark error
# ---------------------------------------------------------------------------


def test_mark_error_from_running(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    manager.deploy(inst.strategy_id)
    manager.mark_error(inst.strategy_id, "connection lost")
    updated = manager.get_status(inst.strategy_id)
    assert updated.status == InstanceStatus.ERROR
    assert updated.error_message == "connection lost"


def test_mark_error_from_paused(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    manager.deploy(inst.strategy_id)
    manager.pause(inst.strategy_id)
    manager.mark_error(inst.strategy_id, "broker down")
    assert manager.get_status(inst.strategy_id).status == InstanceStatus.ERROR


def test_error_instance_is_stopped(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    manager.deploy(inst.strategy_id)
    manager.mark_error(inst.strategy_id, "fatal")
    assert manager.get_status(inst.strategy_id).is_stopped


# ---------------------------------------------------------------------------
# Record signal / trade / cycle
# ---------------------------------------------------------------------------


def test_record_signal(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    manager.record_signal(inst.strategy_id, "BUY")
    assert manager.get_status(inst.strategy_id).last_signal == "BUY"


def test_record_signal_nonexistent_no_error(manager: StrategyLifecycleManager) -> None:
    manager.record_signal("bad-id", "SELL")  # Should not raise


def test_record_trade_increments_count(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    manager.record_trade(inst.strategy_id, pnl=500.0)
    manager.record_trade(inst.strategy_id, pnl=-200.0)
    updated = manager.get_status(inst.strategy_id)
    assert updated.trade_count == 2
    assert updated.daily_pnl == pytest.approx(300.0)


def test_increment_cycle(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    manager.increment_cycle(inst.strategy_id)
    manager.increment_cycle(inst.strategy_id)
    assert manager.get_status(inst.strategy_id).cycle_count == 2


# ---------------------------------------------------------------------------
# List instances
# ---------------------------------------------------------------------------


def test_list_all_instances(manager: StrategyLifecycleManager) -> None:
    make_instance(manager, name="A")
    make_instance(manager, name="B")
    make_instance(manager, name="C")
    all_inst = manager.list_instances()
    assert len(all_inst) == 3


def test_list_filter_running(manager: StrategyLifecycleManager) -> None:
    i1 = make_instance(manager, name="R1")
    i2 = make_instance(manager, name="R2")
    make_instance(manager, name="C1")
    manager.deploy(i1.strategy_id)
    manager.deploy(i2.strategy_id)
    running = manager.list_instances(status_filter=InstanceStatus.RUNNING)
    created = manager.list_instances(status_filter=InstanceStatus.CREATED)
    assert len(running) == 2
    assert len(created) == 1


def test_list_empty(manager: StrategyLifecycleManager) -> None:
    assert manager.list_instances() == []


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------


def test_remove_stopped_instance(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    manager.deploy(inst.strategy_id)
    manager.stop(inst.strategy_id)
    manager.remove(inst.strategy_id)
    assert manager.instance_count == 0


def test_remove_created_instance(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    manager.remove(inst.strategy_id)
    assert manager.instance_count == 0


def test_remove_running_raises(manager: StrategyLifecycleManager) -> None:
    inst = make_instance(manager)
    manager.deploy(inst.strategy_id)
    with pytest.raises(InvalidTransitionError):
        manager.remove(inst.strategy_id)


def test_remove_nonexistent_raises(manager: StrategyLifecycleManager) -> None:
    with pytest.raises(InstanceNotFoundError):
        manager.remove("does-not-exist")


# ---------------------------------------------------------------------------
# Stop all
# ---------------------------------------------------------------------------


def test_stop_all_stops_running_and_paused(manager: StrategyLifecycleManager) -> None:
    i1 = make_instance(manager, name="A")
    i2 = make_instance(manager, name="B")
    make_instance(manager, name="C")  # created, not running
    manager.deploy(i1.strategy_id)
    manager.deploy(i2.strategy_id)
    manager.pause(i2.strategy_id)
    stopped_ids = manager.stop_all()
    assert len(stopped_ids) == 2
    assert manager.running_count == 0


def test_stop_all_empty_manager(manager: StrategyLifecycleManager) -> None:
    assert manager.stop_all() == []


# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------


def test_instance_count(manager: StrategyLifecycleManager) -> None:
    assert manager.instance_count == 0
    make_instance(manager)
    assert manager.instance_count == 1
    make_instance(manager)
    assert manager.instance_count == 2


def test_running_count(manager: StrategyLifecycleManager) -> None:
    i1 = make_instance(manager)
    i2 = make_instance(manager)
    assert manager.running_count == 0
    manager.deploy(i1.strategy_id)
    assert manager.running_count == 1
    manager.deploy(i2.strategy_id)
    assert manager.running_count == 2
    manager.pause(i1.strategy_id)
    assert manager.running_count == 1


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


def test_deploy_calls_registry_enable() -> None:
    mock_registry = MagicMock()
    manager = StrategyLifecycleManager(registry=mock_registry)
    inst = manager.create_instance("EMA", "Test", ["NIFTY"])
    manager.deploy(inst.strategy_id)
    mock_registry.enable.assert_called_once_with("EMA")


def test_pause_calls_registry_disable() -> None:
    mock_registry = MagicMock()
    manager = StrategyLifecycleManager(registry=mock_registry)
    inst = manager.create_instance("EMA", "Test", ["NIFTY"])
    manager.deploy(inst.strategy_id)
    manager.pause(inst.strategy_id)
    mock_registry.disable.assert_called_once_with("EMA")


def test_registry_failure_does_not_block_lifecycle() -> None:
    """Registry errors should log a warning but not prevent state transitions."""
    mock_registry = MagicMock()
    mock_registry.enable.side_effect = KeyError("not registered")
    manager = StrategyLifecycleManager(registry=mock_registry)
    inst = manager.create_instance("Unknown", "Test", ["NIFTY"])
    manager.deploy(inst.strategy_id)  # Should not raise
    assert manager.get_status(inst.strategy_id).status == InstanceStatus.RUNNING


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


def test_concurrent_creates_are_safe() -> None:
    """100 concurrent creates should all succeed without data races."""
    manager = StrategyLifecycleManager()
    errors: list[Exception] = []

    def create(i: int) -> None:
        try:
            manager.create_instance("EMA", f"Strat-{i}", [f"SYM{i}"])
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=create, args=(i,)) for i in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert manager.instance_count == 100


def test_concurrent_record_trade_is_safe() -> None:
    """Concurrent record_trade calls should not corrupt daily_pnl."""
    manager = StrategyLifecycleManager()
    inst = manager.create_instance("EMA", "Test", ["NIFTY"])

    def record() -> None:
        for _ in range(100):
            manager.record_trade(inst.strategy_id, pnl=1.0)

    threads = [threading.Thread(target=record) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final = manager.get_status(inst.strategy_id)
    assert final.trade_count == 1000
    assert final.daily_pnl == pytest.approx(1000.0)


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


def test_lifecycle_error_is_base() -> None:
    assert issubclass(InstanceNotFoundError, StrategyLifecycleError)
    assert issubclass(InvalidTransitionError, StrategyLifecycleError)


def test_get_status_not_found_raises(manager: StrategyLifecycleManager) -> None:
    with pytest.raises(InstanceNotFoundError, match="No instance"):
        manager.get_status("ghost-id")
