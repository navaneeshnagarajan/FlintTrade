"""Tests for keyboard shortcut persistence routes.

Run with:
    python -m pytest packages/core/core/tests/test_shortcuts_routes.py -v --import-mode=importlib
"""
from __future__ import annotations


import pytest

_TEST_API_KEY = "test-shortcuts-key"


def _auth(extra: dict | None = None) -> dict:
    """Return standard auth + content-type headers."""
    headers = {
        "X-API-Key": _TEST_API_KEY,
        "Content-Type": "application/json",
    }
    if extra:
        headers.update(extra)
    return headers


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_module_state():
    """Reset module-level _conn before each test."""
    import flinttrade_core.shortcuts_routes as sr
    sr._reset_conn()
    yield
    sr._reset_conn()


@pytest.fixture()
def in_memory_conn():
    """Provide a real DuckDB in-memory connection with schema created."""
    duckdb = pytest.importorskip("duckdb")
    conn = duckdb.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS shortcuts (
            user_id  TEXT    NOT NULL,
            id       TEXT    NOT NULL,
            keys     TEXT    NOT NULL,
            updated  TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (user_id, id)
        )
        """
    )
    return conn


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def flask_app(monkeypatch_module):
    """Flask app with shortcuts blueprint registered."""
    monkeypatch_module.setenv("OPENALGO_API_KEY", _TEST_API_KEY)
    from flinttrade_core.app import create_flask_app
    app = create_flask_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def client(flask_app, in_memory_conn):
    """Test client with in-memory DuckDB connection injected."""
    import flinttrade_core.shortcuts_routes as sr
    sr._conn = in_memory_conn
    with flask_app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetShortcuts:
    def test_returns_empty_overrides_for_new_user(self, client):
        """GET /v1/shortcuts returns empty dict when no overrides saved."""
        resp = client.get(
            "/v1/shortcuts",
            headers=_auth({"X-User-Id": "user-1"}),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["overrides"] == {}

    def test_returns_saved_overrides(self, client, in_memory_conn):
        """GET returns overrides previously saved via the DB helper."""
        from flinttrade_core.shortcuts_routes import _save_overrides
        _save_overrides("user-2", {"cancel-orders": ["Ctrl", "C"]}, in_memory_conn)

        resp = client.get(
            "/v1/shortcuts",
            headers=_auth({"X-User-Id": "user-2"}),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["overrides"]["cancel-orders"] == ["Ctrl", "C"]

    def test_defaults_to_user_default_when_no_user_id_header(self, client):
        """GET uses 'default' user when X-User-Id header is absent."""
        resp = client.get(
            "/v1/shortcuts",
            headers=_auth(),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["user_id"] == "default"


class TestSaveShortcuts:
    def test_saves_overrides_successfully(self, client):
        """POST /v1/shortcuts persists overrides and returns count."""
        payload = {"overrides": {"quick-buy": ["Shift", "B"]}}
        resp = client.post(
            "/v1/shortcuts",
            json=payload,
            headers=_auth({"X-User-Id": "user-3"}),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["saved"] == 1

    def test_returns_400_for_missing_overrides_key(self, client):
        """POST without 'overrides' key returns 400."""
        resp = client.post(
            "/v1/shortcuts",
            json={"wrong_key": {}},
            headers=_auth({"X-User-Id": "user-4"}),
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["status"] == "error"

    def test_returns_400_for_empty_body(self, client):
        """POST with no body returns 400."""
        resp = client.post(
            "/v1/shortcuts",
            data="",
            content_type="application/json",
            headers=_auth(),
        )
        assert resp.status_code == 400

    def test_save_then_get_roundtrip(self, client):
        """Saved overrides are returned by subsequent GET."""
        overrides = {"toggle-timeframe": ["Alt", "T"]}
        client.post(
            "/v1/shortcuts",
            json={"overrides": overrides},
            headers=_auth({"X-User-Id": "user-5"}),
        )
        resp = client.get(
            "/v1/shortcuts",
            headers=_auth({"X-User-Id": "user-5"}),
        )
        data = resp.get_json()
        assert data["overrides"]["toggle-timeframe"] == ["Alt", "T"]


class TestResetShortcuts:
    def test_reset_deletes_overrides(self, client, in_memory_conn):
        """POST /v1/shortcuts/reset removes all overrides for user."""
        from flinttrade_core.shortcuts_routes import _save_overrides
        _save_overrides(
            "user-6",
            {"cancel-orders": ["C"], "quick-buy": ["B"]},
            in_memory_conn,
        )

        resp = client.post(
            "/v1/shortcuts/reset",
            headers=_auth({"X-User-Id": "user-6"}),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["deleted"] == 2

        # Verify gone
        get_resp = client.get(
            "/v1/shortcuts",
            headers=_auth({"X-User-Id": "user-6"}),
        )
        assert get_resp.get_json()["overrides"] == {}

    def test_reset_idempotent_when_no_overrides(self, client):
        """Resetting a user with no overrides returns deleted=0 without error."""
        resp = client.post(
            "/v1/shortcuts/reset",
            headers=_auth({"X-User-Id": "user-no-overrides"}),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["deleted"] == 0
