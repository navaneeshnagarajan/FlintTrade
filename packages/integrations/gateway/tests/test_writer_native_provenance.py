"""Historical writer facts through the real managed router and durable ledger.

All accounts, native transports and executions in this file are synthetic.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from flinttrade_core.models import Order
from flinttrade_engine.local_state_provider import OrderLifecycleLedger
from flinttrade_engine.safety import SafetyContext, SafetyGate, set_safety_gate_secret
from flinttrade_gateway.brokers.dhan import DhanAdapter
from flinttrade_gateway.router import BrokerRouter
from flinttrade_gateway.session_provider import AuthenticatingSessionProvider
from packages.integrations.gateway.tests.test_canonical_broker_observations import (
    SyntheticAdapter,
    bound as bound,
    richer_trade,
)

pytestmark = pytest.mark.unit


def test_actual_slice_ids_survive_without_claiming_complete_child_ack(
    bound: Any, writer_backend: Any, tmp_path: Path, monkeypatch: Any,
) -> None:
    """An observed native array stays uncertain, but its actual IDs are not lost."""
    from dhanhq import DhanContext, dhanhq
    from flinttrade_core.exceptions import BrokerError

    sdk = dhanhq(DhanContext("NativeCase", "synthetic"))
    adapter = DhanAdapter(client_factory=lambda _: sdk, security_resolver=lambda *_: "101")
    handle = bound(adapter, client=sdk)
    proof = writer_backend(handle)
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "slice.sqlite")
    router, context, _, _ = _writer(handle, adapter, ledger, proof)
    order = Order(symbol="SYNTHETIC", exchange="NSE", product="MIS", action="BUY", quantity="2", variety="iceberg")
    signed = SafetyContext.mint(order, mode="live", user_jti=context.jti, actor_type="human",
        adapter_id="dhan", account_id="AliasCase", backend_lease_proof=proof)
    calls = []
    def send(method: str, url: str, **kwargs: Any) -> Any:
        assert method == "POST" and url.endswith("/orders/slicing")
        calls.append(kwargs)
        return SimpleNamespace(status_code=200,
            content=b'[{"orderId":"ChildA","orderStatus":"PENDING"},{"orderId":"ChildB","orderStatus":"PENDING"}]')
    monkeypatch.setattr(sdk.dhan_http.session, "request", send)
    try:
        with pytest.raises(BrokerError, match="unverified after dispatch"):
            asyncio.run(_submit(router, context, order, signed))
        attempt = ledger.list_unresolved_outcomes()[0]["attempt_id"]
        evidence = OrderLifecycleLedger(ledger_path=tmp_path/"slice.sqlite").native_dispatch_evidence(attempt)
        assert len(calls) == 1
        assert evidence[-1]["kind"] == "uncertain_acknowledgement"
        assert evidence[-1]["observed_order_ids"] == ["ChildA", "ChildB"]
        assert evidence[-1]["full_set"] == "unverified"
        assert not any(row["kind"] == "acknowledged" for row in evidence)
    finally:
        assert router.revoke_and_drain(timeout=1)
        sdk.dhan_http.session.close()


@pytest.fixture
def writer_backend(
    backend_lease_factory: Callable[[], Any], monkeypatch: pytest.MonkeyPatch,
) -> Callable[[Any], Any]:
    """Acquire the real backend in the managed account's actual workspace.

    Args:
        backend_lease_factory: Existing fixture's genuine ownership issuer.
        monkeypatch: Scoped active-workspace selection, restored by that owner.

    Returns:
        A fixture-only adapter selecting the already-created synthetic workspace.
    """
    def acquire(handle: Any) -> Any:
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(handle.workspace_path))
        return backend_lease_factory()
    return acquire


def _provider(handle: Any) -> Any:
    from flinttrade_core.workspace_migrations import read_workspace_snapshot

    return AuthenticatingSessionProvider(handle.registry, {handle.selector.adapter_id: {"AliasCase": ["actor"]}},
        workspace_snapshot=read_workspace_snapshot(handle.workspace_path), workspace_path=handle.workspace_path,
        credential_version_for=lambda selector: handle.store.selector_state(selector).version)


def test_real_writer_persists_managed_native_facts_before_wire(
    bound: Callable[..., Any],
    writer_backend: Callable[[Any], Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ACK is attached to the original session; a native date stays unknown.

    Args:
        bound: Real managed registry and bound read-owner fixture.
        writer_backend: Real isolated backend lease owner.
        tmp_path: Disposable isolated storage root.
        monkeypatch: Scoped test-owned observers and synthetic faults.

    Raises:
        AssertionError: If the real writer, ledger or uncertainty boundary differs.
    """
    from dhanhq import DhanContext, dhanhq

    set_safety_gate_secret(b"synthetic-writer-signing-secret-32")
    sdk = dhanhq(DhanContext("NativeCase", "synthetic"))
    adapter = DhanAdapter(client_factory=lambda _: sdk, security_resolver=lambda *_: "101")
    handle = bound(adapter)
    provider = _provider(handle)
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "writer.sqlite")
    proof = writer_backend(handle)
    gate = SafetyGate()
    router = BrokerRouter({"dhan": adapter}, provider, consume_gate=gate.consume,
                          lifecycle_store=ledger, backend_lease_proof=proof)
    order = Order(symbol="SYNTHETIC", action="BUY", exchange="NSE", product="MIS", quantity="2")
    context = replace(handle.context[0], mode="live")
    captured, before = [], []

    def send(method: Any, url: Any, **kwargs: Any) -> Any:
        assert (method, url) == ("POST", "https://api.dhan.co/v2/orders")
        attempts = ledger.list_dispatch_attempts()
        before.extend(ledger.native_dispatch_evidence(attempts[0]["attempt_id"]))
        return SimpleNamespace(status_code=200, content=b'{"orderId":"OrderAa"}')

    monkeypatch.setattr(sdk.dhan_http.session, "request", send)
    try:
        router.preflight_order(order, adapter_id="dhan", account_id="AliasCase", request_ctx=context,
                               capture_target=captured.append)
        signed = SafetyContext.mint(order, mode="live", user_jti=context.jti, actor_type="human",
                                   adapter_id="dhan", account_id="AliasCase", backend_lease_proof=proof)
        assert asyncio.run(router.place_order(context, order=order, safety_ctx=signed,
            adapter_id="dhan", account_id="AliasCase", preflight_target=captured[0])) == "OrderAa"
        assert len(before) == 1 and before[0]["kind"] == "prepared"
        facts = before[0]["facts"]
        assert facts["provider_account_id"] == "NativeCase"
        assert facts["session_version"]["selector"] == {"adapter_id": "dhan", "account_id": "AliasCase"}
        assert facts["native_order_date"] is None
        assert facts["native_segment"] == "NSE_EQ"
        assert facts["resource_family"] == "ordinary"
        assert facts["intent"]["quantity"] == "2"
        assert facts["preparation"]["intent_json"] == captured[0].preparation.intent_json
        attempt = ledger.list_dispatch_attempts()[0]["attempt_id"]
        restarted = OrderLifecycleLedger(ledger_path=tmp_path / "writer.sqlite")
        evidence = restarted.native_dispatch_evidence(attempt)
        assert evidence[0] == before[0]
        assert evidence[1]["kind"] == "acknowledged" and evidence[1]["order_ids"] == ["OrderAa"]
    finally:
        assert router.revoke_and_drain(timeout=1)
        sdk.dhan_http.session.close()


