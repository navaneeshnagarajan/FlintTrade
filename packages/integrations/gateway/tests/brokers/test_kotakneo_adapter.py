"""Tests for the Kotak Neo adapter's full-parity surface (mock facade; no SDK).

The base surface (login, gated regular/bracket/cover place, reads, quotes,
margin, scrip search) is covered in ``tests/test_kotakneo_adapter.py``; this
file exercises the parity wave: AMO, the bracket/cover leg-cancel endpoints,
full-surface modify, per-order history + fills, filtered limits, scrip master,
typed quotes + market depth, the HSM subscribe/unsubscribe surface and the
market/order feed streams against synthetic frames.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import pytest

from flinttrade_core.exceptions import BrokerError
from flinttrade_core.models import Order
from flinttrade_engine.safety import SafetyBypassError
from flinttrade_gateway.brokers.kotakneo import (
    KOTAKNEO_CAPABILITIES,
    KotakNeoAdapter,
    KotakNeoClient,
    _normalise_credentials,
    _ROUTER_TOKEN,
)
from flinttrade_gateway.brokers.kotakneo_mapping import KotakNeoMappingError

pytestmark = pytest.mark.unit


class MockNeoFull:
    """Mock facade covering the COMPLETE ``KotakNeoClient`` method surface."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    # -- gated writes -------------------------------------------------------

    def place_order(self, params):
        self.calls.append(("place", params))
        return {"stat": "Ok", "nOrdNo": "250122000612876", "stCode": 200}

    def modify_order(self, params):
        self.calls.append(("modify", params))
        return {"stat": "Ok", "nOrdNo": params["order_id"], "stCode": 200}

    def cancel_order(self, order_id, amo="NO", is_verify=False):
        self.calls.append(("cancel", (order_id, amo, is_verify)))
        return {"stat": "Ok", "nOrdNo": order_id, "stCode": 200}

    def cancel_cover_order(self, order_id, amo="NO", is_verify=False):
        self.calls.append(("cancel_co", (order_id, amo, is_verify)))
        return {"stat": "Ok", "nOrdNo": order_id, "stCode": 200}

    def cancel_bracket_order(self, order_id, amo="NO", is_verify=False):
        self.calls.append(("cancel_bo", (order_id, amo, is_verify)))
        return {"stat": "Ok", "nOrdNo": order_id, "stCode": 200}

    # -- reads ---------------------------------------------------------------

    def order_book(self):
        return {"stat": "Ok", "data": []}

    def order_history(self, order_id):
        self.calls.append(("history", order_id))
        return {"data": {"stat": "Ok", "stCode": 200, "data": [
            {"nOrdNo": order_id, "ordSt": "complete", "trdSym": "IDEA-EQ", "exSeg": "nse_cm",
             "trnsTp": "B", "prcTp": "L", "prod": "NRML", "qty": 1, "prc": "9.39",
             "exchTmstp": "22-Jan-2025 14:32:53", "fldQty": 1, "avgPrc": "9.39"},
            {"nOrdNo": order_id, "ordSt": "open", "trdSym": "IDEA-EQ", "exSeg": "nse_cm",
             "trnsTp": "B", "prcTp": "L", "prod": "NRML", "qty": 1, "prc": "9.39",
             "exchTmstp": "22-Jan-2025 14:32:53", "fldQty": 0, "avgPrc": "0.00"},
        ]}}

    def trade_book(self, order_id=None):
        self.calls.append(("trades", order_id))
        if order_id:
            return {"stat": "ok", "stCode": 200, "data":
                    {"nOrdNo": order_id, "trdSym": "IDEA-EQ", "exSeg": "nse_cm", "trnsTp": "B",
                     "fldQty": 1, "avgPrc": "9.39", "prod": "NRML", "flDtTm": "22-Jan-2025 14:33:01"}}
        return {"stat": "ok", "stCode": 200, "data": []}

    def positions(self):
        return {"stat": "ok", "data": []}

    def holdings(self):
        return {"stat": "Ok", "data": []}

    def funds(self):
        return {"Net": "19.41", "MarginUsed": "18.78", "CollateralValue": "38.19", "stat": "Ok"}

    def limits(self, segment, exchange, product):
        self.calls.append(("limits", (segment, exchange, product)))
        return {"Net": "10.00", "MarginUsed": "5.00", "stat": "Ok", "stCode": 200}

    def quotes(self, instrument_tokens, quote_type="all"):
        self.calls.append(("quotes", (instrument_tokens, quote_type)))
        if quote_type == "depth":
            return {"data": [
                {"instrument_token": "14366", "trading_symbol": "IDEA-EQ", "exchange_segment": "nse_cm",
                 "depth": {"buy": [{"price": 9.39, "quantity": 100, "orders": 3}],
                           "sell": [{"price": 9.41, "quantity": 50, "orders": 2}]}},
            ]}
        if quote_type == "ltp":
            return {"data": [{"trading_symbol": "IDEA-EQ", "exchange_segment": "nse_cm", "ltp": 9.4}]}
        return {"data": [
            {"trading_symbol": "IDEA-EQ", "exchange_segment": "nse_cm", "last_traded_price": 9.4,
             "buy_price": 9.39, "sell_price": 9.41, "volume": 1000},
        ]}

    def margin(self, params):
        self.calls.append(("margin", params))
        return {"data": {"reqdMrgn": "15.50", "avlCash": "38.19", "stat": "Ok"}}

    def scrip_master(self, exchange_segment=None):
        self.calls.append(("scrip_master", exchange_segment))
        if exchange_segment:
            return f"https://lapi.kotaksecurities.com/prod/2025-01-22/transformed/{exchange_segment}.csv"
        return {"filesPaths": ["https://x/nse_cm.csv", "https://x/nse_fo.csv"], "baseFolder": "https://x"}

    def search_scrip(self, exchange_segment, symbol, expiry=None, option_type=None,
                     strike_price=None, ignore_50multiple=True):
        self.calls.append(("search", (exchange_segment, symbol, expiry, option_type, strike_price)))
        return [{"pSymbol": 14366, "pExchSeg": exchange_segment, "pSymbolName": str(symbol).upper(),
                 "pTrdSymbol": f"{str(symbol).upper()}-EQ", "lLotSize": 1, "dTickSize": 1}]

    # -- streaming + session -------------------------------------------------

    def subscribe(self, instrument_tokens, is_index, is_depth):
        self.calls.append(("subscribe", (instrument_tokens, is_index, is_depth)))

    def un_subscribe(self, instrument_tokens, is_index, is_depth):
        self.calls.append(("un_subscribe", (instrument_tokens, is_index, is_depth)))

    def subscribe_to_orderfeed(self):
        self.calls.append(("subscribe_orderfeed", None))
        return None

    def logout(self):
        self.calls.append(("logout", None))
        return {"State": "OK"}


