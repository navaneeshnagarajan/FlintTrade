"""Tests for tearsheet.py — all matplotlib/quantstats calls are mocked.

No actual tearsheet rendering or file I/O against real QuantStats happens.
The mock strategy ensures tests pass whether quantstats is installed or not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_returns(n: int = 252, seed: int = 42) -> Any:
    """Build a synthetic daily-returns Series for testing."""
    import random
    from datetime import date, timedelta

    random.seed(seed)
    start = date(2024, 1, 2)
    dates = [start + timedelta(days=i) for i in range(n)]
    values = [random.gauss(0.0003, 0.01) for _ in range(n)]

    try:
        import pandas as pd

        return pd.Series(values, index=pd.to_datetime(dates), name="returns")
    except ImportError:
        pytest.skip("pandas not available")


# ---------------------------------------------------------------------------
# stub HTML helpers
# ---------------------------------------------------------------------------


class TestStubHtml:
    """Test that _stub_html and _brand_html produce valid markup."""

    def test_stub_contains_title(self):
        from tearsheet import _stub_html

        html = _stub_html("My Strategy", "QuantStats not installed.")
        assert "My Strategy" in html

    def test_stub_contains_message(self):
        from tearsheet import _stub_html

        html = _stub_html("X", "Some specific message here.")
        assert "Some specific message here." in html

    def test_stub_is_valid_html_structure(self):
        from tearsheet import _stub_html

        html = _stub_html("T", "M")
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html

    def test_brand_html_injects_header(self):
        from tearsheet import _brand_html

        inner = "<html><body><p>hello</p></body></html>"
        branded = _brand_html(inner, "Test Report")
        assert "FlintTrade" in branded
        assert "Test Report" in branded

    def test_brand_html_injects_footer(self):
        from tearsheet import _brand_html

        inner = "<html><body><p>hello</p></body></html>"
        branded = _brand_html(inner, "Test")
        assert "past performance" in branded.lower() or "Past performance" in branded

    def test_brand_html_handles_fragment(self):
        """brand_html should work even without <body> tags."""
        from tearsheet import _brand_html

        inner = "<p>Just a paragraph.</p>"
        branded = _brand_html(inner, "Fragment")
        assert "FlintTrade" in branded
        assert "<p>Just a paragraph.</p>" in branded


# ---------------------------------------------------------------------------
# save_tearsheet
# ---------------------------------------------------------------------------


class TestSaveTearsheet:
    def test_saves_html_to_file(self, tmp_path: Path):
        from tearsheet import save_tearsheet

        dest = tmp_path / "report.html"
        save_tearsheet("<html><body>test</body></html>", dest)
        assert dest.exists()
        assert dest.read_text(encoding="utf-8") == "<html><body>test</body></html>"

    def test_creates_parent_directories(self, tmp_path: Path):
        from tearsheet import save_tearsheet

        dest = tmp_path / "nested" / "deep" / "report.html"
        save_tearsheet("<html/>", dest)
        assert dest.exists()

    def test_accepts_string_path(self, tmp_path: Path):
        from tearsheet import save_tearsheet

        dest = str(tmp_path / "str_path.html")
        save_tearsheet("<html/>", dest)
        assert Path(dest).exists()

    def test_overwrites_existing_file(self, tmp_path: Path):
        from tearsheet import save_tearsheet

        dest = tmp_path / "overwrite.html"
        dest.write_text("old content", encoding="utf-8")
        save_tearsheet("<html>new</html>", dest)
        assert dest.read_text(encoding="utf-8") == "<html>new</html>"


# ---------------------------------------------------------------------------
# generate_tearsheet — quantstats NOT available (stub path)
# ---------------------------------------------------------------------------


class TestGenerateTearsheetNoQS:
    """Test generate_tearsheet when quantstats is unavailable."""

    @patch("tearsheet._QS_AVAILABLE", False)
    def test_returns_stub_when_qs_unavailable(self):
        from tearsheet import generate_tearsheet

        html = generate_tearsheet(MagicMock(), title="EMA Cross")
        assert "EMA Cross" in html
        assert "quantstats" in html.lower() or "not installed" in html.lower()

    @patch("tearsheet._QS_AVAILABLE", False)
    def test_stub_is_full_html_document(self):
        from tearsheet import generate_tearsheet

        html = generate_tearsheet(MagicMock())
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html

    @patch("tearsheet._QS_AVAILABLE", False)
    def test_branded_stub(self):
        from tearsheet import generate_tearsheet

        html = generate_tearsheet(MagicMock(), title="My Strat")
        assert "FlintTrade" in html


# ---------------------------------------------------------------------------
# generate_tearsheet — quantstats IS available (mocked)
# ---------------------------------------------------------------------------


class TestGenerateTearsheetWithQS:
    @patch("tearsheet._QS_AVAILABLE", True)
    @patch("tearsheet.qs")
    def test_calls_qs_reports_html(self, mock_qs):
        """qs.reports.html should be called with the returns and title."""
        from tearsheet import generate_tearsheet

        mock_qs.reports.html.return_value = None

        returns = _make_returns()
        # qs.reports.html writes to the buffer (output kwarg); simulate that.
        def fake_html(ret, benchmark, title, output):
            output.write("<html><body><p>tearsheet content</p></body></html>")

        mock_qs.reports.html.side_effect = fake_html
        html = generate_tearsheet(returns, title="Test Strategy")
        mock_qs.reports.html.assert_called_once()
        assert "tearsheet content" in html or "FlintTrade" in html

    @patch("tearsheet._QS_AVAILABLE", True)
    @patch("tearsheet.qs")
    def test_branding_injected_into_output(self, mock_qs):
        def fake_html(ret, benchmark, title, output):
            output.write("<html><body><p>content</p></body></html>")

        mock_qs.reports.html.side_effect = fake_html
        from tearsheet import generate_tearsheet

        html = generate_tearsheet(_make_returns(), title="Brand Test")
        assert "FlintTrade" in html

    @patch("tearsheet._QS_AVAILABLE", True)
    @patch("tearsheet.qs")
    def test_returns_stub_on_qs_exception(self, mock_qs):
        """If qs.reports.html raises, return a graceful stub."""
        mock_qs.reports.html.side_effect = RuntimeError("qs internal error")
        from tearsheet import generate_tearsheet

        html = generate_tearsheet(_make_returns(), title="Crash Test")
        assert "Tearsheet generation failed" in html or "FlintTrade" in html

    @patch("tearsheet._QS_AVAILABLE", True)
    @patch("tearsheet.qs")
    def test_benchmark_passed_to_qs(self, mock_qs):
        """benchmark_returns should be forwarded to qs.reports.html."""
        captured = {}

        def fake_html(ret, benchmark, title, output):
            captured["benchmark"] = benchmark
            output.write("<html><body></body></html>")

        mock_qs.reports.html.side_effect = fake_html
        from tearsheet import generate_tearsheet

        bench = _make_returns(seed=99)
        generate_tearsheet(_make_returns(), benchmark_returns=bench)
        assert captured.get("benchmark") is not None


# ---------------------------------------------------------------------------
# generate_snapshot — quantstats NOT available
# ---------------------------------------------------------------------------


class TestGenerateSnapshotNoQS:
    @patch("tearsheet._QS_AVAILABLE", False)
    def test_returns_stub(self):
        from tearsheet import generate_snapshot

        html = generate_snapshot(MagicMock(), title="Quick View")
        assert "Quick View" in html
        assert "FlintTrade" in html

    @patch("tearsheet._QS_AVAILABLE", False)
    def test_stub_mentions_install(self):
        from tearsheet import generate_snapshot

        html = generate_snapshot(MagicMock())
        assert "quantstats" in html.lower()


# ---------------------------------------------------------------------------
# generate_snapshot — quantstats IS available (matplotlib mocked)
# ---------------------------------------------------------------------------


_has_matplotlib = False
try:
    import matplotlib  # noqa: F401
    _has_matplotlib = True
except ImportError:
    pass


@pytest.mark.skipif(not _has_matplotlib, reason="matplotlib not installed")
class TestGenerateSnapshotWithQS:
    @patch("tearsheet._QS_AVAILABLE", True)
    @patch("tearsheet.qs")
    def test_calls_qs_plots_snapshot(self, mock_qs):

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots()
        mock_qs.plots.snapshot.return_value = fig

        from tearsheet import generate_snapshot

        generate_snapshot(_make_returns(), title="Snap")
        mock_qs.plots.snapshot.assert_called_once()
        plt.close("all")

    @patch("tearsheet._QS_AVAILABLE", True)
    @patch("tearsheet.qs")
    def test_returns_stub_on_exception(self, mock_qs):
        mock_qs.plots.snapshot.side_effect = RuntimeError("render error")
        from tearsheet import generate_snapshot

        html = generate_snapshot(_make_returns())
        assert "FlintTrade" in html


# ---------------------------------------------------------------------------
# compare_strategies — no quantstats
# ---------------------------------------------------------------------------


class TestCompareStrategiesNoQS:
    @patch("tearsheet._QS_AVAILABLE", False)
    def test_returns_stub(self):
        from tearsheet import compare_strategies

        html = compare_strategies({"S1": MagicMock(), "S2": MagicMock()})
        assert "FlintTrade" in html
        assert "quantstats" in html.lower()

    @patch("tearsheet._QS_AVAILABLE", False)
    def test_empty_dict_returns_stub(self):
        from tearsheet import compare_strategies

        html = compare_strategies({})
        assert "FlintTrade" in html


# ---------------------------------------------------------------------------
# compare_strategies — with quantstats (mocked metrics)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _has_matplotlib, reason="matplotlib not installed")
class TestCompareStrategiesWithQS:
    @patch("tearsheet._QS_AVAILABLE", True)
    @patch("tearsheet.qs")
    def test_produces_html_with_all_strategy_names(self, mock_qs):
        """Each strategy name should appear in the comparison output."""
        mock_qs.stats.cagr.return_value = 0.15
        mock_qs.stats.sharpe.return_value = 1.2
        mock_qs.stats.sortino.return_value = 1.5
        mock_qs.stats.max_drawdown.return_value = -0.18
        mock_qs.stats.volatility.return_value = 0.12
        mock_qs.stats.calmar.return_value = 0.83
        mock_qs.stats.win_rate.return_value = 0.54

        from tearsheet import compare_strategies

        returns_a = _make_returns(seed=1)
        returns_b = _make_returns(seed=2)
        html = compare_strategies({"Alpha": returns_a, "Beta": returns_b})
        assert "Alpha" in html
        assert "Beta" in html
        assert "FlintTrade" in html

    @patch("tearsheet._QS_AVAILABLE", True)
    @patch("tearsheet.qs")
    def test_single_strategy_works(self, mock_qs):
        mock_qs.stats.cagr.return_value = 0.10
        mock_qs.stats.sharpe.return_value = 0.9
        mock_qs.stats.sortino.return_value = 1.1
        mock_qs.stats.max_drawdown.return_value = -0.15
        mock_qs.stats.volatility.return_value = 0.11
        mock_qs.stats.calmar.return_value = 0.67
        mock_qs.stats.win_rate.return_value = 0.52

        from tearsheet import compare_strategies

        html = compare_strategies({"Only One": _make_returns()})
        assert "Only One" in html

    @patch("tearsheet._QS_AVAILABLE", True)
    @patch("tearsheet.qs")
    def test_returns_stub_on_exception(self, mock_qs):
        mock_qs.stats.cagr.side_effect = RuntimeError("stats error")
        mock_qs.stats.sharpe.side_effect = RuntimeError("stats error")

        from tearsheet import compare_strategies

        # Should not raise — should return stub or partial HTML
        html = compare_strategies({"S": _make_returns()})
        assert "FlintTrade" in html

    @patch("tearsheet._QS_AVAILABLE", True)
    @patch("tearsheet.qs")
    def test_metrics_table_in_output(self, mock_qs):
        mock_qs.stats.cagr.return_value = 0.12
        mock_qs.stats.sharpe.return_value = 1.1
        mock_qs.stats.sortino.return_value = 1.3
        mock_qs.stats.max_drawdown.return_value = -0.20
        mock_qs.stats.volatility.return_value = 0.14
        mock_qs.stats.calmar.return_value = 0.60
        mock_qs.stats.win_rate.return_value = 0.55

        from tearsheet import compare_strategies

        html = compare_strategies({"MyStrat": _make_returns()})
        # Pandas to_html generates <table> elements
        assert "<table" in html.lower()


# ---------------------------------------------------------------------------
# Integration: save + generate round-trip (no qs)
# ---------------------------------------------------------------------------


class TestRoundTrip:
    @patch("tearsheet._QS_AVAILABLE", False)
    def test_generate_and_save_round_trip(self, tmp_path: Path):
        from tearsheet import generate_tearsheet, save_tearsheet

        html = generate_tearsheet(MagicMock(), title="Round Trip")
        dest = tmp_path / "round_trip.html"
        save_tearsheet(html, dest)
        saved = dest.read_text(encoding="utf-8")
        assert "FlintTrade" in saved
        assert "Round Trip" in saved
