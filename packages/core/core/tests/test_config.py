"""Regression coverage for OpenAlgo endpoint derivation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from flinttrade_core import config
from flinttrade_core.config import Settings, openalgo_ws_base_url


@pytest.mark.unit
def test_source_desktop_refuses_checkout_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    load_dotenv = MagicMock()
    monkeypatch.setattr(config, "load_dotenv", load_dotenv)
    monkeypatch.setenv("FLINTTRADE_DESKTOP", "1")
    monkeypatch.setattr(config.sys, "frozen", False, raising=False)

    config._load_dev_env()

    load_dotenv.assert_not_called()


@pytest.mark.unit
def test_contributor_run_still_loads_checkout_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    load_dotenv = MagicMock()
    monkeypatch.setattr(config, "load_dotenv", load_dotenv)
    monkeypatch.delenv("FLINTTRADE_DESKTOP", raising=False)
    monkeypatch.setattr(config.sys, "frozen", False, raising=False)

    config._load_dev_env()

    expected_repo_root = Path(config.__file__).resolve().parents[5]
    load_dotenv.assert_called_once_with(expected_repo_root / ".env", override=False)


@pytest.mark.unit
def test_frozen_desktop_still_refuses_checkout_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    load_dotenv = MagicMock()
    monkeypatch.setattr(config, "load_dotenv", load_dotenv)
    monkeypatch.delenv("FLINTTRADE_DESKTOP", raising=False)
    monkeypatch.setattr(config.sys, "frozen", True, raising=False)

    config._load_dev_env()

    load_dotenv.assert_not_called()


@pytest.mark.unit
def test_openalgo_ws_base_url_maps_https_to_wss_and_uses_workspace_port() -> None:
    settings = Settings(openalgo_host="https://openalgo.local", openalgo_ws_port=8770)

    assert openalgo_ws_base_url(settings) == "wss://openalgo.local:8770"


@pytest.mark.unit
def test_openalgo_ws_base_url_replaces_rest_port_and_preserves_ipv6_host() -> None:
    settings = Settings(openalgo_host="http://[::1]:5000", openalgo_ws_port=8770)

    assert openalgo_ws_base_url(settings) == "ws://[::1]:8770"
