"""Canonical rule-based and ML trading-signal HTTP surface.

Endpoints:
    GET  /api/v1/signals/recent    — recent signals (JSON list)
    GET  /api/v1/signals/stream    — SSE stream of live signals
    POST /api/v1/signals/configure — update pipeline configuration
    GET  /api/v1/signals/config    — current configuration
"""

from __future__ import annotations

import json as _json
import logging
from collections.abc import Callable, Generator
from typing import Any

from flask import Blueprint, Flask, Response, current_app, jsonify, request

from .pipeline import SignalPipeline
from .signal_pipeline import LiveSignalPipeline

logger = logging.getLogger("flinttrade.ai.signal_routes")

signal_bp = Blueprint("signals", __name__, url_prefix="/api/v1/signals")


def configure_signal_sources(
    app: Flask,
    openalgo_client: Any | None = None,
) -> tuple[LiveSignalPipeline, SignalPipeline | None]:
    """Install one application signal hub and, when possible, its ML producer."""
    pipeline: LiveSignalPipeline | None = app.config.get("SIGNAL_HUB")
    if pipeline is None:
        pipeline = getattr(app, "_live_signal_pipeline", None)
    if pipeline is None:
        pipeline = LiveSignalPipeline()

    app.config["SIGNAL_HUB"] = pipeline
    app._live_signal_pipeline = pipeline  # type: ignore[attr-defined]

    ml_pipeline: SignalPipeline | None = app.config.get("ML_SIGNAL_PIPELINE")
    if ml_pipeline is None and openalgo_client is not None:
        try:
            ml_pipeline = SignalPipeline(
                openalgo_client=openalgo_client,
                signal_sink=pipeline.ingest_ml_cycle,
            )
            app.config["ML_SIGNAL_PIPELINE"] = ml_pipeline
        except Exception as exc:  # noqa: BLE001 - optional ML cannot prevent app boot
            logger.warning("Scheduled ML signal source unavailable: %s", exc)
    return pipeline, ml_pipeline


def make_ml_signal_job(
    pipeline: SignalPipeline,
    market_is_open: Callable[[], bool],
) -> Callable[[], dict[str, dict[str, Any]]]:
    """Build the market-hours guard around the scheduled ML signal cycle."""

    def run() -> dict[str, dict[str, Any]]:
        if not market_is_open():
            logger.debug("Scheduled ML signal cycle skipped outside NSE market hours")
            return {}
        return pipeline.run_cycle()

    return run


def _get_pipeline() -> LiveSignalPipeline:
    """Retrieve or create the application-scoped ``LiveSignalPipeline`` singleton.

    The instance is stored on ``current_app`` to survive across requests
    without requiring a global variable.
    """
    pipeline, _ = configure_signal_sources(current_app)  # type: ignore[arg-type]
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

def _sse_generator(
    pipeline: LiveSignalPipeline,
    last_event_id: int | None = None,
    heartbeat_interval: float = 15.0,
) -> Generator[str, None, None]:
    """Yield SSE events when new signals arrive.

    Monotonic event IDs avoid the old deque-length bug once the 100-item ring
    buffer is full. Reconnecting clients can replay retained events with
    ``Last-Event-ID``. A heartbeat comment keeps idle connections alive.
    """
    newest = pipeline.latest_event_id
    cursor = newest if last_event_id is None else max(0, min(last_event_id, newest))

    while True:
        events = pipeline.wait_for_signals_after(cursor, timeout=heartbeat_interval)
        if not events:
            yield ": heartbeat\n\n"
            continue
        for signal in events:
            payload = _json.dumps(signal.to_dict())
            yield f"id: {signal.event_id}\ndata: {payload}\n\n"
            cursor = signal.event_id


@signal_bp.route("/stream", methods=["GET"])
def signals_stream() -> Response:
    """SSE endpoint that streams live signals as they are generated.

    Connect with ``EventSource("/api/v1/signals/stream")``.
    """
    pipeline = _get_pipeline()
    raw_last_event_id = request.headers.get("Last-Event-ID")
    try:
        last_event_id = int(raw_last_event_id) if raw_last_event_id is not None else None
    except ValueError:
        last_event_id = None
    stream = (
        _sse_generator(pipeline)
        if last_event_id is None
        else _sse_generator(pipeline, last_event_id=last_event_id)
    )
    return Response(
        stream,
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
