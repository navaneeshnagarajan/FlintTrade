"""BrokerRouter.execute_gated — extended gated write verbs (contract §8.1).

The extended verbs (forever/super-order/conditional-trigger/convert/exit-all/
multi/cancel-all/smart-cancel) traverse the SAME verify-then-consume gate as
place_order: a one-shot SafetyContext minted by ``gate_broker_write`` for THIS
payload, re-verified field-by-field by the router, consumed exactly once, then
dispatched with the per-process router token. The payload is BOTH the signed
fingerprint AND the dispatch payload, so these tests pin the no-unhashed-field
property: tampering with ANY payload field (including a nested Order's) after
minting invalidates the gate.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import threading

import pytest

from flinttrade_core.exceptions import SafetyBypassError, UnsupportedCapabilityError
from flinttrade_core.models import Order
from flinttrade_engine.local_state_provider import OrderLifecycleLedger
from flinttrade_engine.request_context import RequestContext
from flinttrade_engine.safety import (
    L5_EMERGENCY_POLICY,
    EmergencyReductionPlan,
    GATED_WRITE_VERBS,
    gate_broker_write,
    set_safety_gate_secret,
)
from flinttrade_gateway.brokers._base import ROUTER_TOKEN as _ROUTER_TOKEN
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.router import _GATED_VERB_DISPATCH, BrokerRouter

pytestmark = pytest.mark.unit

SECRET = b"0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def _bind_secret() -> None:
    set_safety_gate_secret(SECRET)


class _FakeNativeAdapter:
    """Fake adapter exposing the extended write verbs, fail-closed on the token."""

    broker_id = "dhan"

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    @staticmethod
    def _require(token: object | None) -> None:
        if token is not _ROUTER_TOKEN:
            raise SafetyBypassError("adapter write method called outside BrokerRouter")

    async def modify_forever(self, session, order_id, changes, *, _router_token=None):
        self._require(_router_token)
        self.calls.append(("modify_forever", order_id, changes))

    async def cancel_forever(self, session, order_id, *, _router_token=None):
        self._require(_router_token)
        self.calls.append(("cancel_forever", order_id))

    async def modify_super_order(self, session, order_id, changes, *, _router_token=None):
        self._require(_router_token)
        self.calls.append(("modify_super_order", order_id, changes))

    async def cancel_super_order(self, session, order_id, leg="ENTRY_LEG", *, _router_token=None):
        self._require(_router_token)
        self.calls.append(("cancel_super_order", order_id, leg))

    async def place_conditional_trigger(self, session, condition, orders, *, _router_token=None):
        self._require(_router_token)
        self.calls.append(("place_conditional_trigger", condition, orders))
        return "ALERT-1"

    async def modify_conditional_trigger(self, session, alert_id, condition, orders, *, _router_token=None):
        self._require(_router_token)
        self.calls.append(("modify_conditional_trigger", alert_id, condition, orders))

    async def cancel_conditional_trigger(self, session, alert_id, *, _router_token=None):
        self._require(_router_token)
        self.calls.append(("cancel_conditional_trigger", alert_id))

    async def convert_position(self, session, req, *, _router_token=None):
        self._require(_router_token)
        self.calls.append(("convert_position", req))

    async def exit_all_positions(self, session, *, _router_token=None):
        # Dhan-shaped: NO tag/segment kwargs — the dispatcher must not pass any.
        self._require(_router_token)
        self.calls.append(("exit_all_positions",))
        return {"status": "ok"}

    async def place_multi_order(self, session, orders, *, _router_token=None):
        self._require(_router_token)
        self.calls.append(("place_multi_order", orders))
        return {"order_ids": [f"OID-{i}" for i, _ in enumerate(orders)]}

    async def cancel_all_orders(self, session, *, tag=None, segment=None, _router_token=None):
        # Upstox-shaped: optional narrowing kwargs.
        self._require(_router_token)
        self.calls.append(("cancel_all_orders", tag, segment))
        return {"status": "ok"}

    async def cancel_smart_order(self, session, order_id, *, segment=None, _router_token=None):
        self._require(_router_token)
        self.calls.append(("cancel_smart_order", order_id, segment))

    async def cancel_order(self, session, order_id, *, variety="regular", amo=False, segment=None, _router_token=None):
        # Kotak/Groww-shaped cancel extras dispatch within the gate.
        self._require(_router_token)
        self.calls.append(("cancel_order", order_id, variety, amo, segment))


class _BlockingLimiter:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def acquire(self, _broker_id: str, _kind: str) -> None:
        self.entered.set()
        await self.release.wait()


def _session(
    read_only: bool = False,
    *,
    adapter_id: str = "dhan",
    account_id: str = "acct-1",
) -> Session:
    return Session(
        access_token="tok",
        expires_at=datetime.now(tz=timezone.utc).timestamp() + 3600,
        account_id=account_id,
        adapter_id=adapter_id,
        read_only_until_at=(datetime.now(tz=timezone.utc).timestamp() + 3600) if read_only else None,
    )


def _request_ctx() -> RequestContext:
    return RequestContext(jti="jti-1", actor_type="human", actor_id="user-1", mode="live")


def _router(
    adapter: object,
    *,
    read_only: bool = False,
    consume_gate=None,
    rate_limiter=None,
    write_admission=None,
    lifecycle_store=None,
) -> BrokerRouter:
    return BrokerRouter(
        {"dhan": adapter, "groww": adapter, "upstox": adapter},
        lambda _ctx, aid, account: _session(
            read_only=read_only,
            adapter_id=aid,
            account_id=account,
        ),
        consume_gate=consume_gate,
        rate_limiter=rate_limiter,
        write_admission=write_admission,
        lifecycle_store=lifecycle_store,
    )


def _mint(verb: str, payload: dict, *, adapter_id: str = "dhan"):
    return gate_broker_write(
        verb, payload, _request_ctx(), adapter_id, account_id="acct-1"
    )


@pytest.mark.parametrize("unidentified_exit_inflight", [False, True])
async def test_plan_emergency_reduction_forwards_unidentified_exit_state(
    unidentified_exit_inflight: bool,
) -> None:
    class _Planner:
        def __init__(self) -> None:
            self.received: bool | None = None

        async def plan_emergency_reduction(
            self,
            _session,
            *,
            policy,
            protected_order_ids,
            protected_exit_order_ids,
            protected_exit_tags,
            unidentified_exit_inflight,
        ):
            self.received = unidentified_exit_inflight
            assert policy == L5_EMERGENCY_POLICY
            assert protected_order_ids == frozenset({"OID-1"})
            assert protected_exit_order_ids == frozenset({"EXIT-1"})
            assert protected_exit_tags == frozenset({"TAG-1"})
            return EmergencyReductionPlan(writes=(), pending_verbs=frozenset())

    adapter = _Planner()
    router = _router(adapter)

    result = await router.plan_emergency_reduction(
        _request_ctx(),
        policy=L5_EMERGENCY_POLICY,
        protected_order_ids=frozenset({"OID-1"}),
        protected_exit_order_ids=frozenset({"EXIT-1"}),
        protected_exit_tags=frozenset({"TAG-1"}),
        unidentified_exit_inflight=unidentified_exit_inflight,
        adapter_id="dhan",
        account_id="acct-1",
    )

    assert result == EmergencyReductionPlan(writes=(), pending_verbs=frozenset())
    assert adapter.received is unidentified_exit_inflight


# ---------------------------------------------------------------------------
# Happy paths — representative verbs across the dispatch shapes
# ---------------------------------------------------------------------------


async def test_modify_forever_dispatches_with_valid_context() -> None:
    adapter = _FakeNativeAdapter()
    router = _router(adapter)
    payload = {"_op": "modify_forever", "order_id": "GTT-1", "changes": {"price": "2900"}}
    ctx = _mint("modify_forever", payload)
    await router.execute_gated(
        _request_ctx(), verb="modify_forever", payload=payload, safety_ctx=ctx,
        adapter_id="dhan", account_id="acct-1",
    )
    assert adapter.calls == [("modify_forever", "GTT-1", {"price": "2900"})]


async def test_execute_gated_dispatches_detached_nested_snapshot_after_throttle() -> None:
    adapter = _FakeNativeAdapter()
    limiter = _BlockingLimiter()
    router = _router(adapter, rate_limiter=limiter)
    payload = {
        "_op": "modify_forever",
        "order_id": "GTT-1",
        "changes": {"nested": {"price": "2900"}},
    }
    ctx = _mint("modify_forever", payload)

    dispatch = asyncio.create_task(
        router.execute_gated(
            _request_ctx(),
            verb="modify_forever",
            payload=payload,
            safety_ctx=ctx,
            adapter_id="dhan",
            account_id="acct-1",
        )
    )
    await limiter.entered.wait()
    payload["order_id"] = "TAMPERED"
    payload["changes"]["nested"]["price"] = "9999"
    limiter.release.set()

    await dispatch
    assert adapter.calls == [
        ("modify_forever", "GTT-1", {"nested": {"price": "2900"}}),
    ]


async def test_cancel_super_order_defaults_entry_leg() -> None:
    adapter = _FakeNativeAdapter()
    router = _router(adapter)
    payload = {"_op": "cancel_super_order", "order_id": "SUP-1"}
    ctx = _mint("cancel_super_order", payload)
    await router.execute_gated(
        _request_ctx(), verb="cancel_super_order", payload=payload, safety_ctx=ctx,
        adapter_id="dhan", account_id="acct-1",
    )
    assert adapter.calls == [("cancel_super_order", "SUP-1", "ENTRY_LEG")]


async def test_cancel_super_order_explicit_leg_travels_in_signed_payload() -> None:
    adapter = _FakeNativeAdapter()
    router = _router(adapter)
    payload = {"_op": "cancel_super_order", "order_id": "SUP-1", "leg": "TARGET_LEG"}
    ctx = _mint("cancel_super_order", payload)
    await router.execute_gated(
        _request_ctx(), verb="cancel_super_order", payload=payload, safety_ctx=ctx,
        adapter_id="dhan", account_id="acct-1",
    )
    assert adapter.calls == [("cancel_super_order", "SUP-1", "TARGET_LEG")]


async def test_place_multi_order_dispatches_typed_orders() -> None:
    adapter = _FakeNativeAdapter()
    router = _router(adapter)
    orders = [
        Order(symbol="RELIANCE", action="BUY", exchange="NSE", quantity="1"),
        Order(symbol="TCS", action="SELL", exchange="NSE", quantity="2"),
    ]
    payload = {"_op": "place_multi_order", "orders": orders}
    ctx = _mint("place_multi_order", payload)
    result = await router.execute_gated(
        _request_ctx(), verb="place_multi_order", payload=payload, safety_ctx=ctx,
        adapter_id="dhan", account_id="acct-1",
    )
    assert result == {"order_ids": ["OID-0", "OID-1"]}
    assert adapter.calls == [("place_multi_order", orders)]


async def test_multi_order_acknowledgement_does_not_poison_real_lifecycle_ledger(tmp_path) -> None:
    class _UniqueBatchAdapter(_FakeNativeAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.batch_number = 0

        async def place_multi_order(self, session, orders, *, _router_token=None):
            self._require(_router_token)
            self.batch_number += 1
            self.calls.append(("place_multi_order", orders))
            return {
                "order_ids": [
                    f"BATCH-{self.batch_number}-OID-{index}"
                    for index, _order in enumerate(orders)
                ]
            }

    adapter = _UniqueBatchAdapter()
    lifecycle = OrderLifecycleLedger(ledger_path=tmp_path / "order-lifecycle.sqlite3")
    router = _router(adapter, lifecycle_store=lifecycle)
    first_orders = [
        Order(symbol="RELIANCE", action="BUY", exchange="NSE", quantity="1"),
        Order(symbol="TCS", action="SELL", exchange="NSE", quantity="2"),
    ]
    first_payload = {"_op": "place_multi_order", "orders": first_orders}

    assert await router.execute_gated(
        _request_ctx(),
        verb="place_multi_order",
        payload=first_payload,
        safety_ctx=_mint("place_multi_order", first_payload, adapter_id="upstox"),
        adapter_id="upstox",
        account_id="acct-1",
    ) == {"order_ids": ["BATCH-1-OID-0", "BATCH-1-OID-1"]}

    second_orders = [Order(symbol="INFY", action="BUY", exchange="NSE", quantity="3")]
    second_payload = {"_op": "place_multi_order", "orders": second_orders}
    assert await router.execute_gated(
        _request_ctx(),
        verb="place_multi_order",
        payload=second_payload,
        safety_ctx=_mint("place_multi_order", second_payload, adapter_id="upstox"),
        adapter_id="upstox",
        account_id="acct-1",
    ) == {"order_ids": ["BATCH-2-OID-0"]}

    assert [attempt["dispatch_state"] for attempt in lifecycle.list_dispatch_attempts()] == [
        "ACKNOWLEDGED",
        "ACKNOWLEDGED",
    ]


async def test_exit_all_positions_omits_absent_optional_kwargs() -> None:
    """The Dhan-shaped adapter takes no tag/segment — the dispatcher must not
    forward kwargs that are absent from the signed payload."""
    adapter = _FakeNativeAdapter()
    router = _router(adapter)
    payload = {"_op": "exit_all_positions"}
    ctx = _mint("exit_all_positions", payload)
    result = await router.execute_gated(
        _request_ctx(), verb="exit_all_positions", payload=payload, safety_ctx=ctx,
        adapter_id="dhan", account_id="acct-1",
    )
    assert result == {"status": "ok"}
    assert adapter.calls == [("exit_all_positions",)]


async def test_cancel_all_orders_forwards_signed_narrowing_kwargs() -> None:
    adapter = _FakeNativeAdapter()
    router = _router(adapter)
    payload = {"_op": "cancel_all_orders", "tag": "ALGO1", "segment": "EQ"}
    ctx = _mint("cancel_all_orders", payload)
    await router.execute_gated(
        _request_ctx(), verb="cancel_all_orders", payload=payload, safety_ctx=ctx,
        adapter_id="dhan", account_id="acct-1",
    )
    assert adapter.calls == [("cancel_all_orders", "ALGO1", "EQ")]


async def test_convert_position_dispatches_req_from_signed_payload() -> None:
    adapter = _FakeNativeAdapter()
    router = _router(adapter)
    req = {"symbol": "RELIANCE", "exchange": "NSE", "from_product": "MIS",
           "to_product": "CNC", "position_type": "LONG", "quantity": 5}
    payload = {"_op": "convert_position", "req": req}
    ctx = _mint("convert_position", payload)
    await router.execute_gated(
        _request_ctx(), verb="convert_position", payload=payload, safety_ctx=ctx,
        adapter_id="dhan", account_id="acct-1",
    )
    assert adapter.calls == [("convert_position", req)]


async def test_cancel_smart_order_dispatches_with_segment() -> None:
    adapter = _FakeNativeAdapter()
    router = _router(adapter)
    payload = {"_op": "cancel_smart_order", "order_id": "DRV-1", "segment": "DERIVATIVE"}
    ctx = _mint("cancel_smart_order", payload)
    await router.execute_gated(
        _request_ctx(), verb="cancel_smart_order", payload=payload, safety_ctx=ctx,
        adapter_id="dhan", account_id="acct-1",
    )
    assert adapter.calls == [("cancel_smart_order", "DRV-1", "DERIVATIVE")]


@pytest.mark.parametrize(
    "payload",
    [
        {"_op": "cancel_smart_order", "order_id": 7, "segment": "DERIVATIVE"},
        {"_op": "cancel_smart_order", "order_id": "DRV-1", "segment": ""},
        {"_op": "cancel_smart_order", "order_id": "DRV-1", "segment": 0},
        {"_op": "cancel_smart_order", "order_id": "DRV-1", "segment": "derivative"},
    ],
)
async def test_cancel_smart_order_rejects_noncanonical_signed_identity(payload) -> None:
    adapter = _FakeNativeAdapter()
    router = _router(adapter)
    ctx = _mint("cancel_smart_order", payload)

    with pytest.raises(SafetyBypassError):
        await router.execute_gated(
            _request_ctx(),
            verb="cancel_smart_order",
            payload=payload,
            safety_ctx=ctx,
            adapter_id="dhan",
            account_id="acct-1",
        )

    assert adapter.calls == []


async def test_execute_gated_marks_the_exact_adapter_invocation_boundary() -> None:
    adapter = _FakeNativeAdapter()
    router = _router(adapter)
    payload = {"_op": "cancel_smart_order", "order_id": "DRV-1", "segment": "DERIVATIVE"}
    ctx = _mint("cancel_smart_order", payload)
    invoked: list[bool] = []

    await router.execute_gated(
        _request_ctx(),
        verb="cancel_smart_order",
        payload=payload,
        safety_ctx=ctx,
        adapter_id="dhan",
        account_id="acct-1",
        on_adapter_invoke=lambda: invoked.append(True),
    )

    assert invoked == [True]


# ---------------------------------------------------------------------------
# Tamper / replay / identity rejection
# ---------------------------------------------------------------------------


async def test_tampered_payload_field_is_rejected() -> None:
    """Mutating ANY payload field after minting must invalidate the gate."""
    adapter = _FakeNativeAdapter()
    router = _router(adapter)
    payload = {"_op": "modify_forever", "order_id": "GTT-1", "changes": {"price": "2900"}}
    ctx = _mint("modify_forever", payload)
    payload["changes"] = {"price": "9999"}  # tamper after mint
    with pytest.raises(SafetyBypassError, match="verification failed"):
        await router.execute_gated(
            _request_ctx(), verb="modify_forever", payload=payload, safety_ctx=ctx,
            adapter_id="dhan", account_id="acct-1",
        )
    assert adapter.calls == []


async def test_tampered_nested_order_is_rejected() -> None:
    """A nested Order's field mutation (e.g. quantity) must flip the hash too —
    the multi-order payload is covered end-to-end, not just its top level."""
    adapter = _FakeNativeAdapter()
    router = _router(adapter)
    orders = [Order(symbol="RELIANCE", action="BUY", exchange="NSE", quantity="1")]
    payload = {"_op": "place_multi_order", "orders": orders}
    ctx = _mint("place_multi_order", payload)
    orders[0].quantity = "100000"  # tamper the nested order after mint
    with pytest.raises(SafetyBypassError, match="verification failed"):
        await router.execute_gated(
            _request_ctx(), verb="place_multi_order", payload=payload, safety_ctx=ctx,
            adapter_id="dhan", account_id="acct-1",
        )
    assert adapter.calls == []


async def test_replayed_gate_is_rejected() -> None:
    adapter = _FakeNativeAdapter()
    consumed: set[str] = set()

    def consume(gate_id: str) -> bool:
        if gate_id in consumed:
            return False
        consumed.add(gate_id)
        return True

    router = _router(adapter, consume_gate=consume)
    payload = {"_op": "cancel_forever", "order_id": "GTT-9"}
    ctx = _mint("cancel_forever", payload)
    await router.execute_gated(
        _request_ctx(), verb="cancel_forever", payload=payload, safety_ctx=ctx,
        adapter_id="dhan", account_id="acct-1",
    )
    with pytest.raises(SafetyBypassError, match="already consumed"):
        await router.execute_gated(
            _request_ctx(), verb="cancel_forever", payload=payload, safety_ctx=ctx,
            adapter_id="dhan", account_id="acct-1",
        )
    assert adapter.calls == [("cancel_forever", "GTT-9")]


async def test_wrong_adapter_is_rejected() -> None:
    """A gate minted for 'dhan' must not fire against 'upstox'."""
    adapter = _FakeNativeAdapter()
    router = _router(adapter)
    payload = {"_op": "exit_all_positions"}
    ctx = _mint("exit_all_positions", payload, adapter_id="dhan")
    with pytest.raises(SafetyBypassError, match="verification failed"):
        await router.execute_gated(
            _request_ctx(), verb="exit_all_positions", payload=payload, safety_ctx=ctx,
            adapter_id="upstox", account_id="acct-1",
        )
    assert adapter.calls == []


async def test_cross_verb_replay_is_rejected() -> None:
    """A gate minted for cancel_forever cannot dispatch modify_forever: the _op
    discriminator is inside the signed payload."""
    adapter = _FakeNativeAdapter()
    router = _router(adapter)
    payload = {"_op": "cancel_forever", "order_id": "GTT-1"}
    ctx = _mint("cancel_forever", payload)
    # (a) same payload, different verb — refused before any verification.
    with pytest.raises(SafetyBypassError, match="_op does not match"):
        await router.execute_gated(
            _request_ctx(), verb="modify_forever", payload=payload, safety_ctx=ctx,
            adapter_id="dhan", account_id="acct-1",
        )
    # (b) re-labelled payload — hash no longer matches the minted context.
    relabelled = {"_op": "modify_forever", "order_id": "GTT-1", "changes": {}}
    with pytest.raises(SafetyBypassError, match="verification failed"):
        await router.execute_gated(
            _request_ctx(), verb="modify_forever", payload=relabelled, safety_ctx=ctx,
            adapter_id="dhan", account_id="acct-1",
        )
    assert adapter.calls == []


async def test_unknown_verb_is_rejected() -> None:
    adapter = _FakeNativeAdapter()
    router = _router(adapter)
    payload = {"_op": "transfer_funds"}
    ctx = _mint("cancel_forever", {"_op": "cancel_forever", "order_id": "X"})
    with pytest.raises(SafetyBypassError, match="unknown gated write verb"):
        await router.execute_gated(
            _request_ctx(), verb="transfer_funds", payload=payload, safety_ctx=ctx,
            adapter_id="dhan", account_id="acct-1",
        )
    assert adapter.calls == []


async def test_read_only_session_is_rejected() -> None:
    adapter = _FakeNativeAdapter()
    router = _router(adapter, read_only=True)
    payload = {"_op": "cancel_forever", "order_id": "GTT-1"}
    ctx = _mint("cancel_forever", payload)
    with pytest.raises(SafetyBypassError, match="read-only"):
        await router.execute_gated(
            _request_ctx(), verb="cancel_forever", payload=payload, safety_ctx=ctx,
            adapter_id="dhan", account_id="acct-1",
        )
    assert adapter.calls == []


async def test_unsupported_verb_on_adapter_raises_capability_error() -> None:
    """An adapter without the verb refuses cleanly (501-shaped), never AttributeError."""

    class _Bare:
        broker_id = "kotakneo"

    router = BrokerRouter({"dhan": _Bare()}, lambda _ctx, _aid, _acct: _session())
    payload = {"_op": "place_multi_order", "orders": []}
    ctx = _mint("place_multi_order", payload)
    with pytest.raises(UnsupportedCapabilityError, match="place_multi_order"):
        await router.execute_gated(
            _request_ctx(), verb="place_multi_order", payload=payload, safety_ctx=ctx,
            adapter_id="dhan", account_id="acct-1",
        )


async def test_missing_required_payload_field_fails_closed() -> None:
    adapter = _FakeNativeAdapter()
    router = _router(adapter)
    payload = {"_op": "modify_forever", "order_id": "GTT-1"}  # no "changes"
    ctx = _mint("modify_forever", payload)
    with pytest.raises(ValueError, match="missing required field 'changes'"):
        await router.execute_gated(
            _request_ctx(), verb="modify_forever", payload=payload, safety_ctx=ctx,
            adapter_id="dhan", account_id="acct-1",
        )
    assert adapter.calls == []


# ---------------------------------------------------------------------------
# cancel_order extras (Kotak Neo bo/co leg exits) — covered-by-fingerprint rule
# ---------------------------------------------------------------------------


async def test_cancel_order_extras_dispatch_when_covered_by_fingerprint() -> None:
    from flinttrade_engine.safety import gate_order

    adapter = _FakeNativeAdapter()
    router = _router(adapter)
    canonical = {"_op": "cancel", "order_id": "OID-7", "variety": "bracket", "amo": False}
    ctx = gate_order(canonical, _request_ctx(), "dhan", account_id="acct-1")
    await router.cancel_order(
        _request_ctx(), order=canonical, order_id="OID-7", safety_ctx=ctx,
        adapter_id="dhan", account_id="acct-1",
        extras={"variety": "bracket", "amo": False},
    )
    assert adapter.calls == [("cancel_order", "OID-7", "bracket", False, None)]


async def test_cancel_order_segment_extra_dispatches_when_covered_by_fingerprint() -> None:
    from flinttrade_engine.safety import gate_order

    adapter = _FakeNativeAdapter()
    router = _router(adapter)
    canonical = {"_op": "cancel", "order_id": "OID-8", "segment": "FNO"}
    ctx = gate_order(canonical, _request_ctx(), "groww", account_id="acct-1")
    await router.cancel_order(
        _request_ctx(),
        order=canonical,
        order_id="OID-8",
        safety_ctx=ctx,
        adapter_id="groww",
        account_id="acct-1",
        extras={"segment": "FNO"},
    )
    assert adapter.calls == [("cancel_order", "OID-8", "regular", False, "FNO")]


async def test_cancel_order_dispatches_signed_detached_values_after_throttle() -> None:
    from flinttrade_engine.safety import gate_order

    adapter = _FakeNativeAdapter()
    limiter = _BlockingLimiter()
    router = _router(adapter, rate_limiter=limiter)
    canonical = {
        "_op": "cancel",
        "order_id": "OID-7",
        "variety": "bracket",
        "amo": False,
    }
    extras = {"variety": "bracket", "amo": False}
    ctx = gate_order(canonical, _request_ctx(), "dhan", account_id="acct-1")

    dispatch = asyncio.create_task(
        router.cancel_order(
            _request_ctx(),
            order=canonical,
            order_id="OID-7",
            safety_ctx=ctx,
            adapter_id="dhan",
            account_id="acct-1",
            extras=extras,
        )
    )
    await limiter.entered.wait()
    canonical["order_id"] = "TAMPERED"
    canonical["variety"] = "cover"
    extras["amo"] = True
    limiter.release.set()

    await dispatch
    assert adapter.calls == [("cancel_order", "OID-7", "bracket", False, None)]


@pytest.mark.parametrize(
    ("canonical", "extras"),
    [
        ({"_op": "cancel", "order_id": "OID-7"}, {"amo": None}),
        ({"_op": "cancel", "order_id": "OID-7", "amo": False}, {"amo": 0}),
        ({"_op": "cancel", "order_id": "OID-7", "amo": True}, {"amo": 1}),
    ],
)
async def test_cancel_order_rejects_noncanonical_extra_matches_before_gate_consumption(
    canonical: dict[str, object],
    extras: dict[str, object],
) -> None:
    from flinttrade_engine.safety import gate_order

    consumed: list[str] = []
    adapter = _FakeNativeAdapter()
    router = _router(adapter, consume_gate=lambda gate_id: consumed.append(gate_id) or True)
    ctx = gate_order(canonical, _request_ctx(), "dhan", account_id="acct-1")

    with pytest.raises(SafetyBypassError, match="extras"):
        await router.cancel_order(
            _request_ctx(),
            order=canonical,
            order_id="OID-7",
            safety_ctx=ctx,
            adapter_id="dhan",
            account_id="acct-1",
            extras=extras,
        )

    assert consumed == []
    assert adapter.calls == []


async def test_cancel_order_extras_not_in_fingerprint_are_refused() -> None:
    from flinttrade_engine.safety import gate_order

    adapter = _FakeNativeAdapter()
    router = _router(adapter)
    canonical = {"_op": "cancel", "order_id": "OID-7"}
    ctx = gate_order(canonical, _request_ctx(), "dhan", account_id="acct-1")
    with pytest.raises(SafetyBypassError, match="not covered by the signed"):
        await router.cancel_order(
            _request_ctx(), order=canonical, order_id="OID-7", safety_ctx=ctx,
            adapter_id="dhan", account_id="acct-1",
            extras={"variety": "bracket"},  # unhashed extra — must never dispatch
        )
    assert adapter.calls == []


async def test_cancel_order_extras_require_mapping_fingerprint() -> None:
    import types

    from flinttrade_engine.safety import gate_order

    adapter = _FakeNativeAdapter()
    router = _router(adapter)
    canonical = types.SimpleNamespace(order_id="OID-7", variety="bracket")
    ctx = gate_order(canonical, _request_ctx(), "dhan", account_id="acct-1")
    with pytest.raises(SafetyBypassError, match="Mapping cancel fingerprint"):
        await router.cancel_order(
            _request_ctx(), order=canonical, order_id="OID-7", safety_ctx=ctx,
            adapter_id="dhan", account_id="acct-1",
            extras={"variety": "bracket"},
        )
    assert adapter.calls == []


async def test_cancelled_native_worker_retains_router_and_safety_write_ownership() -> None:
    from flinttrade_engine.safety import KillSwitch
    from flinttrade_gateway.brokers._base import run_blocking_sdk_call

    worker_started = threading.Event()
    release_worker = threading.Event()

    def blocking_cancel() -> None:
        worker_started.set()
        release_worker.wait(timeout=2)

    class BlockingAdapter(_FakeNativeAdapter):
        async def cancel_all_orders(self, session, *, tag=None, segment=None, _router_token=None):
            self._require(_router_token)
            await run_blocking_sdk_call(blocking_cancel)

    kill_switch = KillSwitch(normal_write_drain_timeout=0)
    adapter = BlockingAdapter()
    router = _router(adapter, write_admission=kill_switch.broker_write_admission)
    payload = {"_op": "cancel_all_orders"}
    ctx = _mint("cancel_all_orders", payload)
    baseline_tasks = asyncio.all_tasks()
    dispatch = asyncio.create_task(
        router.execute_gated(
            _request_ctx(),
            verb="cancel_all_orders",
            payload=payload,
            safety_ctx=ctx,
            adapter_id="dhan",
            account_id="acct-1",
        )
    )

    try:
        assert await asyncio.to_thread(worker_started.wait, 1)
        for task in asyncio.all_tasks() - baseline_tasks:
            task.cancel()
        await asyncio.sleep(0)
        dispatch.cancel()
        await asyncio.sleep(0)

        assert not dispatch.done()
        assert router.revoke_and_drain(timeout=0) is False
        with pytest.raises(SafetyBypassError, match="still in progress"):
            kill_switch.wait_for_idle(timeout=0)
    finally:
        release_worker.set()

    with pytest.raises(asyncio.CancelledError):
        await dispatch
    assert router.revoke_and_drain(timeout=0.1) is True
    kill_switch.wait_for_idle(timeout=0.1)


# ---------------------------------------------------------------------------
# Verb table integrity
# ---------------------------------------------------------------------------


def test_every_registered_verb_has_a_dispatcher() -> None:
    assert set(_GATED_VERB_DISPATCH) == GATED_WRITE_VERBS
