"""Exact Fernet credential authority with bounded pathname replacement checks.

Primary flags are a compatibility projection, not workspace execution authority.
Physical composite keying does not activate cross-adapter duplicate creation.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import sys
import threading
import unicodedata
import weakref
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from flinttrade_core.broker_account_cutover import BrokerAccountCutoverUnavailable, require_broker_account_mutations
from flinttrade_core.broker_identity import INT64_MAX, BrokerSelector, CredentialVersion, QuarantineRef
from flinttrade_core.broker_setup import BrokerSetupValidationError, normalise_broker_setup
from flinttrade_core.db import open_sqlite
from flinttrade_core.secure_file import (
    HeldOwnerDirectory,
    InsecureFilePermissionsError,
    validate_owner_owned_regular_file,
)


class CredentialError(Exception):
    """Stable exception identity, also re-exported by exceptions.py."""

    def __init__(self, message: str = "credential_operation_failed") -> None:
        self.message = message
        super().__init__(message)


class CredentialNotFoundError(CredentialError):
    def __init__(self) -> None:
        super().__init__("credential_not_found")


class CredentialAmbiguityError(CredentialError):
    def __init__(self) -> None:
        super().__init__("credential_selector_ambiguous")


class CredentialConflictError(CredentialError):
    def __init__(self) -> None:
        super().__init__("credential_conflict")


class CredentialStaleError(CredentialError):
    def __init__(self) -> None:
        super().__init__("credential_stale")


class CredentialValidationError(CredentialError):
    def __init__(self) -> None:
        super().__init__("credential_validation_failed")


class CredentialVaultInvalidError(CredentialError):
    def __init__(self) -> None:
        super().__init__("credential_vault_invalid")


class CredentialVaultHardeningRequiredError(CredentialError):
    def __init__(self) -> None:
        super().__init__("credential_vault_hardening_required")


@dataclass(frozen=True)
class CredentialSelectorState:
    version: CredentialVersion
    present: bool
    credential_present: bool
    setup_present: bool
    origin: str | None


@dataclass(frozen=True)
class CredentialAccount:
    selector: BrokerSelector
    broker: str
    label: str
    is_primary: bool
    created_at: str
    version: CredentialVersion


@dataclass(frozen=True)
class QuarantinedCredentialMetadata:
    """Detached recovery metadata; raw source cells never leave the vault owner."""

    ref: QuarantineRef
    reason: str
    provenance: str


class _OpaqueReceipt:
    def __reduce__(self) -> Any:
        raise TypeError("credential_receipt_not_serialisable")


@dataclass(frozen=True, eq=False)
class SelectorSnapshot(_OpaqueReceipt):
    selector: BrokerSelector
    version: CredentialVersion


@dataclass(frozen=True, eq=False)
class PrimaryProjectionSnapshot(_OpaqueReceipt):
    selector: BrokerSelector
    versions: tuple[CredentialVersion, ...]


@dataclass(frozen=True, eq=False)
class PrimaryProjectionMutation(_OpaqueReceipt):
    selector: BrokerSelector
    before_versions: tuple[CredentialVersion, ...]
    after_versions: tuple[CredentialVersion, ...]


_KDF_ITERATIONS = 390_000
_SALT_BYTES = 16
_FAMILY_LOCKS_GUARD = threading.Lock()
_FAMILY_LOCKS: weakref.WeakValueDictionary[str, threading.RLock] = weakref.WeakValueDictionary()
_ORIGINS = ("legacy_pre_workspace_authority", "legacy_interim_candidate", "legacy_interim_writer", "managed")
# Closed historical evidence: future catalogue additions do not enlarge migration inference.
_LEGACY_BROKERS = frozenset(
    """zerodha fyers flattrade arrow tradesmart hdfcsecurities hdfcsky pocketful
