"""Tests for the native broker capture + activation routes (Phase 1 G4 + G9).

Upstox (its direct access-token method) is the exercise broker: ``login()`` builds
a session from any non-empty access token WITHOUT calling the broker (validation is
lazy, on the first API call), so the full connect -> register -> rebuild -> login ->
session path runs offline. Dhan, Upstox, and INDmoney are connectable natives;
Kotak Neo and Groww are catalogued 'coming soon' and rejected on connect until
their remaining live blockers clear.

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
    # `funds` read (audit fix). Stub Upstox's funds so the probe is
    # deterministic and never touches the network — tests that want a dead
    # token re-stub it to raise (see test_relogin_dead_token_surfaces_relogin).
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    async def _ok_funds(_self, _session):
        return {"available_balance": 0.0}

    monkeypatch.setattr(UpstoxAdapter, "funds", _ok_funds)
    (tmp_path / "master_password").write_text("native-routes-test-pw", encoding="utf-8")
    from flinttrade_core import native_account_routes as native_routes
    from flinttrade_core.app import create_flask_app

    native_routes._OAUTH_PENDING.clear()
    app = create_flask_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, app, tmp_path
    native_routes._OAUTH_PENDING.clear()


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


def test_connect_upstox_stores_registers_and_establishes_session(client):
    c, app, tmp_path = client
    resp = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={
            "adapter_id": "upstox",
            "account_id": "UPXTEST01",
            "label": "Upstox test",
            "credentials": {"access_token": "dummy-token"},
            "is_primary": True,
        },
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    data = body["data"]
    assert data["connected"] is True
    assert data["login"] == "ok"
    public_body = json.dumps(body)
    assert "UPXTEST01" not in public_body
    assert "dummy-token" not in public_body

    # Credentials persisted under the composite selector.
    store = app.config["CREDENTIAL_STORE"]
    creds = store.retrieve_for("upstox", "UPXTEST01")
    assert creds["access_token"] == "dummy-token"

    # Selector registered + operator ACL'd + set as execution default.
    brokers = _workspace_brokers(tmp_path)
    assert "upstox:UPXTEST01" in brokers["registered"]
    assert brokers["account_acls"]["upstox"]["UPXTEST01"]  # non-empty actor list
    assert brokers["execution"]["default"] == "upstox:UPXTEST01"

    # Session registered in the registry.
    session = app.config["REGISTRY"].get_session_for("upstox", "UPXTEST01")
    assert session.adapter_id == "upstox"


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
        json={"adapter_id": "upstox", "account_id": payload, "credentials": {"access_token": "x"}},
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
            "adapter_id": "upstox",
            "account_id": "UPXTEST02",
            "credentials": {"access_token": "tok2"},
        },
    )

    listing = c.get("/api/v1/native/accounts").get_json()["data"]["accounts"]
    entry = next(a for a in listing if a["account_id"] == "UPXTEST02")
    assert entry["adapter_id"] == "upstox"
    assert entry["has_session"] is True
    assert entry["read_only"] is False

    removed = c.delete("/api/v1/native/accounts/upstox/UPXTEST02", headers=_h())
    assert removed.status_code == 200

    # Selector deregistered and session gone.
    brokers = _workspace_brokers(tmp_path)
    assert "upstox:UPXTEST02" not in brokers.get("registered", [])
    with pytest.raises(Exception):
        app.config["REGISTRY"].get_session_for("upstox", "UPXTEST02")


def test_remove_primary_native_account_falls_back_to_registered_default(client):
    """Deleting the active primary must not leave brokers.execution.default blank."""
    c, app, tmp_path = client
    connected = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={
            "adapter_id": "upstox",
            "account_id": "UPXPRIMARYDEL",
            "credentials": {"access_token": "tok-primary"},
            "is_primary": True,
        },
    )
    assert connected.status_code == 200, connected.get_json()
    assert _workspace_brokers(tmp_path)["execution"]["default"] == "upstox:UPXPRIMARYDEL"

    removed = c.delete("/api/v1/native/accounts/upstox/UPXPRIMARYDEL", headers=_h())
    assert removed.status_code == 200

    brokers = _workspace_brokers(tmp_path)
    assert "upstox:UPXPRIMARYDEL" not in brokers.get("registered", [])
    assert brokers["execution"]["default"] == "openalgo:default"
    from flinttrade_gateway.routing_config import RoutingConfig

    RoutingConfig.from_workspace(brokers)
    assert app.config["BROKER_ROUTER"] is not None


def test_remove_native_account_is_selector_scoped(client):
    """A wrong adapter path must not delete another broker's vault row."""
    c, app, tmp_path = client
    store = app.config["CREDENTIAL_STORE"]
    registry = app.config["REGISTRY"]

    store.store(
        "SHARED01",
        "dhan",
        "Dhan shared id",
        {"client_id": "SHARED01", "access_token": "dhan-token"},
        is_primary=True,
        adapter_id="dhan",
    )
    from flinttrade_gateway.brokers._base import Session

    registry.put_session(
        "dhan",
        "SHARED01",
        Session(
            access_token="dhan-token",
            expires_at=9e9,
            account_id="SHARED01",
            adapter_id="dhan",
        ),
    )
    from flinttrade_core.native_account_routes import _register_selector_in_workspace

    _register_selector_in_workspace("dhan", "SHARED01", "nava", True)

    removed = c.delete("/api/v1/native/accounts/upstox/SHARED01", headers=_h())
    assert removed.status_code == 200

    assert store.retrieve_for("dhan", "SHARED01")["access_token"] == "dhan-token"
    assert registry.get_session_for("dhan", "SHARED01").adapter_id == "dhan"
    brokers = _workspace_brokers(tmp_path)
    assert "dhan:SHARED01" in brokers.get("registered", [])


def test_list_native_brokers_catalogue(client, monkeypatch):
    c, _app, _tmp = client
    from flinttrade_core import native_account_routes as native_routes

    monkeypatch.setattr(
        native_routes,
        "_sdk_attestations_by_pin",
        lambda: {
            "dhanhq": {
                "pin": "dhanhq",
                "pinned_version": "2.2.0",
                "installed_version": "2.2.0",
                "status": "ok",
            },
            "neo-api-client": {
                "pin": "neo-api-client",
                "pinned_version": "2.0.0",
                "installed_version": "2.0.0",
                "status": "ok",
            },
        },
    )
    data = c.get("/api/v1/native/brokers").get_json()["data"]
    brokers = {b["adapter_id"]: b for b in data["brokers"]}
    assert set(brokers) == {"dhan", "upstox", "kotakneo", "indmoney", "groww"}
    # Proper display names — not .capitalize() ("Kotakneo"/"Indmoney").
    assert brokers["kotakneo"]["display_name"] == "Kotak Neo"
    assert brokers["indmoney"]["display_name"] == "INDmoney"
    # Dhan offers OAuth, access-token AND pin+totp; Upstox offers OAuth AND direct token.
    dhan_methods = {m["id"] for m in brokers["dhan"]["auth_methods"]}
    assert {"oauth", "access_token", "pin_totp"} <= dhan_methods
    upstox_kinds = {m["kind"] for m in brokers["upstox"]["auth_methods"]}
    assert "oauth" in upstox_kinds
    assert brokers["dhan"]["connectable"] is True
    assert {broker_id for broker_id, row in brokers.items() if row["requires_static_ip"]} == {
        "dhan",
        "upstox",
        "kotakneo",
        "indmoney",
        "groww",
    }
    assert brokers["dhan"]["sdk_pin"] == "dhanhq"
    assert brokers["dhan"]["sdk_attestation"] == {
        "pin": "dhanhq",
        "pinned_version": "2.2.0",
        "installed_version": "2.2.0",
        "status": "ok",
    }
    assert brokers["upstox"]["connectable"] is True
    assert brokers["indmoney"]["connectable"] is True
    assert brokers["indmoney"]["sdk_pin"] is None
    assert brokers["indmoney"]["sdk_attestation"]["status"] == "not_required"
    assert brokers["kotakneo"]["connectable"] is False
    assert brokers["kotakneo"]["sdk_pin"] == "neo-api-client"
    assert brokers["kotakneo"]["sdk_attestation"]["status"] == "ok"
    assert {"BCD", "MCX"} <= set(brokers["kotakneo"]["exchanges"])
    assert brokers["groww"]["connectable"] is False
    assert "MCX" in brokers["groww"]["exchanges"]
    assert brokers["dhan"]["mcp"]["remote_url"] == "https://mcp.dhan.co/mcp"
    assert brokers["dhan"]["mcp"]["trading_supported"] is True
    dhan_mcp_configs = {c["id"]: c for c in brokers["dhan"]["mcp"]["client_configs"]}
    assert dhan_mcp_configs["claude_code"]["command"] == "claude"
    assert dhan_mcp_configs["claude_code"]["args"] == [
        "mcp",
        "add",
        "--transport",
        "http",
        "dhan",
        "https://mcp.dhan.co/mcp",
    ]
    assert dhan_mcp_configs["codex_cli"]["command"] == "codex"
    assert dhan_mcp_configs["codex_cli"]["args"] == [
        "mcp",
        "add",
        "dhan",
        "--url",
        "https://mcp.dhan.co/mcp",
    ]
    assert dhan_mcp_configs["cursor"]["config"]["mcpServers"]["dhan"]["url"] == "https://mcp.dhan.co/mcp"
    assert dhan_mcp_configs["vscode_copilot"]["config"]["mcp"]["servers"]["dhan"]["url"] == (
        "https://mcp.dhan.co/mcp"
    )
    assert dhan_mcp_configs["kiro"]["config"]["mcpServers"]["dhan"]["url"] == "https://mcp.dhan.co/mcp"
    assert dhan_mcp_configs["dhanhq_skill_pack"]["command"] == "skills"
    assert "option chain with Greeks" in " ".join(brokers["dhan"]["mcp"]["use_cases"])
    assert brokers["upstox"]["mcp"]["remote_url"] == "https://mcp.upstox.com/mcp"
    assert brokers["upstox"]["mcp"]["read_only"] is True
    assert brokers["upstox"]["mcp"]["trading_supported"] is False
    upstox_mcp_configs = {c["id"]: c for c in brokers["upstox"]["mcp"]["client_configs"]}
    assert upstox_mcp_configs["vscode_copilot"]["config"]["mcp"]["servers"]["Upstox MCP"] == {
        "url": "https://mcp.upstox.com/mcp",
    }
    assert brokers["indmoney"]["mcp"] is None
    assert brokers["groww"]["mcp"]["remote_url"] == "https://mcp.groww.in/mcp"
    assert brokers["groww"]["mcp"]["trading_supported"] is True
    assert brokers["groww"]["mcp"]["client_configs"][0]["config"]["name"] == "GrowwMCP"
    assert brokers["groww"]["mcp"]["client_configs"][1]["config"]["mcpServers"]["growwmcp"]["args"] == [
        "mcp-remote@0.1.18",
        "https://mcp.groww.in/mcp",
        "52155",
    ]
    groww_cautions = " ".join(brokers["groww"]["mcp"]["cautions"])
    assert "approving the API-key session in Groww Cloud" in groww_cautions
    assert "market-data/API permissions, static IP setup" in groww_cautions
    indmoney = next(m for m in brokers["indmoney"]["auth_methods"] if m["id"] == "access_token")
    assert "INDstocks API dashboard" in indmoney["description"]
    assert "static outbound IP" in indmoney["description"]
    assert "06:00 IST" in indmoney["description"]
    assert "five active tokens" in indmoney["description"]
    indmoney_fields = {f["name"]: f for f in indmoney["fields"]}
    assert "daily 06:00 IST reset" in indmoney_fields["access_token"]["help"]
    groww = next(m for m in brokers["groww"]["auth_methods"] if m["id"] == "access_token")
    assert "Groww Cloud/API Keys" in groww["description"]
    assert "06:00 IST" in groww["description"]
    groww_fields = {f["name"]: f for f in groww["fields"]}
    assert groww_fields["access_token"]["secret"] is True
    assert "06:00 IST expiry" in groww_fields["access_token"]["help"]
    groww_secret = next(m for m in brokers["groww"]["auth_methods"] if m["id"] == "api_key_secret")
    assert "passed with an approved key" in groww_secret["description"]
    groww_secret_fields = {f["name"]: f for f in groww_secret["fields"]}
    assert "session approval is required" in groww_secret_fields["api_secret"]["help"]
    # Secret fields are flagged for masking.
    kotak = next(m for m in brokers["kotakneo"]["auth_methods"] if m["id"] == "totp_mpin")
    assert any(f["secret"] for f in kotak["fields"])
    kotak_fields = {f["name"]: f for f in kotak["fields"]}
    assert kotak_fields["access_token"]["secret"] is True
    assert kotak_fields["access_token"]["required"] is True
    assert "SDK's consumer_key" in kotak_fields["access_token"]["help"]
    assert "consumer_key" not in kotak_fields


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
    assert data["postback_uri"].endswith("/api/v1/native/postbacks/upstox")


