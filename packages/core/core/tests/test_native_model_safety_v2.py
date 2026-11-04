"""Finite native model budgets and custody through the normal factory."""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from packages.core.core.tests.test_native_financial_owner import RUN
from packages.core.core.tests.test_native_model_producer_v2 import model_desk, response
from packages.core.core.tests.test_native_producer_v2 import _granted, _plan
from packages.core.core.tests.test_native_workflow_v2 import MountedDesk
from packages.core.core.tests.test_native_workflow_v2 import mounted_desk as mounted_desk

pytestmark = pytest.mark.integration


def _option_plan(source: Any, registration: Any, *, mark: str) -> None:
    """Publish explicitly synthetic option primitives; never provider qualification."""
    from packages.core.core.tests.test_native_financial_owner import _facts, _fees, _ref

    facts = _facts()
    source.publish("mounted-native", facts)
    now = facts["observed_at_ms"]
    contract = {
        "contract_ref": _ref("contract"), "listing_ref": _ref("listing"), "token": "123",
        "underlying_ref": _ref("underlying"), "underlying": "NIFTY", "exchange": "NFO", "product": "NRML",
        "expiry_at_ms": now + 3600000, "right": "CE", "strike": "100", "units_per_lot": 1,
        "quantity_unit": "underlying_units", "currency": "INR",
    }
    entry = {
        "entry_ref": _ref("producer-entry"), "contract": contract, "current_contract": contract,
        "listing_observed_at_ms": now, "side": "long", "fills": [],
        "writes": [{"write_ref": _ref("option-write"), "contract_ref": contract["contract_ref"],
                    "purpose": "entry", "side": "buy", "original_quantity": 1, "remaining_quantity": 1,
                    "released_quantity": 0, "resolution_ref": None, "premium_upper_bound": "4"}],
        "mark": {"contract_ref": contract["contract_ref"], "underlying_ref": contract["underlying_ref"],
                 "source_ref": _ref("mark"), "underlying_price": "50", "underlying_at_ms": now,
                 "option_price": mark, "option_at_ms": now}, "margin": None,
    }
    source.publish_plan(
        "mounted-native", order=registration.order,
        market={"instrument_id": "SYNTH", "exchange": "NFO", "product": "NRML",
                "mark": mark, "observed_at_ms": now},
        entry=entry, fees=_fees(entry, now, ("entry_possible", "close_possible"), options=True),
    )


def _grant_model(desk: MountedDesk, registration: Any) -> dict[str, Any]:
    """Select the exact registered instrument through finite custody and grant."""
    from packages.core.core.tests.test_native_custody_owner import _preview, _selection
    from packages.core.core.tests.test_native_financial_owner import _qualify

    view = _qualify(desk)
    selection = _selection(view)
    order = registration.order
    selection["limits"].update(
        instruments=[{"instrument_id": order["symbol"], "exchange": order["exchange"], "product": order["product"]}],
        max_reads=128,
    )
    preview = _preview(desk, selection)
    accepted = desk.client.post(RUN + "/autonomy-v2/transfer-accept", json={
        "schema_version": "2", "preview_ref": preview["preview_ref"],
        "expected_duty_revision": preview["duty"]["duty_ref"]["revision"],
    }, headers=desk.headers)
    assert accepted.status_code == 200, accepted.get_json()
    granted = desk.client.post(RUN + "/autonomy-v2/grant", json=selection, headers=desk.headers)
    assert granted.status_code == 200, granted.get_json()
    return granted.get_json()["data"]


def _start(desk: MountedDesk, view: dict[str, Any]) -> Any:
    """Start the actually granted registered worker through its HTTP route."""
    started = desk.client.post(RUN + "/autonomy-v2/start", json={
        "schema_version": "2", "run_id": "mounted-native",
        "expected_binding_revision": view["scope"]["binding_revision"],
        "grant_ref": view["grant"]["grant_ref"],
    }, headers=desk.headers)
    assert started.status_code == 200, started.get_json()
    return desk.app.config["EXECUTION_SESSIONS"].owners["mounted-native"]


