"""Regression tests for strategy scheduler lifecycle ownership."""

from __future__ import annotations

import asyncio
import functools
import threading
import weakref
from collections import deque
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from types import MappingProxyType, ModuleType
from typing import Annotated, Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.scheduler import StrategyRunner, StrategyScheduler, TimeScheduler
from flinttrade_engine.strategy import BaseStrategy
from flinttrade_engine.strategy_execution import (
    GatedStrategyDispatcher,
    StrategyExecutionContract,
    StrategyExecutionMode,
)

_MODULE_GLOBAL_RAW_WRITER: Any = None
_DYNAMIC_GLOBAL_RAW_WRITER: Any = None
_MODULE_ATTRIBUTE_CONTAINER = ModuleType("strategy_execution_review_probe")


async def _write_through_module_global(order: Order) -> None:
    await _MODULE_GLOBAL_RAW_WRITER.place_order(order)


async def _write_through_dynamic_globals(order: Order) -> None:
    writer = globals()["_DYNAMIC_GLOBAL_RAW_WRITER"]
    await writer.place_order(order)


async def _write_through_nested_module_global(order: Order) -> None:
    async def nested_write() -> None:
        await _MODULE_GLOBAL_RAW_WRITER.place_order(order)

    await nested_write()


async def _write_through_referenced_module_attribute(order: Order) -> None:
    await _MODULE_ATTRIBUTE_CONTAINER.writer.place_order(order)


class _RawWriter:
    async def place_order(self, _order: Order) -> None:
        return None

HookResult = Coroutine[Any, Any, None]
type ModernHookResult = Coroutine[Any, Any, None]
type GenericHookResult[T] = Coroutine[Any, Any, T]
type IdentityHookResult[T] = T
type MaybeHookResult[T] = T | None
type MetadataHookResult[T] = Annotated[T, "metadata"]
type NestedIdentityHookResult[T] = IdentityHookResult[T]
type SiblingAliasChoice = IdentityHookResult[int] | IdentityHookResult[Coroutine[Any, Any, None]]
type GenericSiblingAliasChoice[T, U] = IdentityHookResult[T] | IdentityHookResult[U]
type NestedSiblingAliasChoice = NestedIdentityHookResult[int] | NestedIdentityHookResult[Coroutine[Any, Any, None]]
type AnnotatedSiblingAliasChoice = Annotated[
    IdentityHookResult[int] | IdentityHookResult[Awaitable[None]],
    "metadata",
]


class _TestStrategy(BaseStrategy):
    supported_execution_modes = frozenset({StrategyExecutionMode.READ_ONLY})

    def __init__(
        self,
        name: str = "test",
        *,
        symbol: str = "RELIANCE",
        execution_contract: StrategyExecutionContract | None = None,
    ) -> None:
        super().__init__(
            name=name,
            exchange="NSE",
            execution_contract=execution_contract or StrategyExecutionContract.read_only(),
        )
        self.symbol = symbol
        self.ticks: list[Quote] = []

    def on_tick(self, quote: Quote) -> None:
        self.ticks.append(quote)

    def on_bar(self, bar: OHLCV) -> None:
        del bar

    def on_signal(self, signal: dict) -> None:
        del signal

    def generate_orders(self) -> list[Order]:
        return []


def _open_time_scheduler() -> TimeScheduler:
    scheduler = TimeScheduler()
    scheduler.is_market_open = MagicMock(return_value=True)
    scheduler.should_square_off = MagicMock(return_value=False)
    return scheduler


def _runner(
    strategy: _TestStrategy,
    *,
    tick_interval: float = 0.005,
    lifecycle_timeout: float | None = None,
) -> StrategyRunner:
    client = MagicMock()
    client.quotes = AsyncMock(return_value=Quote(symbol=strategy.symbol, exchange="NSE", ltp=100))
    kwargs = {}
    if lifecycle_timeout is not None:
        kwargs["lifecycle_timeout_seconds"] = lifecycle_timeout
    return StrategyRunner(
        strategy=strategy,
        client=client,
        scheduler=_open_time_scheduler(),
        tick_interval_seconds=tick_interval,
        **kwargs,
    )


def _live_dispatcher(*, account_id: str = "default") -> GatedStrategyDispatcher:
    from flinttrade_engine.safety import SafetyConfig, SafetySystem

    return GatedStrategyDispatcher(
        safety=SafetySystem(SafetyConfig()),
        request_context_provider=lambda: None,
        router_provider=lambda: None,
        adapter_id="openalgo",
        account_id=account_id,
    )


async def _wait_for_strategy_state(strategy: _TestStrategy, state: str) -> None:
    while strategy.state.value != state:
        await asyncio.sleep(0.001)


@pytest.mark.asyncio
async def test_stop_interrupts_inflight_start_without_post_stop_resurrection() -> None:
    strategy = _TestStrategy()
    entered_start = asyncio.Event()
    release_start = asyncio.Event()
    original_start = strategy.start
    original_stop = strategy.stop

    async def delayed_start() -> None:
        entered_start.set()
        await release_start.wait()
        original_start()

    strategy.start = AsyncMock(side_effect=delayed_start)
    strategy.stop = MagicMock(side_effect=original_stop)
    runner = _runner(strategy)

    start_task = asyncio.create_task(runner.start())
    await asyncio.wait_for(entered_start.wait(), timeout=1.0)
    assert runner.cleanup_required is True
    await asyncio.wait_for(runner.stop(), timeout=1.0)
    release_start.set()
    await asyncio.gather(start_task, return_exceptions=True)

    strategy.stop.assert_called_once_with()
    assert runner.cleanup_required is False
    assert runner.is_running is False
    assert runner._task is None
    assert strategy.state.value == "STOPPED"


@pytest.mark.asyncio
async def test_stop_hook_timeout_is_bounded_and_blocks_restart_until_retry() -> None:
    strategy = _TestStrategy()
    runner = _runner(strategy, lifecycle_timeout=0.02)
    release_stop = asyncio.Event()
    original_stop = strategy.stop

    async def delayed_stop() -> None:
        await release_stop.wait()
        original_stop()

    strategy.stop = AsyncMock(side_effect=delayed_stop)
    await runner.start()

    with pytest.raises(TimeoutError, match="stop hook"):
        await asyncio.wait_for(runner.stop(), timeout=0.5)
    with pytest.raises(RuntimeError, match="previous stop did not complete"):
        await runner.start()

    release_stop.set()
    await runner.stop()
    await runner.start()
    await runner.stop()


@pytest.mark.asyncio
async def test_completed_cancellation_resistant_stop_hook_is_not_run_twice() -> None:
    strategy = _TestStrategy()
    runner = _runner(strategy, lifecycle_timeout=0.02)
    release_stop = asyncio.Event()
    cancellation_seen = asyncio.Event()
    original_stop = strategy.stop
    attempts = 0

    async def resistant_stop() -> None:
        nonlocal attempts
        attempts += 1
        while not release_stop.is_set():
            try:
                await release_stop.wait()
            except asyncio.CancelledError:
                cancellation_seen.set()
        original_stop()

    strategy.stop = AsyncMock(side_effect=resistant_stop)
    await runner.start()

    with pytest.raises(TimeoutError, match="stop hook"):
        await runner.stop()
    assert cancellation_seen.is_set()

    release_stop.set()
    await asyncio.sleep(0)
    await runner.stop()

    assert attempts == 1


@pytest.mark.asyncio
async def test_concurrent_and_repeated_stop_calls_run_hook_once() -> None:
    strategy = _TestStrategy()
    runner = _runner(strategy)
    original_stop = strategy.stop

    async def async_stop() -> None:
        await asyncio.sleep(0)
        original_stop()

    strategy.stop = AsyncMock(side_effect=async_stop)
    await runner.start()

    await asyncio.gather(runner.stop(), runner.stop())
    await runner.stop()

    strategy.stop.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_register_rejects_replacing_an_active_runner() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    original = scheduler.register(_TestStrategy(name="duplicate"))
    original.scheduler = _open_time_scheduler()
    original.client.quotes = AsyncMock(return_value=None)
    await original.start()

    try:
        with pytest.raises(RuntimeError, match="already active"):
            scheduler.register(_TestStrategy(name="duplicate"))
        assert scheduler.get_runner("duplicate") is original
    finally:
        await original.stop()


@pytest.mark.asyncio
async def test_register_rejects_replacing_a_runner_during_start_transition() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    strategy = _TestStrategy(name="starting")
    entered_start = asyncio.Event()
    release_start = asyncio.Event()
    original_start = strategy.start

    async def delayed_start() -> None:
        entered_start.set()
        await release_start.wait()
        original_start()

    strategy.start = AsyncMock(side_effect=delayed_start)
    original = scheduler.register(strategy)
    start_task = asyncio.create_task(original.start())
    await asyncio.wait_for(entered_start.wait(), timeout=1.0)

    try:
        with pytest.raises(RuntimeError, match="already active"):
            scheduler.register(_TestStrategy(name="starting"))
        assert scheduler.get_runner("starting") is original
    finally:
        release_start.set()
        await start_task
        await original.stop()


@pytest.mark.asyncio
async def test_register_rejects_replacing_an_error_generation_until_stopped() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    original = scheduler.register(_TestStrategy(name="errored"))
    original.strategy.set_error("tick failed")

    with pytest.raises(RuntimeError, match="already active"):
        scheduler.register(_TestStrategy(name="errored"))

    assert scheduler.get_runner("errored") is original
    await original.stop()


@pytest.mark.asyncio
async def test_replaced_runner_is_permanently_retired() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    original = scheduler.register(_TestStrategy(name="generation"))

    replacement = scheduler.register(_TestStrategy(name="generation"))

    assert scheduler.get_runner("generation") is replacement
    with pytest.raises(RuntimeError, match="retired"):
        await original.start()


@pytest.mark.asyncio
async def test_stop_all_visits_every_retained_runner_owner() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    current = scheduler.register(_TestStrategy(name="current"))
    retained = _runner(_TestStrategy(name="retained"))
    retained.stop = AsyncMock()
    current.stop = AsyncMock()
    scheduler._owned_runners.append(retained)

    await scheduler.stop_all()

    retained.stop.assert_awaited_once_with()
    current.stop.assert_awaited_once_with()


def test_replacement_prunes_quiescent_retired_generation_from_owner_ledger() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    original = scheduler.register(_TestStrategy(name="pruned"))

    replacement = scheduler.register(_TestStrategy(name="pruned"))

    assert original not in scheduler._owned_runners
    assert replacement in scheduler._owned_runners


