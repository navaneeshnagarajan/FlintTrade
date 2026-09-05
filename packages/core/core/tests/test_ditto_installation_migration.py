"""Task 0 one-time, installation-bound Ditto migration tests."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


def _database(path: Path, value: str, *, leave_wal: bool = False) -> sqlite3.Connection | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    if leave_wal:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE state (value TEXT)")
    conn.execute("INSERT INTO state VALUES (?)", (value,))
    conn.commit()
    if leave_wal:
        assert Path(f"{path}-wal").exists()
        return conn
    conn.close()
    return None


def _value(path: Path) -> str:
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT value FROM state").fetchone()[0]


def test_pytest_installation_state_is_isolated_outside_workspace():
    installation = Path(os.environ["FLINTTRADE_INSTALLATION_STATE_DIR"])
    workspace = Path(os.environ["FLINTTRADE_WORKSPACE_DIR"])

    assert installation != workspace
    assert installation not in workspace.parents
    assert workspace not in installation.parents
    assert installation.name == "installation-state"
    assert "flinttrade-pytest-installation-" in installation.parent.name


def test_same_location_keeps_case_distinct_files_separate_on_case_sensitive_fs(tmp_path):
    from flinttrade_core.workspace import _same_location

    lower = tmp_path / "source.sqlite"
    upper = tmp_path / "SOURCE.sqlite"
    lower.write_bytes(b"lower")
    upper.write_bytes(b"upper")
    if lower.samefile(upper):
        pytest.skip("filesystem is case-insensitive")
    assert _same_location(lower, upper) is False


def test_migration_snapshots_wal_and_consumption_prevents_resurrection(tmp_path):
    from flinttrade_core.workspace import _migrate_legacy_ditto_state

    legacy = tmp_path / "legacy"
    target = tmp_path / "workspace"
    installation = tmp_path / "installation"
    open_connection = _database(legacy / "ditto_accounts.sqlite", "from-wal", leave_wal=True)
    open_vault_connection = _database(legacy / "ditto_credentials.db", "vault-from-wal", leave_wal=True)
    try:
        _migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)
    finally:
        assert open_connection is not None
        open_connection.close()
        assert open_vault_connection is not None
        open_vault_connection.close()

    assert _value(target / "ditto_accounts.sqlite") == "from-wal"
    assert _value(target / "ditto_credentials.db") == "vault-from-wal"
    assert _value(legacy / "ditto_credentials.db") == "vault-from-wal"
    receipt = json.loads((installation / "ditto-legacy-migration.json").read_text(encoding="utf-8"))
    assert receipt["phase"] == "published"
    assert receipt["installation_id"]

    (target / "ditto_accounts.sqlite").unlink()
    (target / "ditto_credentials.db").unlink()
    _migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)
    assert not (target / "ditto_accounts.sqlite").exists()
    assert not (target / "ditto_credentials.db").exists()


def test_consumed_crash_recovers_same_receipt_without_resnapshot(tmp_path):
    from flinttrade_core.workspace import _migrate_legacy_ditto_state

    legacy = tmp_path / "legacy"
    target = tmp_path / "workspace"
    installation = tmp_path / "installation"
    _database(legacy / "ditto_accounts.sqlite", "accounts")
    _database(legacy / "ditto_credentials.db", "vault")

    def crash(phase: str) -> None:
        if phase == "consumed":
            raise RuntimeError("simulated crash")

    with pytest.raises(RuntimeError, match="simulated crash"):
        _migrate_legacy_ditto_state(
            legacy,
            target,
            installation_state_root=installation,
            phase_hook=crash,
        )
    receipt_before = (installation / "ditto-legacy-migration.json").read_bytes()
    assert not (target / "ditto_accounts.sqlite").exists()

    _migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)
    receipt_after = json.loads((installation / "ditto-legacy-migration.json").read_text(encoding="utf-8"))
    assert json.loads(receipt_before)["receipt_id"] == receipt_after["receipt_id"]
    assert _value(target / "ditto_accounts.sqlite") == "accounts"


def test_snapshotted_crash_wal_generation_drift_never_publishes_stale_snapshot(tmp_path):
    from flinttrade_core import workspace

    legacy = tmp_path / "legacy"
    target = tmp_path / "target"
    installation = tmp_path / "installation"
    connection = _database(legacy / "ditto_accounts.sqlite", "accounts", leave_wal=True)
    assert connection is not None
    try:
        with pytest.raises(RuntimeError, match="crash"):
            workspace._migrate_legacy_ditto_state(
                legacy,
                target,
                installation_state_root=installation,
                phase_hook=lambda phase: (_ for _ in ()).throw(RuntimeError("crash"))
                if phase == "snapshotted"
                else None,
            )
        wal = Path(f"{legacy / 'ditto_accounts.sqlite'}-wal")
        original = wal.stat()
        payload = wal.read_bytes()
        replacement_byte = b"X" if payload[:1] != b"X" else b"Y"
        wal.write_bytes(replacement_byte + payload[1:])
        os.utime(wal, ns=(original.st_atime_ns, original.st_mtime_ns))

        with pytest.raises(workspace.WorkspaceStateMigrationError, match="changed after snapshot"):
            workspace._migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)
        assert not (target / "ditto_accounts.sqlite").exists()
    finally:
        connection.close()


def test_snapshotted_accounts_only_receipt_rejects_newly_appeared_vault(tmp_path):
    from flinttrade_core import workspace

    legacy = tmp_path / "legacy"
    target = tmp_path / "target"
    installation = tmp_path / "installation"
    _database(legacy / "ditto_accounts.sqlite", "accounts")
    with pytest.raises(RuntimeError, match="crash"):
        workspace._migrate_legacy_ditto_state(
            legacy,
            target,
            installation_state_root=installation,
            phase_hook=lambda phase: (_ for _ in ()).throw(RuntimeError("crash"))
            if phase == "snapshotted"
            else None,
        )
    _database(legacy / "ditto_credentials.db", "late-vault")

    with pytest.raises(workspace.WorkspaceStateMigrationError, match="source set changed"):
        workspace._migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)

    assert not (target / "ditto_accounts.sqlite").exists()
    assert not (target / "ditto_credentials.db").exists()


def test_crash_between_vault_and_accounts_publication_recovers_pair(tmp_path):
    from flinttrade_core.workspace import _migrate_legacy_ditto_state

    legacy = tmp_path / "legacy"
    target = tmp_path / "workspace"
    installation = tmp_path / "installation"
    _database(legacy / "ditto_accounts.sqlite", "accounts")
    _database(legacy / "ditto_credentials.db", "vault")

    def crash(phase: str) -> None:
        if phase == "published:credentials":
            raise RuntimeError("crash-between-publications")

    with pytest.raises(RuntimeError, match="crash-between-publications"):
        _migrate_legacy_ditto_state(
            legacy,
            target,
            installation_state_root=installation,
            phase_hook=crash,
        )
    assert _value(target / "ditto_credentials.db") == "vault"
    assert not (target / "ditto_accounts.sqlite").exists()
    receipt_id = json.loads((installation / "ditto-legacy-migration.json").read_text())["receipt_id"]

    _migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)
    recovered = json.loads((installation / "ditto-legacy-migration.json").read_text())
    assert recovered["receipt_id"] == receipt_id
    assert recovered["phase"] == "published"
    assert _value(target / "ditto_accounts.sqlite") == "accounts"


def test_crash_after_candidate_fsync_recovers_without_resnapshot(tmp_path, monkeypatch):
    from flinttrade_core import workspace

    legacy = tmp_path / "legacy"
    target = tmp_path / "workspace"
    installation = tmp_path / "installation"
    _database(legacy / "ditto_accounts.sqlite", "accounts")
    _database(legacy / "ditto_credentials.db", "vault")

    with pytest.raises(RuntimeError, match="durability-boundary"):
        workspace._migrate_legacy_ditto_state(
            legacy,
            target,
            installation_state_root=installation,
            phase_hook=lambda phase: (_ for _ in ()).throw(RuntimeError("durability-boundary"))
            if phase == "durable:credentials"
            else None,
        )
    receipt = json.loads((installation / "ditto-legacy-migration.json").read_text())
    candidate = target / f".ditto_credentials.db.{receipt['receipt_id']}.publishing"
    assert candidate.is_file()
    assert not (target / "ditto_credentials.db").exists()

    real_copy = workspace.copy_owner_owned_file_durable
    recopied: list[Path] = []

    def record_recopy(source: Path, destination: Path) -> None:
        recopied.append(destination)
        real_copy(source, destination)

    monkeypatch.setattr(workspace, "copy_owner_owned_file_durable", record_recopy)
    workspace._migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)
    assert candidate in recopied
    assert _value(target / "ditto_credentials.db") == "vault"
    assert _value(target / "ditto_accounts.sqlite") == "accounts"


def test_truncated_recovered_publish_candidate_is_durably_rebuilt(tmp_path):
    from flinttrade_core import workspace

    legacy = tmp_path / "legacy"
    target = tmp_path / "target"
    installation = tmp_path / "installation"
    _database(legacy / "ditto_accounts.sqlite", "accounts")
    with pytest.raises(RuntimeError, match="crash"):
        workspace._migrate_legacy_ditto_state(
            legacy,
            target,
            installation_state_root=installation,
            phase_hook=lambda phase: (_ for _ in ()).throw(RuntimeError("crash"))
            if phase == "durable:accounts"
            else None,
        )
    receipt = json.loads((installation / "ditto-legacy-migration.json").read_text())
    candidate = target / f".ditto_accounts.sqlite.{receipt['receipt_id']}.publishing"
    candidate.write_bytes(b"truncated")
    candidate.chmod(0o600)

    workspace._migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)

    assert _value(target / "ditto_accounts.sqlite") == "accounts"
    assert not candidate.exists()


def test_empty_unhardened_recovered_publish_candidate_is_durably_rebuilt(tmp_path, monkeypatch):
    from flinttrade_core import workspace

    legacy = tmp_path / "legacy"
    target = tmp_path / "target"
    installation = tmp_path / "installation"
    _database(legacy / "ditto_accounts.sqlite", "accounts")
    with pytest.raises(RuntimeError, match="crash"):
        workspace._migrate_legacy_ditto_state(
            legacy,
            target,
            installation_state_root=installation,
            phase_hook=lambda phase: (_ for _ in ()).throw(RuntimeError("crash"))
            if phase == "consumed"
            else None,
        )
    receipt = json.loads((installation / "ditto-legacy-migration.json").read_text())
    candidate = target / f".ditto_accounts.sqlite.{receipt['receipt_id']}.publishing"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(b"")
    if os.name != "nt":
        candidate.chmod(0o644)
        monkeypatch.setattr(workspace, "_windows_publish_candidate_pre_dacl_recovery_required", lambda: True)

    workspace._migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)

    assert _value(target / "ditto_accounts.sqlite") == "accounts"
    assert not candidate.exists()


def test_nonempty_unhardened_recovered_publish_candidate_remains_fatal(tmp_path, monkeypatch):
    from flinttrade_core import workspace

    legacy = tmp_path / "legacy"
    target = tmp_path / "target"
    installation = tmp_path / "installation"
    _database(legacy / "ditto_accounts.sqlite", "accounts")
    with pytest.raises(RuntimeError, match="crash"):
        workspace._migrate_legacy_ditto_state(
            legacy,
            target,
            installation_state_root=installation,
            phase_hook=lambda phase: (_ for _ in ()).throw(RuntimeError("crash"))
            if phase == "consumed"
            else None,
        )
    receipt = json.loads((installation / "ditto-legacy-migration.json").read_text())
    candidate = target / f".ditto_accounts.sqlite.{receipt['receipt_id']}.publishing"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(b"not-a-pre-dacl-empty-file")
    if os.name != "nt":
        candidate.chmod(0o644)
        monkeypatch.setattr(workspace, "_windows_publish_candidate_pre_dacl_recovery_required", lambda: True)

    with pytest.raises(workspace.WorkspaceStateMigrationError, match="candidate is unsafe"):
        workspace._migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)

    assert candidate.read_bytes() == b"not-a-pre-dacl-empty-file"
    assert not (target / "ditto_accounts.sqlite").exists()


@pytest.mark.parametrize("unsafe_kind", ["symlink", "hardlink"])
def test_unsafe_recovered_publish_candidate_is_rejected(tmp_path, unsafe_kind):
    from flinttrade_core import workspace

    legacy = tmp_path / "legacy"
    target = tmp_path / "target"
    installation = tmp_path / "installation"
    _database(legacy / "ditto_accounts.sqlite", "accounts")
    with pytest.raises(RuntimeError, match="crash"):
        workspace._migrate_legacy_ditto_state(
            legacy,
            target,
            installation_state_root=installation,
            phase_hook=lambda phase: (_ for _ in ()).throw(RuntimeError("crash")) if phase == "consumed" else None,
        )
    receipt = json.loads((installation / "ditto-legacy-migration.json").read_text())
    candidate = target / f".ditto_accounts.sqlite.{receipt['receipt_id']}.publishing"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    victim = tmp_path / "victim"
    victim.write_bytes(b"untrusted")
    victim.chmod(0o600)
    if unsafe_kind == "symlink":
        candidate.symlink_to(victim)
    else:
        os.link(victim, candidate)

    with pytest.raises(workspace.WorkspaceStateMigrationError, match="candidate is unsafe"):
        workspace._migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)
    assert victim.read_bytes() == b"untrusted"


def test_snapshot_file_and_parent_are_fsynced_before_snapshotted_receipt(tmp_path, monkeypatch):
    from flinttrade_core import workspace

    legacy = tmp_path / "legacy"
    target = tmp_path / "target"
    installation = tmp_path / "installation"
    _database(legacy / "ditto_accounts.sqlite", "accounts")
    events: list[str] = []
    real_fsync = workspace.os.fsync
    real_parent_fsync = workspace.fsync_parent_directory
    real_receipt_write = workspace._write_ditto_receipt

    def record_fsync(descriptor: int) -> None:
        events.append("file-fsync")
        real_fsync(descriptor)

    def record_parent_fsync(path: Path) -> None:
        events.append("parent-fsync")
        real_parent_fsync(path)

    def record_receipt(path: Path, receipt: dict[str, object]) -> None:
        if receipt["phase"] == "snapshotted":
            events.append("snapshotted-receipt")
        real_receipt_write(path, receipt)

    monkeypatch.setattr(workspace.os, "fsync", record_fsync)
    monkeypatch.setattr(workspace, "fsync_parent_directory", record_parent_fsync)
    monkeypatch.setattr(workspace, "_write_ditto_receipt", record_receipt)

    workspace._migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)

    receipt_index = events.index("snapshotted-receipt")
    assert events.index("file-fsync") < receipt_index
    assert events.index("parent-fsync") < receipt_index


def test_fresh_target_directories_are_barriered_before_publish_and_terminal_receipt(tmp_path, monkeypatch):
    from flinttrade_core import workspace

    legacy = tmp_path / "legacy"
    target = tmp_path / "target"
    installation = tmp_path / "installation"
    _database(legacy / "ditto_accounts.sqlite", "accounts")
    events: list[str] = []
    real_barrier = workspace._durably_barrier_directory_entry
    real_receipt_write = workspace._write_ditto_receipt

    def record_barrier(path: Path, *, newly_created: bool) -> None:
        events.append(f"barrier:{path}:{newly_created}")
        real_barrier(path, newly_created=newly_created)

    def record_receipt(path: Path, receipt: dict[str, object]) -> None:
        if receipt["phase"] == "published":
            events.append("terminal-receipt")
        real_receipt_write(path, receipt)

    monkeypatch.setattr(workspace, "_durably_barrier_directory_entry", record_barrier)
    monkeypatch.setattr(workspace, "_write_ditto_receipt", record_receipt)

    workspace._migrate_legacy_ditto_state(
        legacy,
        target,
        installation_state_root=installation,
        phase_hook=lambda phase: events.append(phase),
    )

    published = events.index("published:accounts")
    terminal = events.index("terminal-receipt")
    target_barriers = [index for index, event in enumerate(events) if event.startswith(f"barrier:{target}:")]
    assert target_barriers
    assert min(target_barriers) < published
    assert any(published < index < terminal for index in target_barriers)


def test_windows_directory_barrier_uses_write_through_child_transaction(tmp_path, monkeypatch):
    from flinttrade_core import workspace

    directory = tmp_path / "target"
    directory.mkdir()
    events: list[tuple[str, Path]] = []
    monkeypatch.setattr(workspace, "_windows_directory_barrier_required", lambda: True)
    monkeypatch.setattr(
        workspace,
        "write_secret_text",
        lambda path, _value: events.append(("write-through-publish", path)),
    )
    monkeypatch.setattr(
        workspace,
        "durable_unlink",
        lambda path: events.append(("durable-retire", path)),
    )

    workspace._durably_barrier_directory_entry(directory, newly_created=True)

    assert [event for event, _path in events] == ["write-through-publish", "durable-retire"]
    assert events[0][1].parent == directory
    assert events[1][1] == events[0][1]


def test_windows_snapshot_seal_opens_flush_capable_descriptor(tmp_path, monkeypatch):
    from flinttrade_core import workspace

    snapshot = tmp_path / "snapshot.sqlite"
    _database(snapshot, "snapshot")
    snapshot.chmod(0o600)
    real_open = workspace.os.open
    observed_flags: list[int] = []

    def record_open(path, flags, *args, **kwargs):  # type: ignore[no-untyped-def]
        if Path(path) == snapshot:
            observed_flags.append(flags)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(workspace, "_windows_snapshot_flush_required", lambda: True)
    monkeypatch.setattr(workspace.os, "open", record_open)

    workspace._durably_seal_sqlite_snapshot(snapshot)

    assert observed_flags
    assert any(flags & workspace.os.O_RDWR for flags in observed_flags)


def test_new_publish_candidate_digest_is_checked_before_exposure(tmp_path, monkeypatch):
    from flinttrade_core import workspace

    legacy = tmp_path / "legacy"
    target = tmp_path / "target"
    installation = tmp_path / "installation"
    _database(legacy / "ditto_accounts.sqlite", "accounts")
    real_copy = workspace.copy_owner_owned_file_durable
    exposed = False

    def corrupt_after_copy(source: Path, destination: Path) -> None:
        real_copy(source, destination)
        destination.write_bytes(b"corrupt-after-durable-copy")
        destination.chmod(0o600)

    monkeypatch.setattr(workspace, "copy_owner_owned_file_durable", corrupt_after_copy)
    real_replace = workspace.durable_replace

    def replace(source: Path, destination: Path) -> None:
        nonlocal exposed
        if destination.parent == target:
            exposed = True
        real_replace(source, destination)

    monkeypatch.setattr(workspace, "durable_replace", replace)

    with pytest.raises(workspace.WorkspaceStateMigrationError, match="candidate digest changed"):
        workspace._migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)

    assert exposed is False
    assert not (target / "ditto_accounts.sqlite").exists()


def test_concurrent_migration_has_one_receipt_and_complete_pair(tmp_path):
    from flinttrade_core.workspace import _migrate_legacy_ditto_state

    legacy = tmp_path / "legacy"
    target = tmp_path / "workspace"
    installation = tmp_path / "installation"
    _database(legacy / "ditto_accounts.sqlite", "accounts")
    _database(legacy / "ditto_credentials.db", "vault")

    def migrate() -> None:
        _migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: migrate(), range(8)))

    assert _value(target / "ditto_accounts.sqlite") == "accounts"
    assert _value(target / "ditto_credentials.db") == "vault"
    assert json.loads((installation / "ditto-legacy-migration.json").read_text())["phase"] == "published"


def test_in_place_source_deleted_after_consumed_is_restored_from_receipt(tmp_path):
    from flinttrade_core import workspace

    legacy = tmp_path / "data"
    installation = tmp_path / "installation"
    accounts = legacy / "ditto_accounts.sqlite"
    _database(accounts, "accounts")
    with pytest.raises(RuntimeError, match="crash"):
        workspace._migrate_legacy_ditto_state(
            legacy,
            legacy,
            installation_state_root=installation,
            target_vault_path=tmp_path / "workspace" / "ditto_credentials.db",
            phase_hook=lambda phase: (_ for _ in ()).throw(RuntimeError("crash")) if phase == "consumed" else None,
        )
    accounts.unlink()

    workspace._migrate_legacy_ditto_state(
        legacy,
        legacy,
        installation_state_root=installation,
        target_vault_path=tmp_path / "workspace" / "ditto_credentials.db",
    )

    assert _value(accounts) == "accounts"
    assert json.loads((installation / "ditto-legacy-migration.json").read_text())["phase"] == "published"


@pytest.mark.parametrize("in_place", [False, True])
def test_missing_target_main_with_stale_sidecar_fails_before_publication(tmp_path, in_place):
    from flinttrade_core import workspace

    legacy = tmp_path / "data"
    target = legacy if in_place else tmp_path / "target"
    installation = tmp_path / "installation"
    accounts = legacy / "ditto_accounts.sqlite"
    _database(accounts, "accounts")
    with pytest.raises(RuntimeError, match="crash"):
        workspace._migrate_legacy_ditto_state(
            legacy,
            target,
            installation_state_root=installation,
            target_vault_path=tmp_path / "workspace" / "ditto_credentials.db",
            phase_hook=lambda phase: (_ for _ in ()).throw(RuntimeError("crash")) if phase == "consumed" else None,
        )
    destination = target / "ditto_accounts.sqlite"
    if destination.exists():
        destination.unlink()
    stale_wal = Path(f"{destination}-wal")
    stale_wal.parent.mkdir(parents=True, exist_ok=True)
    stale_wal.write_bytes(b"stale-unbound-wal")

    with pytest.raises(workspace.WorkspaceStateMigrationError, match="sidecar"):
        workspace._migrate_legacy_ditto_state(
            legacy,
            target,
            installation_state_root=installation,
            target_vault_path=tmp_path / "workspace" / "ditto_credentials.db",
        )

    assert not destination.exists()
    assert stale_wal.read_bytes() == b"stale-unbound-wal"


def test_prior_published_exact_target_main_with_stale_sidecar_is_rejected(tmp_path):
    from flinttrade_core import workspace

    legacy = tmp_path / "legacy"
    target = tmp_path / "target"
    installation = tmp_path / "installation"
    _database(legacy / "ditto_accounts.sqlite", "accounts")
    with pytest.raises(RuntimeError, match="crash"):
        workspace._migrate_legacy_ditto_state(
            legacy,
            target,
            installation_state_root=installation,
            phase_hook=lambda phase: (_ for _ in ()).throw(RuntimeError("crash"))
            if phase == "published:accounts"
            else None,
        )
    stale_wal = Path(f"{target / 'ditto_accounts.sqlite'}-wal")
    stale_wal.write_bytes(b"stale-target-wal")

    with pytest.raises(workspace.WorkspaceStateMigrationError, match="sidecar"):
        workspace._migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode semantics")
def test_prior_published_matching_target_with_broad_mode_is_rejected(tmp_path):
    from flinttrade_core import workspace

    legacy = tmp_path / "legacy"
    target = tmp_path / "target"
    installation = tmp_path / "installation"
    _database(legacy / "ditto_accounts.sqlite", "accounts")
    with pytest.raises(RuntimeError, match="crash"):
        workspace._migrate_legacy_ditto_state(
            legacy,
            target,
            installation_state_root=installation,
            phase_hook=lambda phase: (_ for _ in ()).throw(RuntimeError("crash"))
            if phase == "published:accounts"
            else None,
        )
    published = target / "ditto_accounts.sqlite"
    published.chmod(0o644)

    with pytest.raises(workspace.WorkspaceStateMigrationError, match="ambiguous"):
        workspace._migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)


def test_preparing_retry_discards_stale_snapshot_family(tmp_path, monkeypatch):
    from flinttrade_core import workspace

    legacy = tmp_path / "legacy"
    target = tmp_path / "target"
    installation = tmp_path / "installation"
    _database(legacy / "ditto_accounts.sqlite", "accounts")
    real_snapshot = workspace._sqlite_snapshot

    def leave_stale_snapshot_family(_source: Path, snapshot: Path) -> None:
        snapshot.write_bytes(b"partial-snapshot")
        Path(f"{snapshot}-journal").write_bytes(b"stale-journal")
        raise OSError("crash in backup")

    with monkeypatch.context() as m:
        m.setattr(workspace, "_sqlite_snapshot", leave_stale_snapshot_family)
        with pytest.raises(workspace.WorkspaceStateMigrationError, match="source retained"):
            workspace._migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)

    snapshot = next(installation.glob("*.snapshot"))
    assert Path(f"{snapshot}-journal").exists()
    workspace._sqlite_snapshot = real_snapshot
    workspace._migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)
    assert _value(target / "ditto_accounts.sqlite") == "accounts"
    assert not Path(f"{snapshot}-journal").exists()


def test_in_place_source_change_after_consumed_is_ambiguous(tmp_path):
    from flinttrade_core import workspace

    legacy = tmp_path / "data"
    installation = tmp_path / "installation"
    accounts = legacy / "ditto_accounts.sqlite"
    _database(accounts, "accounts")
    with pytest.raises(RuntimeError, match="crash"):
        workspace._migrate_legacy_ditto_state(
            legacy,
            legacy,
            installation_state_root=installation,
            target_vault_path=tmp_path / "workspace" / "ditto_credentials.db",
            phase_hook=lambda phase: (_ for _ in ()).throw(RuntimeError("crash")) if phase == "consumed" else None,
        )
    with sqlite3.connect(accounts) as connection:
        connection.execute("UPDATE state SET value='changed'")

    with pytest.raises(workspace.WorkspaceStateMigrationError, match="changed after snapshot"):
        workspace._migrate_legacy_ditto_state(
            legacy,
            legacy,
            installation_state_root=installation,
            target_vault_path=tmp_path / "workspace" / "ditto_credentials.db",
        )
    assert _value(accounts) == "changed"


def test_sqlite_source_identity_rejects_replaced_same_metadata_wal(tmp_path):
    from flinttrade_core import workspace

    source = tmp_path / "source.sqlite"
    snapshot = tmp_path / "snapshot.sqlite"
    _database(source, "source")
    _database(snapshot, "snapshot")
    wal = Path(f"{source}-wal")
    wal.write_bytes(b"same-sized-wal-generation")
    identity = workspace._sqlite_source_identity(source, snapshot)
    original = wal.stat()
    replacement = tmp_path / "replacement-wal"
    replacement.write_bytes(wal.read_bytes())
    os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
    replacement.replace(wal)

    assert wal.stat().st_size == original.st_size
    assert wal.stat().st_mtime_ns == original.st_mtime_ns
    assert wal.stat().st_ino != original.st_ino
    assert workspace._sqlite_source_matches_identity(source, identity) is False


@pytest.mark.parametrize("member", ["main", "wal"])
def test_sqlite_source_identity_rejects_same_length_rewrite_with_restored_mtime(tmp_path, member):
    from flinttrade_core import workspace

    source = tmp_path / "source.sqlite"
    snapshot = tmp_path / "snapshot.sqlite"
    _database(source, "source")
    _database(snapshot, "snapshot")
    wal = Path(f"{source}-wal")
    wal.write_bytes(b"original-wal-generation")
    identity = workspace._sqlite_source_identity(source, snapshot)
    changed = source if member == "main" else wal
    original = changed.stat()
    original_bytes = changed.read_bytes()
    replacement_byte = b"X" if original_bytes[:1] != b"X" else b"Y"
    changed.write_bytes(replacement_byte + original_bytes[1:])
    os.utime(changed, ns=(original.st_atime_ns, original.st_mtime_ns))

    assert changed.stat().st_size == original.st_size
    assert changed.stat().st_mtime_ns == original.st_mtime_ns
    assert workspace._sqlite_source_matches_identity(source, identity) is False


def test_sqlite_source_identity_accepts_unchanged_family_resume(tmp_path):
    from flinttrade_core import workspace

    source = tmp_path / "source.sqlite"
    snapshot = tmp_path / "snapshot.sqlite"
    _database(source, "source")
    _database(snapshot, "snapshot")
    Path(f"{source}-wal").write_bytes(b"stable-wal")
    Path(f"{source}-shm").write_bytes(b"stable-shm")
    identity = workspace._sqlite_source_identity(source, snapshot)

    assert workspace._sqlite_source_matches_identity(source, identity) is True


def test_linux_in_place_quarantine_is_terminal_on_second_call(tmp_path):
    from flinttrade_core import workspace

    legacy = tmp_path / "data"
    installation = tmp_path / "installation"
    target_vault = tmp_path / "workspace" / "ditto_credentials.db"
    _database(legacy / "ditto_accounts.sqlite", "accounts")
    _database(legacy / "ditto_credentials.db", "legacy-vault")
    _database(target_vault, "existing-vault")

    workspace._migrate_legacy_ditto_state(
        legacy,
        legacy,
        installation_state_root=installation,
        target_vault_path=target_vault,
    )
    workspace._migrate_legacy_ditto_state(
        legacy,
        legacy,
        installation_state_root=installation,
        target_vault_path=target_vault,
    )

    receipt = json.loads((installation / "ditto-legacy-migration.json").read_text())
    assert receipt["phase"] == "quarantined"
    assert receipt["sources"]["accounts"]["in_place"] is True


def test_target_failure_preserves_sources_and_recovery_candidates(tmp_path, monkeypatch):
    from flinttrade_core import workspace

    legacy = tmp_path / "legacy"
    target = tmp_path / "workspace"
    installation = tmp_path / "installation"
    _database(legacy / "ditto_accounts.sqlite", "accounts")
    _database(legacy / "ditto_credentials.db", "vault")
    real_replace = workspace.durable_replace

    def fail_target(source: Path, destination: Path) -> None:
        if destination.parent == target:
            raise OSError("target unavailable")
        real_replace(source, destination)

    monkeypatch.setattr(workspace, "durable_replace", fail_target)
    with pytest.raises(workspace.WorkspaceStateMigrationError, match="preserve legacy Ditto"):
        workspace._migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)

    assert (legacy / "ditto_accounts.sqlite").exists()
    assert (legacy / "ditto_credentials.db").exists()
    assert list(installation.glob("*.snapshot"))


@pytest.mark.parametrize("boundary", ["preparing", "snapshotted", "consumed", "published"])
def test_restart_recovers_or_accepts_every_journal_boundary(tmp_path, boundary):
    from flinttrade_core.workspace import _migrate_legacy_ditto_state

    root = tmp_path / boundary
    legacy = root / "legacy"
    target = root / "workspace"
    installation = root / "installation"
    _database(legacy / "ditto_accounts.sqlite", "accounts")

    def crash(phase: str) -> None:
        if phase == boundary:
            raise RuntimeError(f"crash-{boundary}")

    with pytest.raises(RuntimeError, match=f"crash-{boundary}"):
        _migrate_legacy_ditto_state(
            legacy,
            target,
            installation_state_root=installation,
            phase_hook=crash,
        )
    receipt_id = json.loads((installation / "ditto-legacy-migration.json").read_text())["receipt_id"]
    _migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)
    recovered = json.loads((installation / "ditto-legacy-migration.json").read_text())
    assert recovered["receipt_id"] == receipt_id
    assert recovered["phase"] == "published"
    assert _value(target / "ditto_accounts.sqlite") == "accounts"


def test_missing_required_source_is_noop_and_optional_vault_may_be_absent(tmp_path):
    from flinttrade_core.workspace import _migrate_legacy_ditto_state

    empty_installation = tmp_path / "empty-installation"
    _migrate_legacy_ditto_state(
        tmp_path / "empty-legacy",
        tmp_path / "empty-target",
        installation_state_root=empty_installation,
    )
    assert not (empty_installation / "ditto-legacy-migration.json").exists()

    legacy = tmp_path / "legacy"
    target = tmp_path / "target"
    installation = tmp_path / "installation"
    _database(legacy / "ditto_accounts.sqlite", "accounts-only")
    _migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)
    assert _value(target / "ditto_accounts.sqlite") == "accounts-only"
    assert not (target / "ditto_credentials.db").exists()

    vault_only = tmp_path / "vault-only"
    vault_only_installation = tmp_path / "vault-only-installation"
    _database(vault_only / "ditto_credentials.db", "orphan-vault")
    _migrate_legacy_ditto_state(
        vault_only,
        tmp_path / "vault-only-target",
        installation_state_root=vault_only_installation,
    )
    vault_receipt = json.loads((vault_only_installation / "ditto-legacy-migration.json").read_text())
    assert vault_receipt["phase"] == "quarantined"
    assert set(vault_receipt["snapshots"]) == {"credentials"}
    assert _value(vault_only / "ditto_credentials.db") == "orphan-vault"


@pytest.mark.parametrize("family", ["ditto_accounts.sqlite", "ditto_credentials.db"])
def test_orphan_legacy_source_sidecar_without_main_fails_closed(tmp_path, family):
    from flinttrade_core import workspace

    legacy = tmp_path / "legacy"
    legacy.mkdir()
    orphan = Path(f"{legacy / family}-wal")
    orphan.write_bytes(b"orphan-wal")

    with pytest.raises(workspace.WorkspaceStateMigrationError, match="orphan sidecar"):
        workspace._migrate_legacy_ditto_state(
            legacy,
            tmp_path / "target",
            installation_state_root=tmp_path / "installation",
        )

    assert orphan.read_bytes() == b"orphan-wal"
    assert not (tmp_path / "target" / family).exists()


def test_preexisting_target_quarantines_ambiguous_originals(tmp_path):
    from flinttrade_core.workspace import _migrate_legacy_ditto_state

    legacy = tmp_path / "legacy"
    target = tmp_path / "target"
    installation = tmp_path / "installation"
    _database(legacy / "ditto_accounts.sqlite", "legacy")
    _database(target / "ditto_accounts.sqlite", "workspace")

    _migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)

    receipt = json.loads((installation / "ditto-legacy-migration.json").read_text())
    assert receipt["phase"] == "quarantined"
    assert _value(target / "ditto_accounts.sqlite") == "workspace"
    assert _value(legacy / "ditto_accounts.sqlite") == "legacy"
    assert list(installation.glob("ditto-quarantine-*.snapshot"))


def test_tampered_receipt_cannot_redirect_recovery_snapshot(tmp_path):
    from flinttrade_core import workspace

    legacy = tmp_path / "legacy"
    target = tmp_path / "target"
    installation = tmp_path / "installation"
    _database(legacy / "ditto_accounts.sqlite", "legacy")

    with pytest.raises(RuntimeError):
        workspace._migrate_legacy_ditto_state(
            legacy,
            target,
            installation_state_root=installation,
            phase_hook=lambda phase: (_ for _ in ()).throw(RuntimeError("crash")) if phase == "consumed" else None,
        )
    journal = installation / "ditto-legacy-migration.json"
    receipt = json.loads(journal.read_text())
    receipt["snapshots"]["accounts"] = str(tmp_path / "attacker-selected.sqlite")
    receipt.pop("journal_sha256")
    receipt["journal_sha256"] = hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    journal.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n")
    journal.chmod(0o600)

    with pytest.raises(workspace.WorkspaceStateMigrationError, match="journal is unsafe"):
        workspace._migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)


def test_consumed_snapshot_corruption_never_reaches_target(tmp_path):
    from flinttrade_core import workspace

    legacy = tmp_path / "legacy"
    target = tmp_path / "target"
    installation = tmp_path / "installation"
    source = legacy / "ditto_accounts.sqlite"
    _database(source, "legacy")
    with pytest.raises(RuntimeError):
        workspace._migrate_legacy_ditto_state(
            legacy,
            target,
            installation_state_root=installation,
            phase_hook=lambda phase: (_ for _ in ()).throw(RuntimeError("crash")) if phase == "consumed" else None,
        )
    receipt = json.loads((installation / "ditto-legacy-migration.json").read_text())
    snapshot = Path(receipt["snapshots"]["accounts"])
    snapshot.write_bytes(b"owner-written-corruption")
    snapshot.chmod(0o600)

    with pytest.raises(workspace.WorkspaceStateMigrationError, match="snapshot digest changed"):
        workspace._migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)
    assert not (target / "ditto_accounts.sqlite").exists()
    assert source.exists()


def test_corrupt_phase_shape_is_rejected_even_with_recomputed_checksum(tmp_path):
    from flinttrade_core import workspace

    legacy = tmp_path / "legacy"
    target = tmp_path / "target"
    installation = tmp_path / "installation"
    _database(legacy / "ditto_accounts.sqlite", "legacy")
    with pytest.raises(RuntimeError):
        workspace._migrate_legacy_ditto_state(
            legacy,
            target,
            installation_state_root=installation,
            phase_hook=lambda phase: (_ for _ in ()).throw(RuntimeError("crash")) if phase == "consumed" else None,
        )
    journal = installation / "ditto-legacy-migration.json"
    receipt = json.loads(journal.read_text())
    receipt["snapshots"] = {}
    receipt.pop("journal_sha256")
    receipt["journal_sha256"] = hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    journal.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n")
    journal.chmod(0o600)
    with pytest.raises(workspace.WorkspaceStateMigrationError, match="journal is unsafe"):
        workspace._migrate_legacy_ditto_state(legacy, target, installation_state_root=installation)


@pytest.mark.skipif(not hasattr(Path, "symlink_to"), reason="symlinks unavailable")
def test_unsafe_sqlite_sidecar_and_distinct_target_parent_fail_closed(tmp_path):
    from flinttrade_core import workspace

    legacy = tmp_path / "legacy"
    installation = tmp_path / "installation"
    accounts = legacy / "ditto_accounts.sqlite"
    _database(accounts, "legacy")
    external = tmp_path / "external"
    external.write_bytes(b"not-a-sidecar")
    Path(f"{accounts}-journal").symlink_to(external)
    with pytest.raises(workspace.WorkspaceStateMigrationError, match="sidecar is unsafe"):
        workspace._migrate_legacy_ditto_state(
            legacy,
            tmp_path / "target",
            installation_state_root=installation,
        )

    Path(f"{accounts}-journal").unlink()
    second_installation = tmp_path / "second-installation"
    real_parent = tmp_path / "real-vault-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-vault-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(workspace.WorkspaceStateMigrationError, match="target directory is unsafe"):
        workspace._migrate_legacy_ditto_state(
            legacy,
            tmp_path / "second-target",
            installation_state_root=second_installation,
            target_vault_path=linked_parent / "ditto_credentials.db",
        )


def test_unsafe_shm_sidecar_fails_before_sqlite_backup(tmp_path):
    from flinttrade_core import workspace

    legacy = tmp_path / "legacy"
    accounts = legacy / "ditto_accounts.sqlite"
    _database(accounts, "legacy")
    external = tmp_path / "external-shm"
    external.write_bytes(b"not-shared-memory")
    Path(f"{accounts}-shm").symlink_to(external)

    with pytest.raises(workspace.WorkspaceStateMigrationError, match="sidecar is unsafe"):
        workspace._migrate_legacy_ditto_state(
            legacy,
            tmp_path / "target",
            installation_state_root=tmp_path / "installation",
        )


def test_workspace_copy_and_account_writer_share_one_fence(tmp_path):
    from flinttrade_core import workspace
    from flinttrade_ditto.account_manager import AccountManager, BrokerAccount

    legacy = tmp_path / "legacy"
    target = tmp_path / "target"
    installation = tmp_path / "installation"
    _database(legacy / "ditto_accounts.sqlite", "before")
    migration_paused = threading.Event()
    release_migration = threading.Event()
    manager = AccountManager(
        db_path=str(legacy / "writer.sqlite"),
        master_password="test-master-pw",
        installation_state_root=installation,
    )

    def hook(phase: str) -> None:
        if phase == "preparing":
            migration_paused.set()
            release_migration.wait(2)

    migration = threading.Thread(
        target=workspace._migrate_legacy_ditto_state,
        args=(legacy, target),
        kwargs={"installation_state_root": installation, "phase_hook": hook},
    )
    migration.start()
    assert migration_paused.wait(2)
    writer_done = threading.Event()

    def write() -> None:
        manager.add_account(BrokerAccount("after", "http://127.0.0.1:1", "secret"))
        writer_done.set()

    writer = threading.Thread(target=write)
    writer.start()
    time.sleep(0.05)
    assert not writer_done.is_set()
    release_migration.set()
    migration.join(2)
    writer.join(2)
    assert writer_done.is_set()
    manager.close()


def test_target_account_manager_constructor_and_write_wait_for_migration(tmp_path):
    from flinttrade_core import workspace
    from flinttrade_ditto.account_manager import AccountManager, BrokerAccount

    class Store:
        def store(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            return None

        def retrieve_for(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            return {"api_key": "test-key"}

    legacy = tmp_path / "legacy"
    target = tmp_path / "target"
    installation = tmp_path / "installation"
    _database(legacy / "ditto_accounts.sqlite", "preserved-before-writer")
    migration_paused = threading.Event()
    release_migration = threading.Event()

    def hook(phase: str) -> None:
        if phase == "preparing":
            migration_paused.set()
            release_migration.wait(2)

    migration = threading.Thread(
        target=workspace._migrate_legacy_ditto_state,
        args=(legacy, target),
        kwargs={"installation_state_root": installation, "phase_hook": hook},
    )
    migration.start()
    assert migration_paused.wait(2)

    constructor_returned = threading.Event()

    def construct_and_write() -> None:
        with AccountManager(
            db_path=str(target / "ditto_accounts.sqlite"),
            credential_store=Store(),  # type: ignore[arg-type]
            installation_state_root=installation,
        ) as manager:
            constructor_returned.set()
            manager.add_account(BrokerAccount("after", "http://127.0.0.1:1", "test-key"))

    writer = threading.Thread(target=construct_and_write)
    writer.start()
    time.sleep(0.05)
    assert not constructor_returned.is_set()
    release_migration.set()
    migration.join(2)
    writer.join(2)

    assert constructor_returned.is_set()
    assert _value(target / "ditto_accounts.sqlite") == "preserved-before-writer"
    with sqlite3.connect(target / "ditto_accounts.sqlite") as connection:
        assert connection.execute("SELECT account_id FROM accounts").fetchone()[0] == "after"
