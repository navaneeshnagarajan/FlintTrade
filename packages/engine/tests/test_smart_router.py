# packages/engine/tests/test_smart_router.py
"""Tests for SmartOrderRouter — liquidity-aware, slippage-budgeted routing.

Uses mocked depth/volume providers and a mock base router so no broker
connectivity is required.

Coverage:
- High urgency: single order, no splitting
- Medium urgency: fits in depth → single order; exceeds depth → splits
- Low urgency: TWAP splitting across slices
- Slippage estimation utility
- SmartRouteResult.add_child and compute_average_slippage
- ChildOrderResult status propagation (placed / failed)
- Child order failure handling
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.engine.src.smart_router import (
    ChildOrderResult,
    SmartOrderRouter,
    SmartRouteResult,
    _available_qty_top_n,
    _best_price,
)


# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------


def _make_depth(ask_qty: int = 500, bid_qty: int = 500, price: float = 100.0) -> dict:
    """Build a minimal depth dict with one level each side."""
    return {
        "asks": [{"price": price + 0.05, "quantity": ask_qty}],
        "bids": [{"price": price - 0.05, "quantity": bid_qty}],
    }


def _make_multi_level_depth(levels: int = 5, qty_per_level: int = 200) -> dict:
    """Build a depth dict with multiple price levels."""
    return {
        "asks": [{"price": 100.0 + i * 0.05, "quantity": qty_per_level} for i in range(levels)],
        "bids": [{"price": 100.0 - i * 0.05, "quantity": qty_per_level} for i in range(levels)],
    }


@dataclass
class FakeDecision:
    """Mimics RoutingDecision for test purposes."""

    passed: bool
    error: str = ""
    order_response: object | None = None


@dataclass
class FakeOrderResponse:
    orderid: str = "MOCK_OID_001"
    status: str = "COMPLETE"


def _make_base_router(*, passed: bool = True, order_id: str = "OID_001") -> MagicMock:
    """Create a mock base router that always succeeds (or fails)."""
    router = MagicMock()
    response = FakeOrderResponse(orderid=order_id) if passed else None
    decision = FakeDecision(passed=passed, order_response=response)

    # Support both sync route() and async route_order()
    router.route = MagicMock(return_value=decision)
    router.route_order = AsyncMock(return_value=decision)
    return router


async def _run(coro):
    """Run a coroutine in tests."""
    return await coro


# ---------------------------------------------------------------------------
# Utility function tests
# ---------------------------------------------------------------------------


def test_available_qty_top_n_buy_uses_asks() -> None:
    depth = _make_multi_level_depth(levels=5, qty_per_level=100)
    result = _available_qty_top_n(depth, "BUY", n=5)
    assert result == 500  # 5 levels × 100


def test_available_qty_top_n_sell_uses_bids() -> None:
    depth = _make_multi_level_depth(levels=5, qty_per_level=150)
    result = _available_qty_top_n(depth, "SELL", n=5)
    assert result == 750  # 5 × 150


def test_available_qty_top_n_limits_to_n_levels() -> None:
    depth = _make_multi_level_depth(levels=10, qty_per_level=100)
    assert _available_qty_top_n(depth, "BUY", n=3) == 300


def test_available_qty_empty_depth_returns_zero() -> None:
    assert _available_qty_top_n({}, "BUY") == 0


def test_best_price_buy_returns_lowest_ask() -> None:
    depth = {"asks": [{"price": 101.0, "quantity": 100}, {"price": 102.0, "quantity": 100}]}
    assert _best_price(depth, "BUY") == 101.0


def test_best_price_sell_returns_highest_bid() -> None:
    depth = {"bids": [{"price": 99.0, "quantity": 100}, {"price": 98.0, "quantity": 100}]}
    assert _best_price(depth, "SELL") == 99.0


def test_best_price_empty_returns_none() -> None:
    assert _best_price({"asks": [], "bids": []}, "BUY") is None


# ---------------------------------------------------------------------------
# SmartRouteResult
# ---------------------------------------------------------------------------


def test_smart_route_result_add_child_increments_filled() -> None:
    result = SmartRouteResult(symbol="X", exchange="NFO", action="BUY", total_quantity=100)
    child = ChildOrderResult(quantity=50, price_type="MARKET", status="placed")
    result.add_child(child)
    assert result.filled_quantity == 50


def test_smart_route_result_failed_child_not_counted() -> None:
    result = SmartRouteResult(symbol="X", exchange="NFO", action="BUY", total_quantity=100)
    child = ChildOrderResult(quantity=50, price_type="MARKET", status="failed")
    result.add_child(child)
    assert result.filled_quantity == 0


def test_compute_average_slippage_weighted() -> None:
    result = SmartRouteResult(symbol="X", exchange="NFO", action="BUY", total_quantity=200)
    result.add_child(ChildOrderResult(quantity=100, price_type="MARKET", status="placed", slippage_bps=10.0))
    result.add_child(ChildOrderResult(quantity=100, price_type="MARKET", status="placed", slippage_bps=20.0))
    result.compute_average_slippage()
    assert result.average_slippage_bps == 15.0


# ---------------------------------------------------------------------------
# High urgency routing
# ---------------------------------------------------------------------------


def test_high_urgency_single_order(tmp_path) -> None:
    base = _make_base_router(passed=True)
    depth_fn = AsyncMock(return_value=_make_depth(ask_qty=100))
    vol_fn = AsyncMock(return_value=1000)

    router = SmartOrderRouter(
        base_router=base,
        depth_provider=depth_fn,
        volume_provider=vol_fn,
        twap_slices=5,
        twap_window_seconds=60,
    )
    result = asyncio.run(
        router.route("NIFTY25FUT", "NFO", 50, "BUY", urgency="high")
    )
    assert len(result.child_orders) == 1
    assert result.child_orders[0].status == "placed"
    assert result.filled_quantity == 50
    assert result.completed is True
    # depth_provider should NOT be called for high urgency
    depth_fn.assert_not_called()


def test_high_urgency_does_not_split_even_large_qty() -> None:
    base = _make_base_router(passed=True)
    router = SmartOrderRouter(
        base_router=base,
        depth_provider=AsyncMock(return_value=_make_depth(ask_qty=100)),
        volume_provider=AsyncMock(return_value=0),
    )
    result = asyncio.run(router.route("NIFTY25FUT", "NFO", 9000, "BUY", urgency="high"))
    assert len(result.child_orders) == 1


# ---------------------------------------------------------------------------
# Medium urgency routing
# ---------------------------------------------------------------------------


def test_medium_urgency_single_order_when_fits_in_depth() -> None:
    base = _make_base_router(passed=True)
    # 1000 available, order qty = 500 → single child
    depth = _make_multi_level_depth(levels=5, qty_per_level=200)  # 1000 total
    router = SmartOrderRouter(
        base_router=base,
        depth_provider=AsyncMock(return_value=depth),
        volume_provider=AsyncMock(return_value=5000),
    )
    result = asyncio.run(router.route("NIFTY25FUT", "NFO", 500, "BUY", urgency="medium"))
    assert len(result.child_orders) == 1
    assert result.child_orders[0].status == "placed"


def test_medium_urgency_splits_when_exceeds_depth() -> None:
    base = _make_base_router(passed=True)
    # Only 200 available in top 5, order qty = 600 → splits
    depth = _make_multi_level_depth(levels=5, qty_per_level=40)  # 200 total
    router = SmartOrderRouter(
        base_router=base,
        depth_provider=AsyncMock(return_value=depth),
        volume_provider=AsyncMock(return_value=1000),
    )
    result = asyncio.run(router.route("NIFTY25FUT", "NFO", 600, "BUY", urgency="medium"))
    assert len(result.child_orders) > 1
    total_placed = sum(c.quantity for c in result.child_orders if c.status == "placed")
    assert total_placed == 600


def test_medium_urgency_child_failure_recorded(tmp_path) -> None:
    base = _make_base_router(passed=False)
    depth = _make_depth(ask_qty=1000)
    router = SmartOrderRouter(
        base_router=base,
        depth_provider=AsyncMock(return_value=depth),
        volume_provider=AsyncMock(return_value=1000),
    )
    result = asyncio.run(router.route("NIFTY25FUT", "NFO", 100, "BUY", urgency="medium"))
    assert result.child_orders[0].status == "failed"
    assert result.filled_quantity == 0


# ---------------------------------------------------------------------------
# Low urgency (TWAP)
# ---------------------------------------------------------------------------


def test_low_urgency_splits_into_n_slices() -> None:
    base = _make_base_router(passed=True)
    router = SmartOrderRouter(
        base_router=base,
        depth_provider=AsyncMock(return_value=_make_depth()),
        volume_provider=AsyncMock(return_value=1000),
        twap_slices=5,
        twap_window_seconds=0,  # Zero window so tests don't sleep
    )
    result = asyncio.run(router.route("NIFTY25FUT", "NFO", 500, "BUY", urgency="low"))
    assert len(result.child_orders) == 5
    total = sum(c.quantity for c in result.child_orders)
    assert total == 500


def test_low_urgency_last_slice_absorbs_remainder() -> None:
    base = _make_base_router(passed=True)
    router = SmartOrderRouter(
        base_router=base,
        depth_provider=AsyncMock(return_value=_make_depth()),
        volume_provider=AsyncMock(return_value=1000),
        twap_slices=3,
        twap_window_seconds=0,
    )
    # 100 / 3 = 33 × 2 + 34 (last)
    result = asyncio.run(router.route("NIFTY25FUT", "NFO", 100, "BUY", urgency="low"))
    quantities = [c.quantity for c in result.child_orders]
    assert sum(quantities) == 100
    assert quantities[-1] == 34  # remainder goes to last slice


# ---------------------------------------------------------------------------
# Strategy tag propagation
# ---------------------------------------------------------------------------


def test_strategy_tag_propagated_to_order(tmp_path) -> None:
    captured_orders = []

    async def fake_route_order(order):
        captured_orders.append(order)
        return FakeDecision(passed=True, order_response=FakeOrderResponse())

    base = MagicMock()
    base.route_order = fake_route_order

    router = SmartOrderRouter(
        base_router=base,
        depth_provider=AsyncMock(return_value=_make_depth(ask_qty=1000)),
        volume_provider=AsyncMock(return_value=1000),
    )
    asyncio.run(router.route("X", "NFO", 10, "BUY", urgency="high", strategy="MyStrat"))
    assert captured_orders[0].strategy == "MyStrat"
