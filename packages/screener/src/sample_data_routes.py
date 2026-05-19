"""Sample-data Flask blueprint — honest placeholder endpoints.

This module exposes Flask routes for eight frontend endpoints whose
real backends are not yet built. Each returns ``is_sample_data: true``
with a realistic-but-clearly-flagged response so:

1. The terminal stops generating 404s in production (closes the "0 errors
   after shipping" gap).
2. Widgets that already handle ``is_sample_data`` (most of the affected
   ones do) render their "Demo" badge instead of an error panel.
3. Future contributors replacing these stubs with real implementations
   only need to swap the handler body — the route and response shape
   stay the same.

The eight endpoints are (full URL after WSGI prefix strip):

- ``GET /api/v1/etf/screener``
- ``GET /api/v1/sectors/rotation``
- ``GET /api/v1/analytics/risk-return``
- ``GET /api/v1/crypto/funding_rates``
- ``GET /api/v1/global/indices``
- ``GET /api/v1/screener/shareholding?symbol=<sym>``
- ``GET /api/v1/screener/sector-constituents?sector=<sec>``
- ``GET /api/v1/screener/lot-size?symbol=<sym>&exchange=<exch>``

Response shapes mirror the corresponding TypeScript interfaces in
``packages/terminal/src/services/ftApi.{analysis,screener}.ts``.
"""

from __future__ import annotations

import datetime as _dt
import logging
from typing import Any

from flask import Blueprint, jsonify, request

logger = logging.getLogger("flinttrade.screener.sample_data")

sample_data_bp = Blueprint("sample_data", __name__, url_prefix="/api/v1")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# GET /api/v1/etf/screener
# ---------------------------------------------------------------------------


_SAMPLE_ETFS: list[dict[str, Any]] = [
    {
        "symbol": "NIFTYBEES",
        "name": "Nippon India ETF Nifty BeES",
        "category": "Equity",
        "exchange": "NSE",
        "price": 268.45,
        "change_1d": 0.42,
        "change_1w": 1.18,
        "change_1m": 2.71,
        "change_3m": 6.14,
        "change_6m": 9.32,
        "change_1y": 17.85,
        "volume": 4218304,
        "week52_high": 272.10,
        "week52_low": 215.30,
        "expense_ratio": 0.05,
        "aum_cr": 35840.0,
        "momentum_score": 0.82,
        "sparkline": [0.40, 0.44, 0.46, 0.45, 0.48, 0.50, 0.52, 0.55, 0.58, 0.56,
                      0.60, 0.62, 0.64, 0.66, 0.68, 0.70, 0.72, 0.74, 0.73, 0.75,
                      0.77, 0.79, 0.81, 0.82, 0.84, 0.86, 0.88, 0.90, 0.92, 0.94],
        "annual_returns": {"2023": 18.5, "2024": 14.2, "2025": 12.8},
    },
    {
        "symbol": "GOLDBEES",
        "name": "Nippon India ETF Gold BeES",
        "category": "Gold",
        "exchange": "NSE",
        "price": 58.20,
        "change_1d": 0.18,
        "change_1w": 0.92,
        "change_1m": 2.04,
        "change_3m": 4.78,
        "change_6m": 8.91,
        "change_1y": 22.15,
        "volume": 1842910,
        "week52_high": 59.40,
        "week52_low": 47.10,
        "expense_ratio": 0.79,
        "aum_cr": 8920.0,
        "momentum_score": 0.74,
        "sparkline": [0.50] * 30,
        "annual_returns": {"2023": 12.4, "2024": 18.7, "2025": 22.1},
    },
    {
        "symbol": "BANKBEES",
        "name": "Nippon India ETF Bank BeES",
        "category": "Sector",
        "exchange": "NSE",
        "price": 542.10,
        "change_1d": -0.21,
        "change_1w": 0.85,
        "change_1m": 1.94,
        "change_3m": 5.62,
        "change_6m": 7.85,
        "change_1y": 14.32,
        "volume": 2104382,
        "week52_high": 558.20,
        "week52_low": 458.40,
        "expense_ratio": 0.18,
        "aum_cr": 6420.0,
        "momentum_score": 0.71,
        "sparkline": [0.45] * 30,
        "annual_returns": {"2023": 16.8, "2024": 11.2, "2025": 9.4},
    },
]


