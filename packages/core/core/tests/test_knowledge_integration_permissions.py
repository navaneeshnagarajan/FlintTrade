"""Operator consent workflow against the same lazy R1/R2 accounting owner."""
from __future__ import annotations

from datetime import timedelta

import pytest

from packages.core.core.tests.test_knowledge_integration import knowledge as _knowledge_fixture
from packages.core.core.tests.test_learning_consent import dispatch, rights
from packages.core.core.tests.test_service_tasks import BASE, HEADERS, NOW, configure, create, policy
from packages.core.core.tests.test_service_tasks import mounted as _mounted_fixture

knowledge = _knowledge_fixture
mounted = _mounted_fixture
pytestmark = pytest.mark.integration
PERMISSIONS = "/v1/learning/permissions"


def proposal(app, client, store):
    from flinttrade_core.learning_consent import DatasetScope, Recipient
    from flinttrade_core.service_usage_contracts import USAGE_DIMENSIONS
    identifier = create(client)
    admission = policy(client.get(BASE, headers=HEADERS).headers["ETag"])
    admission["budget"]["limits"] = {key: 100000 for key in USAGE_DIMENSIONS}
    configure(client, identifier, admission)
    connection = next(c for c in store.read_snapshot().connections if str(c.connection_id) == identifier)
    scope = DatasetScope("synthetic-history", "1", ("native:synthetic:account-a",), ("paper",), ("run-a",),
                         ("journal",), ("symbol", "pnl"), ("train",), "redacted-v1", NOW, NOW + timedelta(days=1))
    recipient = Recipient(connection.ref, store.read_snapshot().etag, "synthetic-provider-owner", "synthetic-generation",
                          "api-key", "https://example.invalid/v1/chat/completions", "test-region", "terms-1",
                          "model", "1", "chat", ())
    payload = dict(scope=scope.to_dict(), recipient=recipient.to_dict(), purpose="reflection", operations=["chat"],
                   valid_from=NOW.isoformat(), valid_until=(NOW + timedelta(hours=1)).isoformat(),
                   limits={key: 10000 for key in USAGE_DIMENSIONS}, max_rows=2, max_trials=2,
                   retention="delete-after-1-day", derivatives="same-scope-no-publication", objective="checked lessons",
                   rights=rights().to_public_dict(), supersedes=None)
    # Synthetic independent authority: normal application boot installs no
    # private-dataset grant, recipient qualification or default rights.
    app.config["LEARNING_PERMISSION_RESOLVER"] = lambda **kw: (scope, recipient, rights()) if (
        kw["actor"] == "operator:" + "a" * 64 and kw["scope"] == scope and kw["recipient"] == recipient
        and kw["purpose"] == "reflection") else None
    return payload, scope, recipient


