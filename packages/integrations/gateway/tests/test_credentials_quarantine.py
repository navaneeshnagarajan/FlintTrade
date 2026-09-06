"""Disposable physical migration fixtures; no provider or decrypted source access."""

import base64
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from uuid import UUID

import pytest

from flinttrade_core.broker_identity import BrokerSelector
from flinttrade_core.secure_file import harden, harden_directory
from flinttrade_gateway import credentials as vault


ACCOUNT_SQL = """CREATE TABLE accounts (
    account_id TEXT PRIMARY KEY, adapter_id TEXT NOT NULL DEFAULT '',
    broker TEXT NOT NULL, label TEXT NOT NULL, salt BLOB NOT NULL,
    encrypted_creds BLOB NOT NULL, is_primary INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
)"""
METADATA_SQL = """CREATE TABLE credential_vault_metadata (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        schema_version INTEGER NOT NULL CHECK(typeof(schema_version)='integer' AND schema_version=1),
        vault_incarnation TEXT NOT NULL
    )"""
VERSIONS_SQL = """CREATE TABLE credential_selector_versions (
        adapter_id TEXT NOT NULL, account_id TEXT NOT NULL,
        generation INTEGER NOT NULL CHECK(typeof(generation)='integer' AND generation BETWEEN 1 AND 9223372036854775807),
        present INTEGER NOT NULL CHECK(typeof(present)='integer' AND present IN (0,1)),
        origin TEXT NOT NULL CHECK(origin IN ('legacy_pre_workspace_authority','legacy_interim_candidate',
                                             'legacy_interim_writer','managed')),
        PRIMARY KEY(adapter_id, account_id)
    )"""
SETUP_SQL = """CREATE TABLE broker_selector_setup (
        adapter_id TEXT NOT NULL, account_id TEXT NOT NULL,
        present INTEGER NOT NULL CHECK(typeof(present)='integer' AND present IN (0,1)),
        setup_json TEXT,
        CHECK((present=0 AND setup_json IS NULL) OR (present=1 AND typeof(setup_json)='text')),
        PRIMARY KEY(adapter_id, account_id)
    )"""
INCARNATION = "384bdd4b-929f-4ead-b171-d8351c9eb9b0"


def source(tmp_path, *, version=0, adapter=True):
    parent = tmp_path / "owned"
    parent.mkdir(exist_ok=True)
    harden_directory(parent)
    path = parent / "vault.db"
    with closing(sqlite3.connect(path)) as conn:
        sql = ACCOUNT_SQL if adapter else ACCOUNT_SQL.replace(" adapter_id TEXT NOT NULL DEFAULT '',", "")
        conn.execute(sql)
        if version:
            for ddl in (METADATA_SQL, VERSIONS_SQL, SETUP_SQL):
                conn.execute(ddl)
            conn.execute("INSERT INTO credential_vault_metadata VALUES(1,1,?)", (INCARNATION,))
            conn.execute("CREATE UNIQUE INDEX idx_accounts_adapter_account ON accounts(adapter_id, account_id)")
            conn.execute("PRAGMA user_version=1")
        conn.commit()
    harden(path)
    return path


def add(conn, account, adapter="dhan", broker="dhan", *, rowid=None, version=0, generation=7, origin="managed"):
    columns = [row[1] for row in conn.execute("PRAGMA table_info(accounts)")]
    values = dict(
        account_id=account,
        adapter_id=adapter,
        broker=broker,
        label="PRIVATE-label-Ω",
        salt=b"0123456789abcdef",
        encrypted_creds=b"PRIVATE-ciphertext\x00\xff",
        is_primary=1,
        created_at="PRIVATE-timestamp",
    )
    names = (["rowid"] if rowid is not None else []) + columns
    data = ([rowid] if rowid is not None else []) + [values[name] for name in columns]
    conn.execute(f"INSERT INTO accounts({','.join(names)}) VALUES({','.join('?' for _ in names)})", data)
    if version:
        conn.execute(
            "INSERT INTO credential_selector_versions VALUES(?,?,?,1,?)", (adapter, account, generation, origin)
        )


def logical(path):
    with closing(sqlite3.connect(path)) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return (
            conn.execute("PRAGMA user_version").fetchone(),
            conn.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name").fetchall(),
            {name: conn.execute(f"SELECT * FROM {name}").fetchall() for name in tables},
        )


