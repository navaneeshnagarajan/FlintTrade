"""Strategy Runner: execute user-uploaded .py strategies as sandboxed subprocesses.

Each uploaded strategy is saved to ``strategies_dir/<name>.py`` and can be
launched as an isolated subprocess.  Communication between the host process and
the strategy subprocess is done via stdin/stdout JSON-RPC pipes (future feature;
currently the strategy only reads environment-injected config).

Safety:
- AST-based static analysis rejects strategies that import dangerous modules or
  call unsafe builtins (``os.system``, ``subprocess``, ``__import__``, ``eval``,
  ``exec``, ``open`` in write mode).
- Each subprocess is monitored by psutil for memory usage and can be terminated
  if it exceeds a configurable threshold.

Usage::

    runner = UserStrategyRunner(strategies_dir=Path("/path/to/strategies"))
    violations = runner.validate(code)
    if not violations:
        strategy_id = runner.upload("my_strategy", code)
        runner.start(strategy_id)
        status = runner.get_status(strategy_id)
        runner.stop(strategy_id)
"""

from __future__ import annotations

import ast
import ctypes as _ctypes
import logging
import math
import os
import platform
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.engine.strategy_runner")

FROZEN_STRATEGY_CHILD_ARG = "--flinttrade-uploaded-strategy-child"
PACKAGED_CHILD_EXECUTABLE_ENV = "FLINTTRADE_PACKAGED_CHILD_EXECUTABLE"
PACKAGED_CHILD_ARG_ENV = "FLINTTRADE_PACKAGED_CHILD_ARG"
STRATEGY_MEMORY_LIMIT_ENV = "FLINTTRADE_STRATEGY_MEMORY_LIMIT_BYTES"
STRATEGY_PROCESS_LIMIT_ENV = "FLINTTRADE_STRATEGY_PROCESS_LIMIT"
_frozen_dispatch_checked = False


class PackagedChildConfigurationError(Exception):
    """Raised when the packaged parent did not publish a usable child contract."""


class StrategyNotRunningError(RuntimeError):
    """Raised when no owned subprocess exists for a requested stop."""


class _ProcessTreeIdentityError(RuntimeError):
    """Raised when a process-tree signal cannot prove its original owner."""


class _WindowsJobCreationRollbackError(RuntimeError):
    """Expose a failed Job owner so the parent can retain and retry cleanup."""

    def __init__(
        self,
        process_tree: Any,
        setup_error: Exception,
        rollback_error: Exception,
    ) -> None:
        super().__init__(f"Windows strategy Job rollback remains owned: {rollback_error}")
        self.process_tree = process_tree
        self.setup_error = setup_error
        self.rollback_error = rollback_error


_WINDOWS_CREATE_SUSPENDED = 0x00000004
_WINDOWS_CREATE_NEW_PROCESS_GROUP = 0x00000200


class _WindowsJobBasicAccountingInformation(_ctypes.Structure):
    """Portable layout of JOBOBJECT_BASIC_ACCOUNTING_INFORMATION."""

    _fields_ = [
        ("TotalUserTime", _ctypes.c_longlong),
        ("TotalKernelTime", _ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", _ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", _ctypes.c_longlong),
        ("TotalPageFaultCount", _ctypes.c_uint32),
        ("TotalProcesses", _ctypes.c_uint32),
        ("ActiveProcesses", _ctypes.c_uint32),
        ("TotalTerminatedProcesses", _ctypes.c_uint32),
    ]


class _WindowsIoCounters(_ctypes.Structure):
    """Portable layout of IO_COUNTERS."""

    _fields_ = [
        ("ReadOperationCount", _ctypes.c_ulonglong),
        ("WriteOperationCount", _ctypes.c_ulonglong),
        ("OtherOperationCount", _ctypes.c_ulonglong),
        ("ReadTransferCount", _ctypes.c_ulonglong),
        ("WriteTransferCount", _ctypes.c_ulonglong),
        ("OtherTransferCount", _ctypes.c_ulonglong),
    ]


class _WindowsJobBasicLimitInformation(_ctypes.Structure):
    """Portable layout of JOBOBJECT_BASIC_LIMIT_INFORMATION."""

    _fields_ = [
        ("PerProcessUserTimeLimit", _ctypes.c_longlong),
        ("PerJobUserTimeLimit", _ctypes.c_longlong),
        ("LimitFlags", _ctypes.c_uint32),
        ("MinimumWorkingSetSize", _ctypes.c_size_t),
        ("MaximumWorkingSetSize", _ctypes.c_size_t),
        ("ActiveProcessLimit", _ctypes.c_uint32),
        ("Affinity", _ctypes.c_size_t),
        ("PriorityClass", _ctypes.c_uint32),
        ("SchedulingClass", _ctypes.c_uint32),
    ]


class _WindowsJobExtendedLimitInformation(_ctypes.Structure):
    """Portable layout used to enforce Job memory and process ceilings."""

    _fields_ = [
        ("BasicLimitInformation", _WindowsJobBasicLimitInformation),
        ("IoInfo", _WindowsIoCounters),
        ("ProcessMemoryLimit", _ctypes.c_size_t),
        ("JobMemoryLimit", _ctypes.c_size_t),
        ("PeakProcessMemoryUsed", _ctypes.c_size_t),
        ("PeakJobMemoryUsed", _ctypes.c_size_t),
    ]


def _read_process_identity(pid: int) -> float:
    """Return a stable process creation token or fail closed."""
    if not globals().get("_PSUTIL_AVAILABLE", False):
        raise _ProcessTreeIdentityError("POSIX process identity proof requires psutil")
    try:
        identity = float(psutil.Process(pid).create_time())
    except Exception as exc:  # noqa: BLE001 - identity uncertainty must retain ownership
        raise _ProcessTreeIdentityError(f"Could not establish process identity for pid={pid}") from exc
    if not math.isfinite(identity) or identity <= 0:
        raise _ProcessTreeIdentityError(f"Invalid process identity for pid={pid}")
    return identity


