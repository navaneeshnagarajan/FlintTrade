"""Tests for packages/core/core/src/backup_routes.py (Flask Blueprint).

Mocks WorkspaceBackup entirely so no filesystem archiving occurs.
Covers create, restore, and list backup admin endpoints.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Flask test client with backup blueprint registered using a temp dir.

    Args:
        tmp_path: Pytest-provided temporary directory.
        monkeypatch: Pytest monkeypatch fixture.

    Yields:
        Flask test client.
    """
    from flinttrade_core.backup_routes import create_backup_blueprint

    # The create route mkdirs ~/flint-backups before the (mocked) backup
    # runs — keep the test from touching the real home directory.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(create_backup_blueprint(workspace_dir=tmp_path / "workspace"))
    with flask_app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# POST /admin/backup/create
# ---------------------------------------------------------------------------


class TestBackupCreate:
    def test_create_backup_success(self, client, tmp_path) -> None:
        """Successful backup creation returns path and size_mb.

        Args:
            client:   Flask test client.
            tmp_path: Pytest temp directory.
        """
        fake_archive = tmp_path / "test_backup.tar.gz"
        fake_archive.write_bytes(b"0" * 1024)

        with patch(
            "flinttrade_core.backup.WorkspaceBackup.create_backup",
            return_value=fake_archive,
        ):
            resp = client.post("/v1/admin/backup/create", json={})

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert "path" in data
        assert "size_mb" in data

    def test_create_backup_error_returns_500(self, client) -> None:
        """BackupError during create surfaces as HTTP 500.

        Args:
            client: Flask test client.
        """
        from flinttrade_core.backup import BackupError

        with patch(
            "flinttrade_core.backup.WorkspaceBackup.create_backup",
            side_effect=BackupError("Disk full"),
        ):
            resp = client.post("/v1/admin/backup/create", json={})

        assert resp.status_code == 500
        assert resp.get_json()["status"] == "error"

    def test_create_accepts_absolute_path_inside_backup_root(self, client, tmp_path) -> None:
        """Absolute output paths stay valid when contained by the backup root."""
        target = tmp_path / "home" / "flint-backups" / "custom.tar.gz"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"0" * 1024)

        with patch(
            "flinttrade_core.backup.WorkspaceBackup.create_backup",
            return_value=target,
        ) as create_backup:
            resp = client.post("/v1/admin/backup/create", json={"output_path": str(target)})

        assert resp.status_code == 200
        assert create_backup.call_args.args[0] == target


# ---------------------------------------------------------------------------
# POST /admin/backup/restore
# ---------------------------------------------------------------------------


class TestBackupRestore:
    def test_restore_missing_path_returns_400(self, client) -> None:
        """Restore without a path field returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.post("/v1/admin/backup/restore", json={})
        assert resp.status_code == 400
        assert resp.get_json()["status"] == "error"
        assert "path" in resp.get_json()["message"]

    def test_restore_success(self, client) -> None:
        """Valid restore path calls WorkspaceBackup.restore_backup and returns ok.

        Args:
            client: Flask test client.
        """
        result_payload = {"files_restored": 10, "dbs_restored": 1, "total_size_mb": 2.1}
        with patch(
            "flinttrade_core.backup.WorkspaceBackup.restore_backup",
            return_value=result_payload,
        ):
            resp = client.post(
                "/v1/admin/backup/restore",
                json={"path": "fake_backup.tar.gz"},
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["files_restored"] == 10

    def test_restore_backup_error_returns_500(self, client) -> None:
        """BackupError during restore surfaces as HTTP 500.

        Args:
            client: Flask test client.
        """
        from flinttrade_core.backup import BackupError

        with patch(
            "flinttrade_core.backup.WorkspaceBackup.restore_backup",
            side_effect=BackupError("Archive corrupt"),
        ):
            resp = client.post(
                "/v1/admin/backup/restore",
                json={"path": "bad.tar.gz"},
            )

        assert resp.status_code == 500
        assert resp.get_json()["status"] == "error"

    def test_restore_rejects_archive_outside_backup_root(self, client) -> None:
        resp = client.post(
            "/v1/admin/backup/restore",
            json={"path": "/tmp/fake_backup.tar.gz"},
        )

        assert resp.status_code == 400
        assert resp.get_json()["status"] == "error"


# ---------------------------------------------------------------------------
# GET /admin/backup/list
# ---------------------------------------------------------------------------


class TestBackupList:
    def test_list_returns_empty_when_no_backups(self, client) -> None:
        """List endpoint returns empty backups list when directory is empty.

        Args:
            client: Flask test client.
        """
        with patch(
            "flinttrade_core.backup.WorkspaceBackup.list_backups",
            return_value=[],
        ):
            resp = client.get("/v1/admin/backup/list")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["backups"] == []

    def test_list_returns_backup_entries(self, client) -> None:
        """List endpoint surfaces entries returned by list_backups.

        Args:
            client: Flask test client.
        """
        entries = [{"path": "/tmp/backup1.tar.gz", "size_mb": 1.5}]
        with patch(
            "flinttrade_core.backup.WorkspaceBackup.list_backups",
            return_value=entries,
        ):
            resp = client.get("/v1/admin/backup/list")

        data = resp.get_json()
        assert len(data["backups"]) == 1
        assert data["backups"][0]["path"] == "/tmp/backup1.tar.gz"

    def test_list_rejects_directory_outside_backup_root(self, client) -> None:
        resp = client.get("/v1/admin/backup/list?dir=/tmp")

        assert resp.status_code == 400
        assert resp.get_json()["status"] == "error"
