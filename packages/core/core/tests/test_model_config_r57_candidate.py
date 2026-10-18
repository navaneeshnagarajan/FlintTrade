"""Candidate confirmation races through real run, HTTP and durable owners."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from packages.core.core.tests.test_model_config_readback import evaluation_value, url_for
from packages.core.core.tests.test_run_adoption_integration import composed as composed
from packages.core.core.tests.test_run_adoption_integration import desk as desk, mounted as mounted
from packages.core.core.tests.test_service_tasks import BASE, HEADERS, policy

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("boundary", ["none", "derived-http", "durable-claim"])
def test_candidate_preview_identity_survives_persistence_boundary(
    composed: Any, monkeypatch: Any, boundary: str,
) -> None:
    """A changed admission cannot be claimed under an earlier serving pin."""
    owner, _supervisor, app, client, _store, calls, headers, _desk = composed
    value = evaluation_value(composed, "candidate")
    proposal = {"action": "candidate", "expected_revision": 0, "value": value}
    base = url_for(composed)
    preview = client.post(base + "/preview", headers=headers, json=proposal)
    assert preview.status_code == 200, preview.json
    pin = preview.json["target_identity"]["serving_identity"]
    dispatcher = owner.dispatcher()
    ledger = dispatcher.ledger
    candidate_key = "run-candidate:" + value["candidate"]
    admission_key = "admission:" + value["selection"]["connection_id"]
    derive = owner.candidate_configuration
    persist = owner.configure_candidate
    configure = ledger.configure_control
    persisting = False
    changes: list[str] = []

    def changed_http() -> None:
        changed = policy(value["selection"]["connection_revision"])
        changed["qualification"] = "synthetic-replacement-at-derivation"
        response = app.test_client().put(
            BASE + "/" + value["selection"]["connection_id"] + "/admission",
            headers={**HEADERS, "If-Match": '"1"'}, json=changed,
        )
        assert response.status_code == 200, response.json
        changes.append("derived-http")

    def observed_derive(*args: Any, **kwargs: Any) -> Any:
        result = derive(*args, **kwargs)
        if persisting and boundary == "derived-http":
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(changed_http).result(timeout=5)
        return result

    def observed_persist(*args: Any, **kwargs: Any) -> Any:
        nonlocal persisting
        persisting = True
        try:
            return persist(*args, **kwargs)
        finally:
            persisting = False

    def observed_claim(key: str, payload: dict[str, Any], **kwargs: Any) -> int:
        if key == candidate_key and boundary == "durable-claim":
            # The public durable mutator may run independently of the connection
            # fence. Change it after ALL identity derivation, before the claim's
            # real SQLite transaction; a preceding reread is not sufficient.
            revision, admission = ledger.control(admission_key)
            changed = {**admission, "qualification": "synthetic-replacement-at-claim"}
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(configure, admission_key, changed, expected_revision=revision).result(timeout=5)
            changes.append("durable-claim")
        return configure(key, payload, **kwargs)

    monkeypatch.setattr(owner, "candidate_configuration", observed_derive)
    monkeypatch.setattr(owner, "configure_candidate", observed_persist)
    monkeypatch.setattr(ledger, "configure_control", observed_claim)
    body = {**proposal, "confirmation": preview.json["confirmation"]}
    confirmed = client.post(base + "/confirm", headers=headers, json=body)
    current = ledger.control_snapshot(candidate_key)
    independent = client.get(base + "/control", headers=headers,
                             query_string={"action": "candidate", "trial": value["candidate"]})
    assert independent.status_code == 200, independent.json
    if boundary == "none":
        assert confirmed.status_code == 200, confirmed.json
        assert current[0] == 1 and current[1]["identity"] == pin
        assert independent.json["exact_control"] == confirmed.json["exact_control"]
    else:
        assert changes == [boundary]
        assert confirmed.status_code == 409, confirmed.json
        assert current == (0, None)
        assert independent.json["exact_control"]["revision"] == 0
    assert client.post(base + "/confirm", headers=headers, json=body).status_code == 409
    assert calls == [] and not owner.serving.bound and owner._activation is None
