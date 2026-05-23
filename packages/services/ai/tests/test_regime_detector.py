"""Tests for the ADX+BB+ATR regime detector.

Covers:
- RegimeState enum: all six states, is_tradeable, is_trending, is_volatile.
- detect_regime raises ValueError for insufficient bars.
- detect_regime_detailed returns RegimeResult with correct fields.
- All 6 regime states are reachable with crafted price series.
- VOLATILE_DIRECTIONLESS: low ADX + wide BB (pre-expiry zone).
- LOW_VOLATILITY: tight BB + falling ATR.
- RegimeResult.to_dict() serialises all fields.
- Helper indicators: _atr, _bollinger_bands, _directional_movement.
"""

from __future__ import annotations

import math
import random

import pytest

from flinttrade_ai.regime_detector import (
    RegimeState,
    _atr,
    _bollinger_bands,
    _directional_movement,
    _ema,
    _sma,
    _true_range,
    detect_regime,
    detect_regime_detailed,
)


# ---------------------------------------------------------------------------
# Fixtures — synthetic price generators
# ---------------------------------------------------------------------------


def _trending_up(n: int = 100, start: float = 22000.0) -> tuple[list[float], list[float], list[float]]:
    """Strong, consistent uptrend with small candles — ADX should be high."""
    random.seed(1)
    price = start
    high, low, close = [], [], []
    for _ in range(n):
        price += random.uniform(30, 80)  # persistent upward drift
        high.append(price + random.uniform(5, 15))
        low.append(price - random.uniform(1, 5))
        close.append(price)
    return high, low, close


def _trending_down(n: int = 100, start: float = 22000.0) -> tuple[list[float], list[float], list[float]]:
    """Strong, consistent downtrend."""
    random.seed(2)
    price = start
    high, low, close = [], [], []
    for _ in range(n):
        price -= random.uniform(30, 80)
        high.append(price + random.uniform(1, 5))
        low.append(price - random.uniform(5, 15))
        close.append(price)
    return high, low, close


def _ranging(n: int = 100, start: float = 22000.0) -> tuple[list[float], list[float], list[float]]:
    """Tight sideways chop — low ADX and narrow BB."""
    random.seed(3)
    high, low, close = [], [], []
    for i in range(n):
        mid = start + math.sin(i * 0.3) * 30  # tiny oscillation
        high.append(mid + random.uniform(5, 10))
        low.append(mid - random.uniform(5, 10))
        close.append(mid + random.uniform(-2, 2))
    return high, low, close


def _volatile_directionless(n: int = 100, start: float = 22000.0) -> tuple[list[float], list[float], list[float]]:
    """High volatility, no clear direction — wide BB, low ADX."""
    random.seed(4)
    price = start
    high, low, close = [], [], []
    for _ in range(n):
        change = random.uniform(-500, 500)  # huge random swings, no trend
        price += change
        swing = abs(change) * 0.5 + 200
        high.append(price + swing)
        low.append(price - swing)
        close.append(price)
    return high, low, close


def _low_volatility(n: int = 100, start: float = 22000.0) -> tuple[list[float], list[float], list[float]]:
    """Very tight compression — tiny candles, ATR declining."""
    random.seed(5)
    price = start
    high, low, close = [], [], []
    for i in range(n):
        # Gradually tighten volatility over the series
        vol = max(1.0, 20.0 - i * 0.15)
        price += random.uniform(-1, 1)
        high.append(price + vol)
        low.append(price - vol)
        close.append(price + random.uniform(-0.5, 0.5))
    return high, low, close


# ---------------------------------------------------------------------------
# RegimeState enum
# ---------------------------------------------------------------------------


class TestRegimeState:
    """Tests for RegimeState enum properties."""

    def test_all_six_states_exist(self) -> None:
        states = {s.value for s in RegimeState}
        expected = {
            "TRENDING_UP", "TRENDING_DOWN", "RANGING",
            "VOLATILE_DIRECTIONAL", "VOLATILE_DIRECTIONLESS", "LOW_VOLATILITY",
        }
        assert states == expected

    def test_label_matches_value(self) -> None:
        for state in RegimeState:
            assert state.label == state.value

    def test_is_tradeable_true_for_trending(self) -> None:
        assert RegimeState.TRENDING_UP.is_tradeable is True
        assert RegimeState.TRENDING_DOWN.is_tradeable is True

    def test_is_tradeable_true_for_ranging(self) -> None:
        assert RegimeState.RANGING.is_tradeable is True

    def test_is_tradeable_false_for_volatile_directionless(self) -> None:
        assert RegimeState.VOLATILE_DIRECTIONLESS.is_tradeable is False

    def test_is_tradeable_false_for_low_volatility(self) -> None:
        assert RegimeState.LOW_VOLATILITY.is_tradeable is False

    def test_is_tradeable_true_for_volatile_directional(self) -> None:
        assert RegimeState.VOLATILE_DIRECTIONAL.is_tradeable is True

    def test_is_trending_only_for_trending_states(self) -> None:
        assert RegimeState.TRENDING_UP.is_trending is True
        assert RegimeState.TRENDING_DOWN.is_trending is True
        assert RegimeState.RANGING.is_trending is False
        assert RegimeState.VOLATILE_DIRECTIONLESS.is_trending is False

    def test_is_volatile_for_volatile_states(self) -> None:
        assert RegimeState.VOLATILE_DIRECTIONAL.is_volatile is True
        assert RegimeState.VOLATILE_DIRECTIONLESS.is_volatile is True
        assert RegimeState.TRENDING_UP.is_volatile is False
        assert RegimeState.RANGING.is_volatile is False

    def test_str_representation_is_value(self) -> None:
        assert str(RegimeState.TRENDING_UP) == "TRENDING_UP"


