"""Tests for FlintTrade data package.

DO NOT RUN — written for pytest. DuckDB tests use in-memory databases.
Audit logger tests use tmp_path fixture.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

IST = timezone(timedelta(hours=5, minutes=30))


# ======================================================================
# StorageManager — DuckDB table creation + queries
# ======================================================================


class TestStorageManager:
    """Test DuckDB schema creation and query helpers."""

    def _make_storage(self):
        from packages.data.src.storage import StorageManager
        # Use in-memory DuckDB for tests
        storage = StorageManager(":memory:")
        storage.initialize()
        return storage

    def test_initialize_creates_all_tables(self):
        storage = self._make_storage()
        result = storage.connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
        tables = {row[0] for row in result}
        assert "ticks" in tables
        assert "trades" in tables
        assert "audit" in tables
        assert "daily_summary" in tables
        storage.close()

    def test_initialize_idempotent(self):
        storage = self._make_storage()
        # Second call should not raise
        storage.initialize()
        storage.close()

    def test_insert_and_query_tick(self):
        storage = self._make_storage()
        ts = datetime(2026, 3, 16, 10, 0, 0)
        storage.insert_tick(
            ts=ts, symbol="RELIANCE", exchange="NSE", mode="quote",
            ltp=2500.0, volume=1000, bid=2499.0, ask=2501.0,
        )
        ticks = storage.get_ticks("RELIANCE", "NSE", "2026-03-16", "2026-03-16")
        assert len(ticks) == 1
        assert ticks[0]["symbol"] == "RELIANCE"
        assert ticks[0]["ltp"] == 2500.0
        storage.close()

    def test_insert_ticks_batch(self):
        storage = self._make_storage()
        ts = datetime(2026, 3, 16, 10, 0, 0)
        rows = [
            (ts, "RELIANCE", "NSE", "ltp", 2500.0, None, None, None, None, None, None, None, None, None, None),
            (ts, "TCS", "NSE", "ltp", 3500.0, None, None, None, None, None, None, None, None, None, None),
            (ts, "INFY", "NSE", "ltp", 1500.0, None, None, None, None, None, None, None, None, None, None),
        ]
        storage.insert_ticks_batch(rows)
        ticks = storage.get_ticks_by_date("2026-03-16")
        assert len(ticks) == 3
        storage.close()

    def test_empty_batch_does_nothing(self):
        storage = self._make_storage()
        storage.insert_ticks_batch([])  # Should not raise
        storage.close()

    def test_query_ticks_date_range_filters(self):
        storage = self._make_storage()
        storage.insert_tick(
            ts=datetime(2026, 3, 15, 10, 0, 0),
            symbol="RELIANCE", exchange="NSE", mode="ltp", ltp=2490.0,
        )
        storage.insert_tick(
            ts=datetime(2026, 3, 16, 10, 0, 0),
            symbol="RELIANCE", exchange="NSE", mode="ltp", ltp=2500.0,
        )
        ticks = storage.get_ticks("RELIANCE", "NSE", "2026-03-16", "2026-03-16")
        assert len(ticks) == 1
        assert ticks[0]["ltp"] == 2500.0
        storage.close()

    def test_insert_and_query_trade(self):
        storage = self._make_storage()
        ts = datetime(2026, 3, 16, 10, 30, 0)
        storage.insert_trade(
            ts=ts, orderid="ORD001", symbol="RELIANCE", exchange="NSE",
            action="BUY", quantity=10, price=2500.0,
            strategy="Flint", pnl=200.0,
        )
        trades = storage.get_trades_by_strategy("Flint", "2026-03-16", "2026-03-16")
        assert len(trades) == 1
        assert trades[0]["orderid"] == "ORD001"
        assert trades[0]["pnl"] == 200.0
        storage.close()

    def test_get_trades_by_date(self):
        storage = self._make_storage()
        ts = datetime(2026, 3, 16, 10, 30, 0)
        storage.insert_trade(
            ts=ts, orderid="ORD001", symbol="TCS", exchange="NSE",
            action="SELL", quantity=5, price=3500.0, strategy="Flint",
        )
        trades = storage.get_trades_by_date("2026-03-16")
        assert len(trades) == 1
        storage.close()

    def test_upsert_daily_summary(self):
        storage = self._make_storage()
        d = date(2026, 3, 16)
        storage.upsert_daily_summary(
            trade_date=d, strategy="Flint",
            total_trades=10, winning_trades=6, losing_trades=4,
            gross_pnl=5000.0, fees=100.0, net_pnl=4900.0,
        )
        summaries = storage.get_daily_summaries("2026-03-16", "2026-03-16", "Flint")
        assert len(summaries) == 1
        assert summaries[0]["total_trades"] == 10
        assert summaries[0]["net_pnl"] == 4900.0

        # Upsert overwrites
        storage.upsert_daily_summary(
            trade_date=d, strategy="Flint",
            total_trades=12, winning_trades=8, losing_trades=4,
            gross_pnl=6000.0, fees=120.0, net_pnl=5880.0,
        )
        summaries = storage.get_daily_summaries("2026-03-16", "2026-03-16", "Flint")
        assert len(summaries) == 1
        assert summaries[0]["total_trades"] == 12
        storage.close()

    def test_get_daily_summaries_no_strategy_filter(self):
        storage = self._make_storage()
        d = date(2026, 3, 16)
        storage.upsert_daily_summary(
            trade_date=d, strategy="A",
            total_trades=5, winning_trades=3, losing_trades=2,
            gross_pnl=1000, fees=50, net_pnl=950,
        )
        storage.upsert_daily_summary(
            trade_date=d, strategy="B",
            total_trades=3, winning_trades=1, losing_trades=2,
            gross_pnl=-500, fees=30, net_pnl=-530,
        )
        summaries = storage.get_daily_summaries("2026-03-16", "2026-03-16")
        assert len(summaries) == 2
        storage.close()

    def test_export_trades_csv(self):
        storage = self._make_storage()
        ts = datetime(2026, 3, 16, 10, 30, 0)
        storage.insert_trade(
            ts=ts, orderid="ORD001", symbol="RELIANCE", exchange="NSE",
            action="BUY", quantity=10, price=2500.0, strategy="Flint",
        )
        csv_str = storage.export_trades_csv("2026-03-16", "2026-03-16", "Flint")
        assert "RELIANCE" in csv_str
        assert "ORD001" in csv_str
        assert csv_str.startswith("ts,")  # header row
        storage.close()

    def test_export_empty_returns_empty_string(self):
        storage = self._make_storage()
        csv_str = storage.export_trades_csv("2026-03-16", "2026-03-16", "NoSuch")
        assert csv_str == ""
        storage.close()

    def test_context_manager(self):
        from packages.data.src.storage import StorageManager
        with StorageManager(":memory:") as storage:
            storage.initialize()
            storage.insert_tick(
                ts=datetime(2026, 3, 16, 10, 0, 0),
                symbol="INFY", exchange="NSE", mode="ltp", ltp=1500.0,
            )
            ticks = storage.get_ticks("INFY", "NSE", "2026-03-16", "2026-03-16")
            assert len(ticks) == 1


# ======================================================================
# AuditLogger — SEBI-compliant JSONL writing
# ======================================================================


class TestAuditLogger:
    """Test audit logger writes correct JSONL files."""

    def test_log_order_placed_creates_file(self, tmp_path):
        from packages.data.src.audit_logger import AuditLogger
        audit = AuditLogger(str(tmp_path))
        audit.log_order_placed(
            strategy="Flint", symbol="RELIANCE", exchange="NSE",
            action="BUY", quantity="10", price="2500",
        )
        audit.close()

        files = list(tmp_path.glob("audit_*.jsonl"))
        assert len(files) == 1

        with open(files[0]) as f:
            lines = f.readlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["event_type"] == "ORDER_PLACED"
        assert event["symbol"] == "RELIANCE"
        assert event["action"] == "BUY"

    def test_multiple_events_same_file(self, tmp_path):
        from packages.data.src.audit_logger import AuditLogger
        audit = AuditLogger(str(tmp_path))
        audit.log_order_placed(
            strategy="Flint", symbol="RELIANCE", exchange="NSE",
            action="BUY", quantity="10", price="2500",
        )
        audit.log_order_cancelled(strategy="Flint", orderid="123")
        audit.log_login(user="admin", ip="192.168.1.100")
        audit.close()

        files = list(tmp_path.glob("audit_*.jsonl"))
        assert len(files) == 1

        with open(files[0]) as f:
            lines = f.readlines()
        assert len(lines) == 3
        assert json.loads(lines[0])["event_type"] == "ORDER_PLACED"
        assert json.loads(lines[1])["event_type"] == "ORDER_CANCELLED"
        assert json.loads(lines[2])["event_type"] == "LOGIN"

    def test_log_order_modified(self, tmp_path):
        from packages.data.src.audit_logger import AuditLogger
        audit = AuditLogger(str(tmp_path))
        audit.log_order_modified(
            strategy="Flint", symbol="TCS", exchange="NSE",
            orderid="456", action="BUY", quantity="5", price="3500",
        )
        audit.close()

        events = audit.read_day(datetime.now(IST).strftime("%Y-%m-%d"))
        assert len(events) == 1
        assert events[0]["event_type"] == "ORDER_MODIFIED"
        assert events[0]["orderid"] == "456"

    def test_log_safety_check(self, tmp_path):
        from packages.data.src.audit_logger import AuditLogger
        audit = AuditLogger(str(tmp_path))
        audit.log_safety_check(
            layer="L1_ORDER", verdict="FAIL",
            reason="Price deviation 12%", symbol="RELIANCE",
        )
        audit.close()

        events = audit.read_day(datetime.now(IST).strftime("%Y-%m-%d"))
        assert events[0]["layer"] == "L1_ORDER"
        assert events[0]["verdict"] == "FAIL"

    def test_log_kill_switch(self, tmp_path):
        from packages.data.src.audit_logger import AuditLogger
        audit = AuditLogger(str(tmp_path))
        audit.log_kill_switch(activated=True, reason="Daily P&L kill")
        audit.log_kill_switch(activated=False, reason="Manual reset")
        audit.close()

        events = audit.read_day(datetime.now(IST).strftime("%Y-%m-%d"))
        assert events[0]["event_type"] == "KILL_SWITCH_ACTIVATED"
        assert events[1]["event_type"] == "KILL_SWITCH_RESET"

    def test_log_login_logout(self, tmp_path):
        from packages.data.src.audit_logger import AuditLogger
        audit = AuditLogger(str(tmp_path))
        audit.log_login(user="admin", ip="192.168.1.100", method="TOTP")
        audit.log_logout(user="admin", reason="session_timeout")
        audit.close()

        events = audit.read_day(datetime.now(IST).strftime("%Y-%m-%d"))
        assert events[0]["event_type"] == "LOGIN"
        assert events[0]["method"] == "TOTP"
        assert events[1]["event_type"] == "LOGOUT"

    def test_log_generic_event(self, tmp_path):
        from packages.data.src.audit_logger import AuditLogger
        audit = AuditLogger(str(tmp_path))
        audit.log_event("STRATEGY_STARTED", name="Scalper", exchange="NFO")
        audit.close()

        events = audit.read_day(datetime.now(IST).strftime("%Y-%m-%d"))
        assert events[0]["event_type"] == "STRATEGY_STARTED"
        assert events[0]["name"] == "Scalper"

    def test_read_nonexistent_day_returns_empty(self, tmp_path):
        from packages.data.src.audit_logger import AuditLogger
        audit = AuditLogger(str(tmp_path))
        events = audit.read_day("2020-01-01")
        assert events == []

    def test_all_events_have_timestamp(self, tmp_path):
        from packages.data.src.audit_logger import AuditLogger
        audit = AuditLogger(str(tmp_path))
        audit.log_order_placed(
            strategy="Flint", symbol="INFY", exchange="NSE",
            action="SELL", quantity="1", price="1500",
        )
        audit.close()

        events = audit.read_day(datetime.now(IST).strftime("%Y-%m-%d"))
        assert "ts" in events[0]
        assert "T" in events[0]["ts"]  # ISO format

    def test_list_audit_files(self, tmp_path):
        from packages.data.src.audit_logger import AuditLogger
        audit = AuditLogger(str(tmp_path))
        audit.log_event("TEST")
        audit.close()

        files = audit.list_audit_files()
        assert len(files) >= 1
        assert files[0].startswith("audit_")

    def test_compress_old_files(self, tmp_path):
        from packages.data.src.audit_logger import AuditLogger
        # Create a fake old audit file
        old_file = tmp_path / "audit_2020-01-01.jsonl"
        old_file.write_text('{"event_type": "TEST", "ts": "2020-01-01T00:00:00"}\n')

        audit = AuditLogger(str(tmp_path))
        compressed = audit.compress_old_files(older_than_days=1)
        assert compressed == 1

        # Original removed, gz exists
        assert not old_file.exists()
        assert (tmp_path / "audit_2020-01-01.jsonl.gz").exists()

    def test_read_compressed_file(self, tmp_path):
        import gzip
        from packages.data.src.audit_logger import AuditLogger

        # Write a gzipped audit file
        gz_path = tmp_path / "audit_2020-06-15.jsonl.gz"
        with gzip.open(gz_path, "wt", encoding="utf-8") as f:
            f.write('{"event_type": "ORDER_PLACED", "ts": "2020-06-15T10:00:00"}\n')

        audit = AuditLogger(str(tmp_path))
        events = audit.read_day("2020-06-15")
        assert len(events) == 1
        assert events[0]["event_type"] == "ORDER_PLACED"

    def test_context_manager(self, tmp_path):
        from packages.data.src.audit_logger import AuditLogger
        with AuditLogger(str(tmp_path)) as audit:
            audit.log_event("CONTEXT_TEST")
        # File should exist after context manager exits
        files = list(tmp_path.glob("audit_*.jsonl"))
        assert len(files) == 1


# ======================================================================
# TradeLogger — P&L calculation + daily summaries
# ======================================================================


class TestTradeLogger:
    """Test trade logging, P&L calculation, and daily summaries."""

    def _make_storage_and_logger(self):
        from packages.data.src.storage import StorageManager
        from packages.data.src.trade_logger import TradeLogger
        storage = StorageManager(":memory:")
        storage.initialize()
        return storage, TradeLogger(storage)

    def test_calculate_pnl_buy(self):
        from packages.data.src.trade_logger import TradeLogger
        pnl = TradeLogger.calculate_pnl("BUY", 10, entry_price=2500.0, exit_price=2520.0)
        assert pnl == 200.0

    def test_calculate_pnl_sell_short(self):
        from packages.data.src.trade_logger import TradeLogger
        pnl = TradeLogger.calculate_pnl("SELL", 10, entry_price=2520.0, exit_price=2500.0)
        assert pnl == 200.0

    def test_calculate_pnl_loss(self):
        from packages.data.src.trade_logger import TradeLogger
        pnl = TradeLogger.calculate_pnl("BUY", 10, entry_price=2500.0, exit_price=2480.0)
        assert pnl == -200.0

    def test_log_trade_stores_in_duckdb(self):
        storage, tl = self._make_storage_and_logger()
        tl.log_trade(
            orderid="ORD001", symbol="RELIANCE", exchange="NSE",
            action="BUY", quantity=10, price=2500.0, strategy="Flint",
        )
        trades = storage.get_trades_by_date(datetime.now(IST).strftime("%Y-%m-%d"))
        assert len(trades) == 1
        assert trades[0]["symbol"] == "RELIANCE"
        storage.close()

    def test_log_trade_with_pnl(self):
        storage, tl = self._make_storage_and_logger()
        tl.log_trade(
            orderid="ORD002", symbol="TCS", exchange="NSE",
            action="BUY", quantity=5, price=3520.0, strategy="Flint",
            entry_price=3500.0, exit_price=3520.0,
        )
        today = datetime.now(IST).strftime("%Y-%m-%d")
        trades = storage.get_trades_by_strategy("Flint", today, today)
        assert len(trades) == 1
        assert trades[0]["pnl"] == 100.0  # (3520-3500)*5
        storage.close()

    def test_log_trade_with_slippage(self):
        storage, tl = self._make_storage_and_logger()
        tl.log_trade(
            orderid="ORD003", symbol="INFY", exchange="NSE",
            action="BUY", quantity=10, price=1502.0, strategy="Flint",
            expected_price=1500.0,
        )
        today = datetime.now(IST).strftime("%Y-%m-%d")
        trades = storage.get_trades_by_strategy("Flint", today, today)
        assert trades[0]["slippage"] == 2.0
        storage.close()

    def test_compute_daily_summary(self):
        storage, tl = self._make_storage_and_logger()
        today = datetime.now(IST).strftime("%Y-%m-%d")
        ts = datetime.now(IST)

        # Simulate 3 trades: 2 winning, 1 losing
        storage.insert_trade(
            ts=ts, orderid="1", symbol="A", exchange="NSE",
            action="BUY", quantity=10, price=100.0,
            strategy="Flint", pnl=500.0, fees=10.0,
        )
        storage.insert_trade(
            ts=ts, orderid="2", symbol="B", exchange="NSE",
            action="SELL", quantity=5, price=200.0,
            strategy="Flint", pnl=300.0, fees=8.0,
        )
        storage.insert_trade(
            ts=ts, orderid="3", symbol="C", exchange="NSE",
            action="BUY", quantity=20, price=50.0,
            strategy="Flint", pnl=-200.0, fees=5.0,
        )

        summary = tl.compute_daily_summary(today, "Flint")
        assert summary.total_trades == 3
        assert summary.winning_trades == 2
        assert summary.losing_trades == 1
        assert summary.gross_pnl == 600.0  # 500 + 300 - 200
        assert summary.fees == 23.0
        assert summary.net_pnl == 577.0
        assert summary.win_rate == pytest.approx(66.67, abs=0.1)
        storage.close()

    def test_daily_summary_persisted(self):
        storage, tl = self._make_storage_and_logger()
        today = datetime.now(IST).strftime("%Y-%m-%d")
        ts = datetime.now(IST)

        storage.insert_trade(
            ts=ts, orderid="1", symbol="A", exchange="NSE",
            action="BUY", quantity=1, price=100.0,
            strategy="Flint", pnl=50.0,
        )
        tl.compute_daily_summary(today, "Flint")

        summaries = storage.get_daily_summaries(today, today, "Flint")
        assert len(summaries) == 1
        assert summaries[0]["total_trades"] == 1
        storage.close()

    def test_daily_summary_max_drawdown(self):
        storage, tl = self._make_storage_and_logger()
        today = datetime.now(IST).strftime("%Y-%m-%d")
        ts = datetime.now(IST)

        # Sequence: +500, -300, -400 → peak 500, trough -200 → dd=700
        storage.insert_trade(
            ts=ts, orderid="1", symbol="A", exchange="NSE",
            action="BUY", quantity=1, price=100.0,
            strategy="Test", pnl=500.0,
        )
        storage.insert_trade(
            ts=ts, orderid="2", symbol="B", exchange="NSE",
            action="BUY", quantity=1, price=100.0,
            strategy="Test", pnl=-300.0,
        )
        storage.insert_trade(
            ts=ts, orderid="3", symbol="C", exchange="NSE",
            action="BUY", quantity=1, price=100.0,
            strategy="Test", pnl=-400.0,
        )

        summary = tl.compute_daily_summary(today, "Test")
        assert summary.max_drawdown == 700.0
        storage.close()

    def test_empty_day_summary(self):
        storage, tl = self._make_storage_and_logger()
        summary = tl.compute_daily_summary("2026-01-01", "Flint")
        assert summary.total_trades == 0
        assert summary.win_rate == 0.0
        assert summary.avg_pnl_per_trade == 0.0
        storage.close()

    def test_export_csv(self):
        storage, tl = self._make_storage_and_logger()
        today = datetime.now(IST).strftime("%Y-%m-%d")
        ts = datetime.now(IST)

        storage.insert_trade(
            ts=ts, orderid="ORD001", symbol="RELIANCE", exchange="NSE",
            action="BUY", quantity=10, price=2500.0, strategy="Flint",
        )
        csv_str = tl.export_csv(today, today, "Flint")
        assert "RELIANCE" in csv_str
        assert "ORD001" in csv_str
        storage.close()

    def test_trade_summary_dataclass(self):
        from packages.data.src.trade_logger import TradeSummary
        s = TradeSummary(
            trade_date=date(2026, 3, 16), strategy="Flint",
            total_trades=10, winning_trades=7, losing_trades=3,
            gross_pnl=5000.0, fees=100.0, net_pnl=4900.0,
        )
        assert s.win_rate == 70.0
        assert s.avg_pnl_per_trade == 490.0


# ======================================================================
# TickRecorder — unit tests (no live WebSocket)
# ======================================================================


class TestTickRecorder:
    """Test TickRecorder watchlist management and tick processing."""

    def _make_recorder(self):
        from packages.data.src.storage import StorageManager
        from packages.data.src.tick_recorder import TickRecorder
        storage = StorageManager(":memory:")
        storage.initialize()
        return storage, TickRecorder(storage=storage)

    def test_add_symbols(self):
        _, recorder = self._make_recorder()
        recorder.add_symbols([
            {"exchange": "NSE", "symbol": "RELIANCE"},
            {"exchange": "NFO", "symbol": "NIFTY26MAR2524000CE"},
        ], mode="quote")
        wl = recorder.get_watchlist()
        assert len(wl["quote"]) == 2

    def test_add_duplicate_ignored(self):
        _, recorder = self._make_recorder()
        inst = {"exchange": "NSE", "symbol": "RELIANCE"}
        recorder.add_symbols([inst], mode="ltp")
        recorder.add_symbols([inst], mode="ltp")
        assert len(recorder.get_watchlist()["ltp"]) == 1

    def test_remove_symbols(self):
        _, recorder = self._make_recorder()
        inst = {"exchange": "NSE", "symbol": "RELIANCE"}
        recorder.add_symbols([inst], mode="quote")
        recorder.remove_symbols([inst], mode="quote")
        assert len(recorder.get_watchlist()["quote"]) == 0

    def test_remove_nonexistent_no_error(self):
        _, recorder = self._make_recorder()
        recorder.remove_symbols([{"exchange": "NSE", "symbol": "GHOST"}], mode="ltp")

    def test_invalid_mode_raises(self):
        _, recorder = self._make_recorder()
        with pytest.raises(ValueError, match="Invalid mode"):
            recorder.add_symbols([{"exchange": "NSE", "symbol": "X"}], mode="invalid")

    def test_process_tick_ltp(self):
        storage, recorder = self._make_recorder()
        recorder._process_tick({"symbol": "RELIANCE", "exchange": "NSE", "ltp": 2500.0})
        assert recorder.tick_count == 1
        assert len(recorder._buffer) == 1

    def test_process_tick_quote(self):
        _, recorder = self._make_recorder()
        recorder._process_tick({
            "symbol": "RELIANCE", "exchange": "NSE",
            "ltp": 2500.0, "bid": 2499.0, "ask": 2501.0, "volume": 1000,
        })
        assert recorder._buffer[0][3] == "quote"  # mode

    def test_process_tick_depth(self):
        _, recorder = self._make_recorder()
        recorder._process_tick({
            "symbol": "RELIANCE", "exchange": "NSE",
            "ltp": 2500.0, "bids": [{"price": 2499, "qty": 100}],
            "asks": [{"price": 2501, "qty": 50}],
        })
        assert recorder._buffer[0][3] == "depth"
        assert recorder._buffer[0][14] is not None  # depth_json

    def test_process_tick_missing_symbol_ignored(self):
        _, recorder = self._make_recorder()
        recorder._process_tick({"exchange": "NSE", "ltp": 2500.0})
        assert recorder.tick_count == 0

    def test_flush_writes_to_duckdb(self):
        storage, recorder = self._make_recorder()
        recorder._process_tick({"symbol": "TCS", "exchange": "NSE", "ltp": 3500.0})
        recorder._process_tick({"symbol": "INFY", "exchange": "NSE", "ltp": 1500.0})
        recorder._flush()
        assert len(recorder._buffer) == 0
        # Query ticks directly — avoids timezone edge cases around midnight
        result = storage.connection.execute("SELECT COUNT(*) FROM ticks").fetchone()
        assert result[0] == 2

    def test_detect_mode(self):
        from packages.data.src.tick_recorder import TickRecorder
        assert TickRecorder._detect_mode({"ltp": 100}) == "ltp"
        assert TickRecorder._detect_mode({"ltp": 100, "bid": 99, "volume": 1000}) == "quote"
        assert TickRecorder._detect_mode({"ltp": 100, "bids": []}) == "depth"

    def test_all_exchange_symbols(self):
        """Verify recorder handles all supported exchanges."""
        _, recorder = self._make_recorder()
        exchanges = ["NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "NCDEX", "DELTA"]
        for exch in exchanges:
            recorder._process_tick({"symbol": "TEST", "exchange": exch, "ltp": 100.0})
        assert recorder.tick_count == len(exchanges)


# ======================================================================
# Package exports
# ======================================================================


class TestPackageExports:
    """Verify __init__.py exports the public API."""

    def test_all_exports(self):
        from packages.data.src import __all__
        expected = ["StorageManager", "TickRecorder", "AuditLogger", "TradeLogger", "TradeSummary"]
        for name in expected:
            assert name in __all__, f"Missing export: {name}"

    def test_version(self):
        from packages.data.src import __version__
        assert __version__ == "0.1.0-alpha"

    def test_package_exists(self):
        pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        assert os.path.exists(os.path.join(pkg_dir, "src", "__init__.py"))
        assert os.path.exists(os.path.join(pkg_dir, "CLAUDE.md"))
        assert os.path.exists(os.path.join(pkg_dir, "AGENTS.md"))
