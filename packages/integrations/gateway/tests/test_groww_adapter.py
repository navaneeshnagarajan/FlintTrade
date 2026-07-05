"""Tests for the Groww native REST adapter (mock transport; no creds needed)."""

from __future__ import annotations

import hashlib
import time
from typing import Any

import pytest

from flinttrade_core.exceptions import BrokerError, DataError, SessionExpired
from flinttrade_core.models import Order
from flinttrade_engine.safety import SafetyBypassError
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.groww import GrowwAdapter, _ROUTER_TOKEN

pytestmark = pytest.mark.unit


class MockGrowwTransport:
    """Groww-style transport that records every request."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.expired = False
        self.forbid_market_data = False

    def __call__(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> tuple[int, Any]:
        self.calls.append({
            "method": method,
            "url": url,
            "path": url.removeprefix("https://api.groww.in"),
            "headers": headers,
            "params": params or {},
            "json_body": json_body,
        })
        if self.expired:
            return 401, {"status": "FAILURE", "message": "Access token expired"}

        path = self.calls[-1]["path"]
        if self.forbid_market_data and (
            path.startswith("/v1/live-data/")
            or path.startswith("/v1/historical/")
            or path.startswith("/v1/option-chain/")
            or url == "https://growwapi-assets.groww.in/instruments/instrument.csv"
        ):
            return 403, {"status": "FAILURE", "error": {"code": "403", "message": "Access forbidden for this request."}}
        if path == "/v1/token/api/access":
            return 200, {"status": "SUCCESS", "payload": {"token": "MINTED_TOKEN"}}
        if path == "/v1/order/create":
            return 200, {"status": "SUCCESS", "payload": {"groww_order_id": "GROWWOID1"}}
        if path == "/v1/order/modify":
            return 200, {"status": "SUCCESS", "payload": {"groww_order_id": "GROWWOID1"}}
        if path == "/v1/order/cancel":
            return 200, {"status": "SUCCESS", "payload": {"groww_order_id": "GROWWOID1"}}
        if path.startswith("/v1/order-advance/cancel/"):
            return 200, {"status": "SUCCESS", "payload": {"smart_order_id": "GTT1"}}
        if path == "/v1/order/list":
            cash_rows = [{
                "groww_order_id": "GROWWOID1",
                "trading_symbol": "RELIANCE",
                "exchange": "NSE",
                "segment": "CASH",
                "transaction_type": "BUY",
                "order_type": "LIMIT",
                "product": "CNC",
                "quantity": 3,
                "price": 2900,
                "order_status": "OPEN",
            }]
            commodity_rows = [{
                "groww_order_id": "GROWWMCX1",
                "trading_symbol": "CRUDEOIL25JANFUT",
                "exchange": "MCX",
                "segment": "COMMODITY",
                "transaction_type": "BUY",
                "order_type": "LIMIT",
                "product": "NRML",
                "quantity": 1,
                "price": 6200,
                "order_status": "OPEN",
            }]
            segment = (params or {}).get("segment")
            rows = cash_rows if segment == "CASH" else commodity_rows if segment == "COMMODITY" else []
            return 200, {"status": "SUCCESS", "payload": {"order_list": rows}}
        if path == "/v1/positions/user":
            return 200, {"status": "SUCCESS", "payload": {"positions": [{
                "trading_symbol": "NIFTY26JUN24000CE",
                "exchange": "NSE",
                "segment": "FNO",
                "product": "MIS",
                "quantity": 50,
                "average_price": 120.5,
                "ltp": 125.0,
                "pnl": 225,
            }]}}
        if path == "/v1/holdings/user":
            return 200, {"status": "SUCCESS", "payload": {"holdings": [{
                "trading_symbol": "TCS",
                "exchange": "NSE",
                "quantity": 2,
                "average_price": 3500,
                "ltp": 3520,
                "isin": "INE467B01029",
            }]}}
        if path == "/v1/margins/detail/user":
            return 200, {"status": "SUCCESS", "payload": {
                "clear_cash": 50000,
                "collateral_available": 10000,
                "net_margin_used": 2500,
            }}
        if path == "/v1/user/detail":
            return 200, {"status": "SUCCESS", "payload": {"name": "Test User", "user_id": "G1"}}
        if path == "/v1/live-data/quote":
            return 200, {"status": "SUCCESS", "payload": {
                "last_price": 2905.5,
                "open": 2890,
                "high": 2910,
                "low": 2880,
                "close": 2899,
                "volume": 12345,
            }}
        if path == "/v1/live-data/ltp":
            keys = [k for k in str((params or {}).get("exchange_symbols", "")).split(",") if k]
            return 200, {"status": "SUCCESS", "payload": {key: 2905.5 for key in keys}}
        if path == "/v1/historical/candle/range":
            return 200, {"status": "SUCCESS", "payload": {"candles": [
                ["2026-07-01 09:15:00", 100, 105, 99, 104, 1000],
            ]}}
        if url == "https://growwapi-assets.groww.in/instruments/instrument.csv":
            return 200, "trading_symbol,exchange,segment\nRELIANCE,NSE,CASH\n"
        raise AssertionError(f"unexpected Groww request: {method} {url}")


def _adapter(transport: MockGrowwTransport) -> GrowwAdapter:
    return GrowwAdapter(http_factory=lambda: transport)


async def _session(adapter: GrowwAdapter):
    return await adapter.login({"user_id": "G1", "access_token": "TOK"})


@pytest.mark.asyncio
async def test_login_returns_daily_expiring_session() -> None:
    adapter = _adapter(MockGrowwTransport())
    before = time.time()
    session = await _session(adapter)
    assert session.adapter_id == "groww"
    assert session.account_id == "G1"
    assert session.access_token == "TOK"
    assert session.extra["auth_method"] == "access_token"
    assert before < session.expires_at <= before + 24 * 3600 + 60


@pytest.mark.asyncio
async def test_login_requires_access_token() -> None:
    with pytest.raises(BrokerError, match="access_token, api_key"):
        await GrowwAdapter().login({"user_id": "G1"})


@pytest.mark.asyncio
async def test_login_requires_complete_api_key_credentials() -> None:
    with pytest.raises(BrokerError, match="exactly one of api_secret or totp"):
        await GrowwAdapter().login({"user_id": "G1", "api_key": "KEY"})


@pytest.mark.asyncio
async def test_login_rejects_ambiguous_groww_token_material() -> None:
    with pytest.raises(BrokerError, match="exactly one of api_secret or totp"):
        await GrowwAdapter().login(
            {"user_id": "G1", "api_key": "KEY", "api_secret": "SECRET", "totp": "123456"}
        )


@pytest.mark.asyncio
async def test_api_key_secret_login_mints_access_token() -> None:
    transport = MockGrowwTransport()
    adapter = _adapter(transport)
    session = await adapter.login({"user_id": "G1", "api_key": "APIKEY", "api_secret": "SECRET"})

    assert session.access_token == "MINTED_TOKEN"
    assert session.extra["auth_method"] == "api_key_secret"
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/v1/token/api/access"
    assert call["headers"]["Authorization"] == "Bearer APIKEY"
    assert call["json_body"]["key_type"] == "approval"
    assert str(call["json_body"]["timestamp"]).isdigit()
    assert call["json_body"]["checksum"] == hashlib.sha256(
        f"SECRET{call['json_body']['timestamp']}".encode("utf-8")
    ).hexdigest()


@pytest.mark.asyncio
async def test_api_key_totp_login_mints_access_token() -> None:
    transport = MockGrowwTransport()
    adapter = _adapter(transport)
    session = await adapter.login({"user_id": "G1", "api_key": "APIKEY", "totp": "123456"})

    assert session.access_token == "MINTED_TOKEN"
    assert session.extra["auth_method"] == "api_key_totp"
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/v1/token/api/access"
    assert call["headers"]["Authorization"] == "Bearer APIKEY"
    assert call["json_body"] == {"key_type": "totp", "totp": "123456"}


def test_replay_credentials_drops_groww_totp_and_keeps_minted_token() -> None:
    adapter = GrowwAdapter(http_factory=lambda: MockGrowwTransport())
    session = Session(
        access_token="MINTED_TOKEN",
        expires_at=9e9,
        account_id="G1",
        adapter_id="groww",
        extra={"auth_method": "api_key_totp"},
    )
    replay = adapter.replay_credentials({"user_id": "G1", "api_key": "APIKEY", "totp": "123456"}, session)
    assert replay == {"user_id": "G1", "api_key": "APIKEY", "access_token": "MINTED_TOKEN"}


def test_replay_credentials_keeps_replayable_groww_secret_material_unchanged() -> None:
    adapter = GrowwAdapter(http_factory=lambda: MockGrowwTransport())
    session = Session(
        access_token="MINTED_TOKEN",
        expires_at=9e9,
        account_id="G1",
        adapter_id="groww",
        extra={"auth_method": "api_key_secret"},
    )
    original = {"user_id": "G1", "api_key": "APIKEY", "api_secret": "SECRET"}
    assert adapter.replay_credentials(original, session) == original


@pytest.mark.asyncio
async def test_place_order_is_gated_before_http() -> None:
    transport = MockGrowwTransport()
    adapter = _adapter(transport)
    session = await _session(adapter)
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS", quantity="1")
    with pytest.raises(SafetyBypassError):
        await adapter.place_order(session, order)
    assert transport.calls == []


@pytest.mark.asyncio
async def test_place_order_posts_groww_payload_with_router_token() -> None:
    transport = MockGrowwTransport()
    adapter = _adapter(transport)
    session = await _session(adapter)
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT", product="CNC", quantity="3", price="2900")
    order_id = await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert order_id == "GROWWOID1"
    call = transport.calls[0]
    assert call["path"] == "/v1/order/create"
    assert call["headers"]["Authorization"] == "Bearer TOK"
    assert call["json_body"] == {
        "trading_symbol": "RELIANCE",
        "quantity": 3,
        "validity": "DAY",
        "exchange": "NSE",
        "segment": "CASH",
        "product": "CNC",
        "order_type": "LIMIT",
        "transaction_type": "BUY",
        "price": 2900.0,
        "order_reference_id": "Flint",
    }


@pytest.mark.asyncio
async def test_modify_cancel_and_smart_cancel_are_gated_and_mapped() -> None:
    transport = MockGrowwTransport()
    adapter = _adapter(transport)
    session = await _session(adapter)
    await adapter.modify_order(session, "GROWWOID1", {"quantity": 2, "price": 2910}, _router_token=_ROUTER_TOKEN)
    await adapter.cancel_order(session, "GROWWOID1", segment="FNO", _router_token=_ROUTER_TOKEN)
    await adapter.cancel_smart_order(session, "GTT1", segment="CASH", smart_order_type="GTT", _router_token=_ROUTER_TOKEN)
    assert [call["path"] for call in transport.calls] == [
        "/v1/order/modify",
        "/v1/order/cancel",
        "/v1/order-advance/cancel/CASH/GTT/GTT1",
    ]
    assert transport.calls[0]["json_body"] == {"groww_order_id": "GROWWOID1", "segment": "CASH", "quantity": 2, "price": 2910.0}
    assert transport.calls[1]["json_body"] == {"groww_order_id": "GROWWOID1", "segment": "FNO"}


@pytest.mark.asyncio
async def test_reads_map_groww_envelopes() -> None:
    transport = MockGrowwTransport()
    adapter = _adapter(transport)
    session = await _session(adapter)
    orders = await adapter.order_book(session)
    positions = await adapter.positions(session)
    holdings = await adapter.holdings(session)
    funds = await adapter.funds(session)
    profile = await adapter.profile(session)
    quotes = await adapter.quotes(session, ["NSE:RELIANCE"])
    ltps = await adapter.ltp(session, ["NSE:RELIANCE"])
    candles = await adapter.historical(session, {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "interval": "1m",
        "from_date": "2026-07-01 09:15:00",
        "to_date": "2026-07-01 09:16:00",
    })
    instruments = await adapter.instruments(session)

    assert orders[0]["orderid"] == "GROWWOID1"
    assert positions[0]["exchange"] == "NFO"
    assert holdings[0]["isin"] == "INE467B01029"
    assert funds["availablecash"] == 50000.0
    assert profile["user_id"] == "G1"
    assert quotes[0].ltp == 2905.5
    assert ltps == {"NSE:RELIANCE": 2905.5}
    assert candles.bars[0].close == 104.0
    assert instruments == [{"trading_symbol": "RELIANCE", "exchange": "NSE", "segment": "CASH"}]
    instrument_call = next(call for call in transport.calls if call["url"] == "https://growwapi-assets.groww.in/instruments/instrument.csv")
    assert instrument_call["headers"] == {"Accept": "text/csv"}


@pytest.mark.asyncio
async def test_mcx_commodity_surface_uses_groww_commodity_segment() -> None:
    transport = MockGrowwTransport()
    adapter = _adapter(transport)
    session = await _session(adapter)
    order = Order(
        symbol="CRUDEOIL25JANFUT",
        action="BUY",
        exchange="MCX",
        pricetype="LIMIT",
        product="NRML",
        quantity="1",
        price="6200",
    )

    await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    await adapter.quotes(session, ["MCX:CRUDEOIL25JANFUT"])
    ltp = await adapter.ltp(session, ["MCX:CRUDEOIL25JANFUT"])
    await adapter.historical(session, {
        "symbol": "CRUDEOIL25JANFUT",
        "exchange": "MCX",
        "interval": "5m",
        "from_date": "2026-07-01 09:15:00",
        "to_date": "2026-07-01 09:20:00",
    })
    orders = await adapter.order_book(session)

    place_call = next(call for call in transport.calls if call["path"] == "/v1/order/create")
    assert place_call["json_body"]["exchange"] == "MCX"
    assert place_call["json_body"]["segment"] == "COMMODITY"
    quote_call = next(call for call in transport.calls if call["path"] == "/v1/live-data/quote")
    assert quote_call["params"] == {
        "exchange": "MCX",
        "segment": "COMMODITY",
        "trading_symbol": "CRUDEOIL25JANFUT",
    }
    ltp_call = next(call for call in transport.calls if call["path"] == "/v1/live-data/ltp")
    assert ltp_call["params"] == {"segment": "COMMODITY", "exchange_symbols": "MCX_CRUDEOIL25JANFUT"}
    assert ltp == {"MCX:CRUDEOIL25JANFUT": 2905.5}
    history_call = next(call for call in transport.calls if call["path"] == "/v1/historical/candle/range")
    assert history_call["params"]["exchange"] == "MCX"
    assert history_call["params"]["segment"] == "COMMODITY"
    assert any(order["exchange"] == "MCX" for order in orders)
    list_segments = [
        call["params"]["segment"]
        for call in transport.calls
        if call["path"] == "/v1/order/list"
    ]
    assert list_segments == ["CASH", "FNO", "COMMODITY"]


@pytest.mark.asyncio
async def test_expired_token_maps_to_session_expired() -> None:
    transport = MockGrowwTransport()
    transport.expired = True
    adapter = _adapter(transport)
    session = await _session(adapter)
    with pytest.raises(SessionExpired):
        await adapter.funds(session)


@pytest.mark.asyncio
async def test_market_data_forbidden_does_not_expire_session() -> None:
    transport = MockGrowwTransport()
    transport.forbid_market_data = True
    adapter = _adapter(transport)
    session = await _session(adapter)

    assert await adapter.funds(session)
    with pytest.raises(DataError, match="market-data access is not enabled"):
        await adapter.quotes(session, ["NSE:RELIANCE"])
