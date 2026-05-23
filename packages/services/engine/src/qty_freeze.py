# packages/services/engine/src/qty_freeze.py
"""Quantity Freeze Manager — NSE/BSE per-symbol order size limits.

NSE and BSE publish quantity freeze limits (QF limits) that cap the
maximum quantity allowed in a single order for F&O instruments.
For example, NIFTY futures have a freeze limit of 1,800 contracts.
Oversized orders are rejected at the exchange level.

This module enforces QF limits *pre-placement* in the FlintTrade engine,
providing a clear error message before the order hits the exchange.

Freeze limits are refreshed daily from the exchange's master contract CSV
files.  The in-memory store is backed by DuckDB for persistence across
restarts.

CSV format (NSE freeze CSV)::

    SYMBOL,EXCHANGE,MAX_QTY
    NIFTY,NFO,1800
    BANKNIFTY,NFO,900
    FINNIFTY,NFO,1800

Usage::

    manager = QuantityFreezeManager()
    manager.load_from_csv(Path("nse_freeze_limits.csv"))

    valid, reason = manager.validate("NIFTY25APRFUT", "NFO", 2000)
    if not valid:
        print(reason)  # "Quantity 2000 exceeds freeze limit 1800 for NIFTY25APRFUT on NFO"

Admin routes::

    GET  /admin/freeze               — list all limits
    POST /admin/freeze               — set/update a limit
    GET  /admin/freeze/blocks        — recent blocked orders
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import duckdb

logger = logging.getLogger("flinttrade.engine.qty_freeze")

_DEFAULT_DB_PATH = Path.home() / ".flinttrade" / "qty_freeze.duckdb"

# Well-known NSE freeze defaults — used when no CSV is loaded.
# Source: NSE circular on F&O quantity limits (updated periodically).
_NSE_DEFAULTS: dict[tuple[str, str], int] = {
    ("NIFTY", "NFO"): 1800,
    ("BANKNIFTY", "NFO"): 900,
    ("FINNIFTY", "NFO"): 1800,
    ("MIDCPNIFTY", "NFO"): 2100,
    ("SENSEX", "BFO"): 500,
    ("BANKEX", "BFO"): 900,
}


# ---------------------------------------------------------------------------
# Blocked order record
# ---------------------------------------------------------------------------


@dataclass
class BlockedOrder:
    """A single order that was blocked by the freeze manager.

    Attributes:
        symbol: Instrument symbol.
        exchange: Exchange code.
        quantity: Requested quantity that exceeded the limit.
        limit: The freeze limit that was violated.
        blocked_at: ISO-8601 UTC timestamp.
    """

    symbol: str
    exchange: str
    quantity: int
    limit: int
    blocked_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        """Serialise to a plain dict for JSON API responses.

        Returns:
            Dict with symbol, exchange, quantity, limit, and blocked_at.
        """
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "quantity": self.quantity,
            "limit": self.limit,
            "blocked_at": self.blocked_at,
        }


# ---------------------------------------------------------------------------
# QuantityFreezeManager
# ---------------------------------------------------------------------------


class QuantityFreezeManager:
    """Manages per-symbol quantity freeze limits from exchange.

    Freeze limits are stored in DuckDB and kept in a hot in-memory dict for
    O(1) lookup during order placement.

    Attributes:
        _db_path: Path to the DuckDB file.
        _limits: In-memory cache mapping ``(symbol, exchange) → max_qty``.
        _blocked: In-memory list of recent blocked orders (capped at 1000).
    """

    _MAX_BLOCKS_MEMORY: int = 1000

    def __init__(self, db_path: Path | None = None) -> None:
        """Initialise the freeze manager.

        Loads existing limits from DuckDB into memory and seeds well-known
        NSE defaults if the table is empty.

        Args:
            db_path: Optional path to the DuckDB file.  Defaults to
                ``~/.flinttrade/qty_freeze.duckdb``.
        """
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._limits: dict[tuple[str, str], int] = {}
        self._blocked: list[BlockedOrder] = []
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._init_db()
        self._load_from_db()
        self._seed_defaults()

    # ------------------------------------------------------------------
    # DB lifecycle
    # ------------------------------------------------------------------

    @property
    def _db(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self._conn = duckdb.connect(str(self._db_path))
        return self._conn

    def _init_db(self) -> None:
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS freeze_limits (
                symbol        VARCHAR NOT NULL,
                exchange      VARCHAR NOT NULL,
                max_qty       INTEGER NOT NULL,
                updated_at    TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (symbol, exchange)
            )
        """)
        self._db.execute("""
            CREATE SEQUENCE IF NOT EXISTS blocked_orders_id_seq
        """)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS blocked_orders (
                id            INTEGER PRIMARY KEY DEFAULT nextval('blocked_orders_id_seq'),
                symbol        VARCHAR NOT NULL,
                exchange      VARCHAR NOT NULL,
                quantity      INTEGER NOT NULL,
                limit_val     INTEGER NOT NULL,
                blocked_at    TIMESTAMP DEFAULT NOW()
            )
        """)

    def _load_from_db(self) -> None:
        """Populate in-memory cache from DuckDB."""
        rows = self._db.execute(
            "SELECT symbol, exchange, max_qty FROM freeze_limits"
        ).fetchall()
        for symbol, exchange, max_qty in rows:
            self._limits[(symbol.upper(), exchange.upper())] = max_qty

    def _seed_defaults(self) -> None:
        """Insert well-known NSE defaults if the table is empty."""
        if self._limits:
            return
        for (symbol, exchange), max_qty in _NSE_DEFAULTS.items():
            self._write_limit(symbol, exchange, max_qty)
        logger.info("Seeded %d NSE default freeze limits", len(_NSE_DEFAULTS))

    def close(self) -> None:
        """Close the DuckDB connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_limit(self, symbol: str, exchange: str, max_qty_per_order: int) -> None:
        """Create or update the freeze limit for a symbol.

        Args:
            symbol: Instrument symbol (case-insensitive, stored uppercase).
            exchange: Exchange code (case-insensitive, stored uppercase).
            max_qty_per_order: Maximum allowed quantity per single order.

        Raises:
            ValueError: If *max_qty_per_order* is not a positive integer.
        """
        if max_qty_per_order <= 0:
            raise ValueError(
                f"max_qty_per_order must be positive, got {max_qty_per_order}"
            )
        self._write_limit(symbol.upper(), exchange.upper(), max_qty_per_order)
        logger.info(
            "Freeze limit set: %s/%s → %d",
            symbol.upper(), exchange.upper(), max_qty_per_order,
        )

    def get_limit(self, symbol: str, exchange: str) -> int | None:
        """Return the freeze limit for *symbol* on *exchange*, or ``None``.

        Args:
            symbol: Instrument symbol.
            exchange: Exchange code.

        Returns:
            Maximum quantity per order, or ``None`` if no limit is configured.
        """
        return self._limits.get((symbol.upper(), exchange.upper()))

    def validate(
        self,
        symbol: str,
        exchange: str,
        quantity: int,
    ) -> tuple[bool, str | None]:
        """Check whether *quantity* is within the freeze limit.

        Records a blocked order entry if the quantity exceeds the limit.

        Args:
            symbol: Instrument symbol.
            exchange: Exchange code.
            quantity: Quantity to validate.

        Returns:
            ``(True, None)`` if valid or no limit is configured.
            ``(False, reason)`` if the quantity exceeds the freeze limit.
        """
        sym = symbol.upper()
        exch = exchange.upper()
        limit = self._limits.get((sym, exch))

        if limit is None:
            # No limit configured — allow
            return True, None

        if quantity <= limit:
            return True, None

        reason = (
            f"Quantity {quantity} exceeds freeze limit {limit} "
            f"for {sym} on {exch}"
        )
        self._record_block(sym, exch, quantity, limit)
        logger.warning("Order BLOCKED by freeze manager: %s", reason)
        return False, reason

    def load_from_csv(self, csv_path: Path) -> int:
        """Load or update freeze limits from a CSV file.

        Expected CSV format::

            SYMBOL,EXCHANGE,MAX_QTY
            NIFTY,NFO,1800
            BANKNIFTY,NFO,900

        Rows with missing or non-numeric MAX_QTY are skipped with a warning.

        Args:
            csv_path: Path to the CSV file.

        Returns:
            Number of rows successfully loaded.

        Raises:
            FileNotFoundError: If *csv_path* does not exist.
            ValueError: If the CSV has no SYMBOL, EXCHANGE, or MAX_QTY column.
        """
        if not csv_path.exists():
            raise FileNotFoundError(f"Freeze CSV not found: {csv_path}")

        loaded = 0
        with csv_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames:
                raise ValueError("CSV file is empty or has no header row")

            # Normalise header names (case-insensitive)
            headers = [h.strip().upper() for h in (reader.fieldnames or [])]
            required = {"SYMBOL", "EXCHANGE", "MAX_QTY"}
            if not required.issubset(set(headers)):
                raise ValueError(
                    f"CSV must have columns: SYMBOL, EXCHANGE, MAX_QTY. "
                    f"Got: {reader.fieldnames}"
                )

            for row in reader:
                sym = row.get("SYMBOL", "").strip().upper()
                exch = row.get("EXCHANGE", "").strip().upper()
                raw_qty = row.get("MAX_QTY", "").strip()

                if not sym or not exch or not raw_qty:
                    logger.warning("Skipping incomplete CSV row: %s", row)
                    continue
                try:
                    max_qty = int(raw_qty)
                except ValueError:
                    logger.warning(
                        "Skipping row with non-numeric MAX_QTY=%s for %s/%s",
                        raw_qty, sym, exch,
                    )
                    continue
                if max_qty <= 0:
                    logger.warning(
                        "Skipping row with non-positive MAX_QTY=%d for %s/%s",
                        max_qty, sym, exch,
                    )
                    continue

                self._write_limit(sym, exch, max_qty)
                loaded += 1

        logger.info("Loaded %d freeze limits from %s", loaded, csv_path)
        return loaded

    def all_limits(self) -> list[dict]:
        """Return all configured freeze limits as a list of dicts.

        Returns:
            List of ``{symbol, exchange, max_qty}`` dicts, sorted by symbol.
        """
        return [
            {"symbol": sym, "exchange": exch, "max_qty": qty}
            for (sym, exch), qty in sorted(self._limits.items())
        ]

    def recent_blocks(self, limit: int = 50) -> list[dict]:
        """Return the most recent blocked orders.

        Queries DuckDB for persistence across restarts.

        Args:
            limit: Maximum number of records to return.

        Returns:
            List of block records as dicts, most recent first.
        """
        rows = self._db.execute(
            """
            SELECT symbol, exchange, quantity, limit_val, blocked_at
            FROM blocked_orders
            ORDER BY blocked_at DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()
        return [
            {
                "symbol": r[0],
                "exchange": r[1],
                "quantity": r[2],
                "limit": r[3],
                "blocked_at": str(r[4]),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _write_limit(self, symbol: str, exchange: str, max_qty: int) -> None:
        """Upsert a limit into DuckDB and update the in-memory cache.

        Args:
            symbol: Uppercase symbol.
            exchange: Uppercase exchange.
            max_qty: Freeze limit value.
        """
        self._db.execute(
            """
            INSERT INTO freeze_limits (symbol, exchange, max_qty, updated_at)
            VALUES (?, ?, ?, NOW())
            ON CONFLICT (symbol, exchange) DO UPDATE SET
                max_qty    = excluded.max_qty,
                updated_at = excluded.updated_at
            """,
            [symbol, exchange, max_qty],
        )
        self._limits[(symbol, exchange)] = max_qty

    def _record_block(
        self,
        symbol: str,
        exchange: str,
        quantity: int,
        limit: int,
    ) -> None:
        """Record a blocked order in memory and DuckDB.

        Args:
            symbol: Uppercase symbol.
            exchange: Uppercase exchange.
            quantity: Quantity that was blocked.
            limit: The freeze limit that was violated.
        """
        blocked = BlockedOrder(
            symbol=symbol,
            exchange=exchange,
            quantity=quantity,
            limit=limit,
        )
        # Cap in-memory list
        self._blocked.append(blocked)
        if len(self._blocked) > self._MAX_BLOCKS_MEMORY:
            self._blocked = self._blocked[-self._MAX_BLOCKS_MEMORY :]

        self._db.execute(
            """
            INSERT INTO blocked_orders (symbol, exchange, quantity, limit_val, blocked_at)
            VALUES (?, ?, ?, ?, NOW())
            """,
            [symbol, exchange, quantity, limit],
        )
