#!/usr/bin/env python3
"""Offline DuckDB journal migration with verified, resumable publication.

All source columns/rows are checked, not silently filtered through defaults.
SQLite nulls and stored P&L are preserved; the current reader, tag normalisation
and FTS triggers validate the new database before it becomes public. A failed
archive returns 3 (published/archive-pending), never completed or a fresh start.
"""
from __future__ import annotations

import argparse
import logging
import re
from contextlib import closing
from pathlib import Path

from flinttrade_core.legacy_sqlite_migration import (
    ArchivePending,
    MigrationRefused,
    database_digest,
    migrate_database,
    rows_digest,
    sqlite_connection,
    sqlite_value,
)
from flinttrade_core.workspace import workspace_dir
from flinttrade_journal.trade_journal import TradeJournal, _coerce_timestamp

_TABLES = ("journal_entries", "daily_notes", "journal_screenshots")


def _legacy_rows(source: Path | None, target: Path) -> dict[str, tuple[list[str], list[tuple]]]:
    if source is None:
        return {}
    import duckdb  # noqa: PLC0415 -- migration only; absence is an error, never success

    with duckdb.connect(str(source), read_only=True, config={"threads": 1}) as duck:
        tables = {r[0] for r in duck.execute("SHOW TABLES").fetchall()}
        if "journal_entries" not in tables or tables - set(_TABLES):
            raise MigrationRefused("unsupported or incomplete journal source schema")
        # Views and non-main schemas could otherwise hide data from SHOW TABLES.
        if duck.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema <> 'main' "
                        "OR table_type <> 'BASE TABLE'").fetchone()[0]:
            raise MigrationRefused("unsupported journal source objects")
        result = {}
        with closing(sqlite_connection(target, readonly=True)) as conn:
            for table in _TABLES:
                if table not in tables:
                    continue
                info = conn.execute(f"PRAGMA table_info({table})").fetchall()
                columns = [r[1] for r in info]
                description = duck.execute(f"DESCRIBE {table}").fetchall()
                if {r[0] for r in description} != set(columns):
                    raise MigrationRefused("journal column set mismatch")
                if any(r[1] in {"TIMESTAMP_NS", "TIMESTAMP_S", "TIMESTAMP_MS"} for r in description):
                    raise MigrationRefused("unsupported journal timestamp precision")
                rows = duck.execute(f"SELECT {','.join(columns)} FROM {table}").fetchall()
                converted = [tuple(sqlite_value(value, info[i][2]) for i, value in enumerate(row)) for row in rows]
                for row in converted:
                    if any(row[i] is None and (col[3] or col[5]) for i, col in enumerate(info)):
                        raise MigrationRefused("null journal key or required value")
                    if table == "journal_entries":
                        for name in ("entry_time", "exit_time", "created_at", "updated_at"):
                            value = row[columns.index(name)]
                            if value is not None and (
                                _coerce_timestamp(value) is None or re.search(r"[.,]\d{7,}", value)
                            ):
                                raise MigrationRefused("journal timestamp cannot be represented by current reader")
                result[table] = (columns, converted)
        return result


def _build(source: Path | None, target: Path) -> None:
    with TradeJournal(target) as journal:
        journal.initialise()
    tables = _legacy_rows(source, target)
    with closing(sqlite_connection(target)) as conn:
        conn.execute("PRAGMA synchronous=FULL")
        with conn:
            for table, (columns, rows) in tables.items():
                conn.executemany(f"INSERT INTO {table} ({','.join(columns)}) VALUES "
                                 f"({','.join('?' for _ in columns)})", rows)
    # Preserve stored values (including NULL P&L and tags); add_entry would
    # recompute P&L and normalise NULL tags to a different stored value.
    with closing(sqlite_connection(target)) as conn, TradeJournal(target) as journal:
        with conn:
            for (entry_id,) in conn.execute("SELECT id FROM journal_entries").fetchall():
                entry = journal.get_entry(entry_id)
                if entry is None:
                    raise MigrationRefused("journal reader lost an entry")
                conn.executemany("INSERT INTO journal_tags VALUES (?, ?)",
                                 [(entry_id, tag) for tag in set(entry.tags) if tag])


def _validate(source: Path | None, target: Path) -> None:
    expected = _legacy_rows(source, target)
    database_digest(target)  # full SQLite integrity and foreign-key checks
    with closing(sqlite_connection(target, readonly=True)) as conn, TradeJournal(target) as journal:
        for table in _TABLES:
            columns, rows = expected.get(table, ([], []))
            actual = conn.execute(f"SELECT {','.join(columns) if columns else '*'} FROM {table}").fetchall()
            if rows_digest(actual) != rows_digest(rows):
                raise MigrationRefused("journal data mismatch")
        tag_rows = []
        for row in conn.execute("SELECT id,side,setup_quality,execution_quality FROM journal_entries"):
            entry = journal.get_entry(row[0])
            if entry is None or (entry.side, entry.setup_quality, entry.execution_quality) != tuple(row[1:]):
                raise MigrationRefused("journal reader normalises invalid source values")
            tag_rows.extend((entry.id, tag) for tag in set(entry.tags) if tag)
        if rows_digest(conn.execute("SELECT entry_id,tag FROM journal_tags").fetchall()) != rows_digest(tag_rows):
            raise MigrationRefused("journal tag relationships mismatch")
        fts = conn.execute("SELECT rowid,id,symbol,notes,tags,strategy FROM journal_fts").fetchall()
        expected_fts = conn.execute("SELECT rowid,id,symbol,COALESCE(notes,''),COALESCE(tags,''),"
                                    "COALESCE(strategy,'') FROM journal_entries").fetchall()
        if rows_digest(fts) != rows_digest(expected_fts):
            raise MigrationRefused("journal search index mismatch")


def migrate(workspace: Path) -> Path:
    """Migrate under exclusive backend maintenance, retaining every source byte."""
    return migrate_database(workspace, source_name="journal.db", destination_name="journal.sqlite",
                            build=_build, validate=_validate)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=None)
    args = parser.parse_args()
    # Library errors can carry row contents. Never emit raw exceptions/tracebacks.
    logging.basicConfig(level=logging.CRITICAL)
    try:
        migrate(args.workspace if args.workspace is not None else workspace_dir())
    except ArchivePending:
        print("published/archive-pending: destination retained; rerun to resume archival")
        return 3
    except Exception as exc:
        print(f"migration refused ({type(exc).__name__}); originals retained; reconcile source/dependencies")
        return 2
    print("journal migration complete; destination and archive verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
