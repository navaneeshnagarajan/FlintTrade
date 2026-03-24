"""Flask blueprint for Action Center endpoints.

Mounts at /ft-api/v1/action-center/ and exposes the pending-order
approval queue to the React terminal via TanStack Query.

All endpoints require no authentication beyond the standard FlintTrade
/ft-api/ exemption in app.py (gateway namespace).  The action center
is an internal tool — operators use the terminal UI on the same host.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from .action_center import ActionCenter, ActionCenterError

logger = logging.getLogger("flinttrade.engine.action_center_routes")

action_center_bp = Blueprint("action_center", __name__, url_prefix="/ft-api/v1/action-center")

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
    except ActionCenterError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 409
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
    except ActionCenterError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 409
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
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400

    return jsonify({
        "status": "success",
        "data": {
            "enabled": ac.enabled,
            "ttl_seconds": ac.ttl_seconds,
        },
    }), 200
