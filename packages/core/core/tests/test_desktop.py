"""Tests for the native-desktop backend entry point (``flinttrade_core.desktop``).

Run with:
    python -m pytest packages/core/core/tests/test_desktop.py -v --import-mode=importlib
"""

from __future__ import annotations

import asyncio
import threading
import time
import traceback
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from flask import Flask

from flinttrade_core import desktop


def _stub_desktop_shutdown_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep serve-order tests isolated from process-global runtime owners."""
    monkeypatch.setattr(
        desktop,
        "_close_runtime_request_admission",
        lambda _app: SimpleNamespace(wait_for_idle=lambda _timeout: True),
    )
    monkeypatch.setattr(desktop, "retire_broker_router_generation", lambda _app: True)
    monkeypatch.setattr(
        "flinttrade_core.smart_order_routes.shutdown_smart_order_jobs",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        "flinttrade_core.agent_routes.shutdown_agent_runtime",
        lambda _app, **_kwargs: True,
    )
    monkeypatch.setattr(
        "flinttrade_engine.strategy_routes.shutdown_strategy_runtime",
        lambda _app: None,
    )


def _stub_transactional_build(
    monkeypatch: pytest.MonkeyPatch,
    events: list[str],
    *,
    smart_shutdown_complete: bool = True,
) -> Flask:
    """Install deterministic desktop build owners and fail after tick acquisition."""
    import flinttrade_core.config as config_module
    import flinttrade_core.local_ai_routes as local_ai_routes
    import flinttrade_core.openalgo_client as client_module
    import flinttrade_core.smart_order_routes as smart_order_routes
    import flinttrade_data.audit_logger as audit_module

    class Audit:
        def __init__(self) -> None:
            events.append("audit-acquired")

        def log_event(self, _event: str) -> None:
            return None

        def close(self) -> None:
            events.append("audit-close")

    class Client:
        def __init__(self, _settings: object) -> None:
            events.append("client-acquired")

    flask_app = Flask("transactional-desktop-build")

    def create_app(*, audit: object, client: object, **_kwargs: object) -> Flask:
        flask_app.config.update(
            AUDIT=audit,
            CLIENT=client,
            SAFETY_CONFIG_READY=False,
        )
        return flask_app

    monkeypatch.setattr(audit_module, "AuditLogger", Audit)
    monkeypatch.setattr(config_module.Settings, "from_env", staticmethod(lambda: object()))
    monkeypatch.setattr(client_module, "OpenAlgoClient", Client)
    monkeypatch.setattr(desktop, "create_flask_app", create_app)
    monkeypatch.setattr(
        local_ai_routes,
        "start_configured_local_ai_runtime",
        lambda _app: events.append("local-ai-start") or True,
    )
    monkeypatch.setattr(
        local_ai_routes,
        "shutdown_local_ai_runtime",
        lambda runtime_app, **_kwargs: (
            runtime_app.config["RUNTIME_ACCEPTING_REQUESTS"] is False
            and not events.append("local-ai-stop")
        ),
    )
    monkeypatch.setattr(
        smart_order_routes,
        "start_smart_order_jobs",
        lambda: events.append("smart-start") or True,
    )
    monkeypatch.setattr(
        smart_order_routes,
        "shutdown_smart_order_jobs",
        lambda **_kwargs: events.append("smart-stop") or smart_shutdown_complete,
    )
    monkeypatch.setattr(
        desktop,
        "_configure_tick_capture",
        MagicMock(side_effect=RuntimeError("injected after smart-order admission")),
    )
    monkeypatch.setattr(desktop, "client_close_sync", lambda _client: events.append("client-close"))
    return flask_app


@pytest.mark.unit
def test_resolve_port_prefers_cli_arg(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit ``--port`` value wins over the env var and the default."""
    monkeypatch.setenv("FLINTTRADE_BACKEND_PORT", "5999")
    assert desktop._resolve_port(5123) == 5123


@pytest.mark.unit
def test_resolve_port_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no CLI arg, the env var is used."""
    monkeypatch.setenv("FLINTTRADE_BACKEND_PORT", "5321")
    assert desktop._resolve_port(None) == 5321


@pytest.mark.unit
def test_resolve_port_defaults_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """With neither CLI arg nor env var, the default port is returned."""
    monkeypatch.delenv("FLINTTRADE_BACKEND_PORT", raising=False)
    assert desktop._resolve_port(None) == desktop.DEFAULT_PORT


@pytest.mark.unit
def test_resolve_port_ignores_non_integer_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A malformed env var is ignored in favour of the default (never crashes)."""
    monkeypatch.setenv("FLINTTRADE_BACKEND_PORT", "not-a-port")
    assert desktop._resolve_port(None) == desktop.DEFAULT_PORT