@pytest.mark.asyncio
async def test_timed_out_sync_start_hook_remains_owned_without_blocking_loop() -> None:
    strategy = _TestStrategy(name="slow-start")
    runner = _runner(strategy, lifecycle_timeout=0.02)
    owner_thread = threading.get_ident()
    hook_threads: list[int] = []
    release_start = threading.Event()
    heartbeat = asyncio.Event()
    original_start = strategy.start

    def blocking_start() -> None:
        hook_threads.append(threading.get_ident())
        release_start.wait(timeout=0.25)
        original_start()

    async def pulse() -> None:
        await asyncio.sleep(0.005)
        heartbeat.set()

    strategy.start = MagicMock(side_effect=blocking_start)
    pulse_task = asyncio.create_task(pulse())

    with pytest.raises(TimeoutError, match="start hook"):
        await runner.start()

    assert heartbeat.is_set()
    assert hook_threads and hook_threads[0] != owner_thread
    assert runner.cleanup_required is True
    assert runner.has_live_owner is True
    assert runner._start_hook_task is not None
    assert not runner._start_hook_task.done()

    release_start.set()
    await asyncio.wait_for(runner._start_hook_task, timeout=1.0)
    await runner.stop()
    await pulse_task


@pytest.mark.asyncio
async def test_timed_out_sync_stop_hook_remains_owned_without_blocking_loop() -> None:
    strategy = _TestStrategy(name="slow-stop")
    runner = _runner(strategy, lifecycle_timeout=0.02)
    owner_thread = threading.get_ident()
    hook_threads: list[int] = []
    release_stop = threading.Event()
    heartbeat = asyncio.Event()
    original_stop = strategy.stop

    def blocking_stop() -> None:
        hook_threads.append(threading.get_ident())
        release_stop.wait(timeout=0.25)
        original_stop()

    async def pulse() -> None:
        await asyncio.sleep(0.005)
        heartbeat.set()

    strategy.stop = MagicMock(side_effect=blocking_stop)
    await runner.start()
    pulse_task = asyncio.create_task(pulse())

    with pytest.raises(TimeoutError, match="stop hook"):
        await runner.stop()

    assert heartbeat.is_set()
    assert hook_threads and hook_threads[0] != owner_thread
    assert runner.cleanup_required is True
    assert runner.has_live_owner is True
    assert runner._stop_hook_task is not None
    assert not runner._stop_hook_task.done()

    release_stop.set()
    await asyncio.wait_for(runner._stop_hook_task, timeout=1.0)
    await runner.stop()
    await pulse_task


@pytest.mark.asyncio
async def test_square_off_sync_stop_timeout_retains_owned_worker() -> None:
    strategy = _TestStrategy(name="square-off-stop")
    runner = _runner(strategy, lifecycle_timeout=0.02)
    release_stop = threading.Event()
    heartbeat = asyncio.Event()
    original_stop = strategy.stop

    def blocking_stop() -> None:
        release_stop.wait(timeout=0.25)
        original_stop()

    async def pulse() -> None:
        await asyncio.sleep(0.005)
        heartbeat.set()

    strategy.start()
    strategy.stop = MagicMock(side_effect=blocking_stop)
    pulse_task = asyncio.create_task(pulse())

    with pytest.raises(TimeoutError, match="stop hook"):
        await runner._handle_square_off()

    assert heartbeat.is_set()
    assert runner.has_live_owner is True
    assert runner._stop_hook_task is not None
    assert not runner._stop_hook_task.done()

    release_stop.set()
    await asyncio.wait_for(runner._stop_hook_task, timeout=1.0)
    await runner.stop()
    await pulse_task


@pytest.mark.asyncio
async def test_live_square_off_and_stop_share_one_stop_hook() -> None:
    strategy = _TestStrategy(name="square-off-race")
    runner = _runner(strategy, tick_interval=0.25)
    runner.scheduler.should_square_off = MagicMock(return_value=True)
    original_stop = strategy.stop
    strategy.stop = MagicMock(side_effect=original_stop)

    await runner.start()
    await asyncio.wait_for(
        _wait_for_strategy_state(strategy, "STOPPED"),
        timeout=1.0,
    )
    assert runner._task is not None

    await runner.stop()

    strategy.stop.assert_called_once_with()


@pytest.mark.asyncio
async def test_pause_keeps_loop_owned_and_resume_restores_tick_delivery() -> None:
    strategy = _TestStrategy()
    runner = _runner(strategy)
    await runner.start()
    await asyncio.sleep(0.03)
    runner.pause()
    ticks_at_pause = runner.tick_count
    task = runner._task

    await asyncio.sleep(0.03)
    assert runner.is_running is True
    assert task is not None and not task.done()
    assert runner.tick_count == ticks_at_pause

    runner.resume()
    await asyncio.sleep(0.03)
    assert runner.tick_count > ticks_at_pause
    await runner.stop()


@pytest.mark.asyncio
async def test_strategy_can_stop_its_runner_from_on_tick() -> None:
    strategy = _TestStrategy(name="self-stopping")
    runner = _runner(strategy)
    stopped_from_tick = asyncio.Event()

    async def stop_from_tick(_quote: Quote) -> None:
        await runner.stop()
        stopped_from_tick.set()

    strategy.on_tick = stop_from_tick

    await runner.start()
    try:
        await asyncio.wait_for(stopped_from_tick.wait(), timeout=1.0)
        assert runner.is_running is False
        task = runner._task
        assert task is not None
        await asyncio.wait_for(task, timeout=1.0)
        assert runner.cleanup_required is False
        assert strategy.state.value == "STOPPED"
    finally:
        await runner.stop()


@pytest.mark.asyncio
async def test_sync_stop_hook_returning_awaitable_is_cancelled_after_worker_returns() -> None:
    strategy = _TestStrategy(name="hybrid-stop")
    runner = _runner(strategy, lifecycle_timeout=0.02)
    release_stop = asyncio.Event()
    cancellation_seen = asyncio.Event()
    original_stop = strategy.stop

    def hybrid_stop():
        async def finish_stop() -> None:
            try:
                await release_stop.wait()
            except asyncio.CancelledError:
                cancellation_seen.set()
                raise
            original_stop()

        return finish_stop()

    strategy.stop = hybrid_stop
    await runner.start()

    with pytest.raises(TimeoutError, match="stop hook"):
        await runner.stop()

    assert cancellation_seen.is_set()
    assert runner._stop_hook_task is not None
    assert runner._stop_hook_task.cancelled()

    strategy.stop = original_stop
    await runner.stop()


@pytest.mark.asyncio
async def test_external_cancellation_while_paused_clears_running_state() -> None:
    strategy = _TestStrategy(name="paused-cancel")
    runner = _runner(strategy, tick_interval=0.25)
    await runner.start()
    runner.pause()
    task = runner._task
    assert task is not None

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert runner.is_running is False
    assert task.done()
    await runner.stop()


@pytest.mark.asyncio
async def test_threadsafe_stop_all_runs_on_bound_runtime_loop() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    runner = scheduler.register(_TestStrategy(name="bound-all"))
    runner.scheduler = _open_time_scheduler()
    runner.client.quotes = AsyncMock(return_value=None)
    runtime_loop = asyncio.get_running_loop()
    scheduler.bind_runtime_loop(runtime_loop)

    await runner.start()
    await asyncio.to_thread(scheduler.stop_all_threadsafe)

    assert runner.is_running is False
    assert runner._task is None


@pytest.mark.asyncio
async def test_start_all_drains_a_timed_out_start_before_late_activation_can_escape() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    strategy = _TestStrategy(name="aggregate-late-start")
    start_entered = threading.Event()
    release_start = threading.Event()
    original_start = strategy.start

    def delayed_start() -> None:
        start_entered.set()
        if not release_start.wait(timeout=1.0):
            raise AssertionError("timed out waiting to release the start hook")
        original_start()

    strategy.start = delayed_start
    runner = scheduler.register(strategy)
    runner.scheduler = _open_time_scheduler()
    runner.client.quotes = AsyncMock(return_value=None)
    runner.lifecycle_timeout = 0.1

    rollback_entered = asyncio.Event()
    allow_rollback = asyncio.Event()
    original_runner_stop = runner.stop

    async def observed_stop() -> None:
        rollback_entered.set()
        await allow_rollback.wait()
        await original_runner_stop()

    runner.stop = observed_stop

    start_all = asyncio.create_task(scheduler.start_all())
    try:
        assert await asyncio.to_thread(start_entered.wait, 1.0)
        await asyncio.wait_for(rollback_entered.wait(), timeout=1.0)
        assert start_all.done() is False

        release_start.set()
        allow_rollback.set()
        result = (await asyncio.gather(start_all, return_exceptions=True))[0]

        assert isinstance(result, TimeoutError)
        assert runner.has_live_owner is False
        assert strategy.state.value == "STOPPED"
    finally:
        release_start.set()
        allow_rollback.set()
        await asyncio.gather(start_all, return_exceptions=True)
        if runner.has_live_owner:
            await original_runner_stop()


_LIFECYCLE_SETTLE_TIMEOUT = 5.0
"""How long a lifecycle transition is given to settle before it counts as wedged.

Generous on purpose. The property under test is *whether* a transition completes
at all, never how fast; a fixed sub-100 ms budget turned an ordinary scheduling
hiccup on a loaded host into a failure (the same wall-clock flake 8ae51cd0
removed from the ollama_runtime tests). ``asyncio.wait`` returns the moment the
task finishes, so the healthy path is still as quick as the machine allows and
only a genuine wedge waits out the whole budget.
"""


