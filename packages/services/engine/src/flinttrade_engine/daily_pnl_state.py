"""Crash-safe, account-scoped state for the Layer 4 daily-loss guard."""

from __future__ import annotations

import math
import sqlite3
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from flinttrade_core.db import open_sqlite
from flinttrade_core.secure_file import harden
from flinttrade_engine.request_context import parse_selector


class DailyPnLStateError(RuntimeError):
    """Layer 4 state cannot be read or changed without weakening safety."""


@dataclass(frozen=True)
class DailyPnLState:
    """One selector's immutable opening capital and current-session latches."""

    selector: str
    session_key: str
    opening_risk_capital: float
    paused: bool = False
    killed: bool = False
    revision: int = 1


class DailyPnLStateStoreProtocol(Protocol):
    """Storage contract consumed by :class:`DailyPnLLimits`."""

    def resolve(
        self,
        *,
        selector: str,
        session_key: str,
        observed_opening_capital: float,
    ) -> DailyPnLState: ...

    def configure(
        self,
        *,
        selector: str,
        session_key: str,
        opening_risk_capital: float,
    ) -> DailyPnLState: ...

    def latch(
        self,
        *,
        selector: str,
        session_key: str,
        paused: bool = False,
        killed: bool = False,
    ) -> DailyPnLState: ...

    def reset(self, *, selector: str, session_key: str) -> DailyPnLState: ...

    def get(self, *, selector: str, session_key: str) -> DailyPnLState | None: ...

    def list_session(self, *, session_key: str) -> tuple[DailyPnLState, ...]: ...


def _normalise_identity(selector: str, session_key: str) -> tuple[str, str]:
    canonical = str(selector or "").strip()
    parse_selector(canonical)
    session = str(session_key or "").strip()
    if not session:
        raise DailyPnLStateError("daily P&L session key is required")
    return canonical, session


def _positive_capital(value: float) -> float:
    try:
        capital = float(value)
    except (TypeError, ValueError) as exc:
        raise DailyPnLStateError("opening risk capital is invalid") from exc
    if not math.isfinite(capital) or capital <= 0:
        raise DailyPnLStateError("positive opening risk capital is required")
    return capital


def _same_capital(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=0.01)


