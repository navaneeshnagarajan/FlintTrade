"""Tests for the Kotak Neo adapter's v3 surface (mock facade; no SDK).

The base surface (login, gated regular/AMO place, reads, quotes,
margin, scrip search) is covered in ``tests/brokers/test_kotakneo_adapter_base.py``; this
file exercises the parity wave: AMO, v3-only cancel/modify, local fill filtering, scrip master,
typed quotes + market depth, the HSM subscribe/unsubscribe surface and the
market/order feed streams against synthetic frames.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, AsyncIterator

import pytest

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
from flinttrade_core.exceptions import (
    BrokerError,
    BrokerInternal,
    CredentialsInvalid,
    MFARequired,
    SessionExpired,
    UnsupportedCapabilityError,
)
from flinttrade_core.models import Order
from flinttrade_engine.safety import SafetyBypassError
from flinttrade_gateway.brokers.kotakneo import (
    KOTAKNEO_CAPABILITIES,
    KotakNeoAdapter,
    KotakNeoClient,
    _normalise_credentials,
    _ROUTER_TOKEN,
)

pytestmark = pytest.mark.unit


_OUT_OF_BOUNDS_ORDER_NUMBERS = (
    pytest.param(
        "price",
        Decimal("12345678901234567890123456789012345678901234567890123456789012345"),
        id="65-significant-digits",
    ),
    pytest.param("quantity", Decimal("1e5000"), id="quantity-exponent-positive-5000"),
    pytest.param("price", Decimal("1e100000"), id="price-exponent-positive-100000"),
    pytest.param("price", Decimal("1e-5000"), id="price-scale-5000"),
)


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

    # -- reads ---------------------------------------------------------------

    def order_book(self):
        return {"stat": "Ok", "data": []}

    def order_history(self, order_id):
        self.calls.append(("history", order_id))
        return {
            "data": {
                "stat": "Ok",
                "stCode": 200,
                "data": [
                    {
                        "nOrdNo": order_id,
                        "ordSt": "complete",
                        "trdSym": "IDEA-EQ",
                        "exSeg": "nse_cm",
                        "trnsTp": "B",
                        "prcTp": "L",
                        "prod": "NRML",
                        "qty": 1,
                        "prc": "9.39",
                        "exchTmstp": "22-Jan-2025 14:32:53",
                        "fldQty": 1,
                        "avgPrc": "9.39",
                    },
                    {
                        "nOrdNo": order_id,
                        "ordSt": "open",
                        "trdSym": "IDEA-EQ",
                        "exSeg": "nse_cm",
                        "trnsTp": "B",
                        "prcTp": "L",
                        "prod": "NRML",
                        "qty": 1,
                        "prc": "9.39",
                        "exchTmstp": "22-Jan-2025 14:32:53",
                        "fldQty": 0,
                        "avgPrc": "0.00",
                    },
                ],
            }
        }

    def trade_book(self):
        self.calls.append(("trades",))
        return {"stat": "ok", "stCode": 200, "data": []}

    def positions(self):
        return {"stat": "ok", "data": []}

    def holdings(self):
        return {"stat": "Ok", "data": []}

    def funds(self):
        return {"Net": "19.41", "MarginUsed": "18.78", "CollateralValue": "38.19", "stat": "Ok"}

    def limits(self):
        self.calls.append(("limits",))
        return {"Net": "10.00", "MarginUsed": "5.00", "stat": "Ok", "stCode": 200}

    def quotes(self, instrument_tokens, quote_type="all"):
        self.calls.append(("quotes", (instrument_tokens, quote_type)))
        if quote_type == "depth":
            return {
                "data": [
                    {
                        "instrument_token": "14366",
                        "trading_symbol": "IDEA-EQ",
                        "exchange_segment": "nse_cm",
                        "depth": {
                            "buy": [{"price": 9.39, "quantity": 100, "orders": 3}],
                            "sell": [{"price": 9.41, "quantity": 50, "orders": 2}],
                        },
                    },
                ]
            }
        if quote_type == "ltp":
            return {"data": [{"trading_symbol": "IDEA-EQ", "exchange_segment": "nse_cm", "ltp": 9.4}]}
        return {
            "data": [
                {
                    "trading_symbol": "IDEA-EQ",
                    "exchange_segment": "nse_cm",
                    "last_traded_price": 9.4,
                    "buy_price": 9.39,
                    "sell_price": 9.41,
                    "volume": 1000,
                },
            ]
        }

    def margin(self, params):
        self.calls.append(("margin", params))
        return {
            "data": {
                "stat": "Ok",
                "stCode": 200,
                "ordMrgn": "15.50",
                "reqdMrgn": "0.00",
                "avlCash": "38.19",
                "insufFund": "0.00",
                "rmsVldtd": "OK",
            }
        }

    def scrip_master(self, exchange_segment=None):
        self.calls.append(("scrip_master", exchange_segment))
        if exchange_segment:
            return f"https://lapi.kotaksecurities.com/prod/2025-01-22/transformed/{exchange_segment}.csv"
        return {"filesPaths": ["https://x/nse_cm.csv", "https://x/nse_fo.csv"], "baseFolder": "https://x"}

    def search_scrip(
        self, exchange_segment, symbol, expiry=None, option_type=None, strike_price=None, ignore_50multiple=True
    ):
        self.calls.append(("search", (exchange_segment, symbol, expiry, option_type, strike_price)))
        return [
            {
                "pSymbol": 14366,
                "pExchSeg": exchange_segment,
                "pSymbolName": str(symbol).upper(),
                "pTrdSymbol": f"{str(symbol).upper()}-EQ",
                "lLotSize": 1,
                "dTickSize": 1,
            }
        ]

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


@pytest.mark.asyncio
async def test_rejected_limits_do_not_become_zero_funds():
    class Rejected(MockNeoFull):
        def funds(self):
            return {"stat": "Not_Ok", "errMsg": "session expired"}

    adapter = _adapter(Rejected())
    session = await _session(adapter)
    with pytest.raises(SessionExpired):
        await adapter.funds(session)
    with pytest.raises(SessionExpired):
        await adapter.balance_snapshot(session)


@pytest.mark.asyncio
async def test_rejected_order_history_does_not_become_an_empty_history():
    class Rejected(MockNeoFull):
        def order_history(self, order_id):
            return {"error": [{"code": "401", "message": "session expired"}]}

    adapter = _adapter(Rejected())
    session = await _session(adapter)
    with pytest.raises(SessionExpired):
        await adapter.order_history(session, "SYNTHETIC")


@pytest.mark.asyncio
async def test_rejected_order_book_surfaces_typed_session_expiry():
    class Rejected(MockNeoFull):
        def order_book(self):
            return {"stat": "Not_Ok", "errMsg": "session expired", "data": []}

    adapter = _adapter(Rejected())
    session = await _session(adapter)
    with pytest.raises(SessionExpired):
        await adapter.order_book(session)


@pytest.mark.asyncio
async def test_rejected_scrip_search_does_not_look_like_an_unknown_symbol():
    class Rejected(MockNeoFull):
        def search_scrip(self, exchange_segment, symbol, expiry=None, option_type=None,
                         strike_price=None, ignore_50multiple=True):
            return {"error": [{"code": "401", "message": "session expired"}]}

    adapter = _adapter(Rejected())
    session = await _session(adapter)
    with pytest.raises(SessionExpired):
        await adapter.search_scrip(session, "SYNTHETIC")


@pytest.mark.asyncio
async def test_refresh_requires_new_mfa_instead_of_returning_old_session():
    adapter = _adapter(MockNeoFull())
    session = await _session(adapter)
    with pytest.raises(MFARequired):
        await adapter.refresh(session)


@pytest.mark.asyncio
async def test_login_requires_typed_fresh_mfa_before_constructing_client():
    adapter = _adapter(MockNeoFull())
    with pytest.raises(MFARequired):
        await adapter.login({"consumer_key": "synthetic", "mobile_number": "synthetic", "ucc": "SYNTHETIC", "mpin": "123456"})
    with pytest.raises(CredentialsInvalid):
        await adapter.login({"mobile_number": "synthetic", "ucc": "SYNTHETIC", "totp": "000000", "mpin": "123456"})


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
        await KotakNeoAdapter().login({"consumer_key": "CK", "mobile_number": "+91...", "ucc": "U1", "mpin": "1234"})


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
        await KotakNeoAdapter().login({"mobile_number": "+91...", "ucc": "U1", "mpin": "1234", "totp": "000000"})


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



def test_v3_cancel_facade_has_no_removed_trading_symbol_argument():
    client = KotakNeoClient.__new__(KotakNeoClient)
    with pytest.raises(TypeError, match="trading_symbol"):
        client.cancel_order("OID-AMO", amo="YES", trading_symbol="SYNTHETIC-EQ")


def test_capabilities_remove_v2_order_and_streaming_claims() -> None:
    assert KOTAKNEO_CAPABILITIES.historical_intraday_intervals_minutes == [1, 3, 5, 10, 15, 30, 60]
    assert KOTAKNEO_CAPABILITIES.historical_calendar_intervals == ["1D", "1W"]
    assert KOTAKNEO_CAPABILITIES.historical_max_lookback_days_intraday is None
    assert KOTAKNEO_CAPABILITIES.historical_max_lookback_days_daily is None
    assert KOTAKNEO_CAPABILITIES.streaming_supported is True
    assert KOTAKNEO_CAPABILITIES.streaming_runtime_ready is False
    assert KOTAKNEO_CAPABILITIES.streaming_max_connections_per_user is None
    assert KOTAKNEO_CAPABILITIES.streaming_max_symbols_per_connection is None
    assert KOTAKNEO_CAPABILITIES.streaming_max_total_symbols is None
    assert KOTAKNEO_CAPABILITIES.bracket_order_native is False
    assert KOTAKNEO_CAPABILITIES.cover_order_native is False


# ---------------------------------------------------------------------------
# Gated writes: regular/AMO place, cancel and exact v3 modify
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_amo_place_sets_flag_through_gate():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(
        symbol="IDEA",
        action="BUY",
        exchange="NSE",
        pricetype="LIMIT",
        product="CNC",
        quantity="10",
        price="9.4",
        variety="amo",
    )
    with pytest.raises(SafetyBypassError):
        await adapter.place_order(session, order)
    assert mock.calls == []
    oid = await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert oid == "250122000612876"
    _, params = mock.calls[0]
    assert params["amo"] == "YES" and params["product"] == "CNC"


@pytest.mark.asyncio
async def test_supported_place_emits_exact_v3_kwargs_and_preserves_tag():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    session.algo_id = "SYNTHETIC-TAG"
    order = Order(
        symbol="IDEA",
        action="BUY",
        exchange="NSE",
        pricetype="SL",
        product="MIS",
        quantity="10",
        price="9.4",
        trigger_price="9.3",
        disclosed_quantity="2",
        validity="IOC",
    )

    await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)

    assert mock.calls == [
        (
            "place",
            {
                "exchange_segment": "nse_cm",
                "product": "MIS",
                "price": "9.4",
                "order_type": "SL",
                "quantity": "10",
                "validity": "IOC",
                "trading_symbol": "IDEA-EQ",
                "transaction_type": "B",
                "trigger_price": "9.3",
                "disclosed_quantity": "2",
                "amo": "NO",
                "tag": "SYNTHETIC-TAG",
            },
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "value"),
    [
        ("variety", "bracket"),
        ("variety", "cover"),
        ("product", "MTF"),
        ("exchange", "CDS"),
        ("exchange", "BCD"),
        ("market_protection", True),
        ("market_protection", False),
    ],
)
async def test_unsupported_place_input_is_rejected_before_any_sdk_transport(mutation, value):
    mock = MockNeoFull()
    adapter = KotakNeoAdapter(client_factory=lambda _session: mock)
    session = await _session(adapter)
    order = Order(
        symbol="IDEA",
        action="BUY",
        exchange="NSE",
        pricetype="LIMIT",
        product="MIS",
        quantity="10",
        price="9.4",
    )
    object.__setattr__(order, mutation, value)

    with pytest.raises(UnsupportedCapabilityError):
        await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)

    assert mock.calls == []


@pytest.mark.asyncio
async def test_place_order_rejects_mcx_ioc_before_symbol_resolution_or_transport():
    mock = MockNeoFull()
    resolver_calls: list[tuple[str, str]] = []
    adapter = KotakNeoAdapter(
        client_factory=lambda _session: mock,
        symbol_resolver=lambda symbol, exchange: resolver_calls.append((symbol, exchange)) or symbol,
    )
    session = await _session(adapter)
    order = Order(
        symbol="GOLDPETAL25JUNFUT",
        action="BUY",
        exchange="MCX",
        pricetype="LIMIT",
        product="NRML",
        quantity="1",
        price="7000",
        validity="IOC",
    )

    with pytest.raises(UnsupportedCapabilityError, match="validity"):
        await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)

    assert resolver_calls == []
    assert mock.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quantity", "1.5"),
        ("quantity", "0"),
        ("price", "NaN"),
        ("price", "Infinity"),
        ("trigger_price", "bad"),
        ("disclosed_quantity", "1.5"),
    ],
)
async def test_place_numeric_rejection_precedes_symbol_resolution_and_transport(field, value):
    mock = MockNeoFull()
    resolver_calls: list[tuple[str, str]] = []
    adapter = KotakNeoAdapter(
        client_factory=lambda _session: mock,
        symbol_resolver=lambda symbol, exchange: resolver_calls.append((symbol, exchange)) or symbol,
    )
    session = await _session(adapter)
    order = Order(
        symbol="IDEA", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS", quantity="1"
    ).model_copy(update={field: value})

    with pytest.raises(UnsupportedCapabilityError):
        await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)

    assert resolver_calls == []
    assert mock.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", _OUT_OF_BOUNDS_ORDER_NUMBERS)
@pytest.mark.parametrize("operation", ["place", "modify", "margin"])
async def test_numeric_bounds_raise_canonical_errors_before_resolution_or_transport(operation, field, value):
    mock = MockNeoFull()
    resolver_calls: list[tuple[str, str]] = []
    adapter = KotakNeoAdapter(
        client_factory=lambda _session: mock,
        symbol_resolver=lambda symbol, exchange: resolver_calls.append((symbol, exchange)) or "IDEA-EQ",
        token_resolver=lambda symbol, exchange: resolver_calls.append((symbol, exchange)) or "14366",
    )
    session = await _session(adapter)
    order = Order(
        symbol="IDEA",
        action="BUY",
        exchange="NSE",
        pricetype="MARKET",
        product="MIS",
        quantity="1",
    ).model_copy(update={field: value})

    with pytest.raises(UnsupportedCapabilityError, match=field.replace("_", " ")):
        if operation == "place":
            await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
        elif operation == "modify":
            await adapter.modify_order(
                session,
                "OID-1",
                {"pricetype": "MARKET", "quantity": "1", "price": "0", field: value},
                _router_token=_ROUTER_TOKEN,
            )
        else:
            await adapter.margin_calculator(session, order)

    assert resolver_calls == []
    assert mock.calls == []


@pytest.mark.asyncio
async def test_place_order_resolves_trading_symbol_via_search_scrip_when_no_resolver():
    mock = MockNeoFull()
    adapter = KotakNeoAdapter(client_factory=lambda _s: mock)
    session = await _session(adapter)
    order = Order(
        symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT", product="CNC", quantity="10", price="9.4"
    )
    await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert ("search", ("nse_cm", "IDEA", None, None, None)) in mock.calls
    _, params = [c for c in mock.calls if c[0] == "place"][0]
    assert params["trading_symbol"] == "IDEA-EQ"


@pytest.mark.asyncio
async def test_place_order_raises_when_search_scrip_has_no_match():
    class NoScripNeo(MockNeoFull):
        def search_scrip(
            self, exchange_segment, symbol, expiry=None, option_type=None, strike_price=None, ignore_50multiple=True
        ):
            self.calls.append(("search", (exchange_segment, symbol, expiry, option_type, strike_price)))
            return []

    mock = NoScripNeo()
    adapter = KotakNeoAdapter(client_factory=lambda _s: mock)
    session = await _session(adapter)
    order = Order(symbol="UNKNOWN", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS", quantity="1")
    with pytest.raises(BrokerError, match="trading_symbol"):
        await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert [c for c in mock.calls if c[0] == "place"] == []


@pytest.mark.asyncio
async def test_margin_calculator_resolves_trading_symbol_via_search_scrip_when_no_resolver():
    mock = MockNeoFull()
    adapter = KotakNeoAdapter(client_factory=lambda _s: mock)
    session = await _session(adapter)
    order = Order(
        symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT", product="MIS", quantity="10", price="9.4"
    )
    await adapter.margin_calculator(session, order)
    assert [c for c in mock.calls if c[0] == "search"] == [
        ("search", ("nse_cm", "IDEA", None, None, None)),
    ]
    _, params = [c for c in mock.calls if c[0] == "margin"][0]
    assert params["instrument_token"] == "14366"
    assert "trading_symbol" not in params


@pytest.mark.asyncio
async def test_margin_calculator_rejects_nonnumeric_token_before_transport():
    mock = MockNeoFull()
    adapter = KotakNeoAdapter(
        client_factory=lambda _session: mock,
        token_resolver=lambda _symbol, _exchange: "IDEA-EQ",
    )
    session = await _session(adapter)
    order = Order(
        symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT", product="MIS", quantity="10", price="9.4"
    )

    with pytest.raises(UnsupportedCapabilityError, match="numeric instrument_token"):
        await adapter.margin_calculator(session, order)

    assert not [call for call in mock.calls if call[0] == "margin"]


@pytest.mark.asyncio
async def test_margin_numeric_rejection_precedes_token_resolution_and_transport():
    mock = MockNeoFull()
    resolver_calls: list[tuple[str, str]] = []
    adapter = KotakNeoAdapter(
        client_factory=lambda _session: mock,
        token_resolver=lambda symbol, exchange: resolver_calls.append((symbol, exchange)) or "14366",
    )
    session = await _session(adapter)
    order = Order(
        symbol="IDEA", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS", quantity="1"
    ).model_copy(update={"quantity": "1.5"})

    with pytest.raises(UnsupportedCapabilityError):
        await adapter.margin_calculator(session, order)

    assert resolver_calls == []
    assert mock.calls == []


@pytest.mark.asyncio
async def test_margin_calculator_rejects_oversized_integer_token_from_resolver_canonically():
    mock = MockNeoFull()
    adapter = KotakNeoAdapter(
        client_factory=lambda _session: mock,
        token_resolver=lambda _symbol, _exchange: 10**5000,
    )
    session = await _session(adapter)
    order = Order(
        symbol="IDEA",
        action="BUY",
        exchange="NSE",
        pricetype="MARKET",
        product="MIS",
        quantity="1",
    )

    with pytest.raises(UnsupportedCapabilityError, match="instrument token"):
        await adapter.margin_calculator(session, order)

    assert mock.calls == []


@pytest.mark.asyncio
async def test_margin_calculator_rejects_oversized_live_search_token_before_margin_transport():
    """A huge SDK pSymbol must not escape as Python's int-to-str ValueError."""

    class OversizedSearchTokenNeo(MockNeoFull):
        def search_scrip(
            self,
            exchange_segment,
            symbol,
            expiry=None,
            option_type=None,
            strike_price=None,
            ignore_50multiple=True,
        ):
            self.calls.append(("search", (exchange_segment, symbol)))
            return [
                {
                    "pSymbol": 10**5000,
                    "pExchSeg": exchange_segment,
                    "pSymbolName": str(symbol).upper(),
                    "pTrdSymbol": f"{str(symbol).upper()}-EQ",
                    "lLotSize": 1,
                    "dTickSize": 1,
                }
            ]

    mock = OversizedSearchTokenNeo()
    adapter = KotakNeoAdapter(client_factory=lambda _session: mock)
    session = await _session(adapter)
    order = Order(
        symbol="IDEA",
        action="BUY",
        exchange="NSE",
        pricetype="MARKET",
        product="MIS",
        quantity="1",
    )

    with pytest.raises(BrokerInternal, match="search response is invalid"):
        await adapter.margin_calculator(session, order)

    assert [call[0] for call in mock.calls] == ["search"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"data": {"stat": "Ok", "stCode": 200, "reqdMrgn": "0", "avlCash": "38.19",
                  "insufFund": "0", "rmsVldtd": "OK"}},
        {"data": {"stat": "Ok", "stCode": 200, "ordMrgn": "bad", "reqdMrgn": "0",
                  "avlCash": "38.19", "insufFund": "0", "rmsVldtd": "OK"}},
        {"data": {"stat": "Ok", "stCode": 200, "ordMrgn": "15.5", "reqdMrgn": "0",
                  "avlCash": "Infinity", "insufFund": "0", "rmsVldtd": "OK"}},
    ],
)
async def test_margin_calculator_canonicalises_malformed_success_as_broker_internal(response):
    class MalformedMarginNeo(MockNeoFull):
        def margin(self, params):
            self.calls.append(("margin", params))
            return response

    mock = MalformedMarginNeo()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(
        symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT",
        product="MIS", quantity="10", price="9.4",
    )

    with pytest.raises(BrokerInternal):
        await adapter.margin_calculator(session, order)

    assert len([call for call in mock.calls if call[0] == "margin"]) == 1