async def _assert_settles(task: "asyncio.Task[None]", message: str) -> None:
    """Assert one lifecycle task completes rather than holding a lock forever.

    Args:
        task: The transition task that must not stay pending.
        message: The assertion message describing the wedge being ruled out.
    """
    done, _pending = await asyncio.wait({task}, timeout=_LIFECYCLE_SETTLE_TIMEOUT)
    assert task in done, message


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_never_returning_start_hook_does_not_wedge_scheduler_transitions() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    blocked_strategy = _TestStrategy(name="blocked-generation")
    healthy_strategy = _TestStrategy(name="healthy-generation")
    blocked = scheduler.register(blocked_strategy)
    healthy = scheduler.register(healthy_strategy)
    for runner in (blocked, healthy):
        runner.scheduler = _open_time_scheduler()
        runner.client.quotes = AsyncMock(return_value=None)
        runner.lifecycle_timeout = 0.01

    hook_entered = threading.Event()
    release_hook = threading.Event()
    original_start = blocked_strategy.start

    def never_returning_start() -> None:
        hook_entered.set()
        release_hook.wait()
        original_start()

    blocked_strategy.start = never_returning_start
    blocked_start = asyncio.create_task(scheduler.start_one(blocked_strategy.name))
    healthy_start: asyncio.Task[None] | None = None
    aggregate_stop: asyncio.Task[None] | None = None
    try:
        assert await asyncio.to_thread(hook_entered.wait, _LIFECYCLE_SETTLE_TIMEOUT)

        await _assert_settles(blocked_start, "a wedged hook retained the scheduler transition lock")
        blocked_result = (await asyncio.gather(blocked_start, return_exceptions=True))[0]
        assert isinstance(blocked_result, TimeoutError)
        assert blocked.has_live_owner is True
        assert blocked.is_running is False
        assert blocked._task is None

        healthy_start = asyncio.create_task(scheduler.start_one(healthy_strategy.name))
        await _assert_settles(healthy_start, "a quarantined generation blocked a later start")
        await healthy_start
        assert healthy.is_running is True

        aggregate_stop = asyncio.create_task(scheduler.stop_all())
        await _assert_settles(aggregate_stop, "a quarantined generation blocked aggregate shutdown")
        stop_result = (await asyncio.gather(aggregate_stop, return_exceptions=True))[0]
        assert isinstance(stop_result, ExceptionGroup)
        assert healthy.has_live_owner is False
        assert blocked.has_live_owner is True
    finally:
        release_hook.set()
        await asyncio.gather(blocked_start, return_exceptions=True)
        if healthy_start is not None:
            await asyncio.gather(healthy_start, return_exceptions=True)
        if aggregate_stop is not None:
            await asyncio.gather(aggregate_stop, return_exceptions=True)
        start_hook = blocked._start_hook_task
        if start_hook is not None:
            await asyncio.wait_for(start_hook, timeout=_LIFECYCLE_SETTLE_TIMEOUT)
        await blocked.stop()

    assert blocked.has_live_owner is False
    assert blocked_strategy.state.value == "STOPPED"


@pytest.mark.asyncio
async def test_failed_start_drain_honours_its_cleanup_deadline() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    strategy = _TestStrategy(name="bounded-drain")
    runner = scheduler.register(strategy)
    runner.scheduler = _open_time_scheduler()
    runner.client.quotes = AsyncMock(return_value=None)
    runner.lifecycle_timeout = 1.0
    hook_entered = threading.Event()
    release_hook = threading.Event()

    def blocked_start() -> None:
        hook_entered.set()
        release_hook.wait()

    strategy.start = blocked_start
    start_hook, worker_active = runner._create_lifecycle_hook_task(strategy.start)
    with runner._ownership_lock:
        runner._cleanup_required = True
        runner._start_hook_task = start_hook
        runner._start_hook_worker_active = worker_active
    try:
        assert await asyncio.to_thread(hook_entered.wait, 0.5)
        started = asyncio.get_running_loop().time()
        terminal = await scheduler._drain_failed_start(runner, timeout=0.03)
        elapsed = asyncio.get_running_loop().time() - started

        assert terminal is False
        assert elapsed < 0.15
        assert runner.is_quarantined is True
        assert runner.has_live_owner is True
    finally:
        release_hook.set()
        await asyncio.wait_for(start_hook, timeout=0.5)
        await runner.stop()


@pytest.mark.asyncio
async def test_start_all_rolls_back_runners_started_before_a_later_failure() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    first_strategy = _TestStrategy(name="aggregate-first")
    first = scheduler.register(first_strategy)
    failing_strategy = _TestStrategy(name="aggregate-failure")
    failing_strategy.start = MagicMock(side_effect=RuntimeError("second start failed"))
    failing = scheduler.register(failing_strategy)
    for runner in (first, failing):
        runner.scheduler = _open_time_scheduler()
        runner.client.quotes = AsyncMock(return_value=None)

    try:
        with pytest.raises(RuntimeError, match="second start failed"):
            await scheduler.start_all()

        assert first.has_live_owner is False
        assert failing.has_live_owner is False
        assert first_strategy.state.value == "STOPPED"
        assert failing_strategy.state.value == "STOPPED"
    finally:
        await scheduler.stop_all()


@pytest.mark.asyncio
async def test_stop_all_rejects_restart_admitted_during_aggregate_stop() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    first = scheduler.register(_TestStrategy(name="first"))
    slow_strategy = _TestStrategy(name="slow")
    slow = scheduler.register(slow_strategy)
    for runner in (first, slow):
        runner.scheduler = _open_time_scheduler()
        runner.client.quotes = AsyncMock(return_value=None)

    stop_entered = asyncio.Event()
    release_stop = asyncio.Event()
    original_stop = slow_strategy.stop

    async def delayed_stop() -> None:
        stop_entered.set()
        await release_stop.wait()
        original_stop()

    slow_strategy.stop = delayed_stop
    await scheduler.start_all()
    aggregate_stop = asyncio.create_task(scheduler.stop_all())
    await asyncio.wait_for(stop_entered.wait(), timeout=1.0)

    restart = asyncio.create_task(scheduler.start_one("first"))
    try:
        with pytest.raises(RuntimeError, match="aggregate stop"):
            await asyncio.wait_for(restart, timeout=1.0)
    finally:
        release_stop.set()
        await aggregate_stop

    assert first.is_running is False
    assert slow.is_running is False


@pytest.mark.asyncio
async def test_stop_all_rejects_direct_runner_restart_during_aggregate_stop() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    first = scheduler.register(_TestStrategy(name="direct-first"))
    slow_strategy = _TestStrategy(name="direct-slow")
    slow = scheduler.register(slow_strategy)
    for runner in (first, slow):
        runner.scheduler = _open_time_scheduler()
        runner.client.quotes = AsyncMock(return_value=None)

    stop_entered = asyncio.Event()
    release_stop = asyncio.Event()
    original_stop = slow_strategy.stop

    async def delayed_stop() -> None:
        stop_entered.set()
        await release_stop.wait()
        original_stop()

    slow_strategy.stop = delayed_stop
    await scheduler.start_all()
    aggregate_stop = asyncio.create_task(scheduler.stop_all())
    await asyncio.wait_for(stop_entered.wait(), timeout=1.0)

    try:
        with pytest.raises(RuntimeError, match="aggregate stop"):
            await first.start()
    finally:
        release_stop.set()
        await aggregate_stop

    assert first.is_running is False
    assert slow.is_running is False


@pytest.mark.asyncio
async def test_threadsafe_stop_all_timeout_does_not_cancel_remaining_cleanup() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    slow_strategy = _TestStrategy(name="slow-first")
    slow = scheduler.register(slow_strategy)
    last = scheduler.register(_TestStrategy(name="last"))
    for runner in (slow, last):
        runner.scheduler = _open_time_scheduler()
        runner.client.quotes = AsyncMock(return_value=None)

    release_stop = asyncio.Event()
    original_stop = slow_strategy.stop

    async def delayed_stop() -> None:
        await release_stop.wait()
        original_stop()

    slow_strategy.stop = delayed_stop
    runtime_loop = asyncio.get_running_loop()
    scheduler.bind_runtime_loop(runtime_loop)
    scheduler._runtime_call_timeout = 0.02
    await scheduler.start_all()

    with pytest.raises(TimeoutError):
        await asyncio.to_thread(scheduler.stop_all_threadsafe)

    release_stop.set()
    deadline = runtime_loop.time() + 1.0
    while (slow.is_running or last.is_running) and runtime_loop.time() < deadline:
        await asyncio.sleep(0.005)

    assert slow.is_running is False
    assert last.is_running is False


@pytest.mark.asyncio
async def test_self_stop_blocks_restart_until_original_tick_loop_exits() -> None:
    strategy = _TestStrategy(name="self-stop-restart")
    runner = _runner(strategy)
    stop_returned = asyncio.Event()
    release_old_tick = asyncio.Event()

    async def stop_and_hold(_quote: Quote) -> None:
        await runner.stop()
        stop_returned.set()
        await release_old_tick.wait()

    strategy.on_tick = stop_and_hold
    await runner.start()
    old_task = runner._task
    assert old_task is not None
    await asyncio.wait_for(stop_returned.wait(), timeout=1.0)

    with pytest.raises(RuntimeError, match="cleanup did not complete"):
        await runner.start()
    assert runner._task is old_task

    release_old_tick.set()
    await asyncio.wait_for(old_task, timeout=1.0)
    await runner.start()
    assert runner._task is not old_task
    await runner.stop()


@pytest.mark.asyncio
async def test_stop_all_from_on_tick_stops_caller_without_cancelling_aggregate() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    strategy = _TestStrategy(name="aggregate-self-stop")
    runner = scheduler.register(strategy)
    runner.scheduler = _open_time_scheduler()
    runner.client.quotes = AsyncMock(return_value=Quote(symbol="RELIANCE", exchange="NSE", ltp=100))
    aggregate_returned = asyncio.Event()

    async def stop_all_from_tick(_quote: Quote) -> None:
        await scheduler.stop_all()
        aggregate_returned.set()

    strategy.on_tick = stop_all_from_tick
    await runner.start()

    await asyncio.wait_for(aggregate_returned.wait(), timeout=1.0)
    task = runner._task
    assert task is not None
    await asyncio.wait_for(task, timeout=1.0)
    assert runner.cleanup_required is False
    assert strategy.state.value == "STOPPED"


@pytest.mark.asyncio
async def test_self_initiated_stop_all_starts_peer_shutdown_before_caller_hook_finishes() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    caller_strategy = _TestStrategy(name="aggregate-caller")
    caller = scheduler.register(caller_strategy)
    peer_strategy = _TestStrategy(name="aggregate-peer")
    peer = scheduler.register(peer_strategy)
    for runner in (caller, peer):
        runner.scheduler = _open_time_scheduler()
        runner.client.quotes = AsyncMock(return_value=None)

    caller_stop_entered = asyncio.Event()
    release_caller_stop = asyncio.Event()
    original_caller_stop = caller_strategy.stop

    async def delayed_caller_stop() -> None:
        caller_stop_entered.set()
        await release_caller_stop.wait()
        original_caller_stop()

    async def stop_all_from_tick(_quote: Quote) -> None:
        await scheduler.stop_all()

    caller_strategy.stop = delayed_caller_stop
    caller_strategy.on_tick = stop_all_from_tick
    caller.client.quotes = AsyncMock(return_value=Quote(symbol="RELIANCE", exchange="NSE", ltp=100))
    await scheduler.start_all()

    await asyncio.wait_for(caller_stop_entered.wait(), timeout=1.0)
    try:
        await asyncio.wait_for(_wait_for_strategy_state(peer_strategy, "STOPPED"), timeout=0.2)
    finally:
        release_caller_stop.set()
    task = caller._task
    assert task is not None
    await asyncio.wait_for(task, timeout=1.0)
    assert peer.is_running is False


