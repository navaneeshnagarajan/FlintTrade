"""BrokerRouter algo-tag guard wiring (contract §8 / SEBI algo tagging, G10).

For adapters advertising ``capabilities.algo_tag_required`` (Dhan/IndMoney),
the router relays the operator's broker-registered ``algo_id`` onto the
dispatch session and enforces the per-(broker, exchange) per-second algo-order
ceiling BELOW the gate — it can only stamp or refuse a verified dispatch,
never bypass safety. Without a guard (or without a config for the broker) the
adapter/mapping retail defaults apply unchanged.
"""

from __future__ import annotations

import types
from datetime import datetime, timezone

import pytest

from flinttrade_engine.algo_tag_guard import AlgoTagConfig, AlgoTagGuard, AlgoTagLimitError
from flinttrade_engine.request_context import RequestContext
from flinttrade_engine.safety import SafetyContext, gate_broker_write, set_safety_gate_secret
from flinttrade_gateway.brokers._base import ROUTER_TOKEN as _ROUTER_TOKEN
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.router import BrokerRouter

pytestmark = pytest.mark.unit

SECRET = b"0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def _bind_secret() -> None:
    set_safety_gate_secret(SECRET)


class _FakeAdapter:
    """Minimal adapter with a togglable ``algo_tag_required`` capability."""

    broker_id = "dhan"

    def __init__(self, *, algo_tag_required: bool = True) -> None:
        self.capabilities = types.SimpleNamespace(algo_tag_required=algo_tag_required)
        self.placed: list[object] = []
        self.calls: list[tuple] = []

    async def place_order(self, session, order, *, _router_token=None):
        assert _router_token is _ROUTER_TOKEN
        self.placed.append(order)
        return "BROKER-OID-1"

    async def modify_order(self, session, order_id, changes, *, _router_token=None):
        assert _router_token is _ROUTER_TOKEN
        self.calls.append(("modify", order_id))

    async def cancel_order(self, session, order_id, *, _router_token=None):
        assert _router_token is _ROUTER_TOKEN
        self.calls.append(("cancel", order_id))

    async def cancel_forever(self, session, order_id, *, _router_token=None):
        assert _router_token is _ROUTER_TOKEN
        self.calls.append(("cancel_forever", order_id))


def _session() -> Session:
    return Session(
        access_token="tok",
        expires_at=datetime.now(tz=timezone.utc).timestamp() + 3600,
        account_id="acct-1",
        adapter_id="dhan",
    )


def _order(symbol: str = "RELIANCE") -> object:
    return types.SimpleNamespace(symbol=symbol, quantity=10, side="BUY", exchange="NSE")


def _request_ctx() -> RequestContext:
    return RequestContext(jti="jti-1", actor_type="human", actor_id="user-1", mode="live")


def _mint(order, **over) -> SafetyContext:
    kwargs = dict(mode="live", user_jti="jti-1", adapter_id="dhan", account_id="acct-1", actor_type="human")
    kwargs.update(over)
    return SafetyContext.mint(order, **kwargs)


def _router(adapter: _FakeAdapter, session: Session, guard: AlgoTagGuard | None) -> BrokerRouter:
    return BrokerRouter(
        {"dhan": adapter},
        lambda _ctx, _aid, _acct: session,
        algo_tag_guard=guard,
    )


def _guard(max_per_sec: int = 10) -> AlgoTagGuard:
    return AlgoTagGuard({"dhan": AlgoTagConfig(algo_id="ALGO-REG-1", max_orders_per_sec=max_per_sec)})


async def test_place_order_stamps_algo_id_and_counts() -> None:
    adapter, session, guard = _FakeAdapter(), _session(), _guard()
    router = _router(adapter, session, guard)
    order = _order()
    await router.place_order(
        _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=_mint(order)
    )
    assert session.algo_id == "ALGO-REG-1"
    assert guard.usage("dhan", "NSE") == 1
    assert adapter.placed == [order]


async def test_ceiling_breach_refuses_dispatch_before_adapter() -> None:
    adapter, session, guard = _FakeAdapter(), _session(), _guard(max_per_sec=2)
    router = _router(adapter, session, guard)
    for _ in range(2):
        order = _order()
        await router.place_order(
            _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=_mint(order)
        )
    order = _order()
    with pytest.raises(AlgoTagLimitError):
        await router.place_order(
            _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=_mint(order)
        )
    # The third dispatch never reached the broker.
    assert len(adapter.placed) == 2


