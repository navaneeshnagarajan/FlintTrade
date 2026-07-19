"""Skill-draft review routes — list / read / approve / reject (AI1).

The operator approval surface for :mod:`flinttrade_ai.skill_drafts`.
Approve and reject are writes and go through the operator-session guard
(the same app-configured ``BROKER_MGMT_WRITE_GUARD`` the AI2 delete uses);
an approval also reloads the app-owned workspace SkillRegistry so the
newly approved skill is immediately loadable.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify

from . import skill_drafts

logger = logging.getLogger("flinttrade.ai.skill_draft_routes")

skill_draft_bp = Blueprint("skill_drafts", __name__, url_prefix="/api/v1/ai/skill-drafts")


def _workspace() -> Path | None:
    workspace = current_app.config.get("WORKSPACE_DIR")
    return Path(workspace) if workspace else None


def _unavailable() -> tuple[Any, int]:
    return jsonify({"status": "error", "message": "Workspace unavailable"}), 503


def _guard() -> Any:
    guard = current_app.config.get("BROKER_MGMT_WRITE_GUARD")
    if callable(guard):
        return guard()
    return None


@skill_draft_bp.route("", methods=["GET"])
def list_drafts() -> tuple[Any, int]:
    """Pending draft summaries, newest first."""
    workspace = _workspace()
    if workspace is None:
        return _unavailable()
    return jsonify({"status": "success", "data": skill_drafts.list_drafts(workspace)}), 200


@skill_draft_bp.route("/<name>", methods=["GET"])
def read_draft(name: str) -> tuple[Any, int]:
    """One draft's full markdown."""
    workspace = _workspace()
    if workspace is None:
        return _unavailable()
    content = skill_drafts.read_draft(workspace, name)
    if content is None:
        return jsonify({"status": "error", "message": "Draft not found"}), 404
    return jsonify({"status": "success", "data": {"name": name, "content": content}}), 200


@skill_draft_bp.route("/<name>/approve", methods=["POST"])
def approve_draft(name: str) -> tuple[Any, int]:
    """Approve a draft into the operator skills directory (guarded write)."""
    denied = _guard()
    if denied is not None:
        return denied
    workspace = _workspace()
    if workspace is None:
        return _unavailable()
    try:
        skill_drafts.approve_draft(workspace, name)
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid skill name"}), 400
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "Draft not found"}), 404

    registry = current_app.config.get("SKILL_REGISTRY")
    if registry is not None:
        try:
            registry.reload()
        except Exception:  # noqa: BLE001 - the file move already succeeded
            logger.warning("Skill registry reload failed after approval", exc_info=True)

    return jsonify({"status": "success", "message": f"Skill '{name}' approved"}), 200


@skill_draft_bp.route("/<name>", methods=["DELETE"])
def reject_draft(name: str) -> tuple[Any, int]:
    """Reject (delete) a draft (guarded write)."""
    denied = _guard()
    if denied is not None:
        return denied
    workspace = _workspace()
    if workspace is None:
        return _unavailable()
    if not skill_drafts.reject_draft(workspace, name):
        return jsonify({"status": "error", "message": "Draft not found"}), 404
    return jsonify({"status": "success", "message": f"Draft '{name}' rejected"}), 200
