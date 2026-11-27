"""Exact Dhan invocation controls with synthetic listings and the pinned SDK.

These tests establish local request correspondence, not provider eligibility,
standalone margin, fills or financial authority.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import datetime
from decimal import Decimal, DefaultContext, ROUND_DOWN, localcontext
from pathlib import Path
from typing import Any

import pytest

from flinttrade_core.models import Order
from flinttrade_core.exceptions import BrokerError
from flinttrade_gateway.brokers import dhan_mapping as M
from flinttrade_gateway.brokers._base import ROUTER_TOKEN
from packages.integrations.gateway.tests.brokers import test_dhan_options_prerequisites as D

pytestmark = pytest.mark.unit


def listed_order(**changes: Any) -> Order:
    """Return an exact synthetic option proposal, never a current listing."""
    return Order(**(dict(symbol="SYNTH-JAN2099-101-CE", exchange="NFO", action="BUY",
                        product="NRML", quantity="6", pricetype="LIMIT", price="7.25") | changes))


def install(adapter: Any, clock: list[float], **rule_changes: Any) -> None:
    """Publish an explicitly dated synthetic master and independent tick rule."""
    adapter.install_security_resolver(D.versioned_resolver(
        clock=lambda: clock[0], tick_rules={("contract-A", "NFO"): D.tick_rule(**rule_changes)},
    ))


async def invoke(adapter: Any, operation: str, order: Order) -> Any:
    """Exercise the existing placement or margin resource, without a fake SDK."""
    if operation == "margin":
        return await adapter.margin_calculator(D.session(), order)
    if operation == "multi":
        return await adapter.margin_calculator_multi(
            D.session(), [order], include_position=False, include_order=False,
        )
    if operation == "modify":
        return await adapter.modify_order(D.session(), "synthetic-order", order.model_dump(),
                                          _router_token=ROUTER_TOKEN)
    return await adapter.place_order(D.session(), order, _router_token=ROUTER_TOKEN)


@pytest.mark.parametrize("operation", ["regular", "amo", "iceberg", "margin", "multi", "modify"])
@pytest.mark.parametrize("change", ["none", "replace", "expire", "rule"])
async def test_queued_resource_binds_exact_contract_and_rule(
    monkeypatch: pytest.MonkeyPatch, operation: str, change: str,
) -> None:
    """Revalidate after the real SDK lock, retaining ordinary single-send controls."""
    response = {"orderId": "synthetic-ack"}
    if operation == "margin":
        response = {"totalMargin": "1"}
    if operation == "multi":
        response = {"total_margin": "1"}
    adapter, calls = D.sdk_adapter(monkeypatch, response)
    clock = [150.0]
    install(adapter, clock)
    entered = asyncio.Event()
    original = adapter.preflight_order

    def observed(*args: Any, **kwargs: Any) -> dict:
        result = original(*args, **kwargs)
        entered.set()
        return result

    monkeypatch.setattr(adapter, "preflight_order", observed)
    order = listed_order(variety=operation if operation in {"amo", "iceberg"} else "regular")
    adapter._sdk_transport_lock.acquire()
    task = asyncio.create_task(invoke(adapter, operation, order))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert calls == []
        if change == "replace":
            install(adapter, clock)  # Same values, different publication identity.
        elif change == "expire":
            clock[0] = 200.0
        elif change == "rule":
            install(adapter, clock, source_revision="synthetic-new-rule")
    finally:
        adapter._sdk_transport_lock.release()
    try:
        if change == "none":
            await asyncio.wait_for(task, 3)
            assert len(calls) == 1
        else:
            with pytest.raises(M.DhanMappingError):
                await asyncio.wait_for(task, 3)
            assert calls == []
    finally:
        if not task.done():
            await task


async def test_publication_cannot_overtake_final_check_or_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A busy publication refuses promptly; it cannot retarget an admitted call."""
    adapter, calls = D.sdk_adapter(monkeypatch, {"orderId": "synthetic-ack"})
    clock = [150.0]
    install(adapter, clock)
    entered, release = threading.Event(), threading.Event()
    original = adapter.resolve_contract

    def observed(*args: Any, **kwargs: Any) -> dict:
        result = original(*args, **kwargs)
        if threading.current_thread() is not threading.main_thread():
            entered.set()
            assert release.wait(3)
        return result

    monkeypatch.setattr(adapter, "resolve_contract", observed)
    task = asyncio.create_task(invoke(adapter, "regular", listed_order()))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        assert calls == []
        with pytest.raises(M.DhanMappingError, match="publication|invocation"):
            install(adapter, clock, source_revision="new-rule")
    finally:
        release.set()
        await asyncio.wait_for(task, 3)
    assert len(calls) == 1
    install(adapter, clock, source_revision="new-rule")