@sample_data_bp.route("/etf/screener", methods=["GET"])
def get_etf_screener() -> Any:
    """Return a placeholder ETF screener payload flagged as sample data."""
    return jsonify({
        "etfs": _SAMPLE_ETFS,
        "updated_at": _utc_iso(),
        "is_sample_data": True,
    })


# ---------------------------------------------------------------------------
# GET /api/v1/sectors/rotation
# ---------------------------------------------------------------------------


_SAMPLE_SECTORS: list[dict[str, Any]] = [
    {
        "symbol": "BANKNIFTY",
        "name": "Nifty Bank",
        "change_1d": -0.21, "change_1w": 0.85, "change_1m": 1.94,
        "change_3m": 5.62, "change_6m": 7.85, "change_1y": 14.32,
        "market_cap_cr": 4_250_000.0,
        "momentum_score": 0.71,
        "quadrant": "improving",
    },
    {
        "symbol": "CNXIT",
        "name": "Nifty IT",
        "change_1d": 0.42, "change_1w": -1.18, "change_1m": -2.71,
        "change_3m": -6.14, "change_6m": -9.32, "change_1y": 3.85,
        "market_cap_cr": 2_100_000.0,
        "momentum_score": 0.32,
        "quadrant": "lagging",
    },
    {
        "symbol": "CNXAUTO",
        "name": "Nifty Auto",
        "change_1d": 0.62, "change_1w": 1.85, "change_1m": 4.71,
        "change_3m": 11.14, "change_6m": 15.32, "change_1y": 28.85,
        "market_cap_cr": 1_840_000.0,
        "momentum_score": 0.92,
        "quadrant": "leading",
    },
    {
        "symbol": "CNXFMCG",
        "name": "Nifty FMCG",
        "change_1d": -0.12, "change_1w": -0.45, "change_1m": -1.71,
        "change_3m": -3.14, "change_6m": -5.32, "change_1y": 1.85,
        "market_cap_cr": 1_920_000.0,
        "momentum_score": 0.42,
        "quadrant": "weakening",
    },
]


@sample_data_bp.route("/sectors/rotation", methods=["GET"])
def get_sectors_rotation() -> Any:
    """Return a placeholder sector-rotation payload flagged as sample data."""
    return jsonify({
        "sectors": _SAMPLE_SECTORS,
        "updated_at": _utc_iso(),
        "is_sample_data": True,
    })


# ---------------------------------------------------------------------------
# GET /api/v1/analytics/risk-return
# ---------------------------------------------------------------------------


_SAMPLE_RR_POINTS: list[dict[str, Any]] = [
    {"symbol": "NIFTYBEES",  "name": "Nifty 50 ETF",     "category": "Equity",        "annualised_return": 17.85, "annualised_volatility": 14.20, "sharpe_ratio": 0.92},
    {"symbol": "BANKBEES",   "name": "Bank Nifty ETF",   "category": "Sector",        "annualised_return": 14.32, "annualised_volatility": 18.40, "sharpe_ratio": 0.58},
    {"symbol": "GOLDBEES",   "name": "Gold ETF",         "category": "Gold",          "annualised_return": 22.15, "annualised_volatility": 16.10, "sharpe_ratio": 1.10},
    {"symbol": "ICICILIQ",   "name": "ICICI Liquid ETF", "category": "Debt",          "annualised_return":  6.80, "annualised_volatility":  1.20, "sharpe_ratio": 1.50},
    {"symbol": "MAFANG",     "name": "Motilal FANG ETF", "category": "International", "annualised_return": 28.40, "annualised_volatility": 22.10, "sharpe_ratio": 1.05},
]