class InMemoryDailyPnLStateStore:
    """Thread-safe test/local implementation with the durable-store contract."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._states: dict[tuple[str, str], DailyPnLState] = {}

    def resolve(
        self,
        *,
        selector: str,
        session_key: str,
        observed_opening_capital: float,
    ) -> DailyPnLState:
        selector, session_key = _normalise_identity(selector, session_key)
        key = (selector, session_key)
        with self._lock:
            current = self._states.get(key)
            if current is not None:
                return current
            capital = _positive_capital(observed_opening_capital)
            current = DailyPnLState(selector, session_key, capital)
            self._states[key] = current
            return current

    def configure(
        self,
        *,
        selector: str,
        session_key: str,
        opening_risk_capital: float,
    ) -> DailyPnLState:
        selector, session_key = _normalise_identity(selector, session_key)
        capital = _positive_capital(opening_risk_capital)
        key = (selector, session_key)
        with self._lock:
            current = self._states.get(key)
            if current is not None:
                if not _same_capital(current.opening_risk_capital, capital):
                    raise DailyPnLStateError("opening risk capital is already frozen for this session")
                return current
            current = DailyPnLState(selector, session_key, capital)
            self._states[key] = current
            return current

    def latch(
        self,
        *,
        selector: str,
        session_key: str,
        paused: bool = False,
        killed: bool = False,
    ) -> DailyPnLState:
        selector, session_key = _normalise_identity(selector, session_key)
        key = (selector, session_key)
        with self._lock:
            current = self._states.get(key)
            if current is None:
                raise DailyPnLStateError("opening risk capital has not been frozen for this session")
            updated = replace(
                current,
                paused=current.paused or bool(paused),
                killed=current.killed or bool(killed),
                revision=current.revision + 1,
            )
            self._states[key] = updated
            return updated

    def reset(self, *, selector: str, session_key: str) -> DailyPnLState:
        selector, session_key = _normalise_identity(selector, session_key)
        key = (selector, session_key)
        with self._lock:
            current = self._states.get(key)
            if current is None:
                raise DailyPnLStateError("opening risk capital has not been frozen for this session")
            updated = replace(current, paused=False, killed=False, revision=current.revision + 1)
            self._states[key] = updated
            return updated

    def get(self, *, selector: str, session_key: str) -> DailyPnLState | None:
        selector, session_key = _normalise_identity(selector, session_key)
        with self._lock:
            return self._states.get((selector, session_key))

    def list_session(self, *, session_key: str) -> tuple[DailyPnLState, ...]:
        session = str(session_key or "").strip()
        if not session:
            raise DailyPnLStateError("daily P&L session key is required")
        with self._lock:
            return tuple(
                self._states[key]
                for key in sorted(self._states)
                if key[1] == session
            )


class DailyPnLStateStore:
    """FULL-sync SQLite implementation used by the production safety system."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path).expanduser().resolve()
        self._lock = threading.RLock()
        self._schema_ready = False

    def _harden_path(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        if self._db_path.exists():
            harden(self._db_path)

    def _connect(self) -> sqlite3.Connection:
        self._harden_path()
        conn = open_sqlite(
            self._db_path,
            durability="full",
            temp_store="FILE",
            cache_size_kb=1024,
        )
        harden(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            if not self._schema_ready:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS daily_pnl_state (
                        selector TEXT NOT NULL,
                        session_key TEXT NOT NULL,
                        opening_risk_capital REAL NOT NULL CHECK (opening_risk_capital > 0),
                        paused INTEGER NOT NULL DEFAULT 0 CHECK (paused IN (0, 1)),
                        killed INTEGER NOT NULL DEFAULT 0 CHECK (killed IN (0, 1)),
                        revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (selector, session_key)
                    ) WITHOUT ROWID
                    """
                )
                conn.execute("PRAGMA user_version = 1")
                conn.commit()
                self._schema_ready = True
            return conn
        except Exception:
            conn.close()
            raise

    @staticmethod
    def _record(row: sqlite3.Row) -> DailyPnLState:
        return DailyPnLState(
            selector=str(row["selector"]),
            session_key=str(row["session_key"]),
            opening_risk_capital=float(row["opening_risk_capital"]),
            paused=bool(row["paused"]),
            killed=bool(row["killed"]),
            revision=int(row["revision"]),
        )

    @staticmethod
    def _select(conn: sqlite3.Connection, selector: str, session_key: str) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM daily_pnl_state WHERE selector = ? AND session_key = ?",
            (selector, session_key),
        ).fetchone()

    def healthcheck(self) -> None:
        """Initialise the schema and reject a corrupt or unreadable store."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("PRAGMA quick_check").fetchone()
                if row is None or str(row[0]).lower() != "ok":
                    raise sqlite3.DatabaseError("daily P&L state quick-check failed")
            finally:
                conn.close()

    def resolve(
        self,
        *,
        selector: str,
        session_key: str,
        observed_opening_capital: float,
    ) -> DailyPnLState:
        selector, session_key = _normalise_identity(selector, session_key)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = self._select(conn, selector, session_key)
                if row is None:
                    capital = _positive_capital(observed_opening_capital)
                    conn.execute(
                        """
                        INSERT INTO daily_pnl_state
                            (selector, session_key, opening_risk_capital)
                        VALUES (?, ?, ?)
                        """,
                        (selector, session_key, capital),
                    )
                    row = self._select(conn, selector, session_key)
                conn.execute("COMMIT")
                assert row is not None
                return self._record(row)
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

    def configure(
        self,
        *,
        selector: str,
        session_key: str,
        opening_risk_capital: float,
    ) -> DailyPnLState:
        selector, session_key = _normalise_identity(selector, session_key)
        capital = _positive_capital(opening_risk_capital)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = self._select(conn, selector, session_key)
                if row is None:
                    conn.execute(
                        """
                        INSERT INTO daily_pnl_state
                            (selector, session_key, opening_risk_capital)
                        VALUES (?, ?, ?)
                        """,
                        (selector, session_key, capital),
                    )
                    row = self._select(conn, selector, session_key)
                elif not _same_capital(float(row["opening_risk_capital"]), capital):
                    raise DailyPnLStateError("opening risk capital is already frozen for this session")
                conn.execute("COMMIT")
                assert row is not None
                return self._record(row)
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

    def latch(
        self,
        *,
        selector: str,
        session_key: str,
        paused: bool = False,
        killed: bool = False,
    ) -> DailyPnLState:
        selector, session_key = _normalise_identity(selector, session_key)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = self._select(conn, selector, session_key)
                if row is None:
                    raise DailyPnLStateError("opening risk capital has not been frozen for this session")
                conn.execute(
                    """
                    UPDATE daily_pnl_state
                    SET paused = CASE WHEN ? THEN 1 ELSE paused END,
                        killed = CASE WHEN ? THEN 1 ELSE killed END,
                        revision = revision + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE selector = ? AND session_key = ?
                    """,
                    (bool(paused), bool(killed), selector, session_key),
                )
                updated = self._select(conn, selector, session_key)
                conn.execute("COMMIT")
                assert updated is not None
                return self._record(updated)
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

    def reset(self, *, selector: str, session_key: str) -> DailyPnLState:
        selector, session_key = _normalise_identity(selector, session_key)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = self._select(conn, selector, session_key)
                if row is None:
                    raise DailyPnLStateError("opening risk capital has not been frozen for this session")
                conn.execute(
                    """
                    UPDATE daily_pnl_state
                    SET paused = 0,
                        killed = 0,
                        revision = revision + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE selector = ? AND session_key = ?
                    """,
                    (selector, session_key),
                )
                updated = self._select(conn, selector, session_key)
                conn.execute("COMMIT")
                assert updated is not None
                return self._record(updated)
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

    def get(self, *, selector: str, session_key: str) -> DailyPnLState | None:
        selector, session_key = _normalise_identity(selector, session_key)
        with self._lock:
            conn = self._connect()
            try:
                row = self._select(conn, selector, session_key)
                return self._record(row) if row is not None else None
            finally:
                conn.close()

    def list_session(self, *, session_key: str) -> tuple[DailyPnLState, ...]:
        session = str(session_key or "").strip()
        if not session:
            raise DailyPnLStateError("daily P&L session key is required")
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM daily_pnl_state WHERE session_key = ? ORDER BY selector",
                    (session,),
                ).fetchall()
                return tuple(self._record(row) for row in rows)
            finally:
                conn.close()
