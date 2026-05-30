"""P&L Tracker: real-time tradebook P&L time series.

Reads tradebook, computes realized P&L per trade, uses current LTP
for unrealized MTM. Stores time series in DuckDB for intraday charting.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.journal.pnl_tracker")


@dataclass
class PnLPoint:
    """A single P&L snapshot in the time series."""

    timestamp: float
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    trade_count: int


class PnLTracker:
    """Real-time P&L time series tracker.

    Computes realized P&L from closed trades and unrealized MTM from
    open positions using live LTP prices.  Stores an in-memory time series
    for intraday charting; optionally persists to DuckDB.

    Args:
        db_path: Optional path to a DuckDB file for persistence.
                 Pass ``None`` (default) to run purely in-memory.

    Example::

        tracker = PnLTracker()
        trades = [
            {"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY",
             "quantity": 10, "price": 2500.0, "entry_price": 2500.0,
             "exit_price": 2520.0},
        ]
        positions = [
            {"symbol": "INFY", "exchange": "NSE", "quantity": 5,
             "average_price": 1800.0, "product": "MIS"},
        ]
        ltp_map = {"NSE:INFY": 1820.0}
        point = tracker.update(trades, positions, ltp_map)
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._series: list[PnLPoint] = []
        self._db_path = db_path
        self._conn: Any = None

        if db_path is not None:
            self._init_db(db_path)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _init_db(self, db_path: Path) -> None:
        """Initialise DuckDB connection and create pnl_series table."""
        try:
            import duckdb  # type: ignore[import]

            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = duckdb.connect(str(db_path))
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS pnl_series (
                    timestamp       DOUBLE NOT NULL,
                    realized_pnl    DOUBLE NOT NULL,
                    unrealized_pnl  DOUBLE NOT NULL,
                    total_pnl       DOUBLE NOT NULL,
                    trade_count     INTEGER NOT NULL
                )
            """)
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pnl_series_ts ON pnl_series (timestamp)"
            )
            logger.info("PnLTracker: DuckDB initialised at %s", db_path)
        except Exception as exc:
            logger.warning("PnLTracker: DuckDB init failed (%s); running in-memory only", exc)
            self._conn = None

    def _persist(self, point: PnLPoint) -> None:
        """Persist a P&L point to DuckDB if available."""
        if self._conn is None:
            return
        try:
            self._conn.execute(
                """
                INSERT INTO pnl_series
                    (timestamp, realized_pnl, unrealized_pnl, total_pnl, trade_count)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    point.timestamp,
                    point.realized_pnl,
                    point.unrealized_pnl,
                    point.total_pnl,
                    point.trade_count,
                ],
            )
        except Exception as exc:
            logger.warning("PnLTracker: failed to persist point: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        trades: list[dict[str, Any]],
        positions: list[dict[str, Any]],
        ltp_map: dict[str, float],
    ) -> PnLPoint:
        """Compute a new P&L snapshot and append it to the time series.

        Realized P&L comes from completed trades that carry both
        ``entry_price`` and ``exit_price``.  Unrealized MTM is computed
        from open positions using the ``ltp_map``.

        Args:
            trades: List of trade dicts.  Each dict may contain:
                ``action`` (str), ``quantity`` (int/float),
                ``entry_price`` (float), ``exit_price`` (float).
            positions: List of position dicts.  Each dict should contain:
                ``symbol`` (str), ``exchange`` (str),
                ``quantity`` (int/float), ``average_price`` (float).
            ltp_map: Mapping of ``"EXCHANGE:SYMBOL"`` (or ``"SYMBOL"``)
                to current LTP.

        Returns:
            The newly created :class:`PnLPoint`.
        """
        realized = 0.0
        trade_count = 0

        for trade in trades:
            entry = trade.get("entry_price")
            exit_ = trade.get("exit_price")
            qty = float(trade.get("quantity", 0))
            action = str(trade.get("action", "BUY")).upper()
            if entry is not None and exit_ is not None and qty > 0:
                if action == "BUY":
                    realized += (float(exit_) - float(entry)) * qty
                else:
                    realized += (float(entry) - float(exit_)) * qty
                trade_count += 1

        unrealized = 0.0
        for pos in positions:
            symbol = str(pos.get("symbol", ""))
            exchange = str(pos.get("exchange", ""))
            qty = float(pos.get("quantity", 0))
            avg_price = float(pos.get("average_price", 0.0))

            if qty == 0:
                continue

            # Try "EXCHANGE:SYMBOL" key first, fall back to bare symbol
            ltp = ltp_map.get(f"{exchange}:{symbol}") or ltp_map.get(symbol)
            if ltp is not None and avg_price > 0:
                unrealized += (float(ltp) - avg_price) * qty

        total = realized + unrealized
        point = PnLPoint(
            timestamp=time.time(),
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            total_pnl=total,
            trade_count=trade_count,
        )
        self._series.append(point)
        self._persist(point)
        logger.debug(
            "PnL update: realized=%.2f unrealized=%.2f total=%.2f trades=%d",
            realized, unrealized, total, trade_count,
        )
        return point

    def get_series(self, since: float | None = None) -> list[PnLPoint]:
        """Return the P&L time series, optionally filtered by timestamp.

        Args:
            since: Unix timestamp.  If provided, only points with
                ``timestamp >= since`` are returned.

        Returns:
            List of :class:`PnLPoint` in chronological order.
        """
        if since is None:
            return list(self._series)
        return [p for p in self._series if p.timestamp >= since]

    def get_summary(self) -> dict[str, Any]:
        """Return a summary dict of the current P&L state.

        Returns:
            Dict with keys: ``realized``, ``unrealized``, ``total``,
            ``max_total``, ``min_total``, ``trade_count``, ``data_points``.
        """
        if not self._series:
            return {
                "realized": 0.0,
                "unrealized": 0.0,
                "total": 0.0,
                "max_total": 0.0,
                "min_total": 0.0,
                "trade_count": 0,
                "data_points": 0,
            }

        latest = self._series[-1]
        totals = [p.total_pnl for p in self._series]
        return {
            "realized": latest.realized_pnl,
            "unrealized": latest.unrealized_pnl,
            "total": latest.total_pnl,
            "max_total": max(totals),
            "min_total": min(totals),
            "trade_count": latest.trade_count,
            "data_points": len(self._series),
        }

    def reset(self) -> None:
        """Clear the in-memory time series (does not truncate DuckDB table)."""
        self._series.clear()
        logger.info("PnLTracker: series reset")

    def close(self) -> None:
        """Close the DuckDB connection if open."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                logger.exception("Failed to close DuckDB connection in PnLTracker")
            self._conn = None
