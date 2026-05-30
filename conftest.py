"""Root-level pytest configuration.

Sole purpose right now: isolate the FlintTrade workspace per pytest worker
so DuckDB / SQLite write locks on `~/.flinttrade/*.db` do not collide when
the suite runs in parallel under pytest-xdist.

The mechanism:
  * `flinttrade_core.workspace.workspace_dir()` honours the env var
    `FLINTTRADE_WORKSPACE_DIR` if it is set, otherwise it falls back to
    `~/.flinttrade`.
  * pytest-xdist exposes the worker id (e.g. "gw0", "gw1", "master") via
    `PYTEST_XDIST_WORKER`. We use that to give each worker a unique tmp
    directory under the system temp.
  * This module is imported by pytest *before* any test module, so the env
    var is set before `auth_service.py`, `app.py`, etc. resolve their
    module-level DB-path constants.

Why module-level (not `pytest_configure`):
  several singletons in `packages/core/core/src/app.py` and `auth_service.py`
  capture the path at import time. If we deferred to a hook, they would
  already have grabbed the wrong path.

Override:
  set `FLINTTRADE_WORKSPACE_DIR` in your environment before running pytest
  to point the suite at any directory you choose; this module will not
  overwrite a user-supplied value.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent
_PY_PACKAGE_SRCS = [
    "packages/core/core/src",
    "packages/core/data/src",
    "packages/core/historical/src",
    "packages/core/indicators/src",
    "packages/services/backtest/src",
    "packages/services/engine/src",
    "packages/services/screener/src",
    "packages/services/journal/src",
    "packages/services/ai/src",
    "packages/services/ditto/src",
    "packages/services/automation/src",
    "packages/integrations/gateway/src",
    "packages/integrations/webhooks/src",
]


def _install_local_package_paths() -> None:
    # Repo root first so `import tests.mocks` (the Identity H9 default-mock package,
    # sub-spec §14.2) resolves consistently under --import-mode=importlib.
    root = str(_REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    for rel_path in _PY_PACKAGE_SRCS:
        src = str(_REPO_ROOT / rel_path)
        if src not in sys.path:
            sys.path.append(src)


# DBs whose on-disk engine changed DuckDB→SQLite. A persistent test workspace
# reused across the migration may still hold the legacy DuckDB file, which
# open_sqlite cannot read — wipe these scratch files so the SQLite code recreates
# them. Only ever touches the throw-away pytest workspace.
_MIGRATED_SCRATCH_DBS = ("activity.db", "security.db")

# Master password no longer auto-generates (locked decision #13: getpass/fd only).
# Seed a hardened-equivalent file so app-creating tests don't block on a TTY prompt.
_TEST_MASTER_PASSWORD = "pytest-master-password"


def _clean_legacy_scratch_dbs(base: Path) -> None:
    for name in _MIGRATED_SCRATCH_DBS:
        for path in (base / name, base / f"{name}-wal", base / f"{name}-shm"):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass


def _seed_test_master_password(base: Path) -> None:
    pw_file = base / "master_password"
    try:
        if not pw_file.exists():
            pw_file.write_text(_TEST_MASTER_PASSWORD)
    except OSError:
        pass


def _isolate_workspace() -> None:
    # Under xdist each worker MUST get its own dir even when the controller
    # already exported FLINTTRADE_WORKSPACE_DIR (workers inherit it) — otherwise
    # all workers share one dir and collide on the still-DuckDB engine
    # SandboxEngine / traffic / error logs. PYTEST_XDIST_WORKER is set per worker
    # (gw0, gw1, …) and absent in the controller / serial runs. A user-supplied
    # FLINTTRADE_WORKSPACE_DIR (no xdist) is still respected.
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    existing = os.environ.get("FLINTTRADE_WORKSPACE_DIR")
    if worker:
        base = Path(tempfile.gettempdir()) / "flinttrade-pytest" / worker
    elif existing:
        base = Path(existing)
    else:
        base = Path(tempfile.gettempdir()) / "flinttrade-pytest" / "main"
    base.mkdir(parents=True, exist_ok=True)
    os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(base)
    _clean_legacy_scratch_dbs(base)
    _seed_test_master_password(base)


_isolate_workspace()
_install_local_package_paths()
