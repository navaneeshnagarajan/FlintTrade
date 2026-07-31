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

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
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


# One workspace per process. A per-package run (uv run pytest
# packages/core/data/tests …) resolves rootdir to THIS package, so the repo-root
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
