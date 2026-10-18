"""Exact rights reads retain established accounting custody without lazy repair."""
from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from packages.core.core.tests.test_model_config_readback import rights_value, url_for
from packages.core.core.tests.test_run_adoption_integration import composed as composed
from packages.core.core.tests.test_run_adoption_integration import desk as desk, mounted as mounted
from packages.core.core.tests.test_run_learning_remote import action

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("subject", ["source", "output"])
@pytest.mark.parametrize("loss", ["healthy", "absent", "closed", "removed-during-event", "closed-during-event"])
def test_exact_rights_never_reacquires_or_uses_retired_usage_custody(
    composed: Any, monkeypatch: Any, subject: str, loss: str,
) -> None:
    """The real event validator must not reconstruct custody, even mid-read."""
    from flinttrade_core import service_task_routes

    owner, _supervisor, app, client, _store, calls, headers, desk = composed
    value = rights_value(composed, subject)
    base = url_for(composed)
    confirmed = action(client, headers, base, "learning-rights", value)
    dispatcher = app.config["SERVICE_TASK_DISPATCHER"]
    memory = app.config["KNOWLEDGE_RUNTIME"].ledger
    paths = [dispatcher.ledger._path, memory._path, desk.store.database_path,
             desk.sandbox._db_path, app.config["EVALUATION_STORE"].path]

    def logical() -> list[str]:
        snapshots = []
        for path in paths:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
                snapshots.append("\n".join(db.iterdump()))
        return snapshots

    before = logical()
    getter = service_task_routes.get_service_task_dispatcher
    ledger_constructor = service_task_routes.ServiceUsageLedger
    dispatcher_constructor = service_task_routes.ServiceTaskDispatcher
    lazy_calls: list[str] = []
    constructed: list[Any] = []
    event_reads: list[str] = []
    original_event = memory.get_event

    def observed_getter() -> Any:
        lazy_calls.append("getter")
        return getter()

    def observed_ledger(*args: Any, **kwargs: Any) -> Any:
        result = ledger_constructor(*args, **kwargs)
        constructed.append(result)
        return result

    def observed_dispatcher(*args: Any, **kwargs: Any) -> Any:
        lazy_calls.append("dispatcher-constructor")
        return dispatcher_constructor(*args, **kwargs)

    def observed_event(*args: Any, **kwargs: Any) -> Any:
        result = original_event(*args, **kwargs)
        event_reads.append(args[0])
        if loss == "removed-during-event":
            app.config.pop("SERVICE_TASK_DISPATCHER", None)
        elif loss == "closed-during-event":
            dispatcher.close()
        return result

    monkeypatch.setattr(service_task_routes, "get_service_task_dispatcher", observed_getter)
    monkeypatch.setattr(service_task_routes, "ServiceUsageLedger", observed_ledger)
    monkeypatch.setattr(service_task_routes, "ServiceTaskDispatcher", observed_dispatcher)
    monkeypatch.setattr(memory, "get_event", observed_event)
    if loss == "absent":
        app.config.pop("SERVICE_TASK_DISPATCHER")
    elif loss == "closed":
        dispatcher.close()
    try:
        response = client.get(base + "/control", headers=headers,
                              query_string={"action": "learning-rights", "subject": subject})
        if loss.endswith("during-event"):
            assert event_reads, "Fault must reach the real rights-event read"
        assert lazy_calls == [], "An exact read must never enter the lazy getter"
        assert constructed == []
        assert logical() == before
        if loss == "healthy":
            assert response.status_code == 200, response.json
            assert response.json["exact_control"] == confirmed["exact_control"]
        else:
            assert response.status_code == 503, response.json
            assert response.json == {"code": "model_configuration_unavailable"}
        assert calls == [] and not owner.serving.bound and owner._activation is None
    finally:
        for ledger in constructed:
            ledger.close()
        app.config["SERVICE_TASK_DISPATCHER"] = dispatcher


def test_older_general_configuration_read_keeps_its_lazy_composition(composed: Any, monkeypatch: Any) -> None:
    """The bounded exact-read correction does not redefine the older general GET."""
    from flinttrade_core import service_task_routes

    _owner, _supervisor, app, client, _store, calls, headers, _desk = composed
    value = rights_value(composed, "source")
    action(client, headers, url_for(composed), "learning-rights", value)
    previous = app.config.pop("SERVICE_TASK_DISPATCHER")
    constructor = service_task_routes.ServiceUsageLedger
    constructed: list[Any] = []

    def observed(*args: Any, **kwargs: Any) -> Any:
        result = constructor(*args, **kwargs)
        constructed.append(result)
        return result

    monkeypatch.setattr(service_task_routes, "ServiceUsageLedger", observed)
    try:
        response = client.get(url_for(composed), headers=headers)
        assert response.status_code == 200, response.json
        assert len(constructed) == 1 and app.config["SERVICE_TASK_DISPATCHER"] is not previous
        assert "exact_control" not in response.json and "controls" in response.json
        assert calls == []
    finally:
        for ledger in constructed:
            ledger.close()
        app.config["SERVICE_TASK_DISPATCHER"] = previous
