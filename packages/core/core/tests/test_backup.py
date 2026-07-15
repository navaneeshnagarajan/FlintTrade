"""Tests for packages/core/core/src/backup.py.

Covers: create, restore, list, roundtrip, error paths.

Run with:
    python -m pytest packages/core/core/tests/test_backup.py -v --import-mode=importlib
"""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest

from flinttrade_core.backup import BackupError, WorkspaceBackup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _populate_workspace(ws: Path) -> None:
    """Seed a minimal workspace directory structure for tests."""
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "workspace.json").write_text('{"theme": "graphite"}', encoding="utf-8")
    (ws / "api_analyzer.duckdb").write_bytes(b"\x00" * 16)
    audit = ws / "archive" / "audit"
    audit.mkdir(parents=True)
    (audit / "audit_2026-04-15.jsonl").write_text(
        '{"ts":"2026-04-15","event_type":"LOGIN"}\n', encoding="utf-8"
    )
    (ws / "master_password").write_text("secret", encoding="utf-8")
    (ws / "api_key_pepper").write_text("pepper", encoding="utf-8")
    (ws / "jwt_secret").write_text("jwt", encoding="utf-8")
    (ws / "totp_install_key").write_text("totp", encoding="utf-8")
    (ws / "credentials.db").write_bytes(b"credential-store")
    ticks = ws / "ticks"
    ticks.mkdir()
    (ticks / "tick_data.bin").write_bytes(b"\xff" * 32)


# ---------------------------------------------------------------------------
# WorkspaceBackup.create_backup
# ---------------------------------------------------------------------------


class TestCreateBackup:
    def test_create_returns_path(self, tmp_path: Path) -> None:
        ws = tmp_path / ".flinttrade"
        _populate_workspace(ws)
        bk = WorkspaceBackup(workspace_dir=ws)
        out = tmp_path / "backup.tar.gz"
        result = bk.create_backup(out)
        assert result == out
        assert out.exists()

    def test_create_archive_is_valid_targz(self, tmp_path: Path) -> None:
        ws = tmp_path / ".flinttrade"
        _populate_workspace(ws)
        bk = WorkspaceBackup(workspace_dir=ws)
        out = tmp_path / "backup.tar.gz"
        bk.create_backup(out)
        assert tarfile.is_tarfile(out)

    def test_create_excludes_ticks_by_default(self, tmp_path: Path) -> None:
        ws = tmp_path / ".flinttrade"
        _populate_workspace(ws)
        bk = WorkspaceBackup(workspace_dir=ws)
        out = tmp_path / "backup.tar.gz"
        bk.create_backup(out, include_ticks=False)
        with tarfile.open(out, "r:gz") as tar:
            names = tar.getnames()
        assert not any("ticks" in n for n in names)

    def test_create_includes_ticks_when_requested(self, tmp_path: Path) -> None:
        ws = tmp_path / ".flinttrade"
        _populate_workspace(ws)
        bk = WorkspaceBackup(workspace_dir=ws)
        out = tmp_path / "backup.tar.gz"
        bk.create_backup(out, include_ticks=True)
        with tarfile.open(out, "r:gz") as tar:
            names = tar.getnames()
        assert any("ticks" in n for n in names)

    def test_create_excludes_secrets_and_credentials_by_default(self, tmp_path: Path) -> None:
        ws = tmp_path / ".flinttrade"
        _populate_workspace(ws)
        bk = WorkspaceBackup(workspace_dir=ws)
        out = tmp_path / "backup.tar.gz"
        bk.create_backup(out)
        with tarfile.open(out, "r:gz") as tar:
            names = tar.getnames()
        forbidden = {
            ".flinttrade/master_password",
            ".flinttrade/api_key_pepper",
            ".flinttrade/jwt_secret",
            ".flinttrade/totp_install_key",
            ".flinttrade/credentials.db",
        }
        assert forbidden.isdisjoint(names)

    def test_create_can_include_credential_store_with_explicit_opt_in(self, tmp_path: Path) -> None:
        ws = tmp_path / ".flinttrade"
        _populate_workspace(ws)
        bk = WorkspaceBackup(workspace_dir=ws)
        out = tmp_path / "backup.tar.gz"
        bk.create_backup(out, include_credentials=True)
        with tarfile.open(out, "r:gz") as tar:
            names = set(tar.getnames())
        assert ".flinttrade/credentials.db" in names
        assert ".flinttrade/master_password" not in names

    def test_create_never_includes_live_order_reservation_state(self, tmp_path: Path) -> None:
        ws = tmp_path / ".flinttrade"
        _populate_workspace(ws)
        runtime_files = {
            "order_exposure_reservations.sqlite",
            "order_exposure_reservations.sqlite-journal",
            "order_exposure_reservations.sqlite-shm",
            "order_exposure_reservations.sqlite-wal",
        }
        for name in runtime_files:
            (ws / name).write_bytes(b"live-admission-state")

        out = tmp_path / "backup.tar.gz"
        WorkspaceBackup(workspace_dir=ws).create_backup(out, include_credentials=True)

        with tarfile.open(out, "r:gz") as tar:
            names = {Path(name).name for name in tar.getnames()}
        assert runtime_files.isdisjoint(names)

    def test_create_excludes_only_runtime_order_lifecycle_ledger(self, tmp_path: Path) -> None:
        ws = tmp_path / ".flinttrade"
        _populate_workspace(ws)
        runtime_files = {
            "order-lifecycle.sqlite3",
            "order-lifecycle.sqlite3-journal",
            "order-lifecycle.sqlite3-shm",
            "order-lifecycle.sqlite3-wal",
        }
        retained_files = {
            "order-lifecycle-history.sqlite3",
            "order-lifecycle.sqlite3.snapshot",
        }
        for name in runtime_files | retained_files:
            (ws / name).write_bytes(name.encode())

        out = tmp_path / "backup.tar.gz"
        WorkspaceBackup(workspace_dir=ws).create_backup(out)

        with tarfile.open(out, "r:gz") as tar:
            names = set(tar.getnames())
        assert {f".flinttrade/{name}" for name in runtime_files}.isdisjoint(names)
        assert {f".flinttrade/{name}" for name in retained_files} <= names

    def test_create_embeds_manifest(self, tmp_path: Path) -> None:
        ws = tmp_path / ".flinttrade"
        _populate_workspace(ws)
        bk = WorkspaceBackup(workspace_dir=ws)
        out = tmp_path / "backup.tar.gz"
        bk.create_backup(out)
        with tarfile.open(out, "r:gz") as tar:
            assert "manifest.json" in tar.getnames()
            f = tar.extractfile("manifest.json")
            assert f is not None
            manifest = json.load(f)
        assert "created_at" in manifest
        assert manifest["file_count"] >= 1

    def test_create_raises_if_workspace_missing(self, tmp_path: Path) -> None:
        ws = tmp_path / "nonexistent"
        bk = WorkspaceBackup(workspace_dir=ws)
        with pytest.raises(BackupError, match="does not exist"):
            bk.create_backup(tmp_path / "backup.tar.gz")

    def test_create_makes_parent_directories(self, tmp_path: Path) -> None:
        ws = tmp_path / ".flinttrade"
        _populate_workspace(ws)
        bk = WorkspaceBackup(workspace_dir=ws)
        out = tmp_path / "deep" / "nested" / "backup.tar.gz"
        bk.create_backup(out)
        assert out.exists()