async def test_refresh_refuses_during_actual_resource_invocation_without_locking_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep publication fenced through real SDK work without holding its lock."""
    adapter, calls = D.sdk_adapter(monkeypatch, {"orderId": "synthetic-ack"})
    clock = [150.0]
    install(adapter, clock)
    client = adapter._client(D.session())
    actual = client.place_order
    entered, release = threading.Event(), threading.Event()

    def held(**kwargs: Any) -> Any:
        entered.set()
        assert release.wait(3)
        return actual(**kwargs)

    monkeypatch.setattr(client, "place_order", held)
    task = asyncio.create_task(invoke(adapter, "regular", listed_order()))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        assert calls == []
        acquired = adapter._contract_lock.acquire(blocking=False)
        assert acquired, "Publication critical section must not span SDK I/O"
        if acquired:
            adapter._contract_lock.release()
        with pytest.raises(M.DhanMappingError, match="invocation"):
            install(adapter, clock, source_revision="new-rule")
    finally:
        release.set()
        await asyncio.wait_for(task, 3)
    assert len(calls) == 1
    install(adapter, clock, source_revision="new-rule")


async def test_queued_order_keeps_captured_economic_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutable caller state cannot alter the already prepared signed request."""
    adapter, calls = D.sdk_adapter(monkeypatch, {"orderId": "synthetic-ack"})
    install(adapter, [150.0])
    entered = asyncio.Event()
    original = adapter.preflight_order

    def observed(*args: Any, **kwargs: Any) -> dict:
        result = original(*args, **kwargs)
        entered.set()
        return result

    monkeypatch.setattr(adapter, "preflight_order", observed)
    order = listed_order()
    adapter._sdk_transport_lock.acquire()
    task = asyncio.create_task(invoke(adapter, "regular", order))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        order.price = "8.00"
        order.quantity = "9"
    finally:
        adapter._sdk_transport_lock.release()
    await asyncio.wait_for(task, 3)
    body = json.loads(calls[0][2]["data"])
    assert len(calls) == 1 and body["price"] == 7.25 and body["quantity"] == 6


@pytest.mark.parametrize("observed", ["02/01/2099 10:00", "03/01/2099 10:00",
                                     "01/01/2099 10:00", "01/01/2000 10:00"])
async def test_sealed_liveness_observation_keeps_registry_custody(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, observed: str,
) -> None:
    """Continuity never writes sealed expiry; shortening is an exact owner signal."""
    from flinttrade_gateway.native_login import prepare_native_session
    from packages.integrations.gateway.tests.test_native_login import RegistryFixture

    profile = {"dhanClientId": "synthetic-account", "tokenValidity": "02/01/2099 10:00"}
    adapter, client, calls = D.auth_adapter(monkeypatch, profile)
    candidate = await prepare_native_session(
        adapter, {"client_id": "synthetic-account", "access_token": "synthetic-token"},
        verify=True, strict_probe=True, mutation_admission=lambda: None,
    )
    registry = RegistryFixture(tmp_path / "owned-registry")
    try:
        registry.publish("dhan", "Case", candidate.session)
        handle = registry.session("dhan", "Case")
        previous = handle.expires_at
        prior_profile = dict(handle.extra["provider_profile"])
        profile["tokenValidity"] = observed
        observed_expiry = adapter._provider_expiry(observed, profile=True)
        assert await adapter.liveness(handle) == min(observed_expiry, previous)
        assert handle.expires_at == previous
        assert handle.extra["provider_profile"] == prior_profile
        assert handle.extra["client"] is client and len(calls) == 2
    finally:
        registry.close()
        adapter.dispose_session(candidate.session)


