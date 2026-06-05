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

    def full_quote(self, instrument_keys):
        self.calls.append(("full_quote", instrument_keys))
        return {"status": "success", "data": {
            "NSE_EQ:RELIANCE": {
                "symbol": "RELIANCE", "instrument_token": "NSE_EQ|INE002A01018", "last_price": 2905.5,
                "volume": 120000, "oi": 0, "ohlc": {"open": 2900, "high": 2920, "low": 2890, "close": 2899},
                "depth": {"buy": [{"price": 2905.0, "quantity": 10}], "sell": [{"price": 2906.0, "quantity": 8}]},
            },
        }}

    def historical(self, instrument_key, unit, interval, to_date, from_date):
        self.calls.append(("historical", (instrument_key, unit, interval, to_date, from_date)))
        return {"status": "success", "data": {"candles": [
            ["2025-01-02T00:00:00+05:30", 100.0, 110.0, 95.0, 105.0, 1500, 0],
        ]}}

    def option_chain(self, instrument_key, expiry_date):
        self.calls.append(("option_chain", (instrument_key, expiry_date)))
        return {"status": "success", "data": [
            {"strike_price": 24000,
             "call_options": {"market_data": {"ltp": 120.5, "oi": 30000, "volume": 5000, "bid_price": 120.0, "ask_price": 121.0},
                              "option_greeks": {"iv": 13.2, "delta": 0.55, "gamma": 0.002, "theta": -8.1, "vega": 6.4}},
             "put_options": {"market_data": {"ltp": 95.0, "oi": 28000, "volume": 4200, "bid_price": 94.5, "ask_price": 95.5},
                             "option_greeks": {"iv": 12.8, "delta": -0.45, "gamma": 0.002, "theta": -7.5, "vega": 6.1}}},
        ]}


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


@pytest.mark.asyncio
async def test_quotes_maps_full_quote():
    adapter = _adapter(MockUpstox())
    session = await _session(adapter)
    quotes = await adapter.quotes(session, ["NSE:RELIANCE"])
    assert len(quotes) == 1
    q = quotes[0]
    assert q.symbol == "RELIANCE" and q.exchange == "NSE"
    assert q.ltp == 2905.5 and q.bid == 2905.0 and q.ask == 2906.0


@pytest.mark.asyncio
async def test_historical_builds_candles():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    candles = await adapter.historical(session, {"symbol": "RELIANCE", "exchange": "NSE", "interval": "15m",
                                                 "from_date": "2025-01-01", "to_date": "2025-01-04"})
    assert candles.symbol == "RELIANCE" and candles.interval == "15m"
    assert len(candles.bars) == 1 and candles.bars[0].close == 105.0
    # v3 history called with (unit, interval) = (minutes, 15)
    _, args = [c for c in mock.calls if c[0] == "historical"][0]
    assert args[1] == "minutes" and args[2] == "15"


@pytest.mark.asyncio
async def test_option_chain_builds_strikes():
    adapter = _adapter(MockUpstox())
    session = await _session(adapter)
    chain = await adapter.option_chain(session, {"symbol": "NIFTY", "exchange": "NSE_INDEX", "expiry": "2025-06-26"})
    assert chain.underlying == "NIFTY" and len(chain.strikes) == 1
    s = chain.strikes[0]
    assert s.strike_price == 24000.0 and s.ce_ltp == 120.5 and s.pe_delta == -0.45


@pytest.mark.asyncio
async def test_stream_still_pending():
    adapter = _adapter(MockUpstox())
    session = await _session(adapter)
    with pytest.raises(NotImplementedError, match="stream"):
        adapter.stream(session)
