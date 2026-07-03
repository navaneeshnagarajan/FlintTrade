"""Flask blueprint for market breadth and volatility cone endpoints.

External URLs (frontend calls these via /ft-api/v1/*; the WSGI prefix stripper
in app.py rewrites to /v1/* before Flask dispatch):
    GET  /ft-api/v1/breadth/current        — Latest breadth snapshot
    GET  /ft-api/v1/breadth/history        — Historical breadth (query: days=30)
    POST /ft-api/v1/analytics/volcone      — Volatility cone from return series

Blueprint registered at ``/v1`` (post-strip form).

All endpoints fall back to sample/synthetic data when no live data is
available, so the terminal works in Explore mode without a broker connection.
"""

from __future__ import annotations

import logging
import threading
from datetime import date
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from .market_breadth import BreadthData, MarketBreadthCalculator
from .volatility_cone import VolatilityCone

logger = logging.getLogger("flinttrade.screener.breadth_routes")

breadth_bp = Blueprint("breadth", __name__, url_prefix="/v1")

# Module-level calculator instance — shared across requests.
# For production multi-process deployments this would be replaced by a
# process-local store or a persistent cache (DuckDB/Redis).
_calculator: MarketBreadthCalculator | None = None

# Live-history accumulation: every live breadth computation from
# /breadth/current lands here keyed by ISO date (the day's latest computation
# wins), so /breadth/history can serve REAL accumulated points instead of the
# sample series once a broker has been connected. Process-local, like the
# smart-route job store (single-process Waitress is the supported deployment);
# bounded to a year of days.
_LIVE_HISTORY: dict[str, dict[str, Any]] = {}
_LIVE_HISTORY_LOCK = threading.Lock()
_LIVE_HISTORY_MAX_DAYS = 365


def _record_live_breadth(point: dict[str, Any]) -> None:
    """Record a live breadth computation into the in-process history."""
    with _LIVE_HISTORY_LOCK:
        _LIVE_HISTORY[str(point.get("date"))] = point
        while len(_LIVE_HISTORY) > _LIVE_HISTORY_MAX_DAYS:
            del _LIVE_HISTORY[min(_LIVE_HISTORY)]


def _get_calculator() -> MarketBreadthCalculator:
    """Return the module-level breadth calculator, seeding sample data on first use.

    Returns:
        MarketBreadthCalculator with at least 90 days of data available.
    """
    global _calculator  # noqa: PLW0603
    if _calculator is None or not _calculator.get_history():
        _calculator = MarketBreadthCalculator()
        _calculator.generate_sample_data(days=90)
        logger.info("BreadthRoutes: seeded sample data (90 days)")
    return _calculator


def _live_breadth_from_quotes(client: Any) -> dict[str, int] | None:
    """Compute real NIFTY 50 advance/decline breadth from live bridge quotes.

    The previous live branch called ``registry.get_market_breadth()`` — a
    method that exists on no registry — so the connected path was dead code
    and the card could never leave sample data. This computes breadth the
    honest way: one multi-quote call over the NIFTY 50 universe, classifying
    each constituent against its previous close.

    ``new_highs``/``new_lows`` need 52-week data the bridge quote does not
    carry, so they stay 0 on the live path (advance/decline is the breadth
    headline; nothing is fabricated).

    Args:
        client: The async OpenAlgo bridge client (``app.config["OPENALGO_CLIENT"]``).

    Returns:
        ``{"advances": A, "declines": D, "unchanged": U}`` or ``None`` when no
        usable live quotes are available (caller falls back to sample).
    """
    if client is None:
        return None
    import asyncio  # noqa: PLC0415

    from .market_scanner import _NIFTY50_SYMBOLS  # noqa: PLC0415

    payload = [{"symbol": s, "exchange": "NSE"} for s in _NIFTY50_SYMBOLS]
    try:
        quotes = asyncio.run(client.multi_quotes(payload))
    except Exception as exc:
        logger.warning("Live breadth quote sweep failed: %s", exc)
        return None

    advances = declines = unchanged = counted = 0
    for quote in quotes or []:
        ltp = float(getattr(quote, "ltp", 0) or 0)
        prev = float(getattr(quote, "prev_close", 0) or 0)
        if ltp <= 0 or prev <= 0:
            continue
        counted += 1
        if ltp > prev:
            advances += 1
        elif ltp < prev:
            declines += 1
        else:
            unchanged += 1

    if counted < 10:
        # Too few real quotes to honestly call it market breadth.
        logger.warning("Live breadth: only %d usable quotes — falling back to sample", counted)
        return None
    return {"advances": advances, "declines": declines, "unchanged": unchanged}


