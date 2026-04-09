"""Tests for PositionTracker.

All tests run with an in-memory DuckDB instance so no filesystem state is
created or leaked between test runs.

Coverage:
- Open / close single position
- Duplicate position guard
- Max-position limit guard
- update_price + MTM P&L correctness (long and short)
- bulk price update
- close_all
- MTM loss limit trigger
- Portfolio aggregates (realised, unrealised, cumulative R)
- DuckDB recovery after restart
- Daily reset
- Thread-safety (concurrent opens)
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest

from packages.engine.src.position_tracker import (
    PositionAlreadyExistsError,
    PositionLimitExceededError,
    PositionNotFoundError,
    PositionRecord,
    PositionTracker,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STRATEGY_A = "strategy-aaa-111"
STRATEGY_B = "strategy-bbb-222"


def _tracker(**kwargs) -> PositionTracker:
    """Return a fresh in-memory PositionTracker."""
    return PositionTracker(db_path=":memory:", **kwargs)


def _open_short(
    tracker: PositionTracker,
    symbol: str = "NIFTY30DEC2523500CE",
    strategy_id: str = STRATEGY_A,
    entry: float = 250.0,
    sl: float = 260.0,
    qty: int = 50,
) -> None:
    tracker.open(
        strategy_id=strategy_id,
        symbol=symbol,
        exchange="NFO",
        direction="SELL",
        entry_price=entry,
        sl_price=sl,
        quantity=qty,
    )


def _open_long(
    tracker: PositionTracker,
    symbol: str = "RELIANCE",
    strategy_id: str = STRATEGY_A,
    entry: float = 2500.0,
    sl: float = 2450.0,
    qty: int = 10,
) -> None:
    tracker.open(
        strategy_id=strategy_id,
        symbol=symbol,
        exchange="NSE",
        direction="BUY",
        entry_price=entry,
        sl_price=sl,
        quantity=qty,
    )


# ---------------------------------------------------------------------------
# PositionRecord model
# ---------------------------------------------------------------------------


def test_position_record_fields_are_set() -> None:
    rec = PositionRecord(
        strategy_id=STRATEGY_A,
        symbol="NIFTY30DEC2523500CE",
        exchange="NFO",
        direction="SELL",
        entry_price=250.0,
        sl_price=260.0,
        quantity=50,
    )
    assert rec.strategy_id == STRATEGY_A
    assert rec.symbol == "NIFTY30DEC2523500CE"
    assert rec.direction == "SELL"
    assert not rec.is_closed


def test_risk_per_unit_long() -> None:
    rec = PositionRecord(
        strategy_id=STRATEGY_A,
        symbol="X",
        entry_price=100.0,
        sl_price=90.0,
        quantity=10,
    )
    assert rec.risk_per_unit == pytest.approx(10.0)
    assert rec.actual_r == pytest.approx(100.0)


def test_risk_per_unit_short() -> None:
    rec = PositionRecord(
        strategy_id=STRATEGY_A,
        symbol="X",
        direction="SELL",
        entry_price=250.0,
        sl_price=260.0,
        quantity=50,
    )
    assert rec.risk_per_unit == pytest.approx(10.0)
    assert rec.actual_r == pytest.approx(500.0)


def test_unrealised_r_zero_when_at_entry() -> None:
    rec = PositionRecord(
        strategy_id=STRATEGY_A,
        symbol="X",
        direction="SELL",
        entry_price=250.0,
        sl_price=260.0,
        quantity=50,
        current_price=250.0,
        unrealised_pnl=0.0,
    )
    assert rec.unrealised_r == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Open / close
# ---------------------------------------------------------------------------


def test_open_creates_position() -> None:
    t = _tracker()
    _open_short(t)
    assert t.open_count() == 1
    positions = t.get_open_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "NIFTY30DEC2523500CE"
    assert positions[0].direction == "SELL"


def test_open_duplicate_raises() -> None:
    t = _tracker()
    _open_short(t)
    with pytest.raises(PositionAlreadyExistsError):
        _open_short(t)


def test_open_two_strategies_same_symbol_allowed() -> None:
    t = _tracker()
    _open_short(t, strategy_id=STRATEGY_A)
    _open_short(t, strategy_id=STRATEGY_B)  # Different strategy — should succeed
    assert t.open_count() == 2


def test_close_position_moves_to_closed() -> None:
    t = _tracker()
    _open_short(t)
    closed = t.close("NIFTY30DEC2523500CE", STRATEGY_A, 240.0, "SL_HIT")
    assert closed.is_closed
    assert closed.exit_price == pytest.approx(240.0)
    assert closed.exit_reason == "SL_HIT"
    # Realised P&L: (entry - exit) * qty for short = (250 - 240) * 50 = 500
    assert closed.realised_pnl == pytest.approx(500.0)
    assert t.open_count() == 0
    assert len(t.get_closed_positions()) == 1


def test_close_nonexistent_raises() -> None:
    t = _tracker()
    with pytest.raises(PositionNotFoundError):
        t.close("UNKNOWN", STRATEGY_A, 100.0, "TEST")


def test_close_long_pnl() -> None:
    t = _tracker()
    _open_long(t)
    closed = t.close("RELIANCE", STRATEGY_A, 2600.0, "TARGET_HIT")
    # Long: (exit - entry) * qty = (2600 - 2500) * 10 = 1000
    assert closed.realised_pnl == pytest.approx(1000.0)


def test_close_short_loss() -> None:
    t = _tracker()
    _open_short(t)
    closed = t.close("NIFTY30DEC2523500CE", STRATEGY_A, 265.0, "SL_HIT")
    # Short loss: (250 - 265) * 50 = -750
    assert closed.realised_pnl == pytest.approx(-750.0)


# ---------------------------------------------------------------------------
# Price updates
# ---------------------------------------------------------------------------


def test_update_price_short_profit() -> None:
    t = _tracker()
    _open_short(t, entry=250.0)
    t.update_price("NIFTY30DEC2523500CE", STRATEGY_A, 240.0)
    positions = t.get_open_positions()
    pos = positions[0]
    # Short profit: (250 - 240) * 50 = 500
    assert pos.unrealised_pnl == pytest.approx(500.0)


def test_update_price_short_loss() -> None:
    t = _tracker()
    _open_short(t, entry=250.0)
    t.update_price("NIFTY30DEC2523500CE", STRATEGY_A, 260.0)
    pos = t.get_open_positions()[0]
    # Short loss: (250 - 260) * 50 = -500
    assert pos.unrealised_pnl == pytest.approx(-500.0)


def test_update_price_long_profit() -> None:
    t = _tracker()
    _open_long(t, entry=2500.0)
    t.update_price("RELIANCE", STRATEGY_A, 2600.0)
    pos = t.get_open_positions()[0]
    assert pos.unrealised_pnl == pytest.approx(1000.0)


def test_update_price_unknown_symbol_is_noop() -> None:
    t = _tracker()
    _open_short(t)
    # Should not raise; unknown symbols are silently skipped
    t.update_price("UNKNOWN", STRATEGY_A, 999.0)
    assert t.open_count() == 1


def test_update_prices_bulk() -> None:
    t = _tracker()
    _open_short(t, symbol="SYM_A", entry=100.0)
    _open_short(t, symbol="SYM_B", entry=200.0)
    t.update_prices_bulk({"SYM_A": 90.0, "SYM_B": 190.0}, strategy_id=STRATEGY_A)
    positions = {p.symbol: p for p in t.get_open_positions()}
    assert positions["SYM_A"].unrealised_pnl == pytest.approx((100 - 90) * 50)
    assert positions["SYM_B"].unrealised_pnl == pytest.approx((200 - 190) * 50)


def test_update_prices_bulk_all_strategies() -> None:
    t = _tracker()
    _open_short(t, symbol="SYM_A", strategy_id=STRATEGY_A)
    _open_short(t, symbol="SYM_A", strategy_id=STRATEGY_B)
    t.update_prices_bulk({"SYM_A": 240.0})  # No strategy_id = update all
    for pos in t.get_open_positions():
        assert pos.current_price == pytest.approx(240.0)


# ---------------------------------------------------------------------------
# Max-position limit
# ---------------------------------------------------------------------------


def test_max_positions_limit_enforced() -> None:
    t = _tracker(max_positions=2)
    _open_short(t, symbol="A")
    _open_short(t, symbol="B")
    with pytest.raises(PositionLimitExceededError):
        _open_short(t, symbol="C")


def test_max_positions_respected_after_close() -> None:
    t = _tracker(max_positions=2)
    _open_short(t, symbol="A")
    _open_short(t, symbol="B")
    t.close("A", STRATEGY_A, 240.0, "TEST")
    # Now we have 1 open — should be allowed to open another
    _open_short(t, symbol="C")
    assert t.open_count() == 2


# ---------------------------------------------------------------------------
# MTM loss limit
# ---------------------------------------------------------------------------


def test_mtm_limit_not_breached() -> None:
    t = _tracker(mtm_loss_limit=-1000.0)
    _open_short(t, entry=250.0, qty=50)
    t.update_price("NIFTY30DEC2523500CE", STRATEGY_A, 255.0)
    # Loss = (250 - 255) * 50 = -250, limit = -1000 → not breached
    assert not t.check_mtm_limit()


def test_mtm_limit_breached() -> None:
    t = _tracker(mtm_loss_limit=-500.0)
    _open_short(t, entry=250.0, qty=50)
    t.update_price("NIFTY30DEC2523500CE", STRATEGY_A, 260.0)
    # Loss = (250 - 260) * 50 = -500, limit = -500 → exactly at limit → breached
    assert t.check_mtm_limit()


def test_mtm_limit_none_never_triggers() -> None:
    t = _tracker(mtm_loss_limit=None)
    _open_short(t, entry=250.0, qty=50)
    t.update_price("NIFTY30DEC2523500CE", STRATEGY_A, 999.0)
    assert not t.check_mtm_limit()


# ---------------------------------------------------------------------------
# close_all
# ---------------------------------------------------------------------------


def test_close_all_closes_every_open_position() -> None:
    t = _tracker()
    _open_short(t, symbol="A", entry=100.0)
    _open_short(t, symbol="B", entry=200.0)
    prices = {"A": 90.0, "B": 190.0}
    closed = t.close_all(prices, reason="EOD_EXIT")
    assert len(closed) == 2
    assert t.open_count() == 0


def test_close_all_uses_fallback_price_for_missing_symbol() -> None:
    t = _tracker()
    _open_short(t, symbol="A", entry=100.0, qty=10)
    t.update_price("A", STRATEGY_A, 95.0)
    # No price provided for "A" — should use current_price (95.0)
    closed = t.close_all({}, reason="TEST")
    assert len(closed) == 1
    # (100 - 95) * 10 = 50
    assert closed[0].realised_pnl == pytest.approx(50.0)


def test_close_all_scoped_to_strategy() -> None:
    t = _tracker()
    _open_short(t, symbol="A", strategy_id=STRATEGY_A)
    _open_short(t, symbol="B", strategy_id=STRATEGY_B)
    t.close_all({"A": 240.0}, reason="TEST", strategy_id=STRATEGY_A)
    assert t.open_count(STRATEGY_A) == 0
    assert t.open_count(STRATEGY_B) == 1


# ---------------------------------------------------------------------------
# Portfolio aggregates
# ---------------------------------------------------------------------------


def test_portfolio_realised_pnl_sums_closed() -> None:
    t = _tracker()
    _open_short(t, symbol="A", entry=100.0, qty=10)
    _open_short(t, symbol="B", entry=200.0, qty=10)
    t.close("A", STRATEGY_A, 90.0, "TEST")   # profit 100
    t.close("B", STRATEGY_A, 205.0, "TEST")  # loss -50
    assert t.portfolio_realised_pnl() == pytest.approx(50.0)


def test_portfolio_unrealised_pnl_sums_open() -> None:
    t = _tracker()
    _open_short(t, symbol="A", entry=100.0, qty=10)
    _open_short(t, symbol="B", entry=200.0, qty=10)
    t.update_price("A", STRATEGY_A, 95.0)    # profit 50
    t.update_price("B", STRATEGY_A, 205.0)   # loss -50
    assert t.portfolio_unrealised_pnl() == pytest.approx(0.0)


def test_cumulative_r_closed_and_open() -> None:
    t = _tracker()
    # Short: entry=250, sl=260 → actual_R = 10 * 50 = 500 per position
    _open_short(t, symbol="A", entry=250.0, sl=260.0, qty=50)
    t.close("A", STRATEGY_A, 240.0, "TEST")  # profit 500 → R = 500/500 = 1.0
    _open_short(t, symbol="B", entry=250.0, sl=260.0, qty=50)
    t.update_price("B", STRATEGY_A, 245.0)   # unrealised 250 → R = 250/500 = 0.5
    r = t.cumulative_r()
    assert r == pytest.approx(1.5)


def test_summary_dict_keys() -> None:
    t = _tracker()
    s = t.summary()
    for key in ("open_count", "closed_count", "realised_pnl", "unrealised_pnl", "total_pnl", "cumulative_r", "mtm_limit_breached"):
        assert key in s


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def test_is_open_true_and_false() -> None:
    t = _tracker()
    _open_short(t)
    assert t.is_open("NIFTY30DEC2523500CE", STRATEGY_A)
    assert not t.is_open("NIFTY30DEC2523500CE", STRATEGY_B)


def test_get_open_positions_scoped_by_strategy() -> None:
    t = _tracker()
    _open_short(t, symbol="A", strategy_id=STRATEGY_A)
    _open_short(t, symbol="B", strategy_id=STRATEGY_B)
    assert len(t.get_open_positions(STRATEGY_A)) == 1
    assert len(t.get_open_positions(STRATEGY_B)) == 1
    assert len(t.get_open_positions()) == 2


def test_get_closed_positions_scoped_by_strategy() -> None:
    t = _tracker()
    _open_short(t, symbol="A", strategy_id=STRATEGY_A)
    t.close("A", STRATEGY_A, 240.0, "TEST")
    assert len(t.get_closed_positions(STRATEGY_A)) == 1
    assert len(t.get_closed_positions(STRATEGY_B)) == 0


# ---------------------------------------------------------------------------
# DuckDB recovery
# ---------------------------------------------------------------------------


def test_recovery_reloads_open_positions(tmp_path) -> None:
    db_file = str(tmp_path / "test_engine.duckdb")
    t1 = PositionTracker(db_path=db_file)
    _open_short(t1, symbol="A")
    t1.close_db()

    # Simulate restart
    t2 = PositionTracker(db_path=db_file)
    assert t2.open_count() == 1
    positions = t2.get_open_positions()
    assert positions[0].symbol == "A"
    t2.close_db()


def test_recovery_ignores_closed_positions(tmp_path) -> None:
    db_file = str(tmp_path / "test_engine2.duckdb")
    t1 = PositionTracker(db_path=db_file)
    _open_short(t1, symbol="A")
    t1.close("A", STRATEGY_A, 240.0, "TEST")
    t1.close_db()

    t2 = PositionTracker(db_path=db_file)
    assert t2.open_count() == 0
    t2.close_db()


# ---------------------------------------------------------------------------
# Daily reset
# ---------------------------------------------------------------------------


def test_daily_reset_clears_state() -> None:
    t = _tracker()
    _open_short(t, symbol="A")
    _open_short(t, symbol="B")
    t.close("A", STRATEGY_A, 240.0, "TEST")
    t.reset_daily()
    assert t.open_count() == 0
    assert len(t.get_closed_positions()) == 0


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


def test_concurrent_opens_do_not_corrupt_state() -> None:
    t = _tracker(max_positions=20)
    errors: list[Exception] = []

    def open_worker(symbol: str) -> None:
        try:
            t.open(
                strategy_id=STRATEGY_A,
                symbol=symbol,
                exchange="NSE",
                direction="BUY",
                entry_price=100.0,
                sl_price=90.0,
                quantity=1,
            )
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=open_worker, args=(f"SYM_{i}",)) for i in range(10)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    # All 10 should have opened without error
    assert not errors
    assert t.open_count() == 10


def test_concurrent_duplicate_open_raises_for_all_but_first() -> None:
    t = _tracker()
    results: list[str] = []

    def open_worker() -> None:
        try:
            t.open(
                strategy_id=STRATEGY_A,
                symbol="SHARED_SYM",
                exchange="NSE",
                direction="BUY",
                entry_price=100.0,
                sl_price=90.0,
                quantity=1,
            )
            results.append("ok")
        except PositionAlreadyExistsError:
            results.append("duplicate")

    threads = [threading.Thread(target=open_worker) for _ in range(5)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert results.count("ok") == 1
    assert results.count("duplicate") == 4
