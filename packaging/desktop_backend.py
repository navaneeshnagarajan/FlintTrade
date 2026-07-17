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

import errno
import inspect
import os
import select
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
SIDECAR_RECORD_VERSION = "v4"

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

#: Durable and stdout proof emitted only by the external POSIX guardian after
#: it has confirmed that the complete owned process tree is gone.
CLEANUP_COMPLETE_SENTINEL = "FLINTTRADE_BACKEND_CLEANUP_COMPLETE"

#: Last-resort orphan timeout if graceful unwinding is unable to stop Waitress.
#: Must cover the backend's own sequential shutdown budget
#: (``flinttrade_core.desktop._DESKTOP_SHUTDOWN_TIMEOUT`` = 60s) plus margin —
#: at the previous 12s the guardian SIGKILLed a mid-unwind trading backend
#: (open-order handling, journal writes) whenever the shell crashed. The Rust
#: shell's ``SIDECAR_WATCHDOG_GRACE_TIMEOUT`` derives from this value; keep
#: them in step.
ORPHAN_GRACE_SECONDS = 75.0

#: Grace between the guardian's escalation SIGTERM and its final SIGKILL of
#: the application leader. A session-wide SIGTERM (Linux logout/shutdown)
#: reaches the guardian and the application simultaneously; killing the
#: application instantly denied it any graceful shutdown at all.
FORCE_KILL_ESCALATION_SECONDS = 5.0

#: Poll interval for forwarding a lock-free SIGTERM flag outside the handler.
SIGNAL_RELAY_POLL_SECONDS = 0.05

#: Brief wait for Rust to publish the pending record after spawning us.
RECORD_PUBLISH_WAIT_SECONDS = 2.0
RECORD_PUBLISH_POLL_SECONDS = 0.01

#: Poll cadence for the external POSIX containment guardian.
POSIX_GUARDIAN_POLL_SECONDS = 0.05
POSIX_GUARDIAN_ACTIVE_RECONCILE_SECONDS = 1.0
POSIX_GUARDIAN_IDLE_RECONCILE_SECONDS = 30.0
POSIX_GUARDIAN_KILL_SECONDS = 5.0
POSIX_GUARDIAN_EMPTY_CONFIRM_SECONDS = 0.1
POSIX_CLEANUP_PROOF_RETRY_SECONDS = 5.0
POSIX_PROCESS_QUERY_TIMEOUT_SECONDS = 1.0
LINUX_PROC_ROOT = Path("/proc")

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


def _cleanup_complete_proof_path(record_path: Path) -> Path:
    """Return the fixed sibling path for a token-bound cleanup proof."""
    return record_path.with_name(f".{record_path.name}.cleanup-complete")


def _cleanup_complete_proof_required(environ: dict[str, str] | None = None) -> bool:
    """Require proof only while the launch's recovery record still exists."""
    env = os.environ if environ is None else environ
    raw_path = (env.get(SIDECAR_RECORD_PATH_ENV) or "").strip()
    if not raw_path:
        return False
    try:
        Path(raw_path).stat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


