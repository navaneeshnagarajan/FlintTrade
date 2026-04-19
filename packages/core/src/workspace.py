"""FlintTrade workspace configuration — ~/.flinttrade/workspace.json.

Cross-platform workspace location:
  Linux:   ~/.flinttrade/
  macOS:   ~/Library/Application Support/flinttrade/
  Windows: %APPDATA%/flinttrade/
  Override: FLINTTRADE_HOME env var

All user preferences (paths, modules, LLM, Telegram, SEBI settings) live
in workspace.json. Infrastructure settings (OpenAlgo connection) stay in .env.
"""

from __future__ import annotations

import json
import logging
import os
import platform
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.core.workspace")

_DEFAULT_CONFIG: dict[str, Any] = {
    "version": "0.1.0-alpha",
    "initialized": False,
    "markets": [],
    "modules": {
        "terminal": True,
        "dashboard": True,
        "screener": True,
        "backtest": True,
        "ai": False,
        "ditto": False,
        "automation": False,
    },
    "storage": {
        "fast": "~/.flinttrade/data",
        "archive": "~/.flinttrade/archive",
    },
    "openalgo": {
        "host": "http://127.0.0.1:5000",
        "ws_port": 8765,
    },
    "ui": {
        "theme": "dark",
        "default_exchange": "NSE",
        "timezone": "Asia/Kolkata",
    },
    "llm": {
        "provider": "",
        "host": "",
        "model": "",
        "api_key_ref": "",
    },
    "notifications": {
        "telegram_enabled": False,
        "telegram_bot_token_ref": "",
        "telegram_chat_id": "",
    },
    "sebi": {
        "max_ops_per_second": 10,
        "audit_retention_years": 5,
        "kill_switch_enabled": True,
    },
}


def _default_home() -> Path:
    """Resolve the platform-appropriate workspace directory."""
    env = os.environ.get("FLINTTRADE_HOME")
    if env:
        return Path(env).expanduser().resolve()

    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "flinttrade"
    if system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            return Path(appdata) / "flinttrade"
        return Path.home() / "AppData" / "Roaming" / "flinttrade"
    # Linux and everything else
    return Path.home() / ".flinttrade"


class Workspace:
    """Central configuration for a FlintTrade installation.

    Manages ``workspace.json`` which stores all user preferences —
    storage paths, enabled modules, LLM config, notification settings, etc.
    """

    def __init__(self, home_dir: Path | None = None) -> None:
        self._home = (home_dir or _default_home()).expanduser().resolve()
        self._config: dict[str, Any] = {}
        if self.config_path.exists():
            self._config = self.load()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def workspace_dir(self) -> Path:
        return self._home

    @property
    def config_path(self) -> Path:
        return self._home / "workspace.json"

    @property
    def fast_data_dir(self) -> Path:
        raw = self.get("storage.fast", "~/.flinttrade/data")
        return Path(raw).expanduser().resolve()

    @property
    def archive_dir(self) -> Path:
        raw = self.get("storage.archive", "~/.flinttrade/archive")
        return Path(raw).expanduser().resolve()

    @property
    def log_dir(self) -> Path:
        return self._home / "logs"

    @property
    def is_initialized(self) -> bool:
        return self.config_path.exists() and self._config.get("initialized", False)

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        """Load workspace.json from disk."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self._config = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load workspace.json: %s — using defaults", exc)
            self._config = dict(_DEFAULT_CONFIG)
        return self._config

    def save(self, config: dict[str, Any] | None = None) -> None:
        """Write workspace.json (pretty JSON, sorted keys)."""
        if config is not None:
            self._config = config
        self._home.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=2, sort_keys=True)

    def initialise(self, config: dict[str, Any] | None = None) -> None:
        """First-time setup — create dirs, write default config."""
        self._config = config or dict(_DEFAULT_CONFIG)
        self._config["initialized"] = True
        self.ensure_directories()
        self.save()
        logger.info("Workspace initialised at %s", self._home)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value using dot notation (e.g. 'storage.fast')."""
        parts = key.split(".")
        node: Any = self._config
        for part in parts:
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def set(self, key: str, value: Any) -> None:
        """Set a config value using dot notation and save."""
        parts = key.split(".")
        node = self._config
        for part in parts[:-1]:
            if part not in node or not isinstance(node[part], dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = value
        self.save()

    def ensure_directories(self) -> None:
        """Create all data directories if they don't exist."""
        for d in [self._home, self.fast_data_dir, self.archive_dir, self.log_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def as_dict(self) -> dict[str, Any]:
        """Return a copy of the current config."""
        return dict(self._config)
