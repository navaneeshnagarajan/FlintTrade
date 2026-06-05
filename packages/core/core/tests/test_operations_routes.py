"""Tests for operations REST endpoints — safety, security, logs, errors, cron, ditto.

Run with:
    python -m pytest packages/core/core/tests/test_operations_routes.py -v --import-mode=importlib
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


_TEST_API_KEY = "test-operations-routes-key"


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch fixture."""
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def flask_app(monkeypatch_module):
    """Create a Flask app with operations blueprint registered."""
    monkeypatch_module.setenv("OPENALGO_API_KEY", _TEST_API_KEY)
    monkeypatch_module.setenv("FLINTTRADE_DEV", "1")
    from flinttrade_core.app import create_flask_app
    app = create_flask_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def client(flask_app):
    """Flask test client with API key header."""
    with flask_app.test_client() as c:
        yield c


def _auth_headers() -> dict[str, str]:
    return {
        "X-API-Key": _TEST_API_KEY,
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Safety config
# ---------------------------------------------------------------------------


class TestSafetyConfigGet:
    """GET /api/v1/safety/config — return safety system configuration."""

    def test_returns_503_when_safety_not_configured(self, flask_app, client):
        """When SAFETY is None, returns 503."""
        original = flask_app.config.get("SAFETY")
        flask_app.config["SAFETY"] = None
        try:
            resp = client.get("/api/v1/safety/config", headers=_auth_headers())
            assert resp.status_code == 503
            data = resp.get_json()
            assert data["status"] == "error"
            assert "SafetySystem" in data["message"]
        finally:
            flask_app.config["SAFETY"] = original

    def test_returns_nested_config(self, flask_app, client):
        """When SAFETY is configured, returns the 5-layer nested config."""
        mock_safety = MagicMock()
        mock_safety.l1_order.price_deviation_pct = 5.0
        mock_safety.l1_order.check_market_hours = True
        mock_safety.l1_order.qty_limits = {"NSE": 1000}
        mock_safety.l2_position.max_positions = 10
        mock_safety.l2_position.max_margin_pct = 80.0
        mock_safety.l3_portfolio.max_net_delta = 50000.0
        mock_safety.l3_portfolio.max_net_vega = 10000.0
        mock_safety.l4_pnl.pause_pct = 2.0
        mock_safety.l4_pnl.kill_pct = 5.0
        mock_safety.l4_pnl.is_paused = False
        mock_safety.l4_pnl.is_killed = False
        mock_safety.l5_kill.is_active = False
        mock_safety.l5_kill.reason = ""

        original = flask_app.config.get("SAFETY")
        flask_app.config["SAFETY"] = mock_safety
        try:
            resp = client.get("/api/v1/safety/config", headers=_auth_headers())
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "success"
            assert "l1_order" in data["data"]
            assert "l2_position" in data["data"]
            assert "l3_portfolio" in data["data"]
            assert "l4_pnl" in data["data"]
            assert "l5_kill" in data["data"]
            assert data["data"]["l1_order"]["price_deviation_pct"] == 5.0
            assert data["data"]["l4_pnl"]["is_paused"] is False
        finally:
            flask_app.config["SAFETY"] = original


class TestSafetyConfigUpdate:
    """POST /api/v1/safety/config — update safety parameters."""

    def test_updates_single_field(self, flask_app, client):
        mock_safety = MagicMock()
        mock_safety.l1_order.price_deviation_pct = 5.0
        original = flask_app.config.get("SAFETY")
        flask_app.config["SAFETY"] = mock_safety
        try:
            resp = client.post("/api/v1/safety/config", json={
                "price_deviation_pct": 10.0,
            }, headers=_auth_headers())
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "success"
            assert mock_safety.l1_order.price_deviation_pct == 10.0
        finally:
            flask_app.config["SAFETY"] = original

    def test_invalid_value_returns_400(self, flask_app, client):
        mock_safety = MagicMock()
        # Make float() conversion raise ValueError
        mock_safety.l1_order.price_deviation_pct = property(
            lambda self: 5.0,
        )
        original = flask_app.config.get("SAFETY")
        flask_app.config["SAFETY"] = mock_safety
        try:
            resp = client.post("/api/v1/safety/config", json={
                "price_deviation_pct": "not-a-number",
            }, headers=_auth_headers())
            assert resp.status_code == 400
            data = resp.get_json()
            assert data["status"] == "error"
        finally:
            flask_app.config["SAFETY"] = original

    def test_returns_503_when_safety_not_configured(self, flask_app, client):
        original = flask_app.config.get("SAFETY")
        flask_app.config["SAFETY"] = None
        try:
            resp = client.post("/api/v1/safety/config", json={},
                               headers=_auth_headers())
            assert resp.status_code == 503
        finally:
            flask_app.config["SAFETY"] = original


# ---------------------------------------------------------------------------
# Security settings
# ---------------------------------------------------------------------------


class TestSecuritySettingsGet:
    """GET /api/v1/security/settings — return security monitor config."""

    def test_returns_settings(self, flask_app, client):
        """SecurityMonitor is auto-created by create_flask_app."""
        resp = client.get("/api/v1/security/settings", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "auto_ban_enabled" in data["data"]
        assert "ban_threshold" in data["data"]
        assert "notfound_ban_threshold" in data["data"]
        assert "ban_duration" in data["data"]

    def test_returns_503_when_monitor_not_configured(self, flask_app, client):
        original = flask_app.config.get("SECURITY_MONITOR")
        flask_app.config["SECURITY_MONITOR"] = None
        try:
            resp = client.get("/api/v1/security/settings", headers=_auth_headers())
            assert resp.status_code == 503
        finally:
            flask_app.config["SECURITY_MONITOR"] = original


class TestSecuritySettingsUpdate:
    """POST /api/v1/security/settings — update security monitor config."""

    def test_update_threshold(self, flask_app, client):
        resp = client.post("/api/v1/security/settings", json={
            "notfound_ban_threshold": 50,
        }, headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["notfound_ban_threshold"] == 50

    def test_invalid_value_returns_400(self, flask_app, client):
        resp = client.post("/api/v1/security/settings", json={
            "notfound_ban_threshold": "not-a-number",
        }, headers=_auth_headers())
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["status"] == "error"


# ---------------------------------------------------------------------------
# Frontend error reporting
# ---------------------------------------------------------------------------


class TestFrontendErrors:
    """POST /api/v1/errors — receive error reports from the React frontend."""

    def test_receives_error_report(self, client):
        """Error endpoint is public (no API key needed) and always returns 200."""
        resp = client.post("/api/v1/errors", json={
            "message": "Uncaught TypeError: Cannot read properties of null",
            "url": "http://localhost:5173/trade",
            "stack": "TypeError: Cannot read properties...",
            "userAgent": "Mozilla/5.0",
        }, headers={"Content-Type": "application/json"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"

    def test_empty_error_body_returns_200(self, client):
        """Even an empty body should not crash."""
        resp = client.post("/api/v1/errors", json={},
                           headers={"Content-Type": "application/json"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"


# ---------------------------------------------------------------------------
# Trade journal — shared store wiring + frontend contract
# ---------------------------------------------------------------------------


class TestTradesJournal:
    """GET /api/v1/trades/journal — reads the shared trade store.

    The order dispatch writes to ``TRADE_STORAGE`` and this route reads the same
    store, so a row inserted there must surface here — keyed as ``timestamp``
    (the terminal's JournalTrade contract), not the DuckDB ``ts`` column.
    """

    def test_shared_store_is_wired_in_dev(self, flask_app):
        assert flask_app.config.get("TRADE_STORAGE") is not None
        assert flask_app.config.get("TRADE_STORAGE_LOCK") is not None

    def test_returns_inserted_trade_with_timestamp_key(self, flask_app, client):
        from datetime import datetime, timedelta, timezone

        ist = timezone(timedelta(hours=5, minutes=30))
        store = flask_app.config["TRADE_STORAGE"]
        store.insert_trade(
            ts=datetime.now(ist),
            orderid="JNL-1",
            symbol="RELIANCE",
            exchange="NSE",
            action="BUY",
            quantity=5,
            price=2500.0,
            product="MIS",
            strategy="manual",
        )

        resp = client.get("/api/v1/trades/journal", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        rows = data["data"]["trades"]
        mine = [r for r in rows if r.get("orderid") == "JNL-1"]
        assert len(mine) == 1
        row = mine[0]
        # Frontend contract: `timestamp`, not the DuckDB `ts` column.
        assert "timestamp" in row
        assert "ts" not in row
        assert row["symbol"] == "RELIANCE"
        assert row["action"] == "BUY"


# ---------------------------------------------------------------------------
# Recent logs
# ---------------------------------------------------------------------------


class TestRecentLogs:
    """GET /api/v1/logs/recent — return recent structured log entries."""

    def test_returns_200(self, client):
        resp = client.get("/api/v1/logs/recent", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert isinstance(data["data"], list)

    def test_with_custom_n(self, client):
        resp = client.get("/api/v1/logs/recent?n=10", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"

    def test_invalid_n_returns_400(self, client):
        resp = client.get("/api/v1/logs/recent?n=abc", headers=_auth_headers())
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["status"] == "error"
        assert "positive integer" in data["message"]

    def test_negative_n_returns_400(self, client):
        resp = client.get("/api/v1/logs/recent?n=-5", headers=_auth_headers())
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Ditto — multi-account endpoints
# ---------------------------------------------------------------------------


class TestDittoMirrorStatus:
    """GET /api/v1/ditto/mirror/status — position mirroring status."""

    def test_returns_200_with_defaults(self, client):
        resp = client.get("/api/v1/ditto/mirror/status", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["active"] is False


class TestDittoAccountCrud:
    """Ditto account CRUD endpoints."""

    class _FakeAccount:
        def __init__(
            self,
            account_id: str,
            name: str = "Demo",
            openalgo_host: str = "http://127.0.0.1:5001",
            api_key: str = "secret",
            enabled: bool = True,
            group: str = "default",
            allocation_weight: float = 1.0,
            max_loss_daily: float = 50000.0,
            is_master: bool = False,
        ) -> None:
            self.account_id = account_id
            self.name = name
            self.openalgo_host = openalgo_host
            self.api_key = api_key
            self.enabled = enabled
            self.group = group
            self.allocation_weight = allocation_weight
            self.max_loss_daily = max_loss_daily
            self.is_master = is_master

    class _FakeManager:
        accounts: dict[str, "TestDittoAccountCrud._FakeAccount"] = {}

        def __init__(self, *args, **kwargs) -> None:
            pass

        def list_accounts(self):
            return list(self.accounts.values())

        def add_account(self, account) -> None:
            self.accounts[account.account_id] = account

        def get_account(self, account_id: str):
            return self.accounts.get(account_id)

        def enable_account(self, account_id: str) -> None:
            self.accounts[account_id].enabled = True

        def disable_account(self, account_id: str) -> None:
            self.accounts[account_id].enabled = False

        def remove_account(self, account_id: str) -> None:
            self.accounts.pop(account_id, None)

    def _patch_manager(self, monkeypatch, accounts=None):
        import flinttrade_ditto.account_manager as account_manager

        self._FakeManager.accounts = {
            account.account_id: account
            for account in (accounts or [])
        }
        monkeypatch.setattr(account_manager, "AccountManager", self._FakeManager)

    def test_create_account_returns_sanitised_account(self, client, monkeypatch):
        self._patch_manager(monkeypatch)
        resp = client.post("/api/v1/ditto/accounts", json={
            "account_id": "family_01",
            "name": "Family Account",
            "openalgo_host": "http://127.0.0.1:5001",
            "api_key": "secret-key",
            "group": "Family",
            "allocation_weight": 1.25,
            "max_loss_daily": 25000,
            "enabled": True,
            "is_master": False,
        }, headers=_auth_headers())

        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["account"]["id"] == "family_01"
        assert data["data"]["account"]["name"] == "Family Account"
        assert "api_key" not in data["data"]["account"]

    def test_create_account_validates_required_fields(self, client, monkeypatch):
        self._patch_manager(monkeypatch)
        resp = client.post("/api/v1/ditto/accounts", json={
            "account_id": "missing_host",
            "api_key": "secret-key",
        }, headers=_auth_headers())
        assert resp.status_code == 400

    def test_enable_disable_and_delete_account(self, client, monkeypatch):
        account = self._FakeAccount("acc_1", name="Primary", enabled=True)
        self._patch_manager(monkeypatch, [account])

        disable_resp = client.post("/api/v1/ditto/accounts/acc_1/disable", headers=_auth_headers())
        assert disable_resp.status_code == 200
        assert disable_resp.get_json()["data"]["account"]["status"] == "disabled"

        enable_resp = client.post("/api/v1/ditto/accounts/acc_1/enable", headers=_auth_headers())
        assert enable_resp.status_code == 200
        assert enable_resp.get_json()["data"]["account"]["status"] == "active"

        delete_resp = client.delete("/api/v1/ditto/accounts/acc_1", headers=_auth_headers())
        assert delete_resp.status_code == 200
        assert delete_resp.get_json()["data"]["removed"] is True


class TestDittoMirrorStart:
    """POST /api/v1/ditto/mirror/start — start position mirroring."""

    def test_missing_source_returns_400(self, client):
        resp = client.post("/api/v1/ditto/mirror/start", json={
            "target_accounts": ["acc_2"],
        }, headers=_auth_headers())
        assert resp.status_code == 400

    def test_missing_targets_returns_400(self, client):
        resp = client.post("/api/v1/ditto/mirror/start", json={
            "source_account": "acc_1",
            "target_accounts": [],
        }, headers=_auth_headers())
        assert resp.status_code == 400

    def test_valid_start_returns_deferred(self, client):
        # Multi-account mirroring is not yet wired (the PositionMirror engine
        # is unwired), so a valid request must fail closed with a truthful
        # "deferred" status rather than fabricate a live mirroring session.
        resp = client.post("/api/v1/ditto/mirror/start", json={
            "source_account": "acc_1",
            "target_accounts": ["acc_2", "acc_3"],
            "mode": "proportional",
        }, headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "deferred"
        assert data["data"]["active"] is False
        assert data["data"]["source_account"] == "acc_1"
