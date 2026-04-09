"""Position tracker with R-multiple accounting and DuckDB persistence.

Tracks open and closed positions across multiple strategies simultaneously,
calculates cumulative P&L (realised + unrealised), enforces per-strategy
position limits, and persists state to DuckDB for crash recovery.

Absorbed from: nifty-trading-railway/baseline_v1_live/position_tracker.py
Redesigned for FlintTrade's multi-strategy, DuckDB-first architecture:
- No hardcoded strategy names or instrument filters
- DuckDB persistence (not SQLite)
- Pydantic models for data structures
- Thread-safe state updates
- MTM square-off at configurable intraday loss limit
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("flinttrade.engine.position_tracker")


# ---------------------------------------------------------------------------
# IST helper (no hard dep on pytz — use stdlib zoneinfo when available)
# ---------------------------------------------------------------------------


def _now_ist() -> datetime:
    """Return current datetime in IST (Asia/Kolkata)."""
    try:
        from zoneinfo import ZoneInfo  # Python 3.9+

        return datetime.now(ZoneInfo("Asia/Kolkata"))
    except Exception:
        return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_ist().isoformat()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class PositionRecord(BaseModel):
    """Immutable snapshot of a position for persistence / API serialisation.

    Attributes:
        strategy_id:    Owning strategy instance UUID.
        symbol:         Instrument symbol (e.g. ``NIFTY30DEC2523500CE``).
        exchange:       Exchange code (``NFO``, ``NSE``, ``MCX``, etc.).
        direction:      ``BUY`` (long) or ``SELL`` (short).
        entry_price:    Fill price at entry.
        sl_price:       Stop-loss reference price used for R calculation.
        quantity:       Total lots / shares.
        entry_time:     ISO-8601 string.
        current_price:  Last known market price.
        unrealised_pnl: Mark-to-market P&L (open position).
        exit_price:     Fill price at exit. ``None`` while open.
        exit_time:      ISO-8601 string. ``None`` while open.
        exit_reason:    Human-readable reason code (e.g. ``SL_HIT``, ``MTM_LIMIT``).
        realised_pnl:   Final P&L (set on close).
        is_closed:      ``True`` once the position is fully exited.
        metadata:       Free-form dict for strategy-specific context.
    """

    strategy_id: str
    symbol: str
    exchange: str = "NSE"
    direction: str = "BUY"  # "BUY" or "SELL"
    entry_price: float
    sl_price: float
    quantity: int
    entry_time: str = Field(default_factory=_now_iso)
    current_price: float = 0.0
    unrealised_pnl: float = 0.0
    exit_price: float | None = None
    exit_time: str | None = None
    exit_reason: str | None = None
    realised_pnl: float = 0.0
    is_closed: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def risk_per_unit(self) -> float:
        """Absolute risk per unit based on entry vs stop-loss."""
        return abs(self.entry_price - self.sl_price)

    @property
    def actual_r(self) -> float:
        """Total monetary risk for this position (risk_per_unit × quantity)."""
        return self.risk_per_unit * self.quantity

    @property
    def unrealised_r(self) -> float:
        """Unrealised P&L expressed as R-multiples."""
        return self.unrealised_pnl / self.actual_r if self.actual_r > 0 else 0.0

    @property
    def realised_r(self) -> float:
        """Realised P&L expressed as R-multiples."""
        return self.realised_pnl / self.actual_r if self.actual_r > 0 else 0.0

    @property
    def max_loss_so_far(self) -> float:
        """Worst (most negative) P&L seen; for open positions uses unrealised."""
        if self.is_closed:
            return min(self.realised_pnl, 0.0)
        return min(self.unrealised_pnl, 0.0)


# ---------------------------------------------------------------------------
# Internal mutable position — NOT Pydantic (mutated in hot path)
# ---------------------------------------------------------------------------


@dataclass
class _LivePosition:
    """Mutable runtime position object. Converted to PositionRecord for I/O."""

    strategy_id: str
    symbol: str
    exchange: str
    direction: str
    entry_price: float
    sl_price: float
    quantity: int
    entry_time: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    current_price: float = 0.0
    unrealised_pnl: float = 0.0
    peak_pnl: float = 0.0       # Highest unrealised P&L (for max-drawdown tracking)
    trough_pnl: float = 0.0     # Lowest unrealised P&L (for max-drawdown tracking)

    exit_price: float | None = None
    exit_time: datetime | None = None
    exit_reason: str | None = None
    realised_pnl: float = 0.0
    is_closed: bool = False

    def update_price(self, price: float) -> None:
        """Update mark-to-market price and recalculate unrealised P&L."""
        self.current_price = price
        if self.direction == "SELL":
            # Short: profit when price falls
            self.unrealised_pnl = (self.entry_price - price) * self.quantity
        else:
            # Long: profit when price rises
            self.unrealised_pnl = (price - self.entry_price) * self.quantity

        if self.unrealised_pnl > self.peak_pnl:
            self.peak_pnl = self.unrealised_pnl
        if self.unrealised_pnl < self.trough_pnl:
            self.trough_pnl = self.unrealised_pnl

    def close(self, exit_price: float, reason: str) -> None:
        """Mark position as closed and calculate realised P&L."""
        self.exit_price = exit_price
        self.exit_time = _now_ist()
        self.exit_reason = reason
        if self.direction == "SELL":
            self.realised_pnl = (self.entry_price - exit_price) * self.quantity
        else:
            self.realised_pnl = (exit_price - self.entry_price) * self.quantity
        self.is_closed = True

    @property
    def actual_r(self) -> float:
        return abs(self.entry_price - self.sl_price) * self.quantity

    @property
    def unrealised_r(self) -> float:
        return self.unrealised_pnl / self.actual_r if self.actual_r > 0 else 0.0

    @property
    def realised_r(self) -> float:
        return self.realised_pnl / self.actual_r if self.actual_r > 0 else 0.0

    @property
    def max_drawdown(self) -> float:
        """Maximum adverse excursion (always <= 0)."""
        return self.trough_pnl

    def to_record(self) -> PositionRecord:
        """Snapshot as a PositionRecord for persistence / API."""
        return PositionRecord(
            strategy_id=self.strategy_id,
            symbol=self.symbol,
            exchange=self.exchange,
            direction=self.direction,
            entry_price=self.entry_price,
            sl_price=self.sl_price,
            quantity=self.quantity,
            entry_time=self.entry_time.isoformat(),
            current_price=self.current_price,
            unrealised_pnl=self.unrealised_pnl,
            exit_price=self.exit_price,
            exit_time=self.exit_time.isoformat() if self.exit_time else None,
            exit_reason=self.exit_reason,
            realised_pnl=self.realised_pnl,
            is_closed=self.is_closed,
            metadata=dict(self.metadata),
        )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PositionTrackerError(Exception):
    """Base exception for PositionTracker."""


class PositionAlreadyExistsError(PositionTrackerError):
    """Raised when trying to open a duplicate position for the same symbol/strategy."""


class PositionNotFoundError(PositionTrackerError):
    """Raised when a position cannot be found."""


class PositionLimitExceededError(PositionTrackerError):
    """Raised when adding a position would breach a configured limit."""


# ---------------------------------------------------------------------------
# DuckDB schema helpers
# ---------------------------------------------------------------------------

_CREATE_POSITIONS_TABLE = """
CREATE TABLE IF NOT EXISTS ft_positions (
    strategy_id   VARCHAR  NOT NULL,
    symbol        VARCHAR  NOT NULL,
    exchange      VARCHAR  NOT NULL,
    direction     VARCHAR  NOT NULL,
    entry_price   DOUBLE   NOT NULL,
    sl_price      DOUBLE   NOT NULL,
    quantity      INTEGER  NOT NULL,
    entry_time    VARCHAR  NOT NULL,
    current_price DOUBLE   DEFAULT 0.0,
    unrealised_pnl DOUBLE  DEFAULT 0.0,
    exit_price    DOUBLE,
    exit_time     VARCHAR,
    exit_reason   VARCHAR,
    realised_pnl  DOUBLE   DEFAULT 0.0,
    is_closed     BOOLEAN  DEFAULT FALSE,
    metadata      VARCHAR  DEFAULT '{}',
    PRIMARY KEY (strategy_id, symbol)
)
"""

_UPSERT_POSITION = """
INSERT OR REPLACE INTO ft_positions
    (strategy_id, symbol, exchange, direction, entry_price, sl_price,
     quantity, entry_time, current_price, unrealised_pnl, exit_price,
     exit_time, exit_reason, realised_pnl, is_closed, metadata)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