class _PosixProcessGroup:
    """Own and verify a dedicated POSIX process group."""

    def __init__(self, process: subprocess.Popen[Any]) -> None:
        self._process = process
        self._pgid = process.pid
        self._leader_identity = _read_process_identity(process.pid)

    def is_alive(self) -> bool:
        if self._process.poll() is None:
            self._assert_live_leader_identity()
            try:
                os.killpg(self._pgid, 0)
            except ProcessLookupError as exc:
                raise _ProcessTreeIdentityError(
                    f"Process group {self._pgid} disappeared while its verified leader was live"
                ) from exc
            except PermissionError:
                return True
            return True
        try:
            os.killpg(self._pgid, 0)
        except ProcessLookupError:
            return False
        except PermissionError as exc:
            raise _ProcessTreeIdentityError(
                f"Process group {self._pgid} remains after its leader exited; identity is unprovable"
            ) from exc
        raise _ProcessTreeIdentityError(
            f"Process group {self._pgid} remains after its leader exited; identity is unprovable"
        )

    def terminate(self) -> None:
        self._signal(signal.SIGTERM)

    def kill(self) -> None:
        self._signal(signal.SIGKILL)

    def wait_gone(self, timeout: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            self._process.poll()
            if not self.is_alive():
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.02, remaining))

    def close(self) -> None:
        """POSIX process groups have no retained kernel handle."""

    def _signal(self, signum: int) -> None:
        if self._process.poll() is not None:
            raise _ProcessTreeIdentityError(
                f"Refusing to signal process group {self._pgid}: leader exited and identity is unprovable"
            )
        self._assert_live_leader_identity()
        try:
            os.killpg(self._pgid, signum)
        except ProcessLookupError:
            return

    def _assert_live_leader_identity(self) -> None:
        current_identity = _read_process_identity(self._process.pid)
        try:
            current_pgid = os.getpgid(self._process.pid)
        except ProcessLookupError as exc:
            raise _ProcessTreeIdentityError(
                f"Process-group leader {self._process.pid} exited during identity verification"
            ) from exc
        if current_identity != self._leader_identity or current_pgid != self._pgid:
            raise _ProcessTreeIdentityError(
                f"Process-group leader identity changed for pid={self._process.pid}"
            )


class _WindowsJobProcessTree:
    """Own a Windows process tree through a kill-on-close Job Object."""

    def __init__(
        self,
        process: subprocess.Popen[Any],
        job_handle: Any,
        kernel32: Any,
        *,
        assigned: bool = True,
    ) -> None:
        self._process = process
        self._job_handle = job_handle
        self._kernel32 = kernel32
        self._assigned = assigned

    @classmethod
    def create(
        cls,
        process: subprocess.Popen[Any],
        *,
        memory_limit_bytes: int,
        process_limit: int,
    ) -> _WindowsJobProcessTree:
        """Assign a suspended child to a Job Object before user code can run."""
        import ctypes  # noqa: PLC0415
        from ctypes import wintypes  # noqa: PLC0415

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        kernel32.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        owner = cls(process, None, kernel32, assigned=False)
        try:
            job_handle = kernel32.CreateJobObjectW(None, None)
            if not job_handle:
                raise ctypes.WinError(ctypes.get_last_error())
            owner._job_handle = job_handle

            limits = _WindowsJobExtendedLimitInformation()
            limits.BasicLimitInformation.LimitFlags = (
                0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                | 0x00000200  # JOB_OBJECT_LIMIT_JOB_MEMORY
                | 0x00000008  # JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            )
            limits.BasicLimitInformation.ActiveProcessLimit = process_limit
            limits.JobMemoryLimit = memory_limit_bytes
            configured = kernel32.SetInformationJobObject(
                job_handle,
                9,  # JobObjectExtendedLimitInformation
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            )
            if not configured:
                raise ctypes.WinError(ctypes.get_last_error())

            assigned = kernel32.AssignProcessToJobObject(
                job_handle,
                wintypes.HANDLE(int(process._handle)),
            )
            if not assigned:
                raise ctypes.WinError(ctypes.get_last_error())

            owner._assigned = True
            _resume_windows_process(process.pid, kernel32)
            return owner
        except Exception as setup_error:
            rollback_error: Exception | None = None
            try:
                owner.kill()
                if not owner.wait_gone(2.0):
                    raise RuntimeError("Windows strategy child did not terminate during creation rollback")
            except Exception as exc:  # noqa: BLE001 - close may still authoritatively kill an assigned Job
                rollback_error = exc
                logger.warning("Windows strategy Job termination rollback failed: %s", exc)
            try:
                owner.close()
            except Exception as close_error:
                raise _WindowsJobCreationRollbackError(owner, setup_error, close_error) from setup_error
            if rollback_error is not None and not owner._assigned:
                raise _WindowsJobCreationRollbackError(owner, setup_error, rollback_error) from setup_error
            raise

    def is_alive(self) -> bool:
        if not self._assigned:
            return self._process.poll() is None
        return self._active_process_count() > 0

    def terminate(self) -> None:
        if not self._assigned:
            self._process.terminate()
            return
        try:
            os.kill(self._process.pid, signal.CTRL_BREAK_EVENT)
        except (AttributeError, OSError):
            logger.debug("Windows strategy tree did not accept CTRL_BREAK; forced Job termination may follow")

    def kill(self) -> None:
        import ctypes  # noqa: PLC0415

        if not self._assigned:
            self._process.kill()
            return
        if self._job_handle and not self._kernel32.TerminateJobObject(self._job_handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    def wait_gone(self, timeout: float) -> bool:
        if not self._assigned:
            try:
                self._process.wait(timeout=max(0.0, timeout))
            except subprocess.TimeoutExpired:
                return False
            return True
        deadline = time.monotonic() + max(0.0, timeout)
        while self._active_process_count() > 0:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.02, remaining))
        return True

    def _active_process_count(self) -> int:
        """Return the Job's ActiveProcesses count without waiting on its handle."""
        import ctypes  # noqa: PLC0415

        if not self._job_handle:
            return 0
        accounting = _WindowsJobBasicAccountingInformation()
        returned_length = ctypes.c_uint32()
        queried = self._kernel32.QueryInformationJobObject(
            self._job_handle,
            1,  # JobObjectBasicAccountingInformation
            ctypes.byref(accounting),
            ctypes.sizeof(accounting),
            ctypes.byref(returned_length),
        )
        if not queried:
            raise ctypes.WinError(ctypes.get_last_error())
        return int(accounting.ActiveProcesses)

    def close(self) -> None:
        import ctypes  # noqa: PLC0415

        if self._job_handle:
            handle = self._job_handle
            if not self._kernel32.CloseHandle(handle):
                raise ctypes.WinError(ctypes.get_last_error())
            self._job_handle = None


