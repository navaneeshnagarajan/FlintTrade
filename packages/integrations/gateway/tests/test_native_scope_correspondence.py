"""Historical native correspondence through real owners and inert primitives.

All resources/accounts here are synthetic. Native order and execution dates are
independently supplied, not inferred from clocks, aliases or ACK arrival.
"""
from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from flinttrade_core.broker_read_port import ExactReadTarget
from flinttrade_engine.local_state_provider import OrderLifecycleLedger
from flinttrade_gateway.broker_read_service import create_broker_read_owner
from flinttrade_gateway.native_scope_primitives import SyntheticNativeScopeSource
from packages.integrations.gateway.tests.test_canonical_broker_observations import (
    SyntheticAdapter, bound as bound, richer_trade,
)
from packages.integrations.gateway.tests.test_writer_native_provenance import (
    _provider, _submit, _writer, writer_backend as writer_backend,
)

pytestmark = pytest.mark.unit


def resource(*, date: str = "2026-10-22", order_id: str = "OrderAa") -> dict:
    """Independent synthetic order resource, not a clock-derived attribution."""
    return {"native_account": "NativeCase", "native_order_date": date, "segment": "NSE_FNO",
            "native_order_date_basis": "synthetic-independent-identity-day-v1",
            "family": "ordinary", "resource_id": order_id, "leg": "1", "order_id": order_id,
            "exchange_order_id": "ExchangeAa", "filled_quantity": "0", "executions": []}


class ScopedTransport(SyntheticAdapter):
    """Inert external provider with independent order resources and fills."""

    broker_id: ClassVar[str] = "dhan"

    def __init__(self) -> None:
        super().__init__([richer_trade()])
        self.resources = [resource()]
        self.native_records: list[dict] = []
        self.primitive_source: Any = None
        self.transport = object()
        self.result: Any = "OrderAa"

    async def place_order(self, session: Any, order: Any, *, _router_token: Any = None) -> Any:
        """Record synthetic native provenance at the actual routed placement seam.

        Args:
            session: Broker session supplied by the real adapter call.
            order: Canonical order whose native provenance is captured at placement.
            _router_token: Existing router identity token required by the synthetic writer.

        Returns:
            The configured acknowledgement with its original scalar or typed receipt shape.

        Raises:
            AssertionError: The call does not carry the existing router token.
        """
        from flinttrade_gateway.brokers._base import ROUTER_TOKEN
        from flinttrade_gateway.router import placement_acknowledgement_fields

        assert _router_token is ROUTER_TOKEN
        fields = placement_acknowledgement_fields(self.result)
        ids = fields["order_ids"] if fields else [self.result]
        record = self.primitive_source.observe_transport(
            transport=self.transport, native_account=session.account_id, order=order,
            order_ids=list(ids), resources=self.resources,
        )
        self.native_records.append(record)
        return self.result

    async def native_scope_read(self, session: Any) -> list[dict]:
        """Read detached synthetic native provenance for the supplied session.

        Args:
            session: Broker session supplied by the real adapter call.

        Returns:
            Deep-copied native scope records captured by the inert writer.
        """
        self.calls.append(("native_scope", session.account_id))
        return copy.deepcopy(self.native_records)


