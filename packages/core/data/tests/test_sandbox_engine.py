"""Tests for SandboxEngine — virtual paper trading engine.

Run with:
    python -m pytest packages/core/data/tests/test_sandbox_engine.py -v --tb=short --import-mode=importlib
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from flinttrade_data.sandbox_engine import SandboxEngine

_DEFAULT_CAPITAL = 1_000_000.0


@pytest.fixture
def engine() -> SandboxEngine:
    """Fresh in-memory SandboxEngine for each test."""
    return SandboxEngine(db_path=":memory:")


# ---------------------------------------------------------------------------
# Capital
# ---------------------------------------------------------------------------


class TestInitialCapital:
    """Engine starts with correct default capital."""

    def test_engine_uses_sqlite_even_when_duckdb_is_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import flinttrade_data.sandbox_engine as sandbox_mod

        monkeypatch.setattr(sandbox_mod, "_DUCKDB_AVAILABLE", False, raising=False)
        try:
            eng = SandboxEngine(db_path=":memory:")
        except ImportError as exc:
            pytest.fail(f"SandboxEngine should use SQLite state.sqlite, not DuckDB: {exc}")
        finally:
            if "eng" in locals():
                eng.close()

    def test_file_backed_engine_creates_canonical_state_sqlite_schema(self, tmp_path: Path) -> None:
        db_path = tmp_path / "sandbox" / "state.sqlite"
        eng = SandboxEngine(db_path=str(db_path))
        try:
            eng.place_order("RELIANCE", "NSE", "BUY", 1, 2800.0)
        finally:
            eng.close()

        assert db_path.exists()
        with sqlite3.connect(db_path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert {"capital", "orders", "positions", "pnl", "mtm"} <= tables
        assert {"sandbox_capital", "sandbox_orders", "sandbox_positions"}.isdisjoint(tables)

    def test_initial_capital_is_one_million(self, engine: SandboxEngine) -> None:
        cap = engine.get_capital()
        assert cap["initial"] == _DEFAULT_CAPITAL
        assert cap["current"] == _DEFAULT_CAPITAL

    def test_initial_available_equals_current(self, engine: SandboxEngine) -> None:
        cap = engine.get_capital()
        assert cap["available"] == cap["current"]

    def test_initial_used_margin_is_zero(self, engine: SandboxEngine) -> None:
        cap = engine.get_capital()
        assert cap["used_margin"] == 0.0

    def test_custom_initial_capital(self) -> None:
        eng = SandboxEngine(db_path=":memory:", initial_capital=500_000.0)
        cap = eng.get_capital()
        assert cap["initial"] == 500_000.0
        assert cap["current"] == 500_000.0


# ---------------------------------------------------------------------------
# adjust_capital
# ---------------------------------------------------------------------------


class TestAdjustCapital:
    """Capital can be increased or decreased."""

    def test_add_capital_increases_current(self, engine: SandboxEngine) -> None:
        cap = engine.adjust_capital(50_000.0)
        assert cap["current"] == _DEFAULT_CAPITAL + 50_000.0

    def test_remove_capital_decreases_current(self, engine: SandboxEngine) -> None:
        cap = engine.adjust_capital(-200_000.0)
        assert cap["current"] == _DEFAULT_CAPITAL - 200_000.0

    def test_remove_more_than_available_raises(self, engine: SandboxEngine) -> None:
        with pytest.raises(ValueError, match="Cannot remove"):
            engine.adjust_capital(-2_000_000.0)

    def test_adjust_returns_updated_capital_dict(self, engine: SandboxEngine) -> None:
        result = engine.adjust_capital(10_000.0)
        assert "initial" in result
        assert "current" in result
        assert "available" in result
        assert "used_margin" in result


# ---------------------------------------------------------------------------
# place_order — BUY
# ---------------------------------------------------------------------------


class TestPlaceBuyOrder:
    """BUY orders deduct from available capital via used_margin."""

    def test_buy_order_returns_complete_status(self, engine: SandboxEngine) -> None:
        result = engine.place_order("RELIANCE", "NSE", "BUY", 10, 2800.0)
        assert result["status"] == "COMPLETE"
        assert result["order_id"] != ""

    def test_buy_order_increases_used_margin(self, engine: SandboxEngine) -> None:
        # 10 lots at 450 = ₹4,500 — well within default ₹10,00,000 capital
        engine.place_order("COALINDIA", "NSE", "BUY", 10, 450.0)
        cap = engine.get_capital()
        assert cap["used_margin"] > 0

    def test_buy_order_reduces_available_capital(self, engine: SandboxEngine) -> None:
        engine.place_order("INFY", "NSE", "BUY", 100, 1800.0)
        cap = engine.get_capital()
        assert cap["available"] < _DEFAULT_CAPITAL

    def test_buy_creates_position(self, engine: SandboxEngine) -> None:
        engine.place_order("TCS", "NSE", "BUY", 5, 3500.0)
        positions = engine.get_positions()
        assert len(positions) == 1
        assert positions[0]["symbol"] == "TCS"
        assert positions[0]["net_qty"] == 5

    def test_multiple_buys_aggregate_position(self, engine: SandboxEngine) -> None:
        engine.place_order("HDFC", "NSE", "BUY", 10, 1600.0)
        engine.place_order("HDFC", "NSE", "BUY", 5, 1620.0)
        positions = engine.get_positions()
        assert len(positions) == 1
        assert positions[0]["net_qty"] == 15

    def test_buy_order_rejected_when_insufficient_capital(self, engine: SandboxEngine) -> None:
        # Price * qty > initial_capital
        result = engine.place_order("NIFTY", "NSE_INDEX", "BUY", 1000, 50_000.0)
        assert result["status"] == "REJECTED"
        assert "Insufficient capital" in result["message"]

    def test_rejected_buy_does_not_change_capital(self, engine: SandboxEngine) -> None:
        engine.place_order("EXPENSIVE", "NSE", "BUY", 10000, 10_000.0)
        cap = engine.get_capital()
        assert cap["available"] == _DEFAULT_CAPITAL

    def test_zero_price_order_rejected(self, engine: SandboxEngine) -> None:
        # A zero price would fabricate a fill (and position) at 0.0 and skip the
        # capital check — reject rather than book a fictitious fill.
        result = engine.place_order("RELIANCE", "NSE", "BUY", 10, 0.0)
        assert result["status"] == "REJECTED"
        assert "live price" in result["message"].lower()

    def test_zero_price_order_does_not_create_position(self, engine: SandboxEngine) -> None:
        engine.place_order("RELIANCE", "NSE", "BUY", 10, 0.0)
        assert engine.get_positions() == []


# ---------------------------------------------------------------------------
# place_order — SELL
# ---------------------------------------------------------------------------


class TestPlaceSellOrder:
    """SELL orders close or reduce an existing position."""

    def test_sell_existing_position_returns_complete(self, engine: SandboxEngine) -> None:
        engine.place_order("WIPRO", "NSE", "BUY", 20, 450.0)
        result = engine.place_order("WIPRO", "NSE", "SELL", 20, 460.0)
        assert result["status"] == "COMPLETE"

    def test_sell_reduces_net_qty(self, engine: SandboxEngine) -> None:
        engine.place_order("HDFCBANK", "NSE", "BUY", 30, 1500.0)
        engine.place_order("HDFCBANK", "NSE", "SELL", 10, 1510.0)
        positions = engine.get_positions()
        assert positions[0]["net_qty"] == 20

    def test_sell_all_removes_open_position(self, engine: SandboxEngine) -> None:
        engine.place_order("BAJAJ", "NSE", "BUY", 10, 7000.0)
        engine.place_order("BAJAJ", "NSE", "SELL", 10, 7100.0)
        # Position still exists in DB but net_qty == 0 → not returned by get_positions
        positions = engine.get_positions()
        assert all(p["net_qty"] != 0 for p in positions)

    def test_sell_realises_pnl(self, engine: SandboxEngine) -> None:
        engine.place_order("SBIN", "NSE", "BUY", 50, 600.0)
        engine.place_order("SBIN", "NSE", "SELL", 50, 620.0)
        pnl = engine.get_pnl()
        # 50 * (620 - 600) = 1000
        assert pnl["realised"] == pytest.approx(1000.0)

    def test_sell_rejected_without_position(self, engine: SandboxEngine) -> None:
        result = engine.place_order("UNKNOWN", "NSE", "SELL", 10, 100.0)
        assert result["status"] == "REJECTED"
        assert "Insufficient position" in result["message"]

    def test_sell_rejected_exceeds_holding(self, engine: SandboxEngine) -> None:
        engine.place_order("ITC", "NSE", "BUY", 5, 450.0)
        result = engine.place_order("ITC", "NSE", "SELL", 10, 455.0)
        assert result["status"] == "REJECTED"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestOrderValidation:
    """Edge cases in order validation."""

    def test_empty_symbol_rejected(self, engine: SandboxEngine) -> None:
        result = engine.place_order("", "NSE", "BUY", 1, 100.0)
        assert result["status"] == "REJECTED"

    def test_zero_quantity_rejected(self, engine: SandboxEngine) -> None:
        result = engine.place_order("NIFTY", "NSE", "BUY", 0, 24000.0)
        assert result["status"] == "REJECTED"

    def test_negative_quantity_rejected(self, engine: SandboxEngine) -> None:
        result = engine.place_order("NIFTY", "NSE", "BUY", -5, 24000.0)
        assert result["status"] == "REJECTED"

    def test_invalid_action_rejected(self, engine: SandboxEngine) -> None:
        result = engine.place_order("NIFTY", "NSE", "HOLD", 1, 24000.0)
        assert result["status"] == "REJECTED"


# ---------------------------------------------------------------------------
# get_positions
# ---------------------------------------------------------------------------


class TestGetPositions:
    """Position book reflects placed orders."""

    def test_no_positions_initially(self, engine: SandboxEngine) -> None:
        assert engine.get_positions() == []

    def test_position_has_required_keys(self, engine: SandboxEngine) -> None:
        engine.place_order("ZOMATO", "NSE", "BUY", 100, 200.0)
        pos = engine.get_positions()[0]
        for key in ("symbol", "exchange", "product", "net_qty", "avg_price",
                    "realised_pnl", "unrealised_pnl", "updated_at"):
            assert key in pos, f"Missing key: {key}"

    def test_avg_price_weighted_correctly(self, engine: SandboxEngine) -> None:
        engine.place_order("NTPC", "NSE", "BUY", 10, 200.0)
        engine.place_order("NTPC", "NSE", "BUY", 10, 220.0)
        pos = engine.get_positions()[0]
        assert pos["avg_price"] == pytest.approx(210.0)


# ---------------------------------------------------------------------------
# get_orders
# ---------------------------------------------------------------------------


class TestGetOrders:
    """Today's orders are returned correctly."""

    def test_orders_empty_initially(self, engine: SandboxEngine) -> None:
        assert engine.get_orders() == []

    def test_order_appears_after_place(self, engine: SandboxEngine) -> None:
        engine.place_order("POWERGRID", "NSE", "BUY", 100, 280.0)
        orders = engine.get_orders()
        assert len(orders) == 1
        assert orders[0]["symbol"] == "POWERGRID"

    def test_order_has_required_keys(self, engine: SandboxEngine) -> None:
        engine.place_order("ONGC", "NSE", "BUY", 50, 260.0)
        order = engine.get_orders()[0]
        for key in ("order_id", "symbol", "exchange", "action",
                    "quantity", "price", "product", "status", "created_at"):
            assert key in order, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# get_pnl