def test_confirmed_grant_shared_usage_manifest_receipt_revoke_and_durable_read(knowledge):
    app, client, store, calls = knowledge
    payload, scope, recipient = proposal(app, client, store)
    preview = client.post(PERMISSIONS + "/preview", headers=HEADERS, json=payload)
    assert preview.status_code == 200, preview.json
    result = client.post(PERMISSIONS + "/grants", headers=HEADERS,
                         json={**payload, "confirmation": preview.json["confirmation"]})
    assert result.status_code == 200, result.json
    grant_id = result.json["grant_id"]
    gate = app.config["LEARNING_CONSENT_LEDGER"]
    assert gate.usage is app.config["SERVICE_TASK_DISPATCHER"].ledger
    from flinttrade_core.learning_consent import DatasetRecord, LearningConsentLedger, LearningRefused
    record = DatasetRecord("row-a", scope.accounts[0], "paper", "run-a", "journal", NOW, "train",
                           {"symbol": "FIXTURE", "pnl": 1}, rights())
    batch = gate.batch(scope, (record,), b"fixture", transform=scope.transform)
    sent = []
    from flinttrade_core.service_usage_contracts import TariffSnapshot
    tariff = TariffSnapshot(recipient.connection.provider_id, "model", "1", "operator", "fixture", "USD",
                            NOW, NOW + timedelta(days=1), {})
    dispatch(gate, grant_id, batch, recipient, send=lambda: sent.append("one"), tariff=tariff)
    assert sent == ["one"]
    manifest = client.get(PERMISSIONS + f"/grants/{grant_id}/manifests/{batch}", headers=HEADERS)
    assert manifest.status_code == 200, manifest.json
    receipt = client.get(PERMISSIONS + "/receipts/attempt-1", headers=HEADERS)
    assert receipt.status_code == 200, receipt.json
    assert receipt.json["batch_id"] == batch
    assert "values" not in manifest.json["members"][0]
    revoked = client.post(PERMISSIONS + f"/grants/{grant_id}/revoke", headers=HEADERS, json={})
    assert revoked.status_code == 200, revoked.json
    state = client.get(PERMISSIONS + f"/grants/{grant_id}", headers=HEADERS)
    assert state.json["egress_blocked"] is True
    assert state.json["grant"]["approver"] == "operator:" + "a" * 64
    assert state.json["remote_cancellation"] == "not-requested"
    assert state.json["weight_unlearning"] == "unavailable"
    with pytest.raises(LearningRefused, match="revoked"):
        dispatch(gate, grant_id, batch, recipient, attempt="attempt-after-revoke", send=lambda: sent.append("bad"))
    gate.close()
    reopened = LearningConsentLedger(gate.root, usage=gate.usage, clock=lambda: NOW)
    app.config["LEARNING_CONSENT_LEDGER"] = reopened
    assert client.get(PERMISSIONS + f"/grants/{grant_id}", headers=HEADERS).json["egress_blocked"] is True
    assert len(sent) == 1 and not calls


def test_duplicate_json_fields_are_rejected_before_confirmation(knowledge):
    app, client, store, calls = knowledge
    payload, scope, recipient = proposal(app, client, store)
    import json
    raw = json.dumps(payload)[:-1] + ', "max_rows": 1}'
    result = client.post(PERMISSIONS + "/preview", headers=HEADERS, data=raw, content_type="application/json")
    assert result.status_code == 400, result.json
    assert not app.config.get("LEARNING_CONFIRMATIONS")


def test_explicit_dev_origin_is_allowed_but_untrusted_origin_is_not(knowledge):
    app, client, store, calls = knowledge
    response = client.get("/v1/knowledge/skills", headers={**HEADERS, "Origin": "http://127.0.0.1:5173"})
    assert response.status_code == 200
    response = client.get("/v1/knowledge/skills", headers={**HEADERS, "Origin": "https://example.invalid"})
    assert response.status_code == 403


@pytest.mark.parametrize("raw", ['{', 'null', '[]', 'true', '1', '"x"', '{"scope":NaN}'])
def test_malformed_shapes_never_mint_grants(knowledge, raw):
    app, client, store, calls = knowledge
    result = client.post(PERMISSIONS + "/grants", headers=HEADERS,
                         data=raw, content_type="application/json")
    assert result.status_code == 400, result.json
    assert app.config.get("LEARNING_CONSENT_LEDGER") is None
    assert app.config.get("SERVICE_TASK_DISPATCHER") is None


@pytest.mark.parametrize("field,value", [
    ("max_rows", True), ("max_trials", 1.2), ("limits", {}), ("operations", "chat"),
    ("purpose", "assistant"), ("rights", None), ("retention", []), ("supersedes", False),
    ("valid_until", "not-a-date"), ("approver", "model-forged"),
])
def test_exact_permission_types_and_fields_refuse(knowledge, field, value):
    app, client, store, calls = knowledge
    payload, scope, recipient = proposal(app, client, store)
    payload[field] = value
    result = client.post(PERMISSIONS + "/preview", headers=HEADERS, json=payload)
    assert result.status_code == 400, result.json
    assert not app.config.get("LEARNING_CONFIRMATIONS")
    assert not calls


