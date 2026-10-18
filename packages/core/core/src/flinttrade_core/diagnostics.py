"""Compose passive diagnostic producers with the existing health/log owners.

Operational incidents are app-owned durable evidence, not the trading audit.
Nothing here probes external targets, restarts services or infers a root cause.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from flask import Flask, g, request

from flinttrade_core.log_stream import install_log_capture
from flinttrade_core.monitoring import HealthAggregator

_logger = logging.getLogger("flinttrade.diagnostics")


def install_diagnostics(app: Flask) -> None:
    """Install actual request/log producers once for a mounted Flask app."""
    if app.extensions.get("flinttrade.diagnostics"):
        return
    app.extensions["flinttrade.diagnostics"] = True
    install_log_capture()
    _logger.setLevel(logging.INFO)
    app.config.setdefault("LOG_STREAM_SHUTDOWN_EVENT", threading.Event())

    @app.before_request
    def diagnostic_start() -> None:
        g.diagnostic_started = time.perf_counter()
        # Do not trust client headers as correlation IDs or record URLs/bodies.
        g.diagnostic_request_id = str(uuid.uuid4()).replace("-", ".")

    @app.after_request
    def diagnostic_complete(response):
        started = getattr(g, "diagnostic_started", None)
        if started is not None:
            request_id = g.diagnostic_request_id
            _logger.info("HTTP request completed", extra={
                "request_id": request_id, "operation": request.endpoint or "unmatched_route",
                "scope": "core_process", "measurement": "core_http_request_duration",
                "duration_ms": (time.perf_counter() - started) * 1000,
                "status_code": response.status_code,
                "outcome": "http_error" if response.status_code >= 400 else "http_response",
            })
            response.headers["X-Diagnostic-Request-ID"] = request_id
            owner = app.config.get("SYSTEM_INCIDENTS")
            critical = getattr(g, "diagnostic_critical", False)
            if owner is not None and (response.status_code >= 400 or critical) and getattr(g, "_runtime_request_admission", None):
                try:
                    owner.observe_http(request_id, response.status_code, (time.perf_counter() - started) * 1000,
                                       critical=critical, operation=request.endpoint or "unmatched_route")
                except Exception:
                    # Preserve the original response and expose storage failure,
                    # never acknowledge persistence that did not happen.
                    response.headers["X-Diagnostic-Persistence"] = "unavailable"
        return response


def diagnostics_snapshot(app: Flask, aggregator: HealthAggregator) -> dict[str, Any]:
    """Read native collectors and actual acquisition counts, preserving gaps."""
    observed = datetime.now(UTC).isoformat()
    resources = aggregator.get_health(registry=app.config.get("REGISTRY"),
                                      duckdb_paths=app.config.get("DIAGNOSTIC_DUCKDB_PATHS"))
    acquisition = app.config.get("DATA_ACQUISITION_OWNER")
    if acquisition is None:
        feeds = {"status": "unavailable", "reason": "owner_not_bound", "scope": "core_process"}
    else:
        try:
            feeds = acquisition.diagnostics()
        except Exception:
            feeds = {"status": "unavailable", "reason": "collection_failed", "scope": "core_process"}
    owner = app.config.get("SYSTEM_INCIDENTS")
    operational = {"status": "unavailable", "durable": False, "reason": "owner_not_bound"}
    if owner is not None:
        try:
            operational = owner.snapshot()
        except Exception:
            operational = {"status": "unavailable", "durable": True, "reason": "incident_storage_unavailable",
                           "retention": "until_manual_deletion"}
    models = {"status": "unmeasured", "capacity": None, "reason": "usage_owner_not_bound"}
    dispatcher = app.config.get("SERVICE_TASK_DISPATCHER")
    if dispatcher is not None:
        try:
            models = dispatcher.ledger.diagnostic_observation()
        except Exception:
            models = {"status": "unavailable", "capacity": None, "reason": "usage_observation_failed"}
    jobs = {"status": "unmeasured", "active": None, "coverage": "registered_collectors_only", "collectors": {}}
    manager = app.config.get("HISTORIFY_JOB_MANAGER")
    if manager is not None:
        try:
            jobs["collectors"]["historical_downloads"] = manager.diagnostic_observation()
            jobs["status"] = "partial"
        except Exception:
            jobs["collectors"]["historical_downloads"] = {"status": "unavailable", "active": None}
    jobs["collectors"]["training"] = {"status": "unmeasured", "reason": "no_passive_runtime_collector", "active": None}
    return {
        "schema_version": 1, "observed_at": observed, "scope": "core_process", "resources": resources,
        "acquisition": feeds,
        "models": models,
        "jobs": jobs,
        "network_diagnosis": {"status": "unmeasured", "cause": None,
                              "reason": "host_byte_counters_do_not_measure_DNS_TLS_or_internet"},
        "operational_events": operational,
        "recovery": {"automatic": "bounded_existing_feed_reconnect_only", "restart_performed": False},
    }
