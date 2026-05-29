"""FlintTrade core configuration.

Two-tier config model:
  .env            → optional infrastructure overrides (OpenAlgo bridge, ports)
  workspace.json  → user preferences (paths, modules, LLM, Telegram, SEBI)
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, field_validator

from .workspace import Workspace

logger = logging.getLogger("flinttrade.core.config")

# Walk up from packages/core/core/src/ to find repo root .env
_repo_root = Path(__file__).resolve().parents[4]
load_dotenv(_repo_root / ".env")


class Settings(BaseModel):
    """Validated configuration for FlintTrade core.

    OpenAlgo connection settings are optional. FlintTrade can boot without
    a running OpenAlgo bridge; live OpenAlgo calls fail gracefully until the
    user connects one.
    User preferences come from Workspace (workspace.json).
    """

    openalgo_host: str = "http://127.0.0.1:5000"
    openalgo_api_key: str = ""
    openalgo_port: int = 5000
    openalgo_ws_port: int = 8765
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
        """Build Settings from environment variables (.env)."""
        host = os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000") or "http://127.0.0.1:5000"
        key = os.getenv("OPENALGO_API_KEY", "")
        port = os.getenv("OPENALGO_PORT", "5000")
        ws_port = os.getenv("OPENALGO_WS_PORT", "8765")

        return cls(
            openalgo_host=host,
            openalgo_api_key=key,
            openalgo_port=int(port),
            openalgo_ws_port=int(ws_port),
        )


class FlintTradeConfig:
    """Combined configuration: .env for infrastructure, workspace for prefs.

    Usage::

        config = FlintTradeConfig.from_env()
        config.settings.openalgo_host   # from .env
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