@pytest.mark.parametrize("date", ["2026-10-22", "2026-10-23"])
def test_unwitnessed_attempt_cannot_own_native_fills(bound: Callable[..., Any], tmp_path: Path, date: str) -> None:
    """Legacy dates and current alias observations cannot establish native ownership.

    Args:
        bound: Real managed registry and bound read-owner fixture.
        tmp_path: Disposable isolated storage root.
        date: Independently supplied synthetic native date.

    Raises:
        AssertionError: If the real writer, ledger or uncertainty boundary differs.
    """
    handle = bound(SyntheticAdapter([richer_trade(trade_date=date)]))
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "legacy.sqlite")
    attempt = ledger.prepare_dispatch(adapter_id="dhan", account_id="AliasCase", operation="place_order",
        request_context=handle.context[0], payload=dict(symbol="SYNTHETIC-OPTION", exchange="NFO",
        product="NRML", action="BUY", quantity=2, price=12.5), observed_at=datetime(2026, 10, 23, tzinfo=UTC))
    ledger.mark_invoked(attempt)
    ledger.acknowledge(attempt, "OrderAa")
    snapshot = asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    assert snapshot.fills[0].owner_attempt_id is None
    assert "unallocated_fills" in snapshot.missing_evidence


class _SyntheticWriter(SyntheticAdapter):
    """Token-gated synthetic external outcome, never a provider qualification."""

    broker_id = "dhan"

    def __init__(self, result: Any = 'OrderAa') -> None:
        super().__init__([richer_trade()])
        self.result = result
        self.native_accounts = []
        self.barrier = None

    async def place_order(self, session: Any, order: Any, *, _router_token: Any = None) -> Any:
        from flinttrade_gateway.brokers._base import ROUTER_TOKEN

        assert _router_token is ROUTER_TOKEN
        self.native_accounts.append(session.account_id)
        if self.barrier is not None:
            await self.barrier()
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _writer(handle: Any, adapter: Any, ledger: Any, proof: Any) -> Any:
    set_safety_gate_secret(b"synthetic-writer-signing-secret-32")
    router = BrokerRouter({handle.selector.adapter_id: adapter}, _provider(handle),
        consume_gate=SafetyGate().consume, lifecycle_store=ledger, backend_lease_proof=proof)
    context = replace(handle.context[0], mode="live")
    order = Order(symbol="SYNTHETIC-OPTION", action="BUY", exchange="NFO", product="NRML",
                  quantity="2", price="12.5")
    signed = SafetyContext.mint(order, mode="live", user_jti=context.jti, actor_type="human",
        adapter_id=handle.selector.adapter_id, account_id="AliasCase", backend_lease_proof=proof)
    return router, context, order, signed


