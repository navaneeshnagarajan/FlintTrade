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

The response includes ``is_live: true`` only when retained buckets contain a
fresh current-session source event that contributed positive volume. ``quality``
and ``provenance`` distinguish exact trade ticks, estimated cumulative-quote
deltas, and synthetic samples. When no retained buckets exist,
``is_sample_data`` is true and freshness fails closed as unavailable.
"""

from __future__ import annotations

import logging
import math
import time
from collections import defaultdict
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request

from .orderflow_aggregator import OrderFlowAggregator, is_arithmetic_safe_tick_size

logger = logging.getLogger("flinttrade.data.orderflow_routes")
_IST = ZoneInfo("Asia/Kolkata")

orderflow_bp = Blueprint("orderflow", __name__, url_prefix="/api/v1")


def _ist_time_label(timestamp: int | float) -> str:
    """Format an epoch timestamp in IST regardless of the host timezone."""
    return datetime.fromtimestamp(timestamp, tz=_IST).strftime("%H:%M:%S")

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
        time_label = _ist_time_label(bucket_ts)

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
            "quality": "sample",
            "provenance": "synthetic",
        })

    return buckets


# ---------------------------------------------------------------------------
# Live aggregator → bucket format converter
# ---------------------------------------------------------------------------

def _exact_multiple_ratio(requested: int | float, source: int | float) -> int | None:
    """Return the positive integer ratio when ``requested`` exactly represents ``source``."""
    try:
        requested_decimal = Decimal(str(requested))
        source_decimal = Decimal(str(source))
        if source_decimal <= 0 or requested_decimal < source_decimal:
            return None
        ratio = requested_decimal / source_decimal
    except (InvalidOperation, ValueError, ZeroDivisionError):
        return None
    integral_ratio = ratio.to_integral_value()
    return int(integral_ratio) if ratio == integral_ratio else None


def _source_interval(aggregator: Any, fallback: int) -> int:
    """Read a real positive source interval without trusting mock-like attributes."""
    value = getattr(aggregator, "time_bin_seconds", None)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    if not math.isfinite(float(value)) or value <= 0 or int(value) != value:
        return fallback
    return int(value)


def _source_tick_size(aggregator: Any, fallback: float) -> float:
    """Read a real positive source tick size without trusting mock-like attributes."""
    value = getattr(aggregator, "tick_size", None)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    value = float(value)
    return value if math.isfinite(value) and value > 0 else fallback


def _unavailable_market_freshness() -> dict[str, Any]:
    return {
        "state": "unavailable",
        "is_fresh": False,
        "last_tick_timestamp": None,
        "last_tick_session": None,
        "current_session": datetime.now(tz=_IST).date().isoformat(),
        "age_seconds": None,
        "provenance": None,
    }


def _market_freshness(aggregator: Any, symbol: str, exchange: str) -> dict[str, Any]:
    """Read a validated freshness snapshot without trusting retained buckets alone."""
    get_freshness = getattr(aggregator, "get_market_freshness", None)
    if not callable(get_freshness):
        return _unavailable_market_freshness()
    try:
        candidate = get_freshness(symbol, exchange=exchange)
    except Exception as exc:  # noqa: BLE001 - freshness failure must fail closed
        logger.debug("Order-flow freshness unavailable for %s:%s: %s", exchange, symbol, exc)
        return _unavailable_market_freshness()
    if not isinstance(candidate, dict) or candidate.get("state") not in {
        "live",
        "delayed",
        "stale",
        "unavailable",
    }:
        return _unavailable_market_freshness()
    state = str(candidate["state"])
    return {
        "state": state,
        "is_fresh": state == "live" and candidate.get("is_fresh") is True,
        "last_tick_timestamp": candidate.get("last_tick_timestamp"),
        "last_tick_session": candidate.get("last_tick_session"),
        "current_session": candidate.get("current_session"),
        "age_seconds": candidate.get("age_seconds"),
        "provenance": (
            candidate.get("provenance")
            if candidate.get("provenance") in {"trade_tick", "cumulative_quote_delta", "mixed"}
            else None
        ),
    }


def _round_to_tick(price: float, tick_size: float) -> float:
    """Round a source price onto a coarser exact-multiple tick boundary."""
    price_decimal = Decimal(str(price))
    tick_decimal = Decimal(str(tick_size))
    units = (price_decimal / tick_decimal).to_integral_value(rounding=ROUND_HALF_EVEN)
    return float(units * tick_decimal)


def _summarise_quality(values: set[str]) -> str:
    """Return a conservative quality label for one or more source buckets."""
    if not values or "unknown" in values:
        return "unknown"
    if len(values) == 1:
        return next(iter(values))
    if values <= {"exact", "estimated"}:
        return "estimated"
    return "unknown"


def _summarise_provenance(values: set[str]) -> str:
    """Return one provenance label, or ``mixed`` when sources differ."""
    if not values:
        return "unknown"
    return next(iter(values)) if len(values) == 1 else "mixed"


def _live_buckets_to_response(
    live_buckets: list[Any],
    symbol: str,
    *,
    coarsen_interval: int | None = None,
    coarsen_tick_size: float | None = None,
) -> list[dict[str, Any]]:
    """Convert OrderFlowAggregatorV2 FootprintBucket list to response format.

    Groups flat price-level buckets (one per price level per bin) into the
    nested cells-dict structure that the frontend expects. Exact-multiple
    interval and tick-size requests may coarsen source rows; colliding cells
    are merged by summing both sides so no volume is lost.

    Args:
        live_buckets: List of FootprintBucket from the aggregator.
        symbol: Symbol (for logging).
        coarsen_interval: Wider target interval, or ``None`` to retain source bins.
        coarsen_tick_size: Wider target tick size, or ``None`` to retain source levels.

    Returns:
        List of bucket dicts with ``time_label``, ``cells``, ``poc_price``,
        ``total_volume``, and ``delta``.
    """
    groups: dict[int, dict[float, list[int]]] = defaultdict(dict)
    group_qualities: dict[int, set[str]] = defaultdict(set)
    group_provenances: dict[int, set[str]] = defaultdict(set)
    for bucket in live_buckets:
        bin_start = int(bucket.timestamp_bin)
        if coarsen_interval is not None:
            bin_start = OrderFlowAggregator.calculate_aligned_time_bin(bin_start, coarsen_interval)
        price_level = float(bucket.price_level)
        if coarsen_tick_size is not None:
            price_level = _round_to_tick(price_level, coarsen_tick_size)
        cell = groups[bin_start].setdefault(price_level, [0, 0])
        cell[0] += int(bucket.buy_volume)
        cell[1] += int(bucket.sell_volume)
        quality = getattr(bucket, "quality", "unknown")
        provenance = getattr(bucket, "provenance", "unknown")
        group_qualities[bin_start].add(
            quality if quality in {"exact", "estimated"} else "unknown"
        )
        group_provenances[bin_start].add(
            provenance
            if provenance in {"trade_tick", "cumulative_quote_delta", "mixed"}
            else "unknown"
        )

    result: list[dict[str, Any]] = []

    for bin_start in sorted(groups):
        levels = groups[bin_start]
        time_label = _ist_time_label(bin_start)
        cells: dict[str, dict[str, int]] = {}
        max_vol = -1
        poc_price = 0.0
        total_volume = 0
        delta = 0

        for price_level in sorted(levels):
            buy_volume, sell_volume = levels[price_level]
            level_str = str(price_level)
            cells[level_str] = {
                "buy_volume": buy_volume,
                "sell_volume": sell_volume,
            }
            total = buy_volume + sell_volume
            total_volume += total
            delta += buy_volume - sell_volume
            if total > max_vol:
                max_vol = total
                poc_price = price_level

        result.append({
            "time_label": time_label,
            "cells": cells,
            "poc_price": poc_price,
            "total_volume": total_volume,
            "delta": delta,
            "quality": _summarise_quality(group_qualities[bin_start]),
            "provenance": _summarise_provenance(group_provenances[bin_start]),
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
        ``data.exchange``, ``data.interval``, ``data.is_live``,
        ``data.is_sample_data``, ``data.quality``, and ``data.provenance``.
    """
    symbol = (request.args.get("symbol") or "").strip().upper()
    if not symbol:
        return jsonify({"status": "error", "message": "symbol query parameter is required"}), 400

    exchange = (request.args.get("exchange", "NFO") or "").strip().upper()
    if not exchange:
        return jsonify({"status": "error", "message": "exchange query parameter must not be blank"}), 400

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
    if not is_arithmetic_safe_tick_size(tick_size):
        return jsonify({
            "status": "error",
            "message": "tick_size must be a finite arithmetic-safe number",
        }), 400

    symbol_upper = symbol
    is_live = False
    buckets: list[dict[str, Any]] = []
    # The bin width actually represented by the returned buckets. The synthetic
    # path honours the requested interval; the live aggregator bins at a fixed
    # width, so we report ITS real width rather than echoing the request — a
    # 1m/15m selection must not relabel fixed 5-minute footprint bins.
    effective_interval = interval
    effective_tick_size = tick_size
    source_interval = interval
    source_tick_size = tick_size
    freshness = _unavailable_market_freshness()
    live_state = "unavailable"
    is_sample_data = False
    quality = "unknown"
    provenance = "unknown"

    # Try live aggregator first
    try:
        aggregator = _get_live_aggregator()
        if aggregator is not None:
            freshness = _market_freshness(aggregator, symbol_upper, exchange)
            live_state = str(freshness["state"])
            source_interval = _source_interval(aggregator, interval)
            source_tick_size = _source_tick_size(aggregator, tick_size)
            interval_ratio = _exact_multiple_ratio(interval, source_interval)
            source_bin_count = bins * interval_ratio if interval_ratio is not None else bins
            live_data = aggregator.get_footprint(symbol_upper, n_bins=source_bin_count, exchange=exchange)
            if live_data:
                tick_size_ratio = _exact_multiple_ratio(tick_size, source_tick_size)
                effective_interval = interval if interval_ratio is not None else source_interval
                effective_tick_size = tick_size if tick_size_ratio is not None else source_tick_size
                buckets = _live_buckets_to_response(
                    live_data,
                    symbol_upper,
                    coarsen_interval=effective_interval if interval_ratio and interval_ratio > 1 else None,
                    coarsen_tick_size=effective_tick_size if tick_size_ratio and tick_size_ratio > 1 else None,
                )[-bins:]
                quality = _summarise_quality({str(bucket["quality"]) for bucket in buckets})
                provenance = _summarise_provenance({str(bucket["provenance"]) for bucket in buckets})
                is_live = freshness["is_fresh"] is True
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
        effective_tick_size = tick_size
        source_interval = interval
        source_tick_size = tick_size
        live_state = "warming" if freshness["state"] == "live" else "unavailable"
        is_sample_data = True
        quality = "sample"
        provenance = "synthetic"

    return jsonify({
        "status": "success",
        "data": {
            "buckets": buckets,
            "symbol": symbol_upper,
            "exchange": exchange,
            "interval": effective_interval,
            "tick_size": effective_tick_size,
            "requested_interval": interval,
            "requested_tick_size": tick_size,
            "source_interval": source_interval,
            "source_tick_size": source_tick_size,
            "is_live": is_live,
            "is_sample_data": is_sample_data,
            "live_state": live_state,
            "freshness": freshness,
            "quality": quality,
            "provenance": provenance,
        },
    }), 200