# ---------------------------------------------------------------------------


class TestGetPnl:
    """P&L aggregation."""

    def test_pnl_zero_initially(self, engine: SandboxEngine) -> None:
        pnl = engine.get_pnl()
        assert pnl["realised"] == 0.0
        assert pnl["unrealised"] == 0.0
        assert pnl["total"] == 0.0

    def test_pnl_has_required_keys(self, engine: SandboxEngine) -> None:
        pnl = engine.get_pnl()
        assert "realised" in pnl
        assert "unrealised" in pnl
        assert "total" in pnl

    def test_total_is_sum_of_realised_and_unrealised(self, engine: SandboxEngine) -> None:
        engine.place_order("COALINDIA", "NSE", "BUY", 100, 400.0)
        engine.place_order("COALINDIA", "NSE", "SELL", 50, 410.0)
        pnl = engine.get_pnl()
        assert pnl["total"] == pytest.approx(pnl["realised"] + pnl["unrealised"])

    def test_realised_pnl_correct_on_profit(self, engine: SandboxEngine) -> None:
        engine.place_order("TATASTEEL", "NSE", "BUY", 100, 130.0)
        engine.place_order("TATASTEEL", "NSE", "SELL", 100, 145.0)
        pnl = engine.get_pnl()
        # 100 * (145 - 130) = 1500
        assert pnl["realised"] == pytest.approx(1500.0)


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


