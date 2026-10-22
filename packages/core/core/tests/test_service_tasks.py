"""Public mounted non-trading dispatch with inert provider wire transports."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest

from flinttrade_core.app import create_flask_app
from flinttrade_core.auth_routes import VerifiedOperatorSession
from flinttrade_core.service_connection_store import ServiceConnectionStore

pytestmark = pytest.mark.integration
BASE = "/v1/services/connections"
NOW = datetime(2026, 10, 10, tzinfo=UTC)
HEADERS = {"Authorization": "Bearer synthetic-task-session"}


class Audit:
    def log_event(self, *args, **kwargs):
        return "synthetic-event"

    def log_idempotent_event(self, _kind, *, event_id, fields):
        return event_id


@pytest.fixture
def mounted(tmp_path, monkeypatch):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "synthetic-key")
    from flinttrade_core import service_connection_routes as routes

    principal = VerifiedOperatorSession(
        "operator:" + "a" * 64, "session:" + "b" * 64, ("admin.services.read", "admin.services.write")
    )
    monkeypatch.setattr(routes, "verify_operator_session_token", lambda _token: principal)
    store = ServiceConnectionStore(tmp_path / "workspace", audit_sink=lambda event: None)
    app = create_flask_app(
        safety=MagicMock(order_reservations_durable=True),
        audit=Audit(),
        contract_manager=MagicMock(),
        service_connection_store=store,
    )
    app.config.update(TESTING=True, SERVICE_TASK_CLOCK=lambda: NOW)
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "id": "synthetic-result",
                "model": "test-model-v1",
                "choices": [{"message": {"content": "Explained without trading."}, "finish_reason": "stop"}],
                "provider": "approved-upstream",
                "usage": {"prompt_tokens": 12, "completion_tokens": 5},
            },
        )

    app.config["SERVICE_TASK_TRANSPORT"] = httpx.MockTransport(transport)
    yield app, app.test_client(), store, calls
    _release_mounted_runtime(app)


def _release_mounted_runtime(app: Any) -> None:
    """Stop workers the proofless factory starts, including incident delivery.

    ``create_flask_app`` starts the incident delivery thread even when the
    caller has no backend lease. Leaving that daemon running keeps its
    file lock and log records alive for later tests on the same worker.
    """
    for key in (
        "MODEL_RUN_SERVICES",
        "DATA_RUNTIME",
        "LEARNING_CONSENT_LEDGER",
        "KNOWLEDGE_RUNTIME",
        "SERVICE_TASK_DISPATCHER",
        "SYSTEM_INCIDENTS",
    ):
        owner = app.config.pop(key, None)
        if owner is not None:
            owner.close()


def test_mounted_release_stops_the_incident_delivery_thread(tmp_path) -> None:
    """A mounted app must not leave incident delivery running after teardown."""
    from flinttrade_core.system_incidents import IncidentTimeline

    timeline = IncidentTimeline(tmp_path / "operational" / "incidents.sqlite")
    timeline.start()
    worker = timeline._thread
    assert isinstance(worker, threading.Thread)
    assert worker.is_alive()
    _release_mounted_runtime(SimpleNamespace(config={"SYSTEM_INCIDENTS": timeline}))
    assert timeline.closed is True
    assert worker.is_alive() is False


def create(client, provider="openrouter", model="test-model-v1", auth="api_key"):
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    response = client.post(
        BASE,
        headers={**HEADERS, "If-Match": revision, "Idempotency-Key": str(uuid4())},
        json={
            "provider_id": "llm:" + provider,
            "model": model,
            "label": "Synthetic provider",
            "auth_mode": auth,
            "credential": "synthetic-destination-secret",
        },
    )
    assert response.status_code == 201, response.get_json()
    identifier = response.get_json()["connection_id"]
    if auth == "chatgpt_oauth":
        from packages.core.core.tests.service_oauth_test_support import acquire_chatgpt

        acquire_chatgpt(client, identifier, HEADERS, NOW)
    return identifier


def policy(connection_revision, protocol="openrouter_chat", role="assistant", effort=None):
    return {
        "connection_revision": connection_revision,
        "enabled": True,
        "protocol": protocol,
        "role": role,
        "model_revision": "test-model-v1",
        "qualification": "synthetic-contract-evidence-v1",
        "entitlement": {
            "status": "verified",
            "evidence": "synthetic-entitlement-v1",
            "expires_at": (NOW + timedelta(hours=1)).isoformat(),
        },
        "privacy": {"classifications": ["public"], "retention": "no_training", "region": "test-region"},
        "efforts": effort or {"balanced": {"reasoning": {"effort": "medium"}}},
        "hard_controls": ["output_tokens"],
        "quota_group": "synthetic-shared-account",
        "downstream": "approved-upstream" if protocol == "openrouter_chat" else None,
        "reservation": {
            "requests": 1,
            "concurrency": 1,
            "input_tokens": 2048,
            "output_tokens": 256,
            "currency_micros": 100,
        },
        "tariff": {
            "provider_id": "llm:openrouter",
            "model": "test-model-v1",
            "model_revision": "test-model-v1",
            "source_kind": "operator",
            "source": "synthetic-tariff",
            "currency": "USD",
            "effective_from": NOW.isoformat(),
            "effective_until": (NOW + timedelta(hours=1)).isoformat(),
            "prices": {"input_tokens": {"micros": 1, "units": 100}, "output_tokens": {"micros": 1, "units": 10}},
            "exchange_rate": None,
        },
        "budget": {
            "currency": "USD",
            "window_start": NOW.isoformat(),
            "window_end": (NOW + timedelta(hours=1)).isoformat(),
            "limits": {
                "requests": 20,
                "concurrency": 2,
                "currency_micros": 10000,
                "input_tokens": 100000,
                "output_tokens": 10000,
            },
        },
    }


def configure(client, connection_id, value=None):
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    value = value or policy(revision)
    group = client.put(
        BASE + "/quota-groups/synthetic-shared-account", headers={**HEADERS, "If-Match": '"0"'}, json=value["budget"]
    )
    assert group.status_code in {200, 412}, group.get_json()
    response = client.put(BASE + f"/{connection_id}/admission", headers={**HEADERS, "If-Match": '"0"'}, json=value)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def task(connection_id, revision, **extra):
    return {
        "request_id": str(uuid4()),
        "mode": "fixed",
        "selection": {
            "connection_id": connection_id,
            "connection_revision": revision,
            "model": "test-model-v1",
            "effort": "balanced",
        },
        "prompt": "Explain the risk procedure, do not place an order.",
        "classification": "public",
        "context_refs": [],
        "purpose": "assistant",
        "deadline_ms": 2000,
        "max_output_tokens": 256,
        "required_hard_controls": ["output_tokens"],
        **extra,
    }


def test_fixed_task_uses_mounted_control_plane_wire_and_durable_receipt(mounted):
    app, client, store, calls = mounted
    identifier = create(client)
    configure(client, identifier)
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    payload = task(identifier, revision)
    response = client.post(BASE + "/tasks", headers=HEADERS, json=payload)
    assert response.status_code == 200, response.get_json()
    result = response.get_json()
    assert result["outcome"] == "completed"
    assert result["output"] == "Explained without trading."
    assert len(calls) == 1
    wire = json.loads(calls[0].content)
    assert str(calls[0].url) == "https://openrouter.ai/api/v1/chat/completions"
    assert wire["reasoning"] == {"effort": "medium"}
    assert wire["provider"] == {
        "only": ["approved-upstream"],
        "allow_fallbacks": False,
        "require_parameters": True,
        "data_collection": "deny",
        "zdr": False,
    }
    assert wire["max_tokens"] == 256
    assert "tools" not in wire
    assert calls[0].headers["authorization"] == "Bearer synthetic-destination-secret"
    assert result["attempts"][0]["state"] == "SETTLED"
    assert result["selection"]["connection_id"] == identifier
    assert result["effective_effort"] == {"reasoning": {"effort": "medium"}}
    assert "synthetic-destination-secret" not in response.get_data(as_text=True)
    read = client.get(BASE + "/tasks/" + payload["request_id"], headers=HEADERS)
    assert read.status_code == 200
    assert read.get_json()["outcome"] == "completed"
    duplicate = client.post(BASE + "/tasks", headers=HEADERS, json=payload)
    assert duplicate.status_code == 200
    assert len(calls) == 1


@pytest.mark.parametrize("with_procedure", [False, True], ids=["no-context", "bundled-procedure"])
def test_decision_routes_only_opaque_eligible_choice_into_native_messages(mounted, with_procedure):
    app, client, store, calls = mounted
    document = None
    if with_procedure:
        read = client.get("/v1/knowledge/skills/risk_management", headers=HEADERS)
        assert read.status_code == 200, read.get_json()
        document = read.get_json()
    target = create(client, "anthropic")
    router = create(client, "openai")
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    target_policy = policy(
        revision, "anthropic_messages", effort={"balanced": {"thinking": {"type": "enabled", "budget_tokens": 1024}}}
    )
    target_policy["tariff"]["provider_id"] = "llm:anthropic"
    target_policy["reservation"]["output_tokens"] = 2048
    target_policy["reservation"]["currency_micros"] = 500
    if with_procedure:
        target_policy["reservation"].update(input_tokens=8192, currency_micros=1000)
    configure(client, target, target_policy)
    router_policy = policy(revision, "openai_decisions", "task_router", {"not_applicable": {}})
    router_policy["tariff"]["provider_id"] = "llm:openai"
    router_policy["hard_controls"] = []
    router_policy["reservation"]["input_tokens"] = 8192
    router_policy["reservation"]["currency_micros"] = 500
    configure(client, router, router_policy)
    router_selection = task(router, revision)["selection"]
    router_selection["effort"] = "not_applicable"
    target_selection = task(target, revision)["selection"]
    config = client.put(
        BASE + "/task-routing",
        headers={**HEADERS, "If-Match": '"0"'},
        json={"bootstrap": router_selection, "candidates": [target_selection]},
    )
    assert config.status_code == 200, config.get_json()

    def transport(request):
        calls.append(request)
        wire = json.loads(request.content)
        if request.url.path == "/v1/decisions":
            projection = json.loads(wire["input"])
            assert set(projection) == {"purpose", "classification", "candidates"}
            assert "Explain" not in wire["input"]
            assert "synthetic-destination-secret" not in wire["input"]
            assert "https://" not in wire["input"]
            assert "Position Sizing" not in wire["input"]
            choice = wire["questions"][0]["choices"][0]["value"]
            return httpx.Response(
                200,
                json={
                    "model": "test-model-v1",
                    "answers": [
                        {
                            "type": "choice",
                            "name": "route",
                            "choice": choice,
                            "probabilities": [
                                {"value": choice, "probability": 1.0},
                                {"value": "abstain", "probability": 0.0},
                            ],
                            "confidence": 0.9,
                        }
                    ],
                    "usage": {"input_tokens": 80, "output_tokens": 0},
                },
            )
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "synthetic-destination-secret"
        assert "authorization" not in request.headers
        assert wire["thinking"] == {"type": "enabled", "budget_tokens": 1024}
        assert "reasoning" not in wire
        if document is not None:
            assert document["body"] in wire["messages"][-1]["content"]
        return httpx.Response(
            200,
            json={
                "id": "synthetic-message",
                "model": "test-model-v1",
                "content": [{"type": "text", "text": "Messages protocol explanation."}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 18, "output_tokens": 27},
            },
        )

    app.config["SERVICE_TASK_DISPATCHER"].transport = httpx.MockTransport(transport)
    response = client.post(
        BASE + "/tasks",
        headers=HEADERS,
        json=task(
            target,
            revision,
            mode="automatic",
            selection=None,
            max_output_tokens=2048,
            context_refs=["skill:risk_management"] if with_procedure else [],
        ),
    )
    assert response.status_code == 200, response.get_json()
    result = response.get_json()
    assert result["outcome"] == "completed", result
    assert result["output"] == "Messages protocol explanation."
    assert len(calls) == 2
    assert result["selection"] == target_selection
    assert result["routing"]["eligible_set_digest"]
    assert result["routing"]["decision"]["confidence"] == 0.9
    assert len(result["attempts"]) == 2
    assert {row["state"] for row in result["attempts"]} == {"SETTLED"}
    if document is not None:
        assert result["context"][0]["version"] == document["version"]


def test_shared_quota_race_and_unknown_survive_restart_without_failover(mounted):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    app, client, store, calls = mounted
    first = create(client)
    second = create(client)
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    configure(client, first)
    configure(client, second)
    group = policy(revision)["budget"]
    group["limits"]["concurrency"] = 1
    changed = client.put(
        BASE + "/quota-groups/synthetic-shared-account", headers={**HEADERS, "If-Match": '"1"'}, json=group
    )
    assert changed.status_code == 200
    entered, release = Event(), Event()

    def transport(request):
        calls.append(request)
        if len(calls) > 1:
            raise httpx.ReadTimeout("unexpected second dispatch", request=request)
        entered.set()
        assert release.wait(10), "test must release owned transport"
        raise httpx.ReadTimeout("synthetic lost remote result", request=request)

    owner = app.config["SERVICE_TASK_DISPATCHER"]
    owner.transport = httpx.MockTransport(transport)
    first_payload = task(first, revision)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(lambda: app.test_client().post(BASE + "/tasks", headers=HEADERS, json=first_payload))
        try:
            assert entered.wait(5)
            other = client.post(BASE + "/tasks", headers=HEADERS, json=task(second, revision)).get_json()
            assert other["code"] == "quota_exceeded", other
            assert len(calls) == 1
        finally:
            release.set()
        result = future.result(timeout=5).get_json()
    assert result["code"] == "provider_outcome_unknown"
    assert result["attempts"][0]["state"] == "UNKNOWN"
    owner.close()
    app.config.pop("SERVICE_TASK_DISPATCHER")
    replay = client.post(BASE + "/tasks", headers=HEADERS, json=first_payload).get_json()
    assert replay["code"] == "provider_outcome_unknown"
    held = client.post(BASE + "/tasks", headers=HEADERS, json=task(second, revision)).get_json()
    assert held["code"] == "quota_exceeded"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "protocol,provider,auth,hard",
    [
        ("openai_responses", "openai", "api_key", ["output_tokens"]),
        ("chatgpt_responses", "openai", "chatgpt_oauth", []),
        ("xai_responses", "grok", "api_key", ["visible_output_tokens"]),
    ],
)
def test_responses_auth_variants_preserve_effective_controls(mounted, protocol, provider, auth, hard):
    app, client, store, calls = mounted
    identifier = create(client, provider, auth=auth)
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    settings = policy(revision, protocol)
    settings["tariff"]["provider_id"] = "llm:" + provider
    settings["hard_controls"] = hard
    configure(client, identifier, settings)

    def transport(request):
        calls.append(request)
        wire = json.loads(request.content)
        assert request.url.path == "/v1/responses"
        assert wire["store"] is False
        assert wire["input"][0]["role"] == "user"
        assert wire["reasoning"] == {"effort": "medium"}
        result = {
            "id": "synthetic-response",
            "model": "test-model-v1",
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "Native response."}]}],
            "usage": {"input_tokens": 20, "output_tokens": 30},
        }
        if protocol == "chatgpt_responses":
            assert "max_output_tokens" not in wire
            assert "max_tool_calls" not in wire
            assert wire["stream"] is True
            event = "data: " + json.dumps({"type": "response.completed", "response": result}) + "\n\n"
            return httpx.Response(200, text=event, headers={"content-type": "text/event-stream"})
        assert wire["max_output_tokens"] == 256
        assert wire["stream"] is False
        return httpx.Response(200, json=result)

    app.config["SERVICE_TASK_DISPATCHER"].transport = httpx.MockTransport(transport)
    result = client.post(
        BASE + "/tasks", headers=HEADERS, json=task(identifier, revision, required_hard_controls=hard)
    ).get_json()
    assert result["outcome"] == "completed", result
    assert result["output"] == "Native response."
    assert result["controls"]["hard"] == hard
    if protocol != "openai_responses":
        refused = client.post(BASE + "/tasks", headers=HEADERS, json=task(identifier, revision)).get_json()
        assert refused["code"] == "hard_control_unsupported"
        assert len(calls) == 1


def test_authorised_context_seam_supplies_full_body_to_optional_unsloth(mounted):
    from flinttrade_core.service_task_contracts import TaskContext, TaskRefused

    app, client, store, calls = mounted
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    created = client.post(
        BASE,
        headers={**HEADERS, "If-Match": revision, "Idempotency-Key": str(uuid4())},
        json={
            "provider_id": "llm:custom",
            "label": "Optional local inference",
            "model": "test-model-v1",
            "endpoint": "http://127.0.0.1:8765",
            "auth_mode": "api_key",
            "credential": "synthetic-local-secret",
        },
    )
    assert created.status_code == 201
    identifier = created.get_json()["connection_id"]
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    value = policy(revision, "unsloth_chat", effort={"balanced": {"reasoning_effort": "medium"}})
    value["tariff"]["provider_id"] = "llm:custom"
    configure(client, identifier, value)

    class ContextOwner:
        revoked = False
        sends = []

        def resolve(self, *, references, actor, purpose):
            assert references == ("procedure:risk",)
            assert purpose == "assistant"
            assert actor.startswith("operator:")
            return (
                TaskContext(
                    "procedure:risk",
                    "immutable-v1",
                    "Step 1: check evidence. Step 2: explain uncertainty.",
                    "public",
                    "synthetic-context-rights-v1",
                ),
            )

        def validate_send(self, *, contexts, actor, purpose, connection, protocol):
            if self.revoked:
                raise TaskRefused("context_revoked", 403)
            assert contexts[0].version == "immutable-v1"
            self.sends.append((connection.connection_id, protocol))

    context_owner = ContextOwner()
    app.config["SERVICE_TASK_DISPATCHER"].context_resolver = context_owner

    def transport(request):
        calls.append(request)
        wire = json.loads(request.content)
        assert str(request.url) == "http://127.0.0.1:8765/v1/chat/completions"
        assert wire["reasoning_effort"] == "medium"
        assert wire["tool_choice"] == "none"
        assert "Step 1: check evidence. Step 2: explain uncertainty." in wire["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "id": "synthetic-local-result",
                "model": "test-model-v1",
                "choices": [{"message": {"content": "Grounded response."}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 8},
            },
        )

    app.config["SERVICE_TASK_DISPATCHER"].transport = httpx.MockTransport(transport)
    result = client.post(
        BASE + "/tasks", headers=HEADERS, json=task(identifier, revision, context_refs=["procedure:risk"])
    ).get_json()
    assert result["outcome"] == "completed", result
    assert result["context"][0]["version"] == "immutable-v1"
    assert result["context"][0]["body_digest"]
    assert "Step 1" not in json.dumps(result)
    assert len(context_owner.sends) == 1
    context_owner.revoked = True
    refused = client.post(
        BASE + "/tasks", headers=HEADERS, json=task(identifier, revision, context_refs=["procedure:risk"])
    ).get_json()
    assert refused["code"] == "context_revoked"
    assert len(calls) == 1


def routing_pool(client, *, private=False):
    target = create(client)
    router = create(client, "openai")
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    target_policy = policy(revision)
    if private:
        target_policy["privacy"]["classifications"].append("private")
    configure(client, target, target_policy)
    router_policy = policy(revision, "openai_decisions", "task_router", {"not_applicable": {}})
    router_policy["tariff"]["provider_id"] = "llm:openai"
    router_policy["hard_controls"] = []
    configure(client, router, router_policy)
    bootstrap = task(router, revision)["selection"]
    bootstrap["effort"] = "not_applicable"
    response = client.put(
        BASE + "/task-routing",
        headers={**HEADERS, "If-Match": '"0"'},
        json={"bootstrap": bootstrap, "candidates": [task(target, revision)["selection"]]},
    )
    assert response.status_code == 200, response.get_json()
    return target, router, revision


def decision_response(request, *, choice=None):
    wire = json.loads(request.content)
    selected = wire["questions"][0]["choices"][0]["value"]
    choice = choice or selected
    return {
        "model": "test-model-v1",
        "answers": [
            {
                "type": "choice",
                "name": "route",
                "choice": choice,
                "probabilities": [{"value": selected, "probability": 0.7}, {"value": "abstain", "probability": 0.3}],
                "confidence": 0.4,
            }
        ],
        "usage": {"input_tokens": 60, "output_tokens": 0},
    }


@pytest.mark.parametrize(
    "failure,code",
    [
        ("effort", "effort_unsupported"),
        ("private", "privacy_denied"),
        ("expired", "entitlement_expired"),
        ("unverified", "entitlement_unverified"),
        ("disabled", "connection_disabled"),
        ("hard_money", "hard_control_unsupported"),
        ("missing_qualification", "qualification_missing"),
        ("stale", "stale_configuration"),
    ],
)
def test_preflight_refusals_make_no_provider_attempt(mounted, failure, code):
    app, client, store, calls = mounted
    identifier = create(client)
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    value = policy(revision)
    if failure == "expired":
        value["entitlement"]["expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
    if failure == "unverified":
        value["entitlement"]["status"] = "unknown"
    if failure == "disabled":
        value["enabled"] = False
    if failure != "missing_qualification":
        configure(client, identifier, value)
    payload = task(identifier, revision)
    if failure == "effort":
        payload["selection"]["effort"] = "invented"
    if failure == "private":
        payload["classification"] = "private"
    if failure == "hard_money":
        payload["required_hard_controls"] = ["currency_micros"]
    if failure == "stale":
        client.patch(
            BASE + "/" + identifier,
            headers={**HEADERS, "If-Match": revision, "Idempotency-Key": str(uuid4())},
            json={"credential": "synthetic-new-secret"},
        )
    result = client.post(BASE + "/tasks", headers=HEADERS, json=payload).get_json()
    assert result["code"] == code, result
    assert result["outcome"] == "refused"
    assert result["attempts"] == []
    assert calls == []


@pytest.mark.parametrize(
    "failure,code",
    [
        ("invented", "invented_choice"),
        ("abstain", "router_abstained"),
        ("stale", "stale_configuration"),
        ("changed_policy", "stale_configuration"),
        ("unavailable", "provider_quota"),
        ("late", "deadline_exceeded"),
    ],
)
def test_router_failure_never_sends_task_or_selects_a_fallback(mounted, failure, code):
    from concurrent.futures import ThreadPoolExecutor

    app, client, store, calls = mounted
    target, router, revision = routing_pool(client)
    owner = app.config["SERVICE_TASK_DISPATCHER"]
    monotonic = [10.0]
    owner.monotonic = lambda: monotonic[0]

    def transport(request):
        calls.append(request)
        assert request.url.path == "/v1/decisions", "no task-provider I/O permitted"
        if failure == "unavailable":
            return httpx.Response(429, json={"error": "private provider diagnostic"})
        response = decision_response(
            request, choice="invented" if failure == "invented" else "abstain" if failure == "abstain" else None
        )
        if failure == "stale":
            # A concurrent real request has its own Flask/contextvars scope.
            # Re-entering the same WSGI app on this thread is not that race.
            with ThreadPoolExecutor(max_workers=1) as edits:
                changed = edits.submit(
                    lambda: app.test_client().patch(
                        BASE + "/" + target,
                        headers={**HEADERS, "If-Match": revision, "Idempotency-Key": str(uuid4())},
                        json={"credential": "synthetic-rotated-credential"},
                    )
                ).result(timeout=5)
            assert changed.status_code == 200
        if failure == "changed_policy":
            settings = policy(revision)
            settings["enabled"] = False
            with ThreadPoolExecutor(max_workers=1) as edits:
                changed = edits.submit(
                    lambda: app.test_client().put(
                        BASE + "/" + target + "/admission", headers={**HEADERS, "If-Match": '"1"'}, json=settings
                    )
                ).result(timeout=5)
            assert changed.status_code == 200
        if failure == "late":
            monotonic[0] += 3
        return httpx.Response(200, json=response)

    owner.transport = httpx.MockTransport(transport)
    result = client.post(
        BASE + "/tasks", headers=HEADERS, json=task(target, revision, mode="automatic", selection=None)
    ).get_json()
    assert result["outcome"] == "refused", result
    assert result["code"] == code, result
    assert len(calls) == 1
    assert len(result["attempts"]) == 1
    assert "private provider diagnostic" not in json.dumps(result)


def test_router_privacy_refuses_before_metadata_egress(mounted):
    app, client, store, calls = mounted
    target, router, revision = routing_pool(client, private=True)
    result = client.post(
        BASE + "/tasks",
        headers=HEADERS,
        json=task(target, revision, classification="private", mode="automatic", selection=None),
    ).get_json()
    assert result["code"] == "privacy_denied", result
    assert calls == []


def test_router_and_task_combined_shared_cost_must_fit_before_router_io(mounted):
    app, client, store, calls = mounted
    target, router, revision = routing_pool(client)
    limits = policy(revision)["budget"]
    limits["limits"]["currency_micros"] = 100
    response = client.put(
        BASE + "/quota-groups/synthetic-shared-account", headers={**HEADERS, "If-Match": '"1"'}, json=limits
    )
    assert response.status_code == 200
    result = client.post(
        BASE + "/tasks", headers=HEADERS, json=task(target, revision, mode="automatic", selection=None)
    ).get_json()
    assert result["code"] == "eligible_pool_empty", result
    assert result["attempts"] == []
    assert calls == []


@pytest.mark.parametrize("raw", ["{", "[]", "null", "true", "42", '"text"'])
def test_malformed_task_bodies_are_rejected_before_dispatch(mounted, raw):
    app, client, store, calls = mounted
    response = client.post(BASE + "/tasks", headers=HEADERS, data=raw, content_type="application/json")
    assert response.status_code == 400
    assert "SERVICE_TASK_DISPATCHER" not in app.config
    assert calls == []


def test_task_family_preserves_auth_no_store_and_nontrading_purpose(mounted):
    app, client, store, calls = mounted
    assert client.post(BASE + "/tasks", json={}).status_code == 401
    assert client.post(BASE + "/tasks", headers={"X-API-Key": "synthetic-key"}, json={}).status_code == 403
    assert (
        client.post(BASE + "/tasks", headers=HEADERS, json={}, environ_base={"REMOTE_ADDR": "192.0.2.1"}).status_code
        == 403
    )
    response = client.post(
        BASE + "/tasks", headers=HEADERS, json=task(str(uuid4()), '"not-a-revision"', purpose="training")
    )
    assert response.status_code == 422
    assert response.headers["Cache-Control"] == "no-store"
    assert calls == []


def test_rejected_admission_change_is_atomic_with_its_budget(mounted):
    app, client, store, calls = mounted
    identifier = create(client)
    configure(client, identifier)
    owner = app.config["SERVICE_TASK_DISPATCHER"]
    connection = store.read_snapshot().connections[0]
    before = owner.ledger.budget(connection.ref)
    value = policy(client.get(BASE, headers=HEADERS).headers["ETag"])
    value["quota_group"] = "not-configured"
    value["budget"]["limits"]["currency_micros"] = 1
    response = client.put(BASE + "/" + identifier + "/admission", headers={**HEADERS, "If-Match": '"1"'}, json=value)
    assert response.status_code in {412, 503}
    assert owner.ledger.budget(connection.ref) == before
    assert owner.admission(identifier)["revision"] == 1


def test_restart_refuses_missing_task_authority_instead_of_recreating_empty(mounted):
    import sqlite3

    from flinttrade_core.service_usage import ServiceUsageLedger, UsageUnavailable

    app, client, store, calls = mounted
    identifier = create(client)
    configure(client, identifier)
    owner = app.config["SERVICE_TASK_DISPATCHER"]
    root = store.workspace_dir / "service-usage"
    owner.close()
    with sqlite3.connect(root / "usage.sqlite") as db:
        db.execute("DROP TABLE task_receipts")
    with pytest.raises(UsageUnavailable):
        replacement = ServiceUsageLedger(root, clock=lambda: NOW)
        replacement.close()


@pytest.mark.parametrize("variant", ["partial_sse", "response_drift", "malformed_usage", "redirect", "missing_usage"])
def test_provider_partial_or_invalid_evidence_keeps_unknown_reservation(mounted, variant):
    app, client, store, calls = mounted
    protocol = "chatgpt_responses" if variant == "partial_sse" else "openrouter_chat"
    provider = "openai" if variant == "partial_sse" else "openrouter"
    auth = "chatgpt_oauth" if variant == "partial_sse" else "api_key"
    identifier = create(client, provider, auth=auth)
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    settings = policy(revision, protocol)
    settings["tariff"]["provider_id"] = "llm:" + provider
    if variant == "partial_sse":
        settings["hard_controls"] = []
    configure(client, identifier, settings)

    def transport(request):
        calls.append(request)
        if variant == "redirect":
            return httpx.Response(307, headers={"location": "https://unapproved.invalid/invoke"})
        if variant == "partial_sse":
            return httpx.Response(200, text='data: {"type":"response.output_text.delta","delta":"partial"}\n\n')
        data = {
            "model": "test-model-v1",
            "provider": "approved-upstream",
            "choices": [{"message": {"content": "ignored"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        if variant == "response_drift":
            data["model"] = "unqualified-model"
        if variant == "malformed_usage":
            data["usage"]["prompt_tokens"] = True
        if variant == "missing_usage":
            del data["usage"]
        return httpx.Response(200, json=data)

    app.config["SERVICE_TASK_DISPATCHER"].transport = httpx.MockTransport(transport)
    result = client.post(
        BASE + "/tasks",
        headers=HEADERS,
        json=task(identifier, revision, required_hard_controls=settings["hard_controls"]),
    ).get_json()
    assert result["outcome"] == "refused", result
    assert result["attempts"][0]["state"] == "UNKNOWN"
    assert "output" not in result
    assert len(calls) == 1


def test_same_provider_instances_use_only_their_bound_credential(mounted):
    app, client, store, calls = mounted
    first = create(client)
    second = create(client)
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    changed = client.patch(
        BASE + "/" + second,
        headers={**HEADERS, "If-Match": revision, "Idempotency-Key": str(uuid4())},
        json={"credential": "synthetic-second-instance"},
    )
    assert changed.status_code == 200
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    configure(client, first)
    configure(client, second)
    for identifier in (second, first):
        result = client.post(BASE + "/tasks", headers=HEADERS, json=task(identifier, revision)).get_json()
        assert result["outcome"] == "completed", result
        assert result["selection"]["connection_id"] == identifier
    assert [call.headers["authorization"] for call in calls] == [
        "Bearer synthetic-second-instance",
        "Bearer synthetic-destination-secret",
    ]


def test_malformed_decision_shape_is_typed_unknown_not_server_error(mounted):
    app, client, store, calls = mounted
    target, router, revision = routing_pool(client)

    def transport(request):
        calls.append(request)
        response = decision_response(request)
        response["answers"] = [None]
        return httpx.Response(200, json=response)

    app.config["SERVICE_TASK_DISPATCHER"].transport = httpx.MockTransport(transport)
    response = client.post(
        BASE + "/tasks", headers=HEADERS, json=task(target, revision, mode="automatic", selection=None)
    )
    assert response.status_code == 200
    assert response.get_json()["code"] == "decision_contract_error"
    assert response.get_json()["attempts"][0]["state"] == "UNKNOWN"
    assert len(calls) == 1
