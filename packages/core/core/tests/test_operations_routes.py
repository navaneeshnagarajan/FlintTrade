"""Tests for operations REST endpoints — safety, security, logs, errors, cron, ditto.

Run with:
    python -m pytest packages/core/core/tests/test_operations_routes.py -v --import-mode=importlib
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
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
# Emergency kill switch — gated broker writes
# ---------------------------------------------------------------------------


class _EmergencyAdapter:
    """Token-checking adapter used by the kill-switch route integration tests."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    @staticmethod
    def _require_router(token: object | None) -> None:
        from flinttrade_core.exceptions import SafetyBypassError
        from flinttrade_gateway.brokers._base import ROUTER_TOKEN

        if token is not ROUTER_TOKEN:
            raise SafetyBypassError("emergency adapter write bypassed BrokerRouter")

    async def cancel_all_orders(self, session, *, _router_token=None):
        self._require_router(_router_token)
        self.calls.append("cancel_all_orders")
        return {"status": "ok"}

    async def exit_all_positions(self, session, *, _router_token=None):
        self._require_router(_router_token)
        self.calls.append("exit_all_positions")
        return {"status": "ok"}


class TestKillSwitchGatedWrites:
    """POST /safety/kill-switch latches L5 and uses the current BrokerRouter."""

    @staticmethod
    def _live_headers() -> dict[str, str]:
        from flinttrade_core.auth_routes import _create_token

        headers = _auth_headers()
        # Emergency flattening deliberately does not require a PIN re-unlock,
        # but it still requires an authenticated live principal for selector ACL.
        token = _create_token("testuser", mode="live", live_mode_unlocked=False)
        headers["Authorization"] = f"Bearer {token}"
        return headers

    @staticmethod
    def _router(adapter, *, allowed_actor: str = "testuser"):
        from datetime import datetime, timezone

        from flinttrade_core.exceptions import SafetyBypassError
        from flinttrade_engine.safety import SafetyGate
        from flinttrade_gateway.brokers._base import Session
        from flinttrade_gateway.router import BrokerRouter

        def session_provider(request_ctx, adapter_id, account_id):
            if request_ctx.actor_id != allowed_actor:
                raise SafetyBypassError("selector ACL refused actor")
            return Session(
                access_token="token",
                expires_at=datetime.now(tz=timezone.utc).timestamp() + 3600,
                account_id=account_id,
                adapter_id=adapter_id,
            )

        gate = SafetyGate()
        return BrokerRouter(
            {"dhan": adapter},
            session_provider,
            consume_gate=gate.consume,
        )

    def test_routes_cancel_and_exit_through_gated_token_adapter(self, flask_app, client):
        from flinttrade_engine.safety import SafetySystem

        adapter = _EmergencyAdapter()
        safety = SafetySystem()
        original = {
            "SAFETY": flask_app.config.get("SAFETY"),
            "BROKER_ROUTER": flask_app.config.get("BROKER_ROUTER"),
            "CLIENT": flask_app.config.get("CLIENT"),
        }
        flask_app.config.update(
            SAFETY=safety,
            BROKER_ROUTER=self._router(adapter),
            CLIENT=None,
        )
        try:
            response = client.post(
                "/api/v1/safety/kill-switch",
                json={
                    "reason": "test emergency",
                    "broker": "dhan",
                    "account_id": "acct-1",
                },
                headers=self._live_headers(),
            )

            assert response.status_code == 200
            assert safety.l5_kill.is_active
            assert adapter.calls == ["cancel_all_orders", "exit_all_positions"]
            assert response.get_json()["data"]["emergency_actions"]["complete"] is True
        finally:
            safety.l5_kill.reset()
            flask_app.config.update(original)

    def test_selector_acl_refusal_latches_l5_without_adapter_write(self, flask_app, client):
        from flinttrade_engine.safety import SafetySystem

        adapter = _EmergencyAdapter()
        safety = SafetySystem()
        original_safety = flask_app.config.get("SAFETY")
        original_router = flask_app.config.get("BROKER_ROUTER")
        flask_app.config["SAFETY"] = safety
        flask_app.config["BROKER_ROUTER"] = self._router(adapter, allowed_actor="someone-else")
        try:
            response = client.post(
                "/api/v1/safety/kill-switch",
                json={"broker": "dhan", "account_id": "acct-1"},
                headers=self._live_headers(),
            )

            assert response.status_code == 207
            assert safety.l5_kill.is_active
            assert adapter.calls == []
            payload = response.get_json()
            assert payload["status"] == "partial"
            assert payload["data"]["is_active"] is True
            assert payload["data"]["emergency_actions"]["complete"] is False
        finally:
            safety.l5_kill.reset()
            flask_app.config["SAFETY"] = original_safety
            flask_app.config["BROKER_ROUTER"] = original_router

    def test_missing_target_fails_closed_and_never_uses_raw_client(self, flask_app, client):
        from flinttrade_engine.safety import SafetySystem

        safety = SafetySystem()
        raw_client = MagicMock()
        original = {
            "SAFETY": flask_app.config.get("SAFETY"),
            "BROKER_ROUTER": flask_app.config.get("BROKER_ROUTER"),
            "CLIENT": flask_app.config.get("CLIENT"),
        }
        flask_app.config.update(SAFETY=safety, BROKER_ROUTER=None, CLIENT=raw_client)
        try:
            response = client.post(
                "/api/v1/safety/kill-switch",
                json={"reason": "router unavailable"},
                headers=self._live_headers(),
            )

            assert response.status_code == 207
            assert safety.l5_kill.is_active
            assert response.get_json()["status"] == "partial"
            raw_client.cancel_all_orders.assert_not_called()
            raw_client.close_position.assert_not_called()
        finally:
            safety.l5_kill.reset()
            flask_app.config.update(original)


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

    @staticmethod
    def _temp_store(flask_app, tmp_path):
        """Swap an isolated temp-file store into the app (restored by caller).

        The DEV fixture wires TRADE_STORAGE at the real default DuckDB path;
        writing test rows there would pollute a real file and accumulate across
        runs, so each write-test gets its own throwaway store.
        """
        from flinttrade_data.storage import StorageManager

        store = StorageManager(db_path=str(tmp_path / "journal.duckdb"))
        store.initialise()
        flask_app.config["TRADE_STORAGE"] = store
        return store

    def test_shared_store_is_wired_in_dev(self, flask_app):
        assert flask_app.config.get("TRADE_STORAGE") is not None
        assert flask_app.config.get("TRADE_STORAGE_LOCK") is not None

    def test_returns_inserted_trade_with_timestamp_key(self, flask_app, client, tmp_path):
        from datetime import datetime, timedelta, timezone

        ist = timezone(timedelta(hours=5, minutes=30))
        orig = flask_app.config.get("TRADE_STORAGE")
        store = self._temp_store(flask_app, tmp_path)
        try:
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
        finally:
            flask_app.config["TRADE_STORAGE"] = orig
            store.close()

    def test_date_range_without_strategy_uses_range_query(self, flask_app, client, tmp_path):
        """start+end with no strategy must hit the range query, not single-day.

        Previously a start+end (no strategy) fell through to a single-day lookup —
        the recurring contract bug the performance dashboard would have tripped.
        """
        from datetime import datetime, timedelta, timezone

        ist = timezone(timedelta(hours=5, minutes=30))
        orig = flask_app.config.get("TRADE_STORAGE")
        store = self._temp_store(flask_app, tmp_path)
        try:
            base = datetime.now(ist)
            store.insert_trade(
                ts=base - timedelta(days=20), orderid="RNG-OLD", symbol="TCS",
                exchange="NSE", action="BUY", quantity=1, price=100.0, strategy="manual",
            )
            store.insert_trade(
                ts=base, orderid="RNG-NEW", symbol="TCS",
                exchange="NSE", action="SELL", quantity=1, price=110.0, strategy="manual",
            )

            start = (base - timedelta(days=30)).strftime("%Y-%m-%d")
            end = base.strftime("%Y-%m-%d")
            resp = client.get(
                f"/api/v1/trades/journal?start_date={start}&end_date={end}",
                headers=_auth_headers(),
            )
            assert resp.status_code == 200
            ids = {r.get("orderid") for r in resp.get_json()["data"]["trades"]}
            # The 20-day-old trade is only reachable via the range query.
            assert "RNG-OLD" in ids
            assert "RNG-NEW" in ids
        finally:
            flask_app.config["TRADE_STORAGE"] = orig
            store.close()


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

    def test_list_accounts_returns_configured_accounts(self, client, monkeypatch):
        self._patch_manager(monkeypatch, [self._FakeAccount("acc_1", name="Primary", enabled=True)])

        resp = client.get("/api/v1/ditto/accounts", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["accounts"] == [
            {
                "id": "acc_1",
                "name": "Primary",
                "broker": "OpenAlgo",
                "capital": 0,
                "pnl_today": 0,
                "status": "active",
                "positions": 0,
                "group": "default",
                "allocation_weight": 1.0,
                "is_master": False,
            }
        ]
        assert "api_key" not in data["data"]["accounts"][0]

    def test_list_accounts_returns_empty_list_when_none_configured(self, client, monkeypatch):
        self._patch_manager(monkeypatch)

        resp = client.get("/api/v1/ditto/accounts", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["accounts"] == []

    def test_list_accounts_returns_503_when_manager_unavailable(self, client, monkeypatch):
        class _BoomManager:
            def __init__(self, *args, **kwargs) -> None:
                raise RuntimeError("database unavailable")

        monkeypatch.setattr("flinttrade_ditto.account_manager.AccountManager", _BoomManager)

        resp = client.get("/api/v1/ditto/accounts", headers=_auth_headers())

        assert resp.status_code == 503
        data = resp.get_json()
        assert data["status"] == "error"
        assert data["message"] == "Account service unavailable"

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


class TestAccountsStatus:
    """GET /api/v1/accounts/status — Account Manager per-broker reauth summary."""

    class _FakeStatus:
        def __init__(self, connected: bool, authenticated: bool, needs_reauth: bool):
            self._d = {
                "connected": connected,
                "authenticated": authenticated,
                "needs_reauth": needs_reauth,
            }

        def to_dict(self) -> dict:
            return self._d

    class _FakeAM:
        def __init__(self, statuses):
            self._statuses = statuses

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def account_status_all(self):
            return self._statuses

    class _NativeStore:
        def __init__(self, rows):
            self._rows = rows

        def list_accounts(self):
            return self._rows

    class _NativeRegistry:
        def __init__(self, sessions=None):
            self._sessions = sessions or {}

        def get_session_for(self, adapter_id, account_id):
            key = (adapter_id, account_id)
            if key not in self._sessions:
                raise KeyError(key)
            return self._sessions[key]

    def test_returns_summary_and_per_account_status(self, client, monkeypatch):
        statuses = [
            self._FakeStatus(connected=True, authenticated=True, needs_reauth=False),
            self._FakeStatus(connected=True, authenticated=False, needs_reauth=True),
            self._FakeStatus(connected=False, authenticated=False, needs_reauth=False),
        ]
        monkeypatch.setattr(
            "flinttrade_ditto.account_manager.AccountManager",
            lambda **_kw: self._FakeAM(statuses),
        )

        resp = client.get("/api/v1/accounts/status", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert len(data["data"]["accounts"]) == 3
        assert data["data"]["summary"] == {
            "total": 3,
            "connected": 2,
            "authenticated": 1,
            "needs_reauth": 1,
        }

    def test_merges_native_account_status(self, flask_app, client, monkeypatch):
        monkeypatch.setattr(
            "flinttrade_ditto.account_manager.AccountManager",
            lambda **_kw: self._FakeAM([]),
        )
        session = type("Session", (), {"expires_at": 4_102_444_800.0})()
        original_store = flask_app.config.get("CREDENTIAL_STORE")
        original_registry = flask_app.config.get("REGISTRY")
        original_login_status = flask_app.config.get("NATIVE_SESSION_STATUS")
        flask_app.config["CREDENTIAL_STORE"] = self._NativeStore([
            {
                "adapter_id": "upstox",
                "account_id": "UPX-LIVE",
                "label": "Upstox main",
                "is_primary": True,
            }
        ])
        flask_app.config["REGISTRY"] = self._NativeRegistry({("upstox", "UPX-LIVE"): session})
        flask_app.config["NATIVE_SESSION_STATUS"] = {}
        try:
            resp = client.get("/api/v1/accounts/status", headers=_auth_headers())
        finally:
            flask_app.config["CREDENTIAL_STORE"] = original_store
            flask_app.config["REGISTRY"] = original_registry
            flask_app.config["NATIVE_SESSION_STATUS"] = original_login_status

        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["summary"] == {
            "total": 1,
            "connected": 1,
            "authenticated": 1,
            "needs_reauth": 0,
        }
        row = data["accounts"][0]
        assert row["source"] == "native"
        assert row["broker"] == "upstox"
        assert row["broker_display"] == "Upstox"
        assert row["name"] == "Upstox main"
        assert row["connected"] is True
        assert row["authenticated"] is True
        assert row["expires_at"] == 4_102_444_800.0

    def test_returns_native_status_when_ditto_unavailable(self, flask_app, client, monkeypatch):
        def _boom():
            raise RuntimeError("credential vault locked")

        monkeypatch.setattr("flinttrade_ditto.account_manager.AccountManager", _boom)
        original_store = flask_app.config.get("CREDENTIAL_STORE")
        original_registry = flask_app.config.get("REGISTRY")
        original_login_status = flask_app.config.get("NATIVE_SESSION_STATUS")
        flask_app.config["CREDENTIAL_STORE"] = self._NativeStore([
            {
                "adapter_id": "indmoney",
                "account_id": "IND-LIVE",
                "label": "INDmoney main",
            }
        ])
        flask_app.config["REGISTRY"] = self._NativeRegistry()
        flask_app.config["NATIVE_SESSION_STATUS"] = {"indmoney:IND-LIVE": "login-failed: token expired"}
        try:
            resp = client.get("/api/v1/accounts/status", headers=_auth_headers())
        finally:
            flask_app.config["CREDENTIAL_STORE"] = original_store
            flask_app.config["REGISTRY"] = original_registry
            flask_app.config["NATIVE_SESSION_STATUS"] = original_login_status

        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["summary"] == {
            "total": 1,
            "connected": 0,
            "authenticated": 0,
            "needs_reauth": 1,
        }
        row = data["accounts"][0]
        assert row["source"] == "native"
        assert row["broker"] == "indmoney"
        assert row["needs_reauth"] is True
        assert row["login_retryable"] is False
        assert row["error"] == "login-failed: token expired"

    def test_native_retryable_login_status_is_not_reauth(self, flask_app, client, monkeypatch):
        from flinttrade_gateway.native_login import BROKER_LOGIN_RETRY_MESSAGE

        def _boom():
            raise RuntimeError("credential vault locked")

        monkeypatch.setattr("flinttrade_ditto.account_manager.AccountManager", _boom)
        original_store = flask_app.config.get("CREDENTIAL_STORE")
        original_registry = flask_app.config.get("REGISTRY")
        original_login_status = flask_app.config.get("NATIVE_SESSION_STATUS")
        flask_app.config["CREDENTIAL_STORE"] = self._NativeStore([
            {
                "adapter_id": "upstox",
                "account_id": "UPX-RETRY",
                "label": "Upstox retry",
            }
        ])
        flask_app.config["REGISTRY"] = self._NativeRegistry()
        flask_app.config["NATIVE_SESSION_STATUS"] = {"upstox:UPX-RETRY": BROKER_LOGIN_RETRY_MESSAGE}
        try:
            resp = client.get("/api/v1/accounts/status", headers=_auth_headers())
        finally:
            flask_app.config["CREDENTIAL_STORE"] = original_store
            flask_app.config["REGISTRY"] = original_registry
            flask_app.config["NATIVE_SESSION_STATUS"] = original_login_status

        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["summary"] == {
            "total": 1,
            "connected": 0,
            "authenticated": 0,
            "needs_reauth": 0,
        }
        row = data["accounts"][0]
        assert row["source"] == "native"
        assert row["broker"] == "upstox"
        assert row["needs_reauth"] is False
        assert row["login_retryable"] is True
        assert row["error"] == BROKER_LOGIN_RETRY_MESSAGE

    def test_returns_503_when_account_manager_unavailable(self, client, monkeypatch):
        def _boom():
            raise RuntimeError("credential vault locked")

        monkeypatch.setattr("flinttrade_ditto.account_manager.AccountManager", _boom)

        resp = client.get("/api/v1/accounts/status", headers=_auth_headers())
        assert resp.status_code == 503
        assert resp.get_json()["status"] == "error"


class TestWebhooksManagement:
    """GET/POST/DELETE /api/v1/webhooks — the endpoints behind the Flows panel.

    The list must emit ``id`` and ``type`` per webhook: the panel keys its table
    and its delete action off ``id`` (so a missing id breaks delete entirely) and
    renders the source badge off ``type``.
    """

    @pytest.fixture(autouse=True)
    def registry(self):
        from flinttrade_core.workspace import Workspace

        workspace = Workspace()
        workspace.load()
        previous = workspace.get("automation.webhooks", [])
        workspace.set("automation.webhooks", [])
        yield
        workspace.set("automation.webhooks", previous)

    def _create(
        self,
        client,
        *,
        path: str,
        name: str,
        webhook_type: str = "custom",
        secret: str = "",
        enabled: bool = True,
    ):
        return client.post(
            "/api/v1/webhooks",
            headers=_auth_headers(),
            json={"path": path, "name": name, "type": webhook_type, "secret": secret, "enabled": enabled},
        )

    def _signed_headers(self, body: bytes, secret: str, *, nonce: str = "ops-nonce-1") -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Signature": "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest(),
            "X-Webhook-Nonce": nonce,
            "X-Webhook-Timestamp": str(time.time()),
        }

    def test_list_starts_empty_without_standalone_server(self, client):
        resp = client.get("/api/v1/webhooks", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data == {"webhooks": []}

    def test_create_returns_full_config(self, client):
        resp = self._create(
            client,
            path="/webhook/chartink/scan1",
            name="Chartink Scan",
            webhook_type="chartink",
        )
        assert resp.status_code == 201
        data = resp.get_json()["data"]
        assert data["id"] == "v1/webhook/chartink/scan1"
        assert data["path"] == "/v1/webhook/chartink/scan1"
        assert data["type"] == "chartink"
        assert data["enabled"] is True
        assert "secret" not in data

    def test_path_without_source_uses_selected_type(self, client):
        resp = self._create(
            client,
            path="/webhook/nifty-breakout",
            name="TV Breakout",
            webhook_type="tradingview",
        )
        assert resp.status_code == 201
        data = resp.get_json()["data"]
        assert data["id"] == "v1/webhook/tradingview/nifty-breakout"
        assert data["path"] == "/v1/webhook/tradingview/nifty-breakout"
        assert data["type"] == "tradingview"

    def test_create_with_secret_uses_encrypted_store_without_echoing_secret(self, flask_app, client):
        resp = self._create(
            client,
            path="/webhook/chartink/scan1",
            name="Chartink Scan",
            webhook_type="chartink",
            secret="do-not-store-in-workspace-json",
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["status"] == "success"
        data = body["data"]
        assert data["path"] == "/v1/webhook/chartink/scan1"
        assert "secret" not in data

        from flinttrade_core.workspace import Workspace

        workspace_rows = Workspace().get("automation.webhooks", [])
        assert workspace_rows
        assert all("secret" not in row for row in workspace_rows)

        store = flask_app.config["WEBHOOK_SECRET_STORE"]
        assert store.get_secret("/v1/webhook/chartink/scan1") == "do-not-store-in-workspace-json"

    def test_list_id_round_trips_through_delete(self, client):
        """The id the list emits must, URL-encoded as the frontend does, delete
        that exact webhook — proving the encoded-path id survives routing."""
        from urllib.parse import quote

        created = self._create(
            client,
            path="/webhook/custom/my_signal",
            name="My Signal",
            webhook_type="custom",
        )
        assert created.status_code == 201

        listed = client.get("/api/v1/webhooks", headers=_auth_headers()).get_json()["data"]["webhooks"]
        target = next(w for w in listed if w["name"] == "My Signal")

        # mirror the frontend's encodeURIComponent(id)
        resp = client.delete(
            f"/api/v1/webhooks/{quote(target['id'], safe='')}",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200

        remaining = client.get("/api/v1/webhooks", headers=_auth_headers()).get_json()["data"]["webhooks"]
        assert all(w["name"] != "My Signal" for w in remaining)

    def test_delete_removes_matching_webhook_secret(self, flask_app, client):
        from urllib.parse import quote

        created = self._create(
            client,
            path="/webhook/custom/private_signal",
            name="Private Signal",
            webhook_type="custom",
            secret="delete-me-too",
        )
        assert created.status_code == 201
        target = created.get_json()["data"]

        store = flask_app.config["WEBHOOK_SECRET_STORE"]
        assert store.has_secret(target["path"]) is True

        resp = client.delete(
            f"/api/v1/webhooks/{quote(target['id'], safe='')}",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        assert store.has_secret(target["path"]) is False

    def test_signed_webhook_post_is_public_but_still_hmac_checked(self, client):
        secret = "public-post-secret"
        created = self._create(
            client,
            path="/webhook/custom/public-signal",
            name="Public Signal",
            webhook_type="custom",
            secret=secret,
        )
        assert created.status_code == 201

        body = json.dumps({"action": "signal", "symbol": "TCS"}).encode("utf-8")
        resp = client.post(
            "/ft-api/v1/webhook/custom/public-signal",
            data=body,
            headers=self._signed_headers(body, secret, nonce=f"public-post-{time.time_ns()}"),
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["status"] == "success"
        assert payload["data"]["status"] == "received"

        bad_headers = self._signed_headers(body, "wrong-secret", nonce=f"public-post-bad-{time.time_ns()}")
        rejected = client.post(
            "/ft-api/v1/webhook/custom/public-signal",
            data=body,
            headers=bad_headers,
        )
        assert rejected.status_code == 401

    def test_disabled_registered_webhook_is_rejected_before_dispatch(self, client):
        secret = "disabled-post-secret"
        created = self._create(
            client,
            path="/webhook/custom/disabled-signal",
            name="Disabled Signal",
            webhook_type="custom",
            secret=secret,
            enabled=False,
        )
        assert created.status_code == 201

        body = json.dumps({"action": "signal", "symbol": "TCS"}).encode("utf-8")
        resp = client.post(
            "/ft-api/v1/webhook/custom/disabled-signal",
            data=body,
            headers=self._signed_headers(body, secret, nonce=f"disabled-post-{time.time_ns()}"),
        )
        assert resp.status_code == 503
        assert resp.get_json()["message"] == "Webhook endpoint disabled"