@pytest.mark.asyncio
async def test_margin_calculator_canonicalises_huge_official_number_as_broker_internal():
    class OversizedMarginNeo(MockNeoFull):
        def margin(self, params):
            self.calls.append(("margin", params))
            return {
                "data": {
                    "stat": "Ok",
                    "stCode": 200,
                    "ordMrgn": "1e100000",
                    "reqdMrgn": "0",
                    "avlCash": "38.19",
                    "insufFund": "0",
                    "rmsVldtd": "OK",
                }
            }

    mock = OversizedMarginNeo()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(
        symbol="IDEA",
        action="BUY",
        exchange="NSE",
        pricetype="LIMIT",
        product="MIS",
        quantity="10",
        price="9.4",
    )

    with pytest.raises(BrokerInternal):
        await adapter.margin_calculator(session, order)

    assert len([call for call in mock.calls if call[0] == "margin"]) == 1


@pytest.mark.asyncio
async def test_margin_calculator_canonicalises_oversized_primitive_int_as_broker_internal():
    class OversizedIntMarginNeo(MockNeoFull):
        def margin(self, params):
            self.calls.append(("margin", params))
            return {
                "data": {
                    "stat": "Ok",
                    "stCode": 200,
                    "ordMrgn": 10**5000,
                    "reqdMrgn": "0",
                    "avlCash": "38.19",
                    "insufFund": "0",
                    "rmsVldtd": "OK",
                }
            }

    mock = OversizedIntMarginNeo()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(
        symbol="IDEA",
        action="BUY",
        exchange="NSE",
        pricetype="LIMIT",
        product="MIS",
        quantity="10",
        price="9.4",
    )

    with pytest.raises(BrokerInternal):
        await adapter.margin_calculator(session, order)

    assert len([call for call in mock.calls if call[0] == "margin"]) == 1


