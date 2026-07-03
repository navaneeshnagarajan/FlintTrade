"""Obsidian vault HTTP routes.

Exposes the :class:`~flinttrade_ai.obsidian_bridge.ObsidianVault` so the terminal
and the AI agent can browse, read, write, and search the operator's Obsidian
vault. The vault path comes from ``FLINTTRADE_OBSIDIAN_VAULT``; when it is unset
the routes return an honest 503 rather than pretending a vault exists.

Routes (all under the backend ``/api/v1`` prefix):

    GET  /api/v1/ai/obsidian/status   — configured? available? vault path
    GET  /api/v1/ai/obsidian/notes    — list every note (relative paths)
    GET  /api/v1/ai/obsidian/note?path=…  — read a note
    POST /api/v1/ai/obsidian/note     — write a note {path, content}
    GET  /api/v1/ai/obsidian/search?q=…   — search notes
"""

from __future__ import annotations

import logging
import os
from typing import Any

from flask import Blueprint, jsonify, request

from .obsidian_bridge import ObsidianError, ObsidianVault

logger = logging.getLogger("flinttrade.ai.obsidian_routes")

obsidian_bp = Blueprint("obsidian", __name__, url_prefix="/api/v1")

_VAULT_ENV = "FLINTTRADE_OBSIDIAN_VAULT"


def _vault() -> ObsidianVault | None:
    path = os.environ.get(_VAULT_ENV, "").strip()
    return ObsidianVault(path) if path else None


def _not_configured() -> tuple[Any, int]:
    return (
        jsonify(
            {
                "status": "error",
                "message": f"Obsidian vault not configured (set {_VAULT_ENV})",
            }
        ),
        503,
    )


@obsidian_bp.route("/ai/obsidian/status", methods=["GET"])
def obsidian_status() -> tuple[Any, int]:
    vault = _vault()
    return (
        jsonify(
            {
                "status": "success",
                "data": {
                    "configured": vault is not None,
                    "available": bool(vault and vault.available),
                    "vault_path": str(vault.root) if vault else None,
                },
            }
        ),
        200,
    )


@obsidian_bp.route("/ai/obsidian/notes", methods=["GET"])
def obsidian_notes() -> tuple[Any, int]:
    vault = _vault()
    if vault is None:
        return _not_configured()
    return jsonify({"status": "success", "data": vault.list_notes()}), 200


@obsidian_bp.route("/ai/obsidian/note", methods=["GET"])
def obsidian_read() -> tuple[Any, int]:
    vault = _vault()
    if vault is None:
        return _not_configured()
    path = request.args.get("path", "").strip()
    try:
        content = vault.read_note(path)
    except ObsidianError:
        return jsonify({"status": "error", "message": "Requested resource was not found"}), 404
    return jsonify({"status": "success", "data": {"path": path, "content": content}}), 200


@obsidian_bp.route("/ai/obsidian/note", methods=["POST"])
def obsidian_write() -> tuple[Any, int]:
    vault = _vault()
    if vault is None:
        return _not_configured()
    body: dict[str, Any] = request.get_json(silent=True) or {}
    path = str(body.get("path", "")).strip()
    content = str(body.get("content", ""))
    if not path:
        return jsonify({"status": "error", "message": "'path' is required"}), 400
    try:
        rel = vault.write_note(path, content)
    except ObsidianError:
        return jsonify({"status": "error", "message": "Invalid request"}), 400
    return jsonify({"status": "success", "data": {"path": rel}}), 200


@obsidian_bp.route("/ai/obsidian/search", methods=["GET"])
def obsidian_search() -> tuple[Any, int]:
    vault = _vault()
    if vault is None:
        return _not_configured()
    query = request.args.get("q", "")
    return jsonify({"status": "success", "data": vault.search(query)}), 200
