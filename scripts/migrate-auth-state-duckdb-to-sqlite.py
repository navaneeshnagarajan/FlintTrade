#!/usr/bin/env python3
"""Migrate ``~/.flinttrade/auth_state.duckdb`` → ``auth_state.sqlite`` (data-layer §5.2).

Full Parquet round-trip with BLOB + TIMESTAMP fidelity (DB H4): CSV silently
corrupts microsecond timestamps and base64-truncates BLOBs; Parquet preserves
both natively. Idempotent across restarts — writes to a ``.new`` file and only
atomically renames after every table's row count (and sampled BLOB checksums)
verifies. The legacy DuckDB is age-encrypted and archived (never deleted in
plaintext) only after the rename succeeds (§5.3 crash matrix).

The canonical ``_SCHEMA_DDL`` below is the single source of truth for a fresh
``auth_state.sqlite`` install (it mirrors §7.1's webhooks/nonces shape verbatim);
``create_schema`` is dependency-free so a fresh install never needs DuckDB.

Heavy, migration-only dependencies (``duckdb``, ``pyarrow``, ``pyrage``) are
imported lazily so importing this module — and running ``create_schema`` on a
fresh install — never requires them. Install them with the ``migration`` extra:
``uv sync --extra migration``.

Usage:
    python scripts/migrate-auth-state-duckdb-to-sqlite.py [--workspace ~/.flinttrade]
    # master password: getpass at TTY (default), OR --master-password-fd N.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import logging
import os
import sys
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Sequence

from flinttrade_core.db import open_sqlite

logger = logging.getLogger("migrate_auth_state")

# Tables expected in auth_state.duckdb, with their target durability profile.
_EXPECTED_TABLES: dict[str, str] = {
    "revoked_jtis": "normal",
    "rate_limit_events": "normal",
    "otp_requests": "normal",
    "consent_ledger": "full",
    "agent_runs": "full",
    "webhooks": "full",
    "webhook_nonces": "normal",
    "audit_chain_head": "full",
    "auth_sessions": "normal",
}

# Pre-flight: reject migration upfront if a table uses a DuckDB type SQLite
# cannot represent, rather than losing data silently.
_PRE_FLIGHT_CHECKS: dict[str, str] = {
    "no_interval_columns": (
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE data_type LIKE '%INTERVAL%'"
    ),
    "no_struct_columns": (
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE data_type LIKE '%STRUCT%' OR data_type LIKE '%LIST%' OR data_type LIKE '%MAP%'"
    ),
}

# Per-table BLOB columns for sha256 round-trip verification.
_BLOB_COLUMNS: dict[str, Sequence[str]] = {
    "webhooks": ("secret_encrypted_aes_gcm_siv",),
}

# Canonical auth_state schema (§5 + §7.1). Single source of truth for fresh
# installs and migration targets alike.
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
    """Apply the canonical auth_state schema (dependency-free; fresh-install safe)."""
    with closing(open_sqlite(str(sqlite_path), durability="normal")) as conn:
        conn.executescript(_SCHEMA_DDL)


# ---------------------------------------------------------------------------
# Migration helpers (lazy heavy deps: duckdb / pyarrow / pyrage)
# ---------------------------------------------------------------------------


def _require_migration_deps():
    try:
        import duckdb  # noqa: PLC0415
        import pyarrow.parquet as pq  # noqa: PLC0415
    except ModuleNotFoundError as exc:  # pragma: no cover - env-dependent
        sys.exit(
            f"migration requires the 'migration' extra ({exc.name} missing); "
            "install with: uv sync --extra migration"
        )
    return duckdb, pq


def _read_master_password(args: argparse.Namespace) -> str:
    """Read the master password via getpass (TTY) or --master-password-fd (Security H11).

    NEVER via argv or environment variable — those leak to process listings,
    shell history, CI logs, and tracebacks that dump sys.argv / os.environ.
    """
    if args.master_password_fd is not None:
        with os.fdopen(args.master_password_fd, "r") as fd:
            return fd.readline().rstrip("\n")
    if not sys.stdin.isatty():
        sys.exit("master password input requires a TTY; use --master-password-fd N otherwise")
    return getpass.getpass("master password: ")


def _run_pre_flight(duck, *, accept_unknown_tables: bool = False) -> None:
    for check, sql in _PRE_FLIGHT_CHECKS.items():
        rows = duck.execute(sql).fetchall()
        if rows:
            logger.error("pre-flight %s failed: %s", check, rows)
            sys.exit(f"pre-flight check {check!r} failed; refusing to migrate")
    actual = {row[0] for row in duck.execute("SHOW TABLES").fetchall()}
    unknown = actual - set(_EXPECTED_TABLES) - {"sqlite_sequence", "sqlite_stat1"}
    if unknown and not accept_unknown_tables:
        sys.exit(
            f"refusing to migrate: unknown source tables {sorted(unknown)}; "
            f"rerun with --accept-unknown-tables to proceed"
        )
    if unknown:
        logger.warning("ignoring unknown source tables: %s", sorted(unknown))
    logger.info("pre-flight checks OK")


def _export_to_parquet(duck, table: str, parquet_path: Path) -> int:
    duck.execute(f"COPY (SELECT * FROM {table}) TO '{parquet_path}' (FORMAT PARQUET)")
    src_count = duck.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    logger.info("exported %s (%d rows)", table, src_count)
    return int(src_count)


def _import_from_parquet(sqlite_path: Path, table: str, parquet_path: Path, durability: str) -> int:
    import pyarrow.parquet as pq  # noqa: PLC0415

    rows = pq.read_table(parquet_path).to_pylist()
    with closing(open_sqlite(str(sqlite_path), durability=durability)) as conn:
        if not rows:
            return 0
        cols = list(rows[0].keys())
        placeholders = ",".join("?" for _ in cols)
        conn.executemany(
            f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
            [tuple(row[c] for c in cols) for row in rows],
        )
        return int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def _verify_row_counts(src: int, dst: int, table: str) -> None:
    if src != dst:
        sys.exit(f"row count mismatch on {table}: duckdb={src} sqlite={dst}")
    logger.info("row count OK on %s: %d", table, src)


def _verify_blob_checksums(duck, sqlite_path: Path, table: str, blob_cols: Sequence[str]) -> None:
    sample = duck.execute(f"SELECT * FROM {table} ORDER BY random() LIMIT 3").fetchall()
    duck_cols = [c[0] for c in duck.execute(f"DESCRIBE {table}").fetchall()]
    with closing(open_sqlite(str(sqlite_path), durability="normal")) as sconn:
        for src_row in sample:
            pk_col, pk_val = duck_cols[0], src_row[0]
            dst_row = sconn.execute(f"SELECT * FROM {table} WHERE {pk_col} = ?", (pk_val,)).fetchone()
            assert dst_row is not None, f"missing row in sqlite: {pk_col}={pk_val!r}"
            for col in blob_cols:
                idx = duck_cols.index(col)
                src_hash = hashlib.sha256(src_row[idx]).hexdigest()
                dst_hash = hashlib.sha256(dst_row[idx]).hexdigest()
                if src_hash != dst_hash:
                    sys.exit(f"BLOB checksum mismatch on {table}.{col} pk={pk_val!r}")
            logger.info("BLOB checksum OK on %s pk=%r", table, pk_val)


def _archive_legacy(duck_path: Path, ts: str, master_password: str) -> None:
    """Age-encrypt + archive the legacy DuckDB, then secure-delete the source.

    Atomic (Database H6): write ciphertext to ``.age.tmp`` → fsync → atomic
    rename → fsync parent dir → ONLY THEN overwrite + unlink the source.
    """
    try:
        import age  # noqa: PLC0415
    except ModuleNotFoundError:  # pragma: no cover - env-dependent
        sys.exit("archive requires the 'migration' extra (pyrage missing); uv sync --extra migration")

    archive_dir = Path.home() / ".flinttrade" / "archive" / "migrations" / ts
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{duck_path.name}.age"
    tmp_path = archive_path.with_suffix(archive_path.suffix + ".tmp")

    payload = duck_path.read_bytes()
    encrypted = age.encrypt(payload, passphrase=master_password)

    tmp_path.write_bytes(encrypted)
    tmp_path.chmod(0o600)
    with tmp_path.open("rb") as f:
        os.fsync(f.fileno())
    os.replace(tmp_path, archive_path)
    if hasattr(os, "O_DIRECTORY"):
        dir_fd = os.open(str(archive_dir), os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    logger.info("archived legacy DuckDB to %s (%d bytes)", archive_path, len(encrypted))

    with duck_path.open("r+b") as f:
        f.write(b"\x00" * min(len(payload), 1024 * 1024))
        f.flush()
        os.fsync(f.fileno())
    duck_path.unlink()
    if hasattr(os, "O_DIRECTORY"):
        dir_fd = os.open(str(duck_path.parent), os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def migrate(workspace: Path, args: argparse.Namespace) -> int:
    duck_path = workspace / "auth_state.duckdb"
    sqlite_path = workspace / "auth_state.sqlite"
    new_sqlite_path = workspace / "auth_state.sqlite.new"
    parquet_dir = workspace / ".migration-tmp"

    if not duck_path.exists():
        # Fresh install: nothing to migrate, but ensure the canonical schema exists.
        if not sqlite_path.exists():
            create_schema(sqlite_path)
            logger.info("no auth_state.duckdb; created fresh auth_state.sqlite schema")
        else:
            logger.info("no auth_state.duckdb to migrate; nothing to do")
        return 0
    if sqlite_path.exists():
        logger.info("auth_state.sqlite already exists; migration already complete")
        return 0

    duckdb, _pq = _require_migration_deps()

    master_password = _read_master_password(args)
    if not master_password:
        sys.exit("master password required (empty input rejected)")

    parquet_dir.mkdir(exist_ok=True)
    new_sqlite_path.unlink(missing_ok=True)
    create_schema(new_sqlite_path)

    duck = duckdb.connect(str(duck_path), read_only=True)
    try:
        _run_pre_flight(duck, accept_unknown_tables=args.accept_unknown_tables)
        actual_tables = {row[0] for row in duck.execute("SHOW TABLES").fetchall()}
        for table, durability in _EXPECTED_TABLES.items():
            if table not in actual_tables:
                logger.info("table %s absent in source; skipping", table)
                continue
            pq_path = parquet_dir / f"{table}.parquet"
            src_count = _export_to_parquet(duck, table, pq_path)
            dst_count = _import_from_parquet(new_sqlite_path, table, pq_path, durability)
            _verify_row_counts(src_count, dst_count, table)

        if args.legacy_fernet_key_path:
            _transcode_webhook_secrets(
                new_sqlite_path, Path(args.legacy_fernet_key_path).read_bytes(), master_password
            )

        for table in _EXPECTED_TABLES:
            if table in actual_tables and table in _BLOB_COLUMNS:
                _verify_blob_checksums(duck, new_sqlite_path, table, _BLOB_COLUMNS[table])
    finally:
        duck.close()

    os.replace(new_sqlite_path, sqlite_path)
    if hasattr(os, "O_DIRECTORY"):
        dir_fd = os.open(str(workspace), os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    logger.info("atomic rename: %s → %s", new_sqlite_path, sqlite_path)

    _archive_legacy(duck_path, time.strftime("%Y-%m-%dT%H-%M-%S"), master_password)

    for f in parquet_dir.iterdir():
        f.unlink()
    parquet_dir.rmdir()
    return 0


def _transcode_webhook_secrets(sqlite_path: Path, legacy_fernet_key: bytes, master_password: str) -> int:
    """Re-encrypt legacy Fernet webhook secrets → AES-GCM-SIV (Database M7)."""
    from cryptography.fernet import Fernet, InvalidToken  # noqa: PLC0415

    from flinttrade_core.auth_service import derive_master_dek  # noqa: PLC0415
    from flinttrade_webhooks.webhook_keys import encrypt_webhook_secret  # noqa: PLC0415

    master_dek = derive_master_dek(master_password)
    fernet = Fernet(legacy_fernet_key)
    transcoded = 0
    with closing(open_sqlite(str(sqlite_path), durability="full")) as conn:
        rows = conn.execute("SELECT webhook_id, secret_encrypted_aes_gcm_siv FROM webhooks").fetchall()
        conn.execute("BEGIN")
        try:
            for webhook_id, blob in rows:
                if not blob or blob[0] != 0x80:
                    continue
                try:
                    plaintext = fernet.decrypt(bytes(blob))
                except InvalidToken:
                    logger.warning("webhook %s: Fernet decrypt failed; skipping", webhook_id)
                    continue
                new_blob = encrypt_webhook_secret(plaintext, webhook_id, master_dek)
                conn.execute(
                    "UPDATE webhooks SET secret_encrypted_aes_gcm_siv = ?, dek_id = ?, "
                    "key_version = 1, last_rotated_at = ? WHERE webhook_id = ?",
                    (new_blob, webhook_id, time.time(), webhook_id),
                )
                transcoded += 1
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    logger.info("transcoded %d webhook secrets Fernet → AES-GCM-SIV", transcoded)
    return transcoded


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=str(Path.home() / ".flinttrade"))
    parser.add_argument("--master-password-fd", type=int, default=None)
    parser.add_argument("--accept-unknown-tables", action="store_true")
    parser.add_argument("--legacy-fernet-key-path", type=str, default=None)
    args = parser.parse_args()
    return migrate(Path(args.workspace), args)


if __name__ == "__main__":
    raise SystemExit(main())