@pytest.mark.asyncio
async def test_cancel_cover_leg_is_gated_then_rejected_before_transport():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    with pytest.raises(SafetyBypassError):
        await adapter.cancel_order(session, "OID1", variety="cover")
    assert mock.calls == []
    with pytest.raises(UnsupportedCapabilityError, match="variety"):
        await adapter.cancel_order(session, "OID1", variety="cover", _router_token=_ROUTER_TOKEN)
    assert mock.calls == []


@pytest.mark.asyncio
async def test_cancel_bracket_leg_is_gated_then_rejected_before_transport():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    with pytest.raises(SafetyBypassError):
        await adapter.cancel_order(session, "OID2", variety="bracket", amo=True)
    assert mock.calls == []
    with pytest.raises(UnsupportedCapabilityError, match="variety"):
        await adapter.cancel_order(
            session,
            "OID2",
            variety="bracket",
            amo=True,
            _router_token=_ROUTER_TOKEN,
        )
    assert mock.calls == []


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
async def test_cancel_rejects_removed_trading_symbol_before_transport():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    with pytest.raises(UnsupportedCapabilityError, match="trading symbol"):
        await adapter.cancel_order(
            session,
            "OID-SYMBOL",
            trading_symbol="IDEA-EQ",
            _router_token=_ROUTER_TOKEN,
        )
    assert mock.calls == []