@pytest.mark.parametrize("version", [0, 1])
@pytest.mark.parametrize("generated_kind", ["STORED", "VIRTUAL"])
def test_generated_source_columns_refuse_without_changing_any_source_state(tmp_path, version, generated_kind):
    path = source(tmp_path, version=version)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            "ALTER TABLE accounts ADD COLUMN unexpected TEXT "
            f"GENERATED ALWAYS AS ('PRIVATE-generated-cell') {generated_kind}"
        )
        if version:
            add(conn, "default", "openalgo", "openalgo", version=version)
        else:
            add(conn, "bad%")
        conn.commit()
        columns = conn.execute("PRAGMA table_xinfo(accounts)").fetchall()
        assert columns[-1][1] == "unexpected" and columns[-1][6] in {2, 3}
        assert conn.execute("SELECT unexpected FROM accounts").fetchone() == ("PRIVATE-generated-cell",)
    before = logical(path)

    with pytest.raises(vault.CredentialVaultInvalidError):
        vault.CredentialStore(path, "synthetic")

    assert logical(path) == before
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA table_xinfo(accounts)").fetchall() == columns
        assert conn.execute("PRAGMA user_version").fetchone() == (version,)
        assert conn.execute("SELECT unexpected FROM accounts").fetchone() == ("PRIVATE-generated-cell",)


@pytest.mark.parametrize("adapter", [False, True])
def test_zero_to_two_partitions_invalid_rows_and_preserves_raw_types(tmp_path, monkeypatch, adapter):
    path = source(tmp_path, adapter=adapter)
    with closing(sqlite3.connect(path)) as conn:
        add(conn, "Valid:Case")
        for rowid, account in [(-2, None), (0, None), (3, "bad%"), (4, "with space"), (5, "é"), (6, "a/b")]:
            add(conn, account, rowid=rowid)
        before = conn.execute(
            "SELECT salt,encrypted_creds,label,created_at,is_primary FROM accounts WHERE account_id='Valid:Case'"
        ).fetchone()
        conn.commit()

    def forbidden(*args, **kwargs):
        pytest.fail("Migration/list must not invoke credential cryptography")

    monkeypatch.setattr(vault.CredentialStore, "_derive_key", forbidden)
    store = vault.CredentialStore(path, "synthetic")
    assert [row["account_id"] for row in store.list_accounts()] == ["Valid:Case"]
    entries = store.list_quarantine()
    assert len(entries) == 6 and isinstance(entries, tuple)
    assert len({entry.ref.quarantine_id for entry in entries}) == 6
    assert all(entry.reason == "legacy_identity_invalid" for entry in entries)
    assert all(entry.provenance == "legacy_pre_workspace_authority" for entry in entries)
    assert all(entry.ref.row_generation == 1 for entry in entries)
    assert "PRIVATE" not in repr(entries) and "bad%" not in repr(entries)
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert conn.execute("SELECT schema_version FROM credential_vault_metadata").fetchone()[0] == 2
        assert (
            conn.execute("SELECT salt,encrypted_creds,label,created_at,is_primary FROM accounts").fetchone() == before
        )
        assert conn.execute("SELECT count(*) FROM credential_selector_versions").fetchone()[0] == 1
        captured = conn.execute(
            "SELECT source_rowid,raw_record FROM credential_quarantine ORDER BY source_rowid"
        ).fetchall()
        assert [row[0] for row in captured] == [-2, 0, 3, 4, 5, 6]
        for _, raw in captured:
            assert type(raw) is bytes
            envelope = json.loads(raw)
            cells = {cell[0]: cell[1:] for cell in envelope[1]}
            assert cells["encrypted_creds"] == ["blob", base64.b64encode(b"PRIVATE-ciphertext\x00\xff").decode()]
            assert cells["salt"] == ["blob", "MDEyMzQ1Njc4OWFiY2RlZg=="]
            assert cells["is_primary"] == ["integer", 1]
            assert cells["created_at"] == ["text", base64.b64encode(b"PRIVATE-timestamp").decode()]
            assert cells["label"] == ["text", base64.b64encode("PRIVATE-label-Ω".encode()).decode()]
            assert ("adapter_id" in cells) is adapter
        info = {r[1]: r[5] for r in conn.execute("PRAGMA table_info(accounts)")}
        assert (info["adapter_id"], info["account_id"]) == (1, 2)
    snapshot = logical(path)
    assert vault.CredentialStore(path, "synthetic").list_quarantine() == entries
    assert logical(path) == snapshot


@pytest.mark.parametrize("components", ["credentials", "setup", "both"])
def test_one_to_two_reserved_components_get_independent_refs_and_one_forward_tombstone(tmp_path, components):
    path = source(tmp_path, version=1)
    with closing(sqlite3.connect(path)) as conn:
        add(conn, "Other", version=1, generation=11, origin="legacy_interim_candidate")
        if components in {"credentials", "both"}:
            add(conn, "default", "openalgo", "zerodha", version=1, generation=8, origin="legacy_interim_writer")
        else:
            conn.execute(
                "INSERT INTO credential_selector_versions VALUES('openalgo','default',8,1,'legacy_interim_writer')"
            )
        if components in {"setup", "both"}:
            conn.execute(
                "INSERT INTO broker_selector_setup VALUES('openalgo','default',1,?)",
                ('{"base_url":"https://example.com"}',),
            )
        conn.commit()
    store = vault.CredentialStore(path, "synthetic")
    entries = store.list_quarantine()
    assert len(entries) == (2 if components == "both" else 1)
    assert all(entry.reason == "reserved_openalgo_default" for entry in entries)
    assert all(entry.provenance == "legacy_interim_writer" for entry in entries)
    assert all(entry.ref.source_vault_incarnation == UUID(INCARNATION) for entry in entries)
    reserved = store.selector_state(BrokerSelector("openalgo", "default"))
    assert reserved.version.generation == 9 and not reserved.present
    assert reserved.origin == "legacy_interim_writer"
    other = store.selector_state(BrokerSelector("dhan", "Other"))
    assert other.version.generation == 11 and other.version.vault_incarnation == UUID(INCARNATION)
    assert store.list_accounts() == []
    assert vault.CredentialStore(path, "synthetic").list_quarantine() == entries


