"""Tests for the scanner engine — configurable market scanning framework.

Adapted from fluxscan (marketcalls/fluxscan) patterns.
"""

from __future__ import annotations

import pytest

from flinttrade_screener.scanner import ScannerDef, ScannerEngine, ScanResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> ScannerEngine:
    return ScannerEngine()


@pytest.fixture
def sample_data() -> dict[str, dict]:
    """Market data for 5 symbols with various indicator values."""
    return {
        "RELIANCE": {"rsi": 28, "volume": 50000, "avg_volume_20": 20000, "ema_20": 2500, "ema_50": 2480, "prev_ema_20": 2470, "prev_ema_50": 2490},
        "SBIN": {"rsi": 72, "volume": 80000, "avg_volume_20": 30000, "ema_20": 600, "ema_50": 610, "prev_ema_20": 595, "prev_ema_50": 605},
        "ICICIBANK": {"rsi": 45, "volume": 15000, "avg_volume_20": 25000, "ema_20": 1100, "ema_50": 1090, "prev_ema_20": 1085, "prev_ema_50": 1095},
        "ITC": {"rsi": 55, "volume": 10000, "avg_volume_20": 10000, "ema_20": 450, "ema_50": 455, "prev_ema_20": 448, "prev_ema_50": 452},
        "WIPRO": {"rsi": 25, "volume": 60000, "avg_volume_20": 15000, "ema_20": 420, "ema_50": 425, "prev_ema_20": 418, "prev_ema_50": 422},
    }


# ---------------------------------------------------------------------------
# ScannerDef
# ---------------------------------------------------------------------------


class TestScannerDef:
    def test_valid_code(self):
        s = ScannerDef(name="test", code="results = [1, 2, 3]")
        valid, err = s.validate_code()
        assert valid is True
        assert err is None

    def test_invalid_code(self):
        s = ScannerDef(name="test", code="def f(:")
        valid, err = s.validate_code()
        assert valid is False
        assert err is not None
        assert "SyntaxError" in err or "invalid syntax" in err

    def test_defaults(self):
        s = ScannerDef(name="x", code="results = []")
        assert s.category == "custom"
        assert s.is_active is True
        assert s.parameters == {}
        assert s.description == ""


# ---------------------------------------------------------------------------
# ScannerEngine — built-in templates
# ---------------------------------------------------------------------------


class TestBuiltinTemplates:
    def test_builtins_loaded(self, engine: ScannerEngine):
        names = engine.get_builtin_names()
        assert len(names) >= 6
        assert "RSI Oversold" in names
        assert "RSI Overbought" in names
        assert "Volume Spike" in names
        assert "EMA Crossover Bullish" in names
        assert "Bollinger Band Squeeze" in names
        assert "Supertrend Bullish Flip" in names

    def test_categories(self, engine: ScannerEngine):
        cats = engine.get_categories()
        assert "trend" in cats
        assert "momentum" in cats
        assert "volatility" in cats
        assert "volume" in cats

    def test_list_scanners_all(self, engine: ScannerEngine):
        scanners = engine.list_scanners()
        assert len(scanners) >= 6

    def test_list_scanners_by_category(self, engine: ScannerEngine):
        momentum = engine.list_scanners(category="momentum")
        assert all(s.category == "momentum" for s in momentum)
        assert len(momentum) >= 2  # RSI Oversold + RSI Overbought


# ---------------------------------------------------------------------------
# ScannerEngine — execution
# ---------------------------------------------------------------------------