def _resume_windows_process(pid: int, kernel32: Any) -> None:
    """Resume every initial thread of a CREATE_SUSPENDED child process."""
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    class _ThreadEntry32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ThreadID", wintypes.DWORD),
            ("th32OwnerProcessID", wintypes.DWORD),
            ("tpBasePri", wintypes.LONG),
            ("tpDeltaPri", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
        ]

    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Thread32First.restype = wintypes.BOOL
    kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry32)]
    kernel32.Thread32Next.restype = wintypes.BOOL
    kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ThreadEntry32)]
    kernel32.OpenThread.restype = wintypes.HANDLE
    kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.ResumeThread.restype = wintypes.DWORD
    kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000004, 0)  # TH32CS_SNAPTHREAD
    invalid_handle = ctypes.c_void_p(-1).value
    if snapshot == invalid_handle:
        raise ctypes.WinError(ctypes.get_last_error())

    resumed = 0
    entry = _ThreadEntry32()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        has_entry = bool(kernel32.Thread32First(snapshot, ctypes.byref(entry)))
        while has_entry:
            if entry.th32OwnerProcessID == pid:
                thread_handle = kernel32.OpenThread(0x0002, False, entry.th32ThreadID)
                if not thread_handle:
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    if kernel32.ResumeThread(thread_handle) == 0xFFFFFFFF:
                        raise ctypes.WinError(ctypes.get_last_error())
                    resumed += 1
                finally:
                    kernel32.CloseHandle(thread_handle)
            has_entry = bool(kernel32.Thread32Next(snapshot, ctypes.byref(entry)))
    finally:
        kernel32.CloseHandle(snapshot)
    if resumed == 0:
        raise RuntimeError(f"Could not locate the suspended strategy process thread for pid={pid}")


def _create_process_tree(
    process: subprocess.Popen[Any],
    system: str,
    *,
    memory_limit_bytes: int,
    process_limit: int,
) -> Any:
    """Create the platform's complete-tree ownership primitive."""
    if system == "Windows":
        return _WindowsJobProcessTree.create(
            process,
            memory_limit_bytes=memory_limit_bytes,
            process_limit=process_limit,
        )
    return _PosixProcessGroup(process)


_DESKTOP_CONTROL_ENV = frozenset(
    {
        "FLINTTRADE_PARENT_PID",
        "FLINTTRADE_PARENT_IDENTITY",
        "FLINTTRADE_SIDECAR_RECORD_PATH",
        "FLINTTRADE_BOOT_ID",
        "FLINTTRADE_LAUNCH_TOKEN",
        PACKAGED_CHILD_EXECUTABLE_ENV,
        PACKAGED_CHILD_ARG_ENV,
    }
)

# ---------------------------------------------------------------------------
# psutil import — optional; degrades gracefully on systems without it
# ---------------------------------------------------------------------------

try:
    import psutil  # type: ignore[import]

    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False
    psutil = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# OS-level resource limiting (Linux/macOS only)
# ---------------------------------------------------------------------------

try:
    import resource as _resource  # type: ignore[import]

    _RESOURCE_AVAILABLE = True
except ImportError:
    _RESOURCE_AVAILABLE = False
    _resource = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Dangerous import / call patterns rejected by the AST validator
# ---------------------------------------------------------------------------

# Top-level module names that are never allowed
_BLOCKED_MODULES: frozenset[str] = frozenset(
    {
        "os",
        "subprocess",
        "socket",
        "shutil",
        "ctypes",
        "importlib",
        "multiprocessing",
        "threading",
        "signal",
        "resource",
        "pty",
        "termios",
        "tty",
        "fcntl",
        "pwd",
        "grp",
        "select",
        "selectors",
        "asyncio",
        "concurrent",
        "mmap",
        "tempfile",
        # Network / HTTP modules — prevent data exfiltration
        "http",
        "urllib",
        "requests",
        "httpx",
        "ftplib",
        "smtplib",
        "webbrowser",
    }
)

# Built-in function names that are never allowed
_BLOCKED_BUILTINS: frozenset[str] = frozenset(
    {
        "eval",
        "exec",
        "__import__",
        "compile",
        "globals",
        "locals",
        "vars",
        "dir",
        "getattr",
        "setattr",
        "delattr",
        "open",
        "breakpoint",
        "input",
    }
)

# Attribute access patterns that are never allowed  (module.attr)
_BLOCKED_ATTR_PATTERNS: frozenset[tuple[str, str]] = frozenset(
    {
        ("os", "system"),
        ("os", "popen"),
        ("os", "execv"),
        ("os", "execve"),
        ("os", "execvp"),
        ("os", "execvpe"),
        ("os", "spawn"),
        ("os", "spawnl"),
        ("os", "fork"),
        ("subprocess", "run"),
        ("subprocess", "call"),
        ("subprocess", "check_call"),
        ("subprocess", "check_output"),
        ("subprocess", "Popen"),
    }
)

# Dunder attribute names that enable sandbox escapes (accessed on ANY object)
_FORBIDDEN_ATTRS: frozenset[str] = frozenset(
    {
        "__class__",
        "__bases__",
        "__subclasses__",
        "__globals__",
        "__code__",
    }
)


# ---------------------------------------------------------------------------
# Sandbox hardening — resource limits, bubblewrap, restricted builtins
# ---------------------------------------------------------------------------

# Builtins allowed inside the sandbox wrapper.  Dangerous names like eval,
# exec, __import__, compile, open, globals, locals, vars, dir, getattr,
# setattr, delattr are intentionally excluded.
_SAFE_BUILTINS: dict[str, Any] = {
    name: getattr(__builtins__ if isinstance(__builtins__, dict) else __builtins__, name, None)
    for name in [
        "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes",
        "callable", "chr", "classmethod", "complex", "dict", "divmod",
        "enumerate", "filter", "float", "format", "frozenset", "hash",
        "hex", "id", "int", "isinstance", "issubclass", "iter",
        "len", "list", "map", "max", "memoryview", "min", "next", "object",
        "oct", "ord", "pow", "print", "property", "range", "repr",
        "reversed", "round", "set", "slice", "sorted", "staticmethod",
        "str", "sum", "super", "tuple", "type", "zip",
    ]
}


