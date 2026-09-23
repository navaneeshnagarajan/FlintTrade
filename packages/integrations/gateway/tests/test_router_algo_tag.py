"""BrokerRouter algo-tag guard wiring (contract §8 / SEBI algo tagging, G10).

For adapters advertising required or optional algo-tag support, the router
relays the operator's trusted configured ``algo_id`` onto the dispatch session
and enforces the per-(broker, exchange) per-second algo-order ceiling BELOW the
gate — it can only stamp or refuse a verified dispatch, never bypass safety.
Without a guard (or without a config for the broker) adapter/mapping retail
defaults apply unchanged.
"""

from __future__ import annotations

import types
from datetime import datetime, timezone

import pytest

from flinttrade_core.models import Order
from flinttrade_engine.algo_tag_guard import AlgoTagConfig, AlgoTagGuard, AlgoTagLimitError
from flinttrade_engine.request_context import RequestContext
from flinttrade_engine.safety import SafetyContext, gate_broker_write, set_safety_gate_secret
from flinttrade_gateway.brokers._base import ROUTER_TOKEN as _ROUTER_TOKEN
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.kotakneo import KOTAKNEO_CAPABILITIES, KotakNeoAdapter
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


class _KotakClient:
    def __init__(self) -> None:
        self.placed: list[dict[str, object]] = []

    def place_order(self, params):
        self.placed.append(params)
        return {"stat": "Ok", "nOrdNo": "KOTAK-OID-1", "stCode": 200}


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


def _mint(order, *, backend_lease_factory, **over) -> SafetyContext:
    kwargs = dict(mode="live", user_jti="jti-1", adapter_id="dhan", account_id="acct-1", actor_type="human")
    kwargs.update(over)
    return SafetyContext.mint(order, **kwargs, backend_lease_proof=backend_lease_factory())


def _router(adapter: _FakeAdapter, session: Session, guard: AlgoTagGuard | None, *, backend_lease_factory) -> BrokerRouter:
    return BrokerRouter(
        {"dhan": adapter},
        lambda _ctx, _aid, _acct: session,
        algo_tag_guard=guard, backend_lease_proof=backend_lease_factory()
    )


def _guard(max_per_sec: int = 10) -> AlgoTagGuard:
    return AlgoTagGuard({"dhan": AlgoTagConfig(algo_id="ALGO-REG-1", max_orders_per_sec=max_per_sec)})


def _kotak_session(*, algo_id: str = "") -> Session:
    return Session(
        access_token="tok",
        expires_at=datetime.now(tz=timezone.utc).timestamp() + 3600,
        account_id="acct-1",
        adapter_id="kotakneo",
        algo_id=algo_id,
    )


def _kotak_order(*, strategy: str = "Flint") -> Order:
    return Order(
        symbol="RELIANCE",
        action="BUY",
        exchange="NSE",
        pricetype="MARKET",
        product="MIS",
        quantity="1",
        strategy=strategy,
    )


def _kotak_mint(order: Order, *, backend_lease_factory) -> SafetyContext:
    return SafetyContext.mint(
        order,
        mode="live",
        user_jti="jti-1",
        adapter_id="kotakneo",
        account_id="acct-1",
        actor_type="human",
        backend_lease_proof=backend_lease_factory(),
    )


def _kotak_router(
    client: _KotakClient,
    session: Session,
    guard: AlgoTagGuard | None,
    *,
    backend_lease_factory,
) -> BrokerRouter:
    adapter = KotakNeoAdapter(
        client_factory=lambda _session: client,
        symbol_resolver=lambda _symbol, _exchange: "RELIANCE-EQ",
    )
    return BrokerRouter(
        {"kotakneo": adapter},
        lambda _ctx, _aid, _acct: session,
        algo_tag_guard=guard,
        backend_lease_proof=backend_lease_factory(),
    )


async def test_place_order_stamps_algo_id_and_counts(*, backend_lease_factory) -> None:
    adapter, session, guard = _FakeAdapter(), _session(), _guard()
    router = _router(adapter, session, guard, backend_lease_factory=backend_lease_factory)
    order = _order()
    await router.place_order(
        _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=_mint(order, backend_lease_factory=backend_lease_factory)
    )
    assert session.algo_id == "ALGO-REG-1"
    assert guard.usage("dhan", "NSE") == 1
    assert adapter.placed == [order]


