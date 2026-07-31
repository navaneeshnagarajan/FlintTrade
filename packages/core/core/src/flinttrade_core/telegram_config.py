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
import re
from pathlib import Path
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

# The complete set of operator-facing refusals this module authors. A route
# renders its response body from this table rather than from the exception it
# caught, so that a ``ValueError`` raised BENEATH us can never reach a client:
# ``update_workspace_config`` alone raises a ``json.JSONDecodeError`` (itself a
# ``ValueError``) for a malformed ``workspace.json`` and two more carrying
# internal workspace-version detail. Those are not settings refusals and must
# fail as a generic server error, not as a 400 quoting our internals.
TELEGRAM_REFUSALS: dict[str, str] = {
    "enabled_not_bool": "enabled must be a boolean",
    "chat_id_not_string": "chat_id must be a string",
    "chat_id_not_numeric": "chat_id must be a numeric Telegram chat id",
    "clear_token_not_bool": "clear_token must be a boolean",
    "bot_token_not_string": "bot_token must be a string",
    "bot_token_malformed": "bot_token does not look like a Telegram bot token",
    "token_and_clear_conflict": "bot_token and clear_token are mutually exclusive",
    "incomplete_enable": "Enabling Telegram requires both a bot token and a chat id",
    "clear_token_failed": "Could not clear the stored bot token",
}

_GENERIC_REFUSAL = "Telegram settings rejected"


class TelegramConfigError(ValueError):
    """A settings refusal authored here, safe to show the operator.

    Subclasses ``ValueError`` so existing callers that catch ``ValueError``
    keep working, but lets a caller distinguish *our* curated refusals from an
    arbitrary ``ValueError`` thrown by a layer underneath.

    Attributes:
        code: The :data:`TELEGRAM_REFUSALS` key naming this refusal.
    """

    def __init__(self, code: str) -> None:
        """Build the refusal named by ``code``.

        Args:
            code: A key of :data:`TELEGRAM_REFUSALS`.
        """
        super().__init__(TELEGRAM_REFUSALS[code])
        self.code = code


def refusal_message(code: str) -> str:
    """Return the fixed operator-facing sentence for a refusal code.

    Args:
        code: A :data:`TELEGRAM_REFUSALS` key, typically ``TelegramConfigError.code``.

    Returns:
        The caller-facing sentence, or a generic refusal for an unknown code.
    """
    return TELEGRAM_REFUSALS.get(code, _GENERIC_REFUSAL)


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
        TelegramConfigError: On any malformed field — nothing is written in
            that case. It subclasses ``ValueError``; any *other* ``ValueError``
            escaping this function came from a layer underneath and is a
            server fault, not a settings refusal.
    """
    workspace = ws or Workspace()
    current = read_telegram_config(workspace)

    enabled = payload.get("enabled", current["enabled"])
    if not isinstance(enabled, bool):
        raise TelegramConfigError("enabled_not_bool")

    chat_id = payload.get("chat_id", current["chat_id"])
    if not isinstance(chat_id, str):
        raise TelegramConfigError("chat_id_not_string")
    chat_id = chat_id.strip()
    if chat_id and not _CHAT_ID_PATTERN.match(chat_id):
        raise TelegramConfigError("chat_id_not_numeric")

    clear_token = payload.get("clear_token", False)
    if not isinstance(clear_token, bool):
        raise TelegramConfigError("clear_token_not_bool")

    new_token = payload.get("bot_token", "")
    if new_token is None:
        new_token = ""
    if not isinstance(new_token, str):
        raise TelegramConfigError("bot_token_not_string")
    new_token = new_token.strip()
    if new_token and not _TOKEN_PATTERN.match(new_token):
        raise TelegramConfigError("bot_token_malformed")
    if new_token and clear_token:
        raise TelegramConfigError("token_and_clear_conflict")

    # Fail closed BEFORE writing anything: enabling requires a complete config.
    would_have_token = bool(new_token) or (not clear_token and bool(resolve_telegram_bot_token(workspace)))
    if enabled and not (chat_id and would_have_token):
        raise TelegramConfigError("incomplete_enable")

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
            raise TelegramConfigError("clear_token_failed") from None

    return read_telegram_config(workspace)
