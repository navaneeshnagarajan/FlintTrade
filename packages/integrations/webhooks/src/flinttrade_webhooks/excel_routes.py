"""Flask endpoints for Excel data export and import.

Registered as a Blueprint by ``create_flask_app()``.

Endpoints
---------
POST /api/v1/integration/excel/export           — export list[dict] to Excel
POST /api/v1/integration/excel/portfolio/report — create portfolio report
POST /api/v1/integration/excel/import           — import from a server-side file
POST /api/v1/integration/excel/import/upload    — import from a browser upload

Note on file paths:
    These endpoints operate on server-side file paths. In production they
    write to a configurable output directory (``EXCEL_OUTPUT_DIR`` app config,
    defaulting to ``~/.flinttrade/exports/``). Import endpoints read from
    paths the client specifies, validated against the configured directory.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, jsonify, request

from .excel_bridge import ExcelBridge, ExcelBridgeError

logger = logging.getLogger("flinttrade.integration.excel_routes")

excel_bp = Blueprint("excel", __name__, url_prefix="/api/v1/integration/excel")

# Module-level singleton
_bridge: ExcelBridge | None = None

_DEFAULT_OUTPUT_DIR = os.path.join(
    os.path.expanduser("~"), ".flinttrade", "exports"
)


def _get_bridge() -> ExcelBridge:
    """Return the module-level ExcelBridge singleton, creating it lazily."""
    global _bridge  # noqa: PLW0603
    if _bridge is None:
        _bridge = ExcelBridge()
    return _bridge


def init_excel_routes(bridge: ExcelBridge) -> None:
    """Inject an ExcelBridge instance into the blueprint's singleton.

    Args:
        bridge: The :class:`ExcelBridge` instance to use for all requests.
    """
    global _bridge  # noqa: PLW0603
    _bridge = bridge
    logger.info("ExcelBridge singleton injected into excel_routes")


def _output_dir() -> str:
    """Resolve the output directory, creating it if necessary."""
    from flask import current_app
    directory: str = current_app.config.get("EXCEL_OUTPUT_DIR", _DEFAULT_OUTPUT_DIR)
    Path(directory).mkdir(parents=True, exist_ok=True)
    return directory


def _safe_path(filename: str) -> str:
    """Build a safe absolute path within the output directory."""
    safe_name = Path(filename).name  # strip any directory traversal
    if not safe_name.endswith(".xlsx"):
        safe_name = safe_name + ".xlsx"
    return os.path.join(_output_dir(), safe_name)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@excel_bp.route("/export", methods=["POST"])
def export_data() -> tuple[Response, int]:
    """Export a list of dicts to an Excel file on the server.

    Request JSON:
        data       (list[dict], required): Rows to export.
        sheet_name (str, optional):       Worksheet name (default ``"Data"``).
        filename   (str, optional):       Output filename (default ``"export.xlsx"``).

    Returns:
        JSON ``{"status": "success", "data": {"file_path": "...", "rows": N}}``.
    """
    bridge = _get_bridge()
    body: dict[str, Any] = request.get_json(silent=True) or {}

    data: list[dict[str, Any]] = body.get("data", [])
    if not isinstance(data, list):
        return jsonify({"status": "error", "message": "data must be a list"}), 400

    sheet_name: str = body.get("sheet_name", "Data")
    filename: str = body.get("filename", "export.xlsx")
    file_path = _safe_path(filename)

    try:
        written_path = bridge.export_to_excel(data, sheet_name, file_path)
    except ExcelBridgeError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500

    logger.info("Excel export: %s (%d rows)", written_path, len(data))
    return jsonify({
        "status": "success",
        "data": {"file_path": written_path, "rows": len(data)},
    }), 200


_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@excel_bp.route("/export/download", methods=["POST"])
def export_download() -> Response:
    """Export rows and stream the ``.xlsx`` straight back as a browser download.

    Unlike ``/export`` (which writes a server-side file and returns its path),
    this builds the workbook in memory and returns the bytes with a
    ``Content-Disposition: attachment`` header, so the terminal can trigger a
    real download that works in the browser and the desktop shell alike — no
    server-side file to locate.

    Request JSON:
        data       (list[dict], required): Rows to export.
        sheet_name (str, optional):        Worksheet name (default ``"Data"``).
        filename   (str, optional):        Download filename (default ``"export.xlsx"``).

    Returns:
        The ``.xlsx`` bytes as an attachment, or a JSON error.
    """
    bridge = _get_bridge()
    body: dict[str, Any] = request.get_json(silent=True) or {}

    data: list[dict[str, Any]] = body.get("data", [])
    if not isinstance(data, list):
        return Response(
            '{"status": "error", "message": "data must be a list"}',
            status=400,
            mimetype="application/json",
        )

    sheet_name: str = body.get("sheet_name", "Data")
    raw_name = Path(str(body.get("filename", "export.xlsx"))).name  # strip traversal
    filename = raw_name if raw_name.endswith(".xlsx") else f"{raw_name}.xlsx"

    try:
        payload = bridge.export_to_bytes(data, sheet_name)
    except ExcelBridgeError as exc:
        return Response(
            f'{{"status": "error", "message": "{exc}"}}',
            status=500,
            mimetype="application/json",
        )

    logger.info("Excel download: %s (%d rows, %d bytes)", filename, len(data), len(payload))
    return Response(
        payload,
        mimetype=_XLSX_MIME,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(payload)),
        },
    )


# ---------------------------------------------------------------------------
# Portfolio report
# ---------------------------------------------------------------------------


@excel_bp.route("/portfolio/report", methods=["POST"])
def portfolio_report() -> tuple[Response, int]:
    """Create a formatted multi-sheet portfolio report.

    Request JSON:
        positions (list[dict], optional): Position rows (default ``[]``).
        holdings  (list[dict], optional): Holdings rows (default ``[]``).
        filename  (str, optional):        Output filename (default ``"portfolio.xlsx"``).

    Returns:
        JSON ``{"status": "success", "data": {"file_path": "..."}}``.
    """
    bridge = _get_bridge()
    body: dict[str, Any] = request.get_json(silent=True) or {}

    positions: list[dict[str, Any]] = body.get("positions", [])
    holdings: list[dict[str, Any]] = body.get("holdings", [])
    filename: str = body.get("filename", "portfolio.xlsx")
    file_path = _safe_path(filename)

    try:
        written_path = bridge.create_portfolio_report(positions, holdings, file_path)
    except ExcelBridgeError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500

    logger.info(
        "Portfolio report: %s (%d positions, %d holdings)",
        written_path, len(positions), len(holdings),
    )
    return jsonify({
        "status": "success",
        "data": {
            "file_path": written_path,
            "positions": len(positions),
            "holdings": len(holdings),
        },
    }), 200


@excel_bp.route("/portfolio/report/download", methods=["POST"])
def portfolio_report_download() -> Response:
    """Build the multi-sheet portfolio report and stream it as a browser download.

    The streaming counterpart of ``/portfolio/report`` (which writes a
    server-side file) — builds Positions/Holdings/Summary in memory and returns
    the ``.xlsx`` bytes with an attachment header, so the terminal triggers a
    real download with no server-side file to locate.

    Request JSON:
        positions (list[dict], optional): Position rows (default ``[]``).
        holdings  (list[dict], optional): Holdings rows (default ``[]``).
        filename  (str, optional):        Download filename (default ``"portfolio.xlsx"``).
    """
    bridge = _get_bridge()
    body: dict[str, Any] = request.get_json(silent=True) or {}

    positions: list[dict[str, Any]] = body.get("positions", [])
    holdings: list[dict[str, Any]] = body.get("holdings", [])
    raw_name = Path(str(body.get("filename", "portfolio.xlsx"))).name  # strip traversal
    filename = raw_name if raw_name.endswith(".xlsx") else f"{raw_name}.xlsx"

    try:
        payload = bridge.create_portfolio_report_bytes(positions, holdings)
    except ExcelBridgeError as exc:
        return Response(
            f'{{"status": "error", "message": "{exc}"}}',
            status=500,
            mimetype="application/json",
        )

    logger.info(
        "Portfolio report download: %s (%d positions, %d holdings, %d bytes)",
        filename, len(positions), len(holdings), len(payload),
    )
    return Response(
        payload,
        mimetype=_XLSX_MIME,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(payload)),
        },
    )


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


@excel_bp.route("/import", methods=["POST"])
def import_data() -> tuple[Response, int]:
    """Import data from an Excel file on the server.

    Request JSON:
        file_path  (str, required):  Path to the ``.xlsx`` file.
        sheet_name (str, optional):  Worksheet to read. Omitted → the
            workbook's FIRST sheet (most workbooks, incl. FlintTrade's own
            exports, are not literally named "Sheet1").

    Returns:
        JSON ``{"status": "success", "data": {"rows": [...], "count": N}}``.
    """
    bridge = _get_bridge()
    body: dict[str, Any] = request.get_json(silent=True) or {}

    file_path: str = body.get("file_path", "").strip()
    if not file_path:
        return jsonify({"status": "error", "message": "file_path is required"}), 400

    # None → the bridge reads the workbook's FIRST sheet (most workbooks are
    # not literally named "Sheet1" — incl. FlintTrade's own exports).
    sheet_name: str | None = body.get("sheet_name") or None

    try:
        rows = bridge.import_from_excel(file_path, sheet_name)
    except ExcelBridgeError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    return jsonify({
        "status": "success",
        "data": {"rows": rows, "count": len(rows)},
    }), 200


@excel_bp.route("/import/upload", methods=["POST"])
def import_upload() -> tuple[Response, int]:
    """Import data from a browser-uploaded ``.xlsx`` (multipart/form-data).

    Companion to ``/import`` (which reads a server-side path): the uploaded
    workbook is spooled to a temporary file, parsed via the same bridge, and
    the temp file removed.

    Form fields:
        file       (file, required):  The ``.xlsx`` upload.
        sheet_name (str, optional):   Worksheet to read. Omitted → the
            workbook's FIRST sheet.

    Returns:
        JSON ``{"status": "success", "data": {"rows": [...], "count": N,
        "sheet_name": "<sheet actually read>"}}``.
    """
    upload = request.files.get("file")
    if upload is None or not (upload.filename or "").strip():
        return jsonify({"status": "error", "message": "file is required"}), 400

    # None → first sheet (see /import).
    sheet_name: str | None = request.form.get("sheet_name") or None

    tmp_path: str | None = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".xlsx")
        with os.fdopen(fd, "wb") as handle:
            upload.save(handle)
        rows, resolved_sheet = _get_bridge().import_from_excel_named(tmp_path, sheet_name)
    except ExcelBridgeError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    logger.info(
        "Excel upload import: %s rows from %s (sheet=%s)",
        len(rows), upload.filename, resolved_sheet,
    )
    return jsonify({
        "status": "success",
        "data": {"rows": rows, "count": len(rows), "sheet_name": resolved_sheet},
    }), 200
