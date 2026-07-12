"""Tests for the desktop sidecar entry script's lifecycle boundary.

The entry script (``packaging/desktop_backend.py``) is desktop-owned and not a
package, so it is loaded here straight from its file path. These tests cover
recovery-record transitions, packaged child dispatch, process identity, parent
liveness, and complete-tree containment. The served backend belongs to
``flinttrade_core.desktop`` and is tested there. These tests live under
``packages/apps/desktop/tests/`` (not ``packaging/tests/``)
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
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

ENTRY_SCRIPT = Path(__file__).resolve().parents[4] / "packaging" / "desktop_backend.py"
TEST_BOOT_ID = "c" * 64


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
    record.write_text(f"v3\n1234\npending\n77\n{TEST_BOOT_ID}\n{token}\n", encoding="utf-8")
    environ = {
        "FLINTTRADE_PARENT_PID": "77",
        "FLINTTRADE_BOOT_ID": TEST_BOOT_ID,
        "FLINTTRADE_LAUNCH_TOKEN": token,
        "FLINTTRADE_SIDECAR_RECORD_PATH": str(record),
    }

    assert entry.promote_application_pid_record(environ=environ, pid=5678) is True
    assert record.read_text(encoding="utf-8") == f"v3\n1234\n5678\n77\n{TEST_BOOT_ID}\n{token}\n"


@pytest.mark.unit
def test_application_pid_promotion_requires_the_exact_boot_bound_record(
    entry: ModuleType,
    tmp_path: Path,
) -> None:
    record = tmp_path / "desktop_backend.pid"
    token = "a" * 64
    boot_id = "c" * 64
    pending = f"v3\n1234\npending\n77\n{boot_id}\n{token}\n"
    record.write_text(pending, encoding="utf-8")
    environ = {
        "FLINTTRADE_PARENT_PID": "77",
        "FLINTTRADE_BOOT_ID": boot_id,
        "FLINTTRADE_LAUNCH_TOKEN": token,
        "FLINTTRADE_SIDECAR_RECORD_PATH": str(record),
    }

    assert entry.promote_application_pid_record(environ=environ, pid=5678) is True
    assert record.read_text(encoding="utf-8") == f"v3\n1234\n5678\n77\n{boot_id}\n{token}\n"


@pytest.mark.unit
def test_application_pid_promotion_keeps_pending_record_when_atomic_replace_fails(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = tmp_path / "desktop_backend.pid"
    token = "a" * 64
    pending = f"v3\n1234\npending\n77\n{TEST_BOOT_ID}\n{token}\n"
    record.write_text(pending, encoding="utf-8")
    environ = {
        "FLINTTRADE_PARENT_PID": "77",
        "FLINTTRADE_BOOT_ID": TEST_BOOT_ID,
        "FLINTTRADE_LAUNCH_TOKEN": token,
        "FLINTTRADE_SIDECAR_RECORD_PATH": str(record),
    }
    monkeypatch.setattr(entry.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("injected")))

    assert entry.promote_application_pid_record(environ=environ, pid=5678) is False
    assert record.read_text(encoding="utf-8") == pending
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.unit
def test_application_pid_promotion_is_valid_after_post_replace_sync_failure(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = tmp_path / "desktop_backend.pid"
    token = "a" * 64
    record.write_text(f"v3\n1234\npending\n77\n{TEST_BOOT_ID}\n{token}\n", encoding="utf-8")
    environ = {
        "FLINTTRADE_PARENT_PID": "77",
        "FLINTTRADE_BOOT_ID": TEST_BOOT_ID,
        "FLINTTRADE_LAUNCH_TOKEN": token,
        "FLINTTRADE_SIDECAR_RECORD_PATH": str(record),
    }
    monkeypatch.setattr(
        entry,
        "_sync_parent_directory",
        lambda _path: (_ for _ in ()).throw(OSError("injected after replace")),
    )

    assert entry.promote_application_pid_record(environ=environ, pid=5678) is False
    assert record.read_text(encoding="utf-8") == f"v3\n1234\n5678\n77\n{TEST_BOOT_ID}\n{token}\n"
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.integration
@pytest.mark.parametrize(
    ("boundary", "exit_code", "application_field"),
    [
        ("before-replace", 41, "pending"),
        ("after-replace", 42, "5678"),
    ],
)
def test_application_pid_promotion_crash_boundary_keeps_a_complete_record(
    tmp_path: Path,
    boundary: str,
    exit_code: int,
    application_field: str,
) -> None:
    record = tmp_path / "desktop_backend.pid"
    token = "a" * 64
    pending = f"v3\n1234\npending\n77\n{TEST_BOOT_ID}\n{token}\n"
    record.write_text(pending, encoding="utf-8")
    script = textwrap.dedent(
        f"""
        import importlib.util, os
        spec = importlib.util.spec_from_file_location("desktop_backend_entry", {str(ENTRY_SCRIPT)!r})
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if {boundary!r} == "before-replace":
            mod.os.replace = lambda *_args: os._exit(41)
        else:
            mod._sync_parent_directory = lambda _path: os._exit(42)
        environ = {{
            "FLINTTRADE_PARENT_PID": "77",
            "FLINTTRADE_BOOT_ID": {TEST_BOOT_ID!r},
            "FLINTTRADE_LAUNCH_TOKEN": {token!r},
            "FLINTTRADE_SIDECAR_RECORD_PATH": {str(record)!r},
        }}
        mod.promote_application_pid_record(environ=environ, pid=5678)
        raise SystemExit(99)
        """
    )

    completed = subprocess.run([sys.executable, "-c", script], timeout=10, check=False)

    assert completed.returncode == exit_code
    assert record.read_text(encoding="utf-8") == (
        f"v3\n1234\n{application_field}\n77\n{TEST_BOOT_ID}\n{token}\n"
    )


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
    record.write_text(
        f"v3\n1234\npending\n77\n{TEST_BOOT_ID}\n{'b' * 64}\n",
        encoding="utf-8",
    )
    environ = {
        "FLINTTRADE_PARENT_PID": "77",
        "FLINTTRADE_BOOT_ID": TEST_BOOT_ID,
        "FLINTTRADE_LAUNCH_TOKEN": "a" * 64,
        "FLINTTRADE_SIDECAR_RECORD_PATH": str(record),
    }

    assert entry.promote_application_pid_record(environ=environ, pid=5678) is False
    assert record.read_text(encoding="utf-8") == (
        f"v3\n1234\npending\n77\n{TEST_BOOT_ID}\n{'b' * 64}\n"
    )


@pytest.mark.unit
def test_application_token_comparisons_do_not_normalise_whitespace(
    entry: ModuleType,
    tmp_path: Path,
) -> None:
    token = "a" * 64
    pending = f"v3\n1234\npending\n77\n{TEST_BOOT_ID}\n{token}\n"
    record = tmp_path / "desktop_backend.pid"
    record.write_text(pending, encoding="utf-8")
    environ = {
        "FLINTTRADE_PARENT_PID": "77",
        "FLINTTRADE_BOOT_ID": TEST_BOOT_ID,
        "FLINTTRADE_LAUNCH_TOKEN": f" {token} ",
        "FLINTTRADE_SIDECAR_RECORD_PATH": str(record),
    }

    assert entry.promote_application_pid_record(environ=environ, pid=5678) is False
    assert entry.clear_pending_application_pid_record(environ=environ) is False
    assert record.read_text(encoding="utf-8") == pending


@pytest.mark.unit
def test_backend_boot_refuses_untracked_application_pid(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(entry, "promote_application_pid_record", lambda: False)

    with pytest.raises(SystemExit, match="application PID record promotion failed"):
        entry.require_application_pid_record()


@pytest.mark.unit
def test_promotion_failure_clears_exact_pending_record_before_refusing_boot(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    token = "a" * 64
    record = tmp_path / "desktop_backend.pid"
    record.write_text(f"v3\n1234\npending\n77\n{TEST_BOOT_ID}\n{token}\n", encoding="utf-8")
    environ = {
        "FLINTTRADE_PARENT_PID": "77",
        "FLINTTRADE_BOOT_ID": TEST_BOOT_ID,
        "FLINTTRADE_LAUNCH_TOKEN": token,
        "FLINTTRADE_SIDECAR_RECORD_PATH": str(record),
    }
    stream = io.StringIO()
    monkeypatch.setattr(entry, "promote_application_pid_record", lambda **_kwargs: False)

    with pytest.raises(SystemExit, match="application PID record promotion failed"):
        entry.require_application_pid_record(environ=environ, stream=stream)

    assert record.exists() is False
    assert stream.getvalue() == (f"FLINTTRADE_BACKEND_PENDING_EXIT_ACK token={token} reason=promotion-failed\n")


@pytest.mark.unit
def test_promotion_failure_ack_survives_a_transient_python_cleanup_failure(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "a" * 64
    environ = {
        "FLINTTRADE_PARENT_PID": "77",
        "FLINTTRADE_BOOT_ID": TEST_BOOT_ID,
        "FLINTTRADE_LAUNCH_TOKEN": token,
        "FLINTTRADE_SIDECAR_RECORD_PATH": "/temporarily/unavailable/desktop_backend.pid",
    }
    stream = io.StringIO()
    monkeypatch.setattr(entry, "promote_application_pid_record", lambda **_kwargs: False)
    monkeypatch.setattr(entry, "clear_pending_application_pid_record", lambda **_kwargs: False)

    with pytest.raises(SystemExit, match="application PID record promotion failed"):
        entry.require_application_pid_record(environ=environ, stream=stream)

    assert stream.getvalue() == (f"FLINTTRADE_BACKEND_PENDING_EXIT_ACK token={token} reason=promotion-failed\n")


@pytest.mark.unit
def test_promotion_and_pending_cleanup_share_the_record_transition_guard(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    token = "a" * 64
    record = tmp_path / "desktop_backend.pid"
    pending = f"v3\n1234\npending\n77\n{TEST_BOOT_ID}\n{token}\n"
    environ = {
        "FLINTTRADE_PARENT_PID": "77",
        "FLINTTRADE_BOOT_ID": TEST_BOOT_ID,
        "FLINTTRADE_LAUNCH_TOKEN": token,
        "FLINTTRADE_SIDECAR_RECORD_PATH": str(record),
    }
    guarded: list[Path] = []

    @contextmanager
    def record_guard(path: Path) -> Iterator[None]:
        guarded.append(path)
        yield

    monkeypatch.setattr(entry, "_record_transition_guard", record_guard)

    record.write_text(pending, encoding="utf-8")
    assert entry.promote_application_pid_record(environ=environ, pid=5678) is True
    assert guarded == [record]

    record.write_text(pending, encoding="utf-8")
    assert entry.clear_pending_application_pid_record(environ=environ) is True
    assert guarded == [record, record]


@pytest.mark.unit
def test_watchdog_off_without_env(entry: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(entry.PARENT_PID_ENV, raising=False)
    assert entry.start_parent_watchdog() is None


@pytest.mark.unit
def test_packaged_child_contract_is_published_only_for_frozen_sidecars(entry: ModuleType) -> None:
    environ: dict[str, str] = {}

    assert (
        entry.publish_packaged_child_contract(
            environ=environ,
            executable="/Applications/FlintTrade/flinttrade-backend",
            frozen=False,
        )
        is False
    )
    assert environ == {}

    assert (
        entry.publish_packaged_child_contract(
            environ=environ,
            executable="/Applications/FlintTrade/flinttrade-backend",
            frozen=True,
        )
        is True
    )
    assert environ == {
        "FLINTTRADE_PACKAGED_CHILD_EXECUTABLE": "/Applications/FlintTrade/flinttrade-backend",
        "FLINTTRADE_PACKAGED_CHILD_ARG": "--flinttrade-uploaded-strategy-child",
    }


@pytest.mark.unit
def test_packaged_child_dispatch_prevents_sidecar_reentry_and_shared_stdin(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_stdin = io.StringIO("FLINTTRADE_FORCE_EXIT\n")
    monkeypatch.setattr(entry.sys, "stdin", shared_stdin)
    for name in entry.DESKTOP_CONTROL_ENV:
        monkeypatch.setenv(name, "must-not-reach-child")
    observed: list[tuple[list[str], str, dict[str, str | None]]] = []

    def dispatch(argv: list[str]) -> bool:
        observed.append(
            (
                argv,
                entry.sys.stdin.read(),
                {name: entry.os.environ.get(name) for name in entry.DESKTOP_CONTROL_ENV},
            )
        )
        return True

    argv = ["flinttrade-backend", "--flinttrade-uploaded-strategy-child", "/tmp/strategy.py"]
    assert entry.dispatch_packaged_child_mode(argv=argv, dispatcher=dispatch) is True
    assert observed == [(argv, "", {name: None for name in entry.DESKTOP_CONTROL_ENV})]
    assert shared_stdin.tell() == 0


@pytest.mark.unit
def test_normal_sidecar_arguments_do_not_enter_packaged_child_mode(entry: ModuleType) -> None:
    assert (
        entry.dispatch_packaged_child_mode(
            argv=["flinttrade-backend", "--port", "0"],
            dispatcher=lambda _argv: pytest.fail("normal sidecar startup must not dispatch a child"),
        )
        is False
    )


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
def test_force_exit_requires_complete_owned_tree_termination(entry: ModuleType) -> None:
    exits: list[int] = []
    attempts: list[str] = []

    assert (
        entry._force_exit_owned_process_tree(
            lambda: attempts.append("terminate") or True,
            exit_process=exits.append,
        )
        is True
    )
    assert attempts == ["terminate"]
    assert exits == [1]

    exits.clear()
    assert (
        entry._force_exit_owned_process_tree(
            lambda: attempts.append("retain") or False,
            exit_process=exits.append,
        )
        is False
    )
    assert attempts == ["terminate", "retain"]
    assert exits == []

    assert entry._force_exit_owned_process_tree(None, exit_process=exits.append) is False
    assert exits == []


@pytest.mark.unit
def test_force_handler_retains_state_without_pending_proof_or_tree_containment(
    entry: ModuleType,
) -> None:
    exits: list[int] = []

    assert (
        entry._handle_force_exit(
            None,
            environ={},
            exit_process=exits.append,
        )
        is False
    )
    assert exits == []


@pytest.mark.unit
def test_posix_owned_tree_discovery_tracks_same_group_and_new_session_descendants(entry: ModuleType) -> None:
    processes = {
        100: entry._PosixProcess(pid=100, ppid=50, pgid=100, sid=50, start_token="root"),
        101: entry._PosixProcess(pid=101, ppid=100, pgid=100, sid=50, start_token="same-group"),
        102: entry._PosixProcess(pid=102, ppid=101, pgid=102, sid=102, start_token="new-session"),
        103: entry._PosixProcess(pid=103, ppid=1, pgid=102, sid=102, start_token="reparented-session-child"),
        900: entry._PosixProcess(pid=900, ppid=1, pgid=900, sid=50, start_token="foreign"),
    }

    owned = entry._discover_posix_owned_processes(
        processes,
        application_pid=100,
        application_group=100,
        tracked={100: "root"},
    )

    assert owned == {
        100: "root",
        101: "same-group",
        102: "new-session",
        103: "reparented-session-child",
    }

    after_session_leader_exit = {
        103: entry._PosixProcess(pid=103, ppid=1, pgid=102, sid=102, start_token="reparented-session-child"),
    }
    assert entry._discover_posix_owned_processes(
        after_session_leader_exit,
        application_pid=100,
        application_group=100,
        tracked={},
        tracked_groups={102},
    ) == {103: "reparented-session-child"}


@pytest.mark.unit
def test_posix_guardian_retains_tracked_identity_when_kernel_probe_is_transient(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processes = {
        100: entry._PosixProcess(pid=100, ppid=50, pgid=100, sid=50, start_token=""),
    }
    monkeypatch.setattr(entry, "_read_posix_process_table", lambda: processes)
    monkeypatch.setattr(
        entry,
        "_posix_process_start_token",
        lambda _pid: (_ for _ in ()).throw(OSError("transient")),
    )

    _, tracked = entry._refresh_posix_owned_processes(100, 100, {100: "kernel-start:1"})

    assert tracked == {100: "kernel-start:1"}


@pytest.mark.unit
def test_posix_guardian_does_not_retain_the_pre_isolation_parent_group(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processes = {
        100: entry._PosixProcess(
            pid=100,
            ppid=50,
            pgid=50,
            sid=50,
            start_token="",
        ),
        900: entry._PosixProcess(
            pid=900,
            ppid=1,
            pgid=50,
            sid=50,
            start_token="",
        ),
    }
    tracked_groups = {100}
    monkeypatch.setattr(entry, "_read_posix_process_table", lambda: processes)
    monkeypatch.setattr(entry.os, "getpid", lambda: 50)
    monkeypatch.setattr(entry, "_posix_process_start_token", lambda pid: f"start:{pid}")

    _, tracked = entry._refresh_posix_owned_processes(
        100,
        100,
        {},
        tracked_groups,
    )

    assert tracked == {100: "start:100"}
    assert tracked_groups == {100}
    assert entry._discover_posix_owned_processes(
        processes,
        application_pid=100,
        application_group=100,
        tracked=tracked,
        guardian_pid=50,
        tracked_groups=tracked_groups,
    ) == {100: "start:100"}


@pytest.mark.unit
def test_windows_owned_tree_uses_a_kill_on_close_job(entry: ModuleType) -> None:
    calls: list[object] = []

    class FakeJobApi:
        def create_job(self) -> int:
            calls.append("create")
            return 99

        def enable_kill_on_close(self, handle: int) -> bool:
            calls.append(("kill-on-close", handle))
            return True

        def assign_current_process(self, handle: int) -> bool:
            calls.append(("assign", handle))
            return True

        def close_handle(self, handle: int) -> bool:
            calls.append(("close", handle))
            return True

    terminator = entry._prepare_windows_owned_process_tree(api=FakeJobApi())

    assert terminator is not None
    assert calls == ["create", ("kill-on-close", 99), ("assign", 99)]
    assert terminator() is True
    assert calls[-1] == ("close", 99)


@pytest.mark.unit
def test_windows_job_setup_fails_closed_and_releases_unassigned_handle(entry: ModuleType) -> None:
    calls: list[object] = []

    class FailingJobApi:
        def create_job(self) -> int:
            return 99

        def enable_kill_on_close(self, handle: int) -> bool:
            calls.append(("kill-on-close", handle))
            return False

        def assign_current_process(self, _handle: int) -> bool:
            pytest.fail("an unconfigured job must not receive the process")

        def close_handle(self, handle: int) -> bool:
            calls.append(("close", handle))
            return True

    assert entry._prepare_windows_owned_process_tree(api=FailingJobApi()) is None
    assert calls == [("kill-on-close", 99), ("close", 99)]


@pytest.mark.unit
def test_stdin_force_exit_targets_the_complete_owned_process_tree(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested = threading.Event()
    exit_codes: list[int] = []
    tree_terminations: list[str] = []
    monkeypatch.setattr(entry.os, "_exit", exit_codes.append)

    thread = entry.start_stdin_shutdown_listener(
        requested.set,
        stream=io.StringIO("FLINTTRADE_FORCE_EXIT\n"),
        terminate_owned_tree=lambda: tree_terminations.append("terminate") or True,
    )

    thread.join(timeout=1)
    assert tree_terminations == ["terminate"]
    assert exit_codes == [1]
    assert requested.is_set() is False


@pytest.mark.unit
def test_pending_force_exit_clears_exact_record_and_acknowledges_before_exit(
    entry: ModuleType,
    tmp_path: Path,
) -> None:
    token = "a" * 64
    record = tmp_path / "desktop_backend.pid"
    record.write_text(f"v3\n1234\npending\n77\n{TEST_BOOT_ID}\n{token}\n", encoding="utf-8")
    environ = {
        "FLINTTRADE_PARENT_PID": "77",
        "FLINTTRADE_BOOT_ID": TEST_BOOT_ID,
        "FLINTTRADE_LAUNCH_TOKEN": token,
        "FLINTTRADE_SIDECAR_RECORD_PATH": str(record),
    }
    stream = io.StringIO()
    exits: list[int] = []

    assert (
        entry._handle_force_exit(
            lambda: pytest.fail("a pre-import pending application has no backend tree to terminate"),
            environ=environ,
            stream=stream,
            exit_process=exits.append,
        )
        is True
    )

    assert record.exists() is False
    assert stream.getvalue() == f"FLINTTRADE_BACKEND_PENDING_EXIT_ACK token={token} reason=force-exit\n"
    assert exits == [1]


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
        terminate_owned_tree=lambda: True,
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
def test_stdin_eof_uses_orphan_tree_fallback(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def request_shutdown() -> None:
        pass

    def terminate_owned_tree() -> bool:
        return True

    orphaned: list[tuple[object, object]] = []
    monkeypatch.setattr(
        entry,
        "_exit_orphaned",
        lambda request, terminate_tree: orphaned.append((request, terminate_tree)),
    )

    thread = entry.start_stdin_shutdown_listener(
        request_shutdown,
        stream=io.StringIO(""),
        terminate_owned_tree=terminate_owned_tree,
    )

    thread.join(timeout=1)
    assert orphaned == [(request_shutdown, terminate_owned_tree)]


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
def test_posix_parent_identity_rejects_shell_pid_reuse_in_pyinstaller_topology(
    entry: ModuleType,
) -> None:
    original = "/Applications/FlintTrade.app/Contents/MacOS/FlintTrade\t77\tFri Jul 11 10:11:12 2026"
    reused = "/usr/bin/python3 unrelated.py\t77\tFri Jul 11 10:11:13 2026"

    assert (
        entry._posix_parent_alive(
            77,
            track_reparent=False,
            expected_identity=original,
            identity_lookup=lambda _pid: original,
        )
        is True
    )
    assert (
        entry._posix_parent_alive(
            77,
            track_reparent=False,
            expected_identity=original,
            identity_lookup=lambda _pid: reused,
        )
        is False
    )


@pytest.mark.unit
def test_posix_parent_identity_fails_closed_without_a_kernel_identity(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        entry.os,
        "kill",
        lambda *_args: pytest.fail("PID-only fallback must not run after identity was required"),
    )

    assert (
        entry._posix_parent_alive(
            77,
            track_reparent=False,
            expected_identity="/Applications/FlintTrade\t77\tmacos-start-time:100:1",
            identity_lookup=lambda _pid: None,
        )
        is False
    )


@pytest.mark.unit
def test_posix_parent_identity_parser_matches_rust_process_identity(entry: ModuleType) -> None:
    output = "77 /Applications/FlintTrade.app/Contents/MacOS/FlintTrade --runtime-flag"

    assert entry._parse_posix_process_identity(output, 77, "kernel-start:123456789") == (
        "/Applications/FlintTrade.app/Contents/MacOS/FlintTrade --runtime-flag\t77\tkernel-start:123456789"
    )
    assert entry._parse_posix_process_identity(output, 88, "kernel-start:123456789") is None
    assert entry._parse_posix_process_identity("", 77, "kernel-start:123456789") is None


@pytest.mark.unit
def test_posix_identity_distinguishes_reuse_within_the_same_wall_clock_second(entry: ModuleType) -> None:
    output = "77 /Applications/FlintTrade.app/Contents/MacOS/FlintTrade"

    first = entry._parse_posix_process_identity(output, 77, "kernel-start:1000001")
    reused = entry._parse_posix_process_identity(output, 77, "kernel-start:1000002")

    assert first != reused


@pytest.mark.integration
@pytest.mark.skipif(os.name == "nt", reason="POSIX kernel process identity")
def test_posix_process_identity_is_stable_and_uses_a_kernel_start_token(entry: ModuleType) -> None:
    first = entry._posix_process_identity(os.getpid())
    second = entry._posix_process_identity(os.getpid())

    assert first == second
    assert first is not None
    command, pid, start_token = first.rsplit("\t", 2)
    assert command
    assert pid == str(os.getpid())
    assert start_token.startswith(("linux-start-ticks:", "macos-start-time:"))


@pytest.mark.unit
def test_posix_watcher_returns_after_first_orphan_request(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, object]] = []
    request_shutdown = object()
    terminate_owned_tree = object()

    monkeypatch.setattr(entry.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(entry, "_posix_parent_alive", lambda *_args, **_kwargs: False)

    def exit_once(request: object, terminate_tree: object) -> None:
        calls.append((request, terminate_tree))
        if len(calls) > 1:
            raise AssertionError("watcher requested orphan shutdown more than once")

    monkeypatch.setattr(entry, "_exit_orphaned", exit_once)

    entry._watch_parent_posix(1234, request_shutdown, terminate_owned_tree)

    assert calls == [(request_shutdown, terminate_owned_tree)]


@pytest.mark.unit
def test_posix_watcher_polls_the_spawn_time_shell_identity_for_pyinstaller_child(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell_identity = "/Applications/FlintTrade.app/Contents/MacOS/FlintTrade\t77\tstable-start"
    probes: list[tuple[int, bool, str | None]] = []
    orphaned: list[object] = []
    request_shutdown = object()

    monkeypatch.setattr(entry.os, "getppid", lambda: 1234)
    monkeypatch.setattr(entry.time, "sleep", lambda _seconds: None)

    def parent_alive(
        pid: int,
        *,
        track_reparent: bool,
        expected_identity: str | None = None,
        **_kwargs: object,
    ) -> bool:
        probes.append((pid, track_reparent, expected_identity))
        return False

    monkeypatch.setattr(entry, "_posix_parent_alive", parent_alive)
    monkeypatch.setattr(entry, "_exit_orphaned", lambda request, _tree: orphaned.append(request))

    entry._watch_parent_posix(77, request_shutdown, parent_identity=shell_identity)

    assert probes == [(77, False, shell_identity)]
    assert orphaned == [request_shutdown]


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
        terminate_owned_tree = mod._prepare_owned_process_tree()
        assert terminate_owned_tree is not None
        assert mod.start_parent_watchdog(terminate_owned_tree=terminate_owned_tree) is not None
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


@pytest.mark.integration
@pytest.mark.skipif(os.name == "nt", reason="POSIX process-tree containment")
def test_posix_guardian_outlives_leader_and_reaps_same_group_and_new_session_descendants(
    entry: ModuleType,
) -> None:
    """Crash the Python leader after spawning descendants in two POSIX sessions."""
    script = textwrap.dedent(
        f"""
        import importlib.util, os, subprocess, sys, time
        spec = importlib.util.spec_from_file_location("desktop_backend_entry", {str(ENTRY_SCRIPT)!r})
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.POSIX_GUARDIAN_POLL_SECONDS = 0.01
        terminate_owned_tree = mod._prepare_owned_process_tree()
        assert terminate_owned_tree is not None
        same_group = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        new_session = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        print(os.getpid(), same_group.pid, new_session.pid, flush=True)
        time.sleep(0.25)
        os._exit(23)
        """
    )
    guardian = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    descendant_pids: list[int] = []
    try:
        stdout, stderr = guardian.communicate(timeout=10)
        assert guardian.returncode == 23, stderr
        leader_pid, same_group_pid, new_session_pid = (
            int(value) for value in stdout.strip().splitlines()[-1].split()
        )
        descendant_pids = [same_group_pid, new_session_pid]
        assert leader_pid != guardian.pid

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if all(not entry._posix_pid_alive(pid) for pid in descendant_pids):
                break
            time.sleep(0.05)
        assert all(not entry._posix_pid_alive(pid) for pid in descendant_pids)
    finally:
        if guardian.poll() is None:
            guardian.kill()
            guardian.wait(timeout=5)
        for pid in descendant_pids:
            if entry._posix_pid_alive(pid):
                os.kill(pid, signal.SIGKILL)


@pytest.mark.integration
@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object containment")
def test_windows_job_kills_descendant_when_python_leader_exits(entry: ModuleType) -> None:
    script = textwrap.dedent(
        f"""
        import importlib.util, os, subprocess, sys
        spec = importlib.util.spec_from_file_location("desktop_backend_entry", {str(ENTRY_SCRIPT)!r})
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod._prepare_owned_process_tree() is not None
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(child.pid, flush=True)
        os._exit(0)
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    descendant_pid = int(completed.stdout.strip().splitlines()[-1])

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and entry._posix_pid_alive(descendant_pid):
        time.sleep(0.05)
    assert entry._posix_pid_alive(descendant_pid) is False
