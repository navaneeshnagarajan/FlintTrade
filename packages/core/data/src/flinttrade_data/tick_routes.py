"""Tick capture Flask endpoints — status, recorded-tick queries, watchlist.

Registered as a Blueprint in ``create_flask_app()`` (flinttrade_core app.py).
The recorder itself is opt-in (``FLINTTRADE_TICK_CAPTURE``) and created at
boot; these routes surface it so the terminal can show capture status, browse
what has been recorded, and manage the capture watchlist at runtime.

Endpoints
---------
GET  /api/v1/data/ticks/status     — capture status (enabled, running, count, watchlist).
GET  /api/v1/data/ticks            — query recorded ticks by symbol/exchange/date.
POST /api/v1/data/ticks/watchlist  — add/remove capture symbols (applies on
                                     the recorder's next WebSocket reconnect).

The recorder, its StorageManager and the shared storage lock are placed on the
Flask app config (``TICK_RECORDER``, ``TICK_STORAGE``, ``TICK_STORAGE_LOCK``)
by the application factory when capture is enabled; with capture disabled the
status endpoint reports ``enabled: false`` and the others return 409 — an
honest "not recording" rather than empty-success.
"""

from __future__ import annotations

import logging
from contextlib import nullcontext
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from .tick_recorder import _canonical_instrument

logger = logging.getLogger("flinttrade.data.tick_routes")

ticks_bp = Blueprint("ticks", __name__, url_prefix="/api/v1/data/ticks")

# Query guardrails — a day of index quote ticks can run to hundreds of
# thousands of rows; the API caps what one call may return.
_DEFAULT_LIMIT = 500
_MAX_LIMIT = 5000


def _recorder() -> Any | None:
    return current_app.config.get("TICK_RECORDER")


def _storage() -> tuple[Any | None, Any | None]:
    return (
        current_app.config.get("TICK_STORAGE"),
        current_app.config.get("TICK_STORAGE_LOCK"),
    )


@ticks_bp.route("/status", methods=["GET"])
def tick_status() -> Any:
    """Report tick-capture status.

    Returns:
        JSON with ``enabled`` (recorder wired at boot), ``running`` (WS loop
        active), ``tick_count`` (recorded this session), and the capture
        ``watchlist`` by mode.
    """
    recorder = _recorder()
    if recorder is None:
        enabled = bool(current_app.config.get("TICK_CAPTURE_ENABLED", False))
        data: dict[str, Any] = {
            "enabled": enabled,
            "running": False,
            "connected": False,
            "tick_count": 0,
            "persisted_tick_count": 0,
            "pending_tick_count": 0,
            "dropped_tick_count": 0,
            "watchlist": {},
        }
        last_error = str(current_app.config.get("TICK_CAPTURE_ERROR", "") or "").strip()
        if last_error:
            data["last_error"] = last_error
        elif not enabled:
            data["hint"] = (
                "Set FLINTTRADE_TICK_CAPTURE=1 (or workspace.json data.tick_capture.enabled) "
                "and restart to record ticks."
            )
        return jsonify(
            {
                "status": "success",
                "data": data,
            }
        )

    snapshot = recorder.status_snapshot()
    recorder_error = str(snapshot.get("last_error", "") or "").strip()
    integration_error = str(current_app.config.get("TICK_CAPTURE_ERROR", "") or "").strip()
    last_error = "; ".join(dict.fromkeys(error for error in (integration_error, recorder_error) if error))
    data: dict[str, Any] = {
        "enabled": True,
        "running": bool(snapshot.get("running", False)),
        "connected": bool(snapshot.get("connected", False)),
        "tick_count": int(snapshot.get("tick_count", 0)),
        "persisted_tick_count": int(snapshot.get("persisted_tick_count", 0)),
        "pending_tick_count": int(snapshot.get("pending_tick_count", 0)),
        "dropped_tick_count": int(snapshot.get("dropped_tick_count", 0)),
        "watchlist": recorder.get_watchlist(),
    }
    for error_name in ("transport_error", "persistence_error"):
        error = str(snapshot.get(error_name, "") or "").strip()
        if error:
            data[error_name] = error
    if integration_error:
        data["integration_error"] = integration_error
    if last_error:
        data["last_error"] = last_error
    return jsonify(
        {
            "status": "success",
            "data": data,
        }
    )


