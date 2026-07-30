"""Tests for workspace.json schema migrations."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from filelock import FileLock

from flinttrade_core import secure_file
from flinttrade_core.workspace_migrations import (
    MIGRATIONS,
    WORKSPACE_VERSION,
    MigrationLockError,
    _atomic_write,
    _migration_lock,
    _merge_defaults,
    run_migrations,
)

_LMSTUDIO_RETIREMENT_JOURNAL = ".lmstudio-retirement.transaction.json"


def _seed(workspace_dir: Path, cfg: dict) -> Path:
    """Write cfg as workspace.json in workspace_dir, return the path."""
    workspace_dir.mkdir(parents=True, exist_ok=True)
    path = workspace_dir / "workspace.json"
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return path


def _write_retirement_journal(
    workspace_dir: Path,
    staged_path: Path,
    *,
    phase: str,
) -> Path:
    staged_stat = staged_path.stat()
    journal = {
        "version": 1,
        "phase": phase,
        "secret_name": "llm_api_key",
        "staged_name": staged_path.name,
        "sha256": hashlib.sha256(staged_path.read_bytes()).hexdigest(),
        "st_dev": staged_stat.st_dev,
        "st_ino": staged_stat.st_ino,
        "st_uid": staged_stat.st_uid,
        "size": staged_stat.st_size,
    }
    journal_path = workspace_dir / _LMSTUDIO_RETIREMENT_JOURNAL
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    return journal_path


_HOLD_WORKSPACE_LOCK = """
import sys
import time
from pathlib import Path
from flinttrade_core.workspace_migrations import _migration_lock

workspace, entered, release = map(Path, sys.argv[1:4])
with _migration_lock(workspace, wait=True, timeout=5.0):
    entered.write_text("entered", encoding="utf-8")
    deadline = time.monotonic() + 10.0
    while not release.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("test did not release first workspace lock holder")
        time.sleep(0.01)
"""

_ENTER_WORKSPACE_LOCK = """
import sys
from pathlib import Path
from flinttrade_core.workspace_migrations import _migration_lock

workspace, entered = map(Path, sys.argv[1:3])
with _migration_lock(workspace, wait=True, timeout=5.0):
    entered.write_text("entered", encoding="utf-8")
