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
        self.persisted_tick_count = 40
        self.pending_tick_count = 2
        self.dropped_tick_count = 3
        self.reconnect_requests = 0
        self._subscription_lock = threading.RLock()
        self._watchlist: dict[str, list[dict[str, str]]] = {
            "quote": [{"exchange": "NSE_INDEX", "symbol": "NIFTY"}],
            "ltp": [],
            "depth": [],
        }

    @property
    def subscription_lock(self):
        return self._subscription_lock

    def status_snapshot(self) -> dict[str, object]:
        return {
            "running": self.is_running,
            "connected": self.is_connected,
            "tick_count": self.tick_count,
            "persisted_tick_count": self.persisted_tick_count,
            "pending_tick_count": self.pending_tick_count,
            "dropped_tick_count": self.dropped_tick_count,
            "last_error": self.last_error,
            "transport_error": self.last_error,
            "persistence_error": "",
        }

    def get_watchlist(self) -> dict[str, list[dict[str, str]]]:
        with self._subscription_lock:
            return {mode: [dict(instrument) for instrument in instruments] for mode, instruments in self._watchlist.items()}

    def add_symbols(self, instruments: list[dict[str, str]], mode: str = "quote") -> None:
        with self._subscription_lock:
            if mode not in self._watchlist:
                raise ValueError(f"Invalid mode: {mode}")
            for instrument in instruments:
                if instrument not in self._watchlist[mode]:
                    self._watchlist[mode].append(dict(instrument))

    def remove_symbols(self, instruments: list[dict[str, str]], mode: str = "quote") -> None:
        with self._subscription_lock:
            for inst in instruments:
                if inst in self._watchlist.get(mode, []):
                    self._watchlist[mode].remove(inst)

    def replace_watchlist(self, watchlist: dict[str, list[dict[str, str]]]) -> None:
        with self._subscription_lock:
            self._watchlist = {
                mode: [dict(instrument) for instrument in instruments]
                for mode, instruments in watchlist.items()
            }

    def request_reconnect(self) -> bool:
        self.reconnect_requests += 1
        return True


