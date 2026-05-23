"""Advisor blueprint — /api/v1/advisor/* and /api/v1/signals endpoints.

Provides AI advisor chat (single-turn and streaming SSE), advisor status, and
the initial signals stub endpoint.
"""

from __future__ import annotations

import json as _json
import logging
from typing import Any

from flask import Blueprint, Response, jsonify, request

from .llm_client import LLMClient, LLMConfig, LLMMessage

logger = logging.getLogger("flinttrade")

advisor_bp = Blueprint("advisor", __name__, url_prefix="/api/v1")

_SYSTEM_PROMPT = (
    "You are FlintTrade AI Advisor, a knowledgeable trading assistant for "
    "Indian markets (NSE, BSE, NFO, MCX). You help with market analysis, "
    "options strategies, technical indicators, and portfolio management. "
    "Be concise, accurate, and always remind users that your responses are "
    "informational — not financial advice. Never recommend specific trades "
    "without proper risk disclaimers."
)


def _is_llm_configured() -> bool:
    """Check whether the LLM provider is configured."""
    try:
        cfg = LLMConfig.from_env()
        return bool(cfg.provider)
    except Exception:
        return False


@advisor_bp.route("/advisor", methods=["POST"])
def advisor_chat() -> tuple[Any, int]:
    """Chat with the AI advisor via the configured LLM backend.

    Request JSON (conversation history — preferred):
        messages (list[dict]): Array of ``{role, content}`` dicts.
        context (str, optional): Additional context (e.g. current positions).

    Request JSON (legacy single-message):
        message (str): User's message text.
        context (str, optional): Additional context.

    Returns:
        JSON with ``status`` and ``data.response`` on success, or
        ``status`` and ``message`` on error.
    """
    if not _is_llm_configured():
        return jsonify({
            "status": "error",
            "message": (
                "LLM not configured. Set provider in Settings \u2192 AI."
            ),
        }), 503

    body = request.get_json(silent=True) or {}
    context: str = body.get("context", "").strip()

    # Accept messages[] array (new) or message string (legacy)
    raw_messages = body.get("messages")
    if isinstance(raw_messages, list) and raw_messages:
        # Conversation history supplied by the frontend
        conversation: list[LLMMessage] = [
            LLMMessage(role="system", content=_SYSTEM_PROMPT),
        ]
        if context:
            conversation.append(LLMMessage(
                role="system",
                content=f"Current trading context:\n{context}",
            ))
        for msg in raw_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role and content:
                conversation.append(LLMMessage(role=role, content=content))
    else:
        # Legacy: single message string
        user_message: str = body.get("message", "").strip()
        if not user_message:
            return jsonify({
                "status": "error",
                "message": "message or messages field is required.",
            }), 400
        conversation = [
            LLMMessage(role="system", content=_SYSTEM_PROMPT),
        ]
        if context:
            conversation.append(LLMMessage(
                role="system",
                content=f"Current trading context:\n{context}",
            ))
        conversation.append(LLMMessage(role="user", content=user_message))

    try:
        client = LLMClient()
        response = client.chat(conversation)
        client.close()

        if response.success:
            return jsonify({
                "status": "success",
                "data": {"response": response.content},
            }), 200

        return jsonify({
            "status": "error",
            "message": f"LLM error: {response.error}",
        }), 502
    except Exception:
        logger.exception("Advisor endpoint error")
        return jsonify({
            "status": "error",
            "message": "Internal server error",
        }), 500


@advisor_bp.route("/advisor/stream", methods=["POST"])
def advisor_stream() -> Response | tuple[Any, int]:
    """SSE streaming variant of the advisor endpoint.

    Accepts the same request body as ``/api/v1/advisor`` (messages[]
    array or legacy message string).  Returns a ``text/event-stream``
    response where each event carries a ``token`` field and the final
    event carries ``done: true``.
    """
    if not _is_llm_configured():
        return jsonify({
            "status": "error",
            "message": "LLM not configured. Set provider in Settings \u2192 AI.",
        }), 503

    body = request.get_json(silent=True) or {}
    context: str = body.get("context", "").strip()

    # Build conversation (same logic as /advisor)
    raw_messages = body.get("messages")
    if isinstance(raw_messages, list) and raw_messages:
        conversation: list[LLMMessage] = [
            LLMMessage(role="system", content=_SYSTEM_PROMPT),
        ]
        if context:
            conversation.append(LLMMessage(
                role="system",
                content=f"Current trading context:\n{context}",
            ))
        for msg in raw_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role and content:
                conversation.append(LLMMessage(role=role, content=content))
    else:
        user_message = body.get("message", "").strip()
        if not user_message:
            return jsonify({
                "status": "error",
                "message": "message or messages field is required.",
            }), 400
        conversation = [
            LLMMessage(role="system", content=_SYSTEM_PROMPT),
        ]
        if context:
            conversation.append(LLMMessage(
                role="system",
                content=f"Current trading context:\n{context}",
            ))
        conversation.append(LLMMessage(role="user", content=user_message))

    def _generate():  # type: ignore[no-untyped-def]
        try:
            client = LLMClient()
            for token in client.chat_stream(conversation):
                yield f"data: {_json.dumps({'token': token})}\n\n"
            yield f"data: {_json.dumps({'done': True})}\n\n"
            client.close()
        except Exception:
            logger.exception("Advisor stream error")
            yield f"data: {_json.dumps({'error': 'Internal server error'})}\n\n"

    return Response(_generate(), content_type="text/event-stream")


@advisor_bp.route("/advisor/status", methods=["GET"])
def advisor_status() -> tuple[Any, int]:
    """Check whether the AI advisor LLM backend is configured."""
    configured = _is_llm_configured()
    cfg = LLMConfig.from_env() if configured else None
    return jsonify({
        "status": "success",
        "data": {
            "configured": configured,
            "provider": cfg.provider if cfg else "",
            "model": cfg.model if cfg else "",
        },
    }), 200


@advisor_bp.route("/signals", methods=["GET"])
def get_signals() -> tuple[Any, int]:
    """Return current signal state (stub — populated by signal pipeline)."""
    return jsonify({
        "status": "success",
        "data": {"signals": []},
    }), 200