@sample_data_bp.route("/analytics/risk-return", methods=["GET"])
def get_risk_return() -> Any:
    """Return a placeholder risk/return scatter dataset flagged as sample data."""
    best = max(_SAMPLE_RR_POINTS, key=lambda p: p["sharpe_ratio"])
    return jsonify({
        "points": _SAMPLE_RR_POINTS,
        "avg_return": sum(p["annualised_return"] for p in _SAMPLE_RR_POINTS) / len(_SAMPLE_RR_POINTS),
        "avg_volatility": sum(p["annualised_volatility"] for p in _SAMPLE_RR_POINTS) / len(_SAMPLE_RR_POINTS),
        "best_sharpe_symbol": best["symbol"],
        "best_sharpe": best["sharpe_ratio"],
        "updated_at": _utc_iso(),
        "is_sample_data": True,
    })


# ---------------------------------------------------------------------------
# GET /api/v1/crypto/funding_rates
# ---------------------------------------------------------------------------


_SAMPLE_FUNDING_RATES: list[dict[str, Any]] = [
    {
        "symbol": "BTCUSD",
        "rate": 0.00012,
        "predicted_rate": 0.00015,
        "next_funding_ms": int(_dt.datetime.now(_dt.timezone.utc).timestamp() * 1000) + 3 * 3600 * 1000,
        "history": [0.0001, 0.00011, 0.00012, 0.00010, 0.00013, 0.00012, 0.00011, 0.00012],
        "open_interest_usd": 8_400_000_000.0,
    },
    {
        "symbol": "ETHUSD",
        "rate": 0.00009,
        "predicted_rate": 0.00008,
        "next_funding_ms": int(_dt.datetime.now(_dt.timezone.utc).timestamp() * 1000) + 3 * 3600 * 1000,
        "history": [0.00008, 0.00009, 0.00010, 0.00008, 0.00009, 0.00008, 0.00009, 0.00009],
        "open_interest_usd": 4_200_000_000.0,
    },
]


@sample_data_bp.route("/crypto/funding_rates", methods=["GET"])
def get_crypto_funding_rates() -> Any:
    """Return a placeholder perp funding-rate payload flagged as sample data.

    The frontend ``FundingRatesResponse`` interface doesn't carry
    ``is_sample_data``, but a top-level flag is still useful for any
    future caller that wants to branch on it. The widget already
    gates ``getCryptoFundingRates`` on ``isConnected`` so it falls
    back to its own static sample when the user isn't logged in.
    """
    return jsonify({
        "rates": _SAMPLE_FUNDING_RATES,
        "updated_at": _utc_iso(),
        "is_sample_data": True,
    })


# ---------------------------------------------------------------------------
# GET /api/v1/global/indices
# ---------------------------------------------------------------------------


_SAMPLE_GLOBAL_INDICES: list[dict[str, Any]] = [
    {"id": "NIFTY",   "name": "Nifty 50",    "region": "India",  "ltp": 24850.50, "change":  142.30, "change_pct": 0.57, "history": [24700, 24750, 24780, 24820, 24850]},
    {"id": "SENSEX",  "name": "BSE Sensex",  "region": "India",  "ltp": 81420.30, "change":  484.20, "change_pct": 0.60, "history": [80900, 81000, 81200, 81350, 81420]},
    {"id": "SPX",     "name": "S&P 500",     "region": "US",     "ltp":  5874.20, "change":   12.40, "change_pct": 0.21, "history": [5840, 5850, 5860, 5870, 5874]},
    {"id": "DJI",     "name": "Dow Jones",   "region": "US",     "ltp": 43240.10, "change":  -85.20, "change_pct": -0.20, "history": [43350, 43320, 43290, 43260, 43240]},
    {"id": "NDX",     "name": "Nasdaq 100",  "region": "US",     "ltp": 20410.50, "change":   98.30, "change_pct": 0.48, "history": [20280, 20320, 20360, 20390, 20410]},
    {"id": "FTSE",    "name": "FTSE 100",    "region": "Europe", "ltp":  8214.50, "change":   18.20, "change_pct": 0.22, "history": [8180, 8195, 8205, 8210, 8214]},
    {"id": "DAX",     "name": "DAX",         "region": "Europe", "ltp": 19420.30, "change":   42.10, "change_pct": 0.22, "history": [19350, 19370, 19390, 19410, 19420]},
    {"id": "NIKKEI",  "name": "Nikkei 225",  "region": "Asia",   "ltp": 38420.10, "change":  198.30, "change_pct": 0.52, "history": [38150, 38220, 38300, 38380, 38420]},
    {"id": "HSI",     "name": "Hang Seng",   "region": "Asia",   "ltp": 19840.40, "change":  -85.20, "change_pct": -0.43, "history": [19950, 19920, 19890, 19860, 19840]},
]