@pytest.mark.asyncio
async def test_stop_all_from_child_task_retains_tick_ownership() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    strategy = _TestStrategy(name="aggregate-child")
    runner = scheduler.register(strategy)
    runner.scheduler = _open_time_scheduler()
    runner.client.quotes = AsyncMock(return_value=Quote(symbol="RELIANCE", exchange="NSE", ltp=100))
    aggregate_returned = asyncio.Event()

    async def stop_all_from_child(_quote: Quote) -> None:
        await asyncio.create_task(scheduler.stop_all())
        aggregate_returned.set()

    strategy.on_tick = stop_all_from_child
    await runner.start()

    await asyncio.wait_for(aggregate_returned.wait(), timeout=1.0)
    task = runner._task
    assert task is not None
    await asyncio.wait_for(task, timeout=1.0)
    assert runner.cleanup_required is False
    assert strategy.state.value == "STOPPED"


@pytest.mark.asyncio
async def test_detached_tick_child_cannot_claim_ownership_after_runner_restart() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    strategy = _TestStrategy(name="stale-child")
    runner = scheduler.register(strategy)
    runner.scheduler = _open_time_scheduler()
    runner.client.quotes = AsyncMock(return_value=Quote(symbol="RELIANCE", exchange="NSE", ltp=100))
    detached_started = asyncio.Event()
    release_detached = asyncio.Event()
    detached_returned = asyncio.Event()
    first_tick_returned = asyncio.Event()
    replacement_entered = asyncio.Event()
    replacement_finished = asyncio.Event()

    async def detached_stop() -> None:
        detached_started.set()
        await release_detached.wait()
        await scheduler.stop_all()
        detached_returned.set()

    async def first_tick(_quote: Quote) -> None:
        asyncio.create_task(detached_stop())
        await detached_started.wait()
        first_tick_returned.set()

    strategy.on_tick = first_tick
    await runner.start()
    await asyncio.wait_for(first_tick_returned.wait(), timeout=1.0)
    await runner.stop()

    async def replacement_tick(_quote: Quote) -> None:
        replacement_entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            replacement_finished.set()

    strategy.on_tick = replacement_tick
    await runner.start()
    await asyncio.wait_for(replacement_entered.wait(), timeout=1.0)
    release_detached.set()

    await asyncio.wait_for(detached_returned.wait(), timeout=1.0)
    await asyncio.wait_for(replacement_finished.wait(), timeout=1.0)
    assert runner.is_running is False
    assert runner.cleanup_required is False


@pytest.mark.asyncio
async def test_nested_stop_from_square_off_retains_tick_ownership() -> None:
    strategy = _TestStrategy(name="square-off-child-stop")
    runner = _runner(strategy)
    runner.scheduler.should_square_off = MagicMock(return_value=True)
    square_off_returned = asyncio.Event()

    async def square_off() -> None:
        await asyncio.create_task(runner.stop())
        square_off_returned.set()

    strategy.on_square_off = square_off
    await runner.start()

    await asyncio.wait_for(square_off_returned.wait(), timeout=1.0)
    task = runner._task
    assert task is not None
    await asyncio.wait_for(task, timeout=1.0)
    assert strategy.state.value == "STOPPED"
    assert runner.cleanup_required is False


@pytest.mark.asyncio
async def test_square_off_releases_stop_hook_before_next_generation() -> None:
    strategy = _TestStrategy(name="square-off-generation")
    runner = _runner(strategy)
    runner.scheduler.should_square_off = MagicMock(return_value=True)
    original_stop = strategy.stop
    strategy.stop = MagicMock(side_effect=original_stop)

    await runner.start()
    first_task = runner._task
    assert first_task is not None
    await asyncio.wait_for(first_task, timeout=1.0)
    assert strategy.stop.call_count == 1
    assert runner._stop_hook_task is None
    assert runner.cleanup_required is False

    runner.scheduler.should_square_off = MagicMock(return_value=False)
    await runner.start()
    await runner.stop()

    assert strategy.stop.call_count == 2
    assert strategy.state.value == "STOPPED"
    assert runner.has_live_owner is False


@pytest.mark.asyncio
async def test_overlapping_square_off_stops_share_exactly_one_stop_hook() -> None:
    strategy = _TestStrategy(name="square-off-overlap")
    runner = _runner(strategy)
    runner.scheduler.should_square_off = MagicMock(return_value=True)
    stop_entered = asyncio.Event()
    release_stop = asyncio.Event()
    original_stop = strategy.stop

    async def delayed_stop() -> None:
        stop_entered.set()
        await release_stop.wait()
        original_stop()

    strategy.stop = AsyncMock(side_effect=delayed_stop)

    async def nested_stop() -> None:
        await asyncio.create_task(runner.stop())

    strategy.on_square_off = nested_stop
    await runner.start()
    await asyncio.wait_for(stop_entered.wait(), timeout=1.0)
    external_stop = asyncio.create_task(runner.stop())
    await asyncio.sleep(0.01)
    release_stop.set()

    await asyncio.wait_for(external_stop, timeout=1.0)
    task = runner._task
    if task is not None:
        await asyncio.wait_for(task, timeout=1.0)
    strategy.stop.assert_awaited_once_with()
    assert runner.cleanup_required is False


@pytest.mark.asyncio
async def test_external_stop_during_self_stop_handoff_reuses_completed_hook() -> None:
    strategy = _TestStrategy(name="self-stop-handoff")
    runner = _runner(strategy)
    self_stop_returned = asyncio.Event()
    release_tick = asyncio.Event()
    original_stop = strategy.stop
    strategy.stop = MagicMock(side_effect=original_stop)

    async def stop_and_hold(_quote: Quote) -> None:
        await runner.stop()
        self_stop_returned.set()
        await release_tick.wait()

    strategy.on_tick = stop_and_hold
    await runner.start()
    await asyncio.wait_for(self_stop_returned.wait(), timeout=1.0)

    await runner.stop()

    strategy.stop.assert_called_once_with()
    assert runner.cleanup_required is False


@pytest.mark.asyncio
async def test_sync_hook_returning_awaitable_can_observe_owner_loop() -> None:
    strategy = _TestStrategy(name="hybrid-owner-loop")
    runner = _runner(strategy)
    owner_loop = asyncio.get_running_loop()
    observed_loops: list[asyncio.AbstractEventLoop] = []
    original_start = strategy.start

    def hybrid_start() -> Coroutine[Any, Any, None]:
        observed_loops.append(asyncio.get_running_loop())

        async def finish_start() -> None:
            original_start()

        return finish_start()

    strategy.start = hybrid_start

    await runner.start()
    assert observed_loops == [owner_loop]
    await runner.stop()


@pytest.mark.asyncio
async def test_awaitable_return_alias_executes_hook_prefix_on_owner_loop() -> None:
    strategy = _TestStrategy(name="hybrid-owner-alias")
    runner = _runner(strategy)
    owner_loop = asyncio.get_running_loop()
    observed_loops: list[asyncio.AbstractEventLoop] = []
    original_start = strategy.start

    def hybrid_start() -> HookResult:
        observed_loops.append(asyncio.get_running_loop())

        async def finish_start() -> None:
            original_start()

        return finish_start()

    strategy.start = hybrid_start

    await runner.start()
    assert observed_loops == [owner_loop]
    await runner.stop()


@pytest.mark.asyncio
async def test_optional_awaitable_return_alias_executes_hook_prefix_on_owner_loop() -> None:
    strategy = _TestStrategy(name="hybrid-owner-optional-alias")
    runner = _runner(strategy)
    owner_loop = asyncio.get_running_loop()
    observed_loops: list[asyncio.AbstractEventLoop] = []
    original_start = strategy.start

    def hybrid_start() -> HookResult | None:
        observed_loops.append(asyncio.get_running_loop())

        async def finish_start() -> None:
            original_start()

        return finish_start()

    strategy.start = hybrid_start

    await runner.start()
    assert observed_loops == [owner_loop]
    await runner.stop()


@pytest.mark.asyncio
async def test_type_statement_awaitable_alias_executes_hook_prefix_on_owner_loop() -> None:
    strategy = _TestStrategy(name="hybrid-owner-modern-alias")
    runner = _runner(strategy)
    owner_loop = asyncio.get_running_loop()
    observed_loops: list[asyncio.AbstractEventLoop] = []
    original_start = strategy.start

    def hybrid_start() -> ModernHookResult:
        observed_loops.append(asyncio.get_running_loop())

        async def finish_start() -> None:
            original_start()

        return finish_start()

    strategy.start = hybrid_start

    await runner.start()
    assert observed_loops == [owner_loop]
    await runner.stop()


@pytest.mark.asyncio
async def test_parameterised_type_alias_executes_hook_prefix_on_owner_loop() -> None:
    strategy = _TestStrategy(name="hybrid-owner-generic-alias")
    runner = _runner(strategy)
    owner_loop = asyncio.get_running_loop()
    observed_loops: list[asyncio.AbstractEventLoop] = []
    original_start = strategy.start

    def hybrid_start() -> GenericHookResult[None]:
        observed_loops.append(asyncio.get_running_loop())

        async def finish_start() -> None:
            original_start()

        return finish_start()

    strategy.start = hybrid_start

    await runner.start()
    assert observed_loops == [owner_loop]
    await runner.stop()


def test_lazily_unresolved_type_alias_defaults_to_worker_classification() -> None:
    namespace: dict[str, Any] = {}
    exec("type MissingHook = MissingResult", namespace)  # noqa: S102 - exercise lazy alias resolution

    assert StrategyRunner._annotation_contains_awaitable(namespace["MissingHook"]) is False


@pytest.mark.parametrize(
    "annotation",
    [
        IdentityHookResult[Coroutine[Any, Any, None]],
        MaybeHookResult[Awaitable[None]],
        MetadataHookResult[Awaitable[None]],
    ],
)
def test_parameterised_alias_substitutes_awaitable_type_arguments(annotation: Any) -> None:
    assert StrategyRunner._annotation_contains_awaitable(annotation) is True


@pytest.mark.parametrize(
    "annotation",
    [
        pytest.param(SiblingAliasChoice, id="outer-alias"),
        pytest.param(
            GenericSiblingAliasChoice[int, Awaitable[None]],
            id="generic-outer-alias",
        ),
        pytest.param(NestedSiblingAliasChoice, id="nested-alias"),
        pytest.param(AnnotatedSiblingAliasChoice, id="annotated-alias"),
        pytest.param(
            IdentityHookResult[int] | IdentityHookResult[Awaitable[None]],
            id="direct-union",
        ),
    ],
)
def test_sibling_generic_alias_branches_keep_independent_cycle_paths(annotation: Any) -> None:
    assert StrategyRunner._annotation_contains_awaitable(annotation) is True


