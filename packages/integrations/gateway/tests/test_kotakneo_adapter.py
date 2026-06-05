"""Tests for the Kotak Neo adapter (mock facade; no SDK / creds needed)."""

from __future__ import annotations

import pytest

from flinttrade_core.exceptions import BrokerError
from flinttrade_core.models import Order
from flinttrade_engine.safety import SafetyBypassError
from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter, _ROUTER_TOKEN

pytestmark = pytest.mark.unit


class MockNeo:
    """Stand-in for the KotakNeoClient facade."""

    def __init__(self):
        self.calls: list[tuple] = []

    def place_order(self, params):
        self.calls.append(("place", params))
        return {"stat": "Ok", "nOrdNo": "250122000612876", "stCode": 200}

    def modify_order(self, params):
        self.calls.append(("modify", params))
        return {"stat": "Ok", "nOrdNo": "250122000612876", "stCode": 200}

    def cancel_order(self, order_id):
        self.calls.append(("cancel", order_id))
        return {"stat": "Ok", "nOrdNo": order_id, "stCode": 200}

    def order_book(self):
        return {"stat": "Ok", "data": [
            {"nOrdNo": "1", "ordSt": "open", "trdSym": "IDEA-EQ", "exSeg": "nse_cm",
             "trnsTp": "B", "prcTp": "L", "prod": "NRML", "qty": 1, "prc": "9.39"},
        ]}

    def trade_book(self):
        return {"stat": "Ok", "data": [
            {"nOrdNo": "1", "trdSym": "IDEA-EQ", "exSeg": "nse_cm", "trnsTp": "B",
             "fldQty": 1, "avgPrc": "9.39", "prod": "NRML"},
        ]}

    def positions(self):
        return {"stat": "ok", "stCode": 200, "data": [
            {"trdSym": "IDEA-EQ", "exSeg": "nse_cm", "prod": "MIS",
             "flBuyQty": 10, "flSellQty": 0, "buyAmt": 1000, "sellAmt": 0},
        ]}

    def holdings(self):
        return {"stat": "Ok", "data": [
            {"displaySymbol": "SBIN", "exchangeSegment": "nse_cm", "quantity": 50,
             "averagePrice": 600, "closingPrice": 620},
        ]}

    def funds(self):
        # Real limits() shape: flat, keyed Net / MarginUsed / CollateralValue.
        return {"CollateralValue": "38.19", "MarginUsed": "18.78", "Net": "19.41", "stat": "Ok"}

    def quotes(self, instrument_tokens):
        self.calls.append(("quotes", instrument_tokens))
        return {"stat": "Ok", "data": [
            {"trading_symbol": "IDEA-EQ", "exchange_segment": "nse_cm", "last_traded_price": 9.4,
             "open": 9.2, "high": 9.6, "low": 9.1, "close": 9.3, "volume": 1000000,
             "buy_price": 9.39, "sell_price": 9.41},
        ]}


def _adapter(mock):
    return KotakNeoAdapter(client_factory=lambda _s: mock, symbol_resolver=lambda s, e: "IDEA-EQ")


async def _session(adapter):
    return await adapter.login(
        {"consumer_key": "CK", "mobile_number": "+91...", "ucc": "U1", "mpin": "1234", "totp": "000000"}
    )


@pytest.mark.asyncio
async def test_login_returns_session():
    session = await _session(_adapter(MockNeo()))
    assert session.adapter_id == "kotakneo" and session.account_id == "U1"


@pytest.mark.asyncio
async def test_login_requires_core_credentials():
    with pytest.raises(BrokerError, match="consumer_key"):
        await KotakNeoAdapter().login({"ucc": "U1", "mpin": "1234", "mobile_number": "x"})


@pytest.mark.asyncio
async def test_place_order_is_gated():
    mock = MockNeo()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(symbol="IDEA", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS", quantity="1")
    with pytest.raises(SafetyBypassError):
        await adapter.place_order(session, order)
    assert mock.calls == []


@pytest.mark.asyncio
async def test_bracket_order_flows_through_gated_place():
    mock = MockNeo()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT", product="MIS",
                  quantity="10", price="9.4", variety="bracket", target_price="9.8", stop_loss_price="9.1")
    # Still gated: a bare bracket order without the token must fail-closed.
    with pytest.raises(SafetyBypassError):
        await adapter.place_order(session, order)
    assert mock.calls == []
    # With the token it reaches the broker as a BO order carrying both legs.
    oid = await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert oid == "250122000612876"
    _, params = mock.calls[0]
    assert params["product"] == "BO" and params["square_off_value"] == "9.8" and params["stop_loss_value"] == "9.1"


