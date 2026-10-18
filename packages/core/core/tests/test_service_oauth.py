"""Real mounted OAuth owner, with inert external HTTP only."""

import base64
import hashlib
import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from flinttrade_core.app import create_flask_app
from flinttrade_core.auth_routes import VerifiedOperatorSession
from flinttrade_core.service_connection_store import ServiceConnectionStore

pytestmark = pytest.mark.integration
BASE = "/v1/services/connections"
CALLBACK = "http://127.0.0.1:5000" + BASE + "/oauth/callback"
HEADERS = {"Authorization": "Bearer synthetic-session"}
ACTOR = VerifiedOperatorSession(
    "operator:" + "a" * 64, "session:" + "b" * 64, ("admin.services.read", "admin.services.write")
)
NOW = 1791850000


class Audit:
    def log_event(self, *args, **kwargs):
        return "test-event"

    def log_idempotent_event(self, _kind, *, event_id, fields):
        return event_id


@pytest.fixture
def flow(tmp_path, monkeypatch):
    from flinttrade_core import service_connection_routes as routes

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "test-key")
    who = [ACTOR]
    monkeypatch.setattr(routes, "verify_operator_session_token", lambda token: who[0])
    store = ServiceConnectionStore(tmp_path / "workspace", audit_sink=lambda e: None)
    app = create_flask_app(
        safety=MagicMock(order_reservations_durable=True),
        audit=Audit(),
        contract_manager=MagicMock(),
        service_connection_store=store,
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = "test-kid"
    state = {"now": NOW, "nonce": None, "calls": [], "refreshes": 0, "subject": "synthetic-subject"}

    def external(req):
        state["calls"].append((req.method, str(req.url)))
        if req.url.path == "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": "https://auth.openai.com",
                    "jwks_uri": "https://auth.openai.com/jwks",
                    "revocation_endpoint": "https://auth.openai.com/revoke",
                },
            )
        if req.url.path == "/jwks":
            return httpx.Response(200, json={"keys": [jwk]})
        if req.url.path == "/revoke":
            return httpx.Response(state.get("revoke_status", 200))
        if req.url.path == "/api/accounts/oauth/token":
            body = parse_qs(req.content.decode())
            if body["grant_type"] == ["authorization_code"]:
                assert body["client_id"] == ["oaiapp_test"]
                assert body["redirect_uri"] == [CALLBACK]
                challenge = (
                    base64.urlsafe_b64encode(hashlib.sha256(body["code_verifier"][0].encode()).digest())
                    .decode()
                    .rstrip("=")
                )
                assert challenge == state["challenge"]
            else:
                assert body["grant_type"] == ["refresh_token"]
                assert "scope" not in body
                state["refreshes"] += 1
            if state.get("token_hook"):
                state["token_hook"]()
            if state.get("timeout"):
                raise httpx.ReadTimeout("synthetic-redacted")
            claims = {
                "iss": "https://auth.openai.com",
                "aud": "oaiapp_test",
                "sub": state["subject"],
                "exp": state["now"] + 3600,
                "iat": state["now"],
                "nonce": state["nonce"],
            }
            invalid = state.get("invalid_identity")
            if invalid == "audience":
                claims["aud"] = "foreign-client"
            if invalid == "issuer":
                claims["iss"] = "https://foreign.invalid"
            signing = rsa.generate_private_key(public_exponent=65537, key_size=2048) if invalid == "signature" else key
            return httpx.Response(
                200,
                json={
                    "access_token": "synthetic-access-" + str(state["refreshes"]),
                    "refresh_token": "synthetic-refresh-" + str(state["refreshes"]),
                    "id_token": jwt.encode(claims, signing, algorithm="RS256", headers={"kid": "test-kid"}),
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": state.get(
                        "scopes", "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
                    ),
                },
            )
        raise AssertionError("unregistered external route")

    app.config.update(TESTING=True)
    # Normal factory must install the owner; trusted configuration is explicit.
    app.config["SERVICE_OAUTH_CONFIG"] = {"deployment": "local_oss", "redirect_uri": CALLBACK}
    app.config["SERVICE_OAUTH_TRANSPORT"] = httpx.MockTransport(external)
    app.config["SERVICE_OAUTH_CLOCK"] = lambda: state["now"]
    from functools import partial

    client = app.test_client()
    client.open = partial(client.open, buffered=True, base_url="http://127.0.0.1:5000")
    yield app, client, store, state, who
    import time
    from flinttrade_core.desktop import _DesktopShutdownRecoveryOwner

    app.extensions.setdefault("r107.cleanup", _DesktopShutdownRecoveryOwner(app)).release(
        deadline=time.monotonic() + 10
    )


def create(client, provider="llm:openai", auth="chatgpt_oauth"):
    etag = client.get(BASE, headers=HEADERS).headers["ETag"]
    response = client.post(
        BASE,
        headers={**HEADERS, "If-Match": etag, "Idempotency-Key": str(uuid4())},
        json={
            "provider_id": provider,
            "auth_mode": auth,
            "label": "OAuth test",
            "model": "test-model-v1",
            **({"endpoint": "https://synthetic.invalid"} if provider == "llm:custom" else {}),
        },
    )
    assert response.status_code == 201
    return response.get_json()["connection_id"], response.headers["ETag"]


def start(client, identifier, etag, state):
    result = client.post(BASE + f"/{identifier}/oauth/start", headers={**HEADERS, "If-Match": etag}, json={})
    assert result.status_code == 200
    data = result.get_json()
    query = parse_qs(urlsplit(data["authorization_url"]).query)
    state["nonce"] = query["nonce"][0]
    state["challenge"] = query["code_challenge"][0]
    assert query["client_id"] == ["dynamic_agent_client"]
    assert query["agent_name_hint"] == ["FlintTrade"]
    assert query["code_challenge_method"] == ["S256"]
    return data, query


