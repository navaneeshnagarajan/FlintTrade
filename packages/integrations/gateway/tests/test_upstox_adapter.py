"""Tests for the Upstox adapter (mock facade; no SDK / creds needed)."""

from __future__ import annotations

import pytest

from flinttrade_core.exceptions import BrokerError
from flinttrade_core.models import Order
from flinttrade_engine.safety import SafetyBypassError
from flinttrade_gateway.brokers.upstox import UpstoxAdapter, _ROUTER_TOKEN

pytestmark = pytest.mark.unit


class MockUpstox:
    """Stand-in for the UpstoxClient facade."""

    def __init__(self):
        self.calls: list[tuple] = []

    def place_order(self, params):
        self.calls.append(("place", params))
        return {"status": "success", "data": {"order_ids": ["UOID1"]}}

    def modify_order(self, params):
        self.calls.append(("modify", params))
        return {"status": "success", "data": {"order_id": "UOID1"}}

    def cancel_order(self, order_id):
        self.calls.append(("cancel", order_id))
        return {"status": "success", "data": {"order_id": order_id}}

    def order_book(self):
        return {"status": "success", "data": [
            {"order_id": "1", "trading_symbol": "TCS", "instrument_token": "NSE_EQ|INE467B01029",
             "transaction_type": "BUY", "order_type": "LIMIT", "product": "D", "quantity": 5, "price": 3500, "status": "open"},
        ]}

    def trade_book(self):
        return {"status": "success", "data": [
            {"order_id": "1", "trading_symbol": "TCS", "instrument_token": "NSE_EQ|INE467B01029",
             "transaction_type": "BUY", "quantity": 5, "average_price": 3499},
        ]}

    def positions(self):
        return {"status": "success", "data": [
            {"trading_symbol": "INFY", "instrument_token": "NSE_EQ|INE009A01021", "product": "I",
             "quantity": 10, "average_price": 1500, "last_price": 1520, "pnl": 200},
        ]}

    def holdings(self):
        return {"status": "success", "data": [
            {"trading_symbol": "SBIN", "exchange": "NSE", "quantity": 50, "average_price": 600},
        ]}

    def funds(self):
        return {"status": "success", "data": {"equity": {"available_margin": 50000, "used_margin": 12000}}}


def _adapter(mock):
    return UpstoxAdapter(client_factory=lambda _s: mock, instrument_resolver=lambda s, e: "NSE_EQ|INE002A01018")


async def _session(adapter):
    return await adapter.login({"client_id": "C1", "access_token": "TOK"})


@pytest.mark.asyncio
async def test_login_returns_session():
    session = await _session(_adapter(MockUpstox()))
    assert session.adapter_id == "upstox" and session.access_token == "TOK"


@pytest.mark.asyncio
async def test_login_requires_access_token():
    with pytest.raises(BrokerError, match="access_token"):
        await UpstoxAdapter().login({"client_id": "C1"})


@pytest.mark.asyncio
async def test_place_order_is_gated():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS", quantity="1")
    with pytest.raises(SafetyBypassError):
        await adapter.place_order(session, order)
    assert mock.calls == []


@pytest.mark.asyncio
async def test_place_order_with_router_token():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT", product="CNC", quantity="3", price="2900")
    oid = await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert oid == "UOID1"
    kind, params = mock.calls[0]
    assert kind == "place"
    assert params["instrument_token"] == "NSE_EQ|INE002A01018"
    assert params["order_type"] == "LIMIT" and params["product"] == "D"


@pytest.mark.asyncio
async def test_modify_and_cancel():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.modify_order(session, "UOID1", {"quantity": 4, "price": 2950}, _router_token=_ROUTER_TOKEN)
    await adapter.cancel_order(session, "UOID1", _router_token=_ROUTER_TOKEN)
    assert [c[0] for c in mock.calls] == ["modify", "cancel"]


@pytest.mark.asyncio
async def test_reads_map_correctly():
    adapter = _adapter(MockUpstox())
    session = await _session(adapter)
    orders = await adapter.order_book(session)
    assert orders[0]["symbol"] == "TCS" and orders[0]["exchange"] == "NSE" and orders[0]["product"] == "CNC"
    positions = await adapter.positions(session)
    assert positions[0]["symbol"] == "INFY" and positions[0]["product"] == "MIS"
    funds = await adapter.funds(session)
    assert funds["available_balance"] == "50000"


@pytest.mark.asyncio
async def test_unresolvable_instrument_raises():
    from flinttrade_core.exceptions import BrokerError

    adapter = UpstoxAdapter(client_factory=lambda _s: MockUpstox())  # no resolver
    session = await _session(adapter)
    order = Order(symbol="OBSCURE", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS")
    with pytest.raises(BrokerError, match="instrument_token"):
        await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
