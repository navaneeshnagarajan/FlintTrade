"""conftest.py — path bootstrap for backtest-engine tests.

This file is loaded automatically by pytest before any test module in this
directory.  It centralises all sys.path manipulation so individual test files
do not need their own path-insert hacks.

Paths added (in priority order — highest priority last via insert(0)):
  1. repo root          → ``from flinttrade_core.models import …`` etc.
  2. packages/core/core/src  → ``from models import OHLCV``
  3. packages/services/engine/src→ ``from strategy import BaseStrategy``
  4. backtest-engine/src → ``from simulator import …`` (highest priority so
                           its ``strategies`` module wins over engine/src/strategies/)
"""

from __future__ import annotations

import os
import sys

# Absolute path to this conftest (packages/services/backtest/tests/)
_tests_dir = os.path.dirname(os.path.abspath(__file__))
_pkg_dir = os.path.join(_tests_dir, "..")        # packages/services/backtest/
_packages_dir = os.path.join(_pkg_dir, "..")     # packages/
_repo_root = os.path.join(_packages_dir, "..")   # repo root

def _add(path: str) -> None:
    """Add *path* to sys.path at position 0 if not already present."""
    resolved = os.path.normpath(path)
    if resolved not in sys.path:
        sys.path.insert(0, resolved)

# Order matters: each insert(0) becomes the new highest priority.
# Final priority (highest → lowest):
#   backtest-engine/src > engine/src > core/src > repo_root > …

_add(_repo_root)
_add(os.path.join(_packages_dir, "core", "src"))
_add(os.path.join(_packages_dir, "engine", "src"))
_add(os.path.join(_pkg_dir, "src"))
