"""Shared fixtures for packages/core/data tests.

Self-isolating workspace: tests that build the Flask app (e.g. the audit-route
tests) cause ``create_flask_app`` to open ``activity.db`` / ``security.db`` under
the workspace dir during construction. Without an isolated workspace the app
falls back to the operator's real platform data dir — which (a) is wrong to touch
from a test, and (b) after the DuckDB→SQLite migration holds a legacy DuckDB
``activity.db`` that ``open_sqlite`` cannot read. Setting
``FLINTTRADE_WORKSPACE_DIR`` to a per-worker tmp dir (mirroring
``packages/core/core/tests/conftest.py``) makes these tests self-contained
regardless of run order.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# DBs whose on-disk engine changed DuckDB→SQLite. A persistent test workspace
# reused across the migration may still hold the legacy DuckDB file, which
# open_sqlite cannot read. Remove these scratch files so the SQLite code
# recreates them fresh. Only ever touches the throw-away pytest workspace.
_MIGRATED_SCRATCH_DBS = ("activity.db", "security.db")


def _clean_legacy_scratch_dbs(base: Path) -> None:
    for name in _MIGRATED_SCRATCH_DBS:
        for path in (base / name, base / f"{name}-wal", base / f"{name}-shm"):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass  # locked by a concurrent worker — that worker owns cleanup


def _seed_test_master_password(base: Path) -> None:
    # Master password no longer auto-generates (locked #13: getpass/fd only).
    pw_file = base / "master_password"
    try:
        if not pw_file.exists():
            pw_file.write_text("pytest-master-password")
    except OSError:
        pass


def _isolate_workspace() -> None:
    # Under xdist, each worker MUST get its own workspace dir even when the
    # controller already exported FLINTTRADE_WORKSPACE_DIR (workers inherit it).
    # Otherwise all workers share one dir and collide on the still-DuckDB engine
    # SandboxEngine / traffic / error logs ("file is being used by another
    # process"). PYTEST_XDIST_WORKER is set in worker subprocesses (gw0, gw1, …)
    # and absent in the controller / serial runs.
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    existing = os.environ.get("FLINTTRADE_WORKSPACE_DIR")
    if worker:
        # mkdtemp, NOT a deterministic per-worker path: a stable directory is
        # reused by every subsequent suite invocation, so encrypted stores
        # (webhook_secrets.db) written under one run's cached master password
        # poison later runs with InvalidTag failures. A fresh dir per run also
        # mirrors core/core's conftest, which this override used to defeat.
        base = Path(tempfile.mkdtemp(prefix=f"flinttrade-pytest-{worker}-"))
    elif existing:
        _clean_legacy_scratch_dbs(Path(existing))
        return
    else:
        base = Path(tempfile.mkdtemp(prefix="flinttrade-pytest-main-"))
    base.mkdir(parents=True, exist_ok=True)
    os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(base)
    # Per-package runs (uv run pytest packages/core/data/tests …) resolve
    # rootdir to THIS package, so the repo-root conftest's DUCKDB_PATH pin is
    # above --confcutdir and never loads. Pin it here too so the operator's
    # machine-local .env DUCKDB_PATH cannot make parallel workers contend on
    # one real DuckDB file (the recurring trade-store flake). This is the
    # DuckDB-heaviest package; mirrors the root + core/core pins.
    os.environ["DUCKDB_PATH"] = str(base / "data" / "flint.duckdb")
    _clean_legacy_scratch_dbs(base)
    _seed_test_master_password(base)


_isolate_workspace()
