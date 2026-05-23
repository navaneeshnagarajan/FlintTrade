"""Multi-phase simulation and event injection system for the FlintTrade backtest engine.

Wraps ``BacktestEngine`` to add:

- Phase-based simulation: each phase modifies bar data to model different market
  regimes (WARMUP, NORMAL, VOLATILE, TRENDING, MEAN_REVERTING, CRISIS, RECOVERY).
- Event injection: discrete shocks (flash crashes, gap opens, liquidity crises)
  applied to specific bars by index.
- Pre-built scenario library: six canonical stress scenarios.
- ``StressTestRunner``: drives a strategy through every built-in scenario and
  produces a ranked ``StressTestReport``.

Patterns absorbed from Stockagent (navaneeshnagarajan/FlintTrade/.local/reference/
repos/external-all/Stockagent/main.py):
- Phase separation (Initial → Trading → Post-Trading → Special Events)
- Discrete special-event injection keyed to bar/date index
- Per-phase state tracking and result aggregation

Design constraints:
- Never modifies ``BacktestEngine`` — wraps it.
- All monetary values use ``Decimal``.
- Pydantic v2 models for all data transfer objects.
- Python 3.12+, PEP 8, type hints, Google-style docstrings.

Usage::

    from flinttrade_backtest.engine import BacktestEngine, EngineConfig
    from flinttrade_backtest.simulation import (
        SimulationEngine, StressTestRunner, SCENARIOS,
    )
    from my_strategy import MyStrategy

    config = EngineConfig(symbol="NIFTY", initial_capital=Decimal("1000000"))
    strategy = MyStrategy()
    engine = SimulationEngine(BacktestEngine(config))

    result = engine.run_scenario(bars, SCENARIOS["flash_crash"], strategy)
    print(result.survived, result.max_drawdown_pct)

    runner = StressTestRunner(MyStrategy, config)
    report = runner.report(runner.run_all_scenarios(bars))
"""

from __future__ import annotations

import copy
import logging
import random
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("flinttrade.backtest.simulation")

# ---------------------------------------------------------------------------
# Re-export engine types used in public signatures
# ---------------------------------------------------------------------------

try:
    from .engine import (  # type: ignore[import]
        BacktestEngine,
        EngineConfig,
        EngineResult,
    )
    from .base_strategy import (  # type: ignore[import]
        BaseBacktestStrategy,
    )
except ImportError:
    # Allow direct execution / tests that add the src dir to sys.path
    from engine import BacktestEngine, EngineConfig, EngineResult  # type: ignore[import]
    from base_strategy import BaseBacktestStrategy  # type: ignore[import]


# ---------------------------------------------------------------------------
# Phase enumeration
# ---------------------------------------------------------------------------


class SimulationPhase(StrEnum):
    """Market regime phases used during a simulation scenario.

    Attributes:
        WARMUP: Initial data loading period; no trading signals generated.
            Bar data passes through unmodified. Strategy builds its indicator
            lookback buffers here.
        NORMAL: Standard market conditions. Moderate volatility and volume.
        VOLATILE: Elevated volatility (±2× ATR) and increased volume. Models
            earnings seasons, macro data releases, or options expiry.
        TRENDING: Persistent directional bias applied to each bar's close.
            High volume, low intra-bar noise relative to trend magnitude.
        MEAN_REVERTING: Range-bound market. Each bar's deviation from a
            rolling mid-price is dampened back towards the mean.
        CRISIS: Severe stress. Amplified downward volatility, volume spike,
            and gap-down risk. Models market crashes or circuit breakers.
        RECOVERY: Post-crisis bounce. Gradual upward drift with above-average
            volume as buyers return.
    """

    WARMUP = "warmup"
    NORMAL = "normal"
    VOLATILE = "volatile"
    TRENDING = "trending"
    MEAN_REVERTING = "mean_reverting"
    CRISIS = "crisis"
    RECOVERY = "recovery"


# ---------------------------------------------------------------------------
# Phase effect parameters (tuning table)
# ---------------------------------------------------------------------------

