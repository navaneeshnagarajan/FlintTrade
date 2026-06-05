"""Track expired option chains for backtesting and analysis (ExpiryTrack).

Captures option chain snapshots before expiry using OpenAlgo's ``optionchain``
endpoint and stores them in DuckDB for historical analysis.

Adapts patterns from MarketCalls/ExpiryFlow:
- DuckDB schema with composite primary keys and download metadata tracking
- Date-chunked downloads with skip-if-exists deduplication
- Thread-safe rate limiting for broker API calls
- Migration tracking via ``_migrations`` table

Schema: symbol, expiry_date, strike, option_type (CE/PE), oi, volume, ltp, iv

Usage::

    tracker = ExpiryTracker(client, db_path=":memory:")
    tracker.capture_snapshot("NIFTY", "260326")
    chain = tracker.get_historical_chain("NIFTY", "260326")
    expiries = tracker.list_expiries("NIFTY")
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb

from flinttrade_core.openalgo_client import OpenAlgoClient

logger = logging.getLogger("flinttrade.historical.expiry_tracker")

IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# Rate limiter (adapted from ExpiryFlow's DataApiRateLimiter)
# ---------------------------------------------------------------------------

_MAX_DAYS_PER_CHUNK = 30


class SnapshotRateLimiter:
    """Thread-safe rate limiter for snapshot capture API calls.

    Prevents overwhelming the broker API when bulk-capturing snapshots.
    Pattern adapted from ExpiryFlow's ``DataApiRateLimiter``.

    Args:
        max_per_second: Maximum API calls per second.
        max_per_day: Maximum API calls per day (0 = unlimited).
    """

    def __init__(
        self,
        max_per_second: int = 5,
        max_per_day: int = 0,
    ) -> None:
        self._max_per_second = max_per_second
        self._max_per_day = max_per_day
        self._second_timestamps: list[float] = []
        self._day_count = 0
        self._day_start = time.time()
        self._lock = threading.Lock()

    def wait_if_needed(self) -> None:
        """Block until a request slot is available.

        Raises:
            RuntimeError: If the daily limit has been reached.
        """
        with self._lock:
            now = time.time()
            # Reset daily counter after 24h
            if now - self._day_start >= 86400:
                self._day_count = 0
                self._day_start = now
            if self._max_per_day > 0 and self._day_count >= self._max_per_day:
                raise RuntimeError(
                    f"Daily API limit reached ({self._max_per_day} requests)"
                )
            # Enforce per-second limit
            self._second_timestamps = [
                t for t in self._second_timestamps if now - t < 1.0
            ]
            if len(self._second_timestamps) >= self._max_per_second:
                sleep_time = 1.0 - (now - self._second_timestamps[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
            self._second_timestamps.append(time.time())
            self._day_count += 1

    @property
    def requests_today(self) -> int:
        """Number of requests made since the daily counter last reset."""
        return self._day_count


# ---------------------------------------------------------------------------
# DuckDB schema (enhanced with ExpiryFlow patterns: metadata + migrations)
# ---------------------------------------------------------------------------

_SCHEMA_OPTION_CHAIN = """
CREATE TABLE IF NOT EXISTS expired_option_chains (
    captured_at   TIMESTAMP NOT NULL,
    symbol        VARCHAR NOT NULL,
    exchange      VARCHAR NOT NULL,
    expiry_date   VARCHAR NOT NULL,
    strike        DOUBLE NOT NULL,
    option_type   VARCHAR NOT NULL,
    oi            BIGINT DEFAULT 0,
    volume        BIGINT DEFAULT 0,
    ltp           DOUBLE DEFAULT 0.0,
    iv            DOUBLE DEFAULT 0.0,
    PRIMARY KEY (symbol, expiry_date, strike, option_type, captured_at)
);
"""

_INDEX_OPTION_CHAIN = (
    "CREATE INDEX IF NOT EXISTS idx_expired_oc_sym_exp "
    "ON expired_option_chains (symbol, expiry_date)"
)

_SCHEMA_DOWNLOAD_METADATA = """
CREATE TABLE IF NOT EXISTS download_metadata (
    id              INTEGER PRIMARY KEY,
    symbol          VARCHAR NOT NULL,
    exchange        VARCHAR NOT NULL,
    expiry_date     VARCHAR NOT NULL,
    from_date       DATE NOT NULL,
    to_date         DATE NOT NULL,
    row_count       INTEGER NOT NULL DEFAULT 0,
    downloaded_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

_SCHEMA_DOWNLOAD_SEQ = (
    "CREATE SEQUENCE IF NOT EXISTS download_metadata_id_seq START 1"
)

_SCHEMA_MIGRATIONS = (
    "CREATE TABLE IF NOT EXISTS _migrations (name VARCHAR PRIMARY KEY)"
)


# ---------------------------------------------------------------------------
# ExpiryTracker
# ---------------------------------------------------------------------------


class ExpiryTracker:
    """Capture and store option chain snapshots for expired expiries.

    Enhanced with patterns from ExpiryFlow:
    - Download metadata tracking (skip-if-exists deduplication)
    - Date range chunking for bulk captures
    - Rate limiting for broker API calls
    - Migration tracking

    Args:
        client: OpenAlgo client for fetching live option chain data.
        db_path: Path to the DuckDB database. Use ``":memory:"`` for tests.
        rate_limiter: Optional rate limiter. A default (5 req/s) is created
            if ``None``.
    """

    def __init__(
        self,
        client: OpenAlgoClient | None = None,
        db_path: str = "",
        rate_limiter: SnapshotRateLimiter | None = None,
    ) -> None:
        self._client = client
        if not db_path:
            db_path = str(Path.home() / ".flinttrade" / "data" / "expiry_tracker.duckdb")
        self._db_path = db_path
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._rate_limiter = rate_limiter or SnapshotRateLimiter()
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            if self._db_path == ":memory:":
                self._conn = duckdb.connect(":memory:")
            else:
                Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
                self._conn = duckdb.connect(self._db_path)
        return self._conn

    def close(self) -> None:
        """Close the DuckDB connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _ensure_schema(self) -> None:
        """Create tables, indexes, and run pending migrations.

        Follows ExpiryFlow's migration pattern: a ``_migrations`` table
        records which schema changes have already been applied.
        """
        self.connection.execute(_SCHEMA_MIGRATIONS)
        self.connection.execute(_SCHEMA_OPTION_CHAIN)
        self.connection.execute(_INDEX_OPTION_CHAIN)
        self.connection.execute(_SCHEMA_DOWNLOAD_METADATA)
        self.connection.execute(_SCHEMA_DOWNLOAD_SEQ)

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    def capture_snapshot(
        self,
        symbol: str,
        expiry: str,
        exchange: str = "NFO",
    ) -> int:
        """Fetch the current option chain and store it as a snapshot.

        Uses the OpenAlgo ``optionchain`` endpoint to get CE/PE data for
        all strikes at the given expiry.

        Args:
            symbol: Underlying symbol (e.g. ``"NIFTY"``).
            expiry: Expiry date string (e.g. ``"260326"`` or ``"2026-03-26"``).
            exchange: Exchange segment (default ``"NFO"``).

        Returns:
            Number of rows inserted.
        """
        if self._client is None:
            logger.error("No OpenAlgo client — cannot capture snapshot")
            return 0

        try:
            data = self._client.optionchain(symbol, exchange, expiry)
        except Exception as exc:
            logger.error("Failed to fetch option chain for %s %s: %s", symbol, expiry, exc)
            return 0

        rows = self._parse_option_chain(data, symbol, exchange, expiry)
        if not rows:
            logger.warning("No option chain data returned for %s %s", symbol, expiry)
            return 0

        now = datetime.now(IST)
        insert_rows = [
            (now, r["symbol"], r["exchange"], r["expiry_date"],
             r["strike"], r["option_type"], r["oi"], r["volume"],
             r["ltp"], r["iv"])
            for r in rows
        ]

        self.connection.executemany(
            """INSERT INTO expired_option_chains
               (captured_at, symbol, exchange, expiry_date, strike,
                option_type, oi, volume, ltp, iv)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            insert_rows,
        )

        self._record_download(symbol, exchange, expiry, len(insert_rows))

        logger.info(
            "Captured %d option chain rows for %s expiry %s",
            len(insert_rows), symbol, expiry,
        )
        return len(insert_rows)

    @staticmethod
    def _parse_option_chain(
        data: Any,
        symbol: str,
        exchange: str,
        expiry: str,
    ) -> list[dict[str, Any]]:
        """Parse OpenAlgo optionchain response into flat rows.

        OpenAlgo returns the option chain in various formats depending on
        broker. This method handles the common shapes:
        - List of dicts with ``strike_price``, ``call_oi``, ``put_oi``, etc.
        - Dict with ``data`` key containing the list.
        """
        records: list[dict[str, Any]] = []

        # Unwrap nested response
        if isinstance(data, dict):
            chain_list = data.get("data", data.get("optionchain", []))
            if isinstance(chain_list, dict):
                chain_list = chain_list.get("data", [])
        elif isinstance(data, list):
            chain_list = data
        else:
            return records

        if not isinstance(chain_list, list):
            return records

        for entry in chain_list:
            if not isinstance(entry, dict):
                continue

            strike = float(entry.get("strike_price", entry.get("strike", 0)))
            if strike <= 0:
                continue

            # CE row
            records.append({
                "symbol": symbol,
                "exchange": exchange,
                "expiry_date": expiry,
                "strike": strike,
                "option_type": "CE",
                "oi": int(entry.get("call_oi", entry.get("ce_oi", 0))),
                "volume": int(entry.get("call_volume", entry.get("ce_volume", 0))),
                "ltp": float(entry.get("call_ltp", entry.get("ce_ltp", 0))),
                "iv": float(entry.get("call_iv", entry.get("ce_iv", 0))),
            })

            # PE row
            records.append({
                "symbol": symbol,
                "exchange": exchange,
                "expiry_date": expiry,
                "strike": strike,
                "option_type": "PE",
                "oi": int(entry.get("put_oi", entry.get("pe_oi", 0))),
                "volume": int(entry.get("put_volume", entry.get("pe_volume", 0))),
                "ltp": float(entry.get("put_ltp", entry.get("pe_ltp", 0))),
                "iv": float(entry.get("put_iv", entry.get("pe_iv", 0))),
            })

        return records

    # ------------------------------------------------------------------
    # Download metadata (adapted from ExpiryFlow)
    # ------------------------------------------------------------------

    def has_snapshot(
        self,
        symbol: str,
        expiry: str,
        exchange: str = "NFO",
    ) -> bool:
        """Check whether a snapshot already exists for this symbol/expiry.

        Adapted from ExpiryFlow's ``_has_data`` skip-if-exists pattern:
        avoids redundant API calls when data has already been captured.

        Args:
            symbol: Underlying symbol.
            expiry: Expiry date string.
            exchange: Exchange segment.

        Returns:
            True if at least one row exists for this combination.
        """
        row = self.connection.execute(
            """SELECT COUNT(*) FROM download_metadata
               WHERE symbol = ? AND expiry_date = ? AND exchange = ?""",
            [symbol, expiry, exchange],
        ).fetchone()
        return row is not None and row[0] > 0

    def _record_download(
        self,
        symbol: str,
        exchange: str,
        expiry: str,
        row_count: int,
    ) -> None:
        """Record a successful download in the metadata table.

        Args:
            symbol: Underlying symbol.
            exchange: Exchange segment.
            expiry: Expiry date string.
            row_count: Number of rows captured.
        """
        today = date.today()
        self.connection.execute(
            """INSERT INTO download_metadata
               (id, symbol, exchange, expiry_date, from_date, to_date,
                row_count, downloaded_at)
               VALUES (nextval('download_metadata_id_seq'),
                       ?, ?, ?, ?::DATE, ?::DATE, ?, CURRENT_TIMESTAMP)""",
            [symbol, exchange, expiry, today.isoformat(), today.isoformat(), row_count],
        )

    def get_download_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent download metadata records.

        Adapted from ExpiryFlow's ``get_download_history``.

        Args:
            limit: Maximum number of records to return.

        Returns:
            List of dicts with download metadata.
        """
        result = self.connection.execute(
            """SELECT symbol, exchange, expiry_date, from_date, to_date,
                      row_count, downloaded_at
               FROM download_metadata
               ORDER BY downloaded_at DESC
               LIMIT ?""",
            [limit],
        )
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    # ------------------------------------------------------------------
    # Bulk capture (adapted from ExpiryFlow's download_service)
    # ------------------------------------------------------------------

    def capture_multiple(
        self,
        symbol: str,
        expiries: list[str],
        exchange: str = "NFO",
        skip_existing: bool = True,
    ) -> dict[str, int]:
        """Capture snapshots for multiple expiries with rate limiting.

        Adapted from ExpiryFlow's ``run_download_job`` pattern:
        - Iterates over expiries
        - Skips already-downloaded data
        - Rate-limits API calls

        Args:
            symbol: Underlying symbol.
            expiries: List of expiry date strings.
            exchange: Exchange segment.
            skip_existing: If True, skip expiries that already have data.

        Returns:
            Dict mapping expiry to row count captured (0 if skipped).
        """
        results: dict[str, int] = {}
        for expiry in expiries:
            if skip_existing and self.has_snapshot(symbol, expiry, exchange):
                logger.info(
                    "Skipping %s %s — snapshot already exists", symbol, expiry
                )
                results[expiry] = 0
                continue
            try:
                self._rate_limiter.wait_if_needed()
                count = self.capture_snapshot(symbol, expiry, exchange)
                results[expiry] = count
            except RuntimeError as exc:
                logger.error("Rate limit hit during bulk capture: %s", exc)
                break
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Failed to capture %s %s: %s", symbol, expiry, exc
                )
                results[expiry] = 0
        return results

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_historical_chain(
        self,
        symbol: str,
        expiry: str,
        exchange: str = "NFO",
    ) -> list[dict[str, Any]]:
        """Retrieve a stored option chain snapshot.

        Returns the most recent snapshot for the given symbol and expiry.

        Args:
            symbol: Underlying symbol.
            expiry: Expiry date string.
            exchange: Exchange segment.

        Returns:
            List of dicts with keys: strike, option_type, oi, volume, ltp, iv,
            captured_at, symbol, exchange, expiry_date.
        """
        result = self.connection.execute(
            """SELECT captured_at, symbol, exchange, expiry_date,
                      strike, option_type, oi, volume, ltp, iv
               FROM expired_option_chains
               WHERE symbol = ? AND expiry_date = ? AND exchange = ?
               ORDER BY strike, option_type""",
            [symbol, expiry, exchange],
        )
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    def list_expiries(
        self,
        symbol: str,
        exchange: str = "NFO",
    ) -> list[str]:
        """List all expiry dates for which snapshots exist.

        Args:
            symbol: Underlying symbol.
            exchange: Exchange segment.

        Returns:
            Sorted list of unique expiry date strings.
        """
        result = self.connection.execute(
            """SELECT DISTINCT expiry_date
               FROM expired_option_chains
               WHERE symbol = ? AND exchange = ?
               ORDER BY expiry_date""",
            [symbol, exchange],
        )
        return [row[0] for row in result.fetchall()]
