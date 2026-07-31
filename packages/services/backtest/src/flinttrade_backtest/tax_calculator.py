"""Indian tax calculator for equity and F&O trading.

Computes all statutory charges applied to Indian trades:

  - STT (Securities Transaction Tax)
  - Stamp Duty
  - Exchange Transaction Charges (NSE / BSE)
  - SEBI Turnover Fee
  - GST (18% on brokerage + exchange charges + SEBI fee)
  - Brokerage (configurable flat or percentage)

All monetary values use ``Decimal`` for precision — never float.

Usage::

    from .tax_calculator import (
        IndianTaxCalculator, TradeType,
    )
    calc = IndianTaxCalculator(instrument_type="fo")
    breakdown = calc.calculate(
        trade_value=Decimal("1000000"),
        trade_type=TradeType.FO,
        is_buy=True,
    )
    print(f"Total charges: {breakdown.total_charges}")
    print(f"STT: {breakdown.stt}")
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

# Rounding to paise (2 decimal places)
_TWO = Decimal("0.01")
_EIGHT = Decimal("0.00000001")  # For intermediate calculations


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TradeType(StrEnum):
    """Classification of a trade for tax computation.

    Attributes:
        DELIVERY: Equity delivery (held overnight, STT on both buy and sell).
        INTRADAY: Equity intraday (squared off on same day, STT on sell only).
        FO: Futures & Options (STT on sell side only, lower rate).
    """

    DELIVERY = "delivery"
    INTRADAY = "intraday"
    FO = "fo"


class Exchange(StrEnum):
    """Exchange for charge rate selection."""

    NSE = "NSE"
    BSE = "BSE"
    MCX = "MCX"
    NSE_FO = "NSE_FO"  # NSE F&O segment
    BSE_FO = "BSE_FO"


# ---------------------------------------------------------------------------
# Rate tables (Updated April 2026 per Finance Act)
# ---------------------------------------------------------------------------

# STT rates (applied on trade value, as fraction)
# April 2026 changes: Futures 0.02% → 0.05%; Options 0.1% → 0.15% (on premium)
# TradeType.FO covers both futures and options; rate here uses the futures rate.
# For options-specific STT (0.15% on premium), use the data.tax_report module
# which handles the futures/options split at the segment level.
_STT_RATES: dict[tuple[TradeType, bool], Decimal] = {
    # (trade_type, is_buy) -> rate
    (TradeType.DELIVERY, True):  Decimal("0.001"),    # 0.1% on buy (unchanged)
    (TradeType.DELIVERY, False): Decimal("0.001"),    # 0.1% on sell (unchanged)
    (TradeType.INTRADAY, True):  Decimal(0),        # No STT on intraday buy
    (TradeType.INTRADAY, False): Decimal("0.00025"),  # 0.025% on sell (unchanged)
    (TradeType.FO, True):        Decimal(0),        # No STT on F&O buy
    (TradeType.FO, False):       Decimal("0.0005"),   # 0.05% on F&O sell (futures, Apr 2026)
}

# Stamp duty — buy side only, as fraction of trade value
_STAMP_DUTY_RATES: dict[TradeType, Decimal] = {
    TradeType.DELIVERY: Decimal("0.00015"),  # 0.015%
    TradeType.INTRADAY: Decimal("0.00003"),  # 0.003%
    TradeType.FO:       Decimal("0.00002"),  # 0.002%
}

# Exchange transaction charges (as fraction of trade value)
_EXCHANGE_CHARGES: dict[Exchange, Decimal] = {
    Exchange.NSE:    Decimal("0.0000325"),  # 0.00325%
    Exchange.BSE:    Decimal("0.0000375"),  # 0.00375% (equity)
    Exchange.MCX:    Decimal("0.0000260"),  # 0.0026%
    Exchange.NSE_FO: Decimal("0.0000500"),  # 0.005% (F&O segment)
    Exchange.BSE_FO: Decimal("0.0000500"),  # 0.005%
}

# SEBI turnover fee (as fraction of trade value)
_SEBI_FEE_RATE = Decimal("0.000001")  # 0.0001%

# GST rate on (brokerage + exchange charges + SEBI fee)
_GST_RATE = Decimal("0.18")  # 18%


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TaxBreakdown:
    """Per-trade tax charge breakdown.

    Attributes:
        trade_value: Gross trade value (price × quantity) in INR.
        trade_type: Type of trade (delivery / intraday / fo).
        is_buy: True if this is the buy leg.
        brokerage: Brokerage charged on this leg in INR.
        stt: Securities Transaction Tax in INR.
        stamp_duty: Stamp duty in INR (buy side only).
        exchange_charges: Exchange transaction charges in INR.
        sebi_fee: SEBI turnover fee in INR.
        gst: GST on (brokerage + exchange_charges + sebi_fee) in INR.
        total_charges: Sum of all charges in INR.
    """

    trade_value: Decimal
    trade_type: TradeType
    is_buy: bool
    brokerage: Decimal = Decimal(0)
    stt: Decimal = Decimal(0)
    stamp_duty: Decimal = Decimal(0)
    exchange_charges: Decimal = Decimal(0)
    sebi_fee: Decimal = Decimal(0)
    gst: Decimal = Decimal(0)
    total_charges: Decimal = Decimal(0)

    def as_dict(self) -> dict[str, str]:
        """Return human-readable string values for all charges.

        Returns:
            Dict mapping charge name to formatted INR string.
        """
        return {
            "trade_value": str(self.trade_value),
            "trade_type": str(self.trade_type),
            "is_buy": str(self.is_buy),
            "brokerage": str(self.brokerage),
            "stt": str(self.stt),
            "stamp_duty": str(self.stamp_duty),
            "exchange_charges": str(self.exchange_charges),
            "sebi_fee": str(self.sebi_fee),
            "gst": str(self.gst),
            "total_charges": str(self.total_charges),
        }


@dataclass
class TaxSummary:
    """Aggregate tax summary across all trades in a session.

    Attributes:
        total_brokerage: Total brokerage paid.
        total_stt: Total STT paid.
        total_stamp_duty: Total stamp duty paid.
        total_exchange_charges: Total exchange transaction charges.
        total_sebi_fee: Total SEBI turnover fee.
        total_gst: Total GST paid.
        total_charges: Grand total of all charges.
        delivery_trades: Number of delivery trades processed.
        intraday_trades: Number of intraday trades processed.
        fo_trades: Number of F&O trades processed.
        total_trade_value: Sum of all trade values processed.
    """

    total_brokerage: Decimal = Decimal(0)
    total_stt: Decimal = Decimal(0)
    total_stamp_duty: Decimal = Decimal(0)
    total_exchange_charges: Decimal = Decimal(0)
    total_sebi_fee: Decimal = Decimal(0)
    total_gst: Decimal = Decimal(0)
    total_charges: Decimal = Decimal(0)
    delivery_trades: int = 0
    intraday_trades: int = 0
    fo_trades: int = 0
    total_trade_value: Decimal = Decimal(0)

    @property
    def effective_charge_rate_pct(self) -> Decimal:
        """Effective charge rate as a percentage of total trade value.

        Returns:
            Charge rate percentage (0.0 if no trades processed).
        """
        if self.total_trade_value <= 0:
            return Decimal(0)
        return (self.total_charges / self.total_trade_value * 100).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )


# ---------------------------------------------------------------------------
# Calculator
# ---------------------------------------------------------------------------


class IndianTaxCalculator:
    """Calculates all statutory charges for Indian equity and F&O trades.

    Handles:
    - STT (both buy and sell legs for delivery; sell only for intraday and F&O)
    - Stamp duty (buy side only)
    - Exchange transaction charges (NSE / BSE / MCX)
    - SEBI turnover fee
    - GST (18% on brokerage + exchange charges + SEBI fee)
    - Configurable brokerage model (flat per order or percentage)

    All values are computed with ``Decimal`` arithmetic — no float rounding errors.

    Args:
        instrument_type: Default trade classification (``"fo"``, ``"equity_delivery"``,
                         ``"equity_intraday"``).
        exchange: Default exchange for transaction charge lookup.
        brokerage_per_order: Flat brokerage per order in INR (default: Rs 20 for F&O).
        brokerage_pct: Percentage brokerage on trade value. Applied on top of flat fee.
        zero_brokerage_delivery: Set True for zero-brokerage delivery (many discount brokers).
    """

    def __init__(
        self,
        instrument_type: str = "fo",
        exchange: Exchange = Exchange.NSE_FO,
        brokerage_per_order: Decimal = Decimal(20),
        brokerage_pct: Decimal = Decimal(0),
        zero_brokerage_delivery: bool = False,
    ) -> None:
        self.instrument_type = instrument_type.lower()
        self.exchange = exchange
        self.brokerage_per_order = brokerage_per_order
        self.brokerage_pct = brokerage_pct
        self.zero_brokerage_delivery = zero_brokerage_delivery

        # Running summary
        self._summary = TaxSummary()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate(
        self,
        trade_value: Decimal,
        trade_type: TradeType | None = None,
        is_buy: bool = True,
        exchange: Exchange | None = None,
    ) -> TaxBreakdown:
        """Calculate all charges for a single trade leg.

        Args:
            trade_value: Gross trade value (price × quantity) in INR.
            trade_type: Type of trade. Falls back to ``instrument_type`` if None.
            is_buy: True for buy leg, False for sell leg.
            exchange: Override exchange for this trade.

        Returns:
            TaxBreakdown with all charge components.
        """
        if trade_type is None:
            trade_type = self._default_trade_type()
        exch = exchange or self.exchange
        tv = trade_value  # Alias for brevity

        # Brokerage
        brokerage = self._compute_brokerage(tv, trade_type, is_buy)

        # STT
        stt_rate = _STT_RATES.get((trade_type, is_buy), Decimal(0))
        stt = (tv * stt_rate).quantize(_TWO, rounding=ROUND_HALF_UP)

        # Stamp duty — buy side only
        stamp_duty = Decimal(0)
        if is_buy:
            stamp_rate = _STAMP_DUTY_RATES.get(trade_type, Decimal(0))
            stamp_duty = (tv * stamp_rate).quantize(_TWO, rounding=ROUND_HALF_UP)

        # Exchange transaction charges
        exch_rate = _EXCHANGE_CHARGES.get(exch, Decimal("0.0000325"))
        exchange_charges = (tv * exch_rate).quantize(_TWO, rounding=ROUND_HALF_UP)

        # SEBI turnover fee
        sebi_fee = (tv * _SEBI_FEE_RATE).quantize(_TWO, rounding=ROUND_HALF_UP)

        # GST — on brokerage + exchange_charges + sebi_fee (NOT on STT or stamp duty)
        gst_base = brokerage + exchange_charges + sebi_fee
        gst = (gst_base * _GST_RATE).quantize(_TWO, rounding=ROUND_HALF_UP)

        # Total charges
        total = brokerage + stt + stamp_duty + exchange_charges + sebi_fee + gst

        breakdown = TaxBreakdown(
            trade_value=tv,
            trade_type=trade_type,
            is_buy=is_buy,
            brokerage=brokerage,
            stt=stt,
            stamp_duty=stamp_duty,
            exchange_charges=exchange_charges,
            sebi_fee=sebi_fee,
            gst=gst,
            total_charges=total.quantize(_TWO, rounding=ROUND_HALF_UP),
        )

        # Accumulate into summary
        self._accumulate(breakdown)
        return breakdown

    def calculate_round_trip(
        self,
        entry_value: Decimal,
        exit_value: Decimal,
        trade_type: TradeType | None = None,
        exchange: Exchange | None = None,
    ) -> tuple[TaxBreakdown, TaxBreakdown, Decimal]:
        """Calculate charges for both legs of a complete round trip.

        Args:
            entry_value: Trade value of the entry leg (price × qty).
            exit_value: Trade value of the exit leg (price × qty).
            trade_type: Trade type (delivery / intraday / fo).
            exchange: Exchange override.

        Returns:
            Tuple of (entry_breakdown, exit_breakdown, total_charges).
        """
        entry_bd = self.calculate(entry_value, trade_type, is_buy=True, exchange=exchange)
        exit_bd = self.calculate(exit_value, trade_type, is_buy=False, exchange=exchange)
        return entry_bd, exit_bd, entry_bd.total_charges + exit_bd.total_charges

    def net_pnl(
        self,
        gross_pnl: Decimal,
        entry_value: Decimal,
        exit_value: Decimal,
        trade_type: TradeType | None = None,
    ) -> Decimal:
        """Compute net P&L after all charges for a round trip.

        Args:
            gross_pnl: Pre-charge profit or loss.
            entry_value: Entry trade value.
            exit_value: Exit trade value.
            trade_type: Trade classification.

        Returns:
            Net P&L in INR.
        """
        _, _, total_charges = self.calculate_round_trip(entry_value, exit_value, trade_type)
        return gross_pnl - total_charges

    def get_summary(self) -> TaxSummary:
        """Return the cumulative charge summary for all trades processed.

        Returns:
            TaxSummary with running totals.
        """
        return self._summary

    def reset(self) -> None:
        """Reset the running summary counters."""
        self._summary = TaxSummary()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _compute_brokerage(
        self, trade_value: Decimal, trade_type: TradeType, is_buy: bool
    ) -> Decimal:
        """Compute brokerage for a single trade leg.

        Applies zero-brokerage rule for equity delivery if configured.

        Args:
            trade_value: Trade value in INR.
            trade_type: Trade type.
            is_buy: Buy or sell leg.

        Returns:
            Brokerage amount in INR.
        """
        if self.zero_brokerage_delivery and trade_type == TradeType.DELIVERY:
            return Decimal(0)
        pct_fee = trade_value * self.brokerage_pct / Decimal(100)
        return (self.brokerage_per_order + pct_fee).quantize(_TWO, rounding=ROUND_HALF_UP)

    def _default_trade_type(self) -> TradeType:
        """Resolve instrument_type string to TradeType enum.

        Returns:
            TradeType enum value.
        """
        if "fo" in self.instrument_type or "futures" in self.instrument_type or "options" in self.instrument_type:
            return TradeType.FO
        if "intraday" in self.instrument_type:
            return TradeType.INTRADAY
        return TradeType.DELIVERY

    def _accumulate(self, breakdown: TaxBreakdown) -> None:
        """Add a breakdown to the running summary.

        Args:
            breakdown: Computed TaxBreakdown to accumulate.
        """
        s = self._summary
        s.total_brokerage += breakdown.brokerage
        s.total_stt += breakdown.stt
        s.total_stamp_duty += breakdown.stamp_duty
        s.total_exchange_charges += breakdown.exchange_charges
        s.total_sebi_fee += breakdown.sebi_fee
        s.total_gst += breakdown.gst
        s.total_charges += breakdown.total_charges
        s.total_trade_value += breakdown.trade_value

        if breakdown.trade_type == TradeType.DELIVERY:
            s.delivery_trades += 1
        elif breakdown.trade_type == TradeType.INTRADAY:
            s.intraday_trades += 1
        else:
            s.fo_trades += 1


# ---------------------------------------------------------------------------
# Convenience factory functions
# ---------------------------------------------------------------------------


def make_equity_calculator(
    exchange: Exchange = Exchange.NSE,
    brokerage_per_order: Decimal = Decimal(0),
    zero_brokerage: bool = True,
) -> IndianTaxCalculator:
    """Create a calculator pre-configured for equity delivery.

    Args:
        exchange: Exchange (default NSE).
        brokerage_per_order: Flat brokerage (default 0 for zero-brokerage brokers).
        zero_brokerage: If True, delivery brokerage is forced to zero.

    Returns:
        Configured IndianTaxCalculator.
    """
    return IndianTaxCalculator(
        instrument_type="equity_delivery",
        exchange=exchange,
        brokerage_per_order=brokerage_per_order,
        zero_brokerage_delivery=zero_brokerage,
    )


def make_intraday_calculator(
    exchange: Exchange = Exchange.NSE,
    brokerage_per_order: Decimal = Decimal(20),
) -> IndianTaxCalculator:
    """Create a calculator pre-configured for equity intraday.

    Args:
        exchange: Exchange (default NSE).
        brokerage_per_order: Flat brokerage per order.

    Returns:
        Configured IndianTaxCalculator.
    """
    return IndianTaxCalculator(
        instrument_type="equity_intraday",
        exchange=exchange,
        brokerage_per_order=brokerage_per_order,
    )


def make_fo_calculator(
    exchange: Exchange = Exchange.NSE_FO,
    brokerage_per_order: Decimal = Decimal(20),
) -> IndianTaxCalculator:
    """Create a calculator pre-configured for F&O.

    Args:
        exchange: Exchange segment (default NSE_FO).
        brokerage_per_order: Flat brokerage per order (Rs 20 standard).

    Returns:
        Configured IndianTaxCalculator.
    """
    return IndianTaxCalculator(
        instrument_type="fo",
        exchange=exchange,
        brokerage_per_order=brokerage_per_order,
    )