# Each phase defines multipliers applied in _apply_phase_effects.
# Keys:
#   vol_mult      — multiplier on the bar's high-low range (intra-bar volatility)
#   volume_mult   — multiplier on the bar's volume
#   trend_bias    — additive % shift applied to every price in the bar
#   gap_prob      — probability of a gap open (applied to bar open only)
#   gap_range     — (min, max) % gap, signed negative = down gap
_PHASE_PARAMS: dict[SimulationPhase, dict[str, Any]] = {
    SimulationPhase.WARMUP: {
        "vol_mult": 1.0,
        "volume_mult": 1.0,
        "trend_bias": 0.0,
        "gap_prob": 0.0,
        "gap_range": (0.0, 0.0),
    },
    SimulationPhase.NORMAL: {
        "vol_mult": 1.0,
        "volume_mult": 1.0,
        "trend_bias": 0.0,
        "gap_prob": 0.02,
        "gap_range": (-0.3, 0.3),
    },
    SimulationPhase.VOLATILE: {
        "vol_mult": 2.2,
        "volume_mult": 1.8,
        "trend_bias": 0.0,
        "gap_prob": 0.08,
        "gap_range": (-1.0, 1.0),
    },
    SimulationPhase.TRENDING: {
        "vol_mult": 1.1,
        "volume_mult": 1.4,
        "trend_bias": 0.15,       # +0.15 % per bar (uptrend)
        "gap_prob": 0.03,
        "gap_range": (0.0, 0.5),  # gap in trend direction
    },
    SimulationPhase.MEAN_REVERTING: {
        "vol_mult": 0.7,
        "volume_mult": 0.9,
        "trend_bias": 0.0,
        "gap_prob": 0.01,
        "gap_range": (-0.2, 0.2),
    },
    SimulationPhase.CRISIS: {
        "vol_mult": 3.5,
        "volume_mult": 4.0,
        "trend_bias": -0.5,       # −0.5 % per bar (relentless selling)
        "gap_prob": 0.30,
        "gap_range": (-3.0, -0.5),  # gap downs only
    },
    SimulationPhase.RECOVERY: {
        "vol_mult": 1.6,
        "volume_mult": 2.2,
        "trend_bias": 0.25,       # steady but gentle recovery
        "gap_prob": 0.05,
        "gap_range": (0.0, 1.0),
    },
}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class MarketEvent(BaseModel):
    """A discrete market event injected at a specific bar.

    Attributes:
        name: Short identifier used in reports (e.g. ``"Flash Crash"``).
        description: Human-readable description of the event.
        bar_index: Zero-based bar index at which the event fires.
        effects: Dict of effect keys and their magnitudes:

            - ``price_shock_pct`` (float): Immediate % change applied to all
              OHLCV prices. Negative = crash, positive = gap-up.
            - ``volume_spike_mult`` (float): Multiply bar volume by this factor.
            - ``volatility_mult`` (float): Widen the high-low range by this
              factor (centred on bar mid-point).
            - ``gap_pct`` (float): Shift the bar's *open* price only (simulates
              an overnight gap). Applied before the intra-bar range.
    """

    name: str
    description: str = ""
    bar_index: int = Field(ge=0)
    effects: dict[str, float] = Field(default_factory=dict)


class SimulationScenario(BaseModel):
    """A complete simulation scenario combining phase transitions and events.

    Attributes:
        name: Scenario identifier.
        description: Plain-English description.
        phases: Ordered list of ``(phase, duration_in_bars)`` tuples. The
            simulation runs each phase for the specified number of bars
            before transitioning to the next. If the input bar list is
            shorter than the total duration, phases are truncated
            proportionally. If longer, the last phase is extended.
        events: List of ``MarketEvent`` objects ordered by ``bar_index``.
            Multiple events can share the same ``bar_index``; they are applied
            in list order.
    """

    name: str
    description: str = ""
    phases: list[tuple[SimulationPhase, int]]
    events: list[MarketEvent] = Field(default_factory=list)

    @property
    def total_phase_bars(self) -> int:
        """Sum of all phase durations."""
        return sum(d for _, d in self.phases)


