"""Flask blueprint for the declarative Market Scanner endpoints.

External URLs (frontend calls these via /ft-api/v1/scanner/*; the WSGI prefix
stripper in app.py rewrites to /v1/scanner/* before Flask dispatch):

    POST /ft-api/v1/scanner/run      — Run a scan (prebuilt or ad-hoc config)
    GET  /ft-api/v1/scanner/prebuilt — List all prebuilt scan configurations
    POST /ft-api/v1/scanner/custom   — Validate and echo a custom ScanConfig

Blueprint registered at ``/v1/scanner`` (post-strip form).

All scan runs use synthetic sample OHLCV data when no broker is connected,
so the frontend scanner widget works in Explore mode without live data.
"""

from __future__ import annotations

import logging
import random
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from .market_scanner import (
    PREBUILT_SCANS,
    MarketScanner,
    ScanConfig,
    ScanResult,
)

logger = logging.getLogger("flinttrade.screener.scanner_routes")

scanner_bp = Blueprint("scanner", __name__, url_prefix="/v1/scanner")

# Module-level scanner instance (stateless — safe to share across requests)
_scanner = MarketScanner()


# ---------------------------------------------------------------------------
# Sample data generation (dev / Explore mode)
# ---------------------------------------------------------------------------


def _make_sample_ohlcv(
    symbol: str,
    n: int = 260,
    base_price: float = 1000.0,
) -> list[dict[str, Any]]:
    """Generate deterministic synthetic OHLCV data for a symbol.

    Uses a seeded random walk so the same symbol always produces the same
    sample path, making Explore mode fully reproducible.

    Args:
        symbol:     Symbol name (used as RNG seed).
        n:          Number of bars to generate (default 260 ≈ 1 trading year).
        base_price: Starting price.

    Returns:
        List of OHLCV dicts oldest-to-newest.
    """
    seed = sum(ord(c) for c in symbol)
    rng = random.Random(seed)
    price = base_price
    bars: list[dict[str, Any]] = []
    avg_vol = rng.randint(100_000, 2_000_000)

    for i in range(n):
        drift = rng.gauss(0.0002, 0.015)
        close = max(10.0, price * (1 + drift))
        open_p = price * (1 + rng.gauss(0, 0.005))
        high_p = max(open_p, close) * (1 + abs(rng.gauss(0, 0.005)))
        low_p = min(open_p, close) * (1 - abs(rng.gauss(0, 0.005)))
        # Occasional volume spikes
        vol_mult = rng.choices([1.0, 2.5, 4.0], weights=[85, 12, 3])[0]
        volume = int(avg_vol * vol_mult * rng.uniform(0.7, 1.3))
        bars.append({
            "open": round(open_p, 2),
            "high": round(high_p, 2),
            "low": round(low_p, 2),
            "close": round(close, 2),
            "volume": volume,
        })
        price = close

    return bars


def _sample_data_fetcher(
    symbol: str,
    exchange: str,  # noqa: ARG001
    timeframe: str,  # noqa: ARG001
) -> list[dict[str, Any]]:
    """Fallback data fetcher that returns synthetic OHLCV for any symbol.

    Args:
        symbol:    NSE symbol string.
        exchange:  Exchange (ignored — all sample data is synthetic).
        timeframe: Timeframe (ignored — always daily bars).

    Returns:
        260 synthetic daily OHLCV bars.
    """
    # Base price seeded from symbol so each stock has a realistic range
    base = 500.0 + (sum(ord(c) for c in symbol) % 4500)
    return _make_sample_ohlcv(symbol, n=260, base_price=base)


def _registry_data_fetcher(
    registry: Any,
) -> Any:
    """Return a data fetcher that pulls live OHLCV from the broker registry.

    Args:
        registry: BrokerRegistry instance from the Flask app config.

    Returns:
        A callable with signature (symbol, exchange, timeframe) → list[dict].
    """
    def _fetch(symbol: str, exchange: str, timeframe: str) -> list[dict[str, Any]]:
        hist = registry.get_history(
            symbol=symbol, exchange=exchange, interval=timeframe, days=365
        )
        return hist.get("candles", [])
    return _fetch


# ---------------------------------------------------------------------------
# POST /ft-api/v1/scanner/run
# ---------------------------------------------------------------------------