def _breadth_to_dict(d: BreadthData) -> dict[str, Any]:
    """Serialise a BreadthData model to a JSON-safe dict.

    Args:
        d: BreadthData pydantic model instance.

    Returns:
        Dictionary with all fields; date is ISO-formatted string.
    """
    return {
        "date": d.date.isoformat(),
        "advances": d.advances,
        "declines": d.declines,
        "unchanged": d.unchanged,
        "new_highs": d.new_highs,
        "new_lows": d.new_lows,
        "ad_ratio": d.ad_ratio,
        "ad_line": d.ad_line,
        "mcclellan_oscillator": d.mcclellan_oscillator,
        "breadth_thrust": d.breadth_thrust,
    }


# ---------------------------------------------------------------------------
# Market breadth endpoints
# ---------------------------------------------------------------------------


@breadth_bp.route("/breadth/current", methods=["GET"])
def breadth_current() -> Any:
    """Return the latest market breadth snapshot.

    Attempts to read live breadth data from the broker registry when connected.
    Falls back to the most recent sample data point when no live data is
    available (Explore mode).

    Returns:
        JSON::

            {
              "status": "success",
              "is_sample_data": true,
              "data": { <BreadthData fields> }
            }
    """
    registry = current_app.config.get("REGISTRY")

    if registry and getattr(registry, "is_connected", lambda: False)():
        raw = _live_breadth_from_quotes(current_app.config.get("OPENALGO_CLIENT"))
        if raw is not None:
            # Build the live point in ISOLATION — never mutate the shared
            # sample-seeded calculator (doing so per 60s poll stacked
            # future-dated duplicate days and recomputed the cumulative
            # A-D line / McClellan / breadth-thrust over synthetic+live junk,
            # presenting fabricated derived indicators as live). The live
            # snapshot reports REAL advance/decline only; the multi-day
            # derived indicators require the historical feed (still sample)
            # and are left at neutral defaults rather than faked.
            advances, declines = raw["advances"], raw["declines"]
            logger.info(
                "BreadthCurrent: live NIFTY 50 breadth %d/%d/%d", advances, declines, raw["unchanged"],
            )
            # Only the genuinely-live single-day fields are populated. The
            # cumulative A-D line, McClellan oscillator, breadth thrust and
            # 52-week new-high/low counts all need a real consecutive history
            # (and 52w data) the live snapshot does not have — report them as
            # null rather than as live 0s (a single-day advances-declines is
            # NOT the cumulative ad_line the schema documents).
            live_point = {
                "date": date.today().isoformat(),
                "advances": advances,
                "declines": declines,
                "unchanged": raw["unchanged"],
                "ad_ratio": round(float(advances) / float(declines), 4) if declines > 0 else 1.0,
                "new_highs": None,
                "new_lows": None,
                "ad_line": None,
                "mcclellan_oscillator": None,
                "breadth_thrust": None,
            }
            # Accumulate so /breadth/history can serve REAL points (the day's
            # latest computation wins).
            _record_live_breadth(live_point)
            return jsonify({
                "status": "success",
                "is_sample_data": False,
                "data": live_point,
            })

    history = _get_calculator().get_history(days=1)
    if not history:
        return jsonify({"status": "error", "message": "No breadth data available"}), 500

    return jsonify({
        "status": "success",
        "is_sample_data": True,
        "data": _breadth_to_dict(history[-1]),
    })