@pytest.mark.unit
def test_resolve_port_zero_means_os_chosen(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--port 0`` is honoured (the OS picks a free port at bind time)."""
    monkeypatch.delenv("FLINTTRADE_BACKEND_PORT", raising=False)
    assert desktop._resolve_port(0) == 0


@pytest.mark.unit
def test_ready_sentinel_constant() -> None:
    """The handshake sentinel is the exact string the Tauri shell scans for."""
    assert desktop.READY_SENTINEL == "FLINTTRADE_BACKEND_READY"


@pytest.mark.unit
def test_desktop_lease_conflict_prints_the_blocked_sentinel(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A lease conflict announces itself so the shell keeps the payload pin.

    Without the sentinel the Tauri shell treats the pre-ready exit as a broken
    payload, demotes it, and each Retry re-downloads the engine.
    """
    from flinttrade_core.backend_instance import BackendInstanceAlreadyRunning

    monkeypatch.setattr(
        desktop,
        "acquire_backend_instance_lease",
        MagicMock(side_effect=BackendInstanceAlreadyRunning("held elsewhere")),
    )
    monkeypatch.setattr(
        desktop,
        "_serve_owned",
        MagicMock(side_effect=AssertionError("serve must not start without a lease")),
    )

    with pytest.raises(BackendInstanceAlreadyRunning):
        desktop.serve(5100)

    assert "FLINTTRADE_BACKEND_BLOCKED reason=instance-lease" in capsys.readouterr().out


@pytest.mark.unit
def test_desktop_lease_acquisition_failure_exposes_only_exception_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "lease-provider-secret"

    class ExternalLeaseError(RuntimeError):
        pass

    monkeypatch.setattr(
        desktop,
        "acquire_backend_instance_lease",
        MagicMock(side_effect=ExternalLeaseError(f"lease rejected {secret}")),
    )
    monkeypatch.setattr(
        desktop,
        "_serve_owned",
        MagicMock(side_effect=AssertionError("serve must not start without a lease")),
    )

    with pytest.raises(
        RuntimeError,
        match=r"Desktop backend startup failed \(ExternalLeaseError\)",
    ) as raised:
        desktop.serve(5100)

    rendered = "".join(traceback.format_exception(raised.value))
    assert secret not in rendered
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    desktop._serve_owned.assert_not_called()


@pytest.mark.unit
def test_desktop_lease_release_failure_is_generic_and_retains_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.backend_instance as backend_instance

    secret = "lease-release-provider-secret"

    class ExternalReleaseError(RuntimeError):
        pass

    class RetryingRawLease:
        release_allowed = False

        def release(self) -> None:
            if not self.release_allowed:
                raise ExternalReleaseError(f"release rejected {secret}")

    raw_lease = RetryingRawLease()
    lease = backend_instance.BackendInstanceLease(raw_lease)
    monkeypatch.setattr(desktop, "acquire_backend_instance_lease", lambda: lease)
    monkeypatch.setattr(desktop, "_serve_owned", lambda *_args, **_kwargs: None)
    try:
        with pytest.raises(
            RuntimeError,
            match=r"Desktop backend lease release failed \(ExternalReleaseError\)",
        ) as raised:
            desktop.serve(5100)

        rendered = "".join(traceback.format_exception(raised.value))
        assert secret not in rendered
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None
        assert any(
            retained is lease
            for retained in backend_instance._RETAINED_FAILED_LEASES
        )
    finally:
        raw_lease.release_allowed = True
        backend_instance.release_retained_backend_instance_lease(lease)


@pytest.mark.unit
def test_desktop_workspace_startup_failure_exposes_only_exception_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "workspace-provider-secret"

    class ExternalWorkspaceError(RuntimeError):
        pass

    monkeypatch.setattr(
        desktop,
        "_ensure_workspace",
        MagicMock(side_effect=ExternalWorkspaceError(f"workspace rejected {secret}")),
    )
    monkeypatch.setattr(
        desktop,
        "serve",
        MagicMock(side_effect=AssertionError("serve must not start without a workspace")),
    )

    with pytest.raises(
        RuntimeError,
        match=r"Desktop backend startup failed \(ExternalWorkspaceError\)",
    ) as raised:
        desktop.main([])

    rendered = "".join(traceback.format_exception(raised.value))
    assert secret not in rendered
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    desktop.serve.assert_not_called()


@pytest.mark.unit
def test_desktop_arms_rotation_scheduler_before_ready_handshake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class Scheduler:
        running = False

        def start(self) -> None:
            events.append("scheduler-start")
            self.running = True

        def shutdown(self, *, wait: bool) -> None:
            assert wait is False
            events.append("scheduler-stop")
            self.running = False

    flask_app = Flask("desktop-rotation-start")
    flask_app.config["ROTATION_SCHEDULER"] = Scheduler()
    server = SimpleNamespace(
        effective_port=5100,
        run=lambda: events.append("serve"),
        close=lambda: events.append("server-close"),
    )
    _stub_desktop_shutdown_dependencies(monkeypatch)
    monkeypatch.setattr(desktop, "_build_app", lambda: flask_app)
    monkeypatch.setattr("waitress.server.create_server", lambda *_args, **_kwargs: server)

    desktop._serve_owned(5100, ready_writer=lambda _message: events.append("ready"))

    assert events.index("scheduler-start") < events.index("ready") < events.index("serve")
    assert events.count("scheduler-start") == 1
    assert events.count("scheduler-stop") == 1
    assert events.count("server-close") == 1


@pytest.mark.unit
def test_desktop_rotation_start_failure_never_signals_ready_or_serves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FailingScheduler:
        running = False

        def start(self) -> None:
            events.append("scheduler-start")
            raise RuntimeError("scheduler thread unavailable")

    flask_app = Flask("desktop-rotation-start-failure")
    flask_app.config["ROTATION_SCHEDULER"] = FailingScheduler()
    server = SimpleNamespace(
        effective_port=5100,
        run=lambda: events.append("serve"),
        close=lambda: events.append("server-close"),
    )
    _stub_desktop_shutdown_dependencies(monkeypatch)
    monkeypatch.setattr(desktop, "_build_app", lambda: flask_app)
    monkeypatch.setattr("waitress.server.create_server", lambda *_args, **_kwargs: server)

    with pytest.raises(
        RuntimeError,
        match=r"Desktop backend startup failed \(RuntimeError\)",
    ) as raised:
        desktop._serve_owned(5100, ready_writer=lambda _message: events.append("ready"))

    assert raised.value.__cause__ is None
    assert events == ["scheduler-start", "server-close"]


@pytest.mark.unit
def test_waitress_bind_failure_cleans_partial_server_and_dispatcher_without_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    secret = "bind-provider-secret"
    deadline = time.monotonic() + 1.0

    class ExternalBindError(RuntimeError):
        pass

    class PartialChannel:
        def close(self) -> None:
            events.append("partial-channel-close")

    class Dispatcher:
        def __init__(self) -> None:
            self.threads: set[str] = set()

        def set_thread_count(self, count: int) -> None:
            events.append(f"dispatcher-start-{count}")

        def shutdown(self, *, timeout: float) -> bool:
            assert 0.0 <= timeout <= max(0.0, deadline - time.monotonic()) + 0.01
            events.append("dispatcher-shutdown")
            self.threads.clear()
            return True

    dispatcher = Dispatcher()
    flask_app = Flask("desktop-waitress-bind-failure")
    flask_app.config["AUDIT"] = SimpleNamespace(close=lambda: events.append("audit-close"))
    _stub_desktop_shutdown_dependencies(monkeypatch)
    monkeypatch.setattr(desktop, "_build_app", lambda: flask_app)
    monkeypatch.setattr("waitress.task.ThreadedTaskDispatcher", lambda: dispatcher)

    def fail_bind(
        _app: object,
        map: dict[object, object] | None = None,  # noqa: A002 - Waitress API name
        _dispatcher: Dispatcher | None = None,
        **_kwargs: object,
    ) -> None:
        events.append("bind")
        if map is not None:
            map[1] = PartialChannel()
        if _dispatcher is not None:
            _dispatcher.threads.add("partial-worker")
        raise ExternalBindError(f"socket provider rejected {secret}")

    monkeypatch.setattr("waitress.server.create_server", fail_bind)

    with pytest.raises(
        RuntimeError,
        match=r"Desktop backend startup failed \(ExternalBindError\)",
    ) as raised:
        desktop._serve_owned(
            5100,
            ready_writer=lambda _message: events.append("ready"),
            shutdown_deadline=deadline,
        )

    rendered = "".join(traceback.format_exception(raised.value))
    assert secret not in rendered
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert "ready" not in events
    assert "partial-channel-close" in events
    assert "dispatcher-shutdown" in events
    assert dispatcher.threads == set()
    assert events.index("partial-channel-close") < events.index("dispatcher-shutdown")
    assert events.index("dispatcher-shutdown") < events.index("audit-close")


@pytest.mark.unit
def test_desktop_shutdown_owns_waitress_dispatcher_inside_absolute_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    deadline = time.monotonic() + 1.0

    class Dispatcher:
        def __init__(self) -> None:
            self.threads: set[str] = set()

        def set_thread_count(self, count: int) -> None:
            assert count == 8
            self.threads.add("worker")
            events.append("dispatcher-start")

        def shutdown(self, *, timeout: float) -> bool:
            assert 0.0 <= timeout <= max(0.0, deadline - time.monotonic()) + 0.01
            events.append("dispatcher-shutdown")
            self.threads.clear()
            return True

    dispatcher = Dispatcher()
    tracker = SimpleNamespace(
        wait_for_idle=lambda _timeout: events.append("requests-drained") or True,
    )
    flask_app = Flask("desktop-waitress-dispatcher-shutdown")
    flask_app.config.update(
        AUDIT=SimpleNamespace(close=lambda: events.append("audit-close")),
        RUNTIME_REQUEST_TRACKER=tracker,
    )
    server = SimpleNamespace(
        effective_port=5100,
        run=lambda: events.append("serve"),
        close=lambda: events.append("server-close"),
    )
    _stub_desktop_shutdown_dependencies(monkeypatch)
    monkeypatch.setattr(desktop, "_build_app", lambda: flask_app)
    monkeypatch.setattr(desktop, "_close_runtime_request_admission", lambda _app: tracker)
    monkeypatch.setattr("waitress.task.ThreadedTaskDispatcher", lambda: dispatcher)

    def create_server(
        _app: object,
        map: dict[object, object] | None = None,  # noqa: A002 - Waitress API name
        _dispatcher: Dispatcher | None = None,
        **_kwargs: object,
    ) -> object:
        assert map == {}
        assert _dispatcher is dispatcher
        events.append("server-created")
        return server

    monkeypatch.setattr("waitress.server.create_server", create_server)

    desktop._serve_owned(
        5100,
        ready_writer=lambda _message: events.append("ready"),
        shutdown_deadline=deadline,
    )

    assert dispatcher.threads == set()
    assert events.index("server-created") < events.index("dispatcher-start")
    assert events.index("dispatcher-start") < events.index("ready") < events.index("serve")
    assert events.index("server-close") < events.index("requests-drained")
    assert events.index("requests-drained") < events.index("dispatcher-shutdown")
    assert events.index("dispatcher-shutdown") < events.index("audit-close")


@pytest.mark.unit
def test_desktop_does_not_start_an_already_running_rotation_scheduler_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class RunningScheduler:
        running = True

        def start(self) -> None:
            events.append("unexpected-restart")

        def shutdown(self, *, wait: bool) -> None:
            assert wait is False
            events.append("scheduler-stop")
            self.running = False

    flask_app = Flask("desktop-rotation-already-running")
    flask_app.config["ROTATION_SCHEDULER"] = RunningScheduler()
    server = SimpleNamespace(effective_port=5100, run=lambda: events.append("serve"), close=lambda: None)
    _stub_desktop_shutdown_dependencies(monkeypatch)
    monkeypatch.setattr(desktop, "_build_app", lambda: flask_app)
    monkeypatch.setattr("waitress.server.create_server", lambda *_args, **_kwargs: server)

    desktop._serve_owned(5100, ready_writer=lambda _message: events.append("ready"))

    assert events == ["ready", "serve", "scheduler-stop"]


@pytest.mark.unit
def test_desktop_quiesces_ditto_before_each_router_retirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    flask_app = Flask("desktop-ditto-shutdown")
    flask_app.config["DITTO_RUNTIME"] = object()
    server = SimpleNamespace(
        effective_port=5100,
        run=lambda: events.append("serve"),
        close=lambda: events.append("server-close"),
    )
    _stub_desktop_shutdown_dependencies(monkeypatch)
    monkeypatch.setattr(desktop, "_build_app", lambda: flask_app)
    monkeypatch.setattr("waitress.server.create_server", lambda *_args, **_kwargs: server)
    monkeypatch.setattr(
        desktop,
        "shutdown_ditto_runtime",
        lambda _app, **_kwargs: events.append("ditto") or True,
    )
    monkeypatch.setattr(
        desktop,
        "retire_broker_router_generation",
        lambda _app: events.append("router") or True,
    )

    desktop._serve_owned(5100, ready_writer=lambda _message: events.append("ready"))

    assert events == [
        "ready",
        "serve",
        "server-close",
        "ditto",
        "router",
        "ditto",
        "router",
    ]


@pytest.mark.unit
def test_desktop_shutdown_passes_only_one_absolute_deadline_remaining_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, float]] = []
    deadline = time.monotonic() + 0.5

    def record_timeout(label: str, timeout: float) -> bool:
        observed.append((label, timeout))
        remaining = max(0.0, deadline - time.monotonic())
        assert 0.0 <= timeout <= remaining + 0.01
        return True

    tracker = SimpleNamespace(
        wait_for_idle=lambda timeout: record_timeout("requests", timeout),
    )
    runtime = SimpleNamespace(
        _desktop_deadline_aware_shutdown=True,
        stop=lambda **kwargs: record_timeout("tick-stop", kwargs["timeout"]),
        close_storage=lambda **kwargs: record_timeout("tick-storage", kwargs["timeout"]),
    )
    flask_app = Flask("desktop-single-shutdown-deadline")
    flask_app.config.update(
        DESKTOP_TICK_CAPTURE_RUNTIME=runtime,
        RUNTIME_REQUEST_TRACKER=tracker,
    )
    server = SimpleNamespace(effective_port=5100, run=lambda: None, close=lambda: None)

    monkeypatch.setattr(desktop, "_build_app", lambda: flask_app)
    monkeypatch.setattr("waitress.server.create_server", lambda *_args, **_kwargs: server)
    monkeypatch.setattr(desktop, "_close_runtime_request_admission", lambda _app: tracker)
    monkeypatch.setattr(
        "flinttrade_core.smart_order_routes.shutdown_smart_order_jobs",
        lambda *, timeout: record_timeout("smart", timeout),
    )
    monkeypatch.setattr(
        "flinttrade_core.agent_routes.shutdown_agent_runtime",
        lambda _app, *, timeout: record_timeout("agent", timeout),
    )
    monkeypatch.setattr(
        "flinttrade_engine.strategy_routes.shutdown_strategy_runtime",
        lambda _app: None,
    )
    monkeypatch.setattr(
        desktop,
        "shutdown_ditto_runtime",
        lambda _app, *, timeout: record_timeout("ditto", timeout),
    )
    monkeypatch.setattr(desktop, "retire_broker_router_generation", lambda _app: True)
    monkeypatch.setattr(
        "flinttrade_core.local_ai_routes.shutdown_local_ai_runtime",
        lambda _app, *, timeout: record_timeout("local-ai", timeout),
    )

    desktop._serve_owned(
        5100,
        ready_writer=lambda _message: None,
        shutdown_deadline=deadline,
    )

    assert [label for label, _timeout in observed] == [
        "local-ai",
        "smart",
        "agent",
        "ditto",
        "tick-stop",
        "requests",
        "ditto",
        "tick-storage",
    ]


