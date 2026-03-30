"""Tests for the 43 new backtest strategies (batch 2).

Each test:
  - Instantiates the strategy with default parameters.
  - Calls on_bar() with synthetic OHLCV bars.
  - Asserts no exception is raised and generate_orders() returns a list.

All tests use only synthetic data; no external broker/network dependency.
"""

from __future__ import annotations

import os
import sys
from typing import Any


# ---------------------------------------------------------------------------
# Path bootstrap (mirrors test_strategies_new.py)
# ---------------------------------------------------------------------------
_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_test_dir, "..", "..", ".."))
sys.path.insert(0, os.path.join(_test_dir, "..", "..", "core", "src"))
sys.path.insert(0, os.path.join(_test_dir, "..", "..", "engine", "src"))
sys.path.insert(0, os.path.join(_test_dir, "..", "src"))


# ---------------------------------------------------------------------------
# Synthetic bar factories
# ---------------------------------------------------------------------------

def _make_bars(
    n: int = 100,
    start: float = 100.0,
    trend: float = 0.05,
    vol: float = 0.5,
    seed: int = 42,
    session_time: str = "10:00",
) -> list[Any]:
    """Return OHLCV model instances with n bars."""
    import random
    from packages.core.src.models import OHLCV
    random.seed(seed)
    bars: list[OHLCV] = []
    price = start
    for i in range(n):
        noise = random.uniform(-vol, vol)
        price = max(1.0, price + trend + noise)
        h = price + abs(noise) * 0.4
        lo = max(0.1, price - abs(noise) * 0.4)
        c = max(lo, min(h, price + random.uniform(-vol * 0.3, vol * 0.3)))
        bars.append(OHLCV(
            timestamp=f"2025-01-{(i % 28) + 1:02d} {session_time}:00",
            open=round(price, 2),
            high=round(h, 2),
            low=round(lo, 2),
            close=round(c, 2),
            volume=10000 + i * 100,
            oi=0,
        ))
    return bars


def _intraday_bars(n: int = 80) -> list[Any]:
    """Return OHLCV model instances with intraday timestamps starting 09:15."""
    import random
    from packages.core.src.models import OHLCV
    random.seed(13)
    bars: list[OHLCV] = []
    price = 19500.0
    hour = 9
    minute = 15
    for i in range(n):
        noise = random.uniform(-20, 20)
        price = max(1.0, price + noise)
        h = price + abs(noise) * 0.3
        lo = max(0.1, price - abs(noise) * 0.3)
        c = max(lo, min(h, price + random.uniform(-5, 5)))
        ts = f"2025-01-01 {hour:02d}:{minute:02d}:00"
        bars.append(OHLCV(
            timestamp=ts,
            open=round(price, 2),
            high=round(h, 2),
            low=round(lo, 2),
            close=round(c, 2),
            volume=5000 + i * 50,
            oi=0,
        ))
        minute += 1
        if minute >= 60:
            minute = 0
            hour += 1
        if hour >= 16:
            hour = 9
            minute = 15
    return bars


def _run_strategy(strategy: Any, bars: list[Any], **kwargs: Any) -> list[Any]:
    """Feed bars through a strategy and collect all orders."""
    all_orders: list[Any] = []
    for bar in bars:
        strategy.on_bar(bar, **kwargs)
        all_orders.extend(strategy.generate_orders())
    return all_orders


# ===========================================================================
# Multi-Timeframe tests
# ===========================================================================

def test_mtf_rsi_trend_instantiates_and_runs() -> None:
    from strategies.mtf_rsi_trend import MTFRSITrend
    s = MTFRSITrend(symbol="NIFTY")
    bars = _make_bars(60)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)
    assert "MTFRSITrend" in s.name or "RSI" in s.name or s.name == "MTFRSITrend"


