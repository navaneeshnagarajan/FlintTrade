"""Tests for QuestDBBridge — all tests use mocks, no live QuestDB instance.

DO NOT RUN against a real QuestDB. All network I/O is patched.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestQuestDBBridgeHealth:
    """check_health — returns True on 200, False on error or non-200."""

    def test_health_returns_true_when_questdb_responds_200(self):
        from flinttrade_data.questdb_bridge import QuestDBBridge

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        bridge = QuestDBBridge()
        with patch.object(bridge._http, "get", return_value=mock_resp):
            assert bridge.check_health() is True

    def test_health_returns_false_on_non_200(self):
        from flinttrade_data.questdb_bridge import QuestDBBridge

        mock_resp = MagicMock()
        mock_resp.status_code = 503

        bridge = QuestDBBridge()
        with patch.object(bridge._http, "get", return_value=mock_resp):
            assert bridge.check_health() is False

    def test_health_returns_false_on_exception(self):
        from flinttrade_data.questdb_bridge import QuestDBBridge

        bridge = QuestDBBridge()
        with patch.object(bridge._http, "get", side_effect=Exception("refused")):
            assert bridge.check_health() is False


class TestQuestDBBridgeInsertTicks:
    """insert_ticks — sends ILP lines over TCP."""

    def test_insert_ticks_returns_count_of_valid_ticks(self):
        from flinttrade_data.questdb_bridge import QuestDBBridge

        ticks = [
            {"symbol": "NIFTY", "exchange": "NFO", "ltp": 22450.5, "volume": 1000},
            {"symbol": "RELIANCE", "exchange": "NSE", "ltp": 2980.0},
        ]

        bridge = QuestDBBridge()
        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)

        with patch("flinttrade_data.questdb_bridge.socket.create_connection", return_value=mock_sock):
            count = bridge.insert_ticks(ticks)

        assert count == 2
        mock_sock.sendall.assert_called_once()
        payload = mock_sock.sendall.call_args[0][0].decode("utf-8")
        assert "NIFTY" in payload
        assert "RELIANCE" in payload

    def test_insert_ticks_skips_ticks_missing_required_fields(self):
        from flinttrade_data.questdb_bridge import QuestDBBridge

        ticks = [
            {"symbol": "NIFTY", "ltp": 22450.5},   # missing exchange → skipped
            {"exchange": "NSE", "ltp": 2980.0},      # missing symbol → skipped
            {"symbol": "TCS", "exchange": "NSE", "ltp": 3500.0},  # valid
        ]

        bridge = QuestDBBridge()
        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)

        with patch("flinttrade_data.questdb_bridge.socket.create_connection", return_value=mock_sock):
            count = bridge.insert_ticks(ticks)

        assert count == 1

    def test_insert_ticks_empty_list_returns_zero(self):
        from flinttrade_data.questdb_bridge import QuestDBBridge

        bridge = QuestDBBridge()
        with patch("flinttrade_data.questdb_bridge.socket.create_connection") as mock_conn:
            count = bridge.insert_ticks([])

        assert count == 0
        mock_conn.assert_not_called()

    def test_insert_ticks_raises_on_tcp_connection_failure(self):
        from flinttrade_data.questdb_bridge import QuestDBBridge, QuestDBBridgeError

        ticks = [{"symbol": "NIFTY", "exchange": "NFO", "ltp": 22450.0}]
        bridge = QuestDBBridge()

        with patch(
            "flinttrade_data.questdb_bridge.socket.create_connection",
            side_effect=OSError("connection refused"),
        ):
            try:
                bridge.insert_ticks(ticks)
                assert False, "Expected QuestDBBridgeError"
            except QuestDBBridgeError as exc:
                assert "connection refused" in str(exc)


class TestQuestDBBridgeQuery:
    """query — executes SQL via HTTP REST API."""

    def test_query_returns_list_of_row_dicts(self):
        from flinttrade_data.questdb_bridge import QuestDBBridge

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "columns": [{"name": "symbol"}, {"name": "ltp"}],
            "dataset": [["NIFTY", 22450.5], ["RELIANCE", 2980.0]],
        }

        bridge = QuestDBBridge()
        with patch.object(bridge._http, "get", return_value=mock_resp):
            rows = bridge.query("SELECT symbol, ltp FROM ticks LIMIT 2")

        assert len(rows) == 2
        assert rows[0] == {"symbol": "NIFTY", "ltp": 22450.5}
        assert rows[1] == {"symbol": "RELIANCE", "ltp": 2980.0}

    def test_query_raises_on_questdb_error_field(self):
        from flinttrade_data.questdb_bridge import QuestDBBridge, QuestDBBridgeError

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"error": "table 'ticks' does not exist"}

        bridge = QuestDBBridge()
        with patch.object(bridge._http, "get", return_value=mock_resp):
            try:
                bridge.query("SELECT * FROM ticks")
                assert False, "Expected QuestDBBridgeError"
            except QuestDBBridgeError as exc:
                assert "does not exist" in str(exc)

    def test_query_raises_on_non_200(self):
        from flinttrade_data.questdb_bridge import QuestDBBridge, QuestDBBridgeError

        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"

        bridge = QuestDBBridge()
        with patch.object(bridge._http, "get", return_value=mock_resp):
            try:
                bridge.query("INVALID SQL")
                assert False, "Expected QuestDBBridgeError"
            except QuestDBBridgeError as exc:
                assert "400" in str(exc)


class TestQuestDBBridgeAggregateOHLCV:
    """aggregate_ohlcv — builds SAMPLE BY query and returns OHLCV bars."""

    def test_aggregate_ohlcv_builds_correct_sql(self):
        from flinttrade_data.questdb_bridge import QuestDBBridge

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "columns": [
                {"name": "timestamp"}, {"name": "open"}, {"name": "high"},
                {"name": "low"}, {"name": "close"}, {"name": "volume"},
            ],
            "dataset": [["2026-04-08T09:15:00", 22400.0, 22500.0, 22350.0, 22450.0, 50000]],
        }

        bridge = QuestDBBridge()
        with patch.object(bridge._http, "get", return_value=mock_resp) as mock_get:
            bars = bridge.aggregate_ohlcv(
                "NIFTY", "5m",
                "2026-04-08T09:15:00", "2026-04-08T15:30:00",
            )

        assert len(bars) == 1
        assert bars[0]["open"] == 22400.0
        assert bars[0]["close"] == 22450.0

        called_sql = mock_get.call_args[1]["params"]["query"]
        assert "SAMPLE BY 5m" in called_sql
        assert "NIFTY" in called_sql
        assert "ALIGN TO CALENDAR" in called_sql


class TestQuestDBBridgeGetLatestTick:
    """get_latest_tick — returns most recent tick or None."""

    def test_get_latest_tick_returns_dict_when_data_exists(self):
        from flinttrade_data.questdb_bridge import QuestDBBridge

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "columns": [{"name": "symbol"}, {"name": "ltp"}, {"name": "timestamp"}],
            "dataset": [["NIFTY", 22450.5, "2026-04-08T15:29:59.999"]],
        }

        bridge = QuestDBBridge()
        with patch.object(bridge._http, "get", return_value=mock_resp):
            tick = bridge.get_latest_tick("NIFTY")

        assert tick is not None
        assert tick["symbol"] == "NIFTY"
        assert tick["ltp"] == 22450.5

    def test_get_latest_tick_returns_none_when_no_data(self):
        from flinttrade_data.questdb_bridge import QuestDBBridge

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "columns": [{"name": "symbol"}, {"name": "ltp"}],
            "dataset": [],
        }

        bridge = QuestDBBridge()
        with patch.object(bridge._http, "get", return_value=mock_resp):
            tick = bridge.get_latest_tick("UNKNOWNSYMBOL")

        assert tick is None


class TestQuestDBBridgeConnectionError:
    """Connection-level failure handling."""

    def test_query_raises_questdb_bridge_error_on_network_failure(self):
        from flinttrade_data.questdb_bridge import QuestDBBridge, QuestDBBridgeError

        bridge = QuestDBBridge()
        with patch.object(bridge._http, "get", side_effect=OSError("timeout")):
            try:
                bridge.query("SELECT 1")
                assert False, "Expected QuestDBBridgeError"
            except QuestDBBridgeError as exc:
                assert "timeout" in str(exc)
