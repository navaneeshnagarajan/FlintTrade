"""Strategy Runner Flask Blueprint — user strategy management endpoints.

All endpoints are under the ``/api/v1/strategies/`` prefix.  The
:class:`~flinttrade_engine.strategy_runner.UserStrategyRunner` instance is
stored on ``app.config["STRATEGY_RUNNER"]`` and injected at app creation.

The :class:`~flinttrade_engine.scheduler.CronStrategyScheduler` instance is
stored on ``app.config["CRON_SCHEDULER"]`` and injected at app creation.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

from flinttrade_core.rate_limiter import rate_limit

from .mode_guard import require_non_explore

logger = logging.getLogger("flinttrade.engine.strategy_routes")

strategy_bp = Blueprint("strategies", __name__, url_prefix="/api/v1/strategies")


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


def _get_cron_scheduler() -> Any:
    """Retrieve the CronStrategyScheduler from the Flask app config."""
    return current_app.config.get("CRON_SCHEDULER")


def _cron_scheduler_required() -> tuple[Any, Response | None]:
    """Return (scheduler, None) or (None, error_response)."""
    scheduler = _get_cron_scheduler()
    if scheduler is None:
        return None, (
            jsonify({"status": "error", "message": "Cron scheduler not configured"}),
            503,
        )
    return scheduler, None


def shutdown_strategy_runtime(app: Any) -> list[str]:
    """Stop every uploaded strategy process owned by a Flask application.

    The process-level application owner should call this during graceful
    shutdown after request admission has closed. Cron shutdown remains owned
    by the parent's existing ``CRON_SCHEDULER`` lifecycle.

    Args:
        app: Flask application carrying ``STRATEGY_RUNNER`` in ``config``.

    Returns:
        Strategy IDs stopped by the runner, or an empty list when no runner is
        configured.
    """
    runner = app.config.get("STRATEGY_RUNNER")
    if runner is None:
        return []
    return runner.stop_all()


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
    name: str = body.get("name", "") or request.form.get("name", "")
    code: str = body.get("code", "") or request.form.get("code", "")

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
    if len(code) > 100_000:
        return jsonify({"status": "error", "message": "Strategy code too large — maximum 100KB"}), 413

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
    except ValueError:
        return jsonify({"status": "error", "message": "Request could not be processed"}), 422
    except Exception:
        logger.exception("Failed to upload strategy '%s'", name)
        return jsonify({"status": "error", "message": "Upload failed. Check server logs."}), 500

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

    return jsonify({"status": "success", "data": {"strategies": runner.list_strategies()}})


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------


@strategy_bp.route("/<strategy_id>/start", methods=["POST"])
@require_non_explore
@rate_limit("smart_orders", user_rate=2, global_rate=20)
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
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "Requested resource was not found"}), 404
    except RuntimeError:
        return jsonify({"status": "error", "message": "Request conflicts with the current state"}), 409
    except Exception:
        logger.exception("Failed to start strategy %s", strategy_id)
        return jsonify({"status": "error", "message": "Start failed. Check server logs."}), 500

    status = runner.get_status(strategy_id)
    return jsonify({"status": "success", "data": {"message": "Strategy started", "strategy": status}})


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
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "Requested resource was not found"}), 404
    except RuntimeError:
        # Not running — treat as a no-op success
        return jsonify({"status": "success", "message": "Strategy was already stopped"})
    except Exception:
        logger.exception("Failed to stop strategy %s", strategy_id)
        return jsonify({"status": "error", "message": "Stop failed. Check server logs."}), 500

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
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "Requested resource was not found"}), 404
    except Exception:
        logger.exception("Failed to delete strategy %s", strategy_id)
        return jsonify({"status": "error", "message": "Delete failed. Check server logs."}), 500

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
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "Requested resource was not found"}), 404

    return jsonify({"status": "success", "data": {"strategy": status}})


# ---------------------------------------------------------------------------
# Forward trades
# ---------------------------------------------------------------------------


@strategy_bp.route("/<strategy_id>/trades", methods=["GET"])
def get_strategy_trades(strategy_id: str) -> Response:
    """Return forward trades executed by a strategy.

    Args:
        strategy_id: UUID of the strategy.

    Returns:
        JSON with ``status``, ``strategy_id``, and ``trades`` (list).

    TODO: Forward trade tracking is a future feature.  The strategy runner
    will need to persist executed trades against each strategy UUID so they
    can be retrieved here.  For now returns an empty list so the frontend
    call succeeds without a 404.
    """
    # Verify the strategy exists so unknown IDs still return 404.
    runner, err = _runner_required()
    if err:
        return err

    try:
        runner.get_status(strategy_id)
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "Requested resource was not found"}), 404

    return jsonify({"status": "success", "data": {"strategy_id": strategy_id, "trades": []}})


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
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "Requested resource was not found"}), 404

    return jsonify({"status": "success", "data": {"strategy_id": strategy_id, "lines": log_lines}})


# ---------------------------------------------------------------------------
# Cron scheduling
# ---------------------------------------------------------------------------

# Supported exchanges for cron scheduling — mirrors EXCHANGE_SCHEDULES in scheduler.py.
_SUPPORTED_EXCHANGES = frozenset({
    "NSE", "BSE", "NFO", "BFO", "CDS", "BCD",
    "MCX", "NCDEX", "NCO",
    "NSE_INDEX", "BSE_INDEX", "MCX_INDEX", "GLOBAL_INDEX",
    "DELTA",
})


@strategy_bp.route("/<strategy_id>/schedule", methods=["POST"])
@require_non_explore
def create_strategy_schedule(strategy_id: str) -> Response:
    """Attach a cron schedule to an existing strategy.

    The scheduler fires the strategy's start endpoint at the specified cron
    time if market is open and the day is not a holiday.

    Request body (JSON):

    .. code-block:: json

        {
            "cron": "30 9 * * 1-5",
            "exchange": "NSE",
            "symbol": "RELIANCE"
        }

    ``cron`` must be a valid 5-field expression (minute hour dom month dow)
    that will be evaluated in IST (Asia/Kolkata).

    ``exchange`` is optional and defaults to ``"NSE"``.

    ``symbol`` is optional and is retained for symbol-scoped market sessions.

    Args:
        strategy_id: UUID of the strategy to schedule.

    Returns:
        JSON with ``job_id`` and echo of the schedule parameters on success.
    """
    # Validate strategy exists
    runner, err = _runner_required()
    if err:
        return err

    try:
        runner.get_status(strategy_id)
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "Requested resource was not found"}), 404

    # Validate cron scheduler availability
    cron_scheduler, err = _cron_scheduler_required()
    if err:
        return err

    body: dict[str, Any] = request.get_json(silent=True) or {}
    cron_expr: str = (body.get("cron") or "").strip()
    exchange: str = (body.get("exchange") or "NSE").strip().upper()
    symbol: str = str(body.get("symbol") or "").strip().upper()

    if not cron_expr:
        return jsonify({"status": "error", "message": "cron expression is required"}), 400

    if exchange not in _SUPPORTED_EXCHANGES:
        return jsonify(
            {
                "status": "error",
                "message": f"Unsupported exchange {exchange!r}. Supported: {sorted(_SUPPORTED_EXCHANGES)}",
            }
        ), 400

    # Validate cron expression before registering
    try:
        from .scheduler import CronStrategyScheduler
        CronStrategyScheduler._parse_cron_expr(cron_expr)
    except ValueError:
        return jsonify({"status": "error", "message": "Cron expression expected 5 fields"}), 400

    # Build the callback — fires strategy start
    def _strategy_start_callback() -> None:
        logger.info("Cron-triggered start for strategy %s", strategy_id)
        try:
            runner.start(strategy_id)
        except RuntimeError:
            # Already running — that is fine for a cron trigger
            pass
        except Exception as exc:
            logger.error("Cron start failed for strategy %s: %s", strategy_id, exc)

    try:
        job_id = cron_scheduler.schedule(
            strategy_id=strategy_id,
            cron_expr=cron_expr,
            callback=_strategy_start_callback,
            exchange=exchange,
            symbol=symbol,
        )
    except ValueError:
        return jsonify({"status": "error", "message": "Cron expression expected 5 fields"}), 400
    except Exception:
        logger.exception("Failed to schedule strategy %s", strategy_id)
        return jsonify({"status": "error", "message": "Scheduling failed. Check server logs."}), 500

    return (
        jsonify(
            {
                "status": "success",
                "message": f"Strategy '{strategy_id}' scheduled",
                "data": {
                    "strategy_id": strategy_id,
                    "cron": cron_expr,
                    "exchange": exchange,
                    "symbol": symbol,
                    "job_id": job_id,
                },
            }
        ),
        201,
    )


@strategy_bp.route("/<strategy_id>/schedule", methods=["DELETE"])
def delete_strategy_schedule(strategy_id: str) -> Response:
    """Remove the cron schedule for a strategy.

    Args:
        strategy_id: UUID of the strategy.

    Returns:
        JSON confirmation.  Returns 404 if no schedule exists.
    """
    cron_scheduler, err = _cron_scheduler_required()
    if err:
        return err

    removed = cron_scheduler.unschedule(strategy_id)
    if not removed:
        return jsonify({"status": "error", "message": f"No schedule found for strategy '{strategy_id}'"}), 404

    return jsonify({"status": "success", "message": f"Schedule removed for strategy '{strategy_id}'"})


@strategy_bp.route("/scheduled", methods=["GET"])
def list_scheduled_strategies() -> Response:
    """List all strategies that have an active cron schedule.

    Returns:
        JSON with a ``schedules`` list.  Each entry contains:
        ``strategy_id``, ``cron``, ``exchange``, ``symbol``, ``job_id``,
        ``last_skipped_reason``, ``next_fire_time``.
    """
    cron_scheduler, err = _cron_scheduler_required()
    if err:
        return err

    jobs = cron_scheduler.list_jobs()
    # Normalise key name: expose ``cron`` (not ``cron_expr``) to match the
    # POST request body shape so clients can round-trip the value.
    normalised = [
        {
            "strategy_id": j["strategy_id"],
            "cron": j["cron_expr"],
            "exchange": j["exchange"],
            "symbol": j["symbol"],
            "job_id": j["job_id"],
            "last_skipped_reason": j["last_skipped_reason"],
            "next_fire_time": j["next_fire_time"],
        }
        for j in jobs
    ]
    return jsonify({"status": "success", "data": {"schedules": normalised}})
