"""Tests for the desktop sidecar entry script's lifecycle boundary.

The entry script (``packaging/desktop_backend.py``) is desktop-owned and not a
package, so it is loaded here straight from its file path. These tests cover
recovery-record transitions, packaged child dispatch, process identity, parent
liveness, and complete-tree containment. The served backend belongs to
``flinttrade_core.desktop`` and is tested there. These tests live under
``packages/apps/desktop/tests/`` (not ``packaging/tests/``)
for two hard reasons: CI's pytest glob is ``packages/*/*/tests/``, and
collecting a ``packaging/`` directory shadows the PyPI ``packaging`` module,
breaking ``packaging.version`` imports for every later test in the process.

Run with::

    uv run pytest packages/apps/desktop/tests/ -v --import-mode=importlib
"""

from __future__ import annotations

import ctypes
import errno
import importlib.util
import io
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ENTRY_SCRIPT = Path(__file__).resolve().parents[4] / "packaging" / "desktop_backend.py"
TEST_BOOT_ID = "c" * 64
POSIX_GUARDIAN_DRILL_TIMEOUT_SECONDS = 30


def _write_hardened_text(path: Path, value: str) -> None:
    """Create a fixture with the recovery boundary's exact owner policy."""
    from flinttrade_core.secure_file import write_secret_text

    write_secret_text(path, value)


