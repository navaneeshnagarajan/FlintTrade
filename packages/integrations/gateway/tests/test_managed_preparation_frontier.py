"""Managed writer freshness at the actual installed SDK lock frontier."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import threading
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from flinttrade_core.models import Order
from flinttrade_core.workspace_migrations import broker_workspace_version, read_workspace_snapshot
from flinttrade_engine.local_state_provider import OrderLifecycleLedger
from flinttrade_engine.safety import SafetyContext, SafetyGate, set_safety_gate_secret
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.dhan import DhanAdapter
from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession, _sdk_class
from flinttrade_gateway.native_scope_primitives import SyntheticNativeScopeSource
from flinttrade_gateway.registry import ManagedSessionAuthority
from flinttrade_gateway.router import BrokerRouter
from packages.core.core.tests.test_exact_contract_http_preflight import _resolver
from packages.integrations.gateway.tests.test_canonical_broker_observations import bound as bound
from packages.integrations.gateway.tests.test_writer_native_provenance import (
    _provider,
    writer_backend as writer_backend,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("broker", ["dhan", "kotakneo"])
@pytest.mark.parametrize("rebind", [False, True])
def test_managed_preparation_checks_original_owner_after_final_lock(
    bound: Any, writer_backend: Any, tmp_path: Any, monkeypatch: Any, broker: str, rebind: bool,
) -> None:
    """Actual SDK invocation must see the same account captured before queueing."""
    resolver, symbol = _resolver(broker, "NFO")
    calls = []
    if broker == "dhan":
        from dhanhq import DhanContext, dhanhq
        client = dhanhq(DhanContext("NativeCase", "synthetic"))

        def send(method: str, url: str, **kwargs: Any) -> Any:
            assert (method, url) == ("POST", "https://api.dhan.co/v2/orders")
            calls.append(kwargs["data"])
            emit_scope()
            return SimpleNamespace(status_code=200, content=b'{"orderId":"OrderAa"}')
        monkeypatch.setattr(client.dhan_http.session, "request", send)
        adapter = DhanAdapter(client_factory=lambda _: client, security_resolver=resolver)
        close = client.dhan_http.session.close
    else:
        def send_neo(request: Any) -> Any:
            assert request.url.host == "example.invalid"
            assert request.url.path == "/quick/order/rule/ms/place"
            calls.append(request.content)
            emit_scope()
            return httpx.Response(200, json={"stat": "Ok", "stCode": 200, "nOrdNo": "OrderAa"})
        neo = _sdk_class()(consumer_key="synthetic", transport=httpx.MockTransport(send_neo))
        neo.configuration.edit_token = "synthetic"
        neo.configuration.edit_sid = "synthetic"
        neo.configuration.base_url = "https://example.invalid"
        client = KotakNeoSdkSession.__new__(KotakNeoSdkSession)
        client._neo, client._closed = neo, False
        adapter = KotakNeoAdapter(client_factory=lambda _: client, contract_resolver=resolver)
        close = client.close
    handle = bound(adapter, broker=broker, client=client)
    proof = writer_backend(handle)
    set_safety_gate_secret(b"synthetic-writer-signing-secret-32")
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "frontier.sqlite")
    router = BrokerRouter({broker: adapter}, _provider(handle), consume_gate=SafetyGate().consume,
                          lifecycle_store=ledger, backend_lease_proof=proof)
    context = replace(handle.context[0], mode="live")
    order = Order(symbol=symbol, exchange="NFO", product="NRML", action="BUY", quantity="3",
                  price="100", pricetype="LIMIT")
    scope_records = []

    async def primitive_reader(_session: Any) -> list[dict]:
        return scope_records

    primitive_source = SyntheticNativeScopeSource(adapter=adapter, transport=client,
        reader=primitive_reader, workspace_path=handle.workspace_path, label="inert-installed-sdk-primitives")

    def emit_scope() -> None:
        # These explicit, independent inert-resource facts are not provider qualification.
        # Only the real writer frame supplies attempt/intent/nonce correspondence.
        scope_records.append(primitive_source.observe_transport(transport=client,
            native_account="NativeCase", order=order, order_ids=["OrderAa"], resources=[{
                "native_account": "NativeCase", "native_order_date_basis": "synthetic-independent-identity-day-v1",
                "native_order_date": "2026-10-22", "segment": "NSE_FNO" if broker == "dhan" else "nse_fo",
                "family": "REGULAR", "resource_id": "OrderAa", "leg": "ENTRY_LEG", "order_id": "OrderAa",
                "exchange_order_id": "synthetic-exchange", "filled_quantity": "0", "executions": [],
            }]))
    pins = []
    router.preflight_order(order, adapter_id=broker, account_id="AliasCase", request_ctx=context,
                           capture_target=pins.append)
    signed = SafetyContext.mint(order, mode="live", user_jti=context.jti, actor_type="human",
                               adapter_id=broker, account_id="AliasCase", backend_lease_proof=proof)
    acquired, release = threading.Event(), threading.Event()
    real_lock = adapter._sdk_transport_lock

    class ObservedLock:
        def __enter__(self) -> None:
            real_lock.acquire()
            acquired.set()
            assert release.wait(3)

        def __exit__(self, *_args: Any) -> None:
            real_lock.release()
    adapter._sdk_transport_lock = ObservedLock()
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(asyncio.run, router.place_order(context, order=order, safety_ctx=signed,
        adapter_id=broker, account_id="AliasCase", preflight_target=pins[0]))
    try:
        assert acquired.wait(2)
        assert calls == []
        if rebind:
            workspace = read_workspace_snapshot(handle.workspace_path)
            authority = ManagedSessionAuthority(handle.store.selector_state(handle.selector).version,
                workspace.version, broker_workspace_version(workspace))
            candidate = handle.publisher.prepare_session_candidate(handle.selector,
                Session("successor", 9e9, "OtherNative", broker),
                expected_registry=handle.registry.snapshot_selector(handle.selector), authority=authority,
                broker=broker, label="Synthetic successor", client=object())
            handle.publisher.publish_prepared_candidate(candidate, current_authority=authority)
        release.set()
        if rebind:
            with pytest.raises(Exception):
                future.result(timeout=2)
            assert calls == []
            assert scope_records == []
            assert ledger.list_unresolved_outcomes()
        else:
            assert future.result(timeout=2) == "OrderAa"
            assert len(calls) == 1
            facts = ledger.native_dispatch_evidence(ledger.list_dispatch_attempts()[0]["attempt_id"])
            assert facts[0]["facts"]["preparation"]["wire_json"] == pins[0].preparation.wire_json
            assert facts[1]["order_ids"] == ["OrderAa"]
            assert facts[1]["native_scope_observation"] == scope_records[0]
            assert facts[1]["native_scope_ack_matches"] is True
            assert scope_records[0]["invocation_id"] == facts[0]["facts"]["invocation_id"]
    finally:
        release.set()
        pool.shutdown(wait=True)
        assert router.revoke_and_drain(timeout=1)
        close()
