"""Tests for the Dhan adapter (mock dhanhq client; no SDK / creds needed)."""

from __future__ import annotations

import struct

import pytest

from flinttrade_core.models import Order
from flinttrade_engine.safety import SafetyBypassError
from flinttrade_gateway.brokers.dhan import DhanAdapter, _ROUTER_TOKEN

pytestmark = pytest.mark.unit


class MockHTTP:
    """Stand-in for the SDK's DhanHTTP transport (direct-endpoint paths)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self.responses: dict[tuple[str, str], dict] = {}

    def _respond(self, method: str, endpoint: str, payload: dict | None = None) -> dict:
        self.calls.append((method, endpoint, payload))
        return self.responses.get(
            (method, endpoint), {"status": "success", "data": {"orderId": "OID1", "orderStatus": "TRANSIT"}}
        )

    def get(self, endpoint):
        return self._respond("GET", endpoint)

    def post(self, endpoint, payload):
        return self._respond("POST", endpoint, payload)

    def put(self, endpoint, payload):
        return self._respond("PUT", endpoint, payload)

    def delete(self, endpoint):
        return self._respond("DELETE", endpoint)


class MockDhan:
    """Stand-in for the synchronous dhanhq 2.2.0 client."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.dhan_http = MockHTTP()

    def place_order(self, **kw):
        self.calls.append(("place", kw))
        return {"status": "success", "data": {"orderId": "OID1", "orderStatus": "TRANSIT"}}

    def place_super_order(self, **kw):
        self.calls.append(("super", kw))
        return {"status": "success", "data": {"orderId": "SUP1", "orderStatus": "TRANSIT"}}

    def place_slice_order(self, **kw):
        self.calls.append(("slice", kw))
        return {"status": "success", "data": {"orderId": "SLC1", "orderStatus": "TRANSIT"}}

    def place_forever(self, **kw):
        self.calls.append(("forever", kw))
        return {"status": "success", "data": {"orderId": "GTT1", "orderStatus": "TRANSIT"}}

    def margin_calculator(self, **kw):
        self.calls.append(("margin", kw))
        return {"status": "success", "data": {"totalMargin": 14500.0, "spanMargin": 12000.0,
                                              "exposureMargin": 2500.0, "availableBalance": 50000.0}}

    def expiry_list(self, under_security_id, under_exchange_segment):
        self.calls.append(("expiry", (under_security_id, under_exchange_segment)))
        return {"status": "success", "data": {"data": ["2026-06-26", "2026-07-31"]}}

    def kill_switch(self, action):
        self.calls.append(("kill", action))
        return {"status": "success", "data": {"killSwitchStatus": action}}

    def get_trade_history(self, from_date, to_date, page_number):
        self.calls.append(("trade_history", (from_date, to_date, page_number)))
        return {"status": "success", "data": [
            {"orderId": "1", "customSymbol": "TCS", "tradedQuantity": 5, "tradedPrice": 3499},
        ]}

    def ledger_report(self, from_date, to_date):
        self.calls.append(("ledger", (from_date, to_date)))
        return {"status": "success", "data": [{"voucherdate": "2026-06-01", "debit": 0, "credit": 5000}]}

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
async def test_bracket_order_dispatches_to_super_order():
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(
        symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT", product="MIS",
        quantity="5", price="2900", variety="bracket", target_price="2950", stop_loss_price="2870",
        trailing_jump="5",
    )
    oid = await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert oid == "SUP1"
    kind, kw = mock.calls[0]
    assert kind == "super"  # routed to place_super_order, not place_order
    assert kw["targetPrice"] == 2950.0 and kw["stopLossPrice"] == 2870.0 and kw["trailingJump"] == 5.0


@pytest.mark.asyncio
async def test_cover_order_has_stop_loss_only():
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(
        symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT", product="MIS",
        quantity="5", price="2900", variety="cover", target_price="2950", stop_loss_price="2870",
    )
    await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    kind, kw = mock.calls[0]
    assert kind == "super" and kw["stopLossPrice"] == 2870.0
    assert kw["targetPrice"] == 0.0  # cover orders drop the target leg


@pytest.mark.asyncio
async def test_iceberg_order_dispatches_to_slice_order():
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(symbol="RELIANCE", action="SELL", exchange="NSE", pricetype="LIMIT",
                  product="MIS", quantity="5000", price="2900", variety="iceberg")
    oid = await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert oid == "SLC1"
    assert mock.calls[0][0] == "slice"


