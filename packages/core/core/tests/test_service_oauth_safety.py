"""Negative public HTTP lifecycle cases, no external login or provider calls."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import httpx
import pytest
from flinttrade_core.auth_routes import VerifiedOperatorSession
from flinttrade_core.service_oauth import ServiceOAuth
from packages.core.core.tests.test_service_oauth import (
    BASE,
    CALLBACK,
    HEADERS,
    ACTOR,
    create,
    start,
    finish,
    connected,
)

from packages.core.core.tests import test_service_oauth as oauth_support

flow = oauth_support.flow
pytestmark = pytest.mark.integration


def post(client, identifier, etag, op, body=None):
    return client.post(BASE + f"/{identifier}/oauth/" + op, headers={**HEADERS, "If-Match": etag}, json=body or {})


@pytest.mark.parametrize(
    "variant",
    [
        "state",
        "cookie",
        "origin",
        "expiry",
        "denied",
        "cancelled",
        "session",
        "scope",
        "nonce",
        "signature",
        "audience",
        "issuer",
    ],
)
def test_acquisition_refuses_unbound_or_denied_results(flow, variant):
    app, client, store, state, who = flow
    identifier, etag = create(client)
    data, query = start(client, identifier, etag, state)
    body = {"transaction_id": data["transaction_id"]}
    if variant == "state":
        query["state"] = ["foreign"]
    if variant == "cookie":
        client.delete_cookie("flinttrade_service_oauth", domain="127.0.0.1", path=BASE + "/oauth/callback")
    if variant == "origin":
        app.config["SERVICE_OAUTH_CONFIG"]["redirect_uri"] = CALLBACK.replace(":5000", ":5001")
    if variant == "expiry":
        state["now"] += 601
    if variant == "cancelled":
        assert post(client, identifier, etag, "cancel", body).status_code == 200
    if variant == "session":
        who[0] = VerifiedOperatorSession(ACTOR.actor_ref, "session:" + "c" * 64, ACTOR.scopes)
    if variant == "scope":
        state["scopes"] = "openid offline_access"
    if variant == "nonce":
        state["nonce"] = "wrong"
    if variant in {"signature", "audience", "issuer"}:
        state["invalid_identity"] = variant
    callback = client.get(
        CALLBACK,
        query_string={
            "state": query["state"][0],
            **({"error": "access_denied"} if variant == "denied" else {"code": "test", "client_id": "oaiapp_test"}),
        },
    )
    result = post(client, identifier, etag, "complete", body)
    if variant == "denied":
        assert result.get_json() == {"status": "denied"}
    elif variant == "cancelled":
        assert result.get_json() == {"status": "cancelled"}
    elif variant == "expiry":
        assert result.get_json() == {"status": "expired"}
    else:
        assert result.status_code in {400, 403, 409, 410, 412}
    assert client.get(BASE, headers=HEADERS).get_json()["connections"][0]["credential_configured"] is False
    assert "test" not in callback.get_data(as_text=True).lower()


def test_durable_single_use_restart_and_reauthorization_identity(flow):
    app, client, store, state, who = flow
    identifier, etag = create(client)
    data, query = start(client, identifier, etag, state)
    assert finish(client, identifier, etag, data, query).status_code == 200
    calls = len(state["calls"])
    from flinttrade_core.service_oauth_routes import bind_oauth

    store.oauth = None
    bind_oauth(app, store)
    assert post(client, identifier, etag, "complete", {"transaction_id": data["transaction_id"]}).status_code == 412
    assert len(state["calls"]) == calls
    newtag = client.get(BASE, headers=HEADERS).headers["ETag"]
    new = post(client, identifier, newtag, "start").get_json()
    from urllib.parse import parse_qs, urlsplit

    q = parse_qs(urlsplit(new["authorization_url"]).query)
    assert q["client_id"] == ["oaiapp_test"]
    assert "agent_name_hint" not in q
    assert q["ext_agent_host_id"] == query["ext_agent_host_id"]
    state["nonce"] = q["nonce"][0]
    state["challenge"] = q["code_challenge"][0]
    state["subject"] = "different-subject"
    result = finish(client, identifier, newtag, new, q)
    assert result.status_code == 403


@pytest.mark.parametrize("operation", ["delete", "clear", "replace", "retire", "cancel"])
def test_held_code_exchange_cannot_revive_changed_authority(flow, operation):
    app, client, store, state, who = flow
    identifier, etag = create(client)
    data, query = start(client, identifier, etag, state)

    def mutate():
        state.pop("token_hook", None)
        from flinttrade_core.service_connection_audit import ConnectionActorContext

        if operation == "retire":
            who[0] = VerifiedOperatorSession("operator:" + "c" * 64, ACTOR.session_binding, ACTOR.scopes)
        elif operation == "cancel":
            store.oauth.cancel(
                identifier,
                etag,
                data["transaction_id"],
                ConnectionActorContext(ACTOR.actor_ref, ACTOR.session_binding),
                lambda: None,
            )
        else:
            payload = (
                {}
                if operation == "delete"
                else {"clear_credential": True}
                if operation == "clear"
                else {"credential": "replacement-material"}
            )
            store.mutate(
                "delete" if operation == "delete" else "update",
                payload,
                connection_id=identifier,
                expected_etag=etag,
                idempotency_key=str(uuid4()),
                actor_context=ConnectionActorContext(ACTOR.actor_ref, ACTOR.session_binding),
            )

    state["token_hook"] = mutate
    result = finish(client, identifier, etag, data, query)
    assert result.status_code in {403, 412}
    assert len([c for c in state["calls"] if c[1].endswith("/oauth/token")]) == 1


@pytest.mark.parametrize("variant", ["timeout", "identity", "expanded_scope", "delete", "clear", "session"])
def test_refresh_uncertainty_never_replays_or_revives(flow, variant):
    app, client, store, state, who = flow
    identifier, etag = connected(flow)
    state["now"] += 3570
    if variant == "timeout":
        state["timeout"] = True
    if variant == "identity":
        state["subject"] = "wrong"
    if variant == "expanded_scope":
        state["scopes"] = (
            "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct arbitrary.admin"
        )
    if variant in {"delete", "clear", "session"}:

        def change():
            from flinttrade_core.service_connection_audit import ConnectionActorContext

            state.pop("token_hook", None)
            if variant == "session":
                who[0] = VerifiedOperatorSession(ACTOR.actor_ref, "session:" + "c" * 64, ACTOR.scopes)
            else:
                store.mutate(
                    "delete" if variant == "delete" else "update",
                    {} if variant == "delete" else {"clear_credential": True},
                    connection_id=identifier,
                    expected_etag=etag,
                    idempotency_key=str(uuid4()),
                    actor_context=ConnectionActorContext(ACTOR.actor_ref, ACTOR.session_binding),
                )

        state["token_hook"] = change
    first = post(client, identifier, etag, "refresh")
    assert first.status_code in {403, 412, 502}
    calls = len(state["calls"])
    original = store.oauth
    store.oauth = ServiceOAuth(store, config=original.config, transport=original.transport, clock=original.clock)
    repeat = post(client, identifier, etag, "refresh")
    assert repeat.status_code in {401, 403, 404, 412}
    assert len(state["calls"]) == calls and state["refreshes"] == 1


def test_concurrent_refresh_is_single_flight_and_durable(flow):
    app, client, store, state, who = flow
    identifier, etag = connected(flow)
    state["now"] += 3570
    entered, release = Event(), Event()

    def held():
        entered.set()
        assert release.wait(5)

    state["token_hook"] = held

    def run():
        with app.test_client() as other:
            return post(other, identifier, etag, "refresh")

    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(run)
        try:
            assert entered.wait(5)
            assert post(client, identifier, etag, "refresh").status_code == 401
        finally:
            release.set()
        result = task.result()
        result.close()
        assert result.status_code == 200
    assert state["refreshes"] == 1
    assert post(client, identifier, etag, "refresh").get_json() == {"status": "current", "rotation": 1}
    assert state["refreshes"] == 1


@pytest.mark.parametrize("status", [400, 500])
def test_remote_revoke_failure_is_not_local_disconnect_failure(flow, status):
    app, client, store, state, who = flow
    identifier, etag = connected(flow)
    state["revoke_status"] = status
    result = post(client, identifier, etag, "disconnect")
    assert result.status_code == 200 and result.get_json() == {
        "status": "disconnected",
        "remote_revocation": "unconfirmed",
    }
    snapshot = client.get(BASE, headers=HEADERS)
    assert snapshot.get_json()["connections"][0]["credential_configured"] is False
    before = len(state["calls"])
    assert post(client, identifier, snapshot.headers["ETag"], "refresh").status_code == 409
    assert len(state["calls"]) == before


def test_oidc_metadata_does_not_follow_arbitrary_jwks_or_revoke_urls(flow):
    app, client, store, state, who = flow
    identifier, etag = create(client)
    data, query = start(client, identifier, etag, state)
    original = app.config["SERVICE_OAUTH_TRANSPORT"]
    requests = []

    def http(request):
        requests.append(str(request.url))
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(
                200, json={"issuer": "https://auth.openai.com", "jwks_uri": "http://169.254.169.254/latest"}
            )
        return original.handle_request(request)

    app.config["SERVICE_OAUTH_TRANSPORT"] = httpx.MockTransport(http)
    assert finish(client, identifier, etag, data, query).status_code == 502
    assert not any("169.254" in url for url in requests)


@pytest.mark.parametrize(
    "provider,auth", [("llm:anthropic", "oauth"), ("llm:grok", "api_key"), ("llm:custom", "api_key")]
)
def test_unsupported_provider_never_contacts_an_external_service(flow, provider, auth):
    app, client, store, state, who = flow
    identifier, etag = create(client, provider, auth)
    assert post(client, identifier, etag, "start").status_code == 422
    assert state["calls"] == []


def test_openrouter_pkce_yields_key_and_honest_nonrenewable_disconnect(flow):
    app, client, store, state, who = flow
    identifier, etag = create(client, "llm:openrouter", "api_key")
    from urllib.parse import parse_qs, urlsplit

    result = post(client, identifier, etag, "start")
    assert result.status_code == 200
    data = result.get_json()
    q = parse_qs(urlsplit(data["authorization_url"]).query)
    assert q["callback_url"] == [CALLBACK] and q["code_challenge_method"] == ["S256"]
    sent = []

    def transport(req):
        sent.append(req)
        body = json.loads(req.content)
        import base64
        import hashlib

        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(body["code_verifier"].encode()).digest()).decode().rstrip("=")
        )
        assert challenge == q["code_challenge"][0]
        assert str(req.url) == "https://openrouter.ai/api/v1/auth/keys"
        return httpx.Response(200, json={"key": "synthetic-openrouter-key"})

    app.config["SERVICE_OAUTH_TRANSPORT"] = httpx.MockTransport(transport)
    callback = client.get(CALLBACK, query_string={"code": "test", "state": q["state"][0]})
    assert callback.status_code == 200
    complete = post(client, identifier, etag, "complete", {"transaction_id": data["transaction_id"]})
    assert complete.status_code == 200
    etag = complete.headers["ETag"]
    assert post(client, identifier, etag, "refresh").status_code == 422
    assert post(client, identifier, etag, "disconnect").get_json() == {
        "status": "disconnected",
        "remote_revocation": "unsupported",
    }
    assert len(sent) == 1


def test_request_drain_precedes_oauth_owner_shutdown(flow):
    import time
    from flinttrade_core import desktop

    app, client, store, state, who = flow
    identifier, etag = create(client)
    data, query = start(client, identifier, etag, state)
    assert (
        client.get(
            CALLBACK, query_string={"code": "test", "state": query["state"][0], "client_id": "oaiapp_test"}
        ).status_code
        == 200
    )
    entered, release = Event(), Event()

    def held():
        assert app.config["RUNTIME_REQUEST_TRACKER"]._active == 1
        entered.set()
        assert release.wait(8)

    state["token_hook"] = held
    recovery = desktop._DesktopShutdownRecoveryOwner(app)
    app.extensions["r107.cleanup"] = recovery

    def request():
        with app.test_client() as other:
            response = other.post(
                BASE + f"/{identifier}/oauth/complete",
                headers={**HEADERS, "If-Match": etag},
                json={"transaction_id": data["transaction_id"]},
                buffered=True,
            )
            return response.status_code

    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(request)
        try:
            assert entered.wait(5)
            with pytest.raises(desktop.DesktopBackendShutdownIncomplete):
                recovery.release(deadline=time.monotonic() + 0.15)
            assert app.config["SERVICE_CONNECTION_STORE"] is store
            assert client.get(BASE + f"/{identifier}/oauth/status", headers=HEADERS).status_code == 503
        finally:
            release.set()
            assert task.result(timeout=8) == 200
            recovery.release(deadline=time.monotonic() + 10)


def test_lost_installed_oauth_owner_is_not_recreated_by_read(flow):
    app, client, store, state, who = flow
    identifier, etag = connected(flow)
    import hashlib

    def custody():
        paths = [
            store.workspace_dir / "workspace.json",
            *(store.workspace_dir / "service-connections-state").rglob("*"),
            *(store.workspace_dir / "secrets").rglob("*"),
        ]
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}

    before = custody()
    original = store.oauth
    store.oauth = None
    try:
        assert client.get(BASE + f"/{identifier}/oauth/status", headers=HEADERS).status_code == 422
        assert store.oauth is None
        assert custody() == before
    finally:
        store.oauth = original


@pytest.mark.parametrize(
    "variant", ["unconfigured", "hosted", "read-only", "foreign-peer", "foreign-origin", "malformed", "extra-field"]
)
def test_start_refuses_before_acquisition_without_approved_authority(flow, variant):
    app, client, store, state, who = flow
    identifier, etag = create(client)
    headers = {**HEADERS, "If-Match": etag}
    kwargs = {"json": {}}
    if variant == "unconfigured":
        app.config["SERVICE_OAUTH_CONFIG"] = {}
    if variant == "hosted":
        app.config["SERVICE_OAUTH_CONFIG"]["deployment"] = "hosted"
    if variant == "read-only":
        who[0] = VerifiedOperatorSession(ACTOR.actor_ref, ACTOR.session_binding, ("admin.services.read",))
    if variant == "foreign-peer":
        kwargs["environ_overrides"] = {"REMOTE_ADDR": "203.0.113.9"}
    if variant == "foreign-origin":
        headers["Sec-Fetch-Site"] = "cross-site"
    if variant == "malformed":
        kwargs = {"data": "{", "content_type": "application/json"}
    if variant == "extra-field":
        kwargs = {"json": {"redirect_uri": "https://foreign.invalid/callback"}}
    result = client.post(BASE + f"/{identifier}/oauth/start", headers=headers, **kwargs)
    assert result.status_code in {400, 403, 422}
    assert state["calls"] == []
    assert not (store.workspace_dir / "service-connections-state" / "oauth-state.json").exists()
