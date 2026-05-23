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
    for rel_path in _PY_PACKAGE_SRCS:
        src = str(_REPO_ROOT / rel_path)
        if src not in sys.path:
            sys.path.append(src)


def _isolate_workspace() -> None:
    if os.environ.get("FLINTTRADE_WORKSPACE_DIR"):
        return
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    base = Path(tempfile.gettempdir()) / "flinttrade-pytest" / worker
    base.mkdir(parents=True, exist_ok=True)
    os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(base)


_isolate_workspace()
_install_local_package_paths()