def test_mtf_rsi_trend_with_htf() -> None:
    from strategies.mtf_rsi_trend import MTFRSITrend
    s = MTFRSITrend(symbol="NIFTY")
    bars = _make_bars(60)
    htf = _make_bars(60, start=100.0, seed=99)
    for bar in bars:
        s.on_bar(bar, bars_htf=htf)
    orders = s.generate_orders()
    assert isinstance(orders, list)


def test_mtf_ema_breakout_instantiates_and_runs() -> None:
    from strategies.mtf_ema_breakout import MTFEMABreakout
    s = MTFEMABreakout(symbol="BANKNIFTY")
    bars = _make_bars(80)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_mtf_vwap_scalp_instantiates_and_runs() -> None:
    from strategies.mtf_vwap_scalp import MTFVWAPScalp
    s = MTFVWAPScalp(symbol="NIFTY")
    bars = _intraday_bars(60)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_mtf_supertrend_confluence_instantiates_and_runs() -> None:
    from strategies.mtf_supertrend_confluence import MTFSupertrendConfluence
    s = MTFSupertrendConfluence(symbol="NIFTY")
    bars = _make_bars(80)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_mtf_macd_momentum_instantiates_and_runs() -> None:
    from strategies.mtf_macd_momentum import MTFMACDMomentum
    s = MTFMACDMomentum(symbol="NIFTY")
    bars = _make_bars(80)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


# ===========================================================================
# Pairs / Statistical tests
# ===========================================================================

def test_pairs_ratio_reversion_instantiates_and_runs() -> None:
    from strategies.pairs_ratio_reversion import PairsRatioReversion
    s = PairsRatioReversion(symbol="HDFCBANK", symbol_b="ICICIBANK")
    bars_a = _make_bars(100)
    bars_b = _make_bars(100, start=105.0, seed=77)
    for bar, bar_b in zip(bars_a, bars_b):
        s.on_bar(bar, bars_b=[bar_b])
    orders = s.generate_orders()
    assert isinstance(orders, list)


def test_pairs_cointegration_instantiates_and_runs() -> None:
    from strategies.pairs_cointegration import PairsCointegration
    s = PairsCointegration(symbol="RELIANCE")
    bars_a = _make_bars(100)
    bars_b = _make_bars(100, start=200.0, seed=55)
    for bar, bar_b in zip(bars_a, bars_b):
        s.on_bar(bar, bars_b=[bar_b])
    orders = s.generate_orders()
    assert isinstance(orders, list)


def test_stat_regime_hmm_instantiates_and_runs() -> None:
    from strategies.stat_regime_hmm import StatRegimeHMM
    s = StatRegimeHMM(symbol="NIFTY", warmup=30, lookback=50)
    bars = _make_bars(80)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_stat_kalman_filter_instantiates_and_runs() -> None:
    from strategies.stat_kalman_filter import StatKalmanFilter
    s = StatKalmanFilter(symbol="NIFTY")
    bars_a = _make_bars(80)
    bars_b = _make_bars(80, start=105.0, seed=33)
    for i, bar in enumerate(bars_a):
        s.on_bar(bar, bars_b=bars_b[:i + 1])
    orders = s.generate_orders()
    assert isinstance(orders, list)


# ===========================================================================
# Intraday India-specific tests
# ===========================================================================

def test_intraday_orb_atr_instantiates_and_runs() -> None:
    from strategies.intraday_orb_atr import IntradayORBATR
    s = IntradayORBATR(symbol="NIFTY", orb_minutes=3)
    bars = _intraday_bars(80)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_intraday_gap_fill_instantiates_and_runs() -> None:
    from strategies.intraday_gap_fill import IntradayGapFill
    s = IntradayGapFill(symbol="NIFTY")
    bars = _intraday_bars(80)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_intraday_first_candle_instantiates_and_runs() -> None:
    from strategies.intraday_first_candle import IntradayFirstCandle
    s = IntradayFirstCandle(symbol="NIFTY")
    bars = _intraday_bars(80)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_intraday_vwap_bounce_instantiates_and_runs() -> None:
    from strategies.intraday_vwap_bounce import IntradayVWAPBounce
    s = IntradayVWAPBounce(symbol="NIFTY")
    bars = _intraday_bars(80)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_intraday_expiry_day_instantiates_and_runs() -> None:
    from strategies.intraday_expiry_day import IntradayExpiryDay
    s = IntradayExpiryDay(symbol="NIFTY")
    bars = _intraday_bars(80)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_intraday_pre_market_instantiates_and_runs() -> None:
    from strategies.intraday_pre_market import IntradayPreMarket
    s = IntradayPreMarket(symbol="NIFTY")
    s.set_premarket_data(oi_change_pct=8.0, delivery_pct=60.0)
    bars = _intraday_bars(80)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


