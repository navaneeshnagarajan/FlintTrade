"""Tests for ExpiryTracker — option chain snapshot capture and retrieval.

Uses in-memory DuckDB. OpenAlgo client is mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class ModernOptionChainClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def option_chain(self, symbol, exchange="NFO"):
        self.calls.append((symbol, exchange))
        return self.response


class GatewayOptionChainClient:
    def __init__(self, response):
        self.response = response
        self.params = None

    def get_option_chain(self, params):
        self.params = params
        return self.response


class AsyncOptionChainClient:
    def __init__(self, response):
        self.response = response

    async def option_chain(self, symbol, exchange="NFO", expiry=""):
        return self.response


# ---------------------------------------------------------------------------
# Capture and retrieve snapshot
# ---------------------------------------------------------------------------


class TestCaptureSnapshot:
    def _tracker(self, client=None):
        from flinttrade_historical.expiry_tracker import ExpiryTracker
        return ExpiryTracker(client=client, db_path=":memory:")

    def test_capture_stores_rows_in_duckdb(self):
        client = MagicMock(spec=["optionchain"])
        client.optionchain.return_value = [
            {
                "strike_price": 24000,
                "call_oi": 100000, "call_volume": 5000, "call_ltp": 150.5, "call_iv": 12.5,
                "put_oi": 80000, "put_volume": 4000, "put_ltp": 120.0, "put_iv": 13.0,
            },
            {
                "strike_price": 24100,
                "call_oi": 90000, "call_volume": 4500, "call_ltp": 100.0, "call_iv": 11.0,
                "put_oi": 70000, "put_volume": 3500, "put_ltp": 160.0, "put_iv": 14.0,
            },
        ]
        tracker = self._tracker(client)
        count = tracker.capture_snapshot("NIFTY", "260326")
        # 2 strikes x 2 option types = 4 rows
        assert count == 4

    def test_retrieve_after_capture(self):
        client = MagicMock(spec=["optionchain"])
        client.optionchain.return_value = [
            {
                "strike_price": 24000,
                "call_oi": 100000, "call_volume": 5000, "call_ltp": 150.5, "call_iv": 12.5,
                "put_oi": 80000, "put_volume": 4000, "put_ltp": 120.0, "put_iv": 13.0,
            },
        ]
        tracker = self._tracker(client)
        tracker.capture_snapshot("NIFTY", "260326")

        chain = tracker.get_historical_chain("NIFTY", "260326")
        assert len(chain) == 2  # CE + PE
        ce_row = [r for r in chain if r["option_type"] == "CE"][0]
        assert ce_row["strike"] == 24000
        assert ce_row["oi"] == 100000
        assert ce_row["ltp"] == 150.5

        pe_row = [r for r in chain if r["option_type"] == "PE"][0]
        assert pe_row["strike"] == 24000
        assert pe_row["oi"] == 80000

    def test_retrieve_returns_only_the_latest_snapshot(self):
        tracker = self._tracker()
        rows = [
            ("2026-03-25 15:29:00", "snapshot-old", "NIFTY", "NFO", "2026-03-26", 24000, "CE", 100, 50, 150.0, 12.0),
            ("2026-03-25 15:29:00", "snapshot-old", "NIFTY", "NFO", "2026-03-26", 24000, "PE", 80, 40, 120.0, 13.0),
            ("2026-03-25 15:30:00", "snapshot-new", "NIFTY", "NFO", "2026-03-26", 24000, "CE", 110, 60, 155.0, 12.5),
            ("2026-03-25 15:30:00", "snapshot-new", "NIFTY", "NFO", "2026-03-26", 24000, "PE", 90, 45, 125.0, 13.5),
        ]
        tracker.connection.executemany(
            """INSERT INTO expired_option_chains
               (captured_at, snapshot_id, symbol, exchange, expiry_date, strike,
                option_type, oi, volume, ltp, iv)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

        chain = tracker.get_historical_chain("NIFTY", "2026-03-26")

        assert len(chain) == 2
        assert {row["captured_at"].strftime("%H:%M:%S") for row in chain} == {"15:30:00"}
        assert {row["option_type"]: row["ltp"] for row in chain} == {"CE": 155.0, "PE": 125.0}

    def test_equal_timestamps_do_not_merge_distinct_snapshot_ids(self):
        tracker = self._tracker()
        tracker.connection.executemany(
            """INSERT INTO expired_option_chains
               (captured_at, snapshot_id, symbol, exchange, expiry_date, strike,
                option_type, oi, volume, ltp, iv)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                ("2026-03-25 15:30:00", "snapshot-a", "NIFTY", "NFO", "2026-03-26", 23900, "CE", 1, 1, 1, 1),
                ("2026-03-25 15:30:00", "snapshot-b", "NIFTY", "NFO", "2026-03-26", 24100, "CE", 2, 2, 2, 2),
            ],
        )

        chain = tracker.get_historical_chain("NIFTY", "260326")

        assert [(row["strike"], row["ltp"]) for row in chain] == [(24100, 2)]

    def test_capture_with_no_client_returns_zero(self):
        tracker = self._tracker(client=None)
        count = tracker.capture_snapshot("NIFTY", "260326")
        assert count == 0
        assert tracker.last_capture_error == "No OpenAlgo client configured"

    def test_capture_with_empty_response_returns_zero(self):
        client = MagicMock(spec=["optionchain"])
        client.optionchain.return_value = []
        tracker = self._tracker(client)
        count = tracker.capture_snapshot("NIFTY", "260326")
        assert count == 0

    def test_capture_handles_api_error(self):
        client = MagicMock(spec=["optionchain"])
        client.optionchain.side_effect = Exception("API timeout")
        tracker = self._tracker(client)
        count = tracker.capture_snapshot("NIFTY", "260326")
        assert count == 0
        assert tracker.last_capture_error == "API timeout"

    def test_capture_uses_modern_option_chain_client(self):
        client = ModernOptionChainClient([
            {
                "strike_price": 24000,
                "call_oi": 100,
                "call_volume": 50,
                "call_ltp": 150,
                "call_iv": 12,
                "put_oi": 80,
                "put_volume": 40,
                "put_ltp": 120,
                "put_iv": 13,
            },
        ])
        tracker = self._tracker(client)
        count = tracker.capture_snapshot("NIFTY", "260326")
        assert count == 2
        assert client.calls == [("NIFTY", "NFO")]

    def test_capture_uses_gateway_payload_with_expiry(self):
        client = GatewayOptionChainClient({
            "chain": [
                {
                    "strike": 24000,
                    "ce": {"oi": 100, "volume": 50, "ltp": 150, "iv": 0.12},
                    "pe": {"oi": 80, "volume": 40, "ltp": 120, "iv": 0.13},
                },
            ],
        })
        tracker = self._tracker(client)
        count = tracker.capture_snapshot("NIFTY", "2026-03-26")
        assert count == 2
        assert client.params == {
            "symbol": "NIFTY",
            "underlying": "NIFTY",
            "exchange": "NFO",
            "expiry": "2026-03-26",
            "expiry_date": "20260326",
        }

    def test_capture_resolves_async_typed_option_chain(self):
        from flinttrade_core.models import OptionChain, OptionChainStrike

        client = AsyncOptionChainClient(OptionChain(
            underlying="NIFTY",
            exchange="NFO",
            strikes=[
                OptionChainStrike(
                    strike_price=24000,
                    ce_oi=100,
                    ce_volume=50,
                    ce_ltp=150,
                    ce_iv=12,
                    pe_oi=80,
                    pe_volume=40,
                    pe_ltp=120,
                    pe_iv=13,
                ),
            ],
        ))
        tracker = self._tracker(client)
        count = tracker.capture_snapshot("NIFTY", "260326")
        assert count == 2


# ---------------------------------------------------------------------------
# List expiries
# ---------------------------------------------------------------------------


class TestListExpiries:
    def _tracker_with_data(self):
        from flinttrade_historical.expiry_tracker import ExpiryTracker
        client = MagicMock(spec=["optionchain"])
        tracker = ExpiryTracker(client=client, db_path=":memory:")

        # Insert data for two expiries
        client.optionchain.return_value = [
            {"strike_price": 24000, "call_oi": 100, "call_volume": 50,
             "call_ltp": 150, "call_iv": 12, "put_oi": 80, "put_volume": 40,
             "put_ltp": 120, "put_iv": 13},
        ]
        tracker.capture_snapshot("NIFTY", "260326")
        tracker.capture_snapshot("NIFTY", "260402")
        return tracker

    def test_list_returns_all_expiries(self):
        tracker = self._tracker_with_data()
        expiries = tracker.list_expiries("NIFTY")
        assert "2026-03-26" in expiries
        assert "2026-04-02" in expiries
        assert len(expiries) == 2

    def test_list_returns_sorted(self):
        tracker = self._tracker_with_data()
        expiries = tracker.list_expiries("NIFTY")
        assert expiries == sorted(expiries)

    def test_list_empty_for_unknown_symbol(self):
        tracker = self._tracker_with_data()
        expiries = tracker.list_expiries("UNKNOWN")
        assert expiries == []

    def test_list_normalises_and_deduplicates_mixed_expiry_formats(self):
        tracker = self._tracker_with_data()
        tracker.connection.execute(
            """UPDATE expired_option_chains
               SET expiry_date = '26MAR26'
               WHERE expiry_date = '2026-03-26'"""
        )

        chain = tracker.get_historical_chain("NIFTY", "2026-03-26")
        assert chain
        assert {row["expiry_date"] for row in chain} == {"26MAR26"}

        tracker.connection.execute(
            """INSERT INTO expired_option_chains
               (captured_at, snapshot_id, symbol, exchange, expiry_date, strike,
                option_type, oi, volume, ltp, iv)
               VALUES ('2026-03-25 15:30:00', 'legacy-alias', 'NIFTY', 'NFO',
                       '260326', 24100, 'CE', 1, 1, 1, 1)"""
        )

        assert tracker.list_expiries("NIFTY") == ["2026-03-26", "2026-04-02"]
        assert tracker.get_historical_chain("NIFTY", "2026-03-26")


# ---------------------------------------------------------------------------
# get_historical_chain — empty result
# ---------------------------------------------------------------------------


class TestGetHistoricalChainEmpty:
    def test_empty_when_no_data(self):
        from flinttrade_historical.expiry_tracker import ExpiryTracker
        tracker = ExpiryTracker(client=None, db_path=":memory:")
        chain = tracker.get_historical_chain("NIFTY", "260326")
        assert chain == []


# ---------------------------------------------------------------------------
# Parse option chain — alternate key formats
# ---------------------------------------------------------------------------


class TestParseOptionChain:
    def test_parse_nested_dict_response(self):
        from flinttrade_historical.expiry_tracker import ExpiryTracker
        data = {
            "data": [
                {"strike": 24000, "ce_oi": 100, "ce_volume": 50,
                 "ce_ltp": 150, "ce_iv": 12, "pe_oi": 80, "pe_volume": 40,
                 "pe_ltp": 120, "pe_iv": 13},
            ],
        }
        rows = ExpiryTracker._parse_option_chain(data, "NIFTY", "NFO", "260326")
        assert len(rows) == 2
        assert rows[0]["option_type"] == "CE"
        assert rows[1]["option_type"] == "PE"

    def test_parse_skips_zero_strike(self):
        from flinttrade_historical.expiry_tracker import ExpiryTracker
        data = [
            {"strike_price": 0, "call_oi": 100, "call_volume": 50,
             "call_ltp": 150, "call_iv": 12, "put_oi": 80, "put_volume": 40,
             "put_ltp": 120, "put_iv": 13},
        ]
        rows = ExpiryTracker._parse_option_chain(data, "NIFTY", "NFO", "260326")
        assert len(rows) == 0


# ---------------------------------------------------------------------------
# ExpiryFlow-adapted features: rate limiter, metadata, bulk capture
# ---------------------------------------------------------------------------


class TestSnapshotRateLimiter:
    """Verify the rate limiter adapted from ExpiryFlow."""

    def test_rate_limiter_allows_burst(self):
        from flinttrade_historical.expiry_tracker import SnapshotRateLimiter
        limiter = SnapshotRateLimiter(max_per_second=10)
        # Should not raise for a small burst
        for _ in range(5):
            limiter.wait_if_needed()
        assert limiter.requests_today == 5

    def test_rate_limiter_daily_limit_raises(self):
        import pytest
        from flinttrade_historical.expiry_tracker import SnapshotRateLimiter
        limiter = SnapshotRateLimiter(max_per_second=100, max_per_day=3)
        limiter.wait_if_needed()
        limiter.wait_if_needed()
        limiter.wait_if_needed()
        with pytest.raises(RuntimeError, match="Daily API limit"):
            limiter.wait_if_needed()


class TestDownloadMetadata:
    """Verify download metadata tracking adapted from ExpiryFlow."""

    def _tracker(self, client=None):
        from flinttrade_historical.expiry_tracker import ExpiryTracker
        return ExpiryTracker(client=client, db_path=":memory:")

    def test_has_snapshot_false_when_empty(self):
        tracker = self._tracker()
        assert tracker.has_snapshot("NIFTY", "260326") is False

    def test_has_snapshot_true_after_capture(self):
        client = MagicMock(spec=["optionchain"])
        client.optionchain.return_value = [
            {"strike_price": 24000, "call_oi": 100, "call_volume": 50,
             "call_ltp": 150, "call_iv": 12, "put_oi": 80, "put_volume": 40,
             "put_ltp": 120, "put_iv": 13},
        ]
        tracker = self._tracker(client)
        tracker.capture_snapshot("NIFTY", "260326")
        assert tracker.has_snapshot("NIFTY", "260326") is True

    def test_get_download_history(self):
        client = MagicMock(spec=["optionchain"])
        client.optionchain.return_value = [
            {"strike_price": 24000, "call_oi": 100, "call_volume": 50,
             "call_ltp": 150, "call_iv": 12, "put_oi": 80, "put_volume": 40,
             "put_ltp": 120, "put_iv": 13},
        ]
        tracker = self._tracker(client)
        tracker.capture_snapshot("NIFTY", "260326")
        history = tracker.get_download_history()
        assert len(history) == 1
        assert history[0]["symbol"] == "NIFTY"
        assert history[0]["row_count"] == 2


class TestBulkCapture:
    """Verify bulk capture with skip-existing adapted from ExpiryFlow."""

    def test_capture_multiple_skips_existing(self):
        client = MagicMock(spec=["optionchain"])
        client.optionchain.return_value = [
            {"strike_price": 24000, "call_oi": 100, "call_volume": 50,
             "call_ltp": 150, "call_iv": 12, "put_oi": 80, "put_volume": 40,
             "put_ltp": 120, "put_iv": 13},
        ]
        from flinttrade_historical.expiry_tracker import ExpiryTracker
        tracker = ExpiryTracker(client=client, db_path=":memory:")

        # Capture first expiry
        tracker.capture_snapshot("NIFTY", "260326")

        # Bulk capture should skip the first and only fetch the second
        results = tracker.capture_multiple("NIFTY", ["260326", "260402"])
        assert results["260326"] == 0  # skipped
        assert results["260402"] == 2  # 1 strike x 2 types

    def test_capture_multiple_no_skip(self):
        client = MagicMock(spec=["optionchain"])
        client.optionchain.return_value = [
            {"strike_price": 24000, "call_oi": 100, "call_volume": 50,
             "call_ltp": 150, "call_iv": 12, "put_oi": 80, "put_volume": 40,
             "put_ltp": 120, "put_iv": 13},
        ]
        from flinttrade_historical.expiry_tracker import ExpiryTracker
        tracker = ExpiryTracker(client=client, db_path=":memory:")
        results = tracker.capture_multiple("NIFTY", ["260326", "260402"], skip_existing=False)
        assert results["260326"] == 2
        assert results["260402"] == 2


# ---------------------------------------------------------------------------
# Client provider — OpenAlgo settings hot-reload safety
# ---------------------------------------------------------------------------


class TestClientProvider:
    """ExpiryTracker resolves the client PER CAPTURE when given a provider.

    The provider keeps each capture on the authoritative shared client if
    startup fallback replaces it. Normal settings hot-reload reconfigures the
    same client object in place.
    """

    _CHAIN = [
        {"strike_price": 24000, "call_oi": 100, "call_volume": 50,
         "call_ltp": 150, "call_iv": 12, "put_oi": 80, "put_volume": 40,
         "put_ltp": 120, "put_iv": 13},
    ]

    def test_capture_uses_current_provider_client_after_hot_reload(self):
        from flinttrade_historical.expiry_tracker import ExpiryTracker

        client_one = MagicMock(spec=["optionchain"])
        client_one.optionchain.return_value = self._CHAIN
        client_two = MagicMock(spec=["optionchain"])
        client_two.optionchain.return_value = self._CHAIN
        current = {"client": client_one}

        tracker = ExpiryTracker(client=lambda: current["client"], db_path=":memory:")

        assert tracker.capture_snapshot("NIFTY", "260326") == 2
        client_one.optionchain.assert_called_once()
        client_two.optionchain.assert_not_called()

        # Simulate a startup fallback replacing the authoritative client.
        current["client"] = client_two
        assert tracker.capture_snapshot("NIFTY", "260402") == 2
        client_two.optionchain.assert_called_once()
        client_one.optionchain.assert_called_once()  # old client untouched

    def test_provider_failure_degrades_to_no_client(self):
        from flinttrade_historical.expiry_tracker import ExpiryTracker

        def broken_provider():
            raise RuntimeError("no app context")

        tracker = ExpiryTracker(client=broken_provider, db_path=":memory:")
        assert tracker.capture_snapshot("NIFTY", "260326") == 0
        assert tracker.last_capture_error == "No OpenAlgo client configured"

    def test_client_instance_still_accepted(self):
        from flinttrade_historical.expiry_tracker import ExpiryTracker

        client = MagicMock(spec=["optionchain"])
        client.optionchain.return_value = self._CHAIN
        tracker = ExpiryTracker(client=client, db_path=":memory:")
        assert tracker.capture_snapshot("NIFTY", "260326") == 2


# ---------------------------------------------------------------------------
# Default DB path — workspace-resolved, with one-shot legacy migration
# ---------------------------------------------------------------------------


def test_schema_migration_adds_snapshot_id_to_legacy_table(tmp_path):
    import duckdb

    from flinttrade_historical.expiry_tracker import ExpiryTracker

    db_path = tmp_path / "legacy.duckdb"
    connection = duckdb.connect(str(db_path))
    connection.execute(
        """CREATE TABLE expired_option_chains (
               captured_at TIMESTAMP NOT NULL,
               symbol VARCHAR NOT NULL,
               exchange VARCHAR NOT NULL,
               expiry_date VARCHAR NOT NULL,
               strike DOUBLE NOT NULL,
               option_type VARCHAR NOT NULL,
               oi BIGINT DEFAULT 0,
               volume BIGINT DEFAULT 0,
               ltp DOUBLE DEFAULT 0.0,
               iv DOUBLE DEFAULT 0.0,
               PRIMARY KEY (symbol, expiry_date, strike, option_type, captured_at)
           )"""
    )
    connection.executemany(
        """INSERT INTO expired_option_chains
           (captured_at, symbol, exchange, expiry_date, strike, option_type, oi,
            volume, ltp, iv)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            ("2026-03-25 15:29:00", "NIFTY", "NFO", "26MAR26", 24000, "CE", 100, 50, 150, 12),
            ("2026-03-25 15:29:00", "NIFTY", "NFO", "26MAR26", 24000, "PE", 80, 40, 120, 13),
            ("2026-03-25 15:30:00", "NIFTY", "NFO", "26MAR26", 24100, "CE", 110, 60, 155, 12.5),
            ("2026-03-25 15:30:00", "NIFTY", "NFO", "26MAR26", 24100, "PE", 90, 45, 125, 13.5),
        ],
    )
    connection.close()

    tracker = ExpiryTracker(db_path=str(db_path))
    try:
        columns = {
            row[1]
            for row in tracker.connection.execute(
                "PRAGMA table_info('expired_option_chains')"
            ).fetchall()
        }
        migration = tracker.connection.execute(
            "SELECT name FROM _migrations WHERE name = ?",
            ["expired_option_chains_snapshot_id_v1"],
        ).fetchone()
        backfill_migration = tracker.connection.execute(
            "SELECT name FROM _migrations WHERE name = ?",
            ["expired_option_chains_snapshot_id_backfill_v2"],
        ).fetchone()
        snapshots = tracker.connection.execute(
            """SELECT captured_at, COUNT(DISTINCT snapshot_id), COUNT(*)
               FROM expired_option_chains
               GROUP BY captured_at
               ORDER BY captured_at"""
        ).fetchall()
        assert "snapshot_id" in columns
        assert migration == ("expired_option_chains_snapshot_id_v1",)
        assert backfill_migration == ("expired_option_chains_snapshot_id_backfill_v2",)
        assert snapshots == [
            (snapshots[0][0], 1, 2),
            (snapshots[1][0], 1, 2),
        ]
        assert len({row[0] for row in tracker.connection.execute(
            "SELECT DISTINCT snapshot_id FROM expired_option_chains"
        ).fetchall()}) == 2
        assert [row["strike"] for row in tracker.get_historical_chain("NIFTY", "2026-03-26")] == [24100, 24100]
    finally:
        tracker.close()


