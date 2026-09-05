"""Task 0 regressions for preserving Ditto's legacy credential sources."""

from __future__ import annotations

import multiprocessing
import os
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


_FORK_INHERITED_STATE = None


def _enter_inherited_fork_state(entered) -> None:  # type: ignore[no-untyped-def]
    with _FORK_INHERITED_STATE.ditto_fence():
        entered.set()


class _ReadOnlyCredentialStore:
    def __init__(self) -> None:
        self.write_calls = 0

    def store(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.write_calls += 1
        raise AssertionError("legacy construction must not write credentials")

    def retrieve_for(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return {}


def _legacy_database(path: Path, ciphertext: str = "opaque-legacy-cell") -> tuple[str, bytes]:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE accounts (
            account_id TEXT PRIMARY KEY,
            name TEXT DEFAULT '',
            openalgo_host TEXT NOT NULL,
            api_key_encrypted TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            allocation_weight REAL DEFAULT 1.0,
            account_group TEXT DEFAULT 'default',
            max_loss_daily REAL DEFAULT 50000.0,
            is_master INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO accounts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("legacy", "Legacy", "http://127.0.0.1:1", ciphertext, 1, 2.0, "family", 123.0, 0, "a", "b"),
    )
    conn.commit()
    schema = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'accounts'").fetchone()[0]
    conn.close()
    return schema, path.read_bytes()


def _marker_database(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE marker (value TEXT)")
        connection.execute("INSERT INTO marker VALUES (?)", (value,))


def _configure_default_ditto_paths(tmp_path: Path, monkeypatch):  # type: ignore[no-untyped-def]
    from flinttrade_core import workspace

    platform_workspace = tmp_path / "workspace"
    legacy = tmp_path / "legacy" / "data"
    installation = tmp_path / "installation"
    monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
    monkeypatch.delenv("FLINTTRADE_WORKSPACE_DIR", raising=False)
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setattr(workspace, "_default_home", lambda: platform_workspace)
    monkeypatch.setattr(workspace, "_legacy_fast_data_dir", lambda: legacy)
    return workspace, platform_workspace, legacy, installation


@pytest.mark.parametrize("legacy_key", [None, "definitely-the-wrong-key"])
def test_constructor_never_consumes_or_changes_legacy_column(tmp_path, monkeypatch, legacy_key):
    from flinttrade_ditto.account_manager import AccountManager

    db = tmp_path / "ditto_accounts.sqlite"
    schema_before, _bytes_before = _legacy_database(db)
    store = _ReadOnlyCredentialStore()
    if legacy_key is None:
        monkeypatch.delenv("DITTO_ENCRYPTION_KEY", raising=False)
    else:
        monkeypatch.setenv("DITTO_ENCRYPTION_KEY", legacy_key)

    with AccountManager(
        db_path=str(db),
        credential_store=store,  # type: ignore[arg-type]
        installation_state_root=tmp_path / "installation",
    ) as manager:
        accounts = manager.list_accounts()

    conn = sqlite3.connect(db)
    schema_after = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'accounts'").fetchone()[0]
    cell_after = conn.execute(
        "SELECT typeof(api_key_encrypted), hex(CAST(api_key_encrypted AS BLOB)) "
        "FROM accounts WHERE account_id='legacy'"
    ).fetchone()
    conn.close()
    assert store.write_calls == 0
    assert schema_after == schema_before
    assert cell_after == ("text", "opaque-legacy-cell".encode().hex().upper())
    assert accounts[0].group == "family"
    assert accounts[0].allocation_weight == 2.0


def test_legacy_target_store_read_failure_preserves_database_bytes(tmp_path):
    from flinttrade_ditto.account_manager import AccountManager

    class FailingStore(_ReadOnlyCredentialStore):
        def retrieve_for(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("target store unavailable")

    db = tmp_path / "ditto_accounts.sqlite"
    schema_before, _bytes_before = _legacy_database(db)
    store = FailingStore()
    with AccountManager(
        db_path=str(db),
        credential_store=store,  # type: ignore[arg-type]
        installation_state_root=tmp_path / "installation",
    ) as manager:
        account = manager.get_account("legacy")

    assert account is not None
    assert account.api_key == ""
    assert store.write_calls == 0
    with sqlite3.connect(db) as connection:
        schema_after = connection.execute("SELECT sql FROM sqlite_master WHERE name = 'accounts'").fetchone()[0]
        cell_after = connection.execute(
            "SELECT api_key_encrypted FROM accounts WHERE account_id='legacy'"
        ).fetchone()[0]
    assert schema_after == schema_before
    assert cell_after == "opaque-legacy-cell"


def test_legacy_writer_updates_metadata_without_changing_ciphertext_and_adds_empty_new_cell(tmp_path):
    from flinttrade_ditto.account_manager import AccountManager, BrokerAccount

    class Store:
        def store(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return None

        def retrieve_for(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return {"api_key": "canonical"}

        def remove_for(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return None

    db = tmp_path / "ditto_accounts.sqlite"
    schema_before, _bytes_before = _legacy_database(db)
    with AccountManager(
        db_path=str(db),
        credential_store=Store(),  # type: ignore[arg-type]
        installation_state_root=tmp_path / "installation",
    ) as manager:
        manager.add_account(BrokerAccount("legacy", "http://127.0.0.1:2", "new", name="Updated"))
        manager.add_account(BrokerAccount("new", "http://127.0.0.1:3", "new"))

    with sqlite3.connect(db) as connection:
        schema_after = connection.execute("SELECT sql FROM sqlite_master WHERE name='accounts'").fetchone()[0]
        rows = connection.execute(
            "SELECT account_id, name, api_key_encrypted FROM accounts ORDER BY account_id"
        ).fetchall()
    assert schema_after == schema_before
    assert rows == [("legacy", "Updated", "opaque-legacy-cell"), ("new", "", "")]


def test_legacy_writer_vault_failure_leaves_metadata_database_unchanged(tmp_path):
    from flinttrade_ditto.account_manager import AccountManager, BrokerAccount

    class FailingStore(_ReadOnlyCredentialStore):
        def store(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            self.write_calls += 1
            raise RuntimeError("vault unavailable")

    db = tmp_path / "ditto_accounts.sqlite"
    _schema, bytes_before = _legacy_database(db)
    manager = AccountManager(
        db_path=str(db),
        credential_store=FailingStore(),  # type: ignore[arg-type]
        installation_state_root=tmp_path / "installation",
    )
    with pytest.raises(RuntimeError, match="vault unavailable"):
        manager.add_account(BrokerAccount("legacy", "http://127.0.0.1:2", "new"))
    manager.close()
    assert db.read_bytes() == bytes_before


def test_explicit_legacy_remove_retires_metadata_and_canonical_credential(tmp_path):
    from flinttrade_ditto.account_manager import AccountManager

    class Store(_ReadOnlyCredentialStore):
        removed: list[tuple[str, str]] = []

        def remove_for(self, adapter_id: str, account_id: str) -> None:
            self.removed.append((adapter_id, account_id))

    db = tmp_path / "ditto_accounts.sqlite"
    _legacy_database(db)
    store = Store()
    with AccountManager(
        db_path=str(db),
        credential_store=store,  # type: ignore[arg-type]
        installation_state_root=tmp_path / "installation",
    ) as manager:
        manager.remove_account("legacy")

    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0
    assert store.removed == [("openalgo", "legacy")]


def test_explicit_database_path_never_touches_real_home(tmp_path, monkeypatch):
    from flinttrade_ditto.account_manager import AccountManager

    installation = tmp_path / "stable-installation"
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: (_ for _ in ()).throw(AssertionError("real home"))))
    manager = AccountManager(
        db_path=str(tmp_path / "accounts.sqlite"),
        master_password="test-master-pw",
        installation_state_root=installation,
    )
    assert manager.list_accounts() == []
    manager.close()
    assert (installation / "installation_id").is_file()


def test_replaced_installation_identity_fails_mutation_readiness(tmp_path):
    from flinttrade_core.installation_state import InstallationState, InstallationStateError

    state = InstallationState(tmp_path / "installation")
    original = state.installation_id
    state.identity_path.write_text("11111111-1111-4111-8111-111111111111\n", encoding="utf-8")
    os.chmod(state.identity_path, 0o600)

    with pytest.raises(InstallationStateError, match="replaced|mismatch"):
        state.assert_mutation_ready()
    assert state.installation_id == original


def test_established_installation_identity_rejects_extra_newline(tmp_path):
    from flinttrade_core.installation_state import InstallationState, InstallationStateError

    state = InstallationState(tmp_path / "installation")
    state.identity_path.write_bytes(f"{state.installation_id}\n\n".encode())
    state.identity_path.chmod(0o600)

    with pytest.raises(InstallationStateError, match="malformed|replaced"):
        state.assert_mutation_ready()


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode semantics")
def test_root_mode_broadening_and_binding_replacement_fail_readiness(tmp_path):
    from flinttrade_core.installation_state import InstallationState, InstallationStateError

    state = InstallationState(tmp_path / "installation")
    state.root.chmod(0o755)
    with pytest.raises(InstallationStateError, match="owner-only"):
        state.assert_mutation_ready()

    state.root.chmod(0o700)
    state._binding_path.unlink()
    original_binding = {
        "installation_id": str(state.installation_id),
        "identity_device": state._identity_stat.st_dev,
        "identity_inode": state._identity_stat.st_ino,
    }
    state._binding_path.write_text(
        __import__("json").dumps(original_binding, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    state._binding_path.chmod(0o600)
    with pytest.raises(InstallationStateError, match="binding was replaced"):
        state.assert_mutation_ready()


def test_byte_for_byte_identity_and_binding_restore_fails_reopen(tmp_path):
    from flinttrade_core.installation_state import InstallationState, InstallationStateError

    root = tmp_path / "installation"
    original = InstallationState(root)
    identity_bytes = original.identity_path.read_bytes()
    binding_bytes = original._binding_path.read_bytes()
    replacement_identity = root / "identity.replacement"
    replacement_identity.write_bytes(identity_bytes)
    replacement_identity.chmod(0o600)
    os.replace(replacement_identity, original.identity_path)
    replacement_binding = root / "binding.replacement"
    replacement_binding.write_bytes(binding_bytes)
    replacement_binding.chmod(0o600)
    os.replace(replacement_binding, original._binding_path)

    with pytest.raises(InstallationStateError, match="binding mismatch"):
        InstallationState(root)


@pytest.mark.skipif(os.name == "nt", reason="mocks Windows mode-bit semantics on POSIX")
def test_windows_dacl_path_does_not_apply_posix_lock_mode_bits(tmp_path, monkeypatch):
    from flinttrade_core import installation_state

    state = installation_state.InstallationState(tmp_path / "installation")
    Path(state._ditto_lock.lock_file).touch(mode=0o600)
    Path(state._ditto_lock.lock_file).chmod(0o666)
    monkeypatch.setattr(installation_state, "_uses_posix_mode_bits", lambda: False)
    with state.ditto_fence():
        pass


def test_installation_identity_concurrent_first_creation_has_one_winner(tmp_path):
    from flinttrade_core.installation_state import InstallationState

    root = tmp_path / "installation"
    with ThreadPoolExecutor(max_workers=8) as pool:
        identities = list(pool.map(lambda _index: InstallationState(root).installation_id, range(24)))
    assert len(set(identities)) == 1


def test_new_installation_root_is_durable_before_identity_write(tmp_path, monkeypatch):
    from flinttrade_core import installation_state

    events: list[str] = []
    real_parent_fsync = installation_state.fsync_parent_directory
    real_write = installation_state.write_secret_text

    def record_parent_fsync(path: Path) -> None:
        events.append("root-parent-fsync")
        real_parent_fsync(path)

    def record_write(path: Path, value: str) -> None:
        events.append(f"write:{path.name}")
        real_write(path, value)

    monkeypatch.setattr(installation_state, "fsync_parent_directory", record_parent_fsync)
    monkeypatch.setattr(installation_state, "write_secret_text", record_write)

    installation_state.InstallationState(tmp_path / "installation")

    identity_candidate_write = next(
        index for index, event in enumerate(events) if event.startswith("write:.installation-id-")
    )
    assert events.index("root-parent-fsync") < identity_candidate_write


def test_existing_installation_root_is_barriered_before_identity_write(tmp_path, monkeypatch):
    from flinttrade_core import installation_state

    root = tmp_path / "installation"
    root.mkdir(mode=0o700)
    installation_state.harden_directory(root)
    events: list[str] = []
    real_parent_fsync = installation_state.fsync_parent_directory
    real_assert_parent = installation_state._assert_parent_generation
    real_assert_root = installation_state._assert_owned_directory
    real_write = installation_state.write_secret_text

    def record_parent_fsync(path: Path) -> None:
        events.append("root-parent-fsync")
        real_parent_fsync(path)

    def record_parent_validation(path: Path, expected) -> None:  # type: ignore[no-untyped-def]
        events.append("parent-validated")
        real_assert_parent(path, expected)

    def record_root_validation(path: Path, **kwargs):  # type: ignore[no-untyped-def]
        events.append("root-validated")
        return real_assert_root(path, **kwargs)

    def record_write(path: Path, value: str) -> None:
        events.append(f"write:{path.name}")
        real_write(path, value)

    monkeypatch.setattr(installation_state, "fsync_parent_directory", record_parent_fsync)
    monkeypatch.setattr(installation_state, "_assert_parent_generation", record_parent_validation)
    monkeypatch.setattr(installation_state, "_assert_owned_directory", record_root_validation)
    monkeypatch.setattr(installation_state, "write_secret_text", record_write)

    installation_state.InstallationState(root)

    identity_candidate_write = next(
        index for index, event in enumerate(events) if event.startswith("write:.installation-id-")
    )
    assert "root-parent-fsync" in events
    barrier = events.index("root-parent-fsync")
    assert barrier < identity_candidate_write
    after_barrier = events[barrier + 1 : identity_candidate_write]
    assert "parent-validated" in after_barrier
    assert "root-validated" in after_barrier


def test_first_creation_recovery_from_preparing_candidate(tmp_path, monkeypatch):
    from flinttrade_core import secure_file
    from flinttrade_core.installation_state import InstallationState

    root = tmp_path / "installation"
    real_replace = secure_file.durable_replace

    def fail_identity_publish(source: Path, destination: Path) -> None:
        if destination.name == "installation_id":
            raise OSError("crash before identity publish")
        real_replace(source, destination)

    with monkeypatch.context() as m:
        m.setattr(secure_file, "durable_replace", fail_identity_publish)
        with pytest.raises(Exception, match="identity|crash"):
            InstallationState(root)

    recovered = InstallationState(root)
    assert recovered.identity_path.is_file()
    assert not list(root.glob(".installation-id-*.candidate"))


def test_first_creation_recovery_rejects_candidate_with_extra_newline(tmp_path, monkeypatch):
    from flinttrade_core import secure_file
    from flinttrade_core.installation_state import InstallationState, InstallationStateError

    root = tmp_path / "installation"
    real_replace = secure_file.durable_replace

    def fail_identity_publish(source: Path, destination: Path) -> None:
        if destination.name == "installation_id":
            raise OSError("crash before identity publish")
        real_replace(source, destination)

    with monkeypatch.context() as m:
        m.setattr(secure_file, "durable_replace", fail_identity_publish)
        with pytest.raises(InstallationStateError):
            InstallationState(root)

    candidate = next(root.glob(".installation-id-*.candidate"))
    candidate.write_bytes(candidate.read_bytes() + b"\n")
    candidate.chmod(0o600)
    with pytest.raises(InstallationStateError, match="does not match|malformed"):
        InstallationState(root)


def test_first_creation_recovery_rejects_preexisting_migration_receipt(tmp_path, monkeypatch):
    from flinttrade_core import secure_file
    from flinttrade_core.installation_state import InstallationState, InstallationStateError

    root = tmp_path / "installation"
    real_replace = secure_file.durable_replace

    def fail_identity_publish(source: Path, destination: Path) -> None:
        if destination.name == "installation_id":
            raise OSError("crash before identity publish")
        real_replace(source, destination)

    with monkeypatch.context() as m:
        m.setattr(secure_file, "durable_replace", fail_identity_publish)
        with pytest.raises(InstallationStateError):
            InstallationState(root)

    receipt = root / "ditto-legacy-migration.json"
    receipt.write_text("{}\n", encoding="utf-8")
    receipt.chmod(0o600)
    with pytest.raises(InstallationStateError, match="receipt|preparation"):
        InstallationState(root)


def test_installation_root_parent_swap_during_creation_fails_closed(tmp_path, monkeypatch):
    from flinttrade_core import installation_state

    parent = tmp_path / "container"
    parent.mkdir()
    root = parent / "installation"
    moved_parent = tmp_path / "moved-container"
    real_mkdir = installation_state.os.mkdir

    def mkdir_then_swap(path, mode=0o777, *args, **kwargs):  # type: ignore[no-untyped-def]
        result = real_mkdir(path, mode, *args, **kwargs)
        if Path(path) == root:
            parent.rename(moved_parent)
            real_mkdir(parent, 0o700)
        return result

    monkeypatch.setattr(installation_state.os, "mkdir", mkdir_then_swap)

    with pytest.raises(installation_state.InstallationStateError, match="parent|unsafe"):
        installation_state.InstallationState(root)
    assert (moved_parent / "installation").is_dir()
    assert not (root / "installation_id").exists()


def test_windows_first_creation_loser_waits_for_winner_hardening(tmp_path, monkeypatch):
    from flinttrade_core import installation_state

    root = tmp_path / "installation"
    real_mkdir = installation_state.os.mkdir
    real_assert = installation_state._assert_owned_directory
    validation_attempts = 0
    root_parent_barriers: list[Path] = []

    def losing_mkdir(path, mode=0o777, *args, **kwargs):  # type: ignore[no-untyped-def]
        real_mkdir(path, mode, *args, **kwargs)
        raise FileExistsError("another creator won")

    def dacl_settles_after_first_probe(path, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal validation_attempts
        validation_attempts += 1
        if validation_attempts == 1:
            raise installation_state.InstallationStateError("winner DACL not installed yet")
        return real_assert(path, **kwargs)

    def record_parent_fsync(path: Path) -> None:
        root_parent_barriers.append(path)

    monkeypatch.setattr(installation_state.os, "mkdir", losing_mkdir)
    monkeypatch.setattr(installation_state, "_assert_owned_directory", dacl_settles_after_first_probe)
    monkeypatch.setattr(installation_state, "fsync_parent_directory", record_parent_fsync)
    monkeypatch.setattr(installation_state.time, "sleep", lambda _seconds: None)

    root_stat = installation_state._prepare_owned_root(root)

    assert validation_attempts == 3
    assert root_parent_barriers == [root]
    assert (root_stat.st_dev, root_stat.st_ino) == (root.stat().st_dev, root.stat().st_ino)


def test_first_creation_recovery_after_identity_publish_before_final_binding(tmp_path, monkeypatch):
    from flinttrade_core import installation_state

    root = tmp_path / "installation"
    real_write = installation_state.write_secret_text
    binding_writes = 0

    def fail_final_binding(path: Path, value: str) -> None:
        nonlocal binding_writes
        if path.name == ".installation-id-binding":
            binding_writes += 1
            if binding_writes == 2:
                raise OSError("crash before final binding")
        real_write(path, value)

    with monkeypatch.context() as m:
        m.setattr(installation_state, "write_secret_text", fail_final_binding)
        with pytest.raises(installation_state.InstallationStateError):
            installation_state.InstallationState(root)

    recovered = installation_state.InstallationState(root)
    assert recovered.identity_path.is_file()
    assert "preparing" not in recovered._binding_path.read_text(encoding="utf-8")


def test_first_creation_ignores_prejournal_orphan_candidate(tmp_path, monkeypatch):
    from flinttrade_core import installation_state

    root = tmp_path / "installation"
    real_write = installation_state.write_secret_text

    def fail_preparing_binding(path: Path, value: str) -> None:
        if path.name == ".installation-id-binding":
            raise OSError("crash before journal")
        real_write(path, value)

    with monkeypatch.context() as m:
        m.setattr(installation_state, "write_secret_text", fail_preparing_binding)
        with pytest.raises(installation_state.InstallationStateError):
            installation_state.InstallationState(root)

    orphan = next(root.glob(".installation-id-*.candidate"))
    recovered = installation_state.InstallationState(root)
    assert recovered.identity_path.is_file()
    assert orphan.is_file()
    assert orphan.read_text(encoding="utf-8") != recovered.identity_path.read_text(encoding="utf-8")


def test_installation_identity_cross_process_first_creation_has_one_winner(tmp_path):
    root = str(tmp_path / "installation")
    code = (
        "import sys; "
        "from flinttrade_core.installation_state import InstallationState; "
        "print(InstallationState(sys.argv[1]).installation_id)"
    )
    processes = [
        subprocess.Popen(  # noqa: S603
            [sys.executable, "-c", code, root],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(12)
    ]
    identities: list[str] = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 0, stderr
        identities.append(stdout.strip())
    assert len(set(identities)) == 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX link and mode semantics")
def test_symlink_or_broad_installation_root_fails_without_chmod(tmp_path):
    from flinttrade_core.installation_state import InstallationState, InstallationStateError

    target = tmp_path / "foreign"
    target.mkdir(mode=0o755)
    link = tmp_path / "installation-link"
    link.symlink_to(target, target_is_directory=True)
    before = target.stat().st_mode & 0o777
    with pytest.raises(InstallationStateError, match="unsafe"):
        InstallationState(link)
    assert target.stat().st_mode & 0o777 == before

    broad = tmp_path / "broad"
    broad.mkdir(mode=0o755)
    with pytest.raises(InstallationStateError, match="owner-only"):
        InstallationState(broad)
    assert broad.stat().st_mode & 0o777 == 0o755


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics")
def test_environment_selected_installation_root_does_not_resolve_symlink(tmp_path, monkeypatch):
    from flinttrade_core.installation_state import InstallationState, InstallationStateError

    target = tmp_path / "foreign"
    target.mkdir(mode=0o755)
    link = tmp_path / "installation-link"
    link.symlink_to(target, target_is_directory=True)
    monkeypatch.setenv("FLINTTRADE_INSTALLATION_STATE_DIR", str(link))

    with pytest.raises(InstallationStateError, match="unsafe"):
        InstallationState()
    assert target.stat().st_mode & 0o777 == 0o755


@pytest.mark.skipif(os.name == "nt", reason="POSIX dangling-symlink semantics")
def test_dangling_installation_root_alias_into_workspace_is_rejected(tmp_path, monkeypatch):
    from flinttrade_core.installation_state import InstallationState, InstallationStateError

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    pivot = tmp_path / "pivot"
    pivot.symlink_to(workspace / "missing", target_is_directory=True)
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("FLINTTRADE_INSTALLATION_STATE_DIR", str(pivot / "lineage"))

    with pytest.raises(InstallationStateError, match="active workspace"):
        InstallationState()


def test_windows_home_candidate_prefers_userprofile_over_msys_home(tmp_path, monkeypatch):
    from flinttrade_core import installation_state

    user_profile = tmp_path / "windows-profile"
    monkeypatch.setattr(installation_state.platform, "system", lambda: "Windows")
    monkeypatch.setenv("HOME", str(tmp_path / "msys-home"))
    monkeypatch.setenv("USERPROFILE", str(user_profile))

    assert installation_state._platform_home_candidate() == user_profile
    assert installation_state._desktop_managed_root() == user_profile / ".flinttrade"


@pytest.mark.parametrize("relative", [".", "state", "backup/state", "../workspace-parent"])
def test_installation_root_cannot_overlap_active_workspace(tmp_path, monkeypatch, relative):
    from flinttrade_core.installation_state import InstallationState, InstallationStateError

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
    root = workspace / relative
    if relative == "../workspace-parent":
        root = tmp_path
    with pytest.raises(InstallationStateError, match="overlaps"):
        InstallationState(root)


@pytest.mark.parametrize("excluded_name", ["legacy archive", "desktop managed root", "backup archive root"])
def test_installation_root_cannot_overlap_static_archive_roots(tmp_path, monkeypatch, excluded_name):
    from flinttrade_core import installation_state

    archive = tmp_path / excluded_name.replace(" ", "-")
    helper = {
        "legacy archive": "_legacy_archive_candidate",
        "desktop managed root": "_desktop_managed_root",
        "backup archive root": "_backup_archive_root",
    }[excluded_name]
    monkeypatch.setattr(installation_state, helper, lambda: archive)
    monkeypatch.setenv("FLINTTRADE_INSTALLATION_STATE_DIR", str(archive / "lineage"))
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path / "workspace"))

    with pytest.raises(installation_state.InstallationStateError, match=excluded_name):
        installation_state.InstallationState()


def test_installation_root_rejects_case_alias_of_workspace_on_case_insensitive_fs(tmp_path, monkeypatch):
    from flinttrade_core import installation_state

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    case_alias = tmp_path / "WORKSPACE"
    if not case_alias.exists():
        pytest.skip("filesystem is case-sensitive")
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))

    with pytest.raises(installation_state.InstallationStateError, match="active workspace"):
        installation_state.InstallationState(case_alias / "lineage")


@pytest.mark.skipif(os.name == "nt", reason="POSIX hardlink semantics")
def test_hardlinked_installation_identity_fails_closed(tmp_path):
    from flinttrade_core.installation_state import InstallationState, InstallationStateError

    root = tmp_path / "installation"
    state = InstallationState(root)
    other = tmp_path / "other-id"
    other.write_text(f"{state.installation_id}\n", encoding="utf-8")
    other.chmod(0o600)
    state.identity_path.unlink()
    os.link(other, state.identity_path)
    with pytest.raises(InstallationStateError, match="owner-owned"):
        InstallationState(root)


def test_separate_state_handles_serialise_threads_on_same_fence(tmp_path):
    from flinttrade_core.installation_state import InstallationState

    first = InstallationState(tmp_path / "installation")
    second = InstallationState(tmp_path / "installation")
    holder_entered = threading.Event()
    release_holder = threading.Event()
    contender_entered = threading.Event()

    def hold() -> None:
        with first.ditto_fence():
            holder_entered.set()
            release_holder.wait(2)

    def contend() -> None:
        holder_entered.wait(2)
        with second.ditto_fence():
            contender_entered.set()

    holder = threading.Thread(target=hold)
    contender = threading.Thread(target=contend)
    holder.start()
    contender.start()
    assert holder_entered.wait(2)
    time.sleep(0.05)
    assert not contender_entered.is_set()
    release_holder.set()
    holder.join(2)
    contender.join(2)
    assert contender_entered.is_set()


def test_separate_state_handles_are_reentrant_on_same_thread(tmp_path):
    from flinttrade_core.installation_state import InstallationState

    first = InstallationState(tmp_path / "installation")
    second = InstallationState(tmp_path / "installation")
    with first.ditto_fence(), second.ditto_fence():
        assert first.installation_id == second.installation_id
        assert first._lock_key == second._lock_key == (
            "inode",
            first._root_stat.st_dev,
            first._root_stat.st_ino,
        )


def test_case_alias_state_handles_share_one_nested_fence_on_case_insensitive_fs(tmp_path):
    from flinttrade_core.installation_state import InstallationState

    root = tmp_path / "installation"
    first = InstallationState(root)
    alias = tmp_path / "INSTALLATION"
    if not alias.exists():
        pytest.skip("filesystem is case-sensitive")
    second = InstallationState(alias)

    assert first._ditto_lock is second._ditto_lock
    with first.ditto_fence(), second.ditto_fence():
        assert first.installation_id == second.installation_id


def test_spawned_account_writer_blocks_on_parent_ditto_fence(tmp_path):
    from flinttrade_core.installation_state import InstallationState

    root = tmp_path / "installation"
    db_path = tmp_path / "accounts.sqlite"
    started = tmp_path / "spawned.started"
    finished = tmp_path / "spawned.finished"
    state = InstallationState(root)
    code = "\n".join(
        (
            "import pathlib, sys",
            "from flinttrade_ditto.account_manager import AccountManager, BrokerAccount",
            "pathlib.Path(sys.argv[3]).write_text('started')",
            "with AccountManager(db_path=sys.argv[2], master_password='test-master-pw', installation_state_root=sys.argv[1]) as manager:",
            "    manager.add_account(BrokerAccount('spawned', 'http://127.0.0.1:1', 'key'))",
            "pathlib.Path(sys.argv[4]).write_text('finished')",
        )
    )
    with state.ditto_fence():
        process = subprocess.Popen(  # noqa: S603
            [sys.executable, "-c", code, str(root), str(db_path), str(started), str(finished)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 5
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert started.exists()
        time.sleep(0.1)
        assert not finished.exists()
    stdout, stderr = process.communicate(timeout=10)

    assert process.returncode == 0, (stdout, stderr)
    assert finished.exists()
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT account_id FROM accounts").fetchone()[0] == "spawned"


@pytest.mark.skipif("fork" not in multiprocessing.get_all_start_methods(), reason="fork unavailable")
def test_forked_child_rebinds_inherited_fence_and_waits_for_parent(tmp_path):
    from flinttrade_core.installation_state import InstallationState

    global _FORK_INHERITED_STATE
    context = multiprocessing.get_context("fork")
    _FORK_INHERITED_STATE = InstallationState(tmp_path / "installation")
    entered = context.Event()
    process = context.Process(target=_enter_inherited_fork_state, args=(entered,))
    with _FORK_INHERITED_STATE.ditto_fence():
        process.start()
        time.sleep(0.1)
        assert not entered.is_set()
    process.join(10)

    assert process.exitcode == 0
    assert entered.is_set()


def test_account_writer_uses_the_shared_installation_fence(tmp_path):
    from flinttrade_core.installation_state import InstallationState
    from flinttrade_ditto.account_manager import AccountManager, BrokerAccount

    root = tmp_path / "installation"
    manager = AccountManager(
        db_path=str(tmp_path / "accounts.sqlite"),
        master_password="test-master-pw",
        installation_state_root=root,
    )
    writer_done = threading.Event()

    def write() -> None:
        manager.add_account(BrokerAccount("blocked", "http://127.0.0.1:1", "test-key"))
        writer_done.set()

    with InstallationState(root).ditto_fence():
        writer = threading.Thread(target=write)
        writer.start()
        time.sleep(0.05)
        assert not writer_done.is_set()
    writer.join(2)
    assert writer_done.is_set()
    manager.close()


def test_every_account_manager_source_sensitive_path_enters_ditto_fence(tmp_path, monkeypatch):
    from contextlib import contextmanager

    from flinttrade_ditto import account_manager

    class TrackingState:
        depth = 0
        entries = 0

        @contextmanager
        def ditto_fence(self):  # type: ignore[no-untyped-def]
            self.entries += 1
            self.depth += 1
            try:
                yield
            finally:
                self.depth -= 1

    state = TrackingState()

    class Store:
        def store(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            assert state.depth > 0

        def retrieve_for(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            assert state.depth > 0
            return {"api_key": "key"}

        def remove_for(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            assert state.depth > 0

    monkeypatch.setattr(account_manager, "InstallationState", lambda _root=None: state)
    manager = account_manager.AccountManager(
        db_path=str(tmp_path / "accounts.sqlite"),
        credential_store=Store(),  # type: ignore[arg-type]
    )
    assert state.entries == 1  # constructor

    def fenced(call):  # type: ignore[no-untyped-def]
        before = state.entries
        call()
        assert state.entries > before
        assert state.depth == 0

    account = account_manager.BrokerAccount("covered", "http://127.0.0.1:1", "key")
    fenced(lambda: manager.add_account(account))
    fenced(lambda: manager.get_account("covered"))  # cache hit
    manager._cache.clear()
    fenced(lambda: manager.get_account("covered"))  # metadata miss + vault read
    manager._cache.clear()
    fenced(manager.list_accounts)  # list + vault read
    fenced(lambda: manager.enable_account("covered"))
    fenced(lambda: manager.disable_account("covered"))
    fenced(lambda: manager.remove_account("covered"))
    fenced(manager.close)


def test_default_constructor_reads_migrated_canonical_vault(tmp_path, monkeypatch):
    from flinttrade_core import workspace
    from flinttrade_ditto.account_manager import AccountManager, BrokerAccount

    monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
    monkeypatch.delenv("FLINTTRADE_WORKSPACE_DIR", raising=False)
    monkeypatch.delenv("DATA_DIR", raising=False)
    platform_workspace = tmp_path / "platform-workspace"
    legacy_fast = tmp_path / "legacy" / "data"
    legacy_fast.mkdir(parents=True)
    monkeypatch.setattr(workspace, "_default_home", lambda: platform_workspace)
    monkeypatch.setattr(workspace, "_legacy_fast_data_dir", lambda: legacy_fast)

    with AccountManager(
        db_path=str(legacy_fast / "ditto_accounts.sqlite"),
        master_password="test-master-pw",
        installation_state_root=tmp_path / "installation-state",
    ) as legacy_manager:
        legacy_manager.add_account(BrokerAccount("legacy", "http://127.0.0.1:1", "preserved-api-key"))

    with AccountManager(master_password="test-master-pw") as migrated_manager:
        migrated = migrated_manager.get_account("legacy")

    assert migrated is not None
    assert migrated.api_key == "preserved-api-key"
    assert (platform_workspace / "ditto_credentials.db").is_file()


@pytest.mark.parametrize(
    ("root_exists", "adjacent_exists"),
    [(True, False), (False, True), (True, True), (False, False)],
    ids=("root-only", "adjacent-only", "both", "neither"),
)
def test_direct_default_without_receipt_always_keeps_historical_adjacent_vault(
    tmp_path,
    monkeypatch,
    root_exists,
    adjacent_exists,
):
    workspace, platform_workspace, _legacy, installation = _configure_default_ditto_paths(tmp_path, monkeypatch)
    root_vault = platform_workspace / "ditto_credentials.db"
    adjacent_vault = platform_workspace / "data" / "ditto_credentials.db"
    if root_exists:
        _marker_database(root_vault, "root")
    if adjacent_exists:
        _marker_database(adjacent_vault, "adjacent")

    accounts, selected_vault = workspace.ditto_account_manager_paths(
        installation_state_root=installation,
    )

    assert accounts == platform_workspace / "data" / "ditto_accounts.sqlite"
    assert selected_vault == adjacent_vault


@pytest.mark.parametrize(
    ("receipt_kind", "expected_location"),
    [
        ("published-credentials", "root"),
        ("published-accounts-only", "adjacent"),
        ("quarantined", "adjacent"),
    ],
)
def test_direct_default_vault_authority_is_receipt_gated(
    tmp_path,
    monkeypatch,
    receipt_kind,
    expected_location,
):
    workspace, platform_workspace, legacy, installation = _configure_default_ditto_paths(tmp_path, monkeypatch)
    _marker_database(legacy / "ditto_accounts.sqlite", "accounts")
    if receipt_kind == "published-credentials":
        _marker_database(legacy / "ditto_credentials.db", "credentials")
    elif receipt_kind == "quarantined":
        _marker_database(legacy / "ditto_credentials.db", "credentials")
        _marker_database(platform_workspace / "ditto_credentials.db", "preexisting-root")

    accounts, selected_vault = workspace.ditto_account_manager_paths(
        installation_state_root=installation,
    )

    expected = (
        platform_workspace / "ditto_credentials.db"
        if expected_location == "root"
        else accounts.parent / "ditto_credentials.db"
    )
    assert selected_vault == expected


@pytest.mark.parametrize("restore_adjacent", [False, True], ids=("root-deleted", "workspace-restored"))
def test_published_credential_receipt_never_falls_back_to_adjacent_after_restore(
    tmp_path,
    monkeypatch,
    restore_adjacent,
):
    workspace, platform_workspace, legacy, installation = _configure_default_ditto_paths(tmp_path, monkeypatch)
    _marker_database(legacy / "ditto_accounts.sqlite", "accounts")
    _marker_database(legacy / "ditto_credentials.db", "credentials")
    accounts, selected = workspace.ditto_account_manager_paths(installation_state_root=installation)
    assert selected == platform_workspace / "ditto_credentials.db"
    selected.unlink()
    if restore_adjacent:
        _marker_database(accounts.parent / "ditto_credentials.db", "restored-adjacent")

    _accounts, after_restore = workspace.ditto_account_manager_paths(
        installation_state_root=installation,
    )

    assert after_restore == platform_workspace / "ditto_credentials.db"


def test_data_dir_and_explicit_database_keep_adjacent_vaults(tmp_path, monkeypatch):
    from flinttrade_ditto.account_manager import AccountManager

    class Store:
        pass

    data_dir = tmp_path / "data-dir"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    default_manager = AccountManager(master_password="test-master-pw")
    assert default_manager._default_vault_path == data_dir / "ditto_credentials.db"
    default_manager.close()

    explicit_db = tmp_path / "explicit" / "accounts.sqlite"
    explicit_manager = AccountManager(
        db_path=str(explicit_db),
        credential_store=Store(),  # type: ignore[arg-type]
        installation_state_root=tmp_path / "explicit-installation",
    )
    assert explicit_manager._default_vault_path == explicit_db.parent / "ditto_credentials.db"
    explicit_manager.close()


def test_custom_installation_root_receipt_selects_root_under_same_fence(tmp_path, monkeypatch):
    workspace, platform_workspace, legacy, installation = _configure_default_ditto_paths(tmp_path, monkeypatch)
    monkeypatch.setenv("FLINTTRADE_INSTALLATION_STATE_DIR", str(tmp_path / "unrelated-default-state"))
    _marker_database(legacy / "ditto_accounts.sqlite", "accounts")
    _marker_database(legacy / "ditto_credentials.db", "credentials")

    accounts, vault = workspace.ditto_account_manager_paths(installation_state_root=installation)

    assert accounts == platform_workspace / "data" / "ditto_accounts.sqlite"
    assert vault == platform_workspace / "ditto_credentials.db"
    assert (installation / "ditto-legacy-migration.json").is_file()
    assert not (tmp_path / "unrelated-default-state" / "ditto-legacy-migration.json").exists()


def test_default_constructor_preserves_data_dir_adjacent_vault(tmp_path, monkeypatch):
    from flinttrade_ditto.account_manager import AccountManager, BrokerAccount

    data_dir = tmp_path / "explicit-data"
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))

    with AccountManager(master_password="test-master-pw") as manager:
        manager.add_account(BrokerAccount("data-dir", "http://127.0.0.1:1", "preserved-api-key"))

    assert (data_dir / "ditto_accounts.sqlite").is_file()
    assert (data_dir / "ditto_credentials.db").is_file()
    assert not (workspace / "ditto_credentials.db").exists()
