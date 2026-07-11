"""Tests for the desktop sidecar entry script's parent-liveness watchdog.

The entry script (``packaging/desktop_backend.py``) is desktop-owned and not a
package, so it is loaded here straight from its file path. These tests cover
the watchdog wiring only — the served backend belongs to
``flinttrade_core.desktop`` and is tested there.

The tests live under ``packages/apps/desktop/tests/`` (not ``packaging/tests/``)
for two hard reasons: CI's pytest glob is ``packages/*/*/tests/``, and
collecting a ``packaging/`` directory shadows the PyPI ``packaging`` module,
breaking ``packaging.version`` imports for every later test in the process.

Run with::

    uv run pytest packages/apps/desktop/tests/ -v --import-mode=importlib
"""

from __future__ import annotations

import importlib.util
import io
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from types import ModuleType

import pytest

ENTRY_SCRIPT = Path(__file__).resolve().parents[4] / "packaging" / "desktop_backend.py"


def _load_entry_module() -> ModuleType:
    """Import the entry script from its file path (it is not a package)."""
    spec = importlib.util.spec_from_file_location("desktop_backend_entry", ENTRY_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(name="entry")
def entry_fixture() -> ModuleType:
    return _load_entry_module()


@pytest.mark.unit
def test_import_has_no_side_effects() -> None:
    """Loading the entry script must not start the backend or a watchdog.

    Compares thread identities before/after a fresh module load — asserting on
    the global thread list alone is order-dependent (daemon watchdogs started
    by other tests in this file legitimately outlive them).
    """
    before = {t.ident for t in threading.enumerate()}
    module = _load_entry_module()
    started_by_load = [
        t for t in threading.enumerate() if t.ident not in before and t.name == "flinttrade-parent-watchdog"
    ]
    assert started_by_load == []
    assert module.PARENT_PID_ENV == "FLINTTRADE_PARENT_PID"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("  ", None),
        ("abc", None),
        ("0", None),
        ("-5", None),
        ("1234", 1234),
        (" 1234 ", 1234),
    ],
)
def test_parent_pid_parsing(entry: ModuleType, raw: str | None, expected: int | None) -> None:
    environ = {} if raw is None else {entry.PARENT_PID_ENV: raw}
    assert entry._parent_pid_from_env(environ) == expected


@pytest.mark.unit
def test_application_promotes_exact_pending_record_before_handshake(
    entry: ModuleType,
    tmp_path: Path,
) -> None:
    record = tmp_path / "desktop_backend.pid"
    token = "a" * 64
    record.write_text(f"v2\n1234\npending\n77\n{token}\n", encoding="utf-8")
    environ = {
        "FLINTTRADE_PARENT_PID": "77",
        "FLINTTRADE_LAUNCH_TOKEN": token,
        "FLINTTRADE_SIDECAR_RECORD_PATH": str(record),
    }

    assert entry.promote_application_pid_record(environ=environ, pid=5678) is True
    assert record.read_text(encoding="utf-8") == f"v2\n1234\n5678\n77\n{token}\n"


@pytest.mark.unit
def test_application_pid_handshake_is_flushed(entry: ModuleType) -> None:
    stream = io.StringIO()

    entry.announce_application_pid(stream=stream, pid=5678)

    assert stream.getvalue() == "FLINTTRADE_BACKEND_PID pid=5678\n"


@pytest.mark.unit
def test_application_refuses_to_promote_another_launch_record(
    entry: ModuleType,
    tmp_path: Path,
) -> None:
    record = tmp_path / "desktop_backend.pid"
    record.write_text(f"v2\n1234\npending\n77\n{'b' * 64}\n", encoding="utf-8")
    environ = {
        "FLINTTRADE_PARENT_PID": "77",
        "FLINTTRADE_LAUNCH_TOKEN": "a" * 64,
        "FLINTTRADE_SIDECAR_RECORD_PATH": str(record),
    }

    assert entry.promote_application_pid_record(environ=environ, pid=5678) is False
    assert record.read_text(encoding="utf-8") == f"v2\n1234\npending\n77\n{'b' * 64}\n"


