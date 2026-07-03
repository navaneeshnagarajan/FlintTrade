"""Tests for the native broker capture + activation routes (Phase 1 G4 + G9).

IndMoney is used as the exercise broker because its ``login()`` builds a session
from any non-empty access token WITHOUT calling the broker (validation is lazy,
on the first API call) and its SDK pin is ``None`` (creds-only activation gate),
so the full connect -> register -> rebuild -> login -> session path runs offline.

G9: every WRITE on these routes requires a valid operator session JWT — the
fixture mints one and ``_h()`` attaches it; the dedicated G9 tests pin the
401-without-JWT behaviour and the preserved loopback read allowance.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    # Other test modules set OPENALGO_API_KEY / FLINTTRADE_API_KEY via os.environ
    # directly (not monkeypatch), so the value leaks into this xdist worker and
    # makes require_auth demand a key. Unset them so these routes run in the
    # default no-key loopback-allowance mode deterministically.
    monkeypatch.delenv("OPENALGO_API_KEY", raising=False)
    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    # The interactive connect/relogin paths now VERIFY the session with a real
    # `funds` read (audit fix). Stub IndMoney's funds so the probe is
    # deterministic and never touches the network — tests that want a dead
    # token re-stub it to raise (see test_relogin_dead_token_surfaces_relogin).
    from flinttrade_gateway.brokers.indmoney import IndMoneyAdapter

    async def _ok_funds(_self, _session):
        return {"available_balance": 0.0}

    monkeypatch.setattr(IndMoneyAdapter, "funds", _ok_funds)
    (tmp_path / "master_password").write_text("native-routes-test-pw", encoding="utf-8")
    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, app, tmp_path


def _h() -> dict[str, str]:
    """Operator-session headers for account-management writes (G9)."""
    from flinttrade_core.auth_routes import _create_token

    return {"Authorization": f"Bearer {_create_token('nava', mode='explore')}"}


def _workspace_brokers(tmp_path):
    # A failed first-ever connect restores workspace.json to its prior state,
    # which for a fresh install (no file yet) means removing it — the app then
    # falls back to default_workspace_config(). Treat a missing file as {}.
    path = tmp_path / "workspace.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("brokers", {})


def test_connect_indmoney_stores_registers_and_establishes_session(client):
    c, app, tmp_path = client
    resp = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={
            "adapter_id": "indmoney",
            "account_id": "INDTEST01",
            "label": "IndMoney test",
            "credentials": {"access_token": "dummy-dashboard-token", "user_id": "INDTEST01"},
            "is_primary": True,
        },
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    data = body["data"]
    assert data["connected"] is True
    assert data["login"] == "ok"
    public_body = json.dumps(body)
    assert "INDTEST01" not in public_body
    assert "dummy-dashboard-token" not in public_body

    # Credentials persisted under the composite selector.
    store = app.config["CREDENTIAL_STORE"]
    creds = store.retrieve_for("indmoney", "INDTEST01")
    assert creds["access_token"] == "dummy-dashboard-token"

    # Selector registered + operator ACL'd + set as execution default.
    brokers = _workspace_brokers(tmp_path)
    assert "indmoney:INDTEST01" in brokers["registered"]
    assert brokers["account_acls"]["indmoney"]["INDTEST01"]  # non-empty actor list
    assert brokers["execution"]["default"] == "indmoney:INDTEST01"

    # Session registered in the registry.
    session = app.config["REGISTRY"].get_session_for("indmoney", "INDTEST01")
    assert session.adapter_id == "indmoney"


def test_connect_rejects_non_native_broker(client):
    c, _app, _tmp = client
    resp = c.post(
        "/api/v1/native/accounts",
        json={"adapter_id": "zerodha", "account_id": "Z1", "credentials": {"access_token": "x"}},
        headers=_h(),
    )
    assert resp.status_code == 400
    assert "not a native broker" in resp.get_json()["message"]


def test_connect_rejects_untrusted_identifiers_without_reflection(client):
    c, _app, _tmp = client
    payload = "<script>alert(1)</script>"

    bad_adapter = c.post(
        "/api/v1/native/accounts",
        json={"adapter_id": payload, "account_id": "Z1", "credentials": {"access_token": "x"}},
        headers=_h(),
    )
    bad_account = c.post(
        "/api/v1/native/accounts",
        json={"adapter_id": "indmoney", "account_id": payload, "credentials": {"access_token": "x"}},
        headers=_h(),
    )

    assert bad_adapter.status_code == 400
    assert payload not in bad_adapter.get_json()["message"]
    assert bad_account.status_code == 400
    assert payload not in bad_account.get_json()["message"]


def test_connect_requires_credentials(client):
    c, _app, _tmp = client
    resp = c.post("/api/v1/native/accounts", json={"adapter_id": "dhan", "account_id": "D1"}, headers=_h())
    assert resp.status_code == 400


def test_list_and_remove_native_account(client):
    c, app, tmp_path = client
    c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={
            "adapter_id": "indmoney",
            "account_id": "INDTEST02",
            "credentials": {"access_token": "tok2"},
        },
    )

    listing = c.get("/api/v1/native/accounts").get_json()["data"]["accounts"]
    entry = next(a for a in listing if a["account_id"] == "INDTEST02")
    assert entry["adapter_id"] == "indmoney"
    assert entry["has_session"] is True

    removed = c.delete("/api/v1/native/accounts/indmoney/INDTEST02", headers=_h())
    assert removed.status_code == 200

    # Selector deregistered and session gone.
    brokers = _workspace_brokers(tmp_path)
    assert "indmoney:INDTEST02" not in brokers.get("registered", [])
    with pytest.raises(Exception):
        app.config["REGISTRY"].get_session_for("indmoney", "INDTEST02")


def test_list_native_brokers_catalogue(client):
    c, _app, _tmp = client
    data = c.get("/api/v1/native/brokers").get_json()["data"]
    brokers = {b["adapter_id"]: b for b in data["brokers"]}
    assert set(brokers) == {"dhan", "upstox", "kotakneo", "indmoney"}
    # Proper display names — not .capitalize() ("Kotakneo"/"Indmoney").
    assert brokers["kotakneo"]["display_name"] == "Kotak Neo"
    assert brokers["indmoney"]["display_name"] == "INDmoney"
    # Dhan offers access-token AND pin+totp; Upstox offers OAuth AND direct token.
    dhan_methods = {m["id"] for m in brokers["dhan"]["auth_methods"]}
    assert {"access_token", "pin_totp"} <= dhan_methods
    upstox_kinds = {m["kind"] for m in brokers["upstox"]["auth_methods"]}
    assert "oauth" in upstox_kinds
    # Secret fields are flagged for masking.
    kotak = next(m for m in brokers["kotakneo"]["auth_methods"] if m["id"] == "totp_mpin")
    assert any(f["secret"] for f in kotak["fields"])


def test_oauth_start_returns_auth_url_and_state(client):
    c, _app, _tmp = client
    resp = c.post(
        "/api/v1/native/oauth/start",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXTEST", "api_key": "APIKEY", "api_secret": "SECRET"},
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert "api.upstox.com/v2/login/authorization/dialog" in data["auth_url"]
    assert "client_id=APIKEY" in data["auth_url"]
    assert data["state"] in data["auth_url"]
    assert data["redirect_uri"].endswith("/api/v1/native/oauth/callback")


def test_oauth_start_requires_api_key_and_secret(client):
    c, _app, _tmp = client
    resp = c.post("/api/v1/native/oauth/start", json={"adapter_id": "upstox", "account_id": "X"}, headers=_h())
    assert resp.status_code == 400


def test_oauth_callback_rejects_unknown_state(client):
    c, _app, _tmp = client
    resp = c.get("/api/v1/native/oauth/callback?code=abc&state=nonexistent")
    assert resp.status_code == 400
    assert "expired or invalid" in resp.get_data(as_text=True)


def test_relogin_replays_stored_credentials(client):
    c, app, _tmp = client
    c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "indmoney", "account_id": "INDTEST03", "credentials": {"access_token": "tok3"}},
    )
    # Drop the session, then re-login should re-establish it from stored creds.
    app.config["REGISTRY"].remove_session_for("indmoney", "INDTEST03")
    resp = c.post("/api/v1/native/accounts/indmoney/INDTEST03/login", headers=_h())
    assert resp.status_code == 200
    assert resp.get_json()["data"]["session"]["has_session"] is True


# ---------------------------------------------------------------------------
# G9 — account-management write guard
# ---------------------------------------------------------------------------


def test_write_without_jwt_is_rejected(client):
    """Any local process can reach 127.0.0.1 — but only the operator's
    authenticated app session may mutate broker registration/credentials."""
    c, _app, _tmp = client
    resp = c.post(
        "/api/v1/native/accounts",
        json={"adapter_id": "indmoney", "account_id": "NOJWT", "credentials": {"access_token": "x"}},
    )
    assert resp.status_code == 401
    assert "logged-in session" in resp.get_json()["message"]


def test_write_with_invalid_jwt_is_rejected(client):
    c, _app, _tmp = client
    resp = c.delete(
        "/api/v1/native/accounts/indmoney/X",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 401


def test_reads_keep_the_loopback_allowance(client):
    """GET list/brokers stay JWT-free — the local capture UI reads them before
    and after login, and they only reveal presence/status, never credentials."""
    c, _app, _tmp = client
    assert c.get("/api/v1/native/brokers").status_code == 200
    assert c.get("/api/v1/native/accounts").status_code == 200


def test_gateway_bp_writes_require_jwt_in_real_app(client):
    """The legacy gateway /v1/accounts* writes get the same guard, injected by
    the app factory via BROKER_MGMT_WRITE_GUARD (G9)."""
    c, _app, _tmp = client
    resp = c.post("/v1/accounts", json={"broker": "dhan", "credentials": {}})
    assert resp.status_code == 401
    # With a valid operator JWT the guard passes (the request then proceeds to
    # normal validation — anything but 401 proves the guard admitted it).
    resp = c.post("/v1/accounts", json={"broker": "dhan", "credentials": {}}, headers=_h())
    assert resp.status_code != 401
    # Reads keep the loopback allowance.
    assert c.get("/v1/accounts").status_code == 200


# ---------------------------------------------------------------------------
# G7 — needs-fresh-login surface
# ---------------------------------------------------------------------------


def test_sessionless_account_with_failed_replay_surfaces_needs_relogin(client):
    """A stored account whose last replay attempt failed shows needs_relogin +
    the actionable reason — not just a bare "no live session" (G7)."""
    c, app, _tmp = client
    c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "indmoney", "account_id": "INDG7", "credentials": {"access_token": "tok"}},
    )
    # Simulate the next boot: session gone, replay failed on stale credentials.
    app.config["REGISTRY"].remove_session_for("indmoney", "INDG7")
    app.config.setdefault("NATIVE_SESSION_STATUS", {})["indmoney:INDG7"] = (
        "login-failed: IndMoney login requires an access_token"
    )

    listing = c.get("/api/v1/native/accounts").get_json()["data"]["accounts"]
    entry = next(a for a in listing if a["account_id"] == "INDG7")
    assert entry["has_session"] is False
    assert entry["needs_relogin"] is True
    assert "login-failed" in entry["login_error"]


def test_connected_account_has_no_relogin_flag(client):
    c, _app, _tmp = client
    c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "indmoney", "account_id": "INDG7B", "credentials": {"access_token": "tok"}},
    )
    listing = c.get("/api/v1/native/accounts").get_json()["data"]["accounts"]
    entry = next(a for a in listing if a["account_id"] == "INDG7B")
    assert entry["has_session"] is True
    assert "needs_relogin" not in entry


def test_connect_schedules_a_daily_refresh_job(client):
    """A broker connected at runtime (after boot) gets its 08:05 IST refresh
    job on the already-running rotator (audit finding G5)."""
    c, app, _tmp = client
    c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "indmoney", "account_id": "INDJOB", "credentials": {"access_token": "tok"}},
    )
    rotator = app.config.get("CREDENTIALS_ROTATOR")
    assert rotator is not None
    assert "cred_refresh_indmoney" in rotator._job_ids


def test_relogin_with_fresh_credentials_preserves_label_and_primary(client):
    """Re-authenticating an existing account must not reset its label to the
    adapter id or clear is_primary (audit finding: relogin clobbers metadata)."""
    c, _app, tmp_path = client
    c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={
            "adapter_id": "indmoney", "account_id": "INDLBL",
            "label": "My IND", "credentials": {"access_token": "tok"}, "is_primary": True,
        },
    )
    resp = c.post(
        "/api/v1/native/accounts/indmoney/INDLBL/login",
        headers=_h(),
        json={"credentials": {"access_token": "fresh-tok"}},
    )
    assert resp.status_code == 200
    listing = c.get("/api/v1/native/accounts").get_json()["data"]["accounts"]
    entry = next(a for a in listing if a["account_id"] == "INDLBL")
    assert entry["label"] == "My IND"
    assert entry["is_primary"] is True


def test_connect_dead_token_surfaces_needs_relogin_not_false_success(client, monkeypatch):
    """Re-audit fix: the interactive connect path now probes the token with a
    real funds read, so a dead token reports needs_relogin instead of a false
    'connected' (the token-replay logins build a Session without a broker call)."""
    from flinttrade_gateway.brokers.indmoney import IndMoneyAdapter

    async def _dead_funds(_self, _session):
        raise RuntimeError("401 token expired")

    monkeypatch.setattr(IndMoneyAdapter, "funds", _dead_funds)
    c, _app, _tmp = client
    resp = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "indmoney", "account_id": "INDDEAD", "credentials": {"access_token": "dead"}},
    )
    # Login could not be verified → not connected → 502, and the vault row is
    # not left dead-credential'd.
    assert resp.status_code == 502
    body = resp.get_json()
    assert body["data"]["connected"] is False
    public_body = json.dumps(body)
    assert "INDDEAD" not in public_body
    assert "dead" not in public_body


def test_relogin_dead_token_surfaces_relogin(client, monkeypatch):
    """The interactive Re-authenticate path probes too — a dead replayed token
    drops the session and records login-failed (needs_relogin), not a false ok."""
    c, app, _tmp = client
    # First connect with the passing stub (fixture default) so the account exists.
    c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "indmoney", "account_id": "INDRL", "credentials": {"access_token": "tok"}},
    )
    # Now the token has "gone dead": funds probe fails on re-authenticate.
    from flinttrade_gateway.brokers.indmoney import IndMoneyAdapter

    async def _dead_funds(_self, _session):
        raise RuntimeError("401 token expired")

    monkeypatch.setattr(IndMoneyAdapter, "funds", _dead_funds)
    resp = c.post("/api/v1/native/accounts/indmoney/INDRL/login", headers=_h())
    assert resp.status_code == 502
    assert resp.get_json()["data"]["session"]["has_session"] is False
    # The accounts list surfaces the honest needs_relogin state.
    listing = c.get("/api/v1/native/accounts").get_json()["data"]["accounts"]
    entry = next(a for a in listing if a["account_id"] == "INDRL")
    assert entry["needs_relogin"] is True


def test_failed_reconnect_restores_prior_good_credentials(client, monkeypatch):
    """Re-audit fix #3: re-connecting an EXISTING account with bad creds must
    not destroy the previously-good vault row — on failure it is restored, and
    the selector is NOT orphaned."""
    c, app, tmp_path = client
    # Connect once (good token, passing probe from the fixture stub).
    c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "indmoney", "account_id": "INDRESTORE",
              "label": "Keep me", "credentials": {"access_token": "good-token"}, "is_primary": True},
    )
    store = app.config["CREDENTIAL_STORE"]
    assert store.retrieve_for("indmoney", "INDRESTORE")["access_token"] == "good-token"

    # Reconnect with a token whose probe fails.
    from flinttrade_gateway.brokers.indmoney import IndMoneyAdapter

    async def _dead_funds(_self, _session):
        raise RuntimeError("401 token expired")

    monkeypatch.setattr(IndMoneyAdapter, "funds", _dead_funds)
    resp = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "indmoney", "account_id": "INDRESTORE", "credentials": {"access_token": "bad-token"}},
    )
    assert resp.status_code == 502
    # The prior good credentials survive; the selector is still registered.
    assert store.retrieve_for("indmoney", "INDRESTORE")["access_token"] == "good-token"
    assert "indmoney:INDRESTORE" in _workspace_brokers(tmp_path).get("registered", [])


def test_failed_new_connect_purges_and_deregisters(client, monkeypatch):
    """A failed BRAND-NEW connect leaves nothing orphaned: no vault row, no
    registered selector."""
    from flinttrade_gateway.brokers.indmoney import IndMoneyAdapter

    async def _dead_funds(_self, _session):
        raise RuntimeError("401 token expired")

    monkeypatch.setattr(IndMoneyAdapter, "funds", _dead_funds)
    c, app, tmp_path = client
    resp = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "indmoney", "account_id": "INDNEW", "credentials": {"access_token": "dead"}},
    )
    assert resp.status_code == 502
    store = app.config["CREDENTIAL_STORE"]
    import pytest as _pt
    with _pt.raises(Exception):
        store.retrieve_for("indmoney", "INDNEW")
    assert "indmoney:INDNEW" not in _workspace_brokers(tmp_path).get("registered", [])


def test_failed_new_connect_preserves_a_prior_working_execution_default(client, monkeypatch):
    """Re-audit fix (HIGH): a failed new connect with is_primary=True must NOT
    blank a pre-existing working execution.default — that would brick the order
    path on the next router rebuild/restart. The transactional rollback restores
    it exactly."""
    c, app, tmp_path = client
    # Establish a working primary first (passing probe from the fixture stub).
    c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "indmoney", "account_id": "PRIMARY1",
              "credentials": {"access_token": "good"}, "is_primary": True},
    )
    assert _workspace_brokers(tmp_path)["execution"]["default"] == "indmoney:PRIMARY1"

    # A new connect for a different account, is_primary=True, whose probe fails.
    from flinttrade_gateway.brokers.indmoney import IndMoneyAdapter

    async def _dead_funds(_self, _session):
        raise RuntimeError("401 token expired")

    monkeypatch.setattr(IndMoneyAdapter, "funds", _dead_funds)
    resp = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "indmoney", "account_id": "BADNEW",
              "credentials": {"access_token": "dead"}, "is_primary": True},
    )
    assert resp.status_code == 502
    brokers = _workspace_brokers(tmp_path)
    # The prior working default survives; the failed selector is not registered.
    assert brokers["execution"]["default"] == "indmoney:PRIMARY1"
    assert "indmoney:BADNEW" not in brokers.get("registered", [])


def test_failed_reconnect_restores_label_and_is_primary(client, monkeypatch):
    """Re-audit fix: a failed reconnect restores the full prior vault row —
    label and is_primary, not just the credential payload."""
    c, app, tmp_path = client
    c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "indmoney", "account_id": "META1", "label": "Original label",
              "credentials": {"access_token": "good"}, "is_primary": True},
    )
    from flinttrade_gateway.brokers.indmoney import IndMoneyAdapter

    async def _dead_funds(_self, _session):
        raise RuntimeError("401 token expired")

    monkeypatch.setattr(IndMoneyAdapter, "funds", _dead_funds)
    c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "indmoney", "account_id": "META1", "label": "New bad label",
              "credentials": {"access_token": "bad"}, "is_primary": False},
    )
    row = next(r for r in app.config["CREDENTIAL_STORE"].list_accounts() if r["account_id"] == "META1")
    assert row["label"] == "Original label"
    assert bool(row["is_primary"]) is True
