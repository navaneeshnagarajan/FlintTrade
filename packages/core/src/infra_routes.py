"""Infrastructure admin routes: traffic log, latency monitor, API analyser.

Registered as a Blueprint in ``create_flask_app()`` under the admin
prefix.  All routes are dev/debug endpoints — gated by the same
``app.debug`` or ``FLINTTRADE_DEV`` check that guards admin_routes.

Routes
------
GET /v1/admin/traffic                — paginated traffic log
GET /v1/admin/traffic/stats          — aggregate traffic statistics
GET /v1/admin/traffic/export         — CSV download

GET /v1/admin/latency/stats          — per-broker percentile stats
GET /v1/admin/latency/histogram      — histogram for a single broker
GET /v1/admin/latency/slow           — top-N slowest orders

GET /v1/admin/analyzer/calls         — paginated API call log
GET /v1/admin/analyzer/<id>/replay   — full request + response for replay
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

logger = logging.getLogger("flinttrade.infra_routes")

infra_bp = Blueprint("infra", __name__, url_prefix="/v1/admin")


# ---------------------------------------------------------------------------
# Helpers — lazy config lookup
# ---------------------------------------------------------------------------


def _get_traffic_logger():  # type: ignore[return]
    """Return the TrafficLogger instance from app config."""
    tl = current_app.config.get("TRAFFIC_LOGGER")
    if tl is None:
        from pathlib import Path  # noqa: PLC0415

        from .traffic_logger import TrafficLogger  # noqa: PLC0415

        db_path = Path.home() / ".flinttrade" / "traffic_log.duckdb"
        tl = TrafficLogger(str(db_path))
        current_app.config["TRAFFIC_LOGGER"] = tl
    return tl


def _get_latency_monitor():  # type: ignore[return]
    """Return the LatencyMonitor instance from app config."""
    lm = current_app.config.get("LATENCY_MONITOR")
    if lm is None:
        from pathlib import Path  # noqa: PLC0415

        from packages.engine.src.latency_monitor import LatencyMonitor  # noqa: PLC0415

        db_path = Path.home() / ".flinttrade" / "latency_log.duckdb"
        lm = LatencyMonitor(str(db_path))
        current_app.config["LATENCY_MONITOR"] = lm
    return lm


def _get_api_analyzer():  # type: ignore[return]
    """Return the APIAnalyzer instance from app config."""
    az = current_app.config.get("API_ANALYZER")
    if az is None:
        from pathlib import Path  # noqa: PLC0415

        from .api_analyzer import APIAnalyzer  # noqa: PLC0415

        db_path = Path.home() / ".flinttrade" / "api_analyzer.duckdb"
        az = APIAnalyzer(str(db_path))
        current_app.config["API_ANALYZER"] = az
    return az


def _parse_int_param(name: str, default: int, min_val: int, max_val: int) -> tuple[int, Response | None]:
    """Parse and validate a single integer query parameter.

    Args:
        name: Query parameter name.
        default: Value to use when the parameter is absent.
        min_val: Minimum allowed value.
        max_val: Maximum allowed value.

    Returns:
        Tuple of (parsed_int, None) on success, or (0, error_response) on failure.
    """
    raw = request.args.get(name, str(default))
    try:
        val = int(raw)
        if val < min_val:
            raise ValueError
        return min(val, max_val), None
    except ValueError:
        err: Response = jsonify(
            {"status": "error", "message": f"{name} must be an integer between {min_val} and {max_val}"}
        )
        err.status_code = 400  # type: ignore[assignment]
        return 0, err


# ---------------------------------------------------------------------------
# Traffic log routes
# ---------------------------------------------------------------------------


@infra_bp.route("/traffic", methods=["GET"])
def traffic_list() -> tuple[Any, int]:
    """Return a paginated list of recent HTTP traffic log entries.

    Query parameters:
        limit (int, optional): Max rows, default 100, max 1000.
        offset (int, optional): Row offset, default 0.
        status (int, optional): Filter by exact HTTP status code.

    Returns:
        JSON with ``status``, ``data.entries``, ``data.total``,
        ``data.limit``, ``data.offset``.
    """
    limit, err = _parse_int_param("limit", 100, 1, 1000)
    if err is not None:
        return err, 400
    offset, err = _parse_int_param("offset", 0, 0, 10_000_000)
    if err is not None:
        return err, 400

    status_filter: int | None = None
    if "status" in request.args:
        try:
            status_filter = int(request.args["status"])
        except ValueError:
            return jsonify({"status": "error", "message": "status must be an integer"}), 400

    tl = _get_traffic_logger()
    entries = tl.recent(limit=limit, offset=offset, status_filter=status_filter)
    total = tl.count()

    return jsonify(
        {
            "status": "success",
            "data": {
                "entries": entries,
                "total": total,
                "limit": limit,
                "offset": offset,
            },
        }
    ), 200


@infra_bp.route("/traffic/stats", methods=["GET"])
def traffic_stats() -> tuple[Any, int]:
    """Return aggregate traffic statistics.

    Returns:
        JSON with ``status`` and ``data`` containing ``total_requests``,
        ``error_rate``, ``avg_duration_ms``, ``p95_duration_ms``,
        ``top_paths``.
    """
    tl = _get_traffic_logger()
    stats = tl.stats()
    return jsonify({"status": "success", "data": stats}), 200


@infra_bp.route("/traffic/export", methods=["GET"])
def traffic_export() -> Any:
    """Download traffic log as a CSV file.

    Returns:
        CSV response with ``Content-Disposition: attachment`` header.
    """
    from flask import Response  # noqa: PLC0415

    tl = _get_traffic_logger()
    csv_data = tl.export_csv()

    from datetime import datetime  # noqa: PLC0415

    filename = f"traffic_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# Latency monitor routes
# ---------------------------------------------------------------------------


@infra_bp.route("/latency/stats", methods=["GET"])
def latency_stats() -> tuple[Any, int]:
    """Return per-broker latency percentile statistics.

    Query parameters:
        window_minutes (int, optional): Lookback window, default 60.

    Returns:
        JSON with ``status`` and ``data`` dict mapping broker names to
        their ``{p50, p95, p99, mean, count}`` stats.
    """
    window, err = _parse_int_param("window_minutes", 60, 1, 10080)
    if err is not None:
        return err, 400

    lm = _get_latency_monitor()
    stats = lm.percentiles_by_broker(window_minutes=window)
    return jsonify({"status": "success", "data": stats}), 200


@infra_bp.route("/latency/histogram", methods=["GET"])
def latency_histogram() -> tuple[Any, int]:
    """Return a latency histogram for a single broker.

    Query parameters:
        broker (str, required): Broker identifier.
        bins (int, optional): Number of histogram bins, default 20.
        window_minutes (int, optional): Lookback window, default 60.

    Returns:
        JSON with ``status`` and ``data`` list of
        ``{bucket_start, bucket_end, count}`` dicts.
    """
    broker: str | None = request.args.get("broker")
    if not broker:
        return jsonify({"status": "error", "message": "broker query parameter is required"}), 400

    bins, err = _parse_int_param("bins", 20, 2, 100)
    if err is not None:
        return err, 400
    window, err = _parse_int_param("window_minutes", 60, 1, 10080)
    if err is not None:
        return err, 400

    lm = _get_latency_monitor()
    buckets = lm.histogram(broker=broker, bins=bins, window_minutes=window)
    return jsonify({"status": "success", "data": buckets}), 200


@infra_bp.route("/latency/slow", methods=["GET"])
def latency_slow() -> tuple[Any, int]:
    """Return the top-N slowest recent order records.

    Query parameters:
        limit (int, optional): Number of records, default 10, max 200.

    Returns:
        JSON with ``status`` and ``data`` list.
    """
    limit, err = _parse_int_param("limit", 10, 1, 200)
    if err is not None:
        return err, 400

    lm = _get_latency_monitor()
    records = lm.slowest_recent(limit=limit)
    return jsonify({"status": "success", "data": records}), 200


# ---------------------------------------------------------------------------
# API Analyser routes
# ---------------------------------------------------------------------------


@infra_bp.route("/analyzer/calls", methods=["GET"])
def analyzer_calls() -> tuple[Any, int]:
    """Return a paginated list of API call log entries.

    Query parameters:
        route (str, optional): Route prefix filter.
        limit (int, optional): Max rows, default 100, max 1000.
        offset (int, optional): Row offset, default 0.

    Returns:
        JSON with ``status``, ``data.calls``, ``data.total``,
        ``data.limit``, ``data.offset``.
    """
    route_filter: str | None = request.args.get("route") or None

    limit, err = _parse_int_param("limit", 100, 1, 1000)
    if err is not None:
        return err, 400
    offset, err = _parse_int_param("offset", 0, 0, 10_000_000)
    if err is not None:
        return err, 400

    az = _get_api_analyzer()
    calls = az.recent(route_filter=route_filter, limit=limit, offset=offset)
    total = az.count(route_filter=route_filter)

    return jsonify(
        {
            "status": "success",
            "data": {
                "calls": calls,
                "total": total,
                "limit": limit,
                "offset": offset,
            },
        }
    ), 200


@infra_bp.route("/analyzer/<call_id>/replay", methods=["GET"])
def analyzer_replay(call_id: str) -> tuple[Any, int]:
    """Return the full request and response for a single API call.

    Args:
        call_id: The ``call_id`` of the call to retrieve (URL segment).

    Returns:
        JSON with ``status`` and ``data`` dict, or 404 if not found.
    """
    if not call_id:
        return jsonify({"status": "error", "message": "call_id is required"}), 400

    az = _get_api_analyzer()
    record = az.replay(call_id=call_id)

    if not record:
        return jsonify({"status": "error", "message": f"Call ID '{call_id}' not found"}), 404

    return jsonify({"status": "success", "data": record}), 200
