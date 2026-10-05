"""Core configuration and developer environment boundaries."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from flinttrade_core import config


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
def test_contributor_env_permission_error_is_optional_not_boot_fatal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """A mis-moded optional .env must not crash a service with injected env."""
    source_root = tmp_path / "FlintTrade"
    monkeypatch.setattr(config, "discover_source_root", lambda: source_root)
    monkeypatch.setattr(
        config,
        "load_dotenv",
        MagicMock(side_effect=PermissionError("denied")),
    )
    monkeypatch.delenv("FLINTTRADE_DESKTOP", raising=False)

    config._load_dev_env()
