"""Selected options prerequisites through the installed SDK, never live I/O."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from copy import deepcopy
import json
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
from flinttrade_gateway.brokers.kotakneo_contracts import KotakContractResolver
from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession, _sdk_class, validate_read_envelope

pytestmark = pytest.mark.unit
SdkFactory = Callable[[dict[str, Any]], tuple[KotakNeoSdkSession, list[httpx.Request]]]


@pytest.fixture
def sdk_runtime() -> Iterator[SdkFactory]:
    """Yield real pinned SDK sessions backed only by the supplied inert HTTP response.

    Yields:
        Factory returning a facade and its exact HTTP request ledger. All
        facades are closed when the requesting test completes.
    """
    facades = []

    def build(response):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json=deepcopy(response))

        neo = _sdk_class()(consumer_key="synthetic", transport=httpx.MockTransport(respond))
        neo.configuration.edit_token = "synthetic"
        neo.configuration.edit_sid = "synthetic"
        neo.configuration.base_url = "https://example.invalid"
        facade = KotakNeoSdkSession.__new__(KotakNeoSdkSession)
        facade._neo = neo
        facade._closed = False
        facades.append(facade)
        return facade, requests

    yield build
    for facade in facades:
        facade.close()


def test_documented_statusless_expiries_at_pinned_facade(sdk_runtime: SdkFactory) -> None:
    """Preserve the documented status-less expiry envelope and exact request identity."""
    body = {"exchange": "nse_fo", "underlying": "NIFTY", "expiries": ["2026-06-25", "2026-06-30"]}
    facade, calls = sdk_runtime(body)
    assert facade.expiries("nse_fo", "NIFTY", "option") == body
    assert len(calls) == 1
    assert calls[0].method == "GET"
    assert calls[0].url.path.endswith("/watchlist/expiries")
    assert dict(calls[0].url.params) == {"exchange": "nse_fo", "underlying": "NIFTY", "instrument_type": "option"}


@pytest.mark.parametrize("patch", [
    {"exchange": "bse_fo"}, {"exchange": []}, {"exchange": {}}, {"exchange": None},
    {"underlying": "BANKNIFTY"}, {"expiries": None},
    {"expiries": ["2026-02-30"]}, {"expiries": ["2026-06-30", "2026-06-25"]},
    {"expiries": ["2026-06-25", "2026-06-25"]}, {"unexpected": "value"},
])
def test_expiries_invalid_or_wrong_identity_refuses(sdk_runtime: SdkFactory, patch: dict[str, Any]) -> None:
    """Refuse malformed or foreign expiry evidence after exactly one installed SDK read."""
    body = {"exchange": "nse_fo", "underlying": "NIFTY", "expiries": ["2026-06-25"]} | patch
    facade, calls = sdk_runtime(body)
    with pytest.raises(BrokerReadResponseInvalid):
        facade.expiries("nse_fo", "NIFTY", "option")
    assert len(calls) == 1


def trade_row(**changes: Any) -> dict[str, Any]:
    """Build a synthetic fill with independent quantity and timestamp observations.

    Args:
        **changes: Explicit field replacements for positive and refusal controls.

    Returns:
        A fresh native-shaped fill, not an observation of a real account.
    """
    # Documented independent qty/fldQty, empty tok and distinct event times.
    return {
        "nOrdNo": "synthetic-order", "flId": "207983744", "flLeg": 1,
        "exOrdId": "synthetic-exchange-order", "exSeg": "nse_cm", "trdSym": "IDEA-EQ",
        "trnsTp": "B", "prod": "NRML", "rptTp": "fill", "avgPrc": "9.39",
        "fldQty": 1, "qty": 0, "tok": "", "flDt": "22-Jan-2025", "flTm": "14:28:16",
        "exTm": "22-Jan-2025 14:28:01", "hsUpTm": "2025/01/22 14:28:16",
        "updRecvTm": 1737536296355319176,
    } | changes


@pytest.mark.asyncio
async def test_day_fill_retains_independent_observations_through_real_sdk(sdk_runtime: SdkFactory) -> None:
    """Keep native fill identity, timing and absent token facts through the real SDK."""
    from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
    from flinttrade_gateway.brokers._base import Session
    row = trade_row()
    facade, calls = sdk_runtime({"stat": "ok", "stCode": 200, "data": [row]})
    adapter = KotakNeoAdapter(client_factory=lambda _: facade)
    trades = await adapter.trade_book(Session("synthetic", 0, "synthetic", "kotakneo"))
    trade = trades[0]
    assert trade["quantity"] == "1"
    assert trade["fill_id"] == "207983744"
    assert trade["fill_leg"] == "1"
    assert trade["exchange_order_id"] == "synthetic-exchange-order"
    assert trade["broker_exchange_segment"] == "nse_cm"
    assert trade["trade_date"] == "22-Jan-2025"
    assert trade["fill_time"] == "14:28:16"
    assert trade["exchange_time"] == "22-Jan-2025 14:28:01"
    assert trade["broker_fields"] == row
    assert "instrument_id" not in trade
    assert len(calls) == 1 and calls[0].url.path == "/quick/user/trades"


@pytest.mark.parametrize("patch", [{"fldQty": 0}, {"fldQty": "1.5"}, {"qty": "bad"}, {"flPrc": "NaN"},
    {"flLeg": True}, {"tok": "bad"}, {"flId": " broken"}, {"rptTp": "order"}])
def test_bad_fill_secondary_observations_refuse(patch: dict[str, Any]) -> None:
    """Refuse unusable supplied fill observations rather than selecting convenient fields."""
    from flinttrade_gateway.brokers import kotakneo_mapping as M
    with pytest.raises(BrokerReadResponseInvalid):
        M.from_kotak_trade(trade_row(**patch))


def test_observed_token_is_not_guessed_or_replaced() -> None:
    """Preserve the supplied token and detached independent price and quantity values."""
    from flinttrade_gateway.brokers import kotakneo_mapping as M
    row = trade_row(tok="14366", flPrc="9.40")
    result = M.from_kotak_trade(row)
    assert result["instrument_id"] == "14366"
    assert result["price"] == "9.39"
    assert result["broker_fields"]["flPrc"] == "9.40"
    row["qty"] = 999
    assert result["broker_fields"]["qty"] == 0


@pytest.mark.asyncio
async def test_scoped_day_fill_duplicates_and_conflicts(sdk_runtime: SdkFactory) -> None:
    """Deduplicate only matching day identities and refuse conflicting fill observations."""
    from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
    from flinttrade_gateway.brokers._base import Session
    session = Session("synthetic", 0, "synthetic", "kotakneo")
    first = trade_row()
    other = trade_row(nOrdNo="another-order")
    another_date = trade_row(flDt="23-Jan-2025")
    facade, _ = sdk_runtime({"stat": "ok", "data": [first, first, other, another_date]})
    adapter = KotakNeoAdapter(client_factory=lambda _: facade)
    observation = await adapter.trade_book_observation(session)
    assert len(observation.rows) == 3
    assert observation.coverage["scope"] == "trading_day"
    assert observation.coverage["lifetime_complete"] is False
    assert observation.coverage["received_count"] == 4
    facade, _ = sdk_runtime({"stat": "ok", "data": [first, trade_row(fldQty=2)]})
    adapter = KotakNeoAdapter(client_factory=lambda _: facade)
    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.trade_book(session)
    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.order_trades(session, "another-order")


def margin_body(**changes: Any) -> dict[str, Any]:
    """Build independent synthetic margin fields without standalone or payment claims.

    Args:
        **changes: Native check-margin field replacements, including invalid controls.

    Returns:
        A new wrapped native margin observation with explicit RMS refusal.
    """
    return {"data": {"stat": "Ok", "stCode": 200, "ordMrgn": "15.500001", "reqdMrgn": "0.123456",
                     "avlCash": "38.190000", "insufFund": "0.000001", "rmsVldtd": "NOT_OK",
                     "mrgnUsd": "1.000001", "totMrgnUsd": "2.000001", "avlMrgn": "3.000001"} | changes}


def test_margin_exact_independent_observations_at_sdk(sdk_runtime: SdkFactory) -> None:
    """Keep exact independent money and RMS observations from the actual margin resource."""
    from flinttrade_gateway.brokers import kotakneo_mapping as M
    body = margin_body()
    facade, calls = sdk_runtime(body["data"])  # SDK wraps the raw check-margin response once.
    result = M.from_kotak_margin(facade.margin({"exchange_segment": "nse_fo", "price": "9.40",
        "order_type": "L", "product": "NRML", "quantity": "65", "instrument_token": "71472", "transaction_type": "B"}))
    assert result["required_margin"] == "15.500001"
    assert result["provider_additional_margin"] == "0.123456"
    assert result["used_margin"] == "1.000001"
    assert result["total_used_margin"] == "2.000001"
    assert result["available_margin"] == "3.000001"
    assert result["rms_validated"] == "NOT_OK"
    assert result["broker_fields"] == body["data"]
    assert calls[0].url.path == "/quick/user/check-margin"
    wire = json.loads(parse_qs(calls[0].content.decode())["jData"][0])
    assert wire["qty"] == "65" and wire["tok"] == "71472"


@pytest.mark.parametrize("value", ["MAYBE", " OK", "", None, True])
def test_margin_unknown_rms_is_not_success(value: Any) -> None:
    """Do not turn missing, malformed or unknown RMS observations into eligibility."""
    from flinttrade_gateway.brokers import kotakneo_mapping as M
    with pytest.raises(BrokerReadResponseInvalid):
        M.from_kotak_margin(margin_body(rmsVldtd=value))


def chain_body() -> dict[str, Any]:
    """Return a fresh synthetic option-chain response with independent common metadata."""
    return {"data": {"common_data": {"mktLot": "65", "multiplier": "1", "unlSymbol": "NIFTY",
            "exSeg": "nse_fo", "expiryDt": "2026-06-23"},
        "call": [{"instrument": {"neoSymbol": "nse_fo|71472", "symbol": "NIFTY26JUN22250CE",
                                  "optionType": "CE", "strikePrice": "22250"},
                  "quote": {"ltp": "166.7500"}}], "put": []}}


@pytest.mark.asyncio
async def test_chain_metadata_survives_existing_adapter(sdk_runtime: SdkFactory) -> None:
    """Retain chain metadata and the exact requested expiry through the existing adapter."""
    from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
    from flinttrade_gateway.brokers._base import Session
    body = chain_body()
    facade, calls = sdk_runtime(body)
    adapter = KotakNeoAdapter(client_factory=lambda _: facade)
    result = await adapter.option_chain_observation(Session("synthetic", 0, "synthetic", "kotakneo"),
        {"underlying": "NIFTY", "exchange": "NFO", "expiry": "2026-06-23"})
    assert result["broker_fields"]["common_data"] == body["data"]["common_data"]
    assert result["broker_fields"]["call"][0]["instrument"]["symbol"] == "NIFTY26JUN22250CE"
    assert result["strikes"][0]["ce_instrument_id"] == "nse_fo|71472"
    assert dict(calls[0].url.params)["expiry"] == "2026-06-23"


@pytest.mark.parametrize("patch", [{"mktLot": "0"}, {"mktLot": "1.5"}, {"multiplier": "NaN"}])
def test_bad_chain_contract_metadata_refuses(patch: dict[str, Any]) -> None:
    """Reject malformed supplied contract metadata without inventing a lot or multiplier."""
    from flinttrade_gateway.brokers import kotakneo_mapping as M
    body = chain_body()
    body["data"]["common_data"].update(patch)
    with pytest.raises(BrokerReadResponseInvalid):
        M.from_kotak_option_chain(
            body, underlying="NIFTY", exchange="NFO", sdk_exchange="nse_fo", requested_expiry="2026-06-23",
        )


def test_confirmed_chain_cannot_omit_expiry_and_retarget_nearest() -> None:
    """A confirmed expiry cannot silently become a nearest-expiry request."""
    from flinttrade_gateway.brokers import kotakneo_mapping as M
    with pytest.raises(M.KotakNeoMappingError):
        M.to_option_chain_request({"underlying": "NIFTY", "exchange": "NFO", "confirmed_expiry": "2026-06-23"})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["place", "margin"])
async def test_underlying_never_firstmatched_for_place_or_margin(sdk_runtime: SdkFactory, operation: str) -> None:
    """Never select the first underlying search hit for a placement or margin request."""
    from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
    from flinttrade_gateway.brokers._base import Session, ROUTER_TOKEN
    from flinttrade_core.models import Order
    from flinttrade_core.exceptions import BrokerError
    facade, calls = sdk_runtime({"stat": "Ok", "stCode": 200, "nOrdNo": "synthetic-order"})
    facade.search_scrip = lambda *args: [
        {"pSymbol": "71472", "pTrdSymbol": "NIFTY26JUN22250CE", "pSymbolName": "NIFTY", "pExchSeg": "nse_fo"},
        {"pSymbol": "71473", "pTrdSymbol": "NIFTY26JUL22250PE", "pSymbolName": "NIFTY", "pExchSeg": "nse_fo"},
    ]
    adapter = KotakNeoAdapter(client_factory=lambda _: facade)
    order = Order(
        symbol="NIFTY", exchange="NFO", action="BUY", product="NRML", pricetype="LIMIT", quantity="65", price="9.40",
    )
    with pytest.raises(BrokerError):
        if operation == "place":
            await adapter.place_order(
                Session("synthetic", 0, "synthetic", "kotakneo"), order, _router_token=ROUTER_TOKEN,
            )
        else:
            await adapter.margin_calculator(Session("synthetic", 0, "synthetic", "kotakneo"), order)
    assert calls == [], "Ambiguous underlying reached an actual SDK resource"


def master_row(*, exchange: str = "NFO", **changes: Any) -> dict[str, Any]:
    """Build a synthetic exact listing with venue-specific native instrument class.

    Args:
        exchange: Synthetic venue; NFO is the default fixture, not an order default.
        **changes: Explicit native field replacements for each control.

    Returns:
        A fresh dated listing; its lot and token are not live master facts.
    """
    from datetime import datetime, timezone
    # Synthetic dated listing; these lot values do not describe a live master.
    segment, underlying, lot = ("nse_fo", "NIFTY", "65") if exchange == "NFO" else ("bse_fo", "SENSEX", "25")
    epoch = int(datetime(2099, 6, 23, 10, tzinfo=timezone.utc).timestamp())
    if exchange == "NFO":
        epoch -= 315511200
    return {"pSymbol": "71472", "pTrdSymbol": underlying + "-EXACT-LISTED-CE", "pExchSeg": segment,
        "pSymbolName": underlying, "pOptionType": "CE", "pInstType": "OPTIDX" if exchange == "NFO" else "IO",
        "lExpiryDate": str(epoch), "pExpiryDate": str(epoch), "dStrikePrice;": "2225000",
        "lLotSize": lot, "dTickSize": "5", "lPrecision": "2"} | changes


def listed_resolver(rows: list[dict[str, Any]], **changes: Any) -> KotakContractResolver:
    """Build an immutable resolver from explicitly supplied synthetic rows.

    Args:
        rows: Exact synthetic native records; no master is fetched.
        **changes: Explicit source/revision/time replacements for the fixture.

    Returns:
        The real resolver with labelled synthetic provenance and validity.
    """
    from datetime import datetime, timezone
    from flinttrade_gateway.brokers.kotakneo_contracts import KotakContractResolver
    return KotakContractResolver.from_records(rows, **({"source": "https://example.invalid/dated-master.csv",
        "revision": "synthetic-v1", "observed_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "valid_until": datetime(2099, 1, 1, tzinfo=timezone.utc)} | changes))


@pytest.mark.asyncio
@pytest.mark.parametrize("exchange", ["NFO", "BFO"])
async def test_exact_listed_contract_lots_reach_real_place_and_margin(sdk_runtime: SdkFactory, exchange: str) -> None:
    """Keep exact listing evidence and units through both installed SDK resources."""
    from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
    from flinttrade_gateway.brokers._base import Session, ROUTER_TOKEN
    from flinttrade_core.models import Order
    from flinttrade_core.broker_read_port import LotSizeRequest
    row = master_row(exchange=exchange)
    resolver = listed_resolver([row])
    facade, calls = sdk_runtime({"stat": "Ok", "stCode": 200, "nOrdNo": "synthetic-order"})
    adapter = KotakNeoAdapter(client_factory=lambda _: facade, contract_resolver=resolver)
    session = Session("synthetic", 0, "synthetic", "kotakneo")
    lots = await adapter.instrument_lot_sizes(session, LotSizeRequest(exchange, (row["pTrdSymbol"],)))
    assert lots[0]["lot_size"] == int(row["lLotSize"])
    assert lots[0]["instrument_id"] == row["pSymbol"]
    order = Order(symbol=row["pTrdSymbol"], exchange=exchange, action="BUY", product="NRML",
                  pricetype="LIMIT", quantity=row["lLotSize"], price="9.40")
    evidence = adapter.preflight_order(order)
    assert evidence["expiry"] == "2099-06-23" and evidence["strike"] == "22250"
    assert evidence["raw_tick_size"] == "5" and evidence["raw_precision"] == "2"
    assert evidence["tick_scale_verified"] is False
    assert evidence["tick_source"]["kind"] == "independent_exchange_rule"
    assert evidence["broker_fields"] == row
    assert await adapter.place_order(session, order, _router_token=ROUTER_TOKEN) == "synthetic-order"
    wire = json.loads(parse_qs(calls[0].content.decode())["jData"][0])
    assert wire["ts"] == row["pTrdSymbol"] and wire["qt"] == row["lLotSize"]
    assert wire["es"] == row["pExchSeg"]
    facade2, calls2 = sdk_runtime(margin_body()["data"])
    adapter2 = KotakNeoAdapter(client_factory=lambda _: facade2, contract_resolver=resolver)
    margin = await adapter2.margin_calculator(session, order)
    assert margin["contract"]["source_revision"] == "synthetic-v1"
    assert margin["order_margin"] == "15.500001"
    assert json.loads(parse_qs(calls2[0].content.decode())["jData"][0])["tok"] == row["pSymbol"]


@pytest.mark.asyncio
@pytest.mark.parametrize("exchange", ["NFO", "BFO"])
@pytest.mark.parametrize("change", [
    {"quantity": "1"}, {"price": "9.41"}, {"product": "CNC"},
    {"pricetype": "SL-M", "trigger_price": "9.40"}, {"pricetype": "MARKET", "price": "0"},
    {"pricetype": "SL", "price": "9.40", "trigger_price": "9.45"},
])
async def test_selected_option_preflight_refuses_before_sdk(
    sdk_runtime: SdkFactory, exchange: str, change: dict[str, Any],
) -> None:
    """Reject invalid selected-option terms before any SDK placement or margin request."""
    from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
    from flinttrade_gateway.brokers._base import Session, ROUTER_TOKEN
    from flinttrade_core.models import Order
    from flinttrade_core.exceptions import UnsupportedCapabilityError
    row = master_row(exchange=exchange)
    facade, calls = sdk_runtime({"stat": "Ok", "stCode": 200, "nOrdNo": "synthetic-order"})
    adapter = KotakNeoAdapter(client_factory=lambda _: facade, contract_resolver=listed_resolver([row]))
    order = Order(**({"symbol": row["pTrdSymbol"], "exchange": exchange, "action": "BUY", "product": "NRML",
                     "pricetype": "LIMIT", "quantity": row["lLotSize"], "price": "9.40"} | change))
    with pytest.raises(UnsupportedCapabilityError):
        adapter.preflight_order(order)
    with pytest.raises(UnsupportedCapabilityError):
        await adapter.place_order(Session("synthetic", 0, "synthetic", "kotakneo"), order, _router_token=ROUTER_TOKEN)
    with pytest.raises(UnsupportedCapabilityError):
        await adapter.margin_calculator(Session("synthetic", 0, "synthetic", "kotakneo"), order)
    assert calls == []


@pytest.mark.parametrize("side,trigger,price,allowed", [
    ("BUY", "50", "60", True), ("BUY", "50", "60.05", False),
    ("SELL", "50", "40", True), ("SELL", "50", "39.95", False),
    ("BUY", "100", "120", True), ("BUY", "100", "120.05", False),
    ("SELL", "100", "80", True), ("SELL", "100", "79.95", False),
])
def test_dated_bse_stop_limit_distance_at_existing_builders(
    side: str, trigger: str, price: str, allowed: bool,
) -> None:
    """Apply the dated BSE stop-distance boundary consistently at every existing builder."""
    from flinttrade_gateway.brokers import kotakneo_mapping as M
    from flinttrade_core.models import Order
    row = master_row(exchange="BFO")
    order = Order(symbol=row["pTrdSymbol"], exchange="BFO", action=side, product="NRML", pricetype="SL",
                  quantity=row["lLotSize"], price=price, trigger_price=trigger)
    changes = {"symbol": order.symbol, "exchange": "BFO", "action": side, "product": "NRML", "pricetype": "SL",
               "quantity": order.quantity, "price": price, "trigger_price": trigger}
    for build in (
        lambda: M.validate_v3_order(order), lambda: M.to_place_order_params(order, order.symbol),
        lambda: M.to_margin_params(order, row["pSymbol"]), lambda: M.to_modify_order_params("synthetic-order", changes),
    ):
        if allowed:
            build()
        else:
            with pytest.raises(M.KotakNeoMappingError):
                build()


def test_nse_future_slm_and_cash_profiles_are_not_option_restrictions() -> None:
    """Keep valid NSE future and cash SL-M shapes outside the selected-option restriction."""
    from flinttrade_gateway.brokers import kotakneo_mapping as M
    from flinttrade_core.models import Order
    for exchange, symbol, product in (("NFO", "NIFTY99JUNFUT", "NRML"), ("NSE", "IDEA", "CNC")):
        order = Order(symbol=symbol, exchange=exchange, action="BUY", product=product,
                      pricetype="SL-M", quantity="1", trigger_price="9.41")
        assert M.to_place_order_params(order, symbol)["order_type"] == "SL-M"


@pytest.mark.asyncio
async def test_modify_checks_listed_lot_and_refresh_is_compare_and_swap(sdk_runtime: SdkFactory) -> None:
    """Validate replacement units and reject stale compare-and-swap refresh attempts."""
    from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
    from flinttrade_gateway.brokers._base import Session, ROUTER_TOKEN
    from flinttrade_core.exceptions import UnsupportedCapabilityError
    row = master_row()
    first = listed_resolver([row])
    second = listed_resolver([row | {"lLotSize": "25"}], revision="synthetic-v2")
    facade, calls = sdk_runtime({"stat": "Ok", "stCode": 200, "nOrdNo": "synthetic-order"})
    adapter = KotakNeoAdapter(client_factory=lambda _: facade, contract_resolver=first)
    session = Session("synthetic", 0, "synthetic", "kotakneo")
    change = {"symbol": row["pTrdSymbol"], "exchange": "NFO", "action": "BUY", "product": "NRML",
              "pricetype": "LIMIT", "price": "9.40", "quantity": "1"}
    with pytest.raises(UnsupportedCapabilityError):
        await adapter.modify_order(session, "synthetic-order", change, _router_token=ROUTER_TOKEN)
    assert calls == []
    adapter.replace_contract_resolver(second, expected_revision="synthetic-v1")
    with pytest.raises(BrokerReadResponseInvalid):
        adapter.replace_contract_resolver(first, expected_revision="synthetic-v1")
    await adapter.modify_order(session, "synthetic-order", change | {"quantity": "25"}, _router_token=ROUTER_TOKEN)
    assert len(calls) == 1
    wire = json.loads(parse_qs(calls[0].content.decode())["jData"][0])
    assert wire["qt"] == "25" and "ts" not in wire


@pytest.mark.asyncio
async def test_refresh_after_preflight_cannot_change_contract_at_dispatch(
    sdk_runtime: SdkFactory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refresh before executor admission cannot silently retarget the signed contract."""
    from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
    from flinttrade_gateway.brokers._base import Session, ROUTER_TOKEN
    from flinttrade_core.models import Order
    from flinttrade_core.exceptions import UnsupportedCapabilityError
    row = master_row()
    facade, calls = sdk_runtime({"stat": "Ok", "stCode": 200, "nOrdNo": "synthetic-order"})
    adapter = KotakNeoAdapter(client_factory=lambda _: facade, contract_resolver=listed_resolver([row]))
    original_call = adapter._call
    async def refresh_then_call(fn, *args, **kwargs):
        adapter.replace_contract_resolver(
            listed_resolver([row | {"pSymbol": "999"}], revision="synthetic-v2"), expected_revision="synthetic-v1",
        )
        return await original_call(fn, *args, **kwargs)
    monkeypatch.setattr(adapter, "_call", refresh_then_call)
    order = Order(
        symbol=row["pTrdSymbol"], exchange="NFO", action="BUY", product="NRML",
        pricetype="LIMIT", quantity="65", price="9.40",
    )
    with pytest.raises(UnsupportedCapabilityError):
        await adapter.place_order(Session("synthetic", 0, "synthetic", "kotakneo"), order, _router_token=ROUTER_TOKEN)
    assert calls == []


