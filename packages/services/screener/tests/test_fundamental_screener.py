"""Tests for FundamentalScreener — Screener.in data parsing and caching.

Tests use fixture HTML and in-memory DuckDB (no network, no disk).
"""

from __future__ import annotations

import time



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cache():
    from flinttrade_screener.stock_cache import StockCache

    return StockCache(db_path=":memory:")


def _make_screener(cache=None):
    from flinttrade_screener.fundamental_screener import FundamentalScreener

    return FundamentalScreener(cache=cache or _make_cache())


# Minimal Screener.in company page HTML fixture
_FIXTURE_HTML = """
<html><body>
<div id="top">
  <h1>Tata Consultancy Services Ltd</h1>
  <div class="font-size-18">
    <span>₹3,850.50</span>
    <span>+1.25 %</span>
  </div>
  <a href="https://www.tcs.com">Website</a>
  <a>BSE: 532540</a>
  <a>NSE: TCS</a>
  <div class="about">Sector: IT Industry: Software Services</div>
  <ul id="top-ratios">
    <li>
      <span class="name">Market Cap</span>
      <span class="value">₹ 14,20,000 Cr.</span>
    </li>
    <li>
      <span class="name">Current Price</span>
      <span class="value">₹ 3,850</span>
    </li>
    <li>
      <span class="name">Stock P/E</span>
      <span class="value">32.1</span>
    </li>
    <li>
      <span class="name">Book Value</span>
      <span class="value">₹ 271</span>
    </li>
    <li>
      <span class="name">Dividend Yield</span>
      <span class="value">1.20 %</span>
    </li>
    <li>
      <span class="name">ROCE</span>
      <span class="value">62.3 %</span>
    </li>
    <li>
      <span class="name">ROE</span>
      <span class="value">48.6 %</span>
    </li>
    <li>
      <span class="name">Face Value</span>
      <span class="value">₹ 1.00</span>
    </li>
    <li>
      <span class="name">High / Low</span>
      <span class="value">₹ 4,592 / 3,311</span>
    </li>
  </ul>
</div>
<div id="analysis">
  <div class="pros">
    <ul>
      <li>Company is almost debt free.</li>
      <li>Company has a good return on equity track record.</li>
    </ul>
  </div>
  <div class="cons">
    <ul>
      <li>Stock is trading at high valuation.</li>
    </ul>
  </div>
</div>
<div id="shareholding">
  <table class="data-table">
    <thead><tr><th></th><th>Dec 2025</th><th>Mar 2026</th></tr></thead>
    <tbody>
      <tr><td>Promoters +</td><td>72.30</td><td>72.30</td></tr>
      <tr><td>FIIs +</td><td>12.50</td><td>12.80</td></tr>
      <tr><td>DIIs +</td><td>8.20</td><td>8.10</td></tr>
      <tr><td>Public +</td><td>7.00</td><td>6.80</td></tr>
    </tbody>
  </table>
</div>
</body></html>
"""


# ---------------------------------------------------------------------------
# Tests: HTML parsing
# ---------------------------------------------------------------------------


class TestParseCompanyPage:
    """Test the HTML parser against fixture data."""

    def test_parses_company_name(self):
        from flinttrade_screener.fundamental_screener import _parse_company_page

        data = _parse_company_page(_FIXTURE_HTML, "TCS")
        assert data.company_name == "Tata Consultancy Services Ltd"

    def test_parses_symbol(self):
        from flinttrade_screener.fundamental_screener import _parse_company_page

        data = _parse_company_page(_FIXTURE_HTML, "tcs")
        assert data.symbol == "TCS"  # uppercased

    def test_parses_top_ratios(self):
        from flinttrade_screener.fundamental_screener import _parse_company_page

        data = _parse_company_page(_FIXTURE_HTML, "TCS")
        assert data.market_cap == 1420000.0
        assert data.pe_ratio == 32.1
        assert data.roce == 62.3
        assert data.roe == 48.6
        assert data.dividend_yield == 1.2
        assert data.book_value == 271.0
        assert data.face_value == 1.0

    def test_parses_high_low(self):
        from flinttrade_screener.fundamental_screener import _parse_company_page

        data = _parse_company_page(_FIXTURE_HTML, "TCS")
        assert data.high_low is not None
        assert data.high_low["high"] == 4592.0
        assert data.high_low["low"] == 3311.0

    def test_parses_pros_cons(self):
        from flinttrade_screener.fundamental_screener import _parse_company_page

        data = _parse_company_page(_FIXTURE_HTML, "TCS")
        assert len(data.pros) == 2
        assert "debt free" in data.pros[0].lower()
        assert len(data.cons) == 1
        assert "valuation" in data.cons[0].lower()

    def test_parses_shareholding(self):
        from flinttrade_screener.fundamental_screener import _parse_company_page

        data = _parse_company_page(_FIXTURE_HTML, "TCS")
        # Takes the last column (Mar 2026)
        assert data.promoter_holding == 72.3
        assert data.fii_holding == 12.8
        assert data.dii_holding == 8.1

    def test_parses_nse_bse_codes(self):
        from flinttrade_screener.fundamental_screener import _parse_company_page

        data = _parse_company_page(_FIXTURE_HTML, "TCS")
        assert data.bse_code == "532540"
        assert data.nse_symbol == "TCS"

    def test_parses_sector(self):
        from flinttrade_screener.fundamental_screener import _parse_company_page

        data = _parse_company_page(_FIXTURE_HTML, "TCS")
        assert data.sector == "IT"