def _adapter(mock: MockNeoFull, **kwargs: Any) -> KotakNeoAdapter:
    return KotakNeoAdapter(
        client_factory=lambda _s: mock,
        symbol_resolver=lambda s, e: f"{s}-EQ",
        **kwargs,
    )


async def _session(adapter: KotakNeoAdapter):
    return await adapter.login(
        {"consumer_key": "CK", "mobile_number": "+91...", "ucc": "U1", "mpin": "1234", "totp": "000000"}
    )


# ---------------------------------------------------------------------------
# Auth lifecycle
# ---------------------------------------------------------------------------

def test_normalise_credentials_accepts_kotak_docs_access_token_alias() -> None:
    original = {"access_token": "TRADE-API-TOKEN", "mobile_number": "9"}

    normalised = _normalise_credentials(original)

    assert normalised["consumer_key"] == "TRADE-API-TOKEN"
    assert normalised["access_token"] == "TRADE-API-TOKEN"
    assert "consumer_key" not in original
    with_both = _normalise_credentials({"consumer_key": "SDK-NAME", "access_token": "DOC-NAME"})
    assert with_both["consumer_key"] == "SDK-NAME"


@pytest.mark.asyncio
async def test_login_requires_totp():
    with pytest.raises(BrokerError, match="totp"):
        await KotakNeoAdapter().login(
            {"consumer_key": "CK", "mobile_number": "+91...", "ucc": "U1", "mpin": "1234"}
        )


