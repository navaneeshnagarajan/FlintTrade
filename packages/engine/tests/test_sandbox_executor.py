"""Tests for packages.engine.src.sandbox_executor.

Covers:
- SignalEvent construction and serialisation
- ExecutionResult construction and serialisation
- SandboxExecutor.run: success, signals, stdout, error handling, timeout
- Namespace restrictions: blocked builtins, blocked import, blocked open
- Allowed modules: math, statistics, datetime, collections
- Signal functions: all four actions, price and metadata kwargs
- Context injection
- Memory limit application (patched on non-Linux)
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

import packages.engine.src.sandbox_executor as mod
from packages.engine.src.sandbox_executor import (
    ExecutionResult,
    SandboxExecutor,
    SignalEvent,
)


# ---------------------------------------------------------------------------
# SignalEvent
# ---------------------------------------------------------------------------


class TestSignalEvent:
    def test_fields(self):
        sig = SignalEvent(timestamp="2025-01-01T00:00:00Z", action="long_entry", price=100.5)
        assert sig.action == "long_entry"
        assert sig.price == 100.5
        assert sig.metadata == {}

    def test_to_dict_keys(self):
        sig = SignalEvent(timestamp="ts", action="short_exit", price=99.0, metadata={"note": "test"})
        d = sig.to_dict()
        assert d["timestamp"] == "ts"
        assert d["action"] == "short_exit"
        assert d["price"] == 99.0
        assert d["metadata"] == {"note": "test"}


# ---------------------------------------------------------------------------
# ExecutionResult
# ---------------------------------------------------------------------------


class TestExecutionResult:
    def test_default_fields(self):
        r = ExecutionResult()
        assert r.success is False
        assert r.signals == []
        assert r.stdout == ""
        assert r.error == ""
        assert r.timed_out is False

    def test_to_dict(self):
        r = ExecutionResult(success=True, stdout="hi\n")
        d = r.to_dict()
        assert d["success"] is True
        assert d["stdout"] == "hi\n"
        assert d["signals"] == []
        assert d["timed_out"] is False


# ---------------------------------------------------------------------------
# SandboxExecutor — basic execution
# ---------------------------------------------------------------------------


class TestSandboxExecutorBasic:
    def test_empty_code_succeeds(self):
        executor = SandboxExecutor()
        result = executor.run("")
        assert result.success is True
        assert result.signals == []

    def test_whitespace_code_succeeds(self):
        executor = SandboxExecutor()
        result = executor.run("   \n\t  ")
        assert result.success is True

    def test_simple_arithmetic_succeeds(self):
        executor = SandboxExecutor()
        result = executor.run("x = 1 + 2")
        assert result.success is True

    def test_print_is_captured_not_forwarded(self, capsys):
        executor = SandboxExecutor()
        result = executor.run('print("hello sandbox")')
        assert result.success is True
        assert "hello sandbox" in result.stdout
        captured = capsys.readouterr()
        assert "hello sandbox" not in captured.out

    def test_syntax_error_returns_failure(self):
        executor = SandboxExecutor()
        result = executor.run("def broken(:")
        assert result.success is False
        assert result.error != ""

    def test_runtime_error_returns_failure(self):
        executor = SandboxExecutor()
        result = executor.run("1 / 0")
        assert result.success is False
        assert result.error_type == "ZeroDivisionError"

    def test_name_error_on_undefined_var(self):
        executor = SandboxExecutor()
        result = executor.run("x = undefined_variable + 1")
        assert result.success is False
        assert result.error_type == "NameError"


# ---------------------------------------------------------------------------
# SandboxExecutor — signal functions
# ---------------------------------------------------------------------------


class TestSignalCapture:
    def test_long_entry_captured(self):
        executor = SandboxExecutor()
        result = executor.run("long_entry()")
        assert result.success is True
        assert len(result.signals) == 1
        assert result.signals[0].action == "long_entry"

    def test_long_exit_captured(self):
        executor = SandboxExecutor()
        result = executor.run("long_exit(price=50.0)")
        assert len(result.signals) == 1
        assert result.signals[0].action == "long_exit"
        assert result.signals[0].price == 50.0

    def test_short_entry_captured(self):
        executor = SandboxExecutor()
        result = executor.run("short_entry(price=200.0, reason='breakout')")
        assert len(result.signals) == 1
        assert result.signals[0].action == "short_entry"
        assert result.signals[0].metadata["reason"] == "breakout"

    def test_short_exit_captured(self):
        executor = SandboxExecutor()
        result = executor.run("short_exit()")
        assert len(result.signals) == 1
        assert result.signals[0].action == "short_exit"

    def test_multiple_signals_ordered(self):
        code = "long_entry(price=10)\nlong_exit(price=12)\nshort_entry(price=12)"
        executor = SandboxExecutor()
        result = executor.run(code)
        assert len(result.signals) == 3
        actions = [s.action for s in result.signals]
        assert actions == ["long_entry", "long_exit", "short_entry"]

    def test_signal_in_loop(self):
        code = "for i in range(3):\n    long_entry(price=float(i))"
        executor = SandboxExecutor()
        result = executor.run(code)
        assert len(result.signals) == 3
        assert result.signals[2].price == 2.0

    def test_signal_has_utc_timestamp(self):
        executor = SandboxExecutor()
        result = executor.run("long_entry()")
        ts = result.signals[0].timestamp
        assert "T" in ts  # ISO-8601 format

    def test_no_signals_on_condition_false(self):
        code = "if False:\n    long_entry()"
        executor = SandboxExecutor()
        result = executor.run(code)
        assert result.signals == []


# ---------------------------------------------------------------------------
# SandboxExecutor — security restrictions
# ---------------------------------------------------------------------------


class TestSecurityRestrictions:
    def test_import_is_blocked(self):
        executor = SandboxExecutor()
        result = executor.run("import os")
        assert result.success is False

    def test_dunder_import_is_blocked(self):
        executor = SandboxExecutor()
        result = executor.run("__import__('os')")
        assert result.success is False

    def test_open_is_blocked(self):
        executor = SandboxExecutor()
        result = executor.run("open('/etc/passwd')")
        assert result.success is False

    def test_eval_is_blocked(self):
        executor = SandboxExecutor()
        result = executor.run("eval('1+1')")
        # eval is not in safe builtins, so NameError
        assert result.success is False

    def test_exec_is_blocked(self):
        executor = SandboxExecutor()
        # exec itself is not in safe builtins namespace
        result = executor.run("exec('x=1')")
        assert result.success is False

    def test_globals_call_blocked(self):
        executor = SandboxExecutor()
        result = executor.run("globals()")
        assert result.success is False

    def test_locals_call_blocked(self):
        executor = SandboxExecutor()
        result = executor.run("locals()")
        assert result.success is False

    def test_safe_builtins_excludes_dangerous_names(self):
        dangerous = {
            "eval", "exec", "__import__", "compile",
            "globals", "locals", "vars", "open",
        }
        overlap = dangerous & set(mod._SAFE_BUILTINS.keys())
        assert overlap == set(), f"Dangerous builtins exposed: {overlap}"

    def test_os_module_not_accessible(self):
        executor = SandboxExecutor()
        result = executor.run("os.system('echo pwned')")
        assert result.success is False


# ---------------------------------------------------------------------------
# SandboxExecutor — allowed modules
# ---------------------------------------------------------------------------


class TestAllowedModules:
    def test_math_available(self):
        executor = SandboxExecutor()
        result = executor.run("x = math.sqrt(16)")
        assert result.success is True

    def test_statistics_available(self):
        executor = SandboxExecutor()
        result = executor.run("m = statistics.mean([1, 2, 3])")
        assert result.success is True

    def test_datetime_available(self):
        executor = SandboxExecutor()
        result = executor.run("d = datetime.now()")
        assert result.success is True

    def test_defaultdict_available(self):
        executor = SandboxExecutor()
        result = executor.run("dd = defaultdict(int)\ndd['x'] += 1")
        assert result.success is True

    def test_deque_available(self):
        executor = SandboxExecutor()
        result = executor.run("dq = deque([1, 2, 3])\ndq.appendleft(0)")
        assert result.success is True

    def test_numpy_not_available(self):
        """numpy is not in the allowed list."""
        executor = SandboxExecutor()
        result = executor.run("import numpy as np")
        assert result.success is False

    def test_pandas_not_available(self):
        executor = SandboxExecutor()
        result = executor.run("import pandas as pd")
        assert result.success is False


# ---------------------------------------------------------------------------
# SandboxExecutor — context injection
# ---------------------------------------------------------------------------


class TestContextInjection:
    def test_context_variable_accessible(self):
        executor = SandboxExecutor()
        result = executor.run(
            "if close > sma: long_entry(price=close)",
            context={"close": 100.0, "sma": 99.5},
        )
        assert result.success is True
        assert len(result.signals) == 1
        assert result.signals[0].price == 100.0

    def test_context_does_not_override_signal_fns(self):
        executor = SandboxExecutor()
        # Even if context has a 'long_entry' key, the real signal fn must survive
        result = executor.run("long_entry()", context={"long_entry": "hijack"})
        # The signal function should still be the real one
        assert result.success is True
        assert len(result.signals) == 1

    def test_list_in_context(self):
        executor = SandboxExecutor()
        result = executor.run(
            "total = sum(prices)\nlong_entry(price=total)",
            context={"prices": [10.0, 20.0, 30.0]},
        )
        assert result.success is True
        assert result.signals[0].price == 60.0

    def test_empty_context(self):
        executor = SandboxExecutor()
        result = executor.run("x = 1 + 1", context={})
        assert result.success is True


# ---------------------------------------------------------------------------
# SandboxExecutor — timeout
# ---------------------------------------------------------------------------


class TestTimeout:
    def test_timeout_kills_infinite_loop(self):
        executor = SandboxExecutor(timeout_seconds=1)
        code = "while True: pass"
        result = executor.run(code)
        # Should time out (timed_out=True) or return without success
        # On most systems the thread is unkillable but we still get timed_out
        assert result.timed_out is True or not result.success

    def test_fast_code_does_not_timeout(self):
        executor = SandboxExecutor(timeout_seconds=5)
        result = executor.run("x = sum(range(100))")
        assert result.success is True
        assert not result.timed_out


# ---------------------------------------------------------------------------
# SandboxExecutor — memory limit
# ---------------------------------------------------------------------------


class TestMemoryLimit:
    def test_apply_memory_limit_no_op_when_unavailable(self):
        executor = SandboxExecutor()
        with patch.object(mod, "_RESOURCE_AVAILABLE", False):
            # Should not raise
            executor._apply_memory_limit()

    def test_apply_memory_limit_calls_setrlimit_when_available(self):
        executor = SandboxExecutor(memory_limit_bytes=64 * 1024 * 1024)
        mock_res = MagicMock()
        mock_res.RLIMIT_AS = 9
        mock_res.setrlimit = MagicMock()
        with patch.object(mod, "_RESOURCE_AVAILABLE", True), \
             patch.object(mod, "_resource_mod", mock_res):
            executor._apply_memory_limit()
        mock_res.setrlimit.assert_called_once_with(
            9,
            (64 * 1024 * 1024, 64 * 1024 * 1024),
        )

    def test_apply_memory_limit_handles_oserror_gracefully(self):
        executor = SandboxExecutor()
        mock_res = MagicMock()
        mock_res.RLIMIT_AS = 9
        mock_res.setrlimit = MagicMock(side_effect=OSError("not permitted"))
        with patch.object(mod, "_RESOURCE_AVAILABLE", True), \
             patch.object(mod, "_resource_mod", mock_res):
            executor._apply_memory_limit()  # Should not raise


# ---------------------------------------------------------------------------
# SandboxExecutor — subprocess isolation (default path post-2026-05-19)
# ---------------------------------------------------------------------------


class TestSubprocessIsolation:
    """Tests for the subprocess-isolated execution path.

    The default ``SandboxExecutor()`` spawns a child Python interpreter
    that runs the actual ``exec()``. The parent communicates via
    pickle-on-stdin / length-prefixed-JSON-on-stdout, and kills the
    child via SIGKILL/TerminateProcess on timeout. These tests verify
    the boundary contracts that the in-thread fallback CANNOT enforce.
    """

    def test_subprocess_signal_capture_round_trips(self):
        """A signal emitted in the child reaches the parent unchanged."""
        executor = SandboxExecutor()  # use_subprocess=True default
        result = executor.run("long_entry(price=100.5, tag='breakout')")
        assert result.success is True
        assert len(result.signals) == 1
        sig = result.signals[0]
        assert sig.action == "long_entry"
        assert sig.price == 100.5
        assert sig.metadata == {"tag": "breakout"}

    def test_subprocess_print_round_trips(self):
        """Strategy print() captured in the child reaches the parent."""
        executor = SandboxExecutor()
        result = executor.run("print('hello from child', 1 + 2)")
        assert result.success is True
        assert "hello from child 3" in result.stdout

    def test_subprocess_timeout_returns_timed_out(self):
        """Wall-clock timeout sets timed_out=True; the child is killed.

        Critical property: the in-thread fallback can only flag
        ``timed_out`` while the daemon thread keeps running; the
        subprocess path actually terminates the child via
        SIGKILL/TerminateProcess, so the strategy cannot continue
        consuming resources past the deadline.
        """
        executor = SandboxExecutor(timeout_seconds=1)
        import time
        t0 = time.time()
        result = executor.run("while True: pass")
        elapsed = time.time() - t0
        assert result.success is False
        assert result.timed_out is True
        assert result.error_type == "TimeoutError"
        # Within 3s window — kill + reap should be sub-second after the
        # 1s wall-clock cap. Tight bound catches regressions where we
        # accidentally fall back to the in-thread path (which can't
        # actually kill).
        assert elapsed < 3.0, f"timeout took {elapsed:.2f}s — child not killed?"

    def test_subprocess_ast_violation_returns_security_error(self):
        """AST validator runs inside the child — violations propagate back."""
        executor = SandboxExecutor()
        result = executor.run("__import__('os').system('echo pwned')")
        assert result.success is False
        assert result.error_type == "SecurityError"
        assert "Blocked" in result.error or "import" in result.error.lower()

    def test_subprocess_unpicklable_context_returns_clean_error(self):
        """Unpicklable context (e.g. a generator) doesn't crash the parent."""
        executor = SandboxExecutor()
        # Generators are explicitly unpicklable in CPython — pickle raises
        # TypeError: cannot pickle 'generator' object.
        def _gen():
            yield 1
        result = executor.run(
            "x = data",
            context={"data": _gen()},
        )
        assert result.success is False
        assert result.error_type == "ContextSerialisationError"

    def test_in_thread_mode_still_works_when_opted_in(self):
        """`use_subprocess=False` falls back to the legacy in-thread path.

        Kept for trusted callers (in-house templates, hot backtest loops)
        where the spawn overhead matters and the source is reviewed.
        """
        executor = SandboxExecutor(use_subprocess=False)
        result = executor.run("long_entry(price=42.0)")
        assert result.success is True
        assert len(result.signals) == 1
        assert result.signals[0].price == 42.0

    def test_subprocess_runtime_error_returns_clean_failure(self):
        """A normal Python exception in the child returns a structured failure."""
        executor = SandboxExecutor()
        result = executor.run("raise ValueError('boom')")
        assert result.success is False
        assert result.error_type == "ValueError"
        assert "boom" in result.error
        # Not a crash — we got a real exception, not a SandboxCrash.
        assert result.error_type != "SandboxCrash"

    def test_subprocess_signal_with_datetime_metadata_succeeds(self):
        """Datetime in signal metadata gets JSON-coerced, not crashed on.

        Regression for Codex stop-gate finding [P2] — strategies can
        legitimately attach a ``datetime`` to signal metadata via
        ``long_entry(at=datetime.now())`` because ``datetime`` is in
        ``_ALLOWED_MODULES``. The previous child crashed on
        ``json.dumps`` because ``datetime`` isn't JSON-serialisable;
        ``_json_safe`` now coerces to ISO-8601 strings.
        """
        executor = SandboxExecutor()
        result = executor.run(
            "long_entry(price=100.0, at=datetime.now(timezone.utc))"
        )
        assert result.success is True, f"unexpected: {result.error}"
        assert len(result.signals) == 1
        # The datetime should have been coerced to an ISO-8601 string.
        at_val = result.signals[0].metadata.get("at")
        assert isinstance(at_val, str)
        assert "T" in at_val  # ISO-8601 format includes 'T' between date and time

    def test_subprocess_signal_with_set_metadata_succeeds(self):
        """Set in signal metadata gets coerced to a list."""
        executor = SandboxExecutor()
        result = executor.run(
            "long_entry(price=100.0, tags={'breakout', 'momentum'})"
        )
        assert result.success is True
        tags_val = result.signals[0].metadata.get("tags")
        assert isinstance(tags_val, list)
        assert set(tags_val) == {"breakout", "momentum"}

    def test_subprocess_executable_path_works_outside_source_checkout(self):
        """Sandbox child is spawned by absolute path, not dotted module name.

        Regression for Codex stop-gate finding [P1] — using ``python -m
        packages.engine.src._sandbox_child`` only resolves when the repo
        root is on ``sys.path``. After ``pip install flint-engine``, the
        ``packages`` namespace doesn't exist and the default executor
        would silently produce ``SandboxCrash`` for every call. Confirm
        the cmd built by ``_run_in_subprocess`` uses an absolute file
        path that exists on disk.
        """
        import os as _os
        from packages.engine.src import sandbox_executor as se
        # The child path is computed inside _run_in_subprocess from
        # __file__, so we verify the file exists at the expected
        # location relative to the module.
        child_path = _os.path.join(
            _os.path.dirname(_os.path.abspath(se.__file__)),
            "_sandbox_child.py",
        )
        assert _os.path.isfile(child_path), (
            f"Sandbox child entry point missing at {child_path} — would crash "
            "in installed-package layouts."
        )