def test_scrip_observation_never_labels_raw_tick_as_inr_or_missing_lot_zero() -> None:
    """Preserve raw tick units and omit unavailable lots without making numeric defaults."""
    from flinttrade_gateway.brokers import kotakneo_mapping as M
    row = master_row()
    result = M.from_kotak_scrip(row)
    assert result["raw_tick_size"] == "5"
    assert "tick_size" not in result
    assert result["broker_fields"]["dStrikePrice;"] == "2225000"
    del row["lLotSize"]
    assert "lot_size" not in M.from_kotak_scrip(row)


@pytest.mark.parametrize("patch", [{"pSymbolName": "BANKNIFTY"}, {"pExchSeg": "bse_fo"},
    {"pExpiryDate": "23Jun2098"}, {"lLotSize": "0"}, {"lLotSize": "1.5"}, {"dTickSize": "NaN"}])
def test_listed_contract_adversarial_master_refuses(patch: dict[str, Any]) -> None:
    """Reject inconsistent or malformed listing fields before constructing authority."""
    with pytest.raises(BrokerReadResponseInvalid):
        listed_resolver([master_row(**patch)])


def test_master_literal_strike_key_duplicates_staleness_and_epoch_are_not_guessed() -> None:
    """Require literal strike schema, unique addresses, exact venue and fresh dated evidence."""
    from datetime import datetime, timezone
    row = master_row()
    wrong = dict(row)
    wrong["dStrikePrice"] = wrong.pop("dStrikePrice;")
    for rows in ([wrong], [row, row], [row, row | {"pTrdSymbol": "OTHER-CE"}]):
        with pytest.raises(BrokerReadResponseInvalid):
            listed_resolver(rows)
    resolver = listed_resolver([row])
    for symbol, exchange, when in (("NIFTY", "NFO", 2027), (row["pTrdSymbol"], "BFO", 2027),
                                   (row["pTrdSymbol"], "NFO", 2100), (row["pTrdSymbol"], "NFO", 2025)):
        with pytest.raises(BrokerReadResponseInvalid):
            resolver.resolve(symbol, exchange, now=datetime(when, 1, 1, tzinfo=timezone.utc))


