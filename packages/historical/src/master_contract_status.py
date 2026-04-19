"""Master contract sync status tracker.

Records when broker master contracts (instrument lists) were last downloaded
from OpenAlgo and exposes helpers to detect stale contracts that need
re-syncing.

DuckDB is used for persistence — same database as the OHLCV pipeline so all
historical data lives in one file.

Example::

    from packages.historical.src.master_contract_status import MasterContractStatus

    status = MasterContractStatus()
    status.record_sync("zerodha", "NSE", symbol_count=2341, checksum="abc123")
    if status.needs_sync("zerodha", "NSE"):
        trigger_download()
    stale = status.stale_contracts(max_age_hours=24)
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

logger = logging.getLogger("flinttrade.historical.master_contract_status")

_DDL = """
CREATE TABLE IF NOT EXISTS master_contract_status (
    broker          VARCHAR NOT NULL,
    exchange        VARCHAR NOT NULL,
    last_sync_utc   TIMESTAMP NOT NULL,
    symbol_count    INTEGER NOT NULL DEFAULT 0,
    checksum        VARCHAR NOT NULL DEFAULT '',
    PRIMARY KEY (broker, exchange)
);
"""


def _default_db_path() -> str:
    """Resolve DuckDB path: env override > workspace > fallback."""
    env = os.getenv("DUCKDB_PATH")
    if env:
        return env
    try:
        from packages.core.src.workspace import Workspace  # noqa: PLC0415
        return str(Workspace().fast_data_dir / "flint.duckdb")
    except Exception:
        return str(Path.home() / ".flinttrade" / "data" / "flint.duckdb")


class MasterContractStatus:
    """Track broker master contract sync timestamps in DuckDB.

    Args:
        db_path: Path to DuckDB file.  Uses the shared flint.duckdb by default.

    Example::

        mcs = MasterContractStatus()
        mcs.record_sync("zerodha", "NSE", 2341, "deadbeef")
        print(mcs.last_sync("zerodha", "NSE"))
        print(mcs.needs_sync("zerodha", "NSE", max_age_hours=6))
        stale = mcs.stale_contracts(max_age_hours=24)
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _default_db_path()
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._ensure_schema()

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """Lazy connection — opens on first access."""
        if self._conn is None:
            self._conn = duckdb.connect(self._db_path)
        return self._conn

    def close(self) -> None:
        """Close the DuckDB connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def __enter__(self) -> MasterContractStatus:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        """Create the master_contract_status table if it does not exist."""
        self.connection.execute(_DDL)
        logger.debug("MasterContractStatus: schema ready at %s", self._db_path)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record_sync(
        self,
        broker: str,
        exchange: str,
        symbol_count: int,
        checksum: str,
    ) -> None:
        """Record a successful master contract sync.

        Upserts the (broker, exchange) row with the current UTC timestamp.

        Args:
            broker: Broker identifier, e.g. ``"zerodha"``.
            exchange: Exchange code, e.g. ``"NSE"``.
            symbol_count: Number of symbols downloaded.
            checksum: Hash of the contract file (for change detection).
        """
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        self.connection.execute(
            """
            INSERT INTO master_contract_status (broker, exchange, last_sync_utc, symbol_count, checksum)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (broker, exchange) DO UPDATE SET
                last_sync_utc = excluded.last_sync_utc,
                symbol_count  = excluded.symbol_count,
                checksum      = excluded.checksum
            """,
            [broker.lower(), exchange.upper(), now, symbol_count, checksum],
        )
        logger.info(
            "MasterContractStatus: recorded sync %s/%s — %d symbols, checksum=%s",
            broker, exchange, symbol_count, checksum[:8],
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def last_sync(self, broker: str, exchange: str) -> datetime | None:
        """Return the UTC datetime of the last successful sync.

        Args:
            broker: Broker identifier.
            exchange: Exchange code.

        Returns:
            UTC-aware :class:`datetime` of the last sync, or ``None`` if
            no sync has been recorded.
        """
        row = self.connection.execute(
            "SELECT last_sync_utc FROM master_contract_status WHERE broker = ? AND exchange = ?",
            [broker.lower(), exchange.upper()],
        ).fetchone()
        if row is None:
            return None
        ts = row[0]
        if isinstance(ts, datetime):
            return ts.replace(tzinfo=timezone.utc)
        # DuckDB may return a string in some builds
        return datetime.fromisoformat(str(ts)).replace(tzinfo=timezone.utc)

    def needs_sync(
        self,
        broker: str,
        exchange: str,
        max_age_hours: int = 24,
    ) -> bool:
        """Return ``True`` if the contract data is stale or has never been synced.

        Args:
            broker: Broker identifier.
            exchange: Exchange code.
            max_age_hours: Age threshold in hours (default 24).

        Returns:
            ``True`` when the last sync is older than *max_age_hours* or absent.
        """
        last = self.last_sync(broker, exchange)
        if last is None:
            logger.debug("needs_sync(%s, %s): no prior sync", broker, exchange)
            return True

        age_hours = (datetime.now(tz=timezone.utc) - last).total_seconds() / 3600
        stale = age_hours > max_age_hours
        logger.debug(
            "needs_sync(%s, %s): age=%.1fh max=%dh → %s",
            broker, exchange, age_hours, max_age_hours, stale,
        )
        return stale

    def all_statuses(self) -> list[dict[str, Any]]:
        """Return all recorded sync statuses.

        Returns:
            List of dicts with keys ``broker``, ``exchange``,
            ``last_sync_utc``, ``symbol_count``, ``checksum``.
        """
        result = self.connection.execute(
            "SELECT broker, exchange, last_sync_utc, symbol_count, checksum"
            " FROM master_contract_status"
            " ORDER BY broker, exchange"
        )
        columns = [d[0] for d in result.description]
        rows = []
        for row in result.fetchall():
            entry: dict[str, Any] = dict(zip(columns, row))
            ts = entry.get("last_sync_utc")
            if isinstance(ts, datetime):
                entry["last_sync_utc"] = ts.replace(tzinfo=timezone.utc).isoformat()
            else:
                entry["last_sync_utc"] = str(ts)
            rows.append(entry)
        return rows

    def stale_contracts(self, max_age_hours: int = 24) -> list[dict[str, Any]]:
        """Return contracts that need re-syncing.

        Args:
            max_age_hours: Age threshold in hours.

        Returns:
            Subset of :meth:`all_statuses` where ``last_sync_utc`` is older
            than *max_age_hours*, plus all brokers/exchanges with no record.
        """
        now = datetime.now(tz=timezone.utc)
        stale = []
        for entry in self.all_statuses():
            ts_str = entry.get("last_sync_utc", "")
            try:
                last = datetime.fromisoformat(ts_str)
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                age_hours = (now - last).total_seconds() / 3600
                if age_hours > max_age_hours:
                    stale.append(entry)
            except (ValueError, TypeError):
                stale.append(entry)

        logger.debug(
            "stale_contracts(max_age_hours=%d): %d stale out of %d total",
            max_age_hours, len(stale), len(self.all_statuses()),
        )
        return stale


# ---------------------------------------------------------------------------
# Convenience checksum helper
# ---------------------------------------------------------------------------


def checksum_for_symbols(symbols: list[str]) -> str:
    """Compute a stable SHA-256 checksum for a list of symbol strings.

    Sorts the list before hashing so insertion order does not matter.

    Args:
        symbols: List of instrument symbol strings.

    Returns:
        Hex-encoded SHA-256 digest (64 chars).
    """
    content = "\n".join(sorted(symbols)).encode()
    return hashlib.sha256(content).hexdigest()
