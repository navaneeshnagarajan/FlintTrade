"""Persistent state machine for strategy lifecycle.

Manages the full strategy session lifecycle with DuckDB-backed persistence
and automatic crash recovery. Thread-safe state transitions with timestamps
and reason codes.

State machine::

    IDLE → ARMED → ENTRY_PENDING → IN_POSITION → EXIT_PENDING → EXITED
                                  ↗                            ↘
                          (loop back for next trade)       (session end)

Adapted from: nifty-trading-railway/baseline_v1_live/state_manager.py
Redesigned for FlintTrade's DuckDB-first, multi-strategy architecture:
- DuckDB persistence (not SQLite)
- No hardcoded strategy identifiers
- Pydantic models, StrEnum, threading.Lock
- Automatic recovery on restart
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("flinttrade.engine.state_manager")


# ---------------------------------------------------------------------------
# IST helper
# ---------------------------------------------------------------------------


def _now_ist() -> datetime:
    """Return current datetime in IST (Asia/Kolkata)."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Kolkata"))
    except Exception:
        return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_ist().isoformat()


# ---------------------------------------------------------------------------
# Strategy state enum
# ---------------------------------------------------------------------------


class StrategyState(StrEnum):
    """Lifecycle states for an intraday strategy session.

    Transitions::

        IDLE → ARMED → ENTRY_PENDING → IN_POSITION → EXIT_PENDING → EXITED

    ``IDLE``           — Initialised, waiting for market open or conditions.
    ``ARMED``          — All pre-conditions met; strategy is actively scanning.
    ``ENTRY_PENDING``  — Entry order placed at broker; waiting for fill.
    ``IN_POSITION``    — Position is open; monitoring for exit trigger.
    ``EXIT_PENDING``   — Exit order placed; waiting for fill confirmation.
    ``EXITED``         — Position closed cleanly; session complete.
    ``ERROR``          — Unrecoverable error; manual intervention required.
    ``PAUSED``         — Temporarily suspended (e.g. news event); resumes to last state.
    """

    IDLE = "IDLE"
    ARMED = "ARMED"
    ENTRY_PENDING = "ENTRY_PENDING"
    IN_POSITION = "IN_POSITION"
    EXIT_PENDING = "EXIT_PENDING"
    EXITED = "EXITED"
    ERROR = "ERROR"
    PAUSED = "PAUSED"


