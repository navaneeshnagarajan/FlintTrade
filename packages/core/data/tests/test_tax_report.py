"""Tests for Tax Report Generator.

Run with:
    python -m pytest packages/core/data/tests/test_tax_report.py -v --import-mode=importlib
"""
from __future__ import annotations

import pytest

from flinttrade_data.tax_report import (
    AUDIT_TURNOVER_ABSOLUTE,
    AUDIT_TURNOVER_CONDITIONAL,
    LTCG_EXEMPTION,
    TaxReportGenerator,
    TaxableTransaction,
)


@pytest.fixture()
def generator() -> TaxReportGenerator:
    return TaxReportGenerator()


# ── classify_trades ──────────────────────────────────────────────────────────


class TestClassifyTrades:
    """Test trade classification into segment buckets."""

    def test_equity_ltcg(self, generator: TaxReportGenerator) -> None:
        trades = [
            TaxableTransaction("2025-01-01", "RELIANCE", "NSE", "SELL", 10, 2800.0, "equity_delivery", 400, 2200.0),
        ]
        classified = generator.classify_trades(trades)
        assert len(classified["equity_ltcg"]) == 1
        assert len(classified["equity_stcg"]) == 0

    def test_equity_stcg(self, generator: TaxReportGenerator) -> None:
        trades = [
            TaxableTransaction("2025-01-01", "TCS", "NSE", "SELL", 5, 4000.0, "equity_delivery", 180, 3500.0),
        ]
        classified = generator.classify_trades(trades)
        assert len(classified["equity_stcg"]) == 1
        assert len(classified["equity_ltcg"]) == 0

    def test_equity_delivery_boundary_365_days(self, generator: TaxReportGenerator) -> None:
        """Exactly 365 days is STCG (need >365 for LTCG)."""
        trades = [
            TaxableTransaction("2025-01-01", "INFY", "NSE", "SELL", 10, 1600.0, "equity_delivery", 365, 1400.0),
        ]
        classified = generator.classify_trades(trades)
        assert len(classified["equity_stcg"]) == 1
        assert len(classified["equity_ltcg"]) == 0

    def test_equity_delivery_boundary_366_days(self, generator: TaxReportGenerator) -> None:
        """366 days qualifies as LTCG."""
        trades = [
            TaxableTransaction("2025-01-01", "INFY", "NSE", "SELL", 10, 1600.0, "equity_delivery", 366, 1400.0),
        ]
        classified = generator.classify_trades(trades)
        assert len(classified["equity_ltcg"]) == 1
        assert len(classified["equity_stcg"]) == 0

    def test_intraday_classification(self, generator: TaxReportGenerator) -> None:
        trades = [
            TaxableTransaction("2025-01-06", "RELIANCE", "NSE", "BUY", 50, 2780.0, "equity_intraday"),
            TaxableTransaction("2025-01-06", "RELIANCE", "NSE", "SELL", 50, 2810.0, "equity_intraday", 0, 2780.0),
        ]
        classified = generator.classify_trades(trades)
        assert len(classified["equity_intraday"]) == 2

    def test_futures_classification(self, generator: TaxReportGenerator) -> None:
        trades = [
            TaxableTransaction("2025-01-15", "NIFTY25JANFUT", "NFO", "SELL", 50, 21800.0, "futures", 0, 21500.0),
        ]
        classified = generator.classify_trades(trades)
        assert len(classified["futures"]) == 1

    def test_options_classification(self, generator: TaxReportGenerator) -> None:
        trades = [
            TaxableTransaction("2025-01-15", "NIFTY25JAN21500CE", "NFO", "SELL", 50, 380.0, "options", 0, 250.0),
        ]
        classified = generator.classify_trades(trades)
        assert len(classified["options"]) == 1

    def test_commodity_classification(self, generator: TaxReportGenerator) -> None:
        trades = [
            TaxableTransaction("2025-01-20", "GOLDM25FEB", "MCX", "SELL", 10, 63200.0, "commodity", 0, 62500.0),
        ]
        classified = generator.classify_trades(trades)
        assert len(classified["commodity"]) == 1

    def test_unknown_segment_skipped(self, generator: TaxReportGenerator) -> None:
        trades = [
            TaxableTransaction("2025-01-01", "XYZ", "NSE", "SELL", 10, 100.0, "unknown_segment"),
        ]
        classified = generator.classify_trades(trades)
        for bucket in classified.values():
            assert len(bucket) == 0

    def test_mixed_trades(self, generator: TaxReportGenerator) -> None:
        trades = [
            TaxableTransaction("2025-01-01", "RELIANCE", "NSE", "SELL", 10, 2800.0, "equity_delivery", 400, 2200.0),
            TaxableTransaction("2025-01-01", "TCS", "NSE", "SELL", 5, 4000.0, "equity_delivery", 180, 3500.0),
            TaxableTransaction("2025-01-06", "INFY", "NSE", "SELL", 50, 1645.0, "equity_intraday", 0, 1620.0),
            TaxableTransaction("2025-01-15", "NIFTY25JANFUT", "NFO", "SELL", 50, 21800.0, "futures", 0, 21500.0),
            TaxableTransaction("2025-01-15", "NIFTY25JAN21500CE", "NFO", "SELL", 50, 380.0, "options", 0, 250.0),
            TaxableTransaction("2025-01-20", "GOLDM25FEB", "MCX", "SELL", 10, 63200.0, "commodity", 0, 62500.0),
        ]
        classified = generator.classify_trades(trades)
        assert len(classified["equity_ltcg"]) == 1
        assert len(classified["equity_stcg"]) == 1
        assert len(classified["equity_intraday"]) == 1
        assert len(classified["futures"]) == 1
        assert len(classified["options"]) == 1
        assert len(classified["commodity"]) == 1


