"""Flask blueprint for earnings calendar endpoints.

External URLs (frontend calls these via /ft-api/v1/earnings/*; the WSGI prefix
stripper in app.py rewrites to /v1/earnings/* before Flask dispatch):

    GET /ft-api/v1/earnings/calendar?days=30
        Upcoming earnings within the next N days.

    GET /ft-api/v1/earnings/by-date?date=2026-04-15
        All earnings announcements on a specific date (ISO format).

    GET /ft-api/v1/earnings/by-symbol?symbol=RELIANCE
        Full earnings history for a single NSE symbol.

Blueprint registered at ``/v1/earnings`` (post-strip form).

All endpoints return sample / synthetic data when no live source is connected.
The :class:`~packages.screener.src.earnings_calendar.EarningsCalendar` instance
is initialised lazily on the first request and cached for the lifetime of the
Flask application.

Response shape (all endpoints)::

    {
        "status": "success",
        "is_sample_data": true,
        "data": { ... }
    }
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from flask import Blueprint, jsonify, request

logger = logging.getLogger("flinttrade.screener.earnings_routes")

earnings_bp = Blueprint("earnings", __name__, url_prefix="/api/v1/earnings")

# ---------------------------------------------------------------------------
# Lazy calendar singleton
# ---------------------------------------------------------------------------

_calendar: Any = None  # EarningsCalendar | None


def _get_calendar() -> Any:
    """Return the module-level :class:`EarningsCalendar`, initialising if needed.

    On first call, ``generate_sample_data(months=6)`` is invoked to pre-populate
    3 months of history and 3 months of upcoming events.

    Returns:
        Initialised :class:`~packages.screener.src.earnings_calendar.EarningsCalendar`.
    """
    global _calendar  # noqa: PLW0603
    if _calendar is None:
        from .earnings_calendar import EarningsCalendar  # noqa: PLC0415

        _calendar = EarningsCalendar()
        _calendar.generate_sample_data(months=6)
        logger.info(
            "EarningsCalendar initialised with %d cached events",
            _calendar.event_count(),
        )
    return _calendar


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@earnings_bp.route("/calendar", methods=["GET"])
def earnings_calendar() -> tuple[Any, int]:
    """Return upcoming earnings events within the next N days.

    Query parameters:
        days (int): Look-ahead window in calendar days (1–365, default 30).

    Returns:
        JSON with upcoming events sorted by date then symbol::

            {
                "status": "success",
                "is_sample_data": true,
                "data": {
                    "days": 30,
                    "count": 12,
                    "events": [
                        {
                            "symbol": "RELIANCE",
                            "company_name": "Reliance Industries Ltd",
                            "date": "2026-04-18",
                            "quarter": "Q4",
                            "financial_year": "FY2026",
                            "estimated_eps": 67.5,
                            "actual_eps": null,
                            "surprise_pct": null,
                            "result": null
                        },
                        ...
                    ]
                }
            }
    """
    try:
        days = int(request.args.get("days", 30))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "days must be an integer"}), 400

    days = max(1, min(365, days))
    cal = _get_calendar()
    events = cal.get_upcoming(days=days)

    return jsonify({
        "status": "success",
        "is_sample_data": True,
        "data": {
            "days": days,
            "count": len(events),
            "events": [e.to_dict() for e in events],
        },
    }), 200


@earnings_bp.route("/by-date", methods=["GET"])
def earnings_by_date() -> tuple[Any, int]:
    """Return all earnings announcements on a specific date.

    Query parameters:
        date (str): ISO-format date string ``YYYY-MM-DD`` (required).

    Returns:
        JSON with all events on the given date::

            {
                "status": "success",
                "is_sample_data": true,
                "data": {
                    "date": "2026-04-15",
                    "count": 3,
                    "events": [ ... ]
                }
            }
    """
    date_str = request.args.get("date", "")
    if not date_str:
        return jsonify({"status": "error", "message": "date parameter is required"}), 400

    try:
        target = date.fromisoformat(date_str)
    except ValueError:
        return jsonify({
            "status": "error",
            "message": f"Invalid date format '{date_str}'. Expected YYYY-MM-DD.",
        }), 400

    cal = _get_calendar()
    events = cal.get_by_date(target)

    return jsonify({
        "status": "success",
        "is_sample_data": True,
        "data": {
            "date": target.isoformat(),
            "count": len(events),
            "events": [e.to_dict() for e in events],
        },
    }), 200


@earnings_bp.route("/by-symbol", methods=["GET"])
def earnings_by_symbol() -> tuple[Any, int]:
    """Return the complete earnings history for a single NSE symbol.

    Query parameters:
        symbol (str): NSE ticker symbol, case-insensitive (required).

    Returns:
        JSON with all events for the symbol sorted by date ascending::

            {
                "status": "success",
                "is_sample_data": true,
                "data": {
                    "symbol": "RELIANCE",
                    "count": 4,
                    "events": [ ... ]
                }
            }
    """
    symbol = (request.args.get("symbol") or "").strip().upper()
    if not symbol:
        return jsonify({"status": "error", "message": "symbol parameter is required"}), 400

    cal = _get_calendar()
    events = cal.get_by_symbol(symbol)

    return jsonify({
        "status": "success",
        "is_sample_data": True,
        "data": {
            "symbol": symbol,
            "count": len(events),
            "events": [e.to_dict() for e in events],
        },
    }), 200
