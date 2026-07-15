"""Strict persistence boundary for tuneable order-safety configuration."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from flinttrade_engine.safety import SafetyConfig

from .workspace_migrations import run_migrations, update_workspace_config


class SafetyRuntimeUnavailable(RuntimeError):
    """Raised when live routing has no validated durable safety runtime."""


def require_ready_safety(config: Mapping[str, Any]) -> Any:
    """Return the configured safety system only after durable validation succeeded."""
    if config.get("SAFETY_CONFIG_READY") is not True:
        raise SafetyRuntimeUnavailable("durable safety configuration is not ready")
    safety = config.get("SAFETY")
    if safety is None:
        raise SafetyRuntimeUnavailable("safety runtime is not configured")
    return safety


def load_workspace_safety_config(workspace_dir: Path) -> SafetyConfig:
    """Load and strictly validate the complete versioned safety snapshot."""
    workspace = run_migrations(workspace_dir)
    raw = workspace.get("safety")
    if not isinstance(raw, Mapping):
        raise ValueError("workspace safety configuration is missing or invalid")
    return SafetyConfig.from_mapping(raw)


def persist_workspace_safety_config(workspace_dir: Path, config: SafetyConfig) -> dict[str, Any]:
    """Atomically replace the full safety section in the latest workspace."""
    payload = config.to_mapping()

    def update(workspace: dict[str, Any]) -> None:
        workspace["safety"] = payload

    return update_workspace_config(workspace_dir, update)