@pytest.mark.asyncio
async def test_sibling_alias_union_executes_hook_prefix_on_owner_loop() -> None:
    strategy = _TestStrategy(name="hybrid-owner-sibling-alias")
    runner = _runner(strategy)
    owner_loop = asyncio.get_running_loop()
    observed_loops: list[asyncio.AbstractEventLoop] = []
    original_start = strategy.start

    def hybrid_start() -> SiblingAliasChoice:
        observed_loops.append(asyncio.get_running_loop())

        async def finish_start() -> None:
            original_start()

        return finish_start()

    strategy.start = hybrid_start

    await runner.start()
    assert observed_loops == [owner_loop]
    await runner.stop()


def test_optional_module_alias_resolution_defaults_to_worker_classification() -> None:
    class MissingOptionalModule:
        def __getattr__(self, name: str) -> Any:
            raise ModuleNotFoundError(f"optional type provider unavailable for {name}")

    namespace: dict[str, Any] = {"plugin_types": MissingOptionalModule()}
    exec("type OptionalHook = plugin_types.HookResult", namespace)  # noqa: S102 - lazy alias resolution

    assert StrategyRunner._annotation_contains_awaitable(namespace["OptionalHook"]) is False


@pytest.mark.asyncio
async def test_unresolved_future_named_annotation_stays_on_bounded_worker() -> None:
    class FutureStatus:
        pass

    strategy = _TestStrategy(name="unresolved-future-status")
    runner = _runner(strategy, lifecycle_timeout=0.05)
    hook_entered = threading.Event()
    release_hook = threading.Event()

    def blocking_start() -> FutureStatus:
        hook_entered.set()
        if not release_hook.wait(timeout=1.0):
            raise AssertionError("timed out waiting to release the start hook")
        return FutureStatus()

    strategy.start = blocking_start
    start_task = asyncio.create_task(runner.start())
    try:
        assert await asyncio.to_thread(hook_entered.wait, 1.0)
        with pytest.raises(TimeoutError, match="start hook"):
            await start_task
        assert runner._start_hook_worker_active is not None
        assert runner._start_hook_worker_active.is_set()
    finally:
        release_hook.set()
        runner.lifecycle_timeout = 1.0
        await asyncio.gather(start_task, return_exceptions=True)
        await runner.stop()


@pytest.mark.asyncio
async def test_stop_all_cancellation_waits_for_every_runner_cleanup() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    release_stops = asyncio.Event()
    stop_entries = [asyncio.Event(), asyncio.Event()]
    runners: list[StrategyRunner] = []

    for index in range(2):
        strategy = _TestStrategy(name=f"cancel-stop-{index}")
        original_stop = strategy.stop

        async def delayed_stop(
            *,
            entered: asyncio.Event = stop_entries[index],
            stop_hook: Callable[[], None] = original_stop,
        ) -> None:
            entered.set()
            await release_stops.wait()
            stop_hook()

        strategy.stop = delayed_stop
        runner = scheduler.register(strategy)
        runner.scheduler = _open_time_scheduler()
        runner.client.quotes = AsyncMock(return_value=None)
        runners.append(runner)

    await scheduler.start_all()
    aggregate_stop = asyncio.create_task(scheduler.stop_all())
    await asyncio.gather(*(entered.wait() for entered in stop_entries))
    aggregate_stop.cancel()
    await asyncio.sleep(0)
    assert aggregate_stop.done() is False

    release_stops.set()
    with pytest.raises(asyncio.CancelledError):
        await aggregate_stop
    assert all(not runner.is_running for runner in runners)
    assert all(not runner.cleanup_required for runner in runners)
    assert all(runner._stop_hook_task is None for runner in runners)


@pytest.mark.asyncio
async def test_stop_all_cancellation_chains_completed_cleanup_failure() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    release_stops = asyncio.Event()
    stop_entries = [asyncio.Event(), asyncio.Event()]

    for index in range(2):
        strategy = _TestStrategy(name=f"cancel-failure-{index}")
        original_stop = strategy.stop

        async def delayed_stop(
            *,
            current_index: int = index,
            entered: asyncio.Event = stop_entries[index],
            stop_hook: Callable[[], None] = original_stop,
        ) -> None:
            entered.set()
            await release_stops.wait()
            if current_index == 0:
                raise RuntimeError("stop exploded")
            stop_hook()

        strategy.stop = delayed_stop
        runner = scheduler.register(strategy)
        runner.scheduler = _open_time_scheduler()
        runner.client.quotes = AsyncMock(return_value=None)

    await scheduler.start_all()
    aggregate_stop = asyncio.create_task(scheduler.stop_all())
    await asyncio.gather(*(entered.wait() for entered in stop_entries))
    aggregate_stop.cancel()
    release_stops.set()

    with pytest.raises(asyncio.CancelledError) as cancellation:
        await aggregate_stop
    assert isinstance(cancellation.value.__cause__, ExceptionGroup)
    assert "stop exploded" in str(cancellation.value.__cause__.exceptions[0])


@pytest.mark.asyncio
async def test_start_all_rollback_retries_a_cancelled_stop_hook_to_terminal_state() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    first_strategy = _TestStrategy(name="rollback-cancelled-stop")
    first = scheduler.register(first_strategy)
    second_strategy = _TestStrategy(name="rollback-start-failure")
    second = scheduler.register(second_strategy)
    for runner in (first, second):
        runner.scheduler = _open_time_scheduler()
        runner.client.quotes = AsyncMock(return_value=None)

    original_stop = first_strategy.stop
    stop_attempts = 0

    async def cancelled_once_stop() -> None:
        nonlocal stop_attempts
        stop_attempts += 1
        if stop_attempts == 1:
            raise asyncio.CancelledError()
        original_stop()

    async def failed_start() -> None:
        raise RuntimeError("start exploded")

    first_strategy.stop = cancelled_once_stop
    second_strategy.start = failed_start

    with pytest.raises(RuntimeError, match="start exploded"):
        await scheduler.start_all()

    assert stop_attempts == 2
    assert first.has_live_owner is False
    assert second.has_live_owner is False
    assert first_strategy.state.value == "STOPPED"
    assert second_strategy.state.value == "STOPPED"


@pytest.mark.asyncio
async def test_start_all_outer_cancellation_waits_for_rollback_before_propagating() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    first_strategy = _TestStrategy(name="cancelled-rollback-owner")
    first = scheduler.register(first_strategy)
    second_strategy = _TestStrategy(name="cancelled-start")
    second = scheduler.register(second_strategy)
    for runner in (first, second):
        runner.scheduler = _open_time_scheduler()
        runner.client.quotes = AsyncMock(return_value=None)

    start_entered = asyncio.Event()
    stop_entered = asyncio.Event()
    release_stop = asyncio.Event()
    original_stop = first_strategy.stop

    async def blocked_start() -> None:
        start_entered.set()
        await asyncio.Event().wait()

    async def delayed_stop() -> None:
        stop_entered.set()
        await release_stop.wait()
        original_stop()

    second_strategy.start = blocked_start
    first_strategy.stop = delayed_stop
    start_all = asyncio.create_task(scheduler.start_all())
    await asyncio.wait_for(start_entered.wait(), timeout=1.0)

    start_all.cancel()
    await asyncio.wait_for(stop_entered.wait(), timeout=1.0)
    assert start_all.done() is False

    release_stop.set()
    with pytest.raises(asyncio.CancelledError):
        await start_all
    assert first.has_live_owner is False
    assert second.has_live_owner is False
    assert first_strategy.state.value == "STOPPED"
    assert second_strategy.state.value == "STOPPED"


def test_runner_defaults_to_strategy_symbol_before_strategy_name() -> None:
    strategy = _TestStrategy(name="EMA_9_21_RELIANCE", symbol="RELIANCE")

    runner = StrategyRunner(strategy=strategy, client=MagicMock())

    assert runner.symbol == "RELIANCE"


@pytest.mark.asyncio
async def test_threadsafe_start_and_stop_run_on_bound_runtime_loop() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    runner = scheduler.register(_TestStrategy(name="bound"))
    runner.scheduler = _open_time_scheduler()
    runner.client.quotes = AsyncMock(return_value=None)
    runtime_loop = asyncio.get_running_loop()
    scheduler.bind_runtime_loop(runtime_loop)

    await asyncio.to_thread(scheduler.start_one_threadsafe, "bound")
    assert runner.is_running is True
    assert runner._task is not None
    assert runner._task.get_loop() is runtime_loop

    await asyncio.to_thread(scheduler.stop_one_threadsafe, "bound")
    assert runner.is_running is False


@pytest.mark.asyncio
async def test_threadsafe_start_timeout_waits_for_revocation_and_rollback() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    strategy = _TestStrategy(name="revoked-start")
    start_entered = asyncio.Event()
    release_start = asyncio.Event()
    original_start = strategy.start

    async def delayed_start() -> None:
        start_entered.set()
        await release_start.wait()
        original_start()

    strategy.start = delayed_start
    runner = scheduler.register(strategy)
    runner.scheduler = _open_time_scheduler()
    runner.client.quotes = AsyncMock(return_value=None)
    scheduler.bind_runtime_loop(asyncio.get_running_loop())
    scheduler._runtime_call_timeout = 0.02

    request = asyncio.create_task(
        asyncio.to_thread(scheduler.start_one_threadsafe, strategy.name)
    )
    await asyncio.wait_for(start_entered.wait(), timeout=1.0)
    try:
        await asyncio.sleep(0.04)
        assert not request.done(), "the route-facing call returned before rollback could finish"
    finally:
        release_start.set()

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(request, timeout=1.0)
    assert runner.is_running is False
    assert runner.cleanup_required is False
    assert strategy.state.value == "STOPPED"

    await asyncio.sleep(0.02)
    assert runner.is_running is False


@pytest.mark.asyncio
async def test_threadsafe_stop_timeout_reports_in_progress_while_cleanup_keeps_running() -> None:
    from flinttrade_engine.scheduler import StrategyStopTimeoutError

    scheduler = StrategyScheduler(client=MagicMock())
    strategy = _TestStrategy(name="bounded-stop")
    stop_entered = asyncio.Event()
    release_stop = asyncio.Event()
    original_stop = strategy.stop

    async def delayed_stop() -> None:
        stop_entered.set()
        await release_stop.wait()
        original_stop()

    strategy.stop = delayed_stop
    runner = scheduler.register(strategy)
    runner.scheduler = _open_time_scheduler()
    runner.client.quotes = AsyncMock(return_value=None)
    scheduler.bind_runtime_loop(asyncio.get_running_loop())
    scheduler._runtime_call_timeout = 0.02
    await runner.start()

    stop_request = asyncio.create_task(
        asyncio.to_thread(scheduler.stop_one_threadsafe, strategy.name)
    )
    await asyncio.wait_for(stop_entered.wait(), timeout=1.0)
    try:
        with pytest.raises(StrategyStopTimeoutError, match="still in progress"):
            await asyncio.wait_for(stop_request, timeout=1.0)
        assert runner.has_live_owner is True
    finally:
        release_stop.set()

    await asyncio.wait_for(_wait_for_strategy_state(strategy, "STOPPED"), timeout=1.0)
    deadline = asyncio.get_running_loop().time() + 1.0
    while runner.has_live_owner and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.005)
    assert runner.has_live_owner is False