@pytest.mark.unit
def test_desktop_stops_local_ai_before_and_independently_of_a_later_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    flask_app = Flask("desktop-local-ai-first-shutdown")
    tracker = SimpleNamespace(wait_for_idle=lambda _timeout: True)
    flask_app.config["RUNTIME_REQUEST_TRACKER"] = tracker
    owner = desktop._DesktopShutdownRecoveryOwner(flask_app)

    monkeypatch.setattr(desktop, "_close_runtime_request_admission", lambda _app: tracker)
    monkeypatch.setattr(
        "flinttrade_core.log_stream.shutdown_log_streams",
        lambda _app: None,
    )
    monkeypatch.setattr(
        "flinttrade_core.local_ai_routes.shutdown_local_ai_runtime",
        lambda _app, **_kwargs: events.append("local-ai") or True,
    )
    monkeypatch.setattr(
        "flinttrade_core.smart_order_routes.shutdown_smart_order_jobs",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        "flinttrade_core.agent_routes.shutdown_agent_runtime",
        lambda _app, **_kwargs: True,
    )

    def fail_strategy(_app: Flask) -> None:
        events.append("strategy")
        raise RuntimeError("injected strategy shutdown failure")

    monkeypatch.setattr(
        "flinttrade_engine.strategy_routes.shutdown_strategy_runtime",
        fail_strategy,
    )
    monkeypatch.setattr(desktop, "_shutdown_rotation_scheduler", lambda _app: None)
    monkeypatch.setattr(desktop, "shutdown_ditto_runtime", lambda _app, **_kwargs: True)
    monkeypatch.setattr(desktop, "retire_broker_router_generation", lambda _app: True)

    assert owner._shutdown(time.monotonic() + 0.5) is False
    assert events == ["local-ai", "strategy"]


