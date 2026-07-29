"""Fernet-encrypted credential storage in SQLite.

Location: ``workspace_dir() / "credentials.db"`` — the active workspace
directory, resolved by :func:`flinttrade_core.workspace.workspace_dir`.

Schema::

    accounts(
        account_id    TEXT PRIMARY KEY,
        broker        TEXT NOT NULL,
        label         TEXT NOT NULL,
        salt          BLOB NOT NULL,
        encrypted_creds BLOB NOT NULL,
        is_primary    INTEGER NOT NULL DEFAULT 0,   -- SQLite bool
        created_at    TEXT NOT NULL                 -- ISO-8601 UTC
    )

Each account uses a **unique random salt** so that two accounts with
identical credentials produce distinct ciphertexts.  The master password
is never stored; it is only used as the key-derivation input.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from flinttrade_core.db import open_sqlite

logger = logging.getLogger("flinttrade.gateway.credentials")

# ---------------------------------------------------------------------------
# Error class — always defined here so callers get a stable class identity
# regardless of import path.  exceptions.py (Task 1) re-exports this class
# rather than defining its own, avoiding the dual-class-object problem that
# arises under pytest --import-mode=importlib.
# ---------------------------------------------------------------------------


class CredentialError(Exception):
    """Raised for all credential-storage failures.

    Args:
        message: Human-readable description of the failure.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_KDF_ITERATIONS: int = 390_000  # NIST-recommended minimum for PBKDF2-SHA256
_SALT_BYTES: int = 16
_CREATE_TABLE_SQL: str = """
CREATE TABLE IF NOT EXISTS accounts (
    account_id      TEXT PRIMARY KEY,
    adapter_id      TEXT NOT NULL DEFAULT '',
    broker          TEXT NOT NULL,
    label           TEXT NOT NULL,
    salt            BLOB NOT NULL,
    encrypted_creds BLOB NOT NULL,
    is_primary      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);
"""
# Composite selector index (contract §12 / identity X7). account_id remains the
# PRIMARY KEY (so existing rows are never recreated — no data-loss risk); the
# adapter_id column + this index give the router a fast (adapter_id, account_id)
# lookup. Same account_id under two adapters is the one shape this does not
# support; in practice broker client codes differ per adapter.
_COMPOSITE_INDEX_SQL: str = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_adapter_account "
    "ON accounts(adapter_id, account_id);"
)


def _copy_credential_payload(credentials: dict[str, Any]) -> dict[str, Any]:
    """Validate and detach a credential payload without exposing its values."""
    try:
        encoded = json.dumps(credentials)
        copied = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise CredentialError("Cannot serialise staged credentials") from exc
    if not isinstance(copied, dict):  # pragma: no cover - input annotation + JSON invariant
        raise CredentialError("Staged credentials must be an object")
    return copied


class StagedCredentialStore:
    """One-selector, in-memory credential overlay used for candidate login.

    Router activation and native login can read and rewrite the candidate through
    the normal credential-store surface, while the backing SQLite row remains
    untouched. ``commit`` is the only operation that writes to the durable vault.
    """

    def __init__(
        self,
        store: CredentialStore,
        *,
        adapter_id: str,
        account_id: str,
        credentials: dict[str, Any],
        metadata: dict[str, Any],
        replace_metadata: bool,
    ) -> None:
        self._store = store
        self._adapter_id = adapter_id
        self._account_id = account_id
        self._credentials = _copy_credential_payload(credentials)
        self._metadata = dict(metadata)
        self._replace_metadata = replace_metadata
        self._active = True

    def __repr__(self) -> str:
        state = "pending" if self._active else "closed"
        return f"<StagedCredentialStore state={state}>"

    def _ensure_active(self) -> None:
        if not self._active:
            raise CredentialError("Staged credentials are no longer available")

    def _ensure_selector(self, adapter_id: str, account_id: str) -> None:
        self._ensure_active()
        if (adapter_id, account_id) != (self._adapter_id, self._account_id):
            raise CredentialError("Staged credential access is limited to its selector")

    def list_accounts(self) -> list[dict[str, Any]]:
        """Return backing metadata with the candidate selector overlaid."""
        self._ensure_active()
        rows = [dict(row) for row in self._store.list_accounts()]
        for index, row in enumerate(rows):
            if (
                str(row.get("adapter_id") or row.get("broker") or "") == self._adapter_id
                and str(row.get("account_id") or "") == self._account_id
            ):
                rows[index] = dict(self._metadata)
                break
        else:
            rows.append(dict(self._metadata))
        return rows

    def retrieve_for(self, adapter_id: str, account_id: str) -> dict[str, Any]:
        """Return a detached copy of the staged candidate payload."""
        self._ensure_selector(adapter_id, account_id)
        return _copy_credential_payload(self._credentials)

    def update_credentials_for(
        self,
        adapter_id: str,
        account_id: str,
        credentials: dict[str, Any],
    ) -> None:
        """Stage replayable credentials produced by a successful adapter login."""
        self._ensure_selector(adapter_id, account_id)
        self._credentials = _copy_credential_payload(credentials)

    def commit(self) -> None:
        """Atomically publish the candidate payload to the backing vault."""
        self._ensure_active()
        if self._replace_metadata:
            self._store.store(
                self._account_id,
                str(self._metadata["broker"]),
                str(self._metadata["label"]),
                self._credentials,
                is_primary=bool(self._metadata["is_primary"]),
                adapter_id=self._adapter_id,
            )
        else:
            self._store.update_credentials_for(
                self._adapter_id,
                self._account_id,
                self._credentials,
            )
        self.discard()

    def discard(self) -> None:
        """Forget the candidate without touching the durable vault."""
        self._credentials.clear()
        self._active = False


