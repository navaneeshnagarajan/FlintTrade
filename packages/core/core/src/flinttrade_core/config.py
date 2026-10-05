"""FlintTrade configuration from the workspace and optional server environment."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel

from .source_root import discover_source_root
from .workspace import Workspace

logger = logging.getLogger("flinttrade.core.config")


def _load_dev_env() -> None:
    """Load repo-root .env for contributor/server runs, never for desktop."""
    if os.environ.get("FLINTTRADE_DESKTOP") == "1":
        return
    try:
        load_dotenv(discover_source_root() / ".env", override=False)
    except OSError as exc:
        logger.warning("Could not read optional server fallback: %s", exc)


class Settings(BaseModel):
    """Core settings; broker credentials belong to the encrypted gateway vault."""

    strategy: str = "Flint"

    @classmethod
    def from_env(cls) -> Settings:
        _load_dev_env()
        return cls()

    @classmethod
    def from_workspace_data(cls, data: dict[str, Any]) -> Settings:
        return cls()


class FlintTradeConfig:
    """Combine core settings and workspace-owned user preferences."""

    def __init__(self, settings: Settings, workspace: Workspace | None = None) -> None:
        self.settings = settings
        self.workspace = workspace or Workspace()

    @classmethod
    def from_env(cls) -> FlintTradeConfig:
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