# ---------------------------------------------------------------------------
# WorkspaceBackup.restore_backup
# ---------------------------------------------------------------------------


class TestRestoreBackup:
    def _make_archive(self, tmp_path: Path) -> Path:
        ws = tmp_path / ".flinttrade"
        _populate_workspace(ws)
        bk = WorkspaceBackup(workspace_dir=ws)
        out = tmp_path / "backup.tar.gz"
        bk.create_backup(out)
        return out

    def test_restore_returns_dict(self, tmp_path: Path) -> None:
        archive = self._make_archive(tmp_path)
        bk = WorkspaceBackup(workspace_dir=tmp_path / ".flinttrade")
        target = tmp_path / "restore"
        result = bk.restore_backup(archive, target_dir=target)
        assert "files_restored" in result
        assert "dbs_restored" in result
        assert "total_size_mb" in result

    def test_restore_files_exist_at_target(self, tmp_path: Path) -> None:
        archive = self._make_archive(tmp_path)
        bk = WorkspaceBackup(workspace_dir=tmp_path / ".flinttrade")
        target = tmp_path / "restore"
        bk.restore_backup(archive, target_dir=target)
        # workspace.json should have been restored somewhere under target.
        restored = list(target.rglob("workspace.json"))
        assert len(restored) >= 1

    def test_restore_raises_if_archive_missing(self, tmp_path: Path) -> None:
        bk = WorkspaceBackup()
        with pytest.raises(BackupError, match="not found"):
            bk.restore_backup(tmp_path / "nonexistent.tar.gz")

    def test_restore_raises_on_conflict_without_force(self, tmp_path: Path) -> None:
        archive = self._make_archive(tmp_path)
        bk = WorkspaceBackup(workspace_dir=tmp_path / ".flinttrade")
        target = tmp_path / "restore"
        # First restore.
        bk.restore_backup(archive, target_dir=target, force=False)
        # Second restore should fail because files already exist.
        with pytest.raises(BackupError, match="already exists"):
            bk.restore_backup(archive, target_dir=target, force=False)

    def test_restore_force_overwrites(self, tmp_path: Path) -> None:
        archive = self._make_archive(tmp_path)
        bk = WorkspaceBackup(workspace_dir=tmp_path / ".flinttrade")
        target = tmp_path / "restore"
        bk.restore_backup(archive, target_dir=target)
        # Should not raise with force=True.
        result = bk.restore_backup(archive, target_dir=target, force=True)
        assert result["files_restored"] >= 1

    @pytest.mark.parametrize(
        "archive_name",
        [
            "order_exposure_reservations.sqlite",
            "ORDER_EXPOSURE_RESERVATIONS.SQLITE",
        ],
    )
    def test_restore_never_overwrites_live_order_reservation_state(
        self,
        tmp_path: Path,
        archive_name: str,
    ) -> None:
        stale_ledger = tmp_path / "stale.sqlite"
        stale_ledger.write_bytes(b"stale-admission-state")
        archive = tmp_path / "legacy-backup.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(
                stale_ledger,
                arcname=f".flinttrade/{archive_name}",
            )

        target = tmp_path / "restore"
        live_ledger = target / ".flinttrade" / "order_exposure_reservations.sqlite"
        live_ledger.parent.mkdir(parents=True)
        live_ledger.write_bytes(b"live-admission-state")

        result = WorkspaceBackup(workspace_dir=target / ".flinttrade").restore_backup(
            archive,
            target_dir=target,
            force=True,
        )

        assert live_ledger.read_bytes() == b"live-admission-state"
        assert result["files_restored"] == 0

    def test_restore_excludes_only_runtime_order_lifecycle_ledger(self, tmp_path: Path) -> None:
        runtime_files = {
            "order-lifecycle.sqlite3",
            "order-lifecycle.sqlite3-journal",
            "order-lifecycle.sqlite3-shm",
            "order-lifecycle.sqlite3-wal",
        }
        retained_files = {
            "order-lifecycle-history.sqlite3",
            "order-lifecycle.sqlite3.snapshot",
        }
        archive_source = tmp_path / "archive-source"
        archive_source.mkdir()
        archive = tmp_path / "legacy-backup.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for name in runtime_files | retained_files:
                source = archive_source / name
                source.write_bytes(f"archived:{name}".encode())
                tar.add(source, arcname=f".flinttrade/{name}")

        target = tmp_path / "restore"
        workspace = target / ".flinttrade"
        workspace.mkdir(parents=True)
        live_ledger = workspace / "order-lifecycle.sqlite3"
        live_ledger.write_bytes(b"live-order-state")

        result = WorkspaceBackup(workspace_dir=workspace).restore_backup(
            archive,
            target_dir=target,
            force=True,
        )

        assert live_ledger.read_bytes() == b"live-order-state"
        assert not (workspace / "order-lifecycle.sqlite3-journal").exists()
        assert not (workspace / "order-lifecycle.sqlite3-shm").exists()
        assert not (workspace / "order-lifecycle.sqlite3-wal").exists()
        for name in retained_files:
            assert (workspace / name).read_bytes() == f"archived:{name}".encode()
        assert result["files_restored"] == len(retained_files)


