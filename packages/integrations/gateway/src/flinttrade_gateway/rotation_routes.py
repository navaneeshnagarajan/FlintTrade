"""Flask admin routes for credential rotation management.

Routes:

- ``GET  /admin/credentials/rotation/status``
- ``POST /admin/credentials/rotation/{broker}/schedule``
- ``POST /admin/credentials/rotation/{broker}/rotate-now``

STATUS — INTENTIONALLY NOT REGISTERED (planned, not built).
``create_flask_app()`` deliberately does NOT mount this blueprint, because the
rotation engine it binds to (:class:`CredentialsRotator`) is still a SCAFFOLD:
``_do_refresh`` / ``_do_rotation`` only record a timestamp and report success —
they do not perform a real token refresh or API-key rotation (see the in-source
notes there). Real rotation requires per-broker re-auth, which for the native
Dhan/Upstox/Kotak adapters needs their (currently absent) SDKs.

Mounting these routes now would surface a "Rotate now" that reports success
while rotating nothing — a fake affordance the no-stale-screens rule forbids.
Wire this (and an Account Manager UI) only once the rotator performs a genuine
rotation; until then it is tracked as planned-but-not-built in PLAN.md /
docs/INVENTORY.md.

Usage (once the rotator is real)::

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
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400  # type: ignore[return-value]

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