class TestReset:
    """Reset clears all data and returns backup."""

    def test_reset_clears_positions(self, engine: SandboxEngine) -> None:
        engine.place_order("ADANIENT", "NSE", "BUY", 5, 2400.0)
        engine.reset()
        assert engine.get_positions() == []

    def test_reset_clears_orders(self, engine: SandboxEngine) -> None:
        engine.place_order("ADANIPORTS", "NSE", "BUY", 10, 800.0)
        engine.reset()
        assert engine.get_orders() == []

    def test_reset_restores_capital(self, engine: SandboxEngine) -> None:
        engine.place_order("BHARTIARTL", "NSE", "BUY", 10, 1000.0)
        engine.reset()
        cap = engine.get_capital()
        assert cap["current"] == _DEFAULT_CAPITAL
        assert cap["used_margin"] == 0.0
        assert cap["available"] == _DEFAULT_CAPITAL

    def test_reset_returns_backup_dict(self, engine: SandboxEngine) -> None:
        engine.place_order("CIPLA", "NSE", "BUY", 10, 1300.0)
        backup = engine.reset()
        assert "capital" in backup
        assert "positions" in backup
        assert "orders" in backup
        assert "reset_at" in backup

    def test_reset_backup_contains_pre_reset_data(self, engine: SandboxEngine) -> None:
        engine.place_order("DRREDDY", "NSE", "BUY", 5, 5500.0)
        backup = engine.reset()
        # Backup should have had one position before reset
        assert len(backup["positions"]) >= 1


