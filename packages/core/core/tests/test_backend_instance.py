"""Tests for single-backend process ownership."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from types import MethodType, SimpleNamespace
from typing import Any

import pytest
from flask import Flask


_HOLD_BACKEND_LEASE = """
import os
import sys
import time
from pathlib import Path

from flinttrade_core.backend_instance import acquire_backend_instance_lease

workspace, entered, release = map(Path, sys.argv[1:4])
os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(workspace)
lease = acquire_backend_instance_lease()
try:
    entered.write_text("entered", encoding="utf-8")
    deadline = time.monotonic() + 10.0
    while not release.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("test did not release backend lease holder")
        time.sleep(0.01)
finally:
    lease.release()
"""


_TRY_BACKEND_LEASE = """
import os
import sys
from pathlib import Path

from flinttrade_core.backend_instance import (
    BackendInstanceAlreadyRunning,
    acquire_backend_instance_lease,
)

workspace = Path(sys.argv[1])
os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(workspace)
try:
    lease = acquire_backend_instance_lease()
except BackendInstanceAlreadyRunning:
    raise SystemExit(23)
lease.release()
"""


_FORKED_CHILD_DESTRUCTOR_HOLDER = """
import gc
import os
import select
import signal
import sys
import time
from contextlib import suppress
from pathlib import Path

from flinttrade_core.backend_instance import acquire_backend_instance_lease

workspace, entered, release = map(Path, sys.argv[1:4])
os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(workspace)
lease = acquire_backend_instance_lease()
ready_read, ready_write = os.pipe()
child_pid = os.fork()

if child_pid == 0:
    os.close(ready_read)
    try:
        del lease
        gc.collect()
        os.write(ready_write, b"1")
    finally:
        os._exit(0)

os.close(ready_write)
try:
    readable, _, _ = select.select([ready_read], [], [], 5.0)
    if not readable or os.read(ready_read, 1) != b"1":
        raise RuntimeError("forked child did not destroy its inherited lease")
    waited_pid, status = os.waitpid(child_pid, 0)
    child_pid = 0
    if waited_pid <= 0 or os.waitstatus_to_exitcode(status) != 0:
        raise RuntimeError("forked child exited unsuccessfully")
    entered.write_text("entered", encoding="utf-8")
    deadline = time.monotonic() + 10.0
    while not release.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("test did not release backend lease holder")
        time.sleep(0.01)
finally:
    if child_pid:
        with suppress(ProcessLookupError):
            os.kill(child_pid, signal.SIGKILL)
        os.waitpid(child_pid, 0)
    os.close(ready_read)
    lease.release()
"""


_FORKED_PRELOADED_WSGI_REQUEST = """
import os
import sys
from pathlib import Path

from flask import Flask

import flinttrade_core.app as app_module

workspace = Path(sys.argv[1])
os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(workspace)
route_calls = []
flask_app = Flask("preloaded-wsgi-request")

@flask_app.get("/probe")
def probe():
    route_calls.append(os.getpid())
    return "served"

app_module._APP_CACHE = None
app_module._APP_CACHE_PID = None
app_module._WSGI_BACKEND_LEASE = None
app_module.create_flask_app = lambda: flask_app
preloaded_app = app_module._get_wsgi_app()
owner_response = preloaded_app.test_client().get("/probe")
if owner_response.status_code != 200 or route_calls != [os.getpid()]:
    app_module._WSGI_BACKEND_LEASE.release()
    raise SystemExit(40)
route_calls.clear()
child_pid = os.fork()

if child_pid == 0:
    try:
        response = preloaded_app.test_client().get("/probe")
        if response.status_code != 503:
            os._exit(41)
        if b"inherited WSGI app" not in response.data:
            os._exit(42)
        if route_calls:
            os._exit(43)
    except BaseException:
        os._exit(44)
    os._exit(0)

_, status = os.waitpid(child_pid, 0)
try:
    if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
        raise SystemExit(os.WEXITSTATUS(status) if os.WIFEXITED(status) else 45)
finally:
    app_module._WSGI_BACKEND_LEASE.release()