@ticks_bp.route("", methods=["GET"])
def query_ticks() -> Any:
    """Query recorded ticks for a symbol over a date range.

    Query params:
        symbol (str, required): Instrument symbol (e.g. ``NIFTY``).
        exchange (str, required): Exchange code (e.g. ``NSE_INDEX``).
        start (str, required): Start date ``YYYY-MM-DD`` (IST).
        end (str, required): End date ``YYYY-MM-DD`` (IST, inclusive).
        limit (int, optional): Max rows (default 500, cap 5000). The MOST
            RECENT rows in the window are returned when truncating.

    Returns:
        JSON rows from the tick store, oldest first.
    """
    storage, lock = _storage()
    if storage is None:
        return jsonify(
            {
                "status": "error",
                "message": "Tick capture is not enabled — no tick store to query.",
            }
        ), 409

    symbol = str(request.args.get("symbol", "")).strip().upper()
    exchange = str(request.args.get("exchange", "")).strip().upper()
    start = str(request.args.get("start", "")).strip()
    end = str(request.args.get("end", "")).strip()
    if not (symbol and exchange and start and end):
        return jsonify(
            {
                "status": "error",
                "message": "symbol, exchange, start and end are required",
            }
        ), 400

    try:
        limit = int(request.args.get("limit", _DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = _DEFAULT_LIMIT
    limit = max(1, min(_MAX_LIMIT, limit))

    try:
        if lock is not None:
            with lock:
                rows = storage.get_ticks(symbol, exchange, start, end, limit=limit + 1)
        else:
            rows = storage.get_ticks(symbol, exchange, start, end, limit=limit + 1)
    except Exception as exc:
        logger.warning("Tick query failed for %s:%s %s..%s: %s", exchange, symbol, start, end, exc)
        return jsonify({"status": "error", "message": "Tick query failed"}), 500

    truncated = len(rows) > limit
    if truncated:
        rows = rows[-limit:]  # keep the most recent rows in the window

    # DuckDB timestamps serialise via str() — make each row JSON-safe.
    for row in rows:
        ts = row.get("ts")
        if ts is not None and not isinstance(ts, (str, int, float)):
            row["ts"] = str(ts)

    return jsonify(
        {
            "status": "success",
            "data": {
                "symbol": symbol,
                "exchange": exchange,
                "start": start,
                "end": end,
                "count": len(rows),
                "truncated": truncated,
                "ticks": rows,
            },
        }
    )


@ticks_bp.route("/watchlist", methods=["POST"])
def update_watchlist() -> Any:
    """Add or remove capture-watchlist instruments at runtime.

    Request JSON:
        action (str): ``add`` or ``remove``.
        instruments (list): ``[{"exchange": "NSE", "symbol": "RELIANCE"}, ...]``.
        mode (str, optional): ``ltp``/``quote``/``depth`` (default ``quote``).

    A successful update mutates the recorder under its shared subscription
    lock, atomically synchronises the signal allowlist, then requests an
    immediate reconnect so the subscription change can take effect.
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"status": "error", "message": "request body must be a JSON object"}), 400

    action = str(body.get("action", "")).strip().lower()
    mode = str(body.get("mode", "quote")).strip().lower()
    raw_instruments = body.get("instruments")
    if action not in ("add", "remove"):
        return jsonify(
            {
                "status": "error",
                "message": "action must be add or remove",
            }
        ), 400
    if not isinstance(raw_instruments, list) or not raw_instruments:
        return jsonify({"status": "error", "message": "instruments must be a non-empty list"}), 400

    instruments: list[dict[str, str]] = []
    for inst in raw_instruments:
        if not isinstance(inst, dict):
            return jsonify({"status": "error", "message": "each instrument must be a JSON object"}), 400
        try:
            instruments.append(_canonical_instrument(inst))
        except ValueError:
            return jsonify(
                {
                    "status": "error",
                    "message": "instrument exchange and symbol must be non-empty strings without ':'",
                }
            ), 400

    def qualified_identities(watchlist: dict[str, list[dict[str, str]]]) -> list[str]:
        return sorted(
            {
                f"{instrument['exchange']}:{instrument['symbol']}"
                for mode_instruments in watchlist.values()
                for instrument in mode_instruments
            }
        )

    lifecycle_lock = current_app.config.get("TICK_CAPTURE_LIFECYCLE_LOCK")
    lifecycle_context: Any = lifecycle_lock if hasattr(lifecycle_lock, "__enter__") else nullcontext()
    with lifecycle_context:
        recorder = _recorder()
        if recorder is None:
            return jsonify(
                {
                    "status": "error",
                    "message": "Tick capture is not enabled.",
                }
            ), 409

        subscription_lock = getattr(recorder, "subscription_lock", None)
        replace_watchlist = getattr(recorder, "replace_watchlist", None)
        if subscription_lock is None or not callable(replace_watchlist):
            return jsonify({"status": "error", "message": "Recorder watchlist control is unavailable."}), 503

        with subscription_lock:
            previous_watchlist = recorder.get_watchlist()
            if mode not in previous_watchlist:
                return jsonify(
                    {
                        "status": "error",
                        "message": "mode must be one of ltp, quote or depth",
                    }
                ), 400

            try:
                if action == "add":
                    recorder.add_symbols(instruments, mode=mode)
                else:
                    recorder.remove_symbols(instruments, mode=mode)
            except Exception as exc:  # noqa: BLE001 - restore any partial recorder mutation
                logger.warning("Recorder watchlist update failed (%s)", type(exc).__name__)
                replace_watchlist(previous_watchlist)
                return jsonify({"status": "error", "message": "Recorder watchlist update failed."}), 500

            updated_watchlist = recorder.get_watchlist()
            if updated_watchlist == previous_watchlist:
                return jsonify(
                    {
                        "status": "success",
                        "data": {
                            "watchlist": updated_watchlist,
                            "changed": False,
                            "reconnect_requested": False,
                            "applies_on": "unchanged",
                        },
                    }
                )

            signal_hub = current_app.config.get("SIGNAL_HUB")
            update_config = getattr(signal_hub, "update_config", None)
            if not callable(update_config):
                replace_watchlist(previous_watchlist)
                return jsonify(
                    {
                        "status": "error",
                        "message": "Signal hub is unavailable; watchlist was not changed.",
                    }
                ), 503

            try:
                update_config(instruments=qualified_identities(updated_watchlist))
            except Exception as exc:  # noqa: BLE001 - atomic hub update leaves its prior state intact
                logger.warning("Signal allowlist update failed (%s)", type(exc).__name__)
                replace_watchlist(previous_watchlist)
                return jsonify(
                    {
                        "status": "error",
                        "message": "Signal allowlist update failed; watchlist was not changed.",
                    }
                ), 500

            reconnect_requested = False
            request_reconnect = getattr(recorder, "request_reconnect", None)
            if callable(request_reconnect):
                try:
                    reconnect_requested = bool(request_reconnect())
                except Exception as exc:  # noqa: BLE001 - mutation succeeded; report deferred application
                    logger.warning("Recorder reconnect request failed (%s)", type(exc).__name__)

        return jsonify(
            {
                "status": "success",
                "data": {
                    "watchlist": updated_watchlist,
                    "changed": True,
                    "reconnect_requested": reconnect_requested,
                    "applies_on": "reconnect requested" if reconnect_requested else "next WebSocket reconnect",
                },
            }
        )