# ===========================================================================
# Options Advanced tests
# ===========================================================================

def test_options_jade_lizard_instantiates_and_runs() -> None:
    from strategies.options_jade_lizard import OptionsJadeLizard
    s = OptionsJadeLizard(symbol="NIFTY25JAN19500CE")
    bars = _intraday_bars(80)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_options_ratio_spread_instantiates_and_runs() -> None:
    from strategies.options_ratio_spread import OptionsRatioSpread
    s = OptionsRatioSpread(symbol="NIFTY_RATIO")
    bars = _intraday_bars(80)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_options_calendar_spread_instantiates_and_runs() -> None:
    from strategies.options_calendar_spread import OptionsCalendarSpread
    s = OptionsCalendarSpread(symbol="NIFTY_CAL")
    bars = _intraday_bars(80)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_options_butterfly_instantiates_and_runs() -> None:
    from strategies.options_butterfly import OptionsButterfly, OptionsIronButterfly
    s1 = OptionsButterfly(symbol="NIFTY_BFLY")
    s2 = OptionsIronButterfly(symbol="NIFTY_IBFLY")
    bars = _intraday_bars(80)
    orders1 = _run_strategy(s1, bars)
    orders2 = _run_strategy(s2, bars)
    assert isinstance(orders1, list)
    assert isinstance(orders2, list)


def test_options_collar_instantiates_and_runs() -> None:
    from strategies.options_collar import OptionsCollar
    s = OptionsCollar(symbol="RELIANCE")
    bars = _intraday_bars(60)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


# ===========================================================================
# Event-Driven tests
# ===========================================================================

def test_event_earnings_instantiates_and_runs() -> None:
    from strategies.event_earnings import EventEarnings
    s = EventEarnings(symbol="TCS")
    bars = _make_bars(60)
    s.set_event_date(bar_index=40)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_event_rbi_policy_instantiates_and_runs() -> None:
    from strategies.event_rbi_policy import EventRBIPolicy
    s = EventRBIPolicy(symbol="NIFTY")
    bars = _make_bars(60)
    s.set_event(bar_index=30, rate_bias=1)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_event_expiry_oi_instantiates_and_runs() -> None:
    from strategies.event_expiry_oi import EventExpiryOI
    s = EventExpiryOI(symbol="NIFTY")
    bars = _make_bars(60)
    s.set_max_pain(max_pain_level=105.0, expiry_bar_idx=55)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_event_fii_flow_instantiates_and_runs() -> None:
    from strategies.event_fii_flow import EventFIIFlow
    s = EventFIIFlow(symbol="NIFTY")
    s.set_flow_data(fii_net_cr=1200.0, dii_net_cr=300.0)
    bars = _intraday_bars(60)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


# ===========================================================================
# Crypto tests
# ===========================================================================

def test_crypto_funding_arb_instantiates_and_runs() -> None:
    from strategies.crypto_funding_arb import CryptoFundingArb
    s = CryptoFundingArb(symbol="BTCUSDT-PERP")
    bars = _make_bars(60)
    for i, bar in enumerate(bars):
        s.set_funding_rate(0.015 if i % 8 < 4 else -0.005)
        s.on_bar(bar)
    orders = s.generate_orders()
    assert isinstance(orders, list)


