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

from flask import Blueprint, current_app, jsonify, request

from . import broker_registry_reads as broker_reads
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
    snapshots: list[OISnapshot] = []
    for i in range(-count, count + 1):
        k = spot + i * step
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
) -> tuple[list[OISnapshot], float]:
    """Fetch live option chain from registry and convert to OISnapshot list.

    Args:
        registry: BrokerRegistry instance.
        symbol:   Underlying symbol.
        exchange: Exchange code.
        expiry:   Expiry label.

    Returns:
        Tuple of (snapshots, spot_price).

    Raises:
        Exception: If the registry call fails.
    """
    chain_data = broker_reads.get_option_chain(
        registry,
        symbol=symbol,
        exchange=exchange,
        expiry=expiry,
    )
    spot = float(chain_data.get("spot", 24000.0))
    snapshots: list[OISnapshot] = []
    for row in chain_data.get("strikes", []):
        k = float(row.get("strike_price", row.get("strike", 0)))
        if k <= 0:
            continue
        snapshots.append(OISnapshot(
            strike=k,
            ce_oi=int(row.get("ce_oi", 0)),
            pe_oi=int(row.get("pe_oi", 0)),
            ce_change=int(row.get("ce_oi_change", row.get("ce_change", 0))),
            pe_change=int(row.get("pe_oi_change", row.get("pe_change", 0))),
            ce_volume=int(row.get("ce_volume", 0)),
            pe_volume=int(row.get("pe_volume", 0)),
            ce_ltp=float(row.get("ce_ltp", 0)),
            pe_ltp=float(row.get("pe_ltp", 0)),
        ))
    return snapshots, spot


def _get_registry() -> Any:
    return current_app.config.get("REGISTRY")


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
                "overall_pcr": float
              }
            }
    """
    body = request.get_json(silent=True) or {}
    symbol = str(body.get("symbol", "NIFTY"))
    exchange = str(body.get("exchange", "NFO"))
    expiry = str(body.get("expiry", ""))
    n_strikes = int(body.get("n_strikes", 20))
    spot = float(body.get("spot", 24000.0))

    chain: list[OISnapshot] | None = None
    is_sample_data = True

    registry = _get_registry()
    if registry and registry.is_connected():
        try:
            chain, spot = _chain_from_registry(registry, symbol, exchange, expiry)
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
    body = request.get_json(silent=True) or {}
    symbol = str(body.get("symbol", "NIFTY"))
    exchange = str(body.get("exchange", "NFO"))
    expiry = str(body.get("expiry", ""))
    price_change = str(body.get("price_change", "flat")).lower()
    if price_change not in ("up", "down", "flat"):
        price_change = "flat"
    spot = float(body.get("spot", 24000.0))

    chain: list[OISnapshot] | None = None
    is_sample_data = True

    registry = _get_registry()
    if registry and registry.is_connected():
        try:
            chain, spot = _chain_from_registry(registry, symbol, exchange, expiry)
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
    body = request.get_json(silent=True) or {}
    symbol = str(body.get("symbol", "NIFTY"))
    exchange = str(body.get("exchange", "NFO"))
    expiry = str(body.get("expiry", ""))
    threshold = float(body.get("threshold", 2.0))
    spot = float(body.get("spot", 24000.0))

    chain: list[OISnapshot] | None = None
    is_sample_data = True

    registry = _get_registry()
    if registry and registry.is_connected():
        try:
            chain, spot = _chain_from_registry(registry, symbol, exchange, expiry)
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
