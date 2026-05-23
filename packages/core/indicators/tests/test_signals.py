"""Tests for signal generators: crossover, crossunder, exrem, flip, valuewhen, pivothigh, pivotlow.

20+ tests covering correctness, edge cases, and type validation.
"""

from __future__ import annotations

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _arr(*values: float) -> np.ndarray:
    return np.array(values, dtype=np.float64)


# ---------------------------------------------------------------------------
# crossover
# ---------------------------------------------------------------------------


class TestCrossover:
    def test_simple_crossover(self):
        """s1 crosses above s2 at bar 2."""
        from flinttrade_indicators.signals import crossover

        s1 = _arr(1.0, 2.0, 4.0, 5.0)
        s2 = _arr(3.0, 3.0, 3.0, 3.0)
        result = crossover(s1, s2)
        # Bar 0: first bar, always False
        # Bar 1: s1[1]=2 <= s2[1]=3, no cross
        # Bar 2: s1[2]=4 > s2[2]=3 AND s1[1]=2 <= s2[1]=3 → True
        # Bar 3: s1[3]=5 > s2[3]=3 but s1[2]=4 > s2[2]=3 (was already above) → False
        assert not result[0]
        assert not result[1]
        assert result[2]
        assert not result[3]

    def test_no_crossover_if_already_above(self):
        """No crossover if s1 stays above s2 the whole time."""
        from flinttrade_indicators.signals import crossover

        s1 = _arr(5.0, 6.0, 7.0)
        s2 = _arr(1.0, 1.0, 1.0)
        result = crossover(s1, s2)
        assert not np.any(result)

    def test_crossover_returns_bool_array(self):
        from flinttrade_indicators.signals import crossover

        s1 = _arr(1.0, 2.0)
        s2 = _arr(2.0, 1.0)
        result = crossover(s1, s2)
        assert result.dtype == np.bool_

    def test_crossover_length_mismatch_raises(self):
        from flinttrade_indicators.signals import crossover

        with pytest.raises(ValueError):
            crossover(_arr(1.0, 2.0), _arr(1.0, 2.0, 3.0))

    def test_crossover_nan_bars_skipped(self):
        """NaN bars should not produce a spurious crossover."""
        from flinttrade_indicators.signals import crossover

        s1 = _arr(1.0, np.nan, 5.0)
        s2 = _arr(3.0, 3.0, 3.0)
        result = crossover(s1, s2)
        # Bar 2: prev bar had NaN → skip
        assert not result[2]

    def test_crossover_first_bar_always_false(self):
        from flinttrade_indicators.signals import crossover

        s1 = _arr(10.0)
        s2 = _arr(1.0)
        result = crossover(s1, s2)
        assert not result[0]


# ---------------------------------------------------------------------------
# crossunder
# ---------------------------------------------------------------------------


class TestCrossunder:
    def test_simple_crossunder(self):
        """s1 crosses below s2 at bar 2."""
        from flinttrade_indicators.signals import crossunder

        s1 = _arr(5.0, 4.0, 2.0, 1.0)
        s2 = _arr(3.0, 3.0, 3.0, 3.0)
        result = crossunder(s1, s2)
        # Bar 2: s1[2]=2 < s2[2]=3 AND s1[1]=4 >= s2[1]=3 → True
        assert not result[0]
        assert not result[1]
        assert result[2]
        assert not result[3]

    def test_no_crossunder_if_already_below(self):
        from flinttrade_indicators.signals import crossunder

        s1 = _arr(0.5, 0.5, 0.5)
        s2 = _arr(1.0, 1.0, 1.0)
        result = crossunder(s1, s2)
        assert not np.any(result)

    def test_crossunder_returns_bool_array(self):
        from flinttrade_indicators.signals import crossunder

        s1 = _arr(1.0, 2.0)
        s2 = _arr(2.0, 1.0)
        result = crossunder(s1, s2)
        assert result.dtype == np.bool_

    def test_crossover_and_crossunder_mutually_exclusive(self):
        """crossover and crossunder cannot both be True at the same bar."""
        from flinttrade_indicators.signals import crossover, crossunder

        rng = np.random.default_rng(99)
        s1 = np.array(100.0 + np.cumsum(rng.normal(0, 1, 50)), dtype=np.float64)
        s2 = np.array(100.0 + np.cumsum(rng.normal(0, 1, 50)), dtype=np.float64)
        co = crossover(s1, s2)
        cu = crossunder(s1, s2)
        # No bar can have both True
        assert not np.any(co & cu)


