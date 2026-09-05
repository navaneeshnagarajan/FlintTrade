"""T4-B (gap G4): composite (adapter_id, account_id) credentials + additive backfill.

The CredentialStore gains an ``adapter_id`` column and a selector-keyed
``retrieve_for``. The schema evolution is purely additive (ALTER TABLE ADD
COLUMN + backfill), so a legacy single-key ``credentials.db`` is migrated in
place with no data loss.
"""

from __future__ import annotations

import sqlite3

from flinttrade_core.broker_identity import BrokerSelector
from flinttrade_core.secure_file import harden_directory

import pytest
from flinttrade_gateway.credentials import CredentialStore, CredentialError

# Per-package pytest binds 'tests' locally; load the shared opt-in fixture by path.
import importlib.util as _fixture_import
from pathlib import Path as _FixturePath

_fixture_spec = _fixture_import.spec_from_file_location(
    "_credential_fixtures", _FixturePath(__file__).resolve().parents[4] / "tests" / "credential_fixtures.py",
)
_fixture_module = _fixture_import.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_module)
seed_credentials = _fixture_module.seed_credentials
legacy_vault = _fixture_module.legacy_vault



_MP = "test-master-password-123"
_CREDS = {"api_key": "k", "api_secret": "s"}


@pytest.mark.parametrize("schema_change", ["column", "index", "trigger"])
def test_unsupported_legacy_sql_semantics_refused_before_migration(tmp_path, schema_change):
    from contextlib import closing

    path = tmp_path / "legacy.db"
    legacy_vault(path, _MP, account_id="CaseA")
    with closing(sqlite3.connect(path)) as conn:
        if schema_change == "column":
            conn.execute("PRAGMA writable_schema=ON")
            conn.execute("""UPDATE sqlite_master SET sql=replace(sql,'account_id TEXT',
                            'account_id TEXT COLLATE NOCASE') WHERE name='accounts'""")
        elif schema_change == "index":
            conn.execute("CREATE UNIQUE INDEX legacy_nocase ON accounts(account_id COLLATE NOCASE)")
        else:
            conn.execute("""CREATE TRIGGER migration_side_effect AFTER UPDATE ON accounts
                            BEGIN UPDATE accounts SET label='changed-by-trigger'; END""")
        conn.commit()
        original = conn.execute("SELECT * FROM accounts").fetchall()
        schema = conn.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name").fetchall()
    with pytest.raises(CredentialError, match="^credential_vault_invalid$"):
        CredentialStore(path, _MP)
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        assert conn.execute("SELECT * FROM accounts").fetchall() == original
        assert conn.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name").fetchall() == schema


def test_store_with_adapter_id_retrieve_for_round_trip(tmp_path) -> None:
    harden_directory(tmp_path)
    store = CredentialStore(tmp_path / "c.db", _MP)
    seed_credentials(store, "personal", "dhan", "Personal", _CREDS, adapter_id="dhan")
    assert store.retrieve_for("dhan", "personal") == _CREDS


def test_adapter_id_defaults_to_broker(tmp_path) -> None:
    harden_directory(tmp_path)
    store = CredentialStore(tmp_path / "c.db", _MP)
    seed_credentials(store, "acct1", "zerodha", "Z", _CREDS)  # no adapter_id passed
    store.store("acct1", "zerodha", "Z", _CREDS)
    assert store.retrieve_for("zerodha", "acct1") == _CREDS


def test_retrieve_for_missing_raises(tmp_path) -> None:
    harden_directory(tmp_path)
    store = CredentialStore(tmp_path / "c.db", _MP)
    with pytest.raises(CredentialError, match="credential_not_found"):
        store.retrieve_for("dhan", "nope")


def test_two_adapters_disambiguated(tmp_path) -> None:
    harden_directory(tmp_path)
    store = CredentialStore(tmp_path / "c.db", _MP)
    seed_credentials(store, "acc-d", "dhan", "D", {"k": "dhan"}, adapter_id="dhan")
    seed_credentials(store, "acc-o", "zerodha", "O", {"k": "oa"}, adapter_id="openalgo")
    assert store.retrieve_for("dhan", "acc-d") == {"k": "dhan"}
    assert store.retrieve_for("openalgo", "acc-o") == {"k": "oa"}


def test_remove_for_is_selector_scoped(tmp_path) -> None:
    harden_directory(tmp_path)
    store = CredentialStore(tmp_path / "c.db", _MP)
    seed_credentials(store, "acc-d", "dhan", "D", {"k": "dhan"}, adapter_id="dhan")

    store.remove_for("upstox", "acc-d")
    assert store.retrieve_for("dhan", "acc-d") == {"k": "dhan"}

    store.remove_for("dhan", "acc-d")
    with pytest.raises(CredentialError, match="credential_not_found"):
        store.retrieve_for("dhan", "acc-d")


def test_legacy_db_backfills_adapter_id_from_broker(tmp_path) -> None:
    db = tmp_path / "legacy.db"
    legacy_vault(db, _MP, credentials=_CREDS)
    migrated = CredentialStore(db, _MP)
    assert migrated.retrieve_for("zerodha", "AB1234") == _CREDS
    rows = {a["account_id"]: a for a in migrated.list_accounts()}
    assert rows["AB1234"]["adapter_id"] == "zerodha"


def test_blank_adapter_id_is_self_healed_on_next_open(tmp_path) -> None:
    """A row stranded with ``adapter_id = ''`` (e.g. a crash mid-migration)
    is self-healed from its ``broker`` on the next open, and ``retrieve_for``
    then resolves it.
    """
    db = tmp_path / "stranded.db"
    legacy_vault(db, _MP, account_id="CD5678", broker="upstox", adapter_id="", credentials=_CREDS)
    healed = CredentialStore(db, _MP)
    rows = {a["account_id"]: a for a in healed.list_accounts()}
    assert rows["CD5678"]["adapter_id"] == "upstox"
    assert healed.retrieve_for("upstox", "CD5678") == _CREDS


