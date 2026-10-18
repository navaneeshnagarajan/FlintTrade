"""Real closed trade -> confirmed configuration/consent -> exact inert wire."""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta

import httpx
import pytest

from packages.core.core.tests.test_practice_agent_runtime import desk as _desk_fixture, _wait_for
from packages.core.core.tests.test_run_adoption_integration import composed as composed, mounted as mounted
from packages.core.core.tests.test_model_run_config import mount
from packages.core.core.tests.test_service_tasks import BASE, HEADERS, NOW, create, configure, policy
from packages.core.core.tests.test_learning_consent import rights

pytestmark = pytest.mark.integration
base_desk = _desk_fixture


@pytest.fixture
def desk(base_desk):
    base_desk.signal = "BUY"
    return base_desk


def action(client, headers, url, name, value, revision=0):
    proposal = {"action": name, "expected_revision": revision, "value": value}
    preview = client.post(url + "/preview", headers=headers, json=proposal)
    assert preview.status_code == 200, preview.json
    response = client.post(url + "/confirm", headers=headers,
                           json={**proposal, "confirmation": preview.json["confirmation"]})
    assert response.status_code == 200, response.json
    return response.json


def prepare(composed):
    from flinttrade_core.run_learning import FIELDS
    from flinttrade_core.service_usage_contracts import USAGE_DIMENSIONS
    from flinttrade_core.service_providers import LicenceFact, RightsBasis, RightsGrant, intersect_rights
    owner, supervisor, app, client, store, calls, headers, desk = composed
    mount(app)
    run = supervisor.run
    url = f"/v1/model-runs/{run.run_id}/configuration"
    connection = create(client)
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    admission = policy(revision)
    admission["privacy"]["classifications"] = ["public", "private"]
    admission["budget"]["limits"] = {key: 1000000 for key in USAGE_DIMENSIONS}
    configure(client, connection, admission)
    selection = {"connection_id": connection, "connection_revision": revision,
                 "model": "test-model-v1", "effort": "balanced"}
    versions = {}
    source_rights = None
    for subject in ("source", "output"):
        document = "Explicit synthetic-only " + subject + " rights; no real data or provider entitlement."
        basis = RightsBasis.LICENCE if subject == "source" else RightsBasis.PROVIDER_TERMS
        resolved = intersect_rights(RightsGrant("synthetic-" + subject, basis, rights().rights, (
            LicenceFact("synthetic-" + subject, "dataset" if subject == "source" else "provider-output",
                        "closed-trades:" + run.run_id if subject == "source" else selection["model"],
                        "https://example.invalid/synthetic-" + subject, "synthetic-v1",
                        hashlib.sha256(document.encode()).hexdigest(), NOW.isoformat(), basis),)))
        reviewed = action(client, headers, url, "learning-rights", {
            "subject": subject, "selection": selection, "rights": resolved.to_public_dict(),
            "documents": {"synthetic-" + subject: document}, "fields": list(FIELDS),
            "review_statement": "Explicit synthetic operator-reviewed document policy, not measured entitlement"})
        versions[subject + "_rights"] = reviewed["result"]["event_id"]
        if subject == "source":
            source_rights = resolved
    dataset = action(client, headers, url, "learning-dataset", {
        **versions, "as_of_start": (NOW - timedelta(days=30)).isoformat(),
        "as_of_end": (NOW + timedelta(hours=1)).isoformat()})
    reservation = {key: 0 for key in USAGE_DIMENSIONS}
    reservation.update(requests=1, concurrency=1, input_tokens=32768, output_tokens=256, bytes=32768, currency_micros=1000)
    configured = action(client, headers, url, "learning-policy", {
        "selection": selection, "reservation": reservation,
        "controls": {key: "hard-local" for key in USAGE_DIMENSIONS},
        "controls_evidence": "explicit-synthetic-protocol-control-qualification",
        "principal": "synthetic-provider-account", "region": "test-region", "terms_revision": "synthetic-terms-v1",
        "valid_until": NOW.timestamp() + 3600, "max_output_tokens": 256, "timeout_seconds": 5})
    proposal = {"scope": dataset["result"]["scope"], "recipient": configured["result"]["recipient"],
        "purpose": "reflection", "operations": ["chat"], "valid_from": NOW.isoformat(),
        "valid_until": (NOW + timedelta(hours=1)).isoformat(), "limits": {key: 1000000 for key in USAGE_DIMENSIONS},
        "max_rows": 10, "max_trials": 10, "retention": "synthetic-one-day", "derivatives": "same-scope-no-publication",
        "objective": "synthetic-reflection", "rights": source_rights.to_public_dict(), "supersedes": None}
    preview = client.post("/v1/learning/permissions/preview", headers=headers, json=proposal)
    assert preview.status_code == 200, preview.json
    granted = client.post("/v1/learning/permissions/grants", headers=headers,
        json={**proposal, "confirmation": preview.json["confirmation"]})
    assert granted.status_code == 200, granted.json
    grant_id = granted.json["grant_id"]
    action(client, headers, url, "learning-binding", {"grant_id": grant_id})
    return run, grant_id, proposal


