"""Tax Report Flask endpoints.

Registered as a Blueprint in ``create_flask_app()``.

Endpoints
---------
GET  /v1/tax/summary?fy=2025-26  — TaxSummary JSON
GET  /v1/tax/report?fy=2025-26   — Detailed breakdown by segment
"""
from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from .tax_report import TaxReportGenerator, TaxableTransaction

logger = logging.getLogger("flinttrade.data.tax_routes")

tax_bp = Blueprint("tax", __name__)

# ── Sample data (50 realistic trades across all segments) ────────────────────

_SAMPLE_TRADES: list[TaxableTransaction] = [
    # --- Equity Delivery — LTCG (held > 12 months) ---
    TaxableTransaction("2024-06-10", "RELIANCE", "NSE", "SELL", 20, 2850.0, "equity_delivery", 450, 2200.0),
    TaxableTransaction("2024-07-15", "TCS", "NSE", "SELL", 15, 4200.0, "equity_delivery", 520, 3600.0),
    TaxableTransaction("2024-08-20", "INFY", "NSE", "SELL", 30, 1650.0, "equity_delivery", 400, 1400.0),
    TaxableTransaction("2024-09-05", "HDFCBANK", "NSE", "SELL", 25, 1720.0, "equity_delivery", 380, 1550.0),
    TaxableTransaction("2024-10-12", "WIPRO", "NSE", "SELL", 50, 520.0, "equity_delivery", 600, 400.0),
    # --- Equity Delivery — STCG (held < 12 months) ---
    TaxableTransaction("2025-01-10", "TATAMOTORS", "NSE", "SELL", 40, 980.0, "equity_delivery", 180, 850.0),
    TaxableTransaction("2025-01-20", "SBIN", "NSE", "SELL", 60, 780.0, "equity_delivery", 90, 820.0),
    TaxableTransaction("2025-02-05", "BAJFINANCE", "NSE", "SELL", 10, 7200.0, "equity_delivery", 200, 6800.0),
    TaxableTransaction("2025-02-15", "ITC", "NSE", "SELL", 100, 440.0, "equity_delivery", 150, 420.0),
    TaxableTransaction("2025-03-01", "MARUTI", "NSE", "SELL", 5, 12500.0, "equity_delivery", 270, 11000.0),
    # --- Equity Intraday ---
    TaxableTransaction("2025-01-06", "RELIANCE", "NSE", "BUY", 50, 2780.0, "equity_intraday", 0, 0.0),
    TaxableTransaction("2025-01-06", "RELIANCE", "NSE", "SELL", 50, 2810.0, "equity_intraday", 0, 2780.0),
    TaxableTransaction("2025-01-07", "TCS", "NSE", "BUY", 30, 4100.0, "equity_intraday", 0, 0.0),
    TaxableTransaction("2025-01-07", "TCS", "NSE", "SELL", 30, 4080.0, "equity_intraday", 0, 4100.0),
    TaxableTransaction("2025-01-08", "INFY", "NSE", "BUY", 100, 1620.0, "equity_intraday", 0, 0.0),
    TaxableTransaction("2025-01-08", "INFY", "NSE", "SELL", 100, 1645.0, "equity_intraday", 0, 1620.0),
    TaxableTransaction("2025-01-09", "HDFCBANK", "NSE", "BUY", 80, 1680.0, "equity_intraday", 0, 0.0),
    TaxableTransaction("2025-01-09", "HDFCBANK", "NSE", "SELL", 80, 1695.0, "equity_intraday", 0, 1680.0),
    TaxableTransaction("2025-02-10", "SBIN", "NSE", "BUY", 200, 790.0, "equity_intraday", 0, 0.0),
    TaxableTransaction("2025-02-10", "SBIN", "NSE", "SELL", 200, 785.0, "equity_intraday", 0, 790.0),
    TaxableTransaction("2025-02-12", "TATAMOTORS", "NSE", "BUY", 100, 960.0, "equity_intraday", 0, 0.0),
    TaxableTransaction("2025-02-12", "TATAMOTORS", "NSE", "SELL", 100, 972.0, "equity_intraday", 0, 960.0),
    # --- Futures ---
    TaxableTransaction("2025-01-15", "NIFTY25JANFUT", "NFO", "BUY", 50, 21500.0, "futures", 0, 0.0),
    TaxableTransaction("2025-01-20", "NIFTY25JANFUT", "NFO", "SELL", 50, 21800.0, "futures", 0, 21500.0),
    TaxableTransaction("2025-02-03", "BANKNIFTY25FEBFUT", "NFO", "BUY", 25, 46200.0, "futures", 0, 0.0),
    TaxableTransaction("2025-02-10", "BANKNIFTY25FEBFUT", "NFO", "SELL", 25, 45800.0, "futures", 0, 46200.0),
    TaxableTransaction("2025-02-20", "RELIANCE25FEBFUT", "NFO", "BUY", 250, 2820.0, "futures", 0, 0.0),
    TaxableTransaction("2025-02-25", "RELIANCE25FEBFUT", "NFO", "SELL", 250, 2860.0, "futures", 0, 2820.0),
    TaxableTransaction("2025-03-05", "NIFTY25MARFUT", "NFO", "BUY", 50, 22100.0, "futures", 0, 0.0),
    TaxableTransaction("2025-03-10", "NIFTY25MARFUT", "NFO", "SELL", 50, 22300.0, "futures", 0, 22100.0),
    # --- Options ---
    TaxableTransaction("2025-01-10", "NIFTY25JAN21500CE", "NFO", "BUY", 50, 250.0, "options", 0, 0.0),
    TaxableTransaction("2025-01-15", "NIFTY25JAN21500CE", "NFO", "SELL", 50, 380.0, "options", 0, 250.0),
    TaxableTransaction("2025-01-22", "NIFTY25JAN21800PE", "NFO", "BUY", 50, 180.0, "options", 0, 0.0),
    TaxableTransaction("2025-01-24", "NIFTY25JAN21800PE", "NFO", "SELL", 50, 120.0, "options", 0, 180.0),
    TaxableTransaction("2025-02-05", "BANKNIFTY25FEB46000CE", "NFO", "BUY", 25, 400.0, "options", 0, 0.0),
    TaxableTransaction("2025-02-07", "BANKNIFTY25FEB46000CE", "NFO", "SELL", 25, 520.0, "options", 0, 400.0),
    TaxableTransaction("2025-02-14", "RELIANCE25FEB2800CE", "NFO", "BUY", 250, 60.0, "options", 0, 0.0),
    TaxableTransaction("2025-02-18", "RELIANCE25FEB2800CE", "NFO", "SELL", 250, 45.0, "options", 0, 60.0),
    TaxableTransaction("2025-03-03", "NIFTY25MAR22000CE", "NFO", "BUY", 50, 320.0, "options", 0, 0.0),
    TaxableTransaction("2025-03-07", "NIFTY25MAR22000CE", "NFO", "SELL", 50, 410.0, "options", 0, 320.0),
    TaxableTransaction("2025-03-10", "NIFTY25MAR22200PE", "NFO", "BUY", 50, 200.0, "options", 0, 0.0),
    TaxableTransaction("2025-03-12", "NIFTY25MAR22200PE", "NFO", "SELL", 50, 150.0, "options", 0, 200.0),
    # --- Commodity ---
    TaxableTransaction("2025-01-12", "GOLDM25FEB", "MCX", "BUY", 10, 62500.0, "commodity", 0, 0.0),
    TaxableTransaction("2025-01-20", "GOLDM25FEB", "MCX", "SELL", 10, 63200.0, "commodity", 0, 62500.0),
    TaxableTransaction("2025-02-01", "CRUDEOIL25MAR", "MCX", "BUY", 100, 6200.0, "commodity", 0, 0.0),
    TaxableTransaction("2025-02-10", "CRUDEOIL25MAR", "MCX", "SELL", 100, 6050.0, "commodity", 0, 6200.0),
    TaxableTransaction("2025-02-20", "SILVERM25MAR", "MCX", "BUY", 5, 75000.0, "commodity", 0, 0.0),
    TaxableTransaction("2025-02-28", "SILVERM25MAR", "MCX", "SELL", 5, 76500.0, "commodity", 0, 75000.0),
    TaxableTransaction("2025-03-05", "NATURALGAS25APR", "MCX", "BUY", 250, 220.0, "commodity", 0, 0.0),
    TaxableTransaction("2025-03-10", "NATURALGAS25APR", "MCX", "SELL", 250, 215.0, "commodity", 0, 220.0),
]

