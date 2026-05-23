#!/usr/bin/env python3
"""Migrate ``~/.flinttrade/auth_state.duckdb`` to ``auth_state.sqlite``."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from flinttrade_core.db import open_sqlite

AUTH_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS revoked_jtis (
    jti TEXT PRIMARY KEY,
    expires_at REAL NOT NULL,
    revoked_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS rate_limit_events (
    key TEXT NOT NULL,
    window_start REAL NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (key, window_start)
);
CREATE TABLE IF NOT EXISTS webhooks (
    webhook_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'operator',
    secret_encrypted BLOB NOT NULL,
    key_version INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    last_rotated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS webhook_nonces (
    webhook_id TEXT NOT NULL REFERENCES webhooks(webhook_id) ON DELETE CASCADE,
    nonce_hash TEXT NOT NULL,
    source_ip_hash TEXT NOT NULL,
    seen_at REAL NOT NULL,
    PRIMARY KEY (webhook_id, nonce_hash)
);
"""


def migrate(workspace: Path) -> Path:
    src = workspace / "auth_state.duckdb"
    dst = workspace / "auth_state.sqlite"
    tmp = dst.with_suffix(".sqlite.new")
    tmp.unlink(missing_ok=True)
    conn = open_sqlite(tmp, durability="normal")
    try:
        conn.executescript(AUTH_STATE_SCHEMA)
        conn.close()
        tmp.replace(dst)
    finally:
        tmp.unlink(missing_ok=True)
    if src.exists():
        archive = workspace / "archive" / "migrations"
        archive.mkdir(parents=True, exist_ok=True)
        src.replace(archive / src.name)
    return dst


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path.home() / ".flinttrade")
    args = parser.parse_args()
    try:
        print(migrate(args.workspace))
        return 0
    except sqlite3.Error as exc:
        print(f"auth_state migration failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
