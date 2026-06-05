"""Tripwire: ``FlintTradeApp.start()`` must start the cron scheduler.

Regression guard for the usability-recovery campaign. ``register_builtin_jobs()``
was called during boot but ``cron.start()`` was not, so APScheduler never ran —
the nightly DuckDB CHECKPOINT+ANALYZE (``db_optimise_job``), square-off warning,
EOD logout, and health-check jobs were all inert. An AST check is used so the
guard survives reformatting and is independent of import side-effects.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP_PY = Path(__file__).resolve().parents[1] / "src" / "flinttrade_core" / "app.py"


def _find_method(tree: ast.AST, class_name: str, method_name: str) -> ast.AST | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for sub in node.body:
                if (
                    isinstance(sub, (ast.AsyncFunctionDef, ast.FunctionDef))
                    and sub.name == method_name
                ):
                    return sub
    return None


@pytest.mark.unit
def test_flinttrade_app_start_calls_cron_start() -> None:
    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    start = _find_method(tree, "FlintTradeApp", "start")
    assert start is not None, "FlintTradeApp.start not found in app.py"

    cron_start_calls = [
        node
        for node in ast.walk(start)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "start"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "cron"
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id == "self"
    ]

    assert cron_start_calls, (
        "FlintTradeApp.start() must call self.cron.start() after "
        "register_builtin_jobs() — otherwise APScheduler never runs and the "
        "nightly DB-optimise and other built-in cron jobs silently never fire."
    )