def test_confirmation_principal_scope_rights_and_replay_are_fenced(knowledge, monkeypatch):
    from flinttrade_core import service_connection_routes
    from flinttrade_core.auth_routes import VerifiedOperatorSession
    app, client, store, calls = knowledge
    payload, scope, recipient = proposal(app, client, store)
    verified = service_connection_routes.verify_operator_session_token
    preview = client.post(PERMISSIONS + "/preview", headers=HEADERS, json=payload).json
    monkeypatch.setattr(service_connection_routes, "verify_operator_session_token", lambda token:
                        VerifiedOperatorSession("operator:" + "c" * 64, "session:" + "d" * 64,
                                                ("admin.services.read", "admin.services.write")))
    result = client.post(PERMISSIONS + "/grants", headers=HEADERS,
                         json={**payload, "confirmation": preview["confirmation"]})
    assert result.status_code == 409
    monkeypatch.setattr(service_connection_routes, "verify_operator_session_token", verified)
    preview = client.post(PERMISSIONS + "/preview", headers=HEADERS, json=payload).json
    changed = {**payload, "max_rows": 100}
    assert client.post(PERMISSIONS + "/grants", headers=HEADERS,
                       json={**changed, "confirmation": preview["confirmation"]}).status_code == 409
    preview = client.post(PERMISSIONS + "/preview", headers=HEADERS, json=payload).json
    confirmed = {**payload, "confirmation": preview["confirmation"]}
    grant = client.post(PERMISSIONS + "/grants", headers=HEADERS, json=confirmed).json["grant_id"]
    assert client.post(PERMISSIONS + "/grants", headers=HEADERS, json=confirmed).status_code == 409
    monkeypatch.setattr(service_connection_routes, "verify_operator_session_token", lambda token:
                        VerifiedOperatorSession("operator:" + "c" * 64, "session:" + "d" * 64,
                                                ("admin.services.read", "admin.services.write")))
    assert client.get(PERMISSIONS + "/grants/" + grant, headers=HEADERS).status_code == 403
    assert client.post(PERMISSIONS + "/grants/" + grant + "/revoke", headers=HEADERS, json={}).status_code == 403
    assert app.config["LEARNING_CONSENT_LEDGER"].status(grant)["egress_blocked"] is False
    monkeypatch.setattr(service_connection_routes, "verify_operator_session_token", verified)
    payload["scope"]["accounts"] = ["native:synthetic:account-b"]
    assert client.post(PERMISSIONS + "/preview", headers=HEADERS, json=payload).status_code == 403
    payload["scope"] = scope.to_dict()
    payload["rights"]["rights"]["training_distillation"] = "unknown"
    assert client.post(PERMISSIONS + "/preview", headers=HEADERS, json=payload).status_code == 403
    assert not calls


def test_auth_scopes_origin_loopback_no_store_and_missing_authority(knowledge, monkeypatch):
    from flinttrade_core import service_connection_routes
    from flinttrade_core.auth_routes import VerifiedOperatorSession
    app, client, store, calls = knowledge
    assert app.config.get("SERVICE_TASK_DISPATCHER") is None
    assert app.config.get("LEARNING_CONSENT_LEDGER") is None
    for method, path in [("GET", "/v1/knowledge/skills"), ("POST", PERMISSIONS + "/grants"),
                         ("GET", "/v1/knowledge/unmatched"), ("GET", PERMISSIONS + "/receipts/unmatched")]:
        for headers, env, expected in [({}, {}, 401), ({"X-API-Key": "synthetic-key"}, {}, 403),
                                       (HEADERS, {"REMOTE_ADDR": "192.0.2.4"}, 403),
                                       ({**HEADERS, "Origin": "null"}, {}, 403),
                                       ({**HEADERS, "Sec-Fetch-Site": "cross-site"}, {}, 403)]:
            response = client.open(path, method=method, headers=headers, environ_overrides=env, json={})
            assert response.status_code == expected
            assert response.headers["Cache-Control"] == "no-store"
    payload, scope, recipient = proposal(app, client, store)
    app.config.pop("LEARNING_PERMISSION_RESOLVER")
    assert client.post(PERMISSIONS + "/preview", headers=HEADERS, json=payload).status_code == 503
    monkeypatch.setattr(service_connection_routes, "verify_operator_session_token", lambda token:
                        VerifiedOperatorSession("operator:" + "a" * 64, "session:" + "b" * 64,
                                                ("admin.services.read",)))
    assert client.get("/v1/knowledge/skills", headers=HEADERS).status_code == 200
    assert client.post(PERMISSIONS + "/preview", headers=HEADERS, json=payload).status_code == 403
    assert not calls
