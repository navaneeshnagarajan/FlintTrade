"""Flask endpoints for n8n workflow automation integration.

Registered as a Blueprint by ``create_flask_app()``.

Endpoints
---------
GET  /api/v1/automation/n8n/health          — check if n8n is running
GET  /api/v1/automation/n8n/workflows       — list all n8n workflows
POST /api/v1/automation/n8n/webhook/trigger — trigger an n8n webhook workflow
POST /api/v1/automation/n8n/workflows/<id>/activate   — activate a workflow
POST /api/v1/automation/n8n/workflows/<id>/deactivate — deactivate a workflow
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, Response, jsonify, request

from .n8n_bridge import N8nBridge, N8nBridgeError

logger = logging.getLogger("flinttrade.automation.n8n_routes")

n8n_bp = Blueprint("n8n", __name__, url_prefix="/api/v1/automation/n8n")

# Module-level singleton — replaced via ``init_n8n_routes`` for dependency injection.
_bridge: N8nBridge | None = None


def _get_bridge() -> N8nBridge:
    """Return the module-level N8nBridge singleton, creating it lazily."""
    global _bridge  # noqa: PLW0603
    if _bridge is None:
        _bridge = N8nBridge()
    return _bridge


def init_n8n_routes(bridge: N8nBridge) -> None:
    """Inject an N8nBridge instance into the blueprint's singleton.

    Args:
        bridge: The :class:`N8nBridge` instance to use for all requests.
    """
    global _bridge  # noqa: PLW0603
    _bridge = bridge
    logger.info("N8nBridge singleton injected into n8n_routes")


def reset_n8n_bridge() -> None:
    """Drop the cached bridge so the next request rebuilds from fresh config.

    Called by the settings route after a save — the singleton captured host
    and API key at construction, and stale values must not outlive the
    operator's change.
    """
    global _bridge  # noqa: PLW0603
    if _bridge is not None:
        try:
            _bridge.close()
        except Exception:  # noqa: BLE001 - a failed close must not block the reset
            logger.debug("n8n bridge close failed during reset", exc_info=True)
    _bridge = None
    logger.info("N8nBridge singleton reset — next request reloads config")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@n8n_bp.route("/health", methods=["GET"])
def health() -> tuple[Response, int]:
    """Check if n8n is running and reachable.

    Returns:
        JSON ``{"status": "success", "data": {"running": true}}`` when n8n
        is up, or ``{"status": "error", ...}`` when it is unreachable.
    """
    bridge = _get_bridge()
    running = bridge.check_health()

    if running:
        return jsonify({"status": "success", "data": {"running": True}}), 200

    return jsonify({
        "status": "error",
        "message": "n8n is not reachable. Ensure it is running on the configured host.",
        "data": {"running": False},
    }), 503


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------


@n8n_bp.route("/workflows", methods=["GET"])
def list_workflows() -> tuple[Response, int]:
    """List all n8n workflows.

    Requires n8n API key configured on the bridge (set ``N8N_API_KEY`` env var).

    Returns:
        JSON ``{"status": "success", "data": {"workflows": [...], "count": N}}``.
    """
    bridge = _get_bridge()
    try:
        workflows = bridge.list_workflows()
    except N8nBridgeError:
        return jsonify({"status": "error", "message": "Invalid request"}), 400

    return jsonify({
        "status": "success",
        "data": {"workflows": workflows, "count": len(workflows)},
    }), 200


@n8n_bp.route("/workflows/<workflow_id>/activate", methods=["POST"])
def activate_workflow(workflow_id: str) -> tuple[Response, int]:
    """Activate an n8n workflow.

    Path parameters:
        workflow_id: Numeric string ID of the workflow in n8n.

    Returns:
        JSON ``{"status": "success", "data": {"workflow_id": "...", "active": true}}``.
    """
    bridge = _get_bridge()
    try:
        ok = bridge.activate_workflow(workflow_id)
    except N8nBridgeError:
        return jsonify({"status": "error", "message": "Invalid request"}), 400

    if ok:
        return jsonify({
            "status": "success",
            "data": {"workflow_id": workflow_id, "active": True},
        }), 200

    return jsonify({
        "status": "error",
        "message": f"Failed to activate workflow {workflow_id}",
    }), 502


@n8n_bp.route("/workflows/<workflow_id>/deactivate", methods=["POST"])
def deactivate_workflow(workflow_id: str) -> tuple[Response, int]:
    """Deactivate an n8n workflow.

    Path parameters:
        workflow_id: Numeric string ID of the workflow in n8n.

    Returns:
        JSON ``{"status": "success", "data": {"workflow_id": "...", "active": false}}``.
    """
    bridge = _get_bridge()
    try:
        ok = bridge.deactivate_workflow(workflow_id)
    except N8nBridgeError:
        return jsonify({"status": "error", "message": "Invalid request"}), 400

    if ok:
        return jsonify({
            "status": "success",
            "data": {"workflow_id": workflow_id, "active": False},
        }), 200

    return jsonify({
        "status": "error",
        "message": f"Failed to deactivate workflow {workflow_id}",
    }), 502


# ---------------------------------------------------------------------------
# Webhook trigger
# ---------------------------------------------------------------------------


@n8n_bp.route("/webhook/trigger", methods=["POST"])
def trigger_webhook() -> tuple[Response, int]:
    """Trigger an n8n webhook workflow.

    Request JSON:
        webhook_id (str, required): The n8n webhook UUID.
        data       (dict, optional): Payload to send to the workflow.

    Returns:
        JSON ``{"status": "success", "data": {...n8n response...}}``.
    """
    bridge = _get_bridge()
    body: dict[str, Any] = request.get_json(silent=True) or {}

    webhook_id: str = body.get("webhook_id", "")
    if not webhook_id:
        return jsonify({"status": "error", "message": "webhook_id is required"}), 400

    payload: dict[str, Any] = body.get("data", {})

    try:
        result = bridge.trigger_webhook(webhook_id, payload)
    except N8nBridgeError:
        return jsonify({"status": "error", "message": "Upstream service failed"}), 502

    return jsonify({"status": "success", "data": result}), 200
