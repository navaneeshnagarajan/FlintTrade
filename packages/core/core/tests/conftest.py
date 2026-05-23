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


def _isolate_workspace() -> None:
    if os.environ.get("FLINTTRADE_WORKSPACE_DIR"):
        return
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    base = Path(tempfile.gettempdir()) / "flinttrade-pytest" / worker
    base.mkdir(parents=True, exist_ok=True)
    os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(base)


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
