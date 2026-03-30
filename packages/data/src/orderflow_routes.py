"""Order Flow Flask endpoint — synthetic footprint data for the OrderFlow widget.

Registered as a Blueprint in ``create_flask_app()`` (packages/core/src/app.py).

Endpoint
--------
GET  /v1/orderflow  — Footprint buckets for a given symbol/interval.

Query parameters:
    symbol    (str, required):  Instrument symbol, e.g. "NIFTY".
    exchange  (str, optional):  Exchange code.  Default ``"NSE"``.
    interval  (int, optional):  Bucket width in seconds.  Default ``60``.
    tick_size (float, optional): Price-level granularity.  Default ``0.05``.

Since real tick data requires an active WebSocket subscription (not available
via REST), this endpoint generates deterministic synthetic footprint data that
mirrors realistic NIFTY-like price/volume distributions.  When the live
WebSocket-based OrderFlowAggregator pipeline is wired, this endpoint will
serve accumulated real buckets instead.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from flask import Blueprint, jsonify, request


logger = logging.getLogger("flinttrade.data.orderflow_routes")

orderflow_bp = Blueprint("orderflow", __name__)

# ---------------------------------------------------------------------------
# Synthetic data generation
# ---------------------------------------------------------------------------

# Base prices per symbol — deterministic so repeated requests return
# structurally consistent data (only the time labels shift).
_BASE_PRICES: dict[str, float] = {
    "NIFTY": 22_500.0,
    "BANKNIFTY": 48_000.0,
    "FINNIFTY": 21_000.0,
    "MIDCPNIFTY": 11_500.0,
    "RELIANCE": 2_900.0,
    "TCS": 3_800.0,
}


def _generate_synthetic_buckets(
    symbol: str,
    interval: int,
    tick_size: float,
    count: int = 20,
) -> list[dict[str, Any]]:
    """Generate *count* synthetic footprint buckets.

    The data uses a simple seeded PRNG so that the same symbol+interval
    combination always produces the same price structure (though time labels
    shift with the clock).

    Args:
        symbol: Instrument symbol (used to seed the base price).
        interval: Bucket width in seconds.
        tick_size: Price-level rounding granularity.
        count: Number of buckets to generate.

    Returns:
        List of serialised bucket dicts ready for JSON response.
    """
    base_price = _BASE_PRICES.get(symbol, 20_000.0)
    price_rows = 10  # levels per bucket

    # Deterministic PRNG seeded by symbol + interval
    seed = sum(ord(c) for c in symbol) + interval
    rng_state = [seed]

    def rand() -> float:
        rng_state[0] = (rng_state[0] * 1664525 + 1013904223) & 0xFFFF_FFFF
        return abs(rng_state[0]) / 0x7FFF_FFFF

    # Time labels — count backwards from "now" in interval-second steps
    now = time.time()
    now_quantised = int(now // interval) * interval

    mid = base_price
    buckets: list[dict[str, Any]] = []

    for i in range(count):
        bucket_ts = now_quantised - (count - 1 - i) * interval
        time_label = time.strftime("%H:%M:%S", time.localtime(bucket_ts))

        # Random-walk the mid price
        mid += (rand() - 0.5) * tick_size * 80
        mid = round(mid / tick_size) * tick_size

        start_price = mid - (price_rows // 2) * tick_size
        cells: dict[str, dict[str, int]] = {}
        max_vol = -1
        poc_price = mid

        for r in range(price_rows):
            level = round(start_price + r * tick_size, 4)
            dist = abs(r - price_rows / 2) / (price_rows / 2)
            vol_scale = max(0.1, 1 - dist * 0.8) * 10_000
            buy_vol = int(rand() * vol_scale * (1 + rand() * 0.5))
            sell_vol = int(rand() * vol_scale * (1 + rand() * 0.5))

            cells[str(level)] = {"buy_volume": buy_vol, "sell_volume": sell_vol}

            total = buy_vol + sell_vol
            if total > max_vol:
                max_vol = total
                poc_price = level

        total_volume = sum(c["buy_volume"] + c["sell_volume"] for c in cells.values())
        delta = sum(c["buy_volume"] - c["sell_volume"] for c in cells.values())

        buckets.append({
            "time_label": time_label,
            "cells": cells,
            "poc_price": poc_price,
            "total_volume": total_volume,
            "delta": delta,
        })

    return buckets


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@orderflow_bp.route("/v1/orderflow", methods=["GET"])
def orderflow_endpoint() -> tuple[Any, int]:
    """Return synthetic footprint buckets for the OrderFlow widget.

    Query params:
        symbol    (str):   Required. Instrument symbol.
        exchange  (str):   Optional, default ``"NSE"``.
        interval  (int):   Optional, bucket width in seconds (default 60).
        tick_size (float): Optional, price-level granularity (default 0.05).

    Returns:
        JSON with ``status``, ``data.buckets``, ``data.symbol``, ``data.interval``.
    """
    symbol = request.args.get("symbol")
    if not symbol:
        return jsonify({"status": "error", "message": "symbol query parameter is required"}), 400

    _exchange = request.args.get("exchange", "NSE")  # reserved for future multi-exchange support

    try:
        interval = int(request.args.get("interval", "60"))
    except ValueError:
        return jsonify({"status": "error", "message": "interval must be an integer (seconds)"}), 400

    try:
        tick_size = float(request.args.get("tick_size", "0.05"))
    except ValueError:
        return jsonify({"status": "error", "message": "tick_size must be a number"}), 400

    if interval <= 0:
        return jsonify({"status": "error", "message": "interval must be positive"}), 400
    if tick_size <= 0:
        return jsonify({"status": "error", "message": "tick_size must be positive"}), 400

    buckets = _generate_synthetic_buckets(
        symbol=symbol.upper(),
        interval=interval,
        tick_size=tick_size,
        count=20,
    )

    return jsonify({
        "status": "success",
        "data": {
            "buckets": buckets,
            "symbol": symbol.upper(),
            "interval": interval,
        },
    }), 200