# Valid forward transitions (source → set of allowed targets)
_VALID_TRANSITIONS: dict[StrategyState, set[StrategyState]] = {
    StrategyState.IDLE: {StrategyState.ARMED, StrategyState.ERROR, StrategyState.PAUSED},
    StrategyState.ARMED: {
        StrategyState.ENTRY_PENDING,
        StrategyState.IDLE,
        StrategyState.ERROR,
        StrategyState.PAUSED,
    },
    StrategyState.ENTRY_PENDING: {
        StrategyState.IN_POSITION,
        StrategyState.ARMED,  # Order cancelled / rejected
        StrategyState.ERROR,
        StrategyState.PAUSED,
    },
    StrategyState.IN_POSITION: {
        StrategyState.EXIT_PENDING,
        StrategyState.EXITED,  # Direct close (e.g. EOD MIS square-off detected)
        StrategyState.ERROR,
        StrategyState.PAUSED,
    },
    StrategyState.EXIT_PENDING: {
        StrategyState.EXITED,
        StrategyState.IN_POSITION,  # Exit order failed / cancelled
        StrategyState.ERROR,
        StrategyState.PAUSED,
    },
    StrategyState.EXITED: {StrategyState.IDLE, StrategyState.ERROR},
    StrategyState.ERROR: {StrategyState.IDLE},  # Manual recovery
    StrategyState.PAUSED: {
        StrategyState.IDLE,
        StrategyState.ARMED,
        StrategyState.ENTRY_PENDING,
        StrategyState.IN_POSITION,
        StrategyState.EXIT_PENDING,
        StrategyState.ERROR,
    },
}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class StateTransitionRecord(BaseModel):
    """A single state-machine transition event.

    Attributes:
        strategy_id:   Owning strategy instance UUID.
        from_state:    State before the transition.
        to_state:      State after the transition.
        reason:        Human-readable reason code (e.g. ``"ORDER_FILLED"``).
        timestamp:     ISO-8601 string of when the transition occurred.
        metadata:      Optional free-form context dict.
    """

    strategy_id: str
    from_state: str
    to_state: str
    reason: str
    timestamp: str = Field(default_factory=_now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StrategyStateSnapshot(BaseModel):
    """Current state snapshot for one strategy.

    Attributes:
        strategy_id:     Strategy instance UUID.
        state:           Current ``StrategyState`` value.
        previous_state:  State before the most recent transition.
        entered_at:      ISO-8601 of when current state was entered.
        last_reason:     Reason code for the most recent transition.
        session_date:    Trading date (``YYYY-MM-DD``).
        metadata:        Arbitrary context stored alongside state.
    """

    strategy_id: str
    state: str
    previous_state: str | None = None
    entered_at: str = Field(default_factory=_now_iso)
    last_reason: str = ""
    session_date: str = Field(default_factory=lambda: _now_ist().strftime("%Y-%m-%d"))
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class StateManagerError(Exception):
    """Base exception for StateManager."""


class InvalidTransitionError(StateManagerError):
    """Raised when a requested state transition is not permitted."""


class StrategyStateNotFoundError(StateManagerError):
    """Raised when querying state for an unknown strategy_id."""


# ---------------------------------------------------------------------------
# DuckDB schema helpers
# ---------------------------------------------------------------------------

_CREATE_STATE_TABLE = """
CREATE TABLE IF NOT EXISTS ft_strategy_state (
    strategy_id    VARCHAR  PRIMARY KEY,
    state          VARCHAR  NOT NULL,
    previous_state VARCHAR,
    entered_at     VARCHAR  NOT NULL,
    last_reason    VARCHAR  DEFAULT '',
    session_date   VARCHAR  NOT NULL,
    metadata       VARCHAR  DEFAULT '{}'
)
"""

_CREATE_TRANSITIONS_SEQUENCE = "CREATE SEQUENCE IF NOT EXISTS ft_state_transitions_id_seq START 1"

_CREATE_TRANSITIONS_TABLE = """
CREATE TABLE IF NOT EXISTS ft_state_transitions (
    id            UBIGINT  PRIMARY KEY DEFAULT nextval('ft_state_transitions_id_seq'),
    strategy_id   VARCHAR  NOT NULL,
    from_state    VARCHAR  NOT NULL,
    to_state      VARCHAR  NOT NULL,
    reason        VARCHAR  NOT NULL,
    timestamp     VARCHAR  NOT NULL,
    metadata      VARCHAR  DEFAULT '{}'
)
"""

_UPSERT_STATE = """
INSERT OR REPLACE INTO ft_strategy_state
    (strategy_id, state, previous_state, entered_at, last_reason, session_date, metadata)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_TRANSITION = """
INSERT INTO ft_state_transitions
    (id, strategy_id, from_state, to_state, reason, timestamp, metadata)
VALUES (nextval('ft_state_transitions_id_seq'), ?, ?, ?, ?, ?, ?)
"""


# ---------------------------------------------------------------------------
# StateManager
# ---------------------------------------------------------------------------


class StateManager:
    """Persistent state machine for strategy lifecycle management.

    Each strategy is identified by a ``strategy_id`` (typically the same UUID
    used in ``StrategyLifecycleManager``). Independent state machines run
    concurrently — mutations for different strategies do NOT block each other.

    Args:
        db_path: Path to the DuckDB file. Use ``":memory:"`` for tests.

    Example::

        sm = StateManager(db_path="~/.flinttrade/engine.duckdb")

        # Initialise a strategy
        sm.initialise("abc-123")

        # Arm it
        sm.transition("abc-123", StrategyState.ARMED, reason="CONDITIONS_MET")

        # Place entry order
        sm.transition("abc-123", StrategyState.ENTRY_PENDING, reason="ORDER_PLACED")

        # Order filled
        sm.transition("abc-123", StrategyState.IN_POSITION, reason="ORDER_FILLED")

        # Exit order placed
        sm.transition("abc-123", StrategyState.EXIT_PENDING, reason="SL_HIT")

        # Position closed
        sm.transition("abc-123", StrategyState.EXITED, reason="EXIT_FILLED")

        # Recovery
        snapshot = sm.get("abc-123")
        history  = sm.get_history("abc-123")
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        # Per-strategy locks to avoid blocking unrelated strategies
        self._strategy_locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()  # Guards the locks dict itself
        # In-memory cache: {strategy_id: StrategyStateSnapshot}
        self._cache: dict[str, StrategyStateSnapshot] = {}
        # Protects read-only iteration over self._cache from concurrent mutations
        self._cache_lock = threading.Lock()
        # Serialises all DuckDB connection usage (not thread-safe)
        self._db_lock = threading.Lock()
        self._conn: Any = None

        self._init_db()
        self._recover()

        logger.info("StateManager ready [db=%s]", db_path)

    # ------------------------------------------------------------------
    # Database initialisation & recovery
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Open DuckDB connection and create tables."""
        try:
            import duckdb

            self._conn = duckdb.connect(self._db_path)
            self._conn.execute(_CREATE_STATE_TABLE)
            self._conn.execute(_CREATE_TRANSITIONS_SEQUENCE)
            self._conn.execute(_CREATE_TRANSITIONS_TABLE)
        except ImportError:
            logger.warning(
                "duckdb not installed — state persistence disabled. "
                "Install with: pip install duckdb"
            )
            self._conn = None

    def _recover(self) -> None:
        """Reload strategy states from DuckDB on startup."""
        if self._conn is None:
            return
        try:
            import json as _json

            rows = self._conn.execute(
                "SELECT strategy_id, state, previous_state, entered_at, "
                "last_reason, session_date, metadata "
                "FROM ft_strategy_state"
            ).fetchall()

            today = _now_ist().strftime("%Y-%m-%d")
            recovered = 0
            for row in rows:
                sid, state, prev_state, entered_at, last_reason, session_date, meta_str = row
                try:
                    meta = _json.loads(meta_str or "{}")
                except Exception:
                    meta = {}

                snapshot = StrategyStateSnapshot(
                    strategy_id=sid,
                    state=state,
                    previous_state=prev_state,
                    entered_at=entered_at,
                    last_reason=last_reason or "",
                    session_date=session_date or today,
                    metadata=meta,
                )
                self._cache[sid] = snapshot
                self._get_lock(sid)  # Pre-create lock
                recovered += 1

            if recovered:
                logger.info("[RECOVERY] Reloaded state for %d strategy/ies from DuckDB.", recovered)
        except Exception as exc:
            logger.error("[RECOVERY] Failed to reload states: %s", exc, exc_info=True)

    def _get_lock(self, strategy_id: str) -> threading.Lock:
        """Return (creating if necessary) the per-strategy lock."""
        with self._global_lock:
            if strategy_id not in self._strategy_locks:
                self._strategy_locks[strategy_id] = threading.Lock()
            return self._strategy_locks[strategy_id]

    def _persist_state(self, snapshot: StrategyStateSnapshot) -> None:
        """Upsert current state snapshot to DuckDB.

        Acquires ``_db_lock`` internally.  DuckDB connections are not
        thread-safe, so all ``_conn.execute`` calls must be serialised.
        """
        if self._conn is None:
            return
        import json as _json

        try:
            with self._db_lock:
                self._conn.execute(
                    _UPSERT_STATE,
                    [
                        snapshot.strategy_id,
                        snapshot.state,
                        snapshot.previous_state,
                        snapshot.entered_at,
                        snapshot.last_reason,
                        snapshot.session_date,
                        _json.dumps(snapshot.metadata),
                    ],
                )
        except Exception as exc:
            logger.error("[DB] Failed to persist state for %s: %s", snapshot.strategy_id, exc)

    def _persist_transition(self, record: StateTransitionRecord) -> None:
        """Append transition record to DuckDB audit log.

        Acquires ``_db_lock`` internally.  DuckDB connections are not
        thread-safe, so all ``_conn.execute`` calls must be serialised.
        """
        if self._conn is None:
            return
        import json as _json

        try:
            with self._db_lock:
                self._conn.execute(
                    _INSERT_TRANSITION,
                    [
                        record.strategy_id,
                        record.from_state,
                        record.to_state,
                        record.reason,
                        record.timestamp,
                        _json.dumps(record.metadata),
                    ],
                )
        except Exception as exc:
            logger.error("[DB] Failed to persist transition for %s: %s", record.strategy_id, exc)

    # ------------------------------------------------------------------
    # Initialise
    # ------------------------------------------------------------------

    def initialise(
        self,
        strategy_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> StrategyStateSnapshot:
        """Register a new strategy in IDLE state.

        Safe to call even if the strategy_id already exists (idempotent:
        returns existing snapshot without modification).

        Args:
            strategy_id:  Strategy instance UUID.
            metadata:     Optional initial context.

        Returns:
            The ``StrategyStateSnapshot`` for this strategy.
        """
        lock = self._get_lock(strategy_id)
        with lock:
            if strategy_id in self._cache:
                return self._cache[strategy_id]

            snapshot = StrategyStateSnapshot(
                strategy_id=strategy_id,
                state=StrategyState.IDLE,
                metadata=dict(metadata or {}),
            )
            with self._cache_lock:
                self._cache[strategy_id] = snapshot
            self._persist_state(snapshot)

        logger.info("[STATE] Initialised %s → IDLE", strategy_id[:8])
        return snapshot

    # ------------------------------------------------------------------
    # Transition
    # ------------------------------------------------------------------

    def transition(
        self,
        strategy_id: str,
        new_state: StrategyState,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> StrategyStateSnapshot:
        """Transition a strategy to a new state.

        Args:
            strategy_id:  Strategy instance UUID.
            new_state:    Target ``StrategyState``.
            reason:       Human-readable reason code (e.g. ``"ORDER_FILLED"``).
            metadata:     Optional context to attach to the transition record.

        Returns:
            Updated ``StrategyStateSnapshot``.

        Raises:
            StrategyStateNotFoundError: If strategy not initialised.
            InvalidTransitionError:     If transition is not permitted.
        """
        lock = self._get_lock(strategy_id)
        with lock:
            if strategy_id not in self._cache:
                raise StrategyStateNotFoundError(
                    f"Strategy '{strategy_id}' not found. Call initialise() first."
                )

            snapshot = self._cache[strategy_id]
            current = StrategyState(snapshot.state)

            allowed = _VALID_TRANSITIONS.get(current, set())
            if new_state not in allowed:
                raise InvalidTransitionError(
                    f"Transition {current} → {new_state} is not permitted for '{strategy_id}'. "
                    f"Allowed: {', '.join(sorted(s.value for s in allowed))}"
                )

            old_state = snapshot.state
            now = _now_iso()

            snapshot.previous_state = old_state
            snapshot.state = new_state
            snapshot.entered_at = now
            snapshot.last_reason = reason
            if metadata:
                snapshot.metadata.update(metadata)

            transition_record = StateTransitionRecord(
                strategy_id=strategy_id,
                from_state=old_state,
                to_state=new_state,
                reason=reason,
                timestamp=now,
                metadata=dict(metadata or {}),
            )

            self._persist_state(snapshot)
            self._persist_transition(transition_record)

        logger.info(
            "[STATE] %s: %s → %s [%s]",
            strategy_id[:8], old_state, new_state, reason,
        )
        return snapshot

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, strategy_id: str) -> StrategyStateSnapshot:
        """Return the current state snapshot for a strategy.

        Args:
            strategy_id: Strategy instance UUID.

        Returns:
            ``StrategyStateSnapshot``.

        Raises:
            StrategyStateNotFoundError: If not found.
        """
        snapshot = self._cache.get(strategy_id)
        if snapshot is None:
            raise StrategyStateNotFoundError(
                f"Strategy '{strategy_id}' not found. Call initialise() first."
            )
        return snapshot

    def current_state(self, strategy_id: str) -> StrategyState:
        """Return just the current state enum value.

        Args:
            strategy_id: Strategy instance UUID.
        """
        return StrategyState(self.get(strategy_id).state)

    def is_in_state(self, strategy_id: str, state: StrategyState) -> bool:
        """Check whether the strategy is currently in the given state.

        Args:
            strategy_id: Strategy instance UUID.
            state:       ``StrategyState`` to check.
        """
        try:
            return self.current_state(strategy_id) == state
        except StrategyStateNotFoundError:
            return False

    def get_history(
        self,
        strategy_id: str,
        limit: int = 100,
    ) -> list[StateTransitionRecord]:
        """Return past state transitions from DuckDB.

        Args:
            strategy_id:  Strategy instance UUID.
            limit:        Maximum number of records to return (most recent first).

        Returns:
            List of ``StateTransitionRecord`` objects.
        """
        if self._conn is None:
            return []

        import json as _json

        try:
            with self._db_lock:
                rows = self._conn.execute(
                    "SELECT strategy_id, from_state, to_state, reason, timestamp, metadata "
                    "FROM ft_state_transitions "
                    "WHERE strategy_id = ? "
                    "ORDER BY id DESC "
                    "LIMIT ?",
                    [strategy_id, limit],
                ).fetchall()
        except Exception as exc:
            logger.error("[DB] Failed to query history for %s: %s", strategy_id, exc)
            return []

        records = []
        for row in rows:
            sid, from_s, to_s, reason, ts, meta_str = row
            try:
                meta = _json.loads(meta_str or "{}")
            except Exception:
                meta = {}
            records.append(
                StateTransitionRecord(
                    strategy_id=sid,
                    from_state=from_s,
                    to_state=to_s,
                    reason=reason,
                    timestamp=ts,
                    metadata=meta,
                )
            )
        return records

    def all_snapshots(self) -> list[StrategyStateSnapshot]:
        """Return snapshots for all registered strategies.

        Takes a snapshot of ``_cache`` under ``_cache_lock`` to avoid racing
        with a concurrent ``initialise`` call that inserts a new entry.
        """
        with self._cache_lock:
            return list(self._cache.values())

    def strategies_in_state(self, state: StrategyState) -> list[str]:
        """Return all strategy_ids currently in the given state.

        Args:
            state: Target ``StrategyState``.
        """
        with self._cache_lock:
            return [
                sid
                for sid, snap in self._cache.items()
                if snap.state == state
            ]

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self, strategy_id: str, reason: str = "DAILY_RESET") -> None:
        """Reset a strategy back to IDLE (for new trading day).

        Does NOT delete history — transitions are retained in DuckDB.

        Args:
            strategy_id: Strategy instance UUID.
            reason:      Reason code for the reset transition.
        """
        lock = self._get_lock(strategy_id)
        with lock:
            snapshot = self._cache.get(strategy_id)
            if snapshot is None:
                return

            old_state = snapshot.state
            now = _now_iso()

            snapshot.previous_state = old_state
            snapshot.state = StrategyState.IDLE
            snapshot.entered_at = now
            snapshot.last_reason = reason
            snapshot.session_date = _now_ist().strftime("%Y-%m-%d")

            transition_record = StateTransitionRecord(
                strategy_id=strategy_id,
                from_state=old_state,
                to_state=StrategyState.IDLE,
                reason=reason,
                timestamp=now,
            )
            self._persist_state(snapshot)
            self._persist_transition(transition_record)

        logger.info("[STATE] %s: reset to IDLE [%s]", strategy_id[:8], reason)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close_db(self) -> None:
        """Close the DuckDB connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                logger.exception("Failed to close DuckDB connection in StateManager")
            self._conn = None

    def __del__(self) -> None:
        self.close_db()