def test_one_to_two_preserves_all_unrelated_versions_and_uuid(tmp_path):
    path = source(tmp_path, version=1)
    with closing(sqlite3.connect(path)) as conn:
        add(conn, "Normal", version=1, generation=11)
        conn.commit()
    store = vault.CredentialStore(path, "synthetic")
    assert store.list_quarantine() == ()
    state = store.selector_state(BrokerSelector("dhan", "Normal"))
    assert (state.version.generation, state.version.vault_incarnation) == (11, UUID(INCARNATION))


@pytest.mark.parametrize("change", ["identity", "overflow", "markers"])
def test_invalid_version_one_is_global_refusal_unchanged(tmp_path, change):
    path = source(tmp_path, version=1)
    with closing(sqlite3.connect(path)) as conn:
        if change == "identity":
            add(conn, "bad%", version=1)
        else:
            add(conn, "default", "openalgo", "openalgo", version=1, generation=2**63 - 1)
        if change == "markers":
            conn.execute("PRAGMA user_version=2")
        conn.commit()
    before = logical(path)
    with pytest.raises(vault.CredentialVaultInvalidError, match="^credential_vault_invalid$"):
        vault.CredentialStore(path, "synthetic")
    assert logical(path) == before


def test_concurrent_open_migrates_once(tmp_path):
    path = source(tmp_path)
    with closing(sqlite3.connect(path)) as conn:
        add(conn, "bad%")
        conn.commit()

    def open_list(_):
        store = vault.CredentialStore(path, "synthetic")
        try:
            return store.list_quarantine()
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = list(pool.map(open_list, range(2)))
    assert len(one) == 1 and one == two


@pytest.mark.parametrize("require_hardened", [False, True], ids=["classification", "family"])
@pytest.mark.parametrize("suffix", ["-wal", "-shm"])
def test_concurrent_open_survives_last_close_during_sidecar_validation(
    tmp_path, monkeypatch, require_hardened, suffix,
):
    path = source(tmp_path)
    with closing(sqlite3.connect(path)) as conn:
        add(conn, "bad%")
        conn.commit()
    initial_identity = (path.stat().st_dev, path.stat().st_ino)
    sidecar = path.with_name(path.name + suffix)
    first_closing = threading.Event()
    second_validating = threading.Event()
    first_closed = threading.Event()
    second_done = threading.Event()
    role = threading.local()
    missing = []
    real_open = vault.open_sqlite
    real_validate = vault.validate_owner_owned_regular_file

    class ClosingConnection:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        @property
        def row_factory(self):
            return self.connection.row_factory

        @row_factory.setter
        def row_factory(self, value):
            self.connection.row_factory = value

        def close(self):
            if first_closing.is_set():
                self.connection.close()
                return
            assert sidecar.exists()
            first_closing.set()
            try:
                assert second_validating.wait(10), "second constructor did not observe the sidecar"
            finally:
                self.connection.close()  # Real last SQLite close removes WAL and SHM.
                assert not sidecar.exists()
                first_closed.set()
            assert second_done.wait(10), "second constructor did not complete"

    def coordinated_open(*args, **kwargs):
        connection = real_open(*args, **kwargs)
        return ClosingConnection(connection) if role.first else connection

    def coordinated_validate(member, *args, **kwargs):
        if (not role.first and member == sidecar and not second_validating.is_set()
                and kwargs.get("require_hardened", False) == require_hardened):
            assert sidecar.exists()
            second_validating.set()
            assert first_closed.wait(10), "first connection did not close"
            assert not sidecar.exists()
            try:
                return real_validate(member, *args, **kwargs)
            except FileNotFoundError:
                missing.append(suffix)
                raise
        return real_validate(member, *args, **kwargs)

    def construct(first):
        role.first = first
        store = None
        try:
            store = vault.CredentialStore(path, "synthetic")
            return store.list_quarantine(), store.selector_state(BrokerSelector("dhan", "Unseen")).version
        finally:
            if store is not None:
                store.close()
            if not first:
                second_done.set()

    monkeypatch.setattr(vault, "open_sqlite", coordinated_open)
    monkeypatch.setattr(vault, "validate_owner_owned_regular_file", coordinated_validate)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(construct, True)
        assert first_closing.wait(10), "first constructor did not reach close"
        second = pool.submit(construct, False)
        two, two_version = second.result(timeout=15)
        one, one_version = first.result(timeout=15)
    assert missing == [suffix]
    assert len(one) == 1 and one == two
    assert one_version == two_version
    assert one[0].ref.source_vault_incarnation == one_version.vault_incarnation
    assert (path.stat().st_dev, path.stat().st_ino) == initial_identity
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone() == (2,)
        assert conn.execute("SELECT schema_version,vault_incarnation FROM credential_vault_metadata").fetchone() == (
            2, str(one_version.vault_incarnation),
        )


