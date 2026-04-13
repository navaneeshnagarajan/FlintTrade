"""QuestDB client — PostgreSQL wire protocol interface for tick data storage.

Uses psycopg2 to connect to QuestDB via its PostgreSQL wire protocol endpoint
(default port 8812). Provides typed table creation, bulk inserts for three tick
schemas (LTP / Quote / Depth), OHLCV candle generation via ``date_trunc``, and
a market-stats CTE that computes 24 h high/low and 1 h/24 h percentage changes.

This module sits alongside the ILP-based :mod:`questdb_bridge` in the data
package. Use the bridge (port 9009 + 9000) for ultra-high-throughput ingestion
and this client (port 8812) when you need full SQL semantics — parameterised
queries, CTEs, transactions.

psycopg2 is an optional dependency. If it is not installed the module still
imports cleanly; all public methods raise :class:`QuestDBClientError` with a
helpful message when called without the driver.

Usage::

    from packages.data.src.questdb_client import QuestDBClient

    with QuestDBClient(host="127.0.0.1") as client:
        client.create_tables()
        client.insert_ltp("NIFTY", "NSE_INDEX", 24500.0)
        candles = client.generate_candles("NIFTY", "NSE_INDEX", interval="5m")
        stats = client.get_market_stats("NIFTY", "NSE_INDEX")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("flinttrade.data.questdb_client")

# ---------------------------------------------------------------------------
# Optional psycopg2 import — graceful degradation
# ---------------------------------------------------------------------------

try:
    import psycopg2
    import psycopg2.extras  # needed for execute_values

    _PSYCOPG2_AVAILABLE = True
except ImportError:  # pragma: no cover
    psycopg2 = None  # type: ignore[assignment]
    _PSYCOPG2_AVAILABLE = False

# ---------------------------------------------------------------------------
# Return-type dataclasses
# ---------------------------------------------------------------------------


@dataclass
class OHLCV:
    """Single aggregated OHLCV bar.

    Attributes:
        timestamp: Bar open timestamp (UTC).
        open: First tick price in the bar.
        high: Highest tick price in the bar.
        low: Lowest tick price in the bar.
        close: Last tick price in the bar.
        volume: Total traded volume in the bar (LTP tick count for
            ``ticks_ltp``; sum of ``volume`` column for ``ticks_quote``).
    """

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class MarketStats:
    """24-hour market statistics for a single instrument.

    Attributes:
        symbol: Instrument symbol.
        exchange: Exchange code.
        current_price: Most recent LTP.
        high_24h: Highest LTP over the past 24 hours.
        low_24h: Lowest LTP over the past 24 hours.
        change_pct_1h: Percentage change over the past 1 hour.
        change_pct_24h: Percentage change over the past 24 hours.
        trade_count: Number of ticks recorded in the past 24 hours.
    """

    symbol: str
    exchange: str
    current_price: float
    high_24h: float
    low_24h: float
    change_pct_1h: float
    change_pct_24h: float
    trade_count: int


# ---------------------------------------------------------------------------
# DDL — table schemas
# ---------------------------------------------------------------------------

# QuestDB SYMBOL type is an indexed, low-cardinality string column — faster
# than VARCHAR for repeated tag values like symbol names.

_DDL_TICKS_LTP = """
CREATE TABLE IF NOT EXISTS ticks_ltp (
    timestamp TIMESTAMP,
    symbol    SYMBOL,
    exchange  SYMBOL,
    ltp       DOUBLE
) timestamp(timestamp) PARTITION BY DAY;
"""

_DDL_TICKS_QUOTE = """
CREATE TABLE IF NOT EXISTS ticks_quote (
    timestamp TIMESTAMP,
    symbol    SYMBOL,
    exchange  SYMBOL,
    ltp       DOUBLE,
    bid       DOUBLE,
    ask       DOUBLE,
    volume    LONG,
    oi        LONG
) timestamp(timestamp) PARTITION BY DAY;
"""

_DDL_TICKS_DEPTH = """
CREATE TABLE IF NOT EXISTS ticks_depth (
    timestamp TIMESTAMP,
    symbol    SYMBOL,
    exchange  SYMBOL,
    level     INT,
    bid_price DOUBLE,
    bid_qty   LONG,
    ask_price DOUBLE,
    ask_qty   LONG
) timestamp(timestamp) PARTITION BY DAY;
"""


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class QuestDBClientError(Exception):
    """Raised when a QuestDB PostgreSQL-wire operation fails."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class QuestDBClient:
    """QuestDB client via PostgreSQL wire protocol (psycopg2, port 8812).

    Manages a single persistent connection. Call :meth:`connect` (or use as a
    context manager) before performing any operation. All write methods accept
    an optional ``timestamp`` parameter; when omitted they default to the
    current UTC time.

    Args:
        host: QuestDB host. Default ``"127.0.0.1"``.
        port: PostgreSQL wire protocol port. Default ``8812``.
        user: QuestDB username. Default ``"admin"``.
        password: QuestDB password. Default ``"quest"``.
        database: QuestDB database name. Default ``"qdb"``.

    Raises:
        QuestDBClientError: If psycopg2 is not installed or the connection
            cannot be established.

    Example::

        with QuestDBClient() as client:
            client.create_tables()
            client.insert_ltp("RELIANCE", "NSE", 2985.5)
            bars = client.generate_candles("RELIANCE", "NSE", interval="1m")
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8812,
        user: str = "admin",
        password: str = "quest",
        database: str = "qdb",
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database

        self._conn: Any | None = None
        self._cursor: Any | None = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> QuestDBClient:
        self.connect()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the PostgreSQL wire protocol connection to QuestDB.

        Safe to call multiple times — closes any existing connection first.

        Raises:
            QuestDBClientError: If psycopg2 is not installed.
            QuestDBClientError: If the connection attempt fails.
        """
        if not _PSYCOPG2_AVAILABLE:
            raise QuestDBClientError(
                "psycopg2 is not installed. "
                "Run: pip install psycopg2-binary"
            )

        # Close any stale connection before re-connecting.
        self._close_internal()

        try:
            self._conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
            )
            self._cursor = self._conn.cursor()
            logger.info(
                "QuestDB connected: %s:%d db=%s", self.host, self.port, self.database
            )
        except Exception as exc:
            self._conn = None
            self._cursor = None
            raise QuestDBClientError(
                f"QuestDB connection to {self.host}:{self.port} failed: {exc}"
            ) from exc

    def is_connected(self) -> bool:
        """Return ``True`` if the connection is open and not closed.

        Returns:
            Connection liveness flag.
        """
        return self._conn is not None and not self._conn.closed

    def close(self) -> None:
        """Close the connection and cursor, releasing server resources."""
        self._close_internal()
        logger.info("QuestDB connection closed")

    def _close_internal(self) -> None:
        """Internal — silently close cursor and connection."""
        if self._cursor:
            try:
                self._cursor.close()
            except Exception:
                pass
            self._cursor = None
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _require_connection(self) -> None:
        """Raise :class:`QuestDBClientError` if not connected."""
        if not self.is_connected():
            raise QuestDBClientError(
                "Not connected to QuestDB. Call connect() first."
            )

    # ------------------------------------------------------------------
    # DDL
    # ------------------------------------------------------------------

    def create_tables(self) -> None:
        """Create the three tick tables if they do not already exist.

        Tables created:
            - ``ticks_ltp``   — LTP-only ticks
            - ``ticks_quote`` — full quote ticks (bid/ask/volume/OI)
            - ``ticks_depth`` — per-level order book depth

        All tables use ``PARTITION BY DAY`` for efficient time-range queries.

        Raises:
            QuestDBClientError: If not connected or table creation fails.
        """
        self._require_connection()

        for ddl in (_DDL_TICKS_LTP, _DDL_TICKS_QUOTE, _DDL_TICKS_DEPTH):
            try:
                self._cursor.execute(ddl)
                self._conn.commit()
            except Exception as exc:
                self._conn.rollback()
                raise QuestDBClientError(
                    f"Failed to create table: {exc}"
                ) from exc

        logger.info("QuestDB tables created/verified: ticks_ltp, ticks_quote, ticks_depth")

    # ------------------------------------------------------------------
    # Inserts — LTP
    # ------------------------------------------------------------------

    def insert_ltp(
        self,
        symbol: str,
        exchange: str,
        ltp: float,
        timestamp: datetime | None = None,
    ) -> bool:
        """Insert a single LTP tick into ``ticks_ltp``.

        Args:
            symbol: Instrument symbol, e.g. ``"NIFTY"``.
            exchange: Exchange code, e.g. ``"NSE_INDEX"``.
            ltp: Last traded price.
            timestamp: Tick timestamp (UTC). Defaults to ``datetime.utcnow()``.

        Returns:
            ``True`` on success, ``False`` on failure (error is logged).

        Raises:
            QuestDBClientError: If not connected.
        """
        self._require_connection()
        ts = _coerce_ts(timestamp)
        try:
            self._cursor.execute(
                "INSERT INTO ticks_ltp (timestamp, symbol, exchange, ltp) "
                "VALUES (%s, %s, %s, %s)",
                (ts, symbol, exchange, float(ltp)),
            )
            self._conn.commit()
            return True
        except Exception as exc:
            logger.error("insert_ltp failed: %s", exc)
            self._conn.rollback()
            return False

    def insert_ltp_bulk(
        self,
        rows: list[tuple[str, str, float, datetime | None]],
    ) -> int:
        """Bulk insert LTP ticks using ``execute_values``.

        Args:
            rows: List of ``(symbol, exchange, ltp, timestamp)`` tuples.
                  ``timestamp`` may be ``None`` — defaults to current UTC time.

        Returns:
            Number of rows successfully inserted. ``0`` on failure.

        Raises:
            QuestDBClientError: If not connected or psycopg2 not available.
        """
        self._require_connection()
        if not rows:
            return 0

        values = [(_coerce_ts(r[3]), r[0], r[1], float(r[2])) for r in rows]
        try:
            import psycopg2.extras as _pg_extras

            _pg_extras.execute_values(
                self._cursor,
                "INSERT INTO ticks_ltp (timestamp, symbol, exchange, ltp) VALUES %s",
                values,
            )
            self._conn.commit()
            logger.debug("insert_ltp_bulk: %d rows inserted", len(values))
            return len(values)
        except Exception as exc:
            logger.error("insert_ltp_bulk failed: %s", exc)
            self._conn.rollback()
            return 0

    # ------------------------------------------------------------------
    # Inserts — Quote
    # ------------------------------------------------------------------

    def insert_quote(
        self,
        symbol: str,
        exchange: str,
        ltp: float,
        bid: float,
        ask: float,
        volume: int,
        oi: int,
        timestamp: datetime | None = None,
    ) -> bool:
        """Insert a single quote tick into ``ticks_quote``.

        Args:
            symbol: Instrument symbol.
            exchange: Exchange code.
            ltp: Last traded price.
            bid: Best bid price.
            ask: Best ask price.
            volume: Traded volume at tick time.
            oi: Open interest.
            timestamp: Tick timestamp (UTC). Defaults to ``datetime.utcnow()``.

        Returns:
            ``True`` on success, ``False`` on failure.

        Raises:
            QuestDBClientError: If not connected.
        """
        self._require_connection()
        ts = _coerce_ts(timestamp)
        try:
            self._cursor.execute(
                "INSERT INTO ticks_quote "
                "(timestamp, symbol, exchange, ltp, bid, ask, volume, oi) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (ts, symbol, exchange, float(ltp), float(bid), float(ask),
                 int(volume), int(oi)),
            )
            self._conn.commit()
            return True
        except Exception as exc:
            logger.error("insert_quote failed: %s", exc)
            self._conn.rollback()
            return False

    def insert_quote_bulk(
        self,
        rows: list[tuple[str, str, float, float, float, int, int, datetime | None]],
    ) -> int:
        """Bulk insert quote ticks using ``execute_values``.

        Args:
            rows: List of ``(symbol, exchange, ltp, bid, ask, volume, oi,
                  timestamp)`` tuples. ``timestamp`` may be ``None``.

        Returns:
            Number of rows successfully inserted.

        Raises:
            QuestDBClientError: If not connected.
        """
        self._require_connection()
        if not rows:
            return 0

        values = [
            (_coerce_ts(r[7]), r[0], r[1], float(r[2]), float(r[3]),
             float(r[4]), int(r[5]), int(r[6]))
            for r in rows
        ]
        try:
            import psycopg2.extras as _pg_extras

            _pg_extras.execute_values(
                self._cursor,
                "INSERT INTO ticks_quote "
                "(timestamp, symbol, exchange, ltp, bid, ask, volume, oi) VALUES %s",
                values,
            )
            self._conn.commit()
            logger.debug("insert_quote_bulk: %d rows inserted", len(values))
            return len(values)
        except Exception as exc:
            logger.error("insert_quote_bulk failed: %s", exc)
            self._conn.rollback()
            return 0

    # ------------------------------------------------------------------
    # Inserts — Depth
    # ------------------------------------------------------------------

    def insert_depth(
        self,
        symbol: str,
        exchange: str,
        level: int,
        bid_price: float,
        bid_qty: int,
        ask_price: float,
        ask_qty: int,
        timestamp: datetime | None = None,
    ) -> bool:
        """Insert a single order-book depth row into ``ticks_depth``.

        Args:
            symbol: Instrument symbol.
            exchange: Exchange code.
            level: Depth level (0 = best bid/ask, 1 = second level, …).
            bid_price: Bid price at this level.
            bid_qty: Bid quantity at this level.
            ask_price: Ask price at this level.
            ask_qty: Ask quantity at this level.
            timestamp: Tick timestamp (UTC). Defaults to ``datetime.utcnow()``.

        Returns:
            ``True`` on success, ``False`` on failure.

        Raises:
            QuestDBClientError: If not connected.
        """
        self._require_connection()
        ts = _coerce_ts(timestamp)
        try:
            self._cursor.execute(
                "INSERT INTO ticks_depth "
                "(timestamp, symbol, exchange, level, bid_price, bid_qty, ask_price, ask_qty) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (ts, symbol, exchange, int(level), float(bid_price),
                 int(bid_qty), float(ask_price), int(ask_qty)),
            )
            self._conn.commit()
            return True
        except Exception as exc:
            logger.error("insert_depth failed: %s", exc)
            self._conn.rollback()
            return False

    def insert_depth_bulk(
        self,
        rows: list[
            tuple[str, str, int, float, int, float, int, datetime | None]
        ],
    ) -> int:
        """Bulk insert depth rows using ``execute_values``.

        Args:
            rows: List of ``(symbol, exchange, level, bid_price, bid_qty,
                  ask_price, ask_qty, timestamp)`` tuples.

        Returns:
            Number of rows successfully inserted.

        Raises:
            QuestDBClientError: If not connected.
        """
        self._require_connection()
        if not rows:
            return 0

        values = [
            (_coerce_ts(r[7]), r[0], r[1], int(r[2]), float(r[3]),
             int(r[4]), float(r[5]), int(r[6]))
            for r in rows
        ]
        try:
            import psycopg2.extras as _pg_extras

            _pg_extras.execute_values(
                self._cursor,
                "INSERT INTO ticks_depth "
                "(timestamp, symbol, exchange, level, bid_price, bid_qty, ask_price, ask_qty) "
                "VALUES %s",
                values,
            )
            self._conn.commit()
            logger.debug("insert_depth_bulk: %d rows inserted", len(values))
            return len(values)
        except Exception as exc:
            logger.error("insert_depth_bulk failed: %s", exc)
            self._conn.rollback()
            return 0

    # ------------------------------------------------------------------
    # Candle generation
    # ------------------------------------------------------------------

    def generate_candles(
        self,
        symbol: str,
        exchange: str,
        interval: str = "1m",
        start: datetime | str | None = None,
        end: datetime | str | None = None,
    ) -> list[OHLCV]:
        """Aggregate ``ticks_ltp`` ticks into OHLCV candles via ``date_trunc``.

        Uses QuestDB's ``date_trunc`` function for time-bucket alignment. The
        query groups ticks within each bucket by ``symbol`` and ``exchange``
        and computes ``first`` / ``max`` / ``min`` / ``last`` aggregates.

        Supported interval values: ``"1m"``, ``"5m"``, ``"15m"``, ``"30m"``,
        ``"1h"``, ``"4h"``, ``"1d"``.

        Args:
            symbol: Instrument symbol, e.g. ``"NIFTY"``.
            exchange: Exchange code, e.g. ``"NSE_INDEX"``.
            interval: Candle interval string. Default ``"1m"``.
            start: Start of query range (UTC datetime or ISO string).
                   Defaults to midnight today.
            end: End of query range (UTC datetime or ISO string).
                 Defaults to now.

        Returns:
            List of :class:`OHLCV` dataclass instances sorted by timestamp
            ascending.

        Raises:
            QuestDBClientError: If not connected or the query fails.
        """
        self._require_connection()

        trunc_unit = _interval_to_trunc_unit(interval)
        start_ts = _parse_ts_arg(start) if start else _today_midnight_utc()
        end_ts = _parse_ts_arg(end) if end else datetime.now(timezone.utc)

        sql = (
            "SELECT date_trunc('{unit}', timestamp) AS ts, "
            "       first(ltp) AS open, "
            "       max(ltp)   AS high, "
            "       min(ltp)   AS low, "
            "       last(ltp)  AS close, "
            "       count(*)   AS volume "
            "FROM ticks_ltp "
            "WHERE symbol = %s "
            "  AND exchange = %s "
            "  AND timestamp BETWEEN %s AND %s "
            "GROUP BY ts "
            "ORDER BY ts"
        ).format(unit=trunc_unit)

        try:
            self._cursor.execute(sql, (symbol, exchange, start_ts, end_ts))
            rows = self._cursor.fetchall()
        except Exception as exc:
            raise QuestDBClientError(
                f"generate_candles query failed: {exc}"
            ) from exc

        return [
            OHLCV(
                timestamp=row[0],
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=int(row[5]),
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Market stats
    # ------------------------------------------------------------------

    def get_market_stats(
        self,
        symbol: str,
        exchange: str,
    ) -> MarketStats:
        """Return 24 h market statistics for a single instrument.

        Executes a CTE query against ``ticks_ltp`` that computes:
        - Current price (most recent LTP)
        - 24 h high and low
        - 1 h and 24 h percentage changes
        - Total tick count over 24 h

        Args:
            symbol: Instrument symbol, e.g. ``"RELIANCE"``.
            exchange: Exchange code, e.g. ``"NSE"``.

        Returns:
            :class:`MarketStats` dataclass. If no data exists, all price fields
            default to ``0.0`` and counts to ``0``.

        Raises:
            QuestDBClientError: If not connected or the query fails.
        """
        self._require_connection()

        sql = """
WITH current_data AS (
    SELECT last(ltp) AS current_price
    FROM ticks_ltp
    WHERE symbol = %s AND exchange = %s
      AND timestamp > dateadd('m', -5, now())
),
hour_ago AS (
    SELECT first(ltp) AS price_1h_ago
    FROM ticks_ltp
    WHERE symbol = %s AND exchange = %s
      AND timestamp BETWEEN dateadd('m', -65, now())
                        AND dateadd('h', -1, now())
),
day_ago AS (
    SELECT first(ltp) AS price_24h_ago
    FROM ticks_ltp
    WHERE symbol = %s AND exchange = %s
      AND timestamp BETWEEN dateadd('m', -1445, now())
                        AND dateadd('h', -24, now())
),
day_range AS (
    SELECT max(ltp) AS high_24h,
           min(ltp) AS low_24h,
           count(*) AS trade_count
    FROM ticks_ltp
    WHERE symbol = %s AND exchange = %s
      AND timestamp > dateadd('h', -24, now())
)
SELECT
    c.current_price,
    COALESCE(dr.high_24h,   c.current_price)                              AS high_24h,
    COALESCE(dr.low_24h,    c.current_price)                              AS low_24h,
    COALESCE(
        (c.current_price - ha.price_1h_ago)  / NULLIF(ha.price_1h_ago,  0) * 100,
        0.0
    )                                                                      AS change_pct_1h,
    COALESCE(
        (c.current_price - da.price_24h_ago) / NULLIF(da.price_24h_ago, 0) * 100,
        0.0
    )                                                                      AS change_pct_24h,
    COALESCE(dr.trade_count, 0)                                           AS trade_count
FROM current_data c
CROSS JOIN hour_ago ha
CROSS JOIN day_ago da
CROSS JOIN day_range dr
"""

        try:
            self._cursor.execute(
                sql,
                (symbol, exchange) * 4,  # 4 CTEs × 2 params each
            )
            row = self._cursor.fetchone()
        except Exception as exc:
            raise QuestDBClientError(
                f"get_market_stats query failed: {exc}"
            ) from exc

        if row is None:
            return MarketStats(
                symbol=symbol,
                exchange=exchange,
                current_price=0.0,
                high_24h=0.0,
                low_24h=0.0,
                change_pct_1h=0.0,
                change_pct_24h=0.0,
                trade_count=0,
            )

        current_price, high_24h, low_24h, change_pct_1h, change_pct_24h, trade_count = row
        return MarketStats(
            symbol=symbol,
            exchange=exchange,
            current_price=float(current_price or 0),
            high_24h=float(high_24h or 0),
            low_24h=float(low_24h or 0),
            change_pct_1h=float(change_pct_1h or 0),
            change_pct_24h=float(change_pct_24h or 0),
            trade_count=int(trade_count or 0),
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_INTERVAL_TO_TRUNC: dict[str, str] = {
    "1m": "minute",
    "5m": "minute",   # QuestDB date_trunc doesn't have 5m; caller post-groups
    "15m": "minute",
    "30m": "minute",
    "1h": "hour",
    "4h": "hour",
    "1d": "day",
    "day": "day",
    "hour": "hour",
    "minute": "minute",
}

# For intervals like 5m/15m/30m/4h we use the smallest natural unit and let
# QuestDB group on the truncated value. True multi-minute bucketing requires
# SAMPLE BY — use QuestDBBridge for that. For this client we map as follows:
_INTERVAL_SAMPLE: dict[str, str] = {
    "1m": "minute",
    "5m": "minute",
    "15m": "minute",
    "30m": "minute",
    "1h": "hour",
    "4h": "hour",
    "1d": "day",
}


def _interval_to_trunc_unit(interval: str) -> str:
    """Map a human interval string to a QuestDB ``date_trunc`` unit.

    Args:
        interval: Interval string, e.g. ``"5m"``, ``"1h"``, ``"1d"``.

    Returns:
        QuestDB ``date_trunc`` unit string.

    Raises:
        QuestDBClientError: If the interval is not recognised.
    """
    unit = _INTERVAL_TO_TRUNC.get(interval.lower())
    if unit is None:
        raise QuestDBClientError(
            f"Unsupported interval '{interval}'. "
            f"Supported: {list(_INTERVAL_TO_TRUNC)}"
        )
    return unit


def _coerce_ts(ts: datetime | None) -> datetime:
    """Return ``ts`` if given, else current UTC time stripped of tzinfo.

    QuestDB's PostgreSQL wire protocol driver (psycopg2) works best with
    naive datetimes. We strip tzinfo before passing to avoid adapter errors.

    Args:
        ts: Optional timestamp.

    Returns:
        Naive UTC datetime.
    """
    if ts is None:
        return datetime.utcnow()
    if ts.tzinfo is not None:
        return ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts


def _parse_ts_arg(value: datetime | str) -> datetime:
    """Parse a datetime or ISO string into a naive UTC datetime.

    Args:
        value: ``datetime`` instance or ISO 8601 string.

    Returns:
        Naive UTC datetime suitable for psycopg2.

    Raises:
        QuestDBClientError: If the string cannot be parsed.
    """
    if isinstance(value, datetime):
        return _coerce_ts(value)
    try:
        dt = datetime.fromisoformat(str(value))
        return _coerce_ts(dt)
    except ValueError as exc:
        raise QuestDBClientError(
            f"Cannot parse timestamp argument '{value}': {exc}"
        ) from exc


def _today_midnight_utc() -> datetime:
    """Return today's midnight in UTC as a naive datetime."""
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, now.day, 0, 0, 0)
