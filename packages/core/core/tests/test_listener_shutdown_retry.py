"""Normal listener cleanup resumes its exact owner after an earlier timeout.

Each ordering control runs the complete public-master timeout/retry caller with
its real factory, listener, schedulers, lease, refusal and release assertions.
Events constrain only the publication order of a real completed stop callback.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
import threading

import pytest

from packages.core.core.tests import test_normal_runtime_smoke as normal

pytestmark = pytest.mark.integration

offline_startup = normal.offline_startup


@pytest.mark.asyncio
@pytest.mark.parametrize("publication", ["before_retry", "during_retry"])
async def test_normal_listener_retry_resumes_an_incomplete_retained_callback(
    monkeypatch: pytest.MonkeyPatch,
    offline_startup: dict[str, Any],
    publication: str,
) -> None:
    """A previous callback's real False is not a fresh attempt's timeout."""
    import flinttrade_core.app as app_module
    import waitress.wasyncore as asyncore

    finish_poll = threading.Event()
    incomplete = threading.Event()
    publish_result = threading.Event()
    resumes: list[dict[str, Any]] = []
    closes: list[Any] = []
    dispatchers: list[Any] = []
    retained: list[Any] = []
    calls: list[dict[str, Any]] = []
    real_stop = app_module._FlaskServerOwner.stop
    real_runtime_stop = app_module.FlintTradeApp.stop
    real_retained = app_module.FlintTradeApp._run_retained_sync_owner
    real_server = app_module._run_flask_server

    def hold_poll_completion(poll: Callable[..., Any]) -> Callable[..., Any]:
        def observed_poll(*args: Any, **kwargs: Any) -> Any:
            result = poll(*args, **kwargs)
            socket_map = kwargs.get("map", args[1] if len(args) > 1 else None)
            if threading.current_thread().name == "flinttrade-api" and not socket_map:
                assert finish_poll.wait(30), "The test did not release its actual listener loop"
            return result

        return observed_poll

    def observe_server(*args: Any, **kwargs: Any) -> Any:
        owner = real_server(*args, **kwargs)
        assert type(owner._server).__module__.startswith("waitress.")
        assert owner._server._map is not asyncore.socket_map
        close = owner._close
        dispatcher_shutdown = owner._dispatcher.shutdown

        def observe_close() -> Any:
            closes.append(owner)
            return close()

        def observe_dispatcher(*args: Any, **kwargs: Any) -> Any:
            dispatchers.append(owner)
            return dispatcher_shutdown(*args, **kwargs)

        monkeypatch.setattr(owner, "_close", observe_close)
        monkeypatch.setattr(owner._dispatcher, "shutdown", observe_dispatcher)
        return owner

    def stop_listener(owner: Any, *, timeout: float) -> bool:
        call = {"owner": owner, "timeout": timeout}
        calls.append(call)
        result = real_stop(owner, timeout=timeout)
        call["result"] = result
        if len(calls) == 1:
            assert result is False
            assert owner._close_complete is True
            assert owner.thread.is_alive()
            assert owner._run_error is None
            incomplete.set()
            assert publish_result.wait(30), "The test did not publish its real incomplete callback"
        return result

    async def stop_runtime(runtime: Any, *, timeout: float | None = None) -> None:
        if timeout == 30 and not resumes:
            assert await asyncio.to_thread(incomplete.wait, 5)
            worker = runtime._shutdown_sync_workers["flask-listener"]
            assert not worker._done.is_set()
            assert worker._thread.is_alive()
            assert runtime._flask_server_owner is calls[0]["owner"]
            retained.append(worker)
            resumes.append({"publication": publication, "worker": worker})
            if publication == "before_retry":
                publish_result.set()
                assert await asyncio.to_thread(worker._done.wait, 5)
                assert worker.outcome() == (False, None)
            finish_poll.set()
        await real_runtime_stop(runtime, timeout=timeout)

    async def observe_retained(runtime: Any, key: str, operation: Any, deadline: Any, **kwargs: Any) -> Any:
        if key == "flask-listener" and retained and runtime._shutdown_sync_workers.get(key) is retained[0]:
            assert deadline.remaining() > 0
            assert len(calls) == 1, "A live earlier callback must not be duplicated"
            if publication == "during_retry":
                assert not retained[0]._done.is_set()
                publish_result.set()
        return await real_retained(runtime, key, operation, deadline, **kwargs)

    monkeypatch.setattr(asyncore, "poll", hold_poll_completion(asyncore.poll))
    monkeypatch.setattr(asyncore, "poll2", hold_poll_completion(asyncore.poll2))
    monkeypatch.setattr(app_module, "_run_flask_server", observe_server)
    monkeypatch.setattr(app_module._FlaskServerOwner, "stop", stop_listener)
    monkeypatch.setattr(app_module.FlintTradeApp, "stop", stop_runtime)
    monkeypatch.setattr(app_module.FlintTradeApp, "_run_retained_sync_owner", observe_retained)
    try:
        await normal.test_normal_stop_retains_a_blocked_public_master_owner_until_retry(monkeypatch, offline_startup)
        assert len(calls) == 2
        assert calls[0]["owner"] is calls[1]["owner"]
        assert 0.0 <= calls[0]["timeout"] <= 0.05
        assert 0.0 < calls[1]["timeout"] <= 30.0
        assert [call["result"] for call in calls] == [False, True]
        assert closes == [calls[0]["owner"]]
        assert dispatchers == [calls[0]["owner"]]
        assert retained[0].outcome() == (False, None)
    finally:
        finish_poll.set()
        publish_result.set()


@pytest.mark.asyncio
async def test_normal_listener_successful_callback_is_shared_with_a_shorter_caller(
    monkeypatch: pytest.MonkeyPatch,
    offline_startup: dict[str, Any],
) -> None:
    """A live successful cleanup is retained, not duplicated or cancelled."""
    import flinttrade_core.app as app_module
    from flinttrade_core.backend_instance import BackendInstanceAlreadyRunning, acquire_backend_instance_lease

    completed = threading.Event()
    publish = threading.Event()
    runtimes: list[Any] = []
    listeners: list[Any] = []
    real_stop = app_module._FlaskServerOwner.stop
    real_runtime_stop = app_module.FlintTradeApp.stop

    def stop_listener(owner: Any, *, timeout: float) -> bool:
        listeners.append(owner)
        result = real_stop(owner, timeout=timeout)
        assert result is True
        completed.set()
        assert publish.wait(30), "The test did not publish its actual completed listener cleanup"
        return result

    async def observe_runtime(runtime: Any, *, timeout: float | None = None) -> None:
        runtimes.append(runtime)
        await real_runtime_stop(runtime, timeout=timeout)

    monkeypatch.setattr(app_module._FlaskServerOwner, "stop", stop_listener)
    monkeypatch.setattr(app_module.FlintTradeApp, "stop", observe_runtime)
    normal_control = asyncio.create_task(
        normal.test_normal_factory_runtime_readiness_refusal_and_clean_stop(monkeypatch, offline_startup)
    )
    try:
        assert await asyncio.to_thread(completed.wait, 5)
        runtime = runtimes[0]
        listener = listeners[0]
        worker = runtime._shutdown_sync_workers["flask-listener"]
        attempt = runtime._shutdown_task
        assert worker._thread.is_alive() and not worker._done.is_set()
        assert not listener.thread.is_alive() and listener._dispatcher.threads == set()
        with pytest.raises(RuntimeError, match="shutdown exceeded its absolute deadline"):
            await runtime.stop(timeout=0.05)
        assert runtime._shutdown_sync_workers["flask-listener"] is worker
        assert runtime._shutdown_task is attempt and not attempt.cancelled()
        assert runtime._flask_server_owner is listener
        assert runtime._stop_completed is False
        assert len(listeners) == 1
        with pytest.raises(BackendInstanceAlreadyRunning):
            acquire_backend_instance_lease()
        assert runtime._flask_app.test_client().get("/api/v1/ping").status_code == 503
        publish.set()
        await normal_control
        assert listeners == [listener]
    finally:
        publish.set()
        await asyncio.gather(normal_control, return_exceptions=True)


@pytest.mark.asyncio
async def test_normal_listener_resume_still_refuses_a_fresh_incomplete_stop(
    monkeypatch: pytest.MonkeyPatch,
    offline_startup: dict[str, Any],
) -> None:
    """Resuming a previous False cannot turn a current False into success."""
    import flinttrade_core.app as app_module
    import waitress.wasyncore as asyncore
    from flinttrade_core.backend_instance import BackendInstanceAlreadyRunning, acquire_backend_instance_lease

    finish_poll = threading.Event()
    incomplete = threading.Event()
    publish_first = threading.Event()
    results: list[bool] = []
    timeouts: list[float] = []
    real_stop = app_module._FlaskServerOwner.stop

    def hold_poll_completion(poll: Callable[..., Any]) -> Callable[..., Any]:
        def observed_poll(*args: Any, **kwargs: Any) -> Any:
            result = poll(*args, **kwargs)
            socket_map = kwargs.get("map", args[1] if len(args) > 1 else None)
            if threading.current_thread().name == "flinttrade-api" and not socket_map:
                assert finish_poll.wait(30), "The test did not release its actual listener loop"
            return result

        return observed_poll

    def stop_listener(owner: Any, *, timeout: float) -> bool:
        timeouts.append(timeout)
        result = real_stop(owner, timeout=timeout)
        results.append(result)
        if len(results) == 1:
            assert result is False
            incomplete.set()
            assert publish_first.wait(30), "The test did not publish its real incomplete callback"
        return result

    monkeypatch.setattr(asyncore, "poll", hold_poll_completion(asyncore.poll))
    monkeypatch.setattr(asyncore, "poll2", hold_poll_completion(asyncore.poll2))
    monkeypatch.setattr(app_module._FlaskServerOwner, "stop", stop_listener)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    baseline = set(threading.enumerate())
    runtime = app_module.FlintTradeApp()
    reached = asyncio.Event()
    real_wait = runtime._wait_for_shutdown_result

    async def observe_startup() -> None:
        reached.set()
        await real_wait()

    monkeypatch.setattr(runtime, "_wait_for_shutdown_result", observe_startup)
    lease = acquire_backend_instance_lease()
    runtime._backend_lease_proof = lease.proof
    start = asyncio.create_task(runtime.start())
    try:
        await normal._wait_started(start, reached)
        listener = runtime._flask_server_owner
        flask_app = runtime._flask_app
        assert listener is not None and flask_app is not None
        assert type(listener._server).__module__.startswith("waitress.")
        ping = await asyncio.to_thread(normal._request, offline_startup["port"], "GET", "/api/v1/ping")
        assert ping["status"] == 200 and ping["body"]["laya_live_qualified"] is False
        threads = normal._owned_threads(baseline)
        with pytest.raises(RuntimeError, match="shutdown encountered errors"):
            await runtime.stop(timeout=0.05)
        with pytest.raises(RuntimeError, match="shutdown encountered errors"):
            await asyncio.wait_for(start, timeout=5)
        assert await asyncio.to_thread(incomplete.wait, 5)
        for key, worker in tuple(runtime._shutdown_sync_workers.items()):
            if key != "flask-listener":
                assert await asyncio.to_thread(worker._done.wait, 5)
        publish_first.set()
        with pytest.raises(RuntimeError, match="Flask API listener \\(TimeoutError\\)"):
            await runtime.stop(timeout=0.05)
        assert runtime._stop_completed is False
        assert runtime._flask_server_owner is listener
        assert listener.thread.is_alive()
        assert flask_app.config["RUNTIME_ACCEPTING_REQUESTS"] is False
        assert flask_app.test_client().get("/api/v1/ping").status_code == 503
        with pytest.raises(BackendInstanceAlreadyRunning):
            acquire_backend_instance_lease()
        finish_poll.set()
        await runtime.stop(timeout=30)
        await normal._assert_released(runtime, listener, lease, threads, offline_startup["port"])
        assert results == [False, False, True]
        assert all(0.0 <= value <= 0.05 for value in timeouts[:2])
        assert 0.0 < timeouts[2] <= 30.0
        assert offline_startup["unexpected"] == []
    finally:
        finish_poll.set()
        publish_first.set()
        if not runtime._stop_completed:
            await runtime.stop(timeout=30)
        await asyncio.gather(start, return_exceptions=True)
        lease.release()
