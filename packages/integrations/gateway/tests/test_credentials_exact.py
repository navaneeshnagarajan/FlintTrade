"""Disposable exact authority tests: component isolation, CAS and receipts."""

import os
import shutil
import sqlite3
import uuid
from contextlib import closing

import pytest

from flinttrade_core.broker_identity import BrokerSelector
from flinttrade_core.secure_file import harden, harden_directory
from flinttrade_gateway import credentials as vault


@pytest.fixture
def store(tmp_path):
    parent = tmp_path / "owned"
    parent.mkdir()
    harden_directory(parent)
    return vault.CredentialStore(parent / "vault.db", "synthetic-password")


def state(store, selector):
    assert hasattr(store, "selector_state"), "exact authority API is missing"
    return store.selector_state(selector)


def seed(store, selector, *, primary=False):
    result = store.put_credentials(
        selector, selector.adapter_id, "Synthetic", {"token": "old"}, expected=state(store, selector).version
    )
    if primary:
        store.apply_primary_projection(store.snapshot_primary_projection(selector, True))
        result = state(store, selector).version
    return result


def test_exact_component_presence_shared_cas_and_absent_delete(store):
    selector = BrokerSelector("openalgo", "A:1")
    unseen = state(store, selector)
    assert (unseen.version.generation, unseen.present, unseen.origin) == (0, False, None)
    setup = store.put_setup(selector, {"base_url": "HTTP://EXAMPLE.COM:80/"}, expected=unseen.version)
    assert setup.generation == 1
    assert store.retrieve_setup(selector) == {"base_url": "http://example.com:80"}
    both = store.put_credentials(selector, "zerodha", "Synthetic", {"token": "old"}, expected=setup)
    assert both.generation == 2
    assert state(store, selector).credential_present and state(store, selector).setup_present
    assert store.account_for_selector(selector).broker == "zerodha"
    with pytest.raises(vault.CredentialStaleError):
        store.remove_setup(selector, expected=setup)
    credentials = store.remove_setup(selector, expected=both)
    assert credentials.generation == 3 and state(store, selector).present
    absent = store.remove_selector(selector, expected=credentials)
    assert absent.generation == 4 and not state(store, selector).present
    again = store.remove_credentials(selector, expected=absent)
    assert again.generation == 5
    assert state(store, selector).origin == "managed"
    with pytest.raises(vault.CredentialStaleError):
        store.remove_selector(selector, expected=absent)


def test_stage_detects_setup_and_true_absent_aba(store):
    selector = BrokerSelector("openalgo", "A")
    stage = store.stage_credentials(selector, {"token": "candidate"}, broker="openalgo", label="Synthetic")
    assert stage.expected_version.generation == 0
    first = store.remove_selector(selector, expected=state(store, selector).version)
    assert first.generation == 1
    with pytest.raises(vault.CredentialStaleError):
        stage.commit()
    seed(store, selector)
    stage = store.stage_credentials(selector)
    store.put_setup(selector, {"base_url": "https://example.com"}, expected=state(store, selector).version)
    with pytest.raises(vault.CredentialStaleError):
        stage.commit()
    assert store.retrieve_credentials(selector) == {"token": "old"}
    stage.discard()
    stage.discard()


def test_primary_touches_demoted_version_and_restores_forward(store):
    a, b, c = (BrokerSelector("dhan", key) for key in ("A", "B", "C"))
    for selector in (a, b, c):
        seed(store, selector)
    store.apply_primary_projection(store.snapshot_primary_projection(a, True))
    stage = store.stage_credentials(a)
    receipt = store.apply_primary_projection(store.snapshot_primary_projection(b, True))
    assert (state(store, a).version.generation, state(store, b).version.generation) == (3, 2)
    with pytest.raises(vault.CredentialStaleError):
        stage.commit()
    store.update_credentials(c, {"token": "unrelated"}, expected=state(store, c).version)
    restored = store.restore_primary_projection(receipt)
    assert tuple(v.generation for v in restored) == (4, 3)
    assert store.account_for_selector(a).is_primary
    assert not store.account_for_selector(b).is_primary
    with pytest.raises(vault.CredentialStaleError):
        store.restore_primary_projection(receipt)


