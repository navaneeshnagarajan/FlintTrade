"""Regression tests for standalone backend port selection."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from flinttrade_core import app as app_module

APP_PY = Path(__file__).resolve().parents[1] / "src" / "flinttrade_core" / "app.py"


def _find_method(tree: ast.AST, class_name: str, method_name: str) -> ast.AST | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for sub in node.body:
                if isinstance(sub, (ast.AsyncFunctionDef, ast.FunctionDef)) and sub.name == method_name:
                    return sub
    return None


@pytest.mark.unit
def test_resolve_backend_port_defaults_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FLINTTRADE_BACKEND_PORT", raising=False)
    assert app_module._resolve_backend_port() == app_module.DEFAULT_BACKEND_PORT


@pytest.mark.unit
def test_resolve_backend_port_reads_makefile_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLINTTRADE_BACKEND_PORT", "5127")
    assert app_module._resolve_backend_port() == 5127


@pytest.mark.unit
def test_resolve_backend_port_ignores_non_integer_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLINTTRADE_BACKEND_PORT", "not-a-port")
    assert app_module._resolve_backend_port() == app_module.DEFAULT_BACKEND_PORT


@pytest.mark.unit
def test_flinttrade_app_start_uses_resolved_backend_port() -> None:
    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    start = _find_method(tree, "FlintTradeApp", "start")
    assert start is not None, "FlintTradeApp.start not found in app.py"

    server_calls = [
        node
        for node in ast.walk(start)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_run_flask_server"
    ]
    assert server_calls, "FlintTradeApp.start() must call _run_flask_server"
    assert any(
        keyword.arg == "port"
        and isinstance(keyword.value, ast.Call)
        and isinstance(keyword.value.func, ast.Name)
        and keyword.value.func.id == "_resolve_backend_port"
        for call in server_calls
        for keyword in call.keywords
    ), (
        "FlintTradeApp.start() must pass port=_resolve_backend_port() so "
        "FLINTTRADE_BACKEND_PORT matches the Makefile runtime contract."
    )
