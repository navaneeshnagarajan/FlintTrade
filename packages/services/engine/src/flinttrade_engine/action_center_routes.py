"""Flask blueprint for Action Center endpoints.

Mounts at /api/v1/action-center/ and exposes the pending-order
approval queue to the React terminal via TanStack Query.

Also registers /admin/action-center/ routes for the PendingOrderQueue
(DuckDB-backed, richer approval workflow with audit history).

All endpoints require no authentication beyond the standard FlintTrade
/v1/ namespace in app.py (gateway namespace).  The action center
is an internal tool — operators use the terminal UI on the same host.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from .action_center import ActionCenter, ActionCenterError, PendingOrderQueue

logger = logging.getLogger("flinttrade.engine.action_center_routes")

action_center_bp = Blueprint("action_center", __name__, url_prefix="/api/v1/action-center")

# Module-level singleton so routes share state even when imported separately.
# The Flask app may inject a custom instance via app.config["ACTION_CENTER"].
_default_action_center: ActionCenter = ActionCenter()


def _get_ac() -> ActionCenter:
    """Return the ActionCenter instance from app config or the default singleton."""
    try:
        ac = current_app.config.get("ACTION_CENTER")
        if isinstance(ac, ActionCenter):
            return ac
    except RuntimeError:
        pass
    return _default_action_center


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------


@action_center_bp.route("/pending", methods=["GET"])
def get_pending() -> tuple[Any, int]:
    """List orders currently awaiting approval.

    Returns:
        JSON with ``status`` and ``data.orders`` list.
    """
    ac = _get_ac()
    orders = ac.get_pending()
    return jsonify({
        "status": "success",
        "data": {"orders": [o.to_dict() for o in orders]},
    }), 200


@action_center_bp.route("/all", methods=["GET"])
def get_all() -> tuple[Any, int]:
    """List all orders (pending, approved, rejected, expired).

    Returns:
        JSON with ``status`` and ``data.orders`` list.
    """
    ac = _get_ac()
    orders = ac.get_all()
    return jsonify({
        "status": "success",
        "data": {"orders": [o.to_dict() for o in orders]},
    }), 200


# ---------------------------------------------------------------------------
# Action endpoints
# ---------------------------------------------------------------------------


@action_center_bp.route("/approve/<order_id>", methods=["POST"])
def approve_order(order_id: str) -> tuple[Any, int]:
    """Approve a single pending order.

    Args:
        order_id: URL path parameter identifying the order.

    Returns:
        JSON with ``status`` and ``data.order`` on success, or
        ``status`` and ``message`` on error (404/409).
    """
    ac = _get_ac()
    try:
        po = ac.approve(order_id)
    except ActionCenterError:
        return jsonify({"status": "error", "message": "Request conflicts with the current state"}), 409
    return jsonify({"status": "success", "data": {"order": po.to_dict()}}), 200


@action_center_bp.route("/reject/<order_id>", methods=["POST"])
def reject_order(order_id: str) -> tuple[Any, int]:
    """Reject a single pending order.

    Args:
        order_id: URL path parameter identifying the order.

    Returns:
        JSON with ``status`` and ``data.order`` on success, or
        ``status`` and ``message`` on error (409).
    """
    ac = _get_ac()
    try:
        po = ac.reject(order_id)
    except ActionCenterError:
        return jsonify({"status": "error", "message": "Request conflicts with the current state"}), 409
    return jsonify({"status": "success", "data": {"order": po.to_dict()}}), 200


@action_center_bp.route("/approve-all", methods=["POST"])
def approve_all() -> tuple[Any, int]:
    """Approve all currently pending orders in bulk.

    Returns:
        JSON with ``status`` and ``data.approved_count``.
    """
    ac = _get_ac()
    approved = ac.approve_all()
    return jsonify({
        "status": "success",
        "data": {
            "approved_count": len(approved),
            "orders": [o.to_dict() for o in approved],
        },
    }), 200


# ---------------------------------------------------------------------------
# Config endpoints
# ---------------------------------------------------------------------------


@action_center_bp.route("/config", methods=["GET"])
def get_config() -> tuple[Any, int]:
    """Return current Action Center configuration.

    Returns:
        JSON with ``status`` and ``data`` containing ``enabled`` and ``ttl_seconds``.
    """
    ac = _get_ac()
    return jsonify({
        "status": "success",
        "data": {
            "enabled": ac.enabled,
            "ttl_seconds": ac.ttl_seconds,
        },
    }), 200


@action_center_bp.route("/config", methods=["POST"])
def update_config() -> tuple[Any, int]:
    """Update Action Center configuration.

    Request JSON (all fields optional):
        enabled (bool): Enable or disable the approval queue.
        ttl_seconds (int): Pending-order TTL in seconds (>= 1).

    Returns:
        JSON with ``status`` and updated ``data`` on success, or
        ``status`` and ``message`` on validation error.
    """
    ac = _get_ac()
    body = request.get_json(silent=True) or {}

    if "enabled" in body:
        ac.enabled = bool(body["enabled"])

    if "ttl_seconds" in body:
        try:
            ttl = int(body["ttl_seconds"])
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "ttl_seconds must be an integer"}), 400
        try:
            ac.ttl_seconds = ttl
        except ValueError:
            return jsonify({"status": "error", "message": "ttl_seconds must be >= 1"}), 400

    return jsonify({
        "status": "success",
        "data": {
            "enabled": ac.enabled,
            "ttl_seconds": ac.ttl_seconds,
        },
    }), 200


# ---------------------------------------------------------------------------
# Admin blueprint — PendingOrderQueue (DuckDB-backed approval workflow)
# ---------------------------------------------------------------------------

admin_action_center_bp = Blueprint(
    "admin_action_center",
    __name__,
    url_prefix="/admin/action-center",
)

# Module-level singleton for the persistent queue.
# The Flask app may inject a custom instance via app.config["PENDING_ORDER_QUEUE"].
_default_queue: PendingOrderQueue | None = None


def _get_queue() -> PendingOrderQueue:
    """Return the PendingOrderQueue from app config or the module singleton.

    Returns:
        A ready-to-use :class:`PendingOrderQueue` instance.
    """
    global _default_queue  # noqa: PLW0603
    try:
        q = current_app.config.get("PENDING_ORDER_QUEUE")
        if isinstance(q, PendingOrderQueue):
            return q
    except RuntimeError:
        pass
    if _default_queue is None:
        _default_queue = PendingOrderQueue()
    return _default_queue


@admin_action_center_bp.route("/pending", methods=["GET"])
def admin_list_pending() -> tuple[Any, int]:
    """List all orders currently awaiting approval.

    Returns:
        JSON with ``status`` and ``data.requests`` (list of
        :class:`~action_center.ApprovalRequest` dicts).
    """
    queue = _get_queue()
    try:
        requests = queue.list_pending()
    except ActionCenterError:
        return jsonify({"status": "error", "message": "Internal server error"}), 500
    return jsonify({
        "status": "success",
        "data": {"requests": [r.to_dict() for r in requests]},
    }), 200


@admin_action_center_bp.route("/<request_id>/approve", methods=["POST"])
def admin_approve_request(request_id: str) -> tuple[Any, int]:
    """Approve a pending approval request.

    Args:
        request_id: UUID path parameter.

    Returns:
        JSON with updated request on success, or error details.
    """
    queue = _get_queue()
    try:
        req = queue.approve(request_id)
    except ActionCenterError:
        return jsonify({"status": "error", "message": "Request conflicts with the current state"}), 409
    return jsonify({"status": "success", "data": {"request": req.to_dict()}}), 200


@admin_action_center_bp.route("/<request_id>/reject", methods=["POST"])
def admin_reject_request(request_id: str) -> tuple[Any, int]:
    """Reject a pending approval request.

    Request JSON (optional):
        reason (str): Human-readable reason for rejection.

    Args:
        request_id: UUID path parameter.

    Returns:
        JSON with updated request on success, or error details.
    """
    queue = _get_queue()
    body = request.get_json(silent=True) or {}
    reason: str = body.get("reason", "")
    try:
        req = queue.reject(request_id, reason)
    except ActionCenterError:
        return jsonify({"status": "error", "message": "Request conflicts with the current state"}), 409
    return jsonify({"status": "success", "data": {"request": req.to_dict()}}), 200


@admin_action_center_bp.route("/history", methods=["GET"])
def admin_history() -> tuple[Any, int]:
    """Return resolved approval requests for audit purposes.

    Query params:
        statuses (str, comma-separated): Filter by status values
            (approved, rejected, expired).  Defaults to all resolved.
        limit (int): Maximum records to return (default 100).

    Returns:
        JSON with ``status`` and ``data.requests`` list.
    """
    queue = _get_queue()
    raw_statuses = request.args.get("statuses", "")
    statuses = [s.strip() for s in raw_statuses.split(",") if s.strip()] or None  # type: ignore[assignment]

    try:
        limit = int(request.args.get("limit", 100))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "limit must be an integer"}), 400

    try:
        history = queue.list_history(statuses=statuses, limit=limit)  # type: ignore[arg-type]
    except ActionCenterError:
        return jsonify({"status": "error", "message": "Internal server error"}), 500
    return jsonify({
        "status": "success",
        "data": {"requests": [r.to_dict() for r in history]},
    }), 200
