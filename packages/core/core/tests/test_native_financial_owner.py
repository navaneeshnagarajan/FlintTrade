"""Normal-factory financial custody using explicitly issued primitive fixtures.

Synthetic facts are not provider qualification. Only the HTTP transport is
inert; authentication, account ownership, canonical capture and storage are real.
"""
from __future__ import annotations

import time
from typing import Any

import pytest
import requests

from packages.core.core.tests.test_native_workflow_v2 import MountedDesk, _configuration
from packages.core.core.tests.test_native_workflow_v2 import mounted_desk as mounted_desk

pytestmark = pytest.mark.integration

BASE = "/api/v1/execution-sessions"
RUN = BASE + "/mounted-native"


def _ref(name: str) -> dict[str, str]:
    import hashlib

    return {"id": name, "revision": hashlib.sha256(name.encode()).hexdigest()}


def _source(desk: MountedDesk) -> Any:
    return desk.app.config["EXECUTION_SESSIONS"].autonomy.v2.install_primitive_fixture_source(
        transport=desk.transport, transport_binding=requests.Session.send,
        current_transport_binding=lambda: requests.Session.send,
    )


def _configure(desk: MountedDesk, *, synthetic: bool = True) -> dict[str, Any]:
    request = _configuration()
    request["config"]["environment"] = "synthetic" if synthetic else "production"
    request["config"]["risk"]["max_mark_age_ms"] = 60000
    result = desk.client.post(BASE + "/native-v2", json=request, headers=desk.headers)
    assert result.status_code == 201, result.get_json()
    return result.get_json()["data"]


def _facts() -> dict[str, Any]:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = int(time.time() * 1000)
    return {
        "history_from_ms": now - 1000, "observed_at_ms": now,
        "native_order_date": datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat(),
        "tariff_ref": _ref("synthetic-tariff"), "tariff_from_ms": now - 1000,
        "tariff_through_ms": now + 60000, "entries": [], "fees": [],
    }


def _qualify(desk: MountedDesk) -> dict[str, Any]:
    result = desk.client.post(RUN + "/autonomy-v2/qualify", json={}, headers=desk.headers)
    assert result.status_code == 200, result.get_json()
    return result.get_json()["data"]


def _financial(desk: MountedDesk) -> dict[str, Any]:
    return desk.app.config["EXECUTION_SESSIONS"].autonomy.v2.financial_status(
        desk.headers["Authorization"][7:], "mounted-native",
    )


def test_bound_primitive_source_reaches_real_financial_owner(mounted_desk: MountedDesk) -> None:
    """An empty synthetic lifetime is assessed, not labelled eligible by a DTO."""
    desk = mounted_desk
    source = _source(desk)
    _configure(desk)
    source.publish("mounted-native", _facts())
    view = _qualify(desk)
    financial = _financial(desk)
    assert financial["assessment"]["status"] == "within_bounds"
    assert financial["assessment"]["capital"] == "0"
    assert financial["assessment"]["loss"] == "0"
    assert financial["loss_latch"]["retired"] is False
    assert view["grant"] is None and view["producer_state"] == "not_started"
    assert view["report"]["dimensions"]["observations"]["provenance"] == "synthetic"
    assert desk.calls == []


@pytest.mark.parametrize("missing", ["native_order_date", "tariff_ref", "history_from_ms"])
def test_unknown_primitive_facts_stay_unavailable(mounted_desk: MountedDesk, missing: str) -> None:
    """Keep missing native primitive facts unavailable rather than fabricate risk inputs.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
        missing: Owner observation or primitive fact deliberately omitted.
    """
    desk = mounted_desk
    source = _source(desk)
    _configure(desk)
    facts = _facts()
    facts[missing] = None
    source.publish("mounted-native", facts)
    view = _qualify(desk)
    assert _financial(desk)["assessment"]["status"] == "unavailable"
    assert view["report"]["status"] == "blocked" and view["grant"] is None
    assert desk.calls == []


def test_primitive_fixture_cannot_qualify_a_production_run(mounted_desk: MountedDesk) -> None:
    """Prevent synthetic primitive fixtures from qualifying a production run.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
    """
    desk = mounted_desk
    source = _source(desk)
    _configure(desk, synthetic=False)
    with pytest.raises(ValueError, match="synthetic"):
        source.publish("mounted-native", _facts())
    view = _qualify(desk)
    assert view["report"]["dimensions"]["fees"]["status"] == "missing"
    assert view["grant"] is None and desk.calls == []


