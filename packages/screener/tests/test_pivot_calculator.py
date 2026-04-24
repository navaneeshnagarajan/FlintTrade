"""Tests for PivotCalculator — all five methods with known values.

Run with:
    python -m pytest packages/screener/tests/test_pivot_calculator.py -v --import-mode=importlib
"""

from __future__ import annotations

import math

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _approx(val: float, expected: float, tol: float = 0.01) -> bool:
    """Return True if val is within tol of expected."""
    return math.isclose(val, expected, rel_tol=0.0, abs_tol=tol)


def _calc(high: float, low: float, close: float, open_price=None, method=None):
    from packages.screener.src.pivot_calculator import PivotCalculator, PivotMethod
    m = method or PivotMethod.STANDARD
    return PivotCalculator.calculate(high, low, close, open_price=open_price, method=m)


# ---------------------------------------------------------------------------
# PivotLevels model
# ---------------------------------------------------------------------------


class TestPivotLevels:
    """Test the PivotLevels Pydantic model."""

    def test_standard_model_creation(self):
        from packages.screener.src.pivot_calculator import PivotLevels, PivotMethod
        levels = PivotLevels(
            method=PivotMethod.STANDARD,
            pivot=18366.67,
            r1=18533.33, r2=18666.67, r3=18833.33,
            s1=18200.00, s2=18066.67, s3=17900.00,
        )
        assert levels.pivot == 18366.67
        assert levels.r4 is None
        assert levels.s4 is None

    def test_camarilla_has_r4_s4(self):
        from packages.screener.src.pivot_calculator import PivotLevels, PivotMethod
        levels = PivotLevels(
            method=PivotMethod.CAMARILLA,
            pivot=100.0,
            r1=100.5, r2=101.0, r3=101.5, r4=102.0,
            s1=99.5, s2=99.0, s3=98.5, s4=98.0,
        )
        assert levels.r4 == 102.0
        assert levels.s4 == 98.0

    def test_to_dict_method_is_string(self):
        from packages.screener.src.pivot_calculator import PivotLevels, PivotMethod
        levels = PivotLevels(
            method=PivotMethod.FIBONACCI,
            pivot=100.0,
            r1=101.0, r2=102.0, r3=103.0,
            s1=99.0, s2=98.0, s3=97.0,
        )
        d = levels.to_dict()
        assert isinstance(d["method"], str)
        assert d["method"] == "fibonacci"

    def test_to_dict_contains_all_fields(self):
        from packages.screener.src.pivot_calculator import PivotLevels, PivotMethod
        levels = PivotLevels(
            method=PivotMethod.STANDARD,
            pivot=100.0,
            r1=101.0, r2=102.0, r3=103.0,
            s1=99.0, s2=98.0, s3=97.0,
        )
        d = levels.to_dict()
        for key in ("method", "pivot", "r1", "r2", "r3", "r4", "s1", "s2", "s3", "s4"):
            assert key in d, f"Missing key: {key}"

    def test_levels_rounded_to_2dp(self):
        from packages.screener.src.pivot_calculator import PivotLevels, PivotMethod
        levels = PivotLevels(
            method=PivotMethod.STANDARD,
            pivot=100.33333,
            r1=100.66667, r2=101.0, r3=101.33333,
            s1=99.66667, s2=99.0, s3=98.33333,
        )
        # Should be rounded to 2 decimal places
        assert levels.pivot == round(100.33333, 2)
        assert levels.r1 == round(100.66667, 2)


# ---------------------------------------------------------------------------
# Standard method
# ---------------------------------------------------------------------------