# ── compute_stt ──────────────────────────────────────────────────────────────


class TestComputeSTT:
    """Test STT calculation across segments."""

    def test_equity_delivery_stt_both_sides(self, generator: TaxReportGenerator) -> None:
        trades = [
            TaxableTransaction("2025-01-01", "RELIANCE", "NSE", "BUY", 10, 2500.0, "equity_delivery"),
            TaxableTransaction("2025-01-01", "RELIANCE", "NSE", "SELL", 10, 2600.0, "equity_delivery", 400, 2500.0),
        ]
        stt = generator.compute_stt(trades)
        # BUY: 10 * 2500 * 0.001 = 25.0; SELL: 10 * 2600 * 0.001 = 26.0
        assert stt == pytest.approx(51.0, abs=0.01)

    def test_futures_stt_sell_only(self, generator: TaxReportGenerator) -> None:
        trades = [
            TaxableTransaction("2025-01-15", "NIFTY25JANFUT", "NFO", "BUY", 50, 21500.0, "futures"),
            TaxableTransaction("2025-01-20", "NIFTY25JANFUT", "NFO", "SELL", 50, 21800.0, "futures", 0, 21500.0),
        ]
        stt = generator.compute_stt(trades)
        # Only sell side: 50 * 21800 * 0.0005 = 545.0 (updated April 2026 per Finance Act)
        assert stt == pytest.approx(545.0, abs=0.01)

    def test_options_stt_sell_only(self, generator: TaxReportGenerator) -> None:
        trades = [
            TaxableTransaction("2025-01-10", "NIFTY25JAN21500CE", "NFO", "BUY", 50, 250.0, "options"),
            TaxableTransaction("2025-01-15", "NIFTY25JAN21500CE", "NFO", "SELL", 50, 380.0, "options", 0, 250.0),
        ]
        stt = generator.compute_stt(trades)
        # Only sell side: 50 * 380 * 0.0015 = 28.5 (updated April 2026 per Finance Act)
        assert stt == pytest.approx(28.5, abs=0.01)

    def test_commodity_ctt(self, generator: TaxReportGenerator) -> None:
        trades = [
            TaxableTransaction("2025-01-12", "GOLDM25FEB", "MCX", "BUY", 10, 62500.0, "commodity"),
            TaxableTransaction("2025-01-20", "GOLDM25FEB", "MCX", "SELL", 10, 63200.0, "commodity", 0, 62500.0),
        ]
        stt = generator.compute_stt(trades)
        # Only sell side: 10 * 63200 * 0.0001 = 63.2
        assert stt == pytest.approx(63.2, abs=0.01)

    def test_empty_trades_zero_stt(self, generator: TaxReportGenerator) -> None:
        assert generator.compute_stt([]) == 0.0


