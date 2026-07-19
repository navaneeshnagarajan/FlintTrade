"""UI-persisted WhatsApp alert settings.

Mirrors :mod:`flinttrade_core.telegram_config`: the webhook URL lives in a
hardened owner-only secret file (webhook URLs routinely embed tokens), and
``workspace.json`` carries only a ``secret://`` reference plus the enabled
flag. Reads are redacted to ``webhook_url_set``. Absent POST fields preserve
the current state; a legacy plaintext ``whatsapp.webhook_url`` workspace key
keeps working as a read fallback and is cleared the first time the UI saves.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .secure_file import read_owner_owned_text, write_secret_text
from .workspace import Workspace

logger = logging.getLogger("flinttrade.core.whatsapp_config")

WHATSAPP_WEBHOOK_URL_REF = "secret://whatsapp/webhook_url"


def _secret_path(ws: Workspace) -> Path:
    return ws.workspace_dir / "secrets" / "whatsapp_webhook_url"


def _validate_webhook_url(value: str) -> None:
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise ValueError("webhook_url is not a valid URL") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("webhook_url must be an http(s) URL")


def resolve_whatsapp_webhook_url(ws: Workspace | None = None) -> str:
    """Read the stored webhook URL, falling back to the legacy plaintext key."""
    workspace = ws or Workspace()
    try:
        stored = read_owner_owned_text(_secret_path(workspace)).strip()
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        stored = ""
    if stored:
        return stored
    legacy = str(workspace.get("whatsapp.webhook_url", "") or "")
    if legacy.startswith("secret://"):
        # Never treat a reference literal as the URL (fail closed).
        return ""
    return legacy


def read_whatsapp_config(ws: Workspace | None = None) -> dict[str, Any]:
    """Redacted settings for the UI — never includes the URL itself."""
    workspace = ws or Workspace()
    return {
        "enabled": bool(workspace.get("whatsapp.enabled", False)),
        "webhook_url_set": bool(resolve_whatsapp_webhook_url(workspace)),
    }


def persist_whatsapp_config(payload: dict[str, Any], ws: Workspace | None = None) -> dict[str, Any]:
    """Validate and persist WhatsApp settings from the UI.

    Payload fields — ABSENT fields preserve the current stored value:
        enabled (bool): turn WhatsApp alerts on or off.
        webhook_url (str, optional): a NEW webhook URL to store. Blank or
            absent preserves the existing one.
        clear_webhook_url (bool, optional): explicitly forget the stored URL.

    Returns:
        The redacted post-save state (same shape as ``read_whatsapp_config``).

    Raises:
        ValueError: On any malformed field — nothing is written in that case.
    """
    workspace = ws or Workspace()
    current = read_whatsapp_config(workspace)

    enabled = payload.get("enabled", current["enabled"])
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean")

    clear_url = payload.get("clear_webhook_url", False)
    if not isinstance(clear_url, bool):
        raise ValueError("clear_webhook_url must be a boolean")

    new_url = payload.get("webhook_url", "")
    if new_url is None:
        new_url = ""
    if not isinstance(new_url, str):
        raise ValueError("webhook_url must be a string")
    new_url = new_url.strip()
    if new_url:
        _validate_webhook_url(new_url)
    if new_url and clear_url:
        raise ValueError("webhook_url and clear_webhook_url are mutually exclusive")

    would_have_url = bool(new_url) or (
        not clear_url and bool(resolve_whatsapp_webhook_url(workspace))
    )
    if enabled and not would_have_url:
        raise ValueError("Enabling WhatsApp alerts requires a webhook URL")

    # Secret WRITE first (workspace untouched on failure); DELETE after the
    # transaction so a mid-clear failure leaves a functional config. When the
    # effective URL currently lives only in the legacy plaintext workspace
    # key, migrate it into the secret file NOW — the transaction below clears
    # that key, and a preserve-save must not lose the URL.
    if would_have_url:
        effective = new_url or resolve_whatsapp_webhook_url(workspace)
        write_secret_text(_secret_path(workspace), effective)

    def _apply(config: dict[str, Any]) -> None:
        whatsapp = config.setdefault("whatsapp", {})
        whatsapp["enabled"] = enabled
        whatsapp["webhook_url_ref"] = WHATSAPP_WEBHOOK_URL_REF if would_have_url else ""
        # The pre-UI plaintext key is superseded by the secret file; clear it
        # on the first save so the URL stops living in workspace.json.
        whatsapp["webhook_url"] = ""

    workspace.update(_apply)

    if clear_url:
        try:
            _secret_path(workspace).unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove the stored WhatsApp webhook URL file")
            raise ValueError("Could not clear the stored webhook URL") from None

    return read_whatsapp_config(workspace)
