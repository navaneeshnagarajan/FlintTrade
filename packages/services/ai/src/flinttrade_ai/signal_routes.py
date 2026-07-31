"""Canonical rule-based and ML trading-signal HTTP surface.

Endpoints:
    GET  /api/v1/signals/recent    — recent signals (JSON list)
    GET  /api/v1/signals/stream    — SSE stream of live signals
    POST /api/v1/signals/configure — update pipeline configuration
    GET  /api/v1/signals/config    — current configuration
"""

from __future__ import annotations

import hmac
import json as _json
import logging
import math
import os
import threading
import time
from collections.abc import Callable, Generator, Mapping
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

from flask import Blueprint, Flask, Response, current_app, jsonify, request
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

from .pipeline import SignalPipeline
from .signal_models import SignalConfig
from .signal_pipeline import LiveSignalPipeline

logger = logging.getLogger("flinttrade.ai.signal_routes")

signal_bp = Blueprint("signals", __name__, url_prefix="/api/v1/signals")

_PASSWORD_CHANGE_IAT_SKEW_SECONDS = 2.0
StreamAuthRevalidator = Callable[[], bool]


@dataclass(frozen=True)
class StreamSessionClaims:
    """Non-secret session claims retained by an active signal stream."""

    jti: str
    issued_at: float
    expires_at: float


def _build_stream_auth_revalidator(
    claims: StreamSessionClaims,
    *,
    is_jti_revoked: Callable[[str], bool],
    password_changed_at: Callable[[], float],
    clock: Callable[[], float] = time.time,
) -> StreamAuthRevalidator:
    """Build a request-context-free JWT lifetime and revocation check."""

    def revalidate() -> bool:
        try:
            checked_at = float(clock())
            if (
                not math.isfinite(checked_at)
                or not math.isfinite(claims.issued_at)
                or not math.isfinite(claims.expires_at)
                or checked_at >= claims.expires_at
            ):
                return False
            if not claims.jti or is_jti_revoked(claims.jti):
                return False
            changed_at = float(password_changed_at())
            if not math.isfinite(changed_at):
                return False
            return not (
                changed_at > 0.0
                and claims.issued_at + _PASSWORD_CHANGE_IAT_SKEW_SECONDS < changed_at
            )
        except Exception as exc:  # noqa: BLE001 - auth-state failure closes the stream
            logger.warning(
                "Signal stream authentication revalidation failed; closing stream (%s)",
                type(exc).__name__,
            )
            return False

    return revalidate


