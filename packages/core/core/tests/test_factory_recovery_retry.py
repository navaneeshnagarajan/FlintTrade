"""Factory cleanup retries retain the exact bounded operation and its custody."""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from packages.core.core.tests import test_factory_ownership as factory

pytestmark = pytest.mark.integration
fresh_lease = factory.fresh_lease
inert_external_downloads = factory.inert_external_downloads


@pytest.mark.asyncio
@pytest.mark.parametrize("publication", ["before_retry", "during_retry"])
async def test_factory_cleanup_retry_resumes_real_late_incomplete(
    fresh_lease, monkeypatch, publication,
):
    """Delay only publication of the real typed refusal, not its deadline."""
    from flinttrade_core import app as core, desktop

    refused, publish = threading.Event(), threading.Event()
    calls, runtimes, workers, deadlines, trace = [], [], [], [], []
    release = desktop._DesktopShutdownRecoveryOwner.release
    rollback = core.FlintTradeApp._rollback_startup_dependencies
    stop = core.FlintTradeApp.stop
    wait = core._RetainedSyncOwnerWorker.wait
    rejoining = False
    cleaning = False

    def note(kind, **fields):
        trace.append(dict(kind=kind, at=time.monotonic(), thread=threading.get_ident(),
                          native_thread=threading.get_native_id(), **fields))

    def observed_release(owner, *, deadline):
        calls.append((owner, deadline))
        note("release", owner=id(owner), deadline=deadline)
        if len(calls) == 3 and not cleaning:
            assert owner is calls[0][0] is runtimes[0]._factory_recovery
            assert workers[0]._done.is_set() and not workers[0]._thread.is_alive()
            assert deadline == deadlines[1].expires_at > deadlines[0].expires_at
            assert deadlines[1].remaining() > 0
            assert not runtimes[0].client._closed
            assert runtimes[0].audit._current_file is not None
            note("fresh_same_owner", owner=id(owner), worker=id(workers[0]),
                 deadline=deadline, old_worker_alive=workers[0]._thread.is_alive())
        try:
            return release(owner, deadline=deadline)
        except desktop.DesktopBackendShutdownIncomplete as error:
            assert error.recovery_owner is owner
            if len(calls) == 2 and not cleaning:
                assert deadline <= time.monotonic(), "the real release did not exhaust its budget"
                note("actual_refusal", owner=id(owner), error=id(error), deadline=deadline)
                refused.set()
                assert publish.wait(15), "test did not publish its real factory refusal"
                note("publish_refusal", owner=id(owner), error=id(error))
            raise

    async def observed_rollback(runtime, deadline):
        if not runtimes:
            runtimes.append(runtime)
        if not cleaning:
            deadlines.append(deadline)
        return await rollback(runtime, deadline)

    async def observed_stop(runtime, *, timeout=None):
        nonlocal rejoining
        if not cleaning and not rejoining:
            rejoining = True
            assert await asyncio.to_thread(refused.wait, 5)
            worker = runtime._shutdown_sync_workers["factory-recovery"]
            workers.append(worker)
            assert worker._thread.is_alive() and not worker._done.is_set()
            assert runtime._factory_recovery is calls[0][0]
            assert not runtime.client._closed and runtime.audit._current_file is not None
            if publication == "before_retry":
                publish.set()
                await asyncio.to_thread(worker._thread.join, 5)
                assert not worker._thread.is_alive()
                note("published_before_retry", worker=id(worker))
        return await stop(runtime, timeout=timeout)

    async def observed_wait(worker, deadline):
        if not cleaning and workers and worker is workers[0]:
            note("rejoin_wait", worker=id(worker), deadline=deadline.expires_at)
            if publication == "during_retry":
                assert worker._thread.is_alive() and not worker._done.is_set()
                assert len(calls) == 2
                publish.set()
            result = await wait(worker, deadline)
            assert result and worker._done.is_set()
            note("rejoin_complete", worker=id(worker), deadline=deadline.expires_at)
            return result
        return await wait(worker, deadline)

    monkeypatch.setattr(desktop._DesktopShutdownRecoveryOwner, "release", observed_release)
    monkeypatch.setattr(core.FlintTradeApp, "_rollback_startup_dependencies", observed_rollback)
    monkeypatch.setattr(core.FlintTradeApp, "stop", observed_stop)
    monkeypatch.setattr(core._RetainedSyncOwnerWorker, "wait", observed_wait)
    try:
        # Reuse every original factory, held DataRuntime, budget and root oracle.
        await factory.test_async_prefactory_failure_retains_partial_app_before_borrowed_root_close(
            fresh_lease, monkeypatch,
        )
        assert len(calls) == 3, "stop must rejoin, then make one fresh same-owner release"
        assert calls[0][0] is calls[1][0] is calls[2][0]
        assert calls[0][0]._released
        assert runtimes[0]._factory_recovery is None
        assert [entry["kind"] for entry in trace].index("rejoin_complete") < [entry["kind"] for entry in trace].index("fresh_same_owner")
    finally:
        cleaning = True
        publish.set()
        # Clean RED as well as GREEN, using only workers/owners acquired here.
        for worker in workers:
            await asyncio.to_thread(worker._thread.join, 5)
            assert not worker._thread.is_alive()
        if calls:
            # Even a dispatch-bypass regression must retire the real factory,
            # not trust the runtime's possibly premature completion flag.
            await asyncio.to_thread(release, calls[0][0], deadline=time.monotonic() + 8)
        if runtimes:
            await stop(runtimes[0], timeout=8)
            assert runtimes[0]._stop_completed and runtimes[0].client._closed
        if calls:
            owner = calls[0][0]
            assert owner._released
            for worker in owner._workers.values():
                await asyncio.to_thread(worker._thread.join, 5)
                assert not worker._thread.is_alive()
            note("owned_cleanup_complete", owner=id(owner))


