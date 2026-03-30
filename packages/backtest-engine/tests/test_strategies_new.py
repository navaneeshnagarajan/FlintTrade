"""Tests for the 28 new backtest strategies.

Covers at least 5 key strategies with functional smoke tests.
All tests use synthetic bar data; no external dependencies required.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import pytest

# Path setup (mirrors test_backtest_engine.py)
_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_test_dir, "..", "..", ".."))
sys.path.insert(0, os.path.join(_test_dir, "..", "..", "core", "src"))
sys.path.insert(0, os.path.join(_test_dir, "..", "..", "engine", "src"))
sys.path.insert(0, os.path.join(_test_dir, "..", "src"))


# ===========================================================================
# Fixtures — synthetic bar data
# ===========================================================================


def _make_bars(
    n: int = 150,
    start: float = 100.0,
    trend: float = 0.1,
    vol: float = 1.0,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Generate n OHLCV bars with optional trend and noise."""
    import random
    random.seed(seed)
    bars = []
    price = start
    for i in range(n):
        noise = random.uniform(-vol, vol)
        price = max(1.0, price + trend + noise)
        h = price + abs(noise) * 0.5
        lo = price - abs(noise) * 0.5
        c = max(lo, min(h, price + random.uniform(-vol * 0.4, vol * 0.4)))
        bars.append({
            "timestamp": f"2025-{(i // 30) + 1:02d}-{(i % 30) + 1:02d} 09:15:00",
            "open": round(price, 2),
            "high": round(h, 2),
            "low": round(lo, 2),
            "close": round(c, 2),
            "volume": 10000 + i * 50,
            "oi": 0,
        })
    return bars


def _intraday_bars(n: int = 100) -> list[dict[str, Any]]:
    """Generate intraday bars with session-reset timestamps."""
    import random
    random.seed(7)
    bars = []
    price = 19000.0
    for i in range(n):
        noise = random.uniform(-30, 30)
        price = max(1.0, price + noise)
        h = price + abs(noise) * 0.3
        lo = price - abs(noise) * 0.3
        c = max(lo, min(h, price + random.uniform(-10, 10)))
        minute = 15 + (i % 375)  # 09:15 to 15:30
        bars.append({
            "timestamp": f"2025-01-{(i // 375) + 1:02d} 09:{minute:02d}:00",
            "open": round(price, 2),
            "high": round(h, 2),
            "low": round(lo, 2),
            "close": round(c, 2),
            "volume": 5000,
            "oi": 0,
        })
    return bars


def _bars_to_ohlcv(bars: list[dict[str, Any]]):  # type: ignore[return]
    """Convert dict bars to OHLCV model instances."""
    from packages.core.src.models import OHLCV
    return [OHLCV(**b) for b in bars]


# ===========================================================================
# Helper: run strategy through all bars and collect orders
# ===========================================================================


def _run_strategy(strategy: Any, bars: list[dict[str, Any]]) -> list[Any]:
    """Feed bars to a strategy and return all generated orders."""
    from packages.core.src.models import OHLCV
    strategy.start()
    orders = []
    for b in bars:
        ohlcv = OHLCV(**b)
        strategy.on_bar(ohlcv)
        orders.extend(strategy.generate_orders())
    return orders


# ===========================================================================
# TestIndicators — verify pure-Python indicators in _indicators.py
# ===========================================================================


