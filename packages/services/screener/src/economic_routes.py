"""Flask blueprint for economic calendar endpoint.

External URL (frontend calls this via /ft-api/v1/economic/*; the WSGI prefix
stripper in app.py rewrites to /v1/economic/* before Flask dispatch):

    GET /ft-api/v1/economic/calendar?days=14&country=IN,US&impact=high

Blueprint registered at ``/v1/economic`` (post-strip form).

Response shape::

    {
        "status": "success",
        "is_sample_data": true,
        "data": {
            "days": 14,
            "filters": { "countries": ["IN", "US"], "min_impact": "high" },
            "count": 3,
            "events": [ { "date": "2026-04-10", "time": "10:00", ... }, ... ]
        }
    }
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

logger = logging.getLogger("flinttrade.screener.economic_routes")

economic_bp = Blueprint("economic", __name__, url_prefix="/v1/economic")

# ---------------------------------------------------------------------------
# Lazy singleton
# ---------------------------------------------------------------------------

_provider: Any = None  # EconomicCalendarProvider | None


def _get_provider() -> Any:
    """Return the module-level provider, initialising lazily on first call.

    Returns:
        Initialised :class:`~flinttrade_screener.economic_calendar.EconomicCalendarProvider`.
    """
    global _provider  # noqa: PLW0603
    if _provider is None:
        from .economic_calendar import EconomicCalendarProvider  # noqa: PLC0415

        _provider = EconomicCalendarProvider()
        _provider.generate_sample_data(months=4)
        logger.info(
            "EconomicCalendarProvider initialised with %d cached events",
            _provider.event_count(),
        )
    return _provider


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@economic_bp.route("/calendar", methods=["GET"])
def economic_calendar() -> tuple[Any, int]:
    """Return upcoming economic events with optional filters.

    Query parameters:
        days (int): Look-ahead window in calendar days (1–365, default 14).
        country (str): Comma-separated two-letter country codes to filter by
            (e.g. ``IN,US``).  Omit or leave blank to include all countries.
        impact (str): Minimum impact level — ``"low"``, ``"medium"``, or
            ``"high"`` (default ``"low"``).

    Returns:
        JSON with filtered events sorted by date::

            {
                "status": "success",
                "is_sample_data": true,
                "data": {
                    "days": 14,
                    "filters": { "countries": ["IN", "US"], "min_impact": "high" },
                    "count": 3,
                    "events": [
                        {
                            "date": "2026-04-10",
                            "time": "10:00",
                            "event": "RBI Monetary Policy Decision",
                            "country": "IN",
                            "impact": "high",
                            "previous": "6.50%",
                            "forecast": "6.50%",
                            "actual": null,
                            "category": "interest_rate"
                        },
                        ...
                    ]
                }
            }

        On validation error returns HTTP 400.
    """
    # --- Parse query parameters ---
    try:
        days = int(request.args.get("days", 14))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "days must be an integer"}), 400

    days = max(1, min(365, days))

    country_raw = request.args.get("country", "").strip()
    countries: list[str] | None = (
        [c.strip().upper() for c in country_raw.split(",") if c.strip()]
        if country_raw
        else None
    )

    impact_raw = request.args.get("impact", "low").strip().lower()
    if impact_raw not in ("low", "medium", "high"):
        return (
            jsonify({
                "status": "error",
                "message": "impact must be one of: low, medium, high",
            }),
            400,
        )

    provider = _get_provider()
    events = provider.get_upcoming(
        days=days, countries=countries, min_impact=impact_raw
    )

    return (
        jsonify({
            "status": "success",
            "is_sample_data": True,
            "data": {
                "days": days,
                "filters": {
                    "countries": countries or [],
                    "min_impact": impact_raw,
                },
                "count": len(events),
                "events": [e.to_dict() for e in events],
            },
        }),
        200,
    )
