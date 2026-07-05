"""Telegram alert test route backed by FlintTrade's automation service.

Endpoint
--------
POST /api/v1/telegram

This keeps the terminal's Telegram test-send on FlintTrade's local backend
instead of requiring an OpenAlgo API key. Explicit bot credentials are accepted
for one test send only and are never persisted or echoed back.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from flinttrade_automation.telegram_bot import BotConfig, TelegramBot

logger = logging.getLogger("flinttrade.core.telegram_routes")

telegram_bp = Blueprint("telegram", __name__, url_prefix="/api/v1")


def _clean(value: Any) -> str:
    return str(value or "").strip()


@telegram_bp.route("/telegram", methods=["POST"])
def send_telegram() -> tuple[Any, int]:
    """Send a Telegram test message through the configured bot."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"status": "error", "message": "JSON object body required"}), 400

    message = _clean(body.get("message"))
    if not message:
        return jsonify({"status": "error", "message": "message is required"}), 400
    if len(message) > 4096:
        return jsonify({"status": "error", "message": "message exceeds Telegram's 4096 character limit"}), 400

    bot_token = _clean(body.get("bot_token") or body.get("botToken") or body.get("token"))
    chat_id = _clean(body.get("chat_id") or body.get("chatId"))

    if bot_token or chat_id:
        if not bot_token or not chat_id:
            return jsonify({"status": "error", "message": "bot_token and chat_id are required together"}), 400
        config = BotConfig(token=bot_token, chat_id=chat_id, enabled=True)
    else:
        config = BotConfig.from_env()
        if not config.enabled:
            return jsonify({"status": "error", "message": "Telegram notifications are disabled"}), 400

    sent = TelegramBot(config=config).send_message(message)
    if not sent:
        logger.warning("Telegram test send failed")
        return jsonify({"status": "error", "message": "Telegram message could not be sent"}), 502

    return jsonify({"status": "success", "data": {"message": "sent"}}), 200
