"""OpenAlgo bridge adapter — forwards the gated router to OpenAlgo (contract §5).

Verifies the §8 router-token guard on writes, faithful forwarding to the
OpenAlgo client, order-id extraction + rejection, honest UnsupportedCapability
for streaming/reconcile, and broker-error-taxonomy mapping.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from flinttrade_core.exceptions import (
    OpenAlgoRateLimitError,
    OrderRejectedByBroker,
    RateLimitError,
    SafetyBypassError,
    UnsupportedCapabilityError,
)
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.dhan import _ROUTER_TOKEN
from flinttrade_gateway.brokers.openalgo import OpenAlgoAdapter


class _FakeClient:
    """Minimal async stand-in for OpenAlgoClient."""

    def __init__(self, *, place_status: str = "success", raise_exc: Exception | None = None) -> None:
        self.calls: list[tuple] = []
        self._place_status = place_status
        self._raise = raise_exc

    async def place_order(self, order):
        self.calls.append(("place_order", order))
        if self._raise:
            raise self._raise
        return SimpleNamespace(status=self._place_status, orderid="OID-1")

    async def modify_order(self, modify):
        self.calls.append(("modify_order", modify))
        return SimpleNamespace(status="success", orderid=modify.orderid)

    async def cancel_order(self, order_id, strategy="Flint"):
        self.calls.append(("cancel_order", order_id, strategy))
        return SimpleNamespace(status="success", orderid=order_id)

    async def positionbook(self):
        self.calls.append(("positionbook",))
        return [{"symbol": "RELIANCE", "qty": 10}]

    async def funds(self):
        return {"available": 50000.0}

    async def multi_quotes(self, payload):
        self.calls.append(("multi_quotes", payload))
        return [{"symbol": p["symbol"], "ltp": 100.0} for p in payload]


def _adapter(client: _FakeClient) -> OpenAlgoAdapter:
    return OpenAlgoAdapter(default_client=client)


def _session() -> Session:
    return Session(access_token="api-key-1", expires_at=4_102_444_800.0, account_id="dhan", adapter_id="openalgo")


def _order() -> object:
    return SimpleNamespace(symbol="RELIANCE", exchange="NSE", action="BUY", quantity=10, pricetype="MARKET")


def test_identity_and_capabilities() -> None:
    a = _adapter(_FakeClient())
    assert a.broker_id == "openalgo"
    assert a.capabilities.streaming_supported is False  # the REST bridge does not stream
    assert a.capabilities.algo_tag_required is False


async def test_login_builds_session_from_api_key() -> None:
    s = await _adapter(_FakeClient()).login({"api_key": "K", "account_id": "dhan", "host": "http://x"})
    assert s.access_token == "K"
    assert s.account_id == "dhan"
    assert s.adapter_id == "openalgo"
    assert s.extra["host"] == "http://x"


async def test_place_order_requires_router_token() -> None:
    a = _adapter(_FakeClient())
    with pytest.raises(SafetyBypassError, match="outside BrokerRouter"):
        await a.place_order(_session(), _order())  # no token


async def test_modify_order_requires_router_token() -> None:
    # The §8 guard must reject a tokenless modify before any OpenAlgo request,
    # so the FakeClient records nothing (mirrors place_order's rejection arm).
    client = _FakeClient()
    a = _adapter(client)
    with pytest.raises(SafetyBypassError, match="outside BrokerRouter"):
        await a.modify_order(_session(), "OID-1", {"price": 1.0})  # no token
    assert client.calls == []  # the guard short-circuits ahead of the client


async def test_cancel_order_requires_router_token() -> None:
    # As above for cancel: a tokenless cancel must raise before the client runs.
    client = _FakeClient()
    a = _adapter(client)
    with pytest.raises(SafetyBypassError, match="outside BrokerRouter"):
        await a.cancel_order(_session(), "OID-9")  # no token
    assert client.calls == []  # the guard short-circuits ahead of the client


async def test_place_order_forwards_and_returns_id() -> None:
    client = _FakeClient()
    a = _adapter(client)
    oid = await a.place_order(_session(), _order(), _router_token=_ROUTER_TOKEN)
    assert oid == "OID-1"
    assert client.calls[0][0] == "place_order"


async def test_place_order_rejection_raises() -> None:
    a = _adapter(_FakeClient(place_status="error"))
    with pytest.raises(OrderRejectedByBroker):
        await a.place_order(_session(), _order(), _router_token=_ROUTER_TOKEN)


async def test_cancel_order_forwards_with_strategy() -> None:
    client = _FakeClient()
    a = _adapter(client)
    await a.cancel_order(_session(), "OID-9", _router_token=_ROUTER_TOKEN)
    assert ("cancel_order", "OID-9", "Flint") in client.calls


async def test_reads_forward() -> None:
    a = _adapter(_FakeClient())
    pos = await a.positions(_session())
    assert pos == [{"symbol": "RELIANCE", "qty": 10}]
    assert await a.funds(_session()) == {"available": 50000.0}


async def test_quotes_split_symbols() -> None:
    client = _FakeClient()
    a = _adapter(client)
    await a.quotes(_session(), ["NFO:NIFTY", "RELIANCE"])
    _, payload = client.calls[-1]
    assert payload == [{"symbol": "NIFTY", "exchange": "NFO"}, {"symbol": "RELIANCE", "exchange": "NSE"}]


async def test_streaming_and_reconcile_unsupported() -> None:
    a = _adapter(_FakeClient())
    with pytest.raises(UnsupportedCapabilityError):
        a.stream(_session())
    with pytest.raises(UnsupportedCapabilityError):
        await a.subscribe(_session(), ["X"])
    with pytest.raises(UnsupportedCapabilityError):
        await a.reconcile(_session())


async def test_rate_limit_error_mapped() -> None:
    a = _adapter(_FakeClient(raise_exc=OpenAlgoRateLimitError("429")))
    with pytest.raises(RateLimitError):
        await a.place_order(_session(), _order(), _router_token=_ROUTER_TOKEN)
