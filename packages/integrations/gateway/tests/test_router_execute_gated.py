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

from datetime import datetime, timezone

import pytest

from flinttrade_core.exceptions import SafetyBypassError, UnsupportedCapabilityError
from flinttrade_core.models import Order
from flinttrade_engine.request_context import RequestContext
from flinttrade_engine.safety import (
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

    async def cancel_order(self, session, order_id, *, variety="regular", amo=False, _router_token=None):
        # Kotak-Neo-shaped cancel: variety/amo extras dispatch within the gate.
        self._require(_router_token)
        self.calls.append(("cancel_order", order_id, variety, amo))


def _session(read_only: bool = False) -> Session:
    return Session(
        access_token="tok",
        expires_at=datetime.now(tz=timezone.utc).timestamp() + 3600,
        account_id="acct-1",
        adapter_id="dhan",
        read_only_until_at=(datetime.now(tz=timezone.utc).timestamp() + 3600) if read_only else None,
    )


def _request_ctx() -> RequestContext:
    return RequestContext(jti="jti-1", actor_type="human", actor_id="user-1", mode="live")


def _router(adapter: object, *, read_only: bool = False, consume_gate=None) -> BrokerRouter:
    return BrokerRouter(
        {"dhan": adapter, "upstox": adapter},
        lambda _ctx, _aid, _acct: _session(read_only=read_only),
        consume_gate=consume_gate,
    )


def _mint(verb: str, payload: dict, *, adapter_id: str = "dhan"):
    return gate_broker_write(
        verb, payload, _request_ctx(), adapter_id, account_id="acct-1"
    )


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
    assert adapter.calls == [("cancel_order", "OID-7", "bracket", False)]


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


# ---------------------------------------------------------------------------
# Verb table integrity
# ---------------------------------------------------------------------------


def test_every_registered_verb_has_a_dispatcher() -> None:
    assert set(_GATED_VERB_DISPATCH) == GATED_WRITE_VERBS