@pytest.mark.unit
def test_backend_boot_refuses_untracked_application_pid(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(entry, "promote_application_pid_record", lambda: False)

    with pytest.raises(SystemExit, match="application PID record promotion failed"):
        entry.require_application_pid_record()


@pytest.mark.unit
def test_watchdog_off_without_env(entry: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(entry.PARENT_PID_ENV, raising=False)
    assert entry.start_parent_watchdog() is None


@pytest.mark.unit
def test_watchdog_starts_as_daemon_thread(entry: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    # Watch a process guaranteed to outlive the assertion: this test process.
    monkeypatch.setenv(entry.PARENT_PID_ENV, str(os.getpid()))
    thread = entry.start_parent_watchdog()
    assert thread is not None
    assert thread.daemon is True
    assert thread.is_alive()
    assert thread.name == "flinttrade-parent-watchdog"


@pytest.mark.unit
def test_shutdown_coordinator_delivers_requests_before_and_after_install(entry: ModuleType) -> None:
    coordinator = entry._ShutdownCoordinator()
    calls: list[str] = []

    assert coordinator.request() is True
    assert coordinator.request() is False

    def callback() -> None:
        calls.append("shutdown")

    coordinator.install(callback)

    assert calls == ["shutdown"]
    coordinator.uninstall(callback)

    second = entry._ShutdownCoordinator()
    second.install(callback)
    assert second.request() is True
    assert second.request() is False
    assert calls == ["shutdown", "shutdown"]


@pytest.mark.unit
def test_sigterm_relay_handler_never_takes_coordinator_lock(entry: ModuleType) -> None:
    coordinator = entry._ShutdownCoordinator()
    callback_called = threading.Event()
    forwarding_started = threading.Event()

    coordinator.install(callback_called.set)

    def forward_request() -> bool:
        forwarding_started.set()
        return coordinator.request()

    relay = entry._SignalShutdownRelay(forward_request, poll_interval=0.001)
    relay_thread = relay.start()

    coordinator._lock.acquire()
    try:
        # Model SIGTERM interrupting the main thread while install/uninstall is
        # inside the coordinator's non-reentrant critical section. The handler
        # itself must return without touching that lock.
        relay.handle(signal.SIGTERM, None)
        assert forwarding_started.wait(timeout=1)
        assert callback_called.is_set() is False
    finally:
        coordinator._lock.release()

    relay_thread.join(timeout=1)
    assert relay_thread.is_alive() is False
    assert callback_called.is_set() is True


@pytest.mark.unit
def test_stdin_shutdown_command_requests_graceful_exit(entry: ModuleType) -> None:
    requested = threading.Event()
    thread = entry.start_stdin_shutdown_listener(
        requested.set,
        stream=io.StringIO(f"ignored\n{entry.SHUTDOWN_COMMAND}\n"),
    )

    thread.join(timeout=1)
    assert requested.is_set()


@pytest.mark.unit
def test_stdin_force_exit_targets_the_exact_python_application(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested = threading.Event()
    exit_codes: list[int] = []
    monkeypatch.setattr(entry.os, "_exit", exit_codes.append)

    thread = entry.start_stdin_shutdown_listener(
        requested.set,
        stream=io.StringIO("FLINTTRADE_FORCE_EXIT\n"),
    )

    thread.join(timeout=1)
    assert exit_codes == [1]
    assert requested.is_set() is False


@pytest.mark.unit
def test_stdin_listener_keeps_force_fallback_after_graceful_request(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested = threading.Event()
    exit_codes: list[int] = []
    monkeypatch.setattr(entry.os, "_exit", exit_codes.append)

    thread = entry.start_stdin_shutdown_listener(
        requested.set,
        stream=io.StringIO(f"{entry.SHUTDOWN_COMMAND}\n{entry.FORCE_EXIT_COMMAND}\n"),
    )

    thread.join(timeout=1)
    assert requested.is_set() is True
    assert exit_codes == [1]


@pytest.mark.unit
def test_stdin_eof_requests_graceful_exit_for_a_dead_parent(entry: ModuleType) -> None:
    requested = threading.Event()
    thread = entry.start_stdin_shutdown_listener(requested.set, stream=io.StringIO(""))

    thread.join(timeout=1)
    assert requested.is_set()


@pytest.mark.unit
@pytest.mark.skipif(os.name == "nt", reason="POSIX liveness checks")
def test_posix_parent_alive_probes(entry: ModuleType) -> None:
    # kill(pid, 0) path: this process is alive.
    assert entry._posix_parent_alive(os.getpid(), track_reparent=False) is True
    # A freshly reaped child PID reads as dead.
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    assert entry._posix_parent_alive(child.pid, track_reparent=False) is False
    # Reparent tracking: our real parent matches; an unrelated PID does not.
    assert entry._posix_parent_alive(os.getppid(), track_reparent=True) is True
    assert entry._posix_parent_alive(os.getpid(), track_reparent=True) is False


@pytest.mark.unit
def test_posix_watcher_returns_after_first_orphan_request(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    request_shutdown = object()

    monkeypatch.setattr(entry.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(entry, "_posix_parent_alive", lambda *_args, **_kwargs: False)

    def exit_once(request: object) -> None:
        calls.append(request)
        if len(calls) > 1:
            raise AssertionError("watcher requested orphan shutdown more than once")

    monkeypatch.setattr(entry, "_exit_orphaned", exit_once)

    entry._watch_parent_posix(1234, request_shutdown)

    assert calls == [request_shutdown]


@pytest.mark.integration
@pytest.mark.skipif(os.name == "nt", reason="POSIX orphan scenario")
def test_sidecar_exits_when_parent_dies(tmp_path: Path) -> None:
    """End-to-end orphan drill: shell dies -> watchdog exits the sidecar.

    A throwaway "shell" process spawns a "sidecar" (this entry script's
    watchdog + a long sleep) with FLINTTRADE_PARENT_PID set to itself, then
    exits. The sidecar must notice and exit on its own within the poll window.
    """
    sidecar_script = textwrap.dedent(
        f"""
        import importlib.util, time
        spec = importlib.util.spec_from_file_location("desktop_backend_entry", {str(ENTRY_SCRIPT)!r})
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.POLL_INTERVAL_SECONDS = 0.1
        assert mod.start_parent_watchdog() is not None
        print("SIDECAR_READY", flush=True)
        time.sleep(60)  # the watchdog must exit us long before this
        """
    )
    shell_script = textwrap.dedent(
        f"""
        import os, subprocess, sys
        env = dict(os.environ)
        env["FLINTTRADE_PARENT_PID"] = str(os.getpid())
        child = subprocess.Popen(
            [sys.executable, "-c", {sidecar_script!r}],
            env=env,
            stdout=subprocess.PIPE,
            text=True,
        )
        line = child.stdout.readline()
        assert "SIDECAR_READY" in line, line
        print(child.pid, flush=True)
        os._exit(0)  # simulate a shell crash: no cleanup, no child kill
        """
    )
    out = subprocess.run(
        [sys.executable, "-c", shell_script],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    sidecar_pid = int(out.stdout.strip().splitlines()[-1])

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            os.kill(sidecar_pid, 0)
        except ProcessLookupError:
            return  # orphaned sidecar exited cleanly
        time.sleep(0.1)
    os.kill(sidecar_pid, 9)  # do not leak the process on failure
    pytest.fail("orphaned sidecar was still alive 10s after its shell died")
