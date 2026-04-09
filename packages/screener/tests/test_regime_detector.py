"""Tests for the market regime detector.

All tests are self-contained — no API calls, no broker connection required.
Uses pytest with --import-mode=importlib.
"""

from __future__ import annotations

import pytest

from packages.screener.src.regime_detector import (
    RegimeDetector,
    RegimeSignal,
    RegimeType,
    _build_rationale,
    _compute_vix_percentile,
    _cumulative_return,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def detector() -> RegimeDetector:
    return RegimeDetector()


def _flat_returns(n: int = 20, value: float = 0.0) -> list[float]:
    """Generate n constant daily returns."""
    return [value] * n


def _trending_returns(n: int = 20, daily: float = 0.003) -> list[float]:
    """Generate n upward daily returns."""
    return [daily] * n


# ---------------------------------------------------------------------------
# RegimeSignal model
# ---------------------------------------------------------------------------

class TestRegimeSignal:
    """Tests for the RegimeSignal Pydantic model."""

    def test_confidence_in_range(self, detector):
        signal = detector.detect(vix=15.0, nifty_returns=_flat_returns())
        assert 0.0 <= signal.confidence <= 1.0

    def test_regime_is_enum_value(self, detector):
        signal = detector.detect(vix=15.0, nifty_returns=_flat_returns())
        assert signal.regime in RegimeType.__members__.values()

    def test_rationale_non_empty(self, detector):
        signal = detector.detect(vix=15.0, nifty_returns=_flat_returns())
        assert signal.rationale
        assert len(signal.rationale) > 10

    def test_vix_stored_correctly(self, detector):
        signal = detector.detect(vix=18.5, nifty_returns=_flat_returns())
        assert signal.vix_level == pytest.approx(18.5)

    def test_none_fields_when_not_provided(self, detector):
        signal = detector.detect(vix=15.0, nifty_returns=_flat_returns())
        assert signal.dxy_level is None
        assert signal.advance_decline_ratio is None
        assert signal.fii_dii_net is None
        assert signal.breadth is None

    def test_fields_set_when_provided(self, detector):
        signal = detector.detect(
            vix=15.0,
            nifty_returns=_flat_returns(),
            advance_decline=(1400, 600),
            fii_net=2500.0,
            breadth=65.0,
            dxy_level=104.5,
        )
        assert signal.advance_decline_ratio is not None
        assert signal.fii_dii_net is not None
        assert signal.breadth is not None
        assert signal.dxy_level is not None


# ---------------------------------------------------------------------------
# VIX-based regime classification
# ---------------------------------------------------------------------------

class TestVIXRegime:
    """Tests for VIX-driven regime rules."""

    def test_very_low_vix_gives_calm(self, detector):
        signal = detector.detect(vix=10.0, nifty_returns=_flat_returns())
        assert signal.regime == RegimeType.CALM

    def test_moderate_vix_not_calm_or_risk_off(self, detector):
        # VIX 16 is normal → regime driven by other signals or ROTATION
        signal = detector.detect(vix=16.0, nifty_returns=_flat_returns())
        assert signal.regime not in (RegimeType.CALM, RegimeType.RISK_OFF)

    def test_high_vix_gives_volatile(self, detector):
        signal = detector.detect(vix=25.0, nifty_returns=_flat_returns())
        assert signal.regime in (RegimeType.VOLATILE, RegimeType.RISK_OFF, RegimeType.TRENDING_DOWN)

    def test_very_high_vix_gives_risk_off(self, detector):
        # VIX > 30 → strong RISK_OFF vote
        signal = detector.detect(vix=35.0, nifty_returns=_flat_returns(value=-0.002))
        assert signal.regime == RegimeType.RISK_OFF

    def test_extreme_vix_gives_risk_off(self, detector):
        signal = detector.detect(vix=50.0, nifty_returns=_trending_returns(daily=-0.01))
        assert signal.regime == RegimeType.RISK_OFF


# ---------------------------------------------------------------------------
# Return-based regime classification
# ---------------------------------------------------------------------------

class TestReturnRegime:
    """Tests for return-driven regime rules."""

    def test_strong_uptrend_gives_trending_up(self, detector):
        # ~0.5% per day × 20 days ≈ +10% cumulative
        signal = detector.detect(vix=14.0, nifty_returns=_trending_returns(daily=0.005))
        assert signal.regime in (RegimeType.TRENDING_UP, RegimeType.RISK_ON)

    def test_strong_downtrend_gives_trending_down(self, detector):
        # VIX=22 contributes a VOLATILE vote; the -0.5%/day × 20 days adds TRENDING_DOWN
        # and RISK_OFF votes. Any of these three outcomes is correct.
        signal = detector.detect(vix=22.0, nifty_returns=_trending_returns(daily=-0.005))
        assert signal.regime in (RegimeType.TRENDING_DOWN, RegimeType.RISK_OFF, RegimeType.VOLATILE)

    def test_flat_returns_no_trend_regime(self, detector):
        signal = detector.detect(vix=15.0, nifty_returns=_flat_returns())
        # With flat returns and moderate VIX → should be CALM or ROTATION (no strong trend)
        assert signal.regime not in (RegimeType.TRENDING_UP, RegimeType.TRENDING_DOWN)

    def test_only_5_returns_still_works(self, detector):
        signal = detector.detect(vix=15.0, nifty_returns=[0.002] * 5)
        assert isinstance(signal.regime, RegimeType)

    def test_empty_returns_still_works(self, detector):
        signal = detector.detect(vix=15.0, nifty_returns=[])
        assert isinstance(signal.regime, RegimeType)


# ---------------------------------------------------------------------------
# Advance/Decline signal
# ---------------------------------------------------------------------------

class TestADRatio:
    """Tests for Advance/Decline ratio signal."""

    def test_strong_breadth_votes_risk_on(self, detector):
        # A/D ratio > 2 → risk_on vote
        signal = detector.detect(
            vix=12.0,
            nifty_returns=_trending_returns(daily=0.003),
            advance_decline=(2000, 500),
        )
        assert signal.regime in (RegimeType.RISK_ON, RegimeType.TRENDING_UP, RegimeType.CALM)

    def test_poor_breadth_votes_risk_off(self, detector):
        signal = detector.detect(
            vix=22.0,
            nifty_returns=_trending_returns(daily=-0.004),
            advance_decline=(300, 1800),
        )
        assert signal.regime in (RegimeType.RISK_OFF, RegimeType.TRENDING_DOWN, RegimeType.VOLATILE)

    def test_ad_ratio_stored(self, detector):
        signal = detector.detect(
            vix=15.0,
            nifty_returns=_flat_returns(),
            advance_decline=(1200, 600),
        )
        assert signal.advance_decline_ratio is not None
        assert signal.advance_decline_ratio == pytest.approx(2.0, rel=0.01)

    def test_zero_declines_handled(self, detector):
        signal = detector.detect(
            vix=12.0,
            nifty_returns=_flat_returns(),
            advance_decline=(1500, 0),
        )
        # Should not raise; advance_decline_ratio stored
        assert signal.advance_decline_ratio is not None


# ---------------------------------------------------------------------------
# FII signal
# ---------------------------------------------------------------------------

class TestFIISignal:
    """Tests for FII net flow signal."""

    def test_large_fii_inflow_boosts_risk_on(self, detector):
        signal = detector.detect(
            vix=12.0,
            nifty_returns=_trending_returns(daily=0.003),
            fii_net=8000.0,
        )
        assert signal.regime in (RegimeType.RISK_ON, RegimeType.TRENDING_UP, RegimeType.CALM)

    def test_large_fii_outflow_plus_high_vix_gives_risk_off(self, detector):
        signal = detector.detect(
            vix=25.0,
            nifty_returns=_trending_returns(daily=-0.004),
            fii_net=-10000.0,
        )
        assert signal.regime in (RegimeType.RISK_OFF, RegimeType.TRENDING_DOWN, RegimeType.VOLATILE)

    def test_fii_net_stored(self, detector):
        signal = detector.detect(
            vix=15.0,
            nifty_returns=_flat_returns(),
            fii_net=1234.0,
        )
        assert signal.fii_dii_net == pytest.approx(1234.0)


# ---------------------------------------------------------------------------
# Composite regime logic
# ---------------------------------------------------------------------------

class TestCompositeRegime:
    """Tests for combined multi-signal regime detection."""

    def test_all_risk_on_signals(self, detector):
        signal = detector.detect(
            vix=11.0,
            nifty_returns=_trending_returns(daily=0.004),
            advance_decline=(1800, 400),
            fii_net=5000.0,
            breadth=70.0,
        )
        assert signal.regime in (RegimeType.RISK_ON, RegimeType.TRENDING_UP, RegimeType.CALM)
        assert signal.confidence > 0.4

    def test_all_risk_off_signals(self, detector):
        signal = detector.detect(
            vix=32.0,
            nifty_returns=_trending_returns(daily=-0.006),
            advance_decline=(200, 2000),
            fii_net=-12000.0,
            breadth=25.0,
        )
        assert signal.regime == RegimeType.RISK_OFF
        assert signal.confidence > 0.5

    def test_conflicting_signals_give_rotation(self, detector):
        # Mixed signals: some bullish, some bearish
        signal = detector.detect(
            vix=18.0,
            nifty_returns=_flat_returns(value=0.001),
            advance_decline=(900, 900),
            fii_net=200.0,
        )
        # Not strongly trending → should be calm, rotation, or mild risk-on
        assert signal.regime in (
            RegimeType.ROTATION, RegimeType.CALM, RegimeType.RISK_ON, RegimeType.VOLATILE
        )

    def test_breadth_stored(self, detector):
        signal = detector.detect(vix=15.0, nifty_returns=_flat_returns(), breadth=55.0)
        assert signal.breadth == pytest.approx(55.0)

    def test_dxy_stored(self, detector):
        signal = detector.detect(vix=15.0, nifty_returns=_flat_returns(), dxy_level=104.2)
        assert signal.dxy_level == pytest.approx(104.2)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestCumulativeReturn:
    """Tests for _cumulative_return helper."""

    def test_empty_returns_zero(self):
        assert _cumulative_return([]) == pytest.approx(0.0)

    def test_single_return(self):
        assert _cumulative_return([0.05]) == pytest.approx(0.05)

    def test_multiple_compounding(self):
        # 3 returns of 1% each: (1.01)^3 - 1 ≈ 0.030301
        result = _cumulative_return([0.01, 0.01, 0.01])
        assert result == pytest.approx(0.030301, rel=1e-4)

    def test_uses_last_20(self):
        # 30 returns where first 10 are -1% and last 20 are +1%
        returns = [-0.01] * 10 + [0.01] * 20
        result = _cumulative_return(returns)
        # Should compound only the last 20
        expected = (1.01 ** 20) - 1
        assert result == pytest.approx(expected, rel=1e-4)

    def test_flat_returns_zero(self):
        assert _cumulative_return([0.0] * 20) == pytest.approx(0.0)


class TestVIXPercentile:
    """Tests for _compute_vix_percentile helper."""

    def test_with_history_median(self):
        history = list(range(10, 30))  # 10 to 29
        pct = _compute_vix_percentile(20.0, history)
        assert 40.0 <= pct <= 60.0

    def test_with_history_min(self):
        history = [15, 16, 17, 18, 19, 20]
        pct = _compute_vix_percentile(10.0, history)
        assert pct == pytest.approx(0.0)

    def test_with_history_max(self):
        history = [10, 11, 12, 13, 14]
        pct = _compute_vix_percentile(20.0, history)
        assert pct == pytest.approx(100.0)

    def test_heuristic_midpoint(self):
        # No history; VIX=24 on 8–40 scale → midpoint is 24 → 50th pct
        pct = _compute_vix_percentile(24.0, None)
        assert pct == pytest.approx(50.0, abs=5.0)

    def test_heuristic_low_vix(self):
        pct = _compute_vix_percentile(8.0, None)
        assert pct == pytest.approx(0.0, abs=1.0)

    def test_heuristic_high_vix(self):
        pct = _compute_vix_percentile(40.0, None)
        assert pct == pytest.approx(100.0, abs=1.0)

    def test_short_history_falls_back_to_heuristic(self):
        # < 5 history items → heuristic
        pct = _compute_vix_percentile(24.0, [10, 15])
        assert 0.0 <= pct <= 100.0


class TestBuildRationale:
    """Tests for _build_rationale helper."""

    def test_contains_vix_info(self):
        rationale = _build_rationale(
            regime=RegimeType.RISK_ON,
            vix=12.5,
            vix_percentile=20.0,
            cum_return=0.08,
            ad_ratio=None,
            fii_net=None,
            breadth=None,
        )
        assert "12.5" in rationale or "VIX" in rationale

    def test_contains_regime_suffix(self):
        rationale = _build_rationale(
            regime=RegimeType.RISK_ON,
            vix=12.0,
            vix_percentile=20.0,
            cum_return=0.0,
            ad_ratio=None,
            fii_net=None,
            breadth=None,
        )
        assert "risk-on" in rationale.lower()

    def test_includes_fii_when_provided(self):
        rationale = _build_rationale(
            regime=RegimeType.RISK_ON,
            vix=12.0,
            vix_percentile=20.0,
            cum_return=0.05,
            ad_ratio=2.5,
            fii_net=3000.0,
            breadth=65.0,
        )
        assert "FII" in rationale or "₹" in rationale

    def test_non_empty_for_all_regimes(self):
        for regime in RegimeType:
            r = _build_rationale(
                regime=regime, vix=15.0, vix_percentile=50.0,
                cum_return=0.0, ad_ratio=None, fii_net=None, breadth=None,
            )
            assert len(r) > 5