@pytest.mark.unit
def test_desktop_expired_shutdown_invokes_zero_budget_local_ai_without_claiming_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoked = threading.Event()
    observed_timeouts: list[float] = []
    flask_app = Flask("desktop-expired-local-ai-shutdown")
    owner = desktop._DesktopShutdownRecoveryOwner(flask_app)

    def stop_local_ai(_app: Flask, *, timeout: float) -> bool:
        observed_timeouts.append(timeout)
        invoked.set()
        return True

    monkeypatch.setattr(
        "flinttrade_core.local_ai_routes.shutdown_local_ai_runtime",
        stop_local_ai,
    )

    assert owner._shutdown(time.monotonic() - 1.0) is False
    assert invoked.wait(timeout=1.0)
    assert observed_timeouts == [0.0]
    assert "local-ai" not in owner._completed


@pytest.mark.unit
def test_desktop_expired_shutdown_bounds_a_blocked_local_ai_root_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    owner = desktop._DesktopShutdownRecoveryOwner(Flask("desktop-blocked-local-ai-root"))

    def block_local_ai(_app: Flask, *, timeout: float) -> bool:
        assert timeout == 0.0
        entered.set()
        release.wait(timeout=1.0)
        return True

    monkeypatch.setattr(
        "flinttrade_core.local_ai_routes.shutdown_local_ai_runtime",
        block_local_ai,
    )

    started = time.monotonic()
    try:
        assert owner._shutdown(started - 1.0) is False
        assert time.monotonic() - started < 0.1
        assert entered.wait(timeout=1.0)
        assert "local-ai" not in owner._completed
    finally:
        release.set()