@pytest.mark.asyncio
async def test_legacy_read_returns_remain_exact_shared_types(sdk_runtime: SdkFactory) -> None:
    """Rich observation companions must not change the exact legacy shared return types."""
    from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
    from flinttrade_gateway.brokers._base import Session
    from flinttrade_core.models import OptionChain
    from flinttrade_gateway.broker_read_service import BrokerReadOwner
    session = Session("synthetic", 0, "synthetic", "kotakneo")
    facade, _ = sdk_runtime(chain_body())
    adapter = KotakNeoAdapter(client_factory=lambda _: facade)
    chain = await adapter.option_chain(session, {"underlying": "NIFTY", "exchange": "NFO", "expiry": "2026-06-23"})
    assert type(chain) is OptionChain
    assert BrokerReadOwner._record(chain, OptionChain)["expiry"] == "2026-06-23"
    facade, _ = sdk_runtime({"stat": "ok", "data": [trade_row()]})
    adapter = KotakNeoAdapter(client_factory=lambda _: facade)
    assert type(await adapter.trade_book(session)) is list


@pytest.mark.asyncio
@pytest.mark.parametrize("token", ["", "14366"])
async def test_empty_trade_token_resolves_only_exact_same_order_evidence(sdk_runtime: SdkFactory, token: str) -> None:
    """Join only explicit same-order evidence and preserve the original raw token value."""
    from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
    from flinttrade_gateway.brokers._base import Session
    facade, calls = sdk_runtime({"stat": "ok", "data": [trade_row(tok=token)]})
    adapter = KotakNeoAdapter(client_factory=lambda _: facade)
    session = Session("synthetic", 0, "synthetic", "kotakneo")
    evidence = {"nOrdNo": "synthetic-order", "trdSym": "IDEA-EQ", "exSeg": "nse_cm", "tok": "14366"}
    result = await adapter.trade_book_observation(session, order_evidence=[evidence])
    assert result.rows[0]["instrument_id"] == "14366"
    assert result.rows[0]["broker_fields"]["tok"] == token
    assert result.rows[0]["instrument_resolution"]["source"] == "same_order_report"
    assert len(calls) == 1  # No hidden extra order/master request.
    for bad in ([evidence | {"trdSym": "OTHER"}], [evidence | {"exSeg": "bse_cm"}], [evidence, evidence]):
        with pytest.raises(BrokerReadResponseInvalid):
            await adapter.trade_book_observation(session, order_evidence=bad)
    unmatched = await adapter.trade_book_observation(session, order_evidence=[evidence | {"nOrdNo": "other-order"}])
    assert ("instrument_id" in unmatched.rows[0]) == bool(token)