async def test_modify_and_cancel_count_toward_the_ceiling() -> None:
    adapter, session, guard = _FakeAdapter(), _session(), _guard()
    router = _router(adapter, session, guard)
    changes = {"price": "100", "exchange": "NSE"}
    order = {"_op": "modify", "order_id": "OID-1", **changes}
    await router.modify_order(
        _request_ctx(), adapter_id="dhan", account_id="acct-1",
        order=order, order_id="OID-1", changes=changes, safety_ctx=_mint(order),
    )
    order2 = {"_op": "cancel", "order_id": "OID-1", "exchange": "NSE"}
    await router.cancel_order(
        _request_ctx(), adapter_id="dhan", account_id="acct-1",
        order=order2, order_id="OID-1", safety_ctx=_mint(order2),
    )
    assert guard.usage("dhan", "NSE") == 2
    assert [c[0] for c in adapter.calls] == ["modify", "cancel"]


async def test_execute_gated_counts_and_stamps() -> None:
    adapter, session, guard = _FakeAdapter(), _session(), _guard()
    router = _router(adapter, session, guard)
    payload = {"_op": "cancel_forever", "order_id": "GTT-1", "exchange": "NSE"}
    ctx = gate_broker_write("cancel_forever", payload, _request_ctx(), "dhan", account_id="acct-1")
    await router.execute_gated(
        _request_ctx(), verb="cancel_forever", payload=payload, safety_ctx=ctx,
        adapter_id="dhan", account_id="acct-1",
    )
    assert session.algo_id == "ALGO-REG-1"
    assert guard.usage("dhan", "NSE") == 1


async def test_adapter_without_requirement_is_untouched() -> None:
    adapter = _FakeAdapter(algo_tag_required=False)
    session, guard = _session(), _guard()
    router = _router(adapter, session, guard)
    order = _order()
    await router.place_order(
        _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=_mint(order)
    )
    assert session.algo_id == ""
    assert guard.usage("dhan", "NSE") == 0


async def test_unconfigured_broker_keeps_retail_defaults() -> None:
    """A guard with no config for this broker must not tag, count, or refuse —
    the adapter/mapping retail-default algo ids apply unchanged."""
    adapter, session = _FakeAdapter(), _session()
    guard = AlgoTagGuard({"indmoney": AlgoTagConfig(algo_id="X", max_orders_per_sec=5)})
    router = _router(adapter, session, guard)
    order = _order()
    await router.place_order(
        _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=_mint(order)
    )
    assert session.algo_id == ""
    assert adapter.placed == [order]


async def test_no_guard_is_a_noop() -> None:
    adapter, session = _FakeAdapter(), _session()
    router = _router(adapter, session, None)
    order = _order()
    await router.place_order(
        _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=_mint(order)
    )
    assert session.algo_id == ""
    assert adapter.placed == [order]


# ---------------------------------------------------------------------------
# Audit fixes: stale-id clearing + exchange fallback bucket
# ---------------------------------------------------------------------------


async def test_stale_algo_id_is_cleared_when_a_later_dispatch_is_not_tagged() -> None:
    """The registry Session is shared across writes; once the guard stops
    tagging (config removed / adapter no longer required) a previously stamped
    algo_id must NOT keep flowing to the broker."""
    adapter, session, guard = _FakeAdapter(), _session(), _guard()
    router = _router(adapter, session, guard)
    order = _order()
    await router.place_order(
        _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=_mint(order)
    )
    assert session.algo_id == "ALGO-REG-1"

    # Operator removes the algo_tags config → guard has no config for the broker.
    empty_guard = AlgoTagGuard({})
    router2 = _router(adapter, session, empty_guard)
    order2 = _order()
    await router2.place_order(
        _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order2, safety_ctx=_mint(order2)
    )
    assert session.algo_id == ""  # cleared, not the stale ALGO-REG-1


async def test_exchange_less_payload_buckets_under_the_star_key() -> None:
    """An extended-verb payload with no recoverable exchange still counts
    (conservative shared per-broker bucket), and still stamps the algo_id."""
    adapter, session = _FakeAdapter(), _session()
    guard = _guard(max_per_sec=2)
    router = _router(adapter, session, guard)
    payload1 = {"_op": "cancel_forever", "order_id": "GTT-1"}  # no exchange
    ctx1 = gate_broker_write("cancel_forever", payload1, _request_ctx(), "dhan", account_id="acct-1")
    await router.execute_gated(
        _request_ctx(), verb="cancel_forever", payload=payload1, safety_ctx=ctx1,
        adapter_id="dhan", account_id="acct-1",
    )
    assert session.algo_id == "ALGO-REG-1"
    assert guard.usage("dhan", "*") == 1


async def test_nested_exchange_is_recovered_from_the_payload() -> None:
    adapter, session, guard = _FakeAdapter(), _session(), _guard()
    router = _router(adapter, session, guard)
    payload = {"_op": "cancel_forever", "order_id": "G1", "order": {"exchange": "BFO"}}
    ctx = gate_broker_write("cancel_forever", payload, _request_ctx(), "dhan", account_id="acct-1")
    await router.execute_gated(
        _request_ctx(), verb="cancel_forever", payload=payload, safety_ctx=ctx,
        adapter_id="dhan", account_id="acct-1",
    )
    assert guard.usage("dhan", "BFO") == 1
