"""Health check Flask endpoints.

This is the single canonical health surface for the FlintTrade backend.
Provides a Blueprint with six routes:

- ``GET /health``         — simple status JSON (one-liner)
- ``GET /health/detail``  — full :class:`HealthReport` JSON
- ``GET /healthz``        — Kubernetes liveness probe
- ``GET /readyz``         — Kubernetes readiness probe
- ``GET /api/v1/ping``    — simple liveness check with IST timestamp
- ``GET /api/v1/health``  — aggregated subsystem health (broker, DuckDB,
  disk, memory) via :class:`HealthAggregator`

Register in ``create_flask_app()``::

    from flinttrade_core.health_routes import health_bp
    app.register_blueprint(health_bp)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from flask import Blueprint, jsonify

from .health_monitor import HealthMonitor
from .monitoring import HealthAggregator

logger = logging.getLogger("flinttrade.health_routes")

health_bp = Blueprint("health_detail", __name__)

# IST timezone offset
_IST = timezone(timedelta(hours=5, minutes=30))

# Module-level singletons — shared across all requests
_monitor = HealthMonitor()
_health_agg = HealthAggregator()


def get_health_monitor() -> HealthMonitor:
    """Return the module-level :class:`HealthMonitor` singleton.

    Tests may call this to inject mocks or verify call counts.
    """
    return _monitor


def init_health_monitor(monitor: HealthMonitor) -> None:
    """Replace the module-level singleton (for testing / DI).

    Args:
        monitor: Replacement :class:`HealthMonitor` instance.
    """
    global _monitor  # noqa: PLW0603
    _monitor = monitor


def get_health_aggregator() -> HealthAggregator:
    """Return the module-level :class:`HealthAggregator` singleton.

    Tests may call this to inject mocks or verify call counts.
    """
    return _health_agg


def init_health_aggregator(health_agg: HealthAggregator) -> None:
    """Replace the module-level :class:`HealthAggregator` (for testing / DI).

    Args:
        health_agg: Replacement :class:`HealthAggregator` instance.
    """
    global _health_agg  # noqa: PLW0603
    _health_agg = health_agg


@health_bp.route("/health", methods=["GET"])
def health_simple() -> tuple[Any, int]:
    """Simple health status endpoint.

    Runs all checks and returns a one-liner JSON.  HTTP 200 for
    ``"healthy"``, 503 for ``"degraded"`` or ``"unhealthy"``.

    Returns:
        JSON ``{"status": "healthy"|"degraded"|"unhealthy",
        "timestamp": "<ISO8601>"}``.
    """
    report = _monitor.check_all()
    http_status = 200 if report.overall_status == "healthy" else 503
    return (
        jsonify(
            {
                "status": report.overall_status,
                "timestamp": report.timestamp.isoformat(),
            }
        ),
        http_status,
    )


@health_bp.route("/health/detail", methods=["GET"])
def health_detail() -> tuple[Any, int]:
    """Detailed health report endpoint.

    Returns the full :class:`HealthReport` including per-check metrics.
    HTTP 200 for healthy, 503 for degraded/unhealthy.

    Returns:
        JSON with ``overall_status``, ``timestamp``, and ``checks``
        list — see :meth:`HealthReport.to_dict`.
    """
    report = _monitor.check_all()
    http_status = 200 if report.overall_status == "healthy" else 503
    return jsonify(report.to_dict()), http_status


@health_bp.route("/healthz", methods=["GET"])
def healthz() -> tuple[Any, int]:
    """Kubernetes liveness probe.

    Always returns 200 as long as the process is running (liveness
    checks should only fail if the process is truly broken and must be
    restarted).  No subsystem checks are run.

    Returns:
        JSON ``{"status": "ok"}``.
    """
    return jsonify({"status": "ok"}), 200


@health_bp.route("/readyz", methods=["GET"])
def readyz() -> tuple[Any, int]:
    """Kubernetes readiness probe.

    Runs a lightweight subset of health checks (memory + disk).  Returns
    200 only when both are healthy — signals the load balancer to route
    traffic here.

    Returns:
        JSON ``{"status": "ready"|"not_ready"}``.
    """
    mem_check = _monitor.check_memory()
    disk_check = _monitor.check_disk()

    if mem_check.status == "unhealthy" or disk_check.status == "unhealthy":
        return jsonify({"status": "not_ready"}), 503
    return jsonify({"status": "ready"}), 200


@health_bp.route("/api/v1/ping", methods=["GET"])
def ping() -> tuple[Any, int]:
    """Simple liveness check.

    Does not run subsystem checks — just confirms the process is alive
    and responding.  Exempt from API key authentication.

    Returns:
        JSON ``{"status": "ok", "timestamp": "<ISO8601 IST>"}``.
    """
    return (
        jsonify(
            {
                "status": "ok",
                "timestamp": datetime.now(_IST).isoformat(),
            }
        ),
        200,
    )


@health_bp.route("/api/v1/health", methods=["GET"])
def health_aggregated() -> tuple[Any, int]:
    """Return aggregated subsystem health status.

    Uses the registry stored in ``current_app.config["REGISTRY"]`` if
    available.  DuckDB paths and data directory are resolved from the
    workspace if available.

    Returns:
        JSON ``{"status": "ok"|"degraded"|"error", "broker": {...},
        "duckdb": {...}, "disk": {...}, "memory": {...}}``.
    """
    from flask import current_app  # noqa: PLC0415

    registry = current_app.config.get("REGISTRY")
    result = _health_agg.get_health(registry=registry)
    http_status = 200 if result["status"] == "ok" else 503
    return jsonify(result), http_status