@pytest.mark.asyncio
async def test_gtt_order_dispatches_to_place_forever():
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT", product="CNC",
                  quantity="5", price="2900", trigger_price="2890", variety="gtt")
    oid = await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert oid == "GTT1"
    kind, kw = mock.calls[0]
    assert kind == "forever" and kw["trigger_Price"] == 2890.0 and kw["order_flag"] == "SINGLE"


@pytest.mark.asyncio
async def test_gtt_oco_order_dispatches_to_place_forever_with_second_leg():
    """The OCO leg trio on a gtt Order flips the forever order to OCO and maps
    the forever.md price1/triggerPrice1/quantity1 fields — same gated method."""
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT", product="CNC",
                  quantity="5", price="2900", trigger_price="2890", variety="gtt",
                  price1="2800", trigger_price1="2805", quantity1="5")
    oid = await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert oid == "GTT1"
    kind, kw = mock.calls[0]
    assert kind == "forever" and kw["order_flag"] == "OCO"
    assert kw["price1"] == 2800.0 and kw["trigger_Price1"] == 2805.0 and kw["quantity1"] == 5


@pytest.mark.asyncio
async def test_gtt_partial_oco_leg_fails_closed():
    from flinttrade_gateway.brokers.dhan_mapping import DhanMappingError

    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT", product="CNC",
                  quantity="5", price="2900", trigger_price="2890", variety="gtt",
                  price1="2800")  # trigger_price1 + quantity1 missing
    with pytest.raises(DhanMappingError, match="OCO"):
        await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert mock.calls == []  # never reached the broker


@pytest.mark.asyncio
async def test_gtt_without_trigger_fails_closed():
    from flinttrade_gateway.brokers.dhan_mapping import DhanMappingError

    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT", product="CNC",
                  quantity="5", price="2900", variety="gtt")  # no trigger_price
    with pytest.raises(DhanMappingError, match="trigger_price"):
        await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert mock.calls == []  # never reached the broker


@pytest.mark.asyncio
async def test_advanced_order_still_requires_router_token():
    # The gating invariant must hold for EVERY variety, not just regular orders.
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT", product="MIS",
                  quantity="5", price="2900", variety="bracket", stop_loss_price="2870")
    with pytest.raises(SafetyBypassError):
        await adapter.place_order(session, order)  # no token
    assert mock.calls == []  # never reached the SDK


@pytest.mark.asyncio
async def test_amo_order_posts_orders_payload_with_amotime():
    """An ``amo`` variety POSTs /orders directly via DhanHTTP with
    afterMarketOrder + amoTime on the wire, instead of the SDK place_order
    (which drops amoTime). The SDK place_order is never touched."""
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="CNC", quantity="5", price="2900", variety="amo")
    oid = await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert oid == "OID1"
    assert mock.calls == []  # the SDK place_order endpoint was NOT used
    method, endpoint, payload = mock.dhan_http.calls[0]
    assert (method, endpoint) == ("POST", "/orders")
    assert payload["afterMarketOrder"] is True and payload["amoTime"] == "OPEN"


@pytest.mark.asyncio
async def test_amo_order_is_advertised_in_capabilities():
    # AMO is advertised in order_types, so dispatch must support it (regression:
    # it previously fell through to the unsupported-variety BrokerError).
    from flinttrade_gateway.brokers.dhan import DHAN_CAPABILITIES
    from flinttrade_gateway.capabilities import OrderTypes

    assert DHAN_CAPABILITIES.order_types & OrderTypes.AMO


@pytest.mark.asyncio
async def test_capabilities_historical_metadata_is_honest():
    """Regression: the 5000 candles-per-request cap was fabricated and 90 days is
    the per-request range, not the lookback (historical-data.md)."""
    from flinttrade_gateway.brokers.dhan import DHAN_CAPABILITIES

    assert DHAN_CAPABILITIES.historical_max_candles_per_request == 0  # unknown, not 5000
    # ~5 years of intraday history; 90 is the per-request range cap, not lookback.
    assert DHAN_CAPABILITIES.historical_max_lookback_days_intraday == 1825


