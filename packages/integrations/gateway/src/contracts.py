"""ContractManager: downloads and caches broker master contracts.

Each broker has its own SQLite DB at contracts_dir/<broker>.db containing
the full symbol list (50K+ instruments). Updated daily at market open.

Schema: symtoken(symbol TEXT, broker_symbol TEXT, token TEXT,
                 exchange TEXT, lot_size INTEGER DEFAULT 1,
                 PRIMARY KEY(symbol, exchange))
"""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from flinttrade_core.db import open_sqlite

from .exceptions import ContractError

logger = logging.getLogger("flinttrade.gateway.contracts")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_IST_OFFSET_HOURS: int = 5
_IST_OFFSET_MINUTES: int = 30

_INSTRUMENTS_DDL: str = """
CREATE TABLE IF NOT EXISTS instruments (
    security_id        INTEGER NOT NULL,
    exchange_segment   TEXT NOT NULL,
    trading_symbol     TEXT NOT NULL,
    custom_symbol      TEXT,
    symbol_name        TEXT NOT NULL,
    instrument_type    TEXT NOT NULL,
    lot_size           INTEGER NOT NULL,
    freeze_qty         INTEGER,
    tick_size          REAL NOT NULL,
    expiry_date        TEXT,
    strike_price       REAL,
    option_type        TEXT,
    underlying_symbol  TEXT,
    last_updated_at    REAL NOT NULL,
    PRIMARY KEY (security_id, exchange_segment)
);

CREATE INDEX IF NOT EXISTS idx_instruments_trading_symbol
    ON instruments (trading_symbol, exchange_segment);

CREATE INDEX IF NOT EXISTS idx_instruments_underlying_expiry
    ON instruments (underlying_symbol, expiry_date)
    WHERE underlying_symbol IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_instruments_custom_symbol
    ON instruments (custom_symbol, exchange_segment);

CREATE TABLE IF NOT EXISTS _meta (
    source_url        TEXT PRIMARY KEY,
    broker            TEXT NOT NULL,
    segment           TEXT,
    etag              TEXT,
    last_modified     TEXT,
    last_refreshed_at REAL NOT NULL,
    row_count         INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_meta_broker_segment
    ON _meta(broker, segment);
"""


# ---------------------------------------------------------------------------
# ContractManager
# ---------------------------------------------------------------------------


def _legacy_symtoken_to_instruments_migration(conn: sqlite3.Connection) -> int:
    """Copy legacy ``symtoken`` rows into canonical ``instruments`` once."""
    has_legacy = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='symtoken'"
    ).fetchone()
    if not has_legacy:
        return 0

    rows = conn.execute(
        """
        SELECT symbol, broker_symbol, token, exchange, lot_size
        FROM symtoken
        """
    ).fetchall()
    for symbol, broker_symbol, security_id, exchange_segment, lot_size in rows:
        conn.execute(
            """
            INSERT OR REPLACE INTO instruments (
                security_id, exchange_segment, trading_symbol, custom_symbol,
                symbol_name, instrument_type, lot_size, freeze_qty, tick_size,
                expiry_date, strike_price, option_type, underlying_symbol,
                last_updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, NULL, NULL, NULL, ?)
            """,
            (
                security_id,
                exchange_segment,
                broker_symbol or symbol,
                symbol,
                symbol,
                "EQUITY",
                lot_size or 1,
                0.05,
                time.time(),
            ),
        )
    conn.execute("DROP TABLE symtoken")
    return len(rows)


def bootstrap_schema(conn: sqlite3.Connection) -> None:
    """Create the canonical instruments schema and walk legacy rows."""
    conn.executescript(_INSTRUMENTS_DDL)
    _legacy_symtoken_to_instruments_migration(conn)