@pytest.mark.parametrize("patch", [
    {"quantity": "4"}, {"pricetype": "SL-M", "price": "0", "trigger_price": "7.25"},
    {"price": "bad"}, {"price": None}, {"trigger_price": None}, {"exchange": None},
    {"product": None}, {"symbol": None}, {"order_type": "MARKET"}, {"securityId": "other"},
])
async def test_contextful_replacement_refuses_invalid_supplied_terms(
    monkeypatch: pytest.MonkeyPatch, patch: dict[str, Any],
) -> None:
    """Supplied malformed, conflicting or unqualified context cannot reach PUT."""
    adapter, calls = D.sdk_adapter(monkeypatch, {"orderId": "synthetic-order"})
    install(adapter, [150.0])
    changes = listed_order().model_dump(mode="json") | patch
    with pytest.raises((M.DhanMappingError, BrokerError)):
        await adapter.modify_order(D.session(), "synthetic-order", changes, _router_token=ROUTER_TOKEN)
    assert calls == []


async def test_versioned_replacement_requires_explicit_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Versioned native modification cannot qualify a contextless opaque ID."""
    adapter, calls = D.sdk_adapter(monkeypatch, {"orderId": "synthetic-order"})
    install(adapter, [150.0])
    with pytest.raises(M.DhanMappingError, match="context"):
        await adapter.modify_order(D.session(), "synthetic-order", {"quantity": "6", "price": "7.25"},
                                   _router_token=ROUTER_TOKEN)
    assert calls == []


async def test_legacy_unrelated_replacement_retains_omission_semantics(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unqualified legacy cash callers keep omitted trigger/validity defaults."""
    adapter, calls = D.sdk_adapter(monkeypatch, {"orderId": "synthetic-order"})
    await adapter.modify_order(D.session(), "synthetic-order", {"quantity": "6", "price": "7.25"},
                               _router_token=ROUTER_TOKEN)
    body = json.loads(calls[0][2]["data"])
    assert len(calls) == 1 and body["price"] == 7.25 and body["triggerPrice"] == 0
    assert body["validity"] == "DAY" and body["orderType"] == "LIMIT"


@pytest.mark.parametrize("operation", ["regular", "modify"])
@pytest.mark.parametrize("effective", [False, True])
@pytest.mark.parametrize("side,trigger,price,allowed", [
    ("BUY", "50", "60", True), ("BUY", "50", "60.05", False),
    ("SELL", "100", "80", True), ("SELL", "100", "79.95", False),
])
async def test_dated_bse_distance_reaches_placement_and_replacement(
    monkeypatch: pytest.MonkeyPatch, operation: str, effective: bool,
    side: str, trigger: str, price: str, allowed: bool,
) -> None:
    """The sourced effective date and exact one-tick boundaries govern both writes."""
    class Clock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return datetime(2026, 2, 9 if effective else 8, 12, tzinfo=tz)

    monkeypatch.setattr(M, "datetime", Clock)
    adapter, calls = D.sdk_adapter(monkeypatch, {"orderId": "synthetic-order"})
    adapter.install_security_resolver(D.versioned_resolver(
        [D.master_row(EXCH_ID="BSE")], tick_rules={("contract-A", "BFO"): D.tick_rule(tick_size="0.05")},
    ))
    order = listed_order(exchange="BFO", action=side, pricetype="SL", price=price, trigger_price=trigger)
    if allowed or not effective:
        await invoke(adapter, operation, order)
        assert len(calls) == 1
    else:
        with pytest.raises(M.DhanMappingError):
            await invoke(adapter, operation, order)
        assert calls == []


@pytest.mark.parametrize("operation", ["regular", "amo", "iceberg", "modify", "margin", "multi",
                                       "forever", "super"])