class TestScannerExecution:
    def test_rsi_oversold(self, engine: ScannerEngine, sample_data: dict):
        result = engine.run("RSI Oversold", sample_data)
        assert isinstance(result, ScanResult)
        assert result.error is None
        assert "RELIANCE" in result.matched_symbols  # RSI 28
        assert "WIPRO" in result.matched_symbols  # RSI 25
        assert "SBIN" not in result.matched_symbols  # RSI 72
        assert result.total_scanned == 5

    def test_rsi_overbought(self, engine: ScannerEngine, sample_data: dict):
        result = engine.run("RSI Overbought", sample_data)
        assert "SBIN" in result.matched_symbols  # RSI 72
        assert "RELIANCE" not in result.matched_symbols

    def test_volume_spike(self, engine: ScannerEngine, sample_data: dict):
        result = engine.run("Volume Spike", sample_data)
        # RELIANCE: 50000 / 20000 = 2.5x > 2x
        # SBIN: 80000 / 30000 = 2.67x > 2x
        # WIPRO: 60000 / 15000 = 4x > 2x
        assert "RELIANCE" in result.matched_symbols
        assert "SBIN" in result.matched_symbols
        assert "WIPRO" in result.matched_symbols
        # ICICIBANK: 15000 / 25000 = 0.6x < 2x
        assert "ICICIBANK" not in result.matched_symbols

    def test_ema_crossover(self, engine: ScannerEngine, sample_data: dict):
        result = engine.run("EMA Crossover Bullish", sample_data)
        # RELIANCE: ema20=2500 > ema50=2480, prev_ema20=2470 <= prev_ema50=2490 => crossover!
        assert "RELIANCE" in result.matched_symbols
        # ICICIBANK: ema20=1100 > ema50=1090, prev_ema20=1085 < prev_ema50=1095 => crossover!
        assert "ICICIBANK" in result.matched_symbols

    def test_override_params(self, engine: ScannerEngine, sample_data: dict):
        # RSI Oversold with threshold=26 should only match WIPRO (RSI 25)
        result = engine.run("RSI Oversold", sample_data, override_params={"threshold": 26})
        assert "WIPRO" in result.matched_symbols
        assert "RELIANCE" not in result.matched_symbols  # RSI 28 > 26

    def test_elapsed_time(self, engine: ScannerEngine, sample_data: dict):
        result = engine.run("RSI Oversold", sample_data)
        assert result.elapsed_ms >= 0

    def test_timestamp_present(self, engine: ScannerEngine, sample_data: dict):
        result = engine.run("RSI Oversold", sample_data)
        assert result.timestamp != ""

    def test_unknown_scanner_raises(self, engine: ScannerEngine, sample_data: dict):
        with pytest.raises(KeyError, match="not registered"):
            engine.run("NonExistent Scanner", sample_data)


# ---------------------------------------------------------------------------
# ScannerEngine — custom scanners
# ---------------------------------------------------------------------------


class TestCustomScanners:
    def test_register_custom(self, engine: ScannerEngine, sample_data: dict):
        custom = ScannerDef(
            name="High RSI + High Volume",
            code='results = [s for s, d in data.items() if d.get("rsi", 0) > 50 and d.get("volume", 0) > 30000]',
            category="custom",
        )
        engine.register(custom)
        result = engine.run("High RSI + High Volume", sample_data)
        assert "SBIN" in result.matched_symbols  # RSI 72, volume 80000
        assert "WIPRO" not in result.matched_symbols  # RSI 25

    def test_register_invalid_code_raises(self, engine: ScannerEngine):
        bad = ScannerDef(name="bad", code="def f(:")
        with pytest.raises(ValueError, match="invalid code"):
            engine.register(bad)

    def test_unregister(self, engine: ScannerEngine):
        assert engine.unregister("RSI Oversold") is True
        assert engine.unregister("RSI Oversold") is False  # Already removed

    def test_runtime_error_captured(self, engine: ScannerEngine, sample_data: dict):
        broken = ScannerDef(
            name="broken",
            code='results = 1 / 0',  # ZeroDivisionError
        )
        engine.register(broken)
        result = engine.run("broken", sample_data)
        assert result.error is not None
        assert "ZeroDivisionError" in result.error or "division by zero" in result.error

    def test_empty_data(self, engine: ScannerEngine):
        result = engine.run("RSI Oversold", {})
        assert result.matched_symbols == []
        assert result.total_scanned == 0
