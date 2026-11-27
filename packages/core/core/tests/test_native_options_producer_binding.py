"""Normal-factory option-plan binding; synthetic listings are not provider qualification."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from packages.core.core.tests.native_writer_fixture import mounted_desk as mounted_desk
from packages.core.core.tests.test_exact_contract_http_preflight import _resolver
from packages.core.core.tests.test_native_custody_owner import _preview, _selection
from packages.core.core.tests.test_native_financial_owner import (
    BASE, RUN, _facts, _fees, _financial, _qualify, _ref, _source,
)
from packages.core.core.tests.test_native_model_safety_v2 import _start
from packages.core.core.tests.test_native_workflow_v2 import MountedDesk

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("fault", ["none", "premium", "token", "listing"])
def test_option_producer_binds_allocation_to_retained_listing_and_limit(
    mounted_desk: MountedDesk, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    """A valid preparation passes binding; cheaper or foreign allocations refuse.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
        monkeypatch: Scoped replacements restored after this test.
        fault: Native allocation or listing mismatch introduced beside the unchanged positive.
    """
    from flinttrade_core.native_autonomy import NativeDispatchAuthority, _digest
    from flinttrade_core.native_producer_v2 import ProducerRegistration

    desk = mounted_desk
    source = _source(desk)
    resolver, symbol = _resolver("dhan", "NFO")
    adapter = desk.app.config["ACTIVE_BROKER_ADAPTERS"]["dhan"]
    adapter.install_security_resolver(resolver)
    native = resolver.contract(symbol, "NFO")
    order = {"symbol": symbol, "exchange": "NFO", "product": "NRML", "action": "BUY",
             "quantity": "3", "price": "4", "pricetype": "LIMIT", "admission_note": "Reviewed option plan"}
    registration = ProducerRegistration.threshold_entry(name="option-plan", order=order, threshold="4",
                                                         interval_ms=25, max_decisions=1)
    workflow = desk.app.config["EXECUTION_SESSIONS"].autonomy.v2
    pin = workflow.register_producer(registration)
    corpus = json.loads((Path(__file__).parent / "fixtures/native-options-v2.json").read_text())
    config = next(c["value"] for c in corpus["cases"] if c["id"] == "options-ConfigureRequestV2-positive")
    config["config"].update(run_id="mounted-native", account_id="Mounted", broker="dhan", producer=pin)
    config["config"]["risk"]["max_mark_age_ms"] = 60000
    created = desk.client.post(BASE + "/native-v2", json=config, headers=desk.headers)
    assert created.status_code == 201, created.get_json()
    facts = _facts()
    source.publish("mounted-native", facts)
    now = facts["observed_at_ms"]
    contract = {"contract_ref": _ref("option-contract"),
                "listing_ref": {"id": "native-listing", "revision": _digest(native)},
                "token": native["security_id"], "underlying_ref": _ref("index"), "underlying": "NIFTY",
                "exchange": "NFO", "product": "NRML",
                "expiry_at_ms": int(datetime(2099, 6, 23, tzinfo=ZoneInfo("Asia/Kolkata")).timestamp() * 1000),
                "right": "CE", "strike": "22250", "units_per_lot": 3,
                "quantity_unit": "underlying_units", "currency": "INR"}
    if fault == "token":
        contract["token"] = "another-contract"
    if fault == "listing":
        contract["listing_ref"] = _ref("different-listing")
    entry = {"entry_ref": _ref("option-entry"), "contract": contract, "current_contract": contract,
             "listing_observed_at_ms": now, "side": "long", "fills": [],
             "writes": [{"write_ref": _ref("option-write"), "contract_ref": contract["contract_ref"],
                         "purpose": "entry", "side": "buy", "original_quantity": 3, "remaining_quantity": 3,
                         "released_quantity": 0, "resolution_ref": None,
                         "premium_upper_bound": "1" if fault == "premium" else "4"}],
             "mark": {"contract_ref": contract["contract_ref"], "underlying_ref": contract["underlying_ref"],
                      "source_ref": _ref("mark"), "underlying_price": "10", "underlying_at_ms": now,
                      "option_price": "4", "option_at_ms": now}, "margin": None}
    source.publish_plan("mounted-native", order=registration.order,
                        market={"instrument_id": symbol, "exchange": "NFO", "product": "NRML",
                                "mark": "4", "observed_at_ms": now}, entry=entry,
                        fees=_fees(entry, now, ("entry_possible", "close_possible"), options=True))
    selection = _selection(_qualify(desk))
    selection["limits"].update(instruments=[{"instrument_id": symbol, "exchange": "NFO", "product": "NRML"}],
                                max_order_quantity=3, max_total_quantity=3, max_commands=1, max_reads=128)
    preview = _preview(desk, selection)
    accepted = desk.client.post(RUN + "/autonomy-v2/transfer-accept", headers=desk.headers, json={
        "schema_version": "2", "preview_ref": preview["preview_ref"],
        "expected_duty_revision": preview["duty"]["duty_ref"]["revision"],
    })
    assert accepted.status_code == 200, accepted.get_json()
    granted = desk.client.post(RUN + "/autonomy-v2/grant", headers=desk.headers, json=selection)
    assert granted.status_code == 200, granted.get_json()
    phases: list[str] = []
    original = NativeDispatchAuthority.capture_laya

    def before_laya(ticket: NativeDispatchAuthority) -> None:
        phases.append("allocation-bound-before-laya")
        original(ticket)

    monkeypatch.setattr(NativeDispatchAuthority, "capture_laya", before_laya)
    owner = _start(desk, granted.get_json()["data"])
    assert owner.completed.wait(5) and owner.shutdown(0)
    assert phases == (["allocation-bound-before-laya"] if fault == "none" else [])
    assert desk.calls == []
    financial = _financial(desk)
    assert all(hold["state"] == "released" for hold in financial["reservations"].values())
