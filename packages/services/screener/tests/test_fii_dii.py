"""Tests for FII/DII institutional flow data module.

All tests use synthetic data or in-memory DuckDB — no NSE API calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from flinttrade_screener import fii_dii
from flinttrade_screener.fii_dii import (
    FiiDiiSnapshot,
    FiiDiiTracker,
    FiiDiiTrend,
    FiiLongShortRatio,
    _bias_label,
    _compute_sentiment,
    _parse_fao_csv,
    _transform_data,
    compute_fii_long_short,
    make_sample_fii_dii,
    make_sample_trend,
)


# ---------------------------------------------------------------------------
# FiiDiiSnapshot dataclass
# ---------------------------------------------------------------------------


class TestFiiDiiSnapshot:
    """Verify FiiDiiSnapshot creation and serialisation."""

    def test_default_values(self):
        snap = FiiDiiSnapshot()
        assert snap.trade_date == ""
        assert snap.fii_net == 0.0
        assert snap.dii_net == 0.0
        assert snap.sentiment_score == 50.0

    def test_to_dict(self):
        snap = FiiDiiSnapshot(trade_date="01-Apr-2026", fii_net=-500.0)
        d = snap.to_dict()
        assert d["trade_date"] == "01-Apr-2026"
        assert d["fii_net"] == -500.0
        assert isinstance(d, dict)

    def test_custom_values(self):
        snap = FiiDiiSnapshot(
            trade_date="02-Apr-2026",
            fii_buy=12000.0,
            fii_sell=13000.0,
            fii_net=-1000.0,
            dii_buy=11000.0,
            dii_sell=10000.0,
            dii_net=1000.0,
            pcr=0.85,
            sentiment_score=45.0,
        )
        assert snap.fii_buy == 12000.0
        assert snap.dii_net == 1000.0
        assert snap.pcr == 0.85


# ---------------------------------------------------------------------------
# FiiDiiTrend
# ---------------------------------------------------------------------------


class TestFiiDiiTrend:
    """Verify FiiDiiTrend aggregation."""

    def test_empty_trend(self):
        trend = FiiDiiTrend()
        assert trend.days == 0
        assert trend.snapshots == []

    def test_to_dict(self):
        snap = FiiDiiSnapshot(trade_date="01-Apr-2026", fii_net=100.0)
        trend = FiiDiiTrend(
            days=1,
            snapshots=[snap],
            fii_net_total=100.0,
            dii_net_total=0.0,
            avg_sentiment=50.0,
        )
        d = trend.to_dict()
        assert d["days"] == 1
        assert len(d["snapshots"]) == 1
        assert d["fii_net_total"] == 100.0


# ---------------------------------------------------------------------------
# Sentiment computation
# ---------------------------------------------------------------------------


class TestSentimentComputation:
    """Verify the sentiment scoring heuristic from fii-dii-data."""

    def test_neutral_baseline(self):
        score = _compute_sentiment(0.0, 0, 1.0)
        assert score == 50.0

    def test_positive_fii_net_increases_sentiment(self):
        score = _compute_sentiment(2000.0, 0, 1.0)
        assert score > 50.0

    def test_negative_fii_net_decreases_sentiment(self):
        score = _compute_sentiment(-2000.0, 0, 1.0)
        assert score < 50.0

    def test_high_pcr_bearish(self):
        score = _compute_sentiment(0.0, 0, 1.5)
        assert score < 50.0

    def test_low_pcr_bullish(self):
        score = _compute_sentiment(0.0, 0, 0.5)
        assert score > 50.0

    def test_clamped_to_0_100(self):
        very_negative = _compute_sentiment(-50000.0, -500000, 2.0)
        assert very_negative >= 0.0
        very_positive = _compute_sentiment(50000.0, 500000, 0.3)
        assert very_positive <= 100.0


# ---------------------------------------------------------------------------
# F&O CSV parsing
# ---------------------------------------------------------------------------


class TestFaoCsvParsing:
    """Verify F&O participant OI CSV parsing from fii-dii-data."""

    def test_empty_csv(self):
        assert _parse_fao_csv(None) == {}
        assert _parse_fao_csv("") == {}

    def test_valid_csv(self):
        csv_text = (
            "Client Type,Idx Fut Long,Idx Fut Short,Stk Fut Long,Stk Fut Short,"
            "Idx Call Long,Idx Call Short,Idx Put Long,Idx Put Short\n"
            "FII/FPI,100000,120000,80000,75000,90000,110000,95000,85000\n"
            "DII,60000,55000,45000,50000,30000,35000,40000,38000\n"
        )
        result = _parse_fao_csv(csv_text)
        assert "FII" in result
        assert "DII" in result
        assert result["FII"]["idx_fut_long"] == 100000
        assert result["FII"]["idx_fut_short"] == 120000
        assert result["DII"]["stk_fut_long"] == 45000

    def test_ignores_non_fii_dii_rows(self):
        csv_text = (
            "Client Type,Col1,Col2,Col3,Col4,Col5,Col6,Col7,Col8\n"
            "PRO,10,20,30,40,50,60,70,80\n"
            "FII/FPI,100,200,300,400,500,600,700,800\n"
        )
        result = _parse_fao_csv(csv_text)
        assert "FII" in result
        assert "PRO" not in result


# ---------------------------------------------------------------------------
# Transform data
# ---------------------------------------------------------------------------


class TestTransformData:
    """Verify the NSE data transformation pipeline."""

    def test_empty_cash_returns_none(self):
        assert _transform_data([], None) is None

    def test_basic_cash_data(self):
        cash = [
            {"category": "FII/FPI", "buyValue": 12000, "sellValue": 13000, "netValue": -1000, "date": "01-Apr-2026"},
            {"category": "DII", "buyValue": 11000, "sellValue": 10000, "netValue": 1000, "date": "01-Apr-2026"},
        ]
        snap = _transform_data(cash, None)
        assert snap is not None
        assert snap.trade_date == "01-Apr-2026"
        assert snap.fii_net == -1000.0
        assert snap.dii_net == 1000.0

    def test_with_fao_csv(self):
        cash = [
            {"category": "FII/FPI", "buyValue": 12000, "sellValue": 13000, "netValue": -1000, "date": "01-Apr-2026"},
        ]
        fao = (
            "Client Type,Col1,Col2,Col3,Col4,Col5,Col6,Col7,Col8\n"
            "FII/FPI,100000,120000,80000,75000,90000,110000,95000,85000\n"
        )
        snap = _transform_data(cash, fao)
        assert snap is not None
        assert snap.fii_idx_fut_long == 100000
        assert snap.fii_idx_fut_net == -20000
        assert snap.pcr == round(85000 / 110000, 2)


# ---------------------------------------------------------------------------
# DuckDB tracker
# ---------------------------------------------------------------------------


class TestFiiDiiTracker:
    """Test the DuckDB-backed FII/DII tracker."""

    def test_store_and_retrieve(self):
        tracker = FiiDiiTracker(db_path=":memory:")
        snap = FiiDiiSnapshot(
            trade_date="01-Apr-2026",
            fii_net=-500.0,
            dii_net=300.0,
            sentiment_score=45.0,
        )
        tracker.store_snapshot(snap)
        retrieved = tracker.get_data_for_date("01-Apr-2026")
        assert retrieved is not None
        assert retrieved.fii_net == -500.0
        assert retrieved.dii_net == 300.0
        tracker.close()

    def test_upsert_replaces(self):
        tracker = FiiDiiTracker(db_path=":memory:")
        snap1 = FiiDiiSnapshot(trade_date="01-Apr-2026", fii_net=-100.0)
        snap2 = FiiDiiSnapshot(trade_date="01-Apr-2026", fii_net=-200.0)
        tracker.store_snapshot(snap1)
        tracker.store_snapshot(snap2)
        retrieved = tracker.get_data_for_date("01-Apr-2026")
        assert retrieved is not None
        assert retrieved.fii_net == -200.0
        tracker.close()

    def test_get_trend(self):
        tracker = FiiDiiTracker(db_path=":memory:")
        for i in range(5):
            snap = FiiDiiSnapshot(
                trade_date=f"0{i+1}-Apr-2026",
                fii_net=float((i + 1) * 100),
                dii_net=float((i + 1) * -50),
                sentiment_score=50.0 + i,
            )
            tracker.store_snapshot(snap)

        trend = tracker.get_trend(days=3)
        assert trend.days == 3
        assert len(trend.snapshots) == 3
        tracker.close()

    def test_get_latest_cached_empty(self):
        tracker = FiiDiiTracker(db_path=":memory:")
        assert tracker.get_latest_cached() is None
        tracker.close()

    def test_get_latest_cached_returns_most_recent(self):
        tracker = FiiDiiTracker(db_path=":memory:")
        tracker.store_snapshot(FiiDiiSnapshot(trade_date="01-Apr-2026", fii_net=100.0))
        tracker.store_snapshot(FiiDiiSnapshot(trade_date="02-Apr-2026", fii_net=200.0))
        latest = tracker.get_latest_cached()
        assert latest is not None
        assert latest.trade_date == "02-Apr-2026"
        tracker.close()

    def test_nonexistent_date_returns_none(self):
        tracker = FiiDiiTracker(db_path=":memory:")
        assert tracker.get_data_for_date("99-Dec-9999") is None
        tracker.close()


# ---------------------------------------------------------------------------
# Sample data generators
# ---------------------------------------------------------------------------


class TestSampleData:
    """Verify sample data generators produce valid output."""

    def test_make_sample_fii_dii(self):
        snap = make_sample_fii_dii()
        assert snap.trade_date != ""
        assert snap.fii_buy > 0
        assert snap.dii_buy > 0
        assert 0 <= snap.sentiment_score <= 100

    def test_make_sample_trend(self):
        trend = make_sample_trend(days=5)
        assert trend.days == 5
        assert len(trend.snapshots) == 5
        for snap in trend.snapshots:
            assert snap.trade_date != ""

    def test_make_sample_trend_single_day(self):
        trend = make_sample_trend(days=1)
        assert trend.days == 1


# ---------------------------------------------------------------------------
# DP1 — FII long/short ratio surface
# ---------------------------------------------------------------------------


class TestFiiLongShort:
    """Verify the FII long/short ratio derivation (pure computation)."""

    def test_computes_four_segments(self):
        ratio = compute_fii_long_short(make_sample_fii_dii())
        assert isinstance(ratio, FiiLongShortRatio)
        keys = [s.segment for s in ratio.segments]
        assert keys == ["index_futures", "stock_futures", "index_calls", "index_puts"]

    def test_ratio_and_pct_match_sample_index_futures(self):
        # Sample: fii_idx_fut_long=125000, short=140000.
        ratio = compute_fii_long_short(make_sample_fii_dii())
        idx_fut = next(s for s in ratio.segments if s.segment == "index_futures")
        assert idx_fut.long == 125000
        assert idx_fut.short == 140000
        assert idx_fut.net == -15000
        assert idx_fut.ls_ratio == round(125000 / 140000, 4)
        assert idx_fut.long_pct == round(125000 / 265000 * 100.0, 2)

    def test_futures_bias_aggregates_index_and_stock(self):
        # long = 125000+80000 = 205000; short = 140000+75000 = 215000.
        ratio = compute_fii_long_short(make_sample_fii_dii())
        assert ratio.futures_long == 205000
        assert ratio.futures_short == 215000
        assert ratio.futures_bias == round(205000 / 420000 * 100.0, 2)

    def test_zero_denominator_is_neutral_not_error(self):
        ratio = compute_fii_long_short(FiiDiiSnapshot(trade_date="01-Jan-2026"))
        assert ratio.futures_bias == 50.0
        assert ratio.bias_label == "Neutral"
        for seg in ratio.segments:
            assert seg.ls_ratio == 0.0
            assert seg.long_pct == 50.0

    def test_bias_label_buckets(self):
        assert _bias_label(70.0) == "Strongly Long"
        assert _bias_label(60.0) == "Long"
        assert _bias_label(50.0) == "Neutral"
        assert _bias_label(40.0) == "Short"
        assert _bias_label(30.0) == "Strongly Short"

    def test_to_dict_is_json_serialisable(self):
        import json

        payload = compute_fii_long_short(make_sample_fii_dii()).to_dict()
        assert json.loads(json.dumps(payload))["segments"][0]["segment"] == "index_futures"


# ---------------------------------------------------------------------------
# Workspace resolution + one-shot legacy copy
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWorkspaceResolution:
    """``fii_dii.duckdb`` resolves under ``workspace_dir()/data``.

    This was the one genuinely unmigrated live default: the constructor built
    a hardcoded ``~/.flinttrade/data`` path, so every upgraded macOS/Windows
    install silently started from an empty flow cache. Mirrors the sibling
    migration in ``flinttrade_historical.expiry_tracker``.
    """

    @staticmethod
    def _default_workspace(monkeypatch, tmp_path: Path) -> Path:
        """Make ``workspace_dir()`` resolve to a tmp dir with no env override.

        Args:
            monkeypatch: Pytest monkeypatch fixture.
            tmp_path: Per-test temporary directory.

        Returns:
            The directory ``workspace_dir()`` will now return.
        """
        import flinttrade_core.workspace as ws

        monkeypatch.delenv("FLINTTRADE_WORKSPACE_DIR", raising=False)
        monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
        workspace = tmp_path / "workspace"
        monkeypatch.setattr(ws, "_default_home", lambda: workspace)
        return workspace

    @staticmethod
    def _point_legacy_at(monkeypatch, legacy: Path) -> None:
        """Redirect the legacy probe so it can never reach the real home dir."""
        monkeypatch.setattr(fii_dii, "_legacy_db_path", lambda: legacy)

    def test_fresh_install_resolves_under_workspace(self, monkeypatch, tmp_path):
        """No legacy cache: the path is the workspace one and nothing is copied."""
        workspace = self._default_workspace(monkeypatch, tmp_path)
        legacy = tmp_path / "legacy" / ".flinttrade" / "data" / "fii_dii.duckdb"
        self._point_legacy_at(monkeypatch, legacy)

        resolved = fii_dii._default_db_path()

        assert resolved == workspace / "data" / "fii_dii.duckdb"
        assert not resolved.exists()

    def test_legacy_only_is_copied_with_sidecar_and_retained(self, monkeypatch, tmp_path):
        """Legacy cache present: it and its ``.wal`` sidecar travel across."""
        workspace = self._default_workspace(monkeypatch, tmp_path)
        legacy = tmp_path / "legacy" / ".flinttrade" / "data" / "fii_dii.duckdb"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"legacy-flows")
        legacy.with_name("fii_dii.duckdb.wal").write_bytes(b"legacy-wal")
        self._point_legacy_at(monkeypatch, legacy)

        resolved = fii_dii._default_db_path()

        assert resolved == workspace / "data" / "fii_dii.duckdb"
        assert resolved.read_bytes() == b"legacy-flows"
        assert (workspace / "data" / "fii_dii.duckdb.wal").read_bytes() == b"legacy-wal"
        # Copy, not move — the legacy family stays behind as a backup.
        assert legacy.exists()

    def test_existing_workspace_cache_is_never_clobbered(self, monkeypatch, tmp_path):
        """Both present: the workspace cache wins and is left byte-identical."""
        workspace = self._default_workspace(monkeypatch, tmp_path)
        legacy = tmp_path / "legacy" / ".flinttrade" / "data" / "fii_dii.duckdb"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"legacy-flows")
        self._point_legacy_at(monkeypatch, legacy)
        (workspace / "data").mkdir(parents=True)
        (workspace / "data" / "fii_dii.duckdb").write_bytes(b"already-here")

        resolved = fii_dii._default_db_path()

        assert resolved.read_bytes() == b"already-here"
        assert legacy.exists()

    def test_environment_override_keeps_the_probe_inert(self, monkeypatch, tmp_path):
        """``FLINTTRADE_WORKSPACE_DIR`` set: no copy, and the path follows the override."""
        override = tmp_path / "override"
        monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(override))
        legacy = tmp_path / "legacy" / ".flinttrade" / "data" / "fii_dii.duckdb"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"legacy-flows")
        self._point_legacy_at(monkeypatch, legacy)

        resolved = fii_dii._default_db_path()

        assert resolved == override.resolve() / "data" / "fii_dii.duckdb"
        assert not resolved.exists()

    def test_no_argument_constructor_uses_the_workspace_path(self, monkeypatch, tmp_path):
        """``FiiDiiTracker()`` resolves at call time, not at import time."""
        workspace = self._default_workspace(monkeypatch, tmp_path)
        legacy = tmp_path / "legacy" / ".flinttrade" / "data" / "fii_dii.duckdb"
        self._point_legacy_at(monkeypatch, legacy)

        tracker = FiiDiiTracker()
        try:
            assert tracker._db_path == str(workspace / "data" / "fii_dii.duckdb")
        finally:
            tracker.close()

    def test_explicit_db_path_skips_the_probe(self, monkeypatch, tmp_path):
        """An explicit ``db_path`` is used verbatim and never migrates."""
        self._default_workspace(monkeypatch, tmp_path)
        legacy = tmp_path / "legacy" / ".flinttrade" / "data" / "fii_dii.duckdb"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"legacy-flows")
        self._point_legacy_at(monkeypatch, legacy)

        tracker = FiiDiiTracker(db_path=":memory:")
        try:
            assert tracker._db_path == ":memory:"
        finally:
            tracker.close()