async def test_ceiling_breach_refuses_dispatch_before_adapter(*, backend_lease_factory) -> None:
    adapter, session, guard = _FakeAdapter(), _session(), _guard(max_per_sec=2)
    router = _router(adapter, session, guard, backend_lease_factory=backend_lease_factory)
    for _ in range(2):
        order = _order()
        await router.place_order(
            _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=_mint(order, backend_lease_factory=backend_lease_factory)
        )
    order = _order()
    with pytest.raises(AlgoTagLimitError):
        await router.place_order(
            _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=_mint(order, backend_lease_factory=backend_lease_factory)
        )
    # The third dispatch never reached the broker.
    assert len(adapter.placed) == 2


async def test_modify_and_cancel_count_toward_the_ceiling(*, backend_lease_factory) -> None:
    adapter, session, guard = _FakeAdapter(), _session(), _guard()
    router = _router(adapter, session, guard, backend_lease_factory=backend_lease_factory)
    changes = {"price": "100", "exchange": "NSE"}
    order = {"_op": "modify", "order_id": "OID-1", **changes}
    await router.modify_order(
        _request_ctx(), adapter_id="dhan", account_id="acct-1",
        order=order, order_id="OID-1", changes=changes, safety_ctx=_mint(order, backend_lease_factory=backend_lease_factory),
    )
    order2 = {"_op": "cancel", "order_id": "OID-1", "exchange": "NSE"}
    await router.cancel_order(
        _request_ctx(), adapter_id="dhan", account_id="acct-1",
        order=order2, order_id="OID-1", safety_ctx=_mint(order2, backend_lease_factory=backend_lease_factory),
    )
    assert guard.usage("dhan", "NSE") == 2
    assert [c[0] for c in adapter.calls] == ["modify", "cancel"]


async def test_execute_gated_counts_and_stamps(*, backend_lease_factory) -> None:
    adapter, session, guard = _FakeAdapter(), _session(), _guard()
    router = _router(adapter, session, guard, backend_lease_factory=backend_lease_factory)
    payload = {"_op": "cancel_forever", "order_id": "GTT-1", "exchange": "NSE"}
    ctx = gate_broker_write("cancel_forever", payload, _request_ctx(), "dhan", account_id="acct-1", backend_lease_proof=backend_lease_factory())
    await router.execute_gated(
        _request_ctx(), verb="cancel_forever", payload=payload, safety_ctx=ctx,
        adapter_id="dhan", account_id="acct-1",
    )
    assert session.algo_id == "ALGO-REG-1"
    assert guard.usage("dhan", "NSE") == 1


async def test_adapter_without_requirement_is_untouched(*, backend_lease_factory) -> None:
    adapter = _FakeAdapter(algo_tag_required=False)
    session, guard = _session(), _guard()
    router = _router(adapter, session, guard, backend_lease_factory=backend_lease_factory)
    order = _order()
    await router.place_order(
        _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=_mint(order, backend_lease_factory=backend_lease_factory)
    )
    assert session.algo_id == ""
    assert guard.usage("dhan", "NSE") == 0


def test_kotak_declares_optional_algo_tag_support() -> None:
    assert KOTAKNEO_CAPABILITIES.algo_tag_supported is True
    assert KOTAKNEO_CAPABILITIES.algo_tag_required is False


async def test_kotak_configured_algo_tag_reaches_payload_instead_of_order_strategy(
    *, backend_lease_factory
) -> None:
    client = _KotakClient()
    session = _kotak_session()
    guard = AlgoTagGuard({"kotakneo": AlgoTagConfig(algo_id="TRUSTED-KOTAK-TAG", max_orders_per_sec=10)})
    router = _kotak_router(client, session, guard, backend_lease_factory=backend_lease_factory)
    order = _kotak_order(strategy="UNTRUSTED-FREE-FORM-STRATEGY")

    await router.place_order(
        _request_ctx(),
        adapter_id="kotakneo",
        account_id="acct-1",
        order=order,
        safety_ctx=_kotak_mint(order, backend_lease_factory=backend_lease_factory),
    )

    assert session.algo_id == "TRUSTED-KOTAK-TAG"
    assert client.placed[0]["tag"] == "TRUSTED-KOTAK-TAG"


async def test_kotak_order_strategy_never_becomes_broker_tag(*, backend_lease_factory) -> None:
    client = _KotakClient()
    session = _kotak_session()
    router = _kotak_router(client, session, None, backend_lease_factory=backend_lease_factory)
    order = _kotak_order(strategy="USER-CONTROLLED")

    await router.place_order(
        _request_ctx(),
        adapter_id="kotakneo",
        account_id="acct-1",
        order=order,
        safety_ctx=_kotak_mint(order, backend_lease_factory=backend_lease_factory),
    )

    assert session.algo_id == ""
    assert "tag" not in client.placed[0]