@pytest.mark.unit
def test_desktop_local_ai_finishing_at_the_deadline_remains_unproved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    observed_timeouts: list[float] = []
    owner = desktop._DesktopShutdownRecoveryOwner(Flask("desktop-local-ai-at-deadline"))
    monkeypatch.setattr(desktop.time, "monotonic", lambda: clock[0])

    def finish_at_deadline(_app: Flask, *, timeout: float) -> bool:
        observed_timeouts.append(timeout)
        clock[0] = 1.0
        return True

    monkeypatch.setattr(
        "flinttrade_core.local_ai_routes.shutdown_local_ai_runtime",
        finish_at_deadline,
    )

    assert owner._shutdown(1.0) is False
    assert observed_timeouts == [1.0]
    assert "local-ai" not in owner._completed


@pytest.mark.unit
def test_desktop_shutdown_timeout_retains_exact_owner_and_rejoins_one_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy_started = threading.Event()
    release_strategy = threading.Event()
    strategy_calls: list[int] = []
    failures: list[BaseException] = []
    lease = MagicMock()
    retain_lease = MagicMock()
    release_lease = MagicMock()

    def shutdown_strategy(_app: Flask) -> None:
        strategy_calls.append(len(strategy_calls) + 1)
        if len(strategy_calls) == 1:
            strategy_started.set()
            assert release_strategy.wait(timeout=2)

    tracker = SimpleNamespace(wait_for_idle=lambda _timeout: True)
    flask_app = Flask("desktop-retained-shutdown-owner")
    flask_app.config["RUNTIME_REQUEST_TRACKER"] = tracker
    server = SimpleNamespace(effective_port=5100, run=lambda: None, close=lambda: None)

    monkeypatch.setattr(desktop, "_build_app", lambda: flask_app)
    monkeypatch.setattr("waitress.server.create_server", lambda *_args, **_kwargs: server)
    monkeypatch.setattr(desktop, "_close_runtime_request_admission", lambda _app: tracker)
    monkeypatch.setattr(
        "flinttrade_core.log_stream.shutdown_log_streams",
        lambda _app: None,
    )
    monkeypatch.setattr(
        "flinttrade_core.smart_order_routes.shutdown_smart_order_jobs",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        "flinttrade_core.agent_routes.shutdown_agent_runtime",
        lambda _app, **_kwargs: True,
    )
    monkeypatch.setattr(
        "flinttrade_engine.strategy_routes.shutdown_strategy_runtime",
        shutdown_strategy,
    )
    monkeypatch.setattr(desktop, "_shutdown_rotation_scheduler", lambda _app: None)
    monkeypatch.setattr(desktop, "shutdown_ditto_runtime", lambda _app, **_kwargs: True)
    monkeypatch.setattr(desktop, "retire_broker_router_generation", lambda _app: True)
    monkeypatch.setattr(
        "flinttrade_core.local_ai_routes.shutdown_local_ai_runtime",
        lambda _app, **_kwargs: True,
    )
    monkeypatch.setattr(desktop, "acquire_backend_instance_lease", lambda: lease)
    monkeypatch.setattr(desktop, "retain_backend_instance_lease", retain_lease)
    monkeypatch.setattr(
        desktop,
        "release_retained_backend_instance_lease",
        release_lease,
        raising=False,
    )

    def run_serve() -> None:
        try:
            desktop.serve(
                5100,
                ready_writer=lambda _message: None,
                shutdown_deadline=time.monotonic() + 0.02,
            )
        except BaseException as exc:  # noqa: BLE001 - asserted below
            failures.append(exc)

    serve_thread = threading.Thread(target=run_serve)
    serve_thread.start()
    assert strategy_started.wait(timeout=1)
    serve_thread.join(timeout=0.2)
    try:
        assert serve_thread.is_alive() is False
        assert len(failures) == 1
        failure = failures[0]
        assert isinstance(failure, desktop.DesktopBackendShutdownIncomplete)
        owner = failure.recovery_owner
        assert owner.app is flask_app
        lease.retain_recovery_owner.assert_called_once_with(owner)
        retain_lease.assert_called_once_with(lease)
        lease.release.assert_not_called()

        with pytest.raises(desktop.DesktopBackendShutdownIncomplete) as retried:
            owner.release(deadline=time.monotonic() + 0.02)
        assert retried.value.recovery_owner is owner
        assert strategy_calls == [1]
        lease.release.assert_not_called()

        release_strategy.set()
        owner.release(deadline=time.monotonic() + 1.0)

        assert strategy_calls == [1, 2]
        release_lease.assert_called_once_with(lease)
        lease.release.assert_not_called()
    finally:
        release_strategy.set()
        serve_thread.join(timeout=2)


