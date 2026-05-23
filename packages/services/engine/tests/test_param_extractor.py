"""Tests for flinttrade_engine.param_extractor.

Covers:
- extract_params: empty / blank source
- Comment marker discovery (# param:)
- Plain top-level assignment discovery
- Type inference: int, float, bool, str
- Comment annotation with all fields
- Comment annotation with partial fields
- Description extraction from multi-word comment
- Ordering by source line
- Dunder variable exclusion
- Non-literal RHS ignored
- Invalid source raises ValueError
- _coerce_default helper
- _collect_comment_annotations helper
- StrategyParam.to_dict serialisation
"""

from __future__ import annotations

import pytest

from flinttrade_engine.param_extractor import (
    StrategyParam,
    _coerce_default,
    _collect_comment_annotations,
    extract_params,
)


# ---------------------------------------------------------------------------
# Empty / blank source
# ---------------------------------------------------------------------------


class TestEmptySource:
    def test_empty_string(self):
        assert extract_params("") == []

    def test_whitespace_only(self):
        assert extract_params("   \n\t  ") == []

    def test_no_assignments(self):
        result = extract_params("# just a comment\n# another")
        assert result == []


# ---------------------------------------------------------------------------
# Plain top-level assignments (inferred)
# ---------------------------------------------------------------------------


class TestInferredParams:
    def test_int_assignment(self):
        params = extract_params("PERIOD = 14")
        assert len(params) == 1
        p = params[0]
        assert p.name == "PERIOD"
        assert p.type == "int"
        assert p.default == 14
        assert p.source == "inferred"

    def test_float_assignment(self):
        params = extract_params("THRESHOLD = 0.5")
        assert len(params) == 1
        assert params[0].type == "float"
        assert params[0].default == 0.5

    def test_bool_assignment(self):
        params = extract_params("ENABLED = True")
        assert len(params) == 1
        assert params[0].type == "bool"
        assert params[0].default is True

    def test_string_assignment(self):
        params = extract_params("SYMBOL = 'NIFTY'")
        assert len(params) == 1
        assert params[0].type == "str"
        assert params[0].default == "NIFTY"

    def test_multiple_assignments(self):
        code = "PERIOD = 14\nTHRESHOLD = 0.5\nSYMBOL = 'BANKNIFTY'"
        params = extract_params(code)
        assert len(params) == 3
        names = [p.name for p in params]
        assert "PERIOD" in names
        assert "THRESHOLD" in names
        assert "SYMBOL" in names

    def test_lowercase_name_is_also_detected(self):
        params = extract_params("stop_loss_pct = 2.0")
        assert len(params) == 1
        assert params[0].name == "stop_loss_pct"

    def test_dunder_variable_excluded(self):
        params = extract_params("__version__ = '1.0'")
        assert params == []

    def test_non_literal_rhs_ignored(self):
        code = "PERIOD = int(os.getenv('PERIOD', '14'))"
        params = extract_params(code)
        assert params == []

    def test_list_rhs_ignored(self):
        code = "SYMBOLS = ['NIFTY', 'BANKNIFTY']"
        params = extract_params(code)
        assert params == []

    def test_function_call_rhs_ignored(self):
        code = "SMA = calculate_sma(data, 20)"
        params = extract_params(code)
        assert params == []


# ---------------------------------------------------------------------------
# Comment marker discovery (# param:)
# ---------------------------------------------------------------------------


class TestCommentMarkers:
    def test_basic_param_comment(self):
        code = "# param: PERIOD int 14 EMA look-back period\nPERIOD = 14"
        params = extract_params(code)
        assert len(params) == 1
        p = params[0]
        assert p.name == "PERIOD"
        assert p.type == "int"
        assert p.default == 14
        assert p.description == "EMA look-back period"
        assert p.source == "comment"

    def test_comment_provides_description(self):
        code = "# param: THRESHOLD float 0.5 Signal threshold value\nTHRESHOLD = 0.5"
        params = extract_params(code)
        assert params[0].description == "Signal threshold value"

    def test_comment_type_overrides_inferred(self):
        # Comment says float but Python literal is int — comment wins
        code = "# param: RATIO float 2 Ratio for sizing\nRATIO = 2"
        params = extract_params(code)
        assert params[0].type == "float"

    def test_comment_default_overrides_literal(self):
        # Comment says 20 but code has 14 — comment default wins
        code = "# param: PERIOD int 20 Period\nPERIOD = 14"
        params = extract_params(code)
        assert params[0].default == 20

    def test_comment_without_type_falls_back_to_inferred(self):
        code = "# param: PERIOD\nPERIOD = 14"
        params = extract_params(code)
        assert params[0].type == "int"
        assert params[0].default == 14

    def test_comment_without_default_uses_literal(self):
        code = "# param: PERIOD int\nPERIOD = 14"
        params = extract_params(code)
        assert params[0].default == 14

    def test_comment_source_label(self):
        code = "# param: X int 1\nX = 1"
        params = extract_params(code)
        assert params[0].source == "comment"

    def test_non_adjacent_comment_is_ignored(self):
        code = "# param: PERIOD int 14 Period\n\nPERIOD = 14"
        # There is a blank line between the comment and the assignment,
        # so the comment line does NOT immediately precede the assignment.
        # The variable is still picked up as inferred.
        params = extract_params(code)
        assert len(params) == 1
        assert params[0].source == "inferred"

    def test_comment_with_bool_type(self):
        code = "# param: FLAG bool True Enable feature\nFLAG = True"
        params = extract_params(code)
        assert params[0].type == "bool"
        assert params[0].default is True

    def test_comment_with_string_type(self):
        code = "# param: MODE str momentum Strategy mode\nMODE = 'momentum'"
        params = extract_params(code)
        assert params[0].type == "str"
        assert params[0].default == "momentum"

    def test_type_alias_integer(self):
        code = "# param: N integer 5\nN = 5"
        params = extract_params(code)
        assert params[0].type == "int"

    def test_type_alias_double(self):
        code = "# param: RATIO double 1.5\nRATIO = 1.5"
        params = extract_params(code)
        assert params[0].type == "float"


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