def _fees(entry: dict[str, Any], now: int, phases: tuple[str, ...], *, options: bool = False) -> list[dict[str, Any]]:
    """Every named component is explicit; these are synthetic flat INR bounds."""
    return [{
        "allocation_ref": _ref(phase), "entry_ref": entry["entry_ref"], "phase": phase, "as_of_ms": now,
        "components": [{"name": name, "basis": "order", "basis_ref": _ref(phase + name),
                        "total_upper_bound": "1" if name == "brokerage" else "0",
                        "charges" if options else "incurred": []}
                       for name in ("brokerage", "exchange", "sebi", "stt", "stamp", "gst", "delivery", "other")],
    } for phase in phases]


def _cash_filled(facts: dict[str, Any], *, mark: str = "3") -> dict[str, Any]:
    entry = {
        "entry_ref": _ref("cash-entry"), "lots": [{"fill_ref": _ref("fill-one"), "quantity": 10,
            "unit_cost": "4", "exited_quantity": 0, "gross_exit_proceeds": "0"}],
        "remaining_possible_quantity": 0, "remaining_price_upper_bound": None, "unknown_possible_write": False,
        "mark": mark, "mark_at_ms": facts["observed_at_ms"],
    }
    facts["entries"] = [entry]
    facts["fees"] = _fees(entry, facts["observed_at_ms"], ("entry_filled", "exit_filled"))
    return entry


def test_loss_latch_once_and_known_fills_survive_stale_source_and_restart(mounted_desk: MountedDesk) -> None:
    """Threshold equality/overrun retires once, with no liquidation or rearm."""
    from flinttrade_core.execution_sessions import ExecutionSessions

    desk = mounted_desk
    source = _source(desk)
    _configure(desk)
    facts = _facts()
    _cash_filled(facts)
    try:
        source.publish("mounted-native", facts)
        first = _qualify(desk)
        financial = _financial(desk)
        assert financial["assessment"] == {"status": "breached", "reasons": ["loss_action_threshold"],
                                           "capital": "42", "exposure": "42", "loss": "11"}
        assert financial["floors"]["cash-entry"] == {"principal": "40", "fee": "2"}
        assert first["loss_threshold_latched"] and first["entry_state"] == "retired"
        events = first["events"]
        assert len(events) == 1
        assert _qualify(desk)["events"] == events
        facts["entries"] = []
        facts["fees"] = []
        source.publish("mounted-native", facts)
        assert _qualify(desk)["events"] == events
        assert _financial(desk)["assessment"]["status"] == "unavailable"
        assert _financial(desk)["floors"] == financial["floors"]
        owner = desk.app.config["EXECUTION_SESSIONS"]
        owner.close()
        desk.app.config["EXECUTION_SESSIONS"] = ExecutionSessions(desk.app, owner.path)
        view = desk.client.get(RUN + "/autonomy-v2", headers=desk.headers).get_json()["data"]
        assert view["events"] == events and view["loss_threshold_latched"]
        assert _financial(desk)["history"] == financial["history"]
        assert view["effective_authority"] == "none" and desk.calls == []
    finally:
        current = desk.app.config["EXECUTION_SESSIONS"].autonomy.v2
        issuer = source if current is source.workflow else _source(desk)
        _settle_cash(desk, issuer, facts)