@pytest.mark.asyncio
@pytest.mark.parametrize("previous", [False, True], ids=["current", "previous"])
@pytest.mark.parametrize("outcome", ["incomplete", "error", "foreign", "absent", "success"])
async def test_factory_cleanup_result_policy(monkeypatch, previous, outcome):
    """Only an old same-owner refusal gets one continuation; errors do not."""
    from types import SimpleNamespace
    from flinttrade_core import app as core, desktop

    publish = threading.Event()
    calls, closed = [], []

    class Recovery:
        def release(self, *, deadline):
            calls.append((threading.current_thread(), deadline))
            assert publish.wait(5)
            if outcome == "incomplete":
                raise desktop.DesktopBackendShutdownIncomplete("bounded refusal", recovery_owner=self)
            if outcome == "error":
                raise ValueError("cleanup failed")
            if outcome == "foreign":
                raise desktop.DesktopBackendShutdownIncomplete("foreign refusal", recovery_owner=object())
            if outcome == "absent":
                raise desktop.DesktopBackendShutdownIncomplete("unbound refusal")

    async def close_client():
        closed.append("client")

    # No extra lifecycle or real resources: exercise the actual factory boundary.
    owner = Recovery()
    runtime = core.FlintTradeApp.__new__(core.FlintTradeApp)
    runtime._factory_recovery = owner
    runtime._flask_app = None
    runtime.scheduler = None
    runtime.client = SimpleNamespace(close=close_client)
    runtime.audit = SimpleNamespace(close=lambda: closed.append("audit"))
    runtime._stop_event = asyncio.Event()
    first = core._LifecycleDeadline.after(0.05 if previous else 2)
    try:
        if previous:
            assert not await runtime._rollback_startup_dependencies(first)
            worker = runtime._shutdown_sync_workers["factory-recovery"]
            assert worker._thread.is_alive() and runtime._factory_recovery is owner
            assert closed == []
            publish.set()
            await asyncio.to_thread(worker._thread.join, 5)
            assert not worker._thread.is_alive()
            deadline = core._LifecycleDeadline.after(2)
        else:
            publish.set()
            deadline = first
        result = await runtime._rollback_startup_dependencies(deadline)
        assert result is (outcome == "success")
        assert len(calls) == (2 if previous and outcome == "incomplete" else 1)
        if previous and outcome == "incomplete":
            assert calls[1][1] == deadline.expires_at > first.expires_at
        if outcome != "success":
            assert runtime._factory_recovery is owner and closed == []
        else:
            assert runtime._factory_recovery is None and closed == ["client", "audit"]
    finally:
        publish.set()
        for thread, _ in calls:
            await asyncio.to_thread(thread.join, 5)
            assert not thread.is_alive()
        for worker in runtime._shutdown_sync_workers.values():
            await asyncio.to_thread(worker._thread.join, 5)
            assert not worker._thread.is_alive()


@pytest.mark.asyncio
@pytest.mark.parametrize("old_incomplete", [False, True], ids=["reuse_success", "resume_incomplete"])
async def test_factory_cleanup_live_worker_survives_shorter_concurrent_stop(monkeypatch, old_incomplete):
    """A shorter caller cannot cancel custody or multiply a live operation."""
    from flinttrade_core import app as core, desktop
    from packages.core.core.tests.test_runtime_lifecycle import _runtime_app

    runtime = _runtime_app()
    runtime._startup_recovery_pending = True
    publish = threading.Event()
    rejoining = asyncio.Event()
    calls = []
    worker = None
    retry = None

    class Recovery:
        def release(self, *, deadline):
            calls.append((threading.current_thread(), deadline))
            assert publish.wait(5)
            if old_incomplete and len(calls) == 1:
                raise desktop.DesktopBackendShutdownIncomplete("bounded refusal", recovery_owner=self)

    owner = Recovery()
    runtime._factory_recovery = owner
    wait = core._RetainedSyncOwnerWorker.wait

    async def observed_wait(current, deadline):
        if current is worker:
            rejoining.set()
        return await wait(current, deadline)

    monkeypatch.setattr(core._RetainedSyncOwnerWorker, "wait", observed_wait)
    try:
        with pytest.raises(RuntimeError, match="startup rollback incomplete"):
            await runtime.stop(timeout=0.05)
        worker = runtime._shutdown_sync_workers["factory-recovery"]
        assert worker._thread.is_alive() and len(calls) == 1
        retry = asyncio.create_task(runtime.stop(timeout=3))
        await asyncio.wait_for(rejoining.wait(), 1)
        attempt = runtime._shutdown_task
        with pytest.raises(RuntimeError, match="shutdown exceeded its absolute deadline"):
            await runtime.stop(timeout=0.01)
        assert runtime._shutdown_task is attempt and not attempt.cancelled()
        assert runtime._shutdown_sync_workers["factory-recovery"] is worker
        assert runtime._factory_recovery is owner and len(calls) == 1
        runtime.client.close.assert_not_awaited()
        runtime.audit.close.assert_not_called()
        publish.set()
        await retry
        assert len(calls) == (2 if old_incomplete else 1)
        assert runtime._factory_recovery is None and runtime._stop_completed
        runtime.client.close.assert_awaited_once()
        runtime.audit.close.assert_called_once()
    finally:
        publish.set()
        if retry is not None:
            await asyncio.gather(retry, return_exceptions=True)
        await runtime.stop(timeout=8)
        for thread, _ in calls:
            await asyncio.to_thread(thread.join, 5)
            assert not thread.is_alive()


