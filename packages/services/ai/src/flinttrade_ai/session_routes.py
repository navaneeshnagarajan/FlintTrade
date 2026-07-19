"""AI session routes — list / read / search / delete persisted chat sessions.

Read surface for the :class:`flinttrade_ai.session_store.AiSessionStore`
(reference-map AI2). Registered under ``/api/v1/ai/sessions``. Reads follow
the /api/v1 family's auth; deletes additionally require the operator session
via the app-configured write guard (same dependency direction as the broker
management guard, G9).
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from .session_store import AiSessionStore

logger = logging.getLogger("flinttrade.ai.session_routes")

session_bp = Blueprint("ai_sessions", __name__, url_prefix="/api/v1/ai/sessions")


def _store() -> AiSessionStore | None:
    return current_app.config.get("AI_SESSION_STORE")


def _unavailable() -> tuple[Any, int]:
    return jsonify({"status": "error", "message": "AI session store unavailable"}), 503


@session_bp.route("", methods=["GET"])
def list_sessions() -> tuple[Any, int]:
    """Newest-first session summaries.

    Query parameters:
        limit (int, default 50), surface (advisor|tutor|agent, optional).
    """
    store = _store()
    if store is None:
        return _unavailable()
    try:
        limit = min(int(request.args.get("limit", "50")), 200)
        if limit < 1:
            raise ValueError
    except ValueError:
        return jsonify({"status": "error", "message": "limit must be a positive integer"}), 400
    surface = request.args.get("surface") or None
    return (
        jsonify({"status": "success", "data": store.list_sessions(limit=limit, surface=surface)}),
        200,
    )


@session_bp.route("/search", methods=["GET"])
def search_sessions() -> tuple[Any, int]:
    """Full-text search across message content (``?q=``)."""
    store = _store()
    if store is None:
        return _unavailable()
    query = request.args.get("q", "")
    return jsonify({"status": "success", "data": store.search(query, limit=50)}), 200


@session_bp.route("/<session_id>", methods=["GET"])
def get_session(session_id: str) -> tuple[Any, int]:
    """One session with its ordered messages."""
    store = _store()
    if store is None:
        return _unavailable()
    session = store.get_session(session_id)
    if session is None:
        return jsonify({"status": "error", "message": "Session not found"}), 404
    return jsonify({"status": "success", "data": session}), 200


@session_bp.route("/<session_id>", methods=["DELETE"])
def delete_session(session_id: str) -> tuple[Any, int]:
    """Delete a stored session (operator-session-guarded write)."""
    guard = current_app.config.get("BROKER_MGMT_WRITE_GUARD")
    if callable(guard):
        denied = guard()
        if denied is not None:
            return denied
    store = _store()
    if store is None:
        return _unavailable()
    if not store.delete_session(session_id):
        return jsonify({"status": "error", "message": "Session not found"}), 404
    return jsonify({"status": "success", "message": "Session deleted"}), 200