def test_crypto_grid_instantiates_and_runs() -> None:
    from strategies.crypto_grid import CryptoGrid
    s = CryptoGrid(symbol="ETHUSDT", grid_levels=3, recalc_bars=10)
    bars = _make_bars(80)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_crypto_dca_momentum_instantiates_and_runs() -> None:
    from strategies.crypto_dca_momentum import CryptoDCAMomentum
    s = CryptoDCAMomentum(symbol="BTCUSDT", dca_interval=10)
    bars = _make_bars(80)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_crypto_breakout_volume_instantiates_and_runs() -> None:
    from strategies.crypto_breakout_volume import CryptoBreakoutVolume
    s = CryptoBreakoutVolume(symbol="SOLUSDT", period=10, obv_ema_period=5)
    bars = _make_bars(80)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


# ===========================================================================
# Commodity tests
# ===========================================================================

def test_commodity_seasonal_instantiates_and_runs() -> None:
    from strategies.commodity_seasonal import CommoditySeasonal
    s = CommoditySeasonal(symbol="GOLD", bullish_months={10, 11, 12, 1, 2})
    bars = _make_bars(80)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_commodity_seasonal_with_seasonal_data() -> None:
    from strategies.commodity_seasonal import CommoditySeasonal
    seasonal = {1: 1, 2: 1, 3: 0, 4: -1, 5: -1, 6: 0,
                7: 1, 8: 1, 9: 0, 10: 1, 11: 1, 12: 1}
    s = CommoditySeasonal(symbol="CRUDEOIL", seasonal_data=seasonal)
    bars = _make_bars(60)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_commodity_spread_instantiates_and_runs() -> None:
    from strategies.commodity_spread import CommoditySpread
    s = CommoditySpread(symbol="CRUDEOIL-NEAR")
    bars_near = _make_bars(80)
    bars_far = _make_bars(80, start=102.0, seed=66)
    for bar, bar_f in zip(bars_near, bars_far):
        s.on_bar(bar, bars_far=[bar_f])
    orders = s.generate_orders()
    assert isinstance(orders, list)


def test_commodity_inventory_instantiates_and_runs() -> None:
    from strategies.commodity_inventory import CommodityInventory
    s = CommodityInventory(symbol="CRUDEOIL")
    bars = _make_bars(60)
    s.set_inventory_data(actual_mbbl=-2.5, expected_mbbl=1.0, event_bar_idx=20)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


# ===========================================================================
# Machine Learning tests
# ===========================================================================

def test_ml_feature_signal_instantiates_and_runs() -> None:
    from strategies.ml_feature_signal import MLFeatureSignal
    s = MLFeatureSignal(symbol="NIFTY", warmup=30)
    bars = _make_bars(80)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_ml_feature_signal_name() -> None:
    from strategies.ml_feature_signal import MLFeatureSignal
    s = MLFeatureSignal()
    assert "LightGBM" in s.name or "ML" in s.name


def test_ml_regime_classifier_instantiates_and_runs() -> None:
    from strategies.ml_regime_classifier import MLRegimeClassifier
    s = MLRegimeClassifier(symbol="NIFTY", warmup=30, retrain_interval=30)
    bars = _make_bars(80)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_ml_ensemble_voter_instantiates_and_runs() -> None:
    from strategies.ml_ensemble_voter import MLEnsembleVoter
    s = MLEnsembleVoter(symbol="NIFTY", vote_threshold=2)
    bars = _make_bars(80)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_ml_adaptive_params_instantiates_and_runs() -> None:
    from strategies.ml_adaptive_params import MLAdaptiveParams
    s = MLAdaptiveParams(symbol="NIFTY", adapt_interval=30)
    bars = _make_bars(80)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


# ===========================================================================
# Portfolio / Risk tests
# ===========================================================================