class _FakeSignalHub:
    def __init__(self) -> None:
        self.instruments: list[str] = []
        self.update_calls = 0

    def update_config(self, *, instruments: list[str]) -> None:
        self.update_calls += 1
        self.instruments = instruments


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
    app.config["TICK_CAPTURE_LIFECYCLE_LOCK"] = threading.RLock()
    app.config["SIGNAL_HUB"] = _FakeSignalHub()
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
        assert data["persisted_tick_count"] == 40
        assert data["pending_tick_count"] == 2
        assert data["dropped_tick_count"] == 3
        assert data["watchlist"]["quote"] == [{"exchange": "NSE_INDEX", "symbol": "NIFTY"}]
        assert "last_error" not in data

    def test_active_recorder_surfaces_hot_reload_integration_failure(self, client, app, wired):
        app.config["TICK_CAPTURE_ERROR"] = "connection reload failed"

        data = client.get("/api/v1/data/ticks/status").get_json()["data"]

        assert data["running"] is True
        assert data["connected"] is True
        assert data["last_error"] == "connection reload failed"
        assert data["integration_error"] == "connection reload failed"

    def test_enabled_consumes_one_recorder_owned_status_snapshot(self, client, app):
        class SnapshotOnlyRecorder:
            def status_snapshot(self):
                return {
                    "running": True,
                    "connected": False,
                    "tick_count": 12,
                    "persisted_tick_count": 7,
                    "pending_tick_count": 3,
                    "dropped_tick_count": 2,
                    "last_error": "offline",
                    "transport_error": "offline",
                    "persistence_error": "",
                }

            def get_watchlist(self):
                return {"ltp": [], "quote": [], "depth": []}

            @property
            def tick_count(self):
                raise AssertionError("route must not assemble status from independent properties")

        app.config["TICK_RECORDER"] = SnapshotOnlyRecorder()

        data = client.get("/api/v1/data/ticks/status").get_json()["data"]

        assert data["tick_count"] == 12
        assert data["persisted_tick_count"] == 7
        assert data["pending_tick_count"] == 3
        assert data["dropped_tick_count"] == 2
        assert data["last_error"] == "offline"

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
        resp = client.get("/api/v1/data/ticks?symbol=NIFTY&exchange=NSE_INDEX&start=2026-07-06&end=2026-07-06")
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
        resp = client.get("/api/v1/data/ticks?symbol=NIFTY&exchange=NSE_INDEX&start=2026-07-06&end=2026-07-06&limit=2")
        data = resp.get_json()["data"]
        assert data["count"] == 2
        assert data["truncated"] is True
        # Most recent rows in the window survive truncation.
        assert data["ticks"][-1]["ltp"] == 24005.0

    def test_limit_is_applied_by_storage_with_one_bounded_truncation_sentinel(self, client, app):
        class LimitAwareStorage:
            def __init__(self) -> None:
                self.requested_limit: int | None = None
                self.rows = [{"ts": index, "ltp": float(index)} for index in range(5)]

            def get_ticks(self, _symbol, _exchange, _start, _end, *, limit=None):
                self.requested_limit = limit
                return self.rows if limit is None else self.rows[-limit:]

        storage = LimitAwareStorage()
        app.config["TICK_STORAGE"] = storage
        app.config["TICK_STORAGE_LOCK"] = threading.Lock()

        resp = client.get(
            "/api/v1/data/ticks?symbol=NIFTY&exchange=NSE_INDEX&start=2026-07-06&end=2026-07-06&limit=2"
        )

        assert resp.status_code == 200
        assert storage.requested_limit == 3
        data = resp.get_json()["data"]
        assert data["truncated"] is True
        assert [tick["ltp"] for tick in data["ticks"]] == [3.0, 4.0]