@pytest.mark.unit
def test_admission_close_failure_retains_backend_ownership_and_continues_teardown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = MagicMock()
    flask_app = Flask("desktop-admission-close-failure")
    flask_app.config["DESKTOP_TICK_CAPTURE_RUNTIME"] = runtime
    server = MagicMock(effective_port=5100)
    lease = MagicMock()
    retain_lease = MagicMock()
    _stub_desktop_shutdown_dependencies(monkeypatch)
    monkeypatch.setattr(desktop, "_build_app", lambda: flask_app)
    monkeypatch.setattr("waitress.server.create_server", lambda *_args, **_kwargs: server)
    monkeypatch.setattr(
        desktop,
        "_close_runtime_request_admission",
        MagicMock(side_effect=RuntimeError("request admission close failed")),
    )
    monkeypatch.setattr(desktop, "acquire_backend_instance_lease", lambda: lease)
    monkeypatch.setattr(desktop, "retain_backend_instance_lease", retain_lease)

    with pytest.raises(
        desktop.DesktopBackendShutdownIncomplete,
        match="backend shutdown failed",
    ) as raised:
        desktop.serve(5100, ready_writer=lambda _message: None)

    owner = raised.value.recovery_owner
    assert owner.app is flask_app
    assert flask_app.config["RUNTIME_ACCEPTING_REQUESTS"] is False
    server.close.assert_called_once_with()
    runtime.stop.assert_called_once_with()
    lease.retain_recovery_owner.assert_called_once_with(owner)
    retain_lease.assert_called_once_with(lease)
    lease.release.assert_not_called()


@pytest.mark.unit
def test_desktop_build_failure_rolls_back_acquired_owners_in_reverse_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    secret = "external-startup-secret"

    class ExternalStartupError(RuntimeError):
        pass

    _stub_transactional_build(monkeypatch, events)
    desktop._configure_tick_capture.side_effect = ExternalStartupError(
        f"provider rejected {secret}"
    )

    with pytest.raises(
        RuntimeError,
        match=r"Desktop backend startup failed \(ExternalStartupError\)",
    ) as raised:
        desktop._build_app()

    rendered = "".join(traceback.format_exception(raised.value))
    assert secret not in rendered
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    rollback = [event for event in events if event.endswith(("-stop", "-close"))]
    assert rollback == ["local-ai-stop", "smart-stop", "client-close", "audit-close"]


@pytest.mark.unit
def test_desktop_startup_rollback_stops_local_ai_before_a_blocking_admission_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.local_ai_routes as local_ai_routes

    events: list[str] = []
    admission_entered = threading.Event()
    release_admission = threading.Event()
    flask_app = Flask("desktop-startup-local-ai-first")
    owner = desktop._DesktopStartupRollbackRecoveryOwner(
        flask_app,
        client=None,
        audit=None,
        local_ai_attempted=True,
        smart_order_started=False,
        startup_error_context="RuntimeError",
    )

    def stop_local_ai(runtime_app: Flask, *, timeout: float) -> bool:
        assert runtime_app.config["RUNTIME_ACCEPTING_REQUESTS"] is False
        assert 0.0 <= timeout <= 5.0
        events.append("local-ai")
        return True

    def block_admission(_app: Flask) -> None:
        events.append("admission-entered")
        admission_entered.set()
        assert release_admission.wait(timeout=1.0)

    monkeypatch.setattr(local_ai_routes, "shutdown_local_ai_runtime", stop_local_ai)
    monkeypatch.setattr(desktop, "_close_runtime_request_admission", block_admission)
    monkeypatch.setattr(desktop, "shutdown_ditto_runtime", lambda _app, **_kwargs: True)
    monkeypatch.setattr(desktop, "retire_broker_router_generation", lambda _app: True)
    result: list[bool] = []
    rollback_thread = threading.Thread(
        target=lambda: result.append(owner.attempt_rollback(deadline=time.monotonic() + 1.0)),
    )
    rollback_thread.start()
    try:
        assert admission_entered.wait(timeout=1.0)
        assert events == ["local-ai", "admission-entered"]
    finally:
        release_admission.set()
        rollback_thread.join(timeout=1.0)

    assert result == [True]


@pytest.mark.unit
def test_desktop_expired_startup_rollback_invokes_zero_budget_local_ai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.local_ai_routes as local_ai_routes

    invoked = threading.Event()
    observed_timeouts: list[float] = []
    owner = desktop._DesktopStartupRollbackRecoveryOwner(
        Flask("desktop-expired-startup-local-ai"),
        client=None,
        audit=None,
        local_ai_attempted=True,
        smart_order_started=False,
        startup_error_context="RuntimeError",
    )

    def stop_local_ai(_app: Flask, *, timeout: float) -> bool:
        observed_timeouts.append(timeout)
        invoked.set()
        return True

    monkeypatch.setattr(local_ai_routes, "shutdown_local_ai_runtime", stop_local_ai)

    assert owner.attempt_rollback(deadline=time.monotonic() - 1.0) is False
    assert invoked.wait(timeout=1.0)
    assert observed_timeouts == [0.0]
    assert owner._rollback_complete is False


@pytest.mark.unit
def test_desktop_startup_local_ai_retry_does_not_repeat_proved_other_teardown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.local_ai_routes as local_ai_routes

    events: list[str] = []
    local_ai_results = iter((False, True))
    audit = SimpleNamespace(close=lambda: events.append("audit-close"))
    flask_app = Flask("desktop-startup-local-ai-retry")
    owner = desktop._DesktopStartupRollbackRecoveryOwner(
        flask_app,
        client=None,
        audit=audit,
        local_ai_attempted=True,
        smart_order_started=False,
        startup_error_context="RuntimeError",
    )
    monkeypatch.setattr(
        local_ai_routes,
        "shutdown_local_ai_runtime",
        lambda _app, **_kwargs: events.append("local-ai") or next(local_ai_results),
    )
    monkeypatch.setattr(
        desktop,
        "_close_runtime_request_admission",
        lambda _app: events.append("admission-close"),
    )
    monkeypatch.setattr(
        desktop,
        "shutdown_ditto_runtime",
        lambda _app, **_kwargs: events.append("ditto-stop") or True,
    )
    monkeypatch.setattr(
        desktop,
        "retire_broker_router_generation",
        lambda _app: events.append("router-retire") or True,
    )

    assert owner.attempt_rollback(deadline=time.monotonic() + 1.0) is False
    assert owner.attempt_rollback(deadline=time.monotonic() + 1.0) is True
    assert events == [
        "local-ai",
        "admission-close",
        "ditto-stop",
        "router-retire",
        "audit-close",
        "local-ai",
    ]


