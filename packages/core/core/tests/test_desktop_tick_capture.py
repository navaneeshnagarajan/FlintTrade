"""Desktop sidecar tick-capture lifecycle tests.

These tests keep the synchronous Waitress boundary and asynchronous recorder
loop honest without opening a real WebSocket or DuckDB database.
"""

from __future__ import annotations

import asyncio
import builtins
import logging
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest
from flask import Flask

from flinttrade_core import desktop
from flinttrade_data.storage import TickReplayCursor


_CAPTURE_CONFIG_KEYS = {
    "ORDERFLOW_AGGREGATOR",
    "TICK_RECORDER",
    "TICK_STORAGE",
    "TICK_STORAGE_LOCK",
}


@pytest.fixture(autouse=True)
def _isolate_backend_instance_lock(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Model each serve test as a fresh process with its own workspace lock."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))


class _FakeStorage:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.initialised = False
        self.closed = False
        self.pruned_days: list[int] = []
        self.tick_queries: list[tuple[object, ...]] = []
        self.tick_rows: list[dict[str, object]] = []
        self.replay_cursor = TickReplayCursor(
            store_id="12345678-1234-5678-1234-567812345678",
            ingest_seq=0,
        )

    def initialise(self) -> None:
        self.initialised = True

    def close(self) -> None:
        self.closed = True

    def prune_ticks(self, days: int) -> int:
        self.pruned_days.append(days)
        return 0

    def get_ticks(self, *args: object, **kwargs: object) -> list[dict[str, object]]:
        self.tick_queries.append((*args, kwargs))
        return list(self.tick_rows)

    def get_tick_replay_cursor(self) -> TickReplayCursor:
        return self.replay_cursor

    def get_ticks_after_cursor(
        self,
        cursor: TickReplayCursor,
        symbol: str,
        exchange: str,
        session: str,
        *,
        limit: int,
    ) -> list[dict[str, object]]:
        self.tick_queries.append((cursor, symbol, exchange, session, {"limit": limit}))
        return list(self.tick_rows)


class _RetentionStorage(_FakeStorage):
    def __init__(self, db_path: str) -> None:
        super().__init__(db_path)
        self.retention_ran = threading.Event()

    def prune_ticks(self, days: int) -> int:
        result = super().prune_ticks(days)
        self.retention_ran.set()
        return result


class _BlockingRetentionStorage(_FakeStorage):
    def __init__(self, db_path: str) -> None:
        super().__init__(db_path)
        self.prune_started = threading.Event()
        self.release_prune = threading.Event()
        self.prune_finished = threading.Event()
        self.close_calls = 0
        self.closed_while_pruning = False
        self._pruning_lock = threading.Lock()
        self._pruning = False

    def prune_ticks(self, days: int) -> int:
        self.pruned_days.append(days)
        with self._pruning_lock:
            self._pruning = True
        self.prune_started.set()
        try:
            self.release_prune.wait()
            return 0
        finally:
            with self._pruning_lock:
                self._pruning = False
            self.prune_finished.set()

    def close(self) -> None:
        self.close_calls += 1
        with self._pruning_lock:
            self.closed_while_pruning = self.closed_while_pruning or self._pruning
        super().close()


class _RetryingCloseStorage(_FakeStorage):
    def __init__(self, db_path: str, failures: int) -> None:
        super().__init__(db_path)
        self.failures = failures
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1
        if self.close_calls <= self.failures:
            raise RuntimeError("transient close failure")
        super().close()


class _BlockingCloseStorage(_FakeStorage):
    def __init__(self, db_path: str) -> None:
        super().__init__(db_path)
        self.close_started = threading.Event()
        self.release_close = threading.Event()

    def close(self) -> None:
        self.close_started.set()
        self.release_close.wait(timeout=1)
        super().close()


class _FakeRecorder:
    def __init__(self) -> None:
        self.run_started = threading.Event()
        self.run_finished = threading.Event()
        self.stop_calls = 0
        self.pending_tick_count = 0

    async def run(self) -> None:
        self.run_started.set()
        try:
            await asyncio.Future()
        finally:
            self.run_finished.set()

    def stop(self) -> None:
        self.stop_calls += 1


class _SlowCleanupRecorder(_FakeRecorder):
    def __init__(self) -> None:
        super().__init__()
        self.cancel_seen = threading.Event()
        self.release_cleanup = threading.Event()

    async def run(self) -> None:
        self.run_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancel_seen.set()
            while not self.release_cleanup.is_set():
                await asyncio.sleep(0.005)
        finally:
            self.run_finished.set()


class _UnexpectedFailureRecorder(_FakeRecorder):
    def __init__(self, api_key: str) -> None:
        super().__init__()
        self.release_failure = threading.Event()
        self.api_key = api_key

    async def run(self) -> None:
        self.run_started.set()
        while not self.release_failure.is_set():
            await asyncio.sleep(0.005)
        raise RuntimeError(f"recorder stopped with {self.api_key}")


class _FlushFailureRecorder(_FakeRecorder):
    def __init__(self, api_key: str) -> None:
        super().__init__()
        self.api_key = api_key

    async def run(self) -> None:
        self.run_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            raise RuntimeError(f"final flush rejected {self.api_key}") from None
        finally:
            self.run_finished.set()


class _TransientFlushFailureRecorder(_FakeRecorder):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events
        self.pending_tick_count = 1
        self.flush_calls = 0

    async def run(self) -> None:
        self.run_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.events.append("final-flush-failed")
            raise RuntimeError("transient final flush failure") from None
        finally:
            self.run_finished.set()

    def flush_pending(self) -> bool:
        self.flush_calls += 1
        self.events.append("flush-retry")
        self.pending_tick_count = 0
        return True


class _RetainedFlushFailureRecorder(_TransientFlushFailureRecorder):
    def __init__(self, events: list[str]) -> None:
        super().__init__(events)
        self.allow_flush = False

    def flush_pending(self) -> bool:
        self.flush_calls += 1
        self.events.append("flush-retry")
        if not self.allow_flush:
            raise RuntimeError("retained flush is still unavailable")
        self.pending_tick_count = 0
        return True


class _BoundedRetryFlushRecorder(_TransientFlushFailureRecorder):
    def __init__(self, events: list[str], *, failures: int) -> None:
        super().__init__(events)
        self.failures = failures

    def flush_pending(self) -> bool:
        self.flush_calls += 1
        self.events.append("flush-retry")
        if self.flush_calls <= self.failures:
            raise RuntimeError("transient retained flush failure")
        self.pending_tick_count = 0
        return True


@pytest.mark.unit
def test_runtime_redacts_original_and_hot_reloaded_api_keys() -> None:
    runtime = desktop._DesktopTickCaptureRuntime(
        _FakeRecorder(),
        _FakeStorage("unused"),
        "old-secret",
    )
    runtime.update_api_key("new-secret")

    diagnostic = runtime.sanitise_error("old-secret then new-secret")

    assert diagnostic == "[redacted] then [redacted]"


@pytest.mark.unit
def test_runtime_prunes_retained_ticks_periodically_during_long_uptime() -> None:
    recorder = _FakeRecorder()
    storage = _RetentionStorage("unused")
    runtime = desktop._DesktopTickCaptureRuntime(
        recorder,
        storage,
        "",
        retention_days=90,
        retention_interval_seconds=0.01,
    )

    runtime.start()
    try:
        assert storage.retention_ran.wait(timeout=1)
        assert storage.pruned_days
        assert set(storage.pruned_days) == {90}
    finally:
        runtime.stop(timeout=1)


@pytest.mark.unit
def test_blocking_retention_prune_does_not_pin_recorder_loop_or_close_storage() -> None:
    recorder = _FakeRecorder()
    storage = _BlockingRetentionStorage("unused")
    runtime = desktop._DesktopTickCaptureRuntime(
        recorder,
        storage,
        "",
        retention_days=90,
        retention_interval_seconds=0.01,
    )

    runtime.start()
    try:
        assert storage.prune_started.wait(timeout=1)
        with pytest.raises(RuntimeError, match="shutdown timed out"):
            runtime.stop(timeout=0.01)

        assert recorder.run_finished.wait(timeout=1)
        assert not runtime._thread.is_alive()
        assert storage.closed is False
        assert storage.closed_while_pruning is False
    finally:
        storage.release_prune.set()
        runtime.stop(timeout=1)


@pytest.mark.unit
def test_blocking_retention_prune_remains_owned_until_retry_can_clean_up() -> None:
    recorder = _FakeRecorder()
    storage = _BlockingRetentionStorage("unused")
    released_owners: list[str] = []
    runtime = desktop._DesktopTickCaptureRuntime(
        recorder,
        storage,
        "",
        retention_days=90,
        retention_interval_seconds=0.01,
        on_storage_closed=lambda: released_owners.append("released"),
    )

    runtime.start()
    try:
        assert storage.prune_started.wait(timeout=1)
        owner = getattr(runtime, "_retention_thread", None)
        assert owner is not None
        assert owner.daemon is True

        with pytest.raises(RuntimeError, match="shutdown timed out"):
            runtime.stop(timeout=0.01)
        assert runtime._retention_thread is owner
        assert owner.is_alive()

        with pytest.raises(RuntimeError, match="shutdown timed out"):
            runtime.stop(timeout=0.01)
        assert runtime._retention_thread is owner
        assert owner.is_alive()
        assert storage.close_calls == 0
        assert released_owners == []

        storage.release_prune.set()
        owner.join(timeout=1)
        assert not owner.is_alive()
        assert storage.prune_finished.is_set()
        assert storage.closed is False
        assert released_owners == []

        runtime.stop(timeout=1)

        assert storage.close_calls == 1
        assert storage.closed is True
        assert storage.closed_while_pruning is False
        assert released_owners == ["released"]
    finally:
        storage.release_prune.set()
        if runtime._thread.is_alive() or not storage.closed:
            runtime.stop(timeout=1)


@pytest.mark.unit
def test_deferred_storage_close_obeys_its_timeout_and_remains_retryable() -> None:
    recorder = _FakeRecorder()
    storage = _BlockingCloseStorage("unused")
    runtime = desktop._DesktopTickCaptureRuntime(recorder, storage, "")
    runtime.start()
    assert recorder.run_started.wait(timeout=1)
    runtime.stop(timeout=1, close_storage=False)

    started = time.monotonic()
    try:
        with pytest.raises(RuntimeError, match="storage shutdown timed out"):
            runtime.close_storage(timeout=0.01)
        assert time.monotonic() - started < 0.2
        assert storage.close_started.wait(timeout=1)
        assert storage.closed is False
    finally:
        storage.release_close.set()

    runtime.close_storage(timeout=1)
    assert storage.closed is True


@pytest.mark.unit
def test_desktop_finalisation_timeout_rejoins_the_same_flush_worker_without_duplicate_dispatch() -> None:
    flush_started = threading.Event()
    release_flush = threading.Event()

    class Recorder:
        pending_tick_count = 3
        flush_calls = 0

        async def run(self) -> None:
            return None

        def flush_pending(self) -> None:
            self.flush_calls += 1
            flush_started.set()
            assert release_flush.wait(2)
            self.pending_tick_count = 0

    recorder = Recorder()
    storage = MagicMock()
    checkpoint_owner = MagicMock()
    runtime = desktop._DesktopTickCaptureRuntime(
        recorder,
        storage,
        "",
        storage_lock=threading.Lock(),
        checkpoint_owner=checkpoint_owner,
        retention_days=0,
    )

    with pytest.raises(RuntimeError, match="storage shutdown timed out"):
        runtime.close_storage(timeout=0.02)

    assert flush_started.wait(1)
    retained_worker = runtime._storage_close_worker
    with pytest.raises(RuntimeError, match="storage shutdown timed out"):
        runtime.close_storage(timeout=0.0)
    assert runtime._storage_close_worker is retained_worker
    assert recorder.flush_calls == 1
    checkpoint_owner.persist.assert_not_called()
    storage.close.assert_not_called()

    release_flush.set()
    runtime.close_storage(timeout=1.0)

    assert recorder.flush_calls == 1
    checkpoint_owner.persist.assert_called_once_with(force=True)
    storage.close.assert_called_once_with()


@pytest.mark.unit
def test_deferred_storage_close_retries_one_transient_close_failure_in_one_call() -> None:
    recorder = _FakeRecorder()
    storage = _RetryingCloseStorage("unused", failures=1)
    runtime = desktop._DesktopTickCaptureRuntime(recorder, storage, "")
    runtime.start()
    assert recorder.run_started.wait(timeout=1)
    runtime.stop(timeout=1, close_storage=False)

    runtime.close_storage(timeout=1)

    assert storage.close_calls == 2
    assert storage.closed is True


@pytest.mark.unit
def test_enabled_desktop_builds_one_runtime_with_existing_hub_and_settings(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flask_app = Flask("desktop-capture")
    signal_hub = object()
    flask_app.config["SIGNAL_HUB"] = signal_hub
    sandbox_engine = object()
    flask_app.config["DATA_SANDBOX_ENGINE"] = sandbox_engine
    settings = SimpleNamespace(openalgo_api_key="workspace-key")
    storage = _FakeStorage("unused")
    storage_paths: list[str] = []
    recorder = _FakeRecorder()
    orderflow = MagicMock()
    orderflow.replay_current_session_tail.return_value = {
        "restored_ticks": 0,
        "skipped_ticks": 0,
    }
    orderflow.export_state.return_value = {"version": 1, "identities": []}
    watchlist = [{"exchange": "NSE_INDEX", "symbol": "NIFTY"}]
    build_calls: list[dict[str, object]] = []

    monkeypatch.setattr(desktop, "_tick_capture_enabled", lambda: True)
    monkeypatch.setattr(desktop, "_workspace_dir", lambda: tmp_path)
    monkeypatch.setattr(desktop, "_tick_capture_watchlist", lambda: watchlist)
    monkeypatch.setattr(desktop, "_tick_capture_mode", lambda: "depth")

    def build_recorder(**kwargs):
        build_calls.append(kwargs)
        return recorder

    runtime = desktop._configure_tick_capture(
        flask_app,
        settings,
        storage_factory=lambda path: storage_paths.append(path) or storage,
        recorder_factory=object(),
        orderflow_factory=lambda: orderflow,
        build_recorder=build_recorder,
    )
    assert runtime is flask_app.config["DESKTOP_TICK_CAPTURE_RUNTIME"]
    assert runtime._thread.daemon is False
    assert recorder.run_started.wait(1)
    assert len(build_calls) == 1
    call = build_calls[0]
    assert call["signal_hub"] is signal_hub
    assert call["sandbox_engine"] is sandbox_engine
    assert call["settings"] is settings
    assert call["storage"] is storage
    assert call["storage_lock"] is flask_app.config["TICK_STORAGE_LOCK"]
    assert call["orderflow"] is orderflow
    assert call["watchlist"] is watchlist
    assert call["mode"] == "depth"
    assert storage.db_path == "unused"
    assert storage_paths == [str(tmp_path / "ticks.duckdb")]
    assert storage.initialised is True
    assert storage.pruned_days == [90]
    assert len(storage.tick_queries) == 1
    orderflow.replay_current_session_tail.assert_called_once()
    orderflow.restore_current_session.assert_not_called()
    assert flask_app.config["TICK_CAPTURE_ENABLED"] is True
    assert flask_app.config["TICK_CAPTURE_ERROR"] == ""
    assert flask_app.config["TICK_RECORDER"] is recorder
    assert flask_app.config["TICK_STORAGE"] is storage
    assert flask_app.config["ORDERFLOW_AGGREGATOR"] is orderflow

    runtime.stop(timeout=1)
    assert recorder.stop_calls == 1
    assert recorder.run_finished.wait(1)
    assert storage.closed is True
    assert "DESKTOP_TICK_CAPTURE_RUNTIME" not in flask_app.config
    assert _CAPTURE_CONFIG_KEYS.isdisjoint(flask_app.config)


@pytest.mark.unit
def test_failed_storage_close_remains_retryable_and_unpublished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flask_app = Flask("desktop-capture-close-retry")
    recorder = _FakeRecorder()
    storage = _RetryingCloseStorage("unused", failures=2)
    monkeypatch.setattr(desktop, "_tick_capture_enabled", lambda: True)

    runtime = desktop._configure_tick_capture(
        flask_app,
        SimpleNamespace(openalgo_api_key=""),
        storage_factory=lambda _path: storage,
        recorder_factory=object(),
        orderflow_factory=object,
        build_recorder=lambda **_kwargs: recorder,
    )
    assert runtime is not None
    assert recorder.run_started.wait(1)

    with pytest.raises(RuntimeError, match="tick storage shutdown failed"):
        runtime.stop(timeout=1)

    assert storage.close_calls == 2
    assert storage.closed is False
    assert runtime._storage_closed is False
    assert flask_app.config["DESKTOP_TICK_CAPTURE_RUNTIME"] is runtime
    assert _CAPTURE_CONFIG_KEYS.isdisjoint(flask_app.config)

    runtime.stop(timeout=1)

    assert storage.close_calls == 3
    assert storage.closed is True
    assert runtime._storage_closed is True
    assert "DESKTOP_TICK_CAPTURE_RUNTIME" not in flask_app.config


@pytest.mark.unit
def test_deferred_storage_close_retries_one_transient_checkpoint_failure_in_one_call() -> None:
    recorder = MagicMock(pending_tick_count=0)
    storage = MagicMock()
    checkpoint_owner = MagicMock()
    checkpoint_owner.persist.side_effect = [RuntimeError("checkpoint unavailable"), None]
    runtime = desktop._DesktopTickCaptureRuntime(
        recorder,
        storage,
        "",
        checkpoint_owner=checkpoint_owner,
    )

    runtime.stop(timeout=1, close_storage=False)
    runtime.close_storage(timeout=1)

    assert checkpoint_owner.persist.call_args_list == [
        call(force=True),
        call(force=True),
    ]
    storage.close.assert_called_once_with()
    assert runtime._storage_closed is True


@pytest.mark.unit
def test_disabled_desktop_capture_opens_no_runtime_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    flask_app = Flask("desktop-capture-disabled")
    monkeypatch.setattr(desktop, "_tick_capture_enabled", lambda: False)
    storage_factory = MagicMock(side_effect=AssertionError("storage must stay closed"))

    runtime = desktop._configure_tick_capture(
        flask_app,
        SimpleNamespace(openalgo_api_key=""),
        storage_factory=storage_factory,
        recorder_factory=object(),
        orderflow_factory=MagicMock(side_effect=AssertionError("aggregator must stay absent")),
        build_recorder=MagicMock(side_effect=AssertionError("recorder must stay absent")),
    )

    assert runtime is None
    assert flask_app.config["TICK_CAPTURE_ENABLED"] is False
    assert flask_app.config["TICK_CAPTURE_ERROR"] == ""
    assert "DESKTOP_TICK_CAPTURE_RUNTIME" not in flask_app.config
    assert _CAPTURE_CONFIG_KEYS.isdisjoint(flask_app.config)
    storage_factory.assert_not_called()


@pytest.mark.unit
def test_configured_capture_failure_is_redacted_and_leaves_no_partial_config(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flask_app = Flask("desktop-capture-failure")
    api_key = "top-secret-workspace-key"
    external_secret = "provider-auth-payload"
    storage = _FakeStorage("unused")
    monkeypatch.setattr(desktop, "_tick_capture_enabled", lambda: True)

    def fail_build(**_kwargs):
        raise RuntimeError(f"OpenAlgo rejected {api_key} using {external_secret}")

    runtime = desktop._configure_tick_capture(
        flask_app,
        SimpleNamespace(openalgo_api_key=api_key),
        storage_factory=lambda _path: storage,
        recorder_factory=object(),
        orderflow_factory=object,
        build_recorder=fail_build,
    )

    assert runtime is None
    assert flask_app.config["TICK_CAPTURE_ENABLED"] is True
    assert flask_app.config["TICK_CAPTURE_ERROR"] == "RuntimeError"
    assert api_key not in flask_app.config["TICK_CAPTURE_ERROR"]
    assert external_secret not in flask_app.config["TICK_CAPTURE_ERROR"]
    assert api_key not in caplog.text
    assert external_secret not in caplog.text
    assert "DESKTOP_TICK_CAPTURE_RUNTIME" not in flask_app.config
    assert _CAPTURE_CONFIG_KEYS.isdisjoint(flask_app.config)
    assert storage.closed is True


@pytest.mark.unit
def test_pre_runtime_rollback_retains_exact_storage_owner_after_close_failure(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_key = "pre-runtime-rollback-secret"
    flask_app = Flask("desktop-pre-runtime-storage-rollback")
    storage = _RetryingCloseStorage("unused", failures=1)
    monkeypatch.setattr(desktop, "_tick_capture_enabled", lambda: True)
    caplog.set_level(logging.WARNING, logger="flinttrade.desktop")

    def fail_build(**_kwargs) -> None:
        raise RuntimeError(f"recorder construction rejected {api_key}")

    configured = desktop._configure_tick_capture(
        flask_app,
        SimpleNamespace(openalgo_api_key=api_key),
        storage_factory=lambda _path: storage,
        recorder_factory=object(),
        orderflow_factory=object,
        build_recorder=fail_build,
    )

    assert configured is None
    owner = flask_app.config["DESKTOP_TICK_CAPTURE_RUNTIME"]
    assert owner.storage is storage
    assert storage.close_calls == 1
    assert storage.closed is False
    assert _CAPTURE_CONFIG_KEYS.isdisjoint(flask_app.config)
    assert flask_app.config["TICK_CAPTURE_ERROR"] == "RuntimeError"
    assert api_key not in caplog.text
    assert "transient close failure" not in caplog.text
    assert "RuntimeError" in caplog.text

    owner.stop(timeout=1.0)

    assert storage.close_calls == 2
    assert storage.closed is True
    assert "DESKTOP_TICK_CAPTURE_RUNTIME" not in flask_app.config


@pytest.mark.unit
def test_failed_startup_rollback_retains_runtime_owner_for_process_teardown(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_key = "startup-rollback-secret"
    flask_app = Flask("desktop-capture-startup-rollback")
    storage = _FakeStorage("unused")
    recorder = _FakeRecorder()

    class FailingRollbackRuntime:
        def __init__(self, _recorder, owned_storage, _api_key, **kwargs) -> None:
            self.storage = owned_storage
            self.on_storage_closed = kwargs.get("on_storage_closed")
            self.stop_calls = 0

        def start(self) -> None:
            raise RuntimeError(f"startup failed for {api_key}")

        def stop(self, **_kwargs) -> None:
            self.stop_calls += 1
            if self.stop_calls == 1:
                raise RuntimeError(f"rollback stop failed for {api_key}")

        def close_storage(self, **_kwargs) -> None:
            self.storage.close()
            if self.on_storage_closed is not None:
                self.on_storage_closed()

        def sanitise_error(self, error: object) -> str:
            return str(error).replace(api_key, "[redacted]")

    monkeypatch.setattr(desktop, "_tick_capture_enabled", lambda: True)
    monkeypatch.setattr(desktop, "_DesktopTickCaptureRuntime", FailingRollbackRuntime)
    caplog.set_level(logging.WARNING, logger="flinttrade.desktop")

    configured = desktop._configure_tick_capture(
        flask_app,
        SimpleNamespace(openalgo_api_key=api_key),
        storage_factory=lambda _path: storage,
        recorder_factory=object(),
        orderflow_factory=object,
        build_recorder=lambda **_kwargs: recorder,
    )

    assert configured is None
    runtime = flask_app.config["DESKTOP_TICK_CAPTURE_RUNTIME"]
    assert isinstance(runtime, FailingRollbackRuntime)
    assert runtime.stop_calls == 1
    assert _CAPTURE_CONFIG_KEYS.isdisjoint(flask_app.config)
    assert flask_app.config["TICK_CAPTURE_ERROR"] == "RuntimeError"
    assert api_key not in caplog.text
    assert "rollback stop failed" not in caplog.text
    assert "RuntimeError" in caplog.text

    monkeypatch.setattr(desktop, "_build_app", lambda: flask_app)
    monkeypatch.setattr(
        "waitress.server.create_server",
        lambda *_args, **_kwargs: SimpleNamespace(effective_port=5100, run=lambda: None),
    )

    desktop._serve_owned(5100, ready_writer=lambda _message: None)

    assert runtime.stop_calls == 2
    assert storage.closed is True
    assert "DESKTOP_TICK_CAPTURE_RUNTIME" not in flask_app.config


@pytest.mark.unit
def test_stop_never_closes_storage_while_recorder_thread_is_still_flushing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flask_app = Flask("desktop-capture-slow-stop")
    recorder = _SlowCleanupRecorder()
    storage = _FakeStorage("unused")
    monkeypatch.setattr(desktop, "_tick_capture_enabled", lambda: True)

    runtime = desktop._configure_tick_capture(
        flask_app,
        SimpleNamespace(openalgo_api_key=""),
        storage_factory=lambda _path: storage,
        recorder_factory=object(),
        orderflow_factory=object,
        build_recorder=lambda **_kwargs: recorder,
    )
    assert runtime is not None
    assert recorder.run_started.wait(1)

    with pytest.raises(RuntimeError, match="shutdown timed out"):
        runtime.stop(timeout=0.01)

    assert recorder.cancel_seen.wait(1)
    assert runtime._thread.is_alive()
    assert storage.closed is False

    recorder.release_cleanup.set()
    runtime._thread.join(timeout=1)
    assert not runtime._thread.is_alive()
    assert recorder.run_finished.is_set()
    runtime.close_storage(timeout=1)
    assert storage.closed is True


@pytest.mark.unit
def test_final_recorder_flush_failure_is_redacted_and_propagated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    api_key = "final-flush-secret"
    recorder = _FlushFailureRecorder(api_key)
    storage = _FakeStorage("unused")
    runtime = desktop._DesktopTickCaptureRuntime(recorder, storage, api_key)
    caplog.set_level(logging.WARNING, logger="flinttrade.desktop")
    runtime.start()
    assert recorder.run_started.wait(1)

    with pytest.raises(RuntimeError, match="tick capture shutdown failed") as error:
        runtime.stop(timeout=1)

    assert recorder.run_finished.wait(1)
    assert storage.closed is True
    assert api_key not in str(error.value)
    assert api_key not in caplog.text
    assert "final flush rejected [redacted]" in caplog.text


@pytest.mark.unit
def test_transient_final_flush_failure_retries_retained_ticks_before_storage_close() -> None:
    events: list[str] = []
    recorder = _TransientFlushFailureRecorder(events)
    storage = _FakeStorage("unused")
    original_close = storage.close

    def close_storage() -> None:
        events.append("storage-close")
        original_close()

    storage.close = close_storage  # type: ignore[method-assign]
    runtime = desktop._DesktopTickCaptureRuntime(recorder, storage, "")
    runtime.start()
    assert recorder.run_started.wait(1)

    runtime.stop(timeout=1)

    assert recorder.run_finished.wait(1)
    assert recorder.flush_calls == 1
    assert recorder.pending_tick_count == 0
    assert storage.closed is True
    assert events == ["final-flush-failed", "flush-retry", "storage-close"]


@pytest.mark.unit
def test_failed_retained_flush_keeps_storage_open_for_later_stop_retry() -> None:
    events: list[str] = []
    recorder = _RetainedFlushFailureRecorder(events)
    storage = _FakeStorage("unused")
    original_close = storage.close

    def close_storage() -> None:
        events.append("storage-close")
        original_close()

    storage.close = close_storage  # type: ignore[method-assign]
    runtime = desktop._DesktopTickCaptureRuntime(recorder, storage, "")
    runtime.start()
    assert recorder.run_started.wait(1)

    with pytest.raises(RuntimeError, match="tick capture shutdown failed"):
        runtime.stop(timeout=1)

    assert recorder.pending_tick_count == 1
    assert recorder.flush_calls == 3
    assert storage.closed is False
    assert "storage-close" not in events

    recorder.allow_flush = True
    runtime.stop(timeout=1)

    assert recorder.pending_tick_count == 0
    assert storage.closed is True
    assert events[-2:] == ["flush-retry", "storage-close"]


@pytest.mark.unit
def test_unexpected_recorder_death_is_redacted_and_removes_closed_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flask_app = Flask("desktop-capture-runtime-failure")
    api_key = "runtime-secret-key"
    recorder = _UnexpectedFailureRecorder(api_key)
    storage = _FakeStorage("unused")
    monkeypatch.setattr(desktop, "_tick_capture_enabled", lambda: True)

    runtime = desktop._configure_tick_capture(
        flask_app,
        SimpleNamespace(openalgo_api_key=api_key),
        storage_factory=lambda _path: storage,
        recorder_factory=object(),
        orderflow_factory=object,
        build_recorder=lambda **_kwargs: recorder,
    )
    assert runtime is not None
    assert _CAPTURE_CONFIG_KEYS.issubset(flask_app.config)

    recorder.release_failure.set()
    runtime._thread.join(timeout=1)

    assert not runtime._thread.is_alive()
    runtime.close_storage(timeout=1)
    assert storage.closed is True
    assert _CAPTURE_CONFIG_KEYS.isdisjoint(flask_app.config)
    assert flask_app.config["TICK_CAPTURE_ENABLED"] is True
    assert flask_app.config["TICK_CAPTURE_ERROR"] == "recorder stopped with [redacted]"
    assert api_key not in flask_app.config["TICK_CAPTURE_ERROR"]


@pytest.mark.unit
def test_unexpected_recorder_close_never_blocks_the_recorder_owner_thread() -> None:
    recorder = _UnexpectedFailureRecorder("runtime-secret")
    storage = _BlockingCloseStorage("unused")
    runtime = desktop._DesktopTickCaptureRuntime(recorder, storage, "runtime-secret")
    runtime.start()
    assert recorder.run_started.wait(1)

    started = time.monotonic()
    recorder.release_failure.set()
    runtime._thread.join(timeout=0.2)

    assert time.monotonic() - started < 0.3
    assert runtime._thread.is_alive() is False
    assert storage.close_started.wait(1)
    assert storage.closed is False

    stop_started = time.monotonic()
    runtime.stop(timeout=0.05, close_storage=False)
    assert time.monotonic() - stop_started < 0.2
    assert storage.closed is False

    storage.release_close.set()
    runtime.close_storage(timeout=1)
    assert storage.closed is True


@pytest.mark.unit
@pytest.mark.parametrize("pending_value", [None, "unknown", object()])
def test_unexpected_recorder_unknown_pending_count_retains_storage_for_retry(
    pending_value: object,
) -> None:
    recorder = _UnexpectedFailureRecorder("runtime-secret")
    if pending_value is None:
        del recorder.pending_tick_count
    else:
        recorder.pending_tick_count = pending_value
    storage = _FakeStorage("unused")
    runtime = desktop._DesktopTickCaptureRuntime(recorder, storage, "runtime-secret")
    runtime.start()
    recorder.release_failure.set()
    runtime._thread.join(timeout=1)

    assert runtime._thread.is_alive() is False
    assert storage.closed is False
    with pytest.raises(RuntimeError, match="tick capture shutdown failed"):
        runtime.stop(timeout=0.1)

    recorder.pending_tick_count = 0
    runtime.stop(timeout=1)
    assert storage.closed is True


@pytest.mark.unit
def test_missing_frozen_capture_dependency_records_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    flask_app = Flask("desktop-capture-import-failure")
    monkeypatch.setattr(desktop, "_tick_capture_enabled", lambda: True)
    real_import = builtins.__import__

    def fail_storage_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "flinttrade_data.storage":
            raise ImportError("tick storage was not bundled")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fail_storage_import)

    runtime = desktop._configure_tick_capture(
        flask_app,
        SimpleNamespace(openalgo_api_key=""),
    )

    assert runtime is None
    assert flask_app.config["TICK_CAPTURE_ENABLED"] is True
    assert flask_app.config["TICK_CAPTURE_ERROR"] == "ImportError"
    assert _CAPTURE_CONFIG_KEYS.isdisjoint(flask_app.config)


@pytest.mark.unit
def test_build_app_configures_capture_with_the_same_settings_and_hub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flask_app = Flask("desktop-build")
    signal_hub = object()
    flask_app.config["SIGNAL_HUB"] = signal_hub
    settings = SimpleNamespace(openalgo_api_key="workspace-key")
    configured: list[tuple[Flask, object, object]] = []

    monkeypatch.setattr("flinttrade_core.config.Settings.from_env", lambda: settings)
    monkeypatch.setattr("flinttrade_core.openalgo_client.OpenAlgoClient", lambda value: ("client", value))
    monkeypatch.setattr("flinttrade_data.audit_logger.AuditLogger", MagicMock)
    monkeypatch.setattr(desktop, "create_flask_app", lambda **_kwargs: flask_app)

    def configure(app, active_settings, **_kwargs):
        configured.append((app, active_settings, app.config["SIGNAL_HUB"]))
        return object()

    monkeypatch.setattr(desktop, "_configure_tick_capture", configure)

    assert desktop._build_app() is flask_app
    assert configured == [(flask_app, settings, signal_hub)]


@pytest.mark.unit
def test_serve_announces_ready_after_capture_start_and_stops_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    runtime = SimpleNamespace(stop=lambda **_kwargs: events.append("capture-stop"))
    flask_app = Flask("desktop-serve")
    flask_app.config["DESKTOP_TICK_CAPTURE_RUNTIME"] = runtime

    class FakeServer:
        effective_port = 5199

        def run(self) -> None:
            events.append("server-run")

    def build_app():
        events.append("capture-start")
        return flask_app

    monkeypatch.setattr(desktop, "_build_app", build_app)
    monkeypatch.setattr("waitress.server.create_server", lambda *_args, **_kwargs: FakeServer())

    desktop.serve(0, ready_writer=lambda _message: events.append("ready"))

    assert events == ["capture-start", "ready", "server-run", "capture-stop"]


@pytest.mark.unit
def test_serve_closes_app_owned_client_and_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    client = object()
    audit = SimpleNamespace(close=lambda: events.append("audit-close"))
    flask_app = Flask("desktop-owned-dependencies")
    flask_app.config.update(CLIENT=client, AUDIT=audit)
    monkeypatch.setattr(desktop, "_build_app", lambda: flask_app)
    monkeypatch.setattr(
        desktop,
        "client_close_sync",
        lambda value: events.append("client-close") if value is client else None,
    )
    monkeypatch.setattr(
        "waitress.server.create_server",
        lambda *_args, **_kwargs: SimpleNamespace(
            effective_port=5100,
            run=lambda: events.append("server-run"),
        ),
    )

    desktop.serve(5100, ready_writer=lambda _message: None)

    assert events == ["server-run", "client-close", "audit-close"]


@pytest.mark.unit
def test_serve_reports_client_close_failure_after_closing_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = MagicMock()
    flask_app = Flask("desktop-client-close-failure")
    flask_app.config.update(CLIENT=object(), AUDIT=audit)
    monkeypatch.setattr(desktop, "_build_app", lambda: flask_app)
    monkeypatch.setattr(
        desktop,
        "client_close_sync",
        MagicMock(side_effect=RuntimeError("close failed")),
    )
    monkeypatch.setattr(
        "waitress.server.create_server",
        lambda *_args, **_kwargs: SimpleNamespace(effective_port=5100, run=lambda: None),
    )

    with pytest.raises(RuntimeError, match="backend shutdown failed"):
        desktop.serve(5100, ready_writer=lambda _message: None)

    audit.close.assert_called_once_with()


@pytest.mark.unit
def test_serve_quiesces_background_owners_and_flushes_capture_before_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.agent_routes as agent_routes
    import flinttrade_core.smart_order_routes as smart_routes
    import flinttrade_engine.strategy_routes as strategy_routes

    events: list[str] = []
    stream_shutdown = threading.Event()
    runtime = SimpleNamespace(stop=lambda **_kwargs: events.append("capture-stop"))
    rotation = MagicMock(running=True)
    rotation.shutdown.side_effect = lambda **_kwargs: events.append("rotation-stop")
    tracker = MagicMock()

    def wait_for_idle(_timeout: float) -> bool:
        assert stream_shutdown.is_set()
        assert events == [
            "smart-stop",
            "agent-stop",
            "uploaded-stop",
            "rotation-stop",
            "router-retire",
            "capture-stop",
        ]
        events.append("requests-drained")
        return True

    tracker.wait_for_idle.side_effect = wait_for_idle
    flask_app = Flask("desktop-quiesce-order")
    flask_app.config.update(
        DESKTOP_TICK_CAPTURE_RUNTIME=runtime,
        RUNTIME_REQUEST_TRACKER=tracker,
        SIGNAL_STREAM_SHUTDOWN_EVENT=stream_shutdown,
        ROTATION_SCHEDULER=rotation,
        BROKER_ROUTER=object(),
    )
    monkeypatch.setattr(desktop, "_build_app", lambda: flask_app)
    monkeypatch.setattr(
        agent_routes,
        "shutdown_agent_runtime",
        lambda _app, **_kwargs: events.append("agent-stop") or True,
        raising=False,
    )
    monkeypatch.setattr(
        smart_routes,
        "shutdown_smart_order_jobs",
        lambda **_kwargs: events.append("smart-stop") or True,
    )
    monkeypatch.setattr(
        strategy_routes,
        "shutdown_strategy_runtime",
        lambda _app: events.append("uploaded-stop") or [],
    )
    monkeypatch.setattr(
        desktop,
        "retire_broker_router_generation",
        lambda _app: events.append("router-retire") or True,
        raising=False,
    )
    monkeypatch.setattr(
        "waitress.server.create_server",
        lambda *_args, **_kwargs: SimpleNamespace(effective_port=5100, run=lambda: None),
    )

    desktop.serve(5100, ready_writer=lambda _message: None)

    tracker.wait_for_idle.assert_called_once()
    assert events == [
        "smart-stop",
        "agent-stop",
        "uploaded-stop",
        "rotation-stop",
        "router-retire",
        "capture-stop",
        "requests-drained",
        "uploaded-stop",
        "router-retire",
    ]


@pytest.mark.unit
def test_serve_defers_real_capture_storage_close_until_requests_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    recorder = MagicMock(pending_tick_count=0)
    recorder.stop.side_effect = lambda: events.append("capture-stop")
    storage = MagicMock()
    storage.close.side_effect = lambda: events.append("storage-close")
    runtime = desktop._DesktopTickCaptureRuntime(recorder, storage, "")
    tracker = MagicMock()

    def wait_for_idle(_timeout: float) -> bool:
        events.append("requests-drained")
        assert "storage-close" not in events
        return True

    tracker.wait_for_idle.side_effect = wait_for_idle
    flask_app = Flask("desktop-deferred-tick-storage")
    flask_app.config.update(
        DESKTOP_TICK_CAPTURE_RUNTIME=runtime,
        RUNTIME_REQUEST_TRACKER=tracker,
    )
    monkeypatch.setattr(desktop, "_build_app", lambda: flask_app)
    monkeypatch.setattr(
        "waitress.server.create_server",
        lambda *_args, **_kwargs: SimpleNamespace(effective_port=5100, run=lambda: None),
    )

    desktop.serve(5100, ready_writer=lambda _message: None)

    assert events == ["capture-stop", "requests-drained", "storage-close"]
    storage.close.assert_called_once_with()


@pytest.mark.unit
def test_one_serve_shutdown_retries_retained_flushes_before_storage_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    recorder = _BoundedRetryFlushRecorder(events, failures=2)
    storage = _FakeStorage("unused")
    original_close = storage.close

    def close_storage() -> None:
        events.append("storage-close")
        original_close()

    storage.close = close_storage  # type: ignore[method-assign]
    runtime = desktop._DesktopTickCaptureRuntime(recorder, storage, "")
    runtime.start()
    assert recorder.run_started.wait(timeout=1)
    flask_app = Flask("desktop-retained-flush-retry")
    flask_app.config["DESKTOP_TICK_CAPTURE_RUNTIME"] = runtime
    monkeypatch.setattr(desktop, "_build_app", lambda: flask_app)
    monkeypatch.setattr(
        "waitress.server.create_server",
        lambda *_args, **_kwargs: SimpleNamespace(effective_port=5100, run=lambda: None),
    )

    desktop._serve_owned(5100, ready_writer=lambda _message: None)

    assert recorder.flush_calls == 3
    assert recorder.pending_tick_count == 0
    assert storage.closed is True
    assert events == [
        "final-flush-failed",
        "flush-retry",
        "flush-retry",
        "flush-retry",
        "storage-close",
    ]


@pytest.mark.unit
def test_serve_drain_timeout_does_not_close_request_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = object()
    audit = MagicMock()
    tracker = MagicMock()
    tracker.wait_for_idle.return_value = False
    flask_app = Flask("desktop-drain-timeout")
    flask_app.config.update(
        CLIENT=client,
        AUDIT=audit,
        RUNTIME_REQUEST_TRACKER=tracker,
    )
    close_client = MagicMock()
    monkeypatch.setattr(desktop, "_build_app", lambda: flask_app)
    monkeypatch.setattr(desktop, "client_close_sync", close_client)
    monkeypatch.setattr(
        "waitress.server.create_server",
        lambda *_args, **_kwargs: SimpleNamespace(effective_port=5100, run=lambda: None),
    )

    with pytest.raises(RuntimeError, match="backend shutdown failed"):
        desktop.serve(5100, ready_writer=lambda _message: None)

    close_client.assert_not_called()
    audit.close.assert_not_called()


@pytest.mark.unit
def test_serve_stops_capture_when_waitress_bind_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = MagicMock()
    flask_app = Flask("desktop-bind-failure")
    flask_app.config["DESKTOP_TICK_CAPTURE_RUNTIME"] = runtime
    monkeypatch.setattr(desktop, "_build_app", lambda: flask_app)

    def fail_bind(*_args, **_kwargs):
        raise OSError("port unavailable")

    monkeypatch.setattr("waitress.server.create_server", fail_bind)

    with pytest.raises(
        RuntimeError,
        match=r"Desktop backend startup failed \(OSError\)",
    ) as raised:
        desktop.serve(5100)

    assert raised.value.__cause__ is None
    runtime.stop.assert_called_once_with()


@pytest.mark.unit
def test_serve_installs_and_removes_graceful_shutdown_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    runtime = SimpleNamespace(stop=lambda **_kwargs: events.append("capture-stop"))
    flask_app = Flask("desktop-shutdown-signal")
    flask_app.config["DESKTOP_TICK_CAPTURE_RUNTIME"] = runtime

    class ShutdownSignal:
        callback = None

        def install(self, callback) -> None:
            self.callback = callback
            events.append("shutdown-install")

        def uninstall(self, callback) -> None:
            assert callback is self.callback
            events.append("shutdown-uninstall")
            self.callback = None

    shutdown_signal = ShutdownSignal()
    monkeypatch.setattr(desktop, "_build_app", lambda: flask_app)
    monkeypatch.setattr(
        "waitress.server.create_server",
        lambda *_args, **_kwargs: SimpleNamespace(
            effective_port=5100,
            run=lambda: events.append("server-run"),
        ),
    )

    desktop.serve(
        5100,
        ready_writer=lambda _message: events.append("ready"),
        shutdown_signal=shutdown_signal,
    )

    assert events == [
        "shutdown-install",
        "ready",
        "server-run",
        "shutdown-uninstall",
        "capture-stop",
    ]


@pytest.mark.unit
def test_graceful_shutdown_request_unwinds_server_and_flushes_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    runtime = SimpleNamespace(stop=lambda **_kwargs: events.append("capture-stop"))
    flask_app = Flask("desktop-graceful-stop")
    flask_app.config["DESKTOP_TICK_CAPTURE_RUNTIME"] = runtime

    class ShutdownSignal:
        callback = None

        def install(self, callback) -> None:
            self.callback = callback

        def uninstall(self, callback) -> None:
            assert callback is self.callback
            self.callback = None

        def request(self) -> None:
            assert self.callback is not None
            self.callback()

    shutdown_signal = ShutdownSignal()

    def run_server() -> None:
        events.append("server-run")
        request_thread = threading.Thread(target=shutdown_signal.request)
        request_thread.start()
        request_thread.join(timeout=1)
        threading.Event().wait(1)

    monkeypatch.setattr(desktop, "_build_app", lambda: flask_app)
    monkeypatch.setattr(
        "waitress.server.create_server",
        lambda *_args, **_kwargs: SimpleNamespace(effective_port=5100, run=run_server),
    )

    desktop.serve(5100, ready_writer=lambda _message: None, shutdown_signal=shutdown_signal)

    assert events == ["server-run", "capture-stop"]


@pytest.mark.unit
def test_serve_redacts_capture_shutdown_failure(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_api_key = "old-workspace-key"
    new_api_key = "rotated-workspace-key"

    def fail_stop() -> None:
        raise RuntimeError(f"close rejected {old_api_key} then {new_api_key}")

    def sanitise_error(error: object) -> str:
        return str(error).replace(old_api_key, "[redacted]").replace(new_api_key, "[redacted]")

    runtime = SimpleNamespace(stop=fail_stop, sanitise_error=sanitise_error)
    flask_app = Flask("desktop-stop-failure")
    flask_app.config["DESKTOP_TICK_CAPTURE_RUNTIME"] = runtime
    monkeypatch.setattr(desktop, "_build_app", lambda: flask_app)
    monkeypatch.setattr(
        "waitress.server.create_server",
        lambda *_args, **_kwargs: SimpleNamespace(effective_port=5100, run=lambda: None),
    )
    caplog.set_level(logging.WARNING, logger="flinttrade.desktop")

    with pytest.raises(RuntimeError, match="backend shutdown failed"):
        desktop.serve(5100, ready_writer=lambda _message: None)

    assert old_api_key not in caplog.text
    assert new_api_key not in caplog.text
    assert "close rejected [redacted] then [redacted]" in caplog.text