def test_primary_snapshot_rejects_new_membership_atomically(store):
    a, b, c = (BrokerSelector("dhan", key) for key in ("A", "B", "C"))
    for selector in (a, b, c):
        seed(store, selector)
    before = store.snapshot_primary_projection(b, True)
    store.apply_primary_projection(store.snapshot_primary_projection(c, True))
    with pytest.raises(vault.CredentialStaleError):
        store.apply_primary_projection(before)
    assert state(store, b).version.generation == 1
    assert store.account_for_selector(c).is_primary


def test_selector_snapshot_is_opaque_forward_cas_and_store_bound(store):
    a, b = BrokerSelector("openalgo", "A"), BrokerSelector("dhan", "B")
    empty = store.snapshot_selector(a)
    created = seed(store, a)
    store.restore_selector(empty, expected=created)
    assert state(store, a).version.generation == 2
    assert not state(store, a).present
    seed(store, a, primary=True)
    seed(store, b)
    snapshot = store.snapshot_selector(a)
    assert "token" not in repr(snapshot) and "old" not in repr(snapshot)
    current = store.remove_selector(a, expected=state(store, a).version)
    reopened = vault.CredentialStore(store._db_path, "synthetic-password")
    with pytest.raises(vault.CredentialStaleError):
        reopened.restore_selector(snapshot, expected=current)
    store.apply_primary_projection(store.snapshot_primary_projection(b, True))
    with pytest.raises(vault.CredentialStaleError):
        store.restore_selector(snapshot, expected=current)
    assert store.account_for_selector(b).is_primary
    assert store.account_for_selector(a) is None


def test_versions_persist_and_legacy_creation_is_unavailable(store):
    from flinttrade_core.broker_account_cutover import BrokerAccountCutoverUnavailable

    a = BrokerSelector("dhan", "A")
    first = seed(store, a)
    reopened = vault.CredentialStore(store._db_path, "synthetic-password")
    assert state(reopened, a).version == first
    assert type(first.vault_incarnation) is uuid.UUID
    with pytest.raises(BrokerAccountCutoverUnavailable):
        store.store("B", "dhan", "Synthetic", {})
    store.store("A", "dhan", "Updated", {"token": "new"}, is_primary=True)
    assert state(store, a).version.generation == 2
    assert store.account_for_selector(a).is_primary


def test_wrong_selector_cannot_reveal_or_overwrite(store):
    a, other = BrokerSelector("dhan", "A"), BrokerSelector("upstox", "A")
    expected = seed(store, a)
    with pytest.raises(vault.CredentialConflictError):
        seed(store, other)
    with pytest.raises(vault.CredentialNotFoundError, match="^credential_not_found$"):
        store.retrieve_credentials(other)
    store.remove_for("upstox", "A")
    assert state(store, other).version.generation == 0
    assert state(store, a).version == expected
    with pytest.raises(vault.CredentialStaleError):
        store.update_credentials(other, {}, expected=expected)
    assert store.retrieve_credentials(a) == {"token": "old"}


@pytest.mark.parametrize(
    "setup",
    [
        {},
        {"base_url": "https://example.com", "api_key": "secret"},
        {"base_url": "https://user:secret@example.com"},
        {"base_url": "https://example.com?"},
        {"base_url": "https://example.com#"},
        {"base_url": "https://example.com/path"},
        {"base_url": "https://example.com:"},
        {"base_url": "https://example.com:0"},
        {"base_url": "https://example.com:65536"},
        {"base_url": "https://exam%70le.com"},
        {"base_url": "https://é.com"},
        {"base_url": " https://example.com"},
        {"base_url": "https://example.com\\path"},
        {"base_url": "https://[bad]"},
        {"base_url": "https://example.com", "ws_port": True},
        {"base_url": "https://example.com", "ws_port": "1"},
    ],
)
def test_setup_validation_is_mutation_free(store, setup):
    selector = BrokerSelector("openalgo", "A")
    before = state(store, selector).version
    with pytest.raises(vault.CredentialValidationError, match="^credential_validation_failed$"):
        store.put_setup(selector, setup, expected=before)
    assert state(store, selector).version == before


