"""Signal pipeline blueprint — live market signal endpoints.

Endpoints:
    GET  /api/v1/signals/recent    — recent signals (JSON list)
    GET  /api/v1/signals/stream    — SSE stream of live signals
    POST /api/v1/signals/configure — update pipeline configuration
    GET  /api/v1/signals/config    — current configuration
"""

from __future__ import annotations

import json as _json
import logging
import time
from typing import Any, Generator

from flask import Blueprint, Response, current_app, jsonify, request

from packages.ai.src.signal_models import SignalConfig
from packages.ai.src.signal_pipeline import LiveSignalPipeline

logger = logging.getLogger("flinttrade.ai.signal_routes")

signal_bp = Blueprint("signals", __name__, url_prefix="/api/v1/signals")


def _get_pipeline() -> LiveSignalPipeline:
    """Retrieve or create the application-scoped ``LiveSignalPipeline`` singleton.

    The instance is stored on ``current_app`` to survive across requests
    without requiring a global variable.
    """
    pipeline: LiveSignalPipeline | None = getattr(
        current_app, "_live_signal_pipeline", None
    )
    if pipeline is None:
        pipeline = LiveSignalPipeline()
        current_app._live_signal_pipeline = pipeline  # type: ignore[attr-defined]
        logger.info("Live signal pipeline initialised with default config")
    return pipeline


# --------------------------------------------------------------------------
# GET /api/v1/signals/recent
# --------------------------------------------------------------------------

@signal_bp.route("/recent", methods=["GET"])
def signals_recent() -> tuple[Any, int]:
    """Return recent signals as a JSON list, newest first.

    Query params:
        limit (int, optional): Max signals to return (default 20, max 100).

    Returns:
        ``{ "status": "success", "data": { "signals": [...] } }``
    """
    try:
        limit_str = request.args.get("limit", "20")
        limit = min(max(int(limit_str), 1), 100)
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "limit must be an integer"}), 400

    pipeline = _get_pipeline()
    signals = pipeline.get_recent_signals(limit=limit)
    return jsonify({
        "status": "success",
        "data": {"signals": [s.to_dict() for s in signals]},
    }), 200


# --------------------------------------------------------------------------
# GET /api/v1/signals/stream  (Server-Sent Events)
# --------------------------------------------------------------------------

def _sse_generator(pipeline: LiveSignalPipeline) -> Generator[str, None, None]:
    """Yield SSE events when new signals arrive.

    Polls the pipeline's signal deque every second and sends any new signals
    that were not yet emitted.  A heartbeat comment is sent every 15 s to
    keep the connection alive through proxies.
    """
    last_sent_count = len(pipeline.signals)
    heartbeat_interval = 15
    last_heartbeat = time.monotonic()

    while True:
        current_count = len(pipeline.signals)
        if current_count > last_sent_count:
            # New signals have been prepended (deque grows from the left)
            new_count = current_count - last_sent_count
            new_signals = list(pipeline.signals)[:new_count]
            for sig in reversed(new_signals):  # oldest new first
                payload = _json.dumps(sig.to_dict())
                yield f"data: {payload}\n\n"
            last_sent_count = current_count
        elif current_count < last_sent_count:
            # Pipeline was reset (config update) — re-sync
            last_sent_count = current_count

        # Heartbeat
        now = time.monotonic()
        if now - last_heartbeat >= heartbeat_interval:
            yield ": heartbeat\n\n"
            last_heartbeat = now

        time.sleep(1)


@signal_bp.route("/stream", methods=["GET"])
def signals_stream() -> Response:
    """SSE endpoint that streams live signals as they are generated.

    Connect with ``EventSource("/api/v1/signals/stream")``.
    """
    pipeline = _get_pipeline()
    return Response(
        _sse_generator(pipeline),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# --------------------------------------------------------------------------
# POST /api/v1/signals/configure
# --------------------------------------------------------------------------

@signal_bp.route("/configure", methods=["POST"])
def signals_configure() -> tuple[Any, int]:
    """Update signal pipeline configuration.

    Request JSON (all fields optional):
        instruments (list[str]): Symbols to track.
        indicators  (list[dict]): Indicator configs.
        thresholds  (dict[str, float]): Threshold values.

    Returns:
        ``{ "status": "success", "data": <updated config> }``
    """
    body = request.get_json(silent=True) or {}

    instruments = body.get("instruments")
    indicators = body.get("indicators")
    thresholds = body.get("thresholds")

    if instruments is not None and not isinstance(instruments, list):
        return jsonify({"status": "error", "message": "instruments must be a list"}), 400
    if indicators is not None and not isinstance(indicators, list):
        return jsonify({"status": "error", "message": "indicators must be a list"}), 400
    if thresholds is not None and not isinstance(thresholds, dict):
        return jsonify({"status": "error", "message": "thresholds must be a dict"}), 400

    pipeline = _get_pipeline()
    config = pipeline.update_config(
        instruments=instruments,
        indicators=indicators,
        thresholds=thresholds,
    )
    return jsonify({"status": "success", "data": config.to_dict()}), 200


# --------------------------------------------------------------------------
# GET /api/v1/signals/config
# --------------------------------------------------------------------------

@signal_bp.route("/config", methods=["GET"])
def signals_config() -> tuple[Any, int]:
    """Return current signal pipeline configuration.

    Returns:
        ``{ "status": "success", "data": <config dict> }``
    """
    pipeline = _get_pipeline()
    return jsonify({
        "status": "success",
        "data": pipeline.get_config().to_dict(),
    }), 200