# ---------------------------------------------------------------------------
# CredentialStore
# ---------------------------------------------------------------------------


class CredentialStore:
    """Fernet-encrypted credential store backed by a SQLite database.

    Each broker account's credentials are encrypted with a Fernet key
    derived from the master password plus a per-account random salt via
    PBKDF2-SHA256.  The master password is held in memory only for the
    lifetime of this object; it is never persisted.

    Args:
        db_path: Absolute path to the SQLite database file.  The parent
            directory is created if it does not exist.
        master_password: Passphrase used for key derivation.  Must be
            identical across store/retrieve calls for the same account.

    Raises:
        CredentialError: If the database cannot be initialised.

    Example::

        from flinttrade_core.workspace import workspace_dir

        store = CredentialStore(workspace_dir() / "credentials.db", "<MASTER_PASSWORD>")
        store.store("acc1", "broker_name", "Primary", {"api_key": "<YOUR_KEY>", "api_secret": "<YOUR_SECRET>"})
        creds = store.retrieve("acc1")
    """

    def __init__(self, db_path: Path, master_password: str) -> None:
        self._db_path = db_path
        self._master_password: bytes = master_password.encode("utf-8")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_connection(self) -> sqlite3.Connection:
        """Return a new SQLite connection with WAL mode for concurrency.

        Returns:
            A configured :class:`sqlite3.Connection`.
        """
        conn = open_sqlite(str(self._db_path), durability="normal")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create the ``accounts`` table and evolve its schema if it predates
        the composite (adapter_id, account_id) selector (contract §12).

        The migration is purely additive — ``ALTER TABLE ADD COLUMN`` plus a
        backfill — so a pre-existing ``credentials.db`` is never recreated and no
        encrypted credential row can be orphaned.
        """
        with self._get_connection() as conn:
            conn.execute(_CREATE_TABLE_SQL)
            self._ensure_adapter_id_column(conn)
            conn.execute(_COMPOSITE_INDEX_SQL)
            conn.commit()

    def _ensure_adapter_id_column(self, conn: sqlite3.Connection) -> None:
        """Add ``adapter_id`` to a legacy single-key table and backfill it.

        Existing rows take their ``adapter_id`` from the ``broker`` column as a
        best-effort default; the operator re-saves an account to correct it if
        the routing adapter differs from the broker name (e.g. an OpenAlgo-routed
        account whose selector adapter is ``"openalgo"``).

        The connection runs in SQLite autocommit mode (``isolation_level=None``),
        so the ALTER and the backfill are wrapped in one explicit
        ``BEGIN IMMEDIATE`` ... ``COMMIT`` transaction. Without it a crash between
        the two statements would strand legacy rows at ``adapter_id = ''``
        permanently, because the ``"adapter_id" not in columns`` guard would never
        re-run the backfill. The backfill ``UPDATE`` is also run on **every** open,
        even when the column already exists, so any rows left blank by an earlier
        partial migration are self-healed.
        """
        columns = {row[1] for row in conn.execute("PRAGMA table_info(accounts)").fetchall()}
        conn.execute("BEGIN IMMEDIATE")
        try:
            if "adapter_id" not in columns:
                try:
                    conn.execute(
                        "ALTER TABLE accounts ADD COLUMN adapter_id TEXT NOT NULL DEFAULT ''"
                    )
                except sqlite3.OperationalError as exc:
                    # Tolerate a cross-process race where another connection added
                    # the column first — treat "duplicate column" as already
                    # migrated and fall through to the self-healing backfill.
                    if "duplicate column" not in str(exc).lower():
                        raise
            # Self-healing backfill: idempotent, runs on every open so a crash
            # mid-migration (or a row inserted with a blank adapter_id) recovers.
            conn.execute(
                "UPDATE accounts SET adapter_id = broker "
                "WHERE adapter_id IS NULL OR adapter_id = ''"
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

    def _derive_key(self, salt: bytes) -> Fernet:
        """Derive a Fernet symmetric key from the master password and salt.

        Uses PBKDF2-HMAC-SHA256 with :data:`_KDF_ITERATIONS` iterations.

        Args:
            salt: Per-account random bytes used as the PBKDF2 salt.

        Returns:
            A ready-to-use :class:`~cryptography.fernet.Fernet` instance.
        """
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=_KDF_ITERATIONS,
        )
        key = base64.urlsafe_b64encode(kdf.derive(self._master_password))
        return Fernet(key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(
        self,
        account_id: str,
        broker: str,
        label: str,
        credentials: dict[str, Any],
        is_primary: bool = False,
        adapter_id: str | None = None,
    ) -> None:
        """Encrypt and persist broker credentials for an account.

        If an account with ``account_id`` already exists its credentials,
        broker, label, ``adapter_id``, and ``is_primary`` flag are overwritten
        (salt and ``created_at`` are preserved for existing rows; a new salt and
        timestamp are generated for brand-new accounts).

        Args:
            account_id: Unique identifier for the account (e.g. client code).
            broker: Canonical broker name (e.g. ``"zerodha"``).
            label: Human-readable label shown in the UI.
            credentials: Arbitrary key-value dict of sensitive credentials
                (API keys, secrets, tokens, etc.).
            is_primary: Whether this account is the default for order routing.
            adapter_id: The routing adapter for this account (e.g. ``"dhan"``,
                ``"openalgo"``). Defaults to ``broker`` when omitted, so legacy
                callers keep working; pass it explicitly for the selector model.

        Raises:
            CredentialError: If serialisation or encryption fails.
        """
        try:
            payload: bytes = json.dumps(credentials).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise CredentialError(f"Cannot serialise credentials: {exc}") from exc

        salt: bytes = os.urandom(_SALT_BYTES)
        fernet: Fernet = self._derive_key(salt)

        try:
            encrypted: bytes = fernet.encrypt(payload)
        except Exception as exc:  # pragma: no cover
            raise CredentialError(f"Encryption failed: {exc}") from exc

        created_at: str = datetime.now(tz=timezone.utc).isoformat()
        is_primary_int: int = int(is_primary)
        resolved_adapter_id: str = adapter_id or broker

        with self._get_connection() as conn:
            # The table's PRIMARY KEY is ``account_id`` alone, but the selector
            # model is composite ``(adapter_id, account_id)``. Without this guard
            # the ON CONFLICT(account_id) upsert would let a second broker that
            # happens to share a client code silently OVERWRITE the first
            # broker's encrypted credentials (unrecoverable). Reject the
            # cross-adapter collision explicitly; re-storing under the SAME
            # adapter (a credential update) is still allowed.
            existing = conn.execute(
                "SELECT adapter_id FROM accounts WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            if existing is not None and str(existing["adapter_id"]) != resolved_adapter_id:
                raise CredentialError(
                    f"account_id {account_id!r} is already used by adapter "
                    f"{existing['adapter_id']!r}; a different broker cannot reuse it "
                    "(it would overwrite the other broker's stored credentials)"
                )
            conn.execute(
                """
                INSERT INTO accounts
                    (account_id, adapter_id, broker, label, salt, encrypted_creds,
                     is_primary, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    adapter_id      = excluded.adapter_id,
                    broker          = excluded.broker,
                    label           = excluded.label,
                    salt            = excluded.salt,
                    encrypted_creds = excluded.encrypted_creds,
                    is_primary      = excluded.is_primary
                """,
                (account_id, resolved_adapter_id, broker, label, salt, encrypted, is_primary_int, created_at),
            )
            conn.commit()

    def update_credentials_for(
        self, adapter_id: str, account_id: str, credentials: dict[str, Any]
    ) -> None:
        """Re-encrypt and replace ONLY the credential payload for a selector.

        The write-back half of reconnect realism (G7): after a successful
        ``login()`` the vault swaps single-use artefacts (an OAuth ``code``, a
        30-second TOTP) for the minted, replayable material (the live
        ``access_token``) — without touching the row's broker, label,
        ``is_primary``, or ``created_at``. A fresh salt is generated per write,
        matching the per-row random-salt design.

        Args:
            adapter_id: The routing adapter (e.g. ``"upstox"``).
            account_id: The account within that adapter.
            credentials: The replayable credential dict to persist.

        Raises:
            CredentialError: If no matching row exists or encryption fails.
        """
        try:
            payload: bytes = json.dumps(credentials).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise CredentialError(f"Cannot serialise credentials: {exc}") from exc

        salt: bytes = os.urandom(_SALT_BYTES)
        fernet: Fernet = self._derive_key(salt)
        try:
            encrypted: bytes = fernet.encrypt(payload)
        except Exception as exc:  # pragma: no cover
            raise CredentialError(f"Encryption failed: {exc}") from exc

        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE accounts SET salt = ?, encrypted_creds = ? "
                "WHERE adapter_id = ? AND account_id = ?",
                (salt, encrypted, adapter_id, account_id),
            )
            conn.commit()
        if cursor.rowcount == 0:
            raise CredentialError(
                f"Account not found for selector {adapter_id!r}:{account_id!r}"
            )

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
        """Build a non-persistent one-selector credential view.

        Omitting all metadata stages a payload-only update for an existing row.
        Supplying metadata stages a full store/upsert, used by native connect.
        The candidate is activation-visible through ``list_accounts`` but does
        not alter SQLite until its explicit ``commit``.
        """
        rows = self.list_accounts()
        same_account = next(
            (row for row in rows if str(row.get("account_id") or "") == account_id),
            None,
        )
        if same_account is not None:
            existing_adapter = str(
                same_account.get("adapter_id") or same_account.get("broker") or ""
            )
            if existing_adapter != adapter_id:
                raise CredentialError(
                    "A different broker already uses this account identifier"
                )

        supplied_metadata = (broker, label, is_primary)
        replace_metadata = any(value is not None for value in supplied_metadata)
        if replace_metadata and not all(value is not None for value in supplied_metadata):
            raise CredentialError("Staged credential metadata must be complete")
        if not replace_metadata and same_account is None:
            raise CredentialError("Cannot stage a payload update for a missing account")

        if replace_metadata:
            metadata = {
                "account_id": account_id,
                "adapter_id": adapter_id,
                "broker": str(broker),
                "label": str(label),
                "is_primary": bool(is_primary),
                "created_at": same_account.get("created_at") if same_account else None,
            }
        else:
            metadata = dict(same_account or {})

        return StagedCredentialStore(
            self,
            adapter_id=adapter_id,
            account_id=account_id,
            credentials=credentials,
            metadata=metadata,
            replace_metadata=replace_metadata,
        )

    def retrieve_for(self, adapter_id: str, account_id: str) -> dict[str, Any]:
        """Decrypt and return credentials by composite ``(adapter_id, account_id)``.

        The selector-keyed counterpart to :meth:`retrieve` (contract §12). Use
        this on the routing path so two accounts that share an ``account_id``
        across adapters resolve to the correct row.

        Args:
            adapter_id: The routing adapter (e.g. ``"dhan"``).
            account_id: The account within that adapter.

        Returns:
            The original credentials dict.

        Raises:
            CredentialError: If no matching row exists, the master password is
                wrong, or the ciphertext is corrupt.
        """
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT salt, encrypted_creds FROM accounts "
                "WHERE adapter_id = ? AND account_id = ?",
                (adapter_id, account_id),
            ).fetchone()

        if row is None:
            raise CredentialError(
                f"Account not found for selector {adapter_id!r}:{account_id!r}"
            )

        fernet: Fernet = self._derive_key(bytes(row["salt"]))
        try:
            plaintext: bytes = fernet.decrypt(bytes(row["encrypted_creds"]))
        except InvalidToken as exc:
            raise CredentialError(
                f"Decryption failed for selector {adapter_id!r}:{account_id!r} — "
                "wrong master password or corrupt data"
            ) from exc

        try:
            return json.loads(plaintext.decode("utf-8"))  # type: ignore[no-any-return]
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:  # pragma: no cover
            raise CredentialError(f"Credential payload corrupt: {exc}") from exc

    def retrieve(self, account_id: str) -> dict[str, Any]:
        """Decrypt and return the credentials for an account.

        Args:
            account_id: Account identifier previously passed to :meth:`store`.

        Returns:
            The original credentials dict as passed to :meth:`store`.

        Raises:
            CredentialError: If the account does not exist, the master
                password is wrong, or the ciphertext is corrupt.
        """
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT salt, encrypted_creds FROM accounts WHERE account_id = ?",
                (account_id,),
            ).fetchone()

        if row is None:
            raise CredentialError(f"Account not found: {account_id!r}")

        fernet: Fernet = self._derive_key(bytes(row["salt"]))
        try:
            plaintext: bytes = fernet.decrypt(bytes(row["encrypted_creds"]))
        except InvalidToken as exc:
            raise CredentialError(
                f"Decryption failed for account {account_id!r} — "
                "wrong master password or corrupt data"
            ) from exc

        try:
            return json.loads(plaintext.decode("utf-8"))  # type: ignore[no-any-return]
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:  # pragma: no cover
            raise CredentialError(f"Credential payload corrupt: {exc}") from exc

    def remove(self, account_id: str) -> None:
        """Delete an account from the store.

        Silently succeeds if the account does not exist.

        Args:
            account_id: Account identifier to remove.
        """
        with self._get_connection() as conn:
            conn.execute(
                "DELETE FROM accounts WHERE account_id = ?", (account_id,)
            )
            conn.commit()

    def remove_for(self, adapter_id: str, account_id: str) -> None:
        """Delete an account by composite ``(adapter_id, account_id)`` selector.

        Native account-management routes carry both selector parts in the URL.
        Deleting by ``account_id`` alone would let a mistyped adapter path remove
        a different broker's vault row when account ids collide or when the
        caller simply supplied the wrong adapter. Missing selectors are a no-op,
        matching :meth:`remove`.

        Args:
            adapter_id: The routing adapter (e.g. ``"dhan"``).
            account_id: The account within that adapter.
        """
        with self._get_connection() as conn:
            conn.execute(
                "DELETE FROM accounts WHERE adapter_id = ? AND account_id = ?",
                (adapter_id, account_id),
            )
            conn.commit()

    def list_accounts(self) -> list[dict[str, Any]]:
        """Return metadata for all stored accounts without decrypted credentials.

        Returns:
            List of dicts with keys ``account_id``, ``broker``, ``label``,
            ``is_primary``, and ``created_at``.  Ordered by ``created_at``
            ascending (oldest first).
        """
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT account_id, adapter_id, broker, label, is_primary, created_at
                FROM accounts
                ORDER BY created_at ASC
                """
            ).fetchall()

        return [
            {
                "account_id": row["account_id"],
                "adapter_id": row["adapter_id"],
                "broker": row["broker"],
                "label": row["label"],
                "is_primary": bool(row["is_primary"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def set_primary(self, account_id: str) -> None:
        """Mark one account as primary and clear the flag on all others.

        Args:
            account_id: The account to promote to primary.

        Raises:
            CredentialError: If the account does not exist.
        """
        with self._get_connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM accounts WHERE account_id = ?", (account_id,)
            ).fetchone()
            if exists is None:
                raise CredentialError(
                    f"Cannot set primary — account not found: {account_id!r}"
                )
            # One atomic statement: under SQLite autocommit
            # (``isolation_level=None``) two separate UPDATEs would leave a
            # transient window in which no row is primary, and the trailing
            # ``conn.commit()`` is a no-op. A single CASE expression sets the
            # chosen account and clears every other in the same write.
            conn.execute(
                "UPDATE accounts SET is_primary = "
                "CASE WHEN account_id = ? THEN 1 ELSE 0 END",
                (account_id,),
            )

    def snapshot_primary_metadata(self) -> dict[str, bool]:
        """Snapshot every vault row's primary flag without decrypting credentials."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT account_id, is_primary FROM accounts"
            ).fetchall()
        return {str(row["account_id"]): bool(row["is_primary"]) for row in rows}

    def restore_primary_metadata(self, snapshot: dict[str, bool]) -> None:
        """Atomically restore a prior primary-flag snapshot.

        A changed account set means the snapshot is stale. Refuse it instead of
        overwriting primary metadata created by a concurrent vault mutation.
        """
        with self._get_connection() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                current_ids = {
                    str(row["account_id"])
                    for row in conn.execute("SELECT account_id FROM accounts").fetchall()
                }
                if current_ids != set(snapshot):
                    raise CredentialError("Primary metadata snapshot is stale")
                conn.executemany(
                    "UPDATE accounts SET is_primary = ? WHERE account_id = ?",
                    [(int(is_primary), account_id) for account_id, is_primary in snapshot.items()],
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def account_exists(self, account_id: str) -> bool:
        """Check whether an account is stored in the database.

        Args:
            account_id: Account identifier to look up.

        Returns:
            ``True`` if the account exists, ``False`` otherwise.
        """
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM accounts WHERE account_id = ?", (account_id,)
            ).fetchone()
        return row is not None