def test_options_short_floor_and_disjoint_possible_hold_do_not_replenish(mounted_desk: MountedDesk) -> None:
    """A lower new standalone quote cannot erase a retained filled commitment."""
    import json
    from pathlib import Path

    desk = mounted_desk
    source = _source(desk)
    corpus = json.loads((Path(__file__).parent / "fixtures/native-options-v2.json").read_text())
    body = next(c["value"] for c in corpus["cases"] if c["id"] == "options-ConfigureRequestV2-positive")
    body["config"].update(run_id="mounted-native", broker="dhan", account_id="Mounted", environment="synthetic")
    body["config"]["risk"]["max_mark_age_ms"] = 60000
    response = desk.client.post(BASE + "/native-v2", json=body, headers=desk.headers)
    assert response.status_code == 201, response.get_json()
    facts = _facts()
    now = facts["observed_at_ms"]
    contract = {"contract_ref": _ref("contract"), "listing_ref": _ref("listing"), "token": "SyntheticOption",
                "underlying_ref": _ref("underlying"), "underlying": "NIFTY", "exchange": "NFO", "product": "NRML",
                "expiry_at_ms": now + 3600000, "right": "CE", "strike": "100", "units_per_lot": 1,
                "quantity_unit": "underlying_units", "currency": "INR"}
    entry = {"entry_ref": _ref("option-entry"), "contract": contract, "current_contract": contract,
             "listing_observed_at_ms": now, "side": "short",
             "fills": [{"fill_ref": _ref("option-fill"), "write_ref": _ref("option-write"),
                        "contract_ref": contract["contract_ref"], "quantity": 1, "unit_price": "4",
                        "observed_at_ms": now, "exits": []}],
             "writes": [{"write_ref": _ref("option-write"), "contract_ref": contract["contract_ref"],
                         "purpose": "entry", "side": "sell", "original_quantity": 2, "remaining_quantity": 1,
                         "released_quantity": 0, "resolution_ref": None, "premium_upper_bound": None}],
             "mark": {"contract_ref": contract["contract_ref"], "underlying_ref": contract["underlying_ref"],
                      "source_ref": _ref("mark"), "underlying_price": "50", "underlying_at_ms": now,
                      "option_price": "4", "option_at_ms": now},
             "margin": {"margin_ref": _ref("margin"), "contract_ref": contract["contract_ref"],
                        "filled_units": 1, "possible_short_units": 1, "filled_floor": "40", "pending_hold": "20",
                        "observed_at_ms": now, "allocation": "exact_standalone_disjoint"}}
    facts["entries"] = [entry]
    facts["fees"] = _fees(
        entry, now, ("entry_filled", "close_filled", "entry_possible", "close_possible"), options=True,
    )
    try:
        source.publish("mounted-native", facts)
        _qualify(desk)
        first = _financial(desk)
        assert first["assessment"]["status"] == "within_bounds", first
        assert first["assessment"]["capital"] == "64"
        assert first["assessment"]["exposure"] == "104"
        assert first["floors"]["option-entry"] == {"principal": "40", "fee": "2"}
        entry["margin"]["filled_floor"] = "10"
        source.publish("mounted-native", facts)
        _qualify(desk)
        assert _financial(desk)["assessment"]["capital"] == "64"
        assert _financial(desk)["floors"] == first["floors"]
        assert _financial(desk)["reservations"], "possible writes must have durable holds"
        entry["margin"]["pending_hold"] = None
        source.publish("mounted-native", facts)
        _qualify(desk)
        assert _financial(desk)["assessment"]["status"] == "unavailable"
        assert _financial(desk)["floors"] == first["floors"]
        assert desk.calls == []
    finally:
        entry["writes"][0].update(remaining_quantity=0, released_quantity=1, resolution_ref=_ref("released"))
        entry["writes"].append({"write_ref": _ref("closing-write"), "contract_ref": contract["contract_ref"],
                                "purpose": "exit", "side": "buy", "original_quantity": 1, "remaining_quantity": 0,
                                "released_quantity": 0, "resolution_ref": None, "premium_upper_bound": "4"})
        entry["fills"][0]["exits"] = [{"execution_ref": _ref("closing-fill"), "write_ref": _ref("closing-write"),
                                     "contract_ref": contract["contract_ref"], "quantity": 1, "unit_price": "4",
                                     "observed_at_ms": now, "kind": "trade", "settlement_ref": None}]
        entry["margin"].update(filled_units=0, possible_short_units=0, filled_floor="0", pending_hold="0")
        facts["fees"] = _fees(entry, now, ("entry_filled", "close_filled"), options=True)
        for fee in facts["fees"]:
            for component in fee["components"]:
                component["total_upper_bound"] = "0"
        source.publish("mounted-native", facts)
        _qualify(desk)


def test_normal_shutdown_retains_financial_duty_until_evidenced_settlement(mounted_desk: MountedDesk) -> None:
    """The same execution owner retains its lease; Stop is not settlement."""
    desk = mounted_desk
    source = _source(desk)
    _configure(desk)
    facts = _facts()
    _cash_filled(facts, mark="4")
    source.publish("mounted-native", facts)
    _qualify(desk)
    owner = desk.app.config["EXECUTION_SESSIONS"]
    try:
        assert owner.shutdown(timeout=0) is False
        assert owner.lease.is_locked and not owner.closed
        view = desk.client.get(RUN + "/autonomy-v2", headers=desk.headers).get_json()["data"]
        assert view["entry_state"] == "retired"
        assert view["duty"]["cumulative_entry_fill"] == 10
        assert view["duty"]["state"] == "handback_required"
        assert desk.calls == []
    finally:
        _settle_cash(desk, source, facts)
    assert owner.shutdown(timeout=0) is True
    assert _financial(desk)["floors"]["cash-entry"] == {"principal": "40", "fee": "2"}