class TestStandardPivot:
    """Test Standard (floor trader) pivot calculations."""

    # Known values: H=18500, L=18200, C=18400
    # P = (18500+18200+18400)/3 = 18366.67
    # R1 = 2*P - L = 36733.33 - 18200 = 18533.33
    # S1 = 2*P - H = 36733.33 - 18500 = 18233.33
    # R2 = P + (H-L) = 18366.67 + 300 = 18666.67
    # S2 = P - (H-L) = 18366.67 - 300 = 18066.67
    # R3 = H + 2*(P-L) = 18500 + 2*(166.67) = 18833.33
    # S3 = L - 2*(H-P) = 18200 - 2*(133.33) = 17933.33

    H, L, C = 18500.0, 18200.0, 18400.0

    def test_pivot(self):
        levels = _calc(self.H, self.L, self.C)
        assert _approx(levels.pivot, 18366.67)

    def test_r1(self):
        levels = _calc(self.H, self.L, self.C)
        assert _approx(levels.r1, 18533.33)

    def test_r2(self):
        levels = _calc(self.H, self.L, self.C)
        assert _approx(levels.r2, 18666.67)

    def test_r3(self):
        levels = _calc(self.H, self.L, self.C)
        assert _approx(levels.r3, 18833.33)

    def test_s1(self):
        levels = _calc(self.H, self.L, self.C)
        assert _approx(levels.s1, 18233.33)

    def test_s2(self):
        levels = _calc(self.H, self.L, self.C)
        assert _approx(levels.s2, 18066.67)

    def test_s3(self):
        levels = _calc(self.H, self.L, self.C)
        assert _approx(levels.s3, 17933.33)

    def test_method_label(self):
        from packages.screener.src.pivot_calculator import PivotMethod
        levels = _calc(self.H, self.L, self.C)
        assert levels.method == PivotMethod.STANDARD

    def test_no_r4_s4(self):
        levels = _calc(self.H, self.L, self.C)
        assert levels.r4 is None
        assert levels.s4 is None

    def test_r_levels_above_pivot(self):
        levels = _calc(self.H, self.L, self.C)
        assert levels.r1 > levels.pivot
        assert levels.r2 > levels.r1
        assert levels.r3 > levels.r2

    def test_s_levels_below_pivot(self):
        levels = _calc(self.H, self.L, self.C)
        assert levels.s1 < levels.pivot
        assert levels.s2 < levels.s1
        assert levels.s3 < levels.s2

    def test_equal_high_low(self):
        # Edge case: H == L (zero range)
        levels = _calc(100.0, 100.0, 100.0)
        assert levels.pivot == 100.0
        assert levels.r1 == levels.s1 == 100.0


# ---------------------------------------------------------------------------
# Fibonacci method
# ---------------------------------------------------------------------------


class TestFibonacciPivot:
    """Test Fibonacci pivot calculations."""

    # H=18500, L=18200, C=18400 → P=18366.67, range=300
    # R1 = P + 0.382*300 = 18366.67 + 114.6 = 18481.27
    # R2 = P + 0.618*300 = 18366.67 + 185.4 = 18552.07
    # R3 = P + 300 = 18666.67
    # S1 = P - 0.382*300 = 18252.07
    # S2 = P - 0.618*300 = 18181.27
    # S3 = P - 300 = 18066.67

    H, L, C = 18500.0, 18200.0, 18400.0

    def _levels(self):
        from packages.screener.src.pivot_calculator import PivotMethod
        return _calc(self.H, self.L, self.C, method=PivotMethod.FIBONACCI)

    def test_pivot(self):
        assert _approx(self._levels().pivot, 18366.67)

    def test_r1(self):
        assert _approx(self._levels().r1, 18481.27)

    def test_r2(self):
        assert _approx(self._levels().r2, 18552.07)

    def test_r3(self):
        assert _approx(self._levels().r3, 18666.67)

    def test_s1(self):
        assert _approx(self._levels().s1, 18252.07)

    def test_s2(self):
        assert _approx(self._levels().s2, 18181.27)

    def test_s3(self):
        assert _approx(self._levels().s3, 18066.67)

    def test_r3_equals_p_plus_range(self):
        lvl = self._levels()
        assert _approx(lvl.r3, lvl.pivot + (self.H - self.L))

    def test_s3_equals_p_minus_range(self):
        lvl = self._levels()
        assert _approx(lvl.s3, lvl.pivot - (self.H - self.L))

    def test_method_label(self):
        from packages.screener.src.pivot_calculator import PivotMethod
        assert self._levels().method == PivotMethod.FIBONACCI


# ---------------------------------------------------------------------------
# Woodie method
# ---------------------------------------------------------------------------


class TestWoodiePivot:
    """Test Woodie pivot calculations."""

    # H=18500, L=18200, C=18400 → P=(18500+18200+2*18400)/4 = 18375.0
    # R1 = 2*P - L = 36750 - 18200 = 18550
    # S1 = 2*P - H = 36750 - 18500 = 18250
    # R2 = P + (H-L) = 18375 + 300 = 18675
    # S2 = P - (H-L) = 18375 - 300 = 18075
    # R3 = R1 + (H-L) = 18550 + 300 = 18850
    # S3 = S1 - (H-L) = 18250 - 300 = 17950

    H, L, C = 18500.0, 18200.0, 18400.0

    def _levels(self):
        from packages.screener.src.pivot_calculator import PivotMethod
        return _calc(self.H, self.L, self.C, method=PivotMethod.WOODIE)

    def test_pivot(self):
        assert _approx(self._levels().pivot, 18375.0)

    def test_pivot_close_weighted(self):
        """Woodie pivot should differ from standard because close is weighted."""
        from packages.screener.src.pivot_calculator import PivotMethod
        std = _calc(self.H, self.L, self.C, method=PivotMethod.STANDARD)
        woo = self._levels()
        assert woo.pivot != std.pivot

    def test_r1(self):
        assert _approx(self._levels().r1, 18550.0)

    def test_r2(self):
        assert _approx(self._levels().r2, 18675.0)

    def test_r3(self):
        assert _approx(self._levels().r3, 18850.0)

    def test_s1(self):
        assert _approx(self._levels().s1, 18250.0)

    def test_s2(self):
        assert _approx(self._levels().s2, 18075.0)

    def test_s3(self):
        assert _approx(self._levels().s3, 17950.0)

    def test_method_label(self):
        from packages.screener.src.pivot_calculator import PivotMethod
        assert self._levels().method == PivotMethod.WOODIE