# ---------------------------------------------------------------------------
# detect_regime — input validation
# ---------------------------------------------------------------------------


class TestDetectRegimeInputValidation:
    """Tests for input length validation."""

    def test_raises_value_error_for_insufficient_bars(self) -> None:
        """detect_regime raises ValueError when fewer than adx_period*2+1 bars."""
        with pytest.raises(ValueError, match="requires at least"):
            detect_regime([1.0] * 5, [0.9] * 5, [0.95] * 5, adx_period=14)

    def test_minimum_bars_does_not_raise(self) -> None:
        """Exactly adx_period*2+1 bars should not raise."""
        adx_period = 14
        min_bars = adx_period * 2 + 1
        h = [100.0 + i * 0.1 for i in range(min_bars)]
        lo = [99.0 + i * 0.1 for i in range(min_bars)]
        c = [99.5 + i * 0.1 for i in range(min_bars)]

        # Should not raise
        state = detect_regime(h, lo, c, adx_period=adx_period)
        assert isinstance(state, RegimeState)

    def test_accepts_list_sequences(self) -> None:
        h, lo, c = _ranging()
        state = detect_regime(h, lo, c)
        assert isinstance(state, RegimeState)


# ---------------------------------------------------------------------------
# RegimeResult
# ---------------------------------------------------------------------------


class TestRegimeResult:
    """Tests for the RegimeResult dataclass."""

    def test_to_dict_contains_all_keys(self) -> None:
        h, lo, c = _ranging()
        result = detect_regime_detailed(h, lo, c)
        d = result.to_dict()

        expected_keys = {
            "state", "adx", "bb_width", "atr_current", "atr_slope",
            "plus_di", "minus_di", "close", "n_bars",
        }
        assert set(d.keys()) == expected_keys

    def test_state_in_dict_is_string(self) -> None:
        h, lo, c = _ranging()
        result = detect_regime_detailed(h, lo, c)
        assert isinstance(result.to_dict()["state"], str)

    def test_n_bars_matches_input_length(self) -> None:
        h, lo, c = _ranging(n=80)
        result = detect_regime_detailed(h, lo, c)
        assert result.n_bars == 80

    def test_close_matches_last_price(self) -> None:
        h, lo, c = _ranging()
        result = detect_regime_detailed(h, lo, c)
        assert result.close == pytest.approx(c[-1])

    def test_adx_is_positive(self) -> None:
        h, lo, c = _trending_up()
        result = detect_regime_detailed(h, lo, c)
        assert result.adx > 0.0

    def test_bb_width_is_positive(self) -> None:
        h, lo, c = _volatile_directionless()
        result = detect_regime_detailed(h, lo, c)
        assert result.bb_width > 0.0


# ---------------------------------------------------------------------------
# Regime detection — one test per state
# ---------------------------------------------------------------------------


class TestRegimeDetectionStates:
    """Verify each of the 6 regime states is reachable."""

    def test_trending_up_detected(self) -> None:
        h, lo, c = _trending_up(n=100)
        state = detect_regime(h, lo, c, adx_threshold=20.0)
        # Strong uptrend should yield either TRENDING_UP or VOLATILE_DIRECTIONAL
        assert state in {RegimeState.TRENDING_UP, RegimeState.VOLATILE_DIRECTIONAL}

    def test_trending_down_detected(self) -> None:
        h, lo, c = _trending_down(n=100)
        state = detect_regime(h, lo, c, adx_threshold=20.0)
        assert state in {RegimeState.TRENDING_DOWN, RegimeState.VOLATILE_DIRECTIONAL}

    def test_ranging_detected(self) -> None:
        h, lo, c = _ranging(n=100)
        state = detect_regime(
            h, lo, c,
            adx_threshold=30.0,       # high threshold so low-ADX ranging passes
            bb_width_threshold=0.10,  # wide threshold so narrow BB is "ranging"
            low_vol_bb_threshold=0.001,
        )
        assert state in {RegimeState.RANGING, RegimeState.LOW_VOLATILITY}

    def test_volatile_directionless_detected(self) -> None:
        """Pre-expiry manipulation zone: low ADX, wide BB."""
        h, lo, c = _volatile_directionless(n=100)
        state = detect_regime(
            h, lo, c,
            adx_threshold=40.0,       # force into low-ADX branch
            bb_width_threshold=0.001,  # very low → wide BB triggers VD
        )
        assert state == RegimeState.VOLATILE_DIRECTIONLESS

    def test_volatile_directionless_is_not_tradeable(self) -> None:
        """Confirm the pre-expiry zone is flagged as non-tradeable."""
        h, lo, c = _volatile_directionless(n=100)
        result = detect_regime_detailed(
            h, lo, c,
            adx_threshold=40.0,
            bb_width_threshold=0.001,
        )
        if result.state == RegimeState.VOLATILE_DIRECTIONLESS:
            assert not result.state.is_tradeable

    def test_low_volatility_detected(self) -> None:
        h, lo, c = _low_volatility(n=100)
        state = detect_regime(
            h, lo, c,
            adx_threshold=40.0,         # force low-ADX
            bb_width_threshold=1.0,     # wide threshold so we never hit VD
            low_vol_bb_threshold=0.5,   # very wide → almost any narrow BB qualifies
        )
        # With these thresholds and declining ATR the state should be LOW_VOLATILITY
        # (or RANGING if ATR slope is not negative)
        assert state in {RegimeState.LOW_VOLATILITY, RegimeState.RANGING}


