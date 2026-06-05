"""Evidence tests: the native sandbox with virtual capital is functional."""

from __future__ import annotations

import pytest

from flinttrade_data.sandbox_engine import SandboxEngine

pytestmark = pytest.mark.unit


def test_virtual_capital_paper_trade_end_to_end():
    eng = SandboxEngine(db_path=":memory:", initial_capital=1_000_000.0)
    try:
        cap = eng.get_capital()
        assert cap["initial"] == 1_000_000.0  # virtual capital is seeded

        result = eng.place_order(
            symbol="RELIANCE", exchange="NSE", action="BUY", quantity=10, price=2900.0,
        )
        assert result["status"] == "COMPLETE", result

        positions = eng.get_positions()
        assert any(p["symbol"] == "RELIANCE" and p["net_qty"] == 10 for p in positions)

        cap2 = eng.get_capital()
        assert cap2["available"] < cap["available"]  # capital was committed

        pnl = eng.get_pnl()
        assert {"realised", "unrealised", "total"} <= set(pnl)

        orders = eng.get_orders()
        assert any(o.get("symbol") == "RELIANCE" for o in orders)
    finally:
        eng.close()


def test_capital_is_adjustable():
    eng = SandboxEngine(db_path=":memory:", initial_capital=500_000.0)
    try:
        before = eng.get_capital()["available"]
        eng.adjust_capital(100_000.0)
        assert eng.get_capital()["available"] > before
    finally:
        eng.close()


def test_reset_clears_positions():
    eng = SandboxEngine(db_path=":memory:", initial_capital=500_000.0)
    try:
        eng.place_order(symbol="NIFTY", exchange="NFO", action="BUY", quantity=50, price=100.0)
        assert eng.get_positions()
        eng.reset()
        assert eng.get_positions() == []
    finally:
        eng.close()