@pytest.mark.parametrize("trigger", [False, True])
@pytest.mark.parametrize("value", ["7.25", "9007199254740993.25"])
async def test_actual_money_is_exact_or_refused_before_native_invocation(
    monkeypatch: pytest.MonkeyPatch, operation: str, trigger: bool, value: str,
) -> None:
    """Validate actual pinned JSON, including active replacement-leg prices."""
    response = {"orderId": "synthetic-order"}
    if operation == "margin":
        response = {"totalMargin": "1"}
    if operation == "multi":
        response = {"total_margin": "1"}
    adapter, calls = D.sdk_adapter(monkeypatch, response)
    install(adapter, [150.0])
    order = listed_order(price=value, trigger_price=value if trigger else "0",
                         pricetype="SL" if trigger else "LIMIT",
                         variety=operation if operation in {"amo", "iceberg"} else "regular")
    saved = DefaultContext.copy()
    try:
        DefaultContext.prec = 2
        DefaultContext.rounding = ROUND_DOWN
        DefaultContext.Emax = 2
        DefaultContext.Emin = -2
        for signal in DefaultContext.traps:
            DefaultContext.traps[signal] = True
        with localcontext(DefaultContext):
            field = "triggerPrice" if trigger else "price"
            try:
                if operation == "forever":
                    await adapter.modify_forever(D.session(), "synthetic-order", {
                        "order_flag": "SINGLE", "leg_name": "TARGET_LEG", "pricetype": "LIMIT",
                        "quantity": "6", "price": value, "trigger_price": value,
                        "disclosed_quantity": "0", "validity": "DAY",
                    }, _router_token=ROUTER_TOKEN)
                elif operation == "super":
                    field = "stopLossPrice" if trigger else "targetPrice"
                    changes = ({"leg_name": "STOP_LOSS_LEG", "stop_loss_price": value, "trailing_jump": "0"}
                               if trigger else {"leg_name": "TARGET_LEG", "target_price": value})
                    await adapter.modify_super_order(D.session(), "synthetic-order", changes,
                                                       _router_token=ROUTER_TOKEN)
                else:
                    await invoke(adapter, operation, order)
            except M.DhanMappingError:
                assert value != "7.25" and calls == []
                return
            assert len(calls) == 1
            body = json.loads(calls[0][2]["data"], parse_float=Decimal)
            if operation == "multi":
                body = body["scripList"][0]
            assert Decimal(str(body[field])) == Decimal(value)
    finally:
        for name in ("prec", "rounding", "Emin", "Emax", "capitals", "clamp"):
            setattr(DefaultContext, name, getattr(saved, name))
        DefaultContext.traps = saved.traps.copy()
        DefaultContext.clear_flags()


@pytest.mark.parametrize("alias", ["foreign", None, "", " ", 7])
def test_versioned_security_aliases_refuse_before_indexing(alias: Any) -> None:
    """A second supplied ID cannot disappear behind compact-first selection."""
    with pytest.raises(M.DhanMappingError):
        D.versioned_resolver([D.master_row(SEM_SMST_SECURITY_ID="contract-A", SECURITY_ID=alias)])


@pytest.mark.parametrize("schema", ["compact", "detailed", "equal"])
def test_versioned_security_aliases_keep_schemas_and_venue_namespaces(schema: str) -> None:
    """Single/equal schemas retain distinct venues even when native IDs match."""
    row = D.master_row()
    if schema in {"compact", "equal"}:
        row["SEM_SMST_SECURITY_ID"] = row["SECURITY_ID"]
    if schema == "compact":
        del row["SECURITY_ID"]
    resolver = D.versioned_resolver([row, row | {"EXCH_ID": "BSE"}])
    for exchange in ("NFO", "BFO"):
        result = resolver.contract(row["TRADING_SYMBOL"], exchange)
        assert result["security_id"] == "contract-A" and result["exchange"] == exchange


@pytest.mark.parametrize("native", [
    {"totalMargin": "10", "currency": 2},
    {"total_margin": "10", "totalMargin": "10", "currency": 2},
    {"total_margin": "10", "totalMargin": "11"},
])
def test_multi_margin_contract_versions_are_not_silent_aliases(native: dict[str, Any]) -> None:
    """Conflicting documented schemas require provider resolution, not aliasing."""
    from flinttrade_core.broker_read_port import BrokerReadResponseInvalid

    with pytest.raises(BrokerReadResponseInvalid):
        M.from_dhan_multi_margin(native)


