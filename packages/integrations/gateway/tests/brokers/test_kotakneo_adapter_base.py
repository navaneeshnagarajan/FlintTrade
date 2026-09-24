"""Tests for the Kotak Neo adapter (mock facade; no SDK / creds needed)."""

from __future__ import annotations

import pytest

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
from flinttrade_core.exceptions import BrokerError, SessionExpired, UnsupportedCapabilityError
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
        return {"stat": "Ok", "nOrdNo": params["order_id"], "stCode": 200}

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
             "cfBuyQty": 0, "flBuyQty": 10, "cfSellQty": 0, "flSellQty": 0,
             "cfBuyAmt": 0, "buyAmt": 1000, "cfSellAmt": 0, "sellAmt": 0,
             "genNum": 1, "genDen": 1, "prcNum": 1, "prcDen": 1,
             "multiplier": 1, "precision": 2},
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
        requested = str(instrument_tokens[0]["instrument_token"])
        trading_symbol = requested if requested == "Nifty 50" else "IDEA-EQ"
        return {"stat": "Ok", "data": [
            {"instrument_token": requested, "trading_symbol": trading_symbol,
             "exchange_segment": "nse_cm", "last_traded_price": 9.4,
             "open": 9.2, "high": 9.6, "low": 9.1, "close": 9.3, "volume": 1000000,
             "buy_price": 9.39, "sell_price": 9.41},
        ]}

    def margin(self, params):
        self.calls.append(("margin", params))
        return {"data": {"reqdMrgn": "0", "ordMrgn": "15.50", "avlCash": "38.19",
                         "insufFund": "0", "rmsVldtd": "OK", "stat": "Ok", "stCode": 200}}

    def search_scrip(self, exchange_segment, symbol):
        self.calls.append(("search", (exchange_segment, symbol)))
        return [
            {"pSymbol": 11915, "pExchSeg": "nse_cm", "pSymbolName": symbol,
             "pTrdSymbol": f"{symbol}-EQ", "pISIN": "INE528G01035", "lLotSize": 1, "dTickSize": 1},
        ]

    def historical_data(self, neosymbol, interval, from_date, to_date):
        self.calls.append(("historical_data", (neosymbol, interval, from_date, to_date)))
        return {
            "status": "success",
            "interval": interval,
            "data": {"candles": [["2026-09-20T09:15:00+05:30", 1, 2, 1, 2, 10, None]]},
        }

    def option_chain(self, exchange, underlying, expiry=None, instrument_type=None, count=None):
        self.calls.append(("option_chain", (exchange, underlying, expiry, instrument_type, count)))
        return {
            "data": {
                "common_data": {
                    "mktLot": "65",
                    "multiplier": "1",
                    "unlSymbol": underlying,
                    "exSeg": exchange,
                    "expiryDt": expiry or "2026-09-24",
                },
                "call": [
                    {
                        "instrument": {
                            "neoSymbol": f"{exchange}|71472",
                            "optionType": "CE",
                            "strikePrice": "25000",
                        },
                        "quote": {"ltp": "1.5", "volume": 10},
                        "openInterest": {"current": 100},
                    }
                ],
                "put": [
                    {
                        "instrument": {
                            "neoSymbol": f"{exchange}|71473",
                            "optionType": "PE",
                            "strikePrice": "25000.0",
                        },
                        "quote": {"ltp": "2.5"},
                    }
                ],
            }
        }


class _NoScripNeo(MockNeo):
    def search_scrip(self, exchange_segment, symbol):
        self.calls.append(("search", (exchange_segment, symbol)))
        return []


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
    assert session.is_read_only is True
    assert session.read_only_until_at == session.expires_at


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
async def test_bracket_order_is_gated_then_refused_before_transport():
    mock = MockNeo()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT", product="MIS",
                  quantity="10", price="9.4", variety="bracket", target_price="9.8", stop_loss_price="9.1")
    # Still gated: a bare bracket order without the token must fail-closed.
    with pytest.raises(SafetyBypassError):
        await adapter.place_order(session, order)
    assert mock.calls == []
    with pytest.raises(UnsupportedCapabilityError, match="variety"):
        await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert mock.calls == []


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
    adapter = KotakNeoAdapter(client_factory=lambda _s: _NoScripNeo())  # no resolver, no broker-side hit
    session = await _session(adapter)
    order = Order(symbol="OBSCURE", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS")
    with pytest.raises(BrokerError, match="trading_symbol"):
        await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)


