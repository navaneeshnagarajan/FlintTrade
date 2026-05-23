#!/usr/bin/env python3
"""Migrate journal storage to SQLite with FTS/tag tables."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from flinttrade_core.db import open_sqlite

JOURNAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS journal_entries (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty INTEGER NOT NULL,
    price REAL NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS journal_tags (
    entry_id TEXT NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (entry_id, tag)
);
CREATE VIRTUAL TABLE IF NOT EXISTS journal_fts
USING fts5(id UNINDEXED, symbol, notes, tags);
"""


def migrate(workspace: Path) -> Path:
    src = workspace / "journal.db"
    dst = workspace / "journal.sqlite"
    tmp = dst.with_suffix(".sqlite.new")
    tmp.unlink(missing_ok=True)
    conn = open_sqlite(tmp, durability="normal")
    try:
        conn.executescript(JOURNAL_SCHEMA)
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
        print(f"journal migration failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