def _submit(router: Any, context: Any, order: Any, signed: Any) -> Any:
    return router.place_order(context, order=order, safety_ctx=signed,
                             adapter_id=signed.adapter_id, account_id="AliasCase")


def test_late_ack_keeps_original_native_session_after_rebind(
    bound: Callable[..., Any],
    tmp_path: Path,
    writer_backend: Callable[[Any], Any],
) -> None:
    """The replacement may complete first; late evidence never samples its owner.

    Args:
        bound: Real managed registry and bound read-owner fixture.
        tmp_path: Disposable isolated storage root.
        writer_backend: Real isolated backend lease owner.

    Raises:
        AssertionError: If the real writer, ledger or uncertainty boundary differs.
    """
    adapter = _SyntheticWriter()
    handle = bound(adapter)
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "late.sqlite")
    router, context, order, signed = _writer(handle, adapter, ledger, writer_backend(handle))

    async def run() -> None:
        started, release = asyncio.Event(), asyncio.Event()

        async def barrier() -> None:
            started.set()
            await release.wait()

        adapter.barrier = barrier
        task = asyncio.create_task(_submit(router, context, order, signed))
        await asyncio.wait_for(started.wait(), 1)
        try:
            attempt = ledger.list_dispatch_attempts()[0]["attempt_id"]
            before = ledger.native_dispatch_evidence(attempt)
            assert before[0]["facts"]["provider_account_id"] == "NativeCase"
            from flinttrade_gateway.brokers._base import Session
            from flinttrade_gateway.registry import ManagedSessionAuthority
            from flinttrade_core.workspace_migrations import broker_workspace_version, read_workspace_snapshot

            workspace = read_workspace_snapshot(handle.workspace_path)
            authority = ManagedSessionAuthority(handle.store.selector_state(handle.selector).version,
                workspace.version, broker_workspace_version(workspace))
            raw = Session("synthetic", 4102444800.0, "OtherNative", "dhan")
            candidate = handle.publisher.prepare_session_candidate(handle.selector, raw,
                expected_registry=handle.registry.snapshot_selector(handle.selector), authority=authority,
                broker="dhan", label="Replacement", client=object())
            handle.publisher.publish_prepared_candidate(candidate, current_authority=authority)
            release.set()
            assert await asyncio.wait_for(task, 1) == "OrderAa"
            facts = OrderLifecycleLedger(ledger_path=tmp_path / "late.sqlite").native_dispatch_evidence(attempt)
            assert facts[0] == before[0]
            assert facts[1]["order_ids"] == ["OrderAa"]
            assert adapter.native_accounts == ["NativeCase"]
            # First read after replacement cannot lend the old attempt to it.
            adapter.rows = [richer_trade(broker_account_id="OtherNative")]
            from flinttrade_core.broker_read_port import ExactReadTarget
            current_port = handle.owner.bind(target=ExactReadTarget(handle.selector),
                                             verify_current_authority=lambda: handle.context[0])
            snapshot = await ledger.refresh_observations(handle.owner, current_port)
            assert snapshot.fills[0].owner_attempt_id is None
        finally:
            release.set()
            await task
    try:
        asyncio.run(run())
    finally:
        assert router.revoke_and_drain(timeout=1)