@pytest.mark.asyncio
async def test_place_order_resolves_trading_symbol_via_search_scrip():
    mock = MockNeo()
    adapter = KotakNeoAdapter(client_factory=lambda _s: mock)
    session = await _session(adapter)
    order = Order(symbol="YESBANK", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="MIS", quantity="10", price="9.4")
    oid = await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert oid == "250122000612876"
    assert ("search", ("nse_cm", "YESBANK")) in mock.calls
    _, params = [c for c in mock.calls if c[0] == "place"][0]
    assert params["trading_symbol"] == "YESBANK-EQ"


@pytest.mark.asyncio
async def test_quotes_maps_records():
    mock = MockNeo()
    adapter = _adapter(mock)
    session = await _session(adapter)
    quotes = await adapter.quotes(session, ["NSE:IDEA"])
    assert len(quotes) == 1
    q = quotes[0]
    assert q.symbol == "IDEA" and q.exchange == "NSE"
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
    with pytest.raises(SessionExpired):
        await adapter.order_book(session)
    with pytest.raises(SessionExpired):
        await adapter.positions(session)
    with pytest.raises(SessionExpired):
        await adapter.funds(session)


@pytest.mark.asyncio
async def test_quotes_bare_list_is_not_a_success_envelope():
    adapter = _adapter(_EnvelopeNeo())
    session = await _session(adapter)
    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.quotes(session, ["NSE:IDEA"])


@pytest.mark.asyncio
async def test_iceberg_refused_at_gated_adapter_layer():
    # NEO has no slice endpoint; an iceberg must be refused through the gated
    # place path and NEVER reach the broker (no silent regular-order placement).
    mock = MockNeo()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="MIS", quantity="5000", price="9.4", variety="iceberg")
    with pytest.raises(UnsupportedCapabilityError, match="variety"):
        await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert mock.calls == []


@pytest.mark.asyncio
async def test_margin_calculator_reads_estimate():
    adapter = _adapter(MockNeo())
    session = await _session(adapter)
    order = Order(symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="MIS", quantity="10", price="9.4")
    margin = await adapter.margin_calculator(session, order)
    assert margin["required_margin"] == "15.50" and margin["available_balance"] == "38.19"


@pytest.mark.asyncio
async def test_margin_calculator_sends_numeric_instrument_token():
    # Margin keys the scrip only by numeric pSymbol (Margin_Required.md:35).
    mock = MockNeo()
    adapter = KotakNeoAdapter(
        client_factory=lambda _s: mock,
        symbol_resolver=lambda s, e: "IDEA-EQ",
        token_resolver=lambda s, e: "14366",
    )
    session = await _session(adapter)
    order = Order(symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="MIS", quantity="10", price="9.4")
    await adapter.margin_calculator(session, order)
    _, params = [c for c in mock.calls if c[0] == "margin"][0]
    assert params["instrument_token"] == "14366"
    assert "trading_symbol" not in params


@pytest.mark.asyncio
async def test_margin_calculator_resolves_token_via_search_scrip():
    # No token resolver → the adapter resolves the numeric token via search_scrip.
    mock = MockNeo()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(symbol="YESBANK", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="MIS", quantity="10", price="9.4")
    await adapter.margin_calculator(session, order)
    _, params = [c for c in mock.calls if c[0] == "margin"][0]
    assert params["instrument_token"] == "11915"   # pSymbol from search_scrip