def test_actual_learning_reflects_only_confirmed_scope_and_persists_wire_lineage(composed, request):
    owner, supervisor, app, client, store, calls, headers, desk = composed
    run, grant_id, proposal = prepare(composed)
    captured = []
    def transport(request):
        assert desk.sandbox.get_positions() == [], "reflection preceded actual safe square-off"
        captured.append(request)
        return httpx.Response(200, json={"model": "test-model-v1", "id": "synthetic-reflection",
            "provider": "approved-upstream", "choices": [{"message": {"content": json.dumps({
                "recommendations": ["Review the opening range before entry"]})}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20}})
    owner.dispatcher().transport = httpx.MockTransport(transport)
    errors = []
    original_chat = run.trader.learning_client.policy.chat
    def observed_chat(*args, **kwargs):
        try:
            return original_chat(*args, **kwargs)
        except Exception as exc:
            errors.append(repr(exc))
            raise
    run.trader.learning_client.policy.chat = observed_chat
    supervisor.stop(desk.owner)
    _wait_for(lambda: run.cleanup_complete)
    assert run.trader.join_background_learning(0)
    assert len(captured) == 1, errors
    gate = app.config["LEARNING_CONSENT_LEDGER"]
    attempts = owner.dispatcher().ledger.list_attempts()
    receipt = gate.receipt(attempts[0].attempt_id)
    assert receipt["grant_id"] == grant_id
    assert receipt["payload_hash"] == hashlib.sha256(captured[0].content).hexdigest()
    request.node.user_properties.extend([
        ("learning_wire_sha256", receipt["payload_hash"]),
        ("learning_wire_bytes", str(len(captured[0].content))),
        ("learning_wire_protocol", "openrouter_chat"),
    ])
    wire = json.loads(captured[0].content)
    assert wire["provider"]["allow_fallbacks"] is False
    manifest = gate.manifest(receipt["batch_id"])
    assert manifest["scope"] == proposal["scope"]
    assert manifest["members"][0]["run"] == run.run_id
    assert manifest["members"][0]["account"] == "paper:sandbox"
    lessons = [app.config["KNOWLEDGE_RUNTIME"].ledger.get_event(i) for i in run.trader.learning_candidates]
    assert any("opening range" in e.payload.get("text", "") for e in lessons)
    assert all(e.payload["generation"] == "remote-model-candidate" for e in lessons)
    assert manifest["members"][0]["record_id"] in lessons[0].parent_ids
    assert run.trader._memory_context("RELIANCE") == "", "no fabricated independent evaluation"


@pytest.mark.parametrize("reason", ["missing", "revoked", "expired", "expanded", "mixed-rights", "recipient", "budget", "rights-changed"])
def test_actual_learning_refusals_do_not_send_and_keep_local_evidence(composed, reason):
    from flinttrade_core.service_providers import RightsResolution
    from flinttrade_core.learning_consent import DatasetRecord
    owner, supervisor, app, client, store, calls, headers, desk = composed
    run, grant_id, _ = prepare(composed)
    learner = run.trader.learning_client
    if reason == "missing":
        owner.runs.configure(run.run_id, "learning-binding", {}, expected_revision=1)
    elif reason == "revoked":
        app.config["LEARNING_CONSENT_LEDGER"].revoke(grant_id, actor=desk.owner)
    elif reason == "expired":
        app.config["LEARNING_CONSENT_LEDGER"].clock = lambda: NOW + timedelta(hours=2)
    elif reason in {"expanded", "mixed-rights"}:
        original_chat = learner.policy.chat
        def altered(messages, *, purpose, records):
            row = records[0]
            altered_record = DatasetRecord(row.record_id, "paper:other" if reason == "expanded" else row.account,
                row.environment, row.run, row.source, row.as_of, row.split, row.values,
                RightsResolution() if reason == "mixed-rights" else row.rights)
            return original_chat(messages, purpose=purpose, records=(altered_record,))
        learner.policy.chat = altered
    elif reason == "rights-changed":
        identity = learner.policy.control("rights:source")[1]["event_id"]
        current = app.config["KNOWLEDGE_RUNTIME"].ledger.get_event(identity).to_dict()["payload"]
        value = {key: current[key] for key in ("subject", "selection", "rights", "documents", "fields", "review_statement")}
        action(client, headers, f"/v1/model-runs/{run.run_id}/configuration", "learning-rights", value, revision=1)
    elif reason == "recipient":
        revision, value = learner.policy.control("policy")
        value["value"]["terms_revision"] = "changed-terms"
        owner.dispatcher().ledger.configure_control("run-learning-policy:" + run.run_id, value, expected_revision=revision)
    else:
        original = learner.policy.policy
        def narrowed(value):
            admission, recipient = original(value)
            value["reservation"]["bytes"] = 1
            return admission, recipient
        learner.policy.policy = narrowed
    owner.dispatcher().transport = httpx.MockTransport(lambda request: pytest.fail("forbidden learning send"))
    supervisor.stop(desk.owner)
    _wait_for(lambda: run.cleanup_complete)
    assert len(desk.sandbox.get_trades()) == 2
    assert run.trader.learning_candidates
    events = [app.config["KNOWLEDGE_RUNTIME"].ledger.get_event(i) for i in run.trader.learning_candidates]
    assert all(e.payload["generation"] == "local-rule-candidate" for e in events)
    assert not owner.dispatcher().ledger.list_attempts()
    assert not run.trader._memory_context("RELIANCE")
    status = app.config["LEARNING_CONSENT_LEDGER"].status(grant_id)
    assert status["remote_cancellation"] == "not-requested" and status["weight_unlearning"] == "unavailable"


def test_revoked_after_response_retains_output_as_unusable_quarantine(composed):
    from flinttrade_core.service_providers import PermissionState
    owner, supervisor, app, client, store, calls, headers, desk = composed
    run, grant_id, _ = prepare(composed)
    original = run.trader.learning_client.policy.chat
    def revoke_after_response(*args, **kwargs):
        result = original(*args, **kwargs)
        app.config["LEARNING_CONSENT_LEDGER"].revoke(grant_id, actor=desk.owner)
        return result
    run.trader.learning_client.policy.chat = revoke_after_response
    owner.dispatcher().transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "model": "test-model-v1", "provider": "approved-upstream", "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        "choices": [{"message": {"content": '{"recommendations":["Late synthetic lesson"]}'}, "finish_reason": "stop"}]}))
    supervisor.stop(desk.owner)
    _wait_for(lambda: run.cleanup_complete)
    assert run.trader.learning_candidates
    for identity in run.trader.learning_candidates:
        event = app.config["KNOWLEDGE_RUNTIME"].ledger.get_event(identity)
        assert event.payload["learning_state"] == "revoked-after-send"
        assert event.rights.rights.output_use is not PermissionState.ALLOWED
    assert run.trader._memory_context("RELIANCE") == ""


def test_matching_new_closed_trade_joins_original_grant_without_resetting_limits(composed):
    import asyncio
    owner, supervisor, app, client, store, calls, headers, desk = composed
    run, grant_id, _ = prepare(composed)
    wires = []
    def send(request):
        wires.append(request.content)
        return httpx.Response(200, json={"model": "test-model-v1", "provider": "approved-upstream",
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            "choices": [{"message": {"content": '{"recommendations":["Synthetic candidate"]}'}, "finish_reason": "stop"}]})
    owner.dispatcher().transport = httpx.MockTransport(send)
    async def close_and_reflect():
        assert await run.trader._square_off_all()
        await run.trader._reflect_and_persist(list(run.trader.state.closed_trades))
    asyncio.run(close_and_reflect())
    asyncio.run(run.trader.run_cycle())
    asyncio.run(close_and_reflect())
    assert len(desk.sandbox.get_trades()) == 4
    assert len(wires) == 2
    gate = app.config["LEARNING_CONSENT_LEDGER"]
    receipts = [gate.receipt(a.attempt_id) for a in owner.dispatcher().ledger.list_attempts()]
    assert {receipt["grant_id"] for receipt in receipts} == {grant_id}
    assert sorted(receipt["rows"] for receipt in receipts) == [1, 2]
    assert {receipt["payload_hash"] for receipt in receipts} == {hashlib.sha256(wire).hexdigest() for wire in wires}
    gate.revoke(grant_id, actor=desk.owner)
    supervisor.stop(desk.owner)
    _wait_for(lambda: run.cleanup_complete)
    assert len(wires) == 2


@pytest.mark.parametrize("reason", ["document", "hash", "stock", "unknown", "fields", "budget"])
def test_configuration_refuses_unresolved_or_expanded_rights_and_missing_budgets(composed, reason):
    from flinttrade_core.service_providers import RightsResolution
    owner, supervisor, app, client, store, calls, headers, desk = composed
    run, grant_id, _ = prepare(composed)
    policy_owner = run.trader.learning_client.policy
    if reason == "budget":
        value = policy_owner.control("policy")[1]["value"]
        value["reservation"].pop("bytes")
        name = "learning-policy"
    else:
        identity = policy_owner.control("rights:source")[1]["event_id"]
        persisted = app.config["KNOWLEDGE_RUNTIME"].ledger.get_event(identity).to_dict()["payload"]
        value = {key: persisted[key] for key in ("subject", "selection", "rights", "documents", "fields", "review_statement")}
        name = "learning-rights"
        if reason == "document":
            value["documents"] = {}
        elif reason == "hash":
            value["documents"]["synthetic-source"] += " changed bytes"
        elif reason == "stock":
            value["rights"] = app.config["KNOWLEDGE_RUNTIME"].stock_rights.to_public_dict()
        elif reason == "unknown":
            value["rights"] = RightsResolution().to_public_dict()
        else:
            value["fields"].append("another-account-secret")
    before = desk.store.events(run.run_id)
    response = client.post(f"/v1/model-runs/{run.run_id}/configuration/preview", headers=headers,
        json={"action": name, "value": value, "expected_revision": 1})
    assert response.status_code == 400, response.json
    assert desk.store.events(run.run_id) == before
    app.config["LEARNING_CONSENT_LEDGER"].revoke(grant_id, actor=desk.owner)
