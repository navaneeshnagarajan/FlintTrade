"""FlintTrade core configuration.

Config model:
  workspace.json  → UI-owned user configuration, including OpenAlgo bridge settings
  .env            → optional developer/server fallback overrides
"""

import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv
from pydantic import BaseModel, field_validator

from .source_root import discover_source_root
from .workspace import Workspace

logger = logging.getLogger("flinttrade.core.config")

DEFAULT_OPENALGO_HOST = "http://127.0.0.1:5000"
DEFAULT_OPENALGO_PORT = 5000
DEFAULT_OPENALGO_WS_PORT = 8765


def _load_dev_env() -> None:
    """Load repo-root .env for contributor/server runs, never for desktop."""
    if os.environ.get("FLINTTRADE_DESKTOP") == "1":
        return
    env_path = discover_source_root() / ".env"
    try:
        load_dotenv(env_path, override=False)
    except OSError as exc:
        logger.warning("Could not read optional server fallback %s: %s", env_path, exc)


def _workspace_openalgo_overrides_from_data(data: dict[str, Any]) -> dict[str, Any]:
    """Return explicit OpenAlgo overrides from one in-memory workspace config."""
    openalgo = data.get("openalgo") if isinstance(data, dict) else None
    if not isinstance(openalgo, dict):
        return {}

    api_key = str(openalgo.get("api_key", "") or "").strip()
    telegram_username = str(openalgo.get("telegram_username", "") or "").strip()
    host = str(openalgo.get("host", "") or "").strip()
    port_raw = openalgo.get("port")
    port = str(port_raw or "").strip()
    ws_port_raw = openalgo.get("ws_port")
    ws_port = str(ws_port_raw or "").strip()

    overrides: dict[str, Any] = {}
    if telegram_username:
        # Telegram is independent of the bridge endpoint. A linked username must
        # not activate the workspace host/port block, or the standard localhost
        # defaults from workspace.json would overwrite OPENALGO_HOST / PORT /
        # WS_PORT on every config hot reload.
        overrides["openalgo_telegram_username"] = telegram_username

    has_connection_value = bool(api_key)
    has_connection_value = has_connection_value or (
        bool(host) and host.rstrip("/") != DEFAULT_OPENALGO_HOST
    )
    has_connection_value = has_connection_value or (bool(port) and port != str(DEFAULT_OPENALGO_PORT))
    has_connection_value = has_connection_value or (
        bool(ws_port) and ws_port != str(DEFAULT_OPENALGO_WS_PORT)
    )
    if not has_connection_value:
        return overrides

    if api_key:
        overrides["openalgo_api_key"] = api_key
    if host:
        overrides["openalgo_host"] = host
    if port:
        overrides["openalgo_port"] = int(port)
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
    openalgo_telegram_username: str = ""
    openalgo_port: int = DEFAULT_OPENALGO_PORT
    openalgo_ws_port: int = DEFAULT_OPENALGO_WS_PORT
    strategy: str = "Flint"

    @field_validator("openalgo_host")
    @classmethod
    def host_must_be_url(cls, v: str) -> str:
        try:
            parsed = urlsplit(v)
            _ = parsed.port
        except ValueError:
            raise ValueError("openalgo_host must be a valid HTTP(S) URL") from None
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("openalgo_host must be a valid HTTP(S) URL")
        return v.rstrip("/")

    @field_validator("openalgo_api_key")
    @classmethod
    def key_must_not_be_placeholder(cls, v: str) -> str:
        if v == "your_openalgo_api_key_here":
            raise ValueError("openalgo_api_key must be set to a real API key")
        return v

    @field_validator("openalgo_port", "openalgo_ws_port")
    @classmethod
    def ports_must_be_valid(cls, v: int) -> int:
        if not 1 <= int(v) <= 65535:
            raise ValueError("OpenAlgo ports must be between 1 and 65535")
        return v

    @classmethod
    def from_env(cls) -> "Settings":
        """Build Settings from UI workspace config, with env as a fallback."""
        try:
            workspace_data = Workspace().as_dict()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("workspace OpenAlgo config unavailable: %s", exc)
            workspace_data = {}
        return cls.from_workspace_data(workspace_data)

    @classmethod
    def from_workspace_data(cls, data: dict[str, Any]) -> "Settings":
        """Validate a candidate workspace config before it is persisted."""
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
        settings.update(_workspace_openalgo_overrides_from_data(data))

        return cls(**settings)


def openalgo_rest_base_url(settings: Settings) -> str:
    """Return the OpenAlgo REST base URL, applying the fallback REST port."""
    host = settings.openalgo_host.rstrip("/")
    try:
        parsed = urlsplit(host)
        if parsed.port is not None:
            return host
    except ValueError:
        return host

    hostname = parsed.hostname or parsed.netloc
    if not hostname:
        return host
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = f"{hostname}:{settings.openalgo_port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), parsed.query, parsed.fragment)).rstrip("/")


def openalgo_ws_base_url(settings: Settings) -> str:
    """Return the OpenAlgo WebSocket origin derived from workspace settings."""
    parsed = urlsplit(settings.openalgo_host)
    scheme = {"http": "ws", "https": "wss"}.get(parsed.scheme)
    hostname = parsed.hostname
    if scheme is None or not hostname:
        raise ValueError("openalgo_host must contain a valid HTTP(S) hostname")
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    return urlunsplit((scheme, f"{hostname}:{settings.openalgo_ws_port}", "", "", ""))


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
