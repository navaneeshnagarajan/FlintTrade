"""Write-safety tests for the QuestDB client, bridge, and ingest route.

All tests use mocks. Do not run them against a live QuestDB instance.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

import flinttrade_data.questdb_routes as routes
from flinttrade_data.questdb_bridge import QuestDBBridge
from flinttrade_data.questdb_client import QuestDBClient
from flinttrade_data.questdb_config import (
    QuestDBWritesDisabledError,
    is_read_only_sql,
    resolve_allow_writes,
    writes_enabled_from_env,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _connected_client(**kwargs):
    kwargs.setdefault("allow_writes", False)
    client = QuestDBClient(**kwargs)
    mock_conn = MagicMock()
    mock_conn.closed = False
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    client._conn = mock_conn
    client._cursor = mock_cursor
    return client, mock_conn, mock_cursor


def _select_response() -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "columns": [{"name": "symbol"}, {"name": "ltp"}],
        "dataset": [["NIFTY", 22450.5]],
    }
    return mock_resp


# ---------------------------------------------------------------------------
# Setting / default
# ---------------------------------------------------------------------------


class TestWriteFlagDefaults:
    def test_default_constructor_is_read_only(self, monkeypatch):
        monkeypatch.delenv("QUESTDB_WRITE_ENABLED", raising=False)
        assert QuestDBBridge().allow_writes is False
        assert QuestDBClient().allow_writes is False

    def test_env_unset_or_falsey_is_disabled(self, monkeypatch):
        monkeypatch.delenv("QUESTDB_WRITE_ENABLED", raising=False)
        assert writes_enabled_from_env() is False
        for value in ("", "0", "false", "False", "no", "off", "maybe", "TRUE "):
            # "TRUE " with trailing space is truthy after strip; tested separately.
            if value.strip().lower() == "true":
                continue
            monkeypatch.setenv("QUESTDB_WRITE_ENABLED", value)
            assert writes_enabled_from_env() is False, value

    def test_env_truthy_enables_writes(self, monkeypatch):
        for value in ("1", "true", "TRUE", "Yes", "on", " true "):
            monkeypatch.setenv("QUESTDB_WRITE_ENABLED", value)
            assert writes_enabled_from_env() is True, value
            assert QuestDBClient().allow_writes is True
            assert QuestDBBridge().allow_writes is True

    def test_explicit_allow_writes_overrides_env(self, monkeypatch):
        monkeypatch.setenv("QUESTDB_WRITE_ENABLED", "true")
        assert resolve_allow_writes(False) is False
        assert QuestDBClient(allow_writes=False).allow_writes is False
        monkeypatch.setenv("QUESTDB_WRITE_ENABLED", "false")
        assert resolve_allow_writes(True) is True
        assert QuestDBClient(allow_writes=True).allow_writes is True

    def test_host_and_port_come_from_env_when_omitted(self, monkeypatch):
        monkeypatch.setenv("QUESTDB_HOST", "questdb.example")
        monkeypatch.setenv("QUESTDB_HTTP_PORT", "9100")
        monkeypatch.setenv("QUESTDB_ILP_PORT", "9109")
        monkeypatch.setenv("QUESTDB_PG_PORT", "9912")
        bridge = QuestDBBridge()
        client = QuestDBClient()
        assert bridge.host == "questdb.example"
        assert bridge.http_port == 9100
        assert bridge.ilp_port == 9109
        assert client.host == "questdb.example"
        assert client.port == 9912

    def test_explicit_host_and_port_override_env(self, monkeypatch):
        monkeypatch.setenv("QUESTDB_HOST", "questdb.example")
        monkeypatch.setenv("QUESTDB_HTTP_PORT", "9100")
        monkeypatch.setenv("QUESTDB_ILP_PORT", "9109")
        monkeypatch.setenv("QUESTDB_PG_PORT", "9912")
        bridge = QuestDBBridge(host="127.0.0.1", http_port=9000, ilp_port=9009)
        client = QuestDBClient(host="127.0.0.1", port=8812)
        assert bridge.host == "127.0.0.1"
        assert bridge.http_port == 9000
        assert bridge.ilp_port == 9009
        assert client.host == "127.0.0.1"
        assert client.port == 8812

    def test_invalid_port_env_raises(self, monkeypatch):
        monkeypatch.setenv("QUESTDB_HTTP_PORT", "not-a-port")
        with pytest.raises(ValueError, match="QUESTDB_HTTP_PORT"):
            QuestDBBridge()
        monkeypatch.setenv("QUESTDB_HTTP_PORT", "70000")
        with pytest.raises(ValueError, match="65535"):
            QuestDBBridge()


class TestReadOnlySql:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM ticks",
            "  select symbol, ltp from ticks limit 1",
            "SHOW TABLES",
            "EXPLAIN SELECT 1",
            "DESCRIBE ticks",
            "WITH x AS (SELECT 1 AS v) SELECT v FROM x",
            "SELECT 'INSERT' AS label FROM ticks",
            "-- comment\nSELECT 1",
            "/* INSERT INTO ticks */ SELECT 1",
        ],
    )
    def test_recognises_reads(self, sql):
        assert is_read_only_sql(sql) is True

    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT INTO ticks VALUES (1)",
            "CREATE TABLE IF NOT EXISTS ticks (ts TIMESTAMP)",
            "DROP TABLE ticks",
            "ALTER TABLE ticks ADD COLUMN x INT",
            "UPDATE ticks SET ltp = 1",
            "DELETE FROM ticks",
            "TRUNCATE TABLE ticks",
            "WITH x AS (SELECT 1 AS v) INSERT INTO ticks SELECT v FROM x",
            "INVALID SQL",
            "",
            "   ",
        ],
    )
    def test_rejects_writes_and_unknown(self, sql):
        assert is_read_only_sql(sql) is False


# ---------------------------------------------------------------------------
# Bridge write paths
# ---------------------------------------------------------------------------


class TestBridgeWriteGuard:
    def test_insert_ticks_refused_by_default(self):
        bridge = QuestDBBridge()
        with patch("flinttrade_data.questdb_bridge.socket.create_connection") as mock_conn:
            with pytest.raises(QuestDBWritesDisabledError, match="insert_ticks"):
                bridge.insert_ticks([{"symbol": "NIFTY", "exchange": "NFO", "ltp": 1.0}])
        mock_conn.assert_not_called()

    def test_insert_ticks_empty_list_still_refused_when_disabled(self):
        bridge = QuestDBBridge(allow_writes=False)
        with patch("flinttrade_data.questdb_bridge.socket.create_connection") as mock_conn:
            with pytest.raises(QuestDBWritesDisabledError):
                bridge.insert_ticks([])
        mock_conn.assert_not_called()

    def test_insert_ticks_works_when_enabled(self):
        bridge = QuestDBBridge(allow_writes=True)
        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        with patch("flinttrade_data.questdb_bridge.socket.create_connection", return_value=mock_sock):
            count = bridge.insert_ticks([{"symbol": "NIFTY", "exchange": "NFO", "ltp": 1.0}])
        assert count == 1
        mock_sock.sendall.assert_called_once()

    def test_write_sql_refused_when_disabled(self):
        bridge = QuestDBBridge()
        with patch.object(bridge._http, "get") as mock_get:
            with pytest.raises(QuestDBWritesDisabledError, match="query"):
                bridge.query("INSERT INTO ticks VALUES (1)")
        mock_get.assert_not_called()

    def test_write_sql_works_when_enabled(self):
        bridge = QuestDBBridge(allow_writes=True)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"columns": [], "dataset": []}
        with patch.object(bridge._http, "get", return_value=mock_resp) as mock_get:
            rows = bridge.query("INSERT INTO ticks VALUES (1)")
        assert rows == []
        mock_get.assert_called_once()

    @pytest.mark.parametrize("allow_writes", [False, True])
    def test_reads_work_in_both_modes(self, allow_writes):
        bridge = QuestDBBridge(allow_writes=allow_writes)
        mock_resp = _select_response()
        with patch.object(bridge._http, "get", return_value=mock_resp):
            rows = bridge.query("SELECT symbol, ltp FROM ticks")
            health = bridge.check_health()
        assert rows[0]["symbol"] == "NIFTY"
        assert health is True


# ---------------------------------------------------------------------------
# Client write paths
# ---------------------------------------------------------------------------


_CLIENT_WRITE_CASES = [
    ("create_tables", lambda c: c.create_tables()),
    ("insert_ltp", lambda c: c.insert_ltp("NIFTY", "NSE", 1.0)),
    ("insert_ltp_bulk", lambda c: c.insert_ltp_bulk([("NIFTY", "NSE", 1.0, None)])),
    ("insert_quote", lambda c: c.insert_quote("NIFTY", "NSE", 1.0, 1.0, 1.1, 1, 0)),
    (
        "insert_quote_bulk",
        lambda c: c.insert_quote_bulk([("NIFTY", "NSE", 1.0, 1.0, 1.1, 1, 0, None)]),
    ),
    ("insert_depth", lambda c: c.insert_depth("NIFTY", "NSE", 0, 1.0, 1, 1.1, 1)),
    (
        "insert_depth_bulk",
        lambda c: c.insert_depth_bulk([("NIFTY", "NSE", 0, 1.0, 1, 1.1, 1, None)]),
    ),
]


class TestClientWriteGuard:
    @pytest.mark.parametrize("operation,invoke", _CLIENT_WRITE_CASES)
    def test_each_write_path_is_refused_by_default(self, operation, invoke):
        client, mock_conn, mock_cursor = _connected_client()
        with pytest.raises(QuestDBWritesDisabledError, match=operation) as exc_info:
            invoke(client)
        assert isinstance(exc_info.value, Exception)
        mock_cursor.execute.assert_not_called()
        mock_conn.commit.assert_not_called()

    @pytest.mark.parametrize("operation,invoke", _CLIENT_WRITE_CASES)
    def test_each_write_path_works_when_enabled(self, operation, invoke):
        import sys

        client, mock_conn, mock_cursor = _connected_client(allow_writes=True)
        if operation.endswith("_bulk"):
            fake_pg2 = MagicMock()
            fake_extras = MagicMock()
            fake_pg2.extras = fake_extras
            with patch.dict(sys.modules, {"psycopg2": fake_pg2, "psycopg2.extras": fake_extras}):
                result = invoke(client)
            fake_extras.execute_values.assert_called_once()
            assert result == 1
            mock_conn.commit.assert_called()
        else:
            result = invoke(client)
            mock_cursor.execute.assert_called()
            mock_conn.commit.assert_called()
            if operation != "create_tables":
                assert result is True

    @pytest.mark.parametrize("allow_writes", [False, True])
    def test_reads_work_in_both_modes(self, allow_writes):
        client, _, mock_cursor = _connected_client(allow_writes=allow_writes)
        mock_cursor.fetchall.return_value = []
        bars = client.generate_candles("NIFTY", "NSE")
        assert bars == []
        mock_cursor.execute.assert_called()


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------


def _route_client(bridge) -> tuple[Flask, object]:
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    routes.init_questdb_routes(bridge)
    # The blueprint may already be registered on a previous app in this
    # process; bind a fresh app only when needed.
    try:
        flask_app.register_blueprint(routes.questdb_bp)
    except ValueError:
        pass
    return flask_app, flask_app.test_client()


class TestQuestDBRouteWriteGuard:
    def test_ticks_route_returns_403_when_writes_disabled(self):
        bridge = QuestDBBridge(allow_writes=False)
        flask_app, client = _route_client(bridge)
        with flask_app.app_context():
            with patch("flinttrade_data.questdb_bridge.socket.create_connection") as mock_conn:
                resp = client.post(
                    "/api/v1/data/questdb/ticks",
                    json={"ticks": [{"symbol": "NIFTY", "exchange": "NFO", "ltp": 1.0}]},
                )
        assert resp.status_code == 403
        body = resp.get_json()
        assert body["status"] == "error"
        assert "disabled" in body["message"].lower()
        mock_conn.assert_not_called()

    def test_ticks_route_inserts_when_writes_enabled(self):
        bridge = QuestDBBridge(allow_writes=True)
        flask_app, client = _route_client(bridge)
        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        with flask_app.app_context():
            with patch("flinttrade_data.questdb_bridge.socket.create_connection", return_value=mock_sock):
                resp = client.post(
                    "/api/v1/data/questdb/ticks",
                    json={"ticks": [{"symbol": "NIFTY", "exchange": "NFO", "ltp": 1.0}]},
                )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["inserted"] == 1

    def test_query_route_refuses_write_sql_when_disabled(self):
        bridge = QuestDBBridge(allow_writes=False)
        flask_app, client = _route_client(bridge)
        with flask_app.app_context():
            with patch.object(bridge._http, "get") as mock_get:
                resp = client.post(
                    "/api/v1/data/questdb/query",
                    json={"sql": "INSERT INTO ticks VALUES (1)"},
                )
        assert resp.status_code == 403
        mock_get.assert_not_called()

    @pytest.mark.parametrize("allow_writes", [False, True])
    def test_query_route_reads_work_in_both_modes(self, allow_writes):
        bridge = QuestDBBridge(allow_writes=allow_writes)
        flask_app, client = _route_client(bridge)
        with flask_app.app_context():
            with patch.object(bridge._http, "get", return_value=_select_response()):
                resp = client.post(
                    "/api/v1/data/questdb/query",
                    json={"sql": "SELECT symbol, ltp FROM ticks"},
                )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["count"] == 1
