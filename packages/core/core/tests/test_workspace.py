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


class TestLegacyPluginDirectoryMigration:
    """The plugin directory follows the same copy-once contract as the databases.

    The default workspace moved off ``~/.flinttrade`` on macOS and Windows.
    Without a migration an upgrade silently stops discovering every plugin the
    operator installed, because an absent plugin directory is not an error.
    """

    @pytest.mark.unit
    def test_fresh_install_has_no_legacy_directory_to_copy(self, tmp_path, monkeypatch):
        """With nothing at the legacy path the workspace plugin dir stays untouched."""
        _clear_storage_overrides(monkeypatch)
        from flinttrade_core import workspace

        target_home = tmp_path / "platform-workspace"
        monkeypatch.setattr(workspace, "_default_home", lambda: target_home)
        monkeypatch.setattr(workspace, "_legacy_plugins_dir", lambda: tmp_path / "legacy" / "plugins")

        target = workspace.plugins_dir()

        assert target == target_home / "plugins"
        assert not target.exists()

    @pytest.mark.unit
    def test_legacy_plugins_are_copied_into_the_platform_workspace(self, tmp_path, monkeypatch):
        """A legacy-only install keeps discovering its plugins after the upgrade."""
        _clear_storage_overrides(monkeypatch)
        from flinttrade_core import workspace

        legacy = tmp_path / "legacy" / "plugins"
        legacy.mkdir(parents=True)
        (legacy / "my_plugin.py").write_text("# operator plugin\n", encoding="utf-8")
        target_home = tmp_path / "platform-workspace"
        monkeypatch.setattr(workspace, "_default_home", lambda: target_home)
        monkeypatch.setattr(workspace, "_legacy_plugins_dir", lambda: legacy)

        target = workspace.plugins_dir()

        assert (target / "my_plugin.py").read_text(encoding="utf-8") == "# operator plugin\n"
        # Copy, never move: a downgrade must still find the original.
        assert (legacy / "my_plugin.py").exists()

    @pytest.mark.unit
    def test_the_migration_lock_stays_inside_the_workspace(self, tmp_path, monkeypatch):
        """``plugins`` sits at the workspace root, so the default lock location is wrong.

        ``target.parent.parent`` would put the lock in ``%APPDATA%`` or
        ``~/Library`` — outside anything FlintTrade owns or uninstalls.
        """
        _clear_storage_overrides(monkeypatch)
        from flinttrade_core import workspace

        legacy = tmp_path / "legacy" / "plugins"
        legacy.mkdir(parents=True)
        (legacy / "my_plugin.py").write_text("# operator plugin\n", encoding="utf-8")
        target_home = tmp_path / "platform" / "workspace"
        monkeypatch.setattr(workspace, "_default_home", lambda: target_home)
        monkeypatch.setattr(workspace, "_legacy_plugins_dir", lambda: legacy)

        # filelock removes its lock file on release, so the path is captured at
        # construction rather than looked for on disk afterwards.
        locks: list[Path] = []
        real_file_lock = workspace.FileLock

        def recording_file_lock(path, *args, **kwargs):
            locks.append(Path(path))
            return real_file_lock(path, *args, **kwargs)

        monkeypatch.setattr(workspace, "FileLock", recording_file_lock)

        workspace.plugins_dir()

        assert locks == [target_home / ".plugins-directory-migration.lock"]
        assert not (target_home.parent / ".plugins-directory-migration.lock").exists()

    @pytest.mark.unit
    def test_existing_workspace_plugins_win_over_the_legacy_directory(self, tmp_path, monkeypatch):
        """Target-exists-wins: a populated workspace directory is never overwritten."""
        _clear_storage_overrides(monkeypatch)
        from flinttrade_core import workspace

        legacy = tmp_path / "legacy" / "plugins"
        legacy.mkdir(parents=True)
        (legacy / "shared.py").write_text("# stale legacy copy\n", encoding="utf-8")
        target_home = tmp_path / "platform-workspace"
        current = target_home / "plugins"
        current.mkdir(parents=True)
        (current / "shared.py").write_text("# current copy\n", encoding="utf-8")
        monkeypatch.setattr(workspace, "_default_home", lambda: target_home)
        monkeypatch.setattr(workspace, "_legacy_plugins_dir", lambda: legacy)

        target = workspace.plugins_dir()

        assert (target / "shared.py").read_text(encoding="utf-8") == "# current copy\n"
        assert (legacy / "shared.py").read_text(encoding="utf-8") == "# stale legacy copy\n"

    @pytest.mark.unit
    @pytest.mark.parametrize("override", ["FLINTTRADE_HOME", "FLINTTRADE_WORKSPACE_DIR"])
    def test_an_explicit_workspace_override_is_never_seeded(self, tmp_path, monkeypatch, override):
        """A deliberately chosen workspace must not inherit someone else's plugins."""
        _clear_storage_overrides(monkeypatch)
        from flinttrade_core import workspace

        legacy = tmp_path / "legacy" / "plugins"
        legacy.mkdir(parents=True)
        (legacy / "my_plugin.py").write_text("# operator plugin\n", encoding="utf-8")
        chosen = tmp_path / "chosen-workspace"
        chosen.mkdir()
        monkeypatch.setenv(override, str(chosen))
        monkeypatch.setattr(workspace, "_legacy_plugins_dir", lambda: legacy)

        target = workspace.plugins_dir()

        assert target == chosen.resolve() / "plugins"
        assert not target.exists()

    @pytest.mark.unit
    def test_the_loader_defaults_to_the_migrated_directory(self, tmp_path, monkeypatch):
        """PluginLoader() with no argument must go through the migrating resolver."""
        _clear_storage_overrides(monkeypatch)
        from flinttrade_core import plugin_loader, workspace

        legacy = tmp_path / "legacy" / "plugins"
        legacy.mkdir(parents=True)
        (legacy / "my_plugin.py").write_text("# operator plugin\n", encoding="utf-8")
        target_home = tmp_path / "platform-workspace"
        monkeypatch.setattr(workspace, "_default_home", lambda: target_home)
        monkeypatch.setattr(workspace, "_legacy_plugins_dir", lambda: legacy)

        loader = plugin_loader.PluginLoader()

        assert loader.plugin_dir == target_home / "plugins"
        assert (loader.plugin_dir / "my_plugin.py").exists()

    @pytest.mark.unit
    def test_a_failed_migration_never_takes_the_loader_down(self, tmp_path, monkeypatch):
        """A copy that cannot complete is logged; the backend still starts."""
        _clear_storage_overrides(monkeypatch)
        from flinttrade_core import plugin_loader, workspace

        legacy = tmp_path / "legacy" / "plugins"
        legacy.mkdir(parents=True)
        (legacy / "my_plugin.py").write_text("# operator plugin\n", encoding="utf-8")
        target_home = tmp_path / "platform-workspace"
        monkeypatch.setattr(workspace, "_default_home", lambda: target_home)
        monkeypatch.setattr(workspace, "_legacy_plugins_dir", lambda: legacy)
        monkeypatch.setattr(
            workspace.shutil,
            "copytree",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
        )

        loader = plugin_loader.PluginLoader()

        assert loader.plugin_dir == target_home / "plugins"
        assert loader.discover() == []
        assert (legacy / "my_plugin.py").exists()

