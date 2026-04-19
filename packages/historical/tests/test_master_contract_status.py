"""Tests for MasterContractStatus.

Run with:
    python -m pytest packages/historical/tests/test_master_contract_status.py -v --import-mode=importlib
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture()
def mcs(tmp_path):
    """Create a fresh MasterContractStatus backed by a temp DuckDB file."""
    from packages.historical.src.master_contract_status import MasterContractStatus
    db_path = str(tmp_path / "test_contracts.duckdb")
    status = MasterContractStatus(db_path=db_path)
    yield status
    status.close()


class TestRecordSync:
    """Tests for record_sync()."""

    def test_creates_record(self, mcs):
        mcs.record_sync("zerodha", "NSE", 2341, "abc123")
        last = mcs.last_sync("zerodha", "NSE")
        assert last is not None

    def test_upserts_on_duplicate(self, mcs):
        mcs.record_sync("zerodha", "NSE", 2341, "abc123")
        mcs.record_sync("zerodha", "NSE", 2500, "def456")
        statuses = mcs.all_statuses()
        nse = [s for s in statuses if s["broker"] == "zerodha" and s["exchange"] == "NSE"]
        assert len(nse) == 1
        assert nse[0]["symbol_count"] == 2500
        assert nse[0]["checksum"] == "def456"

    def test_normalises_broker_lowercase(self, mcs):
        mcs.record_sync("ZERODHA", "NSE", 100, "x")
        last = mcs.last_sync("zerodha", "NSE")
        assert last is not None

    def test_normalises_exchange_uppercase(self, mcs):
        mcs.record_sync("zerodha", "nse", 100, "x")
        last = mcs.last_sync("zerodha", "NSE")
        assert last is not None

    def test_multiple_brokers_independent(self, mcs):
        mcs.record_sync("zerodha", "NSE", 100, "a")
        mcs.record_sync("angel", "NSE", 200, "b")
        assert mcs.last_sync("zerodha", "NSE") is not None
        assert mcs.last_sync("angel", "NSE") is not None
        assert mcs.all_statuses().__len__() == 2


class TestLastSync:
    """Tests for last_sync()."""

    def test_returns_none_when_not_synced(self, mcs):
        assert mcs.last_sync("nobody", "BSE") is None

    def test_returns_utc_aware_datetime(self, mcs):
        mcs.record_sync("zerodha", "BSE", 50, "csum")
        last = mcs.last_sync("zerodha", "BSE")
        assert last is not None
        assert last.tzinfo is not None


class TestNeedsSync:
    """Tests for needs_sync()."""

    def test_needs_sync_when_never_synced(self, mcs):
        assert mcs.needs_sync("zerodha", "MCX") is True

    def test_fresh_sync_does_not_need_resync(self, mcs):
        mcs.record_sync("zerodha", "NSE", 100, "fresh")
        assert mcs.needs_sync("zerodha", "NSE", max_age_hours=24) is False

    def test_old_sync_needs_resync(self, mcs):
        # Record a sync, then manually move the timestamp to 48h ago
        mcs.record_sync("zerodha", "NSE", 100, "old")
        old_ts = (datetime.now(tz=timezone.utc) - timedelta(hours=48)).replace(tzinfo=None)
        mcs.connection.execute(
            "UPDATE master_contract_status SET last_sync_utc = ? WHERE broker = ? AND exchange = ?",
            [old_ts, "zerodha", "NSE"],
        )
        assert mcs.needs_sync("zerodha", "NSE", max_age_hours=24) is True

    def test_custom_max_age(self, mcs):
        mcs.record_sync("zerodha", "NSE", 100, "x")
        # Very strict threshold — should need sync immediately
        assert mcs.needs_sync("zerodha", "NSE", max_age_hours=0) is True


class TestAllStatuses:
    """Tests for all_statuses()."""

    def test_empty_when_no_records(self, mcs):
        assert mcs.all_statuses() == []

    def test_returns_all_records(self, mcs):
        mcs.record_sync("zerodha", "NSE", 100, "a")
        mcs.record_sync("angel", "BSE", 200, "b")
        statuses = mcs.all_statuses()
        assert len(statuses) == 2

    def test_row_has_expected_keys(self, mcs):
        mcs.record_sync("zerodha", "NSE", 100, "csum")
        row = mcs.all_statuses()[0]
        for key in ("broker", "exchange", "last_sync_utc", "symbol_count", "checksum"):
            assert key in row

    def test_last_sync_utc_is_iso_string(self, mcs):
        mcs.record_sync("zerodha", "NSE", 100, "csum")
        row = mcs.all_statuses()[0]
        # Should be parseable as ISO datetime
        datetime.fromisoformat(row["last_sync_utc"])


class TestStaleContracts:
    """Tests for stale_contracts()."""

    def test_returns_stale_records(self, mcs):
        mcs.record_sync("zerodha", "NSE", 100, "old")
        old_ts = (datetime.now(tz=timezone.utc) - timedelta(hours=48)).replace(tzinfo=None)
        mcs.connection.execute(
            "UPDATE master_contract_status SET last_sync_utc = ? WHERE broker = ? AND exchange = ?",
            [old_ts, "zerodha", "NSE"],
        )
        stale = mcs.stale_contracts(max_age_hours=24)
        assert len(stale) == 1
        assert stale[0]["broker"] == "zerodha"

    def test_fresh_records_not_stale(self, mcs):
        mcs.record_sync("zerodha", "NSE", 100, "fresh")
        stale = mcs.stale_contracts(max_age_hours=24)
        assert stale == []

    def test_mixed_returns_only_stale(self, mcs):
        mcs.record_sync("zerodha", "NSE", 100, "fresh")
        mcs.record_sync("angel", "BSE", 50, "old")
        old_ts = (datetime.now(tz=timezone.utc) - timedelta(hours=30)).replace(tzinfo=None)
        mcs.connection.execute(
            "UPDATE master_contract_status SET last_sync_utc = ? WHERE broker = ? AND exchange = ?",
            [old_ts, "angel", "BSE"],
        )
        stale = mcs.stale_contracts(max_age_hours=24)
        brokers = [s["broker"] for s in stale]
        assert "angel" in brokers
        assert "zerodha" not in brokers


class TestChecksumHelper:
    """Tests for checksum_for_symbols()."""

    def test_returns_64_char_hex(self):
        from packages.historical.src.master_contract_status import checksum_for_symbols
        cs = checksum_for_symbols(["NIFTY", "RELIANCE"])
        assert len(cs) == 64
        assert all(c in "0123456789abcdef" for c in cs)

    def test_order_independent(self):
        from packages.historical.src.master_contract_status import checksum_for_symbols
        a = checksum_for_symbols(["NIFTY", "RELIANCE"])
        b = checksum_for_symbols(["RELIANCE", "NIFTY"])
        assert a == b

    def test_different_symbols_different_checksum(self):
        from packages.historical.src.master_contract_status import checksum_for_symbols
        a = checksum_for_symbols(["NIFTY"])
        b = checksum_for_symbols(["SENSEX"])
        assert a != b

    def test_empty_list(self):
        from packages.historical.src.master_contract_status import checksum_for_symbols
        cs = checksum_for_symbols([])
        assert len(cs) == 64
