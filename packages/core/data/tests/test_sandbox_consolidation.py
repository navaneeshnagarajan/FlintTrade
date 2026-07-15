"""Feature-union regressions for the canonical Practice sandbox."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import flinttrade_data.sandbox_engine as sandbox_mod


_PRE_MERGE_SCHEMA = """
CREATE TABLE capital (
    id TEXT PRIMARY KEY, initial REAL NOT NULL, current REAL NOT NULL,
    used_margin REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE orders (
    order_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, exchange TEXT NOT NULL,
    action TEXT NOT NULL, quantity INTEGER NOT NULL, price REAL NOT NULL,
    product TEXT NOT NULL, status TEXT NOT NULL, filled_qty INTEGER NOT NULL,
    avg_fill_px REAL, created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE positions (
    position_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, exchange TEXT NOT NULL,
    product TEXT NOT NULL, net_qty INTEGER NOT NULL, avg_price REAL NOT NULL,
    buy_qty INTEGER NOT NULL, buy_value REAL NOT NULL, sell_qty INTEGER NOT NULL,
    sell_value REAL NOT NULL, realised_pnl REAL NOT NULL,
    unrealised_pnl REAL NOT NULL, updated_at REAL NOT NULL,
    UNIQUE (symbol, exchange, product)
);
CREATE TABLE pnl (
    session_date TEXT PRIMARY KEY, realised_total REAL NOT NULL,
    unrealised_total REAL NOT NULL, gross_pnl REAL NOT NULL,
    charges REAL NOT NULL, net_pnl REAL NOT NULL, high_water_mark REAL NOT NULL,
    max_drawdown REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE mtm (
    id INTEGER PRIMARY KEY AUTOINCREMENT, position_id TEXT NOT NULL,
    tick_ts REAL NOT NULL, ltp REAL NOT NULL, qty INTEGER NOT NULL,
    unrealised REAL NOT NULL
);
"""


def test_workspace_default_preserves_legacy_practice_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy = tmp_path / "legacy" / "sandbox" / "state.sqlite"
    legacy.parent.mkdir(parents=True)
    original = sandbox_mod.SandboxEngine(
        db_path=str(legacy),
        initial_capital=125_000.0,
    )
    try:
        original.place_order("RELIANCE", "NSE", "BUY", 1, 2_500.0, product="CNC")
    finally:
        original.close()

    for name in (
        "SANDBOX_STATE_PATH",
        "SANDBOX_DB_PATH",
        "FLINTTRADE_HOME",
        "FLINTTRADE_WORKSPACE_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    from flinttrade_core import workspace

    target_home = tmp_path / "platform-workspace"
    monkeypatch.setattr(workspace, "_default_home", lambda: target_home)
    monkeypatch.setattr(workspace, "_legacy_sandbox_state_path", lambda: legacy)

    migrated = sandbox_mod.SandboxEngine()
    try:
        assert migrated.get_capital()["initial"] == 125_000.0
        assert [order["symbol"] for order in migrated.get_all_orders()] == ["RELIANCE"]
    finally:
        migrated.close()

    assert legacy.exists()
    assert (target_home / "sandbox" / "state.sqlite").exists()


def test_sandbox_config_persists_and_drives_leverage(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite"
    config = sandbox_mod.SandboxConfig(
        starting_capital=100_000.0,
        equity_leverage=5,
        futures_leverage=2,
        option_buy_leverage=1,
        option_sell_leverage=1,
        squareoff_time="15:10",
        mcx_squareoff_time="23:20",
    )
    engine = sandbox_mod.SandboxEngine(db_path=str(db_path), config=config)
    try:
        result = engine.place_order(
            "RELIANCE",
            "NSE",
            "BUY",
            100,
            1_000.0,
            product="CNC",
        )
        assert result["status"] == "COMPLETE"
        assert engine.get_capital()["used_margin"] == pytest.approx(20_000.0)
        engine.update_config(equity_leverage=4, squareoff_time="15:05")
    finally:
        engine.close()

    reopened = sandbox_mod.SandboxEngine(db_path=str(db_path))
    try:
        assert reopened.config.equity_leverage == 4
        assert reopened.config.squareoff_time == "15:05"
        assert reopened.config.starting_capital == 100_000.0
    finally:
        reopened.close()


def test_limit_order_reserves_margin_then_fills_from_exchange_qualified_tick() -> None:
    engine = sandbox_mod.SandboxEngine(
        db_path=":memory:",
        config=sandbox_mod.SandboxConfig(
            starting_capital=100_000.0,
            equity_leverage=2,
        ),
    )
    try:
        result = engine.place_order(
            "INFY",
            "NSE",
            "BUY",
            10,
            1_000.0,
            order_type="LIMIT",
            strategy="test-limit",
        )
        assert result["status"] == "PENDING"
        assert engine.get_positions() == []
        assert engine.get_trades() == []
        assert engine.get_capital()["used_margin"] == pytest.approx(5_000.0)

        assert engine.check_pending_fills({"NSE:INFY": 1_010.0}) == []
        assert engine.check_pending_fills({"NSE:INFY": 990.0}) == [result["order_id"]]

        order = engine.get_orders()[0]
        assert order["status"] == "COMPLETE"
        assert order["order_type"] == "LIMIT"
        assert order["pricetype"] == "LIMIT"
        assert order["strategy"] == "test-limit"
        assert order["avg_fill_px"] == pytest.approx(1_000.0)
        assert len(engine.get_trades()) == 1
        assert engine.get_positions()[0]["net_qty"] == 10
        assert engine.get_capital()["used_margin"] == pytest.approx(5_000.0)
    finally:
        engine.close()


def test_pending_sell_orders_cannot_overcommit_a_covered_position() -> None:
    engine = sandbox_mod.SandboxEngine(db_path=":memory:")
    try:
        assert engine.place_order("ITC", "NSE", "BUY", 10, 400.0)["status"] == "COMPLETE"
        first = engine.place_order(
            "ITC",
            "NSE",
            "SELL",
            8,
            420.0,
            order_type="LIMIT",
        )
        second = engine.place_order(
            "ITC",
            "NSE",
            "SELL",
            3,
            425.0,
            order_type="LIMIT",
        )

        assert first["status"] == "PENDING"
        assert second["status"] == "REJECTED"
        assert "pending" in second["message"].lower()
        assert engine.get_positions()[0]["net_qty"] == 10
    finally:
        engine.close()


def test_pending_order_modify_and_cancel_are_real_state_changes() -> None:
    engine = sandbox_mod.SandboxEngine(db_path=":memory:")
    try:
        placed = engine.place_order(
            "TCS",
            "NSE",
            "BUY",
            5,
            3_500.0,
            order_type="SL",
            trigger_price=3_450.0,
        )
        modified = engine.modify_order(
            placed["order_id"],
            quantity=4,
            price=3_480.0,
            trigger_price=3_440.0,
        )
        assert modified["status"] == "PENDING"
        order = engine.get_orders()[0]
        assert order["quantity"] == 4
        assert order["price"] == pytest.approx(3_480.0)
        assert order["trigger_price"] == pytest.approx(3_440.0)

        cancelled = engine.cancel_order(placed["order_id"])
        assert cancelled["status"] == "CANCELLED"
        assert engine.get_orders()[0]["status"] == "CANCELLED"
        assert engine.get_capital()["used_margin"] == 0.0
        assert engine.check_pending_fills({"NSE:TCS": 3_500.0}) == []
    finally:
        engine.close()


def test_process_tick_marks_positions_and_fills_stop_market_orders() -> None:
    engine = sandbox_mod.SandboxEngine(db_path=":memory:")
    try:
        assert engine.place_order("SBIN", "NSE", "BUY", 10, 600.0)["status"] == "COMPLETE"
        stop = engine.place_order(
            "SBIN",
            "NSE",
            "SELL",
            4,
            580.0,
            order_type="SL-M",
            trigger_price=590.0,
            strategy="protective-stop",
        )
        assert stop["status"] == "PENDING"

        assert engine.process_tick("NSE", "SBIN", 610.0) == []
        assert engine.get_positions()[0]["unrealised_pnl"] == pytest.approx(100.0)
        assert engine.get_pnl()["total"] == pytest.approx(100.0)

        assert engine.process_tick("NSE", "SBIN", 585.0) == [stop["order_id"]]
        position = engine.get_positions()[0]
        assert position["net_qty"] == 6
        assert position["realised_pnl"] == pytest.approx(-60.0)
        assert position["unrealised_pnl"] == pytest.approx(-90.0)
        assert engine.get_trades()[-1]["strategy"] == ""
        assert engine.get_trades()[0]["strategy"] == "protective-stop"
        assert engine.get_pnl_history()[0]["realised"] == pytest.approx(-60.0)
    finally:
        engine.close()


def test_square_off_is_all_or_nothing_and_uses_current_ltp() -> None:
    engine = sandbox_mod.SandboxEngine(db_path=":memory:")
    try:
        engine.place_order("INFY", "NSE", "BUY", 10, 1_000.0)
        engine.place_order("TCS", "NSE", "BUY", 5, 2_000.0)

        with pytest.raises(ValueError, match="TCS"):
            engine.square_off_all({"NSE:INFY": 1_010.0})
        assert len(engine.get_positions()) == 2
        assert len(engine.get_trades()) == 2

        assert engine.square_off_all(
            {"NSE:INFY": 1_010.0, "NSE:TCS": 1_990.0}
        ) == 2
        assert engine.get_positions() == []
        assert len(engine.get_trades()) == 4
        assert engine.get_pnl()["realised"] == pytest.approx(50.0)
        history = engine.get_pnl_history()
        assert history[0]["realised"] == pytest.approx(50.0)
        assert history[0]["total_trades"] == 4
    finally:
        engine.close()


def test_pre_merge_sqlite_schema_is_migrated_in_place(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-state.sqlite"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(_PRE_MERGE_SCHEMA)
        connection.execute(
            "INSERT INTO capital VALUES ('default', 750000, 750000, 0, 1)"
        )

    engine = sandbox_mod.SandboxEngine(db_path=str(db_path))
    try:
        order_columns = {
            row[1] for row in engine._conn.execute("PRAGMA table_info(orders)").fetchall()
        }
        pnl_columns = {
            row[1] for row in engine._conn.execute("PRAGMA table_info(pnl)").fetchall()
        }
        tables = {
            row[0]
            for row in engine._conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert {"trigger_price", "pricetype", "strategy", "fill_time"} <= order_columns
        assert "total_trades" in pnl_columns
        assert {"trades", "sandbox_config"} <= tables
        assert engine.get_capital()["initial"] == 750_000.0
        assert engine.config.starting_capital == 750_000.0
        assert engine.place_order(
            "INFY", "NSE", "BUY", 1, 1_500.0, order_type="LIMIT"
        )["status"] == "PENDING"
    finally:
        engine.close()


def test_version_two_export_import_preserves_feature_union() -> None:
    source = sandbox_mod.SandboxEngine(
        db_path=":memory:",
        config=sandbox_mod.SandboxConfig(
            starting_capital=250_000.0,
            equity_leverage=4,
            squareoff_time="15:05",
        ),
    )
    target = sandbox_mod.SandboxEngine(db_path=":memory:")
    try:
        source.place_order("ITC", "NSE", "BUY", 10, 400.0, strategy="roundtrip")
        source.process_tick("NSE", "ITC", 410.0)
        payload = json.loads(source.export_data())
        assert payload["schema_version"] == 2
        assert payload["config"]["equity_leverage"] == 4
        assert len(payload["trades"]) == 1
        assert len(payload["pnl_history"]) == 1

        stats = target.import_data(json.dumps(payload))
        assert stats["trades_imported"] == 1
        assert stats["pnl_days_imported"] == 1
        assert target.config.equity_leverage == 4
        assert target.config.squareoff_time == "15:05"
        assert target.get_trades()[0]["strategy"] == "roundtrip"
        assert target.get_pnl_history()[0]["unrealised"] == pytest.approx(100.0)
    finally:
        source.close()
        target.close()


def test_capital_adjustment_cannot_cross_committed_margin() -> None:
    engine = sandbox_mod.SandboxEngine(db_path=":memory:", initial_capital=100_000.0)
    try:
        engine.place_order("INFY", "NSE", "BUY", 10, 1_000.0)
        with pytest.raises(ValueError, match="committed margin"):
            engine.adjust_capital(-95_000.0)
        assert engine.get_capital()["current"] == pytest.approx(100_000.0)

        with pytest.raises(ValueError, match="finite"):
            engine.adjust_capital(float("nan"))
    finally:
        engine.close()


def test_reset_backs_up_and_clears_the_complete_practice_ledger() -> None:
    engine = sandbox_mod.SandboxEngine(
        db_path=":memory:",
        config=sandbox_mod.SandboxConfig(
            starting_capital=200_000.0,
            equity_leverage=2,
        ),
    )
    try:
        engine.place_order("ITC", "NSE", "BUY", 10, 400.0, strategy="reset-check")
        engine.process_tick("NSE", "ITC", 410.0)

        backup = engine.reset()

        assert backup["config"]["equity_leverage"] == 2
        assert len(backup["trades"]) == 1
        assert len(backup["pnl_history"]) == 1
        assert engine.get_orders() == []
        assert engine.get_positions() == []
        assert engine.get_trades() == []
        assert engine.get_pnl_history() == []
        assert engine.get_capital() == {
            "initial": 200_000.0,
            "current": 200_000.0,
            "available": 200_000.0,
            "used_margin": 0.0,
        }
        assert engine.config.equity_leverage == 2
    finally:
        engine.close()


def test_futures_and_option_buys_use_their_configured_leverage() -> None:
    engine = sandbox_mod.SandboxEngine(
        db_path=":memory:",
        config=sandbox_mod.SandboxConfig(
            starting_capital=1_000_000.0,
            futures_leverage=5,
            option_buy_leverage=2,
        ),
    )
    try:
        engine.place_order("NIFTY26JULFUT", "NFO", "BUY", 10, 20_000.0, product="NRML")
        assert engine.get_capital()["used_margin"] == pytest.approx(40_000.0)

        engine.place_order("NIFTY26JUL25000CE", "NFO", "BUY", 50, 100.0, product="NRML")
        assert engine.get_capital()["used_margin"] == pytest.approx(42_500.0)
    finally:
        engine.close()


def test_limit_sell_and_stop_limit_respect_executable_tick_prices() -> None:
    engine = sandbox_mod.SandboxEngine(db_path=":memory:")
    try:
        engine.place_order("INFY", "NSE", "BUY", 10, 1_500.0)
        limit_sell = engine.place_order(
            "INFY", "NSE", "SELL", 4, 1_550.0, order_type="LIMIT"
        )
        assert engine.check_pending_fills({"NSE:INFY": 1_540.0}) == []
        assert engine.check_pending_fills({"NSE:INFY": 1_560.0}) == [limit_sell["order_id"]]

        stop_limit = engine.place_order(
            "INFY",
            "NSE",
            "SELL",
            3,
            1_480.0,
            order_type="SL",
            trigger_price=1_490.0,
        )
        assert engine.check_pending_fills({"NSE:INFY": 1_470.0}) == []
        assert engine.check_pending_fills({"NSE:INFY": 1_485.0}) == [stop_limit["order_id"]]
    finally:
        engine.close()


def test_stop_limit_remains_triggered_until_its_limit_becomes_executable() -> None:
    engine = sandbox_mod.SandboxEngine(db_path=":memory:")
    try:
        stop_limit = engine.place_order(
            "INFY",
            "NSE",
            "BUY",
            1,
            105.0,
            order_type="SL",
            trigger_price=100.0,
        )

        assert engine.check_pending_fills({"NSE:INFY": 110.0}) == []
        triggered = engine.get_orders()[0]
        assert triggered["status"] == "PENDING"
        assert triggered["stop_triggered"] is True

        assert engine.check_pending_fills({"NSE:INFY": 99.0}) == [
            stop_limit["order_id"]
        ]
        assert engine.get_orders()[0]["avg_fill_px"] == pytest.approx(105.0)
    finally:
        engine.close()


def test_gap_stop_market_fill_revalidates_available_capital() -> None:
    engine = sandbox_mod.SandboxEngine(
        db_path=":memory:",
        config=sandbox_mod.SandboxConfig(starting_capital=100.0),
    )
    try:
        stop = engine.place_order(
            "ITC",
            "NSE",
            "BUY",
            1,
            100.0,
            order_type="SL-M",
            trigger_price=100.0,
        )
        assert stop["status"] == "PENDING"

        assert engine.check_pending_fills({"NSE:ITC": 200.0}) == []
        assert engine.get_orders()[0]["status"] == "REJECTED"
        assert engine.get_positions() == []
        assert engine.get_trades() == []
        assert engine.get_capital()["used_margin"] == 0.0
    finally:
        engine.close()


def test_config_update_is_atomic_and_keeps_capital_consistent() -> None:
    engine = sandbox_mod.SandboxEngine(
        db_path=":memory:",
        config=sandbox_mod.SandboxConfig(
            starting_capital=1_000.0,
            equity_leverage=2,
        ),
    )
    try:
        engine.place_order("ITC", "NSE", "BUY", 15, 100.0)
        assert engine.get_capital()["used_margin"] == pytest.approx(750.0)

        with pytest.raises(ValueError, match="committed margin"):
            engine.update_config(equity_leverage=1)

        assert engine.config.equity_leverage == 2
        assert engine.get_capital() == {
            "initial": 1_000.0,
            "current": 1_000.0,
            "available": 250.0,
            "used_margin": 750.0,
        }

        engine.update_config(starting_capital=2_000.0)
        assert engine.get_capital() == {
            "initial": 2_000.0,
            "current": 2_000.0,
            "available": 1_250.0,
            "used_margin": 750.0,
        }
    finally:
        engine.close()


def test_legacy_funds_and_read_aliases_remain_available() -> None:
    engine = sandbox_mod.SandboxEngine(db_path=":memory:")
    try:
        engine.place_order("ITC", "NSE", "BUY", 10, 400.0)
        engine.process_tick("NSE", "ITC", 410.0)

        funds = engine.get_funds()
        order = engine.get_orders()[0]
        position = engine.get_positions()[0]
        history = engine.get_pnl_history()[0]

        assert funds["starting_capital"] == pytest.approx(1_000_000.0)
        assert funds["available_balance"] == pytest.approx(996_000.0)
        assert funds["total_equity"] == pytest.approx(1_000_100.0)
        assert order["fill_price"] == order["avg_fill_px"]
        assert position["realized_pnl"] == position["realised_pnl"]
        assert position["unrealized_pnl"] == position["unrealised_pnl"]
        assert history["recorded_at"] == history["updated_at"]
    finally:
        engine.close()


def test_version_one_import_synthesises_the_trade_ledger() -> None:
    engine = sandbox_mod.SandboxEngine(db_path=":memory:")
    payload = {
        "schema_version": 1,
        "capital": {"initial": 100_000.0, "current": 100_000.0},
        "positions": [],
        "orders": [{
            "order_id": "OLD-1",
            "symbol": "INFY",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": 2,
            "price": 1_500.0,
            "product": "MIS",
            "status": "COMPLETE",
            "created_at": "2026-07-14T10:00:00+00:00",
        }],
    }
    try:
        stats = engine.import_data(json.dumps(payload))

        assert stats["trades_imported"] == 1
        assert engine.get_trades()[0]["order_id"] == "OLD-1"
        assert engine.get_trades()[0]["price"] == pytest.approx(1_500.0)
    finally:
        engine.close()


def test_import_rejects_unknown_future_schema_version() -> None:
    engine = sandbox_mod.SandboxEngine(db_path=":memory:")
    try:
        with pytest.raises(ValueError, match="schema version"):
            engine.import_data(json.dumps({"schema_version": 3}))
    finally:
        engine.close()
