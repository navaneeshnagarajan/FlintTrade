"""Regression tests for Python batch spread input validation."""

from __future__ import annotations

import doctest
import inspect
from collections.abc import Callable, Iterator

import pytest

try:
    from tick_engine import (
        LegConfig,
        OptionType,
        SpreadBacktest,
        SpreadConfig,
        iron_condor_config,
        run_batch,
        run_spreads_batch,
        straddle_config,
        strangle_config,
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


def test_spread_fees_charge_exactly_entry_and_exit_per_absolute_quantity() -> None:
    config = SpreadConfig(initial_capital=100.0, fees=0.1)
    config.add_leg(LegConfig(OptionType.Call, 100.0, -3, 2))

    result = SpreadBacktest("fees", config).run(
        [1, 2],
        [[10.0, 12.0]],
        [True, False],
        [False, True],
    )

    assert result.total_pnl == pytest.approx(-25.2)
    assert result.equity_curve == pytest.approx([100.0, 94.0, 74.8, 74.8])


@pytest.mark.parametrize("runner_kind", ["object", "raw"])
def test_batch_reports_first_semantic_error_before_later_extraction_error(runner_kind: str) -> None:
    if runner_kind == "object":
        first = (
            SpreadBacktest("first", _config()),
            [1, 2],
            [[10.0, -1.0]],
            [True, False],
            [False, True],
        )
        trailing = (
            SpreadBacktest("trailing", _config()),
            [True, 2],
            [[10.0, 11.0]],
            [True, False],
            [False, True],
        )
        runner = run_spreads_batch
    else:
        first = ("first", _config(), [1, 2], [[10.0, -1.0]], [True, False], [False, True])
        trailing = ("trailing", _config(), [True, 2], [[10.0, 11.0]], [True, False], [False, True])
        runner = run_batch

    with pytest.raises(ValueError, match=r"legs_premiums\[0\]\[1\] must be finite and non-negative"):
        runner([first, trailing])


@pytest.mark.parametrize("runner_kind", ["object", "raw"])
def test_batch_validates_an_item_before_requesting_the_next_item(runner_kind: str) -> None:
    if runner_kind == "object":
        first = (
            SpreadBacktest("first", _config()),
            [1, 2],
            [[10.0, -1.0]],
            [True, False],
            [False, True],
        )
        runner = run_spreads_batch
    else:
        first = ("first", _config(), [1, 2], [[10.0, -1.0]], [True, False], [False, True])
        runner = run_batch

    def items() -> Iterator[object]:
        yield first
        raise RuntimeError("later iterator failure")

    with pytest.raises(ValueError, match=r"legs_premiums\[0\]\[1\] must be finite and non-negative"):
        runner(items())


def test_batch_preflight_rejects_cross_bar_aggregate_overflow(
    configured_batch_runner: ConfiguredBatchRunner,
) -> None:
    config = SpreadConfig(initial_capital=100.0, fees=0.0)
    config.add_leg(LegConfig(OptionType.Call, 100.0, 1, 1))
    config.add_leg(LegConfig(OptionType.Put, 100.0, -1, 1))
    large_finite_premium = float.fromhex("0x1.fffffffffffffp+1023") * 0.75

    with pytest.raises(ValueError, match="spread arithmetic overflow at premium bar 1"):
        configured_batch_runner(
            config,
            [[0.0, large_finite_premium], [large_finite_premium, 0.0]],
        )


@pytest.mark.parametrize("runner_kind", ["object", "raw"])
def test_batch_preflight_rejects_force_close_return_overflow(runner_kind: str) -> None:
    config = SpreadConfig(initial_capital=1e-300, fees=1.0)
    config.add_leg(LegConfig(OptionType.Call, 100.0, 1, 100))
    timestamps = [1, 2]
    premiums = [[1e7, 1e7]]
    entries = [True, False]
    exits = [False, False]

    if runner_kind == "object":
        item = (SpreadBacktest("overflow", config), timestamps, premiums, entries, exits)
        runner = run_spreads_batch
    else:
        item = ("overflow", config, timestamps, premiums, entries, exits)
        runner = run_batch

    with pytest.raises(ValueError, match="spread arithmetic overflow at premium bar 1"):
        runner([item])


def test_spread_binding_signatures_and_docs_match_python_contract() -> None:
    assert str(inspect.signature(LegConfig)) == "(option_type, strike, quantity, lot_size=50)"
    assert str(inspect.signature(SpreadConfig)) == (
        "(initial_capital=100000.0, fees=0.001, max_loss=None, target_profit=None)"
    )
    assert str(inspect.signature(straddle_config)) == (
        "(strike, lot_size=50, short=True, initial_capital=100000.0, fees=0.001)"
    )
    assert str(inspect.signature(strangle_config)) == (
        "(call_strike, put_strike, lot_size=50, short=True, initial_capital=100000.0, fees=0.001)"
    )
    assert str(inspect.signature(iron_condor_config)) == (
        "(short_call, long_call, short_put, long_put, lot_size=50, "
        "initial_capital=100000.0, fees=0.001)"
    )
    assert "OptionType.Call" in (OptionType.__doc__ or "")
    assert "OptionType.Put" in (OptionType.__doc__ or "")
    assert "SpreadBacktest" in (run_spreads_batch.__doc__ or "")
    assert "raw parameter tuples" in (run_batch.__doc__ or "")


def test_python_facade_examples_are_executable() -> None:
    import tick_engine

    result = doctest.testmod(tick_engine)
    assert result.attempted == 9
    assert result.failed == 0


@pytest.mark.parametrize("premium", [float("nan"), float("inf"), float("-inf"), -0.01])
def test_batch_rejects_invalid_premium_in_parallel_preflight(
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
def test_batch_rejects_invalid_financial_config_before_simulation(
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


@pytest.mark.parametrize(
    "constructor",
    [
        lambda: SpreadConfig(initial_capital=True, fees=0.0),
        lambda: SpreadConfig(initial_capital=100.0, fees=True),
        lambda: SpreadConfig(initial_capital=100.0, fees=0.0, max_loss=True),
        lambda: SpreadConfig(initial_capital=100.0, fees=0.0, target_profit=True),
        lambda: LegConfig(OptionType.Call, True, 1, 1),
        lambda: LegConfig(OptionType.Call, 100.0, True, 1),
        lambda: LegConfig(OptionType.Call, 100.0, 1, True),
    ],
    ids=[
        "initial-capital",
        "fees",
        "max-loss",
        "target-profit",
        "strike",
        "quantity",
        "lot-size",
    ],
)
def test_spread_numeric_constructors_reject_booleans(constructor: Callable[[], object]) -> None:
    with pytest.raises(TypeError, match="boolean"):
        constructor()


@pytest.mark.parametrize("field", ["strike", "quantity", "lot_size"])
def test_leg_numeric_setters_reject_booleans(field: str) -> None:
    leg = LegConfig(OptionType.Call, 100.0, 1, 1)

    with pytest.raises(TypeError, match="boolean"):
        setattr(leg, field, True)


@pytest.mark.parametrize(
    "constructor",
    [
        lambda: straddle_config(True),
        lambda: strangle_config(True, 100.0),
        lambda: iron_condor_config(True, 110.0, 90.0, 80.0),
    ],
    ids=["straddle", "strangle", "iron-condor"],
)
def test_spread_convenience_constructors_reject_boolean_numerics(
    constructor: Callable[[], object],
) -> None:
    with pytest.raises(TypeError, match="boolean"):
        constructor()


@pytest.mark.parametrize(
    ("timestamps", "premiums"),
    [
        ([True, 2], [[10.0, 11.0]]),
        ([1, 2], [[True, 11.0]]),
    ],
    ids=["timestamp", "premium"],
)
def test_batch_rejects_booleans_in_numeric_series(
    batch_runner: BatchRunner,
    timestamps: list[int],
    premiums: list[list[float]],
) -> None:
    with pytest.raises(TypeError, match="boolean"):
        batch_runner([("invalid", timestamps, premiums, [True, False], [False, True])])


@pytest.mark.parametrize(
    ("timestamps", "premiums"),
    [
        ([True, 2], [[10.0, 11.0]]),
        ([1, 2], [[True, 11.0]]),
    ],
    ids=["timestamp", "premium"],
)
def test_single_spread_run_rejects_booleans_in_numeric_series(
    timestamps: list[int],
    premiums: list[list[float]],
) -> None:
    backtest = SpreadBacktest("invalid", _config())

    with pytest.raises(TypeError, match="boolean"):
        backtest.run(timestamps, premiums, [True, False], [False, True])