@scanner_bp.route("/run", methods=["POST"])
def scanner_run() -> tuple[Any, int]:
    """Run a scan using a prebuilt name or an inline ScanConfig.

    Request JSON (one of):
        prebuilt (str):   Key from PREBUILT_SCANS (e.g. "rsi_oversold").
        config (dict):    Inline ScanConfig payload.

    Returns:
        JSON::

            {
              "status": "success",
              "is_sample_data": bool,
              "scan_name": str,
              "matched_count": int,
              "total_universe": int,
              "results": [
                {
                  "symbol": str,
                  "exchange": str,
                  "ltp": float,
                  "change_pct": float,
                  "matched_conditions": list[str],
                  "scan_time": str,
                  "score": float
                },
                ...
              ]
            }
    """
    body = request.get_json(silent=True) or {}

    # Resolve scan config
    config: ScanConfig | None = None
    if "prebuilt" in body:
        key = str(body["prebuilt"])
        config = PREBUILT_SCANS.get(key)
        if config is None:
            return jsonify({
                "status": "error",
                "message": f"Unknown prebuilt scan '{key}'. "
                           f"Valid keys: {sorted(PREBUILT_SCANS.keys())}",
            }), 400
    elif "config" in body:
        try:
            config = ScanConfig.model_validate(body["config"])
        except Exception as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400
    else:
        return jsonify({
            "status": "error",
            "message": "Request must include 'prebuilt' (str) or 'config' (object).",
        }), 400

    # Resolve data source
    is_sample_data = True
    fetcher = _sample_data_fetcher

    registry = current_app.config.get("REGISTRY")
    if registry and registry.is_connected():
        try:
            fetcher = _registry_data_fetcher(registry)
            is_sample_data = False
        except Exception as exc:
            logger.warning("Could not build registry fetcher, using sample data: %s", exc)

    try:
        results: list[ScanResult] = _scanner.scan(config, data_fetcher=fetcher)
    except Exception as exc:
        logger.exception("Scanner run error for '%s'", config.name)
        return jsonify({"status": "error", "message": str(exc)}), 500

    symbols = config.get_symbols()

    return jsonify({
        "status": "success",
        "is_sample_data": is_sample_data,
        "scan_name": config.name,
        "matched_count": len(results),
        "total_universe": len(symbols),
        "results": [
            {
                "symbol": r.symbol,
                "exchange": r.exchange,
                "ltp": r.ltp,
                "change_pct": r.change_pct,
                "matched_conditions": r.matched_conditions,
                "scan_time": r.scan_time.isoformat(),
                "score": r.score,
            }
            for r in results
        ],
    }), 200


# ---------------------------------------------------------------------------
# GET /ft-api/v1/scanner/prebuilt
# ---------------------------------------------------------------------------


@scanner_bp.route("/prebuilt", methods=["GET"])
def scanner_prebuilt() -> tuple[Any, int]:
    """List all prebuilt scan configurations.

    Returns:
        JSON::

            {
              "status": "success",
              "count": int,
              "scans": [
                {
                  "key": str,
                  "name": str,
                  "universe": str,
                  "timeframe": str,
                  "condition_count": int,
                  "conditions": [{"label": str, "indicator": str, ...}]
                },
                ...
              ]
            }
    """
    scans = []
    for key, cfg in PREBUILT_SCANS.items():
        scans.append({
            "key": key,
            "name": cfg.name,
            "universe": cfg.universe,
            "timeframe": cfg.timeframe,
            "condition_count": len(cfg.conditions),
            "conditions": [
                {
                    "label": c.label,
                    "indicator": c.indicator,
                    "operator": c.operator,
                    "value": c.value,
                }
                for c in cfg.conditions
            ],
        })

    return jsonify({
        "status": "success",
        "count": len(scans),
        "data": {"scans": scans},
    }), 200


# ---------------------------------------------------------------------------
# POST /ft-api/v1/scanner/custom
# ---------------------------------------------------------------------------


@scanner_bp.route("/custom", methods=["POST"])
def scanner_custom() -> tuple[Any, int]:
    """Validate and echo a custom ScanConfig.

    This endpoint validates the structure of a user-supplied ScanConfig
    and returns the normalised config back to the caller.  It does NOT run
    the scan — use /run with a ``config`` payload for that.

    Request JSON:
        Full ScanConfig dict (name, conditions, universe, custom_symbols,
        timeframe).

    Returns:
        JSON with the validated config or a descriptive error.
    """
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"status": "error", "message": "Empty request body."}), 400

    try:
        config = ScanConfig.model_validate(body)
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    try:
        symbols = config.get_symbols()
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    return jsonify({
        "status": "success",
        "data": {
            "name": config.name,
            "universe": config.universe,
            "timeframe": config.timeframe,
            "symbol_count": len(symbols),
            "conditions": [
                {
                    "label": c.label,
                    "indicator": c.indicator,
                    "operator": c.operator,
                    "value": c.value,
                }
                for c in config.conditions
            ],
        },
    }), 200