@pytest.mark.asyncio
async def test_cancel_unknown_variety_refused():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    with pytest.raises(UnsupportedCapabilityError, match="variety"):
        await adapter.cancel_order(session, "OID6", variety="gtt", _router_token=_ROUTER_TOKEN)
    assert mock.calls == []


@pytest.mark.asyncio
async def test_modify_forwards_only_exact_v3_surface_and_checks_envelope():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.modify_order(
        session,
        "OID7",
        {
            "symbol": "IDEA",
            "exchange": "NSE",
            "action": "BUY",
            "product": "MIS",
            "strategy": "Flint",
            "pricetype": "SL",
            "price": 9.5,
            "quantity": 20,
            "trigger_price": 9.45,
            "disclosed_quantity": 2,
            "validity": "IOC",
            "amo": True,
        },
        _router_token=_ROUTER_TOKEN,
    )
    assert mock.calls == [
        (
            "modify",
            {
                "order_id": "OID7",
                "order_type": "SL",
                "price": "9.5",
                "quantity": "20",
                "validity": "IOC",
                "trigger_price": "9.45",
                "disclosed_quantity": "2",
                "amo": "YES",
            },
        )
    ]


@pytest.mark.asyncio
async def test_modify_mcx_ioc_context_is_rejected_before_transport():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)

    with pytest.raises(UnsupportedCapabilityError, match="validity"):
        await adapter.modify_order(
            session,
            "OID-MCX",
            {
                "symbol": "GOLDPETAL25JUNFUT",
                "exchange": "MCX",
                "action": "BUY",
                "product": "NRML",
                "strategy": "Flint",
                "pricetype": "LIMIT",
                "price": "7000",
                "quantity": "1",
                "validity": "IOC",
            },
            _router_token=_ROUTER_TOKEN,
        )

    assert mock.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsupported",
    [
        {"instrument_token": "14366"},
        {"exchange_segment": "NSE"},
        {"trading_symbol": "IDEA-EQ"},
        {"transaction_type": "BUY"},
        {"filled_quantity": 1},
        {"market_protection": 1},
        {"dd": "NA"},
    ],
)
async def test_modify_rejects_removed_fields_before_transport(unsupported):
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    with pytest.raises(UnsupportedCapabilityError, match="does not support"):
        await adapter.modify_order(
            session,
            "OID-REMOVED",
            {"pricetype": "MARKET", "price": 0, "quantity": 1, **unsupported},
            _router_token=_ROUTER_TOKEN,
        )
    assert mock.calls == []


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
    with pytest.raises(BrokerInternal):
        await adapter.modify_order(
            session,
            "OID8",
            {"pricetype": "MARKET", "price": 0, "quantity": 1},
            _router_token=_ROUTER_TOKEN,
        )
    with pytest.raises(BrokerInternal):
        await adapter.cancel_order(session, "OID8", _router_token=_ROUTER_TOKEN)