@pytest.mark.parametrize("currency", [2, "INR"])
def test_multi_margin_ambiguous_currency_is_raw_not_a_currency_code(currency: Any) -> None:
    """Preserve incompatible currency observations without inventing a unit."""
    native = {"total_margin": "10", "currency": currency}
    result = M.from_dhan_multi_margin(native)
    assert result["broker_fields"] == native and "currency" not in result
    assert result["provider_contract"] == "unverified_snake_case_observation"
    assert result["observation_kind"] == "estimate" and "paid_fees" not in result


@pytest.mark.parametrize("trigger", [None, "None"])
async def test_legacy_cash_margin_inactive_trigger_absence_stays_compatible(
    monkeypatch: pytest.MonkeyPatch, trigger: Any,
) -> None:
    """Retain absent inactive triggers from the existing cash snapshot consumer.

    The shared safety reader stringifies absent native trigger observations.
    This is not an active stop replacement or derivative-qualified proposal.
    """
    adapter, calls = D.sdk_adapter(monkeypatch, {"totalMargin": "100"})
    result = await adapter.margin_calculator(D.session(), D.request(trigger_price=trigger))
    assert result["required_margin"] == "100"
    body = json.loads(calls[0][2]["data"])
    assert len(calls) == 1 and body["triggerPrice"] == 0 and body["price"] == 7.25


@pytest.mark.parametrize("trigger", [None, "None"])
async def test_legacy_cash_margin_active_trigger_absence_is_not_compatibility(
    monkeypatch: pytest.MonkeyPatch, trigger: Any,
) -> None:
    """An active SL trigger still requires exact supplied numeric intent."""
    adapter, calls = D.sdk_adapter(monkeypatch, {"totalMargin": "100"})
    with pytest.raises(M.DhanMappingError):
        await adapter.margin_calculator(D.session(), D.request(pricetype="SL", trigger_price=trigger))
    assert calls == []


@pytest.mark.parametrize("variety", ["regular", "amo", "iceberg"])
async def test_native_preparation_captures_one_exact_evidence_and_wire_pair(
    monkeypatch: pytest.MonkeyPatch, variety: str,
) -> None:
    """A typed preparation carries one captured snapshot, not a later lookup."""
    adapter, calls = D.sdk_adapter(monkeypatch, {"orderId": "synthetic-ack"})
    install(adapter, [150.0])
    observed = []
    original = adapter.resolve_contract

    def resolve(*args: Any, **kwargs: Any) -> dict:
        value = original(*args, **kwargs)
        observed.append(value)
        return value

    monkeypatch.setattr(adapter, "resolve_contract", resolve)
    order = listed_order(variety=variety)
    prepared = adapter.prepare_order(order)
    assert type(prepared).__name__ == "DhanOrderPreparation"
    assert len(observed) == 1 and calls == []
    assert prepared.contract_evidence() == observed[0]
    assert prepared.sdk_kwargs()["security_id"] == observed[0]["security_id"]
    detached = prepared.contract_evidence()
    detached["tick_rule"]["source_revision"] = "not-captured"
    prepared.sdk_kwargs()["quantity"] = 99
    assert prepared.contract_evidence() == observed[0] and prepared.sdk_kwargs()["quantity"] == 6
    result = await adapter.place_order(D.session(), order, preparation=prepared, _router_token=ROUTER_TOKEN)
    assert result == "synthetic-ack" and len(calls) == 1 and len(observed) == 2
    assert json.loads(calls[0][2]["data"])["quantity"] == 6


