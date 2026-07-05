"""Daily native session refresh (Phase 1 G5).

``NativeSessionRefresher`` is the REAL ``refresh_token`` hook for
``CredentialsRotator``: renew-in-place where the adapter supports it (Dhan),
vault-credential replay otherwise, per-selector isolation, and a raise on
failure so ``rotate-now`` reports honestly. ``configure_session_rotation``
wires the rotator + admin routes + 08:05 IST jobs into the app factory.
"""

from __future__ import annotations

from typing import Any

import pytest
from flask import Flask

from flinttrade_gateway.native_login import SESSION_INVALID_RELOGIN_MESSAGE

from flinttrade_core.native_rotation import NativeSessionRefresher

pytestmark = pytest.mark.unit


class _Session:
    def __init__(self, token: str) -> None:
        self.access_token = token
        self.expires_at = 4_102_444_800.0


class _Adapter:
    """Fake native adapter; renewable when ``renewable=True``."""

    def __init__(self, *, renewable: bool = False, fail_login: bool = False) -> None:
        self.renew_calls: list[Any] = []
        self.login_calls: list[dict[str, Any]] = []
        self.fail_login = fail_login
        if renewable:
            async def renew_token(session: Any) -> dict[str, Any]:
                self.renew_calls.append(session)
                return {"accessToken": "renewed-token"}

            self.renew_token = renew_token

    async def login(self, credentials: dict[str, Any]) -> _Session:
        self.login_calls.append(credentials)
        if self.fail_login:
            raise RuntimeError("token expired — fresh 2FA required")
        return _Session(str(credentials.get("access_token") or "fresh"))


class _Registry:
    def __init__(self) -> None:
        self.sessions: dict[tuple[str, str], Any] = {}

    def get_session_for(self, adapter_id: str, account_id: str) -> Any:
        return self.sessions[(adapter_id, account_id)]

    def put_session(self, adapter_id: str, account_id: str, session: Any) -> None:
        self.sessions[(adapter_id, account_id)] = session

    def remove_session_for(self, adapter_id: str, account_id: str) -> None:
        self.sessions.pop((adapter_id, account_id), None)


class _Store:
    def __init__(self, rows: dict[tuple[str, str], dict[str, Any]]) -> None:
        self.rows = rows

    def list_accounts(self) -> list[dict[str, Any]]:
        return [
            {"adapter_id": aid, "account_id": acc, "broker": aid}
            for (aid, acc) in self.rows
        ]

    def retrieve_for(self, adapter_id: str, account_id: str) -> dict[str, Any]:
        return dict(self.rows[(adapter_id, account_id)])

    def update_credentials_for(self, adapter_id: str, account_id: str, creds: dict[str, Any]) -> None:
        self.rows[(adapter_id, account_id)] = creds


def _app(adapter: _Adapter, registry: _Registry, store: _Store) -> Flask:
    app = Flask(__name__)
    app.config["NATIVE_ADAPTERS"] = {"dhan": adapter}
    app.config["REGISTRY"] = registry
    app.config["CREDENTIAL_STORE"] = store
    return app


def test_renew_in_place_when_session_live_and_adapter_renewable() -> None:
    adapter = _Adapter(renewable=True)
    registry = _Registry()
    registry.sessions[("dhan", "111")] = _Session("old-token")
    store = _Store({("dhan", "111"): {"client_id": "111", "access_token": "old-token"}})

    NativeSessionRefresher(_app(adapter, registry, store)).refresh_token("dhan")

    assert len(adapter.renew_calls) == 1
    # login() ran with the RENEWED token and the registry holds the new session.
    assert adapter.login_calls[0]["access_token"] == "renewed-token"
    assert registry.sessions[("dhan", "111")].access_token == "renewed-token"


def test_replays_vault_credentials_without_a_live_session() -> None:
    adapter = _Adapter(renewable=True)  # renewable, but no session to renew
    registry = _Registry()
    store = _Store({("dhan", "111"): {"client_id": "111", "access_token": "stored-token"}})

    NativeSessionRefresher(_app(adapter, registry, store)).refresh_token("dhan")

    assert adapter.renew_calls == []
    assert adapter.login_calls[0]["access_token"] == "stored-token"
    assert registry.sessions[("dhan", "111")].access_token == "stored-token"


