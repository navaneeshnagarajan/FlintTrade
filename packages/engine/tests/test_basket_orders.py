"""Tests for packages/engine/src/basket_orders.py.

All broker/router interactions are mocked — no live OpenAlgo required.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.engine.src.basket_orders import (
    BasketLeg,
    BasketOrderExecutor,
    BasketResult,
    BasketValidationError,
    LegResult,
    _leg_to_order,
    _validate_legs,
)
from packages.core.src.models import OrderResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_decision(passed: bool = True, order_id: str = "ORD001", error: str = "") -> MagicMock:
    """Build a mock RoutingDecision."""
    decision = MagicMock()
    decision.passed = passed
    decision.error = error
    if passed:
        decision.order_response = OrderResponse(status="COMPLETE", orderid=order_id)
    else:
        decision.order_response = None
    return decision


def _make_executor(decisions: list[MagicMock] | None = None) -> tuple[BasketOrderExecutor, MagicMock]:
    """Build a BasketOrderExecutor with a mocked router.

    Args:
        decisions: Ordered list of RoutingDecision mocks to return on successive calls.

    Returns:
        (executor, mock_router)
    """
    router = MagicMock()
    router.route_order = AsyncMock(
        side_effect=decisions if decisions else [_make_decision()]
    )
    executor = BasketOrderExecutor(router=router, rollback_delay_seconds=0.0)
    return executor, router


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _leg(
    symbol: str = "NIFTY25MAYFUT",
    exchange: str = "NFO",
    action: str = "BUY",
    quantity: int = 50,
    order_type: str = "MARKET",
) -> BasketLeg:
    return BasketLeg(
        symbol=symbol,
        exchange=exchange,
        action=action,
        quantity=quantity,
        order_type=order_type,
    )


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestValidateLeg:
    """_validate_legs rejects malformed leg lists."""

    def test_empty_legs_raises(self):
        with pytest.raises(BasketValidationError, match="at least one"):
            _validate_legs([])

    def test_missing_symbol_raises(self):
        with pytest.raises(BasketValidationError, match="symbol"):
            _validate_legs([_leg(symbol="")])

    def test_missing_exchange_raises(self):
        with pytest.raises(BasketValidationError, match="exchange"):
            _validate_legs([_leg(exchange="")])

    def test_invalid_action_raises(self):
        bad = _leg()
        bad.action = "HOLD"
        with pytest.raises(BasketValidationError, match="action"):
            _validate_legs([bad])

    def test_zero_quantity_raises(self):
        with pytest.raises(BasketValidationError, match="quantity"):
            _validate_legs([_leg(quantity=0)])

    def test_negative_quantity_raises(self):
        with pytest.raises(BasketValidationError, match="quantity"):
            _validate_legs([_leg(quantity=-10)])

    def test_limit_order_without_price_raises(self):
        leg = BasketLeg("SYM", "NSE", "BUY", 10, "LIMIT", price=None)
        with pytest.raises(BasketValidationError, match="price"):
            _validate_legs([leg])

    def test_sl_order_without_trigger_raises(self):
        leg = BasketLeg("SYM", "NSE", "SELL", 10, "SL", price=100.0, trigger_price=None)
        with pytest.raises(BasketValidationError, match="trigger_price"):
            _validate_legs([leg])

    def test_valid_legs_do_not_raise(self):
        _validate_legs([_leg(), _leg(action="SELL")])  # should not raise


# ---------------------------------------------------------------------------
# _leg_to_order conversion
# ---------------------------------------------------------------------------


class TestLegToOrder:
    """_leg_to_order produces valid Order objects."""

    def test_market_buy_conversion(self):
        leg = _leg()
        order = _leg_to_order(leg, "test_strategy")
        assert order.symbol == "NIFTY25MAYFUT"
        assert str(order.action) in ("BUY", "Action.BUY")
        assert str(order.pricetype) in ("MARKET", "PriceType.MARKET")
        assert order.strategy == "test_strategy"
        assert order.quantity == "50"

    def test_limit_sell_conversion(self):
        leg = BasketLeg("INFY", "NSE", "SELL", 100, "LIMIT", price=1500.0)
        order = _leg_to_order(leg, "strat")
        assert order.price == "1500.0"
        assert str(order.pricetype) in ("LIMIT", "PriceType.LIMIT")


# ---------------------------------------------------------------------------
# BasketOrderExecutor — success path
# ---------------------------------------------------------------------------


class TestBasketExecutorSuccess:
    """Full success: all legs placed, no rollback."""

    def test_single_leg_success(self):
        decisions = [_make_decision(True, "ORD1")]
        executor, router = _make_executor(decisions)
        result = _run(executor.execute([_leg()], strategy="s1"))

        assert result.success
        assert result.placed_count == 1
        assert result.failed_count == 0
        assert result.rolled_back is False
        assert result.order_ids == ["ORD1"]
        assert len(result.legs) == 1
        assert result.legs[0].success

    def test_two_legs_success(self):
        decisions = [_make_decision(True, "O1"), _make_decision(True, "O2")]
        executor, router = _make_executor(decisions)
        legs = [_leg(action="BUY"), _leg(action="SELL")]
        result = _run(executor.execute(legs, strategy="two"))

        assert result.success
        assert result.placed_count == 2
        assert set(result.order_ids) == {"O1", "O2"}

    def test_buy_legs_placed_before_sell_legs(self):
        """BUY legs must be routed before SELL legs."""
        call_log: list[str] = []

        async def record_route(order, **_kw):
            call_log.append(str(order.action))
            return _make_decision(True, "X")

        router = MagicMock()
        router.route_order = record_route
        executor = BasketOrderExecutor(router=router, rollback_delay_seconds=0.0)

        legs = [
            _leg(symbol="A", action="SELL"),
            _leg(symbol="B", action="BUY"),
        ]
        _run(executor.execute(legs))

        buy_idx = next(i for i, a in enumerate(call_log) if "BUY" in a)
        sell_idx = next(i for i, a in enumerate(call_log) if "SELL" in a)
        assert buy_idx < sell_idx

    def test_result_order_ids_property(self):
        decisions = [_make_decision(True, f"ID{i}") for i in range(3)]
        executor, _ = _make_executor(decisions)
        legs = [_leg() for _ in range(3)]
        result = _run(executor.execute(legs))
        assert len(result.order_ids) == 3


# ---------------------------------------------------------------------------
# BasketOrderExecutor — failure and rollback
# ---------------------------------------------------------------------------


class TestBasketExecutorRollback:
    """Atomicity: failure triggers rollback of already-placed legs."""

    def test_first_leg_fails_no_rollback_needed(self):
        decisions = [_make_decision(passed=False, error="Risk limit")]
        executor, router = _make_executor(decisions)
        result = _run(executor.execute([_leg()]))

        assert not result.success
        assert result.failed_leg_index == 0
        assert result.rolled_back is False  # nothing to roll back

    def test_second_leg_fails_triggers_rollback(self):
        decisions = [
            _make_decision(True, "PLACED1"),          # leg 0 placed
            _make_decision(False, error="No margin"),  # leg 1 fails
            _make_decision(True, "ROLLBACK1"),         # rollback order for leg 0
        ]
        executor, router = _make_executor(decisions)
        legs = [_leg(action="BUY"), _leg(action="SELL")]
        result = _run(executor.execute(legs))

        assert not result.success
        assert result.rolled_back is True
        assert result.failed_leg_index >= 0

        placed_leg = next(r for r in result.legs if r.success)
        assert placed_leg.rolled_back is True
        assert placed_leg.rollback_order_id == "ROLLBACK1"

    def test_router_exception_triggers_rollback(self):
        async def side_effect(order, **_kw):
            if "BUY" in str(order.action):
                return _make_decision(True, "O1")
            raise RuntimeError("Network error")

        router = MagicMock()
        router.route_order = side_effect
        executor = BasketOrderExecutor(router=router, rollback_delay_seconds=0.0)
        legs = [_leg(action="BUY"), _leg(action="SELL")]
        result = _run(executor.execute(legs))

        assert not result.success
        assert result.rolled_back is True

    def test_all_legs_fail_no_rollback(self):
        decisions = [_make_decision(False, error="blocked")]
        executor, _ = _make_executor(decisions)
        result = _run(executor.execute([_leg()]))
        assert not result.success
        assert result.rolled_back is False

    def test_failed_leg_not_in_rollback(self):
        """The leg that fails must not have rolled_back=True (nothing was placed)."""
        decisions = [_make_decision(False, error="safety block")]
        executor, _ = _make_executor(decisions)
        result = _run(executor.execute([_leg()]))

        failed_leg = result.legs[0]
        assert not failed_leg.success
        assert not failed_leg.rolled_back


# ---------------------------------------------------------------------------
# BasketResult properties
# ---------------------------------------------------------------------------


class TestBasketResultProperties:
    """Unit tests for BasketResult computed properties."""

    def _make_result(self, successes: list[bool]) -> BasketResult:
        legs = [
            LegResult(
                leg_index=i,
                symbol=f"SYM{i}",
                action="BUY",
                quantity=50,
                success=s,
                order_id=f"ID{i}" if s else "",
            )
            for i, s in enumerate(successes)
        ]
        return BasketResult(success=all(successes), legs=legs)

    def test_placed_count(self):
        r = self._make_result([True, True, False])
        assert r.placed_count == 2

    def test_failed_count(self):
        r = self._make_result([True, False, False])
        assert r.failed_count == 2

    def test_order_ids(self):
        r = self._make_result([True, False, True])
        assert r.order_ids == ["ID0", "ID2"]
