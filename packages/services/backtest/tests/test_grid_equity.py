"""Tests for GridEquityStrategy and GridConfig.

All tests are purely in-process with synthetic OHLCV bars; no broker calls.

Import style follows the conftest.py path convention for backtest-engine:
  ``from strategies.grid_equity import ...``  (backtest-engine/src is on sys.path)
  ``from flinttrade_core.models import ...`` (repo root is on sys.path)
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Synthetic bar factory
# ---------------------------------------------------------------------------


def _bar(close: float, ts: str = "2025-01-01 10:00:00"):
    from flinttrade_core.models import OHLCV
    return OHLCV(
        timestamp=ts,
        open=close,
        high=close + 5,
        low=close - 5,
        close=close,
        volume=1000,
        oi=0,
    )


def _bars_oscillating(
    center: float = 1000.0,
    amplitude: float = 15.0,
    steps: int = 40,
) -> list:
    """Return bars that oscillate around *center* with the given amplitude."""
    import math
    from flinttrade_core.models import OHLCV
    bars = []
    for i in range(steps):
        price = center + amplitude * math.sin(i * 0.3)
        bars.append(OHLCV(
            timestamp=f"2025-01-{(i % 28) + 1:02d} 10:00:00",
            open=round(price, 2),
            high=round(price + 3, 2),
            low=round(price - 3, 2),
            close=round(price, 2),
            volume=1000,
            oi=0,
        ))
    return bars


def _make_strategy(
    lower: float = 900.0,
    upper: float = 1100.0,
    n_grids: int = 10,
    symbol: str = "RELIANCE",
    initial_mode: str = "immediate",
    qty: int = 1,
):
    from strategies.grid_equity import GridConfig, GridEquityStrategy
    cfg = GridConfig(lower_bound=lower, upper_bound=upper, n_grids=n_grids, initial_mode=initial_mode)
    strat = GridEquityStrategy(config=cfg, symbol=symbol, exchange="NSE", product="MIS", qty_per_grid=qty)
    strat.start()
    return strat


# ===========================================================================
# GridConfig validation
# ===========================================================================


class TestGridConfig:
    def test_levels_count(self):
        from strategies.grid_equity import GridConfig
        cfg = GridConfig(lower_bound=1000, upper_bound=1200, n_grids=10)
        assert len(cfg.levels) == 11  # n_grids + 1

    def test_levels_values(self):
        from strategies.grid_equity import GridConfig
        cfg = GridConfig(lower_bound=1000, upper_bound=1200, n_grids=4)
        expected = [1000.0, 1050.0, 1100.0, 1150.0, 1200.0]
        for actual, exp in zip(cfg.levels, expected):
            assert abs(actual - exp) < 0.01

    def test_grid_spacing(self):
        from strategies.grid_equity import GridConfig
        cfg = GridConfig(lower_bound=1000, upper_bound=1200, n_grids=10)
        assert abs(cfg.grid_spacing - 20.0) < 0.001

    def test_stop_loss_one_spacing_below_lower(self):
        from strategies.grid_equity import GridConfig
        cfg = GridConfig(lower_bound=1000, upper_bound=1200, n_grids=10)
        assert abs(cfg.stop_loss - 980.0) < 0.001

    def test_take_profit_one_spacing_above_upper(self):
        from strategies.grid_equity import GridConfig
        cfg = GridConfig(lower_bound=1000, upper_bound=1200, n_grids=10)
        assert abs(cfg.take_profit - 1220.0) < 0.001

    def test_invalid_lower_gte_upper_raises(self):
        from strategies.grid_equity import GridConfig
        with pytest.raises(ValueError, match="lower_bound"):
            GridConfig(lower_bound=1200, upper_bound=1000, n_grids=10)

    def test_invalid_n_grids_raises(self):
        from strategies.grid_equity import GridConfig
        with pytest.raises(ValueError, match="n_grids"):
            GridConfig(lower_bound=1000, upper_bound=1200, n_grids=1)

    def test_invalid_initial_mode_raises(self):
        from strategies.grid_equity import GridConfig
        with pytest.raises(ValueError, match="initial_mode"):
            GridConfig(lower_bound=1000, upper_bound=1200, n_grids=5, initial_mode="bad")


# ===========================================================================
# Strategy instantiation
# ===========================================================================


class TestGridEquityInit:
    def test_strategy_starts_active(self):
        strat = _make_strategy()
        from strategy import StrategyState
        assert strat.state == StrategyState.ACTIVE

    def test_name_includes_symbol(self):
        strat = _make_strategy(symbol="NIFTY25APRFUT")
        assert "NIFTY25APRFUT" in strat.name

    def test_generate_orders_empty_on_start(self):
        strat = _make_strategy()
        assert strat.generate_orders() == []


# ===========================================================================
# First bar — no orders (initialisation)
# ===========================================================================


class TestGridEquityFirstBar:
    def test_no_orders_on_first_bar(self):
        strat = _make_strategy(lower=900, upper=1100)
        strat.on_bar(_bar(close=1000.0))
        orders = strat.generate_orders()
        assert orders == []  # first bar just sets prev_grid_idx


# ===========================================================================
# Buy on downward cross
# ===========================================================================


class TestGridEquityBuy:
    def test_buy_on_downward_cross(self):
        """Price moves down across a grid level → BUY generated."""
        strat = _make_strategy(lower=900, upper=1100, n_grids=10)
        # First bar at 1050 (midgrid)
        strat.on_bar(_bar(close=1050.0))
        strat.generate_orders()  # consume initialisation

        # Second bar drops below next grid line (grid spacing = 20)
        strat.on_bar(_bar(close=1020.0))  # dropped ~30 pts → crosses at least 1 grid
        orders = strat.generate_orders()
        buy_orders = [o for o in orders if o.action == "BUY"]
        assert len(buy_orders) >= 1

    def test_sell_on_upward_cross(self):
        """Price moves up across a grid level → SELL generated."""
        strat = _make_strategy(lower=900, upper=1100, n_grids=10)
        strat.on_bar(_bar(close=1000.0))
        strat.generate_orders()

        strat.on_bar(_bar(close=1040.0))  # moved up ~40 pts → crosses grid lines
        orders = strat.generate_orders()
        sell_orders = [o for o in orders if o.action == "SELL"]
        assert len(sell_orders) >= 1


# ===========================================================================
# Oscillating bars — generates both buys and sells
# ===========================================================================


class TestGridEquityOscillation:
    def test_oscillation_generates_both_buy_and_sell(self):
        strat = _make_strategy(lower=900, upper=1100, n_grids=20)
        all_orders = []
        for bar in _bars_oscillating(center=1000, amplitude=30, steps=60):
            strat.on_bar(bar)
            all_orders.extend(strat.generate_orders())

        buy_count = sum(1 for o in all_orders if o.action == "BUY")
        sell_count = sum(1 for o in all_orders if o.action == "SELL")
        assert buy_count > 0, "Expected at least one BUY from oscillation"
        assert sell_count > 0, "Expected at least one SELL from oscillation"


# ===========================================================================
# Stop-loss trigger
# ===========================================================================


class TestGridEquitySL:
    def test_sl_closes_position_and_resets(self):
        strat = _make_strategy(lower=1000, upper=1200, n_grids=10)
        # Grid spacing = 20; SL = 980
        strat.on_bar(_bar(close=1100.0))
        strat.generate_orders()

        # Buy some: price drops into lower portion of grid
        strat.on_bar(_bar(close=1020.0))
        strat.generate_orders()

        # Hit the stop-loss
        strat.on_bar(_bar(close=975.0))  # below SL = 980
        strat.generate_orders()
        # After SL, reset_count should have incremented
        assert strat._reset_count >= 1


# ===========================================================================
# Take-profit trigger
# ===========================================================================


class TestGridEquityTP:
    def test_tp_resets_grid(self):
        strat = _make_strategy(lower=1000, upper=1200, n_grids=10)
        # TP = 1220
        strat.on_bar(_bar(close=1100.0))
        strat.generate_orders()

        strat.on_bar(_bar(close=1225.0))  # above TP = 1220
        strat.generate_orders()
        assert strat._reset_count >= 1


# ===========================================================================
# Breakout — auto-reset
# ===========================================================================


class TestGridEquityBreakout:
    def test_breakout_above_resets(self):
        strat = _make_strategy(lower=1000, upper=1200, n_grids=5, initial_mode="immediate")
        strat.on_bar(_bar(close=1100.0))
        strat.generate_orders()

        # Breakout above upper (but below TP: SL=960, TP=1240)
        strat.on_bar(_bar(close=1210.0))  # upper=1200; TP=1240
        strat.generate_orders()
        assert strat._reset_count >= 1

    def test_breakout_below_resets(self):
        strat = _make_strategy(lower=1000, upper=1200, n_grids=5, initial_mode="immediate")
        strat.on_bar(_bar(close=1100.0))
        strat.generate_orders()

        # Below lower (1000) but above SL (960)
        strat.on_bar(_bar(close=990.0))
        strat.generate_orders()
        assert strat._reset_count >= 1


# ===========================================================================
# wait_for_buy initial_mode
# ===========================================================================


class TestGridEquityWaitForBuy:
    def test_no_orders_while_price_above_upper(self):
        strat = _make_strategy(lower=900, upper=1100, n_grids=10, initial_mode="wait_for_buy")
        # Price above upper_bound — grid not yet active
        strat.on_bar(_bar(close=1150.0))
        orders = strat.generate_orders()
        assert orders == []
        assert not strat._grid_active

    def test_activates_when_price_enters_grid(self):
        strat = _make_strategy(lower=900, upper=1100, n_grids=10, initial_mode="wait_for_buy")
        strat.on_bar(_bar(close=1150.0))  # above upper — inactive
        strat.on_bar(_bar(close=1050.0))  # inside grid — activates
        assert strat._grid_active


# ===========================================================================
# qty_per_grid propagates to orders
# ===========================================================================


class TestGridEquityQty:
    def test_order_quantity_matches_qty_per_grid(self):
        strat = _make_strategy(lower=900, upper=1100, n_grids=10, qty=3)
        strat.on_bar(_bar(close=1050.0))
        strat.generate_orders()

        strat.on_bar(_bar(close=1020.0))
        orders = strat.generate_orders()
        for o in orders:
            assert o.quantity == "3"


# ===========================================================================
# get_state_dict round-trip
# ===========================================================================


class TestGridEquityState:
    def test_state_dict_keys(self):
        strat = _make_strategy()
        strat.on_bar(_bar(close=1000.0))
        strat.on_bar(_bar(close=980.0))
        state = strat.get_state_dict()
        assert "prev_grid_idx" in state
        assert "grid_active" in state
        assert "position" in state
        assert "reset_count" in state

    def test_state_dict_position_type(self):
        strat = _make_strategy()
        state = strat.get_state_dict()
        assert isinstance(state["position"], int)


# ===========================================================================
# Registration in ALL_STRATEGIES
# ===========================================================================


def test_registered_in_all_strategies():
    from strategies import ALL_STRATEGIES
    assert "GridEquityStrategy" in ALL_STRATEGIES