@pytest.mark.asyncio
async def test_threadsafe_start_preserves_completed_coroutine_timeout_error() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    strategy = _TestStrategy(name="inner-start-timeout")

    async def failing_start() -> None:
        raise TimeoutError("strategy start failed internally")

    strategy.start = failing_start
    runner = scheduler.register(strategy)
    runner.scheduler = _open_time_scheduler()
    scheduler.bind_runtime_loop(asyncio.get_running_loop())

    with pytest.raises(TimeoutError, match="strategy start failed internally") as raised:
        await asyncio.to_thread(scheduler.start_one_threadsafe, strategy.name)

    assert type(raised.value) is TimeoutError
    assert runner.has_live_owner is False


@pytest.mark.asyncio
async def test_threadsafe_stop_preserves_completed_coroutine_timeout_error() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    strategy = _TestStrategy(name="inner-stop-timeout")
    original_stop = strategy.stop

    async def failing_stop() -> None:
        raise TimeoutError("strategy stop failed internally")

    strategy.stop = failing_stop
    runner = scheduler.register(strategy)
    runner.scheduler = _open_time_scheduler()
    scheduler.bind_runtime_loop(asyncio.get_running_loop())
    await runner.start()

    try:
        with pytest.raises(TimeoutError, match="strategy stop failed internally") as raised:
            await asyncio.to_thread(scheduler.stop_one_threadsafe, strategy.name)
        assert type(raised.value) is TimeoutError
    finally:
        strategy.stop = original_stop
        await runner.stop()


def test_scheduler_registration_requires_explicit_execution_contract() -> None:
    scheduler = StrategyScheduler(client=MagicMock())
    strategy = _TestStrategy(name="undeclared")
    strategy._execution_contract = None

    with pytest.raises(RuntimeError, match="execution contract"):
        scheduler.register(strategy)


def test_scheduler_rejects_live_strategy_with_raw_broker_mutation_handle() -> None:
    from flinttrade_engine.safety import SafetyConfig, SafetySystem

    class RawClient:
        async def place_order(self, _order: Order) -> None:
            return None

    class LiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.LIVE_GATED})
        uses_managed_order_dispatch = True

    dispatcher = GatedStrategyDispatcher(
        safety=SafetySystem(SafetyConfig()),
        request_context_provider=MagicMock(),
        router_provider=MagicMock(),
        adapter_id="openalgo",
        account_id="default",
    )
    strategy = LiveStrategy(
        name="raw-live",
        execution_contract=StrategyExecutionContract.live(dispatcher),
    )
    strategy._client = RawClient()

    with pytest.raises(RuntimeError, match="raw broker mutation handle"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_rejects_live_strategy_with_arbitrarily_named_raw_broker_handle() -> None:
    from flinttrade_engine.safety import SafetyConfig, SafetySystem

    class RawClient:
        async def place_order(self, _order: Order) -> None:
            return None

    class LiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.LIVE_GATED})
        uses_managed_order_dispatch = True

    dispatcher = GatedStrategyDispatcher(
        safety=SafetySystem(SafetyConfig()),
        request_context_provider=MagicMock(),
        router_provider=MagicMock(),
        adapter_id="openalgo",
        account_id="default",
    )
    strategy = LiveStrategy(
        name="arbitrary-raw-live",
        execution_contract=StrategyExecutionContract.live(dispatcher),
    )
    strategy._api = RawClient()

    with pytest.raises(RuntimeError, match="raw broker mutation handle '_api'"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_rejects_live_strategy_with_retained_bound_broker_write() -> None:
    from flinttrade_engine.safety import SafetyConfig, SafetySystem

    class RawClient:
        async def place_order(self, _order: Order) -> None:
            return None

    class LiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.LIVE_GATED})
        uses_managed_order_dispatch = True

    dispatcher = GatedStrategyDispatcher(
        safety=SafetySystem(SafetyConfig()),
        request_context_provider=MagicMock(),
        router_provider=MagicMock(),
        adapter_id="openalgo",
        account_id="default",
    )
    strategy = LiveStrategy(
        name="bound-raw-live",
        execution_contract=StrategyExecutionContract.live(dispatcher),
    )
    strategy._submit = RawClient().place_order

    with pytest.raises(RuntimeError, match="raw broker mutation handle '_submit'"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_rejects_live_strategy_with_partial_wrapped_broker_write() -> None:
    from flinttrade_engine.safety import SafetyConfig, SafetySystem

    class RawClient:
        async def place_order(self, _order: Order) -> None:
            return None

    class LiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.LIVE_GATED})
        uses_managed_order_dispatch = True

    dispatcher = GatedStrategyDispatcher(
        safety=SafetySystem(SafetyConfig()),
        request_context_provider=MagicMock(),
        router_provider=MagicMock(),
        adapter_id="openalgo",
        account_id="default",
    )
    strategy = LiveStrategy(
        name="partial-raw-live",
        execution_contract=StrategyExecutionContract.live(dispatcher),
    )
    strategy._submit = functools.partial(RawClient().place_order)

    with pytest.raises(RuntimeError, match="raw broker mutation handle"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_rejects_live_strategy_with_closure_wrapped_broker_write() -> None:
    from flinttrade_engine.safety import SafetyConfig, SafetySystem

    class RawClient:
        async def place_order(self, _order: Order) -> None:
            return None

    class LiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.LIVE_GATED})
        uses_managed_order_dispatch = True

    raw_client = RawClient()

    async def submit(order: Order) -> None:
        await raw_client.place_order(order)

    dispatcher = GatedStrategyDispatcher(
        safety=SafetySystem(SafetyConfig()),
        request_context_provider=MagicMock(),
        router_provider=MagicMock(),
        adapter_id="openalgo",
        account_id="default",
    )
    strategy = LiveStrategy(
        name="closure-raw-live",
        execution_contract=StrategyExecutionContract.live(dispatcher),
    )
    strategy._submit = submit

    with pytest.raises(RuntimeError, match="raw broker mutation handle"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_rejects_live_strategy_with_callable_broker_wrapper() -> None:
    from flinttrade_engine.safety import SafetyConfig, SafetySystem

    class RawClient:
        async def place_order(self, _order: Order) -> None:
            return None

    class CallableWrapper:
        def __init__(self, client: RawClient) -> None:
            self._client = client

        async def __call__(self, order: Order) -> None:
            await self._client.place_order(order)

    class LiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.LIVE_GATED})
        uses_managed_order_dispatch = True

    dispatcher = GatedStrategyDispatcher(
        safety=SafetySystem(SafetyConfig()),
        request_context_provider=MagicMock(),
        router_provider=MagicMock(),
        adapter_id="openalgo",
        account_id="default",
    )
    strategy = LiveStrategy(
        name="callable-wrapper-live",
        execution_contract=StrategyExecutionContract.live(dispatcher),
    )
    strategy._submit = CallableWrapper(RawClient())

    with pytest.raises(RuntimeError, match="raw broker mutation handle"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_rejects_live_strategy_with_class_held_callable_broker_wrapper() -> None:
    from flinttrade_engine.safety import SafetyConfig, SafetySystem

    class RawClient:
        async def place_order(self, _order: Order) -> None:
            return None

    class CallableWrapper:
        __slots__ = ()
        _client = RawClient()

        async def __call__(self, order: Order) -> None:
            await self._client.place_order(order)

    class LiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.LIVE_GATED})
        uses_managed_order_dispatch = True

    dispatcher = GatedStrategyDispatcher(
        safety=SafetySystem(SafetyConfig()),
        request_context_provider=MagicMock(),
        router_provider=MagicMock(),
        adapter_id="openalgo",
        account_id="default",
    )
    strategy = LiveStrategy(
        name="class-callable-wrapper-live",
        execution_contract=StrategyExecutionContract.live(dispatcher),
    )
    strategy._submit = CallableWrapper()

    with pytest.raises(RuntimeError, match="raw broker mutation handle"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_rejects_live_strategy_with_nested_cyclic_broker_handle() -> None:
    from flinttrade_engine.safety import SafetyConfig, SafetySystem

    class RawClient:
        async def place_order(self, _order: Order) -> None:
            return None

    class Holder:
        def __init__(self, client: RawClient) -> None:
            self.client = client

    class LiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.LIVE_GATED})
        uses_managed_order_dispatch = True

    dispatcher = GatedStrategyDispatcher(
        safety=SafetySystem(SafetyConfig()),
        request_context_provider=MagicMock(),
        router_provider=MagicMock(),
        adapter_id="openalgo",
        account_id="default",
    )
    strategy = LiveStrategy(
        name="nested-raw-live",
        execution_contract=StrategyExecutionContract.live(dispatcher),
    )
    nested: list[Any] = []
    nested.append(nested)
    nested.append({"holder": Holder(RawClient())})
    strategy._state_cache = nested

    with pytest.raises(RuntimeError, match="raw broker mutation handle"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_rejects_live_strategy_with_class_held_broker_handle() -> None:
    from flinttrade_engine.safety import SafetyConfig, SafetySystem

    class RawClient:
        async def place_order(self, _order: Order) -> None:
            return None

    class LiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.LIVE_GATED})
        uses_managed_order_dispatch = True
        _api = RawClient()

    dispatcher = GatedStrategyDispatcher(
        safety=SafetySystem(SafetyConfig()),
        request_context_provider=MagicMock(),
        router_provider=MagicMock(),
        adapter_id="openalgo",
        account_id="default",
    )
    strategy = LiveStrategy(
        name="class-raw-live",
        execution_contract=StrategyExecutionContract.live(dispatcher),
    )

    with pytest.raises(RuntimeError, match="raw broker mutation handle"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_rejects_live_strategy_with_unauthorised_dispatcher() -> None:
    from flinttrade_engine.safety import SafetyConfig, SafetySystem

    class LiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.LIVE_GATED})
        uses_managed_order_dispatch = True

    authorised = GatedStrategyDispatcher(
        safety=SafetySystem(SafetyConfig()),
        request_context_provider=MagicMock(),
        router_provider=MagicMock(),
        adapter_id="openalgo",
        account_id="default",
    )
    unauthorised = GatedStrategyDispatcher(
        safety=SafetySystem(SafetyConfig()),
        request_context_provider=MagicMock(),
        router_provider=MagicMock(),
        adapter_id="openalgo",
        account_id="other",
    )
    strategy = LiveStrategy(
        name="unauthorised-dispatcher-live",
        execution_contract=StrategyExecutionContract.live(authorised),
    )
    strategy._other_dispatcher = unauthorised

    with pytest.raises(RuntimeError, match="raw broker mutation handle '_other_dispatcher'"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_rejects_live_strategy_with_dispatch_order_lookalike() -> None:
    from flinttrade_engine.safety import SafetyConfig, SafetySystem

    class DispatchLookalike:
        async def dispatch_order(self, _order: Order) -> None:
            return None

    class LiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.LIVE_GATED})
        uses_managed_order_dispatch = True

    dispatcher = GatedStrategyDispatcher(
        safety=SafetySystem(SafetyConfig()),
        request_context_provider=MagicMock(),
        router_provider=MagicMock(),
        adapter_id="openalgo",
        account_id="default",
    )
    strategy = LiveStrategy(
        name="dispatch-lookalike-live",
        execution_contract=StrategyExecutionContract.live(dispatcher),
    )
    strategy._orders = DispatchLookalike()

    with pytest.raises(RuntimeError, match="raw broker mutation handle '_orders'"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_rejects_live_strategy_with_module_global_broker_write(monkeypatch) -> None:
    from flinttrade_engine.safety import SafetyConfig, SafetySystem

    class RawClient:
        async def place_order(self, _order: Order) -> None:
            return None

    class LiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.LIVE_GATED})
        uses_managed_order_dispatch = True

    monkeypatch.setitem(
        _write_through_module_global.__globals__,
        "_MODULE_GLOBAL_RAW_WRITER",
        RawClient(),
    )
    dispatcher = GatedStrategyDispatcher(
        safety=SafetySystem(SafetyConfig()),
        request_context_provider=MagicMock(),
        router_provider=MagicMock(),
        adapter_id="openalgo",
        account_id="default",
    )
    strategy = LiveStrategy(
        name="module-global-live",
        execution_contract=StrategyExecutionContract.live(dispatcher),
    )
    strategy._submit = _write_through_module_global

    with pytest.raises(RuntimeError, match="raw broker mutation handle '_submit'"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_rejects_live_strategy_with_weakref_slotted_callable() -> None:
    from flinttrade_engine.safety import SafetyConfig, SafetySystem

    class RawClient:
        async def place_order(self, _order: Order) -> None:
            return None

    class WeakCallable:
        __slots__ = ("_writer",)

        def __init__(self, writer: RawClient) -> None:
            self._writer = weakref.ref(writer)

        async def __call__(self, order: Order) -> None:
            writer = self._writer()
            if writer is not None:
                await writer.place_order(order)

    class LiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.LIVE_GATED})
        uses_managed_order_dispatch = True

    raw_client = RawClient()
    dispatcher = GatedStrategyDispatcher(
        safety=SafetySystem(SafetyConfig()),
        request_context_provider=MagicMock(),
        router_provider=MagicMock(),
        adapter_id="openalgo",
        account_id="default",
    )
    strategy = LiveStrategy(
        name="weakref-live",
        execution_contract=StrategyExecutionContract.live(dispatcher),
    )
    strategy._submit = WeakCallable(raw_client)

    with pytest.raises(RuntimeError, match="raw broker mutation handle '_submit'"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_rejects_live_strategy_with_shadowed_instance_dictionary() -> None:
    from flinttrade_engine.safety import SafetyConfig, SafetySystem

    class RawClient:
        async def place_order(self, _order: Order) -> None:
            return None

    class ShadowedHandle:
        @property
        def __dict__(self) -> dict[str, Any]:
            return {}

        def __init__(self, writer: RawClient) -> None:
            self._writer = writer

        async def __call__(self, order: Order) -> None:
            await self._writer.place_order(order)

    class LiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.LIVE_GATED})
        uses_managed_order_dispatch = True

    dispatcher = GatedStrategyDispatcher(
        safety=SafetySystem(SafetyConfig()),
        request_context_provider=MagicMock(),
        router_provider=MagicMock(),
        adapter_id="openalgo",
        account_id="default",
    )
    strategy = LiveStrategy(
        name="shadowed-dict-live",
        execution_contract=StrategyExecutionContract.live(dispatcher),
    )
    strategy._submit = ShadowedHandle(RawClient())

    with pytest.raises(RuntimeError, match="cannot be safely inspected"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_rejects_live_strategy_with_dynamic_global_lookup(monkeypatch) -> None:
    from flinttrade_engine.safety import SafetyConfig, SafetySystem

    class RawClient:
        async def place_order(self, _order: Order) -> None:
            return None

    class LiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.LIVE_GATED})
        uses_managed_order_dispatch = True

    monkeypatch.setitem(
        _write_through_dynamic_globals.__globals__,
        "_DYNAMIC_GLOBAL_RAW_WRITER",
        RawClient(),
    )
    dispatcher = GatedStrategyDispatcher(
        safety=SafetySystem(SafetyConfig()),
        request_context_provider=MagicMock(),
        router_provider=MagicMock(),
        adapter_id="openalgo",
        account_id="default",
    )
    strategy = LiveStrategy(
        name="dynamic-global-live",
        execution_contract=StrategyExecutionContract.live(dispatcher),
    )
    strategy._submit = _write_through_dynamic_globals

    with pytest.raises(RuntimeError, match="cannot be safely inspected"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_rejects_live_strategy_with_nested_function_global_writer(monkeypatch) -> None:
    from flinttrade_engine.safety import SafetyConfig, SafetySystem

    class RawClient:
        async def place_order(self, _order: Order) -> None:
            return None

    class LiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.LIVE_GATED})
        uses_managed_order_dispatch = True

    monkeypatch.setitem(
        _write_through_nested_module_global.__globals__,
        "_MODULE_GLOBAL_RAW_WRITER",
        RawClient(),
    )
    dispatcher = GatedStrategyDispatcher(
        safety=SafetySystem(SafetyConfig()),
        request_context_provider=MagicMock(),
        router_provider=MagicMock(),
        adapter_id="openalgo",
        account_id="default",
    )
    strategy = LiveStrategy(
        name="nested-global-live",
        execution_contract=StrategyExecutionContract.live(dispatcher),
    )
    strategy._submit = _write_through_nested_module_global

    with pytest.raises(RuntimeError, match="raw broker mutation handle '_submit'"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_rejects_live_strategy_when_capability_graph_exceeds_bounds() -> None:
    from flinttrade_engine.safety import SafetyConfig, SafetySystem

    class LiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.LIVE_GATED})
        uses_managed_order_dispatch = True

    dispatcher = GatedStrategyDispatcher(
        safety=SafetySystem(SafetyConfig()),
        request_context_provider=MagicMock(),
        router_provider=MagicMock(),
        adapter_id="openalgo",
        account_id="default",
    )
    strategy = LiveStrategy(
        name="bounded-graph-live",
        execution_contract=StrategyExecutionContract.live(dispatcher),
    )
    retained: list[Any] = []
    for _ in range(StrategyExecutionContract._MAX_CAPABILITY_GRAPH_DEPTH + 1):
        retained = [retained]
    strategy._state_cache = retained

    with pytest.raises(RuntimeError, match="cannot be safely inspected"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_accepts_live_strategy_retaining_only_managed_dispatcher() -> None:
    from flinttrade_engine.safety import SafetyConfig, SafetySystem

    class LiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.LIVE_GATED})
        uses_managed_order_dispatch = True

    dispatcher = GatedStrategyDispatcher(
        safety=SafetySystem(SafetyConfig()),
        request_context_provider=MagicMock(),
        router_provider=MagicMock(),
        adapter_id="openalgo",
        account_id="default",
    )
    strategy = LiveStrategy(
        name="managed-live",
        execution_contract=StrategyExecutionContract.live(dispatcher),
    )
    strategy._managed_orders = dispatcher

    runner = StrategyScheduler(client=MagicMock()).register(strategy)

    assert runner.strategy is strategy
    assert runner.execution_contract.dispatcher is dispatcher


