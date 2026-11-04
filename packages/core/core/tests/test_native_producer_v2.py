"""Successful synthetic native lifecycle through the ordinary application factory."""
from __future__ import annotations

from typing import Any

import pytest

from flinttrade_core.native_producer_v2 import ProducerRegistration
from packages.core.core.tests.test_native_custody_owner import _preview, _selection
from packages.core.core.tests.test_native_financial_owner import BASE, RUN, _facts, _qualify, _source
from packages.core.core.tests.test_native_workflow_v2 import MountedDesk, _configuration
from packages.core.core.tests.test_native_workflow_v2 import mounted_desk as mounted_desk

pytestmark = pytest.mark.integration


def _registered(
    desk: MountedDesk, *, interval_ms: int = 25, order: dict[str, Any] | None = None,
) -> tuple[Any, Any]:
    """Register a concrete bounded strategy against the real synthetic account."""
    workflow = desk.app.config["EXECUTION_SESSIONS"].autonomy.v2
    source = _source(desk)
    from flinttrade_gateway.brokers.dhan_mapping import build_security_resolver

    desk.app.config["ACTIVE_BROKER_ADAPTERS"]["dhan"].install_security_resolver(build_security_resolver([
        {"EXCH_ID": "NSE", "SEGMENT": "E", "SECURITY_ID": "123", "TRADING_SYMBOL": "SYNTH"},
    ]))
    registration = ProducerRegistration.threshold_entry(
        name="threshold-entry", order=order if order is not None else {
                                       "symbol": "SYNTH", "exchange": "NSE", "product": "CNC",
                                       "action": "BUY", "quantity": "1", "price": "4", "pricetype": "LIMIT"},
        threshold="4", interval_ms=interval_ms, max_decisions=2,
    )
    pin = workflow.register_producer(registration)
    request = _configuration()
    request["config"].update(environment="synthetic", producer=pin)
    request["config"]["risk"]["max_mark_age_ms"] = 60000
    result = desk.client.post(BASE + "/native-v2", json=request, headers=desk.headers)
    assert result.status_code == 201, result.get_json()
    source.publish("mounted-native", _facts())
    return source, registration


def _granted(desk: MountedDesk) -> dict[str, Any]:
    view = _qualify(desk)
    selection = _selection(view)
    selection["limits"]["max_reads"] = 128  # Explicit test-operator allowance for canonical preflight reads.
    preview = _preview(desk, selection)
    accepted = desk.client.post(RUN + "/autonomy-v2/transfer-accept", json={
        "schema_version": "2", "preview_ref": preview["preview_ref"],
        "expected_duty_revision": preview["duty"]["duty_ref"]["revision"],
    }, headers=desk.headers)
    assert accepted.status_code == 200, accepted.get_json()
    result = desk.client.post(RUN + "/autonomy-v2/grant", json=selection, headers=desk.headers)
    assert result.status_code == 200, result.get_json()
    return result.get_json()["data"]


def test_registered_strategy_grant_is_durable_and_not_start(mounted_desk: MountedDesk) -> None:
    """Persist a registered strategy grant without implicitly starting its worker.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
    """
    desk = mounted_desk
    _registered(desk)
    view = _granted(desk)
    assert view["report"]["status"] == "eligible"
    assert view["scope"]["environment"] == "synthetic"
    assert view["entry_state"] == "granted"
    assert view["grant"]["state"] == "active"
    assert view["effective_authority"] == "none"
    assert view["producer_state"] == "not_started"
    assert desk.app.config["EXECUTION_SESSIONS"].owners == {}
    assert desk.calls == []
    readback = desk.client.get(RUN + "/autonomy-v2", headers=desk.headers)
    assert readback.status_code == 200
    assert readback.get_json()["data"]["grant"] == view["grant"]


def _plan(source: Any, registration: Any, *, mark: str) -> None:
    """Publish the explicit synthetic market and prospective allocation through its owner."""
    from packages.core.core.tests.test_native_financial_owner import _fees, _ref

    facts = _facts()
    source.publish("mounted-native", facts)
    now = facts["observed_at_ms"]
    entry = {"entry_ref": _ref("producer-entry"), "lots": [], "remaining_possible_quantity": 1,
             "remaining_price_upper_bound": "4", "unknown_possible_write": False,
             "mark": mark, "mark_at_ms": now}
    source.publish_plan("mounted-native", order=registration.order,
                        market={"instrument_id": "SYNTH", "exchange": "NSE", "product": "CNC",
                                "mark": mark, "observed_at_ms": now},
                        entry=entry, fees=_fees(entry, now, ("entry_pending", "exit_pending")))


def test_start_acquires_real_strategy_decisions_without_implicit_order(mounted_desk: MountedDesk) -> None:
    """Start the real registered strategy without inventing an order proposal.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
    """
    desk = mounted_desk
    source, registration = _registered(desk)
    _plan(source, registration, mark="5")  # Above the operator-selected buy threshold.
    view = _granted(desk)
    request = {"schema_version": "2", "run_id": "mounted-native",
               "expected_binding_revision": view["scope"]["binding_revision"],
               "grant_ref": view["grant"]["grant_ref"]}
    started = desk.client.post(RUN + "/autonomy-v2/start", json=request, headers=desk.headers)
    assert started.status_code == 200, started.get_json()
    registry = desk.app.config["EXECUTION_SESSIONS"]
    owner = registry.owners["mounted-native"]
    assert owner.completed.wait(5)
    assert owner.shutdown(0)
    assert owner.snapshot()["decisions"] == 2
    assert not owner.snapshot()["failed"]
    current = desk.client.get(RUN + "/autonomy-v2", headers=desk.headers).get_json()["data"]
    assert current["producer_state"] == "stopped"
    assert current["entry_state"] == "retired"
    assert current["grant"]["state"] == "revoked"
    assert desk.calls == []
    replay = desk.client.post(RUN + "/autonomy-v2/start", json=request, headers=desk.headers)
    assert replay.status_code == 409


def test_real_strategy_proposal_reserves_durably_before_canonical_refusal(mounted_desk: MountedDesk) -> None:
    """Default-Down Laya remains real; a refusal releases only proved unsent holds."""
    from packages.core.core.tests.test_native_financial_owner import _financial

    desk = mounted_desk
    source, registration = _registered(desk)
    _plan(source, registration, mark="4")
    view = _granted(desk)
    started = desk.client.post(RUN + "/autonomy-v2/start", json={
        "schema_version": "2", "run_id": "mounted-native",
        "expected_binding_revision": view["scope"]["binding_revision"], "grant_ref": view["grant"]["grant_ref"],
    }, headers=desk.headers)
    assert started.status_code == 200, started.get_json()
    owner = desk.app.config["EXECUTION_SESSIONS"].owners["mounted-native"]
    assert owner.completed.wait(5)
    assert owner.shutdown(0)
    assert owner.snapshot()["decisions"] == 1
    assert not owner.snapshot()["failed"]
    financial = _financial(desk)
    assert financial["reservations"]["producer-entry"]["state"] == "released"
    assert financial["reservations"]["producer-entry"]["command_id"] == "decision-0"
    assert desk.calls == []
