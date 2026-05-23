"""Tests for AlgoTrading absorption — 5 category files (29 strategy classes).

Tests:
- All strategies can be instantiated with default parameters.
- All strategies produce a list from generate_orders() on synthetic data.
- Registry contains all expected strategy names.
- get_strategy() lookup works and raises KeyError on unknown names.

Synthetic data: 10 bars minimum required by the spec; we use 100 bars to
give warmup-heavy strategies (Ichimoku, TripleScreen) enough data to warm up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Minimal OHLCV stub — avoids importing packages.core in isolation
# ---------------------------------------------------------------------------


@dataclass
class _Bar:
    """Minimal OHLCV bar compatible with BaseBacktestStrategy.on_bar."""

    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    oi: int = 0


def _make_bars(
    n: int = 100,
    start: float = 100.0,
    trend: float = 0.1,
    vol: float = 0.5,
    seed: int = 42,
) -> list[_Bar]:
    """Generate synthetic OHLCV bars.

    Args:
        n: Number of bars.
        start: Starting price.
        trend: Per-bar price drift.
        vol: Noise amplitude.
        seed: Random seed for reproducibility.

    Returns:
        List of _Bar instances.
    """
    import random

    random.seed(seed)
    bars: list[_Bar] = []
    price = start
    for i in range(n):
        noise = random.uniform(-vol, vol)
        price = max(1.0, price + trend + noise)
        h = price + abs(noise) * 0.4
        lo = max(0.1, price - abs(noise) * 0.4)
        c = max(lo, min(h, price + random.uniform(-vol * 0.3, vol * 0.3)))
        bars.append(
            _Bar(
                timestamp=f"2025-01-{(i % 28) + 1:02d} 10:00:00",
                open=round(price, 2),
                high=round(h, 2),
                low=round(lo, 2),
                close=round(c, 2),
                volume=10000 + i * 100,
            )
        )
    return bars


def _run(strategy: Any, bars: list[_Bar]) -> list[Any]:
    """Feed all bars through a strategy and collect orders.

    Args:
        strategy: Any BaseBacktestStrategy subclass instance.
        bars: List of OHLCV bar objects.

    Returns:
        All OrderIntent objects produced across all bars.
    """
    all_orders: list[Any] = []
    for bar in bars:
        strategy.on_bar(bar)
        all_orders.extend(strategy.generate_orders())
    return all_orders


# ---------------------------------------------------------------------------
# Expected strategy names
# ---------------------------------------------------------------------------

TREND_FOLLOWING_NAMES = [
    "SupertrendStrategy",
    "EMACrossoverStrategy",
    "MACDStrategy",
    "ADXStrategy",
    "ADXDIStrategy",
    "ParabolicSARStrategy",
    "DonchianBreakoutStrategy",
    "KeltnerBreakoutStrategy",
    "HeikinAshiStrategy",
]

MEAN_REVERSION_NAMES = [
    "RSIStrategy",
    "BollingerBandStrategy",
    "StochasticStrategy",
    "CCIStrategy",
    "WilliamsRStrategy",
    "KeltnerChannelStrategy",
]

MOMENTUM_NAMES = [
    "MomentumStrategy",
    "DualMomentumStrategy",
    "VolumeBreakoutStrategy",
    "VWAPStrategy",
    "OBVStrategy",
    "VWMAStrategy",
]

VOLATILITY_NAMES = [
    "ATRBreakoutStrategy",
    "ATRRangeStrategy",
    "ChoppinessBreakoutStrategy",
    "VolatilityContractionStrategy",
]

COMPOSITE_NAMES = [
    "RSI_MACD_Strategy",
    "SupertrendEMAStrategy",
    "TripleScreenStrategy",
    "IchimokuStrategy",
]

ALL_NEW_STRATEGY_NAMES = (
    TREND_FOLLOWING_NAMES
    + MEAN_REVERSION_NAMES
    + MOMENTUM_NAMES
    + VOLATILITY_NAMES
    + COMPOSITE_NAMES
)


# ===========================================================================
# Trend-following tests
# ===========================================================================


def test_supertrend_strategy_instantiates() -> None:
    from strategies.trend_following import SupertrendStrategy

    s = SupertrendStrategy(symbol="NIFTY")
    assert s.name == "SupertrendStrategy"
    assert s.period == 10
    assert s.multiplier == 3.0


def test_supertrend_strategy_runs() -> None:
    from strategies.trend_following import SupertrendStrategy

    s = SupertrendStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


def test_ema_crossover_strategy_instantiates() -> None:
    from strategies.trend_following import EMACrossoverStrategy

    s = EMACrossoverStrategy(symbol="NIFTY", fast_period=5, slow_period=15)
    assert s.fast_period == 5
    assert s.slow_period == 15


def test_ema_crossover_strategy_runs() -> None:
    from strategies.trend_following import EMACrossoverStrategy

    s = EMACrossoverStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


def test_macd_strategy_instantiates() -> None:
    from strategies.trend_following import MACDStrategy

    s = MACDStrategy(symbol="NIFTY")
    assert s.fast_period == 12
    assert s.slow_period == 26
    assert s.signal_period == 9


def test_macd_strategy_runs() -> None:
    from strategies.trend_following import MACDStrategy

    s = MACDStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


def test_adx_strategy_instantiates() -> None:
    from strategies.trend_following import ADXStrategy

    s = ADXStrategy(symbol="NIFTY", adx_threshold=20.0)
    assert s.adx_threshold == 20.0


def test_adx_strategy_runs() -> None:
    from strategies.trend_following import ADXStrategy

    s = ADXStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


def test_adx_di_strategy_runs() -> None:
    from strategies.trend_following import ADXDIStrategy

    s = ADXDIStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


def test_parabolic_sar_strategy_instantiates() -> None:
    from strategies.trend_following import ParabolicSARStrategy

    s = ParabolicSARStrategy(symbol="NIFTY", acceleration=0.01, max_acceleration=0.1)
    assert s.acceleration == 0.01


def test_parabolic_sar_strategy_runs() -> None:
    from strategies.trend_following import ParabolicSARStrategy

    s = ParabolicSARStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


def test_donchian_breakout_strategy_runs() -> None:
    from strategies.trend_following import DonchianBreakoutStrategy

    s = DonchianBreakoutStrategy(symbol="NIFTY", period=10)
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


def test_keltner_breakout_strategy_runs() -> None:
    from strategies.trend_following import KeltnerBreakoutStrategy

    s = KeltnerBreakoutStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


def test_heikin_ashi_strategy_instantiates() -> None:
    from strategies.trend_following import HeikinAshiStrategy

    s = HeikinAshiStrategy(symbol="NIFTY", consecutive_candles=4)
    assert s.consecutive_candles == 4


def test_heikin_ashi_strategy_runs() -> None:
    from strategies.trend_following import HeikinAshiStrategy

    s = HeikinAshiStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


# ===========================================================================
# Mean reversion tests
# ===========================================================================


def test_rsi_strategy_instantiates() -> None:
    from strategies.mean_reversion import RSIStrategy

    s = RSIStrategy(symbol="NIFTY", rsi_period=14, oversold_level=30.0)
    assert s.rsi_period == 14
    assert s.oversold_level == 30.0


def test_rsi_strategy_runs() -> None:
    from strategies.mean_reversion import RSIStrategy

    s = RSIStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


def test_bollinger_band_strategy_instantiates() -> None:
    from strategies.mean_reversion import BollingerBandStrategy

    s = BollingerBandStrategy(symbol="NIFTY", period=20, num_std=2.0)
    assert s.period == 20
    assert s.num_std == 2.0


def test_bollinger_band_strategy_runs() -> None:
    from strategies.mean_reversion import BollingerBandStrategy

    s = BollingerBandStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


def test_stochastic_strategy_instantiates() -> None:
    from strategies.mean_reversion import StochasticStrategy

    s = StochasticStrategy(symbol="NIFTY", k_period=14, d_period=3)
    assert s.k_period == 14
    assert s.d_period == 3


def test_stochastic_strategy_runs() -> None:
    from strategies.mean_reversion import StochasticStrategy

    s = StochasticStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


def test_cci_strategy_instantiates() -> None:
    from strategies.mean_reversion import CCIStrategy

    s = CCIStrategy(symbol="NIFTY", cci_period=20)
    assert s.cci_period == 20


def test_cci_strategy_runs() -> None:
    from strategies.mean_reversion import CCIStrategy

    s = CCIStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


def test_williams_r_strategy_instantiates() -> None:
    from strategies.mean_reversion import WilliamsRStrategy

    s = WilliamsRStrategy(symbol="NIFTY", period=14)
    assert s.period == 14


def test_williams_r_strategy_runs() -> None:
    from strategies.mean_reversion import WilliamsRStrategy

    s = WilliamsRStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


def test_keltner_channel_strategy_runs() -> None:
    from strategies.mean_reversion import KeltnerChannelStrategy

    s = KeltnerChannelStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


# ===========================================================================
# Momentum tests
# ===========================================================================


def test_momentum_strategy_instantiates() -> None:
    from strategies.momentum import MomentumStrategy

    s = MomentumStrategy(symbol="NIFTY", roc_period=12)
    assert s.roc_period == 12


def test_momentum_strategy_runs() -> None:
    from strategies.momentum import MomentumStrategy

    s = MomentumStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


def test_dual_momentum_strategy_runs() -> None:
    from strategies.momentum import DualMomentumStrategy

    s = DualMomentumStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


def test_volume_breakout_strategy_instantiates() -> None:
    from strategies.momentum import VolumeBreakoutStrategy

    s = VolumeBreakoutStrategy(symbol="NIFTY", volume_spike_multiplier=2.0)
    assert s.volume_spike_multiplier == 2.0


def test_volume_breakout_strategy_runs() -> None:
    from strategies.momentum import VolumeBreakoutStrategy

    s = VolumeBreakoutStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


def test_vwap_strategy_runs() -> None:
    from strategies.momentum import VWAPStrategy

    s = VWAPStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


def test_obv_strategy_runs() -> None:
    from strategies.momentum import OBVStrategy

    s = OBVStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


def test_vwma_strategy_instantiates() -> None:
    from strategies.momentum import VWMAStrategy

    s = VWMAStrategy(symbol="NIFTY", vwma_period=14)
    assert s.vwma_period == 14


def test_vwma_strategy_runs() -> None:
    from strategies.momentum import VWMAStrategy

    s = VWMAStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


# ===========================================================================
# Volatility tests
# ===========================================================================


def test_atr_breakout_strategy_instantiates() -> None:
    from strategies.volatility import ATRBreakoutStrategy

    s = ATRBreakoutStrategy(symbol="NIFTY", expansion_ratio=1.1)
    assert s.expansion_ratio == 1.1


def test_atr_breakout_strategy_runs() -> None:
    from strategies.volatility import ATRBreakoutStrategy

    s = ATRBreakoutStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


def test_atr_range_strategy_instantiates() -> None:
    from strategies.volatility import ATRRangeStrategy

    s = ATRRangeStrategy(symbol="NIFTY", lookback_period=5)
    assert s.lookback_period == 5


def test_atr_range_strategy_runs() -> None:
    from strategies.volatility import ATRRangeStrategy

    s = ATRRangeStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


def test_choppiness_breakout_strategy_instantiates() -> None:
    from strategies.volatility import ChoppinessBreakoutStrategy

    s = ChoppinessBreakoutStrategy(symbol="NIFTY", trend_threshold=61.8)
    assert s.trend_threshold == 61.8


def test_choppiness_breakout_strategy_runs() -> None:
    from strategies.volatility import ChoppinessBreakoutStrategy

    s = ChoppinessBreakoutStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


def test_volatility_contraction_strategy_runs() -> None:
    from strategies.volatility import VolatilityContractionStrategy

    s = VolatilityContractionStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


# ===========================================================================
# Composite tests
# ===========================================================================


def test_rsi_macd_strategy_instantiates() -> None:
    from strategies.composite import RSI_MACD_Strategy

    s = RSI_MACD_Strategy(symbol="NIFTY", rsi_oversold=35.0)
    assert s.rsi_oversold == 35.0


def test_rsi_macd_strategy_runs() -> None:
    from strategies.composite import RSI_MACD_Strategy

    s = RSI_MACD_Strategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


def test_supertrend_ema_strategy_instantiates() -> None:
    from strategies.composite import SupertrendEMAStrategy

    s = SupertrendEMAStrategy(symbol="NIFTY", st_multiplier=3.5)
    assert s.st_multiplier == 3.5


def test_supertrend_ema_strategy_runs() -> None:
    from strategies.composite import SupertrendEMAStrategy

    s = SupertrendEMAStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


def test_triple_screen_strategy_instantiates() -> None:
    from strategies.composite import TripleScreenStrategy

    s = TripleScreenStrategy(symbol="NIFTY", trend_ema_period=52)
    assert s.trend_ema_period == 52


def test_triple_screen_strategy_runs() -> None:
    from strategies.composite import TripleScreenStrategy

    s = TripleScreenStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


def test_ichimoku_strategy_instantiates() -> None:
    from strategies.composite import IchimokuStrategy

    s = IchimokuStrategy(symbol="NIFTY", tenkan_period=9, kijun_period=26)
    assert s.tenkan_period == 9
    assert s.kijun_period == 26


def test_ichimoku_strategy_runs() -> None:
    from strategies.composite import IchimokuStrategy

    s = IchimokuStrategy(symbol="NIFTY")
    orders = _run(s, _make_bars(100))
    assert isinstance(orders, list)


# ===========================================================================
# Registry tests
# ===========================================================================


def test_strategy_registry_contains_all_new_strategies() -> None:
    """All 29 absorbed strategy classes must be in STRATEGY_REGISTRY."""
    from strategies import STRATEGY_REGISTRY

    for name in ALL_NEW_STRATEGY_NAMES:
        assert name in STRATEGY_REGISTRY, f"Missing from STRATEGY_REGISTRY: {name!r}"


def test_strategy_registry_size() -> None:
    """STRATEGY_REGISTRY must have exactly 29 entries (the absorbed batch)."""
    from strategies import STRATEGY_REGISTRY

    assert len(STRATEGY_REGISTRY) == len(ALL_NEW_STRATEGY_NAMES), (
        f"Expected {len(ALL_NEW_STRATEGY_NAMES)} entries in STRATEGY_REGISTRY, "
        f"got {len(STRATEGY_REGISTRY)}"
    )


def test_all_new_strategies_in_strategy_registry() -> None:
    """All 29 new names must appear in STRATEGY_REGISTRY (BaseBacktestStrategy-based dict)."""
    from strategies import STRATEGY_REGISTRY

    for name in ALL_NEW_STRATEGY_NAMES:
        assert name in STRATEGY_REGISTRY, f"Missing from STRATEGY_REGISTRY: {name!r}"


def test_get_strategy_returns_correct_class() -> None:
    """get_strategy() must return the registered class."""
    from strategies import STRATEGY_REGISTRY, get_strategy
    from strategies.trend_following import SupertrendStrategy

    cls = get_strategy("SupertrendStrategy")
    assert cls is SupertrendStrategy
    assert cls is STRATEGY_REGISTRY["SupertrendStrategy"]


def test_get_strategy_raises_on_unknown() -> None:
    """get_strategy() must raise KeyError for unknown names."""
    from strategies import get_strategy

    with pytest.raises(KeyError, match="does_not_exist"):
        get_strategy("does_not_exist")


# ===========================================================================
# Bulk instantiation and on_bar tests
# ===========================================================================


@pytest.mark.parametrize("strategy_name", ALL_NEW_STRATEGY_NAMES)
def test_all_new_strategies_instantiate(strategy_name: str) -> None:
    """Every new strategy must instantiate via its registry entry."""
    from strategies import STRATEGY_REGISTRY

    cls = STRATEGY_REGISTRY[strategy_name]
    instance = cls(symbol="TEST")
    assert instance is not None
    assert instance.name  # name must be non-empty string


@pytest.mark.parametrize("strategy_name", ALL_NEW_STRATEGY_NAMES)
def test_all_new_strategies_on_bar_no_exception(strategy_name: str) -> None:
    """Every new strategy must process 10 bars without raising an exception."""
    from strategies import STRATEGY_REGISTRY

    cls = STRATEGY_REGISTRY[strategy_name]
    instance = cls(symbol="TEST")
    bars = _make_bars(n=10, start=100.0)
    for bar in bars:
        instance.on_bar(bar)
    orders = instance.generate_orders()
    assert isinstance(orders, list)


@pytest.mark.parametrize("strategy_name", ALL_NEW_STRATEGY_NAMES)
def test_all_new_strategies_produce_signals_on_100_bars(strategy_name: str) -> None:
    """Every new strategy must run 100 bars without error and return a list."""
    from strategies import STRATEGY_REGISTRY

    cls = STRATEGY_REGISTRY[strategy_name]
    instance = cls(symbol="TEST")
    bars = _make_bars(n=100)
    all_orders = _run(instance, bars)
    assert isinstance(all_orders, list)
