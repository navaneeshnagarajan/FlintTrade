"""Data connectors for backtesting — DuckDB, CSV, JSON, yfinance.

All sources normalize to a common bar format:
  [{"timestamp": "...", "open": ..., "high": ..., "low": ..., "close": ..., "volume": ..., "oi": ...}]
"""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

logger = logging.getLogger("flinttrade.backtest.data_connector")


# Standard column order
_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "oi"]


@dataclass
class DataGap:
    """A detected gap in the data."""

    start: str
    end: str
    missing_bars: int


@dataclass
class DataResult:
    """Result from a data connector query."""

    bars: list[dict[str, Any]] = field(default_factory=list)
    symbol: str = ""
    exchange: str = ""
    interval: str = ""
    source: str = ""
    gaps: list[DataGap] = field(default_factory=list)
    error: str = ""

    @property
    def total_bars(self) -> int:
        return len(self.bars)

    @property
    def success(self) -> bool:
        return self.total_bars > 0 and not self.error


def normalize_bar(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw bar dict to the standard format."""
    return {
        "timestamp": str(raw.get("timestamp", raw.get("datetime", raw.get("date", "")))),
        "open": float(raw.get("open", raw.get("Open", 0))),
        "high": float(raw.get("high", raw.get("High", 0))),
        "low": float(raw.get("low", raw.get("Low", 0))),
        "close": float(raw.get("close", raw.get("Close", 0))),
        "volume": int(raw.get("volume", raw.get("Volume", 0)) or 0),
        "oi": int(raw.get("oi", raw.get("OI", raw.get("open_interest", 0))) or 0),
    }


def validate_bars(bars: list[dict[str, Any]]) -> list[str]:
    """Validate bar data integrity. Returns list of issues."""
    issues: list[str] = []
    if not bars:
        issues.append("No bars")
        return issues

    prev_ts = ""
    for i, bar in enumerate(bars):
        ts = str(bar.get("timestamp", ""))
        if not ts:
            issues.append(f"Bar {i}: missing timestamp")
        if ts and ts <= prev_ts:
            issues.append(f"Bar {i}: timestamp {ts} not ascending (prev={prev_ts})")
        prev_ts = ts

        for field_name in ("open", "high", "low", "close"):
            val = bar.get(field_name, 0)
            if val is None or float(val) <= 0:
                issues.append(f"Bar {i}: {field_name}={val} invalid")

        h, l = float(bar.get("high", 0)), float(bar.get("low", 0))
        if h < l:
            issues.append(f"Bar {i}: high ({h}) < low ({l})")

    return issues


def detect_gaps(
    bars: list[dict[str, Any]],
    expected_interval_minutes: int = 5,
) -> list[DataGap]:
    """Detect gaps in bar data based on expected interval."""
    if len(bars) < 2 or expected_interval_minutes <= 0:
        return []

    gaps: list[DataGap] = []
    for i in range(1, len(bars)):
        ts_prev = bars[i - 1].get("timestamp", "")
        ts_curr = bars[i].get("timestamp", "")
        try:
            fmt = "%Y-%m-%d %H:%M:%S" if " " in str(ts_prev) else "%Y-%m-%d"
            dt_prev = datetime.strptime(str(ts_prev)[:19], fmt)
            dt_curr = datetime.strptime(str(ts_curr)[:19], fmt)
            diff_minutes = (dt_curr - dt_prev).total_seconds() / 60
            expected = expected_interval_minutes * 2  # Allow 1 extra bar of tolerance
            if diff_minutes > expected:
                missing = int(diff_minutes / expected_interval_minutes) - 1
                gaps.append(DataGap(start=str(ts_prev), end=str(ts_curr), missing_bars=missing))
        except (ValueError, TypeError):
            continue

    return gaps


# ---------------------------------------------------------------------------
# DuckDB Connector (primary — via historical pipeline)
# ---------------------------------------------------------------------------


class DuckDBConnector:
    """Read historical data from DuckDB via the historical pipeline.

    Usage::

        conn = DuckDBConnector(db_path=":memory:")
        result = conn.load("RELIANCE", "NSE", "5m", "2025-01-01", "2025-12-31")
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path

    def load(
        self,
        symbol: str,
        exchange: str,
        interval: str,
        start_date: str = "",
        end_date: str = "",
    ) -> DataResult:
        """Load bars from DuckDB historical tables."""
        from packages.historical.src.pipeline import INTERVAL_TABLES, DataPipeline

        table = INTERVAL_TABLES.get(interval)
        if not table:
            return DataResult(
                symbol=symbol, exchange=exchange, interval=interval,
                source="duckdb", error=f"Unknown interval: {interval}",
            )

        try:
            pipeline = DataPipeline(self._db_path) if self._db_path else DataPipeline()
            raw_bars = pipeline.get_bars(table, symbol, exchange, start_date, end_date)
            pipeline.close()

            bars = [normalize_bar(b) for b in raw_bars]
            return DataResult(
                bars=bars, symbol=symbol, exchange=exchange,
                interval=interval, source="duckdb",
            )
        except Exception as exc:
            return DataResult(
                symbol=symbol, exchange=exchange, interval=interval,
                source="duckdb", error=str(exc),
            )


# ---------------------------------------------------------------------------
# CSV Connector
# ---------------------------------------------------------------------------


class CSVConnector:
    """Load OHLCV from CSV file or string.

    Expected columns: timestamp (or date/datetime), open, high, low, close, volume, oi (optional).
    """

    @staticmethod
    def load_file(path: str) -> DataResult:
        """Load bars from a CSV file."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return CSVConnector.load_string(f.read())
        except Exception as exc:
            return DataResult(source="csv", error=str(exc))

    @staticmethod
    def load_string(csv_str: str) -> DataResult:
        """Load bars from a CSV string."""
        try:
            reader = csv.DictReader(io.StringIO(csv_str))
            bars = [normalize_bar(row) for row in reader]
            return DataResult(bars=bars, source="csv")
        except Exception as exc:
            return DataResult(source="csv", error=str(exc))


# ---------------------------------------------------------------------------
# JSON Connector
# ---------------------------------------------------------------------------


class JSONConnector:
    """Load OHLCV from JSON file or string.

    Expected: list of objects with standard OHLCV fields.
    """

    @staticmethod
    def load_file(path: str) -> DataResult:
        """Load bars from a JSON file."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                return DataResult(source="json", error="JSON must be an array of bar objects")
            bars = [normalize_bar(item) for item in data]
            return DataResult(bars=bars, source="json")
        except Exception as exc:
            return DataResult(source="json", error=str(exc))

    @staticmethod
    def load_string(json_str: str) -> DataResult:
        """Load bars from a JSON string."""
        try:
            data = json.loads(json_str)
            if not isinstance(data, list):
                return DataResult(source="json", error="JSON must be an array")
            bars = [normalize_bar(item) for item in data]
            return DataResult(bars=bars, source="json")
        except Exception as exc:
            return DataResult(source="json", error=str(exc))


# ---------------------------------------------------------------------------
# yfinance Connector
# ---------------------------------------------------------------------------


class YFinanceConnector:
    """Load data from yfinance (US stocks, crypto, global markets).

    Usage::

        yf_conn = YFinanceConnector()
        result = yf_conn.load("AAPL", interval="1d", start_date="2025-01-01", end_date="2025-12-31")
    """

    @staticmethod
    def load(
        symbol: str,
        interval: str = "1d",
        start_date: str = "",
        end_date: str = "",
    ) -> DataResult:
        """Download data via yfinance."""
        try:
            import yfinance as yf
        except ImportError:
            return DataResult(
                symbol=symbol, interval=interval, source="yfinance",
                error="yfinance not installed — pip install yfinance",
            )

        try:
            data = yf.download(
                symbol, start=start_date or None, end=end_date or None,
                interval=interval, progress=False,
            )
            if data is None or data.empty:
                return DataResult(
                    symbol=symbol, interval=interval, source="yfinance",
                    error=f"No data for {symbol}",
                )

            bars: list[dict[str, Any]] = []
            for idx, row in data.iterrows():
                bars.append(normalize_bar({
                    "timestamp": str(idx),
                    "open": row["Open"],
                    "high": row["High"],
                    "low": row["Low"],
                    "close": row["Close"],
                    "volume": row["Volume"] if row["Volume"] == row["Volume"] else 0,
                }))

            return DataResult(
                bars=bars, symbol=symbol, interval=interval, source="yfinance",
            )
        except Exception as exc:
            return DataResult(
                symbol=symbol, interval=interval, source="yfinance",
                error=str(exc),
            )


# ---------------------------------------------------------------------------
# Unified DataConnector
# ---------------------------------------------------------------------------


class DataConnector:
    """Unified data connector that tries sources in priority order.

    Usage::

        dc = DataConnector()
        result = dc.load("RELIANCE", "NSE", "5m", "2025-01-01", "2025-12-31")
    """

    def __init__(self, duckdb_path: str | None = None) -> None:
        self._duckdb = DuckDBConnector(duckdb_path)
        self._csv = CSVConnector()
        self._json = JSONConnector()
        self._yfinance = YFinanceConnector()

    def load(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "5m",
        start_date: str = "",
        end_date: str = "",
        source: str = "auto",
    ) -> DataResult:
        """Load data from the specified or best available source."""
        if source == "duckdb" or source == "auto":
            result = self._duckdb.load(symbol, exchange, interval, start_date, end_date)
            if result.success:
                return result
            if source == "duckdb":
                return result

        if source == "yfinance" or source == "auto":
            result = self._yfinance.load(symbol, interval, start_date, end_date)
            if result.success:
                return result
            if source == "yfinance":
                return result

        return DataResult(
            symbol=symbol, exchange=exchange, interval=interval,
            error=f"No data found from source={source}",
        )

    def load_csv(self, path: str) -> DataResult:
        """Load from CSV file."""
        return self._csv.load_file(path)

    def load_json(self, path: str) -> DataResult:
        """Load from JSON file."""
        return self._json.load_file(path)
