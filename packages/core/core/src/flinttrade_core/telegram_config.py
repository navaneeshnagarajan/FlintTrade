"""UI-persisted Telegram notification settings.

Mirrors the ``llm_config`` discipline: the bot token lives in a hardened
owner-only secret file under ``<workspace_dir>/secrets/``, and
``workspace.json`` carries only a ``secret://`` reference plus the non-secret
fields (enabled flag, chat id). The raw token never enters ``workspace.json``
or any API response — reads report only whether a token is set.

This closes the env-only gap for the Telegram kill-switch bot: an operator
can now configure it entirely from Settings → Telegram, with environment
variables (``TELEGRAM_BOT_TOKEN`` etc.) remaining an override for
server-style deployments.
"""

from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any

from .secure_file import read_owner_owned_text, write_secret_text
from .workspace import Workspace

logger = logging.getLogger("flinttrade.core.telegram_config")

TELEGRAM_BOT_TOKEN_REF = "secret://telegram/bot_token"

# Telegram bot tokens look like "<bot-id>:<35-ish char secret>"; chat ids are
# signed integers (supergroups use a -100 prefix). Validation is deliberately
# loose enough to survive Telegram format drift but tight enough to reject
# pasted URLs, whole config lines, or secret:// references.
_TOKEN_PATTERN = re.compile(r"^\d{1,14}:[A-Za-z0-9_-]{20,90}$")
_CHAT_ID_PATTERN = re.compile(r"^-?\d{1,20}$")


def _secret_path(ws: Workspace) -> Path:
    return ws.workspace_dir / "secrets" / "telegram_bot_token"


def resolve_telegram_bot_token(ws: Workspace | None = None) -> str:
    """Read the stored bot token, or ``""`` when none is configured."""
    workspace = ws or Workspace()
    try:
        return read_owner_owned_text(_secret_path(workspace)).strip()
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return ""


def read_telegram_config(ws: Workspace | None = None) -> dict[str, Any]:
    """Redacted settings for the UI — never includes the token itself."""
    workspace = ws or Workspace()
    return {
        "enabled": bool(workspace.get("notifications.telegram_enabled", False)),
        "chat_id": str(workspace.get("notifications.telegram_chat_id", "") or ""),
        "bot_token_set": bool(resolve_telegram_bot_token(workspace)),
    }


def persist_telegram_config(payload: dict[str, Any], ws: Workspace | None = None) -> dict[str, Any]:
    """Validate and persist Telegram settings from the UI.

    Payload fields — ABSENT fields preserve the current stored value (a bare
    ``{}`` POST is a no-op, never a destructive disable/erase):
        enabled (bool): turn the bot on or off.
        chat_id (str): authorised chat id (required when enabling). An
            explicit empty string clears the stored chat id.
        bot_token (str, optional): a NEW token to store. An absent or blank
            value preserves any existing stored token (the Settings form's
            blank-keeps-existing convention).
        clear_token (bool, optional): explicitly forget the stored token.

    Returns:
        The redacted post-save state (same shape as ``read_telegram_config``).

    Raises:
        ValueError: On any malformed field — nothing is written in that case.
    """
    workspace = ws or Workspace()
    current = read_telegram_config(workspace)

    enabled = payload.get("enabled", current["enabled"])
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean")

    chat_id = payload.get("chat_id", current["chat_id"])
    if not isinstance(chat_id, str):
        raise ValueError("chat_id must be a string")
    chat_id = chat_id.strip()
    if chat_id and not _CHAT_ID_PATTERN.match(chat_id):
        raise ValueError("chat_id must be a numeric Telegram chat id")

    clear_token = payload.get("clear_token", False)
    if not isinstance(clear_token, bool):
        raise ValueError("clear_token must be a boolean")

    new_token = payload.get("bot_token", "")
    if new_token is None:
        new_token = ""
    if not isinstance(new_token, str):
        raise ValueError("bot_token must be a string")
    new_token = new_token.strip()
    if new_token and not _TOKEN_PATTERN.match(new_token):
        raise ValueError("bot_token does not look like a Telegram bot token")
    if new_token and clear_token:
        raise ValueError("bot_token and clear_token are mutually exclusive")

    # Fail closed BEFORE writing anything: enabling requires a complete config.
    would_have_token = bool(new_token) or (not clear_token and bool(resolve_telegram_bot_token(workspace)))
    if enabled and not (chat_id and would_have_token):
        raise ValueError("Enabling Telegram requires both a bot token and a chat id")

    # Secret WRITE first: if it fails, workspace.json is untouched. The
    # secret DELETE comes after the workspace transaction instead — if the
    # transaction fails mid-clear, the token file is still present and the
    # config stays functional, rather than a silently token-less enabled bot.
    if new_token:
        write_secret_text(_secret_path(workspace), new_token)

    # ONE workspace transaction: per-key set() calls would be three separate
    # read-modify-write commits (torn state on a mid-sequence failure), and a
    # trailing full save() would clobber concurrent workspace writers with
    # this process's stale in-memory snapshot.
    def _apply(config: dict[str, Any]) -> None:
        notifications = config.setdefault("notifications", {})
        notifications["telegram_enabled"] = enabled
        notifications["telegram_chat_id"] = chat_id
        notifications["telegram_bot_token_ref"] = (
            TELEGRAM_BOT_TOKEN_REF if would_have_token else ""
        )

    workspace.update(_apply)

    if clear_token:
        try:
            _secret_path(workspace).unlink(missing_ok=True)
        except OSError:
            # The workspace already says "no token" (disabled, ref cleared) —
            # an orphaned secret file is inert but must be reported.
            logger.warning("Could not remove the stored Telegram bot token file")
            raise ValueError("Could not clear the stored bot token") from None

    return read_telegram_config(workspace)
