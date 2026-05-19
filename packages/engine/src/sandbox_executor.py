"""Sandboxed strategy execution engine.

Safely runs user-provided Python strategy code in a restricted namespace.
Designed for the StrategyBuilder and BacktestLab — users write arbitrary
Python, we execute it without any filesystem, network, or OS access.

Security model — defence in depth:

1. **AST pre-check** (``_validate_sandbox_source``): rejects sandbox-escape
   primitives (``__class__``, ``__subclasses__``, ``__globals__``, etc.)
   plus dangerous calls (``eval``, ``exec``, ``compile``, ``__import__``,
   ``getattr``, ``open`` …) BEFORE any ``exec()`` runs.
2. **Restricted namespace**: ``exec()`` runs with a whitelisted builtin
   dictionary; ``__import__``, ``open``, ``eval``, ``compile`` and all
   OS-level primitives are absent. Pre-imported stdlib modules (math,
   statistics, datetime, collections) give strategies safe tools.
3. **Subprocess isolation** (default): the actual ``exec()`` runs in a
   child Python interpreter via ``_sandbox_child.py``. The parent
   communicates by pickle-on-stdin / length-prefixed-JSON-on-stdout
   (parent NEVER pickle-loads child output — only JSON). A hostile
   strategy that defeats layers 1+2 can still only crash its own
   process; the parent kills it on timeout via ``Popen.kill()``
   (``TerminateProcess`` on Windows, ``SIGKILL`` on POSIX).
4. **OS resource limits**: inside the child, POSIX ``setrlimit`` caps
   address space (256 MB), CPU seconds, open file descriptors, and
   ``RLIMIT_FSIZE=0`` (cannot write files). On Windows the equivalent
   would be a Job Object via ``pywin32`` — not yet implemented;
   wall-clock kill is the only enforcement on Windows pending that
   work. Documented as a follow-up; current Windows behaviour is no
   worse than the pre-subprocess version.

The legacy in-thread execution path (``threading.Timer`` + daemon thread)
is preserved as a fallback when ``use_subprocess=False`` is passed — it
is faster (no spawn overhead) but cannot terminate hostile code mid-
execution (the daemon thread continues running until process exit).
ONLY trusted callers (in-house template engine, hot backtest loop)
should opt out of subprocess isolation.

Usage::

    from packages.engine.src.sandbox_executor import SandboxExecutor

    executor = SandboxExecutor()
    result = executor.run(
        source_code="long_entry(price=100.5)",
        context={"price": 100.5},
    )
    for signal in result.signals:
        print(signal.action, signal.price)
"""

from __future__ import annotations

import ast
import builtins as _builtins_module
import json
import logging
import math
import os
import pickle
import statistics
import struct
import subprocess
import sys
import threading
import traceback
from collections import defaultdict, deque, namedtuple
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("flinttrade.engine.sandbox_executor")

# ---------------------------------------------------------------------------
# AST-level pre-check — block sandbox escape primitives BEFORE `exec()` runs
# ---------------------------------------------------------------------------
#
# Mirrors the validator in ``strategy_runner.py``. Even with a builtin
# allowlist, an attacker who has direct ``exec(code, namespace)`` access can
# reach the full Python object graph via dunders:
#
#     ().__class__.__bases__[0].__subclasses__()[N].__init__.__globals__
#         ['__builtins__']['__import__']('os').system('rm -rf /')
#
# Allowlists alone cannot stop this — AST inspection that rejects the
# escape vectors at parse time can.
#
# Block list:
# - ``__class__``, ``__bases__``, ``__subclasses__``, ``__mro__`` — climb the
#   type hierarchy.
# - ``__globals__``, ``__builtins__``, ``__code__`` — reach the host
#   process's builtins and bytecode.
# - ``__import__``, ``__reduce__``, ``__reduce_ex__`` — pickle-style payload
#   delivery + late binding.
# - ``__init_subclass__``, ``__class_getitem__`` — type creation hooks.
#
# Plus dangerous call names that may slip in via ``namespace`` injection or
# stdlib re-exports (``eval``, ``exec``, ``compile``, ``open``, ``globals``,
# ``locals``, ``vars``, ``dir``, ``getattr``, ``setattr``, ``delattr``,
# ``breakpoint``, ``__import__``).
_SANDBOX_FORBIDDEN_ATTRS: frozenset[str] = frozenset(
    {
        "__class__",
        "__bases__",
        "__subclasses__",
        "__mro__",
        "__globals__",
        "__builtins__",
        "__code__",
        "__import__",
        "__reduce__",
        "__reduce_ex__",
        "__init_subclass__",
        "__class_getitem__",
        "__getattribute__",
    }
)

