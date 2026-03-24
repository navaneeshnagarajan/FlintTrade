"""Flask blueprint for Security Dashboard endpoints.

Mounts at /ft-api/v1/security/ and exposes IP tracking, ban management,
and aggregate statistics to the React terminal.

The companion before_request middleware is registered in ``app.py`` via
``register_security_middleware(app, monitor)`` so that every inbound
request is tracked and banned IPs are rejected with HTTP 403.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, Flask, current_app, jsonify, request

from .security import SecurityMonitor

logger = logging.getLogger("flinttrade.security_routes")

security_bp = Blueprint("security", __name__, url_prefix="/ft-api/v1/security")

# Module-level singleton — shared by the blueprint and the middleware.
_default_monitor: SecurityMonitor = SecurityMonitor()


def _get_monitor() -> SecurityMonitor:
    """Return the SecurityMonitor from app config or the default singleton."""
    try:
        mon = current_app.config.get("SECURITY_MONITOR")
        if isinstance(mon, SecurityMonitor):
            return mon
    except RuntimeError:
        pass
    return _default_monitor


# ---------------------------------------------------------------------------
# Middleware registration helper
# ---------------------------------------------------------------------------


def register_security_middleware(app: Flask, monitor: SecurityMonitor | None = None) -> None:
    """Register before_request and after_request hooks on *app*.

    The before_request hook:
      - Records every inbound request via :meth:`SecurityMonitor.record_request`.
      - Returns HTTP 403 if the remote IP is banned.

    Args:
        app: The Flask application to attach the middleware to.
        monitor: Optional :class:`SecurityMonitor` instance.  If omitted,
            the module-level default singleton is used.
    """
    mon = monitor or _default_monitor
    app.config.setdefault("SECURITY_MONITOR", mon)

    @app.before_request
    def _security_check() -> Any:
        ip = request.remote_addr or "unknown"
        mon.record_request(ip)
        if mon.is_banned(ip):
            logger.warning("Blocked request from banned IP %s → %s", ip, request.path)
            return jsonify({
                "status": "error",
                "message": "Your IP address has been blocked.",
            }), 403
        return None


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------


@security_bp.route("/stats", methods=["GET"])
def get_stats() -> tuple[Any, int]:
    """Return aggregate security statistics.

    Returns:
        JSON with ``status`` and ``data`` containing ``total_ips``,
        ``banned_count``, and ``top_offenders``.
    """
    monitor = _get_monitor()
    return jsonify({
        "status": "success",
        "data": monitor.get_stats(),
    }), 200


@security_bp.route("/bans", methods=["GET"])
def get_bans() -> tuple[Any, int]:
    """Return all currently banned IP addresses.

    Returns:
        JSON with ``status`` and ``data.bans`` list.
    """
    monitor = _get_monitor()
    bans = monitor.get_banned_ips()
    return jsonify({
        "status": "success",
        "data": {"bans": [r.to_dict() for r in bans]},
    }), 200


@security_bp.route("/records", methods=["GET"])
def get_records() -> tuple[Any, int]:
    """Return all tracked IP records.

    Returns:
        JSON with ``status`` and ``data.records`` list ordered by last_seen
        descending.
    """
    monitor = _get_monitor()
    records = monitor.get_all_records()
    return jsonify({
        "status": "success",
        "data": {"records": [r.to_dict() for r in records]},
    }), 200


# ---------------------------------------------------------------------------
# Ban management endpoints
# ---------------------------------------------------------------------------


@security_bp.route("/ban", methods=["POST"])
def ban_ip() -> tuple[Any, int]:
    """Manually ban an IP address.

    Request JSON:
        ip (str): The IP address to ban.
        reason (str): Human-readable justification.
        duration (int, optional): Ban duration in seconds.  Omit for permanent.

    Returns:
        JSON with ``status`` on success, or ``status`` and ``message`` on error.
    """
    monitor = _get_monitor()
    body = request.get_json(silent=True) or {}
    ip: str = (body.get("ip") or "").strip()
    reason: str = (body.get("reason") or "").strip()

    if not ip:
        return jsonify({"status": "error", "message": "ip is required"}), 400
    if not reason:
        return jsonify({"status": "error", "message": "reason is required"}), 400

    duration: int | None = None
    raw_duration = body.get("duration")
    if raw_duration is not None:
        try:
            duration = int(raw_duration)
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "duration must be an integer"}), 400

    monitor.ban_ip(ip, reason, duration)
    return jsonify({"status": "success", "data": {"ip": ip, "reason": reason, "duration": duration}}), 200


@security_bp.route("/unban", methods=["POST"])
def unban_ip() -> tuple[Any, int]:
    """Lift the ban on an IP address.

    Request JSON:
        ip (str): The IP address to unban.

    Returns:
        JSON with ``status`` on success, or ``status`` and ``message`` on error.
    """
    monitor = _get_monitor()
    body = request.get_json(silent=True) or {}
    ip: str = (body.get("ip") or "").strip()

    if not ip:
        return jsonify({"status": "error", "message": "ip is required"}), 400

    monitor.unban_ip(ip)
    return jsonify({"status": "success", "data": {"ip": ip}}), 200