@pytest.mark.asyncio
async def test_login_accepts_access_token_alias_for_kotak_authorization_header():
    mock = MockNeoFull()
    session = await _adapter(mock).login(
        {
            "access_token": "TRADE-API-TOKEN",
            "mobile_number": "+91...",
            "ucc": "U1",
            "mpin": "1234",
            "totp": "000000",
        }
    )

    assert session.account_id == "U1"
    assert session.adapter_id == "kotakneo"


@pytest.mark.asyncio
async def test_login_requires_consumer_key_or_access_token():
    with pytest.raises(BrokerError, match="consumer_key.*access_token"):
        await KotakNeoAdapter().login(
            {"mobile_number": "+91...", "ucc": "U1", "mpin": "1234", "totp": "000000"}
        )


@pytest.mark.asyncio
async def test_logout_calls_facade_and_is_idempotent():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.logout(session)
    await adapter.logout(session)
    assert [c for c in mock.calls if c[0] == "logout"] == [("logout", None), ("logout", None)]


@pytest.mark.asyncio
async def test_logout_tolerates_facade_without_logout():
    class Bare:
        pass

    adapter = KotakNeoAdapter(client_factory=lambda _s: Bare())
    session = await _session(adapter)
    await adapter.logout(session)  # must not raise


def test_sdk_rest_wrapper_adds_fin_key_to_login_and_session_calls_only():
    class FakeRest:
        def __init__(self) -> None:
            self.headers: list[dict[str, str]] = []

        def request(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            self.headers.append(dict(kwargs.get("headers") or {}))
            return {"ok": True}

    class FakeConfig:
        def get_neo_fin_key(self) -> str:
            return "neotradeapi"

    class FakeNeo:
        def __init__(self) -> None:
            self.configuration = FakeConfig()
            self.api_client = type("ApiClient", (), {"rest_client": FakeRest()})()

    neo = FakeNeo()
    KotakNeoClient._install_fin_key_header_patch(neo)
    rest = neo.api_client.rest_client

    rest.request(method="POST", url="https://example/orders", headers={"Auth": "A", "Sid": "S"})
    rest.request(
        method="POST",
        url="https://mis.kotaksecurities.com/login/1.0/tradeApiLogin",
        headers={"Authorization": "plain-token"},
    )
    rest.request(
        method="POST",
        url="https://mis.kotaksecurities.com/login/1.0/tradeApiValidate",
        headers={"Authorization": "plain-token", "Auth": "view-token", "sid": "view-sid"},
    )
    rest.request(
        method="GET",
        url="https://example/script-details/1.0/quotes/neosymbol/nse_cm|26000/all",
        headers={"Authorization": "plain-token"},
    )
    rest.request(
        method="GET",
        url="https://example/script-details/1.0/masterscrip/file-paths",
        headers={"Authorization": "plain-token"},
    )
    rest.request(method="POST", url="https://example/orders", headers={"Auth": "A", "neo-fin-key": "custom"})

    assert rest.headers[0]["neo-fin-key"] == "neotradeapi"
    assert rest.headers[1]["neo-fin-key"] == "neotradeapi"
    assert rest.headers[2]["neo-fin-key"] == "neotradeapi"
    assert "neo-fin-key" not in rest.headers[3]
    assert "neo-fin-key" not in rest.headers[4]
    assert rest.headers[5]["neo-fin-key"] == "custom"


def test_capabilities_record_current_public_websocket_limits_without_runtime_promotion() -> None:
    """Captured Kotak docs advertise 16 channels and 200 subscribed scrips."""
    assert KOTAKNEO_CAPABILITIES.streaming_supported is True
    assert KOTAKNEO_CAPABILITIES.streaming_runtime_ready is False
    assert KOTAKNEO_CAPABILITIES.streaming_max_connections_per_user == 16
    assert KOTAKNEO_CAPABILITIES.streaming_max_symbols_per_connection == 200
    assert KOTAKNEO_CAPABILITIES.streaming_max_total_symbols == 200


# ---------------------------------------------------------------------------
# Gated writes: AMO + leg-wise cancels + full-surface modify
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_amo_place_sets_flag_through_gate():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="CNC", quantity="10", price="9.4", variety="amo")
    with pytest.raises(SafetyBypassError):
        await adapter.place_order(session, order)
    assert mock.calls == []
    oid = await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert oid == "250122000612876"
    _, params = mock.calls[0]
    assert params["amo"] == "YES" and params["product"] == "CNC"


