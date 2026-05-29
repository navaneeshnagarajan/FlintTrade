"""Tests for FlintTrade engine package.

DO NOT RUN — these require no live OpenAlgo instance. All API calls are mocked.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# IST for test helpers
IST = timezone(timedelta(hours=5, minutes=30))


# ======================================================================
# Layer 1 — Order Validation
# ======================================================================


class TestOrderValidation:
    """Test Layer 1: price, qty, exchange, symbol checks."""

    def _make_order(self, **overrides):
        from flinttrade_core.models import Order
        defaults = {"symbol": "RELIANCE", "action": "BUY", "exchange": "NSE", "quantity": "10"}
        defaults.update(overrides)
        return Order(**defaults)

    def test_valid_market_order_passes(self):
        from flinttrade_engine.safety import OrderValidation
        layer = OrderValidation(check_market_hours=False)
        order = self._make_order()
        result = layer.validate(order)
        assert result.passed

    def test_invalid_exchange_fails(self):
        from flinttrade_core.models import Order
        from flinttrade_engine.safety import OrderValidation
        layer = OrderValidation(check_market_hours=False)
        order = Order(symbol="NIFTY", action="BUY", exchange="NSE_INDEX", quantity="1")
        result = layer.validate(order)
        assert not result.passed
        assert "not tradeable" in result.reason

    def test_empty_symbol_fails(self):
        from flinttrade_engine.safety import OrderValidation
        layer = OrderValidation(check_market_hours=False)
        order = self._make_order(symbol="")
        result = layer.validate(order)
        assert not result.passed
        assert "empty" in result.reason.lower()

    def test_zero_quantity_fails(self):
        from flinttrade_engine.safety import OrderValidation
        layer = OrderValidation(check_market_hours=False)
        order = self._make_order(quantity="0")
        result = layer.validate(order)
        assert not result.passed
        assert "positive" in result.reason.lower()

    def test_quantity_exceeds_limit_fails(self):
        from flinttrade_engine.safety import OrderValidation
        layer = OrderValidation(qty_limits={"NSE": 100}, check_market_hours=False)
        order = self._make_order(quantity="200")
        result = layer.validate(order)
        assert not result.passed
        assert "exceeds" in result.reason.lower()

    def test_limit_price_within_tolerance_passes(self):
        from flinttrade_engine.safety import OrderValidation
        layer = OrderValidation(price_deviation_pct=5.0, check_market_hours=False)
        order = self._make_order(pricetype="LIMIT", price="2520")
        result = layer.validate(order, ltp=2500.0)
        assert result.passed

    def test_limit_price_exceeds_tolerance_fails(self):
        from flinttrade_engine.safety import OrderValidation
        layer = OrderValidation(price_deviation_pct=5.0, check_market_hours=False)
        order = self._make_order(pricetype="LIMIT", price="3000")
        result = layer.validate(order, ltp=2500.0)
        assert not result.passed
        assert "deviates" in result.reason.lower()

    def test_market_order_no_price_check(self):
        from flinttrade_engine.safety import OrderValidation
        layer = OrderValidation(check_market_hours=False)
        order = self._make_order(pricetype="MARKET", price="9999")
        result = layer.validate(order, ltp=100.0)
        assert result.passed

    def test_all_tradeable_exchanges_pass(self):
        from flinttrade_engine.safety import OrderValidation
        layer = OrderValidation(check_market_hours=False)
        # NCO (NSE Commodities, Zerodha-only) joined the tradeable list in
        # the OpenAlgo v2.0.0.7 sync.
        for exch in ["NSE", "BSE", "NFO", "BFO", "MCX", "CDS", "BCD", "NCDEX", "NCO"]:
            order = self._make_order(exchange=exch)
            assert layer.validate(order).passed, f"{exch} should pass"


# ======================================================================
# Layer 1 — Market Hours
# ======================================================================


class TestMarketHours:
    """Test per-exchange market hours checking."""

    def _make_order(self, **overrides):
        from flinttrade_core.models import Order
        defaults = {"symbol": "RELIANCE", "action": "BUY", "exchange": "NSE", "quantity": "10"}
        defaults.update(overrides)
        return Order(**defaults)

    def test_is_market_open_nse_during_hours(self):
        from flinttrade_engine.safety import is_market_open
        mid_day = datetime(2026, 3, 16, 12, 0, 0, tzinfo=IST)
        assert is_market_open("NSE", at=mid_day)

    def test_is_market_closed_nse_after_hours(self):
        from flinttrade_engine.safety import is_market_open
        evening = datetime(2026, 3, 16, 18, 0, 0, tzinfo=IST)
        assert not is_market_open("NSE", at=evening)

    def test_is_market_closed_nse_before_open(self):
        from flinttrade_engine.safety import is_market_open
        early = datetime(2026, 3, 16, 8, 0, 0, tzinfo=IST)
        assert not is_market_open("NSE", at=early)

    def test_mcx_open_late_evening(self):
        from flinttrade_engine.safety import is_market_open
        late = datetime(2026, 3, 16, 22, 0, 0, tzinfo=IST)
        assert is_market_open("MCX", at=late)

    def test_mcx_closed_after_2330(self):
        from flinttrade_engine.safety import is_market_open
        late = datetime(2026, 3, 16, 23, 45, 0, tzinfo=IST)
        assert not is_market_open("MCX", at=late)

    def test_cds_open_afternoon(self):
        from flinttrade_engine.safety import is_market_open
        afternoon = datetime(2026, 3, 16, 16, 30, 0, tzinfo=IST)
        assert is_market_open("CDS", at=afternoon)

    def test_cds_closed_after_1700(self):
        from flinttrade_engine.safety import is_market_open
        evening = datetime(2026, 3, 16, 17, 30, 0, tzinfo=IST)
        assert not is_market_open("CDS", at=evening)

    def test_nse_index_always_closed(self):
        from flinttrade_engine.safety import is_market_open
        mid_day = datetime(2026, 3, 16, 12, 0, 0, tzinfo=IST)
        assert not is_market_open("NSE_INDEX", at=mid_day)

    def test_bse_index_always_closed(self):
        from flinttrade_engine.safety import is_market_open
        mid_day = datetime(2026, 3, 16, 12, 0, 0, tzinfo=IST)
        assert not is_market_open("BSE_INDEX", at=mid_day)

    def test_unknown_exchange_closed(self):
        from flinttrade_engine.safety import is_market_open
        assert not is_market_open("FAKE")

    def test_get_expiry_time_nfo(self):
        from flinttrade_engine.safety import get_expiry_time
        assert get_expiry_time("NFO") == time(15, 30)

    def test_get_expiry_time_cds(self):
        from flinttrade_engine.safety import get_expiry_time
        assert get_expiry_time("CDS") == time(12, 30)

    def test_get_expiry_time_mcx(self):
        from flinttrade_engine.safety import get_expiry_time
        assert get_expiry_time("MCX") == time(23, 30)

    def test_get_expiry_time_default(self):
        from flinttrade_engine.safety import get_expiry_time
        assert get_expiry_time("NSE") == time(15, 30)

    def test_delta_always_open(self):
        from flinttrade_engine.safety import is_market_open
        # 3:30 AM — even the middle of the night
        night = datetime(2026, 3, 16, 3, 30, 0, tzinfo=IST)
        assert is_market_open("DELTA", at=night)

    def test_delta_open_midday(self):
        from flinttrade_engine.safety import is_market_open
        mid_day = datetime(2026, 3, 16, 12, 0, 0, tzinfo=IST)
        assert is_market_open("DELTA", at=mid_day)

    def test_get_expiry_time_delta(self):
        from flinttrade_engine.safety import get_expiry_time
        assert get_expiry_time("DELTA") == time(18, 0)

    def test_delta_in_openalgo_exchanges(self):
        from flinttrade_engine.safety import OPENALGO_EXCHANGES
        assert "DELTA" in OPENALGO_EXCHANGES

    def test_delta_order_passes_with_warning(self):
        from flinttrade_engine.safety import OrderValidation
        layer = OrderValidation(check_market_hours=True)
        # DELTA is not in the core Exchange enum yet, so mock the order
        order = MagicMock()
        order.exchange = MagicMock()
        order.exchange.value = "DELTA"
        order.symbol = "BTCUSD"
        order.quantity = "1"
        order.pricetype = MagicMock()
        order.pricetype.value = "MARKET"
        order.price = "0"
        # Any time — should pass (24/7)
        night = datetime(2026, 3, 16, 3, 0, 0, tzinfo=IST)
        result = layer.validate(order, at=night)
        assert result.passed

    def test_openalgo_exchanges_complete(self):
        from flinttrade_engine.safety import OPENALGO_EXCHANGES
        for exch in [
            "NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "NCDEX",
            "NCO", "NSE_INDEX", "BSE_INDEX", "MCX_INDEX", "GLOBAL_INDEX",
        ]:
            assert exch in OPENALGO_EXCHANGES, f"{exch} missing from OPENALGO_EXCHANGES"

    def test_order_rejected_outside_market_hours(self):
        from flinttrade_engine.safety import OrderValidation
        layer = OrderValidation(check_market_hours=True)
        order = self._make_order(exchange="NSE")
        evening = datetime(2026, 3, 16, 18, 0, 0, tzinfo=IST)
        result = layer.validate(order, at=evening)
        assert not result.passed
        assert "Market closed" in result.reason
        assert "09:15" in result.reason
        assert "15:30" in result.reason

    def test_order_accepted_during_market_hours(self):
        from flinttrade_engine.safety import OrderValidation
        layer = OrderValidation(check_market_hours=True)
        order = self._make_order(exchange="NSE")
        mid_day = datetime(2026, 3, 16, 12, 0, 0, tzinfo=IST)
        result = layer.validate(order, at=mid_day)
        assert result.passed

    def test_mcx_order_accepted_late(self):
        from flinttrade_engine.safety import OrderValidation
        layer = OrderValidation(check_market_hours=True)
        order = self._make_order(exchange="MCX")
        late = datetime(2026, 3, 16, 22, 0, 0, tzinfo=IST)
        result = layer.validate(order, at=late)
        assert result.passed

    def test_mcx_order_rejected_after_close(self):
        from flinttrade_engine.safety import OrderValidation
        layer = OrderValidation(check_market_hours=True)
        order = self._make_order(exchange="MCX")
        after = datetime(2026, 3, 16, 23, 45, 0, tzinfo=IST)
        result = layer.validate(order, at=after)
        assert not result.passed
        assert "MCX" in result.reason
        assert "Market closed" in result.reason

    def test_market_hours_dict_has_all_tradeable(self):
        from flinttrade_engine.safety import MARKET_HOURS, _TRADEABLE_EXCHANGES
        for exch in _TRADEABLE_EXCHANGES:
            assert exch in MARKET_HOURS, f"{exch} missing from MARKET_HOURS"


# ======================================================================
# Layer 2 — Position Limits
# ======================================================================


class TestPositionLimits:
    """Test Layer 2: max positions and margin usage."""

    def _make_positions(self, count: int):
        from flinttrade_core.models import Position
        return [Position(symbol=f"SYM{i}", quantity="10") for i in range(count)]

    def test_under_limit_passes(self):
        from flinttrade_engine.safety import PositionLimits
        layer = PositionLimits(max_positions=5)
        result = layer.validate(self._make_positions(3), used_margin=10000, total_balance=100000)
        assert result.passed

    def test_at_max_positions_fails(self):
        from flinttrade_engine.safety import PositionLimits
        layer = PositionLimits(max_positions=5)
        result = layer.validate(self._make_positions(5), used_margin=0, total_balance=100000)
        assert not result.passed
        assert "max positions" in result.reason.lower()

    def test_margin_exceeds_limit_fails(self):
        from flinttrade_engine.safety import PositionLimits
        layer = PositionLimits(max_margin_pct=60.0)
        result = layer.validate([], used_margin=70000, total_balance=100000)
        assert not result.passed
        assert "margin" in result.reason.lower()

    def test_margin_under_limit_passes(self):
        from flinttrade_engine.safety import PositionLimits
        layer = PositionLimits(max_margin_pct=60.0)
        result = layer.validate([], used_margin=50000, total_balance=100000)
        assert result.passed

    def test_zero_balance_no_margin_check(self):
        from flinttrade_engine.safety import PositionLimits
        layer = PositionLimits()
        result = layer.validate([], used_margin=0, total_balance=0)
        assert result.passed

    def test_positions_with_zero_qty_not_counted(self):
        from flinttrade_core.models import Position
        from flinttrade_engine.safety import PositionLimits
        layer = PositionLimits(max_positions=3)
        positions = [
            Position(symbol="A", quantity="10"),
            Position(symbol="B", quantity="0"),  # closed — should not count
            Position(symbol="C", quantity="5"),
        ]
        result = layer.validate(positions, used_margin=0, total_balance=100000)
        assert result.passed  # only 2 active (A, C), under limit of 3


# ======================================================================
# Layer 3 — Portfolio Risk (Greeks)
# ======================================================================


class TestPortfolioRisk:
    """Test Layer 3: net delta and vega limits."""

    def test_within_limits_passes(self):
        from flinttrade_engine.safety import PortfolioRisk
        layer = PortfolioRisk(max_net_delta=500, max_net_vega=10000)
        result = layer.validate(net_delta=200, net_vega=5000)
        assert result.passed

    def test_delta_exceeds_fails(self):
        from flinttrade_engine.safety import PortfolioRisk
        layer = PortfolioRisk(max_net_delta=500)
        result = layer.validate(net_delta=600, net_vega=0)
        assert not result.passed
        assert "delta" in result.reason.lower()

    def test_negative_delta_exceeds_fails(self):
        from flinttrade_engine.safety import PortfolioRisk
        layer = PortfolioRisk(max_net_delta=500)
        result = layer.validate(net_delta=-600, net_vega=0)
        assert not result.passed

    def test_vega_exceeds_fails(self):
        from flinttrade_engine.safety import PortfolioRisk
        layer = PortfolioRisk(max_net_vega=10000)
        result = layer.validate(net_delta=0, net_vega=15000)
        assert not result.passed
        assert "vega" in result.reason.lower()


# ======================================================================
# Layer 4 — Daily P&L Limits
# ======================================================================


class TestDailyPnLLimits:
    """Test Layer 4: pause trigger and kill switch."""

    def test_profit_passes(self):
        from flinttrade_engine.safety import DailyPnLLimits
        layer = DailyPnLLimits()
        result = layer.validate(daily_pnl=5000, starting_capital=100000)
        assert result.passed

    def test_small_loss_passes(self):
        from flinttrade_engine.safety import DailyPnLLimits
        layer = DailyPnLLimits(pause_pct=3.0)
        result = layer.validate(daily_pnl=-2000, starting_capital=100000)
        assert result.passed

    def test_3pct_loss_triggers_pause(self):
        from flinttrade_engine.safety import DailyPnLLimits
        layer = DailyPnLLimits(pause_pct=3.0, kill_pct=15.0)
        result = layer.validate(daily_pnl=-3500, starting_capital=100000)
        assert not result.passed
        assert layer.is_paused
        assert "pause" in result.reason.lower()

    def test_15pct_loss_triggers_kill(self):
        from flinttrade_engine.safety import DailyPnLLimits
        layer = DailyPnLLimits(pause_pct=3.0, kill_pct=15.0)
        result = layer.validate(daily_pnl=-16000, starting_capital=100000)
        assert not result.passed
        assert layer.is_killed
        assert "kill" in result.reason.lower()

    def test_pause_blocks_subsequent_orders(self):
        from flinttrade_engine.safety import DailyPnLLimits
        layer = DailyPnLLimits(pause_pct=3.0)
        layer.validate(daily_pnl=-5000, starting_capital=100000)
        assert layer.is_paused
        result = layer.validate(daily_pnl=0, starting_capital=100000)
        assert not result.passed

    def test_reset_pause_allows_trading(self):
        from flinttrade_engine.safety import DailyPnLLimits
        layer = DailyPnLLimits(pause_pct=3.0)
        layer.validate(daily_pnl=-5000, starting_capital=100000)
        layer.reset_pause()
        result = layer.validate(daily_pnl=0, starting_capital=100000)
        assert result.passed

    def test_kill_requires_explicit_reset(self):
        from flinttrade_engine.safety import DailyPnLLimits
        layer = DailyPnLLimits(kill_pct=15.0)
        layer.validate(daily_pnl=-20000, starting_capital=100000)
        assert layer.is_killed
        # Even with zero loss, kill persists
        result = layer.validate(daily_pnl=0, starting_capital=100000)
        assert not result.passed
        # Explicit reset
        layer.reset_kill()
        result = layer.validate(daily_pnl=0, starting_capital=100000)
        assert result.passed

    def test_zero_capital_passes(self):
        from flinttrade_engine.safety import DailyPnLLimits
        layer = DailyPnLLimits()
        result = layer.validate(daily_pnl=-1000, starting_capital=0)
        assert result.passed


# ======================================================================
# Layer 5 — Kill Switch
# ======================================================================


class TestKillSwitch:
    """Test Layer 5: emergency kill."""

    def test_inactive_passes(self):
        from flinttrade_engine.safety import KillSwitch
        ks = KillSwitch()
        assert ks.validate().passed

    def test_activate_blocks(self):
        from flinttrade_engine.safety import KillSwitch
        ks = KillSwitch()
        ks.activate("Manual emergency")
        assert ks.is_active
        assert not ks.validate().passed
        assert "Manual emergency" in ks.validate().reason

    def test_activate_calls_cancel_and_close(self):
        from flinttrade_engine.safety import KillSwitch
        # Both methods are async — use AsyncMock so they can be awaited correctly.
        mock_client = MagicMock()
        mock_client.cancel_all_orders = AsyncMock()
        mock_client.close_position = AsyncMock()
        ks = KillSwitch()
        ks.activate("Test kill", client=mock_client)
        mock_client.cancel_all_orders.assert_called_once()
        mock_client.close_position.assert_called_once()

    def test_reset_allows_trading(self):
        from flinttrade_engine.safety import KillSwitch
        ks = KillSwitch()
        ks.activate("Test")
        ks.reset()
        assert not ks.is_active
        assert ks.validate().passed


# ======================================================================
# SafetySystem composite
# ======================================================================


class TestSafetySystem:
    """Test the composite safety system with all 5 layers."""

    def _make_order(self, **overrides):
        from flinttrade_core.models import Order
        defaults = {"symbol": "RELIANCE", "action": "BUY", "quantity": "10"}
        defaults.update(overrides)
        return Order(**defaults)

    def _make_system(self, check_market_hours=False):
        from flinttrade_engine.safety import SafetyConfig, SafetySystem
        return SafetySystem(SafetyConfig(check_market_hours=check_market_hours))

    def test_all_layers_pass(self):
        ss = self._make_system()
        results = ss.check_order(
            self._make_order(),
            ltp=2500.0,
            positions=[],
            used_margin=10000,
            total_balance=100000,
            net_delta=100,
            net_vega=1000,
            daily_pnl=500,
            starting_capital=100000,
        )
        assert all(r.passed for r in results)

    def test_all_layers_pass_with_market_hours(self):
        ss = self._make_system(check_market_hours=True)
        mid_day = datetime(2026, 3, 16, 12, 0, 0, tzinfo=IST)
        results = ss.check_order(
            self._make_order(),
            ltp=2500.0,
            positions=[],
            used_margin=10000,
            total_balance=100000,
            net_delta=100,
            net_vega=1000,
            daily_pnl=500,
            starting_capital=100000,
            at=mid_day,
        )
        assert all(r.passed for r in results)

    def test_market_closed_blocks_order(self):
        ss = self._make_system(check_market_hours=True)
        evening = datetime(2026, 3, 16, 18, 0, 0, tzinfo=IST)
        results = ss.check_order(
            self._make_order(),
            starting_capital=100000,
            at=evening,
        )
        failed = [r for r in results if not r.passed]
        assert len(failed) == 1
        assert failed[0].layer == "L1_ORDER"
        assert "Market closed" in failed[0].reason

    def test_kill_switch_blocks_immediately(self):
        ss = self._make_system()
        ss.l5_kill.activate("Test")
        results = ss.check_order(self._make_order())
        assert len(results) == 1
        assert results[0].layer == "L5_KILL"

    def test_pnl_kill_blocks_before_order_check(self):
        ss = self._make_system()
        results = ss.check_order(
            self._make_order(),
            daily_pnl=-20000,
            starting_capital=100000,
        )
        assert any(r.layer == "L4_PNL" and not r.passed for r in results)

    def test_fail_fast_on_invalid_order(self):
        ss = self._make_system()
        results = ss.check_order(
            self._make_order(symbol=""),
            daily_pnl=0,
            starting_capital=100000,
        )
        failed = [r for r in results if not r.passed]
        assert len(failed) == 1
        assert failed[0].layer == "L1_ORDER"


# ======================================================================
# OrderRouter
# ======================================================================


class TestOrderRouter:
    """Test order routing through safety + dispatch."""

    def _make_order(self, **overrides):
        from flinttrade_core.models import Order
        defaults = {"symbol": "RELIANCE", "action": "BUY", "quantity": "10"}
        defaults.update(overrides)
        return Order(**defaults)

    def _make_safety(self):
        from flinttrade_engine.safety import SafetyConfig, SafetySystem
        return SafetySystem(SafetyConfig(check_market_hours=False))

    def test_route_passes_and_places_order(self):
        from flinttrade_core.models import OrderResponse
        from flinttrade_engine.router import OrderRouter

        mock_client = MagicMock()
        mock_client.place_order.return_value = OrderResponse(status="success", orderid="12345")

        router = OrderRouter(client=mock_client, safety=self._make_safety())
        decision = router.route(
            self._make_order(),
            ltp=2500.0,
            positions=[],
            total_balance=100000,
            starting_capital=100000,
        )
        assert decision.passed
        assert decision.order_response.orderid == "12345"
        mock_client.place_order.assert_called_once()

    def test_route_blocked_by_safety(self):
        from flinttrade_engine.router import OrderRouter

        mock_client = MagicMock()
        router = OrderRouter(client=mock_client, safety=self._make_safety())

        # Empty symbol will fail L1
        decision = router.route(self._make_order(symbol=""), starting_capital=100000)
        assert not decision.passed
        mock_client.place_order.assert_not_called()

    def test_disabled_strategy_blocked(self):
        from flinttrade_engine.router import OrderRouter, StrategyRouteConfig

        mock_client = MagicMock()
        router = OrderRouter(client=mock_client, safety=self._make_safety())
        router.add_strategy_config(StrategyRouteConfig("Flint", enabled=False))

        decision = router.route(self._make_order(), starting_capital=100000)
        assert not decision.passed
        assert "disabled" in decision.error.lower()

    def test_history_records_decisions(self):
        from flinttrade_core.models import OrderResponse
        from flinttrade_engine.router import OrderRouter

        mock_client = MagicMock()
        mock_client.place_order.return_value = OrderResponse(status="success", orderid="1")

        router = OrderRouter(client=mock_client, safety=self._make_safety())
        router.route(self._make_order(), ltp=2500.0, starting_capital=100000, total_balance=100000)
        router.route(self._make_order(symbol=""), starting_capital=100000)

        assert len(router.history) == 2
        assert router.history[0].passed
        assert not router.history[1].passed

    def test_api_error_recorded(self):
        from flinttrade_engine.router import OrderRouter

        mock_client = MagicMock()
        mock_client.place_order.side_effect = RuntimeError("Connection refused")

        router = OrderRouter(client=mock_client, safety=self._make_safety())
        decision = router.route(
            self._make_order(),
            ltp=2500.0,
            positions=[],
            total_balance=100000,
            starting_capital=100000,
        )
        assert not decision.passed
        assert "Connection refused" in decision.error


# ======================================================================
# TimeScheduler — Market Hours
# ======================================================================


class TestTimeScheduler:
    """Test market hours, square-off times, and deploy freeze."""

    def test_nse_market_hours(self):
        from flinttrade_engine.scheduler import EXCHANGE_SCHEDULES
        sched = EXCHANGE_SCHEDULES["NSE"]
        assert sched.market_open == time(9, 15)
        assert sched.market_close == time(15, 30)
        assert sched.square_off == time(15, 15)

    def test_mcx_market_hours(self):
        from flinttrade_engine.scheduler import EXCHANGE_SCHEDULES
        sched = EXCHANGE_SCHEDULES["MCX"]
        assert sched.market_open == time(9, 0)
        assert sched.market_close == time(23, 55)
        assert sched.square_off == time(23, 30)

    def test_cds_market_hours(self):
        from flinttrade_engine.scheduler import EXCHANGE_SCHEDULES
        sched = EXCHANGE_SCHEDULES["CDS"]
        assert sched.market_open == time(9, 0)
        assert sched.market_close == time(17, 0)
        assert sched.square_off == time(16, 45)

    def test_delta_is_24x7(self):
        from flinttrade_engine.scheduler import EXCHANGE_SCHEDULES
        sched = EXCHANGE_SCHEDULES["DELTA"]
        assert sched.is_24x7

    def test_bfo_market_hours(self):
        from flinttrade_engine.scheduler import EXCHANGE_SCHEDULES
        sched = EXCHANGE_SCHEDULES["BFO"]
        assert sched.market_open == time(9, 15)
        assert sched.market_close == time(15, 30)

    def test_ncdex_market_hours(self):
        from flinttrade_engine.scheduler import EXCHANGE_SCHEDULES
        sched = EXCHANGE_SCHEDULES["NCDEX"]
        assert sched.market_open == time(10, 0)
        assert sched.market_close == time(17, 0)

    def test_is_market_open_during_hours(self):
        from flinttrade_engine.scheduler import TimeScheduler
        sched = TimeScheduler()
        # 10:00 IST on a weekday — NSE is open
        mid_day = datetime(2026, 3, 16, 10, 0, 0, tzinfo=IST)
        assert sched.is_market_open("NSE", at=mid_day)

    def test_is_market_closed_after_hours(self):
        from flinttrade_engine.scheduler import TimeScheduler
        sched = TimeScheduler()
        evening = datetime(2026, 3, 16, 18, 0, 0, tzinfo=IST)
        assert not sched.is_market_open("NSE", at=evening)

    def test_mcx_open_late_evening(self):
        from flinttrade_engine.scheduler import TimeScheduler
        sched = TimeScheduler()
        late = datetime(2026, 3, 16, 22, 0, 0, tzinfo=IST)
        assert sched.is_market_open("MCX", at=late)

    def test_delta_always_open(self):
        from flinttrade_engine.scheduler import TimeScheduler
        sched = TimeScheduler()
        any_time = datetime(2026, 3, 16, 3, 30, 0, tzinfo=IST)
        assert sched.is_market_open("DELTA", at=any_time)

    def test_unknown_exchange_closed(self):
        from flinttrade_engine.scheduler import TimeScheduler
        sched = TimeScheduler()
        assert not sched.is_market_open("FAKE")

    def test_weekend_not_trading_day(self):
        from flinttrade_engine.scheduler import TimeScheduler
        sched = TimeScheduler()
        saturday = date(2026, 3, 14)  # Saturday
        assert not sched.is_trading_day("NSE", on=saturday)

    def test_crypto_trades_on_weekend(self):
        from flinttrade_engine.scheduler import TimeScheduler
        sched = TimeScheduler()
        sunday = date(2026, 3, 15)
        assert sched.is_trading_day("DELTA", on=sunday)

    def test_weekday_is_trading_day(self):
        from flinttrade_engine.scheduler import TimeScheduler
        sched = TimeScheduler()
        monday = date(2026, 3, 16)
        assert sched.is_trading_day("NSE", on=monday)

    def test_should_square_off_after_time(self):
        from flinttrade_engine.scheduler import TimeScheduler
        sched = TimeScheduler()
        after_squareoff = datetime(2026, 3, 16, 15, 20, 0, tzinfo=IST)
        assert sched.should_square_off("NSE", at=after_squareoff)

    def test_should_not_square_off_before_time(self):
        from flinttrade_engine.scheduler import TimeScheduler
        sched = TimeScheduler()
        before = datetime(2026, 3, 16, 14, 0, 0, tzinfo=IST)
        assert not sched.should_square_off("NSE", at=before)

    def test_crypto_never_square_off(self):
        from flinttrade_engine.scheduler import TimeScheduler
        sched = TimeScheduler()
        assert not sched.should_square_off("DELTA")

    def test_deploy_freeze_equity_during_hours(self):
        from flinttrade_engine.scheduler import TimeScheduler
        sched = TimeScheduler()
        mid_day = datetime(2026, 3, 16, 12, 0, 0, tzinfo=IST)
        assert sched.is_deploy_frozen(["NSE", "NFO"], at=mid_day)

    def test_deploy_not_frozen_after_hours(self):
        from flinttrade_engine.scheduler import TimeScheduler
        sched = TimeScheduler()
        evening = datetime(2026, 3, 16, 18, 0, 0, tzinfo=IST)
        assert not sched.is_deploy_frozen(["NSE"], at=evening)

    def test_deploy_freeze_crypto_always(self):
        from flinttrade_engine.scheduler import TimeScheduler
        sched = TimeScheduler()
        any_time = datetime(2026, 3, 16, 3, 0, 0, tzinfo=IST)
        assert sched.is_deploy_frozen(["DELTA"], at=any_time)

    def test_deploy_freeze_mcx_late(self):
        from flinttrade_engine.scheduler import TimeScheduler
        sched = TimeScheduler()
        late = datetime(2026, 3, 16, 22, 0, 0, tzinfo=IST)
        assert sched.is_deploy_frozen(["MCX"], at=late)

    def test_load_holidays_with_mock_client(self):
        from flinttrade_engine.scheduler import TimeScheduler
        # holidays() is async — use AsyncMock so that awaiting it works correctly.
        mock_client = MagicMock()
        mock_client.holidays = AsyncMock(return_value={"holidays": ["2026-01-26", "2026-08-15"]})
        sched = TimeScheduler(client=mock_client)
        holidays = sched.load_holidays("2026")
        assert "2026-01-26" in holidays
        assert len(holidays) == 2

    def test_holiday_makes_non_trading_day(self):
        from flinttrade_engine.scheduler import TimeScheduler
        sched = TimeScheduler()
        sched._holidays["2026"] = ["2026-03-16"]
        assert not sched.is_trading_day("NSE", on=date(2026, 3, 16))


# ======================================================================
# BaseStrategy & Registry
# ======================================================================


class TestBaseStrategy:
    """Test BaseStrategy interface and state machine."""

    def _make_concrete(self):
        from flinttrade_core.models import OHLCV, Order, Quote
        from flinttrade_engine.strategy import BaseStrategy

        class DummyStrategy(BaseStrategy):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.ticks: list = []
                self.bars: list = []
                self.signals: list = []

            def on_tick(self, quote: Quote) -> None:
                self.ticks.append(quote)

            def on_bar(self, bar: OHLCV) -> None:
                self.bars.append(bar)

            def on_signal(self, signal: dict) -> None:
                self.signals.append(signal)

            def generate_orders(self) -> list[Order]:
                return [Order(symbol="RELIANCE", action="BUY")]

        return DummyStrategy

    def test_initial_state_stopped(self):
        cls = self._make_concrete()
        s = cls(name="test")
        assert s.state.value == "STOPPED"

    def test_start_sets_active(self):
        cls = self._make_concrete()
        s = cls(name="test")
        s.start()
        assert s.is_active

    def test_pause_resume_cycle(self):
        cls = self._make_concrete()
        s = cls(name="test")
        s.start()
        s.pause()
        assert s.state.value == "PAUSED"
        s.resume()
        assert s.is_active

    def test_stop_from_active(self):
        cls = self._make_concrete()
        s = cls(name="test")
        s.start()
        s.stop()
        assert s.state.value == "STOPPED"

    def test_error_state(self):
        cls = self._make_concrete()
        s = cls(name="test")
        s.start()
        s.set_error("Something broke")
        assert s.state.value == "ERROR"
        assert s.error_message == "Something broke"

    def test_start_from_error(self):
        cls = self._make_concrete()
        s = cls(name="test")
        s.set_error("Crash")
        s.start()
        assert s.is_active
        assert s.error_message == ""

    def test_on_tick_called(self):
        from flinttrade_core.models import Quote
        cls = self._make_concrete()
        s = cls(name="test")
        s.on_tick(Quote(symbol="RELIANCE", ltp=2500))
        assert len(s.ticks) == 1

    def test_on_bar_called(self):
        from flinttrade_core.models import OHLCV
        cls = self._make_concrete()
        s = cls(name="test")
        s.on_bar(OHLCV(timestamp="2026-03-16", close=100))
        assert len(s.bars) == 1

    def test_on_signal_called(self):
        cls = self._make_concrete()
        s = cls(name="test")
        s.on_signal({"action": "BUY", "symbol": "TCS"})
        assert len(s.signals) == 1

    def test_generate_orders(self):
        cls = self._make_concrete()
        s = cls(name="test")
        orders = s.generate_orders()
        assert len(orders) == 1
        assert orders[0].symbol == "RELIANCE"

    def test_cannot_instantiate_abstract(self):
        from flinttrade_engine.strategy import BaseStrategy
        with pytest.raises(TypeError):
            BaseStrategy(name="abstract")


class TestStrategyRegistry:
    """Test strategy registration, creation, enable/disable."""

    def _make_concrete(self):
        from flinttrade_core.models import OHLCV, Order, Quote
        from flinttrade_engine.strategy import BaseStrategy

        class TestStrat(BaseStrategy):
            def on_tick(self, quote: Quote) -> None: pass
            def on_bar(self, bar: OHLCV) -> None: pass
            def on_signal(self, signal: dict) -> None: pass
            def generate_orders(self) -> list[Order]: return []

        return TestStrat

    def test_register_and_list(self):
        from flinttrade_engine.strategy import StrategyRegistry
        reg = StrategyRegistry()
        cls = self._make_concrete()
        reg.register(cls)
        assert "TestStrat" in reg.list_registered()

    def test_create_instance(self):
        from flinttrade_engine.strategy import StrategyRegistry
        reg = StrategyRegistry()
        cls = self._make_concrete()
        reg.register(cls)
        inst = reg.create("TestStrat", exchange="NFO")
        assert inst.exchange == "NFO"
        assert inst.state.value == "STOPPED"

    def test_enable_starts_strategy(self):
        from flinttrade_engine.strategy import StrategyRegistry
        reg = StrategyRegistry()
        cls = self._make_concrete()
        reg.register(cls)
        reg.create("TestStrat")
        reg.enable("TestStrat")
        assert reg.get("TestStrat").is_active

    def test_disable_pauses_strategy(self):
        from flinttrade_engine.strategy import StrategyRegistry
        reg = StrategyRegistry()
        cls = self._make_concrete()
        reg.register(cls)
        reg.create("TestStrat")
        reg.enable("TestStrat")
        reg.disable("TestStrat")
        assert reg.get("TestStrat").state.value == "PAUSED"

    def test_list_active(self):
        from flinttrade_engine.strategy import StrategyRegistry
        reg = StrategyRegistry()
        cls = self._make_concrete()
        reg.register(cls)
        reg.create("TestStrat")
        assert reg.list_active() == []
        reg.enable("TestStrat")
        assert reg.list_active() == ["TestStrat"]

    def test_stop_all(self):
        from flinttrade_engine.strategy import StrategyRegistry
        reg = StrategyRegistry()
        cls = self._make_concrete()
        reg.register(cls)
        reg.create("TestStrat")
        reg.enable("TestStrat")
        reg.stop_all()
        assert reg.list_active() == []

    def test_create_unregistered_raises(self):
        from flinttrade_engine.strategy import StrategyRegistry
        reg = StrategyRegistry()
        with pytest.raises(KeyError, match="not registered"):
            reg.create("NonExistent")

    def test_enable_without_create_raises(self):
        from flinttrade_engine.strategy import StrategyRegistry
        reg = StrategyRegistry()
        with pytest.raises(KeyError, match="No instance"):
            reg.enable("Ghost")

    def test_unregister_stops_instance(self):
        from flinttrade_engine.strategy import StrategyRegistry
        reg = StrategyRegistry()
        cls = self._make_concrete()
        reg.register(cls)
        reg.create("TestStrat")
        reg.enable("TestStrat")
        reg.unregister("TestStrat")
        assert "TestStrat" not in reg.list_registered()
        assert reg.get("TestStrat") is None


# ======================================================================
# StrategyRunner — async tick loop
# ======================================================================


class TestStrategyRunner:
    """Test the async strategy execution runner."""

    def _make_strategy(self, exchange="NSE"):
        from flinttrade_core.models import OHLCV, Order, Quote
        from flinttrade_engine.strategy import BaseStrategy

        class TickCountStrategy(BaseStrategy):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.ticks: list = []
                self.squared_off = False

            def on_tick(self, quote: Quote) -> None:
                self.ticks.append(quote)

            def on_bar(self, bar: OHLCV) -> None:
                pass

            def on_signal(self, signal: dict) -> None:
                pass

            def generate_orders(self) -> list[Order]:
                return []

            def on_square_off(self) -> None:
                self.squared_off = True

        return TickCountStrategy(name="TestTicker", exchange=exchange)

    @pytest.mark.asyncio
    async def test_runner_starts_and_stops(self):
        from unittest.mock import AsyncMock
        from flinttrade_core.models import Quote
        from flinttrade_engine.scheduler import StrategyRunner, TimeScheduler

        strategy = self._make_strategy()
        mock_client = MagicMock()
        mock_client.quotes = AsyncMock(return_value=Quote(symbol="RELIANCE", ltp=2500))

        # Scheduler that says market is open, not frozen, not square-off
        scheduler = TimeScheduler()
        scheduler.is_market_open = MagicMock(return_value=True)
        scheduler.is_deploy_frozen = MagicMock(return_value=False)
        scheduler.should_square_off = MagicMock(return_value=False)

        runner = StrategyRunner(
            strategy=strategy, client=mock_client,
            scheduler=scheduler, tick_interval_seconds=0.01,
            symbol="RELIANCE",
        )

        await runner.start()
        assert runner.is_running
        await asyncio.sleep(0.05)
        await runner.stop()

        assert not runner.is_running
        assert strategy.state.value == "STOPPED"
        assert runner.tick_count > 0
        assert len(strategy.ticks) > 0

    @pytest.mark.asyncio
    async def test_runner_delivers_ticks_when_deploy_frozen(self):
        """Deploy freeze must NOT block tick delivery.

        is_deploy_frozen() guards code *deployment* only. Strategies must
        continue to receive ticks during market hours even when a deploy freeze
        is active — otherwise live strategies would be silently starved of data.
        """
        from unittest.mock import AsyncMock
        from flinttrade_engine.scheduler import StrategyRunner, TimeScheduler

        strategy = self._make_strategy()
        mock_client = MagicMock()
        mock_client.quotes = AsyncMock(return_value=None)

        scheduler = TimeScheduler()
        scheduler.is_market_open = MagicMock(return_value=True)
        scheduler.is_deploy_frozen = MagicMock(return_value=True)
        scheduler.should_square_off = MagicMock(return_value=False)

        runner = StrategyRunner(
            strategy=strategy, client=mock_client,
            scheduler=scheduler, tick_interval_seconds=0.01,
        )

        await runner.start()
        await asyncio.sleep(0.05)
        await runner.stop()

        # Ticks SHOULD be delivered — deploy freeze must not gate tick delivery.
        mock_client.quotes.assert_called()

    @pytest.mark.asyncio
    async def test_runner_skips_tick_when_market_closed(self):
        from unittest.mock import AsyncMock
        from flinttrade_engine.scheduler import StrategyRunner, TimeScheduler

        strategy = self._make_strategy()
        mock_client = MagicMock()
        mock_client.quotes = AsyncMock()

        scheduler = TimeScheduler()
        scheduler.is_market_open = MagicMock(return_value=False)
        scheduler.is_deploy_frozen = MagicMock(return_value=False)
        scheduler.should_square_off = MagicMock(return_value=False)

        runner = StrategyRunner(
            strategy=strategy, client=mock_client,
            scheduler=scheduler, tick_interval_seconds=0.01,
        )

        await runner.start()
        await asyncio.sleep(0.05)
        await runner.stop()

        assert len(strategy.ticks) == 0
        mock_client.quotes.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_square_off_triggers(self):
        from unittest.mock import AsyncMock
        from flinttrade_engine.scheduler import StrategyRunner, TimeScheduler

        strategy = self._make_strategy()
        mock_client = MagicMock()
        mock_client.quotes = AsyncMock()

        scheduler = TimeScheduler()
        scheduler.is_market_open = MagicMock(return_value=True)
        scheduler.is_deploy_frozen = MagicMock(return_value=False)
        scheduler.should_square_off = MagicMock(return_value=True)

        runner = StrategyRunner(
            strategy=strategy, client=mock_client,
            scheduler=scheduler, tick_interval_seconds=0.01,
        )

        await runner.start()
        await asyncio.sleep(0.05)

        # Runner should have stopped due to square-off
        assert not runner.is_running
        assert strategy.squared_off
        assert strategy.state.value == "STOPPED"

    @pytest.mark.asyncio
    async def test_runner_pause_resume(self):
        from unittest.mock import AsyncMock
        from flinttrade_core.models import Quote
        from flinttrade_engine.scheduler import StrategyRunner, TimeScheduler

        strategy = self._make_strategy()
        mock_client = MagicMock()
        mock_client.quotes = AsyncMock(return_value=Quote(symbol="RELIANCE", ltp=2500))

        scheduler = TimeScheduler()
        scheduler.is_market_open = MagicMock(return_value=True)
        scheduler.is_deploy_frozen = MagicMock(return_value=False)
        scheduler.should_square_off = MagicMock(return_value=False)

        runner = StrategyRunner(
            strategy=strategy, client=mock_client,
            scheduler=scheduler, tick_interval_seconds=0.01,
            symbol="RELIANCE",
        )

        await runner.start()
        await asyncio.sleep(0.03)
        ticks_before_pause = len(strategy.ticks)
        assert ticks_before_pause > 0

        runner.pause()
        assert strategy.state.value == "PAUSED"
        # Loop continues but strategy is paused so _run_loop exits
        await asyncio.sleep(0.03)
        await runner.stop()


# ======================================================================
# StrategyScheduler — multi-strategy management
# ======================================================================


class TestStrategyScheduler:
    """Test multi-strategy lifecycle management."""

    def _make_strategy(self, name="S1", exchange="NSE"):
        from flinttrade_core.models import OHLCV, Order, Quote
        from flinttrade_engine.strategy import BaseStrategy

        class SimpleStrat(BaseStrategy):
            def on_tick(self, quote: Quote) -> None: pass
            def on_bar(self, bar: OHLCV) -> None: pass
            def on_signal(self, signal: dict) -> None: pass
            def generate_orders(self) -> list[Order]: return []

        return SimpleStrat(name=name, exchange=exchange)

    @pytest.mark.asyncio
    async def test_register_and_status(self):
        from flinttrade_engine.scheduler import StrategyScheduler

        mock_client = MagicMock()
        sched = StrategyScheduler(client=mock_client)

        s1 = self._make_strategy("Alpha", "NSE")
        s2 = self._make_strategy("Beta", "NFO")
        sched.register(s1, tick_interval=0.5)
        sched.register(s2, tick_interval=1.0)

        status = sched.status()
        assert "Alpha" in status
        assert "Beta" in status
        assert status["Alpha"]["exchange"] == "NSE"
        assert status["Beta"]["state"] == "STOPPED"

    @pytest.mark.asyncio
    async def test_start_and_stop_all(self):
        from unittest.mock import AsyncMock
        from flinttrade_core.models import Quote
        from flinttrade_engine.scheduler import StrategyScheduler, TimeScheduler

        mock_client = MagicMock()
        mock_client.quotes = AsyncMock(return_value=Quote(symbol="X", ltp=100))

        ts = TimeScheduler()
        ts.is_market_open = MagicMock(return_value=True)
        ts.is_deploy_frozen = MagicMock(return_value=False)
        ts.should_square_off = MagicMock(return_value=False)

        sched = StrategyScheduler(client=mock_client, time_scheduler=ts)
        s1 = self._make_strategy("A")
        sched.register(s1, tick_interval=0.01, symbol="X")

        await sched.start_all()
        assert sched.get_runner("A").is_running

        await asyncio.sleep(0.03)
        await sched.stop_all()

        assert not sched.get_runner("A").is_running

    @pytest.mark.asyncio
    async def test_stop_one(self):
        from flinttrade_engine.scheduler import StrategyScheduler

        mock_client = MagicMock()
        sched = StrategyScheduler(client=mock_client)
        s1 = self._make_strategy("ToStop")
        sched.register(s1)

        with pytest.raises(KeyError, match="No runner"):
            await sched.stop_one("NonExistent")

    @pytest.mark.asyncio
    async def test_get_runner(self):
        from flinttrade_engine.scheduler import StrategyScheduler

        mock_client = MagicMock()
        sched = StrategyScheduler(client=mock_client)
        s1 = self._make_strategy("Gamma")
        runner = sched.register(s1)

        assert sched.get_runner("Gamma") is runner
        assert sched.get_runner("Missing") is None


# ======================================================================
# Package exports
# ======================================================================


class TestPackageExports:
    """Verify __init__.py exports the public API."""

    def test_all_exports(self):
        from flinttrade_engine import __all__
        expected = [
            "SafetySystem", "OrderRouter", "TimeScheduler",
            "BaseStrategy", "StrategyRegistry", "StrategyState",
            "SafetyResult", "SafetyConfig", "KillSwitch",
            "StrategyRunner", "StrategyScheduler",
        ]
        for name in expected:
            assert name in __all__, f"Missing export: {name}"

    def test_version(self):
        from flinttrade_engine import __version__
        from flinttrade_core.version import APP_VERSION

        assert __version__ == APP_VERSION

    def test_package_exists(self):
        pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        assert os.path.exists(os.path.join(pkg_dir, "src", "__init__.py"))
        assert os.path.exists(os.path.join(pkg_dir, "README.md"))
