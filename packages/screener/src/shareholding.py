"""Shareholding pattern and fundamental data scraper.

Provides async helpers to fetch:
- Shareholding pattern (promoter / FII / DII / public / government) from BSE API
- Financial summary (P&L, balance sheet, cash flow highlights) from Screener.in
- Corporate announcements from BSE API

All HTTP calls use ``httpx`` (async).  HTML parsing uses the stdlib
``html.parser`` (no Playwright / BeautifulSoup dependency).

Data sources:
- Shareholding: ``https://www.screener.in/company/<SYMBOL>/``
- Financials: ``https://www.screener.in/company/<SYMBOL>/consolidated/``
- Corporate announcements: ``https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w``

Usage::

    import asyncio
    from packages.screener.src.shareholding import (
        fetch_shareholding,
        fetch_financial_summary,
        fetch_corporate_announcements,
    )

    shp = asyncio.run(fetch_shareholding("TCS"))
    print(shp.promoter_pct)

    fin = asyncio.run(fetch_financial_summary("RELIANCE"))
    print(fin.roe)

    anns = asyncio.run(fetch_corporate_announcements("INFY", days=30))
    for ann in anns:
        print(ann.date, ann.headline)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from html.parser import HTMLParser
from typing import Any

import httpx

logger = logging.getLogger("flinttrade.screener.shareholding")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCREENER_BASE = "https://www.screener.in"
_BSE_API_BASE = "https://api.bseindia.com"

_TIMEOUT = 20.0
_MAX_RETRIES = 2

_SCREENER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.screener.in/",
}

_BSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.bseindia.com",
    "Referer": "https://www.bseindia.com/",
    "Access-Control-Allow-Origin": "*",
}

# Regex helpers
_NUMBER_RE = re.compile(r"^-?\d[\d,]*(?:\.\d+)?%?$")
_WHITESPACE_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Pydantic-style dataclasses (no Pydantic dependency)
# ---------------------------------------------------------------------------


@dataclass
class QuarterlyHolding:
    """Shareholding percentage for one quarter.

    Attributes:
        quarter: Quarter label, e.g. ``"Mar 2024"``.
        percentage: Holding percentage (0–100).
    """

    quarter: str
    percentage: float


@dataclass
class ShareholdingData:
    """Shareholding pattern for a stock — latest quarter plus history.

    Attributes:
        symbol: NSE/BSE symbol queried.
        as_of_quarter: Latest quarter for which data is available.
        promoter_pct: Promoter holding % (latest quarter).
        fii_pct: FII / foreign institutional holding % (latest quarter).
        dii_pct: DII / domestic institutional holding % (latest quarter).
        public_pct: Public / retail holding % (latest quarter).
        government_pct: Government holding % (latest quarter, 0 if not reported).
        promoter_history: Quarterly history for promoter holding.
        fii_history: Quarterly history for FII holding.
        dii_history: Quarterly history for DII holding.
        public_history: Quarterly history for public holding.
    """

    symbol: str
    as_of_quarter: str = ""
    promoter_pct: float = 0.0
    fii_pct: float = 0.0
    dii_pct: float = 0.0
    public_pct: float = 0.0
    government_pct: float = 0.0
    promoter_history: list[QuarterlyHolding] = field(default_factory=list)
    fii_history: list[QuarterlyHolding] = field(default_factory=list)
    dii_history: list[QuarterlyHolding] = field(default_factory=list)
    public_history: list[QuarterlyHolding] = field(default_factory=list)


@dataclass
class AnnualFinancial:
    """Single year's financial figures.

    Attributes:
        year: Fiscal year label, e.g. ``"Mar 2024"``.
        revenue: Total revenue / sales (₹ Cr).
        net_profit: Net profit after tax (₹ Cr).
        operating_cash_flow: Cash from operations (₹ Cr).
    """

    year: str
    revenue: float | None = None
    net_profit: float | None = None
    operating_cash_flow: float | None = None


@dataclass
class FinancialSummary:
    """Financial highlights for a stock.

    Key ratios reflect the most recently available annual data.

    Attributes:
        symbol: NSE/BSE symbol queried.
        revenue: Latest annual revenue (₹ Cr).
        net_profit: Latest annual net profit (₹ Cr).
        operating_cash_flow: Latest annual operating cash flow (₹ Cr).
        debt_to_equity: Debt-to-equity ratio (latest).
        roe: Return on equity % (latest).
        roce: Return on capital employed % (latest).
        pe_ratio: Price-to-earnings ratio (latest, TTM).
        market_cap: Market capitalisation (₹ Cr).
        book_value: Book value per share (₹).
        annual_history: Last few years of annual revenue / profit / OCF.
    """

    symbol: str
    revenue: float | None = None
    net_profit: float | None = None
    operating_cash_flow: float | None = None
    debt_to_equity: float | None = None
    roe: float | None = None
    roce: float | None = None
    pe_ratio: float | None = None
    market_cap: float | None = None
    book_value: float | None = None
    annual_history: list[AnnualFinancial] = field(default_factory=list)


@dataclass
class Announcement:
    """Single corporate announcement from BSE.

    Attributes:
        symbol: BSE scrip code / symbol.
        date: Announcement date string (as returned by BSE API).
        category: Category label from BSE (e.g. ``"Board Meeting"``, ``"Dividend"``).
        headline: Short description of the announcement.
        attachment_url: Link to the PDF/document, if available.
    """

    symbol: str
    date: str
    category: str
    headline: str
    attachment_url: str = ""


# ---------------------------------------------------------------------------
# Minimal HTML table parser (no BeautifulSoup dependency)
# ---------------------------------------------------------------------------


class _TableParser(HTMLParser):
    """Extract data from the first matching ``<table>`` or ``<section>`` with
    a target id.

    Only records text within ``<td>`` and ``<th>`` tags.  Tracks nesting
    depth so nested tables are handled gracefully.
    """

    def __init__(self, target_id: str) -> None:
        super().__init__()
        self._target_id = target_id
        self._inside_target = False
        self._depth = 0
        self._rows: list[list[str]] = []
        self._current_row: list[str] = []
        self._current_cell: list[str] = []
        self._in_cell = False
        self._table_depth = 0

    # ---- HTMLParser callbacks -----------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        if tag in ("section", "div", "table") and attr_dict.get("id") == self._target_id:
            self._inside_target = True
            self._depth = 1
            return

        if self._inside_target:
            self._depth += 1
            if tag == "tr":
                self._current_row = []
            elif tag in ("td", "th"):
                self._current_cell = []
                self._in_cell = True

    def handle_endtag(self, tag: str) -> None:
        if not self._inside_target:
            return
        if tag in ("td", "th") and self._in_cell:
            text = _WHITESPACE_RE.sub(" ", "".join(self._current_cell)).strip()
            self._current_row.append(text)
            self._in_cell = False
        elif tag == "tr":
            if self._current_row:
                self._rows.append(self._current_row)
        self._depth -= 1
        if self._depth <= 0:
            self._inside_target = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._current_cell.append(data)

    # ---- Public API ---------------------------------------------------------

    @property
    def rows(self) -> list[list[str]]:
        """All captured rows as lists of cell text."""
        return self._rows


class _RatioParser(HTMLParser):
    """Extract key ratio values from Screener.in's ``#top-ratios`` list."""

    def __init__(self) -> None:
        super().__init__()
        self._inside = False
        self._depth = 0
        self._label: str = ""
        self._in_name = False
        self._in_value = False
        self._name_buf: list[str] = []
        self._value_buf: list[str] = []
        self.ratios: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        if tag == "ul" and attr_dict.get("id") == "top-ratios":
            self._inside = True
            self._depth = 1
            return
        if not self._inside:
            return
        self._depth += 1
        classes = attr_dict.get("class", "") or ""
        if "name" in classes:
            self._in_name = True
            self._name_buf = []
        elif "value" in classes or "number" in classes:
            self._in_value = True
            self._value_buf = []

    def handle_endtag(self, tag: str) -> None:
        if not self._inside:
            return
        if self._in_name and tag == "span":
            self._label = _WHITESPACE_RE.sub(" ", "".join(self._name_buf)).strip()
            self._in_name = False
        elif self._in_value and tag == "span":
            val = _WHITESPACE_RE.sub(" ", "".join(self._value_buf)).strip()
            if self._label:
                self.ratios[self._label] = val
            self._in_value = False
        self._depth -= 1
        if self._depth <= 0:
            self._inside = False

    def handle_data(self, data: str) -> None:
        if self._in_name:
            self._name_buf.append(data)
        elif self._in_value:
            self._value_buf.append(data)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


