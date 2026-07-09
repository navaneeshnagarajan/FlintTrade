"""Order Flow Flask endpoint — footprint data for the OrderFlow widget.

Registered as a Blueprint in ``create_flask_app()`` (packages/core/core/src/app.py).

Endpoints
---------
GET  /api/v1/data/orderflow  — Footprint buckets for a given symbol/interval/bins.

Query parameters:
    symbol    (str, required):  Instrument symbol, e.g. "NIFTY".
    exchange  (str, optional):  Exchange code.  Default ``"NFO"``.
    interval  (int, optional):  Bucket width in seconds.  Default ``300`` (5 min).
    bins      (int, optional):  Number of recent bins to return.  Default ``50``.
    tick_size (float, optional): Price-level granularity.  Default ``0.05``.

The response includes ``is_live: true`` when the live OrderFlowAggregatorV2
has accumulated data for the requested symbol.  When no live data is available
(e.g. market is closed or the WebSocket tick pipeline is not yet wired), the
endpoint falls back to the deterministic synthetic generator and returns
``is_live: false``.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from flask import Blueprint, jsonify, request

logger = logging.getLogger("flinttrade.data.orderflow_routes")

orderflow_bp = Blueprint("orderflow", __name__, url_prefix="/api/v1")

# ---------------------------------------------------------------------------
# Lazy import of the live aggregator — optional dependency
# ---------------------------------------------------------------------------

def _get_live_aggregator():  # type: ignore[return]
    """Return the shared OrderFlowAggregator singleton, or None if unavailable.

    The aggregator is created and stored on the Flask app config under the key
    ``"ORDERFLOW_AGGREGATOR"`` by the application factory. If the key is not
    present (e.g. during tests or before the pipeline is wired) this function
    returns None and the route falls back to synthetic data.
    """
    try:
        from flask import current_app  # noqa: PLC0415
        return current_app.config.get("ORDERFLOW_AGGREGATOR")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Synthetic data generation
# ---------------------------------------------------------------------------

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

    seed = sum(ord(c) for c in symbol) + interval
    rng_state = [seed]

    def rand() -> float:
        rng_state[0] = (rng_state[0] * 1664525 + 1013904223) & 0xFFFF_FFFF
        return abs(rng_state[0]) / 0x7FFF_FFFF

    now = time.time()
    now_quantised = int(now // interval) * interval

    mid = base_price
    buckets: list[dict[str, Any]] = []

    for i in range(count):
        bucket_ts = now_quantised - (count - 1 - i) * interval
        time_label = time.strftime("%H:%M:%S", time.localtime(bucket_ts))

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
# Live aggregator → bucket format converter
# ---------------------------------------------------------------------------

def _live_buckets_to_response(
    live_buckets: list[Any],
    symbol: str,
) -> list[dict[str, Any]]:
    """Convert OrderFlowAggregatorV2 FootprintBucket list to response format.

    Groups flat price-level buckets (one per price level per bin) into the
    nested cells-dict structure that the frontend expects. Buckets are already
    binned by the aggregator's fixed width (the caller reports that width).

    Args:
        live_buckets: List of FootprintBucket from the aggregator.
        symbol: Symbol (for logging).

    Returns:
        List of bucket dicts with ``time_label``, ``cells``, ``poc_price``,
        ``total_volume``, and ``delta``.
    """
    # Group by timestamp bin
    from collections import defaultdict  # noqa: PLC0415

    groups: dict[int, list[Any]] = defaultdict(list)
    for b in live_buckets:
        groups[b.timestamp_bin].append(b)

    result: list[dict[str, Any]] = []

    for bin_start in sorted(groups.keys()):
        rows = groups[bin_start]
        time_label = time.strftime("%H:%M:%S", time.localtime(bin_start))
        cells: dict[str, dict[str, int]] = {}
        max_vol = -1
        poc_price = 0.0
        total_volume = 0
        delta = 0

        for row in rows:
            level_str = str(row.price_level)
            cells[level_str] = {
                "buy_volume": row.buy_volume,
                "sell_volume": row.sell_volume,
            }
            total = row.buy_volume + row.sell_volume
            total_volume += total
            delta += row.delta
            if total > max_vol:
                max_vol = total
                poc_price = row.price_level

        result.append({
            "time_label": time_label,
            "cells": cells,
            "poc_price": poc_price,
            "total_volume": total_volume,
            "delta": delta,
        })

    return result


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@orderflow_bp.route("/data/orderflow", methods=["GET"])
def orderflow_endpoint() -> tuple[Any, int]:
    """Return footprint buckets for the OrderFlow / Footprint widgets.

    Tries the live OrderFlowAggregatorV2 first.  Falls back to synthetic
    data if no live data is available.

    Query params:
        symbol    (str):   Required. Instrument symbol.
        exchange  (str):   Optional, default ``"NFO"``.
        interval  (int):   Optional, bucket width in seconds (default 300).
        bins      (int):   Optional, number of recent bins to return (default 50).
        tick_size (float): Optional, price-level granularity (default 0.05).

    Returns:
        JSON with ``status``, ``data.buckets``, ``data.symbol``,
        ``data.exchange``, ``data.interval``, and ``data.is_live``.
    """
    symbol = request.args.get("symbol")
    if not symbol:
        return jsonify({"status": "error", "message": "symbol query parameter is required"}), 400

    exchange = request.args.get("exchange", "NFO")

    try:
        interval = int(request.args.get("interval", "300"))
    except ValueError:
        return jsonify({"status": "error", "message": "interval must be an integer (seconds)"}), 400

    try:
        bins = int(request.args.get("bins", "50"))
    except ValueError:
        return jsonify({"status": "error", "message": "bins must be an integer"}), 400

    try:
        tick_size = float(request.args.get("tick_size", "0.05"))
    except ValueError:
        return jsonify({"status": "error", "message": "tick_size must be a number"}), 400

    if interval <= 0:
        return jsonify({"status": "error", "message": "interval must be positive"}), 400
    if bins <= 0:
        return jsonify({"status": "error", "message": "bins must be positive"}), 400
    if tick_size <= 0:
        return jsonify({"status": "error", "message": "tick_size must be positive"}), 400

    symbol_upper = symbol.upper()
    is_live = False
    buckets: list[dict[str, Any]] = []
    # The bin width actually represented by the returned buckets. The synthetic
    # path honours the requested interval; the live aggregator bins at a fixed
    # width, so we report ITS real width rather than echoing the request — a
    # 1m/15m selection must not relabel fixed 5-minute footprint bins.
    effective_interval = interval

    # Try live aggregator first
    try:
        aggregator = _get_live_aggregator()
        if aggregator is not None:
            live_data = aggregator.get_footprint(symbol_upper, n_bins=bins)
            if live_data:
                buckets = _live_buckets_to_response(live_data, symbol_upper)
                effective_interval = int(getattr(aggregator, "time_bin_seconds", interval))
                is_live = True
    except Exception as exc:
        logger.debug("Live aggregator unavailable for %s: %s", symbol_upper, exc)

    # Fall back to synthetic data when live aggregator has no data
    if not buckets:
        buckets = _generate_synthetic_buckets(
            symbol=symbol_upper,
            interval=interval,
            tick_size=tick_size,
            count=min(bins, 20),
        )
        is_live = False
        effective_interval = interval

    return jsonify({
        "status": "success",
        "data": {
            "buckets": buckets,
            "symbol": symbol_upper,
            "exchange": exchange,
            "interval": effective_interval,
            "requested_interval": interval,
            "is_live": is_live,
        },
    }), 200
