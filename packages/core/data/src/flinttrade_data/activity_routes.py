"""Activity log Flask blueprint.

Endpoint
--------
GET /api/v1/admin/activity
    Query the local activity log.

    Query parameters:
        action  (str)   — filter by action (e.g. ``order.place``)
        user    (str)   — filter by username
        since   (str)   — ISO-8601 lower-bound timestamp
        limit   (int)   — max rows to return (1–500, default 100)

    Returns JSON::

        {
            "status": "success",
            "data": {
                "entries": [...],
                "count": 42
            }
        }
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

from flinttrade_core.auth_scopes import require_scope

logger = logging.getLogger("flinttrade.data.activity_routes")

activity_bp = Blueprint("activity", __name__, url_prefix="/api/v1/admin")


@activity_bp.route("/activity", methods=["GET"])
@require_scope("admin.activity")
def get_activity() -> tuple[Response, int]:
    """Return paginated, filtered activity log entries.

    Reads :data:`ACTIVITY_LOG` from ``current_app.config`` — injected by
    :func:`~flinttrade_core.app.create_flask_app` at startup.

    Query parameters:
        action (str): Dot-namespaced action filter (e.g. ``order.place``).
        user   (str): Username filter.
        since  (str): ISO-8601 lower-bound timestamp (inclusive).
        limit  (int): Maximum rows to return; clamped to 1–500.

    Returns:
        JSON response with ``status``, ``data.entries``, and ``data.count``.
    """
    activity_log = current_app.config.get("ACTIVITY_LOG")
    if activity_log is None:
        return jsonify({"status": "error", "message": "Activity log not initialised"}), 503

    action: str | None = request.args.get("action") or None
    user: str | None = request.args.get("user") or None
    since: str | None = request.args.get("since") or None

    try:
        raw_limit = int(request.args.get("limit", 100))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "limit must be an integer"}), 400

    limit = max(1, min(raw_limit, 500))

    entries = activity_log.query(action=action, user=user, since=since, limit=limit)

    payload: list[dict[str, Any]] = [
        {
            "log_id": e.log_id,
            "timestamp": e.timestamp,
            "action": e.action,
            "user": e.user,
            "ip": e.ip,
            "details": e.details,
        }
        for e in entries
    ]

    return jsonify({
        "status": "success",
        "data": {
            "entries": payload,
            "count": len(payload),
        },
    }), 200
