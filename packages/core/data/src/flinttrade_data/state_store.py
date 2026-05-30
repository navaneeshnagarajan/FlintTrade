"""Native sandbox state store — SQLite ``state.sqlite`` (data-layer §9).

Replaces the legacy DuckDB ``sandbox.duckdb`` (which deadlocked when the terminal
UI, tick recorder, and sandbox engine all wrote concurrently). SQLite WAL handles
the concurrency transparently and the state recreates trivially on loss — the EOD
reset wipes positions anyway.

Schema (§9.2): ``capital``, ``orders``, ``positions``, ``pnl``, ``mtm``. The
``mtm`` table is a circular buffer capped at 100k rows by the ``mtm_cap`` trigger
(fires every 1000th insert to avoid per-row DELETE cost during tick bursts —
Database H7). The EOD ``reset`` (§9.4) is crash-atomic: it archives orders + mtm
to a fsync'd jsonl via tmp-then-rename, then DELETEs the archived rows inside one
SQL transaction, all under a cross-platform file lock so a CLI run and the 15:30
cron cannot interleave.
"""

from __future__ import annotations

import json
import os
import sys
import time
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from flinttrade_core.db import open_sqlite

IST = timezone(timedelta(hours=5, minutes=30))

# data-layer §9.2 canonical DDL. Timestamps are unix-epoch REAL throughout.
_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS capital (
    id           TEXT PRIMARY KEY DEFAULT 'default',
    initial      REAL NOT NULL,
    current      REAL NOT NULL,
    used_margin  REAL NOT NULL DEFAULT 0.0,
    updated_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    order_id    TEXT PRIMARY KEY,
    symbol      TEXT NOT NULL,
    exchange    TEXT NOT NULL,
    action      TEXT NOT NULL CHECK (action IN ('BUY', 'SELL')),
    quantity    INTEGER NOT NULL,
    price       REAL NOT NULL,
    product     TEXT NOT NULL DEFAULT 'MIS',
    status      TEXT NOT NULL DEFAULT 'COMPLETE'
                CHECK (status IN ('PENDING', 'COMPLETE', 'CANCELLED', 'REJECTED', 'PARTIAL')),
    filled_qty  INTEGER NOT NULL DEFAULT 0,
    avg_fill_px REAL,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_created ON orders (created_at);
CREATE INDEX IF NOT EXISTS idx_orders_status  ON orders (status)
    WHERE status IN ('PENDING', 'PARTIAL');

CREATE TABLE IF NOT EXISTS positions (
    position_id     TEXT PRIMARY KEY,
    symbol          TEXT NOT NULL,
    exchange        TEXT NOT NULL,
    product         TEXT NOT NULL DEFAULT 'MIS',
    net_qty         INTEGER NOT NULL DEFAULT 0,
    avg_price       REAL NOT NULL DEFAULT 0.0,
    buy_qty         INTEGER NOT NULL DEFAULT 0,
    buy_value       REAL NOT NULL DEFAULT 0.0,
    sell_qty        INTEGER NOT NULL DEFAULT 0,
    sell_value      REAL NOT NULL DEFAULT 0.0,
    realised_pnl    REAL NOT NULL DEFAULT 0.0,
    unrealised_pnl  REAL NOT NULL DEFAULT 0.0,
    updated_at      REAL NOT NULL,
    UNIQUE (symbol, exchange, product)
);
CREATE INDEX IF NOT EXISTS idx_positions_sym_ex
    ON positions (symbol, exchange, product);

CREATE TABLE IF NOT EXISTS pnl (
    session_date     TEXT PRIMARY KEY,
    realised_total   REAL NOT NULL DEFAULT 0.0,
    unrealised_total REAL NOT NULL DEFAULT 0.0,
    gross_pnl        REAL NOT NULL DEFAULT 0.0,
    charges          REAL NOT NULL DEFAULT 0.0,
    net_pnl          REAL NOT NULL DEFAULT 0.0,
    high_water_mark  REAL NOT NULL DEFAULT 0.0,
    max_drawdown     REAL NOT NULL DEFAULT 0.0,
    updated_at       REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS mtm (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id     TEXT NOT NULL REFERENCES positions(position_id) ON DELETE CASCADE,
    tick_ts         REAL NOT NULL,
    ltp             REAL NOT NULL,
    qty             INTEGER NOT NULL,
    unrealised      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mtm_position_ts ON mtm(position_id, tick_ts DESC);

-- Database H7: prune the mtm circular buffer to 100k rows. Fires every 1000th
-- insert (mod-1000 throttle) so tick bursts do not pay a per-row DELETE.
CREATE TRIGGER IF NOT EXISTS mtm_cap AFTER INSERT ON mtm
WHEN (NEW.id % 1000 = 0)
BEGIN
    DELETE FROM mtm WHERE id < NEW.id - 100000;
END;
"""

_MTM_RETENTION_ROWS = 100_000


def ensure_schema(conn) -> None:
    """Idempotently create the §9.2 sandbox schema (tables, indexes, trigger)."""
    conn.executescript(_SCHEMA_DDL)


def init_capital(conn, initial_capital: float) -> None:
    """Seed the single ``capital`` row if absent (idempotent)."""
    row = conn.execute("SELECT 1 FROM capital WHERE id = 'default'").fetchone()
    if row is None:
        now = time.time()
        conn.execute(
            "INSERT INTO capital (id, initial, current, used_margin, updated_at) "
            "VALUES ('default', ?, ?, 0.0, ?)",
            (initial_capital, initial_capital, now),
        )


class StateStore:
    """Thin SQLite-backed accessor for native sandbox state (§9.3 contract).

    Owns one WAL connection. Higher-level fill simulation lives in
    ``sandbox_engine``; this class is the persistence boundary.
    """

    def __init__(self, db_path: str | os.PathLike[str], *, initial_capital: float = 1_000_000.0) -> None:
        Path(os.fspath(db_path)).parent.mkdir(parents=True, exist_ok=True)
        self._conn = open_sqlite(db_path, durability="normal")
        ensure_schema(self._conn)
        init_capital(self._conn, initial_capital)

    # -- capital -------------------------------------------------------------

    def get_capital(self) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT id, initial, current, used_margin, updated_at "
            "FROM capital WHERE id = 'default'"
        ).fetchone()
        keys = ("id", "initial", "current", "used_margin", "updated_at")
        return dict(zip(keys, row)) if row else {}

    # -- orders --------------------------------------------------------------

    def record_order(
        self,
        order_id: str,
        symbol: str,
        exchange: str,
        action: str,
        quantity: int,
        price: float,
        product: str = "MIS",
        status: str = "COMPLETE",
        filled_qty: int | None = None,
        avg_fill_px: float | None = None,
    ) -> str:
        now = time.time()
        if filled_qty is None:
            filled_qty = quantity if status == "COMPLETE" else 0
        self._conn.execute(
            "INSERT INTO orders (order_id, symbol, exchange, action, quantity, price, "
            "product, status, filled_qty, avg_fill_px, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (order_id, symbol, exchange, action, quantity, price, product, status,
             filled_qty, avg_fill_px, now, now),
        )
        return order_id

    def get_orders(self, limit: int = 200) -> list[dict[str, Any]]:
        cols = [c[1] for c in self._conn.execute("PRAGMA table_info(orders)").fetchall()]
        rows = self._conn.execute(
            "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (int(limit),)
        ).fetchall()
        return [dict(zip(cols, r)) for r in rows]

    # -- positions -----------------------------------------------------------

    def get_positions(self, open_only: bool = True) -> list[dict[str, Any]]:
        cols = [c[1] for c in self._conn.execute("PRAGMA table_info(positions)").fetchall()]
        sql = "SELECT * FROM positions"
        if open_only:
            sql += " WHERE net_qty != 0"
        rows = self._conn.execute(sql).fetchall()
        return [dict(zip(cols, r)) for r in rows]

    def upsert_position(self, position_id: str, symbol: str, exchange: str, product: str = "MIS", **fields: Any) -> None:
        now = time.time()
        existing = self._conn.execute(
            "SELECT 1 FROM positions WHERE position_id = ?", (position_id,)
        ).fetchone()
        if existing is None:
            self._conn.execute(
                "INSERT INTO positions (position_id, symbol, exchange, product, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (position_id, symbol, exchange, product, now),
            )
        for key, value in fields.items():
            self._conn.execute(
                f"UPDATE positions SET {key} = ?, updated_at = ? WHERE position_id = ?",
                (value, now, position_id),
            )

    # -- mtm -----------------------------------------------------------------

    def record_mtm(self, position_id: str, tick_ts: float, ltp: float, qty: int, unrealised: float) -> None:
        self._conn.execute(
            "INSERT INTO mtm (position_id, tick_ts, ltp, qty, unrealised) VALUES (?, ?, ?, ?, ?)",
            (position_id, tick_ts, ltp, qty, unrealised),
        )

    # -- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "StateStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


@contextmanager
def _reset_lock(lock_path: Path) -> Iterator[None]:
    """Cross-platform exclusive file lock (Database H10).

    POSIX: ``fcntl.lockf``; Windows: ``msvcrt.locking``. Released on close/exit.
    Raises ``BlockingIOError``/``OSError`` if another process holds the lock.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def reset(workspace_dir: str | os.PathLike[str], initial_capital: float = 1_000_000.0) -> dict[str, Any]:
    """End-of-day reset: archive orders + mtm; clear positions; reset capital (§9.4).

    Crash-atomic: the archive is written to a tmp file, fsync'd, atomically
    renamed, and only then are the archived rows DELETEd inside one SQL
    transaction — all under a file lock. A crash between any two steps leaves a
    consistent state (rows kept if the archive is incomplete). Idempotent within
    a day: a second run re-archives the now-empty tables (no duplicate rows).
    """
    workspace_dir = Path(os.fspath(workspace_dir))
    state_path = workspace_dir / "sandbox" / "state.sqlite"
    sessions_dir = workspace_dir / "sandbox" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    lock_path = sessions_dir / ".reset_lock"

    session_date = datetime.now(IST).strftime("%Y-%m-%d")
    archive_path = sessions_dir / f"{session_date}.jsonl"
    archive_tmp_path = sessions_dir / f"{session_date}.jsonl.tmp"

    with _reset_lock(lock_path):
        with closing(open_sqlite(str(state_path), durability="normal")) as conn:
            ensure_schema(conn)
            order_cols = [c[1] for c in conn.execute("PRAGMA table_info(orders)").fetchall()]
            mtm_cols = [c[1] for c in conn.execute("PRAGMA table_info(mtm)").fetchall()]
            order_rows = conn.execute("SELECT * FROM orders").fetchall()
            mtm_rows = conn.execute("SELECT * FROM mtm").fetchall()

            # 1. archive → tmp → fsync → atomic rename → fsync parent dir.
            with archive_tmp_path.open("w", encoding="utf-8") as f:
                for row in order_rows:
                    f.write(json.dumps(dict(zip(order_cols, row))) + "\n")
                for row in mtm_rows:
                    f.write(json.dumps(dict(zip(mtm_cols, row))) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(archive_tmp_path, archive_path)
            if hasattr(os, "O_DIRECTORY"):
                dir_fd = os.open(str(sessions_dir), os.O_DIRECTORY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)

            # 2. DELETE archived rows inside one transaction (Database H10).
            conn.execute("BEGIN IMMEDIATE")
            try:
                agg = conn.execute(
                    "SELECT COALESCE(SUM(realised_pnl), 0), COALESCE(SUM(unrealised_pnl), 0) "
                    "FROM positions"
                ).fetchone()
                realised_total, unrealised_total = agg[0] or 0.0, agg[1] or 0.0
                net_pnl = realised_total + unrealised_total
                conn.execute(
                    "INSERT INTO pnl (session_date, realised_total, unrealised_total, "
                    "gross_pnl, charges, net_pnl, updated_at) "
                    "VALUES (?, ?, ?, ?, 0.0, ?, ?) "
                    "ON CONFLICT (session_date) DO UPDATE SET "
                    "realised_total = excluded.realised_total, "
                    "unrealised_total = excluded.unrealised_total, "
                    "net_pnl = excluded.net_pnl, updated_at = excluded.updated_at",
                    (session_date, realised_total, unrealised_total, net_pnl, net_pnl, time.time()),
                )
                conn.execute("DELETE FROM mtm")
                conn.execute("DELETE FROM positions")
                conn.execute("DELETE FROM orders WHERE status NOT IN ('PENDING')")
                conn.execute(
                    "UPDATE capital SET current = ?, used_margin = 0.0, updated_at = ? WHERE id = 'default'",
                    (initial_capital, time.time()),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    return {"archived_to": str(archive_path), "session_date": session_date}
