"""DuckDB storage manager — connection pooling, schema creation, query helpers.

Tables: ticks, trades, audit, daily_summary
All timestamps stored as UTC. Queries accept IST date ranges and convert internally.
"""

from __future__ import annotations

import csv
import io
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

logger = logging.getLogger("flinttrade.data.storage")

def _default_db_path() -> str:
    """Resolve DuckDB path: env override > workspace > fallback."""
    env = os.getenv("DUCKDB_PATH")
    if env:
        return env
    try:
        from packages.core.src.workspace import Workspace
        return str(Workspace().fast_data_dir / "flint.duckdb")
    except Exception:
        return str(Path.home() / ".flinttrade" / "data" / "flint.duckdb")


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

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
    depth_json  VARCHAR
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

_ALL_SCHEMAS = [_SCHEMA_TICKS, _SCHEMA_TRADES, _SCHEMA_AUDIT, _SCHEMA_DAILY_SUMMARY]


# ---------------------------------------------------------------------------
# StorageManager
# ---------------------------------------------------------------------------


class StorageManager:
    """DuckDB connection manager with schema initialization and query helpers.

    Usage::

        storage = StorageManager("/data/flinttrade/flint.duckdb")
        storage.initialize()
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

    def initialize(self) -> None:
        """Create all tables if they don't exist."""
        for ddl in _ALL_SCHEMAS:
            self.connection.execute(ddl)
        logger.info("DuckDB schema initialized")

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
    ) -> None:
        """Insert a single tick row (append-only)."""
        self.connection.execute(
            """INSERT INTO ticks
               (ts, symbol, exchange, mode, ltp, open, high, low, close,
                volume, bid, ask, oi, prev_close, depth_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [ts, symbol, exchange, mode, ltp, open_, high, low, close,
             volume, bid, ask, oi, prev_close, depth_json],
        )

    def insert_ticks_batch(self, rows: list[tuple]) -> None:
        """Bulk insert ticks. Each tuple matches the ticks column order."""
        if not rows:
            return
        self.connection.executemany(
            """INSERT INTO ticks
               (ts, symbol, exchange, mode, ltp, open, high, low, close,
                volume, bid, ask, oi, prev_close, depth_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

    def get_ticks(
        self,
        symbol: str,
        exchange: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """Query ticks by symbol, exchange, and date range (YYYY-MM-DD strings)."""
        result = self.connection.execute(
            """SELECT * FROM ticks
               WHERE symbol = ? AND exchange = ?
                 AND ts >= ? AND ts < ?::DATE + INTERVAL '1 day'
               ORDER BY ts""",
            [symbol, exchange, start_date, end_date],
        )
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    def get_ticks_by_date(self, trade_date: str) -> list[dict[str, Any]]:
        """Get all ticks for a given date."""
        result = self.connection.execute(
            """SELECT * FROM ticks
               WHERE ts >= ?::DATE AND ts < ?::DATE + INTERVAL '1 day'
               ORDER BY ts""",
            [trade_date, trade_date],
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
            [ts, orderid, symbol, exchange, action, quantity, price,
             product, strategy, entry_price, exit_price, pnl, slippage, fees],
        )

    def get_trades_by_strategy(
        self, strategy: str, start_date: str, end_date: str,
    ) -> list[dict[str, Any]]:
        """Get trades filtered by strategy and date range."""
        result = self.connection.execute(
            """SELECT * FROM trades
               WHERE strategy = ?
                 AND ts >= ? AND ts < ?::DATE + INTERVAL '1 day'
               ORDER BY ts""",
            [strategy, start_date, end_date],
        )
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    def get_trades_by_date(self, trade_date: str) -> list[dict[str, Any]]:
        """Get all trades for a given date."""
        result = self.connection.execute(
            """SELECT * FROM trades
               WHERE ts >= ?::DATE AND ts < ?::DATE + INTERVAL '1 day'
               ORDER BY ts""",
            [trade_date, trade_date],
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
                """SELECT * FROM daily_summary
                   WHERE trade_date >= ? AND trade_date <= ? AND strategy = ?
                   ORDER BY trade_date""",
                [start_date, end_date, strategy],
            )
        else:
            result = self.connection.execute(
                """SELECT * FROM daily_summary
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
        """Export trades to CSV string."""
        trades = (
            self.get_trades_by_strategy(strategy, start_date, end_date)
            if strategy
            else self.get_trades_by_date(start_date)
        )
        if not trades:
            return ""

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=trades[0].keys())
        writer.writeheader()
        writer.writerows(trades)
        return output.getvalue()