def test_typed_multi_id_ack_survives_conservative_legacy_projection(
    bound: Callable[..., Any],
    tmp_path: Path,
    writer_backend: Callable[[Any], Any],
) -> None:
    """Record every per-call ID without treating the first child's quantity as all.

    Args:
        bound: Real managed registry and bound read-owner fixture.
        tmp_path: Disposable isolated storage root.
        writer_backend: Real isolated backend lease owner.

    Raises:
        AssertionError: If the real writer, ledger or uncertainty boundary differs.
    """
    from flinttrade_gateway.brokers.upstox import UpstoxPlacementAcknowledgement

    result = UpstoxPlacementAcknowledgement(["ChildA", "ChildB"], {"synthetic": True})
    adapter = _SyntheticWriter(result)
    handle = bound(adapter, broker="upstox")
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "multi.sqlite")
    router, context, order, signed = _writer(handle, adapter, ledger, writer_backend(handle))
    try:
        assert asyncio.run(_submit(router, context, order, signed)) is result
        attempt = ledger.list_dispatch_attempts()[0]
        assert attempt["dispatch_state"] == "OUTCOME_UNKNOWN"
        restarted = OrderLifecycleLedger(ledger_path=tmp_path / "multi.sqlite")
        facts = restarted.native_dispatch_evidence(attempt["attempt_id"])
        assert facts[1]["order_ids"] == ["ChildA", "ChildB"]
        assert ledger.list_unresolved_outcomes()[0]["attempt_id"] == attempt["attempt_id"]
    finally:
        assert router.revoke_and_drain(timeout=1)


def test_possible_write_restart_retains_unknown_date_and_original_facts(
    bound: Callable[..., Any],
    tmp_path: Path,
    writer_backend: Callable[[Any], Any],
) -> None:
    """A genuine post-invocation exception cannot manufacture a date or erase duty.

    Args:
        bound: Real managed registry and bound read-owner fixture.
        tmp_path: Disposable isolated storage root.
        writer_backend: Real isolated backend lease owner.

    Raises:
        AssertionError: If the real writer, ledger or uncertainty boundary differs.
    """
    adapter = _SyntheticWriter(RuntimeError("synthetic interrupted transport"))
    handle = bound(adapter)
    path = tmp_path / "crash.sqlite"
    ledger = OrderLifecycleLedger(ledger_path=path)
    router, context, order, signed = _writer(handle, adapter, ledger, writer_backend(handle))
    try:
        with pytest.raises(RuntimeError, match="interrupted transport"):
            asyncio.run(_submit(router, context, order, signed))
        restarted = OrderLifecycleLedger(ledger_path=path)
        attempt = restarted.list_unresolved_outcomes()[0]["attempt_id"]
        evidence = restarted.native_dispatch_evidence(attempt)
        assert len(evidence) == 1 and evidence[0]["facts"]["native_order_date"] is None
        assert evidence[0]["facts"]["provider_account_id"] == "NativeCase"
        assert adapter.native_accounts == ["NativeCase"]
    finally:
        assert router.revoke_and_drain(timeout=1)


