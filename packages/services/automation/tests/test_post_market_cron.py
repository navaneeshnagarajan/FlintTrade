"""Tests for the post_market_analysis cron slot wiring.

The DEFAULT_JOBS["post_market_analysis"] slot existed with no matching
handler in register_builtin_jobs — these tests pin the wired behaviour:
lazy trade-store resolution, holiday gating, honest log-and-skip when a
dependency is missing, Telegram summary, and DuckDB report persistence.
"""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import MagicMock

import pytest

from flinttrade_automation.cron_manager import (
    DEFAULT_JOBS,
    CronManager,
    make_post_market_analysis_job,
)

pytestmark = pytest.mark.unit


def _no_holiday(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the handler's market-holiday gate open (weekend-proof tests)."""
    monkeypatch.setattr(
        "flinttrade_automation.cron_manager._is_market_holiday",
        lambda holidays=None: False,
    )


def _fake_storage(rows: list[dict[str, Any]]) -> MagicMock:
    storage = MagicMock()
    storage.get_trades_by_date = MagicMock(return_value=rows)
    return storage


_SAMPLE_ROWS: list[dict[str, Any]] = [
    {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 10,
        "entry_price": 2900.0,
        "exit_price": 2950.0,
        "pnl": 500.0,
        "strategy": "momentum",
        "fees": 20.0,
    },
    {
        "symbol": "TCS",
        "exchange": "NSE",
        "action": "SELL",
        "quantity": 5,
        "entry_price": 4100.0,
        "exit_price": 4120.0,
        "pnl": -100.0,
        "strategy": "meanrev",
        "fees": 10.0,
    },
]


class TestRegistration:
    def test_registered_by_register_builtin_jobs(self) -> None:
        """The slot always registers — the handler resolves the store lazily."""
        cron = CronManager()
        cron.register_builtin_jobs()
        assert "post_market_analysis" in cron._jobs  # noqa: SLF001
        assert cron._jobs["post_market_analysis"].handler is not None  # noqa: SLF001

    def test_scheduled_at_1545_ist(self) -> None:
        args = DEFAULT_JOBS["post_market_analysis"]["trigger_args"]
        assert args["hour"] == 15
        assert args["minute"] == 45
        assert args["timezone"] == "Asia/Kolkata"

    def test_store_wired_after_registration_is_picked_up(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fire-time resolution: a late-wired trade store is still used."""
        _no_holiday(monkeypatch)
        cron = CronManager()
        cron.register_builtin_jobs()
        storage = _fake_storage([])
        cron.trade_storage = storage
        cron.trade_storage_lock = threading.Lock()
        cron.run_now("post_market_analysis")
        storage.get_trades_by_date.assert_called_once()

    def test_run_without_store_is_a_safe_skip(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No trade store configured — the job logs-and-skips, never raises."""
        _no_holiday(monkeypatch)
        cron = CronManager()
        cron.register_builtin_jobs()
        cron.run_now("post_market_analysis")
        job = cron._jobs["post_market_analysis"]  # noqa: SLF001
        assert job.last_success is True
        assert job.error_count == 0


class TestHandler:
    def test_holiday_skips_without_touching_storage(self) -> None:
        from datetime import datetime

        from flinttrade_automation.cron_manager import IST

        storage = _fake_storage(_SAMPLE_ROWS)
        today = datetime.now(IST).date().isoformat()
        job = make_post_market_analysis_job(
            lambda: (storage, None, None),
            holidays={today},
        )
        job()
        storage.get_trades_by_date.assert_not_called()

    def test_reads_trades_under_lock_and_sends_telegram(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _no_holiday(monkeypatch)
        storage = _fake_storage(_SAMPLE_ROWS)
        lock = threading.Lock()
        bot = MagicMock()
        job = make_post_market_analysis_job(
            lambda: (storage, lock, None),
            telegram_bot=bot,
        )
        job()
        storage.get_trades_by_date.assert_called_once()
        bot.send_message.assert_called_once()
        message = bot.send_message.call_args[0][0]
        assert "Daily Report" in message
        assert "momentum" in message

    def test_no_trades_builds_empty_report_without_telegram(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _no_holiday(monkeypatch)
        storage = _fake_storage([])
        bot = MagicMock()
        job = make_post_market_analysis_job(
            lambda: (storage, None, None),
            telegram_bot=bot,
        )
        job()
        bot.send_message.assert_not_called()

    def test_storage_read_failure_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _no_holiday(monkeypatch)
        storage = MagicMock()
        storage.get_trades_by_date = MagicMock(side_effect=RuntimeError("db locked"))
        job = make_post_market_analysis_job(lambda: (storage, None, None))
        job()  # must not raise

    def test_provider_failure_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _no_holiday(monkeypatch)

        def boom() -> tuple[Any, Any, str | None]:
            raise RuntimeError("provider blew up")

        job = make_post_market_analysis_job(boom)
        job()  # must not raise

    def test_report_persisted_to_separate_duckdb(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        duckdb = pytest.importorskip("duckdb")
        _no_holiday(monkeypatch)
        report_db = str(tmp_path / "post_market_reports.duckdb")
        storage = _fake_storage(_SAMPLE_ROWS)
        job = make_post_market_analysis_job(lambda: (storage, None, report_db))
        job()
        conn = duckdb.connect(report_db)
        try:
            rows = conn.execute(
                "SELECT total_trades, net_pnl FROM daily_reports"
            ).fetchall()
        finally:
            conn.close()
        assert rows == [(2, 400.0)]

    def test_malformed_rows_do_not_crash_the_scheduler(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _no_holiday(monkeypatch)
        storage = _fake_storage([{"symbol": "X", "quantity": "not-a-number"}])
        job = make_post_market_analysis_job(lambda: (storage, None, None))
        job()  # mapping failure is logged, never raised
