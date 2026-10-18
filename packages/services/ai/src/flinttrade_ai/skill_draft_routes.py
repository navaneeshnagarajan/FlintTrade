"""Retained inputs: candidate intake and retirement, never an approval bypass."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from . import skill_drafts

skill_draft_bp = Blueprint("skill_drafts", __name__, url_prefix="/api/v1/ai/skill-drafts")


def _workspace() -> Path | None:
    workspace = current_app.config.get("WORKSPACE_DIR")
    return Path(workspace) if workspace else None


def _unavailable() -> tuple[Any, int]:
    return jsonify(status="error", message="Knowledge or workspace unavailable; source preserved"), 503


@skill_draft_bp.before_request
def _guard() -> Any:
    # Retained files can be personal material: reads need the same operator
    # session as writes, not only the factory's general inference API-key guard.
    guard = current_app.config.get("BROKER_MGMT_WRITE_GUARD")
    if not callable(guard):
        return jsonify(status="error", message="Operator-session guard unavailable"), 503
    denied = guard()
    if denied is not None:
        return denied
    if request.method in {"POST", "DELETE"} and request.get_data():
        try:
            body = json.loads(request.get_data())
        except ValueError:
            return jsonify(status="error", message="Expected empty JSON object"), 400
        if type(body) is not dict or body:
            return jsonify(status="error", message="No rights or validation assertions accepted"), 400
    return None


@skill_draft_bp.after_request
def _no_store(response: Any) -> Any:
    response.headers["Cache-Control"] = "no-store"
    return response


def _state(runtime: Any, version: str) -> dict[str, Any]:
    return next(row for row in runtime.store.catalogue() if row["version_id"] == version)


@skill_draft_bp.get("")
def list_drafts() -> tuple[Any, int]:
    """Retained inputs with candidate/retirement state, never a pending-approval queue."""
    workspace = _workspace()
    if workspace is None:
        return _unavailable()
    rows = skill_drafts.list_drafts(workspace)
    runtime = current_app.config.get("KNOWLEDGE_RUNTIME")
    versions = {row["name"]: row["version_id"] for row in runtime.refresh_inputs()
                if row["source"] == "skill_drafts"} if runtime else {}
    for row in rows:
        row.update(_state(runtime, versions[row["name"]]) if row["name"] in versions else
                   {"state": "unavailable", "enabled": False})
    return jsonify(status="success", data=rows), 200


@skill_draft_bp.get("/<name>")
def read_draft(name: str) -> tuple[Any, int]:
    """Read retained source bytes; frontmatter status is not activation state."""
    workspace = _workspace()
    if workspace is None:
        return _unavailable()
    try:
        content = skill_drafts.read_draft(workspace, name)
    except (OSError, ValueError):
        return jsonify(status="error", message="Draft unavailable"), 400
    if content is None:
        return jsonify(status="error", message="Draft not found"), 404
    return jsonify(status="success", data={"name": name, "content": content}), 200


@skill_draft_bp.post("/<name>/approve")
@skill_draft_bp.post("/<name>/candidate")
def approve_draft(name: str) -> tuple[Any, int]:
    """Legacy alias for intake; trusted independent validation remains separate."""
    runtime = current_app.config.get("KNOWLEDGE_RUNTIME")
    if _workspace() is None or runtime is None:
        return _unavailable()
    try:
        version = runtime.ingest_skill(name)
    except FileNotFoundError:
        return jsonify(status="error", message="Draft or declared member not found"), 404
    except (ValueError, OSError):
        return jsonify(status="error", message="Invalid skill package; source preserved"), 400
    return jsonify(status="accepted", message="Candidate retained; independent validation and current rights required",
                   data=_state(runtime, version)), 202


@skill_draft_bp.delete("/<name>")
def reject_draft(name: str) -> tuple[Any, int]:
    """Retire a candidate; preserve its source and immutable package."""
    workspace = _workspace()
    runtime = current_app.config.get("KNOWLEDGE_RUNTIME")
    if workspace is None or runtime is None:
        return _unavailable()
    try:
        if not skill_drafts.reject_draft(workspace, name, runtime=runtime):
            return jsonify(status="error", message="Draft not found"), 404
        version = runtime.ingest_skill(name)
    except (ValueError, OSError):
        return jsonify(status="error", message="Invalid skill package; source preserved"), 400
    return jsonify(status="success", message="Candidate retired; source preserved", data=_state(runtime, version)), 200
