"""DuckDB storage pipeline for historical OHLCV data.

Absorbs Historify patterns: per-interval tables, merge without duplicates,
client-side aggregation (1m → 5m → 15m → 1h → 1d), Parquet export.

Schema per table: timestamp (TIMESTAMP), open, high, low, close (DOUBLE),
volume (BIGINT), oi (BIGINT), symbol (VARCHAR), exchange (VARCHAR).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from packages.core.src.models import OHLCV

from .downloader import DownloadResult
from .free_data import FreeBar, FreeDataResult

logger = logging.getLogger("flinttrade.historical.pipeline")

_DEFAULT_DB_PATH = os.getenv("DUCKDB_PATH", "/data/flinttrade/flint.duckdb")

# Interval table names
INTERVAL_TABLES: dict[str, str] = {
    "1m": "ohlcv_1m",
    "5m": "ohlcv_5m",
    "15m": "ohlcv_15m",
    "1h": "ohlcv_1h",
    "D": "ohlcv_1d",
    "1d": "ohlcv_1d",
}

# Aggregation relationships: source → target with bar count
_AGGREGATION_MAP: list[tuple[str, str, int]] = [
    ("ohlcv_1m", "ohlcv_5m", 5),
    ("ohlcv_5m", "ohlcv_15m", 3),
    ("ohlcv_15m", "ohlcv_1h", 4),
    ("ohlcv_1h", "ohlcv_1d", -1),  # -1 = group by date
]

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS {table} (
    timestamp   TIMESTAMP NOT NULL,
    symbol      VARCHAR NOT NULL,
    exchange    VARCHAR NOT NULL,
    open        DOUBLE NOT NULL,
    high        DOUBLE NOT NULL,
    low         DOUBLE NOT NULL,
    close       DOUBLE NOT NULL,
    volume      BIGINT DEFAULT 0,
    oi          BIGINT DEFAULT 0
);
"""


def aggregate_bars(bars: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    """Aggregate OHLCV bars by grouping every n bars.

    For n == -1, group by calendar date (used for hourly → daily).
    Returns new bars with proper OHLCV aggregation:
      open = first bar's open, high = max(highs), low = min(lows),
      close = last bar's close, volume = sum(volumes), oi = last bar's oi.
    """
    if not bars:
        return []

    if n == -1:
        # Group by date
        groups: dict[str, list[dict[str, Any]]] = {}
        for bar in bars:
            ts = bar["timestamp"]
            day = str(ts)[:10] if isinstance(ts, str) else ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]
            groups.setdefault(day, []).append(bar)

        result = []
        for day_bars in groups.values():
            result.append(_merge_group(day_bars))
        return sorted(result, key=lambda b: str(b["timestamp"]))

    # Group every n bars
    result = []
    for i in range(0, len(bars), n):
        group = bars[i : i + n]
        if group:
            result.append(_merge_group(group))
    return result