@pytest.mark.asyncio
async def test_quotes_use_numeric_token_for_scrip():
    # Finding #2 — a scrip is keyed by its resolved numeric token on the quotes
    # request, NOT the trading symbol.
    mock = MockNeo()
    adapter = KotakNeoAdapter(
        client_factory=lambda _s: mock,
        symbol_resolver=lambda s, e: "IDEA-EQ",
        token_resolver=lambda s, e: "14366",
    )
    session = await _session(adapter)
    await adapter.quotes(session, ["NSE:IDEA"])
    _, tokens = [c for c in mock.calls if c[0] == "quotes"][0]
    assert tokens[0] == {"instrument_token": "14366", "exchange_segment": "nse_cm"}


@pytest.mark.asyncio
async def test_quotes_pass_index_by_name():
    # An index keys by its NAME on the quotes request (webSocket.md "For Indexes"
    # / Quotes.md), with no token resolution attempted.
    mock = MockNeo()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.quotes(session, ["NSE:Nifty 50"])
    _, tokens = [c for c in mock.calls if c[0] == "quotes"][0]
    assert tokens[0] == {"instrument_token": "Nifty 50", "exchange_segment": "nse_cm"}
    assert not [c for c in mock.calls if c[0] == "search"]  # index never hits search_scrip


@pytest.mark.asyncio
async def test_search_scrip_resolves_symbol():
    adapter = _adapter(MockNeo())
    session = await _session(adapter)
    scrips = await adapter.search_scrip(session, "YESBANK", "NSE")
    assert len(scrips) == 1
    s = scrips[0]
    assert s["trading_symbol"] == "YESBANK-EQ" and s["token"] == "11915"
    assert s["exchange"] == "NSE" and s["isin"] == "INE528G01035" and s["lot_size"] == "1"


@pytest.mark.asyncio
async def test_v3_historical_and_option_chain():
    mock = MockNeo()
    adapter = _adapter(mock)
    session = await _session(adapter)
    candles = await adapter.historical(
        session,
        {"symbol": "YESBANK", "exchange": "NSE", "interval": "1D", "start_date": "2026-09-01", "end_date": "2026-09-20"},
    )
    assert (candles.symbol, candles.exchange, candles.interval) == ("YESBANK", "NSE", "1D")
    assert candles.bars[0].model_dump(exclude_unset=True) == {
        "timestamp": "2026-09-20T09:15:00+05:30",
        "open": 1.0,
        "high": 2.0,
        "low": 1.0,
        "close": 2.0,
        "volume": 10,
    }
    chain = await adapter.option_chain(
        session,
        {
            "underlying": "NIFTY",
            "exchange": "NSE_INDEX",
            "expiry": "2026-09-24",
            "instrument_type": "option",
            "count": 40,
        },
    )
    assert (chain.underlying, chain.exchange, chain.expiry) == ("NIFTY", "NSE_INDEX", "2026-09-24")
    assert chain.model_dump(exclude_unset=True) == {
        "underlying": "NIFTY",
        "exchange": "NSE_INDEX",
        "expiry": "2026-09-24",
        "expiry_date": "2026-09-24",
        "strikes": [
            {
                "strike_price": 25000.0,
                "ce_instrument_id": "nse_fo|71472",
                "ce_ltp": 1.5,
                "ce_oi": 100,
                "ce_volume": 10,
                "pe_instrument_id": "nse_fo|71473",
                "pe_ltp": 2.5,
            }
        ],
    }
    assert ("historical_data", ("nse_cm|11915", "D", "2026-09-01", "2026-09-20")) in mock.calls
    assert ("option_chain", ("nse_fo", "NIFTY", "2026-09-24", "option", 40)) in mock.calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"symbol": "YESBANK", "exchange": "NSE", "interval": "2m", "start_date": "2026-09-01", "end_date": "2026-09-02"},
        {"symbol": "YESBANK", "exchange": "NSE", "interval": "1m", "start_date": "2026-09-02", "end_date": "2026-09-01"},
        {"symbol": "YESBANK", "exchange": "NSE", "interval": "1m", "start_date": "2026-09-01", "from_date": "2026-09-02", "end_date": "2026-09-03"},
        {"symbol": "YESBANK", "exchange": "NSE", "interval": "1m", "start_date": "2026-09-01", "from_date": object(), "end_date": "2026-09-03"},
        {"symbol": "YESBANK", "exchange": "MCX", "interval": "D", "start_date": "2026-09-01", "end_date": "2026-09-02"},
        {"symbol": " YESBANK", "exchange": "NSE", "interval": "D", "start_date": "2026-09-01", "end_date": "2026-09-02"},
        {"symbol": "YESBANK", "exchange": "UNKNOWN", "interval": "D", "start_date": "2026-09-01", "end_date": "2026-09-02"},
        {"symbol": "YESBANK", "exchange": "NSE", "interval": "D", "start_date": "2026-09-01", "end_date": "2026-09-02", "neosymbol": "not-a-neosymbol"},
    ],
)
async def test_invalid_history_is_rejected_before_search_or_sdk_transport(payload):
    mock = MockNeo()
    adapter = _adapter(mock)
    session = await _session(adapter)

    with pytest.raises(UnsupportedCapabilityError):
        await adapter.historical(session, payload)
    assert not [call for call in mock.calls if call[0] in {"search", "historical_data"}]