class _PlaceAckNeo(MockNeoFull):
    def __init__(self, response: Any) -> None:
        super().__init__()
        self._response = response

    def place_order(self, params):
        self.calls.append(("place", params))
        return self._response


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"stat": "Not_Ok", "nOrdNo": "250122000612876", "stCode": 200, "errMsg": "Order rejected"},
        {"stat": "Ok", "nOrdNo": "250122000612876"},
        {"stat": "Ok", "nOrdNo": "250122000612876", "stCode": "200"},
        {"data": {"nOrdNo": "250122000612876"}},
    ],
)
async def test_place_order_rejects_ambiguous_or_negative_write_acknowledgement(response):
    mock = _PlaceAckNeo(response)
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(symbol="IDEA", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS", quantity="1")
    with pytest.raises(BrokerInternal):
        await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)


@pytest.mark.asyncio
@pytest.mark.parametrize("order_id_key", ["nOrdNo", "orderId"])
async def test_place_order_accepts_explicit_success_with_nested_order_id(order_id_key):
    mock = _PlaceAckNeo(
        {"stat": "Ok", "stCode": 200, "data": {order_id_key: "250122000612876"}}
    )
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(symbol="IDEA", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS", quantity="1")

    assert await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN) == "250122000612876"


class _ModifyAckNeo(MockNeoFull):
    def __init__(self, response: Any) -> None:
        super().__init__()
        self._response = response

    def modify_order(self, params):
        self.calls.append(("modify", params))
        return self._response


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        None,
        [],
        {"stat": "Ok"},
        {"stat": "Ok", "nOrdNo": "OID8"},
        {"stat": "Ok", "nOrdNo": "OID8", "stCode": "200"},
        {"stat": "Ok", "nOrdNo": "", "stCode": 200},
        {"data": {"status": "success", "nOrdNo": "OID8"}},
    ],
)
async def test_modify_order_rejects_ambiguous_or_negative_write_acknowledgement(response):
    mock = _ModifyAckNeo(response)
    adapter = _adapter(mock)
    session = await _session(adapter)
    with pytest.raises(BrokerInternal):
        await adapter.modify_order(
            session,
            "OID8",
            {"pricetype": "MARKET", "price": 0, "quantity": 1},
            _router_token=_ROUTER_TOKEN,
        )