@pytest.mark.asyncio
async def test_place_order_with_router_token():
    mock = MockNeo()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT", product="CNC", quantity="3", price="9.4")
    oid = await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert oid == "250122000612876"
    kind, params = mock.calls[0]
    assert kind == "place"
    assert params["trading_symbol"] == "IDEA-EQ"
    assert params["order_type"] == "L" and params["product"] == "CNC" and params["exchange_segment"] == "nse_cm"


@pytest.mark.asyncio
async def test_modify_and_cancel():
    mock = MockNeo()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.modify_order(session, "OID1", {"quantity": 4, "price": 9.5}, _router_token=_ROUTER_TOKEN)
    await adapter.cancel_order(session, "OID1", _router_token=_ROUTER_TOKEN)
    assert [c[0] for c in mock.calls] == ["modify", "cancel"]


@pytest.mark.asyncio
async def test_reads_map_correctly():
    adapter = _adapter(MockNeo())
    session = await _session(adapter)
    orders = await adapter.order_book(session)
    assert orders[0]["symbol"] == "IDEA-EQ" and orders[0]["exchange"] == "NSE" and orders[0]["product"] == "NRML"
    positions = await adapter.positions(session)
    assert positions[0]["symbol"] == "IDEA-EQ" and positions[0]["product"] == "MIS" and positions[0]["quantity"] == "10"
    funds = await adapter.funds(session)
    assert funds["available_balance"] == "19.41" and funds["used_margin"] == "18.78"


@pytest.mark.asyncio
async def test_unresolvable_symbol_raises():
    adapter = KotakNeoAdapter(client_factory=lambda _s: MockNeo())  # no resolver
    session = await _session(adapter)
    order = Order(symbol="OBSCURE", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS")
    with pytest.raises(BrokerError, match="trading_symbol"):
        await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)


@pytest.mark.asyncio
async def test_quotes_maps_records():
    mock = MockNeo()
    adapter = _adapter(mock)
    session = await _session(adapter)
    quotes = await adapter.quotes(session, ["NSE:IDEA"])
    assert len(quotes) == 1
    q = quotes[0]
    assert q.symbol == "IDEA-EQ" and q.exchange == "NSE"
    assert q.ltp == 9.4 and q.bid == 9.39 and q.ask == 9.41
    # request carried the NEO instrument-token dicts
    _, tokens = [c for c in mock.calls if c[0] == "quotes"][0]
    assert tokens[0]["exchange_segment"] == "nse_cm"


class _EnvelopeNeo(MockNeo):
    """Returns NEO error/empty envelopes (no `data` key) for the read surface."""

    def order_book(self):
        return {"stat": "Not_Ok", "errMsg": "Invalid session"}

    def positions(self):
        return {"stat": "Not_Ok", "errMsg": "Invalid session"}

    def funds(self):
        return {"stat": "Not_Ok", "errMsg": "Invalid session"}

    def quotes(self, instrument_tokens):
        # NEO quirk: REST sometimes echoes a bare top-level list, not {data: [...]}.
        self.calls.append(("quotes", instrument_tokens))
        return [
            {"trading_symbol": "IDEA-EQ", "exchange_segment": "nse_cm", "last_traded_price": 9.4},
        ]


@pytest.mark.asyncio
async def test_reads_tolerate_empty_and_error_envelope():
    adapter = _adapter(_EnvelopeNeo())
    session = await _session(adapter)
    assert await adapter.order_book(session) == []
    assert await adapter.positions(session) == []
    funds = await adapter.funds(session)
    # No data → zeroed funds dict, never a raise.
    assert funds["available_balance"] == "0.00" and funds["used_margin"] == "0.00"


@pytest.mark.asyncio
async def test_quotes_bare_list_fallback():
    adapter = _adapter(_EnvelopeNeo())
    session = await _session(adapter)
    quotes = await adapter.quotes(session, ["NSE:IDEA"])
    assert len(quotes) == 1 and quotes[0].symbol == "IDEA-EQ" and quotes[0].ltp == 9.4


@pytest.mark.asyncio
async def test_no_historical_or_option_chain():
    adapter = _adapter(MockNeo())
    session = await _session(adapter)
    with pytest.raises(NotImplementedError, match="historical"):
        await adapter.historical(session, {})
    with pytest.raises(NotImplementedError, match="option-chain"):
        await adapter.option_chain(session, {})