# ---------------------------------------------------------------------------
# Camarilla method
# ---------------------------------------------------------------------------


class TestCamarillaPivot:
    """Test Camarilla pivot calculations (4 levels each side)."""

    # H=18500, L=18200, C=18400, range=300
    # R1 = C + range*(1.1/12) = 18400 + 300*0.09167 = 18400 + 27.5 = 18427.5
    # R2 = C + range*(1.1/6)  = 18400 + 300*0.18333 = 18400 + 55.0 = 18455.0
    # R3 = C + range*(1.1/4)  = 18400 + 300*0.275   = 18400 + 82.5 = 18482.5
    # R4 = C + range*(1.1/2)  = 18400 + 300*0.55    = 18400 + 165  = 18565.0
    # S1–S4: mirror with minus

    H, L, C = 18500.0, 18200.0, 18400.0

    def _levels(self):
        from packages.screener.src.pivot_calculator import PivotMethod
        return _calc(self.H, self.L, self.C, method=PivotMethod.CAMARILLA)

    def test_has_r4_s4(self):
        lvl = self._levels()
        assert lvl.r4 is not None
        assert lvl.s4 is not None

    def test_r1(self):
        assert _approx(self._levels().r1, 18427.5)

    def test_r2(self):
        assert _approx(self._levels().r2, 18455.0)

    def test_r3(self):
        assert _approx(self._levels().r3, 18482.5)

    def test_r4(self):
        assert _approx(self._levels().r4, 18565.0)

    def test_s1(self):
        assert _approx(self._levels().s1, 18372.5)

    def test_s2(self):
        assert _approx(self._levels().s2, 18345.0)

    def test_s3(self):
        assert _approx(self._levels().s3, 18317.5)

    def test_s4(self):
        assert _approx(self._levels().s4, 18235.0)

    def test_r_ordered_ascending(self):
        lvl = self._levels()
        assert lvl.r1 < lvl.r2 < lvl.r3 < lvl.r4  # type: ignore[operator]

    def test_s_ordered_descending(self):
        lvl = self._levels()
        assert lvl.s1 > lvl.s2 > lvl.s3 > lvl.s4  # type: ignore[operator]

    def test_camarilla_bands_centred_near_close(self):
        lvl = self._levels()
        # All R/S levels should cluster around close
        assert abs(lvl.r1 - self.C) < self.H - self.L
        assert abs(lvl.s1 - self.C) < self.H - self.L

    def test_method_label(self):
        from packages.screener.src.pivot_calculator import PivotMethod
        assert self._levels().method == PivotMethod.CAMARILLA


# ---------------------------------------------------------------------------
# DeMark method
# ---------------------------------------------------------------------------


