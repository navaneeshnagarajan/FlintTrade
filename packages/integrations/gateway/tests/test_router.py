"""BrokerRouter safety-enforcement tests (broker-adapter-contract §8).

The router must refuse to dispatch a broker write unless the presented
SafetyContext verifies against THIS order / mode / jti / actor / resolved
adapter (contract §8.0) and its one-shot gate has not already been consumed.
"""

from __future__ import annotations

import types
from datetime import datetime, timezone

import pytest

from flinttrade_core.exceptions import SafetyBypassError
from flinttrade_engine.request_context import RequestContext
from flinttrade_engine.safety import SafetyContext, set_safety_gate_secret
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.dhan import _ROUTER_TOKEN
from flinttrade_gateway.router import BrokerRouter

SECRET = b"0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def _bind_secret() -> None:
    set_safety_gate_secret(SECRET)


class _FakeAdapter:
    """Minimal adapter that only fires when handed the router token."""

    def __init__(self) -> None:
        self.placed: list[object] = []

    async def place_order(self, session, order, *, _router_token=None):
        if _router_token is not _ROUTER_TOKEN:
            raise SafetyBypassError("adapter write method called outside BrokerRouter")
        self.placed.append(order)
        return "BROKER-OID-1"


def _session(read_only: bool = False) -> Session:
    return Session(
        access_token="tok",
        expires_at=datetime.now(tz=timezone.utc).timestamp() + 3600,
        account_id="acct-1",
        adapter_id="dhan",
        read_only_until_at=(datetime.now(tz=timezone.utc).timestamp() + 3600) if read_only else None,
    )


def _order(symbol: str = "RELIANCE") -> object:
    return types.SimpleNamespace(symbol=symbol, quantity=10, side="BUY", exchange="NSE")


def _request_ctx() -> RequestContext:
    return RequestContext(jti="jti-1", actor_type="human", actor_id="user-1", mode="live")


def _router(adapter: _FakeAdapter, *, read_only: bool = False, consume_gate=None) -> BrokerRouter:
    return BrokerRouter(
        {"dhan": adapter},
        lambda _ctx, _aid, _acct: _session(read_only=read_only),
        consume_gate=consume_gate,
    )


def _mint(order, **over) -> SafetyContext:
    kwargs = dict(mode="live", user_jti="jti-1", adapter_id="dhan", account_id="acct-1", actor_type="human")
    kwargs.update(over)
    return SafetyContext.mint(order, **kwargs)


async def test_place_order_dispatches_with_valid_context() -> None:
    adapter = _FakeAdapter()
    router = _router(adapter)
    order = _order()
    ctx = _mint(order)
    result = await router.place_order(
        _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=ctx
    )
    assert result == "BROKER-OID-1"
    assert adapter.placed == [order]


async def test_place_order_rejects_adapter_mismatch() -> None:
    """A ctx minted for 'dhan' must not fire when the order resolves to 'upstox'."""
    adapter = _FakeAdapter()
    router = BrokerRouter(
        {"dhan": adapter, "upstox": adapter},
        lambda _ctx, _aid, _acct: _session(),
    )
    order = _order()
    ctx = _mint(order, adapter_id="dhan")
    with pytest.raises(SafetyBypassError, match="verification failed"):
        await router.place_order(
            _request_ctx(), adapter_id="upstox", account_id="acct-1", order=order, safety_ctx=ctx
        )
    assert adapter.placed == []


async def test_place_order_rejects_consumed_gate() -> None:
    adapter = _FakeAdapter()
    router = _router(adapter, consume_gate=lambda _gate_id: False)
    order = _order()
    ctx = _mint(order)
    with pytest.raises(SafetyBypassError, match="already consumed"):
        await router.place_order(
            _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=ctx
        )
    assert adapter.placed == []


async def test_place_order_rejects_read_only_session() -> None:
    adapter = _FakeAdapter()
    router = _router(adapter, read_only=True)
    order = _order()
    ctx = _mint(order)
    with pytest.raises(SafetyBypassError, match="read-only"):
        await router.place_order(
            _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=ctx
        )
    assert adapter.placed == []


async def test_gate_consumed_exactly_once() -> None:
    """Second dispatch of the same gate_id must fail (one-shot)."""
    adapter = _FakeAdapter()
    consumed: set[str] = set()

    def consume(gate_id: str) -> bool:
        if gate_id in consumed:
            return False
        consumed.add(gate_id)
        return True

    router = _router(adapter, consume_gate=consume)
    order = _order()
    ctx = _mint(order)
    assert await router.place_order(
        _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=ctx
    ) == "BROKER-OID-1"
    with pytest.raises(SafetyBypassError, match="already consumed"):
        await router.place_order(
            _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=ctx
        )
    assert adapter.placed == [order]
