"""Tests for the native broker capture + activation routes (Phase 1 G4).

IndMoney is used as the exercise broker because its ``login()`` builds a session
from any non-empty access token WITHOUT calling the broker (validation is lazy,
on the first API call) and its SDK pin is ``None`` (creds-only activation gate),
so the full connect -> register -> rebuild -> login -> session path runs offline.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "master_password").write_text("native-routes-test-pw", encoding="utf-8")
    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, app, tmp_path


def _workspace_brokers(tmp_path):
    return json.loads((tmp_path / "workspace.json").read_text(encoding="utf-8")).get("brokers", {})


def test_connect_indmoney_stores_registers_and_establishes_session(client):
    c, app, tmp_path = client
    resp = c.post(
        "/api/v1/native/accounts",
        json={
            "adapter_id": "indmoney",
            "account_id": "INDTEST01",
            "label": "IndMoney test",
            "credentials": {"access_token": "dummy-dashboard-token", "user_id": "INDTEST01"},
            "is_primary": True,
        },
    )
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()["data"]
    assert data["connected"] is True
    assert data["login"] == "ok"

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
    )
    assert resp.status_code == 400
    assert "not a native broker" in resp.get_json()["message"]


def test_connect_requires_credentials(client):
    c, _app, _tmp = client
    resp = c.post("/api/v1/native/accounts", json={"adapter_id": "dhan", "account_id": "D1"})
    assert resp.status_code == 400


def test_list_and_remove_native_account(client):
    c, app, tmp_path = client
    c.post(
        "/api/v1/native/accounts",
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

    removed = c.delete("/api/v1/native/accounts/indmoney/INDTEST02")
    assert removed.status_code == 200

    # Selector deregistered and session gone.
    brokers = _workspace_brokers(tmp_path)
    assert "indmoney:INDTEST02" not in brokers.get("registered", [])
    with pytest.raises(Exception):
        app.config["REGISTRY"].get_session_for("indmoney", "INDTEST02")


def test_relogin_replays_stored_credentials(client):
    c, app, _tmp = client
    c.post(
        "/api/v1/native/accounts",
        json={"adapter_id": "indmoney", "account_id": "INDTEST03", "credentials": {"access_token": "tok3"}},
    )
    # Drop the session, then re-login should re-establish it from stored creds.
    app.config["REGISTRY"].remove_session_for("indmoney", "INDTEST03")
    resp = c.post("/api/v1/native/accounts/indmoney/INDTEST03/login")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["session"]["has_session"] is True