@pytest.mark.parametrize("require_hardened", [False, True], ids=["classification", "family"])
@pytest.mark.parametrize("change", ["reappeared", "unsafe", "main", "parent", "permission_error"])
def test_sidecar_disappearance_does_not_admit_changed_family(tmp_path, monkeypatch, require_hardened, change):
    path = source(tmp_path)
    sidecar = path.with_name(path.name + "-wal")
    sidecar.write_bytes(b"synthetic-sidecar")
    harden(sidecar)
    real_validate = vault.validate_owner_owned_regular_file
    observed = []
    opened = []

    def change_during_validation(member, *args, **kwargs):
        if (member == sidecar and not observed
                and kwargs.get("require_hardened", False) == require_hardened):
            observed.append(change)
            sidecar.unlink()
            if change == "permission_error":
                raise PermissionError("synthetic validation refusal")
            try:
                real_validate(member, *args, **kwargs)
            except FileNotFoundError:
                if change == "reappeared":
                    sidecar.write_bytes(b"synthetic-replacement")
                    harden(sidecar)
                elif change == "unsafe":
                    sidecar.mkdir()
                elif change == "main":
                    replacement = path.with_name("replacement.db")
                    replacement.write_bytes(path.read_bytes())
                    harden(replacement)
                    replacement.replace(path)
                elif change == "parent":
                    path.parent.rename(path.parent.with_name("saved"))
                    path.parent.mkdir()
                    harden_directory(path.parent)
                raise
        return real_validate(member, *args, **kwargs)

    def forbidden_open(*args, **kwargs):
        opened.append(True)
        raise AssertionError("unsafe family reached SQLite")

    monkeypatch.setattr(vault, "validate_owner_owned_regular_file", change_during_validation)
    monkeypatch.setattr(vault, "open_sqlite", forbidden_open)
    with pytest.raises(vault.CredentialVaultInvalidError):
        vault.CredentialStore(path, "synthetic")
    assert observed == [change]
    assert opened == []


def test_sidecar_disappearance_without_initial_main_witness_refuses(tmp_path, monkeypatch):
    path = source(tmp_path)
    path.unlink()
    sidecar = path.with_name(path.name + "-wal")
    sidecar.write_bytes(b"synthetic-sidecar")
    harden(sidecar)
    real_validate = vault.validate_owner_owned_regular_file
    observed = []
    opened = []

    def disappear(member, *args, **kwargs):
        if member == sidecar:
            observed.append(True)
            sidecar.unlink()
        return real_validate(member, *args, **kwargs)

    def forbidden_open(*args, **kwargs):
        opened.append(True)
        raise AssertionError("missing main witness reached SQLite")

    monkeypatch.setattr(vault, "validate_owner_owned_regular_file", disappear)
    monkeypatch.setattr(vault, "open_sqlite", forbidden_open)
    with pytest.raises(vault.CredentialVaultInvalidError):
        vault.CredentialStore(path, "synthetic")
    assert observed == [True]
    assert opened == []
    assert not path.exists()


