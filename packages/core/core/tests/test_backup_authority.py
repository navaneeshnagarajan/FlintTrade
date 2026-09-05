"""Ordinary archives cannot capture or restore running authority."""

from __future__ import annotations

import io
import argparse
import json
import os
import stat
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from flinttrade_core.backup import BackupError, WorkspaceBackup, open_backup_archive
from flinttrade_core.workspace import Workspace

_ROOT = Path(__file__).resolve().parents[4]


def _archive(path, members):
    with tarfile.open(path, "w:gz") as tar:
        for name, value in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(value)
            tar.addfile(info, io.BytesIO(value))
    return path


def _market_workspace(path):
    path.mkdir()
    (path / "data" / "bhavcopy" / "equity").mkdir(parents=True)
    (path / "data" / "bhavcopy" / "equity" / "cm05SEP2026bhav.csv").write_text("symbol,exchange\nFIXTURE,NSE\n")
    return WorkspaceBackup(path)


@pytest.mark.parametrize("force", [False, True])
def test_active_workspace_restore_refuses_before_opening_archive(tmp_path, monkeypatch, force):
    ws = tmp_path / "workspace"
    Workspace(ws).initialise()
    backup = tmp_path / "in.tar.gz"
    backup.write_bytes(b"not even an archive")

    def forbidden_open(*_args, **_kwargs):
        pytest.fail("active restore opened an archive")

    monkeypatch.setattr(tarfile, "open", forbidden_open)
    before = (ws / "workspace.json").read_bytes()
    with pytest.raises(BackupError, match="coordinated_restore_unavailable"):
        WorkspaceBackup(ws).restore_backup(backup, force=force)
    assert (ws / "workspace.json").read_bytes() == before


def test_force_restore_cannot_overwrite_concurrent_workspace_cas(tmp_path):
    ws = tmp_path / "workspace"
    workspace = Workspace(ws)
    workspace.initialise()
    archive = _archive(tmp_path / "stale.tar.gz", {"workspace/workspace.json": (ws / "workspace.json").read_bytes()})
    workspace.set("ui.theme", "light")
    before = (ws / "workspace.json").read_bytes()
    with pytest.raises(BackupError, match="coordinated_restore_unavailable"):
        WorkspaceBackup(ws).restore_backup(archive, force=True)
    assert (ws / "workspace.json").read_bytes() == before


@pytest.mark.parametrize(
    "relative",
    [
        "workspace.json",
        "credentials.db",
        "credentials.db-wal",
        "auth.db",
        "totp_auth.duckdb",
        "secrets/provider/key",
        "emergency_intents.sqlite",
        "future-coordinator/receipt.json",
    ],
)
def test_authority_archive_is_refused_before_any_extraction(tmp_path, monkeypatch, relative):
    archive = _archive(tmp_path / "authority.tar.gz", {f"workspace/{relative}": b"pin=1111"})
    target = tmp_path / "restored"

    def forbidden_extract(*_args, **_kwargs):
        pytest.fail("authority archive reached extraction")

    monkeypatch.setattr(tarfile.TarFile, "extractall", forbidden_extract)
    with pytest.raises(BackupError, match="coordinated_restore_unavailable"):
        WorkspaceBackup(tmp_path / "workspace").restore_backup(archive, target_dir=target, force=True)
    assert not target.exists()


def test_credential_optin_is_unavailable_before_file_collection(tmp_path, monkeypatch):
    backup = _market_workspace(tmp_path / "workspace")

    def forbidden_collect(*_args, **_kwargs):
        pytest.fail("authority backup began collection")

    monkeypatch.setattr(backup, "_collect_files", forbidden_collect)
    with pytest.raises(BackupError, match="coordinated_restore_unavailable"):
        backup.create_backup(tmp_path / "out.tar.gz", include_credentials=True)
    assert not (tmp_path / "out.tar.gz").exists()