@breadth_bp.route("/breadth/history", methods=["GET"])
def breadth_history() -> Any:
    """Return historical market breadth data.

    Query params:
        days (int): Number of recent trading days to return (default 30,
            clamped to 1–365).

    Returns:
        JSON::

            {
              "status": "success",
              "days": 30,
              "is_sample_data": true,
              "count": 30,
              "data": [ { <BreadthData fields> }, ... ]
            }
    """
    days = max(1, min(365, int(request.args.get("days", 30))))

    # Serve REAL accumulated points when live breadth has been computed (every
    # /breadth/current poll while connected records its result). The series
    # only spans days the backend was actually polling — honest, never padded
    # with synthetic history.
    with _LIVE_HISTORY_LOCK:
        live_points = [_LIVE_HISTORY[k] for k in sorted(_LIVE_HISTORY)[-days:]]
    if live_points:
        return jsonify({
            "status": "success",
            "days": days,
            "is_sample_data": False,
            "count": len(live_points),
            "data": live_points,
        })

    calc = _get_calculator()
    history = calc.get_history(days=days)

    return jsonify({
        "status": "success",
        "days": days,
        "is_sample_data": True,  # no live points accumulated yet
        "count": len(history),
        "data": [_breadth_to_dict(d) for d in history],
    })


# ---------------------------------------------------------------------------
# Volatility cone endpoint
# ---------------------------------------------------------------------------


@breadth_bp.route("/analytics/volcone", methods=["POST"])
def volcone_endpoint() -> Any:
    """Calculate a volatility cone from daily return series.

    Request JSON:
        returns (list[float]): Daily log-returns or simple returns, oldest first.
            Minimum length: ``max(lookback_periods) + 1``.
        lookback_periods (list[int], optional): Windows in trading days.
            Defaults to ``[5, 10, 20, 30, 60, 90]``.
        current_iv (float, optional): Current annualised implied volatility
            (e.g. 0.18 for 18%) to overlay on the cone.

    Returns:
        JSON::

            {
              "status": "success",
              "count": 6,
              "data": [
                {
                  "lookback": 5,
                  "current_hv": 0.1423,
                  "current_iv": 0.18,
                  "p10": 0.09, "p25": 0.11, "p50": 0.14,
                  "p75": 0.18, "p90": 0.22,
                  "min": 0.07, "max": 0.31,
                  "iv_percentile": 72.4
                }, ...
              ]
            }

    Errors:
        400: ``returns`` is missing or empty.
        422: No cone points could be computed (series too short).
    """
    body = request.get_json(silent=True) or {}

    raw_returns = body.get("returns")
    if not raw_returns:
        return jsonify({"status": "error", "message": "'returns' field is required and must be non-empty"}), 400

    try:
        daily_returns = [float(r) for r in raw_returns]
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Invalid return values"}), 400

    lookback_periods: list[int] | None = None
    if "lookback_periods" in body:
        try:
            lookback_periods = [int(p) for p in body["lookback_periods"]]
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "Invalid lookback_periods"}), 400

    current_iv: float | None = None
    if "current_iv" in body:
        try:
            current_iv = float(body["current_iv"])
        except (TypeError, ValueError):
            pass  # Silently ignore bad IV; cone is still useful without it

    cone = VolatilityCone()
    points = cone.calculate(daily_returns, lookback_periods=lookback_periods, current_iv=current_iv)

    if not points:
        return jsonify({
            "status": "error",
            "message": "Return series too short to compute any cone points. "
                       "Need at least max(lookback_periods) + 1 data points.",
        }), 422

    # Annotate each point with its IV percentile when IV is available
    serialised = []
    for p in points:
        row: dict[str, Any] = p.model_dump()
        row["date"] = None  # placeholder; terminal can use its own date axis
        if current_iv is not None:
            row["iv_percentile"] = cone.iv_percentile(current_iv, p)
        else:
            row["iv_percentile"] = None
        serialised.append(row)

    return jsonify({
        "status": "success",
        "count": len(serialised),
        "data": serialised,
    })
