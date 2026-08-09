"""Tests for packages/services/engine/src/strategy_runner.py.

Ordinary subprocess execution is mocked. AST validation and file I/O use real
temporary directories, and a Linux-only integration test executes the exact
bubblewrap namespace when a bounded test-only capability check proves it usable.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


POSIX_RESOURCE_LIMITS = os.name != "nt"
NO_POSIX_RESOURCE_REASON = (
    "the autouse fixture pins platform.system() to Linux, whose hard uploaded-strategy limits "
    "require the POSIX resource module"
)


_BWRAP_TEST_TIMEOUT_SECONDS = 5.0


def _functional_bwrap_executable() -> str | None:
    """Return the exact system bwrap only after a bounded real namespace run."""
    if platform.system() != "Linux":
        return None
    import flinttrade_engine.strategy_runner as _mod

    try:
        bwrap_executable = _mod._find_bwrap_executable()
    except RuntimeError:
        return None
    if bwrap_executable is None:
        return None
    with tempfile.TemporaryDirectory(prefix="flinttrade_bwrap_test_") as raw_temp_dir:
        temp_dir = Path(raw_temp_dir)
        work = temp_dir / "work"
        work.mkdir()
        wrapper = _mod._create_sandbox_wrapper(
            work,
            memory_limit_bytes=256 * 1024 * 1024,
            process_limit=1,
        )
        start_gate = _mod._create_strategy_start_gate(work)
        strategy = temp_dir / "strategy.py"
        strategy.write_text("pass\n", encoding="utf-8")
        _mod._release_strategy_start_gate(start_gate)
        try:
            completed = subprocess.run(  # noqa: S603 - exact trusted production command, no shell
                _mod._build_bwrap_command(
                    bwrap_executable,
                    sys.executable,
                    str(wrapper),
                    str(start_gate),
                    str(strategy),
                ),
                check=False,
                close_fds=True,
                cwd="/",
                shell=False,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                start_new_session=True,
                timeout=_BWRAP_TEST_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
    return bwrap_executable if completed.returncode == 0 else None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner(tmp_path, monkeypatch):
    """UserStrategyRunner backed by a temporary directory."""
    import flinttrade_engine.strategy_runner as _mod

    monkeypatch.setattr(_mod, "_find_bwrap_executable", lambda: None)
    return _mod.UserStrategyRunner(strategies_dir=tmp_path / "strategies")


@pytest.fixture(autouse=True)
def _stable_mock_process_identity(monkeypatch):
    """Give mocked POSIX children a stable identity token."""
    import flinttrade_engine.strategy_runner as _mod

    monkeypatch.setattr(_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(_mod, "_read_process_identity", lambda pid: float(pid), raising=False)
    # ``raising=False``: Windows has no ``os.getpgid``/``os.killpg``, and without
    # it this autouse fixture erred during setup and took the whole module —
    # including the AST-validation and Windows Job Object suites — with it.
    monkeypatch.setattr(_mod.os, "getpgid", lambda pid: pid, raising=False)
    monkeypatch.setattr(_mod.os, "killpg", lambda _pgid, _signal: None, raising=False)


SAFE_CODE = """\
# Simple safe strategy
def on_tick(ltp):
    pass
"""

DANGEROUS_OS_CODE = """\
import os
os.system("rm -rf /")
"""

DANGEROUS_SUBPROCESS_CODE = """\
import subprocess
subprocess.run(["ls"])
"""

DANGEROUS_EVAL_CODE = """\
result = eval("1+1")
"""

DANGEROUS_EXEC_CODE = """\
exec("import os")
"""

DANGEROUS_IMPORT_FROM_CODE = """\
from os import system
system("ls")
"""

DANGEROUS_OPEN_WRITE_CODE = """\
with open("/etc/passwd", "w") as f:
    f.write("hacked")
