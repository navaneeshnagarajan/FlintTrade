"""PyInstaller entry script for the native-desktop backend sidecar.

This thin wrapper is the ``__main__`` PyInstaller freezes. It exists (rather
than pointing PyInstaller straight at ``flinttrade_core/desktop.py``) so that
the entry runs as a proper package import — ``flinttrade_core.desktop`` uses
relative imports (``from .app import …``) that only resolve when the module is
imported by name, not executed as a loose script.

It also hosts the desktop-only **parent-liveness watchdog**. The Tauri shell
passes its own PID via ``FLINTTRADE_PARENT_PID``; a daemon thread watches that
process and exits the sidecar cleanly when the shell dies (crash, force-quit,
task-manager kill), so no orphaned backend keeps running and accumulating
across relaunches. The watchdog lives here — not in ``flinttrade_core`` —
because it is desktop-shell behaviour: plain CLI/``make start`` runs never set
the variable and are unaffected.

PyInstaller one-file builds run this Python application below a separate
bootloader process. Before importing the backend, this wrapper creates
platform containment, promotes the shell's exact boot-bound recovery record to
the backend leader PID, and announces that PID on stdout. On POSIX an external
guardian remains alive until same-group and tracked new-session descendants are
gone. On Windows a non-breakaway Job Object kills its complete tree when the
last application handle closes.

The frozen executable also exposes one explicit child mode for uploaded
strategies. It is dispatched before sidecar control starts, strips desktop
ownership variables, and replaces inherited stdin with the null device so a
worker cannot consume shell shutdown commands or re-enter backend startup.

The real serving logic lives in :mod:`flinttrade_core.desktop`.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator, TextIO

#: Environment variable the Tauri shell sets to its own OS process id.
PARENT_PID_ENV = "FLINTTRADE_PARENT_PID"
PARENT_IDENTITY_ENV = "FLINTTRADE_PARENT_IDENTITY"

#: Exact recovery record path and launch token supplied by the Tauri shell.
SIDECAR_RECORD_PATH_ENV = "FLINTTRADE_SIDECAR_RECORD_PATH"
BOOT_ID_ENV = "FLINTTRADE_BOOT_ID"
LAUNCH_TOKEN_ENV = "FLINTTRADE_LAUNCH_TOKEN"
SIDECAR_RECORD_VERSION = "v3"

#: Frozen-child execution contract published to backend code.
PACKAGED_CHILD_EXECUTABLE_ENV = "FLINTTRADE_PACKAGED_CHILD_EXECUTABLE"
PACKAGED_CHILD_ARG_ENV = "FLINTTRADE_PACKAGED_CHILD_ARG"
PACKAGED_CHILD_ARG = "--flinttrade-uploaded-strategy-child"

#: Variables that belong only to the desktop sidecar control process. A
#: packaged worker must not inherit them and impersonate the backend.
DESKTOP_CONTROL_ENV = frozenset(
    {
        PARENT_PID_ENV,
        PARENT_IDENTITY_ENV,
        SIDECAR_RECORD_PATH_ENV,
        BOOT_ID_ENV,
        LAUNCH_TOKEN_ENV,
        PACKAGED_CHILD_EXECUTABLE_ENV,
        PACKAGED_CHILD_ARG_ENV,
    }
)

#: How often (seconds) the POSIX watchdog polls for parent liveness.
POLL_INTERVAL_SECONDS = 2.0

#: Command the Tauri shell writes to stdin before its bounded hard-kill fallback.
SHUTDOWN_COMMAND = "FLINTTRADE_SHUTDOWN"

#: Exact-pipe hard stop used only for the application launched by this shell.
FORCE_EXIT_COMMAND = "FLINTTRADE_FORCE_EXIT"

#: Stdout handshake that identifies the real Python application process.
APPLICATION_PID_SENTINEL = "FLINTTRADE_BACKEND_PID"

#: Proof that this Python application will exit before importing the backend,
#: making only its exact pending recovery record safe for guarded cleanup.
PENDING_RECORD_EXIT_ACK_SENTINEL = "FLINTTRADE_BACKEND_PENDING_EXIT_ACK"

#: Last-resort orphan timeout if graceful unwinding is unable to stop Waitress.
ORPHAN_GRACE_SECONDS = 12.0

#: Poll interval for forwarding a lock-free SIGTERM flag outside the handler.
SIGNAL_RELAY_POLL_SECONDS = 0.05

#: Brief wait for Rust to publish the pending record after spawning us.
RECORD_PUBLISH_WAIT_SECONDS = 2.0
RECORD_PUBLISH_POLL_SECONDS = 0.01

#: Poll cadence for the external POSIX containment guardian.
POSIX_GUARDIAN_POLL_SECONDS = 0.05
POSIX_GUARDIAN_KILL_SECONDS = 5.0

_RECORD_TRANSITION_THREAD_LOCK = threading.Lock()


def _valid_hex_identity(value: str, *, minimum: int, maximum: int) -> bool:
    return (
        minimum <= len(value) <= maximum
        and len(value) % 2 == 0
        and all(character in "0123456789abcdefABCDEF" for character in value)
    )


def publish_packaged_child_contract(
    *,
    environ: dict[str, str] | None = None,
    executable: str | None = None,
    frozen: bool | None = None,
) -> bool:
    """Publish the frozen executable + mode argument used for safe child work."""
    env = os.environ if environ is None else environ
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if not is_frozen:
        return False
    env[PACKAGED_CHILD_EXECUTABLE_ENV] = sys.executable if executable is None else executable
    env[PACKAGED_CHILD_ARG_ENV] = PACKAGED_CHILD_ARG
    return True


def dispatch_packaged_child_mode(
    *,
    argv: list[str] | None = None,
    dispatcher: Callable[[list[str]], bool] | None = None,
) -> bool:
    """Run an explicit frozen child before sidecar control threads can start.

    The entrypoint enforces a detached stdin even if a caller forgets to do so,
    and removes every sidecar-control variable before importing engine code.
    """
    arguments = list(sys.argv if argv is None else argv)
    if len(arguments) < 2 or arguments[1] != PACKAGED_CHILD_ARG:
        return False

    for name in DESKTOP_CONTROL_ENV:
        os.environ.pop(name, None)

    if dispatcher is None:
        from flinttrade_engine.strategy_runner import (  # noqa: PLC0415 - child-only import
            dispatch_frozen_strategy_child,
        )

        dispatcher = dispatch_frozen_strategy_child

    original_stdin = sys.stdin
    with open(os.devnull, encoding="utf-8") as detached_stdin:
        sys.stdin = detached_stdin
        try:
            handled = dispatcher(arguments)
        finally:
            sys.stdin = original_stdin
    if not handled:
        raise RuntimeError("packaged child dispatcher rejected the recognised child mode")
    return True


class _ShutdownCoordinator:
    """Hold an early shutdown request until the backend installs its callback."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requested = False
        self._callback: Callable[[], None] | None = None

    def request(self) -> bool:
        """Request shutdown once and notify the installed backend callback."""
        with self._lock:
            first_request = not self._requested
            self._requested = True
            callback = self._callback if first_request else None
        if callback is not None:
            callback()
        return first_request

    def install(self, callback: Callable[[], None]) -> None:
        """Install the live server callback and replay an early request."""
        with self._lock:
            self._callback = callback
            requested = self._requested
        if requested:
            callback()

    def uninstall(self, callback: Callable[[], None]) -> None:
        """Remove ``callback`` without disturbing a replacement callback."""
        with self._lock:
            if self._callback is callback:
                self._callback = None


