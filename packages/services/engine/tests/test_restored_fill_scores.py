"""A restored fill does not move Laya or strategy scores."""

from __future__ import annotations

import pytest

from flinttrade_automation.post_market import TradeEntry, build_report
from flinttrade_core.restored_fills import RESTORED_FROM_BACKUP
from flinttrade_engine.laya import DecisionRecord
from flinttrade_engine.score_readers import (
    decision_model_benchmark,
    eval_export,
    gate_hit_rates,
    performance_stats,
    strategy_track_record,
    training_export,
)
from flinttrade_journal.trade_journal import TradeJournal
from flinttrade_journal.trade_logger import TradeLogger


pytestmark = pytest.mark.unit


def _journal_entry(**kwargs: object):
    from flinttrade_journal.trade_journal import JournalEntry

    defaults: dict[str, object] = {
        "symbol": "INFY",
        "exchange": "NSE",
        "side": "BUY",
        "quantity": 1,
        "entry_price": 100.0,
        "exit_price": 110.0,
        "strategy": "ORB",
    }
    defaults.update(kwargs)
    return JournalEntry(**defaults)


def test_restored_fill_leaves_scores_unchanged() -> None:
    """Gate, benchmark, track-record, performance scores, and exports stay put."""
    decision = DecisionRecord(
        proof_kind="admit",
        symbol="INFY",
        exchange="NSE",
        action="BUY",
        quantity=1,
        applied_quantity=1,
        status="ready",
        allow=True,
    )
    fills = [
        {
            "strategy": "ORB",
            "pnl": 100.0,
            "allow": True,
            "proof_kind": "admit",
            "predicted": True,
            "outcome": True,
            "split": "train",
        },
        {
            "strategy": "ORB",
            "pnl": -40.0,
            "allow": False,
            "proof_kind": "admit",
            "predicted": False,
            "outcome": False,
            "split": "eval",
        },
    ]
    rows: list[object] = [decision, *fills]
    restored = {
        "strategy": RESTORED_FROM_BACKUP,
        "pnl": 9000.0,
        "allow": True,
        "proof_kind": "admit",
        "predicted": False,
        "outcome": True,
        "split": "train",
    }
    with_restored = [*rows, restored]

    assert gate_hit_rates(rows) == gate_hit_rates(with_restored)
    assert decision_model_benchmark(rows) == decision_model_benchmark(with_restored)
    assert strategy_track_record(rows) == strategy_track_record(with_restored)
    before_perf = performance_stats(rows)
    after_perf = performance_stats(with_restored)
    assert before_perf["laya"] == after_perf["laya"]
    assert before_perf["strategy"] == after_perf["strategy"]
    assert after_perf["pnl"] == pytest.approx(before_perf["pnl"] + 9000.0)
    assert after_perf["restored"] == 1
    assert training_export(rows) == training_export(with_restored)
    assert eval_export(rows) == eval_export(with_restored)
    assert restored not in training_export(with_restored)
    assert restored not in eval_export(with_restored)

    journal = TradeJournal(":memory:")
    journal.initialise()
    journal.add_entry(_journal_entry())
    before_stats = journal.get_stats()
    journal.add_entry(_journal_entry(
        strategy=RESTORED_FROM_BACKUP,
        entry_price=100.0,
        exit_price=50.0,
        quantity=1,
    ))
    after_stats = journal.get_stats()
    assert after_stats.win_rate == before_stats.win_rate
    assert after_stats.by_strategy == before_stats.by_strategy
    assert after_stats.total_pnl == pytest.approx(before_stats.total_pnl - 50.0)

    book = [
        TradeEntry(symbol="INFY", pnl=100.0, strategy="ORB"),
        TradeEntry(symbol="INFY", pnl=-40.0, strategy="ORB"),
    ]
    before_report = build_report(book, "2026-03-16")
    after_report = build_report(
        [*book, TradeEntry(symbol="TCS", pnl=5000.0, strategy=RESTORED_FROM_BACKUP)],
        "2026-03-16",
    )
    assert after_report.win_rate == before_report.win_rate
    assert after_report.total_trades == before_report.total_trades
    assert [
        (row.strategy, row.total_trades, row.net_pnl) for row in after_report.strategy_breakdown
    ] == [
        (row.strategy, row.total_trades, row.net_pnl) for row in before_report.strategy_breakdown
    ]
    assert after_report.gross_pnl == pytest.approx(before_report.gross_pnl + 5000.0)

    summary = TradeLogger(storage=None).compute_daily_summary("2026-03-16", RESTORED_FROM_BACKUP)  # type: ignore[arg-type]
    assert summary.total_trades == 0
    assert summary.net_pnl == 0.0
