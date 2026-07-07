"""Tests for the local data-store routes (bars query/summary, bhavcopy download).

Offline: in-memory DataPipeline; bhavcopy savers are injected fakes.
"""

from __future__ import annotations

from datetime import date

import pytest
from flask import Flask

import flinttrade_historical.local_data_routes as mod
from flinttrade_historical.bhavcopy import (
    MAX_RANGE_DAYS,
    BhavcopyDownloader,
)
from flinttrade_historical.pipeline import DataPipeline


@pytest.fixture()
def pipeline():
    p = DataPipeline(":memory:")
    p.initialise()
    p.store_bars(
        "ohlcv_1d",
        "RELIANCE",
        "NSE",
        [
            {"timestamp": "2026-07-01 00:00:00", "open": 100, "high": 105, "low": 99, "close": 104, "volume": 1000},
            {"timestamp": "2026-07-02 00:00:00", "open": 104, "high": 108, "low": 103, "close": 107, "volume": 1200},
            {"timestamp": "2026-07-03 00:00:00", "open": 107, "high": 109, "low": 105, "close": 106, "volume": 900},
        ],
    )
    return p


@pytest.fixture()
def app(pipeline, tmp_path):
    flask_app = Flask("test_local_data")
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.local_data_bp)
    mod.init_local_data_routes(pipeline=pipeline, bhavcopy_dir=tmp_path / "bhavcopy")
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


class TestBarsQuery:
    def test_returns_stored_bars(self, client):
        resp = client.get("/v1/historify/bars?symbol=RELIANCE&exchange=NSE&interval=1d")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["count"] == 3
        assert data["bars"][0]["close"] == 104.0
        assert isinstance(data["bars"][0]["timestamp"], str)

    def test_date_window(self, client):
        resp = client.get(
            "/v1/historify/bars?symbol=RELIANCE&exchange=NSE&interval=1d&start=2026-07-02&end=2026-07-02"
        )
        data = resp.get_json()["data"]
        assert data["count"] == 1
        assert data["bars"][0]["close"] == 107.0

    def test_limit_keeps_most_recent(self, client):
        resp = client.get("/v1/historify/bars?symbol=RELIANCE&exchange=NSE&interval=1d&limit=1")
        data = resp.get_json()["data"]
        assert data["count"] == 1
        assert data["truncated"] is True
        assert data["bars"][0]["close"] == 106.0  # most recent bar survives

    def test_400_on_missing_or_bad_params(self, client):
        assert client.get("/v1/historify/bars?symbol=RELIANCE").status_code == 400
        assert client.get("/v1/historify/bars?symbol=X&exchange=NSE&interval=bogus").status_code == 400


class TestSummary:
    def test_summary_counts(self, client):
        resp = client.get("/v1/historify/bars/summary")
        assert resp.status_code == 200
        tables = resp.get_json()["data"]["tables"]
        assert tables["ohlcv_1d"]["rows"] == 3
        assert tables["ohlcv_1d"]["symbols"] == 1
        assert tables["ohlcv_1m"]["rows"] == 0


class TestBhavcopyDownloader:
    def test_downloads_weekdays_only_and_skips_existing(self, tmp_path):
        calls: list[tuple[str, str]] = []

        def make_saver(segment: str):
            def _saver(d: date, dest: str) -> str:
                calls.append((segment, d.isoformat()))
                out = tmp_path / "bc" / segment / f"cm{d.strftime('%d%b%Y').upper()}bhav.csv"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text("header\n")
                return str(out)
            return _saver

        dl = BhavcopyDownloader(tmp_path / "bc", savers={"equity": make_saver("equity")})
        # 2026-07-03 Fri .. 2026-07-06 Mon → Fri + Mon only (weekend skipped).
        result = dl.download_range(date(2026, 7, 3), date(2026, 7, 6), ["equity"])
        assert result.saved_count == 2
        assert [d.trade_date for d in result.days] == ["2026-07-03", "2026-07-06"]

        # Second run: both files exist → skipped, no new saver calls.
        calls.clear()
        result2 = dl.download_range(date(2026, 7, 3), date(2026, 7, 6), ["equity"])
        assert result2.saved_count == 0
        assert calls == []
        assert all("equity" in d.skipped for d in result2.days)

    def test_per_day_errors_do_not_abort(self, tmp_path):
        def failing_saver(d: date, dest: str) -> str:
            raise RuntimeError("NSE archive missing (holiday)")

        dl = BhavcopyDownloader(tmp_path / "bc2", savers={"fo": failing_saver})
        result = dl.download_range(date(2026, 7, 6), date(2026, 7, 7), ["fo"])
        assert result.saved_count == 0
        assert result.error_count == 2
        assert "holiday" in result.days[0].errors["fo"]

    def test_range_guardrails(self, tmp_path):
        dl = BhavcopyDownloader(tmp_path / "bc3", savers={})
        with pytest.raises(ValueError):
            dl.download_range(date(2026, 7, 6), date(2026, 7, 5))
        with pytest.raises(ValueError):
            dl.download_range(date(2026, 1, 1), date(2026, 3, 1))  # > MAX_RANGE_DAYS
        assert MAX_RANGE_DAYS == 31


class TestBhavcopyRoute:
    def test_400_on_bad_dates_or_segments(self, client):
        assert client.post("/v1/historify/bhavcopy/download", json={"start": "x", "end": "y"}).status_code == 400
        assert client.post(
            "/v1/historify/bhavcopy/download",
            json={"start": "2026-07-06", "end": "2026-07-06", "segments": ["bogus"]},
        ).status_code == 400

    def test_400_on_oversized_range(self, client):
        resp = client.post(
            "/v1/historify/bhavcopy/download",
            json={"start": "2026-01-01", "end": "2026-03-01"},
        )
        assert resp.status_code == 400
        # Generic message — exception text is logged, never reflected (CodeQL
        # stack-trace-exposure class).
        assert "capped at 31 days" in resp.get_json()["message"]

    def test_download_with_injected_saver(self, client, monkeypatch, tmp_path):
        # Patch the jugaad saver resolution so the route runs offline.
        def fake_savers():
            def _save(d: date, dest: str) -> str:
                out = tmp_path / f"cm{d.strftime('%d%b%Y').upper()}bhav.csv"
                out.write_text("header\n")
                return str(out)
            return {"equity": _save, "fo": _save, "index": _save, "full": _save}

        monkeypatch.setattr("flinttrade_historical.bhavcopy._default_savers", fake_savers)

        resp = client.post(
            "/v1/historify/bhavcopy/download",
            json={"start": "2026-07-06", "end": "2026-07-06", "segments": ["equity"]},
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["saved_count"] == 1
        assert data["days"][0]["saved"] == ["equity"]