@pytest.fixture
def scoped(bound: Any, writer_backend: Any, tmp_path: Path) -> Any:
    """Yield actual read/writer/ledger owners with one server-owned inert source."""
    acquired = []

    def build(adapter: Any = None) -> Any:
        adapter = adapter or ScopedTransport()
        handle = bound(adapter)
        primitive = SyntheticNativeScopeSource(
            adapter=adapter, transport=adapter.transport, reader=adapter.native_scope_read,
            workspace_path=handle.workspace_path, label="independent-native-resource-fixture-v1",
        )
        adapter.primitive_source = primitive
        owner = create_broker_read_owner(
            registry=handle.registry, session_provider=_provider(handle), adapters={"dhan": adapter},
            workspace_path=handle.workspace_path, runtime_accepting_requests=lambda: True,
            native_scope_source=primitive,
        )
        port = owner.bind(target=ExactReadTarget(handle.selector), verify_current_authority=lambda: handle.context[0])
        ledger = OrderLifecycleLedger(ledger_path=tmp_path / f"native-{len(acquired)}.sqlite")
        router, context, order, signed = _writer(handle, adapter, ledger, writer_backend(handle))
        from flinttrade_engine.safety import SafetyContext

        order = order.model_copy(update={"quantity": "10"})
        signed = SafetyContext.mint(order, mode="live", user_jti=context.jti, actor_type="human",
            adapter_id="dhan", account_id="AliasCase", backend_lease_proof=router.backend_lease_proof)
        acquired.append((router, owner))
        return SimpleNamespace(adapter=adapter, handle=handle, owner=owner, port=port, ledger=ledger,
                               router=router, context=context, order=order, signed=signed)

    yield build
    for router, owner in acquired:
        assert router.revoke_and_drain(timeout=1)
        assert owner.close(timeout=1)


def submit(desk: Any) -> str:
    """Dispatch through real signature consumption and captured writer ownership."""
    asyncio.run(_submit(desk.router, desk.context, desk.order, desk.signed))
    return desk.ledger.list_dispatch_attempts()[0]["attempt_id"]


def expose_execution(desk: Any, *, cumulative: str = "3") -> None:
    """Update the inert provider's independently observed execution resource."""
    row = desk.adapter.native_records[0]["resources"][0]
    row["filled_quantity"] = cumulative
    row["executions"] = [{"fill_id": "FillAa", "execution_date": "2026-10-23", "fill_leg": "1"}]


def test_historical_order_date_and_next_day_execution_allocate_and_restart(scoped: Any) -> None:
    """An older order may execute later without lending a recycled scalar ID."""
    desk = scoped()
    attempt = submit(desk)
    expose_execution(desk)
    observed = asyncio.run(desk.ledger.refresh_observations(desk.owner, desk.port))
    assert observed.fills[0].owner_attempt_id == attempt
    assert observed.fills[0].trade.trade_date == "2026-10-23"
    evidence = desk.ledger.native_dispatch_evidence(attempt)
    assert evidence[0]["facts"]["native_order_date"] is None
    assert evidence[1]["native_scope_observation"]["resources"][0]["native_order_date"] == "2026-10-22"
    assert evidence[1]["order_ids"] == ["OrderAa"]
    assert observed.order_fills[0].unique_quantity == "1"
    assert observed.order_fills[0].cumulative_high_water == "3"
    assert observed.order_fills[0].unexplained_quantity == "2"
    reopened = OrderLifecycleLedger(ledger_path=desk.ledger._path()).observation_snapshot(desk.handle.selector)
    assert reopened.fills == observed.fills
    assert reopened.order_fills == observed.order_fills
    assert not observed.admission_available


@pytest.mark.parametrize("field,value", [
    ("native_order_date", "2026-10-21"), ("segment", "BSE_FNO"),
    ("family", "super"), ("resource_id", "OtherResource"), ("leg", "2"),
    ("exchange_order_id", "OtherExchange"),
])
def test_read_cannot_relabel_the_writer_resource(scoped: Any, field: str, value: str) -> None:
    """A matching scalar ACK cannot overwrite the independently witnessed address."""
    desk = scoped()
    submit(desk)
    expose_execution(desk)
    desk.adapter.native_records[0]["resources"][0][field] = value
    observed = asyncio.run(desk.ledger.refresh_observations(desk.owner, desk.port))
    assert observed.fills[0].owner_attempt_id is None
    assert observed.conflicts
    assert not observed.admission_available


@pytest.mark.parametrize("field,value", [
    ("fill_id", "OtherFill"), ("execution_date", "2026-10-22"), ("fill_leg", "2"),
])
def test_execution_address_is_not_an_order_id_join(scoped: Any, field: str, value: str) -> None:
    """A day/leg/fill mismatch remains unallocated even beside a genuine issuer."""
    desk = scoped()
    submit(desk)
    expose_execution(desk)
    desk.adapter.native_records[0]["resources"][0]["executions"][0][field] = value
    observed = asyncio.run(desk.ledger.refresh_observations(desk.owner, desk.port))
    assert observed.fills[0].owner_attempt_id is None
    assert observed.order_fills[0].unique_quantity == "0"
    assert observed.order_fills[0].unexplained_quantity == "3"