class TestWorkspaceCopyMachinery:
    """Unit tests for the public copy-once machinery and its Wave-0 additions."""

    @staticmethod
    def _record_filelock_calls(monkeypatch, captured: list[tuple[Path, float]]):
        """Wrap workspace.FileLock so each construction records (path, timeout)."""
        from flinttrade_core import workspace

        real_filelock = workspace.FileLock

        def recording(path, timeout=10, mode=0o600):  # type: ignore[no-untyped-def]
            captured.append((Path(path), float(timeout)))
            return real_filelock(path, timeout=timeout, mode=mode)

        monkeypatch.setattr(workspace, "FileLock", recording)

    @pytest.mark.unit
    def test_legacy_dotdir_is_the_literal_dot_directory(self):
        from flinttrade_core.workspace import legacy_dotdir

        assert legacy_dotdir() == Path.home() / ".flinttrade"

    @pytest.mark.unit
    def test_default_workspace_active_true_without_overrides(self, monkeypatch):
        _clear_storage_overrides(monkeypatch)
        from flinttrade_core.workspace import default_workspace_active

        assert default_workspace_active() is True

    @pytest.mark.unit
    def test_default_workspace_active_false_under_workspace_dir_override(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path / "workspace"))
        from flinttrade_core.workspace import default_workspace_active

        assert default_workspace_active() is False

    @pytest.mark.unit
    def test_default_workspace_active_false_under_home_override(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FLINTTRADE_WORKSPACE_DIR", raising=False)
        monkeypatch.setenv("FLINTTRADE_HOME", str(tmp_path / "home"))
        from flinttrade_core.workspace import default_workspace_active

        assert default_workspace_active() is False

    @pytest.mark.unit
    def test_database_copy_lock_dir_keeps_lock_inside_workspace(self, tmp_path, monkeypatch):
        """A root-level target with lock_dir=target.parent locks inside the workspace, not above it."""
        from flinttrade_core import workspace

        legacy = tmp_path / "legacy" / "shortcuts.duckdb"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"legacy-db")
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        target = workspace_root / "shortcuts.duckdb"
        captured: list[tuple[Path, float]] = []
        self._record_filelock_calls(monkeypatch, captured)

        workspace.copy_legacy_database_once(
            legacy,
            target,
            sidecar_suffixes=(".wal",),
            lock_name=".shortcuts-migration.lock",
            label="keyboard shortcuts store",
            lock_dir=target.parent,
            timeout=60.0,
        )

        assert target.read_bytes() == b"legacy-db"
        assert legacy.read_bytes() == b"legacy-db"
        assert captured == [(workspace_root / ".shortcuts-migration.lock", 60.0)]

    @pytest.mark.unit
    def test_database_copy_default_lock_placement_and_timeout_unchanged(self, tmp_path, monkeypatch):
        """Without lock_dir the six existing callers keep the historical grandparent placement."""
        from flinttrade_core import workspace

        legacy = tmp_path / "legacy" / "data" / "flint.duckdb"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"legacy-db")
        workspace_root = tmp_path / "workspace"
        target = workspace_root / "data" / "flint.duckdb"
        captured: list[tuple[Path, float]] = []
        self._record_filelock_calls(monkeypatch, captured)

        workspace.copy_legacy_database_once(
            legacy,
            target,
            sidecar_suffixes=(".wal",),
            lock_name=".duckdb-migration.lock",
            label="shared DuckDB",
        )

        assert target.read_bytes() == b"legacy-db"
        assert captured == [(workspace_root / ".duckdb-migration.lock", 10.0)]

    @pytest.mark.unit
    def test_directory_copy_lock_dir_keeps_lock_inside_workspace(self, tmp_path, monkeypatch):
        from flinttrade_core import workspace

        legacy = tmp_path / "legacy" / "flows"
        legacy.mkdir(parents=True)
        (legacy / "flow.json").write_text("{}", encoding="utf-8")
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        target = workspace_root / "flows"
        captured: list[tuple[Path, float]] = []
        self._record_filelock_calls(monkeypatch, captured)

        workspace.copy_legacy_directory_once(
            legacy,
            target,
            lock_name=".flows-directory-migration.lock",
            label="flow store",
            lock_dir=target.parent,
            timeout=60.0,
        )

        assert (target / "flow.json").read_text(encoding="utf-8") == "{}"
        assert (legacy / "flow.json").exists()
        assert captured == [(workspace_root / ".flows-directory-migration.lock", 60.0)]

    @pytest.mark.unit
    def test_directory_migration_target_appearing_under_lock_is_sibling_completion(self, tmp_path, monkeypatch):
        """Regression: N-1 herd workers must not raise when the winner migrates first.

        The pre-lock check sees an empty target, a sibling wins the migration
        lock and completes the copy, and this worker then acquires the lock to
        find the target populated. Even with ``conflict_is_error=True`` that is
        completion by a sibling, not a conflict.
        """
        from flinttrade_core import workspace

        legacy = tmp_path / "legacy" / "audit"
        legacy.mkdir(parents=True)
        (legacy / "audit_2026-07-15.jsonl").write_text("chain-record\n", encoding="utf-8")
        workspace_root = tmp_path / "workspace"
        target = workspace_root / "archive" / "audit"
        real_filelock = workspace.FileLock

        class SiblingWinsLock:
            """Populate the target while this worker is queued on the lock."""

            def __init__(self, path, timeout=10, mode=0o600):  # type: ignore[no-untyped-def]
                self._inner = real_filelock(path, timeout=timeout, mode=mode)

            def acquire(self):  # type: ignore[no-untyped-def]
                if not target.exists():
                    target.mkdir(parents=True)
                    (target / "audit_2026-07-15.jsonl").write_text("sibling-chain\n", encoding="utf-8")
                return self._inner.acquire()

        monkeypatch.setattr(workspace, "FileLock", SiblingWinsLock)

        workspace.copy_legacy_directory_once(
            legacy,
            target,
            lock_name=".audit-directory-migration.lock",
            label="audit chain",
            conflict_is_error=True,
        )

        assert (target / "audit_2026-07-15.jsonl").read_text(encoding="utf-8") == "sibling-chain\n"
        assert (legacy / "audit_2026-07-15.jsonl").read_text(encoding="utf-8") == "chain-record\n"

    @pytest.mark.unit
    def test_directory_migration_pre_existing_conflict_still_raises(self, tmp_path):
        """conflict_is_error keeps guarding genuinely divergent pre-existing state."""
        from flinttrade_core import workspace

        legacy = tmp_path / "legacy" / "audit"
        legacy.mkdir(parents=True)
        (legacy / "audit_2026-07-15.jsonl").write_text("legacy-chain\n", encoding="utf-8")
        target = tmp_path / "workspace" / "archive" / "audit"
        target.mkdir(parents=True)
        (target / "audit_2026-07-16.jsonl").write_text("workspace-chain\n", encoding="utf-8")

        with pytest.raises(workspace.WorkspaceStateMigrationError, match="both were preserved"):
            workspace.copy_legacy_directory_once(
                legacy,
                target,
                lock_name=".audit-directory-migration.lock",
                label="audit chain",
                conflict_is_error=True,
            )

        assert (target / "audit_2026-07-16.jsonl").read_text(encoding="utf-8") == "workspace-chain\n"
        assert (legacy / "audit_2026-07-15.jsonl").read_text(encoding="utf-8") == "legacy-chain\n"

    @pytest.mark.unit
    def test_directory_migration_boot_herd_copies_once_and_nobody_raises(self, tmp_path, monkeypatch):
        """Real concurrency: a herd of workers against one legacy tree, under conflict_is_error.

        This is the branch the Gunicorn herd actually hits. The workers do not
        arrive in lockstep — the winner finishes its copy while later workers
        are still evaluating the *pre-lock* probe — so a pre-lock check that
        treated any populated target as a conflict failed every worker but the
        first, and then failed every worker on every subsequent boot as well.

        Eight threads are released together and four more are run afterwards as
        deliberate late arrivals. Exactly one copy must happen and no caller
        may raise.
        """
        from flinttrade_core import workspace

        legacy = tmp_path / "legacy" / "archive" / "audit"
        legacy.mkdir(parents=True)
        (legacy / "audit_2026-07-15.jsonl").write_text("chain-record\n", encoding="utf-8")
        (legacy / "audit_2026-07-16.jsonl").write_text("later-record\n", encoding="utf-8")
        (legacy / ".audit-chain.lock").write_text("", encoding="utf-8")
        target = tmp_path / "workspace" / "archive" / "audit"

        copies = 0
        copies_lock = threading.Lock()
        real_copytree = workspace.shutil.copytree

        def counting_copytree(*args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal copies
            with copies_lock:
                copies += 1
            return real_copytree(*args, **kwargs)

        monkeypatch.setattr(workspace.shutil, "copytree", counting_copytree)

        workers = 8
        start = threading.Barrier(workers)

        def migrate(concurrent: bool) -> BaseException | None:
            if concurrent:
                start.wait()
            try:
                workspace.copy_legacy_directory_once(
                    legacy,
                    target,
                    lock_name=".audit-directory-migration.lock",
                    label="audit chain",
                    excluded_names=frozenset({".audit-chain.lock"}),
                    source_lock_name=".audit-chain.lock",
                    conflict_is_error=True,
                    timeout=60.0,
                )
            except BaseException as exc:  # noqa: BLE001 - the assertion is that none escapes
                return exc
            return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            failures = [outcome for outcome in executor.map(migrate, [True] * workers) if outcome is not None]
        # Late arrivals: the target is already populated before they even probe.
        failures += [outcome for outcome in (migrate(False) for _ in range(4)) if outcome is not None]

        assert not failures, f"herd workers raised: {failures}"
        assert copies == 1, f"expected exactly one copy, got {copies}"
        assert (target / "audit_2026-07-15.jsonl").read_text(encoding="utf-8") == "chain-record\n"
        assert (target / "audit_2026-07-16.jsonl").read_text(encoding="utf-8") == "later-record\n"
        assert not (target / ".audit-chain.lock").exists()
        assert (legacy / "audit_2026-07-15.jsonl").read_text(encoding="utf-8") == "chain-record\n"

    @pytest.mark.unit
    def test_directory_migration_is_silent_on_every_boot_after_the_first(self, tmp_path):
        """A migrated, since-appended-to audit chain is completion, not divergence.

        The copy retains its source, so from the second boot onwards the legacy
        tree and the target are both populated for ever. The target is still the
        migration's own output — its files are the legacy files plus records the
        running app appended — so ``conflict_is_error`` must stay quiet.
        """
        from flinttrade_core import workspace

        legacy = tmp_path / "legacy" / "archive" / "audit"
        legacy.mkdir(parents=True)
        (legacy / "audit_2026-07-15.jsonl").write_text("chain-record\n", encoding="utf-8")
        target = tmp_path / "workspace" / "archive" / "audit"

        for _boot in range(3):
            workspace.copy_legacy_directory_once(
                legacy,
                target,
                lock_name=".audit-directory-migration.lock",
                label="audit chain",
                conflict_is_error=True,
            )
            # The live chain grows between boots; the migrated file is extended
            # and a new day's file appears alongside it.
            with (target / "audit_2026-07-15.jsonl").open("a", encoding="utf-8") as chain:
                chain.write("appended-after-migration\n")
            (target / "audit_2026-07-17.jsonl").write_text("new-day\n", encoding="utf-8")

        assert (target / "audit_2026-07-15.jsonl").read_text(encoding="utf-8").startswith("chain-record\n")
        assert (legacy / "audit_2026-07-15.jsonl").read_text(encoding="utf-8") == "chain-record\n"

    @pytest.mark.unit
    def test_directory_migration_raises_when_a_target_file_diverged(self, tmp_path):
        """A same-named target file that rewrote rather than extended the legacy one is divergent."""
        from flinttrade_core import workspace

        legacy = tmp_path / "legacy" / "archive" / "audit"
        legacy.mkdir(parents=True)
        (legacy / "audit_2026-07-15.jsonl").write_text("legacy-chain\n", encoding="utf-8")
        target = tmp_path / "workspace" / "archive" / "audit"
        target.mkdir(parents=True)
        (target / "audit_2026-07-15.jsonl").write_text("unrelated-chain\n", encoding="utf-8")

        with pytest.raises(workspace.WorkspaceStateMigrationError, match="both were preserved"):
            workspace.copy_legacy_directory_once(
                legacy,
                target,
                lock_name=".audit-directory-migration.lock",
                label="audit chain",
                conflict_is_error=True,
            )

        assert (target / "audit_2026-07-15.jsonl").read_text(encoding="utf-8") == "unrelated-chain\n"
        assert (legacy / "audit_2026-07-15.jsonl").read_text(encoding="utf-8") == "legacy-chain\n"


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
        stderr_lines = result.stderr.strip().splitlines()
        assert stderr_lines[0] == "Master password provisioning failed."
        assert any(line.startswith("  Stage: read-existing-secret") for line in stderr_lines)
        assert any(line.startswith("  Cause: OSError") for line in stderr_lines)
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
        (workspace / cli._VAULT_PROVISION_LOCK_NAME).symlink_to(outside)
        env = {**os.environ, "FLINTTRADE_WORKSPACE_DIR": str(workspace)}

        result = subprocess.run(
            [sys.executable, "-m", "flinttrade_core.cli", "init", "--provision-master-password"],
            check=False,
            capture_output=True,
            env=env,
            text=True,
        )

        assert result.returncode == 1
        stderr_lines = result.stderr.strip().splitlines()
        assert stderr_lines[0] == "Master password provisioning failed."
        assert any(line.startswith("  Stage: acquire-provision-lock") for line in stderr_lines)
        assert any("UnsafeFileLockPathError" in line for line in stderr_lines)
        assert "do-not-touch" not in result.stdout
        assert "do-not-touch" not in result.stderr
        assert outside.read_text(encoding="utf-8") == "do-not-touch"
        assert (workspace / "master_password").exists() is False

    def test_master_password_cli_reports_degraded_when_existing_secret_is_usable(self, tmp_path):
        """A failure over a present, hardened secret exits 3 so callers may continue.

        The backend only needs the secret to exist and be readable. Refusing to
        start when it demonstrably does turns a transient provisioning fault
        into an outage.
        """
        from flinttrade_core import cli
        from flinttrade_core.secure_file import write_secret_text
        from flinttrade_core.workspace import Workspace

        workspace = tmp_path / "ws"
        ws = Workspace(home_dir=workspace)
        ws.initialise()
        write_secret_text(workspace / "master_password", "a" * 64)
        outside = tmp_path / "outside-lock-target"
        outside.write_text("do-not-touch", encoding="utf-8")
        (workspace / cli._VAULT_PROVISION_LOCK_NAME).symlink_to(outside)
        env = {**os.environ, "FLINTTRADE_WORKSPACE_DIR": str(workspace)}

        result = subprocess.run(
            [sys.executable, "-m", "flinttrade_core.cli", "init", "--provision-master-password"],
            check=False,
            capture_output=True,
            env=env,
            text=True,
        )

        assert result.returncode == cli.EXIT_PROVISION_DEGRADED
        assert result.stderr.splitlines()[0] == "Master password provisioning failed."
        assert "credential vault remains usable" in result.stderr
        assert "do-not-touch" not in result.stderr
        assert outside.read_text(encoding="utf-8") == "do-not-touch"

    def test_master_password_cli_verbose_traceback_never_prints_the_secret(self, tmp_path):
        """--verbose output must not contain the secret either.

        A forward guard rather than proof of a past leak: this passes against the
        old unredacted traceback too, because ``traceback.print_exception``
        renders ``str(exc)`` and ``UnicodeDecodeError`` names a byte offset
        without the content. It pins the property so a future change - an
        exception type that does carry the value, or a switch to ``repr`` - is
        caught rather than shipped.
        """
        from flinttrade_core.workspace import Workspace

        workspace = tmp_path / "ws"
        ws = Workspace(home_dir=workspace)
        ws.initialise()
        secret_bytes = b"REAL-MASTER-PASSWORD-abc123deadbeef" + bytes([0xFF, 0xFE])
        password_file = workspace / "master_password"
        password_file.write_bytes(secret_bytes)
        password_file.chmod(0o600)
        env = {**os.environ, "FLINTTRADE_WORKSPACE_DIR": str(workspace)}

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "flinttrade_core.cli",
                "init",
                "--provision-master-password",
                "--verbose",
            ],
            check=False,
            capture_output=True,
            env=env,
            text=True,
        )

        assert result.returncode == 1
        assert "Traceback" in result.stderr, "--verbose should still render a traceback"
        assert "REAL-MASTER-PASSWORD" not in result.stdout
        assert "REAL-MASTER-PASSWORD" not in result.stderr
        assert password_file.read_bytes() == secret_bytes

    def test_master_password_cli_failure_never_prints_a_non_utf8_secret(self, tmp_path):
        """A non-UTF-8 secret must not reach stderr through a decode error.

        ``repr(UnicodeDecodeError)`` embeds the offending bytes - which here are
        the master password - so the reporter must render ``str(exc)`` only.
        """
        from flinttrade_core.workspace import Workspace

        workspace = tmp_path / "ws"
        ws = Workspace(home_dir=workspace)
        ws.initialise()
        secret_bytes = b"REAL-MASTER-PASSWORD-abc123deadbeef\xff\xfe"
        password_file = workspace / "master_password"
        password_file.write_bytes(secret_bytes)
        password_file.chmod(0o600)
        env = {**os.environ, "FLINTTRADE_WORKSPACE_DIR": str(workspace)}

        result = subprocess.run(
            [sys.executable, "-m", "flinttrade_core.cli", "init", "--provision-master-password"],
            check=False,
            capture_output=True,
            env=env,
            text=True,
        )

        assert result.returncode == 1
        assert result.stderr.splitlines()[0] == "Master password provisioning failed."
        assert "REAL-MASTER-PASSWORD" not in result.stdout
        assert "REAL-MASTER-PASSWORD" not in result.stderr
        assert password_file.read_bytes() == secret_bytes


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

        # The atomic write goes through workspace_migrations.durable_replace (an
        # fsync-then-rename helper), not a bare os.replace, so that is the call
        # this test has to break.
        monkeypatch.setattr(
            workspace_migrations,
            "durable_replace",
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