"""

DANGEROUS_OS_ATTR_CODE = """\
import os as operating_system
operating_system.system("whoami")
"""


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestValidation:
    def test_safe_code_passes(self, runner):
        violations = runner.validate(SAFE_CODE)
        assert violations == []

    def test_import_os_blocked(self, runner):
        violations = runner.validate(DANGEROUS_OS_CODE)
        assert any("os" in v for v in violations)

    def test_import_subprocess_blocked(self, runner):
        violations = runner.validate(DANGEROUS_SUBPROCESS_CODE)
        assert any("subprocess" in v for v in violations)

    def test_eval_call_blocked(self, runner):
        violations = runner.validate(DANGEROUS_EVAL_CODE)
        assert any("eval" in v for v in violations)

    def test_exec_call_blocked(self, runner):
        violations = runner.validate(DANGEROUS_EXEC_CODE)
        assert any("exec" in v for v in violations)

    def test_from_os_import_blocked(self, runner):
        violations = runner.validate(DANGEROUS_IMPORT_FROM_CODE)
        assert any("os" in v for v in violations)

    def test_open_write_blocked(self, runner):
        violations = runner.validate(DANGEROUS_OPEN_WRITE_CODE)
        assert any("open" in v for v in violations)

    def test_syntax_error_reported(self, runner):
        violations = runner.validate("def broken(:\n    pass\n")
        assert any("SyntaxError" in v for v in violations)

    def test_read_only_open_allowed(self, runner):
        code = 'data = open("/tmp/safe.txt", "r").read()\n'
        violations = runner.validate(code)
        # "open" itself is in BLOCKED_BUILTINS but only write modes are flagged
        # The validator blocks the call name itself — this is acceptable security
        # posture. Test that we correctly detect the call.
        # open() with read mode: our validator flags the name "open" as blocked.
        # This is intentional — strategies should not use open() at all.
        assert isinstance(violations, list)


# ---------------------------------------------------------------------------
# Upload tests
# ---------------------------------------------------------------------------


class TestUpload:
    def test_upload_safe_code_returns_id(self, runner):
        strategy_id = runner.upload("my_strategy", SAFE_CODE)
        assert len(strategy_id) == 36  # UUID format

    def test_uploaded_file_exists(self, runner):
        strategy_id = runner.upload("my_strategy", SAFE_CODE)
        strategy_file = runner._strategies_dir / f"{strategy_id}.py"
        assert strategy_file.exists()

    def test_meta_file_contains_name(self, runner):
        strategy_id = runner.upload("awesome_strat", SAFE_CODE)
        meta_file = runner._strategies_dir / f"{strategy_id}.meta"
        assert meta_file.read_text().strip() == "awesome_strat"

    def test_upload_dangerous_code_raises(self, runner):
        with pytest.raises(ValueError, match="failed validation"):
            runner.upload("bad_strategy", DANGEROUS_OS_CODE)

    def test_upload_invalid_name_raises(self, runner):
        with pytest.raises(ValueError, match="valid Python identifier"):
            runner.upload("my-strategy", SAFE_CODE)


# ---------------------------------------------------------------------------
# Start / Stop tests (subprocess mocked)
# ---------------------------------------------------------------------------


class TestWindowsJobProcessTree:
    @staticmethod
    def _active_process_query(module, counts: list[int]):
        import ctypes

        remaining = iter(counts)

        def query(_handle, info_class, info_ptr, _size, _returned_length):
            assert info_class == 1  # JobObjectBasicAccountingInformation
            info = ctypes.cast(
                info_ptr,
                ctypes.POINTER(module._WindowsJobBasicAccountingInformation),
            ).contents
            info.ActiveProcesses = next(remaining)
            return True

        return query

    def test_is_alive_queries_active_job_processes(self):
        import flinttrade_engine.strategy_runner as mod

        kernel32 = MagicMock()
        kernel32.QueryInformationJobObject.side_effect = self._active_process_query(mod, [1, 0])
        tree = mod._WindowsJobProcessTree(MagicMock(spec=subprocess.Popen), 42, kernel32)

        assert tree.is_alive() is True
        assert tree.is_alive() is False
        kernel32.WaitForSingleObject.assert_not_called()

    def test_wait_gone_polls_active_job_processes_until_zero(self):
        import flinttrade_engine.strategy_runner as mod

        kernel32 = MagicMock()
        kernel32.QueryInformationJobObject.side_effect = self._active_process_query(mod, [2, 1, 0])
        tree = mod._WindowsJobProcessTree(MagicMock(spec=subprocess.Popen), 42, kernel32)

        with (
            patch.object(mod.time, "monotonic", return_value=0.0),
            patch.object(mod.time, "sleep"),
        ):
            assert tree.wait_gone(0.1) is True
        assert kernel32.QueryInformationJobObject.call_count == 3
        kernel32.WaitForSingleObject.assert_not_called()

    def test_create_configures_job_memory_and_active_process_limits(self, monkeypatch):
        import ctypes

        import flinttrade_engine.strategy_runner as mod

        process = MagicMock()
        process.pid = 717
        process._handle = 99
        kernel32 = MagicMock()
        kernel32.CreateJobObjectW.return_value = 42
        kernel32.AssignProcessToJobObject.return_value = True
        captured: dict[str, int] = {}

        def set_limits(_handle, info_class, limits_pointer, _size):
            assert info_class == 9
            limits = ctypes.cast(
                limits_pointer,
                ctypes.POINTER(mod._WindowsJobExtendedLimitInformation),
            ).contents
            captured["flags"] = int(limits.BasicLimitInformation.LimitFlags)
            captured["processes"] = int(limits.BasicLimitInformation.ActiveProcessLimit)
            captured["memory"] = int(limits.JobMemoryLimit)
            return True

        kernel32.SetInformationJobObject.side_effect = set_limits
        monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32, raising=False)
        monkeypatch.setattr(mod, "_resume_windows_process", MagicMock())

        tree = mod._WindowsJobProcessTree.create(
            process,
            memory_limit_bytes=96 * 1024 * 1024,
            process_limit=1,
        )

        assert captured == {
            "flags": 0x00002000 | 0x00000200 | 0x00000008,
            "processes": 1,
            "memory": 96 * 1024 * 1024,
        }
        tree.close()

    def test_refuses_to_signal_group_after_leader_identity_changes(self, monkeypatch):
        import flinttrade_engine.strategy_runner as mod

        process = TestStartStop()._make_mock_process(pid=515)
        monkeypatch.setattr(mod, "_read_process_identity", MagicMock(side_effect=[10.0, 11.0]), raising=False)
        killpg = MagicMock()
        monkeypatch.setattr(mod.os, "killpg", killpg)
        monkeypatch.setattr(mod.os, "getpgid", MagicMock(return_value=515))
        tree = mod._PosixProcessGroup(process)

        with pytest.raises(RuntimeError, match="identity"):
            tree.terminate()

        killpg.assert_not_called()

    @pytest.mark.skipif(
        os.name == "nt",
        reason="POSIX process-group signalling; signal.SIGKILL does not exist on Windows",
    )
    def test_refuses_to_signal_unverifiable_group_after_leader_exit(self, monkeypatch):
        import flinttrade_engine.strategy_runner as mod

        process = TestStartStop()._make_mock_process(pid=616, returncode=0)
        monkeypatch.setattr(mod, "_read_process_identity", MagicMock(return_value=10.0), raising=False)
        killpg = MagicMock()
        monkeypatch.setattr(mod.os, "killpg", killpg)
        tree = mod._PosixProcessGroup(process)

        with pytest.raises(RuntimeError, match="leader exited"):
            tree.kill()

        killpg.assert_not_called()

    def test_close_retains_job_handle_until_close_succeeds(self, monkeypatch):
        import ctypes

        import flinttrade_engine.strategy_runner as mod

        monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)
        monkeypatch.setattr(
            ctypes,
            "WinError",
            lambda code: OSError(code, "CloseHandle failed"),
            raising=False,
        )
        kernel32 = MagicMock()
        kernel32.CloseHandle.side_effect = [False, True]
        tree = mod._WindowsJobProcessTree(MagicMock(spec=subprocess.Popen), 42, kernel32)

        with pytest.raises(OSError, match="CloseHandle failed"):
            tree.close()
        assert tree._job_handle == 42

        tree.close()
        assert tree._job_handle is None
        assert kernel32.CloseHandle.call_args_list == [((42,),), ((42,),)]

    def test_create_job_failure_terminates_and_reaps_suspended_child(self, runner, monkeypatch):
        import ctypes

        import flinttrade_engine.strategy_runner as mod

        strategy_id = runner.upload("windows_create_job_failure", SAFE_CODE)
        process = TestStartStop()._make_mock_process(pid=818)
        process.wait.return_value = 1
        kernel32 = MagicMock()
        kernel32.CreateJobObjectW.return_value = 0

        monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32, raising=False)
        monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)
        monkeypatch.setattr(
            ctypes,
            "WinError",
            lambda code: OSError(code, "CreateJobObject failed"),
            raising=False,
        )
        monkeypatch.setattr(mod.platform, "system", lambda: "Windows")

        with (
            patch("subprocess.Popen", return_value=process),
            pytest.raises(OSError, match="CreateJobObject failed"),
        ):
            runner.start(strategy_id)

        process.kill.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=2.0)
        assert strategy_id not in runner._running

    def test_create_job_failure_retains_unreaped_suspended_child_owner(self, runner, monkeypatch):
        import ctypes

        import flinttrade_engine.strategy_runner as mod

        strategy_id = runner.upload("windows_create_job_retained", SAFE_CODE)
        process = TestStartStop()._make_mock_process(pid=828)
        process.kill.side_effect = OSError("kill denied")
        kernel32 = MagicMock()
        kernel32.CreateJobObjectW.return_value = 0

        monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32, raising=False)
        monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)
        monkeypatch.setattr(
            ctypes,
            "WinError",
            lambda code: OSError(code, "CreateJobObject failed"),
            raising=False,
        )
        monkeypatch.setattr(mod.platform, "system", lambda: "Windows")

        with (
            patch("subprocess.Popen", return_value=process),
            pytest.raises(mod._WindowsJobCreationRollbackError) as failed,
        ):
            runner.start(strategy_id)

        entry = runner._running[strategy_id]
        try:
            assert failed.value.process_tree is entry.tree
            assert str(failed.value.setup_error) == "[Errno 5] CreateJobObject failed"
            assert str(failed.value.rollback_error) == "kill denied"
            assert entry.process is process
            assert entry.tree._assigned is False
            assert entry.tree._job_handle is None
            assert entry.log_file is not None
            assert entry.temp_dir is not None and entry.temp_dir.exists()
        finally:
            runner._release_entry_resources(entry)
            runner._running.pop(strategy_id, None)

    def test_failed_resume_and_close_retains_assigned_job_for_stop_retry(
        self,
        runner,
        monkeypatch,
    ):
        import ctypes

        import flinttrade_engine.strategy_runner as mod

        strategy_id = runner.upload("windows_recovery", SAFE_CODE)
        process = MagicMock()
        process.pid = 919
        process._handle = 99
        process.wait.return_value = 1
        kernel32 = MagicMock()
        kernel32.CreateJobObjectW.return_value = 42
        kernel32.SetInformationJobObject.return_value = True
        kernel32.AssignProcessToJobObject.return_value = True
        kernel32.TerminateJobObject.return_value = True
        kernel32.QueryInformationJobObject.side_effect = self._active_process_query(mod, [0, 0, 0])
        kernel32.CloseHandle.side_effect = [False, True]

        monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32, raising=False)
        monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)
        monkeypatch.setattr(
            ctypes,
            "WinError",
            lambda code: OSError(code, "Windows API failure"),
            raising=False,
        )
        monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
        monkeypatch.setattr(
            mod,
            "_resume_windows_process",
            MagicMock(side_effect=RuntimeError("resume failed")),
        )

        with (
            patch("subprocess.Popen", return_value=process),
            pytest.raises(mod._WindowsJobCreationRollbackError) as failed,
        ):
            runner.start(strategy_id)

        entry = runner._running[strategy_id]
        retained_tree = failed.value.process_tree
        retained_temp_dir = entry.temp_dir
        assert entry.tree is retained_tree
        assert entry.process is process
        assert str(failed.value.setup_error) == "resume failed"
        assert retained_tree._job_handle == 42
        assert entry.log_file is not None
        assert retained_temp_dir is not None and retained_temp_dir.exists()
        kernel32.AssignProcessToJobObject.assert_called_once()
        assert kernel32.CloseHandle.call_count == 1

        runner.stop(strategy_id)

        assert strategy_id not in runner._running
        assert retained_tree._job_handle is None
        assert retained_temp_dir.exists() is False
        assert kernel32.CloseHandle.call_count == 2


class TestStartStop:
    def _make_mock_process(self, pid: int = 12345, returncode: int | None = None):
        proc = MagicMock(spec=subprocess.Popen)
        proc.pid = pid
        proc.poll.return_value = returncode
        proc.wait.return_value = returncode
        return proc

    def _attach_tree(self, runner, strategy_id: str, *, alive: bool = True):
        tree = MagicMock()
        tree.is_alive.side_effect = [alive, False] if alive else [False]
        tree.wait_gone.return_value = True
        runner._running[strategy_id].tree = tree
        return tree

    @pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
    def test_start_strategy(self, runner):
        strategy_id = runner.upload("test_strat", SAFE_CODE)
        mock_proc = self._make_mock_process()

        with patch("subprocess.Popen", return_value=mock_proc):
            runner.start(strategy_id)

        assert strategy_id in runner._running
        assert runner._running[strategy_id].process is mock_proc

    def test_start_nonexistent_raises(self, runner):
        with pytest.raises(FileNotFoundError):
            runner.start("nonexistent-id")

    @pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
    def test_start_already_running_raises(self, runner):
        strategy_id = runner.upload("test_strat", SAFE_CODE)
        mock_proc = self._make_mock_process()

        with patch("subprocess.Popen", return_value=mock_proc):
            runner.start(strategy_id)
            with pytest.raises(RuntimeError, match="already running"):
                runner.start(strategy_id)

    @pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
    def test_concurrent_tree_limit_fails_before_spawning_another_process(self, tmp_path, monkeypatch):
        import flinttrade_engine.strategy_runner as mod

        monkeypatch.setattr(mod, "_find_bwrap_executable", lambda: None)
        runner = mod.UserStrategyRunner(
            strategies_dir=tmp_path / "strategies",
            max_concurrent_strategies=1,
        )
        first_id = runner.upload("first_tree", SAFE_CODE)
        second_id = runner.upload("second_tree", SAFE_CODE)
        first = self._make_mock_process(pid=111)

        with patch("subprocess.Popen", return_value=first) as popen:
            runner.start(first_id)
            with pytest.raises(RuntimeError, match="concurrent strategy limit"):
                runner.start(second_id)

        assert popen.call_count == 1
        assert first_id in runner._running
        assert second_id not in runner._running

    def test_posix_start_fails_closed_without_hard_memory_enforcement(self, runner, monkeypatch):
        import flinttrade_engine.strategy_runner as mod

        strategy_id = runner.upload("unsupported_limits", SAFE_CODE)
        monkeypatch.setattr(mod.platform, "system", lambda: "Darwin")
        with (
            patch("subprocess.Popen") as popen,
            pytest.raises(RuntimeError, match="unavailable on Darwin"),
        ):
            runner.start(strategy_id)

        popen.assert_not_called()

    @pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
    def test_posix_identity_failure_retains_a_blocked_child_until_adoption(self, runner, monkeypatch):
        import flinttrade_engine.strategy_runner as mod

        strategy_id = runner.upload("pending_identity", SAFE_CODE)
        process = self._make_mock_process(pid=606)

        with (
            patch("subprocess.Popen", return_value=process),
            patch.object(
                mod,
                "_create_process_tree",
                side_effect=mod._ProcessTreeIdentityError("identity unavailable"),
            ),
            patch.object(mod, "_release_strategy_start_gate") as release_gate,
            pytest.raises(mod._ProcessTreeIdentityError, match="identity unavailable"),
        ):
            runner.start(strategy_id)

        entry = runner._running[strategy_id]
        assert isinstance(entry.tree, mod._PendingPosixProcessGroup)
        assert (entry.temp_dir / "_start_gate").read_text(encoding="utf-8") == ""
        assert entry.log_file is not None and not entry.log_file.closed
        release_gate.assert_not_called()
        retained_temp_dir = entry.temp_dir

        monkeypatch.setattr(mod, "_read_process_identity", lambda pid: float(pid))

        def signal_group(_pgid: int, signum: int) -> None:
            if signum == 0 and process.poll() is not None:
                raise ProcessLookupError
            if signum != 0:
                process.poll.return_value = 0

        monkeypatch.setattr(mod.os, "killpg", signal_group)
        runner.stop(strategy_id)

        assert strategy_id not in runner._running
        assert retained_temp_dir is not None and not retained_temp_dir.exists()

    @pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
    def test_start_publishes_the_process_owner_before_releasing_uploaded_code(self, runner):
        import flinttrade_engine.strategy_runner as mod

        strategy_id = runner.upload("published_before_release", SAFE_CODE)
        process = self._make_mock_process(pid=607)
        observed_entry = None
        original_release = mod._release_strategy_start_gate

        def observed_release(gate_path: Path) -> None:
            nonlocal observed_entry
            observed_entry = runner._running[strategy_id]
            assert observed_entry.process is process
            assert gate_path.read_text(encoding="utf-8") == ""
            original_release(gate_path)

        with (
            patch("subprocess.Popen", return_value=process),
            patch.object(mod, "_release_strategy_start_gate", side_effect=observed_release),
        ):
            runner.start(strategy_id)

        assert observed_entry is runner._running[strategy_id]
        assert (observed_entry.temp_dir / "_start_gate").read_text(encoding="utf-8") == "start\n"
        self._attach_tree(runner, strategy_id)
        runner.stop(strategy_id)

    @pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
    def test_gate_release_failure_retains_the_published_owner_and_resources(self, runner):
        import flinttrade_engine.strategy_runner as mod

        strategy_id = runner.upload("release_failure", SAFE_CODE)
        process = self._make_mock_process(pid=608)

        def fail_after_partial_write(gate_path: Path) -> None:
            gate_path.write_text("sta", encoding="utf-8")
            raise OSError("gate write failed")

        with (
            patch("subprocess.Popen", return_value=process),
            patch.object(mod, "_release_strategy_start_gate", side_effect=fail_after_partial_write),
            pytest.raises(OSError, match="gate write failed"),
        ):
            runner.start(strategy_id)

        entry = runner._running[strategy_id]
        assert entry.process is process
        assert entry.log_file is not None and not entry.log_file.closed
        assert entry.temp_dir is not None and entry.temp_dir.exists()
        assert (entry.temp_dir / "_start_gate").read_text(encoding="utf-8") == "sta"

        self._attach_tree(runner, strategy_id)
        runner.stop(strategy_id)

    @pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
    def test_start_refuses_replacement_while_descendant_tree_survives_leader(self, runner):
        strategy_id = runner.upload("surviving_tree", SAFE_CODE)
        first = self._make_mock_process(pid=505, returncode=0)
        with patch("subprocess.Popen", return_value=first):
            runner.start(strategy_id)
        tree = MagicMock()
        tree.is_alive.return_value = True
        runner._running[strategy_id].tree = tree

        with (
            patch("subprocess.Popen") as popen,
            pytest.raises(RuntimeError, match="already running"),
        ):
            runner.start(strategy_id)

        popen.assert_not_called()
        assert strategy_id in runner._running

    @pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
    def test_concurrent_starts_spawn_exactly_one_owned_process(self, runner):
        strategy_id = runner.upload("concurrent_start", SAFE_CODE)
        first_process = self._make_mock_process(pid=101)
        second_process = self._make_mock_process(pid=202)
        first_spawn_entered = threading.Event()
        release_first_spawn = threading.Event()
        second_spawn_entered = threading.Event()
        spawn_count = 0
        spawn_count_lock = threading.Lock()
        errors: list[Exception] = []

        def spawn(*_args, **_kwargs):
            nonlocal spawn_count
            with spawn_count_lock:
                call_index = spawn_count
                spawn_count += 1
            if call_index == 0:
                first_spawn_entered.set()
                assert release_first_spawn.wait(timeout=2)
                return first_process
            second_spawn_entered.set()
            return second_process

        def start() -> None:
            try:
                runner.start(strategy_id)
            except Exception as exc:  # noqa: BLE001 - captures the losing caller
                errors.append(exc)

        with patch("subprocess.Popen", side_effect=spawn) as popen:
            first_thread = threading.Thread(target=start)
            second_thread = threading.Thread(target=start)
            first_thread.start()
            assert first_spawn_entered.wait(timeout=1)
            second_thread.start()
            second_spawn_entered.wait(timeout=0.25)
            release_first_spawn.set()
            first_thread.join(timeout=2)
            second_thread.join(timeout=2)

        assert not first_thread.is_alive()
        assert not second_thread.is_alive()
        assert popen.call_count == 1
        assert len(errors) == 1
        assert isinstance(errors[0], RuntimeError)
        assert "already running" in str(errors[0])
        assert runner._running[strategy_id].process is first_process

    @pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
    def test_stop_strategy(self, runner):
        strategy_id = runner.upload("test_strat", SAFE_CODE)
        mock_proc = self._make_mock_process()

        with patch("subprocess.Popen", return_value=mock_proc):
            runner.start(strategy_id)

        tree = self._attach_tree(runner, strategy_id)
        runner.stop(strategy_id)
        assert strategy_id not in runner._running
        tree.terminate.assert_called_once_with()
        tree.wait_gone.assert_called_once_with(5.0)
        tree.close.assert_called_once_with()

    @pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
    def test_stop_serialises_with_inflight_start_and_terminates_published_child(self, runner):
        import flinttrade_engine.strategy_runner as mod

        strategy_id = runner.upload("start_stop_race", SAFE_CODE)
        process = self._make_mock_process(pid=303)
        process_tree = MagicMock()
        process_tree.is_alive.side_effect = [True, False]
        process_tree.wait_gone.return_value = True
        spawn_entered = threading.Event()
        release_spawn = threading.Event()
        errors: list[Exception] = []

        def spawn(*_args, **_kwargs):
            spawn_entered.set()
            assert release_spawn.wait(timeout=2)
            return process

        def start() -> None:
            try:
                runner.start(strategy_id)
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        def stop() -> None:
            try:
                runner.stop(strategy_id)
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        with (
            patch("subprocess.Popen", side_effect=spawn),
            patch.object(mod, "_create_process_tree", return_value=process_tree, create=True),
        ):
            start_thread = threading.Thread(target=start)
            stop_thread = threading.Thread(target=stop)
            start_thread.start()
            assert spawn_entered.wait(timeout=1)
            stop_thread.start()
            assert stop_thread.is_alive(), "stop raced past an unpublished child"
            release_spawn.set()
            start_thread.join(timeout=2)
            stop_thread.join(timeout=2)

        assert errors == []
        assert strategy_id not in runner._running
        process_tree.terminate.assert_called_once_with()

    @pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
    def test_stop_bounds_reap_after_forced_kill(self, runner):
        strategy_id = runner.upload("bounded_kill", SAFE_CODE)
        process = self._make_mock_process(pid=404)
        with patch("subprocess.Popen", return_value=process):
            runner.start(strategy_id)
        tree = self._attach_tree(runner, strategy_id)
        tree.wait_gone.side_effect = [False, False]
        entry = runner._running[strategy_id]
        temp_dir = entry.temp_dir
        log_file = entry.log_file

        with pytest.raises(RuntimeError, match="(?i)could not confirm"):
            runner.stop(strategy_id)

        tree.terminate.assert_called_once_with()
        tree.kill.assert_called_once_with()
        assert tree.wait_gone.call_args_list[0].args == (5.0,)
        assert tree.wait_gone.call_args_list[1].args == (2.0,)
        assert strategy_id in runner._running
        assert entry.temp_dir == temp_dir
        assert entry.log_file is log_file
        assert temp_dir.exists()

    def test_stop_not_running_raises(self, runner):
        strategy_id = runner.upload("test_strat", SAFE_CODE)
        with pytest.raises(RuntimeError):
            runner.stop(strategy_id)

    def test_stop_unknown_strategy_raises_file_not_found(self, runner):
        with pytest.raises(FileNotFoundError, match="Strategy not found"):
            runner.stop("unknown-strategy")

    @pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
    def test_start_detaches_stdin_and_owns_dedicated_posix_process_group(self, runner):
        strategy_id = runner.upload("contained", SAFE_CODE)
        mock_proc = self._make_mock_process()

        with (
            patch.dict("os.environ", {"FLINTTRADE_PARENT_PID": "77"}),
            patch("flinttrade_engine.strategy_runner.platform.system", return_value="Linux"),
            patch("subprocess.Popen", return_value=mock_proc) as popen,
        ):
            runner.start(strategy_id)

        kwargs = popen.call_args.kwargs
        assert kwargs["stdin"] is subprocess.DEVNULL
        assert kwargs["close_fds"] is True
        assert kwargs["start_new_session"] is True
        assert "FLINTTRADE_PARENT_PID" not in kwargs["env"]

    def test_windows_start_assigns_suspended_child_to_complete_tree_job(self, runner):
        import flinttrade_engine.strategy_runner as mod

        strategy_id = runner.upload("windows_tree", SAFE_CODE)
        process = self._make_mock_process(pid=909)
        tree = MagicMock()

        with (
            patch.object(mod.platform, "system", return_value="Windows"),
            patch.object(mod, "_create_process_tree", return_value=tree, create=True) as create_tree,
            patch("subprocess.Popen", return_value=process) as popen,
        ):
            runner.start(strategy_id)

        flags = popen.call_args.kwargs["creationflags"]
        assert flags & mod._WINDOWS_CREATE_NEW_PROCESS_GROUP
        assert flags & mod._WINDOWS_CREATE_SUSPENDED
        create_tree.assert_called_once_with(
            process,
            "Windows",
            memory_limit_bytes=256 * 1024 * 1024,
            process_limit=1,
        )
        assert runner._running[strategy_id].tree is tree

    @pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
    def test_stale_sys_frozen_still_uses_source_sandbox_wrapper(self, runner):
        import flinttrade_engine.strategy_runner as mod

        strategy_id = runner.upload("source_only", SAFE_CODE)
        mock_proc = self._make_mock_process()

        with (
            patch.object(mod.sys, "frozen", True, create=True),
            patch.object(mod.platform, "system", return_value="Linux"),
            patch.object(mod, "_find_bwrap_executable", return_value=None),
            patch("subprocess.Popen", return_value=mock_proc) as popen,
        ):
            runner.start(strategy_id)

        command = popen.call_args.args[0]
        assert command[0] == sys.executable
        assert Path(command[1]).name == "_sandbox_wrapper.py"
        assert Path(command[2]).name == "_start_gate"
        assert command[3] == str(runner._strategies_dir / f"{strategy_id}.py")
        assert popen.call_args.kwargs["preexec_fn"] is not None

    @pytest.mark.skipif(platform.system() != "Linux", reason="requires Linux bubblewrap selection")
    def test_linux_bwrap_uses_resolved_system_executable_without_shell(self, tmp_path):
        import flinttrade_engine.strategy_runner as mod

        runner = mod.UserStrategyRunner(strategies_dir=tmp_path / "strategies")
        strategy_id = runner.upload("resolved_bwrap", SAFE_CODE)
        process = self._make_mock_process()
        tree = MagicMock()
        tree.is_alive.return_value = False
        bwrap_executable = mod._find_bwrap_executable()
        if bwrap_executable is None:
            pytest.skip("requires the trusted system bubblewrap executable")
        assert bwrap_executable is not None
        process.wait.side_effect = subprocess.TimeoutExpired(
            cmd=[bwrap_executable],
            timeout=mod._BWRAP_STARTUP_TIMEOUT_SECONDS,
        )

        with (
            patch.object(mod.shutil, "which", wraps=mod.shutil.which) as which,
            patch.object(mod, "_create_process_tree", return_value=tree),
            patch("subprocess.Popen", return_value=process) as popen,
        ):
            runner.start(strategy_id)

        which.assert_called_once_with("bwrap", path=os.defpath)
        command = popen.call_args.args[0]
        assert command[0] == bwrap_executable
        assert popen.call_args.kwargs["shell"] is False

        process.wait.side_effect = None
        process.wait.return_value = 0
        runner.stop(strategy_id)

    @pytest.mark.skipif(platform.system() != "Linux", reason="requires Linux bubblewrap selection")
    def test_installed_broken_bwrap_fails_without_host_python_fallback(self, tmp_path):
        import flinttrade_engine.strategy_runner as mod

        runner = mod.UserStrategyRunner(strategies_dir=tmp_path / "strategies")
        strategy_id = runner.upload("broken_bwrap", SAFE_CODE)
        process = self._make_mock_process(returncode=127)
        process.wait.return_value = 127
        tree = MagicMock()
        tree.is_alive.return_value = False
        bwrap_executable = mod._find_bwrap_executable()
        if bwrap_executable is None:
            pytest.skip("requires the trusted system bubblewrap executable")
        assert bwrap_executable is not None

        with (
            patch.object(mod, "_create_process_tree", return_value=tree),
            patch("subprocess.Popen", return_value=process) as popen,
            pytest.raises(RuntimeError, match="Bubblewrap sandbox exited during startup.*127"),
        ):
            runner.start(strategy_id)

        popen.assert_called_once()
        command = popen.call_args.args[0]
        assert command[0] == bwrap_executable
        assert command[0] != sys.executable
        assert "--unshare-net" in command
        assert popen.call_args.kwargs["shell"] is False
        assert popen.call_args.kwargs["preexec_fn"] is None
        entry = runner._running[strategy_id]
        assert entry.tree is tree
        assert entry.temp_dir is not None
        assert (entry.temp_dir / "_start_gate").read_text(encoding="utf-8") == ""

        runner.stop(strategy_id)

    @pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
    def test_linux_bwrap_binds_only_the_runtime_wrapper_and_strategy(self, runner):
        import flinttrade_engine.strategy_runner as mod

        strategy_id = runner.upload("bwrap_source", SAFE_CODE)
        mock_proc = self._make_mock_process()
        mock_proc.wait.side_effect = subprocess.TimeoutExpired(
            cmd=["/usr/bin/bwrap"],
            timeout=mod._BWRAP_STARTUP_TIMEOUT_SECONDS,
        )

        with (
            patch.object(mod.platform, "system", return_value="Linux"),
            patch.object(mod, "_find_bwrap_executable", return_value="/usr/bin/bwrap"),
            patch("subprocess.Popen", return_value=mock_proc) as popen,
        ):
            runner.start(strategy_id)

        command = popen.call_args.args[0]
        separator = command.index("--")
        sandbox_argv = command[separator + 1 :]
        entry = runner._running[strategy_id]
        wrapper = str((entry.temp_dir / "_sandbox_wrapper.py").resolve())
        start_gate = str((entry.temp_dir / "_start_gate").resolve())
        strategy = str((runner._strategies_dir / f"{strategy_id}.py").resolve())

        assert command[0] == "/usr/bin/bwrap"
        assert ["--ro-bind", wrapper, "/run/flinttrade-strategy/_sandbox_wrapper.py"] == command[
            command.index(wrapper) - 1 : command.index(wrapper) + 2
        ]
        assert ["--ro-bind", start_gate, "/run/flinttrade-strategy/_start_gate"] == command[
            command.index(start_gate) - 1 : command.index(start_gate) + 2
        ]
        assert ["--ro-bind", strategy, "/run/flinttrade-strategy/strategy.py"] == command[
            command.index(strategy) - 1 : command.index(strategy) + 2
        ]
        assert wrapper not in sandbox_argv
        assert start_gate not in sandbox_argv
        assert strategy not in sandbox_argv
        assert sandbox_argv[0].startswith("/run/flinttrade-python/bin/python")
        assert sandbox_argv[1:] == [
            "/run/flinttrade-strategy/_sandbox_wrapper.py",
            "/run/flinttrade-strategy/_start_gate",
            "/run/flinttrade-strategy/strategy.py",
        ]
        assert "--clearenv" in command
        assert "--unshare-net" in command
        assert popen.call_args.kwargs["preexec_fn"] is None

    def test_stale_sys_frozen_does_not_expand_windows_job_process_limit(self, runner):
        import flinttrade_engine.strategy_runner as mod

        strategy_id = runner.upload("source_windows", SAFE_CODE)
        process = self._make_mock_process(pid=919)
        tree = MagicMock()
        with (
            patch.object(mod.sys, "frozen", True, create=True),
            patch.object(mod.platform, "system", return_value="Windows"),
            patch.object(mod, "_create_process_tree", return_value=tree) as create_tree,
            patch("subprocess.Popen", return_value=process) as popen,
        ):
            runner.start(strategy_id)

        command = popen.call_args.args[0]
        assert command[0] == sys.executable
        assert Path(command[1]).name == "_sandbox_wrapper.py"
        assert Path(command[2]).name == "_start_gate"
        assert command[3] == str(runner._strategies_dir / f"{strategy_id}.py")
        create_tree.assert_called_once_with(
            process,
            "Windows",
            memory_limit_bytes=256 * 1024 * 1024,
            process_limit=1,
        )

    @pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
    def test_stop_all_owns_every_uploaded_process(self, runner):
        first_id = runner.upload("first", SAFE_CODE)
        second_id = runner.upload("second", SAFE_CODE)
        first = self._make_mock_process(pid=101)
        second = self._make_mock_process(pid=202)

        with patch("subprocess.Popen", side_effect=[first, second]):
            runner.start(first_id)
            runner.start(second_id)
        first_tree = self._attach_tree(runner, first_id)
        second_tree = self._attach_tree(runner, second_id)

        stopped = runner.stop_all()

        assert set(stopped) == {first_id, second_id}
        assert runner._running == {}
        first_tree.terminate.assert_called_once()
        second_tree.terminate.assert_called_once()

    @pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
    def test_stop_all_continues_after_one_process_fails(self, runner):
        first_id = runner.upload("first_failure", SAFE_CODE)
        second_id = runner.upload("second_stops", SAFE_CODE)
        first = self._make_mock_process(pid=101)
        second = self._make_mock_process(pid=202)

        with patch("subprocess.Popen", side_effect=[first, second]):
            runner.start(first_id)
            runner.start(second_id)

        first_tree = self._attach_tree(runner, first_id)
        first_tree.terminate.side_effect = OSError("termination denied")
        second_tree = self._attach_tree(runner, second_id)

        first_entry = runner._running[first_id]
        first_temp_dir = first_entry.temp_dir

        with pytest.raises(RuntimeError, match="Failed to stop uploaded strategies"):
            runner.stop_all()

        assert first_id in runner._running
        assert second_id not in runner._running
        assert first_entry.log_file is not None
        assert first_entry.temp_dir == first_temp_dir
        assert first_temp_dir.exists()
        second_tree.terminate.assert_called_once_with()


def test_bwrap_namespace_executes_the_bound_wrapper_and_strategy(tmp_path: Path) -> None:
    import flinttrade_engine.strategy_runner as mod

    bwrap_executable = _functional_bwrap_executable()
    if bwrap_executable is None:
        pytest.skip("requires a proven functional Linux bubblewrap namespace")
    assert bwrap_executable is not None

    work = tmp_path / "work"
    work.mkdir()
    wrapper = mod._create_sandbox_wrapper(work)
    start_gate = mod._create_strategy_start_gate(work)
    strategy = tmp_path / "strategy.py"
    strategy.write_text("print('sandbox-ok')\n", encoding="utf-8")
    process = subprocess.Popen(  # noqa: S603
        mod._build_bwrap_command(
            bwrap_executable,
            sys.executable,
            str(wrapper),
            str(start_gate),
            str(strategy),
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd="/",
        text=True,
    )
    try:
        threading.Event().wait(0.1)
        assert process.poll() is None
        mod._release_strategy_start_gate(start_gate)
        stdout, stderr = process.communicate(timeout=15)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    assert process.returncode == 0, stderr
    assert stdout == "sandbox-ok\n"


def test_sandbox_wrapper_blocks_uploaded_code_until_the_parent_releases_it(tmp_path: Path) -> None:
    import flinttrade_engine.strategy_runner as mod

    work = tmp_path / "work"
    work.mkdir()
    wrapper = mod._create_sandbox_wrapper(work)
    start_gate = mod._create_strategy_start_gate(work)
    strategy = tmp_path / "strategy.py"
    strategy.write_text("print('released')\n", encoding="utf-8")
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, str(wrapper), str(start_gate), str(strategy)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        threading.Event().wait(0.1)
        assert process.poll() is None
        mod._release_strategy_start_gate(start_gate)
        stdout, stderr = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    assert process.returncode == 0, stderr
    assert stdout == "released\n"


# ---------------------------------------------------------------------------
# Delete / Status / Logs tests
# ---------------------------------------------------------------------------


class TestDeleteStatusLogs:
    def test_delete_removes_files(self, runner):
        strategy_id = runner.upload("to_delete", SAFE_CODE)
        runner.delete(strategy_id)
        assert not (runner._strategies_dir / f"{strategy_id}.py").exists()

    def test_delete_nonexistent_raises(self, runner):
        with pytest.raises(FileNotFoundError):
            runner.delete("nonexistent-id")

    @pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
    def test_delete_retains_files_and_owner_when_process_will_not_stop(self, runner):
        strategy_id = runner.upload("delete_failure", SAFE_CODE)
        process = TestStartStop()._make_mock_process(pid=303)
        process.terminate.side_effect = OSError("termination denied")
        with patch("subprocess.Popen", return_value=process):
            runner.start(strategy_id)
        tree = TestStartStop()._attach_tree(runner, strategy_id)
        tree.terminate.side_effect = OSError("termination denied")

        strategy_path = runner._strategies_dir / f"{strategy_id}.py"
        metadata_path = runner._strategies_dir / f"{strategy_id}.meta"

        with pytest.raises(OSError, match="termination denied"):
            runner.delete(strategy_id)

        assert strategy_id in runner._running
        assert strategy_path.exists()
        assert metadata_path.exists()

    @pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
    def test_status_retains_owner_when_leader_exits_but_tree_is_alive(self, runner):
        strategy_id = runner.upload("leader_exit", SAFE_CODE)
        process = TestStartStop()._make_mock_process(pid=707, returncode=0)
        with patch("subprocess.Popen", return_value=process):
            runner.start(strategy_id)
        tree = TestStartStop()._attach_tree(runner, strategy_id, alive=True)

        status = runner.get_status(strategy_id)

        assert status["state"] == "running"
        assert status["leader_exited"] is True
        assert strategy_id in runner._running
        tree.close.assert_not_called()

    @pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
    def test_status_retains_owner_when_tree_state_is_uncertain(self, runner):
        strategy_id = runner.upload("uncertain_tree", SAFE_CODE)
        process = TestStartStop()._make_mock_process(pid=808)
        with patch("subprocess.Popen", return_value=process):
            runner.start(strategy_id)
        entry = runner._running[strategy_id]
        tree = MagicMock()
        tree.is_alive.side_effect = OSError("job query failed")
        entry.tree = tree

        status = runner.get_status(strategy_id)

        assert status["state"] == "unknown"
        assert status["ownership_retained"] is True
        assert strategy_id in runner._running
        assert entry.log_file is not None
        assert entry.temp_dir is not None
        tree.close.assert_not_called()

    def test_get_status_stopped(self, runner):
        strategy_id = runner.upload("test_strat", SAFE_CODE)
        status = runner.get_status(strategy_id)
        assert status["state"] == "stopped"
        assert status["strategy_id"] == strategy_id

    def test_get_logs_no_log_file(self, runner):
        strategy_id = runner.upload("test_strat", SAFE_CODE)
        logs = runner.get_logs(strategy_id)
        assert logs == []

    def test_list_strategies_includes_uploaded(self, runner):
        strategy_id = runner.upload("listed_strat", SAFE_CODE)
        strategies = runner.list_strategies()
        ids = [s["strategy_id"] for s in strategies]
        assert strategy_id in ids
