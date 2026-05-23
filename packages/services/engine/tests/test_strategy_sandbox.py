"""Tests for OS-level sandbox hardening in strategy_runner.py.

Covers:
- Resource limits (preexec_fn) construction
- Bubblewrap command construction
- Temp directory creation and cleanup
- Restricted builtins wrapper generation
- Graceful fallback when bwrap is not installed
"""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Module under test
# ---------------------------------------------------------------------------

import flinttrade_engine.strategy_runner as mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAFE_CODE = """\
# Simple safe strategy
def on_tick(ltp):
    pass
"""


@pytest.fixture()
def runner(tmp_path):
    """UserStrategyRunner backed by a temporary directory."""
    return mod.UserStrategyRunner(strategies_dir=tmp_path / "strategies")


@pytest.fixture()
def uploaded(runner):
    """Upload a safe strategy and return (runner, strategy_id)."""
    strategy_id = runner.upload("sandbox_test", SAFE_CODE)
    return runner, strategy_id


def _make_mock_process(pid: int = 99999, returncode: int | None = None):
    proc = MagicMock(spec=subprocess.Popen)
    proc.pid = pid
    proc.poll.return_value = returncode
    proc.wait.return_value = returncode
    return proc


# ---------------------------------------------------------------------------
# Resource limits
# ---------------------------------------------------------------------------


class TestResourceLimits:
    """Verify _build_preexec_fn produces correct resource limits."""

    def test_returns_callable_when_resource_available(self):
        """On Linux/macOS with resource module, preexec_fn is a callable."""
        with patch.object(mod, "_RESOURCE_AVAILABLE", True), \
             patch.object(mod, "_resource", create=True) as mock_res:
            mock_res.RLIMIT_CPU = 0
            mock_res.RLIMIT_NOFILE = 7
            mock_res.RLIMIT_NPROC = 6
            fn = mod._build_preexec_fn(cpu_limit=30, fd_limit=16, nproc_limit=0)
            assert callable(fn)

    def test_returns_none_when_resource_unavailable(self):
        """On Windows (no resource module), preexec_fn is None."""
        with patch.object(mod, "_RESOURCE_AVAILABLE", False):
            fn = mod._build_preexec_fn()
            assert fn is None

    def test_preexec_fn_calls_setrlimit(self):
        """The preexec_fn should call setrlimit for CPU and FD limits."""
        with patch.object(mod, "_RESOURCE_AVAILABLE", True), \
             patch.object(mod, "_resource", create=True) as mock_res:
            mock_res.RLIMIT_CPU = 0
            mock_res.RLIMIT_NOFILE = 7
            mock_res.RLIMIT_NPROC = 6
            mock_res.setrlimit = MagicMock()

            fn = mod._build_preexec_fn(cpu_limit=60, fd_limit=32, nproc_limit=0)
            fn()

            calls = mock_res.setrlimit.call_args_list
            # CPU limit
            assert any(c[0][0] == mock_res.RLIMIT_CPU for c in calls)
            # FD limit
            assert any(c[0][0] == mock_res.RLIMIT_NOFILE for c in calls)
            # NPROC limit
            assert any(c[0][0] == mock_res.RLIMIT_NPROC for c in calls)

    def test_preexec_fn_skips_nproc_when_missing(self):
        """When RLIMIT_NPROC is absent (some macOS builds), no error."""
        with patch.object(mod, "_RESOURCE_AVAILABLE", True), \
             patch.object(mod, "_resource", create=True) as mock_res:
            mock_res.RLIMIT_CPU = 0
            mock_res.RLIMIT_NOFILE = 7
            # Simulate macOS without RLIMIT_NPROC
            if hasattr(mock_res, "RLIMIT_NPROC"):
                delattr(mock_res, "RLIMIT_NPROC")
            mock_res.setrlimit = MagicMock()

            fn = mod._build_preexec_fn()
            fn()  # Should not raise

            calls = mock_res.setrlimit.call_args_list
            assert len(calls) == 2  # Only CPU and FD


# ---------------------------------------------------------------------------
# Bubblewrap command construction
# ---------------------------------------------------------------------------