def test_overflow_refuses_all_primary_changes_and_sql_rejects_zero(store):
    a, b = BrokerSelector("dhan", "A"), BrokerSelector("dhan", "B")
    seed(store, a, primary=True)
    seed(store, b)
    with closing(sqlite3.connect(store._db_path)) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE credential_selector_versions SET generation=0")
        conn.execute("UPDATE credential_selector_versions SET generation=? WHERE account_id='A'", (2**63 - 1,))
        conn.commit()
    before = state(store, b).version
    with pytest.raises(vault.CredentialConflictError):
        store.apply_primary_projection(store.snapshot_primary_projection(b, True))
    assert state(store, b).version == before
    assert store.account_for_selector(a).is_primary


def test_reserved_selector_rejected_by_all_generic_writes(store):
    selector = BrokerSelector("openalgo", "default")
    before = state(store, selector).version
    for method, args in [
        (store.put_credentials, ("openalgo", "Synthetic", {})),
        (store.put_setup, ({"base_url": "https://example.com"},)),
        (store.remove_credentials, ()),
        (store.remove_setup, ()),
        (store.remove_selector, ()),
    ]:
        with pytest.raises(vault.CredentialValidationError):
            method(selector, *args, expected=before)
    assert state(store, selector).version == before


def test_observed_same_uuid_replacement_poison_survives_restore(store):
    a = BrokerSelector("dhan", "A")
    seed(store, a)
    original = store._db_path
    saved, replacement = original.with_suffix(".saved"), original.with_suffix(".copy")
    shutil.copy2(original, replacement)
    os.replace(original, saved)
    os.replace(replacement, original)
    with pytest.raises(vault.CredentialStaleError):
        store.selector_state(a)
    os.replace(saved, original)
    with pytest.raises(vault.CredentialStaleError):
        store.selector_state(a)
    reopened = vault.CredentialStore(original, "synthetic-password")
    assert reopened.retrieve_credentials(a) == {"token": "old"}


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM credential_vault_metadata",
        "DROP TABLE broker_selector_setup",
        "PRAGMA user_version=0",
        "PRAGMA user_version=99",
        "UPDATE credential_vault_metadata SET vault_incarnation='not-a-uuid'",
        "DROP TABLE accounts",
    ],
)
def test_partial_versioned_authority_is_refused_never_repaired(store, sql):
    a = BrokerSelector("dhan", "A")
    seed(store, a)
    with closing(sqlite3.connect(store._db_path)) as conn:
        conn.execute(sql)
        conn.commit()
    with pytest.raises(vault.CredentialVaultInvalidError):
        vault.CredentialStore(store._db_path, "synthetic-password")
    with pytest.raises(vault.CredentialStaleError):
        store.selector_state(a)