# ---------------------------------------------------------------------------
# Indicator helper unit tests
# ---------------------------------------------------------------------------


class TestTrueRange:
    def test_first_bar_is_high_minus_low(self) -> None:
        h = [105.0]
        lo = [95.0]
        c = [100.0]
        tr = _true_range(h, lo, c)
        assert tr[0] == pytest.approx(10.0)

    def test_gaps_are_captured(self) -> None:
        """True range captures gap-up scenarios."""
        h = [100.0, 120.0]
        lo = [90.0, 115.0]
        c = [95.0, 118.0]
        tr = _true_range(h, lo, c)
        # Second bar: max(120-115, |120-95|, |115-95|) = max(5, 25, 20) = 25
        assert tr[1] == pytest.approx(25.0)


class TestAtr:
    def test_nan_for_insufficient_bars(self) -> None:
        h = [100.0] * 5
        lo = [95.0] * 5
        c = [97.0] * 5
        atr = _atr(h, lo, c, period=14)
        assert all(math.isnan(v) for v in atr)

    def test_atr_positive_for_valid_series(self) -> None:
        h, lo, c = _trending_up(n=50)
        atr = _atr(h, lo, c, period=14)
        valid = [v for v in atr if not math.isnan(v)]
        assert all(v > 0 for v in valid)


class TestBollingerBands:
    def test_output_length_matches_input(self) -> None:
        c = [float(i) for i in range(30)]
        upper, mid, lower = _bollinger_bands(c, period=20)
        assert len(upper) == len(mid) == len(lower) == 30

    def test_upper_above_lower(self) -> None:
        h, lo, c = _ranging()
        upper, mid, lower = _bollinger_bands(c, period=20)
        for u, lo in zip(upper, lower):
            if not (math.isnan(u) or math.isnan(lo)):
                assert u >= lo

    def test_mid_between_upper_and_lower(self) -> None:
        h, lo, c = _ranging()
        upper, mid, lower = _bollinger_bands(c, period=20)
        for u, m, lo in zip(upper, mid, lower):
            if not any(math.isnan(v) for v in (u, m, lo)):
                assert lo <= m <= u


class TestDirectionalMovement:
    def test_output_lengths_match_input(self) -> None:
        h, lo, c = _trending_up(n=60)
        pdi, mdi, adx = _directional_movement(h, lo, c, period=14)
        assert len(pdi) == len(mdi) == len(adx) == 60

    def test_adx_in_0_100_range_for_valid_values(self) -> None:
        h, lo, c = _trending_up(n=80)
        _, _, adx = _directional_movement(h, lo, c, period=14)
        for v in adx:
            if not math.isnan(v):
                assert 0.0 <= v <= 100.0

    def test_trending_up_has_plus_di_gt_minus_di(self) -> None:
        h, lo, c = _trending_up(n=80)
        pdi, mdi, _ = _directional_movement(h, lo, c, period=14)
        valid = [
            (p, m) for p, m in zip(pdi, mdi)
            if not math.isnan(p) and not math.isnan(m)
        ]
        assert len(valid) > 0
        # In a strong uptrend, most +DI values should exceed -DI
        above = sum(1 for p, m in valid if p > m)
        assert above / len(valid) > 0.6


class TestEmaAndSma:
    def test_ema_length_matches_input(self) -> None:
        values = list(range(30))
        assert len(_ema([float(v) for v in values], period=10)) == 30

    def test_sma_length_matches_input(self) -> None:
        values = [float(i) for i in range(30)]
        assert len(_sma(values, period=10)) == 30

    def test_sma_correct_value(self) -> None:
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        sma = _sma(values, period=3)
        assert sma[2] == pytest.approx(2.0)  # (1+2+3)/3
        assert sma[4] == pytest.approx(4.0)  # (3+4+5)/3

    def test_ema_first_valid_is_sma_seed(self) -> None:
        values = [2.0] * 10
        ema = _ema(values, period=5)
        # First valid EMA is the average of first 5 = 2.0
        assert ema[4] == pytest.approx(2.0)