def test_dhan_oauth_start_generates_consent_url(client, monkeypatch):
    c, _app, _tmp = client
    from flinttrade_gateway.brokers.dhan import DhanAdapter

    seen = {}

    def _fake_builder(app_id, redirect_uri, state, *, account_id="", api_secret=""):
        seen.update({
            "app_id": app_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "account_id": account_id,
            "api_secret": api_secret,
        })
        return "https://auth.dhan.co/login/consentApp-login?consentAppId=CONSENT1"

    monkeypatch.setattr(DhanAdapter, "build_login_url", staticmethod(_fake_builder))
    resp = c.post(
        "/api/v1/native/oauth/start",
        headers=_h(),
        json={"adapter_id": "dhan", "account_id": "DHANCLIENT1", "api_key": "APPID", "api_secret": "SECRET"},
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["auth_url"].startswith("https://auth.dhan.co/login/consentApp-login")
    assert seen["app_id"] == "APPID"
    assert seen["account_id"] == "DHANCLIENT1"
    assert seen["api_secret"] == "SECRET"
    assert seen["redirect_uri"].endswith("/api/v1/native/oauth/callback")
    assert seen["state"] == data["state"]
    assert data["postback_uri"].endswith("/api/v1/native/postbacks/dhan")


def test_oauth_start_builder_failure_drops_pending_secret(client, monkeypatch, caplog):
    c, _app, _tmp = client
    from flinttrade_core import native_account_routes as native_routes
    from flinttrade_gateway.brokers.dhan import DhanAdapter

    def _bad_builder(_app_id, _redirect_uri, _state, *, account_id="", api_secret=""):
        raise RuntimeError(f"broker payload included {account_id} {api_secret}")

    monkeypatch.setattr(DhanAdapter, "build_login_url", staticmethod(_bad_builder))
    resp = c.post(
        "/api/v1/native/oauth/start",
        headers=_h(),
        json={"adapter_id": "dhan", "account_id": "DHANCLIENT1", "api_key": "APPID", "api_secret": "SECRET"},
    )
    assert resp.status_code == 502
    assert resp.get_json()["message"] == "Could not start broker OAuth login."
    assert native_routes._OAUTH_PENDING == {}
    visible = json.dumps(resp.get_json()) + caplog.text
    assert "DHANCLIENT1" not in visible
    assert "SECRET" not in visible


def test_oauth_start_requires_api_key_and_secret(client):
    c, _app, _tmp = client
    resp = c.post("/api/v1/native/oauth/start", json={"adapter_id": "upstox", "account_id": "X"}, headers=_h())
    assert resp.status_code == 400


def test_oauth_callback_rejects_unknown_state(client):
    c, _app, _tmp = client
    resp = c.get("/api/v1/native/oauth/callback?code=abc&state=nonexistent")
    assert resp.status_code == 400
    assert "expired or invalid" in resp.get_data(as_text=True)


def test_dhan_oauth_callback_accepts_token_id_without_state_when_single_pending(client, monkeypatch):
    c, _app, _tmp = client
    from flinttrade_core import native_account_routes as native_routes

    native_routes._OAUTH_PENDING["DHANSTATE"] = {
        "adapter_id": "dhan",
        "account_id": "DHANCLIENT1",
        "api_key": "APPID",
        "api_secret": "SECRET",
        "redirect_uri": "http://127.0.0.1:5100/api/v1/native/oauth/callback",
        "label": "Dhan",
        "is_primary": True,
        "ts": native_routes.time.time(),
    }
    captured = {}

    def _fake_connect(adapter_id, account_id, label, credentials, is_primary):
        captured.update({
            "adapter_id": adapter_id,
            "account_id": account_id,
            "label": label,
            "credentials": credentials,
            "is_primary": is_primary,
        })
        return {"status": "success", "data": {"connected": True}}, 200

    monkeypatch.setattr(native_routes, "_do_connect", _fake_connect)

    resp = c.get("/api/v1/native/oauth/callback?tokenId=TOKENID1")

    assert resp.status_code == 200
    assert "account connected" in resp.get_data(as_text=True)
    assert "DHANCLIENT1" not in resp.get_data(as_text=True)
    assert "DHANSTATE" not in native_routes._OAUTH_PENDING
    assert captured["adapter_id"] == "dhan"
    assert captured["account_id"] == "DHANCLIENT1"
    assert captured["is_primary"] is True
    assert captured["credentials"]["code"] == "TOKENID1"
    assert captured["credentials"]["token_id"] == "TOKENID1"
    assert captured["credentials"]["client_id"] == "DHANCLIENT1"
    assert captured["credentials"]["app_id"] == "APPID"
    assert captured["credentials"]["api_key"] == "APPID"
    assert captured["credentials"]["api_secret"] == "SECRET"


def test_dhan_oauth_callback_without_state_fails_closed_when_ambiguous(client, monkeypatch):
    c, _app, _tmp = client
    from flinttrade_core import native_account_routes as native_routes

    now = native_routes.time.time()
    for state, account_id in (("DHANSTATE1", "DHANCLIENT1"), ("DHANSTATE2", "DHANCLIENT2")):
        native_routes._OAUTH_PENDING[state] = {
            "adapter_id": "dhan",
            "account_id": account_id,
            "api_key": "APPID",
            "api_secret": "SECRET",
            "redirect_uri": "http://127.0.0.1:5100/api/v1/native/oauth/callback",
            "label": "Dhan",
            "is_primary": False,
            "ts": now,
        }

    def _unexpected_connect(*_args, **_kwargs):
        raise AssertionError("ambiguous Dhan callback must not connect")

    monkeypatch.setattr(native_routes, "_do_connect", _unexpected_connect)

    resp = c.get("/api/v1/native/oauth/callback?tokenId=TOKENID1")

    assert resp.status_code == 400
    assert "ambiguous" in resp.get_data(as_text=True)
    assert set(native_routes._OAUTH_PENDING) == {"DHANSTATE1", "DHANSTATE2"}


def test_oauth_callback_without_state_does_not_accept_plain_authorisation_code(client, monkeypatch):
    c, _app, _tmp = client
    from flinttrade_core import native_account_routes as native_routes

    native_routes._OAUTH_PENDING["UPXSTATE"] = {
        "adapter_id": "upstox",
        "account_id": "UPXCLIENT1",
        "api_key": "APPID",
        "api_secret": "SECRET",
        "redirect_uri": "http://127.0.0.1:5100/api/v1/native/oauth/callback",
        "label": "Upstox",
        "is_primary": False,
        "ts": native_routes.time.time(),
    }

    def _unexpected_connect(*_args, **_kwargs):
        raise AssertionError("non-Dhan OAuth callback must require state")

    monkeypatch.setattr(native_routes, "_do_connect", _unexpected_connect)

    resp = c.get("/api/v1/native/oauth/callback?code=AUTHCODE")

    assert resp.status_code == 400
    assert "expired or invalid" in resp.get_data(as_text=True)
    assert "UPXSTATE" in native_routes._OAUTH_PENDING


def test_native_postback_accepts_without_operator_jwt(client):
    c, app, _tmp = client
    resp = c.post(
        "/api/v1/native/postbacks/upstox",
        json={
            "update_type": "order",
            "order_id": "OID123",
            "user_id": "U1",
            "access_token": "tok_live_secret_1234567890",
            "status": "complete",
            "nested": {
                "clientId": "client-secret-1234567890",
                "primary_ip": "203.0.113.10",
                "note": "filled by user test@example.com from +919876543210",
            },
        },
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["accepted"] is True
    event = app.config["NATIVE_POSTBACK_EVENTS"]["upstox"][-1]
    assert event["update_type"] == "order"
    assert event["payload"]["order_id"] == "[redacted]"
    assert event["payload"]["user_id"] == "[redacted]"
    assert event["payload"]["access_token"] == "[redacted]"
    assert event["payload"]["nested"]["clientId"] == "[redacted]"
    assert event["payload"]["nested"]["primary_ip"] == "[redacted]"
    assert event["payload"]["nested"]["note"] == "filled by user [redacted] from [redacted]"
    assert event["payload"]["status"] == "complete"


def test_native_postback_raw_field_is_redacted(client):
    c, app, _tmp = client
    resp = c.post(
        "/api/v1/native/postbacks/upstox",
        json={"update_type": "order", "raw": "token=tok_live_secret_1234567890&client_id=ABC123"},
    )
    assert resp.status_code == 200
    event = app.config["NATIVE_POSTBACK_EVENTS"]["upstox"][-1]
    assert event["payload"]["raw"] == "[redacted]"


def test_native_postback_rejects_unknown_adapter(client):
    c, _app, _tmp = client
    resp = c.post("/api/v1/native/postbacks/notabroker", json={"update_type": "order"})
    assert resp.status_code == 404


def test_relogin_replays_stored_credentials(client):
    c, app, _tmp = client
    c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXTEST03", "credentials": {"access_token": "tok3"}},
    )
    # Drop the session, then re-login should re-establish it from stored creds.
    app.config["REGISTRY"].remove_session_for("upstox", "UPXTEST03")
    resp = c.post("/api/v1/native/accounts/upstox/UPXTEST03/login", headers=_h())
    assert resp.status_code == 200
    assert resp.get_json()["data"]["session"]["has_session"] is True
    assert resp.get_json()["data"]["session"]["read_only"] is False


def test_list_native_account_surfaces_read_only_sessions(client):
    c, _app, _tmp = client
    resp = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={
            "adapter_id": "upstox",
            "account_id": "UPXREADONLY",
            "credentials": {
                "access_token": "tok-read-only",
                "read_only": "true",
                "token_scope": "analytics",
            },
        },
    )
    assert resp.status_code == 200, resp.get_json()

    listing = c.get("/api/v1/native/accounts").get_json()["data"]["accounts"]
    entry = next(a for a in listing if a["account_id"] == "UPXREADONLY")
    assert entry["has_session"] is True
    assert entry["read_only"] is True

    relogin = c.post("/api/v1/native/accounts/upstox/UPXREADONLY/login", headers=_h())
    assert relogin.status_code == 200
    assert relogin.get_json()["data"]["session"]["read_only"] is True


