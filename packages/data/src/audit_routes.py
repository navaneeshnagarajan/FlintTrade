"""Flask blueprint for SEBI-compliant audit trail endpoints.

External URLs (frontend / Vite proxy calls these):
    GET /ft-api/v1/audit/log     — Paginated, filterable audit trail.
    GET /ft-api/v1/audit/export  — CSV export of the audit log.
    GET /ft-api/v1/audit/stats   — Action-type counts for the admin dashboard.

The WSGI prefix stripper in app.py translates /ft-api/v1/* → /v1/* before
Flask dispatch, so the blueprint is registered at /v1/audit (not /ft-api/v1/audit).

The :class:`~packages.data.src.activity_log.ActivityLog` instance is read from
``current_app.config["ACTIVITY_LOG"]``, which is populated at startup by
:func:`~packages.core.src.app.create_flask_app`.

Response conventions:
- All success responses: ``{"status": "success", "data": {...}}``
- All error responses:   ``{"status": "error", "message": "..."}``
- HTTP 503 when the activity log has not been initialised.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, make_response, request

logger = logging.getLogger("flinttrade.data.audit_routes")

audit_bp = Blueprint("audit", __name__, url_prefix="/v1/audit")

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _get_log() -> Any:
    """Return the ActivityLog instance from the Flask app config.

    Returns:
        ActivityLog instance, or ``None`` if not configured.
    """
    return current_app.config.get("ACTIVITY_LOG")


# ---------------------------------------------------------------------------
# GET /ft-api/v1/audit/log
# ---------------------------------------------------------------------------


@audit_bp.route("/log", methods=["GET"])
def audit_log() -> tuple[Response, int]:
    """Return a paginated, filterable audit log.

    Reads all entries from the SEBI-compliant :class:`ActivityLog` and applies
    optional server-side filters before returning.

    Query parameters:
        action  (str):  Dot-namespaced action filter (e.g. ``order.place``).
        user    (str):  Username filter.
        since   (str):  ISO-8601 lower-bound timestamp (inclusive).
        until   (str):  ISO-8601 upper-bound timestamp (inclusive).
        page    (int):  1-based page number (default 1).
        per_page (int): Entries per page, clamped to 1–500 (default 50).

    Returns:
        JSON with paginated entries and pagination metadata::

            {
                "status": "success",
                "data": {
                    "entries": [ { log_id, timestamp, action, user, ip, details } ],
                    "total": 120,
                    "page": 1,
                    "per_page": 50,
                    "pages": 3
                }
            }
    """
    log = _get_log()
    if log is None:
        return jsonify({"status": "error", "message": "Activity log not initialised"}), 503

    action: str | None = request.args.get("action") or None
    user: str | None = request.args.get("user") or None
    since: str | None = request.args.get("since") or None
    until: str | None = request.args.get("until") or None

    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "page must be an integer"}), 400

    try:
        per_page = max(1, min(500, int(request.args.get("per_page", 50))))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "per_page must be an integer"}), 400

    # Fetch a large batch to support pagination (max 5000 — SEBI audit window)
    # For very large deployments this should be pushed down to SQL OFFSET/LIMIT.
    entries = log.query(action=action, user=user, since=since, limit=5000)

    # Apply until filter (activity_log.query only supports since, not until)
    if until:
        until_dt = datetime.fromisoformat(until) if isinstance(until, str) else until
        # Strip timezone for comparison — TIMESTAMP column stores naive datetimes
        until_naive = until_dt.replace(tzinfo=None) if until_dt.tzinfo else until_dt
        entries = [e for e in entries if (e.timestamp.replace(tzinfo=None) if e.timestamp.tzinfo else e.timestamp) <= until_naive]

    total = len(entries)
    import math  # noqa: PLC0415

    pages = max(1, math.ceil(total / per_page))
    start = (page - 1) * per_page
    page_entries = entries[start : start + per_page]

    payload: list[dict[str, Any]] = [
        {
            "log_id": e.log_id,
            "timestamp": e.timestamp,
            "action": e.action,
            "user": e.user,
            "ip": e.ip,
            "details": e.details,
        }
        for e in page_entries
    ]

    return jsonify({
        "status": "success",
        "data": {
            "entries": payload,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": pages,
        },
    }), 200


# ---------------------------------------------------------------------------
# GET /ft-api/v1/audit/export
# ---------------------------------------------------------------------------


@audit_bp.route("/export", methods=["GET"])
def audit_export() -> tuple[Response, int]:
    """Export the audit log as a CSV file.

    Streams the full (or date-bounded) audit log as a UTF-8 CSV attachment.
    Designed for SEBI record-keeping: up to 5 years of data can be exported
    in one request.

    Query parameters:
        since   (str): ISO-8601 lower-bound timestamp (inclusive).
        until   (str): ISO-8601 upper-bound timestamp (inclusive).
        action  (str): Optional action filter.
        user    (str): Optional user filter.

    Returns:
        ``text/csv`` attachment with headers::

            log_id,timestamp,action,user,ip,details
    """
    log = _get_log()
    if log is None:
        return jsonify({"status": "error", "message": "Activity log not initialised"}), 503

    action: str | None = request.args.get("action") or None
    user: str | None = request.args.get("user") or None
    since: str | None = request.args.get("since") or None
    until: str | None = request.args.get("until") or None

    # Pull all matching rows (retention is 5 years per SEBI)
    entries = log.query(action=action, user=user, since=since, limit=100_000)

    if until:
        until_dt = datetime.fromisoformat(until) if isinstance(until, str) else until
        # Strip timezone for comparison — TIMESTAMP column stores naive datetimes
        until_naive = until_dt.replace(tzinfo=None) if until_dt.tzinfo else until_dt
        entries = [e for e in entries if (e.timestamp.replace(tzinfo=None) if e.timestamp.tzinfo else e.timestamp) <= until_naive]

    # Build CSV in memory — acceptable for audit exports (regulatory, not streaming)
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(["log_id", "timestamp", "action", "user", "ip", "details"])
    for e in entries:
        import json as _json  # noqa: PLC0415

        writer.writerow([
            e.log_id,
            e.timestamp,
            e.action,
            e.user,
            e.ip or "",
            _json.dumps(e.details, ensure_ascii=False),
        ])

    csv_bytes = output.getvalue().encode("utf-8")
    response = make_response(csv_bytes)
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=flinttrade_audit.csv"
    response.headers["Content-Length"] = str(len(csv_bytes))
    return response, 200


# ---------------------------------------------------------------------------
# GET /ft-api/v1/audit/stats
# ---------------------------------------------------------------------------


@audit_bp.route("/stats", methods=["GET"])
def audit_stats() -> tuple[Response, int]:
    """Return action-type counts for the admin dashboard.

    Fetches the last N days of activity and groups entries by action type.
    Useful for the admin panel sparklines and anomaly detection.

    Query parameters:
        since   (str): ISO-8601 lower-bound (default: no lower bound).
        user    (str): Optional user filter.

    Returns:
        JSON with per-action counts and the total::

            {
                "status": "success",
                "data": {
                    "total": 148,
                    "by_action": {
                        "order.place": 42,
                        "order.cancel": 10,
                        "auth.login": 7,
                        ...
                    }
                }
            }
    """
    log = _get_log()
    if log is None:
        return jsonify({"status": "error", "message": "Activity log not initialised"}), 503

    since: str | None = request.args.get("since") or None
    user: str | None = request.args.get("user") or None

    entries = log.query(user=user, since=since, limit=100_000)

    by_action: dict[str, int] = {}
    for e in entries:
        by_action[e.action] = by_action.get(e.action, 0) + 1

    # Sort by count descending for readability
    sorted_counts = dict(
        sorted(by_action.items(), key=lambda item: item[1], reverse=True)
    )

    return jsonify({
        "status": "success",
        "data": {
            "total": len(entries),
            "by_action": sorted_counts,
        },
    }), 200
