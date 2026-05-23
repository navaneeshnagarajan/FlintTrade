"""Fundamental stock screener — scrapes Screener.in for financial data.

Absorbed from openscreener (Playwright-based). Uses httpx for lighter HTTP
fetching and BeautifulSoup / stdlib html.parser for HTML parsing. Results are
cached for 24 hours via StockCache (DuckDB-backed).

Usage::

    from .fundamental_screener import FundamentalScreener

    screener = FundamentalScreener()

    # Search for a company
    results = await screener.search_stocks("reliance")

    # Get detailed fundamentals
    data = await screener.get_fundamentals("TCS")

    # Screen stocks with filters
    matches = await screener.screen({
        "pe_min": 10, "pe_max": 30,
        "roce_min": 15,
        "sector": "IT",
        "market_cap_min": 100000,
    })
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

import httpx

from .stock_cache import StockCache, StockFundamentals

logger = logging.getLogger("flinttrade.screener.fundamental")

_BASE_URL = "https://www.screener.in"
_COMPANY_URL = f"{_BASE_URL}/company/{{symbol}}/consolidated/"
_SEARCH_URL = f"{_BASE_URL}/api/company/search/"
_TIMEOUT = 15.0
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# Number patterns for parsing financial text
_NUMBER_RE = re.compile(r"^-?\d+(?:[,\d]*\d)?(?:\.\d+)?$")
_WHITESPACE_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Minimal HTML helpers (absorbed from openscreener parsers/_html.py)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Node:
    """Lightweight HTML node for parsing Screener pages."""

    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    parent: _Node | None = field(default=None, repr=False)
    children: list[_Node | str] = field(default_factory=list)

    def text(self) -> str:
        """Extract text content, collapsing whitespace."""
        parts: list[str] = []
        self._collect(parts)
        return _WHITESPACE_RE.sub(" ", "".join(parts)).strip()

    def _collect(self, parts: list[str]) -> None:
        for child in self.children:
            if isinstance(child, str):
                parts.append(child)
            else:
                child._collect(parts)

    def find(self, tag: str | None = None, *, id_: str | None = None, class_: str | None = None) -> _Node | None:
        for node in self._iter():
            if tag and node.tag != tag:
                continue
            if id_ and node.attrs.get("id") != id_:
                continue
            if class_ and class_ not in node.attrs.get("class", "").split():
                continue
            return node
        return None

    def find_all(self, tag: str | None = None, *, class_: str | None = None) -> list[_Node]:
        found: list[_Node] = []
        for node in self._iter():
            if tag and node.tag != tag:
                continue
            if class_ and class_ not in node.attrs.get("class", "").split():
                continue
            found.append(node)
        return found

    def _iter(self) -> list[_Node]:
        nodes: list[_Node] = [self]
        for child in self.children:
            if isinstance(child, _Node):
                nodes.extend(child._iter())
        return nodes


_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source"}


class _TreeBuilder(HTMLParser):
    """Build a lightweight DOM tree from HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document")
        self.stack: list[_Node] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag=tag, attrs={k: (v or "") for k, v in attrs}, parent=self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in _VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag=tag, attrs={k: (v or "") for k, v in attrs}, parent=self.stack[-1])
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].children.append(data)


def _parse_html(html: str) -> _Node:
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


# ---------------------------------------------------------------------------
# Value parsing helpers (absorbed from openscreener parsers/_helpers.py)
# ---------------------------------------------------------------------------


def _clean(text: str) -> str:
    """Strip and normalise whitespace."""
    return _WHITESPACE_RE.sub(" ", text.replace("\xa0", " ")).strip()


def _parse_number(text: str) -> float | None:
    """Parse a numeric string, stripping currency/percent symbols."""
    cleaned = _clean(text)
    if cleaned in {"", "-", "--", "N/A"}:
        return None
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = cleaned.strip("()")
    cleaned = cleaned.replace(",", "").replace("₹", "").replace("%", "")
    cleaned = cleaned.replace("Cr.", "").replace("x", "").replace("X", "")
    cleaned = cleaned.replace("times", "").strip()
    if _NUMBER_RE.match(cleaned):
        val = float(cleaned)
        return -val if negative else val
    return None


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class FundamentalData:
    """Detailed fundamental data for a single stock.

    Extends the basic StockFundamentals with additional metrics scraped
    from Screener.in's company page.
    """

    symbol: str
    company_name: str
    current_price: float | None = None
    market_cap: float | None = None  # in Cr
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    book_value: float | None = None
    dividend_yield: float | None = None
    roce: float | None = None
    roe: float | None = None
    face_value: float | None = None
    high_low: dict[str, float | None] | None = None
    # Income statement
    sales: float | None = None
    net_profit: float | None = None
    operating_margin: float | None = None
    # Growth metrics
    sales_growth_3yr: float | None = None
    profit_growth_3yr: float | None = None
    # Shareholding
    promoter_holding: float | None = None
    fii_holding: float | None = None
    dii_holding: float | None = None
    # Valuation
    ev_to_ebitda: float | None = None
    price_to_sales: float | None = None
    # Additional
    sector: str = ""
    industry: str = ""
    bse_code: str = ""
    nse_symbol: str = ""
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)


