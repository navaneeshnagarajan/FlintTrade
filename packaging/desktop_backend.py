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
import sys
import threading
import time

#: Environment variable the Tauri shell sets to its own OS process id.
PARENT_PID_ENV = "FLINTTRADE_PARENT_PID"

#: How often (seconds) the POSIX watchdog polls for parent liveness.
POLL_INTERVAL_SECONDS = 2.0


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


def _exit_orphaned() -> None:
    """Terminate the sidecar because the desktop shell is gone.

    A daemon thread cannot unwind the blocking Waitress main thread, so a
    direct ``os._exit`` is the clean option here — it is no more abrupt than
    the shell's own kill-on-exit path on a graceful quit.
    """
    print("[desktop-sidecar] desktop shell exited; shutting down backend", file=sys.stderr, flush=True)
    os._exit(0)


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


def _watch_parent_posix(parent_pid: int) -> None:
    """Poll the shell process on macOS/Linux; exit when it disappears."""
    track_reparent = os.getppid() == parent_pid
    while True:
        time.sleep(POLL_INTERVAL_SECONDS)
        if not _posix_parent_alive(parent_pid, track_reparent=track_reparent):
            _exit_orphaned()


def _watch_parent_windows(parent_pid: int) -> None:
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
        _exit_orphaned()
        return
    try:
        result = kernel32.WaitForSingleObject(handle, infinite)
    finally:
        kernel32.CloseHandle(handle)
    if result == wait_object_0:
        _exit_orphaned()
    else:
        print(f"[desktop-sidecar] parent watchdog wait failed (result {result})", file=sys.stderr)


def _watchdog_body(parent_pid: int) -> None:
    """Run the platform watchdog, failing open on unexpected errors.

    A watchdog bug must never take down a healthy backend — if anything
    unforeseen goes wrong, log it and leave cleanup to the shell's
    reap-on-launch and kill-on-exit layers.
    """
    try:
        if os.name == "nt":
            _watch_parent_windows(parent_pid)
        else:
            _watch_parent_posix(parent_pid)
    except Exception as exc:  # noqa: BLE001 - deliberate fail-open boundary
        print(f"[desktop-sidecar] parent watchdog stopped: {exc}", file=sys.stderr)


def start_parent_watchdog() -> threading.Thread | None:
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
        args=(parent_pid,),
        name="flinttrade-parent-watchdog",
        daemon=True,
    )
    thread.start()
    return thread


if __name__ == "__main__":
    # Start the watchdog before the (heavy) backend import so a shell that
    # dies during boot still gets its sidecar cleaned up promptly.
    start_parent_watchdog()

    from flinttrade_core.desktop import main  # noqa: PLC0415 - after watchdog start, see above

    main()