def test_connect_read_only_session_cannot_become_execution_default(client):
    c, app, tmp_path = client
    resp = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={
            "adapter_id": "upstox",
            "account_id": "UPXREADONLYPRIMARY",
            "credentials": {
                "access_token": "tok-read-only-primary",
                "read_only": "true",
                "token_scope": "analytics",
            },
            "is_primary": True,
        },
    )
    assert resp.status_code == 200, resp.get_json()

    brokers = _workspace_brokers(tmp_path)
    assert "upstox:UPXREADONLYPRIMARY" in brokers["registered"]
    assert brokers["execution"]["default"] == "openalgo:default"

    listing = c.get("/api/v1/native/accounts").get_json()["data"]["accounts"]
    entry = next(a for a in listing if a["account_id"] == "UPXREADONLYPRIMARY")
    assert entry["has_session"] is True
    assert entry["read_only"] is True
    assert entry["is_primary"] is False

    row = next(
        r for r in app.config["CREDENTIAL_STORE"].list_accounts()
        if r["account_id"] == "UPXREADONLYPRIMARY"
    )
    assert row["is_primary"] is False
    assert app.config["BROKER_ROUTER"] is not None


def test_relogin_read_only_session_cannot_remain_execution_default(client):
    c, app, tmp_path = client
    connected = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={
            "adapter_id": "upstox",
            "account_id": "UPXREADONLYREFRESH",
            "label": "Upstox primary refresh",
            "credentials": {"access_token": "tok-write-capable"},
            "is_primary": True,
        },
    )
    assert connected.status_code == 200, connected.get_json()
    assert _workspace_brokers(tmp_path)["execution"]["default"] == "upstox:UPXREADONLYREFRESH"

    relogin = c.post(
        "/api/v1/native/accounts/upstox/UPXREADONLYREFRESH/login",
        headers=_h(),
        json={
            "credentials": {
                "access_token": "tok-read-only-refresh",
                "read_only": "true",
                "token_scope": "analytics",
            },
        },
    )
    assert relogin.status_code == 200, relogin.get_json()
    assert relogin.get_json()["data"]["session"]["read_only"] is True

    brokers = _workspace_brokers(tmp_path)
    assert "upstox:UPXREADONLYREFRESH" in brokers["registered"]
    assert brokers["execution"]["default"] == "openalgo:default"

    listing = c.get("/api/v1/native/accounts").get_json()["data"]["accounts"]
    entry = next(a for a in listing if a["account_id"] == "UPXREADONLYREFRESH")
    assert entry["read_only"] is True
    assert entry["is_primary"] is False

    row = next(
        r for r in app.config["CREDENTIAL_STORE"].list_accounts()
        if r["account_id"] == "UPXREADONLYREFRESH"
    )
    assert row["is_primary"] is False


# ---------------------------------------------------------------------------
# G9 — account-management write guard
# ---------------------------------------------------------------------------


def test_write_without_jwt_is_rejected(client):
    """Any local process can reach 127.0.0.1 — but only the operator's
    authenticated app session may mutate broker registration/credentials."""
    c, _app, _tmp = client
    resp = c.post(
        "/api/v1/native/accounts",
        json={"adapter_id": "upstox", "account_id": "NOJWT", "credentials": {"access_token": "x"}},
    )
    assert resp.status_code == 401
    assert "logged-in session" in resp.get_json()["message"]


def test_write_with_invalid_jwt_is_rejected(client):
    c, _app, _tmp = client
    resp = c.delete(
        "/api/v1/native/accounts/upstox/X",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 401


def test_reads_keep_the_loopback_allowance(client):
    """GET list/brokers stay JWT-free — the local capture UI reads them before
    and after login, and they only reveal presence/status, never credentials."""
    c, _app, _tmp = client
    assert c.get("/api/v1/native/brokers").status_code == 200
    assert c.get("/api/v1/native/accounts").status_code == 200


def test_native_account_reads_include_orders_and_trades(client, monkeypatch):
    """The terminal account widgets can use a live native session for order and
    trade book reads when no OpenAlgo key is configured."""
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    async def _orders(_self, _session):
        return [{"symbol": "INFY", "order_id": "O1"}]

    async def _trades(_self, _session):
        return [{"symbol": "INFY", "trade_id": "T1"}]

    monkeypatch.setattr(UpstoxAdapter, "order_book", _orders)
    monkeypatch.setattr(UpstoxAdapter, "trade_book", _trades)

    c, _app, _tmp = client
    connected = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXREADS", "credentials": {"access_token": "tok"}},
    )
    assert connected.status_code == 200, connected.get_json()

    orders = c.get("/api/v1/native/accounts/upstox/UPXREADS/orders")
    trades = c.get("/api/v1/native/accounts/upstox/UPXREADS/trades")

    assert orders.status_code == 200, orders.get_json()
    assert trades.status_code == 200, trades.get_json()
    assert orders.get_json()["data"] == [{"symbol": "INFY", "order_id": "O1"}]
    assert trades.get_json()["data"] == [{"symbol": "INFY", "trade_id": "T1"}]


