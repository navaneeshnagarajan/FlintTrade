"""Flask blueprint for enhanced OI analytics endpoints.

External URLs (frontend calls these via /ft-api/v1/oi/*; the WSGI prefix
stripper in app.py rewrites to /v1/oi/* before Flask dispatch):

    POST /ft-api/v1/oi/heatmap  — OI heatmap data (normalised per-strike OI)
    POST /ft-api/v1/oi/analysis — OI change analysis (LB/SC/SB/LU signals)
    POST /ft-api/v1/oi/unusual  — Unusual OI activity (z-score based)

Blueprint registered at ``/v1/oi`` (post-strip form).

All endpoints fall back to synthetic sample data when no broker is connected
so the OI widgets work in Explore mode.

Sample data is generated from the analysis_routes._make_sample_strikes()
pattern (the same synthetic option chain used by GEX, IV Smile, etc.).
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, current_app, jsonify

from . import broker_registry_reads as broker_reads
from .analysis_routes import (
    _MAX_CHAIN_ROWS,
    _MAX_MARKET_VALUE,
    _MAX_OI_CHANGE,
    _authoritative_chain_spot,
    _body_expiry,
    _chain_identity_matches,
    _finite_number,
    _live_option_days_to_expiry,
    _option_chain_underlying_exchange,
    _optional_row_count,
    _optional_row_float,
    _request_identity_string,
    _request_integer,
    _request_json_object,
    _request_number,
    _row_open_interest,
    _row_strike,
    _sample_strike_step,
)
from .oi_analytics import OIAnalytics, OISnapshot
from .option_chain import LOT_SIZES  # noqa: F401 — imported for symmetry with analysis_routes

logger = logging.getLogger("flinttrade.screener.oi_analytics_routes")

oi_analytics_bp = Blueprint("oi_analytics", __name__, url_prefix="/v1/oi")

_analytics = OIAnalytics()


# ---------------------------------------------------------------------------
# Sample data helpers
# ---------------------------------------------------------------------------


def _make_sample_oi_chain(
    spot: float = 24000.0,
    step: float = 100.0,
    count: int = 10,
) -> list[OISnapshot]:
    """Generate synthetic OISnapshot list centred around spot.

    Args:
        spot:  Centre spot price.
        step:  Strike step (default 100).
        count: Number of strikes each side of ATM (total = 2*count + 1).

    Returns:
        List of :class:`OISnapshot` objects.
    """
    safe_spot = _finite_number(spot)
    if safe_spot is None or not 0 < safe_spot <= _MAX_MARKET_VALUE:
        safe_spot = 1.0
    safe_count = max(0, min(int(count), 1000))
    safe_step = _sample_strike_step(safe_spot, step, safe_count)
    snapshots: list[OISnapshot] = []
    for i in range(-safe_count, safe_count + 1):
        k = safe_spot + i * safe_step
        dist = abs(i)
        ce_oi = max(1000, 50000 - dist * 4000)
        pe_oi = max(1000, 40000 - dist * 3500)
        # Add some OI changes to make change-analysis meaningful
        ce_change = int((ce_oi * 0.05) * (1 if i <= 0 else -1))
        pe_change = int((pe_oi * 0.04) * (-1 if i <= 0 else 1))
        # Inject one large unusual spike
        if i == 3:
            ce_change = int(ce_oi * 0.40)
        if i == -2:
            pe_change = int(pe_oi * 0.35)
        snapshots.append(OISnapshot(
            strike=k,
            ce_oi=ce_oi,
            pe_oi=pe_oi,
            ce_change=ce_change,
            pe_change=pe_change,
            ce_volume=ce_oi // 10,
            pe_volume=pe_oi // 10,
            ce_ltp=max(1.0, 200 - max(0, i) * 15),
            pe_ltp=max(1.0, 200 + min(0, i) * 15),
        ))
    return snapshots


def _chain_from_registry(
    registry: Any,
    symbol: str,
    exchange: str,
    expiry: str,
    *,
    require_oi_change: bool = False,
) -> tuple[list[OISnapshot], float]:
    """Fetch live option chain from registry and convert to OISnapshot list.

    Args:
        registry: BrokerRegistry instance.
        symbol:   Underlying symbol.
        exchange: Exchange code.
        expiry:   Expiry label.
        require_oi_change: Exclude rows without explicit finite OI changes.

    Returns:
        Tuple of (snapshots, spot_price).

    Raises:
        Exception: If the registry call fails.
    """
    dte = _live_option_days_to_expiry(expiry)
    if dte is None:
        raise ValueError("Live OI chain requires a valid future expiry")
    underlying_exchange = _option_chain_underlying_exchange(symbol, exchange)
    chain_data = broker_reads.get_option_chain(
        registry,
        symbol=symbol,
        exchange=underlying_exchange,
        expiry=expiry,
    )
    if not isinstance(chain_data, dict):
        raise ValueError("Live OI chain is not an object")
    if not _chain_identity_matches(chain_data, symbol, exchange, expiry):
        raise ValueError("Live OI chain identity does not match the request")
    spot = _authoritative_chain_spot(chain_data)
    if spot is None:
        raise ValueError("Live OI chain has no authoritative spot price")
    raw_strikes = chain_data.get("strikes")
    if not isinstance(raw_strikes, list) or not raw_strikes or len(raw_strikes) > _MAX_CHAIN_ROWS:
        raise ValueError("Live OI chain has no source rows")
    snapshots: list[OISnapshot] = []
    seen_strikes: set[float] = set()
    for row in raw_strikes:
        if not isinstance(row, dict):
            raise ValueError("Live OI chain source row is not an object")
        strike = _row_strike(row)
        ce_oi = _row_open_interest(row, "ce")
        pe_oi = _row_open_interest(row, "pe")
        if strike is None or strike in seen_strikes or ce_oi is None or pe_oi is None:
            raise ValueError("Live OI chain source row has invalid strike or OI")
        seen_strikes.add(strike)
        ce_change = _row_oi_change(row, "ce")
        pe_change = _row_oi_change(row, "pe")
        if require_oi_change and (ce_change is None or pe_change is None):
            raise ValueError("Live OI chain source row has no authoritative OI change")
        ce_volume = _optional_row_count(row, "ce_volume")
        pe_volume = _optional_row_count(row, "pe_volume")
        ce_ltp = _optional_row_float(row, "ce_ltp")
        pe_ltp = _optional_row_float(row, "pe_ltp")
        if None in (ce_volume, pe_volume, ce_ltp, pe_ltp):
            raise ValueError("Live OI chain source row has invalid optional observations")
        snapshots.append(OISnapshot(
            strike=strike,
            ce_oi=ce_oi,
            pe_oi=pe_oi,
            ce_change=ce_change,
            pe_change=pe_change,
            ce_volume=ce_volume,
            pe_volume=pe_volume,
            ce_ltp=ce_ltp,
            pe_ltp=pe_ltp,
        ))
    if not snapshots:
        raise ValueError("Live OI chain has no usable rows")
    return snapshots, spot


def _row_oi_change(row: dict[str, Any], prefix: str) -> int | None:
    for key in (f"{prefix}_oi_change", f"{prefix}_change"):
        if key not in row:
            continue
        change = _finite_number(row[key])
        if change is None or abs(change) > _MAX_OI_CHANGE or not change.is_integer():
            return None
        return int(change)
    return None


def _get_registry() -> Any:
    return current_app.config.get("REGISTRY")


def _oi_request() -> tuple[dict[str, Any], str, str, str]:
    body = _request_json_object()
    symbol = _request_identity_string(body, "symbol", "NIFTY")
    exchange = _request_identity_string(body, "exchange", "NFO")
    _option_chain_underlying_exchange(symbol, exchange)
    expiry = _body_expiry(body, "")
    return body, symbol, exchange, expiry


# ---------------------------------------------------------------------------
# POST /ft-api/v1/oi/heatmap
# ---------------------------------------------------------------------------


@oi_analytics_bp.route("/heatmap", methods=["POST"])
def oi_heatmap_endpoint() -> tuple[Any, int]:
    """OI heatmap data — normalised CE/PE OI across strikes.

    Request JSON:
        symbol (str):     Underlying symbol (default "NIFTY").
        exchange (str):   Exchange code (default "NFO").
        expiry (str):     Expiry label (default "").
        n_strikes (int):  Strikes to include in heatmap (default 20).

    Returns:
        JSON with heatmap entries, max-OI strikes, PCR, and total OI::

            {
              "status": "success",
              "symbol": str,
              "exchange": str,
              "spot": float,
              "is_sample_data": bool,
              "data": {
                "entries": [...],
                "max_ce_oi_strike": float,
                "max_pe_oi_strike": float,
                "total_ce_oi": int,
                "total_pe_oi": int,
                "overall_pcr": float | null
              }
            }
    """
    try:
        body, symbol, exchange, expiry = _oi_request()
        n_strikes = _request_integer(body, "n_strikes", 20, minimum=1)
        spot = _request_number(
            body,
            "spot",
            24000.0,
            minimum=0.0,
            maximum=_MAX_MARKET_VALUE,
            minimum_inclusive=False,
        )
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    chain: list[OISnapshot] | None = None
    is_sample_data = True

    registry = _get_registry()
    dte = _live_option_days_to_expiry(expiry)
    if registry and registry.is_connected() and dte is not None:
        try:
            candidate, candidate_spot = _chain_from_registry(registry, symbol, exchange, expiry)
            if candidate:
                chain, spot = candidate, candidate_spot
                is_sample_data = False
        except Exception as exc:
            logger.warning("OI heatmap: live data unavailable, using sample: %s", exc)

    if not chain:
        chain = _make_sample_oi_chain(spot=spot)
        logger.info("OI heatmap: using sample data for %s %s", symbol, exchange)

    result = _analytics.oi_heatmap(chain, n_strikes=n_strikes, spot=spot)

    return jsonify({
        "status": "success",
        "symbol": symbol,
        "exchange": exchange,
        "expiry": expiry,
        "spot": spot,
        "is_sample_data": is_sample_data,
        "data": result.model_dump(),
    }), 200


# ---------------------------------------------------------------------------
# POST /ft-api/v1/oi/analysis
# ---------------------------------------------------------------------------


@oi_analytics_bp.route("/analysis", methods=["POST"])
def oi_analysis_endpoint() -> tuple[Any, int]:
    """OI change analysis — classify each strike as LB / SC / SB / LU.

    Request JSON:
        symbol (str):       Underlying symbol (default "NIFTY").
        exchange (str):     Exchange code (default "NFO").
        expiry (str):       Expiry label.
        price_change (str): Underlying price move direction:
                            "up", "down", or "flat" (default "flat").

    Returns:
        JSON with per-strike signals and aggregate summary::

            {
              "status": "success",
              "data": {
                "signals": [...],
                "long_buildups": [strike, ...],
                "short_coverings": [strike, ...],
                "short_buildups": [strike, ...],
                "long_unwindings": [strike, ...],
                "summary": {"Long Build-up": N, ...}
              }
            }
    """
    try:
        body, symbol, exchange, expiry = _oi_request()
        price_change = _request_identity_string(body, "price_change", "flat").lower()
        if price_change not in ("up", "down", "flat"):
            raise ValueError("price_change must be one of: up, down, flat")
        spot = _request_number(
            body,
            "spot",
            24000.0,
            minimum=0.0,
            maximum=_MAX_MARKET_VALUE,
            minimum_inclusive=False,
        )
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    chain: list[OISnapshot] | None = None
    is_sample_data = True

    registry = _get_registry()
    dte = _live_option_days_to_expiry(expiry)
    if registry and registry.is_connected() and dte is not None:
        try:
            candidate, candidate_spot = _chain_from_registry(
                registry,
                symbol,
                exchange,
                expiry,
                require_oi_change=True,
            )
            if candidate:
                chain, spot = candidate, candidate_spot
                is_sample_data = False
        except Exception as exc:
            logger.warning("OI analysis: live data unavailable, using sample: %s", exc)

    if not chain:
        chain = _make_sample_oi_chain(spot=spot)
        logger.info("OI analysis: using sample data for %s %s", symbol, exchange)

    result = _analytics.oi_change_analysis(chain, price_change=price_change)

    return jsonify({
        "status": "success",
        "symbol": symbol,
        "exchange": exchange,
        "expiry": expiry,
        "spot": spot,
        "price_change": price_change,
        "is_sample_data": is_sample_data,
        "data": result.model_dump(),
    }), 200


# ---------------------------------------------------------------------------
# POST /ft-api/v1/oi/unusual
# ---------------------------------------------------------------------------


@oi_analytics_bp.route("/unusual", methods=["POST"])
def oi_unusual_endpoint() -> tuple[Any, int]:
    """Unusual OI activity — z-score based outlier detection.

    Request JSON:
        symbol (str):    Underlying symbol (default "NIFTY").
        exchange (str):  Exchange code (default "NFO").
        expiry (str):    Expiry label.
        threshold (float): Z-score threshold (default 2.0).

    Returns:
        JSON with list of unusual OI entries sorted by |z_score| descending::

            {
              "status": "success",
              "data": {
                "unusual": [
                  {
                    "strike": float,
                    "option_type": "CE" | "PE",
                    "oi": int,
                    "oi_change": int,
                    "change_pct": float,
                    "z_score": float,
                    "direction": "addition" | "reduction"
                  },
                  ...
                ],
                "count": int,
                "threshold": float
              }
            }
    """
    try:
        body, symbol, exchange, expiry = _oi_request()
        threshold = _request_number(body, "threshold", 2.0, minimum=0.0, maximum=100.0)
        spot = _request_number(
            body,
            "spot",
            24000.0,
            minimum=0.0,
            maximum=_MAX_MARKET_VALUE,
            minimum_inclusive=False,
        )
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    chain: list[OISnapshot] | None = None
    is_sample_data = True

    registry = _get_registry()
    dte = _live_option_days_to_expiry(expiry)
    if registry and registry.is_connected() and dte is not None:
        try:
            candidate, candidate_spot = _chain_from_registry(
                registry,
                symbol,
                exchange,
                expiry,
                require_oi_change=True,
            )
            if candidate:
                chain, spot = candidate, candidate_spot
                is_sample_data = False
        except Exception as exc:
            logger.warning("Unusual OI: live data unavailable, using sample: %s", exc)

    if not chain:
        chain = _make_sample_oi_chain(spot=spot)
        logger.info("Unusual OI: using sample data for %s %s", symbol, exchange)

    entries = _analytics.unusual_oi_activity(chain, threshold=threshold)

    return jsonify({
        "status": "success",
        "symbol": symbol,
        "exchange": exchange,
        "expiry": expiry,
        "spot": spot,
        "is_sample_data": is_sample_data,
        "data": {
            "unusual": [e.model_dump() for e in entries],
            "count": len(entries),
            "threshold": threshold,
        },
    }), 200