class TestDeMarkPivot:
    """Test DeMark pivot calculations across all three conditional branches."""

    H, L, C = 18500.0, 18200.0, 18400.0

    def _levels(self, open_price):
        from packages.screener.src.pivot_calculator import PivotMethod
        return _calc(self.H, self.L, self.C, open_price=open_price, method=PivotMethod.DEMARK)

    # Branch: C > O (bullish — X = 2H + L + C)
    # O=18300 < C=18400 → X = 2*18500 + 18200 + 18400 = 73600
    # P = 73600/4 = 18400.0
    # R1 = 73600/2 - L = 36800 - 18200 = 18600
    # S1 = 73600/2 - H = 36800 - 18500 = 18300

    def test_bullish_branch_pivot(self):
        levels = self._levels(open_price=18300.0)
        assert _approx(levels.pivot, 18400.0)

    def test_bullish_branch_r1(self):
        levels = self._levels(open_price=18300.0)
        assert _approx(levels.r1, 18600.0)

    def test_bullish_branch_s1(self):
        levels = self._levels(open_price=18300.0)
        assert _approx(levels.s1, 18300.0)

    # Branch: C < O (bearish — X = H + 2L + C)
    # O=18450 > C=18400 → X = 18500 + 2*18200 + 18400 = 73300
    # P = 73300/4 = 18325.0
    # R1 = 73300/2 - L = 36650 - 18200 = 18450
    # S1 = 73300/2 - H = 36650 - 18500 = 18150

    def test_bearish_branch_pivot(self):
        levels = self._levels(open_price=18450.0)
        assert _approx(levels.pivot, 18325.0)

    def test_bearish_branch_r1(self):
        levels = self._levels(open_price=18450.0)
        assert _approx(levels.r1, 18450.0)

    def test_bearish_branch_s1(self):
        levels = self._levels(open_price=18450.0)
        assert _approx(levels.s1, 18150.0)

    # Branch: C == O (doji — X = H + L + 2C)
    # O=18400 == C=18400 → X = 18500 + 18200 + 2*18400 = 73500
    # P = 73500/4 = 18375.0
    # R1 = 73500/2 - L = 36750 - 18200 = 18550
    # S1 = 73500/2 - H = 36750 - 18500 = 18250

    def test_doji_branch_pivot(self):
        levels = self._levels(open_price=18400.0)
        assert _approx(levels.pivot, 18375.0)

    def test_doji_branch_r1(self):
        levels = self._levels(open_price=18400.0)
        assert _approx(levels.r1, 18550.0)

    def test_doji_branch_s1(self):
        levels = self._levels(open_price=18400.0)
        assert _approx(levels.s1, 18250.0)

    def test_no_open_defaults_to_doji_branch(self):
        """When open_price is omitted DeMark should use the doji branch (C==O)."""
        from packages.screener.src.pivot_calculator import PivotMethod
        levels_no_open = _calc(self.H, self.L, self.C, method=PivotMethod.DEMARK)
        levels_doji = self._levels(open_price=self.C)
        assert _approx(levels_no_open.pivot, levels_doji.pivot)
        assert _approx(levels_no_open.r1, levels_doji.r1)
        assert _approx(levels_no_open.s1, levels_doji.s1)

    def test_method_label(self):
        from packages.screener.src.pivot_calculator import PivotMethod
        levels = self._levels(open_price=18300.0)
        assert levels.method == PivotMethod.DEMARK

    def test_three_branches_give_different_pivots(self):
        """Bullish, bearish, doji branches must yield different pivots."""
        bull = self._levels(open_price=18300.0)   # C > O
        bear = self._levels(open_price=18450.0)   # C < O
        doji = self._levels(open_price=18400.0)   # C == O
        pivots = {round(bull.pivot, 2), round(bear.pivot, 2), round(doji.pivot, 2)}
        assert len(pivots) == 3


# ---------------------------------------------------------------------------
# all_methods
# ---------------------------------------------------------------------------


class TestAllMethods:
    """Test PivotCalculator.all_methods aggregation."""

    H, L, C = 18500.0, 18200.0, 18400.0

    def _all(self, open_price=None):
        from packages.screener.src.pivot_calculator import PivotCalculator
        return PivotCalculator.all_methods(self.H, self.L, self.C, open_price=open_price)

    def test_returns_five_methods(self):
        result = self._all()
        assert len(result) == 5

    def test_all_method_keys_present(self):
        result = self._all()
        for key in ("standard", "fibonacci", "woodie", "camarilla", "demark"):
            assert key in result, f"Missing method: {key}"

    def test_each_value_is_pivot_levels(self):
        from packages.screener.src.pivot_calculator import PivotLevels
        result = self._all()
        for val in result.values():
            assert isinstance(val, PivotLevels)

    def test_method_labels_match_keys(self):
        result = self._all()
        for key, levels in result.items():
            assert levels.method.value == key

    def test_camarilla_has_r4_s4_others_dont(self):
        result = self._all()
        assert result["camarilla"].r4 is not None
        assert result["camarilla"].s4 is not None
        for key in ("standard", "fibonacci", "woodie", "demark"):
            assert result[key].r4 is None
            assert result[key].s4 is None

    def test_all_methods_same_pivot_input(self):
        """Standard, Fibonacci, and Camarilla share the same P = (H+L+C)/3."""
        result = self._all()
        expected_p = round((self.H + self.L + self.C) / 3, 2)
        for key in ("standard", "fibonacci", "camarilla"):
            assert _approx(result[key].pivot, expected_p), f"{key} pivot mismatch"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestValidation:
    """Test edge cases and error handling."""

    def test_high_less_than_low_raises(self):
        from packages.screener.src.pivot_calculator import PivotCalculator

        with pytest.raises(ValueError, match="high"):
            PivotCalculator.calculate(18000, 18500, 18200)

    def test_high_equals_low_zero_range(self):
        """Zero-range OHLC should not raise and should produce equal levels."""
        from packages.screener.src.pivot_calculator import PivotCalculator

        levels = PivotCalculator.calculate(100.0, 100.0, 100.0)
        assert levels.pivot == 100.0

    def test_default_method_is_standard(self):
        from packages.screener.src.pivot_calculator import PivotCalculator, PivotMethod

        levels = PivotCalculator.calculate(18500, 18200, 18400)
        assert levels.method == PivotMethod.STANDARD

    def test_fractional_prices(self):
        """Fractional inputs (forex/crypto prices) should work correctly."""
        from packages.screener.src.pivot_calculator import PivotCalculator

        levels = PivotCalculator.calculate(1.1050, 1.0950, 1.1010)
        assert levels.pivot > 0

    def test_large_prices(self):
        """Large prices (e.g. Nifty futures) should not overflow."""
        from packages.screener.src.pivot_calculator import PivotCalculator

        levels = PivotCalculator.calculate(90000, 88000, 89500)
        assert levels.r1 > levels.pivot > levels.s1


