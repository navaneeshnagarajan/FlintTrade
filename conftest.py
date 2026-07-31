"""Root-level pytest configuration.

Sole purpose right now: isolate the FlintTrade workspace per pytest worker
so DuckDB / SQLite write locks on `~/.flinttrade/*.db` do not collide when
the suite runs in parallel under pytest-xdist.

The mechanism:
  * `flinttrade_core.workspace.workspace_dir()` honours the env var
    `FLINTTRADE_WORKSPACE_DIR` if it is set, otherwise it falls back to
    `~/.flinttrade`.
  * pytest-xdist exposes the worker id (e.g. "gw0", "gw1", "master") via
    `PYTEST_XDIST_WORKER`. We use that to give each worker a fresh tmp
    directory for every pytest process.
  * This module is imported by pytest *before* any test module, so the env
    var is set before `auth_service.py`, `app.py`, etc. resolve their
    module-level DB-path constants.
  * The minting itself lives in `tests/scratch_workspace.py` because two
    package conftests need the same thing and a per-package run never loads
    this file. `acquire_workspace()` is memoised per process, so whichever of
    the three gets there first owns the directory and the others adopt it.

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
from pathlib import Path


def pytest_configure(config) -> None:
    """Snapshot CI env before collection-time test imports mutate os.environ."""
    config._flinttrade_ci_env_at_start = dict(os.environ)


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    """Release the scratch workspaces this run created.

    Without this the suite left one hardened ``flinttrade-pytest-*`` tree in the
    system temp directory per invocation, each carrying an owner-only protected
    DACL on Windows that ordinary recursive deletes stumble over.

    ``sweep_stale`` then collects the marked workspaces that earlier runs could
    not remove themselves, because an app-building test holds store handles open
    for the whole process lifetime.
    """
    scratch = _scratch_workspace()
    scratch.release_all()
    scratch.sweep_stale()


_REPO_ROOT = Path(__file__).resolve().parent
_SCRATCH_MODULE_NAME = "_flinttrade_scratch_workspace"


def _scratch_workspace():
    """Return the shared scratch-workspace finaliser module.

    Loaded by path under a private ``sys.modules`` name rather than imported as
    ``tests.scratch_workspace``, because a per-package run binds ``tests`` to that
    package's own tests directory. The private name keeps exactly one registry per
    process, shared by this conftest and the per-package ones.

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


_install_local_package_paths()
# One workspace per process, minted, seeded and env-pinned by the shared helper.
# Each of the three conftests that isolate FLINTTRADE_WORKSPACE_DIR used to mint
# its own, so a worker created three and whichever conftest imported last won
# the env var; acquire_workspace() memoises, so the later callers adopt this one.
_scratch_workspace().acquire_workspace()
