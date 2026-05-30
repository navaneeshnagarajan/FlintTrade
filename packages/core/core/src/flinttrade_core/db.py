"""SQLite connection helpers for FlintTrade persistent state."""

from __future__ import annotations

import contextlib
import os
import sqlite3
from collections.abc import Iterator
from typing import Literal

DurabilityProfile = Literal["normal", "full"]
TempStoreProfile = Literal["MEMORY", "FILE"]


def open_sqlite(
    path: str | os.PathLike[str],
    *,
    durability: DurabilityProfile = "normal",
    temp_store: TempStoreProfile = "MEMORY",
    cache_size_kb: int = 65_536,
) -> sqlite3.Connection:
    """Open a SQLite connection with FlintTrade WAL pragmas applied."""
    path_str = os.fspath(path)
    conn = sqlite3.connect(
        path_str,
        isolation_level=None,
        check_same_thread=False,
        timeout=10.0,
    )
    sync = "FULL" if durability == "full" else "NORMAL"
    conn.executescript(
        f"""
        PRAGMA journal_mode       = WAL;
        PRAGMA synchronous        = {sync};
        PRAGMA busy_timeout       = 5000;
        PRAGMA foreign_keys       = ON;
        PRAGMA wal_autocheckpoint = 1000;
        PRAGMA temp_store         = {temp_store};
        PRAGMA cache_size         = -{int(cache_size_kb)};
        """
    )
    return conn


@contextlib.contextmanager
def disable_journal_triggers(conn: sqlite3.Connection) -> Iterator[None]:
    """Temporarily drop journal FTS triggers for bulk tag updates."""
    trigger_names = [
        "journal_tag_ai",
        "journal_tag_ad",
        "journal_ai",
        "journal_au_before",
        "journal_au_after",
        "journal_ad",
    ]
    saved_ddl: dict[str, str] = {}
    for name in trigger_names:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND name = ?",
            (name,),
        ).fetchone()
        if row and row[0]:
            saved_ddl[name] = row[0]
            conn.execute(f"DROP TRIGGER IF EXISTS {name}")
    try:
        yield
    finally:
        for ddl in saved_ddl.values():
            conn.execute(ddl)
        has_fts = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='journal_fts'"
        ).fetchone()
        if has_fts:
            conn.execute("INSERT INTO journal_fts(journal_fts) VALUES('rebuild')")


_disable_journal_triggers = disable_journal_triggers