def test_broad_parent_and_empty_existing_file_refused_before_sqlite(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("POSIX mode refusal; Windows DACL covered by secure-file suite")
    parent = tmp_path / "broad"
    parent.mkdir(mode=0o755)
    parent.chmod(0o755)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("SQLite must not open")

    with monkeypatch.context() as patch:
        patch.setattr(vault, "open_sqlite", forbidden)
        with pytest.raises(vault.CredentialVaultHardeningRequiredError):
            vault.CredentialStore(parent / "vault.db", "synthetic")
    assert calls == [] and not (parent / "vault.db").exists()
    harden_directory(parent)
    empty = parent / "vault.db"
    empty.touch()
    harden(empty)
    with pytest.raises(vault.CredentialVaultInvalidError):
        vault.CredentialStore(empty, "synthetic")
    assert empty.read_bytes() == b""


def test_lost_main_contents_latch_stale(store):
    a = BrokerSelector("dhan", "A")
    seed(store, a)
    original = store._db_path.read_bytes()
    store._db_path.write_bytes(b"not a SQLite vault")
    with pytest.raises(vault.CredentialStaleError):
        store.selector_state(a)
    store._db_path.write_bytes(original)
    with pytest.raises(vault.CredentialStaleError):
        store.selector_state(a)


def test_lost_required_account_compatibility_index_is_corruption(store):
    with closing(sqlite3.connect(store._db_path)) as conn:
        conn.execute("DROP INDEX idx_accounts_account_id")
        conn.commit()
    with pytest.raises(vault.CredentialVaultInvalidError):
        vault.CredentialStore(store._db_path, "synthetic-password")


@pytest.mark.parametrize("after_commit", [False, True])
def test_failed_commit_never_reports_success_or_retries(store, monkeypatch, after_commit):
    a = BrokerSelector("dhan", "A")
    before = seed(store, a)
    real_open = store._get_connection
    opened, commits = [], []

    class FaultConnection:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def commit(self):
            commits.append(True)
            if after_commit:
                self.connection.commit()
            raise OSError("secret-io-error")

    def open_fault():
        connection = real_open()
        opened.append(connection)
        return FaultConnection(connection)

    with monkeypatch.context() as patch:
        patch.setattr(store, "_get_connection", open_fault)
        with pytest.raises(vault.CredentialError, match="^credential_operation_failed$") as error:
            store.update_credentials(a, {"token": "new"}, expected=before)
        assert error.value.__cause__ is None and error.value.__suppress_context__
    assert commits == [True]
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")
    assert store.retrieve_credentials(a) == {"token": "new" if after_commit else "old"}
    assert state(store, a).version.generation == (2 if after_commit else 1)


def test_candidate_lineage_is_hidden_and_cannot_be_promoted(store):
    a = BrokerSelector("dhan", "A")
    seed(store, a)
    with closing(sqlite3.connect(store._db_path)) as conn:
        conn.execute("UPDATE credential_selector_versions SET origin='legacy_interim_candidate'")
        conn.commit()
    expected = state(store, a).version
    assert state(store, a).origin == "legacy_interim_candidate"
    assert store.account_for_selector(a) is None
    assert store.list_accounts() == []
    with pytest.raises(vault.CredentialNotFoundError):
        store.retrieve_credentials(a)
    with pytest.raises(vault.CredentialConflictError):
        store.put_credentials(a, "dhan", "Synthetic", {}, expected=expected)


def test_other_vault_generation_and_forged_receipts_fail(store, tmp_path):
    a = BrokerSelector("dhan", "A")
    before = seed(store, a)
    other_parent = tmp_path / "other"
    other_parent.mkdir()
    harden_directory(other_parent)
    other = vault.CredentialStore(other_parent / "vault.db", "synthetic-password")
    foreign = seed(other, a)
    assert before.generation == foreign.generation
    with pytest.raises(vault.CredentialStaleError):
        store.update_credentials(a, {}, expected=foreign)
    forged = vault.SelectorSnapshot(a, before)
    with pytest.raises(vault.CredentialStaleError):
        store.restore_selector(forged, expected=before)
    import pickle

    with pytest.raises(TypeError):
        pickle.dumps(store.snapshot_selector(a))


@pytest.mark.parametrize("member", ["vault.db", "vault.db-wal", "vault.db-shm", "vault.db-journal"])
@pytest.mark.parametrize("unsafe", ["broad", "symlink", "hardlink"])
def test_unsafe_family_refuses_before_sqlite_without_repair(tmp_path, monkeypatch, member, unsafe):
    if os.name == "nt":
        pytest.skip("POSIX link/mode fixture; native Windows admission requires its own runner")
    parent = tmp_path / "owned"
    parent.mkdir()
    harden_directory(parent)
    base = parent / "vault.db"
    with closing(sqlite3.connect(base)) as conn:
        conn.execute("CREATE TABLE synthetic(value)")
    harden(base)
    target = parent / member
    if target != base:
        target.write_bytes(b"synthetic")
        harden(target)
    if unsafe == "broad":
        target.chmod(0o644)
    elif unsafe == "symlink":
        saved = parent / "saved"
        target.rename(saved)
        target.symlink_to(saved)
    else:
        os.link(target, parent / "linked")
    baseline = {p.name: (p.lstat().st_mode, p.read_bytes()) for p in parent.iterdir()}
    called = []

    def forbidden(*args, **kwargs):
        called.append(True)
        raise RuntimeError("must not open SQLite")

    monkeypatch.setattr(vault, "open_sqlite", forbidden)
    error = vault.CredentialVaultHardeningRequiredError if unsafe == "broad" else vault.CredentialVaultInvalidError
    with pytest.raises(error):
        vault.CredentialStore(base, "synthetic")
    assert called == []
    assert {p.name: (p.lstat().st_mode, p.read_bytes()) for p in parent.iterdir()} == baseline


def test_only_missing_final_parent_may_be_created(tmp_path):
    harden_directory(tmp_path)
    created = vault.CredentialStore(tmp_path / "child" / "vault.db", "synthetic")
    created.close()
    with pytest.raises(vault.CredentialVaultInvalidError):
        vault.CredentialStore(tmp_path / "absent" / "grandchild" / "vault.db", "synthetic")
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("bad", [0, -1, 1.5, "bad"])
def test_copied_invalid_generation_is_refused_on_reopen(store, bad):
    seed(store, BrokerSelector("dhan", "A"))
    with closing(sqlite3.connect(store._db_path)) as conn:
        conn.execute("PRAGMA ignore_check_constraints=ON")
        conn.execute("UPDATE credential_selector_versions SET generation=?", (bad,))
        conn.commit()
    with pytest.raises(vault.CredentialVaultInvalidError):
        vault.CredentialStore(store._db_path, "synthetic-password")


def test_primary_noop_has_no_generation_and_unrelated_selector_bytes_are_isolated(store):
    a, b = BrokerSelector("openalgo", "A"), BrokerSelector("openalgo", "B")
    seed(store, a, primary=True)
    seed(store, b)
    before = state(store, a).version
    mutation = store.apply_primary_projection(store.snapshot_primary_projection(a, True))
    assert mutation.before_versions == mutation.after_versions == (before,)

    def row_bytes():
        with closing(sqlite3.connect(store._db_path)) as conn:
            return conn.execute("SELECT * FROM accounts WHERE account_id='A'").fetchone()

    original = row_bytes()
    store.put_setup(b, {"base_url": "https://[::1]:443", "ws_port": 65535}, expected=state(store, b).version)
    store.remove_selector(b, expected=state(store, b).version)
    assert row_bytes() == original
    assert state(store, a).version == before


def test_postcommit_physical_replacement_is_failure_with_possibly_applied_mutation(store, monkeypatch):
    a = BrokerSelector("dhan", "A")
    before = seed(store, a)
    real_open = store._get_connection
    saved = store._db_path.with_suffix(".after-commit")

    class SwapAfterCommit:
        def __init__(self, conn):
            self.conn = conn

        def __getattr__(self, name):
            return getattr(self.conn, name)

        def commit(self):
            self.conn.commit()
            os.replace(store._db_path, saved)

    with monkeypatch.context() as patch:
        patch.setattr(store, "_get_connection", lambda: SwapAfterCommit(real_open()))
        with pytest.raises(vault.CredentialStaleError):
            store.update_credentials(a, {"token": "possibly-applied"}, expected=before)
    os.replace(saved, store._db_path)
    with pytest.raises(vault.CredentialStaleError):
        store.selector_state(a)


def test_foreign_incarnation_in_same_file_latches_even_after_restore(store):
    a = BrokerSelector("dhan", "A")
    before = seed(store, a)
    with closing(sqlite3.connect(store._db_path)) as conn:
        conn.execute("UPDATE credential_vault_metadata SET vault_incarnation=?", (str(uuid.uuid4()),))
        conn.commit()
    with pytest.raises(vault.CredentialStaleError):
        store.update_credentials(a, {}, expected=before)
    with closing(sqlite3.connect(store._db_path)) as conn:
        conn.execute("UPDATE credential_vault_metadata SET vault_incarnation=?", (str(before.vault_incarnation),))
        conn.commit()
    with pytest.raises(vault.CredentialStaleError):
        store.retrieve_credentials(a)


def test_stale_precedes_missing_update_and_snapshot_restore_preserves_both_components(store):
    a = BrokerSelector("openalgo", "A")
    first = seed(store, a)
    with_setup = store.put_setup(a, {"base_url": "https://example.com:443", "ws_port": 1}, expected=first)
    snapshot = store.snapshot_selector(a)
    deleted = store.remove_selector(a, expected=with_setup)
    with pytest.raises(vault.CredentialStaleError):
        store.update_credentials(a, {}, expected=with_setup)
    restored = store.restore_selector(snapshot, expected=deleted)
    assert restored.generation == 4
    assert store.retrieve_credentials(a) == {"token": "old"}
    assert store.retrieve_setup(a) == {"base_url": "https://example.com:443", "ws_port": 1}
    copy = store.retrieve_setup(a)
    copy["ws_port"] = 200
    assert store.retrieve_setup(a)["ws_port"] == 1


def test_vault_refuses_wal_not_accepted_by_connection(tmp_path, monkeypatch):
    harden_directory(tmp_path)
    connections = []
    def memory_connection(*args, **kwargs):
        connection = sqlite3.connect(":memory:")
        connections.append(connection)
        return connection
    monkeypatch.setattr(vault, "open_sqlite", memory_connection)
    with pytest.raises(vault.CredentialVaultInvalidError):
        vault.CredentialStore(tmp_path / "vault.db", "synthetic")
    assert len(connections) == 1
    with pytest.raises(sqlite3.ProgrammingError):
        connections[0].execute("SELECT 1")


@pytest.mark.parametrize("replacement", ["MANAGED", "man aged"])
def test_copied_schema_with_changed_check_literal_is_not_normalised(store, replacement):
    with closing(sqlite3.connect(store._db_path)) as conn:
        conn.execute("PRAGMA writable_schema=ON")
        conn.execute("UPDATE sqlite_master SET sql=replace(sql,?,?) WHERE name='credential_selector_versions'",
                     ("'managed'", "'" + replacement + "'"))
        conn.commit()
    with pytest.raises(vault.CredentialVaultInvalidError):
        vault.CredentialStore(store._db_path, "synthetic-password")


def test_legacy_stage_primary_metadata_commits_once_with_complete_cas(store):
    a, b = BrokerSelector("dhan", "A"), BrokerSelector("dhan", "B")
    seed(store, a, primary=True)
    seed(store, b)
    stage = store.stage_credentials_for("dhan", "B", {"token": "new"}, broker="dhan", label="Updated", is_primary=True)
    assert next(row for row in stage.list_accounts() if row["account_id"] == "B")["is_primary"]
    result = stage.commit()
    assert result.generation == 2
    assert state(store, a).version.generation == 3
    assert store.account_for_selector(b).is_primary
    assert not store.account_for_selector(a).is_primary
    stage = store.stage_credentials_for("dhan", "A", {"token": "candidate"}, broker="dhan", label="A", is_primary=True)
    store.update_credentials(b, {"token": "concurrent"}, expected=state(store, b).version)
    with pytest.raises(vault.CredentialStaleError):
        stage.commit()
    assert store.retrieve_credentials(a) == {"token": "old"}


@pytest.mark.parametrize("column,collation", [("account_id", "NOCASE"), ("adapter_id", "RTRIM")])
@pytest.mark.parametrize("already_open", [False, True])
def test_copied_nonbinary_account_columns_are_refused(store, column, collation, already_open):
    seed(store, BrokerSelector("dhan", "CaseA"))
    path = store._db_path
    if not already_open:
        store.close()
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA writable_schema=ON")
        conn.execute(
            "UPDATE sqlite_master SET sql=replace(sql,?,?) WHERE name='accounts'",
            (f"{column} TEXT", f"{column} TEXT COLLATE/**/{collation}"),
        )
        conn.commit()
    if already_open:
        with pytest.raises(vault.CredentialStaleError):
            store.retrieve_credentials(BrokerSelector("dhan", "casea"))
        with pytest.raises(vault.CredentialStaleError):
            store.retrieve_credentials(BrokerSelector("dhan", "CaseA"))
    else:
        with pytest.raises(vault.CredentialVaultInvalidError):
            vault.CredentialStore(path, "synthetic-password")


@pytest.mark.parametrize("table", ["credential_selector_versions", "broker_selector_setup"])
def test_extra_nonbinary_authority_index_refused(store, table):
    seed(store, BrokerSelector("dhan", "CaseA"))
    path = store._db_path
    store.close()
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(f"CREATE UNIQUE INDEX unexpected_equality ON {table}(adapter_id, account_id COLLATE NOCASE)")
        conn.commit()
    with pytest.raises(vault.CredentialVaultInvalidError):
        vault.CredentialStore(path, "synthetic-password")


def test_nonbinary_account_compatibility_index_is_refused(store):
    seed(store, BrokerSelector("dhan", "CaseA"))
    path = store._db_path
    store.close()
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("DROP INDEX idx_accounts_account_id")
        conn.execute(
            "CREATE INDEX idx_accounts_account_id ON accounts(account_id COLLATE NOCASE)"
        )
        conn.commit()
    with pytest.raises(vault.CredentialVaultInvalidError):
        vault.CredentialStore(path, "synthetic-password")


def test_wrong_case_cannot_retrieve_or_mask_absence(store):
    exact, wrong = BrokerSelector("dhan", "CaseA"), BrokerSelector("dhan", "casea")
    seed(store, exact)
    assert store.account_for_selector(wrong) is None
    assert not store.selector_state(wrong).credential_present
    assert store.selector_state(wrong).version.generation == 0
    with pytest.raises(vault.CredentialNotFoundError):
        store.retrieve_credentials(wrong)
    store.put_credentials(wrong, "dhan", "Different case", {"token": "separate"},
                          expected=store.selector_state(wrong).version)
    assert store.retrieve_credentials(exact) == {"token": "old"}
    assert store.retrieve_credentials(wrong) == {"token": "separate"}


@pytest.mark.parametrize("already_open", [False, True])
@pytest.mark.parametrize("table", [
    "accounts", "credential_vault_metadata", "credential_selector_versions", "broker_selector_setup"
])
def test_authority_trigger_refused_before_side_effects(store, table, already_open):
    a, b = BrokerSelector("dhan", "A"), BrokerSelector("dhan", "B")
    expected = seed(store, a)
    seed(store, b)
    path = store._db_path
    if not already_open:
        store.close()
    with closing(sqlite3.connect(path)) as conn:
        before_accounts = conn.execute("SELECT * FROM accounts ORDER BY account_id").fetchall()
        before_versions = conn.execute("SELECT * FROM credential_selector_versions ORDER BY account_id").fetchall()
        conn.execute(f"""CREATE TRIGGER unexpected_sibling_write AFTER UPDATE ON {table}
                         BEGIN UPDATE accounts SET label='changed-by-trigger' WHERE account_id='B'; END""")
        conn.commit()
    if already_open:
        with pytest.raises(vault.CredentialStaleError):
            store.update_credentials(a, {"token": "updated"}, expected=expected)
        with pytest.raises(vault.CredentialStaleError):
            store.selector_state(b)
    else:
        with pytest.raises(vault.CredentialVaultInvalidError):
            vault.CredentialStore(path, "synthetic-password")
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT * FROM accounts ORDER BY account_id").fetchall() == before_accounts
        assert conn.execute("SELECT * FROM credential_selector_versions ORDER BY account_id").fetchall() == before_versions
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0] == 1


