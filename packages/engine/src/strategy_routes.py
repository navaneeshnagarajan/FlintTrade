"""Strategy Runner Flask Blueprint — user strategy management endpoints.

All endpoints are under the ``/ft-api/v1/strategies/`` prefix.  The
:class:`~packages.engine.src.strategy_runner.UserStrategyRunner` instance is
stored on ``app.config["STRATEGY_RUNNER"]`` and injected at app creation.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

logger = logging.getLogger("flinttrade.engine.strategy_routes")

strategy_bp = Blueprint("strategies", __name__, url_prefix="/ft-api/v1/strategies")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_runner():
    """Retrieve the UserStrategyRunner from the Flask app config."""
    return current_app.config.get("STRATEGY_RUNNER")


def _runner_required() -> tuple[Any, Response | None]:
    """Return (runner, None) or (None, error_response)."""
    runner = _get_runner()
    if runner is None:
        return None, (
            jsonify({"status": "error", "message": "Strategy runner not configured"}),
            503,
        )
    return runner, None


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


@strategy_bp.route("", methods=["POST"])
@strategy_bp.route("/upload", methods=["POST"])
def upload_strategy() -> Response:
    """Upload a Python strategy file.

    Accepts either a JSON body ``{"name": "my_strategy", "code": "..."}`` or a
    multipart form with a ``file`` field and an optional ``name`` field.

    Returns:
        JSON with ``strategy_id`` on success, or error details including
        validation violations on failure.
    """
    runner, err = _runner_required()
    if err:
        return err

    # Try JSON body first
    body: dict[str, Any] = request.get_json(silent=True) or {}
    name: str = body.get("name", "")
    code: str = body.get("code", "")

    # Fall back to multipart file upload
    if not code and "file" in request.files:
        uploaded_file = request.files["file"]
        code = uploaded_file.read().decode("utf-8", errors="replace")
        if not name:
            # Derive name from filename (strip .py extension)
            filename = uploaded_file.filename or "strategy"
            name = filename.rsplit(".", 1)[0]

    if not name:
        return jsonify({"status": "error", "message": "Strategy name is required"}), 400
    if not code:
        return jsonify({"status": "error", "message": "Strategy code is required"}), 400

    # Validate first — return violations before saving
    violations = runner.validate(code)
    if violations:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Strategy failed security validation",
                    "violations": violations,
                }
            ),
            422,
        )

    try:
        strategy_id = runner.upload(name, code)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 422
    except Exception as exc:
        logger.error("Failed to upload strategy '%s': %s", name, exc)
        return jsonify({"status": "error", "message": f"Upload failed: {exc}"}), 500

    return (
        jsonify(
            {
                "status": "success",
                "message": f"Strategy '{name}' uploaded successfully",
                "strategy_id": strategy_id,
            }
        ),
        201,
    )


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@strategy_bp.route("", methods=["GET"])
def list_strategies() -> Response:
    """List all uploaded strategies with their current status.

    Returns:
        JSON with a list of strategy status objects.
    """
    runner, err = _runner_required()
    if err:
        return err

    return jsonify({"status": "success", "strategies": runner.list_strategies()})


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------


@strategy_bp.route("/<strategy_id>/start", methods=["POST"])
def start_strategy(strategy_id: str) -> Response:
    """Start a strategy subprocess.

    Args:
        strategy_id: UUID of the strategy to start.

    Returns:
        JSON confirmation with current status.
    """
    runner, err = _runner_required()
    if err:
        return err

    try:
        runner.start(strategy_id)
    except FileNotFoundError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 404
    except RuntimeError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 409
    except Exception as exc:
        logger.error("Failed to start strategy %s: %s", strategy_id, exc)
        return jsonify({"status": "error", "message": f"Start failed: {exc}"}), 500

    status = runner.get_status(strategy_id)
    return jsonify({"status": "success", "message": "Strategy started", "strategy": status})


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------


@strategy_bp.route("/<strategy_id>/stop", methods=["POST"])
def stop_strategy(strategy_id: str) -> Response:
    """Stop a running strategy subprocess.

    Args:
        strategy_id: UUID of the strategy to stop.

    Returns:
        JSON confirmation.
    """
    runner, err = _runner_required()
    if err:
        return err

    try:
        runner.stop(strategy_id)
    except FileNotFoundError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 404
    except RuntimeError as exc:
        # Not running — treat as a no-op success
        return jsonify({"status": "success", "message": str(exc)})
    except Exception as exc:
        logger.error("Failed to stop strategy %s: %s", strategy_id, exc)
        return jsonify({"status": "error", "message": f"Stop failed: {exc}"}), 500

    return jsonify({"status": "success", "message": "Strategy stopped"})


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@strategy_bp.route("/<strategy_id>", methods=["DELETE"])
def delete_strategy(strategy_id: str) -> Response:
    """Delete a strategy (stops it first if running).

    Args:
        strategy_id: UUID of the strategy to delete.

    Returns:
        JSON confirmation.
    """
    runner, err = _runner_required()
    if err:
        return err

    try:
        runner.delete(strategy_id)
    except FileNotFoundError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 404
    except Exception as exc:
        logger.error("Failed to delete strategy %s: %s", strategy_id, exc)
        return jsonify({"status": "error", "message": f"Delete failed: {exc}"}), 500

    return jsonify({"status": "success", "message": "Strategy deleted"})


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@strategy_bp.route("/<strategy_id>/status", methods=["GET"])
def get_strategy_status(strategy_id: str) -> Response:
    """Get current status of a strategy.

    Args:
        strategy_id: UUID of the strategy.

    Returns:
        JSON with state, pid, memory_mb, uptime_seconds.
    """
    runner, err = _runner_required()
    if err:
        return err

    try:
        status = runner.get_status(strategy_id)
    except FileNotFoundError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 404

    return jsonify({"status": "success", "strategy": status})


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


@strategy_bp.route("/<strategy_id>/logs", methods=["GET"])
def get_strategy_logs(strategy_id: str) -> Response:
    """Return recent log output for a strategy.

    Query params:
        lines (int): Number of tail lines to return (default 100, max 1000).

    Returns:
        JSON with ``lines`` list of log strings.
    """
    runner, err = _runner_required()
    if err:
        return err

    try:
        n = min(int(request.args.get("lines", 100)), 1000)
    except (TypeError, ValueError):
        n = 100

    try:
        log_lines = runner.get_logs(strategy_id, lines=n)
    except FileNotFoundError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 404

    return jsonify({"status": "success", "strategy_id": strategy_id, "lines": log_lines})