class TestOrdering:
    def test_sorted_by_line_number(self):
        code = "B = 2\nA = 1\nC = 3"
        params = extract_params(code)
        names = [p.name for p in params]
        assert names == ["B", "A", "C"]  # original source order

    def test_line_number_stored(self):
        code = "A = 1\nB = 2"
        params = extract_params(code)
        assert params[0].line < params[1].line


# ---------------------------------------------------------------------------
# Invalid source
# ---------------------------------------------------------------------------


class TestInvalidSource:
    def test_syntax_error_raises_value_error(self):
        with pytest.raises(ValueError, match="Could not parse"):
            extract_params("def broken(:")

    def test_invalid_indentation_raises_value_error(self):
        with pytest.raises(ValueError):
            extract_params("  x = 1\ny = 2")


# ---------------------------------------------------------------------------
# StrategyParam.to_dict
# ---------------------------------------------------------------------------


class TestStrategyParamToDict:
    def test_to_dict_contains_all_keys(self):
        p = StrategyParam(name="FOO", type="int", default=42, description="test", line=3)
        d = p.to_dict()
        assert d["name"] == "FOO"
        assert d["type"] == "int"
        assert d["default"] == 42
        assert d["description"] == "test"
        assert d["line"] == 3
        assert d["source"] == "inferred"


# ---------------------------------------------------------------------------
# _coerce_default helper
# ---------------------------------------------------------------------------


class TestCoerceDefault:
    def test_empty_string_returns_fallback(self):
        assert _coerce_default("", "int", 14) == 14

    def test_int_coercion(self):
        assert _coerce_default("20", "int", 14) == 20

    def test_float_coercion(self):
        assert abs(_coerce_default("1.5", "float", 1.0) - 1.5) < 1e-9

    def test_bool_true_values(self):
        for val in ("true", "True", "TRUE", "1", "yes"):
            assert _coerce_default(val, "bool", False) is True

    def test_bool_false_values(self):
        for val in ("false", "0", "no"):
            assert _coerce_default(val, "bool", True) is False

    def test_str_returns_raw(self):
        assert _coerce_default("momentum", "str", "") == "momentum"

    def test_invalid_int_returns_fallback(self):
        assert _coerce_default("abc", "int", 14) == 14

    def test_invalid_float_returns_fallback(self):
        assert _coerce_default("abc", "float", 0.5) == 0.5


# ---------------------------------------------------------------------------
# _collect_comment_annotations helper
# ---------------------------------------------------------------------------


class TestCollectCommentAnnotations:
    def test_finds_annotation(self):
        lines = ["# param: PERIOD int 14 EMA period", "PERIOD = 14"]
        annotations = _collect_comment_annotations(lines)
        assert "PERIOD" in annotations
        a = annotations["PERIOD"]
        assert a.name == "PERIOD"
        assert a.type_hint == "int"
        assert a.default_str == "14"
        assert a.description == "EMA period"
        assert a.line == 1  # 1-based

    def test_no_annotations(self):
        lines = ["PERIOD = 14"]
        annotations = _collect_comment_annotations(lines)
        assert annotations == {}

    def test_multiple_annotations(self):
        lines = [
            "# param: A int 1",
            "A = 1",
            "# param: B float 2.0 B value",
            "B = 2.0",
        ]
        annotations = _collect_comment_annotations(lines)
        assert "A" in annotations
        assert "B" in annotations
        assert annotations["B"].description == "B value"