@pytest.mark.asyncio
async def test_factory_cleanup_does_not_clear_replaced_custody(monkeypatch):
    """An observed success cannot clear a different owner or close its roots."""
    from flinttrade_core import app as core
    from packages.core.core.tests.test_runtime_lifecycle import _runtime_app

    runtime = _runtime_app()
    replacement = object()
    calls = []

    class Recovery:
        def release(self, *, deadline):
            calls.append(threading.current_thread())
            runtime._factory_recovery = replacement

    owner = Recovery()
    runtime._factory_recovery = owner
    try:
        assert not await runtime._rollback_startup_dependencies(core._LifecycleDeadline.after(2))
        assert runtime._factory_recovery is replacement
        runtime.client.close.assert_not_awaited()
        runtime.audit.close.assert_not_called()
    finally:
        for thread in calls:
            await asyncio.to_thread(thread.join, 5)
            assert not thread.is_alive()
        # Restore and retire only this control's exact synthetic owner.
        runtime._factory_recovery = owner
        monkeypatch.setattr(owner, "release", lambda *, deadline: None)
        assert await runtime._rollback_startup_dependencies(core._LifecycleDeadline.after(8))
        await runtime.stop(timeout=8)


@pytest.mark.asyncio
@pytest.mark.parametrize("old_incomplete", [False, True], ids=["success", "incomplete"])
@pytest.mark.parametrize("replacement_kind", ["foreign", "absent"])
async def test_factory_cleanup_rejects_between_attempt_owner_substitution(old_incomplete, replacement_kind):
    """An earlier owner's outcome cannot authorise a different custody slot."""
    from flinttrade_core import app as core, desktop
    from packages.core.core.tests.test_runtime_lifecycle import _runtime_app

    runtime = _runtime_app()
    publish = threading.Event()
    calls = []

    class Recovery:
        def release(self, *, deadline):
            calls.append((self, threading.current_thread(), deadline))
            assert publish.wait(5)
            if self is original and old_incomplete and len(calls) == 1:
                raise desktop.DesktopBackendShutdownIncomplete("bounded refusal", recovery_owner=self)

    original = Recovery()
    replacement = Recovery() if replacement_kind == "foreign" else None
    runtime._factory_recovery = original
    first = core._LifecycleDeadline.after(0.05)
    try:
        assert not await runtime._rollback_startup_dependencies(first)
        worker = runtime._shutdown_sync_workers["factory-recovery"]
        assert worker._thread.is_alive() and len(calls) == 1
        runtime._factory_recovery = replacement
        publish.set()
        await asyncio.to_thread(worker._thread.join, 5)
        assert not worker._thread.is_alive()

        assert not await runtime._rollback_startup_dependencies(core._LifecycleDeadline.after(2)), "retained result accepted substituted factory custody"
        assert runtime._factory_recovery is replacement
        assert runtime._shutdown_sync_workers["factory-recovery"] is worker
        assert [owner for owner, _, _ in calls] == [original]
        runtime.client.close.assert_not_awaited()
        runtime.audit.close.assert_not_called()

        # Restoring the exact owner permits the already-defined continuation.
        runtime._factory_recovery = original
        retry = core._LifecycleDeadline.after(2)
        assert await runtime._rollback_startup_dependencies(retry)
        assert len(calls) == (2 if old_incomplete else 1)
        assert all(owner is original for owner, _, _ in calls)
        if old_incomplete:
            assert calls[-1][2] == retry.expires_at > first.expires_at
        assert runtime._factory_recovery is None
        assert runtime._retained_factory_recovery is None
        runtime.client.close.assert_awaited_once()
        runtime.audit.close.assert_called_once()
    finally:
        publish.set()
        for _, thread, _ in calls:
            await asyncio.to_thread(thread.join, 5)
            assert not thread.is_alive()
        runtime._factory_recovery = original
        assert await runtime._rollback_startup_dependencies(core._LifecycleDeadline.after(8))
        for _, thread, _ in calls:
            await asyncio.to_thread(thread.join, 5)
            assert not thread.is_alive()