def test_native_account_reads_include_quotes_and_history(client, monkeypatch):
    """Native-only sessions can power read-only market data without OpenAlgo."""
    from flinttrade_core.models import Candles, OHLCV, Quote
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    async def _quotes(_self, _session, symbols):
        assert symbols == ["NSE:INFY"]
        return [Quote(symbol="INFY", exchange="NSE", ltp=1450.25, open=1440, high=1460, low=1430, close=1448)]

    async def _historical(_self, _session, req):
        assert req["symbol"] == "INFY"
        assert req["exchange"] == "NSE"
        assert req["interval"] == "1d"
        assert req["start_date"] == "2026-01-01"
        assert req["end_date"] == "2026-01-31"
        return Candles(
            symbol="INFY",
            exchange="NSE",
            interval="1d",
            bars=[OHLCV(timestamp="2026-01-02T09:15:00+05:30", open=1, high=2, low=0.5, close=1.5, volume=10)],
        )

    monkeypatch.setattr(UpstoxAdapter, "quotes", _quotes)
    monkeypatch.setattr(UpstoxAdapter, "historical", _historical)

    c, _app, _tmp = client
    connected = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXDATA", "credentials": {"access_token": "tok"}},
    )
    assert connected.status_code == 200, connected.get_json()

    quote = c.get("/api/v1/native/accounts/upstox/UPXDATA/quotes?symbol=INFY&exchange=NSE")
    history = c.get(
        "/api/v1/native/accounts/upstox/UPXDATA/history"
        "?symbol=INFY&exchange=NSE&interval=1d&start_date=2026-01-01&end_date=2026-01-31"
    )

    assert quote.status_code == 200, quote.get_json()
    assert history.status_code == 200, history.get_json()
    assert quote.get_json()["data"][0]["ltp"] == 1450.25
    assert history.get_json()["data"]["bars"][0]["close"] == 1.5


def test_native_account_reads_include_ltp(client, monkeypatch):
    """LTP reads go through the unified native route when a broker exposes only
    a broker-SDK-shaped ltp_quotes method."""
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    async def _ltp_quotes(_self, _session, symbols):
        assert symbols == ["NSE:INFY"]
        return [{"symbol": "INFY", "exchange": "NSE", "ltp": 1450.25}]

    monkeypatch.setattr(UpstoxAdapter, "ltp_quotes", _ltp_quotes)

    c, _app, _tmp = client
    connected = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXLTP", "credentials": {"access_token": "tok"}},
    )
    assert connected.status_code == 200, connected.get_json()

    ltp = c.get("/api/v1/native/accounts/upstox/UPXLTP/ltp?symbol=INFY&exchange=NSE")

    assert ltp.status_code == 200, ltp.get_json()
    assert ltp.get_json()["data"][0]["ltp"] == 1450.25


def test_ltp_reads_serve_one_canonical_shape_for_every_adapter_payload(client, monkeypatch):
    """One-core contract: broker payload differences are absorbed in the core
    reads facade, never in the terminal. Every adapter ltp shape — a raw SDK
    row list, an EXCHANGE:SYMBOL->price map, or a scalar — must serialise to
    the SAME canonical [{symbol, exchange, ltp}] rows."""
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    payloads = {
        "rows": [{"instrument_token": "NSE_EQ|INE1", "symbol": "INFY", "last_price": "1450.25"}],
        "mapping": {"NSE:INFY": "1450.25"},
        "scalar": 1450.25,
    }
    served: dict[str, object] = {}

    async def _ltp_quotes(_self, _session, _symbols):
        return served["value"]

    monkeypatch.setattr(UpstoxAdapter, "ltp_quotes", _ltp_quotes)

    c, _app, _tmp = client
    connected = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXSHAPE", "credentials": {"access_token": "tok"}},
    )
    assert connected.status_code == 200, connected.get_json()

    for name, payload in payloads.items():
        served["value"] = payload
        resp = c.get("/api/v1/native/accounts/upstox/UPXSHAPE/ltp?symbol=INFY&exchange=NSE")
        assert resp.status_code == 200, (name, resp.get_json())
        rows = resp.get_json()["data"]
        assert isinstance(rows, list) and rows, name
        assert rows[0]["symbol"] == "INFY", (name, rows)
        assert rows[0]["exchange"] == "NSE", (name, rows)
        assert rows[0]["ltp"] == 1450.25, (name, rows)

    # quote_details falls back to the ltp read for adapters without the verb —
    # the terminal never selects verbs per broker.
    served["value"] = payloads["mapping"]
    detail = c.get(
        "/api/v1/native/accounts/upstox/UPXSHAPE/quote_details?symbol=INFY&exchange=NSE&quote_type=ltp"
    )
    assert detail.status_code == 200, detail.get_json()
    assert detail.get_json()["data"][0] == {"symbol": "INFY", "exchange": "NSE", "ltp": 1450.25}


def test_native_account_reads_include_market_depth(client, monkeypatch):
    """Depth/DOM widgets can use native market-depth reads without OpenAlgo."""
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    async def _market_depth(_self, _session, symbols):
        assert symbols == ["NSE:INFY"]
        return [{
            "symbol": "INFY",
            "exchange": "NSE",
            "bids": [{"price": 1450.0, "quantity": 10, "orders": 2}],
            "asks": [{"price": 1450.5, "quantity": 8, "orders": 1}],
        }]

    monkeypatch.setattr(UpstoxAdapter, "market_depth", _market_depth)

    c, _app, _tmp = client
    connected = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXDEPTH", "credentials": {"access_token": "tok"}},
    )
    assert connected.status_code == 200, connected.get_json()

    depth = c.get("/api/v1/native/accounts/upstox/UPXDEPTH/depth?symbol=INFY&exchange=NSE")

    assert depth.status_code == 200, depth.get_json()
    assert depth.get_json()["data"][0]["bids"][0]["price"] == 1450.0


def test_native_account_reads_include_margin_calculator(client, monkeypatch):
    """Margin widgets can use native pre-trade margin reads without OpenAlgo."""
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    async def _margin_calculator(_self, _session, order):
        assert order.symbol == "INFY"
        assert order.exchange == "NSE"
        assert order.quantity == "10"
        assert order.product == "MIS"
        assert order.action == "BUY"
        return {
            "required_margin": "2500.50",
            "span_margin": "2000.25",
            "exposure_margin": "500.25",
        }

    monkeypatch.setattr(UpstoxAdapter, "margin_calculator", _margin_calculator)

    c, _app, _tmp = client
    connected = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXMARGIN", "credentials": {"access_token": "tok"}},
    )
    assert connected.status_code == 200, connected.get_json()

    margin = c.get("/api/v1/native/accounts/upstox/UPXMARGIN/margin?symbol=INFY&exchange=NSE&qty=10&product=MIS")

    assert margin.status_code == 200, margin.get_json()
    assert margin.get_json()["data"]["required_margin"] == "2500.50"


def test_native_account_reads_include_market_calendar(client, monkeypatch):
    """Market status hooks can read native calendar data without OpenAlgo."""
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    async def _market_timings(_self, _session, timing_date):
        assert timing_date == "2026-07-05"
        return [{"exchange": "NSE", "start_time": "1718595000000", "end_time": "1718618400000"}]

    async def _market_holidays(_self, _session, holiday_date=None):
        assert holiday_date == "2026-08-15"
        return [{
            "date": "2026-08-15",
            "description": "Independence Day",
            "holiday_type": "TRADING_HOLIDAY",
            "closed_exchanges": ["NSE", "BSE"],
        }]

    monkeypatch.setattr(UpstoxAdapter, "market_timings", _market_timings)
    monkeypatch.setattr(UpstoxAdapter, "market_holidays", _market_holidays)

    c, _app, _tmp = client
    connected = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXCALENDAR", "credentials": {"access_token": "tok"}},
    )
    assert connected.status_code == 200, connected.get_json()

    timings = c.get("/api/v1/native/accounts/upstox/UPXCALENDAR/timings?date=2026-07-05")
    holidays = c.get("/api/v1/native/accounts/upstox/UPXCALENDAR/holidays?date=2026-08-15")

    assert timings.status_code == 200, timings.get_json()
    assert holidays.status_code == 200, holidays.get_json()
    assert timings.get_json()["data"][0]["exchange"] == "NSE"
    assert holidays.get_json()["data"][0]["description"] == "Independence Day"


def test_native_account_reads_include_option_greeks(client, monkeypatch):
    """Portfolio Greeks can batch native option-greek reads without OpenAlgo."""
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    async def _option_greeks(_self, _session, symbols):
        assert symbols == ["NFO:NIFTY24600CE", "NFO:NIFTY24700PE"]
        return [
            {"delta": 0.55, "gamma": 0.002, "theta": -8.1, "vega": 6.4, "iv": 13.2},
            {"delta": -0.45, "gamma": 0.003, "theta": -7.1, "vega": 5.4, "iv": 14.2},
        ]

    monkeypatch.setattr(UpstoxAdapter, "option_greeks", _option_greeks)

    c, _app, _tmp = client
    connected = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXGREEKS", "credentials": {"access_token": "tok"}},
    )
    assert connected.status_code == 200, connected.get_json()

    resp = c.get(
        "/api/v1/native/accounts/upstox/UPXGREEKS/optiongreeks"
        "?symbols=NFO:NIFTY24600CE,NFO:NIFTY24700PE"
    )

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["data"][0]["delta"] == 0.55
    assert resp.get_json()["data"][1]["iv"] == 14.2


