"""Expose checked auth custody for standalone AI package tests too."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _factory_lifecycle():
    # Match the root/core/data loader: package-local ``tests`` may shadow root.
    name = "_flinttrade_test_factory_lifecycle"
    if name not in sys.modules:
        root = Path(__file__).resolve().parents[4]
        spec = importlib.util.spec_from_file_location(name, root / "tests/flask_app_lifecycle.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


owned_flask_apps = _factory_lifecycle().owned_flask_apps
owned_auth_state = _factory_lifecycle().owned_auth_state