paytm dhan aliceblue upstox compositedge rmoney angel fivepaisa zebu shoonya firstock tradejini mstock
kotak kotakneo motilal nubra samco deltaexchange groww wisdom ibulls iifl iiflcapital jainamxts
indmoney fivepaisaxts definedge dhan_sandbox""".split()
)
CREDENTIAL_DB_SCHEMA_VERSION = 2
_CREATE_TABLE_SQL = """CREATE TABLE "accounts" (
    account_id TEXT NOT NULL, adapter_id TEXT NOT NULL,
    broker TEXT NOT NULL, label TEXT NOT NULL, salt BLOB NOT NULL,
    encrypted_creds BLOB NOT NULL, is_primary INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
    PRIMARY KEY(adapter_id, account_id)
)"""
_ACCOUNT_INDEX_SQL = "CREATE INDEX idx_accounts_account_id ON accounts(account_id)"
_AUTHORITY_SCHEMA = {
    "credential_vault_metadata": """CREATE TABLE credential_vault_metadata (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        schema_version INTEGER NOT NULL CHECK(typeof(schema_version)='integer' AND schema_version=2),
        vault_incarnation TEXT NOT NULL
    )""",
    "credential_selector_versions": """CREATE TABLE credential_selector_versions (
        adapter_id TEXT NOT NULL, account_id TEXT NOT NULL,
        generation INTEGER NOT NULL CHECK(typeof(generation)='integer' AND generation BETWEEN 1 AND 9223372036854775807),
        present INTEGER NOT NULL CHECK(typeof(present)='integer' AND present IN (0,1)),
        origin TEXT NOT NULL CHECK(origin IN ('legacy_pre_workspace_authority','legacy_interim_candidate',
                                             'legacy_interim_writer','managed')),
        PRIMARY KEY(adapter_id, account_id)
    )""",
    "broker_selector_setup": """CREATE TABLE broker_selector_setup (
        adapter_id TEXT NOT NULL, account_id TEXT NOT NULL,
        present INTEGER NOT NULL CHECK(typeof(present)='integer' AND present IN (0,1)),
        setup_json TEXT,
        CHECK((present=0 AND setup_json IS NULL) OR (present=1 AND typeof(setup_json)='text')),
        PRIMARY KEY(adapter_id, account_id)
    )""",
}
_AUTHORITY_SCHEMA_ONE = dict(_AUTHORITY_SCHEMA)
_AUTHORITY_SCHEMA_ONE["credential_vault_metadata"] = _AUTHORITY_SCHEMA["credential_vault_metadata"].replace(
    "schema_version=2", "schema_version=1"
)
_REASONS = (
    "legacy_identity_invalid",
    "legacy_role_unresolved",
    "legacy_identity_collision",
    "reserved_openalgo_default",
)
_QUARANTINE_SQL = """CREATE TABLE credential_quarantine (
    quarantine_id TEXT NOT NULL PRIMARY KEY,
    source_vault_incarnation TEXT NOT NULL,
    source_schema_version INTEGER NOT NULL
        CHECK(typeof(source_schema_version)='integer' AND source_schema_version IN (0,1)),
    source_table TEXT NOT NULL CHECK(source_table IN ('accounts','broker_selector_setup')),
    source_rowid INTEGER NOT NULL CHECK(typeof(source_rowid)='integer'),
    row_generation INTEGER NOT NULL
        CHECK(typeof(row_generation)='integer' AND row_generation BETWEEN 1 AND 9223372036854775807),
    reason TEXT NOT NULL CHECK(reason IN ('legacy_identity_invalid','legacy_role_unresolved',
        'legacy_identity_collision','reserved_openalgo_default')),
    provenance TEXT NOT NULL CHECK(provenance IN ('legacy_pre_workspace_authority','legacy_interim_candidate',
        'legacy_interim_writer','managed')),
    raw_record BLOB NOT NULL CHECK(typeof(raw_record)='blob'),
    UNIQUE(source_vault_incarnation,source_schema_version,source_table,source_rowid)
)"""
_AUTHORITY_SCHEMA["credential_quarantine"] = _QUARANTINE_SQL
_ACCOUNT_COLUMNS = (
    "account_id",
    "adapter_id",
    "broker",
    "label",
    "salt",
    "encrypted_creds",
    "is_primary",
    "created_at",
)
_SETUP_COLUMNS = ("adapter_id", "account_id", "present", "setup_json")
_VERSION_COLUMNS = ("adapter_id", "account_id", "generation", "present", "origin")


def _reset_family_locks_after_fork() -> None:
    """Discard process-local thread locks inherited by a forked child."""
    global _FAMILY_LOCKS_GUARD, _FAMILY_LOCKS

    _FAMILY_LOCKS_GUARD = threading.Lock()
    _FAMILY_LOCKS = weakref.WeakValueDictionary()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_family_locks_after_fork)


def _family_lock(path: Path) -> threading.RLock:
    """Return one process-local re-entrant lock for every accepted vault alias."""
    with _FAMILY_LOCKS_GUARD:
        absolute = os.path.abspath(os.fspath(path))
        canonical = os.path.realpath(absolute, strict=False)
        keys = tuple(
            dict.fromkeys(
                unicodedata.normalize("NFC", os.path.normcase(value)).casefold()
                for value in (absolute, canonical)
            )
        )
        locks = {lock for key in keys if (lock := _FAMILY_LOCKS.get(key)) is not None}
        if len(locks) > 1:
            # An active namespace change made two independently locked paths
            # converge. Refuse rather than pretend the live critical sections
            # have been merged.
            raise CredentialVaultInvalidError
        lock = next(iter(locks), None) or threading.RLock()
        for key in keys:
            _FAMILY_LOCKS[key] = lock
        return lock


def _legacy_identity(row: dict[str, Any]) -> tuple[str | None, str | None]:
    """Partition identity-only legacy defects without changing any source value."""
    adapter = row.get("adapter_id")
    if adapter == "openalgo" and row["account_id"] == "default":
        return None, "reserved_openalgo_default"
    try:
        BrokerSelector("legacy", row["account_id"])
        BrokerSelector(row["broker"], "identity")
        if adapter not in (None, ""):
            BrokerSelector(adapter, row["account_id"])
    except ValueError:
        return None, "legacy_identity_invalid"
    if adapter in (None, ""):
        if row["broker"] not in _LEGACY_BROKERS:
            return None, "legacy_role_unresolved"
        adapter = row["broker"]
    elif not (
        (adapter in _LEGACY_BROKERS and adapter == row["broker"])
        or (adapter == "openalgo" and row["broker"] in _LEGACY_BROKERS | {"openalgo"})
    ):
        return None, "legacy_role_unresolved"
    return adapter, None


def _encode_envelope(cells: list, version: list | None) -> bytes:
    return json.dumps([1, cells, version], separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def _raw_cells(conn: sqlite3.Connection, table: str, rowid: int) -> list:
    """Capture TEXT as bytes inside SQLite, keeping its distinct storage class."""
    columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    terms = [
        f"typeof(\"{name}\"), CASE WHEN typeof(\"{name}\") IN ('text','blob') "
        f'THEN CAST("{name}" AS BLOB) ELSE "{name}" END'
        for name in columns
    ]
    row = conn.execute(f"SELECT {','.join(terms)} FROM {table} WHERE rowid=?", (rowid,)).fetchone()
    if row is None:
        raise CredentialVaultInvalidError
    result = []
    for index, name in enumerate(columns):
        kind, value = row[index * 2], row[index * 2 + 1]
        if kind in {"text", "blob"}:
            value = base64.b64encode(value).decode("ascii")
        elif kind not in {"integer", "null"}:
            raise CredentialVaultInvalidError
        result.append([name, kind, value])
    return result


def _decode_cells(cells: object, allowed: tuple[str, ...], *, optional_adapter: bool = False) -> dict[str, Any]:
    if type(cells) is not list:
        raise ValueError
    decoded = {}
    for cell in cells:
        if type(cell) is not list or len(cell) != 3:
            raise ValueError
        name, kind, value = cell
        if type(name) is not str or name not in allowed or name in decoded:
            raise ValueError
        if kind in ("text", "blob"):
            if type(value) is not str:
                raise ValueError
            raw = base64.b64decode(value, validate=True)
            if base64.b64encode(raw).decode("ascii") != value:
                raise ValueError
            value = raw.decode("utf-8") if kind == "text" else raw
        elif kind == "integer":
            if type(value) is not int or not -(2**63) <= value <= INT64_MAX:
                raise ValueError
        elif kind != "null" or value is not None:
            raise ValueError
        decoded[name] = value
    expected = set(allowed)
    if set(decoded) != expected and not (optional_adapter and set(decoded) == expected - {"adapter_id"}):
        raise ValueError
    return decoded


def _selector(value: BrokerSelector, *, mutation: bool = False) -> BrokerSelector:
    try:
        if type(value) is not BrokerSelector:
            raise ValueError
        value.__post_init__()
    except ValueError:
        raise CredentialValidationError from None
    if mutation and value == BrokerSelector("openalgo", "default"):
        raise CredentialValidationError
    return value


def _pair(selector: BrokerSelector) -> tuple[str, str]:
    return selector.adapter_id, selector.account_id


def _copy_credential_payload(credentials: dict[str, Any]) -> dict[str, Any]:
    try:
        if type(credentials) is not dict:
            raise ValueError
        return json.loads(json.dumps(credentials, allow_nan=False))
    except (TypeError, ValueError, OverflowError):
        raise CredentialValidationError from None


def _metadata(selector: BrokerSelector, broker: str, label: str) -> None:
    try:
        BrokerSelector(broker, selector.account_id)
        if type(label) is not str or (selector.adapter_id != "openalgo" and broker != selector.adapter_id):
            raise ValueError
    except ValueError:
        raise CredentialValidationError from None


def _normalise_setup(selector: BrokerSelector, setup: dict[str, Any]) -> str:
    """Preserve the vault error boundary around shared non-invoking validation."""
    try:
        return normalise_broker_setup(selector, setup)
    except BrokerSetupValidationError:
        raise CredentialValidationError from None


class StagedCredentialStore:
    """Detached one-selector login overlay, committed only at captured CAS."""

    def __init__(
        self,
        store: CredentialStore,
        selector: BrokerSelector,
        credentials: dict[str, Any],
        metadata: dict[str, Any],
        replace_metadata: bool,
        expected: CredentialVersion,
    ) -> None:
        self._store, self._selector = store, selector
        self._credentials, self._metadata = _copy_credential_payload(credentials), dict(metadata)
        self._replace_metadata, self._active = replace_metadata, True
        self._expected_version = expected
        self._primary_snapshot: PrimaryProjectionSnapshot | None = None

    @property
    def expected_version(self) -> CredentialVersion:
        return self._expected_version

    def __repr__(self) -> str:
        return "<StagedCredentialStore pending>" if self._active else "<StagedCredentialStore closed>"

    def _ensure_active(self) -> None:
        if not self._active:
            raise CredentialStaleError

    def _ensure_selector(self, adapter_id: str, account_id: str) -> None:
        self._ensure_active()
        if BrokerSelector(adapter_id, account_id) != self._selector:
            raise CredentialNotFoundError

    def list_accounts(self) -> list[dict[str, Any]]:
        self._ensure_active()
        rows = [
            row
            for row in self._store.list_accounts()
            if (row["adapter_id"], row["account_id"]) != _pair(self._selector)
        ]
        return rows + [dict(self._metadata)]

    def retrieve_for(self, adapter_id: str, account_id: str) -> dict[str, Any]:
        self._ensure_selector(adapter_id, account_id)
        return _copy_credential_payload(self._credentials)

    def update_credentials_for(self, adapter_id: str, account_id: str, credentials: dict[str, Any]) -> None:
        self._ensure_selector(adapter_id, account_id)
        self._credentials = _copy_credential_payload(credentials)

    def commit(self) -> CredentialVersion:
        self._ensure_active()
        if self._primary_snapshot is not None:
            version = self._store._commit_legacy_stage(self)
        elif self._replace_metadata:
            version = self._store.put_credentials(
                self._selector,
                self._metadata["broker"],
                self._metadata["label"],
                self._credentials,
                expected=self.expected_version,
            )
        else:
            version = self._store.update_credentials(self._selector, self._credentials, expected=self.expected_version)
        self.discard()
        return version

    def discard(self) -> None:
        self._credentials.clear()
        self._active = False


class CredentialStore:
    """One owner-only vault incarnation; each operation owns and closes its connection."""

    def __init__(self, db_path: Path, master_password: str) -> None:
        self._db_path = Path(db_path).absolute()
        self._master_password = master_password.encode("utf-8")
        self._incarnation: UUID | None = None
        self._poisoned = False
        self._parent: HeldOwnerDirectory | None = None
        self._ancestor: HeldOwnerDirectory | None = None
        self._receipts: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
        with _family_lock(self._db_path):
            self._initialise()

    def _initialise(self) -> None:
        """Validate and initialise one vault while its process family lock is held."""
        try:
            parent = self._db_path.parent
            if not parent.exists():
                self._ancestor = HeldOwnerDirectory(parent.parent).__enter__()
                self._parent = self._ancestor.child(parent.name, create=True).__enter__()
            else:
                self._parent = HeldOwnerDirectory(parent, require_hardened=False).__enter__()
                # Classify topology/ownership before a hardening-only refusal.
                main_identity = None
                if self._parent.exists(self._db_path.name):
                    main_identity = validate_owner_owned_regular_file(self._db_path)
                for suffix in ("-wal", "-shm", "-journal"):
                    member = self._db_path.with_name(self._db_path.name + suffix)
                    self._validate_optional_member(member, main_identity, require_hardened=False)
                self._parent.require_hardened = True
                self._parent.revalidate()
            fresh = False
            if not self._parent.exists(self._db_path.name):
                if any(self._parent.exists(self._db_path.name + suffix) for suffix in ("-wal", "-shm", "-journal")):
                    raise CredentialVaultInvalidError
                try:
                    self._parent.create_empty_hardened_member(self._db_path.name)
                    fresh = True
                except FileExistsError:
                    pass
            self._identity = validate_owner_owned_regular_file(self._db_path, require_hardened=True)
            if not fresh and self._identity.st_size == 0:
                raise CredentialVaultInvalidError
            self._validate_family()
            self._init_db(fresh)
        except InsecureFilePermissionsError:
            self.close()
            raise CredentialVaultHardeningRequiredError from None
        except CredentialError:
            self.close()
            raise
        except Exception:
            self.close()
            raise CredentialVaultInvalidError from None

    def close(self) -> None:
        """Release held directory descriptors; this instance cannot be reused."""
        self._poisoned = True
        if self._parent is not None:
            self._parent.__exit__()
        if self._ancestor is not None:
            self._ancestor.__exit__()

    def __del__(self) -> None:
        self.close()

    def _validate_optional_member(
        self, path: Path, main_identity: os.stat_result | None, *, require_hardened: bool
    ) -> None:
        if not self._parent.exists(path.name):
            return
        try:
            validate_owner_owned_regular_file(path, require_hardened=require_hardened)
        except FileNotFoundError:
            # SQLite's last close can remove WAL/SHM after the existence check.
            self._parent.revalidate()
            if main_identity is None:
                raise
            current = validate_owner_owned_regular_file(self._db_path, require_hardened=require_hardened)
            if ((current.st_dev, current.st_ino) != (main_identity.st_dev, main_identity.st_ino)
                    or self._parent.exists(path.name)):
                raise

    def _validate_family(self) -> None:
        if self._poisoned:
            raise CredentialStaleError
        try:
            self._parent.revalidate()
            current = validate_owner_owned_regular_file(self._db_path, require_hardened=True)
            if (current.st_dev, current.st_ino) != (self._identity.st_dev, self._identity.st_ino):
                raise OSError
            for suffix in ("-wal", "-shm", "-journal"):
                path = self._db_path.with_name(self._db_path.name + suffix)
                self._validate_optional_member(path, self._identity, require_hardened=True)
        except Exception:
            if self._incarnation is not None:
                self._poisoned = True
                raise CredentialStaleError from None
            raise

    def _get_connection(self) -> sqlite3.Connection:
        self._validate_family()
        conn = None
        try:
            conn = open_sqlite(self._db_path, durability="full", strict_existing=True)
            conn.row_factory = sqlite3.Row
            self._validate_family()
            if (
                conn.execute("PRAGMA journal_mode").fetchone()[0] != "wal"
                or conn.execute("PRAGMA synchronous").fetchone()[0] != 2
            ):
                raise CredentialVaultInvalidError
            return conn
        except Exception as exc:
            try:
                if conn is not None:
                    conn.close()
            finally:
                # A real mode=rw open can fail after the pre-open observation.
                # Observe this boundary too: restoring A later must not revive
                # a store that saw A disappear or change while opening it.
                self._validate_family()
            if self._incarnation is not None and getattr(exc, "sqlite_errorcode", None) in (
                sqlite3.SQLITE_CORRUPT,
                sqlite3.SQLITE_NOTADB,
            ):
                self._poisoned = True
                raise CredentialStaleError from None
            raise

    @staticmethod
    def _binary_indices(conn: sqlite3.Connection, table: str) -> bool:
        return all(
            term[4] == "BINARY"
            for index in conn.execute("SELECT name FROM pragma_index_list(?)", (table,))
            for term in conn.execute("SELECT * FROM pragma_index_xinfo(?)", (index[0],))
            if term[5]
        )

    @staticmethod
    def _accounts_schema(conn: sqlite3.Connection, *, legacy: bool = False, version: int = 2) -> bool:
        ddl = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='accounts'").fetchone()
        # Historical and current producers use implicit BINARY columns only.
        # Refuse any COLLATE declaration (including commented/quoted syntax),
        # rather than trying to parse and inherit unrecognised SQL equality.
        if ddl is None or re.search(r"\bcollate\b|\bwithout\s+rowid\b", ddl[0], re.IGNORECASE):
            return False
        if not CredentialStore._binary_indices(conn, "accounts"):
            return False
        if not legacy and version == 2:
            return ddl[0] == _CREATE_TABLE_SQL
        # table_info omits generated/hidden columns; these are unsupported source
        # shapes, not cells we may discard while quarantining excluded rows.
        columns = {row[1]: row for row in conn.execute("PRAGMA table_xinfo(accounts)")}
        if any(row[6] != 0 for row in columns.values()):
            return False
        expected = {
            "account_id": "TEXT",
            "broker": "TEXT",
            "label": "TEXT",
            "salt": "BLOB",
            "encrypted_creds": "BLOB",
            "is_primary": "INTEGER",
            "created_at": "TEXT",
        }
        if set(columns) not in (set(expected), set(expected) | {"adapter_id"}):
            return False
        if not legacy and "adapter_id" not in columns:
            return False
        if "adapter_id" in columns and columns["adapter_id"][2].upper() != "TEXT":
            return False
        if any(columns[key][5] for key in columns if key != "account_id"):
            return False
        if columns["account_id"][5] != 1 or any(columns[key][2].upper() != kind for key, kind in expected.items()):
            return False
        return all(columns[key][3] == 1 for key in expected if key != "account_id")

    def _init_db(self, fresh: bool) -> None:
        conn = self._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise CredentialVaultInvalidError
            self._reject_authority_triggers(conn)
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            marker = conn.execute("PRAGMA user_version").fetchone()[0]
            legacy = not fresh and marker == 0 and tables == {"accounts"}
            if fresh:
                if tables or marker:
                    raise CredentialVaultInvalidError
                conn.execute(_CREATE_TABLE_SQL)
                for sql in _AUTHORITY_SCHEMA.values():
                    conn.execute(sql)
                conn.execute("INSERT INTO credential_vault_metadata VALUES(1,2,?)", (str(uuid4()),))
                conn.execute(_ACCOUNT_INDEX_SQL)
                conn.execute("PRAGMA user_version=2")
            elif legacy or marker == 1:
                self._migrate_composite(conn, marker)
            elif marker != CREDENTIAL_DB_SCHEMA_VERSION:
                raise CredentialVaultInvalidError
            incarnation = self._validate_authority(conn)
            self._validate_family()
            conn.commit()
            self._validate_family()
            self._incarnation = incarnation
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise CredentialVaultInvalidError from None
        finally:
            conn.close()

    def _migrate_composite(self, conn: sqlite3.Connection, marker: int) -> None:
        """One disjoint physical-row partition, verified before the owned swap."""
        if marker == 0:
            if not self._accounts_schema(conn, legacy=True):
                raise CredentialVaultInvalidError
            incarnation = uuid4()
        else:
            incarnation = self._validate_authority(conn, version=1, reserved_source=True)
            reserved_version = conn.execute(
                "SELECT generation,present FROM credential_selector_versions WHERE adapter_id='openalgo' AND account_id='default'"
            ).fetchone()
            if reserved_version is not None and reserved_version[1] and reserved_version[0] == INT64_MAX:
                raise CredentialVaultInvalidError
        rows = [
            (row["rowid"], {key: row[key] for key in row.keys() if key != "rowid"})
            for row in conn.execute("SELECT rowid,* FROM accounts")
        ]
        captured = {rowid: _raw_cells(conn, "accounts", rowid) for rowid, _ in rows}
        decisions = {}
        selectors: dict[tuple[str, str], list[int]] = {}
        for rowid, row in rows:
            self._validate_account_storage(row)
            adapter, reason = (
                _legacy_identity(row)
                if marker == 0
                else (
                    (None, "reserved_openalgo_default")
                    if (row["adapter_id"], row["account_id"]) == ("openalgo", "default")
                    else (row["adapter_id"], None)
                )
            )
            decisions[rowid] = (adapter, reason)
            if reason is None:
                selectors.setdefault((adapter, row["account_id"]), []).append(rowid)
        for participants in selectors.values():
            if len(participants) > 1:
                for rowid in participants:
                    decisions[rowid] = (None, "legacy_identity_collision")
        if marker == 0:
            for sql in _AUTHORITY_SCHEMA.values():
                conn.execute(sql)
            conn.execute("INSERT INTO credential_vault_metadata VALUES(1,2,?)", (str(incarnation),))
        else:
            conn.execute(_QUARANTINE_SQL)
        conn.execute(_CREATE_TABLE_SQL.replace('"accounts"', "accounts_v2", 1))
        valid, excluded = set(), set()
        for rowid, row in rows:
            adapter, reason = decisions[rowid]
            if reason is not None:
                self._quarantine_source(conn, incarnation, marker, "accounts", rowid, captured[rowid], reason, row)
                excluded.add(rowid)
                continue
            migrated = dict(row, adapter_id=adapter)
            self._validate_account_row(migrated, adapter)
            conn.execute(
                f"INSERT INTO accounts_v2({','.join(_ACCOUNT_COLUMNS)}) VALUES(?,?,?,?,?,?,?,?)",
                tuple(migrated[name] for name in _ACCOUNT_COLUMNS),
            )
            copied = conn.execute(
                "SELECT * FROM accounts_v2 WHERE adapter_id=? AND account_id=?", (adapter, row["account_id"])
            ).fetchone()
            if dict(copied) != migrated or any(type(copied[key]) is not type(value) for key, value in migrated.items()):
                raise CredentialVaultInvalidError
            # Also compare SQL storage classes and exact bytes; the sole allowed
            # difference is the explicit legacy missing-adapter backfill.
            target_rowid = conn.execute(
                "SELECT rowid FROM accounts_v2 WHERE adapter_id=? AND account_id=?", (adapter, row["account_id"])
            ).fetchone()[0]
            expected_cells = {cell[0]: cell[1:] for cell in captured[rowid]}
            expected_cells["adapter_id"] = ["text", base64.b64encode(adapter.encode("ascii")).decode("ascii")]
            if {cell[0]: cell[1:] for cell in _raw_cells(conn, "accounts_v2", target_rowid)} != expected_cells:
                raise CredentialVaultInvalidError
            if marker == 0:
                conn.execute(
                    "INSERT INTO credential_selector_versions VALUES(?,?,1,1,?)",
                    (adapter, row["account_id"], _ORIGINS[0]),
                )
            valid.add(rowid)
        if valid & excluded or valid | excluded != set(captured):
            raise CredentialVaultInvalidError
        if conn.execute("SELECT count(*) FROM accounts_v2").fetchone()[0] != len(valid):
            raise CredentialVaultInvalidError
        setup_count = 0
        if marker == 1:
            reserved = conn.execute(
                "SELECT rowid,* FROM broker_selector_setup WHERE adapter_id='openalgo' AND account_id='default'"
            ).fetchone()
            if reserved is not None and reserved["present"]:
                self._quarantine_source(
                    conn,
                    incarnation,
                    marker,
                    "broker_selector_setup",
                    reserved["rowid"],
                    _raw_cells(conn, "broker_selector_setup", reserved["rowid"]),
                    "reserved_openalgo_default",
                    dict(reserved),
                )
                setup_count = 1
            if excluded or setup_count:
                version = conn.execute(
                    "SELECT generation FROM credential_selector_versions WHERE adapter_id='openalgo' AND account_id='default'"
                ).fetchone()
                if version is None or version[0] == INT64_MAX:
                    raise CredentialVaultInvalidError
                conn.execute(
                    "UPDATE credential_selector_versions SET generation=generation+1,present=0 WHERE adapter_id='openalgo' AND account_id='default'"
                )
                if reserved is not None:
                    conn.execute(
                        "UPDATE broker_selector_setup SET present=0,setup_json=NULL WHERE adapter_id='openalgo' AND account_id='default'"
                    )
            conn.execute("DROP TABLE credential_vault_metadata")
            conn.execute(_AUTHORITY_SCHEMA["credential_vault_metadata"])
            conn.execute("INSERT INTO credential_vault_metadata VALUES(1,2,?)", (str(incarnation),))
        if conn.execute("SELECT count(*) FROM credential_quarantine").fetchone()[0] != len(excluded) + setup_count:
            raise CredentialVaultInvalidError
        self._validate_quarantine(conn, incarnation)
        conn.execute("DROP TABLE accounts")
        conn.execute("ALTER TABLE accounts_v2 RENAME TO accounts")
        conn.execute(_ACCOUNT_INDEX_SQL)
        conn.execute("PRAGMA user_version=2")

    def _quarantine_source(
        self,
        conn: sqlite3.Connection,
        incarnation: UUID,
        marker: int,
        table: str,
        rowid: int,
        cells: list,
        reason: str,
        row: dict[str, Any],
    ) -> None:
        snapshot, origin = None, _ORIGINS[0]
        if marker == 1:
            version = conn.execute(
                "SELECT rowid,origin FROM credential_selector_versions WHERE adapter_id=? AND account_id=?",
                (row["adapter_id"], row["account_id"]),
            ).fetchone()
            if version is None:
                raise CredentialVaultInvalidError
            snapshot = _raw_cells(conn, "credential_selector_versions", version[0])
            origin = version[1]
        raw = _encode_envelope(cells, snapshot)
        quarantine_id = str(uuid4())
        conn.execute(
            "INSERT INTO credential_quarantine VALUES(?,?,?,?,?,1,?,?,?)",
            (quarantine_id, str(incarnation), marker, table, rowid, reason, origin, raw),
        )
        if (
            conn.execute(
                "SELECT raw_record FROM credential_quarantine WHERE quarantine_id=?", (quarantine_id,)
            ).fetchone()[0]
            != raw
        ):
            raise CredentialVaultInvalidError

    @staticmethod
    def _validate_account_storage(row: dict[str, Any]) -> None:
        if (
            type(row["label"]) is not str
            or type(row["is_primary"]) is not int
            or row["is_primary"] not in (0, 1)
            or type(row["salt"]) is not bytes
            or len(row["salt"]) != _SALT_BYTES
            or type(row["encrypted_creds"]) is not bytes
            or not row["encrypted_creds"]
            or type(row["created_at"]) is not str
        ):
            raise CredentialVaultInvalidError

    @staticmethod
    def _validate_account_row(row: dict[str, Any], adapter: str, *, reserved_source: bool = False) -> None:
        selector = _selector(BrokerSelector(adapter, row["account_id"]), mutation=not reserved_source)
        _metadata(selector, row["broker"], row["label"])
        CredentialStore._validate_account_storage(row)

    @staticmethod
    def _reject_authority_triggers(conn: sqlite3.Connection) -> None:
        tables = ("accounts", *_AUTHORITY_SCHEMA)
        for schema in ("sqlite_master", "sqlite_temp_master"):
            if conn.execute(
                f"SELECT 1 FROM {schema} WHERE type='trigger' AND lower(tbl_name) IN ({','.join('?' for _ in tables)}) LIMIT 1",
                tables,
            ).fetchone():
                raise CredentialVaultInvalidError

    def _validate_authority(self, conn: sqlite3.Connection, *, version: int = 2, reserved_source: bool = False) -> UUID:
        try:
            self._reject_authority_triggers(conn)
            schema = _AUTHORITY_SCHEMA_ONE if version == 1 else _AUTHORITY_SCHEMA
            if {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")} != {
                "accounts",
                *schema,
            }:
                raise ValueError
            if conn.execute("PRAGMA user_version").fetchone()[0] != version or not self._accounts_schema(
                conn, version=version
            ):
                raise ValueError
            indices = {row[1]: row for row in conn.execute("PRAGMA index_list(accounts)")}
            index_name = "idx_accounts_adapter_account" if version == 1 else "idx_accounts_account_id"
            index = indices.get(index_name)
            if (
                index is None
                or index[2] != (1 if version == 1 else 0)
                or index[4] != 0
                or [row[2] for row in conn.execute(f"PRAGMA index_info({index_name})")]
                != (["adapter_id", "account_id"] if version == 1 else ["account_id"])
                or (version == 2 and set(indices) != {"sqlite_autoindex_accounts_1", index_name})
            ):
                raise ValueError
            for name, sql in schema.items():
                row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
                # These tables have exactly one producer. Compare its DDL
                # verbatim: folding case/whitespace inside CHECK literals can
                # turn a changed constraint into an apparently valid schema.
                if row is None or row[0] != sql or not self._binary_indices(conn, name):
                    raise ValueError
            metadata = conn.execute("SELECT * FROM credential_vault_metadata").fetchall()
            if len(metadata) != 1 or metadata[0]["singleton"] != 1 or metadata[0]["schema_version"] != version:
                raise ValueError
            raw = metadata[0]["vault_incarnation"]
            incarnation = UUID(raw)
            CredentialVersion(BrokerSelector("vault", "identity"), incarnation, 0)
            if str(incarnation) != raw or (self._incarnation is not None and incarnation != self._incarnation):
                raise ValueError
            versions = {}
            for row in conn.execute("SELECT * FROM credential_selector_versions"):
                selector = _selector(BrokerSelector(row["adapter_id"], row["account_id"]))
                if (
                    type(row["generation"]) is not int
                    or not 1 <= row["generation"] <= INT64_MAX
                    or type(row["present"]) is not int
                    or row["present"] not in (0, 1)
                    or row["origin"] not in _ORIGINS
                ):
                    raise ValueError
                if selector == BrokerSelector("openalgo", "default") and not reserved_source and row["present"]:
                    raise ValueError
                versions[selector] = row["present"]
            accounts = set()
            for row in conn.execute("SELECT * FROM accounts"):
                self._validate_account_row(dict(row), row["adapter_id"], reserved_source=reserved_source)
                accounts.add(BrokerSelector(row["adapter_id"], row["account_id"]))
            setups = set()
            for row in conn.execute("SELECT * FROM broker_selector_setup"):
                selector = _selector(
                    BrokerSelector(row["adapter_id"], row["account_id"]),
                    mutation=bool(row["present"]) and not reserved_source,
                )
                if selector not in versions or type(row["present"]) is not int or row["present"] not in (0, 1):
                    raise ValueError
                if row["present"]:
                    if (
                        type(row["setup_json"]) is not str
                        or _normalise_setup(selector, json.loads(row["setup_json"])) != row["setup_json"]
                    ):
                        raise ValueError
                    setups.add(selector)
                elif row["setup_json"] is not None:
                    raise ValueError
            if not accounts.issubset(versions) or any(
                bool(present) != (key in accounts or key in setups) for key, present in versions.items()
            ):
                raise ValueError
            if version == 2:
                self._validate_quarantine(conn, incarnation)
            return incarnation
        except Exception:
            if self._incarnation is not None:
                self._poisoned = True
                raise CredentialStaleError from None
            raise CredentialVaultInvalidError from None

    def _validate_quarantine(self, conn: sqlite3.Connection, incarnation: UUID) -> None:
        for row in conn.execute("SELECT * FROM credential_quarantine"):
            reference = QuarantineRef(
                UUID(row["quarantine_id"]), UUID(row["source_vault_incarnation"]), row["row_generation"]
            )
            if (
                str(reference.quarantine_id) != row["quarantine_id"]
                or str(reference.source_vault_incarnation) != row["source_vault_incarnation"]
                or reference.source_vault_incarnation != incarnation
                or type(row["source_schema_version"]) is not int
                or row["source_schema_version"] not in (0, 1)
                or type(row["source_rowid"]) is not int
                or not -(2**63) <= row["source_rowid"] <= INT64_MAX
                or row["source_table"] not in ("accounts", "broker_selector_setup")
                or row["reason"] not in _REASONS
                or row["provenance"] not in _ORIGINS
                or type(row["raw_record"]) is not bytes
            ):
                raise ValueError
            envelope = json.loads(row["raw_record"])
            if type(envelope) is not list or len(envelope) != 3 or type(envelope[0]) is not int or envelope[0] != 1:
                raise ValueError
            _, cells, snapshot = envelope
            if _encode_envelope(cells, snapshot) != row["raw_record"]:
                raise ValueError
            is_account = row["source_table"] == "accounts"
            decoded = _decode_cells(
                cells,
                _ACCOUNT_COLUMNS if is_account else _SETUP_COLUMNS,
                optional_adapter=row["source_schema_version"] == 0,
            )
            if is_account:
                self._validate_account_storage(decoded)
            if row["source_schema_version"] == 0:
                if not is_account or snapshot is not None or row["provenance"] != _ORIGINS[0]:
                    raise ValueError
                _, reason = _legacy_identity(decoded)
                if reason != row["reason"] and not (reason is None and row["reason"] == "legacy_identity_collision"):
                    raise ValueError
            else:
                original = _decode_cells(snapshot, _VERSION_COLUMNS)
                if (
                    decoded["adapter_id"] != "openalgo"
                    or decoded["account_id"] != "default"
                    or original["adapter_id"] != "openalgo"
                    or original["account_id"] != "default"
                    or type(original["generation"]) is not int
                    or not 1 <= original["generation"] < INT64_MAX
                    or type(original["present"]) is not int
                    or original["present"] != 1
                    or original["origin"] != row["provenance"]
                    or row["reason"] != "reserved_openalgo_default"
                ):
                    raise ValueError
                tombstone = conn.execute(
                    "SELECT generation,present,origin FROM credential_selector_versions WHERE adapter_id='openalgo' AND account_id='default'"
                ).fetchone()
                if (
                    tombstone is None
                    or tombstone[0] != original["generation"] + 1
                    or tombstone[1] != 0
                    or tombstone[2] != original["origin"]
                ):
                    raise ValueError
                if is_account:
                    self._validate_account_row(decoded, "openalgo", reserved_source=True)
                elif (
                    type(decoded["present"]) is not int
                    or decoded["present"] != 1
                    or type(decoded["setup_json"]) is not str
                    or _normalise_setup(BrokerSelector("openalgo", "default"), json.loads(decoded["setup_json"]))
                    != decoded["setup_json"]
                ):
                    raise ValueError

    def list_quarantine(self) -> tuple[QuarantinedCredentialMetadata, ...]:
        """List detached, UUID-sorted recovery references from a validated snapshot."""
        with self._transaction() as conn:
            return tuple(
                QuarantinedCredentialMetadata(
                    QuarantineRef(
                        UUID(row["quarantine_id"]), UUID(row["source_vault_incarnation"]), row["row_generation"]
                    ),
                    row["reason"],
                    row["provenance"],
                )
                for row in conn.execute(
                    "SELECT quarantine_id,source_vault_incarnation,row_generation,reason,provenance FROM credential_quarantine ORDER BY quarantine_id"
                )
            )

    @contextmanager
    def _transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        with _family_lock(self._db_path):
            with self._transaction_locked(write=write) as conn:
                yield conn

    @contextmanager
    def _transaction_locked(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        conn = None
        try:
            conn = self._get_connection()
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            self._validate_authority(conn)
            yield conn
            self._validate_family()
            self._validate_authority(conn)
            conn.commit()
            # A failure here can be applied. Never resample a version or auto-retry.
            self._validate_family()
            conn.execute("BEGIN")
            self._validate_authority(conn)
            conn.rollback()
            self._validate_family()
        except (CredentialError, BrokerAccountCutoverUnavailable):
            raise
        except Exception:
            raise CredentialError from None
        finally:
            if conn is not None:
                pending_error = sys.exception()
                cleanup_failed = False
                try:
                    if conn.in_transaction:
                        conn.rollback()
                except Exception:
                    cleanup_failed = True
                finally:
                    try:
                        conn.close()
                    except Exception:
                        cleanup_failed = True
                if cleanup_failed and pending_error is None:
                    raise CredentialError from None

    def _derive_key(self, salt: bytes) -> Fernet:
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=_KDF_ITERATIONS)
        return Fernet(base64.urlsafe_b64encode(kdf.derive(self._master_password)))

    def _encrypt(self, credentials: dict[str, Any]) -> tuple[bytes, bytes]:
        payload = _copy_credential_payload(credentials)
        salt = os.urandom(_SALT_BYTES)
        return salt, self._derive_key(salt).encrypt(json.dumps(payload).encode("utf-8"))

    def _decrypt(self, row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            raise CredentialNotFoundError
        return _copy_credential_payload(json.loads(self._derive_key(row["salt"]).decrypt(row["encrypted_creds"])))

    @staticmethod
    def _row(conn: sqlite3.Connection, selector: BrokerSelector) -> sqlite3.Row | None:
        return conn.execute("SELECT * FROM accounts WHERE adapter_id=? AND account_id=?", _pair(selector)).fetchone()

    def _state(self, conn: sqlite3.Connection, selector: BrokerSelector) -> CredentialSelectorState:
        row = conn.execute(
            "SELECT * FROM credential_selector_versions WHERE adapter_id=? AND account_id=?", _pair(selector)
        ).fetchone()
        setup = conn.execute(
            "SELECT present FROM broker_selector_setup WHERE adapter_id=? AND account_id=?", _pair(selector)
        ).fetchone()
        return CredentialSelectorState(
            CredentialVersion(selector, self._incarnation, row["generation"] if row else 0),
            bool(row and row["present"]),
            self._row(conn, selector) is not None,
            bool(setup and setup[0]),
            row["origin"] if row else None,
        )

    def _available(self, conn: sqlite3.Connection, selector: BrokerSelector) -> None:
        if self._state(conn, selector).origin == "legacy_interim_candidate":
            raise CredentialConflictError

    def _expected(self, conn: sqlite3.Connection, selector: BrokerSelector, expected: CredentialVersion) -> None:
        try:
            if type(expected) is not CredentialVersion:
                raise ValueError
            expected.__post_init__()
        except ValueError:
            raise CredentialValidationError from None
        if expected != self._state(conn, selector).version:
            raise CredentialStaleError
        self._available(conn, selector)

    def _check_bump(self, conn: sqlite3.Connection, selector: BrokerSelector) -> None:
        if self._state(conn, selector).version.generation == INT64_MAX:
            raise CredentialConflictError

    def _bump(self, conn: sqlite3.Connection, selector: BrokerSelector) -> CredentialVersion:
        self._check_bump(conn, selector)
        current = self._state(conn, selector)
        generation = current.version.generation + 1
        conn.execute(
            """INSERT INTO credential_selector_versions VALUES(?,?,?,?,?)
                        ON CONFLICT(adapter_id,account_id) DO UPDATE SET
                        generation=excluded.generation,present=excluded.present""",
            (
                *_pair(selector),
                generation,
                int(current.credential_present or current.setup_present),
                current.origin or "managed",
            ),
        )
        return CredentialVersion(selector, self._incarnation, generation)

    def selector_state(self, selector: BrokerSelector) -> CredentialSelectorState:
        _selector(selector)
        with self._transaction() as conn:
            return self._state(conn, selector)

    def account_for_selector(self, selector: BrokerSelector) -> CredentialAccount | None:
        _selector(selector)
        with self._transaction() as conn:
            state = self._state(conn, selector)
            if state.origin == "legacy_interim_candidate":
                return None
            row = self._row(conn, selector)
            return (
                None
                if row is None
                else CredentialAccount(
                    selector, row["broker"], row["label"], bool(row["is_primary"]), row["created_at"], state.version
                )
            )

    def retrieve_credentials(self, selector: BrokerSelector) -> dict[str, Any]:
        _selector(selector)
        with self._transaction() as conn:
            if self._state(conn, selector).origin == "legacy_interim_candidate":
                raise CredentialNotFoundError
            return self._decrypt(self._row(conn, selector))

    def retrieve_setup(self, selector: BrokerSelector) -> dict[str, Any]:
        _selector(selector)
        with self._transaction() as conn:
            if self._state(conn, selector).origin == "legacy_interim_candidate":
                raise CredentialNotFoundError
            row = conn.execute(
                "SELECT setup_json FROM broker_selector_setup WHERE adapter_id=? AND account_id=? AND present=1",
                _pair(selector),
            ).fetchone()
            if row is None:
                raise CredentialNotFoundError
            return json.loads(row[0])

    def _put(
        self, conn: sqlite3.Connection, selector: BrokerSelector, broker: str, label: str, credentials: dict[str, Any]
    ) -> None:
        _metadata(selector, broker, label)
        if self._row(conn, selector) is None:
            self._admit_new_component(conn, selector)
        salt, encrypted = self._encrypt(credentials)
        conn.execute(
            """INSERT INTO accounts(account_id,adapter_id,broker,label,salt,encrypted_creds,is_primary,created_at)
                        VALUES(?,?,?,?,?,?,0,?) ON CONFLICT(adapter_id,account_id) DO UPDATE SET
                        broker=excluded.broker,label=excluded.label,salt=excluded.salt,encrypted_creds=excluded.encrypted_creds""",
            (selector.account_id, selector.adapter_id, broker, label, salt, encrypted, datetime.now(UTC).isoformat()),
        )

    @staticmethod
    def _admit_new_component(conn: sqlite3.Connection, selector: BrokerSelector) -> None:
        """Temporary duplicate refusal covers the union of credentials and setup."""
        if conn.execute(
            "SELECT 1 FROM credential_selector_versions WHERE account_id=? AND adapter_id!=? AND present=1 LIMIT 1",
            (selector.account_id, selector.adapter_id),
        ).fetchone():
            raise CredentialConflictError

    def put_credentials(
        self,
        selector: BrokerSelector,
        broker: str,
        label: str,
        credentials: dict[str, Any],
        *,
        expected: CredentialVersion,
    ) -> CredentialVersion:
        _selector(selector, mutation=True)
        with self._transaction(write=True) as conn:
            self._expected(conn, selector, expected)
            self._check_bump(conn, selector)
            self._put(conn, selector, broker, label, credentials)
            return self._bump(conn, selector)

    def update_credentials(
        self, selector: BrokerSelector, credentials: dict[str, Any], *, expected: CredentialVersion
    ) -> CredentialVersion:
        _selector(selector, mutation=True)
        with self._transaction(write=True) as conn:
            self._expected(conn, selector, expected)
            row = self._row(conn, selector)
            if row is None:
                raise CredentialNotFoundError
            self._check_bump(conn, selector)
            self._put(conn, selector, row["broker"], row["label"], credentials)
            return self._bump(conn, selector)

    def put_setup(
        self, selector: BrokerSelector, setup: dict[str, Any], *, expected: CredentialVersion
    ) -> CredentialVersion:
        _selector(selector, mutation=True)
        with self._transaction(write=True) as conn:
            self._expected(conn, selector, expected)
            self._check_bump(conn, selector)
            encoded = _normalise_setup(selector, setup)
            if not self._state(conn, selector).setup_present:
                self._admit_new_component(conn, selector)
            conn.execute(
                """INSERT INTO broker_selector_setup VALUES(?,?,1,?)
                            ON CONFLICT(adapter_id,account_id) DO UPDATE SET present=1,setup_json=excluded.setup_json""",
                (*_pair(selector), encoded),
            )
            return self._bump(conn, selector)

    def _remove(
        self, conn: sqlite3.Connection, selector: BrokerSelector, *, credentials: bool, setup: bool
    ) -> CredentialVersion:
        self._check_bump(conn, selector)
        if credentials:
            conn.execute("DELETE FROM accounts WHERE adapter_id=? AND account_id=?", _pair(selector))
        if setup:
            conn.execute(
                """INSERT INTO broker_selector_setup VALUES(?,?,0,NULL)
                            ON CONFLICT(adapter_id,account_id) DO UPDATE SET present=0,setup_json=NULL""",
                _pair(selector),
            )
        return self._bump(conn, selector)

    def remove_credentials(self, selector: BrokerSelector, *, expected: CredentialVersion) -> CredentialVersion:
        _selector(selector, mutation=True)
        with self._transaction(write=True) as conn:
            self._expected(conn, selector, expected)
            return self._remove(conn, selector, credentials=True, setup=False)

    def remove_setup(self, selector: BrokerSelector, *, expected: CredentialVersion) -> CredentialVersion:
        _selector(selector, mutation=True)
        with self._transaction(write=True) as conn:
            self._expected(conn, selector, expected)
            return self._remove(conn, selector, credentials=False, setup=True)

    def remove_selector(self, selector: BrokerSelector, *, expected: CredentialVersion) -> CredentialVersion:
        _selector(selector, mutation=True)
        with self._transaction(write=True) as conn:
            self._expected(conn, selector, expected)
            return self._remove(conn, selector, credentials=True, setup=True)

    def stage_credentials(
        self,
        selector: BrokerSelector,
        credentials: dict[str, Any] | None = None,
        *,
        broker: str | None = None,
        label: str | None = None,
    ) -> StagedCredentialStore:
        _selector(selector, mutation=True)
        with self._transaction() as conn:
            self._available(conn, selector)
            row = self._row(conn, selector)
            if (broker is None) != (label is None):
                raise CredentialValidationError
            if row is None and (broker is None or credentials is None):
                raise CredentialNotFoundError
            if broker is not None:
                _metadata(selector, broker, label)
            if row is None:
                self._admit_new_component(conn, selector)
            metadata = {
                "adapter_id": selector.adapter_id,
                "account_id": selector.account_id,
                "broker": broker if broker is not None else row["broker"],
                "label": label if label is not None else row["label"],
                "is_primary": bool(row and row["is_primary"]),
                "created_at": row["created_at"] if row else None,
            }
            return StagedCredentialStore(
                self,
                selector,
                self._decrypt(row) if credentials is None else credentials,
                metadata,
                broker is not None,
                self._state(conn, selector).version,
            )

    def _primary(self, conn: sqlite3.Connection) -> dict[BrokerSelector, CredentialVersion]:
        result = {}
        for row in conn.execute("SELECT adapter_id,account_id FROM accounts WHERE is_primary=1"):
            selector = BrokerSelector(row[0], row[1])
            self._available(conn, selector)
            result[selector] = self._state(conn, selector).version
        return result

    def _receipt(self, receipt: object, kind: type) -> Any:
        if type(receipt) is not kind or receipt not in self._receipts:
            raise CredentialStaleError
        return self._receipts[receipt]

    def snapshot_selector(self, selector: BrokerSelector) -> SelectorSnapshot:
        _selector(selector)
        with self._transaction() as conn:
            self._available(conn, selector)
            receipt = SelectorSnapshot(selector, self._state(conn, selector).version)
            row = self._row(conn, selector)
            setup = conn.execute(
                "SELECT present,setup_json FROM broker_selector_setup WHERE adapter_id=? AND account_id=?",
                _pair(selector),
            ).fetchone()
            self._receipts[receipt] = (
                dict(row) if row else None,
                tuple(setup) if setup else (0, None),
                self._primary(conn),
            )
            return receipt

    def restore_selector(self, snapshot: SelectorSnapshot, *, expected: CredentialVersion) -> CredentialVersion:
        row, setup, primary = self._receipt(snapshot, SelectorSnapshot)
        selector = _selector(snapshot.selector, mutation=True)
        with self._transaction(write=True) as conn:
            self._expected(conn, selector, expected)
            self._check_bump(conn, selector)
            current = self._row(conn, selector)
            if (row is not None and current is None) or (setup[0] and not self._state(conn, selector).setup_present):
                self._admit_new_component(conn, selector)
            if bool(current and current["is_primary"]) != bool(row and row["is_primary"]):
                other_current = {key: value for key, value in self._primary(conn).items() if key != selector}
                other_prior = {key: value for key, value in primary.items() if key != selector}
                if other_current != other_prior:
                    raise CredentialStaleError
            if row:
                conn.execute("DELETE FROM accounts WHERE adapter_id=? AND account_id=?", _pair(selector))
                conn.execute(
                    """INSERT INTO accounts(account_id,adapter_id,broker,label,salt,encrypted_creds,is_primary,created_at)
                                VALUES(?,?,?,?,?,?,?,?)""",
                    tuple(
                        row[key]
                        for key in (
                            "account_id",
                            "adapter_id",
                            "broker",
                            "label",
                            "salt",
                            "encrypted_creds",
                            "is_primary",
                            "created_at",
                        )
                    ),
                )
            else:
                conn.execute("DELETE FROM accounts WHERE adapter_id=? AND account_id=?", _pair(selector))
            conn.execute(
                """INSERT INTO broker_selector_setup VALUES(?,?,?,?)
                            ON CONFLICT(adapter_id,account_id) DO UPDATE SET
                            present=excluded.present,setup_json=excluded.setup_json""",
                (*_pair(selector), *setup),
            )
            return self._bump(conn, selector)

    def _snapshot_primary(
        self, conn: sqlite3.Connection, selector: BrokerSelector, is_primary: bool
    ) -> PrimaryProjectionSnapshot:
        if type(is_primary) is not bool:
            raise CredentialValidationError
        self._available(conn, selector)
        if self._row(conn, selector) is None:
            raise CredentialNotFoundError
        primary = self._primary(conn)
        participants = sorted(set(primary) | {selector})
        versions = tuple(self._state(conn, key).version for key in participants)
        flags = {key: key in primary for key in participants}
        receipt = PrimaryProjectionSnapshot(selector, versions)
        self._receipts[receipt] = (is_primary, flags, primary)
        return receipt

    def snapshot_primary_projection(self, selector: BrokerSelector, is_primary: bool) -> PrimaryProjectionSnapshot:
        _selector(selector, mutation=True)
        with self._transaction() as conn:
            return self._snapshot_primary(conn, selector, is_primary)

    def _apply_primary(
        self, conn: sqlite3.Connection, snapshot: PrimaryProjectionSnapshot, *, bump_target: bool = False
    ) -> PrimaryProjectionMutation:
        desired, flags, primary = self._receipt(snapshot, PrimaryProjectionSnapshot)
        if self._primary(conn) != primary:
            raise CredentialStaleError
        for version in snapshot.versions:
            self._expected(conn, version.selector, version)
        after_flags = {
            key: (key == snapshot.selector if desired else False if key == snapshot.selector else value)
            for key, value in flags.items()
        }
        changed = {key for key in flags if flags[key] != after_flags[key]}
        if bump_target:
            changed.add(snapshot.selector)
        for key in changed:
            self._check_bump(conn, key)
        for key in changed:
            conn.execute(
                "UPDATE accounts SET is_primary=? WHERE adapter_id=? AND account_id=?",
                (int(after_flags[key]), *_pair(key)),
            )
            self._bump(conn, key)
        after_versions = tuple(self._state(conn, version.selector).version for version in snapshot.versions)
        receipt = PrimaryProjectionMutation(snapshot.selector, snapshot.versions, after_versions)
        self._receipts[receipt] = (flags, after_flags)
        return receipt

    def apply_primary_projection(self, snapshot: PrimaryProjectionSnapshot) -> PrimaryProjectionMutation:
        self._receipt(snapshot, PrimaryProjectionSnapshot)
        _selector(snapshot.selector, mutation=True)
        with self._transaction(write=True) as conn:
            return self._apply_primary(conn, snapshot)

    def restore_primary_projection(self, mutation: PrimaryProjectionMutation) -> tuple[CredentialVersion, ...]:
        flags, after_flags = self._receipt(mutation, PrimaryProjectionMutation)
        with self._transaction(write=True) as conn:
            if set(self._primary(conn)) != {key for key, flag in after_flags.items() if flag}:
                raise CredentialStaleError
            for version in mutation.after_versions:
                self._expected(conn, version.selector, version)
            changed = {key for key in flags if flags[key] != after_flags[key]}
            for key in changed:
                self._check_bump(conn, key)
            for key in changed:
                conn.execute(
                    "UPDATE accounts SET is_primary=? WHERE adapter_id=? AND account_id=?",
                    (int(flags[key]), *_pair(key)),
                )
                self._bump(conn, key)
            return tuple(self._state(conn, version.selector).version for version in mutation.after_versions)

    # Compatibility resolution and writes share one owned transaction.
    def _resolve_legacy(self, conn: sqlite3.Connection, account_id: str) -> BrokerSelector | None:
        BrokerSelector("legacy", account_id)
        rows = conn.execute("SELECT adapter_id FROM accounts WHERE account_id=?", (account_id,)).fetchall()
        if len(rows) > 1:
            raise CredentialAmbiguityError
        if not rows:
            return None
        selector = BrokerSelector(rows[0][0], account_id)
        self._available(conn, selector)
        return selector

    def retrieve_for(self, adapter_id: str, account_id: str) -> dict[str, Any]:
        return self.retrieve_credentials(BrokerSelector(adapter_id, account_id))

    def retrieve(self, account_id: str) -> dict[str, Any]:
        with self._transaction() as conn:
            selector = self._resolve_legacy(conn, account_id)
            if selector is None:
                raise CredentialNotFoundError
            return self._decrypt(self._row(conn, selector))

    def account_exists(self, account_id: str) -> bool:
        with self._transaction() as conn:
            return self._resolve_legacy(conn, account_id) is not None

    def list_accounts(self) -> list[dict[str, Any]]:
        with self._transaction() as conn:
            rows = conn.execute("""SELECT a.account_id,a.adapter_id,a.broker,a.label,a.is_primary,a.created_at
                                   FROM accounts a JOIN credential_selector_versions v
                                   ON a.adapter_id=v.adapter_id AND a.account_id=v.account_id
                                   WHERE v.origin!='legacy_interim_candidate' ORDER BY a.created_at""").fetchall()
            return [dict(row) | {"is_primary": bool(row["is_primary"])} for row in rows]

    def store(
        self,
        account_id: str,
        broker: str,
        label: str,
        credentials: dict[str, Any],
        is_primary: bool = False,
        adapter_id: str | None = None,
    ) -> None:
        selector = _selector(BrokerSelector(broker if adapter_id is None else adapter_id, account_id), mutation=True)
        with self._transaction(write=True) as conn:
            found = self._resolve_legacy(conn, account_id)
            if found is None:
                require_broker_account_mutations()
            if found != selector:
                raise CredentialConflictError
            snapshot = self._snapshot_primary(conn, selector, is_primary)
            desired, flags, _primary = self._receipt(snapshot, PrimaryProjectionSnapshot)
            for key, flag in flags.items():
                if key == selector or (desired and flag):
                    self._check_bump(conn, key)
            self._put(conn, selector, broker, label, credentials)
            self._apply_primary(conn, snapshot, bump_target=True)

    def update_credentials_for(self, adapter_id: str, account_id: str, credentials: dict[str, Any]) -> None:
        selector = _selector(BrokerSelector(adapter_id, account_id), mutation=True)
        with self._transaction(write=True) as conn:
            self._available(conn, selector)
            row = self._row(conn, selector)
            if row is None:
                raise CredentialNotFoundError
            self._check_bump(conn, selector)
            self._put(conn, selector, row["broker"], row["label"], credentials)
            self._bump(conn, selector)

    def remove(self, account_id: str) -> None:
        with self._transaction(write=True) as conn:
            selector = self._resolve_legacy(conn, account_id)
            if selector is not None:
                _selector(selector, mutation=True)
                self._remove(conn, selector, credentials=True, setup=True)

    def remove_for(self, adapter_id: str, account_id: str) -> None:
        selector = _selector(BrokerSelector(adapter_id, account_id), mutation=True)
        with self._transaction(write=True) as conn:
            self._available(conn, selector)
            if self._row(conn, selector) is not None:
                self._remove(conn, selector, credentials=True, setup=True)

    def set_primary(self, account_id: str) -> None:
        with self._transaction(write=True) as conn:
            selector = self._resolve_legacy(conn, account_id)
            if selector is None:
                raise CredentialNotFoundError
            _selector(selector, mutation=True)
            self._apply_primary(conn, self._snapshot_primary(conn, selector, True))

    def stage_credentials_for(
        self,
        adapter_id: str,
        account_id: str,
        credentials: dict[str, Any],
        *,
        broker: str | None = None,
        label: str | None = None,
        is_primary: bool | None = None,
    ) -> StagedCredentialStore:
        selector = _selector(BrokerSelector(adapter_id, account_id), mutation=True)
        if self.account_for_selector(selector) is None:
            require_broker_account_mutations()
        if is_primary is not None and (broker is None or label is None):
            raise CredentialValidationError
        stage = self.stage_credentials(selector, credentials, broker=broker, label=label)
        if is_primary is not None:
            snapshot = self.snapshot_primary_projection(selector, is_primary)
            if stage.expected_version not in snapshot.versions:
                raise CredentialStaleError
            stage._primary_snapshot = snapshot
            stage._metadata["is_primary"] = is_primary
        return stage

    def _commit_legacy_stage(self, stage: StagedCredentialStore) -> CredentialVersion:
        """Apply legacy metadata and its captured complete primary CAS atomically."""
        snapshot = stage._primary_snapshot
        desired, flags, primary = self._receipt(snapshot, PrimaryProjectionSnapshot)
        with self._transaction(write=True) as conn:
            if self._primary(conn) != primary:
                raise CredentialStaleError
            for version in snapshot.versions:
                self._expected(conn, version.selector, version)
            self._expected(conn, stage._selector, stage.expected_version)
            for key, flag in flags.items():
                if key == stage._selector or (desired and flag):
                    self._check_bump(conn, key)
            self._put(conn, stage._selector, stage._metadata["broker"], stage._metadata["label"], stage._credentials)
            self._apply_primary(conn, snapshot, bump_target=True)
            return self._state(conn, stage._selector).version
