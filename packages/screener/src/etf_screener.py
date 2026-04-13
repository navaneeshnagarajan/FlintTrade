"""ETF screener — catalogue, momentum scoring, asset quilt, and screening.

Provides a curated catalogue of 50+ popular India ETFs with analytics:
- Weighted momentum score (40% 12m + 30% 6m + 20% 3m + 10% 1m)
- Calendar-year return grid (asset quilt) for cross-asset comparison
- 52-week high/low tracking
- Normalised sparkline generation for mini charts
- Multi-criteria ETF screener (sort by momentum, returns, AUM)

Usage::

    from packages.screener.src.etf_screener import (
        ETF_CATALOGUE,
        ETFRecord,
        calculate_momentum_score,
        calculate_asset_quilt,
        get_52w_high_low,
        get_sparkline,
        screen_etfs,
    )

    score = calculate_momentum_score(
        returns_1m=2.1,
        returns_3m=5.4,
        returns_6m=8.9,
        returns_12m=14.3,
    )

    top = screen_etfs(list(ETF_CATALOGUE.values()), sort_by="momentum", min_aum="medium")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger("flinttrade.screener.etf_screener")

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

ETFCategory = Literal["Equity", "Debt", "Gold", "International", "Sector"]
AUMBucket = Literal["small", "medium", "large", "mega"]
SortBy = Literal["momentum", "return_1m", "return_3m", "return_6m", "return_12m", "aum"]

# ---------------------------------------------------------------------------
# AUM bucket ordering for comparison (higher index = larger AUM)
# ---------------------------------------------------------------------------

_AUM_ORDER: dict[AUMBucket, int] = {"small": 0, "medium": 1, "large": 2, "mega": 3}

# ---------------------------------------------------------------------------
# ETFRecord — immutable catalogue entry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ETFRecord:
    """Single ETF entry in the catalogue.

    Attributes:
        symbol: NSE trading symbol (e.g. ``NIFTYBEES``).
        name: Human-readable full name.
        category: Asset class category.
        aum_bucket: Approximate AUM tier.
        benchmark: Underlying index or benchmark tracked.
        fund_house: AMC / fund house name.
        expense_ratio: Annual expense ratio in percent (approximate).
    """

    symbol: str
    name: str
    category: ETFCategory
    aum_bucket: AUMBucket
    benchmark: str = ""
    fund_house: str = ""
    expense_ratio: float = 0.0


# ---------------------------------------------------------------------------
# ETF_CATALOGUE — 50+ India ETFs
# ---------------------------------------------------------------------------

ETF_CATALOGUE: dict[str, ETFRecord] = {
    # ---- Broad Equity -------------------------------------------------------
    "NIFTYBEES": ETFRecord(
        symbol="NIFTYBEES",
        name="Nippon India ETF Nifty BeES",
        category="Equity",
        aum_bucket="mega",
        benchmark="Nifty 50",
        fund_house="Nippon India",
        expense_ratio=0.04,
    ),
    "JUNIORBEES": ETFRecord(
        symbol="JUNIORBEES",
        name="Nippon India ETF Junior BeES",
        category="Equity",
        aum_bucket="large",
        benchmark="Nifty Next 50",
        fund_house="Nippon India",
        expense_ratio=0.19,
    ),
    "ICICIB22": ETFRecord(
        symbol="ICICIB22",
        name="ICICI Prudential Nifty ETF",
        category="Equity",
        aum_bucket="large",
        benchmark="Nifty 50",
        fund_house="ICICI Prudential",
        expense_ratio=0.03,
    ),
    "KOTAKBKETF": ETFRecord(
        symbol="KOTAKBKETF",
        name="Kotak Nifty 50 ETF",
        category="Equity",
        aum_bucket="large",
        benchmark="Nifty 50",
        fund_house="Kotak",
        expense_ratio=0.05,
    ),
    "SETFNIF50": ETFRecord(
        symbol="SETFNIF50",
        name="SBI ETF Nifty 50",
        category="Equity",
        aum_bucket="mega",
        benchmark="Nifty 50",
        fund_house="SBI",
        expense_ratio=0.07,
    ),
    "HDFC50ETF": ETFRecord(
        symbol="HDFC50ETF",
        name="HDFC Nifty 50 ETF",
        category="Equity",
        aum_bucket="large",
        benchmark="Nifty 50",
        fund_house="HDFC",
        expense_ratio=0.05,
    ),
    "UTINIFTETF": ETFRecord(
        symbol="UTINIFTETF",
        name="UTI Nifty 50 ETF",
        category="Equity",
        aum_bucket="large",
        benchmark="Nifty 50",
        fund_house="UTI",
        expense_ratio=0.06,
    ),
    "MIRAE50ETF": ETFRecord(
        symbol="MIRAE50ETF",
        name="Mirae Asset Nifty 50 ETF",
        category="Equity",
        aum_bucket="medium",
        benchmark="Nifty 50",
        fund_house="Mirae Asset",
        expense_ratio=0.04,
    ),
    "NIF100BEES": ETFRecord(
        symbol="NIF100BEES",
        name="Nippon India ETF Nifty 100",
        category="Equity",
        aum_bucket="medium",
        benchmark="Nifty 100",
        fund_house="Nippon India",
        expense_ratio=0.13,
    ),
    "MIDCAPETF": ETFRecord(
        symbol="MIDCAPETF",
        name="Nippon India ETF Nifty Midcap 150",
        category="Equity",
        aum_bucket="medium",
        benchmark="Nifty Midcap 150",
        fund_house="Nippon India",
        expense_ratio=0.32,
    ),
    "HDFCMOMENT": ETFRecord(
        symbol="HDFCMOMENT",
        name="HDFC Nifty200 Momentum 30 ETF",
        category="Equity",
        aum_bucket="medium",
        benchmark="Nifty200 Momentum 30",
        fund_house="HDFC",
        expense_ratio=0.30,
    ),
    "MOMOMENTUM": ETFRecord(
        symbol="MOMOMENTUM",
        name="Motilal Oswal Nifty Midcap 150 Momentum 50 ETF",
        category="Equity",
        aum_bucket="small",
        benchmark="Nifty Midcap150 Momentum 50",
        fund_house="Motilal Oswal",
        expense_ratio=0.30,
    ),
    "MON100": ETFRecord(
        symbol="MON100",
        name="Motilal Oswal Nifty 500 ETF",
        category="Equity",
        aum_bucket="small",
        benchmark="Nifty 500",
        fund_house="Motilal Oswal",
        expense_ratio=0.10,
    ),
    "LOWVOLIETF": ETFRecord(
        symbol="LOWVOLIETF",
        name="ICICI Prudential Nifty Low Vol 30 ETF",
        category="Equity",
        aum_bucket="small",
        benchmark="Nifty Low Volatility 30",
        fund_house="ICICI Prudential",
        expense_ratio=0.30,
    ),
    "QUAL30IETF": ETFRecord(
        symbol="QUAL30IETF",
        name="ICICI Prudential Nifty Quality Low-Volatility 30 ETF",
        category="Equity",
        aum_bucket="small",
        benchmark="Nifty Quality Low-Volatility 30",
        fund_house="ICICI Prudential",
        expense_ratio=0.30,
    ),
    "ALPHA": ETFRecord(
        symbol="ALPHA",
        name="Nippon India ETF Nifty Alpha Low-Volatility 30",
        category="Equity",
        aum_bucket="small",
        benchmark="Nifty Alpha Low-Volatility 30",
        fund_house="Nippon India",
        expense_ratio=0.30,
    ),
    "SMALLCAP": ETFRecord(
        symbol="SMALLCAP",
        name="Nippon India ETF Nifty Smallcap 250",
        category="Equity",
        aum_bucket="small",
        benchmark="Nifty Smallcap 250",
        fund_house="Nippon India",
        expense_ratio=0.40,
    ),
    # ---- Sector ETFs --------------------------------------------------------
    "BANKBEES": ETFRecord(
        symbol="BANKBEES",
        name="Nippon India ETF Bank BeES",
        category="Sector",
        aum_bucket="mega",
        benchmark="Nifty Bank",
        fund_house="Nippon India",
        expense_ratio=0.19,
    ),
    "PSUBNKBEES": ETFRecord(
        symbol="PSUBNKBEES",
        name="Nippon India ETF PSU Bank BeES",
        category="Sector",
        aum_bucket="large",
        benchmark="Nifty PSU Bank",
        fund_house="Nippon India",
        expense_ratio=0.49,
    ),
    "ITBEES": ETFRecord(
        symbol="ITBEES",
        name="Nippon India ETF IT BeES",
        category="Sector",
        aum_bucket="large",
        benchmark="Nifty IT",
        fund_house="Nippon India",
        expense_ratio=0.52,
    ),
    "PHARMABEES": ETFRecord(
        symbol="PHARMABEES",
        name="Nippon India ETF Pharma BeES",
        category="Sector",
        aum_bucket="medium",
        benchmark="Nifty Pharma",
        fund_house="Nippon India",
        expense_ratio=0.58,
    ),
    "INFRAIETF": ETFRecord(
        symbol="INFRAIETF",
        name="ICICI Prudential Nifty Infrastructure ETF",
        category="Sector",
        aum_bucket="medium",
        benchmark="Nifty Infrastructure",
        fund_house="ICICI Prudential",
        expense_ratio=0.25,
    ),
    "CONSUMBEES": ETFRecord(
        symbol="CONSUMBEES",
        name="Nippon India ETF Consumption",
        category="Sector",
        aum_bucket="small",
        benchmark="Nifty India Consumption",
        fund_house="Nippon India",
        expense_ratio=0.46,
    ),
    "AUTOBEES": ETFRecord(
        symbol="AUTOBEES",
        name="Nippon India ETF Auto",
        category="Sector",
        aum_bucket="small",
        benchmark="Nifty Auto",
        fund_house="Nippon India",
        expense_ratio=0.58,
    ),
    "EVINDIA": ETFRecord(
        symbol="EVINDIA",
        name="Mirae Asset Nifty EV & New Age Automotive ETF",
        category="Sector",
        aum_bucket="small",
        benchmark="Nifty EV & New Age Automotive",
        fund_house="Mirae Asset",
        expense_ratio=0.35,
    ),
    "FINIETF": ETFRecord(
        symbol="FINIETF",
        name="ICICI Prudential Nifty Financial Services ETF",
        category="Sector",
        aum_bucket="large",
        benchmark="Nifty Financial Services",
        fund_house="ICICI Prudential",
        expense_ratio=0.11,
    ),
    "HDFCPVTBAN": ETFRecord(
        symbol="HDFCPVTBAN",
        name="HDFC Nifty Private Bank ETF",
        category="Sector",
        aum_bucket="small",
        benchmark="Nifty Private Bank",
        fund_house="HDFC",
        expense_ratio=0.30,
    ),
    "HEALTHY": ETFRecord(
        symbol="HEALTHY",
        name="Mirae Asset Nifty Healthcare ETF",
        category="Sector",
        aum_bucket="small",
        benchmark="Nifty Healthcare",
        fund_house="Mirae Asset",
        expense_ratio=0.35,
    ),
    # ---- Gold ETFs ----------------------------------------------------------
    "GOLDBEES": ETFRecord(
        symbol="GOLDBEES",
        name="Nippon India ETF Gold BeES",
        category="Gold",
        aum_bucket="mega",
        benchmark="Domestic gold price",
        fund_house="Nippon India",
        expense_ratio=0.82,
    ),
    "HDFCGOLD": ETFRecord(
        symbol="HDFCGOLD",
        name="HDFC Gold ETF",
        category="Gold",
        aum_bucket="large",
        benchmark="Domestic gold price",
        fund_house="HDFC",
        expense_ratio=0.59,
    ),
    "AXISGOLD": ETFRecord(
        symbol="AXISGOLD",
        name="Axis Gold ETF",
        category="Gold",
        aum_bucket="medium",
        benchmark="Domestic gold price",
        fund_house="Axis",
        expense_ratio=0.53,
    ),
    "SBISGOLD": ETFRecord(
        symbol="SBISGOLD",
        name="SBI ETF Gold",
        category="Gold",
        aum_bucket="large",
        benchmark="Domestic gold price",
        fund_house="SBI",
        expense_ratio=0.49,
    ),
    "KOTAKGOLD": ETFRecord(
        symbol="KOTAKGOLD",
        name="Kotak Gold ETF",
        category="Gold",
        aum_bucket="large",
        benchmark="Domestic gold price",
        fund_house="Kotak",
        expense_ratio=0.55,
    ),
    "ICICIGOLD": ETFRecord(
        symbol="ICICIGOLD",
        name="ICICI Prudential Gold ETF",
        category="Gold",
        aum_bucket="medium",
        benchmark="Domestic gold price",
        fund_house="ICICI Prudential",
        expense_ratio=0.50,
    ),
    "SILVERIETF": ETFRecord(
        symbol="SILVERIETF",
        name="ICICI Prudential Silver ETF",
        category="Gold",
        aum_bucket="medium",
        benchmark="Domestic silver price",
        fund_house="ICICI Prudential",
        expense_ratio=0.40,
    ),
    # ---- Debt ETFs ----------------------------------------------------------
    "LIQUIDBEES": ETFRecord(
        symbol="LIQUIDBEES",
        name="Nippon India ETF Liquid BeES",
        category="Debt",
        aum_bucket="mega",
        benchmark="Nifty 1D Rate",
        fund_house="Nippon India",
        expense_ratio=0.69,
    ),
    "CPSEETF": ETFRecord(
        symbol="CPSEETF",
        name="Nippon India ETF CPSE",
        category="Equity",
        aum_bucket="large",
        benchmark="Nifty CPSE",
        fund_house="Nippon India",
        expense_ratio=0.01,
    ),
    "ICICILIQ": ETFRecord(
        symbol="ICICILIQ",
        name="ICICI Prudential Liquid ETF",
        category="Debt",
        aum_bucket="large",
        benchmark="Nifty 1D Rate",
        fund_house="ICICI Prudential",
        expense_ratio=0.25,
    ),
    "GSEC10IETF": ETFRecord(
        symbol="GSEC10IETF",
        name="ICICI Prudential Nifty 10yr Benchmark G-Sec ETF",
        category="Debt",
        aum_bucket="small",
        benchmark="Nifty 10yr Benchmark G-Sec",
        fund_house="ICICI Prudential",
        expense_ratio=0.15,
    ),
    "GSEC5IETF": ETFRecord(
        symbol="GSEC5IETF",
        name="ICICI Prudential Nifty 5yr Benchmark G-Sec ETF",
        category="Debt",
        aum_bucket="small",
        benchmark="Nifty 5yr Benchmark G-Sec",
        fund_house="ICICI Prudential",
        expense_ratio=0.15,
    ),
    "HDFCNIFBAN": ETFRecord(
        symbol="HDFCNIFBAN",
        name="HDFC Nifty G-Sec Apr 2029 Debt ETF",
        category="Debt",
        aum_bucket="small",
        benchmark="Nifty G-Sec Apr 2029",
        fund_house="HDFC",
        expense_ratio=0.15,
    ),
    "BBETF0432": ETFRecord(
        symbol="BBETF0432",
        name="Bharat Bond ETF April 2032",
        category="Debt",
        aum_bucket="medium",
        benchmark="Nifty BHARAT Bond Index April 2032",
        fund_house="Edelweiss",
        expense_ratio=0.0005,
    ),
    "BBETF0425": ETFRecord(
        symbol="BBETF0425",
        name="Bharat Bond ETF April 2025",
        category="Debt",
        aum_bucket="medium",
        benchmark="Nifty BHARAT Bond Index April 2025",
        fund_house="Edelweiss",
        expense_ratio=0.0005,
    ),
    # ---- International ETFs -------------------------------------------------
    "MAFANG": ETFRecord(
        symbol="MAFANG",
        name="Mirae Asset NYSE FANG+ ETF",
        category="International",
        aum_bucket="large",
        benchmark="NYSE FANG+",
        fund_house="Mirae Asset",
        expense_ratio=0.48,
    ),
    "MON50": ETFRecord(
        symbol="MON50",
        name="Motilal Oswal Nasdaq 100 ETF",
        category="International",
        aum_bucket="mega",
        benchmark="Nasdaq 100",
        fund_house="Motilal Oswal",
        expense_ratio=0.58,
    ),
    "MOTILALOFS&P": ETFRecord(
        symbol="MOTILALOS500",
        name="Motilal Oswal S&P 500 Index Fund ETF",
        category="International",
        aum_bucket="large",
        benchmark="S&P 500",
        fund_house="Motilal Oswal",
        expense_ratio=0.55,
    ),
    "HANGSENG": ETFRecord(
        symbol="HANGSENG",
        name="Mirae Asset Hang Seng TECH ETF",
        category="International",
        aum_bucket="medium",
        benchmark="Hang Seng TECH",
        fund_house="Mirae Asset",
        expense_ratio=0.48,
    ),
    "ICICIJAPETF": ETFRecord(
        symbol="ICICIJAPETF",
        name="ICICI Prudential Japan iShares ETF",
        category="International",
        aum_bucket="small",
        benchmark="MSCI Japan",
        fund_house="ICICI Prudential",
        expense_ratio=0.50,
    ),
    "AAAETF": ETFRecord(
        symbol="AAAETF",
        name="Nippon India ETF Nifty AAA CPSE Bond Plus SDL — Apr 2027 Maturity 60:40",
        category="Debt",
        aum_bucket="small",
        benchmark="Nifty AAA CPSE Bond Plus SDL",
        fund_house="Nippon India",
        expense_ratio=0.15,
    ),
    "MAFANGPLUS": ETFRecord(
        symbol="MAFANGPLUS",
        name="Mirae Asset NYSE FANG+ ETF (additional units)",
        category="International",
        aum_bucket="medium",
        benchmark="NYSE FANG+",
        fund_house="Mirae Asset",
        expense_ratio=0.48,
    ),
    "MOITATF": ETFRecord(
        symbol="MOITATF",
        name="Motilal Oswal Nifty India Defence ETF",
        category="Sector",
        aum_bucket="medium",
        benchmark="Nifty India Defence",
        fund_house="Motilal Oswal",
        expense_ratio=0.35,
    ),
    "PSUBNKETF": ETFRecord(
        symbol="PSUBNKETF",
        name="ICICI Prudential PSU Bank ETF",
        category="Sector",
        aum_bucket="medium",
        benchmark="Nifty PSU Bank",
        fund_house="ICICI Prudential",
        expense_ratio=0.18,
    ),
    "SETFGOLD": ETFRecord(
        symbol="SETFGOLD",
        name="SBI ETF Gold (alternate listing)",
        category="Gold",
        aum_bucket="large",
        benchmark="Domestic gold price",
        fund_house="SBI",
        expense_ratio=0.49,
    ),
}


# ---------------------------------------------------------------------------
# Momentum scoring (absorbed from marketcalls etftracker analytics)
# ---------------------------------------------------------------------------


def calculate_momentum_score(
    returns_1m: float,
    returns_3m: float,
    returns_6m: float,
    returns_12m: float,
) -> float:
    """Calculate a weighted momentum score from multi-timeframe returns.

    Uses the standard cross-sectional momentum weighting:
    - 40 % 12-month return (long-term trend)
    - 30 % 6-month return  (medium-term trend)
    - 20 % 3-month return  (short-term trend)
    - 10 % 1-month return  (very recent momentum)

    All return arguments are in **percent** (e.g. pass ``14.5`` for 14.5 %).

    Args:
        returns_1m: 1-month return in percent.
        returns_3m: 3-month return in percent.
        returns_6m: 6-month return in percent.
        returns_12m: 12-month return in percent.

    Returns:
        Composite momentum score in percent (same unit as inputs).

    Examples:
        >>> calculate_momentum_score(2.1, 5.4, 8.9, 14.3)
        9.29
    """
    score = (
        0.10 * returns_1m
        + 0.20 * returns_3m
        + 0.30 * returns_6m
        + 0.40 * returns_12m
    )
    return round(score, 4)


# ---------------------------------------------------------------------------
# Asset quilt
# ---------------------------------------------------------------------------


def calculate_asset_quilt(
    symbols: list[str],
    years: list[int],
    annual_returns: dict[str, dict[int, float]],
) -> dict[str, dict[str, float | int]]:
    """Build a calendar-year return grid for the asset quilt visualisation.

    Returns a dict structured for frontend rendering:

    .. code-block:: python

        {
            "NIFTYBEES": {
                "2020": 14.5,
                "2021": 24.1,
                "rank_2020": 3,   # 1 = best performer that year
                "rank_2021": 1,
            },
            ...
        }

    Args:
        symbols: Ordered list of ETF symbols to include.
        years: Calendar years to include (e.g. ``[2020, 2021, 2022, 2023]``).
        annual_returns: Nested mapping ``{symbol: {year: return_pct}}``.
            Missing entries are represented as ``None`` in output.

    Returns:
        Dict keyed by symbol; each value is a flat dict of
        ``year`` → return and ``rank_<year>`` → rank.

    Raises:
        ValueError: If ``symbols`` or ``years`` is empty.
    """
    if not symbols:
        raise ValueError("symbols list must not be empty")
    if not years:
        raise ValueError("years list must not be empty")

    # Build result structure
    result: dict[str, dict[str, float | int]] = {sym: {} for sym in symbols}

    for year in years:
        year_key = str(year)

        # Collect returns for ranking (only symbols with actual data)
        year_data: list[tuple[str, float]] = []
        for sym in symbols:
            ret = annual_returns.get(sym, {}).get(year)
            if ret is not None:
                year_data.append((sym, ret))
                result[sym][year_key] = round(ret, 2)
            else:
                result[sym][year_key] = None  # type: ignore[assignment]

        # Rank descending (rank 1 = best return)
        year_data.sort(key=lambda x: x[1], reverse=True)
        rank_map = {sym: idx + 1 for idx, (sym, _) in enumerate(year_data)}

        for sym in symbols:
            result[sym][f"rank_{year_key}"] = rank_map.get(sym, len(symbols))  # type: ignore[assignment]

    return result


# ---------------------------------------------------------------------------
# 52-week high / low
# ---------------------------------------------------------------------------


def get_52w_high_low(prices: list[float]) -> tuple[float, float]:
    """Return the 52-week (last 252 trading days) high and low from a price series.

    If ``prices`` contains fewer than 252 entries the entire series is used.

    Args:
        prices: Chronologically ordered closing prices (oldest first).

    Returns:
        Tuple of ``(high, low)`` over the look-back window.

    Raises:
        ValueError: If ``prices`` is empty.

    Examples:
        >>> get_52w_high_low([100.0, 105.0, 98.0, 110.0])
        (110.0, 98.0)
    """
    if not prices:
        raise ValueError("prices list must not be empty")

    window = prices[-252:] if len(prices) >= 252 else prices
    return (max(window), min(window))


# ---------------------------------------------------------------------------
# Sparkline
# ---------------------------------------------------------------------------


def get_sparkline(prices: list[float], n: int = 30) -> list[float]:
    """Return the last *n* normalised prices for a mini sparkline chart.

    Normalisation: each value is divided by the first value in the window
    so the sparkline starts at 1.0 (i.e. 100 % base).

    Args:
        prices: Chronologically ordered closing prices (oldest first).
        n: Number of data points to return (default 30).

    Returns:
        List of normalised price floats, length ``min(n, len(prices))``.
        Returns an empty list if ``prices`` is empty.

    Examples:
        >>> get_sparkline([100.0, 102.0, 98.0, 105.0], n=4)
        [1.0, 1.02, 0.98, 1.05]
    """
    if not prices:
        return []

    window = prices[-n:] if len(prices) >= n else prices
    base = window[0]
    if base == 0.0:
        return [0.0] * len(window)

    return [round(p / base, 6) for p in window]


# ---------------------------------------------------------------------------
# ETF screener
# ---------------------------------------------------------------------------


@dataclass
class ETFScreenResult:
    """A single ETF result from the screener.

    Attributes:
        record: The underlying catalogue entry.
        momentum_score: Calculated composite momentum.
        return_1m: 1-month return percent (or ``None`` if unavailable).
        return_3m: 3-month return percent (or ``None`` if unavailable).
        return_6m: 6-month return percent (or ``None`` if unavailable).
        return_12m: 12-month return percent (or ``None`` if unavailable).
        high_52w: 52-week high price (or ``None`` if unavailable).
        low_52w: 52-week low price (or ``None`` if unavailable).
        sparkline: Normalised price series for mini chart.
    """

    record: ETFRecord
    momentum_score: float = 0.0
    return_1m: float | None = None
    return_3m: float | None = None
    return_6m: float | None = None
    return_12m: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    sparkline: list[float] = field(default_factory=list)


def screen_etfs(
    etfs: list[ETFRecord],
    sort_by: SortBy = "momentum",
    min_aum: AUMBucket | None = None,
    category: ETFCategory | None = None,
    returns: dict[str, dict[str, float]] | None = None,
    prices: dict[str, list[float]] | None = None,
) -> list[ETFScreenResult]:
    """Filter and sort ETFs from the catalogue.

    Builds :class:`ETFScreenResult` objects by attaching supplied return /
    price data to each :class:`ETFRecord`.  Rows with missing data for the
    requested ``sort_by`` field are placed at the end.

    Args:
        etfs: List of :class:`ETFRecord` objects (e.g. from
            ``list(ETF_CATALOGUE.values())``).
        sort_by: Column to sort results by.  One of ``"momentum"``,
            ``"return_1m"``, ``"return_3m"``, ``"return_6m"``,
            ``"return_12m"``, or ``"aum"``.
        min_aum: Minimum AUM bucket filter.  ``None`` means no filter.
            E.g. ``"medium"`` keeps medium, large, and mega only.
        category: Filter by category (e.g. ``"Gold"``).  ``None`` = all.
        returns: Mapping ``{symbol: {"1m": ..., "3m": ..., "6m": ..., "12m": ...}}``
            with return percentages for each ETF.
        prices: Mapping ``{symbol: [price, ...]}`` for sparkline / 52w calculations.

    Returns:
        Sorted list of :class:`ETFScreenResult`, most favourable first.

    Examples:
        >>> results = screen_etfs(list(ETF_CATALOGUE.values()), sort_by="aum")
        >>> results[0].record.aum_bucket
        'mega'
    """
    _returns = returns or {}
    _prices = prices or {}

    results: list[ETFScreenResult] = []

    for rec in etfs:
        # AUM filter
        if min_aum is not None:
            if _AUM_ORDER.get(rec.aum_bucket, 0) < _AUM_ORDER[min_aum]:
                continue

        # Category filter
        if category is not None and rec.category != category:
            continue

        sym_returns = _returns.get(rec.symbol, {})
        r1m = sym_returns.get("1m")
        r3m = sym_returns.get("3m")
        r6m = sym_returns.get("6m")
        r12m = sym_returns.get("12m")

        mom = calculate_momentum_score(
            returns_1m=r1m or 0.0,
            returns_3m=r3m or 0.0,
            returns_6m=r6m or 0.0,
            returns_12m=r12m or 0.0,
        )

        sym_prices = _prices.get(rec.symbol, [])
        high_52w: float | None = None
        low_52w: float | None = None
        sparkline: list[float] = []

        if sym_prices:
            high_52w, low_52w = get_52w_high_low(sym_prices)
            sparkline = get_sparkline(sym_prices)

        results.append(
            ETFScreenResult(
                record=rec,
                momentum_score=mom,
                return_1m=r1m,
                return_3m=r3m,
                return_6m=r6m,
                return_12m=r12m,
                high_52w=high_52w,
                low_52w=low_52w,
                sparkline=sparkline,
            )
        )

    # Sort
    _none_sentinel = float("-inf")

    if sort_by == "aum":
        results.sort(key=lambda r: _AUM_ORDER.get(r.record.aum_bucket, 0), reverse=True)
    elif sort_by == "return_1m":
        results.sort(key=lambda r: r.return_1m if r.return_1m is not None else _none_sentinel, reverse=True)
    elif sort_by == "return_3m":
        results.sort(key=lambda r: r.return_3m if r.return_3m is not None else _none_sentinel, reverse=True)
    elif sort_by == "return_6m":
        results.sort(key=lambda r: r.return_6m if r.return_6m is not None else _none_sentinel, reverse=True)
    elif sort_by == "return_12m":
        results.sort(key=lambda r: r.return_12m if r.return_12m is not None else _none_sentinel, reverse=True)
    else:  # default: momentum
        results.sort(key=lambda r: r.momentum_score, reverse=True)

    logger.debug(
        "screen_etfs: %d input, %d passed filters, sort_by=%s",
        len(etfs),
        len(results),
        sort_by,
    )
    return results