async def test_optional_tag_adapter_clears_stale_session_tag_without_config(*, backend_lease_factory) -> None:
    client = _KotakClient()
    session = _kotak_session(algo_id="STALE-ALGO-ID")
    router = _kotak_router(client, session, AlgoTagGuard({}), backend_lease_factory=backend_lease_factory)
    order = _kotak_order()

    await router.place_order(
        _request_ctx(),
        adapter_id="kotakneo",
        account_id="acct-1",
        order=order,
        safety_ctx=_kotak_mint(order, backend_lease_factory=backend_lease_factory),
    )

    assert session.algo_id == ""
    assert "tag" not in client.placed[0]


async def test_unconfigured_broker_keeps_retail_defaults(*, backend_lease_factory) -> None:
    """A guard with no config for this broker must not tag, count, or refuse —
    the adapter/mapping retail-default algo ids apply unchanged."""
    adapter, session = _FakeAdapter(), _session()
    guard = AlgoTagGuard({"indmoney": AlgoTagConfig(algo_id="X", max_orders_per_sec=5)})
    router = _router(adapter, session, guard, backend_lease_factory=backend_lease_factory)
    order = _order()
    await router.place_order(
        _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=_mint(order, backend_lease_factory=backend_lease_factory)
    )
    assert session.algo_id == ""
    assert adapter.placed == [order]


async def test_no_guard_is_a_noop(*, backend_lease_factory) -> None:
    adapter, session = _FakeAdapter(), _session()
    router = _router(adapter, session, None, backend_lease_factory=backend_lease_factory)
    order = _order()
    await router.place_order(
        _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=_mint(order, backend_lease_factory=backend_lease_factory)
    )
    assert session.algo_id == ""
    assert adapter.placed == [order]


# ---------------------------------------------------------------------------
# Audit fixes: stale-id clearing + exchange fallback bucket
# ---------------------------------------------------------------------------


async def test_stale_algo_id_is_cleared_when_a_later_dispatch_is_not_tagged(*, backend_lease_factory) -> None:
    """The registry Session is shared across writes; once the guard stops
    tagging (config removed / adapter no longer required) a previously stamped
    algo_id must NOT keep flowing to the broker."""
    adapter, session, guard = _FakeAdapter(), _session(), _guard()
    router = _router(adapter, session, guard, backend_lease_factory=backend_lease_factory)
    order = _order()
    await router.place_order(
        _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=_mint(order, backend_lease_factory=backend_lease_factory)
    )
    assert session.algo_id == "ALGO-REG-1"

    # Operator removes the algo_tags config → guard has no config for the broker.
    empty_guard = AlgoTagGuard({})
    router2 = _router(adapter, session, empty_guard, backend_lease_factory=backend_lease_factory)
    order2 = _order()
    await router2.place_order(
        _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order2, safety_ctx=_mint(order2, backend_lease_factory=backend_lease_factory)
    )
    assert session.algo_id == ""  # cleared, not the stale ALGO-REG-1


async def test_exchange_less_payload_buckets_under_the_star_key(*, backend_lease_factory) -> None:
    """An extended-verb payload with no recoverable exchange still counts
    (conservative shared per-broker bucket), and still stamps the algo_id."""
    adapter, session = _FakeAdapter(), _session()
    guard = _guard(max_per_sec=2)
    router = _router(adapter, session, guard, backend_lease_factory=backend_lease_factory)
    payload1 = {"_op": "cancel_forever", "order_id": "GTT-1"}  # no exchange
    ctx1 = gate_broker_write("cancel_forever", payload1, _request_ctx(), "dhan", account_id="acct-1", backend_lease_proof=backend_lease_factory())
    await router.execute_gated(
        _request_ctx(), verb="cancel_forever", payload=payload1, safety_ctx=ctx1,
        adapter_id="dhan", account_id="acct-1",
    )
    assert session.algo_id == "ALGO-REG-1"
    assert guard.usage("dhan", "*") == 1


async def test_nested_exchange_is_recovered_from_the_payload(*, backend_lease_factory) -> None:
    adapter, session, guard = _FakeAdapter(), _session(), _guard()
    router = _router(adapter, session, guard, backend_lease_factory=backend_lease_factory)
    payload = {"_op": "cancel_forever", "order_id": "G1", "order": {"exchange": "BFO"}}
    ctx = gate_broker_write("cancel_forever", payload, _request_ctx(), "dhan", account_id="acct-1", backend_lease_proof=backend_lease_factory())
    await router.execute_gated(
        _request_ctx(), verb="cancel_forever", payload=payload, safety_ctx=ctx,
        adapter_id="dhan", account_id="acct-1",
    )
    assert guard.usage("dhan", "BFO") == 1