def _atomically_write_cleanup_complete_proof(record_path: Path, token: str) -> None:
    """Durably replace the proof only after the guarded record comparison."""
    proof_path = _cleanup_complete_proof_path(record_path)
    temporary = proof_path.with_name(f".{proof_path.name}.{token}.{os.getpid()}.tmp")
    payload = f"{CLEANUP_COMPLETE_SENTINEL} token={token}\n".encode("ascii")
    try:
        with temporary.open("xb") as proof_file:
            proof_file.write(payload)
            proof_file.flush()
            os.fsync(proof_file.fileno())
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        os.replace(temporary, proof_path)
        _sync_parent_directory(proof_path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def publish_cleanup_complete_proof(
    application_pid: int,
    *,
    environ: dict[str, str] | None = None,
    stream: TextIO | None = None,
) -> bool:
    """Publish proof only for the exact record owned by this guardian."""
    env = os.environ if environ is None else environ
    output = sys.stdout if stream is None else stream
    raw_path = (env.get(SIDECAR_RECORD_PATH_ENV) or "").strip()
    launch_token = env.get(LAUNCH_TOKEN_ENV) or ""
    boot_id = env.get(BOOT_ID_ENV) or ""
    shell_pid = _parent_pid_from_env(env)
    if (
        not raw_path
        or application_pid <= 0
        or shell_pid is None
        or not _valid_hex_identity(boot_id, minimum=16, maximum=512)
        or not _valid_hex_identity(launch_token, minimum=64, maximum=64)
    ):
        return False

    record_path = Path(raw_path)
    try:
        with _record_transition_guard(record_path):
            lines = record_path.read_text(encoding="utf-8").splitlines()
            if len(lines) != 6 or lines[0] != SIDECAR_RECORD_VERSION:
                return False
            try:
                launcher_pid = int(lines[1])
                recorded_shell_pid = int(lines[3])
            except ValueError:
                return False
            if (
                launcher_pid <= 0
                or lines[2] not in {"pending", str(application_pid)}
                or recorded_shell_pid != shell_pid
                or lines[4] != boot_id
                or lines[5] != launch_token
            ):
                return False
            _atomically_write_cleanup_complete_proof(record_path, launch_token)
    except (OSError, UnicodeError):
        return False

    print(f"{CLEANUP_COMPLETE_SENTINEL} token={launch_token}", file=output, flush=True)
    return True


def _publish_cleanup_complete_proof_with_retry(
    application_pid: int,
    *,
    timeout: float = POSIX_CLEANUP_PROOF_RETRY_SECONDS,
    should_stop: Callable[[], bool] = lambda: False,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Bound proof publication so a permanent filesystem fault cannot wedge the guardian."""
    deadline = clock() + max(0.0, float(timeout))
    while _cleanup_complete_proof_required():
        if publish_cleanup_complete_proof(application_pid):
            return True
        if not _cleanup_complete_proof_required():
            return True
        now = clock()
        if should_stop() or now >= deadline:
            return False
        sleep(min(max(POSIX_GUARDIAN_POLL_SECONDS, 1.0), deadline - now))
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

    __slots__ = (
        "id_version",
        "parent_unique_id",
        "pgid",
        "pid",
        "ppid",
        "sid",
        "start_token",
        "unique_id",
    )

    def __init__(
        self,
        *,
        pid: int,
        ppid: int,
        pgid: int,
        sid: int,
        start_token: str,
        unique_id: int = 0,
        parent_unique_id: int = 0,
        id_version: int = 0,
    ) -> None:
        self.pid = pid
        self.ppid = ppid
        self.pgid = pgid
        self.sid = sid
        self.start_token = start_token
        self.unique_id = unique_id
        self.parent_unique_id = parent_unique_id
        self.id_version = id_version


def _macos_unique_identity_is_stable(
    before: tuple[int, int, int, int],
    after: tuple[int, int, int, int],
) -> bool:
    """Reject a libproc row assembled across two PID generations."""
    return before == after and before[0] > 0


def _posix_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class _MacosProcessInfoUnavailable(OSError):
    """Signal an ambiguous live-PID metadata read that needs revalidation."""


class _MacosPipeLeaseApi:
    """Minimal libproc surface for locating inherited pipe endpoints."""

    PROC_PIDLISTFDS = 1
    PROC_PIDTBSDINFO = 3
    PROC_PIDT_SHORTBSDINFO = 13
    PROC_PIDUNIQIDENTIFIERINFO = 17
    PROC_PIDFDPIPEINFO = 6
    PROX_FDTYPE_PIPE = 6

    def __init__(self) -> None:
        import ctypes  # noqa: PLC0415 - macOS-only

        class ProcFdInfo(ctypes.Structure):
            _fields_ = [
                ("proc_fd", ctypes.c_int32),
                ("proc_fdtype", ctypes.c_uint32),
            ]

        class PipeFdInfo(ctypes.Structure):
            # ``pipe_handle`` starts after proc_fileinfo (24 bytes) and
            # vinfo_stat (136 bytes) in Darwin's struct pipe_fdinfo.
            _fields_ = [
                ("prefix", ctypes.c_ubyte * 160),
                ("pipe_handle", ctypes.c_uint64),
                ("pipe_peerhandle", ctypes.c_uint64),
                ("pipe_status", ctypes.c_int32),
                ("reserved", ctypes.c_int32),
            ]

        class ProcBsdShortInfo(ctypes.Structure):
            _fields_ = [
                ("pid", ctypes.c_uint32),
                ("ppid", ctypes.c_uint32),
                ("pgid", ctypes.c_uint32),
                ("status", ctypes.c_uint32),
                ("comm", ctypes.c_char * 16),
                ("flags", ctypes.c_uint32),
                ("uid", ctypes.c_uint32),
                ("gid", ctypes.c_uint32),
                ("ruid", ctypes.c_uint32),
                ("rgid", ctypes.c_uint32),
                ("svuid", ctypes.c_uint32),
                ("svgid", ctypes.c_uint32),
                ("reserved", ctypes.c_uint32),
            ]

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

        class ProcUniqueIdentifierInfo(ctypes.Structure):
            _fields_ = [
                ("executable_uuid", ctypes.c_ubyte * 16),
                ("unique_id", ctypes.c_uint64),
                ("parent_unique_id", ctypes.c_uint64),
                ("id_version", ctypes.c_int32),
                ("original_parent_id_version", ctypes.c_int32),
                ("reserved_2", ctypes.c_uint64),
                ("reserved_3", ctypes.c_uint64),
            ]

        class AuditToken(ctypes.Structure):
            _fields_ = [("val", ctypes.c_uint32 * 8)]

        if (
            ctypes.sizeof(ProcFdInfo) != 8
            or ctypes.sizeof(PipeFdInfo) != 184
            or ctypes.sizeof(ProcBsdShortInfo) != 64
            or ctypes.sizeof(ProcBsdInfo) != 136
            or ctypes.sizeof(ProcUniqueIdentifierInfo) != 56
            or ctypes.sizeof(AuditToken) != 32
        ):
            raise OSError("unsupported Darwin libproc structure layout")

        self._ctypes = ctypes
        self._proc_fd_info = ProcFdInfo
        self._pipe_fd_info = PipeFdInfo
        self._proc_bsd_short_info = ProcBsdShortInfo
        self._proc_bsd_info = ProcBsdInfo
        self._proc_unique_identifier_info = ProcUniqueIdentifierInfo
        self._audit_token = AuditToken
        self._libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        self._proc_listallpids = self._libproc.proc_listallpids
        self._proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self._proc_listallpids.restype = ctypes.c_int
        self._proc_pidinfo = self._libproc.proc_pidinfo
        self._proc_pidinfo.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        self._proc_pidinfo.restype = ctypes.c_int
        self._proc_pidfdinfo = self._libproc.proc_pidfdinfo
        self._proc_pidfdinfo.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        self._proc_pidfdinfo.restype = ctypes.c_int
        self._proc_signal_with_audittoken = self._libproc.proc_signal_with_audittoken
        self._proc_signal_with_audittoken.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self._proc_signal_with_audittoken.restype = ctypes.c_int

    def list_pids(self) -> list[int]:
        """Return a complete PID snapshot or raise rather than truncate it."""
        ctypes = self._ctypes
        ctypes.set_errno(0)
        required = self._proc_listallpids(None, 0)
        if required <= 0:
            raise OSError(ctypes.get_errno(), "proc_listallpids sizing failed")
        capacity = required + 64
        for _attempt in range(4):
            pids = (ctypes.c_int32 * capacity)()
            ctypes.set_errno(0)
            count = self._proc_listallpids(ctypes.byref(pids), ctypes.sizeof(pids))
            if count < 0:
                raise OSError(ctypes.get_errno(), "proc_listallpids failed")
            if count < capacity:
                return [pid for pid in pids[:count] if pid > 0]
            capacity *= 2
        raise OSError("proc_listallpids changed too quickly for a complete snapshot")

    def list_pipe_fds(self, pid: int) -> list[int]:
        """Return pipe descriptors for one process, tolerating process exit races."""
        ctypes = self._ctypes
        ctypes.set_errno(0)
        required = self._proc_pidinfo(pid, self.PROC_PIDLISTFDS, 0, None, 0)
        if required <= 0:
            error = ctypes.get_errno()
            if error in {0, errno.ESRCH, errno.EPERM, errno.EACCES}:
                return []
            raise OSError(error, f"proc_pidinfo sizing failed for pid {pid}")
        entry_size = ctypes.sizeof(self._proc_fd_info)
        capacity = (required + entry_size - 1) // entry_size + 64
        for _attempt in range(4):
            descriptors = (self._proc_fd_info * capacity)()
            ctypes.set_errno(0)
            read = self._proc_pidinfo(
                pid,
                self.PROC_PIDLISTFDS,
                0,
                ctypes.byref(descriptors),
                ctypes.sizeof(descriptors),
            )
            if read <= 0:
                error = ctypes.get_errno()
                if error in {0, errno.ESRCH, errno.EPERM, errno.EACCES}:
                    return []
                raise OSError(error, f"proc_pidinfo failed for pid {pid}")
            if read % entry_size:
                raise OSError(f"proc_pidinfo returned an incomplete fd record for pid {pid}")
            count = read // entry_size
            if count < capacity:
                return [
                    descriptor.proc_fd
                    for descriptor in descriptors[:count]
                    if descriptor.proc_fd >= 0 and descriptor.proc_fdtype == self.PROX_FDTYPE_PIPE
                ]
            capacity *= 2
        raise OSError(f"fd table for pid {pid} changed too quickly for a complete snapshot")

    def _read_process_info(self, pid: int, flavour: int, info: object) -> object | None:
        """Read one fixed-size libproc structure or report a vanished process."""
        ctypes = self._ctypes
        size = ctypes.sizeof(info)
        ctypes.set_errno(0)
        read = self._proc_pidinfo(pid, flavour, 0, ctypes.byref(info), size)
        if read <= 0:
            error = ctypes.get_errno()
            if error == errno.ESRCH:
                return None
            if error == 0:
                raise _MacosProcessInfoUnavailable(
                    f"proc_pidinfo returned no metadata without errno for pid {pid}, flavour {flavour}"
                )
            raise OSError(error, f"proc_pidinfo failed for pid {pid}, flavour {flavour}")
        if read != size:
            raise OSError(f"proc_pidinfo returned incomplete process metadata for pid {pid}")
        return info

    def _read_unique_info(self, pid: int) -> object | None:
        return self._read_process_info(pid, self.PROC_PIDUNIQIDENTIFIERINFO, self._proc_unique_identifier_info())

    @staticmethod
    def _unique_fields(info: object) -> tuple[int, int, int, int]:
        return (
            int(info.unique_id),
            int(info.parent_unique_id),
            int(info.id_version),
            int(info.original_parent_id_version),
        )

    @staticmethod
    def _permission_fallback_ancestry(pid: int) -> tuple[int, int]:
        """Read one inaccessible PID's ancestry without broadening the snapshot."""
        command = ["ps", "-p", str(pid), "-o", "pid=,ppid=,pgid="]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=POSIX_PROCESS_QUERY_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise OSError(f"Darwin permission fallback timed out for pid {pid}") from exc
        if result.returncode != 0:
            raise OSError(
                f"Darwin permission fallback exited with status {result.returncode} for pid {pid}: "
                f"{result.stderr.strip()}"
            )
        rows = [line.split() for line in result.stdout.splitlines() if line.strip()]
        if len(rows) != 1 or len(rows[0]) != 3:
            raise OSError(f"Darwin permission fallback returned incomplete metadata for pid {pid}")
        try:
            fallback_pid, ppid, pgid = (int(value) for value in rows[0])
        except ValueError as exc:
            raise OSError(f"Darwin permission fallback returned invalid metadata for pid {pid}") from exc
        if fallback_pid != pid or ppid < 0 or pgid <= 0:
            raise OSError(f"Darwin permission fallback returned inconsistent metadata for pid {pid}")
        return ppid, pgid

    def process_info(self, pid: int) -> _PosixProcess | None:
        """Return one generation-consistent PID/group, ancestry, and start row."""
        unique_before = self._read_unique_info(pid)
        if unique_before is None:
            return None
        before_fields = self._unique_fields(unique_before)
        try:
            bsd_info = self._read_process_info(pid, self.PROC_PIDTBSDINFO, self._proc_bsd_info())
        except OSError as exc:
            if not isinstance(exc, _MacosProcessInfoUnavailable) and exc.errno not in {errno.EPERM, errno.EACCES}:
                raise
            ppid, pgid = self._permission_fallback_ancestry(pid)
            unique_after = self._read_unique_info(pid)
            if unique_after is None:
                return None
            after_fields = self._unique_fields(unique_after)
            if before_fields[2] <= 0 or not _macos_unique_identity_is_stable(before_fields, after_fields):
                raise OSError(f"Darwin process {pid} changed during permission fallback")
            return _PosixProcess(
                pid=pid,
                ppid=ppid,
                pgid=pgid,
                sid=pgid,
                start_token=f"macos-unique-id:{before_fields[0]}:{before_fields[2]}",
                unique_id=before_fields[0],
                parent_unique_id=before_fields[1],
                id_version=before_fields[2],
            )
        if bsd_info is None:
            return None
        unique_after = self._read_unique_info(pid)
        if unique_after is None:
            return None
        after_fields = self._unique_fields(unique_after)
        if (
            bsd_info.pbi_pid != pid
            or bsd_info.pbi_start_tvsec <= 0
            or not _macos_unique_identity_is_stable(before_fields, after_fields)
        ):
            raise OSError(f"proc_pidinfo returned inconsistent process metadata for pid {pid}")
        return _PosixProcess(
            pid=pid,
            ppid=int(bsd_info.pbi_ppid),
            pgid=int(bsd_info.pbi_pgid),
            sid=int(bsd_info.pbi_pgid),
            start_token=f"macos-start-time:{bsd_info.pbi_start_tvsec}:{bsd_info.pbi_start_tvusec}",
            unique_id=before_fields[0],
            parent_unique_id=before_fields[1],
            id_version=before_fields[2],
        )

    def unique_identity(self, pid: int) -> tuple[int, int] | None:
        """Return one process and its original parent's stable Darwin IDs."""
        unique_info = self._read_unique_info(pid)
        if unique_info is None:
            return None
        fields = self._unique_fields(unique_info)
        if fields[0] <= 0:
            raise OSError(f"proc_pidinfo returned inconsistent process metadata for pid {pid}")
        return fields[0], fields[1]

    def pipe_info(self, pid: int, fd: int) -> tuple[int, int] | None:
        """Return one pipe's local and peer kernel handles."""
        ctypes = self._ctypes
        info = self._pipe_fd_info()
        size = ctypes.sizeof(info)
        ctypes.set_errno(0)
        read = self._proc_pidfdinfo(
            pid,
            fd,
            self.PROC_PIDFDPIPEINFO,
            ctypes.byref(info),
            size,
        )
        if read <= 0:
            error = ctypes.get_errno()
            if error in {0, errno.ESRCH, errno.EBADF, errno.EINVAL}:
                return None
            raise OSError(error, f"proc_pidfdinfo failed for pid {pid}, fd {fd}")
        if read != size or not info.pipe_handle or not info.pipe_peerhandle:
            # The descriptor can close or change type between PROC_PIDLISTFDS
            # and this lookup. The caller still requires a matching holder (or
            # EOF), so dropping this stale row cannot create false success.
            return None
        return info.pipe_handle, info.pipe_peerhandle

    def signal_process(self, pid: int, id_version: int, signum: int) -> bool:
        """Signal one exact Darwin PID generation through an audit token."""
        if pid <= 0 or id_version <= 0:
            raise OSError("invalid Darwin process audit identity")
        token = self._audit_token()
        token.val[5] = pid
        token.val[7] = id_version
        result = self._proc_signal_with_audittoken(self._ctypes.byref(token), signum)
        if result == 0:
            return True
        if result == errno.ESRCH:
            return False
        raise OSError(result, f"proc_signal_with_audittoken failed for pid {pid}")


def _macos_pipe_lease_holders(
    lease_read_fd: int,
    *,
    api: object | None = None,
    guardian_pid: int | None = None,
) -> dict[int, tuple[str, int]]:
    """Bind each lease writer to one stable process generation."""
    pipe_api = _MacosPipeLeaseApi() if api is None else api
    owner_pid = os.getpid() if guardian_pid is None else guardian_pid
    reader_identity = pipe_api.pipe_info(owner_pid, lease_read_fd)
    if reader_identity is None:
        raise OSError("guardian pipe identity is unavailable")
    reader_handle, writer_handle = reader_identity
    expected_writer = (writer_handle, reader_handle)
    holders: dict[int, tuple[str, int]] = {}
    for pid in pipe_api.list_pids():
        if pid == owner_pid:
            continue
        for fd in pipe_api.list_pipe_fds(pid):
            bracket_before = pipe_api.unique_identity(pid)
            if bracket_before is None:
                raise OSError(f"lease holder candidate {pid} disappeared before endpoint attribution")
            if pipe_api.pipe_info(pid, fd) != expected_writer:
                continue
            generation_identity = _macos_generation_identity(pid, api=pipe_api)
            if generation_identity is None:
                raise OSError(f"lease holder {pid} disappeared during generation binding")
            if pipe_api.pipe_info(pid, fd) != expected_writer:
                raise OSError(f"lease holder {pid} changed before endpoint revalidation")
            bracket_after = pipe_api.unique_identity(pid)
            if bracket_after is None:
                raise OSError(f"lease holder {pid} disappeared after endpoint revalidation")
            if bracket_before != bracket_after:
                raise OSError(f"lease holder {pid} generation changed around endpoint attribution")
            if generation_identity[1] != bracket_before[0]:
                raise OSError(f"lease holder {pid} sampled generation does not match endpoint bracket")
            holders[pid] = generation_identity
            break
    return holders


def _macos_process_unique_identity(pid: int) -> tuple[int, int] | None:
    """Return stable Darwin process and original-parent identities."""
    return _MacosPipeLeaseApi().unique_identity(pid)


def _macos_generation_identity(
    pid: int,
    *,
    expected_start: str | None = None,
    api: object | None = None,
) -> tuple[str, int] | None:
    """Bind a POSIX start token to one stable Darwin process generation."""
    identity_api = _MacosPipeLeaseApi() if api is None else api
    before = identity_api.unique_identity(pid)
    if before is None:
        return None
    start_token = _posix_process_start_token(pid)
    after = identity_api.unique_identity(pid)
    if after is None:
        return None
    if before != after:
        raise OSError(f"process {pid} generation changed during containment sampling")
    if expected_start is not None and start_token != expected_start:
        raise OSError(f"process {pid} start token changed during containment sampling")
    if start_token is None:
        return None
    return start_token, before[0]


def _pipe_lease_eof(lease_read_fd: int) -> bool:
    """Return true only when every writer for an anonymous pipe has closed."""
    readable, _, _ = select.select([lease_read_fd], [], [], 0)
    if not readable:
        return False
    return os.read(lease_read_fd, 4096) == b""


class _WindowsProcessWaitApi:
    """Native non-destructive Windows process-liveness probe."""

    SYNCHRONIZE = 0x0010_0000
    WAIT_OBJECT_0 = 0x0000_0000
    WAIT_TIMEOUT = 0x0000_0102
    ERROR_INVALID_PARAMETER = 87

    def __init__(self) -> None:
        import ctypes  # noqa: PLC0415 - Windows-only

        self._ctypes = ctypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        self._kernel32.OpenProcess.restype = ctypes.c_void_p
        self._kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        self._kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        self._kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self._kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    def open_process_for_wait(self, pid: int) -> int:
        handle = int(self._kernel32.OpenProcess(self.SYNCHRONIZE, False, pid) or 0)
        if not handle and self._ctypes.get_last_error() != self.ERROR_INVALID_PARAMETER:
            raise OSError(self._ctypes.get_last_error(), f"OpenProcess failed for pid {pid}")
        return handle

    def wait_for_exit(self, handle: int) -> bool:
        result = self._kernel32.WaitForSingleObject(self._ctypes.c_void_p(handle), 0)
        if result == self.WAIT_OBJECT_0:
            return True
        if result == self.WAIT_TIMEOUT:
            return False
        raise OSError(self._ctypes.get_last_error(), "WaitForSingleObject failed")

    def close_handle(self, handle: int) -> None:
        self._kernel32.CloseHandle(self._ctypes.c_void_p(handle))


def _windows_pid_alive(pid: int, *, api: object | None = None) -> bool:
    """Return Windows PID liveness without delivering a signal."""
    process_api = _WindowsProcessWaitApi() if api is None else api
    try:
        handle = process_api.open_process_for_wait(pid)
    except OSError:
        return True
    if not handle:
        return False
    try:
        return not bool(process_api.wait_for_exit(handle))
    except OSError:
        return True
    finally:
        process_api.close_handle(handle)


def _parse_linux_process_stat(pid: int, stat: str) -> _PosixProcess:
    """Parse ancestry and generation from one Linux procfs stat snapshot."""
    opening_paren = stat.find("(")
    closing_paren = stat.rfind(")")
    if opening_paren <= 0 or closing_paren <= opening_paren:
        raise OSError(f"could not parse /proc/{pid}/stat")
    try:
        stat_pid = int(stat[:opening_paren].strip())
    except ValueError as exc:
        raise OSError(f"could not parse /proc/{pid}/stat pid") from exc
    fields_after_comm = stat[closing_paren + 1 :].split()
    if len(fields_after_comm) <= 19:
        raise OSError(f"could not read process generation metadata for pid {pid}")
    try:
        ppid = int(fields_after_comm[1])
        pgid = int(fields_after_comm[2])
        sid = int(fields_after_comm[3])
        start_ticks = int(fields_after_comm[19])
    except ValueError as exc:
        raise OSError(f"could not parse process generation metadata for pid {pid}") from exc
    if stat_pid != pid or pid <= 0 or ppid < 0 or pgid <= 0 or sid <= 0 or start_ticks <= 0:
        raise OSError(f"invalid process generation metadata for pid {pid}")
    return _PosixProcess(
        pid=pid,
        ppid=ppid,
        pgid=pgid,
        sid=sid,
        start_token=f"linux-start-ticks:{start_ticks}",
    )


def _read_linux_process_table() -> dict[int, _PosixProcess]:
    """Read each Linux process generation and its ancestry from one stat file."""
    try:
        process_dirs = list(LINUX_PROC_ROOT.iterdir())
    except OSError as exc:
        raise OSError(f"could not enumerate {LINUX_PROC_ROOT}") from exc

    processes: dict[int, _PosixProcess] = {}
    for process_dir in process_dirs:
        if not process_dir.name.isdigit():
            continue
        pid = int(process_dir.name)
        try:
            stat = (process_dir / "stat").read_text(encoding="ascii")
        except OSError as exc:
            if exc.errno in {errno.ENOENT, errno.ESRCH}:
                continue
            raise OSError(f"could not read /proc/{pid}/stat") from exc
        try:
            processes[pid] = _parse_linux_process_stat(pid, stat)
        except OSError:
            # Kernel threads (kthreadd and friends report pgid/sid 0) and other
            # unparseable rows can never belong to the backend's owned tree; a
            # single such row must not poison the whole containment snapshot.
            # A TRACKED pid absent from the table is retained fail-closed by
            # the refresh, so skipping here never loses an owned process.
            continue
    return processes


def _read_linux_process(pid: int) -> _PosixProcess | None:
    """Read one Linux process generation for targeted ancestry validation."""
    try:
        stat = (LINUX_PROC_ROOT / str(pid) / "stat").read_text(encoding="ascii")
    except OSError as exc:
        if exc.errno in {errno.ENOENT, errno.ESRCH}:
            return None
        raise OSError(f"could not read /proc/{pid}/stat") from exc
    return _parse_linux_process_stat(pid, stat)


def _read_posix_process_table(
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> dict[int, _PosixProcess]:
    """Snapshot PID ancestry and process groups without trusting command text."""
    if sys.platform.startswith("linux") and run is None:
        return _read_linux_process_table()
    if sys.platform == "darwin" and run is None:
        process_api = _MacosPipeLeaseApi()
        processes: dict[int, _PosixProcess] = {}
        for pid in process_api.list_pids():
            process = process_api.process_info(pid)
            if process is not None:
                processes[pid] = process
        return processes

    run_command = subprocess.run if run is None else run
    try:
        result = run_command(
            ["ps", "-axo", "pid=,ppid=,pgid="],
            capture_output=True,
            text=True,
            check=False,
            timeout=POSIX_PROCESS_QUERY_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise OSError("ps process-tree query timed out") from exc
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


_NATIVE_POSIX_PROCESS_TABLE_READER = _read_posix_process_table


def _same_posix_process_generation(snapshot: _PosixProcess, current: _PosixProcess) -> bool:
    """Compare the strongest generation identity available on this platform."""
    if snapshot.pid != current.pid:
        return False
    if snapshot.unique_id or current.unique_id:
        return bool(
            snapshot.unique_id > 0
            and snapshot.id_version > 0
            and snapshot.unique_id == current.unique_id
            and snapshot.id_version == current.id_version
        )
    return bool(snapshot.start_token and snapshot.start_token == current.start_token)


def _native_posix_relationship_validator(
    candidate: _PosixProcess,
    relative: _PosixProcess,
    relationship: str,
    *,
    macos_api: object | None = None,
) -> bool:
    """Revalidate one numeric parent/group edge against exact generations."""
    relative_pidfd: int | None = None
    if sys.platform.startswith("linux"):
        read_process = _read_linux_process
        pidfd_open = getattr(os, "pidfd_open", None)
        # pidfd is an EXTRA mid-validation death guard on top of the
        # before/after generation double-reads below. Some CPython builds
        # (python-build-standalone, as installed by uv) ship without
        # os.pidfd_open even on kernels that support it; raising here poisoned
        # every containment snapshot on those builds, so degrade to the
        # double-read validation instead of failing the whole snapshot.
        if pidfd_open is not None:
            try:
                relative_pidfd = pidfd_open(relative.pid, 0)
            except OSError as exc:
                if exc.errno in {errno.ENOENT, errno.ESRCH}:
                    return False
                raise
    elif sys.platform == "darwin":
        process_api = _MacosPipeLeaseApi() if macos_api is None else macos_api
        read_process = process_api.process_info
    else:
        return False

    try:
        if relative_pidfd is not None and select.select([relative_pidfd], [], [], 0)[0]:
            return False
        relative_before = read_process(relative.pid)
        current_candidate = read_process(candidate.pid)
        relative_after = read_process(relative.pid)
        if relative_pidfd is not None and select.select([relative_pidfd], [], [], 0)[0]:
            return False
        if relative_before is None or current_candidate is None or relative_after is None:
            return False
        if not _same_posix_process_generation(relative, relative_before):
            return False
        if not _same_posix_process_generation(relative, relative_after):
            return False
        if not _same_posix_process_generation(candidate, current_candidate):
            return False

        if relationship == "parent":
            if current_candidate.ppid != relative.pid:
                return False
            if current_candidate.parent_unique_id:
                return bool(
                    relative_before.unique_id
                    and current_candidate.parent_unique_id == relative_before.unique_id == relative_after.unique_id
                )
            return True
        if relationship == "group":
            return bool(
                current_candidate.pgid == relative.pid
                and relative_before.pid == relative_before.pgid
                and relative_after.pid == relative_after.pgid
                and current_candidate.sid == relative_before.sid == relative_after.sid
            )
        raise ValueError(f"unsupported POSIX ownership relationship: {relationship}")
    finally:
        if relative_pidfd is not None:
            os.close(relative_pidfd)


def _discover_posix_owned_processes(
    processes: dict[int, _PosixProcess],
    *,
    tracked: dict[int, str],
    guardian_pid: int | None = None,
    tracked_groups: dict[int, str] | None = None,
    owned_unique_ids: set[int] | None = None,
    relationship_validator: Callable[[_PosixProcess, _PosixProcess, str], bool] | None = None,
) -> dict[int, str]:
    """Expand only exact process and group-leader identities through ancestry."""
    historical_unique_ids = owned_unique_ids if owned_unique_ids is not None else set()
    owned: dict[int, str] = {}
    for pid, start_token in tracked.items():
        process = processes.get(pid)
        if process is not None and (not process.start_token or process.start_token == start_token):
            owned[pid] = start_token
            if process.unique_id:
                historical_unique_ids.add(process.unique_id)
    if guardian_pid is not None:
        guardian = processes.get(guardian_pid)
        for pid, process in processes.items():
            if process.ppid == guardian_pid:
                if process.parent_unique_id and (
                    guardian is None or guardian.unique_id != process.parent_unique_id
                ):
                    continue
                if guardian is not None and relationship_validator is not None:
                    if not relationship_validator(process, guardian, "parent"):
                        continue
                owned.setdefault(pid, process.start_token)
                if process.unique_id:
                    historical_unique_ids.add(process.unique_id)

    owned_groups: set[int] = set()
    for pgid, leader_start_token in (tracked_groups or {}).items():
        leader = processes.get(pgid)
        if (
            leader is not None
            and leader.pid == leader.pgid
            and (not leader.start_token or leader.start_token == leader_start_token)
        ):
            owned_groups.add(pgid)

    changed = True
    while changed:
        changed = False
        current_groups = set(owned_groups)
        current_groups.update(
            process.pgid for pid, process in processes.items() if pid in owned and process.pid == process.pgid
        )
        for pid, process in processes.items():
            if pid in owned:
                continue
            unique_parent_owned = bool(
                process.parent_unique_id and process.parent_unique_id in historical_unique_ids
            )
            parent_owned = False
            group_owned = False
            if not process.unique_id:
                parent = processes.get(process.ppid)
                parent_owned = parent is not None and process.ppid in owned
                if parent_owned and relationship_validator is not None:
                    parent_owned = relationship_validator(process, parent, "parent")

                group_leader = processes.get(process.pgid)
                group_owned = group_leader is not None and process.pgid in current_groups
                if group_owned and relationship_validator is not None:
                    group_owned = relationship_validator(process, group_leader, "group")

            if unique_parent_owned or parent_owned or group_owned:
                owned[pid] = process.start_token
                if process.unique_id:
                    historical_unique_ids.add(process.unique_id)
                changed = True
    return owned


def _refresh_posix_owned_processes(
    tracked: dict[int, str],
    tracked_groups: dict[int, str] | None = None,
    *,
    guardian_pid: int | None = None,
    owned_unique_ids: set[int] | None = None,
) -> tuple[dict[int, _PosixProcess], dict[int, str]]:
    process_table_reader = _read_posix_process_table
    processes = process_table_reader()
    relationship_validator: Callable[[_PosixProcess, _PosixProcess, str], bool] | None = None
    if process_table_reader is _NATIVE_POSIX_PROCESS_TABLE_READER:
        macos_api = _MacosPipeLeaseApi() if sys.platform == "darwin" else None

        def validate_relationship(
            candidate: _PosixProcess,
            relative: _PosixProcess,
            relationship: str,
        ) -> bool:
            return _native_posix_relationship_validator(
                candidate,
                relative,
                relationship,
                macos_api=macos_api,
            )

        relationship_validator = validate_relationship

    def has_exact_owned_unique_identity(process: _PosixProcess) -> bool:
        return bool(
            process.unique_id
            and owned_unique_ids is not None
            and process.unique_id in owned_unique_ids
        )

    def bound_start_token(process: _PosixProcess) -> str | None:
        if process.start_token:
            return process.start_token
        if process.unique_id:
            raise OSError(f"Darwin process {process.pid} is missing its generation-bound start token")
        return _posix_process_start_token(process.pid)

    verified: dict[int, str] = {}
    retained: dict[int, str] = {}
    for pid, expected in tracked.items():
        process = processes.get(pid)
        if process is None:
            if _posix_pid_alive(pid):
                retained[pid] = expected
            continue
        try:
            current = bound_start_token(process)
        except OSError:
            retained[pid] = expected
            continue
        if current == expected or has_exact_owned_unique_identity(process):
            process.start_token = current
            verified[pid] = current

    if tracked_groups is not None:
        for pgid, expected in tuple(tracked_groups.items()):
            leader = processes.get(pgid)
            if leader is None or leader.pid != leader.pgid:
                tracked_groups.pop(pgid, None)
                continue
            try:
                current = bound_start_token(leader)
            except OSError:
                continue
            if current != expected and not has_exact_owned_unique_identity(leader):
                tracked_groups.pop(pgid, None)
                continue
            leader.start_token = current
            tracked_groups[pgid] = current

    discovered = _discover_posix_owned_processes(
        processes,
        tracked=verified,
        guardian_pid=guardian_pid,
        tracked_groups=tracked_groups,
        owned_unique_ids=owned_unique_ids,
        relationship_validator=relationship_validator,
    )
    refreshed = retained
    for pid in discovered:
        expected = verified.get(pid, tracked.get(pid))
        try:
            start_token = bound_start_token(processes[pid])
        except OSError:
            if expected is not None:
                refreshed[pid] = expected
                continue
            raise
        if start_token is None:
            continue
        if expected is not None and expected != start_token and not has_exact_owned_unique_identity(processes[pid]):
            continue
        refreshed[pid] = start_token
        # Persist only groups proved to have been created by an owned group
        # leader. Immediately after fork the application can briefly inherit
        # the launcher's group before it calls setpgid(); remembering that
        # inherited PGID would make unrelated launcher processes look owned.
        if tracked_groups is not None and processes[pid].pid == processes[pid].pgid:
            tracked_groups[processes[pid].pgid] = start_token
    return processes, refreshed


def _required_posix_process_start_token(
    pid: int,
    *,
    exited: Callable[[], bool] | None = None,
) -> str | None:
    """Resolve one newly-spawned process identity before ownership is published."""
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        start_token = _posix_process_start_token(pid)
        if start_token:
            return start_token
        if exited is not None and exited():
            return None
        time.sleep(0.001)
    raise OSError(f"process {pid} disappeared before containment registration")


def _install_posix_spawn_registration(
    registrar: Callable[[int, str], None],
    *,
    inherited_fds: tuple[int, ...] = (),
) -> Callable[[], None]:
    """Register each child and explicitly pass application ownership leases."""
    original_popen = subprocess.Popen
    popen_signature = inspect.signature(original_popen)
    has_named_fd_options = {"close_fds", "pass_fds"}.issubset(popen_signature.parameters)

    class RegisteredPopen(original_popen):  # type: ignore[misc, valid-type]
        def __init__(self, *args: object, **kwargs: object) -> None:
            if inherited_fds:
                if has_named_fd_options:
                    bound = popen_signature.bind(*args, **kwargs)
                    existing_fds = tuple(bound.arguments.get("pass_fds", ()))
                    bound.arguments["pass_fds"] = tuple(dict.fromkeys((*existing_fds, *inherited_fds)))
                    bound.arguments["close_fds"] = True
                    args = bound.args
                    kwargs = bound.kwargs
                else:
                    existing_fds = tuple(kwargs.get("pass_fds", ()))
                    kwargs["pass_fds"] = tuple(dict.fromkeys((*existing_fds, *inherited_fds)))
                    kwargs["close_fds"] = True
            super().__init__(*args, **kwargs)
            try:
                start_token = _required_posix_process_start_token(
                    self.pid,
                    exited=lambda: self.poll() is not None,
                )
                if start_token is not None:
                    registrar(self.pid, start_token)
            except Exception:
                try:
                    self.kill()
                except Exception:  # noqa: BLE001 - preserve the registration failure
                    pass
                raise

    subprocess.Popen = RegisteredPopen  # type: ignore[assignment]

    def restore() -> None:
        if subprocess.Popen is RegisteredPopen:
            subprocess.Popen = original_popen

    return restore


def _reap_guardian_children() -> None:
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid <= 0:
            return


def _consume_posix_guardian_commands(
    control_buffer: bytes,
    payload: bytes,
    tracked: dict[int, str],
    owned_unique_ids: set[int],
) -> tuple[bytes, bool, bool]:
    """Apply every complete control-pipe command in one buffered payload."""
    control_buffer += payload
    force_requested = False
    registered = False
    while b"\n" in control_buffer:
        raw_command, control_buffer = control_buffer.split(b"\n", 1)
        if raw_command == b"force":
            force_requested = True
            continue
        fields = raw_command.decode("ascii", errors="ignore").split("\t")
        if len(fields) not in {3, 4} or fields[0] != "register":
            continue
        try:
            registered_pid = int(fields[1])
        except ValueError:
            continue
        registered_start = fields[2]
        if len(fields) == 4:
            try:
                registered_unique_id = int(fields[3])
            except ValueError:
                continue
            if registered_unique_id <= 0:
                continue
            owned_unique_ids.add(registered_unique_id)
        try:
            current_start = _posix_process_start_token(registered_pid)
        except OSError:
            current_start = None
        if registered_pid > 0 and current_start == registered_start:
            tracked[registered_pid] = registered_start
        registered = True
    return control_buffer, force_requested, registered


def _drain_posix_guardian_control(
    control_fd: int,
    control_buffer: bytes,
    tracked: dict[int, str],
    owned_unique_ids: set[int],
) -> tuple[bytes, bool, bool, bool, OSError | None]:
    """Drain all currently queued commands, distinguishing EAGAIN from EOF."""
    force_requested = False
    eof = False
    registered = False
    read_error: OSError | None = None
    while True:
        try:
            payload = os.read(control_fd, 4096)
        except BlockingIOError:
            break
        except InterruptedError:
            continue
        except OSError as exc:
            read_error = exc
            break
        if payload == b"":
            eof = True
            break
        control_buffer, payload_force, payload_registered = _consume_posix_guardian_commands(
            control_buffer,
            payload,
            tracked,
            owned_unique_ids,
        )
        force_requested = force_requested or payload_force
        registered = registered or payload_registered
    return control_buffer, force_requested, eof, registered, read_error


def _signal_owned_posix_process(
    process: _PosixProcess,
    expected_start: str,
) -> bool:
    """Signal only through authority that cannot retarget a reused PID."""
    if sys.platform == "darwin":
        if process.unique_id <= 0 or process.id_version <= 0 or process.start_token != expected_start:
            return False
        try:
            return _MacosPipeLeaseApi().signal_process(process.pid, process.id_version, signal.SIGKILL)
        except OSError:
            return False

    if sys.platform.startswith("linux"):
        pidfd_open = getattr(os, "pidfd_open", None)
        pidfd_send_signal = getattr(signal, "pidfd_send_signal", None)
        if pidfd_open is None or pidfd_send_signal is None:
            # python-build-standalone CPython (as installed by uv) ships
            # without the pidfd surface even on kernels that support it.
            # Fall back to a start-token-verified kill: the generation token
            # is re-read immediately before the signal, shrinking the PID
            # reuse window to the syscall gap. Refusing outright left the
            # guardian unable to terminate anything on such builds.
            try:
                current_start = _posix_process_start_token(process.pid)
            except OSError:
                return False
            if current_start != expected_start:
                return False
            try:
                os.kill(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return True
            except OSError:
                return False
            return True
        try:
            pidfd = pidfd_open(process.pid, 0)
        except OSError:
            return False
        try:
            try:
                current_start = _posix_process_start_token(process.pid)
            except OSError:
                return False
            if current_start != expected_start:
                return False
            try:
                pidfd_send_signal(pidfd, signal.SIGKILL, None, 0)
            except ProcessLookupError:
                return True
            except OSError:
                return False
            return True
        finally:
            os.close(pidfd)

    return False


def _terminate_posix_owned_processes(
    tracked: dict[int, str],
    tracked_groups: dict[int, str],
    *,
    lease_read_fd: int | None = None,
    owned_unique_ids: set[int] | None = None,
) -> bool:
    """Kill and confirm every still-identical process owned by the backend."""
    macos_lease_required = sys.platform == "darwin" and lease_read_fd is not None
    guardian_pid = os.getpid()
    deadline = time.monotonic() + POSIX_GUARDIAN_KILL_SECONDS
    empty_since: float | None = None
    while time.monotonic() < deadline:
        try:
            processes, tracked = _refresh_posix_owned_processes(
                tracked,
                tracked_groups,
                guardian_pid=guardian_pid,
                owned_unique_ids=owned_unique_ids,
            )
        except OSError:
            empty_since = None
            time.sleep(POSIX_GUARDIAN_POLL_SECONDS)
            continue

        lease_eof = True
        if macos_lease_required:
            try:
                lease_eof = _pipe_lease_eof(lease_read_fd)
                if not lease_eof:
                    lease_holders = _macos_pipe_lease_holders(lease_read_fd)
                    for pid, (start_token, unique_id) in lease_holders.items():
                        tracked[pid] = start_token
                        if owned_unique_ids is not None:
                            owned_unique_ids.add(unique_id)
            except OSError:
                empty_since = None
                time.sleep(POSIX_GUARDIAN_POLL_SECONDS)
                continue

        if not tracked and (not macos_lease_required or (not tracked_groups and lease_eof)):
            _reap_guardian_children()
            now = time.monotonic()
            if empty_since is not None and now - empty_since >= POSIX_GUARDIAN_EMPTY_CONFIRM_SECONDS:
                return True
            if empty_since is None:
                empty_since = now
            time.sleep(POSIX_GUARDIAN_POLL_SECONDS)
            continue
        empty_since = None

        for pid, expected_start in tuple(tracked.items()):
            process = processes.get(pid)
            if process is None:
                continue
            _signal_owned_posix_process(process, expected_start)
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


def _run_posix_containment_guardian(
    application_pid: int,
    control_fd: int,
    ready_fd: int,
    lease_read_fd: int | None = None,
) -> None:
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

    try:
        application_start = _required_posix_process_start_token(application_pid)
        if application_start is None:
            raise OSError(f"backend leader {application_pid} exited before containment started")
    except OSError as exc:
        print(f"[desktop-sidecar] backend leader identity unavailable: {exc}", file=sys.stderr, flush=True)
        os.close(control_fd)
        os.close(ready_fd)
        if lease_read_fd is not None:
            os.close(lease_read_fd)
        os._exit(1)
    tracked: dict[int, str] = {application_pid: application_start}
    tracked_groups: dict[int, str] = {}
    owned_unique_ids: set[int] = set()
    if sys.platform == "darwin":
        try:
            application_generation = _macos_generation_identity(
                application_pid,
                expected_start=application_start,
            )
        except OSError as exc:
            print(f"[desktop-sidecar] backend unique identity unavailable: {exc}", file=sys.stderr, flush=True)
            os.close(control_fd)
            if lease_read_fd is not None:
                os.close(lease_read_fd)
            os._exit(1)
        if application_generation is None:
            print("[desktop-sidecar] backend unique identity disappeared", file=sys.stderr, flush=True)
            os.close(control_fd)
            if lease_read_fd is not None:
                os.close(lease_read_fd)
            os._exit(1)
        owned_unique_ids.add(application_generation[1])
    control_buffer = b""
    try:
        if not force_requested and os.write(ready_fd, b"ready\n") != len(b"ready\n"):
            raise OSError("short guardian readiness write")
    except OSError as exc:
        print(f"[desktop-sidecar] containment readiness failed: {exc}", file=sys.stderr, flush=True)
        force_requested = True
    finally:
        os.close(ready_fd)
    status: int | None = None
    next_reconcile = 0.0
    while status is None and not force_requested:
        now = time.monotonic()
        if now >= next_reconcile:
            try:
                _processes, tracked = _refresh_posix_owned_processes(
                    tracked,
                    tracked_groups,
                    guardian_pid=os.getpid(),
                    owned_unique_ids=owned_unique_ids,
                )
            except OSError as exc:
                print(f"[desktop-sidecar] containment snapshot failed: {exc}", file=sys.stderr, flush=True)
            reconcile_seconds = (
                POSIX_GUARDIAN_ACTIVE_RECONCILE_SECONDS if len(tracked) > 1 else POSIX_GUARDIAN_IDLE_RECONCILE_SECONDS
            )
            next_reconcile = now + reconcile_seconds
        control_buffer, pipe_force, _control_eof, registered, control_error = _drain_posix_guardian_control(
            control_fd,
            control_buffer,
            tracked,
            owned_unique_ids,
        )
        force_requested = force_requested or pipe_force
        if control_error is not None:
            print(f"[desktop-sidecar] containment control read failed: {control_error}", file=sys.stderr, flush=True)
        if registered:
            next_reconcile = 0.0
        if force_requested:
            break
        try:
            waited_pid, waited_status = os.waitpid(application_pid, os.WNOHANG)
        except ChildProcessError:
            waited_pid, waited_status = application_pid, 1 << 8
        if waited_pid == application_pid:
            status = waited_status
            break
        time.sleep(POSIX_GUARDIAN_POLL_SECONDS)

    if force_requested and status is None:
        # SIGTERM first: a session-wide SIGTERM (logout, system shutdown)
        # lands on the guardian and the application at the same instant, and
        # an immediate SIGKILL here denied the application its graceful
        # shutdown entirely. The bounded escalation still guarantees death.
        try:
            os.kill(application_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError as exc:
            print(
                f"[desktop-sidecar] backend leader SIGTERM failed: {exc}",
                file=sys.stderr,
                flush=True,
            )
        escalation_deadline = time.monotonic() + FORCE_KILL_ESCALATION_SECONDS
        while time.monotonic() < escalation_deadline:
            try:
                waited_pid, waited_status = os.waitpid(application_pid, os.WNOHANG)
            except ChildProcessError:
                waited_pid, waited_status = application_pid, 1 << 8
            if waited_pid == application_pid:
                status = waited_status
                break
            time.sleep(POSIX_GUARDIAN_POLL_SECONDS)
    if force_requested and status is None:
        try:
            # The application remains this guardian's unreaped direct child, so
            # its PID cannot be reused before the following waitpid.
            os.kill(application_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError as exc:
            print(f"[desktop-sidecar] backend leader cleanup failed: {exc}", file=sys.stderr, flush=True)
        try:
            _pid, status = os.waitpid(application_pid, 0)
        except ChildProcessError:
            status = 1 << 8

    # The application may have registered a child after this loop's final read
    # but before waitpid observed its exit. Drain every byte already queued
    # before the ownership snapshots can declare the tree empty.
    control_buffer, pipe_force, _control_eof, _registered, control_error = _drain_posix_guardian_control(
        control_fd,
        control_buffer,
        tracked,
        owned_unique_ids,
    )
    force_requested = force_requested or pipe_force
    if control_error is not None:
        print(f"[desktop-sidecar] containment control read failed: {control_error}", file=sys.stderr, flush=True)

    exit_code = _wait_status_exit_code(status if status is not None else 1 << 8)
    while True:
        while not _terminate_posix_owned_processes(
            tracked,
            tracked_groups,
            lease_read_fd=lease_read_fd,
            owned_unique_ids=owned_unique_ids,
        ):
            print(
                "[desktop-sidecar] process-tree cleanup remains unresolved; guardian is retaining recovery state "
                f"(tracked={sorted(tracked)} groups={sorted(tracked_groups)})",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(POSIX_GUARDIAN_POLL_SECONDS)

        control_buffer, pipe_force, control_eof, registered, control_error = _drain_posix_guardian_control(
            control_fd,
            control_buffer,
            tracked,
            owned_unique_ids,
        )
        force_requested = force_requested or pipe_force
        if control_error is not None or not control_eof or control_buffer:
            detail = str(control_error) if control_error is not None else "control pipe has not reached clean EOF"
            print(
                f"[desktop-sidecar] containment control drain unresolved ({detail}); retaining recovery state",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(max(POSIX_GUARDIAN_POLL_SECONDS, 1.0))
            continue
        if registered:
            continue
        if _terminate_posix_owned_processes(
            tracked,
            tracked_groups,
            lease_read_fd=lease_read_fd,
            owned_unique_ids=owned_unique_ids,
        ):
            break

    if not _publish_cleanup_complete_proof_with_retry(
        application_pid,
        should_stop=lambda: force_requested,
    ):
        print(
            "[desktop-sidecar] cleanup proof could not be persisted; "
            "guardian is exiting with explicit recovery state retained",
            file=sys.stderr,
            flush=True,
        )
    os.close(control_fd)
    if lease_read_fd is not None:
        os.close(lease_read_fd)
    os._exit(exit_code)


def _prepare_posix_owned_process_tree(
    publish_application_identity: Callable[[], None] | None = None,
) -> Callable[[], bool] | None:
    """Fork an external guardian, then isolate the backend leader in a group."""
    if not _enable_linux_child_subreaper():
        return None
    read_fd, write_fd = os.pipe()
    ready_read_fd, ready_write_fd = os.pipe()
    lease_read_fd: int | None = None
    lease_write_fd: int | None = None
    if sys.platform == "darwin":
        lease_read_fd, lease_write_fd = os.pipe()
    try:
        application_pid = os.fork()
    except OSError:
        os.close(read_fd)
        os.close(write_fd)
        os.close(ready_read_fd)
        os.close(ready_write_fd)
        if lease_read_fd is not None:
            os.close(lease_read_fd)
        if lease_write_fd is not None:
            os.close(lease_write_fd)
        return None
    if application_pid > 0:
        os.close(write_fd)
        os.close(ready_read_fd)
        if lease_write_fd is not None:
            os.close(lease_write_fd)
        _run_posix_containment_guardian(application_pid, read_fd, ready_write_fd, lease_read_fd)
        raise AssertionError("POSIX containment guardian returned")

    os.close(read_fd)
    os.close(ready_write_fd)
    if lease_read_fd is not None:
        os.close(lease_read_fd)
    os.set_inheritable(write_fd, False)
    os.set_inheritable(ready_read_fd, False)
    if lease_write_fd is not None:
        os.set_inheritable(lease_write_fd, False)
    child_pid = os.getpid()
    ready, _, _ = select.select([ready_read_fd], [], [], 2.0)
    if not ready:
        os.close(ready_read_fd)
        os.close(write_fd)
        if lease_write_fd is not None:
            os.close(lease_write_fd)
        return None
    guardian_ready = os.read(ready_read_fd, 64)
    os.close(ready_read_fd)
    if guardian_ready != b"ready\n":
        os.close(write_fd)
        if lease_write_fd is not None:
            os.close(lease_write_fd)
        return None
    if publish_application_identity is not None:
        publish_application_identity()
    try:
        os.setpgid(0, 0)
    except OSError:
        if os.getpgrp() != child_pid:
            os.close(write_fd)
            if lease_write_fd is not None:
                os.close(lease_write_fd)
            return None
    if os.getpgrp() != child_pid:
        os.close(write_fd)
        if lease_write_fd is not None:
            os.close(lease_write_fd)
        return None

    def register_spawn(pid: int, start_token: str) -> None:
        unique_suffix = ""
        if sys.platform == "darwin":
            generation_identity = _macos_generation_identity(pid, expected_start=start_token)
            if generation_identity is None:
                raise OSError(f"process {pid} disappeared before unique containment registration")
            unique_suffix = f"\t{generation_identity[1]}"
        payload = f"register\t{pid}\t{start_token}{unique_suffix}\n".encode("ascii")
        if os.write(write_fd, payload) != len(payload):
            raise OSError(f"short containment registration write for pid {pid}")

    # Every cooperative child receives the same anonymous write endpoint. On
    # macOS, libproc lets the guardian find descendants that escape ancestry
    # before registration. A deliberately hostile descendant can close its own
    # lease; macOS exposes no stronger unprivileged containment primitive.
    inherited_fds = () if lease_write_fd is None else (lease_write_fd,)
    _install_posix_spawn_registration(register_spawn, inherited_fds=inherited_fds)

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


def _prepare_owned_process_tree(
    publish_application_identity: Callable[[], None] | None = None,
) -> Callable[[], bool] | None:
    """Prepare kernel/external containment before backend imports spawn children."""
    if os.name == "nt":
        terminate = _prepare_windows_owned_process_tree()
        if terminate is not None and publish_application_identity is not None:
            publish_application_identity()
        return terminate
    return _prepare_posix_owned_process_tree(publish_application_identity)


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


def _detach_broken_shell_stdio() -> None:
    """Point this process's stdout/stderr at ``/dev/null`` once the shell dies.

    The dead shell owned the read end of our stdio pipes, so ANY later
    diagnostic print in the shutdown path raises ``BrokenPipeError``. That
    exception previously escaped from the announcement print at the top of
    ``_exit_orphaned`` and killed the orphan watchdog thread before the
    graceful shutdown request or the force-exit timer were armed — the whole
    backend tree then survived its shell indefinitely, serving on loopback
    with nobody attached (the recurring zombie-backend reports).
    """
    try:
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
    except OSError:
        return
    for fd in (1, 2):
        try:
            os.dup2(devnull_fd, fd)
        except OSError:
            pass
    try:
        os.close(devnull_fd)
    except OSError:
        pass


def _exit_orphaned(
    request_shutdown: Callable[[], object] | None = None,
    terminate_owned_tree: Callable[[], bool] | None = None,
) -> None:
    """Gracefully unwind the sidecar because the desktop shell is gone."""
    _detach_broken_shell_stdio()
    try:
        print(
            "[desktop-sidecar] desktop shell exited; shutting down backend",
            file=sys.stderr,
            flush=True,
        )
    except OSError:
        # A failed diagnostic must never abort the shutdown itself.
        pass
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
        stat = (LINUX_PROC_ROOT / str(pid) / "stat").read_text(encoding="ascii")
    except FileNotFoundError:
        return None
    return _parse_linux_process_stat(pid, stat).start_token


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


def _linux_process_command(pid: int) -> str | None:
    """Read the native Linux command contract used by the Rust shell."""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as command_file:
            command_bytes = command_file.read()
    except FileNotFoundError:
        return None
    command = command_bytes.replace(b"\0", b" ").decode(errors="replace").strip()
    if not command:
        # /proc/<pid>/cmdline reads empty the moment a dying process's address
        # space is torn down — observably BEFORE its state flips to zombie —
        # and permanently for zombies and kernel threads. None of those can be
        # a live desktop shell, so report the identity as unavailable (None,
        # matching the macOS ESRCH contract): the watchdog then treats the
        # parent as gone and orphan-exits instead of disabling itself against
        # a crashed-and-unreaped shell. Raising here left the backend running
        # unwatched forever.
        return None
    return command


def _macos_process_command(pid: int) -> str | None:
    """Read the native macOS executable path used by the Rust shell."""
    import ctypes  # noqa: PLC0415 - macOS-only

    libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    proc_pidpath = libproc.proc_pidpath
    proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    proc_pidpath.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(4096)
    read = proc_pidpath(pid, ctypes.byref(buffer), len(buffer))
    if read <= 0:
        error = ctypes.get_errno()
        if error == 3:  # ESRCH
            return None
        raise OSError(error, f"proc_pidpath failed for pid {pid}")
    command = bytes(buffer.raw[:read]).decode(errors="replace").strip()
    if not command:
        raise OSError(f"process {pid} has no readable executable path")
    return command


def _posix_process_command(pid: int) -> str | None:
    """Read the same platform-native process command used by the Rust shell."""
    if sys.platform.startswith("linux"):
        return _linux_process_command(pid)
    if sys.platform == "darwin":
        return _macos_process_command(pid)
    raise OSError(f"native POSIX process command lookup is unsupported on {sys.platform}")


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
    """Read native command, PID, and a kernel-resolution process identity."""
    _ = run  # Retained for compatibility with callers from older frozen builds.
    before = _posix_process_start_token(pid)
    if before is None:
        return None
    command = _posix_process_command(pid)
    if command is None:
        return None
    after = _posix_process_start_token(pid)
    if after is None or after != before:
        return None
    return f"{command}\t{pid}\t{before}"


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

    def publish_application_identity() -> None:
        require_application_pid_record()
        announce_application_pid()

    terminate_owned_tree = _prepare_owned_process_tree(publish_application_identity)
    if terminate_owned_tree is None:
        raise SystemExit("complete process-tree containment is unavailable; refusing backend boot")

    # Start the watchdog before the (heavy) backend import so a shell that
    # dies during boot still gets its sidecar cleaned up promptly.
    start_parent_watchdog(shutdown.request, terminate_owned_tree=terminate_owned_tree)
    start_stdin_shutdown_listener(shutdown.request, terminate_owned_tree=terminate_owned_tree)
    start_sigterm_shutdown_relay(shutdown.request)

    from flinttrade_core.desktop import main  # noqa: PLC0415 - after watchdog start, see above

    main(shutdown_signal=shutdown)