def test_recursive_registry_prunes_all_sensitive_families_before_walk(tmp_path, monkeypatch):
    ws = tmp_path / "workspace"
    backup = _market_workspace(ws)
    names = [
        "workspace.json",
        "workspace.0.1.0-alpha.bak.json",
        "workspace.0.5.0.bak.json",
        "workspace.0.5.2.bak.json",
        "workspace.1.0.0.bak.json",
        "workspace.1.1.0.bak.json",
        "workspace.1.2.0.bak.json",
        "workspace.brokers.bak.json",
        "credentials.db",
        "credentials.db-wal",
        "credentials.db.pre-sqlite.bak.1-wal",
        "ditto_credentials.db",
        "webhook_secrets.db",
        "auth.db",
        "auth.db-journal",
        "totp_auth.duckdb",
        "totp_auth.duckdb.wal",
        "totp_install_key",
        "jwt_secret",
        "api_key_pepper",
        "safety_gate_secret",
        "master_password",
        "backup-password",
        "backend_instance.lock",
        "action_center.duckdb",
        "daily_pnl_state.sqlite",
        "emergency_intents.sqlite",
        "order-lifecycle.sqlite3",
        "order_exposure_reservations.sqlite",
        ".credentials.db.xyz.tmp",
        "secrets/nested/pin=1111",
        "secrets/.llm_api_key.transaction.old",
        ".lmstudio-retirement.transaction.json",
        "contracts/secrets/provider/key",
        "data/ditto_credentials.db",
        "data/ditto_accounts.sqlite",
        "data/ditto_accounts.sqlite-wal",
        "data/.ditto_accounts.sqlite.fixture.tmp",
        "logs/freeform.log",
    ]
    for name in names:
        path = ws / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"pin=1111")
    original_scandir = os.scandir

    def refuse_secret_traversal(path):
        if Path(path).name == "secrets":
            pytest.fail("collector traversed a complete secret namespace")
        return original_scandir(path)

    monkeypatch.setattr(os, "scandir", refuse_secret_traversal)
    output = backup.create_backup(tmp_path / "ordinary.tar.gz")
    with open_backup_archive(output) as tar:
        contents = []
        for member in tar:
            contents.append(member.name.encode())
            contents.append(json.dumps(member.pax_headers).encode())
            if member.isfile():
                contents.append(tar.extractfile(member).read())
    assert b"pin=1111" not in b"\n".join(contents)
    assert b"cm05SEP2026bhav.csv" in b"\n".join(contents)
    if os.name == "posix":
        assert stat.S_IMODE(output.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "name",
    [
        "extension/private.txt",
        "workspace.1.2.0-copy.bak.json",
        "credentials.db.unknown",
        "data/unknown/private.csv",
        "data/private.csv",
        "data/bhavcopy/equity/unknown/private.csv",
    ],
)
def test_unknown_or_ambiguous_namespace_never_defaults_to_archive_inclusion(tmp_path, name):
    ws = tmp_path / "workspace"
    backup = _market_workspace(ws)
    unknown = ws / name
    unknown.parent.mkdir(parents=True, exist_ok=True)
    unknown.write_bytes(b"pin=1111")
    with pytest.raises(BackupError, match="coordinated_restore_unavailable"):
        backup.create_backup(tmp_path / "out.tar.gz")
    assert not (tmp_path / "out.tar.gz").exists()


def test_disjoint_market_data_roundtrip_remains_available(tmp_path):
    ws = tmp_path / "workspace"
    backup = _market_workspace(ws)
    output = backup.create_backup(tmp_path / "ordinary.tar.gz")
    target = tmp_path / "restored"
    result = backup.restore_backup(output, target_dir=target)
    assert result["files_restored"] == 1
    assert (
        target / "workspace/data/bhavcopy/equity/cm05SEP2026bhav.csv"
    ).read_text() == "symbol,exchange\nFIXTURE,NSE\n"


@pytest.mark.parametrize("operation", ["create", "restore"])
def test_python_cli_propagates_unavailable_code_with_nonzero_exit(tmp_path, monkeypatch, capsys, operation):
    from scripts.backup import _cmd_create, _cmd_restore

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
    archive = tmp_path / "input.tar.gz"
    archive.write_bytes(b"not opened")
    arguments = argparse.Namespace(
        output=str(tmp_path / "out.tar.gz"),
        include_ticks=False,
        include_credentials=True,
        input=str(archive),
        target=None,
        force=True,
    )
    with pytest.raises(SystemExit) as exc:
        (_cmd_create if operation == "create" else _cmd_restore)(arguments)
    assert exc.value.code == 1
    assert "coordinated_restore_unavailable" in capsys.readouterr().err


