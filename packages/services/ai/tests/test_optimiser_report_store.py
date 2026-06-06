"""Tests for the overnight-optimiser report store + its end-to-end persist path."""

from __future__ import annotations

import pytest

from flinttrade_ai.optimiser_report_store import OptimiserReportStore

pytestmark = pytest.mark.unit


def _report(ts: str, optimised: int = 1) -> dict:
    return {
        "timestamp": ts,
        "strategies_seen": optimised,
        "strategies_optimised": optimised,
        "suggestions": [
            {"strategy_name": "ema", "analysis": "x", "suggested_params": {}, "reasoning": "y", "confidence": 0.5},
        ],
        "errors": [],
    }


def test_write_then_latest_roundtrips(tmp_path):
    store = OptimiserReportStore(tmp_path)
    store.write(_report("2026-06-06T02:00:00+00:00"))

    latest = store.latest()
    assert latest is not None
    assert latest["timestamp"] == "2026-06-06T02:00:00+00:00"
    assert latest["suggestions"][0]["strategy_name"] == "ema"


def test_list_reports_newest_first(tmp_path):
    store = OptimiserReportStore(tmp_path)
    store.write(_report("2026-06-04T02:00:00+00:00"))
    store.write(_report("2026-06-06T02:00:00+00:00"))
    store.write(_report("2026-06-05T02:00:00+00:00"))

    reports = store.list_reports()
    assert [r["timestamp"] for r in reports] == [
        "2026-06-06T02:00:00+00:00",
        "2026-06-05T02:00:00+00:00",
        "2026-06-04T02:00:00+00:00",
    ]
    assert store.latest()["timestamp"] == "2026-06-06T02:00:00+00:00"


def test_empty_store_returns_none_and_empty_list(tmp_path):
    store = OptimiserReportStore(tmp_path / "does-not-exist")
    assert store.latest() is None
    assert store.list_reports() == []


def test_store_is_the_optimiser_sink_end_to_end(tmp_path):
    # OvernightOptimiser.run() with the store as report_sink persists the report,
    # closing the "generate reports" loop: run -> persist -> read back.
    from flinttrade_ai.overnight_optimiser import OvernightOptimiser
    from flinttrade_ai.strategy_refiner import StrategyRefiner

    store = OptimiserReportStore(tmp_path)
    strategies = [
        {"name": "ema_cross", "params": {"fast_period": 9}, "backtest_results": {"sharpe_ratio": 0.5}},
    ]
    optimiser = OvernightOptimiser(lambda: strategies, StrategyRefiner(), report_sink=store.write)

    report = optimiser.run()

    persisted = store.latest()
    assert persisted is not None
    assert persisted["timestamp"] == report["timestamp"]
    assert persisted["strategies_optimised"] == 1
    assert persisted["suggestions"][0]["strategy_name"] == "ema_cross"