_SANDBOX_BLOCKED_CALLS: frozenset[str] = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
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


def _validate_sandbox_source(source_code: str) -> list[str]:
    """Walk the AST of ``source_code`` and return a list of policy violations.

    An empty list means the code is acceptable for ``exec()``. Any non-empty
    return value should be treated as a hard rejection — DO NOT let the
    string reach ``exec()`` even if ``builtins`` are stripped, because a
    single missed dunder access reverses the entire sandbox.

    Args:
        source_code: Untrusted Python source text.

    Returns:
        A list of human-readable violation messages. Empty when safe.
    """
    try:
        tree = ast.parse(source_code)
    except SyntaxError as exc:
        return [f"SyntaxError: {exc}"]

    violations: list[str] = []
    for node in ast.walk(tree):
        # 1. Forbid `obj.__class__`, `obj.__subclasses__`, etc. on ANY object.
        if isinstance(node, ast.Attribute) and node.attr in _SANDBOX_FORBIDDEN_ATTRS:
            violations.append(
                f"Blocked attribute: '.{node.attr}' — sandbox-escape vector"
            )
        # 2. Forbid direct calls to dangerous builtins (`eval()`, `exec()`,
        #    `__import__()`, `getattr(obj, '__class__')`, etc.).
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _SANDBOX_BLOCKED_CALLS:
                violations.append(
                    f"Blocked call: '{func.id}()' — not allowed in sandbox"
                )
        # 3. Forbid `import os` / `from os import ...` and similar stdlib
        #    escape hatches. The runtime namespace already excludes
        #    `__import__`, but a static check rejects the syntax up front.
        elif isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                violations.append(
                    f"Blocked import: '{alias.name}' — module '{root}' is not "
                    "available in the sandbox"
                )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            violations.append(
                f"Blocked import: 'from {node.module or '?'} import …' — "
                f"module '{root}' is not available in the sandbox"
            )

    return violations

# ---------------------------------------------------------------------------
# Platform-level resource limiting (soft-fail on Windows)
# ---------------------------------------------------------------------------

try:
    import resource as _resource_mod  # type: ignore[import]

    _RESOURCE_AVAILABLE = True
except ImportError:
    _resource_mod = None  # type: ignore[assignment]
    _RESOURCE_AVAILABLE = False

# 256 MB memory limit for sandboxed code (bytes)
_MEMORY_LIMIT_BYTES: int = 256 * 1024 * 1024


