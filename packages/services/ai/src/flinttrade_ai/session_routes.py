"""AI session routes — list / read / search / import / delete chat sessions.

Read surface for the :class:`flinttrade_ai.session_store.AiSessionStore`
(reference-map AI2). Registered under ``/api/v1/ai/sessions``. Reads follow
the /api/v1 family's auth; imports and deletes additionally require the
operator session via the app-configured write guard (same dependency
direction as the broker management guard, G9).
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from .session_store import AiSessionStore

logger = logging.getLogger("flinttrade.ai.session_routes")

session_bp = Blueprint("ai_sessions", __name__, url_prefix="/api/v1/ai/sessions")

# Import caps (localStorage-migration spec §4): surfaces the one-time client
# import may write, and hard limits that keep a single request bounded.
_IMPORT_SURFACES = {"advisor", "tutor", "saved-chat"}
# Live-capture surfaces whose sessions a "saved-chat" import may target: the
# Share flow saves the SAME conversation the advisor/tutor capture already
# recorded under the SAME id, so that collision is a promotion, not a clash.
_SAVED_CHAT_PROMOTABLE_SURFACES = {"advisor", "tutor"}
_IMPORT_MAX_MESSAGES = 500
_IMPORT_MAX_CONTENT_BYTES = 32 * 1024
# Explicit import ids become the sessions primary key (echoed by every later
# list) so they are bounded like every other import field; out-of-shape ids
# fall back to the derived deterministic ``imp-`` id. Checked with fullmatch —
# a $-anchored match would admit a trailing newline.
_IMPORT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# Optional per-message ids let byte-identical chunk contents coexist: the
# store's content-hash fallback collapses equal same-role messages, which
# silently loses chunks of highly repetitive content. Out-of-shape ids are
# ignored (content-hash fallback) rather than refused so legacy payloads keep
# importing. Accepted ids are namespaced per session before storage — the
# messages table's id column is a global primary key, so an unscoped client id
# reused across sessions would silently drop the second session's message.
_IMPORT_MESSAGE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def _store() -> AiSessionStore | None:
    return current_app.config.get("AI_SESSION_STORE")


def _unavailable() -> tuple[Any, int]:
    return jsonify({"status": "error", "message": "AI session store unavailable"}), 503


@session_bp.route("", methods=["GET"])
def list_sessions() -> tuple[Any, int]:
    """Newest-first session summaries.

    Query parameters:
        limit (int, default 50), surface (advisor|tutor|agent|saved-chat, optional).
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


def _derived_import_id(surface: str, messages: list[dict[str, Any]]) -> str:
    """Deterministic session id for imports without one (idempotent re-import)."""
    digest = hashlib.sha1()
    digest.update(surface.encode())
    for message in messages:
        digest.update(b"\x00")
        digest.update(str(message.get("role", "") or "").encode())
        digest.update(b"\x00")
        digest.update(str(message.get("content", "") or "").encode())
    return f"imp-{digest.hexdigest()[:20]}"