@pytest.mark.unit
def test_desktop_build_retains_recovery_owner_when_reverse_rollback_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    flask_app = _stub_transactional_build(
        monkeypatch,
        events,
        smart_shutdown_complete=False,
    )

    with pytest.raises(desktop.DesktopBackendShutdownIncomplete) as raised:
        desktop._build_app()

    owner = raised.value.recovery_owner
    assert owner is not flask_app
    assert callable(getattr(owner, "release", None))
    assert str(raised.value) == "Desktop backend startup rollback failed (RuntimeError)"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert "smart-stop" in events
    assert "local-ai-stop" in events
    assert "client-close" not in events
    assert "audit-close" not in events

    import flinttrade_core.smart_order_routes as smart_order_routes

    monkeypatch.setattr(
        smart_order_routes,
        "shutdown_smart_order_jobs",
        lambda **_kwargs: events.append("smart-retry") or True,
    )
    owner.release(deadline=time.monotonic() + 1.0)

    assert "smart-retry" in events
    assert events[-2:] == ["client-close", "audit-close"]


@pytest.mark.unit
def test_desktop_pre_app_rollback_retains_executable_owner_without_secret_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.config as config_module
    import flinttrade_core.openalgo_client as client_module
    import flinttrade_data.audit_logger as audit_module

    events: list[str] = []
    secret = "factory-provider-secret"
    close_attempts = 0

    class ExternalFactoryError(RuntimeError):
        pass

    class Audit:
        def log_event(self, _event: str) -> None:
            return None

        def close(self) -> None:
            events.append("audit-close")

    class Client:
        def __init__(self, _settings: object) -> None:
            return None

    def close_client(_client: object) -> None:
        nonlocal close_attempts
        close_attempts += 1
        events.append(f"client-close-{close_attempts}")
        if close_attempts == 1:
            raise RuntimeError("transient client close failure")

    monkeypatch.setattr(audit_module, "AuditLogger", Audit)
    monkeypatch.setattr(config_module.Settings, "from_env", staticmethod(lambda: object()))
    monkeypatch.setattr(client_module, "OpenAlgoClient", Client)
    monkeypatch.setattr(desktop, "client_close_sync", close_client)
    monkeypatch.setattr(
        desktop,
        "create_flask_app",
        MagicMock(side_effect=ExternalFactoryError(f"factory rejected {secret}")),
    )

    with pytest.raises(desktop.DesktopBackendShutdownIncomplete) as raised:
        desktop._build_app()

    owner = raised.value.recovery_owner
    rendered = "".join(traceback.format_exception(raised.value))
    assert not isinstance(owner, tuple)
    assert callable(getattr(owner, "release", None))
    assert str(raised.value) == "Desktop backend startup rollback failed (ExternalFactoryError)"
    assert secret not in rendered
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None

    owner.release(deadline=time.monotonic() + 1.0)

    assert close_attempts == 2
    assert events == ["client-close-1", "audit-close", "client-close-2", "audit-close"]