# ---------------------------------------------------------------------------
# pivothigh
# ---------------------------------------------------------------------------


class TestPivotHigh:
    def test_simple_pivot_high(self):
        from flinttrade_indicators.signals import pivothigh

        # Bar 2 is a strict maximum in window [0..4] (left=2, right=2)
        source = _arr(1.0, 2.0, 5.0, 3.0, 1.0, 0.5, 0.5, 0.5)
        result = pivothigh(source, left=2, right=2)
        assert not np.isnan(result[2])
        assert result[2] == pytest.approx(5.0)

    def test_no_pivot_when_tied(self):
        """No pivot where two bars share the same maximum."""
        from flinttrade_indicators.signals import pivothigh

        source = _arr(1.0, 5.0, 5.0, 1.0, 1.0)
        result = pivothigh(source, left=1, right=1)
        # Neither bar 1 nor bar 2 is a strict maximum
        assert np.all(np.isnan(result[1:3]))

    def test_pivot_high_nan_boundaries(self):
        """First `left` and last `right` bars must be NaN."""
        from flinttrade_indicators.signals import pivothigh

        source = _arr(1.0, 5.0, 1.0, 1.0, 1.0)
        result = pivothigh(source, left=2, right=2)
        assert np.isnan(result[0])
        assert np.isnan(result[1])
        assert np.isnan(result[-1])
        assert np.isnan(result[-2])

    def test_invalid_left_raises(self):
        from flinttrade_indicators.signals import pivothigh

        with pytest.raises(ValueError):
            pivothigh(_arr(1.0, 2.0, 3.0), left=0, right=1)

    def test_invalid_right_raises(self):
        from flinttrade_indicators.signals import pivothigh

        with pytest.raises(ValueError):
            pivothigh(_arr(1.0, 2.0, 3.0), left=1, right=0)


# ---------------------------------------------------------------------------
# pivotlow
# ---------------------------------------------------------------------------


class TestPivotLow:
    def test_simple_pivot_low(self):
        from flinttrade_indicators.signals import pivotlow

        source = _arr(5.0, 3.0, 1.0, 4.0, 6.0, 7.0, 7.0, 7.0)
        result = pivotlow(source, left=2, right=2)
        assert not np.isnan(result[2])
        assert result[2] == pytest.approx(1.0)

    def test_no_pivot_when_tied(self):
        """No pivot where two bars share the same minimum."""
        from flinttrade_indicators.signals import pivotlow

        source = _arr(5.0, 1.0, 1.0, 5.0, 5.0)
        result = pivotlow(source, left=1, right=1)
        assert np.all(np.isnan(result[1:3]))

    def test_pivot_low_nan_boundaries(self):
        from flinttrade_indicators.signals import pivotlow

        source = _arr(5.0, 1.0, 5.0, 5.0, 5.0)
        result = pivotlow(source, left=2, right=2)
        assert np.isnan(result[0])
        assert np.isnan(result[-1])

    def test_pivot_high_low_non_overlapping(self):
        """A bar cannot be both a pivot high and a pivot low."""
        from flinttrade_indicators.signals import pivothigh, pivotlow

        rng = np.random.default_rng(17)
        source = rng.normal(0, 1, 100).astype(np.float64)
        ph = pivothigh(source, left=3, right=3)
        pl = pivotlow(source, left=3, right=3)
        # No bar has both a pivot high and pivot low value
        both = ~np.isnan(ph) & ~np.isnan(pl)
        assert not np.any(both)


# ---------------------------------------------------------------------------
# exrem (absorbed from pandas_signals_library)
# ---------------------------------------------------------------------------


def _bool(*values: bool) -> np.ndarray:
    return np.array(values, dtype=np.bool_)


