"""Stock screener data cache — DuckDB-backed fundamental data store.

Caches stock fundamentals with 24-hour TTL. Provides filter/sort queries.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

logger = logging.getLogger("flinttrade.screener.stock_cache")

_DEFAULT_DB_PATH = "~/.flinttrade/screener_cache.duckdb"

# Columns permitted in ORDER BY to prevent SQL injection via ``sort_by``.
_VALID_SORT_COLUMNS: frozenset[str] = frozenset(
    {"market_cap", "pe_ratio", "pb_ratio", "roe", "roce", "dividend_yield", "symbol"}
)

_TTL_SECONDS: int = 86_400  # 24 hours


@dataclass
class StockFundamentals:
    """Fundamental data snapshot for a single stock.

    All ratio fields default to ``0.0`` so callers can safely skip fields
    that are unavailable (e.g., dividend yield for growth stocks).

    Attributes:
        symbol: NSE/BSE ticker (e.g. ``"RELIANCE"``).
        name: Display name (e.g. ``"Reliance Industries Ltd"``).
        exchange: Primary listing exchange (``"NSE"`` or ``"BSE"``).
        market_cap: Market capitalisation in INR crore.
        pe_ratio: Price-to-earnings ratio (TTM).
        pb_ratio: Price-to-book ratio.
        roe: Return on equity (%, TTM).
        roce: Return on capital employed (%, TTM).
        dividend_yield: Dividend yield (%).
        sector: SEBI sector classification.
        updated_at: Unix epoch when this row was last written.
    """

    symbol: str
    name: str
    exchange: str
    market_cap: float
    pe_ratio: float
    pb_ratio: float
    roe: float
    roce: float
    dividend_yield: float
    sector: str
    updated_at: float


class StockCache:
    """DuckDB cache for stock fundamental data.

    Each row expires after 24 hours (``updated_at`` TTL). Reads and writes
    use parameterised queries to prevent injection. ``sort_by`` is validated
    against a whitelist before being interpolated into ORDER BY.

    Usage::

        cache = StockCache()
        cache.upsert(StockFundamentals(
            symbol="RELIANCE", name="Reliance Industries", exchange="NSE",
            market_cap=1_800_000, pe_ratio=24.5, pb_ratio=2.1,
            roe=15.2, roce=13.8, dividend_yield=0.4,
            sector="Energy", updated_at=time.time(),
        ))
        stock = cache.get("RELIANCE")
        results = cache.scan(filters={"roce_gt": 15.0, "sector_eq": "IT"}, limit=20)
        cache.close()

    Args:
        db_path: Path to the DuckDB file. Tilde-expanded. Defaults to
            ``~/.flinttrade/screener_cache.duckdb``.
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        path = Path(db_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(path))
        self._init_table()
        logger.info("StockCache opened: %s", path)

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_table(self) -> None:
        """Create the fundamentals table if it does not already exist."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_fundamentals (
                symbol         VARCHAR PRIMARY KEY,
                name           VARCHAR,
                exchange       VARCHAR,
                market_cap     DOUBLE,
                pe_ratio       DOUBLE,
                pb_ratio       DOUBLE,
                roe            DOUBLE,
                roce           DOUBLE,
                dividend_yield DOUBLE,
                sector         VARCHAR,
                updated_at     DOUBLE
            )
        """)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def upsert(self, stock: StockFundamentals) -> None:
        """Insert or replace a stock's fundamentals.

        DuckDB does not support ``INSERT OR REPLACE`` in all versions, so
        this method deletes the existing row first, then inserts.

        Args:
            stock: Populated ``StockFundamentals`` dataclass.
        """
        self._conn.execute(
            "DELETE FROM stock_fundamentals WHERE symbol = ?",
            [stock.symbol],
        )
        self._conn.execute(
            """
            INSERT INTO stock_fundamentals
                (symbol, name, exchange, market_cap, pe_ratio, pb_ratio,
                 roe, roce, dividend_yield, sector, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                stock.symbol,
                stock.name,
                stock.exchange,
                stock.market_cap,
                stock.pe_ratio,
                stock.pb_ratio,
                stock.roe,
                stock.roce,
                stock.dividend_yield,
                stock.sector,
                stock.updated_at,
            ],
        )
        logger.debug("Upserted %s into stock_fundamentals", stock.symbol)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, symbol: str) -> StockFundamentals | None:
        """Fetch a stock by symbol if it exists and has not expired (24 h TTL).

        Args:
            symbol: Ticker to look up (case-sensitive).

        Returns:
            ``StockFundamentals`` instance, or ``None`` if absent or stale.
        """
        cutoff = time.time() - _TTL_SECONDS
        row = self._conn.execute(
            """
            SELECT symbol, name, exchange, market_cap, pe_ratio, pb_ratio,
                   roe, roce, dividend_yield, sector, updated_at
            FROM stock_fundamentals
            WHERE symbol = ? AND updated_at > ?
            """,
            [symbol, cutoff],
        ).fetchone()

        if row is None:
            return None
        return StockFundamentals(*row)

    def scan(
        self,
        filters: dict[str, Any] | None = None,
        sort_by: str = "market_cap",
        ascending: bool = False,
        limit: int = 50,
    ) -> list[StockFundamentals]:
        """Query stocks matching ``filters``, ordered by ``sort_by``.

        Only rows written within the last 24 hours are considered.

        Supported filter keys:

        - ``pe_lt``        — PE ratio less than value
        - ``pe_gt``        — PE ratio greater than value
        - ``pb_lt``        — PB ratio less than value
        - ``pb_gt``        — PB ratio greater than value
        - ``roce_gt``      — ROCE greater than value
        - ``roe_gt``       — ROE greater than value
        - ``sector_eq``    — Exact sector match
        - ``market_cap_gt``— Market cap greater than value (INR crore)
        - ``market_cap_lt``— Market cap less than value (INR crore)
        - ``exchange_eq``  — Exact exchange match (``"NSE"`` / ``"BSE"``)

        Args:
            filters: Optional mapping of filter key → threshold value.
            sort_by: Column to order results by. Must be one of the valid
                sort columns; invalid values fall back to ``"market_cap"``.
            ascending: ``True`` for ascending order, ``False`` for descending.
            limit: Maximum rows to return (capped server-side).

        Returns:
            List of ``StockFundamentals`` matching the criteria.
        """
        # Sanitise sort column against whitelist
        if sort_by not in _VALID_SORT_COLUMNS:
            logger.warning("Invalid sort_by=%r, falling back to market_cap", sort_by)
            sort_by = "market_cap"

        direction = "ASC" if ascending else "DESC"
        cutoff = time.time() - _TTL_SECONDS

        query = """
            SELECT symbol, name, exchange, market_cap, pe_ratio, pb_ratio,
                   roe, roce, dividend_yield, sector, updated_at
            FROM stock_fundamentals
            WHERE updated_at > ?
        """
        params: list[Any] = [cutoff]

        if filters:
            # Numeric range filters
            _numeric_filters: list[tuple[str, str, str]] = [
                ("pe_lt",         "pe_ratio",     "<"),
                ("pe_gt",         "pe_ratio",     ">"),
                ("pb_lt",         "pb_ratio",     "<"),
                ("pb_gt",         "pb_ratio",     ">"),
                ("roce_gt",       "roce",         ">"),
                ("roe_gt",        "roe",          ">"),
                ("market_cap_gt", "market_cap",   ">"),
                ("market_cap_lt", "market_cap",   "<"),
            ]
            for filter_key, column, operator in _numeric_filters:
                if filter_key in filters:
                    query += f" AND {column} {operator} ?"
                    params.append(filters[filter_key])

            # Exact-match string filters (parameterised — no injection risk)
            if "sector_eq" in filters:
                query += " AND sector = ?"
                params.append(filters["sector_eq"])
            if "exchange_eq" in filters:
                query += " AND exchange = ?"
                params.append(filters["exchange_eq"])

        # sort_by is validated against the whitelist above — safe to interpolate
        query += f" ORDER BY {sort_by} {direction} LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [StockFundamentals(*row) for row in rows]

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def purge_expired(self) -> int:
        """Delete all rows older than the 24-hour TTL.

        Returns:
            Number of rows deleted.
        """
        cutoff = time.time() - _TTL_SECONDS
        result = self._conn.execute(
            "DELETE FROM stock_fundamentals WHERE updated_at <= ? RETURNING symbol",
            [cutoff],
        ).fetchall()
        count = len(result)
        if count:
            logger.info("Purged %d expired rows from stock_fundamentals", count)
        return count

    def count(self) -> int:
        """Return the total number of rows currently in the cache (including expired)."""
        row = self._conn.execute("SELECT COUNT(*) FROM stock_fundamentals").fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        self._conn.close()
        logger.info("StockCache closed")

    def __enter__(self) -> StockCache:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
