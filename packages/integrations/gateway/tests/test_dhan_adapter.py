"""Tests for the Dhan adapter (mock dhanhq client; no SDK / creds needed)."""

from __future__ import annotations

import struct

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

    def quote_data(self, securities):
        self.calls.append(("quote", securities))
        return {"status": "success", "data": {"NSE_EQ": {"11536": {
            "last_price": 2901.5, "ohlc": {"open": 2890, "high": 2910, "low": 2885, "close": 2888},
            "volume": 1_200_000,
        }}}}

    def intraday_minute_data(self, security_id, exchange_segment, instrument_type, from_date, to_date, interval=1, oi=False):
        self.calls.append(("intraday", security_id, interval))
        return {"status": "success", "data": {
            "open": [100, 101], "high": [102, 103], "low": [99, 100],
            "close": [101, 102], "volume": [1000, 1500], "timestamp": [1, 2],
        }}

    def historical_daily_data(self, security_id, exchange_segment, instrument_type, from_date, to_date, expiry_code=0, oi=False):
        self.calls.append(("daily", security_id))
        return {"status": "success", "data": {
            "open": [100], "high": [102], "low": [99], "close": [101], "volume": [1000], "timestamp": [1],
        }}

    def option_chain(self, under_security_id, under_exchange_segment, expiry):
        self.calls.append(("option_chain", under_security_id, expiry))
        return {"status": "success", "data": {"oc": {"24000.000000": {
            "ce": {"last_price": 150, "oi": 1000, "greeks": {"delta": 0.5}},
            "pe": {"last_price": 140, "oi": 1200, "greeks": {"delta": -0.5}},
        }}}}


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
async def test_quotes_map_to_models():
    adapter = _adapter(MockDhan())
    session = await _session(adapter)
    quotes = await adapter.quotes(session, ["NSE:RELIANCE"])
    assert len(quotes) == 1
    assert quotes[0].symbol == "RELIANCE"
    assert quotes[0].ltp == 2901.5
    assert quotes[0].open == 2890.0


@pytest.mark.asyncio
async def test_historical_intraday_and_daily():
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    intraday = await adapter.historical(
        session, {"symbol": "RELIANCE", "exchange": "NSE", "interval": "5m", "from_date": "2026-06-01", "to_date": "2026-06-05"}
    )
    assert intraday.symbol == "RELIANCE" and len(intraday.bars) == 2
    assert intraday.bars[0].open == 100.0
    assert ("intraday", "11536", 5) in mock.calls

    daily = await adapter.historical(
        session, {"symbol": "RELIANCE", "exchange": "NSE", "interval": "D", "from_date": "2026-01-01", "to_date": "2026-06-05"}
    )
    assert len(daily.bars) == 1
    assert any(c[0] == "daily" for c in mock.calls)


@pytest.mark.asyncio
async def test_option_chain_maps_to_model():
    mock = MockDhan()
    adapter = _adapter(mock)  # NIFTY/NSE_INDEX uses the index fast path
    session = await _session(adapter)
    oc = await adapter.option_chain(session, {"symbol": "NIFTY", "exchange": "NSE_INDEX", "expiry": "2026-06-25"})
    assert oc.underlying == "NIFTY"
    assert len(oc.strikes) == 1
    assert oc.strikes[0].strike_price == 24000.0
    assert oc.strikes[0].ce_ltp == 150.0 and oc.strikes[0].pe_oi == 1200
    assert ("option_chain", "13", "2026-06-25") in mock.calls  # NIFTY index id


@pytest.mark.asyncio
async def test_subscribe_builds_feed_map_and_stream_yields_ticks():
    frames = [struct.pack("<BHBIfI", 15, 16, 1, 11536, 2901.5, 1)]

    async def fake_feed(_session):
        for frame in frames:
            yield frame

    adapter = DhanAdapter(
        client_factory=lambda _s: MockDhan(),
        security_resolver=lambda s, e: "11536",
        feed_factory=fake_feed,
    )
    session = await _session(adapter)
    await adapter.subscribe(session, ["NSE:RELIANCE"])
    assert adapter._feed_map["11536"] == ("RELIANCE", "NSE")

    ticks = [t async for t in adapter.stream(session)]
    assert len(ticks) == 1
    assert ticks[0].symbol == "RELIANCE"
    assert ticks[0].ltp == 2901.5


@pytest.mark.asyncio
async def test_unsubscribe_removes_from_feed_map():
    adapter = _adapter(MockDhan())
    session = await _session(adapter)
    await adapter.subscribe(session, ["NSE:RELIANCE"])
    assert "11536" in adapter._feed_map
    await adapter.unsubscribe(session, ["NSE:RELIANCE"])
    assert "11536" not in adapter._feed_map


@pytest.mark.asyncio
async def test_index_fast_path_resolution():
    mock = MockDhan()
    adapter = DhanAdapter(client_factory=lambda _s: mock)  # no resolver — index fast path
    session = await _session(adapter)
    order = Order(symbol="NIFTY", action="BUY", exchange="NSE_INDEX", pricetype="MARKET", product="MIS", quantity="1")
    await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert mock.calls[0][1]["security_id"] == "13"  # NIFTY index id