# ---------------------------------------------------------------------------
# export_data
# ---------------------------------------------------------------------------


class TestExportData:
    """Export produces valid, parseable JSON."""

    def test_export_returns_string(self, engine: SandboxEngine) -> None:
        result = engine.export_data()
        assert isinstance(result, str)

    def test_export_is_valid_json(self, engine: SandboxEngine) -> None:
        result = engine.export_data()
        data = json.loads(result)
        assert isinstance(data, dict)

    def test_export_contains_required_keys(self, engine: SandboxEngine) -> None:
        data = json.loads(engine.export_data())
        for key in ("capital", "positions", "orders", "exported_at"):
            assert key in data, f"Missing key: {key}"

    def test_export_includes_capital_state(self, engine: SandboxEngine) -> None:
        data = json.loads(engine.export_data())
        assert data["capital"]["initial"] == _DEFAULT_CAPITAL

    def test_export_includes_orders(self, engine: SandboxEngine) -> None:
        engine.place_order("EICHERMOT", "NSE", "BUY", 1, 4000.0)
        data = json.loads(engine.export_data())
        assert len(data["orders"]) == 1

    def test_export_includes_positions(self, engine: SandboxEngine) -> None:
        engine.place_order("GRASIM", "NSE", "BUY", 5, 2000.0)
        data = json.loads(engine.export_data())
        assert len(data["positions"]) >= 1


# ---------------------------------------------------------------------------
# import_data
# ---------------------------------------------------------------------------


class TestImportData:
    """Import restores engine state from an export."""

    def test_import_restores_capital(self, engine: SandboxEngine) -> None:
        engine.adjust_capital(-100_000.0)
        exported = engine.export_data()
        engine2 = SandboxEngine(db_path=":memory:", initial_capital=500_000.0)
        engine2.import_data(exported)
        cap = engine2.get_capital()
        assert cap["current"] == pytest.approx(_DEFAULT_CAPITAL - 100_000.0)

    def test_import_restores_positions(self, engine: SandboxEngine) -> None:
        engine.place_order("HCLTECH", "NSE", "BUY", 20, 1200.0)
        exported = engine.export_data()
        engine2 = SandboxEngine(db_path=":memory:")
        engine2.import_data(exported)
        positions = engine2.get_all_positions()
        assert any(p["symbol"] == "HCLTECH" for p in positions)

    def test_import_returns_stats(self, engine: SandboxEngine) -> None:
        engine.place_order("HEROMOTOCO", "NSE", "BUY", 5, 4500.0)
        stats = engine.import_data(engine.export_data())
        assert "capital_imported" in stats
        assert "positions_imported" in stats
        assert "orders_imported" in stats

    def test_import_stats_count_matches_export(self, engine: SandboxEngine) -> None:
        engine.place_order("HINDALCO", "NSE", "BUY", 30, 650.0)
        engine.place_order("HINDALCO", "NSE", "SELL", 10, 660.0)
        exported = engine.export_data()
        engine2 = SandboxEngine(db_path=":memory:")
        stats = engine2.import_data(exported)
        assert stats["orders_imported"] == 2

    def test_import_raises_on_invalid_json(self, engine: SandboxEngine) -> None:
        with pytest.raises(ValueError, match="Invalid JSON"):
            engine.import_data("not valid json{{{")

    def test_import_raises_on_non_object_json(self, engine: SandboxEngine) -> None:
        with pytest.raises(ValueError):
            engine.import_data(json.dumps([1, 2, 3]))

    def test_roundtrip_export_import(self, engine: SandboxEngine) -> None:
        """Full export → import → export cycle produces identical capital."""
        engine.place_order("INDUSINDBK", "NSE", "BUY", 10, 1400.0)
        engine.adjust_capital(25_000.0)
        exported_first = engine.export_data()

        engine2 = SandboxEngine(db_path=":memory:")
        engine2.import_data(exported_first)

        data1 = json.loads(exported_first)
        data2 = json.loads(engine2.export_data())

        assert data1["capital"]["current"] == pytest.approx(data2["capital"]["current"])
        assert data1["capital"]["initial"] == pytest.approx(data2["capital"]["initial"])