class _SignalShutdownRelay:
    """Forward SIGTERM to the coordinator without taking locks in the handler."""

    def __init__(
        self,
        request_shutdown: Callable[[], object],
        *,
        poll_interval: float = SIGNAL_RELAY_POLL_SECONDS,
    ) -> None:
        self._request_shutdown = request_shutdown
        self._poll_interval = poll_interval
        self._requested = False

    def handle(self, _signum: int, _frame: object) -> None:
        """Record SIGTERM using one lock-free assignment on Python's main thread."""
        self._requested = True

    def _run(self) -> None:
        while not self._requested:
            time.sleep(self._poll_interval)
        self._request_shutdown()

    def start(self) -> threading.Thread:
        thread = threading.Thread(
            target=self._run,
            name="flinttrade-sigterm-shutdown-relay",
            daemon=True,
        )
        thread.start()
        return thread


def start_sigterm_shutdown_relay(
    request_shutdown: Callable[[], object],
) -> threading.Thread:
    """Install a lock-free SIGTERM handler and relay shutdown from a thread."""
    relay = _SignalShutdownRelay(request_shutdown)
    signal.signal(signal.SIGTERM, relay.handle)
    return relay.start()


def _parent_pid_from_env(environ: dict[str, str] | None = None) -> int | None:
    """Return the shell PID from ``FLINTTRADE_PARENT_PID``, if set and valid.

    Args:
        environ: Environment mapping (defaults to ``os.environ``; injectable
            for tests).

    Returns:
        The positive integer PID, or ``None`` when absent/invalid — in which
        case the watchdog stays off (CLI runs, tests, ``make start``).
    """
    env = os.environ if environ is None else environ
    raw = (env.get(PARENT_PID_ENV) or "").strip()
    if not raw:
        return None
    try:
        pid = int(raw)
    except ValueError:
        print(f"[desktop-sidecar] ignoring non-integer {PARENT_PID_ENV}={raw!r}", file=sys.stderr)
        return None
    return pid if pid > 0 else None


def announce_application_pid(*, stream: TextIO | None = None, pid: int | None = None) -> None:
    """Publish the real Python PID before backend boot or readiness work."""
    output = sys.stdout if stream is None else stream
    application_pid = os.getpid() if pid is None else pid
    print(f"{APPLICATION_PID_SENTINEL} pid={application_pid}", file=output, flush=True)


