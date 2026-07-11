"""Tests for FlintTrade data package.

DO NOT RUN — written for pytest. DuckDB tests use in-memory databases.
Audit logger tests use tmp_path fixture.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

IST = timezone(timedelta(hours=5, minutes=30))


# ======================================================================
# StorageManager — DuckDB table creation + queries
# ======================================================================


class TestStorageManager:
    """Test DuckDB schema creation and query helpers."""

    def _make_storage(self):
        from flinttrade_data.storage import StorageManager

        # Use in-memory DuckDB for tests
        storage = StorageManager(":memory:")
        storage.initialise()
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
        storage.initialise()
        storage.close()

    def test_insert_and_query_tick(self):
        storage = self._make_storage()
        ts = datetime(2026, 3, 16, 10, 0, 0)
        storage.insert_tick(
            ts=ts,
            symbol="RELIANCE",
            exchange="NSE",
            mode="quote",
            ltp=2500.0,
            volume=1000,
            bid=2499.0,
            ask=2501.0,
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

    def test_insert_ticks_batch_is_atomic_on_partial_failure(self):
        # The batch must be all-or-nothing: a mid-batch failure rolls the WHOLE
        # batch back, leaving no committed prefix. This is what lets the
        # TickRecorder retain-and-retry a failed buffer WITHOUT duplicating rows
        # the failed attempt already wrote (the ticks table has no unique key).
        storage = self._make_storage()
        ts = datetime(2026, 3, 16, 10, 0, 0)

        def good(ltp: float) -> tuple:
            return (ts, "TCS", "NSE", "ltp", ltp, None, None, None, None, None, None, None, None, None, None)

        # 3rd row has ts=None → violates TIMESTAMP NOT NULL partway through.
        bad = (None, "TCS", "NSE", "ltp", 3.0, None, None, None, None, None, None, None, None, None, None)

        with pytest.raises(Exception):
            storage.insert_ticks_batch([good(1.0), good(2.0), bad, good(4.0)])

        # Nothing committed — the prefix (rows 1-2) was rolled back, not left behind.
        assert storage.connection.execute("SELECT COUNT(*) FROM ticks").fetchone()[0] == 0

        # A clean retry of the corrected batch inserts exactly 3 — no duplicated prefix.
        storage.insert_ticks_batch([good(1.0), good(2.0), good(4.0)])
        assert storage.connection.execute("SELECT COUNT(*) FROM ticks").fetchone()[0] == 3
        storage.close()

    def test_prune_ticks_removes_old_keeps_recent(self):
        from datetime import datetime, timedelta

        storage = self._make_storage()
        now = datetime.now()

        def row(ts, ltp):
            return (ts, "TCS", "NSE", "ltp", ltp, None, None, None, None, None, None, None, None, None, None)

        storage.insert_ticks_batch(
            [
                row(now - timedelta(days=30), 1.0),  # old → pruned
                row(now - timedelta(hours=1), 2.0),  # recent → kept
            ]
        )

        removed = storage.prune_ticks(7)
        assert removed == 1
        kept = storage.connection.execute("SELECT ltp FROM ticks").fetchall()
        assert [r[0] for r in kept] == [2.0]
        storage.close()

    def test_prune_ticks_noop_for_nonpositive_window(self):
        from datetime import datetime

        storage = self._make_storage()
        row = (datetime.now(), "TCS", "NSE", "ltp", 1.0, None, None, None, None, None, None, None, None, None, None)
        storage.insert_ticks_batch([row])

        assert storage.prune_ticks(0) == 0
        assert storage.connection.execute("SELECT COUNT(*) FROM ticks").fetchone()[0] == 1
        storage.close()

    def test_query_ticks_date_range_filters(self):
        storage = self._make_storage()
        storage.insert_tick(
            ts=datetime(2026, 3, 15, 10, 0, 0),
            symbol="RELIANCE",
            exchange="NSE",
            mode="ltp",
            ltp=2490.0,
        )
        storage.insert_tick(
            ts=datetime(2026, 3, 16, 10, 0, 0),
            symbol="RELIANCE",
            exchange="NSE",
            mode="ltp",
            ltp=2500.0,
        )
        ticks = storage.get_ticks("RELIANCE", "NSE", "2026-03-16", "2026-03-16")
        assert len(ticks) == 1
        assert ticks[0]["ltp"] == 2500.0
        storage.close()

    def test_query_ticks_limit_returns_most_recent_rows_in_chronological_order(self):
        import inspect

        storage = self._make_storage()
        for index in range(5):
            storage.insert_tick(
                ts=datetime(2026, 3, 16, 10, 0, index),
                symbol="RELIANCE",
                exchange="NSE",
                mode="ltp",
                ltp=2500.0 + index,
            )

        parameters = inspect.signature(storage.get_ticks).parameters
        assert "limit" in parameters
        ticks = storage.get_ticks("RELIANCE", "NSE", "2026-03-16", "2026-03-16", limit=2)

        assert [tick["ltp"] for tick in ticks] == [2503.0, 2504.0]
        storage.close()

    def test_legacy_tick_schema_migrates_with_stable_same_timestamp_order(self, tmp_path):
        import duckdb

        from flinttrade_data.storage import StorageManager

        db_path = tmp_path / "legacy-ticks.duckdb"
        legacy = duckdb.connect(str(db_path))
        legacy.execute(
            """CREATE TABLE ticks (
                ts TIMESTAMP NOT NULL,
                symbol VARCHAR NOT NULL,
                exchange VARCHAR NOT NULL,
                mode VARCHAR NOT NULL,
                ltp DOUBLE,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume BIGINT,
                bid DOUBLE,
                ask DOUBLE,
                oi BIGINT,
                prev_close DOUBLE,
                depth_json VARCHAR
            )"""
        )
        timestamp = datetime(2026, 3, 16, 4, 0)
        legacy.executemany(
            "INSERT INTO ticks (ts, symbol, exchange, mode, ltp) VALUES (?, 'RELIANCE', 'NSE', 'ltp', ?)",
            [(timestamp, 2500.0), (timestamp, 2501.0)],
        )
        legacy.close()

        storage = StorageManager(str(db_path))
        storage.initialise()
        storage.insert_tick(timestamp, "RELIANCE", "NSE", "ltp", ltp=2502.0)

        columns = {
            row[1]: row
            for row in storage.connection.execute("PRAGMA table_info('ticks')").fetchall()
        }
        ticks = storage.get_ticks("RELIANCE", "NSE", "2026-03-16", "2026-03-16", limit=2)

        assert columns["ingest_seq"][3] is True
        assert [tick["ltp"] for tick in ticks] == [2501.0, 2502.0]
        assert all("ingest_seq" not in tick for tick in ticks)
        storage.close()

    def test_insert_and_query_trade(self):
        storage = self._make_storage()
        ts = datetime(2026, 3, 16, 10, 30, 0)
        storage.insert_trade(
            ts=ts,
            orderid="ORD001",
            symbol="RELIANCE",
            exchange="NSE",
            action="BUY",
            quantity=10,
            price=2500.0,
            strategy="Flint",
            pnl=200.0,
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
            ts=ts,
            orderid="ORD001",
            symbol="TCS",
            exchange="NSE",
            action="SELL",
            quantity=5,
            price=3500.0,
            strategy="Flint",
        )
        trades = storage.get_trades_by_date("2026-03-16")
        assert len(trades) == 1
        storage.close()

    def test_get_trades_by_date_uses_ist_window_for_aware_timestamps(self):
        storage = self._make_storage()
        ts = datetime(2026, 3, 17, 0, 10, 0, tzinfo=IST)
        storage.insert_trade(
            ts=ts,
            orderid="ORD-MIDNIGHT",
            symbol="TCS",
            exchange="NSE",
            action="BUY",
            quantity=1,
            price=3500.0,
            strategy="Flint",
        )

        raw_ts = storage.connection.execute("SELECT ts FROM trades WHERE orderid = 'ORD-MIDNIGHT'").fetchone()[0]
        assert raw_ts == datetime(2026, 3, 16, 18, 40, 0)

        trades = storage.get_trades_by_date("2026-03-17")
        assert [trade["orderid"] for trade in trades] == ["ORD-MIDNIGHT"]
        assert storage.get_trades_by_date("2026-03-16") == []
        storage.close()

    def test_upsert_daily_summary(self):
        storage = self._make_storage()
        d = date(2026, 3, 16)
        storage.upsert_daily_summary(
            trade_date=d,
            strategy="Flint",
            total_trades=10,
            winning_trades=6,
            losing_trades=4,
            gross_pnl=5000.0,
            fees=100.0,
            net_pnl=4900.0,
        )
        summaries = storage.get_daily_summaries("2026-03-16", "2026-03-16", "Flint")
        assert len(summaries) == 1
        assert summaries[0]["total_trades"] == 10
        assert summaries[0]["net_pnl"] == 4900.0

        # Upsert overwrites
        storage.upsert_daily_summary(
            trade_date=d,
            strategy="Flint",
            total_trades=12,
            winning_trades=8,
            losing_trades=4,
            gross_pnl=6000.0,
            fees=120.0,
            net_pnl=5880.0,
        )
        summaries = storage.get_daily_summaries("2026-03-16", "2026-03-16", "Flint")
        assert len(summaries) == 1
        assert summaries[0]["total_trades"] == 12
        storage.close()

    def test_get_daily_summaries_no_strategy_filter(self):
        storage = self._make_storage()
        d = date(2026, 3, 16)
        storage.upsert_daily_summary(
            trade_date=d,
            strategy="A",
            total_trades=5,
            winning_trades=3,
            losing_trades=2,
            gross_pnl=1000,
            fees=50,
            net_pnl=950,
        )
        storage.upsert_daily_summary(
            trade_date=d,
            strategy="B",
            total_trades=3,
            winning_trades=1,
            losing_trades=2,
            gross_pnl=-500,
            fees=30,
            net_pnl=-530,
        )
        summaries = storage.get_daily_summaries("2026-03-16", "2026-03-16")
        assert len(summaries) == 2
        storage.close()

    def test_export_trades_csv(self):
        storage = self._make_storage()
        ts = datetime(2026, 3, 16, 10, 30, 0)
        storage.insert_trade(
            ts=ts,
            orderid="ORD001",
            symbol="RELIANCE",
            exchange="NSE",
            action="BUY",
            quantity=10,
            price=2500.0,
            strategy="Flint",
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

    def test_export_no_strategy_honours_end_date_range(self):
        # Regression (G28b): the all-strategies export once dropped end_date and
        # returned only the start day. It must span the inclusive range and
        # exclude days outside it.
        storage = self._make_storage()
        for day, oid, sym in ((1, "D1", "AAA"), (2, "D2", "BBB"), (3, "D3", "CCC")):
            storage.insert_trade(
                ts=datetime(2026, 3, day, 10, 0, 0),
                orderid=oid,
                symbol=sym,
                exchange="NSE",
                action="BUY",
                quantity=1,
                price=100.0,
                strategy="Flint",
            )
        csv_str = storage.export_trades_csv("2026-03-01", "2026-03-02")  # no strategy
        assert "AAA" in csv_str and "BBB" in csv_str  # both in-range days present
        assert "CCC" not in csv_str  # day outside the range excluded
        storage.close()

    def test_context_manager(self):
        from flinttrade_data.storage import StorageManager

        with StorageManager(":memory:") as storage:
            storage.initialise()
            storage.insert_tick(
                ts=datetime(2026, 3, 16, 10, 0, 0),
                symbol="INFY",
                exchange="NSE",
                mode="ltp",
                ltp=1500.0,
            )
            ticks = storage.get_ticks("INFY", "NSE", "2026-03-16", "2026-03-16")
            assert len(ticks) == 1


# ======================================================================
# AuditLogger — append-only JSONL writing
# ======================================================================


class TestAuditLogger:
    """Test audit logger writes correct JSONL files."""

    def test_log_order_placed_creates_file(self, tmp_path):
        from flinttrade_data.audit_logger import AuditLogger

        audit = AuditLogger(str(tmp_path))
        audit.log_order_placed(
            strategy="Flint",
            symbol="RELIANCE",
            exchange="NSE",
            action="BUY",
            quantity="10",
            price="2500",
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
        from flinttrade_data.audit_logger import AuditLogger

        audit = AuditLogger(str(tmp_path))
        audit.log_order_placed(
            strategy="Flint",
            symbol="RELIANCE",
            exchange="NSE",
            action="BUY",
            quantity="10",
            price="2500",
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
        from flinttrade_data.audit_logger import AuditLogger

        audit = AuditLogger(str(tmp_path))
        audit.log_order_modified(
            strategy="Flint",
            symbol="TCS",
            exchange="NSE",
            orderid="456",
            action="BUY",
            quantity="5",
            price="3500",
        )
        audit.close()

        events = audit.read_day(datetime.now(IST).strftime("%Y-%m-%d"))
        assert len(events) == 1
        assert events[0]["event_type"] == "ORDER_MODIFIED"
        assert events[0]["orderid"] == "456"

    def test_log_safety_check(self, tmp_path):
        from flinttrade_data.audit_logger import AuditLogger

        audit = AuditLogger(str(tmp_path))
        audit.log_safety_check(
            layer="L1_ORDER",
            verdict="FAIL",
            reason="Price deviation 12%",
            symbol="RELIANCE",
        )
        audit.close()

        events = audit.read_day(datetime.now(IST).strftime("%Y-%m-%d"))
        assert events[0]["layer"] == "L1_ORDER"
        assert events[0]["verdict"] == "FAIL"

    def test_log_kill_switch(self, tmp_path):
        from flinttrade_data.audit_logger import AuditLogger

        audit = AuditLogger(str(tmp_path))
        audit.log_kill_switch(activated=True, reason="Daily P&L kill")
        audit.log_kill_switch(activated=False, reason="Manual reset")
        audit.close()

        events = audit.read_day(datetime.now(IST).strftime("%Y-%m-%d"))
        assert events[0]["event_type"] == "KILL_SWITCH_ACTIVATED"
        assert events[1]["event_type"] == "KILL_SWITCH_RESET"

    def test_log_login_logout(self, tmp_path):
        from flinttrade_data.audit_logger import AuditLogger

        audit = AuditLogger(str(tmp_path))
        audit.log_login(user="admin", ip="192.168.1.100", method="TOTP")
        audit.log_logout(user="admin", reason="session_timeout")
        audit.close()

        events = audit.read_day(datetime.now(IST).strftime("%Y-%m-%d"))
        assert events[0]["event_type"] == "LOGIN"
        assert events[0]["method"] == "TOTP"
        assert events[1]["event_type"] == "LOGOUT"

    def test_log_generic_event(self, tmp_path):
        from flinttrade_data.audit_logger import AuditLogger

        audit = AuditLogger(str(tmp_path))
        audit.log_event("STRATEGY_STARTED", name="Scalper", exchange="NFO")
        audit.close()

        events = audit.read_day(datetime.now(IST).strftime("%Y-%m-%d"))
        assert events[0]["event_type"] == "STRATEGY_STARTED"
        assert events[0]["name"] == "Scalper"

    def test_read_nonexistent_day_returns_empty(self, tmp_path):
        from flinttrade_data.audit_logger import AuditLogger

        audit = AuditLogger(str(tmp_path))
        events = audit.read_day("2020-01-01")
        assert events == []

    def test_all_events_have_timestamp(self, tmp_path):
        from flinttrade_data.audit_logger import AuditLogger

        audit = AuditLogger(str(tmp_path))
        audit.log_order_placed(
            strategy="Flint",
            symbol="INFY",
            exchange="NSE",
            action="SELL",
            quantity="1",
            price="1500",
        )
        audit.close()

        events = audit.read_day(datetime.now(IST).strftime("%Y-%m-%d"))
        assert "ts" in events[0]
        assert "T" in events[0]["ts"]  # ISO format

    def test_list_audit_files(self, tmp_path):
        from flinttrade_data.audit_logger import AuditLogger

        audit = AuditLogger(str(tmp_path))
        audit.log_event("TEST")
        audit.close()

        files = audit.list_audit_files()
        assert len(files) >= 1
        assert files[0].startswith("audit_")

    def test_compress_old_files(self, tmp_path):
        from flinttrade_data.audit_logger import AuditLogger

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
        from flinttrade_data.audit_logger import AuditLogger

        # Write a gzipped audit file
        gz_path = tmp_path / "audit_2020-06-15.jsonl.gz"
        with gzip.open(gz_path, "wt", encoding="utf-8") as f:
            f.write('{"event_type": "ORDER_PLACED", "ts": "2020-06-15T10:00:00"}\n')

        audit = AuditLogger(str(tmp_path))
        events = audit.read_day("2020-06-15")
        assert len(events) == 1
        assert events[0]["event_type"] == "ORDER_PLACED"

    def test_context_manager(self, tmp_path):
        from flinttrade_data.audit_logger import AuditLogger

        with AuditLogger(str(tmp_path)) as audit:
            audit.log_event("CONTEXT_TEST")
        # File should exist after context manager exits
        files = list(tmp_path.glob("audit_*.jsonl"))
        assert len(files) == 1


# ======================================================================
# AuditLogger — hash chain (tamper-evidence)
# ======================================================================


class TestAuditHashChain:
    """The audit log is a real SHA-256 hash chain, not just JSONL."""

    def _write_three(self, tmp_path):
        from flinttrade_data.audit_logger import AuditLogger

        audit = AuditLogger(str(tmp_path))
        audit.log_order_placed(
            strategy="Flint",
            symbol="RELIANCE",
            exchange="NSE",
            action="BUY",
            quantity="10",
            price="2500",
        )
        audit.log_safety_check(layer="L1_ORDER", verdict="PASS", symbol="RELIANCE")
        audit.log_order_cancelled(strategy="Flint", orderid="123")
        audit.close()
        return audit

    def test_records_carry_linked_chain_fields(self, tmp_path):
        from flinttrade_data.audit_logger import GENESIS_HASH

        audit = self._write_three(tmp_path)
        events = audit.read_day(datetime.now(IST).strftime("%Y-%m-%d"))
        assert [e["seq"] for e in events] == [0, 1, 2]
        # First record anchors at genesis; each subsequent prev_hash is the
        # previous record's hash — an actual chain, not independent hashes.
        assert events[0]["prev_hash"] == GENESIS_HASH
        assert events[1]["prev_hash"] == events[0]["hash"]
        assert events[2]["prev_hash"] == events[1]["hash"]
        assert len({e["hash"] for e in events}) == 3

    def test_verify_chain_passes_for_untampered_log(self, tmp_path):
        audit = self._write_three(tmp_path)
        result = audit.verify_chain()
        assert result["ok"] is True
        assert result["checked"] == 3
        assert result["break"] is None

    def test_verify_chain_detects_content_tampering(self, tmp_path):
        self._write_three(tmp_path)
        from flinttrade_data.audit_logger import AuditLogger

        path = next(tmp_path.glob("audit_*.jsonl"))
        lines = path.read_text().splitlines()
        rec = json.loads(lines[1])
        rec["price"] = "99999"  # edit a field WITHOUT recomputing its hash
        lines[1] = json.dumps(rec)
        path.write_text("\n".join(lines) + "\n")

        result = AuditLogger(str(tmp_path)).verify_chain()
        assert result["ok"] is False
        assert result["break"]["seq"] == 1
        assert "hash" in result["break"]["reason"]

    def test_verify_chain_detects_deletion(self, tmp_path):
        self._write_three(tmp_path)
        from flinttrade_data.audit_logger import AuditLogger

        path = next(tmp_path.glob("audit_*.jsonl"))
        lines = path.read_text().splitlines()
        del lines[1]  # remove the middle record
        path.write_text("\n".join(lines) + "\n")

        result = AuditLogger(str(tmp_path)).verify_chain()
        assert result["ok"] is False
        assert result["break"] is not None

    def test_chain_is_continuous_across_reopen(self, tmp_path):
        from flinttrade_data.audit_logger import AuditLogger

        first = AuditLogger(str(tmp_path))
        first.log_event("ONE")
        first.log_event("TWO")
        first.close()

        second = AuditLogger(str(tmp_path))  # fresh instance, same directory
        second.log_event("THREE")
        second.close()

        events = second.read_day(datetime.now(IST).strftime("%Y-%m-%d"))
        assert [e["seq"] for e in events] == [0, 1, 2]
        assert events[2]["prev_hash"] == events[1]["hash"]
        assert second.verify_chain()["ok"] is True

    def test_write_is_fsynced(self, tmp_path, monkeypatch):
        from flinttrade_data import audit_logger

        calls = {"n": 0}
        real_fsync = audit_logger.os.fsync

        def _counting_fsync(fd):
            calls["n"] += 1
            return real_fsync(fd)

        monkeypatch.setattr(audit_logger.os, "fsync", _counting_fsync)

        audit = audit_logger.AuditLogger(str(tmp_path))
        audit.log_event("DURABLE")
        audit.close()
        assert calls["n"] >= 1  # the record was fsync-ed, not just flushed

    def test_intact_chain_is_anchored_at_genesis(self, tmp_path):
        audit = self._write_three(tmp_path)
        result = audit.verify_chain()
        assert result["ok"] is True
        assert result["anchored_at_genesis"] is True

    def test_head_deletion_is_surfaced_as_not_anchored(self, tmp_path):
        # Deleting the oldest (genesis) record leaves a self-consistent tail, so
        # ok stays True — but the chain is no longer provably complete from the
        # start, which verify_chain reports honestly rather than hiding.
        self._write_three(tmp_path)
        from flinttrade_data.audit_logger import AuditLogger

        path = next(tmp_path.glob("audit_*.jsonl"))
        lines = path.read_text().splitlines()
        del lines[0]
        path.write_text("\n".join(lines) + "\n")

        result = AuditLogger(str(tmp_path)).verify_chain()
        assert result["ok"] is True
        assert result["anchored_at_genesis"] is False

    def test_torn_partial_tail_is_repaired_not_concatenated(self, tmp_path):
        # A crash mid-write leaves a newline-less partial record. The next open
        # must drop it (never fsync-committed), not merge the next record into it.
        from flinttrade_data.audit_logger import AuditLogger

        first = AuditLogger(str(tmp_path))
        first.log_event("ONE")
        first.log_event("TWO")
        first.close()
        path = next(tmp_path.glob("audit_*.jsonl"))
        with open(path, "a", encoding="utf-8") as fh:
            fh.write('{"event_type": "TORN", "seq": 9')  # no brace, no newline

        second = AuditLogger(str(tmp_path))
        second.log_event("THREE")
        second.close()

        result = second.verify_chain()
        assert result["ok"] is True
        events = second.read_day(datetime.now(IST).strftime("%Y-%m-%d"))
        assert [e["event_type"] for e in events] == ["ONE", "TWO", "THREE"]
        assert [e["seq"] for e in events] == [0, 1, 2]

    def test_verify_chain_skips_legacy_prefix(self, tmp_path):
        from flinttrade_data.audit_logger import GENESIS_HASH, AuditLogger

        # A pre-chain (legacy) record with no hash, then chained records appended.
        day = datetime.now(IST).strftime("%Y-%m-%d")
        legacy = tmp_path / f"audit_{day}.jsonl"
        legacy.write_text('{"event_type": "LEGACY", "ts": "2020-01-01T00:00:00"}\n')

        audit = AuditLogger(str(tmp_path))
        audit.log_event("NEW_ONE")
        audit.log_event("NEW_TWO")
        audit.close()

        events = audit.read_day(day)
        chained = [e for e in events if "hash" in e]
        assert chained[0]["prev_hash"] == GENESIS_HASH  # fresh chain after legacy
        result = audit.verify_chain()
        assert result["ok"] is True
        assert result["checked"] == 2  # only the chained records are verified


# ======================================================================
# TradeLogger — P&L calculation + daily summaries
# ======================================================================


class TestTradeLogger:
    """Test trade logging, P&L calculation, and daily summaries."""

    # Fixed test date — avoids midnight race conditions and UTC/IST divergence on CI.
    _TEST_DATE = "2026-03-16"
    _TEST_TS = datetime(2026, 3, 16, 10, 30, 0, tzinfo=IST)

    def _make_storage_and_logger(self):
        from flinttrade_data.storage import StorageManager
        from flinttrade_journal.trade_logger import TradeLogger

        storage = StorageManager(":memory:")
        storage.initialise()
        return storage, TradeLogger(storage)

    def test_calculate_pnl_buy(self):
        from flinttrade_journal.trade_logger import TradeLogger

        pnl = TradeLogger.calculate_pnl("BUY", 10, entry_price=2500.0, exit_price=2520.0)
        assert pnl == 200.0

    def test_calculate_pnl_sell_short(self):
        from flinttrade_journal.trade_logger import TradeLogger

        pnl = TradeLogger.calculate_pnl("SELL", 10, entry_price=2520.0, exit_price=2500.0)
        assert pnl == 200.0

    def test_calculate_pnl_loss(self):
        from flinttrade_journal.trade_logger import TradeLogger

        pnl = TradeLogger.calculate_pnl("BUY", 10, entry_price=2500.0, exit_price=2480.0)
        assert pnl == -200.0

    def test_log_trade_stores_in_duckdb(self):
        """log_trade() stores the trade; use a frozen clock so CI timezone never drifts."""
        from unittest.mock import patch

        storage, tl = self._make_storage_and_logger()
        with patch("flinttrade_journal.trade_logger.datetime") as mock_dt:
            mock_dt.now.return_value = self._TEST_TS
            tl.log_trade(
                orderid="ORD001",
                symbol="RELIANCE",
                exchange="NSE",
                action="BUY",
                quantity=10,
                price=2500.0,
                strategy="Flint",
            )
        trades = storage.get_trades_by_date(self._TEST_DATE)
        assert len(trades) == 1
        assert trades[0]["symbol"] == "RELIANCE"
        storage.close()

    def test_log_trade_with_pnl(self):
        """P&L is auto-calculated from entry/exit; frozen clock keeps date consistent."""
        from unittest.mock import patch

        storage, tl = self._make_storage_and_logger()
        with patch("flinttrade_journal.trade_logger.datetime") as mock_dt:
            mock_dt.now.return_value = self._TEST_TS
            tl.log_trade(
                orderid="ORD002",
                symbol="TCS",
                exchange="NSE",
                action="BUY",
                quantity=5,
                price=3520.0,
                strategy="Flint",
                entry_price=3500.0,
                exit_price=3520.0,
            )
        trades = storage.get_trades_by_strategy("Flint", self._TEST_DATE, self._TEST_DATE)
        assert len(trades) == 1
        assert trades[0]["pnl"] == 100.0  # (3520-3500)*5
        storage.close()

    def test_log_trade_with_slippage(self):
        """Slippage = |actual - expected|; frozen clock avoids midnight date drift."""
        from unittest.mock import patch

        storage, tl = self._make_storage_and_logger()
        with patch("flinttrade_journal.trade_logger.datetime") as mock_dt:
            mock_dt.now.return_value = self._TEST_TS
            tl.log_trade(
                orderid="ORD003",
                symbol="INFY",
                exchange="NSE",
                action="BUY",
                quantity=10,
                price=1502.0,
                strategy="Flint",
                expected_price=1500.0,
            )
        trades = storage.get_trades_by_strategy("Flint", self._TEST_DATE, self._TEST_DATE)
        assert trades[0]["slippage"] == 2.0
        storage.close()

    def test_compute_daily_summary(self):
        storage, tl = self._make_storage_and_logger()
        ts = self._TEST_TS

        # Simulate 3 trades: 2 winning, 1 losing
        storage.insert_trade(
            ts=ts,
            orderid="1",
            symbol="A",
            exchange="NSE",
            action="BUY",
            quantity=10,
            price=100.0,
            strategy="Flint",
            pnl=500.0,
            fees=10.0,
        )
        storage.insert_trade(
            ts=ts,
            orderid="2",
            symbol="B",
            exchange="NSE",
            action="SELL",
            quantity=5,
            price=200.0,
            strategy="Flint",
            pnl=300.0,
            fees=8.0,
        )
        storage.insert_trade(
            ts=ts,
            orderid="3",
            symbol="C",
            exchange="NSE",
            action="BUY",
            quantity=20,
            price=50.0,
            strategy="Flint",
            pnl=-200.0,
            fees=5.0,
        )

        summary = tl.compute_daily_summary(self._TEST_DATE, "Flint")
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
        ts = self._TEST_TS

        storage.insert_trade(
            ts=ts,
            orderid="1",
            symbol="A",
            exchange="NSE",
            action="BUY",
            quantity=1,
            price=100.0,
            strategy="Flint",
            pnl=50.0,
        )
        tl.compute_daily_summary(self._TEST_DATE, "Flint")

        summaries = storage.get_daily_summaries(self._TEST_DATE, self._TEST_DATE, "Flint")
        assert len(summaries) == 1
        assert summaries[0]["total_trades"] == 1
        storage.close()

    def test_daily_summary_max_drawdown(self):
        storage, tl = self._make_storage_and_logger()
        ts = self._TEST_TS

        # Sequence: +500, -300, -400 → peak 500, trough -200 → dd=700
        storage.insert_trade(
            ts=ts,
            orderid="1",
            symbol="A",
            exchange="NSE",
            action="BUY",
            quantity=1,
            price=100.0,
            strategy="Test",
            pnl=500.0,
        )
        storage.insert_trade(
            ts=ts,
            orderid="2",
            symbol="B",
            exchange="NSE",
            action="BUY",
            quantity=1,
            price=100.0,
            strategy="Test",
            pnl=-300.0,
        )
        storage.insert_trade(
            ts=ts,
            orderid="3",
            symbol="C",
            exchange="NSE",
            action="BUY",
            quantity=1,
            price=100.0,
            strategy="Test",
            pnl=-400.0,
        )

        summary = tl.compute_daily_summary(self._TEST_DATE, "Test")
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
        ts = self._TEST_TS

        storage.insert_trade(
            ts=ts,
            orderid="ORD001",
            symbol="RELIANCE",
            exchange="NSE",
            action="BUY",
            quantity=10,
            price=2500.0,
            strategy="Flint",
        )
        csv_str = tl.export_csv(self._TEST_DATE, self._TEST_DATE, "Flint")
        assert "RELIANCE" in csv_str
        assert "ORD001" in csv_str
        storage.close()

    def test_trade_summary_dataclass(self):
        from flinttrade_journal.trade_logger import TradeSummary

        s = TradeSummary(
            trade_date=date(2026, 3, 16),
            strategy="Flint",
            total_trades=10,
            winning_trades=7,
            losing_trades=3,
            gross_pnl=5000.0,
            fees=100.0,
            net_pnl=4900.0,
        )
        assert s.win_rate == 70.0
        assert s.avg_pnl_per_trade == 490.0


# ======================================================================
# TickRecorder — unit tests (no live WebSocket)
# ======================================================================


class TestTickRecorder:
    """Test TickRecorder watchlist management and tick processing."""

    def _make_recorder(self):
        from flinttrade_data.storage import StorageManager
        from flinttrade_data.tick_recorder import TickRecorder

        storage = StorageManager(":memory:")
        storage.initialise()
        return storage, TickRecorder(storage=storage)

    @staticmethod
    def _allow(recorder, *identities: tuple[str, str]) -> None:
        recorder.add_symbols(
            [{"exchange": exchange, "symbol": symbol} for exchange, symbol in identities],
            mode="quote",
        )

    @pytest.mark.parametrize("flush_interval", [0, -1, float("nan"), float("inf")])
    def test_flush_interval_must_be_finite_and_positive(self, flush_interval):
        from flinttrade_data.tick_recorder import TickRecorder

        with pytest.raises(ValueError, match="flush_interval"):
            TickRecorder(storage=MagicMock(), flush_interval=flush_interval)

    def test_add_symbols(self):
        _, recorder = self._make_recorder()
        recorder.add_symbols(
            [
                {"exchange": "NSE", "symbol": "RELIANCE"},
                {"exchange": "NFO", "symbol": "NIFTY26MAR2524000CE"},
            ],
            mode="quote",
        )
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

    def test_watchlist_identities_are_canonicalised_for_add_and_remove(self):
        _, recorder = self._make_recorder()

        recorder.add_symbols([{"exchange": " nse ", "symbol": " reliance "}], mode="quote")

        assert recorder.get_watchlist()["quote"] == [{"exchange": "NSE", "symbol": "RELIANCE"}]
        recorder.remove_symbols([{"exchange": " nSe ", "symbol": " ReLiAnCe "}], mode="quote")
        assert recorder.get_watchlist()["quote"] == []

    def test_unwatched_frames_are_ignored_before_any_sink_or_buffer_mutation(self):
        from flinttrade_data.tick_recorder import TickRecorder

        storage = MagicMock()
        sink = MagicMock()
        orderflow = MagicMock()
        recorder = TickRecorder(storage=storage, ltp_sink=sink, orderflow_aggregator=orderflow)
        recorder.add_symbols([{"exchange": "NSE", "symbol": "RELIANCE"}], mode="quote")

        recorder._process_tick({"exchange": "NSE", "symbol": "TCS", "ltp": 3500.0, "volume": 100})

        assert recorder.tick_count == 0
        assert recorder.pending_tick_count == 0
        sink.assert_not_called()
        orderflow.feed_market_tick.assert_not_called()

    def test_incoming_frame_identity_is_canonicalised_before_persistence_and_sinks(self):
        from flinttrade_data.tick_recorder import TickRecorder

        sink = MagicMock()
        recorder = TickRecorder(storage=MagicMock(), ltp_sink=sink)
        recorder.add_symbols([{"exchange": "NSE", "symbol": "RELIANCE"}], mode="quote")

        recorder._process_tick(
            {"exchange": " nse ", "symbol": " reliance ", "ltp": 2500.0, "volume": 100}
        )

        assert recorder._buffer[0][1:3] == ("RELIANCE", "NSE")
        stored_timestamp = recorder._buffer[0][0]
        sink.assert_called_once_with("NSE", "RELIANCE", 2500.0, 100, stored_timestamp.timestamp())

    def test_conflicting_envelope_and_payload_identities_are_rejected(self):
        from flinttrade_data.tick_recorder import TickRecorder

        sink = MagicMock()
        orderflow = MagicMock()
        recorder = TickRecorder(storage=MagicMock(), ltp_sink=sink, orderflow_aggregator=orderflow)
        self._allow(recorder, ("NSE", "RELIANCE"), ("BSE", "TCS"))

        recorder._process_tick(
            {
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "data": {
                    "exchange": "BSE",
                    "symbol": "TCS",
                    "ltp": 3500.0,
                    "volume": 100,
                },
            }
        )

        assert recorder.tick_count == 0
        assert recorder.pending_tick_count == 0
        sink.assert_not_called()
        orderflow.feed_market_tick.assert_not_called()

    def test_frame_arriving_after_watchlist_removal_is_ignored(self):
        from flinttrade_data.tick_recorder import TickRecorder

        recorder = TickRecorder(storage=MagicMock())
        instrument = {"exchange": "NSE", "symbol": "RELIANCE"}
        recorder.add_symbols([instrument], mode="quote")
        recorder.remove_symbols([instrument], mode="quote")

        recorder._process_tick({**instrument, "ltp": 2500.0, "volume": 100})

        assert recorder.tick_count == 0
        assert recorder.pending_tick_count == 0

    def test_watchlist_removal_prunes_orderflow_identity_state(self):
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator
        from flinttrade_data.tick_recorder import TickRecorder

        orderflow = OrderFlowAggregator()
        recorder = TickRecorder(storage=MagicMock(), orderflow_aggregator=orderflow)
        instrument = {"exchange": "NSE", "symbol": "RELIANCE"}
        recorder.add_symbols([instrument], mode="quote")
        orderflow.add_tick("RELIANCE", 2500.0, 10, "BUY", exchange="NSE")

        recorder.remove_symbols([instrument], mode="quote")
        recorder.request_reconnect()

        assert ("NSE", "RELIANCE") not in orderflow._state

    def test_invalid_mode_raises(self):
        _, recorder = self._make_recorder()
        with pytest.raises(ValueError, match="Invalid mode"):
            recorder.add_symbols([{"exchange": "NSE", "symbol": "X"}], mode="invalid")

    @pytest.mark.asyncio
    async def test_authenticate_sends_configured_api_key(self):
        from flinttrade_data.tick_recorder import TickRecorder

        storage = MagicMock()
        recorder = TickRecorder(storage=storage, api_key="configured-test-key")
        ws = AsyncMock()
        ws.recv.return_value = json.dumps({"status": "authenticated"})

        await recorder._authenticate(ws)

        assert json.loads(ws.send.await_args.args[0]) == {
            "action": "authenticate",
            "api_key": "configured-test-key",
        }

    @pytest.mark.asyncio
    async def test_authenticate_times_out_without_exposing_api_key(self):
        from flinttrade_data.tick_recorder import TickRecorder

        api_key = "configured-test-key"
        storage = MagicMock()
        recorder = TickRecorder(storage=storage, api_key=api_key, auth_response_timeout=0.01)
        ws = AsyncMock()

        async def never_respond():
            await asyncio.Future()

        ws.recv.side_effect = never_respond

        with pytest.raises(RuntimeError, match="timed out"):
            await recorder._authenticate(ws)

        assert "timed out" in recorder.last_error
        assert api_key not in recorder.last_error

    @pytest.mark.asyncio
    @pytest.mark.parametrize("response", [["configured-test-key"], "configured-test-key", 42])
    async def test_authenticate_rejects_non_object_json_without_exposing_api_key(self, response):
        from flinttrade_data.tick_recorder import TickRecorder

        api_key = "configured-test-key"
        recorder = TickRecorder(storage=MagicMock(), api_key=api_key)
        ws = AsyncMock()
        ws.recv.return_value = json.dumps(response)

        with pytest.raises(RuntimeError, match="expected JSON object") as exc_info:
            await recorder._authenticate(ws)

        assert api_key not in str(exc_info.value)
        assert api_key not in recorder.last_error

    @pytest.mark.asyncio
    async def test_authenticate_rejects_invalid_utf8_binary_as_reconnectable_error(self):
        from flinttrade_data.tick_recorder import TickRecorder

        api_key = "configured-test-key"
        recorder = TickRecorder(storage=MagicMock(), api_key=api_key)
        ws = AsyncMock()
        ws.recv.return_value = b"\xffconfigured-test-key"

        with pytest.raises(RuntimeError, match="invalid UTF-8") as exc_info:
            await recorder._authenticate(ws)

        assert api_key not in str(exc_info.value)
        assert api_key not in recorder.last_error

    @pytest.mark.asyncio
    async def test_subscribe_all_uses_current_openalgo_payload(self):
        _, recorder = self._make_recorder()
        recorder.add_symbols([{"exchange": "NSE", "symbol": "RELIANCE"}], mode="quote")
        ws = AsyncMock()

        await recorder._subscribe_all(ws)

        assert json.loads(ws.send.await_args_list[-1].args[0]) == {
            "action": "subscribe",
            "symbols": [{"exchange": "NSE", "symbol": "RELIANCE"}],
            "mode": "QUOTE",
        }

    def test_nested_and_legacy_ticks_buffer_the_same_numeric_fields(self):
        _, nested_recorder = self._make_recorder()
        _, legacy_recorder = self._make_recorder()
        self._allow(nested_recorder, ("NSE", "RELIANCE"))
        self._allow(legacy_recorder, ("NSE", "RELIANCE"))
        fields = {
            "ltp": 2500.0,
            "open": 2480.0,
            "high": 2520.0,
            "low": 2470.0,
            "close": 2490.0,
            "volume": 1000,
            "bid": 2499.0,
            "ask": 2501.0,
            "oi": 1200,
            "prev_close": 2485.0,
        }
        nested_recorder._process_tick(
            {
                "type": "market_data",
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "mode": "QUOTE",
                "data": fields,
            }
        )
        legacy_recorder._process_tick({"exchange": "NSE", "symbol": "RELIANCE", **fields})

        assert nested_recorder._buffer[0][4:14] == legacy_recorder._buffer[0][4:14]

    @pytest.mark.parametrize("nested", [False, True], ids=["legacy", "nested"])
    @pytest.mark.parametrize(
        "frame_timestamp",
        [
            pytest.param(1_774_410_300, id="epoch-seconds"),
            pytest.param(1_774_410_300_000, id="epoch-milliseconds"),
            pytest.param(1_774_410_300_000_000, id="epoch-microseconds"),
            pytest.param(1_774_410_300_000_000_000, id="epoch-nanoseconds"),
            pytest.param("1774410300000", id="numeric-string-milliseconds"),
            pytest.param("2026-03-25T03:45:00Z", id="iso-utc"),
            pytest.param("2026-03-25T09:15:00+05:30", id="iso-ist"),
        ],
    )
    def test_supported_frame_timestamps_are_preserved_for_storage_and_orderflow(
        self,
        nested,
        frame_timestamp,
        monkeypatch,
    ):
        import flinttrade_data.tick_recorder as recorder_module
        from flinttrade_data.tick_recorder import TickRecorder

        expected = datetime(2026, 3, 25, 3, 45, tzinfo=timezone.utc)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return expected if tz is not None else expected.replace(tzinfo=None)

        monkeypatch.setattr(recorder_module, "datetime", FixedDateTime)
        sink = MagicMock()
        orderflow = MagicMock()
        recorder = TickRecorder(storage=MagicMock(), ltp_sink=sink, orderflow_aggregator=orderflow)
        self._allow(recorder, ("NSE", "RELIANCE"))
        payload = {
            "exchange": " nse ",
            "symbol": " reliance ",
            "ltp": 2500.0,
            "volume": 1000,
            "timestamp": frame_timestamp,
        }
        frame = {"type": "quote", "data": payload} if nested else payload

        recorder._process_tick(frame)

        assert recorder._buffer[0][0] == expected
        sink.assert_called_once_with("NSE", "RELIANCE", 2500.0, 1000, expected.timestamp())
        orderflow.feed_market_tick.assert_called_once()
        assert orderflow.feed_market_tick.call_args.kwargs["timestamp"] == expected.timestamp()

    @pytest.mark.parametrize("skew_seconds", [1.0, 5.0], ids=["one-second", "five-second-boundary"])
    def test_small_positive_source_clock_skew_is_accepted(self, skew_seconds, monkeypatch):
        import flinttrade_data.tick_recorder as recorder_module
        from flinttrade_data.tick_recorder import TickRecorder

        received_at = datetime(2026, 3, 25, 3, 45, tzinfo=timezone.utc)
        source_time = received_at + timedelta(seconds=skew_seconds)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return received_at if tz is not None else received_at.replace(tzinfo=None)

        monkeypatch.setattr(recorder_module, "datetime", FixedDateTime)
        sink = MagicMock()
        recorder = TickRecorder(storage=MagicMock(), ltp_sink=sink)
        self._allow(recorder, ("NSE", "RELIANCE"))

        recorder._process_tick(
            {
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "ltp": 2500.0,
                "volume": 1000,
                "timestamp": source_time.isoformat(),
            }
        )

        assert recorder._buffer[0][0] == source_time
        sink.assert_called_once_with("NSE", "RELIANCE", 2500.0, 1000, source_time.timestamp())
        snapshot = recorder.status_snapshot()
        assert snapshot["future_source_timestamp_rejections"] == 0
        assert snapshot["stale_source_timestamp_rejections"] == 0

    @pytest.mark.parametrize(
        "frame_timestamp",
        [
            pytest.param("not-a-timestamp", id="invalid"),
            pytest.param("2026-03-23T03:44:59Z", id="stale"),
            pytest.param("2026-03-25T03:39:59Z", id="older-than-live-window"),
            pytest.param("2026-03-25T03:45:06Z", id="future-beyond-tolerance"),
        ],
    )
    def test_explicit_untrusted_timestamp_is_rejected_without_receipt_rewrite(
        self,
        frame_timestamp,
        monkeypatch,
    ):
        import flinttrade_data.tick_recorder as recorder_module
        from flinttrade_data.tick_recorder import TickRecorder

        received_at = datetime(2026, 3, 25, 3, 45, tzinfo=timezone.utc)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return received_at if tz is not None else received_at.replace(tzinfo=None)

        monkeypatch.setattr(recorder_module, "datetime", FixedDateTime)
        sink = MagicMock()
        orderflow = MagicMock()
        recorder = TickRecorder(storage=MagicMock(), ltp_sink=sink, orderflow_aggregator=orderflow)
        self._allow(recorder, ("NSE", "RELIANCE"))

        recorder._process_tick(
            {
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "ltp": 2500.0,
                "volume": 1000,
                "timestamp": frame_timestamp,
            }
        )

        assert recorder.tick_count == 0
        assert recorder.pending_tick_count == 0
        sink.assert_not_called()
        orderflow.feed_market_tick.assert_not_called()

    @pytest.mark.parametrize(
        "frame_timestamp",
        [
            "2026-03-23T03:44:59Z",
            "2026-03-25T03:45:05.001Z",
            "2026-03-25T03:50:00Z",
            "2026-03-25T03:50:01Z",
        ],
        ids=["too-old", "future-beyond-tolerance", "five-minutes-future", "too-far-future"],
    )
    def test_implausibly_skewed_frame_timestamp_is_rejected(
        self,
        frame_timestamp,
        monkeypatch,
    ):
        import flinttrade_data.tick_recorder as recorder_module
        from flinttrade_data.tick_recorder import TickRecorder

        received_at = datetime(2026, 3, 25, 3, 45, tzinfo=timezone.utc)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return received_at if tz is not None else received_at.replace(tzinfo=None)

        monkeypatch.setattr(recorder_module, "datetime", FixedDateTime)
        orderflow = MagicMock()
        recorder = TickRecorder(storage=MagicMock(), orderflow_aggregator=orderflow)
        self._allow(recorder, ("NSE", "RELIANCE"))

        recorder._process_tick(
            {
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "ltp": 2500.0,
                "volume": 1000,
                "timestamp": frame_timestamp,
            }
        )

        assert recorder.pending_tick_count == 0
        orderflow.feed_market_tick.assert_not_called()

    def test_stale_and_future_timestamp_rejections_are_counted_and_diagnosed(self, monkeypatch):
        import flinttrade_data.tick_recorder as recorder_module
        from flinttrade_data.tick_recorder import TickRecorder

        received_at = datetime(2026, 3, 25, 3, 45, tzinfo=timezone.utc)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return received_at if tz is not None else received_at.replace(tzinfo=None)

        monkeypatch.setattr(recorder_module, "datetime", FixedDateTime)
        recorder = TickRecorder(storage=MagicMock())
        self._allow(recorder, ("NSE", "RELIANCE"))

        for source_time in (
            received_at - timedelta(minutes=5, milliseconds=1),
            received_at + timedelta(seconds=5, milliseconds=1),
        ):
            recorder._process_tick(
                {
                    "exchange": "NSE",
                    "symbol": "RELIANCE",
                    "ltp": 2500.0,
                    "timestamp": source_time.isoformat(),
                }
            )

        snapshot = recorder.status_snapshot()
        assert snapshot["stale_source_timestamp_rejections"] == 1
        assert snapshot["future_source_timestamp_rejections"] == 1
        assert "future source timestamp" in snapshot["source_timestamp_error"].lower()
        assert snapshot["source_timestamp_error"] == snapshot["last_error"]
        assert recorder.pending_tick_count == 0

    def test_valid_tick_only_clears_timestamp_diagnostic_for_its_own_instrument(self, monkeypatch):
        import flinttrade_data.tick_recorder as recorder_module
        from flinttrade_data.tick_recorder import TickRecorder

        received_at = datetime(2026, 3, 25, 3, 45, tzinfo=timezone.utc)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return received_at if tz is not None else received_at.replace(tzinfo=None)

        monkeypatch.setattr(recorder_module, "datetime", FixedDateTime)
        recorder = TickRecorder(storage=MagicMock())
        self._allow(recorder, ("NSE", "RELIANCE"), ("NSE", "TCS"))

        recorder._process_tick(
            {
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "ltp": 2500.0,
                "timestamp": (received_at - timedelta(minutes=6)).isoformat(),
            }
        )
        recorder._process_tick({"exchange": "NSE", "symbol": "TCS", "ltp": 3500.0})

        assert "stale source timestamp" in recorder.status_snapshot()["source_timestamp_error"].lower()

        recorder._process_tick({"exchange": "NSE", "symbol": "RELIANCE", "ltp": 2501.0})

        assert recorder.status_snapshot()["source_timestamp_error"] == ""

    def test_removing_instrument_clears_its_active_timestamp_diagnostic(self, monkeypatch):
        import flinttrade_data.tick_recorder as recorder_module
        from flinttrade_data.tick_recorder import TickRecorder

        received_at = datetime(2026, 3, 25, 3, 45, tzinfo=timezone.utc)

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return received_at if tz is not None else received_at.replace(tzinfo=None)

        monkeypatch.setattr(recorder_module, "datetime", FixedDateTime)
        recorder = TickRecorder(storage=MagicMock())
        instrument = {"exchange": "NSE", "symbol": "RELIANCE"}
        recorder.add_symbols([instrument], mode="quote")
        recorder._process_tick(
            {
                **instrument,
                "ltp": 2500.0,
                "timestamp": (received_at - timedelta(minutes=6)).isoformat(),
            }
        )
        assert recorder.status_snapshot()["source_timestamp_error"]

        recorder.remove_symbols([instrument], mode="quote")

        assert recorder.status_snapshot()["source_timestamp_error"] == ""

    @pytest.mark.parametrize("stale_volume", [-1, 1050])
    def test_rejected_explicit_timestamp_cannot_mutate_orderflow_baseline(self, stale_volume):
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator
        from flinttrade_data.tick_recorder import TickRecorder

        now = datetime.now(timezone.utc)
        base = now.timestamp()
        orderflow = OrderFlowAggregator()
        orderflow.feed_market_tick("RELIANCE", 2500.0, 1000, exchange="NSE", timestamp=base - 2)
        orderflow.feed_market_tick("RELIANCE", 2501.0, 1100, exchange="NSE", timestamp=base - 1)
        recorder = TickRecorder(storage=MagicMock(), orderflow_aggregator=orderflow)
        self._allow(recorder, ("NSE", "RELIANCE"))

        recorder._process_tick(
            {
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "ltp": 2499.0,
                "volume": stale_volume,
                "timestamp": (now - timedelta(days=1, microseconds=1)).isoformat(),
            }
        )
        orderflow.feed_market_tick("RELIANCE", 2502.0, 1125, exchange="NSE", timestamp=base + 1)

        buckets = orderflow.get_footprint("RELIANCE", exchange="NSE")
        assert sum(bucket.buy_volume + bucket.sell_volume for bucket in buckets) == 125

    @pytest.mark.parametrize("stale_volume", [-1, 1050])
    def test_rejected_nested_timestamp_cannot_regain_trust_from_envelope(self, stale_volume):
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator
        from flinttrade_data.tick_recorder import TickRecorder

        now = datetime.now(timezone.utc)
        base = now.timestamp()
        orderflow = OrderFlowAggregator()
        orderflow.feed_market_tick("RELIANCE", 2500.0, 1000, exchange="NSE", timestamp=base - 2)
        orderflow.feed_market_tick("RELIANCE", 2501.0, 1100, exchange="NSE", timestamp=base - 1)
        recorder = TickRecorder(storage=MagicMock(), orderflow_aggregator=orderflow)
        self._allow(recorder, ("NSE", "RELIANCE"))

        recorder._process_tick(
            {
                "timestamp": now.isoformat(),
                "data": {
                    "exchange": "NSE",
                    "symbol": "RELIANCE",
                    "ltp": 2499.0,
                    "volume": stale_volume,
                    "timestamp": (now - timedelta(days=1, microseconds=1)).isoformat(),
                },
            }
        )
        orderflow.feed_market_tick("RELIANCE", 2502.0, 1125, exchange="NSE", timestamp=base + 1)

        buckets = orderflow.get_footprint("RELIANCE", exchange="NSE")
        assert sum(bucket.buy_volume + bucket.sell_volume for bucket in buckets) == 125

    @pytest.mark.parametrize(
        "invalid_timestamp",
        [
            None,
            0,
            -1,
            10**30,
            "not-a-timestamp",
            "1999-12-31T23:59:59Z",
            "2100-01-01T00:00:01Z",
            "x" * 65,
        ],
    )
    def test_invalid_or_out_of_bounds_explicit_timestamp_is_rejected(
        self,
        invalid_timestamp,
    ):
        from flinttrade_data.tick_recorder import TickRecorder

        orderflow = MagicMock()
        recorder = TickRecorder(storage=MagicMock(), orderflow_aggregator=orderflow)
        self._allow(recorder, ("NSE", "RELIANCE"))

        recorder._process_tick(
            {
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "ltp": 2500.0,
                "volume": 1000,
                "timestamp": invalid_timestamp,
            }
        )

        assert recorder.pending_tick_count == 0
        orderflow.feed_market_tick.assert_not_called()

    def test_missing_frame_timestamp_uses_one_receipt_time(self):
        from flinttrade_data.tick_recorder import TickRecorder

        orderflow = MagicMock()
        recorder = TickRecorder(storage=MagicMock(), orderflow_aggregator=orderflow)
        self._allow(recorder, ("NSE", "RELIANCE"))
        before = datetime.now(timezone.utc)

        recorder._process_tick(
            {"exchange": "NSE", "symbol": "RELIANCE", "ltp": 2500.0, "volume": 1000}
        )

        after = datetime.now(timezone.utc)
        stored_timestamp = recorder._buffer[0][0]
        assert before <= stored_timestamp <= after
        assert orderflow.feed_market_tick.call_args.kwargs["timestamp"] == stored_timestamp.timestamp()

    def test_numeric_mode_three_persists_as_depth(self):
        _, recorder = self._make_recorder()
        self._allow(recorder, ("NSE", "RELIANCE"))

        recorder._process_tick(
            {
                "type": "market_data",
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "mode": 3,
                "data": {"ltp": 2500.0},
            }
        )

        assert recorder._buffer[0][3] == "depth"

    def test_nested_depth_payload_persists_as_depth(self):
        _, recorder = self._make_recorder()
        self._allow(recorder, ("NSE", "RELIANCE"))

        recorder._process_tick(
            {
                "type": "market_data",
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "data": {
                    "ltp": 2500.0,
                    "volume": 1000,
                    "depth": {"buy": [{"price": 2499.0}], "sell": [{"price": 2501.0}]},
                },
            }
        )

        assert recorder._buffer[0][3] == "depth"
        assert json.loads(recorder._buffer[0][14])["buy"][0]["price"] == 2499.0

    @pytest.mark.parametrize(
        ("aliases", "expected_bid", "expected_ask"),
        [
            pytest.param(
                {"bid_price": 2499.0, "ask_price": 2501.0},
                2499.0,
                2501.0,
                id="quote-price-aliases",
            ),
            pytest.param(
                {
                    "depth": {
                        "buy": [{"price": 2498.0, "quantity": 10}],
                        "sell": [{"price": 2502.0, "quantity": 20}],
                    }
                },
                2498.0,
                2502.0,
                id="legacy-depth-buy-sell",
            ),
            pytest.param(
                {
                    "bids": [{"price": 2497.0, "quantity": 10}],
                    "asks": [{"price": 2503.0, "quantity": 20}],
                },
                2497.0,
                2503.0,
                id="depth-bids-asks",
            ),
        ],
    )
    def test_bbo_aliases_feed_storage_and_orderflow(self, aliases, expected_bid, expected_ask):
        from flinttrade_data.tick_recorder import TickRecorder

        orderflow = MagicMock()
        recorder = TickRecorder(storage=MagicMock(), orderflow_aggregator=orderflow)
        self._allow(recorder, ("NSE", "RELIANCE"))

        recorder._process_tick(
            {
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "ltp": 2500.0,
                "volume": 1000,
                **aliases,
            }
        )

        assert recorder._buffer[0][10:12] == (expected_bid, expected_ask)
        assert orderflow.feed_market_tick.call_args.kwargs["bid"] == expected_bid
        assert orderflow.feed_market_tick.call_args.kwargs["ask"] == expected_ask

    def test_ltp_sink_receives_finite_tick_after_buffering(self):
        from flinttrade_data.storage import StorageManager
        from flinttrade_data.tick_recorder import TickRecorder

        sink = MagicMock()
        storage = StorageManager(":memory:")
        storage.initialise()
        recorder = TickRecorder(storage=storage, ltp_sink=sink)
        self._allow(recorder, ("NSE", "RELIANCE"))

        recorder._process_tick({"exchange": "NSE", "symbol": "RELIANCE", "ltp": 2500.0, "volume": 1000})

        assert len(recorder._buffer) == 1
        stored_timestamp = recorder._buffer[0][0]
        sink.assert_called_once_with("NSE", "RELIANCE", 2500.0, 1000, stored_timestamp.timestamp())

    def test_legacy_four_argument_ltp_sink_receives_tick(self):
        from flinttrade_data.tick_recorder import TickRecorder

        calls = []

        def legacy_sink(exchange, symbol, ltp, volume):
            calls.append((exchange, symbol, ltp, volume))

        recorder = TickRecorder(storage=MagicMock(), ltp_sink=legacy_sink)
        self._allow(recorder, ("NSE", "RELIANCE"))

        recorder._process_tick({"exchange": "NSE", "symbol": "RELIANCE", "ltp": 2500.0, "volume": 1000})

        assert calls == [("NSE", "RELIANCE", 2500.0, 1000)]

    def test_incompatible_ltp_sink_signature_is_rejected_at_construction(self):
        from flinttrade_data.tick_recorder import TickRecorder

        def incompatible_sink(exchange, symbol):
            return (exchange, symbol)

        with pytest.raises(TypeError, match="four or five positional arguments"):
            TickRecorder(storage=MagicMock(), ltp_sink=incompatible_sink)

    @pytest.mark.parametrize(
        "ltp",
        [None, "not-a-number", float("nan"), float("inf"), 10**400, 0.0, -1.0],
    )
    def test_invalid_or_nonfinite_ltp_does_not_reach_sink(self, ltp):
        from flinttrade_data.storage import StorageManager
        from flinttrade_data.tick_recorder import TickRecorder

        sink = MagicMock()
        storage = StorageManager(":memory:")
        storage.initialise()
        recorder = TickRecorder(storage=storage, ltp_sink=sink)
        self._allow(recorder, ("NSE", "RELIANCE"))

        recorder._process_tick({"exchange": "NSE", "symbol": "RELIANCE", "ltp": ltp, "volume": 1000})

        sink.assert_not_called()

    @pytest.mark.parametrize(
        ("ltp", "expected_ltp"),
        [(True, None), (False, None), ("2500.5", 2500.5)],
        ids=["json-true", "json-false", "numeric-string"],
    )
    def test_storage_and_live_consumers_share_one_normalised_ltp(self, ltp, expected_ltp):
        from flinttrade_data.tick_recorder import TickRecorder

        sink = MagicMock()
        orderflow = MagicMock()
        recorder = TickRecorder(
            storage=MagicMock(),
            ltp_sink=sink,
            orderflow_aggregator=orderflow,
        )
        self._allow(recorder, ("NSE", "RELIANCE"))

        recorder._process_tick(
            {
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "ltp": ltp,
                "volume": 1000,
            }
        )

        assert recorder._buffer[0][4] == expected_ltp
        if expected_ltp is None:
            sink.assert_not_called()
            orderflow.feed_market_tick.assert_not_called()
        else:
            assert sink.call_args.args[2] == expected_ltp
            assert orderflow.feed_market_tick.call_args.args[1] == expected_ltp

    @pytest.mark.parametrize("ltp", [0.0, -1.0, float("nan"), float("inf")])
    def test_invalid_ltp_cannot_advance_orderflow_volume_baseline(self, ltp):
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator
        from flinttrade_data.tick_recorder import TickRecorder

        aggregator = OrderFlowAggregator()
        recorder = TickRecorder(storage=MagicMock(), orderflow_aggregator=aggregator)
        recorder.add_symbols([{"exchange": "NSE", "symbol": "RELIANCE"}], mode="quote")

        recorder._process_tick({"exchange": "NSE", "symbol": "RELIANCE", "ltp": 2500.0, "volume": 1000})
        recorder._process_tick({"exchange": "NSE", "symbol": "RELIANCE", "ltp": ltp, "volume": 5000})
        recorder._process_tick({"exchange": "NSE", "symbol": "RELIANCE", "ltp": 2501.0, "volume": 1100})

        buckets = aggregator.get_footprint("RELIANCE", exchange="NSE")
        assert sum(bucket.total_volume for bucket in buckets) == 100

    def test_malformed_numeric_fields_cannot_poison_the_persistence_batch(self):
        from flinttrade_data.storage import StorageManager
        from flinttrade_data.tick_recorder import TickRecorder

        storage = StorageManager(":memory:")
        storage.initialise()
        recorder = TickRecorder(storage=storage)
        self._allow(recorder, ("NSE", "RELIANCE"), ("NSE", "TCS"))
        recorder._process_tick(
            {
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "ltp": 10**400,
                "open": "not-a-price",
                "high": float("inf"),
                "volume": 10**400,
                "oi": "not-an-integer",
            }
        )
        recorder._process_tick({"exchange": "NSE", "symbol": "TCS", "ltp": 3500.0, "volume": 12})

        malformed = recorder._buffer[0]
        assert malformed[4] is None
        assert malformed[5] is None
        assert malformed[6] is None
        assert malformed[9] is None
        assert malformed[12] is None
        assert recorder._flush() is True
        assert recorder.persisted_tick_count == 2
        assert recorder.pending_tick_count == 0

    def test_negative_cumulative_volume_is_normalised_without_poisoning_orderflow_baseline(self):
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator
        from flinttrade_data.tick_recorder import TickRecorder

        aggregator = OrderFlowAggregator()
        recorder = TickRecorder(storage=MagicMock(), orderflow_aggregator=aggregator)
        recorder.add_symbols([{"exchange": "NSE", "symbol": "RELIANCE"}], mode="quote")

        recorder._process_tick({"exchange": "NSE", "symbol": "RELIANCE", "ltp": 2499.0, "volume": -100})
        recorder._process_tick({"exchange": "NSE", "symbol": "RELIANCE", "ltp": 2500.0, "volume": 1000})
        recorder._process_tick({"exchange": "NSE", "symbol": "RELIANCE", "ltp": 2501.0, "volume": 1100})

        assert recorder._buffer[0][9] is None
        buckets = aggregator.get_footprint("RELIANCE", exchange="NSE")
        assert sum(bucket.total_volume for bucket in buckets) == 100

    @pytest.mark.parametrize("volume", [None, "not-a-volume", -100])
    def test_ltp_sink_clamps_missing_invalid_or_negative_volume_to_zero(self, volume):
        from flinttrade_data.storage import StorageManager
        from flinttrade_data.tick_recorder import TickRecorder

        sink = MagicMock()
        storage = StorageManager(":memory:")
        storage.initialise()
        recorder = TickRecorder(storage=storage, ltp_sink=sink)
        self._allow(recorder, ("NSE", "RELIANCE"))

        recorder._process_tick({"exchange": "NSE", "symbol": "RELIANCE", "ltp": 2500.0, "volume": volume})

        stored_timestamp = recorder._buffer[0][0]
        sink.assert_called_once_with("NSE", "RELIANCE", 2500.0, 0, stored_timestamp.timestamp())

    @pytest.mark.parametrize("volume", [True, False], ids=["true", "false"])
    def test_boolean_volume_stays_invalid_for_storage_and_live_consumers(self, volume):
        from flinttrade_data.tick_recorder import TickRecorder

        sink = MagicMock()
        orderflow = MagicMock()
        recorder = TickRecorder(
            storage=MagicMock(),
            ltp_sink=sink,
            orderflow_aggregator=orderflow,
        )
        self._allow(recorder, ("NSE", "RELIANCE"))

        recorder._process_tick(
            {"exchange": "NSE", "symbol": "RELIANCE", "ltp": 2500.0, "volume": volume}
        )

        stored_timestamp = recorder._buffer[0][0]
        assert recorder._buffer[0][9] is None
        sink.assert_called_once_with("NSE", "RELIANCE", 2500.0, 0, stored_timestamp.timestamp())
        orderflow.feed_market_tick.assert_not_called()

    def test_throwing_ltp_sink_does_not_stop_buffering(self):
        from flinttrade_data.storage import StorageManager
        from flinttrade_data.tick_recorder import TickRecorder

        def failing_sink(*_args):
            raise RuntimeError("sink unavailable")

        storage = StorageManager(":memory:")
        storage.initialise()
        recorder = TickRecorder(storage=storage, ltp_sink=failing_sink)
        self._allow(recorder, ("NSE", "RELIANCE"))

        recorder._process_tick({"exchange": "NSE", "symbol": "RELIANCE", "ltp": 2500.0, "volume": 1000})

        assert recorder.tick_count == 1
        assert len(recorder._buffer) == 1

    def test_ltp_sink_exception_log_redacts_api_key(self, caplog):
        from flinttrade_data.tick_recorder import TickRecorder

        api_key = "configured-test-key"

        def failing_sink(*_args):
            raise RuntimeError(f"sink failed for {api_key}")

        caplog.set_level("DEBUG", logger="flinttrade.data.tick_recorder")
        recorder = TickRecorder(storage=MagicMock(), api_key=api_key, ltp_sink=failing_sink)
        self._allow(recorder, ("NSE", "RELIANCE"))

        recorder._process_tick({"exchange": "NSE", "symbol": "RELIANCE", "ltp": 2500.0})

        assert api_key not in caplog.text
        assert "[redacted]" in caplog.text

    @pytest.mark.asyncio
    async def test_non_json_frame_log_redacts_api_key(self, caplog):
        from flinttrade_data.tick_recorder import TickRecorder

        api_key = "configured-test-key"

        async def frames():
            yield f"not-json {api_key}"

        caplog.set_level("DEBUG", logger="flinttrade.data.tick_recorder")
        recorder = TickRecorder(storage=MagicMock(), api_key=api_key)
        self._allow(recorder, ("NSE", "RELIANCE"))
        recorder._running = True

        await recorder._consume(frames())

        assert api_key not in caplog.text
        assert "[redacted]" in caplog.text

    @pytest.mark.asyncio
    async def test_consume_ignores_non_object_json_and_continues(self):
        from flinttrade_data.tick_recorder import TickRecorder

        api_key = "configured-test-key"

        async def frames():
            yield json.dumps([api_key])
            yield json.dumps({"exchange": "NSE", "symbol": "RELIANCE", "ltp": 2500.0})

        recorder = TickRecorder(storage=MagicMock(), api_key=api_key)
        self._allow(recorder, ("NSE", "RELIANCE"))
        recorder._running = True

        await recorder._consume(frames())

        assert recorder.tick_count == 1
        assert "expected JSON object" in recorder.last_error
        assert api_key not in recorder.last_error

    @pytest.mark.asyncio
    async def test_consume_ignores_invalid_utf8_binary_and_continues(self):
        from flinttrade_data.tick_recorder import TickRecorder

        api_key = "configured-test-key"

        async def frames():
            yield b"\xffconfigured-test-key"
            yield json.dumps({"exchange": "NSE", "symbol": "RELIANCE", "ltp": 2500.0})

        recorder = TickRecorder(storage=MagicMock(), api_key=api_key)
        self._allow(recorder, ("NSE", "RELIANCE"))
        recorder._running = True

        await recorder._consume(frames())

        assert recorder.tick_count == 1
        assert "invalid UTF-8" in recorder.last_error
        assert api_key not in recorder.last_error

    def test_control_error_populates_last_error(self):
        _, recorder = self._make_recorder()

        recorder._process_tick({"type": "error", "message": "authentication failed"})

        assert recorder.last_error == "authentication failed"

    @pytest.mark.parametrize("error", [EOFError("closed"), OSError("offline"), TimeoutError("timed out")])
    def test_connection_error_classifier_retries_network_failures(self, error):
        from flinttrade_data.tick_recorder import _is_transient_connection_error

        assert _is_transient_connection_error(error) is True

    def test_connection_error_classifier_retries_connection_closed_without_newer_exception_imports(self, monkeypatch):
        from flinttrade_data import tick_recorder as module

        class ConnectionClosed(Exception):
            pass

        monkeypatch.setattr(module.websockets.exceptions, "ConnectionClosed", ConnectionClosed)
        monkeypatch.delattr(module.websockets.exceptions, "InvalidProxy", raising=False)

        assert module._is_transient_connection_error(ConnectionClosed("stream ended")) is True
        assert module._is_transient_connection_error(ValueError("bad configuration")) is False

    def test_connection_error_classifier_retries_invalid_message_wrapping_eof(self, monkeypatch):
        from flinttrade_data import tick_recorder as module

        class InvalidMessage(Exception):
            pass

        monkeypatch.setattr(module.websockets.exceptions, "InvalidMessage", InvalidMessage)
        try:
            raise InvalidMessage("connection closed during handshake") from EOFError("unexpected EOF")
        except InvalidMessage as error:
            assert module._is_transient_connection_error(error) is True

    @pytest.mark.parametrize(
        ("status_code", "retryable"),
        [(500, True), (502, True), (503, True), (504, True), (501, False), (429, False), (401, False)],
    )
    def test_connection_error_classifier_only_retries_official_server_statuses(
        self, monkeypatch, status_code, retryable
    ):
        from flinttrade_data import tick_recorder as module

        class Response:
            def __init__(self, code: int) -> None:
                self.status_code = code

        class InvalidStatus(Exception):
            def __init__(self, code: int) -> None:
                self.response = Response(code)

        monkeypatch.setattr(module.websockets.exceptions, "InvalidStatus", InvalidStatus)

        assert module._is_transient_connection_error(InvalidStatus(status_code)) is retryable

    @pytest.mark.parametrize(("status_code", "retryable"), [(503, True), (400, False)])
    def test_connection_error_classifier_supports_legacy_status_code_shape(
        self, monkeypatch, status_code, retryable
    ):
        from flinttrade_data import tick_recorder as module

        class InvalidStatusCode(Exception):
            def __init__(self, code: int) -> None:
                self.status_code = code

        monkeypatch.setitem(vars(module.websockets.exceptions), "InvalidStatusCode", InvalidStatusCode)

        assert module._is_transient_connection_error(InvalidStatusCode(status_code)) is retryable

    @pytest.mark.parametrize(
        "exception_name",
        ["InvalidURI", "InvalidProxy", "SecurityError", "InvalidHandshake", "ConcurrencyError", "InvalidState"],
    )
    def test_connection_error_classifier_rejects_configuration_and_programming_errors(
        self, monkeypatch, exception_name
    ):
        from flinttrade_data import tick_recorder as module

        class FatalConnectionError(Exception):
            pass

        monkeypatch.setattr(
            module.websockets.exceptions,
            exception_name,
            FatalConnectionError,
            raising=False,
        )

        assert module._is_transient_connection_error(FatalConnectionError("fatal")) is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("exception_type", [EOFError, OSError, TimeoutError])
    async def test_transient_websocket_setup_failure_reconnects_with_sanitised_error(
        self, monkeypatch, exception_type
    ):
        from flinttrade_data import tick_recorder as module
        from flinttrade_data.tick_recorder import TickRecorder

        api_key = "configured-test-key"
        recorder = TickRecorder(storage=MagicMock(), api_key=api_key, reconnect_delay=0.25)
        failure = exception_type(f"setup failed for {api_key}")

        def failed_connect(_url):
            raise failure

        async def stop_during_backoff(_delay):
            recorder.stop()

        sleep = AsyncMock(side_effect=stop_during_backoff)
        monkeypatch.setattr(module.websockets, "connect", failed_connect)
        monkeypatch.setattr(module.asyncio, "sleep", sleep)

        await recorder.run()

        sleep.assert_awaited_once_with(0.25)
        assert "setup failed" in recorder.last_error
        assert api_key not in recorder.last_error
        assert recorder.is_running is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("exception_name", ["InvalidURI", "InvalidProxy", "SecurityError", "InvalidHandshake"])
    async def test_websocket_configuration_failure_escapes_without_reconnecting(
        self, monkeypatch, exception_name
    ):
        from flinttrade_data import tick_recorder as module
        from flinttrade_data.tick_recorder import TickRecorder

        api_key = "configured-test-key"

        class FatalConnectionError(Exception):
            pass

        monkeypatch.setattr(
            module.websockets.exceptions,
            exception_name,
            FatalConnectionError,
            raising=False,
        )
        recorder = TickRecorder(storage=MagicMock(), api_key=api_key, reconnect_delay=0.25)
        failure = FatalConnectionError(f"invalid setup for {api_key}")

        def failed_connect(_url):
            raise failure

        reconnect_wait = AsyncMock()
        monkeypatch.setattr(module.websockets, "connect", failed_connect)
        monkeypatch.setattr(recorder, "_wait_for_reconnect_delay", reconnect_wait)

        with pytest.raises(FatalConnectionError, match="invalid setup"):
            await recorder.run()

        reconnect_wait.assert_not_awaited()
        assert api_key not in recorder.last_error
        assert recorder.is_running is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("exception_type", ["ConcurrencyError", "InvalidState"])
    async def test_websocket_programming_errors_escape_instead_of_reconnecting(self, monkeypatch, exception_type):
        from flinttrade_data import tick_recorder as module
        from flinttrade_data.tick_recorder import TickRecorder

        recorder = TickRecorder(storage=MagicMock(), reconnect_delay=0.25)
        exception_class = getattr(module.websockets.exceptions, exception_type)
        failure = exception_class("recorder WebSocket misuse")

        def failed_connect(_url):
            raise failure

        reconnect_wait = AsyncMock()
        monkeypatch.setattr(module.websockets, "connect", failed_connect)
        monkeypatch.setattr(recorder, "_wait_for_reconnect_delay", reconnect_wait)

        with pytest.raises(exception_class, match="WebSocket misuse"):
            await recorder.run()

        reconnect_wait.assert_not_awaited()
        assert recorder.is_running is False
        assert recorder.is_connected is False

    @pytest.mark.asyncio
    async def test_control_error_frame_triggers_reconnect(self, monkeypatch):
        from flinttrade_data import tick_recorder as module
        from flinttrade_data.tick_recorder import TickRecorder

        class ErrorWebSocket:
            async def send(self, _message):
                return None

            async def recv(self):
                return json.dumps({"status": "authenticated"})

            def __aiter__(self):
                return self

            async def __anext__(self):
                if not hasattr(self, "sent_error"):
                    self.sent_error = True
                    return json.dumps({"type": "error", "message": "subscription control failed"})
                raise AssertionError("control error should have ended consumption")

        class WebSocketContext:
            async def __aenter__(self):
                return ErrorWebSocket()

            async def __aexit__(self, _exc_type, _exc, _tb):
                return False

        recorder = TickRecorder(storage=MagicMock(), reconnect_delay=0.25)

        async def stop_during_backoff(_delay):
            recorder.stop()

        sleep = AsyncMock(side_effect=stop_during_backoff)
        monkeypatch.setattr(module.websockets, "connect", lambda _url: WebSocketContext())
        monkeypatch.setattr(module.asyncio, "sleep", sleep)

        await recorder.run()

        sleep.assert_awaited_once_with(0.25)
        assert recorder.last_error == "subscription control failed"

    @pytest.mark.asyncio
    async def test_partial_subscribe_ack_without_successes_triggers_reconnect(self, monkeypatch):
        from flinttrade_data import tick_recorder as module
        from flinttrade_data.tick_recorder import TickRecorder

        class PartialWebSocket:
            async def send(self, _message):
                return None

            async def recv(self):
                return json.dumps({"status": "authenticated"})

            def __aiter__(self):
                return self

            async def __anext__(self):
                if not hasattr(self, "sent_partial"):
                    self.sent_partial = True
                    return json.dumps(
                        {
                            "type": "subscribe",
                            "status": "partial",
                            "subscriptions": [{"exchange": "NSE", "symbol": "RELIANCE", "status": "error"}],
                        }
                    )
                raise AssertionError("zero-success partial acknowledgement should have ended consumption")

        class WebSocketContext:
            async def __aenter__(self):
                return PartialWebSocket()

            async def __aexit__(self, _exc_type, _exc, _tb):
                return False

        recorder = TickRecorder(storage=MagicMock(), reconnect_delay=0.25)

        async def stop_during_backoff(_delay):
            recorder.stop()

        sleep = AsyncMock(side_effect=stop_during_backoff)
        monkeypatch.setattr(module.websockets, "connect", lambda _url: WebSocketContext())
        monkeypatch.setattr(module.asyncio, "sleep", sleep)

        await recorder.run()

        sleep.assert_awaited_once_with(0.25)
        assert "NSE:RELIANCE" in recorder.last_error

    @pytest.mark.asyncio
    async def test_partial_subscribe_ack_with_success_keeps_consuming_with_degraded_error(self):
        from flinttrade_data.tick_recorder import TickRecorder

        async def frames():
            yield json.dumps(
                {
                    "type": "subscribe",
                    "status": "partial",
                    "subscriptions": [
                        {"exchange": "NSE", "symbol": "RELIANCE", "status": "success"},
                        {"exchange": "NSE", "symbol": "TCS", "status": "error", "message": "rejected"},
                    ],
                }
            )
            yield json.dumps({"exchange": "NSE", "symbol": "RELIANCE", "ltp": 2500.0})

        recorder = TickRecorder(storage=MagicMock())
        self._allow(recorder, ("NSE", "RELIANCE"))
        recorder._running = True
        recorder._connected = True

        await recorder._consume(frames())

        assert recorder.tick_count == 1
        assert recorder.is_connected is True
        assert "NSE:TCS" in recorder.last_error
        assert "rejected" in recorder.last_error

    def test_partial_subscribe_ack_surfaces_sanitised_failure_and_stays_connected(self):
        from flinttrade_data.tick_recorder import TickRecorder

        api_key = "configured-test-key"
        recorder = TickRecorder(storage=MagicMock(), api_key=api_key)
        recorder._connected = True

        recorder._process_tick(
            {
                "type": "subscribe",
                "status": "partial",
                "subscriptions": [
                    {
                        "exchange": "NSE",
                        "symbol": "RELIANCE",
                        "status": "error",
                        "message": f"subscription rejected for {api_key}",
                    }
                ],
            }
        )

        assert "NSE:RELIANCE" in recorder.last_error
        assert "subscription rejected" in recorder.last_error
        assert api_key not in recorder.last_error
        assert recorder.is_connected is True

    @pytest.mark.parametrize("subscriptions", [None, {}, "invalid-shape"])
    def test_partial_subscribe_ack_with_non_list_subscriptions_sets_generic_error(self, subscriptions):
        from flinttrade_data.tick_recorder import TickRecorder

        api_key = "configured-test-key"
        recorder = TickRecorder(storage=MagicMock(), api_key=api_key)
        recorder._connected = True

        recorder._process_tick(
            {
                "type": "subscribe",
                "status": "partial",
                "subscriptions": subscriptions,
                "message": f"partial response for {api_key}",
            }
        )

        assert recorder.last_error == "Partial subscription failure: invalid subscriptions response"
        assert api_key not in recorder.last_error
        assert recorder.is_connected is True

    @pytest.mark.asyncio
    async def test_request_reconnect_from_thread_closes_active_socket_and_clears_lifecycle_references(
        self, monkeypatch
    ):
        from flinttrade_data import tick_recorder as module
        from flinttrade_data.tick_recorder import TickRecorder

        connected = asyncio.Event()
        closed = asyncio.Event()

        class BlockingWebSocket:
            async def send(self, _message):
                return None

            async def recv(self):
                connected.set()
                return json.dumps({"status": "authenticated"})

            async def close(self):
                closed.set()

            def __aiter__(self):
                return self

            async def __anext__(self):
                await closed.wait()
                raise StopAsyncIteration

        class WebSocketContext:
            async def __aenter__(self):
                return BlockingWebSocket()

            async def __aexit__(self, _exc_type, _exc, _tb):
                return False

        recorder = TickRecorder(storage=MagicMock(), reconnect_delay=0.25)

        async def stop_during_backoff(_delay):
            recorder.stop()

        monkeypatch.setattr(module.websockets, "connect", lambda _url: WebSocketContext())
        monkeypatch.setattr(module.asyncio, "sleep", AsyncMock(side_effect=stop_during_backoff))

        assert recorder.request_reconnect() is False
        task = asyncio.create_task(recorder.run())
        await asyncio.wait_for(connected.wait(), timeout=0.2)

        result: list[bool] = []
        thread = threading.Thread(target=lambda: result.append(recorder.request_reconnect()))
        thread.start()
        thread.join(timeout=0.2)

        assert thread.is_alive() is False
        assert result == [True]
        await asyncio.wait_for(task, timeout=0.2)
        assert recorder.request_reconnect() is False
        assert recorder._active_ws is None
        assert recorder._loop is None

    @pytest.mark.asyncio
    async def test_connection_reconfiguration_discards_a_stale_connection_before_authentication(self, monkeypatch):
        from flinttrade_data import tick_recorder as module
        from flinttrade_data.tick_recorder import TickRecorder

        first_entered = asyncio.Event()
        release_first = asyncio.Event()
        connect_urls: list[str] = []

        class FirstWebSocket:
            def __init__(self) -> None:
                self.sent: list[str] = []

            async def send(self, message: str) -> None:
                self.sent.append(message)

            async def recv(self) -> str:
                return json.dumps({"status": "authenticated"})

            def __aiter__(self):
                return self

            async def __anext__(self):
                raise AssertionError("stale connection must not be consumed")

        class SecondWebSocket:
            def __init__(self) -> None:
                self.sent: list[str] = []

            async def send(self, message: str) -> None:
                self.sent.append(message)

            async def recv(self) -> str:
                return json.dumps({"status": "authenticated"})

            def __aiter__(self):
                return self

            async def __anext__(self):
                recorder.stop()
                raise StopAsyncIteration

        first_ws = FirstWebSocket()
        second_ws = SecondWebSocket()

        class FirstContext:
            async def __aenter__(self):
                first_entered.set()
                await release_first.wait()
                return first_ws

            async def __aexit__(self, _exc_type, _exc, _tb):
                return False

        class SecondContext:
            async def __aenter__(self):
                return second_ws

            async def __aexit__(self, _exc_type, _exc, _tb):
                return False

        def connect(url: str):
            connect_urls.append(url)
            return FirstContext() if len(connect_urls) == 1 else SecondContext()

        recorder = TickRecorder(
            storage=MagicMock(),
            ws_url="ws://old-openalgo.local:8765",
            api_key="old-key",
        )
        monkeypatch.setattr(module.websockets, "connect", connect)
        task = asyncio.create_task(recorder.run())
        await asyncio.wait_for(first_entered.wait(), timeout=0.2)

        try:
            changed = await asyncio.to_thread(
                recorder.reconfigure_connection,
                ws_url="ws://new-openalgo.local:9876",
                api_key="new-key",
            )
            release_first.set()
            await asyncio.wait_for(task, timeout=0.2)
        finally:
            release_first.set()
            if not task.done():
                recorder.stop()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        assert changed is True
        assert connect_urls == ["ws://old-openalgo.local:8765", "ws://new-openalgo.local:9876"]
        assert first_ws.sent == []
        assert json.loads(second_ws.sent[0]) == {"action": "authenticate", "api_key": "new-key"}

    @pytest.mark.asyncio
    async def test_flush_interval_persists_buffered_tail_while_stream_is_idle(self, monkeypatch):
        from flinttrade_data import tick_recorder as module
        from flinttrade_data.tick_recorder import TickRecorder

        class IdleWebSocket:
            def __init__(self) -> None:
                self.sent_tick = False

            async def send(self, _message):
                return None

            async def recv(self):
                return json.dumps({"status": "authenticated"})

            def __aiter__(self):
                return self

            async def __anext__(self):
                if not self.sent_tick:
                    self.sent_tick = True
                    return json.dumps(
                        {"exchange": "NSE", "symbol": "RELIANCE", "ltp": 2500.0, "volume": 1000}
                    )
                await asyncio.Future()

        class WebSocketContext:
            async def __aenter__(self):
                return IdleWebSocket()

            async def __aexit__(self, _exc_type, _exc, _tb):
                return False

        storage = MagicMock()
        recorder = TickRecorder(storage=storage, flush_interval=0.01)
        recorder.add_symbols([{"exchange": "NSE", "symbol": "RELIANCE"}], mode="quote")
        monkeypatch.setattr(module.websockets, "connect", lambda _url: WebSocketContext())

        task = asyncio.create_task(recorder.run())
        try:
            await asyncio.sleep(0.05)
            assert storage.insert_ticks_batch.call_count == 1
            assert recorder.pending_tick_count == 0
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_flush_interval_persists_buffered_tail_during_reconnect_backoff(self, monkeypatch):
        from flinttrade_data import tick_recorder as module
        from flinttrade_data.tick_recorder import TickRecorder

        storage = MagicMock()
        recorder = TickRecorder(
            storage=storage,
            flush_interval=0.01,
            reconnect_delay=1.0,
        )
        recorder.add_symbols([{"exchange": "NSE", "symbol": "RELIANCE"}], mode="quote")
        recorder._process_tick({"exchange": "NSE", "symbol": "RELIANCE", "ltp": 2500.0, "volume": 1000})
        monkeypatch.setattr(module.websockets, "connect", lambda _url: (_ for _ in ()).throw(OSError("offline")))

        task = asyncio.create_task(recorder.run())
        try:
            await asyncio.sleep(0.05)
            assert task.done() is False
            assert storage.insert_ticks_batch.call_count == 1
            assert recorder.pending_tick_count == 0
        finally:
            recorder.stop()
            await asyncio.wait_for(task, timeout=0.2)

    def test_connection_reconfiguration_is_idempotent(self):
        from flinttrade_data.tick_recorder import TickRecorder

        recorder = TickRecorder(
            storage=MagicMock(),
            ws_url="ws://openalgo.local:8765",
            api_key="configured-key",
        )

        assert recorder.reconfigure_connection(
            ws_url="ws://openalgo.local:8765",
            api_key="configured-key",
        ) is False

    def test_connection_reconfiguration_retains_all_keys_for_shutdown_redaction(self):
        from flinttrade_data.tick_recorder import TickRecorder

        recorder = TickRecorder(storage=MagicMock(), api_key="boot-key")
        recorder.reconfigure_connection(ws_url="ws://openalgo.local:9876", api_key="rotated-key")

        assert recorder.sanitise_error("boot-key then rotated-key") == "[redacted] then [redacted]"

    @pytest.mark.asyncio
    async def test_cancellation_runs_final_flush(self, monkeypatch):
        from flinttrade_data import tick_recorder as module
        from flinttrade_data.tick_recorder import TickRecorder

        class BlockingWebSocket:
            async def send(self, _message):
                return None

            async def recv(self):
                return json.dumps({"status": "authenticated"})

            def __aiter__(self):
                return self

            async def __anext__(self):
                await asyncio.sleep(3600)

        class WebSocketContext:
            async def __aenter__(self):
                return BlockingWebSocket()

            async def __aexit__(self, _exc_type, _exc, _tb):
                return False

        storage = MagicMock()
        recorder = TickRecorder(storage=storage, api_key="configured-test-key")
        self._allow(recorder, ("NSE", "RELIANCE"))
        recorder._process_tick({"exchange": "NSE", "symbol": "RELIANCE", "ltp": 2500.0})
        monkeypatch.setattr(module.websockets, "connect", lambda _url: WebSocketContext())

        task = asyncio.create_task(recorder.run())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        storage.insert_ticks_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancellation_forces_one_final_flush_during_persistence_backoff(self, monkeypatch):
        from flinttrade_data import tick_recorder as module
        from flinttrade_data.tick_recorder import TickRecorder

        consume_started = asyncio.Event()

        class BlockingWebSocket:
            async def send(self, _message):
                return None

            async def recv(self):
                return json.dumps({"status": "authenticated"})

            def __aiter__(self):
                return self

            async def __anext__(self):
                consume_started.set()
                await asyncio.Future()

        class WebSocketContext:
            async def __aenter__(self):
                return BlockingWebSocket()

            async def __aexit__(self, _exc_type, _exc, _tb):
                return False

        storage = MagicMock()
        storage.insert_ticks_batch.side_effect = [RuntimeError("duckdb locked"), None]
        recorder = TickRecorder(storage=storage, api_key="configured-test-key")
        self._allow(recorder, ("NSE", "RELIANCE"))
        recorder._process_tick({"exchange": "NSE", "symbol": "RELIANCE", "ltp": 2500.0})
        recorder._flush()
        monkeypatch.setattr(module.websockets, "connect", lambda _url: WebSocketContext())

        task = asyncio.create_task(recorder.run())
        await asyncio.wait_for(consume_started.wait(), timeout=0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert storage.insert_ticks_batch.call_count == 2
        assert recorder.persisted_tick_count == 1
        assert recorder.pending_tick_count == 0

    @pytest.mark.asyncio
    async def test_final_flush_failure_is_propagated_from_run(self, monkeypatch):
        from flinttrade_data import tick_recorder as module
        from flinttrade_data.tick_recorder import TickRecorder

        class StoppingWebSocket:
            async def send(self, _message):
                return None

            async def recv(self):
                return json.dumps({"status": "authenticated"})

            def __aiter__(self):
                return self

            async def __anext__(self):
                recorder.stop()
                raise StopAsyncIteration

        class WebSocketContext:
            async def __aenter__(self):
                return StoppingWebSocket()

            async def __aexit__(self, _exc_type, _exc, _tb):
                return False

        storage = MagicMock()
        storage.insert_ticks_batch.side_effect = RuntimeError("disk full")
        recorder = TickRecorder(storage=storage)
        self._allow(recorder, ("NSE", "RELIANCE"))
        recorder._process_tick({"exchange": "NSE", "symbol": "RELIANCE", "ltp": 2500.0})
        monkeypatch.setattr(module.websockets, "connect", lambda _url: WebSocketContext())

        with pytest.raises(RuntimeError, match="Tick persistence failed"):
            await recorder.run()

        assert recorder.pending_tick_count == 1

    @pytest.mark.asyncio
    async def test_normal_websocket_eof_clears_state_and_backs_off(self, monkeypatch):
        from flinttrade_data import tick_recorder as module
        from flinttrade_data.tick_recorder import TickRecorder

        class FiniteWebSocket:
            async def send(self, _message):
                return None

            async def recv(self):
                return json.dumps({"status": "authenticated"})

            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        class WebSocketContext:
            async def __aenter__(self):
                return FiniteWebSocket()

            async def __aexit__(self, _exc_type, _exc, _tb):
                return False

        recorder = TickRecorder(storage=MagicMock(), reconnect_delay=0.25)
        connect_calls = 0

        def connect(_url):
            nonlocal connect_calls
            connect_calls += 1
            if connect_calls > 1:
                recorder.stop()
            return WebSocketContext()

        async def stop_during_backoff(_delay):
            recorder.stop()

        sleep = AsyncMock(side_effect=stop_during_backoff)
        monkeypatch.setattr(module.websockets, "connect", connect)
        monkeypatch.setattr(module.asyncio, "sleep", sleep)

        await recorder.run()

        sleep.assert_awaited_once_with(0.25)
        assert connect_calls == 1
        assert recorder.is_connected is False
        assert "ended" in recorder.last_error

    @pytest.mark.asyncio
    async def test_normal_websocket_eof_does_not_back_off_after_stop(self, monkeypatch):
        from flinttrade_data import tick_recorder as module
        from flinttrade_data.tick_recorder import TickRecorder

        recorder = TickRecorder(storage=MagicMock(), reconnect_delay=0.25)

        class StoppingWebSocket:
            async def send(self, _message):
                return None

            async def recv(self):
                return json.dumps({"status": "authenticated"})

            def __aiter__(self):
                return self

            async def __anext__(self):
                recorder.stop()
                raise StopAsyncIteration

        class WebSocketContext:
            async def __aenter__(self):
                return StoppingWebSocket()

            async def __aexit__(self, _exc_type, _exc, _tb):
                return False

        sleep = AsyncMock()
        monkeypatch.setattr(module.websockets, "connect", lambda _url: WebSocketContext())
        monkeypatch.setattr(module.asyncio, "sleep", sleep)

        await recorder.run()

        sleep.assert_not_awaited()
        assert recorder.is_connected is False

    @pytest.mark.asyncio
    async def test_stop_interrupts_active_reconnect_delay(self, monkeypatch):
        from flinttrade_data import tick_recorder as module
        from flinttrade_data.tick_recorder import TickRecorder

        delay_started = asyncio.Event()

        async def blocking_sleep(_delay):
            delay_started.set()
            await asyncio.Future()

        def failed_connect(_url):
            raise OSError("offline")

        sleep = AsyncMock(side_effect=blocking_sleep)
        monkeypatch.setattr(module.websockets, "connect", failed_connect)
        monkeypatch.setattr(module.asyncio, "sleep", sleep)
        recorder = TickRecorder(storage=MagicMock(), reconnect_delay=30.0)

        task = asyncio.create_task(recorder.run())
        await asyncio.wait_for(delay_started.wait(), timeout=0.2)
        recorder.stop()
        await asyncio.wait_for(task, timeout=0.2)

        sleep.assert_awaited_once_with(30.0)
        assert recorder.is_running is False

    @pytest.mark.asyncio
    async def test_cancellation_during_reconnect_delay_propagates(self, monkeypatch):
        from flinttrade_data import tick_recorder as module
        from flinttrade_data.tick_recorder import TickRecorder

        delay_started = asyncio.Event()

        async def blocking_sleep(_delay):
            delay_started.set()
            await asyncio.Future()

        def failed_connect(_url):
            raise OSError("offline")

        monkeypatch.setattr(module.websockets, "connect", failed_connect)
        monkeypatch.setattr(module.asyncio, "sleep", AsyncMock(side_effect=blocking_sleep))
        recorder = TickRecorder(storage=MagicMock(), reconnect_delay=30.0)

        task = asyncio.create_task(recorder.run())
        await asyncio.wait_for(delay_started.wait(), timeout=0.2)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_reconnect_delay_waits_until_sleep_completes(self, monkeypatch):
        from flinttrade_data import tick_recorder as module
        from flinttrade_data.tick_recorder import TickRecorder

        delay_started = asyncio.Event()
        release_delay = asyncio.Event()
        connect_calls = 0

        async def controlled_sleep(_delay):
            delay_started.set()
            await release_delay.wait()

        recorder = TickRecorder(storage=MagicMock(), reconnect_delay=0.25)

        def failed_connect(_url):
            nonlocal connect_calls
            connect_calls += 1
            if connect_calls > 1:
                recorder.stop()
            raise OSError("offline")

        sleep = AsyncMock(side_effect=controlled_sleep)
        monkeypatch.setattr(module.websockets, "connect", failed_connect)
        monkeypatch.setattr(module.asyncio, "sleep", sleep)

        task = asyncio.create_task(recorder.run())
        await asyncio.wait_for(delay_started.wait(), timeout=0.2)
        assert task.done() is False

        release_delay.set()
        await asyncio.wait_for(task, timeout=0.2)

        sleep.assert_awaited_once_with(0.25)
        assert connect_calls == 2

    def test_process_tick_ltp(self):
        storage, recorder = self._make_recorder()
        self._allow(recorder, ("NSE", "RELIANCE"))
        recorder._process_tick({"symbol": "RELIANCE", "exchange": "NSE", "ltp": 2500.0})
        assert recorder.tick_count == 1
        assert len(recorder._buffer) == 1

    def test_process_tick_quote(self):
        _, recorder = self._make_recorder()
        self._allow(recorder, ("NSE", "RELIANCE"))
        recorder._process_tick(
            {
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "ltp": 2500.0,
                "bid": 2499.0,
                "ask": 2501.0,
                "volume": 1000,
            }
        )
        assert recorder._buffer[0][3] == "quote"  # mode

    def test_process_tick_depth(self):
        _, recorder = self._make_recorder()
        self._allow(recorder, ("NSE", "RELIANCE"))
        recorder._process_tick(
            {
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "ltp": 2500.0,
                "bids": [{"price": 2499, "qty": 100}],
                "asks": [{"price": 2501, "qty": 50}],
            }
        )
        assert recorder._buffer[0][3] == "depth"
        assert recorder._buffer[0][14] is not None  # depth_json

    def test_process_tick_missing_symbol_ignored(self):
        _, recorder = self._make_recorder()
        recorder._process_tick({"exchange": "NSE", "ltp": 2500.0})
        assert recorder.tick_count == 0

    def test_process_tick_feeds_orderflow_aggregator(self):
        # The recorder feeds the live order-flow aggregator so the footprint is
        # real, not synthetic. First tick = baseline; second = a buyer-initiated
        # trade (price up, +300 volume).
        from flinttrade_data.orderflow_aggregator import OrderFlowAggregator
        from flinttrade_data.storage import StorageManager
        from flinttrade_data.tick_recorder import TickRecorder

        storage = StorageManager(":memory:")
        storage.initialise()
        agg = OrderFlowAggregator()
        recorder = TickRecorder(storage=storage, orderflow_aggregator=agg)
        self._allow(recorder, ("NSE", "RELIANCE"))
        recorder._process_tick({"symbol": "RELIANCE", "exchange": "NSE", "ltp": 2500.0, "volume": 1000})
        recorder._process_tick({"symbol": "RELIANCE", "exchange": "NSE", "ltp": 2505.0, "volume": 1300})
        buckets = agg.get_footprint("RELIANCE", exchange="NSE")
        assert sum(b.buy_volume for b in buckets) == 300
        assert sum(b.sell_volume for b in buckets) == 0

    def test_flush_writes_to_duckdb(self):
        storage, recorder = self._make_recorder()
        self._allow(recorder, ("NSE", "TCS"), ("NSE", "INFY"))
        recorder._process_tick({"symbol": "TCS", "exchange": "NSE", "ltp": 3500.0})
        recorder._process_tick({"symbol": "INFY", "exchange": "NSE", "ltp": 1500.0})
        assert recorder.tick_count == 2
        assert recorder.persisted_tick_count == 0
        assert recorder.pending_tick_count == 2
        recorder._flush()
        assert len(recorder._buffer) == 0
        assert recorder.tick_count == 2
        assert recorder.persisted_tick_count == 2
        assert recorder.pending_tick_count == 0
        # Query ticks directly — avoids timezone edge cases around midnight
        result = storage.connection.execute("SELECT COUNT(*) FROM ticks").fetchone()
        assert result[0] == 2

    def test_flush_retains_buffer_on_write_failure(self):
        # A transient write error must NOT silently discard the batch (the old
        # code cleared the buffer unconditionally). Keep it for the next flush.
        from unittest.mock import MagicMock

        from flinttrade_data.tick_recorder import TickRecorder

        storage = MagicMock()
        storage.insert_ticks_batch.side_effect = RuntimeError("duckdb locked")
        recorder = TickRecorder(storage=storage)
        self._allow(recorder, ("NSE", "TCS"))
        recorder._process_tick({"symbol": "TCS", "exchange": "NSE", "ltp": 3500.0})
        assert len(recorder._buffer) == 1

        recorder._flush()  # insert fails
        assert len(recorder._buffer) == 1  # retained, not lost
        assert recorder.persisted_tick_count == 0
        assert recorder.pending_tick_count == 1
        assert "persistence" in recorder.last_error.lower()

        storage.insert_ticks_batch.side_effect = None  # next flush succeeds
        recorder._flush(force=True)
        assert len(recorder._buffer) == 0  # persisted then cleared
        assert recorder.persisted_tick_count == 1
        assert recorder.pending_tick_count == 0

    def test_flush_pending_raises_then_force_retries_the_retained_batch(self):
        from flinttrade_data.tick_recorder import TickPersistenceError, TickRecorder

        storage = MagicMock()
        storage.insert_ticks_batch.side_effect = [RuntimeError("duckdb locked"), None]
        recorder = TickRecorder(storage=storage)
        self._allow(recorder, ("NSE", "TCS"))
        recorder._process_tick({"symbol": "TCS", "exchange": "NSE", "ltp": 3500.0})

        with pytest.raises(TickPersistenceError, match="Tick persistence failed"):
            recorder.flush_pending()

        assert recorder.pending_tick_count == 1
        assert recorder.persisted_tick_count == 0
        assert recorder.flush_pending() is True
        assert storage.insert_ticks_batch.call_count == 2
        assert recorder.pending_tick_count == 0
        assert recorder.persisted_tick_count == 1
        assert recorder.last_error == ""

    def test_successful_retry_clears_only_persistence_error(self):
        from flinttrade_data.tick_recorder import TickRecorder

        api_key = "configured-test-key"
        storage = MagicMock()
        storage.insert_ticks_batch.side_effect = RuntimeError(f"disk full for {api_key}")
        recorder = TickRecorder(storage=storage, api_key=api_key)
        self._allow(recorder, ("NSE", "TCS"))
        recorder._process_tick({"type": "error", "message": "subscription rejected"})
        recorder._process_tick({"symbol": "TCS", "exchange": "NSE", "ltp": 3500.0})

        recorder._flush()

        assert "persistence" in recorder.last_error.lower()
        assert api_key not in recorder.last_error
        assert recorder.pending_tick_count == 1
        storage.insert_ticks_batch.side_effect = None

        recorder._flush(force=True)

        assert recorder.last_error == "subscription rejected"
        assert recorder.persisted_tick_count == 1
        assert recorder.pending_tick_count == 0

    def test_flush_acquires_the_storage_lock(self):
        # The recorder shares its DuckDB connection with the nightly maintenance
        # job; writes must take the shared lock so the two threads never race.
        from unittest.mock import MagicMock

        from flinttrade_data.tick_recorder import TickRecorder

        storage = MagicMock()
        lock = MagicMock()
        recorder = TickRecorder(storage=storage, storage_lock=lock)
        self._allow(recorder, ("NSE", "TCS"))
        recorder._process_tick({"symbol": "TCS", "exchange": "NSE", "ltp": 3500.0})
        recorder._flush()

        lock.__enter__.assert_called_once()
        lock.__exit__.assert_called_once()
        storage.insert_ticks_batch.assert_called_once()

    def test_flush_caps_buffer_on_persistent_failure(self):
        # A persistent write failure retains ticks for retry, but the buffer is
        # bounded — the oldest are dropped past the cap so memory cannot grow.
        from unittest.mock import MagicMock

        from flinttrade_data.tick_recorder import TickRecorder

        storage = MagicMock()
        storage.insert_ticks_batch.side_effect = RuntimeError("disk full")
        recorder = TickRecorder(storage=storage)
        self._allow(recorder, ("NSE", "TCS"))
        recorder._max_buffer = 3  # tiny cap for a deterministic drop
        for i in range(10):
            recorder._process_tick({"symbol": "TCS", "exchange": "NSE", "ltp": float(i)})
        assert len(recorder._buffer) == 10

        recorder._flush()  # fails, 10 > cap 3 → drop 7 oldest
        assert len(recorder._buffer) == 3
        assert "dropped 7 oldest" in recorder.last_error
        assert recorder.status_snapshot() == {
            "running": False,
            "connected": False,
            "tick_count": 10,
            "persisted_tick_count": 0,
            "pending_tick_count": 3,
            "dropped_tick_count": 7,
            "stale_source_timestamp_rejections": 0,
            "future_source_timestamp_rejections": 0,
            "invalid_source_timestamp_rejections": 0,
            "last_error": recorder.last_error,
            "transport_error": "",
            "persistence_error": recorder.last_error,
            "source_timestamp_error": "",
        }

        storage.insert_ticks_batch.side_effect = None
        recorder._flush(force=True)

        snapshot = recorder.status_snapshot()
        assert snapshot["tick_count"] == 10
        assert snapshot["persisted_tick_count"] == 3
        assert snapshot["pending_tick_count"] == 0
        assert snapshot["dropped_tick_count"] == 7
        assert snapshot["last_error"] == ""

    def test_persistence_retry_uses_bounded_backoff_and_recovers(self, caplog):
        from flinttrade_data.tick_recorder import TickRecorder

        now = [0.0]
        attempt_times: list[float] = []

        def insert_ticks(_rows) -> None:
            attempt_times.append(now[0])
            if len(attempt_times) < 5:
                raise RuntimeError("duckdb unavailable")

        storage = MagicMock()
        storage.insert_ticks_batch.side_effect = insert_ticks
        recorder = TickRecorder(storage=storage)
        self._allow(recorder, ("NSE", "TCS"))
        recorder._persistence_clock = lambda: now[0]
        recorder._persistence_retry_delay = 1.0
        recorder._max_persistence_retry_delay = 4.0
        recorder._max_buffer = 3
        caplog.set_level("ERROR", logger="flinttrade.data.tick_recorder")

        for i in range(4):
            recorder._process_tick({"symbol": "TCS", "exchange": "NSE", "ltp": float(i)})
        recorder._flush()

        for i in range(10):
            recorder._process_tick({"symbol": "TCS", "exchange": "NSE", "ltp": float(i + 10)})
            recorder._flush()

        assert attempt_times == [0.0]
        assert caplog.text.count("Failed to flush") == 1
        assert recorder.pending_tick_count == 3
        assert recorder.status_snapshot()["dropped_tick_count"] == 11

        for retry_at in (1.0, 3.0, 7.0, 11.0):
            now[0] = retry_at - 0.01
            recorder._flush()
            now[0] = retry_at
            recorder._flush()

        assert attempt_times == [0.0, 1.0, 3.0, 7.0, 11.0]
        assert recorder.persisted_tick_count == 3
        assert recorder.pending_tick_count == 0
        assert recorder.last_error == ""

    def test_detect_mode(self):
        from flinttrade_data.tick_recorder import TickRecorder

        assert TickRecorder._detect_mode({"ltp": 100}) == "ltp"
        assert TickRecorder._detect_mode({"ltp": 100, "bid": 99, "volume": 1000}) == "quote"
        assert TickRecorder._detect_mode({"ltp": 100, "bids": []}) == "depth"

    def test_all_exchange_symbols(self):
        """Verify recorder handles all supported exchanges."""
        _, recorder = self._make_recorder()
        # NCO, MCX_INDEX, GLOBAL_INDEX joined the supported list in the
        # OpenAlgo v2.0.0.7 sync.
        exchanges = [
            "NSE",
            "BSE",
            "NFO",
            "BFO",
            "CDS",
            "BCD",
            "MCX",
            "NCDEX",
            "NCO",
            "MCX_INDEX",
            "GLOBAL_INDEX",
            "DELTA",
        ]
        self._allow(recorder, *((exchange, "TEST") for exchange in exchanges))
        for exch in exchanges:
            recorder._process_tick({"symbol": "TEST", "exchange": exch, "ltp": 100.0})
        assert recorder.tick_count == len(exchanges)


# ======================================================================
# Package exports
# ======================================================================


class TestPackageExports:
    """Verify __init__.py exports the public API."""

    def test_all_exports(self):
        from flinttrade_data import __all__

        expected = ["StorageManager", "TickRecorder", "AuditLogger", "TradeLogger", "TradeSummary"]
        for name in expected:
            assert name in __all__, f"Missing export: {name}"

    def test_version(self):
        from flinttrade_data import __version__
        from flinttrade_core.version import APP_VERSION

        assert __version__ == APP_VERSION

    def test_package_exists(self):
        pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        assert os.path.exists(os.path.join(pkg_dir, "src", "flinttrade_data", "__init__.py"))
        assert os.path.exists(os.path.join(pkg_dir, "README.md"))