class SimulationResult(BaseModel):
    """Output from a single scenario run.

    Attributes:
        scenario_name: Name of the scenario that produced this result.
        survived: ``True`` if final equity is > 0 (strategy avoided ruin).
        max_drawdown_pct: Peak-to-trough drawdown percentage (0–100).
        recovery_time_bars: Number of bars from the lowest equity trough to
            full drawdown recovery, or ``None`` if not recovered.
        phase_returns: Mapping of phase name → total return percentage for
            bars processed under that phase.
        events_impact: Per-event record with keys:
            ``name``, ``bar_index``, ``equity_before``, ``equity_after``,
            ``pnl_impact`` (Decimal as string).
        final_equity: Terminal portfolio equity.
        trades: All ``EngineTrade`` objects from the underlying engine run.
        engine_result: The raw ``EngineResult`` for detailed analysis.
    """

    model_config = {"arbitrary_types_allowed": True}

    scenario_name: str
    survived: bool
    max_drawdown_pct: float
    recovery_time_bars: int | None
    phase_returns: dict[str, float]
    events_impact: list[dict[str, Any]]
    final_equity: Decimal
    trades: list[Any]
    engine_result: Any = None  # EngineResult — not serialised by default


class StressTestReport(BaseModel):
    """Summary of a full stress test run across all scenarios.

    Attributes:
        strategy_name: Name of the strategy under test.
        total_scenarios: Number of scenarios executed.
        passed: Number of scenarios where ``survived=True``.
        failed: Number of scenarios where ``survived=False``.
        scenario_summary: Per-scenario compact stats (name, survived,
            max_drawdown_pct, final_equity, trade_count).
        worst_drawdown_scenario: Name of the scenario with the highest
            ``max_drawdown_pct``.
        best_scenario: Name of the scenario with the highest ``final_equity``.
    """

    strategy_name: str
    total_scenarios: int
    passed: int
    failed: int
    scenario_summary: list[dict[str, Any]]
    worst_drawdown_scenario: str
    best_scenario: str


# ---------------------------------------------------------------------------
# Pre-built scenarios
# ---------------------------------------------------------------------------


SCENARIOS: dict[str, SimulationScenario] = {
    "flash_crash": SimulationScenario(
        name="Flash Crash",
        description=(
            "A sudden 5 % price collapse triggered by algorithmic selling, "
            "followed by a V-shaped recovery as buyers step in."
        ),
        phases=[
            (SimulationPhase.NORMAL, 100),
            (SimulationPhase.CRISIS, 10),
            (SimulationPhase.RECOVERY, 50),
            (SimulationPhase.NORMAL, 100),
        ],
        events=[
            MarketEvent(
                name="Flash Crash",
                description="Algorithmic cascade sell-off — 5 % instantaneous drop.",
                bar_index=100,
                effects={"price_shock_pct": -5.0, "volume_spike_mult": 5.0},
            ),
            MarketEvent(
                name="Circuit Breaker Lift",
                description="Exchange lifts circuit breaker; buying resumes.",
                bar_index=110,
                effects={"price_shock_pct": 2.5, "volume_spike_mult": 3.0},
            ),
        ],
    ),
    "trend_reversal": SimulationScenario(
        name="Trend Reversal",
        description=(
            "A strong uptrend exhausts itself and transitions into a volatile "
            "decline before stabilising in a range-bound regime."
        ),
        phases=[
            (SimulationPhase.TRENDING, 80),
            (SimulationPhase.VOLATILE, 30),
            (SimulationPhase.CRISIS, 20),
            (SimulationPhase.MEAN_REVERTING, 70),
        ],
        events=[
            MarketEvent(
                name="Bull Trap",
                description="False breakout to new highs before sharp reversal.",
                bar_index=78,
                effects={"price_shock_pct": 1.5, "volume_spike_mult": 2.0},
            ),
            MarketEvent(
                name="Reversal Signal",
                description="Heavy distribution; price breaks key support.",
                bar_index=85,
                effects={"price_shock_pct": -3.0, "volume_spike_mult": 3.5},
            ),
        ],
    ),
    "range_bound": SimulationScenario(
        name="Range Bound",
        description=(
            "A prolonged consolidation period with repeated false breakouts, "
            "punishing momentum strategies."
        ),
        phases=[
            (SimulationPhase.NORMAL, 30),
            (SimulationPhase.MEAN_REVERTING, 200),
            (SimulationPhase.NORMAL, 30),
        ],
        events=[
            MarketEvent(
                name="False Breakout Up",
                description="Price spikes above range high then reverses.",
                bar_index=80,
                effects={"price_shock_pct": 1.8, "volatility_mult": 2.0},
            ),
            MarketEvent(
                name="False Breakdown",
                description="Price dips below range low then snaps back.",
                bar_index=160,
                effects={"price_shock_pct": -1.8, "volatility_mult": 2.0},
            ),
        ],
    ),
    "gap_up_open": SimulationScenario(
        name="Gap Up Open",
        description=(
            "Overnight positive catalyst (earnings beat / macro surprise) "
            "creates a 3 % opening gap, followed by volatile price discovery."
        ),
        phases=[
            (SimulationPhase.NORMAL, 50),
            (SimulationPhase.VOLATILE, 40),
            (SimulationPhase.TRENDING, 60),
            (SimulationPhase.NORMAL, 50),
        ],
        events=[
            MarketEvent(
                name="Gap Up Open",
                description="Positive overnight catalyst; 3 % opening gap.",
                bar_index=50,
                effects={"gap_pct": 3.0, "volume_spike_mult": 2.5},
            ),
        ],
    ),
    "volatility_expansion": SimulationScenario(
        name="Volatility Expansion",
        description=(
            "Gradual compression in a tight range followed by an explosive "
            "volatility expansion — models squeeze breakouts."
        ),
        phases=[
            (SimulationPhase.MEAN_REVERTING, 60),
            (SimulationPhase.VOLATILE, 80),
            (SimulationPhase.TRENDING, 60),
        ],
        events=[
            MarketEvent(
                name="Volatility Squeeze Break",
                description="ATR doubles in a single bar; breakout confirmed.",
                bar_index=60,
                effects={"volatility_mult": 4.0, "volume_spike_mult": 3.0},
            ),
        ],
    ),
    "liquidity_crisis": SimulationScenario(
        name="Liquidity Crisis",
        description=(
            "A systemic liquidity freeze: wide bid-ask spreads modelled as "
            "extreme slippage, price dislocations, and near-zero volume windows."
        ),
        phases=[
            (SimulationPhase.NORMAL, 60),
            (SimulationPhase.CRISIS, 40),
            (SimulationPhase.VOLATILE, 40),
            (SimulationPhase.RECOVERY, 60),
        ],
        events=[
            MarketEvent(
                name="Liquidity Freeze",
                description="Market makers step away; spreads blow out.",
                bar_index=60,
                effects={
                    "price_shock_pct": -4.0,
                    "volume_spike_mult": 0.1,   # near-zero volume
                    "volatility_mult": 5.0,
                },
            ),
            MarketEvent(
                name="Central Bank Intervention",
                description="Emergency liquidity injection stabilises the market.",
                bar_index=100,
                effects={"price_shock_pct": 3.0, "volume_spike_mult": 4.0},
            ),
        ],
    ),
}