def _lock_record_guard_file(guard_file: BinaryIO) -> None:
    """Take the cross-process record-transition lock."""
    if os.name == "nt":
        import msvcrt  # noqa: PLC0415 - Windows-only

        guard_file.seek(0, os.SEEK_END)
        if guard_file.tell() == 0:
            guard_file.write(b"\0")
            guard_file.flush()
            os.fsync(guard_file.fileno())
        guard_file.seek(0)
        msvcrt.locking(guard_file.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl  # noqa: PLC0415 - POSIX-only

        fcntl.flock(guard_file.fileno(), fcntl.LOCK_EX)


def _unlock_record_guard_file(guard_file: BinaryIO) -> None:
    """Release the cross-process record-transition lock."""
    if os.name == "nt":
        import msvcrt  # noqa: PLC0415 - Windows-only

        guard_file.seek(0)
        msvcrt.locking(guard_file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl  # noqa: PLC0415 - POSIX-only

        fcntl.flock(guard_file.fileno(), fcntl.LOCK_UN)


@contextmanager
def _record_transition_guard(path: Path) -> Iterator[None]:
    """Serialise record promotion and cleanup across Rust and Python."""
    guard_path = path.with_name(f".{path.name}.lock")
    with _RECORD_TRANSITION_THREAD_LOCK, guard_path.open("a+b") as guard_file:
        if os.name != "nt":
            os.chmod(guard_path, 0o600)
        _lock_record_guard_file(guard_file)
        try:
            yield
        finally:
            _unlock_record_guard_file(guard_file)


def _sync_parent_directory(path: Path) -> None:
    """Persist a record rename on filesystems that permit directory fsync."""
    if os.name == "nt":
        return
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _atomically_replace_record(path: Path, expected: bytes, replacement: bytes, token: str) -> bool:
    """Replace one exact record without exposing truncate/write crash states."""
    temporary = path.with_name(f".{path.name}.{token}.{os.getpid()}.tmp")
    try:
        if path.read_bytes() != expected:
            return False
        with temporary.open("xb") as record_file:
            record_file.write(replacement)
            record_file.flush()
            os.fsync(record_file.fileno())
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        if path.read_bytes() != expected:
            return False
        os.replace(temporary, path)
        _sync_parent_directory(path)
        return True
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def promote_application_pid_record(
    *,
    environ: dict[str, str] | None = None,
    pid: int | None = None,
    wait_seconds: float = RECORD_PUBLISH_WAIT_SECONDS,
) -> bool:
    """Promote this launch's exact pending record to the real Python PID."""
    env = os.environ if environ is None else environ
    raw_path = (env.get(SIDECAR_RECORD_PATH_ENV) or "").strip()
    launch_token = env.get(LAUNCH_TOKEN_ENV) or ""
    boot_id = env.get(BOOT_ID_ENV) or ""
    shell_pid = _parent_pid_from_env(env)
    application_pid = os.getpid() if pid is None else pid
    if (
        not raw_path
        or shell_pid is None
        or application_pid <= 0
        or not _valid_hex_identity(boot_id, minimum=16, maximum=512)
        or not _valid_hex_identity(launch_token, minimum=64, maximum=64)
    ):
        return False

    path = Path(raw_path)
    deadline = time.monotonic() + max(wait_seconds, 0.0)
    while True:
        try:
            with _record_transition_guard(path):
                contents_bytes = path.read_bytes()

                try:
                    contents = contents_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    return False

                lines = contents.splitlines()
                if len(lines) != 6 or lines[0].strip() != SIDECAR_RECORD_VERSION:
                    return False
                try:
                    launcher_pid = int(lines[1].strip())
                    recorded_shell_pid = int(lines[3].strip())
                except ValueError:
                    return False
                if (
                    launcher_pid <= 0
                    or lines[2].strip() != "pending"
                    or recorded_shell_pid != shell_pid
                    or lines[4] != boot_id
                    or lines[5] != launch_token
                ):
                    return False

                promoted = (
                    f"{SIDECAR_RECORD_VERSION}\n{launcher_pid}\n{application_pid}\n"
                    f"{shell_pid}\n{boot_id}\n{launch_token}\n"
                ).encode("ascii")
                if not _atomically_replace_record(path, contents_bytes, promoted, launch_token):
                    return False
        except FileNotFoundError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(RECORD_PUBLISH_POLL_SECONDS)
            continue
        except OSError:
            return False
        return True


def clear_pending_application_pid_record(
    *,
    environ: dict[str, str] | None = None,
) -> bool:
    """Remove only this launch's exact still-pending recovery record."""
    env = os.environ if environ is None else environ
    raw_path = (env.get(SIDECAR_RECORD_PATH_ENV) or "").strip()
    launch_token = env.get(LAUNCH_TOKEN_ENV) or ""
    boot_id = env.get(BOOT_ID_ENV) or ""
    shell_pid = _parent_pid_from_env(env)
    if (
        not raw_path
        or shell_pid is None
        or not _valid_hex_identity(boot_id, minimum=16, maximum=512)
        or not _valid_hex_identity(launch_token, minimum=64, maximum=64)
    ):
        return False

    path = Path(raw_path)
    try:
        with _record_transition_guard(path):
            contents = path.read_text(encoding="utf-8")
            lines = contents.splitlines()
            if len(lines) != 6 or lines[0].strip() != SIDECAR_RECORD_VERSION:
                return False
            try:
                launcher_pid = int(lines[1].strip())
                recorded_shell_pid = int(lines[3].strip())
            except ValueError:
                return False
            if (
                launcher_pid <= 0
                or lines[2].strip() != "pending"
                or recorded_shell_pid != shell_pid
                or lines[4] != boot_id
                or lines[5] != launch_token
            ):
                return False
            path.unlink()
    except (OSError, UnicodeError):
        return False
    return True


def announce_pending_record_exit_ack(
    reason: str,
    *,
    environ: dict[str, str] | None = None,
    stream: TextIO | None = None,
) -> bool:
    """Flush exact-token proof that this pending record is safe to clear."""
    env = os.environ if environ is None else environ
    output = sys.stdout if stream is None else stream
    token = env.get(LAUNCH_TOKEN_ENV) or ""
    if len(token) != 64 or any(character not in "0123456789abcdefABCDEF" for character in token):
        return False
    print(f"{PENDING_RECORD_EXIT_ACK_SENTINEL} token={token} reason={reason}", file=output, flush=True)
    return True


def require_application_pid_record(
    *,
    environ: dict[str, str] | None = None,
    stream: TextIO | None = None,
) -> None:
    """Refuse to start an application process the shell cannot track exactly."""
    promoted = promote_application_pid_record() if environ is None else promote_application_pid_record(environ=environ)
    if not promoted:
        clear_pending_application_pid_record(environ=environ)
        announce_pending_record_exit_ack("promotion-failed", environ=environ, stream=stream)
        raise SystemExit("application PID record promotion failed; refusing untracked backend boot")


def _force_exit_owned_process_tree(
    terminate_tree: Callable[[], bool] | None,
    *,
    exit_process: Callable[[int], object] | None = None,
) -> bool:
    """Exit only after an exact current-process tree termination succeeds."""
    if terminate_tree is None:
        return False
    try:
        terminated = terminate_tree()
    except OSError as exc:
        print(f"[desktop-sidecar] owned process-tree termination failed: {exc}", file=sys.stderr, flush=True)
        return False
    if not terminated:
        return False
    exit_now = os._exit if exit_process is None else exit_process
    exit_now(1)
    return True


class _PosixProcess:
    """One process-table row used by the external containment guardian."""

    __slots__ = ("pid", "ppid", "pgid", "sid", "start_token")

    def __init__(self, *, pid: int, ppid: int, pgid: int, sid: int, start_token: str) -> None:
        self.pid = pid
        self.ppid = ppid
        self.pgid = pgid
        self.sid = sid
        self.start_token = start_token


def _posix_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_posix_process_table(
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> dict[int, _PosixProcess]:
    """Snapshot PID ancestry and process groups without trusting command text."""
    run_command = subprocess.run if run is None else run
    result = run_command(
        ["ps", "-axo", "pid=,ppid=,pgid="],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise OSError(f"ps process-tree query exited with status {result.returncode}: {result.stderr.strip()}")
    processes: dict[int, _PosixProcess] = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) != 3:
            continue
        try:
            pid, ppid, pgid = (int(value) for value in fields)
        except ValueError:
            continue
        if pid <= 0 or ppid < 0 or pgid <= 0:
            continue
        processes[pid] = _PosixProcess(
            pid=pid,
            ppid=ppid,
            pgid=pgid,
            # A newly-created POSIX session starts with SID == PGID == PID.
            # PGID is enough for discovery; the field keeps that relationship
            # explicit in tests and future platform-specific snapshots.
            sid=pgid,
            start_token="",
        )
    return processes


def _discover_posix_owned_processes(
    processes: dict[int, _PosixProcess],
    *,
    application_pid: int,
    application_group: int,
    tracked: dict[int, str],
    guardian_pid: int | None = None,
    tracked_groups: set[int] | None = None,
) -> dict[int, str]:
    """Expand exact tracked PIDs through ancestry and owned process groups."""
    owned: dict[int, str] = {}
    for pid, start_token in tracked.items():
        process = processes.get(pid)
        if process is not None and (not process.start_token or process.start_token == start_token):
            owned[pid] = start_token
    if application_pid in processes:
        owned.setdefault(application_pid, processes[application_pid].start_token)
    if guardian_pid is not None:
        for pid, process in processes.items():
            if process.ppid == guardian_pid:
                owned.setdefault(pid, process.start_token)

    changed = True
    while changed:
        changed = False
        owned_groups = {application_group, *(tracked_groups or set())}
        owned_groups.update(
            process.pgid
            for pid, process in processes.items()
            if pid in owned and process.pid == process.pgid
        )
        for pid, process in processes.items():
            if pid in owned:
                continue
            if process.ppid in owned or process.pgid in owned_groups:
                owned[pid] = process.start_token
                changed = True
    return owned


def _refresh_posix_owned_processes(
    application_pid: int,
    application_group: int,
    tracked: dict[int, str],
    tracked_groups: set[int] | None = None,
) -> tuple[dict[int, _PosixProcess], dict[int, str]]:
    processes = _read_posix_process_table()
    discovered = _discover_posix_owned_processes(
        processes,
        application_pid=application_pid,
        application_group=application_group,
        tracked=tracked,
        guardian_pid=os.getpid(),
        tracked_groups=tracked_groups,
    )
    refreshed: dict[int, str] = {}
    for pid in discovered:
        expected = tracked.get(pid)
        try:
            start_token = _posix_process_start_token(pid)
        except OSError:
            if expected is not None:
                refreshed[pid] = expected
                continue
            raise
        if start_token is None:
            continue
        if expected is not None and expected != start_token:
            continue
        refreshed[pid] = start_token
        # Persist only groups proved to have been created by an owned group
        # leader. Immediately after fork the application can briefly inherit
        # the launcher's group before it calls setpgid(); remembering that
        # inherited PGID would make unrelated launcher processes look owned.
        if tracked_groups is not None and processes[pid].pid == processes[pid].pgid:
            tracked_groups.add(processes[pid].pgid)
    return processes, refreshed


def _reap_guardian_children() -> None:
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid <= 0:
            return


def _terminate_posix_owned_processes(
    application_pid: int,
    application_group: int,
    tracked: dict[int, str],
    tracked_groups: set[int],
) -> bool:
    """Kill and confirm every still-identical process owned by the backend."""
    deadline = time.monotonic() + POSIX_GUARDIAN_KILL_SECONDS
    sent_group_kill = False
    while time.monotonic() < deadline:
        try:
            processes, tracked = _refresh_posix_owned_processes(
                application_pid,
                application_group,
                tracked,
                tracked_groups,
            )
        except OSError:
            time.sleep(POSIX_GUARDIAN_POLL_SECONDS)
            continue

        if not tracked:
            _reap_guardian_children()
            return True

        if not sent_group_kill:
            try:
                os.killpg(application_group, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError as exc:
                print(f"[desktop-sidecar] process-group cleanup failed: {exc}", file=sys.stderr, flush=True)
            sent_group_kill = True

        for pid, expected_start in tuple(tracked.items()):
            process = processes.get(pid)
            if process is None:
                continue
            try:
                current_start = _posix_process_start_token(pid)
            except OSError:
                continue
            if current_start != expected_start:
                continue
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError as exc:
                print(f"[desktop-sidecar] descendant cleanup failed for pid {pid}: {exc}", file=sys.stderr, flush=True)
        _reap_guardian_children()
        time.sleep(POSIX_GUARDIAN_POLL_SECONDS)
    return False


def _wait_status_exit_code(status: int) -> int:
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return 1


def _enable_linux_child_subreaper() -> bool:
    if not sys.platform.startswith("linux"):
        return True
    import ctypes  # noqa: PLC0415 - Linux-only

    libc = ctypes.CDLL(None, use_errno=True)
    prctl = libc.prctl
    prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    prctl.restype = ctypes.c_int
    return prctl(36, 1, 0, 0, 0) == 0  # PR_SET_CHILD_SUBREAPER


def _run_posix_containment_guardian(application_pid: int, control_fd: int) -> None:
    """Remain outside the backend group until its complete owned tree is gone."""
    try:
        os.close(0)
    except OSError:
        pass
    os.set_blocking(control_fd, False)
    force_requested = False

    def request_force(_signum: int, _frame: object) -> None:
        nonlocal force_requested
        force_requested = True

    signal.signal(signal.SIGTERM, request_force)
    signal.signal(signal.SIGINT, request_force)

    tracked: dict[int, str] = {}
    tracked_groups = {application_pid}
    status: int | None = None
    while status is None and not force_requested:
        try:
            _processes, tracked = _refresh_posix_owned_processes(
                application_pid,
                application_pid,
                tracked,
                tracked_groups,
            )
        except OSError as exc:
            print(f"[desktop-sidecar] containment snapshot failed: {exc}", file=sys.stderr, flush=True)
        try:
            command = os.read(control_fd, 64)
        except BlockingIOError:
            command = b""
        except OSError:
            command = b""
        if b"force" in command:
            force_requested = True
            break
        try:
            waited_pid, waited_status = os.waitpid(application_pid, os.WNOHANG)
        except ChildProcessError:
            waited_pid, waited_status = application_pid, 1 << 8
        if waited_pid == application_pid:
            status = waited_status
            break
        time.sleep(POSIX_GUARDIAN_POLL_SECONDS)

    if force_requested:
        try:
            os.kill(application_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError as exc:
            print(f"[desktop-sidecar] backend leader cleanup failed: {exc}", file=sys.stderr, flush=True)
        try:
            _pid, status = os.waitpid(application_pid, 0)
        except ChildProcessError:
            status = 1 << 8

    exit_code = _wait_status_exit_code(status if status is not None else 1 << 8)
    while not _terminate_posix_owned_processes(
        application_pid,
        application_pid,
        tracked,
        tracked_groups,
    ):
        print(
            "[desktop-sidecar] process-tree cleanup remains unresolved; guardian is retaining recovery state",
            file=sys.stderr,
            flush=True,
        )
        time.sleep(POSIX_GUARDIAN_POLL_SECONDS)
    os.close(control_fd)
    os._exit(exit_code)


def _prepare_posix_owned_process_tree() -> Callable[[], bool] | None:
    """Fork an external guardian, then isolate the backend leader in a group."""
    if not _enable_linux_child_subreaper():
        return None
    read_fd, write_fd = os.pipe()
    try:
        application_pid = os.fork()
    except OSError:
        os.close(read_fd)
        os.close(write_fd)
        return None
    if application_pid > 0:
        os.close(write_fd)
        _run_posix_containment_guardian(application_pid, read_fd)
        raise AssertionError("POSIX containment guardian returned")

    os.close(read_fd)
    os.set_inheritable(write_fd, False)
    child_pid = os.getpid()
    try:
        os.setpgid(0, 0)
    except OSError:
        if os.getpgrp() != child_pid:
            os.close(write_fd)
            return None
    if os.getpgrp() != child_pid:
        os.close(write_fd)
        return None

    requested = False

    def terminate() -> bool:
        nonlocal requested
        if requested or os.getpid() != child_pid or os.getpgrp() != child_pid:
            return False
        try:
            os.write(write_fd, b"force\n")
        except OSError:
            return False
        requested = True
        return True

    return terminate


class _WindowsJobApi:
    """Small ctypes wrapper for a non-breakaway kill-on-close Job Object."""

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x0000_2000
    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9

    def __init__(self) -> None:
        import ctypes  # noqa: PLC0415 - Windows-only

        self._ctypes = ctypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        self._kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        self._kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        self._kernel32.SetInformationJobObject.restype = ctypes.c_int
        self._kernel32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        self._kernel32.AssignProcessToJobObject.restype = ctypes.c_int
        self._kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self._kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        self._kernel32.CloseHandle.restype = ctypes.c_int
        self._kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    def create_job(self) -> int:
        return int(self._kernel32.CreateJobObjectW(None, None) or 0)

    def enable_kill_on_close(self, handle: int) -> bool:
        ctypes = self._ctypes

        class IoCounters(ctypes.Structure):
            _fields_ = [
                ("read_operations", ctypes.c_uint64),
                ("write_operations", ctypes.c_uint64),
                ("other_operations", ctypes.c_uint64),
                ("read_bytes", ctypes.c_uint64),
                ("write_bytes", ctypes.c_uint64),
                ("other_bytes", ctypes.c_uint64),
            ]

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("per_process_user_time_limit", ctypes.c_int64),
                ("per_job_user_time_limit", ctypes.c_int64),
                ("limit_flags", ctypes.c_uint32),
                ("minimum_working_set_size", ctypes.c_size_t),
                ("maximum_working_set_size", ctypes.c_size_t),
                ("active_process_limit", ctypes.c_uint32),
                ("affinity", ctypes.c_size_t),
                ("priority_class", ctypes.c_uint32),
                ("scheduling_class", ctypes.c_uint32),
            ]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("basic_limit_information", BasicLimitInformation),
                ("io_info", IoCounters),
                ("process_memory_limit", ctypes.c_size_t),
                ("job_memory_limit", ctypes.c_size_t),
                ("peak_process_memory_used", ctypes.c_size_t),
                ("peak_job_memory_used", ctypes.c_size_t),
            ]

        information = ExtendedLimitInformation()
        information.basic_limit_information.limit_flags = self.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        return bool(
            self._kernel32.SetInformationJobObject(
                ctypes.c_void_p(handle),
                self.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(information),
                ctypes.sizeof(information),
            )
        )

    def assign_current_process(self, handle: int) -> bool:
        return bool(
            self._kernel32.AssignProcessToJobObject(
                self._ctypes.c_void_p(handle),
                self._kernel32.GetCurrentProcess(),
            )
        )

    def close_handle(self, handle: int) -> bool:
        return bool(self._kernel32.CloseHandle(self._ctypes.c_void_p(handle)))


def _prepare_windows_owned_process_tree(
    *,
    api: object | None = None,
) -> Callable[[], bool] | None:
    """Assign the application to a complete-tree kill-on-close Job Object."""
    job_api = _WindowsJobApi() if api is None else api
    handle = job_api.create_job()
    if not handle:
        return None
    if not job_api.enable_kill_on_close(handle):
        job_api.close_handle(handle)
        return None
    if not job_api.assign_current_process(handle):
        job_api.close_handle(handle)
        return None
    active_handle: int | None = handle

    def terminate() -> bool:
        nonlocal active_handle
        if active_handle is None:
            return False
        handle_to_close = active_handle
        active_handle = None
        return bool(job_api.close_handle(handle_to_close))

    return terminate


def _prepare_owned_process_tree() -> Callable[[], bool] | None:
    """Prepare kernel/external containment before backend imports spawn children."""
    if os.name == "nt":
        return _prepare_windows_owned_process_tree()
    return _prepare_posix_owned_process_tree()


def _handle_force_exit(
    terminate_owned_tree: Callable[[], bool] | None,
    *,
    environ: dict[str, str] | None = None,
    stream: TextIO | None = None,
    exit_process: Callable[[int], object] | None = None,
) -> bool:
    """Hard-stop a pre-import application or a contained owned process tree."""
    env = os.environ if environ is None else environ
    exit_now = os._exit if exit_process is None else exit_process
    if clear_pending_application_pid_record(environ=env):
        announce_pending_record_exit_ack("force-exit", environ=env, stream=stream)
        exit_now(1)
        return True
    if _force_exit_owned_process_tree(terminate_owned_tree, exit_process=exit_now):
        return True
    print(
        "[desktop-sidecar] complete process-tree termination is unavailable; retaining recovery state",
        file=sys.stderr,
        flush=True,
    )
    return False


def _exit_orphaned(
    request_shutdown: Callable[[], object] | None = None,
    terminate_owned_tree: Callable[[], bool] | None = None,
) -> None:
    """Gracefully unwind the sidecar because the desktop shell is gone."""
    print("[desktop-sidecar] desktop shell exited; shutting down backend", file=sys.stderr, flush=True)
    if request_shutdown is None:
        _handle_force_exit(terminate_owned_tree)
        return
    request_shutdown()

    # A crashed shell cannot provide Tauri's hard-kill fallback. Keep one
    # bounded last resort so a wedged third-party server never becomes an orphan.
    def force_exit() -> None:
        time.sleep(ORPHAN_GRACE_SECONDS)
        _handle_force_exit(terminate_owned_tree)

    threading.Thread(
        target=force_exit,
        name="flinttrade-orphan-shutdown-fallback",
        daemon=True,
    ).start()


def _linux_process_start_token(pid: int) -> str | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    except FileNotFoundError:
        return None
    closing_paren = stat.rfind(")")
    if closing_paren < 0:
        raise OSError(f"could not parse /proc/{pid}/stat")
    fields_after_comm = stat[closing_paren + 2 :].split()
    if len(fields_after_comm) <= 19 or not fields_after_comm[19].isdigit():
        raise OSError(f"could not read process start ticks for pid {pid}")
    return f"linux-start-ticks:{fields_after_comm[19]}"


def _macos_process_start_token(pid: int) -> str | None:
    import ctypes  # noqa: PLC0415 - macOS-only

    class ProcBsdInfo(ctypes.Structure):
        _fields_ = [
            ("pbi_flags", ctypes.c_uint32),
            ("pbi_status", ctypes.c_uint32),
            ("pbi_xstatus", ctypes.c_uint32),
            ("pbi_pid", ctypes.c_uint32),
            ("pbi_ppid", ctypes.c_uint32),
            ("pbi_uid", ctypes.c_uint32),
            ("pbi_gid", ctypes.c_uint32),
            ("pbi_ruid", ctypes.c_uint32),
            ("pbi_rgid", ctypes.c_uint32),
            ("pbi_svuid", ctypes.c_uint32),
            ("pbi_svgid", ctypes.c_uint32),
            ("rfu_1", ctypes.c_uint32),
            ("pbi_comm", ctypes.c_char * 16),
            ("pbi_name", ctypes.c_char * 32),
            ("pbi_nfiles", ctypes.c_uint32),
            ("pbi_pgid", ctypes.c_uint32),
            ("pbi_pjobc", ctypes.c_uint32),
            ("e_tdev", ctypes.c_uint32),
            ("e_tpgid", ctypes.c_uint32),
            ("pbi_nice", ctypes.c_int32),
            ("pbi_start_tvsec", ctypes.c_uint64),
            ("pbi_start_tvusec", ctypes.c_uint64),
        ]

    libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    proc_pidinfo = libproc.proc_pidinfo
    proc_pidinfo.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.c_int,
    ]
    proc_pidinfo.restype = ctypes.c_int
    info = ProcBsdInfo()
    size = ctypes.sizeof(info)
    read = proc_pidinfo(pid, 3, 0, ctypes.byref(info), size)  # PROC_PIDTBSDINFO
    if read == 0:
        error = ctypes.get_errno()
        if error == 3:  # ESRCH
            return None
        raise OSError(error, f"proc_pidinfo failed for pid {pid}")
    if read != size or info.pbi_pid != pid or info.pbi_start_tvsec == 0:
        raise OSError(f"proc_pidinfo returned incomplete identity for pid {pid}")
    return f"macos-start-time:{info.pbi_start_tvsec}:{info.pbi_start_tvusec}"


def _posix_process_start_token(pid: int) -> str | None:
    """Read a kernel-resolution process start token or fail closed."""
    if sys.platform.startswith("linux"):
        return _linux_process_start_token(pid)
    if sys.platform == "darwin":
        return _macos_process_start_token(pid)
    raise OSError(f"high-resolution process identity is unsupported on {sys.platform}")


def _parse_posix_process_identity(text: str, expected_pid: int, start_token: str) -> str | None:
    """Normalise ``ps`` command output with a kernel-resolution start token."""
    fields = text.strip().split(maxsplit=1)
    if len(fields) != 2:
        return None
    try:
        pid = int(fields[0])
    except ValueError:
        return None
    command = fields[1].strip()
    if pid != expected_pid or not command or not start_token:
        return None
    return f"{command}\t{pid}\t{start_token}"


def _posix_process_identity(
    pid: int,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> str | None:
    """Read command, PID, and a kernel-resolution process start identity."""
    run_command = subprocess.run if run is None else run
    before = _posix_process_start_token(pid)
    if before is None:
        return None
    result = run_command(
        ["ps", "-p", str(pid), "-o", "pid=", "-o", "args="],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        if not result.stdout.strip():
            return None
        raise OSError(f"ps exited with status {result.returncode}: {result.stderr.strip()}")
    after = _posix_process_start_token(pid)
    if after is None or after != before:
        return None
    return _parse_posix_process_identity(result.stdout, pid, before)


def _posix_parent_alive(
    parent_pid: int,
    *,
    track_reparent: bool,
    expected_identity: str | None = None,
    identity_lookup: Callable[[int], str | None] | None = None,
) -> bool:
    """Best-effort POSIX liveness check for the shell process.

    Args:
        parent_pid: PID the shell reported for itself.
        track_reparent: True when this process started as a direct child of
            ``parent_pid`` — the shell's death then re-parents us to
            init/launchd, which is race-free against PID reuse. PyInstaller
            grandchild topology instead compares ``expected_identity`` before
            using ``kill(pid, 0)`` only as an indeterminate fallback.

    Returns:
        True only while the exact shell identity remains confirmable.
    """
    if track_reparent:
        return os.getppid() == parent_pid
    if expected_identity is not None:
        lookup = _posix_process_identity if identity_lookup is None else identity_lookup
        try:
            current_identity = lookup(parent_pid)
        except OSError:
            return False
        if current_identity is not None:
            return current_identity == expected_identity
        return False
    try:
        os.kill(parent_pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _watch_parent_posix(
    parent_pid: int,
    request_shutdown: Callable[[], object] | None = None,
    terminate_owned_tree: Callable[[], bool] | None = None,
    *,
    parent_identity: str | None = None,
) -> None:
    """Poll the shell process on macOS/Linux; exit when it disappears."""
    track_reparent = os.getppid() == parent_pid
    if not track_reparent and parent_identity is None:
        try:
            parent_identity = _posix_process_identity(parent_pid)
        except OSError as exc:
            print(
                f"[desktop-sidecar] POSIX parent identity unavailable; PID watchdog disabled: {exc}",
                file=sys.stderr,
                flush=True,
            )
            return
        if parent_identity is None:
            _exit_orphaned(request_shutdown, terminate_owned_tree)
            return
    while True:
        time.sleep(POLL_INTERVAL_SECONDS)
        if not _posix_parent_alive(
            parent_pid,
            track_reparent=track_reparent,
            expected_identity=parent_identity,
        ):
            _exit_orphaned(request_shutdown, terminate_owned_tree)
            return


def _watch_parent_windows(
    parent_pid: int,
    request_shutdown: Callable[[], object] | None = None,
    terminate_owned_tree: Callable[[], bool] | None = None,
) -> None:
    """Block on the shell's process handle on Windows; exit when it dies.

    Holding a ``SYNCHRONIZE`` handle is event-driven (no polling) and immune
    to PID reuse: the handle keeps referring to the original shell process
    even after its PID is recycled.
    """
    import ctypes  # noqa: PLC0415 - Windows-only, keep off the POSIX import path

    synchronize = 0x0010_0000
    error_access_denied = 5
    wait_object_0 = 0x0000_0000
    infinite = 0xFFFF_FFFF

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    handle = kernel32.OpenProcess(synchronize, False, parent_pid)
    if not handle:
        if ctypes.get_last_error() == error_access_denied:
            # Shell alive but unopenable (should not happen same-user):
            # disable the watchdog rather than spuriously killing the backend.
            print("[desktop-sidecar] parent watchdog disabled: access denied", file=sys.stderr)
            return
        # Any other failure means the PID no longer exists — already orphaned.
        _exit_orphaned(request_shutdown, terminate_owned_tree)
        return
    try:
        result = kernel32.WaitForSingleObject(handle, infinite)
    finally:
        kernel32.CloseHandle(handle)
    if result == wait_object_0:
        _exit_orphaned(request_shutdown, terminate_owned_tree)
    else:
        print(f"[desktop-sidecar] parent watchdog wait failed (result {result})", file=sys.stderr)


def _watchdog_body(
    parent_pid: int,
    request_shutdown: Callable[[], object] | None = None,
    terminate_owned_tree: Callable[[], bool] | None = None,
    parent_identity: str | None = None,
) -> None:
    """Run the platform watchdog, failing open on unexpected errors.

    A watchdog bug must never take down a healthy backend — if anything
    unforeseen goes wrong, log it and leave cleanup to the shell's
    reap-on-launch and kill-on-exit layers.
    """
    try:
        if os.name == "nt":
            _watch_parent_windows(parent_pid, request_shutdown, terminate_owned_tree)
        else:
            _watch_parent_posix(
                parent_pid,
                request_shutdown,
                terminate_owned_tree,
                parent_identity=parent_identity,
            )
    except Exception as exc:  # noqa: BLE001 - deliberate fail-open boundary
        print(f"[desktop-sidecar] parent watchdog stopped: {exc}", file=sys.stderr)


def start_parent_watchdog(
    request_shutdown: Callable[[], object] | None = None,
    *,
    terminate_owned_tree: Callable[[], bool] | None = None,
) -> threading.Thread | None:
    """Start the parent-liveness watchdog when launched by the desktop shell.

    Returns:
        The started daemon thread, or ``None`` when ``FLINTTRADE_PARENT_PID``
        is absent/invalid (non-desktop runs).
    """
    parent_pid = _parent_pid_from_env()
    if parent_pid is None:
        return None
    parent_identity = (os.environ.get(PARENT_IDENTITY_ENV) or "").strip() or None
    thread = threading.Thread(
        target=_watchdog_body,
        args=(parent_pid, request_shutdown, terminate_owned_tree, parent_identity),
        name="flinttrade-parent-watchdog",
        daemon=True,
    )
    thread.start()
    return thread


def start_stdin_shutdown_listener(
    request_shutdown: Callable[[], object],
    *,
    stream: TextIO | None = None,
    terminate_owned_tree: Callable[[], bool] | None = None,
) -> threading.Thread:
    """Listen for the shell's graceful command or an EOF from a dead parent."""
    input_stream = sys.stdin if stream is None else stream

    def listen() -> None:
        for line in input_stream:
            command = line.strip()
            if command == FORCE_EXIT_COMMAND:
                _handle_force_exit(terminate_owned_tree)
                return
            if command == SHUTDOWN_COMMAND:
                request_shutdown()
                # Keep the exact inherited pipe alive for Rust's bounded
                # force-exit fallback if graceful server cleanup wedges.
        _exit_orphaned(request_shutdown, terminate_owned_tree)

    thread = threading.Thread(
        target=listen,
        name="flinttrade-stdin-shutdown-listener",
        daemon=True,
    )
    thread.start()
    return thread


if __name__ == "__main__":
    if dispatch_packaged_child_mode():
        raise SystemExit(0)
    publish_packaged_child_contract()

    shutdown = _ShutdownCoordinator()
    terminate_owned_tree = _prepare_owned_process_tree()
    if terminate_owned_tree is None:
        raise SystemExit("complete process-tree containment is unavailable; refusing backend boot")

    # Start the watchdog before the (heavy) backend import so a shell that
    # dies during boot still gets its sidecar cleaned up promptly.
    start_parent_watchdog(shutdown.request, terminate_owned_tree=terminate_owned_tree)
    start_stdin_shutdown_listener(shutdown.request, terminate_owned_tree=terminate_owned_tree)
    start_sigterm_shutdown_relay(shutdown.request)

    # PyInstaller one-file launches through a bootloader process whose PID can
    # disappear while this Python application remains alive. Publish the real
    # PID directly into the exact tokenised record first, then announce it so
    # Rust can independently confirm the process identity.
    require_application_pid_record()
    announce_application_pid()

    from flinttrade_core.desktop import main  # noqa: PLC0415 - after watchdog start, see above

    main(shutdown_signal=shutdown)