@dataclass
class SearchResult:
    """A single result from the Screener.in search API."""

    name: str
    symbol: str
    url: str


# ---------------------------------------------------------------------------
# Screener page parsers (absorbed from openscreener parsers/)
# ---------------------------------------------------------------------------


def _parse_top_ratios(section: _Node) -> dict[str, float | None | dict[str, float | None]]:
    """Parse the top-card ratio list (market cap, P/E, ROCE, etc.)."""
    ratios: dict[str, float | None | dict[str, float | None]] = {}
    ratio_list = section.find("ul", id_="top-ratios")
    if ratio_list is None:
        return ratios

    # Map Screener's display labels to our field names
    label_map: dict[str, str] = {
        "market cap": "market_cap",
        "current price": "current_price",
        "high / low": "high_low",
        "stock p/e": "pe_ratio",
        "book value": "book_value",
        "dividend yield": "dividend_yield",
        "roce": "roce",
        "roe": "roe",
        "face value": "face_value",
        "price to book value": "pb_ratio",
        "p/e": "pe_ratio",
        "ev/ebitda": "ev_to_ebitda",
        "price to sales": "price_to_sales",
    }

    for item in ratio_list.find_all("li"):
        name_node = item.find(None, class_="name")
        value_node = item.find(None, class_="value") or item.find(None, class_="number")
        if name_node is None or value_node is None:
            continue
        label = _clean(name_node.text()).lower()
        value_text = _clean(value_node.text())
        key = label_map.get(label, label.replace(" ", "_").replace("/", "_"))

        if key == "high_low" and "/" in value_text:
            parts = value_text.replace("₹", "").split("/")
            if len(parts) == 2:
                ratios[key] = {"high": _parse_number(parts[0]), "low": _parse_number(parts[1])}
                continue

        ratios[key] = _parse_number(value_text)

    return ratios


def _parse_pros_cons(root: _Node) -> tuple[list[str], list[str]]:
    """Extract pros and cons from the analysis section."""
    pros: list[str] = []
    cons: list[str] = []
    analysis = root.find(None, id_="analysis")
    if analysis is None:
        return pros, cons

    for section in analysis.find_all("div", class_="pros"):
        for li in section.find_all("li"):
            text = _clean(li.text())
            if text:
                pros.append(text)
    for section in analysis.find_all("div", class_="cons"):
        for li in section.find_all("li"):
            text = _clean(li.text())
            if text:
                cons.append(text)

    return pros, cons


def _parse_shareholding(root: _Node) -> dict[str, float | None]:
    """Extract latest shareholding percentages."""
    result: dict[str, float | None] = {}
    section = root.find(None, id_="shareholding")
    if section is None:
        return result

    label_map = {
        "promoters": "promoter_holding",
        "fiis": "fii_holding",
        "diis": "dii_holding",
        "public": "public_holding",
        "government": "government_holding",
    }

    # Look for the data table
    for table in section.find_all("table"):
        rows = table.find_all("tr")
        for row in rows:
            cells = [c for c in row.children if isinstance(c, _Node) and c.tag in ("td", "th")]
            if len(cells) < 2:
                continue
            label = _clean(cells[0].text()).lower().rstrip("+").strip()
            # Take the last column (most recent quarter)
            value_text = _clean(cells[-1].text())
            key = label_map.get(label)
            if key:
                result[key] = _parse_number(value_text)

    return result