def test_failure_raises_and_lands_in_the_status_surface() -> None:
    adapter = _Adapter(fail_login=True)
    registry = _Registry()
    store = _Store({("dhan", "111"): {"client_id": "111", "access_token": "dead"}})
    app = _app(adapter, registry, store)

    with pytest.raises(RuntimeError, match="Broker session expired or invalid") as raised:
        NativeSessionRefresher(app).refresh_token("dhan")

    # The UI surface (G7) records the per-selector reason.
    assert app.config["NATIVE_SESSION_STATUS"]["dhan:111"] == SESSION_INVALID_RELOGIN_MESSAGE
    assert "dhan:111" not in str(raised.value)
    assert "fresh 2FA required" not in str(raised.value)
    assert registry.sessions == {}  # fail-closed: no session registered


def test_inactive_adapter_raises() -> None:
    app = Flask(__name__)
    app.config["NATIVE_ADAPTERS"] = {}
    app.config["REGISTRY"] = _Registry()
    app.config["CREDENTIAL_STORE"] = _Store({})
    with pytest.raises(RuntimeError, match="not active"):
        NativeSessionRefresher(app).refresh_token("dhan")


def test_factory_wires_rotator_routes_and_guard(tmp_path, monkeypatch) -> None:
    """The real app factory mounts the rotation admin routes behind the G9
    guard and exposes the rotator + unstarted scheduler on app.config."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.delenv("OPENALGO_API_KEY", raising=False)
    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    (tmp_path / "master_password").write_text("rotation-test-pw", encoding="utf-8")
    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True
    assert app.config.get("CREDENTIALS_ROTATOR") is not None
    scheduler = app.config.get("ROTATION_SCHEDULER")
    assert scheduler is not None
    assert getattr(scheduler, "running", True) is False  # factory never starts it

    c = app.test_client()
    # Status read keeps the loopback allowance.
    assert c.get("/admin/credentials/rotation/status").status_code == 200
    # Writes need the operator session (G9).
    assert c.post("/admin/credentials/rotation/dhan/rotate-now").status_code == 401


def test_rotation_schedules_only_active_native_adapters(monkeypatch) -> None:
    """Coming-soon native selectors must not create noisy daily refresh jobs."""
    from flinttrade_core.native_rotation import configure_session_rotation

    app = Flask(__name__)
    app.config["NATIVE_ADAPTERS"] = {
        "dhan": object(),
        "upstox": object(),
        "indmoney": object(),
    }
    monkeypatch.setattr(
        "flinttrade_core.app._read_workspace_brokers",
        lambda: {
            "registered": [
                "openalgo:default",
                "dhan:D1",
                "upstox:U1",
                "indmoney:I1",
                "kotakneo:K1",
            ]
        },
    )

    assert configure_session_rotation(app) is not None

    job_ids = {job.id for job in app.config["ROTATION_SCHEDULER"].get_jobs()}
    assert {"cred_refresh_dhan", "cred_refresh_upstox", "cred_refresh_indmoney"} <= job_ids
    assert "cred_refresh_kotakneo" not in job_ids
    assert "cred_refresh_openalgo" not in job_ids


def test_rotation_route_auth_runs_before_active_broker_check(monkeypatch) -> None:
    """Unauthenticated callers get 401, not an active-broker oracle."""
    from flinttrade_core.native_rotation import configure_session_rotation

    app = Flask(__name__)
    app.config["NATIVE_ADAPTERS"] = {}

    def guard():
        return {"status": "error", "message": "unauthorised"}, 401

    app.config["BROKER_MGMT_WRITE_GUARD"] = guard
    monkeypatch.setattr("flinttrade_core.app._read_workspace_brokers", lambda: {"registered": ["kotakneo:K1"]})
    app.register_blueprint(configure_session_rotation(app))

    resp = app.test_client().post("/admin/credentials/rotation/kotakneo/schedule")

    assert resp.status_code == 401


def test_rotation_route_rejects_inactive_native_after_auth(monkeypatch) -> None:
    """Manual admin scheduling follows the same active-native truth as boot."""
    from flinttrade_core.native_rotation import configure_session_rotation

    app = Flask(__name__)
    app.config["NATIVE_ADAPTERS"] = {"dhan": object()}
    app.config["BROKER_MGMT_WRITE_GUARD"] = lambda: None
    monkeypatch.setattr(
        "flinttrade_core.app._read_workspace_brokers",
        lambda: {"registered": ["dhan:D1", "kotakneo:K1", "openalgo:default"]},
    )
    app.register_blueprint(configure_session_rotation(app))
    client = app.test_client()

    assert client.post("/admin/credentials/rotation/dhan/schedule").status_code == 200
    kotak = client.post("/admin/credentials/rotation/kotakneo/schedule")
    openalgo = client.post("/admin/credentials/rotation/openalgo/schedule")

    assert kotak.status_code == 400
    assert "not active" in kotak.get_json()["message"]
    assert openalgo.status_code == 400


def test_rotation_route_rejects_weekly_native_api_key_rotation(monkeypatch) -> None:
    """Core-mounted native rotation supports real daily refresh, not fake weekly key rotation."""
    from flinttrade_core.native_rotation import configure_session_rotation

    app = Flask(__name__)
    app.config["NATIVE_ADAPTERS"] = {"dhan": object()}
    app.config["BROKER_MGMT_WRITE_GUARD"] = lambda: None
    monkeypatch.setattr("flinttrade_core.app._read_workspace_brokers", lambda: {"registered": ["dhan:D1"]})
    app.register_blueprint(configure_session_rotation(app))
    client = app.test_client()

    daily = client.post("/admin/credentials/rotation/dhan/schedule", json={"interval": "daily", "time_ist": "08:05"})
    weekly = client.post(
        "/admin/credentials/rotation/dhan/schedule",
        json={"interval": "weekly", "time_ist": "08:05", "day": 0},
    )

    assert daily.status_code == 200
    assert weekly.status_code == 400
    assert "daily refresh only" in weekly.get_json()["message"]


def test_renewed_token_is_persisted_to_the_vault() -> None:
    """After Dhan RenewToken, the vault must hold the NEW token (write-back's
    replay-equality guard would otherwise skip the write, leaving the old
    token to be replayed next boot)."""
    adapter = _Adapter(renewable=True)
    registry = _Registry()
    registry.sessions[("dhan", "111")] = _Session("old-token")
    store = _Store({("dhan", "111"): {"client_id": "111", "access_token": "old-token"}})

    NativeSessionRefresher(_app(adapter, registry, store)).refresh_token("dhan")

    assert store.rows[("dhan", "111")]["access_token"] == "renewed-token"


def test_dead_token_probe_downgrades_to_needs_relogin() -> None:
    """A lazy token login that builds a Session for a DEAD token must not report
    'ok' — the funds probe fails, the session is dropped, needs_relogin fires."""
    class _DeadTokenAdapter(_Adapter):
        async def funds(self, session):  # noqa: ANN001
            raise RuntimeError("401 token expired")

    adapter = _DeadTokenAdapter()
    registry = _Registry()
    store = _Store({("dhan", "111"): {"access_token": "dead"}})
    app = _app(adapter, registry, store)

    import pytest
    with pytest.raises(RuntimeError, match="Broker session expired or invalid") as raised:
        NativeSessionRefresher(app).refresh_token("dhan")
    assert app.config["NATIVE_SESSION_STATUS"]["dhan:111"] == SESSION_INVALID_RELOGIN_MESSAGE
    assert "dhan:111" not in str(raised.value)
    assert "401 token expired" not in str(raised.value)
    assert ("dhan", "111") not in registry.sessions  # dropped


def test_live_token_probe_passes() -> None:
    class _LiveAdapter(_Adapter):
        async def funds(self, session):  # noqa: ANN001
            return {"available": 100}

    adapter = _LiveAdapter()
    registry = _Registry()
    store = _Store({("dhan", "111"): {"access_token": "good"}})
    app = _app(adapter, registry, store)
    NativeSessionRefresher(app).refresh_token("dhan")
    assert app.config["NATIVE_SESSION_STATUS"]["dhan:111"] == "ok"
