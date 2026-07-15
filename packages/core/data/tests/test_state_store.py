"""Native sandbox state-store tests (data-layer §9.2 / §9.4; Database H7 + H10)."""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pytest

from flinttrade_data.sandbox_migration import (
    LegacySandboxConflict,
    migrate_legacy_sandbox,
)
from flinttrade_data.state_store import StateStore, reset


def _load_sandbox_migrator():
    path = Path(__file__).resolve().parents[4] / "scripts" / "migrate-sandbox-duckdb-to-sqlite.py"
    spec = importlib.util.spec_from_file_location("migrate_sandbox", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed_legacy_duckdb(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime(2026, 7, 14, 9, 30, tzinfo=timezone.utc)
    with duckdb.connect(str(path)) as conn:
        conn.execute(
            """CREATE TABLE sandbox_orders (
                order_id VARCHAR PRIMARY KEY, account_id VARCHAR, symbol VARCHAR,
                exchange VARCHAR, action VARCHAR, quantity INTEGER, price DOUBLE,
                trigger_price DOUBLE, pricetype VARCHAR, product VARCHAR,
                strategy VARCHAR, status VARCHAR, fill_price DOUBLE,
                fill_time TIMESTAMP, created_at TIMESTAMP, updated_at TIMESTAMP
            )"""
        )
        conn.execute(
            """CREATE TABLE sandbox_trades (
                trade_id VARCHAR PRIMARY KEY, order_id VARCHAR, account_id VARCHAR,
                symbol VARCHAR, exchange VARCHAR, action VARCHAR, quantity INTEGER,
                price DOUBLE, product VARCHAR, strategy VARCHAR, traded_at TIMESTAMP
            )"""
        )
        conn.execute(
            """CREATE TABLE sandbox_positions (
                position_id VARCHAR PRIMARY KEY, account_id VARCHAR, symbol VARCHAR,
                exchange VARCHAR, product VARCHAR, net_qty INTEGER, avg_price DOUBLE,
                buy_qty INTEGER, buy_value DOUBLE, sell_qty INTEGER, sell_value DOUBLE,
                unrealized_pnl DOUBLE, realized_pnl DOUBLE, updated_at TIMESTAMP
            )"""
        )
        conn.execute(
            """CREATE TABLE sandbox_funds (
                account_id VARCHAR PRIMARY KEY, starting_capital DOUBLE,
                used_margin DOUBLE, realized_pnl DOUBLE, updated_at TIMESTAMP
            )"""
        )
        conn.execute(
            """CREATE TABLE sandbox_daily_pnl (
                record_id VARCHAR PRIMARY KEY, account_id VARCHAR, date DATE,
                realized_pnl DOUBLE, unrealized_pnl DOUBLE, total_trades INTEGER,
                recorded_at TIMESTAMP
            )"""
        )
        conn.execute(
            "INSERT INTO sandbox_funds VALUES ('default', 250000, 1500, 100, ?)",
            [now],
        )
        conn.execute(
            """INSERT INTO sandbox_orders VALUES
               ('old-order', 'default', 'ITC', 'NSE', 'BUY', 2, 100, 0,
                'MARKET', 'MIS', 'legacy', 'COMPLETE', 101, ?, ?, ?)""",
            [now, now, now],
        )
        conn.execute(
            """INSERT INTO sandbox_trades VALUES
               ('old-trade', 'old-order', 'default', 'ITC', 'NSE', 'BUY', 2,
                101, 'MIS', 'legacy', ?)""",
            [now],
        )
        conn.execute(
            """INSERT INTO sandbox_positions VALUES
               ('old-position', 'default', 'ITC', 'NSE', 'MIS', 2, 101,
                2, 202, 0, 0, 2, 10, ?)""",
            [now],
        )
        conn.execute(
            """INSERT INTO sandbox_daily_pnl VALUES
               ('old-pnl', 'default', DATE '2026-07-14', 10, 2, 1, ?)""",
            [now],
        )


@pytest.fixture
def store(tmp_path: Path) -> StateStore:
    s = StateStore(tmp_path / "sandbox" / "state.sqlite", initial_capital=1_000_000.0)
    try:
        yield s
    finally:
        s.close()


# --- schema -----------------------------------------------------------------


def test_schema_creates_all_tables_and_trigger(store: StateStore) -> None:
    names = {
        r[0]
        for r in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"capital", "orders", "positions", "pnl", "mtm"} <= names
    trig = store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND name='mtm_cap'"
    ).fetchone()
    assert trig is not None


def test_capital_seeded_once(store: StateStore) -> None:
    cap = store.get_capital()
    assert cap["initial"] == 1_000_000.0
    assert cap["current"] == 1_000_000.0
    assert cap["used_margin"] == 0.0


# --- mtm circular-buffer trigger (Database H7) -------------------------------


def test_mtm_cap_trigger_prunes_beyond_retention(store: StateStore) -> None:
    """The trigger fires on the 1000-multiple id and drops rows >100k older."""
    store.upsert_position("p1", "NIFTY", "NSE", net_qty=50)
    conn = store._conn
    # an old row well outside the 100k retention window
    conn.execute(
        "INSERT INTO mtm (id, position_id, tick_ts, ltp, qty, unrealised) VALUES (1, 'p1', 1.0, 100.0, 50, 0.0)"
    )
    # a fresh row whose id is a 1000-multiple → trigger fires, deletes id < 101000-100000
    conn.execute(
        "INSERT INTO mtm (id, position_id, tick_ts, ltp, qty, unrealised) "
        "VALUES (101000, 'p1', 2.0, 101.0, 50, 50.0)"
    )
    remaining = {r[0] for r in conn.execute("SELECT id FROM mtm").fetchall()}
    assert 1 not in remaining        # pruned
    assert 101000 in remaining       # kept


def test_mtm_trigger_does_not_prune_within_window(store: StateStore) -> None:
    store.upsert_position("p1", "NIFTY", "NSE", net_qty=50)
    conn = store._conn
    conn.execute(
        "INSERT INTO mtm (id, position_id, tick_ts, ltp, qty, unrealised) VALUES (500, 'p1', 1.0, 100.0, 50, 0.0)"
    )
    conn.execute(
        "INSERT INTO mtm (id, position_id, tick_ts, ltp, qty, unrealised) VALUES (1000, 'p1', 2.0, 101.0, 50, 5.0)"
    )
    remaining = {r[0] for r in conn.execute("SELECT id FROM mtm").fetchall()}
    assert remaining == {500, 1000}  # 1000-100000 < 0 → nothing pruned


# --- orders + positions -----------------------------------------------------


def test_record_and_read_orders(store: StateStore) -> None:
    store.record_order("o1", "NIFTY", "NSE", "BUY", 50, 22_500.0)
    store.record_order("o2", "BANKNIFTY", "NFO", "SELL", 15, 48_000.0, status="PENDING")
    book = store.get_orders()
    assert {o["order_id"] for o in book} == {"o1", "o2"}
    o1 = next(o for o in book if o["order_id"] == "o1")
    assert o1["status"] == "COMPLETE"
    assert o1["filled_qty"] == 50  # COMPLETE → fully filled


def test_get_positions_open_only(store: StateStore) -> None:
    store.upsert_position("p1", "NIFTY", "NSE", net_qty=50)
    store.upsert_position("p2", "TCS", "NSE", net_qty=0)  # flat
    open_pos = store.get_positions(open_only=True)
    assert {p["position_id"] for p in open_pos} == {"p1"}
    assert len(store.get_positions(open_only=False)) == 2


# --- EOD reset (§9.4) -------------------------------------------------------


def _seed(tmp_path: Path) -> None:
    s = StateStore(tmp_path / "sandbox" / "state.sqlite", initial_capital=1_000_000.0)
    try:
        s.record_order("o1", "NIFTY", "NSE", "BUY", 50, 22_500.0, status="COMPLETE")
        s.record_order("oP", "TCS", "NSE", "BUY", 1, 3000.0, status="PENDING")
        s._conn.execute(
            """INSERT INTO trades
               (trade_id, order_id, symbol, exchange, action, quantity, price,
                product, strategy, traded_at)
               VALUES ('t1', 'o1', 'NIFTY', 'NSE', 'BUY', 50, 22500, 'MIS', '', 1)"""
        )
        s.upsert_position("p1", "NIFTY", "NSE", net_qty=50, realised_pnl=1200.0)
        s.record_mtm("p1", 1.0, 22_510.0, 50, 500.0)
        s._conn.execute(
            """INSERT INTO sandbox_config
               (id, starting_capital, equity_leverage, futures_leverage,
                option_buy_leverage, option_sell_leverage, squareoff_time,
                mcx_squareoff_time, updated_at)
               VALUES ('default', 750000, 1, 1, 1, 1, '15:15', '23:25', 1)"""
        )
        s._conn.execute("UPDATE capital SET current = 950000.0, used_margin = 50000.0 WHERE id='default'")
    finally:
        s.close()


def test_reset_archives_and_clears(tmp_path: Path) -> None:
    _seed(tmp_path)
    out = reset(tmp_path, initial_capital=1_000_000.0)
    archive = Path(out["archived_to"])
    assert archive.exists()
    lines = [json.loads(line) for line in archive.read_text().splitlines()]
    assert any(r.get("_table") == "orders" and r.get("order_id") == "o1" for r in lines)
    assert any(r.get("_table") == "orders" and r.get("order_id") == "oP" for r in lines)
    assert any(r.get("_table") == "trades" and r.get("trade_id") == "t1" for r in lines)
    assert any(r.get("_table") == "positions" and r.get("position_id") == "p1" for r in lines)
    assert any(r.get("_table") == "mtm" and r.get("id") for r in lines)

    s = StateStore(tmp_path / "sandbox" / "state.sqlite")
    try:
        assert s.get_positions(open_only=False) == []       # positions cleared
        assert s._conn.execute("SELECT COUNT(*) FROM mtm").fetchone()[0] == 0
        assert s.get_orders() == []
        assert s._conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0
        cap = s.get_capital()
        assert cap["initial"] == 750_000.0
        assert cap["current"] == 750_000.0 and cap["used_margin"] == 0.0
        pnl = s._conn.execute("SELECT net_pnl, total_trades FROM pnl").fetchone()
        assert pnl is not None and pnl[0] == pytest.approx(1200.0)
        assert pnl[1] == 1
    finally:
        s.close()


def test_reset_atomic_rollback_on_fsync_failure(tmp_path: Path, monkeypatch) -> None:
    """If fsync fails mid-archive, no archive file is published and rows stay."""
    _seed(tmp_path)

    def _boom(_fd):  # noqa: ANN001
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(os, "fsync", _boom)
    with pytest.raises(OSError, match="simulated fsync failure"):
        reset(tmp_path)

    session_archive = next((tmp_path / "sandbox" / "sessions").glob("*.jsonl"), None)
    assert session_archive is None  # nothing published

    s = StateStore(tmp_path / "sandbox" / "state.sqlite")
    try:
        assert len(s.get_positions(open_only=False)) == 1     # rows intact
        assert s._conn.execute("SELECT COUNT(*) FROM mtm").fetchone()[0] == 1
        assert len(s.get_orders()) == 2
    finally:
        s.close()


def test_reset_idempotent_same_day(tmp_path: Path) -> None:
    _seed(tmp_path)
    first = reset(tmp_path)
    first_archive = Path(first["archived_to"]).read_text()
    second = reset(tmp_path)
    assert first["session_date"] == second["session_date"]
    assert Path(second["archived_to"]).read_text() == first_archive
    s = StateStore(tmp_path / "sandbox" / "state.sqlite")
    try:
        assert s.get_positions(open_only=False) == []   # still clear, no error
        assert s._conn.execute("SELECT net_pnl, total_trades FROM pnl").fetchone() == (1200.0, 1)
    finally:
        s.close()


# --- sandbox migration (§9.1) fresh-install path ----------------------------


def test_sandbox_migrate_fresh_install(tmp_path: Path) -> None:
    """No legacy sandbox.duckdb → migrate() creates the canonical state.sqlite."""
    mig = _load_sandbox_migrator()
    rc = mig.migrate(tmp_path)
    assert rc == 0
    db = tmp_path / "sandbox" / "state.sqlite"
    assert db.exists()
    conn = sqlite3.connect(db)
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"capital", "orders", "positions", "pnl", "mtm"} <= names
        cap = conn.execute("SELECT current FROM capital WHERE id='default'").fetchone()
        assert cap is not None and cap[0] == 1_000_000.0
    finally:
        conn.close()