def _merge_group(group: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge a group of bars into a single OHLCV bar."""
    return {
        "timestamp": group[0]["timestamp"],
        "symbol": group[0].get("symbol", ""),
        "exchange": group[0].get("exchange", ""),
        "open": group[0]["open"],
        "high": max(b["high"] for b in group),
        "low": min(b["low"] for b in group),
        "close": group[-1]["close"],
        "volume": sum(b.get("volume", 0) or 0 for b in group),
        "oi": group[-1].get("oi", 0) or 0,
    }


class DataPipeline:
    """DuckDB pipeline for storing, merging, aggregating, and exporting OHLCV data.

    Usage::

        pipeline = DataPipeline()
        pipeline.initialize()
        pipeline.store_download(download_result, "5m")
        pipeline.aggregate("RELIANCE", "NSE", "ohlcv_1m", "ohlcv_5m", 5)
        pipeline.export_parquet("ohlcv_1d", "/data/archive/daily.parquet")
        pipeline.close()
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: duckdb.DuckDBPyConnection | None = None

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self._conn = duckdb.connect(self._db_path)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> DataPipeline:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Create all OHLCV interval tables."""
        for table in set(INTERVAL_TABLES.values()):
            self.connection.execute(_TABLE_DDL.format(table=table))
        logger.info("Historical pipeline schema initialized")

    # ------------------------------------------------------------------
    # Store data
    # ------------------------------------------------------------------

    def store_download(self, result: DownloadResult, interval: str) -> int:
        """Store a DownloadResult into the appropriate interval table.

        Merges without duplicates using (timestamp, symbol, exchange) uniqueness.
        Returns number of new rows inserted.
        """
        table = INTERVAL_TABLES.get(interval)
        if not table:
            raise ValueError(f"Unknown interval: {interval}. Known: {list(INTERVAL_TABLES)}")

        return self._merge_bars(
            table=table,
            symbol=result.symbol,
            exchange=result.exchange,
            bars=[
                {
                    "timestamp": b.timestamp,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                    "oi": 0,
                }
                for b in result.bars
            ],
        )

    def store_free_data(self, result: FreeDataResult, interval: str) -> int:
        """Store a FreeDataResult into the appropriate interval table."""
        table = INTERVAL_TABLES.get(interval)
        if not table:
            raise ValueError(f"Unknown interval: {interval}")

        return self._merge_bars(
            table=table,
            symbol=result.symbol,
            exchange=result.exchange,
            bars=[
                {
                    "timestamp": b.timestamp,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                    "oi": b.oi,
                }
                for b in result.bars
            ],
        )

    def store_bars(
        self,
        table: str,
        symbol: str,
        exchange: str,
        bars: list[dict[str, Any]],
    ) -> int:
        """Store raw bar dicts into a table with dedup."""
        return self._merge_bars(table, symbol, exchange, bars)

    def _merge_bars(
        self,
        table: str,
        symbol: str,
        exchange: str,
        bars: list[dict[str, Any]],
    ) -> int:
        """Insert bars, skipping duplicates by (timestamp, symbol, exchange).

        Returns number of new rows inserted.
        """
        if not bars:
            return 0

        inserted = 0
        for bar in bars:
            ts = bar["timestamp"]
            # Check if row already exists
            existing = self.connection.execute(
                f"SELECT 1 FROM {table} WHERE timestamp = ? AND symbol = ? AND exchange = ? LIMIT 1",
                [ts, symbol, exchange],
            ).fetchone()

            if existing is None:
                self.connection.execute(
                    f"""INSERT INTO {table}
                        (timestamp, symbol, exchange, open, high, low, close, volume, oi)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        ts, symbol, exchange,
                        bar["open"], bar["high"], bar["low"], bar["close"],
                        bar.get("volume", 0) or 0,
                        bar.get("oi", 0) or 0,
                    ],
                )
                inserted += 1

        logger.info(
            "Merged %d/%d bars into %s for %s:%s",
            inserted, len(bars), table, exchange, symbol,
        )
        return inserted

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_bars(
        self,
        table: str,
        symbol: str,
        exchange: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query OHLCV bars from a table."""
        query = f"SELECT * FROM {table} WHERE symbol = ? AND exchange = ?"
        params: list[Any] = [symbol, exchange]

        if start_date:
            query += " AND timestamp >= ?"
            params.append(start_date)
        if end_date:
            query += " AND timestamp <= ?::DATE + INTERVAL '1 day'"
            params.append(end_date)

        query += " ORDER BY timestamp"

        result = self.connection.execute(query, params)
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    def count_bars(self, table: str, symbol: str, exchange: str) -> int:
        """Count bars in a table for a symbol."""
        result = self.connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE symbol = ? AND exchange = ?",
            [symbol, exchange],
        )
        row = result.fetchone()
        return row[0] if row else 0

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def aggregate(
        self,
        symbol: str,
        exchange: str,
        source_table: str,
        target_table: str,
        n: int,
    ) -> int:
        """Aggregate bars from source to target table.

        Args:
            n: number of source bars per target bar, or -1 for daily grouping.

        Returns number of new bars inserted.
        """
        source_bars = self.get_bars(source_table, symbol, exchange)
        if not source_bars:
            return 0

        aggregated = aggregate_bars(source_bars, n)
        return self._merge_bars(target_table, symbol, exchange, aggregated)

    def aggregate_all(self, symbol: str, exchange: str) -> dict[str, int]:
        """Run the full aggregation chain: 1m → 5m → 15m → 1h → 1d.

        Returns dict of table → new rows inserted.
        """
        results: dict[str, int] = {}
        for source, target, n in _AGGREGATION_MAP:
            count = self.aggregate(symbol, exchange, source, target, n)
            results[target] = count
            if count > 0:
                logger.info(
                    "Aggregated %s → %s for %s:%s: %d new bars",
                    source, target, exchange, symbol, count,
                )
        return results

    # ------------------------------------------------------------------
    # Parquet export
    # ------------------------------------------------------------------

    def export_parquet(
        self,
        table: str,
        output_path: str,
        symbol: str | None = None,
        exchange: str | None = None,
    ) -> str:
        """Export a table (or subset) to a Parquet file.

        Returns the output path.
        """
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        query = f"SELECT * FROM {table}"
        conditions: list[str] = []
        params: list[Any] = []

        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        if exchange:
            conditions.append("exchange = ?")
            params.append(exchange)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY timestamp"

        self.connection.execute(
            f"COPY ({query}) TO '{output_path}' (FORMAT PARQUET)",
            params if params else None,
        )
        logger.info("Exported %s to %s", table, output_path)
        return output_path

    def import_parquet(self, table: str, parquet_path: str) -> int:
        """Import a Parquet file into a table. Returns rows imported."""
        before = self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        self.connection.execute(
            f"INSERT INTO {table} SELECT * FROM read_parquet('{parquet_path}')"
        )
        after = self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        imported = after - before
        logger.info("Imported %d rows from %s into %s", imported, parquet_path, table)
        return imported