def _request_stream_auth_revalidator() -> StreamAuthRevalidator | None:
    """Capture a verified JWT as non-secret claims before request teardown.

    API-key and loopback-authenticated streams have no JWT lifecycle to track.
    A valid session JWT is decoded once in the live request; the returned
    callback retains only its JTI/times and context-free auth-state readers.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        return lambda: False

    try:
        from flinttrade_core.auth_routes import _is_jti_revoked, decode_token

        payload = decode_token(token)
    except Exception:
        # Preserve only the configured API-key bearer path. A session can be
        # revoked between Flask admission and this capture, so treating every
        # decode failure as an API key would leave that stream open.
        expected_key = os.environ.get("FLINTTRADE_API_KEY", "") or os.environ.get(
            "OPENALGO_API_KEY", ""
        )
        if expected_key and hmac.compare_digest(token, expected_key):
            return None
        return lambda: False
    if payload.get("type") != "session":
        return lambda: False

    try:
        jti = str(payload["jti"])
        issued_at = float(payload["iat"])
        expires_at = float(payload["exp"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return lambda: False
    if not jti or not math.isfinite(issued_at) or not math.isfinite(expires_at):
        return lambda: False

    auth_service = current_app.config.get("AUTH_SERVICE")
    password_changed_at = getattr(auth_service, "get_password_changed_at", None)
    if not callable(password_changed_at):
        return lambda: False
    return _build_stream_auth_revalidator(
        StreamSessionClaims(
            jti=jti,
            issued_at=issued_at,
            expires_at=expires_at,
        ),
        is_jti_revoked=_is_jti_revoked,
        password_changed_at=password_changed_at,
    )


def _stream_auth_is_valid(auth_revalidator: StreamAuthRevalidator | None) -> bool:
    """Fail a stream closed when an injected revalidator raises."""
    if auth_revalidator is None:
        return True
    try:
        return bool(auth_revalidator())
    except Exception as exc:  # noqa: BLE001 - auth-state failure closes the stream
        logger.warning(
            "Signal stream authentication revalidation failed; closing stream (%s)",
            type(exc).__name__,
        )
        return False


def _signal_stream_shutdown_event(app: Flask) -> threading.Event:
    """Return the application-scoped event used to drain signal streams."""
    configured = app.config.get("SIGNAL_STREAM_SHUTDOWN_EVENT")
    if configured is None:
        configured = app.config.setdefault(
            "SIGNAL_STREAM_SHUTDOWN_EVENT",
            threading.Event(),
        )
    if not isinstance(configured, threading.Event):
        raise TypeError("SIGNAL_STREAM_SHUTDOWN_EVENT must be a threading.Event")
    return configured


def configure_signal_sources(
    app: Flask,
    openalgo_client: Any | None = None,
) -> tuple[LiveSignalPipeline, SignalPipeline | None]:
    """Install one application signal hub and, when possible, its ML producer."""
    _signal_stream_shutdown_event(app)
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
    if ml_pipeline is not None:
        try:
            pipeline.set_instrument_observer(ml_pipeline.update_instruments)
        except Exception as exc:  # noqa: BLE001 - an unsynchronised ML source must stay disabled
            pipeline.set_instrument_observer(None)
            app.config.pop("ML_SIGNAL_PIPELINE", None)
            ml_pipeline = None
            logger.warning("Scheduled ML signal roster unavailable: %s", exc)
    return pipeline, ml_pipeline


def make_ml_signal_job(
    pipeline: SignalPipeline,
    market_is_open: Callable[[str, str], bool],
) -> Callable[[], dict[str, dict[str, Any]]]:
    """Build a symbol-aware market-hours guard for one ML cycle."""

    def run() -> dict[str, dict[str, Any]]:
        open_instruments: set[tuple[str, str]] = set()
        for instrument in pipeline.instruments:
            exchange = str(instrument.get("exchange") or "")
            symbol = str(instrument.get("symbol") or "")
            if not exchange or not symbol:
                continue
            try:
                if market_is_open(exchange, symbol):
                    open_instruments.add((exchange, symbol))
            except Exception:  # noqa: BLE001 - an unknown calendar must fail closed
                logger.exception(
                    "Scheduled ML market-hours lookup failed for %s:%s",
                    exchange,
                    symbol,
                )
        if not open_instruments:
            logger.debug("Scheduled ML signal cycle skipped: all configured instruments are closed")
            return {}
        return pipeline.run_cycle(
            market_is_open=lambda exchange, symbol: (exchange, symbol) in open_instruments
        )

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
            "data": {
                "stream_id": pipeline.stream_id,
                "signals": [s.to_dict() for s in signals],
            },
        }
    ), 200


# --------------------------------------------------------------------------
# GET /api/v1/signals/stream  (Server-Sent Events)
# --------------------------------------------------------------------------


def _sse_generator(
    pipeline: LiveSignalPipeline,
    last_event_id: int | str | None = None,
    heartbeat_interval: float = 15.0,
    auth_revalidator: StreamAuthRevalidator | None = None,
    shutdown_event: threading.Event | None = None,
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
    if (shutdown_event is not None and shutdown_event.is_set()) or not _stream_auth_is_valid(
        auth_revalidator
    ):
        return
    newest, retained = pipeline.get_replay_snapshot()
    cursor = newest
    replay_events = []
    if last_event_id is not None:
        replay_loss_reason: str | None = None
        if isinstance(last_event_id, int):
            requested_cursor = max(0, last_event_id)
        else:
            raw_cursor = last_event_id.strip()
            stream_id, separator, raw_sequence = raw_cursor.rpartition(":")
            if not separator:
                requested_cursor = 0
                replay_loss_reason = "legacy_cursor" if raw_cursor.isdigit() else "invalid_cursor"
            else:
                try:
                    requested_cursor = max(0, int(raw_sequence))
                except ValueError:
                    requested_cursor = 0
                    replay_loss_reason = "invalid_cursor"
                else:
                    if stream_id != pipeline.stream_id:
                        replay_loss_reason = "stream_changed"
        oldest = retained[0].event_id if retained else None
        if replay_loss_reason is None and requested_cursor > newest:
            replay_loss_reason = "cursor_ahead_of_process"
        elif replay_loss_reason is None and oldest is not None and requested_cursor < oldest - 1:
            replay_loss_reason = "cursor_before_retained"

        if replay_loss_reason is not None:
            control = {
                "reason": replay_loss_reason,
                "requested_event_id": requested_cursor,
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
        if (shutdown_event is not None and shutdown_event.is_set()) or not _stream_auth_is_valid(
            auth_revalidator
        ):
            return
        payload = _json.dumps(signal.to_dict())
        yield f"id: {pipeline.sse_event_id(signal.event_id)}\ndata: {payload}\n\n"
        cursor = signal.event_id

    while True:
        if (shutdown_event is not None and shutdown_event.is_set()) or not _stream_auth_is_valid(
            auth_revalidator
        ):
            return
        newest, retained = pipeline.wait_for_replay_snapshot_after(
            cursor,
            timeout=heartbeat_interval,
            stop_requested=shutdown_event.is_set if shutdown_event is not None else None,
        )
        if (shutdown_event is not None and shutdown_event.is_set()) or not _stream_auth_is_valid(
            auth_revalidator
        ):
            return
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
            if (shutdown_event is not None and shutdown_event.is_set()) or not _stream_auth_is_valid(
                auth_revalidator
            ):
                return
            payload = _json.dumps(signal.to_dict())
            yield f"id: {pipeline.sse_event_id(signal.event_id)}\ndata: {payload}\n\n"
            cursor = signal.event_id


@signal_bp.route("/stream", methods=["GET"])
def signals_stream() -> Response | tuple[Any, int]:
    """SSE endpoint that streams live signals as they are generated.

    Connect with ``EventSource("/api/v1/signals/stream")``.

    Clients should listen for the named ``replay-loss`` control event. It means
    the requested cursor belongs to discarded history or an earlier process;
    retained current-process signal messages follow immediately.
    """
    shutdown_event = _signal_stream_shutdown_event(current_app)  # type: ignore[arg-type]
    if shutdown_event.is_set():
        return jsonify({"status": "error", "message": "Signal streaming is shutting down."}), 503

    auth_revalidator = _request_stream_auth_revalidator()
    if auth_revalidator is not None and not _stream_auth_is_valid(auth_revalidator):
        return jsonify(
            {
                "status": "error",
                "message": "Signal stream authentication is no longer valid.",
            }
        ), 401

    pipeline = _get_pipeline()
    raw_last_event_id = request.headers.get("Last-Event-ID")
    stream_kwargs: dict[str, Any] = {"shutdown_event": shutdown_event}
    if raw_last_event_id is not None:
        stream_kwargs["last_event_id"] = raw_last_event_id
    if auth_revalidator is not None:
        stream_kwargs["auth_revalidator"] = auth_revalidator
    stream = _sse_generator(pipeline, **stream_kwargs)
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