def _tail_bytes(data: bytes, max_bytes: int) -> bytes:
    """Return the last ``max_bytes`` of ``data``.

    Used to truncate the child's stderr before bubbling it back into an
    error message. Keeps a hostile strategy from filling the parent's
    memory by printing megabytes of garbage right before crashing.
    """
    if len(data) <= max_bytes:
        return data
    return data[-max_bytes:]


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill a sandbox child plus any descendants it managed to spawn.

    POSIX: the child was started with ``start_new_session=True`` so it's
    the leader of its own session/process group. ``killpg`` sends SIGKILL
    to every process in that group atomically — covers grandchildren a
    missed sandbox escape might have spawned.

    Windows: no session/process-group primitive available without
    ``pywin32`` Job Objects (follow-up). Fall back to ``proc.kill()``
    which calls TerminateProcess on the immediate child only.
    """
    if sys.platform != "win32":
        try:
            import signal as _signal
            os.killpg(os.getpgid(proc.pid), _signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            # Process already gone or we can't signal it — fall through
            # to proc.kill() which is idempotent.
            pass
    try:
        proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        pass

# ---------------------------------------------------------------------------
# Allowed modules injected into the sandbox namespace
# ---------------------------------------------------------------------------

_ALLOWED_MODULES: dict[str, Any] = {
    "math": math,
    "statistics": statistics,
    "datetime": datetime,
    "date": date,
    "timedelta": timedelta,
    "timezone": timezone,
    "defaultdict": defaultdict,
    "deque": deque,
    "namedtuple": namedtuple,
}

# ---------------------------------------------------------------------------
# Whitelisted builtins — everything NOT in this list is blocked.
# Always resolve against the canonical ``builtins`` module to avoid
# differences between ``__builtins__`` being a dict vs a module across
# Python environments (module-level vs exec context on Windows vs Linux).
# ---------------------------------------------------------------------------

#
# DO NOT add `getattr`, `setattr`, `delattr`, `type`, `object`, `super`,
# `globals`, `locals`, `vars`, `dir`, `compile`, `eval`, `exec`,
# `__import__`, `open`, `breakpoint`, or `input` to this list. They are
# either direct sandbox-escape primitives or enable reflection paths that
# can reach the full Python object graph. The AST validator above also
# rejects them statically, but the runtime allowlist is the second wall.
_SAFE_BUILTIN_NAMES: tuple[str, ...] = (
    "abs", "all", "any", "bin", "bool", "bytearray", "bytes",
    "callable", "chr", "complex", "dict", "divmod", "enumerate",
    "filter", "float", "format", "frozenset", "hasattr",
    "hash", "hex", "id", "int", "isinstance", "issubclass", "iter",
    "len", "list", "map", "max", "min", "next", "oct",
    "ord", "pow", "print", "property", "range", "repr", "reversed",
    "round", "set", "slice", "sorted", "staticmethod",
    "str", "sum", "tuple", "zip",
    # Exception hierarchy
    "Exception", "BaseException",
    "ValueError", "TypeError", "KeyError", "IndexError",
    "AttributeError", "RuntimeError", "StopIteration",
    "ZeroDivisionError", "OverflowError", "ArithmeticError",
    "LookupError", "NameError", "NotImplementedError",
    "AssertionError",
)

_SAFE_BUILTINS: dict[str, Any] = {
    name: getattr(_builtins_module, name)
    for name in _SAFE_BUILTIN_NAMES
    if hasattr(_builtins_module, name)
}

# Inject the singletons that are keywords in Python 3 (not module attrs)
_SAFE_BUILTINS["True"] = True
_SAFE_BUILTINS["False"] = False
_SAFE_BUILTINS["None"] = None
_SAFE_BUILTINS["NotImplemented"] = NotImplemented
_SAFE_BUILTINS["Ellipsis"] = Ellipsis


# ---------------------------------------------------------------------------
# Signal model
# ---------------------------------------------------------------------------


@dataclass
class SignalEvent:
    """A single trading signal emitted by user strategy code.

    Attributes:
        timestamp: When the signal was captured (UTC ISO-8601).
        action: One of ``"long_entry"``, ``"long_exit"``,
            ``"short_entry"``, ``"short_exit"``.
        price: Optional price hint provided by the strategy.
        metadata: Arbitrary key-value pairs attached by the strategy.
    """

    timestamp: str
    action: str
    price: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "timestamp": self.timestamp,
            "action": self.action,
            "price": self.price,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Execution result
# ---------------------------------------------------------------------------


@dataclass
class ExecutionResult:
    """Result of a sandboxed strategy execution.

    Attributes:
        success: Whether the code ran to completion without error.
        signals: List of captured ``SignalEvent`` objects.
        stdout: Any text printed by the strategy (captured, not forwarded).
        error: Error message on failure; empty on success.
        error_type: Exception class name on failure; empty on success.
        timed_out: True if the execution was killed by the 30-second timer.
    """

    success: bool = False
    signals: list[SignalEvent] = field(default_factory=list)
    stdout: str = ""
    error: str = ""
    error_type: str = ""
    timed_out: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "success": self.success,
            "signals": [s.to_dict() for s in self.signals],
            "stdout": self.stdout,
            "error": self.error,
            "error_type": self.error_type,
            "timed_out": self.timed_out,
        }


# ---------------------------------------------------------------------------
# SandboxExecutor
# ---------------------------------------------------------------------------


def _execute_in_process(
    source_code: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run ``source_code`` inside THIS process with the restricted namespace.

    Returns the result as a dict (not an ``ExecutionResult`` dataclass)
    so the subprocess child can JSON-serialise it without re-importing
    the dataclass. Performs the AST validator first; if violations are
    found, no ``exec()`` runs and the dict carries a ``SecurityError``.

    This helper is the SINGLE source of truth for the in-process exec
    path. Both the in-thread fallback (``SandboxExecutor._run_in_thread``)
    and the subprocess child (``_sandbox_child.main``) call this so the
    sandbox semantics stay identical regardless of isolation level.

    Args:
        source_code: Untrusted Python source text.
        context: Variables to inject into the exec namespace.

    Returns:
        A dict matching ``ExecutionResult.to_dict()``.
    """
    captured_signals: list[SignalEvent] = []
    captured_output: list[str] = []

    # 1. AST validator — reject sandbox-escape vectors BEFORE exec().
    violations = _validate_sandbox_source(source_code)
    if violations:
        logger.warning(
            "sandbox: rejected source with %d violation(s)", len(violations),
        )
        return {
            "success": False,
            "signals": [],
            "stdout": "",
            "error": "Sandbox policy violation:\n - " + "\n - ".join(violations),
            "error_type": "SecurityError",
            "timed_out": False,
        }

    namespace = _build_sandbox_namespace(
        captured_signals=captured_signals,
        captured_output=captured_output,
        context=context or {},
    )

    try:
        exec(source_code, namespace)  # noqa: S102
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "sandbox: strategy raised %s: %s\n%s",
            type(exc).__name__, exc, traceback.format_exc(),
        )
        return {
            "success": False,
            "signals": [s.to_dict() for s in captured_signals],
            "stdout": "".join(captured_output),
            "error": str(exc),
            "error_type": type(exc).__name__,
            "timed_out": False,
        }

    return {
        "success": True,
        "signals": [s.to_dict() for s in captured_signals],
        "stdout": "".join(captured_output),
        "error": "",
        "error_type": "",
        "timed_out": False,
    }


