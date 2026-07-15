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
def test_resolve_backend_host_defaults_to_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FLINTTRADE_BACKEND_HOST", raising=False)
    assert app_module._resolve_backend_host() == "127.0.0.1"


@pytest.mark.unit
def test_resolve_backend_host_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLINTTRADE_BACKEND_HOST", " 100.64.0.5 ")
    assert app_module._resolve_backend_host() == "100.64.0.5"


@pytest.mark.unit
def test_run_flask_server_refuses_non_loopback_bind_without_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flask import Flask

    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    app = Flask(__name__)
    with pytest.raises(RuntimeError, match="FLINTTRADE_API_KEY"):
        app_module._run_flask_server(app, port=5100, host="100.64.0.5")


@pytest.mark.unit
def test_run_flask_server_fails_closed_when_auth_store_is_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from flask import Flask

    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    app = Flask(__name__)
    app.config["AUTH_SERVICE"] = SimpleNamespace(is_setup=lambda: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(RuntimeError, match="Refusing to bind"):
        app_module._run_flask_server(app, port=5100, host="100.64.0.5")


@pytest.mark.unit
@pytest.mark.parametrize("configure", ["operator_account", "api_key"])
def test_run_flask_server_allows_non_loopback_bind_with_auth_configured(
    monkeypatch: pytest.MonkeyPatch, configure: str
) -> None:
    """With auth configured the gate passes and the bind proceeds to Waitress."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import waitress.server
    from flask import Flask

    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    app = Flask(__name__)
    if configure == "operator_account":
        app.config["AUTH_SERVICE"] = SimpleNamespace(is_setup=lambda: True)
    else:
        monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-key")

    sentinel = RuntimeError("gate-passed-reached-bind")
    monkeypatch.setattr(waitress.server, "create_server", MagicMock(side_effect=sentinel))
    with pytest.raises(RuntimeError, match="gate-passed-reached-bind"):
        app_module._run_flask_server(app, port=5100, host="100.64.0.5")


@pytest.mark.unit
def test_flinttrade_app_start_uses_resolved_backend_host() -> None:
    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    start = _find_method(tree, "FlintTradeApp", "_start_owned")
    assert start is not None, "FlintTradeApp._start_owned not found in app.py"

    server_calls = [
        node
        for node in ast.walk(start)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_run_flask_server"
    ]
    assert any(
        keyword.arg == "host"
        and isinstance(keyword.value, ast.Call)
        and isinstance(keyword.value.func, ast.Name)
        and keyword.value.func.id == "_resolve_backend_host"
        for call in server_calls
        for keyword in call.keywords
    ), (
        "FlintTradeApp._start_owned() must pass host=_resolve_backend_host() so "
        "FLINTTRADE_BACKEND_HOST controls the web-surface bind."
    )


@pytest.mark.unit
def test_flinttrade_app_start_uses_resolved_backend_port() -> None:
    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    start = _find_method(tree, "FlintTradeApp", "_start_owned")
    assert start is not None, "FlintTradeApp._start_owned not found in app.py"

    server_calls = [
        node
        for node in ast.walk(start)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_run_flask_server"
    ]
    assert server_calls, "FlintTradeApp._start_owned() must call _run_flask_server"
    assert any(
        keyword.arg == "port"
        and isinstance(keyword.value, ast.Call)
        and isinstance(keyword.value.func, ast.Name)
        and keyword.value.func.id == "_resolve_backend_port"
        for call in server_calls
        for keyword in call.keywords
    ), (
        "FlintTradeApp._start_owned() must pass port=_resolve_backend_port() so "
        "FLINTTRADE_BACKEND_PORT matches the Makefile runtime contract."
    )