@pytest.mark.asyncio
async def test_cancel_cover_leg_is_gated_and_dispatches():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    with pytest.raises(SafetyBypassError):
        await adapter.cancel_order(session, "OID1", variety="cover")
    assert mock.calls == []
    await adapter.cancel_order(session, "OID1", variety="cover", _router_token=_ROUTER_TOKEN)
    assert mock.calls == [("cancel_co", ("OID1", "NO", False))]


@pytest.mark.asyncio
async def test_cancel_bracket_leg_is_gated_and_dispatches():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    with pytest.raises(SafetyBypassError):
        await adapter.cancel_order(session, "OID2", variety="bracket", amo=True)
    assert mock.calls == []
    await adapter.cancel_order(session, "OID2", variety="bracket", amo=True, _router_token=_ROUTER_TOKEN)
    assert mock.calls == [("cancel_bo", ("OID2", "YES", False))]


@pytest.mark.asyncio
async def test_cancel_regular_and_amo_routes():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.cancel_order(session, "OID3", _router_token=_ROUTER_TOKEN)
    await adapter.cancel_order(session, "OID4", amo=True, _router_token=_ROUTER_TOKEN)
    await adapter.cancel_order(session, "OID5", variety="amo", _router_token=_ROUTER_TOKEN)
    assert mock.calls == [
        ("cancel", ("OID3", "NO", False)),
        ("cancel", ("OID4", "YES", False)),
        ("cancel", ("OID5", "YES", False)),
    ]


@pytest.mark.asyncio
async def test_cancel_unknown_variety_refused():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    with pytest.raises(BrokerError, match="variety"):
        await adapter.cancel_order(session, "OID6", variety="gtt", _router_token=_ROUTER_TOKEN)
    assert mock.calls == []


@pytest.mark.asyncio
async def test_modify_forwards_full_surface_and_checks_envelope():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.modify_order(
        session,
        "OID7",
        {"pricetype": "SL", "price": 9.5, "quantity": 20, "trigger_price": 9.45,
         "instrument_token": "14366", "exchange_segment": "NSE", "product": "MIS",
         "trading_symbol": "IDEA-EQ", "transaction_type": "BUY", "amo": True},
        _router_token=_ROUTER_TOKEN,
    )
    _, params = mock.calls[0]
    assert params["instrument_token"] == "14366" and params["exchange_segment"] == "nse_cm"
    assert params["transaction_type"] == "B" and params["amo"] == "YES"


@pytest.mark.asyncio
async def test_modify_bare_call_is_token_gated():
    # Finding #7 — a bare adapter.modify_order without the router token must fail
    # closed BEFORE the SDK is touched (parity with place/cancel gating).
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    with pytest.raises(SafetyBypassError):
        await adapter.modify_order(session, "OID9", {"quantity": 1})
    assert mock.calls == []


class _RejectingNeo(MockNeoFull):
    def modify_order(self, params):
        return {"stat": "Not_Ok", "errMsg": "Order is not open"}

    def cancel_order(self, order_id, amo="NO", is_verify=False):
        return {"Error Message": "Complete the 2fa process before accessing this application"}