def test_sandbox_migrate_idempotent(tmp_path: Path) -> None:
    mig = _load_sandbox_migrator()
    assert mig.migrate(tmp_path) == 0
    assert mig.migrate(tmp_path) == 0  # second run is a no-op


def test_legacy_engine_sandbox_migrates_into_existing_pristine_sqlite(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "data" / "engine-sandbox" / "default.duckdb"
    target = tmp_path / "sandbox" / "state.sqlite"
    archive_dir = tmp_path / "archive" / "migrations"
    _seed_legacy_duckdb(legacy)
    StateStore(target).close()  # Existing target must not suppress migration.

    result = migrate_legacy_sandbox(legacy, target, archive_dir)

    assert result["status"] == "migrated"
    assert not legacy.exists()
    assert Path(result["archive_path"]).exists()
    with sqlite3.connect(target) as conn:
        capital = conn.execute(
            "SELECT initial, current, used_margin FROM capital WHERE id = 'default'"
        ).fetchone()
        assert capital == (250_000.0, 250_100.0, 1_500.0)
        assert conn.execute(
            "SELECT starting_capital FROM sandbox_config WHERE id = 'default'"
        ).fetchone() == (250_000.0,)
        assert conn.execute(
            "SELECT filled_qty, avg_fill_px, strategy FROM orders WHERE order_id = 'old-order'"
        ).fetchone() == (2, 101.0, "legacy")
        assert conn.execute(
            "SELECT price FROM trades WHERE trade_id = 'old-trade'"
        ).fetchone() == (101.0,)
        assert conn.execute(
            "SELECT realised_pnl, unrealised_pnl FROM positions"
        ).fetchone() == (10.0, 2.0)
        assert conn.execute(
            "SELECT net_pnl, total_trades FROM pnl WHERE session_date = '2026-07-14'"
        ).fetchone() == (12.0, 1)


def test_legacy_engine_sandbox_conflict_keeps_both_databases(tmp_path: Path) -> None:
    legacy = tmp_path / "data" / "engine-sandbox" / "default.duckdb"
    target = tmp_path / "sandbox" / "state.sqlite"
    archive_dir = tmp_path / "archive" / "migrations"
    _seed_legacy_duckdb(legacy)
    with StateStore(target) as store:
        store.record_order("current-order", "TCS", "NSE", "BUY", 1, 3_000.0)

    with pytest.raises(LegacySandboxConflict, match="both contain session state"):
        migrate_legacy_sandbox(legacy, target, archive_dir)

    assert legacy.exists()
    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT order_id FROM orders").fetchall() == [
            ("current-order",)
        ]