@pytest.mark.parametrize("adapter", ["dhan", "upstox"])
def test_exact_existing_sibling_stage_update_restore_and_deletion_isolate_other(tmp_path, adapter):
    path = source(tmp_path)
    with closing(sqlite3.connect(path)) as conn:
        add(conn, "SHARED")
        conn.commit()
    store = vault.CredentialStore(path, "synthetic")
    # Only the schema fixture introduces duplicates; public creation is disabled.
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            "INSERT INTO accounts SELECT account_id,'upstox','upstox',label,salt,encrypted_creds,0,created_at FROM accounts"
        )
        conn.execute("INSERT INTO credential_selector_versions VALUES('upstox','SHARED',1,1,'managed')")
        conn.commit()
    selected = BrokerSelector(adapter, "SHARED")
    other = BrokerSelector("upstox" if adapter == "dhan" else "dhan", "SHARED")

    def sibling():
        with closing(sqlite3.connect(path)) as conn:
            return (
                conn.execute("SELECT * FROM accounts WHERE adapter_id=?", (other.adapter_id,)).fetchall(),
                conn.execute(
                    "SELECT * FROM credential_selector_versions WHERE adapter_id=?", (other.adapter_id,)
                ).fetchall(),
            )

    before = sibling()
    store.apply_primary_projection(store.snapshot_primary_projection(selected, False))
    assert sibling() == before
    version = store.selector_state(selected).version
    store.update_credentials(selected, {"token": "synthetic-updated"}, expected=version)
    snap = store.snapshot_selector(selected)
    stage = store.stage_credentials(selected)
    stage.update_credentials_for(adapter, "SHARED", {"token": "synthetic-stage"})
    after = stage.commit()
    assert store.retrieve_credentials(selected) == {"token": "synthetic-stage"}
    restored = store.restore_selector(snap, expected=after)
    assert store.retrieve_credentials(selected) == {"token": "synthetic-updated"}
    assert sibling() == before
    # Legacy wrappers must never choose a duplicate by row order.
    for call in (
        lambda: store.retrieve("SHARED"),
        lambda: store.remove("SHARED"),
        lambda: store.store("SHARED", adapter, "Synthetic", {}),
        lambda: store.account_exists("SHARED"),
    ):
        with pytest.raises(vault.CredentialAmbiguityError):
            call()
    removed = store.remove_selector(selected, expected=restored)
    assert sibling() == before
    with pytest.raises(vault.CredentialConflictError):
        store.restore_selector(snap, expected=removed)
    with pytest.raises(vault.CredentialConflictError):
        store.put_credentials(selected, adapter, "Synthetic", {}, expected=removed)
    with pytest.raises(vault.CredentialConflictError):
        store.stage_credentials(selected, {}, broker=adapter, label="Synthetic")
    assert sibling() == before and store.selector_state(selected).version == removed


@pytest.mark.parametrize(
    "point",
    [
        "INSERT INTO accounts_v2",
        "INSERT INTO credential_quarantine",
        "DROP TABLE accounts",
        "ALTER TABLE accounts_v2",
        "CREATE INDEX idx_accounts_account_id",
        "PRAGMA user_version=2",
        "commit",
    ],
)
@pytest.mark.parametrize("source_version", [0, 1])
def test_each_precommit_migration_failure_rolls_back_logical_source(tmp_path, monkeypatch, point, source_version):
    path = source(tmp_path, version=source_version)
    with closing(sqlite3.connect(path)) as conn:
        add(conn, "Normal", version=source_version)
        add(
            conn,
            "default" if source_version else "bad%",
            "openalgo" if source_version else "dhan",
            "openalgo" if source_version else "dhan",
            version=source_version,
        )
        conn.commit()
    before = logical(path)
    real = vault.CredentialStore._get_connection
    hits = []

    class Fault:
        def __init__(self, conn):
            self.conn = conn

        def __getattr__(self, name):
            return getattr(self.conn, name)

        def execute(self, sql, *args):
            result = self.conn.execute(sql, *args)
            if sql.startswith(point):
                hits.append(point)
                raise sqlite3.OperationalError("PRIVATE-source-error")
            return result

        def commit(self):
            if point == "commit":
                hits.append(point)
                raise sqlite3.OperationalError("PRIVATE-commit-error")
            return self.conn.commit()

    monkeypatch.setattr(vault.CredentialStore, "_get_connection", lambda self: Fault(real(self)))
    with pytest.raises(vault.CredentialVaultInvalidError, match="^credential_vault_invalid$"):
        vault.CredentialStore(path, "synthetic")
    assert hits == [point]
    assert logical(path) == before
    monkeypatch.setattr(vault.CredentialStore, "_get_connection", real)
    assert len(vault.CredentialStore(path, "synthetic").list_quarantine()) == 1


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE credential_quarantine SET row_generation=0",
        "UPDATE credential_quarantine SET row_generation=-1",
        "UPDATE credential_quarantine SET row_generation=1.5",
        "UPDATE credential_quarantine SET row_generation=9223372036854775808",
        "UPDATE credential_quarantine SET quarantine_id='invalid'",
        "UPDATE credential_quarantine SET source_vault_incarnation='384bdd4b-929f-4ead-b171-d8351c9eb9b0'",
        "UPDATE credential_quarantine SET provenance='unknown'",
        "UPDATE credential_quarantine SET reason='unknown'",
        "UPDATE credential_quarantine SET source_schema_version=2",
        "UPDATE credential_quarantine SET raw_record=X'5b5d'",
        "UPDATE credential_quarantine SET source_rowid=1.5",
    ],
)
def test_copied_quarantine_corruption_refuses_reopen_and_poisoned_read(tmp_path, sql):
    path = source(tmp_path)
    with closing(sqlite3.connect(path)) as conn:
        add(conn, "bad%")
        conn.commit()
    store = vault.CredentialStore(path, "synthetic")
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA ignore_check_constraints=ON")
        conn.execute(sql)
        conn.commit()
    before = logical(path)
    with pytest.raises(vault.CredentialVaultInvalidError, match="^credential_vault_invalid$"):
        vault.CredentialStore(path, "synthetic")
    with pytest.raises(vault.CredentialStaleError):
        store.list_quarantine()
    assert logical(path) == before