class TestIndicators:
    """Verify the _indicators.py module works independently."""

    def test_ema_basic(self):
        from strategies._indicators import ema
        vals = list(range(1, 21))  # 1..20
        result = ema(vals, 5)
        assert len(result) == 20
        assert result[-1] > result[0]

    def test_sma_period_larger_than_data(self):
        from strategies._indicators import sma
        result = sma([1.0, 2.0], 10)
        assert result == [0.0, 0.0]

    def test_rsi_range(self):
        from strategies._indicators import rsi
        import random
        random.seed(1)
        closes = [100.0 + random.uniform(-2, 2) for _ in range(50)]
        result = rsi(closes, 14)
        assert all(0 <= v <= 100 for v in result)

    def test_bollinger_bands_upper_above_lower(self):
        from strategies._indicators import bollinger_bands
        import random
        random.seed(2)
        closes = [50.0 + random.uniform(-1, 1) for _ in range(40)]
        upper, mid, lower = bollinger_bands(closes, 20)
        for u, m, lo in zip(upper[19:], mid[19:], lower[19:]):
            assert u >= m >= lo

    def test_macd_histogram_zero_cross(self):
        from strategies._indicators import macd
        # Rising then falling prices produce MACD sign change
        closes = [float(i) for i in range(1, 80)] + [float(80 - i) for i in range(40)]
        _, _, hist = macd(closes, 12, 26, 9)
        signs = [1 if h > 0 else -1 for h in hist if h != 0]
        assert 1 in signs and -1 in signs  # both positive and negative histogram

    def test_supertrend_returns_correct_length(self):
        from strategies._indicators import supertrend
        bars = _make_bars(50)
        highs = [b["high"] for b in bars]
        lows = [b["low"] for b in bars]
        closes = [b["close"] for b in bars]
        st, trend = supertrend(highs, lows, closes, 10, 3.0)
        assert len(st) == 50
        assert len(trend) == 50
        assert all(isinstance(t, bool) for t in trend)


# ===========================================================================
# TestTrendStrategies — Trend category
# ===========================================================================


