"""Tripwire: ``FlintTradeApp.start()`` must arm calendar-owned cron jobs.

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
def test_flinttrade_app_start_arms_cron_through_calendar_owner() -> None:
    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    start = _find_method(tree, "FlintTradeApp", "_start_owned")
    calendar_start = _find_method(tree, "FlintTradeApp", "_start_calendar_schedulers")
    assert start is not None, "FlintTradeApp._start_owned not found in app.py"
    assert calendar_start is not None, "FlintTradeApp._start_calendar_schedulers not found"

    arms_calendar_runtime = [
        node
        for node in ast.walk(start)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_start_calendar_schedulers"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "self"
    ]
    assert arms_calendar_runtime, (
        "FlintTradeApp._start_owned() must arm market-sensitive schedulers after an "
        "authoritative calendar is loaded."
    )

    calls = [
        node
        for node in ast.walk(calendar_start)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "cron"
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id == "self"
    ]
    register_calls = [node for node in calls if node.func.attr == "register_builtin_jobs"]
    start_calls = [node for node in calls if node.func.attr == "start"]
    assert register_calls and start_calls, (
        "_start_calendar_schedulers() must register built-in jobs and call "
        "self.cron.start(); otherwise APScheduler remains inert."
    )
    assert register_calls[0].lineno < start_calls[0].lineno


@pytest.mark.unit
def test_flinttrade_app_start_injects_the_overnight_optimiser() -> None:
    """The "optimise overnight" feature must be wired at boot.

    The cron slot ``make_overnight_optimise_job`` only fires if something assigns
    ``self.cron.overnight_optimiser``. The injection lives in a best-effort
    try/except, so if the construction or assignment is dropped the nightly
    optimisation silently never runs (and the failure is swallowed). Guard both
    halves with an AST check so the wiring can't regress unnoticed.
    """
    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    start = _find_method(tree, "FlintTradeApp", "_start_owned")
    assert start is not None, "FlintTradeApp._start_owned not found in app.py"

    constructs_optimiser = [
        node
        for node in ast.walk(start)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "OvernightOptimiser"
    ]
    assert constructs_optimiser, (
        "FlintTradeApp._start_owned() must construct an OvernightOptimiser so the "
        "nightly 'optimise overnight' job has an engine to run."
    )

    injects_optimiser = [
        node
        for node in ast.walk(start)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Attribute)
            and t.attr == "overnight_optimiser"
            and isinstance(t.value, ast.Attribute)
            and t.value.attr == "cron"
            and isinstance(t.value.value, ast.Name)
            and t.value.value.id == "self"
            for t in node.targets
        )
    ]
    assert injects_optimiser, (
        "FlintTradeApp._start_owned() must assign self.cron.overnight_optimiser = "
        "<optimiser>.run — otherwise the nightly optimisation job stays "
        "unregistered and 'optimise overnight' silently never runs."
    )
