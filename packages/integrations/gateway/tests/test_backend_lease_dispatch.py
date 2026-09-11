"""Real backend ownership at gate and exact synthetic adapter boundaries."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from flinttrade_core.backend_instance import acquire_backend_instance_lease
from flinttrade_core.exceptions import SafetyBypassError
from flinttrade_engine.request_context import RequestContext
from flinttrade_engine.safety import gate_broker_write, gate_order, set_safety_gate_secret
from flinttrade_gateway.router import BrokerRouter


@pytest.fixture
def owner(tmp_path, monkeypatch):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    set_safety_gate_secret(b"synthetic-backend-proof-test-key-32")
    lease = acquire_backend_instance_lease()
    yield lease
    lease.release()


def _request():
    return RequestContext(jti="synthetic", actor_type="human", actor_id="operator", mode="live")


class _Adapter:
    def __init__(self, inside=None):
        self.calls = []
        self.inside = inside

    async def place_order(self, session, order, **kwargs):
        self.calls.append(order)
        if self.inside is not None:
            await self.inside()
        return "synthetic-ack"

    async def cancel_all_orders(self, session, **kwargs):
        self.calls.append("cancel")
        return {"status": "ok"}


def _router(proof, adapter, **kwargs):
    return BrokerRouter(
        {"synthetic": adapter},
        lambda *_: SimpleNamespace(is_read_only=False, algo_id=""),
        backend_lease_proof=proof,
        **kwargs,
    )


@pytest.mark.parametrize("proof_kind", ["missing", "forged", "released"])
@pytest.mark.parametrize("extended", [False, True])
def test_gate_requires_actual_live_backend_proof(owner, proof_kind, extended):
    proof = owner.proof
    if proof_kind == "released":
        owner.release()
    elif proof_kind == "forged":
        proof = True
    else:
        proof = None
    args = ({"symbol": "SYNTHETIC"}, _request(), "synthetic")
    if extended:
        args = ("cancel_all_orders", {"_op": "cancel_all_orders"}, _request(), "synthetic")
    with pytest.raises(SafetyBypassError, match="backend_lease_unavailable"):
        (gate_broker_write if extended else gate_order)(*args, backend_lease_proof=proof)


@pytest.mark.parametrize("loss_at", ["gate_to_router", "throttle", "external_callback"])
async def test_proof_loss_before_exact_invocation_never_reaches_adapter(owner, loss_at):
    proof = owner.proof
    adapter = _Adapter()

    class Throttle:
        async def acquire(self, *_):
            if loss_at == "throttle":
                proof.revoke()

    router = _router(proof, adapter, rate_limiter=Throttle())
    payload = {"_op": "cancel_all_orders"}
    ticket = gate_broker_write(
        "cancel_all_orders", payload, _request(), "synthetic", backend_lease_proof=proof,
    )
    if loss_at == "gate_to_router":
        proof.revoke()
    with pytest.raises(SafetyBypassError, match="backend_lease_unavailable"):
        await router.execute_gated(
            _request(), verb="cancel_all_orders", payload=payload, safety_ctx=ticket,
            adapter_id="synthetic", account_id="default",
            on_adapter_invoke=proof.revoke if loss_at == "external_callback" else None,
        )
    assert adapter.calls == []
    assert router.revoke_and_drain(timeout=0) is True


async def test_context_incarnation_is_signed_and_old_backend_cannot_replay(owner):
    order = {"symbol": "SYNTHETIC"}
    ticket = gate_order(order, _request(), "synthetic", backend_lease_proof=owner.proof)
    owner.release()
    successor = acquire_backend_instance_lease()
    try:
        adapter = _Adapter()
        router = _router(successor.proof, adapter)
        for candidate in (ticket, replace(ticket, backend_incarnation=str(successor.proof.incarnation))):
            with pytest.raises(SafetyBypassError):
                await router.place_order(
                    _request(), order=order, safety_ctx=candidate, adapter_id="synthetic", account_id="default",
                )
        assert adapter.calls == []
    finally:
        successor.release()


async def test_valid_dispatch_and_inflight_proof_loss_preserve_acknowledgement(owner):
    proof = owner.proof
    entered, finish = asyncio.Event(), asyncio.Event()

    async def inside():
        entered.set()
        await finish.wait()

    adapter = _Adapter(inside)
    router = _router(proof, adapter)
    order = {"symbol": "SYNTHETIC"}
    ticket = gate_order(order, _request(), "synthetic", backend_lease_proof=proof)
    task = asyncio.create_task(router.place_order(
        _request(), order=order, safety_ctx=ticket, adapter_id="synthetic", account_id="default",
    ))
    await asyncio.wait_for(entered.wait(), 1)
    proof.revoke()
    assert router.revoke_and_drain(timeout=0) is False
    finish.set()
    assert await task == "synthetic-ack"
    assert adapter.calls == [order]
    assert router.revoke_and_drain(timeout=0) is True


async def test_inflight_error_after_proof_loss_remains_unknown_without_retry(owner, tmp_path):
    from flinttrade_engine.local_state_provider import DISPATCH_OUTCOME_UNKNOWN, OrderLifecycleLedger

    proof = owner.proof
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / "synthetic-lifecycle.sqlite")

    async def lose_response():
        proof.revoke()
        raise TimeoutError("synthetic invoked response loss")

    adapter = _Adapter(lose_response)
    router = _router(proof, adapter, lifecycle_store=ledger)
    order = {"symbol": "SYNTHETIC"}
    ticket = gate_order(order, _request(), "synthetic", backend_lease_proof=proof)
    with pytest.raises(TimeoutError):
        await router.place_order(
            _request(), order=order, safety_ctx=ticket, adapter_id="synthetic", account_id="default",
        )
    assert adapter.calls == [order]
    assert ledger.list_dispatch_attempts()[0]["dispatch_state"] == DISPATCH_OUTCOME_UNKNOWN
    with pytest.raises(SafetyBypassError, match="backend_lease_unavailable"):
        await router.place_order(
            _request(), order=order, safety_ctx=ticket, adapter_id="synthetic", account_id="default",
        )
    assert adapter.calls == [order]