def finish(client, identifier, etag, data, query):
    response = client.get(
        CALLBACK, query_string={"code": "synthetic-code", "state": query["state"][0], "client_id": "oaiapp_test"}
    )
    assert response.status_code == 200
    assert "synthetic-code" not in response.get_data(as_text=True)
    return client.post(
        BASE + f"/{identifier}/oauth/complete",
        headers={**HEADERS, "If-Match": etag},
        json={"transaction_id": data["transaction_id"]},
    )


def test_mounted_pkce_acquisition_and_secret_owner(flow):
    app, client, store, state, who = flow
    identifier, etag = create(client)
    data, query = start(client, identifier, etag, state)
    response = finish(client, identifier, etag, data, query)
    assert response.status_code == 200
    assert response.get_json()["status"] == "connected"
    read = client.get(BASE, headers=HEADERS)
    assert read.get_json()["connections"][0]["credential_configured"] is True
    assert read.headers["ETag"] != etag
    assert "synthetic-access" not in read.get_data(as_text=True)
    for path in store.workspace_dir.rglob("*"):
        if path.is_file():
            assert b"synthetic-access" not in path.read_bytes()


def connected(flow):
    app, client, store, state, who = flow
    identifier, etag = create(client)
    data, query = start(client, identifier, etag, state)
    response = finish(client, identifier, etag, data, query)
    assert response.status_code == 200
    return identifier, response.headers["ETag"]


def test_refresh_is_consumed_by_canonical_dispatch_and_disconnect_revokes(flow, monkeypatch):
    from packages.core.core.tests import test_service_tasks as tasks

    app, client, store, state, who = flow
    identifier, etag = connected(flow)
    monkeypatch.setattr(tasks, "NOW", datetime.fromtimestamp(NOW, UTC))
    app.config["SERVICE_TASK_CLOCK"] = lambda: datetime.fromtimestamp(state["now"], UTC)
    value = tasks.policy(etag, protocol="chatgpt_responses")
    value["tariff"]["provider_id"] = "llm:openai"
    value["hard_controls"] = []
    tasks.configure(client, identifier, value)
    state["now"] += 3570
    sent = []

    def inference(req):
        sent.append(req)
        assert req.headers["authorization"] == "Bearer synthetic-access-1"
        assert str(req.url) == "https://api.openai.com/v1/responses"
        body = json.loads(req.content)
        assert body["stream"] is True and body["store"] is False
        assert "max_output_tokens" not in body
        return httpx.Response(
            200,
            text="data: "
            + json.dumps(
                {
                    "type": "response.completed",
                    "response": {
                        "model": "test-model-v1",
                        "status": "completed",
                        "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
                        "usage": {"input_tokens": 10, "output_tokens": 2},
                    },
                }
            )
            + "\n\n",
        )

    app.config["SERVICE_TASK_TRANSPORT"] = httpx.MockTransport(inference)
    # Dispatcher was built during policy configuration; its transport is the inert boundary.
    app.config["SERVICE_TASK_DISPATCHER"].transport = app.config["SERVICE_TASK_TRANSPORT"]
    result = client.post(BASE + "/tasks", headers=HEADERS, json=tasks.task(identifier, etag, required_hard_controls=[]))
    assert result.status_code == 200
    assert result.get_json()["outcome"] == "completed"
    assert len(sent) == 1 and state["refreshes"] == 1
    assert client.get(BASE, headers=HEADERS).headers["ETag"] == etag
    disconnect = client.post(BASE + f"/{identifier}/oauth/disconnect", headers={**HEADERS, "If-Match": etag}, json={})
    assert disconnect.status_code == 200
    assert disconnect.get_json() == {"status": "disconnected", "remote_revocation": "confirmed"}
    assert client.get(BASE, headers=HEADERS).get_json()["connections"][0]["credential_configured"] is False
    readback = client.get(BASE + f"/{identifier}/oauth/status", headers=HEADERS)
    assert readback.status_code == 200
    assert readback.get_json() == {"status": "disconnected", "rotation": 1, "remote_revocation": "confirmed"}


def test_refresh_cannot_adopt_concurrent_budget_expansion(flow, monkeypatch):
    from packages.core.core.tests import test_service_tasks as tasks

    app, client, store, state, who = flow
    identifier, etag = connected(flow)
    monkeypatch.setattr(tasks, "NOW", datetime.fromtimestamp(NOW, UTC))
    app.config["SERVICE_TASK_CLOCK"] = lambda: datetime.fromtimestamp(state["now"], UTC)
    value = tasks.policy(etag, protocol="chatgpt_responses")
    value["hard_controls"] = []
    value["tariff"]["provider_id"] = "llm:openai"
    tasks.configure(client, identifier, value)
    state["now"] += 3570

    def expansion():
        state.pop("token_hook", None)
        value["reservation"]["currency_micros"] = 200
        from concurrent.futures import ThreadPoolExecutor

        def update():
            with app.test_client() as other:
                result = other.put(
                    BASE + f"/{identifier}/admission", headers={**HEADERS, "If-Match": '"1"'}, json=value, buffered=True
                )
                return result.status_code

        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(update).result(timeout=5) == 200

    state["token_hook"] = expansion
    sent = []
    app.config["SERVICE_TASK_DISPATCHER"].transport = httpx.MockTransport(
        lambda req: sent.append(req) or httpx.Response(500)
    )
    result = client.post(BASE + "/tasks", headers=HEADERS, json=tasks.task(identifier, etag, required_hard_controls=[]))
    assert result.status_code == 200
    assert result.get_json()["code"] == "stale_configuration"
    assert result.get_json()["attempts"] == [] and sent == []
    assert state["refreshes"] == 1