class TestDefaultDbPathMigration:
    """The default DB path resolves via ``workspace_dir()`` and copies a
    legacy ``~/.flinttrade/data/expiry_tracker.duckdb`` into the workspace
    (copy — never move; existing workspace files are never clobbered)."""

    _CHAIN = [
        {"strike_price": 24000, "call_oi": 100, "call_volume": 50,
         "call_ltp": 150, "call_iv": 12, "put_oi": 80, "put_volume": 40,
         "put_ltp": 120, "put_iv": 13},
    ]

    def _seed(self, db_path, expiry):
        """Create a tracker DB at ``db_path`` holding one snapshot."""
        from flinttrade_historical.expiry_tracker import ExpiryTracker

        client = MagicMock(spec=["optionchain"])
        client.optionchain.return_value = self._CHAIN
        tracker = ExpiryTracker(client=client, db_path=str(db_path))
        assert tracker.capture_snapshot("NIFTY", expiry) == 2
        tracker.close()

    def test_default_path_migrates_legacy_home_db(self, monkeypatch, tmp_path):
        import flinttrade_historical.expiry_tracker as et

        legacy_home = tmp_path / "legacy-home" / ".flinttrade" / "data"
        workspace = tmp_path / "workspace"
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
        monkeypatch.setattr(
            et, "_legacy_db_path", lambda: legacy_home / "expiry_tracker.duckdb"
        )

        legacy_home.mkdir(parents=True)
        self._seed(legacy_home / "expiry_tracker.duckdb", "260326")

        tracker = et.ExpiryTracker()  # no db_path — the workspace default
        try:
            assert tracker._db_path == str(workspace / "data" / "expiry_tracker.duckdb")
            assert (workspace / "data" / "expiry_tracker.duckdb").exists()
            # Copy, not move — the legacy file stays behind as a backup.
            assert (legacy_home / "expiry_tracker.duckdb").exists()
            assert tracker.list_expiries("NIFTY") == ["2026-03-26"]
        finally:
            tracker.close()

    def test_default_path_prefers_existing_workspace_db(self, monkeypatch, tmp_path):
        """No clobbering: an existing workspace DB wins over the legacy one."""
        import flinttrade_historical.expiry_tracker as et

        legacy_home = tmp_path / "legacy-home" / ".flinttrade" / "data"
        workspace = tmp_path / "workspace"
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
        monkeypatch.setattr(
            et, "_legacy_db_path", lambda: legacy_home / "expiry_tracker.duckdb"
        )

        legacy_home.mkdir(parents=True)
        self._seed(legacy_home / "expiry_tracker.duckdb", "260326")
        (workspace / "data").mkdir(parents=True)
        self._seed(workspace / "data" / "expiry_tracker.duckdb", "260402")

        tracker = et.ExpiryTracker()
        try:
            # The workspace snapshot, NOT the legacy one.
            assert tracker.list_expiries("NIFTY") == ["2026-04-02"]
        finally:
            tracker.close()

    def test_default_path_noop_when_paths_coincide(self, monkeypatch, tmp_path):
        """Linux: legacy and workspace paths are the same file — no self-copy."""
        import flinttrade_historical.expiry_tracker as et

        workspace = tmp_path / "workspace"
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
        (workspace / "data").mkdir(parents=True)
        self._seed(workspace / "data" / "expiry_tracker.duckdb", "260326")
        monkeypatch.setattr(
            et, "_legacy_db_path", lambda: workspace / "data" / "expiry_tracker.duckdb"
        )

        tracker = et.ExpiryTracker()
        try:
            assert tracker.list_expiries("NIFTY") == ["2026-03-26"]
        finally:
            tracker.close()

    @pytest.mark.unit
    def test_default_path_migrates_the_duckdb_wal_sidecar(self, monkeypatch, tmp_path):
        """The DuckDB ``.wal`` sidecar travels with the DB.

        The previous private ``shutil.copy2`` migration copied the DB file
        alone, so any uncheckpointed writes still sitting in the write-ahead
        log were silently dropped on first macOS/Windows boot. Resolution now
        goes through the shared workspace copy machinery, which moves the
        whole family.
        """
        import flinttrade_historical.expiry_tracker as et

        legacy_home = tmp_path / "legacy-home" / ".flinttrade" / "data"
        workspace = tmp_path / "workspace"
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
        monkeypatch.setattr(
            et, "_legacy_db_path", lambda: legacy_home / "expiry_tracker.duckdb"
        )

        legacy_home.mkdir(parents=True)
        self._seed(legacy_home / "expiry_tracker.duckdb", "260326")
        (legacy_home / "expiry_tracker.duckdb.wal").write_bytes(b"legacy-wal-bytes")

        # Resolve without opening: a synthetic WAL is not replayable by DuckDB.
        resolved = et._default_db_path()

        assert resolved == workspace / "data" / "expiry_tracker.duckdb"
        assert resolved.exists()
        assert (workspace / "data" / "expiry_tracker.duckdb.wal").read_bytes() == b"legacy-wal-bytes"
        # Copy, not move — the whole legacy family stays behind as a backup.
        assert (legacy_home / "expiry_tracker.duckdb").exists()
        assert (legacy_home / "expiry_tracker.duckdb.wal").exists()