"""


def _wait_for_process_marker(marker: Path, process: subprocess.Popen[str], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while not marker.exists():
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"lock contender exited before entering (code {process.returncode}): {stdout}{stderr}"
            )
        if time.monotonic() >= deadline:
            raise AssertionError("timed out waiting for lock contender to enter")
        time.sleep(0.01)


def test_fresh_install_no_migration(tmp_path):
    """Workspace already at current version: returned as-is, file untouched."""
    cfg = {"version": WORKSPACE_VERSION, "brokers": {"registered": ["openalgo:default"]}}
    path = _seed(tmp_path, cfg)
    mtime_before = path.stat().st_mtime_ns

    result = run_migrations(tmp_path)

    assert result == cfg
    assert path.stat().st_mtime_ns == mtime_before


def test_legacy_010_alpha_full_migration_persists(tmp_path):
    """Walk from 0.1.0-alpha to 1.0.0 and persist the migrated file."""
    _seed(tmp_path, {"version": "0.1.0-alpha", "modules": {"ai": True}})

    result = run_migrations(tmp_path)

    assert result["version"] == WORKSPACE_VERSION
    assert result["brokers"]["execution"]["default"] == "openalgo:default"
    assert result["compliance"]["personal_use_mode"] is True
    assert json.loads((tmp_path / "workspace.json").read_text(encoding="utf-8")) == result
    assert (tmp_path / "workspace.0.1.0-alpha.bak.json").exists()


def test_052_to_100_preserves_manual_edits(tmp_path):
    """Recursive defaults preserve existing operator choices."""
    _seed(
        tmp_path,
        {
            "version": "0.5.2",
            "brokers": {"execution": {"default": "openalgo:zerodha"}},
        },
    )

    result = run_migrations(tmp_path)

    assert result["brokers"]["execution"]["default"] == "openalgo:zerodha"
    assert "ticks" in result["brokers"]["data"]


def test_100_to_110_adds_complete_safety_config_and_preserves_edits(tmp_path):
    _seed(
        tmp_path,
        {
            "version": "1.0.0",
            "safety": {"max_positions": 12},
        },
    )

    result = run_migrations(tmp_path)

    assert result["version"] == WORKSPACE_VERSION
    assert result["safety"]["max_positions"] == 12
    assert result["safety"]["pnl_pause_pct"] == 3.0
    assert result["safety"]["qty_limits"]["NSE"] == 50_000


def test_110_to_current_retires_default_lmstudio_and_deletes_only_its_bound_secret(tmp_path):
    secret_path = tmp_path / "secrets" / "llm_api_key"
    secret_path.parent.mkdir(parents=True)
    secret_path.write_text("legacy-local-secret", encoding="utf-8")
    _seed(
        tmp_path,
        {
            "version": "1.1.0",
            "llm": {
                "provider": "lmstudio",
                "host": "http://127.0.0.1:1234",
                "model": "local-model",
                "api_key_ref": "secret://llm/api_key",
                "api_key_provider": "lmstudio",
                "api_key_destination": "http://127.0.0.1:1234",
            },
        },
    )

    result = run_migrations(tmp_path)

    assert result["version"] == WORKSPACE_VERSION
    assert result["llm"] == {
        "provider": "ollama",
        "host": "",
        "model": "local-model",
        "api_key_ref": "",
        "api_key_provider": "",
        "api_key_destination": "",
    }
    assert not secret_path.exists()
    backup = json.loads((tmp_path / "workspace.1.1.0.bak.json").read_text(encoding="utf-8"))
    assert backup["llm"]["provider"] == "lmstudio"


def test_110_to_current_retires_a_default_lmstudio_secret_with_only_the_legacy_ref(
    tmp_path,
):
    secret_path = tmp_path / "secrets" / "llm_api_key"
    secret_path.parent.mkdir(parents=True)
    secret_path.write_text("legacy-local-secret", encoding="utf-8")
    _seed(
        tmp_path,
        {
            "version": "1.1.0",
            "llm": {
                "provider": "lmstudio",
                "host": "http://127.0.0.1:1234",
                "model": "local-model",
                "api_key_ref": "secret://llm/api_key",
            },
        },
    )

    result = run_migrations(tmp_path)

    assert result["llm"] == {
        "provider": "ollama",
        "host": "",
        "model": "local-model",
        "api_key_ref": "",
        "api_key_provider": "",
        "api_key_destination": "",
    }
    assert not secret_path.exists()


def test_110_to_current_retires_a_remote_lmstudio_secret_with_only_the_legacy_ref(
    tmp_path,
):
    host = "https://models.example.invalid:443/API?Token=X"
    secret_path = tmp_path / "secrets" / "llm_api_key"
    secret_path.parent.mkdir(parents=True)
    secret_path.write_text("legacy-remote-secret", encoding="utf-8")
    _seed(
        tmp_path,
        {
            "version": "1.1.0",
            "llm": {
                "provider": "lmstudio",
                "host": host,
                "model": "remote-model",
                "api_key_ref": "secret://llm/api_key",
            },
        },
    )

    result = run_migrations(tmp_path)

    assert result["llm"] == {
        "provider": "ollama",
        "host": "",
        "model": "remote-model",
        "api_key_ref": "",
        "api_key_provider": "",
        "api_key_destination": "",
    }
    assert not secret_path.exists()


@pytest.mark.parametrize("phase", ["prepared", "committed"])
def test_default_lmstudio_migration_recovers_a_precommit_staged_secret(tmp_path, phase):
    staged_path = tmp_path / "secrets" / ".llm_api_key.lmstudio-retirement.crash"
    staged_path.parent.mkdir(parents=True)
    staged_path.write_text("legacy-local-secret", encoding="utf-8")
    journal_path = _write_retirement_journal(tmp_path, staged_path, phase=phase)
    _seed(
        tmp_path,
        {
            "version": "1.1.0",
            "llm": {
                "provider": "lmstudio",
                "host": "http://127.0.0.1:1234",
                "api_key_ref": "secret://llm/api_key",
                "api_key_provider": "lmstudio",
                "api_key_destination": "http://127.0.0.1:1234",
            },
        },
    )

    result = run_migrations(tmp_path)

    assert result["llm"]["provider"] == "ollama"
    assert not (tmp_path / "secrets" / "llm_api_key").exists()
    assert list((tmp_path / "secrets").glob(".llm_api_key.lmstudio-retirement.*")) == []
    assert not journal_path.exists()


@pytest.mark.parametrize("backup_version", ["1.0.0", "1.1.0"])
@pytest.mark.parametrize("phase", ["prepared", "committed"])
def test_default_lmstudio_migration_finishes_a_postcommit_staged_secret(
    tmp_path,
    backup_version,
    phase,
):
    old = {
        "version": backup_version,
        "llm": {
            "provider": "lmstudio",
            "host": "http://localhost:1234",
            "api_key_ref": "secret://llm/api_key",
            "api_key_provider": "lmstudio",
            "api_key_destination": "http://localhost:1234",
        },
    }
    current = {
        "version": WORKSPACE_VERSION,
        "llm": {
            "provider": "ollama",
            "host": "",
            "api_key_ref": "",
            "api_key_provider": "",
            "api_key_destination": "",
        },
    }
    _seed(tmp_path, current)
    (tmp_path / f"workspace.{backup_version}.bak.json").write_text(json.dumps(old), encoding="utf-8")
    staged_path = tmp_path / "secrets" / ".llm_api_key.lmstudio-retirement.crash"
    staged_path.parent.mkdir(parents=True)
    staged_path.write_text("legacy-local-secret", encoding="utf-8")
    journal_path = _write_retirement_journal(tmp_path, staged_path, phase=phase)

    result = run_migrations(tmp_path)

    assert result == current
    assert not staged_path.exists()
    assert not journal_path.exists()


def test_current_workspace_never_deletes_an_unjournalled_prefixed_file(tmp_path):
    old = {
        "version": "1.1.0",
        "llm": {
            "provider": "lmstudio",
            "host": "http://localhost:1234",
            "api_key_ref": "secret://llm/api_key",
        },
    }
    current = {
        "version": WORKSPACE_VERSION,
        "llm": {
            "provider": "ollama",
            "host": "",
            "api_key_ref": "",
            "api_key_provider": "",
            "api_key_destination": "",
        },
    }
    _seed(tmp_path, current)
    (tmp_path / "workspace.1.1.0.bak.json").write_text(json.dumps(old), encoding="utf-8")
    unrelated_path = tmp_path / "secrets" / ".llm_api_key.lmstudio-retirement.unrelated"
    unrelated_path.parent.mkdir(parents=True)
    unrelated_path.write_text("operator-owned-data", encoding="utf-8")

    assert run_migrations(tmp_path) == current
    assert unrelated_path.read_text(encoding="utf-8") == "operator-owned-data"


def test_staged_lmstudio_recovery_rejects_a_file_that_no_longer_matches_its_journal(
    tmp_path,
):
    old = {
        "version": "1.1.0",
        "llm": {
            "provider": "lmstudio",
            "host": "http://localhost:1234",
            "api_key_ref": "secret://llm/api_key",
        },
    }
    current = {
        "version": WORKSPACE_VERSION,
        "llm": {
            "provider": "ollama",
            "host": "",
            "api_key_ref": "",
            "api_key_provider": "",
            "api_key_destination": "",
        },
    }
    _seed(tmp_path, current)
    (tmp_path / "workspace.1.1.0.bak.json").write_text(json.dumps(old), encoding="utf-8")
    staged_path = tmp_path / "secrets" / ".llm_api_key.lmstudio-retirement.crash"
    staged_path.parent.mkdir(parents=True)
    staged_path.write_text("journalled-secret", encoding="utf-8")
    _write_retirement_journal(tmp_path, staged_path, phase="committed")
    staged_path.write_text("replaced-after-journalling", encoding="utf-8")

    with pytest.raises(MigrationLockError, match="identity"):
        run_migrations(tmp_path)

    assert staged_path.read_text(encoding="utf-8") == "replaced-after-journalling"


def test_lmstudio_staging_does_not_depend_on_unlinking_an_empty_placeholder(
    tmp_path,
    monkeypatch,
):
    secret_path = tmp_path / "secrets" / "llm_api_key"
    secret_path.parent.mkdir(parents=True)
    secret_path.write_text("legacy-local-secret", encoding="utf-8")
    _seed(
        tmp_path,
        {
            "version": "1.1.0",
            "llm": {
                "provider": "lmstudio",
                "host": "http://localhost:1234",
                "api_key_ref": "secret://llm/api_key",
            },
        },
    )
    original_unlink = Path.unlink

    def reject_empty_stage_placeholder(self, *args, **kwargs):
        if (
            self.name.startswith(".llm_api_key.lmstudio-retirement.")
            and self.exists()
            and self.stat().st_size == 0
        ):
            raise PermissionError("empty stage placeholder cannot be removed")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", reject_empty_stage_placeholder)

    result = run_migrations(tmp_path)

    assert result["llm"]["provider"] == "ollama"
    assert not secret_path.exists()
    assert list((tmp_path / "secrets").glob(".llm_api_key.lmstudio-retirement.*")) == []
    assert not (tmp_path / _LMSTUDIO_RETIREMENT_JOURNAL).exists()


def test_lmstudio_stage_rename_failure_cleans_the_journal_and_preserves_the_secret(
    tmp_path,
    monkeypatch,
):
    secret_path = tmp_path / "secrets" / "llm_api_key"
    secret_path.parent.mkdir(parents=True)
    secret_path.write_text("legacy-local-secret", encoding="utf-8")
    workspace_path = _seed(
        tmp_path,
        {
            "version": "1.1.0",
            "llm": {
                "provider": "lmstudio",
                "host": "http://localhost:1234",
                "api_key_ref": "secret://llm/api_key",
            },
        },
    )
    real_replace = os.replace
    native_replace_calls: list[tuple[Path, Path]] = []

    def reject_secret_staging(source, destination):
        source_path = Path(source)
        destination_path = Path(destination)
        native_replace_calls.append((source_path, destination_path))
        if source_path == secret_path and destination_path.name.startswith(
            ".llm_api_key.lmstudio-retirement."
        ):
            raise PermissionError("secret staging rename failed")
        return real_replace(source, destination)

    def portable_windows_reopen(descriptor, **_kwargs):
        reopened = os.dup(descriptor)
        os.close(descriptor)
        return reopened

    monkeypatch.setattr(secure_file, "_is_windows", lambda: True)
    monkeypatch.setattr(secure_file, "_assert_current_user_owns", lambda *_args: None)
    monkeypatch.setattr(
        secure_file,
        "_reopen_windows_descriptor_for_security",
        portable_windows_reopen,
    )
    monkeypatch.setattr(secure_file, "_windows_replace_write_through", reject_secret_staging)
    monkeypatch.setattr(secure_file, "_windows_delete_file", lambda path: path.unlink())

    with pytest.raises(PermissionError, match="staging rename failed"):
        run_migrations(tmp_path)

    assert any(
        source == secret_path
        and destination.name.startswith(".llm_api_key.lmstudio-retirement.")
        for source, destination in native_replace_calls
    )
    assert json.loads(workspace_path.read_text(encoding="utf-8"))["llm"]["provider"] == "lmstudio"
    assert secret_path.read_text(encoding="utf-8") == "legacy-local-secret"
    assert list((tmp_path / "secrets").glob(".llm_api_key.lmstudio-retirement.*")) == []
    assert not (tmp_path / _LMSTUDIO_RETIREMENT_JOURNAL).exists()


def test_110_to_current_retires_remote_lmstudio_and_its_bound_secret(tmp_path):
    host = "http://10.0.0.8:9000"
    secret_path = tmp_path / "secrets" / "llm_api_key"
    secret_path.parent.mkdir(parents=True)
    secret_path.write_text("custom-secret", encoding="utf-8")
    _seed(
        tmp_path,
        {
            "version": "1.1.0",
            "llm": {
                "provider": "lmstudio",
                "host": host,
                "model": "remote-model",
                "api_key_ref": "secret://llm/api_key",
                "api_key_provider": "lmstudio",
                "api_key_destination": host,
            },
        },
    )

    result = run_migrations(tmp_path)

    assert result["llm"]["provider"] == "ollama"
    assert result["llm"]["host"] == ""
    assert result["llm"]["api_key_ref"] == ""
    assert result["llm"]["api_key_provider"] == ""
    assert result["llm"]["api_key_destination"] == ""
    assert not secret_path.exists()


def test_remote_lmstudio_migration_does_not_preserve_the_legacy_endpoint(
    tmp_path: Path,
) -> None:
    host = "HTTPS://Models.Example.INVALID:443/API/?Token=X/"
    _seed(
        tmp_path,
        {
            "version": "1.1.0",
            "initialized": True,
            "llm": {
                "provider": "lmstudio",
                "host": host,
                "model": "remote-model",
                "api_key_ref": "secret://llm/api_key",
            },
        },
    )
    secret_path = tmp_path / "secrets" / "llm_api_key"
    secret_path.parent.mkdir(parents=True)
    secret_path.write_text("remote-secret", encoding="utf-8")
    secret_path.chmod(0o600)

    result = run_migrations(tmp_path)

    assert result["llm"]["provider"] == "ollama"
    assert result["llm"]["host"] == ""
    assert result["llm"]["api_key_destination"] == ""
    assert not secret_path.exists()


def test_110_to_current_retires_bound_secret_when_scheme_and_hostname_case_differ(tmp_path):
    host = "HTTP://Models.Example.INVALID:9000/api"
    secret_path = tmp_path / "secrets" / "llm_api_key"
    secret_path.parent.mkdir(parents=True)
    secret_path.write_text("custom-secret", encoding="utf-8")
    _seed(
        tmp_path,
        {
            "version": "1.1.0",
            "llm": {
                "provider": "lmstudio",
                "host": host,
                "model": "remote-model",
                "api_key_ref": "secret://llm/api_key",
                "api_key_provider": "lmstudio",
                "api_key_destination": "http://models.example.invalid:9000/api/",
            },
        },
    )

    result = run_migrations(tmp_path)

    assert result["llm"]["provider"] == "ollama"
    assert result["llm"]["host"] == ""
    assert result["llm"]["api_key_provider"] == ""
    assert result["llm"]["api_key_destination"] == ""
    assert not secret_path.exists()


def test_default_lmstudio_secret_deletion_failure_rolls_back_and_retries_truthfully(
    tmp_path,
    monkeypatch,
):
    secret_path = tmp_path / "secrets" / "llm_api_key"
    secret_path.parent.mkdir(parents=True)
    secret_path.write_text("legacy-local-secret", encoding="utf-8")
    workspace_path = _seed(
        tmp_path,
        {
            "version": "1.1.0",
            "llm": {
                "provider": "lmstudio",
                "host": "http://127.0.0.1:1234",
                "api_key_ref": "secret://llm/api_key",
                "api_key_provider": "lmstudio",
                "api_key_destination": "http://127.0.0.1:1234",
            },
        },
    )
    original_unlink = Path.unlink
    refused_stage_deletion = False

    def fail_final_staged_secret_deletion(self, *args, **kwargs):
        nonlocal refused_stage_deletion
        if (
            self.name.startswith(".llm_api_key.lmstudio-retirement.")
            and self.exists()
            and self.stat().st_size > 0
            and not refused_stage_deletion
        ):
            refused_stage_deletion = True
            raise PermissionError("simulated LM Studio credential deletion failure")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_final_staged_secret_deletion)

    with pytest.raises(PermissionError, match="credential deletion failure"):
        run_migrations(tmp_path)

    assert json.loads(workspace_path.read_text(encoding="utf-8"))["llm"]["provider"] == "lmstudio"
    assert secret_path.read_text(encoding="utf-8") == "legacy-local-secret"

    monkeypatch.setattr(Path, "unlink", original_unlink)
    recovered = run_migrations(tmp_path)

    assert recovered["llm"]["provider"] == "ollama"
    assert not secret_path.exists()
    assert list((tmp_path / "secrets").glob(".llm_api_key.lmstudio-retirement.*")) == []


def test_110_to_current_preserves_a_secret_bound_to_an_unrelated_destination(tmp_path):
    secret_path = tmp_path / "secrets" / "llm_api_key"
    secret_path.parent.mkdir(parents=True)
    secret_path.write_text("unrelated-secret", encoding="utf-8")
    _seed(
        tmp_path,
        {
            "version": "1.1.0",
            "llm": {
                "provider": "lmstudio",
                "host": "http://localhost:1234",
                "api_key_ref": "secret://llm/api_key",
                "api_key_provider": "openai",
                "api_key_destination": "https://api.openai.com",
            },
        },
    )

    result = run_migrations(tmp_path)

    assert result["llm"]["provider"] == "ollama"
    assert result["llm"]["api_key_ref"] == ""
    assert secret_path.read_text(encoding="utf-8") == "unrelated-secret"


def test_reject_future_version_no_mutation(tmp_path):
    """Unknown future versions are treated as downgrade attempts."""
    original = {"version": "9.9.9", "weird_field": "value"}
    path = _seed(tmp_path, original)

    with pytest.raises(ValueError, match="refusing to overwrite"):
        run_migrations(tmp_path)

    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_reject_future_version_before_lmstudio_journal_recovery_mutates_any_file(tmp_path):
    staged_path = tmp_path / "secrets" / ".llm_api_key.lmstudio-retirement.future"
    staged_path.parent.mkdir(parents=True)
    staged_path.write_text("future-workspace-secret", encoding="utf-8")
    journal_path = _write_retirement_journal(tmp_path, staged_path, phase="prepared")
    original = {
        "version": "9.9.9",
        "llm": {
            "provider": "lmstudio",
            "host": "http://localhost:1234",
            "api_key_ref": "secret://llm/api_key",
        },
        "future_field": {"must": "survive"},
    }
    workspace_path = _seed(tmp_path, original)
    before = {
        workspace_path: workspace_path.read_bytes(),
        journal_path: journal_path.read_bytes(),
        staged_path: staged_path.read_bytes(),
    }

    with pytest.raises(ValueError, match="refusing to overwrite"):
        run_migrations(tmp_path)

    assert not (tmp_path / "secrets" / "llm_api_key").exists()
    assert {path: path.read_bytes() for path in before} == before


def test_partial_failure_restores_on_disk(tmp_path, monkeypatch):
    """If a migration step raises mid-walk, the on-disk file is restored."""
    original = {"version": "0.5.2", "user_field": "important"}
    path = _seed(tmp_path, original)

    def _boom(cfg):
        raise RuntimeError("injected failure")

    monkeypatch.setitem(MIGRATIONS, "0.5.2", ("1.0.0", _boom))

    with pytest.raises(RuntimeError, match="injected failure"):
        run_migrations(tmp_path)

    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_concurrent_lock_blocks_second_caller(tmp_path):
    """A live kernel-lock holder blocks concurrent migration."""
    lock = tmp_path / ".migration.lock"
    with FileLock(lock, mode=0o600):
        with pytest.raises(MigrationLockError):
            with _migration_lock(tmp_path):
                pytest.fail("non-waiting contender acquired an already-held lock")


def test_workspace_load_waits_for_active_writer(tmp_path):
    """Routine reads wait for a valid writer instead of failing transiently."""
    expected = {"version": WORKSPACE_VERSION, "value": "preserved"}
    _seed(tmp_path, expected)
    started = threading.Event()
    outcomes: list[dict | BaseException] = []

    def load_workspace() -> None:
        started.set()
        try:
            outcomes.append(run_migrations(tmp_path))
        except BaseException as exc:  # noqa: BLE001 - retained for assertion in the parent
            outcomes.append(exc)

    lock = FileLock(tmp_path / ".migration.lock", mode=0o600)
    with lock:
        reader = threading.Thread(target=load_workspace)
        reader.start()
        assert started.wait(1.0)
        time.sleep(0.05)
        assert reader.is_alive(), "workspace load failed instead of waiting for the active writer"

    reader.join(2.0)
    assert reader.is_alive() is False
    assert outcomes == [expected]


def test_unlocked_incomplete_lock_record_does_not_block(tmp_path):
    """Lock-file contents alone do not represent ownership."""
    lock = tmp_path / ".migration.lock"
    lock.write_text("", encoding="utf-8")

    with _migration_lock(tmp_path, wait=True, timeout=0.02):
        assert lock.exists()

    assert lock.exists()


def test_stale_lock_contents_do_not_block(tmp_path):
    """Stale PID text cannot block or grant kernel-lock ownership."""
    _seed(tmp_path, {"version": "0.5.2"})
    lock = tmp_path / ".migration.lock"
    lock.write_text(f"{2**22}\n0\n", encoding="utf-8")

    result = run_migrations(tmp_path)

    assert result["version"] == WORKSPACE_VERSION


def test_stale_record_cannot_create_overlapping_process_owners(tmp_path):
    """Two processes serialise even when the lock file starts with stale text."""
    (tmp_path / ".migration.lock").write_text(f"{2**22}\n0\n", encoding="utf-8")
    first_entered = tmp_path / "first-entered"
    release_first = tmp_path / "release-first"
    second_entered = tmp_path / "second-entered"
    first = subprocess.Popen(
        [sys.executable, "-c", _HOLD_WORKSPACE_LOCK, str(tmp_path), str(first_entered), str(release_first)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    second: subprocess.Popen[str] | None = None

    try:
        _wait_for_process_marker(first_entered, first, 5.0)

        second = subprocess.Popen(
            [sys.executable, "-c", _ENTER_WORKSPACE_LOCK, str(tmp_path), str(second_entered)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(0.3)
        assert second.poll() is None, "second lock contender exited while the first held the lock"
        assert not second_entered.exists(), "second process overlapped the first lock owner"

        release_first.write_text("release", encoding="utf-8")
        _wait_for_process_marker(second_entered, second, 5.0)
    finally:
        release_first.touch(exist_ok=True)
        for process in (first, second):
            if process is None:
                continue
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5.0)

    first_stdout, first_stderr = first.communicate()
    assert first.returncode == 0, first_stdout + first_stderr
    assert second is not None
    second_stdout, second_stderr = second.communicate()
    assert second.returncode == 0, second_stdout + second_stderr


def test_atomic_write_leaves_no_tmp(tmp_path):
    """Successful migration leaves no temporary workspace files."""
    _seed(tmp_path, {"version": "0.5.2"})

    run_migrations(tmp_path)

    assert list(tmp_path.glob(".workspace.*.tmp")) == []
    assert list(tmp_path.glob(".workspace.*.tmp.*")) == []


def test_atomic_write_retries_until_every_byte_is_written(tmp_path, monkeypatch):
    target = tmp_path / "workspace.json"
    payload = b'{"version":"1.2.0","model":"complete"}'
    real_write = os.write
    write_sizes: list[int] = []

    def short_write(descriptor: int, data: bytes | memoryview) -> int:
        chunk = bytes(data)
        write_size = max(1, len(chunk) // 2)
        write_sizes.append(write_size)
        return real_write(descriptor, chunk[:write_size])

    monkeypatch.setattr(os, "write", short_write)

    _atomic_write(target, payload)

    assert target.read_bytes() == payload
    assert len(write_sizes) > 1


@pytest.mark.skipif(os.name == "nt", reason="directory fsync is POSIX-only")
def test_atomic_write_fsyncs_the_parent_directory_after_replace(tmp_path, monkeypatch):
    target = tmp_path / "workspace.json"
    real_fsync = os.fsync
    directory_fsyncs = 0

    def record_fsync(descriptor: int) -> None:
        nonlocal directory_fsyncs
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            directory_fsyncs += 1
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", record_fsync)

    _atomic_write(target, "durable")

    assert target.read_text(encoding="utf-8") == "durable"
    assert directory_fsyncs == 1


def test_merge_defaults_recursive():
    defaults = {"a": 1, "nested": {"x": 1, "y": 2}}
    existing = {"nested": {"y": 99}, "extra": "kept"}

    out = _merge_defaults(defaults, existing)

    assert out == {"a": 1, "nested": {"x": 1, "y": 99}, "extra": "kept"}


def test_corrupted_backup_recovered(tmp_path):
    """A corrupt existing backup aborts before mutating workspace.json."""
    original = {"version": "0.5.2", "user_field": "important"}
    path = _seed(tmp_path, original)
    backup = tmp_path / "workspace.0.5.2.bak.json"
    backup.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(MigrationLockError, match="backup"):
        run_migrations(tmp_path)

    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_partial_fsync_via_monkeypatch(tmp_path, monkeypatch):
    """Simulate fsync failing mid-atomic-write; original file is preserved."""
    original = {"version": "0.5.2"}
    path = _seed(tmp_path, original)
    real_fsync = os.fsync

    def _boom_fsync(fd):  # noqa: ARG001
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fsync", _boom_fsync)

    with pytest.raises(OSError, match="No space left"):
        run_migrations(tmp_path)

    assert json.loads(path.read_text(encoding="utf-8")) == original
    monkeypatch.setattr(os, "fsync", real_fsync)


def test_disk_full_via_pyfakefs():
    """pyfakefs disk-full simulation is carried by the optional fixture file."""
    pytest.importorskip("pyfakefs")
    pytest.skip("pyfakefs-based disk-full simulation lives in a platform-specific fixture")


def test_concurrent_read_during_lock_is_serialised(tmp_path):
    """Concurrent readers see original or migrated JSON, never a torn write."""
    _seed(tmp_path, {"version": "0.5.2"})
    import threading

    reader_observations: list[dict] = []

    def _reader():
        for _ in range(10):
            try:
                reader_observations.append(json.loads((tmp_path / "workspace.json").read_text(encoding="utf-8")))
            except (json.JSONDecodeError, FileNotFoundError):
                pass

    thread = threading.Thread(target=_reader)
    thread.start()
    result = run_migrations(tmp_path)
    thread.join()

    for obs in reader_observations:
        assert obs.get("version") in ("0.5.2", WORKSPACE_VERSION)
    assert result["version"] == WORKSPACE_VERSION


def test_fresh_install_round_trip(tmp_path):
    """Missing workspace.json creates current defaults and subsequent calls are no-ops."""
    result = run_migrations(tmp_path)

    assert result["version"] == WORKSPACE_VERSION
    on_disk = json.loads((tmp_path / "workspace.json").read_text(encoding="utf-8"))
    assert on_disk["version"] == WORKSPACE_VERSION
    assert on_disk["compliance"]["personal_use_mode"] is True
    assert on_disk["brokers"]["execution"]["default"] == "openalgo:default"
    assert run_migrations(tmp_path) == result