@pytest.mark.asyncio
async def test_write_error_envelopes_raise():
    adapter = _adapter(_RejectingNeo())
    session = await _session(adapter)
    with pytest.raises(KotakNeoMappingError, match="rejected"):
        await adapter.modify_order(session, "OID8", {"quantity": 1}, _router_token=_ROUTER_TOKEN)
    with pytest.raises(KotakNeoMappingError, match="2fa"):
        await adapter.cancel_order(session, "OID8", _router_token=_ROUTER_TOKEN)


# ---------------------------------------------------------------------------
# Per-order reads
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_order_history_normalises_lifecycle_rows():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    rows = await adapter.order_history(session, "250122000624384")
    assert [r["status"] for r in rows] == ["complete", "open"]
    assert rows[0]["orderid"] == "250122000624384" and rows[0]["exchange"] == "NSE"
    assert mock.calls == [("history", "250122000624384")]


@pytest.mark.asyncio
async def test_order_trades_single_fill_dict():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    fills = await adapter.order_trades(session, "250122000624384")
    assert len(fills) == 1
    assert fills[0]["orderid"] == "250122000624384" and fills[0]["price"] == "9.39"
    assert mock.calls == [("trades", "250122000624384")]


class _NoTradesNeo(MockNeoFull):
    def trade_book(self, order_id=None):
        return {"Error": "There is no trades available with the given order id"}


@pytest.mark.asyncio
async def test_order_trades_tolerates_no_trades():
    adapter = _adapter(_NoTradesNeo())
    session = await _session(adapter)
    assert await adapter.order_trades(session, "X") == []


# ---------------------------------------------------------------------------
# Limits / scrip master / search filters
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_limits_filtered_call():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    out = await adapter.limits(session, segment="FO", exchange="NSE", product="NRML")
    assert mock.calls == [("limits", ("FO", "NSE", "NRML"))]
    assert out["available_balance"] == "10.00" and out["used_margin"] == "5.00"


@pytest.mark.asyncio
async def test_limits_rejects_bad_filters_before_the_wire():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    with pytest.raises(KotakNeoMappingError, match="segment"):
        await adapter.limits(session, segment="EQUITY")
    assert mock.calls == []


@pytest.mark.asyncio
async def test_scrip_master_full_and_filtered():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    full = await adapter.scrip_master(session)
    assert full["base_folder"] == "https://x" and len(full["files"]) == 2
    filtered = await adapter.scrip_master(session, "NFO")
    assert filtered["files"] == ["https://lapi.kotaksecurities.com/prod/2025-01-22/transformed/nse_fo.csv"]
    assert mock.calls == [("scrip_master", None), ("scrip_master", "nse_fo")]


@pytest.mark.asyncio
async def test_search_scrip_forwards_fo_filters():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.search_scrip(session, "BANKNIFTY", "NFO",
                               expiry="28JUN2023", option_type="CE", strike_price="45000")
    assert mock.calls == [("search", ("nse_fo", "BANKNIFTY", "28JUN2023", "CE", "45000"))]


@pytest.mark.asyncio
async def test_search_scrip_minimal_uses_two_arg_call():
    class TwoArgNeo(MockNeoFull):
        def search_scrip(self, exchange_segment, symbol):  # minimal facade
            self.calls.append(("search2", (exchange_segment, symbol)))
            return []

    mock = TwoArgNeo()
    adapter = _adapter(mock)
    session = await _session(adapter)
    assert await adapter.search_scrip(session, "IDEA", "NSE") == []
    assert mock.calls == [("search2", ("nse_cm", "IDEA"))]