def test_set_primary_leaves_exactly_one_primary(tmp_path) -> None:
    """After :meth:`set_primary` exactly one row carries ``is_primary = 1``."""
    db = tmp_path / "primary.db"
    harden_directory(tmp_path)
    store = CredentialStore(db, _MP)
    seed_credentials(store, "a1", "dhan", "A1", _CREDS, adapter_id="dhan", is_primary=True)
    seed_credentials(store, "a2", "dhan", "A2", _CREDS, adapter_id="dhan")
    seed_credentials(store, "a3", "zerodha", "A3", _CREDS, adapter_id="zerodha")

    store.set_primary("a2")

    with sqlite3.connect(db) as conn:
        primary_count = conn.execute(
            "SELECT COUNT(*) FROM accounts WHERE is_primary = 1"
        ).fetchone()[0]
        primary_id = conn.execute(
            "SELECT account_id FROM accounts WHERE is_primary = 1"
        ).fetchone()[0]
    assert primary_count == 1
    assert primary_id == "a2"


@pytest.mark.parametrize("broker", """zerodha fyers flattrade arrow tradesmart hdfcsecurities hdfcsky pocketful
paytm dhan aliceblue upstox compositedge rmoney angel fivepaisa zebu shoonya firstock tradejini mstock
kotak kotakneo motilal nubra samco deltaexchange groww wisdom ibulls iifl iiflcapital jainamxts
indmoney fivepaisaxts definedge dhan_sandbox""".split())
def test_frozen_legacy_identity_map_preserves_encrypted_content(tmp_path, broker):
    from contextlib import closing

    path = tmp_path / "historical.db"
    salt, ciphertext = legacy_vault(path, _MP, broker=broker, account_id="Opaque:Case+1", credentials=_CREDS)
    migrated = CredentialStore(path, _MP)
    selector = BrokerSelector(broker, "Opaque:Case+1")
    state = migrated.selector_state(selector)
    assert state.version.generation == 1
    assert state.origin == "legacy_pre_workspace_authority"
    assert migrated.retrieve_credentials(selector) == _CREDS
    with closing(sqlite3.connect(path)) as conn:
        row = conn.execute("SELECT account_id,salt,encrypted_creds,created_at,label,is_primary FROM accounts").fetchone()
    assert row == ("Opaque:Case+1", salt, ciphertext, "2026-01-01T00:00:00+00:00", "Synthetic", 0)


@pytest.mark.parametrize("broker,adapter", [("zerodha", "openalgo"), ("openalgo", "openalgo")])
def test_legacy_openalgo_roles_are_retained(tmp_path, broker, adapter):
    path = tmp_path / "historical.db"
    legacy_vault(path, _MP, broker=broker, adapter_id=adapter, credentials=_CREDS)
    migrated = CredentialStore(path, _MP)
    assert migrated.account_for_selector(BrokerSelector("openalgo", "AB1234")).broker == broker


@pytest.mark.parametrize("broker,adapter,account", [
    ("openalgo", None, "A"), ("unknown", None, "A"), ("Zerodha", None, "A"),
    ("kotak", "kotakneo", "A"), ("iifl", "iiflcapital", "A"),
    ("openalgo", "openalgo", "default"), ("dhan", None, "A%3AB"), ("dhan", None, ".."),
])
def test_unrecognised_legacy_identity_refuses_without_schema_or_content_changes(tmp_path, broker, adapter, account):
    from contextlib import closing
    from flinttrade_gateway.credentials import CredentialVaultInvalidError

    path = tmp_path / "historical.db"
    legacy_vault(path, _MP, broker=broker, adapter_id=adapter, account_id=account)
    with closing(sqlite3.connect(path)) as conn:
        before = list(conn.iterdump())
    with pytest.raises(CredentialVaultInvalidError):
        CredentialStore(path, _MP)
    with closing(sqlite3.connect(path)) as conn:
        assert list(conn.iterdump()) == before
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0


def test_primary_projection_captures_every_legacy_primary(tmp_path):
    from contextlib import closing

    path = tmp_path / "historical.db"
    legacy_vault(path, _MP, account_id="A", broker="dhan", credentials=_CREDS)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("UPDATE accounts SET is_primary=1")
        conn.execute("INSERT INTO accounts SELECT 'B',broker,label,salt,encrypted_creds,1,created_at FROM accounts")
        conn.commit()
    store = CredentialStore(path, _MP)
    seed_credentials(store, "C", "dhan", "Synthetic", _CREDS)
    snapshot = store.snapshot_primary_projection(BrokerSelector("dhan", "C"), True)
    assert tuple(version.selector.account_id for version in snapshot.versions) == ("A", "B", "C")
    mutation = store.apply_primary_projection(snapshot)
    assert tuple(version.generation for version in mutation.after_versions) == (2, 2, 2)
    store.restore_primary_projection(mutation)
    assert {row["account_id"]: row["is_primary"] for row in store.list_accounts()} == {"A": True, "B": True, "C": False}
    selected = BrokerSelector("dhan", "A")
    whole = store.snapshot_selector(selected)
    removed = store.remove_selector(selected, expected=whole.version)
    store.restore_selector(whole, expected=removed)
    assert {row["account_id"]: row["is_primary"] for row in store.list_accounts()} == {"A": True, "B": True, "C": False}
