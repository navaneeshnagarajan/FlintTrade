"""DuckDB storage pipeline for historical OHLCV data.

Adapts Historify patterns: per-interval tables, merge without duplicates,
client-side aggregation (1m → 5m → 15m → 1h → 1d), Parquet export.

Schema per table: timestamp (TIMESTAMP), open, high, low, close (DOUBLE),
volume (BIGINT), oi (BIGINT), symbol (VARCHAR), exchange (VARCHAR).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any

import duckdb

from flinttrade_core.workspace import duckdb_path

from .downloader import DownloadResult
from .free_data import FreeDataResult

logger = logging.getLogger("flinttrade.historical.pipeline")

# Interval table names — defined before the allowlist so VALID_TABLES can reference them
INTERVAL_TABLES: dict[str, str] = {
    "1m": "ohlcv_1m",
    "5m": "ohlcv_5m",
    "15m": "ohlcv_15m",
    "1h": "ohlcv_1h",
    "D": "ohlcv_1d",
    "1d": "ohlcv_1d",
}

VALID_TABLES: frozenset[str] = frozenset(INTERVAL_TABLES.values())


def _validate_table(table: str) -> str:
    """Validate table name against allowlist to prevent SQL injection.

    Returns the exact matching string from the allowlist to ensure safe interpolation.
    """
    for valid in VALID_TABLES:
        if valid == table:
            return valid

    raise ValueError(f"Invalid table name: {table!r}. Must be one of: {sorted(VALID_TABLES)}")


def _validate_path(path: str, base_dir: str | None = None) -> Path:
    """Validate file path to prevent path traversal."""
    resolved = Path(path).resolve()
    if base_dir:
        base = Path(base_dir).resolve()
        if not resolved.is_relative_to(base):
            raise ValueError(f"Path {path!r} is outside allowed directory {base_dir!r}")
    return resolved


def _default_db_path() -> str:
    """Resolve the shared DuckDB path through the workspace authority."""
    return str(duckdb_path())


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

_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_{table}_sym_ex_ts
    ON {table} (symbol, exchange, timestamp);
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
            day = (
                str(ts)[:10]
                if isinstance(ts, str)
                else ts.strftime("%Y-%m-%d")
                if hasattr(ts, "strftime")
                else str(ts)[:10]
            )
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


def _serialised(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return call


def app_history_pipeline(app: Any = None) -> DataPipeline | None:
    """Borrow the installed history owner without creating a competing connection."""
    from flask import current_app, has_app_context
    if app is None and has_app_context():
        app = current_app
    return app.config.get("HISTORY_PIPELINE") if app is not None else None


class DataPipeline:
    """DuckDB pipeline for storing, merging, aggregating, and exporting OHLCV data.

    Usage::

        pipeline = DataPipeline()
        pipeline.initialise()
        pipeline.store_download(download_result, "5m")
        pipeline.aggregate("RELIANCE", "NSE", "ohlcv_1m", "ohlcv_5m", 5)
        pipeline.export_parquet("ohlcv_1d", "/data/archive/daily.parquet")
        pipeline.close()
    """

    def __init__(self, db_path: str | None = None, *, read_only: bool = False) -> None:
        self._db_path = db_path or _default_db_path()
        self._read_only = read_only
        if not read_only:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._lock = threading.RLock()
        self._retired = False

    @property
    @_serialised
    def connection(self) -> duckdb.DuckDBPyConnection:
        if self._retired:
            raise RuntimeError("historical owner retired")
        if self._conn is None:
            self._conn = duckdb.connect(self._db_path, read_only=self._read_only)
        return self._conn

    @_serialised
    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @_serialised
    def retire(self) -> None:
        """Permanently fence borrowed readers when their app owner shuts down."""
        self._retired = True
        self.close()

    @contextmanager
    def borrow_connection(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """Serialise a complete SQL/result operation in an existing local consumer."""
        with self._lock:
            yield self.connection

    def __enter__(self) -> DataPipeline:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    @_serialised
    def initialise(self) -> None:
        """Create all OHLCV interval tables and indexes."""
        for table in set(INTERVAL_TABLES.values()):
            self.connection.execute(_TABLE_DDL.format(table=table))
            self.connection.execute(_INDEX_DDL.format(table=table))
        logger.info("Historical pipeline schema initialised (tables + indexes)")

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
        table = _validate_table(table)
        return self._merge_bars(table, symbol, exchange, bars)

    @_serialised
    def _merge_bars(
        self,
        table: str,
        symbol: str,
        exchange: str,
        bars: list[dict[str, Any]],
    ) -> int:
        """Insert bars, skipping duplicates by (timestamp, symbol, exchange).

        Uses a staging table + anti-join instead of per-row SELECT+INSERT,
        reducing 2N queries to 3 queries regardless of bar count.

        Returns number of new rows inserted.
        """
        table = _validate_table(table)
        if not bars:
            return 0

        staging = f"_staging_{table}"
        conn = self.connection

        # 1. Create temp staging table
        conn.execute(f"DROP TABLE IF EXISTS {staging}")
        conn.execute(
            f"""CREATE TEMPORARY TABLE {staging} (
                timestamp TIMESTAMP NOT NULL,
                symbol    VARCHAR NOT NULL,
                exchange  VARCHAR NOT NULL,
                open      DOUBLE NOT NULL,
                high      DOUBLE NOT NULL,
                low       DOUBLE NOT NULL,
                close     DOUBLE NOT NULL,
                volume    BIGINT DEFAULT 0,
                oi        BIGINT DEFAULT 0
            )"""
        )

        # 2. Bulk insert into staging
        conn.executemany(
            f"""INSERT INTO {staging}
                (timestamp, symbol, exchange, open, high, low, close, volume, oi)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    bar["timestamp"],
                    symbol,
                    exchange,
                    bar["open"],
                    bar["high"],
                    bar["low"],
                    bar["close"],
                    bar.get("volume", 0) or 0,
                    bar.get("oi", 0) or 0,
                )
                for bar in bars
            ],
        )

        # 3. Count before, insert, count after (reliable across DuckDB versions)
        before = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE symbol = ? AND exchange = ?",
            [symbol, exchange],
        ).fetchone()[0]  # type: ignore[index]

        conn.execute(
            f"""INSERT INTO {table}
                SELECT s.* FROM {staging} s
                WHERE NOT EXISTS (
                    SELECT 1 FROM {table} t
                    WHERE t.timestamp = s.timestamp
                      AND t.symbol = s.symbol
                      AND t.exchange = s.exchange
                )"""
        )

        after = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE symbol = ? AND exchange = ?",
            [symbol, exchange],
        ).fetchone()[0]  # type: ignore[index]
        inserted = after - before

        conn.execute(f"DROP TABLE IF EXISTS {staging}")

        logger.info(
            "Merged %d/%d bars into %s for %s:%s",
            inserted,
            len(bars),
            table,
            exchange,
            symbol,
        )
        return inserted

    @_serialised
    def publish_history(self, *, identity: dict[str, Any], scope: dict[str, Any],
                        policy: dict[str, Any], contributors: list[dict[str, Any]]) -> dict[str, Any]:
        """Publish a content-addressed history in this existing store.

        Legacy OHLCV tables remain distinct: their absent source/adjustment
        metadata cannot be retroactively asserted by this publication.
        """
        from flinttrade_core.data_contracts import canonical_json
        from flinttrade_historical.history_manifest import build_history

        snapshot = build_history(identity=identity, scope=scope, policy=policy, contributors=contributors)
        encoded = canonical_json(snapshot)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS history_manifests (snapshot_id VARCHAR PRIMARY KEY, document VARCHAR NOT NULL)"
        )
        self.connection.execute("INSERT INTO history_manifests VALUES (?, ?) ON CONFLICT DO NOTHING",
                                [snapshot["snapshot_id"], encoded])
        stored = self.history_snapshot(snapshot["snapshot_id"], scope=scope)
        if stored is None:
            raise ValueError("historical publication missing on readback")
        return stored

    @_serialised
    def history_snapshots(self, *, scope: dict[str, Any]) -> list[dict[str, Any]]:
        """Enumerate only verified snapshots owned by the exact current scope."""
        import json

        from flinttrade_core.data_contracts import validate_scope

        scope = validate_scope(scope)
        if self._conn is None and self._db_path != ":memory:" and not Path(self._db_path).exists():
            return []
        if not self.connection.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name='history_manifests'"
        ).fetchone():
            return []
        rows = self.connection.execute("SELECT snapshot_id, document FROM history_manifests ORDER BY snapshot_id").fetchall()
        return [self.history_snapshot(identifier, scope=scope) for identifier, document in rows
                if json.loads(document)["scope"] == scope]

    @_serialised
    def history_snapshot(self, snapshot_id: str, *, scope: dict[str, Any]) -> dict[str, Any] | None:
        """Read and hash-verify an immutable snapshot in its exact scope."""
        import json
        import re

        from flinttrade_core.data_contracts import DataIntegrityError, digest, validate_scope

        scope = validate_scope(scope)
        if not re.fullmatch(r"[0-9a-f]{64}", snapshot_id):
            raise DataIntegrityError("invalid snapshot identity")
        if not self.connection.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name='history_manifests'"
        ).fetchone():
            return None
        row = self.connection.execute("SELECT document FROM history_manifests WHERE snapshot_id=?", [snapshot_id]).fetchone()
        if row is None:
            return None
        snapshot = json.loads(row[0])
        content = {key: value for key, value in snapshot.items() if key != "snapshot_id"}
        if snapshot.get("snapshot_id") != snapshot_id or digest(content) != snapshot_id:
            raise DataIntegrityError("historical manifest checksum mismatch")
        if snapshot["scope"] != scope:
            raise PermissionError("historical snapshot scope mismatch")
        return snapshot

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    @_serialised
    def get_bars(
        self,
        table: str,
        symbol: str,
        exchange: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query OHLCV bars from a table."""
        table = _validate_table(table)
        query = (
            f"SELECT timestamp, symbol, exchange, open, high, low, close, volume, oi"
            f" FROM {table} WHERE symbol = ? AND exchange = ?"
        )
        params: list[Any] = [symbol, exchange]

        if start_date:
            query += " AND timestamp >= ?"
            params.append(start_date)
        if end_date:
            # Inclusive end DATE = strictly before the next midnight. The old
            # `<=` bound also matched a bar stamped exactly at end+1day 00:00
            # (the next session's daily bar), leaking one extra row.
            query += " AND timestamp < ?::DATE + INTERVAL '1 day'"
            params.append(end_date)

        query += " ORDER BY timestamp"

        result = self.connection.execute(query, params)
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    @_serialised
    def count_bars(self, table: str, symbol: str, exchange: str) -> int:
        """Count bars in a table for a symbol."""
        table = _validate_table(table)
        result = self.connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE symbol = ? AND exchange = ?",
            [symbol, exchange],
        )
        row = result.fetchone()
        return row[0] if row else 0

    @_serialised
    def summary(self) -> dict[str, dict[str, Any]]:
        """Summarise the local store: per interval table, row/symbol counts.

        Returns:
            ``{table: {"rows": int, "symbols": int, "first": str|None,
            "last": str|None}}`` for every interval table that exists. Missing
            tables (store not initialised) report zeros.
        """
        out: dict[str, dict[str, Any]] = {}
        for table in sorted(VALID_TABLES):
            try:
                row = self.connection.execute(
                    f"SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(timestamp), MAX(timestamp) FROM {table}"
                ).fetchone()
                out[table] = {
                    "rows": int(row[0]) if row else 0,
                    "symbols": int(row[1]) if row else 0,
                    "first": str(row[2]) if row and row[2] is not None else None,
                    "last": str(row[3]) if row and row[3] is not None else None,
                }
            except Exception:
                out[table] = {"rows": 0, "symbols": 0, "first": None, "last": None}
        return out

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
                    source,
                    target,
                    exchange,
                    symbol,
                    count,
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
        table = _validate_table(table)
        safe_output = _validate_path(output_path)
        safe_output.parent.mkdir(parents=True, exist_ok=True)

        query = f"SELECT timestamp, symbol, exchange, open, high, low, close, volume, oi FROM {table}"
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

        # Sanitize path for SQL string literal — reject single quotes to prevent injection
        safe_output_str = str(safe_output)
        if "'" in safe_output_str:
            raise ValueError(f"Output path must not contain single quotes: {safe_output_str!r}")
        self.connection.execute(
            f"COPY ({query}) TO '{safe_output_str}' (FORMAT PARQUET)",
            params or None,
        )
        logger.info("Exported %s to %s", table, safe_output)
        return str(safe_output)

    def import_parquet(self, table: str, parquet_path: str) -> int:
        """Import a Parquet file into a table. Returns rows imported."""
        table = _validate_table(table)
        safe_parquet = _validate_path(parquet_path)
        before = self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        self.connection.execute(
            f"INSERT INTO {table} SELECT * FROM read_parquet(?)",
            [str(safe_parquet)],
        )
        after = self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        imported = after - before
        logger.info("Imported %d rows from %s into %s", imported, safe_parquet, table)
        return imported
