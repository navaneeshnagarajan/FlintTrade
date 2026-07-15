"""Flask blueprint for Action Center endpoints.

Mounts at /api/v1/action-center/ and exposes the pending-order
approval queue to the React terminal via TanStack Query.

Also registers /admin/action-center/ routes for the PendingOrderQueue
(DuckDB-backed, richer approval workflow with audit history).

Every endpoint delegates authentication to the owning FlintTrade application.
Approvals additionally require a fresh Live-mode unlock before the durable
intent can be claimed and dispatched through the gated broker path.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from .action_center import (
    ActionCenter,
    ActionCenterError,
    ApprovalDispatchResult,
    PendingOrderQueue,
)

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


def _require_operator(*, require_live_unlock: bool = False) -> tuple[Any, int] | None:
    """Delegate current-request authorisation to the owning Flask application."""
    authoriser = current_app.config.get("ACTION_CENTER_AUTHORISER")
    if not callable(authoriser):
        return jsonify({
            "status": "error",
            "message": "Action Centre authorisation runtime is unavailable.",
        }), 503
    try:
        denied = authoriser(require_live_unlock=require_live_unlock)
    except Exception:  # noqa: BLE001 - authentication infrastructure fails closed
        logger.exception("Action Centre authorisation failed")
        return jsonify({
            "status": "error",
            "message": "Action Centre authorisation runtime is unavailable.",
        }), 503
    if denied is None:
        return None
    if isinstance(denied, tuple) and len(denied) == 2:
        return denied
    logger.error("Action Centre authoriser returned an invalid result")
    return jsonify({
        "status": "error",
        "message": "Action Centre authorisation runtime is unavailable.",
    }), 503


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------


@action_center_bp.route("/pending", methods=["GET"])
def get_pending() -> tuple[Any, int]:
    """List orders currently awaiting approval.

    Returns:
        JSON with ``status`` and ``data.orders`` list.
    """
    denied = _require_operator()
    if denied is not None:
        return denied
    orders = _get_queue().list_pending()
    return jsonify({
        "status": "success",
        "data": {"orders": [order.to_terminal_dict() for order in orders]},
    }), 200


@action_center_bp.route("/all", methods=["GET"])
def get_all() -> tuple[Any, int]:
    """List all orders (pending, approved, rejected, expired).

    Returns:
        JSON with ``status`` and ``data.orders`` list.
    """
    denied = _require_operator()
    if denied is not None:
        return denied
    orders = _get_queue().list_all()
    return jsonify({
        "status": "success",
        "data": {"orders": [order.to_dict() for order in orders]},
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
    denied = _require_operator(require_live_unlock=True)
    if denied is not None:
        return denied

    dispatcher = current_app.config.get("ACTION_CENTER_APPROVAL_DISPATCHER")
    if not callable(dispatcher):
        return jsonify({
            "status": "error",
            "message": "Approval dispatch runtime unavailable; the intent remains pending.",
        }), 503

    queue = _get_queue()
    try:
        claimed = queue.claim_for_dispatch(order_id)
    except ActionCenterError as exc:
        return jsonify({
            "status": "error",
            "message": str(exc),
        }), 409

    try:
        result = dispatcher(claimed)
        if not isinstance(result, ApprovalDispatchResult):
            raise TypeError("Approval dispatcher returned an invalid result")
    except Exception:  # noqa: BLE001 - post-claim exceptions have uncertain outcome
        logger.exception("Action Centre dispatch failed for request %s", order_id)
        failed = queue.mark_failed(
            order_id,
            reason=(
                "Approval dispatch did not complete cleanly. The broker outcome may be unknown; "
                "inspect the live order book before creating another intent."
            ),
            outcome_uncertain=True,
        )
        return jsonify({
            "status": "error",
            "message": failed.failure_reason,
            "data": {"request": failed.to_dict()},
        }), 503

    if result.succeeded and result.broker_order_id:
        approved = queue.mark_approved(
            order_id,
            broker_order_id=result.broker_order_id,
        )
        return jsonify({
            "status": "success",
            "data": {
                "order": approved.to_terminal_dict(),
                "request": approved.to_dict(),
            },
        }), 200

    detail = result.message or "Approval was refused"
    message = f"Order was not dispatched: {detail}. This intent will not be replayed."
    failed = queue.mark_failed(
        order_id,
        reason=detail,
        outcome_uncertain=result.outcome_uncertain,
    )
    status_code = result.status_code if 400 <= result.status_code <= 599 else 500
    return jsonify({
        "status": "error",
        "message": message,
        "data": {"request": failed.to_dict()},
    }), status_code


@action_center_bp.route("/reject/<order_id>", methods=["POST"])
def reject_order(order_id: str) -> tuple[Any, int]:
    """Reject a single pending order.

    Args:
        order_id: URL path parameter identifying the order.

    Returns:
        JSON with ``status`` and ``data.order`` on success, or
        ``status`` and ``message`` on error (409).
    """
    denied = _require_operator()
    if denied is not None:
        return denied
    body = request.get_json(silent=True) or {}
    reason = str(body.get("reason") or "Operator rejected")
    try:
        approval_request = _get_queue().reject(order_id, reason=reason)
    except ActionCenterError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 409
    return jsonify({
        "status": "success",
        "data": {"request": approval_request.to_dict()},
    }), 200


@action_center_bp.route("/approve-all", methods=["POST"])
def approve_all() -> tuple[Any, int]:
    """Refuse bulk approval so every live intent gets explicit review."""
    denied = _require_operator(require_live_unlock=True)
    if denied is not None:
        return denied
    return jsonify({
        "status": "error",
        "message": "Bulk approval is disabled; review and approve each live intent individually.",
    }), 405


# ---------------------------------------------------------------------------
# Config endpoints
# ---------------------------------------------------------------------------


@action_center_bp.route("/config", methods=["GET"])
def get_config() -> tuple[Any, int]:
    """Return current Action Center configuration.

    Returns:
        JSON with ``status`` and ``data`` containing ``enabled`` and ``ttl_seconds``.
    """
    denied = _require_operator()
    if denied is not None:
        return denied
    queue = _get_queue()
    return jsonify({
        "status": "success",
        "data": {
            "enabled": True,
            "ttl_seconds": queue.ttl_seconds,
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
    denied = _require_operator()
    if denied is not None:
        return denied
    queue = _get_queue()
    body = request.get_json(silent=True) or {}

    if body.get("enabled") is False:
        return jsonify({
            "status": "error",
            "message": "Autonomous-agent entry approval cannot be disabled.",
        }), 400

    if "ttl_seconds" in body:
        try:
            ttl = int(body["ttl_seconds"])
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "ttl_seconds must be an integer"}), 400
        try:
            queue.ttl_seconds = ttl
        except ValueError:
            return jsonify({"status": "error", "message": "ttl_seconds must be >= 1"}), 400

    return jsonify({
        "status": "success",
        "data": {
            "enabled": True,
            "ttl_seconds": queue.ttl_seconds,
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
    denied = _require_operator()
    if denied is not None:
        return denied
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
    return approve_order(request_id)


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
    return reject_order(request_id)


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
    denied = _require_operator()
    if denied is not None:
        return denied
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
