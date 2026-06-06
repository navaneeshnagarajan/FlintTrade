"""Tests for the per-strategy backtest-results store."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from flinttrade_backtest.result_store import BacktestResultStore

pytestmark = pytest.mark.unit

_CLOCK = lambda: datetime(2026, 6, 6, 2, 0, tzinfo=timezone.utc)  # noqa: E731


def test_save_then_latest_round_trips(tmp_path):
    store = BacktestResultStore(tmp_path, clock=_CLOCK)
    store.save("ema_crossover", {"sharpe_ratio": 1.4, "max_drawdown": -0.1})
    assert store.latest("ema_crossover") == {"sharpe_ratio": 1.4, "max_drawdown": -0.1}


def test_latest_is_none_for_unknown_strategy(tmp_path):
    store = BacktestResultStore(tmp_path)
    assert store.latest("never_run") is None


def test_save_overwrites_with_the_latest_run(tmp_path):
    store = BacktestResultStore(tmp_path, clock=_CLOCK)
    store.save("rsi_mr", {"sharpe_ratio": 0.5})
    store.save("rsi_mr", {"sharpe_ratio": 1.9})
    assert store.latest("rsi_mr") == {"sharpe_ratio": 1.9}


def test_names_lists_stored_strategies_exactly(tmp_path):
    store = BacktestResultStore(tmp_path, clock=_CLOCK)
    # A name with characters that get sanitised in the filename must still come
    # back verbatim from names()/latest().
    store.save("EMA Cross / 5m", {"sharpe_ratio": 1.0})
    store.save("rsi_mr", {"sharpe_ratio": 1.2})
    assert store.names() == ["EMA Cross / 5m", "rsi_mr"]
    assert store.latest("EMA Cross / 5m") == {"sharpe_ratio": 1.0}


def test_record_carries_context_and_timestamp(tmp_path):
    store = BacktestResultStore(tmp_path, clock=_CLOCK)
    store.save("ema", {"sharpe_ratio": 1.1}, context={"symbol": "NIFTY", "interval": "5m"})
    rec = store.record("ema")
    assert rec is not None
    assert rec["context"] == {"symbol": "NIFTY", "interval": "5m"}
    assert rec["timestamp"] == "2026-06-06T02:00:00+00:00"


def test_blank_strategy_name_is_ignored(tmp_path):
    store = BacktestResultStore(tmp_path)
    assert store.save("   ", {"sharpe_ratio": 1.0}) == ""
    assert store.names() == []


def test_names_is_empty_when_dir_absent(tmp_path):
    store = BacktestResultStore(tmp_path / "does-not-exist")
    assert store.names() == []
    assert store.latest("anything") is None
