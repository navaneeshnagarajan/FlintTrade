"""Tests for FlintTrade workspace configuration."""

import concurrent.futures
import json
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest


def _clear_storage_overrides(monkeypatch, *extra: str) -> None:
    for name in ("FLINTTRADE_HOME", "FLINTTRADE_WORKSPACE_DIR", *extra):
        monkeypatch.delenv(name, raising=False)



class TestWorkspaceResolution:
    """Test workspace directory resolution across platforms."""

    def test_flinttrade_home_env_override(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FLINTTRADE_WORKSPACE_DIR", raising=False)
        monkeypatch.setenv("FLINTTRADE_HOME", str(tmp_path / "custom"))
        from flinttrade_core.workspace import Workspace
        ws = Workspace()
        assert ws.workspace_dir == (tmp_path / "custom").resolve()

    def test_workspace_dir_env_wins_over_home_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FLINTTRADE_HOME", str(tmp_path / "home"))
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path / "workspace"))
        from flinttrade_core.workspace import Workspace, workspace_dir
        ws = Workspace()
        assert ws.workspace_dir == workspace_dir()
        assert ws.workspace_dir == (tmp_path / "workspace").resolve()

    def test_default_linux_path(self, monkeypatch):
        monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        from flinttrade_core.workspace import _default_home
        result = _default_home()
        assert result == Path.home() / ".flinttrade"

    def test_default_darwin_path(self, monkeypatch):
        monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        from flinttrade_core.workspace import _default_home
        result = _default_home()
        assert result == Path.home() / "Library" / "Application Support" / "flinttrade"

    def test_default_windows_path(self, monkeypatch):
        monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
        monkeypatch.setattr(platform, "system", lambda: "Windows")
        monkeypatch.setenv("APPDATA", "/fake/appdata")
        from flinttrade_core.workspace import _default_home
        result = _default_home()
        assert result == Path("/fake/appdata/flinttrade")

    def test_platform_default_storage_stays_inside_workspace(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
        monkeypatch.delenv("FLINTTRADE_WORKSPACE_DIR", raising=False)
        from flinttrade_core import workspace

        platform_home = tmp_path / "platform-workspace"
        monkeypatch.setattr(workspace, "_default_home", lambda: platform_home)

        ws = workspace.Workspace()
        ws.initialise()

        assert ws.fast_data_dir == (platform_home / "data").resolve()
        assert ws.archive_dir == (platform_home / "archive").resolve()

    def test_duckdb_path_uses_workspace_storage(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DUCKDB_PATH", raising=False)
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path / "workspace"))
        from flinttrade_core.workspace import duckdb_path

        assert duckdb_path() == (tmp_path / "workspace" / "data" / "flint.duckdb").resolve()

    def test_duckdb_path_preserves_explicit_override(self, tmp_path, monkeypatch):
        override = tmp_path / "operator" / "custom.duckdb"
        monkeypatch.setenv("DUCKDB_PATH", str(override))
        from flinttrade_core.workspace import duckdb_path

        assert duckdb_path() == override

    def test_duckdb_path_copies_legacy_database_and_wal_once(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DUCKDB_PATH", raising=False)
        monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
        monkeypatch.delenv("FLINTTRADE_WORKSPACE_DIR", raising=False)
        from flinttrade_core import workspace

        legacy = tmp_path / "legacy" / "data" / "flint.duckdb"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"legacy-db")
        Path(f"{legacy}.wal").write_bytes(b"legacy-wal")
        target_home = tmp_path / "platform-workspace"
        monkeypatch.setattr(workspace, "_default_home", lambda: target_home)
        monkeypatch.setattr(workspace, "_legacy_duckdb_path", lambda: legacy, raising=False)

        target = workspace.duckdb_path()

        assert target == (target_home / "data" / "flint.duckdb").resolve()
        assert target.read_bytes() == b"legacy-db"
        assert Path(f"{target}.wal").read_bytes() == b"legacy-wal"
        assert legacy.read_bytes() == b"legacy-db"
        assert Path(f"{legacy}.wal").read_bytes() == b"legacy-wal"

    def test_duckdb_path_never_overwrites_existing_workspace_database(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DUCKDB_PATH", raising=False)
        monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
        monkeypatch.delenv("FLINTTRADE_WORKSPACE_DIR", raising=False)
        from flinttrade_core import workspace

        legacy = tmp_path / "legacy" / "data" / "flint.duckdb"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"legacy-db")
        target_home = tmp_path / "platform-workspace"
        target = target_home / "data" / "flint.duckdb"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"current-db")
        monkeypatch.setattr(workspace, "_default_home", lambda: target_home)
        monkeypatch.setattr(workspace, "_legacy_duckdb_path", lambda: legacy, raising=False)

        assert workspace.duckdb_path().read_bytes() == b"current-db"

    def test_sandbox_state_path_preserves_explicit_override_precedence(self, tmp_path, monkeypatch):
        preferred = tmp_path / "preferred" / "state.sqlite"
        legacy_override = tmp_path / "legacy-override" / "state.sqlite"
        monkeypatch.setenv("SANDBOX_STATE_PATH", str(preferred))
        monkeypatch.setenv("SANDBOX_DB_PATH", str(legacy_override))
        from flinttrade_core.workspace import sandbox_state_path

        assert sandbox_state_path() == preferred

    def test_sandbox_state_path_copies_legacy_sqlite_and_wal_once(self, tmp_path, monkeypatch):
        for name in (
            "SANDBOX_STATE_PATH",
            "SANDBOX_DB_PATH",
            "FLINTTRADE_HOME",
            "FLINTTRADE_WORKSPACE_DIR",
        ):
            monkeypatch.delenv(name, raising=False)
        from flinttrade_core import workspace

        legacy = tmp_path / "legacy" / "sandbox" / "state.sqlite"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"legacy-sqlite")
        Path(f"{legacy}-wal").write_bytes(b"legacy-wal")
        target_home = tmp_path / "platform-workspace"
        monkeypatch.setattr(workspace, "_default_home", lambda: target_home)
        monkeypatch.setattr(workspace, "_legacy_sandbox_state_path", lambda: legacy, raising=False)

        target = workspace.sandbox_state_path()

        assert target == (target_home / "sandbox" / "state.sqlite").resolve()
        assert target.read_bytes() == b"legacy-sqlite"
        assert Path(f"{target}-wal").read_bytes() == b"legacy-wal"
        assert legacy.read_bytes() == b"legacy-sqlite"
        assert Path(f"{legacy}-wal").read_bytes() == b"legacy-wal"

    def test_sandbox_state_path_never_overwrites_existing_workspace_database(self, tmp_path, monkeypatch):
        for name in (
            "SANDBOX_STATE_PATH",
            "SANDBOX_DB_PATH",
            "FLINTTRADE_HOME",
            "FLINTTRADE_WORKSPACE_DIR",
        ):
            monkeypatch.delenv(name, raising=False)
        from flinttrade_core import workspace

        legacy = tmp_path / "legacy" / "sandbox" / "state.sqlite"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"legacy-sqlite")
        target_home = tmp_path / "platform-workspace"
        target = target_home / "sandbox" / "state.sqlite"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"current-sqlite")
        monkeypatch.setattr(workspace, "_default_home", lambda: target_home)
        monkeypatch.setattr(workspace, "_legacy_sandbox_state_path", lambda: legacy, raising=False)

        assert workspace.sandbox_state_path().read_bytes() == b"current-sqlite"

    def test_historify_queue_path_copies_legacy_sqlite(self, tmp_path, monkeypatch):
        _clear_storage_overrides(monkeypatch, "HISTORIFY_QUEUE_DB")
        from flinttrade_core import workspace

        legacy_fast = tmp_path / "legacy" / "data"
        legacy_fast.mkdir(parents=True)
        legacy = legacy_fast / "historify_queue.db"
        legacy.write_bytes(b"historify-queue")
        Path(f"{legacy}-wal").write_bytes(b"historify-wal")
        target_home = tmp_path / "platform-workspace"
        monkeypatch.setattr(workspace, "_default_home", lambda: target_home)
        monkeypatch.setattr(workspace, "_legacy_fast_data_dir", lambda: legacy_fast, raising=False)

        target = workspace.historify_queue_path()

        assert target.read_bytes() == b"historify-queue"
        assert Path(f"{target}-wal").read_bytes() == b"historify-wal"
        assert legacy.exists()

    def test_ditto_accounts_path_copies_metadata_and_vault(self, tmp_path, monkeypatch):
        _clear_storage_overrides(monkeypatch, "DATA_DIR")
        from flinttrade_core import workspace

        legacy_fast = tmp_path / "legacy" / "data"
        legacy_fast.mkdir(parents=True)
        legacy_accounts = legacy_fast / "ditto_accounts.sqlite"
        legacy_vault = legacy_fast / "ditto_credentials.db"
        legacy_accounts.write_bytes(b"ditto-accounts")
        legacy_vault.write_bytes(b"ditto-vault")
        target_home = tmp_path / "platform-workspace"
        monkeypatch.setattr(workspace, "_default_home", lambda: target_home)
        monkeypatch.setattr(workspace, "_legacy_fast_data_dir", lambda: legacy_fast, raising=False)

        target = workspace.ditto_accounts_path()

        assert target.read_bytes() == b"ditto-accounts"
        assert (target.parent / "ditto_credentials.db").read_bytes() == b"ditto-vault"
        assert legacy_accounts.exists()
        assert legacy_vault.exists()

    def test_audit_log_dir_copies_chain_without_source_lock(self, tmp_path, monkeypatch):
        _clear_storage_overrides(monkeypatch, "AUDIT_LOG_DIR")
        from flinttrade_core import workspace

        legacy_archive = tmp_path / "legacy" / "archive"
        legacy_audit = legacy_archive / "audit"
        legacy_audit.mkdir(parents=True)
        (legacy_audit / "audit_2026-07-15.jsonl").write_text("chain-record\n")
        (legacy_audit / ".audit-chain.lock").write_text("")
        target_home = tmp_path / "platform-workspace"
        monkeypatch.setattr(workspace, "_default_home", lambda: target_home)
        monkeypatch.setattr(workspace, "_legacy_archive_dir", lambda: legacy_archive, raising=False)

        target = workspace.audit_log_dir()

        assert (target / "audit_2026-07-15.jsonl").read_text() == "chain-record\n"
        assert not (target / ".audit-chain.lock").exists()
        assert (legacy_audit / "audit_2026-07-15.jsonl").exists()

    def test_bhavcopy_dir_copies_legacy_archives(self, tmp_path, monkeypatch):
        _clear_storage_overrides(monkeypatch)
        from flinttrade_core import workspace

        legacy_fast = tmp_path / "legacy" / "data"
        legacy_bhavcopy = legacy_fast / "bhavcopy"
        legacy_bhavcopy.mkdir(parents=True)
        (legacy_bhavcopy / "sample.csv").write_text("symbol,close\nRELIANCE,2500\n")
        target_home = tmp_path / "platform-workspace"
        monkeypatch.setattr(workspace, "_default_home", lambda: target_home)
        monkeypatch.setattr(workspace, "_legacy_fast_data_dir", lambda: legacy_fast, raising=False)

        target = workspace.bhavcopy_dir()

        assert (target / "sample.csv").read_text() == "symbol,close\nRELIANCE,2500\n"
        assert (legacy_bhavcopy / "sample.csv").exists()

    def test_legacy_state_copy_failure_is_explicit(self, tmp_path, monkeypatch):
        _clear_storage_overrides(monkeypatch, "DUCKDB_PATH")
        from flinttrade_core import workspace

        legacy = tmp_path / "legacy" / "data" / "flint.duckdb"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"operator-state")
        target_home = tmp_path / "platform-workspace"
        monkeypatch.setattr(workspace, "_default_home", lambda: target_home)
        monkeypatch.setattr(workspace, "_legacy_duckdb_path", lambda: legacy)
        monkeypatch.setattr(workspace.shutil, "copy2", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk")))

        with pytest.raises(workspace.WorkspaceStateMigrationError, match="shared DuckDB"):
            workspace.duckdb_path()

        assert legacy.read_bytes() == b"operator-state"
        assert not (target_home / "data" / "flint.duckdb").exists()


class TestWorkspaceInit:
    """Test workspace initialization and directory creation."""

    def test_initialize_creates_dirs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FLINTTRADE_HOME", str(tmp_path / "ws"))
        from flinttrade_core.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()
        assert ws.is_initialized
        assert ws.config_path.exists()
        assert ws.fast_data_dir.exists()
        assert ws.archive_dir.exists()
        assert ws.log_dir.exists()

    def test_initialize_writes_workspace_json(self, tmp_path):
        from flinttrade_core.workspace_migrations import WORKSPACE_VERSION
        from flinttrade_core.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()
        with open(ws.config_path) as f:
            config = json.load(f)
        assert config["initialized"] is True
        assert config["version"] == WORKSPACE_VERSION
        assert "modules" in config
        assert "storage" in config

    def test_not_initialized_before_init(self, tmp_path):
        from flinttrade_core.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "empty")
        assert not ws.is_initialized

    def test_cli_provision_master_password_creates_hardened_file(self, tmp_path):
        from flinttrade_core.cli import _provision_master_password
        from flinttrade_core.secure_file import assert_hardened
        from flinttrade_core.workspace import Workspace

        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()

        assert _provision_master_password(ws) is True
        password_file = ws.workspace_dir / "master_password"
        assert password_file.read_text(encoding="utf-8").strip()
        ok, reason = assert_hardened(password_file)
        assert ok, reason

    def test_cli_provision_master_password_never_overwrites_existing_secret(self, tmp_path):
        from flinttrade_core.cli import _provision_master_password
        from flinttrade_core.workspace import Workspace

        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()
        password_file = ws.workspace_dir / "master_password"
        password_file.write_text("operator-owned-secret", encoding="utf-8")

        assert _provision_master_password(ws) is False
        assert password_file.read_text(encoding="utf-8") == "operator-owned-secret"

    def test_cli_provision_master_password_replaces_an_owned_empty_file(self, tmp_path):
        from flinttrade_core.cli import _provision_master_password
        from flinttrade_core.workspace import Workspace

        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()
        password_file = ws.workspace_dir / "master_password"
        password_file.write_text(" \n", encoding="utf-8")

        assert _provision_master_password(ws) is True
        password = password_file.read_text(encoding="utf-8")
        assert len(password) == 64
        assert all(character in "0123456789abcdef" for character in password)

    def test_cli_provision_master_password_serialises_concurrent_callers(self, tmp_path, monkeypatch):
        from flinttrade_core import cli
        from flinttrade_core.workspace import Workspace

        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()
        start = threading.Barrier(2)
        write_count = 0
        write_count_lock = threading.Lock()
        real_write = cli.write_secret_text

        def slow_write(path, value, user=None):  # type: ignore[no-untyped-def]
            nonlocal write_count
            with write_count_lock:
                write_count += 1
            time.sleep(0.15)
            return real_write(path, value, user=user)

        def provision() -> bool:
            start.wait()
            return cli._provision_master_password(ws)

        monkeypatch.setattr(cli, "write_secret_text", slow_write)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: provision(), range(2)))

        assert sorted(results) == [False, True]
        assert write_count == 1
        password = (ws.workspace_dir / "master_password").read_text(encoding="utf-8")
        assert len(password) == 64
        assert all(character in "0123456789abcdef" for character in password)

    def test_cli_provision_master_password_rejects_symlink_without_touching_target(self, tmp_path):
        from flinttrade_core.cli import _provision_master_password
        from flinttrade_core.workspace import Workspace

        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()
        outside = tmp_path / "outside-secret"
        outside.write_text("operator-owned-secret", encoding="utf-8")
        outside.chmod(0o600)
        password_file = ws.workspace_dir / "master_password"
        password_file.symlink_to(outside)

        with pytest.raises(OSError, match="unsafe"):
            _provision_master_password(ws)

        assert password_file.is_symlink()
        assert outside.read_text(encoding="utf-8") == "operator-owned-secret"

    @pytest.mark.skipif(os.name == "nt", reason="POSIX ownership semantics")
    def test_cli_provision_master_password_rejects_another_owner(self, tmp_path, monkeypatch):
        from flinttrade_core import secure_file
        from flinttrade_core.cli import _provision_master_password
        from flinttrade_core.workspace import Workspace

        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()
        password_file = ws.workspace_dir / "master_password"
        password_file.write_text("operator-owned-secret", encoding="utf-8")
        password_file.chmod(0o600)
        actual_user = password_file.stat().st_uid
        monkeypatch.setattr(secure_file.os, "geteuid", lambda: actual_user + 1)

        with pytest.raises(PermissionError, match="owned by the current user"):
            _provision_master_password(ws)

        assert password_file.read_text(encoding="utf-8") == "operator-owned-secret"

    def test_cli_provision_master_password_hardens_owned_existing_secret(self, tmp_path):
        from flinttrade_core.cli import _provision_master_password
        from flinttrade_core.secure_file import assert_hardened
        from flinttrade_core.workspace import Workspace

        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()
        password_file = ws.workspace_dir / "master_password"
        password_file.write_text("operator-owned-secret", encoding="utf-8")
        if os.name != "nt":
            password_file.chmod(0o640)

        assert _provision_master_password(ws) is False
        assert password_file.read_text(encoding="utf-8") == "operator-owned-secret"
        ok, reason = assert_hardened(password_file)
        assert ok, reason

    @pytest.mark.skipif(os.name == "nt", reason="POSIX mode-bit semantics")
    def test_cli_provision_master_password_repairs_noncanonical_owner_mode(self, tmp_path):
        from flinttrade_core.cli import _provision_master_password
        from flinttrade_core.workspace import Workspace

        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()
        password_file = ws.workspace_dir / "master_password"
        password_file.write_text("operator-owned-secret", encoding="utf-8")
        password_file.chmod(0o400)

        assert _provision_master_password(ws) is False
        assert password_file.read_text(encoding="utf-8") == "operator-owned-secret"
        assert password_file.stat().st_mode & 0o777 == 0o600

    def test_cli_provision_master_password_fails_closed_on_postcondition(self, tmp_path, monkeypatch):
        from flinttrade_core import cli
        from flinttrade_core.workspace import Workspace

        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()

        def reject_postcondition(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise PermissionError("postcondition rejected")

        monkeypatch.setattr(cli, "read_hardened_owner_owned_text", reject_postcondition)

        with pytest.raises(PermissionError, match="postcondition rejected"):
            cli._provision_master_password(ws)

    def test_master_password_cli_success_never_prints_the_secret(self, tmp_path):
        workspace = tmp_path / "ws"
        env = {**os.environ, "FLINTTRADE_WORKSPACE_DIR": str(workspace)}

        result = subprocess.run(
            [sys.executable, "-m", "flinttrade_core.cli", "init", "--provision-master-password"],
            check=False,
            capture_output=True,
            env=env,
            text=True,
        )

        password = (workspace / "master_password").read_text(encoding="utf-8")
        assert result.returncode == 0, result.stderr
        assert len(password) == 64
        assert password not in result.stdout
        assert password not in result.stderr

    def test_master_password_cli_reports_stable_failure_without_secret_leakage(self, tmp_path):
        from flinttrade_core.workspace import Workspace

        workspace = tmp_path / "ws"
        ws = Workspace(home_dir=workspace)
        ws.initialise()
        outside = tmp_path / "outside-secret"
        outside.write_text("operator-owned-secret", encoding="utf-8")
        outside.chmod(0o600)
        (workspace / "master_password").symlink_to(outside)
        env = {**os.environ, "FLINTTRADE_WORKSPACE_DIR": str(workspace)}

        result = subprocess.run(
            [sys.executable, "-m", "flinttrade_core.cli", "init", "--provision-master-password"],
            check=False,
            capture_output=True,
            env=env,
            text=True,
        )

        assert result.returncode == 1
        assert result.stderr.strip() == "Master password provisioning failed."
        assert "operator-owned-secret" not in result.stdout
        assert "operator-owned-secret" not in result.stderr
        assert outside.read_text(encoding="utf-8") == "operator-owned-secret"

    def test_master_password_cli_reports_unsafe_provision_lock_without_secret_leakage(self, tmp_path):
        from flinttrade_core import cli
        from flinttrade_core.workspace import Workspace

        workspace = tmp_path / "ws"
        ws = Workspace(home_dir=workspace)
        ws.initialise()
        outside = tmp_path / "outside-lock-target"
        outside.write_text("do-not-touch", encoding="utf-8")
        (workspace / cli._MASTER_PASSWORD_PROVISION_LOCK).symlink_to(outside)
        env = {**os.environ, "FLINTTRADE_WORKSPACE_DIR": str(workspace)}

        result = subprocess.run(
            [sys.executable, "-m", "flinttrade_core.cli", "init", "--provision-master-password"],
            check=False,
            capture_output=True,
            env=env,
            text=True,
        )

        assert result.returncode == 1
        assert result.stderr.strip() == "Master password provisioning failed."
        assert "do-not-touch" not in result.stdout
        assert "do-not-touch" not in result.stderr
        assert outside.read_text(encoding="utf-8") == "do-not-touch"
        assert (workspace / "master_password").exists() is False


class TestWorkspaceLoadSave:
    """Test load/save/get/set operations."""

    def test_save_and_load(self, tmp_path):
        from flinttrade_core.workspace_migrations import WORKSPACE_VERSION
        from flinttrade_core.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise({"version": WORKSPACE_VERSION, "initialized": True, "data": "hello"})
        ws2 = Workspace(home_dir=tmp_path / "ws")
        assert ws2.load()["data"] == "hello"

    def test_get_dot_notation(self, tmp_path):
        from flinttrade_core.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()
        assert ws.get("ui.theme") == "dark"
        assert ws.get("sebi.max_ops_per_second") == 10

    def test_get_missing_key_returns_default(self, tmp_path):
        from flinttrade_core.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()
        assert ws.get("nonexistent.key", "fallback") == "fallback"

    def test_set_and_persist(self, tmp_path):
        from flinttrade_core.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()
        ws.set("ui.theme", "light")
        # Reload from disk
        ws2 = Workspace(home_dir=tmp_path / "ws")
        assert ws2.get("ui.theme") == "light"

    def test_stale_workspace_instances_do_not_clobber_unrelated_updates(self, tmp_path):
        from flinttrade_core.workspace import Workspace

        first = Workspace(home_dir=tmp_path / "ws")
        first.initialise()
        stale = Workspace(home_dir=tmp_path / "ws")

        first.set("ui.theme", "light")
        stale.set("llm.model", "local-model")

        reloaded = Workspace(home_dir=tmp_path / "ws")
        assert reloaded.get("ui.theme") == "light"
        assert reloaded.get("llm.model") == "local-model"

    def test_failed_atomic_save_preserves_previous_workspace(self, tmp_path, monkeypatch):
        from flinttrade_core import workspace_migrations
        from flinttrade_core.workspace import Workspace

        workspace = Workspace(home_dir=tmp_path / "ws")
        workspace.initialise()
        before = workspace.config_path.read_text(encoding="utf-8")
        workspace._config["ui"]["theme"] = "light"

        monkeypatch.setattr(
            workspace_migrations.os,
            "replace",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("rename failed")),
        )

        with pytest.raises(OSError, match="rename failed"):
            workspace.save()

        assert workspace.config_path.read_text(encoding="utf-8") == before

    def test_path_expansion(self, tmp_path):
        from flinttrade_core.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()
        # fast_data_dir should be an absolute path (~ expanded)
        assert ws.fast_data_dir.is_absolute()
        assert "~" not in str(ws.fast_data_dir)

    def test_explicit_home_keeps_default_storage_inside_workspace(self, tmp_path):
        from flinttrade_core.workspace import Workspace

        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()

        assert ws.fast_data_dir == (tmp_path / "ws" / "data").resolve()
        assert ws.archive_dir == (tmp_path / "ws" / "archive").resolve()

    def test_ensure_directories(self, tmp_path):
        from flinttrade_core.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws._config = {"storage": {"fast": str(tmp_path / "ws" / "data"), "archive": str(tmp_path / "ws" / "archive")}}
        ws.ensure_directories()
        assert (tmp_path / "ws" / "data").exists()
        assert (tmp_path / "ws" / "archive").exists()

    def test_as_dict_returns_copy(self, tmp_path):
        from flinttrade_core.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()
        d = ws.as_dict()
        d["version"] = "modified"
        assert ws.get("version") != "modified"

    def test_corrupt_json_falls_back_to_defaults(self, tmp_path):
        from flinttrade_core.workspace_migrations import WORKSPACE_VERSION
        from flinttrade_core.workspace import Workspace
        ws_dir = tmp_path / "ws"
        ws_dir.mkdir()
        (ws_dir / "workspace.json").write_text("not valid json{{{")
        ws = Workspace(home_dir=ws_dir)
        assert ws.get("version") == WORKSPACE_VERSION  # fell back to current defaults