# ---------------------------------------------------------------------------
# SimulationEngine
# ---------------------------------------------------------------------------


class SimulationEngine:
    """Wraps a ``BacktestEngine`` with phase-based simulation and event injection.

    The engine does **not** own the underlying ``BacktestEngine`` — it receives
    a configured instance and resets it between runs by creating a fresh engine
    from the same ``EngineConfig``.

    Args:
        base_engine: A configured ``BacktestEngine`` whose ``EngineConfig`` is
            used as the template for each scenario run. The engine itself is
            **not** mutated; a fresh copy is instantiated per run.
        seed: Optional random seed for reproducible phase noise and gap events.
            Pass ``None`` (default) for non-deterministic runs.
    """

    def __init__(self, base_engine: BacktestEngine, seed: int | None = None) -> None:
        self._config: EngineConfig = base_engine.config
        self._seed = seed
        self._rng = random.Random(seed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_scenario(
        self,
        bars: list[dict[str, Any]],
        scenario: SimulationScenario,
        strategy: BaseBacktestStrategy,
    ) -> SimulationResult:
        """Run a full scenario against the provided bars.

        The method:

        1. Builds a per-bar phase map (which phase is active at each bar index).
        2. Applies phase effects to each bar (volatility amplification, trend
           bias, volume scaling, gap probability).
        3. Injects events at their specified ``bar_index`` values.
        4. Feeds the transformed bars to a fresh ``BacktestEngine`` run.
        5. Aggregates the result into a ``SimulationResult``.

        Args:
            bars: Raw OHLCV bars (list of dicts). Not mutated.
            scenario: The scenario to simulate.
            strategy: Strategy instance. A fresh strategy of the same type
                      is **not** created; the caller must pass a clean instance.

        Returns:
            ``SimulationResult`` with all metrics.
        """
        if not bars:
            return SimulationResult(
                scenario_name=scenario.name,
                survived=False,
                max_drawdown_pct=0.0,
                recovery_time_bars=None,
                phase_returns={},
                events_impact=[],
                final_equity=Decimal("0"),
                trades=[],
            )

        self._rng = random.Random(self._seed)  # reset RNG for reproducibility

        # Build phase map: bar_index → SimulationPhase
        phase_map = self._build_phase_map(len(bars), scenario)

        # Build event map: bar_index → list[MarketEvent]
        event_map: dict[int, list[MarketEvent]] = {}
        for event in scenario.events:
            if 0 <= event.bar_index < len(bars):
                event_map.setdefault(event.bar_index, []).append(event)

        # Transform bars
        transformed_bars: list[dict[str, Any]] = []

        for i, bar in enumerate(bars):
            b = copy.copy(bar)

            # Phase effects first
            phase = phase_map.get(i, SimulationPhase.NORMAL)
            if phase != SimulationPhase.WARMUP:
                b = self._apply_phase_effects(b, phase)

            # Event injection on top of phase-modified bar
            if i in event_map:
                for event in event_map[i]:
                    b = self._inject_event(b, event)

            transformed_bars.append(b)

        # Instantiate a fresh engine from the same config
        engine = BacktestEngine(self._config)
        engine.set_strategy(strategy)

        # Snapshot equity just before event bars (approximation using original
        # bar data — we capture actual equity from the equity curve post-run)
        engine_result: EngineResult = engine.run(transformed_bars)

        # Build equity curve lookup by bar index
        equity_by_bar: list[Decimal] = [
            pt.equity for pt in engine_result.equity_curve
        ]

        # Compute per-phase returns
        phase_returns = self._compute_phase_returns(equity_by_bar, phase_map)

        # Compute events impact
        events_impact = self._compute_events_impact(
            equity_by_bar, event_map
        )

        # Max drawdown from engine equity curve
        max_dd = float(
            max(
                (pt.drawdown_pct for pt in engine_result.equity_curve),
                default=Decimal("0"),
            )
        )

        # Recovery time: bars from trough to return above trough-preceding-peak
        recovery_bars = self._compute_recovery_time(equity_by_bar)

        final_equity = engine_result.final_equity
        survived = final_equity > Decimal("0")

        logger.info(
            "SimulationEngine: scenario=%r bars=%d survived=%s max_dd=%.2f%%"
            " final_equity=%s trades=%d",
            scenario.name,
            len(bars),
            survived,
            max_dd,
            final_equity,
            len(engine_result.trades),
        )

        return SimulationResult(
            scenario_name=scenario.name,
            survived=survived,
            max_drawdown_pct=max_dd,
            recovery_time_bars=recovery_bars,
            phase_returns=phase_returns,
            events_impact=events_impact,
            final_equity=final_equity,
            trades=list(engine_result.trades),
            engine_result=engine_result,
        )

    # ------------------------------------------------------------------
    # Phase and event helpers
    # ------------------------------------------------------------------

    def _build_phase_map(
        self,
        n_bars: int,
        scenario: SimulationScenario,
    ) -> dict[int, SimulationPhase]:
        """Map every bar index to its active phase.

        If the scenario's total phase duration exceeds ``n_bars``, later phases
        are truncated. If it is shorter, the last phase is extended to cover
        all remaining bars.

        Args:
            n_bars: Total number of bars in the simulation.
            scenario: The active scenario.

        Returns:
            Dict mapping bar index (0-based) to ``SimulationPhase``.
        """
        phase_map: dict[int, SimulationPhase] = {}
        cursor = 0
        phases = scenario.phases

        for idx, (phase, duration) in enumerate(phases):
            is_last = idx == len(phases) - 1
            end = n_bars if is_last else min(cursor + duration, n_bars)
            for bar_i in range(cursor, end):
                phase_map[bar_i] = phase
            cursor = end
            if cursor >= n_bars:
                break

        # Fill any remaining bars with NORMAL (safety net)
        for bar_i in range(cursor, n_bars):
            phase_map[bar_i] = SimulationPhase.NORMAL

        return phase_map

    def _apply_phase_effects(
        self, bar: dict[str, Any], phase: SimulationPhase
    ) -> dict[str, Any]:
        """Modify a bar's OHLCV values to reflect the active phase regime.

        Applies in order:

        1. **Trend bias** — shifts all four prices (open/high/low/close) by a
           fixed percentage, compounding the directional drift of the phase.
        2. **Volatility multiplier** — expands or contracts the intra-bar
           high-low range symmetrically around the bar's mid-point.
        3. **Volume multiplier** — scales the bar's volume.
        4. **Gap probability** — with phase-specific probability, shifts the
           bar's open price by a random amount in the phase's gap range.

        All values are clamped to a minimum of 0.01 to avoid non-positive prices.

        Args:
            bar: OHLCV bar dict. Not mutated — a shallow copy is returned.
            phase: The ``SimulationPhase`` currently active.

        Returns:
            Modified bar dict.
        """
        params = _PHASE_PARAMS[phase]
        b = dict(bar)

        o = float(b.get("open", 0))
        h = float(b.get("high", 0))
        lo = float(b.get("low", 0))
        c = float(b.get("close", 0))
        v = int(b.get("volume", 0))

        if o <= 0 or h <= 0 or lo <= 0 or c <= 0:
            return b

        # 1. Trend bias — shift all prices proportionally
        bias_factor = 1.0 + params["trend_bias"] / 100.0
        o *= bias_factor
        h *= bias_factor
        lo *= bias_factor
        c *= bias_factor

        # 2. Volatility expansion/contraction around mid
        vol_mult = params["vol_mult"]
        if vol_mult != 1.0:
            mid = (h + lo) / 2.0
            half_range = (h - lo) / 2.0 * vol_mult
            h = mid + half_range
            lo = max(0.01, mid - half_range)
            # Keep close and open within [low, high]
            c = max(lo, min(h, c))
            o = max(lo, min(h, o))

        # 3. Volume
        volume_mult = params["volume_mult"]
        v = max(1, int(v * volume_mult))

        # 4. Gap probability (applied to open only)
        gap_prob = params["gap_prob"]
        if gap_prob > 0 and self._rng.random() < gap_prob:
            gap_min, gap_max = params["gap_range"]
            gap_pct = self._rng.uniform(gap_min, gap_max) / 100.0
            o = max(0.01, o * (1.0 + gap_pct))
            # Adjust high/low to include new open
            h = max(h, o)
            lo = min(lo, o)

        b["open"] = round(max(0.01, o), 2)
        b["high"] = round(max(0.01, h), 2)
        b["low"] = round(max(0.01, lo), 2)
        b["close"] = round(max(0.01, c), 2)
        b["volume"] = v

        return b

    def _inject_event(
        self, bar: dict[str, Any], event: MarketEvent
    ) -> dict[str, Any]:
        """Apply a ``MarketEvent``'s effects to a bar.

        Supported effect keys:

        - ``price_shock_pct``: Shift all four prices by this percentage.
          Negative values model crashes; positive model rallies. Applied
          to the already phase-modified bar.
        - ``volume_spike_mult``: Multiply volume. Values < 1 model thin markets.
        - ``volatility_mult``: Expand (or contract) the intra-bar range without
          changing the close price.
        - ``gap_pct``: Shift the bar's open price only (gap open simulation).

        Effects are applied in the order: ``gap_pct`` → ``price_shock_pct`` →
        ``volatility_mult`` → ``volume_spike_mult``.

        Args:
            bar: Phase-modified OHLCV bar dict. Not mutated.
            event: The ``MarketEvent`` to apply.

        Returns:
            Bar dict with event effects applied.
        """
        b = dict(bar)

        o = float(b.get("open", 0))
        h = float(b.get("high", 0))
        lo = float(b.get("low", 0))
        c = float(b.get("close", 0))
        v = int(b.get("volume", 0))

        if o <= 0 or h <= 0 or lo <= 0 or c <= 0:
            return b

        effects = event.effects

        # 1. Gap open (shifts open price only)
        gap_pct = effects.get("gap_pct", 0.0)
        if gap_pct != 0.0:
            o = max(0.01, o * (1.0 + gap_pct / 100.0))
            h = max(h, o)
            lo = min(lo, o)

        # 2. Price shock (shifts all prices)
        shock_pct = effects.get("price_shock_pct", 0.0)
        if shock_pct != 0.0:
            factor = 1.0 + shock_pct / 100.0
            o = max(0.01, o * factor)
            h = max(0.01, h * factor)
            lo = max(0.01, lo * factor)
            c = max(0.01, c * factor)

        # 3. Volatility multiplier (expand/contract range around close)
        vol_mult = effects.get("volatility_mult", 1.0)
        if vol_mult != 1.0 and vol_mult > 0:
            mid = (h + lo) / 2.0
            half_range = (h - lo) / 2.0 * vol_mult
            h = mid + half_range
            lo = max(0.01, mid - half_range)
            c = max(lo, min(h, c))
            o = max(lo, min(h, o))

        # 4. Volume spike
        vol_spike = effects.get("volume_spike_mult", 1.0)
        if vol_spike != 1.0:
            v = max(1, int(v * vol_spike))

        b["open"] = round(max(0.01, o), 2)
        b["high"] = round(max(0.01, h), 2)
        b["low"] = round(max(0.01, lo), 2)
        b["close"] = round(max(0.01, c), 2)
        b["volume"] = v

        logger.debug(
            "Event injected: %r at bar — shock=%.1f%% vol_spike=%.1fx",
            event.name,
            effects.get("price_shock_pct", 0.0),
            effects.get("volume_spike_mult", 1.0),
        )
        return b

    # ------------------------------------------------------------------
    # Result computation helpers
    # ------------------------------------------------------------------

    def _compute_phase_returns(
        self,
        equity_by_bar: list[Decimal],
        phase_map: dict[int, SimulationPhase],
    ) -> dict[str, float]:
        """Compute total return percentage per phase.

        For each unique phase, finds the equity at the start and end of each
        contiguous block and computes the cumulative return.

        Args:
            equity_by_bar: Equity value at the end of each bar (len = n_bars).
            phase_map: Bar-index → phase mapping.

        Returns:
            Dict mapping phase name (str) to total return percentage (float).
        """
        if not equity_by_bar or not phase_map:
            return {}

        # Group consecutive bars by phase
        phase_blocks: list[tuple[SimulationPhase, int, int]] = []  # (phase, start, end)
        current_phase: SimulationPhase | None = None
        block_start = 0

        for i in range(len(equity_by_bar)):
            p = phase_map.get(i, SimulationPhase.NORMAL)
            if p != current_phase:
                if current_phase is not None:
                    phase_blocks.append((current_phase, block_start, i - 1))
                current_phase = p
                block_start = i

        if current_phase is not None:
            phase_blocks.append((current_phase, block_start, len(equity_by_bar) - 1))

        # Aggregate returns per phase
        phase_start_equity: dict[str, Decimal] = {}
        phase_end_equity: dict[str, Decimal] = {}

        for phase, start, end in phase_blocks:
            key = phase.value
            start_eq = equity_by_bar[start]
            end_eq = equity_by_bar[end]

            if key not in phase_start_equity:
                phase_start_equity[key] = start_eq
            phase_end_equity[key] = end_eq  # last block wins for end

        result: dict[str, float] = {}
        for key in phase_start_equity:
            start_eq = phase_start_equity[key]
            end_eq = phase_end_equity[key]
            if start_eq > 0:
                ret = float((end_eq - start_eq) / start_eq * 100)
            else:
                ret = 0.0
            result[key] = round(ret, 4)

        return result

    def _compute_events_impact(
        self,
        equity_by_bar: list[Decimal],
        event_map: dict[int, list[MarketEvent]],
    ) -> list[dict[str, Any]]:
        """Compute equity P&L impact for each event.

        Compares equity at ``bar_index - 1`` (before event) and ``bar_index``
        (after event) for each injected event.

        Args:
            equity_by_bar: Equity value at end of each bar.
            event_map: Mapping of bar index to list of events at that bar.

        Returns:
            List of impact dicts (one per event) with keys:
            ``name``, ``bar_index``, ``equity_before``, ``equity_after``,
            ``pnl_impact``.
        """
        impacts: list[dict[str, Any]] = []
        for bar_idx, events in sorted(event_map.items()):
            eq_before = (
                equity_by_bar[bar_idx - 1]
                if bar_idx > 0 and bar_idx - 1 < len(equity_by_bar)
                else Decimal("0")
            )
            eq_after = (
                equity_by_bar[bar_idx]
                if bar_idx < len(equity_by_bar)
                else Decimal("0")
            )
            pnl_impact = eq_after - eq_before
            for event in events:
                impacts.append({
                    "name": event.name,
                    "bar_index": bar_idx,
                    "equity_before": str(eq_before),
                    "equity_after": str(eq_after),
                    "pnl_impact": str(pnl_impact),
                })
        return impacts

    def _compute_recovery_time(self, equity_by_bar: list[Decimal]) -> int | None:
        """Compute the number of bars from the equity trough to full recovery.

        ``Full recovery`` means equity returns to or above the level it was at
        the bar immediately before the trough.

        Args:
            equity_by_bar: Equity curve (per-bar equity values).

        Returns:
            Recovery time in bars, or ``None`` if recovery did not occur.
        """
        if not equity_by_bar:
            return None

        # Find the trough
        trough_val = equity_by_bar[0]
        trough_idx = 0
        for i, eq in enumerate(equity_by_bar):
            if eq < trough_val:
                trough_val = eq
                trough_idx = i

        # Recovery target: equity at bar before trough
        if trough_idx == 0:
            return None
        recovery_target = equity_by_bar[trough_idx - 1]

        # Count bars from trough to first bar at or above target
        for i in range(trough_idx + 1, len(equity_by_bar)):
            if equity_by_bar[i] >= recovery_target:
                return i - trough_idx

        return None  # Never recovered within the simulation window


# ---------------------------------------------------------------------------
# StressTestRunner
# ---------------------------------------------------------------------------


class StressTestRunner:
    """Runs a strategy against every built-in scenario and reports results.

    The runner reinstantiates the strategy class for each scenario to ensure
    a clean state. Strategy must accept ``symbol`` as a keyword argument (which
    is forwarded from the ``EngineConfig``).

    Args:
        strategy_class: The ``BaseBacktestStrategy`` subclass to test.
        config: ``EngineConfig`` template used for all scenario runs.
        scenarios: Optional custom scenario dict. Defaults to ``SCENARIOS``.
        seed: Optional random seed for reproducibility.
    """

    def __init__(
        self,
        strategy_class: type[BaseBacktestStrategy],
        config: EngineConfig,
        scenarios: dict[str, SimulationScenario] | None = None,
        seed: int | None = 42,
    ) -> None:
        self._strategy_class = strategy_class
        self._config = config
        self._scenarios = scenarios if scenarios is not None else SCENARIOS
        self._seed = seed

    def run_all_scenarios(
        self, bars: list[dict[str, Any]]
    ) -> dict[str, SimulationResult]:
        """Run the strategy against every scenario in the scenario library.

        Each scenario gets a fresh strategy instance and a fresh
        ``SimulationEngine``. Results are keyed by scenario name.

        Args:
            bars: Raw OHLCV bars used as the base for all scenarios.

        Returns:
            Dict mapping scenario key (str) to ``SimulationResult``.
        """
        results: dict[str, SimulationResult] = {}
        for key, scenario in self._scenarios.items():
            logger.info("StressTestRunner: running scenario %r", key)
            fresh_engine = BacktestEngine(self._config)
            sim = SimulationEngine(fresh_engine, seed=self._seed)
            strategy = self._strategy_class(symbol=self._config.symbol)
            result = sim.run_scenario(bars, scenario, strategy)
            results[key] = result
            logger.info(
                "  → survived=%s dd=%.2f%% final_equity=%s",
                result.survived,
                result.max_drawdown_pct,
                result.final_equity,
            )
        return results

    def report(self, results: dict[str, SimulationResult]) -> StressTestReport:
        """Generate a ``StressTestReport`` from a set of simulation results.

        Args:
            results: Output of ``run_all_scenarios``.

        Returns:
            Compact report with pass/fail counts and per-scenario stats.
        """
        strategy_name = self._strategy_class.__name__
        total = len(results)
        passed = sum(1 for r in results.values() if r.survived)
        failed = total - passed

        summary: list[dict[str, Any]] = []
        for key, result in results.items():
            summary.append({
                "scenario_key": key,
                "scenario_name": result.scenario_name,
                "survived": result.survived,
                "max_drawdown_pct": result.max_drawdown_pct,
                "final_equity": str(result.final_equity),
                "trade_count": len(result.trades),
                "recovery_time_bars": result.recovery_time_bars,
            })

        # Worst drawdown
        worst_dd_key = max(results, key=lambda k: results[k].max_drawdown_pct)

        # Best final equity
        best_eq_key = max(results, key=lambda k: results[k].final_equity)

        return StressTestReport(
            strategy_name=strategy_name,
            total_scenarios=total,
            passed=passed,
            failed=failed,
            scenario_summary=summary,
            worst_drawdown_scenario=results[worst_dd_key].scenario_name,
            best_scenario=results[best_eq_key].scenario_name,
        )
