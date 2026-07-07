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
from typing import Any

from flask import Blueprint, current_app, jsonify, request

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
        return jsonify({
            "status": "success",
            "data": {
                "enabled": False,
                "running": False,
                "tick_count": 0,
                "watchlist": {},
                "hint": "Set FLINTTRADE_TICK_CAPTURE=1 (or workspace.json data.tick_capture.enabled) and restart to record ticks.",
            },
        })

    return jsonify({
        "status": "success",
        "data": {
            "enabled": True,
            "running": bool(getattr(recorder, "is_running", False)),
            "tick_count": int(getattr(recorder, "tick_count", 0)),
            "watchlist": recorder.get_watchlist(),
        },
    })


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
        return jsonify({
            "status": "error",
            "message": "Tick capture is not enabled — no tick store to query.",
        }), 409

    symbol = str(request.args.get("symbol", "")).strip().upper()
    exchange = str(request.args.get("exchange", "")).strip().upper()
    start = str(request.args.get("start", "")).strip()
    end = str(request.args.get("end", "")).strip()
    if not (symbol and exchange and start and end):
        return jsonify({
            "status": "error",
            "message": "symbol, exchange, start and end are required",
        }), 400

    try:
        limit = int(request.args.get("limit", _DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = _DEFAULT_LIMIT
    limit = max(1, min(_MAX_LIMIT, limit))

    try:
        if lock is not None:
            with lock:
                rows = storage.get_ticks(symbol, exchange, start, end)
        else:
            rows = storage.get_ticks(symbol, exchange, start, end)
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

    return jsonify({
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
    })


@ticks_bp.route("/watchlist", methods=["POST"])
def update_watchlist() -> Any:
    """Add or remove capture-watchlist instruments at runtime.

    Request JSON:
        action (str): ``add`` or ``remove``.
        instruments (list): ``[{"exchange": "NSE", "symbol": "RELIANCE"}, ...]``.
        mode (str, optional): ``ltp``/``quote``/``depth`` (default ``quote``).

    Note: the recorder subscribes at WebSocket (re)connect, so changes apply on
    the next reconnect — reported honestly in the response.
    """
    recorder = _recorder()
    if recorder is None:
        return jsonify({
            "status": "error",
            "message": "Tick capture is not enabled.",
        }), 409

    body = request.get_json(silent=True) or {}
    action = str(body.get("action", "")).strip().lower()
    mode = str(body.get("mode", "quote")).strip().lower()
    raw_instruments = body.get("instruments") or []

    instruments: list[dict[str, str]] = []
    for inst in raw_instruments:
        if not isinstance(inst, dict):
            continue
        symbol = str(inst.get("symbol", "")).strip().upper()
        exchange = str(inst.get("exchange", "")).strip().upper()
        if symbol and exchange:
            instruments.append({"exchange": exchange, "symbol": symbol})

    if action not in ("add", "remove") or not instruments:
        return jsonify({
            "status": "error",
            "message": "action must be add|remove with a non-empty instruments list",
        }), 400

    try:
        if action == "add":
            recorder.add_symbols(instruments, mode=mode)
        else:
            recorder.remove_symbols(instruments, mode=mode)
    except ValueError:
        return jsonify({
            "status": "error",
            "message": "mode must be one of ltp, quote or depth",
        }), 400

    return jsonify({
        "status": "success",
        "data": {
            "watchlist": recorder.get_watchlist(),
            "applies_on": "next WebSocket reconnect",
        },
    })