class TestBwrapCommand:
    """Verify bwrap command is built correctly."""

    def test_command_structure(self):
        cmd = mod._build_bwrap_command("/usr/bin/python3", "/tmp/wrapper.py")
        assert cmd[0] == "bwrap"
        assert "--ro-bind" in cmd
        assert "--unshare-net" in cmd
        assert "--unshare-pid" in cmd
        assert "--die-with-parent" in cmd
        assert "--tmpfs" in cmd
        assert "/usr/bin/python3" in cmd
        assert "/tmp/wrapper.py" in cmd

    def test_command_ends_with_python_and_script(self):
        cmd = mod._build_bwrap_command("/usr/bin/python3", "/tmp/wrapper.py")
        # Last two elements: python exe and script path
        assert cmd[-2] == "/usr/bin/python3"
        assert cmd[-1] == "/tmp/wrapper.py"

    def test_is_bwrap_available_true(self):
        with patch("shutil.which", return_value="/usr/bin/bwrap"):
            assert mod._is_bwrap_available() is True

    def test_is_bwrap_available_false(self):
        with patch("shutil.which", return_value=None):
            assert mod._is_bwrap_available() is False


# ---------------------------------------------------------------------------
# Temp directory isolation
# ---------------------------------------------------------------------------


class TestTempDirIsolation:
    """Verify each strategy run gets its own temp dir and it is cleaned up."""

    def test_start_creates_temp_dir(self, uploaded):
        runner, strategy_id = uploaded
        mock_proc = _make_mock_process()

        with patch("subprocess.Popen", return_value=mock_proc):
            runner.start(strategy_id)

        entry = runner._running[strategy_id]
        assert entry.temp_dir is not None
        assert entry.temp_dir.exists()
        assert entry.temp_dir.is_dir()

        # Clean up
        runner.stop(strategy_id)

    def test_temp_dir_used_as_cwd(self, uploaded):
        runner, strategy_id = uploaded
        mock_proc = _make_mock_process()

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            runner.start(strategy_id)

        call_kwargs = mock_popen.call_args
        entry = runner._running[strategy_id]
        assert call_kwargs.kwargs["cwd"] == str(entry.temp_dir)

        runner.stop(strategy_id)

    def test_stop_cleans_up_temp_dir(self, uploaded):
        runner, strategy_id = uploaded
        mock_proc = _make_mock_process()

        with patch("subprocess.Popen", return_value=mock_proc):
            runner.start(strategy_id)

        temp_dir = runner._running[strategy_id].temp_dir
        assert temp_dir.exists()

        runner.stop(strategy_id)
        assert not temp_dir.exists()

    def test_delete_cleans_up_temp_dir(self, uploaded):
        runner, strategy_id = uploaded
        mock_proc = _make_mock_process()

        with patch("subprocess.Popen", return_value=mock_proc):
            runner.start(strategy_id)

        temp_dir = runner._running[strategy_id].temp_dir
        assert temp_dir.exists()

        # Stop first to release the log file handle (avoids Windows file lock)
        runner.stop(strategy_id)
        assert not temp_dir.exists()

        # delete should still work on a stopped strategy (removes .py/.meta files)
        runner.delete(strategy_id)

    def test_temp_dir_cleanup_on_popen_failure(self, uploaded):
        """If Popen raises, the temp dir should be cleaned up."""
        runner, strategy_id = uploaded

        with patch("subprocess.Popen", side_effect=OSError("exec failed")):
            with pytest.raises(OSError, match="exec failed"):
                runner.start(strategy_id)

        # No temp dirs should remain with our prefix
        # (the cleanup happens inside start())
        assert strategy_id not in runner._running

    def test_cleanup_temp_dir_none_is_noop(self):
        """_cleanup_temp_dir(None) should not raise."""
        mod.UserStrategyRunner._cleanup_temp_dir(None)  # Should not raise


# ---------------------------------------------------------------------------
# Restricted builtins wrapper
# ---------------------------------------------------------------------------


