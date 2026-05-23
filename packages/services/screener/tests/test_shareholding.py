"""Tests for the shareholding and fundamental scraper module.

All tests use synthetic HTML / JSON payloads — no real HTTP calls.
httpx is patched via unittest.mock.AsyncMock.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from flinttrade_screener.shareholding import (
    Announcement,
    AnnualFinancial,
    FinancialSummary,
    QuarterlyHolding,
    ShareholdingData,
    _build_annual_history,
    _parse_financial_table,
    _parse_number,
    _parse_ratios,
    _parse_shareholding_table,
    fetch_corporate_announcements,
    fetch_financial_summary,
    fetch_shareholding,
)


# ---------------------------------------------------------------------------
# Sample HTML fixtures
# ---------------------------------------------------------------------------

# Minimal Screener.in shareholding section
_SHP_HTML = """
<html><body>
<section id="quarterly-shp">
  <table>
    <tr><th></th><th>Mar 2024</th><th>Dec 2023</th><th>Sep 2023</th></tr>
    <tr><td>Promoters</td><td>72.5%</td><td>72.1%</td><td>71.8%</td></tr>
    <tr><td>Foreign Institutions</td><td>13.2%</td><td>13.5%</td><td>14.0%</td></tr>
    <tr><td>Domestic Institutions</td><td>8.3%</td><td>8.1%</td><td>7.9%</td></tr>
    <tr><td>Public</td><td>6.0%</td><td>6.3%</td><td>6.3%</td></tr>
  </table>
</section>
</body></html>
"""

# Minimal Screener.in profit-loss section
_PNL_HTML = """
<html><body>
<section id="profit-loss">
  <table>
    <tr><th></th><th>Mar 2024</th><th>Mar 2023</th><th>Mar 2022</th></tr>
    <tr><td>Sales</td><td>12000</td><td>10000</td><td>8500</td></tr>
    <tr><td>Net Profit</td><td>2000</td><td>1800</td><td>1500</td></tr>
  </table>
</section>
<section id="cash-flow">
  <table>
    <tr><th></th><th>Mar 2024</th><th>Mar 2023</th><th>Mar 2022</th></tr>
    <tr><td>Cash from Operating Activity</td><td>2500</td><td>2100</td><td>1800</td></tr>
  </table>
</section>
<ul id="top-ratios">
  <li><span class="name">Stock P/E</span><span class="number value">24.5</span></li>
  <li><span class="name">ROE</span><span class="number value">18.3 %</span></li>
  <li><span class="name">ROCE</span><span class="number value">22.1 %</span></li>
  <li><span class="name">Market Cap</span><span class="number value">150000</span></li>
  <li><span class="name">Debt / Eq</span><span class="number value">0.12</span></li>
  <li><span class="name">Book Value</span><span class="number value">450</span></li>