@pytest.mark.unit
def test_desktop_construction_diagnostics_expose_classes_not_external_payloads(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.config as config_module
    import flinttrade_core.local_ai_routes as local_ai_routes
    import flinttrade_core.openalgo_client as client_module
    import flinttrade_core.smart_order_routes as smart_order_routes
    import flinttrade_data.audit_logger as audit_module

    audit_secret = "audit-construction-secret"
    client_secret = "client-construction-secret"

    class ExternalAuditError(RuntimeError):
        pass

    class ExternalClientError(RuntimeError):
        pass

    def fail_audit() -> None:
        raise ExternalAuditError(f"audit failed with {audit_secret}")

    def fail_client(_settings: object) -> None:
        raise ExternalClientError(f"client failed with {client_secret}")

    flask_app = Flask("desktop-construction-diagnostics")
    flask_app.config["SAFETY_CONFIG_READY"] = False
    monkeypatch.setattr(audit_module, "AuditLogger", fail_audit)
    monkeypatch.setattr(config_module.Settings, "from_env", staticmethod(lambda: object()))
    monkeypatch.setattr(client_module, "OpenAlgoClient", fail_client)
    monkeypatch.setattr(desktop, "create_flask_app", lambda **_kwargs: flask_app)
    monkeypatch.setattr(local_ai_routes, "start_configured_local_ai_runtime", lambda _app: True)
    monkeypatch.setattr(smart_order_routes, "start_smart_order_jobs", lambda: True)
    monkeypatch.setattr(desktop, "_configure_tick_capture", lambda *_args, **_kwargs: None)

    assert desktop._build_app() is flask_app

    stderr = capsys.readouterr().err
    assert audit_secret not in stderr
    assert client_secret not in stderr
    assert "ExternalAuditError" in stderr
    assert "ExternalClientError" in stderr


@pytest.mark.unit
def test_desktop_safety_construction_diagnostic_omits_external_payload(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.config as config_module
    import flinttrade_core.local_ai_routes as local_ai_routes
    import flinttrade_core.openalgo_client as client_module
    import flinttrade_core.smart_order_routes as smart_order_routes
    import flinttrade_data.audit_logger as audit_module

    safety_secret = "safety-construction-secret"

    class ExternalSafetyError(RuntimeError):
        pass

    safety = object()
    flask_app = Flask("desktop-safety-construction-diagnostic")
    flask_app.config.update(SAFETY_CONFIG_READY=True, SAFETY=safety)
    monkeypatch.setattr(audit_module, "AuditLogger", MagicMock)
    monkeypatch.setattr(config_module.Settings, "from_env", staticmethod(lambda: object()))
    monkeypatch.setattr(client_module, "OpenAlgoClient", lambda _settings: object())
    monkeypatch.setattr(desktop, "create_flask_app", lambda **_kwargs: flask_app)
    monkeypatch.setattr(local_ai_routes, "start_configured_local_ai_runtime", lambda _app: True)
    monkeypatch.setattr(smart_order_routes, "start_smart_order_jobs", lambda: True)
    monkeypatch.setattr(desktop, "_configure_tick_capture", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        desktop,
        "_bind_desktop_safety_runtime",
        MagicMock(side_effect=ExternalSafetyError(f"safety failed with {safety_secret}")),
    )

    assert desktop._build_app() is flask_app

    stderr = capsys.readouterr().err
    assert safety_secret not in stderr
    assert "ExternalSafetyError" in stderr


@pytest.mark.unit
def test_desktop_serve_retains_lease_when_build_rollback_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease = MagicMock()
    retain = MagicMock()
    failure = desktop.DesktopBackendShutdownIncomplete("desktop build rollback incomplete")
    monkeypatch.setattr(desktop, "_build_app", MagicMock(side_effect=failure))
    monkeypatch.setattr(desktop, "acquire_backend_instance_lease", lambda: lease)
    monkeypatch.setattr(desktop, "retain_backend_instance_lease", retain)

    with pytest.raises(desktop.DesktopBackendShutdownIncomplete):
        desktop.serve(5100)

    retain.assert_called_once_with(lease)
    lease.release.assert_not_called()


@pytest.mark.unit
def test_ensure_workspace_does_not_replace_corrupt_existing_config(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "workspace.json"
    corrupt_content = '{"version": "1.1.0", "safety": '
    config_path.write_text(corrupt_content, encoding="utf-8")
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))

    workspace = desktop._ensure_workspace()

    assert workspace.config_path == config_path
    assert config_path.read_text(encoding="utf-8") == corrupt_content


@pytest.mark.unit
def test_desktop_safety_wiring_reuses_client_loop_for_nonblocking_native_mtm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Native MTM reaches the desktop-owned breaker without creating another loop."""
    from flinttrade_core.l2_state import PortfolioSafetyState
    from flinttrade_core.native_account_routes import _submit_live_positions_mtm
    from flinttrade_engine.safety import SafetySystem, set_safety_gate_secret

    class ClientLoopOwner:
        def __init__(self) -> None:
            self.loop = asyncio.new_event_loop()
            self.ensure_calls = 0
            self._thread = threading.Thread(target=self.loop.run_forever, name="desktop-owner-loop")
            self._thread.start()

        def _ensure_owner_loop(self) -> asyncio.AbstractEventLoop:
            self.ensure_calls += 1
            return self.loop

        def run_sync(self, awaitable):
            return asyncio.run_coroutine_threadsafe(awaitable, self.loop).result(timeout=2)

        def close(self) -> None:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self._thread.join(timeout=2)
            self.loop.close()

    class Router:
        def __init__(self) -> None:
            self.writes: list[dict] = []
            self.called = threading.Event()

        @property
        def registered_selectors(self) -> tuple[str, ...]:
            return ("upstox:primary",)

        @property
        def configured_selectors(self) -> tuple[str, ...]:
            return ("upstox:primary",)

        def authorised_selectors(self, actor_id: str) -> tuple[str, ...]:
            assert actor_id == "operator"
            return ("upstox:primary",)

        async def plan_emergency_reduction(self, _request_ctx, *, policy, **_kwargs):
            from flinttrade_engine.safety import EmergencyBrokerWrite, EmergencyReductionPlan

            if self.writes:
                return EmergencyReductionPlan(writes=(), pending_verbs=frozenset())
            return EmergencyReductionPlan(
                writes=(
                    EmergencyBrokerWrite(
                        parent_verb="exit_all_positions",
                        verb="exit_all_positions",
                        payload={"_op": "exit_all_positions"},
                    ),
                ),
                pending_verbs=frozenset(policy.verbs),
            )

        async def execute_gated(self, request_ctx, **kwargs):
            self.writes.append({"request_ctx": request_ctx, **kwargs})
            self.called.set()
            return {"order_ids": [], "errors": [], "total": 0, "success": 0}

    client = ClientLoopOwner()
    router = Router()
    safety = SafetySystem()
    app = Flask("desktop-mtm-wiring")
    rebuild_readiness: list[tuple[bool, object | None]] = []

    def preserve_injected_router(flask_app, *_args) -> bool:
        rebuild_readiness.append(
            (
                flask_app.config.get("EMERGENCY_RUNTIME_READY") is True,
                flask_app.config.get("EMERGENCY_DISPATCHER"),
            )
        )
        return True

    monkeypatch.setattr(desktop, "configure_broker_router", preserve_injected_router)
    app.config.update(
        AUTH_SERVICE=SimpleNamespace(get_profile=lambda: {"username": "operator"}),
        BROKER_ROUTER=router,
        SAFETY=safety,
    )
    set_safety_gate_secret(b"desktop-mtm-safety-secret-0123456789")
    try:
        dispatcher = desktop._bind_desktop_safety_runtime(app, safety, client)
        with app.app_context():
            started = time.monotonic()
            _submit_live_positions_mtm(
                PortfolioSafetyState(
                    positions=[],
                    used_margin=0.0,
                    total_balance=100000.0,
                    daily_pnl=-60000.0,
                    starting_capital=100000.0,
                ),
                adapter_id="upstox",
                account_id="primary",
            )
            assert time.monotonic() - started < 0.1

        assert router.called.wait(timeout=2)
        deadline = time.monotonic() + 2
        while safety.mtm_circuit_breaker.last_emergency_result is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert safety.mtm_circuit_breaker.is_triggered
        assert safety.mtm_circuit_breaker.last_emergency_result is not None
        assert router.writes[0]["verb"] == "exit_all_positions"
        assert dispatcher is app.config["EMERGENCY_DISPATCHER"]
        assert rebuild_readiness == [(True, dispatcher)]
        assert safety._runtime_loop is client.loop
        assert client.ensure_calls == 1
    finally:
        safety.unbind_runtime_loop(client.loop)
        client.close()
