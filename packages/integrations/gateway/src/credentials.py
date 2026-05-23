"""Fernet-encrypted credential storage in SQLite.

Location: ``~/.flinttrade/credentials.db``

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
    broker          TEXT NOT NULL,
    label           TEXT NOT NULL,
    salt            BLOB NOT NULL,
    encrypted_creds BLOB NOT NULL,
    is_primary      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);
"""


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

        store = CredentialStore(Path.home() / ".flinttrade/credentials.db", "<MASTER_PASSWORD>")
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
        """Create the ``accounts`` table if it does not already exist."""
        with self._get_connection() as conn:
            conn.execute(_CREATE_TABLE_SQL)
            conn.commit()

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
    ) -> None:
        """Encrypt and persist broker credentials for an account.

        If an account with ``account_id`` already exists its credentials,
        broker, label, and ``is_primary`` flag are overwritten (salt and
        ``created_at`` are preserved for existing rows; a new salt and
        timestamp are generated for brand-new accounts).

        Args:
            account_id: Unique identifier for the account (e.g. client code).
            broker: Canonical broker name (e.g. ``"zerodha"``).
            label: Human-readable label shown in the UI.
            credentials: Arbitrary key-value dict of sensitive credentials
                (API keys, secrets, tokens, etc.).
            is_primary: Whether this account is the default for order routing.

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

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO accounts
                    (account_id, broker, label, salt, encrypted_creds,
                     is_primary, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    broker          = excluded.broker,
                    label           = excluded.label,
                    salt            = excluded.salt,
                    encrypted_creds = excluded.encrypted_creds,
                    is_primary      = excluded.is_primary
                """,
                (account_id, broker, label, salt, encrypted, is_primary_int, created_at),
            )
            conn.commit()

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
                SELECT account_id, broker, label, is_primary, created_at
                FROM accounts
                ORDER BY created_at ASC
                """
            ).fetchall()

        return [
            {
                "account_id": row["account_id"],
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
            conn.execute("UPDATE accounts SET is_primary = 0")
            conn.execute(
                "UPDATE accounts SET is_primary = 1 WHERE account_id = ?",
                (account_id,),
            )
            conn.commit()

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