async def _get_screener_html(symbol: str, consolidated: bool = True) -> str:
    """Fetch the Screener.in company page HTML.

    Args:
        symbol: NSE/BSE symbol (e.g. ``"TCS"``).
        consolidated: If ``True`` fetch consolidated financials.

    Returns:
        Raw HTML string.

    Raises:
        httpx.HTTPStatusError: On non-2xx responses.
        httpx.RequestError: On network errors.
    """
    suffix = "consolidated/" if consolidated else ""
    url = f"{_SCREENER_BASE}/company/{symbol.upper()}/{suffix}"
    async with httpx.AsyncClient(
        headers=_SCREENER_HEADERS,
        timeout=_TIMEOUT,
        follow_redirects=True,
    ) as client:
        for attempt in range(1, _MAX_RETRIES + 2):
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.text
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                if attempt > _MAX_RETRIES:
                    raise
                logger.warning(
                    "Screener fetch attempt %d failed for %s: %s",
                    attempt,
                    symbol,
                    exc,
                )
    return ""  # unreachable


def _parse_number(text: str) -> float | None:
    """Convert a human-readable number string to float.

    Handles commas, ``%``, ``Cr``, ``L`` suffixes.

    Args:
        text: Raw text from HTML table cell.

    Returns:
        Float value or ``None`` if parsing fails.
    """
    t = text.strip().replace(",", "").replace("%", "").replace("Cr", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Shareholding parser
# ---------------------------------------------------------------------------


def _parse_shareholding_table(html: str) -> ShareholdingData:
    """Parse the quarterly-shp section from Screener.in HTML.

    Args:
        html: Full Screener.in page HTML.

    Returns:
        Partially populated :class:`ShareholdingData` (symbol set to ``""``).
    """
    parser = _TableParser("quarterly-shp")
    parser.feed(html)
    rows = parser.rows

    result = ShareholdingData(symbol="")

    if not rows:
        logger.debug("shareholding table not found in HTML")
        return result

    # First row is headers: ["", "Mar 2024", "Dec 2023", ...]
    headers = rows[0][1:] if len(rows[0]) > 1 else []
    if headers:
        result.as_of_quarter = headers[0]

    # Category label → attribute mapping (case-insensitive prefix match)
    _category_map = {
        "promoter": ("promoter_pct", "promoter_history"),
        "foreign institution": ("fii_pct", "fii_history"),
        "fii": ("fii_pct", "fii_history"),
        "domestic institution": ("dii_pct", "dii_history"),
        "dii": ("dii_pct", "dii_history"),
        "mutual fund": ("dii_pct", "dii_history"),
        "government": ("government_pct", None),
        "public": ("public_pct", "public_history"),
    }

    for row in rows[1:]:
        if not row:
            continue
        label = row[0].lower()
        matched_pct_attr: str | None = None
        matched_history_attr: str | None = None
        for key, (pct_attr, hist_attr) in _category_map.items():
            if key in label:
                matched_pct_attr = pct_attr
                matched_history_attr = hist_attr
                break

        if matched_pct_attr is None:
            continue

        history: list[QuarterlyHolding] = []
        for i, qtr in enumerate(headers):
            cell_idx = i + 1
            if cell_idx >= len(row):
                break
            val = _parse_number(row[cell_idx])
            if val is not None:
                history.append(QuarterlyHolding(quarter=qtr, percentage=val))

        # Latest = first history entry
        if history:
            setattr(result, matched_pct_attr, history[0].percentage)
            if matched_history_attr:
                setattr(result, matched_history_attr, history)

    return result


# ---------------------------------------------------------------------------
# Financial summary parser
# ---------------------------------------------------------------------------


def _parse_financial_table(
    html: str, section_id: str
) -> dict[str, list[tuple[str, float]]]:
    """Parse a Screener.in financial table (P&L / cash flow) into a dict.

    Args:
        html: Full Screener.in page HTML.
        section_id: HTML element id (e.g. ``"profit-loss"`` or ``"cash-flow"``).

    Returns:
        Mapping of ``{row_label: [(year, value), ...]}`` sorted newest first.
    """
    parser = _TableParser(section_id)
    parser.feed(html)
    rows = parser.rows
    if not rows:
        return {}

    headers = rows[0][1:] if len(rows[0]) > 1 else []
    result: dict[str, list[tuple[str, float]]] = {}

    for row in rows[1:]:
        if not row:
            continue
        label = _WHITESPACE_RE.sub(" ", row[0]).strip()
        entries: list[tuple[str, float]] = []
        for i, year in enumerate(headers):
            cell_idx = i + 1
            if cell_idx >= len(row):
                break
            val = _parse_number(row[cell_idx])
            if val is not None:
                entries.append((year, val))
        if entries:
            result[label] = entries

    return result


def _parse_ratios(html: str) -> dict[str, str]:
    """Extract top-ratios from Screener.in page HTML.

    Args:
        html: Full Screener.in page HTML.

    Returns:
        Mapping ``{ratio_name: raw_string_value}``.
    """
    parser = _RatioParser()
    parser.feed(html)
    return parser.ratios


def _build_annual_history(
    pnl: dict[str, list[tuple[str, float]]],
    cashflow: dict[str, list[tuple[str, float]]],
) -> list[AnnualFinancial]:
    """Combine P&L and cash-flow tables into per-year records.

    Args:
        pnl: Output of :func:`_parse_financial_table` for profit-loss section.
        cashflow: Output of :func:`_parse_financial_table` for cash-flow section.

    Returns:
        List of :class:`AnnualFinancial` records, newest year first.
    """
    # Try common label variants
    _sales_keys = ["Sales", "Revenue", "Net Sales", "Total Revenue"]
    _profit_keys = ["Net Profit", "Profit after tax", "PAT"]
    _ocf_keys = ["Cash from Operating Activity", "Operating Activity", "Operating Cash Flow"]

    def _first_match(
        table: dict[str, list[tuple[str, float]]], candidates: list[str]
    ) -> list[tuple[str, float]]:
        for key in candidates:
            for k, v in table.items():
                if key.lower() in k.lower():
                    return v
        return []

    sales_series = _first_match(pnl, _sales_keys)
    profit_series = _first_match(pnl, _profit_keys)
    ocf_series = _first_match(cashflow, _ocf_keys)

    # Build year index
    all_years: list[str] = []
    for series in (sales_series, profit_series, ocf_series):
        for year, _ in series:
            if year not in all_years:
                all_years.append(year)

    history: list[AnnualFinancial] = []
    sales_map = dict(sales_series)
    profit_map = dict(profit_series)
    ocf_map = dict(ocf_series)

    for year in all_years:
        history.append(
            AnnualFinancial(
                year=year,
                revenue=sales_map.get(year),
                net_profit=profit_map.get(year),
                operating_cash_flow=ocf_map.get(year),
            )
        )

    return history


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------


async def fetch_shareholding(
    symbol: str,
    consolidated: bool = True,
) -> ShareholdingData:
    """Fetch and parse the quarterly shareholding pattern for a stock.

    Scrapes the Screener.in company page (no login required for public data)
    and parses the quarterly shareholding section.

    Args:
        symbol: NSE/BSE trading symbol (e.g. ``"TCS"``).
        consolidated: Fetch consolidated view if ``True`` (default).

    Returns:
        :class:`ShareholdingData` with promoter/FII/DII/public percentages
        and quarterly history.

    Raises:
        httpx.HTTPStatusError: On HTTP error from Screener.in.
        httpx.RequestError: On network errors.
    """
    html = await _get_screener_html(symbol, consolidated=consolidated)
    data = _parse_shareholding_table(html)
    data.symbol = symbol.upper()
    logger.info(
        "fetch_shareholding: %s promoter=%.1f%% fii=%.1f%% dii=%.1f%%",
        symbol,
        data.promoter_pct,
        data.fii_pct,
        data.dii_pct,
    )
    return data


async def fetch_financial_summary(
    symbol: str,
    consolidated: bool = True,
) -> FinancialSummary:
    """Fetch financial highlights for a stock from Screener.in.

    Parses the P&L statement, cash-flow statement, and top ratios section
    to extract revenue, net profit, operating cash flow, and key ratios.

    Args:
        symbol: NSE/BSE trading symbol (e.g. ``"RELIANCE"``).
        consolidated: Fetch consolidated financials if ``True`` (default).

    Returns:
        :class:`FinancialSummary` with latest annual figures and ratio snapshot.

    Raises:
        httpx.HTTPStatusError: On HTTP error from Screener.in.
        httpx.RequestError: On network errors.
    """
    html = await _get_screener_html(symbol, consolidated=consolidated)

    pnl = _parse_financial_table(html, "profit-loss")
    cashflow = _parse_financial_table(html, "cash-flow")
    ratios = _parse_ratios(html)
    history = _build_annual_history(pnl, cashflow)

    # Extract latest values from history
    latest = history[0] if history else None

    def _ratio_float(keys: list[str]) -> float | None:
        for k in keys:
            for rk, rv in ratios.items():
                if k.lower() in rk.lower():
                    return _parse_number(rv)
        return None

    summary = FinancialSummary(
        symbol=symbol.upper(),
        revenue=latest.revenue if latest else None,
        net_profit=latest.net_profit if latest else None,
        operating_cash_flow=latest.operating_cash_flow if latest else None,
        debt_to_equity=_ratio_float(["Debt / Eq", "D/E", "Debt to Equity"]),
        roe=_ratio_float(["ROE", "Return on equity"]),
        roce=_ratio_float(["ROCE", "Return on capital"]),
        pe_ratio=_ratio_float(["Stock P/E", "P/E"]),
        market_cap=_ratio_float(["Market Cap"]),
        book_value=_ratio_float(["Book Value"]),
        annual_history=history,
    )
    logger.info(
        "fetch_financial_summary: %s revenue=%s roe=%s roce=%s",
        symbol,
        summary.revenue,
        summary.roe,
        summary.roce,
    )
    return summary


async def fetch_corporate_announcements(
    symbol: str,
    days: int = 30,
    bse_token: str = "",
) -> list[Announcement]:
    """Fetch recent corporate announcements from the BSE API.

    Uses the BSE ``AnnSubCategoryGetData`` endpoint (same as the reference
    screenerScraper.py).  Paginates automatically if more than 50 results
    are returned.

    Args:
        symbol: BSE scrip code or NSE symbol used as ``strScrip`` parameter.
            If you pass an NSE symbol the BSE API will attempt a match; for
            reliable results pass the 6-digit BSE scrip code (e.g. ``"500325"``).
        days: Look-back window in days (default 30, maximum 365).
        bse_token: BSE scrip token for targeted queries.  If empty, results
            cover all stocks (useful for market-wide announcements).

    Returns:
        List of :class:`Announcement` objects, newest first.
        Returns an empty list on any HTTP / parse error.

    Raises:
        httpx.RequestError: On unrecoverable network errors.
    """
    today = date.today()
    from_date = today - timedelta(days=min(days, 365))
    to_str = today.strftime("%Y%m%d")
    from_str = from_date.strftime("%Y%m%d")
    scrip = bse_token or symbol

    base_url = (
        f"{_BSE_API_BASE}/BseIndiaAPI/api/AnnSubCategoryGetData/w"
        f"?pageno={{pageno}}&strCat=-1"
        f"&strPrevDate={from_str}"
        f"&strScrip={scrip}"
        f"&strSearch=P"
        f"&strToDate={to_str}"
        f"&strType=C"
        f"&subcategory=-1"
    )

    announcements: list[Announcement] = []

    async with httpx.AsyncClient(
        headers=_BSE_HEADERS,
        timeout=_TIMEOUT,
        follow_redirects=True,
    ) as client:
        page = 1
        while True:
            url = base_url.format(pageno=page)
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                payload: dict[str, Any] = resp.json()
            except (httpx.HTTPStatusError, httpx.RequestError, json.JSONDecodeError) as exc:
                logger.warning("BSE announcements fetch failed (page=%d): %s", page, exc)
                break

            table: list[dict[str, Any]] = payload.get("Table", [])
            table1: list[dict[str, Any]] = payload.get("Table1", [])

            for row in table:
                announcements.append(
                    Announcement(
                        symbol=str(row.get("SCRIP_CD", symbol)),
                        date=str(row.get("DT_TM", "")),
                        category=str(row.get("CATEGORYNAME", "")),
                        headline=str(row.get("HEADLINE", "")),
                        attachment_url=str(row.get("ATTACHMENTNAME", "")),
                    )
                )

            # Pagination
            total_rows = 0
            if table1:
                try:
                    total_rows = int(table1[0].get("ROWCNT", 0))
                except (KeyError, ValueError, TypeError):
                    pass

            if total_rows > page * 50:
                page += 1
            else:
                break

    logger.info(
        "fetch_corporate_announcements: %s (%d days) → %d announcements",
        symbol,
        days,
        len(announcements),
    )
    return announcements
