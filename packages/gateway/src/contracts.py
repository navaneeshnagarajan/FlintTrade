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
from datetime import datetime, timezone
from pathlib import Path

from .exceptions import ContractError

logger = logging.getLogger("flinttrade.gateway.contracts")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_IST_OFFSET_HOURS: int = 5
_IST_OFFSET_MINUTES: int = 30

_CREATE_TABLE_SQL: str = """
CREATE TABLE IF NOT EXISTS symtoken (
    symbol        TEXT NOT NULL,
    broker_symbol TEXT NOT NULL,
    token         TEXT NOT NULL,
    exchange      TEXT NOT NULL,
    lot_size      INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (symbol, exchange)
);
"""

_IDX_BROKER_SYMBOL_SQL: str = """
CREATE INDEX IF NOT EXISTS idx_broker_symbol
ON symtoken (broker_symbol, exchange);
"""

_IDX_TOKEN_SQL: str = """
CREATE INDEX IF NOT EXISTS idx_token
ON symtoken (token, exchange);
"""


# ---------------------------------------------------------------------------
# ContractManager
# ---------------------------------------------------------------------------


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
            conn = sqlite3.connect(str(db_path))
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(_CREATE_TABLE_SQL)
            conn.execute(_IDX_BROKER_SYMBOL_SQL)
            conn.execute(_IDX_TOKEN_SQL)
            conn.commit()
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
            with conn:
                conn.execute("DELETE FROM symtoken")
                conn.executemany(
                    """
                    INSERT INTO symtoken
                        (symbol, broker_symbol, token, exchange, lot_size)
                    VALUES (:symbol, :broker_symbol, :token, :exchange,
                            COALESCE(:lot_size, 1))
                    """,
                    contracts,
                )
            count = conn.execute("SELECT COUNT(*) FROM symtoken").fetchone()[0]
            logger.info(
                "Inserted %d contracts for broker %r", count, broker
            )
            return count  # type: ignore[no-any-return]
        except (sqlite3.Error, KeyError, TypeError) as exc:
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
                conn.execute("DELETE FROM symtoken")
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
                "SELECT broker_symbol FROM symtoken "
                "WHERE symbol = ? AND exchange = ?",
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
                "SELECT token FROM symtoken "
                "WHERE symbol = ? AND exchange = ?",
                (symbol, exchange),
            ).fetchone()
            return row[0] if row else None
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
                "SELECT symbol FROM symtoken "
                "WHERE broker_symbol = ? AND exchange = ?",
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
            row = conn.execute("SELECT COUNT(*) FROM symtoken").fetchone()
            return row[0]  # type: ignore[no-any-return]
        finally:
            conn.close()