class TestExrem:
    def test_basic_suppression(self):
        """Only the first primary signal fires; subsequent are suppressed."""
        from flinttrade_indicators.signals import exrem

        primary = _bool(False, True, True, False, True, True)
        secondary = _bool(False, False, False, True, False, False)
        result = exrem(primary, secondary)
        expected = _bool(False, True, False, False, True, False)
        np.testing.assert_array_equal(result, expected)

    def test_no_secondary_ever(self):
        """Without a reset, only the very first primary fires."""
        from flinttrade_indicators.signals import exrem

        primary = _bool(True, True, True, True)
        secondary = _bool(False, False, False, False)
        result = exrem(primary, secondary)
        expected = _bool(True, False, False, False)
        np.testing.assert_array_equal(result, expected)

    def test_immediate_reset(self):
        """Secondary immediately after primary re-arms the latch."""
        from flinttrade_indicators.signals import exrem

        primary = _bool(True, False, True, False)
        secondary = _bool(False, True, False, True)
        result = exrem(primary, secondary)
        expected = _bool(True, False, True, False)
        np.testing.assert_array_equal(result, expected)

    def test_empty_primary(self):
        """No primary signals means no output signals."""
        from flinttrade_indicators.signals import exrem

        primary = _bool(False, False, False)
        secondary = _bool(True, True, True)
        result = exrem(primary, secondary)
        assert not np.any(result)

    def test_length_mismatch_raises(self):
        from flinttrade_indicators.signals import exrem

        with pytest.raises(ValueError, match="length mismatch"):
            exrem(_bool(True, False), _bool(True))


class TestFlip:
    def test_basic_latch(self):
        """Set latches on, reset turns off."""
        from flinttrade_indicators.signals import flip

        set_sig = _bool(False, True, False, False, False, True)
        rst_sig = _bool(False, False, False, True, False, False)
        result = flip(set_sig, rst_sig)
        expected = _bool(False, True, True, False, False, True)
        np.testing.assert_array_equal(result, expected)

    def test_starts_off(self):
        """Output is False until the first set signal."""
        from flinttrade_indicators.signals import flip

        set_sig = _bool(False, False, True, False)
        rst_sig = _bool(False, False, False, False)
        result = flip(set_sig, rst_sig)
        expected = _bool(False, False, True, True)
        np.testing.assert_array_equal(result, expected)

    def test_multiple_resets(self):
        """Multiple resets with no set stay off."""
        from flinttrade_indicators.signals import flip

        set_sig = _bool(True, False, False, False)
        rst_sig = _bool(False, True, True, False)
        result = flip(set_sig, rst_sig)
        expected = _bool(True, False, False, False)
        np.testing.assert_array_equal(result, expected)

    def test_length_mismatch_raises(self):
        from flinttrade_indicators.signals import flip

        with pytest.raises(ValueError, match="length mismatch"):
            flip(_bool(True), _bool(True, False))


class TestValuewhen:
    def test_basic_lookback(self):
        """Returns source value at most recent condition=True."""
        from flinttrade_indicators.signals import valuewhen

        cond = _bool(False, True, False, True, False)
        vals = _arr(10.0, 20.0, 30.0, 40.0, 50.0)
        result = valuewhen(cond, vals, 1)
        assert np.isnan(result[0])
        assert result[1] == 20.0
        assert result[2] == 20.0
        assert result[3] == 40.0
        assert result[4] == 40.0

    def test_second_occurrence(self):
        """occurrence=2 gets the second-most-recent trigger."""
        from flinttrade_indicators.signals import valuewhen

        cond = _bool(True, False, True, False, True)
        vals = _arr(1.0, 2.0, 3.0, 4.0, 5.0)
        result = valuewhen(cond, vals, 2)
        assert np.isnan(result[0])  # Only 1 trigger so far
        assert np.isnan(result[1])  # Still only 1 trigger
        assert result[2] == 1.0  # 2nd most recent trigger is index 0
        assert result[3] == 1.0
        assert result[4] == 3.0  # 2nd most recent is index 2

    def test_no_triggers(self):
        """All NaN when condition is never True."""
        from flinttrade_indicators.signals import valuewhen

        cond = _bool(False, False, False)
        vals = _arr(1.0, 2.0, 3.0)
        result = valuewhen(cond, vals, 1)
        assert np.all(np.isnan(result))

    def test_occurrence_zero_raises(self):
        from flinttrade_indicators.signals import valuewhen

        with pytest.raises(ValueError, match="occurrence must be >= 1"):
            valuewhen(_bool(True), _arr(1.0), 0)

    def test_length_mismatch_raises(self):
        from flinttrade_indicators.signals import valuewhen

        with pytest.raises(ValueError, match="length mismatch"):
            valuewhen(_bool(True, False), _arr(1.0), 1)
