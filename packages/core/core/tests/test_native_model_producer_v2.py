"""Normal-factory model decisions with only the external HTTP transport inert."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest

from packages.core.core.tests.test_native_financial_owner import BASE, RUN, _facts, _source
from packages.core.core.tests.test_native_producer_v2 import _granted, _plan
from packages.core.core.tests.test_native_workflow_v2 import MountedDesk, _configuration
from packages.core.core.tests.test_native_workflow_v2 import mounted_desk as mounted_desk
from packages.core.core.tests.test_service_tasks import policy

pytestmark = pytest.mark.integration


def model_desk(
    desk: MountedDesk, handle: Any, *, max_tokens: int = 5000, cost_cap: str = "1", options: bool = False,
) -> tuple[Any, Any]:
    """Configure existing service ownership via its real authenticated routes."""
    services = "/v1/services/connections"
    desk.app.config["SERVICE_TASK_TRANSPORT"] = httpx.MockTransport(handle)
    etag = desk.client.get(services, headers=desk.headers).headers["ETag"]
    created = desk.client.post(services, headers={**desk.headers, "If-Match": etag,
        "Idempotency-Key": str(uuid4())}, json={"provider_id": "llm:openrouter", "model": "test-model-v1",
            "label": "Synthetic native decision transport", "auth_mode": "api_key",
            "credential": "synthetic-no-provider-credential"})
    assert created.status_code == 201, created.get_json()
    connection_id = created.get_json()["connection_id"]
    etag = desk.client.get(services, headers=desk.headers).headers["ETag"]
    evidence = policy(etag)
    now = datetime.now(UTC)
    evidence["entitlement"]["expires_at"] = (now + timedelta(minutes=5)).isoformat()
    evidence["privacy"]["classifications"] = ["public", "private"]
    evidence["tariff"]["effective_from"] = (now - timedelta(seconds=1)).isoformat()
    evidence["tariff"]["effective_until"] = (now + timedelta(minutes=5)).isoformat()
    evidence["budget"].update(window_start=(now - timedelta(seconds=1)).isoformat(),
                              window_end=(now + timedelta(minutes=5)).isoformat())
    group = desk.client.put(services + "/quota-groups/synthetic-shared-account",
                           headers={**desk.headers, "If-Match": '"0"'}, json=evidence["budget"])
    assert group.status_code == 200, group.get_json()
    admitted = desk.client.put(services + f"/{connection_id}/admission",
                              headers={**desk.headers, "If-Match": '"0"'}, json=evidence)
    assert admitted.status_code == 200, admitted.get_json()
    # The real service store advanced the workspace version. The existing
    # account owner must rebind it; labels cannot repair a stale session.
    rebound = desk.client.post("/api/v1/native/accounts/dhan/Mounted/login",
        headers={**desk.headers, "Idempotency-Key": str(uuid4())},
        json={"credentials": {"client_id": "Mounted", "access_token": "synthetic-model-bound-account"}})
    assert rebound.status_code == 200, rebound.get_json()
    workflow = desk.app.config["EXECUTION_SESSIONS"].autonomy.v2
    source = _source(desk)
    pin = workflow.register_model_producer(name="model-threshold",
        order={"symbol": "SYNTH", "exchange": "NFO" if options else "NSE",
               "product": "NRML" if options else "CNC", "action": "BUY",
               "quantity": "1", "price": "4", "pricetype": "LIMIT"},
        threshold="4", interval_ms=25, max_decisions=2,
        selection={"connection_id": connection_id, "connection_revision": etag,
                   "model": "test-model-v1", "effort": "balanced"},
        max_requests=2, max_tokens=max_tokens, cost_cap={"amount": cost_cap, "currency": "USD"})
    request = _configuration()
    if options:
        from pathlib import Path

        corpus = json.loads((Path(__file__).parent / "fixtures/native-options-v2.json").read_text())
        request = next(c["value"] for c in corpus["cases"] if c["id"] == "options-ConfigureRequestV2-positive")
        request["config"].update(run_id="mounted-native", broker="dhan", account_id="Mounted")
    request["config"].update(environment="synthetic", producer=pin)
    request["config"]["risk"]["max_mark_age_ms"] = 60000
    configured = desk.client.post(BASE + "/native-v2", json=request, headers=desk.headers)
    assert configured.status_code == 201, configured.get_json()
    source.publish("mounted-native", _facts())
    return source, workflow._producers[pin["producer_ref"]["id"]]


def response(request: httpx.Request, *, decision: str = "hold") -> httpx.Response:
    """Literal provider wire result, never a patched proposal or authority."""
    assert request.method == "POST" and request.url.host == "openrouter.ai"
    body = json.loads(request.content)
    assert body["model"] == "test-model-v1"
    assert body["max_tokens"] == 256
    return httpx.Response(200, json={"id": "synthetic-result", "model": "test-model-v1",
        "choices": [{"message": {"content": json.dumps({"decision": decision})}, "finish_reason": "stop"}],
        "provider": "approved-upstream", "usage": {"prompt_tokens": 12, "completion_tokens": 5}})


def test_real_bounded_model_decisions_use_existing_dispatch_and_usage(mounted_desk: MountedDesk) -> None:
    """Route bounded model decisions through existing dispatch and usage accounting.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
    """
    desk = mounted_desk
    calls: list[httpx.Request] = []
    errors: list[BaseException] = []

    def send(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        try:
            return response(request)
        except BaseException as exc:
            errors.append(exc)
            raise

    source, registration = model_desk(desk, send)
    _plan(source, registration, mark="5")
    view = _granted(desk)
    assert calls == []  # Grant neither infers readiness nor spends model quota.
    started = desk.client.post(RUN + "/autonomy-v2/start", json={"schema_version": "2",
        "run_id": "mounted-native", "expected_binding_revision": view["scope"]["binding_revision"],
        "grant_ref": view["grant"]["grant_ref"]}, headers=desk.headers)
    assert started.status_code == 200, started.get_json()
    owner = desk.app.config["EXECUTION_SESSIONS"].owners["mounted-native"]
    assert owner.completed.wait(5)
    assert owner.shutdown(0)
    assert errors == []
    assert len(calls) == 2
    assert owner.snapshot()["decisions"] == 2 and not owner.failed
    assert desk.calls == []


def test_stop_during_actual_model_call_retains_owner_and_discards_late_text(mounted_desk: MountedDesk) -> None:
    """Retain the model-call owner after Stop and discard its late decision text.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
    """
    import threading

    desk = mounted_desk
    entered, release = threading.Event(), threading.Event()
    calls: list[httpx.Request] = []
    errors: list[BaseException] = []

    def send(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        entered.set()
        try:
            assert release.wait(10)
            return response(request, decision="propose")
        except BaseException as exc:
            errors.append(exc)
            raise

    source, registration = model_desk(desk, send)
    _plan(source, registration, mark="4")
    view = _granted(desk)
    owner = None
    try:
        result = desk.client.post(RUN + "/autonomy-v2/start", json={"schema_version": "2",
            "run_id": "mounted-native", "expected_binding_revision": view["scope"]["binding_revision"],
            "grant_ref": view["grant"]["grant_ref"]}, headers=desk.headers)
        assert result.status_code == 200, result.get_json()
        registry = desk.app.config["EXECUTION_SESSIONS"]
        owner = registry.owners["mounted-native"]
        assert entered.wait(5), owner.snapshot()
        token = desk.headers["Authorization"].removeprefix("Bearer ")
        with desk.app.app_context():
            reserved = registry.autonomy.v2.producer_status(token, "mounted-native")
        assert len(reserved["model_calls"]) == 1
        assert reserved["model_calls"][0]["state"] == "reserved"
        row = desk.client.get(RUN, headers=desk.headers).get_json()["data"]
        stopped = desk.client.post(RUN + "/stop", headers=desk.headers, json={
            "account": row["account"], "environment": row["environment"],
            "expected_generation": row["generation"]})
        assert stopped.status_code == 200, stopped.get_json()
        assert stopped.get_json()["data"]["autonomy_v2"]["entry_state"] == "retired"
        assert owner.snapshot()["alive"] and not owner.completed.is_set()
        assert registry.owners["mounted-native"] is owner
        assert len(calls) == 1 and desk.calls == []
    finally:
        release.set()
        if owner is not None:
            assert owner.completed.wait(5)
    assert owner is not None
    assert errors == [] and len(calls) == 1 and desk.calls == []
    with desk.app.app_context():
        retained = registry.autonomy.v2.producer_status(token, "mounted-native")
    assert retained["model_calls"][0]["receipt"]["accounting"] == "settled"
    assert retained["model_calls"][0]["tokens_reserved"] == reserved["model_calls"][0]["tokens_reserved"]
    assert retained["decisions"] == [] and owner.snapshot()["decisions"] == 0