class TestWatchlist:
    def test_409_when_capture_disabled(self, client):
        resp = client.post(
            "/api/v1/data/ticks/watchlist",
            json={
            "action": "add",
            "instruments": [{"exchange": "NSE", "symbol": "RELIANCE"}],
            },
        )
        assert resp.status_code == 409

    def test_add_and_remove(self, client, wired):
        resp = client.post(
            "/api/v1/data/ticks/watchlist",
            json={
            "action": "add",
            "instruments": [{"exchange": "NSE", "symbol": "reliance"}],
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert {"exchange": "NSE", "symbol": "RELIANCE"} in data["watchlist"]["quote"]
        assert data["applies_on"] == "reconnect requested"
        assert data["reconnect_requested"] is True

        resp = client.post(
            "/api/v1/data/ticks/watchlist",
            json={
            "action": "remove",
            "instruments": [{"exchange": "NSE", "symbol": "RELIANCE"}],
            },
        )
        data = resp.get_json()["data"]
        assert {"exchange": "NSE", "symbol": "RELIANCE"} not in data["watchlist"]["quote"]

    def test_rejects_non_object_json(self, client, app, wired):
        app.config["PROPAGATE_EXCEPTIONS"] = False

        resp = client.post("/api/v1/data/ticks/watchlist", json=["not", "an", "object"])

        assert resp.status_code == 400
        assert resp.get_json()["message"] == "request body must be a JSON object"

    @pytest.mark.parametrize("instruments", [None, {}, "NSE:RELIANCE"])
    def test_rejects_non_list_instruments(self, client, wired, instruments):
        resp = client.post(
            "/api/v1/data/ticks/watchlist",
            json={"action": "add", "instruments": instruments},
        )

        assert resp.status_code == 400
        assert resp.get_json()["message"] == "instruments must be a non-empty list"

    def test_rejects_non_object_instrument_entries_without_partial_mutation(self, client, wired):
        previous = wired.get_watchlist()

        resp = client.post(
            "/api/v1/data/ticks/watchlist",
            json={
                "action": "add",
                "instruments": [
                    {"exchange": "NSE", "symbol": "RELIANCE"},
                    "NSE:TCS",
                ],
            },
        )

        assert resp.status_code == 400
        assert resp.get_json()["message"] == "each instrument must be a JSON object"
        assert wired.get_watchlist() == previous

    @pytest.mark.parametrize(
        "instrument",
        [
            {"exchange": None, "symbol": "RELIANCE"},
            {"exchange": 123, "symbol": "RELIANCE"},
            {"exchange": "   ", "symbol": "RELIANCE"},
            {"exchange": "N:SE", "symbol": "RELIANCE"},
            {"exchange": "NSE", "symbol": None},
            {"exchange": "NSE", "symbol": 123},
            {"exchange": "NSE", "symbol": "   "},
            {"exchange": "NSE", "symbol": "REL:IANCE"},
        ],
    )
    def test_rejects_invalid_instrument_identities_without_coercion(self, client, wired, instrument):
        previous = wired.get_watchlist()

        resp = client.post(
            "/api/v1/data/ticks/watchlist",
            json={"action": "add", "instruments": [instrument]},
        )

        assert resp.status_code == 400
        assert resp.get_json()["message"] == (
            "instrument exchange and symbol must be non-empty strings without ':'"
        )
        assert wired.get_watchlist() == previous

    def test_lifecycle_lock_is_acquired_before_resolving_the_active_recorder(self, client, app, wired):
        retired = wired
        active = _FakeRecorder()

        class SwapRecorderOnEnter:
            entered = False

            def __enter__(self):
                self.entered = True
                app.config["TICK_RECORDER"] = active
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

        lifecycle_lock = SwapRecorderOnEnter()
        app.config["TICK_CAPTURE_LIFECYCLE_LOCK"] = lifecycle_lock

        resp = client.post(
            "/api/v1/data/ticks/watchlist",
            json={
                "action": "add",
                "instruments": [{"exchange": "NSE", "symbol": "RELIANCE"}],
            },
        )

        assert resp.status_code == 200
        assert lifecycle_lock.entered is True
        instrument = {"exchange": "NSE", "symbol": "RELIANCE"}
        assert instrument in active.get_watchlist()["quote"]
        assert instrument not in retired.get_watchlist()["quote"]

    def test_watchlist_update_synchronises_signal_allowlist_and_reconnects(self, client, app, wired):
        class SignalHub:
            def __init__(self) -> None:
                self.instruments: list[str] = []

            def update_config(self, *, instruments: list[str]) -> None:
                self.instruments = instruments

        hub = SignalHub()
        app.config["SIGNAL_HUB"] = hub

        resp = client.post(
            "/api/v1/data/ticks/watchlist",
            json={
                "action": "add",
                "mode": "quote",
                "instruments": [{"exchange": "nse", "symbol": "reliance"}],
            },
        )

        assert resp.status_code == 200
        assert hub.instruments == ["NSE:RELIANCE", "NSE_INDEX:NIFTY"]
        assert wired.reconnect_requests == 1

        resp = client.post(
            "/api/v1/data/ticks/watchlist",
            json={
                "action": "remove",
                "mode": "quote",
                "instruments": [{"exchange": "NSE_INDEX", "symbol": "NIFTY"}],
            },
        )

        assert resp.status_code == 200
        assert hub.instruments == ["NSE:RELIANCE"]
        assert wired.reconnect_requests == 2

    def test_idempotent_watchlist_update_skips_signal_reset_and_reconnect(self, client, app, wired):
        hub = app.config["SIGNAL_HUB"]

        response = client.post(
            "/api/v1/data/ticks/watchlist",
            json={
                "action": "add",
                "mode": "quote",
                "instruments": [{"exchange": "NSE_INDEX", "symbol": "NIFTY"}],
            },
        )

        assert response.status_code == 200
        assert response.get_json()["data"]["changed"] is False
        assert response.get_json()["data"]["applies_on"] == "unchanged"
        assert hub.update_calls == 0
        assert wired.reconnect_requests == 0

    def test_signal_allowlist_failure_restores_exact_recorder_snapshot_without_hub_compensation(
        self, client, app, wired
    ):
        previous = wired.get_watchlist()
        observed_watchlists: list[dict[str, list[dict[str, str]]]] = []

        class FailingHub:
            def __init__(self) -> None:
                self.update_calls = 0

            def update_config(self, *, instruments: list[str]) -> None:
                self.update_calls += 1
                observed_watchlists.append(wired.get_watchlist())
                raise ValueError("invalid candidate")

        hub = FailingHub()
        app.config["SIGNAL_HUB"] = hub

        resp = client.post(
            "/api/v1/data/ticks/watchlist",
            json={
                "action": "add",
                "instruments": [{"exchange": "NSE", "symbol": "RELIANCE"}],
            },
        )

        assert resp.status_code == 500
        assert {"exchange": "NSE", "symbol": "RELIANCE"} in observed_watchlists[0]["quote"]
        assert wired.get_watchlist() == previous
        assert hub.update_calls == 1
        assert wired.reconnect_requests == 0

    def test_concurrent_adds_produce_exact_union_in_recorder_and_signal_hub(self, app, wired):
        first_entered = threading.Event()
        second_entered = threading.Event()

        class RacingHub:
            def __init__(self) -> None:
                self._call_lock = threading.Lock()
                self.calls = 0
                self.instruments: list[str] = []

            def update_config(self, *, instruments: list[str]) -> None:
                with self._call_lock:
                    call_index = self.calls
                    self.calls += 1
                if call_index == 0:
                    first_entered.set()
                    second_entered.wait(timeout=0.2)
                else:
                    second_entered.set()
                self.instruments = list(instruments)

        hub = RacingHub()
        app.config["SIGNAL_HUB"] = hub
        responses: list[int] = []

        def add(symbol: str) -> None:
            with app.test_client() as thread_client:
                response = thread_client.post(
                    "/api/v1/data/ticks/watchlist",
                    json={
                        "action": "add",
                        "mode": "quote",
                        "instruments": [{"exchange": "NSE", "symbol": symbol}],
                    },
                )
                responses.append(response.status_code)

        first = threading.Thread(target=add, args=("RELIANCE",))
        second = threading.Thread(target=add, args=("TCS",))
        first.start()
        assert first_entered.wait(timeout=0.2)
        second.start()
        first.join(timeout=1.0)
        second.join(timeout=1.0)

        assert first.is_alive() is False
        assert second.is_alive() is False
        assert sorted(responses) == [200, 200]
        expected = ["NSE:RELIANCE", "NSE:TCS", "NSE_INDEX:NIFTY"]
        assert hub.instruments == expected
        recorder_identities = sorted(
            f"{instrument['exchange']}:{instrument['symbol']}"
            for instruments in wired.get_watchlist().values()
            for instrument in instruments
        )
        assert recorder_identities == expected

    def test_400_on_bad_action_or_empty(self, client, wired):
        assert (
            client.post(
                "/api/v1/data/ticks/watchlist",
                json={"action": "bogus", "instruments": [{"exchange": "NSE", "symbol": "X"}]},
            ).status_code
            == 400
        )
        assert client.post("/api/v1/data/ticks/watchlist", json={"action": "add", "instruments": []}).status_code == 400

    def test_400_on_invalid_mode(self, client, wired):
        resp = client.post(
            "/api/v1/data/ticks/watchlist",
            json={
            "action": "add",
            "mode": "bogus",
            "instruments": [{"exchange": "NSE", "symbol": "X"}],
            },
        )
        assert resp.status_code == 400
