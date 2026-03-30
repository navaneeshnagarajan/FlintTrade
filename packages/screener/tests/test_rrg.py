"""Tests for the RRG (Relative Rotation Graph) computation module.

Tests cover:
- EWM smoothing correctness
- Rolling z-score output range
- compute_rrg tail length and structure
- classify_quadrant correctness for all four quadrants + edge cases
- build_sector_rrg multi-sector output structure
- RRG GET endpoint via Flask test client (sample data path)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure repo root on sys.path
_REPO_ROOT = str(Path(__file__).resolve().parents[4])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from packages.screener.src.rrg import (
    NIFTY_SECTORS,
    _Series,
    _ewm_smooth,
    _rolling_zscore,
    build_sector_rrg,
    classify_quadrant,
    compute_rrg,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_series(n: int = 60, start: float = 100.0, drift: float = 0.001) -> _Series:
    """Generates a deterministic trending series for testing."""
    dates = [f"2025-{(i // 4) + 1:02d}-{((i % 4) * 7) + 1:02d}" for i in range(n)]
    values = [start * ((1 + drift) ** i) for i in range(n)]
    return _Series(dates=dates, values=values)


def _make_benchmark(n: int = 60) -> _Series:
    """Flat benchmark series (all 100.0) to isolate sector RS easily."""
    dates = [f"2025-{(i // 4) + 1:02d}-{((i % 4) * 7) + 1:02d}" for i in range(n)]
    values = [100.0] * n
    return _Series(dates=dates, values=values)


# ---------------------------------------------------------------------------
# EWM smoothing
# ---------------------------------------------------------------------------


class TestEWMSmooth:
    def test_output_length_matches_input(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = _ewm_smooth(values, span=3)
        assert len(result) == len(values)

    def test_first_value_unchanged(self):
        values = [10.0, 20.0, 30.0]
        result = _ewm_smooth(values, span=5)
        assert result[0] == pytest.approx(10.0)

    def test_smoothed_lies_between_extremes(self):
        values = [1.0, 100.0, 1.0, 100.0, 1.0]
        result = _ewm_smooth(values, span=3)
        # Smoothed values should be between the min and max of input
        for v in result:
            assert 1.0 <= v <= 100.0

    def test_constant_series_unchanged(self):
        values = [50.0] * 10
        result = _ewm_smooth(values, span=5)
        for v in result:
            assert v == pytest.approx(50.0)

    def test_empty_input_returns_empty(self):
        assert _ewm_smooth([], span=3) == []

    def test_alpha_formula_single_step(self):
        """Verify alpha = 2/(span+1) with manual calculation."""
        values = [10.0, 20.0]
        span = 3
        alpha = 2.0 / (span + 1)  # = 0.5
        result = _ewm_smooth(values, span=span)
        expected_1 = alpha * 20.0 + (1 - alpha) * 10.0
        assert result[1] == pytest.approx(expected_1)


# ---------------------------------------------------------------------------
# Rolling z-score
# ---------------------------------------------------------------------------


class TestRollingZScore:
    def test_output_length_matches_input(self):
        values = [100.0 + i * 0.5 for i in range(30)]
        result = _rolling_zscore(values, window=10)
        assert len(result) == len(values)

    def test_neutral_when_insufficient_data(self):
        """First value (window=1) should be rescale_center (100)."""
        values = [99.5, 100.0, 100.5]
        result = _rolling_zscore(values, window=10)
        # With only 1 value in window, should return center
        assert result[0] == pytest.approx(100.0)

    def test_output_near_center_for_stable_series(self):
        """A near-flat series should stay near 100 after z-scoring."""
        values = [100.0 + 0.001 * i for i in range(60)]
        result = _rolling_zscore(values, window=52)
        # All values should be within a reasonable range of 100
        for v in result:
            assert 90.0 <= v <= 110.0, f"Value {v} out of expected range"

    def test_output_is_floats(self):
        values = [float(i) for i in range(1, 20)]
        result = _rolling_zscore(values, window=5)
        assert all(isinstance(v, float) for v in result)


# ---------------------------------------------------------------------------
# compute_rrg
# ---------------------------------------------------------------------------


class TestComputeRRG:
    def test_returns_list_of_rrg_points(self):
        sector = _make_series(60, drift=0.002)
        bench = _make_benchmark(60)
        tail = compute_rrg(sector, bench, tail_length=12)
        assert isinstance(tail, list)
        assert len(tail) > 0

    def test_tail_length_respected(self):
        sector = _make_series(60, drift=0.001)
        bench = _make_benchmark(60)
        for tl in [4, 8, 12]:
            tail = compute_rrg(sector, bench, tail_length=tl)
            assert len(tail) <= tl

    def test_each_point_has_required_keys(self):
        sector = _make_series(60)
        bench = _make_benchmark(60)
        tail = compute_rrg(sector, bench, tail_length=6)
        for pt in tail:
            assert "date" in pt
            assert "rs_ratio" in pt
            assert "rs_momentum" in pt

    def test_dates_are_strings(self):
        sector = _make_series(60)
        bench = _make_benchmark(60)
        tail = compute_rrg(sector, bench, tail_length=6)
        for pt in tail:
            assert isinstance(pt["date"], str)

    def test_rs_ratio_is_float(self):
        sector = _make_series(60)
        bench = _make_benchmark(60)
        tail = compute_rrg(sector, bench, tail_length=6)
        for pt in tail:
            assert isinstance(pt["rs_ratio"], float)
            assert isinstance(pt["rs_momentum"], float)

    def test_insufficient_data_returns_empty(self):
        sector = _Series(dates=["2025-01-01", "2025-01-08"], values=[100.0, 101.0])
        bench = _Series(dates=["2025-01-01", "2025-01-08"], values=[100.0, 100.0])
        tail = compute_rrg(sector, bench, tail_length=12)
        assert tail == []

    def test_non_overlapping_dates_returns_empty(self):
        sector = _Series(dates=["2025-01-01"], values=[100.0])
        bench = _Series(dates=["2025-06-01"], values=[100.0])
        tail = compute_rrg(sector, bench, tail_length=12)
        assert tail == []

    def test_tail_ordered_oldest_to_newest(self):
        """Tail dates should be in ascending chronological order."""
        sector = _make_series(60)
        bench = _make_benchmark(60)
        tail = compute_rrg(sector, bench, tail_length=12)
        if len(tail) >= 2:
            for i in range(1, len(tail)):
                assert tail[i]["date"] >= tail[i - 1]["date"]

    def test_strong_outperformer_has_high_rs_ratio(self):
        """Sector consistently above benchmark → final rs_ratio should be > 100."""
        # Sector grows at 0.5% per week, benchmark flat
        sector = _make_series(60, start=100.0, drift=0.005)
        bench = _make_benchmark(60)
        tail = compute_rrg(sector, bench, tail_length=12)
        if tail:
            # The strongly outperforming sector should have above-neutral RS-Ratio
            assert tail[-1]["rs_ratio"] > 100.0


# ---------------------------------------------------------------------------
# classify_quadrant
# ---------------------------------------------------------------------------


class TestClassifyQuadrant:
    def _point(self, rs_ratio: float, rs_momentum: float):
        from packages.screener.src.rrg import RRGPoint
        return [RRGPoint(date="2025-01-01", rs_ratio=rs_ratio, rs_momentum=rs_momentum)]

    def test_leading_quadrant(self):
        assert classify_quadrant(self._point(101.0, 101.0)) == "leading"

    def test_weakening_quadrant(self):
        assert classify_quadrant(self._point(101.0, 99.0)) == "weakening"

    def test_lagging_quadrant(self):
        assert classify_quadrant(self._point(99.0, 99.0)) == "lagging"

    def test_improving_quadrant(self):
        assert classify_quadrant(self._point(99.0, 101.0)) == "improving"

    def test_empty_tail_returns_neutral(self):
        assert classify_quadrant([]) == "neutral"

    def test_at_100_boundary_rs_ratio_classifies_as_leading(self):
        """At exactly 100.0 (boundary) — should classify as leading (>= 100)."""
        assert classify_quadrant(self._point(100.0, 100.0)) == "leading"

    def test_uses_last_point(self):
        """Should use the last (most recent) tail point, not the first."""
        from packages.screener.src.rrg import RRGPoint
        tail = [
            RRGPoint(date="2024-12-01", rs_ratio=99.0, rs_momentum=99.0),  # lagging
            RRGPoint(date="2025-01-01", rs_ratio=101.0, rs_momentum=101.0),  # leading
        ]
        assert classify_quadrant(tail) == "leading"


# ---------------------------------------------------------------------------
# build_sector_rrg
# ---------------------------------------------------------------------------


class TestBuildSectorRRG:
    def test_returns_list(self):
        bench = _make_benchmark(60)
        sector_prices = {
            sym: _make_series(60, drift=0.001)
            for sym, _ in NIFTY_SECTORS
        }
        results = build_sector_rrg(sector_prices, bench, tail_length=8)
        assert isinstance(results, list)

    def test_each_result_has_required_keys(self):
        bench = _make_benchmark(60)
        sector_prices = {
            sym: _make_series(60, drift=0.001)
            for sym, _ in NIFTY_SECTORS
        }
        results = build_sector_rrg(sector_prices, bench, tail_length=8)
        for r in results:
            assert "symbol" in r
            assert "name" in r
            assert "tail" in r
            assert "current_quadrant" in r

    def test_all_quadrants_are_valid_strings(self):
        bench = _make_benchmark(60)
        sector_prices = {
            sym: _make_series(60, drift=0.001)
            for sym, _ in NIFTY_SECTORS
        }
        valid = {"leading", "weakening", "lagging", "improving", "neutral"}
        results = build_sector_rrg(sector_prices, bench, tail_length=8)
        for r in results:
            assert r["current_quadrant"] in valid

    def test_missing_sector_is_skipped(self):
        """Sectors with no price data should be silently skipped."""
        bench = _make_benchmark(60)
        # Provide data for only 3 sectors
        sector_prices = {
            sym: _make_series(60)
            for sym, _ in NIFTY_SECTORS[:3]
        }
        results = build_sector_rrg(sector_prices, bench, tail_length=8)
        assert len(results) <= 3

    def test_empty_sector_prices_returns_empty_list(self):
        bench = _make_benchmark(60)
        results = build_sector_rrg({}, bench, tail_length=8)
        assert results == []

    def test_symbol_names_match_nifty_sectors_config(self):
        bench = _make_benchmark(60)
        sector_prices = {
            sym: _make_series(60)
            for sym, _ in NIFTY_SECTORS
        }
        results = build_sector_rrg(sector_prices, bench, tail_length=8)
        result_symbols = {r["symbol"] for r in results}
        config_symbols = {sym for sym, _ in NIFTY_SECTORS}
        # All returned symbols must be from the config universe
        assert result_symbols.issubset(config_symbols)


# ---------------------------------------------------------------------------
# Flask endpoint (sample data path)
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    """Minimal Flask app with only the analysis blueprint."""
    from flask import Flask
    from packages.screener.src.analysis_routes import analysis_bp

    flask_app = Flask("test_rrg")
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(analysis_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


class TestRRGEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/v1/rrg/sectors")
        assert resp.status_code == 200

    def test_status_ok(self, client):
        data = resp = client.get("/v1/rrg/sectors")
        import json
        parsed = json.loads(resp.data)
        assert parsed["status"] == "ok"

    def test_has_sectors_key(self, client):
        import json
        resp = client.get("/v1/rrg/sectors")
        parsed = json.loads(resp.data)
        assert "sectors" in parsed

    def test_sectors_is_list(self, client):
        import json
        resp = client.get("/v1/rrg/sectors")
        parsed = json.loads(resp.data)
        assert isinstance(parsed["sectors"], list)

    def test_has_12_sectors(self, client):
        import json
        resp = client.get("/v1/rrg/sectors")
        parsed = json.loads(resp.data)
        assert len(parsed["sectors"]) == len(NIFTY_SECTORS)

    def test_each_sector_has_required_fields(self, client):
        import json
        resp = client.get("/v1/rrg/sectors")
        parsed = json.loads(resp.data)
        for sector in parsed["sectors"]:
            assert "symbol" in sector
            assert "name" in sector
            assert "tail" in sector
            assert "current_quadrant" in sector

    def test_tail_not_empty(self, client):
        import json
        resp = client.get("/v1/rrg/sectors")
        parsed = json.loads(resp.data)
        for sector in parsed["sectors"]:
            assert len(sector["tail"]) > 0

    def test_tail_points_have_required_keys(self, client):
        import json
        resp = client.get("/v1/rrg/sectors")
        parsed = json.loads(resp.data)
        for sector in parsed["sectors"]:
            for pt in sector["tail"]:
                assert "date" in pt
                assert "rs_ratio" in pt
                assert "rs_momentum" in pt

    def test_is_sample_data_flag_present(self, client):
        import json
        resp = client.get("/v1/rrg/sectors")
        parsed = json.loads(resp.data)
        assert "is_sample_data" in parsed

    def test_benchmark_field_present(self, client):
        import json
        resp = client.get("/v1/rrg/sectors")
        parsed = json.loads(resp.data)
        assert parsed["benchmark"] == "NIFTY 50"

    def test_tail_length_query_param(self, client):
        import json
        resp = client.get("/v1/rrg/sectors?tail_length=6")
        parsed = json.loads(resp.data)
        assert parsed["tail_length"] == 6
        for sector in parsed["sectors"]:
            assert len(sector["tail"]) <= 6

    def test_tail_length_clamped_min(self, client):
        import json
        resp = client.get("/v1/rrg/sectors?tail_length=1")
        parsed = json.loads(resp.data)
        # Clamped to minimum of 4
        assert parsed["tail_length"] == 4

    def test_tail_length_clamped_max(self, client):
        import json
        resp = client.get("/v1/rrg/sectors?tail_length=999")
        parsed = json.loads(resp.data)
        # Clamped to maximum of 52
        assert parsed["tail_length"] == 52

    def test_quadrant_values_valid(self, client):
        import json
        resp = client.get("/v1/rrg/sectors")
        parsed = json.loads(resp.data)
        valid = {"leading", "weakening", "lagging", "improving", "neutral"}
        for sector in parsed["sectors"]:
            assert sector["current_quadrant"] in valid