def _build_preexec_fn(
    cpu_limit: int = 30,
    fd_limit: int | None = 64,
    nproc_limit: int = 0,
    memory_limit_bytes: int | None = None,
) -> Any:
    """Build a preexec_fn that sets OS-level resource limits.

    ``fd_limit=None`` preserves the current descriptor ceiling. Returns None
    on Windows where the resource module is unavailable.
    """
    if not _RESOURCE_AVAILABLE:
        return None
    if memory_limit_bytes is not None and not hasattr(_resource, "RLIMIT_AS"):
        raise RuntimeError("Hard uploaded-strategy memory limit enforcement is unavailable")

    def _set_limits() -> None:
        _resource.setrlimit(_resource.RLIMIT_CPU, (cpu_limit, cpu_limit))
        if fd_limit is not None:
            _resource.setrlimit(_resource.RLIMIT_NOFILE, (fd_limit, fd_limit))
        if hasattr(_resource, "RLIMIT_NPROC"):
            _resource.setrlimit(_resource.RLIMIT_NPROC, (nproc_limit, nproc_limit))
        if memory_limit_bytes is not None:
            _resource.setrlimit(
                _resource.RLIMIT_AS,
                (memory_limit_bytes, memory_limit_bytes),
            )

    return _set_limits


def _apply_uploaded_strategy_child_limits(
    *,
    memory_limit_bytes: int | None = None,
    process_limit: int = 1,
) -> None:
    """Apply resource limits inside a dispatched frozen child process."""
    # The PyInstaller application has already opened its archive and extension
    # modules. Lowering NOFILE after boot can make later runtime reads fail.
    apply_limits = _build_preexec_fn(
        fd_limit=None,
        nproc_limit=max(0, process_limit - 1),
        memory_limit_bytes=memory_limit_bytes,
    )
    if apply_limits is None:
        raise RuntimeError("Hard uploaded-strategy memory enforcement is unavailable")
    apply_limits()


def _require_platform_enforcement(system: str, *, process_limit: int) -> None:
    """Reject a launch before spawn when its hard limits cannot be installed."""
    if system == "Windows":
        return
    if system == "Darwin":
        raise RuntimeError("Hard uploaded-strategy memory enforcement is unavailable on Darwin")
    if system != "Linux":
        raise RuntimeError(f"Uploaded-strategy resource enforcement is unsupported on {system}")
    if not _RESOURCE_AVAILABLE or _resource is None or not hasattr(_resource, "RLIMIT_AS"):
        raise RuntimeError("Hard uploaded-strategy memory enforcement is unavailable")
    if not hasattr(_resource, "RLIMIT_NPROC"):
        raise RuntimeError("Hard uploaded-strategy process enforcement is unavailable")
    if not _PSUTIL_AVAILABLE:
        raise RuntimeError("POSIX uploaded-strategy process identity enforcement is unavailable")
    if process_limit != 1:
        raise RuntimeError("POSIX uploaded strategies support exactly one process per tree")


def _is_bwrap_available() -> bool:
    """Check if bubblewrap (bwrap) is installed on the system."""
    return shutil.which("bwrap") is not None


def _build_bwrap_command(python_exe: str, script_path: str) -> list[str]:
    """Build a bubblewrap sandbox command for running a strategy.

    Args:
        python_exe: Path to the Python interpreter.
        script_path: Path to the wrapper script to execute.

    Returns:
        Command list suitable for subprocess.Popen.
    """
    return [
        "bwrap",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/lib", "/lib",
        "--ro-bind", "/lib64", "/lib64",
        "--ro-bind", "/bin", "/bin",
        "--ro-bind", "/sbin", "/sbin",
        "--tmpfs", "/tmp",
        "--proc", "/proc",
        "--dev", "/dev",
        "--unshare-net",
        "--unshare-pid",
        "--die-with-parent",
        python_exe,
        script_path,
    ]


def _create_sandbox_wrapper(
    temp_dir: Path,
    *,
    memory_limit_bytes: int | None = None,
    process_limit: int = 1,
) -> Path:
    """Create a sandbox wrapper script that restricts available builtins.

    The wrapper is written into *temp_dir* and, when executed, reads the
    strategy script path from ``sys.argv[1]``, compiles it, and runs it
    with a restricted ``__builtins__`` dict.

    Returns:
        Path to the generated wrapper script.
    """
    safe_names = list(_SAFE_BUILTINS.keys())
    # Use json.dumps for the list so names are double-quoted (tests expect this).
    import json as _json
    safe_names_str = _json.dumps(safe_names)
    resource_limits = ""
    if memory_limit_bytes is not None:
        child_process_limit = max(0, process_limit - 1)
        resource_limits = (
            "import resource as _resource\n"
            "_resource.setrlimit(_resource.RLIMIT_CPU, (30, 30))\n"
            "_resource.setrlimit(_resource.RLIMIT_NOFILE, (64, 64))\n"
            f"_resource.setrlimit(_resource.RLIMIT_NPROC, ({child_process_limit}, {child_process_limit}))\n"
            f"_resource.setrlimit(_resource.RLIMIT_AS, ({memory_limit_bytes}, {memory_limit_bytes}))\n"
        )
    wrapper_code = (
        "import sys\n"
        f"{resource_limits}"
        "_safe_names = " + safe_names_str + "\n"
        "_restricted = {n: __builtins__[n] if isinstance(__builtins__, dict) else getattr(__builtins__, n) for n in _safe_names}\n"
        "_script = sys.argv[1]\n"
        "with open(_script) as _f:\n"
        "    _code = _f.read()\n"
        "exec(compile(_code, _script, 'exec'), "
        "{'__builtins__': _restricted, '__name__': '__main__', '__file__': _script})\n"
    )
    wrapper_path = temp_dir / "_sandbox_wrapper.py"
    wrapper_path.write_text(wrapper_code, encoding="utf-8")
    return wrapper_path


def _execute_uploaded_strategy_file(strategy_path: Path) -> None:
    """Execute one uploaded strategy with the restricted builtin namespace."""
    source = strategy_path.read_text(encoding="utf-8")
    runtime_builtins = __builtins__
    restricted = {
        name: runtime_builtins[name]
        if isinstance(runtime_builtins, dict)
        else getattr(runtime_builtins, name)
        for name in _SAFE_BUILTINS
    }
    namespace = {
        "__builtins__": restricted,
        "__file__": str(strategy_path),
        "__name__": "__main__",
    }
    exec(compile(source, str(strategy_path), "exec"), namespace)  # noqa: S102


