"""WhatsApp alert Flask endpoints.

Registered as a Blueprint in ``create_flask_app()``.

Endpoints
---------
POST /api/v1/alerts/whatsapp/test  — send a test message via WhatsApp webhook
"""
from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from .whatsapp_alerts import WhatsAppAlerter, WhatsAppConfig

logger = logging.getLogger("flinttrade.automation.whatsapp_routes")

whatsapp_bp = Blueprint("whatsapp", __name__, url_prefix="/api/v1")

# Module-level singleton — replaced by ``init_whatsapp_routes`` when injected.
_alerter: WhatsAppAlerter | None = None


def _get_alerter() -> WhatsAppAlerter:
    """Return the module-level alerter singleton, creating it lazily."""
    global _alerter  # noqa: PLW0603
    if _alerter is None:
        _alerter = WhatsAppAlerter()
    return _alerter


def init_whatsapp_routes(alerter: WhatsAppAlerter) -> None:
    """Inject a WhatsAppAlerter instance into the blueprint's singleton.

    Args:
        alerter: The :class:`WhatsAppAlerter` instance to use.
    """
    global _alerter  # noqa: PLW0603
    _alerter = alerter
    logger.info("WhatsAppAlerter singleton injected into whatsapp_routes")


@whatsapp_bp.route("/alerts/whatsapp/test", methods=["POST"])
def test_whatsapp() -> tuple[Any, int]:
    """Send a test message to verify WhatsApp webhook configuration.

    Request JSON (optional):
        message (str): Custom test message (default: "FlintTrade WhatsApp test").

    Returns:
        JSON ``{"status": "success", "message": "Test message sent"}`` on success,
        or ``{"status": "error", "message": "..."}`` on failure.
    """
    alerter = _get_alerter()

    if not alerter.is_configured:
        return jsonify({
            "status": "error",
            "message": "WhatsApp not configured — set WHATSAPP_WEBHOOK_URL and WHATSAPP_ENABLED",
        }), 400

    body = request.get_json(silent=True) or {}
    text = body.get("message", "FlintTrade WhatsApp test — connection verified!")

    success = alerter.send_alert(text)

    if success:
        return jsonify({
            "status": "success",
            "message": "Test message sent",
        }), 200

    return jsonify({
        "status": "error",
        "message": "Failed to send test message — check webhook URL and logs",
    }), 502
