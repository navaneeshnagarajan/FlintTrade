"""Regression tests for Python batch spread input validation."""

from __future__ import annotations

from collections.abc import Callable

import pytest

try:
    from tick_engine import (
        LegConfig,
        OptionType,
        SpreadBacktest,
        SpreadConfig,
        run_batch,
        run_spreads_batch,
    )

    TICK_ENGINE_AVAILABLE = True
except ImportError:
    TICK_ENGINE_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not TICK_ENGINE_AVAILABLE,
    reason="tick_engine Rust extension not built - run `maturin develop` in packages/core/ticks/",
)

BatchInput = tuple[str, list[int], list[list[float]], list[bool], list[bool]]
BatchRunner = Callable[[list[BatchInput]], list[object]]
ConfiguredBatchRunner = Callable[[SpreadConfig, list[list[float]]], list[object]]


def _config() -> SpreadConfig:
    config = SpreadConfig(initial_capital=100.0, fees=0.0)
    config.add_leg(LegConfig(OptionType.Call, 100.0, 1, 1))
    return config


def _run_object_batch(items: list[BatchInput]) -> list[object]:
    return run_spreads_batch(
        [
            (SpreadBacktest(name, _config()), timestamps, premiums, entries, exits)
            for name, timestamps, premiums, entries, exits in items
        ]
    )


def _run_raw_batch(items: list[BatchInput]) -> list[object]:
    return run_batch(
        [
            (name, _config(), timestamps, premiums, entries, exits)
            for name, timestamps, premiums, entries, exits in items
        ]
    )


def _run_object_batch_with_config(config: SpreadConfig, premiums: list[list[float]]) -> list[object]:
    return run_spreads_batch(
        [(SpreadBacktest("invalid", config), [1, 2], premiums, [True, False], [False, True])]
    )


def _run_raw_batch_with_config(config: SpreadConfig, premiums: list[list[float]]) -> list[object]:
    return run_batch(
        [("invalid", config, [1, 2], premiums, [True, False], [False, True])]
    )


@pytest.fixture(params=[_run_object_batch, _run_raw_batch], ids=["run_spreads_batch", "run_batch"])
def batch_runner(request: pytest.FixtureRequest) -> BatchRunner:
    return request.param


@pytest.fixture(
    params=[_run_object_batch_with_config, _run_raw_batch_with_config],
    ids=["run_spreads_batch", "run_batch"],
)
def configured_batch_runner(request: pytest.FixtureRequest) -> ConfiguredBatchRunner:
    return request.param


@pytest.mark.parametrize(
    ("timestamps", "premiums", "entries", "exits", "message"),
    [
        ([1, 2], [[10.0]], [True, False], [False, True], r"legs_premiums\[0\] has 1 bars"),
        ([1, 2], [[10.0, 11.0, 12.0]], [True, False], [False, True], r"legs_premiums\[0\] has 3 bars"),
        ([1, 2], [], [True, False], [False, True], "has 0 series but config has 1 legs"),
        ([1, 2], [[10.0, 11.0], [20.0, 21.0]], [True, False], [False, True], "has 2 series"),
        ([1, 2], [[10.0, 11.0]], [True], [False, True], "entries and exits must have the same length"),
        ([1, 2], [[10.0, 11.0]], [True, False], [False], "entries and exits must have the same length"),
        ([], [[]], [], [], "timestamps cannot be empty"),
    ],
)
def test_batch_rejects_malformed_dimensions_with_value_error(
    batch_runner: BatchRunner,
    timestamps: list[int],
    premiums: list[list[float]],
    entries: list[bool],
    exits: list[bool],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        batch_runner([("invalid", timestamps, premiums, entries, exits)])


def test_batch_preserves_valid_extraction_order_and_results(batch_runner: BatchRunner) -> None:
    results = batch_runner(
        [
            ("rising", [1, 2], [[10.0, 12.0]], [True, False], [False, True]),
            ("falling", [1, 2], [[20.0, 17.0]], [True, False], [False, True]),
        ]
    )

    assert [result.strategy_name for result in results] == ["rising", "falling"]
    assert [result.total_pnl for result in results] == pytest.approx([2.0, -3.0])


@pytest.mark.parametrize("premium", [float("nan"), float("inf"), float("-inf"), -0.01])
def test_batch_rejects_invalid_premium_before_parallel_work(
    configured_batch_runner: ConfiguredBatchRunner,
    premium: float,
) -> None:
    with pytest.raises(ValueError, match=r"legs_premiums\[0\]\[1\] must be finite and non-negative"):
        configured_batch_runner(_config(), [[10.0, premium]])


@pytest.mark.parametrize(
    ("config_kwargs", "leg_kwargs", "add_leg", "message"),
    [
        ({"initial_capital": float("nan")}, {}, True, "initial_capital must be finite and positive"),
        ({"initial_capital": 0.0}, {}, True, "initial_capital must be finite and positive"),
        ({"fees": float("inf")}, {}, True, "fees must be finite and non-negative"),
        ({"fees": -0.01}, {}, True, "fees must be finite and non-negative"),
        ({"max_loss": 0.0}, {}, True, "max_loss must be finite and positive"),
        ({"target_profit": float("nan")}, {}, True, "target_profit must be finite and positive"),
        ({}, {}, False, "config must contain at least one leg"),
        ({}, {"strike": 0.0}, True, r"config\.legs\[0\] strike must be finite and positive"),
        ({}, {"strike": float("inf")}, True, r"config\.legs\[0\] strike must be finite and positive"),
        ({}, {"quantity": 0}, True, r"config\.legs\[0\] quantity cannot be zero"),
        ({}, {"lot_size": 0}, True, r"config\.legs\[0\] lot_size must be positive"),
    ],
)
def test_batch_rejects_invalid_financial_config_before_parallel_work(
    configured_batch_runner: ConfiguredBatchRunner,
    config_kwargs: dict[str, float],
    leg_kwargs: dict[str, float | int],
    add_leg: bool,
    message: str,
) -> None:
    config = SpreadConfig(
        initial_capital=config_kwargs.get("initial_capital", 100.0),
        fees=config_kwargs.get("fees", 0.0),
        max_loss=config_kwargs.get("max_loss"),
        target_profit=config_kwargs.get("target_profit"),
    )
    if add_leg:
        config.add_leg(
            LegConfig(
                OptionType.Call,
                leg_kwargs.get("strike", 100.0),
                leg_kwargs.get("quantity", 1),
                leg_kwargs.get("lot_size", 1),
            )
        )

    with pytest.raises(ValueError, match=message):
        configured_batch_runner(config, [[10.0, 11.0]] if add_leg else [])