@pytest.mark.parametrize("change", ["order", "resolver", "adapter", "wire", "no-router"])
async def test_native_preparation_is_not_retargeting_or_write_authority(
    monkeypatch: pytest.MonkeyPatch, change: str,
) -> None:
    """Captured evidence cannot authorise altered intent, owners or publication."""
    from dataclasses import replace

    adapter, calls = D.sdk_adapter(monkeypatch, {"orderId": "synthetic-ack"})
    install(adapter, [150.0])
    order = listed_order()
    prepared = adapter.prepare_order(order)
    token = ROUTER_TOKEN
    if change == "order":
        order.price = "8.00"
    elif change == "resolver":
        install(adapter, [150.0], source_revision="changed-rule")
    elif change == "adapter":
        adapter, calls = D.sdk_adapter(monkeypatch, {"orderId": "synthetic-ack"})
        install(adapter, [150.0])
    elif change == "wire":
        prepared = replace(prepared, wire_json=json.dumps(prepared.sdk_kwargs() | {"quantity": 99}))
    else:
        token = None
    with pytest.raises((M.DhanMappingError, BrokerError)):
        await adapter.place_order(D.session(), order, preparation=prepared, _router_token=token)
    assert calls == []


@pytest.mark.parametrize("observed,owner_mode", [
    ("02/01/2099 10:00", "missing"), ("03/01/2099 10:00", "missing"),
    ("01/01/2099 10:00", "missing"), ("01/01/2000 10:00", "missing"),
    ("01/01/2099 10:00", "exact"), ("01/01/2000 10:00", "exact"),
    ("01/01/2099 10:00", "foreign"), ("03/01/2099 10:00", "exact"),
])
async def test_real_sealed_profile_uses_only_public_registry_expiry_owner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, observed: str, owner_mode: str,
) -> None:
    """The real profile observation needs the existing owner's exact witness."""
    from flinttrade_core.account_mutation_contracts import RegistrySessionUnavailable
    from flinttrade_core.broker_identity import BrokerSelector
    from flinttrade_gateway.native_login import (
        SESSION_INVALID_RELOGIN_MESSAGE, prepare_native_session, verify_native_session,
    )
    from flinttrade_gateway.registry import ManagedLookupAuthority
    from packages.integrations.gateway.tests.test_native_login import RegistryFixture

    profile = {"dhanClientId": "synthetic-account", "tokenValidity": "02/01/2099 10:00"}
    adapter, client, calls = D.auth_adapter(monkeypatch, profile)
    candidate = await prepare_native_session(
        adapter, {"client_id": "synthetic-account", "access_token": "synthetic-token"},
        verify=True, strict_probe=True, mutation_admission=lambda: None,
    )
    exact = RegistryFixture(tmp_path / "owned-registry")
    selector = BrokerSelector("dhan", "Case")
    try:
        exact.publish("dhan", "Case", candidate.session)
        handle = exact.session("dhan", "Case")
        before = exact.registry.snapshot_exact_state(selector)
        binding = handle.version
        authority = ManagedLookupAuthority(binding.credential_version, binding.broker_workspace_version)
        profile["tokenValidity"] = observed
        observed_expiry = adapter._provider_expiry(observed, profile=True)
        owner = exact.owner if owner_mode == "exact" else object() if owner_mode == "foreign" else None
        result = await verify_native_session(
            adapter, handle, registry_publication_owner=owner, current_authority=authority,
        )
        should_apply = owner_mode == "exact" or (owner_mode == "missing" and observed_expiry >= before.expires_at)
        if not should_apply:
            assert result == SESSION_INVALID_RELOGIN_MESSAGE
            assert exact.registry.snapshot_exact_state(selector) == before
        else:
            assert result is None
            after = exact.registry.snapshot_exact_state(selector)
            assert after.expires_at == min(observed_expiry, before.expires_at)
            assert after.binding.credential_version == binding.credential_version
            if observed_expiry < before.expires_at:
                assert after.registry_version.generation == before.registry_version.generation + 1
                with pytest.raises(RegistrySessionUnavailable):
                    exact.owner.shorten_session_expiry(handle, observed_expiry, current_authority=authority)
            else:
                assert after == before
            if observed_expiry < time.time():
                assert after.status == "expired"
                with pytest.raises(RegistrySessionUnavailable):
                    exact.session("dhan", "Case")
        with pytest.raises(AttributeError):
            handle.expires_at = before.expires_at + 1
        assert handle.extra["client"] is client and len(calls) == 2
    finally:
        exact.close()
        adapter.dispose_session(candidate.session)


