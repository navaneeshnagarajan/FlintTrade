"""Flask Blueprint for market holidays and session timings endpoints.

Endpoints
---------
GET /api/v1/holidays        — NSE/exchange market holidays for a given year
GET /api/v1/market/timings  — Standard (and special) session open/close times

Uses :mod:`flinttrade_engine.market_hours` for local special-session data
and :class:`flinttrade_core.openalgo_client.OpenAlgoClient` for live
exchange holiday data from OpenAlgo.

Register in ``create_flask_app()``::

    from flinttrade_historical.holidays_routes import holidays_bp
    app.register_blueprint(holidays_bp, url_prefix="/api/v1")
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

from flask import Blueprint, jsonify, request

logger = logging.getLogger("flinttrade.historical.holidays_routes")

# Module-level imports so tests can patch at the correct namespace.
try:
    from flinttrade_core.openalgo_client import OpenAlgoClient
    from flinttrade_core.config import Settings
except Exception:  # pragma: no cover
    OpenAlgoClient = None  # type: ignore[assignment,misc]
    Settings = None  # type: ignore[assignment,misc]

holidays_bp = Blueprint("holidays", __name__, url_prefix="/api/v1")


def _run_async(coro: Any) -> Any:
    """Run an async coroutine synchronously from a Flask route.

    Args:
        coro: Awaitable coroutine to execute.

    Returns:
        The return value of the coroutine.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@holidays_bp.route("/holidays", methods=["GET"])
def get_holidays() -> tuple[Any, int]:
    """Return market holidays for an exchange in a given year.

    Query parameters:
        exchange (str, optional): Exchange code, e.g. ``NSE``.  Defaults to ``NSE``.
        year (int, optional): Four-digit year.  Defaults to current year.

    Returns:
        JSON ``{"status": "success", "exchange": "NSE", "year": 2026,
        "holidays": ["2026-01-01", ...]}``.

    On OpenAlgo failure the endpoint falls back to an empty list with a
    ``"source": "fallback"`` field so callers can detect degraded mode.
    """
    exchange: str = request.args.get("exchange", "NSE").upper()
    year_raw: str = request.args.get("year", str(date.today().year))

    try:
        year = int(year_raw)
    except ValueError:
        return (
            jsonify({"status": "error", "message": "year must be a 4-digit integer"}),
            400,
        )

    if year < 2000 or year > 2100:
        return (
            jsonify({"status": "error", "message": "year must be between 2000 and 2100"}),
            400,
        )

    # Try OpenAlgo first for live/official holiday data
    try:
        if OpenAlgoClient is None or Settings is None:
            raise ImportError("OpenAlgoClient or Settings not available")

        client = OpenAlgoClient(Settings.from_env())
        raw = _run_async(client.holidays(year=str(year)))
        _run_async(client.close())

        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        holidays_list: list[str] = []

        if isinstance(data, list):
            holidays_list = [str(h) for h in data]
        elif isinstance(data, dict):
            # Some OpenAlgo versions return {"NSE": ["2026-01-01", ...]}
            holidays_list = [str(h) for h in data.get(exchange, data.get("holidays", []))]

        return (
            jsonify(
                {
                    "status": "success",
                    "exchange": exchange,
                    "year": year,
                    "holidays": sorted(holidays_list),
                    "count": len(holidays_list),
                }
            ),
            200,
        )
    except Exception as exc:
        logger.warning("OpenAlgo holidays fetch failed: %s — returning empty list", exc)
        return (
            jsonify(
                {
                    "status": "success",
                    "exchange": exchange,
                    "year": year,
                    "holidays": [],
                    "count": 0,
                    "source": "fallback",
                }
            ),
            200,
        )


@holidays_bp.route("/market/timings", methods=["GET"])
def get_timings() -> tuple[Any, int]:
    """Return session open/close times for an exchange.

    Combines standard hours from the local registry with any known
    special sessions (e.g. Muhurat Trading).

    Query parameters:
        exchange (str, optional): Exchange code.  Defaults to ``NSE``.
            Supported: NSE, BSE, NFO, BFO, CDS, BCD, MCX, NCDEX,
            NSE_INDEX, BSE_INDEX.

    Returns:
        JSON ``{"status": "success", "exchange": "NSE",
        "pre_open": "09:00", "open": "09:15", "close": "15:30",
        "special_sessions": [...]}``.

    Raises HTTP 400 for unrecognised exchange codes.
    """
    exchange: str = request.args.get("exchange", "NSE").upper()

    try:
        from flinttrade_engine.market_hours import (  # noqa: PLC0415
            get_standard_hours,
            list_upcoming_sessions,
            STANDARD_HOURS,
        )
    except ImportError as exc:
        logger.error("market_hours module not available: %s", exc)
        return jsonify({"status": "error", "message": "market_hours module unavailable"}), 503

    if exchange not in STANDARD_HOURS:
        supported = sorted(STANDARD_HOURS.keys())
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"Unknown exchange: {exchange!r}",
                    "supported": supported,
                }
            ),
            400,
        )

    try:
        open_t, close_t = get_standard_hours(exchange)
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid request"}), 400

    # Pre-open is 15 min before open for equity exchanges, same as open otherwise
    _equity = {"NSE", "BSE", "NFO", "BFO", "NSE_INDEX", "BSE_INDEX"}
    if exchange in _equity:
        pre_open_hour = open_t.hour
        pre_open_min = open_t.minute - 15
        if pre_open_min < 0:
            pre_open_hour -= 1
            pre_open_min += 60
        pre_open = f"{pre_open_hour:02d}:{pre_open_min:02d}"
    else:
        pre_open = f"{open_t.hour:02d}:{open_t.minute:02d}"

    # Upcoming special sessions for this exchange
    upcoming = list_upcoming_sessions(limit=5)
    special: list[dict[str, Any]] = [
        {
            "date": s.session_date.isoformat(),
            "name": s.name,
            "open": f"{s.open_time.hour:02d}:{s.open_time.minute:02d}",
            "close": f"{s.close_time.hour:02d}:{s.close_time.minute:02d}",
        }
        for s in upcoming
        if not s.exchanges or exchange in s.exchanges
    ]

    return (
        jsonify(
            {
                "status": "success",
                "exchange": exchange,
                "pre_open": pre_open,
                "open": f"{open_t.hour:02d}:{open_t.minute:02d}",
                "close": f"{close_t.hour:02d}:{close_t.minute:02d}",
                "special_sessions": special,
            }
        ),
        200,
    )