def test_cash_paid_profile_refuses_unknown_payment_and_preserves_charge_history(mounted_desk: MountedDesk) -> None:
    """Incurrence is not payment; uncertainty blocks even after all units close."""
    desk = mounted_desk
    source = _source(desk)
    _configure(desk)
    facts = _facts()
    entry = _cash_filled(facts, mark="4")
    entry["lots"][0].update(exited_quantity=10, gross_exit_proceeds="40")
    for fee in facts["fees"]:
        fee["components"][0]["incurred"] = [{"charge_ref": _ref("paid:" + fee["phase"]), "amount": "1",
                                              "charged_at_ms": facts["observed_at_ms"], "payment": "payment_unknown",
                                              "payment_evidence_ref": None}]
    source.publish("mounted-native", facts)
    _qualify(desk)
    owner = desk.app.config["EXECUTION_SESSIONS"]
    try:
        assert _financial(desk)["assessment"]["status"] == "unavailable"
        assert owner.shutdown(timeout=0) is False
    finally:
        for fee in facts["fees"]:
            charge = fee["components"][0]["incurred"][0]
            charge.update(payment="paid", payment_evidence_ref=_ref("payment:" + fee["phase"]))
        source.publish("mounted-native", facts)
        _qualify(desk)
    assert _financial(desk)["assessment"]["capital"] == "42"
    assert _financial(desk)["assessment"]["exposure"] == "0"
    assert _financial(desk)["assessment"]["loss"] == "2"
    assert owner.shutdown(timeout=0) is True


@pytest.mark.parametrize("retirement", ["stop", "source"])
def test_held_financial_evaluation_revalidates_exact_owner_and_source(
    mounted_desk: MountedDesk, retirement: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An observed old primitive result cannot publish over Stop or replacement."""
    import threading

    desk = mounted_desk
    source = _source(desk)
    _configure(desk)
    facts = _facts()
    source.publish("mounted-native", facts)
    original = source.resolve
    entered, release = threading.Event(), threading.Event()
    result = {}
    held = False

    def observed(row: dict[str, Any], snapshot: Any) -> dict[str, Any]:
        nonlocal held
        value = original(row, snapshot)
        if not held:
            held = True
            entered.set()
            assert release.wait(10)
        return value

    def evaluate() -> None:
        with desk.app.test_client() as client:
            result["response"] = client.post(RUN + "/autonomy-v2/qualify", json={}, headers=desk.headers)

    monkeypatch.setattr(source, "resolve", observed)
    worker = threading.Thread(target=evaluate)
    try:
        worker.start()
        assert entered.wait(5)
        if retirement == "stop":
            generation = desk.client.get(RUN, headers=desk.headers).get_json()["data"]["generation"]
            response = desk.client.post(RUN + "/stop", json={"account": "dhan:Mounted", "environment": "live",
                                       "expected_generation": generation}, headers=desk.headers)
            assert response.status_code == 200
        else:
            facts["tariff_ref"]["revision"] = "d" * 64
            source.publish("mounted-native", facts)
        release.set()
        worker.join(5)
        assert not worker.is_alive()
        assert result["response"].status_code == 409
        assert _financial(desk)["assessment"] is None
        assert desk.calls == []
    finally:
        release.set()
        worker.join(10)
        assert not worker.is_alive()


def test_new_known_fills_survive_an_unavailable_tariff(mounted_desk: MountedDesk) -> None:
    """Arithmetic unavailability does not erase independently observed fills."""
    import copy

    desk = mounted_desk
    source = _source(desk)
    _configure(desk)
    facts = _facts()
    entry = _cash_filled(facts, mark="4")
    original = copy.deepcopy(facts)
    entry["lots"].append({"fill_ref": _ref("fill-two"), "quantity": 2, "unit_cost": "4",
                          "exited_quantity": 0, "gross_exit_proceeds": "0"})
    tariff = facts["tariff_ref"]
    facts["tariff_ref"] = None
    source.publish("mounted-native", facts)
    try:
        view = _qualify(desk)
        assert view["duty"]["cumulative_entry_fill"] == 12
        assert _financial(desk)["assessment"]["status"] == "unavailable"
        source.publish("mounted-native", original)
        view = _qualify(desk)
        assert view["duty"]["cumulative_entry_fill"] == 12
        assert _financial(desk)["assessment"]["status"] == "unavailable"
        assert desk.app.config["EXECUTION_SESSIONS"].shutdown(timeout=0) is False
    finally:
        facts["tariff_ref"] = tariff
        entry["lots"][0].update(exited_quantity=10, gross_exit_proceeds="40")
        entry["lots"][1].update(exited_quantity=2, gross_exit_proceeds="8")
        for fee in facts["fees"]:
            for component in fee["components"]:
                component["total_upper_bound"] = "0"
        source.publish("mounted-native", facts)
        _qualify(desk)
    assert desk.app.config["EXECUTION_SESSIONS"].shutdown(timeout=0) is True
    assert _financial(desk)["floors"]["cash-entry"]["principal"] == "48"


def _settle_cash(desk: MountedDesk, source: Any, facts: dict[str, Any]) -> None:
    """Issue labelled synthetic completed fills; never write a broker or store."""
    entry = _cash_filled(facts, mark="4")
    entry["lots"][0].update(exited_quantity=10, gross_exit_proceeds="40")
    for fee in facts["fees"]:
        for component in fee["components"]:
            component["total_upper_bound"] = "0"
    source.publish("mounted-native", facts)
    _qualify(desk)