def test_native_account_reads_include_ohlc(client, monkeypatch):
    """Native account reads can expose broker OHLC snapshots when an adapter supports them."""
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    async def _ohlc_quotes(_self, _session, symbols):
        assert symbols == ["NSE:RELIANCE"]
        return [{"symbol": "RELIANCE", "exchange": "NSE", "open": 10, "high": 12, "low": 9, "close": 11}]

    monkeypatch.setattr(UpstoxAdapter, "ohlc_quotes", _ohlc_quotes)

    c, _app, _tmp = client
    connected = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXOHLC", "credentials": {"access_token": "tok"}},
    )
    assert connected.status_code == 200, connected.get_json()

    resp = c.get("/api/v1/native/accounts/upstox/UPXOHLC/ohlc?symbol=RELIANCE&exchange=NSE")

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["data"][0]["close"] == 11


def test_native_account_reads_include_order_status(client, monkeypatch):
    """Native-only order status can read a broker's single-order details."""
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    async def _order_details(_self, _session, order_id):
        assert order_id == "OID-123"
        return {"order_id": order_id, "status": "COMPLETE"}

    monkeypatch.setattr(UpstoxAdapter, "order_details", _order_details)

    c, _app, _tmp = client
    connected = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXSTATUS", "credentials": {"access_token": "tok"}},
    )
    assert connected.status_code == 200, connected.get_json()

    resp = c.get("/api/v1/native/accounts/upstox/UPXSTATUS/orderstatus?orderId=OID-123")

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["data"]["status"] == "COMPLETE"


def test_native_margin_read_rejects_invalid_order_fields(client, monkeypatch):
    """Native margin validation errors should stay a public 400, not a 500."""
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    async def _margin_calculator(_self, _session, _order):  # pragma: no cover - validation stops before adapter call
        raise AssertionError("adapter should not be called for invalid margin fields")

    monkeypatch.setattr(UpstoxAdapter, "margin_calculator", _margin_calculator)

    c, _app, _tmp = client
    connected = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXMARGINBAD", "credentials": {"access_token": "tok"}},
    )
    assert connected.status_code == 200, connected.get_json()

    margin = c.get("/api/v1/native/accounts/upstox/UPXMARGINBAD/margin?symbol=INFY&qty=10&action=HOLD")

    assert margin.status_code == 400
    assert margin.get_json()["message"] == "margin read received invalid order fields."


def test_native_account_reads_include_expiry_and_optionchain(client, monkeypatch):
    """Dhan/Upstox native option-chain reads should not require the OpenAlgo bridge."""
    from flinttrade_core.models import OptionChain, OptionChainStrike
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    async def _expiry_list(_self, _session, symbol, exchange):
        assert symbol == "NIFTY"
        assert exchange == "NSE_INDEX"
        return ["2026-07-30"]

    async def _option_chain(_self, _session, req):
        assert req["symbol"] == "NIFTY"
        assert req["underlying"] == "NIFTY"
        assert req["exchange"] == "NSE_INDEX"
        assert req["expiry"] == "2026-07-30"
        assert req["expiry_date"] == "2026-07-30"
        return OptionChain(
            underlying="NIFTY",
            exchange="NSE_INDEX",
            strikes=[
                OptionChainStrike(
                    strike_price=25000,
                    ce_ltp=100,
                    ce_oi=10,
                    ce_volume=1000,
                    pe_ltp=80,
                    pe_oi=20,
                    pe_volume=2000,
                )
            ],
        )

    monkeypatch.setattr(UpstoxAdapter, "expiry_list", _expiry_list)
    monkeypatch.setattr(UpstoxAdapter, "option_chain", _option_chain)

    c, _app, _tmp = client
    connected = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXOPTIONS", "credentials": {"access_token": "tok"}},
    )
    assert connected.status_code == 200, connected.get_json()

    expiry = c.get("/api/v1/native/accounts/upstox/UPXOPTIONS/expiry?symbol=NIFTY&exchange=NSE_INDEX")
    chain = c.get(
        "/api/v1/native/accounts/upstox/UPXOPTIONS/optionchain"
        "?underlying=NIFTY&exchange=NSE_INDEX&expiry=2026-07-30"
    )

    assert expiry.status_code == 200, expiry.get_json()
    assert chain.status_code == 200, chain.get_json()
    assert expiry.get_json()["data"] == ["2026-07-30"]
    assert chain.get_json()["data"]["strikes"][0]["ce_ltp"] == 100


def test_native_account_reads_include_instrument_search(client, monkeypatch):
    """Native adapters that expose instrument search can feed terminal symbol search."""
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    async def _search_instruments(_self, _session, query):
        assert query == "RELIANCE"
        return [{
            "symbol": "RELIANCE",
            "name": "Reliance Industries",
            "exchange": "NSE",
            "instrument_key": "NSE_EQ|INE002A01018",
            "lot_size": 1,
            "tick_size": 0.05,
        }]

    monkeypatch.setattr(UpstoxAdapter, "search_instruments", _search_instruments)

    c, _app, _tmp = client
    connected = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXSEARCH", "credentials": {"access_token": "tok"}},
    )
    assert connected.status_code == 200, connected.get_json()

    resp = c.get("/api/v1/native/accounts/upstox/UPXSEARCH/search?query=RELIANCE")

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["data"][0]["symbol"] == "RELIANCE"
    assert resp.get_json()["data"][0]["instrument_key"] == "NSE_EQ|INE002A01018"


def test_native_account_reads_include_broker_specific_surfaces(client, monkeypatch):
    """Broker-specific read methods stay reachable through the unified native route."""
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    async def _limits(_self, _session, segment, exchange, product):
        assert (segment, exchange, product) == ("CASH", "NSE", "MIS")
        return {"available_cash": 1000, "segment": segment, "exchange": exchange, "product": product}

    async def _quote_details(_self, _session, symbols, quote_type="all"):
        assert symbols == ["NSE:INFY"]
        assert quote_type == "ltp"
        return [{"symbol": "INFY", "ltp": 1450.25}]

    async def _scrip_master(_self, _session, exchange=None):
        assert exchange == "NSE"
        return {"segments": [{"exchange": exchange, "url": "https://example.invalid/nse.csv"}]}

    async def _search_scrip(
        _self, _session, symbol, exchange="NSE", *, expiry=None, option_type=None, strike_price=None,
        ignore_50multiple=True,
    ):
        assert symbol == "NIFTY"
        assert exchange == "NFO"
        assert expiry == "30JUL2026"
        assert option_type == "CE"
        assert strike_price == "25000"
        assert ignore_50multiple is False
        return [{"symbol": symbol, "exchange": exchange, "token": "12345"}]

    async def _order_history(_self, _session, order_id):
        assert order_id == "OID-1"
        return [{"order_id": order_id, "status": "OPEN"}]

    async def _order_trades(_self, _session, order_id):
        assert order_id == "OID-1"
        return [{"order_id": order_id, "trade_id": "T1"}]

    monkeypatch.setattr(UpstoxAdapter, "limits", _limits, raising=False)
    monkeypatch.setattr(UpstoxAdapter, "quote_details", _quote_details, raising=False)
    monkeypatch.setattr(UpstoxAdapter, "scrip_master", _scrip_master, raising=False)
    monkeypatch.setattr(UpstoxAdapter, "search_scrip", _search_scrip, raising=False)
    monkeypatch.setattr(UpstoxAdapter, "order_history", _order_history, raising=False)
    monkeypatch.setattr(UpstoxAdapter, "order_trades", _order_trades, raising=False)

    c, _app, _tmp = client
    connected = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXUSECASES", "credentials": {"access_token": "tok"}},
    )
    assert connected.status_code == 200, connected.get_json()

    limits = c.get("/api/v1/native/accounts/upstox/UPXUSECASES/limits?segment=CASH&exchange=NSE&product=MIS")
    details = c.get("/api/v1/native/accounts/upstox/UPXUSECASES/quote_details?symbol=INFY&exchange=NSE&type=ltp")
    master = c.get("/api/v1/native/accounts/upstox/UPXUSECASES/scrip_master?exchange=NSE")
    search = c.get(
        "/api/v1/native/accounts/upstox/UPXUSECASES/search_scrip"
        "?symbol=NIFTY&exchange=NFO&expiry=30JUL2026&option_type=ce&strike_price=25000&ignore_50multiple=false"
    )
    history = c.get("/api/v1/native/accounts/upstox/UPXUSECASES/orderhistory?orderId=OID-1")
    trades = c.get("/api/v1/native/accounts/upstox/UPXUSECASES/ordertrades?order_id=OID-1")

    assert limits.status_code == 200, limits.get_json()
    assert details.status_code == 200, details.get_json()
    assert master.status_code == 200, master.get_json()
    assert search.status_code == 200, search.get_json()
    assert history.status_code == 200, history.get_json()
    assert trades.status_code == 200, trades.get_json()
    assert limits.get_json()["data"]["product"] == "MIS"
    assert details.get_json()["data"][0]["ltp"] == 1450.25
    assert master.get_json()["data"]["segments"][0]["exchange"] == "NSE"
    assert search.get_json()["data"][0]["token"] == "12345"
    assert history.get_json()["data"][0]["status"] == "OPEN"
    assert trades.get_json()["data"][0]["trade_id"] == "T1"


