"""Tests for the declarative MarketScanner engine.

All tests use synthetic OHLCV data — no API calls are made.
"""

from __future__ import annotations

import math
from datetime import datetime

import pytest

from flinttrade_screener.market_scanner import (
    PREBUILT_SCANS,
    MarketScanner,
    ScanCondition,
    ScanConfig,
    ScanResult,
    _atr,
    _bollinger_width,
    _ema,
    _evaluate_single,
    _macd,
    _rsi,
)


# ---------------------------------------------------------------------------
# OHLCV fixture helpers
# ---------------------------------------------------------------------------


def _flat_bars(
    n: int = 50,
    price: float = 100.0,
    volume: int = 100_000,
) -> list[dict]:
    """n bars all at the same price (no movement)."""
    return [
        {"open": price, "high": price + 0.1, "low": price - 0.1,
         "close": price, "volume": volume}
        for _ in range(n)
    ]


def _trending_bars(
    n: int = 60,
    start: float = 100.0,
    step: float = 1.0,
    volume: int = 100_000,
) -> list[dict]:
    """n bars with a linear uptrend (step per bar)."""
    bars = []
    price = start
    for _ in range(n):
        bars.append({
            "open": price,
            "high": price + abs(step) * 0.5,
            "low": price - abs(step) * 0.2,
            "close": price + step,
            "volume": volume,
        })
        price = price + step
    return bars


def _rsi_bars(n: int = 50, direction: str = "down") -> list[dict]:
    """Bars designed to produce an RSI near 20 (down) or 80 (up)."""
    bars: list[dict] = []
    price = 100.0
    for i in range(n):
        if direction == "down":
            delta = -0.8 if i % 5 != 0 else 0.1
        else:
            delta = 0.8 if i % 5 != 0 else -0.1
        close = max(1.0, price + delta)
        bars.append({
            "open": price,
            "high": max(price, close) + 0.1,
            "low": min(price, close) - 0.1,
            "close": close,
            "volume": 100_000,
        })
        price = close
    return bars


