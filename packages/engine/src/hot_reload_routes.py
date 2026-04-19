"""Hot-Reload Admin Routes — manage user strategy files via HTTP.

Blueprint prefix: ``/admin/strategies``

Endpoints
---------
GET  /admin/strategies/discovered
    List all ``.py`` files in the strategies directory that expose a
    ``Strategy`` class and pass AST validation.

POST /admin/strategies/<name>/reload
    Force-reload a specific strategy by name.

POST /admin/strategies/upload
    Multipart file upload: validate AST, save to the strategies directory.

DELETE /admin/strategies/<name>
    Delete a strategy file from disk.

The :class:`~packages.engine.src.strategy_hot_reload.StrategyHotReloader`
instance must be stored on ``app.config["HOT_RELOADER"]`` before the
blueprint is registered.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, request

logger = logging.getLogger("flinttrade.engine.hot_reload_routes")

hot_reload_bp = Blueprint("hot_reload", __name__, url_prefix="/admin/strategies")

# Max upload size: 512 KB
_MAX_UPLOAD_BYTES: int = 512 * 1024

# Valid Python identifier pattern (used to sanitise <name> path segment)
_VALID_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_reloader():
    """Return the StrategyHotReloader from the Flask app config.

    Returns:
        The reloader instance, or ``None`` if not configured.
    """
    return current_app.config.get("HOT_RELOADER")


def _reloader_required():
    """Return ``(reloader, None)`` or ``(None, error_response)``."""
    reloader = _get_reloader()
    if reloader is None:
        return None, (
            jsonify({"status": "error", "message": "Hot-reloader not configured"}),
            503,
        )
    return reloader, None


def _validate_name(name: str) -> Response | None:
    """Return an error response if *name* is not a valid Python identifier.

    Args:
        name: Candidate strategy name.

    Returns:
        A :class:`flask.Response` with HTTP 400 if invalid, else ``None``.
    """
    if not _VALID_NAME_RE.match(name):
        return (
            jsonify(
                {
                    "status": "error",
                    "message": (
                        f"Invalid strategy name '{name}'. "
                        "Use letters, digits, and underscores only."
                    ),
                }
            ),
            400,
        )
    return None


# ---------------------------------------------------------------------------
# GET /admin/strategies/discovered
# ---------------------------------------------------------------------------


@hot_reload_bp.get("/discovered")
def get_discovered() -> tuple[Response, int]:
    """List all discoverable strategies in the strategies directory.

    Returns:
        JSON body::

            {
                "status": "ok",
                "strategies": ["ema_crossover", "momentum_scalper"],
                "count": 2
            }

    Error (503) if the reloader is not configured.
    """
    reloader, err = _reloader_required()
    if err:
        return err  # type: ignore[return-value]

    names = reloader.discover()
    logger.debug("Discovered %d strategies", len(names))
    return jsonify({"status": "ok", "strategies": names, "count": len(names)}), 200


# ---------------------------------------------------------------------------
# POST /admin/strategies/<name>/reload
# ---------------------------------------------------------------------------


@hot_reload_bp.post("/<name>/reload")
def reload_strategy(name: str) -> tuple[Response, int]:
    """Force-reload a strategy by name.

    Args:
        name: Strategy name (path segment).

    Returns:
        JSON body::

            {"status": "ok", "message": "Strategy 'ema_crossover' reloaded successfully"}

        or::

            {"status": "error", "message": "<reason>"}

    Status codes: 200 on success, 400 on bad name, 422 on reload failure,
    503 if reloader not configured.
    """
    err_resp = _validate_name(name)
    if err_resp:
        return err_resp  # type: ignore[return-value]

    reloader, err = _reloader_required()
    if err:
        return err  # type: ignore[return-value]

    logger.info("Reload requested for strategy '%s'", name)
    success, message = reloader.reload(name)

    if success:
        return jsonify({"status": "ok", "message": message}), 200
    return jsonify({"status": "error", "message": message}), 422


# ---------------------------------------------------------------------------
# POST /admin/strategies/upload
# ---------------------------------------------------------------------------


@hot_reload_bp.post("/upload")
def upload_strategy() -> tuple[Response, int]:
    """Upload a new strategy file after AST validation.

    Request
    -------
    Multipart form-data with a ``file`` field (Python source) and an
    optional ``name`` field.  If ``name`` is omitted the uploaded filename
    (without extension) is used.  The name must be a valid Python identifier.

    Returns:
        JSON body::

            {"status": "ok", "message": "Strategy 'my_strategy' uploaded", "name": "my_strategy"}

        or::

            {"status": "error", "message": "<reason>", "errors": [...]}

    Status codes: 201 on success, 400 on bad input, 422 on validation
    failure, 503 if reloader not configured.
    """
    reloader, err = _reloader_required()
    if err:
        return err  # type: ignore[return-value]

    if "file" not in request.files:
        return jsonify({"status": "error", "message": "No 'file' field in request"}), 400

    uploaded_file = request.files["file"]
    if not uploaded_file.filename:
        return jsonify({"status": "error", "message": "Uploaded file has no filename"}), 400

    # Resolve strategy name
    raw_name: str = request.form.get("name", "") or Path(uploaded_file.filename).stem
    err_resp = _validate_name(raw_name)
    if err_resp:
        return err_resp  # type: ignore[return-value]

    # Size guard — read up to max+1 bytes to detect oversize uploads
    raw_bytes = uploaded_file.read(_MAX_UPLOAD_BYTES + 1)
    if len(raw_bytes) > _MAX_UPLOAD_BYTES:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"Strategy file exceeds maximum size of {_MAX_UPLOAD_BYTES // 1024} KB",
                }
            ),
            400,
        )

    try:
        source = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return jsonify({"status": "error", "message": "File must be valid UTF-8 text"}), 400

    # AST validation
    valid, errors = reloader.validate(source)
    if not valid:
        logger.warning(
            "Upload rejected for '%s': %d validation error(s)", raw_name, len(errors)
        )
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"Strategy failed validation ({len(errors)} issue(s))",
                    "errors": errors,
                }
            ),
            422,
        )

    # Write to strategies directory
    dest = reloader._dir / f"{raw_name}.py"  # noqa: SLF001
    try:
        dest.write_text(source, encoding="utf-8")
    except OSError as exc:
        logger.error("Failed to write strategy '%s': %s", raw_name, exc)
        return jsonify({"status": "error", "message": f"Could not save strategy: {exc}"}), 500

    logger.info("Strategy uploaded: '%s' → %s", raw_name, dest)
    return (
        jsonify(
            {
                "status": "ok",
                "message": f"Strategy '{raw_name}' uploaded successfully",
                "name": raw_name,
            }
        ),
        201,
    )


# ---------------------------------------------------------------------------
# DELETE /admin/strategies/<name>
# ---------------------------------------------------------------------------


@hot_reload_bp.delete("/<name>")
def delete_strategy(name: str) -> tuple[Response, int]:
    """Delete a strategy file from the strategies directory.

    Args:
        name: Strategy name (path segment).

    Returns:
        JSON body::

            {"status": "ok", "message": "Strategy 'my_strategy' deleted"}

        or::

            {"status": "error", "message": "Strategy 'my_strategy' not found"}

    Status codes: 200 on success, 400 on bad name, 404 not found,
    503 if reloader not configured.
    """
    err_resp = _validate_name(name)
    if err_resp:
        return err_resp  # type: ignore[return-value]

    reloader, err = _reloader_required()
    if err:
        return err  # type: ignore[return-value]

    dest = reloader._dir / f"{name}.py"  # noqa: SLF001
    if not dest.exists():
        return (
            jsonify({"status": "error", "message": f"Strategy '{name}' not found"}),
            404,
        )

    # Stop the strategy if it is loaded in the cache
    reloader._evict(name)  # noqa: SLF001

    try:
        dest.unlink()
    except OSError as exc:
        logger.error("Failed to delete strategy '%s': %s", name, exc)
        return jsonify({"status": "error", "message": f"Could not delete strategy: {exc}"}), 500

    logger.info("Strategy deleted: '%s'", name)
    return jsonify({"status": "ok", "message": f"Strategy '{name}' deleted"}), 200