# ── compute_turnover ─────────────────────────────────────────────────────────


class TestComputeTurnover:
    """Test turnover calculation for audit threshold."""

    def test_intraday_turnover_absolute_pnl(self, generator: TaxReportGenerator) -> None:
        trades = [
            TaxableTransaction("2025-01-06", "RELIANCE", "NSE", "SELL", 50, 2810.0, "equity_intraday", 0, 2780.0),
            TaxableTransaction("2025-01-07", "TCS", "NSE", "SELL", 30, 4080.0, "equity_intraday", 0, 4100.0),
        ]
        turnover = generator.compute_turnover(trades)
        # |50*(2810-2780)| + |30*(4080-4100)| = 1500 + 600 = 2100
        assert turnover == pytest.approx(2100.0, abs=0.01)

    def test_futures_turnover(self, generator: TaxReportGenerator) -> None:
        trades = [
            TaxableTransaction("2025-01-20", "NIFTY25JANFUT", "NFO", "SELL", 50, 21800.0, "futures", 0, 21500.0),
        ]
        turnover = generator.compute_turnover(trades)
        # |50*(21800-21500)| = 15000
        assert turnover == pytest.approx(15000.0, abs=0.01)

    def test_equity_delivery_turnover_sell_value(self, generator: TaxReportGenerator) -> None:
        trades = [
            TaxableTransaction("2025-01-01", "RELIANCE", "NSE", "SELL", 10, 2800.0, "equity_delivery", 400, 2200.0),
        ]
        turnover = generator.compute_turnover(trades)
        # 10 * 2800 = 28000
        assert turnover == pytest.approx(28000.0, abs=0.01)

    def test_buy_trades_ignored(self, generator: TaxReportGenerator) -> None:
        trades = [
            TaxableTransaction("2025-01-06", "RELIANCE", "NSE", "BUY", 50, 2780.0, "equity_intraday"),
        ]
        assert generator.compute_turnover(trades) == 0.0

    def test_empty_trades_zero_turnover(self, generator: TaxReportGenerator) -> None:
        assert generator.compute_turnover([]) == 0.0


# ── needs_audit ──────────────────────────────────────────────────────────────