def _parse_company_page(html: str, symbol: str) -> FundamentalData:
    """Parse a Screener.in company page into FundamentalData."""
    root = _parse_html(html)

    # Company name from h1 in #top
    top = root.find(None, id_="top")
    company_name = ""
    if top is not None:
        h1 = top.find("h1")
        if h1 is not None:
            company_name = _clean(h1.text())

    # Top-card ratios
    ratios: dict[str, Any] = {}
    if top is not None:
        ratios = _parse_top_ratios(top)

    # Pros & cons
    pros, cons = _parse_pros_cons(root)

    # Shareholding
    holding = _parse_shareholding(root)

    # BSE/NSE codes
    bse_code = ""
    nse_symbol = ""
    if top is not None:
        for link_node in top.find_all("a"):
            text = _clean(link_node.text())
            if "BSE:" in text:
                bse_code = text.split("BSE:", 1)[1].strip()
            if "NSE:" in text:
                nse_symbol = text.split("NSE:", 1)[1].strip()

    # Sector/industry from the about section
    sector = ""
    industry = ""
    if top is not None:
        about = top.find(None, class_="about")
        if about is not None:
            about_text = _clean(about.text())
            # Screener often has "Sector: X" in the about block
            sector_match = re.search(r"Sector:\s*([^,\n]+?)(?:\s+Industry:|\s*$)", about_text, re.IGNORECASE)
            if sector_match:
                sector = sector_match.group(1).strip()
            industry_match = re.search(r"Industry:\s*([^,\n]+)", about_text, re.IGNORECASE)
            if industry_match:
                industry = industry_match.group(1).strip()

    high_low = ratios.get("high_low")
    if high_low is not None and not isinstance(high_low, dict):
        high_low = None

    return FundamentalData(
        symbol=symbol.upper(),
        company_name=company_name,
        current_price=ratios.get("current_price"),  # type: ignore[arg-type]
        market_cap=ratios.get("market_cap"),  # type: ignore[arg-type]
        pe_ratio=ratios.get("pe_ratio"),  # type: ignore[arg-type]
        pb_ratio=ratios.get("pb_ratio"),  # type: ignore[arg-type]
        book_value=ratios.get("book_value"),  # type: ignore[arg-type]
        dividend_yield=ratios.get("dividend_yield"),  # type: ignore[arg-type]
        roce=ratios.get("roce"),  # type: ignore[arg-type]
        roe=ratios.get("roe"),  # type: ignore[arg-type]
        face_value=ratios.get("face_value"),  # type: ignore[arg-type]
        high_low=high_low,  # type: ignore[arg-type]
        ev_to_ebitda=ratios.get("ev_to_ebitda"),  # type: ignore[arg-type]
        price_to_sales=ratios.get("price_to_sales"),  # type: ignore[arg-type]
        promoter_holding=holding.get("promoter_holding"),
        fii_holding=holding.get("fii_holding"),
        dii_holding=holding.get("dii_holding"),
        sector=sector,
        industry=industry,
        bse_code=bse_code,
        nse_symbol=nse_symbol or symbol.upper(),
        pros=pros,
        cons=cons,
    )


# ---------------------------------------------------------------------------
# FundamentalScreener class
# ---------------------------------------------------------------------------