class ContractManager:
    """Manages per-broker master contract SQLite databases.

    Each broker is isolated in its own ``<contracts_dir>/<broker>.db`` file.
    The manager handles table creation, atomic full-refresh inserts, and
    symbol/token lookups.

    Args:
        contracts_dir: Directory that holds per-broker ``.db`` files.
            Created automatically if it does not exist.

    Example::

        mgr = ContractManager(Path("~/.flinttrade/contracts").expanduser())
        count = mgr.insert_contracts("zerodha", rows)
        token = mgr.get_token("NIFTY", "NSE_INDEX", "zerodha")
    """

    def __init__(self, contracts_dir: Path) -> None:
        self._dir = contracts_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        logger.debug("ContractManager initialised at %s", self._dir)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _db_path(self, broker: str) -> Path:
        """Return the path to a broker's contract database file.

        Args:
            broker: Canonical broker name (e.g. ``"zerodha"``).

        Returns:
            Absolute :class:`~pathlib.Path` to the ``.db`` file.
        """
        return self._dir / f"{broker}.db"

    def _get_conn(self, broker: str) -> sqlite3.Connection:
        """Open a connection to a broker's contract database.

        Creates the ``symtoken`` table and supporting indices if they do
        not already exist.

        Args:
            broker: Canonical broker name.

        Returns:
            An open :class:`sqlite3.Connection` with WAL journal mode.

        Raises:
            ContractError: If the database file cannot be opened or the
                schema cannot be created.
        """
        db_path = self._db_path(broker)
        try:
            conn = open_sqlite(str(db_path), durability="normal")
            bootstrap_schema(conn)
            return conn
        except sqlite3.Error as exc:
            raise ContractError(
                f"Cannot open contract DB for broker {broker!r}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Cache staleness
    # ------------------------------------------------------------------

    def is_cache_stale(self, broker: str, cutoff_hour: int = 8) -> bool:
        """Check whether the contract cache needs refreshing.

        The cache is considered stale if the broker's ``.db`` file does not
        exist, or if it was last modified before today's ``cutoff_hour`` in
        IST (UTC+5:30).

        Args:
            broker: Canonical broker name.
            cutoff_hour: Hour of day in IST (24-hour) after which today's
                data is considered fresh.  Defaults to ``8`` (08:00 IST).

        Returns:
            ``True`` if the cache is absent or stale; ``False`` otherwise.
        """
        db_path = self._db_path(broker)
        if not db_path.exists():
            logger.debug("Contract DB for %r not found — stale", broker)
            return True

        mtime_utc = datetime.fromtimestamp(db_path.stat().st_mtime, tz=timezone.utc)

        # Convert UTC mtime to IST
        ist_offset_seconds = (_IST_OFFSET_HOURS * 60 + _IST_OFFSET_MINUTES) * 60
        # Use simple arithmetic: add offset seconds to the UTC timestamp
        mtime_ist_ts = mtime_utc.timestamp() + ist_offset_seconds
        mtime_ist_dt = datetime.fromtimestamp(mtime_ist_ts, tz=timezone.utc)

        now_ist_ts = datetime.now(tz=timezone.utc).timestamp() + ist_offset_seconds
        now_ist_dt = datetime.fromtimestamp(now_ist_ts, tz=timezone.utc)

        # Today's cutoff in IST: midnight of today + cutoff_hour hours
        today_ist_date = now_ist_dt.date()
        cutoff_ist_ts = (
            datetime(
                today_ist_date.year,
                today_ist_date.month,
                today_ist_date.day,
                cutoff_hour,
                0,
                0,
                tzinfo=timezone.utc,
            ).timestamp()
        )

        # mtime must be on or after today's cutoff (both in IST-equivalent UTC ts)
        if mtime_ist_ts < cutoff_ist_ts:
            logger.debug(
                "Contract DB for %r is stale (mtime IST %s, cutoff %02d:00 IST)",
                broker,
                mtime_ist_dt.strftime("%Y-%m-%d %H:%M"),
                cutoff_hour,
            )
            return True

        logger.debug("Contract DB for %r is fresh", broker)
        return False

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def insert_contracts(self, broker: str, contracts: list[dict]) -> int:
        """Atomically replace all contracts for a broker.

        Deletes all existing records and inserts the new batch in a single
        transaction.  If any record fails (e.g. missing required field) the
        entire operation is rolled back, leaving the previous data intact.

        Args:
            broker: Canonical broker name.
            contracts: List of dicts, each containing:
                ``symbol``, ``broker_symbol``, ``token``, ``exchange``,
                and optionally ``lot_size`` (defaults to ``1``).

        Returns:
            Number of rows successfully inserted.

        Raises:
            ContractError: If the insert fails for any reason.
        """
        conn = self._get_conn(broker)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM instruments")
            conn.executemany(
                """
                INSERT INTO instruments (
                    security_id, exchange_segment, trading_symbol,
                    custom_symbol, symbol_name, instrument_type,
                    lot_size, freeze_qty, tick_size, expiry_date,
                    strike_price, option_type, underlying_symbol,
                    last_updated_at
                ) VALUES (
                    :token, :exchange, :broker_symbol, :symbol, :symbol,
                    COALESCE(:instrument_type, 'EQUITY'),
                    COALESCE(:lot_size, 1), :freeze_qty,
                    COALESCE(:tick_size, 0.05), :expiry_date,
                    :strike_price, :option_type, :underlying_symbol,
                    :last_updated_at
                )
                """,
                [
                    {
                        "token": row.get("token"),
                        "exchange": row.get("exchange"),
                        "broker_symbol": row.get("broker_symbol"),
                        "symbol": row.get("symbol"),
                        "instrument_type": row.get("instrument_type"),
                        "lot_size": row.get("lot_size"),
                        "freeze_qty": row.get("freeze_qty"),
                        "tick_size": row.get("tick_size"),
                        "expiry_date": row.get("expiry_date"),
                        "strike_price": row.get("strike_price"),
                        "option_type": row.get("option_type"),
                        "underlying_symbol": row.get("underlying_symbol"),
                        "last_updated_at": row.get("last_updated_at", time.time()),
                    }
                    for row in contracts
                ],
            )
            conn.execute("COMMIT")
            count = conn.execute("SELECT COUNT(*) FROM instruments").fetchone()[0]
            logger.info(
                "Inserted %d contracts for broker %r", count, broker
            )
            return count  # type: ignore[no-any-return]
        except (sqlite3.Error, KeyError, TypeError) as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise ContractError(
                f"insert_contracts failed for broker {broker!r}: {exc}"
            ) from exc
        finally:
            conn.close()

    def clear(self, broker: str) -> None:
        """Delete all contract records for a broker.

        Args:
            broker: Canonical broker name.

        Raises:
            ContractError: If the delete operation fails.
        """
        conn = self._get_conn(broker)
        try:
            with conn:
                conn.execute("DELETE FROM instruments")
            logger.debug("Cleared all contracts for broker %r", broker)
        except sqlite3.Error as exc:
            raise ContractError(
                f"clear failed for broker {broker!r}: {exc}"
            ) from exc
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Read / lookup operations
    # ------------------------------------------------------------------

    def get_br_symbol(
        self, symbol: str, exchange: str, broker: str
    ) -> str | None:
        """Look up the broker-specific symbol for a FlintTrade symbol.

        Args:
            symbol: FlintTrade canonical symbol (e.g. ``"NIFTY"``).
            exchange: Exchange code (e.g. ``"NSE_INDEX"``).
            broker: Canonical broker name.

        Returns:
            The broker's own symbol string, or ``None`` if not found.
        """
        conn = self._get_conn(broker)
        try:
            row = conn.execute(
                "SELECT trading_symbol FROM instruments "
                "WHERE custom_symbol = ? AND exchange_segment = ?",
                (symbol, exchange),
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def get_token(
        self, symbol: str, exchange: str, broker: str
    ) -> str | None:
        """Look up the instrument token for a FlintTrade symbol.

        Args:
            symbol: FlintTrade canonical symbol.
            exchange: Exchange code.
            broker: Canonical broker name.

        Returns:
            The instrument token string, or ``None`` if not found.
        """
        conn = self._get_conn(broker)
        try:
            row = conn.execute(
                "SELECT security_id FROM instruments "
                "WHERE custom_symbol = ? AND exchange_segment = ?",
                (symbol, exchange),
            ).fetchone()
            return str(row[0]) if row else None
        finally:
            conn.close()

    def get_oa_symbol(
        self, symbol: str, exchange: str, broker: str
    ) -> str | None:
        """Reverse-lookup: broker_symbol -> FlintTrade symbol.

        Args:
            symbol: The broker's own symbol string (``broker_symbol``).
            exchange: Exchange code.
            broker: Canonical broker name.

        Returns:
            The FlintTrade canonical symbol, or ``None`` if not found.
        """
        conn = self._get_conn(broker)
        try:
            row = conn.execute(
                "SELECT custom_symbol FROM instruments "
                "WHERE trading_symbol = ? AND exchange_segment = ?",
                (symbol, exchange),
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def count(self, broker: str) -> int:
        """Return the number of contracts stored for a broker.

        Args:
            broker: Canonical broker name.

        Returns:
            Row count as an integer.
        """
        conn = self._get_conn(broker)
        try:
            row = conn.execute("SELECT COUNT(*) FROM instruments").fetchone()
            return row[0]  # type: ignore[no-any-return]
        finally:
            conn.close()
