"""Tests for packages/indicators/src/pine_converter.py.

Covers:
1.  Simple EMA conversion
2.  MACD conversion
3.  Crossover detection
4.  input.int() parameter conversion
5.  Full SuperTrend strategy conversion
6.  Unsupported function warning
7.  Empty input handling
8.  get_supported_functions() returns non-empty list
9.  Bollinger Bands conversion
10. VWAP property (no-arg) conversion
11. Pine keyword substitution (true/false/na)
12. alertcondition() conversion
13. plot() → comment
14. strategy declaration → comment
15. Custom array variable names
"""

from __future__ import annotations

import pytest

from packages.indicators.src.pine_converter import (
    ConversionResult,
    PineConverter,
    convert_pine,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _converter() -> PineConverter:
    """Return a PineConverter with default array variable names."""
    return PineConverter()


def _contains(code: str, fragment: str) -> bool:
    """Return True if ``fragment`` appears anywhere in ``code``."""
    return fragment in code


# ---------------------------------------------------------------------------
# 1. Simple EMA conversion
# ---------------------------------------------------------------------------


class TestEMAConversion:
    def test_ema_basic(self):
        """ta.ema(close, 20) → ema(closes, 20)."""
        result = _converter().convert("ema20 = ta.ema(close, 20)")
        assert "ema(closes, 20)" in result.python_code

    def test_ema_import_added(self):
        """EMA conversion adds 'ema' to imports."""
        result = _converter().convert("x = ta.ema(close, 14)")
        assert "ema" in result.imports

    def test_ema_custom_source(self):
        """ta.ema(hl2, 9) uses the hl2 mapped expression."""
        result = _converter().convert("val = ta.ema(hl2, 9)")
        assert "ema(" in result.python_code
        # hl2 should be mapped to the array expression
        assert "highs + lows" in result.python_code or "hl2" in result.python_code

    def test_sma_basic(self):
        """ta.sma(close, 50) → sma(closes, 50)."""
        result = _converter().convert("s = ta.sma(close, 50)")
        assert "sma(closes, 50)" in result.python_code
        assert "sma" in result.imports


# ---------------------------------------------------------------------------
# 2. MACD conversion
# ---------------------------------------------------------------------------


class TestMACDConversion:
    def test_macd_full_args(self):
        """ta.macd(close, 12, 26, 9) → macd(closes, 12, 26, 9)."""
        result = _converter().convert("[ml, sl, hist] = ta.macd(close, 12, 26, 9)")
        assert "macd(closes, 12, 26, 9)" in result.python_code

    def test_macd_import_added(self):
        """MACD conversion adds 'macd' to imports."""
        result = _converter().convert("macd_line, sig, hist = ta.macd(close, 12, 26, 9)")
        assert "macd" in result.imports

    def test_macd_preserves_assignment(self):
        """The LHS variable assignment is kept intact."""
        result = _converter().convert("my_macd = ta.macd(close, 12, 26, 9)")
        assert "my_macd" in result.python_code


# ---------------------------------------------------------------------------
# 3. Crossover detection
# ---------------------------------------------------------------------------


class TestCrossoverConversion:
    def test_crossover_basic(self):
        """ta.crossover(fast, slow) → crossover(fast, slow)."""
        result = _converter().convert("bull = ta.crossover(fast, slow)")
        assert "crossover(fast, slow)" in result.python_code
        assert "crossover" in result.imports

    def test_crossunder_basic(self):
        """ta.crossunder(a, b) → crossunder(a, b)."""
        result = _converter().convert("bear = ta.crossunder(macd_line, signal_line)")
        assert "crossunder(macd_line, signal_line)" in result.python_code
        assert "crossunder" in result.imports

    def test_crossover_in_condition(self):
        """Crossover embedded inside an if condition."""
        pine = "if ta.crossover(ema9, ema21)\n    strategy.entry('Long', strategy.long)"
        result = _converter().convert(pine)
        assert "crossover(ema9, ema21)" in result.python_code


# ---------------------------------------------------------------------------
# 4. input.int() parameter conversion
# ---------------------------------------------------------------------------


class TestInputConversion:
    def test_input_int_basic(self):
        """input.int(14, ...) → int(14) assignment."""
        result = _converter().convert("length = input.int(14, title='Length')")
        assert "length = int(14)" in result.python_code

    def test_input_float_basic(self):
        """input.float(3.0, ...) → float(3.0) assignment."""
        result = _converter().convert("mult = input.float(3.0, title='Multiplier')")
        assert "mult = float(3.0)" in result.python_code

    def test_input_bool_basic(self):
        """input.bool(true, ...) → bool(True) or bool(true)."""
        result = _converter().convert("show_labels = input.bool(true, title='Show')")
        assert "show_labels = bool(" in result.python_code

    def test_input_emits_warning(self):
        """input.int() conversion always emits a warning about manual review."""
        result = _converter().convert("period = input.int(20, title='Period')")
        assert any("period" in w for w in result.warnings)

    def test_input_string_basic(self):
        """input.string() → str() assignment."""
        result = _converter().convert('mode = input.string("long", title="Mode")')
        assert "mode = str(" in result.python_code


# ---------------------------------------------------------------------------
# 5. Full SuperTrend strategy conversion
# ---------------------------------------------------------------------------


class TestSuperTrendConversion:
    PINE_SUPERTREND = """\
//@version=5
indicator("SuperTrend", overlay=true)
factor = input.float(3.0, "Factor")
atrPeriod = input.int(10, "ATR Length")
[st, direction] = ta.supertrend(factor, atrPeriod)
isBullish = direction
plot(st, color=color.green)
alertcondition(ta.crossover(close, st), title="Buy Signal")
"""

    def test_supertrend_indicator_call_present(self):
        """supertrend() call appears in the converted output."""
        result = _converter().convert(self.PINE_SUPERTREND)
        assert "supertrend(" in result.python_code

    def test_supertrend_uses_ohlcv_arrays(self):
        """supertrend call injects highs, lows, closes arrays."""
        result = _converter().convert(self.PINE_SUPERTREND)
        assert "highs" in result.python_code
        assert "lows" in result.python_code
        assert "closes" in result.python_code

    def test_supertrend_plot_becomes_comment(self):
        """plot() calls are converted to Python comments."""
        result = _converter().convert(self.PINE_SUPERTREND)
        assert "# plot(" in result.python_code

    def test_supertrend_alertcondition_becomes_signal(self):
        """alertcondition() becomes a signal boolean assignment."""
        result = _converter().convert(self.PINE_SUPERTREND)
        assert "signal = bool(" in result.python_code

    def test_supertrend_version_header_becomes_comment(self):
        """//@version=5 header becomes a Python comment."""
        result = _converter().convert(self.PINE_SUPERTREND)
        # Should be a comment, not left as Pine syntax
        assert "//@version" not in result.python_code

    def test_supertrend_imports_include_supertrend(self):
        """Conversion result includes 'supertrend' in imports."""
        result = _converter().convert(self.PINE_SUPERTREND)
        assert "supertrend" in result.imports

    def test_supertrend_inputs_converted(self):
        """input.float and input.int are converted to typed Python literals."""
        result = _converter().convert(self.PINE_SUPERTREND)
        assert "float(" in result.python_code
        assert "int(" in result.python_code


# ---------------------------------------------------------------------------
# 6. Unsupported function warning
# ---------------------------------------------------------------------------


class TestUnsupportedFunctions:
    def test_unknown_ta_function_flagged(self):
        """ta.unknown() is added to the unsupported list."""
        result = _converter().convert("x = ta.unknown(close, 14)")
        assert any("unknown" in u for u in result.unsupported)

    def test_unknown_ta_function_does_not_raise(self):
        """Conversion with unknown functions completes without raising."""
        result = _converter().convert("x = ta.newfunction(close, 14, 2)")
        assert isinstance(result, ConversionResult)

    def test_known_function_not_in_unsupported(self):
        """ta.rsi() should NOT appear in the unsupported list."""
        result = _converter().convert("r = ta.rsi(close, 14)")
        assert not any("rsi" in u for u in result.unsupported)

    def test_multiple_unsupported_deduplicated(self):
        """Duplicate unsupported function names are deduplicated."""
        pine = "a = ta.foo(close, 5)\nb = ta.foo(close, 10)"
        result = _converter().convert(pine)
        foo_hits = [u for u in result.unsupported if "foo" in u]
        assert len(foo_hits) == len(set(foo_hits))


# ---------------------------------------------------------------------------
# 7. Empty input handling
# ---------------------------------------------------------------------------


class TestEmptyInput:
    def test_empty_string_returns_empty_code(self):
        """Empty string input produces empty python_code."""
        result = _converter().convert("")
        assert result.python_code == ""

    def test_whitespace_only_returns_empty_code(self):
        """Whitespace-only input produces empty python_code."""
        result = _converter().convert("   \n\t\n  ")
        assert result.python_code == ""

    def test_empty_result_has_empty_imports(self):
        """Empty input produces empty imports list."""
        result = _converter().convert("")
        assert result.imports == []

    def test_empty_result_has_empty_warnings(self):
        """Empty input produces empty warnings list."""
        result = _converter().convert("")
        assert result.warnings == []

    def test_empty_result_has_empty_unsupported(self):
        """Empty input produces empty unsupported list."""
        result = _converter().convert("")
        assert result.unsupported == []

    def test_comment_only_input(self):
        """A script with only comments does not crash."""
        result = _converter().convert("// This is a comment\n// Another comment")
        assert isinstance(result, ConversionResult)
        assert result.python_code.count("#") >= 2


# ---------------------------------------------------------------------------
# 8. get_supported_functions()
# ---------------------------------------------------------------------------


class TestGetSupportedFunctions:
    def test_returns_non_empty_list(self):
        """get_supported_functions() returns a non-empty list."""
        funcs = PineConverter.get_supported_functions()
        assert len(funcs) > 0

    def test_returns_list_type(self):
        """get_supported_functions() return type is list."""
        funcs = PineConverter.get_supported_functions()
        assert isinstance(funcs, list)

    def test_contains_core_ta_functions(self):
        """Core ta functions must be present in the supported list."""
        funcs = PineConverter.get_supported_functions()
        for name in ("ta.ema", "ta.rsi", "ta.macd", "ta.supertrend",
                     "ta.crossover", "ta.atr", "ta.bb"):
            assert name in funcs, f"{name!r} missing from supported list"

    def test_contains_input_functions(self):
        """input.* functions must be present in the supported list."""
        funcs = PineConverter.get_supported_functions()
        assert "input.int" in funcs
        assert "input.float" in funcs

    def test_sorted_alphabetically(self):
        """The list should be sorted."""
        funcs = PineConverter.get_supported_functions()
        assert funcs == sorted(funcs)


# ---------------------------------------------------------------------------
# 9. Bollinger Bands conversion
# ---------------------------------------------------------------------------


class TestBollingerBandsConversion:
    def test_bb_basic(self):
        """ta.bb(close, 20, 2.0) → bollinger_bands(closes, 20, 2.0)."""
        result = _converter().convert("[upper, mid, lower] = ta.bb(close, 20, 2.0)")
        assert "bollinger_bands(closes, 20, 2.0)" in result.python_code
        assert "bollinger_bands" in result.imports

    def test_bb_default_args_preserved(self):
        """ta.bb with all args maps them correctly."""
        result = _converter().convert("bands = ta.bb(close, 20, 2)")
        assert "bollinger_bands(" in result.python_code


# ---------------------------------------------------------------------------
# 10. VWAP property conversion
# ---------------------------------------------------------------------------


class TestVWAPConversion:
    def test_vwap_property_becomes_call(self):
        """ta.vwap (no parens) → vwap(highs, lows, closes, volumes)."""
        result = _converter().convert("v = ta.vwap")
        assert "vwap(highs, lows, closes, volumes)" in result.python_code
        assert "vwap" in result.imports

    def test_vwap_custom_array_names(self):
        """Custom array names flow through into the vwap() call."""
        conv = PineConverter(highs="H", lows="L", closes="C", volumes="V")
        result = conv.convert("price = ta.vwap")
        assert "vwap(H, L, C, V)" in result.python_code


# ---------------------------------------------------------------------------
# 11. Pine keyword substitution
# ---------------------------------------------------------------------------


class TestKeywordSubstitution:
    def test_true_becomes_True(self):
        """Pine `true` → Python `True`."""
        result = _converter().convert("flag = true")
        assert "True" in result.python_code

    def test_false_becomes_False(self):
        """Pine `false` → Python `False`."""
        result = _converter().convert("flag = false")
        assert "False" in result.python_code

    def test_na_becomes_nan(self):
        """Pine `na` → ``np.nan``."""
        result = _converter().convert("val = na")
        assert "np.nan" in result.python_code

    def test_pine_comment_becomes_python_comment(self):
        """Pine // comment → Python # comment."""
        result = _converter().convert("// This is a Pine comment")
        assert result.python_code.startswith("#")


# ---------------------------------------------------------------------------
# 12. alertcondition() conversion
# ---------------------------------------------------------------------------


class TestAlertConditionConversion:
    def test_alertcondition_becomes_signal(self):
        """alertcondition(cond) → signal = bool(cond)."""
        result = _converter().convert('alertcondition(rsi < 30, title="Oversold")')
        assert "signal = bool(" in result.python_code

    def test_alertcondition_preserves_condition(self):
        """The condition expression is preserved in the output."""
        result = _converter().convert("alertcondition(bullish_cross)")
        assert "bullish_cross" in result.python_code

    def test_alertcondition_emits_warning(self):
        """alertcondition conversion emits a warning."""
        result = _converter().convert("alertcondition(some_cond)")
        assert any("alertcondition" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# 13. plot() → comment
# ---------------------------------------------------------------------------


class TestPlotConversion:
    def test_plot_becomes_comment(self):
        """plot(series) → # plot(series) Python comment."""
        result = _converter().convert("plot(my_ema, color=color.blue)")
        assert "# plot(" in result.python_code

    def test_plotshape_becomes_comment(self):
        """plotshape() → # plotshape() comment."""
        result = _converter().convert("plotshape(buy_signal, style=shape.triangleup)")
        assert "# plotshape(" in result.python_code

    def test_plot_not_treated_as_function_call(self):
        """plot() lines do not generate false indicator imports."""
        result = _converter().convert("plot(closes)")
        assert result.imports == []


# ---------------------------------------------------------------------------
# 14. strategy declaration → comment
# ---------------------------------------------------------------------------


class TestStrategyDeclaration:
    def test_strategy_declaration_becomes_comment(self):
        """strategy(...) at the top → Python comment."""
        result = _converter().convert('strategy("My Strategy", overlay=true)')
        assert "# strategy(" in result.python_code

    def test_indicator_declaration_becomes_comment(self):
        """indicator(...) declaration → Python comment."""
        result = _converter().convert('indicator("My Indicator", overlay=false)')
        assert "# indicator(" in result.python_code


# ---------------------------------------------------------------------------
# 15. Custom array variable names
# ---------------------------------------------------------------------------


class TestCustomArrayNames:
    def test_ema_custom_array(self):
        """PineConverter with custom closes name uses it in output."""
        conv = PineConverter(closes="price")
        result = conv.convert("x = ta.ema(close, 14)")
        assert "ema(price, 14)" in result.python_code

    def test_atr_custom_ohlcv(self):
        """ATR call uses all custom OHLCV array names."""
        conv = PineConverter(highs="H", lows="L", closes="C")
        result = conv.convert("x = ta.atr(14)")
        assert "atr(H, L, C, 14)" in result.python_code


# ---------------------------------------------------------------------------
# 16. RSI conversion
# ---------------------------------------------------------------------------


class TestRSIConversion:
    def test_rsi_basic(self):
        """ta.rsi(close, 14) → rsi(closes, 14)."""
        result = _converter().convert("r = ta.rsi(close, 14)")
        assert "rsi(closes, 14)" in result.python_code
        assert "rsi" in result.imports

    def test_rsi_in_condition(self):
        """RSI embedded inside if condition converts correctly."""
        result = _converter().convert("oversold = ta.rsi(close, 14) < 30")
        assert "rsi(" in result.python_code


# ---------------------------------------------------------------------------
# 17. ATR conversion
# ---------------------------------------------------------------------------


class TestATRConversion:
    def test_atr_basic(self):
        """ta.atr(14) → atr(highs, lows, closes, 14)."""
        result = _converter().convert("a = ta.atr(14)")
        assert "atr(highs, lows, closes, 14)" in result.python_code
        assert "atr" in result.imports


# ---------------------------------------------------------------------------
# 18. ConversionResult dataclass
# ---------------------------------------------------------------------------


class TestConversionResult:
    def test_dataclass_fields(self):
        """ConversionResult has the expected fields."""
        r = ConversionResult(python_code="x = 1", imports=["ema"], warnings=[], unsupported=[])
        assert r.python_code == "x = 1"
        assert r.imports == ["ema"]
        assert r.warnings == []
        assert r.unsupported == []

    def test_default_factory_fields(self):
        """ConversionResult fields default to empty lists."""
        r = ConversionResult(python_code="")
        assert r.imports == []
        assert r.warnings == []
        assert r.unsupported == []


# ---------------------------------------------------------------------------
# 19. convert_pine() convenience function
# ---------------------------------------------------------------------------


class TestConvertPineFunction:
    def test_convenience_function_basic(self):
        """convert_pine() returns a ConversionResult."""
        result = convert_pine("x = ta.ema(close, 14)")
        assert isinstance(result, ConversionResult)
        assert "ema(" in result.python_code

    def test_convenience_function_custom_arrays(self):
        """convert_pine() forwards kwargs to PineConverter constructor."""
        result = convert_pine("x = ta.ema(close, 14)", closes="price_series")
        assert "price_series" in result.python_code


# ---------------------------------------------------------------------------
# 20. Multi-line script round-trip
# ---------------------------------------------------------------------------


class TestMultiLineScript:
    PINE = """\
//@version=5
indicator("EMA Cross", overlay=true)
fast_len = input.int(9, "Fast")
slow_len = input.int(21, "Slow")
fast_ema = ta.ema(close, fast_len)
slow_ema = ta.ema(close, slow_len)
bull = ta.crossover(fast_ema, slow_ema)
bear = ta.crossunder(fast_ema, slow_ema)
plot(fast_ema, color=color.green)
plot(slow_ema, color=color.red)
alertcondition(bull, title="Bull Cross")
"""

    def test_output_is_string(self):
        """Multi-line conversion returns a string."""
        result = _converter().convert(self.PINE)
        assert isinstance(result.python_code, str)

    def test_line_count_matches(self):
        """Output has the same number of lines as input."""
        result = _converter().convert(self.PINE)
        in_lines = self.PINE.strip().splitlines()
        out_lines = result.python_code.strip().splitlines()
        assert len(out_lines) == len(in_lines)

    def test_both_ema_calls_converted(self):
        """Both EMA calls are converted in a multi-line script."""
        result = _converter().convert(self.PINE)
        assert result.python_code.count("ema(") >= 2

    def test_imports_contain_expected(self):
        """Multi-line script imports include ema, crossover, crossunder."""
        result = _converter().convert(self.PINE)
        for name in ("ema", "crossover", "crossunder"):
            assert name in result.imports, f"'{name}' missing from imports"
