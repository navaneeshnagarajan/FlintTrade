"""Finite custody consent through the normal native-v2 factory routes."""
from __future__ import annotations

import copy
import time
from typing import Any

import pytest

from packages.core.core.tests.test_native_financial_owner import (
    RUN,
    _cash_filled,
    _configure,
    _facts,
    _qualify,
    _settle_cash,
    _source,
)
from packages.core.core.tests.test_native_workflow_v2 import MountedDesk
from packages.core.core.tests.test_native_workflow_v2 import mounted_desk as mounted_desk


pytestmark = pytest.mark.integration


def _selection(view: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": "2", "run_id": "mounted-native",
            "expected_binding_revision": view["scope"]["binding_revision"],
            "report_ref": view["report"]["report_ref"], "policy_ref": view["config"]["risk"]["policy_ref"],
            "limits": {"instruments": [{"instrument_id": "SYNTH", "exchange": "NSE", "product": "CNC"}],
                       "actions": ["place"], "max_order_quantity": 1, "max_total_quantity": 2,
                       "max_commands": 2, "max_reads": 2, "max_duration_ms": 30000},
            "expires_at_ms": int(time.time() * 1000) + 20000}


def _preview(desk: MountedDesk, selection: dict[str, Any]) -> dict[str, Any]:
    response = desk.client.post(RUN + "/autonomy-v2/transfer-preview", json=selection, headers=desk.headers)
    assert response.status_code == 200, response.get_json()
    return response.get_json()["data"]


def test_finite_preview_acceptance_is_one_use_and_never_entry_authority(mounted_desk: MountedDesk) -> None:
    """Keep finite custody preview acceptance one-use and separate from entry authority.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
    """
    desk = mounted_desk
    source = _source(desk)
    _configure(desk)
    source.publish("mounted-native", _facts())
    view = _qualify(desk)
    selection = _selection(view)
    preview = _preview(desk, selection)
    assert preview["selection"] == selection
    body = {"schema_version": "2", "preview_ref": preview["preview_ref"],
            "expected_duty_revision": preview["duty"]["duty_ref"]["revision"]}
    response = desk.client.post(RUN + "/autonomy-v2/transfer-accept", json=body, headers=desk.headers)
    assert response.status_code == 200, response.get_json()
    receipt = response.get_json()["data"]
    assert receipt["receiving_operator"] == view["scope"]["operator"]
    assert receipt["outcome"] == "custody_transferred_not_flatness"
    replay = desk.client.post(RUN + "/autonomy-v2/transfer-accept", json=body, headers=desk.headers)
    assert replay.status_code == 409
    current = desk.client.get(RUN + "/autonomy-v2", headers=desk.headers).get_json()["data"]
    assert current["duty"]["receiving_acceptance_ref"] == receipt["transfer_ref"]
    assert current["effective_authority"] == "none" and current["grant"] is None
    grant = desk.client.post(RUN + "/autonomy-v2/grant", json=selection, headers=desk.headers)
    assert grant.status_code == 409, "missing producer/evidence must not grant"
    assert desk.app.config["EXECUTION_SESSIONS"].owners == {} and desk.calls == []


def test_empty_acceptance_never_covers_unallocated_future_fills(mounted_desk: MountedDesk) -> None:
    """An accepted empty census is not blanket custody for later observations."""
    desk = mounted_desk
    source = _source(desk)
    _configure(desk)
    facts = _facts()
    source.publish("mounted-native", facts)
    view = _qualify(desk)
    preview = _preview(desk, _selection(view))
    response = desk.client.post(RUN + "/autonomy-v2/transfer-accept", json={
        "schema_version": "2", "preview_ref": preview["preview_ref"],
        "expected_duty_revision": preview["duty"]["duty_ref"]["revision"],
    }, headers=desk.headers)
    assert response.status_code == 200
    try:
        _cash_filled(facts, mark="4")
        facts["tariff_ref"] = None
        source.publish("mounted-native", facts)
        view = _qualify(desk)
        assert view["duty"]["cumulative_entry_fill"] == 10
        assert view["duty"]["coverage"] == "stale"
        assert view["duty"]["receiving_acceptance_ref"] is None
        assert view["effective_authority"] == "none" and view["grant"] is None
    finally:
        from packages.core.core.tests.test_native_financial_owner import _ref

        facts["tariff_ref"] = _ref("synthetic-tariff")
        _settle_cash(desk, source, facts)


@pytest.mark.parametrize("change", ["selection", "stop", "source", "account", "expiry", "duty_revision"])
def test_preview_binding_cannot_survive_changed_custody(
    mounted_desk: MountedDesk, change: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalidate a preview when its exact custody binding changes.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
        change: Named mutation applied to the otherwise valid control.
        monkeypatch: Scoped replacements restored after this test.
    """
    desk = mounted_desk
    source = _source(desk)
    _configure(desk)
    facts = _facts()
    source.publish("mounted-native", facts)
    view = _qualify(desk)
    selection = _selection(view)
    preview = _preview(desk, selection)
    body = {"schema_version": "2", "preview_ref": preview["preview_ref"],
            "expected_duty_revision": preview["duty"]["duty_ref"]["revision"]}
    if change == "selection":
        changed = copy.deepcopy(selection)
        changed["limits"]["max_total_quantity"] = 3
        _preview(desk, changed)
    elif change == "stop":
        generation = desk.client.get(RUN, headers=desk.headers).get_json()["data"]["generation"]
        stopped = desk.client.post(RUN + "/stop", json={"account": "dhan:Mounted", "environment": "live",
                                  "expected_generation": generation}, headers=desk.headers)
        assert stopped.status_code == 200
    elif change == "source":
        facts["tariff_ref"]["revision"] = "b" * 64
        source.publish("mounted-native", facts)
    elif change == "account":
        from flinttrade_core.broker_identity import BrokerSelector

        registry = desk.app.config["REGISTRY"]
        selector = BrokerSelector("dhan", "Mounted")
        desk.app.extensions["flinttrade.registry_publication_owner"].remove_session_for_exact(
            selector, expected_registry=registry.snapshot_selector(selector),
        )
    elif change == "expiry":
        monkeypatch.setattr("flinttrade_core.native_custody_v2.time.time",
                            lambda: selection["expires_at_ms"] / 1000 + 1)
    else:
        body["expected_duty_revision"] = "c" * 64
    response = desk.client.post(RUN + "/autonomy-v2/transfer-accept", json=body, headers=desk.headers)
    assert response.status_code == 409, response.get_json()
    assert desk.calls == []


def test_start_refuses_missing_real_producer_and_no_worker_is_registered(mounted_desk: MountedDesk) -> None:
    """Refuse Start without the registered real producer and leave no worker behind.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
    """
    desk = mounted_desk
    _configure(desk, synthetic=False)
    status = desk.client.get(RUN + "/autonomy-v2", headers=desk.headers).get_json()["data"]
    response = desk.client.post(RUN + "/autonomy-v2/start", json={
        "schema_version": "2", "run_id": "mounted-native",
        "expected_binding_revision": status["scope"]["binding_revision"],
        "grant_ref": {"id": "invented", "revision": "a" * 64},
    }, headers=desk.headers)
    assert response.status_code == 409
    assert desk.app.config["EXECUTION_SESSIONS"].owners == {}
    assert desk.calls == []