# ---------------------------------------------------------------------------
# PositionTracker
# ---------------------------------------------------------------------------


class PositionTracker:
    """Track open and closed positions across multiple strategies.

    Features:

    * Per-strategy position maps with optional max-position limits.
    * Aggregate portfolio P&L (realised + unrealised).
    * MTM square-off trigger when aggregate unrealised loss breaches a limit.
    * DuckDB persistence for crash recovery.
    * Thread-safe: all mutations acquire a ``threading.Lock``.

    Args:
        db_path:          Path to the DuckDB file. Defaults to ``":memory:"``.
                          Pass a real path (e.g. ``"~/.flinttrade/engine.duckdb"``)
                          for production use.
        max_positions:    Maximum concurrent open positions across all strategies.
                          ``None`` disables the global limit.
        mtm_loss_limit:   If aggregate unrealised P&L drops below this (negative)
                          value, ``check_mtm_limit()`` returns ``True``.
                          ``None`` disables MTM square-off.

    Example::

        tracker = PositionTracker(db_path="~/.flinttrade/engine.duckdb")
        tracker.open(
            strategy_id="abc-123",
            symbol="NIFTY30DEC2523500CE",
            exchange="NFO",
            direction="SELL",
            entry_price=250.0,
            sl_price=260.0,
            quantity=50,
        )
        tracker.update_price("NIFTY30DEC2523500CE", "abc-123", 245.0)
        tracker.close("NIFTY30DEC2523500CE", "abc-123", 240.0, "SL_HIT")
    """

    def __init__(
        self,
        db_path: str = ":memory:",
        max_positions: int | None = None,
        mtm_loss_limit: float | None = None,
    ) -> None:
        self._db_path = db_path
        self._max_positions = max_positions
        self._mtm_loss_limit = mtm_loss_limit

        # {strategy_id: {symbol: _LivePosition}}
        self._open: dict[str, dict[str, _LivePosition]] = {}
        # {strategy_id: [_LivePosition, ...]}
        self._closed: dict[str, list[_LivePosition]] = {}

        self._lock = threading.Lock()
        self._db_lock = threading.Lock()
        self._conn: Any = None  # duckdb.DuckDBPyConnection

        self._init_db()
        self._recover()

        logger.info(
            "PositionTracker ready [db=%s, max_positions=%s, mtm_limit=%s]",
            db_path, max_positions, mtm_loss_limit,
        )

    # ------------------------------------------------------------------
    # Database initialisation & recovery
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Open DuckDB connection and create schema if needed."""
        try:
            import duckdb

            self._conn = duckdb.connect(self._db_path)
            self._conn.execute(_CREATE_POSITIONS_TABLE)
        except ImportError:
            logger.warning(
                "duckdb not installed — position persistence disabled. "
                "Install with: pip install duckdb"
            )
            self._conn = None

    def _recover(self) -> None:
        """Reload last-known open positions from DuckDB on startup."""
        if self._conn is None:
            return
        try:
            rows = self._conn.execute(
                "SELECT strategy_id, symbol, exchange, direction, entry_price, "
                "sl_price, quantity, entry_time, current_price, unrealised_pnl, metadata "
                "FROM ft_positions WHERE is_closed = FALSE"
            ).fetchall()

            recovered = 0
            for row in rows:
                (
                    strategy_id, symbol, exchange, direction,
                    entry_price, sl_price, quantity, entry_time_str,
                    current_price, unrealised_pnl, metadata_str,
                ) = row

                try:
                    entry_time = datetime.fromisoformat(entry_time_str)
                except (ValueError, TypeError):
                    entry_time = _now_ist()

                import json as _json
                try:
                    metadata = _json.loads(metadata_str or "{}")
                except Exception:
                    metadata = {}

                pos = _LivePosition(
                    strategy_id=strategy_id,
                    symbol=symbol,
                    exchange=exchange,
                    direction=direction,
                    entry_price=entry_price,
                    sl_price=sl_price,
                    quantity=quantity,
                    entry_time=entry_time,
                    metadata=metadata,
                    current_price=current_price,
                    unrealised_pnl=unrealised_pnl,
                )
                if strategy_id not in self._open:
                    self._open[strategy_id] = {}
                self._open[strategy_id][symbol] = pos
                recovered += 1

            if recovered:
                logger.info("[RECOVERY] Reloaded %d open position(s) from DuckDB.", recovered)
        except Exception as exc:
            logger.error("[RECOVERY] Failed to reload positions: %s", exc, exc_info=True)

    def _persist(self, pos: _LivePosition) -> None:
        """Upsert a single position to DuckDB.

        Acquires ``_db_lock`` internally so it is safe to call from any thread
        while holding ``_lock``.  DuckDB connections are not thread-safe, so
        all ``_conn.execute`` calls must be serialised through ``_db_lock``.
        """
        if self._conn is None:
            return
        import json as _json

        try:
            with self._db_lock:
                self._conn.execute(
                    _UPSERT_POSITION,
                    [
                        pos.strategy_id,
                        pos.symbol,
                        pos.exchange,
                        pos.direction,
                        pos.entry_price,
                        pos.sl_price,
                        pos.quantity,
                        pos.entry_time.isoformat(),
                        pos.current_price,
                        pos.unrealised_pnl,
                        pos.exit_price,
                        pos.exit_time.isoformat() if pos.exit_time else None,
                        pos.exit_reason,
                        pos.realised_pnl,
                        pos.is_closed,
                        _json.dumps(pos.metadata),
                    ],
                )
        except Exception as exc:
            logger.error("[DB] Failed to persist position %s/%s: %s", pos.strategy_id, pos.symbol, exc)

    # ------------------------------------------------------------------
    # Open
    # ------------------------------------------------------------------

    def open(
        self,
        strategy_id: str,
        symbol: str,
        exchange: str,
        direction: str,
        entry_price: float,
        sl_price: float,
        quantity: int,
        metadata: dict[str, Any] | None = None,
    ) -> _LivePosition:
        """Open a new position.

        Args:
            strategy_id:  Owning strategy instance UUID.
            symbol:       Instrument symbol.
            exchange:     Exchange code.
            direction:    ``"BUY"`` or ``"SELL"``.
            entry_price:  Fill price.
            sl_price:     Stop-loss price (used for R calculation only).
            quantity:     Number of units.
            metadata:     Optional strategy-specific context dict.

        Returns:
            The newly created ``_LivePosition``.

        Raises:
            PositionAlreadyExistsError: Duplicate symbol/strategy combination.
            PositionLimitExceededError: Global max_positions would be exceeded.
        """
        with self._lock:
            existing = self._open.get(strategy_id, {})
            if symbol in existing:
                raise PositionAlreadyExistsError(
                    f"Position already open for strategy={strategy_id} symbol={symbol}"
                )

            total_open = sum(len(v) for v in self._open.values())
            if self._max_positions is not None and total_open >= self._max_positions:
                raise PositionLimitExceededError(
                    f"Max {self._max_positions} positions reached (currently {total_open})"
                )

            pos = _LivePosition(
                strategy_id=strategy_id,
                symbol=symbol,
                exchange=exchange,
                direction=direction,
                entry_price=entry_price,
                sl_price=sl_price,
                quantity=quantity,
                entry_time=_now_ist(),
                current_price=entry_price,
                metadata=dict(metadata or {}),
            )

            if strategy_id not in self._open:
                self._open[strategy_id] = {}
            self._open[strategy_id][symbol] = pos
            self._persist(pos)

        logger.info(
            "[OPEN] %s %s @ %.2f  qty=%d  sl=%.2f  strategy=%s",
            direction, symbol, entry_price, quantity, sl_price, strategy_id[:8],
        )
        return pos

    # ------------------------------------------------------------------
    # Update price
    # ------------------------------------------------------------------

    def update_price(
        self,
        symbol: str,
        strategy_id: str,
        price: float,
    ) -> None:
        """Update the mark-to-market price for one position.

        Args:
            symbol:       Instrument symbol.
            strategy_id:  Owning strategy UUID.
            price:        Latest market price.
        """
        with self._lock:
            pos = self._open.get(strategy_id, {}).get(symbol)
            if pos is None:
                return
            pos.update_price(price)
            self._persist(pos)

    def update_prices_bulk(self, prices: dict[str, float], strategy_id: str | None = None) -> None:
        """Update prices for multiple symbols at once.

        Args:
            prices:       Mapping of ``{symbol: price}``.
            strategy_id:  If provided, only update positions for this strategy.
                          If ``None``, match symbol across ALL strategies.
        """
        with self._lock:
            if strategy_id is not None:
                strat_positions = self._open.get(strategy_id, {})
                for symbol, price in prices.items():
                    if symbol in strat_positions:
                        strat_positions[symbol].update_price(price)
                        self._persist(strat_positions[symbol])
            else:
                for strat_positions in self._open.values():
                    for symbol, price in prices.items():
                        if symbol in strat_positions:
                            strat_positions[symbol].update_price(price)
                            self._persist(strat_positions[symbol])

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def close(
        self,
        symbol: str,
        strategy_id: str,
        exit_price: float,
        reason: str,
    ) -> _LivePosition:
        """Close a single position.

        Args:
            symbol:       Instrument symbol.
            strategy_id:  Owning strategy UUID.
            exit_price:   Fill price at exit.
            reason:       Human-readable reason code (e.g. ``"SL_HIT"``).

        Returns:
            The closed ``_LivePosition``.

        Raises:
            PositionNotFoundError: If the position does not exist.
        """
        with self._lock:
            strat_positions = self._open.get(strategy_id, {})
            pos = strat_positions.get(symbol)
            if pos is None:
                raise PositionNotFoundError(
                    f"No open position for strategy={strategy_id} symbol={symbol}"
                )

            pos.close(exit_price, reason)
            del strat_positions[symbol]

            if strategy_id not in self._closed:
                self._closed[strategy_id] = []
            self._closed[strategy_id].append(pos)
            self._persist(pos)

        logger.info(
            "[CLOSE] %s @ %.2f  pnl=%.2f  reason=%s  strategy=%s",
            symbol, exit_price, pos.realised_pnl, reason, strategy_id[:8],
        )
        return pos

    def close_all(
        self,
        exit_prices: dict[str, float],
        reason: str,
        strategy_id: str | None = None,
    ) -> list[_LivePosition]:
        """Close all open positions (or all for one strategy).

        Args:
            exit_prices:  Mapping ``{symbol: price}``. Missing prices fall back
                          to last known price.
            reason:       Exit reason code (e.g. ``"MTM_LIMIT"``, ``"EOD_EXIT"``).
            strategy_id:  If provided, only close this strategy's positions.

        Returns:
            List of closed ``_LivePosition`` objects.
        """
        closed: list[_LivePosition] = []

        # Snapshot the (sid, symbol, current_price) triples under the lock so
        # the iteration is not racing with concurrent open/close calls.
        with self._lock:
            if strategy_id:
                to_close = [
                    (strategy_id, sym, pos.current_price)
                    for sym, pos in self._open.get(strategy_id, {}).items()
                ]
            else:
                to_close = [
                    (sid, sym, pos.current_price)
                    for sid, positions in self._open.items()
                    for sym, pos in positions.items()
                ]

        for sid, symbol, fallback_price in to_close:
            price = exit_prices.get(symbol, fallback_price)
            try:
                closed.append(self.close(symbol, sid, price, reason))
            except PositionNotFoundError:
                pass  # Already closed by a concurrent call

        logger.info(
            "[CLOSE_ALL] Closed %d positions | reason=%s | strategy=%s",
            len(closed), reason, strategy_id or "ALL",
        )
        return closed

    # ------------------------------------------------------------------
    # MTM limit check
    # ------------------------------------------------------------------

    def check_mtm_limit(self) -> bool:
        """Return ``True`` if aggregate unrealised P&L has breached the MTM limit.

        The MTM loss limit is the absolute intraday loss threshold. If
        ``mtm_loss_limit`` was not set at construction, always returns ``False``.

        Returns:
            ``True`` if square-off should be triggered.
        """
        if self._mtm_loss_limit is None:
            return False
        total_unrealised = self.portfolio_unrealised_pnl()
        if total_unrealised <= self._mtm_loss_limit:
            logger.warning(
                "[MTM] Loss limit breached: unrealised_pnl=%.2f <= limit=%.2f",
                total_unrealised, self._mtm_loss_limit,
            )
            return True
        return False

    # ------------------------------------------------------------------
    # Portfolio aggregates
    # ------------------------------------------------------------------

    def portfolio_realised_pnl(self, strategy_id: str | None = None) -> float:
        """Sum of all closed-position realised P&L.

        Args:
            strategy_id: Scope to one strategy. ``None`` for all.
        """
        with self._lock:
            if strategy_id:
                return sum(p.realised_pnl for p in self._closed.get(strategy_id, []))
            return sum(
                p.realised_pnl
                for positions in self._closed.values()
                for p in positions
            )

    def portfolio_unrealised_pnl(self, strategy_id: str | None = None) -> float:
        """Sum of all open-position unrealised P&L.

        Args:
            strategy_id: Scope to one strategy. ``None`` for all.
        """
        with self._lock:
            if strategy_id:
                return sum(p.unrealised_pnl for p in self._open.get(strategy_id, {}).values())
            return sum(
                p.unrealised_pnl
                for positions in self._open.values()
                for p in positions.values()
            )

    def portfolio_total_pnl(self, strategy_id: str | None = None) -> float:
        """Realised + unrealised P&L.

        Args:
            strategy_id: Scope to one strategy. ``None`` for all.
        """
        return (
            self.portfolio_realised_pnl(strategy_id)
            + self.portfolio_unrealised_pnl(strategy_id)
        )

    def cumulative_r(self, strategy_id: str | None = None) -> float:
        """Total portfolio R-multiple (closed + open).

        Args:
            strategy_id: Scope to one strategy. ``None`` for all.
        """
        with self._lock:
            closed_r = sum(
                p.realised_r
                for positions in (
                    {strategy_id: self._closed.get(strategy_id, [])}
                    if strategy_id
                    else self._closed
                ).values()
                for p in positions
            )
            open_r = sum(
                p.unrealised_r
                for positions in (
                    {strategy_id: self._open.get(strategy_id, {})}
                    if strategy_id
                    else self._open
                ).values()
                for p in positions.values()
            )
        return closed_r + open_r

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_open_positions(self, strategy_id: str | None = None) -> list[PositionRecord]:
        """Return all open positions as ``PositionRecord`` snapshots.

        Args:
            strategy_id: Scope to one strategy. ``None`` for all.
        """
        with self._lock:
            if strategy_id:
                return [
                    p.to_record()
                    for p in self._open.get(strategy_id, {}).values()
                ]
            return [
                p.to_record()
                for positions in self._open.values()
                for p in positions.values()
            ]

    def get_closed_positions(self, strategy_id: str | None = None) -> list[PositionRecord]:
        """Return all closed positions as ``PositionRecord`` snapshots.

        Args:
            strategy_id: Scope to one strategy. ``None`` for all.
        """
        with self._lock:
            if strategy_id:
                return [p.to_record() for p in self._closed.get(strategy_id, [])]
            return [
                p.to_record()
                for positions in self._closed.values()
                for p in positions
            ]

    def is_open(self, symbol: str, strategy_id: str) -> bool:
        """Check whether a specific position is currently open."""
        with self._lock:
            return symbol in self._open.get(strategy_id, {})

    def open_count(self, strategy_id: str | None = None) -> int:
        """Number of currently open positions."""
        with self._lock:
            if strategy_id:
                return len(self._open.get(strategy_id, {}))
            return sum(len(v) for v in self._open.values())

    def summary(self, strategy_id: str | None = None) -> dict[str, Any]:
        """Return a lightweight P&L and position-count summary dict.

        Args:
            strategy_id: Scope to one strategy. ``None`` for all.
        """
        return {
            "open_count": self.open_count(strategy_id),
            "closed_count": len(self.get_closed_positions(strategy_id)),
            "realised_pnl": self.portfolio_realised_pnl(strategy_id),
            "unrealised_pnl": self.portfolio_unrealised_pnl(strategy_id),
            "total_pnl": self.portfolio_total_pnl(strategy_id),
            "cumulative_r": self.cumulative_r(strategy_id),
            "mtm_limit_breached": self.check_mtm_limit(),
        }

    # ------------------------------------------------------------------
    # Daily reset
    # ------------------------------------------------------------------

    def reset_daily(self) -> None:
        """Clear in-memory state for a new trading day.

        Does NOT truncate DuckDB — historical records are retained.
        Call this at the start of each session (typically 9:00 AM IST).
        """
        with self._lock:
            self._open.clear()
            self._closed.clear()
        logger.info("[DAILY_RESET] PositionTracker cleared for new trading day.")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close_db(self) -> None:
        """Close the DuckDB connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def __del__(self) -> None:
        self.close_db()