# ---------------------------------------------------------------------------
# Tests: Number parsing
# ---------------------------------------------------------------------------


class TestParseNumber:
    """Test the numeric value parser."""

    def test_plain_number(self):
        from flinttrade_screener.fundamental_screener import _parse_number

        assert _parse_number("32.1") == 32.1

    def test_comma_separated(self):
        from flinttrade_screener.fundamental_screener import _parse_number

        assert _parse_number("14,20,000") == 1420000.0

    def test_currency_symbol(self):
        from flinttrade_screener.fundamental_screener import _parse_number

        assert _parse_number("₹ 3,850") == 3850.0

    def test_percentage(self):
        from flinttrade_screener.fundamental_screener import _parse_number

        assert _parse_number("62.3 %") == 62.3

    def test_crore_suffix(self):
        from flinttrade_screener.fundamental_screener import _parse_number

        assert _parse_number("₹ 14,20,000 Cr.") == 1420000.0

    def test_negative_parentheses(self):
        from flinttrade_screener.fundamental_screener import _parse_number

        assert _parse_number("(5.2)") == -5.2

    def test_dash_returns_none(self):
        from flinttrade_screener.fundamental_screener import _parse_number

        assert _parse_number("-") is None
        assert _parse_number("--") is None
        assert _parse_number("N/A") is None
        assert _parse_number("") is None


# ---------------------------------------------------------------------------
# Tests: Cache integration
# ---------------------------------------------------------------------------


class TestCacheIntegration:
    """Test that FundamentalScreener correctly caches and retrieves data."""

    def test_update_cache_and_retrieve(self):
        from flinttrade_screener.fundamental_screener import FundamentalData

        cache = _make_cache()
        screener = _make_screener(cache=cache)
        data = FundamentalData(
            symbol="INFY",
            company_name="Infosys Ltd",
            market_cap=750000.0,
            pe_ratio=28.9,
            pb_ratio=8.5,
            roe=32.1,
            roce=42.8,
            dividend_yield=2.1,
            sector="IT",
        )
        screener._update_cache(data)

        cached = cache.get("INFY")
        assert cached is not None
        assert cached.symbol == "INFY"
        assert cached.pe_ratio == 28.9
        assert cached.roce == 42.8

    def test_screen_filters_work(self):
        from flinttrade_screener.fundamental_screener import FundamentalData

        cache = _make_cache()
        screener = _make_screener(cache=cache)

        # Seed two stocks
        for sym, pe, roce, sector in [
            ("TCS", 32.1, 62.3, "IT"),
            ("SBIN", 9.5, 0.0, "Banking"),
        ]:
            screener._update_cache(FundamentalData(
                symbol=sym,
                company_name=sym,
                market_cap=500000.0,
                pe_ratio=pe,
                roce=roce,
                sector=sector,
            ))

        import asyncio

        # Filter by ROCE > 50 should return only TCS
        results = asyncio.run(screener.screen({"roce_min": 50}))
        assert len(results) == 1
        assert results[0].symbol == "TCS"

        # Filter by sector
        results = asyncio.run(screener.screen({"sector": "Banking"}))
        assert len(results) == 1
        assert results[0].symbol == "SBIN"

    def test_cache_to_fundamental_roundtrip(self):
        from flinttrade_screener.fundamental_screener import FundamentalScreener
        from flinttrade_screener.stock_cache import StockFundamentals

        cached = StockFundamentals(
            symbol="RELIANCE",
            name="Reliance Industries",
            exchange="NSE",
            market_cap=1950000.0,
            pe_ratio=28.5,
            pb_ratio=2.8,
            roe=12.5,
            roce=15.2,
            dividend_yield=0.4,
            sector="Energy",
            updated_at=time.time(),
        )
        data = FundamentalScreener._cache_to_fundamental(cached)
        assert data.symbol == "RELIANCE"
        assert data.company_name == "Reliance Industries"
        assert data.pe_ratio == 28.5
        assert data.sector == "Energy"


# ---------------------------------------------------------------------------
# Tests: Empty/minimal HTML
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test parser behaviour with missing or minimal HTML."""

    def test_empty_html(self):
        from flinttrade_screener.fundamental_screener import _parse_company_page

        data = _parse_company_page("<html><body></body></html>", "UNKNOWN")
        assert data.symbol == "UNKNOWN"
        assert data.company_name == ""
        assert data.market_cap is None
        assert data.pros == []
        assert data.cons == []

    def test_missing_ratios_section(self):
        from flinttrade_screener.fundamental_screener import _parse_company_page

        html = '<html><body><div id="top"><h1>Test Co</h1></div></body></html>'
        data = _parse_company_page(html, "TEST")
        assert data.company_name == "Test Co"
        assert data.pe_ratio is None
        assert data.roce is None

    def test_search_empty_query(self):
        import asyncio

        screener = _make_screener()
        results = asyncio.run(screener.search_stocks(""))
        assert results == []

    def test_search_short_query(self):
        import asyncio

        screener = _make_screener()
        results = asyncio.run(screener.search_stocks("X"))
        assert results == []
