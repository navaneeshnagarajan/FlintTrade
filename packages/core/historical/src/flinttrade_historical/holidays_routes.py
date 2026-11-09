"""Flask Blueprint for market holidays and session timings endpoints.

Endpoints
---------
GET /api/v1/holidays        — NSE/exchange market holidays for a given year
GET /api/v1/market/timings  — Standard (and special) session open/close times

Uses :mod:`flinttrade_engine.market_hours` for local special-session data
and :class:`flinttrade_core.broker_client.BrokerClient` for live
exchange holiday data from native broker.

Register in ``create_flask_app()``::

    from flinttrade_historical.holidays_routes import holidays_bp
    app.register_blueprint(holidays_bp, url_prefix="/api/v1")
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time
from typing import Any

from flask import Blueprint, jsonify, request

logger = logging.getLogger("flinttrade.historical.holidays_routes")

# Module-level imports so tests can patch at the correct namespace.
try:
    from flinttrade_core.broker_client import (
        client_call_sync,
        client_close_sync,
        normalise_holiday_dates,
        resolve_broker_client,
    )
except Exception:  # pragma: no cover
    resolve_broker_client = None  # type: ignore[assignment,misc]
    client_call_sync = None  # type: ignore[assignment,misc]
    client_close_sync = None  # type: ignore[assignment,misc]
    normalise_holiday_dates = None  # type: ignore[assignment,misc]

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

    On native broker failure the endpoint falls back to an empty list with a
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

    # Try native broker first for live/official holiday data
    try:
        if resolve_broker_client is None:
            raise ImportError("native broker client resolver not available")

        client, close_client = resolve_broker_client()
        try:
            raw = client_call_sync(client, client.holidays(year=str(year)))
        finally:
            if close_client:
                client_close_sync(client)

        if normalise_holiday_dates is None:
            raise ImportError("holiday response normaliser not available")
        holidays_list = normalise_holiday_dates(raw, exchange=exchange)

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
        logger.warning("native broker holidays fetch failed: %s — returning empty list", exc)
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
    on_text = (request.args.get("on") or "").strip()
    symbol = (request.args.get("symbol") or "").strip() or None
    expiries_text = (request.args.get("expiries") or "").strip()

    try:
        from flinttrade_engine.market_hours import (  # noqa: PLC0415
            STANDARD_HOURS,
            get_market_hours,
            get_standard_hours,
            is_special_session,
            list_upcoming_sessions,
            session_decision,
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
        session_date = date.fromisoformat(on_text) if on_text else date.today()
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid date"}), 400

    at_text = (request.args.get("at") or "").strip()
    try:
        probe = datetime.fromisoformat(at_text) if at_text else datetime.combine(session_date, time(12, 0))
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid date"}), 400
    if at_text and not on_text:
        session_date = probe.date()

    expiry_calendar = [item.strip() for item in expiries_text.split(",") if item.strip()] or None

    try:
        # Open stays the ordinary published open. A special session stays on
        # the list below and does not replace this row.
        if exchange in {"NFO", "BFO"} and is_special_session(session_date, exchange=exchange) is None:
            open_t, _ordinary_close = get_market_hours(exchange, session_date)
        else:
            open_t, _ordinary_close = get_standard_hours(exchange)
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid request"}), 400

    # NSE, BSE, NFO, BFO, MCX, and NCDEX publish the gate close from the
    # session decision. NCDEX is 17:00. MCX is 23:30. The ordinary row does
    # not apply a special session.
    decision = session_decision(
        exchange,
        probe,
        symbol=symbol,
        expiry_calendar=expiry_calendar,
        apply_special=False,
    )
    phase = decision.phase if exchange in {"NSE", "BSE", "NFO", "BFO", "MCX", "NCDEX"} else None
    order_entry = "open"
    close_t = _ordinary_close
    if exchange in {"NSE", "BSE", "NFO", "BFO", "MCX", "NCDEX"}:
        if decision.reason == "unknown_expiry" or decision.order_close is None:
            order_entry = "closed"
            close_t = None
        else:
            close_t = decision.order_close.time().replace(tzinfo=None)

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
    special: list[dict[str, Any]] = []
    for s in upcoming:
        if s.exchanges and exchange not in s.exchanges:
            continue
        row: dict[str, Any] = {
            "date": s.session_date.isoformat(),
            "name": s.name,
            "open": f"{s.open_time.hour:02d}:{s.open_time.minute:02d}",
            "close": f"{s.close_time.hour:02d}:{s.close_time.minute:02d}",
        }
        if s.pre_open_time is not None:
            row["pre_open"] = f"{s.pre_open_time.hour:02d}:{s.pre_open_time.minute:02d}"
        special.append(row)

    revised_derivatives = exchange in {"NFO", "BFO"} and session_date >= date(2026, 12, 7)
    if is_special_session(session_date, exchange=exchange) is not None:
        revised_derivatives = False
    close_label = None if order_entry == "closed" else f"{close_t.hour:02d}:{close_t.minute:02d}"
    return (
        jsonify(
            {
                "status": "success",
                "exchange": exchange,
                "pre_open": pre_open,
                "open": f"{open_t.hour:02d}:{open_t.minute:02d}",
                "close": close_label,
                "phase": phase,
                "order_entry": order_entry,
                "expiring_index_close": "15:30" if revised_derivatives else None,
                "special_sessions": special,
            }
        ),
        200,
    )