def test_native_account_reads_cover_kotak_neo_documented_surfaces(client, monkeypatch):
    """Kotak Neo's documented read helpers stay routed once an adapter session is active."""
    from flinttrade_gateway.brokers._base import Session
    from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter

    async def _limits(_self, _session, segment, exchange, product):
        assert (segment, exchange, product) == ("CASH", "NSE", "MIS")
        return {"available_cash": 1000, "segment": segment, "exchange": exchange, "product": product}

    async def _quote_details(_self, _session, symbols, quote_type="all"):
        assert symbols == ["NSE:INFY"]
        assert quote_type == "ltp"
        return [{"symbol": "INFY", "ltp": 1450.25}]

    async def _scrip_master(_self, _session, exchange=None):
        assert exchange == "NSE"
        return {"segments": [{"exchange": exchange, "url": "https://example.invalid/nse.csv"}]}

    async def _search_scrip(
        _self,
        _session,
        symbol,
        exchange="NSE",
        *,
        expiry=None,
        option_type=None,
        strike_price=None,
        ignore_50multiple=True,
    ):
        assert symbol == "NIFTY"
        assert exchange == "NFO"
        assert expiry == "30JUL2026"
        assert option_type == "CE"
        assert strike_price == "25000"
        assert ignore_50multiple is False
        return [{"symbol": symbol, "exchange": exchange, "token": "12345"}]

    async def _order_history(_self, _session, order_id):
        assert order_id == "OID-1"
        return [{"order_id": order_id, "status": "OPEN"}]

    async def _order_trades(_self, _session, order_id):
        assert order_id == "OID-1"
        return [{"order_id": order_id, "trade_id": "T1"}]

    async def _market_depth(_self, _session, symbols):
        assert symbols == ["NSE:INFY", "NSE:RELIANCE"]
        return [{"symbol": "INFY", "bids": [{"price": 1450.0}], "asks": [{"price": 1450.25}]}]

    async def _margin_calculator(_self, _session, order):
        assert order.symbol == "INFY"
        assert order.exchange == "NSE"
        assert order.quantity == "10"
        assert order.product == "MIS"
        return {"required_margin": 1234.5}

    monkeypatch.setattr(KotakNeoAdapter, "limits", _limits)
    monkeypatch.setattr(KotakNeoAdapter, "quote_details", _quote_details)
    monkeypatch.setattr(KotakNeoAdapter, "scrip_master", _scrip_master)
    monkeypatch.setattr(KotakNeoAdapter, "search_scrip", _search_scrip)
    monkeypatch.setattr(KotakNeoAdapter, "order_history", _order_history)
    monkeypatch.setattr(KotakNeoAdapter, "order_trades", _order_trades)
    monkeypatch.setattr(KotakNeoAdapter, "market_depth", _market_depth)
    monkeypatch.setattr(KotakNeoAdapter, "margin_calculator", _margin_calculator)

    c, app, _tmp = client
    app.config["NATIVE_ADAPTERS"]["kotakneo"] = KotakNeoAdapter()
    app.config["REGISTRY"].put_session(
        "kotakneo",
        "KOTAKREADS",
        Session(access_token="tok", expires_at=9e9, account_id="KOTAKREADS", adapter_id="kotakneo"),
    )

    limits = c.get("/api/v1/native/accounts/kotakneo/KOTAKREADS/limits?segment=CASH&exchange=NSE&product=MIS")
    details = c.get("/api/v1/native/accounts/kotakneo/KOTAKREADS/quote_details?symbol=INFY&exchange=NSE&type=ltp")
    master = c.get("/api/v1/native/accounts/kotakneo/KOTAKREADS/scrip_master?exchange=NSE")
    search = c.get(
        "/api/v1/native/accounts/kotakneo/KOTAKREADS/search_scrip"
        "?symbol=NIFTY&exchange=NFO&expiry=30JUL2026&option_type=ce&strike_price=25000&ignore_50multiple=false"
    )
    history = c.get("/api/v1/native/accounts/kotakneo/KOTAKREADS/orderhistory?orderId=OID-1")
    trades = c.get("/api/v1/native/accounts/kotakneo/KOTAKREADS/ordertrades?order_id=OID-1")
    depth = c.get("/api/v1/native/accounts/kotakneo/KOTAKREADS/depth?symbols=NSE:INFY,NSE:RELIANCE")
    margin = c.get(
        "/api/v1/native/accounts/kotakneo/KOTAKREADS/margin?symbol=INFY&exchange=NSE&qty=10&product=MIS"
    )

    assert limits.status_code == 200, limits.get_json()
    assert details.status_code == 200, details.get_json()
    assert master.status_code == 200, master.get_json()
    assert search.status_code == 200, search.get_json()
    assert history.status_code == 200, history.get_json()
    assert trades.status_code == 200, trades.get_json()
    assert depth.status_code == 200, depth.get_json()
    assert margin.status_code == 200, margin.get_json()
    assert limits.get_json()["data"]["product"] == "MIS"
    assert details.get_json()["data"][0]["ltp"] == 1450.25
    assert master.get_json()["data"]["segments"][0]["exchange"] == "NSE"
    assert search.get_json()["data"][0]["token"] == "12345"
    assert history.get_json()["data"][0]["status"] == "OPEN"
    assert trades.get_json()["data"][0]["trade_id"] == "T1"
    assert depth.get_json()["data"][0]["bids"][0]["price"] == 1450.0
    assert margin.get_json()["data"]["required_margin"] == 1234.5


def test_native_account_read_service_window_is_retryable_without_dropping_session(client, monkeypatch):
    """A broker service-hours outage is a read outage, not a re-auth signal."""
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    c, app, _tmp = client
    connected = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXWINDOW", "credentials": {"access_token": "tok"}},
    )
    assert connected.status_code == 200, connected.get_json()

    async def _service_window(_self, _session):
        raise RuntimeError(
            "The Funds service is accessible from 5:30 AM to 12:00 AM IST daily. "
            "Please try again during these service hours."
        )

    monkeypatch.setattr(UpstoxAdapter, "funds", _service_window)

    resp = c.get("/api/v1/native/accounts/upstox/UPXWINDOW/funds")

    body = resp.get_json()
    assert resp.status_code == 503
    assert body["message"] == "Broker read is temporarily unavailable; the session remains connected."
    assert body["data"]["retryable"] is True
    session = app.config["REGISTRY"].get_session_for("upstox", "UPXWINDOW")
    assert session.adapter_id == "upstox"


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
        json={"adapter_id": "upstox", "account_id": "UPXG7", "credentials": {"access_token": "tok"}},
    )
    # Simulate the next boot: session gone, replay failed on stale credentials.
    app.config["REGISTRY"].remove_session_for("upstox", "UPXG7")
    app.config.setdefault("NATIVE_SESSION_STATUS", {})["upstox:UPXG7"] = (
        "login-failed: IndMoney login requires an access_token"
    )

    listing = c.get("/api/v1/native/accounts").get_json()["data"]["accounts"]
    entry = next(a for a in listing if a["account_id"] == "UPXG7")
    assert entry["has_session"] is False
    assert entry["needs_relogin"] is True
    assert "login-failed" in entry["login_error"]


def test_sessionless_account_with_retryable_replay_failure_does_not_need_relogin(client):
    """A temporary broker login outage is visible without claiming the token is stale."""
    from flinttrade_gateway.native_login import BROKER_LOGIN_RETRY_MESSAGE

    c, app, _tmp = client
    c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXRETRY", "credentials": {"access_token": "tok"}},
    )
    app.config["REGISTRY"].remove_session_for("upstox", "UPXRETRY")
    app.config.setdefault("NATIVE_SESSION_STATUS", {})["upstox:UPXRETRY"] = BROKER_LOGIN_RETRY_MESSAGE

    listing = c.get("/api/v1/native/accounts").get_json()["data"]["accounts"]
    entry = next(a for a in listing if a["account_id"] == "UPXRETRY")
    assert entry["has_session"] is False
    assert entry["login_retryable"] is True
    assert entry["login_error"] == BROKER_LOGIN_RETRY_MESSAGE
    assert "needs_relogin" not in entry


def test_connected_account_has_no_relogin_flag(client):
    c, _app, _tmp = client
    c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXG7B", "credentials": {"access_token": "tok"}},
    )
    listing = c.get("/api/v1/native/accounts").get_json()["data"]["accounts"]
    entry = next(a for a in listing if a["account_id"] == "UPXG7B")
    assert entry["has_session"] is True
    assert "needs_relogin" not in entry


def test_set_primary_native_account_updates_workspace_and_vault(client):
    c, _app, tmp_path = client
    for account_id in ("UPXPRIMARYA", "UPXPRIMARYB"):
        connected = c.post(
            "/api/v1/native/accounts",
            headers=_h(),
            json={"adapter_id": "upstox", "account_id": account_id, "credentials": {"access_token": "tok"}},
        )
        assert connected.status_code == 200, connected.get_json()

    resp = c.post("/api/v1/native/accounts/upstox/UPXPRIMARYB/set-primary", headers=_h())

    assert resp.status_code == 200, resp.get_json()
    assert _workspace_brokers(tmp_path)["execution"]["default"] == "upstox:UPXPRIMARYB"
    listing = c.get("/api/v1/native/accounts").get_json()["data"]["accounts"]
    by_account = {a["account_id"]: a for a in listing}
    assert by_account["UPXPRIMARYA"]["is_primary"] is False
    assert by_account["UPXPRIMARYB"]["is_primary"] is True


