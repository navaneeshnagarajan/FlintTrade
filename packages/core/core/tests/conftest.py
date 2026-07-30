"""Shared fixtures for packages/core tests.

The ``AuthState`` singleton persists a DuckDB file under the active workspace
by default. We still bind it per test because OTP request counts and JWT
revocations are process-wide singleton state; sharing one store across tests
would flip rate-limit assertions non-deterministically.

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


# Persistent scratch DBs must not carry state between independent pytest runs.
# activity/security also changed DuckDB→SQLite and may hold a foreign-format
# file; the emergency journal intentionally survives production restarts but a
# prior simulated kill episode must not poison a later test process.
_MIGRATED_SCRATCH_DBS = ("activity.db", "security.db", "emergency_intents.sqlite")


def _clean_legacy_scratch_dbs(base: Path) -> None:
    for name in _MIGRATED_SCRATCH_DBS:
        for path in (base / name, base / f"{name}-wal", base / f"{name}-shm"):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass


# The constant every seeded workspace's master_password file carries. The
# per-module fixture below also pins the process cache to it so the password an
# app encrypts under always matches the file beside its stores.
_TEST_MASTER_PASSWORD = "pytest-master-password"


def _seed_test_master_password(base: Path) -> None:
    # Master password no longer auto-generates (locked #13: getpass/fd only).
    # Seed a file so app-creating tests don't block on a TTY prompt.
    pw_file = base / "master_password"
    try:
        if not pw_file.exists():
            from flinttrade_core.secure_file import write_secret_text

            write_secret_text(pw_file, _TEST_MASTER_PASSWORD)
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
        base = Path(tempfile.mkdtemp(prefix=f"flinttrade-pytest-{worker}-"))
    elif existing:
        _clean_legacy_scratch_dbs(Path(existing))
        _pin_duckdb_path(Path(existing))
        return
    else:
        base = Path(tempfile.mkdtemp(prefix="flinttrade-pytest-main-"))
    base.mkdir(parents=True, exist_ok=True)
    os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(base)
    _pin_duckdb_path(base)
    _clean_legacy_scratch_dbs(base)
    _seed_test_master_password(base)


def _pin_duckdb_path(base: Path) -> None:
    # The operator's machine-local .env may pin DUCKDB_PATH at a real, shared
    # DuckDB file (a single-writer engine). Full-app constructions on several
    # xdist workers then contend on that one file — the losers boot with
    # TRADE_STORAGE=None and store-wiring tests flake. Pin the variable to a
    # per-worker scratch file FIRST: load_dotenv() never overrides an existing
    # env var, so the .env value cannot leak into test runs.
    os.environ["DUCKDB_PATH"] = str(base / "data" / "flint.duckdb")


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


@pytest.fixture(scope="module", autouse=True)
def _per_module_workspace(request):
    """Give each app-building test module its own persistent-state workspace.

    Also pins the process-global master-password cache to the seeded constant
    for the module's duration. ``flinttrade_core.app._get_master_password``
    caches whichever password the first app-building test happened to resolve
    (several tests seed bespoke passwords in throw-away workspaces), so without
    the pin the password a module's app encrypts with is an accident of xdist
    scheduling. Module workspaces persist across the fixture's re-setups when
    xdist interleaves modules, so a later round decrypting ``webhook_secrets.db``
    rows written by an earlier round under a different cached password fails
    with ``InvalidTag`` (the TestWebhooksManagement 503 flake). Pinning makes
    every round of every core module encrypt and decrypt under the same
    password that ``_seed_test_master_password`` wrote beside the store.
    """
    import flinttrade_core.app as app_mod

    prev = os.environ.get("FLINTTRADE_WORKSPACE_DIR")
    # mkdtemp fallback, NOT a deterministic path: a stable directory would be
    # reused by every later suite invocation, and stale encrypted stores under
    # yesterday's master password fail with InvalidTag (see 82d7e17f, which
    # removed the same reusable-path pattern from the data conftest).
    base = Path(prev) if prev else Path(tempfile.mkdtemp(prefix="flinttrade-pytest-main-"))
    mod_dir = base / Path(request.module.__file__).stem
    mod_dir.mkdir(parents=True, exist_ok=True)
    _clean_legacy_scratch_dbs(mod_dir)
    _seed_test_master_password(mod_dir)
    os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(mod_dir)
    prev_cached_pw = app_mod._MASTER_PASSWORD
    app_mod._MASTER_PASSWORD = _TEST_MASTER_PASSWORD
    yield
    app_mod._MASTER_PASSWORD = prev_cached_pw
    if prev is not None:
        os.environ["FLINTTRADE_WORKSPACE_DIR"] = prev
    else:
        os.environ.pop("FLINTTRADE_WORKSPACE_DIR", None)
