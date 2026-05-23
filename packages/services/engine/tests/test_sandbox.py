"""Tests for packages/services/engine/src/sandbox.py.

All tests use an in-memory DuckDB database so no files are created on disk.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Skip entire module if duckdb is not installed
# ---------------------------------------------------------------------------
duckdb = pytest.importorskip("duckdb", reason="duckdb not installed")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine():
    """SandboxEngine with in-memory DuckDB and 1 000 000 starting capital."""
    # Import directly from submodule to avoid triggering the pre-existing
    # circular import in flinttrade_engine.__init__.
    import flinttrade_engine.sandbox as _sandbox_mod
    cfg = _sandbox_mod.SandboxConfig(starting_capital=1_000_000.0)
    eng = _sandbox_mod.SandboxEngine(account_id="test_account", config=cfg, db_path=":memory:")
    yield eng
    eng.close()


@pytest.fixture()
def small_engine():
    """SandboxEngine with 10 000 capital (useful for margin failure tests)."""
    import flinttrade_engine.sandbox as _sandbox_mod
    cfg = _sandbox_mod.SandboxConfig(starting_capital=10_000.0)
    eng = _sandbox_mod.SandboxEngine(account_id="small_account", config=cfg, db_path=":memory:")
    yield eng
    eng.close()


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


class TestInitialState:
    def test_funds_starting_capital(self, engine):
        funds = engine.get_funds()
        assert funds["starting_capital"] == 1_000_000.0

    def test_funds_zero_margin_initially(self, engine):
        funds = engine.get_funds()
        assert funds["used_margin"] == 0.0

    def test_funds_available_equals_starting_capital(self, engine):
        funds = engine.get_funds()
        assert funds["available_balance"] == funds["starting_capital"]

    def test_no_positions_initially(self, engine):
        assert engine.get_positions() == []

    def test_no_orders_initially(self, engine):
        assert engine.get_orders() == []

    def test_no_trades_initially(self, engine):
        assert engine.get_trades() == []

    def test_no_pnl_history_initially(self, engine):
        assert engine.get_pnl_history() == []


# ---------------------------------------------------------------------------
# Market orders
# ---------------------------------------------------------------------------


class TestMarketOrders:
    def test_market_order_completes_immediately(self, engine):
        result = engine.place_order(
            {"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY",
             "quantity": 10, "price": 0.0, "pricetype": "MARKET", "product": "MIS"}
        )
        assert result["status"] == "COMPLETE"
        assert result["order_id"] != ""

    def test_market_order_creates_trade(self, engine):
        engine.place_order(
            {"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY",
             "quantity": 10, "price": 0.0, "pricetype": "MARKET", "product": "MIS"}
        )
        trades = engine.get_trades()
        assert len(trades) == 1
        assert trades[0]["symbol"] == "RELIANCE"
        assert trades[0]["quantity"] == 10

    def test_market_order_creates_position(self, engine):
        engine.place_order(
            {"symbol": "NIFTY25APRFUT", "exchange": "NFO", "action": "BUY",
             "quantity": 50, "price": 0.0, "pricetype": "MARKET", "product": "NRML"}
        )
        positions = engine.get_positions()
        assert len(positions) == 1
        assert positions[0]["net_qty"] == 50

    def test_market_buy_then_sell_flattens_position(self, engine):
        engine.place_order(
            {"symbol": "TCS", "exchange": "NSE", "action": "BUY",
             "quantity": 5, "price": 0.0, "pricetype": "MARKET", "product": "CNC"}
        )
        engine.place_order(
            {"symbol": "TCS", "exchange": "NSE", "action": "SELL",
             "quantity": 5, "price": 0.0, "pricetype": "MARKET", "product": "CNC"}
        )
        positions = engine.get_positions()
        assert positions == []

    def test_invalid_symbol_rejected(self, engine):
        result = engine.place_order(
            {"symbol": "", "exchange": "NSE", "action": "BUY",
             "quantity": 10, "price": 0.0, "pricetype": "MARKET", "product": "MIS"}
        )
        assert result["status"] == "REJECTED"

    def test_zero_quantity_rejected(self, engine):
        result = engine.place_order(
            {"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY",
             "quantity": 0, "price": 0.0, "pricetype": "MARKET", "product": "MIS"}
        )
        assert result["status"] == "REJECTED"

    def test_insufficient_margin_rejected(self, small_engine):
        # 10 000 capital, trying to buy 1000 shares @ 5000 = 5 000 000 notional
        result = small_engine.place_order(
            {"symbol": "HDFC", "exchange": "NSE", "action": "BUY",
             "quantity": 1000, "price": 5000.0, "pricetype": "MARKET", "product": "CNC"}
        )
        assert result["status"] == "REJECTED"
        assert "margin" in result["message"].lower()


# ---------------------------------------------------------------------------
# Limit orders
# ---------------------------------------------------------------------------


class TestLimitOrders:
    def test_limit_order_queued_as_pending(self, engine):
        result = engine.place_order(
            {"symbol": "INFY", "exchange": "NSE", "action": "BUY",
             "quantity": 20, "price": 1500.0, "pricetype": "LIMIT", "product": "MIS"}
        )
        assert result["status"] == "PENDING"

    def test_limit_buy_fills_when_price_drops(self, engine):
        engine.place_order(
            {"symbol": "INFY", "exchange": "NSE", "action": "BUY",
             "quantity": 20, "price": 1500.0, "pricetype": "LIMIT", "product": "MIS"}
        )
        filled = engine.check_pending_fills({"INFY": 1490.0})
        assert len(filled) == 1
        trades = engine.get_trades()
        assert len(trades) == 1

    def test_limit_buy_does_not_fill_when_price_above(self, engine):
        engine.place_order(
            {"symbol": "INFY", "exchange": "NSE", "action": "BUY",
             "quantity": 20, "price": 1500.0, "pricetype": "LIMIT", "product": "MIS"}
        )
        filled = engine.check_pending_fills({"INFY": 1510.0})
        assert filled == []


# ---------------------------------------------------------------------------
# Square-off
# ---------------------------------------------------------------------------


class TestSquareOff:
    def test_square_off_closes_open_positions(self, engine):
        engine.place_order(
            {"symbol": "NIFTY25APRFUT", "exchange": "NFO", "action": "BUY",
             "quantity": 50, "price": 0.0, "pricetype": "MARKET", "product": "NRML"}
        )
        count = engine.square_off_all()
        assert count == 1
        positions = engine.get_positions()
        assert positions == []

    def test_square_off_no_positions_returns_zero(self, engine):
        count = engine.square_off_all()
        assert count == 0


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_orders_and_trades(self, engine):
        engine.place_order(
            {"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY",
             "quantity": 5, "price": 0.0, "pricetype": "MARKET", "product": "MIS"}
        )
        engine.reset()
        assert engine.get_orders() == []
        assert engine.get_trades() == []
        assert engine.get_positions() == []

    def test_reset_restores_starting_capital(self, engine):
        engine.place_order(
            {"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY",
             "quantity": 5, "price": 2000.0, "pricetype": "MARKET", "product": "CNC"}
        )
        engine.reset()
        funds = engine.get_funds()
        assert funds["available_balance"] == 1_000_000.0
        assert funds["used_margin"] == 0.0