def test_set_primary_native_account_requires_live_session(client):
    c, app, tmp_path = client
    connected = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXPRIMARYDEAD", "credentials": {"access_token": "tok"}},
    )
    assert connected.status_code == 200, connected.get_json()
    app.config["REGISTRY"].remove_session_for("upstox", "UPXPRIMARYDEAD")

    resp = c.post("/api/v1/native/accounts/upstox/UPXPRIMARYDEAD/set-primary", headers=_h())

    assert resp.status_code == 409
    assert _workspace_brokers(tmp_path)["execution"]["default"] != "upstox:UPXPRIMARYDEAD"
    listing = c.get("/api/v1/native/accounts").get_json()["data"]["accounts"]
    entry = next(a for a in listing if a["account_id"] == "UPXPRIMARYDEAD")
    assert entry["is_primary"] is False


def test_set_primary_native_account_rejects_read_only_session(client):
    c, _app, tmp_path = client
    connected = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={
            "adapter_id": "upstox",
            "account_id": "UPXPRIMARYRO",
            "credentials": {
                "access_token": "tok-read-only",
                "read_only": "true",
                "token_scope": "analytics",
            },
        },
    )
    assert connected.status_code == 200, connected.get_json()

    resp = c.post("/api/v1/native/accounts/upstox/UPXPRIMARYRO/set-primary", headers=_h())

    assert resp.status_code == 409
    assert "read-only" in resp.get_json()["message"]
    assert _workspace_brokers(tmp_path)["execution"]["default"] != "upstox:UPXPRIMARYRO"


def test_connect_schedules_a_daily_refresh_job(client):
    """A broker connected at runtime (after boot) gets its 08:05 IST refresh
    job on the already-running rotator (audit finding G5)."""
    c, app, _tmp = client
    c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXJOB", "credentials": {"access_token": "tok"}},
    )
    rotator = app.config.get("CREDENTIALS_ROTATOR")
    assert rotator is not None
    assert "cred_refresh_upstox" in rotator._job_ids


def test_remove_last_native_account_unschedules_refresh_and_drops_adapter(client):
    """Disconnecting the final account for a broker must remove its runtime hooks."""
    c, app, _tmp = client
    connected = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXJOBLAST", "credentials": {"access_token": "tok"}},
    )
    assert connected.status_code == 200, connected.get_json()
    rotator = app.config.get("CREDENTIALS_ROTATOR")
    assert rotator is not None
    assert "cred_refresh_upstox" in rotator._job_ids
    assert "upstox" in app.config["NATIVE_ADAPTERS"]

    removed = c.delete("/api/v1/native/accounts/upstox/UPXJOBLAST", headers=_h())

    assert removed.status_code == 200
    assert "cred_refresh_upstox" not in rotator._job_ids
    assert all(job.id != "cred_refresh_upstox" for job in app.config["ROTATION_SCHEDULER"].get_jobs())
    assert "upstox" not in app.config["NATIVE_ADAPTERS"]


def test_remove_one_of_multiple_native_accounts_keeps_refresh_and_adapter(client):
    """A broker refresh job is broker-scoped, so it survives while any account remains."""
    c, app, _tmp = client
    for account_id in ("UPXJOBKEEP1", "UPXJOBKEEP2"):
        connected = c.post(
            "/api/v1/native/accounts",
            headers=_h(),
            json={"adapter_id": "upstox", "account_id": account_id, "credentials": {"access_token": "tok"}},
        )
        assert connected.status_code == 200, connected.get_json()
    rotator = app.config.get("CREDENTIALS_ROTATOR")
    assert rotator is not None

    removed = c.delete("/api/v1/native/accounts/upstox/UPXJOBKEEP1", headers=_h())

    assert removed.status_code == 200
    assert "cred_refresh_upstox" in rotator._job_ids
    assert any(job.id == "cred_refresh_upstox" for job in app.config["ROTATION_SCHEDULER"].get_jobs())
    assert "upstox" in app.config["NATIVE_ADAPTERS"]
    assert app.config["REGISTRY"].get_session_for("upstox", "UPXJOBKEEP2").adapter_id == "upstox"


def test_relogin_with_fresh_credentials_preserves_label_and_primary(client):
    """Re-authenticating an existing account must not reset its label to the
    adapter id or clear is_primary (audit finding: relogin clobbers metadata)."""
    c, _app, tmp_path = client
    c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={
            "adapter_id": "upstox", "account_id": "UPXLBL",
            "label": "My UPX", "credentials": {"access_token": "tok"}, "is_primary": True,
        },
    )
    resp = c.post(
        "/api/v1/native/accounts/upstox/UPXLBL/login",
        headers=_h(),
        json={"credentials": {"access_token": "fresh-tok"}},
    )
    assert resp.status_code == 200
    listing = c.get("/api/v1/native/accounts").get_json()["data"]["accounts"]
    entry = next(a for a in listing if a["account_id"] == "UPXLBL")
    assert entry["label"] == "My UPX"
    assert entry["is_primary"] is True


def test_connect_dead_token_surfaces_needs_relogin_not_false_success(client, monkeypatch):
    """Re-audit fix: the interactive connect path now probes the token with a
    real funds read, so a dead token reports needs_relogin instead of a false
    'connected' (the token-replay logins build a Session without a broker call)."""
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    async def _dead_funds(_self, _session):
        raise RuntimeError("401 token expired")

    monkeypatch.setattr(UpstoxAdapter, "funds", _dead_funds)
    c, _app, _tmp = client
    resp = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXDEAD", "credentials": {"access_token": "dead"}},
    )
    # Login could not be verified → not connected → 502, and the vault row is
    # not left dead-credential'd.
    assert resp.status_code == 502
    body = resp.get_json()
    assert body["data"]["connected"] is False
    public_body = json.dumps(body)
    assert "UPXDEAD" not in public_body
    assert "dead" not in public_body


def test_connect_rejects_unattested_sdk_before_storing(client, monkeypatch):
    """A missing required SDK must fail before vault/workspace mutation."""
    c, app, tmp_path = client
    from flinttrade_core import native_account_routes as native_routes

    monkeypatch.setattr(
        native_routes,
        "_sdk_attestations_by_pin",
        lambda: {
            "upstox-python-sdk": {
                "pin": "upstox-python-sdk",
                "pinned_version": "2.28.0",
                "installed_version": None,
                "status": "missing",
            }
        },
    )

    resp = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "SDKMISS", "credentials": {"access_token": "tok"}},
    )

    assert resp.status_code == 503
    body = resp.get_json()
    assert body["data"]["connected"] is False
    assert body["data"]["login"] == "sdk-not-ready"
    assert "Upstox native SDK is not ready" in body["message"]
    assert all(row["account_id"] != "SDKMISS" for row in app.config["CREDENTIAL_STORE"].list_accounts())
    assert _workspace_brokers(tmp_path) == {}


def test_oauth_start_rejects_unattested_sdk_before_pending_state(client, monkeypatch):
    """Do not send the operator to a broker OAuth page when callback cannot activate."""
    c, _app, _tmp = client
    from flinttrade_core import native_account_routes as native_routes

    monkeypatch.setattr(
        native_routes,
        "_sdk_attestations_by_pin",
        lambda: {
            "upstox-python-sdk": {
                "pin": "upstox-python-sdk",
                "pinned_version": "2.28.0",
                "installed_version": "2.27.0",
                "status": "mismatch",
            }
        },
    )

    resp = c.post(
        "/api/v1/native/oauth/start",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXOAUTH", "api_key": "K", "api_secret": "S"},
    )

    assert resp.status_code == 503
    assert "Upstox native SDK is not ready" in resp.get_json()["message"]
    assert native_routes._OAUTH_PENDING == {}


def test_relogin_rejects_unattested_sdk_before_fresh_credential_update(client, monkeypatch):
    """A fresh re-login payload must not overwrite the vault if SDK attestation fails."""
    c, app, _tmp = client
    c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "SDKREL", "credentials": {"access_token": "good"}},
    )
    from flinttrade_core import native_account_routes as native_routes

    monkeypatch.setattr(
        native_routes,
        "_sdk_attestations_by_pin",
        lambda: {
            "upstox-python-sdk": {
                "pin": "upstox-python-sdk",
                "pinned_version": "2.28.0",
                "installed_version": None,
                "status": "missing",
            }
        },
    )

    resp = c.post(
        "/api/v1/native/accounts/upstox/SDKREL/login",
        headers=_h(),
        json={"credentials": {"access_token": "fresh"}},
    )

    assert resp.status_code == 503
    assert "Upstox native SDK is not ready" in resp.get_json()["message"]
    assert app.config["CREDENTIAL_STORE"].retrieve_for("upstox", "SDKREL")["access_token"] == "good"


def test_relogin_dead_token_surfaces_relogin(client, monkeypatch):
    """The interactive Re-authenticate path probes too — a dead replayed token
    drops the session and records login-failed (needs_relogin), not a false ok."""
    c, app, _tmp = client
    # First connect with the passing stub (fixture default) so the account exists.
    c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXRL", "credentials": {"access_token": "tok"}},
    )
    # Now the token has "gone dead": funds probe fails on re-authenticate.
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    async def _dead_funds(_self, _session):
        raise RuntimeError("401 token expired")

    monkeypatch.setattr(UpstoxAdapter, "funds", _dead_funds)
    resp = c.post("/api/v1/native/accounts/upstox/UPXRL/login", headers=_h())
    assert resp.status_code == 502
    assert resp.get_json()["data"]["session"]["has_session"] is False
    # The accounts list surfaces the honest needs_relogin state.
    listing = c.get("/api/v1/native/accounts").get_json()["data"]["accounts"]
    entry = next(a for a in listing if a["account_id"] == "UPXRL")
    assert entry["needs_relogin"] is True


