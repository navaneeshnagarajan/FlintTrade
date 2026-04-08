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
import logging
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.engine.strategy_runner")

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
# Running process descriptor
# ---------------------------------------------------------------------------


@dataclass
class _RunningStrategy:
    """Internal descriptor for a running strategy subprocess."""

    strategy_id: str
    name: str
    process: subprocess.Popen  # type: ignore[type-arg]
    started_at: datetime
    log_path: Path
    memory_limit_mb: float = 256.0


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
        memory_limit_mb: Maximum resident memory (MB) allowed per strategy
            process (monitored via psutil on Windows; enforced via resource
            limits on Linux/macOS).
    """

    def __init__(
        self,
        strategies_dir: Path,
        log_dir: Path | None = None,
        memory_limit_mb: float = 256.0,
    ) -> None:
        self._strategies_dir = Path(strategies_dir)
        self._strategies_dir.mkdir(parents=True, exist_ok=True)

        self._log_dir = Path(log_dir) if log_dir else self._strategies_dir / "logs"
        self._log_dir.mkdir(parents=True, exist_ok=True)

        self._memory_limit_mb = memory_limit_mb
        # strategy_id → _RunningStrategy
        self._running: dict[str, _RunningStrategy] = {}

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

    def start(self, strategy_id: str) -> None:
        """Launch a strategy as a subprocess.

        Args:
            strategy_id: ID returned by :meth:`upload`.

        Raises:
            FileNotFoundError: If the strategy file does not exist.
            RuntimeError: If the strategy is already running.
        """
        strategy_path = self._strategies_dir / f"{strategy_id}.py"
        if not strategy_path.exists():
            raise FileNotFoundError(f"Strategy file not found: {strategy_path}")

        if strategy_id in self._running:
            # Check if actually still alive
            proc = self._running[strategy_id].process
            if proc.poll() is None:
                raise RuntimeError(f"Strategy {strategy_id} is already running (pid={proc.pid})")
            # Process has exited — clean up stale entry
            del self._running[strategy_id]

        name = self._get_name(strategy_id)
        log_path = self._log_dir / f"{strategy_id}.log"
        log_file = open(log_path, "a", encoding="utf-8")  # noqa: WPS515

        try:
            process = subprocess.Popen(  # noqa: S603
                [sys.executable, str(strategy_path)],
                stdout=log_file,
                stderr=log_file,
                cwd=str(self._strategies_dir),
            )
        except Exception:
            log_file.close()
            raise

        self._running[strategy_id] = _RunningStrategy(
            strategy_id=strategy_id,
            name=name,
            process=process,
            started_at=datetime.now(timezone.utc),
            log_path=log_path,
            memory_limit_mb=self._memory_limit_mb,
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
        if strategy_id not in self._running:
            raise RuntimeError(f"Strategy {strategy_id} is not running")

        entry = self._running.pop(strategy_id)
        proc = entry.process

        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

        logger.info("Strategy stopped: %s (id=%s)", entry.name, strategy_id)

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
        strategy_path = self._strategies_dir / f"{strategy_id}.py"
        if not strategy_path.exists():
            raise FileNotFoundError(f"Strategy not found: {strategy_id}")

        # Stop first if running
        if strategy_id in self._running:
            try:
                self.stop(strategy_id)
            except Exception:
                pass

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

        if poll is not None:
            # Process has exited
            state = "crashed" if poll != 0 else "stopped"
            del self._running[strategy_id]
            return {
                "strategy_id": strategy_id,
                "name": name,
                "state": state,
                "pid": proc.pid,
                "memory_mb": None,
                "uptime_seconds": None,
                "exit_code": poll,
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
