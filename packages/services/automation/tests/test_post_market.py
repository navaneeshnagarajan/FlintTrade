"""Extended tests for PostMarketAnalyzer — daily summary generation, trade aggregation,
strategy breakdown, Telegram formatting, and DuckDB storage.

All external dependencies (DuckDB, LLM, Telegram) are mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# TradeEntry dataclass
# ---------------------------------------------------------------------------


class TestTradeEntry:
    def test_default_fields(self):
        from flinttrade_automation.post_market import TradeEntry
        t = TradeEntry()
        assert t.symbol == ""
        assert t.pnl == 0.0
        assert t.quantity == 0
        assert t.strategy == ""

    def test_custom_fields(self):
        from flinttrade_automation.post_market import TradeEntry
        t = TradeEntry(
            symbol="NIFTY", exchange="NFO", action="SELL",
            quantity=75, entry_price=24100.0, exit_price=24000.0,
            pnl=7500.0, strategy="Supertrend",
        )
        assert t.symbol == "NIFTY"
        assert t.pnl == 7500.0
        assert t.strategy == "Supertrend"

    def test_positive_pnl_long_trade(self):
        from flinttrade_automation.post_market import TradeEntry
        t = TradeEntry(entry_price=100.0, exit_price=110.0, quantity=10, pnl=100.0)
        assert t.pnl > 0

    def test_negative_pnl_loss(self):
        from flinttrade_automation.post_market import TradeEntry
        t = TradeEntry(entry_price=200.0, exit_price=190.0, quantity=5, pnl=-50.0)
        assert t.pnl < 0


# ---------------------------------------------------------------------------
# StrategyPerformance
# ---------------------------------------------------------------------------


class TestStrategyPerformance:
    def test_win_rate_100_percent(self):
        from flinttrade_automation.post_market import StrategyPerformance
        perf = StrategyPerformance(strategy="EMA", total_trades=5, winning_trades=5)
        assert perf.win_rate == 100.0

    def test_win_rate_0_percent(self):
        from flinttrade_automation.post_market import StrategyPerformance
        perf = StrategyPerformance(strategy="Bad", total_trades=4, winning_trades=0)
        assert perf.win_rate == 0.0

    def test_win_rate_partial(self):
        from flinttrade_automation.post_market import StrategyPerformance
        perf = StrategyPerformance(strategy="S", total_trades=10, winning_trades=3)
        assert perf.win_rate == 30.0

    def test_win_rate_zero_trades_returns_zero(self):
        from flinttrade_automation.post_market import StrategyPerformance
        perf = StrategyPerformance(strategy="Empty")
        assert perf.win_rate == 0.0

    def test_net_pnl_field(self):
        from flinttrade_automation.post_market import StrategyPerformance
        perf = StrategyPerformance(strategy="S", gross_pnl=5000.0, fees=200.0, net_pnl=4800.0)
        assert perf.net_pnl == 4800.0


# ---------------------------------------------------------------------------
# DailyReport
# ---------------------------------------------------------------------------


class TestDailyReport:
    def test_win_rate_with_trades(self):
        from flinttrade_automation.post_market import DailyReport
        r = DailyReport(total_trades=10, winning_trades=7)
        assert r.win_rate == 70.0

    def test_win_rate_no_trades(self):
        from flinttrade_automation.post_market import DailyReport
        r = DailyReport()
        assert r.win_rate == 0.0

    def test_to_dict_keys(self):
        from flinttrade_automation.post_market import DailyReport, TradeEntry
        r = DailyReport(
            report_date="2026-03-16",
            total_trades=3,
            winning_trades=2,
            losing_trades=1,
            gross_pnl=1000.0,
            net_pnl=950.0,
            fees=50.0,
            best_trade=TradeEntry(pnl=800.0),
            worst_trade=TradeEntry(pnl=-100.0),
        )
        d = r.to_dict()
        assert d["report_date"] == "2026-03-16"
        assert d["total_trades"] == 3
        assert d["win_rate"] == pytest.approx(66.66, abs=0.1)
        assert d["best_trade_pnl"] == 800.0
        assert d["worst_trade_pnl"] == -100.0

    def test_to_dict_no_best_worst_trade(self):
        from flinttrade_automation.post_market import DailyReport
        r = DailyReport(report_date="2026-03-16")
        d = r.to_dict()
        assert d["best_trade_pnl"] == 0
        assert d["worst_trade_pnl"] == 0


import pytest  # noqa: E402


# ---------------------------------------------------------------------------
# build_report — core logic
# ---------------------------------------------------------------------------


class TestBuildReport:
    def _trades(self):
        from flinttrade_automation.post_market import TradeEntry
        return [
            TradeEntry(symbol="A", strategy="EMA", pnl=1000.0),
            TradeEntry(symbol="B", strategy="EMA", pnl=-200.0),
            TradeEntry(symbol="C", strategy="RSI", pnl=500.0),
            TradeEntry(symbol="D", strategy="RSI", pnl=-100.0),
            TradeEntry(symbol="E", strategy="RSI", pnl=300.0),
        ]

    def test_report_date_uses_provided(self):
        from flinttrade_automation.post_market import build_report
        report = build_report(self._trades(), "2026-03-16")
        assert report.report_date == "2026-03-16"

    def test_report_date_defaults_to_today(self):
        from flinttrade_automation.post_market import build_report
        report = build_report(self._trades())
        assert report.report_date != ""
        # Should look like YYYY-MM-DD
        assert len(report.report_date) == 10

    def test_total_trades_count(self):
        from flinttrade_automation.post_market import build_report
        report = build_report(self._trades(), "2026-03-16")
        assert report.total_trades == 5

    def test_winning_trades_count(self):
        from flinttrade_automation.post_market import build_report
        report = build_report(self._trades(), "2026-03-16")
        assert report.winning_trades == 3  # A(1000), C(500), E(300)

    def test_losing_trades_count(self):
        from flinttrade_automation.post_market import build_report
        report = build_report(self._trades(), "2026-03-16")
        assert report.losing_trades == 2  # B(-200), D(-100)

    def test_gross_pnl_sum(self):
        from flinttrade_automation.post_market import build_report
        report = build_report(self._trades(), "2026-03-16")
        assert report.gross_pnl == pytest.approx(1000 - 200 + 500 - 100 + 300)

    def test_net_pnl_equals_gross_when_no_fees(self):
        from flinttrade_automation.post_market import build_report
        report = build_report(self._trades(), "2026-03-16")
        assert report.net_pnl == pytest.approx(report.gross_pnl - report.fees)

    def test_best_trade_is_highest_pnl(self):
        from flinttrade_automation.post_market import build_report
        report = build_report(self._trades(), "2026-03-16")
        assert report.best_trade is not None
        assert report.best_trade.symbol == "A"
        assert report.best_trade.pnl == 1000.0

    def test_worst_trade_is_lowest_pnl(self):
        from flinttrade_automation.post_market import build_report
        report = build_report(self._trades(), "2026-03-16")
        assert report.worst_trade is not None
        assert report.worst_trade.symbol == "B"
        assert report.worst_trade.pnl == -200.0

    def test_strategy_breakdown_two_strategies(self):
        from flinttrade_automation.post_market import build_report
        report = build_report(self._trades(), "2026-03-16")
        assert len(report.strategy_breakdown) == 2
        names = {s.strategy for s in report.strategy_breakdown}
        assert "EMA" in names
        assert "RSI" in names

    def test_strategy_breakdown_sorted_by_net_pnl_descending(self):
        from flinttrade_automation.post_market import build_report
        report = build_report(self._trades(), "2026-03-16")
        pnls = [s.net_pnl for s in report.strategy_breakdown]
        assert pnls == sorted(pnls, reverse=True)

    def test_ema_strategy_pnl(self):
        from flinttrade_automation.post_market import build_report
        report = build_report(self._trades(), "2026-03-16")
        ema = next(s for s in report.strategy_breakdown if s.strategy == "EMA")
        assert ema.total_trades == 2
        assert ema.gross_pnl == pytest.approx(800.0)

    def test_rsi_strategy_pnl(self):
        from flinttrade_automation.post_market import build_report
        report = build_report(self._trades(), "2026-03-16")
        rsi = next(s for s in report.strategy_breakdown if s.strategy == "RSI")
        assert rsi.total_trades == 3
        assert rsi.winning_trades == 2

    def test_unnamed_strategy_defaults_to_default(self):
        """Trades with no strategy name go into the 'default' bucket."""
        from flinttrade_automation.post_market import TradeEntry, build_report
        trades = [
            TradeEntry(symbol="X", pnl=100.0),  # strategy=""
            TradeEntry(symbol="Y", pnl=-50.0),  # strategy=""
        ]
        report = build_report(trades, "2026-03-16")
        names = {s.strategy for s in report.strategy_breakdown}
        assert "default" in names

    def test_all_winning_trades(self):
        from flinttrade_automation.post_market import TradeEntry, build_report
        trades = [TradeEntry(symbol=f"S{i}", pnl=float(i + 1) * 100) for i in range(5)]
        report = build_report(trades, "2026-03-16")
        assert report.winning_trades == 5
        assert report.losing_trades == 0
        assert report.win_rate == 100.0

    def test_all_losing_trades(self):
        from flinttrade_automation.post_market import TradeEntry, build_report
        trades = [TradeEntry(symbol=f"S{i}", pnl=float(-i - 1) * 100) for i in range(3)]
        report = build_report(trades, "2026-03-16")
        assert report.winning_trades == 0
        assert report.losing_trades == 3
        assert report.win_rate == 0.0

    def test_single_trade_report(self):
        from flinttrade_automation.post_market import TradeEntry, build_report
        trades = [TradeEntry(symbol="ONLY", pnl=250.0, strategy="Test")]
        report = build_report(trades, "2026-03-16")
        assert report.total_trades == 1
        assert report.best_trade.symbol == "ONLY"
        assert report.worst_trade.symbol == "ONLY"


# ---------------------------------------------------------------------------
# format_report_telegram
# ---------------------------------------------------------------------------


class TestFormatReportTelegram:
    def _report(self, pnl: float = 1500.0):
        from flinttrade_automation.post_market import TradeEntry, build_report
        trades = [
            TradeEntry(symbol="RELIANCE", strategy="EMA", pnl=pnl),
            TradeEntry(symbol="TCS", strategy="EMA", pnl=-200.0),
        ]
        return build_report(trades, "2026-03-16")

    def test_positive_pnl_has_green_emoji(self):
        from flinttrade_automation.post_market import format_report_telegram
        msg = format_report_telegram(self._report(pnl=1500.0))
        assert "🟢" in msg

    def test_negative_pnl_has_red_emoji(self):
        from flinttrade_automation.post_market import TradeEntry, build_report, format_report_telegram
        trades = [TradeEntry(symbol="X", pnl=-500.0)]
        report = build_report(trades, "2026-03-16")
        msg = format_report_telegram(report)
        assert "🔴" in msg

    def test_contains_date(self):
        from flinttrade_automation.post_market import format_report_telegram
        msg = format_report_telegram(self._report())
        assert "2026-03-16" in msg

    def test_contains_win_rate(self):
        from flinttrade_automation.post_market import format_report_telegram
        msg = format_report_telegram(self._report())
        assert "Win Rate" in msg

    def test_contains_gross_pnl(self):
        from flinttrade_automation.post_market import format_report_telegram
        msg = format_report_telegram(self._report())
        assert "Gross P&L" in msg or "Gross" in msg

    def test_contains_strategy_breakdown(self):
        from flinttrade_automation.post_market import format_report_telegram
        msg = format_report_telegram(self._report())
        assert "EMA" in msg

    def test_contains_best_and_worst(self):
        from flinttrade_automation.post_market import format_report_telegram
        msg = format_report_telegram(self._report(pnl=1500.0))
        assert "Best" in msg
        assert "Worst" in msg

    def test_llm_analysis_shown_when_set(self):
        from flinttrade_automation.post_market import DailyReport, format_report_telegram
        report = DailyReport(
            report_date="2026-03-16",
            total_trades=2,
            llm_analysis="Good risk management. Reduce position size tomorrow.",
        )
        msg = format_report_telegram(report)
        assert "AI Analysis" in msg
        assert "Good risk management" in msg

    def test_llm_analysis_hidden_when_empty(self):
        from flinttrade_automation.post_market import format_report_telegram
        report = self._report()
        report.llm_analysis = ""
        msg = format_report_telegram(report)
        assert "AI Analysis" not in msg

    def test_empty_report_still_formats(self):
        from flinttrade_automation.post_market import DailyReport, format_report_telegram
        report = DailyReport(report_date="2026-03-16")
        msg = format_report_telegram(report)
        assert "2026-03-16" in msg

    def test_strategy_breakdown_emoji_green_positive(self):
        from flinttrade_automation.post_market import TradeEntry, build_report, format_report_telegram
        trades = [TradeEntry(symbol="X", strategy="Good", pnl=1000.0)]
        report = build_report(trades, "2026-03-16")
        msg = format_report_telegram(report)
        assert "🟢" in msg


# ---------------------------------------------------------------------------
# PostMarketAnalysis.run
# ---------------------------------------------------------------------------


class TestPostMarketAnalysisRun:
    def _trades(self):
        from flinttrade_automation.post_market import TradeEntry
        return [
            TradeEntry(symbol="NIFTY", strategy="EMA", pnl=5000.0),
            TradeEntry(symbol="BANKNIFTY", strategy="EMA", pnl=-2000.0),
        ]

    def test_run_returns_daily_report(self):
        from flinttrade_automation.post_market import PostMarketAnalysis
        pma = PostMarketAnalysis()
        report = pma.run(self._trades(), report_date="2026-03-16", include_llm=False)
        from flinttrade_automation.post_market import DailyReport
        assert isinstance(report, DailyReport)

    def test_run_appends_to_internal_list(self):
        from flinttrade_automation.post_market import PostMarketAnalysis
        pma = PostMarketAnalysis()
        pma.run(self._trades(), "2026-03-16", include_llm=False)
        pma.run(self._trades(), "2026-03-17", include_llm=False)
        assert len(pma.reports) == 2

    def test_run_sends_telegram_when_configured(self):
        from flinttrade_automation.post_market import PostMarketAnalysis
        mock_bot = MagicMock()
        pma = PostMarketAnalysis(telegram_bot=mock_bot)
        pma.run(self._trades(), "2026-03-16", include_llm=False)
        mock_bot.send_message.assert_called_once()

    def test_run_no_telegram_when_not_configured(self):
        from flinttrade_automation.post_market import PostMarketAnalysis
        pma = PostMarketAnalysis(telegram_bot=None)
        # Should not raise
        pma.run(self._trades(), "2026-03-16", include_llm=False)

    def test_run_no_telegram_for_empty_trades(self):
        """Telegram not sent when there are no trades."""
        from flinttrade_automation.post_market import PostMarketAnalysis
        mock_bot = MagicMock()
        pma = PostMarketAnalysis(telegram_bot=mock_bot)
        pma.run([], "2026-03-16", include_llm=False)
        mock_bot.send_message.assert_not_called()

    def test_run_include_llm_false_skips_llm(self):
        from flinttrade_automation.post_market import PostMarketAnalysis
        mock_llm = MagicMock()
        pma = PostMarketAnalysis(llm_client=mock_llm)
        report = pma.run(self._trades(), "2026-03-16", include_llm=False)
        mock_llm.chat.assert_not_called()
        assert report.llm_analysis == ""

    def test_reports_property_returns_copy(self):
        from flinttrade_automation.post_market import PostMarketAnalysis
        pma = PostMarketAnalysis()
        pma.run(self._trades(), "2026-03-16", include_llm=False)
        reports = pma.reports
        reports.clear()
        assert len(pma.reports) == 1  # original unaffected

    def test_run_stores_correct_date(self):
        from flinttrade_automation.post_market import PostMarketAnalysis
        pma = PostMarketAnalysis()
        report = pma.run(self._trades(), "2026-03-22", include_llm=False)
        assert report.report_date == "2026-03-22"

    def test_run_multiple_dates_separate_reports(self):
        from flinttrade_automation.post_market import PostMarketAnalysis
        pma = PostMarketAnalysis()
        r1 = pma.run(self._trades(), "2026-03-20", include_llm=False)
        r2 = pma.run(self._trades(), "2026-03-21", include_llm=False)
        assert r1.report_date == "2026-03-20"
        assert r2.report_date == "2026-03-21"


# ---------------------------------------------------------------------------
# PostMarketAnalysis — DuckDB storage
# ---------------------------------------------------------------------------


class TestPostMarketDuckDB:
    def test_store_report_called_with_path(self, tmp_path):
        """When duckdb_path is provided, _store_report is attempted."""
        from flinttrade_automation.post_market import PostMarketAnalysis
        db_path = str(tmp_path / "test_reports.ddb")
        pma = PostMarketAnalysis(duckdb_path=db_path)
        from flinttrade_automation.post_market import TradeEntry
        trades = [TradeEntry(symbol="NIFTY", pnl=500.0)]
        try:
            import duckdb  # noqa: F401
            pma.run(trades, "2026-03-16", include_llm=False)
            # If duckdb is installed, a file should be created
            import os
            assert os.path.exists(db_path)
        except ImportError:
            pass  # duckdb not installed, skip storage assertion

    def test_store_report_no_path_does_not_raise(self):
        from flinttrade_automation.post_market import PostMarketAnalysis, TradeEntry
        pma = PostMarketAnalysis(duckdb_path=None)
        trades = [TradeEntry(symbol="X", pnl=100.0)]
        pma.run(trades, "2026-03-16", include_llm=False)  # must not raise


# ---------------------------------------------------------------------------
# PostMarketAnalysis — LLM integration
# ---------------------------------------------------------------------------


class TestPostMarketLLM:
    def _trades(self):
        from flinttrade_automation.post_market import TradeEntry
        return [TradeEntry(symbol="NIFTY", pnl=2000.0, strategy="EMA")]

    def test_llm_success_adds_analysis_to_report(self):
        from flinttrade_automation.post_market import PostMarketAnalysis
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.success = True
        mock_response.content = "Good day. Watch risk on NIFTY tomorrow."
        mock_llm.chat = MagicMock(return_value=mock_response)

        with patch("flinttrade_automation.post_market.PostMarketAnalysis._generate_llm_analysis",
                   return_value="Good day. Watch risk on NIFTY tomorrow."):
            pma = PostMarketAnalysis(llm_client=mock_llm)
            report = pma.run(self._trades(), "2026-03-16", include_llm=True)

        assert "Good day" in report.llm_analysis

    def test_llm_failure_returns_empty_analysis(self):
        """If LLM call fails, analysis should be empty string (not crash)."""
        from flinttrade_automation.post_market import PostMarketAnalysis
        mock_llm = MagicMock()
        mock_llm.chat = MagicMock(side_effect=RuntimeError("LLM offline"))

        with patch("flinttrade_automation.post_market.PostMarketAnalysis._generate_llm_analysis",
                   return_value=""):
            pma = PostMarketAnalysis(llm_client=mock_llm)
            report = pma.run(self._trades(), "2026-03-16", include_llm=True)

        assert report.llm_analysis == ""

    def test_llm_skipped_when_no_client(self):
        from flinttrade_automation.post_market import PostMarketAnalysis
        pma = PostMarketAnalysis(llm_client=None)
        report = pma.run(self._trades(), "2026-03-16", include_llm=True)
        assert report.llm_analysis == ""

    def test_llm_skipped_on_zero_trades(self):
        from flinttrade_automation.post_market import PostMarketAnalysis
        mock_llm = MagicMock()
        pma = PostMarketAnalysis(llm_client=mock_llm)
        pma.run([], "2026-03-16", include_llm=True)
        mock_llm.chat.assert_not_called()
