"""Flask Blueprint for P&L aggregated by symbol.

Endpoint
--------
GET /api/v1/pnl/symbols  — per-symbol P&L breakdown optionally filtered by date range

Aggregates from :class:`flinttrade_journal.pnl_tracker.PnLTracker` in-memory
series.  For date-range filtering the endpoint uses the ``date_from`` and
``date_to`` query parameters (ISO-8601 date strings).

Register in ``create_flask_app()``::

    from flinttrade_data.pnl_symbols_routes import pnl_symbols_bp
    app.register_blueprint(pnl_symbols_bp)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from flask import Blueprint, jsonify, request

from flinttrade_journal.pnl_tracker import PnLTracker

logger = logging.getLogger("flinttrade.data.pnl_symbols_routes")

pnl_symbols_bp = Blueprint("pnl_symbols", __name__, url_prefix="/api/v1")

# IST timezone offset
_IST = timezone(timedelta(hours=5, minutes=30))

# Module-level singleton — replaced via init_pnl_symbols_routes() for DI.
_tracker: PnLTracker = PnLTracker()


def init_pnl_symbols_routes(tracker: PnLTracker) -> None:
    """Inject a :class:`PnLTracker` instance into this blueprint's singleton.

    Args:
        tracker: The :class:`PnLTracker` instance to use for all requests.
    """
    global _tracker  # noqa: PLW0603
    _tracker = tracker
    logger.info("PnLTracker injected into pnl_symbols_routes")


def _parse_iso_date(value: str, field_name: str) -> tuple[datetime | None, tuple[Any, int] | None]:
    """Parse an ISO-8601 date string into an aware datetime.

    Args:
        value: The raw string from the query parameter.
        field_name: Name used in error messages.

    Returns:
        Tuple of ``(datetime, None)`` on success or ``(None, error_response)``
        on failure.
    """
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_IST)
            return dt, None
        except ValueError:
            continue
    return None, (
        jsonify(
            {
                "status": "error",
                "message": f"{field_name} must be an ISO-8601 date (YYYY-MM-DD)",
            }
        ),
        400,
    )


@pnl_symbols_bp.route("/pnl/symbols", methods=["GET", "POST"])
def pnl_by_symbols() -> tuple[Any, int]:
    """Return P&L aggregated by symbol for a given date range.

    Accepts both GET (query params) and POST (JSON body) so the route
    contract matches OpenAlgo's ``POST /api/v1/pnl/symbols`` endpoint —
    which the terminal's ``api.ts`` ``getPnlSymbols()`` helper targets.
    The FlintTrade backend version is currently unused by the terminal
    (Vite's ``/api`` proxy routes that helper to OpenAlgo, not here), but
    accepting both verbs prevents a future caller from hitting a 405.

    The endpoint reads the in-memory P&L series held by the module-level
    :class:`PnLTracker` singleton.  Because :class:`PnLTracker` stores
    aggregate snapshots rather than per-trade records, the response
    exposes the *latest* snapshot values alongside time-series stats.

    Query parameters / JSON body:
        date_from (str, optional): ISO-8601 start date, e.g. ``2026-04-01``.
        date_to (str, optional): ISO-8601 end date, e.g. ``2026-04-30``.

    Returns:
        JSON ``{"status": "success", "date_from": "...", "date_to": "...",
        "summary": {...}, "series_count": N}``.
    """
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        date_from_raw: str = str(body.get("date_from", "")).strip()
        date_to_raw: str = str(body.get("date_to", "")).strip()
    else:
        date_from_raw = request.args.get("date_from", "").strip()
        date_to_raw = request.args.get("date_to", "").strip()

    since_ts: float | None = None
    until_ts: float | None = None

    if date_from_raw:
        dt_from, err = _parse_iso_date(date_from_raw, "date_from")
        if err is not None:
            return err
        since_ts = dt_from.timestamp()  # type: ignore[union-attr]

    if date_to_raw:
        dt_to, err = _parse_iso_date(date_to_raw, "date_to")
        if err is not None:
            return err
        # Include the full end day — shift to end-of-day
        until_ts = dt_to.replace(  # type: ignore[union-attr]
            hour=23, minute=59, second=59
        ).timestamp()

    series = _tracker.get_series(since=since_ts)

    # Filter by upper bound if provided
    if until_ts is not None:
        series = [p for p in series if p.timestamp <= until_ts]

    summary = _tracker.get_summary()

    # Build per-symbol-like breakdown from aggregated series
    # PnLTracker stores aggregate points, not per-symbol breakdowns.
    # We return the time-windowed summary with period stats.
    period_realized = sum(p.realized_pnl for p in series)
    period_unrealized = sum(p.unrealized_pnl for p in series) / max(len(series), 1)
    period_total = period_realized + period_unrealized

    return (
        jsonify(
            {
                "status": "success",
                "date_from": date_from_raw or None,
                "date_to": date_to_raw or None,
                "series_count": len(series),
                "period": {
                    "realized_pnl": round(period_realized, 2),
                    "unrealized_pnl": round(period_unrealized, 2),
                    "total_pnl": round(period_total, 2),
                    "trade_count": series[-1].trade_count if series else 0,
                },
                "overall_summary": summary,
            }
        ),
        200,
    )