# ---------------------------------------------------------------------------
# WorkspaceBackup.list_backups
# ---------------------------------------------------------------------------


class TestListBackups:
    def test_list_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        bk = WorkspaceBackup()
        assert bk.list_backups(tmp_path) == []

    def test_list_nonexistent_dir_returns_empty(self, tmp_path: Path) -> None:
        bk = WorkspaceBackup()
        assert bk.list_backups(tmp_path / "nope") == []

    def test_list_returns_metadata(self, tmp_path: Path) -> None:
        ws = tmp_path / ".flinttrade"
        _populate_workspace(ws)
        bk = WorkspaceBackup(workspace_dir=ws)
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        bk.create_backup(backup_dir / "b1.tar.gz")
        bk.create_backup(backup_dir / "b2.tar.gz")

        results = bk.list_backups(backup_dir)
        assert len(results) == 2
        for entry in results:
            assert "size_mb" in entry
            assert "filename" in entry


# ---------------------------------------------------------------------------
# Roundtrip
# ---------------------------------------------------------------------------


class TestRoundtrip:
    def test_create_restore_roundtrip(self, tmp_path: Path) -> None:
        """Files in workspace are faithfully recreated after restore."""
        ws = tmp_path / ".flinttrade"
        _populate_workspace(ws)
        original_content = (ws / "workspace.json").read_text(encoding="utf-8")

        bk = WorkspaceBackup(workspace_dir=ws)
        archive = tmp_path / "backup.tar.gz"
        bk.create_backup(archive)

        target = tmp_path / "restored"
        bk.restore_backup(archive, target_dir=target)

        restored_files = list(target.rglob("workspace.json"))
        assert len(restored_files) == 1
        assert restored_files[0].read_text(encoding="utf-8") == original_content