def test_portfolio_equal_weight_instantiates_and_runs() -> None:
    from strategies.portfolio_equal_weight import PortfolioEqualWeight
    s = PortfolioEqualWeight(symbol="NIFTY", rebalance_bars=10)
    bars = _make_bars(60)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)
    assert any(o.action == "BUY" for o in orders)


def test_portfolio_risk_parity_instantiates_and_runs() -> None:
    from strategies.portfolio_risk_parity import PortfolioRiskParity
    s = PortfolioRiskParity(symbol="NIFTY", rebalance_bars=10)
    bars = _make_bars(60)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_portfolio_momentum_rotation_instantiates_and_runs() -> None:
    from strategies.portfolio_momentum_rotation import PortfolioMomentumRotation
    s = PortfolioMomentumRotation(symbol="NIFTY", rebalance_bars=10, momentum_period=10)
    bars = _make_bars(60)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_portfolio_min_variance_instantiates_and_runs() -> None:
    from strategies.portfolio_min_variance import PortfolioMinVariance
    s = PortfolioMinVariance(symbol="NIFTY", rebalance_bars=10)
    bars = _make_bars(60)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


# ===========================================================================
# Scalping tests
# ===========================================================================

def test_scalp_tape_reading_instantiates_and_runs() -> None:
    from strategies.scalp_tape_reading import ScalpTapeReading
    s = ScalpTapeReading(symbol="NIFTY", lookback=3)
    bars = _intraday_bars(60)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_scalp_level2_squeeze_instantiates_and_runs() -> None:
    from strategies.scalp_level2_squeeze import ScalpLevel2Squeeze
    s = ScalpLevel2Squeeze(symbol="NIFTY", atr_period=5)
    bars = _intraday_bars(60)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_scalp_tick_momentum_instantiates_and_runs() -> None:
    from strategies.scalp_tick_momentum import ScalpTickMomentum
    s = ScalpTickMomentum(symbol="NIFTY", consec_bars=2)
    bars = _intraday_bars(60)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


def test_scalp_spread_capture_instantiates_and_runs() -> None:
    from strategies.scalp_spread_capture import ScalpSpreadCapture
    s = ScalpSpreadCapture(symbol="NIFTY", mid_period=3, atr_period=5)
    bars = _intraday_bars(60)
    orders = _run_strategy(s, bars)
    assert isinstance(orders, list)


# ===========================================================================
# Registry test — all new strategies must appear in ALL_STRATEGIES
# ===========================================================================

def test_all_strategies_registry_contains_new_batch() -> None:
    from strategies import ALL_STRATEGIES
    expected_keys = [
        "MTFRSITrend", "MTFEMABreakout", "MTFVWAPScalp",
        "MTFSupertrendConfluence", "MTFMACDMomentum",
        "PairsRatioReversion", "PairsCointegration",
        "StatRegimeHMM", "StatKalmanFilter",
        "IntradayORBATR", "IntradayGapFill", "IntradayFirstCandle",
        "IntradayVWAPBounce", "IntradayExpiryDay", "IntradayPreMarket",
        "OptionsJadeLizard", "OptionsRatioSpread", "OptionsCalendarSpread",
        "OptionsButterfly", "OptionsIronButterfly", "OptionsCollar",
        "EventEarnings", "EventRBIPolicy", "EventExpiryOI", "EventFIIFlow",
        "CryptoFundingArb", "CryptoGrid", "CryptoDCAMomentum", "CryptoBreakoutVolume",
        "CommoditySeasonal", "CommoditySpread", "CommodityInventory",
        "MLFeatureSignal", "MLRegimeClassifier", "MLEnsembleVoter", "MLAdaptiveParams",
        "PortfolioEqualWeight", "PortfolioRiskParity",
        "PortfolioMomentumRotation", "PortfolioMinVariance",
        "ScalpTapeReading", "ScalpLevel2Squeeze",
        "ScalpTickMomentum", "ScalpSpreadCapture",
    ]
    for key in expected_keys:
        assert key in ALL_STRATEGIES, f"Missing from ALL_STRATEGIES: {key}"
    # Total should be at or near 100
    assert len(ALL_STRATEGIES) >= 100, (
        f"Expected ~100 total strategies, got {len(ALL_STRATEGIES)}"
    )