@pytest.mark.parametrize("operation", ["preparation", "regular", "amo", "iceberg", "margin", "multi", "modify"])
@pytest.mark.parametrize("field,value", [
    ("symbol", "OTHER-CONTRACT"), ("source_revision", ""), ("source_revision", None),
    ("source_revision", False), ("source_revision", 7), ("source_revision", "  "),
])
async def test_returned_contract_keeps_literal_symbol_and_source_proof(
    monkeypatch: pytest.MonkeyPatch, operation: str, field: str, value: Any,
) -> None:
    """An address cannot replace missing provenance or a different literal symbol."""
    response = {"totalMargin": "1"} if operation == "margin" else (
        {"total_margin": "1"} if operation == "multi" else {"orderId": "synthetic-ack"}
    )
    adapter, calls = D.sdk_adapter(monkeypatch, response)
    install(adapter, [150.0])
    original = adapter.resolve_contract

    def changed(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return original(*args, **kwargs) | {field: value}

    monkeypatch.setattr(adapter, "resolve_contract", changed)
    order = listed_order(variety=operation if operation in {"amo", "iceberg"} else "regular")
    with pytest.raises(M.DhanMappingError):
        if operation == "preparation":
            adapter.prepare_order(order)
        else:
            await invoke(adapter, operation, order)
    assert calls == []


@pytest.mark.parametrize("variety", ["amo", "iceberg"])
@pytest.mark.parametrize("capture", [False, True], ids=["legacy", "explicit-preparation"])
async def test_family_payload_uses_captured_intent_not_later_caller_mutation(
    monkeypatch: pytest.MonkeyPatch, variety: str, capture: bool,
) -> None:
    """A later family projection cannot reread mutable caller economics."""
    adapter, calls = D.sdk_adapter(monkeypatch, {"orderId": "synthetic-ack"})
    install(adapter, [150.0])
    order = listed_order(variety=variety)
    prepared = adapter.prepare_order(order) if capture else None
    name = "to_amo_order_payload" if variety == "amo" else "to_slice_order_kwargs"
    build = getattr(M, name)

    def mutate_caller(*args: Any, **kwargs: Any) -> dict[str, Any]:
        order.price, order.quantity = "8.00", "9"
        return build(*args, **kwargs)

    monkeypatch.setattr(M, name, mutate_caller)
    result = await adapter.place_order(D.session(), order, preparation=prepared, _router_token=ROUTER_TOKEN)
    assert result == "synthetic-ack" and len(calls) == 1
    assert order.price == "8.00" and order.quantity == "9"
    wire = json.loads(calls[0][2]["data"])
    assert wire["price"] == 7.25 and wire["quantity"] == 6


@pytest.mark.parametrize("operation", ["margin", "modify"])
async def test_margin_and_replacement_freeze_the_caller_economics(
    monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    """Related resource projections cannot adopt a mutable caller replacement."""
    response = {"totalMargin": "1"} if operation == "margin" else {"orderId": "synthetic-ack"}
    adapter, calls = D.sdk_adapter(monkeypatch, response)
    install(adapter, [150.0])
    order = listed_order()
    changes = order.model_dump(mode="json")
    if operation == "margin":
        build = M.to_margin_kwargs

        def mutate_margin(*args: Any, **kwargs: Any) -> dict[str, Any]:
            order.price, order.quantity = "8.00", "9"
            return build(*args, **kwargs)

        monkeypatch.setattr(M, "to_margin_kwargs", mutate_margin)
        await adapter.margin_calculator(D.session(), order)
        assert order.price == "8.00" and order.quantity == "9"
    else:
        preflight = adapter.preflight_order

        def mutate_replacement(*args: Any, **kwargs: Any) -> dict[str, Any]:
            result = preflight(*args, **kwargs)
            changes["price"], changes["quantity"] = "8.00", "9"
            return result

        monkeypatch.setattr(adapter, "preflight_order", mutate_replacement)
        await adapter.modify_order(D.session(), "synthetic-order", changes, _router_token=ROUTER_TOKEN)
        assert changes["price"] == "8.00" and changes["quantity"] == "9"
    assert len(calls) == 1
    wire = json.loads(calls[0][2]["data"])
    assert wire["price"] == 7.25 and wire["quantity"] == 6
