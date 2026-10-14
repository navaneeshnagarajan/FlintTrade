#!/usr/bin/env python3
"""Offline auth-state migration to the actual SQLite runtime authority.

Publication requires real AuthState/webhook readers, exact typed data and
verified encrypted custody. Standalone webhook authorities are never discarded.

AGE requires the declared pyrage migration dependency. Missing crypto or reader
support is a failure, never skipped work. Passwords enter only through a TTY or
--master-password-fd; auth.db password/MFA material is not changed by this tool.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import logging
import os
import sqlite3
import sys
from contextlib import ExitStack, closing
from pathlib import Path

from flinttrade_core.auth_state_migration import record_webhook_selection, validate_staged_selection
from flinttrade_core.legacy_sqlite_migration import (
    ArchivePending,
    MigrationRefused,
    database_digest,
    file_digest,
    fsync_directory,
    fsync_file,
    migrate_database,
    publish_noreplace,
    require_regular,
    rows_digest,
    sqlite_connection,
    sqlite_value,
)
from flinttrade_core.secure_file import harden
from flinttrade_core.workspace import workspace_dir

_TABLES = ("revoked_jtis", "rate_limit_events", "otp_requests", "webhooks", "webhook_nonces")


_SCHEMA_DDL = """
    CREATE TABLE IF NOT EXISTS revoked_jtis (
        jti        TEXT PRIMARY KEY,
        revoked_at REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS rate_limit_events (
        user_id   TEXT NOT NULL,
        endpoint  TEXT NOT NULL,
        bucket_ts REAL NOT NULL,
        count     INTEGER NOT NULL,
        PRIMARY KEY (user_id, endpoint, bucket_ts)
    );

    CREATE TABLE IF NOT EXISTS otp_requests (
        request_id    TEXT PRIMARY KEY,
        user_id       TEXT NOT NULL,
        purpose       TEXT NOT NULL,
        code_hash     TEXT NOT NULL,
        attempts_left INTEGER NOT NULL DEFAULT 3,
        expires_at    REAL NOT NULL,
        created_at    REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_otp_requests_expires_at
        ON otp_requests(expires_at) WHERE attempts_left > 0;

    CREATE TABLE IF NOT EXISTS consent_ledger (
        id              INTEGER PRIMARY KEY,
        purpose         TEXT NOT NULL,
        granted_at      REAL NOT NULL,
        revoked_at      REAL,
        artifact_hash   TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_consent_ledger_purpose_active
        ON consent_ledger(purpose, revoked_at);

    CREATE TABLE IF NOT EXISTS agent_runs (
        run_id                TEXT PRIMARY KEY,
        agent_name            TEXT NOT NULL,
        parent_jti            TEXT NOT NULL,
        started_at            REAL NOT NULL,
        ended_at              REAL,
        status                TEXT NOT NULL CHECK (status IN (
            'running', 'completed', 'failed', 'cancelled'
        )),
        final_decision_count  INTEGER,
        pnl_delta             REAL
    );
    CREATE INDEX IF NOT EXISTS idx_agent_runs_parent_jti
        ON agent_runs(parent_jti);
    CREATE INDEX IF NOT EXISTS idx_agent_runs_agent_started
        ON agent_runs(agent_name, started_at DESC);

    CREATE TABLE IF NOT EXISTS webhooks (
        webhook_id                    TEXT PRIMARY KEY,
        source                        TEXT NOT NULL,
        name                          TEXT NOT NULL,
        user_id                       TEXT NOT NULL,
        secret_encrypted_aes_gcm_siv  BLOB NOT NULL,
        dek_id                        TEXT NOT NULL,
        key_version                   INTEGER NOT NULL,
        created_at                    REAL NOT NULL,
        last_rotated_at               REAL NOT NULL,
        revoked_at                    REAL,
        CHECK (length(webhook_id) > 0)
    );
    CREATE INDEX IF NOT EXISTS idx_webhooks_source_active
        ON webhooks(source) WHERE revoked_at IS NULL;
    CREATE INDEX IF NOT EXISTS idx_webhooks_user_source
        ON webhooks(user_id, source) WHERE revoked_at IS NULL;

    CREATE TABLE IF NOT EXISTS webhook_nonces (
        webhook_id     TEXT NOT NULL REFERENCES webhooks(webhook_id) ON DELETE CASCADE,
        nonce          TEXT NOT NULL,
        seen_at        REAL NOT NULL,
        source_ip_hash TEXT,
        PRIMARY KEY (webhook_id, nonce)
    );
    CREATE INDEX IF NOT EXISTS idx_webhook_nonces_gc ON webhook_nonces(seen_at);

    CREATE TABLE IF NOT EXISTS login_sessions (
        consent_app_id        TEXT PRIMARY KEY,
        broker_id             TEXT NOT NULL,
        encrypted_api_key     BLOB NOT NULL,
        encrypted_api_secret  BLOB NOT NULL,
        nonce                 BLOB NOT NULL,
        dek_salt              BLOB NOT NULL,
        created_at            REAL NOT NULL,
        expires_at            REAL NOT NULL,
        CHECK (length(consent_app_id) > 0),
        CHECK (length(dek_salt) >= 32),
        CHECK (length(nonce) >= 12)
    );
    CREATE INDEX IF NOT EXISTS idx_login_sessions_expires ON login_sessions(expires_at);

    CREATE TABLE IF NOT EXISTS audit_chain_head (
        chain_id        TEXT PRIMARY KEY,
        last_event_hash TEXT NOT NULL,
        last_event_ts   REAL NOT NULL,
        updated_at      REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS auth_sessions (
        jti              TEXT PRIMARY KEY,
        sub              TEXT NOT NULL,
        actor_type       TEXT NOT NULL CHECK (actor_type IN (
            'human', 'agent', 'external_intent'
        )),
        run_id           TEXT REFERENCES agent_runs(run_id),
        issued_at        REAL NOT NULL,
        last_seen_at     REAL NOT NULL,
        ip_hash          TEXT NOT NULL,
        ua_hash          TEXT NOT NULL,
        location_summary TEXT,
        device_summary   TEXT,
        fp_cookie_hash   TEXT,
        created_via      TEXT NOT NULL CHECK (created_via IN (
            'password_totp', 'password_only', 'broker_sso',
            'magic_link', 'jwt_refresh', 'agent_spawn'
        )),
        revoked_at       REAL
    );
    CREATE INDEX IF NOT EXISTS idx_auth_sessions_sub_active ON auth_sessions(
        sub, actor_type, last_seen_at DESC, jti, ip_hash, ua_hash,
        location_summary, device_summary, created_via, issued_at
    ) WHERE revoked_at IS NULL;
"""


def create_schema(sqlite_path: str | os.PathLike[str]) -> None:
    """Retain the historical schema utility; NOT a runtime migration guarantee."""
    with closing(sqlite3.connect(sqlite_path)) as conn:
        conn.executescript(_SCHEMA_DDL)


def _create_staging_schema(sqlite_path: str | os.PathLike[str]) -> None:
    """Create a staging schema from the actual AuthState and webhook owners."""
    from flinttrade_core.auth_state import _CREATE_SCHEMA_SQL
    from flinttrade_webhooks.webhook_replay import ensure_nonce_schema
    from flinttrade_webhooks.webhook_secret_store import _WEBHOOK_SECRET_SCHEMA

    with closing(sqlite3.connect(sqlite_path)) as conn:
        conn.executescript(_CREATE_SCHEMA_SQL)
        conn.executescript(_WEBHOOK_SECRET_SCHEMA)
        ensure_nonce_schema(conn)


def _read_master_password(args: argparse.Namespace) -> str:
    if args.master_password_fd is not None:
        with os.fdopen(args.master_password_fd, "r") as stream:
            password = stream.readline().rstrip("\n")
    elif sys.stdin.isatty():
        password = getpass.getpass("master password: ")
    else:
        raise MigrationRefused("master password requires a TTY or --master-password-fd")
    if not password:
        raise MigrationRefused("empty master password")
    return password


def _plaintext(blob: bytes, webhook_id: str, version: int, master_dek: bytes, legacy_key: bytes | None) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.fernet import Fernet, InvalidToken

    from flinttrade_webhooks.webhook_keys import decrypt_webhook_secret

    if not isinstance(blob, bytes) or type(version) is not int or version < 1:
        raise MigrationRefused("invalid webhook ciphertext metadata")
    try:
        return decrypt_webhook_secret(blob, webhook_id, master_dek, version)
    except (InvalidTag, ValueError):
        if legacy_key is None:
            raise MigrationRefused("webhook decryption failed; source retained") from None
    # Normal Fernet tokens are base64, not a leading raw 0x80 byte.
    token = base64.urlsafe_b64encode(blob) if blob[:1] == b"\x80" else blob
    try:
        return Fernet(legacy_key).decrypt(token)
    except (InvalidToken, ValueError):
        raise MigrationRefused("webhook decryption failed; source retained") from None


def _transcode_webhook_secrets(sqlite_path: Path, legacy_fernet_key: bytes | None, master_password: str) -> int:
    """Authenticate every row and transcode verified Fernet in one transaction."""
    from cryptography.exceptions import InvalidTag

    from flinttrade_webhooks.webhook_keys import decrypt_webhook_secret, encrypt_webhook_secret
    from flinttrade_webhooks.webhook_secret_store import WebhookSecretStore, canonical_webhook_id

    master_dek = WebhookSecretStore._derive_master_dek(master_password)
    updates = []
    with closing(sqlite_connection(sqlite_path)) as conn:
        rows = conn.execute("SELECT webhook_id,path,key_version,secret_encrypted_aes_gcm_siv FROM webhooks").fetchall()
        for webhook_id, path, version, blob in rows:
            if not isinstance(path, str) or not path or canonical_webhook_id(path) != webhook_id:
                raise MigrationRefused("webhook identity/path mismatch")
            plaintext = _plaintext(blob, webhook_id, version, master_dek, legacy_fernet_key)
            plaintext.decode("utf-8")  # actual get_secret contract
            try:
                decrypt_webhook_secret(blob, webhook_id, master_dek, version)
            except (InvalidTag, ValueError):
                encrypted = encrypt_webhook_secret(plaintext, webhook_id, master_dek, version)
                if decrypt_webhook_secret(encrypted, webhook_id, master_dek, version) != plaintext:
                    raise MigrationRefused("webhook transcode verification failed")
                updates.append((encrypted, webhook_id))
        # Do not reset versions, identities or rotation times during transcoding.
        with conn:
            conn.executemany("UPDATE webhooks SET secret_encrypted_aes_gcm_siv=? WHERE webhook_id=?", updates)
    return len(updates)


def _archive_legacy(source: Path | None, archive: Path, expected: str | None, master_password: str) -> None:
    """Verify a durable real AGE archive before the coordinator unlinks source."""
    from pyrage import passphrase

    if source is not None and file_digest(source) != expected:
        raise MigrationRefused("source changed before encrypted archival")
    require_regular(archive)
    temporary = archive.with_name(archive.name + ".tmp")
    require_regular(temporary)

    def verify(path: Path) -> None:
        if hashlib.sha256(passphrase.decrypt(path.read_bytes(), master_password)).hexdigest() != expected:
            raise MigrationRefused("encrypted archive does not match original")

    if temporary.exists():
        # Interrupted encryption is evidence, not permission to truncate a
        # possibly unrelated archive. Reuse only an authenticated exact copy.
        verify(temporary)
    if not archive.exists():
        if not temporary.exists():
            if source is None:
                raise MigrationRefused("source and archive both missing")
            payload = source.read_bytes()
            encrypted = passphrase.encrypt(payload, master_password)
            if passphrase.decrypt(encrypted, master_password) != payload:
                raise MigrationRefused("AGE encryption round-trip failed")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            harden(temporary)
        verify(temporary)
        fsync_file(temporary)
        fsync_directory(temporary.parent)
        publish_noreplace(temporary, archive)
    verify(archive)
    fsync_file(archive)
    fsync_directory(archive.parent)
    if temporary.exists():
        temporary.unlink()
        fsync_directory(archive.parent)


def _source_rows(source: Path | None, target: Path) -> dict[str, tuple[list[str], list[tuple]]]:
    if source is None:
        return {}
    import duckdb

    with duckdb.connect(str(source), read_only=True, config={"threads": 1}) as duck:
        actual = {r[0] for r in duck.execute("SHOW TABLES").fetchall()}
        required, optional = set(_TABLES[:3]), set(_TABLES[3:])
        if not required <= actual or actual - required - optional or (actual & optional not in (set(), optional)):
            raise MigrationRefused("unsupported/incomplete auth schema; no tables may be discarded")
        if duck.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema <> 'main' "
                        "OR table_type <> 'BASE TABLE'").fetchone()[0]:
            raise MigrationRefused("unsupported auth source objects")
        result = {}
        with closing(sqlite_connection(target, readonly=True)) as conn:
            for table in _TABLES:
                if table not in actual:
                    continue
                info = conn.execute(f"PRAGMA table_info({table})").fetchall()
                columns = [r[1] for r in info]
                if {r[0] for r in duck.execute(f"DESCRIBE {table}").fetchall()} != set(columns):
                    raise MigrationRefused("auth column set mismatch; no fields may be discarded")
                affinities = {"VARCHAR": "TEXT", "DOUBLE": "REAL"}
                rows = duck.execute(f"SELECT {','.join(columns)} FROM {table}").fetchall()
                converted = [tuple(sqlite_value(value, affinities.get(info[i][2], info[i][2]))
                                   for i, value in enumerate(row)) for row in rows]
                if any(row[i] is None and (col[3] or col[5]) for row in converted for i, col in enumerate(info)):
                    raise MigrationRefused("null auth key or required value")
                result[table] = (columns, converted)
        return result


def _validate_rows(source: Path | None, target: Path, password: str | None, legacy_key: bytes | None) -> None:
    from flinttrade_webhooks.webhook_secret_store import WebhookSecretStore

    tables = _source_rows(source, target)
    database_digest(target)
    with closing(sqlite_connection(target, readonly=True)) as conn:
        for table in _TABLES:
            columns, rows = tables.get(table, ([], []))
            actual = conn.execute(f"SELECT {','.join(columns) if columns else '*'} FROM {table}").fetchall()
            if table == "webhooks" and rows:
                master_dek = WebhookSecretStore._derive_master_dek(password)
                def plaintext_rows(values, key, columns=columns, master_dek=master_dek):
                    converted = []
                    for value in values:
                        value = list(value)
                        i = columns.index("secret_encrypted_aes_gcm_siv")
                        value[i] = _plaintext(value[i], value[columns.index("webhook_id")],
                                              value[columns.index("key_version")], master_dek, key)
                        converted.append(tuple(value))
                    return converted
                rows, actual = plaintext_rows(rows, legacy_key), plaintext_rows(actual, None)
            if rows_digest(actual) != rows_digest(rows):
                raise MigrationRefused("auth data/crypto relationship mismatch")


def _validate_current_readers(target: Path, password: str | None) -> None:
    from flinttrade_core.auth_state import AuthState, _default_db_path
    from flinttrade_webhooks.webhook_secret_store import WebhookSecretStore

    if _default_db_path().name != "auth_state.sqlite":
        raise MigrationRefused("auth_state_reader_cutover_required; active DuckDB authority retained")
    # Constructors can perform expiry GC. Test a backup, never change the stage.
    probe = target.with_name("reader-probe.sqlite")
    require_regular(probe)
    probe.unlink(missing_ok=True)
    with closing(sqlite_connection(target, readonly=True)) as conn, closing(sqlite3.connect(probe)) as copy:
        conn.backup(copy)
        jtis = conn.execute("SELECT jti FROM revoked_jtis").fetchall()
        hooks = conn.execute("SELECT path,webhook_id,key_version,secret_encrypted_aes_gcm_siv FROM webhooks").fetchall()
    try:
        reader = AuthState(probe)
        try:
            if not all(reader.is_jti_revoked(row[0]) for row in jtis):
                raise MigrationRefused("current AuthState reader lost revocation")
        finally:
            reader.close()
        if hooks:
            store = WebhookSecretStore(probe, password)
            for path, webhook_id, version, blob in hooks:
                if store.get_secret(path).encode() != _plaintext(blob, webhook_id, version, store._master_dek, None):
                    raise MigrationRefused("current webhook reader mismatch")
    finally:
        for suffix in ("", "-wal", "-shm"):
            probe.with_name(probe.name + suffix).unlink(missing_ok=True)


def migrate(workspace: Path, args: argparse.Namespace) -> int:
    """Stage exact authority; publish only after real reader and crypto parity."""
    password, legacy_key = None, None

    def credentials():
        nonlocal password, legacy_key
        if password is None:
            password = _read_master_password(args)
            if args.legacy_fernet_key_path:
                key_path = Path(args.legacy_fernet_key_path)
                require_regular(key_path)
                legacy_key = key_path.read_bytes()
        return password

    def build(source, target):
        if args.accept_unknown_tables:
            raise MigrationRefused("discarding unknown auth tables is not supported")
        _create_staging_schema(target)
        tables = _source_rows(source, target)
        with closing(sqlite_connection(target)) as conn:
            conn.execute("PRAGMA synchronous=FULL")
            with conn:
                for table, (columns, rows) in tables.items():
                    conn.executemany(f"INSERT INTO {table} ({','.join(columns)}) VALUES "
                                     f"({','.join('?' for _ in columns)})", rows)
        if tables.get("webhooks", ([], []))[1]:
            credentials()
            _transcode_webhook_secrets(target, legacy_key, password)
        record_webhook_selection(workspace, target)

    def validate(source, target):
        if source is not None:
            credentials()
        _validate_rows(source, target, password, legacy_key)
        _validate_current_readers(target, password)
        validate_staged_selection(workspace, target)
        if source is not None:
            from pyrage import passphrase

            # Import and check actual crypto BEFORE publication, not afterwards.
            if not callable(passphrase.encrypt) or not callable(passphrase.decrypt):
                raise MigrationRefused("incompatible pyrage dependency")
            credentials()

    def archive(source, target, expected):
        validate_staged_selection(workspace, workspace / "auth_state.sqlite")
        _archive_legacy(source, target, expected, credentials())

    with ExitStack() as fences:
        standalone = workspace / "webhook_secrets.db"
        require_regular(standalone)
        if standalone.exists():
            # Exclude standalone SQLite writers too, without changing their
            # schema, credentials, nonces or journal mode.
            fence = fences.enter_context(closing(sqlite_connection(standalone)))
            fence.execute("BEGIN IMMEDIATE")
        migrate_database(workspace, source_name="auth_state.duckdb", destination_name="auth_state.sqlite",
                         build=build, validate=validate, archive_codec=archive, archive_suffix=".age")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=None)
    parser.add_argument("--master-password-fd", type=int, default=None)
    parser.add_argument("--accept-unknown-tables", action="store_true", help="Retired: unknown data is never discarded")
    parser.add_argument("--legacy-fernet-key-path", type=str, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.CRITICAL)
    try:
        migrate(args.workspace if args.workspace is not None else workspace_dir(), args)
    except ArchivePending:
        print("published/archive-pending: destination retained; rerun to resume encrypted archival")
        return 3
    except Exception as exc:
        code = "auth_state_reader_cutover_required" if isinstance(exc, MigrationRefused) and str(exc).startswith(
            "auth_state_reader_cutover_required") else type(exc).__name__
        print(f"migration refused ({code}); originals retained; reconcile source/dependencies")
        return 2
    print("auth migration complete; destination and encrypted archive verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