@pytest.mark.parametrize("change", ["version", "cells", "encoding", "text_class", "blob_class", "snapshot"])
def test_closed_raw_envelope_rejects_lossy_or_unrecognised_copied_records(tmp_path, change):
    path = source(tmp_path)
    with closing(sqlite3.connect(path)) as conn:
        add(conn, "bad%")
        conn.commit()
    vault.CredentialStore(path, "synthetic").close()
    with closing(sqlite3.connect(path)) as conn:
        raw = conn.execute("SELECT raw_record FROM credential_quarantine").fetchone()[0]
        envelope = json.loads(raw)
        if change == "version":
            envelope[0] = True
        elif change == "cells":
            envelope[1].append(envelope[1][0])
        elif change == "encoding":
            envelope[1][0][2] += "="
        elif change == "text_class":
            next(cell for cell in envelope[1] if cell[0] == "label")[1] = "blob"
        elif change == "blob_class":
            next(cell for cell in envelope[1] if cell[0] == "salt")[1] = "text"
        else:
            envelope[2] = []
        conn.execute(
            "UPDATE credential_quarantine SET raw_record=?", (json.dumps(envelope, separators=(",", ":")).encode(),)
        )
        conn.commit()
    with pytest.raises(vault.CredentialVaultInvalidError):
        vault.CredentialStore(path, "synthetic")


def test_quarantine_schema_checks_constraints_triggers_and_binary_indices(tmp_path):
    path = source(tmp_path)
    with closing(sqlite3.connect(path)) as conn:
        add(conn, "bad%")
        conn.commit()
    vault.CredentialStore(path, "synthetic").close()
    with closing(sqlite3.connect(path)) as conn:
        for value in (0, -1, 1.5, "malformed", 2**63 * 1.0):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("UPDATE credential_quarantine SET row_generation=?", (value,))
        conn.execute("CREATE TRIGGER poison AFTER INSERT ON credential_quarantine BEGIN DELETE FROM accounts; END")
        conn.commit()
    with pytest.raises(vault.CredentialVaultInvalidError):
        vault.CredentialStore(path, "synthetic")


@pytest.mark.parametrize("damage", ["without_rowid", "bad_salt", "real_adapter", "bad_flag"])
def test_global_source_corruption_cannot_be_reclassified_as_row_recovery(tmp_path, damage):
    path = source(tmp_path)
    with closing(sqlite3.connect(path)) as conn:
        add(conn, "bad%")
        if damage == "without_rowid":
            conn.execute("ALTER TABLE accounts RENAME TO old_accounts")
            conn.execute(ACCOUNT_SQL + " WITHOUT ROWID")
            conn.execute("INSERT INTO accounts SELECT * FROM old_accounts")
            conn.execute("DROP TABLE old_accounts")
        elif damage == "bad_salt":
            conn.execute("UPDATE accounts SET salt=X'00'")
        elif damage == "real_adapter":
            conn.execute("UPDATE accounts SET adapter_id=CAST(1.5 AS BLOB)")
            # BLOB identity is representable; an unsupported REAL storage class
            # is deliberately placed in a non-identity column instead.
            conn.execute("UPDATE accounts SET is_primary=1.5")
        else:
            conn.execute("UPDATE accounts SET is_primary=2")
        conn.commit()
    before = logical(path)
    with pytest.raises(vault.CredentialVaultInvalidError):
        vault.CredentialStore(path, "synthetic")
    assert logical(path) == before


@pytest.mark.parametrize(
    "adapter,broker,reason",
    [
        (None, "dhan", None),
        ("", "dhan", None),
        ("Dhan", "dhan", "legacy_identity_invalid"),
        ("dhan ", "dhan", "legacy_identity_invalid"),
        (b"dhan", "dhan", "legacy_identity_invalid"),
        ("dhan", "upstox", "legacy_role_unresolved"),
        ("kotakneo", "kotak", "legacy_role_unresolved"),
        ("iiflcapital", "iifl", "legacy_role_unresolved"),
        ("unknown", "unknown", "legacy_role_unresolved"),
    ],
)
def test_nullable_legacy_adapter_roles_are_not_normalised(tmp_path, adapter, broker, reason):
    path = source(tmp_path, adapter=False)
    with closing(sqlite3.connect(path)) as conn:
        # Literal legacy additive producer permits NULL; this is not a versioned
        # table with its authority erased.
        conn.execute("ALTER TABLE accounts ADD COLUMN adapter_id TEXT DEFAULT ''")
        add(conn, "A", adapter, broker)
        conn.commit()
    store = vault.CredentialStore(path, "synthetic")
    if reason is None:
        assert store.list_quarantine() == ()
        assert store.list_accounts()[0]["adapter_id"] == "dhan"
    else:
        assert store.list_accounts() == []
        assert store.list_quarantine()[0].reason == reason