def test_scheduler_accepts_only_the_configured_dispatcher_bound_method() -> None:
    class LiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.LIVE_GATED})
        uses_managed_order_dispatch = True

    dispatcher = _live_dispatcher()
    strategy = LiveStrategy(
        name="configured-bound-dispatch",
        execution_contract=StrategyExecutionContract.live(dispatcher),
    )
    strategy._submit = dispatcher.dispatch_order

    assert strategy._submit is not dispatcher.dispatch_order
    runner = StrategyScheduler(client=MagicMock()).register(strategy)

    assert runner.strategy is strategy


def test_scheduler_rejects_same_class_dispatch_method_from_another_dispatcher() -> None:
    class LiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.LIVE_GATED})
        uses_managed_order_dispatch = True

    configured = _live_dispatcher()
    alternate = _live_dispatcher(account_id="alternate")
    strategy = LiveStrategy(
        name="alternate-bound-dispatch",
        execution_contract=StrategyExecutionContract.live(configured),
    )
    strategy._submit = alternate.dispatch_order

    with pytest.raises(RuntimeError, match="raw broker mutation handle"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_rejects_configured_dispatcher_after_class_implementation_changes(
    monkeypatch,
) -> None:
    class LiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.LIVE_GATED})
        uses_managed_order_dispatch = True

    dispatcher = _live_dispatcher()
    strategy = LiveStrategy(
        name="mutated-dispatch-class",
        execution_contract=StrategyExecutionContract.live(dispatcher),
    )

    async def replacement_dispatch_order(_self, _order: Order) -> None:
        return None

    monkeypatch.setattr(GatedStrategyDispatcher, "dispatch_order", replacement_dispatch_order)

    with pytest.raises(RuntimeError, match="raw broker mutation handle"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_rejects_strategy_dispatch_order_override() -> None:
    class LiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.LIVE_GATED})
        uses_managed_order_dispatch = True

        async def dispatch_order(self, _order: Order) -> None:
            return None

    strategy = LiveStrategy(
        name="dispatch-override",
        execution_contract=StrategyExecutionContract.live(_live_dispatcher()),
    )

    with pytest.raises(RuntimeError, match="raw broker mutation handle"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_rejects_same_named_dispatch_function_lookalike() -> None:
    async def dispatch_order(_order: Order) -> None:
        return None

    class LiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.LIVE_GATED})
        uses_managed_order_dispatch = True

    strategy = LiveStrategy(
        name="dispatch-function-lookalike",
        execution_contract=StrategyExecutionContract.live(_live_dispatcher()),
    )
    strategy._submit = dispatch_order

    with pytest.raises(RuntimeError, match="raw broker mutation handle"):
        StrategyScheduler(client=MagicMock()).register(strategy)


