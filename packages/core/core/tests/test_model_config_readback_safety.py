"""Fail-closed HTTP custody, history, authentication and delivery regressions."""
from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from packages.core.core.tests.test_run_adoption_integration import composed as composed
from packages.core.core.tests.test_run_adoption_integration import desk as desk, mounted as mounted
from packages.core.core.tests.test_model_config_readback import evaluation_value, rights_value, training_value, url_for
from packages.core.core.tests.test_run_learning_remote import action

pytestmark = pytest.mark.integration


def prepared(composed, category):
    if category == "learning-rights":
        value = rights_value(composed, "source")
        selector = {"action": category, "subject": "source"}
    elif category == "training-backend":
        value = training_value(composed)
        selector = {"action": category, "connection_id": value["connection_id"]}
    else:
        value = evaluation_value(composed, category)
        selector = {"action": category, "trial": value.get("trial", value.get("candidate"))}
        if category == "evaluation":
            selector["suite"] = value["suite"]
    action(composed[3], composed[6], url_for(composed), category, value)
    return selector, value


@pytest.mark.parametrize("category", ["candidate", "evaluation", "training-backend"])
@pytest.mark.parametrize("damage", ["missing-current", "corrupt-current", "missing-history"])
def test_exact_read_rejects_missing_or_disagreeing_usage_history(composed, category, damage):
    owner, _run, _app, client, _store, calls, headers, _desk = composed
    selector, _value = prepared(composed, category)
    key = "admission:" + selector["connection_id"] if category == "training-backend" else "run-" + category + ":" + selector["trial"]
    with owner.dispatcher().ledger._transaction() as db:
        if damage == "missing-current":
            db.execute("DELETE FROM task_controls WHERE key=?", (key,))
        elif damage == "missing-history":
            db.execute("DELETE FROM task_control_history WHERE key=?", (key,))
        else:
            row = json.loads(db.execute("SELECT payload FROM task_controls WHERE key=?", (key,)).fetchone()[0])
            if category == "candidate":
                row["deadline_ms"] += 1
            elif category == "evaluation":
                row["suite_digest"] = "f" * 64
            else:
                row["timeout_seconds"] += 1
            db.execute("UPDATE task_controls SET payload=? WHERE key=?", (json.dumps(row), key))
    response = client.get(url_for(composed) + "/control", headers=headers, query_string=selector)
    assert response.status_code == 503, response.json
    assert response.json == {"code": "model_configuration_unavailable"}
    assert calls == []


@pytest.mark.parametrize("category", ["learning-rights", "candidate", "evaluation", "training-backend"])
@pytest.mark.parametrize("damage", ["missing-owner", "corrupt-custody", "late-session"])
def test_exact_read_never_bootstraps_or_delivers_after_custody_or_authority_loss(composed, category, damage, monkeypatch):
    owner, supervisor, app, client, _store, calls, headers, _desk = composed
    selector, _value = prepared(composed, category)
    ledger = (owner._learning[supervisor.run.run_id].runtime.ledger if category == "learning-rights"
              else owner.dispatcher().ledger)
    if damage == "missing-owner":
        key = "KNOWLEDGE_RUNTIME" if category == "learning-rights" else "EVALUATION_STORE" if category in {"candidate", "evaluation"} else "SERVICE_TASK_DISPATCHER"
        monkeypatch.delitem(app.config, key)
    elif damage == "corrupt-custody":
        with ledger._transaction() as db:
            db.execute("DROP TABLE events" if category == "learning-rights" else "DROP TABLE task_controls")
    else:
        original = ledger._transaction
        @contextmanager
        def retiring():
            with original() as db:
                yield db
            monkeypatch.setattr(supervisor.run.adapter, "validate_session", lambda: (_ for _ in ()).throw(ValueError("retired")))
        monkeypatch.setattr(ledger, "_transaction", retiring)
    response = client.get(url_for(composed) + "/control", headers=headers, query_string=selector)
    assert response.status_code == 503, response.json
    assert "exact_control" not in response.json and calls == []


@pytest.mark.parametrize("category", ["learning-rights", "candidate", "evaluation", "training-backend"])
def test_exact_read_needs_real_current_actor_and_read_scope(composed, category):
    _owner, _supervisor, _app, client, _store, calls, headers, desk = composed
    selector, _value = prepared(composed, category)
    for bad in ({"X-API-Key": "synthetic-key"}, {**headers, "Origin": "https://foreign.invalid"},
                {"Authorization": "Bearer " + desk.token(sub="other", scopes=["admin.services.read"])},
                {"Authorization": "Bearer " + desk.token(scopes=["admin.services.write"])}):
        response = client.get(url_for(composed) + "/control", headers=bad, query_string=selector)
        assert response.status_code == 403, response.json
        assert "exact_control" not in response.json
    assert calls == []


@pytest.mark.parametrize("category", ["candidate", "evaluation"])
def test_exact_read_rejects_foreign_immutable_control_scope_before_policy_lookup(composed, category, monkeypatch):
    owner, _supervisor, app, client, _store, calls, headers, _desk = composed
    value = evaluation_value(composed, category)
    trial = value.get("trial", value.get("candidate"))
    evidence = app.config["EVALUATION_STORE"]
    record = evidence.trial(trial)
    manifest = evidence.experiment(record["experiment_id"])["manifest"]
    manifest["control_scope"]["account"] = "foreign-private-book"
    with evidence._db() as db:
        db.execute("UPDATE experiments SET manifest=? WHERE id=?", (json.dumps(manifest), record["experiment_id"]))
    seen = []
    monkeypatch.setattr(owner.dispatcher().ledger, "control_snapshot", lambda *args: seen.append(args))
    selector = {"action": category, "trial": trial}
    if category == "evaluation":
        selector["suite"] = value["suite"]
    response = client.get(url_for(composed) + "/control", headers=headers, query_string=selector)
    assert response.status_code == 403, response.json
    assert not seen and not calls


def test_rights_readback_excludes_private_document_uris_and_review_text(composed):
    value = rights_value(composed, "source")
    value["rights"]["grants"][0]["evidence"][0]["source_uri"] = "https://example.invalid/terms?token=PRIVATE-URI-R41"
    action(composed[3], composed[6], url_for(composed), "learning-rights", value)
    response = composed[3].get(url_for(composed) + "/control", headers=composed[6],
                              query_string={"action": "learning-rights", "subject": "source"})
    assert response.status_code == 200
    assert "PRIVATE-URI-R41" not in response.text
    assert "source_uri" not in response.text


@pytest.mark.parametrize("query", ["", "action=learning-rights&subject=source&subject=output", "action=learning-rights&subject=source&actor=foreign",
    "action=learning-rights&subject=SOURCE", "action=candidate&trial=%20id", "action=evaluation&trial=id&suite=x%2Fy",
    "action=training-backend&connection_id=0123456789abcdef0123456789abcdef"])
def test_selector_validation_precedes_any_control_lookup(composed, query, monkeypatch):
    owner, _supervisor, _app, client, _store, calls, headers, _desk = composed
    seen = []
    monkeypatch.setattr(owner.runs, "owner", lambda *args: seen.append(args))
    response = client.get(url_for(composed) + "/control?" + query, headers=headers)
    assert response.status_code == 400, response.json
    assert seen == [] and calls == []