</ul>
</body></html>
"""

# Minimal BSE API announcement payload
_BSE_ANN_PAGE1 = {
    "Table": [
        {
            "SCRIP_CD": "500325",
            "DT_TM": "2024-04-01 09:30:00",
            "CATEGORYNAME": "Board Meeting",
            "HEADLINE": "Board meeting to consider Q4 results",
            "ATTACHMENTNAME": "https://example.com/doc1.pdf",
        },
        {
            "SCRIP_CD": "500325",
            "DT_TM": "2024-03-28 14:00:00",
            "CATEGORYNAME": "Dividend",
            "HEADLINE": "Declaration of interim dividend",
            "ATTACHMENTNAME": "https://example.com/doc2.pdf",
        },
    ],
    "Table1": [{"ROWCNT": "2"}],
}


# ---------------------------------------------------------------------------
# QuarterlyHolding
# ---------------------------------------------------------------------------


class TestQuarterlyHolding:
    def test_creation(self):
        qh = QuarterlyHolding(quarter="Mar 2024", percentage=72.5)
        assert qh.quarter == "Mar 2024"
        assert qh.percentage == 72.5

    def test_zero_percentage(self):
        qh = QuarterlyHolding(quarter="Dec 2023", percentage=0.0)
        assert qh.percentage == 0.0


# ---------------------------------------------------------------------------
# ShareholdingData
# ---------------------------------------------------------------------------


class TestShareholdingData:
    def test_defaults(self):
        shp = ShareholdingData(symbol="TCS")
        assert shp.promoter_pct == 0.0
        assert shp.fii_pct == 0.0
        assert shp.promoter_history == []

    def test_custom(self):
        shp = ShareholdingData(
            symbol="TCS",
            promoter_pct=72.5,
            fii_pct=13.2,
            dii_pct=8.3,
            public_pct=6.0,
        )
        assert shp.promoter_pct == 72.5
        assert shp.symbol == "TCS"


# ---------------------------------------------------------------------------
# AnnualFinancial
# ---------------------------------------------------------------------------


class TestAnnualFinancial:
    def test_creation(self):
        af = AnnualFinancial(year="Mar 2024", revenue=12000.0, net_profit=2000.0)
        assert af.year == "Mar 2024"
        assert af.revenue == 12000.0
        assert af.net_profit == 2000.0

    def test_optional_fields(self):
        af = AnnualFinancial(year="Mar 2023")
        assert af.revenue is None
        assert af.net_profit is None
        assert af.operating_cash_flow is None


# ---------------------------------------------------------------------------
# FinancialSummary
# ---------------------------------------------------------------------------


class TestFinancialSummary:
    def test_defaults(self):
        fs = FinancialSummary(symbol="RELIANCE")
        assert fs.symbol == "RELIANCE"
        assert fs.revenue is None
        assert fs.annual_history == []

    def test_fully_populated(self):
        fs = FinancialSummary(
            symbol="TCS",
            revenue=12000.0,
            net_profit=2000.0,
            roe=18.3,
            roce=22.1,
            pe_ratio=24.5,
        )
        assert fs.roe == 18.3
        assert fs.pe_ratio == 24.5


# ---------------------------------------------------------------------------
# Announcement
# ---------------------------------------------------------------------------


class TestAnnouncement:
    def test_creation(self):
        ann = Announcement(
            symbol="500325",
            date="2024-04-01",
            category="Board Meeting",
            headline="Q4 results discussion",
        )
        assert ann.category == "Board Meeting"
        assert ann.attachment_url == ""


# ---------------------------------------------------------------------------
# _parse_number
# ---------------------------------------------------------------------------


class TestParseNumber:
    def test_plain_int(self):
        assert _parse_number("12000") == 12000.0

    def test_with_commas(self):
        assert _parse_number("1,20,000") == 120000.0

    def test_with_percent(self):
        assert _parse_number("72.5%") == 72.5

    def test_with_cr(self):
        assert _parse_number("12000Cr") == 12000.0

    def test_float(self):
        assert _parse_number("0.12") == 0.12

    def test_negative(self):
        assert _parse_number("-500") == -500.0

    def test_invalid_returns_none(self):
        assert _parse_number("N/A") is None
        assert _parse_number("") is None
        assert _parse_number("abc") is None


# ---------------------------------------------------------------------------
# _parse_shareholding_table
# ---------------------------------------------------------------------------


class TestParseShareholdingTable:
    def test_promoter_pct(self):
        data = _parse_shareholding_table(_SHP_HTML)
        assert abs(data.promoter_pct - 72.5) < 0.01

    def test_fii_pct(self):
        data = _parse_shareholding_table(_SHP_HTML)
        assert abs(data.fii_pct - 13.2) < 0.01

    def test_dii_pct(self):
        data = _parse_shareholding_table(_SHP_HTML)
        assert abs(data.dii_pct - 8.3) < 0.01

    def test_public_pct(self):
        data = _parse_shareholding_table(_SHP_HTML)
        assert abs(data.public_pct - 6.0) < 0.01

    def test_as_of_quarter(self):
        data = _parse_shareholding_table(_SHP_HTML)
        assert data.as_of_quarter == "Mar 2024"

    def test_promoter_history_length(self):
        data = _parse_shareholding_table(_SHP_HTML)
        assert len(data.promoter_history) == 3

    def test_promoter_history_order(self):
        data = _parse_shareholding_table(_SHP_HTML)
        assert data.promoter_history[0].quarter == "Mar 2024"
        assert data.promoter_history[1].quarter == "Dec 2023"

    def test_empty_html_returns_defaults(self):
        data = _parse_shareholding_table("<html></html>")
        assert data.promoter_pct == 0.0
        assert data.fii_pct == 0.0


# ---------------------------------------------------------------------------
# _parse_financial_table and _parse_ratios
# ---------------------------------------------------------------------------


class TestParseFinancialTable:
    def test_pnl_sales_row(self):
        table = _parse_financial_table(_PNL_HTML, "profit-loss")
        assert "Sales" in table
        years_values = dict(table["Sales"])
        assert years_values.get("Mar 2024") == 12000.0

    def test_pnl_net_profit_row(self):
        table = _parse_financial_table(_PNL_HTML, "profit-loss")
        assert "Net Profit" in table

    def test_cashflow_ocf_row(self):
        table = _parse_financial_table(_PNL_HTML, "cash-flow")
        assert any("Operating" in k for k in table)

    def test_missing_section_returns_empty(self):
        table = _parse_financial_table("<html></html>", "profit-loss")
        assert table == {}


class TestParseRatios:
    def test_pe_ratio(self):
        ratios = _parse_ratios(_PNL_HTML)
        assert any("P/E" in k or "P/E" in v for k, v in ratios.items())

    def test_empty_html_returns_empty(self):
        assert _parse_ratios("<html></html>") == {}


# ---------------------------------------------------------------------------
# _build_annual_history
# ---------------------------------------------------------------------------


class TestBuildAnnualHistory:
    def test_combines_pnl_and_cashflow(self):
        pnl = {
            "Sales": [("Mar 2024", 12000.0), ("Mar 2023", 10000.0)],
            "Net Profit": [("Mar 2024", 2000.0), ("Mar 2023", 1800.0)],
        }
        cashflow = {
            "Cash from Operating Activity": [
                ("Mar 2024", 2500.0),
                ("Mar 2023", 2100.0),
            ]
        }
        history = _build_annual_history(pnl, cashflow)
        assert len(history) >= 2
        mar24 = next(h for h in history if h.year == "Mar 2024")
        assert mar24.revenue == 12000.0
        assert mar24.net_profit == 2000.0
        assert mar24.operating_cash_flow == 2500.0

    def test_empty_tables_return_empty(self):
        history = _build_annual_history({}, {})
        assert history == []

    def test_missing_cashflow(self):
        pnl = {"Sales": [("Mar 2024", 5000.0)]}
        history = _build_annual_history(pnl, {})
        assert history[0].operating_cash_flow is None

    def test_year_ordering_preserved(self):
        pnl = {
            "Sales": [
                ("Mar 2024", 12000.0),
                ("Mar 2023", 10000.0),
                ("Mar 2022", 8500.0),
            ]
        }
        history = _build_annual_history(pnl, {})
        assert history[0].year == "Mar 2024"


# ---------------------------------------------------------------------------
# fetch_shareholding (mocked HTTP)
# ---------------------------------------------------------------------------


class TestFetchShareholding:
    @pytest.mark.asyncio
    async def test_returns_shareholding_data(self):
        mock_resp = MagicMock()
        mock_resp.text = _SHP_HTML
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("flinttrade_screener.shareholding.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_shareholding("TCS")

        assert isinstance(result, ShareholdingData)
        assert result.symbol == "TCS"
        assert abs(result.promoter_pct - 72.5) < 0.01

    @pytest.mark.asyncio
    async def test_symbol_uppercased(self):
        mock_resp = MagicMock()
        mock_resp.text = _SHP_HTML
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("flinttrade_screener.shareholding.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_shareholding("tcs")

        assert result.symbol == "TCS"


# ---------------------------------------------------------------------------
# fetch_financial_summary (mocked HTTP)
# ---------------------------------------------------------------------------


class TestFetchFinancialSummary:
    @pytest.mark.asyncio
    async def test_returns_financial_summary(self):
        mock_resp = MagicMock()
        mock_resp.text = _PNL_HTML
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("flinttrade_screener.shareholding.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_financial_summary("RELIANCE")

        assert isinstance(result, FinancialSummary)
        assert result.symbol == "RELIANCE"

    @pytest.mark.asyncio
    async def test_annual_history_populated(self):
        mock_resp = MagicMock()
        mock_resp.text = _PNL_HTML
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("flinttrade_screener.shareholding.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_financial_summary("TCS")

        assert len(result.annual_history) >= 1


# ---------------------------------------------------------------------------
# fetch_corporate_announcements (mocked HTTP)
# ---------------------------------------------------------------------------


class TestFetchCorporateAnnouncements:
    @pytest.mark.asyncio
    async def test_returns_list_of_announcements(self):
        mock_resp = MagicMock()
        mock_resp.json = MagicMock(return_value=_BSE_ANN_PAGE1)
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("flinttrade_screener.shareholding.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_corporate_announcements("500325", days=30)

        assert isinstance(result, list)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_announcement_fields_populated(self):
        mock_resp = MagicMock()
        mock_resp.json = MagicMock(return_value=_BSE_ANN_PAGE1)
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("flinttrade_screener.shareholding.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_corporate_announcements("500325", days=30)

        ann = result[0]
        assert isinstance(ann, Announcement)
        assert ann.symbol == "500325"
        assert ann.category == "Board Meeting"
        assert "Q4" in ann.headline
        assert ann.attachment_url.startswith("https")

    @pytest.mark.asyncio
    async def test_empty_table_returns_empty_list(self):
        mock_resp = MagicMock()
        mock_resp.json = MagicMock(return_value={"Table": [], "Table1": [{"ROWCNT": "0"}]})
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("flinttrade_screener.shareholding.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_corporate_announcements("INFY", days=10)

        assert result == []

    @pytest.mark.asyncio
    async def test_http_error_returns_empty_list(self):
        import httpx

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(
            side_effect=httpx.RequestError("connection refused")
        )

        with patch("flinttrade_screener.shareholding.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_corporate_announcements("INFY", days=10)

        assert result == []

    @pytest.mark.asyncio
    async def test_days_capped_at_365(self):
        """Ensure from_date never exceeds 365 days back (no assertion on URL, just no crash)."""
        mock_resp = MagicMock()
        mock_resp.json = MagicMock(return_value={"Table": [], "Table1": [{"ROWCNT": "0"}]})
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("flinttrade_screener.shareholding.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_corporate_announcements("TCS", days=9999)

        assert isinstance(result, list)
