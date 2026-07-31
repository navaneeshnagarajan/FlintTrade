"""Flask blueprint for payoff analysis, regime detection, and correlation endpoints.

External URLs (frontend calls these via /ft-api/v1/*; the WSGI prefix stripper
in app.py rewrites to /v1/* before Flask dispatch):
    POST /ft-api/v1/payoff/analyse        — Full options payoff analysis
    POST /ft-api/v1/payoff/curve          — P&L curve only (lightweight)
    GET  /ft-api/v1/regime/current        — Current market regime signal
    POST /ft-api/v1/analytics/correlation — Correlation matrix + regime

Blueprint registered at ``/v1`` (post-strip form).

All endpoints:
1. Extract parameters from JSON body or query string.
2. Validate and parse using Pydantic models where appropriate.
3. Delegate computation to the relevant engine class.
4. Return JSON with a consistent ``{"status": "success", "data": {...}}`` envelope.
5. Fall back to sample/synthetic data in dev mode (no broker connection required).

Consistent with the existing analysis_routes.py pattern in this package.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from . import broker_registry_reads as broker_reads
from .correlation import CorrelationEngine, make_sample_returns
from .options_payoff import OptionLeg, OptionsPayoffEngine
from .regime_detector import RegimeDetector

logger = logging.getLogger("flinttrade.screener.payoff_routes")

payoff_bp = Blueprint("payoff", __name__, url_prefix="/api/v1")

# Engine singletons (created once per process)
_payoff_engine = OptionsPayoffEngine()
_regime_detector = RegimeDetector()
_correlation_engine = CorrelationEngine(regime_detector=_regime_detector)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_registry() -> Any:
    """Return the BrokerRegistry from the current Flask app config.

    Returns:
        BrokerRegistry instance, or None if not configured.
    """
    return current_app.config.get("REGISTRY")


def _legs_from_body(body: dict[str, Any]) -> list[OptionLeg]:
    """Parse OptionLeg list from request body.

    Args:
        body: Parsed JSON request body.

    Returns:
        List of OptionLeg objects.

    Raises:
        ValueError: If a leg dict is missing required fields or has invalid values.
    """
    raw_legs = body.get("legs", [])
    if not isinstance(raw_legs, list):
        raise ValueError("'legs' must be a list")

    legs: list[OptionLeg] = []
    for i, raw in enumerate(raw_legs):
        if not isinstance(raw, dict):
            raise ValueError(f"leg[{i}] must be an object")
        try:
            legs.append(OptionLeg(**raw))
        except Exception as exc:
            raise ValueError(f"leg[{i}] invalid: {exc}") from exc

    return legs


# ---------------------------------------------------------------------------
# POST /ft-api/v1/payoff/analyse
# ---------------------------------------------------------------------------

@payoff_bp.route("/payoff/analyse", methods=["POST"])
def payoff_analyse() -> Any:
    """Full options payoff analysis.

    Request JSON:
        legs (list): List of option leg objects.  Each leg requires:
            side (str): 'BUY' or 'SELL'.
            option_type (str): 'CE' or 'PE'.
            strike (float): Strike price.
            lots (int): Number of lots.
            premium (float): Entry premium per unit.
            lot_size (int, optional): Lot size (default 1).
        spot (float): Current spot price.
        iv (float, optional): Implied volatility as decimal (default 0.20).
        days_to_expiry (int, optional): Calendar days to expiry (default 30).
        risk_free_rate (float, optional): Risk-free rate as decimal (default 0.065).

    Returns:
        JSON::

            {
              "status": "success",
              "data": {
                "legs": [...],
                "points": [{"spot": f, "pnl": f}, ...],
                "max_profit": float | null,
                "max_loss": float | null,
                "breakevens": [float, ...],
                "net_premium": float,
                "net_delta": float,
                "net_gamma": float,
                "net_theta": float,
                "net_vega": float,
                "pop": float
              }
            }
    """
    body = request.get_json(silent=True) or {}

    try:
        legs = _legs_from_body(body)
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid request"}), 400

    if not legs:
        return jsonify({"status": "error", "message": "At least one leg is required"}), 400

    spot = float(body.get("spot", 24000.0))
    iv = float(body.get("iv", 0.20))
    days_to_expiry = int(body.get("days_to_expiry", 30))
    risk_free_rate = float(body.get("risk_free_rate", 0.065))

    try:
        result = _payoff_engine.calculate(
            legs=legs,
            spot=spot,
            iv=iv,
            days_to_expiry=days_to_expiry,
            risk_free_rate=risk_free_rate,
        )
    except Exception as exc:
        logger.exception("Payoff analysis failed: %s", exc)
        return jsonify({"status": "error", "message": "Payoff calculation failed"}), 500

    return jsonify({
        "status": "success",
        "data": result.model_dump(),
    })


# ---------------------------------------------------------------------------
# POST /ft-api/v1/payoff/curve
# ---------------------------------------------------------------------------

@payoff_bp.route("/payoff/curve", methods=["POST"])
def payoff_curve() -> Any:
    """P&L curve at expiry (lightweight — no Greeks, no POP).

    Request JSON:
        legs (list): Same format as /payoff/analyse.
        spot (float): Reference spot for range calculation.
        n_points (int, optional): Curve resolution (default 200, max 500).
        spot_range (list[float, float], optional): [low, high] range override.

    Returns:
        JSON::

            {
              "status": "success",
              "data": {
                "points": [{"spot": f, "pnl": f}, ...],
                "net_premium": float
              }
            }
    """
    body = request.get_json(silent=True) or {}

    try:
        legs = _legs_from_body(body)
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid request"}), 400

    if not legs:
        return jsonify({"status": "error", "message": "At least one leg is required"}), 400

    spot = float(body.get("spot", 24000.0))
    n_points = min(500, int(body.get("n_points", 200)))

    # Optional explicit spot range
    raw_range = body.get("spot_range")
    if (
        isinstance(raw_range, (list, tuple))
        and len(raw_range) == 2
        and float(raw_range[0]) < float(raw_range[1])
    ):
        spot_range = (float(raw_range[0]), float(raw_range[1]))
    else:
        spot_range = (spot * 0.7, spot * 1.3)

    try:
        points = _payoff_engine.payoff_at_expiry(legs, spot_range=spot_range, n_points=n_points)
        net_premium = sum(
            (1 if leg.side == "SELL" else -1) * leg.premium * leg.quantity
            for leg in legs
        )
    except Exception as exc:
        logger.exception("Payoff curve failed: %s", exc)
        return jsonify({"status": "error", "message": "Curve calculation failed"}), 500

    return jsonify({
        "status": "success",
        "data": {
            "points": [p.model_dump() for p in points],
            "net_premium": round(net_premium, 2),
        },
    })


# ---------------------------------------------------------------------------
# GET /ft-api/v1/regime/current
# ---------------------------------------------------------------------------

@payoff_bp.route("/regime/current", methods=["GET"])
def regime_current() -> Any:
    """Current market regime signal.

    Query params:
        vix (float): Current VIX level (default 15.0).
        advance (int): Advances count for A/D ratio (optional).
        decline (int): Declines count for A/D ratio (optional).
        fii_net (float): Net FII flow in crores (optional).
        breadth (float): % stocks above 200 DMA (optional).
        dxy (float): US Dollar Index level (optional).

    Returns:
        JSON::

            {
              "status": "success",
              "data": {
                "regime": str,
                "confidence": float,
                "vix_level": float,
                "vix_percentile": float,
                "dxy_level": float | null,
                "advance_decline_ratio": float | null,
                "fii_dii_net": float | null,
                "breadth": float | null,
                "rationale": str
              }
            }
    """
    vix = float(request.args.get("vix", 15.0))
    dxy_raw = request.args.get("dxy")
    dxy_level = float(dxy_raw) if dxy_raw is not None else None
    fii_raw = request.args.get("fii_net")
    fii_net = float(fii_raw) if fii_raw is not None else None
    breadth_raw = request.args.get("breadth")
    breadth = float(breadth_raw) if breadth_raw is not None else None

    # Build advance/decline tuple if both params provided
    advance_raw = request.args.get("advance")
    decline_raw = request.args.get("decline")
    advance_decline: tuple[int, int] | None = None
    if advance_raw is not None and decline_raw is not None:
        try:
            advance_decline = (int(advance_raw), int(decline_raw))
        except ValueError:
            pass

    # Attempt to pull live VIX and FII data from registry if available
    registry = _get_registry()
    nifty_returns: list[float] = []
    if registry and registry.is_connected():
        try:
            hist = broker_reads.get_history(
                registry,
                symbol="NIFTY",
                exchange="NSE_INDEX",
                interval="1d",
                days=25,
            )
            candles = hist.get("candles", [])
            closes = [float(c.get("close", 0)) for c in candles if c.get("close")]
            if len(closes) >= 2:
                nifty_returns = [
                    (closes[i] - closes[i - 1]) / closes[i - 1]
                    for i in range(1, len(closes))
                ]
        except Exception as exc:
            logger.debug("Could not fetch Nifty history for regime: %s", exc)

    try:
        signal = _regime_detector.detect(
            vix=vix,
            nifty_returns=nifty_returns,
            advance_decline=advance_decline,
            fii_net=fii_net,
            breadth=breadth,
            dxy_level=dxy_level,
        )
    except Exception as exc:
        logger.exception("Regime detection failed: %s", exc)
        return jsonify({"status": "error", "message": "Regime detection failed"}), 500

    return jsonify({
        "status": "success",
        "data": signal.model_dump(),
    })


# ---------------------------------------------------------------------------
# POST /ft-api/v1/analytics/correlation
# ---------------------------------------------------------------------------

@payoff_bp.route("/analytics/correlation", methods=["GET", "POST"])
def correlation_matrix() -> Any:
    """Correlation matrix for a set of instruments.

    Accepts both GET (query params) and POST (JSON body) for flexibility.

    Request JSON (POST) / Query params (GET):
        symbols (list[str], optional): Symbol list.  Defaults to 6 benchmark symbols.
        period (int, optional): Look-back days (default 90).
        vix (float, optional): Current VIX (default 15.0).
        fii_net (float, optional): Net FII flow in crores.
        advance (int, optional): Advances count.
        decline (int, optional): Declines count.
        breadth (float, optional): % above 200 DMA.

    Returns:
        JSON matching the CorrelationResponse TypeScript interface::

            {
              "status": "success",
              "data": {
                "symbols": [str, ...],
                "matrix": [[float, ...], ...],
                "regime": str,
                "regime_rationale": str,
                "vix": float,
                "dxy": float | null,
                "updated_at": str,   // ISO-format UTC
                "is_sample_data": bool,
                "period_days": int
              }
            }
    """
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
    else:
        body = dict(request.args)

    # Resolve symbols
    symbols_raw = body.get("symbols", [])
    if isinstance(symbols_raw, str):
        symbols_raw = [s.strip() for s in symbols_raw.split(",") if s.strip()]
    if not isinstance(symbols_raw, list) or not symbols_raw:
        symbols_raw = []

    period = int(body.get("period", 90))
    vix = float(body.get("vix", 15.0))
    fii_raw = body.get("fii_net")
    fii_net = float(fii_raw) if fii_raw is not None else None
    breadth_raw = body.get("breadth")
    breadth = float(breadth_raw) if breadth_raw is not None else None

    advance_raw = body.get("advance")
    decline_raw = body.get("decline")
    advance_decline: tuple[int, int] | None = None
    if advance_raw is not None and decline_raw is not None:
        try:
            advance_decline = (int(advance_raw), int(decline_raw))
        except (ValueError, TypeError):
            pass

    # Attempt live return data from registry
    is_sample_data = False
    returns: dict[str, list[float]] = {}
    registry = _get_registry()

    if registry and registry.is_connected() and symbols_raw:
        for sym in symbols_raw:
            try:
                hist = broker_reads.get_history(
                    registry,
                    symbol=sym,
                    exchange="NSE_INDEX",
                    interval="1d",
                    days=period + 5,
                )
                candles = hist.get("candles", [])
                closes = [float(c.get("close", 0)) for c in candles if c.get("close")]
                if len(closes) >= 5:
                    rets = [
                        (closes[i] - closes[i - 1]) / closes[i - 1]
                        for i in range(1, len(closes))
                    ]
                    returns[sym] = rets[-period:]
            except Exception as exc:
                logger.debug("History fetch failed for %s: %s", sym, exc)

    if not returns:
        is_sample_data = True
        use_syms = symbols_raw or None
        returns = make_sample_returns(n_days=period, symbols=use_syms)
        logger.info("Correlation: using sample return data")

    try:
        result = _correlation_engine.compute(
            returns=returns,
            period=period,
            vix=vix,
            fii_net=fii_net,
            advance_decline=advance_decline,
            breadth=breadth,
        )
    except Exception as exc:
        logger.exception("Correlation computation failed: %s", exc)
        return jsonify({"status": "error", "message": "Correlation computation failed"}), 500

    # Build response in the shape expected by the TypeScript CorrelationResponse interface
    regime_signal = result.regime
    # Map RegimeType → MarketRegime string expected by the frontend
    _regime_display_map: dict[str, str] = {
        "risk_on": "Risk-On",
        "risk_off": "Risk-Off",
        "rotation": "Rotation",
        "trending_up": "Risk-On",       # Map trending_up → Risk-On for frontend compat
        "trending_down": "Risk-Off",    # Map trending_down → Risk-Off
        "volatile": "Risk-Off",
        "calm": "Risk-On",
    }
    regime_display = _regime_display_map.get(regime_signal.regime.value, "Rotation")

    return jsonify({
        "status": "success",
        "data": {
            "symbols": result.symbols,
            "matrix": result.matrix,
            "regime": regime_display,
            "regime_rationale": regime_signal.rationale,
            "vix": regime_signal.vix_level,
            "dxy": regime_signal.dxy_level,
            "updated_at": result.updated_at,
            "is_sample_data": is_sample_data,
            "period_days": result.period_days,
        },
    })