def test_reserved_setup_snapshot_corruption_is_not_new_authority(tmp_path):
    path = source(tmp_path, version=1)
    with closing(sqlite3.connect(path)) as conn:
        add(conn, "default", "openalgo", "openalgo", version=1)
        conn.commit()
    vault.CredentialStore(path, "synthetic").close()
    with closing(sqlite3.connect(path)) as conn:
        envelope = json.loads(conn.execute("SELECT raw_record FROM credential_quarantine").fetchone()[0])
        next(cell for cell in envelope[2] if cell[0] == "generation")[2] = 3
        conn.execute(
            "UPDATE credential_quarantine SET raw_record=?", (json.dumps(envelope, separators=(",", ":")).encode(),)
        )
        conn.commit()
    with pytest.raises(vault.CredentialVaultInvalidError):
        vault.CredentialStore(path, "synthetic")


def test_uncertain_migration_commit_is_failure_without_retry_or_false_rollback(tmp_path, monkeypatch):
    path = source(tmp_path)
    with closing(sqlite3.connect(path)) as conn:
        add(conn, "bad%")
        conn.commit()
    real = vault.CredentialStore._get_connection
    commits = []

    class Uncertain:
        def __init__(self, conn):
            self.conn = conn

        def __getattr__(self, name):
            return getattr(self.conn, name)

        def commit(self):
            self.conn.commit()
            commits.append(1)
            raise sqlite3.OperationalError("synthetic uncertain commit")

    monkeypatch.setattr(vault.CredentialStore, "_get_connection", lambda self: Uncertain(real(self)))
    with pytest.raises(vault.CredentialVaultInvalidError):
        vault.CredentialStore(path, "synthetic")
    assert commits == [1]
    applied = logical(path)
    assert applied[0] == (2,)
    monkeypatch.setattr(vault.CredentialStore, "_get_connection", real)
    assert len(vault.CredentialStore(path, "synthetic").list_quarantine()) == 1
    assert logical(path) == applied


def test_quarantine_read_inherits_observed_same_incarnation_replacement_poison(tmp_path):
    import os
    import shutil

    path = source(tmp_path)
    with closing(sqlite3.connect(path)) as conn:
        add(conn, "bad%")
        conn.commit()
    store = vault.CredentialStore(path, "synthetic")
    entries = store.list_quarantine()
    saved, copied = path.with_suffix(".saved"), path.with_suffix(".copy")
    shutil.copy2(path, copied)
    os.replace(path, saved)
    os.replace(copied, path)
    with pytest.raises(vault.CredentialStaleError):
        store.list_quarantine()
    os.replace(saved, path)
    with pytest.raises(vault.CredentialStaleError):
        store.list_quarantine()
    assert vault.CredentialStore(path, "synthetic").list_quarantine() == entries


@pytest.mark.parametrize("setup", [None, 0, 1])
def test_one_to_two_reserved_absent_and_setup_tombstones_do_not_bump_without_removal(tmp_path, setup):
    path = source(tmp_path, version=1)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            "INSERT INTO credential_selector_versions VALUES('openalgo','default',5,?,'managed')", (int(setup == 1),)
        )
        if setup is not None:
            conn.execute(
                "INSERT INTO broker_selector_setup VALUES('openalgo','default',?,?)",
                (setup, '{"base_url":"https://example.com"}' if setup else None),
            )
        conn.commit()
    store = vault.CredentialStore(path, "synthetic")
    state = store.selector_state(BrokerSelector("openalgo", "default"))
    assert state.version.generation == (6 if setup == 1 else 5)
    assert not state.present
    assert len(store.list_quarantine()) == int(setup == 1)


def test_unrelated_setup_and_versions_are_byte_preserved_by_reserved_cutover(tmp_path):
    path = source(tmp_path, version=1)
    with closing(sqlite3.connect(path)) as conn:
        add(conn, "default", "openalgo", "openalgo", version=1)
        conn.execute("INSERT INTO credential_selector_versions VALUES('openalgo','Other',14,1,'managed')")
        conn.execute(
            "INSERT INTO broker_selector_setup VALUES('openalgo','Other',1,?)",
            ('{"base_url":"https://example.com:8443","ws_port":8766}',),
        )
        before = conn.execute("SELECT * FROM broker_selector_setup").fetchall()
        conn.commit()
    store = vault.CredentialStore(path, "synthetic")
    assert store.selector_state(BrokerSelector("openalgo", "Other")).version.generation == 14
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT * FROM broker_selector_setup").fetchall() == before


@pytest.mark.parametrize(
    "change",
    [
        "DROP TABLE credential_quarantine",
        "PRAGMA user_version=1",
        "CREATE INDEX extra_quarantine_equality ON credential_quarantine(quarantine_id COLLATE NOCASE)",
    ],
)
def test_missing_or_wrong_quarantine_schema_is_global_corruption(tmp_path, change):
    path = source(tmp_path)
    store = vault.CredentialStore(path, "synthetic")
    store.close()
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(change)
        conn.commit()
    before = logical(path)
    with pytest.raises(vault.CredentialVaultInvalidError):
        vault.CredentialStore(path, "synthetic")
    assert logical(path) == before