@pytest.mark.parametrize("field,value", [("transport", object()), ("source_id", "foreign-source")])
def test_primitive_source_substitution_remains_unavailable(scoped: Any, field: str, value: Any) -> None:
    """Substituting a configured dependency never turns a report into proof."""
    desk = scoped()
    submit(desk)
    expose_execution(desk)
    setattr(desk.adapter.primitive_source, field, value)
    observed = asyncio.run(desk.ledger.refresh_observations(desk.owner, desk.port))
    assert observed.fills[0].owner_attempt_id is None
    assert not observed.admission_available


def test_cumulative_scope_and_fill_high_water_survive_missing_and_lower_reads(scoped: Any) -> None:
    """Missing pages and contradictory lower quantities cannot release liabilities."""
    desk = scoped()
    attempt = submit(desk)
    expose_execution(desk, cumulative="3")
    first = asyncio.run(desk.ledger.refresh_observations(desk.owner, desk.port))
    desk.adapter.rows = []
    desk.adapter.native_records[0]["resources"][0]["filled_quantity"] = "0"
    later = asyncio.run(desk.ledger.refresh_observations(desk.owner, desk.port))
    assert later.fills[0].owner_attempt_id == attempt
    assert later.fills == first.fills
    assert later.order_fills[0].cumulative_high_water == "3"
    assert later.order_fills[0].unexplained_quantity == "2"
    assert "native_scope_cumulative_regression" in later.conflicts


@pytest.mark.parametrize("quantity", ["broken", "NaN", "Infinity", "-1", "1.5"])
def test_invalid_cumulative_is_unavailable_without_erasing_proven_history(scoped: Any, quantity: str) -> None:
    """Malformed new primitive amounts must not crash capture or erase old known amounts."""
    import json
    from flinttrade_core.broker_read_port import BrokerObservationSnapshot

    desk = scoped()
    submit(desk)
    expose_execution(desk, cumulative="3")
    first = asyncio.run(desk.ledger.refresh_observations(desk.owner, desk.port))
    desk.adapter.native_records[0]["resources"][0]["filled_quantity"] = quantity
    captured = asyncio.run(desk.owner.capture_observations(desk.port))
    assert type(captured) is BrokerObservationSnapshot
    assert json.loads(captured.native_scope_json)["availability"] == "provider_failure"
    later = asyncio.run(desk.ledger.refresh_observations(desk.owner, desk.port))
    assert later.fills == first.fills
    assert later.order_fills[0].cumulative_high_water == "3"
    assert later.order_fills[0].unexplained_quantity == "2"
    assert not later.admission_available


def test_source_cannot_issue_a_constructed_proof_outside_invocation(scoped: Any) -> None:
    """The actual server issuer requires the verified writer's active attempt."""
    desk = scoped()
    with pytest.raises(ValueError, match="verified transport"):
        desk.adapter.primitive_source.observe_transport(transport=desk.adapter.transport,
            native_account="NativeCase", order=desk.order, order_ids=["OrderAa"], resources=desk.adapter.resources)
    assert desk.ledger.list_dispatch_attempts() == []