def test_writer_manifest_and_attempt_rollback_together(
    bound: Callable[..., Any],
    tmp_path: Path,
    writer_backend: Callable[[Any], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupted prepare transaction cannot publish a witness or invoke.

    Args:
        bound: Real managed registry and bound read-owner fixture.
        tmp_path: Disposable isolated storage root.
        writer_backend: Real isolated backend lease owner.
        monkeypatch: Scoped test-owned observers and synthetic faults.

    Raises:
        AssertionError: If the real writer, ledger or uncertainty boundary differs.
    """
    adapter = _SyntheticWriter()
    handle = bound(adapter)
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "rollback.sqlite")
    router, context, order, signed = _writer(handle, adapter, ledger, writer_backend(handle))
    append = ledger._append_native_writer_manifest

    def fail(*args: Any) -> None:
        append(*args)
        raise RuntimeError("synthetic interruption after manifest insert")

    monkeypatch.setattr(ledger, "_append_native_writer_manifest", fail)
    try:
        from flinttrade_core.exceptions import SafetyBypassError
        with pytest.raises(SafetyBypassError, match="could not persist"):
            asyncio.run(_submit(router, context, order, signed))
        assert ledger.list_dispatch_attempts() == []
        assert ledger.latest_snapshot_generation(adapter_id="dhan", account_id="AliasCase") is None
        assert adapter.native_accounts == []
    finally:
        assert router.revoke_and_drain(timeout=1)


def test_constructed_writer_receipt_cannot_enter_existing_transaction(tmp_path: Path) -> None:
    """Exact DTO type and caller-chosen fields are not an active verified issuer.

    Args:
        tmp_path: Disposable isolated storage root.

    Raises:
        AssertionError: If the real writer, ledger or uncertainty boundary differs.
    """
    from flinttrade_gateway.writer_provenance import NativeWriterSource

    source = object.__new__(NativeWriterSource)
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "forged.sqlite")
    with pytest.raises(ValueError, match="active verified"):
        ledger.prepare_dispatch(adapter_id="dhan", account_id="AliasCase", operation="place_order",
                                request_context=object(), payload={}, native_source=source)
    assert ledger.list_dispatch_attempts() == []


@pytest.mark.parametrize("native_account,date", [("OtherNative", "2026-10-23"), ("NativeCase", "2026-10-22")])
def test_unscoped_cumulative_rows_cannot_spend_native_fills(
    bound: Callable[..., Any],
    tmp_path: Path,
    native_account: str,
    date: str,
) -> None:
    """Unknown order scope keeps its whole remainder, regardless of scalar IDs.

    Args:
        bound: Real managed registry and bound read-owner fixture.
        tmp_path: Disposable isolated storage root.
        native_account: Exact case-sensitive synthetic provider account.
        date: Independently supplied synthetic native date.

    Raises:
        AssertionError: If the real writer, ledger or uncertainty boundary differs.
    """
    handle = bound(SyntheticAdapter([richer_trade(broker_account_id=native_account, trade_date=date)]),
                   native_account=native_account)
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "cumulative.sqlite")
    ledger.record_broker_snapshot(adapter_id="dhan", account_id="AliasCase", orders=[dict(
        orderid="OrderAa", symbol="SYNTHETIC-OPTION", exchange="NFO", product="NRML", action="BUY",
        status="PARTIALLY_FILLED", quantity="2", filled_quantity="1", price="12.5")],
        positions=[], holdings=[], observed_at=datetime.now(UTC))
    snapshot = asyncio.run(ledger.refresh_observations(handle.owner, handle.port))
    assert snapshot.order_fills[0].unique_quantity == "0"
    assert snapshot.order_fills[0].unexplained_quantity == "1.0"


@pytest.mark.parametrize("alteration", ["empty", "missing-schema", "changed-schema"])
def test_native_writer_manifest_discriminator_is_integrity_checked(
    bound: Callable[..., Any], tmp_path: Path, writer_backend: Callable[[Any], Any], alteration: str,
) -> None:
    """A lost discriminator cannot silently erase already-retained writer facts.

    Args:
        bound: Real managed registry and read owner with synthetic native transport.
        tmp_path: Disposable isolated storage.
        writer_backend: Real isolated backend lease.
        alteration: Synthetic durable manifest corruption.

    Raises:
        AssertionError: If corruption is mistaken for a legacy absence of facts.
    """
    import json
    import sqlite3
    from flinttrade_engine.local_state_provider import LifecycleStateError

    adapter = _SyntheticWriter()
    handle = bound(adapter)
    path = tmp_path / "integrity.sqlite"
    ledger = OrderLifecycleLedger(ledger_path=path)
    router, context, order, signed = _writer(handle, adapter, ledger, writer_backend(handle))
    try:
        asyncio.run(_submit(router, context, order, signed))
        attempt = ledger.list_dispatch_attempts()[0]["attempt_id"]
        assert len(ledger.native_dispatch_evidence(attempt)) == 2
        with sqlite3.connect(path) as connection:
            raw = connection.execute(
                "SELECT evidence_json FROM snapshot_generation_manifests WHERE generation=1"
            ).fetchone()[0]
            payload = json.loads(raw)
            if alteration == "missing-schema":
                payload.pop("schema")
            elif alteration == "changed-schema":
                payload["schema"] = "old"
            corrupted = "" if alteration == "empty" else json.dumps(payload, sort_keys=True, separators=(",", ":"))
            connection.execute("UPDATE snapshot_generation_manifests SET evidence_json=? WHERE generation=1",
                               (corrupted,))
        with pytest.raises(LifecycleStateError, match="integrity"):
            OrderLifecycleLedger(ledger_path=path).native_dispatch_evidence(attempt)
    finally:
        assert router.revoke_and_drain(timeout=1)



def test_writer_refuses_a_backend_from_another_workspace(
    bound: Callable[..., Any], tmp_path: Path, backend_lease_factory: Callable[[], Any],
) -> None:
    """A genuine lease in another workspace is not native writer correspondence.

    Args:
        bound: Real managed account/session issuer in a disposable workspace.
        tmp_path: Isolated test storage root.
        backend_lease_factory: Genuine owner of a deliberately different workspace.

    Raises:
        AssertionError: If native facts or a write borrow an unrelated backend.
    """
    from flinttrade_core.exceptions import SafetyBypassError

    adapter = _SyntheticWriter()
    handle = bound(adapter)
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "wrong-backend.sqlite")
    router, context, order, signed = _writer(handle, adapter, ledger, backend_lease_factory())
    try:
        with pytest.raises(SafetyBypassError, match="workspace"):
            asyncio.run(_submit(router, context, order, signed))
        assert ledger.list_dispatch_attempts() == []
        assert adapter.native_accounts == []
    finally:
        assert router.revoke_and_drain(timeout=1)



def test_captured_managed_session_cannot_bypass_another_actor_acl(
    bound: Callable[..., Any], tmp_path: Path, writer_backend: Callable[[Any], Any],
) -> None:
    """An observation pin cannot turn another actor's valid signature into an ACL.

    Args:
        bound: Real managed registry and session provider.
        tmp_path: Disposable isolated storage.
        writer_backend: Actual backend ownership of this synthetic account workspace.

    Raises:
        AssertionError: If a foreign actor can consume the captured session.
    """
    from flinttrade_core.exceptions import SafetyBypassError

    class Adapter(_SyntheticWriter):
        def preflight_order(self, order: Any) -> None:
            return None

    adapter = Adapter()
    handle = bound(adapter)
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "actor.sqlite")
    router, context, order, signed = _writer(handle, adapter, ledger, writer_backend(handle))
    captured = []
    try:
        router.preflight_order(order, adapter_id="dhan", account_id="AliasCase", request_ctx=context,
                               capture_target=captured.append)
        foreign = replace(context, actor_id="foreign-actor")
        with pytest.raises(SafetyBypassError):
            asyncio.run(router.place_order(foreign, order=order, safety_ctx=signed,
                adapter_id="dhan", account_id="AliasCase", preflight_target=captured[0]))
        assert adapter.native_accounts == []
        assert ledger.list_dispatch_attempts() == []
        assert asyncio.run(router.place_order(context, order=order, safety_ctx=signed,
            adapter_id="dhan", account_id="AliasCase", preflight_target=captured[0])) == "OrderAa"
        assert adapter.native_accounts == ["NativeCase"]
    finally:
        assert router.revoke_and_drain(timeout=1)
