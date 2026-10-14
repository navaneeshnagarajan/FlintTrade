"""Production factory composition and exact retained lifecycle custody."""
from __future__ import annotations

import secrets
import time

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def inert_external_downloads(monkeypatch):
    import urllib.request
    from urllib.error import URLError
    from urllib.parse import urlsplit

    original = urllib.request.urlopen

    def transport(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else request
        if urlsplit(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise URLError("synthetic external transport unavailable")
        return original(request, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", transport)


@pytest.fixture
def fresh_lease(tmp_path, monkeypatch):
    from flinttrade_core.backend_instance import acquire_backend_instance_lease
    from flinttrade_core.maintenance_history import initialise_fresh_history

    monkeypatch.setenv("HOME", str(tmp_path))
    workspace = tmp_path / ".flinttrade"
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("FLINTTRADE_INSTALLATION_STATE_DIR", str(tmp_path / ".flinttrade-installation"))
    lease = acquire_backend_instance_lease()
    assert initialise_fresh_history(workspace, lease)
    try:
        yield lease
    finally:
        lease.release()


@pytest.fixture
def owned_factory(fresh_lease):
    from flinttrade_core.app import create_flask_app
    from flinttrade_core.auth_routes import _create_token
    from flinttrade_core.desktop import _DesktopShutdownRecoveryOwner

    app = create_flask_app(backend_lease_proof=fresh_lease.proof)
    app.config["AUTH_SERVICE"].setup_account("operator", "operator@example.invalid", secrets.token_urlsafe(32))
    with app.app_context():
        token = _create_token("operator")
    try:
        yield app, {"Authorization": "Bearer " + token}
    finally:
        recovery = app.extensions.setdefault("test.release", _DesktopShutdownRecoveryOwner(app))
        recovery.release(deadline=time.monotonic() + 10)


def test_unproved_normal_factory_stays_read_only_and_closes_without_inventing_history(tmp_path, monkeypatch):
    from flinttrade_core import app as core, desktop

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    app = core.create_flask_app()
    protection = app.config["PROTECTION_SERVICES"]
    data = app.config["DATA_RUNTIME"]
    assert "EXECUTION_SESSIONS" not in app.config
    assert "flinttrade.maintenance" not in app.extensions
    assert not protection.maintenance_snapshot()["registry_complete"]
    desktop._DesktopShutdownRecoveryOwner(app).release(deadline=time.monotonic() + 8)
    assert protection._closed and data.closed
    assert not (tmp_path / "protection.sqlite").exists()
    assert not (tmp_path / "execution-sessions").exists()


def test_normal_factory_opens_execution_census_and_mounts_public_controls(owned_factory):
    from flinttrade_ai.run_store import AgentRunStore
    from flinttrade_core.execution_sessions import ExecutionSessions
    from flinttrade_core.protection_grants import ProtectionServices
    from flinttrade_engine.scheduler import StrategyScheduler

    app, headers = owned_factory
    assert isinstance(app.config.get("PROTECTION_SERVICES"), ProtectionServices)
    assert isinstance(app.config.get("EXECUTION_SESSIONS"), ExecutionSessions)
    assert isinstance(app.config.get("PRACTICE_AGENT_RUN_STORE"), AgentRunStore)
    assert isinstance(app.config.get("SCHEDULER"), StrategyScheduler)
    client = app.test_client()
    response = client.get("/api/v1/execution-sessions", headers=headers)
    assert response.status_code == 200, response.json
    assert response.json["data"] == []
    assert response.headers["Cache-Control"] == "no-store"
    response = client.get("/v1/model-runs/missing/configuration", headers=headers)
    assert response.status_code == 403, response.json
    assert response.json["code"] == "run_not_owned"
    # Mounted protection guard, not SPA fallback; no grant or action issued.
    response = client.post("/api/v1/protection/grants", json={})
    assert response.status_code == 401, response.json
    assert "/api/v1/protection/grants" in {rule.rule for rule in app.url_map.iter_rules()}
    assert "flinttrade.maintenance" not in app.extensions
    assert "SERVICE_TASK_DISPATCHER" not in app.config


@pytest.mark.parametrize("kind", ["desktop", "async"])
def test_factory_execution_shutdown_timeout_keeps_exact_worker_and_dependencies(owned_factory, monkeypatch, kind):
    import asyncio
    import threading
    from flinttrade_core.desktop import DesktopBackendShutdownIncomplete, _DesktopShutdownRecoveryOwner
    from packages.core.core.tests.test_runtime_lifecycle import _runtime_app

    app, _ = owned_factory
    sessions = app.config["EXECUTION_SESSIONS"]
    dependencies = {key: app.config[key] for key in ("PROTECTION_SERVICES", "MODEL_RUN_SERVICES", "DATA_RUNTIME", "KNOWLEDGE_RUNTIME")}
    entered, finish = threading.Event(), threading.Event()
    calls = []
    shutdown = sessions.shutdown

    def held_shutdown(timeout):
        calls.append(threading.current_thread())
        entered.set()
        assert finish.wait(8)
        return shutdown(timeout)

    monkeypatch.setattr(sessions, "shutdown", held_shutdown)
    if kind == "desktop":
        owner = _DesktopShutdownRecoveryOwner(app)
        app.extensions["test.release"] = owner

        async def stop(timeout):
            await asyncio.to_thread(owner.release, deadline=time.monotonic() + timeout)
    else:
        owner = _runtime_app()
        owner._flask_app = app
        stop = owner.stop

    async def exercise():
        try:
            with pytest.raises((RuntimeError, DesktopBackendShutdownIncomplete)):
                await stop(timeout=0.2)
            assert entered.is_set(), "actual ExecutionSessions.shutdown was never called"
            assert len(calls) == 1 and calls[0].is_alive()
            assert app.config["EXECUTION_SESSIONS"] is sessions and not sessions.closed
            assert all(app.config.get(key) is exact for key, exact in dependencies.items())
            finish.set()
            await stop(timeout=8)
            assert len(calls) == 1, "retry duplicated the retained shutdown worker"
            assert sessions.closed
            assert all(key not in app.config for key in dependencies)
        finally:
            finish.set()
            await stop(timeout=8)

    asyncio.run(exercise())


@pytest.mark.parametrize("kind", ["desktop", "async"])
def test_factory_protection_close_refusal_keeps_borrowed_dependencies(owned_factory, monkeypatch, kind):
    import asyncio
    from flinttrade_core.desktop import _DesktopShutdownRecoveryOwner
    from packages.core.core.tests.test_runtime_lifecycle import _runtime_app

    app, _ = owned_factory
    protection = app.config["PROTECTION_SERVICES"]
    dependencies = {key: app.config[key] for key in ("MODEL_RUN_SERVICES", "DATA_RUNTIME", "KNOWLEDGE_RUNTIME")}
    real_close = protection.close
    fail = True

    def refuse():
        if fail:
            raise RuntimeError("synthetic unresolved protection duty")
        return real_close()

    monkeypatch.setattr(protection, "close", refuse)
    if kind == "desktop":
        owner = _DesktopShutdownRecoveryOwner(app)
        app.extensions["test.release"] = owner

        async def stop(timeout):
            await asyncio.to_thread(owner.release, deadline=time.monotonic() + timeout)
    else:
        owner = _runtime_app()
        owner._flask_app = app
        stop = owner.stop

    async def exercise():
        nonlocal fail
        try:
            with pytest.raises(RuntimeError):
                await stop(timeout=5)
            assert app.config["PROTECTION_SERVICES"] is protection
            assert all(app.config.get(key) is exact for key, exact in dependencies.items())
        finally:
            fail = False
            await stop(timeout=8)
        assert protection._closed

    asyncio.run(exercise())


@pytest.mark.parametrize("entrypoint", ["normal", "desktop", "wsgi"])
def test_pre_return_factory_failure_retains_exact_partial_app(fresh_lease, monkeypatch, entrypoint):
    import threading
    from flask import Flask
    from flinttrade_core import app as core, desktop
    from flinttrade_core.data_runtime import DataRuntime

    entered, finish = threading.Event(), threading.Event()
    observed, closes = [], []
    original_register = Flask.register_blueprint
    original_close = DataRuntime.close

    def register(app, blueprint, **kwargs):
        if blueprint.name == "ai":
            observed.append(app)
            app.config["RUNTIME_FACTORY_ROLLBACK_TIMEOUT_SECONDS"] = 0.1
            raise RuntimeError("synthetic factory failure")
        return original_register(app, blueprint, **kwargs)

    def close(owner):
        closes.append(threading.current_thread())
        entered.set()
        assert finish.wait(15)
        return original_close(owner)

    monkeypatch.setattr(Flask, "register_blueprint", register)
    monkeypatch.setattr(DataRuntime, "close", close)
    monkeypatch.setattr(desktop, "_DESKTOP_SHUTDOWN_TIMEOUT", 0.1)
    if entrypoint == "wsgi":
        for key in ("_APP_CACHE", "_APP_CACHE_PID", "_WSGI_BACKEND_LEASE", "_WSGI_STARTUP_RECOVERY"):
            monkeypatch.setattr(core, key, None)
        monkeypatch.setattr(core, "acquire_backend_instance_lease", lambda: fresh_lease)
        build = core._get_wsgi_app
    elif entrypoint == "desktop":
        def build():
            return desktop._build_app(fresh_lease.proof)
    else:
        def build():
            return core.create_flask_app(backend_lease_proof=fresh_lease.proof)
    recovery = None
    try:
        with pytest.raises(RuntimeError) as caught:
            build()
        assert len(observed) == 1
        recovery = getattr(caught.value, "recovery_owner", None)
        assert recovery is not None, "factory lost the unreturned Flask application's cleanup custody"
        assert entered.is_set()
        assert len(closes) == 1 and closes[0].is_alive()
        app = observed[0]
        assert app.config["DATA_RUNTIME"].closed is False
        assert "KNOWLEDGE_RUNTIME" in app.config
        assert fresh_lease._is_live(), "caller released the backend beneath retained factory owners"
        assert not app.config["CLIENT"]._closed, "borrowed broker client closed beneath the partial app"
        if entrypoint == "desktop":
            assert app.config["AUDIT"]._current_file is not None, "borrowed audit closed beneath the partial app"
        finish.set()
        if entrypoint == "wsgi":
            core._WSGI_STARTUP_RECOVERY.retry_recovery()
        else:
            recovery.release(deadline=time.monotonic() + 8)
        assert len(closes) == 1
        assert "DATA_RUNTIME" not in app.config
    finally:
        finish.set()
        if observed:
            # Same exact owner after GREEN; fallback only cleans the RED leak.
            if recovery is None:
                recovery = desktop._DesktopShutdownRecoveryOwner(observed[0])
            recovery.release(deadline=time.monotonic() + 8)


@pytest.mark.parametrize("entrypoint", ["desktop", "wsgi"])
def test_managed_factory_mounts_real_maintenance_after_proof(fresh_lease, monkeypatch, entrypoint):
    import atexit
    from flinttrade_core import app as core, desktop
    from flinttrade_core.maintenance_control import MaintenanceControl

    if entrypoint == "desktop":
        app = desktop._build_app(fresh_lease.proof)
    else:
        for key in ("_APP_CACHE", "_APP_CACHE_PID", "_WSGI_BACKEND_LEASE", "_WSGI_STARTUP_RECOVERY"):
            monkeypatch.setattr(core, key, None)
        monkeypatch.setattr(core, "acquire_backend_instance_lease", lambda: fresh_lease)
        monkeypatch.setattr(atexit, "register", lambda *a, **k: None)
        app = core._get_wsgi_app(shutdown_callback=lambda: None)
    try:
        control = app.extensions.get("flinttrade.maintenance")
        assert type(control) is MaintenanceControl, "actual managed factory omitted the live maintenance channel"
        assert control.proof is fresh_lease.proof
        assert control.thread.is_alive()
        assert app.test_client().get("/healthz").status_code == 200
    finally:
        release = app.extensions.get("flinttrade.wsgi_shutdown_owner") or desktop._DesktopShutdownRecoveryOwner(app)
        release.release(deadline=time.monotonic() + 8)
    assert control.closed.is_set() and not control.thread.is_alive()


def test_wsgi_postfactory_recovery_reuses_exact_held_close(fresh_lease, monkeypatch):
    import atexit
    import threading
    from flinttrade_core import app as core
    from flinttrade_core.data_runtime import DataRuntime

    for key in ("_APP_CACHE", "_APP_CACHE_PID", "_WSGI_BACKEND_LEASE", "_WSGI_STARTUP_RECOVERY"):
        monkeypatch.setattr(core, key, None)
    monkeypatch.setattr(core, "acquire_backend_instance_lease", lambda: fresh_lease)
    finish, entered = threading.Event(), threading.Event()
    calls = []
    close = DataRuntime.close

    def held(owner):
        calls.append(owner)
        entered.set()
        assert finish.wait(10)
        close(owner)

    monkeypatch.setattr(DataRuntime, "close", held)
    original_registration = atexit.register

    def fail_registration(callback, *args, **kwargs):
        if getattr(callback, "__name__", None) == "stop_at_exit":
            raise RuntimeError("synthetic postfactory failure")
        return original_registration(callback, *args, **kwargs)
    monkeypatch.setattr(atexit, "register", fail_registration)
    # Configure the real retained recovery's startup attempt, not its algorithm.
    original_retry = core._WSGIStartupRecovery.retry_recovery
    monkeypatch.setattr(core._WSGIStartupRecovery, "retry_recovery", lambda self: original_retry(self, timeout=0.15))
    recovery = None
    try:
        with pytest.raises(RuntimeError, match="synthetic postfactory failure"):
            core._get_wsgi_app()
        recovery = core._WSGI_STARTUP_RECOVERY
        assert recovery is not None and entered.is_set()
        candidate = recovery._candidate
        exact_release = recovery._release_owner
        assert fresh_lease._is_live()
        with pytest.raises(RuntimeError):
            original_retry(recovery, timeout=0.05)
        assert recovery._release_owner is exact_release and len(calls) == 1
        assert candidate.config["DATA_RUNTIME"] is calls[0]
    finally:
        finish.set()
        if recovery is not None:
            original_retry(recovery, timeout=8)
    assert core._WSGI_STARTUP_RECOVERY is None
    assert len(calls) == 1 and calls[0].closed


@pytest.mark.asyncio
async def test_full_async_factory_maintenance_uses_owning_loop_and_retained_completion(fresh_lease, monkeypatch):
    import asyncio
    import threading
    from flinttrade_core import app as core
    from flinttrade_core.maintenance_control import MaintenanceControl

    runtime = core.FlintTradeApp()
    runtime._backend_lease_proof = fresh_lease.proof
    monkeypatch.setattr(core, "_resolve_backend_port", lambda: 0)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    started = asyncio.Event()
    wait = runtime._wait_for_shutdown_result

    async def observed_wait():
        started.set()
        return await wait()

    monkeypatch.setattr(runtime, "_wait_for_shutdown_result", observed_wait)
    task = asyncio.create_task(runtime.start())
    finish, entered = threading.Event(), threading.Event()
    calls = []
    control = None
    try:
        await asyncio.wait_for(started.wait(), timeout=15)
        app = runtime._flask_app
        assert app is not None
        control = app.extensions.get("flinttrade.maintenance")
        assert type(control) is MaintenanceControl, "full async runtime omitted managed maintenance"
        assert runtime._flask_server_owner is not None
        assert app.test_client().get("/healthz").status_code == 200
        real_complete = control.runtime_stopped

        def held_complete(*, timeout):
            assert runtime._flask_server_owner is None
            assert not any(key in app.config for key in ("EXECUTION_SESSIONS", "MODEL_RUN_SERVICES", "DATA_RUNTIME", "KNOWLEDGE_RUNTIME"))
            calls.append(threading.current_thread())
            entered.set()
            assert finish.wait(10)
            real_complete(timeout=timeout)

        monkeypatch.setattr(control, "runtime_stopped", held_complete)
        app.config["RUNTIME_SHUTDOWN_TIMEOUT_SECONDS"] = 3.0
        await asyncio.to_thread(control.request_shutdown)
        assert await asyncio.to_thread(entered.wait, 5)
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(task, timeout=5)
        assert not runtime._stop_completed
        assert fresh_lease._is_live()
        finish.set()
        await runtime.stop(timeout=8)
        assert runtime._stop_completed
        assert len(calls) == 1
        assert control.closed.is_set() and not control.thread.is_alive()
    finally:
        finish.set()
        await runtime.stop(timeout=8)
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("entrypoint", ["async", "desktop", "wsgi"])
def test_fresh_production_factory_qualifies_real_managed_stop(tmp_path, monkeypatch, entrypoint):
    import json
    import subprocess
    import sys
    from pathlib import Path
    from flinttrade_core.backend_instance import BackendInstanceAlreadyRunning, acquire_backend_instance_lease
    from flinttrade_core.maintenance_control import stopped_workspace

    monkeypatch.setenv("HOME", str(tmp_path))
    workspace = tmp_path / ".flinttrade"
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("FLINTTRADE_INSTALLATION_STATE_DIR", str(tmp_path / ".flinttrade-installation"))
    script = Path(__file__).with_name("factory_maintenance_child.py")
    log = (tmp_path / "child.log").open("w")
    child = subprocess.Popen([sys.executable, str(script), entrypoint, "fresh", str(tmp_path)],
                             stdout=log, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + 20
        while not (tmp_path / "ready.json").exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert (tmp_path / "ready.json").exists(), (tmp_path / "child.log").read_text()
        assert json.loads((tmp_path / "ready.json").read_text())["maintenance"]
        with stopped_workspace(workspace, timeout=20):
            assert child.wait(timeout=5) == 0, (tmp_path / "child.log").read_text()
            assert json.loads((tmp_path / "finished.json").read_text()) == {"drained": True, "entries_rearmed": False}
            with pytest.raises(BackendInstanceAlreadyRunning):
                acquire_backend_instance_lease()
        successor = acquire_backend_instance_lease()
        successor.release()
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
        log.close()


@pytest.mark.parametrize("kind", ["desktop", "async"])
def test_real_session_read_holds_factory_dependencies_until_response_closes(owned_factory, monkeypatch, kind):
    import asyncio
    import threading
    from flinttrade_core import desktop
    from packages.core.core.tests.test_runtime_lifecycle import _runtime_app

    app, headers = owned_factory
    sessions = app.config["EXECUTION_SESSIONS"]
    original = sessions.list
    entered, finish = threading.Event(), threading.Event()
    observed = []

    def held(actor):
        assert app.config["RUNTIME_REQUEST_TRACKER"]._active == 1
        entered.set()
        assert finish.wait(10)
        assert not sessions.closed
        return original(actor)

    monkeypatch.setattr(sessions, "list", held)
    request = threading.Thread(target=lambda: observed.append(app.test_client().get("/api/v1/execution-sessions", headers=headers).status_code))
    request.start()
    if kind == "desktop":
        owner = desktop._DesktopShutdownRecoveryOwner(app)
        app.extensions["test.release"] = owner
        async def stop(timeout):
            await asyncio.to_thread(owner.release, deadline=time.monotonic() + timeout)
    else:
        owner = _runtime_app()
        owner._flask_app = app
        stop = owner.stop

    async def exercise():
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            with pytest.raises(RuntimeError):
                await stop(timeout=0.15)
            assert not sessions.closed
            assert app.config["EXECUTION_SESSIONS"] is sessions
            assert app.test_client().get("/api/v1/execution-sessions", headers=headers).status_code == 503
        finally:
            finish.set()
            await asyncio.to_thread(request.join, 5)
            await stop(timeout=8)
        assert observed == [200]
        assert sessions.closed

    asyncio.run(exercise())


@pytest.mark.parametrize("kind", ["desktop", "async"])
def test_execution_shutdown_substitution_does_not_dispose_original_or_dependencies(owned_factory, monkeypatch, kind):
    import asyncio
    from flinttrade_core import desktop
    from packages.core.core.tests.test_runtime_lifecycle import _runtime_app

    app, _ = owned_factory
    sessions = app.config["EXECUTION_SESSIONS"]
    original = sessions.shutdown
    monkeypatch.setattr(sessions, "shutdown", lambda timeout: False)
    if kind == "desktop":
        owner = desktop._DesktopShutdownRecoveryOwner(app)
        app.extensions["test.release"] = owner
        async def stop(timeout):
            await asyncio.to_thread(owner.release, deadline=time.monotonic() + timeout)
    else:
        owner = _runtime_app()
        owner._flask_app = app
        stop = owner.stop

    async def exercise():
        try:
            with pytest.raises(RuntimeError):
                await stop(timeout=3)
            app.config["EXECUTION_SESSIONS"] = object()
            with pytest.raises(RuntimeError):
                await stop(timeout=3)
            app.config.pop("EXECUTION_SESSIONS")
            with pytest.raises(RuntimeError):
                await stop(timeout=3)
            assert not sessions.closed
            assert not app.config["DATA_RUNTIME"].closed
        finally:
            app.config["EXECUTION_SESSIONS"] = sessions
            monkeypatch.setattr(sessions, "shutdown", original)
            await stop(timeout=8)

    asyncio.run(exercise())


def test_desktop_factory_registered_scheduler_failure_keeps_dependencies(owned_factory, monkeypatch):
    from flinttrade_core import desktop

    app, _ = owned_factory
    scheduler = app.config["SCHEDULER"]
    real_stop = scheduler.stop_all
    calls = []
    failing = True

    async def fail_stop():
        calls.append(scheduler)
        if failing:
            raise RuntimeError("synthetic scheduler drain failure")
        await real_stop()

    monkeypatch.setattr(scheduler, "stop_all", fail_stop)
    owner = desktop._DesktopShutdownRecoveryOwner(app)
    app.extensions["test.release"] = owner
    try:
        with pytest.raises(RuntimeError):
            owner.release(deadline=time.monotonic() + 5)
        assert calls == [scheduler]
        assert not app.config["DATA_RUNTIME"].closed
        assert not app.config["EXECUTION_SESSIONS"].closed
    finally:
        failing = False
        owner.release(deadline=time.monotonic() + 8)


def test_early_factory_failure_captures_vault_before_later_constructor(fresh_lease, monkeypatch):
    from flinttrade_core import app as core

    closed, created = [], []
    real_close = core.CredentialStore.close
    real_init = core.CredentialStore.__init__

    def observe_init(owner, *args, **kwargs):
        real_init(owner, *args, **kwargs)
        created.append(owner)

    def observe_close(owner):
        if owner in created:
            closed.append(owner)
        return real_close(owner)

    def fail_contracts(*args, **kwargs):
        raise RuntimeError("synthetic contracts constructor failed")

    monkeypatch.setattr(core.CredentialStore, "__init__", observe_init)
    monkeypatch.setattr(core.CredentialStore, "close", observe_close)
    monkeypatch.setattr(core, "ContractManager", fail_contracts)
    with pytest.raises(RuntimeError, match="synthetic contracts constructor failed") as caught:
        core.create_flask_app(backend_lease_proof=fresh_lease.proof)
    assert len(closed) == 1
    assert caught.value.recovery_owner._released


def test_restart_protection_recovery_runs_only_after_full_factory_mount(fresh_lease, monkeypatch):
    from flinttrade_core import app as core, desktop
    from flinttrade_core.execution_sessions import ExecutionSessions

    first = core.create_flask_app(backend_lease_proof=fresh_lease.proof)
    desktop._DesktopShutdownRecoveryOwner(first).release(deadline=time.monotonic() + 8)
    observed = []
    real_resume = ExecutionSessions.resume_protection

    def resume(owner):
        observed.append(owner)
        assert owner.app.config.get("AUTH_SERVICE") is not None, "restart worker admitted before authentication owner exists"
        assert "/api/v1/orders/place" in {rule.rule for rule in owner.app.url_map.iter_rules()}, "restart worker admitted before canonical ingress is mounted"
        return real_resume(owner)

    monkeypatch.setattr(ExecutionSessions, "resume_protection", resume)
    app = core.create_flask_app(backend_lease_proof=fresh_lease.proof)
    try:
        assert observed and all(owner is app.config["EXECUTION_SESSIONS"] for owner in observed)
        assert app.config["EXECUTION_PROTECTION_RECOVERY"]["state"] == "observed"
        assert app.config["EXECUTION_PROTECTION_RECOVERY"]["runs"] == []
    finally:
        desktop._DesktopShutdownRecoveryOwner(app).release(deadline=time.monotonic() + 8)


@pytest.mark.asyncio
async def test_async_prefactory_failure_retains_partial_app_before_borrowed_root_close(fresh_lease, monkeypatch):
    import threading
    from flask import Flask
    from flinttrade_core import app as core
    from flinttrade_core.data_runtime import DataRuntime

    runtime = core.FlintTradeApp()
    runtime._backend_lease_proof = fresh_lease.proof
    finish, entered = threading.Event(), threading.Event()
    register, close = Flask.register_blueprint, DataRuntime.close
    observed = []

    def fail_after_owners(app, blueprint, **kwargs):
        if blueprint.name == "ai":
            app.config.update(RUNTIME_FACTORY_ROLLBACK_TIMEOUT_SECONDS=0.1, RUNTIME_STARTUP_ROLLBACK_TIMEOUT_SECONDS=0.1)
            observed.append(app)
            raise RuntimeError("synthetic async prefactory failure")
        return register(app, blueprint, **kwargs)

    def held_close(owner):
        entered.set()
        assert finish.wait(30)
        close(owner)

    monkeypatch.setattr(Flask, "register_blueprint", fail_after_owners)
    monkeypatch.setattr(DataRuntime, "close", held_close)
    try:
        before = time.monotonic()
        with pytest.raises(RuntimeError, match="synthetic async prefactory failure"):
            await runtime.start()
        assert time.monotonic() - before < 5, "startup ignored the partial factory's remaining rollback budget"
        assert entered.is_set() and runtime._startup_recovery_pending
        assert runtime._factory_recovery is observed[0].extensions["flinttrade.factory_recovery"]
        assert not runtime.client._closed
        assert runtime.audit._current_file is not None
    finally:
        finish.set()
        await runtime.stop(timeout=8)
    assert runtime._stop_completed and runtime.client._closed


def test_desktop_real_master_worker_retains_factory_dependencies(fresh_lease, monkeypatch):
    import threading
    from urllib.error import URLError
    from flinttrade_core import desktop, instrument_lot_master

    entered, finish = threading.Event(), threading.Event()

    def held_download(url):
        entered.set()
        assert finish.wait(10)
        raise URLError("synthetic external transport unavailable")

    monkeypatch.setattr(instrument_lot_master, "_download_text", held_download)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    app = desktop._build_app(fresh_lease.proof)
    recovery = desktop._DesktopShutdownRecoveryOwner(app)
    master = app.config["INSTRUMENT_MASTER_REFRESH_OWNER"]
    try:
        assert entered.wait(3)
        with pytest.raises(RuntimeError):
            recovery.release(deadline=time.monotonic() + 0.15)
        assert "INSTRUMENT_MASTER_REFRESH_OWNER" in app.config
        assert not app.config["DATA_RUNTIME"].closed
        assert not app.config["CLIENT"]._closed
        app.config.pop("INSTRUMENT_MASTER_REFRESH_OWNER")
        with pytest.raises(RuntimeError):
            recovery.release(deadline=time.monotonic() + 3)
        assert not app.config["DATA_RUNTIME"].closed
    finally:
        app.config["INSTRUMENT_MASTER_REFRESH_OWNER"] = master
        finish.set()
        recovery.release(deadline=time.monotonic() + 8)
        assert master.stop(timeout=5)
    assert "INSTRUMENT_MASTER_REFRESH_OWNER" not in app.config


@pytest.mark.parametrize("kind", ["desktop", "async"])
def test_actual_historify_worker_blocks_factory_dependency_disposal(owned_factory, kind):
    import asyncio
    import threading
    from flinttrade_core import desktop
    from packages.core.core.tests.test_runtime_lifecycle import _runtime_app

    app, _ = owned_factory
    data = app.config["DATA_RUNTIME"]
    entered, finish = threading.Event(), threading.Event()

    async def download(progress):
        entered.set()
        await asyncio.to_thread(finish.wait)
        assert not data.closed

    data.downloads.start(total=1, runner=download, storage_path=str(data.workspace))
    if kind == "desktop":
        owner = desktop._DesktopShutdownRecoveryOwner(app)
        app.extensions["test.release"] = owner
        async def stop(timeout):
            await asyncio.to_thread(owner.release, deadline=time.monotonic() + timeout)
    else:
        owner = _runtime_app()
        owner._flask_app = app
        stop = owner.stop

    async def exercise():
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            with pytest.raises(RuntimeError):
                await stop(timeout=0.15)
            assert app.config["DATA_RUNTIME"] is data and not data.closed
            assert not app.config["CLIENT"]._closed
            assert "KNOWLEDGE_RUNTIME" in app.config
        finally:
            finish.set()
            await stop(timeout=8)
        assert data.closed

    asyncio.run(exercise())


def test_unknown_history_public_maintenance_refuses_live_factory(tmp_path, monkeypatch):
    import subprocess
    import sys
    from pathlib import Path
    from flinttrade_core.maintenance_control import stop_workspace
    from flinttrade_core.maintenance_custody import MaintenanceRefused

    monkeypatch.setenv("HOME", str(tmp_path))
    workspace = tmp_path / ".flinttrade"
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("FLINTTRADE_INSTALLATION_STATE_DIR", str(tmp_path / ".flinttrade-installation"))
    script = Path(__file__).with_name("factory_maintenance_child.py")
    with (tmp_path / "child.log").open("w") as log:
        child = subprocess.Popen([sys.executable, str(script), "wsgi", "unknown", str(tmp_path)], stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 20
            while not (tmp_path / "ready.json").exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            assert (tmp_path / "ready.json").exists(), (tmp_path / "child.log").read_text()
            with pytest.raises(MaintenanceRefused, match="historical ownership unknown"):
                stop_workspace(workspace, timeout=5)
            assert child.poll() is None
            assert not (tmp_path / "finished.json").exists()
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)


