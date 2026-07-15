"""ExpiryTracker Flask endpoints — historical expired option chains.

Registered as a Blueprint in ``create_flask_app()``.

Endpoints
---------
GET /api/v1/historical/expiries/<symbol>        — list available expired expiries
GET /api/v1/historical/chain/<symbol>/<expiry>  — get historical option chain
POST /api/v1/historical/chain/<symbol>/<expiry>/capture
    — capture/populate an option-chain snapshot
"""
from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from .expiry_tracker import ExpiryTracker, normalise_expiry

logger = logging.getLogger("flinttrade.historical.expiry_tracker_routes")

try:
    from flinttrade_core.openalgo_client import get_openalgo_client
except Exception:  # pragma: no cover - optional when package is imported standalone
    get_openalgo_client = None  # type: ignore[assignment,misc]

expiry_tracker_bp = Blueprint("expiry_tracker", __name__, url_prefix="/api/v1")

# Module-level singleton — replaced by ``init_expiry_tracker_routes`` when injected.
_tracker: ExpiryTracker | None = None


def _get_tracker() -> ExpiryTracker:
    """Return the module-level tracker singleton, creating it lazily.

    The tracker receives the ``get_openalgo_client`` provider so each capture
    resolves the app's authoritative shared client. Hot reload normally
    reconfigures that object in place; provider resolution also keeps this
    integration correct if startup fallback ever replaces the client object.
    """
    global _tracker  # noqa: PLW0603
    if _tracker is None:
        _tracker = ExpiryTracker(client=get_openalgo_client)
    return _tracker


def init_expiry_tracker_routes(tracker: ExpiryTracker) -> None:
    """Inject an ExpiryTracker instance into the blueprint's singleton.

    Args:
        tracker: The :class:`ExpiryTracker` instance to use.
    """
    global _tracker  # noqa: PLW0603
    _tracker = tracker
    logger.info("ExpiryTracker singleton injected into expiry_tracker_routes")


@expiry_tracker_bp.route("/historical/expiries/<symbol>", methods=["GET"])
def list_expiries(symbol: str) -> tuple[Any, int]:
    """List all expiry dates with stored snapshots for a symbol.

    Path parameters:
        symbol (str): Underlying symbol (e.g. ``NIFTY``).

    Query parameters:
        exchange (str, optional): Exchange segment (default ``NFO``).

    Returns:
        JSON ``{"status": "success", "data": {"symbol": "...", "expiries": [...]}}``
    """
    exchange = request.args.get("exchange", "NFO")
    tracker = _get_tracker()
    expiries = tracker.list_expiries(symbol.upper(), exchange)

    return jsonify({
        "status": "success",
        "data": {
            "symbol": symbol.upper(),
            "exchange": exchange,
            "expiries": expiries,
        },
    }), 200


@expiry_tracker_bp.route("/historical/chain/<symbol>/<expiry>", methods=["GET"])
def get_historical_chain(symbol: str, expiry: str) -> tuple[Any, int]:
    """Get a stored historical option chain for a symbol and expiry.

    Path parameters:
        symbol (str): Underlying symbol (e.g. ``NIFTY``).
        expiry (str): Expiry date string (e.g. ``260326``).

    Query parameters:
        exchange (str, optional): Exchange segment (default ``NFO``).

    Returns:
        JSON ``{"status": "success", "data": {"symbol": "...", "expiry": "...", "chain": [...]}}``
        where each chain entry has keys: strike, option_type, oi, volume, ltp, iv.
    """
    exchange = request.args.get("exchange", "NFO")
    tracker = _get_tracker()
    chain = tracker.get_historical_chain(symbol.upper(), expiry, exchange)
    canonical_expiry = normalise_expiry(expiry)

    return jsonify({
        "status": "success",
        "data": {
            "symbol": symbol.upper(),
            "expiry": canonical_expiry,
            "exchange": exchange,
            "chain": chain,
        },
    }), 200


@expiry_tracker_bp.route("/historical/chain/<symbol>/<expiry>/capture", methods=["POST"])
def capture_historical_chain(symbol: str, expiry: str) -> tuple[Any, int]:
    """Capture and store the current option chain snapshot for an expiry.

    Path parameters:
        symbol (str): Underlying symbol (e.g. ``NIFTY``).
        expiry (str): Expiry date string (e.g. ``260326`` or ``2026-03-26``).

    Query/body parameters:
        exchange (str, optional): Exchange segment (default ``NFO``).

    Returns:
        JSON ``{"status": "success", "data": {"rows_inserted": N, ...}}``.
    """
    body = request.get_json(silent=True) or {}
    exchange_raw = body.get("exchange") if isinstance(body, dict) else None
    exchange = str(exchange_raw or request.args.get("exchange", "NFO")).upper()
    symbol_value = symbol.upper()
    canonical_expiry = normalise_expiry(expiry)
    tracker = _get_tracker()
    rows_inserted = tracker.capture_snapshot(symbol_value, expiry, exchange)
    capture_error = getattr(tracker, "last_capture_error", None)
    if rows_inserted == 0 and capture_error:
        status_code = 503 if "No OpenAlgo client configured" in capture_error else 502
        logger.warning("Historical chain capture failed: %s", capture_error)
        message = (
            "Historical chain capture failed: no OpenAlgo client is configured"
            if status_code == 503
            else "Historical chain capture failed — see the backend log for detail"
        )
        return jsonify({
            "status": "error",
            "message": message,
            "data": {
                "symbol": symbol_value,
                "expiry": canonical_expiry,
                "exchange": exchange,
                "rows_inserted": rows_inserted,
                "captured": False,
            },
        }), status_code

    return jsonify({
        "status": "success",
        "data": {
            "symbol": symbol_value,
            "expiry": canonical_expiry,
            "exchange": exchange,
            "rows_inserted": rows_inserted,
            "captured": rows_inserted > 0,
        },
    }), 200