class FundamentalScreener:
    """Fundamental stock screener backed by Screener.in data.

    Fetches company pages via httpx, parses financials, and caches results
    for 24 hours in the DuckDB-backed StockCache.

    Args:
        cache: Optional StockCache instance. If None, a default one is created.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        cache: StockCache | None = None,
        timeout: float = _TIMEOUT,
    ) -> None:
        self._cache = cache
        self._timeout = timeout
        self._headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
        }

    @property
    def cache(self) -> StockCache:
        """Lazy-initialise the StockCache on first access."""
        if self._cache is None:
            self._cache = StockCache()
        return self._cache

    async def search_stocks(self, query: str) -> list[SearchResult]:
        """Search for stocks on Screener.in.

        Args:
            query: Search term (company name or symbol).

        Returns:
            List of SearchResult with name, symbol, and URL.
        """
        if not query or len(query.strip()) < 2:
            return []

        async with httpx.AsyncClient(headers=self._headers, timeout=self._timeout) as client:
            resp = await client.get(
                _SEARCH_URL,
                params={"q": query.strip()},
            )
            resp.raise_for_status()

        data = resp.json()
        results: list[SearchResult] = []

        # Screener returns a list of dicts with 'name' and 'url'
        for item in data if isinstance(data, list) else []:
            name = item.get("name", "")
            url = item.get("url", "")
            # Extract symbol from URL like /company/TCS/consolidated/
            symbol = ""
            if "/company/" in url:
                parts = url.split("/company/", 1)[1].split("/")
                if parts:
                    symbol = parts[0].upper()
            if name and symbol:
                results.append(SearchResult(name=name, symbol=symbol, url=url))

        return results

    async def get_fundamentals(self, symbol: str) -> FundamentalData:
        """Fetch detailed fundamentals for a single stock.

        Checks the 24-hour cache first. On cache miss, scrapes
        the Screener.in company page.

        Args:
            symbol: NSE symbol (e.g. ``"TCS"``, ``"RELIANCE"``).

        Returns:
            FundamentalData with all available metrics.

        Raises:
            httpx.HTTPStatusError: If Screener.in returns an error.
        """
        symbol = symbol.upper().strip()

        # Check cache first
        cached = self.cache.get(symbol)
        if cached is not None:
            logger.debug("Cache hit for %s", symbol)
            return self._cache_to_fundamental(cached)

        # Fetch live page
        logger.info("Fetching fundamentals for %s from Screener.in", symbol)
        url = _COMPANY_URL.format(symbol=symbol)

        async with httpx.AsyncClient(
            headers=self._headers,
            timeout=self._timeout,
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        data = _parse_company_page(resp.text, symbol)

        # Persist to cache
        self._update_cache(data)

        return data

    async def screen(self, filters: dict[str, Any]) -> list[StockFundamentals]:
        """Screen cached stocks against fundamental filters.

        This queries the DuckDB cache, so stocks must have been fetched at
        least once (via ``get_fundamentals`` or seed data) within the last
        24 hours.

        Supported filter keys:

        - ``pe_min`` / ``pe_max`` — P/E ratio range
        - ``pb_min`` / ``pb_max`` — P/B ratio range
        - ``market_cap_min`` / ``market_cap_max`` — Market cap in Cr
        - ``roce_min`` — Minimum ROCE %
        - ``roe_min`` — Minimum ROE %
        - ``dividend_yield_min`` — Minimum dividend yield %
        - ``sector`` — Exact sector match
        - ``sort_by`` — Column to sort by (default: ``market_cap``)
        - ``limit`` — Max results (default: 50)

        Args:
            filters: Dict of filter keys to threshold values.

        Returns:
            List of matching StockFundamentals.
        """
        cache_filters: dict[str, Any] = {}

        # Map our filter names to StockCache filter keys
        if "pe_min" in filters:
            cache_filters["pe_gt"] = filters["pe_min"]
        if "pe_max" in filters:
            cache_filters["pe_lt"] = filters["pe_max"]
        if "pb_min" in filters:
            cache_filters["pb_gt"] = filters["pb_min"]
        if "pb_max" in filters:
            cache_filters["pb_lt"] = filters["pb_max"]
        if "market_cap_min" in filters:
            cache_filters["market_cap_gt"] = filters["market_cap_min"]
        if "market_cap_max" in filters:
            cache_filters["market_cap_lt"] = filters["market_cap_max"]
        if "roce_min" in filters:
            cache_filters["roce_gt"] = filters["roce_min"]
        if "roe_min" in filters:
            cache_filters["roe_gt"] = filters["roe_min"]
        if "sector" in filters:
            cache_filters["sector_eq"] = filters["sector"]

        sort_by = filters.get("sort_by", "market_cap")
        limit = filters.get("limit", 50)

        return self.cache.scan(
            filters=cache_filters,
            sort_by=sort_by,
            limit=limit,
        )

    def _update_cache(self, data: FundamentalData) -> None:
        """Persist parsed fundamental data into the StockCache."""
        self.cache.upsert(StockFundamentals(
            symbol=data.symbol,
            name=data.company_name,
            exchange="NSE",
            market_cap=data.market_cap or 0.0,
            pe_ratio=data.pe_ratio or 0.0,
            pb_ratio=data.pb_ratio or 0.0,
            roe=data.roe or 0.0,
            roce=data.roce or 0.0,
            dividend_yield=data.dividend_yield or 0.0,
            sector=data.sector,
            updated_at=time.time(),
        ))

    @staticmethod
    def _cache_to_fundamental(cached: StockFundamentals) -> FundamentalData:
        """Convert a cached StockFundamentals back to FundamentalData."""
        return FundamentalData(
            symbol=cached.symbol,
            company_name=cached.name,
            market_cap=cached.market_cap,
            pe_ratio=cached.pe_ratio,
            pb_ratio=cached.pb_ratio,
            roe=cached.roe,
            roce=cached.roce,
            dividend_yield=cached.dividend_yield,
            sector=cached.sector,
            nse_symbol=cached.symbol,
        )
