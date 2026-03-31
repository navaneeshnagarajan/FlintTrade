"""Collect historical data for expired F&O contracts.

Absorbs ExpiryTrack patterns. Downloads OHLCV data before each expiry date for
NIFTY, BANKNIFTY weekly/monthly options and stock F&O. Stores as CSV/JSON in
~/.flinttrade/expiry_data/ for backtesting expired strategies.

Uses existing ExpiryManager for expiry date lookup and HistoricalDownloader for
OHLCV retrieval.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from packages.core.src.openalgo_client import OpenAlgoClient

from .downloader import HistoricalDownloader
from .expiry_manager import ExpiryManager, _parse_expiry_date

logger = logging.getLogger("flinttrade.historical.expiry_collector")

# Default OHLCV columns for CSV export
_CSV_HEADER = "timestamp,open,high,low,close,volume"

# Default symbols to collect expiry data for
DEFAULT_SYMBOLS: list[str] = ["NIFTY", "BANKNIFTY"]

# Default exchanges for F&O segments
DEFAULT_EXCHANGE = "NFO"


@dataclass
class ExpiryDataRecord:
    """A single OHLCV bar associated with an expired contract."""

    timestamp: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0
    symbol: str = ""
    expiry: str = ""


@dataclass
class ExpiryDataResult:
    """Result from collecting data for a single expiry."""

    symbol: str = ""
    expiry: str = ""
    exchange: str = ""
    records: list[ExpiryDataRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def total_bars(self) -> int:
        return len(self.records)

    @property
    def success(self) -> bool:
        return self.total_bars > 0


class ExpiryDataCollector:
    """Collect historical data for expired F&O contracts.

    Downloads OHLCV data before each expiry date for:
    - NIFTY weekly/monthly options
    - BANKNIFTY weekly/monthly options
    - Stock F&O

    Usage::

        collector = ExpiryDataCollector(client)
        expiries = collector.get_past_expiries("NIFTY", months=6)
        result = collector.download_expiry_data("NIFTY", expiries[0], days_before=90)
        path = collector.export_csv("NIFTY", expiries[0])
    """

    def __init__(
        self,
        client: OpenAlgoClient,
        data_dir: str = "~/.flinttrade/expiry_data",
    ) -> None:
        self.data_dir = Path(data_dir).expanduser()
        self._client = client
        self._expiry_mgr = ExpiryManager(client)
        self._downloader = HistoricalDownloader(client)
        self._cache: dict[str, ExpiryDataResult] = {}

    def _ensure_data_dir(self) -> None:
        """Create the data directory if it doesn't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def get_past_expiries(
        self,
        symbol: str,
        months: int = 12,
        exchange: str = DEFAULT_EXCHANGE,
    ) -> list[str]:
        """Get expiry dates that have already passed.

        Args:
            symbol: Underlying symbol (e.g. "NIFTY", "BANKNIFTY").
            months: How far back to look for expired contracts.
            exchange: Exchange segment (default NFO).

        Returns:
            List of expiry date strings (YYMMDD format) sorted chronologically.
        """
        info = self._expiry_mgr.get_expiries(symbol, exchange)
        if not info.expiry_dates:
            logger.warning("No expiry dates found for %s:%s", exchange, symbol)
            return []

        cutoff = date.today()
        lookback = cutoff - timedelta(days=months * 30)

        past: list[str] = []
        for exp_str in sorted(info.expiry_dates):
            try:
                exp_date = _parse_expiry_date(exp_str)
                if lookback <= exp_date < cutoff:
                    past.append(exp_str)
            except ValueError:
                continue

        logger.info(
            "Found %d past expiries for %s:%s within %d months",
            len(past), exchange, symbol, months,
        )
        return past

    def download_expiry_data(
        self,
        symbol: str,
        expiry: str,
        days_before: int = 90,
        interval: str = "D",
        exchange: str = DEFAULT_EXCHANGE,
    ) -> ExpiryDataResult:
        """Download OHLCV data leading up to an expiry date.

        Args:
            symbol: Underlying symbol.
            expiry: Expiry date string (YYMMDD or ISO format).
            days_before: Number of trading days of data to collect before expiry.
            interval: OHLCV interval (default "D" for daily).
            exchange: Exchange segment.

        Returns:
            ExpiryDataResult with bars and any errors.
        """
        cache_key = f"{exchange}:{symbol}:{expiry}:{interval}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        result = ExpiryDataResult(symbol=symbol, expiry=expiry, exchange=exchange)

        try:
            exp_date = _parse_expiry_date(expiry)
        except ValueError as exc:
            result.errors.append(f"Invalid expiry format: {expiry} — {exc}")
            return result

        start_date = exp_date - timedelta(days=days_before)
        end_date = exp_date

        try:
            download = self._downloader.download(
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
            )

            for bar in download.bars:
                result.records.append(ExpiryDataRecord(
                    timestamp=bar.timestamp,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    symbol=symbol,
                    expiry=expiry,
                ))

            if download.errors:
                result.errors.extend(download.errors)

            logger.info(
                "Downloaded %d bars for %s expiry %s (%d days before)",
                result.total_bars, symbol, expiry, days_before,
            )
        except Exception as exc:
            result.errors.append(str(exc))
            logger.error("Failed to download %s expiry %s: %s", symbol, expiry, exc)

        self._cache[cache_key] = result
        return result

    def export_csv(
        self,
        symbol: str,
        expiry: str,
        exchange: str = DEFAULT_EXCHANGE,
        interval: str = "D",
    ) -> Path:
        """Export collected expiry data to CSV.

        Downloads data if not already cached. File is written to
        ``{data_dir}/{symbol}/{expiry}.csv``.

        Returns:
            Path to the written CSV file.
        """
        result = self.download_expiry_data(symbol, expiry, exchange=exchange, interval=interval)
        self._ensure_data_dir()

        symbol_dir = self.data_dir / symbol.upper()
        symbol_dir.mkdir(parents=True, exist_ok=True)

        csv_path = symbol_dir / f"{expiry}.csv"
        lines = [_CSV_HEADER]
        for r in result.records:
            lines.append(
                f"{r.timestamp},{r.open},{r.high},{r.low},{r.close},{r.volume}",
            )
        csv_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Exported CSV: %s (%d records)", csv_path, result.total_bars)
        return csv_path

    def export_json(
        self,
        symbol: str,
        expiry: str,
        exchange: str = DEFAULT_EXCHANGE,
        interval: str = "D",
    ) -> Path:
        """Export collected expiry data to JSON.

        Downloads data if not already cached. File is written to
        ``{data_dir}/{symbol}/{expiry}.json``.

        Returns:
            Path to the written JSON file.
        """
        result = self.download_expiry_data(symbol, expiry, exchange=exchange, interval=interval)
        self._ensure_data_dir()

        symbol_dir = self.data_dir / symbol.upper()
        symbol_dir.mkdir(parents=True, exist_ok=True)

        json_path = symbol_dir / f"{expiry}.json"
        payload: dict[str, Any] = {
            "symbol": result.symbol,
            "expiry": result.expiry,
            "exchange": result.exchange,
            "total_bars": result.total_bars,
            "records": [
                {
                    "timestamp": r.timestamp,
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "volume": r.volume,
                }
                for r in result.records
            ],
        }
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("Exported JSON: %s (%d records)", json_path, result.total_bars)
        return json_path

    def collect_all(
        self,
        symbols: list[str] | None = None,
        months: int = 12,
        days_before: int = 90,
        exchange: str = DEFAULT_EXCHANGE,
    ) -> dict[str, list[ExpiryDataResult]]:
        """Collect expiry data for multiple symbols.

        Convenience method that fetches past expiries and downloads data for each.

        Args:
            symbols: List of underlying symbols (defaults to NIFTY, BANKNIFTY).
            months: How far back to look.
            days_before: Days of data to collect before each expiry.
            exchange: Exchange segment.

        Returns:
            Dict mapping symbol → list of ExpiryDataResult.
        """
        targets = symbols or DEFAULT_SYMBOLS
        results: dict[str, list[ExpiryDataResult]] = {}

        for sym in targets:
            expiries = self.get_past_expiries(sym, months=months, exchange=exchange)
            sym_results: list[ExpiryDataResult] = []
            for exp in expiries:
                r = self.download_expiry_data(
                    sym, exp, days_before=days_before, exchange=exchange,
                )
                sym_results.append(r)
            results[sym] = sym_results
            logger.info(
                "Collected %d expiries for %s (%d total bars)",
                len(sym_results), sym, sum(r.total_bars for r in sym_results),
            )

        return results
