"""Regression: every native adapter honours the ONE router token (§8.0c).

Guards the bug where Upstox / Kotak Neo minted their own ``_ROUTER_TOKEN``: the
``BrokerRouter`` passes a single shared token on every write, and an adapter that
checks against a different ``object()`` would reject every legitimate gated order
with ``SafetyBypassError`` the moment it went live. These tests drive the REAL
``BrokerRouter`` into the REAL native adapters (mock broker clients) and assert
the broker is actually called — not a re-exported per-module token.
"""

from __future__ import annotations

import pytest

from flinttrade_core.models import Order
from flinttrade_engine.request_context import RequestContext
from flinttrade_engine.safety import SafetyContext, set_safety_gate_secret
from flinttrade_gateway.brokers import _base, dhan, kotakneo, openalgo, upstox
from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
from flinttrade_gateway.brokers.upstox import UpstoxAdapter
from flinttrade_gateway.router import BrokerRouter
from flinttrade_gateway import router as router_mod

pytestmark = pytest.mark.unit

SECRET = b"0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def _bind_secret() -> None:
    set_safety_gate_secret(SECRET)


def test_all_adapters_and_router_share_one_token():
    """The canonical token lives in _base; everyone re-exports the SAME object."""
    tok = _base.ROUTER_TOKEN
    assert dhan._ROUTER_TOKEN is tok
    assert upstox._ROUTER_TOKEN is tok
    assert kotakneo._ROUTER_TOKEN is tok
    assert openalgo._ROUTER_TOKEN is tok
    assert router_mod._ROUTER_TOKEN is tok


class _MockUpClient:
    def __init__(self):
        self.placed = []

    def place_order(self, params):
        self.placed.append(params)
        return {"status": "success", "data": {"order_ids": ["UOID-ROUTER"]}}


class _MockNeoClient:
    def __init__(self):
        self.placed = []

    def place_order(self, params):
        self.placed.append(params)
        return {"stat": "Ok", "nOrdNo": "NEO-ROUTER", "stCode": 200}


def _order() -> Order:
    return Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT", product="CNC",
                 quantity="1", price="2900")


def _ctx() -> RequestContext:
    return RequestContext(jti="jti-1", actor_type="human", actor_id="user-1", mode="live")


async def _dispatch_through_router(adapter, adapter_id: str):
    session = await adapter.login(_login_creds(adapter_id))
    router = BrokerRouter(
        {adapter_id: adapter},
        lambda _ctx, _aid, _acct: session,
    )
    order = _order()
    ctx = SafetyContext.mint(
        order, mode="live", user_jti="jti-1", adapter_id=adapter_id, account_id="acct-1", actor_type="human",
    )
    return await router.place_order(
        _ctx(), adapter_id=adapter_id, account_id="acct-1", order=order, safety_ctx=ctx
    )


def _login_creds(adapter_id: str) -> dict:
    if adapter_id == "upstox":
        return {"client_id": "C", "access_token": "T"}
    return {"consumer_key": "CK", "mobile_number": "+91", "ucc": "U1", "mpin": "1234", "totp": "000000"}


@pytest.mark.asyncio
async def test_upstox_write_accepted_through_real_router():
    client = _MockUpClient()
    adapter = UpstoxAdapter(client_factory=lambda _s: client, instrument_resolver=lambda s, e: "NSE_EQ|INE002A01018")
    oid = await _dispatch_through_router(adapter, "upstox")
    assert oid == "UOID-ROUTER"
    assert len(client.placed) == 1  # the broker WAS called — no SafetyBypassError


@pytest.mark.asyncio
async def test_kotakneo_write_accepted_through_real_router():
    client = _MockNeoClient()
    adapter = KotakNeoAdapter(client_factory=lambda _s: client, symbol_resolver=lambda s, e: "RELIANCE-EQ")
    oid = await _dispatch_through_router(adapter, "kotakneo")
    assert oid == "NEO-ROUTER"
    assert len(client.placed) == 1


@pytest.mark.asyncio
async def test_bare_native_write_without_token_still_raises():
    """The shared token must not weaken the guard: a bare call still fails-closed."""
    from flinttrade_engine.safety import SafetyBypassError

    client = _MockUpClient()
    adapter = UpstoxAdapter(client_factory=lambda _s: client, instrument_resolver=lambda s, e: "NSE_EQ|X")
    session = await adapter.login(_login_creds("upstox"))
    with pytest.raises(SafetyBypassError):
        await adapter.place_order(session, _order())  # no _router_token
    assert client.placed == []