_generator = TaxReportGenerator()
_TAX_DATA_SOURCE = "sample"


def _sample_meta() -> dict[str, Any]:
    """Return source metadata for the current built-in tax ledger."""
    return {"is_sample_data": True, "data_source": _TAX_DATA_SOURCE}


def _get_trades_for_fy(fy: str) -> list[TaxableTransaction]:
    """Return sample trades. In production, this would query DuckDB."""
    # For now, return all sample trades regardless of FY
    return _SAMPLE_TRADES


# ── Endpoints ────────────────────────────────────────────────────────────────

def _current_fy() -> str:
    """Return the current Indian fiscal year (e.g. ``"2026-27"``).

    Indian FY runs April → March. Before 1 April we are still in the
    previous-calendar-year FY; on or after 1 April we move into the
    current-calendar-year FY. Used as the default for `fy` query
    parameters so the endpoint always tracks the live calendar instead
    of a hardcoded "2025-26" that goes stale on FY-rollover.
    """
    import datetime as _dt
    today = _dt.date.today()
    start = today.year - 1 if today.month < 4 else today.year
    return f"{start}-{str(start + 1)[2:]}"


@tax_bp.route("/v1/tax/summary", methods=["GET"])
def tax_summary() -> tuple[Any, int]:
    """Return tax summary for a financial year.

    Query parameters:
        fy (str): Financial year (e.g. "2025-26"). Defaults to the
            currently-active Indian fiscal year computed by
            ``_current_fy()`` — see that helper for FY-rollover semantics.

    Returns:
        JSON ``{"status": "success", "is_sample_data": true, "data": {...}}``
        with TaxSummary fields. The tax dataset is still the built-in sample
        ledger, so both the envelope and payload declare that explicitly.
    """
    fy = request.args.get("fy", _current_fy())
    trades = _get_trades_for_fy(fy)
    summary = _generator.compute_pnl_by_segment(trades, fy)
    sample_meta = _sample_meta()

    return jsonify({
        "status": "success",
        **sample_meta,
        "data": {
            "fy": summary.fy,
            "equity_ltcg": summary.equity_ltcg,
            "equity_stcg": summary.equity_stcg,
            "intraday_pnl": summary.intraday_pnl,
            "fno_pnl": summary.fno_pnl,
            "commodity_pnl": summary.commodity_pnl,
            "stt_paid": summary.stt_paid,
            "turnover": summary.turnover,
            "tax_liability_estimated": summary.tax_liability_estimated,
            "ltcg_exemption_used": summary.ltcg_exemption_used,
            "needs_audit": summary.needs_audit,
            "trade_count": summary.trade_count,
            **sample_meta,
        },
    }), 200


@tax_bp.route("/v1/tax/report", methods=["GET"])
def tax_report() -> tuple[Any, int]:
    """Return detailed tax report with per-segment breakdown.

    Query parameters:
        fy (str): Financial year (e.g. "2025-26"). Defaults to the
            currently-active Indian fiscal year.

    Returns:
        JSON ``{"status": "success", "is_sample_data": true, "data": {...}}``
        with summary and segments from the built-in sample ledger.
    """
    fy = request.args.get("fy", _current_fy())
    trades = _get_trades_for_fy(fy)
    report = _generator.generate_report(trades, fy)
    sample_meta = _sample_meta()
    report = {
        **report,
        **sample_meta,
        "summary": {
            **report["summary"],
            **sample_meta,
        },
    }

    return jsonify({"status": "success", **sample_meta, "data": report}), 200