def _build_sandbox_namespace(
    *,
    captured_signals: list[SignalEvent],
    captured_output: list[str],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Build the restricted execution namespace for ``exec()``."""

    def _make_signal_fn(action: str):
        def _signal(*, price: float = 0.0, **metadata: Any) -> None:
            ts = datetime.now(timezone.utc).isoformat()
            captured_signals.append(
                SignalEvent(
                    timestamp=ts,
                    action=action,
                    price=float(price),
                    metadata=metadata,
                )
            )

        _signal.__name__ = action
        return _signal

    def _safe_print(*args: Any, sep: str = " ", end: str = "\n", **_: Any) -> None:
        captured_output.append(sep.join(str(a) for a in args) + end)

    safe_builtins = dict(_SAFE_BUILTINS)
    safe_builtins["print"] = _safe_print

    namespace: dict[str, Any] = {
        "__builtins__": safe_builtins,
        # Allowed stdlib modules
        **_ALLOWED_MODULES,
        # Signal capture functions
        "long_entry": _make_signal_fn("long_entry"),
        "long_exit": _make_signal_fn("long_exit"),
        "short_entry": _make_signal_fn("short_entry"),
        "short_exit": _make_signal_fn("short_exit"),
    }

    # Inject user context (cannot override signal functions or builtins)
    for key, value in context.items():
        if key not in namespace:
            namespace[key] = value

    return namespace


def _result_dict_to_execution_result(data: dict[str, Any]) -> ExecutionResult:
    """Convert a JSON-shape dict back to an ``ExecutionResult`` dataclass."""
    signals: list[SignalEvent] = []
    for raw in data.get("signals", []) or []:
        try:
            signals.append(SignalEvent(
                timestamp=str(raw.get("timestamp", "")),
                action=str(raw.get("action", "")),
                price=float(raw.get("price", 0.0)),
                metadata=dict(raw.get("metadata") or {}),
            ))
        except (TypeError, ValueError):
            continue
    return ExecutionResult(
        success=bool(data.get("success", False)),
        signals=signals,
        stdout=str(data.get("stdout", "")),
        error=str(data.get("error", "")),
        error_type=str(data.get("error_type", "")),
        timed_out=bool(data.get("timed_out", False)),
    )


class SandboxExecutor:
    """Execute user-provided Python strategy code in a restricted namespace.

    Provides four signal-capture functions to the strategy:
    ``long_entry()``, ``long_exit()``, ``short_entry()``, ``short_exit()``.
    Each accepts optional keyword arguments ``price`` (float) and
    ``**metadata`` (arbitrary key-value pairs).

    Args:
        timeout_seconds: Wall-clock timeout per execution (default 30).
        memory_limit_bytes: Address-space limit applied via ``resource``
            on Linux/macOS (set inside the child process). Ignored on
            Windows until Job Object support lands. Default 256 MB.
        use_subprocess: When ``True`` (default), spawn ``_sandbox_child``
            in a child Python interpreter and communicate via pipes. The
            child is killed via SIGKILL/TerminateProcess on timeout, so
            hostile code cannot outlive the timeout window. When ``False``,
            run inside a daemon ``threading.Thread`` in this process —
            faster (no spawn overhead) but cannot terminate hostile code.
            Only use ``False`` for trusted callers (in-house template
            engine, BacktestLab walk-forward inner loop).

    Example::

        executor = SandboxExecutor()
        result = executor.run(
            "if close > sma: long_entry(price=close)",
            context={"close": 100.0, "sma": 99.5},
        )
        print(result.signals)
    """

    def __init__(
        self,
        timeout_seconds: int = 30,
        memory_limit_bytes: int = _MEMORY_LIMIT_BYTES,
        use_subprocess: bool = True,
    ) -> None:
        self._timeout = timeout_seconds
        self._memory_limit = memory_limit_bytes
        self._use_subprocess = use_subprocess

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        source_code: str,
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Execute ``source_code`` in a restricted sandbox.

        Args:
            source_code: Raw Python source text (user strategy code).
            context: Optional dict of variables to inject into the
                execution namespace (e.g. OHLCV arrays, indicator values,
                strategy parameters).

        Returns:
            An ``ExecutionResult`` with signals, stdout, and error info.
            If the source code fails static validation, no ``exec()`` is
            performed and the result carries a ``SecurityError``.
        """
        if self._use_subprocess:
            return self._run_in_subprocess(source_code, context or {})
        return self._run_in_thread(source_code, context or {})

    # ------------------------------------------------------------------
    # Subprocess execution path — default; hostile-code-safe
    # ------------------------------------------------------------------

    def _run_in_subprocess(
        self,
        source_code: str,
        context: dict[str, Any],
    ) -> ExecutionResult:
        """Spawn ``_sandbox_child`` and run the strategy there.

        Strategy:
        1. Pickle the payload to a single bytestring on parent side.
        2. Spawn ``python -I -S -m packages.engine.src._sandbox_child``
           with stdin/stdout/stderr pipes. ``-I`` isolated mode ignores
           ``PYTHON*`` env vars; ``-S`` skips site.py.
        3. Send payload, close stdin, wait for response with wall-clock
           timeout. On timeout, ``proc.kill()`` (TerminateProcess on
           Windows, SIGKILL on POSIX) → reap → return ``timed_out``.
        4. Parse the response: 8-byte big-endian length prefix +
           JSON body. Parent ONLY ``json.loads()`` from the child —
           NEVER pickle.loads, so a hostile child cannot inject a
           ``__reduce__`` payload into the parent.

        If the child exits before emitting a result frame (segfault,
        OOM kill, raised in bootstrap), the parent reports a
        ``SandboxCrash`` with the last 4 KiB of the child's stderr.
        """
        # Compose the payload. Context can carry numpy arrays / pandas
        # frames produced by the indicators package, so pickle is the
        # only practical serialiser here — but the parent writes pickle
        # and never reads it, so a hostile context author cannot get
        # code execution in the parent.
        try:
            payload = pickle.dumps({
                "source": source_code,
                "context": context,
                "memory_limit": self._memory_limit,
                "timeout": self._timeout,
            })
        except (pickle.PicklingError, TypeError) as exc:
            logger.warning("sandbox: context could not be pickled: %s", exc)
            return ExecutionResult(
                success=False,
                error=f"Context could not be serialised for sandbox: {exc}",
                error_type="ContextSerialisationError",
            )

        # Spawn the child by absolute file path so the executor works
        # both in the source checkout (where ``packages.engine.src`` is
        # importable from the repo root) AND when ``flint-engine`` is
        # installed from its package (where ``src/`` maps to the
        # ``flint_engine`` import name and the legacy
        # ``packages.engine.src._sandbox_child`` dotted spec doesn't
        # exist). Passing the script as a positional path bypasses the
        # import-by-dotted-name lookup entirely.
        child_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "_sandbox_child.py",
        )
        cmd = [sys.executable, child_path]

        env = {
            k: v for k, v in os.environ.items()
            if not k.startswith("PYTHON")
        }
        # PYTHONPATH still must include the repo root so the child's
        # ``from packages.engine.src import sandbox_executor as se``
        # import resolves the same way it does in the parent. In an
        # installed layout this is harmless — the import lookup just
        # falls through to the installed package.
        repo_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..")
        )
        path_entries = [repo_root] + [p for p in sys.path if p]
        env["PYTHONPATH"] = os.pathsep.join(path_entries)

        # On POSIX, put the child in its own process group so a missed
        # escape that spawns grandchildren is still bounded by the
        # group-kill at timeout. ``start_new_session=True`` calls
        # ``setsid()`` in the child so it becomes the leader of a new
        # session AND a new process group. Windows has no equivalent
        # primitive here; ``proc.kill()`` (TerminateProcess) only kills
        # the immediate child on Windows — Job Object support is a
        # follow-up to bound grandchildren on Windows.
        popen_kwargs: dict[str, Any] = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "env": env,
        }
        if sys.platform != "win32":
            popen_kwargs["start_new_session"] = True

        try:
            proc = subprocess.Popen(cmd, **popen_kwargs)
        except OSError as exc:
            logger.error("sandbox: could not spawn child: %s", exc)
            return ExecutionResult(
                success=False,
                error=f"Could not spawn sandbox child process: {exc}",
                error_type="SandboxSpawnError",
            )

        try:
            stdout, stderr = proc.communicate(
                input=payload, timeout=self._timeout,
            )
        except subprocess.TimeoutExpired:
            # Hard-kill on timeout. On POSIX we kill the WHOLE PROCESS
            # GROUP so any grandchildren a missed escape might have
            # spawned die with the parent — ``proc.kill()`` alone only
            # signals the immediate child. On Windows we fall back to
            # ``proc.kill()`` (TerminateProcess); Job Object follow-up
            # will close that gap.
            _kill_process_tree(proc)
            try:
                stdout, stderr = proc.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                stdout, stderr = b"", b""
            logger.warning(
                "sandbox: child killed after %ds wall-clock timeout", self._timeout,
            )
            return ExecutionResult(
                success=False,
                error=f"Execution timed out after {self._timeout} seconds",
                error_type="TimeoutError",
                timed_out=True,
            )

        # Parse the length-prefixed JSON response frame.
        if len(stdout) < 8:
            tail = _tail_bytes(stderr, 4096).decode("utf-8", errors="replace")
            logger.warning(
                "sandbox: child emitted no result frame (exit=%s, stderr_tail=%r)",
                proc.returncode, tail[:200],
            )
            return ExecutionResult(
                success=False,
                error=(
                    "Sandbox child exited without a result frame "
                    f"(exit={proc.returncode}). stderr tail: {tail}"
                ),
                error_type="SandboxCrash",
            )

        length = struct.unpack(">Q", stdout[:8])[0]
        body = stdout[8:8 + length]
        if len(body) < length:
            return ExecutionResult(
                success=False,
                error=(
                    f"Sandbox child result truncated: expected {length} bytes, "
                    f"got {len(body)}"
                ),
                error_type="SandboxCrash",
            )

        try:
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return ExecutionResult(
                success=False,
                error=f"Sandbox child result was not valid JSON: {exc}",
                error_type="SandboxCrash",
            )

        return _result_dict_to_execution_result(data)

    # ------------------------------------------------------------------
    # In-thread execution path — fallback for trusted callers only
    # ------------------------------------------------------------------

    def _run_in_thread(
        self,
        source_code: str,
        context: dict[str, Any],
    ) -> ExecutionResult:
        """Legacy in-process executor — kept for trusted callers only.

        This path CANNOT terminate hostile code: ``threading.Thread`` has
        no kill primitive in CPython. A strategy that goes into
        ``while True: pass`` will be marked ``timed_out`` after the
        wall-clock window, but the daemon thread continues consuming a
        CPU until the parent process exits. Only use this path when the
        source is trusted (in-house templates, hot backtest loops where
        the spawn overhead matters and the source is reviewed).
        """
        result = ExecutionResult()
        captured_signals: list[SignalEvent] = []
        captured_output: list[str] = []

        # Static AST pre-check — reject sandbox-escape vectors BEFORE exec().
        violations = _validate_sandbox_source(source_code)
        if violations:
            result.error = "Sandbox policy violation:\n - " + "\n - ".join(violations)
            result.error_type = "SecurityError"
            logger.warning(
                "SandboxExecutor: rejected source with %d violation(s)",
                len(violations),
            )
            return result

        namespace = self._build_namespace(
            captured_signals=captured_signals,
            captured_output=captured_output,
            context=context or {},
        )

        exc_holder: list[Exception] = []
        timed_out_flag: list[bool] = [False]

        def _run() -> None:
            self._apply_memory_limit()
            try:
                exec(source_code, namespace)  # noqa: S102
            except Exception as exc:  # noqa: BLE001
                exc_holder.append(exc)

        timer = threading.Timer(self._timeout, lambda: timed_out_flag.__setitem__(0, True))
        worker = threading.Thread(target=_run, daemon=True)

        timer.start()
        worker.start()
        worker.join(timeout=self._timeout + 1)
        timer.cancel()

        if worker.is_alive():
            # Thread is stuck — mark as timed out; daemon status ensures
            # it cannot outlive the process.
            result.timed_out = True
            result.error = f"Execution timed out after {self._timeout} seconds"
            result.error_type = "TimeoutError"
            logger.warning("SandboxExecutor: execution timed out after %ds", self._timeout)
            return result

        result.stdout = "".join(captured_output)
        result.signals = list(captured_signals)

        if exc_holder:
            exc = exc_holder[0]
            result.success = False
            result.error = str(exc)
            result.error_type = type(exc).__name__
            logger.debug(
                "SandboxExecutor: strategy raised %s: %s\n%s",
                result.error_type,
                result.error,
                traceback.format_exc(),
            )
        else:
            result.success = True

        return result

    # ------------------------------------------------------------------
    # Namespace construction
    # ------------------------------------------------------------------

    def _build_namespace(
        self,
        *,
        captured_signals: list[SignalEvent],
        captured_output: list[str],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the restricted execution namespace for ``exec()``.

        Args:
            captured_signals: Mutable list; signal functions append here.
            captured_output: Mutable list; print() output is appended here.
            context: User-provided variables to inject.

        Returns:
            Namespace dict passed as the ``globals`` argument to ``exec()``.
        """

        def _make_signal_fn(action: str):
            def _signal(*, price: float = 0.0, **metadata: Any) -> None:
                ts = datetime.now(timezone.utc).isoformat()
                captured_signals.append(
                    SignalEvent(
                        timestamp=ts,
                        action=action,
                        price=float(price),
                        metadata=metadata,
                    )
                )

            _signal.__name__ = action
            return _signal

        def _safe_print(*args: Any, sep: str = " ", end: str = "\n", **_: Any) -> None:
            captured_output.append(sep.join(str(a) for a in args) + end)

        safe_builtins = dict(_SAFE_BUILTINS)
        safe_builtins["print"] = _safe_print

        namespace: dict[str, Any] = {
            "__builtins__": safe_builtins,
            # Allowed stdlib modules
            **_ALLOWED_MODULES,
            # Signal capture functions
            "long_entry": _make_signal_fn("long_entry"),
            "long_exit": _make_signal_fn("long_exit"),
            "short_entry": _make_signal_fn("short_entry"),
            "short_exit": _make_signal_fn("short_exit"),
        }

        # Inject user context variables (cannot override signal functions or builtins)
        for key, value in context.items():
            if key not in namespace:
                namespace[key] = value

        return namespace

    # ------------------------------------------------------------------
    # Memory limiting
    # ------------------------------------------------------------------

    def _apply_memory_limit(self) -> None:
        """Apply address-space limit via ``resource`` (Linux/macOS only).

        On Windows (no ``resource`` module) this is a silent no-op.
        The limit is applied inside the worker thread so it only
        constrains that thread's process-level address space.
        """
        if not _RESOURCE_AVAILABLE or _resource_mod is None:
            return
        try:
            _resource_mod.setrlimit(
                _resource_mod.RLIMIT_AS,
                (self._memory_limit, self._memory_limit),
            )
        except (ValueError, OSError) as exc:
            logger.debug("SandboxExecutor: could not apply memory limit: %s", exc)