def test_relogin_login_failure_drops_prior_session(client, monkeypatch):
    """If fresh login throws before registering a replacement session, the old
    in-memory session must not keep the account looking connected."""
    c, app, _tmp = client
    c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXLOGINFAIL", "credentials": {"access_token": "tok"}},
    )
    assert app.config["REGISTRY"].get_session_for("upstox", "UPXLOGINFAIL").adapter_id == "upstox"

    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    async def _login_failure(_self, _credentials):
        raise RuntimeError("401 token expired")

    monkeypatch.setattr(UpstoxAdapter, "login", _login_failure)

    resp = c.post(
        "/api/v1/native/accounts/upstox/UPXLOGINFAIL/login",
        headers=_h(),
        json={"credentials": {"access_token": "dead"}},
    )

    assert resp.status_code == 502
    assert resp.get_json()["data"]["session"]["has_session"] is False
    with pytest.raises(Exception):
        app.config["REGISTRY"].get_session_for("upstox", "UPXLOGINFAIL")
    listing = c.get("/api/v1/native/accounts").get_json()["data"]["accounts"]
    entry = next(a for a in listing if a["account_id"] == "UPXLOGINFAIL")
    assert entry["has_session"] is False
    assert entry["needs_relogin"] is True


def test_native_read_dead_token_drops_session_and_surfaces_relogin(client, monkeypatch):
    """A token can expire after a successful connect; the next authenticated
    native read must not leave the account looking connected with only 502s."""
    c, app, _tmp = client
    c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXREADDEAD", "credentials": {"access_token": "tok"}},
    )

    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    async def _dead_profile(_self, _session):
        raise RuntimeError("401 token expired")

    monkeypatch.setattr(UpstoxAdapter, "profile", _dead_profile)

    resp = c.get("/api/v1/native/accounts/upstox/UPXREADDEAD/profile")

    assert resp.status_code == 409
    body = resp.get_json()
    assert body["message"] == "Broker session expired or invalid; re-login required."
    public_body = json.dumps(body)
    assert "UPXREADDEAD" not in public_body
    assert "tok" not in public_body
    with pytest.raises(Exception):
        app.config["REGISTRY"].get_session_for("upstox", "UPXREADDEAD")
    listing = c.get("/api/v1/native/accounts").get_json()["data"]["accounts"]
    entry = next(a for a in listing if a["account_id"] == "UPXREADDEAD")
    assert entry["has_session"] is False
    assert entry["needs_relogin"] is True
    assert entry["login_error"] == "Broker session expired or invalid; re-login required."


def test_native_read_service_window_keeps_session(client, monkeypatch):
    """Closed broker service windows are not auth failures; keep the session so
    the operator is not forced through daily login for a temporary venue issue."""
    c, app, _tmp = client
    c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "UPXSERVICE", "credentials": {"access_token": "tok"}},
    )

    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    async def _service_window(_self, _session):
        raise RuntimeError("The Funds service is accessible from 5:30 AM to 12:00 AM IST daily.")

    monkeypatch.setattr(UpstoxAdapter, "funds", _service_window)

    resp = c.get("/api/v1/native/accounts/upstox/UPXSERVICE/funds")

    assert resp.status_code == 503
    assert resp.get_json()["data"]["retryable"] is True
    assert app.config["REGISTRY"].get_session_for("upstox", "UPXSERVICE").adapter_id == "upstox"
    listing = c.get("/api/v1/native/accounts").get_json()["data"]["accounts"]
    entry = next(a for a in listing if a["account_id"] == "UPXSERVICE")
    assert entry["has_session"] is True
    assert "needs_relogin" not in entry


def test_failed_reconnect_restores_prior_good_credentials(client, monkeypatch):
    """Re-audit fix #3: re-connecting an EXISTING account with bad creds must
    not destroy the previously-good vault row — on failure it is restored, and
    the selector is NOT orphaned."""
    c, app, tmp_path = client
    # Connect once (good token, passing probe from the fixture stub).
    c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "INDRESTORE",
              "label": "Keep me", "credentials": {"access_token": "good-token"}, "is_primary": True},
    )
    store = app.config["CREDENTIAL_STORE"]
    assert store.retrieve_for("upstox", "INDRESTORE")["access_token"] == "good-token"

    # Reconnect with a token whose probe fails.
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    async def _dead_funds(_self, _session):
        raise RuntimeError("401 token expired")

    monkeypatch.setattr(UpstoxAdapter, "funds", _dead_funds)
    resp = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "INDRESTORE", "credentials": {"access_token": "bad-token"}},
    )
    assert resp.status_code == 502
    # The prior good credentials survive; the selector is still registered.
    assert store.retrieve_for("upstox", "INDRESTORE")["access_token"] == "good-token"
    assert "upstox:INDRESTORE" in _workspace_brokers(tmp_path).get("registered", [])


def test_failed_new_connect_purges_and_deregisters(client, monkeypatch):
    """A failed BRAND-NEW connect leaves nothing orphaned: no vault row, no
    registered selector."""
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    async def _dead_funds(_self, _session):
        raise RuntimeError("401 token expired")

    monkeypatch.setattr(UpstoxAdapter, "funds", _dead_funds)
    c, app, tmp_path = client
    resp = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "INDNEW", "credentials": {"access_token": "dead"}},
    )
    assert resp.status_code == 502
    store = app.config["CREDENTIAL_STORE"]
    import pytest as _pt
    with _pt.raises(Exception):
        store.retrieve_for("upstox", "INDNEW")
    assert "upstox:INDNEW" not in _workspace_brokers(tmp_path).get("registered", [])


def test_workspace_registration_failure_purges_new_vault_row(client, monkeypatch):
    """If vault storage succeeds but workspace registration fails, rollback must
    remove the new encrypted row so a disconnected account is not replayed."""
    c, app, tmp_path = client

    import flinttrade_core.native_account_routes as routes

    def _boom(*_args, **_kwargs):
        raise RuntimeError("workspace write failed")

    monkeypatch.setattr(routes, "_register_selector_in_workspace", _boom)
    resp = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "WSFAIL", "credentials": {"access_token": "tok"}},
    )
    assert resp.status_code == 502
    store = app.config["CREDENTIAL_STORE"]
    with pytest.raises(Exception):
        store.retrieve_for("upstox", "WSFAIL")
    assert "upstox:WSFAIL" not in _workspace_brokers(tmp_path).get("registered", [])


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
        json={"adapter_id": "upstox", "account_id": "PRIMARY1",
              "credentials": {"access_token": "good"}, "is_primary": True},
    )
    assert _workspace_brokers(tmp_path)["execution"]["default"] == "upstox:PRIMARY1"

    # A new connect for a different account, is_primary=True, whose probe fails.
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    async def _dead_funds(_self, _session):
        raise RuntimeError("401 token expired")

    monkeypatch.setattr(UpstoxAdapter, "funds", _dead_funds)
    resp = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "BADNEW",
              "credentials": {"access_token": "dead"}, "is_primary": True},
    )
    assert resp.status_code == 502
    brokers = _workspace_brokers(tmp_path)
    # The prior working default survives; the failed selector is not registered.
    assert brokers["execution"]["default"] == "upstox:PRIMARY1"
    assert "upstox:BADNEW" not in brokers.get("registered", [])


def test_failed_reconnect_restores_label_and_is_primary(client, monkeypatch):
    """Re-audit fix: a failed reconnect restores the full prior vault row —
    label and is_primary, not just the credential payload."""
    c, app, tmp_path = client
    c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "META1", "label": "Original label",
              "credentials": {"access_token": "good"}, "is_primary": True},
    )
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    async def _dead_funds(_self, _session):
        raise RuntimeError("401 token expired")

    monkeypatch.setattr(UpstoxAdapter, "funds", _dead_funds)
    c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": "upstox", "account_id": "META1", "label": "New bad label",
              "credentials": {"access_token": "bad"}, "is_primary": False},
    )
    row = next(r for r in app.config["CREDENTIAL_STORE"].list_accounts() if r["account_id"] == "META1")
    assert row["label"] == "Original label"
    assert bool(row["is_primary"]) is True


@pytest.mark.parametrize("adapter_id", ["kotakneo", "groww"])
def test_connect_rejects_coming_soon_native(client, adapter_id):
    """A native broker that is catalogued but not yet tried-and-tested
    (connectable=False, e.g. Kotak Neo or Groww) is rejected on connect with a
    'coming soon' message."""
    c, _app, _tmp = client
    resp = c.post(
        "/api/v1/native/accounts",
        headers=_h(),
        json={"adapter_id": adapter_id, "account_id": "CS1", "credentials": {"access_token": "x"}},
    )
    assert resp.status_code == 400
    assert "coming soon" in resp.get_json()["message"].lower()


@pytest.mark.parametrize("adapter_id", ["kotakneo", "groww"])
def test_relogin_rejects_coming_soon_native_even_if_vault_row_exists(client, adapter_id):
    """A stale/local vault row must not turn a catalogued-but-unverified native
    into an active connectable broker."""
    c, app, _tmp = client
    store = app.config["CREDENTIAL_STORE"]
    store.store(
        "CSRELOGIN", adapter_id, "Coming-soon stale",
        {"access_token": "tok"}, is_primary=False, adapter_id=adapter_id,
    )
    resp = c.post(f"/api/v1/native/accounts/{adapter_id}/CSRELOGIN/login", headers=_h())
    assert resp.status_code == 400
    assert "coming soon" in resp.get_json()["message"].lower()
