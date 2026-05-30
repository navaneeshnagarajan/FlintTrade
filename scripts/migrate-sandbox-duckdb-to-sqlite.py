#!/usr/bin/env python3
"""Migrate legacy ``sandbox.duckdb`` → ``sandbox/state.sqlite`` (data-layer §9.1).

Smaller analogue of the §5 auth_state migration. Native sandbox state is
recreatable (the EOD reset wipes positions anyway) and contains no secrets, so
this copies the legacy ``sandbox_capital`` / ``sandbox_orders`` /
``sandbox_positions`` rows by column-name intersection into the canonical §9.2
schema, then archives the legacy DuckDB (never deletes in plaintext). The new
``pnl`` / ``mtm`` tables start empty.

``duckdb`` is imported lazily (migration-only, ``migration`` extra), so a fresh
install with no legacy file never needs it.

Usage:
    python scripts/migrate-sandbox-duckdb-to-sqlite.py [--workspace ~/.flinttrade]
"""

from __future__ import annotations

import argparse
import logging
import sys
from contextlib import closing
from pathlib import Path

from flinttrade_core.db import open_sqlite
from flinttrade_data.state_store import ensure_schema, init_capital

logger = logging.getLogger("migrate_sandbox")

# legacy DuckDB table → canonical SQLite table
_TABLE_MAP = {
    "sandbox_capital": "capital",
    "sandbox_orders": "orders",
    "sandbox_positions": "positions",
}


def _copy_table(duck, dst_conn, legacy: str, target: str) -> int:
    src_cols = [c[0] for c in duck.execute(f"DESCRIBE {legacy}").fetchall()]
    dst_cols = [c[1] for c in dst_conn.execute(f"PRAGMA table_info({target})").fetchall()]
    shared = [c for c in src_cols if c in dst_cols]
    if not shared:
        return 0
    rows = duck.execute(f"SELECT {', '.join(shared)} FROM {legacy}").fetchall()
    if not rows:
        return 0
    placeholders = ",".join("?" for _ in shared)
    dst_conn.executemany(
        f"INSERT OR REPLACE INTO {target} ({', '.join(shared)}) VALUES ({placeholders})", rows
    )
    return len(rows)


def migrate(workspace: Path) -> int:
    legacy = workspace / "data" / "sandbox.duckdb"
    state_path = workspace / "sandbox" / "state.sqlite"
    state_path.parent.mkdir(parents=True, exist_ok=True)

    if state_path.exists():
        logger.info("sandbox/state.sqlite already exists; migration already complete")
        return 0

    with closing(open_sqlite(str(state_path), durability="normal")) as conn:
        ensure_schema(conn)
        init_capital(conn, 1_000_000.0)
        if not legacy.exists():
            logger.info("no legacy sandbox.duckdb; created fresh state.sqlite schema")
            return 0
        try:
            import duckdb  # noqa: PLC0415
        except ModuleNotFoundError:  # pragma: no cover - env-dependent
            sys.exit("migration requires the 'migration' extra (duckdb missing); uv sync --extra migration")
        duck = duckdb.connect(str(legacy), read_only=True)
        try:
            present = {r[0] for r in duck.execute("SHOW TABLES").fetchall()}
            for legacy_tbl, target in _TABLE_MAP.items():
                if legacy_tbl in present:
                    n = _copy_table(duck, conn, legacy_tbl, target)
                    logger.info("copied %s → %s (%d rows)", legacy_tbl, target, n)
        finally:
            duck.close()

    archive = workspace / "archive" / "migrations"
    archive.mkdir(parents=True, exist_ok=True)
    legacy.replace(archive / legacy.name)
    logger.info("archived legacy sandbox.duckdb to %s", archive / legacy.name)
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=str(Path.home() / ".flinttrade"))
    args = parser.parse_args()
    return migrate(Path(args.workspace))


if __name__ == "__main__":
    raise SystemExit(main())
