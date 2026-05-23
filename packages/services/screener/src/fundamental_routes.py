"""Flask blueprint for fundamental screener endpoints.

Provides three endpoints under /api/v1/screener/fundamental/:

- GET  /api/v1/screener/fundamental/search?q=reliance
- GET  /api/v1/screener/fundamental/<symbol>
- POST /api/v1/screener/fundamental/screen

All endpoints use the FundamentalScreener which caches results in DuckDB
for 24 hours. The search endpoint queries Screener.in's API; the symbol
endpoint scrapes the company page; the screen endpoint queries cached data.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import Any

from flask import Blueprint, jsonify, request

from .fundamental_screener import FundamentalScreener

logger = logging.getLogger("flinttrade.screener.fundamental_routes")

fundamental_bp = Blueprint(
    "fundamental_screener",
    __name__,
    url_prefix="/api/v1/screener/fundamental",
)

# Module-level screener instance (lazy-initialised)
_screener: FundamentalScreener | None = None


def _get_screener() -> FundamentalScreener:
    """Return the module-level FundamentalScreener, creating it on first access."""
    global _screener  # noqa: PLW0603
    if _screener is None:
        _screener = FundamentalScreener()
    return _screener


def _run_async(coro: Any) -> Any:
    """Run an async coroutine from sync Flask code.

    Creates a new event loop if none is running (standard for Flask).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already in an async context — create a new thread loop
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# GET /api/v1/screener/fundamental/search?q=reliance
# ---------------------------------------------------------------------------


@fundamental_bp.route("/search", methods=["GET"])
def fundamental_search() -> tuple[Any, int]:
    """Search stocks by name or symbol.

    Query parameters:
        q (str, required): Search query (minimum 2 characters).

    Returns:
        JSON: ``{"status": "success", "data": {"query": "...", "results": [...]}}``
    """
    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return jsonify({
            "status": "error",
            "message": "Query parameter 'q' must be at least 2 characters.",
        }), 400

    try:
        screener = _get_screener()
        results = _run_async(screener.search_stocks(query))
        return jsonify({
            "status": "success",
            "data": {
                "query": query,
                "results": [
                    {"name": r.name, "symbol": r.symbol, "url": r.url}
                    for r in results
                ],
                "count": len(results),
            },
        }), 200
    except Exception:
        logger.exception("fundamental_search error for q=%s", query)
        return jsonify({
            "status": "error",
            "message": "Failed to search stocks. Please try again.",
        }), 500


# ---------------------------------------------------------------------------
# GET /api/v1/screener/fundamental/<symbol>
# ---------------------------------------------------------------------------


@fundamental_bp.route("/<symbol>", methods=["GET"])
def fundamental_detail(symbol: str) -> tuple[Any, int]:
    """Get detailed fundamentals for a single stock.

    Path parameters:
        symbol (str): NSE/BSE ticker (e.g. ``TCS``, ``RELIANCE``).

    Returns:
        JSON: ``{"status": "success", "data": {...}}``

    Notes:
        Results are cached for 24 hours. First request for a symbol
        scrapes Screener.in and may take 2-5 seconds.
    """
    symbol = symbol.upper().strip()
    if not symbol or len(symbol) > 20:
        return jsonify({
            "status": "error",
            "message": "Invalid symbol.",
        }), 400

    try:
        screener = _get_screener()
        data = _run_async(screener.get_fundamentals(symbol))
        result = asdict(data)
        return jsonify({
            "status": "success",
            "data": result,
        }), 200
    except Exception:
        logger.exception("fundamental_detail error for symbol=%s", symbol)
        return jsonify({
            "status": "error",
            "message": f"Failed to fetch fundamentals for {symbol}.",
        }), 500


# ---------------------------------------------------------------------------
# POST /api/v1/screener/fundamental/screen
# ---------------------------------------------------------------------------


@fundamental_bp.route("/screen", methods=["POST"])
def fundamental_screen() -> tuple[Any, int]:
    """Screen stocks using fundamental filters.

    Request body (JSON):
        pe_min (float, optional): Minimum P/E ratio.
        pe_max (float, optional): Maximum P/E ratio.
        pb_min (float, optional): Minimum P/B ratio.
        pb_max (float, optional): Maximum P/B ratio.
        market_cap_min (float, optional): Min market cap (INR Cr).
        market_cap_max (float, optional): Max market cap (INR Cr).
        roce_min (float, optional): Minimum ROCE (%).
        roe_min (float, optional): Minimum ROE (%).
        dividend_yield_min (float, optional): Minimum dividend yield (%).
        sector (str, optional): Filter by sector (exact match).
        sort_by (str, optional): Sort column (default: market_cap).
        limit (int, optional): Max results (default: 50, max: 200).

    Returns:
        JSON: ``{"status": "success", "data": {"stocks": [...], "count": N}}``
    """
    try:
        body = request.get_json(silent=True) or {}
        filters: dict[str, Any] = {}

        # Extract and validate numeric filters
        _NUMERIC_KEYS = [
            "pe_min", "pe_max", "pb_min", "pb_max",
            "market_cap_min", "market_cap_max",
            "roce_min", "roe_min", "dividend_yield_min",
        ]
        for key in _NUMERIC_KEYS:
            if key in body:
                try:
                    filters[key] = float(body[key])
                except (ValueError, TypeError):
                    pass

        # String filters
        if "sector" in body and isinstance(body["sector"], str):
            filters["sector"] = body["sector"]

        # Pagination/sort
        sort_by = body.get("sort_by", "market_cap")
        if not isinstance(sort_by, str):
            sort_by = "market_cap"
        filters["sort_by"] = sort_by

        limit = body.get("limit", 50)
        try:
            limit = min(max(1, int(limit)), 200)
        except (ValueError, TypeError):
            limit = 50
        filters["limit"] = limit

        screener = _get_screener()
        stocks = _run_async(screener.screen(filters))

        return jsonify({
            "status": "success",
            "data": {
                "stocks": [
                    {
                        "symbol": s.symbol,
                        "name": s.name,
                        "exchange": s.exchange,
                        "market_cap": s.market_cap,
                        "pe_ratio": s.pe_ratio,
                        "pb_ratio": s.pb_ratio,
                        "roe": s.roe,
                        "roce": s.roce,
                        "dividend_yield": s.dividend_yield,
                        "sector": s.sector,
                    }
                    for s in stocks
                ],
                "count": len(stocks),
                "filters_applied": {k: v for k, v in filters.items() if k not in ("sort_by", "limit")},
            },
        }), 200
    except Exception:
        logger.exception("fundamental_screen error")
        return jsonify({
            "status": "error",
            "message": "Failed to screen stocks.",
        }), 500