def test_failed_real_strict_open_latches_missing_main_before_restore(store, monkeypatch):
    selector = BrokerSelector("dhan", "A")
    seed(store, selector)
    path, saved = store._db_path, store._db_path.with_name("saved.db")
    real_open = vault.open_sqlite
    observed_errors = []

    def disappear_then_open(*args, **kwargs):
        os.replace(path, saved)
        try:
            return real_open(*args, **kwargs)
        except sqlite3.OperationalError as exc:
            observed_errors.append(exc.sqlite_errorcode)
            raise

    monkeypatch.setattr(vault, "open_sqlite", disappear_then_open)
    try:
        with pytest.raises(vault.CredentialStaleError, match="^credential_stale$"):
            store.selector_state(selector)
        assert observed_errors == [sqlite3.SQLITE_CANTOPEN]
    finally:
        # Restoration occurs only after the failed real mode=rw open returns.
        os.replace(saved, path)
    monkeypatch.setattr(vault, "open_sqlite", real_open)
    with pytest.raises(vault.CredentialStaleError):
        store.selector_state(selector)


def test_failed_open_with_unchanged_family_remains_fixed_transient_failure(store, monkeypatch):
    selector = BrokerSelector("dhan", "A")
    expected = seed(store, selector)
    real_open = vault.open_sqlite
    calls = []

    def transient_failure(*args, **kwargs):
        calls.append(1)
        raise sqlite3.OperationalError("synthetic-private-io-detail")

    monkeypatch.setattr(vault, "open_sqlite", transient_failure)
    with pytest.raises(vault.CredentialError, match="^credential_operation_failed$") as error:
        store.selector_state(selector)
    assert calls == [1]
    assert error.value.__suppress_context__
    monkeypatch.setattr(vault, "open_sqlite", real_open)
    assert store.selector_state(selector).version == expected
