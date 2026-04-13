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