# ---------------------------------------------------------------------------
# Typed quotes + market depth
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_quote_details_typed_request():
    # A scrip resolves to its numeric token before the quotes call (the quotes
    # endpoint keys by pSymbol, not the trading symbol).
    mock = MockNeoFull()
    adapter = _adapter(mock, token_resolver=lambda s, e: "14366")
    session = await _session(adapter)
    rows = await adapter.quote_details(session, ["NSE:IDEA"], quote_type="ltp")
    assert rows == [{"trading_symbol": "IDEA-EQ", "exchange_segment": "nse_cm", "ltp": 9.4}]
    (_, (tokens, qtype)) = [c for c in mock.calls if c[0] == "quotes"][0]
    assert qtype == "ltp"
    assert tokens[0] == {"instrument_token": "14366", "exchange_segment": "nse_cm"}


@pytest.mark.asyncio
async def test_quote_details_canonicalises_filter_and_index_case():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.quote_details(session, ["NSE:nifty 50", "BSE:bankex"], quote_type="52w")
    (_, (tokens, qtype)) = [c for c in mock.calls if c[0] == "quotes"][0]
    assert qtype == "52W"
    assert tokens == [
        {"instrument_token": "Nifty 50", "exchange_segment": "nse_cm"},
        {"instrument_token": "BANKEX", "exchange_segment": "bse_cm"},
    ]


@pytest.mark.asyncio
async def test_quote_details_rejects_unknown_type():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    with pytest.raises(BrokerError, match="quote_type"):
        await adapter.quote_details(session, ["NSE:IDEA"], quote_type="greeks")
    assert mock.calls == []


@pytest.mark.asyncio
async def test_market_depth_normalises_book():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    books = await adapter.market_depth(session, ["NSE:IDEA"])
    assert len(books) == 1
    book = books[0]
    assert book["symbol"] == "IDEA-EQ" and book["exchange"] == "NSE"
    assert book["bids"][0]["price"] == 9.39 and book["asks"][0]["quantity"] == 50


# ---------------------------------------------------------------------------
# HSM subscribe / unsubscribe
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subscribe_with_token_resolver_and_depth_mode():
    mock = MockNeoFull()
    adapter = _adapter(mock, token_resolver=lambda s, e: "14366")
    session = await _session(adapter)
    await adapter.subscribe(session, ["NSE:IDEA"], mode="FULL")
    assert mock.calls == [("subscribe", ([{"instrument_token": "14366", "exchange_segment": "nse_cm"}],
                                         False, True))]


@pytest.mark.asyncio
async def test_subscribe_resolves_token_via_search_when_no_resolver():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.subscribe(session, ["NSE:IDEA"], mode="LTP")
    sub = [c for c in mock.calls if c[0] == "subscribe"]
    assert sub == [("subscribe", ([{"instrument_token": "14366", "exchange_segment": "nse_cm"}],
                                  False, False))]


@pytest.mark.asyncio
async def test_subscribe_index_mode_passes_name_through():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.subscribe(session, ["NSE:nifty 50", "BSE:bankex"], mode="INDEX")
    assert mock.calls == [("subscribe", ([{"instrument_token": "Nifty 50", "exchange_segment": "nse_cm"},
                                          {"instrument_token": "BANKEX", "exchange_segment": "bse_cm"}],
                                         True, False))]


@pytest.mark.asyncio
async def test_unsubscribe_replays_recorded_subscription_flags():
    mock = MockNeoFull()
    adapter = _adapter(mock, token_resolver=lambda s, e: "14366")
    session = await _session(adapter)
    await adapter.subscribe(session, ["NSE:IDEA"], mode="DEPTH")
    await adapter.unsubscribe(session, ["NSE:IDEA"])
    unsub = [c for c in mock.calls if c[0] == "un_subscribe"]
    assert unsub == [("un_subscribe", ([{"instrument_token": "14366", "exchange_segment": "nse_cm"}],
                                       False, True))]


@pytest.mark.asyncio
async def test_unsubscribe_unknown_symbol_is_noop():
    mock = MockNeoFull()
    adapter = _adapter(mock, token_resolver=lambda s, e: "14366")
    session = await _session(adapter)
    await adapter.unsubscribe(session, ["NSE:NEVERSUBSCRIBED"])
    assert mock.calls == []