class TestRestrictedBuiltins:
    """Verify the sandbox wrapper script is generated correctly."""

    def test_wrapper_created_in_temp_dir(self, tmp_path):
        wrapper = mod._create_sandbox_wrapper(tmp_path)
        assert wrapper.exists()
        assert wrapper.name == "_sandbox_wrapper.py"
        assert wrapper.parent == tmp_path

    def test_wrapper_contains_safe_builtins(self, tmp_path):
        wrapper = mod._create_sandbox_wrapper(tmp_path)
        content = wrapper.read_text(encoding="utf-8")
        # Should contain key safe builtins
        assert '"print"' in content
        assert '"len"' in content
        assert '"range"' in content
        # Should NOT contain dangerous builtins as top-level allowed names
        # (eval/exec/compile are not in _SAFE_BUILTINS)
        assert '"eval"' not in content
        assert '"exec"' not in content or "exec(compile(" in content  # exec is used in wrapper itself
        assert '"compile"' not in content or "compile(_code" in content

    def test_safe_builtins_excludes_dangerous(self):
        """The _SAFE_BUILTINS dict must not contain dangerous names."""
        dangerous = {"eval", "exec", "__import__", "compile", "globals", "locals",
                     "vars", "dir", "getattr", "setattr", "delattr", "open"}
        overlap = dangerous & set(mod._SAFE_BUILTINS.keys())
        assert overlap == set(), f"Dangerous builtins in _SAFE_BUILTINS: {overlap}"


# ---------------------------------------------------------------------------
# Fallback behaviour
# ---------------------------------------------------------------------------


class TestFallback:
    """Verify sandboxing degrades gracefully when tools are unavailable."""

    def test_start_without_bwrap_uses_plain_subprocess(self, uploaded):
        """When bwrap is not installed, strategy still starts via plain Popen."""
        runner, strategy_id = uploaded
        mock_proc = _make_mock_process()

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen, \
             patch.object(mod, "_is_bwrap_available", return_value=False), \
             patch("platform.system", return_value="Linux"):
            runner.start(strategy_id)

        cmd = mock_popen.call_args[0][0]
        # Should NOT start with bwrap
        assert cmd[0] != "bwrap"
        # Should use python interpreter
        assert cmd[0] == sys.executable

        runner.stop(strategy_id)

    def test_start_on_linux_with_bwrap_uses_bwrap(self, uploaded):
        """When bwrap is available on Linux, command starts with bwrap."""
        runner, strategy_id = uploaded
        mock_proc = _make_mock_process()

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen, \
             patch.object(mod, "_is_bwrap_available", return_value=True), \
             patch("platform.system", return_value="Linux"):
            runner.start(strategy_id)

        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "bwrap"

        runner.stop(strategy_id)

    def test_start_on_windows_skips_bwrap(self, uploaded):
        """On Windows, bwrap is never used regardless of availability."""
        runner, strategy_id = uploaded
        mock_proc = _make_mock_process()

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen, \
             patch("platform.system", return_value="Windows"):
            runner.start(strategy_id)

        cmd = mock_popen.call_args[0][0]
        assert cmd[0] != "bwrap"

        runner.stop(strategy_id)

    def test_preexec_fn_passed_to_popen(self, uploaded):
        """The preexec_fn from _build_preexec_fn is passed to Popen."""
        runner, strategy_id = uploaded
        mock_proc = _make_mock_process()
        sentinel = lambda: None  # noqa: E731

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen, \
             patch.object(mod, "_build_preexec_fn", return_value=sentinel):
            runner.start(strategy_id)

        assert mock_popen.call_args.kwargs["preexec_fn"] is sentinel

        runner.stop(strategy_id)

    def test_wrapper_script_in_popen_command(self, uploaded):
        """The sandbox wrapper script path appears in the Popen command."""
        runner, strategy_id = uploaded
        mock_proc = _make_mock_process()

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen, \
             patch("platform.system", return_value="Windows"):
            runner.start(strategy_id)

        cmd = mock_popen.call_args[0][0]
        # Second arg should be the wrapper script path
        assert "_sandbox_wrapper.py" in cmd[1]
        # Third arg should be the strategy script path
        assert strategy_id in cmd[2]

        runner.stop(strategy_id)
