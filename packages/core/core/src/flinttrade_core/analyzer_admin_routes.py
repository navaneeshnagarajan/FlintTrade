"""Flask admin routes for the API analyser toggle.

Routes:

- ``POST   /admin/analyzer/enable``
- ``POST   /admin/analyzer/disable``
- ``GET    /admin/analyzer/status``
- ``DELETE /admin/analyzer/clear``  (query: ``?older_than_days=30``)

Usage::

    from flinttrade_core.analyzer_admin_routes import create_analyzer_admin_blueprint
    app.register_blueprint(create_analyzer_admin_blueprint(api_analyzer))
"""

from __future__ import annotations

import logging

from flask import Blueprint, Response, jsonify, request

logger = logging.getLogger("flinttrade.core.analyzer_admin_routes")


def create_analyzer_admin_blueprint(analyzer: object) -> Blueprint:
    """Create the analyzer admin Blueprint.

    Args:
        analyzer: An :class:`~flinttrade_core.api_analyzer.APIAnalyzer`
            instance.

    Returns:
        Flask :class:`~flask.Blueprint` with analyzer admin routes.
    """
    bp = Blueprint("analyzer_admin", __name__)

    @bp.route("/admin/analyzer/enable", methods=["POST"])
    def analyzer_enable() -> Response:
        """Enable API call logging.

        Returns:
            JSON confirmation.
        """
        analyzer.enable()  # type: ignore[attr-defined]
        return jsonify({"status": "ok", "enabled": True, "message": "API analyzer enabled"})  # type: ignore[return-value]

    @bp.route("/admin/analyzer/disable", methods=["POST"])
    def analyzer_disable() -> Response:
        """Disable API call logging (existing logs are retained).

        Returns:
            JSON confirmation.
        """
        analyzer.disable()  # type: ignore[attr-defined]
        return jsonify({"status": "ok", "enabled": False, "message": "API analyzer disabled"})  # type: ignore[return-value]

    @bp.route("/admin/analyzer/status", methods=["GET"])
    def analyzer_status() -> Response:
        """Return current analyzer status and call count.

        Returns:
            JSON with ``enabled`` (bool) and ``total_calls`` (int).
        """
        enabled: bool = analyzer.is_enabled()  # type: ignore[attr-defined]
        total: int = analyzer.count()  # type: ignore[attr-defined]
        return jsonify(  # type: ignore[return-value]
            {
                "status": "ok",
                "enabled": enabled,
                "total_calls": total,
            }
        )

    @bp.route("/admin/analyzer/clear", methods=["DELETE"])
    def analyzer_clear() -> Response:
        """Delete API call log rows.

        Query parameters:
            older_than_days (int, optional): Only delete rows older than
                this many days.  Omit to delete all rows.

        Returns:
            JSON with ``rows_deleted`` count.
        """
        older_str: str | None = request.args.get("older_than_days")
        older_than_days: int | None = None
        if older_str is not None:
            try:
                older_than_days = int(older_str)
                if older_than_days < 0:
                    raise ValueError("Must be non-negative")
            except ValueError as exc:
                logger.warning("Invalid older_than_days: %s", exc)
                return jsonify(  # type: ignore[return-value]
                    {"status": "error", "message": "Invalid older_than_days"}
                ), 400

        deleted: int = analyzer.clear_logs(older_than_days=older_than_days)  # type: ignore[attr-defined]
        return jsonify({"status": "ok", "rows_deleted": deleted})  # type: ignore[return-value]

    return bp
