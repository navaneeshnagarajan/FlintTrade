"""Tests for the native-desktop backend entry point (``flinttrade_core.desktop``).

Run with:
    python -m pytest packages/core/core/tests/test_desktop.py -v --import-mode=importlib
"""

from __future__ import annotations

import pytest

from flinttrade_core import desktop


@pytest.mark.unit
def test_resolve_port_prefers_cli_arg(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit ``--port`` value wins over the env var and the default."""
    monkeypatch.setenv("FLINTTRADE_BACKEND_PORT", "5999")
    assert desktop._resolve_port(5123) == 5123


@pytest.mark.unit
def test_resolve_port_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no CLI arg, the env var is used."""
    monkeypatch.setenv("FLINTTRADE_BACKEND_PORT", "5321")
    assert desktop._resolve_port(None) == 5321


@pytest.mark.unit
def test_resolve_port_defaults_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """With neither CLI arg nor env var, the default port is returned."""
    monkeypatch.delenv("FLINTTRADE_BACKEND_PORT", raising=False)
    assert desktop._resolve_port(None) == desktop.DEFAULT_PORT


@pytest.mark.unit
def test_resolve_port_ignores_non_integer_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A malformed env var is ignored in favour of the default (never crashes)."""
    monkeypatch.setenv("FLINTTRADE_BACKEND_PORT", "not-a-port")
    assert desktop._resolve_port(None) == desktop.DEFAULT_PORT


@pytest.mark.unit
def test_resolve_port_zero_means_os_chosen(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--port 0`` is honoured (the OS picks a free port at bind time)."""
    monkeypatch.delenv("FLINTTRADE_BACKEND_PORT", raising=False)
    assert desktop._resolve_port(0) == 0


@pytest.mark.unit
def test_ready_sentinel_constant() -> None:
    """The handshake sentinel is the exact string the Tauri shell scans for."""
    assert desktop.READY_SENTINEL == "FLINTTRADE_BACKEND_READY"
