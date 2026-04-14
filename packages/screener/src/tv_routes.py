"""TradingView signals API routes.

Exposes TradingView technical analysis data (buy/sell/neutral recommendations,
oscillators, moving averages) via REST endpoints. No API key required from
TradingView — uses the public tradingview-ta library.

Blueprint prefix: /v1/tv
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

logger = logging.getLogger("flinttrade.screener.tv_routes")

tv_bp = Blueprint("tv_signals", __name__, url_prefix="/v1/tv")


@tv_bp.route("/analysis", methods=["GET"])
def tv_analysis() -> tuple[Any, int]:
    """Get TradingView technical analysis for a symbol.

    Query params:
        symbol (str): Trading symbol (e.g. RELIANCE, NIFTY).
        exchange (str): Exchange code (default: NSE).
        interval (str): Timeframe (default: 1d). Options: 1m,5m,15m,30m,1h,2h,4h,1d,1w,1M.

    Returns:
        JSON with recommendation, summary counts, oscillators, and moving averages.
    """
    symbol = request.args.get("symbol", "").strip().upper()
    exchange = request.args.get("exchange", "NSE").strip().upper()
    interval = request.args.get("interval", "1d").strip()

    if not symbol:
        return jsonify({"status": "error", "message": "symbol parameter is required."}), 400

    from .tv_signals import TVSignals  # noqa: PLC0415

    tv = TVSignals()
    result = tv.get_analysis(symbol, exchange, interval)

    if result.error:
        return jsonify({"status": "error", "message": result.error}), 502

    return jsonify({
        "status": "success",
        "data": {
            "symbol": result.symbol,
            "exchange": result.exchange,
            "interval": result.interval,
            "recommendation": result.recommendation,
            "summary": result.summary,
            "oscillators": result.oscillators,
            "oscillators_recommendation": result.oscillators_recommendation,
            "moving_averages": result.moving_averages,
            "moving_averages_recommendation": result.moving_averages_recommendation,
        },
    }), 200


@tv_bp.route("/analysis/bulk", methods=["POST"])
def tv_bulk_analysis() -> tuple[Any, int]:
    """Get TradingView analysis for multiple symbols.

    Request JSON:
        symbols (list[dict]): Each with "symbol" and optional "exchange" keys.
        interval (str, optional): Timeframe for all symbols (default: 1d).

    Returns:
        JSON with analysis results for each symbol.
    """
    body = request.get_json(silent=True) or {}
    raw_symbols = body.get("symbols", [])
    interval = body.get("interval", "1d")

    if not isinstance(raw_symbols, list) or not raw_symbols:
        return jsonify({"status": "error", "message": "symbols must be a non-empty list."}), 400

    pairs: list[tuple[str, str]] = []
    for item in raw_symbols[:20]:  # Cap at 20 to avoid abuse
        if isinstance(item, dict):
            sym = str(item.get("symbol", "")).strip().upper()
            exch = str(item.get("exchange", "NSE")).strip().upper()
            if sym:
                pairs.append((sym, exch))
        elif isinstance(item, str):
            pairs.append((item.strip().upper(), "NSE"))

    if not pairs:
        return jsonify({"status": "error", "message": "No valid symbols provided."}), 400

    from .tv_signals import TVSignals  # noqa: PLC0415

    tv = TVSignals()
    results = tv.get_bulk_analysis(pairs, interval)

    return jsonify({
        "status": "success",
        "data": [
            {
                "symbol": r.symbol,
                "exchange": r.exchange,
                "recommendation": r.recommendation,
                "summary": r.summary,
                "error": r.error or None,
            }
            for r in results
        ],
    }), 200


@tv_bp.route("/recommendation", methods=["GET"])
def tv_recommendation() -> tuple[Any, int]:
    """Get multi-timeframe recommendation summary for a symbol.

    Query params:
        symbol (str): Trading symbol.
        exchange (str): Exchange code (default: NSE).

    Returns:
        JSON with recommendations across 1h, 4h, 1d, 1w timeframes.
    """
    symbol = request.args.get("symbol", "").strip().upper()
    exchange = request.args.get("exchange", "NSE").strip().upper()

    if not symbol:
        return jsonify({"status": "error", "message": "symbol parameter is required."}), 400

    from .tv_signals import TVSignals  # noqa: PLC0415

    tv = TVSignals()
    recs = tv.get_recommendation_summary(symbol, exchange)

    return jsonify({
        "status": "success",
        "data": {
            "symbol": symbol,
            "exchange": exchange,
            "recommendations": recs,
        },
    }), 200
