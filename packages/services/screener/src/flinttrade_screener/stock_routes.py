"""Flask blueprint for stock screener endpoints.

Provides GET /v1/stocks/scan for querying stock fundamentals.
Seeds the StockCache with 30 Indian large-cap stocks on first request.

The StockCache is DuckDB-backed with 24-hour TTL; seeded data refreshes
automatically when stale.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from flask import Blueprint, jsonify, request

from .stock_cache import StockCache, StockFundamentals

logger = logging.getLogger("flinttrade.screener.stock_routes")

stock_bp = Blueprint("stocks", __name__, url_prefix="/v1/stocks")


# ---------------------------------------------------------------------------
# Seed data — 30 real Indian large-cap stocks with realistic fundamentals
# ---------------------------------------------------------------------------

_SEED_STOCKS: list[dict[str, Any]] = [
    {"symbol": "RELIANCE", "name": "Reliance Industries Ltd", "exchange": "NSE", "market_cap": 1950000, "pe_ratio": 28.5, "pb_ratio": 2.8, "roe": 12.5, "roce": 15.2, "dividend_yield": 0.4, "sector": "Energy"},
    {"symbol": "TCS", "name": "Tata Consultancy Services Ltd", "exchange": "NSE", "market_cap": 1420000, "pe_ratio": 32.1, "pb_ratio": 14.2, "roe": 48.6, "roce": 62.3, "dividend_yield": 1.2, "sector": "IT"},
    {"symbol": "HDFCBANK", "name": "HDFC Bank Ltd", "exchange": "NSE", "market_cap": 1280000, "pe_ratio": 19.8, "pb_ratio": 3.1, "roe": 16.8, "roce": 0.0, "dividend_yield": 1.1, "sector": "Banking"},
    {"symbol": "INFY", "name": "Infosys Ltd", "exchange": "NSE", "market_cap": 750000, "pe_ratio": 28.9, "pb_ratio": 8.5, "roe": 32.1, "roce": 42.8, "dividend_yield": 2.1, "sector": "IT"},
    {"symbol": "ICICIBANK", "name": "ICICI Bank Ltd", "exchange": "NSE", "market_cap": 720000, "pe_ratio": 18.2, "pb_ratio": 3.4, "roe": 18.2, "roce": 0.0, "dividend_yield": 0.8, "sector": "Banking"},
    {"symbol": "BHARTIARTL", "name": "Bharti Airtel Ltd", "exchange": "NSE", "market_cap": 680000, "pe_ratio": 75.3, "pb_ratio": 7.2, "roe": 12.8, "roce": 11.5, "dividend_yield": 0.5, "sector": "Telecom"},
    {"symbol": "SBIN", "name": "State Bank of India", "exchange": "NSE", "market_cap": 620000, "pe_ratio": 9.5, "pb_ratio": 1.8, "roe": 18.5, "roce": 0.0, "dividend_yield": 1.7, "sector": "Banking"},
    {"symbol": "ITC", "name": "ITC Ltd", "exchange": "NSE", "market_cap": 580000, "pe_ratio": 27.2, "pb_ratio": 7.8, "roe": 28.5, "roce": 36.2, "dividend_yield": 3.1, "sector": "FMCG"},
    {"symbol": "HINDUNILVR", "name": "Hindustan Unilever Ltd", "exchange": "NSE", "market_cap": 560000, "pe_ratio": 58.5, "pb_ratio": 10.2, "roe": 18.5, "roce": 25.8, "dividend_yield": 1.7, "sector": "FMCG"},
    {"symbol": "LT", "name": "Larsen & Toubro Ltd", "exchange": "NSE", "market_cap": 520000, "pe_ratio": 35.2, "pb_ratio": 5.8, "roe": 15.2, "roce": 18.5, "dividend_yield": 0.9, "sector": "Infra"},
    {"symbol": "BAJFINANCE", "name": "Bajaj Finance Ltd", "exchange": "NSE", "market_cap": 480000, "pe_ratio": 42.5, "pb_ratio": 8.2, "roe": 22.5, "roce": 0.0, "dividend_yield": 0.4, "sector": "Finance"},
    {"symbol": "KOTAKBANK", "name": "Kotak Mahindra Bank Ltd", "exchange": "NSE", "market_cap": 420000, "pe_ratio": 22.8, "pb_ratio": 3.5, "roe": 14.2, "roce": 0.0, "dividend_yield": 0.1, "sector": "Banking"},
    {"symbol": "MARUTI", "name": "Maruti Suzuki India Ltd", "exchange": "NSE", "market_cap": 380000, "pe_ratio": 30.5, "pb_ratio": 5.2, "roe": 16.8, "roce": 22.5, "dividend_yield": 0.8, "sector": "Auto"},
    {"symbol": "HCLTECH", "name": "HCL Technologies Ltd", "exchange": "NSE", "market_cap": 370000, "pe_ratio": 25.8, "pb_ratio": 7.1, "roe": 25.2, "roce": 32.5, "dividend_yield": 3.2, "sector": "IT"},
    {"symbol": "SUNPHARMA", "name": "Sun Pharmaceutical Industries Ltd", "exchange": "NSE", "market_cap": 360000, "pe_ratio": 38.2, "pb_ratio": 5.5, "roe": 14.8, "roce": 18.2, "dividend_yield": 0.7, "sector": "Pharma"},
    {"symbol": "TITAN", "name": "Titan Company Ltd", "exchange": "NSE", "market_cap": 340000, "pe_ratio": 85.2, "pb_ratio": 18.5, "roe": 25.8, "roce": 32.1, "dividend_yield": 0.3, "sector": "Consumer"},
    {"symbol": "TATAMOTORS", "name": "Tata Motors Ltd", "exchange": "NSE", "market_cap": 320000, "pe_ratio": 12.5, "pb_ratio": 3.8, "roe": 28.5, "roce": 15.8, "dividend_yield": 0.5, "sector": "Auto"},
    {"symbol": "AXISBANK", "name": "Axis Bank Ltd", "exchange": "NSE", "market_cap": 310000, "pe_ratio": 14.5, "pb_ratio": 2.2, "roe": 16.5, "roce": 0.0, "dividend_yield": 0.1, "sector": "Banking"},
    {"symbol": "ADANIENT", "name": "Adani Enterprises Ltd", "exchange": "NSE", "market_cap": 300000, "pe_ratio": 95.2, "pb_ratio": 12.5, "roe": 10.2, "roce": 12.8, "dividend_yield": 0.1, "sector": "Infra"},
    {"symbol": "NTPC", "name": "NTPC Ltd", "exchange": "NSE", "market_cap": 290000, "pe_ratio": 18.5, "pb_ratio": 2.8, "roe": 12.8, "roce": 10.5, "dividend_yield": 2.2, "sector": "Energy"},
    {"symbol": "ONGC", "name": "Oil and Natural Gas Corporation Ltd", "exchange": "NSE", "market_cap": 280000, "pe_ratio": 7.8, "pb_ratio": 1.2, "roe": 15.2, "roce": 18.5, "dividend_yield": 4.5, "sector": "Energy"},
    {"symbol": "WIPRO", "name": "Wipro Ltd", "exchange": "NSE", "market_cap": 260000, "pe_ratio": 22.5, "pb_ratio": 3.8, "roe": 16.2, "roce": 20.5, "dividend_yield": 0.1, "sector": "IT"},
    {"symbol": "POWERGRID", "name": "Power Grid Corporation of India Ltd", "exchange": "NSE", "market_cap": 250000, "pe_ratio": 15.2, "pb_ratio": 2.5, "roe": 18.2, "roce": 12.8, "dividend_yield": 3.8, "sector": "Energy"},
    {"symbol": "TATASTEEL", "name": "Tata Steel Ltd", "exchange": "NSE", "market_cap": 220000, "pe_ratio": 8.5, "pb_ratio": 1.5, "roe": 18.5, "roce": 15.2, "dividend_yield": 2.5, "sector": "Metals"},
    {"symbol": "COALINDIA", "name": "Coal India Ltd", "exchange": "NSE", "market_cap": 210000, "pe_ratio": 6.8, "pb_ratio": 3.2, "roe": 52.5, "roce": 68.2, "dividend_yield": 5.8, "sector": "Metals"},
    {"symbol": "DRREDDY", "name": "Dr. Reddy's Laboratories Ltd", "exchange": "NSE", "market_cap": 200000, "pe_ratio": 22.8, "pb_ratio": 4.2, "roe": 18.5, "roce": 22.5, "dividend_yield": 0.6, "sector": "Pharma"},
    {"symbol": "NESTLEIND", "name": "Nestle India Ltd", "exchange": "NSE", "market_cap": 195000, "pe_ratio": 82.5, "pb_ratio": 72.5, "roe": 108.5, "roce": 142.5, "dividend_yield": 1.5, "sector": "FMCG"},
    {"symbol": "ULTRACEMCO", "name": "UltraTech Cement Ltd", "exchange": "NSE", "market_cap": 190000, "pe_ratio": 42.5, "pb_ratio": 5.8, "roe": 12.8, "roce": 15.2, "dividend_yield": 0.4, "sector": "Infra"},
    {"symbol": "JSWSTEEL", "name": "JSW Steel Ltd", "exchange": "NSE", "market_cap": 185000, "pe_ratio": 35.2, "pb_ratio": 3.5, "roe": 10.5, "roce": 12.8, "dividend_yield": 0.8, "sector": "Metals"},
    {"symbol": "TECHM", "name": "Tech Mahindra Ltd", "exchange": "NSE", "market_cap": 180000, "pe_ratio": 38.5, "pb_ratio": 5.2, "roe": 12.5, "roce": 15.8, "dividend_yield": 1.8, "sector": "IT"},
]

# Unique sectors from seed data for filter dropdown
_SECTORS: list[str] = sorted({s["sector"] for s in _SEED_STOCKS})

# Module-level cache instance (lazy-initialised)
_cache: StockCache | None = None


def _get_cache() -> StockCache:
    """Return the module-level StockCache, creating it on first access."""
    global _cache  # noqa: PLW0603
    if _cache is None:
        _cache = StockCache()
    return _cache


def _ensure_seeded(cache: StockCache) -> None:
    """Seed the cache if it is empty or all rows have expired.

    Checks by looking up the first symbol; if missing, re-seeds all 30.
    """
    if cache.get(_SEED_STOCKS[0]["symbol"]) is not None:
        return  # cache is warm

    logger.info("Seeding StockCache with %d large-cap stocks", len(_SEED_STOCKS))
    now = time.time()
    for s in _SEED_STOCKS:
        cache.upsert(StockFundamentals(
            symbol=s["symbol"],
            name=s["name"],
            exchange=s["exchange"],
            market_cap=s["market_cap"],
            pe_ratio=s["pe_ratio"],
            pb_ratio=s["pb_ratio"],
            roe=s["roe"],
            roce=s["roce"],
            dividend_yield=s["dividend_yield"],
            sector=s["sector"],
            updated_at=now,
        ))
    logger.info("StockCache seeded successfully")


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@stock_bp.route("/scan", methods=["GET"])
def stock_scan() -> tuple[Any, int]:
    """Scan stocks with optional filters and sorting.

    Query parameters:
        sector (str, optional): Filter by sector name (exact match).
        min_market_cap (float, optional): Minimum market cap in INR crore.
        max_pe (float, optional): Maximum PE ratio filter.
        sort_by (str, optional): Column to sort by (default: market_cap).
        limit (int, optional): Max results to return (default: 50, max: 200).

    Returns:
        JSON: ``{"status": "success", "data": {"stocks": [...], "sectors": [...], "count": N}}``
    """
    try:
        cache = _get_cache()
        _ensure_seeded(cache)

        # Parse query parameters
        sector = request.args.get("sector", type=str)
        min_market_cap = request.args.get("min_market_cap", type=float)
        max_pe = request.args.get("max_pe", type=float)
        sort_by = request.args.get("sort_by", default="market_cap", type=str)
        limit = request.args.get("limit", default=50, type=int)
        limit = min(max(1, limit), 200)  # clamp 1–200

        # Build filter dict for StockCache.scan()
        filters: dict[str, Any] = {}
        if sector:
            filters["sector_eq"] = sector
        if min_market_cap is not None:
            filters["market_cap_gt"] = min_market_cap
        if max_pe is not None:
            filters["pe_lt"] = max_pe

        stocks = cache.scan(filters=filters, sort_by=sort_by, limit=limit)

        stock_dicts = [
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
        ]

        return jsonify({
            "status": "success",
            "data": {
                "stocks": stock_dicts,
                "sectors": _SECTORS,
                "count": len(stock_dicts),
            },
        }), 200

    except Exception:
        logger.exception("stock_scan error")
        return jsonify({
            "status": "error",
            "message": "Internal server error",
        }), 500
