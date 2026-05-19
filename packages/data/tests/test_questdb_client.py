"""Tests for QuestDBClient — PostgreSQL wire protocol interface.

All tests use mocks. No live QuestDB instance required.
psycopg2 is mocked at the module level so the tests run even when the
optional driver is not installed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(**kwargs: Any):
    """Return a QuestDBClient with psycopg2 patched out."""
    from packages.data.src.questdb_client import QuestDBClient

    client = QuestDBClient(**kwargs)
    # Inject a mock connection/cursor directly so we never touch the network.
    mock_conn = MagicMock()
    mock_conn.closed = False
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    client._conn = mock_conn
    client._cursor = mock_cursor
    return client, mock_conn, mock_cursor


# ---------------------------------------------------------------------------
# Module-level graceful import
# ---------------------------------------------------------------------------


class TestGracefulImport:
    def test_module_imports_without_psycopg2(self):
        """Module must import cleanly even when psycopg2 is absent."""
        import importlib
        import sys

        # Temporarily hide psycopg2 from sys.modules
        saved = sys.modules.pop("psycopg2", None)
        saved_extras = sys.modules.pop("psycopg2.extras", None)
        mod_key = "packages.data.src.questdb_client"
        saved_mod = sys.modules.pop(mod_key, None)

        try:
            with patch.dict(sys.modules, {"psycopg2": None, "psycopg2.extras": None}):
                mod = importlib.import_module(mod_key)
                assert not mod._PSYCOPG2_AVAILABLE
        finally:
            # Restore everything
            if saved is not None:
                sys.modules["psycopg2"] = saved
            if saved_extras is not None:
                sys.modules["psycopg2.extras"] = saved_extras
            if saved_mod is not None:
                sys.modules[mod_key] = saved_mod


class TestConnectWithoutPsycopg2:
    def test_connect_raises_when_psycopg2_missing(self):
        import importlib
        import sys

        mod_key = "packages.data.src.questdb_client"
        # Import directly, bypassing __init__.py (which pulls in duckdb)
        if mod_key not in sys.modules:
            import importlib.util
            import os

            path = os.path.join(
                os.path.dirname(__file__), "..", "src", "questdb_client.py"
            )
            spec = importlib.util.spec_from_file_location(mod_key, path)
            mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
            sys.modules[mod_key] = mod
            spec.loader.exec_module(mod)  # type: ignore[union-attr]

        from packages.data.src.questdb_client import QuestDBClient, QuestDBClientError

        client = QuestDBClient()
        with patch("packages.data.src.questdb_client._PSYCOPG2_AVAILABLE", False):
            try:
                client.connect()
                assert False, "Expected QuestDBClientError"
            except QuestDBClientError as exc:
                assert "psycopg2" in str(exc).lower()


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------


class TestIsConnected:
    def test_is_connected_true_when_conn_open(self):
        client, mock_conn, _ = _make_client()
        assert client.is_connected() is True

    def test_is_connected_false_when_conn_none(self):
        from packages.data.src.questdb_client import QuestDBClient

        client = QuestDBClient()
        assert client.is_connected() is False

    def test_is_connected_false_when_conn_closed(self):
        client, mock_conn, _ = _make_client()
        mock_conn.closed = True
        assert client.is_connected() is False


class TestClose:
    def test_close_sets_conn_to_none(self):
        client, _, _ = _make_client()
        client.close()
        assert client._conn is None
        assert client._cursor is None


class TestRequireConnection:
    def test_require_connection_raises_when_not_connected(self):
        from packages.data.src.questdb_client import QuestDBClient, QuestDBClientError

        client = QuestDBClient()
        try:
            client._require_connection()
            assert False, "Expected QuestDBClientError"
        except QuestDBClientError as exc:
            assert "connect" in str(exc).lower()


# ---------------------------------------------------------------------------
# create_tables
# ---------------------------------------------------------------------------


class TestCreateTables:
    def test_create_tables_executes_three_ddl_statements(self):
        client, mock_conn, mock_cursor = _make_client()
        client.create_tables()
        # Three DDL statements → three execute calls
        assert mock_cursor.execute.call_count == 3
        # All three table names appear in the executed SQL
        all_sql = " ".join(
            str(call.args[0]) for call in mock_cursor.execute.call_args_list
        )
        assert "ticks_ltp" in all_sql
        assert "ticks_quote" in all_sql
        assert "ticks_depth" in all_sql

    def test_create_tables_commits_after_each_ddl(self):
        client, mock_conn, mock_cursor = _make_client()
        client.create_tables()
        assert mock_conn.commit.call_count == 3

    def test_create_tables_raises_and_rolls_back_on_failure(self):
        from packages.data.src.questdb_client import QuestDBClientError

        client, mock_conn, mock_cursor = _make_client()
        mock_cursor.execute.side_effect = Exception("syntax error")
        try:
            client.create_tables()
            assert False, "Expected QuestDBClientError"
        except QuestDBClientError as exc:
            assert "syntax error" in str(exc)
        mock_conn.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# insert_ltp
# ---------------------------------------------------------------------------


class TestInsertLtp:
    def test_insert_ltp_returns_true_on_success(self):
        client, mock_conn, mock_cursor = _make_client()
        result = client.insert_ltp("NIFTY", "NSE_INDEX", 24500.0)
        assert result is True
        mock_cursor.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    def test_insert_ltp_uses_provided_timestamp(self):
        client, _, mock_cursor = _make_client()
        ts = datetime(2026, 4, 13, 9, 15, 0)
        client.insert_ltp("NIFTY", "NSE_INDEX", 24500.0, timestamp=ts)
        args = mock_cursor.execute.call_args[0][1]
        assert args[0] == ts  # first param is timestamp (naive)

    def test_insert_ltp_defaults_timestamp_to_utcnow(self):
        client, _, mock_cursor = _make_client()
        # datetime.utcnow() is deprecated in 3.12+; the production code now uses
        # `datetime.now(timezone.utc).replace(tzinfo=None)` to keep the naive-UTC
        # contract — mirror that here so the bracketing assertion is exact.
        before = datetime.now(timezone.utc).replace(tzinfo=None)
        client.insert_ltp("RELIANCE", "NSE", 2985.5)
        after = datetime.now(timezone.utc).replace(tzinfo=None)
        ts = mock_cursor.execute.call_args[0][1][0]
        assert isinstance(ts, datetime)
        assert before <= ts <= after

    def test_insert_ltp_returns_false_on_db_error(self):
        client, mock_conn, mock_cursor = _make_client()
        mock_cursor.execute.side_effect = Exception("disk full")
        result = client.insert_ltp("NIFTY", "NSE_INDEX", 24500.0)
        assert result is False
        mock_conn.rollback.assert_called_once()

    def test_insert_ltp_strips_tzinfo_from_aware_timestamp(self):
        client, _, mock_cursor = _make_client()
        aware_ts = datetime(2026, 4, 13, 9, 15, 0, tzinfo=timezone.utc)
        client.insert_ltp("NIFTY", "NSE_INDEX", 24500.0, timestamp=aware_ts)
        ts = mock_cursor.execute.call_args[0][1][0]
        assert ts.tzinfo is None  # must be naive


# ---------------------------------------------------------------------------
# insert_ltp_bulk
# ---------------------------------------------------------------------------


class TestInsertLtpBulk:
    def test_insert_ltp_bulk_returns_row_count(self):
        import sys

        client, mock_conn, mock_cursor = _make_client()
        rows = [
            ("NIFTY", "NSE_INDEX", 24500.0, None),
            ("RELIANCE", "NSE", 2985.5, None),
        ]
        # Inject a fake psycopg2.extras so the `import psycopg2.extras` inside
        # insert_ltp_bulk succeeds even when the real driver is not installed.
        fake_pg2 = MagicMock()
        fake_extras = MagicMock()
        fake_pg2.extras = fake_extras
        fake_extras.execute_values = MagicMock()
        with patch.dict(sys.modules, {"psycopg2": fake_pg2, "psycopg2.extras": fake_extras}):
            result = client.insert_ltp_bulk(rows)
        assert result == 2
        mock_conn.commit.assert_called()

    def test_insert_ltp_bulk_empty_returns_zero(self):
        client, _, _ = _make_client()
        result = client.insert_ltp_bulk([])
        assert result == 0


# ---------------------------------------------------------------------------
# insert_quote
# ---------------------------------------------------------------------------


class TestInsertQuote:
    def test_insert_quote_returns_true_on_success(self):
        client, mock_conn, mock_cursor = _make_client()
        result = client.insert_quote(
            "RELIANCE", "NSE", 2985.0, 2984.5, 2985.5, 1200, 0
        )
        assert result is True
        mock_cursor.execute.assert_called_once()

    def test_insert_quote_returns_false_on_error(self):
        client, mock_conn, mock_cursor = _make_client()
        mock_cursor.execute.side_effect = Exception("constraint")
        result = client.insert_quote(
            "RELIANCE", "NSE", 2985.0, 2984.5, 2985.5, 1200, 0
        )
        assert result is False
        mock_conn.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# insert_depth
# ---------------------------------------------------------------------------


class TestInsertDepth:
    def test_insert_depth_returns_true_on_success(self):
        client, mock_conn, mock_cursor = _make_client()
        result = client.insert_depth(
            "NIFTY", "NSE_INDEX", 0, 24498.0, 50, 24501.0, 60
        )
        assert result is True
        mock_cursor.execute.assert_called_once()

    def test_insert_depth_returns_false_on_error(self):
        client, mock_conn, mock_cursor = _make_client()
        mock_cursor.execute.side_effect = Exception("table missing")
        result = client.insert_depth(
            "NIFTY", "NSE_INDEX", 0, 24498.0, 50, 24501.0, 60
        )
        assert result is False
        mock_conn.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# generate_candles
# ---------------------------------------------------------------------------


class TestGenerateCandles:
    def _stub_cursor_with_rows(self, mock_cursor: MagicMock) -> None:
        mock_cursor.fetchall.return_value = [
            (datetime(2026, 4, 13, 9, 15), 24400.0, 24500.0, 24350.0, 24450.0, 150),
            (datetime(2026, 4, 13, 9, 20), 24450.0, 24520.0, 24420.0, 24510.0, 120),
        ]

    def test_generate_candles_returns_ohlcv_list(self):
        from packages.data.src.questdb_client import OHLCV

        client, _, mock_cursor = _make_client()
        self._stub_cursor_with_rows(mock_cursor)
        result = client.generate_candles(
            "NIFTY", "NSE_INDEX",
            start=datetime(2026, 4, 13, 9, 15),
            end=datetime(2026, 4, 13, 15, 30),
        )
        assert len(result) == 2
        assert all(isinstance(r, OHLCV) for r in result)
        assert result[0].open == 24400.0
        assert result[0].close == 24450.0
        assert result[0].volume == 150

    def test_generate_candles_default_interval_is_1m(self):
        client, _, mock_cursor = _make_client()
        mock_cursor.fetchall.return_value = []
        client.generate_candles("NIFTY", "NSE_INDEX")
        sql = mock_cursor.execute.call_args[0][0]
        assert "minute" in sql

    def test_generate_candles_1h_interval_uses_hour_trunc(self):
        client, _, mock_cursor = _make_client()
        mock_cursor.fetchall.return_value = []
        client.generate_candles("NIFTY", "NSE_INDEX", interval="1h")
        sql = mock_cursor.execute.call_args[0][0]
        assert "hour" in sql

    def test_generate_candles_raises_on_bad_interval(self):
        from packages.data.src.questdb_client import QuestDBClientError

        client, _, _ = _make_client()
        try:
            client.generate_candles("NIFTY", "NSE_INDEX", interval="99x")
            assert False, "Expected QuestDBClientError"
        except QuestDBClientError as exc:
            assert "99x" in str(exc)

    def test_generate_candles_raises_on_query_failure(self):
        from packages.data.src.questdb_client import QuestDBClientError

        client, _, mock_cursor = _make_client()
        mock_cursor.execute.side_effect = Exception("table not found")
        try:
            client.generate_candles("NIFTY", "NSE_INDEX")
            assert False, "Expected QuestDBClientError"
        except QuestDBClientError as exc:
            assert "table not found" in str(exc)

    def test_generate_candles_accepts_iso_string_dates(self):
        client, _, mock_cursor = _make_client()
        mock_cursor.fetchall.return_value = []
        # Should not raise
        client.generate_candles(
            "NIFTY", "NSE_INDEX",
            start="2026-04-13T09:15:00",
            end="2026-04-13T15:30:00",
        )
        mock_cursor.execute.assert_called_once()


# ---------------------------------------------------------------------------
# get_market_stats
# ---------------------------------------------------------------------------


class TestGetMarketStats:
    def test_get_market_stats_returns_market_stats_dataclass(self):
        from packages.data.src.questdb_client import MarketStats

        client, _, mock_cursor = _make_client()
        mock_cursor.fetchone.return_value = (
            24500.0,  # current_price
            24800.0,  # high_24h
            24200.0,  # low_24h
            0.25,     # change_pct_1h
            1.5,      # change_pct_24h
            4200,     # trade_count
        )
        result = client.get_market_stats("NIFTY", "NSE_INDEX")
        assert isinstance(result, MarketStats)
        assert result.symbol == "NIFTY"
        assert result.exchange == "NSE_INDEX"
        assert result.current_price == 24500.0
        assert result.high_24h == 24800.0
        assert result.low_24h == 24200.0
        assert abs(result.change_pct_1h - 0.25) < 1e-9
        assert abs(result.change_pct_24h - 1.5) < 1e-9
        assert result.trade_count == 4200

    def test_get_market_stats_returns_zeros_when_no_data(self):
        from packages.data.src.questdb_client import MarketStats

        client, _, mock_cursor = _make_client()
        mock_cursor.fetchone.return_value = None
        result = client.get_market_stats("UNKNOWN", "NSE")
        assert isinstance(result, MarketStats)
        assert result.current_price == 0.0
        assert result.trade_count == 0

    def test_get_market_stats_raises_on_query_failure(self):
        from packages.data.src.questdb_client import QuestDBClientError

        client, _, mock_cursor = _make_client()
        mock_cursor.execute.side_effect = Exception("connection reset")
        try:
            client.get_market_stats("NIFTY", "NSE_INDEX")
            assert False, "Expected QuestDBClientError"
        except QuestDBClientError as exc:
            assert "connection reset" in str(exc)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestCoerceTs:
    def test_none_returns_utcnow(self):
        from packages.data.src.questdb_client import _coerce_ts

        # Match the new naive-UTC pattern the production helper now uses.
        before = datetime.now(timezone.utc).replace(tzinfo=None)
        result = _coerce_ts(None)
        after = datetime.now(timezone.utc).replace(tzinfo=None)
        assert result.tzinfo is None
        assert before <= result <= after

    def test_naive_datetime_passes_through(self):
        from packages.data.src.questdb_client import _coerce_ts

        naive = datetime(2026, 4, 13, 9, 15, 0)
        assert _coerce_ts(naive) == naive

    def test_aware_datetime_stripped_to_naive_utc(self):
        from packages.data.src.questdb_client import _coerce_ts

        aware = datetime(2026, 4, 13, 9, 15, 0, tzinfo=timezone.utc)
        result = _coerce_ts(aware)
        assert result.tzinfo is None
        assert result == datetime(2026, 4, 13, 9, 15, 0)


class TestIntervalToTruncUnit:
    def test_known_intervals(self):
        from packages.data.src.questdb_client import _interval_to_trunc_unit

        assert _interval_to_trunc_unit("1m") == "minute"
        assert _interval_to_trunc_unit("1h") == "hour"
        assert _interval_to_trunc_unit("1d") == "day"

    def test_unknown_interval_raises(self):
        from packages.data.src.questdb_client import (
            QuestDBClientError,
            _interval_to_trunc_unit,
        )

        try:
            _interval_to_trunc_unit("42w")
            assert False, "Expected QuestDBClientError"
        except QuestDBClientError:
            pass


class TestParseTsArg:
    def test_parses_iso_string(self):
        from packages.data.src.questdb_client import _parse_ts_arg

        result = _parse_ts_arg("2026-04-13T09:15:00")
        assert isinstance(result, datetime)
        assert result.year == 2026

    def test_raises_on_invalid_string(self):
        from packages.data.src.questdb_client import QuestDBClientError, _parse_ts_arg

        try:
            _parse_ts_arg("not-a-date")
            assert False, "Expected QuestDBClientError"
        except QuestDBClientError:
            pass

    def test_accepts_datetime_directly(self):
        from packages.data.src.questdb_client import _parse_ts_arg

        dt = datetime(2026, 4, 13, 9, 15)
        assert _parse_ts_arg(dt) == dt