def _status(desk: MountedDesk) -> dict[str, Any]:
    """Read retained receipts through the authenticated producer facade."""
    token = desk.headers["Authorization"].removeprefix("Bearer ")
    with desk.app.app_context():
        return desk.app.config["EXECUTION_SESSIONS"].autonomy.v2.producer_status(token, "mounted-native")


@pytest.mark.parametrize("dimension", ["tokens", "cost"])
def test_prior_observed_overage_refuses_next_call_before_model_io(
    mounted_desk: MountedDesk, dimension: str,
) -> None:
    """A settled over-reservation debit must count before the next HTTP call.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
        dimension: Token or monetary usage bound exceeded by the preceding observed task.
    """
    desk = mounted_desk
    calls: list[httpx.Request] = []

    def send(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        payload = response(request).json()
        # Literal synthetic usage: 3000 tokens or 130 micros under the actual
        # admitted tariff (one micro/100 input tokens). Neither is a default.
        payload["usage"] = {"prompt_tokens": 3000 if dimension == "tokens" else 13000, "completion_tokens": 0}
        return httpx.Response(200, json=payload)

    source, registration = model_desk(
        desk, send, max_tokens=5000 if dimension == "tokens" else 100000,
        cost_cap="1" if dimension == "tokens" else "0.0002",
    )
    _plan(source, registration, mark="5")
    owner = _start(desk, _granted(desk))
    assert owner.completed.wait(5)
    assert owner.shutdown(0)
    retained = _status(desk)
    assert len(calls) == 1, "the second native call must be refused before external I/O"
    assert len(retained["model_calls"]) == 1
    first = retained["model_calls"][0]
    assert first["receipt"]["accounting"] == "settled"
    assert first["receipt"]["attempts"][0]["charged"][
        "input_tokens" if dimension == "tokens" else "currency_micros"
    ] == (3000 if dimension == "tokens" else 130)
    assert len(retained["decisions"]) == 1
    assert owner.snapshot()["failed"] is True
    assert desk.calls == []


@pytest.mark.parametrize("options", [False, True], ids=["cash", "options"])
@pytest.mark.parametrize("action", ["kill", "stop"])
def test_held_model_retirement_remains_inspectable(
    mounted_desk: MountedDesk, options: bool, action: str,
) -> None:
    """Both nominal DTOs expose stopping, never stopped, during held model I/O.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
        options: Whether the synthetic run uses the nominal options rather than cash profile.
        action: Existing Stop or retirement action exercised while the model call is held.
    """
    import threading

    from flinttrade_core.native_autonomy_contracts_v2 import OptionsRunViewV2, RunViewV2

    desk = mounted_desk
    entered, release = threading.Event(), threading.Event()
    calls: list[httpx.Request] = []

    def send(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        entered.set()
        assert release.wait(10)
        return response(request, decision="propose")

    source, registration = model_desk(desk, send, options=options)
    (_option_plan if options else _plan)(source, registration, mark="5")
    owner = _start(desk, _grant_model(desk, registration))
    try:
        assert entered.wait(5)
        assert owner.snapshot()["alive"]
        if action == "kill":
            desk.app.config["SAFETY"].l5_kill.activate("synthetic held native model")
        else:
            row = desk.client.get(RUN, headers=desk.headers).get_json()["data"]
            stopped = desk.client.post(RUN + "/stop", json={
                "account": row["account"], "environment": row["environment"],
                "expected_generation": row["generation"],
            }, headers=desk.headers)
            assert stopped.status_code == 200, stopped.get_json()
        readback = desk.client.get(RUN + "/autonomy-v2", headers=desk.headers)
        assert readback.status_code == 200, readback.get_json()
        view = (OptionsRunViewV2 if options else RunViewV2).model_validate(readback.get_json()["data"])
        assert view.entry_state == "retired" and view.producer_state == "stopping"
        assert view.effective_authority == "none"
        assert owner.stop.is_set() and owner.snapshot()["alive"] and not owner.completed.is_set()
        census = desk.client.get("/api/v1/execution-sessions", headers=desk.headers)
        assert census.status_code == 200, census.get_json()
        assert len(_status(desk)["model_calls"]) == 1
        assert len(calls) == 1 and desk.calls == []
    finally:
        release.set()
        assert owner.completed.wait(5)
    assert owner.shutdown(0)
    assert len(calls) == 1 and desk.calls == []


@pytest.mark.parametrize("boundary", ["duty", "drain", "restart-account"])
def test_unknown_model_cost_retains_native_custody_until_existing_owner_reconciles(
    mounted_desk: MountedDesk, boundary: str,
) -> None:
    """Unknown task receipts are monetary duties, not fictitious broker quantities.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
        boundary: Retirement or reconciliation boundary at which the unresolved model duty is inspected.
    """
    from uuid import uuid4

    from flinttrade_core.execution_sessions import ExecutionSessions
    from flinttrade_core.service_usage_contracts import UsageAmounts

    desk = mounted_desk
    calls: list[httpx.Request] = []

    def send(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadError("synthetic unknown model outcome", request=request)

    source, registration = model_desk(desk, send)
    _plan(source, registration, mark="5")
    granted = _granted(desk)
    before = granted["duty"]["obligation_revision"]
    owner = _start(desk, granted)
    assert owner.completed.wait(5) and owner.shutdown(0)
    retained = _status(desk)
    attempt = retained["model_calls"][0]["receipt"]["attempts"][0]
    assert attempt["state"] == "UNKNOWN" and len(calls) == 1
    registry = desk.app.config["EXECUTION_SESSIONS"]
    try:
        if boundary == "duty":
            result = desk.client.get(RUN + "/autonomy-v2", headers=desk.headers)
            assert result.status_code == 200, result.get_json()
            duty = result.get_json()["data"]["duty"]
            assert duty["obligation_revision"] != before, "a model call invalidates old empty-census acceptance"
            assert duty["receiving_acceptance_ref"] is None
            assert duty["obligations"] == [] and duty["possible_entry_quantity"] == 0
            assert duty["unknown_possible_writes"] is False
            model = duty["model_obligations"][0]
            assert model["request_ref"]["id"] == retained["model_calls"][0]["request_id"]
            assert model["attempts"][0]["attempt_id"] == attempt["attempt_id"]
            assert model["attempts"][0]["observed_cost_micros"] is None
        elif boundary == "drain":
            assert registry.shutdown(0) is False, "worker exit does not settle model costs"
        else:
            registry.close()
            registry = ExecutionSessions(desk.app, registry.path)
            desk.app.config["EXECUTION_SESSIONS"] = registry
            with pytest.raises(ValueError, match="custody"):
                with registry.native_account_fence():
                    pytest.fail("unknown model duty admitted an empty native census")
            request = desk.client.post("/api/v1/native/accounts/dhan/Mounted/login", json={
                "credentials": {"client_id": "Mounted", "access_token": "synthetic-successor"},
            }, headers={**desk.headers, "Idempotency-Key": str(uuid4())})
            assert request.status_code != 200, "restart must not erase unresolved model custody"
            assert len(desk.transport.authentication_calls) == 2
        assert desk.calls == []
    finally:
        # Explicit synthetic usage evidence resolves the actual existing ledger;
        # no record deletion or forced native release is permitted.
        dispatcher = desk.app.config["MODEL_RUN_SERVICES"].dispatcher()
        dispatcher.ledger.reconcile(
            attempt["attempt_id"], UsageAmounts(requests=1, input_tokens=12, output_tokens=5, currency_micros=1),
            evidence="synthetic-complete-provider-usage-receipt",
        )
        workflow = registry.autonomy.v2
        reconcile = getattr(workflow, "reconcile_model_calls", None)
        if reconcile is not None:
            with desk.app.app_context():
                reconcile(desk.headers["Authorization"][7:], "mounted-native")
    # Reconciliation removes only outstanding duties, never historical debit.
    final = _status(desk)
    assert len(final["model_calls"]) == 1
    assert final["model_calls"][0]["tokens_reserved"] == retained["model_calls"][0]["tokens_reserved"]
    assert registry.shutdown(0) is True
    view = desk.client.get(RUN + "/autonomy-v2", headers=desk.headers).get_json()["data"]
    assert view["duty"]["model_obligations"] == []
    assert view["duty"]["obligations"] == []
    assert len(calls) == 1 and desk.calls == []
