"""Shared fixtures for gateway tests.

Also handles the bare-name import shim: historical gateway tests import
modules as top-level (``from registry import BrokerRegistry``) but the
``src`` directory is a proper Python package (``src/__init__.py`` +
relative imports in every module). When pytest is invoked from the repo
root, bare-name imports fail because the src modules' relative imports
(``from .session import BrokerSession``) have no parent package.

This conftest imports every gateway submodule through its package path
first, then aliases the loaded modules back to bare names so the legacy
import style keeps working without edits to every test file.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Import each gateway submodule through its fully-qualified package path
# so relative imports resolve, then alias under the bare name used by
# existing tests. New submodules should be added here when tests pick
# them up as bare imports.
_GATEWAY_MODULES = (
    "models",
    "exceptions",
    "adapter",
    "session",
    "registry",
    "auth",
    "credentials",
    "credentials_rotation",
    "contracts",
    "capabilities",
    "capabilities_routes",
    "rotation_routes",
    "ticker",
    "ws_bridge",
)

for _name in _GATEWAY_MODULES:
    _fq = f"flinttrade_gateway.{_name}"
    if _fq not in sys.modules:
        importlib.import_module(_fq)
    sys.modules.setdefault(_name, sys.modules[_fq])

# ws_proxy/ submodules — same shim, package one level deeper. Tests import
# them as ``from ws_proxy.depth_20 import ...`` instead of the fully
# qualified path.
_WS_PROXY_PKG_FQ = "flinttrade_gateway.ws_proxy"
if _WS_PROXY_PKG_FQ not in sys.modules:
    importlib.import_module(_WS_PROXY_PKG_FQ)
sys.modules.setdefault("ws_proxy", sys.modules[_WS_PROXY_PKG_FQ])
for _name in ("depth_20",):
    _fq = f"{_WS_PROXY_PKG_FQ}.{_name}"
    if _fq not in sys.modules:
        importlib.import_module(_fq)
    sys.modules.setdefault(f"ws_proxy.{_name}", sys.modules[_fq])


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Temporary database path for tests."""
    return tmp_path / "test.db"


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to test fixtures directory."""
    return Path(__file__).parent / "fixtures"
