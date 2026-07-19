"""Advisor blueprint - conversational and streaming advisor endpoints.

Provides AI advisor chat (single-turn and streaming SSE) and advisor status.
"""

from __future__ import annotations

import json as _json
import logging
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

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


def _capture_session(
    body: dict[str, Any],
    raw_messages: Any,
    assistant_reply: str = "",
) -> None:
    """Best-effort AI2 session capture — must never break a chat.

    Records the request's conversation history (and, when supplied, the fresh
    assistant reply) into the app-owned AiSessionStore under the client's
    ``session_id``. No ``session_id`` in the body → no capture (the frontend
    omits it for Explore/demo sessions, so fabricated chats never persist).
    Message ids are content-hash-derived in the store, so replaying the full
    history each request never duplicates rows. Streamed replies are picked
    up from the next request's history (only a session's final streamed reply
    can be missed).
    """
    try:
        session_id = str(body.get("session_id", "") or "").strip()
        if not session_id:
            return
        store = current_app.config.get("AI_SESSION_STORE")
        if store is None:
            return
        captured: list[dict[str, Any]] = []
        if isinstance(raw_messages, list):
            for msg in raw_messages:
                if isinstance(msg, dict):
                    captured.append(
                        {"role": msg.get("role", ""), "content": msg.get("content", "")}
                    )
        if assistant_reply.strip():
            captured.append({"role": "assistant", "content": assistant_reply})
        if captured:
            store.record_exchange(session_id, "advisor", captured)
    except Exception:  # noqa: BLE001 - capture is never chat-critical
        logger.debug("AI session capture failed", exc_info=True)


def _is_llm_configured() -> bool:
    """Check whether the LLM provider is configured."""
    try:
        cfg = LLMConfig.from_env()
        return bool(cfg.provider)
    except Exception:
        return False


def _coerce_context(raw: Any) -> str:
    """Normalise the request's ``context`` field to a single string.

    The frontend sends ``context`` either as a plain string (legacy) or as an
    object describing the current UI state (e.g. ``{"route": "/lab",
    "activeWidget": "OptionChain"}``). Calling ``.strip()`` on the object form
    raised AttributeError and 500'd the advisor for the floating help pill,
    which always sends an object — so accept both shapes here.
    """
    if isinstance(raw, dict):
        return ", ".join(f"{k}: {v}" for k, v in raw.items() if v not in (None, "", []))
    if isinstance(raw, str):
        return raw.strip()
    return ""


@advisor_bp.route("/advisor", methods=["POST"])
def advisor_chat() -> tuple[Any, int]:
    """Chat with the AI advisor via the configured LLM backend.

    Request JSON (conversation history — preferred):
        messages (list[dict]): Array of ``{role, content}`` dicts.
        context (str | dict, optional): Additional context (e.g. current
            positions, or a UI-state object like ``{route, activeWidget}``).

    Request JSON (legacy single-message):
        message (str): User's message text.
        context (str | dict, optional): Additional context.

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
    context: str = _coerce_context(body.get("context"))

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
            _capture_session(body, raw_messages, assistant_reply=response.content or "")
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
    context: str = _coerce_context(body.get("context"))

    # Build conversation (same logic as /advisor)
    raw_messages = body.get("messages")
    # AI2 capture: the request history (incl. the PREVIOUS streamed reply the
    # frontend appended) persists before streaming starts; the fresh reply is
    # picked up from the next request's history.
    _capture_session(body, raw_messages)
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
