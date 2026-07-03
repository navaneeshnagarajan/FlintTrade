"""Flask admin routes for credential rotation management.

Routes:

- ``GET  /admin/credentials/rotation/status``
- ``POST /admin/credentials/rotation/{broker}/schedule``
- ``POST /admin/credentials/rotation/{broker}/rotate-now``

MOUNTED since Phase 1 G5: ``create_flask_app`` builds a
:class:`CredentialsRotator` over core's ``NativeSessionRefresher`` — a REAL
``refresh_token`` hook that renews (Dhan ``RenewToken``) or replays vault
credentials per selector and raises on failure, so ``rotate-now`` reports an
honest per-broker result rather than the scaffold-era fake success. The core
factory adds a G9 write guard (operator session JWT) before mounting.

Usage::

    from flinttrade_gateway.rotation_routes import create_rotation_blueprint
    app.register_blueprint(create_rotation_blueprint(rotator))
"""

from __future__ import annotations

import logging

from flask import Blueprint, Response, jsonify, request

logger = logging.getLogger("flinttrade.gateway.rotation_routes")


def create_rotation_blueprint(rotator: object) -> Blueprint:
    """Create the rotation admin Blueprint bound to *rotator*.

    Args:
        rotator: A :class:`~flinttrade_gateway.credentials_rotation.CredentialsRotator`
            instance.

    Returns:
        Flask :class:`~flask.Blueprint` with rotation routes.
    """
    bp = Blueprint("rotation_admin", __name__)

    @bp.route("/admin/credentials/rotation/status", methods=["GET"])
    def rotation_status() -> Response:
        """Return rotation status for all configured brokers.

        Returns:
            JSON with ``brokers`` list.
        """
        status = rotator.rotation_status()  # type: ignore[attr-defined]
        return jsonify({"status": "ok", "brokers": status})  # type: ignore[return-value]

    @bp.route(
        "/admin/credentials/rotation/<broker>/schedule",
        methods=["POST"],
    )
    def rotation_schedule(broker: str) -> Response:
        """Schedule a credential rotation for *broker*.

        Request body (JSON):
            interval (str): ``"daily"`` or ``"weekly"``.
            time_ist (str): Time in ``"HH:MM"`` format (IST).
            day (int, optional): Day of week for weekly rotation (0=Mon).

        Returns:
            JSON confirmation.
        """
        body = request.get_json(silent=True) or {}
        interval: str = str(body.get("interval", "daily")).lower()
        time_ist: str = str(body.get("time_ist", "08:00"))
        day: int = int(body.get("day", 0))

        try:
            if interval == "weekly":
                rotator.schedule_weekly_rotation(broker, day=day, time_ist=time_ist)  # type: ignore[attr-defined]
                message = f"Weekly rotation scheduled for {broker} on day={day} at {time_ist} IST"
            else:
                rotator.schedule_daily_refresh(broker, time_ist=time_ist)  # type: ignore[attr-defined]
                message = f"Daily refresh scheduled for {broker} at {time_ist} IST"
        except ValueError:
            return jsonify({"status": "error", "message": "Invalid request"}), 400  # type: ignore[return-value]

        return jsonify({"status": "ok", "message": message})  # type: ignore[return-value]

    @bp.route(
        "/admin/credentials/rotation/<broker>/rotate-now",
        methods=["POST"],
    )
    def rotation_rotate_now(broker: str) -> Response:
        """Immediately rotate credentials for *broker*.

        Returns:
            JSON with rotation result including ``success``, ``rotated_at``,
            and ``error`` (if failed).
        """
        result = rotator.rotate_now(broker)  # type: ignore[attr-defined]
        payload = {
            "status": "ok" if result.success else "error",
            "broker": result.broker,
            "success": result.success,
            "rotated_at": result.rotated_at.isoformat(),
            "rotation_type": result.rotation_type,
        }
        if result.error:
            payload["error"] = result.error
        http_status = 200 if result.success else 500
        return jsonify(payload), http_status  # type: ignore[return-value]

    return bp