def dispatch_frozen_strategy_child(argv: list[str] | None = None) -> bool:
    """Dispatch the frozen executable's uploaded-strategy child mode.

    A PyInstaller one-file executable cannot interpret ``wrapper.py`` as a
    normal Python interpreter would. Its entry script must call this function
    before starting sidecar watchdogs or importing the backend application.
    A normal parent invocation returns ``False`` and records that this early
    handshake occurred; frozen strategy launch fails closed without it.

    Args:
        argv: Argument vector to inspect. Defaults to :data:`sys.argv`.

    Returns:
        ``True`` when child mode was recognised and executed, otherwise
        ``False`` so the normal sidecar entry can continue.
    """
    global _frozen_dispatch_checked  # noqa: PLW0603 - process-wide entry handshake

    arguments = sys.argv if argv is None else argv
    if len(arguments) < 2 or arguments[1] != FROZEN_STRATEGY_CHILD_ARG:
        _frozen_dispatch_checked = True
        return False
    if len(arguments) != 3:
        raise ValueError("Frozen strategy child mode requires exactly one strategy path")

    try:
        memory_limit_bytes = int(os.environ[STRATEGY_MEMORY_LIMIT_ENV])
        process_limit = int(os.environ[STRATEGY_PROCESS_LIMIT_ENV])
    except (KeyError, ValueError) as exc:
        raise RuntimeError("Frozen strategy child resource limits are missing or invalid") from exc
    if memory_limit_bytes <= 0 or process_limit <= 0:
        raise RuntimeError("Frozen strategy child resource limits must be positive")
    system = platform.system()
    if system != "Windows":
        _require_platform_enforcement(system, process_limit=process_limit)
        _apply_uploaded_strategy_child_limits(
            memory_limit_bytes=memory_limit_bytes,
            process_limit=process_limit,
        )
    _execute_uploaded_strategy_file(Path(arguments[2]))
    return True


def _resolve_frozen_child_contract() -> tuple[str, str]:
    """Return the parent-verified frozen child executable and mode argument."""
    executable = (os.environ.get(PACKAGED_CHILD_EXECUTABLE_ENV) or "").strip()
    child_arg = (os.environ.get(PACKAGED_CHILD_ARG_ENV) or "").strip()
    if executable and child_arg == FROZEN_STRATEGY_CHILD_ARG:
        return executable, child_arg
    if _frozen_dispatch_checked:
        return sys.executable, FROZEN_STRATEGY_CHILD_ARG
    raise PackagedChildConfigurationError(
        "Frozen strategy child dispatcher is not installed by the parent entrypoint"
    )


# ---------------------------------------------------------------------------
# Running process descriptor
# ---------------------------------------------------------------------------


@dataclass
class _RunningStrategy:
    """Internal descriptor for a running strategy subprocess."""

    strategy_id: str
    name: str
    process: subprocess.Popen  # type: ignore[type-arg]
    tree: Any
    started_at: datetime
    log_path: Path
    memory_limit_mb: float = 256.0
    temp_dir: Path | None = field(default=None)
    log_file: Any = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# UserStrategyRunner
# ---------------------------------------------------------------------------