@pytest.mark.parametrize("first", ["credentials", "setup"])
def test_first_component_cannot_bypass_unified_sibling_presence(tmp_path, first):
    store = vault.CredentialStore(source(tmp_path), "synthetic")
    native, bridge = BrokerSelector("dhan", "SHARED"), BrokerSelector("openalgo", "SHARED")
    if first == "credentials":
        store.put_credentials(native, "dhan", "Synthetic", {}, expected=store.selector_state(native).version)

        def call():
            return store.put_setup(
                bridge, {"base_url": "https://example.com"}, expected=store.selector_state(bridge).version
            )
    else:
        store.put_setup(bridge, {"base_url": "https://example.com"}, expected=store.selector_state(bridge).version)

        def call():
            return store.put_credentials(native, "dhan", "Synthetic", {}, expected=store.selector_state(native).version)

    before = logical(store._db_path)
    with pytest.raises(vault.CredentialConflictError):
        call()
    assert logical(store._db_path) == before
    if first == "setup":
        with pytest.raises(vault.CredentialConflictError):
            store.stage_credentials(native, {}, broker="dhan", label="Synthetic")


def test_setup_sibling_update_allowed_but_missing_setup_restore_refused(tmp_path):
    store = vault.CredentialStore(source(tmp_path), "synthetic")
    native, bridge = BrokerSelector("dhan", "SHARED"), BrokerSelector("openalgo", "SHARED")
    expected = store.selector_state(bridge).version
    store.put_credentials(bridge, "openalgo", "Synthetic", {}, expected=expected)
    store.put_setup(bridge, {"base_url": "https://example.com"}, expected=store.selector_state(bridge).version)
    with closing(sqlite3.connect(store._db_path)) as conn:
        conn.execute(
            "INSERT INTO accounts SELECT account_id,'dhan','dhan',label,salt,encrypted_creds,0,created_at FROM accounts"
        )
        conn.execute("INSERT INTO credential_selector_versions VALUES('dhan','SHARED',1,1,'managed')")
        conn.commit()
    native_version = store.selector_state(native).version
    snap = store.snapshot_selector(bridge)
    changed = store.put_setup(
        bridge, {"base_url": "https://example.com:8443"}, expected=store.selector_state(bridge).version
    )
    restored = store.restore_selector(snap, expected=changed)
    assert store.retrieve_setup(bridge) == {"base_url": "https://example.com"}
    assert store.selector_state(native).version == native_version
    removed = store.remove_setup(bridge, expected=restored)
    before = logical(store._db_path)
    with pytest.raises(vault.CredentialConflictError):
        store.restore_selector(snap, expected=removed)
    with pytest.raises(vault.CredentialConflictError):
        store.put_setup(bridge, {"base_url": "https://example.com"}, expected=removed)
    assert logical(store._db_path) == before


def test_absent_sibling_tombstone_does_not_prevent_first_component(tmp_path):
    store = vault.CredentialStore(source(tmp_path), "synthetic")
    native, bridge = BrokerSelector("dhan", "SHARED"), BrokerSelector("openalgo", "SHARED")
    absent = store.remove_selector(bridge, expected=store.selector_state(bridge).version)
    native_version = store.put_credentials(
        native, "dhan", "Synthetic", {}, expected=store.selector_state(native).version
    )
    snapshot = store.snapshot_selector(native)
    assert store.selector_state(bridge).version == absent
    native_absent = store.remove_selector(native, expected=native_version)
    store.put_setup(bridge, {"base_url": "https://example.com"}, expected=absent)
    before = logical(store._db_path)
    with pytest.raises(vault.CredentialConflictError):
        store.restore_selector(snapshot, expected=native_absent)
    assert logical(store._db_path) == before


def test_version_two_open_refuses_failed_sqlite_integrity_check(tmp_path, monkeypatch):
    path = source(tmp_path)
    vault.CredentialStore(path, "synthetic").close()
    before = logical(path)
    real = vault.CredentialStore._get_connection
    checks = []

    class InvalidIntegrity:
        def __init__(self, conn):
            self.conn = conn

        def __getattr__(self, name):
            return getattr(self.conn, name)

        def execute(self, sql, *args):
            if sql == "PRAGMA integrity_check":
                checks.append(sql)
                return self.conn.execute("SELECT 'synthetic corrupt index'")
            return self.conn.execute(sql, *args)

    monkeypatch.setattr(vault.CredentialStore, "_get_connection", lambda self: InvalidIntegrity(real(self)))
    with pytest.raises(vault.CredentialVaultInvalidError):
        vault.CredentialStore(path, "synthetic")
    assert checks == ["PRAGMA integrity_check"] and logical(path) == before
