"""Known lifecycle events raise when the current state does not permit them."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.scheduler import StrategyRunner, TimeScheduler
from flinttrade_engine.state_manager import InvalidTransitionError
from flinttrade_engine.strategy import BaseStrategy, StrategyRegistry, StrategyState
from flinttrade_engine.strategy_execution import StrategyExecutionContract, StrategyExecutionMode


class _Strategy(BaseStrategy):
    supported_execution_modes = frozenset({StrategyExecutionMode.READ_ONLY})

    def __init__(self, name: str = "transition") -> None:
        super().__init__(
            name=name,
            exchange="NSE",
            execution_contract=StrategyExecutionContract.read_only(),
        )

    def on_tick(self, quote: Quote) -> None:
        del quote

    def on_bar(self, bar: OHLCV) -> None:
        del bar

    def on_signal(self, signal: dict) -> None:
        del signal

    def generate_orders(self) -> list[Order]:
        return []


def test_start_from_active_raises() -> None:
    strategy = _Strategy()
    strategy.start()

    with pytest.raises(InvalidTransitionError):
        strategy.start()

    assert strategy.state is StrategyState.ACTIVE


def test_start_from_stopped_still_activates() -> None:
    strategy = _Strategy()

    strategy.start()

    assert strategy.state is StrategyState.ACTIVE


def test_pause_resume_and_stop_reject_a_state_that_does_not_permit_them() -> None:
    strategy = _Strategy()

    with pytest.raises(InvalidTransitionError):
        strategy.pause()
    with pytest.raises(InvalidTransitionError):
        strategy.resume()
    with pytest.raises(InvalidTransitionError):
        strategy.stop()

    assert strategy.state is StrategyState.STOPPED


def _native_runner(strategy: _Strategy) -> StrategyRunner:
    client = MagicMock()
    client.quotes = AsyncMock(return_value=None)
    scheduler = TimeScheduler()
    scheduler.session_active = MagicMock(return_value=False)
    scheduler.should_square_off = MagicMock(return_value=False)
    return StrategyRunner(
        strategy=strategy,
        client=client,
        scheduler=scheduler,
        tick_interval_seconds=30.0,
    )


@pytest.mark.asyncio
async def test_second_runner_start_while_running_returns_without_raising() -> None:
    strategy = _Strategy(name="already_running")
    runner = _native_runner(strategy)
    await runner.start()
    try:
        await runner.start()
        assert strategy.state is StrategyState.ACTIVE
        assert runner.is_running is True
    finally:
        await runner.stop()


def test_registry_enable_of_an_active_strategy_does_not_raise() -> None:
    registry = StrategyRegistry()
    registry.register(_Strategy)
    registry.create("_Strategy")
    registry.enable("_Strategy")

    registry.enable("_Strategy")

    assert registry.get("_Strategy").state is StrategyState.ACTIVE


def test_registry_stop_all_and_unregister_ignore_an_already_stopped_strategy() -> None:
    registry = StrategyRegistry()
    registry.register(_Strategy)
    registry.create("_Strategy")

    registry.stop_all()
    registry.unregister("_Strategy")

    assert registry.get("_Strategy") is None
