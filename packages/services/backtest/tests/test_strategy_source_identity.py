"""Shipped strategy classes retain their real Python source owner."""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
import sys

import pytest

from flinttrade_backtest import strategies

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("name,strategy", sorted(strategies.BUILTIN_STRATEGIES.items()))
def test_builtin_source_identity_is_the_actual_loaded_module(name, strategy):
    module = inspect.getmodule(strategy)
    assert module is not None, f"{name} has no registered source module"
    assert sys.modules[strategy.__module__] is module
    assert getattr(module, strategy.__name__) is strategy
    source_path = Path(strategies.__file__).parent.parent / "strategies.py"
    assert Path(inspect.getfile(strategy)).resolve() == source_path.resolve()
    source = inspect.getsource(strategy)
    tree = ast.parse(source)
    assert any(isinstance(node, ast.ClassDef) and node.name == strategy.__name__ for node in tree.body)


@pytest.mark.parametrize("prior", ["absent", "established", "blocked"])
@pytest.mark.parametrize("failure", ["error", "interrupt"])
def test_failed_module_execution_restores_exact_prior_registration(prior, failure):
    import subprocess
    import textwrap

    # A fresh interpreter exercises the real import path without damaging the
    # strategy classes used by neighbouring tests in this process.
    script = textwrap.dedent("""\
        import importlib
        import importlib.machinery
        import sys
        from types import ModuleType

        name = "_backtest_strategies_parent"
        prior, failure = sys.argv[1:]
        previous = ModuleType(name) if prior == "established" else None
        if prior != "absent":
            sys.modules[name] = previous
        original = importlib.machinery.SourceFileLoader.exec_module
        observed = []
        exception = RuntimeError if failure == "error" else KeyboardInterrupt

        def fail_parent(self, module):
            if module.__name__ == name:
                observed.append(sys.modules.get(name) is module)
                raise exception("synthetic source-loader failure")
            return original(self, module)

        importlib.machinery.SourceFileLoader.exec_module = fail_parent
        try:
            importlib.import_module("flinttrade_backtest.strategies")
        except exception as exc:
            assert str(exc) == "synthetic source-loader failure"
        else:
            raise AssertionError("Loader failure was swallowed")
        assert observed == [True], observed
        if prior == "absent":
            assert name not in sys.modules
        else:
            assert name in sys.modules and sys.modules[name] is previous
    """)
    result = subprocess.run([sys.executable, "-c", script, prior, failure], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