@session_bp.route("/import", methods=["POST"])
def import_session() -> tuple[Any, int]:
    """Import a client-held conversation (operator-session-guarded write).

    Body: ``{id?, surface, title?, messages: [{id?, role, content,
    timestamp?: ms}]}``. Message ids make re-imports idempotent: an explicit
    per-message ``id`` (fullmatch ``[A-Za-z0-9_.:-]{1,128}``, namespaced per
    session before storage; out-of-shape ids are ignored) lets byte-identical
    chunk contents coexist, while messages without one fall back to the
    store's content-hash ids, which collapse equal same-role contents. A
    message ``timestamp`` (epoch milliseconds) becomes its stored
    ``created_at``. An explicit session ``id`` must fullmatch
    ``[A-Za-z0-9_-]{1,64}`` (otherwise the derived ``imp-`` id is used),
    and an id that names an existing session of a different surface is
    refused with 400 rather than appending into that conversation. The one
    exception is the Share flow's promotion: a ``saved-chat`` import may
    target an existing ``advisor``/``tutor`` session — that is the same
    operator saving the same live-captured conversation under its own id
    (the stored surface stays unchanged; reads serve the id regardless).
    """
    guard = current_app.config.get("BROKER_MGMT_WRITE_GUARD")
    if callable(guard):
        denied = guard()
        if denied is not None:
            return denied
    store = _store()
    if store is None:
        return _unavailable()

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"status": "error", "message": "Request body must be a JSON object"}), 400
    surface = str(body.get("surface", "") or "").strip()
    if surface not in _IMPORT_SURFACES:
        return (
            jsonify({"status": "error", "message": f"surface must be one of {sorted(_IMPORT_SURFACES)}"}),
            400,
        )
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return jsonify({"status": "error", "message": "messages must be a non-empty list"}), 400
    if len(messages) > _IMPORT_MAX_MESSAGES:
        return (
            jsonify(
                {"status": "error", "message": f"messages must contain at most {_IMPORT_MAX_MESSAGES} entries"}
            ),
            400,
        )

    prepared: list[dict[str, Any]] = []
    message_ids: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            return jsonify({"status": "error", "message": "each message must be an object"}), 400
        content = str(message.get("content", "") or "")
        if len(content.encode("utf-8")) > _IMPORT_MAX_CONTENT_BYTES:
            return (
                jsonify({"status": "error", "message": "message content must be at most 32 KiB"}),
                400,
            )
        entry: dict[str, Any] = {"role": message.get("role"), "content": content}
        raw_message_id = message.get("id")
        message_id = raw_message_id.strip() if isinstance(raw_message_id, str) else ""
        if message_id and not _IMPORT_MESSAGE_ID_RE.fullmatch(message_id):
            # Out-of-shape ids are ignored, not refused: the content-hash
            # fallback still imports the message (collapsing byte-identical
            # same-role contents, the pre-id behaviour).
            message_id = ""
        message_ids.append(message_id)
        timestamp = message.get("timestamp")
        if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool) and timestamp > 0:
            try:
                entry["created_at"] = datetime.fromtimestamp(timestamp / 1000, tz=UTC).isoformat()
            except (OverflowError, OSError, ValueError):
                pass  # Nonsense legacy timestamps fall back to the import time.
        prepared.append(entry)

    requested_id = str(body.get("id", "") or "").strip()
    if requested_id and not _IMPORT_ID_RE.fullmatch(requested_id):
        # Unbounded or out-of-alphabet legacy ids never become a primary key;
        # the derived id keeps re-imports of the same content idempotent.
        requested_id = ""
    session_id = requested_id or _derived_import_id(surface, prepared)
    existing_surface = store.session_surface(session_id)
    if (
        existing_surface is not None
        and existing_surface != surface
        and not (surface == "saved-chat" and existing_surface in _SAVED_CHAT_PROMOTABLE_SURFACES)
    ):
        # record_exchange upserts by id, so an id collision would silently
        # append imported messages into an unrelated live conversation.
        # Exception: saved-chat promotion of a live advisor/tutor capture —
        # the Share flow re-imports the SAME conversation under the SAME id,
        # and the upsert only bumps last_at, so the stored surface persists.
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"session id already belongs to a different surface ({existing_surface})",
                }
            ),
            400,
        )
    for entry, message_id in zip(prepared, message_ids):
        if message_id:
            # Namespace accepted client message ids by the resolved session so
            # the same client id in two different imports can never collide on
            # the messages table's global primary key (which would silently
            # drop the later session's message).
            entry["id"] = f"imp:{session_id}:{message_id}"
    title_raw = body.get("title")
    title = title_raw.strip() if isinstance(title_raw, str) and title_raw.strip() else None
    try:
        store.record_exchange(session_id, surface, prepared, title=title)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    if store.get_session(session_id) is None:
        # Every message was skipped (blank content / unknown roles) — nothing stored.
        return jsonify({"status": "error", "message": "messages contained no importable entries"}), 400
    return jsonify({"status": "success", "data": {"session_id": session_id}}), 200


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
