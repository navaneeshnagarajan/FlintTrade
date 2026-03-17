"""Free data sources — no broker API key required.

- OpenChart (pip install openchart): free NSE/NFO historical data
- yfinance: MCX commodity prices (GOLD, SILVER, CRUDE in INR), global indices
- jugaad-data: NSE holidays, corporate actions

These are supplementary sources. Primary data comes from OpenAlgo via broker API.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

logger = logging.getLogger("flinttrade.historical.free_data")


@dataclass
class FreeBar:
    """Generic OHLCV bar from free data sources."""

    timestamp: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0
    oi: int = 0
    source: str = ""


@dataclass
class FreeDataResult:
    """Result from a free data query."""

    symbol: str
    exchange: str
    source: str
    bars: list[FreeBar] = field(default_factory=list)
    error: str = ""

    @property
    def total_bars(self) -> int:
        return len(self.bars)

    @property
    def success(self) -> bool:
        return self.total_bars > 0 and not self.error


# ---------------------------------------------------------------------------
# NSE Data via OpenChart
# ---------------------------------------------------------------------------


class NSEData:
    """Free NSE/NFO historical data via the openchart library.

    OpenChart provides data for indices, equities, futures, and options
    without needing any broker API key.

    Usage::

        nse = NSEData()
        result = nse.historical("RELIANCE", "NSE", "2025-01-01", "2025-12-31", "1d")
        matches = nse.search("NIFTY")
    """

    def __init__(self) -> None:
        self._chart = None

    def _get_chart(self) -> Any:
        """Lazy-load openchart to avoid import errors if not installed."""
        if self._chart is None:
            try:
                from openchart import NSEData as OpenChartNSE
                self._chart = OpenChartNSE()
                logger.info("OpenChart NSEData initialized")
            except ImportError:
                logger.warning("openchart not installed — pip install openchart")
                raise ImportError(
                    "openchart is required for free NSE data. Install with: pip install openchart"
                )
        return self._chart

    def historical(
        self,
        symbol: str,
        exchange: str,
        start_date: str,
        end_date: str,
        interval: str = "1d",
    ) -> FreeDataResult:
        """Fetch free historical data for NSE/NFO symbols.

        Args:
            symbol: e.g. "RELIANCE", "NIFTY", "NIFTY26MARFUT"
            exchange: "NSE" or "NFO"
            start_date: "YYYY-MM-DD"
            end_date: "YYYY-MM-DD"
            interval: "1m", "5m", "15m", "1h", "1d"
        """
        result = FreeDataResult(symbol=symbol, exchange=exchange, source="openchart")

        try:
            chart = self._get_chart()
            df = chart.historical(
                symbol=symbol,
                exchange=exchange,
                start=start_date,
                end=end_date,
                interval=interval,
            )

            if df is None or df.empty:
                result.error = "No data returned from OpenChart"
                return result

            for _, row in df.iterrows():
                bar = FreeBar(
                    timestamp=str(row.get("datetime", row.name if hasattr(row, "name") else "")),
                    open=float(row.get("open", 0)),
                    high=float(row.get("high", 0)),
                    low=float(row.get("low", 0)),
                    close=float(row.get("close", 0)),
                    volume=int(row.get("volume", 0)),
                    oi=int(row.get("oi", 0)) if "oi" in row.index else 0,
                    source="openchart",
                )
                result.bars.append(bar)

            logger.info(
                "OpenChart: %s %s — %d bars (%s to %s)",
                symbol, exchange, result.total_bars, start_date, end_date,
            )
        except ImportError:
            result.error = "openchart not installed"
        except Exception as exc:
            result.error = str(exc)
            logger.error("OpenChart error for %s: %s", symbol, exc)

        return result

    def search(self, query: str) -> list[dict[str, str]]:
        """Search NSE symbols via OpenChart.

        Returns list of dicts: [{"symbol": "RELIANCE", "exchange": "NSE", "name": "..."}, ...]
        """
        try:
            chart = self._get_chart()
            results = chart.search(query)
            if isinstance(results, list):
                return results
            # Some versions return a DataFrame
            if hasattr(results, "to_dict"):
                return results.to_dict("records")
            return []
        except ImportError:
            return []
        except Exception as exc:
            logger.error("OpenChart search error: %s", exc)
            return []


# ---------------------------------------------------------------------------
# MCX / Global commodity data via yfinance
# ---------------------------------------------------------------------------

# Yahoo Finance tickers for Indian MCX commodities
_YFINANCE_MCX_MAP: dict[str, str] = {
    "GOLD": "GC=F",       # Gold futures (USD) — convert to INR
    "SILVER": "SI=F",     # Silver futures
    "CRUDEOIL": "CL=F",   # WTI Crude
    "NATURALGAS": "NG=F", # Natural Gas
    "COPPER": "HG=F",     # Copper
    "ZINC": "ZN=F",       # Zinc (LME)
}

# INR conversion ticker
_USDINR_TICKER = "USDINR=X"


class CommodityData:
    """Free MCX commodity price data via yfinance.

    Note: yfinance provides international prices. For INR-denominated MCX prices,
    we multiply by USDINR. This is approximate — actual MCX prices may differ
    due to import duty, logistics, and local supply/demand.

    Usage::

        mcx = CommodityData()
        result = mcx.historical("GOLD", "2025-01-01", "2025-12-31")
    """

    def historical(
        self,
        commodity: str,
        start_date: str,
        end_date: str,
        interval: str = "1d",
        convert_to_inr: bool = True,
    ) -> FreeDataResult:
        """Fetch commodity historical data.

        Args:
            commodity: "GOLD", "SILVER", "CRUDEOIL", "NATURALGAS", "COPPER", "ZINC"
            start_date: "YYYY-MM-DD"
            end_date: "YYYY-MM-DD"
            interval: yfinance interval ("1d", "1h", "5m", etc.)
            convert_to_inr: multiply by USDINR rate if True
        """
        result = FreeDataResult(
            symbol=commodity, exchange="MCX", source="yfinance",
        )

        ticker = _YFINANCE_MCX_MAP.get(commodity.upper())
        if not ticker:
            result.error = f"Unknown commodity: {commodity}. Supported: {list(_YFINANCE_MCX_MAP)}"
            return result

        try:
            import yfinance as yf
        except ImportError:
            result.error = "yfinance not installed — pip install yfinance"
            return result

        try:
            data = yf.download(
                ticker, start=start_date, end=end_date,
                interval=interval, progress=False,
            )
            if data is None or data.empty:
                result.error = f"No yfinance data for {ticker}"
                return result

            # Get USDINR rate for conversion
            inr_rate = 1.0
            if convert_to_inr:
                try:
                    fx = yf.download(
                        _USDINR_TICKER, start=start_date, end=end_date,
                        interval=interval, progress=False,
                    )
                    if fx is not None and not fx.empty:
                        # Use a simple average for the period
                        inr_rate = float(fx["Close"].mean())
                except Exception:
                    inr_rate = 83.0  # Fallback approximate rate
                    logger.warning("USDINR fetch failed, using fallback rate %.1f", inr_rate)

            for idx, row in data.iterrows():
                bar = FreeBar(
                    timestamp=str(idx),
                    open=float(row["Open"]) * inr_rate,
                    high=float(row["High"]) * inr_rate,
                    low=float(row["Low"]) * inr_rate,
                    close=float(row["Close"]) * inr_rate,
                    volume=int(row["Volume"]) if row["Volume"] == row["Volume"] else 0,
                    source="yfinance",
                )
                result.bars.append(bar)

            logger.info(
                "yfinance: %s (%s) — %d bars, INR rate=%.2f",
                commodity, ticker, result.total_bars, inr_rate,
            )
        except Exception as exc:
            result.error = str(exc)
            logger.error("yfinance error for %s: %s", commodity, exc)

        return result


# ---------------------------------------------------------------------------
# NSE Holidays via jugaad-data
# ---------------------------------------------------------------------------


class NSEHolidays:
    """NSE trading holidays via jugaad-data library.

    Usage::

        holidays = NSEHolidays()
        dates = holidays.get_holidays(2026)
        if holidays.is_holiday(date(2026, 1, 26)):
            print("Republic Day — market closed")
    """

    def __init__(self) -> None:
        self._cache: dict[int, list[date]] = {}

    def get_holidays(self, year: int) -> list[date]:
        """Get list of NSE trading holidays for a year."""
        if year in self._cache:
            return self._cache[year]

        try:
            from jugaad_data.holidays import holidays as jd_holidays
            holiday_dates = jd_holidays(year)
            if isinstance(holiday_dates, list):
                self._cache[year] = [
                    d if isinstance(d, date) else date.fromisoformat(str(d))
                    for d in holiday_dates
                ]
            else:
                self._cache[year] = []
            logger.info("Loaded %d NSE holidays for %d", len(self._cache[year]), year)
        except ImportError:
            logger.warning("jugaad-data not installed — pip install jugaad-data")
            self._cache[year] = []
        except Exception as exc:
            logger.error("Failed to load holidays for %d: %s", year, exc)
            self._cache[year] = []

        return self._cache[year]

    def is_holiday(self, d: date) -> bool:
        """Check if a date is an NSE holiday."""
        holidays = self.get_holidays(d.year)
        return d in holidays

    def is_trading_day(self, d: date) -> bool:
        """Check if a date is a trading day (weekday and not holiday)."""
        if d.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        return not self.is_holiday(d)


# ---------------------------------------------------------------------------
# Composite free data source
# ---------------------------------------------------------------------------


class FreeDataSource:
    """Unified interface to all free data sources.

    Usage::

        free = FreeDataSource()
        # NSE equity via OpenChart (no API key needed)
        result = free.nse_historical("RELIANCE", "NSE", "2025-01-01", "2025-12-31")
        # MCX commodity via yfinance
        result = free.commodity_historical("GOLD", "2025-01-01", "2025-12-31")
        # NSE holidays
        holidays = free.get_holidays(2026)
    """

    def __init__(self) -> None:
        self.nse = NSEData()
        self.commodity = CommodityData()
        self.holidays = NSEHolidays()

    def nse_historical(
        self,
        symbol: str,
        exchange: str = "NSE",
        start_date: str = "",
        end_date: str = "",
        interval: str = "1d",
    ) -> FreeDataResult:
        """Get free NSE/NFO data via OpenChart."""
        return self.nse.historical(symbol, exchange, start_date, end_date, interval)

    def commodity_historical(
        self,
        commodity: str,
        start_date: str = "",
        end_date: str = "",
        interval: str = "1d",
        convert_to_inr: bool = True,
    ) -> FreeDataResult:
        """Get free MCX commodity data via yfinance."""
        return self.commodity.historical(
            commodity, start_date, end_date, interval, convert_to_inr,
        )

    def search(self, query: str) -> list[dict[str, str]]:
        """Search NSE symbols."""
        return self.nse.search(query)

    def get_holidays(self, year: int) -> list[date]:
        """Get NSE holidays for a year."""
        return self.holidays.get_holidays(year)

    def is_trading_day(self, d: date) -> bool:
        """Check if a date is a trading day."""
        return self.holidays.is_trading_day(d)