@pytest.mark.skipif(os.name != "posix", reason="mode bits are POSIX evidence, not Windows DACL verification")
def test_archive_is_owner_only_while_bytes_are_being_written(tmp_path, monkeypatch):
    backup = _market_workspace(tmp_path / "workspace")
    original_addfile = tarfile.TarFile.addfile

    def check_permissions(tar, *args, **kwargs):
        assert stat.S_IMODE(os.fstat(tar.fileobj.fileobj.fileno()).st_mode) == 0o600
        return original_addfile(tar, *args, **kwargs)

    monkeypatch.setattr(tarfile.TarFile, "addfile", check_permissions)
    backup.create_backup(tmp_path / "out.tar.gz")


def test_bounded_reader_rejects_decompression_limit_before_restore(tmp_path, monkeypatch):
    from flinttrade_core import backup as module

    archive = _archive(tmp_path / "large.tar.gz", {"workspace/data/bhavcopy/equity/cm05SEP2026bhav.csv": b"a" * 10240})
    monkeypatch.setattr(module, "MAX_ARCHIVE_UNCOMPRESSED_BYTES", 4096, raising=False)
    target = tmp_path / "restored"
    with pytest.raises(BackupError, match="limit"):
        WorkspaceBackup(tmp_path / "workspace").restore_backup(archive, target_dir=target)
    assert not target.exists()


def test_duplicate_archive_members_refused_before_restore(tmp_path):
    archive = tmp_path / "duplicate.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for content in (b"first", b"second"):
            info = tarfile.TarInfo("workspace/data/bhavcopy/equity/cm05SEP2026bhav.csv")
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    target = tmp_path / "restored"
    with pytest.raises(BackupError, match="duplicate"):
        WorkspaceBackup(tmp_path / "workspace").restore_backup(archive, target_dir=target)
    assert not target.exists()


@pytest.mark.parametrize(
    "script,args",
    [("backup.sh", []), ("restore.sh", []), ("restore.sh", ["--target", "unused", "--snapshot", "fixture"])],
)
@pytest.mark.skipif(os.name == "nt" or shutil.which("bash") is None, reason="POSIX deployment scripts require Bash")
def test_restic_authority_entrypoints_refuse_before_external_actions(tmp_path, script, args):
    # An empty PATH makes any command before the refusal fail observably; bash
    # builtins still work. There is no real restic, service or credential access.
    env = {"PATH": str(tmp_path), "HOME": str(tmp_path), "RESTIC_PASSWORD_FILE": str(tmp_path / "absent-key")}
    result = subprocess.run(
        [shutil.which("bash"), str(_ROOT / "infra/backup" / script), *args],
        env=env,
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "coordinated_restore_unavailable" in result.stderr
    assert "command not found" not in result.stderr
    assert not (tmp_path / "unused").exists()


@pytest.mark.parametrize("args", [[], ["--restart"]])
@pytest.mark.skipif(os.name != "posix" or shutil.which("bash") is None, reason="POSIX script requires Bash")
def test_reset_refuses_before_path_resolution_or_external_actions(tmp_path, args):
    result = subprocess.run(
        [shutil.which("bash"), str(_ROOT / "scripts/reset-flinttrade-state.sh"), *args],
        env={"PATH": str(tmp_path), "HOME": str(tmp_path)},
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "coordinated_restore_unavailable" in result.stderr
    assert "command not found" not in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_alternate_backup_source_cannot_restore_into_configured_active_workspace(tmp_path, monkeypatch):
    active = tmp_path / "active" / "workspace"
    Workspace(active).initialise()
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(active))
    archive = _archive(tmp_path / "ordinary.tar.gz", {"workspace/data/bhavcopy/equity/cm05SEP2026bhav.csv": b"a,b\n"})
    with pytest.raises(BackupError, match="coordinated_restore_unavailable"):
        WorkspaceBackup(tmp_path / "other" / "workspace").restore_backup(archive, target_dir=active.parent, force=True)
    assert not (active / "data/bhavcopy/equity/cm05SEP2026bhav.csv").exists()