# ---------------------------------------------------------------------------
# Streams (synthetic frames)
# ---------------------------------------------------------------------------

def _market_frames(_session: Any) -> AsyncIterator[Any]:
    async def gen():
        yield json.dumps([{"type": "cn", "msg": "connected"}])  # ack — skipped
        yield {"type": "stock_feed", "data": [
            {"tk": "14366", "ts": "IDEA-EQ", "e": "nse_cm", "ltp": "9.4", "v": "1000",
             "bp": "9.39", "sp": "9.41", "oi": "0", "ltt": "22/01/2025 14:28:16"},
        ]}
        yield [{"tk": "Nifty 50", "e": "nse_cm", "name": "if", "iv": "24050.5", "ic": "23990"}]
    return gen()


@pytest.mark.asyncio
async def test_stream_decodes_synthetic_frames():
    adapter = _adapter(MockNeoFull(), feed_factory=_market_frames)
    session = await _session(adapter)
    ticks = [t async for t in adapter.stream(session)]
    assert len(ticks) == 2
    assert ticks[0].symbol == "IDEA-EQ" and ticks[0].exchange == "NSE"
    assert ticks[0].ltp == 9.4 and ticks[0].bid == 9.39 and ticks[0].ask == 9.41
    assert ticks[1].ltp == 24050.5  # index tick


@pytest.mark.asyncio
async def test_stream_without_factory_raises():
    adapter = _adapter(MockNeoFull())
    session = await _session(adapter)
    with pytest.raises(NotImplementedError, match="feed_factory"):
        async for _ in adapter.stream(session):  # pragma: no cover - never yields
            pass


def _order_frames(_session: Any) -> AsyncIterator[Any]:
    async def gen():
        yield '{"type": "cn"}'  # connection ack — skipped
        yield {"type": "order_feed", "data": json.dumps({"data": {
            "nOrdNo": "250122000624384", "ordSt": "complete", "trdSym": "IDEA-EQ",
            "exSeg": "nse_cm", "trnsTp": "B", "prcTp": "L", "prod": "NRML",
            "qty": 1, "prc": "9.39", "fldQty": 1, "avgPrc": "9.39"}})}
    return gen()


@pytest.mark.asyncio
async def test_order_stream_decodes_updates():
    mock = MockNeoFull()
    adapter = _adapter(mock, order_feed_factory=_order_frames)
    session = await _session(adapter)
    updates = [u async for u in adapter.order_stream(session)]
    assert mock.calls[0] == ("subscribe_orderfeed", None)
    assert len(updates) == 1
    assert updates[0]["orderid"] == "250122000624384" and updates[0]["status"] == "complete"


@pytest.mark.asyncio
async def test_order_stream_without_factory_raises():
    adapter = _adapter(MockNeoFull())
    session = await _session(adapter)
    with pytest.raises(NotImplementedError, match="order_feed_factory"):
        async for _ in adapter.order_stream(session):  # pragma: no cover - never yields
            pass


# ---------------------------------------------------------------------------
# G7 — replayable-credential payload
# ---------------------------------------------------------------------------


def test_replay_credentials_drops_the_one_time_totp_only() -> None:
    from flinttrade_gateway.brokers._base import Session

    adapter = KotakNeoAdapter(client_factory=lambda _s: object())
    session = Session(access_token="UCC1", expires_at=9e9, account_id="UCC1", adapter_id="kotakneo")
    creds = {
        "consumer_key": "CK",
        "mobile_number": "9",
        "ucc": "UCC1",
        "mpin": "111111",
        "totp": "000111",
        "access_token": "PORTAL-TOKEN",
    }
    replay = adapter.replay_credentials(creds, session)
    assert replay == {
        "consumer_key": "CK",
        "mobile_number": "9",
        "ucc": "UCC1",
        "mpin": "111111",
        "access_token": "PORTAL-TOKEN",
    }