"""


def _wait_for_marker(marker: Path, process: subprocess.Popen[str], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not marker.exists():
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(f"backend lease holder exited early (code {process.returncode}): {stdout}{stderr}")
        if time.monotonic() >= deadline:
            raise AssertionError("timed out waiting for backend lease holder")
        time.sleep(0.01)


@pytest.mark.unit
def test_live_backend_process_blocks_a_second_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_core.backend_instance import (
        BackendInstanceAlreadyRunning,
        acquire_backend_instance_lease,
    )

    entered = tmp_path / "entered"
    release = tmp_path / "release"
    env = os.environ.copy()
    env["FLINTTRADE_WORKSPACE_DIR"] = str(tmp_path)
    process = subprocess.Popen(
        [sys.executable, "-c", _HOLD_BACKEND_LEASE, str(tmp_path), str(entered), str(release)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_marker(entered, process)
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))

        with pytest.raises(
            BackendInstanceAlreadyRunning,
            match="another FlintTrade backend",
        ) as raised:
            acquire_backend_instance_lease()
        assert raised.value.__cause__ is None
    finally:
        release.touch(exist_ok=True)
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5.0)

    stdout, stderr = process.communicate()
    assert process.returncode == 0, stdout + stderr


@pytest.mark.unit
def test_stale_lock_file_contents_do_not_claim_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_core.backend_instance import acquire_backend_instance_lease

    lock_path = tmp_path / "backend_instance.lock"
    lock_path.write_text(f"{2**22}\n0\n", encoding="utf-8")
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))

    lease = acquire_backend_instance_lease()
    try:
        assert lock_path.exists()
        if os.name == "posix":
            assert lock_path.stat().st_mode & 0o777 == 0o600
    finally:
        lease.release()


@pytest.mark.unit
def test_released_backend_lease_allows_a_successor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_core.backend_instance import acquire_backend_instance_lease

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    first = acquire_backend_instance_lease()
    first.release()

    successor = acquire_backend_instance_lease()
    successor.release()


@pytest.mark.unit
def test_pid_bound_lease_refuses_release_from_an_inheriting_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.backend_instance as backend_instance

    releases: list[str] = []
    raw_lease = SimpleNamespace(release=lambda: releases.append("raw-release"))
    lease = backend_instance.BackendInstanceLease(raw_lease, owner_pid=101)
    monkeypatch.setattr(backend_instance.os, "getpid", lambda: 202)

    with pytest.raises(RuntimeError, match="inherited backend lease"):
        lease.release()

    assert releases == []


@pytest.mark.unit
@pytest.mark.skipif(os.name != "posix", reason="requires POSIX descriptor ownership")
def test_posix_lease_retains_descriptor_until_unlock_and_close_both_succeed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.backend_instance as backend_instance

    events: list[str] = []
    unlock_attempts = 0
    close_attempts = 0

    def unlock(descriptor: int, operation: int) -> None:
        nonlocal unlock_attempts
        assert descriptor == 42
        assert operation == backend_instance.fcntl.LOCK_UN
        unlock_attempts += 1
        events.append(f"unlock-{unlock_attempts}")
        if unlock_attempts == 1:
            raise OSError("unlock unavailable")

    def close(descriptor: int) -> None:
        nonlocal close_attempts
        assert descriptor == 42
        close_attempts += 1
        events.append(f"close-{close_attempts}")
        if close_attempts == 1:
            raise OSError("close unavailable")

    monkeypatch.setattr(backend_instance.fcntl, "flock", unlock)
    monkeypatch.setattr(backend_instance.os, "close", close)
    raw_lease = backend_instance._PosixBackendFileLease(42)

    with pytest.raises(OSError, match="unlock unavailable"):
        raw_lease.release()
    assert raw_lease._descriptor == 42

    with pytest.raises(OSError, match="close unavailable"):
        raw_lease.release()
    assert raw_lease._descriptor == 42

    raw_lease.release()

    assert raw_lease._descriptor is None
    assert events == ["unlock-1", "unlock-2", "close-1", "unlock-3", "close-2"]


@pytest.mark.unit
def test_failed_retained_release_keeps_global_retry_authority() -> None:
    import flinttrade_core.backend_instance as backend_instance

    class RetryingLease:
        def __init__(self) -> None:
            self.release_calls = 0

        def release(self) -> None:
            self.release_calls += 1
            if self.release_calls == 1:
                raise RuntimeError("unlock and close incomplete")

    lease = RetryingLease()
    backend_instance.retain_backend_instance_lease(lease)
    try:
        with pytest.raises(RuntimeError, match="unlock and close incomplete"):
            backend_instance.release_retained_backend_instance_lease(lease)

        assert any(retained is lease for retained in backend_instance._RETAINED_FAILED_LEASES)

        backend_instance.release_retained_backend_instance_lease(lease)

        assert lease.release_calls == 2
        assert not any(retained is lease for retained in backend_instance._RETAINED_FAILED_LEASES)
    finally:
        with backend_instance._RETAINED_FAILED_LEASES_LOCK:
            backend_instance._RETAINED_FAILED_LEASES[:] = [
                retained
                for retained in backend_instance._RETAINED_FAILED_LEASES
                if retained is not lease
            ]


@pytest.mark.unit
def test_failed_release_keeps_descriptor_wrapper_and_recovery_owner_attached() -> None:
    import flinttrade_core.backend_instance as backend_instance

    class RetryingRawLease:
        def __init__(self) -> None:
            self.release_calls = 0

        def release(self) -> None:
            self.release_calls += 1
            if self.release_calls == 1:
                raise OSError("descriptor close incomplete")

    raw_lease = RetryingRawLease()
    lease = backend_instance.BackendInstanceLease(raw_lease)
    recovery_owner = object()
    lease.retain_recovery_owner(recovery_owner)
    backend_instance.retain_backend_instance_lease(lease)
    try:
        with pytest.raises(OSError, match="descriptor close incomplete"):
            backend_instance.release_retained_backend_instance_lease(lease)

        assert lease._released is False
        assert lease.recovery_owner is recovery_owner
        assert any(retained is lease for retained in backend_instance._RETAINED_FAILED_LEASES)

        backend_instance.release_retained_backend_instance_lease(lease)

        assert lease._released is True
        assert lease.recovery_owner is None
        assert not any(retained is lease for retained in backend_instance._RETAINED_FAILED_LEASES)
    finally:
        with backend_instance._RETAINED_FAILED_LEASES_LOCK:
            backend_instance._RETAINED_FAILED_LEASES[:] = [
                retained
                for retained in backend_instance._RETAINED_FAILED_LEASES
                if retained is not lease
            ]


@pytest.mark.unit
def test_direct_release_failure_self_retains_global_authority_until_retry() -> None:
    import flinttrade_core.backend_instance as backend_instance

    class RetryingRawLease:
        def __init__(self) -> None:
            self.release_calls = 0

        def release(self) -> None:
            self.release_calls += 1
            if self.release_calls == 1:
                raise OSError("direct descriptor release incomplete")

    raw_lease = RetryingRawLease()
    lease = backend_instance.BackendInstanceLease(raw_lease)
    try:
        with pytest.raises(OSError, match="direct descriptor release incomplete"):
            lease.release()

        assert lease._released is False
        assert any(retained is lease for retained in backend_instance._RETAINED_FAILED_LEASES)

        lease.release()

        assert lease._released is True
        assert not any(retained is lease for retained in backend_instance._RETAINED_FAILED_LEASES)
    finally:
        with backend_instance._RETAINED_FAILED_LEASES_LOCK:
            backend_instance._RETAINED_FAILED_LEASES[:] = [
                retained
                for retained in backend_instance._RETAINED_FAILED_LEASES
                if retained is not lease
            ]


@pytest.mark.unit
@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires POSIX fork semantics")
def test_forked_child_destructor_cannot_release_parent_backend_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    entered = tmp_path / "fork-entered"
    release = tmp_path / "fork-release"
    env = os.environ.copy()
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _FORKED_CHILD_DESTRUCTOR_HOLDER,
            str(tmp_path),
            str(entered),
            str(release),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_marker(entered, process)
        contender = subprocess.run(
            [sys.executable, "-c", _TRY_BACKEND_LEASE, str(tmp_path)],
            env=env,
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        assert contender.returncode == 23, contender.stdout + contender.stderr
    finally:
        release.touch(exist_ok=True)
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5.0)

    stdout, stderr = process.communicate()
    assert process.returncode == 0, stdout + stderr
    successor = subprocess.run(
        [sys.executable, "-c", _TRY_BACKEND_LEASE, str(tmp_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=5.0,
        check=False,
    )
    assert successor.returncode == 0, successor.stdout + successor.stderr


@pytest.mark.unit
def test_different_workspaces_can_hold_independent_backend_leases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_core.backend_instance import acquire_backend_instance_lease

    first_workspace = tmp_path / "first"
    second_workspace = tmp_path / "second"
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(first_workspace))
    first = acquire_backend_instance_lease()
    try:
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(second_workspace))
        second = acquire_backend_instance_lease()
        second.release()
    finally:
        first.release()


class _FakeLease:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def release(self) -> None:
        self._events.append("release")


@pytest.mark.unit
def test_standalone_run_claims_before_start_and_releases_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    events: list[str] = []
    runtime = app_module.FlintTradeApp.__new__(app_module.FlintTradeApp)
    runtime._shutdown_task = None
    runtime._shutdown_request_task = None

    async def fail_start(_self: object) -> None:
        events.append("start")
        raise RuntimeError("startup failed")

    runtime.start = MethodType(fail_start, runtime)
    monkeypatch.setattr(
        app_module,
        "acquire_backend_instance_lease",
        lambda: events.append("acquire") or _FakeLease(events),
    )

    with pytest.raises(RuntimeError, match="startup failed"):
        runtime.run()

    assert events == ["acquire", "start", "release"]


@pytest.mark.unit
def test_standalone_run_retains_lease_when_live_owner_teardown_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    events: list[str] = []
    runtime = app_module.FlintTradeApp.__new__(app_module.FlintTradeApp)
    runtime._flask_app = Flask("failed-runtime-owner")
    runtime._stop_completed = False

    def fail_run(_self: object) -> None:
        events.append("run")
        raise RuntimeError("shutdown encountered errors")

    runtime._run_owned = MethodType(fail_run, runtime)
    lease = _FakeLease(events)
    monkeypatch.setattr(
        app_module,
        "acquire_backend_instance_lease",
        lambda: events.append("acquire") or lease,
    )
    monkeypatch.setattr(
        app_module,
        "retain_backend_instance_lease",
        lambda retained: events.append("retain") if retained is lease else None,
        raising=False,
    )

    with pytest.raises(RuntimeError, match="shutdown encountered errors"):
        runtime.run()

    assert events == ["acquire", "run", "retain"]


@pytest.mark.unit
def test_standalone_contention_prevents_start(monkeypatch: pytest.MonkeyPatch) -> None:
    import flinttrade_core.app as app_module
    from flinttrade_core.backend_instance import BackendInstanceAlreadyRunning

    runtime = app_module.FlintTradeApp.__new__(app_module.FlintTradeApp)
    started = False

    async def start(_self: object) -> None:
        nonlocal started
        started = True

    runtime.start = MethodType(start, runtime)

    def reject() -> Any:
        raise BackendInstanceAlreadyRunning("already running")

    monkeypatch.setattr(app_module, "acquire_backend_instance_lease", reject)

    with pytest.raises(BackendInstanceAlreadyRunning, match="already running"):
        runtime.run()

    assert started is False


@pytest.mark.unit
def test_wsgi_retains_one_lease_for_the_cached_app(monkeypatch: pytest.MonkeyPatch) -> None:
    import flinttrade_core.app as app_module

    events: list[str] = []
    flask_app = Flask("wsgi-backend-lease")
    lease = _FakeLease(events)
    monkeypatch.setattr(app_module, "_APP_CACHE", None)
    monkeypatch.setattr(app_module, "_APP_CACHE_PID", None, raising=False)
    monkeypatch.setattr(app_module, "_WSGI_BACKEND_LEASE", None)
    monkeypatch.setattr(
        app_module,
        "acquire_backend_instance_lease",
        lambda: events.append("acquire") or lease,
    )
    monkeypatch.setattr(
        app_module,
        "create_flask_app",
        lambda: events.append("factory") or flask_app,
    )

    assert app_module._get_wsgi_app() is flask_app
    assert app_module._get_wsgi_app() is flask_app
    assert app_module._WSGI_BACKEND_LEASE is lease
    assert events == ["acquire", "factory"]


@pytest.mark.unit
def test_wsgi_rejects_an_app_cache_inherited_across_fork(monkeypatch: pytest.MonkeyPatch) -> None:
    import flinttrade_core.app as app_module

    events: list[str] = []
    flask_app = Flask("inherited-wsgi-app")
    lease = _FakeLease(events)
    monkeypatch.setattr(app_module, "_APP_CACHE", flask_app)
    monkeypatch.setattr(app_module, "_APP_CACHE_PID", 101, raising=False)
    monkeypatch.setattr(app_module, "_WSGI_BACKEND_LEASE", lease)
    monkeypatch.setattr(app_module.os, "getpid", lambda: 202)
    monkeypatch.setattr(
        app_module,
        "acquire_backend_instance_lease",
        lambda: events.append("acquire") or lease,
    )

    with pytest.raises(RuntimeError, match="inherited WSGI app"):
        app_module._get_wsgi_app()

    assert events == []


@pytest.mark.unit
@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires POSIX fork semantics")
def test_preloaded_wsgi_callable_rejects_a_real_forked_request(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-c", _FORKED_PRELOADED_WSGI_REQUEST, str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.unit
def test_wsgi_releases_lease_when_factory_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    import flinttrade_core.app as app_module

    events: list[str] = []
    monkeypatch.setattr(app_module, "_APP_CACHE", None)
    monkeypatch.setattr(app_module, "_APP_CACHE_PID", None, raising=False)
    monkeypatch.setattr(app_module, "_WSGI_BACKEND_LEASE", None)
    monkeypatch.setattr(
        app_module,
        "acquire_backend_instance_lease",
        lambda: events.append("acquire") or _FakeLease(events),
    )

    def fail_factory() -> Flask:
        events.append("factory")
        raise RuntimeError("factory failed")

    monkeypatch.setattr(app_module, "create_flask_app", fail_factory)

    with pytest.raises(RuntimeError, match="factory failed"):
        app_module._get_wsgi_app()

    assert app_module._APP_CACHE is None
    assert app_module._WSGI_BACKEND_LEASE is None
    assert events == ["acquire", "factory", "release"]


@pytest.mark.unit
def test_desktop_serve_holds_lease_until_server_and_cleanup_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.desktop as desktop

    events: list[str] = []
    flask_app = Flask("desktop-backend-lease")
    flask_app.config["AUDIT"] = SimpleNamespace(close=lambda: events.append("cleanup"))
    monkeypatch.setattr(
        desktop,
        "acquire_backend_instance_lease",
        lambda: events.append("acquire") or _FakeLease(events),
    )
    monkeypatch.setattr(desktop, "_build_app", lambda: events.append("build") or flask_app)
    monkeypatch.setattr(
        "waitress.server.create_server",
        lambda *_args, **_kwargs: SimpleNamespace(
            effective_port=5100,
            run=lambda: events.append("serve"),
        ),
    )

    desktop.serve(5100, ready_writer=lambda _message: None)

    assert events == ["acquire", "build", "serve", "cleanup", "release"]


@pytest.mark.unit
def test_desktop_serve_releases_lease_when_app_build_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.desktop as desktop

    events: list[str] = []
    monkeypatch.setattr(
        desktop,
        "acquire_backend_instance_lease",
        lambda: events.append("acquire") or _FakeLease(events),
    )

    def fail_build() -> Flask:
        events.append("build")
        raise RuntimeError("build failed")

    monkeypatch.setattr(desktop, "_build_app", fail_build)

    with pytest.raises(RuntimeError, match="build failed"):
        desktop.serve(5100)

    assert events == ["acquire", "build", "release"]


@pytest.mark.unit
def test_desktop_serve_retains_lease_when_shutdown_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.desktop as desktop

    events: list[str] = []
    lease = _FakeLease(events)
    monkeypatch.setattr(
        desktop,
        "acquire_backend_instance_lease",
        lambda: events.append("acquire") or lease,
    )
    monkeypatch.setattr(
        desktop,
        "retain_backend_instance_lease",
        lambda retained: events.append("retain") if retained is lease else None,
        raising=False,
    )

    def fail_shutdown(*_args: object, **_kwargs: object) -> None:
        events.append("serve")
        raise desktop.DesktopBackendShutdownIncomplete("shutdown failed")

    monkeypatch.setattr(desktop, "_serve_owned", fail_shutdown)

    with pytest.raises(RuntimeError, match="shutdown failed"):
        desktop.serve(5100)

    assert events == ["acquire", "serve", "retain"]
