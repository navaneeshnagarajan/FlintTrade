"""Flask routes for audit log export.

Admin endpoints:

- ``GET /admin/audit/export?format=csv&from=2026-04-01&to=2026-04-30``
- ``GET /admin/audit/export?format=pdf&from=...&to=...``
- ``GET /admin/audit/summary?from=...&to=...``

Usage (register on an existing Flask app)::

    from packages.data.src.audit_export_routes import create_audit_export_blueprint
    app.register_blueprint(create_audit_export_blueprint(audit_logger))
"""

from __future__ import annotations

import logging
import tempfile
from datetime import date
from pathlib import Path

from flask import Blueprint, Response, jsonify, request, send_file

logger = logging.getLogger("flinttrade.data.audit_export_routes")


def create_audit_export_blueprint(audit_logger: object) -> Blueprint:
    """Create the audit export Blueprint bound to *audit_logger*.

    Args:
        audit_logger: An :class:`~packages.data.src.audit_logger.AuditLogger`
            instance.

    Returns:
        A Flask :class:`~flask.Blueprint` with the export routes registered.
    """
    from packages.data.src.audit_export import AuditExporter, AuditExportError  # noqa: PLC0415

    bp = Blueprint("audit_export", __name__)
    exporter = AuditExporter(audit_logger)

    def _parse_date(param: str, param_name: str) -> date:
        """Parse an ISO-8601 date query parameter.

        Args:
            param: Raw string value from the query string.
            param_name: Name of the parameter (for error messages).

        Returns:
            Parsed :class:`datetime.date`.

        Raises:
            :class:`~flask.Response`: 400 JSON response if the value is
                missing or malformed.
        """
        if not param:
            raise ValueError(f"Missing required query parameter: {param_name!r}")
        try:
            return date.fromisoformat(param)
        except ValueError as exc:
            raise ValueError(
                f"Invalid date format for {param_name!r}: {param!r} "
                "(expected YYYY-MM-DD)"
            ) from exc

    @bp.route("/admin/audit/export", methods=["GET"])
    def export_audit() -> Response:
        """Export audit logs as CSV or PDF file download.

        Query parameters:
            format: ``"csv"`` (default) or ``"pdf"``.
            from: Start date in ``YYYY-MM-DD`` format.
            to: End date in ``YYYY-MM-DD`` format.

        Returns:
            File download response with the appropriate MIME type.
        """
        fmt = request.args.get("format", "csv").lower()
        try:
            from_date = _parse_date(request.args.get("from", ""), "from")
            to_date = _parse_date(request.args.get("to", ""), "to")
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400  # type: ignore[return-value]

        if from_date > to_date:
            return jsonify(  # type: ignore[return-value]
                {"status": "error", "message": "'from' must be on or before 'to'"}
            ), 400

        range_str = f"{from_date.isoformat()}_{to_date.isoformat()}"

        if fmt == "pdf":
            try:
                with tempfile.NamedTemporaryFile(
                    suffix=".pdf", delete=False, prefix=f"audit_{range_str}_"
                ) as tmp:
                    tmp_path = Path(tmp.name)
                exporter.to_pdf(from_date, to_date, tmp_path)
                return send_file(  # type: ignore[return-value]
                    tmp_path,
                    as_attachment=True,
                    download_name=f"audit_report_{range_str}.pdf",
                    mimetype="application/pdf",
                )
            except AuditExportError as exc:
                return jsonify({"status": "error", "message": exc.message}), 500  # type: ignore[return-value]

        # Default: CSV
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".csv", delete=False, prefix=f"audit_{range_str}_",
                mode="w"
            ) as tmp:
                tmp_path = Path(tmp.name)
            exporter.to_csv(from_date, to_date, tmp_path)
            return send_file(  # type: ignore[return-value]
                tmp_path,
                as_attachment=True,
                download_name=f"audit_{range_str}.csv",
                mimetype="text/csv",
            )
        except AuditExportError as exc:
            return jsonify({"status": "error", "message": exc.message}), 500  # type: ignore[return-value]

    @bp.route("/admin/audit/summary", methods=["GET"])
    def audit_summary() -> Response:
        """Return summary statistics for an audit date range.

        Query parameters:
            from: Start date in ``YYYY-MM-DD`` format.
            to: End date in ``YYYY-MM-DD`` format.

        Returns:
            JSON with keys ``total_events``, ``events_by_type``,
            ``orders_placed``, ``orders_rejected``, ``safety_triggers``.
        """
        try:
            from_date = _parse_date(request.args.get("from", ""), "from")
            to_date = _parse_date(request.args.get("to", ""), "to")
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400  # type: ignore[return-value]

        if from_date > to_date:
            return jsonify(  # type: ignore[return-value]
                {"status": "error", "message": "'from' must be on or before 'to'"}
            ), 400

        stats = exporter.summary_stats(from_date, to_date)
        return jsonify({"status": "ok", "data": stats})  # type: ignore[return-value]

    return bp