def test_legacy_funds_only_customisation_is_migrated(tmp_path: Path) -> None:
    legacy = tmp_path / "data" / "engine-sandbox" / "default.duckdb"
    target = tmp_path / "sandbox" / "state.sqlite"
    archive_dir = tmp_path / "archive" / "migrations"
    _seed_legacy_duckdb(legacy)
    with duckdb.connect(str(legacy)) as conn:
        for table in (
            "sandbox_daily_pnl",
            "sandbox_positions",
            "sandbox_trades",
            "sandbox_orders",
        ):
            conn.execute(f"DELETE FROM {table}")

    result = migrate_legacy_sandbox(legacy, target, archive_dir)

    assert result["status"] == "migrated"
    with sqlite3.connect(target) as conn:
        assert conn.execute(
            "SELECT initial, current, used_margin FROM capital"
        ).fetchone() == (250_000.0, 250_100.0, 1_500.0)


def test_legacy_negative_position_is_preserved_for_manual_recovery(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "data" / "engine-sandbox" / "default.duckdb"
    target = tmp_path / "sandbox" / "state.sqlite"
    archive_dir = tmp_path / "archive" / "migrations"
    _seed_legacy_duckdb(legacy)
    with duckdb.connect(str(legacy)) as conn:
        conn.execute("UPDATE sandbox_positions SET net_qty = -2")

    with pytest.raises(LegacySandboxConflict, match="short position"):
        migrate_legacy_sandbox(legacy, target, archive_dir)

    assert legacy.exists()
    assert not archive_dir.exists()


def test_migration_marker_does_not_match_a_replacement_database(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "data" / "engine-sandbox" / "default.duckdb"
    target = tmp_path / "sandbox" / "state.sqlite"
    archive_dir = tmp_path / "archive" / "migrations"
    _seed_legacy_duckdb(legacy)
    migrate_legacy_sandbox(legacy, target, archive_dir)
    _seed_legacy_duckdb(legacy)
    with duckdb.connect(str(legacy)) as conn:
        conn.execute("UPDATE sandbox_orders SET order_id = 'replacement-order'")
        conn.execute(
            "UPDATE sandbox_trades SET trade_id = 'replacement-trade', "
            "order_id = 'replacement-order'"
        )

    with pytest.raises(LegacySandboxConflict, match="both contain session state"):
        migrate_legacy_sandbox(legacy, target, archive_dir)

    assert legacy.exists()
