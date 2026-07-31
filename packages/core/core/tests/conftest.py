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

_SCRATCH_MODULE_NAME = "_flinttrade_scratch_workspace"


def _scratch_workspace():
    """Return the shared scratch-workspace finaliser module.

    Loaded by path under a private ``sys.modules`` name rather than imported as
    ``tests.scratch_workspace``: a per-package run binds ``tests`` to *this*
    package's tests directory, which shadows the repo-root ``tests`` package. The
    private name keeps exactly one registry per process, shared by every conftest
    that creates a scratch workspace.

    Returns:
        The loaded ``tests/scratch_workspace.py`` module.
    """
    import importlib.util

    module = sys.modules.get(_SCRATCH_MODULE_NAME)
    if module is None:
        spec = importlib.util.spec_from_file_location(
            _SCRATCH_MODULE_NAME,
            _REPO_ROOT / "tests" / "scratch_workspace.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[_SCRATCH_MODULE_NAME] = module
        spec.loader.exec_module(module)
    return module


# The constant every seeded workspace's master_password file carries. The
# per-module fixture below also pins the process cache to it so the password an
# app encrypts under always matches the file beside its stores.
_TEST_MASTER_PASSWORD = "pytest-master-password"

# One workspace per process. A per-package run (uv run pytest
# packages/core/core/tests …) resolves rootdir to THIS package, so the repo-root
# conftest is above --confcutdir and never loads — this call is what mints,
# seeds and env-pins the workspace then. In a full-suite run the root conftest
# got there first and acquire_workspace() hands back the directory it already
# minted, rather than this conftest minting a second one and quietly re-pointing
# FLINTTRADE_WORKSPACE_DIR at it.
_scratch_workspace().acquire_workspace()


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    """Release the scratch workspaces this run created.

    Registered here as well as in the repo-root conftest because a per-package
    run resolves rootdir to this package and never loads that one.
    """
    scratch = _scratch_workspace()
    scratch.release_all()
    scratch.sweep_stale()


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
    password that ``seed_master_password`` wrote beside the store.
    """
    import flinttrade_core.app as app_mod

    scratch = _scratch_workspace()
    # This process's one workspace, not whatever FLINTTRADE_WORKSPACE_DIR
    # happens to say: reading the env var made the module subdirectory hang off
    # a value another fixture could have moved, and made teardown restore that
    # same accident. The base is a mkdtemp, NOT a deterministic path — a stable
    # directory would be reused by every later suite invocation, and stale
    # encrypted stores under yesterday's master password fail with InvalidTag
    # (see 82d7e17f, which removed the same reusable-path pattern).
    base = scratch.acquire_workspace()
    mod_dir = base / Path(request.module.__file__).stem
    mod_dir.mkdir(parents=True, exist_ok=True)
    scratch.clean_legacy_scratch_dbs(mod_dir)
    scratch.seed_master_password(mod_dir)
    os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(mod_dir)
    prev_cached_pw = app_mod._MASTER_PASSWORD
    app_mod._MASTER_PASSWORD = _TEST_MASTER_PASSWORD
    yield
    app_mod._MASTER_PASSWORD = prev_cached_pw
    os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(base)
