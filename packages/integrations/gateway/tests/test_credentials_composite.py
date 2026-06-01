"""T4-B (gap G4): composite (adapter_id, account_id) credentials + additive backfill.

The CredentialStore gains an ``adapter_id`` column and a selector-keyed
``retrieve_for``. The schema evolution is purely additive (ALTER TABLE ADD
COLUMN + backfill), so a legacy single-key ``credentials.db`` is migrated in
place with no data loss.
"""

from __future__ import annotations

import json
import os
import sqlite3

import pytest

from flinttrade_gateway.credentials import CredentialStore, CredentialError

_MP = "test-master-password-123"
_CREDS = {"api_key": "k", "api_secret": "s"}


def test_store_with_adapter_id_retrieve_for_round_trip(tmp_path) -> None:
    store = CredentialStore(tmp_path / "c.db", _MP)
    store.store("personal", "dhan", "Personal", _CREDS, adapter_id="dhan")
    assert store.retrieve_for("dhan", "personal") == _CREDS


def test_adapter_id_defaults_to_broker(tmp_path) -> None:
    store = CredentialStore(tmp_path / "c.db", _MP)
    store.store("acct1", "zerodha", "Z", _CREDS)  # no adapter_id passed
    assert store.retrieve_for("zerodha", "acct1") == _CREDS


def test_retrieve_for_missing_raises(tmp_path) -> None:
    store = CredentialStore(tmp_path / "c.db", _MP)
    with pytest.raises(CredentialError, match="selector"):
        store.retrieve_for("dhan", "nope")


def test_two_adapters_disambiguated(tmp_path) -> None:
    store = CredentialStore(tmp_path / "c.db", _MP)
    store.store("acc-d", "dhan", "D", {"k": "dhan"}, adapter_id="dhan")
    store.store("acc-o", "zerodha", "O", {"k": "oa"}, adapter_id="openalgo")
    assert store.retrieve_for("dhan", "acc-d") == {"k": "dhan"}
    assert store.retrieve_for("openalgo", "acc-o") == {"k": "oa"}


def test_legacy_db_backfills_adapter_id_from_broker(tmp_path) -> None:
    db = tmp_path / "legacy.db"
    # 1. create a store so we can reuse its key derivation, then replicate a
    #    legacy (pre-adapter_id) row by recreating the OLD schema.
    store = CredentialStore(db, _MP)
    salt = os.urandom(16)
    enc = store._derive_key(salt).encrypt(json.dumps(_CREDS).encode("utf-8"))
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE accounts")
        conn.execute(
            "CREATE TABLE accounts (account_id TEXT PRIMARY KEY, broker TEXT NOT NULL, "
            "label TEXT NOT NULL, salt BLOB NOT NULL, encrypted_creds BLOB NOT NULL, "
            "is_primary INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO accounts VALUES (?,?,?,?,?,?,?)",
            ("AB1234", "zerodha", "Z", salt, enc, 0, "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
    # 2. re-open -> _init_db runs the additive backfill migration in place.
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
    store = CredentialStore(db, _MP)
    store.store("CD5678", "upstox", "U", _CREDS, adapter_id="upstox")
    # Simulate a row left blank by an interrupted backfill.
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE accounts SET adapter_id = '' WHERE account_id = ?", ("CD5678",))
        conn.commit()
    # Re-open -> the idempotent self-healing backfill runs even though the
    # column already exists.
    healed = CredentialStore(db, _MP)
    rows = {a["account_id"]: a for a in healed.list_accounts()}
    assert rows["CD5678"]["adapter_id"] == "upstox"
    assert healed.retrieve_for("upstox", "CD5678") == _CREDS


def test_set_primary_leaves_exactly_one_primary(tmp_path) -> None:
    """After :meth:`set_primary` exactly one row carries ``is_primary = 1``."""
    db = tmp_path / "primary.db"
    store = CredentialStore(db, _MP)
    store.store("a1", "dhan", "A1", _CREDS, adapter_id="dhan", is_primary=True)
    store.store("a2", "dhan", "A2", _CREDS, adapter_id="dhan")
    store.store("a3", "zerodha", "A3", _CREDS, adapter_id="zerodha")

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