class UserStrategyRunner:
    """Execute user-uploaded Python strategy files as isolated subprocesses.

    Args:
        strategies_dir: Directory where ``.py`` strategy files are stored.
            Created automatically if it does not exist.
        log_dir: Directory for per-strategy stdout/stderr log files.
            Defaults to ``strategies_dir / "logs"``.
        memory_limit_mb: Maximum hard memory budget (MB) allowed per strategy
            tree, enforced before uploaded code can execute.
        max_concurrent_strategies: Maximum number of process trees retained by
            this runner, including trees whose state is uncertain.
        max_processes_per_strategy: Maximum processes in each strategy tree.
    """

    def __init__(
        self,
        strategies_dir: Path,
        log_dir: Path | None = None,
        memory_limit_mb: float = 256.0,
        max_concurrent_strategies: int = 4,
        max_processes_per_strategy: int = 1,
    ) -> None:
        if not math.isfinite(memory_limit_mb) or memory_limit_mb <= 0:
            raise ValueError("memory_limit_mb must be a positive finite number")
        if not isinstance(max_concurrent_strategies, int) or isinstance(max_concurrent_strategies, bool):
            raise ValueError("max_concurrent_strategies must be a positive integer")
        if max_concurrent_strategies < 1:
            raise ValueError("max_concurrent_strategies must be a positive integer")
        if not isinstance(max_processes_per_strategy, int) or isinstance(max_processes_per_strategy, bool):
            raise ValueError("max_processes_per_strategy must be a positive integer")
        if max_processes_per_strategy < 1:
            raise ValueError("max_processes_per_strategy must be a positive integer")
        self._strategies_dir = Path(strategies_dir)
        self._strategies_dir.mkdir(parents=True, exist_ok=True)

        self._log_dir = Path(log_dir) if log_dir else self._strategies_dir / "logs"
        self._log_dir.mkdir(parents=True, exist_ok=True)

        self._memory_limit_mb = memory_limit_mb
        self._memory_limit_bytes = int(memory_limit_mb * 1024 * 1024)
        self._max_concurrent_strategies = int(max_concurrent_strategies)
        self._max_processes_per_strategy = int(max_processes_per_strategy)
        # strategy_id → _RunningStrategy
        self._running: dict[str, _RunningStrategy] = {}
        self._lifecycle_lock = threading.RLock()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self, code: str) -> list[str]:
        """Static-analyse ``code`` for dangerous patterns.

        Uses Python's built-in :mod:`ast` module to parse and walk the syntax
        tree.  No code is executed.

        Args:
            code: Python source code to validate.

        Returns:
            List of violation messages.  Empty list means the code is safe to
            upload.
        """
        violations: list[str] = []

        # Parse stage — syntax errors are caught here
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return [f"SyntaxError: {exc}"]

        for node in ast.walk(tree):
            # Block dangerous imports: import os / from os import system
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module_name = ""
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module_name = alias.name.split(".")[0]
                        if module_name in _BLOCKED_MODULES:
                            violations.append(
                                f"Blocked import: '{alias.name}' — module '{module_name}' is not allowed"
                            )
                elif isinstance(node, ast.ImportFrom):
                    module_name = (node.module or "").split(".")[0]
                    if module_name in _BLOCKED_MODULES:
                        violations.append(
                            f"Blocked import: 'from {node.module} import ...' — "
                            f"module '{module_name}' is not allowed"
                        )
                    # Also check imported names for dangerous builtins re-exported
                    for alias in node.names:
                        if alias.name in _BLOCKED_BUILTINS:
                            violations.append(
                                f"Blocked import: 'from {node.module} import {alias.name}'"
                            )

            # Block forbidden dunder attribute access on any object
            # (e.g. obj.__class__, obj.__subclasses__())
            elif isinstance(node, ast.Attribute):
                if node.attr in _FORBIDDEN_ATTRS:
                    violations.append(
                        f"Blocked attribute: '.{node.attr}' access is not allowed in strategies"
                    )

            # Block dangerous built-in calls: eval("..."), exec("..."), __import__(...)
            elif isinstance(node, ast.Call):
                func = node.func
                # Direct call: eval(...), exec(...), open(..., "w")
                if isinstance(func, ast.Name) and func.id in _BLOCKED_BUILTINS:
                    if func.id == "open":
                        # Only flag open() if it has a write-mode argument
                        _check_open_call(node, violations)
                    else:
                        violations.append(
                            f"Blocked call: '{func.id}()' is not allowed in strategies"
                        )
                # Attribute call: os.system(...), subprocess.Popen(...)
                elif isinstance(func, ast.Attribute):
                    if isinstance(func.value, ast.Name):
                        pair = (func.value.id, func.attr)
                        if pair in _BLOCKED_ATTR_PATTERNS:
                            violations.append(
                                f"Blocked call: '{func.value.id}.{func.attr}()' is not allowed"
                            )

        return violations

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def upload(self, name: str, code: str) -> str:
        """Validate and save a strategy file.

        Args:
            name: Strategy name (used as the filename base).  Must be a valid
                Python identifier.
            code: Python source code.

        Returns:
            Unique strategy_id (UUID string).

        Raises:
            ValueError: If ``code`` contains violations, or ``name`` is not a
                valid Python identifier.
        """
        if not name.isidentifier():
            raise ValueError(
                f"Strategy name '{name}' is not a valid Python identifier. "
                "Use letters, digits, and underscores only."
            )

        violations = self.validate(code)
        if violations:
            raise ValueError(
                f"Strategy '{name}' failed validation ({len(violations)} issue(s)):\n"
                + "\n".join(f"  - {v}" for v in violations)
            )

        strategy_id = str(uuid.uuid4())
        strategy_path = self._strategies_dir / f"{strategy_id}.py"
        # Prepend a metadata header comment so the file is self-describing
        header = (
            f"# FlintTrade Strategy\n"
            f"# name: {name}\n"
            f"# strategy_id: {strategy_id}\n"
            f"# uploaded_at: {datetime.now(timezone.utc).isoformat()}\n\n"
        )
        strategy_path.write_text(header + code, encoding="utf-8")

        # Save a mapping file: strategy_id.meta
        meta_path = self._strategies_dir / f"{strategy_id}.meta"
        meta_path.write_text(name, encoding="utf-8")

        logger.info("Strategy uploaded: %s (id=%s)", name, strategy_id)
        return strategy_id

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------

    @staticmethod
    def _cleanup_temp_dir(temp_dir: Path | None) -> None:
        """Remove a strategy's temporary directory.  No-op if *temp_dir* is None."""
        if temp_dir is None:
            return
        shutil.rmtree(temp_dir, ignore_errors=True)

    def _release_entry_resources(self, entry: _RunningStrategy) -> None:
        """Close an owned process entry's files and remove its temporary dir."""
        if entry.log_file is not None:
            try:
                entry.log_file.close()
            except Exception:
                logger.exception(
                    "Failed to close log file handle for strategy %s (id=%s)",
                    entry.name,
                    entry.strategy_id,
                )
            finally:
                entry.log_file = None
        self._cleanup_temp_dir(entry.temp_dir)
        entry.temp_dir = None

    def _release_verified_entry(self, entry: _RunningStrategy) -> int | None:
        """Release a process entry only after its entire tree is gone."""
        try:
            exit_code = entry.process.wait(timeout=0)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Could not reap strategy {entry.strategy_id} leader after its process tree stopped"
            ) from exc
        entry.tree.close()
        self._release_entry_resources(entry)
        return exit_code

    def start(self, strategy_id: str) -> None:
        """Launch a strategy as a sandboxed subprocess.

        Each strategy runs in its own temporary directory with a restricted
        builtins wrapper.  On Linux with bubblewrap installed the process is
        additionally network-isolated and PID-namespaced.

        Args:
            strategy_id: ID returned by :meth:`upload`.

        Raises:
            FileNotFoundError: If the strategy file does not exist.
            PackagedChildConfigurationError: If packaged child dispatch is not configured.
            RuntimeError: If the strategy is already running.
        """
        with self._lifecycle_lock:
            self._start_locked(strategy_id)

    def _start_locked(self, strategy_id: str) -> None:
        """Launch and publish one child while ``_lifecycle_lock`` is held."""
        strategy_path = self._strategies_dir / f"{strategy_id}.py"
        if not strategy_path.exists():
            raise FileNotFoundError(f"Strategy file not found: {strategy_path}")

        if strategy_id in self._running:
            entry = self._running[strategy_id]
            if entry.tree.is_alive():
                proc = entry.process
                raise RuntimeError(f"Strategy {strategy_id} is already running (pid={proc.pid})")
            self._release_verified_entry(entry)
            del self._running[strategy_id]

        if len(self._running) >= self._max_concurrent_strategies:
            raise RuntimeError(
                f"Uploaded-strategy concurrent strategy limit reached ({self._max_concurrent_strategies})"
            )

        name = self._get_name(strategy_id)
        log_path = self._log_dir / f"{strategy_id}.log"
        frozen = bool(getattr(sys, "frozen", False))
        system = platform.system()
        _require_platform_enforcement(
            system,
            process_limit=self._max_processes_per_strategy,
        )
        child_executable, child_arg = (
            _resolve_frozen_child_contract()
            if frozen
            else (sys.executable, "")
        )

        # Create an isolated temp directory for this run
        temp_dir = Path(tempfile.mkdtemp(prefix=f"flinttrade_{strategy_id[:8]}_"))

        # Create the sandbox wrapper script
        wrapper_path = _create_sandbox_wrapper(
            temp_dir,
            memory_limit_bytes=self._memory_limit_bytes if system == "Linux" else None,
            process_limit=self._max_processes_per_strategy,
        )

        log_file = open(log_path, "a", encoding="utf-8")  # noqa: WPS515

        try:
            # Build command — bwrap on Linux when available, plain subprocess otherwise
            use_bwrap = not frozen and system == "Linux" and _is_bwrap_available()
            child_arg = child_arg if frozen else str(wrapper_path)
            if use_bwrap:
                cmd: list[str] = _build_bwrap_command(child_executable, child_arg)
                cmd.append(str(strategy_path))
            else:
                cmd = [child_executable, child_arg, str(strategy_path)]

            # A frozen one-file executable has a bootloader parent that must
            # spawn the Python application process. Apply limits in the early
            # child dispatcher instead of blocking that bootloader with
            # RLIMIT_NPROC=0 before exec.
            preexec_fn = (
                None
                if frozen or system == "Windows" or use_bwrap
                else _build_preexec_fn(
                    nproc_limit=max(0, self._max_processes_per_strategy - 1),
                    memory_limit_bytes=self._memory_limit_bytes,
                )
            )
            child_env = {
                key: value
                for key, value in os.environ.items()
                if key not in _DESKTOP_CONTROL_ENV
            }
            child_env[STRATEGY_MEMORY_LIMIT_ENV] = str(self._memory_limit_bytes)
            child_env[STRATEGY_PROCESS_LIMIT_ENV] = str(self._max_processes_per_strategy)

            platform_spawn: dict[str, Any]
            if system == "Windows":
                platform_spawn = {
                    "creationflags": _WINDOWS_CREATE_NEW_PROCESS_GROUP | _WINDOWS_CREATE_SUSPENDED,
                }
            else:
                platform_spawn = {"start_new_session": True}

            process = subprocess.Popen(  # noqa: S603
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=log_file,
                cwd=str(temp_dir),
                env=child_env,
                close_fds=True,
                preexec_fn=preexec_fn,
                **platform_spawn,
            )
            ownership_process_limit = self._max_processes_per_strategy + int(frozen and system == "Windows")
            tree = _create_process_tree(
                process,
                system,
                memory_limit_bytes=self._memory_limit_bytes,
                process_limit=ownership_process_limit,
            )
        except _WindowsJobCreationRollbackError as exc:
            self._running[strategy_id] = _RunningStrategy(
                strategy_id=strategy_id,
                name=name,
                process=process,
                tree=exc.process_tree,
                started_at=datetime.now(timezone.utc),
                log_path=log_path,
                memory_limit_mb=self._memory_limit_mb,
                temp_dir=temp_dir,
                log_file=log_file,
            )
            logger.error(
                "Windows strategy start failed with process-tree ownership retained: %s (id=%s, pid=%d)",
                name,
                strategy_id,
                process.pid,
            )
            raise
        except Exception:
            log_file.close()
            self._cleanup_temp_dir(temp_dir)
            raise

        self._running[strategy_id] = _RunningStrategy(
            strategy_id=strategy_id,
            name=name,
            process=process,
            tree=tree,
            started_at=datetime.now(timezone.utc),
            log_path=log_path,
            memory_limit_mb=self._memory_limit_mb,
            temp_dir=temp_dir,
            log_file=log_file,
        )
        logger.info("Strategy started: %s (id=%s, pid=%d)", name, strategy_id, process.pid)

    def stop(self, strategy_id: str) -> None:
        """Terminate a running strategy subprocess.

        Sends SIGTERM first; if the process does not exit within 5 seconds,
        sends SIGKILL.

        Args:
            strategy_id: ID of the running strategy.

        Raises:
            RuntimeError: If the strategy is not currently running.
        """
        with self._lifecycle_lock:
            self._stop_locked(strategy_id)

    def _stop_locked(self, strategy_id: str) -> None:
        """Terminate one child while ``_lifecycle_lock`` owns its identity."""
        if strategy_id not in self._running:
            strategy_path = self._strategies_dir / f"{strategy_id}.py"
            if not strategy_path.exists():
                raise FileNotFoundError(f"Strategy not found: {strategy_id}")
            raise StrategyNotRunningError(f"Strategy {strategy_id} is not running")

        entry = self._running[strategy_id]
        tree = entry.tree

        try:
            if tree.is_alive():
                tree.terminate()
                if not tree.wait_gone(5.0):
                    tree.kill()
                    if not tree.wait_gone(2.0):
                        raise RuntimeError(
                            f"Could not confirm strategy {strategy_id} process-tree termination after forced kill"
                        )
            if tree.is_alive():
                raise RuntimeError(f"Could not confirm strategy {strategy_id} process tree is empty")
        except Exception:
            # Keep the complete ownership record and resources for a later retry.
            raise

        self._release_verified_entry(entry)
        self._running.pop(strategy_id, None)

        logger.info("Strategy stopped: %s (id=%s)", entry.name, strategy_id)

    def stop_all(self) -> list[str]:
        """Stop every uploaded strategy process currently owned by this runner.

        All entries are attempted even if one process fails to terminate. A
        combined ``RuntimeError`` is raised only after the remaining children
        have been handled, allowing the parent shutdown owner to fail closed.

        Returns:
            Strategy IDs stopped during this call.
        """
        with self._lifecycle_lock:
            return self._stop_all_locked()

    def _stop_all_locked(self) -> list[str]:
        """Stop every child while lifecycle ownership cannot change."""
        stopped: list[str] = []
        failures: list[tuple[str, Exception]] = []
        for strategy_id in tuple(self._running):
            try:
                self.stop(strategy_id)
            except Exception as exc:  # noqa: BLE001 - shutdown continues for siblings
                failures.append((strategy_id, exc))
                logger.exception("Failed to stop uploaded strategy %s", strategy_id)
            else:
                stopped.append(strategy_id)

        if failures:
            failed_ids = ", ".join(strategy_id for strategy_id, _ in failures)
            raise RuntimeError(f"Failed to stop uploaded strategies: {failed_ids}") from failures[0][1]
        return stopped

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, strategy_id: str) -> None:
        """Stop a running strategy (if any) and delete its files.

        Args:
            strategy_id: ID of the strategy to delete.

        Raises:
            FileNotFoundError: If the strategy file does not exist.
        """
        with self._lifecycle_lock:
            self._delete_locked(strategy_id)

    def _delete_locked(self, strategy_id: str) -> None:
        """Delete one strategy while start/stop/status cannot race it."""
        strategy_path = self._strategies_dir / f"{strategy_id}.py"
        if not strategy_path.exists():
            raise FileNotFoundError(f"Strategy not found: {strategy_id}")

        # Stop first if running
        if strategy_id in self._running:
            # Fail closed: deleting the files after a termination failure would
            # hide a still-owned child behind a successful API response.
            self.stop(strategy_id)

        # Remove files
        strategy_path.unlink(missing_ok=True)
        meta_path = self._strategies_dir / f"{strategy_id}.meta"
        meta_path.unlink(missing_ok=True)
        log_path = self._log_dir / f"{strategy_id}.log"
        log_path.unlink(missing_ok=True)

        logger.info("Strategy deleted: %s", strategy_id)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self, strategy_id: str) -> dict[str, Any]:
        """Return status for a strategy.

        Args:
            strategy_id: ID of the strategy.

        Returns:
            Dict with keys: strategy_id, name, state (running/stopped/crashed),
            pid, memory_mb, uptime_seconds, log_path.

        Raises:
            FileNotFoundError: If the strategy does not exist.
        """
        with self._lifecycle_lock:
            return self._get_status_locked(strategy_id)

    def _get_status_locked(self, strategy_id: str) -> dict[str, Any]:
        """Snapshot one strategy while lifecycle ownership is stable."""
        strategy_path = self._strategies_dir / f"{strategy_id}.py"
        if not strategy_path.exists():
            raise FileNotFoundError(f"Strategy not found: {strategy_id}")

        name = self._get_name(strategy_id)
        log_path = self._log_dir / f"{strategy_id}.log"

        if strategy_id not in self._running:
            return {
                "strategy_id": strategy_id,
                "name": name,
                "state": "stopped",
                "pid": None,
                "memory_mb": None,
                "uptime_seconds": None,
                "log_path": str(log_path),
            }

        entry = self._running[strategy_id]
        proc = entry.process
        poll = proc.poll()

        try:
            tree_alive = entry.tree.is_alive()
        except Exception:
            logger.exception("Could not verify process-tree state for strategy %s", strategy_id)
            return {
                "strategy_id": strategy_id,
                "name": name,
                "state": "unknown",
                "pid": proc.pid,
                "memory_mb": None,
                "uptime_seconds": None,
                "ownership_retained": True,
                "log_path": str(log_path),
            }

        if not tree_alive:
            exit_code = self._release_verified_entry(entry)
            del self._running[strategy_id]
            state = "crashed" if exit_code not in (None, 0) else "stopped"
            return {
                "strategy_id": strategy_id,
                "name": name,
                "state": state,
                "pid": proc.pid,
                "memory_mb": None,
                "uptime_seconds": None,
                "exit_code": exit_code,
                "log_path": str(log_path),
            }

        # Process is running — collect memory usage via psutil
        memory_mb: float | None = None
        if _PSUTIL_AVAILABLE:
            try:
                ps = psutil.Process(proc.pid)
                memory_mb = ps.memory_info().rss / (1024 * 1024)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        uptime = (datetime.now(timezone.utc) - entry.started_at).total_seconds()

        return {
            "strategy_id": strategy_id,
            "name": name,
            "state": "running",
            "pid": proc.pid,
            "leader_exited": poll is not None,
            "memory_mb": memory_mb,
            "uptime_seconds": uptime,
            "log_path": str(log_path),
        }

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    def list_strategies(self) -> list[dict[str, Any]]:
        """Return all uploaded strategies with their current status.

        Returns:
            List of status dicts (one per strategy), sorted by name.
        """
        strategies = []
        for meta_path in sorted(self._strategies_dir.glob("*.meta")):
            strategy_id = meta_path.stem
            try:
                status = self.get_status(strategy_id)
            except FileNotFoundError:
                continue
            strategies.append(status)
        return strategies

    # ------------------------------------------------------------------
    # Logs
    # ------------------------------------------------------------------

    def get_logs(self, strategy_id: str, lines: int = 100) -> list[str]:
        """Return the last ``lines`` lines from the strategy log file.

        Args:
            strategy_id: ID of the strategy.
            lines: Maximum number of log lines to return (most recent first).

        Returns:
            List of log lines (most recent last).

        Raises:
            FileNotFoundError: If the strategy does not exist.
        """
        strategy_path = self._strategies_dir / f"{strategy_id}.py"
        if not strategy_path.exists():
            raise FileNotFoundError(f"Strategy not found: {strategy_id}")

        log_path = self._log_dir / f"{strategy_id}.log"
        if not log_path.exists():
            return []

        all_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return all_lines[-lines:]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_name(self, strategy_id: str) -> str:
        """Read the human-readable name from the .meta file."""
        meta_path = self._strategies_dir / f"{strategy_id}.meta"
        if meta_path.exists():
            return meta_path.read_text(encoding="utf-8").strip()
        return strategy_id


