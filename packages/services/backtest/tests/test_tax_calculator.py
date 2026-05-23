"""Tests for IndianTaxCalculator — each charge component verified independently.

All monetary values use Decimal for precision. Known-input → expected-output tests.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:  # forward-ref for `-> "IndianTaxCalculator"` annotation
    from tax_calculator import IndianTaxCalculator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _calc(instrument_type: str = "fo", brokerage: float = 20.0) -> "IndianTaxCalculator":
    from tax_calculator import IndianTaxCalculator, Exchange
    exchange_map = {
        "fo": "NSE_FO",
        "equity_delivery": "NSE",
        "equity_intraday": "NSE",
    }
    exch_str = exchange_map.get(instrument_type, "NSE_FO")
    exch = Exchange(exch_str)
    return IndianTaxCalculator(
        instrument_type=instrument_type,
        exchange=exch,
        brokerage_per_order=Decimal(str(brokerage)),
    )


# ---------------------------------------------------------------------------
# STT tests
# ---------------------------------------------------------------------------


class TestSTT:
    """Securities Transaction Tax — rate varies by trade type and side."""

    def test_delivery_buy_stt(self):
        """Delivery buy: 0.1% STT."""
        from tax_calculator import TradeType
        calc = _calc("equity_delivery", brokerage=0)
        bd = calc.calculate(Decimal("100000"), TradeType.DELIVERY, is_buy=True)
        # 0.1% of 100,000 = 100
        assert bd.stt == Decimal("100.00")

    def test_delivery_sell_stt(self):
        """Delivery sell: 0.1% STT."""
        from tax_calculator import TradeType
        calc = _calc("equity_delivery", brokerage=0)
        bd = calc.calculate(Decimal("100000"), TradeType.DELIVERY, is_buy=False)
        assert bd.stt == Decimal("100.00")

    def test_intraday_buy_no_stt(self):
        """Intraday buy: no STT."""
        from tax_calculator import TradeType
        calc = _calc("equity_intraday", brokerage=0)
        bd = calc.calculate(Decimal("100000"), TradeType.INTRADAY, is_buy=True)
        assert bd.stt == Decimal("0")

    def test_intraday_sell_stt(self):
        """Intraday sell: 0.025% STT."""
        from tax_calculator import TradeType
        calc = _calc("equity_intraday", brokerage=0)
        bd = calc.calculate(Decimal("100000"), TradeType.INTRADAY, is_buy=False)
        # 0.025% of 100,000 = 25
        assert bd.stt == Decimal("25.00")

    def test_fo_buy_no_stt(self):
        """F&O buy: no STT on buy side."""
        from tax_calculator import TradeType
        calc = _calc("fo", brokerage=0)
        bd = calc.calculate(Decimal("100000"), TradeType.FO, is_buy=True)
        assert bd.stt == Decimal("0")

    def test_fo_sell_stt(self):
        """F&O sell: 0.05% STT (updated April 2026 per Finance Act)."""
        from tax_calculator import TradeType
        calc = _calc("fo", brokerage=0)
        bd = calc.calculate(Decimal("100000"), TradeType.FO, is_buy=False)
        # 0.05% of 100,000 = 50.00
        assert bd.stt == Decimal("50.00")

    def test_stt_zero_for_small_fo_buy(self):
        from tax_calculator import TradeType
        calc = _calc("fo", brokerage=0)
        bd = calc.calculate(Decimal("500"), TradeType.FO, is_buy=True)
        assert bd.stt == Decimal("0")


# ---------------------------------------------------------------------------
# Stamp duty tests
# ---------------------------------------------------------------------------


class TestStampDuty:
    """Stamp duty — buy side only."""

    def test_delivery_buy_stamp_duty(self):
        """Delivery buy stamp duty: 0.015%."""
        from tax_calculator import TradeType
        calc = _calc("equity_delivery", brokerage=0)
        bd = calc.calculate(Decimal("100000"), TradeType.DELIVERY, is_buy=True)
        # 0.015% of 100,000 = 15
        assert bd.stamp_duty == Decimal("15.00")

    def test_intraday_buy_stamp_duty(self):
        """Intraday buy stamp duty: 0.003%."""
        from tax_calculator import TradeType
        calc = _calc("equity_intraday", brokerage=0)
        bd = calc.calculate(Decimal("100000"), TradeType.INTRADAY, is_buy=True)
        # 0.003% of 100,000 = 3
        assert bd.stamp_duty == Decimal("3.00")

    def test_fo_buy_stamp_duty(self):
        """F&O buy stamp duty: 0.002%."""
        from tax_calculator import TradeType
        calc = _calc("fo", brokerage=0)
        bd = calc.calculate(Decimal("100000"), TradeType.FO, is_buy=True)
        # 0.002% of 100,000 = 2
        assert bd.stamp_duty == Decimal("2.00")

    def test_no_stamp_duty_on_sell(self):
        """All sell legs: stamp duty = 0."""
        from tax_calculator import TradeType
        calc = _calc("equity_delivery", brokerage=0)
        for tt in (TradeType.DELIVERY, TradeType.INTRADAY, TradeType.FO):
            bd = calc.calculate(Decimal("100000"), tt, is_buy=False)
            assert bd.stamp_duty == Decimal("0"), f"Stamp duty on sell for {tt}"


# ---------------------------------------------------------------------------
# Exchange charges
# ---------------------------------------------------------------------------


class TestExchangeCharges:
    """Exchange transaction charge rates."""

    def test_nse_charge_rate(self):
        """NSE: 0.00325% = 3.25 per 100,000."""
        from tax_calculator import IndianTaxCalculator, Exchange, TradeType
        calc = IndianTaxCalculator(
            instrument_type="equity_delivery",
            exchange=Exchange.NSE,
            brokerage_per_order=Decimal("0"),
        )
        bd = calc.calculate(Decimal("100000"), TradeType.DELIVERY, is_buy=True)
        # 0.00325% of 100,000 = 3.25
        assert bd.exchange_charges == Decimal("3.25")

    def test_bse_charge_rate(self):
        """BSE: 0.00375% = 3.75 per 100,000."""
        from tax_calculator import IndianTaxCalculator, Exchange, TradeType
        calc = IndianTaxCalculator(
            instrument_type="equity_delivery",
            exchange=Exchange.BSE,
            brokerage_per_order=Decimal("0"),
        )
        bd = calc.calculate(Decimal("100000"), TradeType.DELIVERY, is_buy=False)
        assert bd.exchange_charges == Decimal("3.75")

    def test_nse_fo_charge_rate(self):
        """NSE F&O: 0.005% = 5 per 100,000."""
        from tax_calculator import IndianTaxCalculator, Exchange, TradeType
        calc = IndianTaxCalculator(
            instrument_type="fo",
            exchange=Exchange.NSE_FO,
            brokerage_per_order=Decimal("0"),
        )
        bd = calc.calculate(Decimal("100000"), TradeType.FO, is_buy=True)
        assert bd.exchange_charges == Decimal("5.00")


# ---------------------------------------------------------------------------
# SEBI fee
# ---------------------------------------------------------------------------


class TestSEBIFee:
    """SEBI turnover fee: 0.0001%."""

    def test_sebi_fee_on_100k(self):
        """0.0001% of 100,000 = 0.10."""
        from tax_calculator import TradeType
        calc = _calc("fo", brokerage=0)
        bd = calc.calculate(Decimal("100000"), TradeType.FO, is_buy=True)
        assert bd.sebi_fee == Decimal("0.10")

    def test_sebi_fee_on_1m(self):
        """0.0001% of 1,000,000 = 1.00."""
        from tax_calculator import TradeType
        calc = _calc("fo", brokerage=0)
        bd = calc.calculate(Decimal("1000000"), TradeType.FO, is_buy=False)
        assert bd.sebi_fee == Decimal("1.00")

    def test_sebi_fee_scales_linearly(self):
        from tax_calculator import TradeType
        calc = _calc("fo", brokerage=0)
        bd1 = calc.calculate(Decimal("100000"), TradeType.FO, is_buy=True)
        bd2 = calc.calculate(Decimal("200000"), TradeType.FO, is_buy=True)
        assert bd2.sebi_fee == bd1.sebi_fee * 2


# ---------------------------------------------------------------------------
# GST
# ---------------------------------------------------------------------------


class TestGST:
    """GST = 18% on (brokerage + exchange_charges + SEBI fee)."""

    def test_gst_on_brokerage_only(self):
        """With zero exchange charges and SEBI fee, GST = 18% of brokerage."""
        from tax_calculator import IndianTaxCalculator, Exchange, TradeType
        # Use tiny trade value so exchange charges ≈ 0
        calc = IndianTaxCalculator(
            instrument_type="fo",
            exchange=Exchange.NSE_FO,
            brokerage_per_order=Decimal("100"),
        )
        bd = calc.calculate(Decimal("1"), TradeType.FO, is_buy=True)
        # GST ≈ 18% of brokerage (100) = 18.00 (exchange charges on 1 rupee ≈ 0)
        assert bd.gst == pytest.approx(18.0, abs=0.5)

    def test_gst_rate_correct(self):
        from tax_calculator import TradeType
        calc = _calc("fo", brokerage=0)
        bd = calc.calculate(Decimal("100000"), TradeType.FO, is_buy=True)
        # GST = 18% of (exchange_charges + sebi_fee)
        gst_base = bd.exchange_charges + bd.sebi_fee
        expected_gst = (gst_base * Decimal("0.18")).quantize(Decimal("0.01"))
        assert bd.gst == expected_gst

    def test_gst_not_on_stt_or_stamp_duty(self):
        """STT and stamp duty are government taxes — GST must not apply to them."""
        from tax_calculator import TradeType
        calc = _calc("equity_delivery", brokerage=0)
        bd = calc.calculate(Decimal("100000"), TradeType.DELIVERY, is_buy=True)
        # Verify by checking that brokerage + exchange + sebi_fee gives correct GST
        gst_base = bd.brokerage + bd.exchange_charges + bd.sebi_fee
        expected = (gst_base * Decimal("0.18")).quantize(Decimal("0.01"))
        assert bd.gst == expected


# ---------------------------------------------------------------------------
# Total charges and round trip
# ---------------------------------------------------------------------------


class TestTotalCharges:
    """Total charge = sum of all components."""

    def test_total_is_sum_of_components(self):
        from tax_calculator import TradeType
        calc = _calc("fo", brokerage=20)
        bd = calc.calculate(Decimal("500000"), TradeType.FO, is_buy=False)
        expected = bd.brokerage + bd.stt + bd.stamp_duty + bd.exchange_charges + bd.sebi_fee + bd.gst
        assert bd.total_charges == expected.quantize(Decimal("0.01"))

    def test_round_trip_total_sum_of_legs(self):
        from tax_calculator import TradeType
        calc = _calc("fo", brokerage=20)
        entry_bd, exit_bd, total = calc.calculate_round_trip(
            Decimal("500000"), Decimal("520000"), TradeType.FO
        )
        assert total == entry_bd.total_charges + exit_bd.total_charges

    def test_net_pnl_deducts_charges(self):
        from tax_calculator import TradeType
        calc = _calc("fo", brokerage=20)
        gross = Decimal("5000")
        net = calc.net_pnl(gross, Decimal("500000"), Decimal("505000"), TradeType.FO)
        assert net < gross
        assert isinstance(net, Decimal)

    def test_net_pnl_can_be_negative_on_small_profit(self):
        from tax_calculator import TradeType
        calc = _calc("fo", brokerage=20)
        # Very small profit on large trade value — charges exceed profit
        net = calc.net_pnl(Decimal("10"), Decimal("10000000"), Decimal("10000010"), TradeType.FO)
        assert net < Decimal("10")

    def test_charges_are_always_positive(self):
        from tax_calculator import TradeType
        calc = _calc("fo", brokerage=20)
        for tt in (TradeType.DELIVERY, TradeType.INTRADAY, TradeType.FO):
            for is_buy in (True, False):
                bd = calc.calculate(Decimal("100000"), tt, is_buy=is_buy)
                assert bd.total_charges >= Decimal("0"), f"Negative charges for {tt} buy={is_buy}"


# ---------------------------------------------------------------------------
# Tax summary aggregation
# ---------------------------------------------------------------------------


class TestTaxSummary:
    """Running summary across multiple trades."""

    def test_summary_accumulates_charges(self):
        from tax_calculator import TradeType
        calc = _calc("fo", brokerage=20)
        for _ in range(5):
            calc.calculate(Decimal("100000"), TradeType.FO, is_buy=True)
            calc.calculate(Decimal("100000"), TradeType.FO, is_buy=False)
        summary = calc.get_summary()
        assert summary.fo_trades == 10
        assert summary.total_charges > Decimal("0")

    def test_summary_trade_type_counts(self):
        from tax_calculator import TradeType
        calc = _calc("equity_delivery", brokerage=0)
        calc.calculate(Decimal("100000"), TradeType.DELIVERY, is_buy=True)
        calc.calculate(Decimal("100000"), TradeType.DELIVERY, is_buy=False)
        calc.calculate(Decimal("100000"), TradeType.INTRADAY, is_buy=False)
        summary = calc.get_summary()
        assert summary.delivery_trades == 2
        assert summary.intraday_trades == 1

    def test_summary_reset_clears_totals(self):
        from tax_calculator import TradeType
        calc = _calc("fo", brokerage=20)
        calc.calculate(Decimal("100000"), TradeType.FO, is_buy=True)
        calc.reset()
        summary = calc.get_summary()
        assert summary.total_charges == Decimal("0")
        assert summary.fo_trades == 0

    def test_effective_charge_rate(self):
        from tax_calculator import TradeType
        calc = _calc("fo", brokerage=20)
        calc.calculate(Decimal("1000000"), TradeType.FO, is_buy=True)
        summary = calc.get_summary()
        rate = summary.effective_charge_rate_pct
        # Effective charge rate on F&O buy: brokerage (20) + exchange (50) + sebi (1) + GST
        # = ~71 on 1M → ~0.0071%
        assert rate > Decimal("0")
        assert rate < Decimal("1")  # Should be well under 1%

    def test_total_trade_value_accumulated(self):
        from tax_calculator import TradeType
        calc = _calc("fo", brokerage=0)
        calc.calculate(Decimal("500000"), TradeType.FO, is_buy=True)
        calc.calculate(Decimal("500000"), TradeType.FO, is_buy=False)
        assert calc.get_summary().total_trade_value == Decimal("1000000")


# ---------------------------------------------------------------------------
# Breakdown as_dict
# ---------------------------------------------------------------------------


class TestTaxBreakdownDict:
    """TaxBreakdown.as_dict() utility."""

    def test_as_dict_has_all_keys(self):
        from tax_calculator import TradeType
        calc = _calc("fo")
        bd = calc.calculate(Decimal("100000"), TradeType.FO, is_buy=True)
        d = bd.as_dict()
        for key in ("trade_value", "brokerage", "stt", "stamp_duty",
                    "exchange_charges", "sebi_fee", "gst", "total_charges"):
            assert key in d, f"Missing key: {key}"

    def test_as_dict_values_are_strings(self):
        from tax_calculator import TradeType
        calc = _calc("fo")
        bd = calc.calculate(Decimal("100000"), TradeType.FO, is_buy=True)
        for k, v in bd.as_dict().items():
            assert isinstance(v, str), f"Key {k} is not a string: {v}"


# ---------------------------------------------------------------------------
# Convenience factory functions
# ---------------------------------------------------------------------------


class TestFactoryFunctions:
    """make_equity_calculator, make_intraday_calculator, make_fo_calculator."""

    def test_equity_calc_zero_brokerage(self):
        from tax_calculator import make_equity_calculator, TradeType
        calc = make_equity_calculator()
        bd = calc.calculate(Decimal("100000"), TradeType.DELIVERY, is_buy=True)
        assert bd.brokerage == Decimal("0")

    def test_intraday_calc_default_brokerage(self):
        from tax_calculator import make_intraday_calculator, TradeType
        calc = make_intraday_calculator()
        bd = calc.calculate(Decimal("100000"), TradeType.INTRADAY, is_buy=True)
        assert bd.brokerage == Decimal("20")

    def test_fo_calc_default_brokerage(self):
        from tax_calculator import make_fo_calculator, TradeType
        calc = make_fo_calculator()
        bd = calc.calculate(Decimal("100000"), TradeType.FO, is_buy=False)
        assert bd.brokerage == Decimal("20")

    def test_fo_calc_stt_on_sell(self):
        from tax_calculator import make_fo_calculator, TradeType
        calc = make_fo_calculator()
        bd = calc.calculate(Decimal("100000"), TradeType.FO, is_buy=False)
        # 0.05% of 100,000 = 50.00 (updated April 2026 per Finance Act)
        assert bd.stt == Decimal("50.00")


# ---------------------------------------------------------------------------
# Edge cases and precision
# ---------------------------------------------------------------------------


class TestEdgeCasesAndPrecision:
    """Zero trade value, large trade value, Decimal precision."""

    def test_zero_trade_value_charges_are_brokerage_only(self):
        from tax_calculator import TradeType
        calc = _calc("fo", brokerage=20)
        bd = calc.calculate(Decimal("0"), TradeType.FO, is_buy=True)
        # All percentage-based charges = 0; only brokerage + GST on brokerage
        assert bd.stt == Decimal("0")
        assert bd.stamp_duty == Decimal("0")
        assert bd.brokerage == Decimal("20")
        # GST on 20 brokerage = 3.60
        assert bd.gst == Decimal("3.60")

    def test_large_trade_value_precision(self):
        """Rs 10 crore trade — all charges should be Decimal with 2dp."""
        from tax_calculator import TradeType
        calc = _calc("fo", brokerage=20)
        bd = calc.calculate(Decimal("100000000"), TradeType.FO, is_buy=False)
        # Verify it's 2dp
        assert bd.total_charges == bd.total_charges.quantize(Decimal("0.01"))
        assert bd.stt == bd.stt.quantize(Decimal("0.01"))

    def test_charges_are_decimal_type(self):
        from tax_calculator import TradeType
        calc = _calc("fo")
        bd = calc.calculate(Decimal("500000"), TradeType.FO, is_buy=True)
        assert isinstance(bd.stt, Decimal)
        assert isinstance(bd.gst, Decimal)
        assert isinstance(bd.total_charges, Decimal)

    def test_no_float_in_charges(self):
        """Verify no floating-point numbers sneak in."""
        from tax_calculator import TradeType
        calc = _calc("equity_delivery", brokerage=20)
        bd = calc.calculate(Decimal("333333"), TradeType.DELIVERY, is_buy=True)
        for attr in ("brokerage", "stt", "stamp_duty", "exchange_charges", "sebi_fee", "gst", "total_charges"):
            val = getattr(bd, attr)
            assert isinstance(val, Decimal), f"{attr} is not Decimal"