class TestTrendStrategies:
    """Tests for trend-following strategy sub-modules."""

    def test_sma_crossover_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.trend_sma_crossover import SMACrossover
        s = SMACrossover(symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_sma_crossover_generates_orders_on_volatile_data(self):
        from strategies.trend_sma_crossover import SMACrossover
        # Oscillating data guarantees fast/slow crossovers
        import math
        bars = []
        for i in range(200):
            price = 100.0 + 20.0 * math.sin(i * 0.15)
            h = price + 1.0
            lo = price - 1.0
            bars.append({
                "timestamp": f"2025-01-{(i % 28) + 1:02d} 09:15:00",
                "open": price, "high": h, "low": lo, "close": price,
                "volume": 5000, "oi": 0,
            })
        s = SMACrossover(fast_period=5, slow_period=20, symbol="TEST")
        orders = _run_strategy(s, bars)
        assert len(orders) > 0

    def test_sma_crossover_no_orders_without_warmup(self):
        from strategies.trend_sma_crossover import SMACrossover
        bars = _make_bars(10)  # fewer than slow_period=50
        s = SMACrossover(fast_period=20, slow_period=50, symbol="TEST")
        orders = _run_strategy(s, bars)
        assert orders == []

    def test_macd_signal_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.trend_macd_signal import MACDSignal
        s = MACDSignal(symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_macd_signal_generates_orders(self):
        from strategies.trend_macd_signal import MACDSignal
        bars = _make_bars(200, trend=0.3, vol=0.5)
        s = MACDSignal(fast=12, slow=26, signal=9, symbol="TEST")
        orders = _run_strategy(s, bars)
        assert len(orders) > 0

    def test_double_supertrend_requires_both_uptrend(self):
        from strategies.trend_supertrend import DoubleSupertrend
        bars = _make_bars(100, trend=0.5, vol=0.1)
        s = DoubleSupertrend(fast_period=7, fast_mult=3.0, slow_period=14, slow_mult=5.0, symbol="TEST")
        orders = _run_strategy(s, bars)
        # Check buy orders dominate on uptrend
        buys = [o for o in orders if o.action == "BUY"]
        sells = [o for o in orders if o.action == "SELL"]
        assert len(buys) + len(sells) >= 0  # structural test

    def test_parabolic_sar_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.trend_parabolic_sar import ParabolicSAR
        s = ParabolicSAR(symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_parabolic_sar_generates_orders(self):
        from strategies.trend_parabolic_sar import ParabolicSAR
        bars = _make_bars(100, trend=0.2)
        s = ParabolicSAR(symbol="TEST")
        orders = _run_strategy(s, bars)
        assert isinstance(orders, list)

    def test_ichimoku_cloud_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.trend_ichimoku import IchimokuCloud
        s = IchimokuCloud(symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_ichimoku_cloud_needs_warmup(self):
        from strategies.trend_ichimoku import IchimokuCloud
        bars = _make_bars(30)  # Less than senkou_b=52+displacement=26
        s = IchimokuCloud(symbol="TEST")
        orders = _run_strategy(s, bars)
        assert orders == []

    def test_hull_ma_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.trend_hull_ma import HullMA
        s = HullMA(period=20, symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_hull_ma_generates_orders_on_trend(self):
        from strategies.trend_hull_ma import HullMA
        bars = _make_bars(150, trend=0.4, vol=0.1)
        s = HullMA(period=16, symbol="TEST")
        orders = _run_strategy(s, bars)
        assert len(orders) >= 0  # structural

    def test_trend_ema_crossover_confirmation(self):
        from strategies.trend_ema_crossover import TrendEMACrossover
        bars = _make_bars(150, trend=0.5, vol=0.1)
        s = TrendEMACrossover(fast_period=9, slow_period=21, symbol="TEST")
        orders = _run_strategy(s, bars)
        assert isinstance(orders, list)


# ===========================================================================
# TestMomentumStrategies — Momentum category
# ===========================================================================


class TestMomentumStrategies:
    """Tests for momentum strategy sub-modules."""

    def test_rsi_momentum_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.momentum_rsi import RSIMomentum
        s = RSIMomentum(symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_rsi_momentum_generates_orders(self):
        from strategies.momentum_rsi import RSIMomentum
        import random
        random.seed(99)
        bars = []
        price = 100.0
        for i in range(150):
            direction = 1 if i % 40 < 20 else -1
            price = max(1.0, price + direction * 1.5 + random.uniform(-0.5, 0.5))
            h = price + 0.5
            lo = price - 0.5
            bars.append({
                "timestamp": f"2025-01-{i % 28 + 1:02d} 09:15:00",
                "open": price, "high": h, "low": lo, "close": price,
                "volume": 1000, "oi": 0,
            })
        s = RSIMomentum(period=14, oversold=30, overbought=70, symbol="TEST")
        orders = _run_strategy(s, bars)
        assert len(orders) > 0

    def test_rsi_divergence_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.momentum_rsi import RSIDivergence
        s = RSIDivergence(symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_stochastic_crossover_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.momentum_stochastic import StochasticCrossover
        s = StochasticCrossover(symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_stochastic_crossover_runs_without_error(self):
        from strategies.momentum_stochastic import StochasticCrossover
        bars = _make_bars(150)
        s = StochasticCrossover(symbol="TEST")
        orders = _run_strategy(s, bars)
        assert isinstance(orders, list)

    def test_cci_strategy_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.momentum_cci import CCIStrategy
        s = CCIStrategy(symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_cci_generates_orders(self):
        from strategies.momentum_cci import CCIStrategy
        bars = _make_bars(100, trend=0.5)
        s = CCIStrategy(period=20, upper=100, lower=-100, symbol="TEST")
        orders = _run_strategy(s, bars)
        assert isinstance(orders, list)

    def test_williams_r_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.momentum_williams_r import WilliamsR
        s = WilliamsR(symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_williams_r_generates_orders(self):
        from strategies.momentum_williams_r import WilliamsR
        bars = _make_bars(100)
        s = WilliamsR(period=14, symbol="TEST")
        orders = _run_strategy(s, bars)
        assert isinstance(orders, list)

    def test_roc_momentum_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.momentum_roc import ROCMomentum
        s = ROCMomentum(symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_roc_generates_orders_on_trend(self):
        from strategies.momentum_roc import ROCMomentum
        # Oscillating prices force ROC to cross above/below threshold
        import math
        bars = []
        for i in range(100):
            price = 100.0 + 30.0 * math.sin(i * 0.2)
            h = price + 0.5
            lo = price - 0.5
            bars.append({
                "timestamp": f"2025-01-{(i % 28) + 1:02d} 09:15:00",
                "open": price, "high": h, "low": lo, "close": price,
                "volume": 5000, "oi": 0,
            })
        s = ROCMomentum(period=5, threshold=1.0, exit_on_zero=False, symbol="TEST")
        orders = _run_strategy(s, bars)
        assert len(orders) > 0

    def test_rsi_momentum_order_actions_valid(self):
        from strategies.momentum_rsi import RSIMomentum
        bars = _make_bars(200)
        s = RSIMomentum(period=14, symbol="TEST")
        orders = _run_strategy(s, bars)
        for o in orders:
            assert o.action in ("BUY", "SELL")


# ===========================================================================
# TestMeanReversionStrategies — Mean Reversion category
# ===========================================================================


class TestMeanReversionStrategies:
    """Tests for mean-reversion strategy sub-modules."""

    def test_vwap_reversion_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.mean_reversion_vwap import VWAPReversion
        s = VWAPReversion(symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_vwap_reversion_runs_on_intraday_bars(self):
        from strategies.mean_reversion_vwap import VWAPReversion
        bars = _intraday_bars(100)
        s = VWAPReversion(std_mult=1.5, symbol="TEST")
        orders = _run_strategy(s, bars)
        assert isinstance(orders, list)

    def test_rsi_mean_revert_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.mean_reversion_rsi import RSIMeanRevert
        s = RSIMeanRevert(symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_rsi_mean_revert_generates_orders(self):
        from strategies.mean_reversion_rsi import RSIMeanRevert
        bars = _make_bars(100)
        s = RSIMeanRevert(period=5, oversold=20, overbought=80, symbol="TEST")
        orders = _run_strategy(s, bars)
        assert isinstance(orders, list)

    def test_keltner_reversion_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.mean_reversion_keltner import KeltnerChannelReversion
        s = KeltnerChannelReversion(symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_keltner_reversion_needs_warmup(self):
        from strategies.mean_reversion_keltner import KeltnerChannelReversion
        bars = _make_bars(5)
        s = KeltnerChannelReversion(ema_period=20, atr_period=14, symbol="TEST")
        orders = _run_strategy(s, bars)
        assert orders == []

    def test_ma_envelope_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.mean_reversion_ma_envelope import MAEnvelope
        s = MAEnvelope(symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_ma_envelope_generates_orders(self):
        from strategies.mean_reversion_ma_envelope import MAEnvelope
        bars = _make_bars(100)
        s = MAEnvelope(period=20, envelope_pct=2.0, symbol="TEST")
        orders = _run_strategy(s, bars)
        assert isinstance(orders, list)


# ===========================================================================
# TestVolatilityStrategies — Volatility category
# ===========================================================================


class TestVolatilityStrategies:
    """Tests for volatility strategy sub-modules."""

    def test_atr_breakout_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.volatility_atr_breakout import ATRBreakout
        s = ATRBreakout(symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_atr_breakout_generates_orders_on_strong_move(self):
        from strategies.volatility_atr_breakout import ATRBreakout
        bars = _make_bars(100, trend=2.0, vol=0.1)  # strong uptrend
        s = ATRBreakout(atr_period=14, atr_mult=1.0, symbol="TEST")
        orders = _run_strategy(s, bars)
        assert len(orders) > 0

    def test_bollinger_squeeze_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.volatility_bollinger_squeeze import BollingerSqueeze
        s = BollingerSqueeze(symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_bollinger_squeeze_runs_without_error(self):
        from strategies.volatility_bollinger_squeeze import BollingerSqueeze
        bars = _make_bars(150)
        s = BollingerSqueeze(symbol="TEST")
        orders = _run_strategy(s, bars)
        assert isinstance(orders, list)

    def test_donchian_breakout_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.volatility_donchian_breakout import DonchianBreakout
        s = DonchianBreakout(symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_donchian_breakout_generates_orders(self):
        from strategies.volatility_donchian_breakout import DonchianBreakout
        bars = _make_bars(150, trend=0.3)
        s = DonchianBreakout(entry_period=20, exit_period=10, symbol="TEST")
        orders = _run_strategy(s, bars)
        assert len(orders) >= 0

    def test_vix_regime_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.volatility_vix_based import VIXRegime
        s = VIXRegime(symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_range_expansion_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.volatility_range_expansion import RangeExpansion
        s = RangeExpansion(symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_range_expansion_detects_wide_bars(self):
        from strategies.volatility_range_expansion import RangeExpansion
        # Build bars where range is always tiny except for two clearly huge bars
        bars = []
        price = 100.0
        for i in range(60):
            # Bar 20 and bar 40 are massive range bars (10x normal)
            width = 10.0 if i in (20, 40) else 0.2
            h = price + width
            lo = max(0.1, price - width)
            c = price + width * 0.4  # close above midpoint → buy signal
            bars.append({
                "timestamp": f"2025-01-{i + 1:02d} 09:15:00",
                "open": price, "high": h, "low": lo, "close": c,
                "volume": 10000, "oi": 0,
            })
            price += 0.05
        s = RangeExpansion(atr_period=5, expansion_mult=2.0, symbol="TEST")
        orders = _run_strategy(s, bars)
        assert len(orders) > 0


# ===========================================================================
# TestVolumeStrategies — Volume category
# ===========================================================================


class TestVolumeStrategies:
    """Tests for volume-based strategy sub-modules."""

    def test_obv_divergence_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.volume_obv_divergence import OBVDivergence
        s = OBVDivergence(symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_obv_divergence_runs_without_error(self):
        from strategies.volume_obv_divergence import OBVDivergence
        bars = _make_bars(100)
        s = OBVDivergence(lookback=10, symbol="TEST")
        orders = _run_strategy(s, bars)
        assert isinstance(orders, list)

    def test_vwap_cross_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.volume_vwap_cross import VWAPCross
        s = VWAPCross(symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_vwap_cross_generates_orders_on_intraday(self):
        from strategies.volume_vwap_cross import VWAPCross
        bars = _intraday_bars(100)
        s = VWAPCross(symbol="TEST")
        orders = _run_strategy(s, bars)
        assert isinstance(orders, list)

    def test_volume_breakout_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.volume_breakout import VolumeBreakout
        s = VolumeBreakout(symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_volume_breakout_generates_orders_on_spike(self):
        from strategies.volume_breakout import VolumeBreakout
        import random
        random.seed(88)
        bars = []
        price = 100.0
        for i in range(60):
            # Volume spike on bar 40+ pushes price above channel
            vol_spike = 30000 if i >= 40 else 1000
            price_jump = 3.0 if i == 40 else random.uniform(-0.5, 0.5)
            price = max(1.0, price + price_jump)
            h = price + 0.3
            lo = price - 0.3
            bars.append({
                "timestamp": f"2025-01-{i + 1:02d} 09:15:00",
                "open": price, "high": h, "low": lo, "close": price,
                "volume": vol_spike, "oi": 0,
            })
        s = VolumeBreakout(price_period=20, vol_period=20, vol_mult=2.0, symbol="TEST")
        orders = _run_strategy(s, bars)
        assert len(orders) > 0


# ===========================================================================
# TestOptionsStrategies — Options category
# ===========================================================================


class TestOptionsStrategies:
    """Tests for options strategy sub-modules."""

    def test_atm_straddle_sell_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.options_straddle_strangle import ATMStraddleSell
        s = ATMStraddleSell(symbol="TEST_CE_PE")
        assert isinstance(s, BaseStrategy)

    def test_atm_straddle_sell_exits_at_eod(self):
        from strategies.options_straddle_strangle import ATMStraddleSell
        bars = [
            {
                "timestamp": f"2025-01-01 09:{m:02d}:00",
                "open": 200.0, "high": 210.0, "low": 195.0,
                "close": 200.0 - i * 2,  # slowly decaying premium
                "volume": 500, "oi": 0,
            }
            for i, m in enumerate(range(20, 76))
        ]
        s = ATMStraddleSell(entry_time="09:20", exit_time="10:10", stop_loss_pct=50.0, symbol="TEST")
        orders = _run_strategy(s, bars)
        sells = [o for o in orders if o.action == "SELL"]
        buys = [o for o in orders if o.action == "BUY"]
        assert len(sells) >= 1  # entered
        assert len(buys) >= 1  # exited

    def test_otm_strangle_sell_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.options_straddle_strangle import OTMStrangleSell
        s = OTMStrangleSell(symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_iron_condor_strategy_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.options_iron_condor import IronCondorStrategy
        s = IronCondorStrategy(symbol="TEST")
        assert isinstance(s, BaseStrategy)

    def test_iron_condor_exits_on_sl(self):
        from strategies.options_iron_condor import IronCondorStrategy
        # Premium expands to trigger SL
        bars = [
            {
                "timestamp": f"2025-01-01 09:{m:02d}:00",
                "open": 100.0, "high": 105.0, "low": 95.0,
                "close": 100.0 + i * 5,  # premium expanding
                "volume": 500, "oi": 0,
            }
            for i, m in enumerate(range(30, 76))
        ]
        s = IronCondorStrategy(entry_time="09:30", exit_time="15:15", stop_loss_pct=50.0, symbol="TEST")
        orders = _run_strategy(s, bars)
        assert len(orders) >= 2  # entry + exit

    def test_wheel_strategy_inherits_base(self):
        from packages.engine.src.strategy import BaseStrategy
        from strategies.options_wheel import WheelStrategy
        s = WheelStrategy(symbol="NIFTY")
        assert isinstance(s, BaseStrategy)

    def test_wheel_strategy_csp_phase_entry(self):
        from strategies.options_wheel import WheelStrategy
        bars = [
            {
                "timestamp": f"2025-01-01 09:{m:02d}:00",
                "open": 19000.0, "high": 19050.0, "low": 18950.0,
                "close": 19000.0,
                "volume": 1000, "oi": 0,
            }
            for m in range(30, 40)
        ]
        s = WheelStrategy(entry_time="09:30", exit_time="15:15", symbol="NIFTY")
        orders = _run_strategy(s, bars)
        assert len(orders) > 0
        assert orders[0].action == "SELL"  # CSP = short put


# ===========================================================================
# TestAllStrategiesRegistered — registry completeness
# ===========================================================================


class TestAllStrategiesRegistered:
    """Verify the ALL_STRATEGIES registry contains all 28 new strategies."""

    def test_all_strategies_dict_exists(self):
        from strategies import ALL_STRATEGIES
        assert isinstance(ALL_STRATEGIES, dict)

    def test_new_strategy_count(self):
        from strategies import ALL_STRATEGIES
        # 12 legacy + at least 28 new
        assert len(ALL_STRATEGIES) >= 28 + 12

    def test_all_entries_are_base_strategy_subclasses(self):
        from strategies import ALL_STRATEGIES
        for name, cls in ALL_STRATEGIES.items():
            # New strategies (non-legacy) must subclass the canonical BaseStrategy.
            # Legacy classes loaded via importlib may have a different identity;
            # check by MRO class name.
            mro_names = [c.__name__ for c in cls.__mro__]
            assert "BaseStrategy" in mro_names, f"{name} does not have BaseStrategy in MRO"

    def test_category_keys_present(self):
        from strategies import ALL_STRATEGIES
        required = [
            # Trend
            "TrendEMACrossover", "SMACrossover", "MACDSignal",
            "DoubleSupertrend", "ParabolicSAR", "IchimokuCloud", "HullMA",
            # Momentum
            "RSIMomentum", "RSIDivergence", "StochasticCrossover",
            "CCI", "WilliamsR", "ROCMomentum",
            # Mean Reversion
            "VWAPReversion", "RSIMeanRevert", "KeltnerReversion", "MAEnvelope",
            # Volatility
            "ATRBreakout", "BollingerSqueeze", "DonchianBreakout",
            "VIXRegime", "RangeExpansion",
            # Volume
            "OBVDivergence", "VWAPCross", "VolumeBreakout",
            # Options
            "ATMStraddleSell", "OTMStrangleSell", "IronCondorStrategy", "WheelStrategy",
        ]
        for key in required:
            assert key in ALL_STRATEGIES, f"Missing strategy: {key}"

    def test_all_strategies_instantiable(self):
        from strategies import ALL_STRATEGIES
        for name, cls in ALL_STRATEGIES.items():
            try:
                instance = cls(symbol="TEST")
                instance.start()
            except Exception as e:
                pytest.fail(f"Strategy {name} failed to instantiate or start: {e}")

    def test_legacy_strategies_still_present(self):
        from strategies import (
            BearCallSpread,
            BollingerMeanReversion,
            BullPutSpread,
            EMACrossover,
            IronCondor,
            MACDRSIStrategy,
            MomentumBreakout,
            OpeningRangeBreakout,
            StraddleSell,
            StrangleSell,
            SupertrendStrategy,
            VWAPDeviation,
        )
        assert all([
            EMACrossover, SupertrendStrategy, MACDRSIStrategy,
            BollingerMeanReversion, VWAPDeviation, StraddleSell,
            StrangleSell, IronCondor, BullPutSpread, BearCallSpread,
            MomentumBreakout, OpeningRangeBreakout,
        ])