class TestNeedsAudit:
    """Test tax audit threshold determination."""

    def test_below_2_crore_no_audit(self, generator: TaxReportGenerator) -> None:
        assert generator.needs_audit(1_50_00_000.0, 5_00_000.0) is False

    def test_above_10_crore_always_audit(self, generator: TaxReportGenerator) -> None:
        assert generator.needs_audit(AUDIT_TURNOVER_ABSOLUTE + 1, 99_00_00_000.0) is True

    def test_between_2_10_crore_profit_above_6_percent(self, generator: TaxReportGenerator) -> None:
        turnover = 5_00_00_000.0  # 5 crore
        profit = turnover * 0.07  # 7% > 6%
        assert generator.needs_audit(turnover, profit) is False

    def test_between_2_10_crore_profit_below_6_percent(self, generator: TaxReportGenerator) -> None:
        turnover = 5_00_00_000.0  # 5 crore
        profit = turnover * 0.04  # 4% < 6%
        assert generator.needs_audit(turnover, profit) is True

    def test_between_2_10_crore_loss(self, generator: TaxReportGenerator) -> None:
        """Losses definitely trigger audit when turnover > 2 crore."""
        turnover = 3_00_00_000.0  # 3 crore
        assert generator.needs_audit(turnover, -50_000.0) is True

    def test_exactly_2_crore_boundary(self, generator: TaxReportGenerator) -> None:
        """At exactly 2 crore, no audit (threshold is >2 crore)."""
        assert generator.needs_audit(AUDIT_TURNOVER_CONDITIONAL, 0.0) is False

    def test_exactly_10_crore_boundary(self, generator: TaxReportGenerator) -> None:
        """At exactly 10 crore with 0 profit, audit required via conditional check."""
        # 10 crore is not >10 crore so absolute threshold doesn't trigger,
        # but it IS >2 crore with profit (0) < 6% of turnover, so audit required.
        assert generator.needs_audit(AUDIT_TURNOVER_ABSOLUTE, 0.0) is True


# ── compute_pnl_by_segment ──────────────────────────────────────────────────


class TestComputePnlBySegment:
    """Test full P&L summary computation."""

    def test_equity_ltcg_with_exemption(self, generator: TaxReportGenerator) -> None:
        # Gain of 2,00,000 on LTCG — exemption of 1,25,000
        trades = [
            TaxableTransaction("2025-01-01", "RELIANCE", "NSE", "SELL", 100, 4200.0, "equity_delivery", 400, 2200.0),
        ]
        summary = generator.compute_pnl_by_segment(trades, "2025-26")
        assert summary.equity_ltcg == pytest.approx(200000.0, abs=0.01)
        assert summary.ltcg_exemption_used == pytest.approx(LTCG_EXEMPTION, abs=0.01)
        # Tax: (200000 - 125000) * 0.125 = 9375
        assert summary.tax_liability_estimated == pytest.approx(9375.0, abs=0.01)

    def test_equity_ltcg_below_exemption(self, generator: TaxReportGenerator) -> None:
        # Gain of 50,000 — fully covered by 1.25L exemption
        trades = [
            TaxableTransaction("2025-01-01", "WIPRO", "NSE", "SELL", 100, 900.0, "equity_delivery", 400, 400.0),
        ]
        summary = generator.compute_pnl_by_segment(trades, "2025-26")
        assert summary.equity_ltcg == pytest.approx(50000.0, abs=0.01)
        assert summary.tax_liability_estimated == 0.0

    def test_stcg_tax_computation(self, generator: TaxReportGenerator) -> None:
        # STCG gain of 10,000 → tax = 10000 * 0.20 = 2000
        trades = [
            TaxableTransaction("2025-01-01", "SBIN", "NSE", "SELL", 100, 900.0, "equity_delivery", 180, 800.0),
        ]
        summary = generator.compute_pnl_by_segment(trades, "2025-26")
        assert summary.equity_stcg == pytest.approx(10000.0, abs=0.01)
        assert summary.tax_liability_estimated == pytest.approx(2000.0, abs=0.01)

    def test_fno_pnl_combines_futures_and_options(self, generator: TaxReportGenerator) -> None:
        trades = [
            TaxableTransaction("2025-01-20", "NIFTY25JANFUT", "NFO", "SELL", 50, 21800.0, "futures", 0, 21500.0),
            TaxableTransaction("2025-01-15", "NIFTY25JAN21500CE", "NFO", "SELL", 50, 380.0, "options", 0, 250.0),
        ]
        summary = generator.compute_pnl_by_segment(trades, "2025-26")
        # Futures: 50*(21800-21500) = 15000; Options: 50*(380-250) = 6500
        assert summary.fno_pnl == pytest.approx(21500.0, abs=0.01)

    def test_loss_produces_zero_tax(self, generator: TaxReportGenerator) -> None:
        trades = [
            TaxableTransaction("2025-01-07", "TCS", "NSE", "SELL", 30, 4080.0, "equity_intraday", 0, 4100.0),
        ]
        summary = generator.compute_pnl_by_segment(trades, "2025-26")
        assert summary.intraday_pnl < 0
        assert summary.tax_liability_estimated == 0.0

    def test_fy_field_set(self, generator: TaxReportGenerator) -> None:
        summary = generator.compute_pnl_by_segment([], "2024-25")
        assert summary.fy == "2024-25"

    def test_trade_count(self, generator: TaxReportGenerator) -> None:
        trades = [
            TaxableTransaction("2025-01-01", "RELIANCE", "NSE", "SELL", 10, 2800.0, "equity_delivery", 400, 2200.0),
            TaxableTransaction("2025-01-06", "INFY", "NSE", "SELL", 50, 1645.0, "equity_intraday", 0, 1620.0),
        ]
        summary = generator.compute_pnl_by_segment(trades, "2025-26")
        assert summary.trade_count == 2

    def test_empty_trades_returns_zeroes(self, generator: TaxReportGenerator) -> None:
        summary = generator.compute_pnl_by_segment([], "2025-26")
        assert summary.equity_ltcg == 0.0
        assert summary.equity_stcg == 0.0
        assert summary.intraday_pnl == 0.0
        assert summary.fno_pnl == 0.0
        assert summary.commodity_pnl == 0.0
        assert summary.stt_paid == 0.0
        assert summary.turnover == 0.0
        assert summary.tax_liability_estimated == 0.0
        assert summary.needs_audit is False


