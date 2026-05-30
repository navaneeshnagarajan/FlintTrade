"""Native sandbox state-store tests (data-layer §9.2 / §9.4; Database H7 + H10)."""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
from pathlib import Path

import pytest

from flinttrade_data.state_store import StateStore, reset


def _load_sandbox_migrator():
    path = Path(__file__).resolve().parents[4] / "scripts" / "migrate-sandbox-duckdb-to-sqlite.py"
    spec = importlib.util.spec_from_file_location("migrate_sandbox", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
        s.upsert_position("p1", "NIFTY", "NSE", net_qty=50, realised_pnl=1200.0)
        s.record_mtm("p1", 1.0, 22_510.0, 50, 500.0)
        s._conn.execute("UPDATE capital SET current = 950000.0, used_margin = 50000.0 WHERE id='default'")
    finally:
        s.close()


def test_reset_archives_and_clears(tmp_path: Path) -> None:
    _seed(tmp_path)
    out = reset(tmp_path, initial_capital=1_000_000.0)
    archive = Path(out["archived_to"])
    assert archive.exists()
    lines = [json.loads(line) for line in archive.read_text().splitlines()]
    assert any(r.get("order_id") == "o1" for r in lines)   # COMPLETE order archived

    s = StateStore(tmp_path / "sandbox" / "state.sqlite")
    try:
        assert s.get_positions(open_only=False) == []       # positions cleared
        assert s._conn.execute("SELECT COUNT(*) FROM mtm").fetchone()[0] == 0
        # PENDING order survives, COMPLETE one removed
        ids = {o["order_id"] for o in s.get_orders()}
        assert ids == {"oP"}
        cap = s.get_capital()
        assert cap["current"] == 1_000_000.0 and cap["used_margin"] == 0.0
        pnl = s._conn.execute("SELECT net_pnl FROM pnl").fetchone()
        assert pnl is not None and pnl[0] == pytest.approx(1200.0)
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
    second = reset(tmp_path)
    assert first["session_date"] == second["session_date"]
    s = StateStore(tmp_path / "sandbox" / "state.sqlite")
    try:
        assert s.get_positions(open_only=False) == []   # still clear, no error
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
