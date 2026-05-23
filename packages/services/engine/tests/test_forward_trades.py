"""Tests for ForwardTradeLog — JSON-lines per-strategy trade persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flinttrade_engine.forward_trade_log import ForwardTradeLog


@pytest.fixture()
def log_dir(tmp_path: Path) -> Path:
    """Return a temporary directory for forward trade logs."""
    return tmp_path / "forward_trades"


@pytest.fixture()
def trade_log(log_dir: Path) -> ForwardTradeLog:
    """Return a ForwardTradeLog instance backed by a temp directory."""
    return ForwardTradeLog(log_dir)


STRATEGY_A = "aaaaaaaa-1111-2222-3333-444444444444"
STRATEGY_B = "bbbbbbbb-5555-6666-7777-888888888888"


class TestLogTrade:
    """Test ForwardTradeLog.log_trade()."""

    def test_log_trade_creates_file(self, trade_log: ForwardTradeLog, log_dir: Path) -> None:
        """Logging a trade should create a JSONL file for the strategy."""
        trade_log.log_trade(STRATEGY_A, {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": 10,
            "price": 2500.0,
            "order_id": "ORD-001",
        })
        path = log_dir / f"{STRATEGY_A}.jsonl"
        assert path.exists()
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["symbol"] == "RELIANCE"
        assert record["action"] == "BUY"
        assert record["quantity"] == 10
        assert record["strategy_id"] == STRATEGY_A

    def test_log_trade_adds_timestamp(self, trade_log: ForwardTradeLog) -> None:
        """A timestamp should be auto-generated if not provided."""
        result = trade_log.log_trade(STRATEGY_A, {"symbol": "NIFTY", "action": "SELL"})
        assert "timestamp" in result
        assert result["timestamp"]  # non-empty

    def test_log_trade_preserves_caller_timestamp(self, trade_log: ForwardTradeLog) -> None:
        """If the caller provides a timestamp, it should be kept."""
        result = trade_log.log_trade(STRATEGY_A, {
            "symbol": "NIFTY",
            "action": "BUY",
            "timestamp": "2026-04-08T10:00:00+05:30",
        })
        assert result["timestamp"] == "2026-04-08T10:00:00+05:30"

    def test_log_trade_appends(self, trade_log: ForwardTradeLog) -> None:
        """Multiple trades for the same strategy append to the same file."""
        trade_log.log_trade(STRATEGY_A, {"symbol": "RELIANCE", "action": "BUY"})
        trade_log.log_trade(STRATEGY_A, {"symbol": "RELIANCE", "action": "SELL"})
        trades = trade_log.get_trades(STRATEGY_A)
        assert len(trades) == 2
        assert trades[0]["action"] == "BUY"
        assert trades[1]["action"] == "SELL"


class TestGetTrades:
    """Test ForwardTradeLog.get_trades()."""

    def test_no_trades_returns_empty(self, trade_log: ForwardTradeLog) -> None:
        """Getting trades for a non-existent strategy returns []."""
        assert trade_log.get_trades("nonexistent-id") == []

    def test_trades_filtered_by_strategy(self, trade_log: ForwardTradeLog) -> None:
        """Trades for different strategies are stored separately."""
        trade_log.log_trade(STRATEGY_A, {"symbol": "RELIANCE", "action": "BUY"})
        trade_log.log_trade(STRATEGY_B, {"symbol": "TCS", "action": "SELL"})
        trade_log.log_trade(STRATEGY_A, {"symbol": "INFY", "action": "BUY"})

        trades_a = trade_log.get_trades(STRATEGY_A)
        trades_b = trade_log.get_trades(STRATEGY_B)

        assert len(trades_a) == 2
        assert len(trades_b) == 1
        assert trades_a[0]["symbol"] == "RELIANCE"
        assert trades_a[1]["symbol"] == "INFY"
        assert trades_b[0]["symbol"] == "TCS"

    def test_corrupt_line_skipped(self, trade_log: ForwardTradeLog, log_dir: Path) -> None:
        """Corrupt JSON lines should be skipped without crashing."""
        trade_log.log_trade(STRATEGY_A, {"symbol": "RELIANCE", "action": "BUY"})
        # Manually inject a corrupt line
        path = log_dir / f"{STRATEGY_A}.jsonl"
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("this is not valid json\n")
        trade_log.log_trade(STRATEGY_A, {"symbol": "TCS", "action": "SELL"})

        trades = trade_log.get_trades(STRATEGY_A)
        assert len(trades) == 2
        assert trades[0]["symbol"] == "RELIANCE"
        assert trades[1]["symbol"] == "TCS"


class TestClearTrades:
    """Test ForwardTradeLog.clear_trades()."""

    def test_clear_removes_file(self, trade_log: ForwardTradeLog, log_dir: Path) -> None:
        """Clearing trades should remove the JSONL file."""
        trade_log.log_trade(STRATEGY_A, {"symbol": "RELIANCE", "action": "BUY"})
        count = trade_log.clear_trades(STRATEGY_A)
        assert count == 1
        assert not (log_dir / f"{STRATEGY_A}.jsonl").exists()
        assert trade_log.get_trades(STRATEGY_A) == []

    def test_clear_nonexistent_returns_zero(self, trade_log: ForwardTradeLog) -> None:
        """Clearing a non-existent strategy returns 0."""
        assert trade_log.clear_trades("no-such-id") == 0


class TestTradeCount:
    """Test ForwardTradeLog.trade_count()."""

    def test_count_empty(self, trade_log: ForwardTradeLog) -> None:
        assert trade_log.trade_count("no-such-id") == 0

    def test_count_after_logging(self, trade_log: ForwardTradeLog) -> None:
        trade_log.log_trade(STRATEGY_A, {"symbol": "A", "action": "BUY"})
        trade_log.log_trade(STRATEGY_A, {"symbol": "B", "action": "SELL"})
        assert trade_log.trade_count(STRATEGY_A) == 2


class TestPathSafety:
    """Ensure strategy IDs with path traversal characters are sanitised."""

    def test_path_traversal_sanitised(self, trade_log: ForwardTradeLog, log_dir: Path) -> None:
        """Strategy IDs with ../ should not escape the log directory."""
        dodgy_id = "../../etc/passwd"
        trade_log.log_trade(dodgy_id, {"symbol": "X", "action": "BUY"})
        # File should be inside log_dir, not escaped
        trades = trade_log.get_trades(dodgy_id)
        assert len(trades) == 1
        # Verify no files created outside log_dir
        for path in log_dir.rglob("*.jsonl"):
            assert str(path).startswith(str(log_dir))