@pytest.mark.asyncio
async def test_quotes_handle_double_nested_live_payload():
    """Regression: live quotes are double-wrapped (data.data.<SEGMENT>); the
    adapter must still surface a Quote (market-quote.md doc-exact envelope)."""
    class _DoubleWrapped(MockDhan):
        def quote_data(self, securities):
            return {"status": "success", "data": {"data": {"NSE_EQ": {"11536": {
                "last_price": 4525.55,
                "ohlc": {"open": 4521.45, "close": 4507.85, "high": 4530, "low": 4500},
                "oi": 0, "volume": 0,
            }}}, "status": "success"}}

    adapter = _adapter(_DoubleWrapped())
    session = await _session(adapter)
    quotes = await adapter.quotes(session, ["NSE:RELIANCE"])
    assert len(quotes) == 1
    assert quotes[0].ltp == 4525.55 and quotes[0].open == 4521.45


@pytest.mark.asyncio
async def test_option_chain_handles_double_nested_live_payload():
    """Regression: live option chain is data.data.{oc} (option-chain.md); the
    adapter must return non-empty strikes through the double-nest."""
    class _DoubleWrapped(MockDhan):
        def option_chain(self, under_security_id, under_exchange_segment, expiry):
            return {"status": "success", "data": {"data": {"last_price": 25642.8, "oc": {
                "25650.000000": {
                    "ce": {"last_price": 134, "oi": 3786445, "greeks": {"delta": 0.53871}},
                    "pe": {"last_price": 132.8, "oi": 3096145, "greeks": {"delta": -0.46732}},
                },
            }}, "status": "success"}}

    adapter = DhanAdapter(client_factory=lambda _s: _DoubleWrapped())  # NIFTY index fast path
    session = await _session(adapter)
    oc = await adapter.option_chain(session, {"symbol": "NIFTY", "exchange": "NSE_INDEX",
                                              "expiry": "2026-06-25"})
    assert len(oc.strikes) == 1
    assert oc.strikes[0].strike_price == 25650.0 and oc.strikes[0].ce_ltp == 134.0


@pytest.mark.asyncio
async def test_unsupported_variety_raises():
    from flinttrade_core.exceptions import BrokerError

    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(symbol="X", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS", quantity="1")
    object.__setattr__(order, "variety", "exotic")
    with pytest.raises(BrokerError, match="variety"):
        await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)


@pytest.mark.asyncio
async def test_margin_calculator_reads_estimate():
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="MIS", quantity="10", price="2900")
    # No router token needed — margin calc is a read-only pre-trade estimate.
    margin = await adapter.margin_calculator(session, order)
    assert margin["total_margin"] == "14500.0" and margin["available_balance"] == "50000.0"
    assert mock.calls[0][0] == "margin"


@pytest.mark.asyncio
async def test_expiry_list_returns_dates():
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    expiries = await adapter.expiry_list(session, "NIFTY", "NSE_INDEX")
    assert expiries == ["2026-06-26", "2026-07-31"]


@pytest.mark.asyncio
async def test_trade_history_and_ledger_reads():
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    trades = await adapter.trade_history(session, "2026-06-01", "2026-06-05", 0)
    assert len(trades) == 1 and trades[0]["customSymbol"] == "TCS"
    assert mock.calls[0] == ("trade_history", ("2026-06-01", "2026-06-05", 0))
    ledger = await adapter.ledger(session, "2026-06-01", "2026-06-05")
    assert len(ledger) == 1 and ledger[0]["credit"] == 5000


@pytest.mark.asyncio
async def test_kill_switch_validates_and_relays():
    from flinttrade_core.exceptions import BrokerError

    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    resp = await adapter.kill_switch(session, "activate")  # case-insensitive
    assert resp["killSwitchStatus"] == "ACTIVATE"
    assert mock.calls[0] == ("kill", "ACTIVATE")
    with pytest.raises(BrokerError, match="ACTIVATE or DEACTIVATE"):
        await adapter.kill_switch(session, "maybe")


@pytest.mark.asyncio
async def test_kill_switch_non_dict_response_fallback():
    class _ScalarKill(MockDhan):
        def kill_switch(self, action):
            return "ACTIVATED"  # some builds return a bare string

    adapter = _adapter(_ScalarKill())
    session = await _session(adapter)
    resp = await adapter.kill_switch(session, "ACTIVATE")
    assert resp == {"status": "ACTIVATED"}  # wrapped, not crashed


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
