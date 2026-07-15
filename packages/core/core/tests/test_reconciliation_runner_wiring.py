"""Reconciliation-runner boot wiring (contract §14.2).

``FlintTradeApp.start()`` must launch the engine's ``ReconciliationRunner`` as
a background task on its event loop (reading the ``RECONCILE_TARGETS``
provider that ``create_flask_app`` builds), and ``stop()`` must shut it down.
Mirrors the AST-based tick-capture wiring guard: assertions survive
reformatting and do not require booting the app (which opens sockets and
spawns threads).
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from flask import Flask
import pytest

from flinttrade_core.app import _record_current_reconcile_snapshot
from flinttrade_engine.local_state_provider import OrderLifecycleLedger
from flinttrade_engine.reconciliation_runner import ReconciliationRunner
from flinttrade_gateway.reconciliation import build_report

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


def _calls_named(scope: ast.AST, func_name: str) -> bool:
    """True if `scope` contains a call to a function/attribute named `func_name`."""
    for node in ast.walk(scope):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id == func_name:
                return True
            if isinstance(f, ast.Attribute) and f.attr == func_name:
                return True
    return False


@pytest.mark.unit
def test_start_launches_reconciliation_runner() -> None:
    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    start = _find_method(tree, "FlintTradeApp", "_start_owned")
    assert start is not None, "FlintTradeApp._start_owned not found"

    assert _calls_named(start, "ReconciliationRunner"), (
        "_start_owned() must construct the engine ReconciliationRunner over the "
        "RECONCILE_TARGETS provider"
    )
    assert _calls_named(start, "create_task"), (
        "_start_owned() must launch the runner via asyncio.create_task so it runs as "
        "a background task on the event loop"
    )


@pytest.mark.unit
def test_stop_stops_reconciliation_runner() -> None:
    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    stop_once = _find_method(tree, "FlintTradeApp", "_stop_once")
    assert stop_once is not None, "FlintTradeApp._stop_once not found"
    refs = [
        n
        for n in ast.walk(stop_once)
        if isinstance(n, ast.Attribute)
        and n.attr in ("_reconciliation_runner", "_reconciliation_task")
    ]
    assert refs, "_stop_once() must stop/cancel the reconciliation runner"


@pytest.mark.integration
async def test_app_recorder_returns_snapshot_generation_to_runner_payload(tmp_path: Path) -> None:
    class _Adapter:
        broker_id = "dhan"
        capabilities = SimpleNamespace(reconcile_recommended_seconds=300)

        async def reconcile(self, session: Any) -> Any:
            return build_report(
                adapter_id=self.broker_id,
                account_id=session.account_id,
                generated_at=datetime(2026, 7, 15, 9, 30, tzinfo=timezone.utc),
            )

    app = Flask("reconciliation-recorder-wiring")
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "order-lifecycle.sqlite3")
    app.config["ORDER_LIFECYCLE_LEDGER"] = ledger
    runner = ReconciliationRunner(
        lambda: [(_Adapter(), SimpleNamespace(account_id="integration"))],
        home_dir=tmp_path,
        state_recorder=lambda **snapshot: _record_current_reconcile_snapshot(app, **snapshot),
    )

    payloads = await runner.run_once()

    assert payloads[0]["snapshot_generation"] == 1
    assert ledger.latest_snapshot_generation(adapter_id="dhan", account_id="integration") == 1
