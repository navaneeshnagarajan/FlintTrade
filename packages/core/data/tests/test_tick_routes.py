"""Tests for the tick-capture Flask routes (status / query / watchlist).

Uses a minimal Flask app with the blueprint and in-memory fakes — no
WebSocket, no real DuckDB file.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest
from flask import Flask

from flinttrade_data.storage import StorageManager
from flinttrade_data.tick_routes import ticks_bp

IST = timezone(timedelta(hours=5, minutes=30))


class _FakeRecorder:
    def __init__(self) -> None:
        self.is_running = True
        self.is_connected = True
        self.last_error = ""
        self.tick_count = 42
        self._watchlist: dict[str, list[dict[str, str]]] = {
            "quote": [{"exchange": "NSE_INDEX", "symbol": "NIFTY"}],
            "ltp": [],
            "depth": [],
        }

    def get_watchlist(self) -> dict[str, list[dict[str, str]]]:
        return {m: list(v) for m, v in self._watchlist.items()}

    def add_symbols(self, instruments: list[dict[str, str]], mode: str = "quote") -> None:
        if mode not in self._watchlist:
            raise ValueError(f"Invalid mode: {mode}")
        self._watchlist[mode].extend(instruments)

    def remove_symbols(self, instruments: list[dict[str, str]], mode: str = "quote") -> None:
        for inst in instruments:
            if inst in self._watchlist.get(mode, []):
                self._watchlist[mode].remove(inst)


@pytest.fixture()
def app():
    flask_app = Flask("test_ticks")
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(ticks_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def wired(app):
    """Wire a fake recorder + a real in-memory tick store with one row."""
    recorder = _FakeRecorder()
    storage = StorageManager(":memory:")
    storage.initialise()
    storage.insert_tick(
        datetime(2026, 7, 6, 10, 15, 0, tzinfo=IST),
        "NIFTY",
        "NSE_INDEX",
        "quote",
        ltp=24000.5,
        volume=1000,
    )
    app.config["TICK_RECORDER"] = recorder
    app.config["TICK_STORAGE"] = storage
    app.config["TICK_STORAGE_LOCK"] = threading.Lock()
    return recorder


class TestStatus:
    def test_disabled_when_no_recorder(self, client):
        resp = client.get("/api/v1/data/ticks/status")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["enabled"] is False
        assert data["running"] is False
        assert data["connected"] is False
        assert "hint" in data

    def test_configured_startup_failure_is_not_reported_as_off(self, client, app):
        app.config["TICK_CAPTURE_ENABLED"] = True
        app.config["TICK_CAPTURE_ERROR"] = "OpenAlgo rejected [redacted]"

        data = client.get("/api/v1/data/ticks/status").get_json()["data"]

        assert data["enabled"] is True
        assert data["running"] is False
        assert data["connected"] is False
        assert data["last_error"] == "OpenAlgo rejected [redacted]"
        assert "hint" not in data

    def test_enabled_reports_recorder_state(self, client, wired):
        resp = client.get("/api/v1/data/ticks/status")
        data = resp.get_json()["data"]
        assert data["enabled"] is True
        assert data["running"] is True
        assert data["connected"] is True
        assert data["tick_count"] == 42
        assert data["watchlist"]["quote"] == [{"exchange": "NSE_INDEX", "symbol": "NIFTY"}]
        assert "last_error" not in data

    def test_connected_and_sanitised_error_are_reported_when_reconnecting(self, client, wired):
        wired.is_connected = False
        wired.last_error = "OpenAlgo connection refused"

        data = client.get("/api/v1/data/ticks/status").get_json()["data"]

        assert data["running"] is True
        assert data["connected"] is False
        assert data["last_error"] == "OpenAlgo connection refused"

    def test_connected_control_error_is_reported(self, client, wired):
        wired.is_connected = True
        wired.last_error = "Partial subscription failure: NSE:BAD"

        data = client.get("/api/v1/data/ticks/status").get_json()["data"]

        assert data["running"] is True
        assert data["connected"] is True
        assert data["last_error"] == "Partial subscription failure: NSE:BAD"


class TestQuery:
    def test_409_when_capture_disabled(self, client):
        resp = client.get("/api/v1/data/ticks?symbol=NIFTY&exchange=NSE_INDEX&start=2026-07-06&end=2026-07-06")
        assert resp.status_code == 409

    def test_400_on_missing_params(self, client, wired):
        resp = client.get("/api/v1/data/ticks?symbol=NIFTY")
        assert resp.status_code == 400

    def test_returns_recorded_ticks(self, client, wired):
        resp = client.get(
            "/api/v1/data/ticks?symbol=NIFTY&exchange=NSE_INDEX&start=2026-07-06&end=2026-07-06"
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["count"] == 1
        assert data["truncated"] is False
        tick = data["ticks"][0]
        assert tick["symbol"] == "NIFTY"
        assert tick["ltp"] == 24000.5
        # Timestamp serialised JSON-safe.
        assert isinstance(tick["ts"], str)

    def test_limit_keeps_most_recent(self, client, app, wired):
        storage = app.config["TICK_STORAGE"]
        for i in range(5):
            storage.insert_tick(
                datetime(2026, 7, 6, 10, 16, i, tzinfo=IST),
                "NIFTY",
                "NSE_INDEX",
                "quote",
                ltp=24001.0 + i,
            )
        resp = client.get(
            "/api/v1/data/ticks?symbol=NIFTY&exchange=NSE_INDEX&start=2026-07-06&end=2026-07-06&limit=2"
        )
        data = resp.get_json()["data"]
        assert data["count"] == 2
        assert data["truncated"] is True
        # Most recent rows in the window survive truncation.
        assert data["ticks"][-1]["ltp"] == 24005.0


class TestWatchlist:
    def test_409_when_capture_disabled(self, client):
        resp = client.post("/api/v1/data/ticks/watchlist", json={
            "action": "add",
            "instruments": [{"exchange": "NSE", "symbol": "RELIANCE"}],
        })
        assert resp.status_code == 409

    def test_add_and_remove(self, client, wired):
        resp = client.post("/api/v1/data/ticks/watchlist", json={
            "action": "add",
            "instruments": [{"exchange": "NSE", "symbol": "reliance"}],
        })
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert {"exchange": "NSE", "symbol": "RELIANCE"} in data["watchlist"]["quote"]
        assert data["applies_on"] == "next WebSocket reconnect"

        resp = client.post("/api/v1/data/ticks/watchlist", json={
            "action": "remove",
            "instruments": [{"exchange": "NSE", "symbol": "RELIANCE"}],
        })
        data = resp.get_json()["data"]
        assert {"exchange": "NSE", "symbol": "RELIANCE"} not in data["watchlist"]["quote"]

    def test_400_on_bad_action_or_empty(self, client, wired):
        assert client.post("/api/v1/data/ticks/watchlist", json={"action": "bogus", "instruments": [{"exchange": "NSE", "symbol": "X"}]}).status_code == 400
        assert client.post("/api/v1/data/ticks/watchlist", json={"action": "add", "instruments": []}).status_code == 400

    def test_400_on_invalid_mode(self, client, wired):
        resp = client.post("/api/v1/data/ticks/watchlist", json={
            "action": "add",
            "mode": "bogus",
            "instruments": [{"exchange": "NSE", "symbol": "X"}],
        })
        assert resp.status_code == 400