def test_reused_order_id_keeps_independent_order_days_and_cumulative_scopes(scoped: Any) -> None:
    """Two genuine attempts may share a scalar ID without borrowing executions."""
    from flinttrade_engine.safety import SafetyContext

    desk = scoped()
    submit(desk)
    expose_execution(desk, cumulative="2")
    desk.adapter.resources = [resource(date="2026-10-23")]
    desk.adapter.resources[0]["exchange_order_id"] = "ExchangeBb"
    desk.signed = SafetyContext.mint(desk.order, mode="live", user_jti=desk.context.jti, actor_type="human",
        adapter_id="dhan", account_id="AliasCase", backend_lease_proof=desk.router.backend_lease_proof)
    submit(desk)
    desk.adapter.native_records[1]["resources"][0].update(filled_quantity="3", executions=[
        {"fill_id": "FillBb", "execution_date": "2026-10-24", "fill_leg": "1"}])
    desk.adapter.rows = [richer_trade(), richer_trade(fill_id="FillBb", trade_date="2026-10-24",
        exchange_order_id="ExchangeBb", broker_fields={})]
    observed = asyncio.run(desk.ledger.refresh_observations(desk.owner, desk.port))
    assert len(observed.fills) == 2
    assert len({fill.owner_attempt_id for fill in observed.fills}) == 2
    assert all(fill.owner_attempt_id is not None for fill in observed.fills)
    assert [(row.unique_quantity, row.cumulative_high_water, row.unexplained_quantity)
            for row in observed.order_fills] == [("1", "2", "1"), ("1", "3", "2")]
    assert {row.native_order_scope[3] for row in observed.order_fills} == {"2026-10-22", "2026-10-23"}
    assert not observed.admission_available


@pytest.mark.parametrize("field,value", [("native_order_date", None), ("native_order_date_basis", None),
                                         ("native_account", ""), ("leg", "")])
def test_missing_independent_scope_cannot_be_issued(scoped: Any, field: str, value: Any) -> None:
    """Missing date semantics/account/leg cannot be manufactured by the issuer."""
    desk = scoped()
    desk.adapter.resources[0][field] = value
    with pytest.raises(ValueError):
        submit(desk)
    attempt = desk.ledger.list_unresolved_outcomes()[0]["attempt_id"]
    assert [row["kind"] for row in desk.ledger.native_dispatch_evidence(attempt)] == ["prepared"]


def test_creation_time_is_not_an_independent_order_identity_day(scoped: Any) -> None:
    """A plausible independent timestamp label does not establish ID-day semantics."""
    desk = scoped()
    desk.adapter.resources[0]["native_order_date_basis"] = "creationTimestamp"
    with pytest.raises(ValueError, match="independent native identity-day basis"):
        submit(desk)
    attempt = desk.ledger.list_unresolved_outcomes()[0]["attempt_id"]
    assert [row["kind"] for row in desk.ledger.native_dispatch_evidence(attempt)] == ["prepared"]


def test_resource_leg_cumulative_rows_do_not_spend_each_others_fills(scoped: Any) -> None:
    """Two independently observed legs sharing an order ID retain separate totals."""
    desk = scoped()
    other = resource()
    other.update(leg="2", exchange_order_id="ExchangeBb")
    desk.adapter.resources.append(other)
    submit(desk)
    expose_execution(desk, cumulative="2")
    second = desk.adapter.native_records[0]["resources"][1]
    second.update(filled_quantity="3", executions=[
        {"fill_id": "FillBb", "execution_date": "2026-10-23", "fill_leg": "2"}])
    desk.adapter.rows = [richer_trade(), richer_trade(fill_id="FillBb", fill_leg="2",
                                                    exchange_order_id="ExchangeBb", broker_fields={})]
    observed = asyncio.run(desk.ledger.refresh_observations(desk.owner, desk.port))
    assert len(observed.fills) == 2
    assert {(row.native_order_scope[7], row.unique_quantity, row.unexplained_quantity)
            for row in observed.order_fills} == {("1", "1", "1"), ("2", "1", "2")}
    assert not observed.admission_available


def test_ambiguous_attempts_do_not_erase_a_larger_native_cumulative(scoped: Any) -> None:
    """Ownership ambiguity is not permission to lower a known resource floor."""
    from flinttrade_engine.safety import SafetyContext

    desk = scoped()
    submit(desk)
    expose_execution(desk, cumulative="2")
    desk.signed = SafetyContext.mint(desk.order, mode="live", user_jti=desk.context.jti, actor_type="human",
        adapter_id="dhan", account_id="AliasCase", backend_lease_proof=desk.router.backend_lease_proof)
    submit(desk)
    desk.adapter.native_records[1]["resources"][0]["filled_quantity"] = "5"
    observed = asyncio.run(desk.ledger.refresh_observations(desk.owner, desk.port))
    assert observed.fills[0].owner_attempt_id is None
    assert "native_scope_multiple_attempts" in observed.conflicts
    native_rows = [row for row in observed.order_fills if row.native_order_scope is not None]
    assert len(native_rows) == 1
    assert native_rows[0].cumulative_high_water == native_rows[0].unexplained_quantity == "5"
    assert native_rows[0].owner_attempt_id is None


