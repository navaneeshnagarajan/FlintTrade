"""Exact history reads distinguish unissued controls from damaged custody."""
from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from packages.core.core.tests.test_model_config_readback import training_value, url_for
from packages.core.core.tests.test_run_adoption_integration import composed as composed
from packages.core.core.tests.test_run_adoption_integration import desk as desk, mounted as mounted
from packages.core.core.tests.test_run_learning_remote import action

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("damage", [
    "none", "fractional-hole", "corrupt-old-json", "old-array", "old-noncanonical", "old-duplicate-key",
    "old-nonfinite", "missing-current", "current-mismatch", "missing-history",
])
def test_exact_training_requires_integral_history_and_every_retained_payload(
    composed: Any, damage: str,
) -> None:
    """Validate the retained sequence, not just its latest row/count/minimum."""
    owner, _supervisor, _app, client, _store, calls, headers, _desk = composed
    value = training_value(composed)
    base = url_for(composed)
    selector = {"action": "training-backend", "connection_id": value["connection_id"]}
    ledger = owner.dispatcher().ledger

    def logical() -> str:
        with sqlite3.connect(f"file:{ledger._path}?mode=ro", uri=True) as db:
            return "\n".join(db.iterdump())

    before_unissued = logical()
    unissued = client.get(base + "/control", headers=headers, query_string=selector)
    assert unissued.status_code == 200, unissued.json
    assert unissued.json["exact_control"]["revision"] == 0
    assert unissued.json["exact_control"]["value"] is None
    assert logical() == before_unissued
    action(client, headers, base, "training-backend", value)
    key = "admission:" + value["connection_id"]
    stored = ledger.control(key)[1]
    ledger.configure_control(key, stored, expected_revision=1)
    ledger.configure_control(key, stored, expected_revision=2)
    bad_payloads = {"corrupt-old-json": "not-json", "old-array": "[]", "old-noncanonical": '{"x": 1}',
                    "old-duplicate-key": '{"x":1,"x":2}', "old-nonfinite": '{"x":NaN}'}
    with ledger._transaction() as db:
        if damage == "fractional-hole":
            db.execute("UPDATE task_control_history SET revision=2.5 WHERE key=? AND revision=2", (key,))
        elif damage in bad_payloads:
            db.execute("UPDATE task_control_history SET payload=? WHERE key=? AND revision=2",
                       (bad_payloads[damage], key))
        elif damage == "missing-current":
            db.execute("DELETE FROM task_controls WHERE key=?", (key,))
        elif damage == "current-mismatch":
            db.execute("UPDATE task_controls SET payload='{}' WHERE key=?", (key,))
        elif damage == "missing-history":
            db.execute("DELETE FROM task_control_history WHERE key=? AND revision=2", (key,))
    before_read = logical()
    observed = client.get(base + "/control", headers=headers, query_string=selector)
    assert logical() == before_read, "Readback must neither repair nor mutate corrupt custody"
    if damage == "none":
        assert observed.status_code == 200, observed.json
        assert observed.json["exact_control"]["revision"] == 3
        assert observed.json["exact_control"]["value"] == value
    else:
        assert observed.status_code == 503, observed.json
        assert observed.json == {"code": "model_configuration_unavailable"}
    assert calls == [] and owner._activation is None and not owner.serving.bound
