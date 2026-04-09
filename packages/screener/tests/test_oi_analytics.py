"""Tests for the enhanced OI analytics module.

All tests use synthetic OISnapshot data — no API calls are made.
"""

from __future__ import annotations

import pytest

from packages.screener.src.oi_analytics import (
    OIAnalytics,
    OIChangeAnalysis,
    OIHeatmapData,
    OISnapshot,
    SupportResistanceLevels,
    UnusualOIEntry,
    _classify_signal,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_chain(
    spot: float = 24000.0,
    step: float = 100.0,
    count: int = 5,
) -> list[OISnapshot]:
    """Build a synthetic chain centred on spot."""
    chain = []
    for i in range(-count, count + 1):
        k = spot + i * step
        dist = abs(i)
        ce_oi = max(500, 50000 - dist * 4000)
        pe_oi = max(500, 40000 - dist * 3500)
        ce_change = int(ce_oi * 0.05 * (1 if i <= 0 else -1))
        pe_change = int(pe_oi * 0.04 * (-1 if i <= 0 else 1))
        chain.append(OISnapshot(
            strike=k,
            ce_oi=ce_oi,
            pe_oi=pe_oi,
            ce_change=ce_change,
            pe_change=pe_change,
            ce_volume=ce_oi // 10,
            pe_volume=pe_oi // 10,
            ce_ltp=max(1.0, 200.0 - max(0, i) * 15),
            pe_ltp=max(1.0, 200.0 + min(0, i) * 15),
        ))
    return chain


@pytest.fixture
def chain() -> list[OISnapshot]:
    return _make_chain()


@pytest.fixture
def analytics() -> OIAnalytics:
    return OIAnalytics()


# ---------------------------------------------------------------------------
# OISnapshot model
# ---------------------------------------------------------------------------


class TestOISnapshot:
    def test_pcr_zero_ce_oi(self):
        s = OISnapshot(strike=24000.0, ce_oi=0, pe_oi=5000)
        assert s.pcr == 0.0

    def test_pcr_normal(self):
        s = OISnapshot(strike=24000.0, ce_oi=10000, pe_oi=12000)
        assert abs(s.pcr - 1.2) < 0.001

    def test_total_oi(self):
        s = OISnapshot(strike=24000.0, ce_oi=10000, pe_oi=8000)
        assert s.total_oi == 18000

    def test_defaults(self):
        s = OISnapshot(strike=25000.0)
        assert s.ce_oi == 0
        assert s.pe_oi == 0
        assert s.ce_change == 0
        assert s.pe_change == 0


# ---------------------------------------------------------------------------
# _classify_signal
# ---------------------------------------------------------------------------


class TestClassifySignal:
    def test_price_up_oi_up_long_buildup(self):
        label, code = _classify_signal("up", 1000)
        assert code == "LB"
        assert "Long Build-up" in label

    def test_price_up_oi_down_short_covering(self):
        label, code = _classify_signal("up", -500)
        assert code == "SC"

    def test_price_down_oi_up_short_buildup(self):
        label, code = _classify_signal("down", 2000)
        assert code == "SB"

    def test_price_down_oi_down_long_unwinding(self):
        label, code = _classify_signal("down", -800)
        assert code == "LU"

    def test_flat_oi_addition(self):
        label, code = _classify_signal("flat", 500)
        assert code == "OA"

    def test_flat_oi_reduction(self):
        label, code = _classify_signal("flat", -200)
        assert code == "OR"

    def test_flat_flat_neutral(self):
        label, code = _classify_signal("flat", 0)
        assert code == "N"


# ---------------------------------------------------------------------------
# OIAnalytics.oi_heatmap
# ---------------------------------------------------------------------------


class TestOIHeatmap:
    def test_returns_heatmap_data(self, analytics: OIAnalytics, chain: list[OISnapshot]):
        result = analytics.oi_heatmap(chain)
        assert isinstance(result, OIHeatmapData)

    def test_empty_chain_returns_empty(self, analytics: OIAnalytics):
        result = analytics.oi_heatmap([])
        assert result.entries == []
        assert result.total_ce_oi == 0

    def test_entries_sorted_by_strike(self, analytics: OIAnalytics, chain: list[OISnapshot]):
        result = analytics.oi_heatmap(chain, n_strikes=20)
        strikes = [e.strike for e in result.entries]
        assert strikes == sorted(strikes)

    def test_n_strikes_limit(self, analytics: OIAnalytics, chain: list[OISnapshot]):
        result = analytics.oi_heatmap(chain, n_strikes=5)
        assert len(result.entries) <= 5

    def test_pct_values_in_0_100(self, analytics: OIAnalytics, chain: list[OISnapshot]):
        result = analytics.oi_heatmap(chain, n_strikes=20)
        for e in result.entries:
            assert 0.0 <= e.ce_oi_pct <= 100.0
            assert 0.0 <= e.pe_oi_pct <= 100.0

    def test_max_strike_has_100_pct(self, analytics: OIAnalytics, chain: list[OISnapshot]):
        result = analytics.oi_heatmap(chain, n_strikes=20)
        ce_pcts = [e.ce_oi_pct for e in result.entries]
        pe_pcts = [e.pe_oi_pct for e in result.entries]
        assert max(ce_pcts) == pytest.approx(100.0, abs=0.01)
        assert max(pe_pcts) == pytest.approx(100.0, abs=0.01)

    def test_atm_flag_with_spot(self, analytics: OIAnalytics, chain: list[OISnapshot]):
        spot = 24000.0
        result = analytics.oi_heatmap(chain, n_strikes=20, spot=spot)
        atm_entries = [e for e in result.entries if e.is_atm]
        assert len(atm_entries) == 1
        assert atm_entries[0].strike == 24000.0

    def test_atm_flag_no_spot(self, analytics: OIAnalytics, chain: list[OISnapshot]):
        result = analytics.oi_heatmap(chain, n_strikes=20)
        atm_entries = [e for e in result.entries if e.is_atm]
        assert len(atm_entries) == 0

    def test_overall_pcr_positive(self, analytics: OIAnalytics, chain: list[OISnapshot]):
        result = analytics.oi_heatmap(chain)
        assert result.overall_pcr >= 0

    def test_max_oi_strikes(self, analytics: OIAnalytics):
        chain = [
            OISnapshot(strike=23000.0, ce_oi=80000, pe_oi=10000),
            OISnapshot(strike=24000.0, ce_oi=20000, pe_oi=90000),
            OISnapshot(strike=25000.0, ce_oi=15000, pe_oi=5000),
        ]
        result = analytics.oi_heatmap(chain, n_strikes=10)
        assert result.max_ce_oi_strike == 23000.0
        assert result.max_pe_oi_strike == 24000.0


# ---------------------------------------------------------------------------
# OIAnalytics.oi_change_analysis
# ---------------------------------------------------------------------------


class TestOIChangeAnalysis:
    def test_returns_oi_change_analysis(self, analytics: OIAnalytics, chain: list[OISnapshot]):
        result = analytics.oi_change_analysis(chain, price_change="up")
        assert isinstance(result, OIChangeAnalysis)

    def test_signals_count(self, analytics: OIAnalytics, chain: list[OISnapshot]):
        result = analytics.oi_change_analysis(chain)
        # 2 signals per strike (CE + PE)
        assert len(result.signals) == len(chain) * 2

    def test_price_up_oi_up_long_buildup_lists(self, analytics: OIAnalytics):
        chain = [
            OISnapshot(strike=24000.0, ce_oi=50000, pe_oi=40000,
                       ce_change=5000, pe_change=3000),
        ]
        result = analytics.oi_change_analysis(chain, price_change="up")
        assert 24000.0 in result.long_buildups

    def test_price_up_oi_down_short_covering(self, analytics: OIAnalytics):
        chain = [
            OISnapshot(strike=24000.0, ce_oi=50000, pe_oi=40000,
                       ce_change=-3000, pe_change=-2000),
        ]
        result = analytics.oi_change_analysis(chain, price_change="up")
        assert 24000.0 in result.short_coverings

    def test_price_down_oi_up_short_buildup(self, analytics: OIAnalytics):
        chain = [
            OISnapshot(strike=24000.0, ce_oi=50000, pe_oi=40000,
                       ce_change=5000, pe_change=4000),
        ]
        result = analytics.oi_change_analysis(chain, price_change="down")
        assert 24000.0 in result.short_buildups

    def test_price_down_oi_down_long_unwinding(self, analytics: OIAnalytics):
        chain = [
            OISnapshot(strike=24000.0, ce_oi=50000, pe_oi=40000,
                       ce_change=-4000, pe_change=-3000),
        ]
        result = analytics.oi_change_analysis(chain, price_change="down")
        assert 24000.0 in result.long_unwindings

    def test_summary_keys_are_strings(self, analytics: OIAnalytics, chain: list[OISnapshot]):
        result = analytics.oi_change_analysis(chain)
        assert all(isinstance(k, str) for k in result.summary.keys())

    def test_summary_counts_sum_to_signal_count(self, analytics: OIAnalytics, chain: list[OISnapshot]):
        result = analytics.oi_change_analysis(chain)
        assert sum(result.summary.values()) == len(result.signals)

    def test_empty_chain(self, analytics: OIAnalytics):
        result = analytics.oi_change_analysis([])
        assert result.signals == []
        assert result.long_buildups == []
        assert result.summary == {}


# ---------------------------------------------------------------------------
# OIAnalytics.support_resistance_from_oi
# ---------------------------------------------------------------------------


class TestSupportResistance:
    def test_returns_levels(self, analytics: OIAnalytics, chain: list[OISnapshot]):
        result = analytics.support_resistance_from_oi(chain)
        assert isinstance(result, SupportResistanceLevels)

    def test_resistance_is_max_ce_oi(self, analytics: OIAnalytics):
        chain = [
            OISnapshot(strike=23000.0, ce_oi=100000, pe_oi=20000),
            OISnapshot(strike=24000.0, ce_oi=40000, pe_oi=80000),
            OISnapshot(strike=25000.0, ce_oi=20000, pe_oi=10000),
        ]
        result = analytics.support_resistance_from_oi(chain)
        assert result.resistance_strike == 23000.0
        assert result.resistance_oi == 100000

    def test_support_is_max_pe_oi(self, analytics: OIAnalytics):
        chain = [
            OISnapshot(strike=23000.0, ce_oi=100000, pe_oi=20000),
            OISnapshot(strike=24000.0, ce_oi=40000, pe_oi=80000),
            OISnapshot(strike=25000.0, ce_oi=20000, pe_oi=10000),
        ]
        result = analytics.support_resistance_from_oi(chain)
        assert result.support_strike == 24000.0
        assert result.support_oi == 80000

    def test_secondary_levels_present(self, analytics: OIAnalytics):
        chain = _make_chain(count=5)
        result = analytics.support_resistance_from_oi(chain)
        assert result.secondary_resistance is not None
        assert result.secondary_support is not None
        assert result.secondary_resistance != result.resistance_strike
        assert result.secondary_support != result.support_strike

    def test_secondary_levels_absent_for_single_strike(self, analytics: OIAnalytics):
        chain = [OISnapshot(strike=24000.0, ce_oi=50000, pe_oi=40000)]
        result = analytics.support_resistance_from_oi(chain)
        assert result.secondary_resistance is None
        assert result.secondary_support is None

    def test_empty_chain(self, analytics: OIAnalytics):
        result = analytics.support_resistance_from_oi([])
        assert result.resistance_strike == 0.0
        assert result.support_strike == 0.0


# ---------------------------------------------------------------------------
# OIAnalytics.unusual_oi_activity
# ---------------------------------------------------------------------------


class TestUnusualOIActivity:
    def test_returns_list(self, analytics: OIAnalytics, chain: list[OISnapshot]):
        result = analytics.unusual_oi_activity(chain)
        assert isinstance(result, list)

    def test_entries_are_unusual_oi_entry(self, analytics: OIAnalytics, chain: list[OISnapshot]):
        result = analytics.unusual_oi_activity(chain, threshold=1.0)
        assert all(isinstance(e, UnusualOIEntry) for e in result)

    def test_sorted_by_abs_z_score(self, analytics: OIAnalytics, chain: list[OISnapshot]):
        result = analytics.unusual_oi_activity(chain, threshold=0.0)
        z_scores = [abs(e.z_score) for e in result]
        assert z_scores == sorted(z_scores, reverse=True)

    def test_detects_spike(self, analytics: OIAnalytics):
        """A strike with a huge OI change should be flagged as unusual."""
        chain = [OISnapshot(strike=float(k), ce_oi=50000, pe_oi=40000,
                             ce_change=100 if k != 25 else 90000,
                             pe_change=50)
                 for k in range(20, 31)]
        result = analytics.unusual_oi_activity(chain, threshold=1.5)
        assert any(e.strike == 25.0 and e.option_type == "CE" for e in result)

    def test_direction_addition(self, analytics: OIAnalytics):
        chain = [OISnapshot(strike=24000.0, ce_oi=50000, pe_oi=40000,
                             ce_change=20000, pe_change=50)]
        result = analytics.unusual_oi_activity(chain, threshold=0.0)
        ce_entries = [e for e in result if e.option_type == "CE"]
        if ce_entries:
            assert ce_entries[0].direction == "addition"

    def test_direction_reduction(self, analytics: OIAnalytics):
        chain = [OISnapshot(strike=24000.0, ce_oi=50000, pe_oi=40000,
                             ce_change=-20000, pe_change=50)]
        result = analytics.unusual_oi_activity(chain, threshold=0.0)
        ce_entries = [e for e in result if e.option_type == "CE"]
        if ce_entries:
            assert ce_entries[0].direction == "reduction"

    def test_high_threshold_returns_fewer(self, analytics: OIAnalytics, chain: list[OISnapshot]):
        low_count = len(analytics.unusual_oi_activity(chain, threshold=0.5))
        high_count = len(analytics.unusual_oi_activity(chain, threshold=3.0))
        assert high_count <= low_count

    def test_empty_chain(self, analytics: OIAnalytics):
        assert analytics.unusual_oi_activity([]) == []

    def test_uniform_changes_zero_std(self, analytics: OIAnalytics):
        """All same OI change → std = 0, no z-score, nothing flagged at threshold=1."""
        chain = [OISnapshot(strike=float(k), ce_oi=50000, pe_oi=40000,
                             ce_change=1000, pe_change=500)
                 for k in range(20, 26)]
        result = analytics.unusual_oi_activity(chain, threshold=1.0)
        # z=0 for all, so nothing should exceed threshold=1
        assert result == []


# ---------------------------------------------------------------------------
# OIAnalytics.oi_trend
# ---------------------------------------------------------------------------


class TestOITrend:
    def test_empty_history(self, analytics: OIAnalytics):
        result = analytics.oi_trend([])
        assert result["sessions"] == []
        assert result["ce_trend"] == "flat"

    def test_returns_correct_keys(self, analytics: OIAnalytics, chain: list[OISnapshot]):
        history = [chain, chain, chain]
        result = analytics.oi_trend(history)
        assert "sessions" in result
        assert "ce_trend" in result
        assert "pe_trend" in result
        assert "pcr_trend" in result

    def test_session_count_limited_by_n_sessions(self, analytics: OIAnalytics, chain: list[OISnapshot]):
        history = [chain] * 10
        result = analytics.oi_trend(history, n_sessions=5)
        assert len(result["sessions"]) == 5

    def test_session_count_all_when_less_than_n(self, analytics: OIAnalytics, chain: list[OISnapshot]):
        history = [chain, chain, chain]
        result = analytics.oi_trend(history, n_sessions=5)
        assert len(result["sessions"]) == 3

    def test_trend_up_when_oi_increases(self, analytics: OIAnalytics):
        """OI increasing each session → ce_trend should be 'up'."""
        sessions = []
        for multiplier in [0.8, 0.9, 1.0, 1.1, 1.2]:
            snap = [OISnapshot(strike=24000.0,
                               ce_oi=int(50000 * multiplier),
                               pe_oi=int(40000 * multiplier))]
            sessions.append(snap)
        result = analytics.oi_trend(sessions, n_sessions=5)
        assert result["ce_trend"] == "up"

    def test_trend_down_when_oi_decreases(self, analytics: OIAnalytics):
        sessions = []
        for multiplier in [1.2, 1.1, 1.0, 0.9, 0.8]:
            snap = [OISnapshot(strike=24000.0,
                               ce_oi=int(50000 * multiplier),
                               pe_oi=int(40000 * multiplier))]
            sessions.append(snap)
        result = analytics.oi_trend(sessions, n_sessions=5)
        assert result["ce_trend"] == "down"

    def test_session_pcr_values(self, analytics: OIAnalytics):
        snap = [OISnapshot(strike=24000.0, ce_oi=10000, pe_oi=12000)]
        result = analytics.oi_trend([snap], n_sessions=1)
        session = result["sessions"][0]
        assert abs(session["overall_pcr"] - 1.2) < 0.001

    def test_trend_direction_values(self, analytics: OIAnalytics, chain: list[OISnapshot]):
        history = [chain] * 5
        result = analytics.oi_trend(history, n_sessions=5)
        assert result["ce_trend"] in ("up", "down", "flat")
        assert result["pe_trend"] in ("up", "down", "flat")
        assert result["pcr_trend"] in ("up", "down", "flat")
