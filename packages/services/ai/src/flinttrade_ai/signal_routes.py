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
from collections.abc import Callable, Generator, Mapping
from contextlib import nullcontext
from typing import Any

from flask import Blueprint, Flask, Response, current_app, jsonify, request
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

from .pipeline import SignalPipeline
from .signal_models import SignalConfig
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
    return jsonify(
        {
            "status": "success",
            "data": {"signals": [s.to_dict() for s in signals]},
        }
    ), 200


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
    ``Last-Event-ID``. When that cursor cannot be resumed, a named
    ``replay-loss`` control event is emitted without an SSE ID, followed by all
    retained events from the current process. Its data payload contains the
    reason, requested cursor, and available ID bounds; it is not a
    ``SignalEvent`` payload. A heartbeat comment keeps idle connections alive.
    """
    newest, retained = pipeline.get_replay_snapshot()
    cursor = newest
    replay_events = []
    if last_event_id is not None:
        requested_cursor = max(0, last_event_id)
        oldest = retained[0].event_id if retained else None
        replay_loss_reason: str | None = None
        if last_event_id > newest:
            replay_loss_reason = "cursor_ahead_of_process"
        elif oldest is not None and requested_cursor < oldest - 1:
            replay_loss_reason = "cursor_before_retained"

        if replay_loss_reason is not None:
            control = {
                "reason": replay_loss_reason,
                "requested_event_id": last_event_id,
                "oldest_available_event_id": oldest,
                "newest_available_event_id": newest,
            }
            yield f"event: replay-loss\ndata: {_json.dumps(control)}\n\n"
            replay_events = retained
            cursor = oldest - 1 if oldest is not None else 0
        else:
            cursor = requested_cursor
            replay_events = [signal for signal in retained if signal.event_id > cursor]

    for signal in replay_events:
        payload = _json.dumps(signal.to_dict())
        yield f"id: {signal.event_id}\ndata: {payload}\n\n"
        cursor = signal.event_id

    while True:
        newest, retained = pipeline.wait_for_replay_snapshot_after(
            cursor,
            timeout=heartbeat_interval,
        )
        events = [signal for signal in retained if signal.event_id > cursor]
        if not events:
            yield ": heartbeat\n\n"
            continue
        oldest = retained[0].event_id
        if oldest > cursor + 1:
            control = {
                "reason": "cursor_before_retained",
                "requested_event_id": cursor,
                "oldest_available_event_id": oldest,
                "newest_available_event_id": newest,
            }
            yield f"event: replay-loss\ndata: {_json.dumps(control)}\n\n"
            events = retained
            cursor = oldest - 1
        for signal in events:
            payload = _json.dumps(signal.to_dict())
            yield f"id: {signal.event_id}\ndata: {payload}\n\n"
            cursor = signal.event_id


@signal_bp.route("/stream", methods=["GET"])
def signals_stream() -> Response:
    """SSE endpoint that streams live signals as they are generated.

    Connect with ``EventSource("/api/v1/signals/stream")``.

    Clients should listen for the named ``replay-loss`` control event. It means
    the requested cursor belongs to discarded history or an earlier process;
    retained current-process signal messages follow immediately.
    """
    pipeline = _get_pipeline()
    raw_last_event_id = request.headers.get("Last-Event-ID")
    try:
        last_event_id = int(raw_last_event_id) if raw_last_event_id is not None else None
    except ValueError:
        last_event_id = None
    stream = (
        _sse_generator(pipeline) if last_event_id is None else _sse_generator(pipeline, last_event_id=last_event_id)
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
    if not request.get_data(cache=True):
        body = {}
    else:
        try:
            body = request.get_json(silent=False)
        except (BadRequest, UnsupportedMediaType):
            return jsonify({"status": "error", "message": "request body must contain valid JSON"}), 400

    if not isinstance(body, dict):
        return jsonify({"status": "error", "message": "configuration payload must be an object"}), 400

    supported_keys = {"instruments", "indicators", "thresholds"}
    unknown_keys = set(body) - supported_keys
    if unknown_keys:
        names = ", ".join(sorted(unknown_keys))
        return jsonify({"status": "error", "message": f"unknown configuration keys: {names}"}), 400

    pipeline = _get_pipeline()
    if not body:
        return jsonify({"status": "success", "data": pipeline.get_config().to_dict()}), 200

    instruments = body.get("instruments")
    indicators = body.get("indicators")
    thresholds = body.get("thresholds")

    if "instruments" in body and not isinstance(instruments, list):
        return jsonify({"status": "error", "message": "instruments must be a list"}), 400
    if "indicators" in body and not isinstance(indicators, list):
        return jsonify({"status": "error", "message": "indicators must be a list"}), 400
    if "thresholds" in body and not isinstance(thresholds, dict):
        return jsonify({"status": "error", "message": "thresholds must be a dict"}), 400
    if instruments is not None:
        try:
            instruments = SignalConfig(instruments=instruments).instruments
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400

    lifecycle_lock = current_app.config.get("TICK_CAPTURE_LIFECYCLE_LOCK")
    lifecycle_context: Any = lifecycle_lock if hasattr(lifecycle_lock, "__enter__") else nullcontext()
    with lifecycle_context:
        recorder = current_app.config.get("TICK_RECORDER")
        update_lock: Any = nullcontext()
        if recorder is not None:
            subscription_lock = getattr(recorder, "subscription_lock", None)
            get_watchlist = getattr(recorder, "get_watchlist", None)
            if subscription_lock is None or not callable(get_watchlist):
                return jsonify({"status": "error", "message": "Recorder watchlist control is unavailable."}), 503
            update_lock = subscription_lock

        with update_lock:
            if recorder is not None and instruments is not None:
                try:
                    watchlist = get_watchlist()
                    if not isinstance(watchlist, Mapping):
                        raise ValueError("watchlist must be a mapping")
                    recorder_instruments = [
                        f"{instrument['exchange']}:{instrument['symbol']}"
                        for mode_instruments in watchlist.values()
                        for instrument in mode_instruments
                    ]
                    recorder_identities = set(SignalConfig(instruments=recorder_instruments).instruments)
                except (KeyError, TypeError, ValueError):
                    return jsonify({"status": "error", "message": "Recorder watchlist snapshot is invalid."}), 503

                if set(instruments) != recorder_identities:
                    return jsonify(
                        {
                            "status": "error",
                            "message": (
                                "Signal instruments must match the active tick recorder watchlist; "
                                "update /api/v1/data/ticks/watchlist instead."
                            ),
                        }
                    ), 409

            try:
                config = pipeline.update_config(
                    instruments=instruments,
                    indicators=indicators,
                    thresholds=thresholds,
                )
            except (TypeError, ValueError) as exc:
                return jsonify({"status": "error", "message": str(exc)}), 400
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
    return jsonify(
        {
            "status": "success",
            "data": pipeline.get_config().to_dict(),
        }
    ), 200