def test_account_rebind_retains_proven_history_without_lending_it_to_successor(scoped: Any) -> None:
    """The genuine old owner remains knowable; a new alias binding cannot borrow it."""
    import time
    from flinttrade_core.workspace_migrations import broker_workspace_version, read_workspace_snapshot
    from flinttrade_gateway.brokers._base import Session
    from flinttrade_gateway.registry import ManagedSessionAuthority

    desk = scoped()
    attempt = submit(desk)
    expose_execution(desk)
    first = asyncio.run(desk.ledger.refresh_observations(desk.owner, desk.port))
    handle = desk.handle
    workspace = read_workspace_snapshot(handle.workspace_path)
    authority = ManagedSessionAuthority(handle.store.selector_state(handle.selector).version,
        workspace.version, broker_workspace_version(workspace))
    candidate = handle.publisher.prepare_session_candidate(handle.selector,
        Session("successor", time.time()+3600, "OtherNative", "dhan"),
        expected_registry=handle.registry.snapshot_selector(handle.selector), authority=authority,
        broker="dhan", label="Synthetic successor", client=object())
    handle.publisher.publish_prepared_candidate(candidate, current_authority=authority)
    port = desk.owner.bind(target=ExactReadTarget(handle.selector), verify_current_authority=lambda: handle.context[0])
    desk.adapter.rows = [richer_trade(broker_account_id="OtherNative", broker_fields={})]
    observed = asyncio.run(desk.ledger.refresh_observations(desk.owner, port))
    by_account = {fill.namespace[1]: fill for fill in observed.fills}
    assert by_account["NativeCase"] == first.fills[0]
    assert by_account["NativeCase"].owner_attempt_id == attempt
    assert by_account["OtherNative"].owner_attempt_id is None
    assert "provider_account_rebound" in observed.conflicts
    assert not observed.admission_available


def test_first_capture_after_rebind_cannot_borrow_a_genuine_old_writer(scoped: Any) -> None:
    """No earlier account capture is needed to refuse a successor's scalar-ID join."""
    import time
    from flinttrade_core.workspace_migrations import broker_workspace_version, read_workspace_snapshot
    from flinttrade_gateway.brokers._base import Session
    from flinttrade_gateway.registry import ManagedSessionAuthority

    desk = scoped()
    attempt = submit(desk)
    original = desk.ledger.native_dispatch_evidence(attempt)
    assert [row["kind"] for row in original] == ["prepared", "acknowledged"]
    expose_execution(desk)
    handle = desk.handle
    workspace = read_workspace_snapshot(handle.workspace_path)
    authority = ManagedSessionAuthority(handle.store.selector_state(handle.selector).version,
        workspace.version, broker_workspace_version(workspace))
    candidate = handle.publisher.prepare_session_candidate(handle.selector,
        Session("successor", time.time()+3600, "OtherNative", "dhan"),
        expected_registry=handle.registry.snapshot_selector(handle.selector), authority=authority,
        broker="dhan", label="Synthetic successor", client=object())
    handle.publisher.publish_prepared_candidate(candidate, current_authority=authority)
    port = desk.owner.bind(target=ExactReadTarget(handle.selector), verify_current_authority=lambda: handle.context[0])
    desk.adapter.rows = [richer_trade(broker_account_id="OtherNative", broker_fields={})]
    observed = asyncio.run(desk.ledger.refresh_observations(desk.owner, port))
    assert len(observed.fills) == 1 and observed.fills[0].namespace[1] == "OtherNative"
    assert observed.fills[0].owner_attempt_id is None and observed.fills[0].native_order_scope is None
    assert desk.ledger.native_dispatch_evidence(attempt) == original
    assert not observed.admission_available
