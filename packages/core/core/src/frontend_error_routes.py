"""Frontend error reporting + changelog Blueprint.

External URLs (frontend calls these via /ft-api/v1/*; the WSGI prefix stripper
in app.py rewrites to /v1/* before Flask dispatch):

- ``POST /ft-api/v1/errors``    — ingest frontend runtime errors into
  ``ErrorLog`` for post-mortem debugging. Fire-and-forget from the client.
- ``GET  /ft-api/v1/changelog`` — serve the repo changelog.md as plain
  markdown so the in-app Changelog viewer renders the same source of
  truth as GitHub.

Blueprint registered at ``/v1`` (post-strip form).

Both endpoints log failures via structlog rather than raising, so the
UI never receives a 5xx for these auxiliary calls.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

logger = logging.getLogger("flinttrade.core.frontend_error_routes")

frontend_errors_bp = Blueprint(
    "frontend_errors", __name__, url_prefix="/v1"
)

# Repo root — four parents up from this file (packages/core/core/src/<file>.py).
_REPO_ROOT = Path(__file__).resolve().parents[4]
_CHANGELOG_PATH = _REPO_ROOT / "changelog.md"

# Cap frontend error payloads so a runaway client can't flood the DB.
_MAX_MESSAGE_CHARS = 2_000
_MAX_STACK_CHARS = 10_000


@frontend_errors_bp.route("/errors", methods=["POST"])
def report_frontend_error() -> tuple[Response, int]:
    """Persist a frontend runtime error into the ErrorLog.

    Body shape (every field optional — client sends best-effort):

    .. code-block:: json

        {
            "message": "TypeError: Cannot read property 'x' of undefined",
            "stack": "at Component (bundle.js:...)",
            "url": "https://host/trade",
            "userAgent": "Mozilla/5.0 ...",
            "timestamp": "2026-04-19T10:00:00Z"
        }

    Returns ``{"status": "ok"}`` on success. Failures return HTTP 200
    with ``status: "error"`` so the fire-and-forget client never retries.
    """
    log = current_app.config.get("ERROR_LOG")
    if log is None:
        logger.info("Frontend error received but ERROR_LOG not configured")
        return jsonify({"status": "error", "message": "error log unavailable"}), 200

    body: dict[str, Any] = request.get_json(silent=True) or {}
    message = str(body.get("message", "")).strip()[:_MAX_MESSAGE_CHARS]
    stack = str(body.get("stack", "")).strip()[:_MAX_STACK_CHARS]
    url = str(body.get("url", ""))[:500]

    if not message:
        return jsonify({"status": "error", "message": "message is required"}), 400

    try:
        # Build a synthetic exception carrying the client stack trace.
        err = RuntimeError(message)
        err.__traceback__ = None  # client-supplied stack lives in the log row
        log.log(
            route=url or "frontend",
            method="CLIENT",
            status_code=0,
            request_body={"userAgent": body.get("userAgent"), "client_stack": stack},
            error=err,
            user_id=body.get("user_id"),
        )
        return jsonify({"status": "ok"}), 200
    except Exception as exc:
        logger.exception("Failed to persist frontend error: %s", exc)
        return jsonify({"status": "error", "message": "persist failed"}), 200


@frontend_errors_bp.route("/changelog", methods=["GET"])
def get_changelog() -> tuple[Response, int]:
    """Serve the repo changelog.md as markdown for the in-app viewer.

    Uses a filesystem read (not a git lookup) so the frontend always
    reflects what is on disk in the current deployment.
    """
    try:
        if not _CHANGELOG_PATH.exists():
            return jsonify({"status": "error", "message": "changelog.md not found"}), 404
        text = _CHANGELOG_PATH.read_text(encoding="utf-8")
        # Content-Type is markdown; the viewer renders it client-side.
        resp = current_app.response_class(
            text, status=200, mimetype="text/markdown; charset=utf-8"
        )
        resp.headers["Cache-Control"] = "no-cache"
        return resp, 200
    except Exception as exc:
        logger.exception("Failed to serve changelog.md: %s", exc)
        return jsonify({"status": "error", "message": "read failed"}), 500
