"""Tax Report Generator: indicative Indian tax P&L reports from trade history.

Classifies trades by segment (equity delivery LTCG/STCG, intraday, F&O,
commodity), computes P&L per segment, STT, turnover, an estimated tax
liability, and a preliminary audit-threshold signal.

Simplified tax-estimate assumptions:
- Equity LTCG (>12 months): 12.5% above ₹1.25 lakh exemption
- Equity STCG (<12 months): 20%
- Intraday / F&O / Commodity: Business income — taxed at slab rate (estimated 30%)

Derivative STT rates by transaction date:
- Before 1 October 2024: futures 0.0125%, options 0.0625% on the sell side
- 1 October 2024 to 31 March 2026: futures 0.02%, options 0.1%
- From 1 April 2026: futures 0.05%, options 0.15%
- Equity delivery: 0.1% on buy + sell (unchanged)

Usage::

    from flinttrade_data.tax_report import TaxReportGenerator, TaxableTransaction

    trades = [
        TaxableTransaction(
            date="2025-04-15", symbol="RELIANCE", exchange="NSE",
            action="SELL", quantity=10, price=2600.0,
            segment="equity_delivery", holding_period_days=400,
            buy_price=2200.0,
        ),
    ]
    gen = TaxReportGenerator()
    summary = gen.compute_pnl_by_segment(trades, fy="2025-26")
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

logger = logging.getLogger("flinttrade.data.tax_report")

# ── Constants ────────────────────────────────────────────────────────────────

# Holding period threshold for LTCG (days)
LTCG_THRESHOLD_DAYS = 365

# LTCG exemption limit (₹)
LTCG_EXEMPTION = 125_000.0

# Tax rates
LTCG_RATE = 0.125        # 12.5%
STCG_RATE = 0.20         # 20%
BUSINESS_INCOME_RATE = 0.30  # estimated slab rate for business income

# STT rates. Derivative rates are selected using each transaction date.
STT_EQUITY_DELIVERY = 0.001  # 0.1% on both buy and sell (unchanged)
_DERIVATIVE_STT_PERIODS: tuple[tuple[date | None, date | None, float, float], ...] = (
    (None, date(2024, 9, 30), 0.000625, 0.000125),
    (date(2024, 10, 1), date(2026, 3, 31), 0.001, 0.0002),
    (date(2026, 4, 1), None, 0.0015, 0.0005),
)

AUDIT_ASSESSMENT_REASON = (
    "Complete taxpayer-specific books, payment evidence, other income, deductions, and set-offs are not available."
)
TAX_ESTIMATE_METHODOLOGY = (
    "Indicative estimate from realised P&L only: equity LTCG and STCG use the modelled capital-gains rates, "
    "while net positive business income uses an illustrative 30% slab-rate assumption."
)
STT_METHODOLOGY = (
    "STT is calculated per transaction date on the applicable taxable value; the existing equity treatment is unchanged."
)
STT_RATE_PROVENANCE = (
    "Derivative sell-side option/futures rates are 0.0625%/0.0125% before 1 October 2024, 0.1%/0.02% from "
    "1 October 2024 through 31 March 2026, and 0.15%/0.05% from 1 April 2026; the effective-date changes follow "
    "the Finance (No. 2) Act, 2024 and Finance Act, 2026 schedules."
)

# Audit thresholds (₹)
AUDIT_TURNOVER_ABSOLUTE = 10_00_00_000.0  # 10 crore
AUDIT_TURNOVER_CONDITIONAL = 2_00_00_000.0  # 2 crore
AUDIT_PROFIT_PERCENT = 0.06  # 6% of turnover


def _stt_rate_schedule() -> list[dict[str, str | float | None]]:
    """Return the derivative STT schedule in an API-safe form."""
    return [
        {
            "effective_from": start.isoformat() if start else None,
            "effective_to": end.isoformat() if end else None,
            "options_sell_rate": options_rate,
            "futures_sell_rate": futures_rate,
        }
        for start, end, options_rate, futures_rate in _DERIVATIVE_STT_PERIODS
    ]


def _derivative_stt_rates(transaction_date: str) -> tuple[float, float]:
    """Return option and futures sell-side rates for an ISO transaction date."""
    traded_on = date.fromisoformat(transaction_date)
    for start, end, options_rate, futures_rate in _DERIVATIVE_STT_PERIODS:
        if (start is None or traded_on >= start) and (end is None or traded_on <= end):
            return options_rate, futures_rate
    raise ValueError(f"No derivative STT schedule for transaction date {transaction_date}")


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class TaxableTransaction:
    """A single taxable trade entry.

    Attributes:
        date: Trade date as ISO string (YYYY-MM-DD).
        symbol: Instrument symbol.
        exchange: Exchange code (NSE, BSE, NFO, MCX, etc.).
        action: BUY or SELL.
        quantity: Number of units.
        price: Trade price per unit.
        segment: One of equity_delivery, equity_intraday, futures, options, commodity.
        holding_period_days: Days held (only relevant for equity_delivery).
        buy_price: Entry price per unit (for P&L calculation on SELL trades).
    """

    date: str
    symbol: str
    exchange: str
    action: str  # BUY / SELL
    quantity: int
    price: float
    segment: str  # equity_delivery, equity_intraday, futures, options, commodity
    holding_period_days: int = 0
    buy_price: float = 0.0


@dataclass
class TaxSummary:
    """Aggregated tax summary for a financial year.

    Attributes:
        fy: Financial year string (e.g. "2025-26").
        equity_ltcg: Long-term capital gains on equity delivery.
        equity_stcg: Short-term capital gains on equity delivery.
        intraday_pnl: Net P&L from intraday equity trades.
        fno_pnl: Net P&L from futures + options trades.
        commodity_pnl: Net P&L from commodity trades.
        stt_paid: Total STT paid across all segments.
        turnover: Total turnover for audit calculation.
        tax_liability_estimated: Estimated total tax liability.
        ltcg_exemption_used: Portion of LTCG exemption used.
        needs_audit: Preliminary threshold signal retained for compatibility.
        audit_assessment: Explicit completeness state for the audit assessment.
        trade_count: Total number of trades.
    """

    fy: str = ""
    equity_ltcg: float = 0.0
    equity_stcg: float = 0.0
    intraday_pnl: float = 0.0
    fno_pnl: float = 0.0
    commodity_pnl: float = 0.0
    stt_paid: float = 0.0
    turnover: float = 0.0
    tax_liability_estimated: float = 0.0
    ltcg_exemption_used: float = 0.0
    needs_audit: bool = False
    audit_assessment: str = "incomplete"
    audit_assessment_reason: str = AUDIT_ASSESSMENT_REASON
    tax_estimate_methodology: str = TAX_ESTIMATE_METHODOLOGY
    stt_methodology: str = STT_METHODOLOGY
    stt_rate_provenance: str = STT_RATE_PROVENANCE
    stt_rate_schedule: list[dict[str, str | float | None]] = field(default_factory=_stt_rate_schedule)
    trade_count: int = 0


# ── Generator ────────────────────────────────────────────────────────────────

class TaxReportGenerator:
    """Generate indicative tax P&L reports from trade history.

    All methods are stateless — pass in trades, get results out.
    """

    def classify_trades(
        self, trades: list[TaxableTransaction],
    ) -> dict[str, list[TaxableTransaction]]:
        """Classify trades into segment buckets.

        Args:
            trades: List of taxable transactions.

        Returns:
            Dict mapping segment name to list of trades in that segment.
        """
        buckets: dict[str, list[TaxableTransaction]] = {
            "equity_ltcg": [],
            "equity_stcg": [],
            "equity_intraday": [],
            "futures": [],
            "options": [],
            "commodity": [],
        }

        for trade in trades:
            seg = trade.segment.lower()
            if seg == "equity_delivery":
                if trade.holding_period_days > LTCG_THRESHOLD_DAYS:
                    buckets["equity_ltcg"].append(trade)
                else:
                    buckets["equity_stcg"].append(trade)
            elif seg == "equity_intraday":
                buckets["equity_intraday"].append(trade)
            elif seg == "futures":
                buckets["futures"].append(trade)
            elif seg == "options":
                buckets["options"].append(trade)
            elif seg == "commodity":
                buckets["commodity"].append(trade)
            else:
                logger.warning("Unknown segment %r for trade %s — skipping", seg, trade.symbol)

        return buckets

    def _compute_segment_pnl(self, trades: list[TaxableTransaction]) -> float:
        """Compute net P&L for a list of SELL trades.

        Only SELL trades contribute to realized P&L. Each SELL trade must have
        ``buy_price`` set to compute profit/loss.

        Args:
            trades: List of trades (BUY trades are ignored).

        Returns:
            Net realized P&L.
        """
        pnl = 0.0
        for t in trades:
            if t.action.upper() == "SELL":
                pnl += (t.price - t.buy_price) * t.quantity
        return pnl

    def compute_stt(self, trades: list[TaxableTransaction]) -> float:
        """Compute total STT (Securities Transaction Tax) paid.

        STT is charged on the sell side for most segments. Equity delivery
        has STT on both buy and sell sides.

        Args:
            trades: List of all taxable transactions.

        Returns:
            Total STT amount in INR.
        """
        total_stt = 0.0
        for t in trades:
            value = t.price * t.quantity
            seg = t.segment.lower()

            if seg == "equity_delivery":
                # 0.1% on both buy and sell
                total_stt += value * STT_EQUITY_DELIVERY
            elif seg == "equity_intraday":
                # 0.025% on sell side only
                if t.action.upper() == "SELL":
                    total_stt += value * 0.00025
            elif seg == "futures":
                if t.action.upper() == "SELL":
                    _, futures_rate = _derivative_stt_rates(t.date)
                    total_stt += value * futures_rate
            elif seg == "options":
                if t.action.upper() == "SELL":
                    options_rate, _ = _derivative_stt_rates(t.date)
                    total_stt += value * options_rate
            elif seg == "commodity":
                # CTT on sell side for non-agri: 0.01%
                if t.action.upper() == "SELL":
                    total_stt += value * 0.0001

        return round(total_stt, 2)

    def compute_turnover(self, trades: list[TaxableTransaction]) -> float:
        """Compute turnover for tax audit determination.

        Turnover definitions per Indian tax law:
        - Equity intraday: absolute value of each trade's P&L
        - F&O / Commodity: absolute profit/loss + premium received (sell value)
        - Equity delivery: total sell value (not counted for speculative turnover,
          but included for overall turnover computation)

        Args:
            trades: List of all taxable transactions.

        Returns:
            Total turnover in INR.
        """
        turnover = 0.0
        for t in trades:
            seg = t.segment.lower()
            if t.action.upper() != "SELL":
                continue

            if seg == "equity_intraday":
                # Absolute P&L per trade
                turnover += abs((t.price - t.buy_price) * t.quantity)
            elif seg in ("futures", "options", "commodity"):
                # Absolute P&L + premium received
                pnl = abs((t.price - t.buy_price) * t.quantity)
                turnover += pnl
            elif seg == "equity_delivery":
                # Total sell value
                turnover += t.price * t.quantity

        return round(turnover, 2)

    def needs_audit(self, turnover: float, pnl: float) -> bool:
        """Return the simplified Section 44AB turnover/profit threshold signal.

        This model flags:
        1. Turnover exceeds ₹10 crore (absolute), OR
        2. Turnover exceeds ₹2 crore AND profit is less than 6% of turnover

        A false result is not a complete no-audit determination because this
        model does not ingest all taxpayer-specific audit inputs.

        Args:
            turnover: Total turnover in INR.
            pnl: Net profit/loss in INR.

        Returns:
            True if the simplified threshold signal is triggered.
        """
        if turnover > AUDIT_TURNOVER_ABSOLUTE:
            return True
        if turnover > AUDIT_TURNOVER_CONDITIONAL:
            # Profit must be >= 6% of turnover to avoid audit
            if pnl < turnover * AUDIT_PROFIT_PERCENT:
                return True
        return False

    def compute_pnl_by_segment(
        self, trades: list[TaxableTransaction], fy: str = "",
    ) -> TaxSummary:
        """Compute P&L broken down by segment and estimate tax liability.

        Args:
            trades: List of all taxable transactions for the FY.
            fy: Financial year string (e.g. "2025-26").

        Returns:
            Complete TaxSummary with all fields populated.
        """
        classified = self.classify_trades(trades)

        equity_ltcg = self._compute_segment_pnl(classified["equity_ltcg"])
        equity_stcg = self._compute_segment_pnl(classified["equity_stcg"])
        intraday_pnl = self._compute_segment_pnl(classified["equity_intraday"])
        futures_pnl = self._compute_segment_pnl(classified["futures"])
        options_pnl = self._compute_segment_pnl(classified["options"])
        fno_pnl = futures_pnl + options_pnl
        commodity_pnl = self._compute_segment_pnl(classified["commodity"])

        stt = self.compute_stt(trades)
        turnover = self.compute_turnover(trades)
        total_net_pnl = equity_ltcg + equity_stcg + intraday_pnl + fno_pnl + commodity_pnl

        # LTCG tax: 12.5% above ₹1.25 lakh exemption
        ltcg_exemption_used = min(max(equity_ltcg, 0.0), LTCG_EXEMPTION)
        taxable_ltcg = max(equity_ltcg - LTCG_EXEMPTION, 0.0)
        ltcg_tax = taxable_ltcg * LTCG_RATE

        # STCG tax: 20% on gains (losses can be set off, but we don't reduce below 0)
        stcg_tax = max(equity_stcg, 0.0) * STCG_RATE

        # Business income tax: estimated at 30% slab rate
        business_pnl = intraday_pnl + fno_pnl + commodity_pnl
        business_tax = max(business_pnl, 0.0) * BUSINESS_INCOME_RATE

        tax_liability = round(ltcg_tax + stcg_tax + business_tax, 2)
        audit_required = self.needs_audit(turnover, total_net_pnl)

        summary = TaxSummary(
            fy=fy,
            equity_ltcg=round(equity_ltcg, 2),
            equity_stcg=round(equity_stcg, 2),
            intraday_pnl=round(intraday_pnl, 2),
            fno_pnl=round(fno_pnl, 2),
            commodity_pnl=round(commodity_pnl, 2),
            stt_paid=stt,
            turnover=turnover,
            tax_liability_estimated=tax_liability,
            ltcg_exemption_used=ltcg_exemption_used,
            needs_audit=audit_required,
            trade_count=len(trades),
        )

        logger.info(
            "Tax report FY %s: LTCG=%.2f STCG=%.2f Intraday=%.2f F&O=%.2f "
            "Commodity=%.2f STT=%.2f Turnover=%.2f Tax=%.2f Audit=%s",
            fy, equity_ltcg, equity_stcg, intraday_pnl, fno_pnl,
            commodity_pnl, stt, turnover, tax_liability, audit_required,
        )
        return summary

    def generate_report(
        self, trades: list[TaxableTransaction], fy: str,
    ) -> dict[str, Any]:
        """Generate a full tax report with summary and per-segment breakdown.

        Args:
            trades: List of all taxable transactions for the FY.
            fy: Financial year string (e.g. "2025-26").

        Returns:
            Dict with 'summary' (TaxSummary as dict) and 'segments' (per-segment
            trade lists with individual P&L).
        """
        summary = self.compute_pnl_by_segment(trades, fy)
        classified = self.classify_trades(trades)

        segments: dict[str, Any] = {}
        for seg_name, seg_trades in classified.items():
            segments[seg_name] = {
                "trade_count": len(seg_trades),
                "pnl": round(self._compute_segment_pnl(seg_trades), 2),
                "trades": [
                    {
                        "date": t.date,
                        "symbol": t.symbol,
                        "exchange": t.exchange,
                        "action": t.action,
                        "quantity": t.quantity,
                        "price": t.price,
                        "buy_price": t.buy_price,
                        "pnl": round((t.price - t.buy_price) * t.quantity, 2)
                        if t.action.upper() == "SELL"
                        else 0.0,
                        "holding_period_days": t.holding_period_days,
                    }
                    for t in seg_trades
                ],
            }

        return {
            "summary": {
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
                "audit_assessment": summary.audit_assessment,
                "audit_assessment_reason": summary.audit_assessment_reason,
                "tax_estimate_methodology": summary.tax_estimate_methodology,
                "stt_methodology": summary.stt_methodology,
                "stt_rate_provenance": summary.stt_rate_provenance,
                "stt_rate_schedule": summary.stt_rate_schedule,
                "trade_count": summary.trade_count,
            },
            "segments": segments,
        }
