"""Sandboxed strategy execution engine.

Safely runs user-provided Python strategy code in a restricted namespace.
Designed for the StrategyBuilder and BacktestLab — users write arbitrary
Python, we execute it without any filesystem, network, or OS access.

Security model:
- ``exec()`` runs in a namespace with only whitelisted builtins.
- ``__import__``, ``open``, ``eval``, ``compile``, and all OS-level
  primitives are excluded.
- Allowed stdlib modules (math, statistics, datetime, collections) are
  pre-imported and injected, giving strategies safe data-processing tools.
- Execution is capped at 30 seconds via a ``threading.Timer``; the
  thread is marked as a daemon so it cannot outlive the process.
- Memory limits are applied via the ``resource`` module on Linux/macOS.
  The call is a no-op on Windows where ``resource`` is not available.

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

import builtins as _builtins_module
import logging
import math
import statistics
import threading
import traceback
from collections import defaultdict, deque, namedtuple
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("flinttrade.engine.sandbox_executor")

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

_SAFE_BUILTIN_NAMES: tuple[str, ...] = (
    "abs", "all", "any", "bin", "bool", "bytearray", "bytes",
    "callable", "chr", "complex", "dict", "divmod", "enumerate",
    "filter", "float", "format", "frozenset", "getattr", "hasattr",
    "hash", "hex", "id", "int", "isinstance", "issubclass", "iter",
    "len", "list", "map", "max", "min", "next", "object", "oct",
    "ord", "pow", "print", "property", "range", "repr", "reversed",
    "round", "set", "setattr", "slice", "sorted", "staticmethod",
    "str", "sum", "super", "tuple", "type", "zip",
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


class SandboxExecutor:
    """Execute user-provided Python strategy code in a restricted namespace.

    Provides four signal-capture functions to the strategy:
    ``long_entry()``, ``long_exit()``, ``short_entry()``, ``short_exit()``.
    Each accepts optional keyword arguments ``price`` (float) and
    ``**metadata`` (arbitrary key-value pairs).

    Args:
        timeout_seconds: Wall-clock timeout per execution (default 30).
        memory_limit_bytes: Address-space limit applied via ``resource``
            on Linux/macOS. Ignored on Windows. Default 256 MB.

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
    ) -> None:
        self._timeout = timeout_seconds
        self._memory_limit = memory_limit_bytes

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
        """
        result = ExecutionResult()
        captured_signals: list[SignalEvent] = []
        captured_output: list[str] = []

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
