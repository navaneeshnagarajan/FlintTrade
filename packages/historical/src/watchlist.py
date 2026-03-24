"""Historify Watchlist: auto-download OHLCV data for tracked symbols.

Maintains a persistent list of (symbol, exchange, interval) items
in SQLite.  The scheduler calls :meth:`DownloadWatchlist.get_enabled`
and downloads OHLCV data for each item via the
:class:`~packages.historical.src.downloader.HistoricalDownloader`.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("flinttrade.historical.watchlist")

_DDL = """
CREATE TABLE IF NOT EXISTS watchlist (
    symbol      TEXT NOT NULL,
    exchange    TEXT NOT NULL,
    interval    TEXT NOT NULL DEFAULT '1d',
    enabled     INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (symbol, exchange)
)
"""


@dataclass
class WatchlistItem:
    """A single entry in the download watchlist."""

    symbol: str
    exchange: str
    interval: str = "1d"
    enabled: bool = True


class DownloadWatchlist:
    """Persistent watchlist for scheduled OHLCV downloads.

    Stores items in an SQLite database so they survive restarts.
    The download trigger (``/ft-api/v1/historify/download``) iterates
    only over enabled items.

    Args:
        db_path: Path to the SQLite database file.  The parent directory
                 is created if it does not exist.

    Example::

        wl = DownloadWatchlist(Path.home() / ".flinttrade" / "watchlist.db")
        wl.add("NIFTY", "NSE_INDEX", "1d")
        wl.add("RELIANCE", "NSE", "15m")
        enabled = wl.get_enabled()
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_DDL)
        self._conn.commit()
        logger.info("DownloadWatchlist: SQLite at %s", db_path)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(
        self,
        symbol: str,
        exchange: str,
        interval: str = "1d",
    ) -> WatchlistItem:
        """Add a symbol to the watchlist (or update interval if it exists).

        Args:
            symbol: Instrument symbol, e.g. ``"RELIANCE"``.
            exchange: Exchange code, e.g. ``"NSE"``.
            interval: OHLCV interval, e.g. ``"1d"``, ``"15m"``.

        Returns:
            The created or updated :class:`WatchlistItem`.
        """
        self._conn.execute(
            """
            INSERT INTO watchlist (symbol, exchange, interval, enabled)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(symbol, exchange) DO UPDATE SET
                interval = excluded.interval,
                enabled  = 1
            """,
            (symbol.upper(), exchange.upper(), interval),
        )
        self._conn.commit()
        item = WatchlistItem(symbol=symbol.upper(), exchange=exchange.upper(), interval=interval, enabled=True)
        logger.info("Watchlist: added %s/%s interval=%s", symbol, exchange, interval)
        return item

    def remove(self, symbol: str, exchange: str) -> None:
        """Remove a symbol from the watchlist.

        Args:
            symbol: Instrument symbol.
            exchange: Exchange code.
        """
        self._conn.execute(
            "DELETE FROM watchlist WHERE symbol = ? AND exchange = ?",
            (symbol.upper(), exchange.upper()),
        )
        self._conn.commit()
        logger.info("Watchlist: removed %s/%s", symbol, exchange)

    def list_items(self) -> list[WatchlistItem]:
        """Return all watchlist items (enabled and disabled).

        Returns:
            List of :class:`WatchlistItem` in insertion order.
        """
        rows = self._conn.execute(
            "SELECT symbol, exchange, interval, enabled FROM watchlist"
        ).fetchall()
        return [
            WatchlistItem(
                symbol=row["symbol"],
                exchange=row["exchange"],
                interval=row["interval"],
                enabled=bool(row["enabled"]),
            )
            for row in rows
        ]

    def toggle(self, symbol: str, exchange: str, enabled: bool) -> None:
        """Enable or disable a watchlist item.

        Args:
            symbol: Instrument symbol.
            exchange: Exchange code.
            enabled: ``True`` to enable, ``False`` to disable.
        """
        self._conn.execute(
            "UPDATE watchlist SET enabled = ? WHERE symbol = ? AND exchange = ?",
            (1 if enabled else 0, symbol.upper(), exchange.upper()),
        )
        self._conn.commit()
        state = "enabled" if enabled else "disabled"
        logger.info("Watchlist: %s %s/%s", state, symbol, exchange)

    def get_enabled(self) -> list[WatchlistItem]:
        """Return only the enabled watchlist items.

        Returns:
            List of :class:`WatchlistItem` with ``enabled=True``.
        """
        rows = self._conn.execute(
            "SELECT symbol, exchange, interval FROM watchlist WHERE enabled = 1"
        ).fetchall()
        return [
            WatchlistItem(
                symbol=row["symbol"],
                exchange=row["exchange"],
                interval=row["interval"],
                enabled=True,
            )
            for row in rows
        ]

    def close(self) -> None:
        """Close the SQLite connection."""
        try:
            self._conn.close()
        except Exception:
            pass
