#!/usr/bin/env python3
"""Migrate a legacy DuckDB trade journal to the SQLite + FTS5 ``journal.sqlite``.

The annotated :class:`~flinttrade_journal.trade_journal.TradeJournal` moved from
a DuckDB ``journal_entries`` table to its own SQLite database (see G31). This
script creates the new schema and, if a legacy DuckDB journal exists, copies
every row through the class itself — so tags and the FTS index are populated
exactly as a live write would, rather than a hand-rolled column copy that could
drift from the model. The legacy file is archived (never deleted in place).

Idempotent: re-running when ``journal.sqlite`` already exists is a no-op.
``duckdb`` is imported lazily (migration-only), so a fresh install with no
legacy file never needs it.

Usage:
    python scripts/migrate-journal-duckdb-to-sqlite.py [--workspace ~/.flinttrade]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from flinttrade_journal.trade_journal import JournalEntry, TradeJournal

logger = logging.getLogger("migrate_journal")

# Legacy DuckDB journal columns → JournalEntry fields. The legacy table used the
# same field names, so this is an identity map for the columns that exist.
_FIELDS = [
    "id", "symbol", "exchange", "side", "quantity", "entry_price", "exit_price",
    "entry_time", "exit_time", "strategy", "tags", "notes", "screenshot_path",
    "emotion_before", "emotion_after", "setup_quality", "execution_quality",
    "pnl", "pnl_pct", "risk_reward_ratio", "created_at", "updated_at",
]


def _legacy_rows(legacy: Path) -> list[dict]:
    """Read journal_entries rows from a legacy DuckDB file, or [] if absent."""
    if not legacy.exists():
        return []
    try:
        import duckdb  # noqa: PLC0415
    except ModuleNotFoundError:
        sys.exit("migration requires the 'migration' extra (duckdb missing); uv sync --extra migration")
    conn = duckdb.connect(str(legacy), read_only=True)
    try:
        tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
        if "journal_entries" not in tables:
            return []
        present = [c[0] for c in conn.execute("DESCRIBE journal_entries").fetchall()]
        cols = [c for c in _FIELDS if c in present]
        rows = conn.execute(f"SELECT {', '.join(cols)} FROM journal_entries").fetchall()
        return [dict(zip(cols, row, strict=False)) for row in rows]
    finally:
        conn.close()


def migrate(workspace: Path) -> Path:
    """Create journal.sqlite and copy any legacy DuckDB journal rows into it."""
    workspace.mkdir(parents=True, exist_ok=True)
    dst = workspace / "journal.sqlite"
    if dst.exists():
        logger.info("journal.sqlite already exists; migration already complete")
        return dst

    journal = TradeJournal(str(dst))
    journal.initialise()
    copied = 0
    for row in _legacy_rows(workspace / "journal.db"):
        tags_raw = row.get("tags")
        if isinstance(tags_raw, str) and tags_raw:
            import json  # noqa: PLC0415

            try:
                row["tags"] = json.loads(tags_raw)
            except json.JSONDecodeError:
                row["tags"] = [t.strip() for t in tags_raw.split(",") if t.strip()]
        journal.add_entry(JournalEntry.model_validate(row))
        copied += 1
    journal.close()
    logger.info("journal migration complete: %d legacy rows copied", copied)

    legacy = workspace / "journal.db"
    if legacy.exists():
        archive = workspace / "archive" / "migrations"
        archive.mkdir(parents=True, exist_ok=True)
        legacy.replace(archive / legacy.name)
        logger.info("archived legacy journal.db to %s", archive / legacy.name)
    return dst


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path.home() / ".flinttrade")
    args = parser.parse_args()
    print(migrate(args.workspace))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
