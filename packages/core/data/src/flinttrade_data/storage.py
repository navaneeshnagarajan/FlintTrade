"""DuckDB storage manager — connection pooling, schema creation, query helpers.

Tables: ticks, trades, audit, daily_summary
All timestamps stored as UTC. Queries accept IST date ranges and convert internally.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb

logger = logging.getLogger("flinttrade.data.storage")
IST = timezone(timedelta(hours=5, minutes=30))
_SCHEMA_INITIALISE_LOCK = threading.RLock()
MAX_TICK_REPLAY_QUERY_ROWS = 100_001
_TICK_STORE_ID_KEY = "tick_store_id"
_MAX_INGEST_SEQ = 2**63 - 1


class TickReplayCursorError(ValueError):
    """Base class for persisted tick replay cursor failures."""


class TickReplayStoreMismatchError(TickReplayCursorError):
    """Raised when a cursor belongs to a different tick store."""


class TickReplayCursorAheadError(TickReplayCursorError):
    """Raised when storage has rolled back behind a persisted cursor."""


@dataclass(frozen=True, slots=True)
class TickReplayCursor:
    """Stable tick-store lineage and its latest committed ingest sequence."""

    store_id: str
    ingest_seq: int

    def __post_init__(self) -> None:
        if not isinstance(self.store_id, str):
            raise ValueError("store_id must be a canonical UUID")
        try:
            parsed_store_id = uuid.UUID(self.store_id)
        except (AttributeError, ValueError) as exc:
            raise ValueError("store_id must be a canonical UUID") from exc
        if str(parsed_store_id) != self.store_id:
            raise ValueError("store_id must be a canonical UUID")
        if (
            isinstance(self.ingest_seq, bool)
            or not isinstance(self.ingest_seq, int)
            or not 0 <= self.ingest_seq <= _MAX_INGEST_SEQ
        ):
            raise ValueError("ingest_seq must be a non-negative BIGINT")


def _normalise_ts(value: Any) -> Any:
    """Store aware timestamps as naive UTC for DuckDB TIMESTAMP columns."""
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _timestamp_provenance(value: Any) -> str:
    """Validate whether a stored timestamp is source-authored or untrusted."""
    if not isinstance(value, str) or value not in {"source", "unknown"}:
        raise ValueError("timestamp_provenance must be 'source' or 'unknown'")
    return value


def _ist_date_window(start_date: str, end_date: str) -> tuple[datetime, datetime]:
    """Convert inclusive IST date strings to UTC-naive storage bounds."""
    start = datetime.combine(date.fromisoformat(start_date), time.min, tzinfo=IST)
    end = datetime.combine(date.fromisoformat(end_date), time.min, tzinfo=IST) + timedelta(days=1)
    return _normalise_ts(start), _normalise_ts(end)


def _default_db_path() -> str:
    """Resolve DuckDB path: env override > workspace > fallback."""
    env = os.getenv("DUCKDB_PATH")
    if env:
        return env
    try:
        from flinttrade_core.workspace import Workspace
        return str(Workspace().fast_data_dir / "flint.duckdb")
    except Exception:
        return str(Path.home() / ".flinttrade" / "data" / "flint.duckdb")


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_SCHEMA_TICKS_SEQUENCE = "CREATE SEQUENCE IF NOT EXISTS ticks_ingest_seq START 1;"

_SCHEMA_TICKS = """
CREATE TABLE IF NOT EXISTS ticks (
    ts          TIMESTAMP NOT NULL,
    symbol      VARCHAR NOT NULL,
    exchange    VARCHAR NOT NULL,
    mode        VARCHAR NOT NULL,
    ltp         DOUBLE,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    volume      BIGINT,
    bid         DOUBLE,
    ask         DOUBLE,
    oi          BIGINT,
    prev_close  DOUBLE,
    depth_json  VARCHAR,
    timestamp_provenance VARCHAR NOT NULL DEFAULT 'unknown',
    ingest_seq  BIGINT NOT NULL DEFAULT nextval('ticks_ingest_seq')
);
"""

_MIGRATE_TICKS_INGEST_SEQUENCE = """
ALTER TABLE ticks
ADD COLUMN IF NOT EXISTS ingest_seq BIGINT DEFAULT nextval('ticks_ingest_seq');
"""

_REQUIRE_TICKS_INGEST_SEQUENCE = """
ALTER TABLE ticks ALTER COLUMN ingest_seq SET NOT NULL;
"""

_MIGRATE_TICKS_TIMESTAMP_PROVENANCE = """
ALTER TABLE ticks
ADD COLUMN IF NOT EXISTS timestamp_provenance VARCHAR DEFAULT 'unknown';
"""

_REQUIRE_TICKS_TIMESTAMP_PROVENANCE = """
ALTER TABLE ticks ALTER COLUMN timestamp_provenance SET NOT NULL;
"""

_BACKFILL_TICKS_TIMESTAMP_PROVENANCE = """
UPDATE ticks SET timestamp_provenance = 'unknown' WHERE timestamp_provenance IS NULL;
"""

_SCHEMA_STORAGE_METADATA = """
CREATE TABLE IF NOT EXISTS flinttrade_storage_metadata (
    key     VARCHAR PRIMARY KEY,
    value   VARCHAR NOT NULL
);
"""

_SCHEMA_TRADES = """
CREATE TABLE IF NOT EXISTS trades (
    ts              TIMESTAMP NOT NULL,
    orderid         VARCHAR NOT NULL,
    symbol          VARCHAR NOT NULL,
    exchange        VARCHAR NOT NULL,
    action          VARCHAR NOT NULL,
    quantity        INTEGER NOT NULL,
    price           DOUBLE NOT NULL,
    product         VARCHAR,
    strategy        VARCHAR,
    entry_price     DOUBLE,
    exit_price      DOUBLE,
    pnl             DOUBLE,
    slippage        DOUBLE,
    fees            DOUBLE
);
"""

_SCHEMA_AUDIT = """
CREATE TABLE IF NOT EXISTS audit (
    ts          TIMESTAMP NOT NULL,
    event_type  VARCHAR NOT NULL,
    strategy    VARCHAR,
    symbol      VARCHAR,
    exchange    VARCHAR,
    action      VARCHAR,
    quantity    VARCHAR,
    price       VARCHAR,
    layer       VARCHAR,
    verdict     VARCHAR,
    reason      VARCHAR,
    details     VARCHAR
);
"""

_SCHEMA_DAILY_SUMMARY = """
CREATE TABLE IF NOT EXISTS daily_summary (
    trade_date      DATE NOT NULL,
    strategy        VARCHAR,
    total_trades    INTEGER DEFAULT 0,
    winning_trades  INTEGER DEFAULT 0,
    losing_trades   INTEGER DEFAULT 0,
    gross_pnl       DOUBLE DEFAULT 0.0,
    fees            DOUBLE DEFAULT 0.0,
    net_pnl         DOUBLE DEFAULT 0.0,
    max_drawdown    DOUBLE DEFAULT 0.0
);
"""

_ALL_SCHEMAS = [
    _SCHEMA_TICKS,
    _SCHEMA_TRADES,
    _SCHEMA_AUDIT,
    _SCHEMA_DAILY_SUMMARY,
    _SCHEMA_STORAGE_METADATA,
]

# Indexes — without these, every query does a full table scan.
_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_ticks_sym_ex_ts_seq ON ticks (symbol, exchange, ts, ingest_seq)",
    "CREATE INDEX IF NOT EXISTS idx_trades_strategy_ts ON trades (strategy, ts)",
    "CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts ON trades (symbol, ts)",
    "CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades (ts)",
    "CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit (ts)",
    "CREATE INDEX IF NOT EXISTS idx_audit_event ON audit (event_type, ts)",
    "CREATE INDEX IF NOT EXISTS idx_daily_summary_date ON daily_summary (trade_date, strategy)",
]
_DROP_TICKS_INDEX = "DROP INDEX IF EXISTS idx_ticks_sym_ex_ts_seq"


# ---------------------------------------------------------------------------
# StorageManager
# ---------------------------------------------------------------------------


class StorageManager:
    """DuckDB connection manager with schema initialisation and query helpers.

    Usage::

        storage = StorageManager("/data/flinttrade/flint.duckdb")
        storage.initialise()
        storage.insert_tick(...)
        ticks = storage.get_ticks("RELIANCE", "NSE", "2026-03-01", "2026-03-16")
        storage.close()
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _default_db_path()
        # Ensure parent directory exists
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: duckdb.DuckDBPyConnection | None = None

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self._conn = duckdb.connect(self._db_path)
            logger.info("DuckDB connected: %s", self._db_path)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            logger.info("DuckDB closed: %s", self._db_path)

    def __enter__(self) -> StorageManager:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Schema management
    # ------------------------------------------------------------------

    def initialise(self) -> None:
        """Create all tables and indexes if they don't exist."""
        with _SCHEMA_INITIALISE_LOCK:
            self.connection.execute(_SCHEMA_TICKS_SEQUENCE)
            for ddl in _ALL_SCHEMAS:
                self.connection.execute(ddl)
            self.connection.execute(_MIGRATE_TICKS_INGEST_SEQUENCE)
            self.connection.execute(_MIGRATE_TICKS_TIMESTAMP_PROVENANCE)
            tick_columns = {
                row[1]: row
                for row in self.connection.execute("PRAGMA table_info('ticks')").fetchall()
            }
            requires_constraint_migration = not (
                tick_columns["ingest_seq"][3]
                and tick_columns["timestamp_provenance"][3]
            )
            if requires_constraint_migration:
                # DuckDB refuses ALTER COLUMN while any index depends on the
                # table, even when that index does not mention the new column.
                self.connection.execute(_DROP_TICKS_INDEX)
            try:
                if not tick_columns["ingest_seq"][3]:
                    self.connection.execute(_REQUIRE_TICKS_INGEST_SEQUENCE)
                if not tick_columns["timestamp_provenance"][3]:
                    self.connection.execute(_BACKFILL_TICKS_TIMESTAMP_PROVENANCE)
                    self.connection.execute(_REQUIRE_TICKS_TIMESTAMP_PROVENANCE)
            finally:
                if requires_constraint_migration:
                    self.connection.execute(_INDEXES[0])
            for idx in _INDEXES:
                self.connection.execute(idx)
            candidate_store_id = str(uuid.uuid4())
            self.connection.execute(
                """INSERT INTO flinttrade_storage_metadata (key, value)
                   SELECT ?, ?
                   WHERE NOT EXISTS (
                       SELECT 1 FROM flinttrade_storage_metadata WHERE key = ?
                   )""",
                [_TICK_STORE_ID_KEY, candidate_store_id, _TICK_STORE_ID_KEY],
            )
            self._read_tick_store_id()
        logger.info("DuckDB schema initialised (tables + indexes)")

    # ------------------------------------------------------------------
    # Tick storage
    # ------------------------------------------------------------------

    def insert_tick(
        self,
        ts: datetime,
        symbol: str,
        exchange: str,
        mode: str,
        *,
        ltp: float | None = None,
        open_: float | None = None,
        high: float | None = None,
        low: float | None = None,
        close: float | None = None,
        volume: int | None = None,
        bid: float | None = None,
        ask: float | None = None,
        oi: int | None = None,
        prev_close: float | None = None,
        depth_json: str | None = None,
        timestamp_provenance: str = "unknown",
    ) -> None:
        """Insert a single tick row (append-only)."""
        self.connection.execute(
            """INSERT INTO ticks
               (ts, symbol, exchange, mode, ltp, open, high, low, close,
                volume, bid, ask, oi, prev_close, depth_json, timestamp_provenance)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [_normalise_ts(ts), symbol, exchange, mode, ltp, open_, high, low, close,
             volume, bid, ask, oi, prev_close, depth_json, _timestamp_provenance(timestamp_provenance)],
        )

    def insert_ticks_batch(self, rows: list[tuple]) -> None:
        """Bulk insert ticks ATOMICALLY. Each tuple matches the ticks column order.

        Provenance-aware rows contain 16 fields and end in ``"source"``.
        Legacy 15-field rows remain insertable but are marked ``"unknown"``
        so restart replay cannot treat receipt-substituted history as source time.

        The batch runs in an explicit transaction so a mid-batch failure (e.g. a
        bad row, disk-full) rolls the WHOLE batch back rather than leaving a
        partially-committed prefix. This is what lets the TickRecorder safely
        retain-and-retry a failed buffer without duplicating already-committed
        rows (the ticks table has no unique constraint, so a partial commit
        followed by a full retry would otherwise double-insert the prefix).
        """
        if not rows:
            return
        conn = self.connection
        normalised_rows = []
        for row in rows:
            if len(row) == 15:
                row = (*row, "unknown")
            if len(row) != 16:
                raise ValueError("tick rows must contain 15 legacy or 16 provenance-aware fields")
            normalised_rows.append(
                (_normalise_ts(row[0]), *row[1:15], _timestamp_provenance(row[15]))
            )
        conn.execute("BEGIN TRANSACTION")
        try:
            conn.executemany(
                """INSERT INTO ticks
                   (ts, symbol, exchange, mode, ltp, open, high, low, close,
                    volume, bid, ask, oi, prev_close, depth_json, timestamp_provenance)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                normalised_rows,
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def prune_ticks(self, days_to_keep: int) -> int:
        """Delete ticks older than ``days_to_keep`` days; return rows removed.

        Keeps the append-only tick store bounded. A non-positive window is a
        no-op — it never deletes everything by accident. The cut-off is computed
        in Python (a naive datetime, matching the naive ``ts`` column) so the
        comparison is timezone-consistent.
        """
        if days_to_keep <= 0:
            return 0
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_to_keep)
        conn = self.connection
        before = conn.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
        conn.execute("DELETE FROM ticks WHERE ts < ?", [cutoff])
        after = conn.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
        return int(before - after)

    def get_ticks(
        self,
        symbol: str,
        exchange: str,
        start_date: str,
        end_date: str,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Query ticks by symbol, exchange, and date range (YYYY-MM-DD strings).

        When ``limit`` is supplied, the query reads only the most recent rows
        from DuckDB and reverses that bounded result for chronological output.
        """
        start, end = _ist_date_window(start_date, end_date)
        params: list[Any] = [symbol, exchange, start, end]
        order_clause = "ORDER BY ts, ingest_seq"
        if limit is not None:
            if limit <= 0:
                return []
            order_clause = "ORDER BY ts DESC, ingest_seq DESC LIMIT ?"
            params.append(limit)
        result = self.connection.execute(
            f"""SELECT ts, symbol, exchange, mode, ltp, open, high, low, close,
                       volume, bid, ask, oi, prev_close, depth_json, timestamp_provenance
                FROM ticks
                WHERE symbol = ? AND exchange = ?
                  AND ts >= ? AND ts < ?
                {order_clause}""",  # noqa: S608 - clause is selected from fixed literals above
            params,
        )
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        if limit is not None:
            rows.reverse()
        return [dict(zip(columns, row)) for row in rows]

    def get_tick_replay_cursor(self) -> TickReplayCursor:
        """Return this store's identity and latest committed global tick sequence."""
        store_id = self._read_tick_store_id()
        row = self.connection.execute(
            "SELECT COALESCE(MAX(ingest_seq), 0) FROM ticks"
        ).fetchone()
        ingest_seq = int(row[0]) if row is not None else 0
        return TickReplayCursor(store_id=store_id, ingest_seq=ingest_seq)

    def validate_tick_replay_cursor(
        self,
        cursor: TickReplayCursor,
    ) -> TickReplayCursor:
        """Validate cursor lineage and rollback safety; return the current cursor."""
        if not isinstance(cursor, TickReplayCursor):
            raise TypeError("cursor must be a TickReplayCursor")
        current = self.get_tick_replay_cursor()
        if cursor.store_id != current.store_id:
            raise TickReplayStoreMismatchError("cursor belongs to a different tick store")
        if cursor.ingest_seq > current.ingest_seq:
            raise TickReplayCursorAheadError("cursor is ahead of tick storage")
        return current

    def get_ticks_after_cursor(
        self,
        cursor: TickReplayCursor,
        symbol: str,
        exchange: str,
        session_date: str,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return the earliest current-session rows committed after ``cursor``.

        Callers should request ``max_ticks + 1`` rows. Receiving at most
        ``max_ticks`` proves the cursor-bound tail is complete; receiving the
        extra row proves replay must fail closed or use a newer checkpoint.
        Unlike :meth:`get_ticks`, rows include ``ingest_seq`` so duplicate source
        timestamps retain a stable persistence order.
        """
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 0 < limit <= MAX_TICK_REPLAY_QUERY_ROWS
        ):
            raise ValueError(
                f"limit must be between 1 and {MAX_TICK_REPLAY_QUERY_ROWS}"
            )
        self.validate_tick_replay_cursor(cursor)
        start, end = _ist_date_window(session_date, session_date)
        result = self.connection.execute(
            """SELECT ts, symbol, exchange, mode, ltp, open, high, low, close,
                      volume, bid, ask, oi, prev_close, depth_json,
                      timestamp_provenance, ingest_seq
               FROM ticks
               WHERE ingest_seq > ?
                 AND symbol = ? AND exchange = ?
                 AND ts >= ? AND ts < ?
               ORDER BY ingest_seq
               LIMIT ?""",
            [cursor.ingest_seq, symbol, exchange, start, end, limit],
        )
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    def _read_tick_store_id(self) -> str:
        """Read and validate the durable tick-store identity."""
        try:
            row = self.connection.execute(
                "SELECT value FROM flinttrade_storage_metadata WHERE key = ?",
                [_TICK_STORE_ID_KEY],
            ).fetchone()
        except duckdb.Error as exc:
            raise RuntimeError("tick storage is not initialised") from exc
        if row is None:
            raise RuntimeError("tick storage identity is missing")
        try:
            return TickReplayCursor(str(row[0]), 0).store_id
        except ValueError as exc:
            raise RuntimeError("tick storage identity is invalid") from exc

    def get_ticks_by_date(self, trade_date: str) -> list[dict[str, Any]]:
        """Get all ticks for a given date."""
        start, end = _ist_date_window(trade_date, trade_date)
        result = self.connection.execute(
            """SELECT ts, symbol, exchange, mode, ltp, open, high, low, close,
                      volume, bid, ask, oi, prev_close, depth_json, timestamp_provenance
               FROM ticks
               WHERE ts >= ? AND ts < ?
               ORDER BY ts, ingest_seq""",
            [start, end],
        )
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    # ------------------------------------------------------------------
    # Trade storage
    # ------------------------------------------------------------------

    def insert_trade(
        self,
        ts: datetime,
        orderid: str,
        symbol: str,
        exchange: str,
        action: str,
        quantity: int,
        price: float,
        *,
        product: str = "",
        strategy: str = "",
        entry_price: float | None = None,
        exit_price: float | None = None,
        pnl: float | None = None,
        slippage: float | None = None,
        fees: float | None = None,
    ) -> None:
        """Insert a single trade row."""
        self.connection.execute(
            """INSERT INTO trades
               (ts, orderid, symbol, exchange, action, quantity, price,
                product, strategy, entry_price, exit_price, pnl, slippage, fees)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [_normalise_ts(ts), orderid, symbol, exchange, action, quantity, price,
             product, strategy, entry_price, exit_price, pnl, slippage, fees],
        )

    def get_trades_by_strategy(
        self, strategy: str, start_date: str, end_date: str,
    ) -> list[dict[str, Any]]:
        """Get trades filtered by strategy and date range."""
        start, end = _ist_date_window(start_date, end_date)
        result = self.connection.execute(
            """SELECT ts, orderid, symbol, exchange, action, quantity, price,
                      product, strategy, entry_price, exit_price, pnl, slippage, fees
               FROM trades
               WHERE strategy = ?
                 AND ts >= ? AND ts < ?
               ORDER BY ts""",
            [strategy, start, end],
        )
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    def get_trades_by_date(self, trade_date: str) -> list[dict[str, Any]]:
        """Get all trades for a given date."""
        start, end = _ist_date_window(trade_date, trade_date)
        result = self.connection.execute(
            """SELECT ts, orderid, symbol, exchange, action, quantity, price,
                      product, strategy, entry_price, exit_price, pnl, slippage, fees
               FROM trades
               WHERE ts >= ? AND ts < ?
               ORDER BY ts""",
            [start, end],
        )
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    def get_trades_by_date_range(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        """Get all trades between two dates (inclusive), across every strategy.

        Args:
            start_date: Inclusive lower bound (``YYYY-MM-DD``).
            end_date: Inclusive upper bound (``YYYY-MM-DD``).

        Returns:
            Trade rows ordered by timestamp. Used by the journal route for
            history-window queries (e.g. the performance dashboard) where no
            single strategy is specified.
        """
        start, end = _ist_date_window(start_date, end_date)
        result = self.connection.execute(
            """SELECT ts, orderid, symbol, exchange, action, quantity, price,
                      product, strategy, entry_price, exit_price, pnl, slippage, fees
               FROM trades
               WHERE ts >= ? AND ts < ?
               ORDER BY ts""",
            [start, end],
        )
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    # ------------------------------------------------------------------
    # Daily summary
    # ------------------------------------------------------------------

    def upsert_daily_summary(
        self,
        trade_date: date,
        strategy: str,
        total_trades: int,
        winning_trades: int,
        losing_trades: int,
        gross_pnl: float,
        fees: float,
        net_pnl: float,
        max_drawdown: float = 0.0,
    ) -> None:
        """Insert or replace a daily summary row."""
        # DuckDB doesn't have UPSERT, so delete + insert
        self.connection.execute(
            "DELETE FROM daily_summary WHERE trade_date = ? AND strategy = ?",
            [trade_date, strategy],
        )
        self.connection.execute(
            """INSERT INTO daily_summary
               (trade_date, strategy, total_trades, winning_trades, losing_trades,
                gross_pnl, fees, net_pnl, max_drawdown)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [trade_date, strategy, total_trades, winning_trades, losing_trades,
             gross_pnl, fees, net_pnl, max_drawdown],
        )

    def get_daily_summaries(
        self, start_date: str, end_date: str, strategy: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get daily summaries for a date range, optionally filtered by strategy."""
        if strategy:
            result = self.connection.execute(
                """SELECT trade_date, strategy, total_trades, winning_trades,
                          losing_trades, gross_pnl, fees, net_pnl, max_drawdown
                   FROM daily_summary
                   WHERE trade_date >= ? AND trade_date <= ? AND strategy = ?
                   ORDER BY trade_date""",
                [start_date, end_date, strategy],
            )
        else:
            result = self.connection.execute(
                """SELECT trade_date, strategy, total_trades, winning_trades,
                          losing_trades, gross_pnl, fees, net_pnl, max_drawdown
                   FROM daily_summary
                   WHERE trade_date >= ? AND trade_date <= ?
                   ORDER BY trade_date""",
                [start_date, end_date],
            )
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_trades_csv(
        self, start_date: str, end_date: str, strategy: str | None = None,
    ) -> str:
        """Export trades to CSV string over the inclusive [start_date, end_date] range."""
        trades = (
            self.get_trades_by_strategy(strategy, start_date, end_date)
            if strategy
            else self.get_trades_by_date_range(start_date, end_date)
        )
        if not trades:
            return ""

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=trades[0].keys())
        writer.writeheader()
        writer.writerows(trades)
        return output.getvalue()
