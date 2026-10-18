"""Retire credential payloads, never replay/identity/uncertain-outcome custody."""

import copy
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from flinttrade_core.service_connection_store import ServiceConnectionStore
from packages.core.core.tests.test_service_oauth import BASE, HEADERS, connected, finish, flow as _flow

flow = _flow
pytestmark = pytest.mark.integration


@pytest.mark.parametrize("mutation", ["clear", "replace", "delete", "auth_change", "replace_handle"])
def test_binding_retirement_strips_only_obsolete_payloads(flow, mutation):
    app, client, store, provider, who = flow
    identifier, etag = connected(flow)
    with store.oauth.locked() as (_, _, state):
        before = copy.deepcopy(state)
    payload = (
        {"clear_credential": True}
        if mutation == "clear"
        else {"credential": "inert-replacement"}
        if mutation == "replace"
        else {"auth_mode": "api_key"}
    )
    if mutation == "replace_handle":
        import json

        payload = {"credential": json.dumps({"service_oauth": next(iter(before["grants"]))}, separators=(",", ":"))}
    result = client.open(
        BASE + "/" + identifier,
        method="DELETE" if mutation == "delete" else "PATCH",
        headers={**HEADERS, "If-Match": etag, "Idempotency-Key": str(uuid4())},
        json={} if mutation == "delete" else payload,
    )
    assert result.status_code == 200
    with store.oauth.locked() as (_, _, state):
        retained_count = sum(bool(g.get("tokens")) for g in state["grants"].values())
        assert retained_count == 0
        assert state["registrations"] == before["registrations"]
        assert set(state["grants"]) == set(before["grants"])
        assert set(state["transactions"]) == set(before["transactions"])
        assert [t["status"] for t in state["transactions"].values()] == ["connected"]
    assert ServiceConnectionStore(store.workspace_dir).recover().etag == result.headers["ETag"]


def test_second_grant_retires_first_and_disconnect_keeps_tombstones(flow):
    app, client, store, provider, who = flow
    identifier, etag = connected(flow)
    result = client.post(BASE + f"/{identifier}/oauth/start", headers={**HEADERS, "If-Match": etag}, json={})
    assert result.status_code == 200
    attempt = result.json
    query = parse_qs(urlsplit(attempt["authorization_url"]).query)
    provider.update(nonce=query["nonce"][0], challenge=query["code_challenge"][0])
    completed = finish(client, identifier, etag, attempt, query)
    assert completed.status_code == 200
    with store.oauth.locked() as (_, _, state):
        payload_count = sum(bool(g.get("tokens")) for g in state["grants"].values())
    assert payload_count == 1
    result = client.post(
        BASE + f"/{identifier}/oauth/disconnect", headers={**HEADERS, "If-Match": completed.headers["ETag"]}, json={}
    )
    assert result.status_code == 200 and result.json["remote_revocation"] == "confirmed"
    with store.oauth.locked() as (_, _, state):
        payload_count = sum(bool(g.get("tokens")) for g in state["grants"].values())
        assert payload_count == 0
        assert len(state["transactions"]) == 2 and len(state["grants"]) == 2
        assert state["registrations"][identifier]["subject"] == provider["subject"]


def test_clear_preserves_unknown_refresh_claim_and_cannot_replay(flow):
    app, client, store, provider, who = flow
    identifier, etag = connected(flow)
    provider.update(now=provider["now"] + 3600, timeout=True)
    result = client.post(BASE + f"/{identifier}/oauth/refresh", headers={**HEADERS, "If-Match": etag}, json={})
    assert result.status_code == 502
    result = client.patch(
        BASE + "/" + identifier,
        headers={**HEADERS, "If-Match": etag, "Idempotency-Key": str(uuid4())},
        json={"clear_credential": True},
    )
    assert result.status_code == 200
    with store.oauth.locked() as (_, _, state):
        status = [g["status"] for g in state["grants"].values()]
        payload_count = sum(bool(g.get("tokens")) for g in state["grants"].values())
    assert payload_count == 0
    assert status == ["refresh_unknown"]
    count = len(provider["calls"])
    result = client.post(
        BASE + f"/{identifier}/oauth/refresh", headers={**HEADERS, "If-Match": result.headers["ETag"]}, json={}
    )
    assert result.status_code == 409 and len(provider["calls"]) == count


def test_interrupted_retirement_recovers_before_success_and_keeps_replay_receipt(flow, monkeypatch):
    from flinttrade_core import service_oauth

    app, client, store, provider, who = flow
    identifier, etag = connected(flow)
    key = str(uuid4())
    original = service_oauth.retire_obsolete_oauth_payloads

    def fail(*args, **kwargs):
        raise OSError("synthetic retirement storage failure")

    monkeypatch.setattr(service_oauth, "retire_obsolete_oauth_payloads", fail)
    result = client.patch(
        BASE + "/" + identifier,
        headers={**HEADERS, "If-Match": etag, "Idempotency-Key": key},
        json={"clear_credential": True},
    )
    assert result.status_code == 503
    monkeypatch.setattr(service_oauth, "retire_obsolete_oauth_payloads", original)
    reopened = ServiceConnectionStore(store.workspace_dir)
    assert reopened.recover().connections[0].credential_configured is False
    with store.oauth.locked() as (_, _, state):
        count = sum(bool(g.get("tokens")) for g in state["grants"].values())
        assert count == 0
        assert len(state["transactions"]) == 1 and len(state["registrations"]) == 1
    result = client.patch(
        BASE + "/" + identifier,
        headers={**HEADERS, "If-Match": etag, "Idempotency-Key": key},
        json={"clear_credential": True},
    )
    assert result.status_code == 200


def test_metadata_edit_keeps_exact_current_binding_payload(flow):
    app, client, store, provider, who = flow
    identifier, etag = connected(flow)
    result = client.patch(
        BASE + "/" + identifier,
        headers={**HEADERS, "If-Match": etag, "Idempotency-Key": str(uuid4())},
        json={"label": "Retained binding"},
    )
    assert result.status_code == 200
    with store.oauth.locked() as (_, _, state):
        count = sum(bool(g.get("tokens")) for g in state["grants"].values())
    assert count == 1
