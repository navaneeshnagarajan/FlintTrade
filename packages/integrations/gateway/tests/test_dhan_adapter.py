"""Tests for the Dhan adapter (mock dhanhq client; no SDK / creds needed)."""

from __future__ import annotations

import pytest

from flinttrade_core.models import Order
from flinttrade_engine.safety import SafetyBypassError
from flinttrade_gateway.brokers.dhan import DhanAdapter, _ROUTER_TOKEN

pytestmark = pytest.mark.unit


class MockDhan:
    """Stand-in for the synchronous dhanhq 2.2.0 client."""

    def __init__(self):
        self.calls: list[tuple] = []

    def place_order(self, **kw):
        self.calls.append(("place", kw))
        return {"status": "success", "data": {"orderId": "OID1", "orderStatus": "TRANSIT"}}

    def modify_order(self, **kw):
        self.calls.append(("modify", kw))
        return {"status": "success", "data": {"orderId": "OID1"}}

    def cancel_order(self, order_id):
        self.calls.append(("cancel", order_id))
        return {"status": "success", "data": {"orderId": order_id}}

    def get_order_list(self):
        return {"status": "success", "data": [
            {"orderId": "1", "tradingSymbol": "TCS", "exchangeSegment": "NSE_EQ",
             "transactionType": "BUY", "orderType": "LIMIT", "productType": "CNC",
             "orderStatus": "PENDING", "quantity": 5, "price": 3500},
        ]}

    def get_trade_book(self):
        return {"status": "success", "data": [
            {"orderId": "1", "tradingSymbol": "TCS", "exchangeSegment": "NSE_EQ",
             "transactionType": "BUY", "tradedQuantity": 5, "tradedPrice": 3499},
        ]}

    def get_positions(self):
        return {"status": "success", "data": [
            {"tradingSymbol": "INFY", "exchangeSegment": "NSE_EQ", "productType": "CNC",
             "netQty": 10, "costPrice": 1500},
        ]}

    def get_holdings(self):
        return {"status": "success", "data": [
            {"tradingSymbol": "SBIN", "exchange": "NSE", "totalQty": 50, "avgCostPrice": 600},
        ]}

    def get_fund_limits(self):
        return {"status": "success", "data": {"availabelBalance": 50000, "utilizedAmount": 12000}}


def _adapter(mock):
    return DhanAdapter(client_factory=lambda _s: mock, security_resolver=lambda s, e: "11536")


async def _session(adapter):
    return await adapter.login({"client_id": "C1", "access_token": "TOK"})


@pytest.mark.asyncio
async def test_login_returns_session():
    adapter = _adapter(MockDhan())
    session = await _session(adapter)
    assert session.adapter_id == "dhan"
    assert session.account_id == "C1"
    assert session.access_token == "TOK"


@pytest.mark.asyncio
async def test_login_requires_access_token():
    from flinttrade_core.exceptions import BrokerError

    with pytest.raises(BrokerError, match="access_token"):
        await DhanAdapter().login({"client_id": "C1"})


@pytest.mark.asyncio
async def test_place_order_is_gated():
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS", quantity="1")
    with pytest.raises(SafetyBypassError):
        await adapter.place_order(session, order)  # no router token
    assert mock.calls == []  # never reached the SDK


@pytest.mark.asyncio
async def test_place_order_with_router_token():
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT", product="CNC", quantity="3", price="2900")
    oid = await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert oid == "OID1"
    kind, kw = mock.calls[0]
    assert kind == "place"
    assert kw["security_id"] == "11536"
    assert kw["exchange_segment"] == "NSE_EQ"
    assert kw["order_type"] == "LIMIT"
    assert kw["product_type"] == "CNC"


@pytest.mark.asyncio
async def test_modify_and_cancel_gated_and_call_sdk():
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.modify_order(session, "OID1", {"quantity": 4, "price": 2950}, _router_token=_ROUTER_TOKEN)
    await adapter.cancel_order(session, "OID1", _router_token=_ROUTER_TOKEN)
    assert [c[0] for c in mock.calls] == ["modify", "cancel"]


@pytest.mark.asyncio
async def test_reads_map_correctly():
    adapter = _adapter(MockDhan())
    session = await _session(adapter)
    orders = await adapter.order_book(session)
    assert orders[0]["symbol"] == "TCS" and orders[0]["exchange"] == "NSE"
    positions = await adapter.positions(session)
    assert positions[0]["symbol"] == "INFY" and positions[0]["quantity"] == "10"
    trades = await adapter.trade_book(session)
    assert trades[0]["price"] == "3499"
    holdings = await adapter.holdings(session)
    assert holdings[0]["symbol"] == "SBIN"
    funds = await adapter.funds(session)
    assert funds["available_balance"] == "50000"


@pytest.mark.asyncio
async def test_unresolvable_symbol_raises():
    from flinttrade_core.exceptions import BrokerError

    adapter = DhanAdapter(client_factory=lambda _s: MockDhan())  # no resolver
    session = await _session(adapter)
    order = Order(symbol="OBSCURE", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS")
    with pytest.raises(BrokerError, match="security_id"):
        await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)


@pytest.mark.asyncio
async def test_index_fast_path_resolution():
    mock = MockDhan()
    adapter = DhanAdapter(client_factory=lambda _s: mock)  # no resolver — index fast path
    session = await _session(adapter)
    order = Order(symbol="NIFTY", action="BUY", exchange="NSE_INDEX", pricetype="MARKET", product="MIS", quantity="1")
    await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert mock.calls[0][1]["security_id"] == "13"  # NIFTY index id