# ── generate_report ──────────────────────────────────────────────────────────


class TestGenerateReport:
    """Test full report generation."""

    def test_report_has_summary_and_segments(self, generator: TaxReportGenerator) -> None:
        trades = [
            TaxableTransaction("2025-01-01", "RELIANCE", "NSE", "SELL", 10, 2800.0, "equity_delivery", 400, 2200.0),
            TaxableTransaction("2025-01-15", "NIFTY25JAN21500CE", "NFO", "SELL", 50, 380.0, "options", 0, 250.0),
        ]
        report = generator.generate_report(trades, "2025-26")
        assert "summary" in report
        assert "segments" in report
        assert report["summary"]["fy"] == "2025-26"

    def test_segment_trade_details(self, generator: TaxReportGenerator) -> None:
        trades = [
            TaxableTransaction("2025-01-15", "NIFTY25JAN21500CE", "NFO", "SELL", 50, 380.0, "options", 0, 250.0),
        ]
        report = generator.generate_report(trades, "2025-26")
        options_seg = report["segments"]["options"]
        assert options_seg["trade_count"] == 1
        assert options_seg["pnl"] == pytest.approx(6500.0, abs=0.01)
        assert len(options_seg["trades"]) == 1
        trade_detail = options_seg["trades"][0]
        assert trade_detail["symbol"] == "NIFTY25JAN21500CE"
        assert trade_detail["pnl"] == pytest.approx(6500.0, abs=0.01)

    def test_buy_trades_have_zero_pnl_in_report(self, generator: TaxReportGenerator) -> None:
        trades = [
            TaxableTransaction("2025-01-06", "RELIANCE", "NSE", "BUY", 50, 2780.0, "equity_intraday"),
        ]
        report = generator.generate_report(trades, "2025-26")
        intraday_seg = report["segments"]["equity_intraday"]
        assert intraday_seg["trades"][0]["pnl"] == 0.0

    def test_all_segment_keys_present(self, generator: TaxReportGenerator) -> None:
        report = generator.generate_report([], "2025-26")
        expected_keys = {"equity_ltcg", "equity_stcg", "equity_intraday", "futures", "options", "commodity"}
        assert set(report["segments"].keys()) == expected_keys