def _load_entry_module() -> ModuleType:
    """Import the entry script from its file path (it is not a package)."""
    spec = importlib.util.spec_from_file_location("desktop_backend_entry", ENTRY_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(name="entry")
def entry_fixture() -> ModuleType:
    return _load_entry_module()


@pytest.fixture
def serial_posix_guardian(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Serialise drills that inspect the machine-wide POSIX process table."""
    if os.name == "nt":
        yield
        return

    import fcntl  # noqa: PLC0415 - POSIX-only test fixture

    lock_path = tmp_path_factory.getbasetemp().parent / "flinttrade-posix-guardian.lock"
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _macos_permission_fallback_api_type(
    entry: ModuleType,
    unique_ids: tuple[int, ...],
    *,
    pids: tuple[int, ...] = (56290,),
) -> type[object]:
    class PermissionFallbackApi(entry._MacosPipeLeaseApi):
        def __init__(self) -> None:
            self._proc_bsd_info = object
            self._unique_ids = iter(unique_ids)

        def list_pids(self) -> list[int]:
            return list(pids)

        def _read_unique_info(self, _pid: int) -> object:
            return SimpleNamespace(
                unique_id=next(self._unique_ids),
                parent_unique_id=42,
                id_version=7,
                original_parent_id_version=6,
            )

        def _read_process_info(self, _pid: int, _flavour: int, _info: object) -> object:
            raise PermissionError(errno.EPERM, "PROC_PIDTBSDINFO denied")

    return PermissionFallbackApi


@pytest.mark.unit
def test_import_has_no_side_effects() -> None:
    """Loading the entry script must not start the backend or a watchdog.

    Compares thread identities before/after a fresh module load — asserting on
    the global thread list alone is order-dependent (daemon watchdogs started
    by other tests in this file legitimately outlive them).
    """
    before = {t.ident for t in threading.enumerate()}
    module = _load_entry_module()
    started_by_load = [
        t for t in threading.enumerate() if t.ident not in before and t.name == "flinttrade-parent-watchdog"
    ]
    assert started_by_load == []
    assert module.PARENT_PID_ENV == "FLINTTRADE_PARENT_PID"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("  ", None),
        ("abc", None),
        ("0", None),
        ("-5", None),
        ("1234", 1234),
        (" 1234 ", 1234),
    ],
)
def test_parent_pid_parsing(entry: ModuleType, raw: str | None, expected: int | None) -> None:
    environ = {} if raw is None else {entry.PARENT_PID_ENV: raw}
    assert entry._parent_pid_from_env(environ) == expected


@pytest.mark.unit
def test_source_parent_identity_probe_prints_one_exact_line(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(entry.os, "getppid", lambda: 77)
    monkeypatch.setattr(
        entry,
        "_source_process_identity",
        lambda pid: f"v1|darwin|{pid}|macos-start-time:1:2|{'a' * 64}",
    )

    entry.print_parent_identity(stream=stream)

    assert stream.getvalue() == (
        f"FLINTTRADE_PARENT_IDENTITY v1|darwin|77|macos-start-time:1:2|{'a' * 64}\n"
    )


@pytest.mark.unit
def test_source_parent_identity_validation_binds_the_direct_parent(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = f"v1|darwin|77|macos-start-time:1:2|{'a' * 64}"
    monkeypatch.setattr(entry.os, "getppid", lambda: 77)
    monkeypatch.setattr(entry, "_source_process_identity", lambda pid: identity if pid == 77 else None)

    assert entry.validate_source_parent_identity(
        {
            entry.PARENT_PID_ENV: "77",
            entry.PARENT_IDENTITY_ENV: identity,
        }
    ) == identity

    with pytest.raises(SystemExit, match="direct Electron parent identity"):
        entry.validate_source_parent_identity(
            {
                entry.PARENT_PID_ENV: "88",
                entry.PARENT_IDENTITY_ENV: identity,
            }
        )


@pytest.mark.unit
def test_source_parent_identity_validation_rejects_generation_or_image_change(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = f"v1|darwin|77|macos-start-time:1:2|{'a' * 64}"
    current = f"v1|darwin|77|macos-start-time:1:3|{'a' * 64}"
    monkeypatch.setattr(entry.os, "getppid", lambda: 77)
    monkeypatch.setattr(entry, "_source_process_identity", lambda _pid: current)

    with pytest.raises(SystemExit, match="direct Electron parent identity"):
        entry.validate_source_parent_identity(
            {
                entry.PARENT_PID_ENV: "77",
                entry.PARENT_IDENTITY_ENV: expected,
            }
        )


@pytest.mark.unit
def test_source_parent_identity_match_is_exact_and_rejects_pid_reuse(
    entry: ModuleType,
) -> None:
    expected = f"v1|win32|77|windows-creation-time:123|{'a' * 64}"

    assert entry._source_parent_identity_matches(
        77,
        expected,
        identity_lookup=lambda _pid: expected,
    ) is True
    assert entry._source_parent_identity_matches(
        77,
        expected,
        identity_lookup=lambda _pid: expected.replace(":123|", ":124|"),
    ) is False
    assert entry._source_parent_identity_matches(
        88,
        expected,
        identity_lookup=lambda _pid: expected,
    ) is False


@pytest.mark.unit
def test_source_parent_watch_uses_the_bound_kernel_generation_without_rehashing(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    platform_name = "linux" if sys.platform.startswith("linux") else "darwin"
    expected = f"v1|{platform_name}|77|kernel-start:1:2|{'a' * 64}"
    monkeypatch.setattr(
        entry,
        "_posix_process_start_token",
        lambda pid: "kernel-start:1:2" if pid == 77 else None,
    )
    monkeypatch.setattr(
        entry,
        "_source_process_identity",
        lambda _pid: (_ for _ in ()).throw(AssertionError("polling must not rehash Electron")),
    )

    assert entry._posix_parent_alive(
        77,
        track_reparent=False,
        expected_identity=expected,
    ) is True

    monkeypatch.setattr(entry, "_posix_process_start_token", lambda _pid: "kernel-start:1:3")
    assert entry._posix_parent_alive(
        77,
        track_reparent=False,
        expected_identity=expected,
    ) is False


@pytest.mark.unit
def test_source_guardian_creates_exact_pending_record(
    entry: ModuleType,
    tmp_path: Path,
) -> None:
    record = tmp_path / "desktop_backend.pid"
    token = "a" * 64
    environ = {
        entry.PARENT_PID_ENV: "77",
        entry.BOOT_ID_ENV: TEST_BOOT_ID,
        entry.LAUNCH_TOKEN_ENV: token,
        entry.SIDECAR_RECORD_PATH_ENV: str(record),
    }

    assert entry.create_pending_application_pid_record(environ=environ, guardian_pid=1234) is True
    assert record.read_text(encoding="ascii") == (
        f"v4\n1234\npending\n77\n{TEST_BOOT_ID}\n{token}\n"
    )
    if os.name != "nt":
        assert record.stat().st_mode & 0o077 == 0


@pytest.mark.unit
def test_source_guardian_refuses_to_replace_existing_recovery_record(
    entry: ModuleType,
    tmp_path: Path,
) -> None:
    record = tmp_path / "desktop_backend.pid"
    record.write_text("existing recovery authority\n", encoding="ascii")
    environ = {
        entry.PARENT_PID_ENV: "77",
        entry.BOOT_ID_ENV: TEST_BOOT_ID,
        entry.LAUNCH_TOKEN_ENV: "a" * 64,
        entry.SIDECAR_RECORD_PATH_ENV: str(record),
    }

    assert entry.create_pending_application_pid_record(environ=environ, guardian_pid=1234) is False
    assert record.read_text(encoding="ascii") == "existing recovery authority\n"


@pytest.mark.unit
@pytest.mark.parametrize("raw_path", ["desktop_backend.pid", " /tmp/desktop_backend.pid "])
def test_source_guardian_requires_an_exact_absolute_record_path(
    entry: ModuleType,
    raw_path: str,
) -> None:
    environ = {
        entry.PARENT_PID_ENV: "77",
        entry.BOOT_ID_ENV: TEST_BOOT_ID,
        entry.LAUNCH_TOKEN_ENV: "a" * 64,
        entry.SIDECAR_RECORD_PATH_ENV: raw_path,
    }

    assert entry.create_pending_application_pid_record(environ=environ, guardian_pid=1234) is False


@pytest.mark.unit
def test_source_guardian_fails_closed_on_a_stale_pre_existing_v4_record(
    entry: ModuleType,
    tmp_path: Path,
) -> None:
    record = tmp_path / "desktop_backend.pid"
    stale = f"v4\n9001\n9002\n77\n{'d' * 64}\n{'b' * 64}\n"
    record.write_text(stale, encoding="ascii")
    environ = {
        entry.PARENT_PID_ENV: "77",
        entry.BOOT_ID_ENV: TEST_BOOT_ID,
        entry.LAUNCH_TOKEN_ENV: "a" * 64,
        entry.SIDECAR_RECORD_PATH_ENV: str(record),
    }

    assert entry.create_pending_application_pid_record(environ=environ, guardian_pid=1234) is False
    assert record.read_text(encoding="ascii") == stale
    assert entry._cleanup_complete_proof_path(record).exists() is False


@pytest.mark.unit
@pytest.mark.skipif(os.name == "nt", reason="link fixtures require POSIX ownership semantics")
@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_source_guardian_refuses_unsafe_transition_lock_without_chmoding_target(
    entry: ModuleType,
    tmp_path: Path,
    link_kind: str,
) -> None:
    record = tmp_path / "desktop_backend.pid"
    guard = record.with_name(f".{record.name}.lock")
    target = tmp_path / "foreign-lock-target"
    target.write_text("foreign authority\n", encoding="ascii")
    target.chmod(0o644)
    if link_kind == "symlink":
        guard.symlink_to(target)
    else:
        os.link(target, guard)
    original_mode = target.stat().st_mode
    environ = {
        entry.PARENT_PID_ENV: "77",
        entry.BOOT_ID_ENV: TEST_BOOT_ID,
        entry.LAUNCH_TOKEN_ENV: "a" * 64,
        entry.SIDECAR_RECORD_PATH_ENV: str(record),
    }

    assert entry.create_pending_application_pid_record(environ=environ, guardian_pid=1234) is False
    assert target.read_text(encoding="ascii") == "foreign authority\n"
    assert target.stat().st_mode == original_mode
    assert record.exists() is False


@pytest.mark.unit
@pytest.mark.skipif(os.name == "nt", reason="link fixtures require POSIX ownership semantics")
@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_new_pending_record_refuses_linked_orphaned_cleanup_proof(
    entry: ModuleType,
    tmp_path: Path,
    link_kind: str,
) -> None:
    record = tmp_path / "desktop_backend.pid"
    proof = entry._cleanup_complete_proof_path(record)
    target = tmp_path / "old-proof-target"
    old_payload = f"FLINTTRADE_BACKEND_CLEANUP_COMPLETE token={'b' * 64}\n"
    _write_hardened_text(target, old_payload)
    if link_kind == "symlink":
        proof.symlink_to(target)
    else:
        os.link(target, proof)
    environ = {
        entry.PARENT_PID_ENV: "77",
        entry.BOOT_ID_ENV: TEST_BOOT_ID,
        entry.LAUNCH_TOKEN_ENV: "a" * 64,
        entry.SIDECAR_RECORD_PATH_ENV: str(record),
    }

    assert entry.create_pending_application_pid_record(environ=environ, guardian_pid=1234) is False
    assert target.read_text(encoding="ascii") == old_payload
    assert record.exists() is False


def _write_cleanup_fixture(
    entry: ModuleType,
    tmp_path: Path,
    *,
    application: str = "5678",
    token: str = "a" * 64,
) -> tuple[Path, dict[str, str]]:
    record = tmp_path / "desktop_backend.pid"
    _write_hardened_text(
        record,
        f"v4\n1234\n{application}\n77\n{TEST_BOOT_ID}\n{token}\n",
    )
    guard = record.with_name(f".{record.name}.lock")
    _write_hardened_text(guard, "")
    environ = {
        entry.PARENT_PID_ENV: "77",
        entry.BOOT_ID_ENV: TEST_BOOT_ID,
        entry.LAUNCH_TOKEN_ENV: token,
        entry.SIDECAR_RECORD_PATH_ENV: str(record),
    }
    return record, environ


@pytest.mark.unit
def test_managed_cleanup_removes_exact_promoted_record_and_token_proof(
    entry: ModuleType,
    tmp_path: Path,
) -> None:
    record, environ = _write_cleanup_fixture(entry, tmp_path)
    proof = entry._cleanup_complete_proof_path(record)
    _write_hardened_text(
        proof,
        f"FLINTTRADE_BACKEND_CLEANUP_COMPLETE token={'a' * 64}\n",
    )

    assert entry.finalise_source_cleanup(
        1234,
        5678,
        environ=environ,
        pid_alive=lambda _pid: False,
    ) is True
    assert record.exists() is False
    assert proof.exists() is False


@pytest.mark.unit
def test_managed_cleanup_allows_exact_dead_pending_record_without_a_proof(
    entry: ModuleType,
    tmp_path: Path,
) -> None:
    record, environ = _write_cleanup_fixture(entry, tmp_path, application="pending")

    assert entry.finalise_source_cleanup(
        1234,
        None,
        environ=environ,
        pid_alive=lambda _pid: False,
    ) is True
    assert record.exists() is False


@pytest.mark.unit
def test_managed_pending_cleanup_is_idempotent_after_python_already_cleared_record(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record, environ = _write_cleanup_fixture(entry, tmp_path, application="pending")

    assert entry.clear_pending_application_pid_record(environ=environ) is True
    assert record.exists() is False
    monkeypatch.setattr(entry.os, "getpid", lambda: 999_999)

    assert entry.finalise_source_cleanup(
        1234,
        None,
        environ=environ,
        pid_alive=lambda _pid: False,
    ) is True


@pytest.mark.unit
def test_managed_pending_cleanup_refuses_absent_record_with_mismatched_crash_left_proof(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record, environ = _write_cleanup_fixture(entry, tmp_path, application="pending")
    assert entry.clear_pending_application_pid_record(environ=environ) is True
    proof = entry._cleanup_complete_proof_path(record)
    foreign_proof = f"FLINTTRADE_BACKEND_CLEANUP_COMPLETE token={'b' * 64}\n"
    _write_hardened_text(proof, foreign_proof)
    monkeypatch.setattr(entry.os, "getpid", lambda: 999_999)

    assert entry.finalise_source_cleanup(
        1234,
        None,
        environ=environ,
        pid_alive=lambda _pid: False,
    ) is False
    assert record.exists() is False
    assert proof.read_text(encoding="ascii") == foreign_proof


@pytest.mark.unit
def test_managed_pending_cleanup_finalises_record_when_python_clear_failed(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record, environ = _write_cleanup_fixture(entry, tmp_path, application="pending")
    stream = io.StringIO()
    monkeypatch.setattr(entry, "promote_application_pid_record", lambda **_kwargs: False)
    monkeypatch.setattr(entry, "clear_pending_application_pid_record", lambda **_kwargs: False)

    with pytest.raises(SystemExit, match="application PID record promotion failed"):
        entry.require_application_pid_record(environ=environ, stream=stream)
    assert record.exists() is True
    assert stream.getvalue() == (
        f"FLINTTRADE_BACKEND_PENDING_EXIT_ACK token={'a' * 64} reason=promotion-failed\n"
    )

    monkeypatch.setattr(entry.os, "getpid", lambda: 999_999)
    assert entry.finalise_source_cleanup(
        1234,
        None,
        environ=environ,
        pid_alive=lambda _pid: False,
    ) is True
    assert record.exists() is False


@pytest.mark.unit
def test_new_pending_record_reconciles_proof_left_by_finaliser_crash(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record, old_environ = _write_cleanup_fixture(entry, tmp_path)
    proof = entry._cleanup_complete_proof_path(record)
    _write_hardened_text(
        proof,
        f"FLINTTRADE_BACKEND_CLEANUP_COMPLETE token={'a' * 64}\n",
    )
    durable_unlink = entry._durably_unlink_cleanup_file

    def crash_after_record_unlink(path: Path) -> None:
        if path == proof:
            raise OSError("injected finaliser crash")
        durable_unlink(path)

    monkeypatch.setattr(entry, "_durably_unlink_cleanup_file", crash_after_record_unlink)
    assert entry.finalise_source_cleanup(
        1234,
        5678,
        environ=old_environ,
        pid_alive=lambda _pid: False,
    ) is False
    assert record.exists() is False
    assert proof.exists() is True

    monkeypatch.setattr(entry, "_durably_unlink_cleanup_file", durable_unlink)
    new_environ = old_environ | {
        entry.LAUNCH_TOKEN_ENV: "b" * 64,
        entry.BOOT_ID_ENV: "d" * 64,
    }
    assert entry.create_pending_application_pid_record(
        environ=new_environ,
        guardian_pid=4321,
    ) is True
    assert proof.exists() is False
    assert record.read_text(encoding="ascii") == (
        f"v4\n4321\npending\n77\n{'d' * 64}\n{'b' * 64}\n"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("guardian_pid", "application_pid", "mutate_proof"),
    [
        (9999, 5678, False),
        (1234, 9999, False),
        (1234, 5678, True),
    ],
)
def test_managed_cleanup_refuses_mismatched_record_or_proof(
    entry: ModuleType,
    tmp_path: Path,
    guardian_pid: int,
    application_pid: int,
    mutate_proof: bool,
) -> None:
    record, environ = _write_cleanup_fixture(entry, tmp_path)
    proof = entry._cleanup_complete_proof_path(record)
    proof_token = "b" * 64 if mutate_proof else "a" * 64
    _write_hardened_text(
        proof,
        f"FLINTTRADE_BACKEND_CLEANUP_COMPLETE token={proof_token}\n",
    )
    original_record = record.read_bytes()

    assert entry.finalise_source_cleanup(
        guardian_pid,
        application_pid,
        environ=environ,
        pid_alive=lambda _pid: False,
    ) is False
    assert record.read_bytes() == original_record
    assert proof.exists() is True


@pytest.mark.unit
def test_managed_cleanup_refuses_a_live_recorded_process(
    entry: ModuleType,
    tmp_path: Path,
) -> None:
    record, environ = _write_cleanup_fixture(entry, tmp_path)
    proof = entry._cleanup_complete_proof_path(record)
    _write_hardened_text(
        proof,
        f"FLINTTRADE_BACKEND_CLEANUP_COMPLETE token={'a' * 64}\n",
    )

    assert entry.finalise_source_cleanup(
        1234,
        5678,
        environ=environ,
        pid_alive=lambda pid: pid == 5678,
    ) is False
    assert record.exists() is True
    assert proof.exists() is True


@pytest.mark.unit
def test_managed_cleanup_refuses_record_and_proof_symlinks(
    entry: ModuleType,
    tmp_path: Path,
) -> None:
    if os.name == "nt":
        pytest.skip("symlink creation requires optional Windows privileges")
    target_dir = tmp_path / "targets"
    target_dir.mkdir()
    record_target, environ = _write_cleanup_fixture(entry, target_dir)
    proof_target = entry._cleanup_complete_proof_path(record_target)
    _write_hardened_text(
        proof_target,
        f"FLINTTRADE_BACKEND_CLEANUP_COMPLETE token={'a' * 64}\n",
    )
    record_link = tmp_path / "desktop_backend.pid"
    record_link.symlink_to(record_target)
    link_guard = record_link.with_name(f".{record_link.name}.lock")
    _write_hardened_text(link_guard, "")
    record_env = environ | {entry.SIDECAR_RECORD_PATH_ENV: str(record_link)}

    assert entry.finalise_source_cleanup(
        1234,
        5678,
        environ=record_env,
        pid_alive=lambda _pid: False,
    ) is False
    assert record_target.exists() is True

    proof_link = entry._cleanup_complete_proof_path(record_target)
    proof_elsewhere = tmp_path / "proof-elsewhere"
    _write_hardened_text(proof_elsewhere, proof_target.read_text(encoding="ascii"))
    proof_link.unlink()
    proof_link.symlink_to(proof_elsewhere)
    assert entry.finalise_source_cleanup(
        1234,
        5678,
        environ=environ,
        pid_alive=lambda _pid: False,
    ) is False
    assert record_target.exists() is True
    assert proof_elsewhere.exists() is True


@pytest.mark.unit
def test_managed_cleanup_command_validates_parent_and_emits_no_token(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[object] = []
    monkeypatch.setenv("FLINTTRADE_DESKTOP", "1")
    monkeypatch.setattr(entry.sys, "frozen", False, raising=False)
    monkeypatch.setattr(
        entry,
        "validate_source_parent_identity",
        lambda: events.append("validate-parent") or "v1|test",
    )
    monkeypatch.setattr(
        entry,
        "finalise_source_cleanup",
        lambda guardian_pid, application_pid: events.append(
            (guardian_pid, application_pid)
        )
        or True,
    )

    assert entry.run_desktop_backend(
        [
            "--flinttrade-finalise-cleanup",
            "--guardian-pid",
            "1234",
            "--application-pid",
            "5678",
        ]
    ) == 0
    assert events == ["validate-parent", (1234, 5678)]
    assert capsys.readouterr().out == ""


@pytest.mark.integration
@pytest.mark.skipif(os.name == "nt", reason="POSIX hard-link publication boundary")
@pytest.mark.parametrize(
    ("boundary", "exit_code", "record_exists"),
    [
        ("before-publish", 41, False),
        ("after-publish", 42, True),
    ],
)
def test_source_guardian_pending_record_crash_boundary_is_absent_or_complete(
    tmp_path: Path,
    boundary: str,
    exit_code: int,
    record_exists: bool,
) -> None:
    record = tmp_path / "desktop_backend.pid"
    token = "a" * 64
    script = textwrap.dedent(
        f"""
        import importlib.util, os
        spec = importlib.util.spec_from_file_location("desktop_backend_entry", {str(ENTRY_SCRIPT)!r})
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if {boundary!r} == "before-publish":
            mod.os.link = lambda *_args, **_kwargs: os._exit(41)
        else:
            mod._sync_parent_directory = lambda _path: os._exit(42)
        environ = {{
            "FLINTTRADE_PARENT_PID": "77",
            "FLINTTRADE_BOOT_ID": {TEST_BOOT_ID!r},
            "FLINTTRADE_LAUNCH_TOKEN": {token!r},
            "FLINTTRADE_SIDECAR_RECORD_PATH": {str(record)!r},
        }}
        mod.create_pending_application_pid_record(environ=environ, guardian_pid=1234)
        raise SystemExit(99)
        """
    )

    completed = subprocess.run([sys.executable, "-c", script], timeout=10, check=False)

    assert completed.returncode == exit_code
    assert record.exists() is record_exists
    if record_exists:
        assert record.read_text(encoding="ascii") == (
            f"v4\n1234\npending\n77\n{TEST_BOOT_ID}\n{token}\n"
        )


@pytest.mark.unit
def test_source_guardian_acquires_lease_before_record_containment_and_backend_import(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    cleanup_callbacks: list[object] = []

    class Lease:
        owner_pid = os.getpid()

        def release(self) -> None:
            events.append("release-lease")

    monkeypatch.setenv(entry.PARENT_PID_ENV, str(os.getppid()))
    monkeypatch.setenv(entry.PARENT_IDENTITY_ENV, "v1|test")
    monkeypatch.setenv(entry.BOOT_ID_ENV, TEST_BOOT_ID)
    monkeypatch.setenv(entry.LAUNCH_TOKEN_ENV, "a" * 64)
    monkeypatch.setenv(entry.SIDECAR_RECORD_PATH_ENV, str(tmp_path / "desktop_backend.pid"))
    monkeypatch.setenv("FLINTTRADE_DESKTOP", "1")
    monkeypatch.setattr(entry.sys, "frozen", False, raising=False)
    monkeypatch.setattr(
        entry,
        "validate_source_parent_identity",
        lambda: events.append("validate-parent") or "v1|test",
    )
    monkeypatch.setattr(
        entry,
        "_acquire_source_guardian_lease",
        lambda: events.append("acquire-lease") or Lease(),
    )
    monkeypatch.setattr(
        entry,
        "create_pending_application_pid_record",
        lambda: events.append("create-record") or True,
    )
    monkeypatch.setattr(
        entry,
        "require_application_pid_record",
        lambda: events.append("promote-record"),
    )
    monkeypatch.setattr(entry, "announce_application_pid", lambda: events.append("announce-pid"))

    def prepare(
        publish_application_identity: object | None = None,
        *,
        cleanup_complete: object | None = None,
    ) -> object:
        events.append("prepare-containment")
        assert publish_application_identity is None
        assert callable(cleanup_complete)
        cleanup_callbacks.append(cleanup_complete)
        return lambda: True

    monkeypatch.setattr(entry, "_prepare_owned_process_tree", prepare)
    monkeypatch.setattr(entry, "start_parent_watchdog", lambda *_args, **_kwargs: events.append("watch-parent"))
    monkeypatch.setattr(entry, "start_stdin_shutdown_listener", lambda *_args, **_kwargs: events.append("watch-stdin"))
    monkeypatch.setattr(entry, "start_sigterm_shutdown_relay", lambda *_args, **_kwargs: events.append("watch-sigterm"))
    monkeypatch.setattr(
        entry,
        "_run_core_desktop",
        lambda argv, **kwargs: events.append(f"core:{argv}:{kwargs['guardian_owned_lease']}"),
    )

    assert entry.run_desktop_backend(["--port", "0"]) == 0
    assert events == [
        "validate-parent",
        "acquire-lease",
        "create-record",
        "prepare-containment",
        "promote-record",
        "announce-pid",
        "watch-parent",
        "watch-stdin",
        "watch-sigterm",
        "core:['--port', '0']:True",
    ]

    cleanup_callbacks[0]()
    assert events[-1] == "release-lease"


@pytest.mark.unit
@pytest.mark.parametrize("failure", ["return-none", "raise"])
def test_source_guardian_containment_setup_failure_is_proved_finalisable_and_releases_lease(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    token = "a" * 64
    record = tmp_path / "desktop_backend.pid"
    guardian_pid = os.getpid()
    released: list[str] = []

    class Lease:
        owner_pid = guardian_pid

        def release(self) -> None:
            released.append("released")

    monkeypatch.setenv(entry.PARENT_PID_ENV, str(os.getppid()))
    monkeypatch.setenv(entry.PARENT_IDENTITY_ENV, "v1|test")
    monkeypatch.setenv(entry.BOOT_ID_ENV, TEST_BOOT_ID)
    monkeypatch.setenv(entry.LAUNCH_TOKEN_ENV, token)
    monkeypatch.setenv(entry.SIDECAR_RECORD_PATH_ENV, str(record))
    monkeypatch.setenv("FLINTTRADE_DESKTOP", "1")
    monkeypatch.setattr(entry.sys, "frozen", False, raising=False)
    monkeypatch.setattr(entry, "validate_source_parent_identity", lambda: "v1|test")
    monkeypatch.setattr(entry, "_acquire_source_guardian_lease", Lease)

    def fail_containment(**_kwargs: object) -> None:
        if failure == "raise":
            raise OSError("injected containment failure")
        return None

    monkeypatch.setattr(entry, "_prepare_owned_process_tree", fail_containment)
    if failure == "raise":
        with pytest.raises(OSError, match="injected containment failure"):
            entry.run_desktop_backend(["--port", "0"])
    else:
        with pytest.raises(SystemExit, match="complete process-tree containment is unavailable"):
            entry.run_desktop_backend(["--port", "0"])

    expected_record = f"v4\n{guardian_pid}\npending\n{os.getppid()}\n{TEST_BOOT_ID}\n{token}\n"
    expected_proof = f"FLINTTRADE_BACKEND_CLEANUP_COMPLETE token={token}\n"
    assert released == ["released"]
    assert record.read_text(encoding="ascii") == expected_record
    assert entry._cleanup_complete_proof_path(record).read_text(encoding="ascii") == expected_proof
    assert capsys.readouterr().out == (
        expected_proof
        + f"FLINTTRADE_BACKEND_PENDING_EXIT_ACK token={token} reason=promotion-failed\n"
    )

    monkeypatch.setattr(entry.os, "getpid", lambda: 999_999)
    assert entry.finalise_source_cleanup(
        guardian_pid,
        None,
        pid_alive=lambda _pid: False,
    ) is True
    assert record.exists() is False
    assert entry._cleanup_complete_proof_path(record).exists() is False


@pytest.mark.unit
def test_source_guardian_lease_contention_blocks_before_record_publication(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from flinttrade_core.backend_instance import BackendInstanceAlreadyRunning

    monkeypatch.setenv("FLINTTRADE_DESKTOP", "1")
    monkeypatch.setattr(entry.sys, "frozen", False, raising=False)
    monkeypatch.setattr(entry, "validate_source_parent_identity", lambda: "v1|test")
    monkeypatch.setattr(
        entry,
        "_acquire_source_guardian_lease",
        lambda: (_ for _ in ()).throw(BackendInstanceAlreadyRunning("occupied")),
    )
    marker: list[str] = []
    monkeypatch.setattr(entry, "create_pending_application_pid_record", lambda: marker.append("record"))

    with pytest.raises(BackendInstanceAlreadyRunning):
        entry.run_desktop_backend(["--port", "0"])

    assert marker == []
    assert capsys.readouterr().out == "FLINTTRADE_BACKEND_BLOCKED reason=instance-lease\n"


@pytest.mark.unit
def test_source_guardian_lease_failure_exposes_only_the_exception_class(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "lease-provider-secret"

    class ExternalLeaseError(RuntimeError):
        pass

    monkeypatch.setenv("FLINTTRADE_DESKTOP", "1")
    monkeypatch.setattr(entry.sys, "frozen", False, raising=False)
    monkeypatch.setattr(entry, "validate_source_parent_identity", lambda: "v1|test")
    monkeypatch.setattr(
        entry,
        "_acquire_source_guardian_lease",
        lambda: (_ for _ in ()).throw(ExternalLeaseError(secret)),
    )
    create_record = []
    monkeypatch.setattr(
        entry,
        "create_pending_application_pid_record",
        lambda: create_record.append("record"),
    )

    with pytest.raises(
        RuntimeError,
        match=r"Source guardian lease acquisition failed \(ExternalLeaseError\)",
    ) as raised:
        entry.run_desktop_backend(["--port", "0"])

    assert secret not in str(raised.value)
    assert raised.value.__cause__ is None
    assert create_record == []


@pytest.mark.unit
def test_frozen_tauri_dispatch_does_not_use_source_guardian_lease(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    monkeypatch.setenv("FLINTTRADE_DESKTOP", "1")
    monkeypatch.setattr(entry.sys, "frozen", True, raising=False)
    monkeypatch.setattr(entry, "publish_packaged_child_contract", lambda: events.append("publish-child"))
    monkeypatch.setattr(
        entry,
        "_acquire_source_guardian_lease",
        lambda: (_ for _ in ()).throw(AssertionError("frozen path must keep Tauri ownership")),
    )
    monkeypatch.setattr(
        entry,
        "_prepare_owned_process_tree",
        lambda publish_application_identity=None, **_kwargs: (
            pytest.fail("record publication must follow complete containment")
            if publish_application_identity is not None
            else (lambda: True)
        ),
    )
    monkeypatch.setattr(entry, "require_application_pid_record", lambda: events.append("promote-record"))
    monkeypatch.setattr(entry, "announce_application_pid", lambda: events.append("announce-pid"))
    monkeypatch.setattr(entry, "start_parent_watchdog", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(entry, "start_stdin_shutdown_listener", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(entry, "start_sigterm_shutdown_relay", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        entry,
        "_run_core_desktop",
        lambda argv, **kwargs: events.append(f"core:{argv}:{kwargs['guardian_owned_lease']}"),
    )

    assert entry.run_desktop_backend(["--port", "0"]) == 0
    assert events == [
        "publish-child",
        "promote-record",
        "announce-pid",
        "core:['--port', '0']:False",
    ]


@pytest.mark.unit
def test_posix_guardian_releases_source_lease_only_after_cleanup_proof(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    released: list[str] = []
    monkeypatch.setattr(entry, "_publish_cleanup_complete_proof_with_retry", lambda _pid, **_kwargs: False)

    def release() -> None:
        released.append("cleanup-proved")

    assert entry._complete_guardian_cleanup(5678, release) is False
    assert released == []

    monkeypatch.setattr(entry, "_publish_cleanup_complete_proof_with_retry", lambda _pid, **_kwargs: True)
    assert entry._complete_guardian_cleanup(5678, release) is True
    assert released == ["cleanup-proved"]


@pytest.mark.unit
def test_application_promotes_exact_pending_record_before_handshake(
    entry: ModuleType,
    tmp_path: Path,
) -> None:
    record = tmp_path / "desktop_backend.pid"
    token = "a" * 64
    _write_hardened_text(record, f"v4\n1234\npending\n77\n{TEST_BOOT_ID}\n{token}\n")
    environ = {
        "FLINTTRADE_PARENT_PID": "77",
        "FLINTTRADE_BOOT_ID": TEST_BOOT_ID,
        "FLINTTRADE_LAUNCH_TOKEN": token,
        "FLINTTRADE_SIDECAR_RECORD_PATH": str(record),
    }

    assert entry.promote_application_pid_record(environ=environ, pid=5678) is True
    assert record.read_text(encoding="utf-8") == f"v4\n1234\n5678\n77\n{TEST_BOOT_ID}\n{token}\n"


@pytest.mark.unit
def test_application_pid_promotion_requires_the_exact_boot_bound_record(
    entry: ModuleType,
    tmp_path: Path,
) -> None:
    record = tmp_path / "desktop_backend.pid"
    token = "a" * 64
    boot_id = "c" * 64
    pending = f"v4\n1234\npending\n77\n{boot_id}\n{token}\n"
    _write_hardened_text(record, pending)
    environ = {
        "FLINTTRADE_PARENT_PID": "77",
        "FLINTTRADE_BOOT_ID": boot_id,
        "FLINTTRADE_LAUNCH_TOKEN": token,
        "FLINTTRADE_SIDECAR_RECORD_PATH": str(record),
    }

    assert entry.promote_application_pid_record(environ=environ, pid=5678) is True
    assert record.read_text(encoding="utf-8") == f"v4\n1234\n5678\n77\n{boot_id}\n{token}\n"


@pytest.mark.unit
def test_application_pid_promotion_keeps_pending_record_when_atomic_replace_fails(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = tmp_path / "desktop_backend.pid"
    token = "a" * 64
    pending = f"v4\n1234\npending\n77\n{TEST_BOOT_ID}\n{token}\n"
    _write_hardened_text(record, pending)
    environ = {
        "FLINTTRADE_PARENT_PID": "77",
        "FLINTTRADE_BOOT_ID": TEST_BOOT_ID,
        "FLINTTRADE_LAUNCH_TOKEN": token,
        "FLINTTRADE_SIDECAR_RECORD_PATH": str(record),
    }
    monkeypatch.setattr(entry.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("injected")))

    assert entry.promote_application_pid_record(environ=environ, pid=5678) is False
    assert record.read_text(encoding="utf-8") == pending
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.unit
def test_application_pid_promotion_is_valid_after_post_replace_sync_failure(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = tmp_path / "desktop_backend.pid"
    token = "a" * 64
    _write_hardened_text(record, f"v4\n1234\npending\n77\n{TEST_BOOT_ID}\n{token}\n")
    environ = {
        "FLINTTRADE_PARENT_PID": "77",
        "FLINTTRADE_BOOT_ID": TEST_BOOT_ID,
        "FLINTTRADE_LAUNCH_TOKEN": token,
        "FLINTTRADE_SIDECAR_RECORD_PATH": str(record),
    }
    monkeypatch.setattr(
        entry,
        "_sync_parent_directory",
        lambda _path: (_ for _ in ()).throw(OSError("injected after replace")),
    )

    assert entry.promote_application_pid_record(environ=environ, pid=5678) is False
    assert record.read_text(encoding="utf-8") == f"v4\n1234\n5678\n77\n{TEST_BOOT_ID}\n{token}\n"
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.integration
@pytest.mark.parametrize(
    ("boundary", "exit_code", "application_field"),
    [
        ("before-replace", 41, "pending"),
        ("after-replace", 42, "5678"),
    ],
)
def test_application_pid_promotion_crash_boundary_keeps_a_complete_record(
    tmp_path: Path,
    boundary: str,
    exit_code: int,
    application_field: str,
) -> None:
    record = tmp_path / "desktop_backend.pid"
    token = "a" * 64
    pending = f"v4\n1234\npending\n77\n{TEST_BOOT_ID}\n{token}\n"
    _write_hardened_text(record, pending)
    script = textwrap.dedent(
        f"""
        import importlib.util, os
        spec = importlib.util.spec_from_file_location("desktop_backend_entry", {str(ENTRY_SCRIPT)!r})
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if {boundary!r} == "before-replace":
            mod.os.replace = lambda *_args: os._exit(41)
        else:
            mod._sync_parent_directory = lambda _path: os._exit(42)
        environ = {{
            "FLINTTRADE_PARENT_PID": "77",
            "FLINTTRADE_BOOT_ID": {TEST_BOOT_ID!r},
            "FLINTTRADE_LAUNCH_TOKEN": {token!r},
            "FLINTTRADE_SIDECAR_RECORD_PATH": {str(record)!r},
        }}
        mod.promote_application_pid_record(environ=environ, pid=5678)
        raise SystemExit(99)
        """
    )

    completed = subprocess.run([sys.executable, "-c", script], timeout=10, check=False)

    assert completed.returncode == exit_code
    assert record.read_text(encoding="utf-8") == (f"v4\n1234\n{application_field}\n77\n{TEST_BOOT_ID}\n{token}\n")


@pytest.mark.unit
def test_application_pid_handshake_is_flushed(entry: ModuleType) -> None:
    stream = io.StringIO()

    entry.announce_application_pid(stream=stream, pid=5678)

    assert stream.getvalue() == "FLINTTRADE_BACKEND_PID pid=5678\n"


@pytest.mark.unit
def test_application_refuses_to_promote_another_launch_record(
    entry: ModuleType,
    tmp_path: Path,
) -> None:
    record = tmp_path / "desktop_backend.pid"
    _write_hardened_text(
        record,
        f"v4\n1234\npending\n77\n{TEST_BOOT_ID}\n{'b' * 64}\n",
    )
    environ = {
        "FLINTTRADE_PARENT_PID": "77",
        "FLINTTRADE_BOOT_ID": TEST_BOOT_ID,
        "FLINTTRADE_LAUNCH_TOKEN": "a" * 64,
        "FLINTTRADE_SIDECAR_RECORD_PATH": str(record),
    }

    assert entry.promote_application_pid_record(environ=environ, pid=5678) is False
    assert record.read_text(encoding="utf-8") == (f"v4\n1234\npending\n77\n{TEST_BOOT_ID}\n{'b' * 64}\n")


@pytest.mark.unit
def test_application_token_comparisons_do_not_normalise_whitespace(
    entry: ModuleType,
    tmp_path: Path,
) -> None:
    token = "a" * 64
    pending = f"v4\n1234\npending\n77\n{TEST_BOOT_ID}\n{token}\n"
    record = tmp_path / "desktop_backend.pid"
    _write_hardened_text(record, pending)
    environ = {
        "FLINTTRADE_PARENT_PID": "77",
        "FLINTTRADE_BOOT_ID": TEST_BOOT_ID,
        "FLINTTRADE_LAUNCH_TOKEN": f" {token} ",
        "FLINTTRADE_SIDECAR_RECORD_PATH": str(record),
    }

    assert entry.promote_application_pid_record(environ=environ, pid=5678) is False
    assert entry.clear_pending_application_pid_record(environ=environ) is False
    assert record.read_text(encoding="utf-8") == pending


@pytest.mark.unit
def test_backend_boot_refuses_untracked_application_pid(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(entry, "promote_application_pid_record", lambda: False)

    with pytest.raises(SystemExit, match="application PID record promotion failed"):
        entry.require_application_pid_record()


@pytest.mark.unit
def test_promotion_failure_clears_exact_pending_record_before_refusing_boot(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    token = "a" * 64
    record = tmp_path / "desktop_backend.pid"
    _write_hardened_text(record, f"v4\n1234\npending\n77\n{TEST_BOOT_ID}\n{token}\n")
    environ = {
        "FLINTTRADE_PARENT_PID": "77",
        "FLINTTRADE_BOOT_ID": TEST_BOOT_ID,
        "FLINTTRADE_LAUNCH_TOKEN": token,
        "FLINTTRADE_SIDECAR_RECORD_PATH": str(record),
    }
    stream = io.StringIO()
    monkeypatch.setattr(entry, "promote_application_pid_record", lambda **_kwargs: False)

    with pytest.raises(SystemExit, match="application PID record promotion failed"):
        entry.require_application_pid_record(environ=environ, stream=stream)

    assert record.exists() is False
    assert stream.getvalue() == (f"FLINTTRADE_BACKEND_PENDING_EXIT_ACK token={token} reason=promotion-failed\n")


@pytest.mark.unit
def test_promotion_failure_ack_survives_a_transient_python_cleanup_failure(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "a" * 64
    environ = {
        "FLINTTRADE_PARENT_PID": "77",
        "FLINTTRADE_BOOT_ID": TEST_BOOT_ID,
        "FLINTTRADE_LAUNCH_TOKEN": token,
        "FLINTTRADE_SIDECAR_RECORD_PATH": "/temporarily/unavailable/desktop_backend.pid",
    }
    stream = io.StringIO()
    monkeypatch.setattr(entry, "promote_application_pid_record", lambda **_kwargs: False)
    monkeypatch.setattr(entry, "clear_pending_application_pid_record", lambda **_kwargs: False)

    with pytest.raises(SystemExit, match="application PID record promotion failed"):
        entry.require_application_pid_record(environ=environ, stream=stream)

    assert stream.getvalue() == (f"FLINTTRADE_BACKEND_PENDING_EXIT_ACK token={token} reason=promotion-failed\n")


@pytest.mark.unit
def test_promotion_and_pending_cleanup_share_the_record_transition_guard(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    token = "a" * 64
    record = tmp_path / "desktop_backend.pid"
    pending = f"v4\n1234\npending\n77\n{TEST_BOOT_ID}\n{token}\n"
    environ = {
        "FLINTTRADE_PARENT_PID": "77",
        "FLINTTRADE_BOOT_ID": TEST_BOOT_ID,
        "FLINTTRADE_LAUNCH_TOKEN": token,
        "FLINTTRADE_SIDECAR_RECORD_PATH": str(record),
    }
    guarded: list[Path] = []

    @contextmanager
    def record_guard(path: Path) -> Iterator[None]:
        guarded.append(path)
        yield

    monkeypatch.setattr(entry, "_record_transition_guard", record_guard)

    _write_hardened_text(record, pending)
    assert entry.promote_application_pid_record(environ=environ, pid=5678) is True
    assert guarded == [record]

    _write_hardened_text(record, pending)
    assert entry.clear_pending_application_pid_record(environ=environ) is True
    assert guarded == [record, record]


@pytest.mark.unit
def test_guardian_publishes_durable_exact_token_cleanup_proof(
    entry: ModuleType,
    tmp_path: Path,
) -> None:
    token = "a" * 64
    application_pid = 5678
    record = tmp_path / "desktop_backend.pid"
    _write_hardened_text(
        record,
        f"v4\n1234\n{application_pid}\n77\n{TEST_BOOT_ID}\n{token}\n",
    )
    environ = {
        "FLINTTRADE_PARENT_PID": "77",
        "FLINTTRADE_BOOT_ID": TEST_BOOT_ID,
        "FLINTTRADE_LAUNCH_TOKEN": token,
        "FLINTTRADE_SIDECAR_RECORD_PATH": str(record),
    }
    stream = io.StringIO()

    assert entry.publish_cleanup_complete_proof(application_pid, environ=environ, stream=stream) is True

    proof = entry._cleanup_complete_proof_path(record)
    expected = f"FLINTTRADE_BACKEND_CLEANUP_COMPLETE token={token}\n"
    assert proof.read_text(encoding="ascii") == expected
    if os.name != "nt":
        assert proof.stat().st_mode & 0o077 == 0
    assert stream.getvalue() == expected


@pytest.mark.unit
def test_guardian_refuses_cleanup_proof_for_another_record(
    entry: ModuleType,
    tmp_path: Path,
) -> None:
    token = "a" * 64
    record = tmp_path / "desktop_backend.pid"
    _write_hardened_text(
        record,
        f"v4\n1234\n9999\n77\n{TEST_BOOT_ID}\n{token}\n",
    )
    environ = {
        "FLINTTRADE_PARENT_PID": "77",
        "FLINTTRADE_BOOT_ID": TEST_BOOT_ID,
        "FLINTTRADE_LAUNCH_TOKEN": token,
        "FLINTTRADE_SIDECAR_RECORD_PATH": str(record),
    }

    assert entry.publish_cleanup_complete_proof(5678, environ=environ, stream=io.StringIO()) is False
    assert entry._cleanup_complete_proof_path(record).exists() is False


@pytest.mark.unit
@pytest.mark.skipif(os.name == "nt", reason="link fixtures require POSIX ownership semantics")
@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_record_transitions_refuse_linked_recovery_record(
    entry: ModuleType,
    tmp_path: Path,
    link_kind: str,
) -> None:
    token = "a" * 64
    payload = f"v4\n1234\npending\n77\n{TEST_BOOT_ID}\n{token}\n"
    target = tmp_path / "record-target"
    _write_hardened_text(target, payload)
    record = tmp_path / "desktop_backend.pid"
    if link_kind == "symlink":
        record.symlink_to(target)
    else:
        os.link(target, record)
    environ = {
        entry.PARENT_PID_ENV: "77",
        entry.BOOT_ID_ENV: TEST_BOOT_ID,
        entry.LAUNCH_TOKEN_ENV: token,
        entry.SIDECAR_RECORD_PATH_ENV: str(record),
    }

    assert entry.promote_application_pid_record(environ=environ, pid=5678) is False
    assert entry.clear_pending_application_pid_record(environ=environ) is False
    assert entry.publish_cleanup_complete_proof(5678, environ=environ, stream=io.StringIO()) is False
    assert target.read_text(encoding="ascii") == payload


@pytest.mark.unit
@pytest.mark.skipif(os.name == "nt", reason="link fixtures require POSIX ownership semantics")
@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_cleanup_proof_publication_refuses_linked_proof_target(
    entry: ModuleType,
    tmp_path: Path,
    link_kind: str,
) -> None:
    token = "a" * 64
    record = tmp_path / "desktop_backend.pid"
    environ = {
        entry.PARENT_PID_ENV: "77",
        entry.BOOT_ID_ENV: TEST_BOOT_ID,
        entry.LAUNCH_TOKEN_ENV: token,
        entry.SIDECAR_RECORD_PATH_ENV: str(record),
    }
    assert entry.create_pending_application_pid_record(
        environ=environ,
        guardian_pid=1234,
    ) is True
    proof = entry._cleanup_complete_proof_path(record)
    target = tmp_path / "proof-target"
    _write_hardened_text(target, "foreign proof\n")
    if link_kind == "symlink":
        proof.symlink_to(target)
    else:
        os.link(target, proof)

    assert entry.publish_cleanup_complete_proof(5678, environ=environ, stream=io.StringIO()) is False
    assert target.read_text(encoding="ascii") == "foreign proof\n"


@pytest.mark.unit
def test_guardian_needs_no_cleanup_proof_after_pending_record_was_cleared(
    entry: ModuleType,
    tmp_path: Path,
) -> None:
    environ = {"FLINTTRADE_SIDECAR_RECORD_PATH": str(tmp_path / "desktop_backend.pid")}

    assert entry._cleanup_complete_proof_required(environ) is False

    Path(environ["FLINTTRADE_SIDECAR_RECORD_PATH"]).write_text("pending", encoding="ascii")
    assert entry._cleanup_complete_proof_required(environ) is True


@pytest.mark.unit
def test_guardian_cleanup_proof_retry_is_bounded(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [0.0]
    attempts: list[int] = []
    monkeypatch.setattr(entry, "_cleanup_complete_proof_required", lambda: True)
    monkeypatch.setattr(
        entry,
        "publish_cleanup_complete_proof",
        lambda application_pid: attempts.append(application_pid) or False,
    )

    result = entry._publish_cleanup_complete_proof_with_retry(
        5678,
        timeout=2.0,
        should_stop=lambda: False,
        clock=lambda: now[0],
        sleep=lambda duration: now.__setitem__(0, now[0] + duration),
    )

    assert result is False
    assert attempts == [5678, 5678, 5678]
    assert now[0] == pytest.approx(2.0)


@pytest.mark.unit
def test_guardian_cleanup_proof_retry_honours_force_request(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[int] = []
    sleeps: list[float] = []
    monkeypatch.setattr(entry, "_cleanup_complete_proof_required", lambda: True)
    monkeypatch.setattr(
        entry,
        "publish_cleanup_complete_proof",
        lambda application_pid: attempts.append(application_pid) or False,
    )

    result = entry._publish_cleanup_complete_proof_with_retry(
        5678,
        timeout=30.0,
        should_stop=lambda: True,
        sleep=sleeps.append,
    )

    assert result is False
    assert attempts == [5678]
    assert sleeps == []


@pytest.mark.unit
def test_watchdog_off_without_env(entry: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(entry.PARENT_PID_ENV, raising=False)
    assert entry.start_parent_watchdog() is None


@pytest.mark.unit
def test_packaged_child_contract_is_published_only_for_frozen_sidecars(entry: ModuleType) -> None:
    environ: dict[str, str] = {}

    assert (
        entry.publish_packaged_child_contract(
            environ=environ,
            executable="/Applications/FlintTrade/flinttrade-backend",
            frozen=False,
        )
        is False
    )
    assert environ == {}

    assert (
        entry.publish_packaged_child_contract(
            environ=environ,
            executable="/Applications/FlintTrade/flinttrade-backend",
            frozen=True,
        )
        is True
    )
    assert environ == {
        "FLINTTRADE_PACKAGED_CHILD_EXECUTABLE": "/Applications/FlintTrade/flinttrade-backend",
        "FLINTTRADE_PACKAGED_CHILD_ARG": "--flinttrade-uploaded-strategy-child",
    }


@pytest.mark.unit
def test_packaged_child_dispatch_prevents_sidecar_reentry_and_shared_stdin(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_stdin = io.StringIO("FLINTTRADE_FORCE_EXIT\n")
    monkeypatch.setattr(entry.sys, "stdin", shared_stdin)
    for name in entry.DESKTOP_CONTROL_ENV:
        monkeypatch.setenv(name, "must-not-reach-child")
    observed: list[tuple[list[str], str, dict[str, str | None]]] = []

    def dispatch(argv: list[str]) -> bool:
        observed.append(
            (
                argv,
                entry.sys.stdin.read(),
                {name: entry.os.environ.get(name) for name in entry.DESKTOP_CONTROL_ENV},
            )
        )
        return True

    argv = ["flinttrade-backend", "--flinttrade-uploaded-strategy-child", "/tmp/strategy.py"]
    assert entry.dispatch_packaged_child_mode(argv=argv, dispatcher=dispatch) is True
    assert observed == [(argv, "", {name: None for name in entry.DESKTOP_CONTROL_ENV})]
    assert shared_stdin.tell() == 0


@pytest.mark.unit
def test_normal_sidecar_arguments_do_not_enter_packaged_child_mode(entry: ModuleType) -> None:
    assert (
        entry.dispatch_packaged_child_mode(
            argv=["flinttrade-backend", "--port", "0"],
            dispatcher=lambda _argv: pytest.fail("normal sidecar startup must not dispatch a child"),
        )
        is False
    )


@pytest.mark.unit
def test_watchdog_starts_as_daemon_thread(entry: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    # Watch a process guaranteed to outlive the assertion: this test process.
    monkeypatch.setenv(entry.PARENT_PID_ENV, str(os.getpid()))
    thread = entry.start_parent_watchdog()
    assert thread is not None
    assert thread.daemon is True
    assert thread.is_alive()
    assert thread.name == "flinttrade-parent-watchdog"


@pytest.mark.unit
def test_shutdown_coordinator_delivers_requests_before_and_after_install(entry: ModuleType) -> None:
    coordinator = entry._ShutdownCoordinator()
    calls: list[str] = []

    assert coordinator.request() is True
    assert coordinator.request() is False

    def callback() -> None:
        calls.append("shutdown")

    coordinator.install(callback)

    assert calls == ["shutdown"]
    coordinator.uninstall(callback)

    second = entry._ShutdownCoordinator()
    second.install(callback)
    assert second.request() is True
    assert second.request() is False
    assert calls == ["shutdown", "shutdown"]


@pytest.mark.unit
def test_sigterm_relay_handler_never_takes_coordinator_lock(entry: ModuleType) -> None:
    coordinator = entry._ShutdownCoordinator()
    callback_called = threading.Event()
    forwarding_started = threading.Event()

    coordinator.install(callback_called.set)

    def forward_request() -> bool:
        forwarding_started.set()
        return coordinator.request()

    relay = entry._SignalShutdownRelay(forward_request, poll_interval=0.001)
    relay_thread = relay.start()

    coordinator._lock.acquire()
    try:
        # Model SIGTERM interrupting the main thread while install/uninstall is
        # inside the coordinator's non-reentrant critical section. The handler
        # itself must return without touching that lock.
        relay.handle(signal.SIGTERM, None)
        assert forwarding_started.wait(timeout=1)
        assert callback_called.is_set() is False
    finally:
        coordinator._lock.release()

    relay_thread.join(timeout=10)
    assert relay_thread.is_alive() is False
    assert callback_called.is_set() is True


@pytest.mark.unit
def test_stdin_shutdown_command_requests_graceful_exit(entry: ModuleType) -> None:
    requested = threading.Event()
    thread = entry.start_stdin_shutdown_listener(
        requested.set,
        stream=io.StringIO(f"ignored\n{entry.SHUTDOWN_COMMAND}\n"),
    )

    thread.join(timeout=10)
    assert requested.is_set()


@pytest.mark.unit
def test_force_exit_requires_complete_owned_tree_termination(entry: ModuleType) -> None:
    exits: list[int] = []
    attempts: list[str] = []

    assert (
        entry._force_exit_owned_process_tree(
            lambda: attempts.append("terminate") or True,
            exit_process=exits.append,
        )
        is True
    )
    assert attempts == ["terminate"]
    assert exits == [1]

    exits.clear()
    assert (
        entry._force_exit_owned_process_tree(
            lambda: attempts.append("retain") or False,
            exit_process=exits.append,
        )
        is False
    )
    assert attempts == ["terminate", "retain"]
    assert exits == []

    assert entry._force_exit_owned_process_tree(None, exit_process=exits.append) is False
    assert exits == []


@pytest.mark.unit
def test_force_handler_retains_state_without_pending_proof_or_tree_containment(
    entry: ModuleType,
) -> None:
    exits: list[int] = []

    assert (
        entry._handle_force_exit(
            None,
            environ={},
            exit_process=exits.append,
        )
        is False
    )
    assert exits == []


@pytest.mark.unit
def test_posix_owned_tree_discovery_tracks_same_group_and_new_session_descendants(entry: ModuleType) -> None:
    processes = {
        100: entry._PosixProcess(pid=100, ppid=50, pgid=100, sid=50, start_token="root"),
        101: entry._PosixProcess(pid=101, ppid=100, pgid=100, sid=50, start_token="same-group"),
        102: entry._PosixProcess(pid=102, ppid=101, pgid=102, sid=102, start_token="new-session"),
        103: entry._PosixProcess(pid=103, ppid=1, pgid=102, sid=102, start_token="reparented-session-child"),
        900: entry._PosixProcess(pid=900, ppid=1, pgid=900, sid=50, start_token="foreign"),
    }

    owned = entry._discover_posix_owned_processes(
        processes,
        tracked={100: "root"},
        tracked_groups={100: "root"},
    )

    assert owned == {
        100: "root",
        101: "same-group",
        102: "new-session",
        103: "reparented-session-child",
    }

    after_session_leader_exit = {
        103: entry._PosixProcess(pid=103, ppid=1, pgid=102, sid=102, start_token="reparented-session-child"),
    }
    assert entry._discover_posix_owned_processes(
        after_session_leader_exit,
        tracked={103: "reparented-session-child"},
        tracked_groups={102: "new-session"},
    ) == {103: "reparented-session-child"}


@pytest.mark.unit
def test_macos_unique_parent_identity_recovers_descendant_after_intermediary_exit(entry: ModuleType) -> None:
    processes = {
        103: entry._PosixProcess(
            pid=103,
            ppid=1,
            pgid=103,
            sid=103,
            start_token="detached-child",
            unique_id=3003,
            parent_unique_id=2002,
        ),
    }
    owned_unique_ids = {1001, 2002}

    owned = entry._discover_posix_owned_processes(
        processes,
        tracked={},
        tracked_groups={},
        owned_unique_ids=owned_unique_ids,
    )

    assert owned == {103: "detached-child"}
    assert owned_unique_ids == {1001, 2002, 3003}


@pytest.mark.unit
def test_macos_discovery_rejects_numeric_parent_from_another_generation(entry: ModuleType) -> None:
    processes = {
        100: entry._PosixProcess(
            pid=100,
            ppid=50,
            pgid=100,
            sid=100,
            start_token="owned-generation",
            unique_id=9001,
            parent_unique_id=42,
            id_version=7,
        ),
        200: entry._PosixProcess(
            pid=200,
            ppid=100,
            pgid=200,
            sid=200,
            start_token="unrelated-generation",
            unique_id=9100,
            parent_unique_id=9099,
            id_version=8,
        ),
    }
    owned_unique_ids = {9001}

    owned = entry._discover_posix_owned_processes(
        processes,
        tracked={100: "owned-generation"},
        tracked_groups={},
        owned_unique_ids=owned_unique_ids,
    )

    assert owned == {100: "owned-generation"}
    assert owned_unique_ids == {9001}


@pytest.mark.unit
def test_posix_guardian_rejects_reused_root_and_group_identities(entry: ModuleType) -> None:
    processes = {
        100: entry._PosixProcess(pid=100, ppid=1, pgid=100, sid=100, start_token="reused-root"),
        101: entry._PosixProcess(pid=101, ppid=100, pgid=100, sid=100, start_token="foreign-child"),
    }

    assert (
        entry._discover_posix_owned_processes(
            processes,
            tracked={100: "owned-root"},
            tracked_groups={100: "owned-root"},
        )
        == {}
    )


@pytest.mark.unit
def test_posix_spawn_is_registered_before_popen_returns(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registrations: list[tuple[int, str]] = []

    class FakePopen:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.pid = 4321

    monkeypatch.setattr(entry.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(
        entry,
        "_required_posix_process_start_token",
        lambda pid, *, exited: f"start:{pid}",
    )

    restore = entry._install_posix_spawn_registration(lambda pid, start_token: registrations.append((pid, start_token)))
    try:
        process = entry.subprocess.Popen(["worker"])
        assert process.pid == 4321
        assert registrations == [(4321, "start:4321")]
    finally:
        restore()


@pytest.mark.unit
def test_posix_spawn_inherits_application_pipe_lease_with_close_fds(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    popen_kwargs: list[dict[str, object]] = []

    class FakePopen:
        def __init__(self, *_args: object, **kwargs: object) -> None:
            self.pid = 4321
            popen_kwargs.append(kwargs)

    monkeypatch.setattr(entry.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(entry, "_required_posix_process_start_token", lambda _pid, *, exited: "start:4321")

    restore = entry._install_posix_spawn_registration(
        lambda _pid, _start_token: None,
        inherited_fds=(71,),
    )
    try:
        entry.subprocess.Popen(["worker"], close_fds=False, pass_fds=(63,))
    finally:
        restore()

    assert popen_kwargs == [{"close_fds": True, "pass_fds": (63, 71)}]


@pytest.mark.unit
def test_posix_spawn_merges_pipe_lease_with_positional_popen_options(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[tuple[bool, tuple[int, ...]]] = []

    class FakePopen:
        def __init__(  # noqa: PLR0913 - mirrors subprocess.Popen's positional API
            self,
            _args: object,
            _bufsize: int = -1,
            _executable: object = None,
            _stdin: object = None,
            _stdout: object = None,
            _stderr: object = None,
            _preexec_fn: object = None,
            close_fds: bool = True,
            _shell: bool = False,
            _cwd: object = None,
            _env: object = None,
            _universal_newlines: object = None,
            _startupinfo: object = None,
            _creationflags: int = 0,
            _restore_signals: bool = True,
            _start_new_session: bool = False,
            pass_fds: tuple[int, ...] = (),
        ) -> None:
            self.pid = 4321
            received.append((close_fds, pass_fds))

    monkeypatch.setattr(entry.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(entry, "_required_posix_process_start_token", lambda _pid, *, exited: "start:4321")

    restore = entry._install_posix_spawn_registration(
        lambda _pid, _start_token: None,
        inherited_fds=(71,),
    )
    try:
        entry.subprocess.Popen(
            ["worker"],
            -1,
            None,
            None,
            None,
            None,
            None,
            False,
            False,
            None,
            None,
            None,
            None,
            0,
            True,
            False,
            (63,),
        )
    finally:
        restore()

    assert received == [(True, (63, 71))]


@pytest.mark.unit
def test_posix_spawn_that_exits_before_identity_sampling_needs_no_registration(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registrations: list[tuple[int, str]] = []

    class ExitedPopen:
        pid = 4321

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def poll(self) -> int:
            return 0

    monkeypatch.setattr(entry.subprocess, "Popen", ExitedPopen)
    monkeypatch.setattr(
        entry,
        "_required_posix_process_start_token",
        lambda _pid, *, exited: None if exited() else pytest.fail("child should be exited"),
    )

    restore = entry._install_posix_spawn_registration(lambda pid, start_token: registrations.append((pid, start_token)))
    try:
        assert entry.subprocess.Popen(["true"]).poll() == 0
        assert registrations == []
    finally:
        restore()


@pytest.mark.unit
def test_macos_pipe_lease_scanner_binds_generation_and_revalidates_endpoint(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePipeApi:
        def __init__(self) -> None:
            self.holder_pipe_reads = 0

        def list_pids(self) -> list[int]:
            return [100, 200, 300]

        def list_pipe_fds(self, pid: int) -> list[int]:
            return {100: [7], 200: [8], 300: [9]}[pid]

        def pipe_info(self, pid: int, fd: int) -> tuple[int, int] | None:
            if (pid, fd) == (200, 8):
                self.holder_pipe_reads += 1
            return {
                (100, 7): (11, 22),
                (200, 8): (22, 11),
                (300, 9): (22, 99),
            }[(pid, fd)]

        def unique_identity(self, pid: int) -> tuple[int, int]:
            return {
                200: (9001, 42),
                300: (9003, 43),
            }[pid]

    monkeypatch.setattr(entry, "_posix_process_start_token", lambda pid: f"start:{pid}")

    api = FakePipeApi()
    assert entry._macos_pipe_lease_holders(7, api=api, guardian_pid=100) == {
        200: ("start:200", 9001),
    }
    assert api.holder_pipe_reads == 2


@pytest.mark.unit
def test_macos_pipe_lease_scanner_rejects_generation_change_around_matching_endpoints(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ChangedGenerationPipeApi:
        def __init__(self) -> None:
            self.identities = iter(
                [
                    (9001, 42),
                    (9001, 42),
                    (9001, 42),
                    (9002, 99),
                ]
            )
            self.holder_pipe_reads = 0

        def list_pids(self) -> list[int]:
            return [100, 200]

        def list_pipe_fds(self, pid: int) -> list[int]:
            return {100: [7], 200: [8]}[pid]

        def pipe_info(self, pid: int, fd: int) -> tuple[int, int]:
            if (pid, fd) == (100, 7):
                return 11, 22
            self.holder_pipe_reads += 1
            return 22, 11

        def unique_identity(self, pid: int) -> tuple[int, int]:
            assert pid == 200
            return next(self.identities)

    monkeypatch.setattr(entry, "_posix_process_start_token", lambda _pid: "start:200")

    api = ChangedGenerationPipeApi()
    with pytest.raises(OSError, match="generation changed around endpoint attribution"):
        entry._macos_pipe_lease_holders(7, api=api, guardian_pid=100)
    assert api.holder_pipe_reads == 2


@pytest.mark.unit
def test_macos_pipe_lease_scanner_requires_sampled_generation_to_match_endpoint_bracket(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePipeApi:
        def list_pids(self) -> list[int]:
            return [100, 200]

        def list_pipe_fds(self, pid: int) -> list[int]:
            return {100: [7], 200: [8]}[pid]

        def pipe_info(self, pid: int, fd: int) -> tuple[int, int]:
            return (11, 22) if (pid, fd) == (100, 7) else (22, 11)

        def unique_identity(self, pid: int) -> tuple[int, int]:
            assert pid == 200
            return 9001, 42

    monkeypatch.setattr(
        entry,
        "_macos_generation_identity",
        lambda _pid, *, api: ("start:200", 9002),
    )

    with pytest.raises(OSError, match="sampled generation does not match endpoint bracket"):
        entry._macos_pipe_lease_holders(7, api=FakePipeApi(), guardian_pid=100)


@pytest.mark.unit
def test_macos_pipe_lease_scanner_rejects_pid_reuse_before_endpoint_revalidation(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ReusedPidPipeApi:
        def __init__(self) -> None:
            self.holder_pipe_reads = 0

        def list_pids(self) -> list[int]:
            return [100, 200]

        def list_pipe_fds(self, pid: int) -> list[int]:
            return {100: [7], 200: [8]}[pid]

        def pipe_info(self, pid: int, fd: int) -> tuple[int, int] | None:
            if (pid, fd) == (100, 7):
                return 11, 22
            self.holder_pipe_reads += 1
            return (22, 11) if self.holder_pipe_reads == 1 else None

        def unique_identity(self, pid: int) -> tuple[int, int]:
            assert pid == 200
            return 9002, 99

    monkeypatch.setattr(entry, "_posix_process_start_token", lambda _pid: "reused-generation")

    with pytest.raises(OSError, match="changed before endpoint revalidation"):
        entry._macos_pipe_lease_holders(7, api=ReusedPidPipeApi(), guardian_pid=100)


@pytest.mark.unit
def test_macos_pipe_lease_scanner_fails_closed_without_guardian_pipe_identity(entry: ModuleType) -> None:
    class FakePipeApi:
        def list_pids(self) -> list[int]:
            return []

        def list_pipe_fds(self, _pid: int) -> list[int]:
            return []

        def pipe_info(self, _pid: int, _fd: int) -> None:
            return None

    with pytest.raises(OSError, match="guardian pipe identity"):
        entry._macos_pipe_lease_holders(7, api=FakePipeApi(), guardian_pid=100)


@pytest.mark.unit
def test_macos_process_metadata_rejects_a_pid_generation_change(entry: ModuleType) -> None:
    before = (101, 99, 3, 2)

    assert entry._macos_unique_identity_is_stable(before, before) is True
    assert entry._macos_unique_identity_is_stable(before, (102, 99, 3, 2)) is False
    assert entry._macos_unique_identity_is_stable(before, (101, 100, 3, 2)) is False


@pytest.mark.unit
def test_macos_process_metadata_resolves_eperm_inside_stable_unique_id_bracket(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        assert kwargs == {
            "capture_output": True,
            "text": True,
            "check": False,
            "timeout": entry.POSIX_PROCESS_QUERY_TIMEOUT_SECONDS,
        }
        return subprocess.CompletedProcess(command, 0, "56290 1 56290\n", "")

    monkeypatch.setattr(entry.subprocess, "run", run)
    api_type = _macos_permission_fallback_api_type(entry, (9001, 9001))

    process = api_type().process_info(56290)

    assert process is not None
    assert (process.pid, process.ppid, process.pgid) == (56290, 1, 56290)
    assert process.start_token == "macos-unique-id:9001:7"
    assert (process.unique_id, process.parent_unique_id, process.id_version) == (9001, 42, 7)
    assert commands == [["ps", "-p", "56290", "-o", "pid=,ppid=,pgid="]]


@pytest.mark.unit
def test_macos_process_metadata_rejects_unique_id_change_around_permission_fallback(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        entry.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, "56290 1 56290\n", ""),
    )
    api_type = _macos_permission_fallback_api_type(entry, (9001, 9002))

    with pytest.raises(OSError, match="changed during permission fallback"):
        api_type().process_info(56290)


@pytest.mark.unit
def test_macos_guardian_retains_recovery_when_permission_fallback_fails(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback_attempts: list[list[str]] = []
    reaped: list[bool] = []
    clock = 0.0

    def monotonic() -> float:
        nonlocal clock
        clock += 0.05
        return clock

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        fallback_attempts.append(command)
        return subprocess.CompletedProcess(command, 1, "", "ps API failure")

    api_type = _macos_permission_fallback_api_type(entry, (9001,))
    monkeypatch.setattr(entry.sys, "platform", "darwin")
    monkeypatch.setattr(entry, "_MacosPipeLeaseApi", api_type)
    monkeypatch.setattr(entry.subprocess, "run", run)
    monkeypatch.setattr(entry, "POSIX_GUARDIAN_KILL_SECONDS", 0.25)
    monkeypatch.setattr(entry, "POSIX_GUARDIAN_POLL_SECONDS", 0.0)
    monkeypatch.setattr(entry.time, "monotonic", monotonic)
    monkeypatch.setattr(entry.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(entry, "_reap_guardian_children", lambda: reaped.append(True))

    assert entry._terminate_posix_owned_processes({}, {}) is False
    assert fallback_attempts
    assert reaped == []


@pytest.mark.unit
def test_macos_guardian_completes_with_stably_resolved_unrelated_system_process(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback_attempts: list[list[str]] = []
    reaped: list[bool] = []
    clock = 0.0

    def monotonic() -> float:
        nonlocal clock
        clock += 0.05
        return clock

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        fallback_attempts.append(command)
        return subprocess.CompletedProcess(command, 0, "56290 1 56290\n", "")

    api_type = _macos_permission_fallback_api_type(entry, (9001, 9001))
    monkeypatch.setattr(entry.sys, "platform", "darwin")
    monkeypatch.setattr(entry, "_MacosPipeLeaseApi", api_type)
    monkeypatch.setattr(entry.subprocess, "run", run)
    monkeypatch.setattr(entry, "POSIX_GUARDIAN_KILL_SECONDS", 1.0)
    monkeypatch.setattr(entry, "POSIX_GUARDIAN_POLL_SECONDS", 0.0)
    monkeypatch.setattr(entry, "POSIX_GUARDIAN_EMPTY_CONFIRM_SECONDS", 0.01)
    monkeypatch.setattr(entry.time, "monotonic", monotonic)
    monkeypatch.setattr(entry.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(entry, "_reap_guardian_children", lambda: reaped.append(True))

    assert entry._terminate_posix_owned_processes({}, {}) is True
    assert len(fallback_attempts) >= 2
    assert len(reaped) >= 2


@pytest.mark.unit
@pytest.mark.parametrize("libproc_errno", [errno.EPERM, errno.EACCES])
def test_macos_guardian_retains_recovery_for_unconfirmed_permission_failure(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    libproc_errno: int,
) -> None:
    class ProcessInfo(ctypes.Structure):
        _fields_ = [("pid", ctypes.c_int)]

    api = object.__new__(entry._MacosPipeLeaseApi)
    api._ctypes = ctypes

    def fail_process_info(*_args: object) -> int:
        ctypes.set_errno(libproc_errno)
        return 0

    api._proc_pidinfo = fail_process_info
    observed_errors: list[OSError] = []
    reaped: list[bool] = []
    clock = 0.0

    def monotonic() -> float:
        nonlocal clock
        clock += 0.05
        return clock

    def refresh(
        _tracked: dict[int, str],
        _groups: dict[int, str],
        **_kwargs: object,
    ) -> tuple[dict[int, object], dict[int, str]]:
        try:
            info = api._read_process_info(200, api.PROC_PIDTBSDINFO, ProcessInfo())
        except OSError as exc:
            observed_errors.append(exc)
            raise
        assert info is None
        return {}, {}

    monkeypatch.setattr(entry.sys, "platform", "darwin")
    monkeypatch.setattr(entry, "POSIX_GUARDIAN_KILL_SECONDS", 0.25)
    monkeypatch.setattr(entry, "POSIX_GUARDIAN_POLL_SECONDS", 0.0)
    monkeypatch.setattr(entry, "POSIX_GUARDIAN_EMPTY_CONFIRM_SECONDS", 0.01)
    monkeypatch.setattr(entry.time, "monotonic", monotonic)
    monkeypatch.setattr(entry.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(entry, "_refresh_posix_owned_processes", refresh)
    monkeypatch.setattr(entry, "_reap_guardian_children", lambda: reaped.append(True))

    assert entry._terminate_posix_owned_processes({}, {}) is False
    assert observed_errors
    assert all(error.errno == libproc_errno for error in observed_errors)
    assert reaped == []


@pytest.mark.unit
def test_macos_process_metadata_resolves_zero_errno_inside_stable_unique_id_bracket(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "56290 1 56290\n", "")

    base_api_type = _macos_permission_fallback_api_type(entry, (9001, 9001))

    class ZeroErrnoFallbackApi(base_api_type):
        def _read_process_info(self, pid: int, flavour: int, _info: object) -> object:
            class ProcessInfo(ctypes.Structure):
                _fields_ = [("pid", ctypes.c_int)]

            self._ctypes = ctypes

            def zero_byte_read(*_args: object) -> int:
                ctypes.set_errno(0)
                return 0

            self._proc_pidinfo = zero_byte_read
            return entry._MacosPipeLeaseApi._read_process_info(self, pid, flavour, ProcessInfo())

    monkeypatch.setattr(entry.subprocess, "run", run)

    process = ZeroErrnoFallbackApi().process_info(56290)

    assert process is not None
    assert (process.pid, process.ppid, process.pgid) == (56290, 1, 56290)
    assert process.start_token == "macos-unique-id:9001:7"
    assert commands == [["ps", "-p", "56290", "-o", "pid=,ppid=,pgid="]]


@pytest.mark.unit
def test_macos_process_info_treats_confirmed_esrch_as_disappeared(entry: ModuleType) -> None:
    class ProcessInfo(ctypes.Structure):
        _fields_ = [("pid", ctypes.c_int)]

    api = object.__new__(entry._MacosPipeLeaseApi)
    api._ctypes = ctypes

    def missing_process(*_args: object) -> int:
        ctypes.set_errno(errno.ESRCH)
        return 0

    api._proc_pidinfo = missing_process

    assert api._read_process_info(200, api.PROC_PIDTBSDINFO, ProcessInfo()) is None


@pytest.mark.unit
@pytest.mark.parametrize(
    ("after_start_sample", "expected_error"),
    [
        ("changed", "inconsistent process metadata"),
        ("error", "libproc failed after start-token sampling"),
    ],
)
def test_macos_refresh_binds_start_token_inside_the_libproc_generation_bracket(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    after_start_sample: str,
    expected_error: str,
) -> None:
    start_sampled = False

    class GenerationChangingMacosApi(entry._MacosPipeLeaseApi):
        def __init__(self) -> None:
            self._proc_bsd_info = object

        def list_pids(self) -> list[int]:
            return [200]

        def _read_unique_info(self, _pid: int) -> object:
            if start_sampled:
                if after_start_sample == "error":
                    raise OSError("libproc failed after start-token sampling")
                unique_id = 9002
            else:
                unique_id = 9001
            return SimpleNamespace(
                unique_id=unique_id,
                parent_unique_id=42,
                id_version=7,
                original_parent_id_version=6,
            )

        def _read_process_info(self, _pid: int, _flavour: int, _info: object) -> object:
            nonlocal start_sampled
            start_sampled = True
            return SimpleNamespace(
                pbi_pid=200,
                pbi_ppid=50,
                pbi_pgid=200,
                pbi_start_tvsec=123,
                pbi_start_tvusec=456,
            )

    monkeypatch.setattr(entry.sys, "platform", "darwin")
    monkeypatch.setattr(entry, "_MacosPipeLeaseApi", GenerationChangingMacosApi)

    with pytest.raises(OSError, match=expected_error):
        entry._refresh_posix_owned_processes({}, {}, guardian_pid=50, owned_unique_ids=set())


@pytest.mark.unit
@pytest.mark.skipif(os.name == "nt", reason="POSIX pipe lease")
def test_pipe_lease_observes_eof_only_after_every_writer_closes(entry: ModuleType) -> None:
    read_fd, write_fd = os.pipe()
    try:
        assert entry._pipe_lease_eof(read_fd) is False
        os.close(write_fd)
        write_fd = -1
        assert entry._pipe_lease_eof(read_fd) is True
    finally:
        os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)


@pytest.mark.unit
def test_macos_guardian_retains_recovery_for_live_unattributed_lease(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(entry.sys, "platform", "darwin")
    monkeypatch.setattr(entry, "POSIX_GUARDIAN_KILL_SECONDS", 0.001)
    monkeypatch.setattr(entry, "POSIX_GUARDIAN_POLL_SECONDS", 0.0)
    monkeypatch.setattr(entry, "_refresh_posix_owned_processes", lambda tracked, groups, **_kwargs: ({}, {}))
    monkeypatch.setattr(entry, "_pipe_lease_eof", lambda _fd: False)
    monkeypatch.setattr(entry, "_macos_pipe_lease_holders", lambda _fd, **_kwargs: {})

    assert entry._terminate_posix_owned_processes({}, {}, lease_read_fd=71) is False


@pytest.mark.unit
def test_macos_guardian_retains_recovery_when_libproc_scan_fails(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(entry.sys, "platform", "darwin")
    monkeypatch.setattr(entry, "POSIX_GUARDIAN_KILL_SECONDS", 0.001)
    monkeypatch.setattr(entry, "POSIX_GUARDIAN_POLL_SECONDS", 0.0)
    monkeypatch.setattr(entry, "_refresh_posix_owned_processes", lambda tracked, groups, **_kwargs: ({}, {}))
    monkeypatch.setattr(entry, "_pipe_lease_eof", lambda _fd: False)
    monkeypatch.setattr(
        entry,
        "_macos_pipe_lease_holders",
        lambda _fd, **_kwargs: (_ for _ in ()).throw(OSError("libproc unavailable")),
    )

    assert entry._terminate_posix_owned_processes({}, {}, lease_read_fd=71) is False


@pytest.mark.unit
def test_macos_guardian_refuses_generation_change_before_the_signal_sink(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = entry._PosixProcess(
        pid=200,
        ppid=50,
        pgid=200,
        sid=200,
        start_token="start:200",
        unique_id=9001,
        parent_unique_id=42,
        id_version=7,
    )
    reused = entry._PosixProcess(
        pid=200,
        ppid=1,
        pgid=200,
        sid=200,
        start_token="start:reused",
        unique_id=9002,
        parent_unique_id=99,
        id_version=8,
    )
    clock = iter([0.0, 0.0, 2.0])
    signals: list[tuple[int, signal.Signals]] = []
    exact_signal_attempts: list[tuple[int, int, signal.Signals, int]] = []

    class ReusedGenerationApi:
        def signal_process(self, pid: int, id_version: int, signum: signal.Signals) -> bool:
            assert pid == 200
            exact_signal_attempts.append((pid, id_version, signum, reused.id_version))
            return id_version == reused.id_version

    monkeypatch.setattr(entry.sys, "platform", "darwin")
    monkeypatch.setattr(entry, "POSIX_GUARDIAN_KILL_SECONDS", 1.0)
    monkeypatch.setattr(entry, "POSIX_GUARDIAN_POLL_SECONDS", 0.0)
    monkeypatch.setattr(entry.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(entry.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(entry.os, "getpid", lambda: 50)
    monkeypatch.setattr(entry.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    monkeypatch.setattr(entry, "_reap_guardian_children", lambda: None)
    monkeypatch.setattr(entry, "_MacosPipeLeaseApi", ReusedGenerationApi)
    monkeypatch.setattr(entry, "_posix_process_start_token", lambda _pid: "start:200")
    monkeypatch.setattr(
        entry,
        "_refresh_posix_owned_processes",
        lambda _tracked, _groups, **_kwargs: ({200: original}, {200: "start:200"}),
    )

    assert entry._terminate_posix_owned_processes({200: "start:200"}, {}) is False
    assert signals == []
    assert exact_signal_attempts == [(200, 7, signal.SIGKILL, 8)]


@pytest.mark.unit
def test_guardian_consumes_every_queued_registration_after_application_exit(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracked: dict[int, str] = {}
    owned_unique_ids: set[int] = set()
    reads = iter(
        [
            b"register\t321\tstart:321\t9001\nregister\t654\tstart:654\t9002\n",
            BlockingIOError(),
        ]
    )

    def read(_fd: int, _size: int) -> bytes:
        result = next(reads)
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(entry.os, "read", read)
    monkeypatch.setattr(entry, "_posix_process_start_token", lambda pid: f"start:{pid}")

    remaining, force_requested, eof, registered, error = entry._drain_posix_guardian_control(
        71,
        b"",
        tracked,
        owned_unique_ids,
    )

    assert remaining == b""
    assert force_requested is False
    assert eof is False
    assert registered is True
    assert error is None
    assert tracked == {321: "start:321", 654: "start:654"}
    assert owned_unique_ids == {9001, 9002}


@pytest.mark.unit
def test_guardian_control_drain_reports_unexpected_read_errors(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(entry.os, "read", lambda _fd, _size: (_ for _ in ()).throw(OSError("I/O failed")))

    remaining, force_requested, eof, registered, error = entry._drain_posix_guardian_control(71, b"", {}, set())

    assert remaining == b""
    assert force_requested is False
    assert eof is False
    assert registered is False
    assert isinstance(error, OSError)


@pytest.mark.unit
def test_macos_registration_identity_rejects_mixed_pid_generations(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeIdentityApi:
        def __init__(self, identities: list[tuple[int, int] | None]) -> None:
            self.identities = iter(identities)

        def unique_identity(self, _pid: int) -> tuple[int, int] | None:
            return next(self.identities)

    monkeypatch.setattr(entry, "_posix_process_start_token", lambda _pid: "start:321")

    assert entry._macos_generation_identity(321, api=FakeIdentityApi([(9001, 42), (9001, 42)])) == (
        "start:321",
        9001,
    )
    with pytest.raises(OSError, match="generation changed"):
        entry._macos_generation_identity(321, api=FakeIdentityApi([(9001, 42), (9002, 42)]))
    with pytest.raises(OSError, match="start token changed"):
        entry._macos_generation_identity(
            321,
            expected_start="start:other",
            api=FakeIdentityApi([(9001, 42), (9001, 42)]),
        )


@pytest.mark.unit
def test_guardian_requires_a_quiet_second_empty_snapshot(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refresh_calls = 0
    clock = 0.0

    def monotonic() -> float:
        nonlocal clock
        clock += 0.05
        return clock

    def refresh(tracked, groups, **_kwargs):  # noqa: ANN001
        nonlocal refresh_calls
        refresh_calls += 1
        return {}, {}

    monkeypatch.setattr(entry.time, "monotonic", monotonic)
    monkeypatch.setattr(entry.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(entry, "POSIX_GUARDIAN_KILL_SECONDS", 1.0)
    monkeypatch.setattr(entry, "POSIX_GUARDIAN_EMPTY_CONFIRM_SECONDS", 0.05)
    monkeypatch.setattr(entry, "_refresh_posix_owned_processes", refresh)

    assert entry._terminate_posix_owned_processes({}, {}) is True
    assert refresh_calls >= 2


@pytest.mark.unit
def test_posix_guardian_retains_tracked_identity_when_kernel_probe_is_transient(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processes = {
        100: entry._PosixProcess(pid=100, ppid=50, pgid=100, sid=50, start_token=""),
    }
    monkeypatch.setattr(entry, "_read_posix_process_table", lambda: processes)
    monkeypatch.setattr(
        entry,
        "_posix_process_start_token",
        lambda _pid: (_ for _ in ()).throw(OSError("transient")),
    )

    _, tracked = entry._refresh_posix_owned_processes({100: "kernel-start:1"})

    assert tracked == {100: "kernel-start:1"}


@pytest.mark.unit
def test_linux_refresh_never_attributes_reused_pid_from_stale_discovery(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    proc_root = tmp_path / "proc"

    def write_stat(pid: int, *, ppid: int, pgid: int, sid: int, start_ticks: int) -> None:
        process_dir = proc_root / str(pid)
        process_dir.mkdir(parents=True)
        fields = ["S", str(ppid), str(pgid), str(sid), *(["0"] * 15), str(start_ticks)]
        (process_dir / "stat").write_text(f"{pid} (worker with ) paren) {' '.join(fields)}\n", encoding="ascii")

    write_stat(100, ppid=50, pgid=100, sid=100, start_ticks=111)
    # PID 200 belonged to the owned tree when ps ran, but was reused by an
    # unrelated process before the old implementation sampled its start token.
    write_stat(200, ppid=1, pgid=200, sid=200, start_ticks=222)
    stale_ps = subprocess.CompletedProcess(
        args=["ps"],
        returncode=0,
        stdout="100 50 100\n200 100 100\n",
        stderr="",
    )
    starts = {
        100: "linux-start-ticks:111",
        200: "linux-start-ticks:222",
    }
    monkeypatch.setattr(entry.sys, "platform", "linux")
    monkeypatch.setattr(entry, "LINUX_PROC_ROOT", proc_root, raising=False)
    monkeypatch.setattr(entry.subprocess, "run", lambda *_args, **_kwargs: stale_ps)
    monkeypatch.setattr(entry, "_posix_process_start_token", starts.get)
    tracked_groups = {100: "linux-start-ticks:111"}

    processes, tracked = entry._refresh_posix_owned_processes(
        {100: "linux-start-ticks:111"},
        tracked_groups,
    )

    assert processes[200].ppid == 1
    assert processes[200].start_token == "linux-start-ticks:222"
    assert tracked == {100: "linux-start-ticks:111"}
    assert tracked_groups == {100: "linux-start-ticks:111"}


@pytest.mark.unit
@pytest.mark.parametrize("relationship", ["parent", "group"])
def test_linux_refresh_revalidates_relative_generation_before_discovery(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    relationship: str,
) -> None:
    proc_root = tmp_path / "proc"
    parent_stat = proc_root / "100" / "stat"
    candidate_stat = proc_root / "200" / "stat"
    parent_stat.parent.mkdir(parents=True)
    candidate_stat.parent.mkdir(parents=True)

    def stat_line(pid: int, *, ppid: int, pgid: int, sid: int, start_ticks: int) -> str:
        fields = ["S", str(ppid), str(pgid), str(sid), *(["0"] * 15), str(start_ticks)]
        return f"{pid} (worker) {' '.join(fields)}\n"

    owned_parent = stat_line(100, ppid=50, pgid=100, sid=100, start_ticks=111)
    reused_parent = stat_line(100, ppid=1, pgid=100, sid=100, start_ticks=999)
    candidate = stat_line(
        200,
        ppid=100 if relationship == "parent" else 1,
        pgid=200 if relationship == "parent" else 100,
        sid=100,
        start_ticks=222,
    )
    parent_stat.write_text(owned_parent, encoding="ascii")
    candidate_stat.write_text(candidate, encoding="ascii")
    original_read_text = Path.read_text
    parent_reads = 0

    def changing_read_text(path: Path, *args: object, **kwargs: object) -> str:
        nonlocal parent_reads
        if path == parent_stat:
            parent_reads += 1
            return owned_parent if parent_reads == 1 else reused_parent
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(entry.sys, "platform", "linux")
    monkeypatch.setattr(entry, "LINUX_PROC_ROOT", proc_root)
    monkeypatch.setattr(Path, "read_text", changing_read_text)
    monkeypatch.setattr(entry.os, "pidfd_open", lambda _pid, _flags: 71, raising=False)
    monkeypatch.setattr(entry.os, "close", lambda _fd: None)
    monkeypatch.setattr(entry.select, "select", lambda _reads, _writes, _errors, _timeout: ([], [], []))
    tracked = {100: "linux-start-ticks:111"} if relationship == "parent" else {}
    tracked_groups = {100: "linux-start-ticks:111"} if relationship == "group" else {}

    _processes, refreshed = entry._refresh_posix_owned_processes(tracked, tracked_groups)

    assert 200 not in refreshed
    assert parent_reads >= 2


@pytest.mark.unit
@pytest.mark.parametrize("relationship", ["parent", "group"])
def test_linux_refresh_accepts_only_stably_bracketed_relationships(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    relationship: str,
) -> None:
    proc_root = tmp_path / "proc"

    def write_stat(pid: int, *, ppid: int, pgid: int, sid: int, start_ticks: int) -> None:
        process_dir = proc_root / str(pid)
        process_dir.mkdir(parents=True)
        fields = ["S", str(ppid), str(pgid), str(sid), *(["0"] * 15), str(start_ticks)]
        (process_dir / "stat").write_text(f"{pid} (worker) {' '.join(fields)}\n", encoding="ascii")

    write_stat(100, ppid=50, pgid=100, sid=100, start_ticks=111)
    write_stat(
        200,
        ppid=100 if relationship == "parent" else 1,
        pgid=200 if relationship == "parent" else 100,
        sid=100,
        start_ticks=222,
    )
    monkeypatch.setattr(entry.sys, "platform", "linux")
    monkeypatch.setattr(entry, "LINUX_PROC_ROOT", proc_root)
    monkeypatch.setattr(entry.os, "pidfd_open", lambda _pid, _flags: 71, raising=False)
    monkeypatch.setattr(entry.os, "close", lambda _fd: None)
    monkeypatch.setattr(entry.select, "select", lambda _reads, _writes, _errors, _timeout: ([], [], []))
    tracked = {100: "linux-start-ticks:111"} if relationship == "parent" else {}
    tracked_groups = {100: "linux-start-ticks:111"} if relationship == "group" else {}

    _processes, refreshed = entry._refresh_posix_owned_processes(tracked, tracked_groups)

    assert refreshed[200] == "linux-start-ticks:222"


@pytest.mark.unit
def test_posix_guardian_does_not_retain_the_pre_isolation_parent_group(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processes = {
        100: entry._PosixProcess(
            pid=100,
            ppid=50,
            pgid=50,
            sid=50,
            start_token="",
        ),
        900: entry._PosixProcess(
            pid=900,
            ppid=1,
            pgid=50,
            sid=50,
            start_token="",
        ),
    }
    tracked_groups = {100: "start:100"}
    monkeypatch.setattr(entry, "_read_posix_process_table", lambda: processes)
    monkeypatch.setattr(entry.os, "getpid", lambda: 50)
    monkeypatch.setattr(entry, "_posix_process_start_token", lambda pid: f"start:{pid}")

    _, tracked = entry._refresh_posix_owned_processes(
        {},
        tracked_groups,
        guardian_pid=50,
    )

    assert tracked == {100: "start:100"}
    assert tracked_groups == {}
    assert entry._discover_posix_owned_processes(
        processes,
        tracked=tracked,
        guardian_pid=50,
        tracked_groups=tracked_groups,
    ) == {100: "start:100"}


@pytest.mark.unit
def test_windows_owned_tree_uses_a_kill_on_close_job(entry: ModuleType) -> None:
    calls: list[object] = []

    class FakeJobApi:
        def create_job(self) -> int:
            calls.append("create")
            return 99

        def enable_kill_on_close(self, handle: int) -> bool:
            calls.append(("kill-on-close", handle))
            return True

        def assign_current_process(self, handle: int) -> bool:
            calls.append(("assign", handle))
            return True

        def close_handle(self, handle: int) -> bool:
            calls.append(("close", handle))
            return True

    terminator = entry._prepare_windows_owned_process_tree(api=FakeJobApi())

    assert terminator is not None
    assert calls == ["create", ("kill-on-close", 99), ("assign", 99)]
    assert terminator() is True
    assert calls[-1] == ("close", 99)


@pytest.mark.unit
def test_windows_job_setup_fails_closed_and_releases_unassigned_handle(entry: ModuleType) -> None:
    calls: list[object] = []

    class FailingJobApi:
        def create_job(self) -> int:
            return 99

        def enable_kill_on_close(self, handle: int) -> bool:
            calls.append(("kill-on-close", handle))
            return False

        def assign_current_process(self, _handle: int) -> bool:
            pytest.fail("an unconfigured job must not receive the process")

        def close_handle(self, handle: int) -> bool:
            calls.append(("close", handle))
            return True

    assert entry._prepare_windows_owned_process_tree(api=FailingJobApi()) is None
    assert calls == [("kill-on-close", 99), ("close", 99)]


@pytest.mark.unit
def test_windows_liveness_uses_a_non_destructive_process_handle(entry: ModuleType) -> None:
    calls: list[object] = []

    class FakeProcessApi:
        def open_process_for_wait(self, pid: int) -> int:
            calls.append(("open", pid))
            return 99

        def wait_for_exit(self, handle: int) -> bool:
            calls.append(("wait", handle))
            return False

        def close_handle(self, handle: int) -> None:
            calls.append(("close", handle))

    assert entry._windows_pid_alive(4321, api=FakeProcessApi()) is True
    assert calls == [("open", 4321), ("wait", 99), ("close", 99)]


@pytest.mark.unit
def test_stdin_force_exit_targets_the_complete_owned_process_tree(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested = threading.Event()
    exit_codes: list[int] = []
    tree_terminations: list[str] = []
    monkeypatch.setattr(entry.os, "_exit", exit_codes.append)

    thread = entry.start_stdin_shutdown_listener(
        requested.set,
        stream=io.StringIO("FLINTTRADE_FORCE_EXIT\n"),
        terminate_owned_tree=lambda: tree_terminations.append("terminate") or True,
    )

    thread.join(timeout=10)
    assert tree_terminations == ["terminate"]
    assert exit_codes == [1]
    assert requested.is_set() is False


@pytest.mark.unit
def test_pending_force_exit_clears_exact_record_and_acknowledges_before_exit(
    entry: ModuleType,
    tmp_path: Path,
) -> None:
    token = "a" * 64
    record = tmp_path / "desktop_backend.pid"
    _write_hardened_text(record, f"v4\n1234\npending\n77\n{TEST_BOOT_ID}\n{token}\n")
    environ = {
        "FLINTTRADE_PARENT_PID": "77",
        "FLINTTRADE_BOOT_ID": TEST_BOOT_ID,
        "FLINTTRADE_LAUNCH_TOKEN": token,
        "FLINTTRADE_SIDECAR_RECORD_PATH": str(record),
    }
    stream = io.StringIO()
    exits: list[int] = []

    assert (
        entry._handle_force_exit(
            lambda: pytest.fail("a pre-import pending application has no backend tree to terminate"),
            environ=environ,
            stream=stream,
            exit_process=exits.append,
        )
        is True
    )

    assert record.exists() is False
    assert stream.getvalue() == f"FLINTTRADE_BACKEND_PENDING_EXIT_ACK token={token} reason=force-exit\n"
    assert exits == [1]


@pytest.mark.unit
def test_stdin_listener_keeps_force_fallback_after_graceful_request(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested = threading.Event()
    exit_codes: list[int] = []
    monkeypatch.setattr(entry.os, "_exit", exit_codes.append)

    thread = entry.start_stdin_shutdown_listener(
        requested.set,
        stream=io.StringIO(f"{entry.SHUTDOWN_COMMAND}\n{entry.FORCE_EXIT_COMMAND}\n"),
        terminate_owned_tree=lambda: True,
    )

    thread.join(timeout=10)
    assert requested.is_set() is True
    assert exit_codes == [1]


@pytest.mark.unit
def test_stdin_eof_requests_graceful_exit_for_a_dead_parent(entry: ModuleType) -> None:
    requested = threading.Event()
    thread = entry.start_stdin_shutdown_listener(requested.set, stream=io.StringIO(""))

    thread.join(timeout=10)
    assert requested.is_set()


@pytest.mark.unit
def test_exit_orphaned_survives_a_broken_shell_stdio_pipe(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dead shell's broken stderr pipe must never abort the orphan shutdown.

    The announcement print at the top of ``_exit_orphaned`` used to raise
    ``BrokenPipeError`` (the shell owned the pipe's read end), killing the
    watchdog thread before the graceful request or force-exit timer were
    armed — the backend tree then outlived its shell indefinitely.
    """

    class BrokenPipe(io.TextIOBase):
        def write(self, _text: str) -> int:
            raise BrokenPipeError(32, "Broken pipe")

        def flush(self) -> None:
            raise BrokenPipeError(32, "Broken pipe")

    # Keep the test's own stdio intact: neutralise the fd-level detach and
    # poison only the module's view of stderr.
    monkeypatch.setattr(entry, "_detach_broken_shell_stdio", lambda: None)
    monkeypatch.setattr(entry.sys, "stderr", BrokenPipe())
    armed: list[str] = []
    monkeypatch.setattr(
        entry.threading,
        "Thread",
        lambda *args, **kwargs: type(
            "T", (), {"start": lambda self: armed.append(kwargs.get("name", ""))}
        )(),
    )

    requested: list[bool] = []
    entry._exit_orphaned(lambda: requested.append(True), lambda: True)

    assert requested == [True]
    assert armed == ["flinttrade-orphan-shutdown-fallback"]


@pytest.mark.unit
def test_stdin_eof_uses_orphan_tree_fallback(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def request_shutdown() -> None:
        pass

    def terminate_owned_tree() -> bool:
        return True

    orphaned: list[tuple[object, object]] = []
    monkeypatch.setattr(
        entry,
        "_exit_orphaned",
        lambda request, terminate_tree: orphaned.append((request, terminate_tree)),
    )

    thread = entry.start_stdin_shutdown_listener(
        request_shutdown,
        stream=io.StringIO(""),
        terminate_owned_tree=terminate_owned_tree,
    )

    thread.join(timeout=10)
    assert orphaned == [(request_shutdown, terminate_owned_tree)]


@pytest.mark.unit
@pytest.mark.skipif(os.name == "nt", reason="POSIX liveness checks")
def test_posix_parent_alive_probes(entry: ModuleType) -> None:
    # kill(pid, 0) path: this process is alive.
    assert entry._posix_parent_alive(os.getpid(), track_reparent=False) is True
    # A freshly reaped child PID reads as dead.
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    assert entry._posix_parent_alive(child.pid, track_reparent=False) is False
    # Reparent tracking: our real parent matches; an unrelated PID does not.
    assert entry._posix_parent_alive(os.getppid(), track_reparent=True) is True
    assert entry._posix_parent_alive(os.getpid(), track_reparent=True) is False


@pytest.mark.unit
def test_posix_parent_identity_rejects_shell_pid_reuse_in_pyinstaller_topology(
    entry: ModuleType,
) -> None:
    original = "/Applications/FlintTrade.app/Contents/MacOS/FlintTrade\t77\tFri Jul 11 10:11:12 2026"
    reused = "/usr/bin/python3 unrelated.py\t77\tFri Jul 11 10:11:13 2026"

    assert (
        entry._posix_parent_alive(
            77,
            track_reparent=False,
            expected_identity=original,
            identity_lookup=lambda _pid: original,
        )
        is True
    )
    assert (
        entry._posix_parent_alive(
            77,
            track_reparent=False,
            expected_identity=original,
            identity_lookup=lambda _pid: reused,
        )
        is False
    )


@pytest.mark.unit
def test_posix_parent_identity_fails_closed_without_a_kernel_identity(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        entry.os,
        "kill",
        lambda *_args: pytest.fail("PID-only fallback must not run after identity was required"),
    )

    assert (
        entry._posix_parent_alive(
            77,
            track_reparent=False,
            expected_identity="/Applications/FlintTrade\t77\tmacos-start-time:100:1",
            identity_lookup=lambda _pid: None,
        )
        is False
    )


@pytest.mark.unit
def test_posix_parent_identity_parser_matches_rust_process_identity(entry: ModuleType) -> None:
    output = "77 /Applications/FlintTrade.app/Contents/MacOS/FlintTrade --runtime-flag"

    assert entry._parse_posix_process_identity(output, 77, "kernel-start:123456789") == (
        "/Applications/FlintTrade.app/Contents/MacOS/FlintTrade --runtime-flag\t77\tkernel-start:123456789"
    )
    assert entry._parse_posix_process_identity(output, 88, "kernel-start:123456789") is None
    assert entry._parse_posix_process_identity("", 77, "kernel-start:123456789") is None


@pytest.mark.unit
def test_posix_parent_identity_uses_rust_native_command_contract(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    starts = iter(("macos-start-time:100:1", "macos-start-time:100:1"))
    monkeypatch.setattr(entry, "_posix_process_start_token", lambda _pid: next(starts))
    monkeypatch.setattr(
        entry,
        "_posix_process_command",
        lambda pid: "/Applications/FlintTrade.app/Contents/MacOS/flinttrade" if pid == 77 else None,
    )

    assert entry._posix_process_identity(77) == (
        "/Applications/FlintTrade.app/Contents/MacOS/flinttrade\t77\tmacos-start-time:100:1"
    )


@pytest.mark.unit
def test_posix_identity_distinguishes_reuse_within_the_same_wall_clock_second(entry: ModuleType) -> None:
    output = "77 /Applications/FlintTrade.app/Contents/MacOS/FlintTrade"

    first = entry._parse_posix_process_identity(output, 77, "kernel-start:1000001")
    reused = entry._parse_posix_process_identity(output, 77, "kernel-start:1000002")

    assert first != reused


@pytest.mark.unit
@pytest.mark.skipif(os.name == "nt", reason="POSIX process probes")
def test_posix_process_table_fails_closed_on_ps_timeout(entry: ModuleType) -> None:
    def timeout(command, **kwargs):  # noqa: ANN001
        assert kwargs["timeout"] == entry.POSIX_PROCESS_QUERY_TIMEOUT_SECONDS
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    with pytest.raises(OSError, match="process-tree query timed out"):
        entry._read_posix_process_table(run=timeout)


@pytest.mark.unit
def test_posix_process_identity_fails_closed_on_native_command_error(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(entry, "_posix_process_start_token", lambda _pid: "start:1")
    monkeypatch.setattr(
        entry,
        "_posix_process_command",
        lambda _pid: (_ for _ in ()).throw(OSError("native lookup failed")),
    )

    with pytest.raises(OSError, match="native lookup failed"):
        entry._posix_process_identity(77)


@pytest.mark.integration
@pytest.mark.skipif(os.name == "nt", reason="POSIX kernel process identity")
def test_posix_process_identity_is_stable_and_uses_a_kernel_start_token(entry: ModuleType) -> None:
    first = entry._posix_process_identity(os.getpid())
    second = entry._posix_process_identity(os.getpid())

    assert first == second
    assert first is not None
    command, pid, start_token = first.rsplit("\t", 2)
    assert command
    assert pid == str(os.getpid())
    assert start_token.startswith(("linux-start-ticks:", "macos-start-time:"))


@pytest.mark.unit
def test_posix_watcher_returns_after_first_orphan_request(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, object]] = []
    request_shutdown = object()
    terminate_owned_tree = object()

    monkeypatch.setattr(entry.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(entry, "_posix_parent_alive", lambda *_args, **_kwargs: False)

    def exit_once(request: object, terminate_tree: object) -> None:
        calls.append((request, terminate_tree))
        if len(calls) > 1:
            raise AssertionError("watcher requested orphan shutdown more than once")

    monkeypatch.setattr(entry, "_exit_orphaned", exit_once)

    entry._watch_parent_posix(1234, request_shutdown, terminate_owned_tree)

    assert calls == [(request_shutdown, terminate_owned_tree)]


@pytest.mark.unit
def test_posix_watcher_polls_the_spawn_time_shell_identity_for_pyinstaller_child(
    entry: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell_identity = "/Applications/FlintTrade.app/Contents/MacOS/FlintTrade\t77\tstable-start"
    probes: list[tuple[int, bool, str | None]] = []
    orphaned: list[object] = []
    request_shutdown = object()

    monkeypatch.setattr(entry.os, "getppid", lambda: 1234)
    monkeypatch.setattr(entry.time, "sleep", lambda _seconds: None)

    def parent_alive(
        pid: int,
        *,
        track_reparent: bool,
        expected_identity: str | None = None,
        **_kwargs: object,
    ) -> bool:
        probes.append((pid, track_reparent, expected_identity))
        return False

    monkeypatch.setattr(entry, "_posix_parent_alive", parent_alive)
    monkeypatch.setattr(entry, "_exit_orphaned", lambda request, _tree: orphaned.append(request))

    entry._watch_parent_posix(77, request_shutdown, parent_identity=shell_identity)

    assert probes == [(77, False, shell_identity)]
    assert orphaned == [request_shutdown]


@pytest.mark.integration
@pytest.mark.skipif(os.name == "nt", reason="POSIX orphan scenario")
def test_sidecar_exits_when_parent_dies(tmp_path: Path, serial_posix_guardian: None) -> None:
    """End-to-end orphan drill: shell dies -> watchdog exits the sidecar.

    A throwaway "shell" process spawns a "sidecar" (this entry script's
    watchdog + a long sleep) with FLINTTRADE_PARENT_PID set to itself, then
    exits. The sidecar must notice and exit on its own within the poll window.
    """
    sidecar_script = textwrap.dedent(
        f"""
        import importlib.util, time
        spec = importlib.util.spec_from_file_location("desktop_backend_entry", {str(ENTRY_SCRIPT)!r})
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.POLL_INTERVAL_SECONDS = 0.1
        terminate_owned_tree = mod._prepare_owned_process_tree()
        assert terminate_owned_tree is not None
        assert mod.start_parent_watchdog(terminate_owned_tree=terminate_owned_tree) is not None
        print("SIDECAR_READY", flush=True)
        time.sleep(60)  # the watchdog must exit us long before this
        """
    )
    shell_script = textwrap.dedent(
        f"""
        import os, subprocess, sys
        env = dict(os.environ)
        env["FLINTTRADE_PARENT_PID"] = str(os.getpid())
        child = subprocess.Popen(
            [sys.executable, "-c", {sidecar_script!r}],
            env=env,
            stdout=subprocess.PIPE,
            text=True,
        )
        line = child.stdout.readline()
        assert "SIDECAR_READY" in line, line
        print(child.pid, flush=True)
        os._exit(0)  # simulate a shell crash: no cleanup, no child kill
        """
    )
    out = subprocess.run(
        [sys.executable, "-c", shell_script],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    sidecar_pid = int(out.stdout.strip().splitlines()[-1])

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            os.kill(sidecar_pid, 0)
        except ProcessLookupError:
            return  # orphaned sidecar exited cleanly
        time.sleep(0.1)
    os.kill(sidecar_pid, 9)  # do not leak the process on failure
    pytest.fail("orphaned sidecar was still alive 10s after its shell died")


@pytest.mark.integration
@pytest.mark.skipif(os.name == "nt", reason="POSIX process-tree containment")
def test_posix_application_identity_is_published_after_group_isolation(serial_posix_guardian: None) -> None:
    script = textwrap.dedent(
        f"""
        import importlib.util, os
        spec = importlib.util.spec_from_file_location("desktop_backend_entry", {str(ENTRY_SCRIPT)!r})
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        def publish_identity():
            print(f"PUBLISH {{os.getpid()}} {{os.getpgrp()}}", flush=True)

        terminate_owned_tree = mod._prepare_owned_process_tree(publish_identity)
        assert terminate_owned_tree is not None
        print(f"ISOLATED {{os.getpid()}} {{os.getpgrp()}}", flush=True)
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    publish_line, isolated_line = completed.stdout.strip().splitlines()[-2:]
    _, publish_pid, publish_group = publish_line.split()
    _, isolated_pid, isolated_group = isolated_line.split()

    assert publish_pid == isolated_pid
    assert publish_pid == publish_group
    assert isolated_pid == isolated_group


@pytest.mark.integration
@pytest.mark.skipif(os.name == "nt", reason="POSIX process-tree containment")
def test_posix_guardian_outlives_leader_and_reaps_same_group_and_new_session_descendants(
    entry: ModuleType,
    serial_posix_guardian: None,
) -> None:
    """Crash the Python leader after spawning descendants in two POSIX sessions."""
    script = textwrap.dedent(
        f"""
        import importlib.util, os, subprocess, sys, time
        spec = importlib.util.spec_from_file_location("desktop_backend_entry", {str(ENTRY_SCRIPT)!r})
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.POSIX_GUARDIAN_POLL_SECONDS = 0.01
        terminate_owned_tree = mod._prepare_owned_process_tree()
        assert terminate_owned_tree is not None
        same_group = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        new_session = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        print(os.getpid(), same_group.pid, new_session.pid, flush=True)
        os._exit(23)
        """
    )
    guardian = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    descendant_pids: list[int] = []
    try:
        stdout, stderr = guardian.communicate(timeout=POSIX_GUARDIAN_DRILL_TIMEOUT_SECONDS)
        assert guardian.returncode == 23, stderr
        leader_pid, same_group_pid, new_session_pid = (int(value) for value in stdout.strip().splitlines()[-1].split())
        descendant_pids = [same_group_pid, new_session_pid]
        assert leader_pid != guardian.pid

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if all(not entry._posix_pid_alive(pid) for pid in descendant_pids):
                break
            time.sleep(0.05)
        assert all(not entry._posix_pid_alive(pid) for pid in descendant_pids)
    finally:
        if guardian.poll() is None:
            guardian.kill()
            guardian.wait(timeout=5)
        for pid in descendant_pids:
            if entry._posix_pid_alive(pid):
                os.kill(pid, signal.SIGKILL)


@pytest.mark.integration
@pytest.mark.skipif(sys.platform != "darwin", reason="macOS daemon containment")
def test_macos_guardian_reaps_rapid_daemon_after_intermediary_exits(
    entry: ModuleType,
    tmp_path: Path,
    serial_posix_guardian: None,
) -> None:
    daemon_pid_path = tmp_path / "daemon.pid"
    daemon_code = textwrap.dedent(
        f"""
        import os, pathlib, time
        child_pid = os.fork()
        if child_pid:
            os._exit(0)
        os.setsid()
        pathlib.Path({str(daemon_pid_path)!r}).write_text(str(os.getpid()), encoding="utf-8")
        time.sleep(60)
        """
    )
    script = textwrap.dedent(
        f"""
        import importlib.util, os, pathlib, subprocess, sys, time
        spec = importlib.util.spec_from_file_location("desktop_backend_entry", {str(ENTRY_SCRIPT)!r})
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.POSIX_GUARDIAN_POLL_SECONDS = 0.01
        terminate_owned_tree = mod._prepare_owned_process_tree()
        assert terminate_owned_tree is not None
        intermediary = subprocess.Popen(
            [sys.executable, "-c", {daemon_code!r}],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        intermediary.wait(timeout=2)
        marker = pathlib.Path({str(daemon_pid_path)!r})
        deadline = time.monotonic() + 2
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists()
        print(marker.read_text(encoding="utf-8"), flush=True)
        os._exit(24)
        """
    )
    guardian = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    daemon_pid = 0
    try:
        stdout, stderr = guardian.communicate(timeout=POSIX_GUARDIAN_DRILL_TIMEOUT_SECONDS)
        assert guardian.returncode == 24, stderr
        daemon_pid = int(stdout.strip().splitlines()[-1])
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and entry._posix_pid_alive(daemon_pid):
            time.sleep(0.05)
        assert not entry._posix_pid_alive(daemon_pid)
    finally:
        if guardian.poll() is None:
            guardian.kill()
            guardian.wait(timeout=5)
        if daemon_pid and entry._posix_pid_alive(daemon_pid):
            os.kill(daemon_pid, signal.SIGKILL)


@pytest.mark.integration
@pytest.mark.skipif(sys.platform != "darwin", reason="macOS unique-parent containment")
def test_macos_guardian_reaps_detached_close_fds_grandchild(
    entry: ModuleType,
    tmp_path: Path,
    serial_posix_guardian: None,
) -> None:
    daemon_pid_path = tmp_path / "close-fds-daemon.pid"
    daemon_code = textwrap.dedent(
        f"""
        import pathlib, subprocess, sys
        sys.stdin.buffer.read(1)
        daemon = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
        pathlib.Path({str(daemon_pid_path)!r}).write_text(str(daemon.pid), encoding="utf-8")
        """
    )
    script = textwrap.dedent(
        f"""
        import importlib.util, os, pathlib, subprocess, sys, time
        spec = importlib.util.spec_from_file_location("desktop_backend_entry", {str(ENTRY_SCRIPT)!r})
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.POSIX_GUARDIAN_POLL_SECONDS = 0.01
        terminate_owned_tree = mod._prepare_owned_process_tree()
        assert terminate_owned_tree is not None
        intermediary = subprocess.Popen(
            [sys.executable, "-c", {daemon_code!r}],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        assert intermediary.stdin is not None
        intermediary.stdin.write(b"x")
        intermediary.stdin.close()
        intermediary.wait(timeout=2)
        marker = pathlib.Path({str(daemon_pid_path)!r})
        deadline = time.monotonic() + 2
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists()
        print(marker.read_text(encoding="utf-8"), flush=True)
        os._exit(25)
        """
    )
    guardian = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    daemon_pid = 0
    try:
        stdout, stderr = guardian.communicate(timeout=POSIX_GUARDIAN_DRILL_TIMEOUT_SECONDS)
        assert guardian.returncode == 25, stderr
        daemon_pid = int(stdout.strip().splitlines()[-1])
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and entry._posix_pid_alive(daemon_pid):
            time.sleep(0.05)
        assert not entry._posix_pid_alive(daemon_pid)
    finally:
        if guardian.poll() is None:
            guardian.kill()
            guardian.wait(timeout=5)
        if daemon_pid and entry._posix_pid_alive(daemon_pid):
            os.kill(daemon_pid, signal.SIGKILL)


@pytest.mark.integration
@pytest.mark.skipif(sys.platform != "darwin", reason="macOS guardian polling")
def test_macos_idle_guardian_uses_adaptive_process_reconciliation(
    tmp_path: Path,
    serial_posix_guardian: None,
) -> None:
    scan_path = tmp_path / "guardian-scans.log"
    script = textwrap.dedent(
        f"""
        import importlib.util, os, pathlib, time
        spec = importlib.util.spec_from_file_location("desktop_backend_entry", {str(ENTRY_SCRIPT)!r})
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        original_refresh = mod._refresh_posix_owned_processes
        marker = pathlib.Path({str(scan_path)!r})
        def counted_refresh(*args, **kwargs):
            descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(descriptor, b"scan\\n")
            finally:
                os.close(descriptor)
            return original_refresh(*args, **kwargs)
        mod._refresh_posix_owned_processes = counted_refresh
        mod.POSIX_GUARDIAN_POLL_SECONDS = 0.01
        terminate_owned_tree = mod._prepare_owned_process_tree()
        assert terminate_owned_tree is not None
        time.sleep(0.3)
        active_scans = marker.read_text(encoding="utf-8").count("scan")
        print(f"ACTIVE_SCANS {{active_scans}}", flush=True)
        os._exit(0)
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
        check=True,
    )

    assert completed.returncode == 0
    active_scans = int(completed.stdout.strip().split()[-1])
    total_scans = len(scan_path.read_text(encoding="utf-8").splitlines())
    assert active_scans <= 2
    assert active_scans <= total_scans <= active_scans + 20


@pytest.mark.integration
@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object containment")
def test_windows_job_kills_descendant_when_python_leader_exits(entry: ModuleType) -> None:
    script = textwrap.dedent(
        f"""
        import importlib.util, os, subprocess, sys
        spec = importlib.util.spec_from_file_location("desktop_backend_entry", {str(ENTRY_SCRIPT)!r})
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod._prepare_owned_process_tree() is not None
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(child.pid, flush=True)
        os._exit(0)
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    descendant_pid = int(completed.stdout.strip().splitlines()[-1])

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and entry._windows_pid_alive(descendant_pid):
        time.sleep(0.05)
    assert entry._windows_pid_alive(descendant_pid) is False
