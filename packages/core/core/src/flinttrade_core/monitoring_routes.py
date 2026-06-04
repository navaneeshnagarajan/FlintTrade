"""Monitoring Flask endpoints.

Registered as a Blueprint in ``create_flask_app()``.

The aggregated ``GET /api/v1/health`` endpoint lives in
:mod:`flinttrade_core.health_routes` — the single canonical health
surface — not here.

Endpoints
---------
GET /api/v1/traffic/stats      — traffic statistics
GET /api/v1/traffic/recent     — recent requests
GET /api/v1/latency/stats      — order latency stats
GET /api/v1/latency/recent     — recent latency records
"""
from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from .monitoring import LatencyTracker, TrafficCounter

logger = logging.getLogger("flinttrade.monitoring_routes")

monitoring_bp = Blueprint("monitoring", __name__, url_prefix="/api/v1")

# Module-level singletons
_traffic: TrafficCounter = TrafficCounter()
_latency: LatencyTracker = LatencyTracker()


def get_traffic_counter() -> TrafficCounter:
    """Return the module-level TrafficCounter singleton.

    Use this in ``after_request`` middleware to record request metrics.
    """
    return _traffic


def get_latency_tracker() -> LatencyTracker:
    """Return the module-level LatencyTracker singleton.

    Use this in order-placement code to record per-broker RTT.
    """
    return _latency


def init_monitoring_routes(
    traffic: TrafficCounter | None = None,
    latency: LatencyTracker | None = None,
) -> None:
    """Inject monitoring singletons into the blueprint.

    Args:
        traffic: Optional :class:`TrafficCounter` to inject.
        latency: Optional :class:`LatencyTracker` to inject.
    """
    global _traffic, _latency  # noqa: PLW0603
    if traffic is not None:
        _traffic = traffic
    if latency is not None:
        _latency = latency
    logger.info("Monitoring singletons injected")


# ---------------------------------------------------------------------------
# Traffic
# ---------------------------------------------------------------------------


@monitoring_bp.route("/traffic/stats", methods=["GET"])
def traffic_stats() -> tuple[Any, int]:
    """Return traffic statistics.

    Query parameters:
        minutes (int, optional): Lookback window in minutes (default 5).

    Returns:
        JSON ``{"status": "ok", "data": {...}}``.
    """
    minutes_raw = request.args.get("minutes", "5")
    try:
        minutes = int(minutes_raw)
        if minutes < 1:
            raise ValueError
    except ValueError:
        return jsonify({"status": "error", "message": "minutes must be a positive integer"}), 400

    return jsonify({"status": "success", "data": _traffic.get_stats(minutes=minutes)}), 200


@monitoring_bp.route("/traffic/recent", methods=["GET"])
def traffic_recent() -> tuple[Any, int]:
    """Return recent HTTP requests.

    Query parameters:
        n (int, optional): Number of records (default 100, max 1000).

    Returns:
        JSON ``{"status": "ok", "data": [...]}``.
    """
    n_raw = request.args.get("n", "100")
    try:
        n = min(int(n_raw), 1000)
        if n < 1:
            raise ValueError
    except ValueError:
        return jsonify({"status": "error", "message": "n must be a positive integer"}), 400

    return jsonify({"status": "success", "data": _traffic.get_recent(n=n)}), 200


# ---------------------------------------------------------------------------
# Latency
# ---------------------------------------------------------------------------


@monitoring_bp.route("/latency/stats", methods=["GET"])
def latency_stats() -> tuple[Any, int]:
    """Return order latency statistics per broker.

    Returns:
        JSON ``{"status": "ok", "data": {"BROKER": {count, avg_ms,
        p50_ms, p95_ms, p99_ms}, ...}}``.
    """
    return jsonify({"status": "success", "data": _latency.get_stats()}), 200


@monitoring_bp.route("/latency/recent", methods=["GET"])
def latency_recent() -> tuple[Any, int]:
    """Return recent order latency records.

    Query parameters:
        n (int, optional): Number of records (default 50, max 500).

    Returns:
        JSON ``{"status": "ok", "data": [...]}``.
    """
    n_raw = request.args.get("n", "50")
    try:
        n = min(int(n_raw), 500)
        if n < 1:
            raise ValueError
    except ValueError:
        return jsonify({"status": "error", "message": "n must be a positive integer"}), 400

    return jsonify({"status": "success", "data": _latency.get_recent(n=n)}), 200
