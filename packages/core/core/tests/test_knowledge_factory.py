"""Normal factory composition: no test-only knowledge installer."""
from __future__ import annotations

import json

import pytest

from packages.core.core.tests.test_service_tasks import (
    BASE, HEADERS, configure, create, policy, task,
    mounted as _mounted_fixture,
)

mounted = _mounted_fixture
pytestmark = pytest.mark.integration


def test_normal_factory_has_full_procedures_without_eager_provider_or_consent(mounted):
    app, client, store, calls = mounted
    assert app.config.get("KNOWLEDGE_INSTALLED") is True
    assert "SERVICE_TASK_DISPATCHER" not in app.config
    assert "LEARNING_CONSENT_LEDGER" not in app.config
    document = client.get("/v1/knowledge/skills/risk_management", headers=HEADERS)
    assert document.status_code == 200, document.get_json()
    assert "## Position Sizing" in document.json["body"]
    assert not calls
    identifier = create(client)
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    admission = policy(revision)
    admission["reservation"].update(input_tokens=8192, currency_micros=1000)
    configure(client, identifier, admission)
    response = client.post(BASE + "/tasks", headers=HEADERS,
                           json=task(identifier, revision, context_refs=["skill:risk_management"]))
    assert response.status_code == 200, response.get_json()
    assert response.json["outcome"] == "completed", response.json
    assert len(calls) == 1
    assert document.json["body"] in json.loads(calls[0].content)["messages"][-1]["content"]
    assert response.json["context"][0]["version"] == document.json["version"]
    assert "LEARNING_CONSENT_LEDGER" not in app.config


def test_public_dispatcher_getter_is_the_same_lazy_owner_used_by_consent(mounted):
    from flinttrade_core import service_task_routes
    from flinttrade_core.knowledge_integration import get_learning_consent_ledger

    app, client, store, calls = mounted
    getter = getattr(service_task_routes, "get_service_task_dispatcher", None)
    assert callable(getter), "The shared dispatcher has no public composition seam"
    with app.app_context():
        first = getter()
        second = getter()
    assert first is second is app.config["SERVICE_TASK_DISPATCHER"]
    from flinttrade_core.service_task_dispatch import ServiceTaskDispatcher
    assert isinstance(first, ServiceTaskDispatcher)
    consent = get_learning_consent_ledger(app)
    assert consent.usage is first.ledger
    assert not calls
