"""UI-persisted n8n bridge settings.

Mirrors the telegram/whatsapp config discipline: the n8n API key lives in a
hardened owner-only secret file with only a ``secret://`` reference in
``workspace.json``; the host is non-secret and stored plainly under
``n8n.host``. Reads are redacted to ``api_key_set``. Absent POST fields
preserve current state. Environment variables (``N8N_HOST``/``N8N_API_KEY``)
remain an override for server-style deployments.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .secure_file import read_owner_owned_text, write_secret_text
from .workspace import Workspace

logger = logging.getLogger("flinttrade.core.n8n_config")

N8N_API_KEY_REF = "secret://n8n/api_key"


def _secret_path(ws: Workspace) -> Path:
    return ws.workspace_dir / "secrets" / "n8n_api_key"


def resolve_n8n_api_key(ws: Workspace | None = None) -> str:
    """Read the stored n8n API key, or ``""`` when none is configured."""
    workspace = ws or Workspace()
    try:
        return read_owner_owned_text(_secret_path(workspace)).strip()
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return ""


def read_n8n_config(ws: Workspace | None = None) -> dict[str, Any]:
    """Redacted settings for the UI — never includes the key itself."""
    workspace = ws or Workspace()
    return {
        "host": str(workspace.get("n8n.host", "") or ""),
        "api_key_set": bool(resolve_n8n_api_key(workspace)),
    }


def persist_n8n_config(payload: dict[str, Any], ws: Workspace | None = None) -> dict[str, Any]:
    """Validate and persist n8n settings from the UI.

    Payload fields — ABSENT fields preserve the current stored value:
        host (str): n8n base URL. An explicit empty string clears it (the
            bridge then falls back to its default ``http://127.0.0.1:5678``).
        api_key (str, optional): a NEW key to store; blank/absent preserves.
        clear_api_key (bool, optional): explicitly forget the stored key.

    Returns:
        The redacted post-save state (same shape as ``read_n8n_config``).

    Raises:
        ValueError: On any malformed field — nothing is written in that case.
    """
    workspace = ws or Workspace()
    current = read_n8n_config(workspace)

    host = payload.get("host", current["host"])
    if not isinstance(host, str):
        raise ValueError("host must be a string")
    host = host.strip().rstrip("/")
    if host:
        try:
            parsed = urlsplit(host)
        except ValueError as exc:
            raise ValueError("host is not a valid URL") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("host must be an http(s) URL")

    clear_key = payload.get("clear_api_key", False)
    if not isinstance(clear_key, bool):
        raise ValueError("clear_api_key must be a boolean")

    new_key = payload.get("api_key", "")
    if new_key is None:
        new_key = ""
    if not isinstance(new_key, str):
        raise ValueError("api_key must be a string")
    new_key = new_key.strip()
    if new_key and new_key.startswith("secret://"):
        raise ValueError("api_key must be the key itself, not a reference")
    if new_key and clear_key:
        raise ValueError("api_key and clear_api_key are mutually exclusive")

    would_have_key = bool(new_key) or (not clear_key and bool(resolve_n8n_api_key(workspace)))

    # Secret WRITE first (workspace untouched on failure); DELETE after the
    # transaction so a mid-clear failure leaves a functional config.
    if new_key:
        write_secret_text(_secret_path(workspace), new_key)

    def _apply(config: dict[str, Any]) -> None:
        n8n = config.setdefault("n8n", {})
        n8n["host"] = host
        n8n["api_key_ref"] = N8N_API_KEY_REF if would_have_key else ""

    workspace.update(_apply)

    if clear_key:
        try:
            _secret_path(workspace).unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove the stored n8n API key file")
            raise ValueError("Could not clear the stored API key") from None

    return read_n8n_config(workspace)
