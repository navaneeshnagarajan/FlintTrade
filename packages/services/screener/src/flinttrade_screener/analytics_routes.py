"""Flask blueprint for VWAP bands, pair correlation, and multi-timeframe endpoints.

External URLs (frontend calls these via /ft-api/v1/*; the WSGI prefix stripper
in app.py rewrites to /v1/* before Flask dispatch):

    POST /ft-api/v1/indicators/vwap    — VWAP with ±1σ/2σ/3σ bands
    POST /ft-api/v1/analytics/pairs   — Pair correlation and z-score signals
    POST /ft-api/v1/analytics/mtf     — Multi-timeframe signal confluence

Blueprint registered at ``/v1`` (post-strip form).

All endpoints:
1. Extract parameters from the JSON request body.
2. Validate required fields and types; return HTTP 400 on bad input.
3. Delegate computation to the relevant engine class.
4. Return JSON with a consistent ``{"status": "success", "data": {...}}`` envelope.
5. Fall back to sample/synthetic data in dev mode (no broker connection required).

Pattern follows payoff_routes.py in this package.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from .multi_timeframe import MultiTimeframeAnalyser, make_sample_mtf_data
from .pair_correlation import PairCorrelationEngine, make_sample_pair_data

logger = logging.getLogger("flinttrade.screener.analytics_routes")

analytics_bp = Blueprint("analytics_ext", __name__, url_prefix="/v1")

# Engine singletons (created once per process)
_pair_engine = PairCorrelationEngine()
_mtf_analyser = MultiTimeframeAnalyser()


# ---------------------------------------------------------------------------
# POST /ft-api/v1/indicators/vwap
# ---------------------------------------------------------------------------


@analytics_bp.route("/indicators/vwap", methods=["POST"])
def indicators_vwap() -> Any:
    """Calculate intraday VWAP with ±1σ / ±2σ / ±3σ standard deviation bands.

    Request JSON:
        bars (list[dict]): OHLCV bars, sorted oldest-first.  Each bar must
            contain: ``timestamp`` (str, ISO), ``high`` (float), ``low``
            (float), ``close`` (float), ``volume`` (float).
            ``open`` is accepted but not used for VWAP.
        session_reset (bool, optional): Reset VWAP accumulator at each new
            calendar date (default ``true``).

    Returns:
        JSON::

            {
              "status": "success",
              "data": {
                "timestamps": ["2025-01-15T09:15:00", ...],
                "vwap":    [24012.3, ...],
                "upper_1": [24050.1, ...],
                "upper_2": [24088.0, ...],
                "upper_3": [24125.8, ...],
                "lower_1": [23974.5, ...],
                "lower_2": [23936.6, ...],
                "lower_3": [23898.8, ...]
              }
            }

        On error::

            {"status": "error", "message": "..."}
    """
    from flinttrade_indicators.vwap_bands import calculate_vwap_bands  # noqa: PLC0415

    body = request.get_json(silent=True) or {}
    bars = body.get("bars")
    session_reset = bool(body.get("session_reset", True))

    if not bars:
        # Dev fallback — generate sample intraday data
        logger.debug("VWAP endpoint: no bars provided, using sample data")
        bars = _make_sample_vwap_bars()

    if not isinstance(bars, list) or len(bars) == 0:
        return jsonify({"status": "error", "message": "'bars' must be a non-empty list"}), 400

    try:
        result = calculate_vwap_bands(bars, session_reset=session_reset)
    except ValueError:
        return jsonify({"status": "error", "message": "Invalid request"}), 400
    except Exception as exc:
        logger.exception("VWAP calculation failed: %s", exc)
        return jsonify({"status": "error", "message": "VWAP calculation failed"}), 500

    return jsonify({"status": "success", "data": result.model_dump()})


# ---------------------------------------------------------------------------
# POST /ft-api/v1/analytics/pairs
# ---------------------------------------------------------------------------


@analytics_bp.route("/analytics/pairs", methods=["POST"])
def analytics_pairs() -> Any:
    """Analyse correlated instrument pairs for spread divergence.

    Request JSON (two modes):

    Mode 1 — explicit pairs::

        {
          "pairs": [
            {
              "symbol_a": "TCS",
              "symbol_b": "INFY",
              "returns_a": [...],
              "returns_b": [...],
              "prices_a":  [...],
              "prices_b":  [...]
            }
          ]
        }

    Mode 2 — preset pairs (pass data for each symbol)::

        {
          "preset": true,
          "data": {
            "TCS":  {"returns": [...], "prices": [...]},
            "INFY": {"returns": [...], "prices": [...]}
          }
        }

    Returns:
        JSON::

            {
              "status": "success",
              "data": {
                "signals": [
                  {
                    "pair": ["TCS", "INFY"],
                    "correlation": 0.87,
                    "current_spread": 2100.0,
                    "mean_spread": 2050.3,
                    "std_spread": 120.5,
                    "z_score": 0.41,
                    "signal": "converging"
                  },
                  ...
                ]
              }
            }
    """
    body = request.get_json(silent=True) or {}
    use_preset = bool(body.get("preset", False))

    if use_preset:
        data = body.get("data")
        if not data:
            # Dev fallback
            logger.debug("Pairs endpoint: no data provided, using sample data")
            data = make_sample_pair_data()

        if not isinstance(data, dict):
            return jsonify({"status": "error", "message": "'data' must be an object"}), 400

        try:
            signals = _pair_engine.analyse_all_presets(data)
        except Exception as exc:
            logger.exception("Pair preset analysis failed: %s", exc)
            return jsonify({"status": "error", "message": "Pair analysis failed"}), 500

    else:
        raw_pairs = body.get("pairs")
        if not raw_pairs:
            # Dev fallback with preset
            logger.debug("Pairs endpoint: no pairs provided, using sample data")
            data = make_sample_pair_data()
            signals = _pair_engine.analyse_all_presets(data)
        else:
            if not isinstance(raw_pairs, list):
                return jsonify({"status": "error", "message": "'pairs' must be a list"}), 400

            signals = []
            for i, entry in enumerate(raw_pairs):
                if not isinstance(entry, dict):
                    return jsonify({
                        "status": "error",
                        "message": f"pairs[{i}] must be an object",
                    }), 400

                sym_a = str(entry.get("symbol_a", "A"))
                sym_b = str(entry.get("symbol_b", "B"))
                try:
                    sig = _pair_engine.analyse_pair(
                        returns_a=list(entry.get("returns_a", [])),
                        returns_b=list(entry.get("returns_b", [])),
                        prices_a=list(entry.get("prices_a", [])),
                        prices_b=list(entry.get("prices_b", [])),
                        pair=(sym_a, sym_b),
                    )
                    signals.append(sig)
                except Exception as exc:
                    logger.exception("Pair analysis failed for %s/%s: %s", sym_a, sym_b, exc)
                    return jsonify({
                        "status": "error",
                        "message": f"Analysis failed for pair {sym_a}/{sym_b}",
                    }), 500

    return jsonify({
        "status": "success",
        "data": {"signals": [s.model_dump() for s in signals]},
    })


# ---------------------------------------------------------------------------
# POST /ft-api/v1/analytics/mtf
# ---------------------------------------------------------------------------


@analytics_bp.route("/analytics/mtf", methods=["POST"])
def analytics_mtf() -> Any:
    """Analyse signal alignment across multiple timeframes for a symbol.

    Request JSON::

        {
          "symbol": "NIFTY",
          "data": {
            "5m":  [{"timestamp": "...", "open": f, "high": f,
                     "low": f, "close": f, "volume": f}, ...],
            "15m": [...],
            "1h":  [...],
            "1D":  [...]
          }
        }

    Returns:
        JSON::

            {
              "status": "success",
              "data": {
                "symbol": "NIFTY",
                "signals": [
                  {
                    "timeframe": "5m",
                    "trend": "bullish",
                    "rsi": 58.3,
                    "macd_histogram": 12.5,
                    "ema_position": "above",
                    "strength": 0.72
                  },
                  ...
                ],
                "confluence": 0.75,
                "overall": "bullish"
              }
            }
    """
    body = request.get_json(silent=True) or {}
    symbol = str(body.get("symbol", "NIFTY"))
    data_by_tf = body.get("data")

    if not data_by_tf:
        # Dev fallback
        logger.debug("MTF endpoint: no data provided, using sample data for %s", symbol)
        data_by_tf = make_sample_mtf_data()

    if not isinstance(data_by_tf, dict):
        return jsonify({"status": "error", "message": "'data' must be an object"}), 400

    try:
        result = _mtf_analyser.analyse(symbol=symbol, data_by_tf=data_by_tf)
    except Exception as exc:
        logger.exception("MTF analysis failed for %s: %s", symbol, exc)
        return jsonify({"status": "error", "message": "Multi-timeframe analysis failed"}), 500

    return jsonify({"status": "success", "data": result.model_dump()})


# ---------------------------------------------------------------------------
# Private sample-data helpers
# ---------------------------------------------------------------------------


def _make_sample_vwap_bars(n: int = 75, seed: int = 0) -> list[dict]:
    """Generate synthetic intraday OHLCV bars for VWAP dev/fallback mode.

    Args:
        n:    Number of bars to generate.
        seed: Random seed for reproducibility.

    Returns:
        List of OHLCV bar dicts with keys
        ``timestamp``, ``open``, ``high``, ``low``, ``close``, ``volume``.
    """
    import random

    rng = random.Random(seed)
    close = 24000.0
    bars = []
    for i in range(n):
        ret = rng.gauss(0.0, 0.002)
        close = max(close * (1.0 + ret), 1.0)
        spread = close * 0.001
        open_ = close + rng.uniform(-spread, spread)
        high = max(open_, close) + abs(rng.gauss(0, spread * 0.5))
        low = min(open_, close) - abs(rng.gauss(0, spread * 0.5))
        minute = i % 375   # NSE trading minutes (9:15 to 15:30)
        hour = 9 + minute // 60
        minute_of_hour = 15 + minute % 60
        if minute_of_hour >= 60:
            hour += 1
            minute_of_hour -= 60
        ts = f"2025-01-15T{hour:02d}:{minute_of_hour:02d}:00"
        bars.append({
            "timestamp": ts,
            "open": round(open_, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
            "volume": round(rng.uniform(1000, 30000), 0),
        })
    return bars