# ---------------------------------------------------------------------------
# Helper: validate open() call mode
# ---------------------------------------------------------------------------


def _check_open_call(node: ast.Call, violations: list[str]) -> None:
    """Flag ``open()`` calls that include a write mode argument.

    This inspects positional and keyword arguments for ``"w"``, ``"wb"``,
    ``"a"``, ``"ab"``, ``"x"``, ``"xb"`` mode strings.

    Args:
        node: The :class:`ast.Call` node for the ``open()`` call.
        violations: List to append violation messages to.
    """
    write_modes = frozenset({"w", "wb", "a", "ab", "x", "xb", "w+", "r+", "a+"})

    # Check second positional argument (mode)
    if len(node.args) >= 2:
        mode_arg = node.args[1]
        if isinstance(mode_arg, ast.Constant) and str(mode_arg.value) in write_modes:
            violations.append(
                f"Blocked call: 'open()' with write mode '{mode_arg.value}' is not allowed"
            )
            return

    # Check 'mode' keyword argument
    for keyword in node.keywords:
        if keyword.arg == "mode":
            if isinstance(keyword.value, ast.Constant) and str(keyword.value.value) in write_modes:
                violations.append(
                    f"Blocked call: 'open()' with write mode '{keyword.value.value}' is not allowed"
                )
                return