@pytest.mark.asyncio
async def test_modify_order_rejects_acknowledgement_for_a_different_order():
    mock = _ModifyAckNeo({"stat": "Ok", "nOrdNo": "250720000007588", "stCode": 200})
    adapter = _adapter(mock)
    session = await _session(adapter)
    with pytest.raises(BrokerInternal):
        await adapter.modify_order(
            session,
            "OID8",
            {"pricetype": "MARKET", "price": 0, "quantity": 1},
            _router_token=_ROUTER_TOKEN,
        )


@pytest.mark.asyncio
async def test_modify_order_accepts_explicit_success_with_nested_order_id():
    mock = _ModifyAckNeo({"stat": "Ok", "stCode": 200, "data": {"nOrdNo": "OID8"}})
    adapter = _adapter(mock)
    session = await _session(adapter)

    await adapter.modify_order(
        session,
        "OID8",
        {"pricetype": "MARKET", "price": 0, "quantity": 1},
        _router_token=_ROUTER_TOKEN,
    )


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
async def test_order_trades_fetches_unfiltered_report_and_preserves_all_matching_fills():
    class MultiFillNeo(MockNeoFull):
        def trade_book(self):
            self.calls.append(("trades",))
            base = {
                "trdSym": "IDEA-EQ",
                "exSeg": "nse_cm",
                "trnsTp": "B",
                "prod": "NRML",
                "flDtTm": "22-Jan-2025 14:33:01",
            }
            return {
                "stat": "ok",
                "stCode": 200,
                "data": [
                    {**base, "nOrdNo": "250122000624384", "fldQty": 1, "avgPrc": "9.39"},
                    {**base, "nOrdNo": "OTHER", "fldQty": 5, "avgPrc": "9.40"},
                    {**base, "nOrdNo": "250122000624384", "fldQty": 2, "avgPrc": "9.41"},
                ],
            }

    mock = MultiFillNeo()
    adapter = _adapter(mock)
    session = await _session(adapter)
    fills = await adapter.order_trades(session, "250122000624384")
    assert [(fill["quantity"], fill["price"]) for fill in fills] == [("1", "9.39"), ("2", "9.41")]
    assert {fill["orderid"] for fill in fills} == {"250122000624384"}
    assert mock.calls == [("trades",)]