@pytest.mark.asyncio
async def test_contract_resolver_is_used_by_token_and_quote_callers(sdk_runtime: SdkFactory) -> None:
    """Listed token and quote reads must not fall back to ambiguous underlying search."""
    from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
    from flinttrade_gateway.brokers._base import Session
    row = master_row()
    facade, calls = sdk_runtime({"data": [{"exchange_token": "71472", "exchange_segment": "nse_fo",
                                         "trading_symbol": row["pTrdSymbol"], "ltp": "9.4"}]})
    facade.search_scrip = lambda *args: pytest.fail("Exact listed symbol must not use underlying search")
    adapter = KotakNeoAdapter(client_factory=lambda _: facade, contract_resolver=listed_resolver([row]))
    session = Session("synthetic", 0, "synthetic", "kotakneo")
    assert await adapter._resolve_token(session, row["pTrdSymbol"], "NFO") == "71472"
    rows = await adapter._fetch_bound_quote_rows(session, ["NFO:" + row["pTrdSymbol"]])
    assert rows[0][1:] == (row["pTrdSymbol"], "NFO")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_selected_option_cannot_be_introduced_by_legacy_symbol_alias(sdk_runtime: SdkFactory) -> None:
    """A legacy alias cannot introduce a selected option after shape-only preflight."""
    from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
    from flinttrade_gateway.brokers._base import Session, ROUTER_TOKEN
    from flinttrade_core.models import Order
    from flinttrade_core.exceptions import UnsupportedCapabilityError
    facade, calls = sdk_runtime({"stat": "Ok", "stCode": 200, "nOrdNo": "synthetic-order"})
    adapter = KotakNeoAdapter(client_factory=lambda _: facade, symbol_resolver=lambda *args: master_row()["pTrdSymbol"])
    order = Order(
        symbol="UNREVIEWED-ALIAS", exchange="NFO", action="BUY", product="NRML",
        pricetype="LIMIT", quantity="1", price="9.40",
    )
    with pytest.raises(UnsupportedCapabilityError):
        await adapter.place_order(Session("synthetic", 0, "synthetic", "kotakneo"), order, _router_token=ROUTER_TOKEN)
    assert calls == []


