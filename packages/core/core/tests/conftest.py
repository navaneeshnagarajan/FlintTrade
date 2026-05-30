"""Shared fixtures for packages/core tests.

The ``AuthState`` singleton persists a DuckDB file at
``~/.flinttrade/auth_state.duckdb`` by default, which causes test
isolation failures: OTP request counts and JWT revocations from one
test leak into the next, flipping rate-limit assertions non-
deterministically.

The autouse fixture below rebinds the singleton to a throw-away
DuckDB under the pytest ``tmp_path`` so every test starts with an
empty state store and finishes without side effects. Tests that want
a custom binding can still call ``reset_singleton_for_tests()`` and
``get_auth_state(db_path=...)`` themselves.
"""

from __future__ import annotations

import sys
import os
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
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

for _rel_path in _PY_PACKAGE_SRCS:
    _src = str(_REPO_ROOT / _rel_path)
    if _src not in sys.path:
        sys.path.append(_src)


# DBs whose on-disk engine changed DuckDB→SQLite (activity_log, security_tracker).
# A persistent test workspace reused across the migration may still hold the
# legacy DuckDB file, which open_sqlite cannot read. Remove these scratch files
# so the SQLite code recreates them fresh. Only touches the pytest workspace.
_MIGRATED_SCRATCH_DBS = ("activity.db", "security.db")


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
    # Master password no longer auto-generates (locked #13: getpass/fd only).
    # Seed a file so app-creating tests don't block on a TTY prompt.
    pw_file = base / "master_password"
    try:
        if not pw_file.exists():
            pw_file.write_text("pytest-master-password")
    except OSError:
        pass


def _isolate_workspace() -> None:
    # Under xdist, each worker MUST get its own workspace dir even when the
    # controller already exported FLINTTRADE_WORKSPACE_DIR (workers inherit it),
    # else all workers share one dir and collide on the still-DuckDB engine
    # SandboxEngine / traffic / error logs. PYTEST_XDIST_WORKER is set per worker
    # (gw0, gw1, …) and absent in the controller / serial runs.
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    existing = os.environ.get("FLINTTRADE_WORKSPACE_DIR")
    if worker:
        base = Path(tempfile.gettempdir()) / "flinttrade-pytest" / worker
    elif existing:
        _clean_legacy_scratch_dbs(Path(existing))
        return
    else:
        base = Path(tempfile.gettempdir()) / "flinttrade-pytest" / "main"
    base.mkdir(parents=True, exist_ok=True)
    os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(base)
    _clean_legacy_scratch_dbs(base)
    _seed_test_master_password(base)


_isolate_workspace()


@pytest.fixture(autouse=True)
def _isolated_auth_state(tmp_path_factory):
    """Point AuthState at a per-test DuckDB so OTP/JWT state is fresh."""
    from flinttrade_core import auth_state as auth_state_mod

    auth_state_mod.reset_singleton_for_tests()
    db_dir = tmp_path_factory.mktemp("auth_state")
    auth_state_mod.get_auth_state(db_path=db_dir / "auth_state.duckdb")
    yield
    auth_state_mod.reset_singleton_for_tests()