# ---------------------------------------------------------------------------
# Pivot routes
# ---------------------------------------------------------------------------

_TEST_API_KEY = "test-pivot-route-key"


@pytest.fixture(scope="module")
def pivot_client(tmp_path_factory):
    """Flask test client for pivot routes."""
    import os

    os.environ["OPENALGO_API_KEY"] = _TEST_API_KEY
    from packages.core.src.app import create_flask_app
    import packages.screener.src.pivot_routes  # noqa: F401 — ensure blueprint loaded

    app = create_flask_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def _post(client, payload: dict):
    return client.post(
        "/v1/pivots/calculate",
        json=payload,
        headers={"X-API-Key": _TEST_API_KEY, "Content-Type": "application/json"},
    )


class TestPivotRoute:
    """Test POST /ft-api/v1/pivots/calculate."""

    def test_returns_200(self, pivot_client):
        resp = _post(pivot_client, {"high": 18500, "low": 18200, "close": 18400})
        assert resp.status_code == 200

    def test_response_shape(self, pivot_client):
        resp = _post(pivot_client, {"high": 18500, "low": 18200, "close": 18400})
        data = resp.get_json()
        assert data["status"] == "success"
        assert "methods" in data["data"]
        assert "input" in data["data"]

    def test_all_five_methods_present(self, pivot_client):
        resp = _post(pivot_client, {"high": 18500, "low": 18200, "close": 18400})
        methods = resp.get_json()["data"]["methods"]
        for m in ("standard", "fibonacci", "woodie", "camarilla", "demark"):
            assert m in methods, f"Missing method: {m}"

    def test_method_has_pivot_and_levels(self, pivot_client):
        resp = _post(pivot_client, {"high": 18500, "low": 18200, "close": 18400})
        std = resp.get_json()["data"]["methods"]["standard"]
        for key in ("pivot", "r1", "r2", "r3", "s1", "s2", "s3"):
            assert key in std

    def test_missing_high_returns_400(self, pivot_client):
        resp = _post(pivot_client, {"low": 18200, "close": 18400})
        assert resp.status_code == 400

    def test_missing_low_returns_400(self, pivot_client):
        resp = _post(pivot_client, {"high": 18500, "close": 18400})
        assert resp.status_code == 400

    def test_missing_close_returns_400(self, pivot_client):
        resp = _post(pivot_client, {"high": 18500, "low": 18200})
        assert resp.status_code == 400

    def test_invalid_numeric_returns_400(self, pivot_client):
        resp = _post(pivot_client, {"high": "abc", "low": 18200, "close": 18400})
        assert resp.status_code == 400

    def test_high_less_than_low_returns_400(self, pivot_client):
        resp = _post(pivot_client, {"high": 18000, "low": 18500, "close": 18200})
        assert resp.status_code == 400

    def test_open_included_in_input(self, pivot_client):
        resp = _post(pivot_client, {"high": 18500, "low": 18200, "close": 18400, "open": 18300})
        inp = resp.get_json()["data"]["input"]
        assert inp["open"] == 18300.0

    def test_camarilla_has_r4_s4_in_response(self, pivot_client):
        resp = _post(pivot_client, {"high": 18500, "low": 18200, "close": 18400})
        cam = resp.get_json()["data"]["methods"]["camarilla"]
        assert "r4" in cam
        assert "s4" in cam
        assert cam["r4"] is not None
        assert cam["s4"] is not None