def test_all_new_strategies_instantiate() -> None:
    """Instantiate every new strategy via the registry with default params."""
    from strategies import ALL_STRATEGIES
    new_keys = [
        "MTFRSITrend", "MTFEMABreakout", "MTFVWAPScalp",
        "MTFSupertrendConfluence", "MTFMACDMomentum",
        "PairsRatioReversion", "PairsCointegration",
        "StatRegimeHMM", "StatKalmanFilter",
        "IntradayORBATR", "IntradayGapFill", "IntradayFirstCandle",
        "IntradayVWAPBounce", "IntradayExpiryDay", "IntradayPreMarket",
        "OptionsJadeLizard", "OptionsRatioSpread", "OptionsCalendarSpread",
        "OptionsButterfly", "OptionsIronButterfly", "OptionsCollar",
        "EventEarnings", "EventRBIPolicy", "EventExpiryOI", "EventFIIFlow",
        "CryptoFundingArb", "CryptoGrid", "CryptoDCAMomentum", "CryptoBreakoutVolume",
        "CommoditySeasonal", "CommoditySpread", "CommodityInventory",
        "MLFeatureSignal", "MLRegimeClassifier", "MLEnsembleVoter", "MLAdaptiveParams",
        "PortfolioEqualWeight", "PortfolioRiskParity",
        "PortfolioMomentumRotation", "PortfolioMinVariance",
        "ScalpTapeReading", "ScalpLevel2Squeeze",
        "ScalpTickMomentum", "ScalpSpreadCapture",
    ]
    for key in new_keys:
        cls = ALL_STRATEGIES[key]
        instance = cls(symbol="TEST")
        assert instance is not None


def test_all_new_strategies_on_bar_no_exception() -> None:
    """Call on_bar() on every new strategy with a synthetic bar."""
    from packages.core.src.models import OHLCV
    from strategies import ALL_STRATEGIES
    new_keys = [
        "MTFRSITrend", "MTFEMABreakout", "MTFVWAPScalp",
        "MTFSupertrendConfluence", "MTFMACDMomentum",
        "PairsRatioReversion", "PairsCointegration",
        "StatRegimeHMM", "StatKalmanFilter",
        "IntradayORBATR", "IntradayGapFill", "IntradayFirstCandle",
        "IntradayVWAPBounce", "IntradayExpiryDay", "IntradayPreMarket",
        "OptionsJadeLizard", "OptionsRatioSpread", "OptionsCalendarSpread",
        "OptionsButterfly", "OptionsIronButterfly", "OptionsCollar",
        "EventEarnings", "EventRBIPolicy", "EventExpiryOI", "EventFIIFlow",
        "CryptoFundingArb", "CryptoGrid", "CryptoDCAMomentum", "CryptoBreakoutVolume",
        "CommoditySeasonal", "CommoditySpread", "CommodityInventory",
        "MLFeatureSignal", "MLRegimeClassifier", "MLEnsembleVoter", "MLAdaptiveParams",
        "PortfolioEqualWeight", "PortfolioRiskParity",
        "PortfolioMomentumRotation", "PortfolioMinVariance",
        "ScalpTapeReading", "ScalpLevel2Squeeze",
        "ScalpTickMomentum", "ScalpSpreadCapture",
    ]
    bar = OHLCV(
        timestamp="2025-01-01 10:00:00",
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=10000,
        oi=0,
    )
    for key in new_keys:
        cls = ALL_STRATEGIES[key]
        instance = cls(symbol="TEST")
        instance.on_bar(bar)
        orders = instance.generate_orders()
        assert isinstance(orders, list), f"{key}: generate_orders() did not return list"