@pytest.mark.parametrize("mode", [StrategyExecutionMode.READ_ONLY, StrategyExecutionMode.PRACTICE])
def test_non_live_contracts_reject_nested_raw_mutation_handles(mode: StrategyExecutionMode) -> None:
    class NonLiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({mode})

    contract = (
        StrategyExecutionContract.read_only()
        if mode == StrategyExecutionMode.READ_ONLY
        else StrategyExecutionContract.practice()
    )
    strategy = NonLiveStrategy(name=f"nested-{mode.value}", execution_contract=contract)
    strategy._nested = {"queue": [_RawWriter()]}

    with pytest.raises(RuntimeError, match="raw broker mutation handle '_nested'"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_rejects_raw_mutation_handle_in_top_level_strategy_slot() -> None:
    class SlottedStrategy(_TestStrategy):
        __slots__ = ("_slot_writer",)

    strategy = SlottedStrategy(name="slotted-read-only")
    strategy._slot_writer = _RawWriter()

    with pytest.raises(RuntimeError, match="raw broker mutation handle '_slot_writer'"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_inspects_mixins_after_base_strategy_in_the_full_mro() -> None:
    class TailMixin:
        _mixin_writer = _RawWriter()

    class MixedStrategy(_TestStrategy, TailMixin):
        pass

    assert MixedStrategy.__mro__.index(TailMixin) > MixedStrategy.__mro__.index(BaseStrategy)
    strategy = MixedStrategy(name="tail-mixin")

    with pytest.raises(RuntimeError, match="TailMixin._mixin_writer"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_inspects_attributes_attached_to_configured_dispatcher() -> None:
    class LiveStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.LIVE_GATED})
        uses_managed_order_dispatch = True

    dispatcher = _live_dispatcher()
    dispatcher._review_state = {"nested": [_RawWriter()]}
    strategy = LiveStrategy(
        name="dispatcher-retained-writer",
        execution_contract=StrategyExecutionContract.live(dispatcher),
    )

    with pytest.raises(RuntimeError, match="raw broker mutation handle"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_inspects_referenced_module_attributes(monkeypatch) -> None:
    monkeypatch.setattr(_MODULE_ATTRIBUTE_CONTAINER, "writer", _RawWriter(), raising=False)
    strategy = _TestStrategy(name="module-attribute")
    strategy._submit = _write_through_referenced_module_attribute

    with pytest.raises(RuntimeError, match="raw broker mutation handle '_submit'"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_inspects_weakref_callbacks() -> None:
    class Target:
        pass

    raw_writer = _RawWriter()

    def callback(_reference: weakref.ReferenceType[Target]) -> None:
        raw_writer.place_order

    target = Target()
    strategy = _TestStrategy(name="weakref-callback")
    strategy._target = target
    strategy._reference = weakref.ref(target, callback)

    with pytest.raises(RuntimeError, match="raw broker mutation handle '_reference'"):
        StrategyScheduler(client=MagicMock()).register(strategy)


@pytest.mark.parametrize(
    "wrapped",
    [
        MappingProxyType({"writer": _RawWriter()}),
        deque([_RawWriter()]),
    ],
    ids=["mapping-proxy", "deque"],
)
def test_scheduler_inspects_standard_container_wrappers(wrapped: Any) -> None:
    strategy = _TestStrategy(name="wrapped-read-only")
    strategy._wrapped = wrapped

    with pytest.raises(RuntimeError, match="raw broker mutation handle '_wrapped'"):
        StrategyScheduler(client=MagicMock()).register(strategy)


@pytest.mark.timeout(1)
def test_capability_inspection_bypasses_hostile_strategy_metaclass() -> None:
    metadata_accesses: list[str] = []
    armed = False

    class HostileMeta(type(_TestStrategy)):
        def __getattribute__(cls, name: str) -> Any:
            if armed and name in {"__dict__", "__module__", "__mro__", "__name__", "__qualname__"}:
                metadata_accesses.append(name)
                raise AssertionError(f"strategy metaclass hook invoked for {name}")
            return super().__getattribute__(name)

    class TailMixin:
        writer = _RawWriter()

    class HostileStrategy(_TestStrategy, TailMixin, metaclass=HostileMeta):
        pass

    armed = True
    strategy = HostileStrategy(name="hostile-metaclass")

    with pytest.raises(RuntimeError, match="raw broker mutation handle"):
        StrategyScheduler(client=MagicMock()).register(strategy)
    assert metadata_accesses == []


@pytest.mark.timeout(1)
def test_mapping_proxy_uses_builtin_dict_storage_without_mapping_hooks() -> None:
    mapping_calls: list[str] = []

    class HostileDict(dict[str, Any]):
        def __getitem__(self, key: str) -> Any:
            mapping_calls.append("__getitem__")
            raise AssertionError("mapping __getitem__ hook invoked")

        def __iter__(self):
            mapping_calls.append("__iter__")
            raise AssertionError("mapping __iter__ hook invoked")

        def items(self):
            mapping_calls.append("items")
            raise AssertionError("mapping items hook invoked")

    backing = HostileDict(writer=_RawWriter())
    strategy = _TestStrategy(name="hostile-dict-proxy")
    strategy._wrapped = MappingProxyType(backing)

    with pytest.raises(RuntimeError, match="raw broker mutation handle '_wrapped'"):
        StrategyScheduler(client=MagicMock()).register(strategy)
    assert mapping_calls == []


@pytest.mark.timeout(1)
def test_mapping_proxy_with_non_dict_backing_fails_closed_without_hooks() -> None:
    mapping_calls: list[str] = []

    class HostileMapping(Mapping[str, Any]):
        def __getitem__(self, key: str) -> Any:
            mapping_calls.append("__getitem__")
            raise AssertionError("mapping __getitem__ hook invoked")

        def __iter__(self):
            mapping_calls.append("__iter__")
            raise AssertionError("mapping __iter__ hook invoked")

        def __len__(self) -> int:
            mapping_calls.append("__len__")
            raise AssertionError("mapping __len__ hook invoked")

    strategy = _TestStrategy(name="hostile-mapping-proxy")
    strategy._wrapped = MappingProxyType(HostileMapping())

    with pytest.raises(RuntimeError, match="cannot be safely inspected"):
        StrategyScheduler(client=MagicMock()).register(strategy)
    assert mapping_calls == []


@pytest.mark.timeout(1)
def test_weakref_subclass_uses_base_descriptors_without_calling_override() -> None:
    weakref_calls: list[str] = []

    class HostileReference(weakref.ref[_RawWriter]):
        def __call__(self) -> _RawWriter | None:
            weakref_calls.append("__call__")
            raise AssertionError("weakref __call__ override invoked")

    target = _RawWriter()
    reference = HostileReference(target)
    strategy = _TestStrategy(name="hostile-weakref")
    strategy._reference = reference

    with pytest.raises(RuntimeError, match="raw broker mutation handle '_reference'"):
        StrategyScheduler(client=MagicMock()).register(strategy)
    assert weakref_calls == []


@pytest.mark.timeout(1)
def test_weakref_like_callable_is_inspected_without_invocation() -> None:
    callable_calls: list[str] = []

    class WeakrefLikeCallable:
        def __init__(self) -> None:
            self.writer = _RawWriter()

        def __call__(self) -> None:
            callable_calls.append("__call__")
            raise AssertionError("weakref-like callable invoked")

    strategy = _TestStrategy(name="weakref-like-callable")
    strategy._reference = WeakrefLikeCallable()

    with pytest.raises(RuntimeError, match="raw broker mutation handle '_reference'"):
        StrategyScheduler(client=MagicMock()).register(strategy)
    assert callable_calls == []


def test_scheduler_inspects_state_on_immutable_leaf_subclasses() -> None:
    class RetainedText(str):
        pass

    wrapped = RetainedText("read-only metadata")
    wrapped.writer = _RawWriter()
    strategy = _TestStrategy(name="leaf-subclass")
    strategy._wrapped = wrapped

    with pytest.raises(RuntimeError, match="raw broker mutation handle '_wrapped'"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_scheduler_does_not_trust_spoofed_standard_library_module_names() -> None:
    class SpoofedWrapper:
        writer = _RawWriter()

    SpoofedWrapper.__module__ = "collections"
    strategy = _TestStrategy(name="spoofed-module")
    strategy._wrapped = SpoofedWrapper()

    with pytest.raises(RuntimeError, match="raw broker mutation handle '_wrapped'"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_read_only_capability_graph_bounds_fail_closed() -> None:
    strategy = _TestStrategy(name="bounded-read-only")
    retained: list[Any] = []
    for _ in range(StrategyExecutionContract._MAX_CAPABILITY_GRAPH_DEPTH + 1):
        retained = [retained]
    strategy._state_cache = retained

    with pytest.raises(RuntimeError, match="cannot be safely inspected"):
        StrategyScheduler(client=MagicMock()).register(strategy)


def test_practice_capability_graph_node_bound_fails_closed() -> None:
    class PracticeStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.PRACTICE})

    strategy = PracticeStrategy(
        name="wide-practice-graph",
        execution_contract=StrategyExecutionContract.practice(),
    )
    strategy._state_cache = [
        object() for _ in range(StrategyExecutionContract._MAX_CAPABILITY_GRAPH_NODES + 1)
    ]

    with pytest.raises(RuntimeError, match="node limit exceeded"):
        StrategyScheduler(client=MagicMock()).register(strategy)


@pytest.mark.asyncio
async def test_runner_revalidates_execution_contract_immediately_before_start() -> None:
    class RawClient:
        async def place_order(self, _order: Order) -> None:
            return None

    strategy = _TestStrategy(name="contract-drift")
    runner = StrategyScheduler(client=MagicMock()).register(strategy)
    strategy._client = RawClient()

    with pytest.raises(RuntimeError, match="raw broker mutation handle"):
        await runner.start()
    assert strategy.state.value == "STOPPED"
    assert runner.has_live_owner is False


@pytest.mark.asyncio
async def test_practice_contract_stays_distinct_and_has_no_live_dispatcher() -> None:
    class PracticeStrategy(_TestStrategy):
        supported_execution_modes = frozenset({StrategyExecutionMode.PRACTICE})

    strategy = PracticeStrategy(
        name="practice-only",
        execution_contract=StrategyExecutionContract.practice(),
    )
    scheduler = StrategyScheduler(client=MagicMock())
    runner = scheduler.register(strategy)
    runner.scheduler = _open_time_scheduler()
    runner.client.quotes = AsyncMock(return_value=None)

    await runner.start()
    try:
        with pytest.raises(RuntimeError, match="cannot mutate a broker"):
            await strategy.dispatch_order(Order(symbol="RELIANCE", action="BUY"))
    finally:
        await runner.stop()
