"""Encrypted per-webhook secret and replay store.

The Flows registry keeps only frontend-safe metadata in ``workspace.json``.
This store owns the sensitive half of the mounted webhook path: HMAC signing
secrets encrypted at rest plus the replay nonce table used before dispatch.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from flinttrade_core.auth_state_runtime import (
    AuthStateUnavailable,
    open_authority_database,
    require_database,
    validate_schema,
)

from .webhook_keys import decrypt_webhook_secret, encrypt_webhook_secret
from .webhook_replay import (
    _NONCE_SCHEMA,
    GC_RETAIN_SECONDS,
    check_replay,
    gc_old_nonces,
    record_nonce,
)

_KDF_ITERATIONS = 390_000
_MASTER_DEK_SALT = b"flinttrade-webhook-store-v1"

_WEBHOOK_SECRET_SCHEMA = """
CREATE TABLE IF NOT EXISTS webhooks (
    webhook_id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    name TEXT NOT NULL,
    secret_encrypted_aes_gcm_siv BLOB NOT NULL,
    key_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def canonical_webhook_id(path: str) -> str:
    """Return the stable identity bound into encryption and replay checks."""
    return path.strip().lstrip("/")


class WebhookSecretStore:
    """SQLite-backed encrypted signing-secret and replay store."""

    def __init__(self, db_path: str | Path, master_password: str) -> None:
        self._db_path = Path(db_path).absolute()
        if self._db_path.name in {"auth_state.sqlite", "webhook_secrets.db"}:
            from flinttrade_core.auth_state_migration import select_webhook_store_path

            if select_webhook_store_path(self._db_path.parent) != self._db_path:
                raise AuthStateUnavailable("webhook consumer differs from verified selection")
        self._master_dek = self._derive_master_dek(master_password)
        self._init_db()
        stat = self._db_path.stat()
        self._identity = (stat.st_dev, stat.st_ino)

    @staticmethod
    def _derive_master_dek(master_password: str) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_MASTER_DEK_SALT,
            iterations=_KDF_ITERATIONS,
        )
        return kdf.derive(master_password.encode("utf-8"))

    def _connect(self) -> sqlite3.Connection:
        require_database(self._db_path)
        stat = self._db_path.stat()
        if (stat.st_dev, stat.st_ino) != self._identity:
            raise AuthStateUnavailable("webhook authority was replaced")
        conn = sqlite3.connect(self._db_path.as_uri() + "?mode=rw", uri=True, isolation_level=None, timeout=5.0)
        try:
            validate_schema(conn, _WEBHOOK_SECRET_SCHEMA + _NONCE_SCHEMA)
            conn.execute("PRAGMA synchronous=FULL")
            conn.row_factory = sqlite3.Row
            return conn
        except BaseException:
            conn.close()
            raise

    def _init_db(self) -> None:
        # Merely reopening must retain migrated historical evidence. Normal
        # intake and explicit GC still apply the existing retention contract.
        with closing(open_authority_database(self._db_path, _WEBHOOK_SECRET_SCHEMA + _NONCE_SCHEMA)):
            pass

    def store_secret(self, path: str, source: str, name: str, secret: str) -> None:
        """Encrypt and persist the signing secret for one mounted webhook path."""
        webhook_id = canonical_webhook_id(path)
        now = datetime.now(UTC).isoformat()
        blob = encrypt_webhook_secret(secret.encode("utf-8"), webhook_id, self._master_dek)
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO webhooks (
                    webhook_id, path, source, name, secret_encrypted_aes_gcm_siv,
                    key_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    source = excluded.source,
                    name = excluded.name,
                    secret_encrypted_aes_gcm_siv = excluded.secret_encrypted_aes_gcm_siv,
                    key_version = 1,
                    updated_at = excluded.updated_at
                """,
                (webhook_id, path, source, name, blob, now, now),
            )

    def delete_secret(self, path: str) -> None:
        """Remove any stored signing secret for the mounted webhook path."""
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM webhooks WHERE path = ?", (path,))

    def get_secret(self, path: str) -> str | None:
        """Return the decrypted signing secret for ``path``, or ``None``."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT webhook_id, secret_encrypted_aes_gcm_siv, key_version
                FROM webhooks
                WHERE path = ?
                """,
                (path,),
            ).fetchone()
        if row is None:
            return None
        plaintext = decrypt_webhook_secret(
            bytes(row["secret_encrypted_aes_gcm_siv"]),
            str(row["webhook_id"]),
            self._master_dek,
            int(row["key_version"]),
        )
        return plaintext.decode("utf-8")

    def has_secret(self, path: str) -> bool:
        """Return whether a signing secret is configured for ``path``."""
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT 1 FROM webhooks WHERE path = ? LIMIT 1", (path,)).fetchone()
        return row is not None

    def check_and_record_nonce(
        self,
        path: str,
        nonce: str,
        payload_ts: float,
        source_ip_hash: str | None = None,
        now: float | None = None,
    ) -> str | None:
        """Atomically reject stale/replayed nonces, then record accepted ones."""
        webhook_id = canonical_webhook_id(path)
        seen_at = time.time() if now is None else now
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                reason = check_replay(conn, webhook_id, nonce, payload_ts, now=seen_at)
                if reason is None:
                    record_nonce(conn, webhook_id, nonce, seen_at=seen_at, source_ip_hash=source_ip_hash)
                # The packaged desktop intentionally does not run the full
                # automation scheduler. Keep its replay table bounded on every
                # intake while the server runtime retains the daily cron job.
                gc_old_nonces(conn, now=seen_at)
                conn.execute("COMMIT")
                return reason
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def release_nonce_reservation(
        self,
        path: str,
        nonce: str,
        claimed_at: float,
    ) -> bool:
        """Release exactly the caller's nonce claim after quota refusal."""
        webhook_id = canonical_webhook_id(path)
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "DELETE FROM webhook_nonces WHERE webhook_id = ? AND nonce = ? AND seen_at = ?",
                (webhook_id, nonce, claimed_at),
            )
            return cursor.rowcount == 1

    def gc_nonces(
        self,
        *,
        retain_seconds: int = GC_RETAIN_SECONDS,
        now: float | None = None,
    ) -> int:
        """Delete expired replay evidence while retaining the forensic grace."""
        with closing(self._connect()) as conn:
            return gc_old_nonces(conn, retain_seconds=retain_seconds, now=now)
