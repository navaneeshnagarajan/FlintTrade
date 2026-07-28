#!/usr/bin/env python3
"""FlintTrade cross-platform task runner.

``scripts/ft.py`` is the single task entry point that behaves identically on
Windows, macOS and Linux. It replaces the shell-only parts of the Makefile, so
none of the following are required: ``make``, ``bash``, ``lsof``, ``ss``,
``find``, ``du``, ``grep``, ``awk`` or ``echo -e``. Nothing outside the Python
standard library is imported.

Usage::

    python scripts/ft.py <start|stop|restart|status|dev|setup|test|test-fast|lint|clean|version|help|
                          desktop-test|desktop-build|desktop-package|desktop-dev>

After a FlintTrade install the shim exposes exactly the same interface as::

    flinttrade <same subcommands>

Run ``python scripts/ft.py help`` for the full command table.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
"""Repository root - ``scripts/ft.py`` lives one level below it."""

IS_WINDOWS = os.name == "nt"

BACKEND_HOST = os.environ.get("FLINTTRADE_BACKEND_HOST", "127.0.0.1")
BACKEND_PORT = int(os.environ.get("FLINTTRADE_BACKEND_PORT", "5100"))
OPENALGO_PORT = int(os.environ.get("OPENALGO_PORT", "5000"))
BACKEND_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"

CORE_SRC = REPO_ROOT / "packages" / "core" / "core" / "src"
DEV_LOG_DIR = REPO_ROOT / ".local" / "dev-logs"
DESKTOP_PKG = "packages/apps/desktop"
TERMINAL_PKG = "packages/apps/terminal"

PINNED_PNPM_VERSION = "9.15.0"

# Directories that `clean` and the workspace walk never descend into: the repo
# virtualenv, the git object store, and the gitignored .local/ scratch tree
# (external test-dep clones and archives live there and are not ours to delete).
PRUNED_DIRS = frozenset({".git", ".venv", ".local"})

# Every key here MUST have a handler in HANDLERS and MUST appear in the
# Makefile header's "Via scripts/ft.py" list - tests/test_ft_runner.py pins all
# three surfaces together, because a command documented in only two of them is
# a command that exits 2 when a user runs it.
COMMANDS: dict[str, str] = {
    "start": "Start the FlintTrade backend API on port 5100",
    "start-gateway": "Alias for start (the standalone FlintTrade backend)",
    "stop": "Stop the FlintTrade backend listening on the backend port",
    "restart": "Stop then start the FlintTrade backend",
    "status": "Show backend, port-ownership, workspace and version status",
    "dev": "Run the terminal dev server alongside the FlintTrade backend",
    "setup": "First-time setup - install Python and Node dependencies",
    "test": "Run the full pytest suite (plus the Rust ticks crate when cargo is present)",
    "test-fast": "Run pytest and stop on the first failure",
    "lint": "Run ruff over packages/ and tests/",
    "clean": "Delete __pycache__, .pytest_cache and node_modules trees",
    "version": "Print the FlintTrade version",
    "help": "Show this command table",
    "desktop-test": "Typecheck and test the Electron shell",
    "desktop-build": "Verify and bundle the Electron shell",
    "desktop-package": "Package and verify the Electron installer for this OS/arch",
    "desktop-dev": "Run the Electron shell against its managed source bootstrap",
}


# ---------------------------------------------------------------------------
# Output helpers (ASCII only - Windows consoles default to a non-UTF-8 codepage)
# ---------------------------------------------------------------------------


def info(message: str) -> None:
    """Print an informational line to stdout.

    Args:
        message: The text to display.
    """
    print(message, flush=True)


def warn(message: str) -> None:
    """Print a warning line to stderr.

    Args:
        message: The text to display.
    """
    print(f"warning: {message}", file=sys.stderr, flush=True)


def fail(message: str) -> None:
    """Print an error line to stderr.

    Args:
        message: The text to display.
    """
    print(f"error: {message}", file=sys.stderr, flush=True)


def header(title: str) -> None:
    """Print a section header.

    Args:
        title: The section name.
    """
    print(f"\n=== {title} ===", flush=True)


# ---------------------------------------------------------------------------
# Interpreter resolution
# ---------------------------------------------------------------------------


def is_store_alias(candidate: str | Path) -> bool:
    """Recognise a Microsoft Store "App execution alias" stub.

    Windows ships ``python.exe``/``python3.exe`` shims under ``WindowsApps`` that
    exist on ``PATH`` but do not run anything: invoked non-interactively they
    exit 49 and open the Store instead. They must never be selected silently.

    Args:
        candidate: Path to a candidate interpreter.

    Returns:
        True when the path lives inside a ``WindowsApps`` directory.
    """
    if not IS_WINDOWS:
        return False
    return "\\windowsapps\\" in str(candidate).replace("/", "\\").lower()


def probe_python(candidate: str | Path) -> bool:
    """Check that *candidate* is a real, runnable CPython interpreter.

    This is the check that rejects the Microsoft Store alias stub: the stub
    exits 49 without executing the ``-c`` snippet, so a non-zero return code
    means the candidate is unusable and the caller should fall through.

    Args:
        candidate: Path to a candidate interpreter.

    Returns:
        True when the interpreter ran the probe successfully.
    """
    try:
        proc = subprocess.run(
            [str(candidate), "-c", "import sys; sys.exit(0)"],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def resolve_python() -> str:
    """Resolve the interpreter used for every FlintTrade Python invocation.

    Resolution order:

    1. The repository virtualenv - ``.venv/Scripts/python.exe`` on Windows and
       ``.venv/bin/python`` on POSIX. ``uv`` creates only one of the two, so both
       layouts are checked rather than assuming the POSIX one, but the host's own
       layout is always tried first: a ``.venv`` shared with a Windows host (or
       left behind by WSL) must never win over the layout that can actually run.
    2. The interpreter currently running this script.
    3. ``python3`` then ``python`` from ``PATH``.

    Every ``PATH`` candidate is probed, which is what recognises and rejects the
    Microsoft Store alias stub.

    Returns:
        An absolute (or ``PATH``-resolved) path to a working interpreter.

    Raises:
        SystemExit: When no usable interpreter could be found.
    """
    venv = REPO_ROOT / ".venv"
    windows_layout = (venv / "Scripts" / "python.exe",)
    posix_layout = (venv / "bin" / "python", venv / "bin" / "python3")
    venv_candidates = windows_layout + posix_layout if IS_WINDOWS else posix_layout + windows_layout
    for candidate in venv_candidates:
        if candidate.is_file() and probe_python(candidate):
            return str(candidate)

    if sys.executable and not is_store_alias(sys.executable):
        return sys.executable

    for name in ("python3", "python"):
        found = shutil.which(name)
        if not found:
            continue
        if is_store_alias(found):
            # A Store alias may still be a genuine Store-installed Python; probe
            # before discarding it, and fall through when it is the stub.
            if not probe_python(found):
                continue
            return found
        if probe_python(found):
            return found

    fail("No usable Python interpreter found.")
    fail("Install Python 3.12+ from https://python.org (tick 'Add python.exe to PATH' on Windows),")
    fail("or create the repo virtualenv with: uv sync --frozen --all-packages")
    raise SystemExit(1)


def python_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build the child-process environment for FlintTrade Python commands.

    ``PYTHONPATH`` is joined with :data:`os.pathsep` so it is ``;`` on Windows
    and ``:`` on POSIX - hardcoding ``:`` silently breaks every import on
    Windows because drive letters then split the path.

    Args:
        extra: Additional environment entries to overlay.

    Returns:
        A complete environment mapping for :mod:`subprocess`.
    """
    env = os.environ.copy()
    parts = [str(CORE_SRC)]
    existing = env.get("PYTHONPATH", "")
    if existing:
        parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    if extra:
        env.update(extra)
    return env


# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------


def run(
    argv: Sequence[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    check: bool = True,
    quiet: bool = False,
) -> int:
    """Run a command and optionally propagate its failure.

    Args:
        argv: The command and its arguments.
        env: Environment for the child process; inherited when omitted.
        cwd: Working directory; the repository root when omitted.
        check: Raise :class:`SystemExit` with the child's code on failure.
        quiet: Discard the child's stdout. stderr is NEVER discarded - a quiet
            step that fails must still say why, otherwise the runner aborts with
            a bare exit code and the user sees nothing at all.

    Returns:
        The child's exit code.

    Raises:
        SystemExit: When ``check`` is set and the command failed.
    """
    proc = subprocess.run(
        [str(part) for part in argv],
        env=env,
        cwd=str(cwd or REPO_ROOT),
        stdout=subprocess.DEVNULL if quiet else None,
        stderr=None,
        check=False,
    )
    if check and proc.returncode != 0:
        raise SystemExit(proc.returncode)
    return proc.returncode


def capture(argv: Sequence[str], *, cwd: Path | None = None, timeout: float = 30.0) -> str | None:
    """Run a command and return its stripped stdout.

    Args:
        argv: The command and its arguments.
        cwd: Working directory; the repository root when omitted.
        timeout: Seconds to wait before giving up.

    Returns:
        The stripped stdout, or None when the command is missing or failed.
    """
    try:
        proc = subprocess.run(
            [str(part) for part in argv],
            cwd=str(cwd or REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


# ---------------------------------------------------------------------------
# Port ownership (no lsof dependency)
# ---------------------------------------------------------------------------


def port_is_live(port: int, host: str = BACKEND_HOST, timeout: float = 0.6) -> bool:
    """Test whether something is listening on a local TCP port.

    A plain loopback connect works identically on every OS, so liveness never
    depends on ``lsof``.

    Args:
        port: TCP port to probe.
        host: Interface to connect to.
        timeout: Connect timeout in seconds.

    Returns:
        True when the connect succeeded.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _owner_pid_windows(port: int) -> int | None:
    """Resolve the listening PID on Windows via ``Get-NetTCPConnection``."""
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if not shell:
        return None
    script = (
        f"$c = Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue | "
        "Select-Object -First 1; if ($c) { $c.OwningProcess }"
    )
    out = capture([shell, "-NoProfile", "-NonInteractive", "-Command", script])
    if not out:
        return None
    match = re.search(r"\d+", out)
    return int(match.group(0)) if match else None


def _owner_pid_posix(port: int) -> int | None:
    """Resolve the listening PID on POSIX via ``lsof`` or ``ss``."""
    lsof = shutil.which("lsof")
    if lsof:
        out = capture([lsof, f"-tiTCP:{port}", "-sTCP:LISTEN"])
        if out:
            first = out.splitlines()[0].strip()
            if first.isdigit():
                return int(first)
    ss_bin = shutil.which("ss")
    if ss_bin:
        out = capture([ss_bin, "-ltnp", f"sport = :{port}"])
        if out:
            match = re.search(r"pid=(\d+)", out)
            if match:
                return int(match.group(1))
    return None


def port_owner_pid(port: int) -> int | None:
    """Resolve the PID owning a listening TCP port.

    Args:
        port: TCP port to inspect.

    Returns:
        The owning PID, or None when it could not be determined. None means
        "unknown" - never "free"; use :func:`port_is_live` for liveness.
    """
    if IS_WINDOWS:
        return _owner_pid_windows(port)
    return _owner_pid_posix(port)


def describe_port(port: int) -> str:
    """Describe a port's state in one line.

    Args:
        port: TCP port to inspect.

    Returns:
        A human-readable state such as ``in use (PID 1234)`` or ``free``.
    """
    if not port_is_live(port):
        return "free"
    pid = port_owner_pid(port)
    if pid is None:
        return "in use (owner unknown)"
    return f"in use (PID {pid})"


def terminate_pid(pid: int) -> bool:
    """Terminate a process by PID, including its children on Windows.

    Args:
        pid: The process identifier.

    Returns:
        True when the terminate request was accepted.
    """
    if IS_WINDOWS:
        taskkill = shutil.which("taskkill")
        if taskkill:
            proc = subprocess.run(
                [taskkill, "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
            return proc.returncode == 0
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------
# Canonical paths
# ---------------------------------------------------------------------------


def workspace_dir() -> Path:
    """Resolve the canonical per-OS FlintTrade workspace directory.

    MIRROR: this is a byte-for-byte behavioural twin of
    ``flinttrade_core.workspace.workspace_dir`` / ``_default_home`` in
    ``packages/core/core/src/flinttrade_core/workspace.py``. The two MUST agree;
    ``tests/test_ft_runner.py`` compares them on every platform and both env
    overrides. It is deliberately duplicated rather than imported because
    ``scripts/ft.py`` is stdlib-only and has to run before any dependency (and
    therefore ``flinttrade_core``) is installed - it is what installs them.

    Precedence matches the core resolver: ``FLINTTRADE_WORKSPACE_DIR`` beats
    ``FLINTTRADE_HOME``, which beats the platform default (``~/.flinttrade`` on
    Linux, ``~/Library/Application Support/flinttrade`` on macOS,
    ``%APPDATA%/flinttrade`` on Windows). Both overrides are resolved, exactly as
    the core does; the platform defaults are not.

    Returns:
        The workspace directory. Unlike the core resolver this helper never
        creates the directory - ``status`` must be able to report its absence.
    """
    for name in ("FLINTTRADE_WORKSPACE_DIR", "FLINTTRADE_HOME"):
        value = os.environ.get(name)
        if value:
            return Path(value).expanduser().resolve()
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "flinttrade"
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "flinttrade"
        return Path.home() / "AppData" / "Roaming" / "flinttrade"
    return Path.home() / ".flinttrade"


def dir_size_bytes(path: Path) -> int:
    """Total size of every regular file below *path*.

    Replaces ``du -sh``, which does not exist on Windows.

    Args:
        path: Directory to measure.

    Returns:
        The total size in bytes; 0 when the directory is missing.
    """
    total = 0
    for root, _dirnames, filenames in os.walk(path, onerror=lambda _e: None):
        for filename in filenames:
            try:
                total += (Path(root) / filename).stat().st_size
            except OSError:
                continue
    return total


def format_size(num_bytes: int) -> str:
    """Render a byte count in human-readable units.

    Args:
        num_bytes: Size in bytes.

    Returns:
        A short string such as ``12.4MB``.
    """
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0:
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}TB"


def read_version() -> str:
    """Read the repository VERSION file.

    Returns:
        The version string, or ``unknown`` when the file is absent.
    """
    version_file = REPO_ROOT / "VERSION"
    try:
        return version_file.read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


# ---------------------------------------------------------------------------
# Node toolchain
# ---------------------------------------------------------------------------


def pnpm_argv() -> list[str] | None:
    """Resolve a pinned pnpm invocation prefix.

    Mirrors the installer's resolution chain: corepack first, then a pnpm binary
    already on ``PATH`` at the pinned version, then ``npx --yes pnpm@<pinned>``.

    Returns:
        The argv prefix to which pnpm arguments are appended, or None when no
        Node toolchain is available.
    """
    corepack = shutil.which("corepack")
    if corepack:
        return [corepack, "pnpm"]
    pnpm = shutil.which("pnpm")
    if pnpm and capture([pnpm, "--version"]) == PINNED_PNPM_VERSION:
        return [pnpm]
    npx = shutil.which("npx")
    if npx:
        return [npx, "--yes", f"pnpm@{PINNED_PNPM_VERSION}"]
    return None


def require_pnpm() -> list[str]:
    """Resolve pnpm or abort with remediation text.

    Returns:
        The pnpm argv prefix.

    Raises:
        SystemExit: When no Node toolchain could be found.
    """
    argv = pnpm_argv()
    if argv is None:
        fail("No Node toolchain found (corepack, pnpm or npx).")
        fail("Install Node 22.22+ from https://nodejs.org/ and re-run.")
        raise SystemExit(1)
    return argv


def ci_env() -> dict[str, str]:
    """Build the environment used for Node commands.

    ``CI=true`` is set through the environment dictionary rather than a
    ``CI=true cmd`` shell prefix, which cmd.exe does not understand.

    Returns:
        A complete environment mapping with ``CI`` forced on.
    """
    env = os.environ.copy()
    env["CI"] = "true"
    return env


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


INIT_ARGV: tuple[str, ...] = ("-m", "flinttrade_core.cli", "init", "--provision-master-password")
"""The first-run workspace/master-password provisioning step."""


def provision_workspace(python: str, env: dict[str, str]) -> None:
    """Run the first-run workspace provisioning step.

    The step's chatty stdout is suppressed (it runs before every ``start``,
    ``dev`` and ``setup``), but its stderr is left attached so a genuine failure
    - a missing dependency, an unwritable workspace, a traceback - is visible.
    Silence here reads as a hang, which is exactly the first-run experience this
    guards against.

    Args:
        python: The interpreter resolved by :func:`resolve_python`.
        env: The child environment from :func:`python_env`.

    Raises:
        SystemExit: When provisioning failed, after printing what to re-run.
    """
    code = run([python, *INIT_ARGV], env=env, check=False, quiet=True)
    if code == 0:
        return
    fail(f"Workspace initialisation failed (exit {code}); any error above came from that step.")
    fail("Re-run it on its own to see the full output:")
    fail(f"  {python} " + " ".join(INIT_ARGV))
    raise SystemExit(code)


def cmd_start(_args: list[str]) -> int:
    """Start the FlintTrade backend API.

    Args:
        _args: Unused positional arguments.

    Returns:
        The backend's exit code.
    """
    python = resolve_python()
    env = python_env()
    header("Starting FlintTrade")
    info(f"  Backend: {BACKEND_URL}")
    info("")
    provision_workspace(python, env)
    return run([python, "-m", "flinttrade_core.app"], env=env, check=False)


def cmd_stop(_args: list[str]) -> int:
    """Stop the FlintTrade backend listening on the backend port.

    Args:
        _args: Unused positional arguments.

    Returns:
        0 when the port is free or was freed; 1 when the owner is unknown or the
        process would not exit.
    """
    if not port_is_live(BACKEND_PORT):
        info(f"No FlintTrade backend listening on port {BACKEND_PORT}.")
        return 0

    pid = port_owner_pid(BACKEND_PORT)
    if pid is None:
        warn(f"Port {BACKEND_PORT} is in use but its owning PID is unknown on this host.")
        warn("Stop the FlintTrade backend process manually, then re-run.")
        return 1

    info(f"Stopping FlintTrade backend on port {BACKEND_PORT} (PID {pid})")
    if not terminate_pid(pid):
        fail(f"Could not terminate PID {pid}; stop it manually.")
        return 1

    for _ in range(20):
        if not port_is_live(BACKEND_PORT):
            info(f"Port {BACKEND_PORT} is free.")
            return 0
        time.sleep(0.5)
    warn(f"PID {pid} was signalled but port {BACKEND_PORT} is still in use.")
    return 1


def cmd_restart(args: list[str]) -> int:
    """Stop then start the FlintTrade backend.

    Args:
        args: Forwarded to :func:`cmd_start`.

    Returns:
        The exit code of the failing step, or the backend's exit code.
    """
    code = cmd_stop([])
    if code != 0:
        fail("Restart aborted: the running backend could not be stopped.")
        return code
    return cmd_start(args)


def backend_responds() -> bool:
    """Check whether the backend answers its ping route.

    Returns:
        True when the backend produced any HTTP response.
    """
    try:
        with urllib.request.urlopen(f"{BACKEND_URL}/api/v1/ping", timeout=2):  # noqa: S310 - fixed loopback URL
            return True
    except urllib.error.HTTPError:
        # A 4xx/5xx still proves the backend is serving.
        return True
    except (urllib.error.URLError, OSError):
        return False


def cmd_status(_args: list[str]) -> int:
    """Show backend, port, workspace and version status.

    Args:
        _args: Unused positional arguments.

    Returns:
        Always 0 - status reporting never fails the caller.
    """
    header("FlintTrade Status")

    info("\nFlintTrade backend:")
    if backend_responds():
        info(f"  API: responding on {BACKEND_URL}")
    else:
        info(f"  API: not responding on port {BACKEND_PORT}")

    info("\nOpenAlgo integration (optional):")
    info(f"  API: {'responding' if port_is_live(OPENALGO_PORT) else 'not responding'} on port {OPENALGO_PORT}")

    info("\nPorts:")
    for port in (BACKEND_PORT, OPENALGO_PORT, 5173, 3000):
        info(f"  :{port} - {describe_port(port)}")

    info("\nWorkspace:")
    workspace = workspace_dir()
    if workspace.is_dir():
        info(f"  {workspace} - {format_size(dir_size_bytes(workspace))}")
    else:
        info(f"  {workspace} - does not exist")

    info(f"\nVersion: {read_version()}")
    return 0


def cmd_dev(_args: list[str]) -> int:
    """Run the terminal dev server alongside the FlintTrade backend.

    Args:
        _args: Unused positional arguments.

    Returns:
        The backend's exit code, or 0 when interrupted.
    """
    python = resolve_python()
    env = python_env()

    header("FlintTrade Dev Mode")
    info("  Terminal:  http://127.0.0.1:5173")
    info(f"  Backend:   {BACKEND_URL}")
    info("  OpenAlgo:  optional integration, configure in Settings when needed")
    info("")

    DEV_LOG_DIR.mkdir(parents=True, exist_ok=True)
    provision_workspace(python, env)

    backend_log = (DEV_LOG_DIR / "backend.log").open("wb")
    terminal_log = (DEV_LOG_DIR / "terminal.log").open("wb")
    processes: list[subprocess.Popen[bytes]] = []
    try:
        backend = subprocess.Popen(
            [python, "-m", "flinttrade_core.app"],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=backend_log,
            stderr=subprocess.STDOUT,
        )
        processes.append(backend)

        pnpm = pnpm_argv()
        if pnpm is None:
            warn("No Node toolchain found; the terminal dev server was not started.")
        else:
            # Vite's dev server is interactive, so CI is deliberately not forced here.
            terminal_env = os.environ.copy()
            terminal_env.setdefault("VITE_FLINTTRADE_HOST", BACKEND_URL)
            terminal = subprocess.Popen(
                [*pnpm, "--dir", TERMINAL_PKG, "run", "dev"],
                cwd=str(REPO_ROOT),
                env=terminal_env,
                stdout=terminal_log,
                stderr=subprocess.STDOUT,
            )
            processes.append(terminal)

        info(f"Started backend PID {backend.pid}.")
        info("Logs: .local/dev-logs/backend.log and .local/dev-logs/terminal.log")
        info("Press Ctrl+C to stop.")
        try:
            return backend.wait()
        except KeyboardInterrupt:
            info("\nStopping dev processes...")
            return 0
    finally:
        for proc in processes:
            if proc.poll() is None:
                terminate_pid(proc.pid)
        for handle in (backend_log, terminal_log):
            handle.close()


def cmd_setup(_args: list[str]) -> int:
    """Install Python and Node dependencies and initialise the workspace.

    On POSIX this delegates to ``infra/scripts/setup.sh``. On Windows, where
    that script's toolchain does not exist, an equivalent native sequence runs
    instead.

    Args:
        _args: Unused positional arguments.

    Returns:
        0 on success, non-zero otherwise.
    """
    setup_sh = REPO_ROOT / "infra" / "scripts" / "setup.sh"
    bash = shutil.which("bash")
    if not IS_WINDOWS and bash and setup_sh.is_file():
        return run([bash, str(setup_sh)], check=False)

    header("FlintTrade setup (native)")
    python = resolve_python()

    uv = shutil.which("uv")
    if uv:
        info("Syncing the Python workspace with uv...")
        run([uv, "sync", "--frozen", "--all-packages"])
        info("OK Python workspace synced")
    else:
        info("uv not found; falling back to the hash-verified pip baseline.")
        lock = REPO_ROOT / "requirements.lock"
        if not lock.is_file():
            fail("requirements.lock is missing; install uv from https://docs.astral.sh/uv/ and re-run.")
            return 1
        run([python, "-m", "pip", "install", "--require-hashes", "-r", str(lock)])
        info("OK Root requirements installed")

    pnpm = pnpm_argv()
    if pnpm is None:
        warn("No Node toolchain found; the terminal, site and desktop packages were skipped.")
        warn("Install Node 22.22+ from https://nodejs.org/ and re-run setup.")
    else:
        info("Installing the pnpm workspace...")
        run([*pnpm, "install", "--frozen-lockfile"], env=ci_env())
        info("OK workspace node_modules (pnpm --frozen-lockfile)")

    info("Initialising the workspace...")
    provision_workspace(python, python_env())
    info(f"OK Workspace initialised: {workspace_dir()}")

    info("")
    info("Next steps:")
    info("  1. Run: python scripts/ft.py start")
    info("  2. Open the terminal app and finish setup")
    info("  3. Run: python scripts/ft.py status")
    return 0


def pytest_paths() -> list[str]:
    """Collect the pytest target directories.

    The repository nests packages three levels deep (``packages/<group>/<pkg>``),
    so the glob is expanded here rather than relying on a shell that may not
    exist.

    Returns:
        Repo-relative POSIX paths for every existing test directory.
    """
    paths = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in REPO_ROOT.glob("packages/*/*/tests")
        if path.is_dir()
    )
    if (REPO_ROOT / "tests").is_dir():
        paths.append("tests")
    return paths


def _run_pytest(extra_flags: Sequence[str]) -> int:
    """Run pytest over every discovered test directory.

    Args:
        extra_flags: Flags appended after the target paths.

    Returns:
        pytest's exit code.
    """
    python = resolve_python()
    paths = pytest_paths()
    if not paths:
        fail("No test directories found.")
        return 1
    argv = [python, "-m", "pytest", *paths, *extra_flags, "--tb=short", "--import-mode=importlib"]
    return run(argv, env=python_env(), check=False)


def cmd_test(_args: list[str]) -> int:
    """Run the full pytest suite, then the Rust ticks crate when cargo is present.

    Args:
        _args: Unused positional arguments.

    Returns:
        The first non-zero exit code, or 0.
    """
    code = _run_pytest(["-v"])
    if code != 0:
        return code

    cargo = shutil.which("cargo")
    if cargo is None:
        info("cargo not found - skipping Rust ticks tests")
        return 0
    return run(
        [cargo, "test", "--manifest-path", "packages/core/ticks/Cargo.toml"],
        check=False,
    )


def cmd_test_fast(_args: list[str]) -> int:
    """Run pytest and stop on the first failure.

    Args:
        _args: Unused positional arguments.

    Returns:
        pytest's exit code.
    """
    return _run_pytest(["-x"])


def cmd_lint(_args: list[str]) -> int:
    """Run ruff over ``packages/`` and ``tests/``.

    A missing ruff is reported with install guidance and is not a failure; a
    genuine lint violation is propagated.

    Args:
        _args: Unused positional arguments.

    Returns:
        ruff's exit code, or 0 when ruff is not installed.
    """
    python = resolve_python()
    env = python_env()
    if capture([python, "-m", "ruff", "--version"]) is None:
        info("ruff not installed. Install with: uv sync --frozen --all-packages (or: pip install ruff)")
        return 0
    return run([python, "-m", "ruff", "check", "packages/", "tests/"], env=env, check=False)


def _clean_targets() -> Iterator[Path]:
    """Yield every build-artefact directory that ``clean`` removes."""
    for root, dirnames, _filenames in os.walk(REPO_ROOT):
        root_path = Path(root)
        for name in list(dirnames):
            if name in {"__pycache__", ".pytest_cache", "node_modules"}:
                dirnames.remove(name)
                yield root_path / name
            elif name in PRUNED_DIRS:
                dirnames.remove(name)


def cmd_clean(args: list[str]) -> int:
    """Delete ``__pycache__``, ``.pytest_cache`` and ``node_modules`` trees.

    Uses :func:`shutil.rmtree` rather than ``find -exec rm -rf``, so it behaves
    identically on Windows.

    Args:
        args: Pass ``--yes`` (or ``-y``) to skip the confirmation prompt.

    Returns:
        0 on success or when the user declined; 1 when a tree could not be removed.
    """
    assume_yes = any(arg in {"--yes", "-y"} for arg in args)
    targets = list(_clean_targets())
    if not targets:
        info("Nothing to clean.")
        return 0

    info(f"This will remove {len(targets)} __pycache__, .pytest_cache and node_modules director(y/ies).")
    if not assume_yes:
        if not sys.stdin.isatty():
            fail("Refusing to clean without confirmation; re-run with --yes.")
            return 1
        if input("Continue? [y/N] ").strip().lower() not in {"y", "yes"}:
            info("Cancelled.")
            return 0

    failures = 0
    for target in targets:
        try:
            shutil.rmtree(target)
        except OSError as exc:
            warn(f"could not remove {target}: {exc}")
            failures += 1
    if failures:
        return 1
    info("OK Cleaned")
    return 0


def cmd_version(_args: list[str]) -> int:
    """Print the FlintTrade version.

    Args:
        _args: Unused positional arguments.

    Returns:
        Always 0.
    """
    info(read_version())
    return 0


def _make_targets() -> list[tuple[str, str]]:
    """Parse ``target: ## description`` pairs out of the Makefile.

    This is the Python replacement for the Makefile's ``grep | sort | awk``
    help pipeline, none of which exists on Windows.

    Returns:
        Sorted ``(target, description)`` pairs; empty when the Makefile is absent.
    """
    makefile = REPO_ROOT / "Makefile"
    try:
        text = makefile.read_text(encoding="utf-8")
    except OSError:
        return []
    pattern = re.compile(r"^([a-zA-Z_-]+):.*?## (.*)$", re.MULTILINE)
    return sorted((match.group(1), match.group(2).strip()) for match in pattern.finditer(text))


def cmd_help(_args: list[str]) -> int:
    """Show the command table.

    Args:
        _args: Unused positional arguments.

    Returns:
        Always 0.
    """
    info("FlintTrade - cross-platform task runner")
    info("")
    info("  python scripts/ft.py <command>")
    info("  flinttrade <command>          (after install, via the shim)")
    info("")
    info("Commands (Windows, macOS and Linux):")
    for name, description in COMMANDS.items():
        info(f"  {name:<17} {description}")

    targets = _make_targets()
    if targets:
        info("")
        info("make targets (some are POSIX-only or need Docker - see the Makefile header):")
        for name, description in targets:
            info(f"  {name:<17} {description}")
    return 0


def _pnpm_desktop(script: str) -> int:
    """Run a pnpm script inside the desktop package.

    Args:
        script: The package.json script name.

    Returns:
        The command's exit code.
    """
    pnpm = require_pnpm()
    return run([*pnpm, "--dir", DESKTOP_PKG, "run", script], env=ci_env(), check=False)


def _pnpm_workspace_install() -> int:
    """Install the pnpm workspace with the committed lockfile.

    Returns:
        The command's exit code.
    """
    pnpm = require_pnpm()
    return run([*pnpm, "install", "--frozen-lockfile"], env=ci_env(), check=False)


def cmd_desktop_test(_args: list[str]) -> int:
    """Typecheck and test the Electron shell.

    Args:
        _args: Unused positional arguments.

    Returns:
        The first non-zero exit code, or 0.
    """
    for step in (_pnpm_workspace_install, lambda: _pnpm_desktop("typecheck"), lambda: _pnpm_desktop("test:electron")):
        code = step()
        if code != 0:
            return code
    return 0


def cmd_desktop_build(_args: list[str]) -> int:
    """Verify and bundle the Electron shell.

    Args:
        _args: Unused positional arguments.

    Returns:
        The first non-zero exit code, or 0.
    """
    code = _pnpm_workspace_install()
    if code != 0:
        return code
    return _pnpm_desktop("build")


def desktop_pack_script() -> str:
    """Choose the electron-builder pack script for this host.

    Returns:
        One of ``pack:win``, ``pack:mac``, ``pack:linux:x64`` or ``pack:linux:arm64``.

    Raises:
        SystemExit: When the host OS/architecture is unsupported.
    """
    system = platform.system()
    if system == "Windows":
        return "pack:win"
    if system == "Darwin":
        return "pack:mac"
    machine = platform.machine().lower()
    if system == "Linux":
        if machine in {"x86_64", "amd64"}:
            return "pack:linux:x64"
        if machine in {"arm64", "aarch64"}:
            return "pack:linux:arm64"
    fail(f"Unsupported desktop package target: {system}/{platform.machine()}")
    raise SystemExit(1)


def cmd_desktop_package(args: list[str]) -> int:
    """Package and verify the Electron installer for this OS/arch.

    Args:
        args: Forwarded to :func:`cmd_desktop_build`.

    Returns:
        The first non-zero exit code, or 0.
    """
    code = cmd_desktop_build(args)
    if code != 0:
        return code
    code = _pnpm_desktop(desktop_pack_script())
    if code != 0:
        return code
    info("OK Electron package under packages/apps/desktop/release/electron/")
    return 0


def cmd_desktop_dev(_args: list[str]) -> int:
    """Run the Electron shell against its managed source bootstrap.

    Args:
        _args: Unused positional arguments.

    Returns:
        The first non-zero exit code, or 0.
    """
    code = _pnpm_workspace_install()
    if code != 0:
        return code
    return _pnpm_desktop("dev")


HANDLERS: dict[str, Callable[[list[str]], int]] = {
    "start": cmd_start,
    # `make start-gateway` is a plain alias for `make start`; the runner mirrors
    # it so the Makefile header's command list is dispatchable in full.
    "start-gateway": cmd_start,
    "stop": cmd_stop,
    "restart": cmd_restart,
    "status": cmd_status,
    "dev": cmd_dev,
    "setup": cmd_setup,
    "test": cmd_test,
    "test-fast": cmd_test_fast,
    "lint": cmd_lint,
    "clean": cmd_clean,
    "version": cmd_version,
    "help": cmd_help,
    "desktop-test": cmd_desktop_test,
    "desktop-build": cmd_desktop_build,
    "desktop-package": cmd_desktop_package,
    "desktop-dev": cmd_desktop_dev,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch a subcommand.

    Args:
        argv: Argument vector without the program name; ``sys.argv[1:]`` when omitted.

    Returns:
        The subcommand's exit code; 2 for an unrecognised command.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help", "help"}:
        return cmd_help([])

    name, rest = args[0], args[1:]
    handler = HANDLERS.get(name)
    if handler is None:
        fail(f"Unknown command: {name}")
        info("")
        cmd_help([])
        return 2

    try:
        return handler(rest)
    except KeyboardInterrupt:
        info("\nInterrupted.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
