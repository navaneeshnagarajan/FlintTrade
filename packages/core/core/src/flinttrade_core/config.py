"""FlintTrade core configuration.

Config model:
  workspace.json  → UI-owned user configuration, including OpenAlgo bridge settings
  .env            → optional developer/server fallback overrides
"""

import logging
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, field_validator

from .workspace import Workspace

logger = logging.getLogger("flinttrade.core.config")

DEFAULT_OPENALGO_HOST = "http://127.0.0.1:5000"
DEFAULT_OPENALGO_PORT = 5000
DEFAULT_OPENALGO_WS_PORT = 8765


def _load_dev_env() -> None:
    """Load repo-root .env for contributor/server runs, never for frozen desktop."""
    if getattr(sys, "frozen", False):
        return
    repo_root = Path(__file__).resolve().parents[5]
    load_dotenv(repo_root / ".env", override=False)


def _workspace_openalgo_overrides() -> dict[str, Any]:
    """Return explicit UI/workspace OpenAlgo settings.

    A fresh workspace contains default host/port values. Those defaults should
    not silently override server/developer environment variables unless the UI
    has actually stored a non-default value or an API key.
    """
    try:
        workspace = Workspace()
        data = workspace.as_dict()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("workspace OpenAlgo config unavailable: %s", exc)
        return {}

    openalgo = data.get("openalgo") if isinstance(data, dict) else None
    if not isinstance(openalgo, dict):
        return {}

    api_key = str(openalgo.get("api_key", "") or "").strip()
    host = str(openalgo.get("host", "") or "").strip()
    ws_port_raw = openalgo.get("ws_port")
    ws_port = str(ws_port_raw or "").strip()

    has_user_value = bool(api_key)
    has_user_value = has_user_value or (bool(host) and host.rstrip("/") != DEFAULT_OPENALGO_HOST)
    has_user_value = has_user_value or (bool(ws_port) and ws_port != str(DEFAULT_OPENALGO_WS_PORT))
    if not has_user_value:
        return {}

    overrides: dict[str, Any] = {}
    if api_key:
        overrides["openalgo_api_key"] = api_key
    if host:
        overrides["openalgo_host"] = host
    if ws_port:
        overrides["openalgo_ws_port"] = int(ws_port)
    return overrides


class Settings(BaseModel):
    """Validated configuration for FlintTrade core.

    OpenAlgo connection settings are optional. FlintTrade can boot without
    a running OpenAlgo bridge; live OpenAlgo calls fail gracefully until the
    user connects one.
    User preferences come from Workspace (workspace.json).
    """

    openalgo_host: str = DEFAULT_OPENALGO_HOST
    openalgo_api_key: str = ""
    openalgo_port: int = DEFAULT_OPENALGO_PORT
    openalgo_ws_port: int = DEFAULT_OPENALGO_WS_PORT
    strategy: str = "Flint"

    @field_validator("openalgo_host")
    @classmethod
    def host_must_be_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("openalgo_host must start with http:// or https://")
        return v.rstrip("/")

    @field_validator("openalgo_api_key")
    @classmethod
    def key_must_not_be_placeholder(cls, v: str) -> str:
        if v == "your_openalgo_api_key_here":
            raise ValueError("openalgo_api_key must be set to a real API key")
        return v

    @classmethod
    def from_env(cls) -> "Settings":
        """Build Settings from UI workspace config, with env as a fallback."""
        _load_dev_env()
        host = os.getenv("OPENALGO_HOST", DEFAULT_OPENALGO_HOST) or DEFAULT_OPENALGO_HOST
        key = os.getenv("OPENALGO_API_KEY", "")
        port = os.getenv("OPENALGO_PORT", str(DEFAULT_OPENALGO_PORT))
        ws_port = os.getenv("OPENALGO_WS_PORT", str(DEFAULT_OPENALGO_WS_PORT))

        settings = {
            "openalgo_host": host,
            "openalgo_api_key": key,
            "openalgo_port": int(port),
            "openalgo_ws_port": int(ws_port),
        }
        settings.update(_workspace_openalgo_overrides())

        return cls(**settings)


class FlintTradeConfig:
    """Combined configuration: workspace for UI config, env for fallback.

    Usage::

        config = FlintTradeConfig.from_env()
        config.settings.openalgo_host   # from workspace.json or env fallback
        config.workspace.fast_data_dir  # from workspace.json
    """

    def __init__(self, settings: Settings, workspace: Workspace | None = None) -> None:
        self.settings = settings
        self.workspace = workspace or Workspace()

    @classmethod
    def from_env(cls) -> "FlintTradeConfig":
        return cls(settings=Settings.from_env())

    @property
    def fast_data_dir(self) -> Path:
        return self.workspace.fast_data_dir

    @property
    def archive_dir(self) -> Path:
        return self.workspace.archive_dir

    @property
    def log_dir(self) -> Path:
        return self.workspace.log_dir
