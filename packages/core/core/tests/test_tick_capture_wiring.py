"""Tick-capture boot wiring + gate.

Live tick capture (``TickRecorder``) is a complete OpenAlgo-WS → DuckDB recorder
that previously was never launched by the backend. This guards the wiring:

* ``_tick_capture_enabled()`` is OFF unless ``FLINTTRADE_TICK_CAPTURE`` is set
  (the recorder opens a WebSocket on boot, so it must be opt-in).
* ``FlintTradeApp.start()`` constructs a ``TickRecorder`` and launches it as a
  background task, gated by ``_tick_capture_enabled()``.
* ``FlintTradeApp.stop()`` stops the recorder.

The ``start()`` assertions are AST-based so they survive reformatting and do not
require booting the app (which opens sockets and spawns threads).
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from flinttrade_core.app import _tick_capture_enabled

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
def test_tick_capture_disabled_by_default() -> None:
    old = os.environ.pop("FLINTTRADE_TICK_CAPTURE", None)
    try:
        assert _tick_capture_enabled() is False
        for val in ("1", "true", "YES", "on"):
            os.environ["FLINTTRADE_TICK_CAPTURE"] = val
            assert _tick_capture_enabled() is True
        os.environ["FLINTTRADE_TICK_CAPTURE"] = "false"
        assert _tick_capture_enabled() is False
    finally:
        if old is None:
            os.environ.pop("FLINTTRADE_TICK_CAPTURE", None)
        else:
            os.environ["FLINTTRADE_TICK_CAPTURE"] = old


@pytest.mark.unit
def test_start_launches_gated_tick_recorder() -> None:
    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    start = _find_method(tree, "FlintTradeApp", "start")
    assert start is not None, "FlintTradeApp.start not found"

    assert _calls_named(start, "_tick_capture_enabled"), (
        "Tick capture must be gated by _tick_capture_enabled() in start()"
    )
    assert _calls_named(start, "TickRecorder"), (
        "start() must construct a TickRecorder when tick capture is enabled"
    )
    assert _calls_named(start, "create_task"), (
        "start() must launch the recorder via asyncio.create_task so it runs "
        "as a background task on the event loop"
    )


@pytest.mark.unit
def test_stop_stops_tick_recorder() -> None:
    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    stop = _find_method(tree, "FlintTradeApp", "stop")
    assert stop is not None, "FlintTradeApp.stop not found"
    # The stop path must reference the recorder handle so it is shut down.
    refs = [
        n
        for n in ast.walk(stop)
        if isinstance(n, ast.Attribute) and n.attr == "_tick_recorder"
    ]
    assert refs, "stop() must stop/cancel the tick recorder (_tick_recorder)"


@pytest.mark.unit
def test_workspace_config_readers(tmp_path, monkeypatch) -> None:
    """Tick mode + auto-sync flags read from workspace.json with safe defaults."""
    import json

    from flinttrade_core.app import (
        _auto_sync_enabled,
        _auto_sync_lookback_days,
        _tick_capture_mode,
        _tick_capture_watchlist,
    )

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))

    # No workspace.json → safe defaults.
    assert _tick_capture_mode() == "quote"
    assert _auto_sync_enabled() is False
    assert _auto_sync_lookback_days() == 7
    assert len(_tick_capture_watchlist()) == 3  # default index trio

    (tmp_path / "workspace.json").write_text(json.dumps({
        "data": {
            "tick_capture": {
                "mode": "depth",
                "symbols": [
                    {"exchange": "nse", "symbol": "reliance"},
                    {"bogus": True},
                ],
            },
            "auto_sync": {"enabled": True, "lookback_days": 30},
        },
    }), encoding="utf-8")

    assert _tick_capture_mode() == "depth"
    assert _auto_sync_enabled() is True
    assert _auto_sync_lookback_days() == 30
    # Malformed entries skipped; valid ones normalised to upper case.
    assert _tick_capture_watchlist() == [{"exchange": "NSE", "symbol": "RELIANCE"}]

    # Invalid mode falls back to quote, lookback clamps.
    (tmp_path / "workspace.json").write_text(json.dumps({
        "data": {"tick_capture": {"mode": "warp"}, "auto_sync": {"enabled": 1, "lookback_days": 900}},
    }), encoding="utf-8")
    assert _tick_capture_mode() == "quote"
    assert _auto_sync_enabled() is True
    assert _auto_sync_lookback_days() == 90
