"""Tests for EMACrossover strategy."""

from __future__ import annotations

import pytest

from flinttrade_core.models import Quote


def _make_strategy(fast=3, slow=5, qty=1, router=None):
    from flinttrade_engine.strategies.ema_crossover import EMACrossover

    return EMACrossover(
        symbol="RELIANCE",
        exchange="NSE",
        fast_period=fast,
        slow_period=slow,
        quantity=qty,
        product="MIS",
        router=router,
    )


def _quote(ltp: float) -> Quote:
    return Quote(symbol="RELIANCE", exchange="NSE", ltp=ltp)


class TestEMACrossover:
    """Test EMA crossover signal generation."""

    @pytest.mark.asyncio
    async def test_no_signal_before_warmup(self):
        """Feed fewer ticks than slow_period — no orders should be placed."""
        strategy = _make_strategy(fast=3, slow=5)

        # Feed only 4 ticks (< slow_period of 5)
        for price in [100.0, 101.0, 102.0, 103.0]:
            await strategy.on_tick(_quote(price))

        assert strategy.generate_orders() == []
        assert strategy.position == 0
        assert strategy.last_signal == "NONE"

    @pytest.mark.asyncio
    async def test_buy_signal_on_golden_cross(self):
        """Rising prices after warmup should trigger a BUY (golden cross)."""
        strategy = _make_strategy(fast=3, slow=5)

        # Warmup: 5 flat prices — no cross yet
        for price in [100.0, 100.0, 100.0, 100.0, 100.0]:
            await strategy.on_tick(_quote(price))

        # Now feed sharply rising prices to make fast EMA > slow EMA
        for price in [110.0, 120.0, 130.0]:
            await strategy.on_tick(_quote(price))

        orders = strategy.generate_orders()
        assert len(orders) == 1
        order_arg = orders[0]
        assert order_arg.action.value == "BUY"
        assert strategy.position == 1
        assert strategy.last_signal == "BUY"

    @pytest.mark.asyncio
    async def test_sell_signal_on_death_cross(self):
        """Dropping prices after warmup should trigger a SELL (death cross)."""
        strategy = _make_strategy(fast=3, slow=5)

        # Warmup with flat prices
        for price in [100.0, 100.0, 100.0, 100.0, 100.0]:
            await strategy.on_tick(_quote(price))

        # Sharp drop to create death cross
        for price in [90.0, 80.0, 70.0]:
            await strategy.on_tick(_quote(price))

        orders = strategy.generate_orders()
        assert len(orders) == 1
        order_arg = orders[0]
        assert order_arg.action.value == "SELL"
        assert strategy.position == -1
        assert strategy.last_signal == "SELL"

    @pytest.mark.asyncio
    async def test_no_duplicate_signals(self):
        """Same crossover direction should not fire twice."""
        strategy = _make_strategy(fast=3, slow=5)

        # Warmup
        for price in [100.0, 100.0, 100.0, 100.0, 100.0]:
            await strategy.on_tick(_quote(price))

        # Trigger BUY with rising prices
        for price in [110.0, 120.0, 130.0]:
            await strategy.on_tick(_quote(price))

        buy_orders = strategy.generate_orders()
        assert len(buy_orders) == 1

        # Feed more rising prices — should NOT trigger another BUY
        for price in [135.0, 140.0, 145.0]:
            await strategy.on_tick(_quote(price))

        assert strategy.generate_orders() == []

    @pytest.mark.asyncio
    async def test_square_off_closes_long(self):
        """Square-off with a long position should place a SELL."""
        strategy = _make_strategy()
        strategy.position = 1  # Simulate being long

        await strategy.on_square_off()

        orders = strategy.generate_orders()
        assert len(orders) == 1
        order_arg = orders[0]
        assert order_arg.action.value == "SELL"
        assert strategy.position == 0

    @pytest.mark.asyncio
    async def test_square_off_flat(self):
        """Square-off with no position should NOT place any order."""
        strategy = _make_strategy()
        strategy.position = 0

        await strategy.on_square_off()

        assert strategy.generate_orders() == []
        assert strategy.position == 0

    @pytest.mark.asyncio
    async def test_reversal_doubles_quantity(self):
        """Reversing from short to long should send 2x quantity."""
        strategy = _make_strategy(fast=3, slow=5, qty=10)
        strategy.position = -1  # Already short
        strategy.last_signal = "SELL"

        # Warmup buffer with declining prices (to match short state)
        for price in [100.0, 95.0, 90.0, 85.0, 80.0]:
            strategy.price_buffer.append(price)

        # Now push rising prices to trigger BUY (reversal)
        for price in [100.0, 110.0, 120.0]:
            await strategy.on_tick(_quote(price))

        orders = strategy.generate_orders()
        assert len(orders) == 1
        order_arg = orders[0]
        assert order_arg.action.value == "BUY"
        assert order_arg.quantity == "20"  # 2x for reversal
        assert strategy.position == 1

    @pytest.mark.asyncio
    async def test_generate_orders_without_router(self):
        """Without a router, orders should be stored in pending list."""
        strategy = _make_strategy(fast=3, slow=5, router=None)

        # Warmup
        for price in [100.0, 100.0, 100.0, 100.0, 100.0]:
            await strategy.on_tick(_quote(price))

        # Trigger BUY
        for price in [110.0, 120.0, 130.0]:
            await strategy.on_tick(_quote(price))

        orders = strategy.generate_orders()
        assert len(orders) >= 1
        assert orders[0].action.value == "BUY"

        # generate_orders clears the list
        assert strategy.generate_orders() == []

    def test_ema_calculation(self):
        """Verify the EMA calculation helper."""
        from flinttrade_engine.strategies.ema_crossover import _ema

        prices = [10.0, 11.0, 12.0, 13.0, 14.0]
        ema3 = _ema(prices, 3)
        ema5 = _ema(prices, 5)
        # With rising prices, shorter EMA should be higher
        assert ema3 > ema5