class _NoTradesNeo(MockNeoFull):
    def trade_book(self):
        self.calls.append(("trades",))
        return {"stat": "Ok", "stCode": 200, "data": []}


@pytest.mark.asyncio
async def test_order_trades_tolerates_no_trades():
    adapter = _adapter(_NoTradesNeo())
    session = await _session(adapter)
    assert await adapter.order_trades(session, "X") == []


@pytest.mark.asyncio
async def test_order_trades_validates_every_row_before_local_filtering():
    class MissingOrderIdNeo(MockNeoFull):
        def trade_book(self):
            self.calls.append(("trades",))
            return {
                "stat": "Ok",
                "stCode": 200,
                "data": [
                    {
                        "trdSym": "IDEA-EQ",
                        "exSeg": "nse_cm",
                        "trnsTp": "B",
                        "prod": "NRML",
                        "flDtTm": "22-Jan-2025 14:33:01",
                        "fldQty": "1",
                        "avgPrc": "9.39",
                    }
                ],
            }

    adapter = _adapter(MissingOrderIdNeo())
    session = await _session(adapter)
    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.order_trades(session, "OTHER")


# ---------------------------------------------------------------------------
# Limits / scrip master / search filters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_limits_default_call_uses_no_sdk_arguments():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    out = await adapter.limits(session)
    assert mock.calls == [("limits",)]
    assert out["available_balance"] == "10.00" and out["used_margin"] == "5.00"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filters",
    [
        {"segment": "FO"},
        {"exchange": "NSE"},
        {"product": "NRML"},
        {"segment": "FO", "exchange": "NSE", "product": "NRML"},
        {"segment": "EQUITY"},
    ],
)
async def test_limits_rejects_all_non_default_filters_before_the_wire(filters):
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    with pytest.raises(UnsupportedCapabilityError, match="server-side filters"):
        await adapter.limits(session, **filters)
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
    await adapter.search_scrip(session, "BANKNIFTY", "NFO", expiry="28JUN2023", option_type="CE", strike_price="45000")
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
    assert mock.calls == [("subscribe", ([{"instrument_token": "14366", "exchange_segment": "nse_cm"}], False, True))]


