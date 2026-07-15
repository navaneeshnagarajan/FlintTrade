#!/usr/bin/env python3
"""Migrate the retired DuckDB Practice ledger into canonical SQLite.

The source is discovered at the historical engine path
``<workspace>/data/engine-sandbox/default.duckdb``. Older fallback locations
and ``SANDBOX_ENGINE_DB_PATH`` are also recognised. A populated source is only
merged when canonical SQLite has no session state; ambiguous dual-ledger state
is left untouched for explicit operator review.

Usage:
    python scripts/migrate-sandbox-duckdb-to-sqlite.py [--workspace PATH]
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from flinttrade_data.sandbox_migration import (
    LegacySandboxConflict,
    migrate_workspace,
)

logger = logging.getLogger("migrate_sandbox")


def migrate(workspace: Path, legacy_path: Path | None = None) -> int:
    """Run the idempotent workspace migration and return a process status."""
    try:
        results = migrate_workspace(workspace, legacy_path=legacy_path)
    except LegacySandboxConflict as exc:
        logger.error("Sandbox migration stopped: %s", exc)
        return 2
    for result in results:
        logger.info("Sandbox migration: %s", result["status"])
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=str(Path.home() / ".flinttrade"))
    parser.add_argument("--legacy", type=Path)
    args = parser.parse_args()
    return migrate(Path(args.workspace), legacy_path=args.legacy)


if __name__ == "__main__":
    raise SystemExit(main())
