"""Advisor blueprint - conversational and streaming advisor endpoints.

Provides AI advisor chat (single-turn and streaming SSE) and advisor status.
"""

from __future__ import annotations

import json as _json
import logging
import os
from typing import Any

import jwt
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
    "without proper risk disclaimers. Practice SandboxEngine fills and native "
    "Connected (read) feeds are analysis context only — not a live order path "
    "and not a guarantee of profitable alphas. Never place or claim to place "
    "a Live order. Kotak Neo has no Practice sandbox."
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


def _llm_readiness_source() -> str:
    """Classify LLM readiness: env override, stored workspace, or empty default.

    ``LLMConfig.from_env()`` defaults a blank stored provider to ollama.
    That implicit default is not a configured LLM. ``LLM_PROVIDER`` counts
    as an explicit env-only setup.
    """
    if os.getenv("LLM_PROVIDER", "").strip():
        return "env"
    try:
        from flinttrade_core.llm_config import read_llm_config

        if str(read_llm_config().get("provider") or "").strip():
            return "stored"
    except Exception:
        pass
    return "default"


def _is_llm_configured() -> bool:
    """Check whether an explicit LLM provider is configured."""
    try:
        return _llm_readiness_source() != "default"
    except Exception:
        return False


def _jwt_mode() -> str | None:
    """Return the signed JWT ``mode`` claim, or ``None`` when absent/invalid."""
    from flinttrade_core.auth_routes import decode_token  # lazy: avoid import cycle

    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        token = request.headers.get("X-FlintTrade-Token", "").strip()
    if not token:
        return None
    try:
        payload = decode_token(token)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
    if not isinstance(payload, dict):
        return None
    mode = payload.get("mode")
    return mode if isinstance(mode, str) else None


def _practice_sandbox_book_context() -> str:
    """Return the Practice SandboxEngine book when the JWT is Practice.

    Desk/AI read the same paper fills that ``orders/place`` recorded. Explore
    stays sample-only. Live never receives this paper book — native
    Connected (read) feeds are a separate path (FT-MONDAY-003).
    """
    if _jwt_mode() != "practice":
        return ""
    engine = current_app.config.get("DATA_SANDBOX_ENGINE")
    if engine is None:
        return ""
    try:
        positions = engine.get_positions()
        orders = engine.get_orders()
        trades = engine.get_trades()
    except Exception:  # noqa: BLE001 - advisor must never 500 on a book read
        logger.debug("Practice sandbox book read failed", exc_info=True)
        return ""
    return (
        "Practice SandboxEngine book (paper fills only; not a live broker):\n"
        f"positions: {positions}\n"
        f"orders: {orders}\n"
        f"trades: {trades}"
    )


def _native_live_read_symbols(raw: Any) -> list[str]:
    """Prefer the request symbol; otherwise the Monday smoke default."""
    symbol, exchange = "RELIANCE", "NSE"
    if isinstance(raw, dict):
        requested = str(raw.get("symbol") or "").strip()
        venue = str(raw.get("exchange") or "").strip().upper()
        if requested:
            symbol = requested
        if venue:
            exchange = venue
    return [f"{exchange}:{symbol}"]


def _native_live_read_context(raw: Any = None) -> str:
    """Inject authorised Dhan/Neo Connected (read) quotes when the JWT may analyse.

    Practice and Live JWTs may consume stamped ``read_smoke_ok`` feeds after
    ``admin.accounts.read`` and each account ACL via the authorised
    broker-context / read-port boundary. Explore stays dark. Never enumerates
    raw registry sessions, never places, and never invents Neo Practice.
    """
    if _jwt_mode() not in {"practice", "live"}:
        return ""
    try:
        from flinttrade_core.ai_broker_context import collect_authorised_monday_read_feeds
        from flinttrade_gateway.monday_read_smoke import format_monday_ai_read_context

        hook = current_app.config.get("MONDAY_AI_READ_FEED_COLLECTOR")
        if callable(hook):
            rows = hook()
            if not isinstance(rows, list):
                return ""
            return format_monday_ai_read_context(rows)

        pair = _native_live_read_symbols(raw)[0]
        exchange, _, symbol = pair.partition(":")
        rows = collect_authorised_monday_read_feeds(symbol, exchange)
        return format_monday_ai_read_context(rows)
    except Exception:  # noqa: BLE001 - advisor must never 500 on a read feed
        logger.debug("Native live-read AI context failed", exc_info=True)
        return ""


def _merge_request_context(raw: Any) -> str:
    """Flatten request context plus Practice book and Connected (read) feeds."""
    context = _coerce_context(raw)
    extras: list[str] = []
    practice_book = _practice_sandbox_book_context()
    if practice_book:
        extras.append(practice_book)
    native_reads = _native_live_read_context(raw)
    if native_reads:
        extras.append(native_reads)
    if not extras:
        return context
    glued = "\n".join(extras)
    if not context:
        return glued
    return f"{context}\n{glued}"


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
    context: str = _merge_request_context(body.get("context"))

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
    context: str = _merge_request_context(body.get("context"))

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
            emitted = False
            for token in client.chat_stream(conversation):
                emitted = True
                yield f"data: {_json.dumps({'token': token})}\n\n"
            if not emitted:
                # A token-less completion used to emit only ``{done: true}``.
                # The frontend treated that as success and persisted a blank
                # assistant bubble — fail closed with a visible error instead.
                yield f"data: {_json.dumps({'error': 'The LLM returned no reply. Check Settings → AI, or try again.'})}\n\n"
            else:
                yield f"data: {_json.dumps({'done': True})}\n\n"
            client.close()
        except Exception:
            logger.exception("Advisor stream error")
            yield f"data: {_json.dumps({'error': 'Internal server error'})}\n\n"

    return Response(_generate(), content_type="text/event-stream")


@advisor_bp.route("/advisor/status", methods=["GET"])
def advisor_status() -> tuple[Any, int]:
    """Check whether the AI advisor LLM backend is configured."""
    source = _llm_readiness_source()
    configured = _is_llm_configured()
    cfg = LLMConfig.from_env() if configured else None
    return jsonify({
        "status": "success",
        "data": {
            "configured": configured,
            "provider": cfg.provider if cfg else "",
            "model": cfg.model if cfg else "",
            "source": source,
        },
    }), 200