@pytest.mark.asyncio
async def test_subscribe_resolves_token_via_search_when_no_resolver():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.subscribe(session, ["NSE:IDEA"], mode="LTP")
    sub = [c for c in mock.calls if c[0] == "subscribe"]
    assert sub == [("subscribe", ([{"instrument_token": "14366", "exchange_segment": "nse_cm"}], False, False))]


@pytest.mark.asyncio
async def test_subscribe_index_mode_passes_name_through():
    mock = MockNeoFull()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.subscribe(session, ["NSE:nifty 50", "BSE:bankex"], mode="INDEX")
    assert mock.calls == [
        (
            "subscribe",
            (
                [
                    {"instrument_token": "Nifty 50", "exchange_segment": "nse_cm"},
                    {"instrument_token": "BANKEX", "exchange_segment": "bse_cm"},
                ],
                True,
                False,
            ),
        )
    ]


@pytest.mark.asyncio
async def test_unsubscribe_replays_recorded_subscription_flags():
    mock = MockNeoFull()
    adapter = _adapter(mock, token_resolver=lambda s, e: "14366")
    session = await _session(adapter)
    await adapter.subscribe(session, ["NSE:IDEA"], mode="DEPTH")
    await adapter.unsubscribe(session, ["NSE:IDEA"])
    unsub = [c for c in mock.calls if c[0] == "un_subscribe"]
    assert unsub == [("un_subscribe", ([{"instrument_token": "14366", "exchange_segment": "nse_cm"}], False, True))]


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
        yield {
            "type": "stock_feed",
            "data": [
                {
                    "tk": "14366",
                    "ts": "IDEA-EQ",
                    "e": "nse_cm",
                    "ltp": "9.4",
                    "v": "1000",
                    "bp": "9.39",
                    "sp": "9.41",
                    "oi": "0",
                    "ltt": "22/01/2025 14:28:16",
                },
            ],
        }
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
        yield {
            "type": "order_feed",
            "data": json.dumps(
                {
                    "data": {
                        "nOrdNo": "250122000624384",
                        "ordSt": "complete",
                        "trdSym": "IDEA-EQ",
                        "exSeg": "nse_cm",
                        "trnsTp": "B",
                        "prcTp": "L",
                        "prod": "NRML",
                        "qty": 1,
                        "prc": "9.39",
                        "fldQty": 1,
                        "avgPrc": "9.39",
                    }
                }
            ),
        }

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