@pytest.mark.asyncio
async def test_history_rejects_caller_neosymbol_that_differs_from_resolved_identity():
    mock = MockNeo()
    adapter = _adapter(mock)
    session = await _session(adapter)

    with pytest.raises(UnsupportedCapabilityError, match="neosymbol"):
        await adapter.historical(
            session,
            {
                "symbol": "YESBANK",
                "exchange": "NSE",
                "interval": "D",
                "start_date": "2026-09-01",
                "end_date": "2026-09-02",
                "neosymbol": "nse_cm|99999",
            },
        )
    assert ("search", ("nse_cm", "YESBANK")) in mock.calls
    assert not [call for call in mock.calls if call[0] == "historical_data"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"underlying": "NIFTY", "exchange": "CDS", "instrument_type": "option"},
        {"underlying": "NIFTY", "exchange": "NFO", "instrument_type": "fut"},
        {"underlying": "NIFTY", "exchange": "NFO", "instrument_type": "option", "count": 15},
        {"underlying": "NIFTY", "symbol": "BANKNIFTY", "exchange": "NFO"},
        {"underlying": "NIFTY", "exchange": "NFO", "expiry": "24-09-2026"},
    ],
)
async def test_invalid_option_request_is_rejected_before_sdk_transport(payload):
    mock = MockNeo()
    adapter = _adapter(mock)
    session = await _session(adapter)

    with pytest.raises(UnsupportedCapabilityError):
        await adapter.option_chain(session, payload)
    assert not [call for call in mock.calls if call[0] == "option_chain"]


@pytest.mark.asyncio
async def test_explicit_null_option_defaults_reach_transport_as_sdk_defaults():
    mock = MockNeo()
    adapter = _adapter(mock)
    session = await _session(adapter)

    chain = await adapter.option_chain(
        session,
        {
            "underlying": None,
            "symbol": "NIFTY",
            "exchange": "NSE_INDEX",
            "expiry": None,
            "instrument_type": None,
        },
    )

    assert chain.expiry == "2026-09-24"
    assert ("option_chain", ("nse_fo", "NIFTY", None, "option", None)) in mock.calls


def test_sfeed_only_facade_rejects_subscribe_as_rest_only():
    from flinttrade_gateway.brokers.kotakneo import KotakNeoClient

    class _SFeedOnly:
        def create_websocket(self):
            raise AssertionError("create_websocket must not be called")

    facade = KotakNeoClient.__new__(KotakNeoClient)
    facade._neo = _SFeedOnly()
    with pytest.raises(BrokerError, match="REST-only") as raised:
        facade.subscribe([], False, False)
    message = str(raised.value)
    assert "Connected (read)" in message
    assert "API smoke" in message
    assert "Monday" not in message
