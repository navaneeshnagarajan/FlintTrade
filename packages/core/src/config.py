"""FlintTrade core configuration — loads .env and validates required settings."""

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, field_validator

# Walk up from packages/core/src/ to find repo root .env
_repo_root = Path(__file__).resolve().parents[3]
load_dotenv(_repo_root / ".env")


class Settings(BaseModel):
    """Validated configuration for FlintTrade core."""

    openalgo_host: str
    openalgo_api_key: str
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
        if not v or v == "your_openalgo_api_key_here":
            raise ValueError("openalgo_api_key must be set to a real API key")
        return v

    @classmethod
    def from_env(cls) -> "Settings":
        """Build Settings from environment variables."""
        from .exceptions import ConfigError

        host = os.getenv("OPENALGO_HOST", "")
        key = os.getenv("OPENALGO_API_KEY", "")
        ws_port = os.getenv("OPENALGO_WS_PORT", "8765")

        if not host:
            raise ConfigError("OPENALGO_HOST environment variable is required")
        if not key:
            raise ConfigError("OPENALGO_API_KEY environment variable is required")

        return cls(
            openalgo_host=host,
            openalgo_api_key=key,
            openalgo_ws_port=int(ws_port),
        )
