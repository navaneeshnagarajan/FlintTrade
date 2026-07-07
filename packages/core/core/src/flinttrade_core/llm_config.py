"""Workspace-backed LLM configuration and local secret storage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .secure_file import write_secret_text
from .workspace import Workspace

LLM_API_KEY_REF = "secret://llm/api_key"


def _secret_path(ws: Workspace) -> Path:
    return ws.workspace_dir / "secrets" / "llm_api_key"


def _read_secret(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except OSError:
        return ""


def resolve_llm_api_key(ws: Workspace | None = None) -> str:
    """Return the workspace-stored LLM API key, if configured."""
    workspace = ws or Workspace()
    ref = str(workspace.get("llm.api_key_ref", "") or "")
    if ref != LLM_API_KEY_REF:
        return ""
    return _read_secret(_secret_path(workspace))


def read_llm_config(ws: Workspace | None = None) -> dict[str, Any]:
    """Return the redacted LLM config stored in the workspace."""
    workspace = ws or Workspace()
    api_key = resolve_llm_api_key(workspace)
    return {
        "provider": str(workspace.get("llm.provider", "") or ""),
        "host": str(workspace.get("llm.host", "") or ""),
        "model": str(workspace.get("llm.model", "") or ""),
        "api_key_configured": bool(api_key),
        "api_key_last4": api_key[-4:] if api_key else "",
    }


def persist_llm_config(payload: dict[str, Any], ws: Workspace | None = None) -> dict[str, Any]:
    """Persist a partial LLM config patch and return the redacted config."""
    workspace = ws or Workspace()
    if not workspace.config_path.exists():
        workspace.initialise()

    has_update = False
    for field in ("provider", "host", "model"):
        if field in payload:
            workspace.set(f"llm.{field}", str(payload.get(field, "") or "").strip())
            has_update = True

    if "api_key" in payload:
        api_key = str(payload.get("api_key", "") or "").strip()
        secret_path = _secret_path(workspace)
        if api_key:
            write_secret_text(secret_path, api_key)
            workspace.set("llm.api_key_ref", LLM_API_KEY_REF)
        else:
            try:
                secret_path.unlink()
            except FileNotFoundError:
                pass
            workspace.set("llm.api_key_ref", "")
        has_update = True

    if not has_update:
        raise ValueError("At least one of provider, host, model, api_key is required")

    return read_llm_config(workspace)
