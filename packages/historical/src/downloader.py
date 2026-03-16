"""Historical OHLCV downloader via OpenAlgo /api/v1/history endpoint.

Supports all exchanges (NSE, BSE, NFO, BFO, CDS, BCD, MCX, NCDEX) and all
intervals (1m, 2m, 3m, 5m, 10m, 15m, 30m, 1h, D).

Brokers typically limit intraday history to ~30 days per request, so this
module automatically chunks large date ranges and stitches the results.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from packages.core.src.models import OHLCV
from packages.core.src.openalgo_client import OpenAlgoClient

logger = logging.getLogger("flinttrade.historical.downloader")

# Max days per request for intraday intervals (broker limitation)
_INTRADAY_INTERVALS = {"1m", "2m", "3m", "5m", "10m", "15m", "30m", "1h"}
_DAILY_INTERVALS = {"D", "1d", "1W", "1M"}

# Most brokers allow ~30 days of intraday data per API call
_DEFAULT_CHUNK_DAYS_INTRADAY = 30
_DEFAULT_CHUNK_DAYS_DAILY = 365

# All tradeable exchanges
SUPPORTED_EXCHANGES = {"NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "NCDEX"}

# Canonical interval mapping — normalize user-friendly names to OpenAlgo format
_INTERVAL_MAP: dict[str, str] = {
    "1m": "1m", "2m": "2m", "3m": "3m", "5m": "5m", "10m": "10m",
    "15m": "15m", "30m": "30m", "1h": "1h",
    "1d": "D", "D": "D", "1W": "1W", "1M": "1M",
}


@dataclass
class DownloadResult:
    """Result of a download operation."""

    symbol: str
    exchange: str
    interval: str
    start_date: str
    end_date: str
    bars: list[OHLCV] = field(default_factory=list)
    chunks_fetched: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total_bars(self) -> int:
        return len(self.bars)

    @property
    def success(self) -> bool:
        return self.total_bars > 0


def compute_date_chunks(
    start: date,
    end: date,
    chunk_days: int,
) -> list[tuple[date, date]]:
    """Split a date range into chunks of at most chunk_days.

    Returns list of (chunk_start, chunk_end) tuples.
    """
    chunks: list[tuple[date, date]] = []
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=chunk_days - 1), end)
        chunks.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)
    return chunks


class HistoricalDownloader:
    """Downloads historical OHLCV data via OpenAlgo with automatic date chunking.

    Usage::

        dl = HistoricalDownloader(client)
        result = dl.download("RELIANCE", "NSE", "5m", "2025-01-01", "2025-12-31")
        print(f"Downloaded {result.total_bars} bars in {result.chunks_fetched} chunks")
    """

    def __init__(
        self,
        client: OpenAlgoClient,
        chunk_days_intraday: int = _DEFAULT_CHUNK_DAYS_INTRADAY,
        chunk_days_daily: int = _DEFAULT_CHUNK_DAYS_DAILY,
    ) -> None:
        self._client = client
        self._chunk_days_intraday = chunk_days_intraday
        self._chunk_days_daily = chunk_days_daily

    def download(
        self,
        symbol: str,
        exchange: str,
        interval: str,
        start_date: str,
        end_date: str,
    ) -> DownloadResult:
        """Download historical data for a symbol, chunking if needed.

        Args:
            symbol: e.g. "RELIANCE", "NIFTY26MARFUT"
            exchange: e.g. "NSE", "NFO", "MCX"
            interval: e.g. "1m", "5m", "1h", "D", "1d", "1W", "1M"
            start_date: "YYYY-MM-DD"
            end_date: "YYYY-MM-DD"
        """
        canonical = _INTERVAL_MAP.get(interval, interval)
        result = DownloadResult(
            symbol=symbol, exchange=exchange, interval=canonical,
            start_date=start_date, end_date=end_date,
        )

        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)

        if start > end:
            result.errors.append(f"start_date {start_date} is after end_date {end_date}")
            return result

        # Determine chunk size
        is_intraday = canonical in _INTRADAY_INTERVALS
        chunk_days = self._chunk_days_intraday if is_intraday else self._chunk_days_daily
        chunks = compute_date_chunks(start, end, chunk_days)

        logger.info(
            "Downloading %s %s %s from %s to %s (%d chunks)",
            symbol, exchange, canonical, start_date, end_date, len(chunks),
        )

        all_bars: list[OHLCV] = []
        for i, (c_start, c_end) in enumerate(chunks, 1):
            c_start_str = c_start.isoformat()
            c_end_str = c_end.isoformat()
            logger.info(
                "  Chunk %d/%d: %s to %s", i, len(chunks), c_start_str, c_end_str,
            )

            try:
                bars = self._client.history(
                    symbol=symbol,
                    exchange=exchange,
                    interval=canonical,
                    start_date=c_start_str,
                    end_date=c_end_str,
                )
                all_bars.extend(bars)
                result.chunks_fetched += 1
                logger.info("    Got %d bars", len(bars))
            except Exception as exc:
                msg = f"Chunk {i} ({c_start_str} to {c_end_str}) failed: {exc}"
                result.errors.append(msg)
                logger.warning("    %s", msg)

        # Deduplicate by timestamp (overlapping chunks may return same bar)
        seen: set[str] = set()
        unique: list[OHLCV] = []
        for bar in all_bars:
            if bar.timestamp not in seen:
                seen.add(bar.timestamp)
                unique.append(bar)

        # Sort by timestamp
        unique.sort(key=lambda b: b.timestamp)
        result.bars = unique

        logger.info(
            "Download complete: %s %s %s — %d bars (%d errors)",
            symbol, exchange, canonical, result.total_bars, len(result.errors),
        )
        return result

    def download_batch(
        self,
        symbols: list[dict[str, str]],
        interval: str,
        start_date: str,
        end_date: str,
    ) -> list[DownloadResult]:
        """Download historical data for multiple symbols.

        Each entry: {"symbol": "RELIANCE", "exchange": "NSE"}
        """
        results: list[DownloadResult] = []
        for entry in symbols:
            sym = entry["symbol"]
            exch = entry.get("exchange", "NSE")
            result = self.download(sym, exch, interval, start_date, end_date)
            results.append(result)
        return results