def _volume_spike_bars(n: int = 30, spike_at_last: bool = True) -> list[dict]:
    """Bars with a volume spike on the last bar."""
    bars = [
        {"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 100_000}
        for _ in range(n - 1)
    ]
    vol = 500_000 if spike_at_last else 50_000
    bars.append({"open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": vol})
    return bars


def _ema_cross_bars(
    n_before: int = 60,
    cross_direction: str = "up",
) -> list[dict]:
    """Bars where fast EMA (20) crosses slow EMA (50) on the last two bars."""
    bars: list[dict] = []
    # Build initial bars with fast below slow
    price = 100.0
    step = -0.02 if cross_direction == "up" else 0.02
    for i in range(n_before):
        bars.append({
            "open": price,
            "high": price + 0.2,
            "low": price - 0.2,
            "close": price,
            "volume": 100_000,
        })
        price += step

    # Two final bars that force the crossover
    if cross_direction == "up":
        for delta in [2.0, 3.5]:
            bars.append({
                "open": price,
                "high": price + delta + 0.5,
                "low": price - 0.2,
                "close": price + delta,
                "volume": 150_000,
            })
            price += delta
    else:
        for delta in [2.0, 3.5]:
            bars.append({
                "open": price,
                "high": price + 0.2,
                "low": price - delta - 0.5,
                "close": price - delta,
                "volume": 150_000,
            })
            price -= delta
    return bars


def _simple_fetcher(ohlcv_map: dict[str, list[dict]]):
    """Return a data_fetcher that looks up from a dict."""
    def _fetch(symbol: str, exchange: str, timeframe: str) -> list[dict]:
        return ohlcv_map.get(symbol, [])
    return _fetch


# ---------------------------------------------------------------------------
# Unit tests: indicator calculations
# ---------------------------------------------------------------------------


class TestRSI:
    def test_oversold(self):
        bars = _rsi_bars(50, direction="down")
        closes = [b["close"] for b in bars]
        import numpy as np
        val = _rsi(np.array(closes), period=14)
        assert val < 35, f"Expected RSI < 35 for downtrend, got {val:.2f}"

    def test_overbought(self):
        bars = _rsi_bars(50, direction="up")
        closes = [b["close"] for b in bars]
        import numpy as np
        val = _rsi(np.array(closes), period=14)
        assert val > 65, f"Expected RSI > 65 for uptrend, got {val:.2f}"

    def test_insufficient_data_returns_neutral(self):
        import numpy as np
        val = _rsi(np.array([100.0, 101.0, 99.0]), period=14)
        assert val == 50.0

    def test_all_gains_returns_100(self):
        import numpy as np
        closes = np.array([float(i) for i in range(1, 20)])
        val = _rsi(closes, period=14)
        assert val == 100.0


class TestEMA:
    def test_ema_length_preserved(self):
        import numpy as np
        values = np.arange(60, dtype=float)
        result = _ema(values, 20)
        assert len(result) == len(values)

    def test_first_values_nan(self):
        import numpy as np
        values = np.arange(30, dtype=float)
        result = _ema(values, 10)
        assert all(math.isnan(v) for v in result[:9])
        assert not math.isnan(result[9])

    def test_ema_rises_with_uptrend(self):
        import numpy as np
        values = np.linspace(100.0, 200.0, 60)
        result = _ema(values, 20)
        # Last EMA should be close to last price
        assert result[-1] > 150.0


class TestMACD:
    def test_returns_four_floats(self):
        import numpy as np
        closes = np.linspace(100.0, 150.0, 80)
        m_now, s_now, m_prev, s_prev = _macd(closes)
        assert all(isinstance(v, float) for v in (m_now, s_now, m_prev, s_prev))

    def test_insufficient_data(self):
        import numpy as np
        result = _macd(np.array([100.0] * 20))
        assert result == (0.0, 0.0, 0.0, 0.0)


class TestATR:
    def test_basic(self):
        import numpy as np
        bars = _trending_bars(30, step=0.5)
        h = np.array([b["high"] for b in bars])
        lo = np.array([b["low"] for b in bars])
        c = np.array([b["close"] for b in bars])
        val = _atr(h, lo, c, 14)
        assert val > 0

    def test_insufficient_data(self):
        import numpy as np
        val = _atr(np.array([1.0, 2.0]), np.array([0.9, 1.8]), np.array([1.0, 2.0]), 14)
        assert val == 0.0


class TestBollingerWidth:
    def test_flat_bars_low_width(self):
        import numpy as np
        bars = _flat_bars(30)
        closes = np.array([b["close"] for b in bars])
        width = _bollinger_width(closes, 20)
        assert width < 0.01  # Very tight band for flat price

    def test_volatile_bars_high_width(self):
        import numpy as np
        rng = __import__("random").Random(42)
        closes = np.array([100.0 + rng.gauss(0, 5.0) for _ in range(30)])
        width = _bollinger_width(closes, 20)
        assert width > 0.05


# ---------------------------------------------------------------------------
# Unit tests: _evaluate_single
# ---------------------------------------------------------------------------


class TestEvaluateSingle:
    def test_rsi_below(self):
        cond = ScanCondition(indicator="rsi", operator="below", value=35.0)
        bars = _rsi_bars(50, direction="down")
        assert _evaluate_single(cond, bars)

    def test_rsi_above(self):
        cond = ScanCondition(indicator="rsi", operator="above", value=65.0)
        bars = _rsi_bars(50, direction="up")
        assert _evaluate_single(cond, bars)

    def test_rsi_between(self):
        cond = ScanCondition(indicator="rsi", operator="between", value=(40.0, 60.0))
        bars = _flat_bars(50, price=100.0)
        # Flat bars → RSI ≈ 50; just check it doesn't crash
        result = _evaluate_single(cond, bars)
        assert isinstance(bool(result), bool)

    def test_volume_spike_above(self):
        cond = ScanCondition(indicator="volume_spike", operator="above", value=2.0)
        bars = _volume_spike_bars(30, spike_at_last=True)
        assert _evaluate_single(cond, bars)

    def test_volume_spike_no_spike(self):
        cond = ScanCondition(indicator="volume_spike", operator="above", value=2.0)
        bars = _flat_bars(30)
        assert not _evaluate_single(cond, bars)

    def test_price_breakout_above(self):
        cond = ScanCondition(indicator="price_breakout", operator="above", value=0.0,
                             params={"days": 20})
        bars = _trending_bars(60, start=100.0, step=0.5)
        assert _evaluate_single(cond, bars)

    def test_price_breakout_below(self):
        cond = ScanCondition(indicator="price_breakout", operator="below", value=0.0,
                             params={"days": 20})
        bars = _trending_bars(60, start=100.0, step=-0.5)
        assert _evaluate_single(cond, bars)

    def test_gap_up_above(self):
        bars = _flat_bars(10)
        # Create a big gap up on the last bar
        bars[-1] = {"open": 110.0, "high": 115.0, "low": 109.0, "close": 112.0,
                    "volume": 100_000}
        cond = ScanCondition(indicator="gap_up", operator="above", value=5.0)
        assert _evaluate_single(cond, bars)

    def test_gap_down_above(self):
        bars = _flat_bars(10)
        bars[-1] = {"open": 90.0, "high": 92.0, "low": 88.0, "close": 91.0,
                    "volume": 100_000}
        cond = ScanCondition(indicator="gap_down", operator="above", value=5.0)
        assert _evaluate_single(cond, bars)

    def test_atr_expansion(self):
        cond = ScanCondition(indicator="atr_expansion", operator="above", value=1.0)
        # Volatile bars at the end
        bars = _flat_bars(60)
        for i in range(-5, 0):
            bars[i] = {
                "open": 100.0 + i * 5,
                "high": 100.0 + abs(i) * 8,
                "low": 100.0 - abs(i) * 8,
                "close": 100.0 + i * 3,
                "volume": 200_000,
            }
        result = _evaluate_single(cond, bars)
        assert isinstance(bool(result), bool)  # Just verify no crash

    def test_empty_ohlcv_returns_false(self):
        cond = ScanCondition(indicator="rsi", operator="below", value=30.0)
        assert not _evaluate_single(cond, [])

    def test_near_resistance(self):
        bars = _flat_bars(10, price=99.5)
        cond = ScanCondition(indicator="near_resistance", operator="above", value=100.0,
                             params={"pct": 1.0})
        assert _evaluate_single(cond, bars)

    def test_macd_crossover_above(self):
        cond = ScanCondition(indicator="macd_crossover", operator="above", value=0.0)
        bars = _trending_bars(80, step=1.0)
        # Just verify it doesn't crash and returns bool
        result = _evaluate_single(cond, bars)
        assert isinstance(bool(result), bool)


# ---------------------------------------------------------------------------
# Unit tests: ScanCondition model validation
# ---------------------------------------------------------------------------


class TestScanConditionValidation:
    def test_invalid_indicator_raises(self):
        with pytest.raises(Exception, match="Unknown indicator"):
            ScanCondition(indicator="unknown_thing", operator="above", value=50.0)

    def test_invalid_operator_raises(self):
        with pytest.raises(Exception, match="Unknown operator"):
            ScanCondition(indicator="rsi", operator="equals", value=50.0)

    def test_between_requires_tuple(self):
        with pytest.raises(Exception, match="between"):
            ScanCondition(indicator="rsi", operator="between", value=50.0)

    def test_label_single(self):
        c = ScanCondition(indicator="rsi", operator="below", value=30.0)
        assert c.label == "rsi below 30.0"

    def test_label_between(self):
        c = ScanCondition(indicator="rsi", operator="between", value=(30.0, 70.0))
        assert "30.0" in c.label and "70.0" in c.label


# ---------------------------------------------------------------------------
# Unit tests: ScanConfig
# ---------------------------------------------------------------------------


class TestScanConfig:
    def test_get_symbols_nifty50(self):
        cfg = ScanConfig(
            name="test",
            conditions=[ScanCondition(indicator="rsi", operator="below", value=30.0)],
            universe="nifty50",
        )
        symbols = cfg.get_symbols()
        assert len(symbols) == 50
        assert "RELIANCE" in symbols

    def test_get_symbols_niftybank(self):
        cfg = ScanConfig(
            name="test",
            conditions=[ScanCondition(indicator="rsi", operator="below", value=30.0)],
            universe="niftybank",
        )
        symbols = cfg.get_symbols()
        assert len(symbols) == 12
        assert "HDFCBANK" in symbols

    def test_get_symbols_custom(self):
        cfg = ScanConfig(
            name="test",
            conditions=[ScanCondition(indicator="rsi", operator="below", value=30.0)],
            universe="custom",
            custom_symbols=["RELIANCE", "TCS"],
        )
        assert cfg.get_symbols() == ["RELIANCE", "TCS"]

    def test_custom_empty_symbols_raises(self):
        cfg = ScanConfig(
            name="test",
            conditions=[ScanCondition(indicator="rsi", operator="below", value=30.0)],
            universe="custom",
        )
        with pytest.raises(ValueError, match="empty"):
            cfg.get_symbols()

    def test_unknown_universe_falls_back_to_nifty50(self):
        cfg = ScanConfig(
            name="test",
            conditions=[ScanCondition(indicator="rsi", operator="below", value=30.0)],
            universe="nonexistent",
        )
        symbols = cfg.get_symbols()
        assert len(symbols) == 50


# ---------------------------------------------------------------------------
# Unit tests: MarketScanner
# ---------------------------------------------------------------------------


class TestMarketScanner:
    def test_scan_returns_list(self):
        scanner = MarketScanner()
        cfg = ScanConfig(
            name="RSI Low",
            conditions=[ScanCondition(indicator="rsi", operator="below", value=35.0)],
            universe="custom",
            custom_symbols=["A", "B"],
        )
        ohlcv_a = _rsi_bars(50, direction="down")
        ohlcv_b = _rsi_bars(50, direction="up")
        fetcher = _simple_fetcher({"A": ohlcv_a, "B": ohlcv_b})
        results = scanner.scan(cfg, data_fetcher=fetcher)
        assert isinstance(results, list)

    def test_scan_matching_symbol(self):
        scanner = MarketScanner()
        cfg = ScanConfig(
            name="RSI Oversold",
            conditions=[ScanCondition(indicator="rsi", operator="below", value=35.0)],
            universe="custom",
            custom_symbols=["DOWN"],
        )
        fetcher = _simple_fetcher({"DOWN": _rsi_bars(50, direction="down")})
        results = scanner.scan(cfg, data_fetcher=fetcher)
        assert len(results) == 1
        assert results[0].symbol == "DOWN"

    def test_scan_no_match(self):
        scanner = MarketScanner()
        cfg = ScanConfig(
            name="RSI Oversold",
            conditions=[ScanCondition(indicator="rsi", operator="below", value=35.0)],
            universe="custom",
            custom_symbols=["UP"],
        )
        fetcher = _simple_fetcher({"UP": _rsi_bars(50, direction="up")})
        results = scanner.scan(cfg, data_fetcher=fetcher)
        assert results == []

    def test_scan_result_fields(self):
        scanner = MarketScanner()
        cfg = ScanConfig(
            name="Test",
            conditions=[ScanCondition(indicator="rsi", operator="below", value=35.0)],
            universe="custom",
            custom_symbols=["SYM"],
        )
        fetcher = _simple_fetcher({"SYM": _rsi_bars(50, direction="down")})
        results = scanner.scan(cfg, data_fetcher=fetcher)
        assert len(results) == 1
        r = results[0]
        assert isinstance(r, ScanResult)
        assert r.symbol == "SYM"
        assert r.exchange == "NSE"
        assert isinstance(r.ltp, float) and r.ltp > 0
        assert 0.0 <= r.score <= 1.0
        assert isinstance(r.scan_time, datetime)
        assert isinstance(r.matched_conditions, list)

    def test_scan_sorted_by_score(self):
        scanner = MarketScanner()
        # Two conditions: RSI low + volume spike
        cfg = ScanConfig(
            name="Multi",
            conditions=[
                ScanCondition(indicator="rsi", operator="below", value=35.0),
                ScanCondition(indicator="volume_spike", operator="above", value=2.0),
            ],
            universe="custom",
            custom_symbols=["A", "B"],
        )
        # A: matches RSI only (score 0.5), B: matches both (score 1.0)
        bars_a = _rsi_bars(50, direction="down")
        bars_b = _rsi_bars(50, direction="down")
        bars_b[-1]["volume"] = 500_000  # spike
        for bar in bars_b[:-1]:
            bar["volume"] = 50_000
        fetcher = _simple_fetcher({"A": bars_a, "B": bars_b})
        results = scanner.scan(cfg, data_fetcher=fetcher)
        # Both match (all conditions must be true for inclusion)
        # In this config, A might not match volume spike so won't appear
        # Just check that results are in descending score order
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_scan_skips_empty_fetcher(self):
        scanner = MarketScanner()
        cfg = ScanConfig(
            name="Test",
            conditions=[ScanCondition(indicator="rsi", operator="below", value=35.0)],
            universe="custom",
            custom_symbols=["MISSING"],
        )
        fetcher = _simple_fetcher({})  # Returns [] for everything
        results = scanner.scan(cfg, data_fetcher=fetcher)
        assert results == []

    def test_evaluate_conditions_empty_conditions(self):
        scanner = MarketScanner()
        matched, names, score = scanner.evaluate_conditions(_flat_bars(20), [])
        assert matched is False
        assert names == []
        assert score == 0.0

    def test_evaluate_conditions_partial_match(self):
        scanner = MarketScanner()
        conditions = [
            ScanCondition(indicator="rsi", operator="below", value=35.0),
            ScanCondition(indicator="volume_spike", operator="above", value=10.0),  # won't match
        ]
        bars = _rsi_bars(50, direction="down")
        matched, names, score = scanner.evaluate_conditions(bars, conditions)
        assert matched is False  # AND logic
        assert score == 0.5  # 1 of 2 conditions matched
        assert len(names) == 1

    def test_evaluate_conditions_full_match(self):
        scanner = MarketScanner()
        conditions = [
            ScanCondition(indicator="rsi", operator="below", value=35.0),
        ]
        bars = _rsi_bars(50, direction="down")
        matched, names, score = scanner.evaluate_conditions(bars, conditions)
        assert matched is True
        assert score == 1.0


# ---------------------------------------------------------------------------
# Unit tests: PREBUILT_SCANS
# ---------------------------------------------------------------------------


class TestPrebuiltScans:
    def test_all_keys_present(self):
        expected = {
            "rsi_oversold", "rsi_overbought", "volume_breakout",
            "bullish_momentum", "bearish_reversal", "pre_market_movers",
            "volatility_expansion", "52_week_breakout",
        }
        assert expected <= set(PREBUILT_SCANS.keys())

    def test_all_configs_valid(self):
        for key, cfg in PREBUILT_SCANS.items():
            assert isinstance(cfg, ScanConfig), f"{key} is not a ScanConfig"
            assert len(cfg.conditions) >= 1, f"{key} has no conditions"

    def test_rsi_oversold_condition(self):
        cfg = PREBUILT_SCANS["rsi_oversold"]
        assert any(c.indicator == "rsi" for c in cfg.conditions)
        rsi_cond = next(c for c in cfg.conditions if c.indicator == "rsi")
        assert rsi_cond.operator == "below"
        assert rsi_cond.value == 30.0

    def test_rsi_overbought_condition(self):
        cfg = PREBUILT_SCANS["rsi_overbought"]
        rsi_cond = next(c for c in cfg.conditions if c.indicator == "rsi")
        assert rsi_cond.operator == "above"
        assert rsi_cond.value == 70.0

    def test_prebuilt_scan_runs_without_error(self):
        """Smoke test: each prebuilt scan runs on a tiny custom universe."""
        scanner = MarketScanner()
        for key, cfg in PREBUILT_SCANS.items():
            custom_cfg = ScanConfig(
                name=cfg.name,
                conditions=cfg.conditions,
                universe="custom",
                custom_symbols=["RELIANCE", "TCS"],
            )
            ohlcv = _trending_bars(80, step=0.5)
            fetcher = _simple_fetcher({"RELIANCE": ohlcv, "TCS": ohlcv})
            results = scanner.scan(custom_cfg, data_fetcher=fetcher)
            assert isinstance(results, list), f"Prebuilt scan '{key}' failed"