@sample_data_bp.route("/global/indices", methods=["GET"])
def get_global_indices() -> Any:
    """Return a placeholder global-indices payload flagged as sample data."""
    return jsonify({
        "indices": _SAMPLE_GLOBAL_INDICES,
        "updated_at": _utc_iso(),
        "is_sample_data": True,
    })


# ---------------------------------------------------------------------------
# GET /api/v1/screener/shareholding?symbol=<sym>
# ---------------------------------------------------------------------------


def _empty_quarterly_history(value: float) -> list[dict[str, Any]]:
    """Build a placeholder 8-quarter history at a constant value."""
    # Build 8 quarters ending with the current FY's most recent close.
    now = _dt.date.today()
    quarters: list[dict[str, Any]] = []
    for i in range(8):
        # IST FY: 2025-26 = Apr 2025 → Mar 2026. Quarters: Q1=Jun, Q2=Sep, Q3=Dec, Q4=Mar.
        offset_months = i * 3
        month = ((now.month - 1 - offset_months) % 12) + 1
        year = now.year - ((now.month - 1 - offset_months) // 12 * -1)  # rough — placeholder anyway
        quarters.append({"quarter": f"Q{((month - 1) // 3) + 1} {year}", "percentage": value})
    return list(reversed(quarters))


@sample_data_bp.route("/screener/shareholding", methods=["GET"])
def get_shareholding() -> Any:
    """Return a placeholder shareholding/financials payload flagged as sample data."""
    symbol = (request.args.get("symbol") or "RELIANCE").upper()
    today = _dt.date.today()
    fy_start = today.year - 1 if today.month < 4 else today.year
    fy_label = f"FY{str(fy_start + 1)[2:]}"
    return jsonify({
        "is_sample_data": True,
        "shareholding": {
            "symbol": symbol,
            "as_of_quarter": fy_label,
            "promoter_pct": 50.4,
            "fii_pct": 22.1,
            "dii_pct": 14.6,
            "public_pct": 12.5,
            "government_pct": 0.4,
            "promoter_history": _empty_quarterly_history(50.4),
            "fii_history": _empty_quarterly_history(22.1),
            "dii_history": _empty_quarterly_history(14.6),
            "public_history": _empty_quarterly_history(12.5),
        },
        "financials": {
            "symbol": symbol,
            "revenue": None,
            "net_profit": None,
            "operating_cash_flow": None,
            "debt_to_equity": None,
            "roe": None,
            "roce": None,
            "pe_ratio": None,
            "market_cap": None,
            "book_value": None,
            "annual_history": [],
        },
        "announcements": [],
    })


# ---------------------------------------------------------------------------
# GET /api/v1/screener/sector-constituents?sector=<sec>
# ---------------------------------------------------------------------------


_SAMPLE_RRG_TAIL = [
    {"rs_ratio": 99.5, "rs_momentum": 99.5, "ts": "2026-04-01"},
    {"rs_ratio": 99.8, "rs_momentum": 100.0, "ts": "2026-04-15"},
    {"rs_ratio": 100.1, "rs_momentum": 100.4, "ts": "2026-04-29"},
    {"rs_ratio": 100.5, "rs_momentum": 100.8, "ts": "2026-05-13"},
]


@sample_data_bp.route("/screener/sector-constituents", methods=["GET"])
def get_sector_constituents() -> Any:
    """Return a placeholder sector-RRG-constituents payload flagged as sample data."""
    sector = request.args.get("sector") or "BANKNIFTY"
    constituents = [
        {
            "symbol": "HDFCBANK",  "name": "HDFC Bank",        "weight": 28.4,
            "tail": _SAMPLE_RRG_TAIL, "current_quadrant": "leading",
        },
        {
            "symbol": "ICICIBANK", "name": "ICICI Bank",       "weight": 22.1,
            "tail": _SAMPLE_RRG_TAIL, "current_quadrant": "improving",
        },
        {
            "symbol": "SBIN",      "name": "State Bank of India", "weight": 11.8,
            "tail": _SAMPLE_RRG_TAIL, "current_quadrant": "weakening",
        },
        {
            "symbol": "KOTAKBANK", "name": "Kotak Mahindra Bank", "weight": 9.2,
            "tail": _SAMPLE_RRG_TAIL, "current_quadrant": "lagging",
        },
    ]
    return jsonify({
        "sector": sector,
        "benchmark": "NIFTY",
        "is_sample_data": True,
        "constituents": constituents,
    })


# ---------------------------------------------------------------------------
# GET /api/v1/screener/lot-size?symbol=<sym>&exchange=<exch>
# ---------------------------------------------------------------------------


# Common F&O lot sizes — pulled from typical NSE/MCX values. Built-in
# fallback for the most-requested symbols; everything else returns the
# generic ``50`` default (NIFTY lot size) — the ScalperWidget already
# falls back to its built-in config table when this returns 0 or fails,
# so an approximate answer is better than 404.
_LOT_SIZE_TABLE: dict[str, int] = {
    "NIFTY": 75,
    "BANKNIFTY": 30,
    "FINNIFTY": 65,
    "MIDCPNIFTY": 120,
    "SENSEX": 20,
    "BANKEX": 30,
    "CRUDEOIL": 100,
    "NATURALGAS": 1250,
    "GOLD": 100,
    "SILVER": 30,
    "COPPER": 2500,
    "USDINR": 1000,
    "EURINR": 1000,
    "GBPINR": 1000,
    "JPYINR": 1000,
}


@sample_data_bp.route("/screener/lot-size", methods=["GET"])
def get_lot_size() -> Any:
    """Return the lot size for a derivatives symbol.

    Looks the symbol up in a built-in table of common F&O lot sizes
    (NSE / BSE / MCX / CDS). Falls back to ``0`` for unknown symbols,
    which the frontend ``ScalperWidget`` interprets as "use the
    widget's built-in config" rather than a hard error.
    """
    symbol = (request.args.get("symbol") or "").upper().strip()
    exchange = (request.args.get("exchange") or "NFO").upper().strip()

    # Strip expiry suffix (e.g. NIFTY25MAYFUT → NIFTY) for the lookup.
    base = symbol
    for suffix in ("FUT", "CE", "PE"):
        if base.endswith(suffix):
            # Trim digits + month chars before the suffix.
            base = base[: -len(suffix)]
            # Keep stripping digits and short month abbrevs.
            while base and (base[-1].isdigit() or base[-3:].isalpha() and len(base) > 3):
                if base[-1].isdigit():
                    base = base[:-1]
                else:
                    break
            break
    base = base.rstrip("0123456789").rstrip("JFMASONDjfmasond")

    lot_size = _LOT_SIZE_TABLE.get(base, 0)
    return jsonify({
        "symbol": symbol,
        "exchange": exchange,
        "lot_size": lot_size,
    })
