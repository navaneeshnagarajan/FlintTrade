"""Health check Flask endpoints.

This is the single canonical health surface for the FlintTrade backend.
Provides a Blueprint with these routes:

- ``GET /health``         — simple status JSON (one-liner)
- ``GET /health/detail``  — full :class:`HealthReport` JSON
- ``GET /healthz``        — Kubernetes liveness probe
- ``GET /readyz``         — Kubernetes readiness probe
- ``GET /api/v1/ping``    — simple liveness check with IST timestamp
- ``GET /api/v1/versions`` — authenticated, read-only About metadata
- ``GET /api/v1/versions/ollama`` — bounded, observational Ollama version probe
- ``POST /api/v1/laya/start`` — start or restart the managed Laya sidecar
- ``GET /api/v1/health``  — aggregated subsystem health (broker, DuckDB,
  disk, memory) via :class:`HealthAggregator`

Register in ``create_flask_app()``::

    from flinttrade_core.health_routes import health_bp
    app.register_blueprint(health_bp)
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from flask import Blueprint, current_app, jsonify

from flinttrade_core.version_inventory import build_version_inventory

from .health_monitor import HealthMonitor
from .monitoring import HealthAggregator

logger = logging.getLogger("flinttrade.health_routes")

health_bp = Blueprint("health_detail", __name__)

# IST timezone offset
_IST = timezone(timedelta(hours=5, minutes=30))

# Module-level singletons — shared across all requests, built on first use.
#
# These are deliberately NOT constructed at import time. `HealthMonitor()`
# resolves its disk-probe directory through
# `flinttrade_core.workspace.workspace_dir()` in its constructor, and this
# module is imported while `create_flask_app()` is still wiring itself up.
# Constructing at import time would freeze whatever workspace was active
# then — the wrong directory under Gunicorn preload+fork, and the wrong
# directory for any test that sets `FLINTTRADE_WORKSPACE_DIR` after import.
_monitor: HealthMonitor | None = None
_health_agg: HealthAggregator | None = None

# Guards first construction: eight Flask worker threads can race the first
# request, and building two monitors would waste the psutil baseline.
_singleton_lock = threading.Lock()


def get_health_monitor() -> HealthMonitor:
    """Return the module-level :class:`HealthMonitor`, building it on first use.

    Tests may call this to inject mocks or verify call counts.

    Returns:
        The shared :class:`HealthMonitor` instance.
    """
    global _monitor  # noqa: PLW0603
    if _monitor is None:
        with _singleton_lock:
            if _monitor is None:
                _monitor = HealthMonitor()
    return _monitor


def init_health_monitor(monitor: HealthMonitor) -> None:
    """Replace the module-level singleton (for testing / DI).

    Args:
        monitor: Replacement :class:`HealthMonitor` instance.
    """
    global _monitor  # noqa: PLW0603
    with _singleton_lock:
        _monitor = monitor


def get_health_aggregator() -> HealthAggregator:
    """Return the module-level :class:`HealthAggregator`, building it on first use.

    Tests may call this to inject mocks or verify call counts.

    Returns:
        The shared :class:`HealthAggregator` instance.
    """
    global _health_agg  # noqa: PLW0603
    if _health_agg is None:
        with _singleton_lock:
            if _health_agg is None:
                _health_agg = HealthAggregator()
    return _health_agg


def init_health_aggregator(health_agg: HealthAggregator) -> None:
    """Replace the module-level :class:`HealthAggregator` (for testing / DI).

    Args:
        health_agg: Replacement :class:`HealthAggregator` instance.
    """
    global _health_agg  # noqa: PLW0603
    with _singleton_lock:
        _health_agg = health_agg


def _reconcile_laya_for_desk() -> None:
    """Apply a command-line stop or start before the desk reads the gate.

    This is the same watch the order gate runs. The chip's ping and an
    order then publish one status. An Ollama backend publishes that runtime
    instead of the sidecar watch.
    """
    try:
        from flinttrade_engine.laya_ollama import laya_backend, publish_ollama_gate_status  # noqa: PLC0415

        if laya_backend() != "sidecar":
            publish_ollama_gate_status()
            return
        from flinttrade_core.laya_runtime import process_runtime  # noqa: PLC0415

        runtime = process_runtime()
        reconcile = getattr(runtime, "reconcile_watched_state", None)
        if callable(reconcile):
            reconcile()
    except Exception:
        logger.warning("Laya desk reconcile failed", exc_info=True)


def _refresh_laya_status() -> None:
    """Record sidecar health. A missing sidecar leaves the stored status alone."""
    try:
        from flinttrade_core.laya_runtime import refresh_process_laya_status  # noqa: PLC0415

        refresh_process_laya_status()
    except Exception:
        logger.warning("Laya status probe failed", exc_info=True)
        try:
            from flinttrade_engine.laya import DecisionStatus, process_laya  # noqa: PLC0415

            process_laya().apply_runtime_status(DecisionStatus.DOWN, live_qualified=False)
        except Exception:
            logger.warning("Laya status could not be recorded", exc_info=True)


def reset_health_singletons_for_tests() -> None:
    """Drop both cached singletons so the next call rebuilds them.

    Tests that change ``FLINTTRADE_WORKSPACE_DIR`` need this: the monitor
    caches its disk-probe directory for its lifetime, so a stale instance
    would keep probing the previous workspace.
    """
    global _monitor, _health_agg  # noqa: PLW0603
    with _singleton_lock:
        _monitor = None
        _health_agg = None


@health_bp.route("/health", methods=["GET"])
def health_simple() -> tuple[Any, int]:
    """Simple health status endpoint.

    Runs all checks and returns a one-liner JSON.  HTTP 200 for
    ``"healthy"``, 503 for ``"degraded"`` or ``"unhealthy"``.

    Returns:
        JSON ``{"status": "healthy"|"degraded"|"unhealthy",
        "timestamp": "<ISO8601>"}``.

    When a Laya sidecar is registered, this probe records Ready, Degraded,
    or Down from that sidecar before the process report is returned. Ping
    publishes the stored Live-facing status and does not invent Ready.
    """
    _refresh_laya_status()
    report = get_health_monitor().check_all()
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
    report = get_health_monitor().check_all()
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
    monitor = get_health_monitor()
    mem_check = monitor.check_memory()
    disk_check = monitor.check_disk()

    if mem_check.status == "unhealthy" or disk_check.status == "unhealthy":
        return jsonify({"status": "not_ready"}), 503
    return jsonify({"status": "ready"}), 200


@health_bp.route("/api/v1/versions", methods=["GET"])
def versions() -> tuple[Any, int]:
    """Return allowlisted version metadata under the default session guard."""
    response = jsonify(build_version_inventory())
    response.headers["Cache-Control"] = "no-store"
    return response, 200


@health_bp.route("/api/v1/versions/ollama", methods=["GET"])
def ollama_versions() -> tuple[Any, int]:
    """Read a managed loopback version without invoking lifecycle status."""
    payload: dict[str, str | None] = {"configured": None, "reported": None, "status": "unavailable"}
    runtime = current_app.config.get("OLLAMA_RUNTIME")
    if runtime is not None:
        from flinttrade_core.ollama_runtime import OllamaRuntime

        if isinstance(runtime, OllamaRuntime):
            payload = OllamaRuntime.version_snapshot(runtime)
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response, 200


@health_bp.route("/api/v1/ping", methods=["GET"])
def ping() -> tuple[Any, int]:
    """Simple liveness check.

    Does not run subsystem checks — just confirms the process is alive
    and responding.  Exempt from API key authentication.

    Returns:
        JSON with ``laya`` (Live-facing), ``laya_practice`` (sidecar),
        ``laya_live_qualified``, ``laya_reason``, ``laya_port``, and, while a
        model download is in progress, ``laya_download_bytes`` and
        ``laya_download_total``. ``laya`` starts Down. A ping reconciles the
        watched pid, key, and runtime record the same way an order does, then
        returns that stored status. It does not invent Ready when those files
        have not changed, and it does not probe the port on its own.
    """
    from flinttrade_engine.laya import process_laya  # noqa: PLC0415

    _reconcile_laya_for_desk()
    engine = process_laya()
    practice, live, qualified = engine.desk_heartbeat()
    reason, port = engine.runtime_reason()
    progress = engine.download_progress()
    body = {
        "status": "ok",
        "timestamp": datetime.now(_IST).isoformat(),
        "laya": live.value,
        "laya_practice": practice.value,
        "laya_live_qualified": qualified,
        "laya_reason": reason,
        "laya_port": port,
        "laya_download_bytes": None if progress is None else progress[0],
        "laya_download_total": None if progress is None else progress[1],
    }
    from flinttrade_engine.laya_ollama import laya_backend  # noqa: PLC0415

    if laya_backend() == "ollama":
        body["laya_checking"] = engine.gate_checking()
        body["laya_route"] = "ollama"
        body["laya_managed"] = _ollama_install_is_managed()
    return jsonify(body), 200


def _ollama_install_is_managed() -> bool:
    """True when this process can start a FlintTrade-managed Ollama install."""
    try:
        from flask import current_app, has_app_context  # noqa: PLC0415

        if not has_app_context():
            return False
        runtime = current_app.config.get("OLLAMA_RUNTIME")
        present = getattr(runtime, "install_present", None)
        return bool(callable(present) and present())
    except Exception:  # noqa: BLE001 - an unreadable install is unmanaged
        return False


def _start_managed_ollama_for_gate() -> None:
    """Start the FlintTrade-managed Ollama install. Unmanaged installs raise."""
    from flask import current_app, has_app_context  # noqa: PLC0415

    if not has_app_context():
        raise RuntimeError("managed Ollama is unavailable")
    runtime = current_app.config.get("OLLAMA_RUNTIME")
    present = getattr(runtime, "install_present", None)
    if runtime is None or not callable(present) or not present():
        raise RuntimeError("managed Ollama is not installed")
    runtime.start_async()


@health_bp.route("/api/v1/laya/start", methods=["POST"])
def start_laya() -> tuple[Any, int]:
    """Start the runtime behind the current Laya route.

    The sidecar route starts the managed sidecar. The Ollama route starts a
    FlintTrade-managed Ollama install and leaves an unmanaged Ollama alone.
    Operator session only. A failure is a generic 503. The response does not
    include paths or the API key.
    """
    from flinttrade_core.auth_routes import require_operator_session  # noqa: PLC0415
    from flinttrade_engine.laya_ollama import laya_backend  # noqa: PLC0415

    denied = require_operator_session()
    if denied is not None:
        return denied
    backend = laya_backend()
    if backend == "closed":
        return jsonify({"status": "error", "message": "Laya could not be started."}), 503
    ollama = backend == "ollama"
    try:
        if ollama:
            _start_managed_ollama_for_gate()
        else:
            from flinttrade_core.laya_runtime import start_managed_sidecar  # noqa: PLC0415

            start_managed_sidecar()
    except Exception:
        if ollama:
            logger.warning("Managed Ollama could not be started", exc_info=True)
        else:
            logger.warning("Laya sidecar could not be started", exc_info=True)
        return jsonify({"status": "error", "message": "Laya could not be started."}), 503
    return jsonify({"status": "ok"}), 200


@health_bp.route("/api/v1/health", methods=["GET"])
def health_aggregated() -> tuple[Any, int]:
    """Return aggregated subsystem health status.

    Uses the registry stored in ``current_app.config["REGISTRY"]`` if
    available.  DuckDB paths and data directory are resolved from the
    workspace if available.

    Returns:
        JSON ``{"status": "ok"|"degraded"|"error", "broker": {...},
        "duckdb": {...}, "disk": {...}, "memory": {...}}`` plus ``cpu``,
        ``gpu``, and ``network`` when the install host can report them.
        Host memory uses ``used_mb`` / ``total_mb`` / ``used_pct``. Process
        RSS stays under ``memory.process`` and is not host RAM.
    """
    from flask import current_app  # noqa: PLC0415

    registry = current_app.config.get("REGISTRY")
    result = get_health_aggregator().get_health(registry=registry)
    http_status = 200 if result["status"] == "ok" else 503
    return jsonify(result), http_status
