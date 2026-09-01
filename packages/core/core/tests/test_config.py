"""Regression coverage for OpenAlgo endpoint derivation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from flinttrade_core import config
from flinttrade_core.config import Settings, openalgo_ws_base_url


@pytest.mark.unit
def test_source_desktop_refuses_checkout_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    load_dotenv = MagicMock()
    discover_source_root = MagicMock()
    monkeypatch.setattr(config, "load_dotenv", load_dotenv)
    monkeypatch.setattr(config, "discover_source_root", discover_source_root)
    monkeypatch.setenv("FLINTTRADE_DESKTOP", "1")

    config._load_dev_env()

    load_dotenv.assert_not_called()
    discover_source_root.assert_not_called()


@pytest.mark.unit
def test_contributor_run_loads_dotenv_from_validated_source_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    load_dotenv = MagicMock()
    source_root = tmp_path / "FlintTrade"
    discover_source_root = MagicMock(return_value=source_root)
    monkeypatch.setattr(config, "load_dotenv", load_dotenv)
    monkeypatch.setattr(config, "discover_source_root", discover_source_root)
    monkeypatch.delenv("FLINTTRADE_DESKTOP", raising=False)

    config._load_dev_env()

    discover_source_root.assert_called_once_with()
    load_dotenv.assert_called_once_with(source_root / ".env", override=False)


@pytest.mark.unit
def test_openalgo_telegram_username_loads_from_workspace() -> None:
    settings = Settings.from_workspace_data(
        {"openalgo": {"telegram_username": "linked-trader"}}
    )

    assert settings.openalgo_telegram_username == "linked-trader"


@pytest.mark.unit
def test_openalgo_ws_base_url_maps_https_to_wss_and_uses_workspace_port() -> None:
    settings = Settings(openalgo_host="https://openalgo.local", openalgo_ws_port=8770)

    assert openalgo_ws_base_url(settings) == "wss://openalgo.local:8770"


@pytest.mark.unit
def test_openalgo_ws_base_url_replaces_rest_port_and_preserves_ipv6_host() -> None:
    settings = Settings(openalgo_host="http://[::1]:5000", openalgo_ws_port=8770)

    assert openalgo_ws_base_url(settings) == "ws://[::1]:8770"
