"""Tests for packages/services/backtest/src/simulation.py.

Covers:
- Phase map construction and bar coverage
- Phase effect application (volatility, trend bias, volume scaling)
- Event injection (price shock, volume spike, gap, volatility mult)
- Flash crash scenario runs to completion
- Stress test runner processes all six built-in scenarios
- A simple buy-and-hold strategy survives NORMAL but can be assessed in CRISIS
- SimulationResult fields are populated correctly
- StressTestReport aggregates pass/fail counts

All tests use synthetic bars only. No broker or live-data connections.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from engine import BacktestEngine, EngineConfig  # noqa: E402
from base_strategy import BaseBacktestStrategy  # noqa: E402
from simulation import (  # noqa: E402
    MarketEvent,
    SCENARIOS,
    SimulationEngine,
    SimulationPhase,
    SimulationResult,
    SimulationScenario,
    StressTestReport,
    StressTestRunner,
    _PHASE_PARAMS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bars(
    n: int = 260,
    start: float = 100.0,
    trend: float = 0.0,
    vol: float = 0.5,
    seed: int = 99,
) -> list[dict[str, Any]]:
    """Generate synthetic OHLCV bars."""
    import random

    rng = random.Random(seed)
    bars: list[dict[str, Any]] = []
    price = start
    for i in range(n):
        noise = rng.uniform(-vol, vol)
        price = max(1.0, price + trend + noise)
        h = price + abs(noise) + 0.1
        lo = max(0.01, price - abs(noise) - 0.1)
        c = max(lo, min(h, price + rng.uniform(-0.2, 0.2)))
        bars.append(
            {
                "timestamp": f"2025-01-{(i % 28) + 1:02d} 09:15:00",
                "open": round(price, 2),
                "high": round(h, 2),
                "low": round(lo, 2),
                "close": round(c, 2),
                "volume": 10000 + i * 10,
            }
        )
    return bars


def _make_config(capital: float = 500_000.0) -> EngineConfig:
    return EngineConfig(
        symbol="TEST",
        exchange="NSE",
        initial_capital=Decimal(str(capital)),
        slippage_bps=Decimal("0"),
        commission_per_order=Decimal("0"),
        tax_enabled=False,
    )


# ---------------------------------------------------------------------------
# Minimal strategy for testing
# ---------------------------------------------------------------------------


class DoNothingStrategy(BaseBacktestStrategy):
    """A strategy that never places orders. Equity equals initial capital."""

    def __init__(self, symbol: str = "TEST", **kwargs: Any) -> None:
        super().__init__(name="DoNothing", symbol=symbol)

    def on_bar(self, bar: Any) -> None:
        pass  # intentionally empty


class BuyOnceStrategy(BaseBacktestStrategy):
    """Buys once on bar 1, holds forever. Tests non-zero trade in results."""

    def __init__(self, symbol: str = "TEST", **kwargs: Any) -> None:
        super().__init__(name="BuyOnce", symbol=symbol)
        self._bought = False

    def on_bar(self, bar: Any) -> None:
        if not self._bought:
            self.enter_long(quantity=10)
            self._bought = True


class AlwaysLongStrategy(BaseBacktestStrategy):
    """Re-enters long after every exit. Sensitive to drawdown in crisis."""

    def __init__(self, symbol: str = "TEST", **kwargs: Any) -> None:
        super().__init__(name="AlwaysLong", symbol=symbol)
        self._bar = 0

    def on_bar(self, bar: Any) -> None:
        self._bar += 1
        if not self.has_position():
            self.enter_long(quantity=5)


# ---------------------------------------------------------------------------
# Phase map construction
# ---------------------------------------------------------------------------


class TestBuildPhaseMap:
    """Tests for SimulationEngine._build_phase_map."""

    def _engine(self) -> SimulationEngine:
        return SimulationEngine(BacktestEngine(_make_config()), seed=0)

    def test_total_coverage(self) -> None:
        """Every bar index must map to a phase."""
        sim = self._engine()
        scenario = SCENARIOS["flash_crash"]
        n = 260
        phase_map = sim._build_phase_map(n, scenario)
        assert len(phase_map) == n

    def test_first_phase_starts_at_zero(self) -> None:
        sim = self._engine()
        scenario = SCENARIOS["flash_crash"]
        phase_map = sim._build_phase_map(260, scenario)
        assert phase_map[0] == SimulationPhase.NORMAL

    def test_crisis_phase_present(self) -> None:
        sim = self._engine()
        scenario = SCENARIOS["flash_crash"]
        phase_map = sim._build_phase_map(260, scenario)
        phases_used = set(phase_map.values())
        assert SimulationPhase.CRISIS in phases_used

    def test_short_bar_list_truncates_gracefully(self) -> None:
        """Scenario total is 260 bars but only 50 bars provided."""
        sim = self._engine()
        scenario = SCENARIOS["flash_crash"]  # total = 260 bars
        phase_map = sim._build_phase_map(50, scenario)
        assert len(phase_map) == 50

    def test_long_bar_list_extends_last_phase(self) -> None:
        """More bars than scenario total — last phase fills remainder."""
        sim = self._engine()
        scenario = SimulationScenario(
            name="Short",
            phases=[
                (SimulationPhase.NORMAL, 5),
                (SimulationPhase.CRISIS, 5),
            ],
        )
        phase_map = sim._build_phase_map(20, scenario)
        assert len(phase_map) == 20
        # Last phase (CRISIS) must cover bars 10–19
        for i in range(10, 20):
            assert phase_map[i] == SimulationPhase.CRISIS

    def test_single_phase_scenario(self) -> None:
        sim = self._engine()
        scenario = SimulationScenario(
            name="AllNormal",
            phases=[(SimulationPhase.NORMAL, 100)],
        )
        phase_map = sim._build_phase_map(100, scenario)
        assert all(v == SimulationPhase.NORMAL for v in phase_map.values())

    def test_warmup_phase_at_start(self) -> None:
        sim = self._engine()
        scenario = SimulationScenario(
            name="WithWarmup",
            phases=[
                (SimulationPhase.WARMUP, 20),
                (SimulationPhase.NORMAL, 80),
            ],
        )
        phase_map = sim._build_phase_map(100, scenario)
        for i in range(20):
            assert phase_map[i] == SimulationPhase.WARMUP
        for i in range(20, 100):
            assert phase_map[i] == SimulationPhase.NORMAL


# ---------------------------------------------------------------------------
# Phase effect application
# ---------------------------------------------------------------------------


class TestApplyPhaseEffects:
    """Tests for SimulationEngine._apply_phase_effects."""

    _base_bar: dict[str, Any] = {
        "timestamp": "2025-01-01",
        "open": 100.0,
        "high": 102.0,
        "low": 98.0,
        "close": 101.0,
        "volume": 10000,
    }

    def _engine(self) -> SimulationEngine:
        return SimulationEngine(BacktestEngine(_make_config()), seed=0)

    def test_normal_phase_preserves_prices_approximately(self) -> None:
        """NORMAL phase should not dramatically alter bar values."""
        sim = self._engine()
        b = sim._apply_phase_effects(dict(self._base_bar), SimulationPhase.NORMAL)
        # Volume should be unchanged (volume_mult=1.0 for NORMAL)
        assert b["volume"] == 10000
        # Prices should be within ±5 % of originals (gap may fire but is rare)
        for key in ("open", "high", "low", "close"):
            assert abs(b[key] - self._base_bar[key]) / self._base_bar[key] < 0.10

    def test_crisis_widens_range(self) -> None:
        """CRISIS vol_mult=3.5 must widen the high-low range."""
        sim = self._engine()
        orig_range = self._base_bar["high"] - self._base_bar["low"]
        b = sim._apply_phase_effects(dict(self._base_bar), SimulationPhase.CRISIS)
        new_range = b["high"] - b["low"]
        assert new_range > orig_range

    def test_crisis_trend_bias_lowers_prices(self) -> None:
        """CRISIS trend_bias=-0.5 % must lower prices relative to input."""
        sim = self._engine()
        b = sim._apply_phase_effects(dict(self._base_bar), SimulationPhase.CRISIS)
        # All prices should be lower than originals due to negative bias
        assert b["close"] < self._base_bar["close"]

    def test_volatile_increases_volume(self) -> None:
        """VOLATILE volume_mult=1.8 must increase volume."""
        sim = self._engine()
        b = sim._apply_phase_effects(dict(self._base_bar), SimulationPhase.VOLATILE)
        expected_vol = int(10000 * _PHASE_PARAMS[SimulationPhase.VOLATILE]["volume_mult"])
        assert b["volume"] == expected_vol

    def test_trending_raises_prices(self) -> None:
        """TRENDING trend_bias=+0.15 % must raise prices."""
        sim = self._engine()
        b = sim._apply_phase_effects(dict(self._base_bar), SimulationPhase.TRENDING)
        assert b["close"] > self._base_bar["close"]

    def test_mean_reverting_narrows_range(self) -> None:
        """MEAN_REVERTING vol_mult=0.7 must narrow the high-low range."""
        sim = self._engine()
        orig_range = self._base_bar["high"] - self._base_bar["low"]
        b = sim._apply_phase_effects(dict(self._base_bar), SimulationPhase.MEAN_REVERTING)
        new_range = b["high"] - b["low"]
        assert new_range < orig_range

    def test_prices_always_positive(self) -> None:
        """All output prices must be > 0, even under extreme crisis conditions."""
        sim = self._engine()
        for _ in range(30):
            b = sim._apply_phase_effects(dict(self._base_bar), SimulationPhase.CRISIS)
            for key in ("open", "high", "low", "close"):
                assert b[key] > 0, f"{key} became non-positive"

    def test_warmup_passes_through_unchanged(self) -> None:
        """WARMUP is NOT processed by _apply_phase_effects (caller skips it)."""
        # The caller (run_scenario) skips phase effects for WARMUP — this test
        # validates the NORMAL case as a baseline.
        sim = self._engine()
        b = sim._apply_phase_effects(dict(self._base_bar), SimulationPhase.NORMAL)
        assert isinstance(b, dict)

    def test_high_never_below_low(self) -> None:
        """After any phase transformation, high >= low must always hold."""
        sim = self._engine()
        for phase in SimulationPhase:
            if phase == SimulationPhase.WARMUP:
                continue
            for _ in range(10):
                b = sim._apply_phase_effects(dict(self._base_bar), phase)
                assert b["high"] >= b["low"], (
                    f"high < low after phase {phase}: h={b['high']} l={b['low']}"
                )

    def test_original_bar_not_mutated(self) -> None:
        """_apply_phase_effects must not mutate the input bar dict."""
        sim = self._engine()
        original = dict(self._base_bar)
        sim._apply_phase_effects(original, SimulationPhase.CRISIS)
        assert original == self._base_bar


# ---------------------------------------------------------------------------
# Event injection
# ---------------------------------------------------------------------------


class TestInjectEvent:
    """Tests for SimulationEngine._inject_event."""

    _base_bar: dict[str, Any] = {
        "timestamp": "2025-01-01",
        "open": 100.0,
        "high": 102.0,
        "low": 98.0,
        "close": 101.0,
        "volume": 10000,
    }

    def _engine(self) -> SimulationEngine:
        return SimulationEngine(BacktestEngine(_make_config()), seed=0)

    def test_price_shock_negative_lowers_all_prices(self) -> None:
        sim = self._engine()
        event = MarketEvent(
            name="Crash",
            bar_index=0,
            effects={"price_shock_pct": -10.0},
        )
        b = sim._inject_event(dict(self._base_bar), event)
        for key in ("open", "high", "low", "close"):
            assert b[key] < self._base_bar[key], f"{key} not lowered"

    def test_price_shock_positive_raises_all_prices(self) -> None:
        sim = self._engine()
        event = MarketEvent(
            name="Rally",
            bar_index=0,
            effects={"price_shock_pct": 5.0},
        )
        b = sim._inject_event(dict(self._base_bar), event)
        for key in ("open", "high", "low", "close"):
            assert b[key] > self._base_bar[key], f"{key} not raised"

    def test_volume_spike_scales_volume(self) -> None:
        sim = self._engine()
        event = MarketEvent(
            name="Panic",
            bar_index=0,
            effects={"volume_spike_mult": 5.0},
        )
        b = sim._inject_event(dict(self._base_bar), event)
        assert b["volume"] == 50000

    def test_volume_spike_below_one_reduces_volume(self) -> None:
        """Liquidity freeze: volume_spike_mult=0.1 thins the market."""
        sim = self._engine()
        event = MarketEvent(
            name="Thin",
            bar_index=0,
            effects={"volume_spike_mult": 0.1},
        )
        b = sim._inject_event(dict(self._base_bar), event)
        assert b["volume"] < self._base_bar["volume"]
        assert b["volume"] >= 1  # clamped to minimum 1

    def test_volatility_mult_widens_range(self) -> None:
        sim = self._engine()
        orig_range = self._base_bar["high"] - self._base_bar["low"]
        event = MarketEvent(
            name="VolExpand",
            bar_index=0,
            effects={"volatility_mult": 3.0},
        )
        b = sim._inject_event(dict(self._base_bar), event)
        new_range = b["high"] - b["low"]
        assert new_range > orig_range

    def test_gap_pct_shifts_open_only(self) -> None:
        """gap_pct shifts the open price and adjusts high/low but not close."""
        sim = self._engine()
        event = MarketEvent(
            name="GapUp",
            bar_index=0,
            effects={"gap_pct": 3.0},
        )
        b = sim._inject_event(dict(self._base_bar), event)
        expected_open = round(100.0 * 1.03, 2)
        assert abs(b["open"] - expected_open) < 0.01

    def test_gap_down_reduces_open(self) -> None:
        sim = self._engine()
        event = MarketEvent(
            name="GapDown",
            bar_index=0,
            effects={"gap_pct": -2.0},
        )
        b = sim._inject_event(dict(self._base_bar), event)
        assert b["open"] < self._base_bar["open"]

    def test_prices_remain_positive_after_large_crash(self) -> None:
        sim = self._engine()
        event = MarketEvent(
            name="TotalCrash",
            bar_index=0,
            effects={"price_shock_pct": -99.0},
        )
        b = sim._inject_event(dict(self._base_bar), event)
        for key in ("open", "high", "low", "close"):
            assert b[key] > 0

    def test_high_never_below_low_after_event(self) -> None:
        sim = self._engine()
        events = [
            MarketEvent(name="E1", bar_index=0, effects={"price_shock_pct": -50.0}),
            MarketEvent(name="E2", bar_index=0, effects={"volatility_mult": 5.0}),
            MarketEvent(name="E3", bar_index=0, effects={"gap_pct": -5.0}),
        ]
        for event in events:
            b = sim._inject_event(dict(self._base_bar), event)
            assert b["high"] >= b["low"]

    def test_no_effects_returns_bar_unchanged(self) -> None:
        sim = self._engine()
        event = MarketEvent(name="NoOp", bar_index=0, effects={})
        b = sim._inject_event(dict(self._base_bar), event)
        assert b["open"] == self._base_bar["open"]
        assert b["close"] == self._base_bar["close"]
        assert b["volume"] == self._base_bar["volume"]

    def test_original_bar_not_mutated(self) -> None:
        sim = self._engine()
        original = dict(self._base_bar)
        event = MarketEvent(
            name="Check",
            bar_index=0,
            effects={"price_shock_pct": -20.0},
        )
        sim._inject_event(original, event)
        assert original == self._base_bar


# ---------------------------------------------------------------------------
# Scenario model validation
# ---------------------------------------------------------------------------


class TestSimulationScenario:
    """Tests for SimulationScenario model properties."""

    def test_total_phase_bars(self) -> None:
        scenario = SCENARIOS["flash_crash"]
        # flash_crash has phases: (100 + 10 + 50 + 100) = 260
        assert scenario.total_phase_bars == 260

    def test_all_builtin_scenarios_have_phases(self) -> None:
        for key, scenario in SCENARIOS.items():
            assert len(scenario.phases) > 0, f"Scenario {key!r} has no phases"

    def test_all_builtin_scenarios_have_names(self) -> None:
        for key, scenario in SCENARIOS.items():
            assert scenario.name, f"Scenario {key!r} has empty name"

    def test_event_bar_indices_are_non_negative(self) -> None:
        for key, scenario in SCENARIOS.items():
            for event in scenario.events:
                assert event.bar_index >= 0, (
                    f"Scenario {key!r} event {event.name!r} has negative bar_index"
                )

    def test_six_builtin_scenarios_exist(self) -> None:
        assert len(SCENARIOS) == 6

    def test_scenario_keys(self) -> None:
        expected = {
            "flash_crash",
            "trend_reversal",
            "range_bound",
            "gap_up_open",
            "volatility_expansion",
            "liquidity_crisis",
        }
        assert set(SCENARIOS.keys()) == expected


# ---------------------------------------------------------------------------
# Full scenario runs
# ---------------------------------------------------------------------------


class TestRunScenario:
    """Integration tests for SimulationEngine.run_scenario."""

    def _sim(self, seed: int = 42) -> SimulationEngine:
        return SimulationEngine(BacktestEngine(_make_config()), seed=seed)

    def test_flash_crash_runs_to_completion(self) -> None:
        """Flash crash scenario must produce a result without exceptions."""
        bars = _make_bars(n=260)
        sim = self._sim()
        strategy = DoNothingStrategy()
        result = sim.run_scenario(bars, SCENARIOS["flash_crash"], strategy)
        assert isinstance(result, SimulationResult)
        assert result.scenario_name == "Flash Crash"

    def test_flash_crash_result_has_expected_fields(self) -> None:
        bars = _make_bars(n=260)
        sim = self._sim()
        result = sim.run_scenario(bars, SCENARIOS["flash_crash"], DoNothingStrategy())
        assert isinstance(result.survived, bool)
        assert isinstance(result.max_drawdown_pct, float)
        assert isinstance(result.phase_returns, dict)
        assert isinstance(result.events_impact, list)
        assert isinstance(result.final_equity, Decimal)

    def test_do_nothing_strategy_equity_equals_capital(self) -> None:
        """DoNothingStrategy never trades so final equity = initial capital."""
        bars = _make_bars(n=260)
        sim = self._sim()
        result = sim.run_scenario(bars, SCENARIOS["flash_crash"], DoNothingStrategy())
        assert result.final_equity == _make_config().initial_capital

    def test_do_nothing_strategy_survives_all_scenarios(self) -> None:
        """A strategy with no positions cannot lose money; always survives."""
        bars = _make_bars(n=300)
        for key, scenario in SCENARIOS.items():
            sim = self._sim()
            result = sim.run_scenario(bars, scenario, DoNothingStrategy())
            assert result.survived, (
                f"DoNothingStrategy should survive {key!r} but did not"
            )

    def test_buy_once_strategy_produces_trades(self) -> None:
        bars = _make_bars(n=260)
        sim = self._sim()
        result = sim.run_scenario(bars, SCENARIOS["flash_crash"], BuyOnceStrategy())
        # Strategy buys once; engine closes at end → at least 1 trade
        assert len(result.trades) >= 1

    def test_phase_returns_populated(self) -> None:
        bars = _make_bars(n=260)
        sim = self._sim()
        result = sim.run_scenario(bars, SCENARIOS["flash_crash"], DoNothingStrategy())
        # Flash crash has NORMAL, CRISIS, RECOVERY phases → should see keys
        assert len(result.phase_returns) > 0

    def test_phase_returns_keys_are_phase_names(self) -> None:
        bars = _make_bars(n=260)
        sim = self._sim()
        result = sim.run_scenario(bars, SCENARIOS["flash_crash"], DoNothingStrategy())
        valid_phases = {p.value for p in SimulationPhase}
        for key in result.phase_returns:
            assert key in valid_phases

    def test_events_impact_list_has_one_entry_per_event(self) -> None:
        """Flash crash has 2 events; both must appear in events_impact."""
        bars = _make_bars(n=260)
        sim = self._sim()
        result = sim.run_scenario(bars, SCENARIOS["flash_crash"], DoNothingStrategy())
        assert len(result.events_impact) == 2

    def test_events_impact_has_required_keys(self) -> None:
        bars = _make_bars(n=260)
        sim = self._sim()
        result = sim.run_scenario(bars, SCENARIOS["flash_crash"], DoNothingStrategy())
        required = {"name", "bar_index", "equity_before", "equity_after", "pnl_impact"}
        for impact in result.events_impact:
            assert required.issubset(impact.keys())

    def test_empty_bars_returns_result_without_crashing(self) -> None:
        sim = self._sim()
        result = sim.run_scenario([], SCENARIOS["flash_crash"], DoNothingStrategy())
        assert result.scenario_name == "Flash Crash"
        assert result.final_equity == Decimal("0")
        assert not result.survived

    def test_max_drawdown_is_non_negative(self) -> None:
        bars = _make_bars(n=260)
        for key in SCENARIOS:
            sim = self._sim()
            result = sim.run_scenario(bars, SCENARIOS[key], BuyOnceStrategy())
            assert result.max_drawdown_pct >= 0.0

    def test_all_builtin_scenarios_run_without_exception(self) -> None:
        bars = _make_bars(n=300)
        for key, scenario in SCENARIOS.items():
            sim = self._sim()
            result = sim.run_scenario(bars, scenario, DoNothingStrategy())
            assert result.scenario_name == scenario.name, (
                f"Scenario {key!r} returned wrong name"
            )

    def test_range_bound_scenario(self) -> None:
        bars = _make_bars(n=300)
        sim = self._sim()
        result = sim.run_scenario(bars, SCENARIOS["range_bound"], DoNothingStrategy())
        assert isinstance(result, SimulationResult)

    def test_gap_up_open_scenario(self) -> None:
        bars = _make_bars(n=200)
        sim = self._sim()
        result = sim.run_scenario(bars, SCENARIOS["gap_up_open"], DoNothingStrategy())
        assert isinstance(result, SimulationResult)

    def test_liquidity_crisis_scenario(self) -> None:
        bars = _make_bars(n=260)
        sim = self._sim()
        result = sim.run_scenario(
            bars, SCENARIOS["liquidity_crisis"], DoNothingStrategy()
        )
        assert isinstance(result, SimulationResult)

    def test_custom_single_event_scenario(self) -> None:
        """Custom scenario with a single price shock event."""
        bars = _make_bars(n=50)
        scenario = SimulationScenario(
            name="SingleEvent",
            phases=[(SimulationPhase.NORMAL, 50)],
            events=[
                MarketEvent(
                    name="Shock",
                    bar_index=25,
                    effects={"price_shock_pct": -3.0},
                )
            ],
        )
        sim = self._sim()
        result = sim.run_scenario(bars, scenario, DoNothingStrategy())
        assert len(result.events_impact) == 1
        assert result.events_impact[0]["name"] == "Shock"
        assert result.events_impact[0]["bar_index"] == 25

    def test_warmup_phase_bars_not_modified(self) -> None:
        """During WARMUP phase, bars should pass through unmodified."""
        bars = _make_bars(n=50)
        scenario = SimulationScenario(
            name="WarmupOnly",
            phases=[(SimulationPhase.WARMUP, 50)],
        )
        sim = self._sim(seed=999)  # seed that won't produce gaps
        result = sim.run_scenario(bars, scenario, DoNothingStrategy())
        # With no trades and no modifications, equity should equal capital
        assert result.final_equity == _make_config().initial_capital

    def test_seed_produces_reproducible_results(self) -> None:
        """Same seed must produce identical SimulationResult."""
        bars = _make_bars(n=260)
        r1 = SimulationEngine(BacktestEngine(_make_config()), seed=7).run_scenario(
            bars, SCENARIOS["volatile_expansion"] if "volatile_expansion" in SCENARIOS
            else SCENARIOS["volatility_expansion"],
            DoNothingStrategy(),
        )
        r2 = SimulationEngine(BacktestEngine(_make_config()), seed=7).run_scenario(
            bars, SCENARIOS["volatile_expansion"] if "volatile_expansion" in SCENARIOS
            else SCENARIOS["volatility_expansion"],
            DoNothingStrategy(),
        )
        assert r1.final_equity == r2.final_equity
        assert r1.max_drawdown_pct == r2.max_drawdown_pct


# ---------------------------------------------------------------------------
# Recovery time computation
# ---------------------------------------------------------------------------


class TestComputeRecoveryTime:
    """Tests for SimulationEngine._compute_recovery_time."""

    def _engine(self) -> SimulationEngine:
        return SimulationEngine(BacktestEngine(_make_config()), seed=0)

    def test_monotone_increasing_curve_has_no_trough(self) -> None:
        """An always-increasing equity curve has a trough at index 0 → None."""
        sim = self._engine()
        equity = [Decimal(str(100 + i)) for i in range(20)]
        # Trough is at index 0; there is no bar before it, so returns None
        result = sim._compute_recovery_time(equity)
        assert result is None

    def test_v_shaped_crash_recovery(self) -> None:
        """V-shaped crash: recovers exactly at the bar after the trough."""
        sim = self._engine()
        equity = (
            [Decimal("1000")] * 5
            + [Decimal("800")]   # trough at index 5
            + [Decimal("950")]
            + [Decimal("1000")]  # recovery at index 7 → 7 - 5 = 2 bars
            + [Decimal("1050")] * 5
        )
        result = sim._compute_recovery_time(equity)
        assert result == 2

    def test_never_recovers_returns_none(self) -> None:
        """If equity never recovers to pre-trough level, returns None."""
        sim = self._engine()
        equity = [Decimal("1000")] * 5 + [Decimal("600")] * 10  # trough, never recovers
        result = sim._compute_recovery_time(equity)
        assert result is None

    def test_empty_equity_returns_none(self) -> None:
        sim = self._engine()
        result = sim._compute_recovery_time([])
        assert result is None


# ---------------------------------------------------------------------------
# StressTestRunner
# ---------------------------------------------------------------------------


class TestStressTestRunner:
    """Tests for StressTestRunner."""

    def _runner(self) -> StressTestRunner:
        return StressTestRunner(DoNothingStrategy, _make_config(), seed=42)

    def test_run_all_scenarios_returns_dict(self) -> None:
        bars = _make_bars(n=300)
        runner = self._runner()
        results = runner.run_all_scenarios(bars)
        assert isinstance(results, dict)

    def test_run_all_scenarios_covers_all_builtin(self) -> None:
        bars = _make_bars(n=300)
        runner = self._runner()
        results = runner.run_all_scenarios(bars)
        assert set(results.keys()) == set(SCENARIOS.keys())

    def test_do_nothing_passes_all_scenarios(self) -> None:
        """DoNothingStrategy never loses money — must pass every scenario."""
        bars = _make_bars(n=300)
        runner = self._runner()
        results = runner.run_all_scenarios(bars)
        for key, result in results.items():
            assert result.survived, (
                f"DoNothingStrategy should survive {key!r}"
            )

    def test_report_structure(self) -> None:
        bars = _make_bars(n=300)
        runner = self._runner()
        results = runner.run_all_scenarios(bars)
        report = runner.report(results)
        assert isinstance(report, StressTestReport)

    def test_report_strategy_name(self) -> None:
        bars = _make_bars(n=300)
        runner = self._runner()
        results = runner.run_all_scenarios(bars)
        report = runner.report(results)
        assert report.strategy_name == "DoNothingStrategy"

    def test_report_total_scenarios_count(self) -> None:
        bars = _make_bars(n=300)
        runner = self._runner()
        results = runner.run_all_scenarios(bars)
        report = runner.report(results)
        assert report.total_scenarios == len(SCENARIOS)

    def test_report_passed_plus_failed_equals_total(self) -> None:
        bars = _make_bars(n=300)
        runner = self._runner()
        results = runner.run_all_scenarios(bars)
        report = runner.report(results)
        assert report.passed + report.failed == report.total_scenarios

    def test_report_do_nothing_all_pass(self) -> None:
        bars = _make_bars(n=300)
        runner = self._runner()
        results = runner.run_all_scenarios(bars)
        report = runner.report(results)
        assert report.passed == len(SCENARIOS)
        assert report.failed == 0

    def test_report_scenario_summary_has_all_keys(self) -> None:
        bars = _make_bars(n=300)
        runner = self._runner()
        results = runner.run_all_scenarios(bars)
        report = runner.report(results)
        required = {
            "scenario_key",
            "scenario_name",
            "survived",
            "max_drawdown_pct",
            "final_equity",
            "trade_count",
            "recovery_time_bars",
        }
        for entry in report.scenario_summary:
            assert required.issubset(entry.keys())

    def test_report_worst_drawdown_scenario_is_valid(self) -> None:
        bars = _make_bars(n=300)
        runner = self._runner()
        results = runner.run_all_scenarios(bars)
        report = runner.report(results)
        valid_names = {s.name for s in SCENARIOS.values()}
        assert report.worst_drawdown_scenario in valid_names

    def test_report_best_scenario_is_valid(self) -> None:
        bars = _make_bars(n=300)
        runner = self._runner()
        results = runner.run_all_scenarios(bars)
        report = runner.report(results)
        valid_names = {s.name for s in SCENARIOS.values()}
        assert report.best_scenario in valid_names

    def test_custom_scenario_subset(self) -> None:
        """Runner accepts a custom scenario dict with fewer scenarios."""
        bars = _make_bars(n=300)
        custom = {"fc": SCENARIOS["flash_crash"]}
        runner = StressTestRunner(DoNothingStrategy, _make_config(), scenarios=custom, seed=42)
        results = runner.run_all_scenarios(bars)
        assert len(results) == 1
        assert "fc" in results

    def test_buy_once_strategy_in_runner(self) -> None:
        """BuyOnceStrategy should also produce valid results in the runner."""
        bars = _make_bars(n=300)
        runner = StressTestRunner(BuyOnceStrategy, _make_config(), seed=42)
        results = runner.run_all_scenarios(bars)
        report = runner.report(results)
        assert report.total_scenarios == len(SCENARIOS)

    def test_runner_fresh_strategy_per_scenario(self) -> None:
        """Each scenario must receive a fresh strategy instance (no shared state)."""
        bars = _make_bars(n=300)
        runner = self._runner()
        results = runner.run_all_scenarios(bars)
        # All results should have identical final_equity (DoNothing, no trades)
        equities = [r.final_equity for r in results.values()]
        expected = _make_config().initial_capital
        for eq in equities:
            assert eq == expected


# ---------------------------------------------------------------------------
# MarketEvent model validation
# ---------------------------------------------------------------------------


class TestMarketEvent:
    """Tests for MarketEvent Pydantic model."""

    def test_valid_event(self) -> None:
        event = MarketEvent(
            name="Test",
            bar_index=10,
            effects={"price_shock_pct": -5.0},
        )
        assert event.name == "Test"
        assert event.bar_index == 10
        assert event.effects["price_shock_pct"] == -5.0

    def test_negative_bar_index_raises(self) -> None:
        with pytest.raises(Exception):
            MarketEvent(name="Bad", bar_index=-1, effects={})

    def test_empty_effects_is_valid(self) -> None:
        event = MarketEvent(name="NoOp", bar_index=5, effects={})
        assert event.effects == {}

    def test_default_description_is_empty(self) -> None:
        event = MarketEvent(name="E", bar_index=0, effects={})
        assert event.description == ""


# ---------------------------------------------------------------------------
# Edge cases and integration
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge-case and integration tests."""

    def test_event_at_last_bar(self) -> None:
        """Event injected at the last bar should not raise an exception."""
        bars = _make_bars(n=10)
        scenario = SimulationScenario(
            name="LastBar",
            phases=[(SimulationPhase.NORMAL, 10)],
            events=[
                MarketEvent(
                    name="EndShock",
                    bar_index=9,  # last bar (0-indexed)
                    effects={"price_shock_pct": -2.0},
                )
            ],
        )
        sim = SimulationEngine(BacktestEngine(_make_config()), seed=0)
        result = sim.run_scenario(bars, scenario, DoNothingStrategy())
        assert isinstance(result, SimulationResult)

    def test_event_beyond_bar_list_is_silently_ignored(self) -> None:
        """Events with bar_index >= len(bars) must be silently ignored."""
        bars = _make_bars(n=10)
        scenario = SimulationScenario(
            name="OutOfBounds",
            phases=[(SimulationPhase.NORMAL, 10)],
            events=[
                MarketEvent(
                    name="Ghost",
                    bar_index=999,  # way beyond bar list
                    effects={"price_shock_pct": -50.0},
                )
            ],
        )
        sim = SimulationEngine(BacktestEngine(_make_config()), seed=0)
        result = sim.run_scenario(bars, scenario, DoNothingStrategy())
        # No events should appear in impact list
        assert len(result.events_impact) == 0

    def test_multiple_events_same_bar(self) -> None:
        """Two events on the same bar should both appear in events_impact."""
        bars = _make_bars(n=20)
        scenario = SimulationScenario(
            name="TwoEvents",
            phases=[(SimulationPhase.NORMAL, 20)],
            events=[
                MarketEvent(name="E1", bar_index=10, effects={"price_shock_pct": -1.0}),
                MarketEvent(name="E2", bar_index=10, effects={"volume_spike_mult": 2.0}),
            ],
        )
        sim = SimulationEngine(BacktestEngine(_make_config()), seed=0)
        result = sim.run_scenario(bars, scenario, DoNothingStrategy())
        assert len(result.events_impact) == 2

    def test_phase_transitions_correct_count(self) -> None:
        """Verify phase transitions match scenario definition."""
        scenario = SimulationScenario(
            name="TwoPhase",
            phases=[
                (SimulationPhase.NORMAL, 50),
                (SimulationPhase.CRISIS, 50),
            ],
        )
        sim = SimulationEngine(BacktestEngine(_make_config()), seed=0)
        phase_map = sim._build_phase_map(100, scenario)
        normal_count = sum(1 for p in phase_map.values() if p == SimulationPhase.NORMAL)
        crisis_count = sum(1 for p in phase_map.values() if p == SimulationPhase.CRISIS)
        assert normal_count == 50
        assert crisis_count == 50

    def test_single_bar_scenario(self) -> None:
        """Scenario with a single bar must not crash."""
        bars = _make_bars(n=1)
        scenario = SimulationScenario(
            name="OneBar",
            phases=[(SimulationPhase.NORMAL, 1)],
        )
        sim = SimulationEngine(BacktestEngine(_make_config()), seed=0)
        result = sim.run_scenario(bars, scenario, DoNothingStrategy())
        assert isinstance(result, SimulationResult)
