"""Flask blueprint for FlintTrade analysis endpoints.

Provides 8 endpoints under /api/v1/ for the analysis tools:
    - POST /api/v1/gex
    - POST /api/v1/volsurface
    - POST /api/v1/ivsmile
    - POST /api/v1/straddlepnl
    - POST /api/v1/oiprofile
    - POST /api/v1/maxpain
    - GET  /api/v1/rrg/sectors
    - GET  /api/v1/screener/fii-dii

All endpoints:
1. Extract params from the JSON request body (or query string for GET).
2. Attempt to get live data from the BrokerRegistry (if connected).
3. Fall back to sample/synthetic data when no broker is connected (dev mode).
4. Call the relevant screener calculation function.
5. Return the result as JSON.

The BrokerRegistry is retrieved from ``current_app.config["REGISTRY"]`` which
is set up by ``create_flask_app()`` in packages/core/core/src/app.py.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from .gex import calculate_gex
from .iv_smile import calculate_iv_smile
from .oi_analysis import OIAnalysis
from .oi_profile import calculate_oi_profile
from .option_chain import LOT_SIZES, OptionChainSnapshot, StrikeData
from .rrg import (
    BENCHMARK_EXCHANGE,
    BENCHMARK_SYMBOL,
    NIFTY_SECTORS,
    SECTOR_EXCHANGE,
    _Series,
    build_sector_rrg,
)
from .straddle_pnl import simulate_straddle_pnl
from .vol_surface import calculate_vol_surface

logger = logging.getLogger("flinttrade.screener.analysis_routes")

analysis_bp = Blueprint("analysis", __name__, url_prefix="/api/v1")


# ---------------------------------------------------------------------------
# Expiry param normalisation
#
# The terminal sends `expiry_date` / `expiry_dates`; these handlers historically
# read `expiry` / `expiries`. Accept all variants so a user-selected expiry is
# never silently dropped (which made every OI/GEX/IV panel fall back to a
# hardcoded expiry — see feature audit H7).
# ---------------------------------------------------------------------------


def _body_expiry(body: dict[str, Any], default: str) -> str:
    """Return a single expiry from the request body, accepting any key variant."""
    dates = body.get("expiry_dates") or body.get("expiries")
    return (
        body.get("expiry")
        or body.get("expiry_date")
        or (dates[0] if isinstance(dates, list) and dates else None)
        or default
    )


def _body_expiries(body: dict[str, Any], default: list[str]) -> list[str]:
    """Return a list of expiries from the request body, accepting any key variant."""
    value = body.get("expiries") or body.get("expiry_dates")
    if isinstance(value, list) and value:
        return value
    single = body.get("expiry") or body.get("expiry_date")
    return [single] if single else default


# ---------------------------------------------------------------------------
# Registry access helper
# ---------------------------------------------------------------------------


def _get_registry() -> Any:
    """Return the BrokerRegistry from the current Flask app config.

    Returns:
        BrokerRegistry instance, or None if not configured.
    """
    return current_app.config.get("REGISTRY")


# ---------------------------------------------------------------------------
# Sample data helpers (dev/fallback when no broker connected)
# ---------------------------------------------------------------------------


def _make_sample_strikes(
    spot: float = 24000.0,
    step: float = 100.0,
    count: int = 10,
) -> list[StrikeData]:
    """Generate synthetic strike data for dev/fallback mode.

    Args:
        spot: Center spot price.
        step: Strike step size.
        count: Number of strikes each side of ATM.

    Returns:
        List of StrikeData objects around the given spot.
    """
    strikes: list[StrikeData] = []
    for i in range(-count, count + 1):
        k = spot + i * step
        dist = abs(i)
        ce_oi = max(1000, 50000 - dist * 4000)
        pe_oi = max(1000, 40000 - dist * 3500)
        ce_ltp = max(1.0, 200 - max(0, i) * 15)
        pe_ltp = max(1.0, 200 + min(0, i) * 15)
        iv = 15.0 + dist * 0.6
        gamma = max(0.0001, 0.005 - dist * 0.0003)
        strikes.append(StrikeData(
            strike_price=k,
            ce_ltp=ce_ltp,
            ce_oi=ce_oi,
            ce_volume=ce_oi // 10,
            ce_iv=iv,
            ce_delta=max(0.05, 0.5 - i * 0.05),
            ce_gamma=gamma,
            ce_theta=-5.0 - dist * 0.3,
            ce_vega=10.0 - dist * 0.4,
            pe_ltp=pe_ltp,
            pe_oi=pe_oi,
            pe_volume=pe_oi // 10,
            pe_iv=iv + 0.5,
            pe_delta=-max(0.05, 0.5 + i * 0.05),
            pe_gamma=gamma,
            pe_theta=-5.0 - dist * 0.3,
            pe_vega=10.0 - dist * 0.4,
        ))
    return strikes


def _make_sample_snapshot(
    symbol: str = "NIFTY",
    exchange: str = "NFO",
    spot: float = 24000.0,
    step: float = 100.0,
    count: int = 10,
) -> OptionChainSnapshot:
    """Create a synthetic OptionChainSnapshot for dev/fallback mode.

    Args:
        symbol: Underlying symbol.
        exchange: Exchange code.
        spot: Spot price.
        step: Strike step.
        count: Strikes per side.

    Returns:
        OptionChainSnapshot with synthetic data.
    """
    strikes = _make_sample_strikes(spot=spot, step=step, count=count)
    return OptionChainSnapshot(
        underlying=symbol,
        exchange=exchange,
        spot_price=spot,
        atm_strike=spot,
        strikes=strikes,
    )


def _make_sample_candles(
    spot: float = 24000.0,
    n: int = 48,
    base_ts: int = 1711900000,
    candle_seconds: int = 300,
) -> list[dict[str, Any]]:
    """Generate synthetic futures OHLCV candles for dev/fallback mode.

    Args:
        spot: Starting spot price.
        n: Number of candles.
        base_ts: Base Unix timestamp.
        candle_seconds: Duration per candle in seconds.

    Returns:
        List of OHLCV candle dicts.
    """
    import math
    candles = []
    price = spot
    for i in range(n):
        # Sinusoidal price movement for realistic shape
        move = 50 * math.sin(i * 0.3)
        open_p = price
        close_p = price + move
        high_p = max(open_p, close_p) + abs(move) * 0.2
        low_p = min(open_p, close_p) - abs(move) * 0.2
        candles.append({
            "time": base_ts + i * candle_seconds,
            "open": round(open_p, 2),
            "high": round(high_p, 2),
            "low": round(low_p, 2),
            "close": round(close_p, 2),
            "volume": 10000 + i * 500,
        })
        price = close_p
    return candles


def _dataclass_to_dict(obj: Any) -> Any:
    """Recursively convert dataclass instances to dicts for JSON serialization.

    Args:
        obj: A dataclass instance, list, or primitive value.

    Returns:
        JSON-serializable representation.
    """
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _dataclass_to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [_dataclass_to_dict(item) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# GEX endpoint
# ---------------------------------------------------------------------------


@analysis_bp.route("/gex", methods=["POST"])
def gex_endpoint() -> Any:
    """Gamma Exposure (GEX) calculation.

    Request JSON:
        symbol (str): Underlying symbol (e.g. 'NIFTY').
        exchange (str): Exchange code (e.g. 'NFO').
        expiry (str): Expiry label (e.g. '26MAR26').

    Returns:
        JSON with GEX result or error.
    """
    body = request.get_json(silent=True) or {}
    symbol = body.get("symbol", "NIFTY")
    exchange = body.get("exchange", "NFO")
    expiry = _body_expiry(body, "")

    lot_size = LOT_SIZES.get(symbol.upper(), 50)
    spot = 24000.0
    snapshot: OptionChainSnapshot | None = None

    # Attempt live data via registry
    registry = _get_registry()
    if registry and registry.is_connected():
        try:
            chain_data = registry.get_option_chain(
                symbol=symbol, exchange=exchange, expiry=expiry
            )
            spot = float(chain_data.get("spot", spot))
            snapshot = _snapshot_from_registry_data(chain_data, symbol, exchange, spot)
        except Exception as exc:
            logger.warning("Live GEX data unavailable, using sample: %s", exc)

    if snapshot is None:
        snapshot = _make_sample_snapshot(symbol=symbol, exchange=exchange, spot=spot)
        logger.info("GEX: using sample data for %s %s", symbol, exchange)

    result = calculate_gex(snapshot, spot=spot, lot_size=lot_size)

    # Shape ``data`` to the terminal's GEXData contract. The raw dataclass used
    # strike_price / total_net_gex and lacked atm_strike / gamma_flip_strike /
    # dealer_zone, so the widget read undefined for those.
    frontend_strikes = [
        {
            "strike": gs.strike_price,
            "call_gex": gs.call_gex,
            "put_gex": gs.put_gex,
            "net_gex": gs.net_gex,
            "call_oi": gs.call_oi,
            "put_oi": gs.put_oi,
        }
        for gs in result.strikes
    ]
    atm_strike = (
        min(result.strikes, key=lambda s: abs(s.strike_price - spot)).strike_price
        if result.strikes
        else spot
    )
    # Gamma flip = first strike where net GEX crosses from positive to negative.
    gamma_flip_strike: float | None = None
    for i in range(len(result.strikes) - 1):
        if result.strikes[i].net_gex >= 0 and result.strikes[i + 1].net_gex < 0:
            gamma_flip_strike = result.strikes[i + 1].strike_price
            break
    dealer_zone = "Long Gamma" if result.total_net_gex > 0 else "Short Gamma"

    gex_data = {
        "underlying": symbol,
        "spot_price": spot,
        "atm_strike": atm_strike,
        "strikes": frontend_strikes,
        "gamma_flip_strike": gamma_flip_strike,
        "dealer_zone": dealer_zone,
        "total_call_gex": result.total_call_gex,
        "total_put_gex": result.total_put_gex,
        "net_gex": result.total_net_gex,
    }

    return jsonify({
        "status": "success",
        "symbol": symbol,
        "exchange": exchange,
        "expiry": expiry,
        "spot": spot,
        "lot_size": lot_size,
        "data": gex_data,
        "is_sample_data": snapshot.underlying == symbol and registry is None,
    })


# ---------------------------------------------------------------------------
# Vol Surface endpoint
# ---------------------------------------------------------------------------


@analysis_bp.route("/volsurface", methods=["POST"])
def vol_surface_endpoint() -> Any:
    """Implied Volatility surface calculation.

    Request JSON:
        symbol (str): Underlying symbol.
        exchange (str): Exchange code.
        expiries (list[str]): List of expiry labels.
        strike_count (int): Max strikes in surface grid (default 20).

    Returns:
        JSON with 3-D vol surface data or error.
    """
    body = request.get_json(silent=True) or {}
    symbol = body.get("symbol", "NIFTY")
    exchange = body.get("exchange", "NFO")
    expiries = _body_expiries(body, ["26MAR26", "24APR26"])
    strike_count = int(body.get("strike_count", 20))
    spot = 24000.0

    chains_by_expiry: dict[str, dict] = {}

    registry = _get_registry()
    if registry and registry.is_connected():
        try:
            for expiry in expiries:
                chain_data = registry.get_option_chain(
                    symbol=symbol, exchange=exchange, expiry=expiry
                )
                spot = float(chain_data.get("spot", spot))
                chains_by_expiry[expiry] = _chain_to_vol_surface_format(chain_data, spot)
        except Exception as exc:
            logger.warning("Live vol surface data unavailable, using sample: %s", exc)
            chains_by_expiry = {}

    if not chains_by_expiry:
        chains_by_expiry = _make_sample_chains_by_expiry(spot=spot, expiries=expiries)
        logger.info("VolSurface: using sample data for %s %s", symbol, exchange)

    result = calculate_vol_surface(chains_by_expiry, spot=spot, strike_count=strike_count)

    # Shape ``data`` to the terminal's VolSurfaceData contract (the widget read
    # undefined for expiries/days_to_expiry/atm_strike from the raw dataclass,
    # whose fields are expiry_labels/expiries_dte/atm_ivs).
    atm_strike = min(result.strikes, key=lambda s: abs(s - spot)) if result.strikes else spot
    vol_surface_data = {
        "underlying": symbol,
        "spot_price": spot,
        "strikes": result.strikes,
        "expiries": result.expiry_labels,
        "days_to_expiry": result.expiries_dte,
        "iv_matrix": result.iv_matrix,
        "atm_strike": atm_strike,
    }

    return jsonify({
        "status": "success",
        "symbol": symbol,
        "exchange": exchange,
        "spot": spot,
        "data": vol_surface_data,
    })


# ---------------------------------------------------------------------------
# IV Smile endpoint
# ---------------------------------------------------------------------------


@analysis_bp.route("/ivsmile", methods=["POST"])
def iv_smile_endpoint() -> Any:
    """IV Smile curve extraction.

    Request JSON:
        symbol (str): Underlying symbol.
        exchange (str): Exchange code.
        expiry (str): Expiry label.

    Returns:
        JSON with IV smile data or error.
    """
    body = request.get_json(silent=True) or {}
    symbol = body.get("symbol", "NIFTY")
    exchange = body.get("exchange", "NFO")
    expiry = _body_expiry(body, "26MAR26")
    spot = 24000.0
    snapshot: OptionChainSnapshot | None = None

    registry = _get_registry()
    if registry and registry.is_connected():
        try:
            chain_data = registry.get_option_chain(
                symbol=symbol, exchange=exchange, expiry=expiry
            )
            spot = float(chain_data.get("spot", spot))
            snapshot = _snapshot_from_registry_data(chain_data, symbol, exchange, spot)
        except Exception as exc:
            logger.warning("Live IV smile data unavailable, using sample: %s", exc)

    if snapshot is None:
        snapshot = _make_sample_snapshot(symbol=symbol, exchange=exchange, spot=spot)
        logger.info("IVSmile: using sample data for %s %s", symbol, exchange)

    result = calculate_iv_smile(snapshot, spot=spot, expiry_date=expiry)

    # Shape ``data`` to the terminal's IVSmileData contract: a single expiry's
    # flat dataclass becomes one entry in a ``curves`` array of per-strike points.
    # (The widget read `curves`/`points` and got undefined from the raw dataclass.)
    curve = {
        "expiry": result.expiry_date or expiry,
        "days_to_expiry": 0,  # not derived for a single-expiry smile
        "atm_iv": result.atm_iv,
        "atm_strike": result.atm_strike,
        "skew_25delta": result.skew,
        "points": [
            {
                "strike": p.strike_price,
                "call_iv": p.call_iv,
                "put_iv": p.put_iv,
                "moneyness": p.moneyness,
            }
            for p in result.points
        ],
    }
    iv_smile_data = {
        "underlying": symbol,
        "spot_price": spot,
        "curves": [curve],
    }

    return jsonify({
        "status": "success",
        "symbol": symbol,
        "exchange": exchange,
        "expiry": expiry,
        "spot": spot,
        "data": iv_smile_data,
    })


# ---------------------------------------------------------------------------
# Straddle P&L endpoint
# ---------------------------------------------------------------------------


@analysis_bp.route("/straddlepnl", methods=["POST"])
def straddle_pnl_endpoint() -> Any:
    """Straddle P&L simulation with re-hedging.

    Request JSON:
        symbol (str): Underlying symbol.
        exchange (str): Exchange code.
        expiry (str): Expiry label.
        interval (str): Candle interval (e.g. '5m', '15m').
        adjustment_points (float): P&L drawdown triggering re-hedge.
        strike (float, optional): Straddle strike. Default: ATM.
        ce_premium (float, optional): CE premium. Default: synthetic.
        pe_premium (float, optional): PE premium. Default: synthetic.

    Returns:
        JSON with P&L series, adjustments, and summary stats.
    """
    body = request.get_json(silent=True) or {}
    symbol = body.get("symbol", "NIFTY")
    exchange = body.get("exchange", "NFO")
    expiry = _body_expiry(body, "26MAR26")
    interval = body.get("interval", "5m")
    adjustment_points = float(body.get("adjustment_points", 50.0))
    lot_size = LOT_SIZES.get(symbol.upper(), 50)
    spot = 24000.0

    strike = float(body.get("strike", spot))
    ce_premium = float(body.get("ce_premium", 0.0))
    pe_premium = float(body.get("pe_premium", 0.0))
    candles: list[dict[str, Any]] = []

    registry = _get_registry()
    if registry and registry.is_connected():
        try:
            hist = registry.get_history(
                symbol=symbol, exchange=exchange,
                interval=interval, days=1,
            )
            candles = hist.get("candles", [])
            spot = float(hist.get("spot", spot))
        except Exception as exc:
            logger.warning("Live straddle candle data unavailable, using sample: %s", exc)

    if not candles:
        candles = _make_sample_candles(spot=spot)
        logger.info("StraddlePnL: using sample candle data for %s", symbol)

    # Default strike/premiums from sample data if not provided
    if strike <= 0:
        strike = round(spot / 50) * 50
    if ce_premium <= 0:
        ce_premium = spot * 0.01  # ~1% of spot as rough ATM premium
    if pe_premium <= 0:
        pe_premium = spot * 0.0105  # slightly higher puts for skew

    result = simulate_straddle_pnl(
        candles=candles,
        strike=strike,
        ce_premium=ce_premium,
        pe_premium=pe_premium,
        adjustment_points=adjustment_points,
        lot_size=lot_size,
    )

    # Augment with the terminal's StraddlePnLData contract. The widget plots a
    # long-straddle PAYOFF DIAGRAM (P&L at expiry vs underlying price) — a
    # different object from the dataclass's intraday P&L time series, which is
    # retained for any other consumer. The payoff is analytic from the legs:
    # per unit at expiry, pnl(S) = |S - strike| - (ce_premium + pe_premium).
    total_premium = ce_premium + pe_premium
    lo, hi, steps = strike * 0.9, strike * 1.1, 41
    payoff_curve = []
    for i in range(steps):
        s = lo + (hi - lo) * i / (steps - 1)
        payoff_curve.append({
            "spot_price": round(s, 2),
            "pnl": round(lot_size * (abs(s - strike) - total_premium), 2),
        })
    data = _dataclass_to_dict(result)
    data.update({
        "underlying": symbol,
        "atm_strike": strike,
        "call_premium": ce_premium,
        "put_premium": pe_premium,
        "break_even_low": strike - total_premium,
        "break_even_high": strike + total_premium,
        "max_loss": -total_premium * lot_size,
        "curve": payoff_curve,
        "legs": [
            {"strike": strike, "type": "CE", "action": "BUY", "premium": ce_premium, "lots": 1},
            {"strike": strike, "type": "PE", "action": "BUY", "premium": pe_premium, "lots": 1},
        ],
    })

    return jsonify({
        "status": "success",
        "symbol": symbol,
        "exchange": exchange,
        "expiry": expiry,
        "interval": interval,
        "spot": spot,
        "data": data,
    })


# ---------------------------------------------------------------------------
# OI Profile endpoint
# ---------------------------------------------------------------------------


@analysis_bp.route("/oiprofile", methods=["POST"])
def oi_profile_endpoint() -> Any:
    """OI Profile with butterfly analysis.

    Request JSON:
        symbol (str): Underlying symbol.
        exchange (str): Exchange code.
        expiry (str): Expiry label.
        interval (str): Futures candle interval.

    Returns:
        JSON with OI profile data, butterfly, and futures OHLCV.
    """
    body = request.get_json(silent=True) or {}
    symbol = body.get("symbol", "NIFTY")
    exchange = body.get("exchange", "NFO")
    expiry = _body_expiry(body, "26MAR26")
    interval = body.get("interval", "5m")
    spot = 24000.0
    snapshot: OptionChainSnapshot | None = None
    futures_candles: list[dict[str, Any]] = []

    registry = _get_registry()
    if registry and registry.is_connected():
        try:
            chain_data = registry.get_option_chain(
                symbol=symbol, exchange=exchange, expiry=expiry
            )
            spot = float(chain_data.get("spot", spot))
            snapshot = _snapshot_from_registry_data(chain_data, symbol, exchange, spot)
            hist = registry.get_history(
                symbol=symbol + "FUT", exchange=exchange,
                interval=interval, days=1,
            )
            futures_candles = hist.get("candles", [])
        except Exception as exc:
            logger.warning("Live OI profile data unavailable, using sample: %s", exc)

    if snapshot is None:
        snapshot = _make_sample_snapshot(symbol=symbol, exchange=exchange, spot=spot)
        logger.info("OIProfile: using sample data for %s %s", symbol, exchange)

    if not futures_candles:
        futures_candles = _make_sample_candles(spot=spot)

    result = calculate_oi_profile(snapshot, futures_candles=futures_candles)

    # Augment the raw dataclass with the terminal's OIProfileData contract. The
    # widget reads per-strike OBJECTS (strike/ce_oi/pe_oi/…) plus atm_strike,
    # max_pain_strike, total_ce_oi/pe_oi and pcr — none of which the column-
    # oriented dataclass exposed, so it rendered undefined. The dataclass's own
    # keys (oi_butterfly, oi_change, futures_ohlcv, …) are retained for any other
    # consumer; only ``strikes`` is overridden from a float list to the objects.
    data = _dataclass_to_dict(result)
    total_ce_oi = sum(result.ce_oi)
    total_pe_oi = sum(result.pe_oi)
    data.update({
        "underlying": symbol,
        "expiry": expiry,
        "spot_price": spot,
        "atm_strike": snapshot.atm_strike,
        "max_pain_strike": OIAnalysis.max_pain(snapshot).max_pain_strike,
        "strikes": [
            {
                "strike": ps.strike_price,
                "ce_oi": ps.ce_oi,
                "pe_oi": ps.pe_oi,
                "ce_oi_change": ps.ce_oi_change,
                "pe_oi_change": ps.pe_oi_change,
            }
            for ps in result.profile_strikes
        ],
        "total_ce_oi": total_ce_oi,
        "total_pe_oi": total_pe_oi,
        "pcr": (total_pe_oi / total_ce_oi) if total_ce_oi else 0.0,
    })

    return jsonify({
        "status": "success",
        "symbol": symbol,
        "exchange": exchange,
        "expiry": expiry,
        "spot": spot,
        "data": data,
    })


# ---------------------------------------------------------------------------
# Max Pain endpoint
# ---------------------------------------------------------------------------


@analysis_bp.route("/maxpain", methods=["POST"])
def max_pain_endpoint() -> Any:
    """Max Pain strike calculation.

    Request JSON:
        symbol (str): Underlying symbol.
        exchange (str): Exchange code.
        expiry (str): Expiry label.

    Returns:
        JSON with max pain strike, total loss at max pain, and per-strike losses.
    """
    body = request.get_json(silent=True) or {}
    symbol = body.get("symbol", "NIFTY")
    exchange = body.get("exchange", "NFO")
    expiry = _body_expiry(body, "26MAR26")
    spot = 24000.0
    snapshot: OptionChainSnapshot | None = None

    registry = _get_registry()
    if registry and registry.is_connected():
        try:
            chain_data = registry.get_option_chain(
                symbol=symbol, exchange=exchange, expiry=expiry
            )
            spot = float(chain_data.get("spot", spot))
            snapshot = _snapshot_from_registry_data(chain_data, symbol, exchange, spot)
        except Exception as exc:
            logger.warning("Live max pain data unavailable, using sample: %s", exc)

    if snapshot is None:
        snapshot = _make_sample_snapshot(symbol=symbol, exchange=exchange, spot=spot)
        logger.info("MaxPain: using sample data for %s %s", symbol, exchange)

    result = OIAnalysis.max_pain(snapshot)

    return jsonify({
        "status": "success",
        "symbol": symbol,
        "exchange": exchange,
        "expiry": expiry,
        "spot": spot,
        "data": {
            "max_pain_strike": result.max_pain_strike,
            "total_loss_at_max_pain": result.total_loss_at_max_pain,
            "strike_losses": result.strike_losses,
        },
    })


# ---------------------------------------------------------------------------
# RRG endpoint
# ---------------------------------------------------------------------------


def _make_sample_rrg_series(
    symbol: str,
    n_weeks: int = 60,
    base_level: float = 100.0,
    drift: float = 0.0,
    noise: float = 1.2,
) -> _Series:
    """Generate synthetic weekly close-price series for dev/fallback RRG.

    Prices are a random walk around base_level, seeded deterministically from
    the symbol string so the same symbol always produces the same sample path
    (reproducible dev mode).

    Args:
        symbol: Sector or benchmark symbol (used to seed the RNG).
        n_weeks: Number of weekly bars to generate.
        base_level: Starting index level (default 100 = relative to benchmark).
        drift: Weekly drift in percent (default 0 = no trend).
        noise: Weekly volatility in percent (default 1.2%).

    Returns:
        _Series with ISO-format weekly date strings and synthetic closes.
    """
    import hashlib
    import random
    from datetime import date, timedelta

    # Deterministic seed from symbol name so results are reproducible
    seed = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)

    # Weekly bars ending today, going backwards
    today = date.today()
    # Find nearest Monday
    monday = today - timedelta(days=today.weekday())
    dates: list[str] = []
    for i in range(n_weeks - 1, -1, -1):
        week_start = monday - timedelta(weeks=i)
        dates.append(week_start.isoformat())

    price = base_level
    prices: list[float] = []
    for _ in dates:
        change_pct = drift / 100.0 + rng.gauss(0, noise / 100.0)
        price = max(10.0, price * (1 + change_pct))
        prices.append(round(price, 2))

    return _Series(dates=dates, values=prices)


@analysis_bp.route("/rrg/sectors", methods=["GET"])
def rrg_sectors_endpoint() -> Any:
    """Relative Rotation Graph data for all 12 NIFTY sector indices.

    Query params:
        tail_length (int): Number of weekly tail points to return (default 12).
        interval (str): Price history interval — 'W' weekly (default) or '1M' monthly.

    Returns:
        JSON with list of SectorRRG objects plus benchmark info:
        {
          "status": "success",
          "benchmark": "NIFTY 50",
          "tail_length": 12,
          "is_sample_data": bool,
          "sectors": [ { symbol, name, tail: [{date, rs_ratio, rs_momentum}], current_quadrant }, ... ]
        }

    Notes:
        - Uses OpenAlgo /history endpoint (weekly) when broker is connected.
        - Falls back to deterministic synthetic data in dev/disconnected mode.
        - Benchmark is always NIFTY 50 (NSE_INDEX).
    """
    tail_length = int(request.args.get("tail_length", 12))
    # Clamp tail to 4-52 range
    tail_length = max(4, min(52, tail_length))
    n_bars = max(60, tail_length + 52)  # need enough history for 52-bar z-score window

    is_sample_data = True
    sector_prices: dict[str, _Series] = {}
    benchmark_prices: _Series | None = None

    registry = _get_registry()
    if registry and registry.is_connected():
        try:
            from datetime import date, timedelta  # noqa: PLC0415
            end_date = date.today().isoformat()
            start_date = (date.today() - timedelta(weeks=n_bars + 4)).isoformat()

            # Fetch benchmark (NIFTY 50) weekly history
            bench_hist = registry.get_history(
                symbol=BENCHMARK_SYMBOL,
                exchange=BENCHMARK_EXCHANGE,
                interval="W",
                start_date=start_date,
                end_date=end_date,
            )
            bench_candles = bench_hist.get("candles", [])
            if bench_candles:
                benchmark_prices = _candles_to_series(bench_candles)

            # Fetch each sector's weekly history
            if benchmark_prices:
                for symbol, _name in NIFTY_SECTORS:
                    try:
                        sec_hist = registry.get_history(
                            symbol=symbol,
                            exchange=SECTOR_EXCHANGE,
                            interval="W",
                            start_date=start_date,
                            end_date=end_date,
                        )
                        candles = sec_hist.get("candles", [])
                        if candles:
                            sector_prices[symbol] = _candles_to_series(candles)
                    except Exception as exc:
                        logger.warning("RRG: sector %s history failed: %s", symbol, exc)

                if len(sector_prices) >= 3:
                    is_sample_data = False

        except Exception as exc:
            logger.warning("RRG: live history unavailable, using sample data: %s", exc)
            sector_prices = {}
            benchmark_prices = None

    # Fall back to synthetic data
    if is_sample_data or benchmark_prices is None:
        logger.info("RRG: using synthetic sample data")
        benchmark_prices = _make_sample_rrg_series(
            BENCHMARK_SYMBOL, n_weeks=n_bars, base_level=24000.0, drift=0.08, noise=1.5
        )
        # Each sector drifts differently so they end up in different quadrants
        sector_drifts = [0.12, 0.05, 0.09, -0.02, 0.15, -0.08, 0.03, 0.10, 0.01, -0.05, 0.07, 0.11]
        for i, (symbol, _name) in enumerate(NIFTY_SECTORS):
            drift = sector_drifts[i % len(sector_drifts)]
            sector_prices[symbol] = _make_sample_rrg_series(
                symbol, n_weeks=n_bars, base_level=24000.0, drift=drift, noise=1.8
            )

    results = build_sector_rrg(sector_prices, benchmark_prices, tail_length=tail_length)

    return jsonify({
        "status": "success",
        "data": {
            "benchmark": BENCHMARK_SYMBOL,
            "tail_length": tail_length,
            "is_sample_data": is_sample_data,
            "sectors": results,
        },
    })


def _candles_to_series(candles: list[dict[str, Any]]) -> _Series:
    """Convert OpenAlgo OHLCV candle list to a dated close-price _Series.

    Candle format: {"time": unix_ts, "open": f, "high": f, "low": f, "close": f, "volume": i}
    or {"timestamp": unix_ts, ...} — handles both field names.

    Args:
        candles: List of OHLCV candle dicts from registry.get_history().

    Returns:
        _Series with ISO date strings and close prices, sorted ascending.
    """
    from datetime import datetime, timezone  # noqa: PLC0415

    dates: list[str] = []
    closes: list[float] = []

    for c in candles:
        ts_raw = c.get("time", c.get("timestamp"))
        close = float(c.get("close", 0))
        if ts_raw is None or close <= 0:
            continue
        try:
            ts = int(ts_raw)
            # Handle millisecond timestamps (> year 2100 in seconds)
            if ts > 4_102_444_800:
                ts = ts // 1000
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            dates.append(dt.date().isoformat())
            closes.append(close)
        except (ValueError, OSError):
            continue

    # Sort ascending by date
    paired = sorted(zip(dates, closes), key=lambda x: x[0])
    if not paired:
        return _Series(dates=[], values=[])
    sorted_dates, sorted_closes = zip(*paired)
    return _Series(dates=list(sorted_dates), values=list(sorted_closes))


# ---------------------------------------------------------------------------
# Internal helpers: registry data → screener models
# ---------------------------------------------------------------------------


def _snapshot_from_registry_data(
    chain_data: dict[str, Any],
    symbol: str,
    exchange: str,
    spot: float,
) -> OptionChainSnapshot:
    """Convert BrokerRegistry option chain response to OptionChainSnapshot.

    Args:
        chain_data: Raw chain response dict from registry.
        symbol: Underlying symbol.
        exchange: Exchange code.
        spot: Spot price.

    Returns:
        OptionChainSnapshot populated from the registry data.
    """
    raw_strikes = chain_data.get("strikes", [])
    strike_data_list: list[StrikeData] = []

    for row in raw_strikes:
        k = float(row.get("strike_price", row.get("strike", 0)))
        if k <= 0:
            continue
        sd = StrikeData(
            strike_price=k,
            ce_ltp=float(row.get("ce_ltp", 0)),
            ce_oi=int(row.get("ce_oi", 0)),
            ce_volume=int(row.get("ce_volume", 0)),
            ce_iv=float(row.get("ce_iv", 0)),
            ce_delta=float(row.get("ce_delta", 0)),
            ce_gamma=float(row.get("ce_gamma", 0)),
            ce_theta=float(row.get("ce_theta", 0)),
            ce_vega=float(row.get("ce_vega", 0)),
            pe_ltp=float(row.get("pe_ltp", 0)),
            pe_oi=int(row.get("pe_oi", 0)),
            pe_volume=int(row.get("pe_volume", 0)),
            pe_iv=float(row.get("pe_iv", 0)),
            pe_delta=float(row.get("pe_delta", 0)),
            pe_gamma=float(row.get("pe_gamma", 0)),
            pe_theta=float(row.get("pe_theta", 0)),
            pe_vega=float(row.get("pe_vega", 0)),
        )
        strike_data_list.append(sd)

    return OptionChainSnapshot(
        underlying=symbol,
        exchange=exchange,
        spot_price=spot,
        atm_strike=spot,
        strikes=strike_data_list,
    )


def _chain_to_vol_surface_format(
    chain_data: dict[str, Any],
    spot: float,
) -> dict[str, Any]:
    """Convert BrokerRegistry chain response to vol surface input format.

    Args:
        chain_data: Raw chain response dict.
        spot: Spot price.

    Returns:
        Dict with 'dte', 'spot', and 'strikes' for vol surface calculation.
    """
    return {
        "dte": int(chain_data.get("days_to_expiry", chain_data.get("dte", 7))),
        "spot": spot,
        "strikes": [
            {
                "strike": float(r.get("strike_price", r.get("strike", 0))),
                "ce_ltp": float(r.get("ce_ltp", 0)),
                "pe_ltp": float(r.get("pe_ltp", 0)),
                "ce_iv": float(r.get("ce_iv", 0)),
                "pe_iv": float(r.get("pe_iv", 0)),
            }
            for r in chain_data.get("strikes", [])
        ],
    }


def _make_sample_chains_by_expiry(
    spot: float,
    expiries: list[str],
) -> dict[str, dict[str, Any]]:
    """Generate sample vol surface input for dev/fallback mode.

    Args:
        spot: Spot price.
        expiries: List of expiry labels.

    Returns:
        ChainsByExpiry dict with synthetic multi-expiry data.
    """
    base_dtes = [7, 30, 60, 90, 120]
    result: dict[str, dict[str, Any]] = {}

    for i, expiry in enumerate(expiries):
        dte = base_dtes[i] if i < len(base_dtes) else (i + 1) * 30
        iv_base = 15.0 + i * 1.5  # term structure: longer expiry = higher IV
        strikes_data = []
        for j in range(-10, 11):
            k = spot + j * 100
            dist = abs(j)
            iv = iv_base + dist * 0.6
            strikes_data.append({
                "strike": k,
                "ce_ltp": max(1.0, 200 - max(0, j) * 15),
                "pe_ltp": max(1.0, 200 + min(0, j) * 15),
                "ce_iv": iv,
                "pe_iv": iv + 0.5,
            })
        result[expiry] = {"dte": dte, "spot": spot, "strikes": strikes_data}

    return result


# ---------------------------------------------------------------------------
# FII/DII endpoint (absorbed from MarketCalls/fii-dii-data)
# ---------------------------------------------------------------------------


@analysis_bp.route("/screener/fii-dii", methods=["GET"])
def fii_dii_endpoint() -> Any:
    """FII/DII institutional flow data.

    Fetches latest FII/DII cash and F&O data from NSE, caches in DuckDB,
    and returns the result.  Pattern absorbed from MarketCalls/fii-dii-data.

    Query params:
        days (int): Number of days for trend data (default 1 = latest only).
            Use ``days=30`` to get the last 30 trading days.
        refresh (bool): Force a fresh fetch from NSE (default false).

    Returns:
        JSON with latest FII/DII snapshot and optional trend data:
        {
          "status": "success",
          "is_sample_data": bool,
          "latest": { ... FiiDiiSnapshot fields ... },
          "trend": { ... FiiDiiTrend fields ... } | null
        }
    """
    from .fii_dii import (  # noqa: PLC0415
        FiiDiiTracker,
        make_sample_fii_dii,
        make_sample_trend,
    )

    days = int(request.args.get("days", 1))
    days = max(1, min(200, days))
    force_refresh = request.args.get("refresh", "false").lower() in ("true", "1", "yes")

    is_sample_data = False
    tracker: FiiDiiTracker | None = None
    latest = None

    try:
        tracker = FiiDiiTracker()

        if force_refresh:
            latest = tracker.fetch_latest()
        else:
            latest = tracker.get_latest_cached()
            if latest is None:
                latest = tracker.fetch_latest()

    except Exception as exc:
        logger.warning("FII/DII live data unavailable: %s", exc)

    if latest is None:
        is_sample_data = True
        latest = make_sample_fii_dii()
        logger.info("FII/DII: using sample data")

    trend_data = None
    if days > 1:
        if tracker is not None and not is_sample_data:
            try:
                trend = tracker.get_trend(days=days)
                trend_data = trend.to_dict()
            except Exception as exc:
                logger.warning("FII/DII trend query failed: %s", exc)
                trend_data = make_sample_trend(days=days).to_dict()
                is_sample_data = True
        else:
            trend_data = make_sample_trend(days=days).to_dict()

    if tracker is not None:
        tracker.close()

    return jsonify({
        "status": "success",
        "data": {
            "is_sample_data": is_sample_data,
            "latest": latest.to_dict(),
            "trend": trend_data,
        },
    })