def test_master_oversized_raw_primitive_is_a_canonical_refusal() -> None:
    """Oversized raw integer evidence is a canonical refusal, not a conversion accident."""
    with pytest.raises(BrokerReadResponseInvalid):
        listed_resolver([master_row(lLotSize=10 ** 5000)])


def test_chain_secondary_text_metadata_is_validated() -> None:
    """Validate secondary chain text before preserving it as native evidence."""
    from flinttrade_gateway.brokers import kotakneo_mapping as M
    body = chain_body()
    body["data"]["call"][0]["instrument"]["moneyness"] = {"wrong": "type"}
    with pytest.raises(BrokerReadResponseInvalid):
        M.from_kotak_option_chain(
            body, underlying="NIFTY", exchange="NFO", sdk_exchange="nse_fo", requested_expiry="2026-06-23",
        )


@pytest.mark.asyncio
async def test_opaque_listed_symbol_still_has_option_modify_constraints(sdk_runtime: SdkFactory) -> None:
    """Opaque listed symbols retain lot-qualified modification restrictions."""
    from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
    from flinttrade_gateway.brokers._base import Session, ROUTER_TOKEN
    from flinttrade_core.exceptions import UnsupportedCapabilityError
    row = master_row(pTrdSymbol="opaque-listed-contract")
    facade, calls = sdk_runtime({"stat": "Ok", "stCode": 200, "nOrdNo": "synthetic-order"})
    adapter = KotakNeoAdapter(client_factory=lambda _: facade, contract_resolver=listed_resolver([row]))
    with pytest.raises(UnsupportedCapabilityError):
        await adapter.modify_order(Session("synthetic", 0, "synthetic", "kotakneo"), "synthetic-order",
            {"symbol": row["pTrdSymbol"], "exchange": "NFO", "action": "BUY", "product": "NRML",
             "pricetype": "LIMIT", "price": "9.40", "quantity": "1"}, _router_token=ROUTER_TOKEN)
    assert calls == []


def test_statusless_exception_does_not_admit_other_reads() -> None:
    """The expiry-envelope exception never relaxes success requirements for other resources."""
    for operation in ("order_report", "trade_report", "positions", "margin_required"):
        with pytest.raises(BrokerReadResponseInvalid):
            validate_read_envelope({"exchange": "nse_fo", "underlying": "NIFTY", "expiries": []}, operation=operation)
