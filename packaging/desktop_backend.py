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

The real serving logic lives in :mod:`flinttrade_core.desktop`.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from collections.abc import Callable
from typing import TextIO

#: Environment variable the Tauri shell sets to its own OS process id.
PARENT_PID_ENV = "FLINTTRADE_PARENT_PID"

#: How often (seconds) the POSIX watchdog polls for parent liveness.
POLL_INTERVAL_SECONDS = 2.0

#: Command the Tauri shell writes to stdin before its bounded hard-kill fallback.
SHUTDOWN_COMMAND = "FLINTTRADE_SHUTDOWN"

#: Last-resort orphan timeout if graceful unwinding is unable to stop Waitress.
ORPHAN_GRACE_SECONDS = 12.0

#: Poll interval for forwarding a lock-free SIGTERM flag outside the handler.
SIGNAL_RELAY_POLL_SECONDS = 0.05


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


def _exit_orphaned(request_shutdown: Callable[[], object] | None = None) -> None:
    """Gracefully unwind the sidecar because the desktop shell is gone."""
    print("[desktop-sidecar] desktop shell exited; shutting down backend", file=sys.stderr, flush=True)
    if request_shutdown is None:
        os._exit(0)
    request_shutdown()

    # A crashed shell cannot provide Tauri's hard-kill fallback. Keep one
    # bounded last resort so a wedged third-party server never becomes an orphan.
    def force_exit() -> None:
        time.sleep(ORPHAN_GRACE_SECONDS)
        os._exit(0)

    threading.Thread(
        target=force_exit,
        name="flinttrade-orphan-shutdown-fallback",
        daemon=True,
    ).start()


def _posix_parent_alive(parent_pid: int, *, track_reparent: bool) -> bool:
    """Best-effort POSIX liveness check for the shell process.

    Args:
        parent_pid: PID the shell reported for itself.
        track_reparent: True when this process started as a direct child of
            ``parent_pid`` — the shell's death then re-parents us to
            init/launchd, which is race-free against PID reuse. Otherwise fall
            back to ``kill(pid, 0)`` probing.

    Returns:
        True while the shell appears alive. Indeterminate errors report
        "alive" — a spurious backend self-kill is worse than a lingering one
        (the reap-on-launch layer still cleans that up).
    """
    if track_reparent:
        return os.getppid() == parent_pid
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
) -> None:
    """Poll the shell process on macOS/Linux; exit when it disappears."""
    track_reparent = os.getppid() == parent_pid
    while True:
        time.sleep(POLL_INTERVAL_SECONDS)
        if not _posix_parent_alive(parent_pid, track_reparent=track_reparent):
            _exit_orphaned(request_shutdown)
            return


def _watch_parent_windows(
    parent_pid: int,
    request_shutdown: Callable[[], object] | None = None,
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
        _exit_orphaned(request_shutdown)
        return
    try:
        result = kernel32.WaitForSingleObject(handle, infinite)
    finally:
        kernel32.CloseHandle(handle)
    if result == wait_object_0:
        _exit_orphaned(request_shutdown)
    else:
        print(f"[desktop-sidecar] parent watchdog wait failed (result {result})", file=sys.stderr)


def _watchdog_body(
    parent_pid: int,
    request_shutdown: Callable[[], object] | None = None,
) -> None:
    """Run the platform watchdog, failing open on unexpected errors.

    A watchdog bug must never take down a healthy backend — if anything
    unforeseen goes wrong, log it and leave cleanup to the shell's
    reap-on-launch and kill-on-exit layers.
    """
    try:
        if os.name == "nt":
            _watch_parent_windows(parent_pid, request_shutdown)
        else:
            _watch_parent_posix(parent_pid, request_shutdown)
    except Exception as exc:  # noqa: BLE001 - deliberate fail-open boundary
        print(f"[desktop-sidecar] parent watchdog stopped: {exc}", file=sys.stderr)


def start_parent_watchdog(
    request_shutdown: Callable[[], object] | None = None,
) -> threading.Thread | None:
    """Start the parent-liveness watchdog when launched by the desktop shell.

    Returns:
        The started daemon thread, or ``None`` when ``FLINTTRADE_PARENT_PID``
        is absent/invalid (non-desktop runs).
    """
    parent_pid = _parent_pid_from_env()
    if parent_pid is None:
        return None
    thread = threading.Thread(
        target=_watchdog_body,
        args=(parent_pid, request_shutdown),
        name="flinttrade-parent-watchdog",
        daemon=True,
    )
    thread.start()
    return thread


def start_stdin_shutdown_listener(
    request_shutdown: Callable[[], object],
    *,
    stream: TextIO | None = None,
) -> threading.Thread:
    """Listen for the shell's graceful command or an EOF from a dead parent."""
    input_stream = sys.stdin if stream is None else stream

    def listen() -> None:
        for line in input_stream:
            if line.strip() == SHUTDOWN_COMMAND:
                request_shutdown()
                return
        request_shutdown()

    thread = threading.Thread(
        target=listen,
        name="flinttrade-stdin-shutdown-listener",
        daemon=True,
    )
    thread.start()
    return thread


if __name__ == "__main__":
    shutdown = _ShutdownCoordinator()

    # Start the watchdog before the (heavy) backend import so a shell that
    # dies during boot still gets its sidecar cleaned up promptly.
    start_parent_watchdog(shutdown.request)
    start_stdin_shutdown_listener(shutdown.request)
    start_sigterm_shutdown_relay(shutdown.request)

    from flinttrade_core.desktop import main  # noqa: PLC0415 - after watchdog start, see above

    main(shutdown_signal=shutdown)
