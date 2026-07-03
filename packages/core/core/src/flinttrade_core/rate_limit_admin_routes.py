"""Flask admin routes for per-user rate-limit overrides.

Routes:

- ``GET    /admin/rate-limits/overrides``
- ``POST   /admin/rate-limits/overrides``
- ``DELETE /admin/rate-limits/overrides/{user_id}/{endpoint}``

Usage::

    from flinttrade_core.rate_limit_admin_routes import create_rate_limit_admin_blueprint
    app.register_blueprint(create_rate_limit_admin_blueprint(limiter))
"""

from __future__ import annotations

import logging

from flask import Blueprint, Response, jsonify, request

logger = logging.getLogger("flinttrade.core.rate_limit_admin_routes")


def create_rate_limit_admin_blueprint(rate_limiter: object) -> Blueprint:
    """Create the rate-limit admin Blueprint.

    Args:
        rate_limiter: A :class:`~flinttrade_core.rate_limiter.RateLimiter`
            instance.

    Returns:
        Flask :class:`~flask.Blueprint` with override management routes.
    """
    bp = Blueprint("rate_limit_admin", __name__)

    @bp.route("/admin/rate-limits/overrides", methods=["GET"])
    def list_overrides() -> Response:
        """List all active per-user rate-limit overrides.

        Returns:
            JSON with ``overrides`` list containing ``user_id``,
            ``endpoint``, and ``user_rate`` for each entry.
        """
        overrides = rate_limiter.list_overrides()  # type: ignore[attr-defined]
        return jsonify({"status": "ok", "overrides": overrides})  # type: ignore[return-value]

    @bp.route("/admin/rate-limits/overrides", methods=["POST"])
    def set_override() -> Response:
        """Create or update a per-user rate-limit override.

        Request body (JSON):
            user_id (str, required): User identifier.
            endpoint (str, required): Logical endpoint name.
            rate (int, required): New per-user rate (requests/second).

        Returns:
            JSON confirmation.
        """
        body = request.get_json(silent=True) or {}
        user_id: str | None = body.get("user_id")
        endpoint: str | None = body.get("endpoint")
        rate: int | None = body.get("rate")

        if not user_id:
            return jsonify(  # type: ignore[return-value]
                {"status": "error", "message": "Missing required field: 'user_id'"}
            ), 400
        if not endpoint:
            return jsonify(  # type: ignore[return-value]
                {"status": "error", "message": "Missing required field: 'endpoint'"}
            ), 400
        if rate is None:
            return jsonify(  # type: ignore[return-value]
                {"status": "error", "message": "Missing required field: 'rate'"}
            ), 400

        try:
            rate_limiter.set_user_override(str(user_id), str(endpoint), int(rate))  # type: ignore[attr-defined]
        except ValueError:
            return jsonify({"status": "error", "message": "Invalid request"}), 400  # type: ignore[return-value]

        return jsonify(  # type: ignore[return-value]
            {
                "status": "ok",
                "message": f"Override set: user={user_id} endpoint={endpoint} rate={rate}/s",
            }
        )

    @bp.route(
        "/admin/rate-limits/overrides/<user_id>/<endpoint>",
        methods=["DELETE"],
    )
    def remove_override(user_id: str, endpoint: str) -> Response:
        """Remove a per-user rate-limit override.

        Path parameters:
            user_id: User identifier.
            endpoint: Logical endpoint name.

        Returns:
            JSON with ``removed`` boolean indicating whether an override
            existed and was deleted.
        """
        removed = rate_limiter.remove_user_override(user_id, endpoint)  # type: ignore[attr-defined]
        if removed:
            return jsonify(  # type: ignore[return-value]
                {
                    "status": "ok",
                    "removed": True,
                    "message": f"Override removed: user={user_id} endpoint={endpoint}",
                }
            )
        return jsonify(  # type: ignore[return-value]
            {
                "status": "ok",
                "removed": False,
                "message": f"No override found for user={user_id} endpoint={endpoint}",
            }
        )

    return bp
